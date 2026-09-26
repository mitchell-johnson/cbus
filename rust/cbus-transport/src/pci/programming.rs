//! Correlated programming transactions over the same PCI as lighting/MQTT.
//! Pointer selection is volatile; memory reads never issue a memory write.

use super::*;
use cbus_protocol::dali::DaliCalMode;
use cbus_protocol::serial_address::{encode_serial_address, parse_native_serial};
use cbus_protocol::{kfi, label_clear};
use std::io::{Error, ErrorKind, Result};
use std::sync::atomic::{AtomicBool, Ordering};

const REPLY_TIMEOUT: Duration = Duration::from_secs(10);
const IDENTIFY_QUIET: Duration = Duration::from_secs(2);
const IDENTIFY_MAX_REPLIES: usize = 7;
const DUPLICATE_PROBE_QUIET: Duration = Duration::from_secs(2);
const DUPLICATE_PROBE_MAX_REPLIES: usize = 7;
const SERIAL_ADDRESS_QUIET: Duration = Duration::from_secs(2);
const NVM_POLL_INTERVAL: Duration = Duration::from_millis(500);
const NVM_POLL_TIMEOUT: Duration = Duration::from_secs(15);

fn validate_bridge_route(bridges: &[u8]) -> Result<()> {
    if (1..=6).contains(&bridges.len()) {
        Ok(())
    } else {
        Err(Error::new(
            ErrorKind::InvalidInput,
            "routed CAL requires one to six bridges",
        ))
    }
}

fn identify_reply_matches(
    meta: &Meta,
    unit_address: u8,
    bridged: bool,
    hops: &[u8],
    bridges: &[u8],
    unit: u8,
) -> bool {
    if bridges.is_empty() {
        !bridged && meta.source_address == Some(unit)
    } else {
        bridged
            && meta.source_address == bridges.first().copied()
            && hops == &bridges[1..]
            && unit_address == unit
    }
}

// After a cancelled/failed transaction, late untagged CAL fragments cannot be
// distinguished from a future read. Require a fresh connection instead of
// ever returning a potentially misattributed memory image.
struct Transaction<'a> {
    fault: &'a AtomicBool,
    complete: bool,
}

// Cancellation can definitively stop a queued write, but it cannot retract a
// write that started. Fault the programming lane only in the latter case.
struct OneShotWriteTransaction<'a> {
    client: &'a PciClient,
    progress: Arc<flow::WriteProgress>,
    complete: bool,
}

// Once the exact write completes, cancellation or malformed/lost capture
// input still leaves the connection unsafe for another correlated command.
struct SelectedSerialCaptureTransaction<'a> {
    client: &'a PciClient,
    complete: bool,
}

#[derive(Clone, Copy)]
enum ProgrammingRoute {
    DirectChecksummed,
    DirectUnchecksummed,
    Oem,
}

#[derive(Debug, Clone, PartialEq, Eq)]
enum ExtendedOutcome {
    Reply {
        status: u8,
        data: Vec<u8>,
        response_wire: Vec<u8>,
    },
    Nak {
        response_wire: Vec<u8>,
    },
}

/// One source-correlated DALI extended-CAL exchange.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DaliExchange {
    /// Native command mode sent for this exchange.
    pub mode: DaliCalMode,
    /// Canonical native outgoing command string, including its leading `\`.
    pub request_wire: String,
    /// Exact decoded C-Bus reply re-encoded as binary wire bytes.
    pub response_wire: Vec<u8>,
    /// Native gateway status byte, or `0xFF` for a correlated NAK.
    pub status: u8,
    /// Operation-specific response bytes.
    pub data: Vec<u8>,
    /// Whether the correlated response was a CAL negative acknowledgement.
    pub nak: bool,
}

/// Result of one explicit DALI mode or an AUTO execute/poll sequence.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DaliCommandResult {
    /// Every exchange in order. AUTO retains its execute and all polls.
    pub exchanges: Vec<DaliExchange>,
}

/// One already-validated native patch-memory block.
///
/// C-Gate's patch parser emits at most twelve contiguous bytes and marks
/// blocks that need the parameter unlock exchange.  The service validates
/// address ranges and overlap before constructing this transport value.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PatchProgrammingBlock {
    /// First standard CAL parameter written by this block.
    pub parameter: u8,
    /// One to twelve patch bytes.
    pub data: Vec<u8>,
    /// Run native parameter unlock before the tagged STORE.
    pub unlock: bool,
}

/// Verified result of a complete physical patch pipeline.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PatchApplyReceipt {
    /// Patch version read before any mutation.
    pub previous_version: u8,
    /// Version required and read back after the pipeline.
    pub target_version: u8,
    /// Number of patch blocks with exact readback.
    pub verified_blocks: usize,
    /// Which verified physical path completed.
    pub disposition: PatchApplyDisposition,
}

/// Observable outcome of a verified patch request.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PatchApplyDisposition {
    /// The complete disable/write/full-verify/version/enable pipeline ran.
    AppliedFullPipeline,
    /// Version and blocks matched, but control parameter 0x70 needed repair.
    RepairedEnableOnly,
    /// Version, blocks and control parameter 0x70 matched without a STORE.
    AlreadyVerifiedReadOnly,
}

impl PatchApplyDisposition {
    /// Stable receipt/event spelling.
    pub fn as_str(self) -> &'static str {
        match self {
            Self::AppliedFullPipeline => "applied_full_pipeline",
            Self::RepairedEnableOnly => "repaired_enable_only",
            Self::AlreadyVerifiedReadOnly => "already_verified_read_only",
        }
    }
}

/// Correlated acceptance of one selected-serial address broadcast.
///
/// This records the exact addressed receipt only. It never proves movement,
/// persistence, or uniqueness; callers must perform independent inventory.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SelectedSerialAcceptance {
    /// Canonical serial selected by the broadcast.
    pub serial: String,
    /// Requested address and source of the correlated receipt.
    pub destination: u8,
    /// Attached PCI unit that received the correlated reply.
    pub local_unit: u8,
    /// Two native reply bytes whose meaning is not established.
    pub opaque_tail: [u8; 2],
}

/// Bounded evidence from one strict-plan selected-serial send.
///
/// `send_completed` means the exact request finished writing to the shared
/// PCI transport. `receipt_matched` is only correlation evidence; a complete
/// capture can return `false` for a missing, rejected, reordered, duplicate,
/// or nonmatching receipt so that the caller can perform independent
/// inventory. This type never claims movement or persistence.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SelectedSerialApplyEvidence {
    /// Exact plan bytes submitted once outside the retry table.
    pub request: Vec<u8>,
    /// True after the exact request finished writing to the shared transport.
    pub send_completed: bool,
    /// True only for one positive fixed-code confirmation followed by one
    /// exact direct receipt with no contradictory address evidence.
    pub receipt_matched: bool,
    /// Whether any confirmation using the selected code was captured.
    pub confirmation_observed: bool,
    /// Whether any selected-serial-shaped receipt was captured.
    pub receipt_observed: bool,
}

/// Failure evidence from one strict-plan selected-serial send.
///
/// The progress fields distinguish a definite pre-write refusal from an
/// uncertain started write and from a completed write followed by malformed
/// or lost response input. Any failure with `send_attempted=true` requires
/// discarding the [`PciClient`].
#[derive(Debug)]
pub struct SelectedSerialApplyError {
    /// Exact plan bytes associated with the failed transaction.
    pub request: Vec<u8>,
    /// Whether the queued writer irrevocably started processing the request.
    pub send_attempted: bool,
    /// Whether the exact request finished writing to the shared transport.
    pub send_completed: bool,
    /// Whether any confirmation using the selected code was captured.
    pub confirmation_observed: bool,
    /// Whether any selected-serial-shaped receipt was captured.
    pub receipt_observed: bool,
    error: Error,
}

impl SelectedSerialApplyError {
    fn new(
        error: Error,
        request: &[u8],
        send_attempted: bool,
        send_completed: bool,
        confirmation_observed: bool,
        receipt_observed: bool,
    ) -> Self {
        Self {
            request: request.to_vec(),
            send_attempted,
            send_completed,
            confirmation_observed,
            receipt_observed,
            error,
        }
    }

    /// Underlying I/O error category.
    pub fn kind(&self) -> ErrorKind {
        self.error.kind()
    }
}

impl std::fmt::Display for SelectedSerialApplyError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        self.error.fmt(f)
    }
}

impl std::error::Error for SelectedSerialApplyError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        Some(&self.error)
    }
}

impl Drop for Transaction<'_> {
    fn drop(&mut self) {
        if !self.complete {
            self.fault.store(true, Ordering::Release);
        }
    }
}

impl Drop for OneShotWriteTransaction<'_> {
    fn drop(&mut self) {
        if !self.complete && !self.progress.cancel_before_start() {
            self.client.programming_fault.store(true, Ordering::Release);
            self.client.request_shutdown();
        }
    }
}

impl Drop for SelectedSerialCaptureTransaction<'_> {
    fn drop(&mut self) {
        if !self.complete {
            self.client.programming_fault.store(true, Ordering::Release);
            self.client.request_shutdown();
        }
    }
}

impl PciClient {
    /// Run native C-Gate's operational `LABEL KFIGET` sequence.
    ///
    /// Despite its name, the operation first performs three volatile
    /// parameter-`0xFF` writes. Each write must receive the source-correlated
    /// `32 FF 00` unit acknowledgement before the attribute-`0x3D` IDENTIFY is
    /// sent. The returned vector deliberately retains response multiplicity so
    /// the C-Gate endpoint can distinguish native 524 no-response and
    /// too-many-response outcomes.
    pub async fn get_key_function_indicators(&self, unit: u8) -> Result<Vec<[u8; kfi::COUNT]>> {
        let requests = kfi::get_requests();
        let _lane = self.programming_lane.lock().await;
        if self.programming_fault.load(Ordering::Acquire) {
            return Err(Error::other(
                "programming stream needs reconnect after an incomplete transaction",
            ));
        }
        let mut transaction = Transaction {
            fault: &self.programming_fault,
            complete: false,
        };
        for request in requests.iter().take(3).cloned() {
            self.kfi_write(unit, request).await?;
        }
        let replies = self.collect_kfi_replies(unit, requests[3].clone()).await?;
        transaction.complete = true;
        Ok(replies)
    }

    /// Run native C-Gate's operational `LABEL KFISET` sequence.
    ///
    /// All eight values must be in `0..=15`. The four parameter-`0xFF`
    /// writes are serialized and the sequence stops at the first missing,
    /// rejected, or malformed source-correlated acknowledgement.
    pub async fn set_key_function_indicators(
        &self,
        unit: u8,
        values: [u8; kfi::COUNT],
    ) -> Result<()> {
        let requests = kfi::set_requests(values)
            .map_err(|error| Error::new(ErrorKind::InvalidInput, error.0))?;
        let _lane = self.programming_lane.lock().await;
        if self.programming_fault.load(Ordering::Acquire) {
            return Err(Error::other(
                "programming stream needs reconnect after an incomplete transaction",
            ));
        }
        let mut transaction = Transaction {
            fault: &self.programming_fault,
            complete: false,
        };
        for request in requests {
            self.kfi_write(unit, request).await?;
        }
        transaction.complete = true;
        Ok(())
    }

    // Caller holds programming_lane. Native ct requires both normal PCI
    // delivery confirmation and a source-correlated `32 FF 00` unit ACK.
    async fn kfi_write(&self, unit: u8, request: Cal) -> Result<()> {
        let mut replies = self.packets.subscribe();
        if !self.is_connected() {
            return Err(Error::new(ErrorKind::BrokenPipe, "PCI disconnected"));
        }
        let packet = Packet::PointToPoint {
            meta: Meta::new(true, 1),
            unit_address: unit,
            bridged: false,
            hops: vec![],
            cals: vec![request],
        };
        // KFI selector writes are stateful and their unit ACK is untagged.
        // Send exactly once: replay after a lost confirmation could create a
        // delayed identical ACK that a following selector write cannot
        // distinguish from its own response.
        let confirmation = self.send_guarded_once(&packet).await?;
        let code = confirmation.code;
        tokio::time::timeout(REPLY_TIMEOUT, async {
            let mut confirmed = false;
            let mut accepted = false;
            loop {
                match replies.recv().await {
                    Ok(Some(Packet::Confirmation { code: got, success })) if got == code => {
                        if confirmed {
                            return Err(Error::new(
                                ErrorKind::InvalidData,
                                "duplicate KFI write confirmation",
                            ));
                        }
                        if !success {
                            return Err(Error::other("PCI rejected KFI write"));
                        }
                        confirmed = true;
                    }
                    Ok(Some(Packet::PciError)) => {
                        return Err(Error::other("PCI rejected KFI write"));
                    }
                    Ok(Some(packet)) => {
                        let cals = match packet {
                            Packet::PointToPoint { meta, cals, .. }
                                if meta.source_address == Some(unit) =>
                            {
                                cals
                            }
                            Packet::PointToPoint { meta, cals, .. }
                                if meta.source_address.is_none()
                                    && self.local_unit.load(Ordering::Acquire)
                                        == u16::from(unit) =>
                            {
                                cals
                            }
                            Packet::BareCal(cal)
                                if self.local_unit.load(Ordering::Acquire) == u16::from(unit) =>
                            {
                                vec![cal]
                            }
                            _ => continue,
                        };
                        for cal in cals {
                            match cal {
                                Cal::Ack {
                                    parameter: 0xff,
                                    data,
                                } if data == [0] => accepted = true,
                                // Native ct accepts only the exact `32 FF 00`
                                // success prefix. A `3B FF` NAK can carry
                                // operation-specific error detail, but no tail
                                // can turn that source-correlated rejection
                                // into success.
                                Cal::Nak {
                                    parameter: 0xff, ..
                                } => {
                                    return Err(Error::other("unit rejected KFI write"));
                                }
                                _ => {}
                            }
                        }
                    }
                    Ok(None) | Err(_) => {
                        return Err(Error::new(
                            ErrorKind::BrokenPipe,
                            "PCI response stream lost",
                        ));
                    }
                }
                if confirmed && accepted {
                    return Ok(());
                }
            }
        })
        .await
        .unwrap_or_else(|_| Err(Error::new(ErrorKind::TimedOut, "KFI write timed out")))
    }

    // Caller holds programming_lane across the three KFIGET selector writes
    // and this complete response window.
    async fn collect_kfi_replies(&self, unit: u8, request: Cal) -> Result<Vec<[u8; kfi::COUNT]>> {
        let mut replies = self.packets.subscribe();
        if !self.is_connected() {
            return Err(Error::new(ErrorKind::BrokenPipe, "PCI disconnected"));
        }
        let packet = Packet::PointToPoint {
            meta: Meta::new(true, 1),
            unit_address: unit,
            bridged: false,
            hops: vec![],
            cals: vec![request],
        };
        // Reply multiplicity is part of KFIGET's native result, so replaying
        // the IDENTIFY would also turn one unit into a false multi-response.
        let confirmation = self.send_guarded_once(&packet).await?;
        let code = confirmation.code;

        tokio::time::timeout(REPLY_TIMEOUT, async {
            let mut confirmed = false;
            let mut collected = Vec::new();
            let mut quiet_deadline = None;
            loop {
                let next = async {
                    match quiet_deadline {
                        Some(deadline) => tokio::time::timeout_at(deadline, replies.recv())
                            .await
                            .map_err(|_| Error::new(ErrorKind::TimedOut, "KFIGET quiet"))?,
                        None => replies.recv().await,
                    }
                    .map_err(|_| Error::new(ErrorKind::BrokenPipe, "PCI response stream lost"))
                };
                let packet = match next.await {
                    Err(error)
                        if error.kind() == ErrorKind::TimedOut && quiet_deadline.is_some() =>
                    {
                        return Ok(collected);
                    }
                    Err(error) => return Err(error),
                    Ok(None) => {
                        return Err(Error::new(
                            ErrorKind::BrokenPipe,
                            "PCI response stream lost",
                        ));
                    }
                    Ok(Some(packet)) => packet,
                };
                if let Packet::Confirmation { code: got, success } = &packet {
                    if *got != code {
                        continue;
                    }
                    if confirmed {
                        return Err(Error::new(
                            ErrorKind::InvalidData,
                            "duplicate KFIGET confirmation",
                        ));
                    }
                    if !*success {
                        return Err(Error::other("PCI rejected KFIGET IDENTIFY command"));
                    }
                    confirmed = true;
                    if collected.len() > 1 {
                        return Ok(collected);
                    }
                    quiet_deadline = Some(Instant::now() + IDENTIFY_QUIET);
                    continue;
                }
                if matches!(packet, Packet::PciError) {
                    return Err(Error::other("PCI rejected KFIGET IDENTIFY command"));
                }
                let cals = match packet {
                    Packet::PointToPoint { meta, cals, .. }
                        if meta.source_address == Some(unit) =>
                    {
                        cals
                    }
                    Packet::PointToPoint { meta, cals, .. }
                        if meta.source_address.is_none()
                            && self.local_unit.load(Ordering::Acquire) == u16::from(unit) =>
                    {
                        cals
                    }
                    Packet::BareCal(cal)
                        if self.local_unit.load(Ordering::Acquire) == u16::from(unit) =>
                    {
                        vec![cal]
                    }
                    _ => continue,
                };
                let matches_attribute = cals.iter().any(
                    |cal| matches!(cal, Cal::Reply { parameter, .. } if *parameter == kfi::ATTRIBUTE),
                );
                if !matches_attribute {
                    continue;
                }
                if cals.len() != 1 {
                    return Err(Error::new(
                        ErrorKind::InvalidData,
                        "KFIGET reply contains an ambiguous CAL chain",
                    ));
                }
                let Cal::Reply { data, .. } = &cals[0] else {
                    unreachable!("matching KFIGET reply checked above")
                };
                let values = kfi::decode_reply(data)
                    .map_err(|error| Error::new(ErrorKind::InvalidData, error.0))?;
                if collected.len() < 2 {
                    collected.push(values);
                }
                if confirmed && collected.len() > 1 {
                    return Ok(collected);
                }
                if confirmed {
                    quiet_deadline = Some(Instant::now() + IDENTIFY_QUIET);
                }
            }
        })
        .await
        .unwrap_or_else(|_| Err(Error::new(ErrorKind::TimedOut, "KFIGET reply timed out")))
    }

    /// Send one selected-serial address broadcast on this shared PCI.
    ///
    /// cmqttd enables SRCHK, so the exact request includes both the native
    /// inner serial-address checksum and the outer command checksum. The
    /// operation is never placed in the retry table. Success requires one
    /// positive PCI confirmation followed by one exact direct `87 00`
    /// receipt and a two-second quiet interval. It remains receipt evidence,
    /// not movement or persistence evidence.
    pub async fn address_selected_serial(
        &self,
        serial: &str,
        destination: u8,
    ) -> Result<SelectedSerialAcceptance> {
        self.address_selected_serial_inner(serial, destination)
            .await
    }

    async fn address_selected_serial_inner(
        &self,
        serial: &str,
        destination: u8,
    ) -> Result<SelectedSerialAcceptance> {
        let selected = parse_native_serial(serial)
            .map_err(|error| Error::new(ErrorKind::InvalidInput, error.0))?;
        if !selected.known || !(2..=254).contains(&destination) {
            return Err(Error::new(
                ErrorKind::InvalidInput,
                "selected-serial address requires a known serial and destination in 2..254",
            ));
        }
        let local = self.local_unit.load(Ordering::Acquire);
        if local > u8::MAX.into() {
            return Err(Error::new(
                ErrorKind::InvalidInput,
                "selected-serial address requires a known local PCI unit",
            ));
        }
        let local = local as u8;
        if local == destination {
            return Err(Error::new(
                ErrorKind::InvalidInput,
                "selected-serial destination cannot be the local PCI unit",
            ));
        }

        let _lane = self.programming_lane.lock().await;
        if self.programming_fault.load(Ordering::Acquire) {
            return Err(Error::other(
                "programming stream needs reconnect after an incomplete transaction",
            ));
        }
        let mut transaction = Transaction {
            fault: &self.programming_fault,
            complete: false,
        };
        let mut replies = self.packets.subscribe();
        let code = self.get_confirmation_code()?;
        let request = encode_serial_address(&selected.canonical, destination, true, code)
            .map_err(|error| Error::new(ErrorKind::InvalidInput, error.0))?;

        let result = tokio::time::timeout(REPLY_TIMEOUT, async {
            self.init_done
                .subscribe()
                .wait_for(|&done| done)
                .await
                .map_err(|_| Error::new(ErrorKind::BrokenPipe, "PCI initialization ended"))?;
            if !self.is_connected() {
                return Err(Error::new(ErrorKind::BrokenPipe, "PCI disconnected"));
            }
            self.flow
                .submit(request, Priority::Command, ResponseKind::Confirmation(code))
                .await
                .map_err(|_| Error::new(ErrorKind::BrokenPipe, "PCI writer ended"))??;

            let mut confirmed = false;
            let mut acceptance = None;
            let mut quiet_deadline = None;
            loop {
                let next = async {
                    match quiet_deadline {
                        Some(deadline) => tokio::time::timeout_at(deadline, replies.recv())
                            .await
                            .map_err(|_| {
                            Error::new(ErrorKind::TimedOut, "selected-serial quiet interval")
                        })?,
                        None => replies.recv().await,
                    }
                    .map_err(|_| Error::new(ErrorKind::BrokenPipe, "PCI response stream lost"))
                };
                match next.await {
                    Err(error)
                        if error.kind() == ErrorKind::TimedOut
                            && quiet_deadline.is_some()
                            && confirmed
                            && acceptance.is_some() =>
                    {
                        return Ok(acceptance.unwrap())
                    }
                    Err(error)
                        if error.kind() == ErrorKind::TimedOut && quiet_deadline.is_some() =>
                    {
                        return Err(Error::new(
                            ErrorKind::TimedOut,
                            "selected-serial address receipt timed out",
                        ))
                    }
                    Err(error) => return Err(error),
                    Ok(None) => {
                        return Err(Error::new(
                            ErrorKind::BrokenPipe,
                            "PCI response stream lost",
                        ))
                    }
                    Ok(Some(Packet::Confirmation { code: got, success })) if got == code => {
                        if confirmed {
                            return Err(Error::new(
                                ErrorKind::InvalidData,
                                "duplicate selected-serial confirmation",
                            ));
                        }
                        if !success {
                            if acceptance.is_some() {
                                return Err(Error::new(
                                    ErrorKind::InvalidData,
                                    "selected-serial receipt followed by rejection",
                                ));
                            }
                            return Err(Error::other(
                                "PCI rejected selected-serial address command",
                            ));
                        }
                        confirmed = true;
                        quiet_deadline = Some(Instant::now() + SERIAL_ADDRESS_QUIET);
                    }
                    Ok(Some(Packet::PointToPoint {
                        meta,
                        unit_address,
                        bridged,
                        hops,
                        cals,
                    })) if cals.iter().any(
                        |cal| matches!(cal, Cal::Reply { parameter: 0, data } if data.len() == 6),
                    ) =>
                    {
                        if !confirmed {
                            return Err(Error::new(
                                ErrorKind::InvalidData,
                                "selected-serial receipt preceded its confirmation",
                            ));
                        }
                        if acceptance.is_some() {
                            return Err(Error::new(
                                ErrorKind::InvalidData,
                                "multiple selected-serial receipts are ambiguous",
                            ));
                        }
                        if meta.source_address != Some(destination)
                            || unit_address != local
                            || bridged
                            || !hops.is_empty()
                            || cals.len() != 1
                        {
                            return Err(Error::new(
                                ErrorKind::InvalidData,
                                "selected-serial receipt route is ambiguous",
                            ));
                        }
                        let Cal::Reply { data, .. } = &cals[0] else {
                            unreachable!("matching selected-serial reply checked above")
                        };
                        if data[..4] != selected.packed {
                            return Err(Error::new(
                                ErrorKind::InvalidData,
                                "selected-serial receipt contains another serial",
                            ));
                        }
                        acceptance = Some(SelectedSerialAcceptance {
                            serial: selected.canonical.clone(),
                            destination,
                            local_unit: local,
                            opaque_tail: [data[4], data[5]],
                        });
                        quiet_deadline = Some(Instant::now() + SERIAL_ADDRESS_QUIET);
                    }
                    Ok(Some(Packet::PciError)) => {
                        if acceptance.is_some() {
                            return Err(Error::new(
                                ErrorKind::InvalidData,
                                "selected-serial receipt followed by PCI error",
                            ));
                        }
                        return Err(Error::other("PCI rejected selected-serial address command"));
                    }
                    Ok(Some(Packet::Invalid)) => {
                        return Err(Error::new(
                            ErrorKind::InvalidData,
                            "invalid PCI input during selected-serial transaction",
                        ))
                    }
                    Ok(Some(_)) => {}
                }
            }
        })
        .await
        .unwrap_or_else(|_| {
            Err(Error::new(
                ErrorKind::TimedOut,
                "selected-serial address transaction timed out",
            ))
        });

        {
            self.release_legacy_confirmation(code);
        }
        if result.is_ok()
            || result.as_ref().is_err_and(|error| {
                error.to_string() == "PCI rejected selected-serial address command"
            })
        {
            transaction.complete = true;
        }
        result
    }

