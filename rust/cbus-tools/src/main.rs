//! `cbus-tools`: frame decoding, CBZ label export, and unit interrogation.

use cbus_protocol::cal::Cal;
use cbus_protocol::decode::decode_packet;
use cbus_protocol::json::packet_to_json;
use cbus_protocol::packet::Packet;
use cbus_transport::apply::{load_recovery, ApplyError, ApplyOnce, ApplyOptions};
use cbus_transport::conn::Endpoint;
use cbus_transport::inventory::InventoryOptions;
use cbus_transport::plan::{validate_plan_document_with_value, ValidatedPlan, MAX_PLAN_BYTES};
use cbus_transport::verify::{
    extract_snapshots, verify_plan, VerifyEvidence, VerifyOptions, VerifyOutcome,
};
use cbus_transport::{conn, PciClient};
use clap::{Parser, Subcommand};
use serde_json::{json, Map, Value};
use std::io::Read;
use std::net::{Ipv4Addr, SocketAddrV4};
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::Duration;

#[derive(Parser)]
#[command(name = "cbus-tools", about = "C-Bus debugging tools")]
struct Cli {
    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand)]
enum Command {
    /// Discover CNI2/Wiser interfaces with one bounded UDP query
    CniDiscover {
        /// Local IPv4 address to bind
        #[arg(long, default_value = "0.0.0.0")]
        bind: Ipv4Addr,
        /// Local UDP port; 0 selects an ephemeral port
        #[arg(long, default_value_t = cbus_protocol::cni_discovery::DISCOVERY_PORT)]
        listen_port: u16,
        /// Broadcast or unicast IPv4 destination
        #[arg(long, default_value = "255.255.255.255")]
        destination: Ipv4Addr,
        /// Destination UDP port
        #[arg(long, default_value_t = cbus_protocol::cni_discovery::DISCOVERY_PORT)]
        discovery_port: u16,
        /// Total reply window in seconds, in (0, 300]
        #[arg(long, default_value_t = 2.0)]
        timeout: f64,
        /// Maximum accepted datagrams before reporting an incomplete result
        #[arg(long, default_value_t = 256)]
        max_datagrams: usize,
        /// Include product-id 2 replies hidden by captured Toolkit behavior
        #[arg(long)]
        include_hidden: bool,
    },
    /// Decode a single C-Bus serial frame (ASCII as seen on the wire)
    Decode {
        /// The frame, e.g. '0538007901490D' or '\\053800790149g'
        packet: String,
        /// Do not require a checksum
        #[arg(short = 'C', long = "no-checksum")]
        no_checksum: bool,
        /// Lenient mode (warn instead of Invalid)
        #[arg(short = 'S', long = "not-strict")]
        not_strict: bool,
        /// Parse as a client->PCI frame (default: PCI->client)
        #[arg(short = 'c', long)]
        client: bool,
    },
    /// Dump group address and unit metadata from a C-Bus project as JSON
    DumpLabels {
        /// C-Bus project backup (.cbz or .xml)
        input: PathBuf,
        /// Write output to FILE (default stdout)
        #[arg(short = 'o', long)]
        output: Option<PathBuf>,
        /// Pretty-print with this many spaces per indent level
        #[arg(short = 'p', long)]
        pretty: Option<usize>,
    },
    /// Read device attributes from C-Bus units via a CNI/PCI
    Interrogate {
        /// CNI address as HOST:PORT
        #[arg(long)]
        tcp: String,
        /// Unit address to interrogate
        #[arg(long)]
        unit: Option<u8>,
        /// Discover units by scanning addresses 0..=MAX (default 37)
        #[arg(long)]
        discover: bool,
        /// Highest address to scan with --discover
        #[arg(long, default_value_t = 37)]
        max_address: u8,
        /// Reply timeout in seconds
        #[arg(long, default_value_t = 5.0)]
        timeout: f64,
    },
    /// Verify live bus state against a selected-serial plan (read-only: no
    /// address command is sent and no journal is written)
    ///
    /// The plan is authoritative: `--pci HOST:PORT` must equal the plan's
    /// embedded endpoint (host and port), verified before any I/O. `--pci`
    /// opens a direct TCP socket and requires exclusive ownership of
    /// the CNI; stop `cmqttd` or any other current owner before running it.
    /// Caller timing replaces plan timing: `--timeout` bounds the whole
    /// observation while plan transport settings are validated but never
    /// enforced. The plan comes from a file (`--plan`) or from the embedded
    /// plan in a recovery journal (`--journal`, resuming verification from
    /// a crashed/interrupted apply without the plan file); exactly one of
    /// the two is required. Journal endpoint binding is identical: `--pci`
    /// must equal the journal's embedded endpoint.
    SerialVerify {
        /// Direct PCI endpoint as numeric IP:PORT (bracket IPv6); must equal
        /// the embedded endpoint and be exclusively available to this command
        #[arg(long)]
        pci: String,
        /// Selected-serial plan file (validated before connecting);
        /// mutually exclusive with --journal
        #[arg(long, conflicts_with = "journal", required_unless_present = "journal")]
        plan: Option<PathBuf>,
        /// Recovery journal from `serial-apply` (embedded plan validated
        /// before connecting); mutually exclusive with --plan
        #[arg(long, conflicts_with = "plan", required_unless_present = "plan")]
        journal: Option<PathBuf>,
        /// Overall observation deadline in seconds, in (0, 3600]
        #[arg(long, default_value_t = 300.0)]
        timeout: f64,
    },
    /// Send exactly one guarded selected-serial address move with a durable
    /// recovery journal (no automatic replay or rollback)
    ///
    /// Same endpoint rule as `serial-verify`: `--pci HOST:PORT` must equal
    /// the plan's embedded endpoint, verified before any I/O. `--pci` opens a
    /// direct TCP socket and requires exclusive ownership of
    /// the CNI; stop `cmqttd` or any other current owner before running it.
    /// The journal must not exist (exclusive creation, checked before connecting);
    /// `--timeout` separately bounds the fresh-before and post-send
    /// observations. The exact one-shot send and its bounded receipt capture
    /// use the same PCI connection as those observations. The journal is
    /// recovery evidence that
    /// also carries the embedded plan, so `serial-verify --journal` can
    /// re-verify from it without the plan file.
    SerialApply {
        /// Direct PCI endpoint as numeric IP:PORT (bracket IPv6); must equal
        /// the plan endpoint and be exclusively available to this command
        #[arg(long)]
        pci: String,
        /// Selected-serial plan file (validated before connecting)
        #[arg(long)]
        plan: PathBuf,
        /// New recovery journal file; must not exist (checked before connecting)
        #[arg(long)]
        journal: PathBuf,
        /// Per-observation deadline in seconds, in (0, 3600]
        #[arg(long, default_value_t = 300.0)]
        timeout: f64,
    },
}

