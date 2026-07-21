//! PCI client state machine. Port of `cbus/protocol/pciprotocol.py`:
//! confirmation-code allocator (round-robin, 30 s timeout, force cleanup),
//! byte-identical retransmit with jittered exponential backoff (max 3
//! attempts), and the exact PCI init sequence at its deployed-proven
//! fixed 0.1 s pacing. All post-init traffic is paced by the adaptive
//! flow controller in [`crate::flow`] instead of fixed delays.

use crate::flow::{self, AckSignal, Flow, FlowConfig, Priority, ResponseKind};
use cbus_protocol::cal::Cal;
use cbus_protocol::common::CONFIRMATION_CODES;
use cbus_protocol::packet::{Meta, Packet};
use cbus_protocol::report::StatusReport;
use cbus_protocol::sal::Sal;
use chrono::{Datelike, Timelike};
use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use std::time::Duration;
use tokio::io::{AsyncRead, AsyncReadExt, AsyncWrite, AsyncWriteExt};
use tokio::sync::{mpsc, watch};
// tokio's Instant (not std): identical on a live clock, but it follows
// the virtual clock in paused-time tests like the flow controller does.
use tokio::time::Instant;

use crate::framing::FrameBuffer;

/// A confirmation code still unanswered after this long is abandoned.
pub const CONFIRMATION_TIMEOUT: Duration = Duration::from_secs(30);
/// Total transmission attempts for an unconfirmed frame.
pub const MAX_PACKET_RETRIES: u32 = 3;
/// How often due retransmits/give-ups are checked for.
pub const RETRY_SWEEP_INTERVAL: Duration = Duration::from_millis(100);
/// Pause before each init-sequence write (deployed-proven pacing, pinned
/// by the harness init assertion; post-init traffic is flow-controlled).
pub const INIT_SEND_DELAY: Duration = Duration::from_millis(100);
const FORCE_CLEANUP_THRESHOLD: f64 = 0.9;
const FORCE_CLEANUP_PERCENTAGE: f64 = 0.25;

/// High-level events surfaced to the MQTT gateway (mirrors the
/// `PCIProtocol.on_*` handlers consumed by `mqtt_gateway.CBusHandler`).
#[derive(Debug, Clone, PartialEq)]
pub enum CBusEvent {
    /// A lighting group was switched on.
    LightingOn {
        /// Source unit address (`None` when the source byte was 0).
        source: Option<u8>,
        /// Lighting application address (0x30..=0x5F).
        app: u8,
        /// Group address.
        group: u8,
    },
    /// A lighting group was switched off.
    LightingOff {
        /// Source unit address (`None` when the source byte was 0).
        source: Option<u8>,
        /// Lighting application address (0x30..=0x5F).
        app: u8,
        /// Group address.
        group: u8,
    },
    /// A lighting group started ramping to a level.
    LightingRamp {
        /// Source unit address (`None` when the source byte was 0).
        source: Option<u8>,
        /// Lighting application address (0x30..=0x5F).
        app: u8,
        /// Group address.
        group: u8,
        /// Ramp duration in seconds (already snapped to the rate table).
        duration: u32,
        /// Target level 0..=255.
        level: u8,
    },
    /// An extended-status level report arrived.
    LevelReport {
        /// Child application the report describes.
        app: u8,
        /// First group address covered by the report.
        block_start: u8,
        /// One level per group; `None` = missing/undecodable.
        levels: Vec<Option<u8>>,
    },
    /// An extended-status binary report arrived.
    BinaryReport {
        /// Child application the report describes.
        app: u8,
        /// First group address covered by the report.
        block_start: u8,
        /// One `GroupState` per group: 0 missing, 1 on, 2 off, 3 error.
        states: Vec<u8>,
    },
    /// A unit asked for the network time.
    ClockRequest {
        /// Source unit address (`None` when the source byte was 0).
        source: Option<u8>,
    },
    /// The transport dropped; the client is dead and must be replaced.
    ConnectionLost,
}

