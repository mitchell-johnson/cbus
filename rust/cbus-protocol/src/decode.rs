//! C-Bus frame decoder. Compatibility-sensitive branches are pinned by
//! golden vectors.

use crate::cal::Cal;
use crate::common::{
    bridge_length, cbus_checksum, CONFIRMATION_CODES, DAT_POINT_TO_MULTIPOINT, DAT_POINT_TO_POINT,
    DAT_POINT_TO_POINT_TO_MULTIPOINT, HEX_CHARS, MIN_MESSAGE_SIZE,
};
use crate::packet::{Meta, Packet};
use crate::sal;
use crate::DecodeError;

fn find(haystack: &[u8], needle: &[u8]) -> Option<usize> {
    if needle.len() == 1 {
        return haystack.iter().position(|&b| b == needle[0]);
    }
    haystack.windows(needle.len()).position(|w| w == needle)
}

/// Decode a single C-Bus Serial Interface packet from the head of `data`.
/// Returns `(packet-or-none, consumed)`. `consumed == 0` means "wait for
/// more data".
pub fn decode_packet(
    data: &[u8],
    checksum: bool,
    strict: bool,
    from_pci: bool,
) -> (Option<Packet>, usize) {
    decode_packet_mode(data, checksum, strict, from_pci, false)
}

/// Decode while an installation MMI response is expected.
///
/// Standard-status MMI blocks are byte-ambiguous with some valid addressed
/// frames, so callers must opt into this mode only for the lifetime of a
/// confirmed installation MMI transaction.
pub fn decode_packet_install_mmi(
    data: &[u8],
    checksum: bool,
    strict: bool,
    from_pci: bool,
) -> (Option<Packet>, usize) {
    decode_packet_mode(data, checksum, strict, from_pci, true)
}

fn decode_packet_mode(
    data: &[u8],
    checksum: bool,
    strict: bool,
    from_pci: bool,
    install_mmi: bool,
) -> (Option<Packet>, usize) {
    let mut checksum = checksum;
    let mut confirmation: Option<u8> = None;
    let mut device_management_cal = false;

    if data.is_empty() {
        return (None, 0);
    }

    // transport-layer specials
    let end: Option<usize> = if from_pci {
        if data[0] == b'+' {
            return (Some(Packet::PowerOn), 1);
        }
        if data[0] == b'!' {
            return (Some(Packet::PciError), 1);
        }
        if data.len() < MIN_MESSAGE_SIZE {
            return (None, 0);
        }
        if CONFIRMATION_CODES.contains(&data[0]) {
            let success = data[1] == 0x2e; // b'.'
            return (
                Some(Packet::Confirmation {
                    code: data[0],
                    success,
                }),
                2,
            );
        }
        find(data, b"\r\n")
    } else {
        if data[0] == b'~' {
            return (Some(Packet::Reset), 1);
        }
        if data.starts_with(b"null") {
            // Toolkit is buggy, just ignore it.
            return (None, 4);
        }
        if data.starts_with(b"|\r") || data.starts_with(b"||\r") {
            // SMART + CONNECT shortcut
            let f = find(data, b"\r").unwrap();
            return (Some(Packet::SmartConnect), f + 1);
        }
        // Cancel request (s4.2.4): discard data before-and-including '?'
        let nlp = find(data, b"\r");
        let qp = find(data, b"?");
        if let (Some(q), Some(n)) = (qp, nlp) {
            if q < n {
                return (None, q + 1);
            }
        }
        find(data, b"\r")
    };

    let end = match end {
        Some(e) => e,
        None => return (None, 0),
    };
    let mut body = &data[..end];
    let consumed = end + if from_pci { 2 } else { 1 };

    if body.is_empty() {
        return (None, consumed);
    }

    if !from_pci {
        if body[0] == b'@' {
            // Once-off BASIC mode command (s4.2.7)
            checksum = false;
            device_management_cal = true;
            body = &body[1..];
        } else if body[0] == b'\\' {
            body = &body[1..];
        } else {
            device_management_cal = true;
        }

        // confirmation char detection: last byte not uppercase hex
        let last = match body.last() {
            Some(&l) => l,
            // Truncated bridge metadata is invalid.
            None => return (Some(Packet::Invalid), consumed),
        };
        if !HEX_CHARS.contains(&last) {
            confirmation = Some(last);
            if !CONFIRMATION_CODES.contains(&last) && strict {
                return (Some(Packet::Invalid), consumed);
            }
            // lenient: warn + accept
            body = &body[..body.len() - 1];
        }
    }

    // UPPERCASE base16 only
    for &c in body {
        if !HEX_CHARS.contains(&c) {
            return (Some(Packet::Invalid), consumed);
        }
    }
    // Hex decoding requires an even number of digits.
    if !body.len().is_multiple_of(2) {
        return (Some(Packet::Invalid), consumed);
    }
    let mut raw = match hex::decode(body) {
        Ok(r) => r,
        Err(_) => return (Some(Packet::Invalid), consumed),
    };

    if checksum {
        if !crate::common::validate_cbus_checksum(&raw) {
            let _real = if raw.len() > 1 {
                cbus_checksum(&raw[..raw.len() - 1])
            } else {
                0
            };
            if strict {
                return (Some(Packet::Invalid), consumed);
            }
            // lenient: warn, still strip and decode
        }
        raw.pop();
    }

    if raw.is_empty() {
        // A packet without flags is invalid.
        return (Some(Packet::Invalid), consumed);
    }

    match decode_body(
        &raw,
        checksum,
        from_pci,
        device_management_cal,
        confirmation,
        consumed,
        install_mmi,
    ) {
        Ok((p, c)) => (Some(p), c),
        Err(_) => (Some(Packet::Invalid), consumed),
    }
}