fn main() {
    let cli = Cli::parse();
    match cli.command {
        Command::CniDiscover {
            bind,
            listen_port,
            destination,
            discovery_port,
            timeout,
            max_datagrams,
            include_hidden,
        } => {
            let rt = tokio::runtime::Runtime::new().unwrap();
            if let Err(error) = rt.block_on(cni_discover_cmd(
                bind,
                listen_port,
                destination,
                discovery_port,
                timeout,
                max_datagrams,
                include_hidden,
            )) {
                eprintln!("error: {error}");
                std::process::exit(1);
            }
        }
        Command::Decode {
            packet,
            no_checksum,
            not_strict,
            client,
        } => decode_cmd(&packet, !no_checksum, !not_strict, !client),
        Command::DumpLabels {
            input,
            output,
            pretty,
        } => {
            if let Err(e) = dump_labels(&input, output.as_deref(), pretty) {
                eprintln!("error: {e}");
                std::process::exit(1);
            }
        }
        Command::Interrogate {
            tcp,
            unit,
            discover,
            max_address,
            timeout,
        } => {
            let rt = tokio::runtime::Runtime::new().unwrap();
            if let Err(e) = rt.block_on(interrogate_cmd(&tcp, unit, discover, max_address, timeout))
            {
                eprintln!("error: {e}");
                std::process::exit(1);
            }
        }
        Command::SerialVerify {
            pci,
            plan,
            journal,
            timeout,
        } => {
            let rt = tokio::runtime::Runtime::new().unwrap();
            match rt.block_on(serial_verify_cmd(
                &pci,
                plan.as_deref(),
                journal.as_deref(),
                timeout,
            )) {
                Ok(code) => std::process::exit(code),
                Err(e) => {
                    eprintln!("error: {e}");
                    std::process::exit(1);
                }
            }
        }
        Command::SerialApply {
            pci,
            plan,
            journal,
            timeout,
        } => {
            let rt = tokio::runtime::Runtime::new().unwrap();
            match rt.block_on(serial_apply_cmd(&pci, &plan, &journal, timeout)) {
                Ok(code) => std::process::exit(code),
                Err(e) => {
                    eprintln!("error: {e}");
                    std::process::exit(1);
                }
            }
        }
    }
}

async fn cni_discover_cmd(
    bind: Ipv4Addr,
    listen_port: u16,
    destination: Ipv4Addr,
    discovery_port: u16,
    timeout: f64,
    max_datagrams: usize,
    include_hidden: bool,
) -> Result<(), String> {
    use cbus_transport::cni_discovery::{discover, DiscoveryConfig};

    if !timeout.is_finite() || timeout <= 0.0 || timeout > 300.0 {
        return Err("CNI discovery timeout must be finite and in (0, 300]".to_string());
    }
    let report = discover(&DiscoveryConfig {
        bind: SocketAddrV4::new(bind, listen_port),
        destination: SocketAddrV4::new(destination, discovery_port),
        timeout: Duration::from_secs_f64(timeout),
        max_datagrams,
        include_hidden,
    })
    .await?;
    let devices = report
        .devices
        .iter()
        .map(|item| {
            json!({
                "source_address": item.source.ip().to_string(),
                "source_port": item.source.port(),
                "service_address": item.source.ip().to_string(),
                "service_port": item.reply.service_port,
                "endpoint": format!("{}:{}", item.source.ip(), item.reply.service_port),
                "unknown1_hex": hex::encode(item.reply.unknown1),
                "product_id": item.reply.product_id,
                "product": item.reply.product_name(),
                "visible_by_default": item.reply.visible_by_default(),
                "status_raw": item.reply.status,
                "trailer_hex": hex::encode(item.reply.trailer),
                "raw_hex": hex::encode(&item.raw),
            })
        })
        .collect::<Vec<_>>();
    let malformed = report
        .malformed
        .iter()
        .map(|item| {
            json!({
                "source": item.source.to_string(),
                "raw_hex": hex::encode(&item.raw),
                "error": item.error,
            })
        })
        .collect::<Vec<_>>();
    println!(
        "{}",
        serde_json::to_string_pretty(&json!({
            "format": "cbus-cni-discovery-v1",
            "query_hex": hex::encode(cbus_protocol::cni_discovery::DISCOVERY_QUERY),
            "query_sent_once": true,
            "listen": {"address": report.local.ip().to_string(), "port": report.local.port()},
            "destination": {"address": report.destination.ip().to_string(), "port": report.destination.port()},
            "collection_complete": report.collection_complete,
            "collection_ended": if report.collection_complete {"deadline"} else {"datagram_limit"},
            "datagrams_received": report.datagrams_received,
            "duplicates_ignored": report.duplicates_ignored,
            "hidden_ignored": report.hidden_ignored,
            "devices": devices,
            "malformed": malformed,
            "read_only": true,
            "tcp_connection_opened": false,
            "absence_proven": false,
            "scope": "Captured fixed-layout IPv4 UDP discovery; no TCP reachability, ownership, identity authenticity or physical-network validation",
        }))
        .map_err(|error| format!("Unable to encode CNI discovery report: {error}"))?
    );
    Ok(())
}

