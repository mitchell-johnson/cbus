//! Stable packet-to-JSON conversion used by CLI output and golden-vector tests.

use crate::cal::Cal;
use crate::packet::{Meta, Packet};
use crate::report::StatusReport;
use crate::sal::aircon::{AirconCommand, AirconStatus};
use crate::sal::Sal;
use serde_json::{json, Map, Value};

// ---------------------------------------------------------------- to_json

/// Canonical JSON for one SAL.
pub fn sal_to_json(s: &Sal) -> Value {
    match s {
        Sal::Aircon(command) => aircon_to_json(command),
        Sal::AirconStatus(status) => aircon_status_to_json(status),
        Sal::LightingRamp {
            application,
            group_address,
            duration,
            level,
        } => json!({"sal": "lighting_ramp", "application": application,
                    "group_address": group_address,
                    "duration": duration, "level": level}),
        Sal::LightingOn {
            application,
            group_address,
        } => json!({"sal": "lighting_on", "application": application,
                    "group_address": group_address}),
        Sal::LightingOff {
            application,
            group_address,
        } => json!({"sal": "lighting_off", "application": application,
                    "group_address": group_address}),
        Sal::LightingTerminateRamp {
            application,
            group_address,
        } => json!({"sal": "lighting_terminate_ramp",
                    "application": application,
                    "group_address": group_address}),
        Sal::TriggerEvent {
            group_address,
            action_selector,
        } => json!({"sal": "trigger_event", "group_address": group_address,
                    "action_selector": action_selector}),
        Sal::TriggerIndicatorKill { group_address } => {
            json!({"sal": "trigger_indicator_kill", "group_address": group_address})
        }
        Sal::TriggerMin { group_address } => {
            json!({"sal": "trigger_min", "group_address": group_address})
        }
        Sal::TriggerMax { group_address } => {
            json!({"sal": "trigger_max", "group_address": group_address})
        }
        Sal::ClockRequest => json!({"sal": "clock_request"}),
        Sal::ClockUpdateDate { year, month, day } => {
            json!({"sal": "clock_update_date", "year": year,
                   "month": month, "day": day})
        }
        Sal::ClockUpdateTime {
            hour,
            minute,
            second,
        } => json!({"sal": "clock_update_time", "hour": hour,
                    "minute": minute, "second": second}),
        Sal::TemperatureBroadcast {
            group_address,
            temperature,
        } => json!({"sal": "temperature_broadcast",
                    "group_address": group_address,
                    "temperature": temperature}),
        Sal::EnableSetNetworkVariable { variable, value } => {
            json!({"sal": "enable_set_network_variable",
                   "variable": variable, "value": value})
        }
        Sal::StatusRequest {
            level_request,
            group_address,
            child_application,
        } => json!({"sal": "status_request",
                    "level_request": level_request,
                    "group_address": group_address,
                    "child_application": child_application}),
        Sal::InstallMmiRequest => json!({"sal": "install_mmi_request"}),
        Sal::DynamicLabel {
            application,
            payload,
        } => json!({"sal": "dynamic_label", "application": application,
                    "payload_hex": hex::encode(payload)}),
    }
}

