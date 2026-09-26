//! Simple Application Language model and application dispatch.

pub mod aircon;
pub mod audio;
pub mod clock;
pub mod enable;
pub mod label;
pub mod lighting;
pub mod security;
pub mod status_request;
pub mod temperature;
pub mod trigger;

use crate::common::{
    duration_to_ramp_rate, APP_AIRCON, APP_AUDIO, APP_CLOCK, APP_ENABLE, APP_LIGHTING_FIRST,
    APP_LIGHTING_LAST, APP_SECURITY, APP_STATUS_REQUEST, APP_TEMPERATURE, APP_TRIGGER,
    CLOCK_ATTR_DATE, CLOCK_ATTR_TIME, CLOCK_REQUEST_REFRESH, ENABLE_SET_NETWORK_VARIABLE,
    LIGHT_OFF, LIGHT_ON, LIGHT_TERMINATE_RAMP, TEMPERATURE_BROADCAST, TRIGGER_EVENT,
    TRIGGER_INDICATOR_KILL, TRIGGER_MAX, TRIGGER_MIN,
};
use crate::{DecodeError, EncodeError};
use chrono::Datelike;

/// A Smart Application Language message.
#[derive(Debug, Clone, PartialEq)]
pub enum Sal {
    /// An Air-Conditioning application command.
    Aircon(aircon::AirconCommand),
    /// An Air-Conditioning device status/report.
    AirconStatus(aircon::AirconStatus),
    /// An Audio application command.
    AudioCommand(audio::AudioCommand),
    /// An Audio application-only event.
    AudioEvent(audio::AudioEvent),
    /// A Security application command.
    SecurityCommand(security::SecurityCommand),
    /// A Security application device event or report.
    SecurityEvent(security::SecurityEvent),
    /// Switch a lighting group on.
    LightingOn {
        /// Lighting application address (0x30..=0x5F).
        application: u8,
        /// Group address.
        group_address: u8,
    },
    /// Switch a lighting group off.
    LightingOff {
        /// Lighting application address (0x30..=0x5F).
        application: u8,
        /// Group address.
        group_address: u8,
    },
    /// Stop a ramp in progress.
    LightingTerminateRamp {
        /// Lighting application address (0x30..=0x5F).
        application: u8,
        /// Group address.
        group_address: u8,
    },
    /// Ramp a lighting group to a level.
    LightingRamp {
        /// Lighting application address (0x30..=0x5F).
        application: u8,
        /// Group address.
        group_address: u8,
        /// Requested duration in seconds (snapped to the rate table on
        /// encode; JSON keeps the original value).
        duration: u32,
        /// Target level 0..=255.
        level: u8,
    },
    /// Send an explicit Trigger Control action selector to a group.
    TriggerEvent {
        /// Trigger group address.
        group_address: u8,
        /// Action selector 0..=255.
        action_selector: u8,
    },
    /// Clear the indicators associated with a Trigger Control group.
    TriggerIndicatorKill {
        /// Trigger group address.
        group_address: u8,
    },
    /// Trigger Control compact minimum-selector command.
    TriggerMin {
        /// Trigger group address.
        group_address: u8,
    },
    /// Trigger Control compact maximum-selector command.
    TriggerMax {
        /// Trigger group address.
        group_address: u8,
    },
    /// Broadcast the network time (DST byte always 0xFF on encode).
    ClockUpdateTime {
        /// Hour 0..=23.
        hour: u8,
        /// Minute 0..=59.
        minute: u8,
        /// Second 0..=59.
        second: u8,
    },
    /// Broadcast the network date (weekday derived, Monday = 0).
    ClockUpdateDate {
        /// Year 1..=9999.
        year: u16,
        /// Month 1..=12.
        month: u8,
        /// Day of month.
        day: u8,
    },
    /// Ask for a clock update.
    ClockRequest,
    /// A temperature measurement (quarter-degree resolution).
    TemperatureBroadcast {
        /// Group address of the sensor.
        group_address: u8,
        /// Temperature in °C (`byte / 4.0`).
        temperature: f64,
    },
    /// Set an enable-control network variable.
    EnableSetNetworkVariable {
        /// Variable number.
        variable: u8,
        /// New value.
        value: u8,
    },
    /// Ask units to report group status.
    StatusRequest {
        /// Level (manchester) report rather than binary.
        level_request: bool,
        /// Block start; multiple of 0x20 (encode masks with 0xE0).
        group_address: u8,
        /// Application whose groups are being queried.
        child_application: u8,
    },
    /// Request the complete installation MMI presence map.
    InstallMmiRequest,
    /// Exact native dynamic-label SAL payload. The application is retained
    /// because label payloads are shared by lighting, Trigger, and Enable.
    DynamicLabel {
        /// Target application (lighting 48..95, Trigger 202, or Enable 203).
        application: u8,
        /// Complete length-prefixed `0xAx` or `0xCx` SAL payload.
        payload: Vec<u8>,
    },
}

