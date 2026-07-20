//! PCI client state machine. Port of `cbus/protocol/pciprotocol.py`:
//! confirmation-code allocator (round-robin, 30 s timeout, force cleanup),
//! byte-identical retransmit every 1 s (max 3 attempts), 0.1 s pre-write
//! delay, and the exact PCI init sequence.

use cbus_protocol::cal::Cal;
use cbus_protocol::common::CONFIRMATION_CODES;
use cbus_protocol::packet::{Meta, Packet};
use cbus_protocol::report::StatusReport;
use cbus_protocol::sal::Sal;
use chrono::{Datelike, Timelike};
use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};
use tokio::io::{AsyncRead, AsyncReadExt, AsyncWrite, AsyncWriteExt};
use tokio::sync::mpsc;

use crate::framing::FrameBuffer;

pub const CONFIRMATION_TIMEOUT: Duration = Duration::from_secs(30);
pub const MAX_PACKET_RETRIES: u32 = 3;
pub const RETRY_INTERVAL: Duration = Duration::from_secs(1);
pub const PACKET_SEND_DELAY: Duration = Duration::from_millis(100);
const FORCE_CLEANUP_THRESHOLD: f64 = 0.9;
const FORCE_CLEANUP_PERCENTAGE: f64 = 0.25;

/// High-level events surfaced to the MQTT gateway (mirrors the
/// `PCIProtocol.on_*` handlers consumed by `mqtt_gateway.CBusHandler`).
#[derive(Debug, Clone, PartialEq)]
pub enum CBusEvent {
    LightingOn {
        source: Option<u8>,
        app: u8,
        group: u8,
    },
    LightingOff {
        source: Option<u8>,
        app: u8,
        group: u8,
    },
    LightingRamp {
        source: Option<u8>,
        app: u8,
        group: u8,
        duration: u32,
        level: u8,
    },
    LevelReport {
        app: u8,
        block_start: u8,
        levels: Vec<Option<u8>>,
    },
    ClockRequest {
        source: Option<u8>,
    },
    ConnectionLost,
}

struct Pending {
    data: Vec<u8>,
    attempts: u32,
    last_attempt: Instant,
}

#[derive(Default)]
struct PciState {
    next_confirmation_index: usize,
    codes_in_use: HashMap<u8, Instant>,
    pending: HashMap<u8, Pending>,
}

pub type BoxedWrite = Box<dyn AsyncWrite + Send + Unpin>;
pub type BoxedRead = Box<dyn AsyncRead + Send + Unpin>;

pub struct PciClient {
    writer: tokio::sync::Mutex<BoxedWrite>,
    state: Mutex<PciState>,
    events: mpsc::UnboundedSender<CBusEvent>,
}

impl PciClient {
    /// Create a client over a connected transport. Spawns the reader loop
    /// and the 1 s retry task. `pci_reset()` must be invoked by the caller
    /// (mirrors `connection_made`).
    pub fn new(
        reader: BoxedRead,
        writer: BoxedWrite,
        events: mpsc::UnboundedSender<CBusEvent>,
    ) -> Arc<Self> {
        let client = Arc::new(PciClient {
            writer: tokio::sync::Mutex::new(writer),
            state: Mutex::new(PciState::default()),
            events,
        });
        tokio::spawn(Self::reader_loop(client.clone(), reader));
        tokio::spawn(Self::retry_task(client.clone()));
        client
    }

    // ------------------------------------------------------------ sending

    /// `PCIProtocol._send`: prepare (escape, confirmation char, CR),
    /// transmit, and register for retry when a confirmation was requested.
    pub async fn send(
        &self,
        cmd: &Packet,
        confirmation: bool,
        basic_mode: bool,
    ) -> std::io::Result<Option<u8>> {
        // SpecialClientPacket: always basic mode, never confirmed
        let special = matches!(cmd, Packet::Reset | Packet::SmartConnect);
        let (confirmation, basic_mode) = if special {
            (false, true)
        } else {
            (confirmation, basic_mode)
        };

        let mut bytes = cmd
            .encode_packet()
            .map_err(|e| std::io::Error::new(std::io::ErrorKind::InvalidInput, e.0))?;
        if !basic_mode {
            bytes.insert(0, b'\\');
        }
        let conf = if confirmation {
            let code = self.get_confirmation_code();
            bytes.push(code);
            Some(code)
        } else {
            None
        };
        bytes.extend_from_slice(b"\r");

        self.send_raw(&bytes).await?;

        if let Some(code) = conf {
            let mut st = self.state.lock().unwrap();
            st.pending.insert(
                code,
                Pending {
                    data: bytes,
                    attempts: 1,
                    last_attempt: Instant::now(),
                },
            );
        }
        Ok(conf)
    }