/// The `try:` block of `decode_packet` — any error becomes InvalidPacket.
fn decode_body(
    raw: &[u8],
    checksum: bool,
    from_pci: bool,
    device_management_cal: bool,
    confirmation: Option<u8>,
    consumed: usize,
    install_mmi: bool,
) -> Result<(Packet, usize), DecodeError> {
    let flags = raw[0];
    let address_type = flags & 0x07;
    let dp = flags & 0x20 == 0x20;
    let priority_class = (flags >> 6) & 0x03;

    // Standard-status MMI blocks are direct from-PCI messages. Their first
    // byte is a C/D marker with a low-five-bit byte count, not an addressed
    // packet header. The wire form is ambiguous with priority-3 addressed
    // traffic, so only recognize installation blocks inside an active MMI
    // transaction and only for the installation application.
    if install_mmi && from_pci && flags & 0xe0 == 0xc0 && raw.get(1) == Some(&0xff) {
        let count = usize::from(flags & 0x1f);
        if count >= 3 && raw.len() == count + 1 {
            let application = raw[1];
            let block_start = raw[2];
            let mut states = Vec::with_capacity((raw.len() - 3) * 4);
            for value in &raw[3..] {
                states.extend((0..4).map(|shift| (value >> (shift * 2)) & 0x03));
            }
            if usize::from(block_start) + states.len() > 256 {
                return Err(DecodeError::new(
                    "standard-status block extends beyond address 255",
                ));
            }
            return Ok((
                Packet::StandardStatus {
                    application,
                    block_start,
                    states,
                },
                consumed,
            ));
        }
    }

    // Direct CAL replies: from-PCI frames whose "flags" byte is really a
    // CAL header (address type not 3/5/6, dp clear). The *entire* payload
    // including the flags byte parses as a CAL stream.
    if from_pci
        && !matches!(
            address_type,
            DAT_POINT_TO_POINT_TO_MULTIPOINT | DAT_POINT_TO_MULTIPOINT | DAT_POINT_TO_POINT
        )
        && !dp
    {
        let mut cals = Vec::new();
        let mut cal_data = raw;
        while !cal_data.is_empty() {
            let (cal, cal_len) = Cal::decode_one(cal_data)?;
            cal_data = cal_data.get(cal_len..).unwrap_or(&[]);
            cals.push(cal);
        }
        return Ok((
            Packet::PointToPoint {
                meta: Meta {
                    checksum,
                    priority_class,
                    source_address: None,
                    confirmation: None,
                },
                unit_address: 0,
                bridged: false,
                hops: vec![],
                cals,
            },
            consumed,
        ));
    }

    let mut rest = &raw[1..];

    // from-PCI frames carry a source address byte right after flags
    let source_addr: Option<u8> = if from_pci {
        let s = *rest
            .first()
            .ok_or_else(|| DecodeError::new("missing source address"))?;
        rest = &rest[1..];
        Some(s)
    } else {
        None
    };

    let mut p = if dp {
        // DeviceManagementPacket.decode_packet: [param, 0x00, value], len 3
        let parameter = *rest
            .first()
            .ok_or_else(|| DecodeError::new("short DM packet"))?;
        if *rest
            .get(1)
            .ok_or_else(|| DecodeError::new("short DM packet"))?
            != 0
        {
            return Err(DecodeError::new(
                "second byte of DeviceManagementPacket must be 0",
            ));
        }
        let value = *rest
            .get(2)
            .ok_or_else(|| DecodeError::new("short DM packet"))?;
        if rest.len() != 3 {
            return Err(DecodeError::new(
                "Unexpected DeviceManagementPacket payload length",
            ));
        }
        Packet::DeviceManagement {
            meta: Meta::new(checksum, priority_class),
            parameter,
            value,
        }
    } else if device_management_cal {
        // Bare CAL return uses compatibility-sensitive consumed accounting:
        // frame-consumed plus the CAL length.
        let (cal, cal_len) = Cal::decode_one(rest)?;
        return Ok((Packet::BareCal(cal), consumed + cal_len));
    } else if address_type == DAT_POINT_TO_POINT {
        // Captured OEM programming responses carry a local 01 00 route,
        // unlike the outgoing 09 00 selector and ordinary bridge lengths.
        if from_pci && rest.get(1..3) == Some(&[0x01, 0x00]) {
            let mut direct = vec![rest[0], 0];
            direct.extend_from_slice(&rest[3..]);
            decode_pp(&direct, checksum, priority_class)?
        } else {
            decode_pp(rest, checksum, priority_class)?
        }
    } else if address_type == DAT_POINT_TO_MULTIPOINT {
        decode_pm(rest, checksum, priority_class)?
    } else {
        // PPM and everything else: NotImplementedError
        return Err(DecodeError::new(format!(
            "Destination address type = 0x{:x}",
            address_type
        )));
    };

    if !from_pci {
        if let Some(meta) = p.meta_mut() {
            meta.confirmation = confirmation;
            meta.source_address = None;
        }
    } else if let Some(s) = source_addr {
        // only assigned when truthy (source 0 leaves it None)
        if s != 0 {
            if let Some(meta) = p.meta_mut() {
                meta.source_address = Some(s);
                meta.confirmation = None;
            }
        }
    }
    Ok((p, consumed))
}

