//! Air-Conditioning application SAL commands implemented by C-Gate 3.4.
//!
//! The byte layouts are pinned to captures from an isolated owned
//! C-Gate 3.4.0.2001 instance. They are broadcast commands: a PCI
//! confirmation proves delivery to the interface, not acceptance by an HVAC
//! controller.

use crate::{DecodeError, EncodeError};

/// Native C-Gate AIRCON command payload.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum AirconCommand {
    /// Switch every plant in a ward off.
    WardOff {
        /// Ward number (0..=255).
        ward: u8,
    },
    /// Ask a ward to refresh its state.
    Refresh {
        /// Ward number (0..=255).
        ward: u8,
    },
    /// Broadcast an HVAC mode and level to selected zones.
    ZoneHvacMode {
        /// Ward number (0..=255).
        ward: u8,
        /// Zone-selection bitmap; bits 0 through 6 select zones.
        zones: u8,
        /// Plant mode (HVAC 0..=4; humidity 0..=3).
        mode: u8,
        /// Whether the level uses its raw representation.
        raw_level: bool,
        /// Whether setback control is enabled.
        setback_enabled: bool,
        /// Whether guard-limit control is enabled.
        guard_enabled: bool,
        /// Whether the auxiliary level is active.
        use_aux_level: bool,
        /// Plant type byte.
        plant_type: u8,
        /// Raw or engineering level, in native big-endian units.
        level: u16,
        /// Auxiliary level byte.
        aux_level: u8,
    },
    /// Broadcast a humidity mode and level to selected zones.
    ZoneHumidityMode {
        /// Ward number (0..=255).
        ward: u8,
        /// Zone-selection bitmap; bits 0 through 6 select zones.
        zones: u8,
        /// Plant mode (HVAC 0..=4; humidity 0..=3).
        mode: u8,
        /// Whether the level uses its raw representation.
        raw_level: bool,
        /// Whether setback control is enabled.
        setback_enabled: bool,
        /// Whether guard-limit control is enabled.
        guard_enabled: bool,
        /// Whether the auxiliary level is active.
        use_aux_level: bool,
        /// Plant type byte.
        plant_type: u8,
        /// Raw or engineering level, in native big-endian units.
        level: u16,
        /// Auxiliary level byte.
        aux_level: u8,
    },
    /// Set the upper HVAC guard limit.
    HvacUpperGuardLimit {
        /// Ward number (0..=255).
        ward: u8,
        /// Zone-selection bitmap; bits 0 through 6 select zones.
        zones: u8,
        /// Limit in native big-endian units.
        limit: u16,
        /// Plant mode (HVAC 0..=4; humidity 0..=3).
        mode: u8,
        /// Whether the level uses its raw representation.
        raw_level: bool,
    },
    /// Set the lower HVAC guard limit.
    HvacLowerGuardLimit {
        /// Ward number (0..=255).
        ward: u8,
        /// Zone-selection bitmap; bits 0 through 6 select zones.
        zones: u8,
        /// Limit in native big-endian units.
        limit: u16,
        /// Plant mode (HVAC 0..=4; humidity 0..=3).
        mode: u8,
        /// Whether the level uses its raw representation.
        raw_level: bool,
    },
    /// Set the HVAC setback limit.
    HvacSetbackLimit {
        /// Ward number (0..=255).
        ward: u8,
        /// Zone-selection bitmap; bits 0 through 6 select zones.
        zones: u8,
        /// Limit in native big-endian units.
        limit: u16,
        /// Plant mode (HVAC 0..=4; humidity 0..=3).
        mode: u8,
        /// Whether the level uses its raw representation.
        raw_level: bool,
    },
    /// Set the upper humidity guard limit.
    HumidityUpperGuardLimit {
        /// Ward number (0..=255).
        ward: u8,
        /// Zone-selection bitmap; bits 0 through 6 select zones.
        zones: u8,
        /// Limit in native big-endian units.
        limit: u16,
        /// Plant mode (HVAC 0..=4; humidity 0..=3).
        mode: u8,
        /// Whether the level uses its raw representation.
        raw_level: bool,
    },
    /// Set the lower humidity guard limit.
    HumidityLowerGuardLimit {
        /// Ward number (0..=255).
        ward: u8,
        /// Zone-selection bitmap; bits 0 through 6 select zones.
        zones: u8,
        /// Limit in native big-endian units.
        limit: u16,
        /// Plant mode (HVAC 0..=4; humidity 0..=3).
        mode: u8,
        /// Whether the level uses its raw representation.
        raw_level: bool,
    },
    /// Return a ward to its prior operating state.
    WardOn {
        /// Ward number (0..=255).
        ward: u8,
    },
    /// Set the humidity setback limit.
    HumiditySetbackLimit {
        /// Ward number (0..=255).
        ward: u8,
        /// Zone-selection bitmap; bits 0 through 6 select zones.
        zones: u8,
        /// Limit in native big-endian units.
        limit: u16,
        /// Plant mode (HVAC 0..=4; humidity 0..=3).
        mode: u8,
        /// Whether the level uses its raw representation.
        raw_level: bool,
    },
}

