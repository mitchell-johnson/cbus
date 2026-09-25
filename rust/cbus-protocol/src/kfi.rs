//! Native DLT Key Function Indicator (KFI) CAL sequences.
//!
//! KFI values are eight four-bit indicators. C-Gate's `LABEL KFIGET`
//! transaction selects the KFI bank with three parameter-`0xFF` writes before
//! identifying attribute `0x3D`; `LABEL KFISET` writes four packed pairs.

use crate::{Cal, DecodeError, EncodeError};

/// IDENTIFY attribute used for Key Function Indicator replies.
pub const ATTRIBUTE: u8 = 0x3d;

/// Number of Key Function Indicator values carried by the native commands.
pub const COUNT: usize = 8;

/// Build the exact four CAL requests used by native `LABEL KFIGET`.
pub fn get_requests() -> [Cal; 4] {
    [
        write(&[0x00, 0x09]),
        write(&[0x00, 0x82, 0x00, 0x1c]),
        write(&[0x00, 0x84, 0x04, 0xff]),
        Cal::Identify {
            attribute: ATTRIBUTE,
        },
    ]
}

/// Build the exact four parameter-`0xFF` writes used by native
/// `LABEL KFISET`.
pub fn set_requests(values: [u8; COUNT]) -> Result<[Cal; 4], EncodeError> {
    if values.iter().any(|value| *value > 0x0f) {
        return Err(EncodeError::new("KFI values must be in 0..15"));
    }
    let pair = |low: u8, high: u8| low | (high << 4);
    Ok([
        write(&[0x00, 0x09]),
        write(&[
            0x00,
            0x84,
            pair(values[0], values[1]),
            pair(values[2], values[3]),
        ]),
        write(&[
            0x00,
            0x84,
            pair(values[4], values[5]),
            pair(values[6], values[7]),
        ]),
        write(&[0x00, 0x6b, 0xac]),
    ])
}

/// Decode the twelve-byte payload of C-Gate's `8D 3D` KFI reply.
///
/// CAL opcode `0x8D` declares 13 following bytes (`0x8D & 0x1F`): the
/// attribute parameter plus exactly twelve data bytes. Native C-Gate then
/// matches the `8D 3D 80` prefix before extracting the four packed pairs.
/// The first byte is the fixed `0x80` selector. The following four bytes
/// contain low-nibble/high-nibble pairs for KFI 1 through KFI 8. Seven
/// trailing bytes are present in the native `0x8D` reply and are ignored.
pub fn decode_reply(data: &[u8]) -> Result<[u8; COUNT], DecodeError> {
    if data.len() != 12 {
        return Err(DecodeError::new(
            "KFI reply must use the native twelve-byte 0x8D payload",
        ));
    }
    if data[0] != 0x80 {
        return Err(DecodeError::new("KFI reply selector must be 0x80"));
    }
    let mut values = [0u8; COUNT];
    for (index, byte) in data[1..5].iter().copied().enumerate() {
        values[index * 2] = byte & 0x0f;
        values[index * 2 + 1] = byte >> 4;
    }
    Ok(values)
}

fn write(data: &[u8]) -> Cal {
    Cal::Write {
        parameter: 0xff,
        data: data.to_vec(),
    }
}