/// PointToMultipointPacket.decode_packet
fn decode_pm(data: &[u8], checksum: bool, priority_class: u8) -> Result<Packet, DecodeError> {
    let application = *data
        .first()
        .ok_or_else(|| DecodeError::new("short PM packet"))?;
    // Application(data[0]) raises for values outside the IntEnum; the
    // registry lookup then raises for unregistered apps. Both -> Invalid,
    // and sal::decode_sals errors for anything unregistered, so a single
    // check suffices.
    if *data
        .get(1)
        .ok_or_else(|| DecodeError::new("short PM packet"))?
        != 0
    {
        return Err(DecodeError::new("Routing data in PM message?"));
    }
    let sals = sal::decode_sals(application, &data[2..])?;
    Ok(Packet::PointToMultipoint {
        meta: Meta::new(checksum, priority_class),
        application,
        sals,
    })
}

/// PointToPointPacket.decode_packet
fn decode_pp(data: &[u8], checksum: bool, priority_class: u8) -> Result<Packet, DecodeError> {
    let b1 = *data
        .get(1)
        .ok_or_else(|| DecodeError::new("short PP packet"))?;
    let unit_address;
    let bridged;
    let mut hops = Vec::new();
    let mut rest;
    if b1 == 0 {
        unit_address = data[0];
        rest = &data[2..];
        bridged = false;
    } else {
        let bridge_address = data[0];
        let bl = bridge_length(b1)
            .ok_or_else(|| DecodeError::new(format!("bad bridge length code {:#x}", b1)))?;
        rest = &data[2..];
        for _ in 0..bl {
            let h = *rest
                .first()
                .ok_or_else(|| DecodeError::new("short bridged PP packet"))?;
            hops.push(h);
            rest = &rest[1..];
        }
        unit_address = *rest
            .first()
            .ok_or_else(|| DecodeError::new("short bridged PP packet"))?;
        rest = &rest[1..];
        bridged = true;
        // PointToPointPacket.__init__: hops given but bridge_address <= 0
        if bridge_address == 0 {
            return Err(DecodeError::new(
                "hops were specified, but there is no bridge_address!",
            ));
        }
    }

    let mut cals = Vec::new();
    let mut d = rest;
    while !d.is_empty() {
        let (cal, cal_len) = Cal::decode_one(d)?;
        d = d.get(cal_len..).unwrap_or(&[]);
        cals.push(cal);
    }
    Ok(Packet::PointToPoint {
        meta: Meta::new(checksum, priority_class),
        unit_address,
        bridged,
        hops,
        cals,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn specials() {
        assert_eq!(decode_packet(b"", true, true, true), (None, 0));
        assert_eq!(
            decode_packet(b"+", true, true, true),
            (Some(Packet::PowerOn), 1)
        );
        assert_eq!(
            decode_packet(b"++", true, true, true),
            (Some(Packet::PowerOn), 1)
        );
        assert_eq!(
            decode_packet(b"!", true, true, true),
            (Some(Packet::PciError), 1)
        );
        assert_eq!(
            decode_packet(b"h.", true, true, true),
            (
                Some(Packet::Confirmation {
                    code: b'h',
                    success: true
                }),
                2
            )
        );
        assert_eq!(
            decode_packet(b"g#", true, true, true),
            (
                Some(Packet::Confirmation {
                    code: b'g',
                    success: false
                }),
                2
            )
        );
        assert_eq!(
            decode_packet(b"~", false, true, false),
            (Some(Packet::Reset), 1)
        );
        assert_eq!(decode_packet(b"null", false, true, false), (None, 4));
        assert_eq!(
            decode_packet(b"|\r", false, true, false),
            (Some(Packet::SmartConnect), 2)
        );
        assert_eq!(
            decode_packet(b"||\r", false, true, false),
            (Some(Packet::SmartConnect), 3)
        );
    }

    #[test]
    fn pm_light_on_from_pci() {
        // 050138007901 + ck 48 = PM source 1, lighting app 38, on GA 1
        let (p, c) = decode_packet(b"05013800790148\r\n", true, true, true);
        assert_eq!(c, 16);
        match p.unwrap() {
            Packet::PointToMultipoint {
                meta,
                application,
                sals,
            } => {
                assert_eq!(application, 0x38);
                assert_eq!(meta.source_address, Some(1));
                assert_eq!(
                    sals,
                    vec![crate::sal::Sal::LightingOn {
                        application: 0x38,
                        group_address: 1
                    }]
                );
            }
            other => panic!("wrong packet {:?}", other),
        }
    }

    #[test]
    fn direct_cal_reply() {
        // 82 21 10 + ck 4D: reply CAL where the flags byte IS the header
        let wire = b"8221104D\r\n";
        let (p, c) = decode_packet(wire, true, true, true);
        assert_eq!(c, 10);
        match p.unwrap() {
            Packet::PointToPoint {
                meta,
                unit_address,
                cals,
                ..
            } => {
                assert_eq!(unit_address, 0);
                assert_eq!(meta.source_address, None);
                assert_eq!(meta.priority_class, 2);
                assert_eq!(
                    cals,
                    vec![crate::cal::Cal::Reply {
                        parameter: 0x21,
                        data: vec![0x10]
                    }]
                );
            }
            other => panic!("wrong packet {:?}", other),
        }
    }

    #[test]
    fn installation_mmi_requires_explicit_decode_context() {
        let wire = b"D8FF000000000001000000000000000000000000000000000028\r\n";
        let (packet, consumed) = decode_packet_install_mmi(wire, true, true, true);
        assert_eq!(consumed, wire.len());
        match packet.unwrap() {
            Packet::StandardStatus {
                application,
                block_start,
                states,
            } => {
                assert_eq!(application, 0xff);
                assert_eq!(block_start, 0);
                assert_eq!(states.len(), 88);
                assert_eq!(states[16], 1);
                assert_eq!(states.iter().filter(|state| **state != 0).count(), 1);
            }
            other => panic!("wrong packet {other:?}"),
        }
        assert!(!matches!(
            decode_packet(wire, true, true, true).0,
            Some(Packet::StandardStatus { .. })
        ));
    }
}
