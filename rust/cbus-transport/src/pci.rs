//! PCI client state machine:
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
use cbus_protocol::sal::{
    aircon::{AirconCommand, AirconStatus},
    Sal,
};
use chrono::{Datelike, Timelike};
use std::collections::{HashMap, HashSet};
use std::sync::{Arc, Mutex, Weak};
use std::time::Duration;
use tokio::io::{AsyncRead, AsyncReadExt, AsyncWrite, AsyncWriteExt};
use tokio::sync::{broadcast, mpsc, watch};
// tokio's Instant (not std): identical on a live clock, but it follows
// the virtual clock in paused-time tests like the flow controller does.
use tokio::time::Instant;

use crate::framing::FrameBuffer;

mod mmi;
mod programming;

/// Holds both local commissioning lanes across a complete observation.
/// Ordinary SAL traffic is deliberately outside this scope.
pub(crate) struct CommissioningObservation<'a> {
    client: &'a PciClient,
    _mmi: tokio::sync::MutexGuard<'a, ()>,
    _programming: tokio::sync::MutexGuard<'a, ()>,
}

impl CommissioningObservation<'_> {
    pub(crate) async fn install_mmi(&self) -> std::io::Result<Vec<u8>> {
        self.client.install_mmi_inner().await
    }

    pub(crate) async fn identify_serials(&self, unit: u8) -> std::io::Result<Vec<Vec<u8>>> {
        self.client.identify_collect_inner(unit, 4, false).await
    }
}

/// Native C-Gate GOC programming dialect and its wire-size limits.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum GocProgramming {
    /// Legacy GOC block transport (ten-byte stores, six-byte recalls).
    Goc,
    /// Byte-oriented GOC transport (ten-byte stores, six-byte recalls).
    GocByt,
    /// GOC2 transport (eleven-byte stores, up to 255-byte recalls).
    Goc2,
}

impl GocProgramming {
    fn store_limit(self) -> usize {
        match self {
            Self::Goc | Self::GocByt => 10,
            Self::Goc2 => 11,
        }
    }

    fn recall_limit(self) -> usize {
        match self {
            Self::Goc | Self::GocByt => 6,
            Self::Goc2 => u8::MAX as usize,
        }
    }
}

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
    /// One AIRCON command observed on the shared PCI receive stream.
    AirconCommand {
        /// Source unit address (`None` when the source byte was 0).
        source: Option<u8>,
        /// Fully decoded command/event payload.
        command: AirconCommand,
    },
    /// One AIRCON device status observed on the shared PCI receive stream.
    AirconStatus {
        /// Source unit address (`None` when the source byte was 0).
        source: Option<u8>,
        /// Fully decoded status/report payload.
        status: AirconStatus,
    },
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
    /// A Trigger Control action was observed.
    TriggerEvent {
        /// Source unit address (`None` when the source byte was 0).
        source: Option<u8>,
        /// Trigger group address.
        group: u8,
        /// Action selector.
        selector: u8,
    },
    /// A Trigger Control indicator-kill was observed.
    TriggerIndicatorKill {
        /// Source unit address (`None` when the source byte was 0).
        source: Option<u8>,
        /// Trigger group address.
        group: u8,
    },
    /// An Enable Control variable update was observed.
    EnableSet {
        /// Source unit address (`None` when the source byte was 0).
        source: Option<u8>,
        /// Enable variable address.
        variable: u8,
        /// New variable value.
        value: u8,
    },
    /// One exact dynamic-label SAL observed on the network. Higher layers may
    /// assemble Unicode or dynamic-icon transactions, while retaining the raw
    /// payload so an incomplete observation is never presented as a cache read.
    DynamicLabel {
        /// Source unit address (`None` when the source byte was 0).
        source: Option<u8>,
        /// Target application (Lighting, Trigger Control, or Enable Control).
        application: u8,
        /// Complete length-prefixed dynamic-label SAL payload.
        payload: Vec<u8>,
    },
    /// A Temperature Broadcast value was observed.
    TemperatureBroadcast {
        /// Source unit address (`None` when the source byte was 0).
        source: Option<u8>,
        /// Temperature group address.
        group: u8,
        /// Decoded temperature in degrees Celsius.
        temperature: f64,
    },
    /// A clock date update was observed.
    ClockDate {
        /// Source unit address (`None` when the source byte was 0).
        source: Option<u8>,
        /// Four-digit year.
        year: u16,
        /// Month 1..=12.
        month: u8,
        /// Day of month.
        day: u8,
    },
    /// A clock time update was observed.
    ClockTime {
        /// Source unit address (`None` when the source byte was 0).
        source: Option<u8>,
        /// Hour 0..=23.
        hour: u8,
        /// Minute 0..=59.
        minute: u8,
        /// Second 0..=59.
        second: u8,
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
    queued_retry: Option<Arc<flow::WriteProgress>>,
}

impl Drop for Pending {
    fn drop(&mut self) {
        if let Some(progress) = &self.queued_retry {
            progress.cancel_before_start();
        }
    }
}

// Retained after Pending is removed: every started retry can still produce
// another ACK, including earlier retries whose writes already completed.
struct RetryWrites {
    allocation_id: u64,
    writes: Vec<Arc<flow::WriteProgress>>,
}

#[derive(Default)]
struct PciState {
    next_confirmation_index: usize,
    codes_in_use: HashMap<u8, Instant>,
    pending: HashMap<u8, Pending>,
    next_allocation_id: u64,
    allocation_ids: HashMap<u8, u64>,
    active_allocations: HashMap<u8, u64>,
    quarantined_codes: HashSet<u8>,
    retry_writes: HashMap<u8, RetryWrites>,
}

// Own allocation until send has returned successfully. A generation prevents
// cancellation from clearing an unrelated command that reused the same code.
struct ConfirmationAllocation<'a> {
    client: &'a PciClient,
    code: u8,
    id: u64,
    retained: bool,
    progress: Arc<flow::WriteProgress>,
}

impl ConfirmationAllocation<'_> {
    fn retain(&mut self, bytes: Vec<u8>) {
        let code = self.code;
        let mut st = self.client.state.lock().unwrap();
        // A fast PCI can confirm before the write future resumes.
        // Do not resurrect an already acknowledged command for retry.
        if st.codes_in_use.contains_key(&code) && st.allocation_ids.get(&code) == Some(&self.id) {
            st.pending.insert(
                code,
                Pending {
                    data: bytes,
                    attempts: 1,
                    next_retry: Instant::now() + flow::jittered_backoff(1),
                    queued_retry: None,
                },
            );
        }
        if st.active_allocations.get(&code) == Some(&self.id) {
            st.active_allocations.remove(&code);
        }
        self.retained = true;
    }

    // Keep this generation reserved without registering the frame for retry.
    // Stateful programming writes cannot be replayed safely: once their bytes
    // reached the PCI, a missing confirmation leaves the result uncertain.
    fn retain_once(&mut self) {
        let mut st = self.client.state.lock().unwrap();
        if st.active_allocations.get(&self.code) == Some(&self.id) {
            st.active_allocations.remove(&self.code);
        }
        self.retained = true;
    }
}