    /// Send one validated selected-serial plan request exactly once on this
    /// shared PCI and retain bounded correlation evidence.
    ///
    /// The supplied serial, destination, checksum setting, and fixed
    /// confirmation code are re-encoded and must equal `expected_request`
    /// before a lane is taken or any I/O is attempted. The fixed code is
    /// reserved only when free and the exact supplied bytes are submitted
    /// once outside the retry table. After the write completes, a fixed
    /// two-second capture returns `receipt_matched=false` for missing,
    /// rejected, reordered, duplicate, or nonmatching address evidence;
    /// callers must decide movement through an independent inventory.
    ///
    /// A malformed or lost response stream is an error. Cancellation before
    /// the queued write starts prevents the write and releases the code. If a
    /// write started, cancellation or write uncertainty faults this client's
    /// programming lane and quarantines the code; discard the client. A
    /// completed capture with no confirmation also quarantines the code so a
    /// late acknowledgement cannot satisfy a later command.
    pub async fn send_selected_serial_plan_once(
        &self,
        serial: &str,
        destination: u8,
        command_checksum: bool,
        confirmation: u8,
        expected_request: &[u8],
    ) -> std::result::Result<SelectedSerialApplyEvidence, SelectedSerialApplyError> {
        let selected = parse_native_serial(serial)
            .map_err(|error| Error::new(ErrorKind::InvalidInput, error.0))
            .map_err(|error| {
                SelectedSerialApplyError::new(error, expected_request, false, false, false, false)
            })?;
        if !selected.known || !(2..=254).contains(&destination) {
            return Err(SelectedSerialApplyError::new(
                Error::new(
                    ErrorKind::InvalidInput,
                    "selected-serial address requires a known serial and destination in 2..254",
                ),
                expected_request,
                false,
                false,
                false,
                false,
            ));
        }
        let encoded = encode_serial_address(
            &selected.canonical,
            destination,
            command_checksum,
            confirmation,
        )
        .map_err(|error| Error::new(ErrorKind::InvalidInput, error.0))
        .map_err(|error| {
            SelectedSerialApplyError::new(error, expected_request, false, false, false, false)
        })?;
        if encoded != expected_request {
            return Err(SelectedSerialApplyError::new(
                Error::new(
                    ErrorKind::InvalidInput,
                    "selected-serial request differs from the validated plan",
                ),
                expected_request,
                false,
                false,
                false,
                false,
            ));
        }
        let local = self.local_unit.load(Ordering::Acquire);
        if local > u8::MAX.into() {
            return Err(SelectedSerialApplyError::new(
                Error::new(
                    ErrorKind::InvalidInput,
                    "selected-serial address requires a known local PCI unit",
                ),
                expected_request,
                false,
                false,
                false,
                false,
            ));
        }
        let local = local as u8;
        if local == destination {
            return Err(SelectedSerialApplyError::new(
                Error::new(
                    ErrorKind::InvalidInput,
                    "selected-serial destination cannot be the local PCI unit",
                ),
                expected_request,
                false,
                false,
                false,
                false,
            ));
        }

        let _lane = self.programming_lane.lock().await;
        if self.programming_fault.load(Ordering::Acquire) {
            return Err(SelectedSerialApplyError::new(
                Error::other("programming stream needs reconnect after an incomplete transaction"),
                expected_request,
                false,
                false,
                false,
                false,
            ));
        }
        let mut replies = self.packets.subscribe();
        let progress = Arc::new(flow::WriteProgress::default());
        let mut write_transaction = OneShotWriteTransaction {
            client: self,
            progress: progress.clone(),
            complete: false,
        };
        let (code, allocation_id) =
            self.allocate_exact_confirmation(confirmation)
                .map_err(|error| {
                    SelectedSerialApplyError::new(
                        error,
                        expected_request,
                        false,
                        false,
                        false,
                        false,
                    )
                })?;
        let mut allocation = ConfirmationAllocation {
            client: self,
            code,
            id: allocation_id,
            retained: false,
            progress: progress.clone(),
        };

        self.init_done
            .subscribe()
            .wait_for(|&done| done)
            .await
            .map_err(|_| Error::new(ErrorKind::BrokenPipe, "PCI initialization ended"))
            .map_err(|error| {
                SelectedSerialApplyError::new(error, expected_request, false, false, false, false)
            })?;
        if !self.is_connected() {
            return Err(SelectedSerialApplyError::new(
                Error::new(ErrorKind::BrokenPipe, "PCI disconnected"),
                expected_request,
                false,
                false,
                false,
                false,
            ));
        }
        let mut write = self.flow.submit_tracked(
            expected_request.to_vec(),
            Priority::Command,
            ResponseKind::Confirmation(code),
            progress.clone(),
        );
        match tokio::time::timeout(REPLY_TIMEOUT, &mut write).await {
            Ok(Ok(Ok(()))) => {
                allocation.retain_once();
                write_transaction.complete = true;
            }
            Ok(Ok(Err(error))) => {
                return Err(SelectedSerialApplyError::new(
                    error,
                    expected_request,
                    progress.has_started(),
                    false,
                    false,
                    false,
                ));
            }
            Ok(Err(_)) => {
                return Err(SelectedSerialApplyError::new(
                    Error::new(ErrorKind::BrokenPipe, "PCI writer ended"),
                    expected_request,
                    progress.has_started(),
                    false,
                    false,
                    false,
                ));
            }
            Err(_) if progress.cancel_before_start() => {
                return Err(SelectedSerialApplyError::new(
                    Error::new(
                        ErrorKind::TimedOut,
                        "selected-serial write timed out before starting",
                    ),
                    expected_request,
                    false,
                    false,
                    false,
                    false,
                ));
            }
            Err(_) => {
                return Err(SelectedSerialApplyError::new(
                    Error::new(
                        ErrorKind::TimedOut,
                        "selected-serial write completion is uncertain; discard PCI client",
                    ),
                    expected_request,
                    true,
                    false,
                    false,
                    false,
                ));
            }
        }
        drop(allocation);
        let _sent = SentConfirmation {
            client: self,
            code,
            allocation_id,
        };
        let mut transaction = SelectedSerialCaptureTransaction {
            client: self,
            complete: false,
        };

        let mut event_index = 0usize;
        let mut confirmation_count = 0usize;
        let mut confirmation_positive = false;
        let mut confirmation_at = None;
        let mut receipt_count = 0usize;
        let mut exact_receipt_count = 0usize;
        let mut exact_receipt_at = None;
        let mut contradictory = false;
        let capture: std::result::Result<
            std::result::Result<(), Error>,
            tokio::time::error::Elapsed,
        > = tokio::time::timeout(SERIAL_ADDRESS_QUIET, async {
            loop {
                match replies.recv().await {
                    Ok(Some(Packet::Confirmation { code: got, success })) if got == code => {
                        confirmation_count += 1;
                        confirmation_positive |= success;
                        confirmation_at.get_or_insert(event_index);
                    }
                    Ok(Some(Packet::PointToPoint {
                        meta,
                        unit_address,
                        bridged,
                        hops,
                        cals,
                    })) if cals.iter().any(
                        |cal| matches!(cal, Cal::Reply { parameter: 0, data } if data.len() == 6),
                    ) =>
                    {
                        receipt_count += 1;
                        let exact_route = meta.source_address == Some(destination)
                            && unit_address == local
                            && !bridged
                            && hops.is_empty()
                            && cals.len() == 1;
                        let exact_serial = matches!(
                            cals.first(),
                            Some(Cal::Reply { parameter: 0, data })
                                if data.len() == 6 && data[..4] == selected.packed
                        );
                        if exact_route && exact_serial {
                            exact_receipt_count += 1;
                            exact_receipt_at.get_or_insert(event_index);
                        } else {
                            contradictory = true;
                        }
                    }
                    Ok(Some(Packet::BareCal(Cal::Reply { parameter: 0, data })))
                        if data.len() == 6 =>
                    {
                        receipt_count += 1;
                        contradictory = true;
                    }
                    Ok(Some(Packet::PciError)) => contradictory = true,
                    Ok(Some(Packet::Invalid)) => {
                        return Err(Error::new(
                            ErrorKind::InvalidData,
                            "invalid PCI input during selected-serial capture",
                        ));
                    }
                    Ok(Some(_)) => {}
                    Ok(None) | Err(_) => {
                        return Err(Error::new(
                            ErrorKind::BrokenPipe,
                            "PCI response stream lost during selected-serial capture",
                        ));
                    }
                }
                event_index = event_index.saturating_add(1);
            }
        })
        .await;
        if let Ok(Err(error)) = capture {
            return Err(SelectedSerialApplyError::new(
                error,
                expected_request,
                true,
                true,
                confirmation_count != 0,
                receipt_count != 0,
            ));
        }
        let receipt_after_confirmation = matches!(
            (confirmation_at, exact_receipt_at),
            (Some(confirmation), Some(receipt)) if confirmation < receipt
        );
        let receipt_matched = confirmation_count == 1
            && confirmation_positive
            && receipt_count == 1
            && exact_receipt_count == 1
            && receipt_after_confirmation
            && !contradictory;
        transaction.complete = true;
        Ok(SelectedSerialApplyEvidence {
            request: expected_request.to_vec(),
            send_completed: true,
            receipt_matched,
            confirmation_observed: confirmation_count != 0,
            receipt_observed: receipt_count != 0,
        })
    }

    /// Send one native standard dynamic-label cache clear exactly once.
    ///
    /// `None` clears every key; `Some(key)` clears one key in `1..=8`. Native
    /// completion is the correlated PCI confirmation only; native behavior
    /// treats both confirmation forms as completion without exposing their
    /// polarity. There is no unit acknowledgement or cache readback, so
    /// success proves neither delivery, erasure, nor persistence on the
    /// target unit.
    pub async fn clear_dynamic_label_cache(&self, unit: u8, key: Option<u8>) -> Result<()> {
        // Validate before taking a lane or attempting any I/O.
        let request = label_clear::request(key)
            .map_err(|error| Error::new(ErrorKind::InvalidInput, error.0))?;
        let _lane = self.programming_lane.lock().await;
        if self.programming_fault.load(Ordering::Acquire) {
            return Err(Error::other(
                "programming stream needs reconnect after an incomplete transaction",
            ));
        }
        let mut transaction = Transaction {
            fault: &self.programming_fault,
            complete: false,
        };
        let mut replies = self.packets.subscribe();
        if !self.is_connected() {
            return Err(Error::new(ErrorKind::BrokenPipe, "PCI disconnected"));
        }
        let packet = Packet::PointToPoint {
            meta: Meta::new(true, 1),
            unit_address: unit,
            bridged: false,
            hops: vec![],
            cals: vec![request],
        };
        let confirmation = self.send_guarded_once(&packet).await?;
        let code = confirmation.code;
        let result = tokio::time::timeout(REPLY_TIMEOUT, async {
            loop {
                match replies.recv().await {
                    Ok(Some(Packet::Confirmation { code: got, .. })) if got == code => {
                        return Ok(());
                    }
                    Ok(Some(_)) => {}
                    Ok(None) | Err(_) => {
                        return Err(Error::new(
                            ErrorKind::BrokenPipe,
                            "PCI response stream lost",
                        ));
                    }
                }
            }
        })
        .await
        .unwrap_or_else(|_| {
            Err(Error::new(
                ErrorKind::TimedOut,
                "dynamic-label clear confirmation timed out",
            ))
        });
        if result.is_ok() {
            // Native LABEL CLEAR records correlation only. Both `.` and `#`
            // complete the transaction, with no delivery polarity exposed.
            transaction.complete = true;
        }
        result
    }

    /// Send the native eDLT dynamic-label clear control exactly once.
    ///
    /// The unit ACK proves only that the programming control was accepted;
    /// C-Bus exposes no readback for the erased dynamic-label cache.
    pub async fn clear_edlt_dynamic_labels(&self, unit: u8) -> Result<()> {
        self.edlt_oem_control(unit, [0xc1, 0xea], "eDLT label clear")
            .await
    }

    /// Send the native C-Gate `CBusEdlt.FactoryDefault` control exactly once.
    ///
    /// The source-correlated unit ACK proves acceptance of the OEM control.
    /// It does not prove the post-reboot defaults, retained address, rendered
    /// state, or power-cycle persistence; callers must report those separately.
    pub async fn factory_default_edlt(&self, unit: u8) -> Result<()> {
        self.edlt_oem_control(unit, [0xb2, 0xb2], "eDLT factory default")
            .await
    }

    async fn edlt_oem_control(
        &self,
        unit: u8,
        control: [u8; 2],
        operation: &'static str,
    ) -> Result<()> {
        if unit == 0 || unit == 255 {
            return Err(Error::new(
                ErrorKind::InvalidInput,
                format!("{operation} requires a unit address in 1..254"),
            ));
        }
        let _lane = self.programming_lane.lock().await;
        if self.programming_fault.load(Ordering::Acquire) {
            return Err(Error::other(
                "programming stream needs reconnect after an incomplete transaction",
            ));
        }
        let mut transaction = Transaction {
            fault: &self.programming_fault,
            complete: false,
        };
        let mut replies = self.packets.subscribe();
        let mut bytes = cbus_protocol::packet::programming_request(
            unit,
            &Cal::Write {
                parameter: 0xff,
                data: vec![0x43, control[0], control[1]],
            },
        )
        .map_err(|error| Error::new(ErrorKind::InvalidInput, error.0))?;
        let code = self.get_confirmation_code()?;
        bytes.insert(bytes.len() - 1, code);

        let result = tokio::time::timeout(REPLY_TIMEOUT, async {
            self.init_done
                .subscribe()
                .wait_for(|&done| done)
                .await
                .map_err(|_| Error::new(ErrorKind::BrokenPipe, "PCI initialization ended"))?;
            if !self.is_connected() {
                return Err(Error::new(ErrorKind::BrokenPipe, "PCI disconnected"));
            }
            self.flow
                .submit(bytes, Priority::Command, ResponseKind::Confirmation(code))
                .await
                .map_err(|_| Error::new(ErrorKind::BrokenPipe, "PCI writer ended"))??;
            let mut confirmed = None;
            let mut accepted = None;
            loop {
                match replies.recv().await {
                    Ok(Some(Packet::Confirmation { code: got, success })) if got == code => {
                        confirmed = Some(success)
                    }
                    Ok(Some(Packet::PointToPoint { meta, cals, .. }))
                        if meta.source_address == Some(unit) =>
                    {
                        for cal in cals {
                            match cal {
                                Cal::Ack {
                                    parameter: 0xff,
                                    data,
                                } if data == [0x43] => accepted = Some(true),
                                Cal::Nak {
                                    parameter: 0xff,
                                    data,
                                } if data.starts_with(&[0x43]) => accepted = Some(false),
                                _ => {}
                            }
                        }
                    }
                    Ok(Some(Packet::PciError)) => {
                        return Err(Error::other(format!("PCI rejected {operation}")));
                    }
                    Ok(Some(_)) => {}
                    Ok(None) | Err(_) => {
                        return Err(Error::new(
                            ErrorKind::BrokenPipe,
                            "PCI response stream lost",
                        ));
                    }
                }
                if confirmed == Some(false) {
                    return Err(Error::other(format!("PCI rejected {operation}")));
                }
                if accepted == Some(false) {
                    return Err(Error::other(format!("unit rejected {operation}")));
                }
                if confirmed == Some(true) && accepted == Some(true) {
                    return Ok(());
                }
            }
        })
        .await
        .unwrap_or_else(|_| {
            Err(Error::new(
                ErrorKind::TimedOut,
                format!("{operation} timed out"),
            ))
        });

        {
            self.release_legacy_confirmation(code);
        }
        let pci_rejected = format!("PCI rejected {operation}");
        let unit_rejected = format!("unit rejected {operation}");
        if result.is_ok()
            || result.as_ref().is_err_and(|error| {
                let message = error.to_string();
                message == pci_rejected || message == unit_rejected
            })
        {
            transaction.complete = true;
        }
        result
    }

    /// Supply the configured local-interface address used to correlate bare
    /// CAL replies. A conflicting hint is rejected; this does not itself
    /// establish physical presence or identity.
    pub fn set_local_unit_hint(&self, unit: u8) -> Result<()> {
        match self.local_unit.compare_exchange(
            256,
            u16::from(unit),
            Ordering::AcqRel,
            Ordering::Acquire,
        ) {
            Ok(_) => Ok(()),
            Err(existing) if existing == u16::from(unit) => Ok(()),
            Err(_) => Err(Error::new(
                ErrorKind::InvalidInput,
                "local-interface address conflicts with the active PCI",
            )),
        }
    }

    /// Discover and cache the attached PCI's own C-Bus unit address through
    /// the read-only BASIC `@1A2001` query. Local IDENTIFY replies are bare
    /// CALs, so callers that inventory the full network must establish this
    /// address before correlating them.
    pub async fn discover_local_unit(&self) -> Result<u8> {
        let cached = self.local_unit.load(Ordering::Acquire);
        if cached <= u8::MAX.into() {
            return Ok(cached as u8);
        }
        let _lane = self.programming_lane.lock().await;
        let cached = self.local_unit.load(Ordering::Acquire);
        if cached <= u8::MAX.into() {
            return Ok(cached as u8);
        }
        if self.programming_fault.load(Ordering::Acquire) {
            return Err(Error::other(
                "programming stream needs reconnect after an incomplete transaction",
            ));
        }
        let mut transaction = Transaction {
            fault: &self.programming_fault,
            complete: false,
        };
        let mut replies = self.packets.subscribe();
        self.init_done
            .subscribe()
            .wait_for(|&done| done)
            .await
            .map_err(|_| Error::new(ErrorKind::BrokenPipe, "PCI initialization ended"))?;
        if !self.is_connected() {
            return Err(Error::new(ErrorKind::BrokenPipe, "PCI disconnected"));
        }
        self.flow
            .submit(
                b"@1A2001\r".to_vec(),
                Priority::Command,
                ResponseKind::Silent,
            )
            .await
            .map_err(|_| Error::new(ErrorKind::BrokenPipe, "PCI writer ended"))??;
        let unit = tokio::time::timeout(REPLY_TIMEOUT, async {
            loop {
                match replies.recv().await {
                    Ok(Some(Packet::BareCal(Cal::Reply {
                        parameter: 0x20,
                        data,
                    }))) => {
                        if data.len() != 1 {
                            return Err(Error::new(
                                ErrorKind::InvalidData,
                                "BASIC local-address reply must contain exactly one byte",
                            ));
                        }
                        return Ok(data[0]);
                    }
                    Ok(Some(Packet::PointToPoint { meta, cals, .. }))
                        if meta.source_address.is_none()
                            && cals.len() == 1
                            && matches!(
                                cals.first(),
                                Some(Cal::Reply {
                                    parameter: 0x20,
                                    ..
                                })
                            ) =>
                    {
                        let Cal::Reply { data, .. } = &cals[0] else {
                            unreachable!("reply checked above")
                        };
                        if data.len() != 1 {
                            return Err(Error::new(
                                ErrorKind::InvalidData,
                                "BASIC local-address reply must contain exactly one byte",
                            ));
                        }
                        return Ok(data[0]);
                    }
                    Ok(Some(Packet::PciError)) => {
                        return Err(Error::other("PCI rejected local-address discovery"))
                    }
                    Ok(Some(_)) => {}
                    Ok(None) | Err(_) => {
                        return Err(Error::new(
                            ErrorKind::BrokenPipe,
                            "PCI response stream lost",
                        ))
                    }
                }
            }
        })
        .await
        .unwrap_or_else(|_| {
            Err(Error::new(
                ErrorKind::TimedOut,
                "local-address discovery timed out",
            ))
        })?;
        self.local_unit.store(u16::from(unit), Ordering::Release);
        transaction.complete = true;
        Ok(unit)
    }

    /// Whether the reader has observed transport loss.
    pub fn is_connected(&self) -> bool {
        !self.disconnected.load(Ordering::Acquire)
    }

    /// Send a command and wait for its PCI delivery confirmation. A negative
    /// confirmation is an error, not a successful state transition.
    pub async fn send_confirmed(&self, packet: &Packet) -> Result<()> {
        let mut replies = self.packets.subscribe();
        if !self.is_connected() {
            return Err(Error::new(ErrorKind::BrokenPipe, "PCI disconnected"));
        }
        let confirmation = self.send_guarded(packet).await?;
        let code = confirmation.code;
        let result = tokio::time::timeout(Duration::from_secs(12), async {
            loop {
                match replies.recv().await {
                    Ok(Some(Packet::Confirmation { code: got, success })) if got == code => {
                        return if success {
                            Ok(())
                        } else {
                            Err(Error::other("PCI rejected command"))
                        };
                    }
                    Ok(Some(_)) => {}
                    Ok(None) | Err(_) => {
                        return Err(Error::new(
                            ErrorKind::BrokenPipe,
                            "PCI response stream lost",
                        ))
                    }
                }
            }
        })
        .await
        .unwrap_or_else(|_| {
            Err(Error::new(
                ErrorKind::TimedOut,
                "PCI delivery confirmation timed out",
            ))
        });
        result
    }

    /// Send exactly once and wait for its PCI delivery confirmation.
    ///
    /// Unlike [`Self::send_confirmed`], this does not register the frame for
    /// automatic retransmission. An absent confirmation is outcome-uncertain;
    /// the confirmation code stays quarantined so a late reply cannot satisfy
    /// another command.
    pub async fn send_confirmed_once(&self, packet: &Packet) -> Result<()> {
        let mut replies = self.packets.subscribe();
        if !self.is_connected() {
            return Err(Error::new(ErrorKind::BrokenPipe, "PCI disconnected"));
        }
        let confirmation = self.send_guarded_once(packet).await?;
        let code = confirmation.code;
        tokio::time::timeout(Duration::from_secs(12), async {
            loop {
                match replies.recv().await {
                    Ok(Some(Packet::Confirmation { code: got, success })) if got == code => {
                        return if success {
                            Ok(())
                        } else {
                            Err(Error::other("PCI rejected command"))
                        };
                    }
                    Ok(Some(_)) => {}
                    Ok(None) | Err(_) => {
                        return Err(Error::new(
                            ErrorKind::BrokenPipe,
                            "PCI response stream lost",
                        ));
                    }
                }
            }
        })
        .await
        .unwrap_or_else(|_| {
            Err(Error::new(
                ErrorKind::TimedOut,
                "PCI delivery confirmation timed out",
            ))
        })
    }

    async fn programming_exchange(
        &self,
        unit: u8,
        request: Cal,
        parameter: u8,
        count: usize,
        ack: Option<u8>,
        route: ProgrammingRoute,
    ) -> Result<Vec<u8>> {
        let mut replies = self.packets.subscribe();
        let bytes = if !matches!(route, ProgrammingRoute::Oem) {
            let packet = Packet::PointToPoint {
                meta: Meta::new(matches!(route, ProgrammingRoute::DirectChecksummed), 1),
                unit_address: unit,
                bridged: false,
                hops: vec![],
                cals: vec![request],
            };
            let mut bytes = vec![b'\\'];
            bytes.extend(
                packet
                    .encode_packet()
                    .map_err(|e| Error::new(ErrorKind::InvalidInput, e.0))?,
            );
            bytes.push(b'\r');
            bytes
        } else {
            cbus_protocol::packet::programming_request(unit, &request)
                .map_err(|e| Error::new(ErrorKind::InvalidInput, e.0))?
        };
        tokio::time::timeout(REPLY_TIMEOUT, async {
            self.init_done
                .subscribe()
                .wait_for(|&done| done)
                .await
                .map_err(|_| Error::new(ErrorKind::BrokenPipe, "PCI initialization ended"))?;
            if !self.is_connected() {
                return Err(Error::new(ErrorKind::BrokenPipe, "PCI disconnected"));
            }
            self.flow
                .submit(bytes, Priority::Command, ResponseKind::Silent)
                .await
                .map_err(|_| Error::new(ErrorKind::BrokenPipe, "PCI writer ended"))??;
            let mut result = Vec::with_capacity(count);
            loop {
                let cals = match replies.recv().await {
                    Ok(Some(Packet::PointToPoint { meta, cals, .. }))
                        if meta.source_address == Some(unit) =>
                    {
                        cals
                    }
                    Ok(Some(Packet::PointToPoint { meta, cals, .. }))
                        if meta.source_address.is_none()
                            && self.local_unit.load(Ordering::Acquire) == u16::from(unit) =>
                    {
                        cals
                    }
                    Ok(Some(Packet::BareCal(cal)))
                        if self.local_unit.load(Ordering::Acquire) == u16::from(unit) =>
                    {
                        vec![cal]
                    }
                    Ok(Some(_)) => continue,
                    Ok(None) | Err(_) => {
                        return Err(Error::new(
                            ErrorKind::BrokenPipe,
                            "PCI response stream lost",
                        ))
                    }
                };
                for cal in cals {
                    match cal {
                        Cal::Ack { parameter: p, data } if p == parameter && ack.is_some() => {
                            if data == [ack.unwrap()] {
                                return Ok(Vec::new());
                            }
                            // A different acknowledgement tag belongs to a
                            // separate programming operation. Native command
                            // handlers correlate both parameter and tag; only
                            // the matching 0x3B form below is a rejection.
                        }
                        Cal::Nak { parameter: p, data }
                            if p == parameter && ack.is_some() && data.first().copied() == ack =>
                        {
                            return Err(Error::other("unit rejected programming selector"));
                        }
                        Cal::Reply { parameter: p, data } if p == parameter && ack.is_none() => {
                            if count == 0 {
                                return Ok(data);
                            }
                            result.extend(data);
                            if result.len() > count {
                                return Err(Error::new(
                                    ErrorKind::InvalidData,
                                    "unit returned excess memory bytes",
                                ));
                            }
                            if result.len() == count {
                                return Ok(result);
                            }
                        }
                        _ => {}
                    }
                }
            }
        })
        .await
        .unwrap_or_else(|_| {
            Err(Error::new(
                ErrorKind::TimedOut,
                "unit programming reply timed out",
            ))
        })
    }

    /// Send one native extended CAL command and wait for its source-correlated
    /// status or NAK. These commands receive a unit response and therefore do
    /// not carry a separate PCI confirmation character.
    async fn programming_extended_exchange(
        &self,
        unit: u8,
        request: Cal,
        group: u8,
        operation: u8,
        priority_class: u8,
    ) -> Result<ExtendedOutcome> {
        let mut replies = self.packets.subscribe();
        let packet = Packet::PointToPoint {
            meta: Meta::new(false, priority_class),
            unit_address: unit,
            bridged: false,
            hops: vec![],
            cals: vec![request],
        };
        let mut bytes = vec![b'\\'];
        bytes.extend(
            packet
                .encode_packet()
                .map_err(|error| Error::new(ErrorKind::InvalidInput, error.0))?,
        );
        bytes.push(b'\r');
        tokio::time::timeout(REPLY_TIMEOUT, async {
            self.init_done
                .subscribe()
                .wait_for(|&done| done)
                .await
                .map_err(|_| Error::new(ErrorKind::BrokenPipe, "PCI initialization ended"))?;
            if !self.is_connected() {
                return Err(Error::new(ErrorKind::BrokenPipe, "PCI disconnected"));
            }
            self.flow
                .submit(bytes, Priority::Command, ResponseKind::Silent)
                .await
                .map_err(|_| Error::new(ErrorKind::BrokenPipe, "PCI writer ended"))??;
            loop {
                let (cals, response_wire) = match replies.recv().await {
                    Ok(Some(Packet::PointToPoint {
                        meta,
                        unit_address,
                        bridged,
                        hops,
                        cals,
                    })) if meta.source_address == Some(unit) => {
                        let response_wire = Packet::PointToPoint {
                            meta,
                            unit_address,
                            bridged,
                            hops,
                            cals: cals.clone(),
                        }
                        .encode()
                        .map_err(|error| Error::new(ErrorKind::InvalidData, error.0))?;
                        (cals, response_wire)
                    }
                    Ok(Some(Packet::PointToPoint {
                        meta,
                        unit_address,
                        bridged,
                        hops,
                        cals,
                    })) if meta.source_address.is_none()
                        && self.local_unit.load(Ordering::Acquire) == u16::from(unit) =>
                    {
                        let response_wire = Packet::PointToPoint {
                            meta,
                            unit_address,
                            bridged,
                            hops,
                            cals: cals.clone(),
                        }
                        .encode()
                        .map_err(|error| Error::new(ErrorKind::InvalidData, error.0))?;
                        (cals, response_wire)
                    }
                    Ok(Some(Packet::BareCal(cal)))
                        if self.local_unit.load(Ordering::Acquire) == u16::from(unit) =>
                    {
                        let response_wire = cal.encode();
                        (vec![cal], response_wire)
                    }
                    Ok(Some(_)) => continue,
                    Ok(None) | Err(_) => {
                        return Err(Error::new(
                            ErrorKind::BrokenPipe,
                            "PCI response stream lost",
                        ));
                    }
                };
                for cal in cals {
                    match cal {
                        Cal::ExtendedReply {
                            group: got_group,
                            operation: got_operation,
                            status,
                            data,
                        } if (got_group == group || (group == 0xda && got_group == 0))
                            && got_operation == operation =>
                        {
                            return Ok(ExtendedOutcome::Reply {
                                status,
                                data,
                                response_wire,
                            });
                        }
                        // Native aQ accepts any 0x3B response from the
                        // correlated unit as the command's negative ACK.
                        Cal::Nak { .. } | Cal::ReaddressNak => {
                            return Ok(ExtendedOutcome::Nak { response_wire });
                        }
                        _ => {}
                    }
                }
            }
        })
        .await
        .unwrap_or_else(|_| {
            Err(Error::new(
                ErrorKind::TimedOut,
                "extended CAL reply timed out",
            ))
        })
    }

