//! Pure codecs for the original CAL selected-serial address broadcast.
//!
//! No function opens a connection or sends bytes. A matching receipt
//! establishes packet correlation only; independent physical inventory
//! remains necessary. [`Receipt::movement_verified`] is always false by
//! construction.
//!
//! The encoder mirrors the Python `pci_serial_address` oracle byte for byte:
//! the body is `00` plus four big-endian serial bytes plus the destination,
//! the payload is `05 FF 00 0F` plus the body plus its inner checksum, an
//! optional outer SRCHK checksum covers the whole payload, and the frame is
//! `\` plus uppercase hex plus one confirmation byte plus `\r`.
//!
//! Compatibility notes: `local_unit: u8` accepts the full `0..=255` range
//! including `0`/`1`; the Python `pci_serial_address` oracle rejects the
//! bools `True`/`False` because `type(local_unit) is not int`
//! (`pci_serial_address.py:124`). All argument failures collapse to
//! [`EncodeError`], while the oracle raises `TypeError` for non-bytes
//! receipt input versus `ValueError` otherwise
//! (`pci_serial_address.py:126-127`).

use crate::{DecodeError, EncodeError};

/// Maximum captured exchange the receipt classifier accepts, in bytes.
const MAX_RECEIPT_BYTES: usize = 4096;

/// A parsed native decimal-dot serial number.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NativeSerial {
    /// First (20-bit) serial component.
    pub first: u32,
    /// Second (12-bit) serial component.
    pub second: u32,
    /// Decimal-dot form with leading zeros stripped.
    pub canonical: String,
    /// Four big-endian bytes of `(first << 12) | second`.
    pub packed: [u8; 4],
    /// False for the unknown serials `0.0` and `1048575.4095`.
    pub known: bool,
}

/// Parse an exact native decimal-dot serial number.
///
/// Mirrors the oracle: one dot, 1..16 ASCII decimal digits per side, first in
/// `0..1048575`, second in `0..4095`. Anything else is an [`EncodeError`].
pub fn parse_native_serial(value: &str) -> Result<NativeSerial, EncodeError> {
    let fail = || EncodeError::new("Expected a native decimal-dot serial number");
    let (first_text, second_text) = value.split_once('.').ok_or_else(fail)?;
    if second_text.contains('.') {
        return Err(fail());
    }
    for part in [first_text, second_text] {
        if part.is_empty() || part.len() > 16 || !part.bytes().all(|b| b.is_ascii_digit()) {
            return Err(fail());
        }
    }
    // 16 decimal digits fit in u64; the range checks below reject overflow.
    let first: u64 = first_text.parse().map_err(|_| fail())?;
    let second: u64 = second_text.parse().map_err(|_| fail())?;
    if first > 1_048_575 {
        return Err(EncodeError::new(
            "Native serial first component must be in 0..1048575",
        ));
    }
    if second > 4095 {
        return Err(EncodeError::new(
            "Native serial second component must be in 0..4095",
        ));
    }
    let first = first as u32;
    let second = second as u32;
    let combined = (first << 12) | second;
    Ok(NativeSerial {
        first,
        second,
        canonical: format!("{first}.{second}"),
        packed: combined.to_be_bytes(),
        known: (first, second) != (0, 0) && (first, second) != (1_048_575, 4095),
    })
}

fn cbus_checksum(data: &[u8]) -> u8 {
    let sum: u32 = data.iter().map(|&b| u32::from(b)).sum();
    ((256 - (sum % 256)) % 256) as u8
}

/// Encode one explicit serial/destination broadcast; do not transmit it.
///
/// The frame has no source-address field and cannot enforce source location.
/// Unknown serials, destinations outside `2..254`, and confirmation bytes
/// outside `g..z` are rejected.
pub fn encode_serial_address(
    serial: &str,
    destination: u8,
    command_checksum: bool,
    confirmation: u8,
) -> Result<Vec<u8>, EncodeError> {
    let selected = parse_native_serial(serial)?;
    if !selected.known {
        return Err(EncodeError::new(
            "Selected serial must be known; zero and FFFFFFFF are unsupported",
        ));
    }
    if !(2..=254).contains(&destination) {
        return Err(EncodeError::new(
            "Selected-serial destination must be an integer in the supported range 2..254",
        ));
    }
    if !(b'g'..=b'z').contains(&confirmation) {
        return Err(EncodeError::new(
            "Confirmation must be exactly one byte in g..z",
        ));
    }
    let mut body = Vec::with_capacity(6);
    body.push(0x00);
    body.extend_from_slice(&selected.packed);
    body.push(destination);
    let mut payload = vec![0x05, 0xFF, 0x00, 0x0F];
    payload.extend_from_slice(&body);
    payload.push(cbus_checksum(&body));
    if command_checksum {
        let outer = cbus_checksum(&payload);
        payload.push(outer);
    }
    let mut frame = Vec::with_capacity(2 * payload.len() + 3);
    frame.push(b'\\');
    frame.extend_from_slice(hex::encode(&payload).to_ascii_uppercase().as_bytes());
    frame.push(confirmation);
    frame.push(b'\r');
    Ok(frame)
}

