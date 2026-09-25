//! Native C-Gate project-identify six-bit text codec.
//!
//! `NET SET_PROJECT_IDENTIFY` stores an upper-case, eight-character project
//! name in six bytes at unit parameter 35. Space has the special value 30;
//! every other supported character maps from ASCII `!`..`` ` `` to 0..63.

use crate::{DecodeError, EncodeError};

/// Encode one native project-identify string into its six-byte unit value.
///
/// Names contain one to eight UTF-16 code units before uppercasing, matching
/// Java's string-length check in native C-Gate. Unicode uppercase folding is
/// applied before the encoded repertoire is checked, so characters such as
/// `ſ` that fold into ASCII are accepted. The resulting repertoire is space
/// plus `!` through `` ` `` and must still fit in eight UTF-16 code units.
pub fn encode_project_identity(name: &str) -> Result<[u8; 6], EncodeError> {
    if name.is_empty() || name.encode_utf16().count() > 8 {
        return Err(EncodeError::new("sixbit string too long"));
    }
    let upper: String = name.chars().flat_map(char::to_uppercase).collect();
    if upper.encode_utf16().count() > 8 {
        return Err(EncodeError::new("sixbit string too long"));
    }
    let mut value = 0u64;
    for character in upper.chars().chain(std::iter::repeat(' ')).take(8) {
        let six = match character {
            ' ' => 30,
            '!'..='`' => character as u8 - b'!',
            _ => {
                return Err(EncodeError::new("Character out of sixbit range"));
            }
        };
        value = (value << 6) | u64::from(six);
    }
    let bytes = value.to_be_bytes();
    Ok(bytes[2..].try_into().expect("a 48-bit value is six bytes"))
}

/// Decode a native six-byte project-identify value.
///
/// The fixed eight-character width, including trailing padding spaces, is
/// retained like native C-Gate's `ProjectName` property. Embedded spaces and
/// every other representable character are retained verbatim.
pub fn decode_project_identity(encoded: &[u8]) -> Result<String, DecodeError> {
    let encoded: [u8; 6] = encoded
        .try_into()
        .map_err(|_| DecodeError::new("project identity must contain exactly six bytes"))?;
    let mut value = u64::from_be_bytes([
        0, 0, encoded[0], encoded[1], encoded[2], encoded[3], encoded[4], encoded[5],
    ]);
    let mut output = [b' '; 8];
    for index in (0..8).rev() {
        let six = (value & 0x3f) as u8;
        output[index] = if six == 30 { b' ' } else { six + b'!' };
        value >>= 6;
    }
    Ok(String::from_utf8(output.to_vec()).expect("the native six-bit repertoire is ASCII"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn native_project_identity_vector_and_case_folding() {
        let expected = [0xce, 0x4c, 0xb3, 0x79, 0xe7, 0x9e];
        assert_eq!(encode_project_identity("TEST").unwrap(), expected);
        assert_eq!(encode_project_identity("test").unwrap(), expected);
        assert_eq!(decode_project_identity(&expected).unwrap(), "TEST    ");
        assert_eq!(
            encode_project_identity("ſest").unwrap(),
            encode_project_identity("SEST").unwrap()
        );
    }

    #[test]
    fn project_identity_preserves_embedded_space_and_boundary_characters() {
        for name in ["A B", "!", "_"] {
            let encoded = encode_project_identity(name).unwrap();
            assert_eq!(
                decode_project_identity(&encoded).unwrap(),
                format!("{name:<8}")
            );
        }
        assert_eq!(
            encode_project_identity("?").unwrap(),
            encode_project_identity(" ").unwrap()
        );
        assert_eq!(decode_project_identity(&[0; 6]).unwrap(), "!!!!!!!!");
        assert_eq!(decode_project_identity(&[0xff; 6]).unwrap(), "````````");
    }

    #[test]
    fn project_identity_rejects_invalid_shapes() {
        for invalid in ["", "123456789", "café", "A\nB", "{"] {
            assert!(encode_project_identity(invalid).is_err(), "{invalid:?}");
        }
        assert_eq!(
            encode_project_identity("TOOLONG99")
                .unwrap_err()
                .to_string(),
            "sixbit string too long"
        );
        assert_eq!(
            encode_project_identity("{").unwrap_err().to_string(),
            "Character out of sixbit range"
        );
        assert_eq!(
            encode_project_identity("ééééé").unwrap_err().to_string(),
            "Character out of sixbit range"
        );
        assert_eq!(
            encode_project_identity("ßßßßß").unwrap_err().to_string(),
            "sixbit string too long"
        );
        assert!(decode_project_identity(&[0; 5]).is_err());
    }
}
