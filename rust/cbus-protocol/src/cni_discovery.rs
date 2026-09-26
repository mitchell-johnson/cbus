//! Codecs for Toolkit and C-Gate CNI/Network Interface UDP discovery.
//!
//! This is a separate protocol from the ASCII PCI stream.  The query and
//! reply layout are pinned by the original captures in
//! `testdata/vectors/cni_discovery.jsonl`.

use crate::DecodeError;
use std::net::Ipv4Addr;

/// UDP port used by the captured Toolkit CNI discovery exchange.
pub const DISCOVERY_PORT: u16 = 20_050;

/// UDP port used by the original CNI discovery protocol and `PORT CNISCAN`.
pub const LEGACY_DISCOVERY_PORT: u16 = 30_718;

/// Four-byte query sent by C-Gate for original CNI discovery.
pub const LEGACY_DISCOVERY_QUERY: [u8; 4] = [0x00, 0x00, 0x00, 0xf8];

/// Exact reply length accepted by C-Gate's original CNI scanner.
pub const LEGACY_DISCOVERY_REPLY_LEN: usize = 124;

/// UDP port used by C-Gate's CNI2 discovery protocol and `PORT CNISCAN2`.
pub const CNI2_DISCOVERY_PORT: u16 = 20_050;

/// Parameters read by a C-Gate 3.4 CNI2 discovery query, in wire order.
pub const CNI2_READ_PARAMETERS: [u8; 16] = [0, 1, 2, 3, 4, 5, 7, 9, 11, 12, 13, 14, 15, 16, 29, 30];

/// Exact 19-byte discovery query emitted by the captured client.
pub const DISCOVERY_QUERY: [u8; 19] = [
    0xcb, 0x80, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01, 0x01, 0x01, 0x0b, 0x01, 0x1d, 0x80, 0x01,
    0x02, 0x47, 0xff,
];

/// Exact size of a captured CNI discovery reply.
pub const DISCOVERY_REPLY_LEN: usize = 30;

/// One decoded original CNI discovery reply.
///
/// The sender address is UDP metadata rather than part of this datagram. C-Gate
/// only checks the datagram length and reads the little-endian service port at
/// offsets 24 and 25.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct LegacyDiscoveryReply {
    /// Advertised TCP service port.
    pub service_port: u16,
}

/// Serial number returned by a CNI2 discovery response.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct Cni2SerialNumber {
    /// High 20-bit serial number component.
    pub number: u32,
    /// Low 12-bit serial suffix.
    pub suffix: u16,
}

impl Cni2SerialNumber {
    /// Format the serial as C-Gate prints it in a `PORT CNISCAN2` response.
    pub fn cgate_string(self) -> String {
        format!("{:08}.{:04}", self.number, self.suffix)
    }
}

/// Metadata decoded from one variable-instruction CNI2 response.
///
/// Most fields are optional because a device may return an unsuccessful result
/// for an individual read instruction. The address falls back to the UDP
/// source address when parameter 7 is absent, matching C-Gate.
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct Cni2DiscoveryReply {
    /// Four-byte request/response correlation value.
    pub sequence: u32,
    /// Product/unit type parameter (parameter 1).
    pub product_id: Option<u8>,
    /// Effective IPv4 address: parameter 7, or the UDP source address when
    /// that parameter is absent.
    pub ip_address: Ipv4Addr,
    /// Advertised TCP service port (parameter 11).
    pub service_port: Option<u16>,
    /// Device connection status (parameter 29).
    pub status: Option<u8>,
    /// Device MAC address (parameter 4).
    pub mac_address: Option<[u8; 6]>,
    /// Packed device serial number (parameter 5).
    pub serial_number: Option<Cni2SerialNumber>,
    /// C-Bus unit address (parameter 12).
    pub cbus_unit_address: Option<u8>,
}

impl Cni2DiscoveryReply {
    /// Product label used by native C-Gate's `PORT CNISCAN2` response.
    pub fn product_name(&self) -> String {
        match self.product_id {
            Some(1) => "CNI2".to_owned(),
            Some(2) => "IP_GATEWAY".to_owned(),
            Some(3) => "WISER".to_owned(),
            Some(4) => "MRA_STREAMER".to_owned(),
            Some(5) => "EZI".to_owned(),
            Some(6) => "WISER2".to_owned(),
            Some(7) => "CNIAC".to_owned(),
            Some(other) => format!("UNKNOWN_{other}"),
            None => "UNKNOWN_0".to_owned(),
        }
    }