// ------------------------------------------------------------------ decode

fn decode_cmd(packet: &str, checksum: bool, strict: bool, from_pci: bool) {
    let mut data = packet.as_bytes().to_vec();
    let (p, consumed) = decode_packet(&data, checksum, strict, from_pci);
    let (p, consumed) = if p.is_none() && consumed == 0 {
        // convenience: retry with the line terminator appended
        data.extend_from_slice(if from_pci { b"\r\n" } else { b"\r" });
        decode_packet(&data, checksum, strict, from_pci)
    } else {
        (p, consumed)
    };
    println!("consumed: {consumed}");
    match &p {
        Some(pkt) => {
            println!("packet: {pkt:#?}");
            println!("json: {}", packet_to_json(Some(pkt)));
        }
        None => println!("packet: None"),
    }
}

// ------------------------------------------------------------- dump-labels

/// Full CBZ walk (networks, applications,
/// groups, units incl. `GroupAddress` PP channel parsing).
fn dump_labels(
    input: &std::path::Path,
    output: Option<&std::path::Path>,
    pretty: Option<usize>,
) -> Result<(), String> {
    use cbus_mqtt::cbz::{children, get_field, load_xml};

    let xml = load_xml(input).map_err(|e| e.to_string())?;
    let doc = roxmltree::Document::parse(&xml).map_err(|e| e.to_string())?;
    let installation = doc.root_element();
    let project = children(installation, "project")
        .into_iter()
        .next()
        .ok_or("no Project element")?;

    let int_field = |node: roxmltree::Node, name: &str| -> Result<i64, String> {
        get_field(node, name)
            .ok_or_else(|| format!("missing {name}"))?
            .trim()
            .parse::<i64>()
            .map_err(|e| format!("bad {name}: {e}"))
    };

    let mut o = Map::new();
    for network in children(project, "network") {
        let net_addr = int_field(network, "address")?;
        let mut apps = Map::new();
        for app in children(network, "application") {
            let addr = int_field(app, "address")?;
            let mut groups = Map::new();
            for group in children(app, "group") {
                let gaddr = int_field(group, "address")?;
                groups.insert(
                    gaddr.to_string(),
                    json!(get_field(group, "tag_name").unwrap_or_default()),
                );
            }
            apps.insert(
                addr.to_string(),
                json!({
                    "name": get_field(app, "tag_name").unwrap_or_default(),
                    "address": addr,
                    "description": get_field(app, "description").unwrap_or_default(),
                    "groups": groups,
                }),
            );
        }
        let mut units = Map::new();
        for unit in children(network, "unit") {
            let addr = int_field(unit, "address")?;
            // channel configuration: `GroupAddress` PP values like
            // "0x38 0xFF" maps to [0x38, 0xFF].
            let mut channels: Vec<i64> = Vec::new();
            for pp in children(unit, "pp") {
                if get_field(pp, "name").as_deref() == Some("GroupAddress") {
                    if let Some(value) = get_field(pp, "value") {
                        for c in value.split(' ') {
                            if c.len() > 2 {
                                if let Ok(v) = i64::from_str_radix(&c[2..], 16) {
                                    channels.push(v);
                                }
                            }
                        }
                    }
                }
            }
            units.insert(
                addr.to_string(),
                json!({
                    "name": get_field(unit, "tag_name").unwrap_or_default(),
                    "address": addr,
                    "unittype": get_field(unit, "unit_type").unwrap_or_default(),
                    "unitname": get_field(unit, "unit_name").unwrap_or_default(),
                    "serial": get_field(unit, "serial_number").unwrap_or_default(),
                    "catalog": get_field(unit, "catalog_number").unwrap_or_default(),
                    "groups": channels,
                }),
            );
        }
        o.insert(
            net_addr.to_string(),
            json!({
                "name": get_field(network, "tag_name").unwrap_or_default(),
                "address": net_addr,
                "networknumber": int_field(network, "network_number").unwrap_or(0),
                "applications": apps,
                "units": units,
            }),
        );
    }

    let value = Value::Object(o);
    let text = match pretty {
        Some(n) => {
            let indent = vec![b' '; n];
            let mut out = Vec::new();
            let fmt = serde_json::ser::PrettyFormatter::with_indent(&indent);
            let mut ser = serde_json::Serializer::with_formatter(&mut out, fmt);
            serde::Serialize::serialize(&value, &mut ser).map_err(|e| e.to_string())?;
            String::from_utf8(out).map_err(|e| e.to_string())?
        }
        None => value.to_string(),
    };
    match output {
        Some(path) => std::fs::write(path, text).map_err(|e| e.to_string())?,
        None => println!("{text}"),
    }
    Ok(())
}

