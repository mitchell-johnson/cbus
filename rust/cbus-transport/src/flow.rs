//! Adaptive, closed-loop flow control for post-init PCI traffic.
//!
//! Replaces the open-loop pacing (fixed 0.1 s pre-write delay + 0.2 s
//! command throttle) with an ack-clocked sliding window sized from the
//! device's own responses, based on live wire captures of the real CNI:
//! ~195 ms confirmation latency when healthy, ~340 ms to the first status
//! report, one report frame per ~52-75 ms (the 9600-baud serial ceiling),
//! and explicit `!` ("PCI cannot accept data") frames under overload.
//!
//! Policy:
//! - at most W frames outstanding (W starts at 2, 1..=4), each slot
//!   released by that frame's own response: a confirmation for confirmed
//!   frames, the first matching status report for codeless status
//!   requests, or a short hold for frames with no observable response;
//! - a ~30 ms inter-frame floor so the serial line rate is never
//!   exceeded, and a per-slot response timeout of
//!   clamp(2.5 x EWMA ack latency, 500 ms..2 s) so a lost reply can
//!   never stall the pipeline;
//! - AIMD window control: `!` pauses all sends 250 ms and collapses W to
//!   1, two consecutive response timeouts collapse W to 1, and 10
//!   consecutive clean acks grow W by 1 up to 4;
//! - user commands queue ahead of status-sweep traffic, FIFO within each
//!   class;
//! - retransmits of unconfirmed frames back off 1 s -> 2 s -> 4 s with
//!   +-20% jitter (scheduled by the caller via [`jittered_backoff`];
//!   they bypass the window but respect the floor and pause).
//!
//! The controller changes WHEN frames are sent, never WHAT: wire formats,
//! confirmation usage and the init sequence are untouched.

use std::collections::VecDeque;
use std::time::Duration;
use tokio::io::{AsyncWrite, AsyncWriteExt};
use tokio::sync::{mpsc, oneshot};
use tokio::time::Instant;

/// Tuning knobs for the flow controller. The defaults encode the live
/// CNI measurements and are what the daemon runs with.
#[derive(Debug, Clone)]
pub struct FlowConfig {
    /// Initial window (outstanding-frame cap) after connect.
    pub window_initial: usize,
    /// Window floor (never below; 1 keeps the pipeline ack-clocked).
    pub window_min: usize,
    /// Window ceiling.
    pub window_max: usize,
    /// Minimum gap between any two wire writes (serial line-rate floor).
    pub min_gap: Duration,
    /// Response timeout = clamp(`rto_factor` x EWMA latency, min..max).
    pub rto_factor: f64,
    /// Lower clamp of the response timeout.
    pub rto_min: Duration,
    /// Upper clamp of the response timeout.
    pub rto_max: Duration,
    /// Pause applied to ALL sends when the PCI reports `!`.
    pub error_pause: Duration,
    /// Consecutive response timeouts that collapse the window to min.
    pub collapse_timeouts: u32,
    /// Consecutive clean acks that grow the window by one.
    pub grow_acks: u32,
    /// Slot hold for frames with no observable response.
    pub silent_hold: Duration,
    /// EWMA seed before the first ack (healthy CNI confirmation latency).
    pub seed_latency: Duration,
    /// EWMA smoothing factor for the ack latency estimate.
    pub ewma_alpha: f64,
    /// EWMA smoothing factor for the mean-deviation estimate.
    pub var_beta: f64,
}

impl Default for FlowConfig {
    fn default() -> Self {
        FlowConfig {
            window_initial: 2,
            window_min: 1,
            window_max: 4,
            min_gap: Duration::from_millis(30),
            rto_factor: 2.5,
            rto_min: Duration::from_millis(500),
            rto_max: Duration::from_secs(2),
            error_pause: Duration::from_millis(250),
            collapse_timeouts: 2,
            grow_acks: 10,
            silent_hold: Duration::from_millis(100),
            seed_latency: Duration::from_millis(200),
            ewma_alpha: 0.125,
            var_beta: 0.25,
        }
    }
}

/// Send-priority class: user commands outrank background traffic
/// (status sweeps/resyncs); FIFO within each class.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Priority {
    /// A user-initiated command (MQTT /set -> lighting operation).
    Command,
    /// Everything else: status requests, clock replies, timesync.
    Background,
}

/// What releases a frame's window slot.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ResponseKind {
    /// A confirmed frame: released by its confirmation code.
    Confirmation(u8),
    /// A codeless status request: released by the first status report
    /// matching the request's app + block + kind.
    Report {
        /// Child application the request targets.
        app: u8,
        /// Block start group address.
        block: u8,
        /// `true` for a level request, `false` for binary.
        level: bool,
    },
    /// No observable response: the slot is held briefly then released.
    Silent,
}

/// An observed device response fed back into the controller.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AckSignal {
    /// A confirmation frame (any success value: it IS a response).
    Confirmation(u8),
    /// An extended status report frame.
    Report {
        /// Child application of the report.
        app: u8,
        /// Block start group address of the report.
        block: u8,
        /// `true` for a level report, `false` for binary.
        level: bool,
    },
}

