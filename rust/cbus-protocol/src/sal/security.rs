//! Security application SAL commands and reports implemented by C-Gate 3.4.
//!
//! The layouts and bounds here are pinned to an isolated C-Gate
//! 3.4.0.2001 instance and its retained decoder. Security commands are
//! broadcasts: PCI confirmation proves interface delivery, not acceptance by
//! an alarm panel.

use crate::{DecodeError, EncodeError};

/// Native Security system arm mode.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SecurityArmMode {
    /// Arm the premises in away mode.
    Away,
    /// Arm the premises in night mode.
    Night,
    /// Arm the premises in day mode.
    Day,
    /// Arm the premises in vacation mode.
    Vacation,
    /// Request the panel's highest supported arm mode.
    Highest,
}

impl SecurityArmMode {
    /// Return the native Security application byte value.
    pub fn value(self) -> u8 {
        match self {
            Self::Away => 1,
            Self::Night => 2,
            Self::Day => 3,
            Self::Vacation => 4,
            Self::Highest => 255,
        }
    }

    /// Return the lower-case C-Gate command name.
    pub fn name(self) -> &'static str {
        match self {
            Self::Away => "away",
            Self::Night => "night",
            Self::Day => "day",
            Self::Vacation => "vacation",
            Self::Highest => "highest",
        }
    }

    /// Decode a native Security arm-mode byte.
    pub fn from_value(value: u8) -> Result<Self, DecodeError> {
        match value {
            1 => Ok(Self::Away),
            2 => Ok(Self::Night),
            3 => Ok(Self::Day),
            4 => Ok(Self::Vacation),
            255 => Ok(Self::Highest),
            _ => Err(DecodeError::new("Security arm mode is out of range")),
        }
    }
}

/// Public native C-Gate SECURITY command payload.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SecurityCommand {
    /// Request status report 1 or 2.
    StatusRequest {
        /// Report number; the encoder accepts only 1 or 2.
        report: u8,
    },
    /// Request a system arm mode.
    Arm {
        /// Requested native arm mode.
        mode: SecurityArmMode,
    },
    /// Raise or drop the system tamper indication.
    Tamper {
        /// `true` raises tamper; `false` drops it.
        raised: bool,
    },
    /// Raise the general alarm indication.
    RaiseAlarm,
    /// Emulate one keypad byte.
    EmulateKeypad {
        /// Native keypad byte.
        key: u8,
    },
    /// Send raw message bytes to a Security display.
    DisplayMessage {
        /// Message bytes. The protocol accepts at most 18 observed bytes;
        /// C-Gate's command parser emits at most 17.
        message: Vec<u8>,
    },
    /// Ask the panel to report one zone name.
    RequestZoneName {
        /// Zone number in 1..=127.
        zone: u8,
    },
}