// ------------------------------------------------------------- interrogate

const PP_HEADER: u8 = 0x46;
const CONFIRMATION_CODES: &[u8] = cbus_protocol::common::CONFIRMATION_CODES;

/// `(identify?, attribute, recall-count)` interrogation table.
const INTERROGATION_ATTRS: &[(bool, u8, u8)] = &[
    (true, 0x01, 0),   // TYPE_NAME
    (true, 0x02, 0),   // FIRMWARE_VERSION
    (true, 0x04, 0),   // SERIAL_NUMBER
    (false, 0x10, 4),  // TERMINAL_LEVELS
    (false, 0x3e, 1),  // PARAMETER_AREA
    (false, 0xfa, 44), // INSTALLED_APPS
    (false, 0xfb, 9),  // FIRMWARE_EXTENDED
    (false, 0x20, 12), // GAV_ZONE_DATA
    (false, 0x2c, 12), // GROUP_ADDRESS_TABLE
    (false, 0x23, 6),  // OUTPUT_SUMMARY
    (false, 0x2a, 6),  // GAV_STORE
];

struct Interrogator {
    stream: tokio::net::TcpStream,
    conf_idx: usize,
    timeout: std::time::Duration,
}

impl Interrogator {
    async fn connect(host: &str, port: u16, timeout: f64) -> std::io::Result<Interrogator> {
        let timeout = std::time::Duration::from_secs_f64(timeout);
        let stream = tokio::time::timeout(timeout, tokio::net::TcpStream::connect((host, port)))
            .await
            .map_err(|_| std::io::Error::new(std::io::ErrorKind::TimedOut, "connect timeout"))??;
        let mut me = Interrogator {
            stream,
            conf_idx: 0,
            timeout,
        };
        // `||` smart+connect, then drain any pending output
        me.send_raw(b"||").await?;
        tokio::time::sleep(std::time::Duration::from_millis(100)).await;
        let mut buf = [0u8; 4096];
        let _ = tokio::time::timeout(
            std::time::Duration::from_millis(500),
            tokio::io::AsyncReadExt::read(&mut me.stream, &mut buf),
        )
        .await;
        Ok(me)
    }

    fn next_conf(&mut self) -> u8 {
        let code = CONFIRMATION_CODES[self.conf_idx % CONFIRMATION_CODES.len()];
        self.conf_idx += 1;
        code
    }

    async fn send_raw(&mut self, data: &[u8]) -> std::io::Result<()> {
        use tokio::io::AsyncWriteExt;
        self.stream.write_all(data).await?;
        self.stream.write_all(b"\r").await?;
        self.stream.flush().await
    }

    /// `\46 <unit> 00 <cal bytes>` in uppercase hex + rotating confirmation.
    async fn pp_command(&mut self, unit: u8, cal: &[u8]) -> std::io::Result<Option<Vec<u8>>> {
        let conf = self.next_conf();
        let mut cmd = vec![PP_HEADER, unit, 0x00];
        cmd.extend_from_slice(cal);
        let mut frame = b"\\".to_vec();
        frame.extend(hex::encode_upper(&cmd).into_bytes());
        frame.push(conf);
        self.send_raw(&frame).await?;
        self.read_reply().await
    }

    async fn identify(&mut self, unit: u8, attr: u8) -> std::io::Result<Option<Vec<u8>>> {
        self.pp_command(unit, &[0x21, attr]).await
    }

    async fn recall(&mut self, unit: u8, attr: u8, count: u8) -> std::io::Result<Option<Vec<u8>>> {
        self.pp_command(unit, &[0x1a, attr, count]).await
    }

    /// Read response lines until a reply CAL arrives or timeout.
    async fn read_reply(&mut self) -> std::io::Result<Option<Vec<u8>>> {
        use tokio::io::AsyncReadExt;
        let deadline = tokio::time::Instant::now() + self.timeout;
        let mut buf: Vec<u8> = Vec::new();
        let mut chunk = [0u8; 4096];
        loop {
            let now = tokio::time::Instant::now();
            if now >= deadline {
                return Ok(None);
            }
            let n = match tokio::time::timeout(deadline - now, self.stream.read(&mut chunk)).await {
                Err(_) => return Ok(None),
                Ok(Ok(0)) => return Ok(None),
                Ok(Ok(n)) => n,
                Ok(Err(e)) => return Err(e),
            };
            buf.extend_from_slice(&chunk[..n]);

            while let Some(pos) = buf.windows(2).position(|w| w == b"\r\n") {
                let mut line = buf[..pos].to_vec();
                buf.drain(..pos + 2);
                if line.len() == 2 && line[1] == b'.' {
                    continue; // confirmation
                }
                line.extend_from_slice(b"\r\n");
                let (pkt, _) = decode_packet(&line, true, false, true);
                if let Some(Packet::PointToPoint { cals, .. }) = pkt {
                    for cal in cals {
                        if let Cal::Reply { data, .. } = cal {
                            return Ok(Some(data));
                        }
                    }
                }
            }
        }
    }
}