impl ResponseKind {
    fn matches(&self, sig: &AckSignal) -> bool {
        match (self, sig) {
            (ResponseKind::Confirmation(c), AckSignal::Confirmation(s)) => c == s,
            (
                ResponseKind::Report { app, block, level },
                AckSignal::Report {
                    app: a,
                    block: b,
                    level: l,
                },
            ) => app == a && block == b && level == l,
            _ => false,
        }
    }
}

// ------------------------------------------------------------ core state

struct InFlight {
    kind: ResponseKind,
    sent_at: Instant,
    deadline: Instant,
}

/// Reason a send is not allowed right now.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Gate {
    /// May transmit immediately.
    Ready,
    /// Time-gated (inter-frame floor or `!` pause): retry at the instant.
    Until(Instant),
    /// Window full: wait for an ack or a slot timeout.
    Window,
}

/// The synchronous controller core: window accounting, latency EWMA,
/// AIMD transitions. All decisions take an explicit `now` so the math is
/// unit-testable with a simulated clock.
struct FlowState {
    cfg: FlowConfig,
    window: usize,
    in_flight: Vec<InFlight>,
    /// EWMA of the ack latency, seconds.
    ewma: f64,
    /// EWMA of the absolute deviation from `ewma`, seconds.
    var: f64,
    consecutive_timeouts: u32,
    clean_acks: u32,
    paused_until: Option<Instant>,
    last_send: Option<Instant>,
    /// Set on collapse so the first regrowth logs an INFO recovery line.
    collapsed: bool,
}

impl FlowState {
    fn new(cfg: FlowConfig) -> FlowState {
        FlowState {
            window: cfg.window_initial,
            ewma: cfg.seed_latency.as_secs_f64(),
            var: 0.0,
            cfg,
            in_flight: Vec::new(),
            consecutive_timeouts: 0,
            clean_acks: 0,
            paused_until: None,
            last_send: None,
            collapsed: false,
        }
    }

    /// Current per-slot response timeout.
    fn rto(&self) -> Duration {
        Duration::from_secs_f64((self.ewma * self.cfg.rto_factor).clamp(
            self.cfg.rto_min.as_secs_f64(),
            self.cfg.rto_max.as_secs_f64(),
        ))
    }

    /// May a frame be written now? `windowed` is false for retransmits,
    /// which bypass the window but still respect floor and pause.
    fn gate(&self, windowed: bool, now: Instant) -> Gate {
        if windowed && self.in_flight.len() >= self.window {
            return Gate::Window;
        }
        let mut ready = now;
        if let Some(p) = self.paused_until {
            ready = ready.max(p);
        }
        if let Some(last) = self.last_send {
            ready = ready.max(last + self.cfg.min_gap);
        }
        if ready > now {
            Gate::Until(ready)
        } else {
            Gate::Ready
        }
    }

    /// A windowed frame hit the wire: occupy a slot until its response
    /// (or timeout) and restart the inter-frame floor.
    fn record_send(&mut self, kind: ResponseKind, now: Instant) {
        let hold = match kind {
            ResponseKind::Silent => self.cfg.silent_hold,
            _ => self.rto(),
        };
        self.in_flight.push(InFlight {
            kind,
            sent_at: now,
            deadline: now + hold,
        });
        self.last_send = Some(now);
    }

    /// An unwindowed (retransmit) frame hit the wire: floor only.
    fn record_raw_send(&mut self, now: Instant) {
        self.last_send = Some(now);
    }

    /// Release timed-out slots. Non-[`ResponseKind::Silent`] expiries
    /// count as response timeouts and can collapse the window.
    fn expire(&mut self, now: Instant) {
        let mut timeouts = 0u32;
        self.in_flight.retain(|f| {
            if f.deadline > now {
                return true;
            }
            if !matches!(f.kind, ResponseKind::Silent) {
                tracing::debug!(
                    "flow: response timeout for {:?} after {:?}",
                    f.kind,
                    now - f.sent_at
                );
                timeouts += 1;
            }
            false
        });
        for _ in 0..timeouts {
            self.consecutive_timeouts += 1;
            self.clean_acks = 0;
            if self.consecutive_timeouts >= self.cfg.collapse_timeouts {
                self.collapse("consecutive response timeouts");
            }
        }
    }