    /// `PCIProtocol._send_packet`: 0.1 s delay then write (the CNI is slow).
    async fn send_raw(&self, data: &[u8]) -> std::io::Result<()> {
        tokio::time::sleep(PACKET_SEND_DELAY).await;
        let mut w = self.writer.lock().await;
        w.write_all(data).await?;
        w.flush().await
    }

    // --------------------------------------------- confirmation allocator

    /// `PCIProtocol._get_confirmation_code`
    fn get_confirmation_code(&self) -> u8 {
        let mut st = self.state.lock().unwrap();
        Self::check_and_release_timed_out(&mut st);

        for _ in 0..CONFIRMATION_CODES.len() {
            let code = CONFIRMATION_CODES[st.next_confirmation_index];
            st.next_confirmation_index =
                (st.next_confirmation_index + 1) % CONFIRMATION_CODES.len();
            if let std::collections::hash_map::Entry::Vacant(e) = st.codes_in_use.entry(code) {
                e.insert(Instant::now());
                return code;
            }
        }

        // all in use: force release the oldest, then take the next available
        tracing::warn!("all confirmation codes in use, releasing oldest");
        if let Some((&oldest, _)) = st.codes_in_use.iter().min_by_key(|(_, &t)| t) {
            st.codes_in_use.remove(&oldest);
            st.pending.remove(&oldest);
            for _ in 0..CONFIRMATION_CODES.len() {
                let code = CONFIRMATION_CODES[st.next_confirmation_index];
                st.next_confirmation_index =
                    (st.next_confirmation_index + 1) % CONFIRMATION_CODES.len();
                if code != oldest && !st.codes_in_use.contains_key(&code) {
                    st.codes_in_use.insert(code, Instant::now());
                    return code;
                }
            }
            st.codes_in_use.insert(oldest, Instant::now());
            oldest
        } else {
            let code = CONFIRMATION_CODES[0];
            st.codes_in_use.insert(code, Instant::now());
            code
        }
    }

    /// `PCIProtocol._check_and_release_timed_out_codes`
    fn check_and_release_timed_out(st: &mut PciState) {
        let now = Instant::now();
        let timed_out: Vec<u8> = st
            .codes_in_use
            .iter()
            .filter(|(_, &t)| now.duration_since(t) > CONFIRMATION_TIMEOUT)
            .map(|(&c, _)| c)
            .collect();
        for code in timed_out {
            tracing::warn!("confirmation code {:#04x} timed out", code);
            st.codes_in_use.remove(&code);
            st.pending.remove(&code);
        }
        // force cleanup of the oldest 25% when >90% of codes in use
        let threshold = (CONFIRMATION_CODES.len() as f64 * FORCE_CLEANUP_THRESHOLD) as usize;
        if st.codes_in_use.len() > threshold {
            let mut by_age: Vec<(u8, Instant)> =
                st.codes_in_use.iter().map(|(&c, &t)| (c, t)).collect();
            by_age.sort_by_key(|&(_, t)| t);
            let release_count = ((by_age.len() as f64 * FORCE_CLEANUP_PERCENTAGE) as usize).max(1);
            for &(code, _) in by_age.iter().take(release_count) {
                tracing::warn!("force releasing confirmation code {:#04x}", code);
                st.codes_in_use.remove(&code);
                st.pending.remove(&code);
            }
        }
    }

    // -------------------------------------------------------- retry task

    /// `PCIProtocol._check_pending_confirmations`: every 1 s, resend
    /// byte-identical frames (attempts capped at 3, then abandon+release).
    async fn retry_task(self: Arc<Self>) {
        loop {
            tokio::time::sleep(RETRY_INTERVAL).await;
            let now = Instant::now();
            let mut to_retry: Vec<(u8, Vec<u8>)> = Vec::new();
            {
                let mut st = self.state.lock().unwrap();
                Self::check_and_release_timed_out(&mut st);

                let mut to_abandon: Vec<u8> = Vec::new();
                for (&code, p) in st.pending.iter() {
                    if now.duration_since(p.last_attempt) >= RETRY_INTERVAL {
                        if p.attempts < MAX_PACKET_RETRIES {
                            to_retry.push((code, p.data.clone()));
                        } else {
                            to_abandon.push(code);
                        }
                    }
                }
                for code in to_abandon {
                    tracing::warn!(
                        "giving up on confirmation code {:#04x} after {} attempts",
                        code,
                        MAX_PACKET_RETRIES
                    );
                    st.pending.remove(&code);
                    st.codes_in_use.remove(&code);
                }
                for (code, _) in &to_retry {
                    if let Some(p) = st.pending.get_mut(code) {
                        p.attempts += 1;
                        p.last_attempt = now;
                        tracing::info!(
                            "resending frame with confirmation code {:#04x}, attempt {}",
                            code,
                            p.attempts
                        );
                    }
                }
            }
            for (_, data) in to_retry {
                if self.send_raw(&data).await.is_err() {
                    return;
                }
            }
        }
    }