struct Pending {
    data: Vec<u8>,
    attempts: u32,
    /// When the next retransmit (or the give-up after the final attempt)
    /// is due: jittered 1 s -> 2 s -> 4 s exponential backoff.
    next_retry: Instant,
}

#[derive(Default)]
struct PciState {
    next_confirmation_index: usize,
    codes_in_use: HashMap<u8, Instant>,
    pending: HashMap<u8, Pending>,
}

/// Write half of a connected transport.
pub type BoxedWrite = Box<dyn AsyncWrite + Send + Unpin>;
/// Read half of a connected transport.
pub type BoxedRead = Box<dyn AsyncRead + Send + Unpin>;

/// Async client for a C-Bus PCI/CNI. Port of `PCIProtocol`, with the
/// fixed post-init pacing replaced by the adaptive flow controller.
pub struct PciClient {
    /// Write half, shared with the flow-controller task (init frames
    /// write directly; everything else goes through the controller).
    writer: Arc<tokio::sync::Mutex<BoxedWrite>>,
    /// Ack-clocked pacing for all post-init traffic.
    flow: Flow,
    state: Mutex<PciState>,
    events: mpsc::UnboundedSender<CBusEvent>,
    /// Opens once `pci_reset` has finished: everything except the init
    /// frames themselves waits on this, so the init sequence hits the
    /// wire uninterrupted (`PCIProtocol._send` awaiting `_reset_task`).
    init_done: watch::Sender<bool>,
    /// Fair FIFO lane for non-init sends: frames blocked on the init
    /// gate enter the flow queues in the order `send` was called
    /// (asyncio wakes gate waiters FIFO; tokio's watch does not, so
    /// order it explicitly).
    send_lane: tokio::sync::Mutex<()>,
}

impl PciClient {
    /// Create a client over a connected transport. Spawns the reader
    /// loop, the flow-controller task and the retransmit task.
    /// `pci_reset()` must be invoked by the caller (mirrors
    /// `connection_made`).
    pub fn new(
        reader: BoxedRead,
        writer: BoxedWrite,
        events: mpsc::UnboundedSender<CBusEvent>,
    ) -> Arc<Self> {
        let writer = Arc::new(tokio::sync::Mutex::new(writer));
        let client = Arc::new(PciClient {
            flow: Flow::start(writer.clone(), FlowConfig::default()),
            writer,
            state: Mutex::new(PciState::default()),
            events,
            init_done: watch::Sender::new(false),
            send_lane: tokio::sync::Mutex::new(()),
        });
        tokio::spawn(Self::reader_loop(client.clone(), reader));
        tokio::spawn(Self::retry_task(client.clone()));
        client
    }

    // ------------------------------------------------------------ sending

    /// `PCIProtocol._send`: prepare (escape, confirmation char, CR),
    /// wait for the init gate (unless this IS an init frame), transmit
    /// (fixed-paced for init frames, flow-controlled for everything
    /// else), and register for retry when a confirmation was requested.
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

        // Only the frames pci_reset itself sends bypass the flow
        // controller (and the init gate): their fixed pacing is a
        // deployed-proven contract. Everything else queues behind init,
        // in send-call order (the lane is a fair FIFO mutex held until
        // the frame is in the flow queue).
        let init_frame = special || matches!(cmd, Packet::DeviceManagement { .. });
        let lane = if !init_frame {
            let lane = self.send_lane.lock().await;
            self.init_done
                .subscribe()
                .wait_for(|&done| done)
                .await
                .map_err(|_| std::io::Error::new(std::io::ErrorKind::BrokenPipe, "client gone"))?;
            Some(lane)
        } else {
            None
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

        if init_frame {
            self.send_init(&bytes).await?;
        } else {
            let (priority, kind) = classify(cmd, conf);
            let rx = self.flow.submit(bytes.clone(), priority, kind);
            // Enqueued: this sender's place in line is fixed, so let the
            // next caller queue up while we wait for the wire.
            drop(lane);
            rx.await.map_err(|_| {
                std::io::Error::new(std::io::ErrorKind::BrokenPipe, "flow controller gone")
            })??;
        }

        if let Some(code) = conf {
            let mut st = self.state.lock().unwrap();
            st.pending.insert(
                code,
                Pending {
                    data: bytes,
                    attempts: 1,
                    next_retry: Instant::now() + flow::jittered_backoff(1),
                },
            );
        }
        Ok(conf)
    }

