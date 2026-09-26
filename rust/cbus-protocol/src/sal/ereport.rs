//! Error Reporting application messages implemented by C-Gate 3.4.

use crate::{DecodeError, EncodeError};

/// One fixed-width Error Reporting message.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ErrorReportMessage {
    /// Message type byte. Named native values are 5, 21, 37, and 53.
    pub message_type: u8,
    /// Ten-bit category number.
    pub category: u16,
    /// Most-recent marker.
    pub most_recent: bool,
    /// Acknowledged marker.
    pub acknowledged: bool,
    /// Most-severe marker.
    pub most_severe: bool,
    /// Severity 0..=7.
    pub severity: u8,
    /// Reporting unit address.
    pub unit: u8,
    /// First category-specific byte; omitted commands use 0xFF.
    pub data1: u8,
    /// Second category-specific byte; omitted commands use 0xFF.
    pub data2: u8,
}

impl ErrorReportMessage {
    /// Exact six SAL bytes excluding the point-to-multipoint envelope.
    pub fn encode(self) -> Result<Vec<u8>, EncodeError> {
        if self.category > 1023 {
            return Err(EncodeError::new("Error Reporting category is out of range"));
        }
        if self.severity > 7 {
            return Err(EncodeError::new("Error Reporting severity is out of range"));
        }
        Ok(vec![
            self.message_type,
            (self.category >> 2) as u8,
            ((self.category as u8 & 3) << 6)
                | if self.most_recent { 0x20 } else { 0 }
                | if self.acknowledged { 0x10 } else { 0 }
                | if self.most_severe { 0x08 } else { 0 }
                | self.severity,
            self.unit,
            self.data1,
            self.data2,
        ])
    }

    /// Native event type token.
    pub fn type_name(self) -> String {
        match self.message_type {
            5 => "RECENT".to_string(),
            21 => "ERROR_REPORT".to_string(),
            37 => "ACK".to_string(),
            53 => "CLEAR".to_string(),
            value => value.to_string(),
        }
    }

    /// Native C-Gate message arguments.
    pub fn event_arguments(self) -> String {
        let flag = |value| if value { 'y' } else { 'n' };
        format!(
            "{} {} {} {} {} {} {} {} {}",
            self.type_name(),
            self.category,
            flag(self.most_recent),
            flag(self.acknowledged),
            flag(self.most_severe),
            self.severity,
            self.unit,
            self.data1,
            self.data2
        )
    }
}

/// Decode one or more fixed-width Error Reporting messages.
pub fn decode_sals(data: &[u8]) -> Result<Vec<ErrorReportMessage>, DecodeError> {
    if data.is_empty() {
        return Ok(Vec::new());
    }
    if !data.len().is_multiple_of(6) {
        return Err(DecodeError::new("truncated Error Reporting message"));
    }
    data.as_chunks::<6>()
        .0
        .iter()
        .map(|bytes| {
            let flags = bytes[2];
            Ok(ErrorReportMessage {
                message_type: bytes[0],
                category: (u16::from(bytes[1]) << 2) | u16::from(flags >> 6),
                most_recent: flags & 0x20 != 0,
                acknowledged: flags & 0x10 != 0,
                most_severe: flags & 0x08 != 0,
                severity: flags & 7,
                unit: bytes[3],
                data1: bytes[4],
                data2: bytes[5],
            })
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn native_vectors_round_trip() {
        for (message, encoded) in [
            (
                ErrorReportMessage {
                    message_type: 37,
                    category: 1023,
                    most_recent: false,
                    acknowledged: false,
                    most_severe: false,
                    severity: 7,
                    unit: 255,
                    data1: 255,
                    data2: 255,
                },
                vec![0x25, 0xff, 0xc7, 0xff, 0xff, 0xff],
            ),
            (
                ErrorReportMessage {
                    message_type: 21,
                    category: 1,
                    most_recent: true,
                    acknowledged: false,
                    most_severe: true,
                    severity: 4,
                    unit: 1,
                    data1: 2,
                    data2: 255,
                },
                vec![0x15, 0x00, 0x6c, 0x01, 0x02, 0xff],
            ),
        ] {
            assert_eq!(message.encode().unwrap(), encoded);
            assert_eq!(decode_sals(&encoded).unwrap(), vec![message]);
        }
    }

    #[test]
    fn decoder_rejects_truncation() {
        assert!(decode_sals(&[0; 5]).is_err());
    }
}
