//! Codec for the captured CNI/Network Interface UDP discovery exchange.
//!
//! This is a separate protocol from the ASCII PCI stream.  The query and
//! reply layout are pinned by the original captures in
//! `testdata/vectors/cni_discovery.jsonl`.

use crate::DecodeError;

/// UDP port used by the captured Toolkit CNI discovery exchange.
pub const DISCOVERY_PORT: u16 = 20_050;

/// Exact 19-byte discovery query emitted by the captured client.
pub const DISCOVERY_QUERY: [u8; 19] = [
    0xcb, 0x80, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01, 0x01, 0x01, 0x0b, 0x01, 0x1d, 0x80, 0x01,
    0x02, 0x47, 0xff,
];

/// Exact size of a captured CNI discovery reply.
pub const DISCOVERY_REPLY_LEN: usize = 30;

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

    #[test]
    fn query_is_the_exact_captured_datagram() {
        assert_eq!(
            hex::encode(DISCOVERY_QUERY),
            "cb800000000000000101010b011d80010247ff"
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
