//! Bounded IPv4 UDP discovery for CNI2 and Wiser interfaces.

use cbus_protocol::cni_discovery::{decode_discovery_reply, DiscoveryReply, DISCOVERY_QUERY};
use ring::digest::{digest, SHA256};
use std::collections::HashSet;
use std::net::{SocketAddr, SocketAddrV4};
use std::time::Duration;
use tokio::net::UdpSocket;
use tokio::time::{timeout_at, Instant};

/// OS socket option confirmed by readback before an automatic adapter probe.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct InterfaceConstraint {
    /// OS interface index checked against the selected name before sending.
    pub index: u32,
    /// The socket option set and read back for this operating system.
    pub mechanism: &'static str,
}

fn pin_discovery_interface(
    socket: &UdpSocket,
    name: &str,
    index: u32,
) -> Result<InterfaceConstraint, String> {
    if name.is_empty() || name.as_bytes().contains(&0) || index == 0 {
        return Err("CNI interface name or index is invalid".into());
    }
    #[cfg(any(target_os = "macos", target_os = "linux"))]
    {
        use std::ffi::CString;
        use std::os::fd::AsRawFd;

        let name = CString::new(name).map_err(|_| "CNI interface name contains NUL")?;
        // The planner's interface index is a snapshot. Confirm it still names
        // the selected adapter immediately before constraining the socket.
        let current = unsafe { libc::if_nametoindex(name.as_ptr()) };
        if current == 0 || current != index {
            return Err("CNI interface index changed after route planning".into());
        }
        let fd = socket.as_raw_fd();
        #[cfg(target_os = "macos")]
        {
            let size = std::mem::size_of::<u32>() as libc::socklen_t;
            let set = unsafe {
                libc::setsockopt(
                    fd,
                    libc::IPPROTO_IP,
                    libc::IP_BOUND_IF,
                    (&index as *const u32).cast(),
                    size,
                )
            };
            if set != 0 {
                return Err(format!(
                    "Unable to pin CNI interface: {}",
                    std::io::Error::last_os_error()
                ));
            }
            let mut actual = 0u32;
            let mut read_size = size;
            let get = unsafe {
                libc::getsockopt(
                    fd,
                    libc::IPPROTO_IP,
                    libc::IP_BOUND_IF,
                    (&mut actual as *mut u32).cast(),
                    &mut read_size,
                )
            };
            if get != 0 || read_size != size || actual != index {
                return Err("CNI IP_BOUND_IF readback did not match selected adapter".into());
            }
            return Ok(InterfaceConstraint {
                index,
                mechanism: "IP_BOUND_IF",
            });
        }
        #[cfg(target_os = "linux")]
        {
            let bytes = name.as_bytes_with_nul();
            if bytes.len() > libc::IFNAMSIZ {
                return Err("CNI Linux interface name exceeds IFNAMSIZ".into());
            }
            let set = unsafe {
                libc::setsockopt(
                    fd,
                    libc::SOL_SOCKET,
                    libc::SO_BINDTODEVICE,
                    bytes.as_ptr().cast(),
                    bytes.len() as libc::socklen_t,
                )
            };
            if set != 0 {
                return Err(format!(
                    "Unable to pin CNI interface: {}",
                    std::io::Error::last_os_error()
                ));
            }
            let mut actual = [0u8; libc::IFNAMSIZ];
            let mut read_size = actual.len() as libc::socklen_t;
            let get = unsafe {
                libc::getsockopt(
                    fd,
                    libc::SOL_SOCKET,
                    libc::SO_BINDTODEVICE,
                    actual.as_mut_ptr().cast(),
                    &mut read_size,
                )
            };
            if get != 0
                || read_size as usize > actual.len()
                || actual[..read_size as usize].split(|byte| *byte == 0).next()
                    != Some(name.as_bytes())
            {
                return Err("CNI SO_BINDTODEVICE readback did not match selected adapter".into());
            }
            return Ok(InterfaceConstraint {
                index,
                mechanism: "SO_BINDTODEVICE",
            });
        }
    }
    #[cfg(windows)]
    {
        use std::os::windows::io::AsRawSocket;

        #[link(name = "ws2_32")]
        extern "system" {
            fn setsockopt(
                socket: usize,
                level: i32,
                option: i32,
                value: *const i8,
                len: i32,
            ) -> i32;
            fn getsockopt(
                socket: usize,
                level: i32,
                option: i32,
                value: *mut i8,
                len: *mut i32,
            ) -> i32;
            #[link_name = "WSAGetLastError"]
            fn wsa_get_last_error() -> i32;
        }
        const IPPROTO_IP: i32 = 0;
        const IP_UNICAST_IF: i32 = 31;
        let raw = socket.as_raw_socket() as usize;
        let network_index = index.to_be_bytes();
        let set = unsafe {
            setsockopt(
                raw,
                IPPROTO_IP,
                IP_UNICAST_IF,
                network_index.as_ptr().cast(),
                4,
            )
        };
        if set != 0 {
            return Err(format!("Unable to pin CNI interface: Winsock {}", unsafe {
                wsa_get_last_error()
            }));
        }
        let mut actual = 0u32;
        let mut size = 4i32;
        let get = unsafe {
            getsockopt(
                raw,
                IPPROTO_IP,
                IP_UNICAST_IF,
                (&mut actual as *mut u32).cast(),
                &mut size,
            )
        };
        if get != 0 || size != 4 || actual != index {
            return Err("CNI IP_UNICAST_IF readback did not match selected adapter".into());
        }
        return Ok(InterfaceConstraint {
            index,
            mechanism: "IP_UNICAST_IF",
        });
    }
    #[allow(unreachable_code)]
    Err("CNI interface pinning is unsupported on this OS".into())
}