/// AIRCON application reports accepted by native C-Gate 3.4.
///
/// These are observations emitted by an HVAC device, rather than commands
/// exposed by the `AIRCON` command family. Keeping them typed prevents a
/// REFRESH response from being discarded as an unknown SAL packet.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum AirconStatus {
    /// One HVAC schedule entry (extended SAL command 0).
    HvacScheduleEntry {
        /// Ward number.
        ward: u8,
        /// Zone-selection bitmap (bits 0 through 6).
        zones: u8,
        /// Schedule entry number.
        entry: u8,
        /// Schedule format (1..=7).
        format: u8,
        /// HVAC mode (0..=4).
        mode: u8,
        /// Whether the set level uses its raw representation.
        raw_level: bool,
        /// Whether setback control is enabled.
        setback_enabled: bool,
        /// Whether guard-limit control is enabled.
        guard_enabled: bool,
        /// Whether the auxiliary level is active.
        use_aux_level: bool,
        /// Minutes from Sunday 00:00.
        start_time: u16,
        /// Scheduled set level in native units.
        set_level: u16,
    },
    /// One humidity schedule entry (extended SAL command 1).
    HumidityScheduleEntry {
        /// Ward number.
        ward: u8,
        /// Zone-selection bitmap (bits 0 through 6).
        zones: u8,
        /// Schedule entry number.
        entry: u8,
        /// Schedule format (1..=7).
        format: u8,
        /// Humidity mode (0..=3).
        mode: u8,
        /// Whether the set level uses its raw representation.
        raw_level: bool,
        /// Whether setback control is enabled.
        setback_enabled: bool,
        /// Whether guard-limit control is enabled.
        guard_enabled: bool,
        /// Whether the auxiliary level is active.
        use_aux_level: bool,
        /// Minutes from Sunday 00:00.
        start_time: u16,
        /// Scheduled set level in native units.
        set_level: u16,
    },
    /// HVAC plant status for one or more zones.
    ZoneHvacPlantStatus {
        /// Ward number.
        ward: u8,
        /// Zone-selection bitmap (bits 0 through 6).
        zones: u8,
        /// Plant type byte.
        plant_type: u8,
        /// Plant-status bitmask.
        status: u8,
        /// Plant error code.
        error: u8,
    },
    /// Humidity plant status for one or more zones.
    ZoneHumidityPlantStatus {
        /// Ward number.
        ward: u8,
        /// Zone-selection bitmap (bits 0 through 6).
        zones: u8,
        /// Plant type byte.
        plant_type: u8,
        /// Plant-status bitmask.
        status: u8,
        /// Plant error code.
        error: u8,
    },
    /// Temperature report for one or more zones.
    ZoneTemperature {
        /// Ward number.
        ward: u8,
        /// Zone-selection bitmap (bits 0 through 6).
        zones: u8,
        /// Raw two-byte fixed-point temperature bits, preserved without
        /// interpreting the sign.
        level: u16,
        /// Sensor status (0..=3).
        sensor_status: u8,
    },
    /// Humidity report for one or more zones.
    ZoneHumidity {
        /// Ward number.
        ward: u8,
        /// Zone-selection bitmap (bits 0 through 6).
        zones: u8,
        /// Raw two-byte fixed-point humidity bits.
        level: u16,
        /// Sensor status (0..=3).
        sensor_status: u8,
    },
    /// Native `set_plant_hvac_level` report (not exposed as a 3.4 command).
    PlantHvacLevel {
        /// Ward number.
        ward: u8,
        /// Zone-selection bitmap (bits 0 through 6).
        zones: u8,
        /// HVAC mode (0..=4).
        mode: u8,
        /// Whether the level uses its raw representation.
        raw_level: bool,
        /// Whether setback control is enabled.
        setback_enabled: bool,
        /// Whether guard-limit control is enabled.
        guard_enabled: bool,
        /// Whether the auxiliary level is active.
        use_aux_level: bool,
        /// Plant type byte.
        plant_type: u8,
        /// One-byte plant output level.
        level: u8,
        /// Auxiliary level byte.
        aux_level: u8,
    },
    /// Native `set_plant_humidity_level` report (not exposed as a 3.4 command).
    PlantHumidityLevel {
        /// Ward number.
        ward: u8,
        /// Zone-selection bitmap (bits 0 through 6).
        zones: u8,
        /// Humidity mode (0..=3).
        mode: u8,
        /// Whether the level uses its raw representation.
        raw_level: bool,
        /// Whether setback control is enabled.
        setback_enabled: bool,
        /// Whether guard-limit control is enabled.
        guard_enabled: bool,
        /// Whether the auxiliary level is active.
        use_aux_level: bool,
        /// Plant type byte.
        plant_type: u8,
        /// One-byte plant output level.
        level: u8,
        /// Auxiliary level byte.
        aux_level: u8,
    },
}

