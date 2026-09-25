//! Tokio one-shot selected-serial address transport.
//!
//! Sends exactly one broadcast from the P3a codec
//! ([`cbus_protocol::serial_address::encode_serial_address`]) on a fresh
//! numeric-IP socket, then closes. The capture window begins when the send
//! completes; every byte is retained up to `max_bytes`. No receipt,
//! rejection, or malformed prefix ends the window early. A valid retained
//! prefix can still correlate when the capture is incomplete.
//!
//! No inventory, commissioning, retry, SMART, or option-change occurs.
//! `send_completed` means bytes were handed to the socket, not bus
//! delivery. Correlation never verifies movement or persistence.
//!
//! Scope notes (oracle `pci_serial_address_transport.py` parity boundaries):
//! close-failure parity is out of scope — Rust `drop(stream)` cannot report
//! a failed close, unlike the oracle which reports `connection_closed:false`
//! plus an error entry. JSON/v1 projections (`sent_byte_count`,
//! `retained_bytes`, `native_response_timeout`, and the
//! `cbus-pci-serial-address-exchange-v1` emitter) live elsewhere, not in
//! this transport module. The oracle's `interrupted` termination (the
//! exception path attaching the exchange to the raised error) has no Rust
//! equivalent because task-abort cannot yield an `Exchange`; the nine
//! `Termination` variants are the complete wire set for this API. Oracle
//! bool/type rejections (timeouts, port, local_unit, confirmation, host)
//! collapse into Rust's `Duration`/`u16`/`u8`/`IpAddr` types and are
//! unrepresentable here, not unhandled. Termination coverage is
//! intentionally partial: `matched` (via `classify_receipt`),
//! `response_window_elapsed`, `disconnected`, `byte_limit`, and
//! `insufficient_response_budget` are pinned by loopback tests.
//! `late_data` is race-only in both oracle and Rust (a delayed-past-window
//! reply yields `response_window_elapsed`; only a recv-near-deadline
//! arrival reports `late_data`), and `overall_timeout`, `send_error`,
//! `receive_error`, `connection_error` need fault injection — all five
//! remain uncovered by design, not by omission.

use cbus_protocol::serial_address::{classify_receipt, encode_serial_address, Receipt};
use std::fmt;
use std::net::IpAddr;
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::Duration;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::TcpStream;

/// Upper bound of the compatibility evidence format.
const MAX_BYTES_LIMIT: usize = 4096;
/// Upper bound for either timeout, in seconds (mirrors the oracle `(0,60]`).
const TIMEOUT_LIMIT_SECS: f64 = 60.0;

/// How the bounded capture window ended.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Termination {
    /// No new data arrived before the response deadline; complete capture.
    ResponseWindowElapsed,
    /// Data arrived at or after the response deadline but before overall.
    LateData,
    /// The peer closed the connection inside the window (EOF).
    Disconnected,
    /// More than `max_bytes` arrived (saturation, incomplete).
    ByteLimit,
    /// The absolute overall deadline passed first.
    OverallTimeout,
    /// Too little overall budget remained for a response window.
    InsufficientResponseBudget,
    /// The send itself failed.
    SendError,
    /// A receive after a completed send failed.
    ReceiveError,
    /// Socket creation or connect failed.
    ConnectionError,
}

impl Termination {
    /// Wire-stable termination name pinned by the oracle contract.
    pub fn as_str(self) -> &'static str {
        match self {
            Termination::ResponseWindowElapsed => "response_window_elapsed",
            Termination::LateData => "late_data",
            Termination::Disconnected => "disconnected",
            Termination::ByteLimit => "byte_limit",
            Termination::OverallTimeout => "overall_timeout",
            Termination::InsufficientResponseBudget => "insufficient_response_budget",
            Termination::SendError => "send_error",
            Termination::ReceiveError => "receive_error",
            Termination::ConnectionError => "connection_error",
        }
    }
}