impl SecurityCommand {
    /// Return the native C-Gate event name for an observed command.
    pub fn event_name(&self) -> &'static str {
        match self {
            Self::StatusRequest { .. } => "status_request",
            Self::Arm { .. } => "arm",
            Self::Tamper { .. } => "tamper",
            Self::RaiseAlarm => "raise_alarm",
            Self::EmulateKeypad { .. } => "emulate_keypad",
            Self::DisplayMessage { .. } => "display_message",
            Self::RequestZoneName { .. } => "request_zone_name",
        }
    }

    /// Format native C-Gate event arguments for an observed command.
    pub fn event_arguments(&self) -> String {
        match self {
            Self::StatusRequest { report } => report.to_string(),
            Self::Arm { mode } => mode.name().to_owned(),
            Self::Tamper { raised } => if *raised { "raise" } else { "drop" }.to_owned(),
            Self::RaiseAlarm => String::new(),
            Self::EmulateKeypad { key } => key.to_string(),
            Self::DisplayMessage { message } => escape_bytes(message),
            Self::RequestZoneName { .. } => String::new(),
        }
    }

    /// Return the zone encoded in this command, when it addresses one zone.
    pub fn zone(&self) -> Option<u8> {
        match self {
            Self::RequestZoneName { zone } => Some(*zone),
            _ => None,
        }
    }

    /// Exact SAL bytes excluding the point-to-multipoint envelope.
    pub fn encode(&self) -> Result<Vec<u8>, EncodeError> {
        match self {
            Self::StatusRequest { report: 1 } => Ok(vec![0x09, 0xa0]),
            Self::StatusRequest { report: 2 } => Ok(vec![0x09, 0xa1]),
            Self::StatusRequest { .. } => {
                Err(EncodeError::new("Security status report is out of range"))
            }
            Self::Arm { mode } => Ok(vec![0x0a, 0xa2, mode.value()]),
            Self::Tamper { raised } => Ok(vec![if *raised { 0x79 } else { 0x01 }, 0xa3]),
            Self::RaiseAlarm => Ok(vec![0x79, 0xa4]),
            Self::EmulateKeypad { key } => Ok(vec![0x0a, 0xa5, *key]),
            Self::DisplayMessage { message } => {
                // The native command parser emits at most 17 bytes because
                // it applies a 34-hex-character bound before constructing
                // SAL. Its application decoder nevertheless accepts the
                // protocol's full E1..F3 form, including 18 observed bytes.
                if message.len() > 18 {
                    return Err(EncodeError::new(
                        "Security display message is longer than 18 bytes",
                    ));
                }
                let mut out = Vec::with_capacity(message.len() + 2);
                out.push(0xe0 | (message.len() as u8 + 1));
                out.push(0xa6);
                out.extend_from_slice(message);
                Ok(out)
            }
            Self::RequestZoneName { zone } => {
                validate_zone_encode(*zone)?;
                Ok(vec![0x0a, 0xa7, *zone])
            }
        }
    }
}

/// Security application observations recognized by native C-Gate 3.4.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SecurityEvent {
    /// Report the current arm state.
    SystemArm {
        /// Native state value in 0..=127.
        state: u8,
    },
    /// Report that the exit delay started.
    ExitDelayStarted,
    /// Report that the entry delay started.
    EntryDelayStarted,
    /// Report the general alarm flag.
    Alarm {
        /// Whether the alarm is active.
        active: bool,
    },
    /// Report the tamper flag.
    Tamper {
        /// Whether tamper is active.
        active: bool,
    },
    /// Report the panic flag.
    Panic {
        /// Whether panic is active.
        active: bool,
    },
    /// Report an unsealed zone.
    ZoneUnsealed {
        /// Zone number in 1..=127.
        zone: u8,
    },
    /// Report a sealed zone.
    ZoneSealed {
        /// Zone number in 1..=127.
        zone: u8,
    },
    /// Report an open-circuit zone.
    ZoneOpen {
        /// Zone number in 1..=127.
        zone: u8,
    },
    /// Report a short-circuit zone.
    ZoneShort {
        /// Zone number in 1..=127.
        zone: u8,
    },
    /// Report an isolated zone.
    ZoneIsolated {
        /// Zone number in 1..=127.
        zone: u8,
    },
    /// Report the system low-battery flag.
    LowBattery {
        /// Whether low battery is detected.
        detected: bool,
    },
    /// Report the battery-charging flag.
    BatteryCharging {
        /// Whether charging is active.
        active: bool,
    },
    /// Report one fixed-width zone name.
    ZoneName {
        /// Zone number in 1..=127.
        zone: u8,
        /// Exactly 11 raw name bytes.
        name: Vec<u8>,
    },
    /// Report arm/tamper/panic state and zones 1 through 32.
    StatusReport1 {
        /// Native arm-state value in 0..=127.
        arm_state: u8,
        /// Whether tamper is active.
        tamper: bool,
        /// Whether panic is active.
        panic: bool,
        /// Exactly 32 two-bit zone states in zone order.
        zones: Vec<u8>,
    },
    /// Report zones 33 through 80.
    StatusReport2 {
        /// Exactly 48 two-bit zone states in zone order.
        zones: Vec<u8>,
    },
    /// Report the password-entry status.
    PasswordEntryStatus {
        /// Native status in 1..=4.
        status: u8,
    },
    /// Report mains power state.
    Mains {
        /// Whether mains power has been restored.
        restored: bool,
    },
    /// Report that the panel is ready to arm.
    ArmReady,
    /// Report the zone preventing the panel from arming.
    ArmNotReady {
        /// Zone number in 1..=127.
        zone: u8,
    },
    /// Report the current alarm type.
    CurrentAlarmType {
        /// Native alarm type in 0..=254.
        alarm_type: u8,
    },
    /// Report the telephone line-cut alarm flag.
    LineCutAlarm {
        /// Whether the flag is raised.
        raised: bool,
    },
    /// Report the arm-failed flag.
    ArmFailed {
        /// Whether the flag is raised.
        raised: bool,
    },
    /// Report the fire-alarm flag.
    FireAlarm {
        /// Whether the flag is raised.
        raised: bool,
    },
    /// Report the gas-alarm flag.
    GasAlarm {
        /// Whether the flag is raised.
        raised: bool,
    },
    /// Report the other-alarm flag.
    OtherAlarm {
        /// Whether the flag is raised.
        raised: bool,
    },
}

