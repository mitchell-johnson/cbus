//! Pure codecs for bounded PCI observation evidence.
//!
//! These helpers contain the wire rules shared by transport-level evidence
//! validators: command framing, addressed and bare CAL response parsing,
//! incremental PCI event framing, and installation MMI block decoding. They
//! perform no I/O and retain the original hexadecimal line bytes so callers
//! can compare an observation with its recorded evidence.

use crate::cal::Cal;
use crate::common::{cbus_checksum, validate_cbus_checksum};
use crate::decode::decode_packet_install_mmi;
use crate::packet::Packet;

const DEFAULT_MAX_BUFFER: usize = 8192;

/// Encode one payload as a checksummed-or-unchecksummed PCI command using
/// confirmation code `g`.
fn encode_command(payload: &[u8], command_checksum: bool) -> Vec<u8> {
    let mut full = payload.to_vec();
    if command_checksum {
        full.push(cbus_checksum(payload));
    }
    let mut out = Vec::with_capacity(2 * full.len() + 3);
    out.push(b'\\');
    out.extend_from_slice(hex::encode_upper(full).as_bytes());
    out.extend_from_slice(b"g\r");
    out
}

/// Encode an addressed CAL IDENTIFY request using confirmation code `g`.
pub fn identify_request(address: u8, attribute: u8, command_checksum: bool) -> Vec<u8> {
    encode_command(&[0x46, address, 0x00, 0x21, attribute], command_checksum)
}

/// Encode an addressed CAL RECALL request using confirmation code `g`.
pub fn recall_request(address: u8, parameter: u8, count: u8, command_checksum: bool) -> Vec<u8> {
    encode_command(
        &[0x46, address, 0x00, 0x1A, parameter, count],
        command_checksum,
    )
}

/// Encode the installation MMI request using confirmation code `g`.
pub fn installation_mmi_request(command_checksum: bool) -> Vec<u8> {
    encode_command(&[0x05, 0xFF, 0x00, 0xFA, 0xFF, 0x00], command_checksum)
}

/// Encode an addressed CAL IDENTIFY sent through `bridges` (nearest first)
/// using confirmation code `g`: header `46`, nearest bridge, `9 x count`,
/// the remaining bridges, then the far unit. No bridges is the direct form.
pub fn routed_identify_request(
    bridges: &[u8],
    address: u8,
    attribute: u8,
    command_checksum: bool,
) -> Vec<u8> {
    let Some((first, rest)) = bridges.split_first() else {
        return identify_request(address, attribute, command_checksum);
    };
    let mut payload = vec![0x46, *first, (bridges.len() as u8).wrapping_mul(9)];
    payload.extend_from_slice(rest);
    payload.extend_from_slice(&[address, 0x21, attribute]);
    encode_command(&payload, command_checksum)
}

/// Encode the installation MMI request for the network reached through
/// `bridges` (native `NET PINGU` point-to-point-to-multipoint form) using
/// confirmation code `g`. No bridges is the direct form.
pub fn routed_installation_mmi_request(bridges: &[u8], command_checksum: bool) -> Vec<u8> {
    let Some((first, rest)) = bridges.split_first() else {
        return installation_mmi_request(command_checksum);
    };
    let mut payload = vec![0x03, *first, (bridges.len() as u8).wrapping_mul(9)];
    payload.extend_from_slice(rest);
    payload.extend_from_slice(&[0xFF, 0xFA, 0xFF, 0x00]);
    encode_command(&payload, command_checksum)
}

/// One checksummed frame line returned by a PCI.
#[derive(Debug, Clone, PartialEq)]
pub struct PciFrame {
    /// Frame header byte, or `None` for an unattributed bare CAL response.
    pub header: Option<u8>,
    /// Source unit for an addressed response.
    pub source: Option<u8>,
    /// Destination unit for an addressed response.
    pub destination: Option<u8>,
    /// Exact direct/programming route bytes. A routed parse also admits a
    /// Reply Network: its count byte (1..=6) followed by every entry, the
    /// last being the replying unit; `source` is then the nearest bridge.
    pub route: Vec<u8>,
    /// Decoded CAL messages in wire order.
    pub cals: Vec<Cal>,
    /// Original hexadecimal line bytes, excluding the line terminator.
    pub raw: Vec<u8>,
}

