//! cbus-tools: decode | dump-labels | interrogate
//! Ports of `cbus/tools/decode_packet.py`, `cbus/toolkit/dump_labels.py`
//! and `cbus/protocol/interrogator.py`.

use cbus_protocol::cal::Cal;
use cbus_protocol::decode::decode_packet;
use cbus_protocol::json::packet_to_json;
use cbus_protocol::packet::Packet;
use clap::{Parser, Subcommand};
use serde_json::{json, Map, Value};
use std::path::PathBuf;

#[derive(Parser)]
#[command(name = "cbus-tools", about = "C-Bus debugging tools (Rust port)")]
struct Cli {
    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand)]
enum Command {
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
    /// Dump group address and unit metadata from a Toolkit CBZ as JSON
    DumpLabels {
        /// Toolkit backup (.cbz or .xml)
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
}

fn main() {
    let cli = Cli::parse();
    match cli.command {
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
    }
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

/// Port of `toolkit/dump_labels.py`: full CBZ walk (networks, applications,
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
            // "0x38 0xFF" -> [0x38, 0xFF] (dump_labels.py:89-105)
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

/// (identify?, attribute, recall-count) — `_INTERROGATION_ATTRS` +
/// `_RECALL_COUNTS` from `protocol/interrogator.py`.
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