    // -------------------------------------------------------- reader loop

    async fn reader_loop(self: Arc<Self>, mut reader: BoxedRead) {
        let mut fb = FrameBuffer::new_client();
        let mut buf = [0u8; 4096];
        loop {
            match reader.read(&mut buf).await {
                Ok(0) | Err(_) => break,
                Ok(n) => {
                    for ev in fb.feed(&buf[..n]) {
                        if let Some(p) = ev.packet {
                            self.handle_cbus_packet(p);
                        }
                    }
                }
            }
        }
        tracing::warn!("connection to PCI lost");
        let _ = self.events.send(CBusEvent::ConnectionLost);
    }

    /// `PCIProtocol.handle_cbus_packet` event dispatch.
    fn handle_cbus_packet(&self, p: Packet) {
        match p {
            Packet::Confirmation { code, success } => {
                tracing::debug!("confirmation: code {:#04x} success {}", code, success);
                let mut st = self.state.lock().unwrap();
                st.pending.remove(&code);
                st.codes_in_use.remove(&code);
            }
            Packet::PciError => tracing::debug!("PCI cannot accept data"),
            Packet::PowerOn => tracing::debug!("PCI power-up notification"),
            Packet::PointToMultipoint { meta, sals, .. } => {
                for s in sals {
                    let src = meta.source_address;
                    let event = match s {
                        Sal::LightingRamp {
                            application,
                            group_address,
                            duration,
                            level,
                        } => Some(CBusEvent::LightingRamp {
                            source: src,
                            app: application,
                            group: group_address,
                            duration,
                            level,
                        }),
                        Sal::LightingOn {
                            application,
                            group_address,
                        } => Some(CBusEvent::LightingOn {
                            source: src,
                            app: application,
                            group: group_address,
                        }),
                        Sal::LightingOff {
                            application,
                            group_address,
                        } => Some(CBusEvent::LightingOff {
                            source: src,
                            app: application,
                            group: group_address,
                        }),
                        Sal::ClockRequest => Some(CBusEvent::ClockRequest { source: src }),
                        _ => None,
                    };
                    if let Some(e) = event {
                        let _ = self.events.send(e);
                    }
                }
            }
            Packet::PointToPoint { cals, .. } => {
                for c in cals {
                    if let Cal::ExtendedStatus {
                        child_application,
                        block_start,
                        report: StatusReport::Level(levels),
                        ..
                    } = c
                    {
                        // binary reports are ignored (Python passes on them)
                        let _ = self.events.send(CBusEvent::LevelReport {
                            app: child_application,
                            block_start,
                            levels,
                        });
                    }
                }
            }
            other => tracing::debug!("unhandled packet: {:?}", other),
        }
    }

    // ------------------------------------------------------ high-level API

    /// `PCIProtocol.pci_reset`: 3 resets, smart-connect shortcut, then the
    /// four basic-mode DM commands (each with a confirmation char).
    pub async fn pci_reset(&self) -> std::io::Result<()> {
        for _ in 0..3 {
            self.send(&Packet::Reset, true, false).await?;
        }
        self.send(&Packet::SmartConnect, true, false).await?;
        for (parameter, value) in [(0x21u8, 0xffu8), (0x22, 0xff), (0x42, 0x0e), (0x30, 0x79)] {
            self.send(
                &Packet::DeviceManagement {
                    meta: Meta::new(false, 2),
                    parameter,
                    value,
                },
                true,
                true,
            )
            .await?;
        }
        Ok(())
    }

    pub async fn lighting_group_on(&self, groups: &[u8], app: u8) -> std::io::Result<Option<u8>> {
        self.send_lighting(groups, app, |application, group_address| Sal::LightingOn {
            application,
            group_address,
        })
        .await
    }