/// Serial identity decoded from one receipt frame's CAL data.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ReceiptSerial {
    /// Decimal-dot serial from the four serial bytes.
    pub serial: String,
    /// False for the unknown serials `0.0` and `1048575.4095`.
    pub known: bool,
    /// The four serial bytes.
    pub packed: [u8; 4],
    /// Two opaque trailing bytes, retained without interpretation.
    pub tail: [u8; 2],
}

/// One parsed receipt frame: optional addressed header plus serial identity.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ReceiptFrame {
    /// Frame header byte (`0x86` for a direct receipt, `None` when bare).
    pub header: Option<u8>,
    /// Source unit for addressed frames, `None` when bare.
    pub source: Option<u8>,
    /// Destination unit for addressed frames, `None` when bare.
    pub destination: Option<u8>,
    /// Routing bytes (`00` direct, `01 00` captured programming response).
    pub route: Vec<u8>,
    /// Serial identity from the `87 00` reply CAL.
    pub reply: ReceiptSerial,
}

/// Decode the serial identity from one receipt frame payload in hex.
///
/// Accepts a direct addressed frame (for example
/// `86061000870018B106160000F8`) or a bare reply CAL (for example
/// `870018B10616000094`). Both carry a checksum, exactly one `87 00` reply
/// CAL, and six data bytes: four serial bytes plus a two-byte opaque tail.
pub fn decode_receipt_serial(frame_payload_hex: &str) -> Result<ReceiptSerial, DecodeError> {
    Ok(decode_receipt_frame(frame_payload_hex)?.reply)
}

/// Decode one receipt frame payload in hex into its header and serial.
///
/// See [`decode_receipt_serial`] for the accepted shapes.
pub fn decode_receipt_frame(frame_payload_hex: &str) -> Result<ReceiptFrame, DecodeError> {
    let frame = parse_frame_line(frame_payload_hex.as_bytes()).map_err(DecodeError::new)?;
    receipt_frame(frame)
}

/// Match predicate for the exact direct-receipt shape.
///
/// True only for header `0x86`, source equal to the expected destination,
/// destination equal to the local unit, route `00`, and serial equality.
/// Bare frames never match: without a header the reply is unattributed.
pub fn receipt_frame_matches(
    frame: &ReceiptFrame,
    expected_packed: &[u8; 4],
    expected_source: u8,
    local_unit: u8,
) -> bool {
    frame.header == Some(0x86)
        && frame.source == Some(expected_source)
        && frame.destination == Some(local_unit)
        && frame.route == [0x00]
        && frame.reply.packed == *expected_packed
}

/// Classification of one bounded captured PCI exchange.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ReceiptStatus {
    /// One successful expected confirmation before one exact direct receipt.
    Matched,
    /// Structurally parsed but not correlating (missing confirmation, bare
    /// receipt, or a header/source/destination/route/serial mismatch).
    Unverified,
    /// Multiple, foreign, reordered, or contradictory responses.
    Ambiguous,
    /// Framing, checksum, hex, prefix, or CAL errors.
    Invalid,
    /// Missing or truncated input.
    Incomplete,
    /// The expected confirmation reports rejection.
    Rejected,
}

impl ReceiptStatus {
    /// Wire-stable status name pinned by the compatibility vectors.
    pub fn as_str(self) -> &'static str {
        match self {
            ReceiptStatus::Matched => "matched",
            ReceiptStatus::Unverified => "unverified",
            ReceiptStatus::Ambiguous => "ambiguous",
            ReceiptStatus::Invalid => "invalid",
            ReceiptStatus::Incomplete => "incomplete",
            ReceiptStatus::Rejected => "rejected",
        }
    }
}