/// One decoded AIRCON SAL, either a maintained command or a device report.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum AirconSal {
    /// Command/event opcode exposed by native C-Gate's AIRCON family.
    Command(AirconCommand),
    /// Status/report opcode recognized by native C-Gate.
    Status(AirconStatus),
}

impl AirconCommand {
    /// Native opcode for this command.
    pub fn opcode(&self) -> u8 {
        match self {
            Self::WardOff { .. } => 0x01,
            Self::Refresh { .. } => 0x21,
            Self::ZoneHvacMode { .. } => 0x2f,
            Self::ZoneHumidityMode { .. } => 0x47,
            Self::HvacUpperGuardLimit { .. } => 0x55,
            Self::HvacLowerGuardLimit { .. } => 0x5d,
            Self::HvacSetbackLimit { .. } => 0x65,
            Self::HumidityUpperGuardLimit { .. } => 0x6d,
            Self::HumidityLowerGuardLimit { .. } => 0x75,
            Self::WardOn { .. } => 0x79,
            Self::HumiditySetbackLimit { .. } => 0x7d,
        }
    }

    /// Native lower-case event name for an observed command SAL.
    pub fn event_name(&self) -> &'static str {
        match self {
            Self::WardOff { .. } => "set_ward_off",
            Self::Refresh { .. } => "refresh",
            Self::ZoneHvacMode { .. } => "set_zone_hvac_mode",
            Self::ZoneHumidityMode { .. } => "set_zone_humidity_mode",
            Self::HvacUpperGuardLimit { .. } => "set_hvac_upper_guard_limit",
            Self::HvacLowerGuardLimit { .. } => "set_hvac_lower_guard_limit",
            Self::HvacSetbackLimit { .. } => "set_hvac_setback_limit",
            Self::HumidityUpperGuardLimit { .. } => "set_humidity_upper_guard_limit",
            Self::HumidityLowerGuardLimit { .. } => "set_humidity_lower_guard_limit",
            Self::WardOn { .. } => "set_ward_on",
            Self::HumiditySetbackLimit { .. } => "set_humidity_setback_limit",
        }
    }

    /// Positional event arguments after the application address.
    pub fn event_arguments(&self) -> String {
        match self {
            Self::WardOff { ward } | Self::Refresh { ward } | Self::WardOn { ward } => {
                ward.to_string()
            }
            Self::ZoneHvacMode {
                ward,
                zones,
                mode,
                raw_level,
                setback_enabled,
                guard_enabled,
                use_aux_level,
                plant_type,
                level,
                aux_level,
            }
            | Self::ZoneHumidityMode {
                ward,
                zones,
                mode,
                raw_level,
                setback_enabled,
                guard_enabled,
                use_aux_level,
                plant_type,
                level,
                aux_level,
            } => format!(
                "{ward} {} {mode} {} {} {} {} {plant_type} {level} {aux_level}",
                zone_list(*zones),
                u8::from(*raw_level),
                u8::from(*setback_enabled),
                u8::from(*guard_enabled),
                u8::from(*use_aux_level),
            ),
            Self::HvacUpperGuardLimit {
                ward,
                zones,
                limit,
                mode,
                raw_level,
            }
            | Self::HvacLowerGuardLimit {
                ward,
                zones,
                limit,
                mode,
                raw_level,
            }
            | Self::HvacSetbackLimit {
                ward,
                zones,
                limit,
                mode,
                raw_level,
            }
            | Self::HumidityUpperGuardLimit {
                ward,
                zones,
                limit,
                mode,
                raw_level,
            }
            | Self::HumidityLowerGuardLimit {
                ward,
                zones,
                limit,
                mode,
                raw_level,
            }
            | Self::HumiditySetbackLimit {
                ward,
                zones,
                limit,
                mode,
                raw_level,
            } => format!(
                "{ward} {} {limit} {mode} {}",
                zone_list(*zones),
                u8::from(*raw_level)
            ),
        }
    }

    /// Exact SAL bytes, excluding the point-to-multipoint envelope.
    pub fn encode(&self) -> Result<Vec<u8>, EncodeError> {
        match self {
            Self::WardOff { ward } | Self::Refresh { ward } | Self::WardOn { ward } => {
                Ok(vec![self.opcode(), *ward])
            }
            Self::ZoneHvacMode {
                ward,
                zones,
                mode,
                raw_level,
                setback_enabled,
                guard_enabled,
                use_aux_level,
                plant_type,
                level,
                aux_level,
            } => encode_zone(
                self.opcode(),
                *ward,
                *zones,
                *mode,
                4,
                *raw_level,
                *setback_enabled,
                *guard_enabled,
                *use_aux_level,
                *plant_type,
                *level,
                *aux_level,
            ),
            Self::ZoneHumidityMode {
                ward,
                zones,
                mode,
                raw_level,
                setback_enabled,
                guard_enabled,
                use_aux_level,
                plant_type,
                level,
                aux_level,
            } => encode_zone(
                self.opcode(),
                *ward,
                *zones,
                *mode,
                3,
                *raw_level,
                *setback_enabled,
                *guard_enabled,
                *use_aux_level,
                *plant_type,
                *level,
                *aux_level,
            ),
            Self::HvacUpperGuardLimit {
                ward,
                zones,
                limit,
                mode,
                raw_level,
            }
            | Self::HvacLowerGuardLimit {
                ward,
                zones,
                limit,
                mode,
                raw_level,
            }
            | Self::HvacSetbackLimit {
                ward,
                zones,
                limit,
                mode,
                raw_level,
            } => encode_limit(self.opcode(), *ward, *zones, *limit, *mode, 4, *raw_level),
            Self::HumidityUpperGuardLimit {
                ward,
                zones,
                limit,
                mode,
                raw_level,
            }
            | Self::HumidityLowerGuardLimit {
                ward,
                zones,
                limit,
                mode,
                raw_level,
            }
            | Self::HumiditySetbackLimit {
                ward,
                zones,
                limit,
                mode,
                raw_level,
            } => encode_limit(self.opcode(), *ward, *zones, *limit, *mode, 3, *raw_level),
        }
    }
}