fn aircon_status_to_json(status: &AirconStatus) -> Value {
    match status {
        AirconStatus::HvacScheduleEntry {
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
        | AirconStatus::HumidityScheduleEntry {
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
        } => json!({"sal":"aircon_status",
            "event": if matches!(status, AirconStatus::HumidityScheduleEntry { .. }) {
                "humidity_schedule_entry"
            } else { "hvac_schedule_entry" },
            "ward":ward, "zones":zones, "entry":entry, "format":format,
            "mode":mode, "raw_level":raw_level,
            "setback_enabled":setback_enabled, "guard_enabled":guard_enabled,
            "use_aux_level":use_aux_level, "start_time":start_time,
            "set_level":set_level}),
        AirconStatus::ZoneHvacPlantStatus {
            ward,
            zones,
            plant_type,
            status: plant_status,
            error,
        }
        | AirconStatus::ZoneHumidityPlantStatus {
            ward,
            zones,
            plant_type,
            status: plant_status,
            error,
        } => json!({"sal":"aircon_status",
            "event": if matches!(status, AirconStatus::ZoneHumidityPlantStatus { .. }) {
                "zone_humidity_plant_status"
            } else { "zone_hvac_plant_status" },
            "ward":ward, "zones":zones, "plant_type":plant_type,
            "status":plant_status, "error":error}),
        AirconStatus::ZoneTemperature {
            ward,
            zones,
            level,
            sensor_status,
        }
        | AirconStatus::ZoneHumidity {
            ward,
            zones,
            level,
            sensor_status,
        } => json!({"sal":"aircon_status",
            "event": if matches!(status, AirconStatus::ZoneHumidity { .. }) {
                "zone_humidity"
            } else { "zone_temperature" },
            "ward":ward, "zones":zones, "level":level,
            "sensor_status":sensor_status}),
        AirconStatus::PlantHvacLevel {
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
        | AirconStatus::PlantHumidityLevel {
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
        } => json!({"sal":"aircon_status",
            "event": if matches!(status, AirconStatus::PlantHumidityLevel { .. }) {
                "set_plant_humidity_level"
            } else { "set_plant_hvac_level" },
            "ward":ward, "zones":zones, "mode":mode, "raw_level":raw_level,
            "setback_enabled":setback_enabled, "guard_enabled":guard_enabled,
            "use_aux_level":use_aux_level, "plant_type":plant_type,
            "level":level, "aux_level":aux_level}),
    }
}

fn aircon_to_json(command: &AirconCommand) -> Value {
    match command {
        AirconCommand::WardOff { ward } => {
            json!({"sal":"aircon", "command":"set_ward_off", "ward":ward})
        }
        AirconCommand::Refresh { ward } => {
            json!({"sal":"aircon", "command":"refresh", "ward":ward})
        }
        AirconCommand::WardOn { ward } => {
            json!({"sal":"aircon", "command":"set_ward_on", "ward":ward})
        }
        AirconCommand::ZoneHvacMode {
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
        } => json!({"sal":"aircon", "command":"set_zone_hvac_mode",
            "ward":ward, "zones":zones, "mode":mode, "raw_level":raw_level,
            "setback_enabled":setback_enabled, "guard_enabled":guard_enabled,
            "use_aux_level":use_aux_level, "plant_type":plant_type,
            "level":level, "aux_level":aux_level}),
        AirconCommand::ZoneHumidityMode {
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
        } => json!({"sal":"aircon", "command":"set_zone_humidity_mode",
            "ward":ward, "zones":zones, "mode":mode, "raw_level":raw_level,
            "setback_enabled":setback_enabled, "guard_enabled":guard_enabled,
            "use_aux_level":use_aux_level, "plant_type":plant_type,
            "level":level, "aux_level":aux_level}),
        AirconCommand::HvacUpperGuardLimit {
            ward,
            zones,
            limit,
            mode,
            raw_level,
        } => aircon_limit_json(
            "set_hvac_upper_guard_limit",
            *ward,
            *zones,
            *limit,
            *mode,
            *raw_level,
        ),
        AirconCommand::HvacLowerGuardLimit {
            ward,
            zones,
            limit,
            mode,
            raw_level,
        } => aircon_limit_json(
            "set_hvac_lower_guard_limit",
            *ward,
            *zones,
            *limit,
            *mode,
            *raw_level,
        ),
        AirconCommand::HvacSetbackLimit {
            ward,
            zones,
            limit,
            mode,
            raw_level,
        } => aircon_limit_json(
            "set_hvac_setback_limit",
            *ward,
            *zones,
            *limit,
            *mode,
            *raw_level,
        ),
        AirconCommand::HumidityUpperGuardLimit {
            ward,
            zones,
            limit,
            mode,
            raw_level,
        } => aircon_limit_json(
            "set_humidity_upper_guard_limit",
            *ward,
            *zones,
            *limit,
            *mode,
            *raw_level,
        ),
        AirconCommand::HumidityLowerGuardLimit {
            ward,
            zones,
            limit,
            mode,
            raw_level,
        } => aircon_limit_json(
            "set_humidity_lower_guard_limit",
            *ward,
            *zones,
            *limit,
            *mode,
            *raw_level,
        ),
        AirconCommand::HumiditySetbackLimit {
            ward,
            zones,
            limit,
            mode,
            raw_level,
        } => aircon_limit_json(
            "set_humidity_setback_limit",
            *ward,
            *zones,
            *limit,
            *mode,
            *raw_level,
        ),
    }
}

fn aircon_limit_json(
    command: &str,
    ward: u8,
    zones: u8,
    limit: u16,
    mode: u8,
    raw_level: bool,
) -> Value {
    json!({"sal":"aircon", "command":command, "ward":ward, "zones":zones,
        "limit":limit, "mode":mode, "raw_level":raw_level})
}

/// Canonical JSON for a status report.
pub fn report_to_json(r: &StatusReport) -> Value {
    match r {
        StatusReport::Binary(states) => {
            json!({"report": "binary", "group_states": states})
        }
        StatusReport::Level(levels) => json!({"report": "level", "levels": levels}),
    }
}

/// Canonical JSON for one CAL.
pub fn cal_to_json(c: &Cal) -> Value {
    match c {
        Cal::Write { parameter, data } => {
            json!({"cal": "write", "parameter": parameter, "data_hex": hex::encode(data)})
        }
        Cal::Ack { parameter, data } => {
            json!({"cal": "ack", "parameter": parameter, "data_hex": hex::encode(data)})
        }
        Cal::Unlock { parameter } => json!({"cal": "unlock", "parameter": parameter}),
        Cal::Readdress {
            destination,
            challenge,
        } => json!({"cal": "readdress", "destination": destination,
                    "challenge": challenge}),
        Cal::ReaddressNak => json!({"cal": "readdress_nak"}),
        Cal::Nak { parameter, data } => {
            json!({"cal": "nak", "parameter": parameter, "data_hex": hex::encode(data)})
        }
        Cal::Execute {
            group,
            operation,
            data,
        } => json!({"cal": "execute", "group": group, "operation": operation,
                    "data_hex": hex::encode(data)}),
        Cal::Poll { group, operation } => {
            json!({"cal": "poll", "group": group, "operation": operation})
        }
        Cal::ExtendedReply {
            group,
            operation,
            status,
            data,
        } => json!({"cal": "extended_reply", "group": group, "operation": operation,
                    "status": status, "data_hex": hex::encode(data)}),
        Cal::SetPage { page } => json!({"cal": "set_page", "page": page}),
        Cal::Identify { attribute } => json!({"cal": "identify", "attribute": attribute}),
        Cal::Recall { param, count } => {
            json!({"cal": "recall", "param": param, "count": count})
        }
        Cal::PagedRecall { page, param, count } => {
            json!({"cal": "paged_recall", "page": page, "param": param, "count": count})
        }
        Cal::Reply { parameter, data } => json!({"cal": "reply", "parameter": parameter,
                    "data_hex": hex::encode(data)}),
        Cal::ExtendedStatus {
            externally_initiated,
            child_application,
            block_start,
            report,
        } => json!({"cal": "extended_status",
                    "externally_initiated": externally_initiated,
                    "child_application": child_application,
                    "block_start": block_start,
                    "report": report_to_json(report)}),
    }
}

fn conf_to_json(confirmation: Option<u8>) -> Value {
    match confirmation {
        None => Value::Null,
        Some(c) => Value::String((c as char).to_string()),
    }
}

fn envelope(map: &mut Map<String, Value>, meta: &Meta) {
    map.insert("checksum".into(), json!(meta.checksum));
    map.insert("priority_class".into(), json!(meta.priority_class));
    map.insert("source_address".into(), json!(meta.source_address));
    map.insert("confirmation".into(), conf_to_json(meta.confirmation));
}

/// Canonical JSON for anything decode_packet() may return.
pub fn packet_to_json(p: Option<&Packet>) -> Value {
    let p = match p {
        None => return Value::Null,
        Some(p) => p,
    };
    match p {
        Packet::Invalid => json!({"type": "invalid"}),
        Packet::PowerOn => json!({"type": "power_on"}),
        Packet::PciError => json!({"type": "pci_error"}),
        Packet::Confirmation { code, success } => {
            json!({"type": "confirmation",
                   "code": (*code as char).to_string(), "success": success})
        }
        Packet::Reset => json!({"type": "reset"}),
        Packet::SmartConnect => json!({"type": "smart_connect"}),
        Packet::DeviceManagement {
            meta,
            parameter,
            value,
        } => {
            let mut m = Map::new();
            m.insert("type".into(), json!("device_management"));
            envelope(&mut m, meta);
            m.insert("parameter".into(), json!(parameter));
            m.insert("value".into(), json!(value));
            Value::Object(m)
        }
        Packet::PointToMultipoint {
            meta,
            application,
            sals,
        } => {
            let mut m = Map::new();
            m.insert("type".into(), json!("point_to_multipoint"));
            envelope(&mut m, meta);
            m.insert("application".into(), json!(application));
            m.insert(
                "sals".into(),
                Value::Array(sals.iter().map(sal_to_json).collect()),
            );
            Value::Object(m)
        }
        Packet::PointToPointToMultipoint {
            meta,
            bridges,
            application,
            sals,
        } => {
            let mut m = Map::new();
            m.insert("type".into(), json!("point_to_point_to_multipoint"));
            envelope(&mut m, meta);
            m.insert("bridges".into(), json!(bridges));
            m.insert("application".into(), json!(application));
            m.insert(
                "sals".into(),
                Value::Array(sals.iter().map(sal_to_json).collect()),
            );
            Value::Object(m)
        }
        Packet::StandardStatus {
            application,
            block_start,
            states,
        } => json!({"type": "standard_status", "application": application,
                   "block_start": block_start, "states": states}),
        Packet::PointToPoint {
            meta,
            unit_address,
            bridged,
            hops,
            cals,
        } => {
            let mut m = Map::new();
            m.insert("type".into(), json!("point_to_point"));
            envelope(&mut m, meta);
            m.insert("unit_address".into(), json!(unit_address));
            m.insert("bridged".into(), json!(bridged));
            m.insert("hops".into(), json!(hops));
            m.insert(
                "cals".into(),
                Value::Array(cals.iter().map(cal_to_json).collect()),
            );
            Value::Object(m)
        }
        Packet::BareCal(cal) => {
            let mut m = Map::new();
            m.insert("type".into(), json!("cal"));
            if let Value::Object(cm) = cal_to_json(cal) {
                for (k, v) in cm {
                    m.insert(k, v);
                }
            }
            Value::Object(m)
        }
    }
}

// -------------------------------------------------------------- from_json

/// Anything `packet_from_json` may build (encode.jsonl also exercises bare
/// SAL/CAL/report encoders).
#[derive(Debug, Clone, PartialEq)]
pub enum JsonObject {
    /// A full packet.
    Packet(Packet),
    /// A bare SAL (standalone encode vectors).
    Sal(Sal),
    /// A bare CAL.
    Cal(Cal),
    /// A bare status report.
    Report(StatusReport),
}

impl JsonObject {
    /// the underlying packet value.
    pub fn encode(&self) -> Result<Vec<u8>, crate::EncodeError> {
        match self {
            JsonObject::Packet(p) => p.encode(),
            JsonObject::Sal(s) => s.encode(),
            JsonObject::Cal(c) => Ok(c.encode()),
            JsonObject::Report(r) => Ok(r.encode()),
        }
    }

    /// `.encode_packet()` — only meaningful for packets.
    pub fn encode_packet(&self) -> Result<Vec<u8>, crate::EncodeError> {
        match self {
            JsonObject::Packet(p) => p.encode_packet(),
            _ => Err(crate::EncodeError::new("no encode_packet on this object")),
        }
    }
}

type JErr = String;

fn get_u8(d: &Value, k: &str) -> Result<u8, JErr> {
    d.get(k)
        .and_then(Value::as_u64)
        .and_then(|value| u8::try_from(value).ok())
        .ok_or_else(|| format!("missing/invalid field {k}"))
}

fn get_u16(d: &Value, k: &str) -> Result<u16, JErr> {
    d.get(k)
        .and_then(Value::as_u64)
        .and_then(|value| u16::try_from(value).ok())
        .ok_or_else(|| format!("missing/invalid field {k}"))
}

fn get_bool(d: &Value, k: &str) -> Result<bool, JErr> {
    d.get(k)
        .and_then(Value::as_bool)
        .ok_or_else(|| format!("missing/invalid field {k}"))
}

fn get_str<'a>(d: &'a Value, k: &str) -> Result<&'a str, JErr> {
    d.get(k)
        .and_then(Value::as_str)
        .ok_or_else(|| format!("missing/invalid field {k}"))
}

