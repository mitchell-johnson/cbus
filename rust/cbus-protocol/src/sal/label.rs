//! Dynamic-label SAL codecs used by lighting, Trigger Control, and Enable.
//!
//! The command byte carries the complete SAL length. Standard labels use the
//! `0xA0` family and Unicode fragments use `0xC0`.

use super::Sal;
use crate::{DecodeError, EncodeError};

const MAX_STANDARD_DATA: usize = 14;
const MAX_UNICODE_FRAGMENTS: usize = 18;
const MAX_DYNAMIC_ICON_BYTES: usize = 1800;

fn target(application: u8, variant: u8, action_selector: Option<u8>) -> Result<bool, EncodeError> {
    if !(48..=95).contains(&application) && !matches!(application, 202 | 203) {
        return Err(EncodeError::new("unsupported dynamic-label application"));
    }
    if variant > 3 {
        return Err(EncodeError::new("dynamic-label variant must be 0..3"));
    }
    Ok(action_selector.is_some())
}

/// Encode one standard dynamic-label SAL payload.
pub fn encode_standard(
    application: u8,
    group: u8,
    language: u8,
    options: u8,
    data: &[u8],
    action_selector: Option<u8>,
    variant: u8,
) -> Result<Vec<u8>, EncodeError> {
    let selected = target(application, variant, action_selector)?;
    if data.len() > MAX_STANDARD_DATA {
        return Err(EncodeError::new(
            "standard dynamic-label data exceeds 14 bytes",
        ));
    }
    let mut payload = vec![
        0xa0 | (data.len() as u8 + 3 + u8::from(selected)),
        group,
        options | u8::from(selected) | (variant << 5),
    ];
    if let Some(action_selector) = action_selector {
        payload.push(action_selector);
    }
    payload.push(language);
    payload.extend_from_slice(data);
    Ok(payload)
}

/// Encode native segmented UTF-8 labels. The sequence nibble is selected by
/// the caller so a command can reserve one contiguous modulo-16 sequence.
pub fn encode_unicode(
    application: u8,
    group: u8,
    language: u8,
    data: &[u8],
    action_selector: Option<u8>,
    variant: u8,
    sequence: u8,
) -> Result<Vec<Vec<u8>>, EncodeError> {
    let selected = target(application, variant, action_selector)?;
    if application == 203 {
        return Err(EncodeError::new(
            "Enable Control has no Unicode label command",
        ));
    }
    if sequence > 15 {
        return Err(EncodeError::new(
            "Unicode dynamic-label sequence must be 0..15",
        ));
    }
    std::str::from_utf8(data)
        .map_err(|_| EncodeError::new("Unicode dynamic-label data is not valid UTF-8"))?;
    let chunk_size = if selected { 12 } else { 13 };
    if data.len() > chunk_size * MAX_UNICODE_FRAGMENTS {
        return Err(EncodeError::new(
            "Unicode dynamic-label data exceeds eighteen fragments",
        ));
    }
    let chunks = if data.is_empty() {
        vec![&[][..]]
    } else {
        data.chunks(chunk_size).collect::<Vec<_>>()
    };
    let last = chunks.len() - 1;
    Ok(chunks
        .into_iter()
        .enumerate()
        .map(|(index, chunk)| {
            let phase = if last == 0 {
                12
            } else if index == 0 {
                0
            } else if index == last {
                8
            } else {
                4
            };
            let control = phase
                | (((usize::from(sequence) + index) & 15) as u8) << 4
                | if selected { 3 } else { 2 };
            let mut payload = vec![
                0xc0 | (chunk.len() as u8 + 4 + u8::from(selected)),
                group,
                control,
                (if selected { 0x80 } else { 0 }) | variant,
            ];
            if let Some(action_selector) = action_selector {
                payload.push(action_selector);
            }
            payload.push(language);
            payload.extend_from_slice(chunk);
            payload
        })
        .collect())
}