impl AirconStatus {
    /// Native lower-case event name for this device report.
    pub fn event_name(&self) -> &'static str {
        match self {
            Self::HvacScheduleEntry { .. } => "hvac_schedule_entry",
            Self::HumidityScheduleEntry { .. } => "humidity_schedule_entry",
            Self::ZoneHvacPlantStatus { .. } => "zone_hvac_plant_status",
            Self::ZoneHumidityPlantStatus { .. } => "zone_humidity_plant_status",
            Self::ZoneTemperature { .. } => "zone_temperature",
            Self::ZoneHumidity { .. } => "zone_humidity",
            Self::PlantHvacLevel { .. } => "set_plant_hvac_level",
            Self::PlantHumidityLevel { .. } => "set_plant_humidity_level",
        }
    }

    /// Positional event arguments after the application address.
    pub fn event_arguments(&self) -> String {
        match self {
            Self::HvacScheduleEntry {
                ward,
                zones,
                entry,
                format,
                mode,
                raw_level,
                setback_enabled,
                guard_enabled,
                use_aux_level,
                start_time,
                set_level,
            }
            | Self::HumidityScheduleEntry {
                ward,
                zones,
                entry,
                format,
                mode,
                raw_level,
                setback_enabled,
                guard_enabled,
                use_aux_level,
                start_time,
                set_level,
            } => format!(
                "{ward} {} {entry} {format} {mode} {} {} {} {} {start_time} {set_level}",
                zone_list(*zones),
                u8::from(*raw_level),
                u8::from(*setback_enabled),
                u8::from(*guard_enabled),
                u8::from(*use_aux_level),
            ),
            Self::ZoneHvacPlantStatus {
                ward,
                zones,
                plant_type,
                status,
                error,
            }
            | Self::ZoneHumidityPlantStatus {
                ward,
                zones,
                plant_type,
                status,
                error,
            } => format!("{ward} {} {plant_type} {status} {error}", zone_list(*zones)),
            Self::ZoneTemperature {
                ward,
                zones,
                level,
                sensor_status,
            }
            | Self::ZoneHumidity {
                ward,
                zones,
                level,
                sensor_status,
            } => format!("{ward} {} {level} {sensor_status}", zone_list(*zones)),
            Self::PlantHvacLevel {
                ward,
                zones,
                mode,
                raw_level,
                setback_enabled,
                guard_enabled,
                use_aux_level,
                plant_type,
                level,
                aux_level,
            }
            | Self::PlantHumidityLevel {
                ward,
                zones,
                mode,
                raw_level,
                setback_enabled,
                guard_enabled,
                use_aux_level,
                plant_type,
                level,
                aux_level,
            } => format!(
                "{ward} {} {mode} {} {} {} {} {plant_type} {level} {aux_level}",
                zone_list(*zones),
                u8::from(*raw_level),
                u8::from(*setback_enabled),
                u8::from(*guard_enabled),
                u8::from(*use_aux_level),
            ),
        }
    }

    /// Exact SAL bytes, excluding the point-to-multipoint envelope.
    pub fn encode(&self) -> Result<Vec<u8>, EncodeError> {
        match self {
            Self::HvacScheduleEntry {
                ward,
                zones,
                entry,
                format,
                mode,
                raw_level,
                setback_enabled,
                guard_enabled,
                use_aux_level,
                start_time,
                set_level,
            }
            | Self::HumidityScheduleEntry {
                ward,
                zones,
                entry,
                format,
                mode,
                raw_level,
                setback_enabled,
                guard_enabled,
                use_aux_level,
                start_time,
                set_level,
            } => {
                let humidity = matches!(self, Self::HumidityScheduleEntry { .. });
                validate_common(*zones, *mode, if humidity { 3 } else { 4 })?;
                if !(1..=7).contains(format) {
                    return Err(EncodeError::new("AIRCON schedule format is out of range"));
                }
                let [start_high, start_low] = start_time.to_be_bytes();
                let [level_high, level_low] = set_level.to_be_bytes();
                Ok(vec![
                    if humidity { 0xa9 } else { 0x89 },
                    *ward,
                    *zones,
                    *entry,
                    *format,
                    mode_byte(
                        *mode,
                        *raw_level,
                        *setback_enabled,
                        *guard_enabled,
                        *use_aux_level,
                    ),
                    start_high,
                    start_low,
                    level_high,
                    level_low,
                ])
            }
            Self::ZoneHvacPlantStatus {
                ward,
                zones,
                plant_type,
                status,
                error,
            }
            | Self::ZoneHumidityPlantStatus {
                ward,
                zones,
                plant_type,
                status,
                error,
            } => {
                validate_zones(*zones)?;
                Ok(vec![
                    if matches!(self, Self::ZoneHumidityPlantStatus { .. }) {
                        0x0d
                    } else {
                        0x05
                    },
                    *ward,
                    *zones,
                    *plant_type,
                    *status,
                    *error,
                ])
            }
            Self::ZoneTemperature {
                ward,
                zones,
                level,
                sensor_status,
            }
            | Self::ZoneHumidity {
                ward,
                zones,
                level,
                sensor_status,
            } => {
                validate_zones(*zones)?;
                if *sensor_status > 3 {
                    return Err(EncodeError::new("AIRCON sensor status is out of range"));
                }
                let [high, low] = level.to_be_bytes();
                Ok(vec![
                    if matches!(self, Self::ZoneHumidity { .. }) {
                        0x1d
                    } else {
                        0x15
                    },
                    *ward,
                    *zones,
                    high,
                    low,
                    *sensor_status,
                ])
            }
            Self::PlantHvacLevel {
                ward,
                zones,
                mode,
                raw_level,
                setback_enabled,
                guard_enabled,
                use_aux_level,
                plant_type,
                level,
                aux_level,
            }
            | Self::PlantHumidityLevel {
                ward,
                zones,
                mode,
                raw_level,
                setback_enabled,
                guard_enabled,
                use_aux_level,
                plant_type,
                level,
                aux_level,
            } => {
                let humidity = matches!(self, Self::PlantHumidityLevel { .. });
                validate_common(*zones, *mode, if humidity { 3 } else { 4 })?;
                Ok(vec![
                    if humidity { 0x4e } else { 0x36 },
                    *ward,
                    *zones,
                    mode_byte(
                        *mode,
                        *raw_level,
                        *setback_enabled,
                        *guard_enabled,
                        *use_aux_level,
                    ),
                    *plant_type,
                    *level,
                    *aux_level,
                ])
            }
        }
    }
}