    /// Feed a device response; returns whether it released a slot. The
    /// oldest matching in-flight entry is the one released.
    fn on_ack(&mut self, sig: &AckSignal, now: Instant) -> bool {
        let Some(idx) = self.in_flight.iter().position(|f| f.kind.matches(sig)) else {
            return false;
        };
        let f = self.in_flight.remove(idx);
        let sample = (now - f.sent_at).as_secs_f64();
        self.var =
            (1.0 - self.cfg.var_beta) * self.var + self.cfg.var_beta * (sample - self.ewma).abs();
        self.ewma = (1.0 - self.cfg.ewma_alpha) * self.ewma + self.cfg.ewma_alpha * sample;
        self.consecutive_timeouts = 0;
        self.clean_acks += 1;
        if self.clean_acks >= self.cfg.grow_acks && self.window < self.cfg.window_max {
            self.clean_acks = 0;
            let old = self.window;
            self.window += 1;
            if self.collapsed {
                self.collapsed = false;
                tracing::info!(
                    "flow: window recovering {old} -> {} after {} clean acks; ewma={:.0}ms var={:.0}ms",
                    self.window,
                    self.cfg.grow_acks,
                    self.ewma * 1000.0,
                    self.var * 1000.0
                );
            } else {
                tracing::debug!("flow: window {old} -> {} (clean acks)", self.window);
            }
        }
        true
    }

    /// The PCI reported `!`: pause all sends and collapse the window.
    fn on_pci_error(&mut self, now: Instant) {
        let until = now + self.cfg.error_pause;
        self.paused_until = Some(self.paused_until.map_or(until, |p| p.max(until)));
        self.collapse("PCI cannot accept data (!)");
    }

    fn collapse(&mut self, reason: &str) {
        self.clean_acks = 0;
        if self.window > self.cfg.window_min {
            let old = self.window;
            self.window = self.cfg.window_min;
            self.collapsed = true;
            tracing::info!(
                "flow: window collapsed {old} -> {} ({reason}); ewma={:.0}ms var={:.0}ms in_flight={}",
                self.window,
                self.ewma * 1000.0,
                self.var * 1000.0,
                self.in_flight.len()
            );
        } else {
            tracing::debug!("flow: window already at minimum ({reason})");
        }
    }

    /// Earliest instant a held slot expires, if any.
    fn next_deadline(&self) -> Option<Instant> {
        self.in_flight.iter().map(|f| f.deadline).min()
    }
}

// ------------------------------------------------------- retransmit math

/// Jitter fraction applied to retransmit backoff (+-20%).
pub const RETRY_JITTER: f64 = 0.2;

/// Nominal backoff after the `attempt`-th transmission of an unconfirmed
/// frame (1-based): 1 s, 2 s, then 4 s.
pub fn retry_backoff(attempt: u32) -> Duration {
    Duration::from_secs(1 << attempt.saturating_sub(1).min(2))
}

/// Apply +-[`RETRY_JITTER`] to `nominal`; `unit` must be in `[0, 1)`.
pub fn jittered(nominal: Duration, unit: f64) -> Duration {
    nominal.mul_f64(1.0 - RETRY_JITTER + 2.0 * RETRY_JITTER * unit)
}

/// [`retry_backoff`] with random jitter applied.
pub fn jittered_backoff(attempt: u32) -> Duration {
    jittered(retry_backoff(attempt), cheap_unit_rand())
}

/// A cheap splitmix64-based uniform sample in `[0, 1)`; jitter does not
/// warrant a rand dependency.
fn cheap_unit_rand() -> f64 {
    use std::sync::atomic::{AtomicU64, Ordering};
    static STATE: AtomicU64 = AtomicU64::new(0);
    let t = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.subsec_nanos() as u64)
        .unwrap_or(0);
    let mut z = STATE
        .fetch_add(0x9E37_79B9_7F4A_7C15, Ordering::Relaxed)
        .wrapping_add(t.wrapping_mul(0x2545_F491_4F6C_DD1D));
    z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
    z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
    z ^= z >> 31;
    (z >> 11) as f64 / (1u64 << 53) as f64
}

// ------------------------------------------------------------ async side

struct Job {
    data: Vec<u8>,
    priority: Priority,
    kind: ResponseKind,
    windowed: bool,
    done: oneshot::Sender<std::io::Result<()>>,
}

enum FlowEvent {
    Ack(AckSignal),
    PciError,
}

/// Handle to a running flow-controller task. Submitting returns a
/// receiver that resolves once the frame is on the wire (or errored);
/// device responses are fed back via [`Flow::ack`] / [`Flow::pci_error`].
pub struct Flow {
    jobs: mpsc::UnboundedSender<Job>,
    events: mpsc::UnboundedSender<FlowEvent>,
}

impl Flow {
    /// Spawn the controller task over the (shared) transport write half.
    pub fn start<W>(writer: std::sync::Arc<tokio::sync::Mutex<W>>, cfg: FlowConfig) -> Flow
    where
        W: AsyncWrite + Send + Unpin + 'static,
    {
        let (jobs_tx, jobs_rx) = mpsc::unbounded_channel();
        let (events_tx, events_rx) = mpsc::unbounded_channel();
        tokio::spawn(run(FlowState::new(cfg), writer, jobs_rx, events_rx));
        Flow {
            jobs: jobs_tx,
            events: events_tx,
        }
    }

