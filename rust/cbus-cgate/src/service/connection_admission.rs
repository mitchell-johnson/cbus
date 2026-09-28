//! Native command-listener admission for `accept-connections-from`.
//!
//! The owned build-2001 loopback oracle proves that `CONFIG SET` changes
//! admission for *new* command connections immediately, even though CONFIG
//! INFO advertises `effective=restart`. Existing sessions continue. A denied
//! TCP peer stays connected without a greeting or command reply for at least
//! fifteen seconds. This module implements the observed numeric-IP and `all`
//! slice, plus the captured `localhost` spelling; other unresolved hostnames
//! fail closed until independently captured.

use std::net::{IpAddr, Ipv4Addr};
use tokio::{io, net::TcpStream};

pub(super) fn accepts(value: &str, peer: IpAddr) -> bool {
    value == "all"
        || value
            .split_whitespace()
            .any(|part| match part.parse::<IpAddr>() {
                Ok(address) => address == peer,
                Err(_) => part == "localhost" && peer == IpAddr::V4(Ipv4Addr::LOCALHOST),
            })
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

    #[test]
    fn observed_ipv4_allow_and_deny_values() {
        let loopback = "127.0.0.1".parse().unwrap();
        assert!(accepts("all", loopback));
        assert!(accepts("127.0.0.1", loopback));
        assert!(!accepts("192.0.2.55", loopback));
        assert!(!accepts("", loopback));
        assert!(accepts("192.0.2.55 127.0.0.1", loopback));
        assert!(accepts("localhost", loopback));
        assert!(!accepts("unresolved.example", loopback));
    }
}