async fn interrogate_cmd(
    tcp: &str,
    unit: Option<u8>,
    discover: bool,
    max_address: u8,
    timeout: f64,
) -> Result<(), String> {
    let (host, port) = tcp
        .split_once(':')
        .map(|(h, p)| (h.to_string(), p.parse::<u16>().unwrap_or(10001)))
        .unwrap_or((tcp.to_string(), 10001));
    let mut it = Interrogator::connect(&host, port, timeout)
        .await
        .map_err(|e| e.to_string())?;

    if discover {
        for addr in 0..=max_address {
            if let Ok(Some(data)) = it.identify(addr, 0x01).await {
                if !data.iter().all(|&b| b == 0) {
                    let name = String::from_utf8_lossy(&data).trim().to_string();
                    if !name.is_empty() {
                        println!("Unit {addr} (0x{addr:02X}): {name}");
                    }
                }
            }
        }
        return Ok(());
    }

    let unit = unit.ok_or("pass --unit N or --discover")?;
    let mut type_name = String::new();
    let mut firmware = String::new();
    let mut serial: Vec<u8> = Vec::new();
    let mut installed_apps: Vec<u8> = Vec::new();
    for &(is_identify, attr, count) in INTERROGATION_ATTRS {
        let data = if is_identify {
            it.identify(unit, attr).await
        } else {
            it.recall(unit, attr, count).await
        };
        match data {
            Ok(Some(data)) => {
                match attr {
                    0x01 if is_identify => type_name = String::from_utf8_lossy(&data).to_string(),
                    0x02 if is_identify => firmware = String::from_utf8_lossy(&data).to_string(),
                    0x04 if is_identify => serial = data.clone(),
                    0xfa => installed_apps = data.iter().copied().filter(|&b| b != 0xff).collect(),
                    _ => {}
                }
                println!("attr 0x{attr:02X}: {}", hex::encode(&data));
            }
            Ok(None) => println!("attr 0x{attr:02X}: no reply"),
            Err(e) => println!("attr 0x{attr:02X}: error {e}"),
        }
    }
    let apps = installed_apps
        .iter()
        .map(|a| format!("0x{a:02X}"))
        .collect::<Vec<_>>()
        .join(", ");
    println!(
        "Unit {unit} (0x{unit:02X}): {} fw={} serial={} apps=[{apps}]",
        type_name.trim(),
        firmware.trim(),
        hex::encode(&serial),
    );
    Ok(())
}

// ------------------------------------------- serial commissioning (P3e-P3h)

// Exit-code contract (mirrors the oracle `serial-address apply/verify`):
// exit 0 ONLY for `observed_expected_change`, exit 1 for every other
// classified outcome (unchanged / unexpected / uncertain) and for errors.
// Full evidence JSON goes to stdout on every classified observation:
// every verify outcome plus the classified apply failures (preconditions
// and post-send observation, which the journal also records). Hard errors
// (corrupt plan, endpoint mismatch, journal-exists, journal/transport
// failures) go to stderr with exit 1 and empty stdout. Evidence echoes
// the effective (used) timeouts alongside the plan's planned settings so
// caller/plan divergence is auditable; caller timing still replaces plan
// timing exactly as before (no semantic change).
// Clap usage errors keep their exit code 2. Ctrl-C kills the process with
// the shell's usual 130-ish status; no cleanup beyond socket close.

/// Per-address IDENTIFY4 probe budget for the fresh observation.
const SERIAL_PROBE_TIMEOUT: Duration = Duration::from_secs(30);

/// Strict numeric-IP endpoint parse for the caller-owned PCI.
fn parse_pci(spec: &str) -> Result<std::net::SocketAddr, String> {
    spec.parse::<std::net::SocketAddr>()
        .map_err(|_| format!("pci: expected numeric IP:PORT (bracket IPv6), got {spec:?}"))
}

/// Endpoint binding: the CLI `--pci` endpoint must equal the plan's
/// embedded endpoint (host and port). The plan is authoritative; a mismatch
/// is refused before any I/O, mirroring the oracle coordinator/plan match.
fn check_endpoint(endpoint: std::net::SocketAddr, plan: &ValidatedPlan) -> Result<(), String> {
    let plan_ip = plan
        .host
        .parse::<std::net::IpAddr>()
        .map_err(|_| "plan endpoint is not a numeric IP address".to_string())?;
    if endpoint.ip() != plan_ip || endpoint.port() != plan.port {
        return Err(format!(
            "endpoint mismatch: --pci {endpoint} does not match plan endpoint {}:{}; the plan is authoritative",
            plan.host, plan.port
        ));
    }
    Ok(())
}

fn check_timeout(timeout: f64) -> Result<Duration, String> {
    if timeout.is_finite() && timeout > 0.0 && timeout <= 3600.0 {
        Ok(Duration::from_secs_f64(timeout))
    } else {
        Err(format!(
            "timeout must be finite and in (0, 3600] seconds, got {timeout}"
        ))
    }
}