impl PciFrame {
    /// True when the response has no attributable addressed header.
    pub fn bare(&self) -> bool {
        self.header.is_none()
    }
}

/// One event from an incremental PCI response capture.
#[derive(Debug, Clone, PartialEq)]
pub enum PciEvent {
    /// Two-byte command confirmation `(code, status)`.
    Confirmation(u8, char),
    /// One checksummed CAL response frame.
    Frame(PciFrame),
    /// One unsolicited one-byte notification.
    Notification(char),
}

fn is_hex_line(line: &[u8]) -> bool {
    !line.is_empty() && line.len().is_multiple_of(2) && line.iter().all(u8::is_ascii_hexdigit)
}

/// Decode the CAL subset admitted in serial-identity and local-options
/// observations. The subset is deliberately narrower than the general CAL
/// decoder because an observation must reject unrelated protocol traffic.
fn decode_observation_cal(data: &[u8]) -> Result<(Cal, usize), String> {
    let opcode = *data
        .first()
        .ok_or_else(|| "Missing CAL opcode".to_string())?;
    let (cal, consumed) = Cal::decode_one(data).map_err(|_| {
        // Receipt compatibility vectors predate the shared CAL decoder and
        // pin these diagnostics. Parsing still belongs to `Cal::decode_one`;
        // this projection only preserves the established error text.
        let family = opcode & 0xE0;
        let expected = if opcode == 0x21 {
            Some(2)
        } else if opcode == 0x1A || opcode == 0x32 {
            Some(3)
        } else if family == 0x80 || family == 0xA0 {
            let count = usize::from(opcode & 0x1F);
            if count == 0 {
                return "CAL count must include a parameter byte".to_string();
            }
            Some(1 + count)
        } else {
            None
        };
        match expected {
            Some(length) if data.len() < length => format!(
                "Truncated CAL: expected {length} bytes, received {}",
                data.len()
            ),
            _ => format!("Unsupported CAL opcode 0x{opcode:02X}"),
        }
    })?;
    let admitted_opcode =
        matches!(opcode, 0x21 | 0x1A | 0x32) || opcode & 0xE0 == 0x80 || opcode & 0xE0 == 0xA0;
    if !admitted_opcode {
        return Err(format!("Unsupported CAL opcode 0x{opcode:02X}"));
    }
    match &cal {
        Cal::Recall { count: 0, .. } => Err("Recall count must be positive".to_string()),
        Cal::Identify { .. }
        | Cal::Recall { .. }
        | Cal::Ack { .. }
        | Cal::Reply { .. }
        | Cal::Write { .. } => Ok((cal, consumed)),
        _ => Err(format!("Unsupported CAL opcode 0x{opcode:02X}")),
    }
}

fn decode_observation_cals(mut data: &[u8]) -> Result<Vec<Cal>, String> {
    let mut cals = Vec::new();
    while !data.is_empty() {
        let (cal, consumed) = decode_observation_cal(data)?;
        cals.push(cal);
        data = &data[consumed..];
    }
    if cals.is_empty() {
        return Err("Empty CAL message".to_string());
    }
    Ok(cals)
}

/// Parse one hexadecimal frame line returned by a PCI and enforce its C-Bus
/// checksum.
///
/// Addressed headers `06`, `46`, `86`, and `C6` accept direct route `00` or
/// captured programming route `01 00`. A CAL-only reply is otherwise decoded
/// as bare without fabricating a source address.
pub fn parse_frame_line(line: &[u8]) -> Result<PciFrame, String> {
    parse_frame_line_with_routes(line, false)
}

/// Parse one frame line like [`parse_frame_line`], additionally admitting a
/// Reply Network route of one to six entries. Correlation stays with the
/// caller, which compares the whole route with its expected path.
pub fn parse_routed_frame_line(line: &[u8]) -> Result<PciFrame, String> {
    parse_frame_line_with_routes(line, true)
}