/// Hard bound for a single discovery run.
pub const MAX_DISCOVERY_DATAGRAMS: usize = 4_096;
/// Keep malformed evidence bounded even when a peer sends a maximal UDP datagram.
pub const MAX_MALFORMED_RAW_PREFIX: usize = 64;

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
    /// The first at most 64 bytes of the datagram.
    pub raw: Vec<u8>,
    /// Original datagram length before truncation.
    pub raw_length: usize,
    /// Whether raw contains only a prefix of the datagram.
    pub raw_truncated: bool,
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
    discover_inner(config, None).await.map(|(report, _)| report)
}

/// Discover through one named, indexed OS adapter. Any pin or readback error
/// fails before the query is sent, with no unconstrained fallback.
pub async fn discover_on_interface(
    config: &DiscoveryConfig,
    name: &str,
    index: u32,
) -> Result<(DiscoveryReport, InterfaceConstraint), String> {
    let (report, constraint) = discover_inner(config, Some((name, index))).await?;
    Ok((report, constraint.expect("interface was requested")))
}

async fn discover_inner(
    config: &DiscoveryConfig,
    interface: Option<(&str, u32)>,
) -> Result<(DiscoveryReport, Option<InterfaceConstraint>), String> {
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
    let constraint = interface
        .map(|(name, index)| pin_discovery_interface(&socket, name, index))
        .transpose()?;
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
    let mut seen = HashSet::<(SocketAddr, usize, [u8; 32])>::new();
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
        let raw = &buffer[..length];
        let mut fingerprint = [0u8; 32];
        fingerprint.copy_from_slice(digest(&SHA256, raw).as_ref());
        if !seen.insert((source, length, fingerprint)) {
            duplicates_ignored += 1;
            continue;
        }
        match decode_discovery_reply(raw) {
            Ok(reply) => {
                let SocketAddr::V4(source) = source else {
                    malformed.push(MalformedObservation {
                        source,
                        raw: raw[..raw.len().min(MAX_MALFORMED_RAW_PREFIX)].to_vec(),
                        raw_length: length,
                        raw_truncated: length > MAX_MALFORMED_RAW_PREFIX,
                        error: "CNI discovery reply source must be IPv4".to_string(),
                    });
                    continue;
                };
                if !config.include_hidden && !reply.visible_by_default() {
                    hidden_ignored += 1;
                    continue;
                }
                devices.push(DiscoveryObservation {
                    source,
                    raw: raw.to_vec(),
                    reply,
                });
            }
            Err(error) => malformed.push(MalformedObservation {
                source,
                raw: raw[..raw.len().min(MAX_MALFORMED_RAW_PREFIX)].to_vec(),
                raw_length: length,
                raw_truncated: length > MAX_MALFORMED_RAW_PREFIX,
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
        (&left.source, &left.raw, left.raw_length, &left.error).cmp(&(
            &right.source,
            &right.raw,
            right.raw_length,
            &right.error,
        ))
    });
    Ok((
        DiscoveryReport {
            local,
            destination: config.destination,
            devices,
            malformed,
            duplicates_ignored,
            hidden_ignored,
            datagrams_received,
            collection_complete,
        },
        constraint,
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::net::Ipv4Addr;

    #[tokio::test]
    async fn invalid_interface_pin_fails_before_query_send() {
        let peer = UdpSocket::bind((Ipv4Addr::LOCALHOST, 0)).await.unwrap();
        let destination = match peer.local_addr().unwrap() {
            SocketAddr::V4(value) => value,
            SocketAddr::V6(_) => unreachable!(),
        };
        let config = DiscoveryConfig {
            bind: SocketAddrV4::new(Ipv4Addr::LOCALHOST, 0),
            destination,
            timeout: Duration::from_millis(50),
            max_datagrams: 1,
            include_hidden: false,
        };
        assert!(discover_on_interface(&config, "invalid", 0)
            .await
            .unwrap_err()
            .contains("invalid"));
        let mut buffer = [0u8; 64];
        assert!(
            tokio::time::timeout(Duration::from_millis(25), peer.recv_from(&mut buffer))
                .await
                .is_err()
        );
    }

    #[cfg(target_os = "macos")]
    #[tokio::test]
    async fn macos_loopback_interface_pin_receives_reply() {
        use std::ffi::CString;

        let name = CString::new("lo0").unwrap();
        let index = unsafe { libc::if_nametoindex(name.as_ptr()) };
        assert_ne!(index, 0);
        let peer = UdpSocket::bind((Ipv4Addr::LOCALHOST, 0)).await.unwrap();
        let destination = match peer.local_addr().unwrap() {
            SocketAddr::V4(value) => value,
            SocketAddr::V6(_) => unreachable!(),
        };
        let responder = tokio::spawn(async move {
            let mut query = [0u8; 64];
            let (size, source) = peer.recv_from(&mut query).await.unwrap();
            assert_eq!(&query[..size], DISCOVERY_QUERY);
            peer.send_to(
                &hex::decode("cb81000020e8f5528101000101810b00022711811d000101800100028c26")
                    .unwrap(),
                source,
            )
            .await
            .unwrap();
        });
        let (report, constraint) = discover_on_interface(
            &DiscoveryConfig {
                bind: SocketAddrV4::new(Ipv4Addr::LOCALHOST, 0),
                destination,
                timeout: Duration::from_millis(100),
                max_datagrams: 16,
                include_hidden: false,
            },
            "lo0",
            index,
        )
        .await
        .unwrap();
        responder.await.unwrap();
        assert_eq!(constraint.mechanism, "IP_BOUND_IF");
        assert_eq!(constraint.index, index);
        assert_eq!(report.devices.len(), 1);
    }

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
    async fn long_malformed_datagrams_keep_only_prefix_and_full_content_dedupe() {
        let peer = UdpSocket::bind((Ipv4Addr::LOCALHOST, 0)).await.unwrap();
        let peer_address = match peer.local_addr().unwrap() {
            SocketAddr::V4(value) => value,
            SocketAddr::V6(_) => unreachable!(),
        };
        let responder = tokio::spawn(async move {
            let mut query = [0u8; 64];
            let (_, source) = peer.recv_from(&mut query).await.unwrap();
            let first = vec![b'X'; 2_048];
            let mut second = first.clone();
            second[2_047] = b'Y';
            for payload in [&first[..], &first[..], &second[..]] {
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
        assert_eq!(report.datagrams_received, 3);
        assert_eq!(report.duplicates_ignored, 1);
        assert_eq!(report.malformed.len(), 2);
        for item in &report.malformed {
            assert_eq!(item.raw.len(), MAX_MALFORMED_RAW_PREFIX);
            assert_eq!(item.raw_length, 2_048);
            assert!(item.raw_truncated);
        }
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
