//! Native-compatible C-Gate `PORT` discovery, enumeration, and probe family.
//!
//! The UDP layouts and response grammar are retained from C-Gate 3.4 build
//! 2001. Discovery is explicitly invoked by an authenticated command client;
//! no background scan is performed.

use crate::{err, Response};
use cbus_protocol::cni_discovery::{
    build_cni2_discovery_query, decode_cni2_discovery_reply, decode_legacy_discovery_reply,
    CNI2_DISCOVERY_PORT, LEGACY_DISCOVERY_PORT, LEGACY_DISCOVERY_QUERY,
};
use cbus_transport::{
    conn::{Endpoint, ESP32_DEFAULT_BAUD},
    pci::{BoxedRead, BoxedWrite},
};
use std::{
    io,
    net::{IpAddr, Ipv4Addr, SocketAddr},
    sync::atomic::{AtomicU32, Ordering},
    time::{Duration, SystemTime, UNIX_EPOCH},
};
use tokio::{
    io::{AsyncRead, AsyncReadExt, AsyncWrite, AsyncWriteExt},
    net::{lookup_host, TcpStream, UdpSocket},
};
use tokio_serial::SerialPort as _;

pub(crate) const HELP: &[&str] = &[
    "Help: PORT commands:",
    "Help:  PORT ? Help for these commands",
    "Help:  PORT CNISCAN - Scan an IP address range for C-Bus Network Interfaces",
    "Help:  PORT CNISCAN2 - Scan an IP address range for C-Bus Network Interfaces",
    "Help:  PORT IFLIST - Return a list of IP interfaces on the C-Gate server",
    "Help:  PORT LIST - Return a list of local serial ports",
    "Help:  PORT PROBE - Probe a port for a C-Bus network connection",
    "Help:  PORT REFRESH - Refresh the known local serial ports",
];

const LEGACY_SCAN_TIME: Duration = Duration::from_secs(3);
const CNI2_SCAN_TIME: Duration = Duration::from_secs(5);
const LEGACY_CONNECT_TIME: Duration = Duration::from_secs(3);
const PROBE_CONNECT_TIME: Duration = Duration::from_secs(20);
const MAX_SCAN_DATAGRAMS: usize = 4096;

static NEXT_SEQUENCE: AtomicU32 = AtomicU32::new(0);

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct ScanArgs {
    pub interface: Option<String>,
    pub destination: String,
    pub fast: bool,
}

fn response(tag: &str, status: u16, mut rows: Vec<String>, empty: &str) -> Response {
    if rows.is_empty() {
        return Response {
            tag: tag.to_string(),
            lines: Vec::new(),
            final_text: format!("{status} {empty}"),
            status,
        };
    }
    let final_row = rows.pop().expect("checked nonempty");
    Response {
        tag: tag.to_string(),
        lines: rows,
        final_text: format!("{status} {final_row}"),
        status,
    }
}

pub(crate) fn help(tag: &str) -> Response {
    let mut rows = HELP
        .iter()
        .map(|row| (*row).to_string())
        .collect::<Vec<_>>();
    let final_row = rows.pop().expect("PORT help is nonempty");
    Response {
        tag: tag.to_string(),
        lines: rows,
        final_text: format!("101 {final_row}"),
        status: 101,
    }
}

/// Reproduce the two native scanners' unusual optional-`FAST` consumption.
/// The optional comparison consumes a non-matching token, while a matched
/// `FAST` consumes one further token before checking for leftovers.
pub(crate) fn parse_scan_args(words: &[&str], cni2: bool) -> Option<ScanArgs> {
    let args = words.get(2..)?;
    if cni2 {
        let mut position = 0;
        let interface = args.get(position).map(|value| {
            position += 1;
            (*value).to_string()
        });
        let mut candidate = args.get(position).copied();
        if candidate.is_some() {
            position += 1;
        }
        let mut fast = false;
        if candidate.is_some_and(|value| value.eq_ignore_ascii_case("fast")) {
            candidate = args.get(position).copied();
            if candidate.is_some() {
                position += 1;
            }
            fast = true;
        }
        let destination = candidate.unwrap_or("255.255.255.255").to_string();
        if !fast {
            let next = args.get(position).copied();
            if next.is_some() {
                position += 1;
            }
            if next.is_some_and(|value| value.eq_ignore_ascii_case("fast")) {
                // Native nextArg() consumes one token after a matched FAST.
                if args.get(position).is_some() {
                    position += 1;
                }
                fast = true;
            }
        }
        (position == args.len()).then_some(ScanArgs {
            interface,
            destination,
            fast,
        })
    } else {
        let mut position = 0;
        let mut candidate = args.get(position).copied();
        if candidate.is_some() {
            position += 1;
        }
        let mut fast = false;
        if candidate.is_some_and(|value| value.eq_ignore_ascii_case("fast")) {
            candidate = args.get(position).copied();
            if candidate.is_some() {
                position += 1;
            }
            fast = true;
        }
        let destination = candidate.unwrap_or("255.255.255.255").to_string();
        if !fast {
            let next = args.get(position).copied();
            if next.is_some() {
                position += 1;
            }
            if next.is_some_and(|value| value.eq_ignore_ascii_case("fast")) {
                if args.get(position).is_some() {
                    position += 1;
                }
                fast = true;
            }
        }
        (position == args.len()).then_some(ScanArgs {
            interface: None,
            destination,
            fast,
        })
    }
}