    /// Lower-case connection status used by native C-Gate output.
    pub fn status_name(&self) -> &'static str {
        match self.status {
            Some(0) => "available",
            Some(1) => "active",
            _ => "",
        }
    }

    /// Upper-case colon-separated MAC address used by native C-Gate output.
    pub fn mac_string(&self) -> Option<String> {
        self.mac_address.map(|mac| {
            mac.iter()
                .map(|byte| format!("{byte:02X}"))
                .collect::<Vec<_>>()
                .join(":")
        })
    }
}

/// One decoded CNI discovery reply.
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct DiscoveryReply {
    /// Opaque four-byte `unknown1` field carried immediately after the reply
    /// magic. It is not a stable device identifier.
    pub unknown1: [u8; 4],
    /// Captured product discriminator (`1` CNI2, `2` hidden, `3` Wiser).
    pub product_id: u8,
    /// Advertised TCP service port, in network byte order on the wire.
    pub service_port: u16,
    /// Opaque one-byte status/access field.  Its meaning is not inferred.
    pub status: u8,
    /// Opaque final two bytes.  Historical notes suggest a checksum, but no
    /// verified checksum algorithm exists, so the bytes are retained only.
    pub trailer: [u8; 2],
}

impl DiscoveryReply {
    /// Stable product label for JSON and diagnostics.
    pub fn product_name(&self) -> &'static str {
        match self.product_id {
            1 => "cni2",
            2 => "hidden",
            3 => "wiser",
            _ => "unknown",
        }
    }

    /// Toolkit's captured discovery UI ignores product id 2.
    pub fn visible_by_default(&self) -> bool {
        self.product_id != 2
    }
}

/// Build the C-Gate 3.4 CNI2 query used by `PORT CNISCAN2`.
///
/// The sequence is encoded in network byte order. The checksum covers the
/// read instructions and the three-byte checksum instruction, but not the
/// eight-byte packet header.
pub fn build_cni2_discovery_query(sequence: u32) -> Vec<u8> {
    let mut query = Vec::with_capacity(45);
    query.extend_from_slice(&[0xcb, 0x80, 0x00, 0x00]);
    query.extend_from_slice(&sequence.to_be_bytes());
    for parameter in CNI2_READ_PARAMETERS {
        query.extend_from_slice(&[0x01, parameter]);
    }
    query.extend_from_slice(&[0x80, 0x01, 0x02]);
    let checksum = crc_ccitt(&query[8..]);
    query.extend_from_slice(&checksum.to_be_bytes());
    query
}

/// Decode one original CNI discovery reply accepted by `PORT CNISCAN`.
pub fn decode_legacy_discovery_reply(data: &[u8]) -> Result<LegacyDiscoveryReply, DecodeError> {
    if data.len() != LEGACY_DISCOVERY_REPLY_LEN {
        return Err(DecodeError::new(format!(
            "legacy CNI discovery reply must be exactly {LEGACY_DISCOVERY_REPLY_LEN} bytes, got {}",
            data.len()
        )));
    }
    Ok(LegacyDiscoveryReply {
        service_port: u16::from_le_bytes([data[24], data[25]]),
    })
}