/// Build a SAL from canonical JSON.
pub fn sal_from_json(d: &Value) -> Result<Sal, JErr> {
    match get_str(d, "sal")? {
        "aircon" => aircon_from_json(d).map(Sal::Aircon),
        "aircon_status" => aircon_status_from_json(d).map(Sal::AirconStatus),
        "lighting_on" => Ok(Sal::LightingOn {
            application: get_u8(d, "application")?,
            group_address: get_u8(d, "group_address")?,
        }),
        "lighting_off" => Ok(Sal::LightingOff {
            application: get_u8(d, "application")?,
            group_address: get_u8(d, "group_address")?,
        }),
        "lighting_terminate_ramp" => Ok(Sal::LightingTerminateRamp {
            application: get_u8(d, "application")?,
            group_address: get_u8(d, "group_address")?,
        }),
        "lighting_ramp" => Ok(Sal::LightingRamp {
            application: get_u8(d, "application")?,
            group_address: get_u8(d, "group_address")?,
            duration: d
                .get("duration")
                .and_then(Value::as_u64)
                .ok_or("missing duration")? as u32,
            level: get_u8(d, "level")?,
        }),
        "trigger_event" => Ok(Sal::TriggerEvent {
            group_address: get_u8(d, "group_address")?,
            action_selector: get_u8(d, "action_selector")?,
        }),
        "trigger_indicator_kill" => Ok(Sal::TriggerIndicatorKill {
            group_address: get_u8(d, "group_address")?,
        }),
        "trigger_min" => Ok(Sal::TriggerMin {
            group_address: get_u8(d, "group_address")?,
        }),
        "trigger_max" => Ok(Sal::TriggerMax {
            group_address: get_u8(d, "group_address")?,
        }),
        "clock_request" => Ok(Sal::ClockRequest),
        "clock_update_date" => Ok(Sal::ClockUpdateDate {
            year: d
                .get("year")
                .and_then(Value::as_u64)
                .ok_or("missing year")? as u16,
            month: get_u8(d, "month")?,
            day: get_u8(d, "day")?,
        }),
        "clock_update_time" => Ok(Sal::ClockUpdateTime {
            hour: get_u8(d, "hour")?,
            minute: get_u8(d, "minute")?,
            second: get_u8(d, "second")?,
        }),
        "temperature_broadcast" => Ok(Sal::TemperatureBroadcast {
            group_address: get_u8(d, "group_address")?,
            temperature: d
                .get("temperature")
                .and_then(Value::as_f64)
                .ok_or("missing temperature")?,
        }),
        "enable_set_network_variable" => Ok(Sal::EnableSetNetworkVariable {
            variable: get_u8(d, "variable")?,
            value: get_u8(d, "value")?,
        }),
        "status_request" => Ok(Sal::StatusRequest {
            level_request: get_bool(d, "level_request")?,
            group_address: get_u8(d, "group_address")?,
            child_application: get_u8(d, "child_application")?,
        }),
        "install_mmi_request" => Ok(Sal::InstallMmiRequest),
        "dynamic_label" => Ok(Sal::DynamicLabel {
            application: get_u8(d, "application")?,
            payload: hex::decode(get_str(d, "payload_hex")?).map_err(|e| e.to_string())?,
        }),
        other => Err(format!("unhandled SAL json: {other}")),
    }
}