impl fmt::Display for Termination {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

/// One captured I/O or parse failure attached to an [`Exchange`].
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ExchangeError {
    /// Oracle phase (`connect`, `send`, `receive`, `receipt_parse`, ...).
    pub phase: String,
    /// Error type name.
    pub kind: String,
    /// Error message.
    pub message: String,
}

/// Bounded capture evidence for one one-shot exchange.
///
/// Mirrors the `cbus-pci-serial-address-exchange-v1` fields: request and
/// retained bytes, send flags, receipt plus correlation status, termination,
/// timeouts, closure, and the error list. I/O failures are recorded here;
/// received bytes are never thrown away on error.
#[derive(Debug, Clone)]
pub struct Exchange {
    /// Exact wire bytes sent (P3a encoder output).
    pub request: Vec<u8>,
    /// Retained bytes, truncated to `max_bytes`.
    pub received: Vec<u8>,
    /// True once the send was attempted.
    pub send_attempted: bool,
    /// True once bytes were handed to the socket (not bus delivery).
    pub send_completed: bool,
    /// Total bytes that arrived, including any over `max_bytes`.
    pub bytes_received: usize,
    /// Classification of the retained bytes.
    pub receipt: Receipt,
    /// How the capture window ended.
    pub termination: Termination,
    /// True only for `response_window_elapsed`.
    pub capture_complete: bool,
    /// Wall time from start to the final clock read.
    pub elapsed: Duration,
    /// Wall time from send completion to the final clock read, if sent.
    pub response_elapsed: Option<Duration>,
    /// Response window budget.
    pub response_timeout: Duration,
    /// Absolute overall budget.
    pub overall_timeout: Duration,
    /// Retention cap (1..=4096).
    pub max_bytes: usize,
    /// True once the socket is closed (always true after an exchange).
    pub connection_closed: bool,
    /// First-error-preserved failure list.
    pub errors: Vec<ExchangeError>,
}

impl Exchange {
    /// Receipt correlation status (`matched`, `unverified`, ...).
    pub fn correlation_status(&self) -> &'static str {
        self.receipt.status.as_str()
    }

    /// The retained bytes correlate; never proof of physical movement.
    pub fn matched(&self) -> bool {
        self.receipt.matched()
    }

    /// Always false: correlation is not movement evidence.
    pub fn movement_verified(&self) -> bool {
        false
    }

    /// Always false: one capture never verifies persistence.
    pub fn persistence_verified(&self) -> bool {
        false
    }

    /// Always true: correlation requires independent verification.
    pub fn requires_independent_verification(&self) -> bool {
        true
    }

    /// Always false: this transport performs no inventory.
    pub fn inventory_performed(&self) -> bool {
        false
    }

    /// Always false: this transport updates no database.
    pub fn database_updated(&self) -> bool {
        false
    }

    /// Always false: the broadcast frame has no source-address field.
    pub fn request_has_source_address(&self) -> bool {
        false
    }

    /// Always zero: this transport never retries automatically.
    pub fn automatic_retries(&self) -> u32 {
        0
    }
}

/// Tunables for [`SerialAddressTransport`].
#[derive(Debug, Clone, Copy)]
pub struct SerialAddressOptions {
    /// Capture window after the send completes (0,60]s.
    pub response_timeout: Duration,
    /// Absolute budget from start (0,60]s, strictly greater than response.
    pub overall_timeout: Duration,
    /// Retention cap, 1..=4096.
    pub max_bytes: usize,
    /// Confirmation byte, `g..=z`.
    pub confirmation: u8,
    /// Whether to append the outer SRCHK checksum.
    pub command_checksum: bool,
}

impl Default for SerialAddressOptions {
    fn default() -> Self {
        SerialAddressOptions {
            response_timeout: Duration::from_secs(2),
            overall_timeout: Duration::from_secs(5),
            max_bytes: MAX_BYTES_LIMIT,
            confirmation: b'g',
            command_checksum: false,
        }
    }
}

/// Construction or reuse failure; I/O failures live in [`Exchange::errors`].
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum TransportError {
    /// An argument failed validation.
    InvalidArgument(String),
    /// The one-shot object was already used.
    AlreadyUsed,
}

impl fmt::Display for TransportError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            TransportError::InvalidArgument(message) => write!(f, "{message}"),
            TransportError::AlreadyUsed => write!(
                f,
                "Selected-serial transport is one-shot; requests must never be replayed automatically"
            ),
        }
    }
}

impl std::error::Error for TransportError {}

fn check_timeout(value: Duration, name: &str) -> Result<Duration, TransportError> {
    let secs = value.as_secs_f64();
    if !secs.is_finite() || secs <= 0.0 || secs > TIMEOUT_LIMIT_SECS {
        return Err(TransportError::InvalidArgument(format!(
            "{name} must be finite and in (0,60] seconds"
        )));
    }
    Ok(value)
}

/// One-shot selected-serial address transport.
///
/// Exactly one broadcast on a fresh numeric-IP socket, then close. The
/// second use of the same object fails with [`TransportError::AlreadyUsed`].
#[derive(Debug)]
pub struct SerialAddressTransport {
    host: IpAddr,
    port: u16,
    local_unit: u8,
    options: SerialAddressOptions,
    used: AtomicBool,
}

