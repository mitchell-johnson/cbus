//! Native standard dynamic-label cache clear CAL commands.
//!
//! C-Gate's `LABEL CLEAR` command uses one parameter-`0xFF` write. Clearing
//! every key carries `00 27`; clearing one key carries `00 66 <key>`, where
//! native key numbers are one-based in `1..=8`.

use crate::{Cal, EncodeError};

/// Build the exact CAL request for a native `LABEL CLEAR` operation.
///
/// `None` clears the complete dynamic-label cache. `Some(key)` clears one
/// one-based key in `1..=8`.
pub fn request(key: Option<u8>) -> Result<Cal, EncodeError> {
    let data = match key {
        None => vec![0x00, 0x27],
        Some(key @ 1..=8) => vec![0x00, 0x66, key],
        Some(_) => {
            return Err(EncodeError::new("dynamic-label clear key must be in 1..8"));
        }
    };
    Ok(Cal::Write {
        parameter: 0xff,
        data,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn exact_native_requests_and_key_validation() {
        assert_eq!(request(None).unwrap().encode(), [0xa3, 0xff, 0x00, 0x27]);
        assert_eq!(
            request(Some(1)).unwrap().encode(),
            [0xa4, 0xff, 0x00, 0x66, 0x01]
        );
        assert_eq!(
            request(Some(8)).unwrap().encode(),
            [0xa4, 0xff, 0x00, 0x66, 0x08]
        );
        for invalid in [0, 9, u8::MAX] {
            assert_eq!(
                request(Some(invalid)).unwrap_err().to_string(),
                "dynamic-label clear key must be in 1..8"
            );
        }
    }
}