fn zone_list(zones: u8) -> String {
    let selected = (0..=6)
        .filter(|zone| zones & (1 << zone) != 0)
        .map(|zone| zone.to_string())
        .collect::<Vec<_>>();
    if selected.is_empty() {
        "-1".to_string()
    } else {
        selected.join(",")
    }
}

#[allow(clippy::too_many_arguments)]
fn encode_zone(
    opcode: u8,
    ward: u8,
    zones: u8,
    mode: u8,
    max_mode: u8,
    raw_level: bool,
    setback_enabled: bool,
    guard_enabled: bool,
    use_aux_level: bool,
    plant_type: u8,
    level: u16,
    aux_level: u8,
) -> Result<Vec<u8>, EncodeError> {
    validate_common(zones, mode, max_mode)?;
    let mode = mode_byte(
        mode,
        raw_level,
        setback_enabled,
        guard_enabled,
        use_aux_level,
    );
    let [high, low] = level.to_be_bytes();
    Ok(vec![
        opcode, ward, zones, mode, plant_type, high, low, aux_level,
    ])
}

fn encode_limit(
    opcode: u8,
    ward: u8,
    zones: u8,
    limit: u16,
    mode: u8,
    max_mode: u8,
    raw_level: bool,
) -> Result<Vec<u8>, EncodeError> {
    validate_common(zones, mode, max_mode)?;
    let [high, low] = limit.to_be_bytes();
    Ok(vec![
        opcode,
        ward,
        zones,
        high,
        low,
        mode_byte(mode, raw_level, false, false, false),
    ])
}

fn validate_common(zones: u8, mode: u8, max_mode: u8) -> Result<(), EncodeError> {
    validate_zones(zones)?;
    if mode > max_mode {
        return Err(EncodeError::new("AIRCON plant mode is out of range"));
    }
    Ok(())
}

fn validate_zones(zones: u8) -> Result<(), EncodeError> {
    if zones & 0x80 != 0 {
        return Err(EncodeError::new(
            "AIRCON zone bitmap contains reserved bit 7",
        ));
    }
    Ok(())
}

