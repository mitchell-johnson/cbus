//! Access Control application (0xD5) SAL messages.
//!
//! C-Gate 3.4's `CBusAccessControlApplication` decodes each SAL with the
//! standard command-byte rules: a short opcode (bit 7 clear) carries the
//! command in bits 3..6 and its parameter length in bits 0..2, while a long
//! opcode (bit 7 set) carries the command in bits 5..6 and its parameter
//! length in bits 0..4. Short commands 0, 1, 2, 3, 4 and 6 are close, lock,
//! left open, forced open, closed and exit request; each takes a zone and an
//! access point. Long commands 1 and 2 are valid and invalid access requests;
//! they take a zone, a point, a direction and the variable-length access data
//! that native events print as the `requester` hexadecimal string.
//!
//! The native decoder accepts zones and points 0..=254 and directions 0..=2
//! and reports any other value as a bad SAL parameter without emitting an
//! event. This decoder applies the same ranges but fails closed, together with
//! unknown commands, non-canonical short lengths and truncated payloads, so a
//! malformed SAL yields no typed message. Native C-Gate instead ignores extra
//! short-form parameter bytes and still emits the valid messages that precede
//! or follow a rejected one in the same SAL; the owned capture in
//! `testdata/fixtures/native_cgate_access_control.json` records those
//! differences. Outbound close and lock retain the full byte range that
//! cmqttd's command grammar accepts.

use crate::{DecodeError, EncodeError};

/// Short command 0: close an access point.
const CLOSE: u8 = 0x02;
/// Short command 1: lock an access point.
const LOCK: u8 = 0x0a;
/// Short command 2: access point left open.
const LEFT_OPEN: u8 = 0x12;
/// Short command 3: access point forced open.
const FORCED_OPEN: u8 = 0x1a;
/// Short command 4: access point closed.
const CLOSED: u8 = 0x22;
/// Short command 6: request to exit.
const EXIT_REQUEST: u8 = 0x32;
/// Long command 1: valid access request (low five bits are the length).
const REQUEST_VALID: u8 = 0xa0;
/// Long command 2: invalid access request (low five bits are the length).
const REQUEST_INVALID: u8 = 0xc0;
/// Highest zone and access-point number the native decoder accepts.
pub const MAX_INBOUND_ADDRESS: u8 = 254;
/// Highest access-request direction the native decoder accepts.
pub const MAX_DIRECTION: u8 = 2;
/// Largest access-request data length after zone, point and direction.
pub const MAX_ACCESS_DATA: usize = 0x1f - 3;

/// A command or observation for one Access Control point.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum AccessControlMessage {
    /// Ask the point to close.
    Close {
        /// Zone address.
        zone: u8,
        /// Access-point address within the zone.
        point: u8,
    },
    /// Ask the point to lock.
    Lock {
        /// Zone address.
        zone: u8,
        /// Access-point address within the zone.
        point: u8,
    },
    /// The point was left open.
    PointLeftOpen {
        /// Zone address.
        zone: u8,
        /// Access-point address within the zone.
        point: u8,
    },
    /// The point was forced open.
    PointForcedOpen {
        /// Zone address.
        zone: u8,
        /// Access-point address within the zone.
        point: u8,
    },
    /// The point closed.
    PointClosed {
        /// Zone address.
        zone: u8,
        /// Access-point address within the zone.
        point: u8,
    },
    /// A user requested exit at the point.
    ExitRequest {
        /// Zone address.
        zone: u8,
        /// Access-point address within the zone.
        point: u8,
    },
    /// A reader accepted the presented access data.
    AccessRequestValid {
        /// Zone address.
        zone: u8,
        /// Access-point address within the zone.
        point: u8,
        /// Native direction byte, 0..=2.
        direction: u8,
        /// Raw access data (for example a card or code), 0..=28 bytes.
        data: Vec<u8>,
    },
    /// A reader rejected the presented access data.
    AccessRequestInvalid {
        /// Zone address.
        zone: u8,
        /// Access-point address within the zone.
        point: u8,
        /// Native direction byte, 0..=2.
        direction: u8,
        /// Raw access data (for example a card or code), 0..=28 bytes.
        data: Vec<u8>,
    },
}

impl AccessControlMessage {
    /// Encode the native SAL payload.
    pub fn encode(&self) -> Result<Vec<u8>, EncodeError> {
        let (opcode, zone, point) = match *self {
            Self::Close { zone, point } => (CLOSE, zone, point),
            Self::Lock { zone, point } => (LOCK, zone, point),
            Self::PointLeftOpen { zone, point } => (LEFT_OPEN, zone, point),
            Self::PointForcedOpen { zone, point } => (FORCED_OPEN, zone, point),
            Self::PointClosed { zone, point } => (CLOSED, zone, point),
            Self::ExitRequest { zone, point } => (EXIT_REQUEST, zone, point),
            Self::AccessRequestValid {
                zone,
                point,
                direction,
                ref data,
            } => return encode_request(REQUEST_VALID, zone, point, direction, data),
            Self::AccessRequestInvalid {
                zone,
                point,
                direction,
                ref data,
            } => return encode_request(REQUEST_INVALID, zone, point, direction, data),
        };
        Ok(vec![opcode, zone, point])
    }