/// Decode one variable-instruction CNI2 reply accepted by `PORT CNISCAN2`.
///
/// Unknown parameters and unsuccessful per-parameter results are ignored.
/// Every instruction is bounds-checked, including ignored instructions. An
/// optional checksum instruction is validated and must be last; native C-Gate
/// also accepts replies without that trailer.
pub fn decode_cni2_discovery_reply(
    data: &[u8],
    source_ip: Ipv4Addr,
) -> Result<Cni2DiscoveryReply, DecodeError> {
    if data.len() < 8 {
        return Err(DecodeError::new(format!(
            "CNI2 discovery reply header is truncated: got {} bytes",
            data.len()
        )));
    }
    if data[..4] != [0xcb, 0x81, 0x00, 0x00] {
        return Err(DecodeError::new("Invalid CNI2 discovery reply magic"));
    }

    let mut reply = Cni2DiscoveryReply {
        sequence: u32::from_be_bytes(
            data[4..8]
                .try_into()
                .expect("CNI2 header length checked above"),
        ),
        product_id: None,
        ip_address: source_ip,
        service_port: None,
        status: None,
        mac_address: None,
        serial_number: None,
        cbus_unit_address: None,
    };
    let mut offset = 8;
    while offset < data.len() {
        match data[offset] {
            0x81 => {
                let header = data.get(offset..offset + 4).ok_or_else(|| {
                    DecodeError::new(format!(
                        "truncated CNI2 result instruction at offset {offset}"
                    ))
                })?;
                let parameter = header[1];
                let result = header[2];
                let value_len = usize::from(header[3]);
                let value_start = offset + 4;
                let value_end = value_start
                    .checked_add(value_len)
                    .ok_or_else(|| DecodeError::new("CNI2 result instruction length overflow"))?;
                let value = data.get(value_start..value_end).ok_or_else(|| {
                    DecodeError::new(format!(
                        "truncated CNI2 parameter {parameter} value at offset {offset}: expected {value_len} bytes"
                    ))
                })?;
                if result == 0 {
                    decode_cni2_parameter(&mut reply, parameter, value)?;
                }
                offset = value_end;
            }
            0x80 => {
                let trailer = data.get(offset..offset + 6).ok_or_else(|| {
                    DecodeError::new(format!(
                        "truncated CNI2 checksum instruction at offset {offset}"
                    ))
                })?;
                if trailer[..4] != [0x80, 0x01, 0x00, 0x02] {
                    return Err(DecodeError::new(format!(
                        "invalid CNI2 checksum instruction at offset {offset}"
                    )));
                }
                if offset + 6 != data.len() {
                    return Err(DecodeError::new(
                        "CNI2 checksum instruction must be the final instruction",
                    ));
                }
                let expected = crc_ccitt(&data[8..offset + 4]);
                let actual = u16::from_be_bytes([trailer[4], trailer[5]]);
                if actual != expected {
                    return Err(DecodeError::new(format!(
                        "invalid CNI2 checksum: expected {expected:04x}, got {actual:04x}"
                    )));
                }
                offset += 6;
            }
            opcode => {
                return Err(DecodeError::new(format!(
                    "invalid CNI2 instruction opcode 0x{opcode:02x} at offset {offset}"
                )));
            }
        }
    }
    Ok(reply)
}

fn decode_cni2_parameter(
    reply: &mut Cni2DiscoveryReply,
    parameter: u8,
    value: &[u8],
) -> Result<(), DecodeError> {
    match parameter {
        1 => reply.product_id = Some(one_byte_parameter(parameter, value)?),
        4 => {
            reply.mac_address =
                Some(exact_parameter(parameter, value)?.try_into().map_err(|_| {
                    DecodeError::new("CNI2 parameter 4 must contain exactly 6 bytes")
                })?);
        }
        5 => {
            let packed =
                u32::from_be_bytes(exact_parameter(parameter, value)?.try_into().map_err(
                    |_| DecodeError::new("CNI2 parameter 5 must contain exactly 4 bytes"),
                )?);
            reply.serial_number = Some(Cni2SerialNumber {
                number: packed >> 12,
                suffix: (packed & 0x0fff) as u16,
            });
        }
        7 => {
            let octets: [u8; 4] = exact_parameter(parameter, value)?
                .try_into()
                .map_err(|_| DecodeError::new("CNI2 parameter 7 must contain exactly 4 bytes"))?;
            reply.ip_address = Ipv4Addr::from(octets);
        }
        11 => {
            let bytes: [u8; 2] = exact_parameter(parameter, value)?
                .try_into()
                .map_err(|_| DecodeError::new("CNI2 parameter 11 must contain exactly 2 bytes"))?;
            reply.service_port = Some(u16::from_be_bytes(bytes));
        }
        12 => reply.cbus_unit_address = Some(one_byte_parameter(parameter, value)?),
        29 => reply.status = Some(one_byte_parameter(parameter, value)?),
        _ => {}
    }
    Ok(())
}