    pub async fn lighting_group_off(&self, groups: &[u8], app: u8) -> std::io::Result<Option<u8>> {
        self.send_lighting(groups, app, |application, group_address| Sal::LightingOff {
            application,
            group_address,
        })
        .await
    }

    async fn send_lighting(
        &self,
        groups: &[u8],
        app: u8,
        make: impl Fn(u8, u8) -> Sal,
    ) -> std::io::Result<Option<u8>> {
        let p = Packet::PointToMultipoint {
            meta: Meta::new(true, 0),
            application: app,
            sals: groups.iter().map(|&g| make(app, g)).collect(),
        };
        self.send(&p, true, false).await
    }

    pub async fn lighting_group_ramp(
        &self,
        group: u8,
        app: u8,
        duration: u32,
        level: u8,
    ) -> std::io::Result<Option<u8>> {
        let p = Packet::PointToMultipoint {
            meta: Meta::new(true, 0),
            application: app,
            sals: vec![Sal::LightingRamp {
                application: app,
                group_address: group,
                duration,
                level,
            }],
        };
        self.send(&p, true, false).await
    }

    pub async fn request_status(&self, block: u8, app: u8) -> std::io::Result<Option<u8>> {
        let p = Packet::PointToMultipoint {
            meta: Meta::new(true, 0),
            application: 0xff,
            sals: vec![Sal::StatusRequest {
                level_request: true,
                group_address: block,
                child_application: app,
            }],
        };
        self.send(&p, true, false).await
    }

    /// `PCIProtocol.clock_datetime`: one PM packet, date SAL then time SAL.
    pub async fn clock_datetime(&self) -> std::io::Result<Option<u8>> {
        let now = chrono::Local::now();
        let p = Packet::PointToMultipoint {
            meta: Meta::new(true, 0),
            application: 0xdf,
            sals: vec![
                Sal::ClockUpdateDate {
                    year: now.year() as u16,
                    month: now.month() as u8,
                    day: now.day() as u8,
                },
                Sal::ClockUpdateTime {
                    hour: now.hour() as u8,
                    minute: now.minute() as u8,
                    second: now.second() as u8,
                },
            ],
        };
        self.send(&p, true, false).await
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    async fn read_available(read: &mut tokio::io::DuplexStream, ms: u64) -> Vec<u8> {
        let mut out = Vec::new();
        let mut buf = [0u8; 1024];
        loop {
            match tokio::time::timeout(
                Duration::from_millis(ms),
                tokio::io::AsyncReadExt::read(read, &mut buf),
            )
            .await
            {
                Ok(Ok(n)) if n > 0 => out.extend_from_slice(&buf[..n]),
                _ => break,
            }
        }
        out
    }

    #[tokio::test]
    async fn init_sequence_bytes() {
        let (client_side, mut pci_side) = tokio::io::duplex(4096);
        let (rd, wr) = tokio::io::split(client_side);
        let (tx, _rx) = mpsc::unbounded_channel();
        let pci = PciClient::new(Box::new(rd), Box::new(wr), tx);
        pci.pci_reset().await.unwrap();
        let got = read_available(&mut pci_side, 300).await;
        let s = String::from_utf8_lossy(&got);
        assert!(
            s.starts_with("~\r~\r~\r|\rA32100FFh\rA32200FFi\rA342000Ej\rA3300079k\r"),
            "unexpected init sequence: {s:?}"
        );
    }

    #[tokio::test]
    async fn retry_unconfirmed_identical() {
        let (client_side, mut pci_side) = tokio::io::duplex(4096);
        let (rd, wr) = tokio::io::split(client_side);
        let (tx, _rx) = mpsc::unbounded_channel();
        let pci = PciClient::new(Box::new(rd), Box::new(wr), tx);
        pci.request_status(0, 0x30).await.unwrap();
        // withhold confirmation; retries land at ~2.1s and ~3.1s (the 1s
        // sweep sees elapsed 0.9s on its first tick, like Python)
        tokio::time::sleep(Duration::from_millis(3600)).await;
        let got = read_available(&mut pci_side, 200).await;
        let s = String::from_utf8_lossy(&got).to_string();
        let frame = "\\05FF007307300052h\r";
        assert_eq!(s.matches(frame).count(), 3, "got: {s:?}");
        // after 3 attempts the code is abandoned and released
        tokio::time::sleep(Duration::from_millis(1200)).await;
        let got = read_available(&mut pci_side, 200).await;
        assert!(got.is_empty());
    }
}