/// Read, validate, and snapshot-check the plan document with no I/O, then
/// bind the CLI endpoint to the plan's embedded endpoint. Every corruption
/// class (bad JSON, failed validation, missing snapshots) is rejected here,
/// before any connection is attempted.
fn load_plan_for_cli(
    plan_path: &Path,
    pci_spec: &str,
    timeout: f64,
) -> Result<(Vec<u8>, ValidatedPlan, Duration), String> {
    let total_deadline = check_timeout(timeout)?;
    let file = std::fs::File::open(plan_path)
        .map_err(|e| format!("plan: cannot read {}: {e}", plan_path.display()))?;
    let mut raw = Vec::new();
    file.take(MAX_PLAN_BYTES as u64 + 1)
        .read_to_end(&mut raw)
        .map_err(|e| format!("plan: cannot read {}: {e}", plan_path.display()))?;
    if raw.len() > MAX_PLAN_BYTES {
        return Err(format!(
            "plan: {} exceeds the {}-byte plan bound",
            plan_path.display(),
            MAX_PLAN_BYTES
        ));
    }
    let (plan, document) = validate_plan_document_with_value(&raw)
        .map_err(|e| format!("plan: invalid plan document: {e}"))?;
    // Snapshot extraction is part of "corrupt plan" rejection: a plan whose
    // embedded before/expected snapshots cannot be read must fail before
    // connecting, not after a wasted observation.
    extract_snapshots(&document)
        .map_err(|e| format!("plan: invalid plan document: snapshot: {}", e.message()))?;
    check_endpoint(parse_pci(pci_spec)?, &plan)?;
    let sanitized = serde_json::to_vec(&document)
        .map_err(|e| format!("plan: cannot encode validated plan document: {e}"))?;
    Ok((sanitized, plan, total_deadline))
}

/// Read, strictly revalidate, and snapshot-check the embedded plan in a
/// recovery journal with no I/O, then bind the CLI endpoint to the
/// journal's embedded endpoint. The library `load_recovery` is the bounded
/// guarded gate (symlink/non-regular refusal, size bound, strict
/// embedded-plan validation); the embedded plan bytes are then pinned from
/// the journal for `verify_plan` (which revalidates them) and re-checked
/// here, so the exact bytes used are the bytes bound to `--pci`. Every
/// corruption class (unreadable journal, corrupt envelope, wrong format,
/// missing/unvalidatable embedded plan, missing snapshots, endpoint
/// mismatch) is rejected here, before any connection is attempted.
fn load_journal_for_cli(
    journal_path: &Path,
    pci_spec: &str,
    timeout: f64,
) -> Result<(Vec<u8>, ValidatedPlan, Duration), String> {
    let total_deadline = check_timeout(timeout)?;
    // One bounded guarded read returns both the strictly revalidated plan and
    // the same journal evidence; do not reopen the path and introduce a
    // substitution or unbounded-read window.
    let recovery = load_recovery(journal_path).map_err(|e| e.to_string())?;
    let plan_value: Value = serde_json::from_slice(&recovery.plan_document)
        .map_err(|e| format!("journal: invalid embedded plan: {e}"))?;
    extract_snapshots(&plan_value)
        .map_err(|e| format!("journal: invalid embedded plan: snapshot: {}", e.message()))?;
    check_endpoint(parse_pci(pci_spec)?, &recovery.plan)?;
    Ok((recovery.plan_document, recovery.plan, total_deadline))
}

/// Connect the caller-owned PCI endpoint and run the fixed init sequence,
/// mirroring the deployed `connection_made` -> `pci_reset` order.
async fn connect_pci(host: String, port: u16) -> Result<Arc<PciClient>, String> {
    let endpoint = Endpoint::Tcp { host, port };
    let (rd, wr) = conn::connect(&endpoint)
        .await
        .map_err(|e| format!("connect: {e}"))?;
    let (ev_tx, _ev_rx) = tokio::sync::mpsc::unbounded_channel();
    let pci = PciClient::new(rd, wr, ev_tx);
    pci.pci_reset()
        .await
        .map_err(|e| format!("pci_reset: {e}"))?;
    Ok(pci)
}

fn verify_options(total_deadline: Duration) -> VerifyOptions {
    VerifyOptions {
        inventory: InventoryOptions {
            per_address_timeout: SERIAL_PROBE_TIMEOUT,
            total_deadline,
        },
    }
}

/// Effective-vs-planned timeouts for the evidence JSON.
///
/// `used` carries the caller-owned values actually enforced for each
/// inventory observation (the fixed per-address probe budget plus the
/// `--timeout` total); `planned` echoes the plan's own `settings` verbatim so
/// any divergence is auditable. Caller observation timing replaces plan
/// timing.
fn timeouts_json(raw: &[u8], total_deadline: Duration) -> Value {
    let planned: Value = serde_json::from_slice(raw)
        .ok()
        .and_then(|doc: Value| doc.get("settings").cloned())
        .unwrap_or(Value::Null);
    let used = json!({
        "verify_per_address_secs": SERIAL_PROBE_TIMEOUT.as_secs_f64(),
        "verify_total_secs": total_deadline.as_secs_f64(),
    });
    json!({ "used": used, "planned": planned })
}