    /// Send a DALI extended-CAL command through the shared PCI exactly once
    /// per exchange. AUTO performs one execute followed by at most ten polls,
    /// matching C-Gate 3.4's bounded sequence. It never retries a lost or
    /// uncertain write. Any incomplete exchange faults the programming lane
    /// until the caller installs a fresh [`PciClient`].
    pub async fn dali_command(
        &self,
        unit: u8,
        mode: DaliCalMode,
        device_type: u8,
        operation: u8,
        payload: &[u8],
    ) -> Result<DaliCommandResult> {
        if unit == 0 || unit == 255 {
            return Err(Error::new(
                ErrorKind::InvalidInput,
                "DALI gateway address must be in 1..254",
            ));
        }
        // Build every possible first request before taking the lane. This
        // makes malformed input a definite pre-I/O refusal.
        let first_mode = if mode == DaliCalMode::Auto {
            DaliCalMode::Execute
        } else {
            mode
        };
        let first_request = first_mode
            .request(device_type, operation, payload)
            .map_err(|error| Error::new(ErrorKind::InvalidInput, error.0))?;
        let _lane = self.programming_lane.lock().await;
        if self.programming_fault.load(Ordering::Acquire) {
            return Err(Error::other(
                "programming stream needs reconnect after an incomplete transaction",
            ));
        }
        let mut transaction = Transaction {
            fault: &self.programming_fault,
            complete: false,
        };
        let mut exchanges = Vec::new();
        let mut next = Some((first_mode, first_request));
        let mut polls = 0usize;
        while let Some((sent_mode, request)) = next.take() {
            let request_wire = format!("\\06{unit:02X}00{}", hex::encode_upper(request.encode()));
            let outcome = self
                .programming_extended_exchange(unit, request, device_type, operation, 0)
                .await?;
            let (status, data, response_wire, nak) = match outcome {
                ExtendedOutcome::Reply {
                    status,
                    data,
                    response_wire,
                } => (status, data, response_wire, false),
                ExtendedOutcome::Nak { response_wire } => (0xff, Vec::new(), response_wire, true),
            };
            exchanges.push(DaliExchange {
                mode: sent_mode,
                request_wire,
                response_wire,
                status,
                data,
                nak,
            });
            if mode == DaliCalMode::Auto && !nak && matches!(status, 1 | 2) && polls < 10 {
                polls += 1;
                tokio::time::sleep(Duration::from_millis(1500)).await;
                let poll = DaliCalMode::Poll
                    .request(device_type, operation, &[])
                    .expect("payload-free DALI poll is always encodable");
                next = Some((DaliCalMode::Poll, poll));
            }
        }
        transaction.complete = true;
        Ok(DaliCommandResult { exchanges })
    }

    /// Commit volatile programming changes in a C-Bus 3 unit to NVM using
    /// native C-Gate's group-0 operation-4 EXECUTE/POLL sequence.
    pub async fn save_to_nvm(&self, unit: u8) -> Result<()> {
        let _lane = self.programming_lane.lock().await;
        if self.programming_fault.load(Ordering::Acquire) {
            return Err(Error::other(
                "programming stream needs reconnect after an incomplete transaction",
            ));
        }
        let mut transaction = Transaction {
            fault: &self.programming_fault,
            complete: false,
        };
        let execute = self
            .programming_extended_exchange(
                unit,
                Cal::Execute {
                    group: 0,
                    operation: 4,
                    data: vec![],
                },
                0,
                4,
                1,
            )
            .await?;
        match execute {
            ExtendedOutcome::Reply { status: 0, .. } => {
                transaction.complete = true;
                return Ok(());
            }
            ExtendedOutcome::Reply { status: 1, .. } => {}
            ExtendedOutcome::Reply { status: 2, .. } => {
                transaction.complete = true;
                return Err(Error::other("C-Bus 3 unit is busy saving to NVM"));
            }
            ExtendedOutcome::Reply { status, .. } => {
                transaction.complete = true;
                return Err(Error::other(format!(
                    "Save-to-NVM EXECUTE returned status 0x{status:02X}"
                )));
            }
            ExtendedOutcome::Nak { .. } => {
                transaction.complete = true;
                return Err(Error::other("unit rejected Save-to-NVM EXECUTE"));
            }
        }

        let polled = tokio::time::timeout(NVM_POLL_TIMEOUT, async {
            loop {
                let outcome = self
                    .programming_extended_exchange(
                        unit,
                        Cal::Poll {
                            group: 0,
                            operation: 4,
                        },
                        0,
                        4,
                        1,
                    )
                    .await?;
                match outcome {
                    ExtendedOutcome::Reply { status: 1, .. } => {
                        tokio::time::sleep(NVM_POLL_INTERVAL).await;
                    }
                    other => return Ok(other),
                }
            }
        })
        .await;
        let outcome = match polled {
            Ok(Ok(outcome)) => outcome,
            Ok(Err(error)) => return Err(error),
            Err(_) => {
                return Err(Error::new(
                    ErrorKind::TimedOut,
                    "Save-to-NVM polling timed out",
                ));
            }
        };
        transaction.complete = true;
        match outcome {
            ExtendedOutcome::Reply { status: 0, .. } => Ok(()),
            ExtendedOutcome::Reply { status, .. } => Err(Error::other(format!(
                "Save-to-NVM POLL returned status 0x{status:02X}"
            ))),
            ExtendedOutcome::Nak { .. } => Err(Error::other("unit rejected Save-to-NVM POLL")),
        }
    }

    /// Read a bounded range of OEM physical memory. Each block explicitly
    /// selects its address; the only WRITE is the volatile 0x41 selector.
    /// Logical unit-spec addresses >=256 map to physical address = logical-256.
    pub async fn read_memory(&self, unit: u8, address: u32, length: usize) -> Result<Vec<u8>> {
        if length == 0 || length > 65536 || address.checked_add(length as u32).is_none() {
            return Err(Error::new(
                ErrorKind::InvalidInput,
                "memory read requires 1..65536 bytes without address overflow",
            ));
        }
        let _lane = self.programming_lane.lock().await;
        if self.programming_fault.load(Ordering::Acquire) {
            return Err(Error::other(
                "programming stream needs reconnect after an incomplete transaction",
            ));
        }
        let mut transaction = Transaction {
            fault: &self.programming_fault,
            complete: false,
        };
        let mut result = Vec::with_capacity(length);
        while result.len() < length {
            let offset = address + result.len() as u32;
            let mut selector = vec![0x41];
            selector
                .extend_from_slice(&offset.to_le_bytes()[..if offset <= 0xffff { 2 } else { 4 }]);
            self.programming_exchange(
                unit,
                Cal::Write {
                    parameter: 0,
                    data: selector,
                },
                0,
                0,
                Some(0x41),
                ProgrammingRoute::Oem,
            )
            .await?;
            let count = (length - result.len()).min(128) as u8;
            result.extend(
                self.programming_exchange(
                    unit,
                    Cal::Recall { param: 1, count },
                    1,
                    usize::from(count),
                    None,
                    ProgrammingRoute::Oem,
                )
                .await?,
            );
        }
        transaction.complete = true;
        Ok(result)
    }

    /// Read GOC programming memory through the native parameter-0xFF
    /// address selector. The dialect controls the exact C-Gate recall limit.
    pub async fn read_goc_memory(
        &self,
        unit: u8,
        address: u32,
        length: usize,
        dialect: GocProgramming,
    ) -> Result<Vec<u8>> {
        if length == 0
            || length > 65_536
            || address
                .checked_add(length as u32)
                .is_none_or(|end| end > 65_536)
        {
            return Err(Error::new(
                ErrorKind::InvalidInput,
                "GOC memory read requires 1..65536 bytes in the 16-bit address space",
            ));
        }
        let _lane = self.programming_lane.lock().await;
        if self.programming_fault.load(Ordering::Acquire) {
            return Err(Error::other(
                "programming stream needs reconnect after an incomplete transaction",
            ));
        }
        let mut transaction = Transaction {
            fault: &self.programming_fault,
            complete: false,
        };
        let result = self
            .read_goc_memory_inner(unit, address, length, dialect)
            .await?;
        transaction.complete = true;
        Ok(result)
    }

    async fn read_goc_memory_inner(
        &self,
        unit: u8,
        address: u32,
        length: usize,
        dialect: GocProgramming,
    ) -> Result<Vec<u8>> {
        let mut result = Vec::with_capacity(length);
        while result.len() < length {
            let offset = address + result.len() as u32;
            let offset = u16::try_from(offset)
                .map_err(|_| Error::new(ErrorKind::InvalidInput, "GOC address exceeds 16 bits"))?;
            self.programming_exchange(
                unit,
                Cal::Write {
                    parameter: u8::MAX,
                    data: vec![0x42, (offset >> 8) as u8, offset as u8],
                },
                u8::MAX,
                0,
                Some(0x42),
                ProgrammingRoute::DirectChecksummed,
            )
            .await?;
            let count = (length - result.len()).min(dialect.recall_limit()) as u8;
            result.extend(
                self.programming_exchange(
                    unit,
                    Cal::Recall {
                        param: u8::MAX,
                        count,
                    },
                    u8::MAX,
                    usize::from(count),
                    None,
                    ProgrammingRoute::DirectChecksummed,
                )
                .await?,
            );
        }
        Ok(result)
    }

    /// Recall one standard CAL programming parameter. This is the transport
    /// used by native PP for unit-spec logical addresses below 256; larger
    /// logical addresses use [`Self::read_memory`] with the 256-byte bias.
    pub async fn recall_parameter(
        &self,
        unit: u8,
        parameter: u8,
        length: usize,
    ) -> Result<Vec<u8>> {
        self.recall_parameter_with_route(
            unit,
            parameter,
            length,
            ProgrammingRoute::DirectChecksummed,
        )
        .await
    }

    async fn recall_parameter_with_route(
        &self,
        unit: u8,
        parameter: u8,
        length: usize,
        route: ProgrammingRoute,
    ) -> Result<Vec<u8>> {
        let count = u8::try_from(length).map_err(|_| {
            Error::new(
                ErrorKind::InvalidInput,
                "parameter recall requires 1..255 bytes",
            )
        })?;
        if count == 0 {
            return Err(Error::new(
                ErrorKind::InvalidInput,
                "parameter recall requires 1..255 bytes",
            ));
        }
        let _lane = self.programming_lane.lock().await;
        if self.programming_fault.load(Ordering::Acquire) {
            return Err(Error::other(
                "programming stream needs reconnect after an incomplete transaction",
            ));
        }
        let mut transaction = Transaction {
            fault: &self.programming_fault,
            complete: false,
        };
        let result = self
            .programming_exchange(
                unit,
                Cal::Recall {
                    param: parameter,
                    count,
                },
                parameter,
                length,
                None,
                route,
            )
            .await?;
        transaction.complete = true;
        Ok(result)
    }

    /// Read the native KEYGL5 static widget-group mapping.
    ///
    /// C-Gate reads parameter `0xFA` with an exact length of 44 over the
    /// captured OEM route and exposes all returned bytes as unsigned decimal
    /// values separated by commas.
    /// The underlying programming transaction correlates source, parameter,
    /// and total length; an incomplete exchange faults the programming lane
    /// until reconnect.
    pub async fn read_edlt_widget_groups(&self, unit: u8) -> Result<String> {
        let data = self
            .recall_parameter_with_route(
                unit,
                cbus_protocol::edlt_widget_groups::PARAMETER,
                cbus_protocol::edlt_widget_groups::LENGTH,
                ProgrammingRoute::Oem,
            )
            .await?;
        cbus_protocol::edlt_widget_groups::decode_reply(&data)
            .map_err(|error| Error::new(ErrorKind::InvalidData, error.0))
    }

    /// Read the native KEYGL5 extended-firmware string.
    ///
    /// This is parameter `0xFB` over the captured OEM route, exactly nine
    /// bytes, decoded up to the first NUL. It is distinct from the ordinary
    /// IDENTIFY2 version string. The request is exact-once and an incomplete
    /// exchange faults the programming lane until reconnect.
    pub async fn read_edlt_extended_firmware(&self, unit: u8) -> Result<String> {
        let data = self
            .recall_parameter_with_route(
                unit,
                cbus_protocol::edlt_sync_metadata::FIRMWARE_PARAMETER,
                cbus_protocol::edlt_sync_metadata::FIRMWARE_LENGTH,
                ProgrammingRoute::Oem,
            )
            .await?;
        cbus_protocol::edlt_sync_metadata::decode_firmware(&data)
            .map_err(|error| Error::new(ErrorKind::InvalidData, error.0))
    }

    /// Read the native KEYGL5 primary and secondary applications.
    ///
    /// Native C-Gate selects OEM memory address 16 once, then recalls exactly
    /// two bytes from parameter 1. [`Self::read_memory`] provides the required
    /// source, selector-tag, parameter, and total-length correlation and
    /// faults the programming lane after any incomplete phase.
    pub async fn read_edlt_applications(&self, unit: u8) -> Result<[u8; 2]> {
        let data = self
            .read_memory(
                unit,
                cbus_protocol::edlt_sync_metadata::APPLICATION_ADDRESS,
                cbus_protocol::edlt_sync_metadata::APPLICATION_LENGTH,
            )
            .await?;
        cbus_protocol::edlt_sync_metadata::decode_applications(&data)
            .map_err(|error| Error::new(ErrorKind::InvalidData, error.0))
    }

    /// Recall a bounded logical range using C-Gate's page-aware `0x1B`
    /// command. Requests never cross a 256-byte page and preserve the exact
    /// unchecksummed direct route used by native `paged` and `ncc` PP loads.
    pub async fn recall_paged_parameter(
        &self,
        unit: u8,
        address: u32,
        length: usize,
    ) -> Result<Vec<u8>> {
        if length == 0
            || length > 65_536
            || address
                .checked_add(length as u32)
                .is_none_or(|end| end > 65_536)
        {
            return Err(Error::new(
                ErrorKind::InvalidInput,
                "paged recall requires 1..65536 bytes within the 16-bit address space",
            ));
        }
        let _lane = self.programming_lane.lock().await;
        if self.programming_fault.load(Ordering::Acquire) {
            return Err(Error::other(
                "programming stream needs reconnect after an incomplete transaction",
            ));
        }
        let mut transaction = Transaction {
            fault: &self.programming_fault,
            complete: false,
        };
        let mut result = Vec::with_capacity(length);
        while result.len() < length {
            let logical = address + result.len() as u32;
            let page = (logical >> 8) as u8;
            let parameter = logical as u8;
            let page_remaining = 256 - usize::from(parameter);
            let count = (length - result.len()).min(page_remaining).min(255) as u8;
            result.extend(
                self.programming_exchange(
                    unit,
                    Cal::PagedRecall {
                        page,
                        param: parameter,
                        count,
                    },
                    parameter,
                    usize::from(count),
                    None,
                    ProgrammingRoute::DirectUnchecksummed,
                )
                .await?,
            );
        }
        transaction.complete = true;
        Ok(result)
    }

    /// Select each required programming page, issue native tagged STOREs,
    /// and verify the complete logical range through page-aware recalls.
    /// C-Gate limits these STORE groups to twelve bytes and unlocks the
    /// low-byte parameter after selecting a page when protection is `lock`.
    pub async fn store_paged_parameter_verified(
        &self,
        unit: u8,
        address: u32,
        data: &[u8],
        locked: bool,
    ) -> Result<()> {
        if data.is_empty()
            || data.len() > 65_536
            || address
                .checked_add(data.len() as u32)
                .is_none_or(|end| end > 65_536)
        {
            return Err(Error::new(
                ErrorKind::InvalidInput,
                "paged store requires 1..65536 bytes within the 16-bit address space",
            ));
        }
        let _lane = self.programming_lane.lock().await;
        if self.programming_fault.load(Ordering::Acquire) {
            return Err(Error::other(
                "programming stream needs reconnect after an incomplete transaction",
            ));
        }
        let mut transaction = Transaction {
            fault: &self.programming_fault,
            complete: false,
        };
        let mut written = 0usize;
        let mut selected_page = None;
        let mut transaction_tag = 0u8;
        while written < data.len() {
            let logical = address + written as u32;
            let page = (logical >> 8) as u8;
            let parameter = logical as u8;
            if selected_page != Some(page) {
                let reply = self
                    .programming_exchange(
                        unit,
                        Cal::SetPage { page },
                        page,
                        0,
                        None,
                        ProgrammingRoute::DirectUnchecksummed,
                    )
                    .await?;
                if !reply.is_empty() {
                    return Err(Error::new(
                        ErrorKind::InvalidData,
                        "page selection reply must not contain data",
                    ));
                }
                selected_page = Some(page);
            }
            let count = (data.len() - written)
                .min(12)
                .min(256 - usize::from(parameter));
            if locked {
                self.programming_unlock(unit, parameter).await?;
            }
            let mut tagged = Vec::with_capacity(count + 1);
            tagged.push(transaction_tag);
            tagged.extend_from_slice(&data[written..written + count]);
            self.programming_exchange(
                unit,
                Cal::Write {
                    parameter,
                    data: tagged,
                },
                parameter,
                0,
                Some(transaction_tag),
                ProgrammingRoute::DirectChecksummed,
            )
            .await?;
            written += count;
            transaction_tag = transaction_tag.wrapping_add(1);
        }

        let mut actual = Vec::with_capacity(data.len());
        while actual.len() < data.len() {
            let logical = address + actual.len() as u32;
            let page = (logical >> 8) as u8;
            let parameter = logical as u8;
            let count = (data.len() - actual.len())
                .min(256 - usize::from(parameter))
                .min(255) as u8;
            actual.extend(
                self.programming_exchange(
                    unit,
                    Cal::PagedRecall {
                        page,
                        param: parameter,
                        count,
                    },
                    parameter,
                    usize::from(count),
                    None,
                    ProgrammingRoute::DirectUnchecksummed,
                )
                .await?,
            );
        }
        if actual != data {
            return Err(Error::other("paged parameter readback did not match STORE"));
        }
        transaction.complete = true;
        Ok(())
    }

    async fn programming_unlock(&self, unit: u8, parameter: u8) -> Result<u8> {
        let mut replies = self.packets.subscribe();
        let packet = Packet::PointToPoint {
            // Native C-Gate's dd command is deliberately unchecksummed and
            // asks the PCI to confirm delivery separately.
            meta: Meta::new(false, 1),
            unit_address: unit,
            bridged: false,
            hops: vec![],
            cals: vec![Cal::Unlock { parameter }],
        };
        let confirmation = self.send_guarded(&packet).await?;
        let code = confirmation.code;
        let result = tokio::time::timeout(REPLY_TIMEOUT, async {
            let mut confirmed = false;
            let mut challenge = None;
            loop {
                match replies.recv().await {
                    Ok(Some(Packet::Confirmation { code: got, success })) if got == code => {
                        if !success {
                            return Err(Error::other("PCI rejected parameter unlock"));
                        }
                        confirmed = true;
                    }
                    Ok(Some(packet)) => {
                        let cals = match packet {
                            Packet::PointToPoint { meta, cals, .. }
                                if meta.source_address == Some(unit) =>
                            {
                                cals
                            }
                            Packet::PointToPoint { meta, cals, .. }
                                if meta.source_address.is_none()
                                    && self.local_unit.load(Ordering::Acquire)
                                        == u16::from(unit) =>
                            {
                                cals
                            }
                            Packet::BareCal(cal)
                                if self.local_unit.load(Ordering::Acquire) == u16::from(unit) =>
                            {
                                vec![cal]
                            }
                            _ => continue,
                        };
                        if !cals.iter().any(|cal| {
                            matches!(cal, Cal::Reply { parameter: got, .. } if *got == parameter)
                        }) {
                            continue;
                        }
                        if cals.len() != 1 {
                            return Err(Error::new(
                                ErrorKind::InvalidData,
                                "parameter unlock reply contains an ambiguous CAL chain",
                            ));
                        }
                        let Cal::Reply { data, .. } = &cals[0] else {
                            unreachable!("matching unlock reply checked above")
                        };
                        if data.len() != 1 {
                            return Err(Error::new(
                                ErrorKind::InvalidData,
                                "parameter unlock reply must contain one byte",
                            ));
                        }
                        challenge = Some(data[0]);
                    }
                    Ok(None) | Err(_) => {
                        return Err(Error::new(
                            ErrorKind::BrokenPipe,
                            "PCI response stream lost",
                        ))
                    }
                }
                if confirmed {
                    if let Some(challenge) = challenge {
                        return Ok(challenge);
                    }
                }
            }
        })
        .await
        .unwrap_or_else(|_| {
            Err(Error::new(
                ErrorKind::TimedOut,
                "parameter unlock timed out",
            ))
        });
        result
    }

    async fn programming_send_once(&self, packet: &Packet) -> Result<u8> {
        let lane = self.send_lane.lock().await;
        self.init_done
            .subscribe()
            .wait_for(|&done| done)
            .await
            .map_err(|_| Error::new(ErrorKind::BrokenPipe, "PCI initialization ended"))?;
        if !self.is_connected() {
            return Err(Error::new(ErrorKind::BrokenPipe, "PCI disconnected"));
        }
        let mut bytes = packet
            .encode_packet()
            .map_err(|error| Error::new(ErrorKind::InvalidInput, error.0))?;
        bytes.insert(0, b'\\');
        let code = self.get_confirmation_code()?;
        bytes.push(code);
        bytes.push(b'\r');
        let written = self
            .flow
            .submit(bytes, Priority::Command, ResponseKind::Confirmation(code));
        drop(lane);
        if let Err(error) = written
            .await
            .map_err(|_| Error::new(ErrorKind::BrokenPipe, "flow controller ended"))?
        {
            self.release_legacy_confirmation(code);
            return Err(error);
        }
        // Deliberately do not add this write to `pending`: the protected
        // address STORE may already have moved the unit when confirmation is
        // lost, so replaying it would violate the zero-retry contract.
        Ok(code)
    }

    /// Readdress one unit using native C-Gate's protected parameter-0x20
    /// challenge exchange. The operation is sent exactly once and completes
    /// only after both PCI delivery confirmation and the unit's address-store
    /// ACK have been received.
    pub async fn readdress_unit(&self, source: u8, destination: u8) -> Result<()> {
        if source == 0 || !(1..=254).contains(&destination) || source == destination {
            return Err(Error::new(
                ErrorKind::InvalidInput,
                "readdress requires a source in 1..255 and a distinct destination in 1..254",
            ));
        }
        let _lane = self.programming_lane.lock().await;
        if self.programming_fault.load(Ordering::Acquire) {
            return Err(Error::other(
                "programming stream needs reconnect after an incomplete transaction",
            ));
        }
        let mut transaction = Transaction {
            fault: &self.programming_fault,
            complete: false,
        };
        let challenge = self.programming_unlock(source, 0x20).await?;
        let mut replies = self.packets.subscribe();
        let packet = Packet::PointToPoint {
            meta: Meta::new(false, 1),
            unit_address: source,
            bridged: false,
            hops: vec![],
            cals: vec![Cal::Readdress {
                destination,
                challenge,
            }],
        };
        let code = self.programming_send_once(&packet).await?;
        let result = tokio::time::timeout(REPLY_TIMEOUT, async {
            let mut confirmed = false;
            let mut accepted = None;
            loop {
                match replies.recv().await {
                    Ok(Some(Packet::Confirmation { code: got, success })) if got == code => {
                        if !success {
                            return Err(Error::other("PCI rejected readdress command"));
                        }
                        confirmed = true;
                    }
                    Ok(Some(Packet::PointToPoint { meta, cals, .. }))
                        if meta.source_address == Some(destination)
                            && cals
                                == [Cal::Ack {
                                    parameter: 0x20,
                                    data: vec![0x4e],
                                }] =>
                    {
                        accepted = Some(true);
                    }
                    Ok(Some(Packet::PointToPoint { meta, cals, .. }))
                        if meta.source_address == Some(source) && cals == [Cal::ReaddressNak] =>
                    {
                        accepted = Some(false);
                    }
                    Ok(Some(_)) => {}
                    Ok(None) | Err(_) => {
                        return Err(Error::new(
                            ErrorKind::BrokenPipe,
                            "PCI response stream lost",
                        ));
                    }
                }
                if confirmed {
                    match accepted {
                        Some(true) => return Ok(()),
                        Some(false) => {
                            return Err(Error::other("unit rejected readdress command"));
                        }
                        None => {}
                    }
                }
            }
        })
        .await
        .unwrap_or_else(|_| Err(Error::new(ErrorKind::TimedOut, "readdress timed out")));
        if result.is_err() {
            self.release_legacy_confirmation(code);
        }
        // A positive ACK or a definitive NAK closes the transaction. A
        // transport/timeout error remains uncertain and faults this lane.
        if result.is_ok()
            || result
                .as_ref()
                .is_err_and(|error| error.to_string() == "unit rejected readdress command")
        {
            transaction.complete = true;
        }
        result
    }

    /// Store one contiguous standard CAL parameter range and verify it with
    /// an immediate direct RECALL. Each STORE carries an explicit transaction
    /// tag, and large ranges are split at native C-Gate's twelve-byte limit.
    pub async fn store_parameter_verified(
        &self,
        unit: u8,
        parameter: u8,
        data: &[u8],
    ) -> Result<()> {
        self.store_parameter_verified_inner(unit, parameter, data, false)
            .await
    }

    /// Store the native C-Gate project identity at parameter 35 and verify it.
    ///
    /// Unlike ordinary tagged STORE operations, C-Gate fixes the transaction
    /// tag/operation byte to `0x46` for `NET SET_PROJECT_IDENTIFY`. Preserve
    /// that exact wire contract and require the matching unit ACK before a
    /// direct six-byte RECALL proves the value that remains on the unit.
    pub async fn set_project_identity_verified(&self, unit: u8, encoded: &[u8; 6]) -> Result<()> {
        const PARAMETER: u8 = 35;
        const TAG: u8 = 0x46;

        let _lane = self.programming_lane.lock().await;
        if self.programming_fault.load(Ordering::Acquire) {
            return Err(Error::other(
                "programming stream needs reconnect after an incomplete transaction",
            ));
        }
        let mut transaction = Transaction {
            fault: &self.programming_fault,
            complete: false,
        };
        let mut tagged = Vec::with_capacity(encoded.len() + 1);
        tagged.push(TAG);
        tagged.extend_from_slice(encoded);
        if let Err(error) = self
            .programming_exchange(
                unit,
                Cal::Write {
                    parameter: PARAMETER,
                    data: tagged,
                },
                PARAMETER,
                0,
                Some(TAG),
                ProgrammingRoute::DirectChecksummed,
            )
            .await
        {
            if error
                .to_string()
                .contains("unit rejected programming selector")
            {
                transaction.complete = true;
            }
            return Err(error);
        }
        let actual = self
            .programming_exchange(
                unit,
                Cal::Recall {
                    param: PARAMETER,
                    count: encoded.len() as u8,
                },
                PARAMETER,
                encoded.len(),
                None,
                ProgrammingRoute::DirectChecksummed,
            )
            .await?;
        if actual != encoded {
            return Err(Error::other(
                "project identity readback did not match STORE",
            ));
        }
        transaction.complete = true;
        Ok(())
    }

    /// Unlock, store and verify one lock-protected standard CAL parameter.
    /// The captured native path supports one STORE-sized field per unlock.
    pub async fn store_locked_parameter_verified(
        &self,
        unit: u8,
        parameter: u8,
        data: &[u8],
    ) -> Result<()> {
        self.store_parameter_verified_inner(unit, parameter, data, true)
            .await
    }

    async fn store_parameter_verified_inner(
        &self,
        unit: u8,
        parameter: u8,
        data: &[u8],
        locked: bool,
    ) -> Result<()> {
        if data.is_empty()
            || data.len() > u8::MAX as usize
            || usize::from(parameter) + data.len() > 256
        {
            return Err(Error::new(
                ErrorKind::InvalidInput,
                "parameter store requires 1..255 bytes within the parameter address space",
            ));
        }
        let _lane = self.programming_lane.lock().await;
        if self.programming_fault.load(Ordering::Acquire) {
            return Err(Error::other(
                "programming stream needs reconnect after an incomplete transaction",
            ));
        }
        let mut transaction = Transaction {
            fault: &self.programming_fault,
            complete: false,
        };
        for (chunk_index, chunk) in data.chunks(12).enumerate() {
            let offset = chunk_index * 12;
            let target = parameter + offset as u8;
            if locked {
                self.programming_unlock(unit, target).await?;
            }
            let tag = chunk_index as u8;
            let mut tagged = Vec::with_capacity(chunk.len() + 1);
            tagged.push(tag);
            tagged.extend_from_slice(chunk);
            self.programming_exchange(
                unit,
                Cal::Write {
                    parameter: target,
                    data: tagged,
                },
                target,
                0,
                Some(tag),
                ProgrammingRoute::DirectChecksummed,
            )
            .await?;
        }
        let count = data.len() as u8;
        let actual = self
            .programming_exchange(
                unit,
                Cal::Recall {
                    param: parameter,
                    count,
                },
                parameter,
                data.len(),
                None,
                ProgrammingRoute::DirectChecksummed,
            )
            .await?;
        if actual != data {
            return Err(Error::other(
                "standard parameter readback did not match STORE",
            ));
        }
        transaction.complete = true;
        Ok(())
    }

