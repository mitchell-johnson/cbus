//! TCP and serial connections: 10 s connect timeout; optional
//! reconnect every `reconnect_interval` (default 5 s), 0 = unlimited
//! attempts.

use crate::pci::{BoxedRead, BoxedWrite};
use std::time::Duration;
use tokio::net::TcpStream;

/// Timeout for a single connection attempt.
pub const CONNECT_TIMEOUT: Duration = Duration::from_secs(10);
/// Default pause between reconnection attempts.
pub const DEFAULT_RECONNECT_INTERVAL: Duration = Duration::from_secs(5);
/// Default TCP port of an ESP32 C-Bus bridge.
pub const ESP32_DEFAULT_PORT: u16 = 10001;
/// Default baud rate of an ESP32 serial bridge (9600 8N1).
pub const ESP32_DEFAULT_BAUD: u32 = 9600;

/// Where the C-Bus PCI/CNI lives.
#[derive(Debug, Clone, PartialEq)]
pub enum Endpoint {
    /// TCP connection to a CNI (or ESP32 bridge in WiFi mode).
    Tcp {
        /// Host name or IP address.
        host: String,
        /// TCP port.
        port: u16,
    },
    /// Direct serial connection (PCI or ESP32 bridge), 8N1.
    Serial {
        /// Device path, e.g. `/dev/ttyUSB0`.
        device: String,
        /// Baud rate (9600 for a 5500PC/ESP32).
        baud: u32,
    },
}

impl Endpoint {
    /// `-t ADDR:PORT`
    pub fn parse_tcp(spec: &str) -> Result<Endpoint, String> {
        let (host, port) = spec
            .split_once(':')
            .ok_or_else(|| format!("invalid TCP address {spec:?}, expected ADDR:PORT"))?;
        Ok(Endpoint::Tcp {
            host: host.to_string(),
            port: port
                .parse()
                .map_err(|_| format!("invalid TCP port {port:?}"))?,
        })
    }

    /// `--esp32-wifi HOST[:PORT]` (default port 10001)
    pub fn parse_esp32_wifi(spec: &str) -> Result<Endpoint, String> {
        match spec.rsplit_once(':') {
            Some((host, port)) => Ok(Endpoint::Tcp {
                host: host.to_string(),
                port: port.parse().map_err(|_| format!("invalid port {port:?}"))?,
            }),
            None => Ok(Endpoint::Tcp {
                host: spec.to_string(),
                port: ESP32_DEFAULT_PORT,
            }),
        }
    }

    /// `--esp32-serial DEVICE` (9600 8N1)
    pub fn serial(device: &str, baud: u32) -> Endpoint {
        Endpoint::Serial {
            device: device.to_string(),
            baud,
        }
    }
}

/// Connect once, with the 10 s timeout. Returns split read/write halves.
pub async fn connect(ep: &Endpoint) -> std::io::Result<(BoxedRead, BoxedWrite)> {
    match ep {
        Endpoint::Tcp { host, port } => {
            let stream =
                tokio::time::timeout(CONNECT_TIMEOUT, TcpStream::connect((host.as_str(), *port)))
                    .await
                    .map_err(|_| {
                        std::io::Error::new(
                            std::io::ErrorKind::TimedOut,
                            format!("connect to {host}:{port} timed out"),
                        )
                    })??;
            stream.set_nodelay(true).ok();
            let (rd, wr) = stream.into_split();
            Ok((Box::new(rd), Box::new(wr)))
        }
        Endpoint::Serial { device, baud } => {
            let port = open_serial(device, *baud)?;
            let (rd, wr) = tokio::io::split(port);
            Ok((Box::new(rd), Box::new(wr)))
        }
    }
}

fn serial_builder(device: &str, baud: u32) -> tokio_serial::SerialPortBuilder {
    tokio_serial::new(device, baud)
        .data_bits(tokio_serial::DataBits::Eight)
        .parity(tokio_serial::Parity::None)
        .stop_bits(tokio_serial::StopBits::One)
}

/// Open `device` 8N1, exclusively (serialport's TIOCEXCL plus flock).
///
/// On macOS the line rate is set with `IOSSIOSPEED`, which a pseudo-terminal
/// rejects with ENOTTY after the port is already configured. Only that
/// failure is retried once without a rate: a pty has no line rate, while a
/// real serial driver accepts the ioctl, so its errors are never masked.
fn open_serial(device: &str, baud: u32) -> std::io::Result<tokio_serial::SerialStream> {
    match tokio_serial::SerialStream::open(&serial_builder(device, baud)) {
        Ok(port) => Ok(port),
        #[cfg(any(target_os = "macos", target_os = "ios"))]
        Err(error) if baud > 0 && is_enotty(&error) => {
            tracing::info!(
                "{device} rejected the serial speed ioctl; opening it as a pseudo-terminal"
            );
            tokio_serial::SerialStream::open(&serial_builder(device, 0))
                .map_err(std::io::Error::other)
        }
        Err(error) => Err(std::io::Error::other(error)),
    }
}

