//! Measurement application SAL data broadcasts implemented by C-Gate 3.4.
//!
//! The layout and bounds are pinned to an isolated C-Gate 3.4.0.2001
//! instance. A Measurement data command is a broadcast: PCI confirmation
//! proves interface delivery, not acceptance by a measurement device.

use crate::{DecodeError, EncodeError};

/// One Measurement application channel sample.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct MeasurementData {
    /// Measurement device address.
    pub device: u8,
    /// Channel within the measurement device.
    pub channel: u8,
    /// Signed sixteen-bit mantissa.
    pub value: i16,
    /// Signed base-ten multiplier/exponent.
    pub multiplier: i8,
    /// Native C-Bus engineering-units selector.
    pub units: u8,
}

impl MeasurementData {
    /// Exact SAL bytes excluding the point-to-multipoint envelope.
    pub fn encode(self) -> Result<Vec<u8>, EncodeError> {
        let value = self.value.to_be_bytes();
        Ok(vec![
            0x0e,
            self.device,
            self.channel,
            self.units,
            self.multiplier as u8,
            value[0],
            value[1],
        ])
    }

    /// Native C-Gate event arguments, after the channel address.
    pub fn event_arguments(self) -> String {
        format!("{} {} {}", self.value, self.multiplier, self.units)
    }
}

/// Decode the Measurement SAL stream of a point-to-multipoint packet.
pub fn decode_sals(data: &[u8]) -> Result<Vec<MeasurementData>, DecodeError> {
    if data.is_empty() {
        return Ok(Vec::new());
    }
    if !data.len().is_multiple_of(7) {
        return Err(DecodeError::new("truncated Measurement data command"));
    }
    data.chunks_exact(7)
        .map(|chunk| {
            if chunk[0] != 0x0e {
                return Err(DecodeError::new(format!(
                    "unsupported Measurement opcode 0x{:02x}",
                    chunk[0]
                )));
            }
            Ok(MeasurementData {
                device: chunk[1],
                channel: chunk[2],
                units: chunk[3],
                multiplier: chunk[4] as i8,
                value: i16::from_be_bytes([chunk[5], chunk[6]]),
            })
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn native_examples_round_trip() {
        for (sample, encoded) in [
            (
                MeasurementData {
                    device: 1,
                    channel: 1,
                    value: 10_234,
                    multiplier: -2,
                    units: 2,
                },
                vec![0x0e, 1, 1, 2, 0xfe, 0x27, 0xfa],
            ),
            (
                MeasurementData {
                    device: 0,
                    channel: 0,
                    value: i16::MIN,
                    multiplier: i8::MIN,
                    units: 0,
                },
                vec![0x0e, 0, 0, 0, 0x80, 0x80, 0x00],
            ),
            (
                MeasurementData {
                    device: u8::MAX,
                    channel: u8::MAX,
                    value: i16::MAX,
                    multiplier: i8::MAX,
                    units: u8::MAX,
                },
                vec![0x0e, 0xff, 0xff, 0xff, 0x7f, 0x7f, 0xff],
            ),
        ] {
            assert_eq!(sample.encode().unwrap(), encoded);
            assert_eq!(decode_sals(&encoded).unwrap(), vec![sample]);
        }
    }

    #[test]
    fn decoder_rejects_truncation_and_unknown_opcodes() {
        assert!(decode_sals(&[0x0e, 1]).is_err());
        assert!(decode_sals(&[0x0d, 1, 2, 3, 4, 5, 6]).is_err());
    }
}
