//! TCP / serial connections. Port of `transport/{base,tcp,serial}.py` and
//! `esp32/connection.py` semantics: 10 s connect timeout; optional
//! reconnect every `reconnect_interval` (default 5 s), 0 = unlimited
//! attempts.

use crate::pci::{BoxedRead, BoxedWrite};
use std::time::Duration;
use tokio::net::TcpStream;

pub const CONNECT_TIMEOUT: Duration = Duration::from_secs(10);
pub const DEFAULT_RECONNECT_INTERVAL: Duration = Duration::from_secs(5);
pub const ESP32_DEFAULT_PORT: u16 = 10001;
pub const ESP32_DEFAULT_BAUD: u32 = 9600;

#[derive(Debug, Clone, PartialEq)]
pub enum Endpoint {
    Tcp { host: String, port: u16 },
    Serial { device: String, baud: u32 },
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
            let port = tokio_serial::SerialStream::open(
                &tokio_serial::new(device, *baud)
                    .data_bits(tokio_serial::DataBits::Eight)
                    .parity(tokio_serial::Parity::None)
                    .stop_bits(tokio_serial::StopBits::One),
            )
            .map_err(std::io::Error::other)?;
            let (rd, wr) = tokio::io::split(port);
            Ok((Box::new(rd), Box::new(wr)))
        }
    }
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