fn aircon_status_from_json(d: &Value) -> Result<AirconStatus, JErr> {
    let event = get_str(d, "event")?;
    let ward = get_u8(d, "ward")?;
    let zones = get_u8(d, "zones")?;
    if matches!(event, "hvac_schedule_entry" | "humidity_schedule_entry") {
        let fields = (
            get_u8(d, "entry")?,
            get_u8(d, "format")?,
            get_u8(d, "mode")?,
            get_bool(d, "raw_level")?,
            get_bool(d, "setback_enabled")?,
            get_bool(d, "guard_enabled")?,
            get_bool(d, "use_aux_level")?,
            get_u16(d, "start_time")?,
            get_u16(d, "set_level")?,
        );
        return Ok(if event == "humidity_schedule_entry" {
            AirconStatus::HumidityScheduleEntry {
                ward,
                zones,
                entry: fields.0,
                format: fields.1,
                mode: fields.2,
                raw_level: fields.3,
                setback_enabled: fields.4,
                guard_enabled: fields.5,
                use_aux_level: fields.6,
                start_time: fields.7,
                set_level: fields.8,
            }
        } else {
            AirconStatus::HvacScheduleEntry {
                ward,
                zones,
                entry: fields.0,
                format: fields.1,
                mode: fields.2,
                raw_level: fields.3,
                setback_enabled: fields.4,
                guard_enabled: fields.5,
                use_aux_level: fields.6,
                start_time: fields.7,
                set_level: fields.8,
            }
        });
    }
    if matches!(
        event,
        "zone_hvac_plant_status" | "zone_humidity_plant_status"
    ) {
        let fields = (
            get_u8(d, "plant_type")?,
            get_u8(d, "status")?,
            get_u8(d, "error")?,
        );
        return Ok(if event == "zone_humidity_plant_status" {
            AirconStatus::ZoneHumidityPlantStatus {
                ward,
                zones,
                plant_type: fields.0,
                status: fields.1,
                error: fields.2,
            }
        } else {
            AirconStatus::ZoneHvacPlantStatus {
                ward,
                zones,
                plant_type: fields.0,
                status: fields.1,
                error: fields.2,
            }
        });
    }
    if matches!(event, "zone_temperature" | "zone_humidity") {
        let level = get_u16(d, "level")?;
        let sensor_status = get_u8(d, "sensor_status")?;
        return Ok(if event == "zone_humidity" {
            AirconStatus::ZoneHumidity {
                ward,
                zones,
                level,
                sensor_status,
            }
        } else {
            AirconStatus::ZoneTemperature {
                ward,
                zones,
                level,
                sensor_status,
            }
        });
    }
    if matches!(event, "set_plant_hvac_level" | "set_plant_humidity_level") {
        let fields = (
            get_u8(d, "mode")?,
            get_bool(d, "raw_level")?,
            get_bool(d, "setback_enabled")?,
            get_bool(d, "guard_enabled")?,
            get_bool(d, "use_aux_level")?,
            get_u8(d, "plant_type")?,
            get_u8(d, "level")?,
            get_u8(d, "aux_level")?,
        );
        return Ok(if event == "set_plant_humidity_level" {
            AirconStatus::PlantHumidityLevel {
                ward,
                zones,
                mode: fields.0,
                raw_level: fields.1,
                setback_enabled: fields.2,
                guard_enabled: fields.3,
                use_aux_level: fields.4,
                plant_type: fields.5,
                level: fields.6,
                aux_level: fields.7,
            }
        } else {
            AirconStatus::PlantHvacLevel {
                ward,
                zones,
                mode: fields.0,
                raw_level: fields.1,
                setback_enabled: fields.2,
                guard_enabled: fields.3,
                use_aux_level: fields.4,
                plant_type: fields.5,
                level: fields.6,
                aux_level: fields.7,
            }
        });
    }
    Err(format!("unhandled AIRCON status json: {event}"))
}

