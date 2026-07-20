//! Port of `cbus/protocol/application/clock.py` decode, including the
//! double-skip bug for unknown clock variables (`clock.py:175`).

use super::Sal;
use crate::common::{CLOCK_ATTR_DATE, CLOCK_ATTR_TIME, CLOCK_REQUEST_REFRESH};
use crate::DecodeError;

/// Python-style forgiving slice: `data[n:]`.
fn skip(data: &[u8], n: usize) -> &[u8] {
    &data[n.min(data.len())..]
}

pub fn decode_sals(data: &[u8]) -> Result<Vec<Sal>, DecodeError> {
    let mut out = Vec::new();
    let mut data = data;
    while !data.is_empty() {
        let command_code = data[0];
        data = &data[1..];

        if command_code & 0x80 == 0x80 {
            // long form is not used: warn + stop
            break;
        }
        if command_code & 0xe0 != 0 {
            // unknown high bits: warn + stop
            break;
        }
        if command_code & 0xf8 == 0x08 {
            // ClockUpdateSAL.decode
            let variable = *data
                .first()
                .ok_or_else(|| DecodeError::new("truncated clock update"))?;
            let data_length = (command_code & 0x07) as usize;
            // val = data[1:data_length] (forgiving slice)
            let val_end = data_length.min(data.len());
            let val: &[u8] = if val_end > 1 { &data[1..val_end] } else { &[] };
            let new_data = skip(data, data_length);

            if variable == CLOCK_ATTR_DATE {
                if data_length != 6 {
                    // warn: ignoring date variable with wrong length
                    data = new_data;
                    continue;
                }
                // unpack('>HBBB', val) requires exactly 5 bytes
                if val.len() != 5 {
                    return Err(DecodeError::new("short clock date value"));
                }
                let year = u16::from_be_bytes([val[0], val[1]]);
                let month = val[2];
                let day = val[3];
                // day-of-week byte (val[4]) is ignored
                // Python date() validation: year 1..=9999, valid month/day
                if !(1..=9999).contains(&year)
                    || chrono::NaiveDate::from_ymd_opt(year as i32, month as u32, day as u32)
                        .is_none()
                {
                    return Err(DecodeError::new("invalid date"));
                }
                out.push(Sal::ClockUpdateDate { year, month, day });
                data = new_data;
            } else if variable == CLOCK_ATTR_TIME {
                if data_length != 5 {
                    data = new_data;
                    continue;
                }
                // unpack('>BBBB', val) requires exactly 4 bytes
                if val.len() != 4 {
                    return Err(DecodeError::new("short clock time value"));
                }
                let (hour, minute, second) = (val[0], val[1], val[2]);
                // dst byte (val[3]) is ignored
                // Python time() validation
                if hour > 23 || minute > 59 || second > 59 {
                    return Err(DecodeError::new("invalid time"));
                }
                out.push(Sal::ClockUpdateTime {
                    hour,
                    minute,
                    second,
                });
                data = new_data;
            } else {
                // unknown clock variable: Python skips data_length TWICE
                // (bug in clock.py:175) -- keep bug-for-bug.
                data = skip(new_data, data_length);
            }
        } else if command_code == CLOCK_REQUEST_REFRESH {
            let argument = *data
                .first()
                .ok_or_else(|| DecodeError::new("truncated clock request"))?;
            data = &data[1..];
            if argument != 0x03 {
                // warn: request refresh argument != 3; SAL dropped
                continue;
            }
            out.push(Sal::ClockRequest);
        } else {
            // last stage dropout: warn + stop
            break;
        }
    }
    Ok(out)
}
