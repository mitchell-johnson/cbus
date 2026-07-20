//! Port of `cbus/protocol/application/status_request.py` decode.
//! Errors here (unknown type / bad block) invalidate the whole packet.

use super::Sal;
use crate::DecodeError;

pub fn decode_sals(data: &[u8]) -> Result<Vec<Sal>, DecodeError> {
    let mut out = Vec::new();
    let mut data = data;
    while !data.is_empty() {
        let level_request;
        if data[0] == 0x7a || data[0] == 0xfa {
            // 0xfa form is deprecated, decode-only; re-encodes as 0x7a
            data = &data[1..];
            level_request = false;
        } else if data.starts_with(&[0x73, 0x07]) {
            data = &data[2..];
            level_request = true;
        } else {
            return Err(DecodeError::new(format!(
                "Unknown status request type 0x{:x}",
                data[0]
            )));
        }

        // Python warns when len < 2 but then indexes anyway (IndexError)
        let child_application = *data
            .first()
            .ok_or_else(|| DecodeError::new("incomplete status request SAL"))?;
        let group_address = *data
            .get(1)
            .ok_or_else(|| DecodeError::new("incomplete status request SAL"))?;
        data = &data[2..];

        if group_address & 0x1f != 0 {
            return Err(DecodeError::new(
                "group_address report must be a multiple of 0x20",
            ));
        }
        out.push(Sal::StatusRequest {
            level_request,
            group_address,
            child_application,
        });
    }
    Ok(out)
}