fn aircon_from_json(d: &Value) -> Result<AirconCommand, JErr> {
    let ward = get_u8(d, "ward")?;
    let command = get_str(d, "command")?;
    if command == "refresh" {
        return Ok(AirconCommand::Refresh { ward });
    }
    if command == "set_ward_off" {
        return Ok(AirconCommand::WardOff { ward });
    }
    if command == "set_ward_on" {
        return Ok(AirconCommand::WardOn { ward });
    }
    let zones = get_u8(d, "zones")?;
    let mode = get_u8(d, "mode")?;
    let raw_level = get_bool(d, "raw_level")?;
    if matches!(command, "set_zone_hvac_mode" | "set_zone_humidity_mode") {
        let fields = (
            get_bool(d, "setback_enabled")?,
            get_bool(d, "guard_enabled")?,
            get_bool(d, "use_aux_level")?,
            get_u8(d, "plant_type")?,
            get_u16(d, "level")?,
            get_u8(d, "aux_level")?,
        );
        return Ok(if command == "set_zone_hvac_mode" {
            AirconCommand::ZoneHvacMode {
                ward,
                zones,
                mode,
                raw_level,
                setback_enabled: fields.0,
                guard_enabled: fields.1,
                use_aux_level: fields.2,
                plant_type: fields.3,
                level: fields.4,
                aux_level: fields.5,
            }
        } else {
            AirconCommand::ZoneHumidityMode {
                ward,
                zones,
                mode,
                raw_level,
                setback_enabled: fields.0,
                guard_enabled: fields.1,
                use_aux_level: fields.2,
                plant_type: fields.3,
                level: fields.4,
                aux_level: fields.5,
            }
        });
    }
    let limit = get_u16(d, "limit")?;
    Ok(match command {
        "set_hvac_upper_guard_limit" => AirconCommand::HvacUpperGuardLimit {
            ward,
            zones,
            limit,
            mode,
            raw_level,
        },
        "set_hvac_lower_guard_limit" => AirconCommand::HvacLowerGuardLimit {
            ward,
            zones,
            limit,
            mode,
            raw_level,
        },
        "set_hvac_setback_limit" => AirconCommand::HvacSetbackLimit {
            ward,
            zones,
            limit,
            mode,
            raw_level,
        },
        "set_humidity_upper_guard_limit" => AirconCommand::HumidityUpperGuardLimit {
            ward,
            zones,
            limit,
            mode,
            raw_level,
        },
        "set_humidity_lower_guard_limit" => AirconCommand::HumidityLowerGuardLimit {
            ward,
            zones,
            limit,
            mode,
            raw_level,
        },
        "set_humidity_setback_limit" => AirconCommand::HumiditySetbackLimit {
            ward,
            zones,
            limit,
            mode,
            raw_level,
        },
        other => return Err(format!("unhandled AIRCON command json: {other}")),
    })
}

