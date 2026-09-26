//! Stable packet-to-JSON conversion used by CLI output and golden-vector tests.

use crate::cal::Cal;
use crate::packet::{Meta, Packet};
use crate::report::StatusReport;
use crate::sal::aircon::{AirconCommand, AirconStatus};
use crate::sal::audio::{AudioAddress, AudioCommand, AudioEvent};
use crate::sal::measurement::MeasurementData;
use crate::sal::mediatransport::MediaTransportMessage;
use crate::sal::security::{SecurityArmMode, SecurityCommand, SecurityEvent};
use crate::sal::telephony::{
    DialFailure, OffHookReason, TelephonyCommand, TelephonyDirection, TelephonyEvent,
};
use crate::sal::Sal;
use serde_json::{json, Map, Value};

// ---------------------------------------------------------------- to_json

/// Canonical JSON for one SAL.
pub fn sal_to_json(s: &Sal) -> Value {
    match s {
        Sal::Aircon(command) => aircon_to_json(command),
        Sal::AirconStatus(status) => aircon_status_to_json(status),
        Sal::AudioCommand(command) => audio_command_to_json(command),
        Sal::AudioEvent(event) => audio_event_to_json(event),
        Sal::SecurityCommand(command) => security_command_to_json(command),
        Sal::SecurityEvent(event) => security_event_to_json(event),
        Sal::MeasurementData(measurement) => json!({
            "sal":"measurement_data",
            "device":measurement.device,
            "channel":measurement.channel,
            "value":measurement.value,
            "multiplier":measurement.multiplier,
            "units":measurement.units
        }),
        Sal::MediaTransport(message) => mediatransport_to_json(message),
        Sal::TelephonyCommand(command) => telephony_command_to_json(command),
        Sal::TelephonyEvent(event) => telephony_event_to_json(event),
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

fn telephony_command_to_json(command: &TelephonyCommand) -> Value {
    match command {
        TelephonyCommand::ClearDiversion => {
            json!({"sal":"telephony", "command":"clear_diversion"})
        }
        TelephonyCommand::Divert {
            number,
            declared_length,
        } => json!({"sal":"telephony", "command":"divert",
                    "number_hex":hex::encode(number), "declared_length":declared_length}),
        TelephonyCommand::IsolateSecondaryOutlet { isolated } => {
            json!({"sal":"telephony", "command":"isolate_secondary_outlet",
                   "mode":if *isolated { "isolate" } else { "normal" }})
        }
        TelephonyCommand::RecallLastNumberRequest { direction } => {
            json!({"sal":"telephony", "command":"recall_last_number_request",
                   "direction":direction.name()})
        }
        TelephonyCommand::RejectIncomingCall => {
            json!({"sal":"telephony", "command":"reject_incoming_call"})
        }
    }
}

fn telephony_event_to_json(event: &TelephonyEvent) -> Value {
    let mut value = json!({"sal":"telephony_event", "event":event.event_name()});
    let object = value.as_object_mut().expect("object");
    match event {
        TelephonyEvent::LineOnHook
        | TelephonyEvent::DialInFailure
        | TelephonyEvent::InternetConnectionRequestMade => {}
        TelephonyEvent::LineOffHook {
            direction,
            reason,
            number,
        } => {
            object.insert("direction".into(), json!(direction.name()));
            object.insert("reason".into(), json!(reason.name()));
            object.insert("number_hex".into(), json!(hex::encode(number)));
        }
        TelephonyEvent::DialOutFailure { reason } => {
            object.insert("reason".into(), json!(reason.name()));
        }
        TelephonyEvent::Ringing { qualifier, number } => {
            object.insert("qualifier".into(), json!(qualifier));
            object.insert("number_hex".into(), json!(hex::encode(number)));
        }
        TelephonyEvent::LastNumber { direction, number } => {
            object.insert("direction".into(), json!(direction.name()));
            object.insert("number_hex".into(), json!(hex::encode(number)));
        }
    }
    value
}

fn insert_audio_address(object: &mut Map<String, Value>, address: AudioAddress) {
    match address {
        AudioAddress::Zone {
            multiplexer,
            zone,
            function,
        } => {
            object.insert("multiplexer".into(), json!(multiplexer));
            object.insert("zone".into(), json!(zone));
            object.insert("function".into(), json!(function));
        }
        AudioAddress::Function(function) => {
            object.insert("multiplexer".into(), json!("Z"));
            object.insert("function".into(), json!(function));
        }
    }
}

fn audio_command_to_json(command: &AudioCommand) -> Value {
    let mut value = json!({"sal":"audio", "command":command.event_name()});
    let object = value.as_object_mut().expect("object");
    match command {
        AudioCommand::CurrentFeed { address, gain } => {
            insert_audio_address(object, *address);
            object.insert("gain".into(), json!(gain));
        }
        AudioCommand::Dynamic1 { address }
        | AudioCommand::Dynamic2 { address }
        | AudioCommand::NextFeed { address }
        | AudioCommand::NextLanguage { address }
        | AudioCommand::Off { address }
        | AudioCommand::On { address }
        | AudioCommand::OutputErrorCode { address }
        | AudioCommand::PreviousFeed { address }
        | AudioCommand::RequestCurrentFeed { address }
        | AudioCommand::TerminateRamp { address }
        | AudioCommand::ZoneDescriptorRequest { address }
        | AudioCommand::ZoneFeedLabelRequest { address } => insert_audio_address(object, *address),
        AudioCommand::HighPriority {
            multiplexer,
            level,
            feed,
        } => {
            object.insert("multiplexer".into(), json!(multiplexer));
            object.insert("level".into(), json!(level));
            object.insert("feed".into(), json!(feed));
        }
        AudioCommand::Mute { address, mode } => {
            insert_audio_address(object, *address);
            object.insert("mode".into(), json!(mode));
        }
        AudioCommand::OutputCommonControl { control } => {
            object.insert("control".into(), json!(control));
        }
        AudioCommand::OutputDeviceStatusRequest { parameter } => {
            object.insert("parameter".into(), json!(parameter));
        }
        AudioCommand::Ramp {
            address,
            level,
            rate,
        } => {
            insert_audio_address(object, *address);
            object.insert("level".into(), json!(level));
            object.insert("rate".into(), json!(rate));
        }
        AudioCommand::SetFeed { address, option } => {
            insert_audio_address(object, *address);
            object.insert("option".into(), json!(option));
        }
    }
    value
}

fn audio_event_to_json(event: &AudioEvent) -> Value {
    let mut value = json!({"sal":"audio_event", "event":event.event_name()});
    let object = value.as_object_mut().expect("object");
    match event {
        AudioEvent::Label {
            address,
            options,
            language,
            bytes,
        } => {
            insert_audio_address(object, *address);
            object.insert("options".into(), json!(options));
            object.insert("language".into(), json!(language));
            object.insert("bytes_hex".into(), json!(hex::encode(bytes)));
        }
        AudioEvent::LoadIcon {
            address,
            options,
            bytes,
        } => {
            insert_audio_address(object, *address);
            object.insert("options".into(), json!(options));
            object.insert("bytes_hex".into(), json!(hex::encode(bytes)));
        }
    }
    value
}

fn mediatransport_to_json(message: &MediaTransportMessage) -> Value {
    use MediaTransportMessage as M;
    match message {
        M::Stop { group } => json!({"sal":"mediatransport", "command":"stop", "group":group}),
        M::Play { group } => json!({"sal":"mediatransport", "command":"play", "group":group}),
        M::Pause { group, operation } => {
            json!({"sal":"mediatransport", "command":"pause", "group":group, "operation":operation})
        }
        M::SetCategory { group, category } => {
            json!({"sal":"mediatransport", "command":"set_category", "group":group, "category":category})
        }
        M::SetSelection { group, selection } => {
            json!({"sal":"mediatransport", "command":"set_selection", "group":group, "selection":selection})
        }
        M::SetTrack { group, track } => {
            json!({"sal":"mediatransport", "command":"set_track", "group":group, "track":track})
        }
        M::Shuffle { group, operation } => {
            json!({"sal":"mediatransport", "command":"shuffle", "group":group, "operation":operation})
        }
        M::Repeat { group, operation } => {
            json!({"sal":"mediatransport", "command":"repeat", "group":group, "operation":operation})
        }
        M::NextCategory { group, operation } => {
            json!({"sal":"mediatransport", "command":"next_category", "group":group, "operation":operation})
        }
        M::NextSelection { group, operation } => {
            json!({"sal":"mediatransport", "command":"next_selection", "group":group, "operation":operation})
        }
        M::NextTrack { group, operation } => {
            json!({"sal":"mediatransport", "command":"next_track", "group":group, "operation":operation})
        }
        M::Forward { group, operation } => {
            json!({"sal":"mediatransport", "command":"forward", "group":group, "operation":operation})
        }
        M::Rewind { group, operation } => {
            json!({"sal":"mediatransport", "command":"rewind", "group":group, "operation":operation})
        }
        M::SourcePower { group, operation } => {
            json!({"sal":"mediatransport", "command":"source_power", "group":group, "operation":operation})
        }
        M::TotalTracks { group, tracks } => {
            json!({"sal":"mediatransport", "command":"total_tracks", "group":group, "tracks":tracks})
        }
        M::StatusRequest { group } => {
            json!({"sal":"mediatransport", "command":"status_request", "group":group})
        }
        M::Enumerate {
            group,
            enumeration_type,
            start,
        } => {
            json!({"sal":"mediatransport", "command":"enumerate", "group":group, "enumeration_type":enumeration_type, "start":start})
        }
        M::EnumerationSize {
            group,
            enumeration_type,
            start,
            size,
        } => {
            json!({"sal":"mediatransport", "command":"enumeration_size", "group":group, "enumeration_type":enumeration_type, "start":start, "size":size})
        }
        M::TrackName {
            group,
            wni,
            total,
            index,
            text,
        } => media_name_json("track_name", *group, *wni, *total, *index, text),
        M::SelectionName {
            group,
            wni,
            total,
            index,
            text,
        } => media_name_json("selection_name", *group, *wni, *total, *index, text),
        M::CategoryName {
            group,
            wni,
            total,
            index,
            text,
        } => media_name_json("category_name", *group, *wni, *total, *index, text),
    }
}

fn media_name_json(command: &str, group: u8, wni: u8, total: u8, index: u8, text: &[u8]) -> Value {
    json!({"sal":"mediatransport", "command":command, "group":group,
        "wni":wni, "total":total, "index":index, "text_hex":hex::encode(text)})
}

fn security_command_to_json(command: &SecurityCommand) -> Value {
    match command {
        SecurityCommand::StatusRequest { report } => {
            json!({"sal":"security", "command":"status_request", "report":report})
        }
        SecurityCommand::Arm { mode } => {
            json!({"sal":"security", "command":"arm", "mode":mode.name()})
        }
        SecurityCommand::Tamper { raised } => {
            json!({"sal":"security", "command":"tamper", "raised":raised})
        }
        SecurityCommand::RaiseAlarm => json!({"sal":"security", "command":"raise_alarm"}),
        SecurityCommand::EmulateKeypad { key } => {
            json!({"sal":"security", "command":"emulate_keypad", "key":key})
        }
        SecurityCommand::DisplayMessage { message } => {
            json!({"sal":"security", "command":"display_message", "message_hex":hex::encode(message)})
        }
        SecurityCommand::RequestZoneName { zone } => {
            json!({"sal":"security", "command":"request_zone_name", "zone":zone})
        }
    }
}

fn security_event_to_json(event: &SecurityEvent) -> Value {
    let mut value = json!({"sal":"security_event", "event":event.event_name()});
    let object = value.as_object_mut().expect("object");
    match event {
        SecurityEvent::SystemArm { state } => {
            object.insert("state".into(), json!(state));
        }
        SecurityEvent::Alarm { active }
        | SecurityEvent::Tamper { active }
        | SecurityEvent::Panic { active }
        | SecurityEvent::BatteryCharging { active } => {
            object.insert("active".into(), json!(active));
        }
        SecurityEvent::LowBattery { detected } => {
            object.insert("detected".into(), json!(detected));
        }
        SecurityEvent::ZoneUnsealed { zone }
        | SecurityEvent::ZoneSealed { zone }
        | SecurityEvent::ZoneOpen { zone }
        | SecurityEvent::ZoneShort { zone }
        | SecurityEvent::ZoneIsolated { zone }
        | SecurityEvent::ArmNotReady { zone } => {
            object.insert("zone".into(), json!(zone));
        }
        SecurityEvent::ZoneName { zone, name } => {
            object.insert("zone".into(), json!(zone));
            object.insert("name_hex".into(), json!(hex::encode(name)));
        }
        SecurityEvent::StatusReport1 {
            arm_state,
            tamper,
            panic,
            zones,
        } => {
            object.insert("arm_state".into(), json!(arm_state));
            object.insert("tamper".into(), json!(tamper));
            object.insert("panic".into(), json!(panic));
            object.insert("zones".into(), json!(zones));
        }
        SecurityEvent::StatusReport2 { zones } => {
            object.insert("zones".into(), json!(zones));
        }
        SecurityEvent::PasswordEntryStatus { status } => {
            object.insert("status".into(), json!(status));
        }
        SecurityEvent::Mains { restored } => {
            object.insert("restored".into(), json!(restored));
        }
        SecurityEvent::CurrentAlarmType { alarm_type } => {
            object.insert("alarm_type".into(), json!(alarm_type));
        }
        SecurityEvent::LineCutAlarm { raised }
        | SecurityEvent::ArmFailed { raised }
        | SecurityEvent::FireAlarm { raised }
        | SecurityEvent::GasAlarm { raised }
        | SecurityEvent::OtherAlarm { raised } => {
            object.insert("raised".into(), json!(raised));
        }
        SecurityEvent::ExitDelayStarted
        | SecurityEvent::EntryDelayStarted
        | SecurityEvent::ArmReady => {}
    }
    value
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
        Cal::ExtendedStatusRequest {
            group,
            operation,
            status,
        } => json!({"cal": "extended_status_request", "group": group,
                    "operation": operation, "status": status}),
        Cal::Cancel { group, operation } => {
            json!({"cal": "cancel", "group": group, "operation": operation})
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

fn get_i16(d: &Value, k: &str) -> Result<i16, JErr> {
    d.get(k)
        .and_then(Value::as_i64)
        .and_then(|value| i16::try_from(value).ok())
        .ok_or_else(|| format!("missing/invalid field {k}"))
}

fn get_i8(d: &Value, k: &str) -> Result<i8, JErr> {
    d.get(k)
        .and_then(Value::as_i64)
        .and_then(|value| i8::try_from(value).ok())
        .ok_or_else(|| format!("missing/invalid field {k}"))
}

fn get_u32(d: &Value, k: &str) -> Result<u32, JErr> {
    d.get(k)
        .and_then(Value::as_u64)
        .and_then(|value| u32::try_from(value).ok())
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
        "audio" => audio_command_from_json(d).map(Sal::AudioCommand),
        "audio_event" => audio_event_from_json(d).map(Sal::AudioEvent),
        "security" => security_command_from_json(d).map(Sal::SecurityCommand),
        "security_event" => security_event_from_json(d).map(Sal::SecurityEvent),
        "measurement_data" => Ok(Sal::MeasurementData(MeasurementData {
            device: get_u8(d, "device")?,
            channel: get_u8(d, "channel")?,
            value: get_i16(d, "value")?,
            multiplier: get_i8(d, "multiplier")?,
            units: get_u8(d, "units")?,
        })),
        "mediatransport" => mediatransport_from_json(d).map(Sal::MediaTransport),
        "telephony" => telephony_command_from_json(d).map(Sal::TelephonyCommand),
        "telephony_event" => telephony_event_from_json(d).map(Sal::TelephonyEvent),
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

fn telephony_direction_from_json(d: &Value) -> Result<TelephonyDirection, JErr> {
    match get_str(d, "direction")? {
        "out" => Ok(TelephonyDirection::Out),
        "in" => Ok(TelephonyDirection::In),
        direction => Err(format!("unhandled Telephony direction: {direction}")),
    }
}

fn telephony_command_from_json(d: &Value) -> Result<TelephonyCommand, JErr> {
    Ok(match get_str(d, "command")? {
        "clear_diversion" => TelephonyCommand::ClearDiversion,
        "divert" => TelephonyCommand::Divert {
            number: get_hex(d, "number_hex")?,
            declared_length: get_u8(d, "declared_length")?,
        },
        "isolate_secondary_outlet" => TelephonyCommand::IsolateSecondaryOutlet {
            isolated: match get_str(d, "mode")? {
                "normal" => false,
                "isolate" => true,
                mode => return Err(format!("unhandled Telephony isolation mode: {mode}")),
            },
        },
        "recall_last_number_request" => TelephonyCommand::RecallLastNumberRequest {
            direction: telephony_direction_from_json(d)?,
        },
        "reject_incoming_call" => TelephonyCommand::RejectIncomingCall,
        command => return Err(format!("unhandled Telephony command: {command}")),
    })
}

fn telephony_event_from_json(d: &Value) -> Result<TelephonyEvent, JErr> {
    let number = || get_hex(d, "number_hex");
    Ok(match get_str(d, "event")? {
        "line_on_hook" => TelephonyEvent::LineOnHook,
        "line_off_hook" => TelephonyEvent::LineOffHook {
            direction: telephony_direction_from_json(d)?,
            reason: match get_str(d, "reason")? {
                "voice" => OffHookReason::Voice,
                "data" => OffHookReason::Data,
                "other" => OffHookReason::Other,
                reason => return Err(format!("unhandled Telephony off-hook reason: {reason}")),
            },
            number: number()?,
        },
        "dial_out_failure" => TelephonyEvent::DialOutFailure {
            reason: match get_str(d, "reason")? {
                "no_dialtone" => DialFailure::NoDialtone,
                "no_answer" => DialFailure::NoAnswer,
                "no_ack_prompt" => DialFailure::NoAckPrompt,
                "unobtainable" => DialFailure::Unobtainable,
                "busy" => DialFailure::Busy,
                reason => return Err(format!("unhandled Telephony dial failure: {reason}")),
            },
        },
        "dial_in_failure" => TelephonyEvent::DialInFailure,
        "ringing" => TelephonyEvent::Ringing {
            qualifier: match d.get("qualifier") {
                None | Some(Value::Null) => None,
                Some(_) => Some(get_u8(d, "qualifier")?),
            },
            number: number()?,
        },
        "last_number" => TelephonyEvent::LastNumber {
            direction: telephony_direction_from_json(d)?,
            number: number()?,
        },
        "internet_connection_request_made" => TelephonyEvent::InternetConnectionRequestMade,
        event => return Err(format!("unhandled Telephony event: {event}")),
    })
}

fn audio_address_from_json(d: &Value) -> Result<AudioAddress, JErr> {
    if d.get("multiplexer").and_then(Value::as_str) == Some("Z") {
        return Ok(AudioAddress::Function(get_u8(d, "function")?));
    }
    AudioAddress::zone(
        get_u8(d, "multiplexer")?,
        get_u8(d, "zone")?,
        get_u8(d, "function")?,
    )
    .map_err(|error| error.to_string())
}

fn get_hex(d: &Value, key: &str) -> Result<Vec<u8>, JErr> {
    hex::decode(get_str(d, key)?).map_err(|error| format!("invalid field {key}: {error}"))
}

fn audio_command_from_json(d: &Value) -> Result<AudioCommand, JErr> {
    let address = || audio_address_from_json(d);
    Ok(match get_str(d, "command")? {
        "current_feed" => AudioCommand::CurrentFeed {
            address: address()?,
            gain: get_u8(d, "gain")?,
        },
        "dynamic_1" => AudioCommand::Dynamic1 {
            address: address()?,
        },
        "dynamic_2" => AudioCommand::Dynamic2 {
            address: address()?,
        },
        "high_priority" => AudioCommand::HighPriority {
            multiplexer: get_u8(d, "multiplexer")?,
            level: get_u8(d, "level")?,
            feed: get_u8(d, "feed")?,
        },
        "mute" => AudioCommand::Mute {
            address: address()?,
            mode: get_u8(d, "mode")?,
        },
        "next_feed" => AudioCommand::NextFeed {
            address: address()?,
        },
        "next_language" => AudioCommand::NextLanguage {
            address: address()?,
        },
        "off" => AudioCommand::Off {
            address: address()?,
        },
        "on" => AudioCommand::On {
            address: address()?,
        },
        "output_common_control" => AudioCommand::OutputCommonControl {
            control: get_u8(d, "control")?,
        },
        "output_device_status_request" => AudioCommand::OutputDeviceStatusRequest {
            parameter: get_u8(d, "parameter")?,
        },
        "output_error_code" => AudioCommand::OutputErrorCode {
            address: address()?,
        },
        "previous_feed" => AudioCommand::PreviousFeed {
            address: address()?,
        },
        "ramp" => AudioCommand::Ramp {
            address: address()?,
            level: get_u8(d, "level")?,
            rate: get_u8(d, "rate")?,
        },
        "request_current_feed" => AudioCommand::RequestCurrentFeed {
            address: address()?,
        },
        "set_feed" => AudioCommand::SetFeed {
            address: address()?,
            option: get_u8(d, "option")?,
        },
        "terminateramp" => AudioCommand::TerminateRamp {
            address: address()?,
        },
        "zone_descriptor_request" => AudioCommand::ZoneDescriptorRequest {
            address: address()?,
        },
        "zone_feed_label_request" => AudioCommand::ZoneFeedLabelRequest {
            address: address()?,
        },
        command => return Err(format!("unhandled Audio command: {command}")),
    })
}

fn audio_event_from_json(d: &Value) -> Result<AudioEvent, JErr> {
    Ok(match get_str(d, "event")? {
        "label" => AudioEvent::Label {
            address: audio_address_from_json(d)?,
            options: get_u8(d, "options")?,
            language: get_u8(d, "language")?,
            bytes: get_hex(d, "bytes_hex")?,
        },
        "load_icon" => AudioEvent::LoadIcon {
            address: audio_address_from_json(d)?,
            options: get_u8(d, "options")?,
            bytes: get_hex(d, "bytes_hex")?,
        },
        event => return Err(format!("unhandled Audio event: {event}")),
    })
}

fn mediatransport_from_json(d: &Value) -> Result<MediaTransportMessage, JErr> {
    use MediaTransportMessage as M;
    let group = get_u8(d, "group")?;
    let operation = || get_u8(d, "operation");
    let name = |kind: &str| -> Result<M, JErr> {
        let text = hex::decode(get_str(d, "text_hex")?).map_err(|e| e.to_string())?;
        let wni = get_u8(d, "wni")?;
        let total = get_u8(d, "total")?;
        let index = get_u8(d, "index")?;
        Ok(match kind {
            "track_name" => M::TrackName {
                group,
                wni,
                total,
                index,
                text,
            },
            "selection_name" => M::SelectionName {
                group,
                wni,
                total,
                index,
                text,
            },
            "category_name" => M::CategoryName {
                group,
                wni,
                total,
                index,
                text,
            },
            _ => unreachable!(),
        })
    };
    Ok(match get_str(d, "command")? {
        "stop" => M::Stop { group },
        "play" => M::Play { group },
        "pause" => M::Pause {
            group,
            operation: operation()?,
        },
        "set_category" => M::SetCategory {
            group,
            category: get_u8(d, "category")?,
        },
        "set_selection" => M::SetSelection {
            group,
            selection: get_u16(d, "selection")?,
        },
        "set_track" => M::SetTrack {
            group,
            track: get_u32(d, "track")?,
        },
        "shuffle" => M::Shuffle {
            group,
            operation: operation()?,
        },
        "repeat" => M::Repeat {
            group,
            operation: operation()?,
        },
        "next_category" => M::NextCategory {
            group,
            operation: operation()?,
        },
        "next_selection" => M::NextSelection {
            group,
            operation: operation()?,
        },
        "next_track" => M::NextTrack {
            group,
            operation: operation()?,
        },
        "forward" => M::Forward {
            group,
            operation: operation()?,
        },
        "rewind" => M::Rewind {
            group,
            operation: operation()?,
        },
        "source_power" => M::SourcePower {
            group,
            operation: operation()?,
        },
        "total_tracks" => M::TotalTracks {
            group,
            tracks: get_u32(d, "tracks")?,
        },
        "status_request" => M::StatusRequest { group },
        "enumerate" => M::Enumerate {
            group,
            enumeration_type: get_u8(d, "enumeration_type")?,
            start: get_u8(d, "start")?,
        },
        "enumeration_size" => M::EnumerationSize {
            group,
            enumeration_type: get_u8(d, "enumeration_type")?,
            start: get_u8(d, "start")?,
            size: get_u8(d, "size")?,
        },
        "track_name" => return name("track_name"),
        "selection_name" => return name("selection_name"),
        "category_name" => return name("category_name"),
        command => return Err(format!("unhandled Media Transport command: {command}")),
    })
}

fn security_command_from_json(d: &Value) -> Result<SecurityCommand, JErr> {
    Ok(match get_str(d, "command")? {
        "status_request" => SecurityCommand::StatusRequest {
            report: get_u8(d, "report")?,
        },
        "arm" => SecurityCommand::Arm {
            mode: match get_str(d, "mode")? {
                "away" => SecurityArmMode::Away,
                "night" => SecurityArmMode::Night,
                "day" => SecurityArmMode::Day,
                "vacation" => SecurityArmMode::Vacation,
                "highest" => SecurityArmMode::Highest,
                mode => return Err(format!("unhandled Security arm mode: {mode}")),
            },
        },
        "tamper" => SecurityCommand::Tamper {
            raised: get_bool(d, "raised")?,
        },
        "raise_alarm" => SecurityCommand::RaiseAlarm,
        "emulate_keypad" => SecurityCommand::EmulateKeypad {
            key: get_u8(d, "key")?,
        },
        "display_message" => SecurityCommand::DisplayMessage {
            message: hex::decode(get_str(d, "message_hex")?).map_err(|e| e.to_string())?,
        },
        "request_zone_name" => SecurityCommand::RequestZoneName {
            zone: get_u8(d, "zone")?,
        },
        command => return Err(format!("unhandled Security command: {command}")),
    })
}

fn security_event_from_json(d: &Value) -> Result<SecurityEvent, JErr> {
    let zones = || -> Result<Vec<u8>, JErr> {
        d.get("zones")
            .and_then(Value::as_array)
            .ok_or_else(|| "missing/invalid field zones".to_owned())?
            .iter()
            .map(|value| {
                value
                    .as_u64()
                    .and_then(|v| u8::try_from(v).ok())
                    .ok_or_else(|| "invalid zone state".to_owned())
            })
            .collect()
    };
    Ok(match get_str(d, "event")? {
        "system_arm" => SecurityEvent::SystemArm {
            state: get_u8(d, "state")?,
        },
        "exit_delay_started" => SecurityEvent::ExitDelayStarted,
        "entry_delay_started" => SecurityEvent::EntryDelayStarted,
        "alarm_on" => SecurityEvent::Alarm {
            active: security_named_bool(d, "active", true)?,
        },
        "alarm_off" => SecurityEvent::Alarm {
            active: security_named_bool(d, "active", false)?,
        },
        "tamper_on" => SecurityEvent::Tamper {
            active: security_named_bool(d, "active", true)?,
        },
        "tamper_off" => SecurityEvent::Tamper {
            active: security_named_bool(d, "active", false)?,
        },
        "panic_activated" => SecurityEvent::Panic {
            active: security_named_bool(d, "active", true)?,
        },
        "panic_cleared" => SecurityEvent::Panic {
            active: security_named_bool(d, "active", false)?,
        },
        "zone_unsealed" => SecurityEvent::ZoneUnsealed {
            zone: get_u8(d, "zone")?,
        },
        "zone_sealed" => SecurityEvent::ZoneSealed {
            zone: get_u8(d, "zone")?,
        },
        "zone_open" => SecurityEvent::ZoneOpen {
            zone: get_u8(d, "zone")?,
        },
        "zone_short" => SecurityEvent::ZoneShort {
            zone: get_u8(d, "zone")?,
        },
        "zone_isolated" => SecurityEvent::ZoneIsolated {
            zone: get_u8(d, "zone")?,
        },
        "low_battery_detected" => SecurityEvent::LowBattery {
            detected: security_named_bool(d, "detected", true)?,
        },
        "low_battery_corrected" => SecurityEvent::LowBattery {
            detected: security_named_bool(d, "detected", false)?,
        },
        "battery_charging" => SecurityEvent::BatteryCharging {
            active: get_bool(d, "active")?,
        },
        "zone_name" => SecurityEvent::ZoneName {
            zone: get_u8(d, "zone")?,
            name: hex::decode(get_str(d, "name_hex")?).map_err(|e| e.to_string())?,
        },
        "status_report_1" => SecurityEvent::StatusReport1 {
            arm_state: get_u8(d, "arm_state")?,
            tamper: get_bool(d, "tamper")?,
            panic: get_bool(d, "panic")?,
            zones: zones()?,
        },
        "status_report_2" => SecurityEvent::StatusReport2 { zones: zones()? },
        "password_entry_status" => SecurityEvent::PasswordEntryStatus {
            status: get_u8(d, "status")?,
        },
        "mains_failure" => SecurityEvent::Mains {
            restored: security_named_bool(d, "restored", false)?,
        },
        "mains_restored" => SecurityEvent::Mains {
            restored: security_named_bool(d, "restored", true)?,
        },
        "arm_ready" => SecurityEvent::ArmReady,
        "arm_not_ready" => SecurityEvent::ArmNotReady {
            zone: get_u8(d, "zone")?,
        },
        "current_alarm_type" => SecurityEvent::CurrentAlarmType {
            alarm_type: get_u8(d, "alarm_type")?,
        },
        "line_cut_alarm" => SecurityEvent::LineCutAlarm {
            raised: get_bool(d, "raised")?,
        },
        "arm_failed" => SecurityEvent::ArmFailed {
            raised: get_bool(d, "raised")?,
        },
        "fire_alarm" => SecurityEvent::FireAlarm {
            raised: get_bool(d, "raised")?,
        },
        "gas_alarm" => SecurityEvent::GasAlarm {
            raised: get_bool(d, "raised")?,
        },
        "other_alarm" => SecurityEvent::OtherAlarm {
            raised: get_bool(d, "raised")?,
        },
        event => return Err(format!("unhandled Security event: {event}")),
    })
}

fn security_named_bool(d: &Value, field: &str, expected: bool) -> Result<bool, JErr> {
    let actual = get_bool(d, field)?;
    if actual == expected {
        Ok(actual)
    } else {
        Err(format!("Security event name conflicts with field {field}"))
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
        "extended_status_request" => Ok(Cal::ExtendedStatusRequest {
            group: get_u8(d, "group")?,
            operation: get_u8(d, "operation")?,
            status: get_u8(d, "status")?,
        }),
        "cancel" => Ok(Cal::Cancel {
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

    #[test]
    fn security_event_names_and_boolean_fields_must_agree() {
        let alarm = json!({
            "sal": "security_event",
            "event": "alarm_on",
            "active": true
        });
        let sal = sal_from_json(&alarm).unwrap();
        assert_eq!(sal_to_json(&sal), alarm);

        let mut contradictory = alarm;
        contradictory["active"] = json!(false);
        assert!(sal_from_json(&contradictory).is_err());
    }

    #[test]
    fn telephony_command_and_event_json_preserve_native_fields() {
        for value in [
            json!({
                "sal": "telephony",
                "command": "divert",
                "number_hex": "ffff",
                "declared_length": 1
            }),
            json!({
                "sal": "telephony_event",
                "event": "line_off_hook",
                "direction": "out",
                "reason": "data",
                "number_hex": "3132"
            }),
            json!({
                "sal": "telephony_event",
                "event": "ringing",
                "qualifier": 0,
                "number_hex": "3132"
            }),
        ] {
            let sal = sal_from_json(&value).unwrap();
            assert_eq!(sal_to_json(&sal), value);
        }
    }
}