    /// Queue a frame for windowed transmission. The receiver resolves
    /// when the frame has been written (dropped-with-error when the
    /// controller is gone: the transport is dead).
    pub fn submit(
        &self,
        data: Vec<u8>,
        priority: Priority,
        kind: ResponseKind,
    ) -> oneshot::Receiver<std::io::Result<()>> {
        let (done, rx) = oneshot::channel();
        let _ = self.jobs.send(Job {
            data,
            priority,
            kind,
            windowed: true,
            done,
        });
        rx
    }

    /// Queue a retransmit: bypasses the window (its slot was already
    /// released by timeout) but respects the floor and any `!` pause.
    pub fn submit_unwindowed(&self, data: Vec<u8>) -> oneshot::Receiver<std::io::Result<()>> {
        let (done, rx) = oneshot::channel();
        let _ = self.jobs.send(Job {
            data,
            priority: Priority::Command,
            kind: ResponseKind::Silent,
            windowed: false,
            done,
        });
        rx
    }

    /// Feed an observed device response (confirmation or status report).
    pub fn ack(&self, sig: AckSignal) {
        let _ = self.events.send(FlowEvent::Ack(sig));
    }

    /// The PCI reported `!` ("cannot accept data").
    pub fn pci_error(&self) {
        let _ = self.events.send(FlowEvent::PciError);
    }
}

/// Wake-up horizon when fully idle (any event re-arms the loop sooner).
const IDLE_WAKE: Duration = Duration::from_secs(3600);

fn enqueue(
    job: Job,
    unwindowed: &mut VecDeque<Job>,
    commands: &mut VecDeque<Job>,
    background: &mut VecDeque<Job>,
) {
    if !job.windowed {
        unwindowed.push_back(job);
    } else if job.priority == Priority::Command {
        commands.push_back(job);
    } else {
        background.push_back(job);
    }
}

