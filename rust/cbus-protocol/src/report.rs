//! Port of `cbus/protocol/cal/report.py`: binary & manchester level reports.

use crate::DecodeError;

const MANCHESTER_NIBBLES: [u8; 4] = [0b1010, 0b1001, 0b0110, 0b0101];

fn nibble_index(n: u8) -> Option<u8> {
    MANCHESTER_NIBBLES
        .iter()
        .position(|&x| x == n)
        .map(|i| i as u8)
}

/// Decode a 2-byte manchester pair into a level; any invalid nibble -> None.
pub fn manchester_decode(b: &[u8]) -> Option<u8> {
    let n0 = nibble_index(b[0] & 0xf)?;
    let n1 = nibble_index(b[0] >> 4)?;
    let n2 = nibble_index(b[1] & 0xf)?;
    let n3 = nibble_index(b[1] >> 4)?;
    Some(n0 | (n1 << 2) | (n2 << 4) | (n3 << 6))
}

/// Encode a level as a 2-byte manchester pair; None -> [0, 0].
pub fn manchester_encode(value: Option<u8>) -> [u8; 2] {
    match value {
        None => [0, 0],
        Some(v) => [
            MANCHESTER_NIBBLES[(v & 0x3) as usize]
                | (MANCHESTER_NIBBLES[((v >> 2) & 0x3) as usize] << 4),
            MANCHESTER_NIBBLES[((v >> 4) & 0x3) as usize]
                | (MANCHESTER_NIBBLES[((v >> 6) & 0x3) as usize] << 4),
        ],
    }
}

#[derive(Debug, Clone, PartialEq)]
pub enum StatusReport {
    /// group states, values 0..=3 (missing/on/off/error)
    Binary(Vec<u8>),
    /// levels 0-255, None = missing / undecodable manchester pair
    Level(Vec<Option<u8>>),
}

impl StatusReport {
    pub fn block_type(&self) -> u8 {
        match self {
            StatusReport::Binary(_) => 0x00,
            StatusReport::Level(_) => 0x07,
        }
    }

    /// 4 group states per byte, 2 bits each, LSB-first.
    pub fn decode_binary(data: &[u8]) -> StatusReport {
        let mut states = Vec::with_capacity(data.len() * 4);
        for &c in data {
            states.push(c & 0x3);
            states.push((c >> 2) & 0x3);
            states.push((c >> 4) & 0x3);
            states.push((c >> 6) & 0x3);
        }
        StatusReport::Binary(states)
    }

    /// 2 bytes per level; odd byte count is an error.
    pub fn decode_level(data: &[u8]) -> Result<StatusReport, DecodeError> {
        if !data.len().is_multiple_of(2) {
            return Err(DecodeError::new(
                "Expected a multiple of 2 bytes in LevelStatusReport",
            ));
        }
        Ok(StatusReport::Level(
            data.chunks(2).map(manchester_decode).collect(),
        ))
    }

    pub fn encode(&self) -> Vec<u8> {
        match self {
            StatusReport::Binary(states) => {
                let mut s = states.clone();
                let r = s.len() % 4;
                if r != 0 {
                    // pad with MISSING
                    s.resize(s.len() + (4 - r), 0);
                }
                s.chunks(4)
                    .map(|c| c[0] | (c[1] << 2) | (c[2] << 4) | (c[3] << 6))
                    .collect()
            }
            StatusReport::Level(levels) => {
                levels.iter().flat_map(|&l| manchester_encode(l)).collect()
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn manchester() {
        assert_eq!(manchester_decode(&[0xaa, 0xaa]), Some(0));
        assert_eq!(manchester_decode(&[0x00, 0x00]), None);
        assert_eq!(manchester_decode(&[0x95, 0x99]), Some(0x57));
        assert_eq!(manchester_decode(&[0x55, 0x55]), Some(0xff));
        for v in 0..=255u8 {
            let enc = manchester_encode(Some(v));
            assert_eq!(manchester_decode(&enc), Some(v));
        }
        assert_eq!(manchester_encode(None), [0, 0]);
    }

    #[test]
    fn binary_report_roundtrip() {
        let r = StatusReport::decode_binary(&[0b11100100]);
        assert_eq!(r, StatusReport::Binary(vec![0, 1, 2, 3]));
        assert_eq!(r.encode(), vec![0b11100100]);
        // padding: 5 states -> 2 bytes
        let r = StatusReport::Binary(vec![1, 1, 1, 1, 1]);
        assert_eq!(r.encode(), vec![0b01010101, 0b00000001]);
    }

    #[test]
    fn level_report() {
        assert!(StatusReport::decode_level(&[0xaa]).is_err());
        let r = StatusReport::decode_level(&[0xaa, 0xaa, 0x00, 0x00]).unwrap();
        assert_eq!(r, StatusReport::Level(vec![Some(0), None]));
        assert_eq!(r.encode(), vec![0xaa, 0xaa, 0x00, 0x00]);
    }
}