/// Read-only evidence JSON mirroring the library [`VerifyEvidence`] shape:
/// outcome plus per-address diffs against the embedded expectation.
fn verify_json(
    plan: &ValidatedPlan,
    evidence: &VerifyEvidence,
    raw: &[u8],
    total_deadline: Duration,
) -> Value {
    let mut value = json!({
        "format": "cbus-selected-serial-verify-v1",
        "operation": "verify",
        "outcome": evidence.outcome.as_str(),
        "expected_identity_change": evidence.expected_identity_change,
        "unexpected_changes": evidence.unexpected_changes.iter().map(|diff| json!({
            "address": diff.address,
            "expected_serials": diff.expected_serials,
            "observed_serials": diff.observed_serials,
            "expected_state": diff.expected_state,
            "observed_state": diff.observed_state,
        })).collect::<Vec<_>>(),
        "after_collection_complete": evidence.after_collection_complete,
        "errors": evidence.errors,
        "atomic_observation": evidence.atomic_observation,
        "firmware_persistence_verified": evidence.firmware_persistence_verified,
        "physical_compatibility_verified": evidence.physical_compatibility_verified,
        "exclusive_ownership_required": evidence.exclusive_ownership_required,
        "movement_verified": evidence.movement_verified,
        "persistence_verified": evidence.persistence_verified,
        "plan_transport_settings_enforced": evidence.plan_transport_settings_enforced,
        "endpoint_binding_verified": evidence.endpoint_binding_verified,
        "local_serial_binding_verified": evidence.local_serial_binding_verified,
        "raw_transport_evidence_verified": evidence.raw_transport_evidence_verified,
        "underlying_read_retries_possible": evidence.underlying_read_retries_possible,
        "whole_operation_replays": evidence.whole_operation_replays,
        "non_commissioning_traffic_may_interleave": evidence.non_commissioning_traffic_may_interleave,
        "wire_quiescence_after_return_verified": evidence.wire_quiescence_after_return_verified,
        "discard_client_after_deadline_or_cancellation": evidence.discard_client_after_deadline_or_cancellation,
        "endpoint_binding_cli_verified": true,
        "plan": {
            "serial": plan.serial,
            "destination": plan.destination,
            "local_unit": plan.local_unit,
            "endpoint": {"host": plan.host, "port": plan.port},
        },
        "endpoint": {"host": plan.host, "port": plan.port},
    });
    value["timeouts"] = timeouts_json(raw, total_deadline);
    value
}

/// Classified apply-failure evidence mirroring the verify shape.
///
/// `Preconditions` (no journal, no send) and `PostSendObservation` (the
/// journal holds the after-observation) are classified outcomes, not hard
/// errors, so they print to stdout exactly like verify evidence while the
/// process still exits 1. Post-send per-address diffs are recovered from the
/// journal when an observation completed.
#[allow(clippy::too_many_arguments)]
fn apply_failure_json(
    plan: &ValidatedPlan,
    raw: &[u8],
    total_deadline: Duration,
    outcome: &str,
    after_collection_complete: Option<bool>,
    errors: Vec<String>,
    unexpected_changes: Value,
    journal_path: Option<&Path>,
    receipt_matched: Value,
) -> Value {
    let mut value = json!({
        "format": "cbus-selected-serial-apply-v1",
        "operation": "apply",
        "outcome": outcome,
        "expected_identity_change": outcome == VerifyOutcome::ObservedExpectedChange.as_str(),
        "unexpected_changes": unexpected_changes,
        "after_collection_complete": after_collection_complete,
        "errors": errors,
        "atomic_observation": false,
        "firmware_persistence_verified": false,
        "physical_compatibility_verified": false,
        "exclusive_ownership_required": true,
        "movement_verified": false,
        "persistence_verified": false,
        "plan_transport_settings_enforced": false,
        "endpoint_binding_verified": false,
        "local_serial_binding_verified": false,
        "raw_transport_evidence_verified": false,
        "underlying_read_retries_possible": true,
        "whole_operation_replays": 0,
        "non_commissioning_traffic_may_interleave": true,
        "wire_quiescence_after_return_verified": false,
        "discard_client_after_deadline_or_cancellation": true,
        "endpoint_binding_cli_verified": true,
        "plan": {
            "serial": plan.serial,
            "destination": plan.destination,
            "local_unit": plan.local_unit,
            "endpoint": {"host": plan.host, "port": plan.port},
        },
        "endpoint": {"host": plan.host, "port": plan.port},
        "serial": plan.serial,
        "destination": plan.destination,
        "receipt_matched": receipt_matched,
        "journal": journal_path.map(|path| path.to_string_lossy().into_owned()),
    });
    value["timeouts"] = timeouts_json(raw, total_deadline);
    value
}

