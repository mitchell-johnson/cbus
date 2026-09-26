//! Access Control application (0xD5) SAL messages.
//!
//! C-Gate 3.4 represents point commands as a standard three-byte SAL:
//! the short command header followed by zone and point addresses.  The same
//! shape is used by the device observations retained here.

use crate::{DecodeError, EncodeError};

const CLOSE: u8 = 0x02;
const LOCK: u8 = 0x0a;
const LEFT_OPEN: u8 = 0x12;
const FORCED_OPEN: u8 = 0x1a;
const CLOSED: u8 = 0x22;
const EXIT_REQUEST: u8 = 0x32;

/// A command or observation for one Access Control point.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
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
}

impl AccessControlMessage {
    /// Encode the native three-byte SAL payload.
    pub fn encode(&self) -> Result<Vec<u8>, EncodeError> {
        let (opcode, zone, point) = match *self {
            Self::Close { zone, point } => (CLOSE, zone, point),
            Self::Lock { zone, point } => (LOCK, zone, point),
            Self::PointLeftOpen { zone, point } => (LEFT_OPEN, zone, point),
            Self::PointForcedOpen { zone, point } => (FORCED_OPEN, zone, point),
            Self::PointClosed { zone, point } => (CLOSED, zone, point),
            Self::ExitRequest { zone, point } => (EXIT_REQUEST, zone, point),
        };
        Ok(vec![opcode, zone, point])
    }
}

/// Decode one or more concatenated three-byte Access Control messages.
pub fn decode_sals(data: &[u8]) -> Result<Vec<AccessControlMessage>, DecodeError> {
    if data.is_empty() || !data.len().is_multiple_of(3) {
        return Err(DecodeError::new("invalid Access Control SAL length"));
    }
    data.as_chunks::<3>()
        .0
        .iter()
        .map(|chunk| {
            let zone = chunk[1];
            let point = chunk[2];
            match chunk[0] {
                CLOSE => Ok(AccessControlMessage::Close { zone, point }),
                LOCK => Ok(AccessControlMessage::Lock { zone, point }),
                LEFT_OPEN => Ok(AccessControlMessage::PointLeftOpen { zone, point }),
                FORCED_OPEN => Ok(AccessControlMessage::PointForcedOpen { zone, point }),
                CLOSED => Ok(AccessControlMessage::PointClosed { zone, point }),
                EXIT_REQUEST => Ok(AccessControlMessage::ExitRequest { zone, point }),
                opcode => Err(DecodeError::new(format!(
                    "unknown Access Control opcode 0x{opcode:02x}"
                ))),
            }
        })
        .collect()
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
                    zone: 255,
                    point: 0,
                },
                vec![0x0a, 255, 0],
            ),
        ] {
            assert_eq!(message.encode().unwrap(), bytes);
            assert_eq!(decode_sals(&bytes).unwrap(), vec![message]);
        }
    }

    #[test]
    fn malformed_or_unknown_payloads_fail_closed() {
        assert!(decode_sals(&[]).is_err());
        assert!(decode_sals(&[0x02, 1]).is_err());
        assert!(decode_sals(&[0x2a, 1, 2]).is_err());
    }
}