fn mode_byte(
    mode: u8,
    raw_level: bool,
    setback_enabled: bool,
    guard_enabled: bool,
    use_aux_level: bool,
) -> u8 {
    mode | u8::from(raw_level) << 3
        | u8::from(setback_enabled) << 4
        | u8::from(guard_enabled) << 5
        | u8::from(use_aux_level) << 6
}

/// Decode one or more exact AIRCON commands or device reports.
///
/// The status opcodes and extended schedule-entry framing are evidenced by
/// the C-Gate 3.4 manual and its owned decoder. Unknown opcodes and malformed
/// fields fail closed instead of being labelled as HVAC state.
pub fn decode_sals(data: &[u8]) -> Result<Vec<AirconSal>, DecodeError> {
    let mut messages = Vec::new();
    let mut offset = 0;
    while offset < data.len() {
        let opcode = data[offset];
        let length = match opcode {
            0x01 | 0x21 | 0x79 => 2,
            0x05 | 0x0d | 0x15 | 0x1d => 6,
            0x36 | 0x4e => 7,
            0x2f | 0x47 => 8,
            0x55 | 0x5d | 0x65 | 0x6d | 0x75 | 0x7d => 6,
            0x89 | 0xa9 => 10,
            _ => {
                return Err(DecodeError::new(format!(
                    "unsupported AIRCON SAL 0x{opcode:02x}"
                )))
            }
        };
        let end = offset + length;
        let bytes = data
            .get(offset..end)
            .ok_or_else(|| DecodeError::new("truncated AIRCON SAL"))?;
        let message = match opcode {
            0x05 => AirconSal::Status(decode_plant_status(bytes, false)?),
            0x0d => AirconSal::Status(decode_plant_status(bytes, true)?),
            0x15 => AirconSal::Status(decode_measurement(bytes, false)?),
            0x1d => AirconSal::Status(decode_measurement(bytes, true)?),
            0x36 => AirconSal::Status(decode_plant_level(bytes, false)?),
            0x4e => AirconSal::Status(decode_plant_level(bytes, true)?),
            0x89 => AirconSal::Status(decode_schedule(bytes, false)?),
            0xa9 => AirconSal::Status(decode_schedule(bytes, true)?),
            _ => AirconSal::Command(
                decode_commands(bytes)?
                    .pop()
                    .expect("one complete command was decoded"),
            ),
        };
        messages.push(message);
        offset = end;
    }
    Ok(messages)
}

/// Decode one or more exact maintained AIRCON commands.
pub fn decode_commands(data: &[u8]) -> Result<Vec<AirconCommand>, DecodeError> {
    let mut commands = Vec::new();
    let mut offset = 0;
    while offset < data.len() {
        let opcode = data[offset];
        let length = match opcode {
            0x01 | 0x21 | 0x79 => 2,
            0x2f | 0x47 => 8,
            0x55 | 0x5d | 0x65 | 0x6d | 0x75 | 0x7d => 6,
            _ => {
                return Err(DecodeError::new(format!(
                    "unsupported AIRCON command 0x{opcode:02x}"
                )))
            }
        };
        let end = offset + length;
        let bytes = data
            .get(offset..end)
            .ok_or_else(|| DecodeError::new("truncated AIRCON command"))?;
        let command = match opcode {
            0x01 => AirconCommand::WardOff { ward: bytes[1] },
            0x21 => AirconCommand::Refresh { ward: bytes[1] },
            0x79 => AirconCommand::WardOn { ward: bytes[1] },
            0x2f => decode_zone(bytes, false)?,
            0x47 => decode_zone(bytes, true)?,
            0x55 => decode_limit(bytes, 0)?,
            0x5d => decode_limit(bytes, 1)?,
            0x65 => decode_limit(bytes, 2)?,
            0x6d => decode_limit(bytes, 3)?,
            0x75 => decode_limit(bytes, 4)?,
            0x7d => decode_limit(bytes, 5)?,
            _ => unreachable!(),
        };
        commands.push(command);
        offset = end;
    }
    Ok(commands)
}

fn decode_plant_status(bytes: &[u8], humidity: bool) -> Result<AirconStatus, DecodeError> {
    validate_decoded_zones(bytes[2])?;
    let fields = (bytes[1], bytes[2], bytes[3], bytes[4], bytes[5]);
    Ok(if humidity {
        AirconStatus::ZoneHumidityPlantStatus {
            ward: fields.0,
            zones: fields.1,
            plant_type: fields.2,
            status: fields.3,
            error: fields.4,
        }
    } else {
        AirconStatus::ZoneHvacPlantStatus {
            ward: fields.0,
            zones: fields.1,
            plant_type: fields.2,
            status: fields.3,
            error: fields.4,
        }
    })
}

fn decode_measurement(bytes: &[u8], humidity: bool) -> Result<AirconStatus, DecodeError> {
    validate_decoded_zones(bytes[2])?;
    if bytes[5] > 3 {
        return Err(DecodeError::new("AIRCON sensor status is out of range"));
    }
    let fields = (
        bytes[1],
        bytes[2],
        u16::from_be_bytes([bytes[3], bytes[4]]),
        bytes[5],
    );
    Ok(if humidity {
        AirconStatus::ZoneHumidity {
            ward: fields.0,
            zones: fields.1,
            level: fields.2,
            sensor_status: fields.3,
        }
    } else {
        AirconStatus::ZoneTemperature {
            ward: fields.0,
            zones: fields.1,
            level: fields.2,
            sensor_status: fields.3,
        }
    })
}

