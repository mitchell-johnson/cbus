//! C-Bus network-management and learn-mode SAL codecs retained by C-Gate 3.4.
//!
//! `NETWORK LOCATE` uses application `0xD0`, which is also used by the
//! Security family.  Its `0x13` and `0x16` payload prefixes are disjoint from
//! the retained Security layouts.  `NET LEARN` sends the four-byte learn-mode
//! payload on the caller-selected application.

use crate::serial_address::NativeSerial;
use crate::{DecodeError, EncodeError};

/// Network-management application used by `NETWORK LOCATE`.
pub const APP_NETWORK_MANAGEMENT: u8 = 0xd0;

/// One target selector carried by a locate-yourself command.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum LocateTarget {
    /// Match one C-Bus unit address.
    Unit(u8),
    /// Match every unit supporting an application.
    Application(u8),
    /// Match one application/group pair.
    Group {
        /// Application address.
        application: u8,
        /// Group address within the application.
        group: u8,
    },
    /// Match one manufacturer and native decimal-dot serial identity.
    Serial {
        /// Manufacturer identifier.
        manufacturer: u8,
        /// Native C-Bus unit serial identity.
        serial: NativeSerial,
    },
}

/// Native `NETWORK LOCATE` payload.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NetworkLocate {
    /// Unit/application/group/serial selector.
    pub target: LocateTarget,
    /// Locate mode (`OFF=0`, `ON=1`, or an explicit byte).
    pub mode: u8,
}

impl NetworkLocate {
    /// Encode the exact C-Gate 3.4 SAL payload.
    pub fn encode(&self) -> Result<Vec<u8>, EncodeError> {
        Ok(match &self.target {
            LocateTarget::Unit(unit) => vec![0x13, 0xff, *unit, self.mode],
            LocateTarget::Application(application) => {
                if *application == 0xff {
                    return Err(EncodeError::new(
                        "Network locate application must be in 0..254",
                    ));
                }
                vec![0x13, *application, 0xff, self.mode]
            }
            LocateTarget::Group { application, group } => {
                if *application == 0xff || *group == 0xff {
                    return Err(EncodeError::new(
                        "Network locate group application and group must be in 0..254",
                    ));
                }
                vec![0x13, *application, *group, self.mode]
            }
            LocateTarget::Serial {
                manufacturer,
                serial,
            } => {
                let mut bytes = Vec::with_capacity(7);
                bytes.extend_from_slice(&[0x16, *manufacturer]);
                bytes.extend_from_slice(&serial.packed);
                bytes.push(self.mode);
                bytes
            }
        })
    }
}

/// Native application learn-mode payload.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LearnMode {
    /// Application carrying the command.
    pub application: u8,
    /// Native grade: 1, 2, or 128 through 131.
    pub grade: u8,
    /// Group address.
    pub group: u8,
}

impl LearnMode {
    /// Encode opcode, grade, group and the retained inner checksum byte.
    pub fn encode(&self) -> Result<Vec<u8>, EncodeError> {
        if !matches!(self.grade, 1 | 2 | 128..=131) {
            return Err(EncodeError::new("Learn grade must be 1, 2, or in 128..131"));
        }
        let checksum = 0_u8.wrapping_sub(self.grade.wrapping_add(self.group));
        Ok(vec![0x03, self.grade, self.group, checksum])
    }
}

/// Decode an exact locate-yourself payload.
pub fn decode_locate(data: &[u8]) -> Result<NetworkLocate, DecodeError> {
    let (target, mode) = match data {
        [0x13, 0xff, unit, mode] => (LocateTarget::Unit(*unit), *mode),
        [0x13, application, 0xff, mode] => (LocateTarget::Application(*application), *mode),
        [0x13, application, group, mode] => (
            LocateTarget::Group {
                application: *application,
                group: *group,
            },
            *mode,
        ),
        [0x16, manufacturer, serial @ .., mode] if serial.len() == 4 => {
            let packed: [u8; 4] = serial.try_into().expect("four-byte slice");
            let combined = u32::from_be_bytes(packed);
            let first = combined >> 12;
            let second = combined & 0x0fff;
            (
                LocateTarget::Serial {
                    manufacturer: *manufacturer,
                    serial: NativeSerial {
                        first,
                        second,
                        canonical: format!("{first}.{second}"),
                        packed,
                        known: (first, second) != (0, 0) && (first, second) != (1_048_575, 4095),
                    },
                },
                *mode,
            )
        }
        _ => return Err(DecodeError::new("invalid network locate payload")),
    };
    Ok(NetworkLocate { target, mode })
}

/// Decode and validate an exact learn-mode payload for `application`.
pub fn decode_learn(application: u8, data: &[u8]) -> Result<LearnMode, DecodeError> {
    let [0x03, grade, group, checksum] = data else {
        return Err(DecodeError::new("invalid learn-mode payload"));
    };
    if !matches!(*grade, 1 | 2 | 128..=131) {
        return Err(DecodeError::new("invalid learn-mode grade"));
    }
    if grade.wrapping_add(*group).wrapping_add(*checksum) != 0 {
        return Err(DecodeError::new("invalid learn-mode checksum"));
    }
    Ok(LearnMode {
        application,
        grade: *grade,
        group: *group,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::serial_address::parse_native_serial;

    #[test]
    fn retained_locate_vectors_round_trip() {
        let cases = [
            (
                NetworkLocate {
                    target: LocateTarget::Unit(1),
                    mode: 1,
                },
                vec![0x13, 0xff, 0x01, 0x01],
            ),
            (
                NetworkLocate {
                    target: LocateTarget::Application(56),
                    mode: 2,
                },
                vec![0x13, 0x38, 0xff, 0x02],
            ),
            (
                NetworkLocate {
                    target: LocateTarget::Group {
                        application: 56,
                        group: 1,
                    },
                    mode: 0,
                },
                vec![0x13, 0x38, 0x01, 0x00],
            ),
            (
                NetworkLocate {
                    target: LocateTarget::Serial {
                        manufacturer: 1,
                        serial: parse_native_serial("12345.67").unwrap(),
                    },
                    mode: 255,
                },
                vec![0x16, 0x01, 0x03, 0x03, 0x90, 0x43, 0xff],
            ),
        ];
        for (command, bytes) in cases {
            assert_eq!(command.encode().unwrap(), bytes);
            assert_eq!(decode_locate(&bytes).unwrap(), command);
        }
    }

    #[test]
    fn retained_learn_vector_and_guards() {
        let command = LearnMode {
            application: 56,
            grade: 1,
            group: 1,
        };
        let bytes = vec![0x03, 0x01, 0x01, 0xfe];
        assert_eq!(command.encode().unwrap(), bytes);
        assert_eq!(decode_learn(56, &bytes).unwrap(), command);
        assert!(LearnMode {
            application: 56,
            grade: 3,
            group: 1,
        }
        .encode()
        .is_err());
        assert!(decode_learn(56, &[0x03, 0x01, 0x01, 0xff]).is_err());
    }
}
