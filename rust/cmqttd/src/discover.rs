//! mDNS discovery of ESP32 C-Bus bridges. Port of
//! `cbus/esp32/discovery.py`: browse `_cbus._tcp.local.` and connect to
//! the first device found (the Python daemon uses a 10 s window).

use std::time::{Duration, Instant};

/// Service type advertised by the ESP32 firmware.
pub const CBUS_MDNS_SERVICE_TYPE: &str = "_cbus._tcp.local.";

/// Default browse window (matches the Python daemon).
pub const DISCOVER_TIMEOUT: Duration = Duration::from_secs(10);

/// Browse for `timeout` and return the first resolved bridge as
/// `(host, port)`. Unlike Python (which always waits the full window and
/// then picks the first device), this returns as soon as one resolves.
pub fn discover_esp32(timeout: Duration) -> Result<(String, u16), String> {
    let mdns = mdns_sd::ServiceDaemon::new().map_err(|e| format!("mDNS init failed: {e}"))?;
    let receiver = mdns
        .browse(CBUS_MDNS_SERVICE_TYPE)
        .map_err(|e| format!("mDNS browse failed: {e}"))?;
    let deadline = Instant::now() + timeout;
    let mut found: Option<(String, u16)> = None;
    while found.is_none() {
        let now = Instant::now();
        if now >= deadline {
            break;
        }
        match receiver.recv_timeout(deadline - now) {
            Ok(mdns_sd::ServiceEvent::ServiceResolved(info)) => {
                // The address set mixes A and AAAA records (often IPv6
                // link-local, sometimes even the loopback interface's).
                // Python's zeroconf lists IPv4 first; do the same.
                let addrs = info.get_addresses();
                if let Some(addr) = addrs
                    .iter()
                    .find(|a| a.is_ipv4())
                    .or_else(|| addrs.iter().next())
                {
                    tracing::info!(
                        "discovered ESP32 C-Bus bridge {} at {}:{}",
                        info.get_fullname(),
                        addr,
                        info.get_port()
                    );
                    found = Some((addr.to_string(), info.get_port()));
                }
            }
            Ok(_) => {}
            Err(_) => break, // timeout or daemon gone
        }
    }
    let _ = mdns.shutdown();
    found.ok_or_else(|| "No ESP32 C-Bus bridge devices found on the network".into())
}