    /// Native C-Gate event name.
    pub fn event_name(&self) -> &'static str {
        match self {
            Self::Close { .. } => "close_access_point",
            Self::Lock { .. } => "lock_access_point",
            Self::PointLeftOpen { .. } => "access_point_left_open",
            Self::PointForcedOpen { .. } => "access_point_forced_open",
            Self::PointClosed { .. } => "access_point_closed",
            Self::ExitRequest { .. } => "exit_request",
            Self::AccessRequestValid { .. } => "access_request_valid",
            Self::AccessRequestInvalid { .. } => "access_request_invalid",
        }
    }

    /// Native space-separated event values: zone and point, plus direction
    /// and upper-case access-data hex for access requests. Native appends
    /// the requester with a separator even when it is empty, so an empty
    /// request retains one trailing space.
    pub fn event_arguments(&self) -> String {
        match self {
            Self::Close { zone, point }
            | Self::Lock { zone, point }
            | Self::PointLeftOpen { zone, point }
            | Self::PointForcedOpen { zone, point }
            | Self::PointClosed { zone, point }
            | Self::ExitRequest { zone, point } => format!("{zone} {point}"),
            Self::AccessRequestValid {
                zone,
                point,
                direction,
                data,
            }
            | Self::AccessRequestInvalid {
                zone,
                point,
                direction,
                data,
            } => {
                let requester: String = data.iter().map(|byte| format!("{byte:02X}")).collect();
                format!("{zone} {point} {direction} {requester}")
            }
        }
    }

    /// Native `702` event detail: `zone=Z point=P[ direction=D requester=HEX]`.
    pub fn event_detail(&self) -> String {
        super::keyed_event_text(
            &["zone", "point", "direction", "requester"],
            &self.event_arguments(),
        )
    }

    /// True for observations native marks with `# ` in the status row;
    /// only close and lock are commands.
    pub fn is_report(&self) -> bool {
        !matches!(self, Self::Close { .. } | Self::Lock { .. })
    }
}

fn encode_request(
    base: u8,
    zone: u8,
    point: u8,
    direction: u8,
    data: &[u8],
) -> Result<Vec<u8>, EncodeError> {
    if direction > MAX_DIRECTION {
        return Err(EncodeError::new(
            "Access Control direction must be 0 through 2",
        ));
    }
    if data.len() > MAX_ACCESS_DATA {
        return Err(EncodeError::new(format!(
            "Access Control access data is limited to {MAX_ACCESS_DATA} bytes"
        )));
    }
    let mut out = Vec::with_capacity(4 + data.len());
    out.push(base | (3 + data.len()) as u8);
    out.extend([zone, point, direction]);
    out.extend_from_slice(data);
    Ok(out)
}

/// Decode one or more concatenated Access Control messages.
pub fn decode_sals(mut data: &[u8]) -> Result<Vec<AccessControlMessage>, DecodeError> {
    if data.is_empty() {
        return Err(DecodeError::new("empty Access Control SAL"));
    }
    let mut messages = Vec::new();
    while let Some(&opcode) = data.first() {
        let length = if opcode & 0x80 != 0 {
            usize::from(opcode & 0x1f)
        } else {
            usize::from(opcode & 0x07)
        };
        let Some(parameters) = data.get(1..=length) else {
            return Err(DecodeError::new("truncated Access Control SAL"));
        };
        messages.push(decode_one(opcode, parameters)?);
        data = &data[1 + length..];
    }
    Ok(messages)
}