fn seed_sequence() -> u32 {
    let current = NEXT_SEQUENCE.load(Ordering::Relaxed);
    if current != 0 {
        return NEXT_SEQUENCE.fetch_add(1, Ordering::Relaxed);
    }
    let seed = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .subsec_nanos()
        & 0x0fff_ffff;
    let seed = seed.max(1);
    let _ = NEXT_SEQUENCE.compare_exchange(0, seed, Ordering::Relaxed, Ordering::Relaxed);
    NEXT_SEQUENCE.fetch_add(1, Ordering::Relaxed)
}

async fn ipv4(value: &str, purpose: &str) -> io::Result<Ipv4Addr> {
    if let Ok(address) = value.parse::<Ipv4Addr>() {
        return Ok(address);
    }
    lookup_host((value, 0))
        .await?
        .find_map(|address| match address.ip() {
            IpAddr::V4(address) => Some(address),
            IpAddr::V6(_) => None,
        })
        .ok_or_else(|| {
            io::Error::new(
                io::ErrorKind::AddrNotAvailable,
                format!("{purpose} has no IPv4 address"),
            )
        })
}

fn legacy_lookup_error(value: &str, interface: bool, error: io::Error) -> io::Error {
    let message = if interface {
        // Java UnknownHostException returns the requested interface token.
        format!("Can not send via interface: {value}")
    } else {
        let detail = error.to_string();
        let detail = detail
            .strip_prefix("failed to lookup address information: ")
            .unwrap_or(&detail);
        if detail.contains(value) {
            format!("Can not send to network: {detail}")
        } else {
            format!("Can not send to network: {value}: {detail}")
        }
    };
    io::Error::new(error.kind(), message)
}

async fn scan_legacy(args: &ScanArgs) -> io::Result<Vec<String>> {
    let bind_ip = match args.interface.as_deref() {
        Some(value) => ipv4(value, "scan interface")
            .await
            .map_err(|error| legacy_lookup_error(value, true, error))?,
        None => Ipv4Addr::UNSPECIFIED,
    };
    let destination = ipv4(&args.destination, "scan destination")
        .await
        .map_err(|error| legacy_lookup_error(&args.destination, false, error))?;
    let socket = UdpSocket::bind((bind_ip, LEGACY_DISCOVERY_PORT))
        .await
        .map_err(|error| {
            io::Error::new(error.kind(), format!("Can not send to network: {error}"))
        })?;
    socket.set_broadcast(true).map_err(|error| {
        io::Error::new(error.kind(), format!("Can not send to network: {error}"))
    })?;
    socket
        .send_to(
            &LEGACY_DISCOVERY_QUERY,
            SocketAddr::new(IpAddr::V4(destination), LEGACY_DISCOVERY_PORT),
        )
        .await
        .map_err(|error| io::Error::new(error.kind(), "Can not send to network"))?;
    let deadline = tokio::time::Instant::now() + LEGACY_SCAN_TIME;
    let mut rows = Vec::new();
    let mut buffer = [0u8; 512];
    for _ in 0..MAX_SCAN_DATAGRAMS {
        let received = match tokio::time::timeout_at(deadline, socket.recv_from(&mut buffer)).await
        {
            Ok(Ok(received)) => received,
            Ok(Err(error)) => {
                return Err(io::Error::new(
                    error.kind(),
                    format!("Can not receive from network: {error}"),
                ))
            }
            Err(_) => break,
        };
        let (length, source) = received;
        let Ok(reply) = decode_legacy_discovery_reply(&buffer[..length]) else {
            continue;
        };
        let status = if args.fast {
            "unknown"
        } else if tokio::time::timeout(
            LEGACY_CONNECT_TIME,
            TcpStream::connect(SocketAddr::new(source.ip(), reply.service_port)),
        )
        .await
        .is_ok_and(|result| result.is_ok())
        {
            "available"
        } else {
            "unknown"
        };
        rows.push(format!(
            "ip-address={} status={status} port={} type=CNI",
            source.ip(),
            reply.service_port
        ));
    }
    Ok(rows)
}