impl SecurityEvent {
    /// Return the native C-Gate event name.
    pub fn event_name(&self) -> &'static str {
        match self {
            Self::SystemArm { .. } => "system_arm",
            Self::ExitDelayStarted => "exit_delay_started",
            Self::EntryDelayStarted => "entry_delay_started",
            Self::Alarm { active: true } => "alarm_on",
            Self::Alarm { active: false } => "alarm_off",
            Self::Tamper { active: true } => "tamper_on",
            Self::Tamper { active: false } => "tamper_off",
            Self::Panic { active: true } => "panic_activated",
            Self::Panic { active: false } => "panic_cleared",
            Self::ZoneUnsealed { .. } => "zone_unsealed",
            Self::ZoneSealed { .. } => "zone_sealed",
            Self::ZoneOpen { .. } => "zone_open",
            Self::ZoneShort { .. } => "zone_short",
            Self::ZoneIsolated { .. } => "zone_isolated",
            Self::LowBattery { detected: true } => "low_battery_detected",
            Self::LowBattery { detected: false } => "low_battery_corrected",
            Self::BatteryCharging { .. } => "battery_charging",
            Self::ZoneName { .. } => "zone_name",
            Self::StatusReport1 { .. } => "status_report_1",
            Self::StatusReport2 { .. } => "status_report_2",
            Self::PasswordEntryStatus { .. } => "password_entry_status",
            Self::Mains { restored: false } => "mains_failure",
            Self::Mains { restored: true } => "mains_restored",
            Self::ArmReady => "arm_ready",
            Self::ArmNotReady { .. } => "arm_not_ready",
            Self::CurrentAlarmType { .. } => "current_alarm_type",
            Self::LineCutAlarm { .. } => "line_cut_alarm",
            Self::ArmFailed { .. } => "arm_failed",
            Self::FireAlarm { .. } => "fire_alarm",
            Self::GasAlarm { .. } => "gas_alarm",
            Self::OtherAlarm { .. } => "other_alarm",
        }
    }

    /// Return the zone addressed by this event, when present.
    pub fn zone(&self) -> Option<u8> {
        match self {
            Self::ZoneUnsealed { zone }
            | Self::ZoneSealed { zone }
            | Self::ZoneOpen { zone }
            | Self::ZoneShort { zone }
            | Self::ZoneIsolated { zone }
            | Self::ZoneName { zone, .. }
            | Self::ArmNotReady { zone } => Some(*zone),
            _ => None,
        }
    }

    /// Format the native C-Gate event arguments.
    pub fn event_arguments(&self) -> String {
        match self {
            Self::SystemArm { state } => state.to_string(),
            Self::BatteryCharging { active } => {
                if *active { "started" } else { "stopped" }.to_owned()
            }
            Self::ZoneName { name, .. } => escape_bytes(name),
            Self::StatusReport1 {
                arm_state,
                tamper,
                panic,
                zones,
            } => {
                let mut fields = vec![
                    arm_state.to_string(),
                    u8::from(*tamper).wrapping_mul(255).to_string(),
                    u8::from(*panic).wrapping_mul(255).to_string(),
                ];
                fields.extend(zones.iter().map(u8::to_string));
                fields.join(" ")
            }
            Self::StatusReport2 { zones } => zones
                .iter()
                .map(u8::to_string)
                .collect::<Vec<_>>()
                .join(" "),
            Self::PasswordEntryStatus { status } => status.to_string(),
            Self::CurrentAlarmType { alarm_type } => alarm_type.to_string(),
            Self::LineCutAlarm { raised } => if *raised {
                "line_cut_alarm_raised"
            } else {
                "line_cut_alarm_cleared"
            }
            .to_owned(),
            Self::ArmFailed { raised } => if *raised {
                "arm_failed_raised"
            } else {
                "arm_failed_cleared"
            }
            .to_owned(),
            Self::FireAlarm { raised } => if *raised {
                "fire_alarm_raised"
            } else {
                "fire_alarm_cleared"
            }
            .to_owned(),
            Self::GasAlarm { raised } => if *raised {
                "gas_alarm_raised"
            } else {
                "gas_alarm_cleared"
            }
            .to_owned(),
            Self::OtherAlarm { raised } => if *raised {
                "other_alarm_raised"
            } else {
                "other_alarm_cleared"
            }
            .to_owned(),
            _ => String::new(),
        }
    }

    /// Exact SAL bytes excluding the point-to-multipoint envelope.
    pub fn encode(&self) -> Result<Vec<u8>, EncodeError> {
        match self {
            Self::SystemArm { state: 0 } => Ok(vec![0x01, 0x80]),
            Self::SystemArm { state } if *state <= 127 => Ok(vec![0x7a, 0x80, *state]),
            Self::SystemArm { .. } => Err(EncodeError::new("Security arm state is out of range")),
            Self::ExitDelayStarted => Ok(vec![0x09, 0x81]),
            Self::EntryDelayStarted => Ok(vec![0x09, 0x82]),
            Self::Alarm { active } => Ok(bool_sal(*active, 0x83)),
            Self::Tamper { active } => Ok(bool_sal(*active, 0x84)),
            Self::Panic { active } => Ok(bool_sal(*active, 0x85)),
            Self::ZoneUnsealed { zone } => zone_sal(*zone, 0x86),
            Self::ZoneSealed { zone } => zone_sal(*zone, 0x87),
            Self::ZoneOpen { zone } => zone_sal(*zone, 0x88),
            Self::ZoneShort { zone } => zone_sal(*zone, 0x89),
            Self::ZoneIsolated { zone } => zone_sal(*zone, 0x8a),
            Self::LowBattery { detected } => Ok(bool_sal(*detected, 0x8b)),
            Self::BatteryCharging { active } => Ok(vec![0x0a, 0x8c, if *active { 255 } else { 0 }]),
            Self::ZoneName { zone, name } => {
                validate_zone_encode(*zone)?;
                if name.len() != 11 {
                    return Err(EncodeError::new(
                        "Security zone name must contain exactly 11 bytes",
                    ));
                }
                let mut out = vec![0xad, 0x8d, *zone];
                out.extend_from_slice(name);
                Ok(out)
            }
            Self::StatusReport1 {
                arm_state,
                tamper,
                panic,
                zones,
            } => {
                if *arm_state > 127 {
                    return Err(EncodeError::new("Security arm state is out of range"));
                }
                if zones.len() != 32 {
                    return Err(EncodeError::new(
                        "Security status report 1 requires 32 zone states",
                    ));
                }
                let mut out = vec![
                    0xac,
                    0x8e,
                    *arm_state,
                    if *tamper { 255 } else { 0 },
                    if *panic { 255 } else { 0 },
                ];
                out.extend(pack_zones(zones)?);
                Ok(out)
            }
            Self::StatusReport2 { zones } => {
                if zones.len() != 48 {
                    return Err(EncodeError::new(
                        "Security status report 2 requires 48 zone states",
                    ));
                }
                let mut out = vec![0xad, 0x8f];
                out.extend(pack_zones(zones)?);
                Ok(out)
            }
            Self::PasswordEntryStatus { status } if (1..=4).contains(status) => {
                Ok(vec![0x0a, 0x90, *status])
            }
            Self::PasswordEntryStatus { .. } => Err(EncodeError::new(
                "Security password entry status is out of range",
            )),
            Self::Mains { restored } => Ok(bool_sal(!*restored, 0x91)),
            Self::ArmReady => Ok(vec![0x0a, 0x92, 0]),
            Self::ArmNotReady { zone } => zone_sal(*zone, 0x92),
            Self::CurrentAlarmType { alarm_type } if *alarm_type <= 254 => {
                Ok(vec![0x0a, 0x93, *alarm_type])
            }
            Self::CurrentAlarmType { .. } => {
                Err(EncodeError::new("Security alarm type is out of range"))
            }
            Self::LineCutAlarm { raised } => Ok(bool_sal(*raised, 0x94)),
            Self::ArmFailed { raised } => Ok(bool_sal(*raised, 0x95)),
            Self::FireAlarm { raised } => Ok(bool_sal(*raised, 0x96)),
            Self::GasAlarm { raised } => Ok(bool_sal(*raised, 0x97)),
            Self::OtherAlarm { raised } => Ok(bool_sal(*raised, 0x98)),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
/// A decoded Security SAL classified as an observed command or device event.
pub enum SecuritySal {
    /// A command observed on the shared C-Bus network.
    Command(SecurityCommand),
    /// A device event or report observed on the shared C-Bus network.
    Event(SecurityEvent),
}

/// Decode one or more Security SALs from a point-to-multipoint payload.
pub fn decode_sals(data: &[u8]) -> Result<Vec<SecuritySal>, DecodeError> {
    let mut messages = Vec::new();
    let mut offset = 0;
    while offset < data.len() {
        if data.len() - offset < 2 {
            return Err(DecodeError::new("truncated Security SAL"));
        }
        let prefix = data[offset];
        let opcode = data[offset + 1];
        let len = match prefix {
            0x01 | 0x09 | 0x79 => 2,
            0x0a | 0x7a => 3,
            0xac => 13,
            0xad => 14,
            0xe1..=0xf3 if opcode == 0xa6 => usize::from(prefix & 0x1f) + 1,
            _ => {
                return Err(DecodeError::new(format!(
                    "unknown Security SAL prefix 0x{prefix:02x}"
                )))
            }
        };
        if data.len() - offset < len {
            return Err(DecodeError::new("truncated Security SAL"));
        }
        messages.push(decode_one(&data[offset..offset + len])?);
        offset += len;
    }
    Ok(messages)
}

fn decode_one(bytes: &[u8]) -> Result<SecuritySal, DecodeError> {
    let prefix = bytes[0];
    let opcode = bytes[1];
    let arg = bytes.get(2).copied();
    let command = match opcode {
        0xa0 if prefix == 0x09 => Some(SecurityCommand::StatusRequest { report: 1 }),
        0xa1 if prefix == 0x09 => Some(SecurityCommand::StatusRequest { report: 2 }),
        0xa2 if prefix == 0x0a => Some(SecurityCommand::Arm {
            mode: SecurityArmMode::from_value(arg.unwrap())?,
        }),
        0xa3 if prefix == 0x01 || prefix == 0x79 => Some(SecurityCommand::Tamper {
            raised: prefix == 0x79,
        }),
        0xa4 if prefix == 0x79 => Some(SecurityCommand::RaiseAlarm),
        0xa5 if prefix == 0x0a => Some(SecurityCommand::EmulateKeypad { key: arg.unwrap() }),
        0xa6 if (0xe1..=0xf3).contains(&prefix) => Some(SecurityCommand::DisplayMessage {
            message: bytes[2..].to_vec(),
        }),
        0xa7 if prefix == 0x0a => {
            validate_zone_decode(arg.unwrap())?;
            Some(SecurityCommand::RequestZoneName { zone: arg.unwrap() })
        }
        _ => None,
    };
    if let Some(command) = command {
        return Ok(SecuritySal::Command(command));
    }
    let event = match opcode {
        0x80 if prefix == 0x01 => SecurityEvent::SystemArm { state: 0 },
        0x80 if prefix == 0x7a && arg.unwrap() <= 127 => SecurityEvent::SystemArm {
            state: arg.unwrap(),
        },
        0x81 if prefix == 0x09 => SecurityEvent::ExitDelayStarted,
        0x82 if prefix == 0x09 => SecurityEvent::EntryDelayStarted,
        0x83 => SecurityEvent::Alarm {
            active: decode_bool_prefix(prefix)?,
        },
        0x84 => SecurityEvent::Tamper {
            active: decode_bool_prefix(prefix)?,
        },
        0x85 => SecurityEvent::Panic {
            active: decode_bool_prefix(prefix)?,
        },
        0x86 if prefix == 0x0a => SecurityEvent::ZoneUnsealed {
            zone: checked_zone(arg.unwrap())?,
        },
        0x87 if prefix == 0x0a => SecurityEvent::ZoneSealed {
            zone: checked_zone(arg.unwrap())?,
        },
        0x88 if prefix == 0x0a => SecurityEvent::ZoneOpen {
            zone: checked_zone(arg.unwrap())?,
        },
        0x89 if prefix == 0x0a => SecurityEvent::ZoneShort {
            zone: checked_zone(arg.unwrap())?,
        },
        0x8a if prefix == 0x0a => SecurityEvent::ZoneIsolated {
            zone: checked_zone(arg.unwrap())?,
        },
        0x8b => SecurityEvent::LowBattery {
            detected: decode_bool_prefix(prefix)?,
        },
        0x8c if prefix == 0x0a && matches!(arg, Some(0 | 255)) => SecurityEvent::BatteryCharging {
            active: arg == Some(255),
        },
        0x8d if prefix == 0xad => SecurityEvent::ZoneName {
            zone: checked_zone(arg.unwrap())?,
            name: bytes[3..].to_vec(),
        },
        0x8e if prefix == 0xac
            && bytes[2] <= 127
            && matches!(bytes[3], 0 | 255)
            && matches!(bytes[4], 0 | 255) =>
        {
            SecurityEvent::StatusReport1 {
                arm_state: bytes[2],
                tamper: bytes[3] == 255,
                panic: bytes[4] == 255,
                zones: unpack_zones(&bytes[5..]),
            }
        }
        0x8f if prefix == 0xad => SecurityEvent::StatusReport2 {
            zones: unpack_zones(&bytes[2..]),
        },
        0x90 if prefix == 0x0a && matches!(arg, Some(1..=4)) => {
            SecurityEvent::PasswordEntryStatus {
                status: arg.unwrap(),
            }
        }
        0x91 => SecurityEvent::Mains {
            restored: !decode_bool_prefix(prefix)?,
        },
        0x92 if prefix == 0x0a && arg == Some(0) => SecurityEvent::ArmReady,
        0x92 if prefix == 0x0a => SecurityEvent::ArmNotReady {
            zone: checked_zone(arg.unwrap())?,
        },
        0x93 if prefix == 0x0a && arg.unwrap() <= 254 => SecurityEvent::CurrentAlarmType {
            alarm_type: arg.unwrap(),
        },
        0x94 => SecurityEvent::LineCutAlarm {
            raised: decode_bool_prefix(prefix)?,
        },
        0x95 => SecurityEvent::ArmFailed {
            raised: decode_bool_prefix(prefix)?,
        },
        0x96 => SecurityEvent::FireAlarm {
            raised: decode_bool_prefix(prefix)?,
        },
        0x97 => SecurityEvent::GasAlarm {
            raised: decode_bool_prefix(prefix)?,
        },
        0x98 => SecurityEvent::OtherAlarm {
            raised: decode_bool_prefix(prefix)?,
        },
        _ => {
            return Err(DecodeError::new(format!(
                "unknown or invalid Security SAL opcode 0x{opcode:02x}"
            )))
        }
    };
    Ok(SecuritySal::Event(event))
}

fn bool_sal(active: bool, opcode: u8) -> Vec<u8> {
    vec![if active { 0x79 } else { 0x01 }, opcode]
}
fn decode_bool_prefix(prefix: u8) -> Result<bool, DecodeError> {
    match prefix {
        0x79 => Ok(true),
        0x01 => Ok(false),
        _ => Err(DecodeError::new("invalid Security boolean SAL prefix")),
    }
}
fn checked_zone(zone: u8) -> Result<u8, DecodeError> {
    validate_zone_decode(zone)?;
    Ok(zone)
}
fn validate_zone_decode(zone: u8) -> Result<(), DecodeError> {
    if (1..=127).contains(&zone) {
        Ok(())
    } else {
        Err(DecodeError::new("Security zone is out of range"))
    }
}
fn validate_zone_encode(zone: u8) -> Result<(), EncodeError> {
    if (1..=127).contains(&zone) {
        Ok(())
    } else {
        Err(EncodeError::new("Security zone is out of range"))
    }
}
fn zone_sal(zone: u8, opcode: u8) -> Result<Vec<u8>, EncodeError> {
    validate_zone_encode(zone)?;
    Ok(vec![0x0a, opcode, zone])
}

fn unpack_zones(bytes: &[u8]) -> Vec<u8> {
    bytes
        .iter()
        .flat_map(|byte| [byte >> 6, (byte >> 4) & 3, (byte >> 2) & 3, byte & 3])
        .collect()
}
fn pack_zones(zones: &[u8]) -> Result<Vec<u8>, EncodeError> {
    if zones.iter().any(|state| *state > 3) {
        return Err(EncodeError::new("Security zone state is out of range"));
    }
    Ok(zones
        .chunks_exact(4)
        .map(|z| (z[0] << 6) | (z[1] << 4) | (z[2] << 2) | z[3])
        .collect())
}

/// C-Gate command/event escaping for byte-oriented Security strings.
pub fn escape_bytes(bytes: &[u8]) -> String {
    let mut out = String::new();
    for byte in bytes {
        match *byte {
            b'\\' => out.push_str("\\\\"),
            0x21..=0x7e => out.push(char::from(*byte)),
            _ => out.push_str(&format!("\\x{byte:02X}")),
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn captured_commands_round_trip() {
        let cases = [
            (
                SecurityCommand::StatusRequest { report: 1 },
                vec![0x09, 0xa0],
            ),
            (
                SecurityCommand::Arm {
                    mode: SecurityArmMode::Vacation,
                },
                vec![0x0a, 0xa2, 4],
            ),
            (SecurityCommand::Tamper { raised: true }, vec![0x79, 0xa3]),
            (SecurityCommand::RaiseAlarm, vec![0x79, 0xa4]),
            (
                SecurityCommand::EmulateKeypad { key: 0x41 },
                vec![0x0a, 0xa5, 0x41],
            ),
            (
                SecurityCommand::DisplayMessage {
                    message: b"HELLO".to_vec(),
                },
                vec![0xe6, 0xa6, b'H', b'E', b'L', b'L', b'O'],
            ),
            (
                SecurityCommand::RequestZoneName { zone: 127 },
                vec![0x0a, 0xa7, 127],
            ),
        ];
        for (command, bytes) in cases {
            assert_eq!(command.encode().unwrap(), bytes);
            assert_eq!(
                decode_sals(&bytes).unwrap(),
                vec![SecuritySal::Command(command)]
            );
        }
    }

    #[test]
    fn reports_round_trip_and_unpack_high_pairs_first() {
        let report = SecurityEvent::StatusReport1 {
            arm_state: 4,
            tamper: true,
            panic: false,
            zones: (0..32).map(|n| n % 4).collect(),
        };
        let bytes = report.encode().unwrap();
        assert_eq!(&bytes[..6], &[0xac, 0x8e, 4, 255, 0, 0x1b]);
        assert_eq!(
            decode_sals(&bytes).unwrap(),
            vec![SecuritySal::Event(report)]
        );
    }

    #[test]
    fn invalid_and_truncated_forms_fail_closed() {
        for bytes in [
            &[0x0a, 0xa7, 0][..],
            &[0xe3, 0xa6, b'A'][..],
            &[0x79, 0xa2][..],
            &[0x0a, 0x8c, 1][..],
        ] {
            assert!(decode_sals(bytes).is_err(), "{bytes:02X?}");
        }
        assert!(SecurityCommand::DisplayMessage {
            message: vec![b'A'; 19]
        }
        .encode()
        .is_err());
    }
}