impl SerialAddressTransport {
    /// Build a one-shot transport over a numeric IP endpoint (no DNS).
    pub fn new(
        host: &str,
        port: u16,
        local_unit: u8,
        options: SerialAddressOptions,
    ) -> Result<Self, TransportError> {
        if host.contains('%') {
            return Err(TransportError::InvalidArgument(
                "A numeric IPv4 or IPv6 endpoint without a scope suffix is required".to_string(),
            ));
        }
        let host: IpAddr = host.parse().map_err(|_| {
            TransportError::InvalidArgument(
                "A numeric IP endpoint is required; DNS is not deadline-bounded".to_string(),
            )
        })?;
        if !(1..=65535).contains(&port) {
            return Err(TransportError::InvalidArgument(
                "port must be an integer in 1..65535".to_string(),
            ));
        }
        if !(b'g'..=b'z').contains(&options.confirmation) {
            return Err(TransportError::InvalidArgument(
                "Confirmation must be exactly one byte in g..z".to_string(),
            ));
        }
        if !(1..=MAX_BYTES_LIMIT).contains(&options.max_bytes) {
            return Err(TransportError::InvalidArgument(
                "max_bytes must be an integer in 1..4096".to_string(),
            ));
        }
        let response_timeout = check_timeout(options.response_timeout, "response_timeout")?;
        let overall_timeout = check_timeout(options.overall_timeout, "overall_timeout")?;
        if overall_timeout <= response_timeout {
            return Err(TransportError::InvalidArgument(
                "overall_timeout must strictly exceed response_timeout".to_string(),
            ));
        }
        Ok(SerialAddressTransport {
            host,
            port,
            local_unit,
            options: SerialAddressOptions {
                response_timeout,
                overall_timeout,
                ..options
            },
            used: AtomicBool::new(false),
        })
    }

    /// Preflight pure inputs, send once, and return only capture evidence.
    ///
    /// I/O failures are recorded in the returned [`Exchange`]; only
    /// invalid arguments or a second use fail with [`TransportError`].
    pub async fn send_serial_address(
        &self,
        serial: &str,
        destination: u8,
    ) -> Result<Exchange, TransportError> {
        let request = encode_serial_address(
            serial,
            destination,
            self.options.command_checksum,
            self.options.confirmation,
        )
        .map_err(|e| TransportError::InvalidArgument(e.0.clone()))?;
        if self.used.swap(true, Ordering::SeqCst) {
            return Err(TransportError::AlreadyUsed);
        }
        Ok(self.exchange(request, serial, destination).await)
    }