/// One structural reply decoded from a receipt frame.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SerialAddressReply {
    /// Frame header byte, `None` for unattributed bare receipts.
    pub header: Option<u8>,
    /// Source unit, `None` for bare receipts.
    pub source: Option<u8>,
    /// Destination unit, `None` for bare receipts.
    pub destination: Option<u8>,
    /// Routing bytes of the frame.
    pub route: Vec<u8>,
    /// Decimal-dot serial from the four serial bytes.
    pub serial: String,
    /// False for the unknown serials `0.0` and `1048575.4095`.
    pub serial_known: bool,
    /// The four serial bytes.
    pub packed_serial: [u8; 4],
    /// Two opaque trailing bytes, retained without interpretation.
    pub opaque_tail: [u8; 2],
    /// Original line bytes of the frame.
    pub raw: Vec<u8>,
}

/// Classification of one bounded captured PCI exchange without I/O.
///
/// A matched exchange requires one successful expected confirmation before
/// one exact direct `86`/target/local/`00` receipt with CAL `87 00` and the
/// selected serial. Every classification retains the original bytes.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Receipt {
    /// Expected serial in canonical decimal-dot form.
    pub expected_serial: String,
    /// Expected destination (the receipt's source unit).
    pub expected_destination: u8,
    /// Local unit (the receipt's destination unit).
    pub local_unit: u8,
    /// Expected confirmation code.
    pub expected_confirmation: u8,
    /// Original captured bytes.
    pub raw: Vec<u8>,
    /// Classification status.
    pub status: ReceiptStatus,
    /// Deduplicated issue tags in first-seen order.
    pub issues: Vec<String>,
    /// Framing/checksum error detail (non-empty exactly when invalid input
    /// was observed).
    pub errors: Vec<String>,
    /// Parsed confirmations as `(code, status)` pairs.
    pub confirmations: Vec<(u8, char)>,
    /// Structural replies decoded from receipt frames.
    pub replies: Vec<SerialAddressReply>,
    /// Unsolicited notification codes in arrival order.
    pub notifications: Vec<char>,
    /// Trailing bytes that do not form a complete event.
    pub pending: Vec<u8>,
}

impl Receipt {
    /// The bytes correlate; this is never proof of physical movement.
    pub fn matched(&self) -> bool {
        self.status == ReceiptStatus::Matched
    }

    /// Always false: correlation is not movement evidence.
    pub fn movement_verified(&self) -> bool {
        false
    }
}

/// Record an issue tag once, preserving first-seen order.
fn push_issue(issues: &mut Vec<String>, tag: &str) {
    if !issues.iter().any(|existing| existing == tag) {
        issues.push(tag.to_string());
    }
}