async fn run<W>(
    mut st: FlowState,
    writer: std::sync::Arc<tokio::sync::Mutex<W>>,
    mut jobs_rx: mpsc::UnboundedReceiver<Job>,
    mut events_rx: mpsc::UnboundedReceiver<FlowEvent>,
) where
    W: AsyncWrite + Send + Unpin + 'static,
{
    let mut unwindowed: VecDeque<Job> = VecDeque::new();
    let mut commands: VecDeque<Job> = VecDeque::new();
    let mut background: VecDeque<Job> = VecDeque::new();
    loop {
        // Drain pending feedback and submissions before deciding what to
        // transmit, so acks release slots first and a command arriving
        // together with background frames still outranks them.
        while let Ok(evt) = events_rx.try_recv() {
            match evt {
                FlowEvent::Ack(sig) => {
                    st.on_ack(&sig, Instant::now());
                }
                FlowEvent::PciError => st.on_pci_error(Instant::now()),
            }
        }
        while let Ok(job) = jobs_rx.try_recv() {
            enqueue(job, &mut unwindowed, &mut commands, &mut background);
        }

        let now = Instant::now();
        st.expire(now);

        // Retransmits first (oldest traffic), then commands, then
        // background; FIFO within each queue.
        let lane = if !unwindowed.is_empty() {
            Some(&mut unwindowed)
        } else if !commands.is_empty() {
            Some(&mut commands)
        } else if !background.is_empty() {
            Some(&mut background)
        } else {
            None
        };

        let mut wake = st.next_deadline();
        if let Some(queue) = lane {
            let windowed = queue.front().is_some_and(|j| j.windowed);
            match st.gate(windowed, now) {
                Gate::Ready => {
                    let job = queue.pop_front().expect("non-empty lane");
                    let res = {
                        let mut w = writer.lock().await;
                        match w.write_all(&job.data).await {
                            Ok(()) => w.flush().await,
                            Err(e) => Err(e),
                        }
                    };
                    match res {
                        Ok(()) => {
                            let sent = Instant::now();
                            if job.windowed {
                                st.record_send(job.kind, sent);
                            } else {
                                st.record_raw_send(sent);
                            }
                            let _ = job.done.send(Ok(()));
                        }
                        Err(e) => {
                            let _ = job.done.send(Err(e));
                        }
                    }
                    continue;
                }
                Gate::Until(t) => wake = Some(wake.map_or(t, |w| w.min(t))),
                // Window full: an ack event or a slot deadline (already
                // in `wake`) unblocks us.
                Gate::Window => {}
            }
        }

        let sleep_to = wake.unwrap_or(now + IDLE_WAKE);
        tokio::select! {
            job = jobs_rx.recv() => match job {
                Some(job) => enqueue(job, &mut unwindowed, &mut commands, &mut background),
                // Flow handle dropped: the client is gone.
                None => return,
            },
            evt = events_rx.recv() => match evt {
                Some(FlowEvent::Ack(sig)) => {
                    st.on_ack(&sig, Instant::now());
                }
                Some(FlowEvent::PciError) => st.on_pci_error(Instant::now()),
                None => return,
            },
            _ = tokio::time::sleep_until(sleep_to) => {}
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn state() -> FlowState {
        FlowState::new(FlowConfig::default())
    }

    fn t0() -> Instant {
        Instant::now()
    }

    const MS: Duration = Duration::from_millis(1);

    // ------------------------------------------------------- core: window

    #[test]
    fn window_blocks_at_w_and_ack_releases_oldest_match() {
        let mut st = state();
        let now = t0();
        assert_eq!(st.gate(true, now), Gate::Ready);
        st.record_send(ResponseKind::Confirmation(b'h'), now);
        st.record_send(ResponseKind::Confirmation(b'i'), now + 30 * MS);
        // window (2) full: ack- or timeout-gated, not time-gated
        assert_eq!(st.gate(true, now + 60 * MS), Gate::Window);
        // wrong code releases nothing
        assert!(!st.on_ack(&AckSignal::Confirmation(b'x'), now + 70 * MS));
        assert_eq!(st.gate(true, now + 70 * MS), Gate::Window);
        // matching code frees a slot
        assert!(st.on_ack(&AckSignal::Confirmation(b'h'), now + 80 * MS));
        assert_eq!(st.gate(true, now + 80 * MS), Gate::Ready);
    }

    #[test]
    fn report_ack_matches_app_block_kind_and_releases_oldest_first() {
        let mut st = state();
        let now = t0();
        let kind = ResponseKind::Report {
            app: 0x38,
            block: 0,
            level: false,
        };
        st.record_send(kind, now);
        st.record_send(kind, now + 30 * MS);
        // kind/app/block mismatches release nothing
        for sig in [
            AckSignal::Report {
                app: 0x38,
                block: 0,
                level: true,
            },
            AckSignal::Report {
                app: 0x30,
                block: 0,
                level: false,
            },
            AckSignal::Report {
                app: 0x38,
                block: 0x20,
                level: false,
            },
            AckSignal::Confirmation(b'h'),
        ] {
            assert!(!st.on_ack(&sig, now + 40 * MS), "{sig:?} must not match");
        }
        // an exact match releases the OLDER of the two identical entries
        let sig = AckSignal::Report {
            app: 0x38,
            block: 0,
            level: false,
        };
        assert!(st.on_ack(&sig, now + 50 * MS));
        assert_eq!(st.in_flight.len(), 1);
        assert_eq!(st.in_flight[0].sent_at, now + 30 * MS);
        assert!(st.on_ack(&sig, now + 60 * MS));
        assert!(st.in_flight.is_empty());
    }

    // -------------------------------------------------------- core: floor

    #[test]
    fn floor_gates_next_send_until_30ms_after_last_write() {
        let mut st = state();
        let now = t0();
        st.record_send(ResponseKind::Silent, now);
        assert_eq!(st.gate(true, now + 10 * MS), Gate::Until(now + 30 * MS));
        assert_eq!(st.gate(true, now + 30 * MS), Gate::Ready);
        // raw (retransmit) sends restart the floor too
        st.record_raw_send(now + 40 * MS);
        assert_eq!(st.gate(false, now + 41 * MS), Gate::Until(now + 70 * MS));
    }

    // ------------------------------------------------------ core: timeout

    #[test]
    fn timeout_releases_slot_and_two_consecutive_collapse_window() {
        let mut st = state();
        let now = t0();
        st.record_send(ResponseKind::Confirmation(b'h'), now);
        let rto = st.rto();
        assert_eq!(
            rto,
            Duration::from_millis(500),
            "seed 200ms -> clamped floor"
        );
        assert_eq!(st.next_deadline(), Some(now + rto));
        // not yet expired
        st.expire(now + rto - MS);
        assert_eq!(st.in_flight.len(), 1);
        // first timeout: slot freed, window intact
        st.expire(now + rto);
        assert!(st.in_flight.is_empty());
        assert_eq!(st.consecutive_timeouts, 1);
        assert_eq!(st.window, 2);
        // second consecutive timeout: collapse to 1
        st.record_send(ResponseKind::Confirmation(b'i'), now + rto);
        st.expire(now + rto * 2);
        assert_eq!(st.window, 1);
        assert!(st.collapsed);
        // a clean ack resets the consecutive count
        st.record_send(ResponseKind::Confirmation(b'j'), now + rto * 2);
        assert!(st.on_ack(&AckSignal::Confirmation(b'j'), now + rto * 2 + 100 * MS));
        assert_eq!(st.consecutive_timeouts, 0);
    }

    #[test]
    fn silent_frames_release_after_hold_without_timeout_penalty() {
        let mut st = state();
        let now = t0();
        st.clean_acks = 5;
        st.record_send(ResponseKind::Silent, now);
        assert_eq!(st.next_deadline(), Some(now + 100 * MS));
        st.expire(now + 100 * MS);
        assert!(st.in_flight.is_empty());
        assert_eq!(st.consecutive_timeouts, 0, "silent expiry is not a timeout");
        assert_eq!(st.clean_acks, 5, "silent expiry keeps the clean-ack run");
        assert_eq!(st.window, 2);
    }

    // ---------------------------------------------------- core: EWMA/RTO

    #[test]
    fn ack_updates_ewma_variance_and_rto_clamps_both_ends() {
        let mut st = state();
        let now = t0();
        // seed: 200ms -> 2.5x = 500ms == clamp floor
        assert_eq!(st.rto(), Duration::from_millis(500));
        // slow acks push the estimate (and RTO) up
        let mut at = now;
        for i in 0..40 {
            st.record_send(ResponseKind::Confirmation(b'h'), at);
            let ack_at = at + Duration::from_millis(1500);
            // avoid slot expiry interfering: ack before expire is called
            assert!(st.on_ack(&AckSignal::Confirmation(b'h'), ack_at));
            at = ack_at;
            if i == 0 {
                // one 1.5s sample against ewma 0.2: ewma = 0.2 + (1.3/8)
                assert!((st.ewma - 0.3625).abs() < 1e-9, "ewma={}", st.ewma);
                assert!((st.var - 0.325).abs() < 1e-9, "var={}", st.var);
            }
        }
        assert!((st.ewma - 1.5).abs() < 0.05, "ewma converges: {}", st.ewma);
        assert_eq!(st.rto(), Duration::from_secs(2), "upper clamp");
        assert!(
            st.var < 0.05,
            "variance decays on steady latency: {}",
            st.var
        );
        // fast acks bring it back down to the lower clamp
        for _ in 0..60 {
            st.record_send(ResponseKind::Confirmation(b'h'), at);
            let ack_at = at + Duration::from_millis(50);
            assert!(st.on_ack(&AckSignal::Confirmation(b'h'), ack_at));
            at = ack_at;
        }
        assert!((st.ewma - 0.05).abs() < 0.05, "ewma={}", st.ewma);
        assert_eq!(st.rto(), Duration::from_millis(500), "lower clamp");
    }

    // --------------------------------------------------------- core: AIMD

    fn feed_clean_acks(st: &mut FlowState, n: usize, mut at: Instant) -> Instant {
        for _ in 0..n {
            st.record_send(ResponseKind::Confirmation(b'h'), at);
            at += 100 * MS;
            assert!(st.on_ack(&AckSignal::Confirmation(b'h'), at));
        }
        at
    }

    #[test]
    fn window_grows_one_per_10_clean_acks_and_caps_at_max() {
        let mut st = state();
        let mut at = t0();
        assert_eq!(st.window, 2);
        at = feed_clean_acks(&mut st, 9, at);
        assert_eq!(st.window, 2);
        at = feed_clean_acks(&mut st, 1, at);
        assert_eq!(st.window, 3);
        at = feed_clean_acks(&mut st, 10, at);
        assert_eq!(st.window, 4);
        feed_clean_acks(&mut st, 30, at);
        assert_eq!(st.window, 4, "capped at window_max");
    }

    #[test]
    fn timeout_resets_the_clean_ack_run() {
        let mut st = state();
        let mut at = t0();
        at = feed_clean_acks(&mut st, 9, at);
        // a timeout wipes the run: 9 more clean acks must not grow W
        st.record_send(ResponseKind::Confirmation(b'i'), at);
        let expired = at + st.rto();
        st.expire(expired);
        at = feed_clean_acks(&mut st, 9, expired);
        assert_eq!(st.window, 2);
        feed_clean_acks(&mut st, 1, at);
        assert_eq!(st.window, 3);
    }

    #[test]
    fn pci_error_pauses_all_sends_and_collapses_then_recovers() {
        let mut st = state();
        let now = t0();
        st.on_pci_error(now);
        assert_eq!(st.window, 1);
        assert!(st.collapsed);
        // both windowed and raw sends wait out the pause
        assert_eq!(st.gate(true, now + 10 * MS), Gate::Until(now + 250 * MS));
        assert_eq!(st.gate(false, now + 10 * MS), Gate::Until(now + 250 * MS));
        assert_eq!(st.gate(true, now + 250 * MS), Gate::Ready);
        // a second `!` extends, never shortens, the pause
        st.on_pci_error(now + 100 * MS);
        assert_eq!(st.gate(false, now + 260 * MS), Gate::Until(now + 350 * MS));
        // additive recovery: 10 clean acks regrow the window by one
        let at = feed_clean_acks(&mut st, 10, now + 350 * MS);
        assert_eq!(st.window, 2);
        assert!(!st.collapsed);
        feed_clean_acks(&mut st, 10, at);
        assert_eq!(st.window, 3);
    }

    // ------------------------------------------------------ backoff math

    #[test]
    fn backoff_schedule_is_1_2_4_seconds_capped() {
        assert_eq!(retry_backoff(1), Duration::from_secs(1));
        assert_eq!(retry_backoff(2), Duration::from_secs(2));
        assert_eq!(retry_backoff(3), Duration::from_secs(4));
        assert_eq!(retry_backoff(4), Duration::from_secs(4), "capped");
        assert_eq!(retry_backoff(0), Duration::from_secs(1), "defensive");
    }

    #[test]
    fn jitter_stays_within_20_percent_bounds() {
        let d = Duration::from_secs(1);
        assert_eq!(jittered(d, 0.0), Duration::from_millis(800));
        assert_eq!(jittered(d, 0.5), Duration::from_secs(1));
        assert!(jittered(d, 0.999999) < Duration::from_millis(1201));
        for attempt in 1..=3 {
            let nominal = retry_backoff(attempt);
            for _ in 0..200 {
                let j = jittered_backoff(attempt);
                assert!(j >= nominal.mul_f64(0.8), "{j:?} below -20% of {nominal:?}");
                assert!(j <= nominal.mul_f64(1.2), "{j:?} above +20% of {nominal:?}");
            }
        }
    }

    #[test]
    fn cheap_unit_rand_is_uniform_enough_and_in_range() {
        let mut acc = 0.0;
        for _ in 0..1000 {
            let r = cheap_unit_rand();
            assert!((0.0..1.0).contains(&r));
            acc += r;
        }
        let mean = acc / 1000.0;
        assert!((0.3..0.7).contains(&mean), "suspicious mean {mean}");
    }

    // -------------------------------------------------------- async driver

    /// AsyncWrite capturing (virtual-time instant, bytes) per write.
    #[derive(Clone, Default)]
    struct RecordingWriter(std::sync::Arc<std::sync::Mutex<Vec<(Instant, Vec<u8>)>>>);

    impl RecordingWriter {
        fn writes(&self) -> Vec<(Instant, Vec<u8>)> {
            self.0.lock().unwrap().clone()
        }
    }

    impl AsyncWrite for RecordingWriter {
        fn poll_write(
            self: std::pin::Pin<&mut Self>,
            _cx: &mut std::task::Context<'_>,
            buf: &[u8],
        ) -> std::task::Poll<std::io::Result<usize>> {
            self.0.lock().unwrap().push((Instant::now(), buf.to_vec()));
            std::task::Poll::Ready(Ok(buf.len()))
        }
        fn poll_flush(
            self: std::pin::Pin<&mut Self>,
            _cx: &mut std::task::Context<'_>,
        ) -> std::task::Poll<std::io::Result<()>> {
            std::task::Poll::Ready(Ok(()))
        }
        fn poll_shutdown(
            self: std::pin::Pin<&mut Self>,
            _cx: &mut std::task::Context<'_>,
        ) -> std::task::Poll<std::io::Result<()>> {
            std::task::Poll::Ready(Ok(()))
        }
    }

    fn start_flow() -> (Flow, RecordingWriter) {
        let w = RecordingWriter::default();
        let flow = Flow::start(
            std::sync::Arc::new(tokio::sync::Mutex::new(w.clone())),
            FlowConfig::default(),
        );
        (flow, w)
    }

    fn conf(n: u8) -> ResponseKind {
        ResponseKind::Confirmation(n)
    }

    #[tokio::test(start_paused = true)]
    async fn driver_is_ack_clocked_third_frame_waits_for_ack() {
        let (flow, w) = start_flow();
        let r1 = flow.submit(b"1".to_vec(), Priority::Command, conf(b'h'));
        let r2 = flow.submit(b"2".to_vec(), Priority::Command, conf(b'i'));
        let _r3 = flow.submit(b"3".to_vec(), Priority::Command, conf(b'j'));
        r1.await.unwrap().unwrap();
        r2.await.unwrap().unwrap();
        // window 2 full; the third frame must NOT go out on its own
        tokio::time::sleep(Duration::from_millis(200)).await;
        assert_eq!(w.writes().len(), 2);
        // ack frame 1 -> frame 3 goes out promptly
        flow.ack(AckSignal::Confirmation(b'h'));
        tokio::time::sleep(Duration::from_millis(100)).await;
        let writes = w.writes();
        assert_eq!(writes.len(), 3);
        assert_eq!(writes[2].1, b"3");
    }

    #[tokio::test(start_paused = true)]
    async fn driver_enforces_exact_30ms_floor_between_writes() {
        let (flow, w) = start_flow();
        // acks keep the window open so only the floor paces the stream
        let mut receivers = Vec::new();
        for i in 0..4u8 {
            receivers.push(flow.submit(vec![i], Priority::Command, conf(b'h' + i)));
        }
        for (i, r) in receivers.into_iter().enumerate() {
            r.await.unwrap().unwrap();
            flow.ack(AckSignal::Confirmation(b'h' + i as u8));
        }
        let writes = w.writes();
        assert_eq!(writes.len(), 4);
        for pair in writes.windows(2) {
            // paused clock: the spacing is exactly the 30ms floor
            assert_eq!(pair[1].0 - pair[0].0, Duration::from_millis(30));
        }
    }

    #[tokio::test(start_paused = true)]
    async fn driver_prefers_commands_over_earlier_background_frames() {
        let (flow, w) = start_flow();
        // enqueued back-to-back: the driver drains all three before its
        // first transmission decision, so the command must lead
        let rb1 = flow.submit(b"bg1".to_vec(), Priority::Background, conf(b'h'));
        let rb2 = flow.submit(b"bg2".to_vec(), Priority::Background, conf(b'i'));
        let rc = flow.submit(b"cmd".to_vec(), Priority::Command, conf(b'j'));
        rc.await.unwrap().unwrap();
        rb1.await.unwrap().unwrap();
        // window (2) now full: ack the command so bg2 can go out
        flow.ack(AckSignal::Confirmation(b'j'));
        rb2.await.unwrap().unwrap();
        let order: Vec<Vec<u8>> = w.writes().into_iter().map(|(_, b)| b).collect();
        assert_eq!(
            order,
            vec![b"cmd".to_vec(), b"bg1".to_vec(), b"bg2".to_vec()]
        );
    }

    #[tokio::test(start_paused = true)]
    async fn driver_timeouts_release_slots_pipeline_never_stalls() {
        let (flow, w) = start_flow();
        // nothing ever acks: every slot must be released by its RTO
        let receivers: Vec<_> = (0..5u8)
            .map(|i| flow.submit(vec![i], Priority::Background, conf(b'h' + i)))
            .collect();
        for r in receivers {
            r.await.unwrap().unwrap();
        }
        let writes = w.writes();
        assert_eq!(writes.len(), 5, "all frames delivered despite zero acks");
        // frames 1,2 at t0/t0+30ms; the rest are RTO-clocked (500ms seed)
        let span = writes[4].0 - writes[0].0;
        assert!(span >= Duration::from_millis(1500), "span {span:?}");
    }

    #[tokio::test(start_paused = true)]
    async fn driver_pci_error_pauses_next_write_250ms() {
        let (flow, w) = start_flow();
        let r1 = flow.submit(b"1".to_vec(), Priority::Command, conf(b'h'));
        r1.await.unwrap().unwrap();
        flow.ack(AckSignal::Confirmation(b'h'));
        // let the driver process the ack before the error arrives
        tokio::time::sleep(Duration::from_millis(50)).await;
        flow.pci_error();
        tokio::time::sleep(Duration::from_millis(1)).await;
        let before_pause = Instant::now();
        let r2 = flow.submit(b"2".to_vec(), Priority::Command, conf(b'i'));
        r2.await.unwrap().unwrap();
        let writes = w.writes();
        assert_eq!(writes.len(), 2);
        let waited = writes[1].0 - before_pause;
        assert!(
            waited >= Duration::from_millis(240),
            "second write must wait out the pause, waited {waited:?}"
        );
    }

    #[tokio::test(start_paused = true)]
    async fn driver_unwindowed_bypasses_full_window_but_keeps_floor() {
        let (flow, w) = start_flow();
        let r1 = flow.submit(b"1".to_vec(), Priority::Command, conf(b'h'));
        let r2 = flow.submit(b"2".to_vec(), Priority::Command, conf(b'i'));
        r1.await.unwrap().unwrap();
        r2.await.unwrap().unwrap();
        // window full; a retransmit must still go through, floor-paced
        let rr = flow.submit_unwindowed(b"retry".to_vec());
        rr.await.unwrap().unwrap();
        let writes = w.writes();
        assert_eq!(writes.len(), 3);
        assert_eq!(writes[2].1, b"retry");
        assert_eq!(writes[2].0 - writes[1].0, Duration::from_millis(30));
        // ...while a windowed frame stays queued
        let r4 = flow.submit(b"4".to_vec(), Priority::Command, conf(b'j'));
        tokio::time::sleep(Duration::from_millis(100)).await;
        assert_eq!(w.writes().len(), 3);
        flow.ack(AckSignal::Confirmation(b'h'));
        r4.await.unwrap().unwrap();
        assert_eq!(w.writes().len(), 4);
    }

    #[tokio::test(start_paused = true)]
    async fn driver_reports_write_errors_to_the_submitter() {
        struct FailWriter;
        impl AsyncWrite for FailWriter {
            fn poll_write(
                self: std::pin::Pin<&mut Self>,
                _cx: &mut std::task::Context<'_>,
                _buf: &[u8],
            ) -> std::task::Poll<std::io::Result<usize>> {
                std::task::Poll::Ready(Err(std::io::Error::new(
                    std::io::ErrorKind::BrokenPipe,
                    "gone",
                )))
            }
            fn poll_flush(
                self: std::pin::Pin<&mut Self>,
                _cx: &mut std::task::Context<'_>,
            ) -> std::task::Poll<std::io::Result<()>> {
                std::task::Poll::Ready(Ok(()))
            }
            fn poll_shutdown(
                self: std::pin::Pin<&mut Self>,
                _cx: &mut std::task::Context<'_>,
            ) -> std::task::Poll<std::io::Result<()>> {
                std::task::Poll::Ready(Ok(()))
            }
        }
        let flow = Flow::start(
            std::sync::Arc::new(tokio::sync::Mutex::new(FailWriter)),
            FlowConfig::default(),
        );
        let r = flow.submit(b"1".to_vec(), Priority::Command, conf(b'h'));
        let err = r.await.unwrap().unwrap_err();
        assert_eq!(err.kind(), std::io::ErrorKind::BrokenPipe);
    }
}