fn decode_plant_level(bytes: &[u8], humidity: bool) -> Result<AirconStatus, DecodeError> {
    let flags = bytes[3];
    let mode = flags & 7;
    validate_decoded(bytes[2], mode, if humidity { 3 } else { 4 }, flags)?;
    let fields = (
        bytes[1],
        bytes[2],
        mode,
        flags & 8 != 0,
        flags & 16 != 0,
        flags & 32 != 0,
        flags & 64 != 0,
        bytes[4],
        bytes[5],
        bytes[6],
    );
    Ok(if humidity {
        AirconStatus::PlantHumidityLevel {
            ward: fields.0,
            zones: fields.1,
            mode: fields.2,
            raw_level: fields.3,
            setback_enabled: fields.4,
            guard_enabled: fields.5,
            use_aux_level: fields.6,
            plant_type: fields.7,
            level: fields.8,
            aux_level: fields.9,
        }
    } else {
        AirconStatus::PlantHvacLevel {
            ward: fields.0,
            zones: fields.1,
            mode: fields.2,
            raw_level: fields.3,
            setback_enabled: fields.4,
            guard_enabled: fields.5,
            use_aux_level: fields.6,
            plant_type: fields.7,
            level: fields.8,
            aux_level: fields.9,
        }
    })
}

fn decode_schedule(bytes: &[u8], humidity: bool) -> Result<AirconStatus, DecodeError> {
    let flags = bytes[5];
    let mode = flags & 7;
    validate_decoded(bytes[2], mode, if humidity { 3 } else { 4 }, flags)?;
    if !(1..=7).contains(&bytes[4]) {
        return Err(DecodeError::new("AIRCON schedule format is out of range"));
    }
    let fields = (
        bytes[1],
        bytes[2],
        bytes[3],
        bytes[4],
        mode,
        flags & 8 != 0,
        flags & 16 != 0,
        flags & 32 != 0,
        flags & 64 != 0,
        u16::from_be_bytes([bytes[6], bytes[7]]),
        u16::from_be_bytes([bytes[8], bytes[9]]),
    );
    Ok(if humidity {
        AirconStatus::HumidityScheduleEntry {
            ward: fields.0,
            zones: fields.1,
            entry: fields.2,
            format: fields.3,
            mode: fields.4,
            raw_level: fields.5,
            setback_enabled: fields.6,
            guard_enabled: fields.7,
            use_aux_level: fields.8,
            start_time: fields.9,
            set_level: fields.10,
        }
    } else {
        AirconStatus::HvacScheduleEntry {
            ward: fields.0,
            zones: fields.1,
            entry: fields.2,
            format: fields.3,
            mode: fields.4,
            raw_level: fields.5,
            setback_enabled: fields.6,
            guard_enabled: fields.7,
            use_aux_level: fields.8,
            start_time: fields.9,
            set_level: fields.10,
        }
    })
}

fn decode_zone(bytes: &[u8], humidity: bool) -> Result<AirconCommand, DecodeError> {
    let flags = bytes[3];
    let mode = flags & 7;
    validate_decoded(bytes[2], mode, if humidity { 3 } else { 4 }, flags)?;
    let fields = (
        bytes[1],
        bytes[2],
        mode,
        flags & 8 != 0,
        flags & 16 != 0,
        flags & 32 != 0,
        flags & 64 != 0,
        bytes[4],
        u16::from_be_bytes([bytes[5], bytes[6]]),
        bytes[7],
    );
    Ok(if humidity {
        AirconCommand::ZoneHumidityMode {
            ward: fields.0,
            zones: fields.1,
            mode: fields.2,
            raw_level: fields.3,
            setback_enabled: fields.4,
            guard_enabled: fields.5,
            use_aux_level: fields.6,
            plant_type: fields.7,
            level: fields.8,
            aux_level: fields.9,
        }
    } else {
        AirconCommand::ZoneHvacMode {
            ward: fields.0,
            zones: fields.1,
            mode: fields.2,
            raw_level: fields.3,
            setback_enabled: fields.4,
            guard_enabled: fields.5,
            use_aux_level: fields.6,
            plant_type: fields.7,
            level: fields.8,
            aux_level: fields.9,
        }
    })
}