/// Encode the native start/header/chunk/commit sequence for one dynamic icon.
#[allow(clippy::too_many_arguments)]
pub fn encode_dynamic_icon(
    application: u8,
    group: u8,
    language: u8,
    icon: u16,
    width: u8,
    height: u8,
    vertical_offset: u8,
    data: &[u8],
    action_selector: Option<u8>,
    variant: u8,
) -> Result<Vec<Vec<u8>>, EncodeError> {
    let selected = target(application, variant, action_selector)?;
    if !(1..=240).contains(&width) || !(1..=60).contains(&height) {
        return Err(EncodeError::new(
            "dynamic icon dimensions are outside native bounds",
        ));
    }
    let expected = (usize::from(width) * usize::from(height)).div_ceil(8);
    if expected > MAX_DYNAMIC_ICON_BYTES || data.len() != expected {
        return Err(EncodeError::new(
            "dynamic icon byte count does not match its dimensions",
        ));
    }
    let mut result = vec![encode_standard(
        application,
        group,
        0,
        8,
        &[0x20],
        action_selector,
        variant,
    )?];
    let [icon_high, icon_low] = icon.to_be_bytes();
    result.push(encode_standard(
        application,
        group,
        language,
        4,
        &[icon_high, icon_low, width, height, vertical_offset],
        action_selector,
        variant,
    )?);
    for chunk in data.chunks(6) {
        result.push(encode_standard(
            application,
            group,
            0,
            8,
            &[0x21],
            action_selector,
            variant,
        )?);
        let mut payload = vec![
            0xa0 | (chunk.len() as u8 + 2 + u8::from(selected)),
            group,
            4 | u8::from(selected) | (variant << 5),
        ];
        if let Some(action_selector) = action_selector {
            payload.push(action_selector);
        }
        payload.extend_from_slice(chunk);
        result.push(payload);
    }
    result.push(encode_standard(
        application,
        group,
        0,
        8,
        &[0x22],
        action_selector,
        variant,
    )?);
    Ok(result)
}

/// Validate one complete label payload and retain its exact wire bytes.
pub fn validate_payload(application: u8, payload: &[u8]) -> Result<(), EncodeError> {
    target(application, 0, None)?;
    let Some(opcode) = payload.first().copied() else {
        return Err(EncodeError::new("empty dynamic-label payload"));
    };
    if !matches!(opcode & 0xe0, 0xa0 | 0xc0) || usize::from(opcode & 0x1f) + 1 != payload.len() {
        return Err(EncodeError::new("invalid dynamic-label payload length"));
    }
    match opcode & 0xe0 {
        0xa0 => {
            let options = *payload
                .get(2)
                .ok_or_else(|| EncodeError::new("truncated standard dynamic-label payload"))?;
            if payload.len() < if options & 1 == 0 { 4 } else { 5 } {
                return Err(EncodeError::new("truncated standard dynamic-label payload"));
            }
        }
        0xc0 => {
            if application == 203 {
                return Err(EncodeError::new(
                    "Enable Control has no Unicode label command",
                ));
            }
            let control = *payload
                .get(2)
                .ok_or_else(|| EncodeError::new("truncated Unicode dynamic-label payload"))?;
            let options = *payload
                .get(3)
                .ok_or_else(|| EncodeError::new("truncated Unicode dynamic-label payload"))?;
            let selected = options & 0x80 != 0;
            if control & 3 != if selected { 3 } else { 2 }
                || payload.len() < if selected { 6 } else { 5 }
            {
                return Err(EncodeError::new("invalid Unicode dynamic-label header"));
            }
        }
        _ => unreachable!("dynamic-label family was checked above"),
    }
    Ok(())
}

/// Decode a stream containing one or more complete dynamic-label payloads.
pub fn decode_sals(application: u8, mut data: &[u8]) -> Result<Vec<Sal>, DecodeError> {
    let mut result = Vec::new();
    while !data.is_empty() {
        let length = usize::from(data[0] & 0x1f) + 1;
        if !matches!(data[0] & 0xe0, 0xa0 | 0xc0) || length > data.len() {
            return Err(DecodeError::new("truncated dynamic-label SAL"));
        }
        let payload = data[..length].to_vec();
        validate_payload(application, &payload)
            .map_err(|error| DecodeError::new(error.to_string()))?;
        result.push(Sal::DynamicLabel {
            application,
            payload,
        });
        data = &data[length..];
    }
    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn native_standard_unicode_and_dynamic_encodings() {
        assert_eq!(
            encode_standard(56, 1, 0, 0, b"Lounge", None, 2).unwrap(),
            hex::decode("a90140004c6f756e6765").unwrap()
        );
        assert_eq!(
            encode_unicode(56, 1, 0, "Māori".as_bytes(), None, 1, 14).unwrap(),
            vec![hex::decode("ca01ee01004dc4816f7269").unwrap()]
        );
        assert_eq!(
            encode_dynamic_icon(56, 3, 7, 65535, 8, 7, 2, &[1, 2, 4, 8, 16, 32, 64], None, 0)
                .unwrap(),
            vec![
                hex::decode("a403080020").unwrap(),
                hex::decode("a8030407ffff080702").unwrap(),
                hex::decode("a403080021").unwrap(),
                hex::decode("a80304010204081020").unwrap(),
                hex::decode("a403080021").unwrap(),
                hex::decode("a3030440").unwrap(),
                hex::decode("a403080022").unwrap(),
            ]
        );
    }
}