fn decode_one(opcode: u8, parameters: &[u8]) -> Result<AccessControlMessage, DecodeError> {
    let address = |index: usize, name: &str| {
        parameters
            .get(index)
            .copied()
            .filter(|value| *value <= MAX_INBOUND_ADDRESS)
            .ok_or_else(|| DecodeError::new(format!("Access Control {name} is out of range")))
    };
    if opcode & 0x80 != 0 {
        let base = opcode & 0xe0;
        if !matches!(base, REQUEST_VALID | REQUEST_INVALID) {
            return Err(DecodeError::new(format!(
                "unknown Access Control opcode 0x{opcode:02x}"
            )));
        }
        let zone = address(0, "zone")?;
        let point = address(1, "access point")?;
        let direction = parameters
            .get(2)
            .copied()
            .filter(|value| *value <= MAX_DIRECTION)
            .ok_or_else(|| DecodeError::new("Access Control direction is out of range"))?;
        let data = parameters[3..].to_vec();
        return Ok(if base == REQUEST_VALID {
            AccessControlMessage::AccessRequestValid {
                zone,
                point,
                direction,
                data,
            }
        } else {
            AccessControlMessage::AccessRequestInvalid {
                zone,
                point,
                direction,
                data,
            }
        });
    }
    if parameters.len() != 2 {
        return Err(DecodeError::new(format!(
            "unknown Access Control opcode 0x{opcode:02x}"
        )));
    }
    let zone = address(0, "zone")?;
    let point = address(1, "access point")?;
    Ok(match opcode {
        CLOSE => AccessControlMessage::Close { zone, point },
        LOCK => AccessControlMessage::Lock { zone, point },
        LEFT_OPEN => AccessControlMessage::PointLeftOpen { zone, point },
        FORCED_OPEN => AccessControlMessage::PointForcedOpen { zone, point },
        CLOSED => AccessControlMessage::PointClosed { zone, point },
        EXIT_REQUEST => AccessControlMessage::ExitRequest { zone, point },
        _ => {
            return Err(DecodeError::new(format!(
                "unknown Access Control opcode 0x{opcode:02x}"
            )))
        }
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn exact_cgate_close_and_lock_payloads_round_trip() {
        for (message, bytes) in [
            (
                AccessControlMessage::Close { zone: 7, point: 9 },
                vec![0x02, 7, 9],
            ),
            (
                AccessControlMessage::Lock {
                    zone: 254,
                    point: 0,
                },
                vec![0x0a, 254, 0],
            ),
        ] {
            assert_eq!(message.encode().unwrap(), bytes);
            assert_eq!(decode_sals(&bytes).unwrap(), vec![message]);
        }
    }

    #[test]
    fn outbound_close_and_lock_keep_the_full_byte_range() {
        assert_eq!(
            AccessControlMessage::Lock {
                zone: 255,
                point: 255
            }
            .encode()
            .unwrap(),
            vec![0x0a, 255, 255]
        );
    }

    #[test]
    fn every_native_message_round_trips_with_its_event_text() {
        let cases = [
            (
                AccessControlMessage::PointLeftOpen { zone: 1, point: 2 },
                vec![0x12, 1, 2],
                "access_point_left_open",
                "1 2",
            ),
            (
                AccessControlMessage::PointForcedOpen { zone: 3, point: 4 },
                vec![0x1a, 3, 4],
                "access_point_forced_open",
                "3 4",
            ),
            (
                AccessControlMessage::PointClosed { zone: 5, point: 6 },
                vec![0x22, 5, 6],
                "access_point_closed",
                "5 6",
            ),
            (
                AccessControlMessage::ExitRequest {
                    zone: 0,
                    point: 254,
                },
                vec![0x32, 0, 254],
                "exit_request",
                "0 254",
            ),
            (
                AccessControlMessage::AccessRequestValid {
                    zone: 7,
                    point: 9,
                    direction: 1,
                    data: vec![0x12, 0xab, 0x00],
                },
                vec![0xa6, 7, 9, 1, 0x12, 0xab, 0x00],
                "access_request_valid",
                "7 9 1 12AB00",
            ),
            (
                AccessControlMessage::AccessRequestInvalid {
                    zone: 7,
                    point: 9,
                    direction: 2,
                    data: vec![],
                },
                vec![0xc3, 7, 9, 2],
                "access_request_invalid",
                "7 9 2 ",
            ),
        ];
        for (message, bytes, name, arguments) in cases {
            assert_eq!(message.encode().unwrap(), bytes);
            assert_eq!(decode_sals(&bytes).unwrap(), vec![message.clone()]);
            assert_eq!(message.event_name(), name);
            assert_eq!(message.event_arguments(), arguments);
        }
    }

    #[test]
    fn maximum_access_data_and_concatenated_messages_decode() {
        let data: Vec<u8> = (0..MAX_ACCESS_DATA as u8).collect();
        let request = AccessControlMessage::AccessRequestValid {
            zone: 1,
            point: 1,
            direction: 0,
            data: data.clone(),
        };
        let mut bytes = request.encode().unwrap();
        assert_eq!(bytes[0], 0xbf);
        bytes.extend([0x22, 1, 1]);
        assert_eq!(
            decode_sals(&bytes).unwrap(),
            vec![
                request,
                AccessControlMessage::PointClosed { zone: 1, point: 1 }
            ]
        );
        assert!(AccessControlMessage::AccessRequestInvalid {
            zone: 1,
            point: 1,
            direction: 0,
            data: vec![0; MAX_ACCESS_DATA + 1],
        }
        .encode()
        .is_err());
        assert!(AccessControlMessage::AccessRequestValid {
            zone: 1,
            point: 1,
            direction: 3,
            data: vec![],
        }
        .encode()
        .is_err());
    }

    #[test]
    fn malformed_unknown_or_native_out_of_range_payloads_fail_closed() {
        for bytes in [
            &[][..],
            &[0x02, 1],
            &[0x2a, 1, 2],
            &[0x3a, 1, 2],
            &[0x03, 1, 2, 3],
            &[0x01, 1],
            &[0x02, 255, 1],
            &[0x02, 1, 255],
            &[0x82, 1, 2],
            &[0xe3, 1, 2, 0],
            &[0xa2, 1, 2],
            &[0xa3, 1, 2, 3],
            &[0xa3, 255, 2, 1],
            &[0xa5, 1, 2, 1, 0],
            &[0x02, 1, 2, 0x22],
        ] {
            assert!(decode_sals(bytes).is_err(), "{bytes:02x?}");
        }
    }
}
