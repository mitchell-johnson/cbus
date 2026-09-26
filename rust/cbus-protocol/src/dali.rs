//! Native C-Gate DALI extended-CAL primitives.
//!
//! C-Bus DALI gateways use point-to-point extended CAL. The command byte is
//! line-relative for DALI device commands (line B sets bit 7), while gateway
//! commands keep their operation byte unchanged.

use crate::{Cal, EncodeError};

/// A DALI gateway line.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DaliLine {
    /// DALI line A (`A` or `0` in the C-Gate grammar).
    A,
    /// DALI line B (`B` or `1` in the C-Gate grammar).
    B,
}

impl DaliLine {
    /// Parse native C-Gate line spellings.
    pub fn parse(value: &str) -> Result<Self, EncodeError> {
        if value.eq_ignore_ascii_case("A") || value == "0" {
            Ok(Self::A)
        } else if value.eq_ignore_ascii_case("B") || value == "1" {
            Ok(Self::B)
        } else {
            Err(EncodeError::new("DALI line must be A, B, 0, or 1"))
        }
    }

    /// Native display spelling.
    pub fn name(self) -> &'static str {
        match self {
            Self::A => "A",
            Self::B => "B",
        }
    }

    /// Apply the native line bit. Gateway commands (`device_type == 0`) use
    /// the same operation on both lines.
    pub fn operation(self, device_type: u8, operation: u8) -> u8 {
        if device_type == 0 || self == Self::A {
            operation
        } else {
            operation | 0x80
        }
    }
}

/// Native extended-CAL command mode accepted by C-Gate's DALI family.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DaliCalMode {
    /// Execute and poll while the gateway reports running or busy.
    Auto,
    /// Send one `0x81` execute.
    Execute,
    /// Send one `0x82` poll.
    Poll,
    /// Send one `0x83` status request.
    Status,
    /// Send one `0x84` cancel.
    Cancel,
}

impl DaliCalMode {
    /// Parse native full names and unambiguous prefixes.
    pub fn parse(value: &str) -> Option<Self> {
        let value = value.trim().to_ascii_uppercase();
        if value.is_empty() {
            None
        } else if "AUTO".starts_with(&value) {
            Some(Self::Auto)
        } else if "EXECUTE".starts_with(&value) {
            Some(Self::Execute)
        } else if "POLL".starts_with(&value) {
            Some(Self::Poll)
        } else if "STATUS".starts_with(&value) {
            Some(Self::Status)
        } else if "CANCEL".starts_with(&value) {
            Some(Self::Cancel)
        } else {
            None
        }
    }

    /// Native response/debug name.
    pub fn name(self) -> &'static str {
        match self {
            Self::Auto => "AUTO",
            Self::Execute => "EXECUTE",
            Self::Poll => "POLL",
            Self::Status => "STATUS",
            Self::Cancel => "CANCEL",
        }
    }

    /// Build the CAL request. Payload is legal only for execute/auto. C-Gate
    /// sends status selector zero for its status form.
    pub fn request(
        self,
        device_type: u8,
        operation: u8,
        payload: &[u8],
    ) -> Result<Cal, EncodeError> {
        if payload.len() > 10 {
            return Err(EncodeError::new("DALI payload cannot exceed ten bytes"));
        }
        match self {
            Self::Auto | Self::Execute => Ok(Cal::Execute {
                group: device_type,
                operation,
                data: payload.to_vec(),
            }),
            Self::Poll if payload.is_empty() => Ok(Cal::Poll {
                group: device_type,
                operation,
            }),
            Self::Status if payload.is_empty() => Ok(Cal::ExtendedStatusRequest {
                group: device_type,
                operation,
                status: 0,
            }),
            Self::Cancel if payload.is_empty() => Ok(Cal::Cancel {
                group: device_type,
                operation,
            }),
            Self::Poll => Err(EncodeError::new("DALI poll cannot carry a payload")),
            Self::Status => Err(EncodeError::new("DALI status cannot carry a payload")),
            Self::Cancel => Err(EncodeError::new("DALI cancel cannot carry a payload")),
        }
    }
}

/// Parse a fixed-width native hexadecimal bit mask.
///
/// `L` pads on the left, `R` pads on the right, and `>` reverses decoded
/// bytes. The modifiers match C-Gate 3.4's DALI parser.
pub fn parse_mask(value: &str, bytes: usize) -> Result<Vec<u8>, EncodeError> {
    if bytes == 0 {
        return Err(EncodeError::new("DALI mask width must be nonzero"));
    }
    let value = value.trim();
    if value.is_empty() {
        return Err(EncodeError::new("DALI mask cannot be empty"));
    }
    let prefix = &value[..value.len().min(2)];
    let left = prefix.to_ascii_uppercase().contains('L');
    let right = prefix.to_ascii_uppercase().contains('R');
    let reverse = prefix.contains('>');
    let cut = usize::from(reverse) + usize::from(left || right);
    if cut > value.len() {
        return Err(EncodeError::new("invalid DALI mask modifier"));
    }
    let mut digits = value[cut..].to_string();
    let width = bytes * 2;
    if left && digits.len() < width {
        digits = format!("{}{}", "0".repeat(width - digits.len()), digits);
    } else if right && digits.len() < width {
        digits.push_str(&"0".repeat(width - digits.len()));
    }
    if digits.len() != width {
        return Err(EncodeError::new(format!(
            "DALI mask must contain {width} hexadecimal characters"
        )));
    }
    let mut result = hex::decode(&digits)
        .map_err(|error| EncodeError::new(format!("invalid DALI mask: {error}")))?;
    if reverse {
        result.reverse();
    }
    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn line_b_sets_only_device_command_bit() {
        assert_eq!(DaliLine::B.operation(0xda, 7), 0x87);
        assert_eq!(DaliLine::B.operation(0, 4), 4);
    }

    #[test]
    fn modes_encode_native_extended_cal() {
        assert_eq!(
            DaliCalMode::Execute
                .request(0xda, 7, &[3])
                .unwrap()
                .encode(),
            [0xe4, 0x81, 0xda, 7, 3]
        );
        assert_eq!(
            DaliCalMode::Poll.request(0xda, 7, &[]).unwrap().encode(),
            [0xe3, 0x82, 0xda, 7]
        );
        assert_eq!(
            DaliCalMode::Status.request(0xda, 7, &[]).unwrap().encode(),
            [0xe4, 0x83, 0xda, 7, 0]
        );
        assert_eq!(
            DaliCalMode::Cancel.request(0xda, 7, &[]).unwrap().encode(),
            [0xe3, 0x84, 0xda, 7]
        );
    }

    #[test]
    fn mask_modifiers_match_native_direction_and_padding() {
        assert_eq!(parse_mask("L1", 2).unwrap(), [0, 1]);
        assert_eq!(parse_mask("R1", 2).unwrap(), [0x10, 0]);
        assert_eq!(parse_mask(">0102", 2).unwrap(), [2, 1]);
    }
}
