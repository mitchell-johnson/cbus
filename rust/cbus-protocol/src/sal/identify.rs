//! Identify application SAL commands.
//!
//! C-Gate 3.4 registers application 0xFB as a lighting-derived application,
//! but it is not part of the ordinary 0x30..=0x5F lighting range. Keeping a
//! distinct type prevents an observed identify packet from entering lighting
//! state or MQTT handling by accident.

use crate::common::{
    duration_to_ramp_rate, ramp_rate_to_duration, LIGHT_OFF, LIGHT_ON, LIGHT_TERMINATE_RAMP,
};
use crate::{DecodeError, EncodeError};

/// One Identify application command.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum IdentifyCommand {
    /// Switch an identify group on.
    On {
        /// Identify group.
        group: u8,
    },
    /// Switch an identify group off.
    Off {
        /// Identify group.
        group: u8,
    },
    /// Ramp an identify group to a level.
    Ramp {
        /// Identify group.
        group: u8,
        /// Requested duration, snapped to the standard C-Bus rate table.
        duration: u32,
        /// Target level.
        level: u8,
    },
    /// Stop a ramp in progress.
    TerminateRamp {
        /// Identify group.
        group: u8,
    },
}

impl IdentifyCommand {
    /// Exact SAL bytes excluding the point-to-multipoint envelope.
    pub fn encode(self) -> Result<Vec<u8>, EncodeError> {
        Ok(match self {
            Self::On { group } => vec![LIGHT_ON, group],
            Self::Off { group } => vec![LIGHT_OFF, group],
            Self::Ramp {
                group,
                duration,
                level,
            } => vec![duration_to_ramp_rate(duration.into()), group, level],
            Self::TerminateRamp { group } => vec![LIGHT_TERMINATE_RAMP, group],
        })
    }

    /// Addressed identify group.
    pub fn group(self) -> u8 {
        match self {
            Self::On { group }
            | Self::Off { group }
            | Self::Ramp { group, .. }
            | Self::TerminateRamp { group } => group,
        }
    }
}

/// Decode one or more Identify commands.
pub fn decode_sals(data: &[u8]) -> Result<Vec<IdentifyCommand>, DecodeError> {
    let mut commands = Vec::new();
    let mut remaining = data;
    while !remaining.is_empty() {
        if remaining.len() < 2 {
            return Err(DecodeError::new("truncated Identify command"));
        }
        let opcode = remaining[0];
        let group = remaining[1];
        remaining = &remaining[2..];
        let command = match opcode {
            LIGHT_ON => IdentifyCommand::On { group },
            LIGHT_OFF => IdentifyCommand::Off { group },
            LIGHT_TERMINATE_RAMP => IdentifyCommand::TerminateRamp { group },
            rate => {
                let Some(duration) = ramp_rate_to_duration(rate) else {
                    return Err(DecodeError::new(format!(
                        "unsupported Identify opcode 0x{rate:02x}"
                    )));
                };
                let Some((&level, tail)) = remaining.split_first() else {
                    return Err(DecodeError::new("truncated Identify ramp"));
                };
                remaining = tail;
                IdentifyCommand::Ramp {
                    group,
                    duration,
                    level,
                }
            }
        };
        commands.push(command);
    }
    Ok(commands)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn native_commands_round_trip() {
        for (command, encoded) in [
            (IdentifyCommand::On { group: 1 }, vec![0x79, 1]),
            (IdentifyCommand::Off { group: 1 }, vec![0x01, 1]),
            (
                IdentifyCommand::Ramp {
                    group: 1,
                    duration: 20,
                    level: 128,
                },
                vec![0x22, 1, 128],
            ),
            (IdentifyCommand::TerminateRamp { group: 1 }, vec![0x09, 1]),
        ] {
            assert_eq!(command.encode().unwrap(), encoded);
            assert_eq!(decode_sals(&encoded).unwrap(), vec![command]);
        }
    }

    #[test]
    fn malformed_commands_fail_closed() {
        assert!(decode_sals(&[0x79]).is_err());
        assert!(decode_sals(&[0x22, 1]).is_err());
        assert!(decode_sals(&[0x03, 1]).is_err());
    }
}
