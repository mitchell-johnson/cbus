//! Bounded IPv4 UDP discovery for CNI2 and Wiser interfaces.

use cbus_protocol::cni_discovery::{decode_discovery_reply, DiscoveryReply, DISCOVERY_QUERY};
use std::collections::HashSet;
use std::net::{SocketAddr, SocketAddrV4};
use std::time::Duration;
use tokio::net::UdpSocket;
use tokio::time::{timeout_at, Instant};

/// Hard bound for a single discovery run.
pub const MAX_DISCOVERY_DATAGRAMS: usize = 4_096;

/// Inputs to one read-only CNI discovery broadcast.
#[derive(Debug, Clone)]
pub struct DiscoveryConfig {
    /// Local IPv4 address and UDP port.  Port zero asks the OS for an
    /// ephemeral port; native Toolkit-compatible discovery normally uses
    /// port 20050.
    pub bind: SocketAddrV4,
    /// Broadcast or unicast IPv4 destination and discovery UDP port.
    pub destination: SocketAddrV4,
    /// Total receive window after the one query datagram is sent.
    pub timeout: Duration,
    /// Maximum number of datagrams accepted before collection is marked
    /// incomplete.
    pub max_datagrams: usize,
    /// Include product-id 2 replies, which captured Toolkit behavior hides.
    pub include_hidden: bool,
}

/// One valid, unique discovery reply and its network provenance.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DiscoveryObservation {
    /// UDP peer that sent the reply.
    pub source: SocketAddrV4,
    /// Exact raw reply bytes.
    pub raw: Vec<u8>,
    /// Strictly decoded fixed-layout reply.
    pub reply: DiscoveryReply,
}

/// One rejected UDP datagram received during the bounded window.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MalformedObservation {
    /// UDP peer that sent the datagram.
    pub source: SocketAddr,
    /// Exact raw datagram bytes.
    pub raw: Vec<u8>,
    /// Decoder rejection reason.
    pub error: String,
}

/// Complete evidence from one bounded query/receive cycle.
#[derive(Debug, Clone)]
pub struct DiscoveryReport {
    /// Actual local address after binding; contains the selected ephemeral
    /// port when the input port was zero.
    pub local: SocketAddrV4,
    /// Destination to which the one exact query was sent.
    pub destination: SocketAddrV4,
    /// Valid unique replies admitted by the visibility policy.
    pub devices: Vec<DiscoveryObservation>,
    /// Structurally invalid datagrams retained as evidence.
    pub malformed: Vec<MalformedObservation>,
    /// Count of exact source-and-payload duplicates not repeated in output.
    pub duplicates_ignored: usize,
    /// Count of valid product-id 2 replies excluded by the default policy.
    pub hidden_ignored: usize,
    /// Total datagrams received, including invalid and duplicate datagrams.
    pub datagrams_received: usize,
    /// False when the datagram cap ended collection before the deadline.
    pub collection_complete: bool,
}

