//! Short Message application commands and observations.
//!
//! C-Gate 3.4's public SEND encoder is internally inconsistent with its own
//! decoder: it swaps the number/symbol flags, overstates the extended-SAL
//! length by one, and writes user text directly into the PCI ASCII-hex stream.
//! Command encoding here deliberately follows the coherent layout accepted by
//! the native decoder: UTF-8 bytes, an exact body length, number flag 0x40,
//! symbol flag 0x80. Delivery is handled as a confirmed one-shot operation by
//! the service so this repair can never report native's false success.

use crate::{DecodeError, EncodeError};

/// Outbound Short Message command.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ShortMessageCommand {
    /// Ask a device to retransmit one information class.
    Refresh {
        /// Information/service class, 0..=63.
        info_type: u8,
    },
    /// Send one coherent Short Message fragment.
    Send {
        /// Logical total field, 0..=7.
        total: u8,
        /// Fragment index, 0..=7.
        index: u8,
        /// Information/service class, 0..=63.
        info_type: u8,
        /// Optional number portion.
        number: Option<u16>,
        /// Optional symbol index.
        symbol: Option<u8>,
        /// UTF-8 message bytes, at most fourteen bytes.
        text: Vec<u8>,
    },
}

/// Inbound Short Message event using native C-Gate event semantics.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ShortMessageEvent {
    /// Refresh request observed on the bus.
    Refresh {
        /// Information/service class, 0..=63.
        info_type: u8,
    },
    /// Short Message fragment observed on the bus.
    Send {
        /// Native C-Gate exposes the packed mask (0,8,..,56), not 0..=7.
        total: u8,
        /// Fragment index, 0..=7.
        sequence: u8,
        /// Information/service class, 0..=63.
        info_type: u8,
        /// Optional number portion.
        number: Option<u16>,
        /// Optional symbol index.
        symbol: Option<u8>,
        /// Raw message bytes. Native renders these as text.
        text: Vec<u8>,
    },
}

impl ShortMessageCommand {
    /// Exact repaired SAL bytes excluding the PM envelope.
    pub fn encode(&self) -> Result<Vec<u8>, EncodeError> {
        match self {
            Self::Refresh { info_type } => {
                if *info_type > 63 {
                    return Err(EncodeError::new("Short Message info type is out of range"));
                }
                Ok(vec![0x01, *info_type])
            }
            Self::Send {
                total,
                index,
                info_type,
                number,
                symbol,
                text,
            } => {
                if *total > 7 || *index > 7 {
                    return Err(EncodeError::new("Short Message sequence is out of range"));
                }
                if *info_type > 63 {
                    return Err(EncodeError::new("Short Message info type is out of range"));
                }
                if text.len() > 14 {
                    return Err(EncodeError::new(
                        "Short Message text is longer than 14 bytes",
                    ));
                }
                let body_len = 2
                    + usize::from(number.is_some()) * 2
                    + usize::from(symbol.is_some())
                    + text.len();
                if body_len > 31 {
                    return Err(EncodeError::new("Short Message SAL is too long"));
                }
                let mut out = Vec::with_capacity(body_len + 1);
                out.push(0x80 | body_len as u8);
                out.push((*total << 3) | *index);
                out.push(
                    *info_type
                        | if number.is_some() { 0x40 } else { 0 }
                        | if symbol.is_some() { 0x80 } else { 0 },
                );
                if let Some(number) = number {
                    out.extend_from_slice(&number.to_be_bytes());
                }
                if let Some(symbol) = symbol {
                    out.push(*symbol);
                }
                out.extend_from_slice(text);
                Ok(out)
            }
        }
    }
}

impl ShortMessageEvent {
    /// Native C-Gate event arguments.
    pub fn event_arguments(&self) -> String {
        match self {
            Self::Refresh { info_type } => format!("info-type={info_type}"),
            Self::Send {
                total,
                sequence,
                info_type,
                number,
                symbol,
                text,
            } => format!(
                "total={total} sequence={sequence} info-type={info_type} number={} symbol={} text=\"{}\"",
                number.map_or_else(|| "-1".to_string(), |value| value.to_string()),
                symbol.map_or_else(|| "-1".to_string(), |value| value.to_string()),
                String::from_utf8_lossy(text)
            ),
        }
    }

    /// Native lower-case event name.
    pub fn event_name(&self) -> &'static str {
        match self {
            Self::Refresh { .. } => "refresh",
            Self::Send { .. } => "send",
        }
    }
}