/// Build a status report from canonical JSON.
pub fn report_from_json(d: &Value) -> Result<StatusReport, JErr> {
    match get_str(d, "report")? {
        "binary" => {
            let states = d
                .get("group_states")
                .and_then(Value::as_array)
                .ok_or("missing group_states")?
                .iter()
                .map(|v| {
                    v.as_u64()
                        .map(|x| x as u8)
                        .ok_or_else(|| "bad group state".to_string())
                })
                .collect::<Result<Vec<u8>, _>>()?;
            Ok(StatusReport::Binary(states))
        }
        "level" => {
            let levels = d
                .get("levels")
                .and_then(Value::as_array)
                .ok_or("missing levels")?
                .iter()
                .map(|v| {
                    if v.is_null() {
                        Ok(None)
                    } else {
                        v.as_u64()
                            .map(|x| Some(x as u8))
                            .ok_or_else(|| "bad level".to_string())
                    }
                })
                .collect::<Result<Vec<Option<u8>>, _>>()?;
            Ok(StatusReport::Level(levels))
        }
        other => Err(format!("unhandled report json: {other}")),
    }
}

/// Build a CAL from canonical JSON.
pub fn cal_from_json(d: &Value) -> Result<Cal, JErr> {
    match get_str(d, "cal")? {
        "write" => Ok(Cal::Write {
            parameter: get_u8(d, "parameter")?,
            data: hex::decode(get_str(d, "data_hex")?).map_err(|e| e.to_string())?,
        }),
        "ack" => Ok(Cal::Ack {
            parameter: get_u8(d, "parameter")?,
            data: hex::decode(get_str(d, "data_hex")?).map_err(|e| e.to_string())?,
        }),
        "unlock" => Ok(Cal::Unlock {
            parameter: get_u8(d, "parameter")?,
        }),
        "readdress" => Ok(Cal::Readdress {
            destination: get_u8(d, "destination")?,
            challenge: get_u8(d, "challenge")?,
        }),
        "readdress_nak" => Ok(Cal::ReaddressNak),
        "nak" => Ok(Cal::Nak {
            parameter: get_u8(d, "parameter")?,
            data: hex::decode(get_str(d, "data_hex")?).map_err(|e| e.to_string())?,
        }),
        "execute" => Ok(Cal::Execute {
            group: get_u8(d, "group")?,
            operation: get_u8(d, "operation")?,
            data: hex::decode(get_str(d, "data_hex")?).map_err(|e| e.to_string())?,
        }),
        "poll" => Ok(Cal::Poll {
            group: get_u8(d, "group")?,
            operation: get_u8(d, "operation")?,
        }),
        "extended_reply" => Ok(Cal::ExtendedReply {
            group: get_u8(d, "group")?,
            operation: get_u8(d, "operation")?,
            status: get_u8(d, "status")?,
            data: hex::decode(get_str(d, "data_hex")?).map_err(|e| e.to_string())?,
        }),
        "set_page" => Ok(Cal::SetPage {
            page: get_u8(d, "page")?,
        }),
        "identify" => Ok(Cal::Identify {
            attribute: get_u8(d, "attribute")?,
        }),
        "recall" => Ok(Cal::Recall {
            param: get_u8(d, "param")?,
            count: get_u8(d, "count")?,
        }),
        "paged_recall" => Ok(Cal::PagedRecall {
            page: get_u8(d, "page")?,
            param: get_u8(d, "param")?,
            count: get_u8(d, "count")?,
        }),
        "reply" => Ok(Cal::Reply {
            parameter: get_u8(d, "parameter")?,
            data: hex::decode(get_str(d, "data_hex")?).map_err(|e| e.to_string())?,
        }),
        "extended_status" => Ok(Cal::ExtendedStatus {
            externally_initiated: get_bool(d, "externally_initiated")?,
            child_application: get_u8(d, "child_application")?,
            block_start: get_u8(d, "block_start")?,
            report: report_from_json(d.get("report").ok_or("missing report")?)?,
        }),
        other => Err(format!("unhandled CAL json: {other}")),
    }
}