impl Drop for ConfirmationAllocation<'_> {
    fn drop(&mut self) {
        if self.retained {
            return;
        }
        let never_started = self.progress.cancel_before_start();
        let mut state = self.client.state.lock().unwrap();
        if state.allocation_ids.get(&self.code) == Some(&self.id) {
            PciClient::cancel_retries(&state, self.code);
            state.pending.remove(&self.code);
            if state.active_allocations.get(&self.code) == Some(&self.id) {
                state.active_allocations.remove(&self.code);
            }
            if never_started {
                PciClient::retire_confirmation(&mut state, self.code);
            } else if let Some(timestamp) = state.codes_in_use.get_mut(&self.code) {
                // It may still produce a late confirmation. Do not let forced
                // allocation cleanup recycle this code before confirmation or
                // a full reservation timeout measured from cancellation.
                *timestamp = Instant::now();
                state.quarantined_codes.insert(self.code);
            }
        }
    }
}

// Own a completed send's confirmation until its transaction ends. Cancellation
// removes retries but cannot retract bytes, so an unacknowledged code remains
// reserved. Allocation identity survives an ACK/reuse race.
struct SentConfirmation<'a> {
    client: &'a PciClient,
    code: u8,
    allocation_id: u64,
}

impl Drop for SentConfirmation<'_> {
    fn drop(&mut self) {
        let mut state = self.client.state.lock().unwrap();
        if state.allocation_ids.get(&self.code) == Some(&self.allocation_id) {
            PciClient::cancel_retries(&state, self.code);
            state.pending.remove(&self.code);
            if state.active_allocations.get(&self.code) == Some(&self.allocation_id) {
                state.active_allocations.remove(&self.code);
            }
            if let Some(timestamp) = state.codes_in_use.get_mut(&self.code) {
                *timestamp = Instant::now();
                state.quarantined_codes.insert(self.code);
            }
        }
    }
}

/// Write half of a connected transport.
pub type BoxedWrite = Box<dyn AsyncWrite + Send + Unpin>;
/// Read half of a connected transport.
pub type BoxedRead = Box<dyn AsyncRead + Send + Unpin>;

/// Async client for a C-Bus PCI/CNI, with the
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
    /// Separate fanout for correlated CAL transactions; never consumes MQTT events.
    packets: broadcast::Sender<Option<Packet>>,
    programming_lane: tokio::sync::Mutex<()>,
    programming_fault: std::sync::atomic::AtomicBool,
    /// Attached PCI unit address, or 256 until the BASIC query succeeds.
    local_unit: std::sync::atomic::AtomicU16,
    mmi_lane: tokio::sync::Mutex<()>,
    mmi_fault: std::sync::atomic::AtomicBool,
    mmi_collecting: std::sync::atomic::AtomicBool,
    disconnected: std::sync::atomic::AtomicBool,
    shutdown: watch::Sender<bool>,
    background_tasks: Mutex<Vec<tokio::task::JoinHandle<()>>>,
    shutdown_lane: tokio::sync::Mutex<()>,
}

