//! Native KEYGL5 static widget-group mapping.
//!
//! C-Gate 3.4.0.2001 reads the mapping from parameter `0xFA` as exactly
//! 44 bytes. Its `WidgetGroups` getter exposes every byte as an unsigned
//! decimal value separated by commas. Parameter `0xFB` is a separate
//! NUL-terminated extended-firmware string and is deliberately not handled
//! here.

use crate::{Cal, DecodeError};

/// CAL parameter containing the KEYGL5 static widget-group mapping.
pub const PARAMETER: u8 = 0xfa;

/// Exact byte count requested by native C-Gate.
pub const LENGTH: usize = 44;

/// Build the exact CAL recall used by native C-Gate.
pub fn request() -> Cal {
    Cal::Recall {
        param: PARAMETER,
        count: LENGTH as u8,
    }
}

/// Decode the exact native payload into C-Gate's comma-separated property.
pub fn decode_reply(data: &[u8]) -> Result<String, DecodeError> {
    if data.len() != LENGTH {
        return Err(DecodeError::new(
            "KEYGL5 WidgetGroups reply must contain exactly 44 bytes",
        ));
    }
    Ok(data.iter().map(u8::to_string).collect::<Vec<_>>().join(","))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn exact_request_and_native_decimal_projection() {
        assert_eq!(request().encode(), [0x1a, 0xfa, 0x2c]);
        let values = (0..LENGTH as u8).collect::<Vec<_>>();
        assert_eq!(
            decode_reply(&values).unwrap(),
            (0..LENGTH)
                .map(|value| value.to_string())
                .collect::<Vec<_>>()
                .join(",")
        );
        assert_eq!(
            decode_reply(&values[..LENGTH - 1]).unwrap_err().to_string(),
            "KEYGL5 WidgetGroups reply must contain exactly 44 bytes"
        );
    }
}