/// Classify one bounded captured PCI exchange without I/O or state changes.
///
/// See [`Receipt`] for the matching rule. Statuses `matched`, `unverified`,
/// `ambiguous`, `invalid`, `incomplete`, and `rejected` mirror the oracle;
/// [`Receipt::movement_verified`] is always false.
pub fn classify_receipt(
    data: &[u8],
    serial: &str,
    destination: u8,
    local_unit: u8,
    confirmation: u8,
) -> Result<Receipt, EncodeError> {
    let selected = parse_native_serial(serial)?;
    if !selected.known {
        return Err(EncodeError::new(
            "Selected serial must be known; zero and FFFFFFFF are unsupported",
        ));
    }
    if !(2..=254).contains(&destination) {
        return Err(EncodeError::new(
            "Selected-serial destination must be an integer in the supported range 2..254",
        ));
    }
    if !(b'g'..=b'z').contains(&confirmation) {
        return Err(EncodeError::new(
            "Confirmation must be exactly one byte in g..z",
        ));
    }
    if data.len() > MAX_RECEIPT_BYTES {
        return Err(EncodeError::new(
            "Receipt exceeds the supported 4096-byte captured exchange limit",
        ));
    }

    // Incremental from-PCI scan mirroring FrameStream: strip flow-control
    // bytes, skip bare line breaks, take `+`/`!` notifications, two-byte
    // confirmations, and `\r`-terminated frame lines.
    let stream: Vec<u8> = data
        .iter()
        .copied()
        .filter(|&b| b != 0x11 && b != 0x13)
        .collect();
    enum Event {
        Confirmation(u8, char),
        Frame(ParsedFrame),
        Notification(char),
    }
    let mut events: Vec<Event> = Vec::new();
    let mut invalid: Option<String> = None;
    let mut pos = 0;
    while pos < stream.len() {
        let byte = stream[pos];
        if byte == b'\n' || byte == b'\r' {
            pos += 1;
            continue;
        }
        if byte == b'+' || byte == b'!' {
            events.push(Event::Notification(byte as char));
            pos += 1;
            continue;
        }
        if (b'g'..=b'z').contains(&byte) {
            if pos + 1 >= stream.len() {
                break;
            }
            let status = stream[pos + 1] as char;
            if !matches!(status, '.' | '#' | '$' | '%' | '!') {
                invalid = Some(format!("Invalid PCI confirmation status {status:?}"));
                break;
            }
            events.push(Event::Confirmation(byte, status));
            pos += 2;
            continue;
        }
        let Some(end) = stream[pos..].iter().position(|&b| b == b'\r') else {
            break;
        };
        let end = pos + end;
        if end - pos > MAX_RECEIPT_BYTES {
            invalid = Some("PCI frame exceeds maximum buffer size".to_string());
            pos = stream.len();
            break;
        }
        let line = stream[pos..end].to_vec();
        pos = end + 1;
        match parse_frame_line(&line) {
            Ok(frame) => events.push(Event::Frame(frame)),
            Err(error) => {
                invalid = Some(error);
                break;
            }
        }
    }
    let pending = stream[pos..].to_vec();

    let mut confirmations: Vec<(u8, char)> = Vec::new();
    let mut frames: Vec<ParsedFrame> = Vec::new();
    let mut notifications: Vec<char> = Vec::new();
    for event in &events {
        match event {
            Event::Confirmation(code, status) => confirmations.push((*code, *status)),
            Event::Frame(frame) => frames.push(frame.clone()),
            Event::Notification(code) => notifications.push(*code),
        }
    }

    let mut issues: Vec<String> = Vec::new();
    let mut errors: Vec<String> = Vec::new();
    if let Some(error) = invalid {
        push_issue(&mut issues, "invalid_framing_or_checksum");
        errors.push(error);
    }

    let mut replies: Vec<SerialAddressReply> = Vec::new();
    for frame in &frames {
        if frame.cals.len() != 1 {
            push_issue(&mut issues, "multiple_cals");
            continue;
        }
        let (parameter, reply_data) = match &frame.cals[0] {
            ReceiptCal::Reply(parameter, reply_data) => (*parameter, reply_data.clone()),
            _ => {
                push_issue(&mut issues, "unsupported_receipt_cal");
                continue;
            }
        };
        if parameter != 0 || reply_data.len() != 6 {
            push_issue(&mut issues, "unsupported_receipt_cal");
            continue;
        }
        let value =
            u32::from_be_bytes([reply_data[0], reply_data[1], reply_data[2], reply_data[3]]);
        let known = value != 0 && value != 0xFFFF_FFFF;
        replies.push(SerialAddressReply {
            header: frame.header,
            source: frame.source,
            destination: frame.destination,
            route: frame.route.clone(),
            serial: format!("{}.{}", value >> 12, value & 4095),
            serial_known: known,
            packed_serial: [reply_data[0], reply_data[1], reply_data[2], reply_data[3]],
            opaque_tail: [reply_data[4], reply_data[5]],
            raw: frame.raw.clone(),
        });
    }

    let mut ambiguous = false;
    if confirmations.len() > 1 {
        push_issue(&mut issues, "multiple_confirmations");
        ambiguous = true;
    }
    if confirmations.iter().any(|(code, _)| *code != confirmation) {
        push_issue(&mut issues, "foreign_confirmation");
        ambiguous = true;
    }
    if frames.len() > 1 {
        push_issue(&mut issues, "multiple_frames");
        ambiguous = true;
    }
    if issues.iter().any(|tag| tag == "multiple_cals") {
        ambiguous = true;
    }
    if !notifications.is_empty() {
        push_issue(&mut issues, "unsolicited_notification");
        ambiguous = true;
    }
    let first_frame = events.iter().position(|e| matches!(e, Event::Frame(_)));
    let first_confirmation = events
        .iter()
        .position(|e| matches!(e, Event::Confirmation(_, _)));
    if let (Some(frame_at), Some(conf_at)) = (first_frame, first_confirmation) {
        if frame_at < conf_at {
            push_issue(&mut issues, "receipt_before_confirmation");
            ambiguous = true;
        }
    }
    let rejected = confirmations
        .iter()
        .any(|(code, status)| *code == confirmation && *status != '.');
    if rejected {
        push_issue(&mut issues, "command_rejected");
        if !frames.is_empty() {
            push_issue(&mut issues, "receipt_after_rejection");
            ambiguous = true;
        }
    }
    if confirmations.is_empty() {
        push_issue(&mut issues, "missing_confirmation");
    }
    if frames.is_empty() {
        push_issue(&mut issues, "missing_receipt");
    }
    for reply in &replies {
        match reply.header {
            None => push_issue(&mut issues, "bare_receipt_unattributed"),
            Some(header) if header != 0x86 => push_issue(&mut issues, "unsupported_receipt_header"),
            _ => {}
        }
        if reply.source != Some(destination) {
            push_issue(&mut issues, "source_mismatch");
        }
        if reply.destination != Some(local_unit) {
            push_issue(&mut issues, "local_destination_mismatch");
        }
        if reply.route != [0x00] {
            push_issue(&mut issues, "route_mismatch");
        }
        if reply.packed_serial != selected.packed {
            push_issue(&mut issues, "serial_mismatch");
        }
        if !reply.serial_known {
            push_issue(&mut issues, "unknown_serial");
        }
    }
    if !pending.is_empty() {
        push_issue(&mut issues, "truncated_input");
    }

    let invalid = !errors.is_empty() || issues.iter().any(|t| t == "invalid_framing_or_checksum");
    let status = if invalid {
        ReceiptStatus::Invalid
    } else if ambiguous {
        ReceiptStatus::Ambiguous
    } else if !pending.is_empty() {
        ReceiptStatus::Incomplete
    } else if rejected {
        ReceiptStatus::Rejected
    } else if frames.is_empty() {
        ReceiptStatus::Incomplete
    } else if !issues.is_empty() {
        ReceiptStatus::Unverified
    } else {
        ReceiptStatus::Matched
    };

    Ok(Receipt {
        expected_serial: selected.canonical,
        expected_destination: destination,
        local_unit,
        expected_confirmation: confirmation,
        raw: data.to_vec(),
        status,
        issues,
        errors,
        confirmations,
        replies,
        notifications,
        pending,
    })
}