fn meta_from_json(d: &Value) -> Result<Meta, JErr> {
    let checksum = get_bool(d, "checksum")?;
    let priority_class = get_u8(d, "priority_class")?;
    let source_address = match d.get("source_address") {
        None => None,
        Some(Value::Null) => None,
        Some(v) => Some(v.as_u64().ok_or("bad source_address")? as u8),
    };
    // An empty confirmation string means no confirmation.
    let confirmation = match d.get("confirmation") {
        None => None,
        Some(Value::Null) => None,
        Some(v) => {
            let s = v.as_str().ok_or("bad confirmation")?;
            s.bytes().next()
        }
    };
    Ok(Meta {
        checksum,
        priority_class,
        source_address,
        confirmation,
    })
}

/// Construct an encodable packet from
/// canonical JSON (no invalid/bridged variants).
pub fn packet_from_json(d: &Value) -> Result<JsonObject, JErr> {
    match get_str(d, "type")? {
        "reset" => Ok(JsonObject::Packet(Packet::Reset)),
        "smart_connect" => Ok(JsonObject::Packet(Packet::SmartConnect)),
        "power_on" => Ok(JsonObject::Packet(Packet::PowerOn)),
        "pci_error" => Ok(JsonObject::Packet(Packet::PciError)),
        "confirmation" => Ok(JsonObject::Packet(Packet::Confirmation {
            code: get_str(d, "code")?
                .bytes()
                .next()
                .ok_or("empty confirmation code")?,
            success: get_bool(d, "success")?,
        })),
        "device_management" => Ok(JsonObject::Packet(Packet::DeviceManagement {
            meta: meta_from_json(d)?,
            parameter: get_u8(d, "parameter")?,
            value: get_u8(d, "value")?,
        })),
        "point_to_multipoint" => {
            let sals = d
                .get("sals")
                .and_then(Value::as_array)
                .ok_or("missing sals")?
                .iter()
                .map(sal_from_json)
                .collect::<Result<Vec<Sal>, _>>()?;
            // The packet application is derived from its SALs.
            let application = sals
                .first()
                .map(|s| s.application())
                .ok_or("PM packet with no SALs cannot be encoded")?;
            Ok(JsonObject::Packet(Packet::PointToMultipoint {
                meta: meta_from_json(d)?,
                application,
                sals,
            }))
        }
        "point_to_point_to_multipoint" => {
            let sals = d
                .get("sals")
                .and_then(Value::as_array)
                .ok_or("missing sals")?
                .iter()
                .map(sal_from_json)
                .collect::<Result<Vec<Sal>, _>>()?;
            let application = sals
                .first()
                .map(|s| s.application())
                .ok_or("PPM packet with no SALs cannot be encoded")?;
            let bridges = d
                .get("bridges")
                .and_then(Value::as_array)
                .ok_or("missing bridges")?
                .iter()
                .map(|value| {
                    value
                        .as_u64()
                        .and_then(|value| u8::try_from(value).ok())
                        .ok_or_else(|| "bad bridge address".to_string())
                })
                .collect::<Result<Vec<_>, _>>()?;
            Ok(JsonObject::Packet(Packet::PointToPointToMultipoint {
                meta: meta_from_json(d)?,
                bridges,
                application,
                sals,
            }))
        }
        "standard_status" => {
            let states = d
                .get("states")
                .and_then(Value::as_array)
                .ok_or("missing states")?
                .iter()
                .map(|value| {
                    value
                        .as_u64()
                        .and_then(|value| u8::try_from(value).ok())
                        .ok_or_else(|| "bad standard status state".to_string())
                })
                .collect::<Result<Vec<_>, _>>()?;
            Ok(JsonObject::Packet(Packet::StandardStatus {
                application: get_u8(d, "application")?,
                block_start: get_u8(d, "block_start")?,
                states,
            }))
        }
        "point_to_point" => {
            let cals = d
                .get("cals")
                .and_then(Value::as_array)
                .ok_or("missing cals")?
                .iter()
                .map(cal_from_json)
                .collect::<Result<Vec<Cal>, _>>()?;
            Ok(JsonObject::Packet(Packet::PointToPoint {
                meta: meta_from_json(d)?,
                unit_address: get_u8(d, "unit_address")?,
                bridged: d.get("bridged").and_then(Value::as_bool).unwrap_or(false),
                hops: d
                    .get("hops")
                    .and_then(Value::as_array)
                    .map(|values| {
                        values
                            .iter()
                            .map(|value| {
                                value
                                    .as_u64()
                                    .and_then(|value| u8::try_from(value).ok())
                                    .ok_or_else(|| "bad bridge hop".to_string())
                            })
                            .collect::<Result<Vec<_>, _>>()
                    })
                    .transpose()?
                    .unwrap_or_default(),
                cals,
            }))
        }
        "cal" => Ok(JsonObject::Cal(cal_from_json(d)?)),
        "sal" => Ok(JsonObject::Sal(sal_from_json(d)?)),
        "binary_report" => Ok(JsonObject::Report(report_from_json(
            &json!({"report": "binary", "group_states": d.get("group_states")}),
        )?)),
        "level_report" => Ok(JsonObject::Report(report_from_json(
            &json!({"report": "level", "levels": d.get("levels")}),
        )?)),
        other => Err(format!("unhandled packet json type: {other}")),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn roundtrip_pm() {
        let v = json!({
            "type": "point_to_multipoint", "checksum": true,
            "priority_class": 0, "source_address": null,
            "confirmation": "h", "application": 56,
            "sals": [{"sal": "lighting_on", "application": 56,
                      "group_address": 1}]});
        let obj = packet_from_json(&v).unwrap();
        if let JsonObject::Packet(p) = &obj {
            assert_eq!(packet_to_json(Some(p)), v);
        } else {
            panic!("not a packet");
        }
    }

    #[test]
    fn temperature_float() {
        let v = json!({"sal": "temperature_broadcast", "group_address": 5,
                       "temperature": 25.0});
        let s = sal_from_json(&v).unwrap();
        assert_eq!(sal_to_json(&s), v);
    }

    #[test]
    fn aircon_report_roundtrip() {
        let v = json!({
            "sal": "aircon_status",
            "event": "zone_hvac_plant_status",
            "ward": 1,
            "zones": 7,
            "plant_type": 3,
            "status": 1,
            "error": 0
        });
        let sal = sal_from_json(&v).unwrap();
        assert_eq!(sal_to_json(&sal), v);

        let mut out_of_range = v;
        out_of_range["plant_type"] = json!(256);
        assert!(sal_from_json(&out_of_range).is_err());
    }
}