async fn scan_cni2(args: &ScanArgs) -> io::Result<Vec<String>> {
    let bind_ip = match args.interface.as_deref() {
        Some(value) => ipv4(value, "scan interface").await?,
        None => Ipv4Addr::UNSPECIFIED,
    };
    let destination = ipv4(&args.destination, "scan destination").await?;
    let socket = UdpSocket::bind((bind_ip, CNI2_DISCOVERY_PORT)).await?;
    socket.set_broadcast(true)?;
    let query = build_cni2_discovery_query(seed_sequence());
    socket
        .send_to(
            &query,
            SocketAddr::new(IpAddr::V4(destination), CNI2_DISCOVERY_PORT),
        )
        .await?;
    let deadline = tokio::time::Instant::now() + CNI2_SCAN_TIME;
    let mut rows = Vec::new();
    let mut buffer = [0u8; 512];
    for _ in 0..MAX_SCAN_DATAGRAMS {
        let received = match tokio::time::timeout_at(deadline, socket.recv_from(&mut buffer)).await
        {
            Ok(Ok(received)) => received,
            Ok(Err(error)) => return Err(error),
            Err(_) => break,
        };
        let (length, source) = received;
        let IpAddr::V4(source_ip) = source.ip() else {
            continue;
        };
        let Ok(reply) = decode_cni2_discovery_reply(&buffer[..length], source_ip) else {
            continue;
        };
        rows.push(format!(
            "ip-address={} status={} port={} type={} mac={} serial={} cbus-unit-address={}",
            reply.ip_address,
            reply.status_name(),
            reply.service_port.unwrap_or(0),
            reply.product_name(),
            reply.mac_string().unwrap_or_else(|| "null".to_string()),
            reply
                .serial_number
                .map(|serial| serial.cgate_string())
                .unwrap_or_else(|| "null".to_string()),
            reply.cbus_unit_address.unwrap_or(0)
        ));
    }
    Ok(rows)
}

fn serial_name(path: &str) -> &str {
    path.strip_prefix("/dev/").unwrap_or(path)
}

async fn endpoints_equal(left: &Endpoint, right: &Endpoint) -> bool {
    match (left, right) {
        (Endpoint::Tcp { host: lh, port: lp }, Endpoint::Tcp { host: rh, port: rp }) => {
            if lp != rp {
                return false;
            }
            if lh.eq_ignore_ascii_case(rh) {
                return true;
            }
            let left_addresses = lookup_host((lh.as_str(), *lp)).await;
            let right_addresses = lookup_host((rh.as_str(), *rp)).await;
            match (left_addresses, right_addresses) {
                (Ok(left), Ok(right)) => {
                    let left = left.map(|address| address.ip()).collect::<Vec<_>>();
                    right
                        .map(|address| address.ip())
                        .any(|address| left.contains(&address))
                }
                _ => false,
            }
        }
        (Endpoint::Serial { device: ld, .. }, Endpoint::Serial { device: rd, .. }) => {
            serial_name(ld).eq_ignore_ascii_case(serial_name(rd))
        }
        _ => false,
    }
}

/// Native `CBusSocketNetwork` tokenizes on `:` and uses port zero when the
/// second token is absent or non-numeric. Additional tokens are ignored.
fn tcp_endpoint(address: &str) -> Result<Endpoint, String> {
    let mut tokens = address.split(':').filter(|token| !token.is_empty());
    let host = tokens.next().unwrap_or(address);
    let port = match tokens.next() {
        Some(port) => match port.parse::<i32>() {
            Ok(port) if (0..=i32::from(u16::MAX)).contains(&port) => port as u16,
            Ok(_) => return Err("Bad host or port number".to_string()),
            Err(_) => 0,
        },
        None => 0,
    };
    Ok(Endpoint::Tcp {
        host: host.to_string(),
        port,
    })
}