/// One CAL of a from-PCI receipt frame.
#[derive(Debug, Clone, PartialEq, Eq)]
enum ReceiptCal {
    /// `0x21` identify request (unsupported as a receipt).
    Identify(u8),
    /// `0x1A` recall request (unsupported as a receipt).
    Recall(u8, u8),
    /// `0x32` acknowledgement; bare-allowed but never a serial receipt.
    Ack(u8, u8),
    /// `0x8x` reply: parameter plus payload.
    Reply(u8, Vec<u8>),
    /// `0xAx` write (unsupported as a receipt).
    Write(u8, Vec<u8>),
}

fn decode_cal(data: &[u8]) -> Result<(ReceiptCal, usize), String> {
    let opcode = *data
        .first()
        .ok_or_else(|| "Missing CAL opcode".to_string())?;
    let family = opcode & 0xE0;
    let length = if opcode == 0x21 || opcode == 0x1A || opcode == 0x32 {
        if opcode == 0x21 {
            2
        } else {
            3
        }
    } else if family == 0x80 || family == 0xA0 {
        if opcode & 0x1F == 0 {
            return Err("CAL count must include a parameter byte".to_string());
        }
        1 + usize::from(opcode & 0x1F)
    } else {
        return Err(format!("Unsupported CAL opcode 0x{opcode:02X}"));
    };
    if data.len() < length {
        return Err(format!(
            "Truncated CAL: expected {length} bytes, received {}",
            data.len()
        ));
    }
    match opcode {
        0x21 => Ok((ReceiptCal::Identify(data[1]), length)),
        0x1A => {
            if data[2] == 0 {
                return Err("Recall count must be positive".to_string());
            }
            Ok((ReceiptCal::Recall(data[1], data[2]), length))
        }
        0x32 => Ok((ReceiptCal::Ack(data[1], data[2]), length)),
        _ if family == 0x80 => Ok((ReceiptCal::Reply(data[1], data[2..length].to_vec()), length)),
        _ => Ok((ReceiptCal::Write(data[1], data[2..length].to_vec()), length)),
    }
}

fn decode_cals(mut data: &[u8]) -> Result<Vec<ReceiptCal>, String> {
    let mut cals = Vec::new();
    while !data.is_empty() {
        let (cal, consumed) = decode_cal(data)?;
        cals.push(cal);
        data = &data[consumed..];
    }
    if cals.is_empty() {
        return Err("Empty CAL message".to_string());
    }
    Ok(cals)
}