impl PciClient {
    /// Acquire MMI before programming everywhere a combined guard is needed.
    /// Nested operations use the guard's methods rather than reacquiring lanes.
    pub(crate) async fn commissioning_observation(
        &self,
    ) -> std::io::Result<CommissioningObservation<'_>> {
        let mmi = self.mmi_lane.lock().await;
        let programming = self.programming_lane.lock().await;
        if self.mmi_fault.load(std::sync::atomic::Ordering::Acquire)
            || self
                .programming_fault
                .load(std::sync::atomic::Ordering::Acquire)
        {
            return Err(std::io::Error::other(
                "commissioning observation needs reconnect after an incomplete transaction",
            ));
        }
        Ok(CommissioningObservation {
            client: self,
            _mmi: mmi,
            _programming: programming,
        })
    }

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
        let (shutdown, _) = watch::channel(false);
        let client = Arc::new(PciClient {
            flow: Flow::start(writer.clone(), FlowConfig::default()),
            writer,
            state: Mutex::new(PciState::default()),
            events,
            init_done: watch::Sender::new(false),
            send_lane: tokio::sync::Mutex::new(()),
            packets: broadcast::channel(512).0,
            programming_lane: tokio::sync::Mutex::new(()),
            programming_fault: std::sync::atomic::AtomicBool::new(false),
            local_unit: std::sync::atomic::AtomicU16::new(256),
            mmi_lane: tokio::sync::Mutex::new(()),
            mmi_fault: std::sync::atomic::AtomicBool::new(false),
            mmi_collecting: std::sync::atomic::AtomicBool::new(false),
            disconnected: std::sync::atomic::AtomicBool::new(false),
            shutdown,
            background_tasks: Mutex::new(Vec::with_capacity(2)),
            shutdown_lane: tokio::sync::Mutex::new(()),
        });
        let weak = Arc::downgrade(&client);
        let reader_task = tokio::spawn(Self::reader_loop(
            weak.clone(),
            reader,
            client.shutdown.subscribe(),
        ));
        let retry_task = tokio::spawn(Self::retry_task(weak, client.shutdown.subscribe()));
        client
            .background_tasks
            .lock()
            .unwrap()
            .extend([reader_task, retry_task]);
        client
    }

    /// Close the transport and wait for the reader, flow controller, and
    /// retry worker to stop. The operation is idempotent. Use this before
    /// replacing a client after any transaction whose write may have started.
    pub async fn shutdown(&self) {
        let _lane = self.shutdown_lane.lock().await;
        self.request_shutdown();
        self.flow.shutdown().await;
        let tasks = std::mem::take(&mut *self.background_tasks.lock().unwrap());
        for task in tasks {
            let _ = task.await;
        }
    }

    /// Synchronously signal every owned transport task to stop.
    fn request_shutdown(&self) {
        self.shutdown.send_replace(true);
        self.flow.request_shutdown();
        if !self
            .disconnected
            .swap(true, std::sync::atomic::Ordering::AcqRel)
        {
            let _ = self.packets.send(None);
            let _ = self.events.send(CBusEvent::ConnectionLost);
        }
    }

    // ------------------------------------------------------------ sending

    /// `PCIProtocol._send`: prepare (escape, confirmation char, CR),
    /// wait for the init gate (unless this IS an init frame), transmit
    /// (fixed-paced for init frames, flow-controlled for everything
    /// else), and register for retry when a confirmation was requested.
    /// Cancellation before writing frees the confirmation code. Once writing
    /// starts, cancellation stops retry registration but reserves the code
    /// until confirmation or a 30-second timeout. If any retry started, even
    /// an ACK keeps the code reserved until 30 seconds after the latest retry
    /// completion or ACK, with no retry still writing. It cannot retract bytes
    /// already being written; close/reconnect after an in-flight cancellation.
    pub async fn send(
        &self,
        cmd: &Packet,
        confirmation: bool,
        basic_mode: bool,
    ) -> std::io::Result<Option<u8>> {
        self.send_with_allocation(cmd, confirmation, basic_mode, true)
            .await
            .map(|(code, _)| code)
    }

    async fn send_with_allocation(
        &self,
        cmd: &Packet,
        confirmation: bool,
        basic_mode: bool,
        retry: bool,
    ) -> std::io::Result<(Option<u8>, Option<u64>)> {
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
        let progress = Arc::new(flow::WriteProgress::default());
        let mut allocation = if confirmation {
            let (code, id) = self.allocate_confirmation()?;
            Some(ConfirmationAllocation {
                client: self,
                code,
                id,
                retained: false,
                progress: progress.clone(),
            })
        } else {
            None
        };
        let conf = allocation.as_ref().map(|allocation| allocation.code);
        if let Some(code) = conf {
            bytes.push(code);
        }
        bytes.extend_from_slice(b"\r");

        if init_frame {
            self.send_init(&bytes, &progress).await?;
        } else {
            let (priority, kind) = classify(cmd, conf);
            let rx = self
                .flow
                .submit_tracked(bytes.clone(), priority, kind, progress);
            // Enqueued: this sender's place in line is fixed, so let the
            // next caller queue up while we wait for the wire.
            drop(lane);
            rx.await.map_err(|_| {
                std::io::Error::new(std::io::ErrorKind::BrokenPipe, "flow controller gone")
            })??;
        }

        if let Some(allocation) = allocation.as_mut() {
            if retry {
                allocation.retain(bytes);
            } else {
                allocation.retain_once();
            }
        }
        Ok((conf, allocation.as_ref().map(|allocation| allocation.id)))
    }

    /// `PCIProtocol._send_packet` for the init sequence only: fixed
    /// 0.1 s pre-write delay. Post-init traffic goes through the flow
    /// controller instead.
    async fn send_init(&self, data: &[u8], progress: &flow::WriteProgress) -> std::io::Result<()> {
        tokio::time::sleep(INIT_SEND_DELAY).await;
        let mut w = self.writer.lock().await;
        if !progress.start() {
            return Err(std::io::Error::other("send cancelled before write"));
        }
        w.write_all(data).await?;
        w.flush().await
    }

    async fn send_guarded(&self, packet: &Packet) -> std::io::Result<SentConfirmation<'_>> {
        let (code, allocation_id) = self.send_with_allocation(packet, true, false, true).await?;
        let code = code.ok_or_else(|| {
            std::io::Error::new(
                std::io::ErrorKind::InvalidInput,
                "command cannot be confirmed",
            )
        })?;
        Ok(SentConfirmation {
            client: self,
            code,
            allocation_id: allocation_id.expect("confirmed send has allocation generation"),
        })
    }

    // Generation-safe confirmed send with no retry registration. Dropping the
    // returned guard quarantines an unconfirmed code, so a late confirmation
    // cannot be attributed to a later command using the same code.
    async fn send_guarded_once(&self, packet: &Packet) -> std::io::Result<SentConfirmation<'_>> {
        let (code, allocation_id) = self
            .send_with_allocation(packet, true, false, false)
            .await?;
        let code = code.ok_or_else(|| {
            std::io::Error::new(
                std::io::ErrorKind::InvalidInput,
                "command cannot be confirmed",
            )
        })?;
        Ok(SentConfirmation {
            client: self,
            code,
            allocation_id: allocation_id.expect("confirmed send has allocation generation"),
        })
    }

    // Legacy one-shot programming has no send-generation receipt. Its old
    // epilogue must never erase a later generated send's active/quarantined code.
    fn release_legacy_confirmation(&self, code: u8) {
        let mut state = self.state.lock().unwrap();
        if !state.allocation_ids.contains_key(&code) {
            Self::retire_confirmation(&mut state, code);
        }
    }

    // --------------------------------------------- confirmation allocator

    /// `PCIProtocol._get_confirmation_code`
    fn get_confirmation_code(&self) -> std::io::Result<u8> {
        let mut state = self.state.lock().unwrap();
        let code = Self::confirmation_code_inner(&mut state)?;
        // Manual programming paths have their own transaction cleanup; only
        // send() needs an allocation generation for its cancellation guard.
        state.allocation_ids.remove(&code);
        Ok(code)
    }

    // Reserve one caller-selected confirmation code without recycling an
    // active or quarantined allocation. Strict selected-serial plans encode
    // `g` into their signed-off request bytes, so substituting the allocator's
    // next code would change the command the operator reviewed.
    fn allocate_exact_confirmation(&self, code: u8) -> std::io::Result<(u8, u64)> {
        if !CONFIRMATION_CODES.contains(&code) {
            return Err(std::io::Error::new(
                std::io::ErrorKind::InvalidInput,
                "confirmation code must be in g..=z",
            ));
        }
        let mut state = self.state.lock().unwrap();
        Self::check_and_release_timed_out(&mut state);
        if state.codes_in_use.contains_key(&code) {
            return Err(std::io::Error::new(
                std::io::ErrorKind::WouldBlock,
                "requested confirmation code is already reserved",
            ));
        }
        state.codes_in_use.insert(code, Instant::now());
        let id = state.next_allocation_id;
        state.next_allocation_id = state.next_allocation_id.wrapping_add(1);
        state.allocation_ids.insert(code, id);
        state.active_allocations.insert(code, id);
        Ok((code, id))
    }

    fn allocate_confirmation(&self) -> std::io::Result<(u8, u64)> {
        let mut st = self.state.lock().unwrap();
        let code = Self::confirmation_code_inner(&mut st)?;
        let id = st.next_allocation_id;
        st.next_allocation_id = st.next_allocation_id.wrapping_add(1);
        st.allocation_ids.insert(code, id);
        st.active_allocations.insert(code, id);
        Ok((code, id))
    }

    fn confirmation_code_inner(st: &mut PciState) -> std::io::Result<u8> {
        Self::check_and_release_timed_out(st);
        for _ in 0..CONFIRMATION_CODES.len() {
            let code = CONFIRMATION_CODES[st.next_confirmation_index];
            st.next_confirmation_index =
                (st.next_confirmation_index + 1) % CONFIRMATION_CODES.len();
            if let std::collections::hash_map::Entry::Vacant(entry) = st.codes_in_use.entry(code) {
                entry.insert(Instant::now());
                return Ok(code);
            }
        }
        // Only legacy/returned sends are eligible for forced release. Active
        // writers and cancelled in-flight writers cannot safely share a code.
        let mut candidates: Vec<_> = st
            .codes_in_use
            .iter()
            .filter(|(code, _)| {
                !st.active_allocations.contains_key(code) && !st.quarantined_codes.contains(code)
            })
            .map(|(&code, &at)| (code, at))
            .collect();
        candidates.sort_by_key(|&(_, at)| at);
        for (code, _) in candidates {
            if Self::retire_confirmation(st, code) {
                st.codes_in_use.insert(code, Instant::now());
                return Ok(code);
            }
        }
        Err(std::io::Error::new(
            std::io::ErrorKind::WouldBlock,
            "all confirmation codes are reserved by active or cancelled writes",
        ))
    }

    // Atomically prevent each queued retry from starting. False from any
    // token means that copy started (or finished) and may still acknowledge.
    fn cancel_retries(st: &PciState, code: u8) -> bool {
        st.retry_writes.get(&code).is_some_and(|history| {
            debug_assert_eq!(st.allocation_ids.get(&code), Some(&history.allocation_id));
            let mut may_ack = false;
            for progress in &history.writes {
                may_ack |= !progress.cancel_before_start();
            }
            may_ack
        })
    }

    fn release_confirmation(st: &mut PciState, code: u8) {
        st.pending.remove(&code);
        st.codes_in_use.remove(&code);
        st.active_allocations.remove(&code);
        st.quarantined_codes.remove(&code);
        st.allocation_ids.remove(&code);
        st.retry_writes.remove(&code);
    }

    // Used for ACK, pressure and give-up. A retransmitted generation is never
    // immediately reusable: no ACK says which copy it acknowledges.
    fn retire_confirmation(st: &mut PciState, code: u8) -> bool {
        let may_ack = Self::cancel_retries(st, code);
        st.pending.remove(&code);
        if may_ack {
            if let Some(timestamp) = st.codes_in_use.get_mut(&code) {
                *timestamp = Instant::now();
                st.quarantined_codes.insert(code);
            }
            false
        } else {
            Self::release_confirmation(st, code);
            true
        }
    }

    /// `PCIProtocol._check_and_release_timed_out_codes`
    fn check_and_release_timed_out(st: &mut PciState) {
        Self::check_and_release_timed_out_at(st, Instant::now());
    }

    fn check_and_release_timed_out_at(st: &mut PciState, now: Instant) {
        let timed_out: Vec<u8> = st
            .codes_in_use
            .iter()
            .filter(|(code, &t)| {
                !st.active_allocations.contains_key(code)
                    && now.saturating_duration_since(t) > CONFIRMATION_TIMEOUT
            })
            .map(|(&c, _)| c)
            .collect();
        for code in timed_out {
            Self::cancel_retries(st, code);
            let retry_still_possible = st.retry_writes.get(&code).is_some_and(|history| {
                history.writes.iter().any(|progress| {
                    !progress.cancel_before_start()
                        && progress.finished_at().is_none_or(|at| {
                            now.saturating_duration_since(at) <= CONFIRMATION_TIMEOUT
                        })
                })
            });
            if retry_still_possible {
                st.quarantined_codes.insert(code);
                continue;
            }
            tracing::warn!("confirmation code {:#04x} timed out", code);
            Self::release_confirmation(st, code);
        }
        // force cleanup of the oldest 25% when >90% of codes in use
        let threshold = (CONFIRMATION_CODES.len() as f64 * FORCE_CLEANUP_THRESHOLD) as usize;
        if st.codes_in_use.len() > threshold {
            let mut by_age: Vec<(u8, Instant)> = st
                .codes_in_use
                .iter()
                .filter(|(code, _)| {
                    !st.active_allocations.contains_key(code)
                        && !st.quarantined_codes.contains(code)
                })
                .map(|(&c, &t)| (c, t))
                .collect();
            by_age.sort_by_key(|&(_, t)| t);
            let release_count = ((by_age.len() as f64 * FORCE_CLEANUP_PERCENTAGE) as usize).max(1);
            for &(code, _) in by_age.iter().take(release_count) {
                tracing::warn!("force releasing confirmation code {:#04x}", code);
                Self::retire_confirmation(st, code);
            }
        }
    }

    // -------------------------------------------------------- retry task

    /// `PCIProtocol._check_pending_confirmations` on a backoff schedule:
    /// resend byte-identical frames at jittered 1 s -> 2 s -> 4 s
    /// intervals (attempts capped at 3, then abandon+release, same
    /// retry schedule as before). Started retries keep their confirmation code
    /// reserved after give-up, through the late-ACK timeout. Retransmits use the flow
    /// controller's unwindowed lane: no window slot, but the inter-frame
    /// floor and any `!` pause still apply.
    async fn retry_task(client: Weak<Self>, mut shutdown: watch::Receiver<bool>) {
        loop {
            tokio::select! {
                biased;
                changed = shutdown.changed() => {
                    let _ = changed;
                    return;
                }
                _ = tokio::time::sleep(RETRY_SWEEP_INTERVAL) => {}
            }
            let now = Instant::now();
            let mut to_retry = Vec::new();
            {
                let Some(client) = client.upgrade() else {
                    return;
                };
                let mut st = client.state.lock().unwrap();
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
                        let progress = Arc::new(flow::WriteProgress::default());
                        p.queued_retry = Some(progress.clone());
                        let data = p.data.clone();
                        let allocation_id = st.allocation_ids[&code];
                        let history = st.retry_writes.entry(code).or_insert_with(|| RetryWrites {
                            allocation_id,
                            writes: Vec::with_capacity((MAX_PACKET_RETRIES - 1) as usize),
                        });
                        debug_assert_eq!(history.allocation_id, allocation_id);
                        history.writes.push(progress.clone());
                        to_retry.push((data, progress));
                    } else {
                        tracing::warn!(
                            "giving up on confirmation code {:#04x} after {} attempts",
                            code,
                            MAX_PACKET_RETRIES
                        );
                        Self::retire_confirmation(&mut st, code);
                    }
                }
            }
            for (data, progress) in to_retry {
                let response = {
                    let Some(client) = client.upgrade() else {
                        return;
                    };
                    client.flow.submit_unwindowed_tracked(data, progress)
                };
                let result = tokio::select! {
                    biased;
                    changed = shutdown.changed() => {
                        let _ = changed;
                        return;
                    }
                    result = response => result,
                };
                match result {
                    Ok(Ok(())) => {}
                    // A cancelled queued retry drops its sender without a
                    // write. Other commands still need their retry service.
                    Err(_) => continue,
                    Ok(Err(_)) => return,
                }
            }
        }
    }

    // -------------------------------------------------------- reader loop

    async fn reader_loop(
        client: Weak<Self>,
        mut reader: BoxedRead,
        mut shutdown: watch::Receiver<bool>,
    ) {
        let mut fb = FrameBuffer::new_client();
        let mut buf = [0u8; 4096];
        loop {
            let read = tokio::select! {
                biased;
                changed = shutdown.changed() => {
                    let _ = changed;
                    break;
                }
                read = reader.read(&mut buf) => read,
            };
            match read {
                Ok(0) | Err(_) => break,
                Ok(n) => {
                    let Some(client) = client.upgrade() else {
                        break;
                    };
                    // The bound applies to an incomplete frame, not a TCP
                    // read containing many complete programming replies.
                    for chunk in buf[..n].chunks(64) {
                        fb.set_install_mmi(
                            client
                                .mmi_collecting
                                .load(std::sync::atomic::Ordering::Acquire),
                        );
                        for ev in fb.feed(chunk) {
                            if let Some(p) = ev.packet {
                                client.handle_cbus_packet(p);
                            }
                        }
                    }
                }
            }
        }
        tracing::warn!("connection to PCI lost");
        if let Some(client) = client.upgrade() {
            client.request_shutdown();
        }
    }

    /// `PCIProtocol.handle_cbus_packet` event dispatch.
    fn handle_cbus_packet(&self, p: Packet) {
        let _ = self.packets.send(Some(p.clone()));
        match p {
            Packet::Confirmation { code, success } => {
                tracing::debug!("confirmation: code {:#04x} success {}", code, success);
                {
                    let mut st = self.state.lock().unwrap();
                    Self::retire_confirmation(&mut st, code);
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
                        Sal::Aircon(command) => Some(CBusEvent::AirconCommand {
                            source: src,
                            command,
                        }),
                        Sal::AirconStatus(status) => Some(CBusEvent::AirconStatus {
                            source: src,
                            status,
                        }),
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
                        Sal::TriggerEvent {
                            group_address,
                            action_selector,
                        } => Some(CBusEvent::TriggerEvent {
                            source: src,
                            group: group_address,
                            selector: action_selector,
                        }),
                        Sal::TriggerMin { group_address } => Some(CBusEvent::TriggerEvent {
                            source: src,
                            group: group_address,
                            selector: 0,
                        }),
                        Sal::TriggerMax { group_address } => Some(CBusEvent::TriggerEvent {
                            source: src,
                            group: group_address,
                            selector: 255,
                        }),
                        Sal::TriggerIndicatorKill { group_address } => {
                            Some(CBusEvent::TriggerIndicatorKill {
                                source: src,
                                group: group_address,
                            })
                        }
                        Sal::EnableSetNetworkVariable { variable, value } => {
                            Some(CBusEvent::EnableSet {
                                source: src,
                                variable,
                                value,
                            })
                        }
                        Sal::TemperatureBroadcast {
                            group_address,
                            temperature,
                        } => Some(CBusEvent::TemperatureBroadcast {
                            source: src,
                            group: group_address,
                            temperature,
                        }),
                        Sal::ClockUpdateDate { year, month, day } => Some(CBusEvent::ClockDate {
                            source: src,
                            year,
                            month,
                            day,
                        }),
                        Sal::ClockUpdateTime {
                            hour,
                            minute,
                            second,
                        } => Some(CBusEvent::ClockTime {
                            source: src,
                            hour,
                            minute,
                            second,
                        }),
                        Sal::ClockRequest => Some(CBusEvent::ClockRequest { source: src }),
                        Sal::DynamicLabel {
                            application,
                            payload,
                        } => Some(CBusEvent::DynamicLabel {
                            source: src,
                            application,
                            payload,
                        }),
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
                        if child_application == 0xff {
                            continue;
                        }
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

/// Flow-control classification of an outbound frame: interactive lighting,
/// Trigger, Enable, and Air-Conditioning commands outrank background
/// frames, and the response that will release the frame's window slot
/// is derived from what the device observably sends back.
fn classify(cmd: &Packet, conf: Option<u8>) -> (Priority, ResponseKind) {
    let is_interactive = |s: &Sal| {
        matches!(
            s,
            Sal::Aircon(_)
                | Sal::LightingOn { .. }
                | Sal::LightingOff { .. }
                | Sal::LightingRamp { .. }
                | Sal::LightingTerminateRamp { .. }
                | Sal::TriggerEvent { .. }
                | Sal::TriggerIndicatorKill { .. }
                | Sal::TriggerMin { .. }
                | Sal::TriggerMax { .. }
                | Sal::EnableSetNetworkVariable { .. }
                | Sal::TemperatureBroadcast { .. }
        )
    };
    let priority = match cmd {
        Packet::PointToMultipoint { sals, .. } if sals.iter().any(is_interactive) => {
            Priority::Command
        }
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
    async fn dropping_last_client_closes_transport_tasks_and_socket() {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let peer = tokio::spawn(async move {
            let (mut stream, _) = listener.accept().await.unwrap();
            let mut bytes = Vec::new();
            stream.read_to_end(&mut bytes).await.unwrap();
            bytes
        });
        let stream = tokio::net::TcpStream::connect(address).await.unwrap();
        let (reader, writer) = stream.into_split();
        let (events, _events_rx) = mpsc::unbounded_channel();
        let pci = PciClient::new(Box::new(reader), Box::new(writer), events);

        drop(pci);

        let bytes = tokio::time::timeout(Duration::from_secs(1), peer)
            .await
            .expect("client drop must close the TCP session")
            .unwrap();
        assert!(bytes.is_empty());
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
        assert_eq!(pci.state.lock().unwrap().allocation_ids.len(), 1);
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
        assert!(pci.state.lock().unwrap().allocation_ids.is_empty());
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
            codes.push(pci.get_confirmation_code().unwrap());
        }
        assert!(codes.iter().all(|c| CONFIRMATION_CODES.contains(c)));
        // the first 19 allocations are distinct (force cleanup starts
        // when >90% of the 20-code pool is in use)
        let mut first19 = codes[..19].to_vec();
        first19.sort_unstable();
        first19.dedup();
        assert_eq!(first19.len(), 19);
        assert!(pci.state.lock().unwrap().allocation_ids.is_empty());
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
        // Give-up removes pending retry state but quarantines the confirmation
        // code because any completed retry can still acknowledge late.
        {
            let state = pci.state.lock().unwrap();
            assert!(state.pending.is_empty());
            assert!(state.codes_in_use.contains_key(&b'h'));
            assert!(state.quarantined_codes.contains(&b'h'));
            assert_eq!(state.retry_writes[&b'h'].writes.len(), 2);
            assert!(state.retry_writes[&b'h']
                .writes
                .iter()
                .all(|p| p.finished_at().is_some()));
        }
        // Give-up and either old ACK must not recycle a code after two
        // completed retries. Every copy remains in the generation history.
        pci.handle_cbus_packet(Packet::Confirmation {
            code: b'h',
            success: true,
        });
        for _ in 0..64 {
            assert_ne!(pci.get_confirmation_code().unwrap(), b'h');
        }
        tokio::time::advance(CONFIRMATION_TIMEOUT + Duration::from_secs(1)).await;
        let mut state = pci.state.lock().unwrap();
        PciClient::check_and_release_timed_out(&mut state);
        assert!(!state.codes_in_use.contains_key(&b'h'));
        assert!(!state.allocation_ids.contains_key(&b'h'));
        assert!(!state.retry_writes.contains_key(&b'h'));
    }

    #[tokio::test]
    async fn temperature_packets_surface_as_transport_events() {
        let (client_side, _pci_side) = tokio::io::duplex(4096);
        let (rd, wr) = tokio::io::split(client_side);
        let (tx, mut rx) = mpsc::unbounded_channel();
        let pci = PciClient::new(Box::new(rd), Box::new(wr), tx);
        pci.handle_cbus_packet(Packet::PointToMultipoint {
            meta: Meta {
                checksum: true,
                priority_class: 0,
                source_address: Some(9),
                confirmation: None,
            },
            application: 25,
            sals: vec![Sal::TemperatureBroadcast {
                group_address: 3,
                temperature: 21.25,
            }],
        });
        assert_eq!(
            rx.try_recv().unwrap(),
            CBusEvent::TemperatureBroadcast {
                source: Some(9),
                group: 3,
                temperature: 21.25,
            }
        );
    }

    #[tokio::test]
    async fn dynamic_label_packets_surface_exact_transport_events() {
        let (client_side, _pci_side) = tokio::io::duplex(4096);
        let (rd, wr) = tokio::io::split(client_side);
        let (tx, mut rx) = mpsc::unbounded_channel();
        let pci = PciClient::new(Box::new(rd), Box::new(wr), tx);
        let payload = b"\xa9\x01\x40\x00Lounge".to_vec();
        pci.handle_cbus_packet(Packet::PointToMultipoint {
            meta: Meta {
                checksum: true,
                priority_class: 0,
                source_address: Some(5),
                confirmation: None,
            },
            application: 56,
            sals: vec![Sal::DynamicLabel {
                application: 56,
                payload: payload.clone(),
            }],
        });
        assert_eq!(
            rx.try_recv().unwrap(),
            CBusEvent::DynamicLabel {
                source: Some(5),
                application: 56,
                payload,
            }
        );
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
        let trigger = Packet::PointToMultipoint {
            meta: Meta::new(true, 0),
            application: 0xca,
            sals: vec![Sal::TriggerEvent {
                group_address: 1,
                action_selector: 123,
            }],
        };
        assert_eq!(
            classify(&trigger, Some(b'i')),
            (Priority::Command, ResponseKind::Confirmation(b'i'))
        );
        let temperature = Packet::PointToMultipoint {
            meta: Meta::new(true, 0),
            application: 25,
            sals: vec![Sal::TemperatureBroadcast {
                group_address: 3,
                temperature: 21.25,
            }],
        };
        assert_eq!(
            classify(&temperature, Some(b'j')),
            (Priority::Command, ResponseKind::Confirmation(b'j'))
        );
        let aircon = Packet::PointToMultipoint {
            meta: Meta::new(true, 0),
            application: 0xac,
            sals: vec![Sal::Aircon(
                cbus_protocol::sal::aircon::AirconCommand::Refresh { ward: 1 },
            )],
        };
        assert_eq!(
            classify(&aircon, Some(b'k')),
            (Priority::Command, ResponseKind::Confirmation(b'k'))
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
    #[tokio::test(start_paused = true)]
    async fn cancelled_confirmed_send_releases_allocation_and_never_starts_queued_write() {
        let (client, mut remote) = tokio::io::duplex(4096);
        let (rd, wr) = tokio::io::split(client);
        let (tx, _) = mpsc::unbounded_channel();
        let pci = PciClient::new(Box::new(rd), Box::new(wr), tx);
        pci.pci_reset().await.unwrap();
        read_available(&mut remote, 1).await;
        let held = pci.writer.lock().await;
        let send_client = pci.clone();
        let sending = tokio::spawn(async move { send_client.lighting_group_on(&[1], 0x38).await });
        tokio::task::yield_now().await;
        assert_eq!(pci.state.lock().unwrap().codes_in_use.len(), 1);
        sending.abort();
        assert!(sending.await.unwrap_err().is_cancelled());
        {
            let state = pci.state.lock().unwrap();
            assert!(state.codes_in_use.is_empty());
            assert!(state.pending.is_empty());
            assert!(state.allocation_ids.is_empty());
        }
        drop(held);
        tokio::time::advance(Duration::from_secs(15)).await;
        assert!(read_available(&mut remote, 1).await.is_empty());
    }
    #[tokio::test(start_paused = true)]
    async fn send_allocation_generations_follow_confirmation_timeout_and_force_release() {
        let (client, _remote) = tokio::io::duplex(4096);
        let (rd, wr) = tokio::io::split(client);
        let (tx, _) = mpsc::unbounded_channel();
        let pci = PciClient::new(Box::new(rd), Box::new(wr), tx);
        for success in [true, false] {
            let (code, _) = pci.allocate_confirmation().unwrap();
            pci.handle_cbus_packet(Packet::Confirmation { code, success });
            assert!(pci.state.lock().unwrap().allocation_ids.is_empty());
        }
        for _ in 0..64 {
            let (code, _) = pci.allocate_confirmation().unwrap();
            pci.state.lock().unwrap().active_allocations.remove(&code);
            let state = pci.state.lock().unwrap();
            assert_eq!(state.allocation_ids.len(), state.codes_in_use.len());
            assert!(state
                .allocation_ids
                .keys()
                .all(|code| state.codes_in_use.contains_key(code)));
        }
        let mut state = pci.state.lock().unwrap();
        for timestamp in state.codes_in_use.values_mut() {
            *timestamp = Instant::now() - CONFIRMATION_TIMEOUT - Duration::from_secs(1);
        }
        PciClient::check_and_release_timed_out(&mut state);
        assert!(state.codes_in_use.is_empty());
        assert!(state.allocation_ids.is_empty());
    }

    #[derive(Default)]
    struct WriteGate {
        blocked: std::sync::atomic::AtomicBool,
        started: tokio::sync::Notify,
        waker: Mutex<Option<std::task::Waker>>,
    }

    struct BlockingWriter {
        inner: BoxedWrite,
        gate: Arc<WriteGate>,
    }

    impl AsyncWrite for BlockingWriter {
        fn poll_write(
            mut self: std::pin::Pin<&mut Self>,
            cx: &mut std::task::Context<'_>,
            bytes: &[u8],
        ) -> std::task::Poll<std::io::Result<usize>> {
            if self.gate.blocked.load(std::sync::atomic::Ordering::Acquire) {
                *self.gate.waker.lock().unwrap() = Some(cx.waker().clone());
                self.gate.started.notify_one();
                return std::task::Poll::Pending;
            }
            std::pin::Pin::new(&mut self.inner).poll_write(cx, bytes)
        }

        fn poll_flush(
            mut self: std::pin::Pin<&mut Self>,
            cx: &mut std::task::Context<'_>,
        ) -> std::task::Poll<std::io::Result<()>> {
            std::pin::Pin::new(&mut self.inner).poll_flush(cx)
        }

        fn poll_shutdown(
            mut self: std::pin::Pin<&mut Self>,
            cx: &mut std::task::Context<'_>,
        ) -> std::task::Poll<std::io::Result<()>> {
            std::pin::Pin::new(&mut self.inner).poll_shutdown(cx)
        }
    }

    #[tokio::test(start_paused = true)]
    async fn cancelled_started_write_reserves_code_through_pressure_and_late_ack() {
        let (client, mut remote) = tokio::io::duplex(4096);
        let (rd, wr) = tokio::io::split(client);
        let gate = Arc::new(WriteGate::default());
        let writer = BlockingWriter {
            inner: Box::new(wr),
            gate: gate.clone(),
        };
        let (tx, _) = mpsc::unbounded_channel();
        let pci = PciClient::new(Box::new(rd), Box::new(writer), tx);
        pci.pci_reset().await.unwrap();
        read_available(&mut remote, 1).await;
        gate.blocked
            .store(true, std::sync::atomic::Ordering::Release);
        let sender = pci.clone();
        let sending = tokio::spawn(async move { sender.lighting_group_on(&[1], 0x38).await });
        gate.started.notified().await;
        let old_code = *pci
            .state
            .lock()
            .unwrap()
            .codes_in_use
            .keys()
            .next()
            .unwrap();
        sending.abort();
        assert!(sending.await.unwrap_err().is_cancelled());
        {
            let state = pci.state.lock().unwrap();
            assert!(state.quarantined_codes.contains(&old_code));
            assert!(state.codes_in_use.contains_key(&old_code));
            assert!(state.active_allocations.is_empty());
            assert!(state.pending.is_empty());
        }
        // Forced-release pressure must not make the cancelled writer's code
        // available to another command while its write is still in progress.
        for _ in 0..64 {
            assert_ne!(pci.get_confirmation_code().unwrap(), old_code);
        }
        let sender = pci.clone();
        let replacement = tokio::spawn(async move { sender.lighting_group_on(&[2], 0x38).await });
        tokio::task::yield_now().await;
        let new_code = *pci
            .state
            .lock()
            .unwrap()
            .active_allocations
            .keys()
            .next()
            .unwrap();
        assert_ne!(old_code, new_code);
        gate.blocked
            .store(false, std::sync::atomic::Ordering::Release);
        gate.waker.lock().unwrap().take().unwrap().wake();
        let first = read_available(&mut remote, 1).await;
        assert_eq!(first[first.len() - 2], old_code);
        // Old ACK cannot acknowledge the newer queued command. It only
        // releases the old reservation and Flow slot.
        remote.write_all(&[old_code, b'.']).await.unwrap();
        let newer = read_available(&mut remote, 100).await;
        assert_eq!(newer[newer.len() - 2], new_code);
        assert_eq!(replacement.await.unwrap().unwrap(), Some(new_code));
        {
            let state = pci.state.lock().unwrap();
            assert!(state.pending.contains_key(&new_code));
            assert!(state.codes_in_use.contains_key(&new_code));
            assert!(!state.codes_in_use.contains_key(&old_code));
            assert!(!state.quarantined_codes.contains(&old_code));
        }
        remote.write_all(&[new_code, b'.']).await.unwrap();
        tokio::task::yield_now().await;
        assert!(pci.state.lock().unwrap().allocation_ids.is_empty());
    }

    #[tokio::test(start_paused = true)]
    async fn fast_ack_reuse_keeps_new_generation_active_on_old_completion_and_drop() {
        let (client, _remote) = tokio::io::duplex(4096);
        let (rd, wr) = tokio::io::split(client);
        let (tx, _) = mpsc::unbounded_channel();
        let pci = PciClient::new(Box::new(rd), Box::new(wr), tx);
        for completes in [false, true] {
            let (code, id) = pci.allocate_confirmation().unwrap();
            let progress = Arc::new(flow::WriteProgress::default());
            assert!(progress.start());
            let mut old = ConfirmationAllocation {
                client: &pci,
                code,
                id,
                retained: false,
                progress,
            };
            pci.handle_cbus_packet(Packet::Confirmation {
                code,
                success: true,
            });
            pci.state.lock().unwrap().next_confirmation_index = CONFIRMATION_CODES
                .iter()
                .position(|&value| value == code)
                .unwrap();
            let (replacement, new_id) = pci.allocate_confirmation().unwrap();
            assert_eq!(replacement, code);
            if completes {
                old.retain(b"old command".to_vec());
            }
            drop(old);
            {
                let state = pci.state.lock().unwrap();
                assert_eq!(state.active_allocations.get(&code), Some(&new_id));
                assert_eq!(state.allocation_ids.get(&code), Some(&new_id));
                assert!(!state.pending.contains_key(&code));
                assert!(!state.quarantined_codes.contains(&code));
            }
            pci.handle_cbus_packet(Packet::Confirmation {
                code,
                success: true,
            });
        }
    }

    #[tokio::test(start_paused = true)]
    async fn reserved_codes_exhaust_without_reuse_then_quarantine_expires() {
        let (client, _remote) = tokio::io::duplex(4096);
        let (rd, wr) = tokio::io::split(client);
        let (tx, _) = mpsc::unbounded_channel();
        let pci = PciClient::new(Box::new(rd), Box::new(wr), tx);
        for _ in CONFIRMATION_CODES {
            let (code, id) = pci.allocate_confirmation().unwrap();
            let progress = Arc::new(flow::WriteProgress::default());
            assert!(progress.start());
            drop(ConfirmationAllocation {
                client: &pci,
                code,
                id,
                retained: false,
                progress,
            });
        }
        assert_eq!(
            pci.get_confirmation_code().unwrap_err().kind(),
            std::io::ErrorKind::WouldBlock
        );
        assert_eq!(
            pci.state.lock().unwrap().quarantined_codes.len(),
            CONFIRMATION_CODES.len()
        );
        tokio::time::advance(CONFIRMATION_TIMEOUT + Duration::from_secs(1)).await;
        let mut state = pci.state.lock().unwrap();
        PciClient::check_and_release_timed_out(&mut state);
        assert!(state.codes_in_use.is_empty());
        assert!(state.allocation_ids.is_empty());
        assert!(state.quarantined_codes.is_empty());
        assert!(state.active_allocations.is_empty());
    }

    #[tokio::test(start_paused = true)]
    async fn started_retry_keeps_generation_reserved_after_original_and_late_ack() {
        let (client, mut remote) = tokio::io::duplex(4096);
        let (rd, wr) = tokio::io::split(client);
        let gate = Arc::new(WriteGate::default());
        let writer = BlockingWriter {
            inner: Box::new(wr),
            gate: gate.clone(),
        };
        let (tx, _) = mpsc::unbounded_channel();
        let pci = PciClient::new(Box::new(rd), Box::new(writer), tx);
        pci.pci_reset().await.unwrap();
        read_available(&mut remote, 1).await;
        let old_code = pci.lighting_group_on(&[1], 0x38).await.unwrap().unwrap();
        let original = read_available(&mut remote, 1).await;
        assert_eq!(original[original.len() - 2], old_code);
        gate.blocked
            .store(true, std::sync::atomic::Ordering::Release);
        pci.state
            .lock()
            .unwrap()
            .pending
            .get_mut(&old_code)
            .unwrap()
            .next_retry = Instant::now();
        gate.started.notified().await;
        remote.write_all(&[old_code, b'.']).await.unwrap();
        tokio::task::yield_now().await;
        {
            let state = pci.state.lock().unwrap();
            assert!(!state.pending.contains_key(&old_code));
            assert!(state.quarantined_codes.contains(&old_code));
            assert_eq!(state.retry_writes[&old_code].writes.len(), 1);
            assert!(state.retry_writes[&old_code].writes[0]
                .finished_at()
                .is_none());
        }
        for _ in 0..64 {
            assert_ne!(pci.get_confirmation_code().unwrap(), old_code);
        }
        // The timeout cannot expire while the started retry is still inside
        // write_all, even 31 seconds after the original ACK.
        tokio::time::advance(CONFIRMATION_TIMEOUT + Duration::from_secs(1)).await;
        assert_ne!(pci.get_confirmation_code().unwrap(), old_code);
        assert!(pci
            .state
            .lock()
            .unwrap()
            .codes_in_use
            .contains_key(&old_code));
        gate.blocked
            .store(false, std::sync::atomic::Ordering::Release);
        gate.waker.lock().unwrap().take().unwrap().wake();
        let retry = read_available(&mut remote, 1).await;
        assert_eq!(retry, original);
        let new_code = pci.lighting_group_on(&[2], 0x38).await.unwrap().unwrap();
        assert_ne!(old_code, new_code);
        read_available(&mut remote, 1).await;
        remote.write_all(&[old_code, b'.']).await.unwrap();
        tokio::task::yield_now().await;
        {
            let state = pci.state.lock().unwrap();
            assert!(state.pending.contains_key(&new_code));
            assert!(state.codes_in_use.contains_key(&new_code));
            assert!(state.quarantined_codes.contains(&old_code));
            assert!(state.retry_writes[&old_code].writes[0]
                .finished_at()
                .is_some());
        }
        remote.write_all(&[new_code, b'.']).await.unwrap();
        tokio::task::yield_now().await;
        for _ in 0..64 {
            assert_ne!(pci.get_confirmation_code().unwrap(), old_code);
        }
        tokio::time::advance(CONFIRMATION_TIMEOUT - Duration::from_secs(1)).await;
        {
            let mut state = pci.state.lock().unwrap();
            PciClient::check_and_release_timed_out(&mut state);
            assert!(state.codes_in_use.contains_key(&old_code));
        }
        tokio::time::advance(Duration::from_secs(2)).await;
        let mut state = pci.state.lock().unwrap();
        PciClient::check_and_release_timed_out(&mut state);
        assert!(!state.codes_in_use.contains_key(&old_code));
        assert!(!state.retry_writes.contains_key(&old_code));
        assert!(!state.allocation_ids.contains_key(&old_code));
    }

    #[tokio::test(start_paused = true)]
    async fn expiry_snapshot_before_retry_completion_keeps_reservation() {
        let (client, mut remote) = tokio::io::duplex(4096);
        let (rd, wr) = tokio::io::split(client);
        let (tx, _) = mpsc::unbounded_channel();
        let pci = PciClient::new(Box::new(rd), Box::new(wr), tx);
        pci.pci_reset().await.unwrap();
        read_available(&mut remote, 1).await;
        let code = pci.lighting_group_on(&[1], 0x38).await.unwrap().unwrap();
        read_available(&mut remote, 1).await;
        let snapshot = Instant::now();
        pci.state
            .lock()
            .unwrap()
            .pending
            .get_mut(&code)
            .unwrap()
            .next_retry = snapshot;
        tokio::time::sleep(Duration::from_millis(500)).await;
        let retry = read_available(&mut remote, 1).await;
        assert!(!retry.is_empty());
        let mut state = pci.state.lock().unwrap();
        let finished = state.retry_writes[&code].writes[0].finished_at().unwrap();
        assert!(finished > snapshot);
        // Model Flow publishing a completion after expiry captured `now`.
        // The reservation itself is old enough to reach the retry-age check.
        state.codes_in_use.insert(
            code,
            snapshot - CONFIRMATION_TIMEOUT - Duration::from_secs(1),
        );
        PciClient::check_and_release_timed_out_at(&mut state, snapshot);
        assert!(state.codes_in_use.contains_key(&code));
        assert!(state.quarantined_codes.contains(&code));
        assert!(state.retry_writes.contains_key(&code));
    }
}
