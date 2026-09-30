//! Native command-listener admission for `accept-connections-from`.
//!
//! The owned build-2001 loopback oracle proves that `CONFIG SET` changes
//! admission for *new* command connections immediately, even though CONFIG
//! INFO advertises `effective=restart`. Existing sessions continue. A denied
//! TCP peer stays connected without a greeting or command reply for at least
//! fifteen seconds. This module implements the observed numeric-IP and `all`
//! slice, plus source-captured case-insensitive hostname resolution, an
//! IPv4-mapped IPv6 literal, and the corresponding mTLS pre-handshake gate.
//! DNS lookup is bounded and failed lookups deny new peers. The retained
//! Java server can remain denied after setting an unresolvable name and then
//! `all`; cmqttd intentionally recovers on `all` rather than reproducing
//! that native failure state.

use std::{
    net::{IpAddr, Ipv4Addr, Ipv6Addr},
    time::Duration,
};
use tokio::{io, net::TcpStream};

fn matches_address(allowed: IpAddr, peer: IpAddr) -> bool {
    // Dual-stack listeners report IPv4 clients as mapped IPv6 peers.
    // Normalize either side, so a numeric IPv4 allowlist works there too.
    allowed.to_canonical() == peer.to_canonical()
}

pub(super) async fn accepts(value: &str, peer: IpAddr) -> bool {
    let parts = value.split_whitespace().collect::<Vec<_>>();
    // Match literals first: an unrelated DNS outage must not prevent an
    // explicit numeric address or native case-insensitive `all` from working.
    if parts.iter().any(|part| part.eq_ignore_ascii_case("all"))
        || parts.iter().any(|part| {
            // localhost is a special-use loopback name, including its
            // absolute spelling. Do not depend on external DNS or whether
            // /etc/hosts happens to list the trailing-dot alias.
            ((part.eq_ignore_ascii_case("localhost") || part.eq_ignore_ascii_case("localhost."))
                && (matches_address(IpAddr::V4(Ipv4Addr::LOCALHOST), peer)
                    || matches_address(IpAddr::V6(Ipv6Addr::LOCALHOST), peer)))
                || part
                    .parse::<IpAddr>()
                    .is_ok_and(|allowed| matches_address(allowed, peer))
        })
    {
        return true;
    }

    // Native accepts DNS names such as LOCALHOST, localhost. and a separately
    // resolved loopback FQDN on both plain and TLS command listeners. Resolve
    // only names here, never host:port syntax; the address is the peer IP.
    tokio::time::timeout(Duration::from_secs(2), async {
        for part in parts {
            if part.parse::<IpAddr>().is_ok()
                || part.eq_ignore_ascii_case("localhost")
                || part.eq_ignore_ascii_case("localhost.")
            {
                continue;
            }
            if let Ok(mut addresses) = tokio::net::lookup_host((part, 0)).await {
                if addresses.any(|address| matches_address(address.ip(), peer)) {
                    return true;
                }
            }
        }
        false
    })
    .await
    .unwrap_or(false)
}

/// Native build 2001 leaves an explicitly denied command TCP connection
/// silent rather than writing 421 or immediately closing it. Keep the stream
/// open until the peer disconnects; the service's 64-slot listener bound also
/// applies to these sockets. No bytes reach command parsing, ACCESS, or PCI.
pub(super) async fn hold_silent(mut stream: TcpStream) -> io::Result<()> {
    io::copy(&mut stream, &mut io::sink()).await?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn observed_ipv4_hostname_mapped_and_ipv6_values() {
        let loopback = "127.0.0.1".parse().unwrap();
        let oracle: serde_json::Value = serde_json::from_str(include_str!(
            "../../../testdata/fixtures/native_cgate_config_hostname_tls_admission.json"
        ))
        .unwrap();
        assert_eq!(
            oracle["schema"],
            "native-cgate-config-hostname-tls-admission-v1"
        );
        assert_eq!(oracle["oracle"]["tls_cleanup"]["cleanup_complete"], true);
        for row in oracle["cases"].as_array().unwrap() {
            assert_eq!(row["cleanup"]["cleanup_complete"], true);
        }

        assert!(accepts("all", loopback).await);
        assert!(accepts("ALL", loopback).await);
        assert!(accepts("127.0.0.1", loopback).await);
        assert!(!accepts("192.0.2.55", loopback).await);
        assert!(!accepts("", loopback).await);
        assert!(accepts("192.0.2.55 127.0.0.1", loopback).await);
        assert!(accepts("localhost", loopback).await);
        assert!(accepts("LOCALHOST", loopback).await);
        assert!(accepts("localhost.", loopback).await);
        assert!(accepts("LOCALHOST.", "::1".parse().unwrap()).await);
        assert!(!accepts("localhost.", "192.0.2.55".parse().unwrap()).await);
        assert!(accepts("::ffff:127.0.0.1", loopback).await);
        let mapped = "::ffff:127.0.0.1".parse().unwrap();
        assert!(accepts("127.0.0.1", mapped).await);
        assert!(accepts("localhost.", mapped).await);
        assert!(!accepts("192.0.2.55", mapped).await);
        assert!(!accepts("::1", loopback).await);
        assert!(!accepts("unresolved.invalid", loopback).await);
        assert!(!accepts("127.0.0.1/8", loopback).await);
    }
}