fn exact_parameter(parameter: u8, value: &[u8]) -> Result<&[u8], DecodeError> {
    let expected = match parameter {
        4 => 6,
        5 | 7 => 4,
        11 => 2,
        _ => value.len(),
    };
    if value.len() != expected {
        return Err(DecodeError::new(format!(
            "CNI2 parameter {parameter} must contain exactly {expected} bytes, got {}",
            value.len()
        )));
    }
    Ok(value)
}

fn one_byte_parameter(parameter: u8, value: &[u8]) -> Result<u8, DecodeError> {
    if value.len() != 1 {
        return Err(DecodeError::new(format!(
            "CNI2 parameter {parameter} must contain exactly 1 byte, got {}",
            value.len()
        )));
    }
    Ok(value[0])
}

fn crc_ccitt(data: &[u8]) -> u16 {
    let mut crc = 0xfa50_u16;
    for byte in data {
        crc ^= u16::from(*byte) << 8;
        for _ in 0..8 {
            crc = if crc & 0x8000 != 0 {
                (crc << 1) ^ 0x1021
            } else {
                crc << 1
            };
        }
    }
    crc
}

/// Decode one exact captured-format CNI discovery reply.
///
/// Fixed field tags and lengths are checked before any values are exposed.
/// Unknown product ids and opaque fields remain representable.
pub fn decode_discovery_reply(data: &[u8]) -> Result<DiscoveryReply, DecodeError> {
    if data.len() != DISCOVERY_REPLY_LEN {
        return Err(DecodeError::new(format!(
            "CNI discovery reply must be exactly {DISCOVERY_REPLY_LEN} bytes, got {}",
            data.len()
        )));
    }
    if data[..4] != [0xcb, 0x81, 0x00, 0x00] {
        return Err(DecodeError::new("Invalid CNI discovery reply magic"));
    }
    for (offset, expected, name) in [
        (8, &[0x81, 0x01, 0x00, 0x01][..], "product"),
        (13, &[0x81, 0x0b, 0x00, 0x02][..], "service-port"),
        (19, &[0x81, 0x1d, 0x00, 0x01][..], "status"),
        (24, &[0x80, 0x01, 0x00, 0x02][..], "trailer"),
    ] {
        if data[offset..offset + expected.len()] != *expected {
            return Err(DecodeError::new(format!(
                "Invalid CNI discovery {name} field tag"
            )));
        }
    }
    Ok(DiscoveryReply {
        unknown1: data[4..8]
            .try_into()
            .expect("fixed discovery unknown1 field"),
        product_id: data[12],
        service_port: u16::from_be_bytes([data[17], data[18]]),
        status: data[23],
        trailer: [data[28], data[29]],
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    const NATIVE_CNI2_RESPONSE: &str = "cb8100000102030481000001008101000101810200030102038103000107810400060017dd010e33810500041895cdc681070004c000020a81090004c0000201810b00022711810c000125810d000105810e00095465737420434e4932810f00010981100008544553544d4f444c811d000100811e0003040506";

    #[test]
    fn query_is_the_exact_captured_datagram() {
        assert_eq!(
            hex::encode(DISCOVERY_QUERY),
            "cb800000000000000101010b011d80010247ff"
        );
    }

    #[test]
    fn cgate_query_has_native_parameters_and_checksum() {
        assert_eq!(
            hex::encode(build_cni2_discovery_query(0x022d_c791)),
            "cb800000022dc79101000101010201030104010501070109010b010c010d010e010f0110011d011e8001022935"
        );
    }

    #[test]
    fn legacy_reply_uses_native_length_and_little_endian_port() {
        let mut raw = [0_u8; LEGACY_DISCOVERY_REPLY_LEN];
        raw[24..26].copy_from_slice(&10_001_u16.to_le_bytes());
        assert_eq!(
            decode_legacy_discovery_reply(&raw).unwrap(),
            LegacyDiscoveryReply {
                service_port: 10_001
            }
        );
        assert!(decode_legacy_discovery_reply(&raw[..123]).is_err());
    }

    #[test]
    fn cgate_variable_response_decodes_native_output_metadata() {
        let reply = decode_cni2_discovery_reply(
            &hex::decode(NATIVE_CNI2_RESPONSE).unwrap(),
            Ipv4Addr::new(198, 51, 100, 1),
        )
        .expect("synthetic response accepted by native C-Gate must decode");
        assert_eq!(reply.sequence, 0x0102_0304);
        assert_eq!(reply.product_id, Some(1));
        assert_eq!(reply.product_name(), "CNI2");
        assert_eq!(reply.ip_address, Ipv4Addr::new(192, 0, 2, 10));
        assert_eq!(reply.service_port, Some(10_001));
        assert_eq!(reply.status, Some(0));
        assert_eq!(reply.status_name(), "available");
        assert_eq!(reply.mac_string().as_deref(), Some("00:17:DD:01:0E:33"));
        assert_eq!(
            reply.serial_number,
            Some(Cni2SerialNumber {
                number: 100_700,
                suffix: 3526,
            })
        );
        assert_eq!(
            reply.serial_number.map(Cni2SerialNumber::cgate_string),
            Some("00100700.3526".to_owned())
        );
        assert_eq!(reply.cbus_unit_address, Some(37));
    }

    #[test]
    fn cni2_decoder_accepts_failed_and_unknown_parameters() {
        let raw = hex::decode("cb810000010203048101010081fe0003010203").unwrap();
        let reply = decode_cni2_discovery_reply(&raw, Ipv4Addr::LOCALHOST).unwrap();
        assert_eq!(reply.product_id, None);
        assert_eq!(reply.product_name(), "UNKNOWN_0");
        assert_eq!(reply.status_name(), "");
        assert_eq!(reply.ip_address, Ipv4Addr::LOCALHOST);
    }

    #[test]
    fn cni2_decoder_accepts_structural_checksum_trailer() {
        let raw =
            hex::decode("cb810000010203048101000101810b00022711811d000100800100022677").unwrap();
        let reply = decode_cni2_discovery_reply(&raw, Ipv4Addr::LOCALHOST).unwrap();
        assert_eq!(reply.product_id, Some(1));
        assert_eq!(reply.service_port, Some(10_001));
        assert_eq!(reply.status, Some(0));
    }

    #[test]
    fn cni2_decoder_rejects_truncated_instructions_without_panicking() {
        let raw = hex::decode(NATIVE_CNI2_RESPONSE).unwrap();
        for len in 0..8 {
            assert!(decode_cni2_discovery_reply(&raw[..len], Ipv4Addr::LOCALHOST).is_err());
        }

        let truncated_value = hex::decode("cb81000001020304810400060017dd").unwrap();
        assert!(
            decode_cni2_discovery_reply(&truncated_value, Ipv4Addr::LOCALHOST)
                .unwrap_err()
                .to_string()
                .contains("truncated CNI2 parameter 4")
        );

        let wrong_known_length = hex::decode("cb81000001020304810b000127").unwrap();
        assert!(
            decode_cni2_discovery_reply(&wrong_known_length, Ipv4Addr::LOCALHOST)
                .unwrap_err()
                .to_string()
                .contains("exactly 2 bytes")
        );

        let trailing_after_checksum = hex::decode("cb8100000102030480010002123400").unwrap();
        assert!(
            decode_cni2_discovery_reply(&trailing_after_checksum, Ipv4Addr::LOCALHOST)
                .unwrap_err()
                .to_string()
                .contains("final instruction")
        );

        let bad_checksum = hex::decode("cb81000001020304800100021234").unwrap();
        assert!(
            decode_cni2_discovery_reply(&bad_checksum, Ipv4Addr::LOCALHOST)
                .unwrap_err()
                .to_string()
                .contains("invalid CNI2 checksum")
        );
    }

    #[test]
    fn unknown_products_and_opaque_fields_are_preserved() {
        let mut raw =
            hex::decode("cb8100000102030481010001fe810b0002ffff811d0001aa800100021234").unwrap();
        let reply = decode_discovery_reply(&raw).unwrap();
        assert_eq!(reply.unknown1, [1, 2, 3, 4]);
        assert_eq!(reply.product_id, 0xfe);
        assert_eq!(reply.product_name(), "unknown");
        assert_eq!(reply.service_port, 65_535);
        assert_eq!(reply.status, 0xaa);
        assert_eq!(reply.trailer, [0x12, 0x34]);
        assert!(reply.visible_by_default());

        raw[8] ^= 1;
        assert!(decode_discovery_reply(&raw).is_err());
    }
}