fn serial_endpoint(address: &str) -> Endpoint {
    #[cfg(unix)]
    let device = if address.starts_with('/') {
        address.to_string()
    } else {
        format!("/dev/{address}")
    };
    #[cfg(not(unix))]
    let device = address.to_string();
    Endpoint::Serial {
        device,
        baud: ESP32_DEFAULT_BAUD,
    }
}

#[derive(Debug, Clone, PartialEq)]
struct ProbeTarget {
    endpoint: Endpoint,
    etherlite_port: Option<u32>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct ProbeTargetError {
    status: u16,
    response: String,
}

impl ProbeTargetError {
    fn operation(message: impl AsRef<str>) -> Self {
        Self {
            status: 408,
            response: format!("408 Operation failed: {}", message.as_ref()),
        }
    }

    fn internal() -> Self {
        Self {
            status: 500,
            response: "500 Internal error.".to_string(),
        }
    }
}

fn probe_target(kind: &str, address: &str) -> Result<ProbeTarget, ProbeTargetError> {
    match kind.to_ascii_lowercase().as_str() {
        "serial" => Ok(ProbeTarget {
            endpoint: serial_endpoint(address),
            etherlite_port: None,
        }),
        "socket" | "cni" | "wiser" => Ok(ProbeTarget {
            endpoint: tcp_endpoint(address).map_err(ProbeTargetError::operation)?,
            etherlite_port: None,
        }),
        "etherlite" => {
            // Native uses StringTokenizer. A missing second token escapes its
            // command handler as the retained 500, while a malformed or
            // negative token is a normal CBusNetworkNoPortException.
            let mut tokens = address.split(':').filter(|token| !token.is_empty());
            let host = tokens.next().ok_or_else(ProbeTargetError::internal)?;
            let port_index = tokens.next().ok_or_else(ProbeTargetError::internal)?;
            let port_index = port_index
                .parse::<i32>()
                .ok()
                .filter(|port| *port >= 0)
                .map(|port| port as u32)
                .ok_or_else(|| ProbeTargetError::operation(format!("Port not found: {address}")))?;
            Ok(ProbeTarget {
                endpoint: Endpoint::Tcp {
                    host: host.to_string(),
                    port: 10_001,
                },
                etherlite_port: Some(port_index),
            })
        }
        other => {
            let mut chars = other.chars();
            let class = chars
                .next()
                .map(|first| first.to_uppercase().collect::<String>() + chars.as_str())
                .unwrap_or_default();
            Err(ProbeTargetError::operation(format!(
                "Unable to load class:com.clipsal.cgate.cbus.net.CBus{class}Network for network type:{other} (com.clipsal.cgate.cbus.net.CBus{class}Network)"
            )))
        }
    }
}

pub(crate) fn validate_probe_target(kind: &str, address: &str) -> Result<(), (u16, String)> {
    probe_target(kind, address)
        .map(|_| ())
        .map_err(|error| (error.status, error.response))
}

async fn connect_probe_target(target: &ProbeTarget) -> io::Result<(BoxedRead, BoxedWrite)> {
    match &target.endpoint {
        Endpoint::Tcp { host, port } => {
            if *port == 0 {
                return Err(io::Error::new(
                    io::ErrorKind::AddrNotAvailable,
                    "Can't assign requested address (connect failed)",
                ));
            }
            let stream = tokio::time::timeout(
                PROBE_CONNECT_TIME,
                TcpStream::connect((host.as_str(), *port)),
            )
            .await
            .map_err(|_| {
                io::Error::new(
                    io::ErrorKind::TimedOut,
                    format!("connect to {host}:{port} timed out"),
                )
            })??;
            stream.set_nodelay(true).ok();
            let (reader, writer) = stream.into_split();
            Ok((Box::new(reader), Box::new(writer)))
        }
        Endpoint::Serial { device, baud } => connect_serial_probe(device, *baud).await,
    }
}

async fn connect_serial_probe(device: &str, baud: u32) -> io::Result<(BoxedRead, BoxedWrite)> {
    let wanted = serial_name(device);
    let ports = tokio_serial::available_ports()
        .map_err(|error| io::Error::other(format!("Failure in port library: {error}")))?;
    if !ports
        .iter()
        .any(|port| serial_name(&port.port_name).eq_ignore_ascii_case(wanted))
    {
        return Err(io::Error::new(
            io::ErrorKind::NotFound,
            format!("Port not found: {wanted}"),
        ));
    }

    let builder = tokio_serial::new(device, baud)
        .data_bits(tokio_serial::DataBits::Eight)
        .parity(tokio_serial::Parity::None)
        .stop_bits(tokio_serial::StopBits::One)
        .flow_control(tokio_serial::FlowControl::Software);
    let mut stream = tokio_serial::SerialStream::open(&builder).map_err(io::Error::from)?;
    stream.write_data_terminal_ready(true).map_err(|error| {
        io::Error::new(
            io::ErrorKind::InvalidInput,
            format!("Serial parameter setting failed: {error}"),
        )
    })?;
    stream.write_request_to_send(false).map_err(|error| {
        io::Error::new(
            io::ErrorKind::InvalidInput,
            format!("Serial parameter setting failed: {error}"),
        )
    })?;

    // serial.fixbaud defaults to yes in native C-Gate. Its return value is
    // deliberately ignored: even an undetected baud proceeds to PORT PROBE.
    let _ = serial_fix_baud(&mut stream).await;
    let (reader, writer) = tokio::io::split(stream);
    Ok((Box::new(reader), Box::new(writer)))
}

const SERIAL_BAUD_ATTEMPTS: [u32; 6] = [9_600, 2_400, 4_800, 1_200, 600, 300];
const SERIAL_AUTOBAUD_RESET: &[u8] = b"\r~~~~~~~~~\r";
const SERIAL_AUTOBAUD_QUERY: &[u8] = b"******\r";

async fn serial_autobaud_probe<S>(stream: &mut S) -> io::Result<bool>
where
    S: AsyncRead + AsyncWrite + Unpin,
{
    tokio::time::sleep(Duration::from_millis(500)).await;
    let _ = drain_ready(stream).await?;
    stream.write_all(SERIAL_AUTOBAUD_RESET).await?;
    stream.flush().await?;
    tokio::time::sleep(Duration::from_millis(500)).await;
    let _ = drain_ready(stream).await?;
    stream.write_all(SERIAL_AUTOBAUD_QUERY).await?;
    stream.flush().await?;
    tokio::time::sleep(Duration::from_millis(500)).await;
    Ok(drain_ready(stream).await?.contains(&b'*'))
}

async fn serial_fix_baud(stream: &mut tokio_serial::SerialStream) -> bool {
    for baud in SERIAL_BAUD_ATTEMPTS {
        if stream.set_baud_rate(baud).is_err() {
            continue;
        }
        let Ok(found) = serial_autobaud_probe(stream).await else {
            return false;
        };
        if !found {
            continue;
        }
        if baud == 9_600 {
            return true;
        }
        if stream.write_all(b"A33DBDFF\r").await.is_err() || stream.flush().await.is_err() {
            return false;
        }
        tokio::time::sleep(Duration::from_millis(2_500)).await;
        if stream.set_baud_rate(9_600).is_err() {
            return false;
        }
        let Ok(_) = drain_ready(stream).await else {
            return false;
        };
        if stream.write_all(SERIAL_AUTOBAUD_RESET).await.is_err() || stream.flush().await.is_err() {
            return false;
        }
        tokio::time::sleep(Duration::from_millis(500)).await;
        return drain_ready(stream)
            .await
            .is_ok_and(|bytes| bytes.contains(&b'~'));
    }
    false
}

fn socket_open_error(error: &io::Error) -> String {
    match error.kind() {
        io::ErrorKind::ConnectionRefused => "Connection refused (Connection refused)".to_string(),
        io::ErrorKind::AddrNotAvailable => {
            "Can't assign requested address (connect failed)".to_string()
        }
        _ => error.to_string(),
    }
}

fn serial_port_in_use(error: &io::Error) -> bool {
    matches!(
        error.kind(),
        io::ErrorKind::ResourceBusy | io::ErrorKind::WouldBlock
    ) || {
        let message = error.to_string().to_ascii_lowercase();
        message.contains("resource busy")
            || message.contains("device busy")
            || message.contains("port in use")
    }
}

async fn drain_ready<R>(reader: &mut R) -> io::Result<Vec<u8>>
where
    R: AsyncRead + Unpin,
{
    let mut drained = Vec::new();
    let mut buffer = [0u8; 512];
    loop {
        match tokio::time::timeout(Duration::from_millis(2), reader.read(&mut buffer)).await {
            Ok(Ok(0)) | Err(_) => return Ok(drained),
            Ok(Ok(length)) => drained.extend_from_slice(&buffer[..length]),
            Ok(Err(error)) => return Err(error),
        }
    }
}

/// Reproduce `CBusBaseNetwork.O()/bb()`, the wire operation used by native
/// `PORT PROBE`. It is deliberately smaller than cmqttd's normal PCI startup:
/// DC1+CR, an echoed `@2104` serial query, then the reply already available
/// after the native 500 ms wait.
async fn native_probe_wire(reader: &mut BoxedRead, writer: &mut BoxedWrite) -> io::Result<String> {
    writer
        .write_all(&[0x11, b'\r'])
        .await
        .map_err(|error| io::Error::new(error.kind(), format!("IO Exception: {error}")))?;
    writer
        .flush()
        .await
        .map_err(|error| io::Error::new(error.kind(), format!("IO Exception: {error}")))?;
    tokio::time::sleep(Duration::from_millis(200)).await;
    let _ = drain_ready(reader).await?;

    const QUERY: &[u8; 6] = b"@2104\r";
    writer
        .write_all(QUERY)
        .await
        .map_err(|error| io::Error::new(error.kind(), format!("IO Exception: {error}")))?;
    writer
        .flush()
        .await
        .map_err(|error| io::Error::new(error.kind(), format!("IO Exception: {error}")))?;
    let mut echo = [0u8; QUERY.len()];
    tokio::time::timeout(Duration::from_millis(500), reader.read_exact(&mut echo))
        .await
        .map_err(|_| io::Error::new(io::ErrorKind::TimedOut, "No response/timeout"))??;

    tokio::time::sleep(Duration::from_millis(500)).await;
    let response = drain_ready(reader).await?;
    // Native's byte filter leaves NULs for lowercase bytes and values below
    // ASCII '0'; the command response renderer displays those NULs as spaces.
    let response = response
        .into_iter()
        .map(|byte| {
            if byte.is_ascii_lowercase() || byte < b'0' {
                b' '
            } else {
                byte
            }
        })
        .collect::<Vec<_>>();
    Ok(String::from_utf8_lossy(&response).into_owned())
}

async fn probe(tag: &str, kind: &str, address: &str, configured: Option<&Endpoint>) -> Response {
    let target = match probe_target(kind, address) {
        Ok(target) => target,
        Err(error) => return err(tag, error.status, &error.response),
    };
    if let Some(active) = configured {
        if endpoints_equal(active, &target.endpoint).await {
            return err(
                tag,
                431,
                &format!("431 Probe failed: port in use: Port in use: {address}"),
            );
        }
    }
    let connection = if let Some(port_index) = target.etherlite_port {
        let Endpoint::Tcp { host, .. } = &target.endpoint else {
            unreachable!("EtherLite targets are TCP endpoints")
        };
        crate::etherlite::connect(host, port_index).await
    } else {
        connect_probe_target(&target).await
    };
    let (mut reader, mut writer) = match connection {
        Ok(streams) => streams,
        Err(error) if target.etherlite_port.is_some() => {
            let message = if error.kind() == io::ErrorKind::InvalidInput {
                format!("Port not found: {address}")
            } else {
                format!("Can't open etherlite: {address}")
            };
            return err(tag, 408, &format!("408 Operation failed: {message}"));
        }
        Err(error)
            if matches!(&target.endpoint, Endpoint::Serial { .. })
                && serial_port_in_use(&error) =>
        {
            return err(
                tag,
                431,
                &format!("431 Probe failed: port in use: Port in use: {address}"),
            );
        }
        Err(error) => {
            let message = match &target.endpoint {
                Endpoint::Tcp { .. } => socket_open_error(&error),
                Endpoint::Serial { .. } if error.kind() == io::ErrorKind::NotFound => {
                    format!("Port not found: {address}")
                }
                Endpoint::Serial { .. } => error.to_string(),
            };
            return err(tag, 408, &format!("408 Operation failed: {message}"));
        }
    };
    match native_probe_wire(&mut reader, &mut writer).await {
        Ok(serial) => Response {
            tag: tag.to_string(),
            lines: Vec::new(),
            final_text: format!("230 Probe succeeded: C-Bus network detected (PCIserial={serial})"),
            status: 230,
        },
        Err(error) => err(tag, 408, &format!("408 Operation failed: {error}")),
    }
}

pub(crate) async fn handle(tag: &str, words: &[&str], configured: Option<&Endpoint>) -> Response {
    if words.len() == 1 || (words.len() == 2 && words[1] == "?") {
        return help(tag);
    }
    let Some(sub) = words.get(1).map(|word| word.to_ascii_uppercase()) else {
        return err(tag, 400, "400 Syntax Error.");
    };
    match sub.as_str() {
        "LIST" if words.len() == 2 => match tokio_serial::available_ports() {
            Ok(ports) => {
                let active = configured.and_then(|endpoint| match endpoint {
                    Endpoint::Serial { device, .. } => Some(serial_name(device)),
                    Endpoint::Tcp { .. } => None,
                });
                let rows = ports
                    .into_iter()
                    .map(|port| {
                        let name = serial_name(&port.port_name);
                        let status = if active.is_some_and(|item| item.eq_ignore_ascii_case(name)) {
                            "inuse"
                        } else {
                            "available"
                        };
                        format!("port={name} status={status}")
                    })
                    .collect::<Vec<_>>();
                if rows.is_empty() {
                    response(tag, 126, rows, "no ports found")
                } else {
                    response(tag, 125, rows, "no ports found")
                }
            }
            Err(error) => err(
                tag,
                408,
                &format!("408 Operation failed: Failure in port library: {error}"),
            ),
        },
        "IFLIST" if words.len() == 2 => match if_addrs::get_if_addrs() {
            Ok(interfaces) => {
                let rows = interfaces
                    .into_iter()
                    .filter(|interface| !interface.is_loopback())
                    .map(|interface| {
                        format!("address={} interface={}", interface.ip(), interface.name.trim())
                    })
                    .collect::<Vec<_>>();
                if rows.is_empty() {
                    response(tag, 128, rows, "no interfaces found")
                } else {
                    response(tag, 127, rows, "no interfaces found")
                }
            }
            Err(error) => err(
                tag,
                408,
                &format!("408 Operation failed: Socket exception{error}"),
            ),
        },
        "REFRESH" if words.len() == 2 => err(
            tag,
            408,
            "408 Operation failed: This command is not applicable.  The list of ports is automatically updated.",
        ),
        "CNISCAN" => {
            let Some(args) = parse_scan_args(words, false) else {
                return err(tag, 400, "400 Syntax Error.");
            };
            match scan_legacy(&args).await {
                Ok(rows) if rows.is_empty() => response(tag, 130, rows, "no CNIs found"),
                Ok(rows) => response(tag, 129, rows, "no CNIs found"),
                Err(error) => err(tag, 408, &format!("408 Operation failed: scan failed: {error}")),
            }
        }
        "CNISCAN2" => {
            let Some(args) = parse_scan_args(words, true) else {
                return err(tag, 400, "400 Syntax Error.");
            };
            let mut rows = match scan_legacy(&args).await {
                Ok(rows) => rows,
                Err(error) => {
                    return err(tag, 408, &format!("408 Operation failed: scan failed: {error}"))
                }
            };
            match scan_cni2(&args).await {
                Ok(cni2) => rows.extend(cni2),
                Err(error) => {
                    return err(tag, 408, &format!("408 Operation failed: scan failed: {error}"))
                }
            }
            if rows.is_empty() {
                response(tag, 130, rows, "no CNIs found")
            } else {
                response(tag, 129, rows, "no CNIs found")
            }
        }
        "PROBE" if words.len() >= 4 => probe(tag, words[2], words[3], configured).await,
        _ => err(tag, 400, "400 Syntax Error."),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn native_scan_argument_quirks_are_preserved() {
        assert_eq!(
            parse_scan_args(&["PORT", "CNISCAN"], false),
            Some(ScanArgs {
                interface: None,
                destination: "255.255.255.255".into(),
                fast: false,
            })
        );
        assert_eq!(
            parse_scan_args(
                &["PORT", "CNISCAN", "192.0.2.255", "FAST", "ignored"],
                false
            ),
            Some(ScanArgs {
                interface: None,
                destination: "192.0.2.255".into(),
                fast: true,
            })
        );
        assert_eq!(
            parse_scan_args(
                &[
                    "PORT",
                    "CNISCAN2",
                    "192.0.2.1",
                    "192.0.2.255",
                    "FAST",
                    "ignored"
                ],
                true
            ),
            Some(ScanArgs {
                interface: Some("192.0.2.1".into()),
                destination: "192.0.2.255".into(),
                fast: true,
            })
        );
        assert_eq!(
            parse_scan_args(&["PORT", "CNISCAN", "192.0.2.255", "not-fast"], false),
            Some(ScanArgs {
                interface: None,
                destination: "192.0.2.255".into(),
                fast: false,
            })
        );
        assert_eq!(
            parse_scan_args(
                &["PORT", "CNISCAN2", "192.0.2.1", "192.0.2.255", "not-fast"],
                true
            ),
            Some(ScanArgs {
                interface: Some("192.0.2.1".into()),
                destination: "192.0.2.255".into(),
                fast: false,
            })
        );
        assert!(parse_scan_args(
            &["PORT", "CNISCAN", "192.0.2.255", "not-fast", "leftover"],
            false
        )
        .is_none());
        let lookup = legacy_lookup_error(
            "does-not-exist.invalid",
            false,
            io::Error::new(
                io::ErrorKind::NotFound,
                "failed to lookup address information: nodename not known",
            ),
        );
        assert_eq!(
            lookup.to_string(),
            "Can not send to network: does-not-exist.invalid: nodename not known"
        );
        let interface = legacy_lookup_error(
            "does-not-exist.invalid",
            true,
            io::Error::new(io::ErrorKind::NotFound, "platform-specific resolver text"),
        );
        assert_eq!(
            interface.to_string(),
            "Can not send via interface: does-not-exist.invalid"
        );
    }

    #[test]
    fn native_probe_address_grammar_is_bounded() {
        assert_eq!(
            probe_target("cni", "192.0.2.4:10001").unwrap(),
            ProbeTarget {
                endpoint: Endpoint::Tcp {
                    host: "192.0.2.4".into(),
                    port: 10001,
                },
                etherlite_port: None,
            }
        );
        assert_eq!(
            probe_target("socket", "example.test:1234").unwrap(),
            ProbeTarget {
                endpoint: Endpoint::Tcp {
                    host: "example.test".into(),
                    port: 1234,
                },
                etherlite_port: None,
            }
        );
        assert_eq!(
            probe_target("socket", "missing-port").unwrap().endpoint,
            Endpoint::Tcp {
                host: "missing-port".into(),
                port: 0,
            }
        );
        assert_eq!(
            probe_target("socket", "example.test:not-a-number")
                .unwrap()
                .endpoint,
            Endpoint::Tcp {
                host: "example.test".into(),
                port: 0,
            }
        );
        assert!(probe_target("socket", "example.test:-1").is_err());
        assert!(probe_target("bogus", "nowhere")
            .unwrap_err()
            .response
            .contains("CBusBogusNetwork"));
        assert_eq!(
            validate_probe_target("etherlite", "127.0.0.1"),
            Err((500, "500 Internal error.".to_string()))
        );
        assert_eq!(
            validate_probe_target("etherlite", "127.0.0.1:x"),
            Err((
                408,
                "408 Operation failed: Port not found: 127.0.0.1:x".to_string()
            ))
        );
        assert_eq!(
            probe_target("etherlite", "127.0.0.1:256")
                .unwrap()
                .etherlite_port,
            Some(256)
        );
    }

    #[test]
    fn port_help_is_the_observed_native_envelope() {
        let got = help("x");
        assert_eq!(got.status, 101);
        assert_eq!(got.lines.first().unwrap(), "Help: PORT commands:");
        assert_eq!(
            got.final_text,
            "101 Help:  PORT REFRESH - Refresh the known local serial ports"
        );
    }

    #[tokio::test(start_paused = true)]
    async fn native_serial_autobaud_exchange_is_exact() {
        let (mut probe, mut pci) = tokio::io::duplex(128);
        let fake = tokio::spawn(async move {
            let mut reset = [0; SERIAL_AUTOBAUD_RESET.len()];
            pci.read_exact(&mut reset).await.unwrap();
            assert_eq!(&reset, SERIAL_AUTOBAUD_RESET);
            pci.write_all(b"discarded").await.unwrap();

            let mut query = [0; SERIAL_AUTOBAUD_QUERY.len()];
            pci.read_exact(&mut query).await.unwrap();
            assert_eq!(&query, SERIAL_AUTOBAUD_QUERY);
            pci.write_all(b"*\r").await.unwrap();
        });
        assert!(serial_autobaud_probe(&mut probe).await.unwrap());
        fake.await.unwrap();
        assert_eq!(SERIAL_BAUD_ATTEMPTS, [9_600, 2_400, 4_800, 1_200, 600, 300]);
        assert!(serial_port_in_use(&io::Error::new(
            io::ErrorKind::ResourceBusy,
            "device busy"
        )));
    }
}