    /// `PCIProtocol._send_packet` for the init sequence only: fixed
    /// 0.1 s pre-write delay. Post-init traffic goes through the flow
    /// controller instead.
    async fn send_init(&self, data: &[u8]) -> std::io::Result<()> {
        tokio::time::sleep(INIT_SEND_DELAY).await;
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

    /// `PCIProtocol._check_pending_confirmations` on a backoff schedule:
    /// resend byte-identical frames at jittered 1 s -> 2 s -> 4 s
    /// intervals (attempts capped at 3, then abandon+release, same
    /// give-up semantics as before). Retransmits go through the flow
    /// controller's unwindowed lane: no window slot, but the inter-frame
    /// floor and any `!` pause still apply.
    async fn retry_task(self: Arc<Self>) {
        loop {
            tokio::time::sleep(RETRY_SWEEP_INTERVAL).await;
            let now = Instant::now();
            let mut to_retry: Vec<Vec<u8>> = Vec::new();
            {
                let mut st = self.state.lock().unwrap();
                Self::check_and_release_timed_out(&mut st);

                let due: Vec<u8> = st
                    .pending
                    .iter()
                    .filter(|(_, p)| now >= p.next_retry)
                    .map(|(&code, _)| code)
                    .collect();
                for code in due {
                    let p = st.pending.get_mut(&code).expect("due code present");
                    if p.attempts < MAX_PACKET_RETRIES {
                        p.attempts += 1;
                        p.next_retry = now + flow::jittered_backoff(p.attempts);
                        tracing::info!(
                            "resending frame with confirmation code {:#04x}, attempt {}",
                            code,
                            p.attempts
                        );
                        to_retry.push(p.data.clone());
                    } else {
                        tracing::warn!(
                            "giving up on confirmation code {:#04x} after {} attempts",
                            code,
                            MAX_PACKET_RETRIES
                        );
                        st.pending.remove(&code);
                        st.codes_in_use.remove(&code);
                    }
                }
            }
            for data in to_retry {
                match self.flow.submit_unwindowed(data).await {
                    Ok(Ok(())) => {}
                    // transport dead or controller gone: this client is done
                    _ => return,
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
                {
                    let mut st = self.state.lock().unwrap();
                    st.pending.remove(&code);
                    st.codes_in_use.remove(&code);
                }
                // any confirmation (even success=false) is a response:
                // it releases the frame's flow-control slot
                self.flow.ack(AckSignal::Confirmation(code));
            }
            Packet::PciError => {
                // explicit congestion signal: the controller pauses all
                // sends and collapses the window
                tracing::debug!("PCI cannot accept data");
                self.flow.pci_error();
            }
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
                        report,
                        ..
                    } = c
                    {
                        // the first report matching a pending status
                        // request's app+block+kind acks that request
                        self.flow.ack(AckSignal::Report {
                            app: child_application,
                            block: block_start,
                            level: matches!(report, StatusReport::Level(_)),
                        });
                        let event = match report {
                            StatusReport::Level(levels) => CBusEvent::LevelReport {
                                app: child_application,
                                block_start,
                                levels,
                            },
                            StatusReport::Binary(states) => CBusEvent::BinaryReport {
                                app: child_application,
                                block_start,
                                states,
                            },
                        };
                        let _ = self.events.send(event);
                    }
                }
            }
            other => tracing::debug!("unhandled packet: {:?}", other),
        }
    }

    // ------------------------------------------------------ high-level API

    /// `PCIProtocol.pci_reset`: 3 resets, smart-connect shortcut, then the
    /// four basic-mode DM commands, all without confirmation chars (the
    /// PCI is still echoing in basic mode; asking for confirmations here
    /// triggers retry storms on real CNIs). Opens the init gate when done.
    pub async fn pci_reset(&self) -> std::io::Result<()> {
        let result = self.pci_reset_frames().await;
        // Open the gate even on failure: blocked senders then surface the
        // dead transport themselves instead of waiting forever.
        self.init_done.send_replace(true);
        result
    }

    async fn pci_reset_frames(&self) -> std::io::Result<()> {
        for _ in 0..3 {
            self.send(&Packet::Reset, false, true).await?;
        }
        self.send(&Packet::SmartConnect, false, true).await?;
        for (parameter, value) in [(0x21u8, 0xffu8), (0x22, 0xff), (0x42, 0x0e), (0x30, 0x79)] {
            self.send(
                &Packet::DeviceManagement {
                    meta: Meta::new(false, 2),
                    parameter,
                    value,
                },
                false,
                true,
            )
            .await?;
        }
        Ok(())
    }

    /// `PCIProtocol.lighting_group_on`: switch up to 9 groups on.
    pub async fn lighting_group_on(&self, groups: &[u8], app: u8) -> std::io::Result<Option<u8>> {
        self.send_lighting(groups, app, |application, group_address| Sal::LightingOn {
            application,
            group_address,
        })
        .await
    }

    /// `PCIProtocol.lighting_group_off`: switch up to 9 groups off.
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

    /// `PCIProtocol.lighting_group_ramp`: ramp one group to a level.
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

    /// `PCIProtocol.request_status`: binary or level status request for
    /// one block. Status reports are their own replies; asking the CNI
    /// for command confirmations here creates a large retry backlog on
    /// slow hardware, so these frames are sent without a confirmation.
    pub async fn request_status(
        &self,
        block: u8,
        app: u8,
        level_request: bool,
    ) -> std::io::Result<Option<u8>> {
        let p = Packet::PointToMultipoint {
            meta: Meta::new(true, 0),
            application: 0xff,
            sals: vec![Sal::StatusRequest {
                level_request,
                group_address: block,
                child_application: app,
            }],
        };
        self.send(&p, false, false).await
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

/// Flow-control classification of an outbound frame: user commands
/// (lighting operations, i.e. MQTT /set traffic) outrank background
/// frames, and the response that will release the frame's window slot
/// is derived from what the device observably sends back.
fn classify(cmd: &Packet, conf: Option<u8>) -> (Priority, ResponseKind) {
    let is_lighting = |s: &Sal| {
        matches!(
            s,
            Sal::LightingOn { .. } | Sal::LightingOff { .. } | Sal::LightingRamp { .. }
        )
    };
    let priority = match cmd {
        Packet::PointToMultipoint { sals, .. } if sals.iter().any(is_lighting) => Priority::Command,
        _ => Priority::Background,
    };
    let kind = if let Some(code) = conf {
        ResponseKind::Confirmation(code)
    } else if let Packet::PointToMultipoint { sals, .. } = cmd {
        // status requests are sent one per frame (request_status)
        match sals.first() {
            Some(Sal::StatusRequest {
                level_request,
                group_address,
                child_application,
            }) => ResponseKind::Report {
                app: *child_application,
                block: *group_address,
                level: *level_request,
            },
            _ => ResponseKind::Silent,
        }
    } else {
        ResponseKind::Silent
    };
    (priority, kind)
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
        // deployed-faithful: no confirmation chars anywhere in the init
        // sequence (the PCI is still echoing in basic mode)
        assert!(
            s.starts_with("~\r~\r~\r|\rA32100FF\rA32200FF\rA342000E\rA3300079\r"),
            "unexpected init sequence: {s:?}"
        );
    }

    #[tokio::test]
    async fn status_requests_are_codeless_binary_and_level() {
        let (client_side, mut pci_side) = tokio::io::duplex(4096);
        let (rd, wr) = tokio::io::split(client_side);
        let (tx, _rx) = mpsc::unbounded_channel();
        let pci = PciClient::new(Box::new(rd), Box::new(wr), tx);
        pci.pci_reset().await.unwrap();
        read_available(&mut pci_side, 200).await; // drain the init frames
        assert_eq!(pci.request_status(0, 0x38, false).await.unwrap(), None);
        assert_eq!(pci.request_status(0, 0x38, true).await.unwrap(), None);
        let got = read_available(&mut pci_side, 300).await;
        let s = String::from_utf8_lossy(&got);
        assert_eq!(s, "\\05FF007A38004A\r\\05FF00730738004A\r");
        // nothing was registered for retry: no retransmits follow
        tokio::time::sleep(Duration::from_millis(2500)).await;
        let got = read_available(&mut pci_side, 200).await;
        assert!(
            got.is_empty(),
            "codeless status requests must not retransmit: {:?}",
            String::from_utf8_lossy(&got)
        );
    }

    #[tokio::test]
    async fn init_gate_holds_noninit_traffic_until_reset_completes() {
        let (client_side, mut pci_side) = tokio::io::duplex(4096);
        let (rd, wr) = tokio::io::split(client_side);
        let (tx, _rx) = mpsc::unbounded_channel();
        let pci = PciClient::new(Box::new(rd), Box::new(wr), tx);
        // traffic issued while the init sequence has not even started yet
        let p = pci.clone();
        let sr = tokio::spawn(async move { p.request_status(0, 0x38, true).await });
        let p = pci.clone();
        let cmd = tokio::spawn(async move { p.lighting_group_on(&[1], 0x38).await });
        tokio::time::sleep(Duration::from_millis(300)).await;
        let early = read_available(&mut pci_side, 100).await;
        assert!(
            early.is_empty(),
            "traffic leaked before init: {:?}",
            String::from_utf8_lossy(&early)
        );
        pci.pci_reset().await.unwrap();
        sr.await.unwrap().unwrap();
        cmd.await.unwrap().unwrap();
        let got = read_available(&mut pci_side, 300).await;
        let s = String::from_utf8_lossy(&got);
        let init = "~\r~\r~\r|\rA32100FF\rA32200FF\rA342000E\rA3300079\r";
        assert!(s.starts_with(init), "init must lead the stream: {s:?}");
        let rest = &s[init.len()..];
        assert!(
            rest.contains("\\05FF00730738004A\r"),
            "status request missing: {s:?}"
        );
        assert!(
            rest.contains("\\053800790149h\r"),
            "lighting command missing: {s:?}"
        );
    }

    #[tokio::test(start_paused = true)]
    async fn confirmation_releases_and_stops_retry() {
        let (client_side, mut pci_side) = tokio::io::duplex(4096);
        let (rd, wr) = tokio::io::split(client_side);
        let (tx, _rx) = mpsc::unbounded_channel();
        let pci = PciClient::new(Box::new(rd), Box::new(wr), tx);
        pci.pci_reset().await.unwrap();
        let code = pci.lighting_group_on(&[1], 0x38).await.unwrap().unwrap();
        assert_eq!(code, b'h');
        let first = read_available(&mut pci_side, 300).await;
        assert!(!first.is_empty());
        // deliver the confirmation; the pending frame must not be resent
        // (first backoff fires no earlier than 0.8s after transmission)
        tokio::io::AsyncWriteExt::write_all(&mut pci_side, b"h.")
            .await
            .unwrap();
        tokio::time::sleep(Duration::from_millis(6000)).await;
        let got = read_available(&mut pci_side, 200).await;
        assert!(
            got.is_empty(),
            "unexpected retransmit after confirmation: {:?}",
            String::from_utf8_lossy(&got)
        );
    }

    #[tokio::test]
    async fn allocator_survives_exhaustion_pressure() {
        let (client_side, _pci_side) = tokio::io::duplex(4096);
        let (rd, wr) = tokio::io::split(client_side);
        let (tx, _rx) = mpsc::unbounded_channel();
        let pci = PciClient::new(Box::new(rd), Box::new(wr), tx);
        // Nothing ever confirms; the >90% force-cleanup and the
        // exhaustion fallback must keep yielding valid codes without
        // panicking or spinning.
        let mut codes = Vec::new();
        for _ in 0..64 {
            codes.push(pci.get_confirmation_code());
        }
        assert!(codes.iter().all(|c| CONFIRMATION_CODES.contains(c)));
        // the first 19 allocations are distinct (force cleanup starts
        // when >90% of the 20-code pool is in use)
        let mut first19 = codes[..19].to_vec();
        first19.sort_unstable();
        first19.dedup();
        assert_eq!(first19.len(), 19);
    }

    #[tokio::test(start_paused = true)]
    async fn retry_unconfirmed_backoff_three_attempts_then_abandon() {
        let (client_side, mut pci_side) = tokio::io::duplex(4096);
        let (rd, wr) = tokio::io::split(client_side);
        let (tx, _rx) = mpsc::unbounded_channel();
        let pci = PciClient::new(Box::new(rd), Box::new(wr), tx);
        pci.pci_reset().await.unwrap();
        pci.lighting_group_on(&[1], 0x38).await.unwrap();
        let frame = "\\053800790149h\r";
        // withhold confirmation: byte-identical retransmits back off at
        // jittered 1s then 2s (+100ms sweep granularity each)
        tokio::time::sleep(Duration::from_millis(500)).await;
        let got = read_available(&mut pci_side, 100).await;
        let s = String::from_utf8_lossy(&got).to_string();
        assert_eq!(
            s.matches(frame).count(),
            1,
            "no retransmit before the 0.8s jitter floor: {s:?}"
        );
        // worst case: retry2 at 1.3s, retry3 at 1.3+2.5=3.8s
        tokio::time::sleep(Duration::from_millis(3400)).await;
        let got = read_available(&mut pci_side, 100).await;
        let s = String::from_utf8_lossy(&got).to_string();
        assert_eq!(s.matches(frame).count(), 2, "got: {s:?}");
        // after 3 total attempts the code is abandoned (give-up due at
        // worst 3.8s + 4.9s): no fourth transmission ever
        tokio::time::sleep(Duration::from_millis(5500)).await;
        let got = read_available(&mut pci_side, 100).await;
        assert!(
            got.is_empty(),
            "unexpected 4th attempt: {:?}",
            String::from_utf8_lossy(&got)
        );
        // the give-up released the confirmation code
        assert!(pci.state.lock().unwrap().codes_in_use.is_empty());
        assert!(pci.state.lock().unwrap().pending.is_empty());
    }

    #[test]
    fn classify_priorities_and_response_kinds() {
        // lighting command with a code: user priority, conf-released
        let cmd = Packet::PointToMultipoint {
            meta: Meta::new(true, 0),
            application: 0x38,
            sals: vec![Sal::LightingOn {
                application: 0x38,
                group_address: 1,
            }],
        };
        assert_eq!(
            classify(&cmd, Some(b'h')),
            (Priority::Command, ResponseKind::Confirmation(b'h'))
        );
        // codeless status request: background, released by the first
        // report matching app+block+kind
        let sr = Packet::PointToMultipoint {
            meta: Meta::new(true, 0),
            application: 0xff,
            sals: vec![Sal::StatusRequest {
                level_request: true,
                group_address: 0x20,
                child_application: 0x38,
            }],
        };
        assert_eq!(
            classify(&sr, None),
            (
                Priority::Background,
                ResponseKind::Report {
                    app: 0x38,
                    block: 0x20,
                    level: true
                }
            )
        );
        // confirmed clock update: background but conf-released
        let clock = Packet::PointToMultipoint {
            meta: Meta::new(true, 0),
            application: 0xdf,
            sals: vec![Sal::ClockUpdateTime {
                hour: 1,
                minute: 2,
                second: 3,
            }],
        };
        assert_eq!(
            classify(&clock, Some(b'g')),
            (Priority::Background, ResponseKind::Confirmation(b'g'))
        );
        // a codeless frame with no observable response: short slot hold
        assert_eq!(classify(&clock, None).1, ResponseKind::Silent);
    }
}