/// Send the exact captured query once and collect replies until the monotonic
/// deadline or datagram bound.  This operation does not open a CNI TCP
/// connection or prove that an unobserved interface is absent.
pub async fn discover(config: &DiscoveryConfig) -> Result<DiscoveryReport, String> {
    if config.timeout.is_zero() || config.timeout > Duration::from_secs(300) {
        return Err("CNI discovery timeout must be in (0, 300] seconds".to_string());
    }
    if !(1..=MAX_DISCOVERY_DATAGRAMS).contains(&config.max_datagrams) {
        return Err(format!(
            "CNI discovery max_datagrams must be in 1..={MAX_DISCOVERY_DATAGRAMS}"
        ));
    }
    if config.destination.port() == 0 {
        return Err("CNI discovery destination port must be in 1..=65535".to_string());
    }

    let socket = UdpSocket::bind(config.bind)
        .await
        .map_err(|error| format!("Unable to bind CNI discovery socket: {error}"))?;
    socket
        .set_broadcast(true)
        .map_err(|error| format!("Unable to enable CNI discovery broadcast: {error}"))?;
    let local = match socket
        .local_addr()
        .map_err(|error| format!("Unable to inspect CNI discovery socket: {error}"))?
    {
        SocketAddr::V4(address) => address,
        SocketAddr::V6(_) => return Err("CNI discovery requires an IPv4 socket".to_string()),
    };
    let sent = socket
        .send_to(&DISCOVERY_QUERY, config.destination)
        .await
        .map_err(|error| format!("Unable to send CNI discovery query: {error}"))?;
    if sent != DISCOVERY_QUERY.len() {
        return Err(format!(
            "CNI discovery sent {sent} of {} query bytes",
            DISCOVERY_QUERY.len()
        ));
    }

    let deadline = Instant::now() + config.timeout;
    let mut buffer = vec![0u8; 65_535];
    let mut seen = HashSet::<(SocketAddr, Vec<u8>)>::new();
    let mut devices = Vec::new();
    let mut malformed = Vec::new();
    let mut duplicates_ignored = 0usize;
    let mut hidden_ignored = 0usize;
    let mut datagrams_received = 0usize;
    let mut collection_complete = true;

    loop {
        if datagrams_received == config.max_datagrams {
            collection_complete = false;
            break;
        }
        let received = match timeout_at(deadline, socket.recv_from(&mut buffer)).await {
            Err(_) => break,
            Ok(Err(error)) => {
                return Err(format!("Unable to receive CNI discovery reply: {error}"));
            }
            Ok(Ok(value)) => value,
        };
        let (length, source) = received;
        datagrams_received += 1;
        let raw = buffer[..length].to_vec();
        if !seen.insert((source, raw.clone())) {
            duplicates_ignored += 1;
            continue;
        }
        match decode_discovery_reply(&raw) {
            Ok(reply) => {
                let SocketAddr::V4(source) = source else {
                    malformed.push(MalformedObservation {
                        source,
                        raw,
                        error: "CNI discovery reply source must be IPv4".to_string(),
                    });
                    continue;
                };
                if !config.include_hidden && !reply.visible_by_default() {
                    hidden_ignored += 1;
                    continue;
                }
                devices.push(DiscoveryObservation { source, raw, reply });
            }
            Err(error) => malformed.push(MalformedObservation {
                source,
                raw,
                error: error.to_string(),
            }),
        }
    }

    devices.sort_by_key(|item| {
        (
            *item.source.ip(),
            item.reply.service_port,
            item.reply.product_id,
            item.reply.unknown1,
        )
    });
    malformed.sort_by(|left, right| {
        (&left.source, &left.raw, &left.error).cmp(&(&right.source, &right.raw, &right.error))
    });
    Ok(DiscoveryReport {
        local,
        destination: config.destination,
        devices,
        malformed,
        duplicates_ignored,
        hidden_ignored,
        datagrams_received,
        collection_complete,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::net::Ipv4Addr;

    #[tokio::test]
    async fn local_peer_exercises_dedup_hidden_and_malformed_boundaries() {
        let peer = UdpSocket::bind((Ipv4Addr::LOCALHOST, 0)).await.unwrap();
        let peer_address = match peer.local_addr().unwrap() {
            SocketAddr::V4(value) => value,
            SocketAddr::V6(_) => unreachable!(),
        };
        let responder = tokio::spawn(async move {
            let mut query = [0u8; 64];
            let (size, source) = peer.recv_from(&mut query).await.unwrap();
            assert_eq!(&query[..size], DISCOVERY_QUERY);
            let visible =
                hex::decode("cb81000020e8f5528101000101810b00022711811d000101800100028c26")
                    .unwrap();
            let hidden =
                hex::decode("cb810000000000028101000102810b00022711811d000100800100020000")
                    .unwrap();
            for payload in [&visible[..], &visible[..], &hidden[..], b"noise"] {
                peer.send_to(payload, source).await.unwrap();
            }
        });
        let report = discover(&DiscoveryConfig {
            bind: SocketAddrV4::new(Ipv4Addr::LOCALHOST, 0),
            destination: peer_address,
            timeout: Duration::from_millis(100),
            max_datagrams: 16,
            include_hidden: false,
        })
        .await
        .unwrap();
        responder.await.unwrap();
        assert!(report.collection_complete);
        assert_eq!(report.datagrams_received, 4);
        assert_eq!(report.devices.len(), 1);
        assert_eq!(report.duplicates_ignored, 1);
        assert_eq!(report.hidden_ignored, 1);
        assert_eq!(report.malformed.len(), 1);
        assert_eq!(report.devices[0].reply.product_name(), "cni2");
    }

    #[tokio::test]
    async fn cap_is_reported_as_incomplete() {
        let peer = UdpSocket::bind((Ipv4Addr::LOCALHOST, 0)).await.unwrap();
        let peer_address = match peer.local_addr().unwrap() {
            SocketAddr::V4(value) => value,
            SocketAddr::V6(_) => unreachable!(),
        };
        let responder = tokio::spawn(async move {
            let mut query = [0u8; 64];
            let (_, source) = peer.recv_from(&mut query).await.unwrap();
            peer.send_to(b"noise", source).await.unwrap();
        });
        let report = discover(&DiscoveryConfig {
            bind: SocketAddrV4::new(Ipv4Addr::LOCALHOST, 0),
            destination: peer_address,
            timeout: Duration::from_secs(1),
            max_datagrams: 1,
            include_hidden: false,
        })
        .await
        .unwrap();
        responder.await.unwrap();
        assert!(!report.collection_complete);
        assert_eq!(report.datagrams_received, 1);
    }

    #[tokio::test]
    async fn invalid_bounds_fail_before_socket_io() {
        let base = DiscoveryConfig {
            bind: SocketAddrV4::new(Ipv4Addr::LOCALHOST, 0),
            destination: SocketAddrV4::new(
                Ipv4Addr::LOCALHOST,
                cbus_protocol::cni_discovery::DISCOVERY_PORT,
            ),
            timeout: Duration::from_millis(1),
            max_datagrams: 1,
            include_hidden: false,
        };
        for config in [
            DiscoveryConfig {
                timeout: Duration::ZERO,
                ..base.clone()
            },
            DiscoveryConfig {
                timeout: Duration::from_secs(301),
                ..base.clone()
            },
            DiscoveryConfig {
                max_datagrams: 0,
                ..base.clone()
            },
            DiscoveryConfig {
                max_datagrams: MAX_DISCOVERY_DATAGRAMS + 1,
                ..base.clone()
            },
            DiscoveryConfig {
                destination: SocketAddrV4::new(Ipv4Addr::LOCALHOST, 0),
                ..base.clone()
            },
        ] {
            assert!(discover(&config).await.is_err());
        }
    }
}