    /// Apply one operator-reviewed PP patch through the pipeline recovered
    /// from C-Gate 3.4's `mi`/`mh` patch executor.
    ///
    /// The programming lane remains held from the initial version read to the
    /// final version readback. Every STORE is source/tag correlated and then
    /// recalled exactly. An incomplete phase faults the lane until reconnect,
    /// so a caller can never replay an uncertain firmware write.
    pub async fn write_patch_verified(
        &self,
        unit: u8,
        patch_version_parameter: u8,
        expected_current_versions: &[u8],
        target_version: u8,
        blocks: &[PatchProgrammingBlock],
    ) -> Result<PatchApplyReceipt> {
        const PATCH_CONTROL_PARAMETER: u8 = 0x70;
        const PATCH_CONTROL_TAG: u8 = 0x85;
        const PATCH_VERSION_TAG: u8 = 0x86;
        const PATCH_BLOCK_TAG: u8 = 0x73;
        const PATCH_DISABLED: &[u8] = &[0xff, 0xff];
        const PATCH_ENABLED: &[u8] = &[0x9d, 0x40];

        if !(1..=254).contains(&unit) {
            return Err(Error::new(
                ErrorKind::InvalidInput,
                "patch programming requires a unit address from 1 through 254",
            ));
        }
        if patch_version_parameter != 0xf2 {
            return Err(Error::new(
                ErrorKind::InvalidInput,
                "native patch-version parameter must be 0xF2",
            ));
        }
        if expected_current_versions.is_empty() || blocks.is_empty() || blocks.len() > 4096 {
            return Err(Error::new(
                ErrorKind::InvalidInput,
                "patch requires expected versions and 1..4096 blocks",
            ));
        }
        let mut claimed = HashSet::new();
        let mut total = 0usize;
        for block in blocks {
            if block.data.is_empty() || block.data.len() > 12 {
                return Err(Error::new(
                    ErrorKind::InvalidInput,
                    "patch blocks require 1..12 bytes",
                ));
            }
            let end = usize::from(block.parameter) + block.data.len();
            let native_range = (114..=241).contains(&block.parameter) && end <= 242
                || (247..=254).contains(&block.parameter) && end <= 255;
            if !native_range {
                return Err(Error::new(
                    ErrorKind::InvalidInput,
                    "patch block is outside native patch memory ranges",
                ));
            }
            for byte in usize::from(block.parameter)..end {
                if !claimed.insert(byte as u8) {
                    return Err(Error::new(ErrorKind::InvalidInput, "patch blocks overlap"));
                }
            }
            total += block.data.len();
            if total > 136 {
                return Err(Error::new(
                    ErrorKind::InvalidInput,
                    "patch exceeds the 136-byte native range limit",
                ));
            }
        }

        let _lane = self.programming_lane.lock().await;
        if self.programming_fault.load(Ordering::Acquire) {
            return Err(Error::other(
                "programming stream needs reconnect after an incomplete transaction",
            ));
        }
        let mut transaction = Transaction {
            fault: &self.programming_fault,
            complete: false,
        };
        let previous_version = self
            .patch_recall_inner(unit, patch_version_parameter, 1)
            .await?[0];

        if previous_version == target_version {
            for block in blocks {
                let actual = self
                    .patch_recall_inner(unit, block.parameter, block.data.len())
                    .await?;
                if actual != block.data {
                    transaction.complete = true;
                    return Err(Error::other(format!(
                        "target patch version is already set but block at 0x{:02X} does not match",
                        block.parameter
                    )));
                }
            }
            // A previous attempt can set the target version and then lose the
            // final enable acknowledgement. Prove 0x70 before declaring the
            // patch complete, and repair it only when the recalled value is
            // not enabled.
            let control = self
                .patch_recall_inner(unit, PATCH_CONTROL_PARAMETER, PATCH_ENABLED.len())
                .await?;
            let repaired_control = control != PATCH_ENABLED;
            if repaired_control {
                self.patch_store_inner(
                    unit,
                    PATCH_CONTROL_PARAMETER,
                    PATCH_ENABLED,
                    true,
                    PATCH_CONTROL_TAG,
                )
                .await
                .map_err(|error| {
                    Error::new(
                        error.kind(),
                        format!("existing patch re-enable failed: {error}"),
                    )
                })?;
            }
            let final_version = self
                .patch_recall_inner(unit, patch_version_parameter, 1)
                .await?[0];
            if final_version != target_version {
                return Err(Error::other(format!(
                    "final patch version readback was 0x{final_version:02X}, expected 0x{target_version:02X}"
                )));
            }
            transaction.complete = true;
            return Ok(PatchApplyReceipt {
                previous_version,
                target_version,
                verified_blocks: blocks.len(),
                disposition: if repaired_control {
                    PatchApplyDisposition::RepairedEnableOnly
                } else {
                    PatchApplyDisposition::AlreadyVerifiedReadOnly
                },
            });
        }
        if !expected_current_versions.contains(&previous_version) {
            transaction.complete = true;
            return Err(Error::other(format!(
                "current patch version 0x{previous_version:02X} is not admitted by the patch manifest"
            )));
        }

        self.patch_store_inner(
            unit,
            PATCH_CONTROL_PARAMETER,
            PATCH_DISABLED,
            true,
            PATCH_CONTROL_TAG,
        )
        .await
        .map_err(|error| Error::new(error.kind(), format!("patch disable failed: {error}")))?;
        self.patch_store_inner(
            unit,
            patch_version_parameter,
            &[u8::MAX],
            true,
            PATCH_VERSION_TAG,
        )
        .await
        .map_err(|error| {
            Error::new(
                error.kind(),
                format!("temporary patch-version write failed: {error}"),
            )
        })?;

        for (index, block) in blocks.iter().enumerate() {
            self.patch_store_inner(
                unit,
                block.parameter,
                &block.data,
                block.unlock || block.parameter == 247,
                PATCH_BLOCK_TAG,
            )
            .await
            .map_err(|error| {
                Error::new(
                    error.kind(),
                    format!(
                        "patch block {} at 0x{:02X} failed: {error}",
                        index + 1,
                        block.parameter
                    ),
                )
            })?;
        }

        // Native `mi.a(patch, ..., true)` runs a distinct full verify pass
        // after the complete write pass. Retain the immediate per-STORE
        // readback above to prove each acknowledgement, then recall every
        // block again so a later block cannot silently disturb an earlier
        // one before the version is finalized.
        for (index, block) in blocks.iter().enumerate() {
            let actual = self
                .patch_recall_inner(unit, block.parameter, block.data.len())
                .await
                .map_err(|error| {
                    Error::new(
                        error.kind(),
                        format!(
                            "full patch verify read {} at 0x{:02X} failed: {error}",
                            index + 1,
                            block.parameter
                        ),
                    )
                })?;
            if actual != block.data {
                return Err(Error::other(format!(
                    "full patch verify failed at block {} parameter 0x{:02X}",
                    index + 1,
                    block.parameter
                )));
            }
        }

        self.patch_store_inner(
            unit,
            patch_version_parameter,
            &[target_version],
            true,
            PATCH_VERSION_TAG,
        )
        .await
        .map_err(|error| {
            Error::new(
                error.kind(),
                format!("target patch-version write failed: {error}"),
            )
        })?;
        self.patch_store_inner(
            unit,
            PATCH_CONTROL_PARAMETER,
            PATCH_ENABLED,
            true,
            PATCH_CONTROL_TAG,
        )
        .await
        .map_err(|error| Error::new(error.kind(), format!("patch enable failed: {error}")))?;
        let final_version = self
            .patch_recall_inner(unit, patch_version_parameter, 1)
            .await?[0];
        if final_version != target_version {
            return Err(Error::other(format!(
                "final patch version readback was 0x{final_version:02X}, expected 0x{target_version:02X}"
            )));
        }
        transaction.complete = true;
        Ok(PatchApplyReceipt {
            previous_version,
            target_version,
            verified_blocks: blocks.len(),
            disposition: PatchApplyDisposition::AppliedFullPipeline,
        })
    }

    async fn patch_store_inner(
        &self,
        unit: u8,
        parameter: u8,
        data: &[u8],
        unlock: bool,
        tag: u8,
    ) -> Result<()> {
        let effective_tag = if parameter == 0xf7 {
            // Native mh.java classifies 0xF7 as custom type 3 and uses the
            // returned dd unlock challenge as the ct STORE tag.
            self.programming_unlock(unit, parameter).await?
        } else {
            if unlock {
                // Ordinary protected blocks discard the challenge and retain
                // their fixed native operation tag.
                self.programming_unlock(unit, parameter).await?;
            }
            tag
        };
        let mut tagged = Vec::with_capacity(data.len() + 1);
        tagged.push(effective_tag);
        tagged.extend_from_slice(data);
        self.programming_exchange(
            unit,
            Cal::Write {
                parameter,
                data: tagged,
            },
            parameter,
            0,
            Some(effective_tag),
            ProgrammingRoute::DirectChecksummed,
        )
        .await?;
        let actual = self.patch_recall_inner(unit, parameter, data.len()).await?;
        if actual != data {
            return Err(Error::other(format!(
                "parameter 0x{parameter:02X} readback did not match STORE"
            )));
        }
        Ok(())
    }

    async fn patch_recall_inner(&self, unit: u8, parameter: u8, count: usize) -> Result<Vec<u8>> {
        let count_u8 = u8::try_from(count).map_err(|_| {
            Error::new(
                ErrorKind::InvalidInput,
                "patch recall requires 1..255 bytes",
            )
        })?;
        if count_u8 == 0 {
            return Err(Error::new(
                ErrorKind::InvalidInput,
                "patch recall requires 1..255 bytes",
            ));
        }
        self.programming_exchange(
            unit,
            Cal::Recall {
                param: parameter,
                count: count_u8,
            },
            parameter,
            count,
            None,
            ProgrammingRoute::DirectChecksummed,
        )
        .await
    }

    /// Store a bounded OEM physical-memory range through the captured 0x41
    /// pointer and tagged 0x42 data path, then reselect and read the entire
    /// range back before reporting success.
    pub async fn write_memory_verified(&self, unit: u8, address: u32, data: &[u8]) -> Result<()> {
        self.write_oem_memory_verified_inner(unit, address, data, false, false)
            .await
    }

    /// Store GIU memory while the native run flag is halted, restore it, and
    /// verify the complete range through the OEM recall path.
    pub async fn write_giu_memory_verified(
        &self,
        unit: u8,
        address: u32,
        data: &[u8],
    ) -> Result<()> {
        self.write_oem_memory_verified_inner(unit, address, data, true, false)
            .await
    }

    /// Store SGIU memory with the native twelve-byte block limit and verify it.
    pub async fn write_sgiu_memory_verified(
        &self,
        unit: u8,
        address: u32,
        data: &[u8],
    ) -> Result<()> {
        self.write_oem_memory_verified_inner(unit, address, data, false, false)
            .await
    }

    /// Store DALI-unit programming memory after C-Gate's one-second settling
    /// interval, then verify the complete range.
    pub async fn write_dali_memory_verified(
        &self,
        unit: u8,
        address: u32,
        data: &[u8],
    ) -> Result<()> {
        self.write_oem_memory_verified_inner(unit, address, data, false, true)
            .await
    }

    async fn write_oem_memory_verified_inner(
        &self,
        unit: u8,
        address: u32,
        data: &[u8],
        halt: bool,
        settle: bool,
    ) -> Result<()> {
        if data.is_empty()
            || data.len() > 65_536
            || address.checked_add(data.len() as u32).is_none()
        {
            return Err(Error::new(
                ErrorKind::InvalidInput,
                "memory store requires 1..65536 bytes without address overflow",
            ));
        }
        let _lane = self.programming_lane.lock().await;
        if self.programming_fault.load(Ordering::Acquire) {
            return Err(Error::other(
                "programming stream needs reconnect after an incomplete transaction",
            ));
        }
        let mut transaction = Transaction {
            fault: &self.programming_fault,
            complete: false,
        };
        if halt {
            self.programming_exchange(
                unit,
                Cal::Write {
                    parameter: 0xfc,
                    data: vec![3, 0],
                },
                0xfc,
                0,
                Some(3),
                ProgrammingRoute::Oem,
            )
            .await?;
        }
        if settle {
            tokio::time::sleep(Duration::from_secs(1)).await;
        }
        for (chunk_index, chunk) in data.chunks(12).enumerate() {
            let offset = address + (chunk_index * 12) as u32;
            let mut selector = vec![0x41];
            selector
                .extend_from_slice(&offset.to_le_bytes()[..if offset <= 0xffff { 2 } else { 4 }]);
            self.programming_exchange(
                unit,
                Cal::Write {
                    parameter: 0,
                    data: selector,
                },
                0,
                0,
                Some(0x41),
                ProgrammingRoute::Oem,
            )
            .await?;
            let mut tagged = Vec::with_capacity(chunk.len() + 1);
            tagged.push(0x42);
            tagged.extend_from_slice(chunk);
            self.programming_exchange(
                unit,
                Cal::Write {
                    parameter: 1,
                    data: tagged,
                },
                1,
                0,
                Some(0x42),
                ProgrammingRoute::Oem,
            )
            .await?;
        }

        if halt {
            self.programming_exchange(
                unit,
                Cal::Write {
                    parameter: 0xfc,
                    data: vec![3, 1],
                },
                0xfc,
                0,
                Some(3),
                ProgrammingRoute::Oem,
            )
            .await?;
        }

        let mut actual = Vec::with_capacity(data.len());
        while actual.len() < data.len() {
            let offset = address + actual.len() as u32;
            let mut selector = vec![0x41];
            selector
                .extend_from_slice(&offset.to_le_bytes()[..if offset <= 0xffff { 2 } else { 4 }]);
            self.programming_exchange(
                unit,
                Cal::Write {
                    parameter: 0,
                    data: selector,
                },
                0,
                0,
                Some(0x41),
                ProgrammingRoute::Oem,
            )
            .await?;
            let count = (data.len() - actual.len()).min(128) as u8;
            actual.extend(
                self.programming_exchange(
                    unit,
                    Cal::Recall { param: 1, count },
                    1,
                    usize::from(count),
                    None,
                    ProgrammingRoute::Oem,
                )
                .await?,
            );
        }
        if actual != data {
            return Err(Error::other("physical memory readback did not match STORE"));
        }
        transaction.complete = true;
        Ok(())
    }

    /// Store one GOC programming range with its native address prefix and
    /// dialect-specific block size, then read the range back before success.
    pub async fn write_goc_memory_verified(
        &self,
        unit: u8,
        address: u32,
        data: &[u8],
        dialect: GocProgramming,
    ) -> Result<()> {
        if data.is_empty()
            || data.len() > 65_536
            || address
                .checked_add(data.len() as u32)
                .is_none_or(|end| end > 65_536)
        {
            return Err(Error::new(
                ErrorKind::InvalidInput,
                "GOC memory store requires 1..65536 bytes in the 16-bit address space",
            ));
        }
        let _lane = self.programming_lane.lock().await;
        if self.programming_fault.load(Ordering::Acquire) {
            return Err(Error::other(
                "programming stream needs reconnect after an incomplete transaction",
            ));
        }
        let mut transaction = Transaction {
            fault: &self.programming_fault,
            complete: false,
        };
        for (chunk_index, chunk) in data.chunks(dialect.store_limit()).enumerate() {
            let offset = address + (chunk_index * dialect.store_limit()) as u32;
            let offset = u16::try_from(offset)
                .map_err(|_| Error::new(ErrorKind::InvalidInput, "GOC address exceeds 16 bits"))?;
            let tag = chunk_index as u8;
            let mut tagged = Vec::with_capacity(chunk.len() + 3);
            tagged.extend_from_slice(&[tag, (offset >> 8) as u8, offset as u8]);
            tagged.extend_from_slice(chunk);
            self.programming_exchange(
                unit,
                Cal::Write {
                    parameter: u8::MAX,
                    data: tagged,
                },
                u8::MAX,
                0,
                Some(tag),
                ProgrammingRoute::DirectChecksummed,
            )
            .await?;
        }
        let actual = self
            .read_goc_memory_inner(unit, address, data.len(), dialect)
            .await?;
        if actual != data {
            return Err(Error::other("GOC memory readback did not match STORE"));
        }
        transaction.complete = true;
        Ok(())
    }

    /// Identify a real unit attribute, preserving its original reply bytes.
    pub async fn identify(&self, unit: u8, attribute: u8) -> Result<Vec<u8>> {
        let _lane = self.programming_lane.lock().await;
        if self.programming_fault.load(Ordering::Acquire) {
            return Err(Error::other(
                "programming stream needs reconnect after an incomplete transaction",
            ));
        }
        let mut transaction = Transaction {
            fault: &self.programming_fault,
            complete: false,
        };
        let result = self
            .programming_exchange(
                unit,
                Cal::Identify { attribute },
                attribute,
                0,
                None,
                ProgrammingRoute::DirectChecksummed,
            )
            .await?;
        transaction.complete = true;
        Ok(result)
    }

    /// Collect every reply to one IDENTIFY request through a two-second
    /// quiet interval. This is the native C-Gate duplicate-address probe used
    /// by `NET CHECKUNIT`: a first reply establishes presence, but cannot
    /// establish that only one unit owns the address.
    ///
    /// A positive PCI delivery confirmation is required before the observation
    /// can complete; real CNIs may deliver unit data first, so it is buffered
    /// until that confirmation arrives. Reaching the seven-frame native response bound is treated as
    /// incomplete rather than silently claiming that no further identity was
    /// present. As with memory reads, any incomplete observation poisons this
    /// programming lane until reconnect so a late untagged reply cannot be
    /// attributed to another request.
    pub async fn identify_all(&self, unit: u8, attribute: u8) -> Result<Vec<Vec<u8>>> {
        self.identify_collect(unit, attribute, false, &[]).await
    }

    /// Return the first confirmed matching IDENTIFY reply, or `None` when the
    /// unit remains silent for the bounded response window. This populates
    /// ordinary identity fields without claiming duplicate absence.
    pub async fn identify_first(&self, unit: u8, attribute: u8) -> Result<Option<Vec<u8>>> {
        Ok(self
            .identify_collect(unit, attribute, true, &[])
            .await?
            .into_iter()
            .next())
    }

    /// Collect every matching IDENTIFY reply through an evidenced bridge
    /// source route. Replies from the direct network or another route are
    /// ignored and cannot populate the target network's cache.
    pub async fn identify_all_routed(
        &self,
        bridges: &[u8],
        unit: u8,
        attribute: u8,
    ) -> Result<Vec<Vec<u8>>> {
        validate_bridge_route(bridges)?;
        self.identify_collect(unit, attribute, false, bridges).await
    }

    /// Return the first confirmed IDENTIFY reply on an evidenced bridge
    /// route, or `None` after the bounded quiet interval.
    pub async fn identify_first_routed(
        &self,
        bridges: &[u8],
        unit: u8,
        attribute: u8,
    ) -> Result<Option<Vec<u8>>> {
        validate_bridge_route(bridges)?;
        Ok(self
            .identify_collect(unit, attribute, true, bridges)
            .await?
            .into_iter()
            .next())
    }

    /// Run one native C-Gate duplicate-address challenge for `NET SYNCNEW`.
    ///
    /// Native C-Gate sends CAL Unlock parameters `0x80`, `0x81`, and `0x82`
    /// on the three successive attempts and counts every matching one-byte
    /// reply. The byte value is deliberately ignored: two matching replies
    /// prove that more than one unit answered at this address. A positive PCI
    /// confirmation is required before the two-second quiet interval can
    /// complete, and reaching the native seven-reply bound faults the lane
    /// rather than silently claiming a complete count.
    pub async fn duplicate_address_probe(&self, unit: u8, attempt: u8) -> Result<usize> {
        if attempt > 2 {
            return Err(Error::new(
                ErrorKind::InvalidInput,
                "duplicate-address probe attempt must be in 0..=2",
            ));
        }
        let parameter = 0x80 + attempt;
        let _lane = self.programming_lane.lock().await;
        if self.programming_fault.load(Ordering::Acquire) {
            return Err(Error::other(
                "programming stream needs reconnect after an incomplete transaction",
            ));
        }
        let mut transaction = Transaction {
            fault: &self.programming_fault,
            complete: false,
        };
        let mut replies = self.packets.subscribe();
        if !self.is_connected() {
            return Err(Error::new(ErrorKind::BrokenPipe, "PCI disconnected"));
        }
        let packet = Packet::PointToPoint {
            meta: Meta::new(true, 1),
            unit_address: unit,
            bridged: false,
            hops: vec![],
            cals: vec![Cal::Unlock { parameter }],
        };
        let confirmation = self.send_guarded(&packet).await?;
        let code = confirmation.code;

        let result = tokio::time::timeout(REPLY_TIMEOUT, async {
            let mut confirmed = false;
            let mut count = 0usize;
            let mut quiet_deadline = None;
            loop {
                let next = async {
                    match quiet_deadline {
                        Some(deadline) => tokio::time::timeout_at(deadline, replies.recv())
                            .await
                            .map_err(|_| {
                            Error::new(ErrorKind::TimedOut, "duplicate-address probe quiet")
                        })?,
                        None => replies.recv().await,
                    }
                    .map_err(|_| Error::new(ErrorKind::BrokenPipe, "PCI response stream lost"))
                };
                match next.await {
                    Err(error)
                        if error.kind() == ErrorKind::TimedOut && quiet_deadline.is_some() =>
                    {
                        return Ok(count);
                    }
                    Err(error) => return Err(error),
                    Ok(None) => {
                        return Err(Error::new(
                            ErrorKind::BrokenPipe,
                            "PCI response stream lost",
                        ));
                    }
                    Ok(Some(Packet::Confirmation { code: got, success })) if got == code => {
                        if confirmed {
                            return Err(Error::new(
                                ErrorKind::InvalidData,
                                "duplicate duplicate-address probe confirmation",
                            ));
                        }
                        if !success {
                            return Err(Error::other("PCI rejected duplicate-address probe"));
                        }
                        confirmed = true;
                        quiet_deadline = Some(Instant::now() + DUPLICATE_PROBE_QUIET);
                    }
                    Ok(Some(packet)) => {
                        let cals = match packet {
                            Packet::PointToPoint { meta, cals, .. }
                                if meta.source_address == Some(unit) =>
                            {
                                cals
                            }
                            Packet::PointToPoint { meta, cals, .. }
                                if meta.source_address.is_none()
                                    && self.local_unit.load(Ordering::Acquire)
                                        == u16::from(unit) =>
                            {
                                cals
                            }
                            Packet::BareCal(cal)
                                if self.local_unit.load(Ordering::Acquire) == u16::from(unit) =>
                            {
                                vec![cal]
                            }
                            _ => continue,
                        };
                        if !cals.iter().any(|cal| {
                            matches!(cal, Cal::Reply { parameter: got, .. } if *got == parameter)
                        }) {
                            continue;
                        }
                        if cals.len() != 1 {
                            return Err(Error::new(
                                ErrorKind::InvalidData,
                                "duplicate-address reply contains an ambiguous CAL chain",
                            ));
                        }
                        let Cal::Reply { data, .. } = cals.into_iter().next().unwrap() else {
                            unreachable!("matching reply checked above")
                        };
                        if data.len() != 1 {
                            return Err(Error::new(
                                ErrorKind::InvalidData,
                                "duplicate-address reply must contain one byte",
                            ));
                        }
                        count += 1;
                        if count >= DUPLICATE_PROBE_MAX_REPLIES {
                            return Err(Error::new(
                                ErrorKind::InvalidData,
                                "duplicate-address response count reached the collection limit",
                            ));
                        }
                        if confirmed {
                            quiet_deadline = Some(Instant::now() + DUPLICATE_PROBE_QUIET);
                        }
                    }
                }
            }
        })
        .await
        .unwrap_or_else(|_| {
            Err(Error::new(
                ErrorKind::TimedOut,
                "duplicate-address probe timed out",
            ))
        });

        if result.is_ok() {
            transaction.complete = true;
        }
        result
    }

    async fn identify_collect(
        &self,
        unit: u8,
        attribute: u8,
        stop_after_first: bool,
        bridges: &[u8],
    ) -> Result<Vec<Vec<u8>>> {
        let _lane = self.programming_lane.lock().await;
        self.identify_collect_inner_for_route(unit, attribute, stop_after_first, bridges)
            .await
    }

    // Caller holds programming_lane for the entire reply window.
    pub(super) async fn identify_collect_inner(
        &self,
        unit: u8,
        attribute: u8,
        stop_after_first: bool,
    ) -> Result<Vec<Vec<u8>>> {
        self.identify_collect_inner_for_route(unit, attribute, stop_after_first, &[])
            .await
    }