fn parse_frame_line_with_routes(line: &[u8], routed: bool) -> Result<PciFrame, String> {
    if !is_hex_line(line) {
        return Err("Frame must contain an even number of hexadecimal characters".to_string());
    }
    let payload = hex::decode(line)
        .map_err(|_| "Frame must contain an even number of hexadecimal characters".to_string())?;
    if payload.len() < 2 || !validate_cbus_checksum(&payload) {
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
            } else if routed && (1..=6).contains(&body[3]) && body.len() > 4 + usize::from(body[3])
            {
                let end = 4 + usize::from(body[3]);
                (body[3..end].to_vec(), end)
            } else {
                addressed_error = Some("Unsupported response routing".to_string());
                (Vec::new(), 0)
            };
            if addressed_error.is_none() {
                match decode_observation_cals(&body[offset..]) {
                    Ok(cals) => {
                        return Ok(PciFrame {
                            header: Some(body[0]),
                            source: Some(body[1]),
                            destination: Some(body[2]),
                            route,
                            cals,
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
    match decode_observation_cals(body) {
        Ok(cals) => {
            if !cals
                .iter()
                .all(|cal| matches!(cal, Cal::Reply { .. } | Cal::Ack { .. }))
            {
                return Err(format!(
                    "Unsupported PCI frame: {}; Unsupported bare PCI response",
                    addressed_error.unwrap_or_else(|| "no addressed header".to_string())
                ));
            }
            Ok(PciFrame {
                header: None,
                source: None,
                destination: None,
                route: Vec::new(),
                cals,
                raw: line.to_vec(),
            })
        }
        Err(bare_error) => Err(format!(
            "Unsupported PCI frame: {}; {bare_error}",
            addressed_error.unwrap_or_else(|| "no addressed header".to_string())
        )),
    }
}

/// Incrementally parse a captured PCI response stream.
///
/// XON/XOFF bytes and bare line endings are ignored. Complete notifications,
/// confirmations, and checksummed frame lines are returned in wire order;
/// an incomplete tail is returned separately.
pub fn parse_capture(raw: &[u8]) -> Result<(Vec<PciEvent>, Vec<u8>), String> {
    parse_capture_with_routes(raw, false)
}

/// Incrementally parse a captured PCI response stream whose frames may carry
/// a Reply Network route (see [`parse_routed_frame_line`]).
pub fn parse_routed_capture(raw: &[u8]) -> Result<(Vec<PciEvent>, Vec<u8>), String> {
    parse_capture_with_routes(raw, true)
}

fn parse_capture_with_routes(raw: &[u8], routed: bool) -> Result<(Vec<PciEvent>, Vec<u8>), String> {
    let mut buffer: Vec<u8> = Vec::new();
    let mut events = Vec::new();
    for &byte in raw {
        if byte == 0x11 || byte == 0x13 {
            continue;
        }
        buffer.push(byte);
        loop {
            if buffer.is_empty() {
                break;
            }
            if buffer[0] == b'\n' || buffer[0] == b'\r' {
                buffer.remove(0);
                continue;
            }
            if buffer[0] == b'+' || buffer[0] == b'!' {
                events.push(PciEvent::Notification(buffer.remove(0) as char));
                continue;
            }
            if (b'g'..=b'z').contains(&buffer[0]) {
                if buffer.len() < 2 {
                    break;
                }
                let code = buffer[0];
                let status = buffer[1] as char;
                if !matches!(status, '.' | '#' | '$' | '%' | '!') {
                    return Err(format!("Invalid PCI confirmation status {status:?}"));
                }
                buffer.drain(..2);
                events.push(PciEvent::Confirmation(code, status));
                continue;
            }
            let Some(end) = buffer.iter().position(|&b| b == b'\r') else {
                if buffer.len() > DEFAULT_MAX_BUFFER {
                    return Err("PCI frame exceeds maximum buffer size".to_string());
                }
                break;
            };
            if end > DEFAULT_MAX_BUFFER {
                return Err("PCI frame exceeds maximum buffer size".to_string());
            }
            let line: Vec<u8> = buffer.drain(..end).collect();
            buffer.remove(0);
            events.push(PciEvent::Frame(parse_frame_line_with_routes(
                &line, routed,
            )?));
        }
    }
    Ok((events, buffer))
}

/// One decoded standard-status installation MMI block.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MmiBlock {
    /// Application address reported by the block.
    pub application: u8,
    /// First unit address represented by `states`.
    pub start: u8,
    /// Two-bit unit states in ascending address order.
    pub states: Vec<u8>,
    /// Original C/D marker and byte-count field.
    pub marker: u8,
    /// Original hexadecimal line bytes, excluding the line terminator.
    pub raw: Vec<u8>,
    /// Routed blocks only: the replying unit ending the exact Reply Network.
    pub reply_unit: Option<u8>,
}

/// One event from an incremental installation MMI response capture.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum MmiEvent {
    /// Two-byte command confirmation `(code, status)`.
    Confirmation(u8, char),
    /// One valid standard-status block.
    Block(MmiBlock),
    /// One unsolicited one-byte notification.
    Notification(char),
    /// A valid checksummed line that is not a standard-status block.
    OtherFrame,
}

fn parse_mmi_line(line: &[u8]) -> Result<Option<MmiBlock>, String> {
    if !is_hex_line(line) {
        return Err("MMI transport frame must contain even-length hexadecimal text".to_string());
    }
    let data = hex::decode(line)
        .map_err(|_| "MMI transport frame must contain even-length hexadecimal text".to_string())?;
    if data.len() < 2 || !validate_cbus_checksum(&data) {
        return Err("Invalid C-Bus checksum".to_string());
    }
    if data[0] & 0xE0 != 0xC0 {
        return Ok(None);
    }
    let count = data[0] & 31;
    if count < 3 || data.len() != usize::from(count) + 2 {
        return Err("Invalid standard MMI block length".to_string());
    }
    if data[1] != 0xFF {
        return Ok(None);
    }
    let mut wire = hex::encode_upper(&data).into_bytes();
    wire.extend_from_slice(b"\r\n");
    let (packet, consumed) = decode_packet_install_mmi(&wire, true, true, true);
    let Some(Packet::StandardStatus {
        application,
        block_start,
        states,
    }) = packet
    else {
        let state_count = (data.len() - 4) * 4;
        if usize::from(data[2]) + state_count > 256 {
            return Err("MMI block extends beyond address 255".to_string());
        }
        return Err("Invalid standard MMI block length".to_string());
    };
    if consumed != wire.len() {
        return Err("Invalid standard MMI block length".to_string());
    }
    if usize::from(block_start) + states.len() > 256 {
        return Err("MMI block extends beyond address 255".to_string());
    }
    Ok(Some(MmiBlock {
        application,
        start: block_start,
        states,
        marker: data[0],
        raw: line.to_vec(),
        reply_unit: None,
    }))
}

/// One Reply Network extended-status MMI block for `bridges`, or `None` for
/// traffic that cannot belong to that routed request.
///
/// The frame is addressed `06`/`86` from the nearest bridge to `local`, its
/// count equals the bridge count, and its entries repeat the remaining
/// bridges followed by the replying unit (recorded, not required). Its single
/// CAL is extended status: `E0|length`, binary coding `00`/`40`, application
/// `FF`, block start and two-bit states.
fn parse_routed_mmi_line(
    line: &[u8],
    bridges: &[u8],
    local: u8,
) -> Result<Option<MmiBlock>, String> {
    if !is_hex_line(line) {
        return Err("MMI transport frame must contain even-length hexadecimal text".to_string());
    }
    let data = hex::decode(line)
        .map_err(|_| "MMI transport frame must contain even-length hexadecimal text".to_string())?;
    if data.len() < 2 || !validate_cbus_checksum(&data) {
        return Err("Invalid C-Bus checksum".to_string());
    }
    let count = bridges.len();
    if count == 0
        || data[0] & 0xE0 == 0xC0
        || !matches!(data[0], 0x06 | 0x86)
        || data.len() < 6
        || data[3] > 6
    {
        return Ok(None);
    }
    if data[1] != bridges[0]
        || data[2] != local
        || usize::from(data[3]) != count
        || data.len() < 5 + count
        || data[4..3 + count] != bridges[1..]
    {
        return Ok(None);
    }
    let cal = &data[4 + count..data.len() - 1];
    if cal.len() < 4
        || cal[0] & 0xE0 != 0xE0
        || usize::from(cal[0] & 0x1F) + 1 != cal.len()
        || !matches!(cal[1], 0x00 | 0x40)
        || cal[2] != 0xFF
    {
        return Ok(None);
    }
    let mut states = Vec::with_capacity((cal.len() - 4) * 4);
    for byte in &cal[4..] {
        for shift in [0, 2, 4, 6] {
            states.push((byte >> shift) & 3);
        }
    }
    if usize::from(cal[3]) + states.len() > 256 {
        return Err("MMI block extends beyond address 255".to_string());
    }
    Ok(Some(MmiBlock {
        application: cal[2],
        start: cal[3],
        states,
        marker: cal[0],
        raw: line.to_vec(),
        reply_unit: Some(data[3 + count]),
    }))
}

/// Incrementally parse a captured installation MMI response stream.
pub fn parse_mmi_capture(raw: &[u8]) -> Result<(Vec<MmiEvent>, Vec<u8>), String> {
    parse_mmi_capture_for_route(raw, &[], 0)
}

/// Incrementally parse a routed installation MMI capture: only exact Reply
/// Network extended-status blocks for `bridges` and `local` are blocks;
/// direct blocks and other routes are [`MmiEvent::OtherFrame`].
pub fn parse_routed_mmi_capture(
    raw: &[u8],
    bridges: &[u8],
    local: u8,
) -> Result<(Vec<MmiEvent>, Vec<u8>), String> {
    parse_mmi_capture_for_route(raw, bridges, local)
}

fn parse_mmi_capture_for_route(
    raw: &[u8],
    bridges: &[u8],
    local: u8,
) -> Result<(Vec<MmiEvent>, Vec<u8>), String> {
    let mut buffer: Vec<u8> = Vec::new();
    let mut events = Vec::new();
    for &byte in raw {
        if byte == 0x11 || byte == 0x13 {
            continue;
        }
        buffer.push(byte);
        loop {
            if buffer.is_empty() {
                break;
            }
            if buffer[0] == b'\n' || buffer[0] == b'\r' {
                buffer.remove(0);
                continue;
            }
            if buffer[0] == b'+' || buffer[0] == b'!' {
                events.push(MmiEvent::Notification(buffer.remove(0) as char));
                continue;
            }
            if (b'g'..=b'z').contains(&buffer[0]) {
                if buffer.len() < 2 {
                    break;
                }
                let code = buffer[0];
                let status = buffer[1] as char;
                if !matches!(status, '.' | '#' | '$' | '%' | '!') {
                    return Err("Invalid PCI confirmation status".to_string());
                }
                buffer.drain(..2);
                events.push(MmiEvent::Confirmation(code, status));
                continue;
            }
            let Some(end) = buffer.iter().position(|&b| b == b'\r') else {
                if buffer.len() > DEFAULT_MAX_BUFFER {
                    return Err("MMI transport frame exceeds buffer limit".to_string());
                }
                break;
            };
            let line: Vec<u8> = buffer.drain(..end).collect();
            buffer.remove(0);
            let parsed = if bridges.is_empty() {
                parse_mmi_line(&line)?
            } else {
                parse_routed_mmi_line(&line, bridges, local)?
            };
            match parsed {
                Some(block) => events.push(MmiEvent::Block(block)),
                None => events.push(MmiEvent::OtherFrame),
            }
        }
    }
    Ok((events, buffer))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn request_encoders_match_selected_serial_oracle() {
        assert_eq!(identify_request(16, 4, false), b"\\4610002104g\r");
        assert_eq!(identify_request(16, 4, true), b"\\461000210485g\r");
        assert_eq!(recall_request(16, 66, 1, false), b"\\4610001A4201g\r");
        assert_eq!(recall_request(16, 66, 1, true), b"\\4610001A42014Dg\r");
        assert_eq!(installation_mmi_request(false), b"\\05FF00FAFF00g\r");
        assert_eq!(installation_mmi_request(true), b"\\05FF00FAFF0003g\r");
    }

    #[test]
    fn capture_decodes_addressed_serial_reply() {
        let raw = b"g.86061000870018B106160000F8\r\n";
        let (events, pending) = parse_capture(raw).unwrap();
        assert!(pending.is_empty());
        assert_eq!(events[0], PciEvent::Confirmation(b'g', '.'));
        let PciEvent::Frame(frame) = &events[1] else {
            panic!("expected a frame")
        };
        assert!(!frame.bare());
        assert_eq!(frame.header, Some(0x86));
        assert_eq!(frame.source, Some(6));
        assert_eq!(frame.destination, Some(16));
        assert_eq!(frame.route, [0]);
        assert!(matches!(
            &frame.cals[..],
            [Cal::Reply {
                parameter: 0,
                data
            }] if data.len() == 6
        ));
    }

    #[test]
    fn routed_requests_match_native_and_python_forms() {
        assert_eq!(
            routed_installation_mmi_request(&[0x20], true),
            b"\\032009FFFAFF00DCg\r"
        );
        assert_eq!(
            routed_installation_mmi_request(&[0xFD, 0xFC], true),
            b"\\03FD12FCFFFAFF00FAg\r"
        );
        assert_eq!(
            routed_identify_request(&[253, 252], 255, 4, false),
            b"\\46FD12FCFF2104g\r"
        );
        assert_eq!(
            routed_identify_request(&[], 16, 4, false),
            identify_request(16, 4, false)
        );
    }

    #[test]
    fn routed_capture_keeps_the_whole_reply_network() {
        // 86 FD(nearest bridge) 10(PCI) 02 FC(next bridge) 06(unit) 87 00 serial tail.
        let mut payload = hex::decode("86FD1002FC06870018B106160000").unwrap();
        payload.push(cbus_checksum(&payload));
        let mut wire = b"g.".to_vec();
        wire.extend_from_slice(hex::encode_upper(&payload).as_bytes());
        wire.extend_from_slice(b"\r\n");
        assert!(parse_capture(&wire).is_err());
        let (events, pending) = parse_routed_capture(&wire).unwrap();
        assert!(pending.is_empty());
        let PciEvent::Frame(frame) = &events[1] else {
            panic!("expected a frame")
        };
        assert_eq!((frame.source, frame.destination), (Some(0xFD), Some(0x10)));
        assert_eq!(frame.route, [2, 0xFC, 6]);
    }

    #[test]
    fn routed_mmi_accepts_only_the_exact_reply_network() {
        let block = |bridges: &[u8], local: u8| {
            let mut payload = vec![0x86, bridges[0], local, bridges.len() as u8];
            payload.extend_from_slice(&bridges[1..]);
            payload.extend_from_slice(&[0x01, 0xE0 | 5, 0x00, 0xFF, 0x00, 0x04, 0x00]);
            payload.push(cbus_checksum(&payload));
            let mut line = hex::encode_upper(&payload).into_bytes();
            line.extend_from_slice(b"\r\n");
            line
        };
        let (events, _) =
            parse_routed_mmi_capture(&block(&[0xFD, 0xFC], 16), &[0xFD, 0xFC], 16).unwrap();
        let MmiEvent::Block(parsed) = &events[0] else {
            panic!("expected a routed block")
        };
        assert_eq!(
            (parsed.start, parsed.states.len(), parsed.states[1]),
            (0, 8, 1)
        );
        assert_eq!(parsed.reply_unit, Some(1));
        for (wire, bridges, local) in [
            (block(&[0xFE, 0xFC], 16), [0xFD, 0xFC], 16),
            (block(&[0xFD, 0xFB], 16), [0xFD, 0xFC], 16),
            (block(&[0xFD, 0xFC], 17), [0xFD, 0xFC], 16),
        ] {
            let (events, _) = parse_routed_mmi_capture(&wire, &bridges, local).unwrap();
            assert_eq!(events, [MmiEvent::OtherFrame]);
        }
        let direct = b"D8FF000000000001000000000000000000000000000000000028\r\n";
        let (events, _) = parse_routed_mmi_capture(direct, &[0xFD], 16).unwrap();
        assert_eq!(events, [MmiEvent::OtherFrame]);
    }

    #[test]
    fn capture_rejects_non_observation_ack_opcode() {
        let error = parse_frame_line(b"3120AF").unwrap_err();
        assert!(error.contains("Unsupported CAL opcode 0x31"));
    }

    #[test]
    fn mmi_capture_decodes_standard_status_block() {
        let raw = b"g.D8FF000000000001000000000000000000000000000000000028\r\n";
        let (events, pending) = parse_mmi_capture(raw).unwrap();
        assert!(pending.is_empty());
        assert_eq!(events[0], MmiEvent::Confirmation(b'g', '.'));
        let MmiEvent::Block(block) = &events[1] else {
            panic!("expected an MMI block")
        };
        assert_eq!(block.application, 255);
        assert_eq!(block.start, 0);
        assert_eq!(block.states.len(), 88);
        assert_eq!(block.states[16], 1);
    }
}
