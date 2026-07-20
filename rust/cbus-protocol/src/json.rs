//! Canonical packet <-> JSON codec, mirroring
//! `rust-migration-harness/lib/pyjson.py` field-for-field.

use crate::cal::Cal;
use crate::packet::{Meta, Packet};
use crate::report::StatusReport;
use crate::sal::Sal;
use serde_json::{json, Map, Value};

// ---------------------------------------------------------------- to_json

pub fn sal_to_json(s: &Sal) -> Value {
    match s {
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
    }
}

pub fn report_to_json(r: &StatusReport) -> Value {
    match r {
        StatusReport::Binary(states) => {
            json!({"report": "binary", "group_states": states})
        }
        StatusReport::Level(levels) => json!({"report": "level", "levels": levels}),
    }
}

pub fn cal_to_json(c: &Cal) -> Value {
    match c {
        Cal::Identify { attribute } => json!({"cal": "identify", "attribute": attribute}),
        Cal::Recall { param, count } => {
            json!({"cal": "recall", "param": param, "count": count})
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
    Packet(Packet),
    Sal(Sal),
    Cal(Cal),
    Report(StatusReport),
}

impl JsonObject {
    /// `.encode()` on the underlying Python object.
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
        .map(|v| v as u8)
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

pub fn sal_from_json(d: &Value) -> Result<Sal, JErr> {
    match get_str(d, "sal")? {
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
        other => Err(format!("unhandled SAL json: {other}")),
    }
}

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

pub fn cal_from_json(d: &Value) -> Result<Cal, JErr> {
    match get_str(d, "cal")? {
        "identify" => Ok(Cal::Identify {
            attribute: get_u8(d, "attribute")?,
        }),
        "recall" => Ok(Cal::Recall {
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
    // Python: conf.encode('ascii') if conf else None (empty string -> None)
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

/// Port of `pyjson.packet_from_json`: constructs an encodable object from
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
            // Python derives the packet application from the SALs
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
                bridged: false,
                hops: vec![],
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
}
