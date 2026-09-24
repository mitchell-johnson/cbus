//! Trigger Control application encoding and decoding.

use super::Sal;
use crate::common::{TRIGGER_EVENT, TRIGGER_INDICATOR_KILL, TRIGGER_MAX, TRIGGER_MIN};
use crate::DecodeError;

/// Decode one or more Trigger Control SAL commands.
///
/// The short MIN/MAX forms retain their wire identity rather than being
/// canonicalised to EVENT, so decode/re-encode remains exact.
pub fn decode_sals(data: &[u8]) -> Result<Vec<Sal>, DecodeError> {
    let mut result = Vec::new();
    let mut offset = 0;
    while offset < data.len() {
        let opcode = data[offset];
        match opcode {
            TRIGGER_EVENT => {
                let group_address = *data
                    .get(offset + 1)
                    .ok_or_else(|| DecodeError::new("truncated trigger event group"))?;
                let action_selector = *data
                    .get(offset + 2)
                    .ok_or_else(|| DecodeError::new("truncated trigger action selector"))?;
                result.push(Sal::TriggerEvent {
                    group_address,
                    action_selector,
                });
                offset += 3;
            }
            TRIGGER_INDICATOR_KILL => {
                let group_address = *data
                    .get(offset + 1)
                    .ok_or_else(|| DecodeError::new("truncated trigger indicator kill"))?;
                result.push(Sal::TriggerIndicatorKill { group_address });
                offset += 2;
            }
            TRIGGER_MIN => {
                let group_address = *data
                    .get(offset + 1)
                    .ok_or_else(|| DecodeError::new("truncated trigger minimum"))?;
                result.push(Sal::TriggerMin { group_address });
                offset += 2;
            }
            TRIGGER_MAX => {
                let group_address = *data
                    .get(offset + 1)
                    .ok_or_else(|| DecodeError::new("truncated trigger maximum"))?;
                result.push(Sal::TriggerMax { group_address });
                offset += 2;
            }
            _ => {
                return Err(DecodeError::new(format!(
                    "unsupported Trigger Control command 0x{opcode:02x}"
                )))
            }
        }
    }
    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn native_event_and_kill_capture_decodes_exactly() {
        assert_eq!(
            decode_sals(&[0x02, 0x01, 0x7b, 0x09, 0x01]).unwrap(),
            vec![
                Sal::TriggerEvent {
                    group_address: 1,
                    action_selector: 123,
                },
                Sal::TriggerIndicatorKill { group_address: 1 },
            ]
        );
    }

    #[test]
    fn short_min_and_max_forms_remain_distinct() {
        assert_eq!(
            decode_sals(&[0x01, 4, 0x79, 5]).unwrap(),
            vec![
                Sal::TriggerMin { group_address: 4 },
                Sal::TriggerMax { group_address: 5 },
            ]
        );
    }

    #[test]
    fn malformed_or_unknown_command_is_rejected_atomically() {
        for payload in [&[0x02, 1][..], &[0x09][..], &[0x03, 1, 2][..]] {
            assert!(decode_sals(payload).is_err());
        }
    }
}
