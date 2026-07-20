//! Port of `cbus/protocol/application/enable.py` decode.

use super::Sal;
use crate::DecodeError;

/// Decode the enable-control SAL stream of a PM packet.
pub fn decode_sals(data: &[u8]) -> Result<Vec<Sal>, DecodeError> {
    let mut out = Vec::new();
    let mut data = data;
    while !data.is_empty() {
        if data.len() < 3 {
            // less than 3 bytes of stray SAL: warn + stop
            break;
        }
        let command_code = data[0];
        data = &data[1..];
        if command_code & 0x80 == 0x80 {
            break;
        }
        if command_code & 0x07 != 2 {
            // invalid length nibble (Enable s9.4.1): warn + stop
            break;
        }
        let variable = data[0];
        let value = data[1];
        data = &data[2..];
        out.push(Sal::EnableSetNetworkVariable { variable, value });
    }
    Ok(out)
}