/// One parsed from-PCI frame line with its original bytes.
#[derive(Debug, Clone, PartialEq, Eq)]
struct ParsedFrame {
    header: Option<u8>,
    source: Option<u8>,
    destination: Option<u8>,
    route: Vec<u8>,
    cals: Vec<ReceiptCal>,
    payload: Vec<u8>,
    raw: Vec<u8>,
}

/// Parse one `\r`-terminated from-PCI frame line (checksum enforced).
///
/// Mirrors `decode_frame` on the from-PCI path: an addressed header of `06`,
/// `46`, `86`, or `C6` with `00` or `01 00` routing takes precedence, and a
/// CAL-only reply is otherwise decoded bare without a fabricated source.
fn parse_frame_line(line: &[u8]) -> Result<ParsedFrame, String> {
    if line.is_empty()
        || !line.len().is_multiple_of(2)
        || !line.iter().all(|b| b.is_ascii_hexdigit())
    {
        return Err("Frame must contain an even number of hexadecimal characters".to_string());
    }
    let payload = hex::decode(line)
        .map_err(|_| "Frame must contain an even number of hexadecimal characters".to_string())?;
    let sum: u32 = payload.iter().map(|&b| u32::from(b)).sum();
    if payload.len() < 2 || !sum.is_multiple_of(256) {
        return Err("Invalid C-Bus checksum".to_string());
    }
    let body = &payload[..payload.len() - 1];
    let mut addressed_error: Option<String> = None;
    if [0x06, 0x46, 0x86, 0xC6].contains(&body[0]) {
        if body.len() >= 5 {
            let (route, offset) = if body[3] == 0 {
                (vec![0x00], 4)
            } else if body[3..5] == [0x01, 0x00] {
                (vec![0x01, 0x00], 5)
            } else {
                addressed_error = Some("Unsupported response routing".to_string());
                (Vec::new(), 0)
            };
            if addressed_error.is_none() {
                match decode_cals(&body[offset..]) {
                    Ok(cals) => {
                        return Ok(ParsedFrame {
                            header: Some(body[0]),
                            source: Some(body[1]),
                            destination: Some(body[2]),
                            route,
                            cals,
                            payload: body.to_vec(),
                            raw: line.to_vec(),
                        });
                    }
                    Err(error) => addressed_error = Some(error),
                }
            }
        } else {
            addressed_error = Some("Truncated point-to-point header".to_string());
        }
    }
    match decode_cals(body) {
        Ok(cals) => {
            if !cals
                .iter()
                .all(|cal| matches!(cal, ReceiptCal::Reply(..) | ReceiptCal::Ack(..)))
            {
                return Err(format!(
                    "Unsupported PCI frame: {}; Unsupported bare PCI response",
                    addressed_error.unwrap_or_else(|| "no addressed header".to_string())
                ));
            }
            Ok(ParsedFrame {
                header: None,
                source: None,
                destination: None,
                route: Vec::new(),
                cals,
                payload: body.to_vec(),
                raw: line.to_vec(),
            })
        }
        Err(bare_error) => Err(format!(
            "Unsupported PCI frame: {}; {bare_error}",
            addressed_error.unwrap_or_else(|| "no addressed header".to_string())
        )),
    }
}

fn receipt_frame(frame: ParsedFrame) -> Result<ReceiptFrame, DecodeError> {
    if frame.cals.len() != 1 {
        return Err(DecodeError::new("Receipt frame must contain one reply CAL"));
    }
    let (parameter, reply_data) = match &frame.cals[0] {
        ReceiptCal::Reply(parameter, reply_data) => (*parameter, reply_data.clone()),
        _ => return Err(DecodeError::new("Unsupported receipt CAL")),
    };
    if parameter != 0 || reply_data.len() != 6 {
        return Err(DecodeError::new("Unsupported receipt CAL"));
    }
    let value = u32::from_be_bytes([reply_data[0], reply_data[1], reply_data[2], reply_data[3]]);
    Ok(ReceiptFrame {
        header: frame.header,
        source: frame.source,
        destination: frame.destination,
        route: frame.route,
        reply: ReceiptSerial {
            serial: format!("{}.{}", value >> 12, value & 4095),
            known: value != 0 && value != 0xFFFF_FFFF,
            packed: [reply_data[0], reply_data[1], reply_data[2], reply_data[3]],
            tail: [reply_data[4], reply_data[5]],
        },
    })
}