/// Decode one or more Short Message events.
pub fn decode_sals(data: &[u8]) -> Result<Vec<ShortMessageEvent>, DecodeError> {
    let mut events = Vec::new();
    let mut offset = 0;
    while offset < data.len() {
        let header = data[offset];
        if header == 0x01 {
            let Some(info_type) = data.get(offset + 1).copied() else {
                return Err(DecodeError::new("truncated Short Message refresh"));
            };
            if info_type > 63 {
                return Err(DecodeError::new("Short Message info type is out of range"));
            }
            events.push(ShortMessageEvent::Refresh { info_type });
            offset += 2;
            continue;
        }
        if header & 0xe0 != 0x80 {
            return Err(DecodeError::new(format!(
                "unsupported Short Message header 0x{header:02x}"
            )));
        }
        let body_len = usize::from(header & 0x1f);
        if body_len < 2 || data.len().saturating_sub(offset + 1) < body_len {
            return Err(DecodeError::new("truncated Short Message send"));
        }
        let body = &data[offset + 1..offset + 1 + body_len];
        let sequence_id = body[0];
        let service = body[1];
        let mut cursor = 2;
        let number = if service & 0x40 != 0 {
            if body.len().saturating_sub(cursor) < 2 {
                return Err(DecodeError::new("truncated Short Message number"));
            }
            let value = u16::from_be_bytes([body[cursor], body[cursor + 1]]);
            cursor += 2;
            Some(value)
        } else {
            None
        };
        let symbol = if service & 0x80 != 0 {
            let Some(value) = body.get(cursor).copied() else {
                return Err(DecodeError::new("truncated Short Message symbol"));
            };
            cursor += 1;
            Some(value)
        } else {
            None
        };
        let text = body[cursor..].to_vec();
        if text.len() > 14 {
            return Err(DecodeError::new(
                "Short Message text is longer than 14 bytes",
            ));
        }
        events.push(ShortMessageEvent::Send {
            total: sequence_id & 0x38,
            sequence: sequence_id & 7,
            info_type: service & 0x3f,
            number,
            symbol,
            text,
        });
        offset += body_len + 1;
    }
    Ok(events)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn repaired_send_uses_coherent_native_decoder_layout() {
        let command = ShortMessageCommand::Send {
            total: 5,
            index: 3,
            info_type: 17,
            number: Some(4660),
            symbol: Some(86),
            text: b"AB".to_vec(),
        };
        let encoded = vec![0x87, 0x2b, 0xd1, 0x12, 0x34, 0x56, 0x41, 0x42];
        assert_eq!(command.encode().unwrap(), encoded);
        assert_eq!(
            decode_sals(&encoded).unwrap(),
            vec![ShortMessageEvent::Send {
                total: 40,
                sequence: 3,
                info_type: 17,
                number: Some(4660),
                symbol: Some(86),
                text: b"AB".to_vec(),
            }]
        );
    }

    #[test]
    fn native_flag_vectors_decode() {
        for (encoded, number, symbol) in [
            (&[0x84, 0x2b, 0x11, 0x41, 0x42][..], None, None),
            (
                &[0x86, 0x2b, 0x51, 0x12, 0x34, 0x41, 0x42],
                Some(4660),
                None,
            ),
            (&[0x85, 0x2b, 0x91, 0x56, 0x41, 0x42], None, Some(86)),
        ] {
            let decoded = decode_sals(encoded).unwrap();
            let [ShortMessageEvent::Send {
                total,
                sequence,
                info_type,
                number: decoded_number,
                symbol: decoded_symbol,
                text,
            }] = decoded.as_slice()
            else {
                panic!("unexpected decode")
            };
            assert_eq!((*total, *sequence, *info_type), (40, 3, 17));
            assert_eq!(*decoded_number, number);
            assert_eq!(*decoded_symbol, symbol);
            assert_eq!(text, b"AB");
        }
    }

    #[test]
    fn refresh_and_empty_send_decode() {
        assert_eq!(
            decode_sals(&[0x01, 0x3f]).unwrap(),
            vec![ShortMessageEvent::Refresh { info_type: 63 }]
        );
        assert_eq!(
            decode_sals(&[0x82, 0, 0]).unwrap(),
            vec![ShortMessageEvent::Send {
                total: 0,
                sequence: 0,
                info_type: 0,
                number: None,
                symbol: None,
                text: vec![],
            }]
        );
    }

    #[test]
    fn malformed_messages_fail_closed() {
        assert!(decode_sals(&[0x01]).is_err());
        assert!(decode_sals(&[0x86, 0, 0]).is_err());
        assert!(decode_sals(&[0x83, 0, 0x40, 1]).is_err());
        assert!(ShortMessageCommand::Send {
            total: 0,
            index: 0,
            info_type: 0,
            number: None,
            symbol: None,
            text: vec![0; 15],
        }
        .encode()
        .is_err());
    }
}
