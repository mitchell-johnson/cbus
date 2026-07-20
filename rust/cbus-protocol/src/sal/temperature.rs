//! Port of `cbus/protocol/application/temperature.py` decode.

use super::Sal;
use crate::DecodeError;

/// Decode the temperature SAL stream of a PM packet.
pub fn decode_sals(data: &[u8]) -> Result<Vec<Sal>, DecodeError> {
    let mut out = Vec::new();
    let mut data = data;
    while !data.is_empty() {
        if data.len() < 3 {
            // less than 3 bytes of stray SAL: warn + stop
            break;
        }
        let command_code = data[0];
        let group_address = data[1];
        data = &data[2..];
        if command_code & 0x80 == 0x80 {
            break;
        }
        if command_code & 0x07 != 2 {
            // invalid length nibble (Temperature s9.4.1): warn + stop
            break;
        }
        let temperature = data[0] as f64 / 4.0;
        data = &data[1..];
        out.push(Sal::TemperatureBroadcast {
            group_address,
            temperature,
        });
    }
    Ok(out)
}