impl Sal {
    /// Application byte this SAL belongs to.
    pub fn application(&self) -> u8 {
        match self {
            Sal::Aircon(_) | Sal::AirconStatus(_) => APP_AIRCON,
            Sal::AudioCommand(_) | Sal::AudioEvent(_) => APP_AUDIO,
            Sal::SecurityCommand(_) | Sal::SecurityEvent(_) => APP_SECURITY,
            Sal::LightingOn { application, .. }
            | Sal::LightingOff { application, .. }
            | Sal::LightingTerminateRamp { application, .. }
            | Sal::LightingRamp { application, .. } => *application,
            Sal::TriggerEvent { .. }
            | Sal::TriggerIndicatorKill { .. }
            | Sal::TriggerMin { .. }
            | Sal::TriggerMax { .. } => APP_TRIGGER,
            Sal::ClockUpdateTime { .. } | Sal::ClockUpdateDate { .. } | Sal::ClockRequest => {
                APP_CLOCK
            }
            Sal::TemperatureBroadcast { .. } => APP_TEMPERATURE,
            Sal::EnableSetNetworkVariable { .. } => APP_ENABLE,
            Sal::StatusRequest { .. } | Sal::InstallMmiRequest => APP_STATUS_REQUEST,
            Sal::DynamicLabel { application, .. } => *application,
        }
    }

    /// Wire bytes of this SAL.
    pub fn encode(&self) -> Result<Vec<u8>, EncodeError> {
        match self {
            Sal::Aircon(command) => command.encode(),
            Sal::AirconStatus(status) => status.encode(),
            Sal::AudioCommand(command) => command.encode(),
            Sal::AudioEvent(event) => event.encode(),
            Sal::SecurityCommand(command) => command.encode(),
            Sal::SecurityEvent(event) => event.encode(),
            Sal::LightingOn { group_address, .. } => Ok(vec![LIGHT_ON, *group_address]),
            Sal::LightingOff { group_address, .. } => Ok(vec![LIGHT_OFF, *group_address]),
            Sal::LightingTerminateRamp { group_address, .. } => {
                Ok(vec![LIGHT_TERMINATE_RAMP, *group_address])
            }
            Sal::LightingRamp {
                group_address,
                duration,
                level,
                ..
            } => Ok(vec![
                duration_to_ramp_rate(*duration as i64),
                *group_address,
                *level,
            ]),
            Sal::TriggerEvent {
                group_address,
                action_selector,
            } => Ok(vec![TRIGGER_EVENT, *group_address, *action_selector]),
            Sal::TriggerIndicatorKill { group_address } => {
                Ok(vec![TRIGGER_INDICATOR_KILL, *group_address])
            }
            Sal::TriggerMin { group_address } => Ok(vec![TRIGGER_MIN, *group_address]),
            Sal::TriggerMax { group_address } => Ok(vec![TRIGGER_MAX, *group_address]),
            Sal::ClockUpdateTime {
                hour,
                minute,
                second,
            } => {
                // val = pack('>BBBB', h, m, s, 255); [0x08|(len+1), attr] + val
                Ok(vec![0x0d, CLOCK_ATTR_TIME, *hour, *minute, *second, 0xff])
            }
            Sal::ClockUpdateDate { year, month, day } => {
                let d = chrono::NaiveDate::from_ymd_opt(*year as i32, *month as u32, *day as u32)
                    .ok_or_else(|| EncodeError::new("invalid date"))?;
                let weekday = d.weekday().num_days_from_monday() as u8; // Monday=0
                let yb = year.to_be_bytes();
                Ok(vec![
                    0x0e,
                    CLOCK_ATTR_DATE,
                    yb[0],
                    yb[1],
                    *month,
                    *day,
                    weekday,
                ])
            }
            Sal::ClockRequest => Ok(vec![CLOCK_REQUEST_REFRESH, 0x03]),
            Sal::TemperatureBroadcast {
                group_address,
                temperature,
            } => {
                if !(0.0..=63.75).contains(temperature) {
                    return Err(EncodeError::new(format!(
                        "Temperature is out of bounds. Must be between 0.0 and \
                         63.75 celsius (got {}).",
                        temperature
                    )));
                }
                // int(temp * 4) truncates
                Ok(vec![
                    TEMPERATURE_BROADCAST,
                    *group_address,
                    (*temperature * 4.0) as u8,
                ])
            }
            Sal::EnableSetNetworkVariable { variable, value } => {
                Ok(vec![ENABLE_SET_NETWORK_VARIABLE, *variable, *value])
            }
            Sal::StatusRequest {
                level_request,
                group_address,
                child_application,
            } => {
                let ga = group_address & 0xe0;
                if *level_request {
                    Ok(vec![0x73, 0x07, *child_application, ga])
                } else {
                    Ok(vec![0x7a, *child_application, ga])
                }
            }
            Sal::InstallMmiRequest => Ok(vec![0xfa, 0xff, 0x00]),
            Sal::DynamicLabel {
                application,
                payload,
            } => {
                label::validate_payload(*application, payload)?;
                Ok(payload.clone())
            }
        }
    }
}

