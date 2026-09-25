//! Native KEYGL5 synchronization metadata.
//!
//! C-Gate 3.4.0.2001 reads the eDLT's extended firmware string from
//! parameter `0xFB` as exactly nine bytes. It separately selects OEM memory
//! address 16 and recalls two bytes for the primary and secondary C-Bus
//! applications. These values are distinct from the ordinary IDENTIFY2
//! version string.

use crate::{Cal, DecodeError};

/// CAL parameter containing the KEYGL5 extended firmware string.
pub const FIRMWARE_PARAMETER: u8 = 0xfb;

/// Exact extended-firmware byte count requested by native C-Gate.
pub const FIRMWARE_LENGTH: usize = 9;

/// OEM memory address containing the primary and secondary applications.
pub const APPLICATION_ADDRESS: u32 = 16;

/// Exact application byte count requested by native C-Gate.
pub const APPLICATION_LENGTH: usize = 2;

/// Build the exact CAL recall used for the native extended-firmware read.
pub fn firmware_request() -> Cal {
    Cal::Recall {
        param: FIRMWARE_PARAMETER,
        count: FIRMWARE_LENGTH as u8,
    }
}

/// Decode the native fixed-width, NUL-terminated extended-firmware string.
///
/// Native C-Gate casts each unsigned byte directly to a Java character and
/// stops at the first NUL. Mapping each byte to the same Unicode code point
/// preserves that behavior for all possible byte values.
pub fn decode_firmware(data: &[u8]) -> Result<String, DecodeError> {
    if data.len() != FIRMWARE_LENGTH {
        return Err(DecodeError::new(
            "KEYGL5 extended-firmware reply must contain exactly 9 bytes",
        ));
    }
    Ok(data
        .iter()
        .copied()
        .take_while(|value| *value != 0)
        .map(char::from)
        .collect())
}

/// Decode the exact OEM-memory application pair.
pub fn decode_applications(data: &[u8]) -> Result<[u8; APPLICATION_LENGTH], DecodeError> {
    data.try_into()
        .map_err(|_| DecodeError::new("KEYGL5 application reply must contain exactly 2 bytes"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn exact_firmware_request_and_native_nul_projection() {
        assert_eq!(firmware_request().encode(), [0x1a, 0xfb, 0x09]);
        assert_eq!(decode_firmware(b"01.05.00\0").unwrap(), "01.05.00");
        assert_eq!(decode_firmware(b"A\0ignored").unwrap(), "A");
        assert_eq!(
            decode_firmware(&[0xff, 0, 1, 2, 3, 4, 5, 6, 7]).unwrap(),
            "ÿ"
        );
        assert_eq!(
            decode_firmware(b"short").unwrap_err().to_string(),
            "KEYGL5 extended-firmware reply must contain exactly 9 bytes"
        );
    }

    #[test]
    fn exact_application_pair() {
        assert_eq!(decode_applications(&[56, 255]).unwrap(), [56, 255]);
        assert_eq!(
            decode_applications(&[56]).unwrap_err().to_string(),
            "KEYGL5 application reply must contain exactly 2 bytes"
        );
    }
}
