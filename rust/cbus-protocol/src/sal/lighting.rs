//! Port of `cbus/protocol/application/lighting.py` decode (forgiving:
//! warn-and-stop on malformed tails).

use super::Sal;
use crate::common::{ramp_rate_to_duration, LIGHT_OFF, LIGHT_ON, LIGHT_TERMINATE_RAMP};
use crate::DecodeError;

/// Decode the lighting SAL stream of a PM packet.
pub fn decode_sals(application: u8, data: &[u8]) -> Result<Vec<Sal>, DecodeError> {
    let mut out = Vec::new();
    let mut data = data;
    while !data.is_empty() {
        if data.len() < 2 {
            // 1 byte of stray SAL: warn + stop
            break;
        }
        let command_code = data[0];
        let group_address = data[1];
        data = &data[2..];
        match command_code {
            LIGHT_ON => out.push(Sal::LightingOn {
                application,
                group_address,
            }),
            LIGHT_OFF => out.push(Sal::LightingOff {
                application,
                group_address,
            }),
            LIGHT_TERMINATE_RAMP => out.push(Sal::LightingTerminateRamp {
                application,
                group_address,
            }),
            c => match ramp_rate_to_duration(c) {
                Some(duration) => {
                    if data.is_empty() {
                        // ramp missing its level byte: warn + drop the SAL
                        break;
                    }
                    let level = data[0];
                    data = &data[1..];
                    out.push(Sal::LightingRamp {
                        application,
                        group_address,
                        duration,
                        level,
                    });
                }
                // unknown command code: warn + stop
                None => break,
            },
        }
    }
    Ok(out)
}