/// serialport reports errno ENOTTY as an unknown error carrying nix's text.
#[cfg(any(target_os = "macos", target_os = "ios"))]
fn is_enotty(error: &tokio_serial::Error) -> bool {
    error.kind == tokio_serial::ErrorKind::Unknown
        && (error.description == "Not a typewriter"
            || error.description
                == std::io::Error::from_raw_os_error(libc::ENOTTY)
                    .to_string()
                    .split(" (os error")
                    .next()
                    .unwrap_or_default())
}

/// Connect with retries: sleep `interval` between attempts;
/// `max_attempts` 0 = unlimited.
pub async fn connect_with_retry(
    ep: &Endpoint,
    interval: Duration,
    max_attempts: u32,
) -> std::io::Result<(BoxedRead, BoxedWrite)> {
    let mut attempts = 0u32;
    loop {
        match connect(ep).await {
            Ok(pair) => return Ok(pair),
            Err(e) => {
                attempts += 1;
                if max_attempts != 0 && attempts >= max_attempts {
                    return Err(e);
                }
                tracing::warn!("connect failed ({e}); retrying in {:?}", interval);
                tokio::time::sleep(interval).await;
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn tcp_connect_and_reconnect() {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = listener.local_addr().unwrap().port();
        let ep = Endpoint::Tcp {
            host: "127.0.0.1".into(),
            port,
        };
        let accept = tokio::spawn(async move {
            let (_s, _) = listener.accept().await.unwrap();
        });
        let r = connect(&ep).await;
        assert!(r.is_ok());
        accept.await.unwrap();
        // dropped listener: connect fails now
        let r2 = connect(&ep).await;
        assert!(r2.is_err());
        // retry path with capped attempts
        let r3 = connect_with_retry(&ep, Duration::from_millis(20), 2).await;
        assert!(r3.is_err());
    }

    /// A pseudo-terminal slave carries bytes both ways through the same
    /// serial endpoint cmqttd uses for `--serial`.
    #[cfg(unix)]
    #[tokio::test]
    async fn serial_endpoint_opens_a_pseudo_terminal() {
        use std::io::{Read, Write};
        use std::os::fd::FromRawFd;
        use tokio::io::{AsyncReadExt, AsyncWriteExt};

        let (master, path) = unsafe {
            let fd = libc::posix_openpt(libc::O_RDWR | libc::O_NOCTTY);
            assert!(fd >= 0, "posix_openpt failed");
            assert_eq!(libc::grantpt(fd), 0);
            assert_eq!(libc::unlockpt(fd), 0);
            let name = std::ffi::CStr::from_ptr(libc::ptsname(fd))
                .to_string_lossy()
                .into_owned();
            (std::fs::File::from_raw_fd(fd), name)
        };
        let (mut rd, mut wr) = connect(&Endpoint::serial(&path, ESP32_DEFAULT_BAUD))
            .await
            .unwrap_or_else(|error| panic!("open {path}: {error}"));
        // Read the master first: flushing a serial stream waits (tcdrain)
        // until the other side of the pty has consumed the output.
        let mut reader = master.try_clone().unwrap();
        let sent = tokio::task::spawn_blocking(move || {
            let mut sent = [0u8; 2];
            reader.read_exact(&mut sent).unwrap();
            sent
        });
        wr.write_all(b"~\r").await.unwrap();
        wr.flush().await.unwrap();
        assert_eq!(
            &tokio::time::timeout(Duration::from_secs(5), sent)
                .await
                .unwrap()
                .unwrap(),
            b"~\r"
        );
        (&master).write_all(b"++\r\n").unwrap();
        let mut received = [0u8; 4];
        tokio::time::timeout(Duration::from_secs(5), rd.read_exact(&mut received))
            .await
            .unwrap()
            .unwrap();
        assert_eq!(&received, b"++\r\n");
    }

    #[test]
    fn endpoint_parsing() {
        assert_eq!(
            Endpoint::parse_tcp("192.0.2.1:10001").unwrap(),
            Endpoint::Tcp {
                host: "192.0.2.1".into(),
                port: 10001
            }
        );
        assert_eq!(
            Endpoint::parse_esp32_wifi("10.0.0.5").unwrap(),
            Endpoint::Tcp {
                host: "10.0.0.5".into(),
                port: 10001
            }
        );
        assert_eq!(
            Endpoint::parse_esp32_wifi("10.0.0.5:2000").unwrap(),
            Endpoint::Tcp {
                host: "10.0.0.5".into(),
                port: 2000
            }
        );
    }
}