    async fn exchange(&self, request: Vec<u8>, serial: &str, destination: u8) -> Exchange {
        let confirmation = self.options.confirmation;
        let local_unit = self.local_unit;
        let max_bytes = self.options.max_bytes;
        let response_timeout = self.options.response_timeout;
        let overall_timeout = self.options.overall_timeout;

        let started = tokio::time::Instant::now();
        let deadline = started + overall_timeout;
        let mut errors: Vec<ExchangeError> = Vec::new();
        let push_error = |errors: &mut Vec<ExchangeError>, phase: &str, err: &dyn fmt::Display| {
            errors.push(ExchangeError {
                phase: phase.to_string(),
                kind: "io".to_string(),
                message: err.to_string(),
            });
        };

        let mut send_attempted = false;
        let mut send_completed = false;
        let mut total_bytes: usize = 0;
        let mut retained: Vec<u8> = Vec::new();
        let mut termination: Option<Termination> = None;
        let mut capture_complete = false;
        let mut sent_at: Option<tokio::time::Instant> = None;

        let mut stream: Option<TcpStream> = None;

        // Overall budget already exhausted before starting.
        if tokio::time::Instant::now() >= deadline {
            termination = Some(Termination::OverallTimeout);
        } else {
            // Connect with the remaining overall budget.
            let remaining = deadline.saturating_duration_since(tokio::time::Instant::now());
            match tokio::time::timeout(remaining, TcpStream::connect((self.host, self.port))).await
            {
                Err(_) => {
                    push_error(&mut errors, "connect", &"connect timed out");
                    termination = Some(Termination::ConnectionError);
                }
                Ok(Err(e)) => {
                    push_error(&mut errors, "connect", &e);
                    termination = Some(Termination::ConnectionError);
                }
                Ok(Ok(s)) => {
                    stream = Some(s);
                }
            }
        }

        if let Some(ref mut stream) = stream {
            if termination.is_none() {
                let now = tokio::time::Instant::now();
                if now >= deadline {
                    termination = Some(Termination::OverallTimeout);
                } else if deadline - now <= response_timeout {
                    termination = Some(Termination::InsufficientResponseBudget);
                } else {
                    // Send phase.
                    let remaining = deadline.saturating_duration_since(now);
                    send_attempted = true;
                    match tokio::time::timeout(remaining, stream.write_all(&request)).await {
                        Err(_) => {
                            push_error(&mut errors, "send", &"send timed out");
                            termination = Some(Termination::SendError);
                        }
                        Ok(Err(e)) => {
                            push_error(&mut errors, "send", &e);
                            termination = Some(Termination::SendError);
                        }
                        Ok(Ok(())) => {
                            send_completed = true;
                            let at = tokio::time::Instant::now();
                            sent_at = Some(at);
                            if at >= deadline {
                                termination = Some(Termination::OverallTimeout);
                            } else if at + response_timeout >= deadline {
                                termination = Some(Termination::InsufficientResponseBudget);
                            } else {
                                // Receive phase: fixed window, no early exit
                                // on receipt/rejection/malformed content.
                                let response_deadline = at + response_timeout;
                                let mut buf = vec![0u8; 4096];
                                loop {
                                    let now = tokio::time::Instant::now();
                                    if now >= deadline {
                                        termination = Some(Termination::OverallTimeout);
                                        break;
                                    }
                                    if now >= response_deadline {
                                        termination = Some(Termination::ResponseWindowElapsed);
                                        capture_complete = true;
                                        break;
                                    }
                                    let wait = std::cmp::min(deadline, response_deadline)
                                        .saturating_duration_since(now);
                                    let want = std::cmp::min(
                                        4096,
                                        max_bytes + 1 - retained.len().min(max_bytes),
                                    );
                                    match tokio::time::timeout(
                                        wait,
                                        stream.read(&mut buf[..want.max(1)]),
                                    )
                                    .await
                                    {
                                        Err(_) => continue,
                                        Ok(Err(e)) => {
                                            push_error(&mut errors, "receive", &e);
                                            termination = Some(Termination::ReceiveError);
                                            break;
                                        }
                                        Ok(Ok(0)) => {
                                            let arrived = tokio::time::Instant::now();
                                            if arrived >= deadline {
                                                termination = Some(Termination::OverallTimeout);
                                            } else if arrived >= response_deadline {
                                                termination = Some(Termination::LateData);
                                            } else {
                                                termination = Some(Termination::Disconnected);
                                            }
                                            break;
                                        }
                                        Ok(Ok(n)) => {
                                            total_bytes += n;
                                            let room = max_bytes.saturating_sub(retained.len());
                                            retained.extend_from_slice(&buf[..n.min(room)]);
                                            let arrived = tokio::time::Instant::now();
                                            if total_bytes > max_bytes {
                                                termination = Some(Termination::ByteLimit);
                                                break;
                                            }
                                            if arrived >= deadline {
                                                termination = Some(Termination::OverallTimeout);
                                                break;
                                            }
                                            if arrived >= response_deadline {
                                                termination = Some(Termination::LateData);
                                                break;
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        } else if termination.is_none() {
            termination = Some(Termination::ConnectionError);
        }

        drop(stream);
        let connection_closed = true;

        let receipt =
            match classify_receipt(&retained, serial, destination, local_unit, confirmation) {
                Ok(receipt) => receipt,
                Err(e) => {
                    errors.push(ExchangeError {
                        phase: "receipt_parse".to_string(),
                        kind: "parse".to_string(),
                        message: e.0.clone(),
                    });
                    // Preflight validated the inputs, so the empty capture
                    // classifies; this fallback never fails in practice.
                    classify_receipt(b"", serial, destination, local_unit, confirmation)
                        .unwrap_or_else(|_| {
                            classify_receipt(b"", "0.1", 2, local_unit, b'g')
                                .expect("fallback receipt")
                        })
                }
            };

        let last = tokio::time::Instant::now();
        let elapsed = last.saturating_duration_since(started);
        let response_elapsed = sent_at.map(|at| last.saturating_duration_since(at));

        Exchange {
            request,
            received: retained,
            send_attempted,
            send_completed,
            bytes_received: total_bytes,
            receipt,
            termination: termination.unwrap_or(Termination::ConnectionError),
            capture_complete,
            elapsed,
            response_elapsed,
            response_timeout,
            overall_timeout,
            max_bytes,
            connection_closed,
            errors,
        }
    }
}

/// One-shot convenience: fresh transport, single exchange, then close.
pub async fn send_serial_address(
    host: &str,
    port: u16,
    local_unit: u8,
    serial: &str,
    destination: u8,
    options: SerialAddressOptions,
) -> Result<Exchange, TransportError> {
    let transport = SerialAddressTransport::new(host, port, local_unit, options)?;
    transport.send_serial_address(serial, destination).await
}