fn decode_limit(bytes: &[u8], kind: u8) -> Result<AirconCommand, DecodeError> {
    let flags = bytes[5];
    let mode = flags & 7;
    let humidity = kind >= 3;
    validate_decoded(bytes[2], mode, if humidity { 3 } else { 4 }, flags)?;
    if flags & 0x70 != 0 {
        return Err(DecodeError::new(
            "AIRCON limit command contains reserved mode flags",
        ));
    }
    let ward = bytes[1];
    let zones = bytes[2];
    let limit = u16::from_be_bytes([bytes[3], bytes[4]]);
    let raw_level = flags & 8 != 0;
    Ok(match kind {
        0 => AirconCommand::HvacUpperGuardLimit {
            ward,
            zones,
            limit,
            mode,
            raw_level,
        },
        1 => AirconCommand::HvacLowerGuardLimit {
            ward,
            zones,
            limit,
            mode,
            raw_level,
        },
        2 => AirconCommand::HvacSetbackLimit {
            ward,
            zones,
            limit,
            mode,
            raw_level,
        },
        3 => AirconCommand::HumidityUpperGuardLimit {
            ward,
            zones,
            limit,
            mode,
            raw_level,
        },
        4 => AirconCommand::HumidityLowerGuardLimit {
            ward,
            zones,
            limit,
            mode,
            raw_level,
        },
        5 => AirconCommand::HumiditySetbackLimit {
            ward,
            zones,
            limit,
            mode,
            raw_level,
        },
        _ => unreachable!(),
    })
}

fn validate_decoded(zones: u8, mode: u8, max_mode: u8, flags: u8) -> Result<(), DecodeError> {
    validate_decoded_zones(zones)?;
    if mode > max_mode {
        return Err(DecodeError::new("AIRCON plant mode is out of range"));
    }
    if flags & 0x80 != 0 {
        return Err(DecodeError::new("AIRCON mode byte contains reserved bit 7"));
    }
    Ok(())
}

fn validate_decoded_zones(zones: u8) -> Result<(), DecodeError> {
    if zones & 0x80 != 0 {
        return Err(DecodeError::new(
            "AIRCON zone bitmap contains reserved bit 7",
        ));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn native_cgate_captures_round_trip() {
        let captures = [
            "0101",
            "2101",
            "7901",
            "2F010753FF001740",
            "4701074302002840",
            "550106001B03",
            "5D0107001203",
            "650107000203",
            "6D0106004603",
            "750107001403",
            "7D0118000F01",
        ];
        for capture in captures {
            let bytes = hex::decode(capture).unwrap();
            let commands = decode_commands(&bytes).unwrap();
            assert_eq!(commands.len(), 1);
            assert_eq!(commands[0].encode().unwrap(), bytes, "{capture}");
        }
    }

    #[test]
    fn documented_device_reports_round_trip_and_mix_with_commands() {
        // Schedule and status values come from the C-Gate 3.4 manual sample
        // events; 0x36/0x4e layouts come from the owned 3.4 decoder.
        let captures = [
            "89010700070305DC1400",
            "A9010700010302EE3333",
            "050107030100",
            "0D0106030100",
            "150107140000",
            "1D010728F500",
            "36010773FF40FF",
            "4E010773024064",
        ];
        for capture in captures {
            let bytes = hex::decode(capture).unwrap();
            let messages = decode_sals(&bytes).unwrap();
            assert_eq!(messages.len(), 1);
            let AirconSal::Status(status) = &messages[0] else {
                panic!("expected status for {capture}");
            };
            assert_eq!(status.encode().unwrap(), bytes, "{capture}");
        }

        let bytes = hex::decode("2101050107030100150107140000").unwrap();
        assert!(matches!(
            decode_sals(&bytes).unwrap().as_slice(),
            [
                AirconSal::Command(AirconCommand::Refresh { ward: 1 }),
                AirconSal::Status(AirconStatus::ZoneHvacPlantStatus { .. }),
                AirconSal::Status(AirconStatus::ZoneTemperature { .. })
            ]
        ));

        // Opcode 0xa9 shares the generic dynamic-label prefix. Application
        // dispatch must keep it in the AIRCON decoder.
        let dispatched = crate::sal::decode_sals(
            crate::common::APP_AIRCON,
            &hex::decode("A9010700010302EE3333").unwrap(),
        )
        .unwrap();
        assert!(matches!(
            dispatched.as_slice(),
            [crate::sal::Sal::AirconStatus(
                AirconStatus::HumidityScheduleEntry { .. }
            )]
        ));
    }

    #[test]
    fn malformed_commands_fail_closed() {
        for payload in [
            &[0x21][..],
            &[0x00, 1][..],
            &[0x2f, 1, 0x80, 0, 0, 0, 0, 0][..],
            &[0x47, 1, 1, 4, 0, 0, 0, 0][..],
            &[0x55, 1, 1, 0, 0, 0x10][..],
        ] {
            assert!(decode_commands(payload).is_err(), "{payload:02x?}");
        }
        for payload in [
            &[0x05, 1, 0x80, 0, 0, 0][..],
            &[0x15, 1, 1, 0, 0, 4][..],
            &[0xa9, 1, 1, 0, 0, 0, 0, 0, 0, 0][..],
            &[0xa9, 1, 1][..],
        ] {
            assert!(decode_sals(payload).is_err(), "{payload:02x?}");
        }
    }
}