/// Application dispatch: decode the SAL payload of a PM packet.
/// The supported registry includes status-request (0xFF), clock (0xDF),
/// enable (0xCB), Audio (0xCD), Security (0xD0), Air-Conditioning (0xAC),
/// lighting (0x30-0x5F) and temperature (0x19) are registered; anything else
/// errors (-> Invalid packet).
pub fn decode_sals(app: u8, data: &[u8]) -> Result<Vec<Sal>, DecodeError> {
    // Extended AIRCON schedule entries use the 0xA9 opcode. Application
    // dispatch must happen before the generic dynamic-label prefix check.
    if app == APP_AIRCON {
        return aircon::decode_sals(data).map(|messages| {
            messages
                .into_iter()
                .map(|message| match message {
                    aircon::AirconSal::Command(command) => Sal::Aircon(command),
                    aircon::AirconSal::Status(status) => Sal::AirconStatus(status),
                })
                .collect()
        });
    }
    if app == APP_AUDIO {
        return audio::decode_sals(data).map(|messages| {
            messages
                .into_iter()
                .map(|message| match message {
                    audio::AudioSal::Command(command) => Sal::AudioCommand(command),
                    audio::AudioSal::Event(event) => Sal::AudioEvent(event),
                })
                .collect()
        });
    }
    if app == APP_SECURITY {
        return security::decode_sals(data).map(|messages| {
            messages
                .into_iter()
                .map(|message| match message {
                    security::SecuritySal::Command(command) => Sal::SecurityCommand(command),
                    security::SecuritySal::Event(event) => Sal::SecurityEvent(event),
                })
                .collect()
        });
    }
    if data
        .first()
        .is_some_and(|opcode| matches!(opcode & 0xe0, 0xa0 | 0xc0))
    {
        return label::decode_sals(app, data);
    }
    match app {
        a if (APP_LIGHTING_FIRST..=APP_LIGHTING_LAST).contains(&a) => {
            lighting::decode_sals(a, data)
        }
        APP_CLOCK => clock::decode_sals(data),
        APP_TEMPERATURE => temperature::decode_sals(data),
        APP_TRIGGER => trigger::decode_sals(data),
        APP_ENABLE => enable::decode_sals(data),
        APP_STATUS_REQUEST => status_request::decode_sals(data),
        _ => Err(DecodeError::new(format!(
            "unregistered application 0x{:02x}",
            app
        ))),
    }
}
