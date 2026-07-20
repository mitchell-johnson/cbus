//! SAL model + application dispatch. Port of
//! `cbus/protocol/application/*.py` (registry in `__init__.py:30-36`).

pub mod clock;
pub mod enable;
pub mod lighting;
pub mod status_request;
pub mod temperature;

use crate::common::{
    APP_CLOCK, APP_ENABLE, APP_LIGHTING_FIRST, APP_LIGHTING_LAST, APP_STATUS_REQUEST,
    APP_TEMPERATURE, CLOCK_ATTR_DATE, CLOCK_ATTR_TIME, CLOCK_REQUEST_REFRESH,
    ENABLE_SET_NETWORK_VARIABLE, LIGHT_OFF, LIGHT_ON, LIGHT_TERMINATE_RAMP,
    TEMPERATURE_BROADCAST, duration_to_ramp_rate,
};
use crate::{DecodeError, EncodeError};
use chrono::Datelike;

#[derive(Debug, Clone, PartialEq)]
pub enum Sal {
    LightingOn {
        application: u8,
        group_address: u8,
    },
    LightingOff {
        application: u8,
        group_address: u8,
    },
    LightingTerminateRamp {
        application: u8,
        group_address: u8,
    },
    LightingRamp {
        application: u8,
        group_address: u8,
        duration: u32,
        level: u8,
    },
    ClockUpdateTime {
        hour: u8,
        minute: u8,
        second: u8,
    },
    ClockUpdateDate {
        year: u16,
        month: u8,
        day: u8,
    },
    ClockRequest,
    TemperatureBroadcast {
        group_address: u8,
        temperature: f64,
    },
    EnableSetNetworkVariable {
        variable: u8,
        value: u8,
    },
    StatusRequest {
        level_request: bool,
        group_address: u8,
        child_application: u8,
    },
}

impl Sal {
    /// Application byte this SAL belongs to.
    pub fn application(&self) -> u8 {
        match self {
            Sal::LightingOn { application, .. }
            | Sal::LightingOff { application, .. }
            | Sal::LightingTerminateRamp { application, .. }
            | Sal::LightingRamp { application, .. } => *application,
            Sal::ClockUpdateTime { .. } | Sal::ClockUpdateDate { .. } | Sal::ClockRequest => {
                APP_CLOCK
            }
            Sal::TemperatureBroadcast { .. } => APP_TEMPERATURE,
            Sal::EnableSetNetworkVariable { .. } => APP_ENABLE,
            Sal::StatusRequest { .. } => APP_STATUS_REQUEST,
        }
    }

    pub fn encode(&self) -> Result<Vec<u8>, EncodeError> {
        match self {
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
                Ok(vec![0x0e, CLOCK_ATTR_DATE, yb[0], yb[1], *month, *day, weekday])
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
        }
    }
}

/// Application dispatch: decode the SAL payload of a PM packet.
/// Mirrors the Python registry: only status-request (0xFF), clock (0xDF),
/// enable (0xCB), lighting (0x30-0x5F) and temperature (0x19) are
/// registered; anything else errors (-> Invalid packet).
pub fn decode_sals(app: u8, data: &[u8]) -> Result<Vec<Sal>, DecodeError> {
    match app {
        a if (APP_LIGHTING_FIRST..=APP_LIGHTING_LAST).contains(&a) => {
            lighting::decode_sals(a, data)
        }
        APP_CLOCK => clock::decode_sals(data),
        APP_TEMPERATURE => temperature::decode_sals(data),
        APP_ENABLE => enable::decode_sals(data),
        APP_STATUS_REQUEST => status_request::decode_sals(data),
        _ => Err(DecodeError::new(format!(
            "unregistered application 0x{:02x}",
            app
        ))),
    }
}