    async fn identify_collect_inner_for_route(
        &self,
        unit: u8,
        attribute: u8,
        stop_after_first: bool,
        bridges: &[u8],
    ) -> Result<Vec<Vec<u8>>> {
        if self.programming_fault.load(Ordering::Acquire) {
            return Err(Error::other(
                "programming stream needs reconnect after an incomplete transaction",
            ));
        }
        let mut transaction = Transaction {
            fault: &self.programming_fault,
            complete: false,
        };
        let mut replies = self.packets.subscribe();
        if !self.is_connected() {
            return Err(Error::new(ErrorKind::BrokenPipe, "PCI disconnected"));
        }
        let packet = Packet::PointToPoint {
            meta: Meta::new(true, 1),
            unit_address: unit,
            bridged: !bridges.is_empty(),
            hops: bridges.to_vec(),
            cals: vec![Cal::Identify { attribute }],
        };
        let confirmation = self.send_guarded(&packet).await?;
        let code = confirmation.code;

        let result = tokio::time::timeout(REPLY_TIMEOUT, async {
            let mut confirmed = false;
            let mut collected = Vec::new();
            let mut quiet_deadline = None;
            loop {
                let next =
                    async {
                        match quiet_deadline {
                            Some(deadline) => tokio::time::timeout_at(deadline, replies.recv())
                                .await
                                .map_err(|_| Error::new(ErrorKind::TimedOut, "identify quiet"))?,
                            None => replies.recv().await,
                        }
                        .map_err(|_| Error::new(ErrorKind::BrokenPipe, "PCI response stream lost"))
                    };
                match next.await {
                    Err(error)
                        if error.kind() == ErrorKind::TimedOut && quiet_deadline.is_some() =>
                    {
                        return Ok(collected)
                    }
                    Err(error) => return Err(error),
                    Ok(None) => {
                        return Err(Error::new(
                            ErrorKind::BrokenPipe,
                            "PCI response stream lost",
                        ))
                    }
                    Ok(Some(Packet::Confirmation { code: got, success })) if got == code => {
                        if confirmed {
                            return Err(Error::new(
                                ErrorKind::InvalidData,
                                "duplicate IDENTIFY confirmation",
                            ));
                        }
                        if !success {
                            return Err(Error::other("PCI rejected IDENTIFY command"));
                        }
                        confirmed = true;
                        if stop_after_first && !collected.is_empty() {
                            return Ok(collected);
                        }
                        quiet_deadline = Some(Instant::now() + IDENTIFY_QUIET);
                    }
                    Ok(Some(packet)) => {
                        let cals = match packet {
                            Packet::PointToPoint {
                                meta,
                                unit_address,
                                bridged,
                                hops,
                                cals,
                            } if identify_reply_matches(
                                &meta,
                                unit_address,
                                bridged,
                                &hops,
                                bridges,
                                unit,
                            ) =>
                            {
                                cals
                            }
                            Packet::PointToPoint { meta, cals, .. }
                                if bridges.is_empty()
                                    && meta.source_address.is_none()
                                    && self.local_unit.load(Ordering::Acquire)
                                        == u16::from(unit) =>
                            {
                                cals
                            }
                            Packet::BareCal(cal)
                                if bridges.is_empty()
                                    && self.local_unit.load(Ordering::Acquire)
                                        == u16::from(unit) =>
                            {
                                vec![cal]
                            }
                            _ => continue,
                        };
                        if !cals.iter().any(|cal| {
                            matches!(cal, Cal::Reply { parameter, .. } if *parameter == attribute)
                        }) {
                            continue;
                        }
                        if cals.len() != 1 {
                            return Err(Error::new(
                                ErrorKind::InvalidData,
                                "IDENTIFY reply contains an ambiguous CAL chain",
                            ));
                        }
                        let Cal::Reply { data, .. } = cals.into_iter().next().unwrap() else {
                            unreachable!("matching reply checked above")
                        };
                        collected.push(data);
                        if stop_after_first && confirmed {
                            return Ok(collected);
                        }
                        if collected.len() >= IDENTIFY_MAX_REPLIES {
                            return Err(Error::new(
                                ErrorKind::InvalidData,
                                "IDENTIFY response count reached the collection limit",
                            ));
                        }
                        if confirmed {
                            quiet_deadline = Some(Instant::now() + IDENTIFY_QUIET);
                        }
                    }
                }
            }
        })
        .await
        .unwrap_or_else(|_| {
            Err(Error::new(
                ErrorKind::TimedOut,
                "IDENTIFY collection timed out",
            ))
        });

        if result.is_ok() {
            transaction.complete = true;
        }
        result
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tokio::io::{AsyncBufReadExt, AsyncReadExt, BufReader};

    #[derive(Default)]
    struct SelectedSerialWriteGate {
        blocked: std::sync::atomic::AtomicBool,
        started: tokio::sync::Notify,
        waker: Mutex<Option<std::task::Waker>>,
    }

    struct SelectedSerialBlockingWriter {
        inner: BoxedWrite,
        gate: Arc<SelectedSerialWriteGate>,
    }

    impl tokio::io::AsyncWrite for SelectedSerialBlockingWriter {
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

    async fn setup() -> (
        Arc<PciClient>,
        BufReader<tokio::io::DuplexStream>,
        mpsc::UnboundedReceiver<CBusEvent>,
    ) {
        let (client, remote) = tokio::io::duplex(8192);
        let (rd, wr) = tokio::io::split(client);
        let (tx, rx) = mpsc::unbounded_channel();
        let pci = PciClient::new(Box::new(rd), Box::new(wr), tx);
        pci.pci_reset().await.unwrap();
        let mut remote = BufReader::new(remote);
        for _ in 0..8 {
            let mut bytes = Vec::new();
            remote.read_until(b'\r', &mut bytes).await.unwrap();
        }
        (pci, remote, rx)
    }

    async fn setup_with_blocking_writer() -> (
        Arc<PciClient>,
        BufReader<tokio::io::DuplexStream>,
        Arc<SelectedSerialWriteGate>,
    ) {
        let (client, remote) = tokio::io::duplex(8192);
        let (rd, wr) = tokio::io::split(client);
        let gate = Arc::new(SelectedSerialWriteGate::default());
        let writer = SelectedSerialBlockingWriter {
            inner: Box::new(wr),
            gate: gate.clone(),
        };
        let (tx, _rx) = mpsc::unbounded_channel();
        let pci = PciClient::new(Box::new(rd), Box::new(writer), tx);
        pci.pci_reset().await.unwrap();
        let mut remote = BufReader::new(remote);
        for _ in 0..8 {
            let mut bytes = Vec::new();
            remote.read_until(b'\r', &mut bytes).await.unwrap();
        }
        (pci, remote, gate)
    }

    async fn line(remote: &mut BufReader<tokio::io::DuplexStream>) -> Vec<u8> {
        let mut bytes = Vec::new();
        remote.read_until(b'\r', &mut bytes).await.unwrap();
        bytes
    }

    async fn reply(remote: &mut BufReader<tokio::io::DuplexStream>, unit: u8, cal: &[u8]) {
        // Captured response route; independent of the request encoder.
        let mut bytes = vec![0x86, unit, 0x10, 0x01, 0x00];
        bytes.extend(cal);
        let sum = bytes.iter().fold(0u8, |acc, b| acc.wrapping_add(*b));
        bytes.push(0u8.wrapping_sub(sum));
        let wire = format!(
            "{}\r\n",
            bytes.iter().map(|b| format!("{b:02X}")).collect::<String>()
        );
        remote.get_mut().write_all(wire.as_bytes()).await.unwrap();
    }

    async fn direct_reply(remote: &mut BufReader<tokio::io::DuplexStream>, source: u8, cal: &[u8]) {
        // Literal native direct-reply envelope: source, local PCI unit 0x10,
        // route terminator, CAL and checksum.
        let mut bytes = vec![0x86, source, 0x10, 0x00];
        bytes.extend(cal);
        let sum = bytes.iter().fold(0u8, |acc, byte| acc.wrapping_add(*byte));
        bytes.push(0u8.wrapping_sub(sum));
        let mut wire = hex::encode_upper(bytes).into_bytes();
        wire.extend_from_slice(b"\r\n");
        remote.get_mut().write_all(&wire).await.unwrap();
    }

    async fn routed_reply(
        remote: &mut BufReader<tokio::io::DuplexStream>,
        bridges: &[u8],
        unit: u8,
        cal: &[u8],
    ) {
        let mut bytes = vec![0x86, bridges[0], 0x10, bridges.len() as u8];
        bytes.extend_from_slice(&bridges[1..]);
        bytes.push(unit);
        bytes.extend_from_slice(cal);
        let sum = bytes.iter().fold(0u8, |acc, byte| acc.wrapping_add(*byte));
        bytes.push(0u8.wrapping_sub(sum));
        let wire = format!(
            "{}\r\n",
            bytes
                .iter()
                .map(|byte| format!("{byte:02X}"))
                .collect::<String>()
        );
        remote.get_mut().write_all(wire.as_bytes()).await.unwrap();
    }

    async fn drive_kfi_get_preamble(
        remote: &mut BufReader<tokio::io::DuplexStream>,
        unit: u8,
    ) -> u8 {
        let expected = [
            b"\\460500A3FF00090A".as_slice(),
            b"\\460500A5FF0082001C73".as_slice(),
            b"\\460500A5FF008404FF8A".as_slice(),
        ];
        assert_eq!(unit, 5, "literal KFI oracle frames are for unit 5");
        for (index, frame) in expected.into_iter().enumerate() {
            let request = line(remote).await;
            assert_eq!(&request[..request.len() - 2], frame);
            let code = request[request.len() - 2];
            // The source-correlated unit ACK may arrive on either side of
            // the independent PCI delivery confirmation.
            if index == 0 {
                reply(remote, unit, &[0x32, 0xff, 0x00]).await;
                remote.get_mut().write_all(&[code, b'.']).await.unwrap();
            } else {
                remote.get_mut().write_all(&[code, b'.']).await.unwrap();
                reply(remote, unit, &[0x32, 0xff, 0x00]).await;
            }
        }
        let request = line(remote).await;
        assert_eq!(&request[..request.len() - 2], b"\\460500213D57");
        request[request.len() - 2]
    }

    async fn kfi_reply(remote: &mut BufReader<tokio::io::DuplexStream>, unit: u8, packed: [u8; 4]) {
        let mut cal = vec![0x8d, kfi::ATTRIBUTE, 0x80];
        cal.extend_from_slice(&packed);
        cal.extend_from_slice(&[0; 7]);
        reply(remote, unit, &cal).await;
    }

    #[tokio::test(start_paused = true)]
    async fn kfiget_uses_native_sequence_and_correlates_one_reply() {
        let (pci, mut remote, _) = setup().await;
        let running = tokio::spawn({
            let pci = pci.clone();
            async move { pci.get_key_function_indicators(5).await }
        });
        let code = drive_kfi_get_preamble(&mut remote, 5).await;

        // A valid reply may precede confirmation, but the command must not
        // complete until delivery is positively confirmed. A different
        // source cannot satisfy the unit-scoped transaction.
        kfi_reply(&mut remote, 4, [0xff; 4]).await;
        kfi_reply(&mut remote, 5, [0x21, 0x43, 0x65, 0x87]).await;
        tokio::task::yield_now().await;
        assert!(!running.is_finished());
        remote.get_mut().write_all(&[code, b'.']).await.unwrap();
        tokio::time::advance(IDENTIFY_QUIET).await;
        tokio::task::yield_now().await;
        assert_eq!(
            running.await.unwrap().unwrap(),
            vec![[1, 2, 3, 4, 5, 6, 7, 8]]
        );
    }

    #[tokio::test(start_paused = true)]
    async fn kfiget_preserves_zero_and_multiple_native_outcomes() {
        let (pci, mut remote, _) = setup().await;
        let none = tokio::spawn({
            let pci = pci.clone();
            async move { pci.get_key_function_indicators(5).await }
        });
        let code = drive_kfi_get_preamble(&mut remote, 5).await;
        remote.get_mut().write_all(&[code, b'.']).await.unwrap();
        tokio::time::advance(IDENTIFY_QUIET).await;
        tokio::task::yield_now().await;
        assert!(none.await.unwrap().unwrap().is_empty());

        let multiple = tokio::spawn({
            let pci = pci.clone();
            async move { pci.get_key_function_indicators(5).await }
        });
        let code = drive_kfi_get_preamble(&mut remote, 5).await;
        remote.get_mut().write_all(&[code, b'.']).await.unwrap();
        kfi_reply(&mut remote, 5, [0x21, 0x43, 0x65, 0x87]).await;
        kfi_reply(&mut remote, 5, [0x10, 0x32, 0x54, 0x76]).await;
        let replies = multiple.await.unwrap().unwrap();
        assert_eq!(replies.len(), 2);
        assert_eq!(replies[0], [1, 2, 3, 4, 5, 6, 7, 8]);
        assert_eq!(replies[1], [0, 1, 2, 3, 4, 5, 6, 7]);
    }

    #[tokio::test(start_paused = true)]
    async fn kfiget_rejects_a_short_correlated_reply() {
        let (pci, mut remote, _) = setup().await;
        let running = tokio::spawn(async move { pci.get_key_function_indicators(5).await });
        let code = drive_kfi_get_preamble(&mut remote, 5).await;
        remote.get_mut().write_all(&[code, b'.']).await.unwrap();
        // 0x85 carries parameter plus four data bytes, shorter than native
        // 0x8D while retaining the correlated attribute/selector prefix.
        reply(
            &mut remote,
            5,
            &[0x85, kfi::ATTRIBUTE, 0x80, 0x21, 0x43, 0x65],
        )
        .await;
        assert_eq!(
            running.await.unwrap().unwrap_err().kind(),
            ErrorKind::InvalidData
        );
    }

    #[tokio::test(start_paused = true)]
    async fn kfiget_negative_identify_confirmation_is_an_error() {
        let (pci, mut remote, _) = setup().await;
        let running = tokio::spawn(async move { pci.get_key_function_indicators(5).await });
        let code = drive_kfi_get_preamble(&mut remote, 5).await;
        remote.get_mut().write_all(&[code, b'#']).await.unwrap();
        assert!(running
            .await
            .unwrap()
            .unwrap_err()
            .to_string()
            .contains("PCI rejected KFIGET"));
    }

    #[tokio::test(start_paused = true)]
    async fn kfiset_packs_nibbles_and_aborts_on_rejection() {
        let (pci, mut remote, _) = setup().await;
        let running = tokio::spawn({
            let pci = pci.clone();
            async move {
                pci.set_key_function_indicators(5, [1, 2, 3, 4, 5, 6, 7, 8])
                    .await
            }
        });
        for expected in [
            b"\\460500A3FF00090A".as_slice(),
            b"\\460500A5FF0084214329".as_slice(),
            b"\\460500A5FF00846587A1".as_slice(),
            b"\\460500A4FF006BACFB".as_slice(),
        ] {
            let request = line(&mut remote).await;
            assert_eq!(&request[..request.len() - 2], expected);
            let code = request[request.len() - 2];
            remote.get_mut().write_all(&[code, b'.']).await.unwrap();
            reply(&mut remote, 5, &[0x32, 0xff, 0x00]).await;
        }
        running.await.unwrap().unwrap();

        let (pci, mut remote, _) = setup().await;
        let rejected = tokio::spawn(async move {
            pci.set_key_function_indicators(5, [1, 2, 3, 4, 5, 6, 7, 8])
                .await
        });
        let request = line(&mut remote).await;
        assert_eq!(&request[..request.len() - 2], b"\\460500A3FF00090A");
        let code = request[request.len() - 2];
        remote.get_mut().write_all(&[code, b'.']).await.unwrap();
        reply(&mut remote, 5, &[0x32, 0xff, 0x00]).await;
        let request = line(&mut remote).await;
        assert_eq!(&request[..request.len() - 2], b"\\460500A5FF0084214329");
        let code = request[request.len() - 2];
        remote.get_mut().write_all(&[code, b'.']).await.unwrap();
        // NAK tails are operation-specific; every source-correlated `3B FF`
        // rejects this write, not only a zero-valued tail.
        reply(&mut remote, 5, &[0x3b, 0xff, 0x7e]).await;
        assert!(rejected
            .await
            .unwrap()
            .unwrap_err()
            .to_string()
            .contains("rejected"));
    }

    #[tokio::test(start_paused = true)]
    async fn kfiset_non_exact_ack_times_out_without_sending_the_next_write() {
        let (pci, mut remote, _) = setup().await;
        let running =
            tokio::spawn(async move { pci.set_key_function_indicators(5, [0; kfi::COUNT]).await });
        let request = line(&mut remote).await;
        assert_eq!(&request[..request.len() - 2], b"\\460500A3FF00090A");
        let code = request[request.len() - 2];
        remote.get_mut().write_all(&[code, b'.']).await.unwrap();
        // Only native `32 FF 00` is success. An ACK for the same parameter
        // with a longer payload must not advance the write sequence.
        reply(&mut remote, 5, &[0x33, 0xff, 0x00, 0x01]).await;
        tokio::select! {
            unexpected = line(&mut remote) => {
                panic!("non-exact KFI ACK advanced the sequence: {unexpected:?}")
            }
            _ = tokio::time::sleep(Duration::from_millis(1)) => {}
        }
        tokio::time::advance(REPLY_TIMEOUT).await;
        tokio::task::yield_now().await;
        assert_eq!(
            running.await.unwrap().unwrap_err().kind(),
            ErrorKind::TimedOut
        );
    }

    #[tokio::test(start_paused = true)]
    async fn kfi_ack_before_lost_confirmation_is_not_replayed_or_reused() {
        let (pci, mut remote, _) = setup().await;
        let running = tokio::spawn({
            let pci = pci.clone();
            async move { pci.set_key_function_indicators(5, [0; kfi::COUNT]).await }
        });
        let request = line(&mut remote).await;
        assert_eq!(&request[..request.len() - 2], b"\\460500A3FF00090A");
        let code = request[request.len() - 2];
        assert!(pci.state.lock().unwrap().pending.is_empty());

        // The unit ACK can precede the PCI confirmation. Losing the latter
        // leaves this exact-once stateful write uncertain; it must never be
        // replayed merely to obtain another confirmation.
        reply(&mut remote, 5, &[0x32, 0xff, 0x00]).await;
        tokio::time::advance(REPLY_TIMEOUT - Duration::from_millis(1)).await;
        tokio::task::yield_now().await;
        tokio::select! {
            unexpected = line(&mut remote) => {
                panic!("KFI write was replayed after lost confirmation: {unexpected:?}")
            }
            _ = tokio::time::sleep(Duration::from_millis(1)) => {}
        }
        tokio::task::yield_now().await;
        assert_eq!(
            running.await.unwrap().unwrap_err().kind(),
            ErrorKind::TimedOut
        );
        assert!(pci.programming_fault.load(Ordering::Acquire));
        {
            let state = pci.state.lock().unwrap();
            assert!(state.pending.is_empty());
            assert!(state.quarantined_codes.contains(&code));
        }

        // A late confirmation and duplicate untagged ACK cannot satisfy the
        // next identical write. The uncertain transaction has faulted the
        // programming lane until a reconnect establishes a clean boundary.
        remote.get_mut().write_all(&[code, b'.']).await.unwrap();
        reply(&mut remote, 5, &[0x32, 0xff, 0x00]).await;
        tokio::task::yield_now().await;
        let error = pci
            .set_key_function_indicators(5, [1; kfi::COUNT])
            .await
            .unwrap_err();
        assert!(error.to_string().contains("reconnect"));
        tokio::select! {
            unexpected = line(&mut remote) => {
                panic!("late KFI responses advanced a new sequence: {unexpected:?}")
            }
            _ = tokio::time::sleep(Duration::from_millis(1)) => {}
        }
    }

    #[tokio::test(start_paused = true)]
    async fn kfiget_reply_before_lost_confirmation_does_not_replay_identify() {
        let (pci, mut remote, _) = setup().await;
        let running = tokio::spawn({
            let pci = pci.clone();
            async move { pci.get_key_function_indicators(5).await }
        });
        let _code = drive_kfi_get_preamble(&mut remote, 5).await;
        kfi_reply(&mut remote, 5, [0x21, 0x43, 0x65, 0x87]).await;
        assert!(pci.state.lock().unwrap().pending.is_empty());

        tokio::time::advance(REPLY_TIMEOUT - Duration::from_millis(1)).await;
        tokio::task::yield_now().await;
        tokio::select! {
            unexpected = line(&mut remote) => {
                panic!("KFIGET IDENTIFY was replayed after lost confirmation: {unexpected:?}")
            }
            _ = tokio::time::sleep(Duration::from_millis(1)) => {}
        }
        tokio::task::yield_now().await;
        assert_eq!(
            running.await.unwrap().unwrap_err().kind(),
            ErrorKind::TimedOut
        );
        assert!(pci.programming_fault.load(Ordering::Acquire));
    }

    #[tokio::test(start_paused = true)]
    async fn edlt_label_clear_requires_confirmation_and_source_tagged_ack() {
        let (pci, mut remote, mut events) = setup().await;
        let worker = pci.clone();
        let clear = tokio::spawn(async move { worker.clear_edlt_dynamic_labels(5).await });
        let request = line(&mut remote).await;
        assert_eq!(&request[..request.len() - 2], b"\\46050900A4FF43C1EA1B");
        let code = request[request.len() - 2];

        // A foreign ACK and unrelated lighting traffic must not complete or
        // disappear into the programming transaction.
        reply(&mut remote, 4, &[0x32, 0xff, 0x43]).await;
        remote
            .get_mut()
            .write_all(b"05043800790145\r\n")
            .await
            .unwrap();
        remote.get_mut().write_all(&[code, b'.']).await.unwrap();
        assert!(!clear.is_finished());
        reply(&mut remote, 5, &[0x32, 0xff, 0x43]).await;
        clear.await.unwrap().unwrap();
        assert!(matches!(
            events.recv().await,
            Some(CBusEvent::LightingOn {
                source: Some(4),
                app: 56,
                group: 1
            })
        ));
        assert_eq!(
            pci.clear_edlt_dynamic_labels(0).await.unwrap_err().kind(),
            ErrorKind::InvalidInput
        );
    }

    #[tokio::test(start_paused = true)]
    async fn edlt_factory_default_requires_confirmation_and_source_tagged_ack() {
        let (pci, mut remote, mut events) = setup().await;
        let worker = pci.clone();
        let reset = tokio::spawn(async move { worker.factory_default_edlt(5).await });
        let request = line(&mut remote).await;
        assert_eq!(&request[..request.len() - 2], b"\\46050900A4FF43B2B262");
        let code = request[request.len() - 2];

        // A foreign ACK and unrelated application traffic must not complete
        // or disappear into this destructive programming transaction.
        reply(&mut remote, 4, &[0x32, 0xff, 0x43]).await;
        remote
            .get_mut()
            .write_all(b"05043800790145\r\n")
            .await
            .unwrap();
        remote.get_mut().write_all(&[code, b'.']).await.unwrap();
        assert!(!reset.is_finished());
        reply(&mut remote, 5, &[0x32, 0xff, 0x43]).await;
        reset.await.unwrap().unwrap();
        assert!(matches!(
            events.recv().await,
            Some(CBusEvent::LightingOn {
                source: Some(4),
                app: 56,
                group: 1
            })
        ));
        assert_eq!(
            pci.factory_default_edlt(255).await.unwrap_err().kind(),
            ErrorKind::InvalidInput
        );
    }

    #[tokio::test(start_paused = true)]
    async fn label_clear_all_uses_native_cal_and_only_its_confirmation() {
        let (pci, mut remote, _) = setup().await;
        let worker = pci.clone();
        let clear = tokio::spawn(async move { worker.clear_dynamic_label_cache(5, None).await });
        let request = line(&mut remote).await;
        assert_eq!(&request[..request.len() - 2], b"\\460500A3FF0027EC");
        let code = request[request.len() - 2];

        // Another command's confirmation does not complete this transaction.
        // The correlated PCI confirmation does, without a unit response or
        // readback.
        let foreign = if code == b'h' { b'i' } else { b'h' };
        remote.get_mut().write_all(&[foreign, b'.']).await.unwrap();
        assert!(!clear.is_finished());
        remote.get_mut().write_all(&[code, b'.']).await.unwrap();
        clear.await.unwrap().unwrap();
        assert!(!pci.programming_fault.load(Ordering::Acquire));
    }

    #[tokio::test(start_paused = true)]
    async fn keyed_label_clear_hash_completes_and_keeps_lane_usable() {
        let (pci, mut remote, _) = setup().await;
        let worker = pci.clone();
        let clear = tokio::spawn(async move { worker.clear_dynamic_label_cache(5, Some(8)).await });
        let request = line(&mut remote).await;
        assert_eq!(&request[..request.len() - 2], b"\\460500A4FF006608A4");
        let code = request[request.len() - 2];
        remote.get_mut().write_all(&[code, b'#']).await.unwrap();
        clear.await.unwrap().unwrap();
        assert!(!pci.programming_fault.load(Ordering::Acquire));
        assert!(pci.state.lock().unwrap().pending.is_empty());

        let worker = pci.clone();
        let next = tokio::spawn(async move { worker.clear_dynamic_label_cache(5, None).await });
        let request = line(&mut remote).await;
        let code = request[request.len() - 2];
        remote.get_mut().write_all(&[code, b'.']).await.unwrap();
        next.await.unwrap().unwrap();
    }

    #[tokio::test(start_paused = true)]
    async fn label_clear_rejects_invalid_key_before_io() {
        let (pci, mut remote, _) = setup().await;
        for key in [0, 9, u8::MAX] {
            assert_eq!(
                pci.clear_dynamic_label_cache(5, Some(key))
                    .await
                    .unwrap_err()
                    .kind(),
                ErrorKind::InvalidInput
            );
        }
        tokio::select! {
            unexpected = line(&mut remote) => {
                panic!("invalid label-clear key wrote to PCI: {unexpected:?}")
            }
            _ = tokio::time::sleep(Duration::from_millis(1)) => {}
        }
        assert!(!pci.programming_fault.load(Ordering::Acquire));
    }

    #[tokio::test(start_paused = true)]
    async fn lost_label_clear_confirmation_is_not_replayed_and_faults_lane() {
        let (pci, mut remote, _) = setup().await;
        let worker = pci.clone();
        let clear = tokio::spawn(async move { worker.clear_dynamic_label_cache(5, Some(1)).await });
        let request = line(&mut remote).await;
        let code = request[request.len() - 2];
        assert!(pci.state.lock().unwrap().pending.is_empty());

        tokio::time::advance(REPLY_TIMEOUT - Duration::from_millis(1)).await;
        tokio::task::yield_now().await;
        tokio::select! {
            unexpected = line(&mut remote) => {
                panic!("label clear was replayed after lost confirmation: {unexpected:?}")
            }
            _ = tokio::time::sleep(Duration::from_millis(1)) => {}
        }
        tokio::task::yield_now().await;
        assert_eq!(
            clear.await.unwrap().unwrap_err().kind(),
            ErrorKind::TimedOut
        );
        assert!(pci.programming_fault.load(Ordering::Acquire));
        {
            let state = pci.state.lock().unwrap();
            assert!(state.pending.is_empty());
            assert!(state.quarantined_codes.contains(&code));
        }
        assert!(pci
            .clear_dynamic_label_cache(5, None)
            .await
            .unwrap_err()
            .to_string()
            .contains("needs reconnect"));
    }

    #[tokio::test(start_paused = true)]
    async fn label_clear_response_stream_loss_faults_lane() {
        let (pci, mut remote, _) = setup().await;
        let worker = pci.clone();
        let clear = tokio::spawn(async move { worker.clear_dynamic_label_cache(5, None).await });
        let _request = line(&mut remote).await;
        drop(remote);
        assert_eq!(
            clear.await.unwrap().unwrap_err().kind(),
            ErrorKind::BrokenPipe
        );
        assert!(pci.programming_fault.load(Ordering::Acquire));
        assert!(pci
            .clear_dynamic_label_cache(5, None)
            .await
            .unwrap_err()
            .to_string()
            .contains("needs reconnect"));
    }

    async fn selected_serial_reply(
        remote: &mut BufReader<tokio::io::DuplexStream>,
        source: u8,
        local: u8,
        serial: [u8; 4],
        tail: [u8; 2],
    ) {
        let mut bytes = vec![0x86, source, local, 0x00, 0x87, 0x00];
        bytes.extend_from_slice(&serial);
        bytes.extend_from_slice(&tail);
        let sum = bytes.iter().fold(0u8, |acc, byte| acc.wrapping_add(*byte));
        bytes.push(0u8.wrapping_sub(sum));
        let mut wire = hex::encode_upper(bytes).into_bytes();
        wire.extend_from_slice(b"\r\n");
        remote.get_mut().write_all(&wire).await.unwrap();
    }

    #[tokio::test(start_paused = true)]
    async fn selected_serial_address_is_exact_once_correlated_and_quiet_bounded() {
        let (pci, mut remote, mut events) = setup().await;
        pci.set_local_unit_hint(16).unwrap();
        let worker = pci.clone();
        let selected =
            tokio::spawn(async move { worker.address_selected_serial("101136.1558", 6).await });
        let request = line(&mut remote).await;
        assert_eq!(&request[..request.len() - 2], b"\\05FF000F0018B106160615ED");
        let code = request[request.len() - 2];
        remote.get_mut().write_all(&[code, b'.']).await.unwrap();
        remote
            .get_mut()
            .write_all(b"05043800790145\r\n")
            .await
            .unwrap();
        selected_serial_reply(&mut remote, 6, 16, [0x18, 0xb1, 0x06, 0x16], [0xfa, 0xce]).await;
        let accepted = selected.await.unwrap().unwrap();
        assert_eq!(accepted.serial, "101136.1558");
        assert_eq!(accepted.destination, 6);
        assert_eq!(accepted.local_unit, 16);
        assert_eq!(accepted.opaque_tail, [0xfa, 0xce]);
        assert!(matches!(
            events.recv().await,
            Some(CBusEvent::LightingOn {
                source: Some(4),
                app: 56,
                group: 1
            })
        ));
        assert_eq!(
            pci.address_selected_serial("0.0", 6)
                .await
                .unwrap_err()
                .kind(),
            ErrorKind::InvalidInput
        );
    }

    async fn assert_exact_selected_serial_plan_request(
        command_checksum: bool,
        expected_request: &[u8],
    ) {
        let (pci, mut remote, _) = setup().await;
        pci.set_local_unit_hint(16).unwrap();
        let encoded = encode_serial_address("101136.1558", 6, command_checksum, b'g').unwrap();
        assert_eq!(encoded, expected_request);

        let worker = pci.clone();
        let supplied = encoded.clone();
        let selected = tokio::spawn(async move {
            worker
                .send_selected_serial_plan_once("101136.1558", 6, command_checksum, b'g', &supplied)
                .await
        });
        assert_eq!(line(&mut remote).await, encoded);
        remote.get_mut().write_all(b"g.").await.unwrap();
        selected_serial_reply(&mut remote, 6, 16, [0x18, 0xb1, 0x06, 0x16], [0xfa, 0xce]).await;

        let evidence = selected.await.unwrap().unwrap();
        assert_eq!(evidence.request, encoded);
        assert!(evidence.send_completed);
        assert!(evidence.receipt_matched);
        assert!(evidence.confirmation_observed);
        assert!(evidence.receipt_observed);
        assert!(
            tokio::time::timeout(Duration::from_millis(25), line(&mut remote))
                .await
                .is_err(),
            "an exact selected-serial request must never be replayed"
        );
    }

    #[tokio::test(start_paused = true)]
    async fn exact_selected_serial_plan_request_without_command_checksum_is_sent_once() {
        assert_exact_selected_serial_plan_request(false, b"\\05FF000F0018B106160615g\r").await;
    }

    #[tokio::test(start_paused = true)]
    async fn exact_selected_serial_plan_request_with_command_checksum_is_sent_once() {
        assert_exact_selected_serial_plan_request(true, b"\\05FF000F0018B106160615EDg\r").await;
    }

    #[tokio::test(start_paused = true)]
    async fn exact_selected_serial_plan_request_refuses_busy_confirmation_before_write() {
        let (pci, mut remote, _) = setup().await;
        pci.set_local_unit_hint(16).unwrap();
        assert_eq!(pci.allocate_exact_confirmation(b'g').unwrap().0, b'g');
        let expected = encode_serial_address("101136.1558", 6, true, b'g').unwrap();

        let error = pci
            .send_selected_serial_plan_once("101136.1558", 6, true, b'g', &expected)
            .await
            .unwrap_err();
        assert_eq!(error.kind(), ErrorKind::WouldBlock);
        assert!(error
            .to_string()
            .contains("requested confirmation code is already reserved"));
        assert!(
            tokio::time::timeout(Duration::from_millis(25), line(&mut remote))
                .await
                .is_err(),
            "a busy fixed confirmation code must refuse before writing"
        );
        assert!(!pci.programming_fault.load(Ordering::Acquire));
        PciClient::release_confirmation(&mut pci.state.lock().unwrap(), b'g');
    }

    #[tokio::test(start_paused = true)]
    async fn selected_serial_plan_cancelled_queued_write_releases_code_without_sending() {
        let (pci, mut remote, _) = setup().await;
        pci.set_local_unit_hint(16).unwrap();
        let expected = encode_serial_address("101136.1558", 6, true, b'g').unwrap();
        let held_writer = pci.writer.lock().await;
        let worker = pci.clone();
        let supplied = expected.clone();
        let sending = tokio::spawn(async move {
            worker
                .send_selected_serial_plan_once("101136.1558", 6, true, b'g', &supplied)
                .await
        });
        for _ in 0..16 {
            if pci
                .state
                .lock()
                .unwrap()
                .active_allocations
                .contains_key(&b'g')
            {
                break;
            }
            tokio::task::yield_now().await;
        }
        assert!(pci
            .state
            .lock()
            .unwrap()
            .active_allocations
            .contains_key(&b'g'));

        sending.abort();
        assert!(sending.await.unwrap_err().is_cancelled());
        {
            let state = pci.state.lock().unwrap();
            assert!(!state.codes_in_use.contains_key(&b'g'));
            assert!(!state.active_allocations.contains_key(&b'g'));
            assert!(!state.allocation_ids.contains_key(&b'g'));
            assert!(!state.quarantined_codes.contains(&b'g'));
        }
        assert!(!pci.programming_fault.load(Ordering::Acquire));
        assert!(pci.programming_lane.try_lock().is_ok());
        let (code, _) = pci.allocate_exact_confirmation(b'g').unwrap();
        assert_eq!(code, b'g');
        PciClient::release_confirmation(&mut pci.state.lock().unwrap(), b'g');

        drop(held_writer);
        tokio::time::advance(Duration::from_secs(15)).await;
        tokio::task::yield_now().await;
        assert!(
            tokio::time::timeout(Duration::from_millis(25), line(&mut remote))
                .await
                .is_err(),
            "a cancelled queued selected-serial write must never reach the transport"
        );
    }

    #[tokio::test(start_paused = true)]
    async fn selected_serial_plan_cancelled_started_write_faults_and_disconnects() {
        let (pci, mut remote, gate) = setup_with_blocking_writer().await;
        pci.set_local_unit_hint(16).unwrap();
        let expected = encode_serial_address("101136.1558", 6, true, b'g').unwrap();
        gate.blocked
            .store(true, std::sync::atomic::Ordering::Release);
        let worker = pci.clone();
        let supplied = expected.clone();
        let sending = tokio::spawn(async move {
            worker
                .send_selected_serial_plan_once("101136.1558", 6, true, b'g', &supplied)
                .await
        });
        gate.started.notified().await;

        sending.abort();
        assert!(sending.await.unwrap_err().is_cancelled());
        assert!(pci.programming_fault.load(Ordering::Acquire));
        {
            let state = pci.state.lock().unwrap();
            assert!(state.codes_in_use.contains_key(&b'g'));
            assert!(state.quarantined_codes.contains(&b'g'));
            assert!(!state.active_allocations.contains_key(&b'g'));
        }
        assert_eq!(
            pci.allocate_exact_confirmation(b'g').unwrap_err().kind(),
            ErrorKind::WouldBlock
        );

        gate.blocked
            .store(false, std::sync::atomic::Ordering::Release);
        if let Some(waker) = gate.waker.lock().unwrap().take() {
            waker.wake();
        }
        pci.shutdown().await;
        assert!(line(&mut remote).await.is_empty());
        tokio::time::advance(Duration::from_secs(15)).await;
        tokio::task::yield_now().await;
        assert!(line(&mut remote).await.is_empty());
    }

    #[tokio::test]
    async fn selected_serial_started_cancellation_closes_cni_before_reconnect() {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let (initialized_tx, initialized_rx) = tokio::sync::oneshot::channel();
        let (eof_tx, eof_rx) = tokio::sync::oneshot::channel();
        let server = tokio::spawn(async move {
            let (first, _) = listener.accept().await.unwrap();
            let mut first = BufReader::new(first);
            for _ in 0..8 {
                let mut request = Vec::new();
                assert_ne!(first.read_until(b'\r', &mut request).await.unwrap(), 0);
            }
            initialized_tx.send(()).unwrap();
            let mut trailing = Vec::new();
            first.read_to_end(&mut trailing).await.unwrap();
            assert!(
                trailing.is_empty(),
                "started cancellation must cancel the blocked address write"
            );
            eof_tx.send(()).unwrap();
            listener.accept().await.unwrap()
        });

        let first = tokio::net::TcpStream::connect(address).await.unwrap();
        let (reader, writer) = first.into_split();
        let gate = Arc::new(SelectedSerialWriteGate::default());
        let writer = SelectedSerialBlockingWriter {
            inner: Box::new(writer),
            gate: gate.clone(),
        };
        let (events, _events_rx) = mpsc::unbounded_channel();
        let pci = PciClient::new(Box::new(reader), Box::new(writer), events);
        pci.pci_reset().await.unwrap();
        initialized_rx.await.unwrap();
        pci.set_local_unit_hint(16).unwrap();

        gate.blocked
            .store(true, std::sync::atomic::Ordering::Release);
        let expected = encode_serial_address("101136.1558", 6, true, b'g').unwrap();
        let worker = pci.clone();
        let sending = tokio::spawn(async move {
            worker
                .send_selected_serial_plan_once("101136.1558", 6, true, b'g', &expected)
                .await
        });
        gate.started.notified().await;
        sending.abort();
        assert!(sending.await.unwrap_err().is_cancelled());

        // The cancellation guard signals shutdown automatically; awaiting it
        // makes the close deterministic before another single-client session.
        pci.shutdown().await;
        pci.shutdown().await;
        eof_rx.await.unwrap();
        let second = tokio::net::TcpStream::connect(address).await.unwrap();
        let (_accepted, _) = server.await.unwrap();
        drop(second);
    }

    #[tokio::test(start_paused = true)]
    async fn exact_selected_serial_plan_missing_confirmation_is_unmatched_and_quarantined() {
        let (pci, mut remote, _) = setup().await;
        pci.set_local_unit_hint(16).unwrap();
        let expected = encode_serial_address("101136.1558", 6, false, b'g').unwrap();
        let worker = pci.clone();
        let supplied = expected.clone();
        let selected = tokio::spawn(async move {
            worker
                .send_selected_serial_plan_once("101136.1558", 6, false, b'g', &supplied)
                .await
        });
        assert_eq!(line(&mut remote).await, expected);
        let evidence = selected.await.unwrap().unwrap();
        assert!(evidence.send_completed);
        assert!(!evidence.receipt_matched);
        assert!(!evidence.confirmation_observed);
        assert!(!evidence.receipt_observed);
        assert!(!pci.disconnected.load(Ordering::Acquire));
        {
            let state = pci.state.lock().unwrap();
            assert!(state.codes_in_use.contains_key(&b'g'));
            assert!(state.quarantined_codes.contains(&b'g'));
        }
        assert_eq!(
            pci.allocate_exact_confirmation(b'g').unwrap_err().kind(),
            ErrorKind::WouldBlock
        );
    }

    #[tokio::test(start_paused = true)]
    async fn selected_serial_ambiguous_receipt_faults_lane_without_replay() {
        let (pci, mut remote, _) = setup().await;
        pci.set_local_unit_hint(16).unwrap();
        let worker = pci.clone();
        let selected =
            tokio::spawn(async move { worker.address_selected_serial("101136.1558", 6).await });
        let request = line(&mut remote).await;
        let code = request[request.len() - 2];
        selected_serial_reply(&mut remote, 6, 16, [0x18, 0xb1, 0x06, 0x16], [0, 0]).await;
        remote.get_mut().write_all(&[code, b'.']).await.unwrap();
        assert!(selected
            .await
            .unwrap()
            .unwrap_err()
            .to_string()
            .contains("preceded"));
        assert!(pci
            .recall_parameter(5, 1, 1)
            .await
            .unwrap_err()
            .to_string()
            .contains("needs reconnect"));
    }

    #[tokio::test(start_paused = true)]
    async fn selected_serial_definite_pci_rejection_keeps_lane_usable() {
        let (pci, mut remote, _) = setup().await;
        pci.set_local_unit_hint(16).unwrap();
        let worker = pci.clone();
        let selected =
            tokio::spawn(async move { worker.address_selected_serial("101136.1558", 6).await });
        let request = line(&mut remote).await;
        let code = request[request.len() - 2];
        remote.get_mut().write_all(&[code, b'#']).await.unwrap();
        assert!(selected
            .await
            .unwrap()
            .unwrap_err()
            .to_string()
            .contains("PCI rejected"));

        let worker = pci.clone();
        let recall = tokio::spawn(async move { worker.recall_parameter(5, 1, 1).await });
        assert_eq!(line(&mut remote).await, b"\\4605001A010199\r");
        reply(&mut remote, 5, &[0x82, 1, 9]).await;
        assert_eq!(recall.await.unwrap().unwrap(), vec![9]);
    }

    #[tokio::test(start_paused = true)]
    async fn selected_serial_receipt_then_pci_error_faults_lane_without_replay() {
        let (pci, mut remote, _) = setup().await;
        pci.set_local_unit_hint(16).unwrap();
        let worker = pci.clone();
        let selected =
            tokio::spawn(async move { worker.address_selected_serial("101136.1558", 6).await });
        let request = line(&mut remote).await;
        let code = request[request.len() - 2];
        remote.get_mut().write_all(&[code, b'.']).await.unwrap();
        selected_serial_reply(&mut remote, 6, 16, [0x18, 0xb1, 0x06, 0x16], [0, 0]).await;
        remote.get_mut().write_all(b"!").await.unwrap();
        assert!(selected
            .await
            .unwrap()
            .unwrap_err()
            .to_string()
            .contains("receipt followed by PCI error"));
        assert!(pci
            .recall_parameter(5, 1, 1)
            .await
            .unwrap_err()
            .to_string()
            .contains("needs reconnect"));
    }

    #[tokio::test(start_paused = true)]
    async fn definitive_edlt_factory_default_nak_keeps_programming_lane_usable() {
        let (pci, mut remote, _) = setup().await;
        let worker = pci.clone();
        let reset = tokio::spawn(async move { worker.factory_default_edlt(5).await });
        let request = line(&mut remote).await;
        let code = request[request.len() - 2];
        remote.get_mut().write_all(&[code, b'.']).await.unwrap();
        reply(&mut remote, 5, &[0x3b, 0xff, 0x43]).await;
        assert!(reset
            .await
            .unwrap()
            .unwrap_err()
            .to_string()
            .contains("unit rejected"));

        let worker = pci.clone();
        let recall = tokio::spawn(async move { worker.recall_parameter(5, 1, 1).await });
        assert_eq!(line(&mut remote).await, b"\\4605001A010199\r");
        reply(&mut remote, 5, &[0x82, 1, 9]).await;
        assert_eq!(recall.await.unwrap().unwrap(), vec![9]);
    }

    #[tokio::test(start_paused = true)]
    async fn definitive_edlt_label_clear_nak_keeps_programming_lane_usable() {
        let (pci, mut remote, _) = setup().await;
        let worker = pci.clone();
        let clear = tokio::spawn(async move { worker.clear_edlt_dynamic_labels(5).await });
        let request = line(&mut remote).await;
        let code = request[request.len() - 2];
        remote.get_mut().write_all(&[code, b'.']).await.unwrap();
        reply(&mut remote, 5, &[0x3b, 0xff, 0x43]).await;
        assert!(clear
            .await
            .unwrap()
            .unwrap_err()
            .to_string()
            .contains("unit rejected"));

        let worker = pci.clone();
        let recall = tokio::spawn(async move { worker.recall_parameter(5, 1, 1).await });
        assert_eq!(line(&mut remote).await, b"\\4605001A010199\r");
        reply(&mut remote, 5, &[0x82, 1, 9]).await;
        assert_eq!(recall.await.unwrap().unwrap(), vec![9]);
    }

    #[tokio::test(start_paused = true)]
    async fn lost_edlt_label_clear_ack_is_not_retried_and_faults_programming_lane() {
        let (pci, mut remote, _) = setup().await;
        let worker = pci.clone();
        let clear = tokio::spawn(async move { worker.clear_edlt_dynamic_labels(5).await });
        let request = line(&mut remote).await;
        let code = request[request.len() - 2];
        remote.get_mut().write_all(&[code, b'.']).await.unwrap();
        assert!(
            tokio::time::timeout(Duration::from_secs(5), line(&mut remote))
                .await
                .is_err()
        );
        assert_eq!(
            clear.await.unwrap().unwrap_err().kind(),
            ErrorKind::TimedOut
        );
        assert!(pci.programming_fault.load(Ordering::Acquire));
        assert!(pci.state.lock().unwrap().pending.is_empty());
        assert!(pci
            .recall_parameter(5, 1, 1)
            .await
            .unwrap_err()
            .to_string()
            .contains("needs reconnect"));
    }

    #[tokio::test(start_paused = true)]
    async fn memory_read_matches_source_and_assembles_fragments_without_stealing_mqtt() {
        let (pci, mut remote, mut events) = setup().await;
        let read = tokio::spawn(async move { pci.read_memory(5, 0x10000, 33).await });
        assert_eq!(line(&mut remote).await, b"\\46050900A6004100000100C4\r");
        reply(&mut remote, 4, &[0x32, 0, 0x41]).await;
        reply(&mut remote, 5, &[0x32, 0, 0x41]).await;
        assert_eq!(line(&mut remote).await, b"\\460509001A012170\r");
        // A real lighting event interleaved with CAL traffic still reaches MQTT.
        remote
            .get_mut()
            .write_all(b"05043800790145\r\n")
            .await
            .unwrap();
        reply(&mut remote, 4, &[0x82, 1, 0xff]).await;
        for range in [0..16, 16..32, 32..33] {
            let mut cal = vec![0x80 | (range.len() as u8 + 1), 1];
            cal.extend(range);
            reply(&mut remote, 5, &cal).await;
        }
        assert_eq!(read.await.unwrap().unwrap(), (0..33).collect::<Vec<u8>>());
        assert!(matches!(
            events.recv().await,
            Some(CBusEvent::LightingOn {
                source: Some(4),
                app: 56,
                group: 1
            })
        ));
    }

    #[tokio::test(start_paused = true)]
    async fn standard_parameter_recall_uses_declared_parameter_and_exact_length() {
        let (pci, mut remote, _) = setup().await;
        let worker = pci.clone();
        let read = tokio::spawn(async move { worker.recall_parameter(5, 0x22, 3).await });
        assert_eq!(line(&mut remote).await, b"\\4605001A220376\r");
        reply(&mut remote, 4, &[0x83, 0x22, 9, 9]).await;
        reply(&mut remote, 5, &[0x82, 0x22, 1]).await;
        reply(&mut remote, 5, &[0x83, 0x22, 2, 3]).await;
        assert_eq!(read.await.unwrap().unwrap(), vec![1, 2, 3]);
        assert_eq!(
            pci.recall_parameter(5, 1, 0).await.unwrap_err().kind(),
            ErrorKind::InvalidInput
        );
        assert_eq!(
            pci.recall_parameter(5, 1, 256).await.unwrap_err().kind(),
            ErrorKind::InvalidInput
        );
    }

    #[tokio::test(start_paused = true)]
    async fn edlt_widget_groups_uses_captured_oem_route_and_fragmentation() {
        let (pci, mut remote, _) = setup().await;
        let worker = pci.clone();
        let read = tokio::spawn(async move { worker.read_edlt_widget_groups(5).await });
        assert_eq!(line(&mut remote).await, b"\\460509001AFA2C6C\r");

        // Retained physical capture: the KEYGL5 repeats parameter FA across
        // three replies carrying 16, 16, and 12 bytes respectively.
        let values = hex::decode(
            "FFFFFFFFFFFFFFFFFFFFFFFF381B381938213818FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF",
        )
        .unwrap();
        assert_eq!(values.len(), cbus_protocol::edlt_widget_groups::LENGTH);
        let wrong_source = Cal::Reply {
            parameter: cbus_protocol::edlt_widget_groups::PARAMETER,
            data: values[..16].to_vec(),
        }
        .encode();
        reply(&mut remote, 4, &wrong_source).await;
        let wrong_parameter = Cal::Reply {
            parameter: 0xfb,
            data: values[..16].to_vec(),
        }
        .encode();
        reply(&mut remote, 5, &wrong_parameter).await;
        tokio::task::yield_now().await;
        assert!(!read.is_finished());

        let first = Cal::Reply {
            parameter: cbus_protocol::edlt_widget_groups::PARAMETER,
            data: values[..16].to_vec(),
        }
        .encode();
        assert_eq!(
            hex::encode_upper(&first),
            "91FAFFFFFFFFFFFFFFFFFFFFFFFF381B3819"
        );
        reply(&mut remote, 5, &first).await;
        tokio::task::yield_now().await;
        assert!(!read.is_finished(), "a short matching reply is incomplete");

        let second = Cal::Reply {
            parameter: cbus_protocol::edlt_widget_groups::PARAMETER,
            data: values[16..32].to_vec(),
        }
        .encode();
        assert_eq!(
            hex::encode_upper(&second),
            "91FA38213818FFFFFFFFFFFFFFFFFFFFFFFF"
        );
        reply(&mut remote, 5, &second).await;
        tokio::task::yield_now().await;
        assert!(!read.is_finished(), "32 matching bytes are incomplete");

        let third = Cal::Reply {
            parameter: cbus_protocol::edlt_widget_groups::PARAMETER,
            data: values[32..].to_vec(),
        }
        .encode();
        assert_eq!(hex::encode_upper(&third), "8DFAFFFFFFFFFFFFFFFFFFFFFFFF");
        reply(&mut remote, 5, &third).await;
        assert_eq!(
            read.await.unwrap().unwrap(),
            values
                .iter()
                .map(u8::to_string)
                .collect::<Vec<_>>()
                .join(",")
        );
    }

    #[tokio::test(start_paused = true)]
    async fn edlt_extended_firmware_uses_oem_fb_9_and_native_nul_projection() {
        let (pci, mut remote, _) = setup().await;
        let worker = pci.clone();
        let read = tokio::spawn(async move { worker.read_edlt_extended_firmware(5).await });
        assert_eq!(line(&mut remote).await, b"\\460509001AFB098E\r");

        reply(&mut remote, 4, &[0x85, 0xfb, b'w', b'r', b'o', b'n']).await;
        reply(&mut remote, 5, &[0x84, 0xfa, b'w', b'r', b'o']).await;
        tokio::task::yield_now().await;
        assert!(!read.is_finished());

        reply(&mut remote, 5, &[0x85, 0xfb, b'0', b'1', b'.', b'0']).await;
        reply(&mut remote, 5, &[0x86, 0xfb, b'5', b'.', b'0', b'0', 0]).await;
        assert_eq!(read.await.unwrap().unwrap(), "01.05.00");
    }

    #[tokio::test(start_paused = true)]
    async fn edlt_applications_select_address_16_once_and_correlate_both_phases() {
        let (pci, mut remote, _) = setup().await;
        let worker = pci.clone();
        let read = tokio::spawn(async move { worker.read_edlt_applications(5).await });
        assert_eq!(line(&mut remote).await, b"\\46050900A400411000B7\r");

        reply(&mut remote, 4, &[0x32, 0, 0x41]).await;
        reply(&mut remote, 5, &[0x32, 0, 0x42]).await;
        tokio::task::yield_now().await;
        assert!(!read.is_finished());
        reply(&mut remote, 5, &[0x32, 0, 0x41]).await;

        assert_eq!(line(&mut remote).await, b"\\460509001A01028F\r");
        reply(&mut remote, 4, &[0x82, 1, 99]).await;
        reply(&mut remote, 5, &[0x82, 2, 88]).await;
        tokio::task::yield_now().await;
        assert!(!read.is_finished());
        reply(&mut remote, 5, &[0x82, 1, 56]).await;
        tokio::task::yield_now().await;
        assert!(!read.is_finished());
        reply(&mut remote, 5, &[0x82, 1, 255]).await;
        assert_eq!(read.await.unwrap().unwrap(), [56, 255]);
    }

    #[tokio::test(start_paused = true)]
    async fn edlt_application_recall_timeout_does_not_replay_and_faults_lane() {
        let (pci, mut remote, _) = setup().await;
        let worker = pci.clone();
        let read = tokio::spawn(async move { worker.read_edlt_applications(5).await });
        assert_eq!(line(&mut remote).await, b"\\46050900A400411000B7\r");
        reply(&mut remote, 5, &[0x32, 0, 0x41]).await;
        assert_eq!(line(&mut remote).await, b"\\460509001A01028F\r");
        tokio::time::advance(REPLY_TIMEOUT).await;
        tokio::task::yield_now().await;
        assert_eq!(read.await.unwrap().unwrap_err().kind(), ErrorKind::TimedOut);
        assert!(pci.programming_fault.load(Ordering::Acquire));
        assert!(pci
            .read_edlt_extended_firmware(5)
            .await
            .unwrap_err()
            .to_string()
            .contains("needs reconnect"));
        assert!(
            tokio::time::timeout(Duration::from_secs(1), line(&mut remote))
                .await
                .is_err(),
            "neither phase may be replayed after an incomplete recall"
        );
    }

    #[tokio::test(start_paused = true)]
    async fn edlt_widget_groups_timeout_does_not_replay_and_faults_programming_lane() {
        let (pci, mut remote, _) = setup().await;
        let worker = pci.clone();
        let read = tokio::spawn(async move { worker.read_edlt_widget_groups(5).await });
        assert_eq!(line(&mut remote).await, b"\\460509001AFA2C6C\r");
        tokio::time::advance(REPLY_TIMEOUT).await;
        tokio::task::yield_now().await;
        assert_eq!(read.await.unwrap().unwrap_err().kind(), ErrorKind::TimedOut);
        assert!(pci.programming_fault.load(Ordering::Acquire));
        assert!(pci
            .read_edlt_widget_groups(5)
            .await
            .unwrap_err()
            .to_string()
            .contains("needs reconnect"));
        assert!(
            tokio::time::timeout(Duration::from_secs(1), line(&mut remote))
                .await
                .is_err(),
            "the incomplete read must not be replayed"
        );
    }

    #[tokio::test(start_paused = true)]
    async fn paged_recall_carries_page_and_splits_at_page_boundary() {
        let (pci, mut remote, _) = setup().await;
        let worker = pci.clone();
        let read = tokio::spawn(async move { worker.recall_paged_parameter(5, 0x01fe, 4).await });
        assert_eq!(line(&mut remote).await, b"\\4605001B01FE02\r");
        reply(&mut remote, 5, &[0x83, 0xfe, 1, 2]).await;
        assert_eq!(line(&mut remote).await, b"\\4605001B020002\r");
        reply(&mut remote, 4, &[0x83, 0, 9, 9]).await;
        reply(&mut remote, 5, &[0x83, 0, 3, 4]).await;
        assert_eq!(read.await.unwrap().unwrap(), vec![1, 2, 3, 4]);
        assert_eq!(
            pci.recall_paged_parameter(5, 0, 0)
                .await
                .unwrap_err()
                .kind(),
            ErrorKind::InvalidInput
        );
    }

    #[tokio::test(start_paused = true)]
    async fn locked_paged_store_selects_each_page_unlocks_and_verifies() {
        let (pci, mut remote, _) = setup().await;
        let worker = pci.clone();
        let write = tokio::spawn(async move {
            worker
                .store_paged_parameter_verified(5, 0x01fe, &[0xaa, 0xbb, 0xcc, 0xdd], true)
                .await
        });

        assert_eq!(line(&mut remote).await, b"\\4605003901\r");
        reply(&mut remote, 5, &[0x81, 1]).await;
        assert_eq!(line(&mut remote).await, b"\\46050011FEh\r");
        reply(&mut remote, 5, &[0x82, 0xfe, 0x5a]).await;
        remote.get_mut().write_all(b"h.\r\n").await.unwrap();
        assert_eq!(line(&mut remote).await, b"\\460500A4FE00AABBAE\r");
        reply(&mut remote, 5, &[0x32, 0xfe, 0]).await;

        assert_eq!(line(&mut remote).await, b"\\4605003902\r");
        reply(&mut remote, 5, &[0x81, 2]).await;
        assert_eq!(line(&mut remote).await, b"\\4605001100i\r");
        reply(&mut remote, 5, &[0x82, 0, 0x5a]).await;
        remote.get_mut().write_all(b"i.\r\n").await.unwrap();
        assert_eq!(line(&mut remote).await, b"\\460500A40001CCDD67\r");
        reply(&mut remote, 5, &[0x32, 0, 1]).await;

        assert_eq!(line(&mut remote).await, b"\\4605001B01FE02\r");
        reply(&mut remote, 5, &[0x83, 0xfe, 0xaa, 0xbb]).await;
        assert_eq!(line(&mut remote).await, b"\\4605001B020002\r");
        reply(&mut remote, 5, &[0x83, 0, 0xcc, 0xdd]).await;
        write.await.unwrap().unwrap();
    }

    #[tokio::test(start_paused = true)]
    async fn standard_parameter_store_is_tagged_direct_and_read_back() {
        let (pci, mut remote, _) = setup().await;
        let worker = pci.clone();
        let data = [0xbe, 0xfd, 0xb1, 0xa3, 0x39, 0x1e];
        let write =
            tokio::spawn(async move { worker.store_parameter_verified(5, 0x2a, &data).await });
        assert_eq!(line(&mut remote).await, b"\\460500A82A00BEFDB1A3391E7D\r");
        reply(&mut remote, 4, &[0x32, 0x2a, 0]).await;
        reply(&mut remote, 5, &[0x32, 0x2a, 0]).await;
        assert_eq!(line(&mut remote).await, b"\\4605001A2A066B\r");
        reply(
            &mut remote,
            5,
            &[0x87, 0x2a, 0xbe, 0xfd, 0xb1, 0xa3, 0x39, 0x1e],
        )
        .await;
        write.await.unwrap().unwrap();
        assert_eq!(
            pci.store_parameter_verified(5, 1, &[])
                .await
                .unwrap_err()
                .kind(),
            ErrorKind::InvalidInput
        );
        assert_eq!(
            pci.store_parameter_verified(5, 255, &[1, 2])
                .await
                .unwrap_err()
                .kind(),
            ErrorKind::InvalidInput
        );
    }

    #[tokio::test(start_paused = true)]
    async fn patch_pipeline_uses_native_tags_verifies_every_write_and_is_idempotent() {
        async fn recall(
            remote: &mut BufReader<tokio::io::DuplexStream>,
            parameter: u8,
            data: &[u8],
        ) {
            let request = line(remote).await;
            assert!(
                request
                    .starts_with(format!("\\4605001A{parameter:02X}{:02X}", data.len()).as_bytes()),
                "{request:?}"
            );
            let mut cal = vec![0x80 | (data.len() as u8 + 1), parameter];
            cal.extend_from_slice(data);
            reply(remote, 5, &cal).await;
        }

        async fn unlock(remote: &mut BufReader<tokio::io::DuplexStream>, parameter: u8) -> u8 {
            let request = line(remote).await;
            assert!(
                request.starts_with(format!("\\46050011{parameter:02X}").as_bytes()),
                "{request:?}"
            );
            let code = request[request.len() - 2];
            let challenge = 0x5a;
            reply(remote, 5, &[0x82, parameter, challenge]).await;
            remote.get_mut().write_all(&[code, b'.']).await.unwrap();
            challenge
        }

        async fn store(
            remote: &mut BufReader<tokio::io::DuplexStream>,
            parameter: u8,
            tag: u8,
            data: &[u8],
            locked: bool,
        ) {
            let challenge = if locked {
                Some(unlock(remote, parameter).await)
            } else {
                None
            };
            let effective_tag = if parameter == 0xf7 {
                challenge.expect("0xF7 must use custom unlock")
            } else {
                tag
            };
            let request = line(remote).await;
            let mut prefix = format!(
                "\\460500A{:X}{parameter:02X}{effective_tag:02X}",
                data.len() + 2
            );
            prefix.push_str(&hex::encode_upper(data));
            assert!(request.starts_with(prefix.as_bytes()), "{request:?}");
            reply(remote, 5, &[0x32, parameter, effective_tag]).await;
            recall(remote, parameter, data).await;
        }

        let (pci, mut remote, _) = setup().await;
        let blocks = vec![
            PatchProgrammingBlock {
                parameter: 0x72,
                data: vec![0xaa, 0xbb],
                unlock: false,
            },
            PatchProgrammingBlock {
                parameter: 0xf7,
                data: vec![0xcc],
                unlock: true,
            },
            PatchProgrammingBlock {
                parameter: 0x80,
                data: vec![0xdd],
                unlock: true,
            },
        ];
        let worker = pci.clone();
        let apply_blocks = blocks.clone();
        let apply = tokio::spawn(async move {
            worker
                .write_patch_verified(5, 0xf2, &[0, 0xff], 1, &apply_blocks)
                .await
        });

        // Explicitly admitted 0xFF recovers a prior interrupted run that
        // reached the native temporary-version phase before reconnect.
        recall(&mut remote, 0xf2, &[0xff]).await;
        store(&mut remote, 0x70, 0x85, &[0xff, 0xff], true).await;
        store(&mut remote, 0xf2, 0x86, &[0xff], true).await;
        store(&mut remote, 0x72, 0x73, &[0xaa, 0xbb], false).await;
        store(&mut remote, 0xf7, 0x73, &[0xcc], true).await;
        // Ordinary protected blocks discard the 0x5A challenge and keep the
        // fixed 0x73 tag; only 0xF7 substitutes its challenge.
        store(&mut remote, 0x80, 0x73, &[0xdd], true).await;
        recall(&mut remote, 0x72, &[0xaa, 0xbb]).await;
        recall(&mut remote, 0xf7, &[0xcc]).await;
        recall(&mut remote, 0x80, &[0xdd]).await;
        store(&mut remote, 0xf2, 0x86, &[1], true).await;
        store(&mut remote, 0x70, 0x85, &[0x9d, 0x40], true).await;
        recall(&mut remote, 0xf2, &[1]).await;
        assert_eq!(
            apply.await.unwrap().unwrap(),
            PatchApplyReceipt {
                previous_version: 0xff,
                target_version: 1,
                verified_blocks: 3,
                disposition: PatchApplyDisposition::AppliedFullPipeline,
            }
        );

        // Model a reconnect after an earlier attempt set the target version
        // and blocks but left 0x70 disabled. The retry repairs only enable.
        let worker = pci.clone();
        let repeat_blocks = blocks.clone();
        let repeat = tokio::spawn(async move {
            worker
                .write_patch_verified(5, 0xf2, &[0], 1, &repeat_blocks)
                .await
        });
        recall(&mut remote, 0xf2, &[1]).await;
        recall(&mut remote, 0x72, &[0xaa, 0xbb]).await;
        recall(&mut remote, 0xf7, &[0xcc]).await;
        recall(&mut remote, 0x80, &[0xdd]).await;
        recall(&mut remote, 0x70, &[0xff, 0xff]).await;
        store(&mut remote, 0x70, 0x85, &[0x9d, 0x40], true).await;
        recall(&mut remote, 0xf2, &[1]).await;
        assert_eq!(
            repeat.await.unwrap().unwrap().disposition,
            PatchApplyDisposition::RepairedEnableOnly
        );

        // Once control, version and blocks all match, replay is read-only.
        let worker = pci.clone();
        let idempotent =
            tokio::spawn(
                async move { worker.write_patch_verified(5, 0xf2, &[0], 1, &blocks).await },
            );
        recall(&mut remote, 0xf2, &[1]).await;
        recall(&mut remote, 0x72, &[0xaa, 0xbb]).await;
        recall(&mut remote, 0xf7, &[0xcc]).await;
        recall(&mut remote, 0x80, &[0xdd]).await;
        recall(&mut remote, 0x70, &[0x9d, 0x40]).await;
        recall(&mut remote, 0xf2, &[1]).await;
        assert_eq!(
            idempotent.await.unwrap().unwrap().disposition,
            PatchApplyDisposition::AlreadyVerifiedReadOnly
        );
        assert!(
            tokio::time::timeout(Duration::from_millis(25), line(&mut remote))
                .await
                .is_err(),
            "existing-patch recovery emitted an unexpected extra command"
        );
    }

    #[tokio::test(start_paused = true)]
    async fn patch_version_precondition_refuses_before_unlock_or_store() {
        let (pci, mut remote, _) = setup().await;
        for unit in [0, 255] {
            assert_eq!(
                pci.write_patch_verified(
                    unit,
                    0xf2,
                    &[0],
                    1,
                    &[PatchProgrammingBlock {
                        parameter: 0x72,
                        data: vec![0xaa],
                        unlock: false,
                    }],
                )
                .await
                .unwrap_err()
                .kind(),
                ErrorKind::InvalidInput
            );
        }
        assert_eq!(
            pci.write_patch_verified(
                5,
                5,
                &[0],
                1,
                &[PatchProgrammingBlock {
                    parameter: 0x72,
                    data: vec![0xaa],
                    unlock: false,
                }],
            )
            .await
            .unwrap_err()
            .kind(),
            ErrorKind::InvalidInput
        );
        let worker = pci.clone();
        let apply = tokio::spawn(async move {
            worker
                .write_patch_verified(
                    5,
                    0xf2,
                    &[0],
                    1,
                    &[PatchProgrammingBlock {
                        parameter: 0x72,
                        data: vec![0xaa],
                        unlock: false,
                    }],
                )
                .await
        });
        let request = line(&mut remote).await;
        assert!(request.starts_with(b"\\4605001AF201"), "{request:?}");
        reply(&mut remote, 5, &[0x82, 0xf2, 2]).await;
        assert!(apply
            .await
            .unwrap()
            .unwrap_err()
            .to_string()
            .contains("not admitted"));
        assert!(!pci.programming_fault.load(Ordering::Acquire));
        assert!(
            tokio::time::timeout(Duration::from_millis(25), line(&mut remote))
                .await
                .is_err(),
            "version mismatch emitted a mutating command"
        );
    }

    #[tokio::test(start_paused = true)]
    async fn full_patch_verify_detects_post_store_corruption_and_faults_lane() {
        async fn respond_recall(
            remote: &mut BufReader<tokio::io::DuplexStream>,
            parameter: u8,
            data: &[u8],
        ) {
            let request = line(remote).await;
            assert!(request
                .starts_with(format!("\\4605001A{parameter:02X}{:02X}", data.len()).as_bytes()));
            let mut cal = vec![0x80 | (data.len() as u8 + 1), parameter];
            cal.extend_from_slice(data);
            reply(remote, 5, &cal).await;
        }
        async fn respond_unlock(remote: &mut BufReader<tokio::io::DuplexStream>, parameter: u8) {
            let request = line(remote).await;
            assert!(request.starts_with(format!("\\46050011{parameter:02X}").as_bytes()));
            let code = request[request.len() - 2];
            reply(remote, 5, &[0x82, parameter, 0x5a]).await;
            remote.get_mut().write_all(&[code, b'.']).await.unwrap();
        }
        async fn respond_store(
            remote: &mut BufReader<tokio::io::DuplexStream>,
            parameter: u8,
            tag: u8,
            data: &[u8],
            unlock: bool,
        ) {
            if unlock {
                respond_unlock(remote, parameter).await;
            }
            let request = line(remote).await;
            let marker = format!("{parameter:02X}{tag:02X}");
            assert!(request
                .windows(marker.len())
                .any(|window| window == marker.as_bytes()));
            reply(remote, 5, &[0x32, parameter, tag]).await;
            respond_recall(remote, parameter, data).await;
        }

        let (pci, mut remote, _) = setup().await;
        let worker = pci.clone();
        let apply = tokio::spawn(async move {
            worker
                .write_patch_verified(
                    5,
                    0xf2,
                    &[0],
                    1,
                    &[PatchProgrammingBlock {
                        parameter: 0x72,
                        data: vec![0xaa],
                        unlock: false,
                    }],
                )
                .await
        });
        respond_recall(&mut remote, 0xf2, &[0]).await;
        respond_store(&mut remote, 0x70, 0x85, &[0xff, 0xff], true).await;
        respond_store(&mut remote, 0xf2, 0x86, &[0xff], true).await;
        respond_store(&mut remote, 0x72, 0x73, &[0xaa], false).await;
        // The immediate STORE readback matched, then the distinct full verify
        // sees corruption before target-version finalization or re-enable.
        respond_recall(&mut remote, 0x72, &[0xbb]).await;
        assert!(apply
            .await
            .unwrap()
            .unwrap_err()
            .to_string()
            .contains("full patch verify failed"));
        assert!(pci.programming_fault.load(Ordering::Acquire));
        assert!(
            tokio::time::timeout(Duration::from_millis(25), line(&mut remote))
                .await
                .is_err(),
            "failed full verification continued to version finalization"
        );
    }

    #[tokio::test(start_paused = true)]
    async fn existing_patch_enable_recovery_requires_verified_readback() {
        async fn respond_recall(
            remote: &mut BufReader<tokio::io::DuplexStream>,
            parameter: u8,
            data: &[u8],
        ) {
            let request = line(remote).await;
            assert!(request
                .starts_with(format!("\\4605001A{parameter:02X}{:02X}", data.len()).as_bytes()));
            let mut cal = vec![0x80 | (data.len() as u8 + 1), parameter];
            cal.extend_from_slice(data);
            reply(remote, 5, &cal).await;
        }

        let (pci, mut remote, _) = setup().await;
        let worker = pci.clone();
        let apply = tokio::spawn(async move {
            worker
                .write_patch_verified(
                    5,
                    0xf2,
                    &[0],
                    1,
                    &[PatchProgrammingBlock {
                        parameter: 0x72,
                        data: vec![0xaa],
                        unlock: false,
                    }],
                )
                .await
        });
        respond_recall(&mut remote, 0xf2, &[1]).await;
        respond_recall(&mut remote, 0x72, &[0xaa]).await;
        respond_recall(&mut remote, 0x70, &[0xff, 0xff]).await;

        let unlock_request = line(&mut remote).await;
        assert!(unlock_request.starts_with(b"\\4605001170"));
        let code = unlock_request[unlock_request.len() - 2];
        reply(&mut remote, 5, &[0x82, 0x70, 0x5a]).await;
        remote.get_mut().write_all(&[code, b'.']).await.unwrap();

        let store_request = line(&mut remote).await;
        assert!(store_request.windows(8).any(|window| window == b"70859D40"));
        reply(&mut remote, 5, &[0x32, 0x70, 0x85]).await;
        // The STORE ACK arrived, but readback proves that enable did not take.
        respond_recall(&mut remote, 0x70, &[0xff, 0xff]).await;

        assert!(apply
            .await
            .unwrap()
            .unwrap_err()
            .to_string()
            .contains("existing patch re-enable failed"));
        assert!(pci.programming_fault.load(Ordering::Acquire));
        assert!(
            tokio::time::timeout(Duration::from_millis(25), line(&mut remote))
                .await
                .is_err()
        );
    }

    #[tokio::test(start_paused = true)]
    async fn project_identity_store_uses_native_fixed_tag_and_verifies_readback() {
        let (pci, mut remote, _) = setup().await;
        let worker = pci.clone();
        let encoded = [0xce, 0x4c, 0xb3, 0x79, 0xe7, 0x9e];
        let write =
            tokio::spawn(async move { worker.set_project_identity_verified(6, &encoded).await });
        assert_eq!(line(&mut remote).await, b"\\460600A82346CE4CB379E79ED8\r");
        reply(&mut remote, 6, &[0x32, 0x23, 0x46]).await;
        assert_eq!(line(&mut remote).await, b"\\4606001A230671\r");
        reply(
            &mut remote,
            6,
            &[0x87, 0x23, 0xce, 0x4c, 0xb3, 0x79, 0xe7, 0x9e],
        )
        .await;
        write.await.unwrap().unwrap();
    }

    #[tokio::test(start_paused = true)]
    async fn project_identity_store_matching_nak_fails_immediately_without_recall() {
        let (pci, mut remote, _) = setup().await;
        let worker = pci.clone();
        let encoded = [0xce, 0x4c, 0xb3, 0x79, 0xe7, 0x9e];
        let write =
            tokio::spawn(async move { worker.set_project_identity_verified(6, &encoded).await });
        assert_eq!(line(&mut remote).await, b"\\460600A82346CE4CB379E79ED8\r");
        reply(&mut remote, 6, &[0x3b, 0x23, 0x46]).await;
        assert!(write
            .await
            .unwrap()
            .unwrap_err()
            .to_string()
            .contains("unit rejected programming selector"));
        assert!(
            tokio::time::timeout(Duration::from_millis(25), line(&mut remote))
                .await
                .is_err(),
            "a definitive NAK must not start RECALL"
        );
        assert!(
            !pci.programming_fault.load(Ordering::Acquire),
            "a definitive NAK must leave the programming lane usable"
        );
    }

    #[tokio::test(start_paused = true)]
    async fn locked_parameter_store_uses_native_unlock_then_verifies_readback() {
        let (pci, mut remote, _) = setup().await;
        let worker = pci.clone();
        let write = tokio::spawn(async move {
            worker
                .store_locked_parameter_verified(4, 0x20, &[0x06])
                .await
        });
        assert_eq!(line(&mut remote).await, b"\\4604001120h\r");
        reply(&mut remote, 5, &[0x82, 0x20, 0x99]).await;
        reply(&mut remote, 4, &[0x82, 0x20, 0x5a]).await;
        remote.get_mut().write_all(b"h.\r\n").await.unwrap();
        assert_eq!(line(&mut remote).await, b"\\460400A3200006ED\r");
        reply(&mut remote, 4, &[0x32, 0x20, 0]).await;
        assert_eq!(line(&mut remote).await, b"\\4604001A20017B\r");
        reply(&mut remote, 4, &[0x82, 0x20, 0x06]).await;
        write.await.unwrap().unwrap();
        assert_eq!(
            pci.store_locked_parameter_verified(4, 0xf0, &[0; 30])
                .await
                .unwrap_err()
                .kind(),
            ErrorKind::InvalidInput
        );
    }

    #[tokio::test(start_paused = true)]
    async fn readdress_uses_native_challenge_and_preserves_mqtt_fanout() {
        let (pci, mut remote, mut events) = setup().await;
        let worker = pci.clone();
        let moving = tokio::spawn(async move { worker.readdress_unit(4, 6).await });
        assert_eq!(line(&mut remote).await, b"\\4604001120h\r");
        reply(&mut remote, 4, &[0x82, 0x20, 0x5a]).await;
        remote.get_mut().write_all(b"h.\r\n").await.unwrap();
        assert_eq!(line(&mut remote).await, b"\\460400A3204E065Ai\r");
        remote
            .get_mut()
            .write_all(b"05043800790145\r\n")
            .await
            .unwrap();
        // C-Gate's cu command accepts the ACK from the destination address.
        reply(&mut remote, 6, &[0x32, 0x20, 0x4e]).await;
        remote.get_mut().write_all(b"i.\r\n").await.unwrap();
        moving.await.unwrap().unwrap();
        assert!(matches!(
            events.recv().await,
            Some(CBusEvent::LightingOn {
                source: Some(4),
                app: 56,
                group: 1
            })
        ));
    }

    #[tokio::test(start_paused = true)]
    async fn definitive_readdress_nak_does_not_fault_programming_lane() {
        let (pci, mut remote, _) = setup().await;
        let worker = pci.clone();
        let moving = tokio::spawn(async move { worker.readdress_unit(4, 6).await });
        assert_eq!(line(&mut remote).await, b"\\4604001120h\r");
        reply(&mut remote, 4, &[0x82, 0x20, 0x5a]).await;
        remote.get_mut().write_all(b"h.\r\n").await.unwrap();
        assert_eq!(line(&mut remote).await, b"\\460400A3204E065Ai\r");
        reply(&mut remote, 4, &[0x3b, 0x20, 0x4e]).await;
        remote.get_mut().write_all(b"i.\r\n").await.unwrap();
        assert!(moving
            .await
            .unwrap()
            .unwrap_err()
            .to_string()
            .contains("unit rejected"));
        assert!(!pci.programming_fault.load(Ordering::Acquire));
        assert_eq!(
            pci.readdress_unit(4, 4).await.unwrap_err().kind(),
            ErrorKind::InvalidInput
        );
    }

    #[tokio::test(start_paused = true)]
    async fn save_to_nvm_polls_and_preserves_mqtt_fanout() {
        let (pci, mut remote, mut events) = setup().await;
        let worker = pci.clone();
        let saving = tokio::spawn(async move { worker.save_to_nvm(5).await });
        assert_eq!(line(&mut remote).await, b"\\460500E3810004\r");

        // Normal bus traffic must continue to reach the MQTT side while the
        // programming lane waits for a source-correlated extended reply.
        remote
            .get_mut()
            .write_all(b"05043800790145\r\n")
            .await
            .unwrap();
        reply(&mut remote, 5, &[0xe4, 0x83, 0, 4, 1]).await;

        assert_eq!(line(&mut remote).await, b"\\460500E3820004\r");
        reply(&mut remote, 5, &[0xe4, 0x83, 0, 4, 1]).await;
        tokio::time::advance(NVM_POLL_INTERVAL).await;
        tokio::task::yield_now().await;
        assert_eq!(line(&mut remote).await, b"\\460500E3820004\r");
        reply(&mut remote, 5, &[0xe4, 0x83, 0, 4, 0]).await;

        saving.await.unwrap().unwrap();
        assert!(matches!(
            events.recv().await,
            Some(CBusEvent::LightingOn {
                source: Some(4),
                app: 56,
                group: 1
            })
        ));
        assert!(!pci.programming_fault.load(Ordering::Acquire));
    }

    #[tokio::test(start_paused = true)]
    async fn dali_auto_uses_native_priority_zero_and_correlates_execute_poll_sequence() {
        let (pci, mut remote, mut events) = setup().await;
        let worker = pci.clone();
        let running = tokio::spawn(async move {
            worker
                .dali_command(20, DaliCalMode::Auto, 0xda, 7, &[])
                .await
        });
        assert_eq!(line(&mut remote).await, b"\\061400E381DA07\r");

        // MQTT/event fanout stays live while the source-correlated DALI
        // transaction owns only the programming lane.
        remote
            .get_mut()
            .write_all(b"05043800790145\r\n")
            .await
            .unwrap();
        direct_reply(&mut remote, 19, &[0xe4, 0x83, 0xda, 7, 0]).await;
        tokio::task::yield_now().await;
        assert!(
            !running.is_finished(),
            "a different source must not satisfy DALI"
        );

        // Retained firmware accepts group zero as an alias for device type
        // 0xDA in an otherwise correlated response.
        direct_reply(&mut remote, 20, &[0xe4, 0x83, 0, 7, 1]).await;
        tokio::time::advance(Duration::from_millis(1500)).await;
        tokio::task::yield_now().await;
        assert_eq!(line(&mut remote).await, b"\\061400E382DA07\r");
        direct_reply(&mut remote, 20, &[0xe4, 0x83, 0xda, 7, 2]).await;
        tokio::time::advance(Duration::from_millis(1500)).await;
        tokio::task::yield_now().await;
        assert_eq!(line(&mut remote).await, b"\\061400E382DA07\r");
        direct_reply(&mut remote, 20, &[0xe5, 0x83, 0xda, 7, 0, 0xaa]).await;

        let result = running.await.unwrap().unwrap();
        assert_eq!(
            result
                .exchanges
                .iter()
                .map(|exchange| (exchange.mode, exchange.status, exchange.data.clone()))
                .collect::<Vec<_>>(),
            [
                (DaliCalMode::Execute, 1, vec![]),
                (DaliCalMode::Poll, 2, vec![]),
                (DaliCalMode::Poll, 0, vec![0xaa]),
            ]
        );
        assert_eq!(result.exchanges[0].request_wire, "\\061400E381DA07");
        assert!(matches!(
            events.recv().await,
            Some(CBusEvent::LightingOn {
                source: Some(4),
                app: 56,
                group: 1
            })
        ));
        assert!(!pci.programming_fault.load(Ordering::Acquire));
    }

    #[tokio::test(start_paused = true)]
    async fn dali_nak_is_definitive_but_lost_reply_faults_without_replay() {
        let (pci, mut remote, _) = setup().await;
        let worker = pci.clone();
        let rejected = tokio::spawn(async move {
            worker
                .dali_command(20, DaliCalMode::Execute, 0xda, 7, &[])
                .await
        });
        assert_eq!(line(&mut remote).await, b"\\061400E381DA07\r");
        direct_reply(&mut remote, 20, &[0x3b, 0, 7, 2]).await;
        let result = rejected.await.unwrap().unwrap();
        assert_eq!(result.exchanges.len(), 1);
        assert!(result.exchanges[0].nak);
        assert_eq!(result.exchanges[0].status, 0xff);
        assert!(!pci.programming_fault.load(Ordering::Acquire));

        let worker = pci.clone();
        let uncertain = tokio::spawn(async move {
            worker
                .dali_command(20, DaliCalMode::Execute, 0xda, 7, &[])
                .await
        });
        assert_eq!(line(&mut remote).await, b"\\061400E381DA07\r");
        assert_eq!(
            uncertain.await.unwrap().unwrap_err().kind(),
            ErrorKind::TimedOut
        );
        assert!(pci.programming_fault.load(Ordering::Acquire));
        assert!(pci
            .dali_command(20, DaliCalMode::Execute, 0xda, 7, &[])
            .await
            .unwrap_err()
            .to_string()
            .contains("needs reconnect"));
        assert!(
            tokio::time::timeout(Duration::from_millis(1), line(&mut remote))
                .await
                .is_err()
        );
    }

    #[tokio::test(start_paused = true)]
    async fn definitive_save_to_nvm_failures_do_not_fault_programming_lane() {
        let (pci, mut remote, _) = setup().await;
        let worker = pci.clone();
        let busy = tokio::spawn(async move { worker.save_to_nvm(5).await });
        assert_eq!(line(&mut remote).await, b"\\460500E3810004\r");
        reply(&mut remote, 5, &[0xe4, 0x83, 0, 4, 2]).await;
        assert!(busy
            .await
            .unwrap()
            .unwrap_err()
            .to_string()
            .contains("busy"));
        assert!(!pci.programming_fault.load(Ordering::Acquire));

        let worker = pci.clone();
        let rejected = tokio::spawn(async move { worker.save_to_nvm(5).await });
        assert_eq!(line(&mut remote).await, b"\\460500E3810004\r");
        reply(&mut remote, 5, &[0x3b, 0, 4, 2]).await;
        assert!(rejected
            .await
            .unwrap()
            .unwrap_err()
            .to_string()
            .contains("rejected"));
        assert!(!pci.programming_fault.load(Ordering::Acquire));
    }

    #[tokio::test(start_paused = true)]
    async fn lost_save_to_nvm_reply_faults_programming_lane() {
        let (pci, mut remote, _) = setup().await;
        let worker = pci.clone();
        let saving = tokio::spawn(async move { worker.save_to_nvm(5).await });
        assert_eq!(line(&mut remote).await, b"\\460500E3810004\r");
        assert_eq!(
            saving.await.unwrap().unwrap_err().kind(),
            ErrorKind::TimedOut
        );
        assert!(pci.programming_fault.load(Ordering::Acquire));
    }

    #[tokio::test(start_paused = true)]
    async fn lost_readdress_confirmation_is_never_replayed() {
        let (pci, mut remote, _) = setup().await;
        let worker = pci.clone();
        let moving = tokio::spawn(async move { worker.readdress_unit(4, 6).await });
        assert_eq!(line(&mut remote).await, b"\\4604001120h\r");
        reply(&mut remote, 4, &[0x82, 0x20, 0x5a]).await;
        remote.get_mut().write_all(b"h.\r\n").await.unwrap();
        assert_eq!(line(&mut remote).await, b"\\460400A3204E065Ai\r");
        reply(&mut remote, 6, &[0x32, 0x20, 0x4e]).await;
        // The unit moved, but the PCI confirmation is lost. The normal send
        // path would retry after about one second; this mutation must not.
        assert!(
            tokio::time::timeout(Duration::from_secs(5), line(&mut remote))
                .await
                .is_err()
        );
        tokio::time::advance(Duration::from_secs(6)).await;
        tokio::task::yield_now().await;
        assert_eq!(
            moving.await.unwrap().unwrap_err().kind(),
            ErrorKind::TimedOut
        );
        assert!(pci.programming_fault.load(Ordering::Acquire));
        assert!(pci.state.lock().unwrap().pending.is_empty());
    }

    #[tokio::test(start_paused = true)]
    async fn rejected_locked_parameter_unlock_poisons_the_programming_lane() {
        let (pci, mut remote, _) = setup().await;
        let worker = pci.clone();
        let write = tokio::spawn(async move {
            worker
                .store_locked_parameter_verified(4, 0x20, &[0x06])
                .await
        });
        assert_eq!(line(&mut remote).await, b"\\4604001120h\r");
        remote.get_mut().write_all(b"h#\r\n").await.unwrap();
        assert!(write
            .await
            .unwrap()
            .unwrap_err()
            .to_string()
            .contains("rejected"));
        assert!(pci.programming_fault.load(Ordering::Acquire));
        assert!(pci.state.lock().unwrap().pending.is_empty());
    }

    #[tokio::test(start_paused = true)]
    async fn locked_parameter_store_splits_at_native_twelve_byte_limit() {
        let (pci, mut remote, _) = setup().await;
        let worker = pci.clone();
        let write = tokio::spawn(async move {
            worker
                .store_locked_parameter_verified(4, 0x40, &[0; 13])
                .await
        });
        assert_eq!(line(&mut remote).await, b"\\4604001140h\r");
        reply(&mut remote, 4, &[0x82, 0x40, 0x5a]).await;
        remote.get_mut().write_all(b"h.\r\n").await.unwrap();
        assert_eq!(
            line(&mut remote).await,
            b"\\460400AE4000000000000000000000000000C8\r"
        );
        reply(&mut remote, 4, &[0x32, 0x40, 0]).await;
        assert_eq!(line(&mut remote).await, b"\\460400114Ci\r");
        reply(&mut remote, 4, &[0x82, 0x4c, 0x5a]).await;
        remote.get_mut().write_all(b"i.\r\n").await.unwrap();
        assert_eq!(line(&mut remote).await, b"\\460400A34C0100C6\r");
        reply(&mut remote, 4, &[0x32, 0x4c, 1]).await;
        assert_eq!(line(&mut remote).await, b"\\4604001A400D4F\r");
        let mut recalled = vec![0x8e, 0x40];
        recalled.extend([0; 13]);
        reply(&mut remote, 4, &recalled).await;
        write.await.unwrap().unwrap();
    }

    #[tokio::test(start_paused = true)]
    async fn oem_memory_store_uses_captured_tags_and_verifies_readback() {
        let (pci, mut remote, _) = setup().await;
        let worker = pci.clone();
        let write = tokio::spawn(async move {
            worker
                .write_memory_verified(5, 0x1000, &[0xaa, 0xbb, 0xcc])
                .await
        });
        assert_eq!(line(&mut remote).await, b"\\46050900A400410010B7\r");
        reply(&mut remote, 5, &[0x32, 0, 0x41]).await;
        assert_eq!(line(&mut remote).await, b"\\46050900A50142AABBCC93\r");
        reply(&mut remote, 4, &[0x32, 1, 0x42]).await;
        reply(&mut remote, 5, &[0x32, 1, 0x42]).await;
        assert_eq!(line(&mut remote).await, b"\\46050900A400410010B7\r");
        reply(&mut remote, 5, &[0x32, 0, 0x41]).await;
        assert_eq!(line(&mut remote).await, b"\\460509001A01038E\r");
        reply(&mut remote, 5, &[0x84, 1, 0xaa, 0xbb, 0xcc]).await;
        write.await.unwrap().unwrap();
        assert_eq!(
            pci.write_memory_verified(5, u32::MAX, &[1])
                .await
                .unwrap_err()
                .kind(),
            ErrorKind::InvalidInput
        );
    }

    #[tokio::test(start_paused = true)]
    async fn giu_store_halts_writes_resumes_and_verifies() {
        let (pci, mut remote, _) = setup().await;
        let worker = pci.clone();
        let write = tokio::spawn(async move {
            worker
                .write_giu_memory_verified(5, 0x1000, &[0xaa, 0xbb, 0xcc])
                .await
        });
        assert_eq!(line(&mut remote).await, b"\\46050900A3FC03000A\r");
        reply(&mut remote, 5, &[0x32, 0xfc, 3]).await;
        assert_eq!(line(&mut remote).await, b"\\46050900A400410010B7\r");
        reply(&mut remote, 5, &[0x32, 0, 0x41]).await;
        assert_eq!(line(&mut remote).await, b"\\46050900A50142AABBCC93\r");
        reply(&mut remote, 5, &[0x32, 1, 0x42]).await;
        assert_eq!(line(&mut remote).await, b"\\46050900A3FC030109\r");
        reply(&mut remote, 5, &[0x32, 0xfc, 3]).await;
        assert_eq!(line(&mut remote).await, b"\\46050900A400410010B7\r");
        reply(&mut remote, 5, &[0x32, 0, 0x41]).await;
        assert_eq!(line(&mut remote).await, b"\\460509001A01038E\r");
        reply(&mut remote, 5, &[0x84, 1, 0xaa, 0xbb, 0xcc]).await;
        write.await.unwrap().unwrap();
    }

    #[tokio::test(start_paused = true)]
    async fn goc_store_prefixes_big_endian_address_and_verifies() {
        let (pci, mut remote, _) = setup().await;
        let worker = pci.clone();
        let write = tokio::spawn(async move {
            worker
                .write_goc_memory_verified(5, 0x1234, &[0xaa, 0xbb, 0xcc], GocProgramming::Goc2)
                .await
        });
        assert_eq!(line(&mut remote).await, b"\\460500A7FF001234AABBCC98\r");
        reply(&mut remote, 4, &[0x32, 0xff, 0]).await;
        reply(&mut remote, 5, &[0x32, 0xff, 0]).await;
        assert_eq!(line(&mut remote).await, b"\\460500A4FF4212348A\r");
        reply(&mut remote, 5, &[0x32, 0xff, 0x42]).await;
        assert_eq!(line(&mut remote).await, b"\\4605001AFF0399\r");
        reply(&mut remote, 5, &[0x84, 0xff, 0xaa, 0xbb, 0xcc]).await;
        write.await.unwrap().unwrap();
    }

    #[tokio::test(start_paused = true)]
    async fn incomplete_read_poisoned_until_reconnect_and_does_not_write_memory() {
        let (pci, mut remote, _) = setup().await;
        let cloned = pci.clone();
        let read = tokio::spawn(async move { cloned.read_memory(5, 0x1000, 64).await });
        assert_eq!(line(&mut remote).await, b"\\46050900A400410010B7\r");
        reply(&mut remote, 5, &[0x32, 0, 0x41]).await;
        assert_eq!(line(&mut remote).await, b"\\460509001A014051\r");
        reply(&mut remote, 5, &[0x82, 1, 0x20]).await;
        assert_eq!(read.await.unwrap().unwrap_err().kind(), ErrorKind::TimedOut);
        assert!(pci
            .read_memory(5, 0x1000, 64)
            .await
            .unwrap_err()
            .to_string()
            .contains("reconnect"));
    }

    #[tokio::test(start_paused = true)]
    async fn negative_delivery_confirmation_is_error_and_never_retried() {
        let (pci, mut remote, _) = setup().await;
        let cloned = pci.clone();
        let command = tokio::spawn(async move {
            cloned
                .send_confirmed(&Packet::PointToMultipoint {
                    meta: Meta::new(true, 0),
                    application: 56,
                    sals: vec![Sal::LightingOn {
                        application: 56,
                        group_address: 1,
                    }],
                })
                .await
        });
        assert_eq!(line(&mut remote).await, b"\\053800790149h\r");
        remote.get_mut().write_all(b"h.").await.unwrap();
        assert!(command.await.unwrap().is_ok());
        assert!(pci.state.lock().unwrap().pending.is_empty());
        let cloned = pci.clone();
        let command = tokio::spawn(async move {
            cloned
                .send_confirmed(&Packet::PointToMultipoint {
                    meta: Meta::new(true, 0),
                    application: 56,
                    sals: vec![Sal::LightingOff {
                        application: 56,
                        group_address: 1,
                    }],
                })
                .await
        });
        line(&mut remote).await;
        remote.get_mut().write_all(b"i#").await.unwrap();
        assert!(command
            .await
            .unwrap()
            .unwrap_err()
            .to_string()
            .contains("rejected"));
        assert!(pci.state.lock().unwrap().pending.is_empty());
    }

    #[tokio::test(start_paused = true)]
    async fn one_shot_confirmation_timeout_never_registers_or_replays_the_frame() {
        let (pci, mut remote, _) = setup().await;
        let worker = pci.clone();
        let command = tokio::spawn(async move {
            worker
                .send_confirmed_once(&Packet::PointToMultipoint {
                    meta: Meta::new(true, 0),
                    application: cbus_protocol::common::APP_MEDIA_TRANSPORT,
                    sals: vec![Sal::MediaTransport(
                        cbus_protocol::sal::mediatransport::MediaTransportMessage::StatusRequest {
                            group: 2,
                        },
                    )],
                })
                .await
        });
        assert_eq!(line(&mut remote).await, b"\\05C0007102C8h\r");
        assert!(pci.state.lock().unwrap().pending.is_empty());

        tokio::time::advance(Duration::from_secs(13)).await;
        assert_eq!(
            command.await.unwrap().unwrap_err().kind(),
            ErrorKind::TimedOut
        );
        {
            let state = pci.state.lock().unwrap();
            assert!(state.pending.is_empty());
            assert!(state.quarantined_codes.contains(&b'h'));
        }

        let mut replay = Vec::new();
        assert!(tokio::time::timeout(
            Duration::from_millis(1),
            remote.read_until(b'\r', &mut replay)
        )
        .await
        .is_err());
        assert!(replay.is_empty());
    }

    #[tokio::test(start_paused = true)]
    async fn aircon_status_is_fanned_out_without_completing_confirmed_send() {
        let (pci, mut remote, mut events) = setup().await;
        let worker = pci.clone();
        let command = tokio::spawn(async move {
            worker
                .send_confirmed(&Packet::PointToMultipoint {
                    meta: Meta::new(true, 0),
                    application: cbus_protocol::common::APP_AIRCON,
                    sals: vec![Sal::Aircon(AirconCommand::Refresh { ward: 1 })],
                })
                .await
        });
        assert_eq!(line(&mut remote).await, b"\\05AC0021012Dh\r");

        // A REFRESH response is normal PM traffic. It must be decoded and
        // delivered while the sender continues waiting for its assigned PCI
        // confirmation character.
        remote
            .get_mut()
            .write_all(b"0504AC000501070301003A\r\n")
            .await
            .unwrap();
        assert_eq!(
            events.recv().await,
            Some(CBusEvent::AirconStatus {
                source: Some(4),
                status: AirconStatus::ZoneHvacPlantStatus {
                    ward: 1,
                    zones: 7,
                    plant_type: 3,
                    status: 1,
                    error: 0,
                },
            })
        );
        assert!(!command.is_finished());
        remote.get_mut().write_all(b"h.\r\n").await.unwrap();
        assert!(command.await.unwrap().is_ok());
    }

    #[tokio::test(start_paused = true)]
    async fn security_event_is_fanned_out_without_completing_confirmed_send() {
        let (pci, mut remote, mut events) = setup().await;
        let worker = pci.clone();
        let command = tokio::spawn(async move {
            worker
                .send_confirmed(&Packet::PointToMultipoint {
                    meta: Meta::new(true, 0),
                    application: cbus_protocol::common::APP_SECURITY,
                    sals: vec![Sal::SecurityCommand(SecurityCommand::StatusRequest {
                        report: 1,
                    })],
                })
                .await
        });
        assert_eq!(line(&mut remote).await, b"\\05D00009A082h\r");

        // Normal Security traffic remains independently observable while
        // the sender waits for its assigned PCI confirmation character.
        remote
            .get_mut()
            .write_all(b"0504D0000A860790\r\n")
            .await
            .unwrap();
        assert_eq!(
            events.recv().await,
            Some(CBusEvent::SecurityEvent {
                source: Some(4),
                event: SecurityEvent::ZoneUnsealed { zone: 7 },
            })
        );
        assert!(!command.is_finished());
        remote.get_mut().write_all(b"h.\r\n").await.unwrap();
        assert!(command.await.unwrap().is_ok());
    }

    #[tokio::test(start_paused = true)]
    async fn telephony_event_is_fanned_out_without_completing_confirmed_send() {
        let (pci, mut remote, mut events) = setup().await;
        let worker = pci.clone();
        let command = tokio::spawn(async move {
            worker
                .send_confirmed(&Packet::PointToMultipoint {
                    meta: Meta::new(true, 0),
                    application: cbus_protocol::common::APP_TELEPHONY,
                    sals: vec![Sal::TelephonyCommand(
                        TelephonyCommand::RecallLastNumberRequest {
                            direction: cbus_protocol::sal::telephony::TelephonyDirection::Out,
                        },
                    )],
                })
                .await
        });
        assert_eq!(line(&mut remote).await, b"\\05E0000A81018Fh\r");

        // Telephony application traffic is a bus event, not the PCI
        // confirmation assigned to this send generation.
        remote
            .get_mut()
            .write_all(b"0504E0000A02010A\r\n")
            .await
            .unwrap();
        assert_eq!(
            events.recv().await,
            Some(CBusEvent::TelephonyEvent {
                source: Some(4),
                event: TelephonyEvent::LineOffHook {
                    direction: cbus_protocol::sal::telephony::TelephonyDirection::In,
                    reason: cbus_protocol::sal::telephony::OffHookReason::Voice,
                    number: Vec::new(),
                },
            })
        );
        assert!(!command.is_finished());
        remote.get_mut().write_all(b"h.\r\n").await.unwrap();
        assert!(command.await.unwrap().is_ok());
    }

    #[tokio::test(start_paused = true)]
    async fn measurement_data_is_fanned_out_without_completing_confirmed_send() {
        let (pci, mut remote, mut events) = setup().await;
        let sample = MeasurementData {
            device: 1,
            channel: 1,
            value: 10_234,
            multiplier: -2,
            units: 2,
        };
        let worker = pci.clone();
        let command = tokio::spawn(async move {
            worker
                .send_confirmed(&Packet::PointToMultipoint {
                    meta: Meta::new(true, 0),
                    application: cbus_protocol::common::APP_MEASUREMENT,
                    sals: vec![Sal::MeasurementData(sample)],
                })
                .await
        });
        assert_eq!(line(&mut remote).await, b"\\05E4000E010102FE27FAE6h\r");

        // An observed sample remains independently visible while the sender
        // waits for the assigned PCI confirmation character.
        remote
            .get_mut()
            .write_all(b"0564E4000E010102FE27FA82\r\n")
            .await
            .unwrap();
        assert_eq!(
            events.recv().await,
            Some(CBusEvent::MeasurementData {
                source: Some(100),
                measurement: sample,
            })
        );
        assert!(!command.is_finished());
        remote.get_mut().write_all(b"h.\r\n").await.unwrap();
        assert!(command.await.unwrap().is_ok());
    }

    #[tokio::test(start_paused = true)]
    async fn identify_all_waits_for_quiet_and_preserves_distinct_replies() {
        let (pci, mut remote, mut events) = setup().await;
        let running = tokio::spawn({
            let pci = pci.clone();
            async move { pci.identify_all(5, 4).await }
        });
        let request = line(&mut remote).await;
        assert!(
            request.starts_with(b"\\4605002104"),
            "{}",
            String::from_utf8_lossy(&request)
        );
        let code = request[request.len() - 2];
        remote.get_mut().write_all(&[code, b'.']).await.unwrap();
        let first = vec![
            0x38, 0xff, 0xff, 0xff, 0xff, 0x18, 0xb1, 0x06, 0x16, 0xa2, 0x00, 0x05,
        ];
        let second = vec![
            0x38, 0xff, 0xff, 0xff, 0xff, 0x18, 0xb1, 0x06, 0x17, 0xa2, 0x00, 0x05,
        ];
        reply(
            &mut remote,
            5,
            &[
                0x8d, 4, first[0], first[1], first[2], first[3], first[4], first[5], first[6],
                first[7], first[8], first[9], first[10], first[11],
            ],
        )
        .await;
        remote
            .get_mut()
            .write_all(b"05043800790145\r\n")
            .await
            .unwrap();
        tokio::time::advance(Duration::from_millis(1500)).await;
        tokio::task::yield_now().await;
        assert!(!running.is_finished());
        reply(
            &mut remote,
            5,
            &[
                0x8d, 4, second[0], second[1], second[2], second[3], second[4], second[5],
                second[6], second[7], second[8], second[9], second[10], second[11],
            ],
        )
        .await;
        tokio::time::advance(IDENTIFY_QUIET).await;
        tokio::task::yield_now().await;
        assert_eq!(running.await.unwrap().unwrap(), vec![first, second]);
        assert!(matches!(
            events.recv().await,
            Some(CBusEvent::LightingOn {
                source: Some(4),
                app: 56,
                group: 1
            })
        ));
    }

    #[tokio::test(start_paused = true)]
    async fn routed_identify_uses_native_path_and_preserves_mqtt_events() {
        let (pci, mut remote, mut events) = setup().await;
        let running = tokio::spawn({
            let pci = pci.clone();
            async move { pci.identify_first_routed(&[0xfd, 0xfc], 5, 1).await }
        });
        let request = line(&mut remote).await;
        assert_eq!(&request[..request.len() - 2], b"\\46FD12FC05210188");
        let code = request[request.len() - 2];

        // A direct reply and a reply from another first bridge must not be
        // attributed to the remote network. Ordinary monitored SAL continues
        // through the same reader while the CAL transaction is in flight.
        reply(
            &mut remote,
            5,
            &[0x87, 1, b'D', b'I', b'R', b'E', b'C', b'T'],
        )
        .await;
        routed_reply(
            &mut remote,
            &[0xfe, 0xfc],
            5,
            &[0x86, 1, b'W', b'R', b'O', b'N', b'G'],
        )
        .await;
        remote
            .get_mut()
            .write_all(b"05043800790145\r\n")
            .await
            .unwrap();
        routed_reply(
            &mut remote,
            &[0xfd, 0xfc],
            5,
            &[0x87, 1, b'K', b'E', b'Y', b'G', b'L', b'5'],
        )
        .await;
        tokio::task::yield_now().await;
        assert!(!running.is_finished());
        remote.get_mut().write_all(&[code, b'.']).await.unwrap();
        assert_eq!(running.await.unwrap().unwrap(), Some(b"KEYGL5".to_vec()));
        assert!(matches!(
            events.recv().await,
            Some(CBusEvent::LightingOn {
                source: Some(4),
                app: 56,
                group: 1
            })
        ));
    }

    #[tokio::test(start_paused = true)]
    async fn identify_all_can_prove_no_reply_in_the_bounded_window() {
        let (pci, mut remote, _) = setup().await;
        let running = tokio::spawn(async move { pci.identify_all(99, 4).await });
        let request = line(&mut remote).await;
        let code = request[request.len() - 2];
        remote.get_mut().write_all(&[code, b'.']).await.unwrap();
        tokio::time::advance(IDENTIFY_QUIET).await;
        tokio::task::yield_now().await;
        assert!(running.await.unwrap().unwrap().is_empty());
    }

    #[tokio::test(start_paused = true)]
    async fn local_address_discovery_correlates_bare_identify_replies() {
        let (pci, mut remote, _) = setup().await;
        let discovery = tokio::spawn({
            let pci = pci.clone();
            async move { pci.discover_local_unit().await }
        });
        assert_eq!(line(&mut remote).await, b"@1A2001\r");
        remote.get_mut().write_all(b"8220104E\r\n").await.unwrap();
        assert_eq!(discovery.await.unwrap().unwrap(), 16);

        let running = tokio::spawn(async move { pci.identify_all(16, 4).await });
        let request = line(&mut remote).await;
        let code = request[request.len() - 2];
        remote.get_mut().write_all(&[code, b'.']).await.unwrap();
        let identity = vec![
            0xff, 0xff, 0xff, 0x00, 0x00, 0x18, 0xa6, 0x64, 0xa3, 0xb1, 0x00, 0x05,
        ];
        let mut raw = Cal::Reply {
            parameter: 4,
            data: identity.clone(),
        }
        .encode();
        raw = cbus_protocol::common::add_cbus_checksum(&raw);
        let mut wire = raw
            .iter()
            .flat_map(|byte| format!("{byte:02X}").into_bytes())
            .collect::<Vec<_>>();
        wire.extend_from_slice(b"\r\n");
        remote.get_mut().write_all(&wire).await.unwrap();
        tokio::task::yield_now().await;
        tokio::time::advance(IDENTIFY_QUIET).await;
        tokio::task::yield_now().await;
        assert_eq!(running.await.unwrap().unwrap(), vec![identity]);
    }

    #[tokio::test(start_paused = true)]
    async fn identify_all_buffers_data_until_positive_confirmation() {
        let (pci, mut remote, _) = setup().await;
        let cloned = pci.clone();
        let running = tokio::spawn(async move { cloned.identify_all(5, 4).await });
        let request = line(&mut remote).await;
        let code = request[request.len() - 2];
        let data = [
            0x38, 0xff, 0xff, 0xff, 0xff, 0x18, 0xb1, 0x06, 0x16, 0xa2, 0x00, 0x05,
        ];
        let mut cal = vec![0x8d, 4];
        cal.extend(data);
        reply(&mut remote, 5, &cal).await;
        tokio::task::yield_now().await;
        assert!(!running.is_finished());
        remote.get_mut().write_all(&[code, b'.']).await.unwrap();
        tokio::time::advance(IDENTIFY_QUIET).await;
        tokio::task::yield_now().await;
        assert_eq!(running.await.unwrap().unwrap(), vec![data.to_vec()]);
    }

    #[tokio::test(start_paused = true)]
    async fn duplicate_address_probes_use_native_challenges_and_count_every_reply() {
        let (pci, mut remote, mut events) = setup().await;
        for (attempt, expected) in [
            (0, b"\\460500118024".as_slice()),
            (1, b"\\460500118123".as_slice()),
            (2, b"\\460500118222".as_slice()),
        ] {
            let running = tokio::spawn({
                let pci = pci.clone();
                async move { pci.duplicate_address_probe(5, attempt).await }
            });
            let request = line(&mut remote).await;
            assert_eq!(&request[..request.len() - 2], expected);
            let code = request[request.len() - 2];
            remote.get_mut().write_all(&[code, b'.']).await.unwrap();
            reply(&mut remote, 4, &[0x82, 0x80 + attempt, 0xaa]).await;
            reply(&mut remote, 5, &[0x82, 0x80 + attempt, 0x11]).await;
            reply(&mut remote, 5, &[0x82, 0x80 + attempt, 0x11]).await;
            remote
                .get_mut()
                .write_all(b"05043800790145\r\n")
                .await
                .unwrap();
            tokio::time::advance(DUPLICATE_PROBE_QUIET).await;
            tokio::task::yield_now().await;
            assert_eq!(running.await.unwrap().unwrap(), 2);
        }
        assert!(matches!(
            events.recv().await,
            Some(CBusEvent::LightingOn {
                source: Some(4),
                app: 56,
                group: 1
            })
        ));
    }

    #[tokio::test(start_paused = true)]
    async fn duplicate_address_probe_can_prove_silence_after_confirmation() {
        let (pci, mut remote, _) = setup().await;
        let running = tokio::spawn(async move { pci.duplicate_address_probe(99, 0).await });
        let request = line(&mut remote).await;
        let code = request[request.len() - 2];
        remote.get_mut().write_all(&[code, b'.']).await.unwrap();
        tokio::time::advance(DUPLICATE_PROBE_QUIET).await;
        tokio::task::yield_now().await;
        assert_eq!(running.await.unwrap().unwrap(), 0);
    }

    #[tokio::test(start_paused = true)]
    async fn duplicate_address_probe_rejects_an_unknown_attempt_without_faulting_lane() {
        let (pci, _remote, _) = setup().await;
        assert_eq!(
            pci.duplicate_address_probe(5, 3).await.unwrap_err().kind(),
            ErrorKind::InvalidInput
        );
        assert!(!pci.programming_fault.load(Ordering::Acquire));
    }
    #[tokio::test(start_paused = true)]
    async fn identify_cancellation_does_not_clear_a_reused_confirmation_code() {
        let (pci, _remote, _) = setup().await;
        let code = b'h';
        let replacement = b"same IDENTIFY request bytes".to_vec();
        let guard = SentConfirmation {
            client: &pci,
            code,
            allocation_id: 41,
        };
        {
            let mut state = pci.state.lock().unwrap();
            state.codes_in_use.insert(code, Instant::now());
            state.allocation_ids.insert(code, 42);
            state.pending.insert(
                code,
                Pending {
                    data: replacement.clone(),
                    attempts: 1,
                    next_retry: Instant::now() + Duration::from_secs(1),
                    queued_retry: None,
                },
            );
        }
        drop(guard);
        {
            let state = pci.state.lock().unwrap();
            assert_eq!(state.pending[&code].data, replacement);
            assert!(state.codes_in_use.contains_key(&code));
        }
        drop(SentConfirmation {
            client: &pci,
            code,
            allocation_id: 42,
        });
        let state = pci.state.lock().unwrap();
        assert!(!state.pending.contains_key(&code));
        assert!(state.codes_in_use.contains_key(&code));
        assert!(state.quarantined_codes.contains(&code));
        assert_eq!(state.allocation_ids.get(&code), Some(&42));
    }

    #[tokio::test(start_paused = true)]
    async fn cancelling_identify_skips_a_retry_already_queued_for_the_writer() {
        let (pci, mut remote, _) = setup().await;
        let caller = pci.clone();
        let operation = tokio::spawn(async move { caller.identify_all(5, 4).await });
        let request = line(&mut remote).await;
        let code = request[request.len() - 2];
        let held = pci.writer.lock().await;
        {
            let mut state = pci.state.lock().unwrap();
            state.pending.get_mut(&code).unwrap().next_retry = Instant::now();
        }
        tokio::time::advance(RETRY_SWEEP_INTERVAL).await;
        tokio::task::yield_now().await;
        {
            let state = pci.state.lock().unwrap();
            let pending = &state.pending[&code];
            assert_eq!(pending.attempts, 2);
            assert!(pending.queued_retry.is_some());
        }
        operation.abort();
        assert!(operation.await.unwrap_err().is_cancelled());
        {
            let state = pci.state.lock().unwrap();
            assert!(!state.pending.contains_key(&code));
            assert!(state.quarantined_codes.contains(&code));
        }
        drop(held);
        tokio::time::advance(Duration::from_secs(15)).await;
        let mut byte = [0u8; 1];
        assert!(tokio::time::timeout(
            Duration::from_millis(100),
            tokio::io::AsyncReadExt::read(&mut remote, &mut byte)
        )
        .await
        .is_err());
        remote.get_mut().write_all(&[code, b'.']).await.unwrap();
        tokio::task::yield_now().await;
        let state = pci.state.lock().unwrap();
        assert!(!state.codes_in_use.contains_key(&code));
        assert!(!state.allocation_ids.contains_key(&code));
        assert!(!state.quarantined_codes.contains(&code));
    }

    #[tokio::test(start_paused = true)]
    async fn legacy_selected_serial_completion_preserves_reused_send_quarantine() {
        let (pci, mut remote, _) = setup().await;
        pci.set_local_unit_hint(16).unwrap();
        let caller = pci.clone();
        let operation =
            tokio::spawn(async move { caller.address_selected_serial("101136.1558", 6).await });
        let request = line(&mut remote).await;
        let code = request[request.len() - 2];
        remote.get_mut().write_all(&[code, b'.']).await.unwrap();
        tokio::task::yield_now().await;
        assert!(!pci.state.lock().unwrap().codes_in_use.contains_key(&code));
        pci.state.lock().unwrap().next_confirmation_index = CONFIRMATION_CODES
            .iter()
            .position(|&value| value == code)
            .unwrap();
        let (replacement, generation) = pci.allocate_confirmation().unwrap();
        assert_eq!(replacement, code);
        let progress = Arc::new(flow::WriteProgress::default());
        assert!(progress.start());
        drop(ConfirmationAllocation {
            client: &pci,
            code,
            id: generation,
            retained: false,
            progress,
        });
        selected_serial_reply(&mut remote, 6, 16, [0x18, 0xb1, 0x06, 0x16], [0, 0]).await;
        operation.await.unwrap().unwrap();
        let state = pci.state.lock().unwrap();
        assert_eq!(state.allocation_ids.get(&code), Some(&generation));
        assert!(state.codes_in_use.contains_key(&code));
        assert!(state.quarantined_codes.contains(&code));
    }
}