async fn serial_verify_cmd(
    pci: &str,
    plan_path: Option<&Path>,
    journal_path: Option<&Path>,
    timeout: f64,
) -> Result<i32, String> {
    let (raw, plan, total_deadline, journal) = match (plan_path, journal_path) {
        (Some(plan_path), None) => {
            let (raw, plan, total_deadline) = load_plan_for_cli(plan_path, pci, timeout)?;
            (raw, plan, total_deadline, None)
        }
        (None, Some(journal_path)) => {
            let (raw, plan, total_deadline) = load_journal_for_cli(journal_path, pci, timeout)?;
            (raw, plan, total_deadline, Some(journal_path))
        }
        // Unreachable via the CLI (clap enforces exactly one of --plan /
        // --journal); defense-in-depth for direct callers.
        _ => {
            return Err("either --plan or --journal is required (mutually exclusive)".to_string());
        }
    };
    let pci_client = connect_pci(plan.host.clone(), plan.port).await?;
    // Local PCI IDENTIFY replies are bare CAL frames, so correlation needs the
    // validated plan address even though this hint does not establish physical
    // identity by itself. Apply installs the same hint before its observations.
    pci_client
        .set_local_unit_hint(plan.local_unit)
        .map_err(|e| format!("local PCI unit: {e}"))?;
    let evidence = verify_plan(&raw, &pci_client, verify_options(total_deadline))
        .await
        .map_err(|e| format!("verify: {e}"))?;
    let expected = evidence.outcome == VerifyOutcome::ObservedExpectedChange;
    let mut value = verify_json(&plan, &evidence, &raw, total_deadline);
    if let Some(journal_path) = journal {
        value["journal"] = Value::from(journal_path.to_string_lossy().into_owned());
    }
    println!("{value}");
    Ok(i32::from(!expected))
}

async fn serial_apply_cmd(
    pci: &str,
    plan_path: &Path,
    journal_path: &Path,
    timeout: f64,
) -> Result<i32, String> {
    let (raw, plan, total_deadline) = load_plan_for_cli(plan_path, pci, timeout)?;
    // Exclusive journal creation is checked before connecting (the library's
    // `O_CREAT | O_EXCL` remains as defense-in-depth for races and restarts).
    if journal_path.exists() || journal_path.is_symlink() {
        return Err(format!(
            "journal: output already exists: {}",
            journal_path.display()
        ));
    }
    if let Some(parent) = journal_path.parent().filter(|p| !p.as_os_str().is_empty()) {
        if !parent.is_dir() {
            return Err(format!(
                "journal: output directory does not exist: {}",
                parent.display()
            ));
        }
    }
    let pci_client = connect_pci(plan.host.clone(), plan.port).await?;
    // Bind the plan's local address hint for correlated receipt parsing. The
    // inventory still checks the pinned serial independently; this hint alone
    // does not establish physical identity.
    pci_client
        .set_local_unit_hint(plan.local_unit)
        .map_err(|e| format!("local PCI unit: {e}"))?;
    let once_ = ApplyOnce::new(&raw);
    match once_
        .apply(
            &pci_client,
            journal_path,
            ApplyOptions {
                verify: verify_options(total_deadline),
            },
        )
        .await
    {
        Ok(success) => {
            let mut evidence = verify_json(&plan, &success.verify, &raw, total_deadline);
            evidence["format"] = Value::from("cbus-selected-serial-apply-v1");
            evidence["operation"] = Value::from("apply");
            evidence["serial"] = Value::from(success.serial);
            evidence["destination"] = Value::from(success.destination);
            evidence["receipt_matched"] = Value::from(success.receipt_matched);
            evidence["journal"] = Value::from(success.journal_path.to_string_lossy().into_owned());
            println!("{evidence}");
            // Exit 0 ONLY on the expected change, exactly like verify:
            // even on `Ok`, a non-expected outcome (should the library ever
            // return one) must exit 1.
            Ok(i32::from(
                success.verify.outcome != VerifyOutcome::ObservedExpectedChange,
            ))
        }
        Err(ApplyError::Preconditions(detail)) => {
            let evidence = apply_failure_json(
                &plan,
                &raw,
                total_deadline,
                "preconditions_failed",
                Some(false),
                vec![format!("apply: preconditions: {detail}")],
                Value::Array(Vec::new()),
                None,
                Value::Null,
            );
            println!("{evidence}");
            Ok(1)
        }
        Err(ApplyError::PostSendObservation(detail)) => {
            // The library journaled the after-observation before failing;
            // surface its classification on stdout in the verify shape.
            let journal = load_recovery(journal_path)
                .ok()
                .map(|record| record.evidence);
            let outcome = journal
                .as_ref()
                .and_then(|j| j.get("after_outcome"))
                .and_then(Value::as_str)
                .unwrap_or(VerifyOutcome::Uncertain.as_str())
                .to_string();
            let after_collection_complete = journal
                .as_ref()
                .and_then(|j| j.get("after_collection_complete"))
                .and_then(Value::as_bool);
            let mut errors = vec![format!("apply: post_send_observation: {detail}")];
            if let Some(after_errors) = journal
                .as_ref()
                .and_then(|j| j.get("after_errors"))
                .and_then(Value::as_array)
            {
                errors.extend(
                    after_errors
                        .iter()
                        .filter_map(Value::as_str)
                        .map(str::to_string),
                );
            }
            let receipt_matched = journal
                .as_ref()
                .and_then(|j| j.get("receipt_matched"))
                .cloned()
                .unwrap_or(Value::Null);
            let unexpected_changes = journal
                .as_ref()
                .and_then(|j| j.get("after_unexpected_changes"))
                .filter(|value| value.is_array())
                .cloned()
                .unwrap_or_else(|| Value::Array(Vec::new()));
            let evidence = apply_failure_json(
                &plan,
                &raw,
                total_deadline,
                &outcome,
                after_collection_complete,
                errors,
                unexpected_changes,
                Some(journal_path),
                receipt_matched,
            );
            println!("{evidence}");
            Ok(1)
        }
        Err(e) => Err(format!("apply: {e}")),
    }
}
