//! Telephony application SAL commands and device events implemented by C-Gate 3.4.
//!
//! The application address, command payloads, length-code handling and event
//! names are pinned to an isolated C-Gate 3.4.0.2001 instance and its retained
//! decoder. Commands are broadcasts: PCI confirmation proves interface
//! delivery, not acceptance by a telephony unit.

use crate::{DecodeError, EncodeError};

/// Direction used by last-number messages.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TelephonyDirection {
    /// Outgoing call.
    Out,
    /// Incoming call.
    In,
}

impl TelephonyDirection {
    /// Native direction byte.
    pub fn value(self) -> u8 {
        match self {
            Self::Out => 1,
            Self::In => 2,
        }
    }

    /// Native lower-case event/command name.
    pub fn name(self) -> &'static str {
        match self {
            Self::Out => "out",
            Self::In => "in",
        }
    }

    fn decode(value: u8) -> Result<Self, DecodeError> {
        match value {
            1 => Ok(Self::Out),
            2 => Ok(Self::In),
            _ => Err(DecodeError::new("Telephony direction is out of range")),
        }
    }
}

/// Reason for taking a telephone line off hook.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum OffHookReason {
    /// Voice call.
    Voice,
    /// Data call.
    Data,
    /// Other call type.
    Other,
}

impl OffHookReason {
    /// Native lower-case event name.
    pub fn name(self) -> &'static str {
        match self {
            Self::Voice => "voice",
            Self::Data => "data",
            Self::Other => "other",
        }
    }

    fn decode(value: u8) -> Result<(TelephonyDirection, Self), DecodeError> {
        let (direction, reason) = if value >= 16 {
            (TelephonyDirection::Out, value >> 4)
        } else {
            (TelephonyDirection::In, value)
        };
        let reason = match reason {
            1 => Self::Voice,
            2 => Self::Data,
            3 => Self::Other,
            _ => {
                return Err(DecodeError::new(
                    "Telephony off-hook reason is out of range",
                ))
            }
        };
        Ok((direction, reason))
    }
}

/// Outgoing-call failure reported by a telephony unit.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DialFailure {
    /// No dial tone was detected.
    NoDialtone,
    /// The remote endpoint did not answer.
    NoAnswer,
    /// No acknowledgement prompt was detected.
    NoAckPrompt,
    /// The number was unobtainable.
    Unobtainable,
    /// The destination was busy.
    Busy,
}

impl DialFailure {
    /// Native lower-case event name.
    pub fn name(self) -> &'static str {
        match self {
            Self::NoDialtone => "no_dialtone",
            Self::NoAnswer => "no_answer",
            Self::NoAckPrompt => "no_ack_prompt",
            Self::Unobtainable => "unobtainable",
            Self::Busy => "busy",
        }
    }

    fn decode(value: u8) -> Result<Self, DecodeError> {
        match value {
            1 => Ok(Self::NoDialtone),
            2 => Ok(Self::NoAnswer),
            3 => Ok(Self::NoAckPrompt),
            4 => Ok(Self::Unobtainable),
            5 => Ok(Self::Busy),
            _ => Err(DecodeError::new("Telephony dial failure is out of range")),
        }
    }
}

/// Public native C-Gate TELEPHONY command payload.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum TelephonyCommand {
    /// Clear an existing diversion.
    ClearDiversion,
    /// Divert to one byte-oriented number token.
    Divert {
        /// Bytes placed after opcode `0x83` (one through sixteen bytes).
        number: Vec<u8>,
        /// Length C-Gate declares in the SAL prefix. It normally equals
        /// `number.len()`, but is retained separately to reproduce C-Gate's
        /// captured malformed non-ASCII encoding bug.
        declared_length: u8,
    },
    /// Change the secondary-outlet isolation mode.
    IsolateSecondaryOutlet {
        /// `true` isolates the outlet; `false` returns it to normal.
        isolated: bool,
    },
    /// Request the last incoming or outgoing number.
    RecallLastNumberRequest {
        /// Requested direction.
        direction: TelephonyDirection,
    },
    /// Reject the current incoming call.
    RejectIncomingCall,
}

impl TelephonyCommand {
    /// Construct a canonical diversion whose declared length equals its bytes.
    pub fn divert(number: Vec<u8>) -> Result<Self, EncodeError> {
        let declared_length = u8::try_from(number.len())
            .map_err(|_| EncodeError::new("Telephony diversion number is too long"))?;
        let command = Self::Divert {
            number,
            declared_length,
        };
        command.validate()?;
        Ok(command)
    }

    /// Native lower-case C-Gate event name.
    pub fn event_name(&self) -> &'static str {
        match self {
            Self::ClearDiversion => "clear_diversion",
            Self::Divert { .. } => "divert",
            Self::IsolateSecondaryOutlet { .. } => "isolate_secondary_outlet",
            Self::RecallLastNumberRequest { .. } => "recall_last_number_request",
            Self::RejectIncomingCall => "reject_incoming_call",
        }
    }

    /// Native C-Gate event arguments for an observed command.
    pub fn event_arguments(&self) -> String {
        match self {
            Self::ClearDiversion | Self::RejectIncomingCall => String::new(),
            Self::Divert { number, .. } => bytes_to_native_string(number),
            Self::IsolateSecondaryOutlet { isolated } => {
                if *isolated { "isolate" } else { "normal" }.to_owned()
            }
            Self::RecallLastNumberRequest { direction } => direction.name().to_owned(),
        }
    }

    /// Exact SAL bytes excluding the point-to-multipoint envelope.
    pub fn encode(&self) -> Result<Vec<u8>, EncodeError> {
        self.validate()?;
        match self {
            Self::ClearDiversion => Ok(vec![0x09, 0x84]),
            Self::Divert {
                number,
                declared_length,
            } => {
                let mut out = Vec::with_capacity(number.len() + 2);
                out.push(0xa1 + *declared_length);
                out.push(0x83);
                out.extend_from_slice(number);
                Ok(out)
            }
            Self::IsolateSecondaryOutlet { isolated } => Ok(vec![0x0a, 0x80, u8::from(*isolated)]),
            Self::RecallLastNumberRequest { direction } => Ok(vec![0x0a, 0x81, direction.value()]),
            Self::RejectIncomingCall => Ok(vec![0x09, 0x82]),
        }
    }

    fn validate(&self) -> Result<(), EncodeError> {
        if let Self::Divert {
            number,
            declared_length,
        } = self
        {
            if number.is_empty() || number.len() > 16 {
                return Err(EncodeError::new(
                    "Telephony diversion number must contain 1..=16 bytes",
                ));
            }
            if !(1..=16).contains(declared_length) {
                return Err(EncodeError::new(
                    "Telephony diversion declared length must be 1..=16",
                ));
            }
        }
        Ok(())
    }
}

/// Telephony device event recognized by native C-Gate 3.4.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum TelephonyEvent {
    /// The telephone line went on hook.
    LineOnHook,
    /// The telephone line went off hook.
    LineOffHook {
        /// Incoming or outgoing call.
        direction: TelephonyDirection,
        /// Voice, data, or other call reason.
        reason: OffHookReason,
        /// Optional byte-oriented number.
        number: Vec<u8>,
    },
    /// An outgoing call failed.
    DialOutFailure {
        /// Failure reason.
        reason: DialFailure,
    },
    /// An incoming call failed because it was not answered.
    DialInFailure,
    /// A call is ringing.
    Ringing {
        /// Native qualifier byte, ignored by C-Gate's event text.
        qualifier: Option<u8>,
        /// Optional byte-oriented calling number.
        number: Vec<u8>,
    },
    /// Last-number response.
    LastNumber {
        /// Incoming or outgoing number.
        direction: TelephonyDirection,
        /// Optional byte-oriented number.
        number: Vec<u8>,
    },
    /// A unit requested an Internet connection.
    InternetConnectionRequestMade,
}

impl TelephonyEvent {
    /// Native lower-case C-Gate event name.
    pub fn event_name(&self) -> &'static str {
        match self {
            Self::LineOnHook => "line_on_hook",
            Self::LineOffHook { .. } => "line_off_hook",
            Self::DialOutFailure { .. } => "dial_out_failure",
            Self::DialInFailure => "dial_in_failure",
            Self::Ringing { .. } => "ringing",
            Self::LastNumber { .. } => "last_number",
            Self::InternetConnectionRequestMade => "internet_connection_request_made",
        }
    }

    /// Native C-Gate event arguments.
    pub fn event_arguments(&self) -> String {
        match self {
            Self::LineOnHook | Self::InternetConnectionRequestMade => String::new(),
            Self::LineOffHook {
                direction,
                reason,
                number,
            } => join_number(&format!("{} {}", direction.name(), reason.name()), number),
            Self::DialOutFailure { reason } => reason.name().to_owned(),
            Self::DialInFailure => "no_answer".to_owned(),
            Self::Ringing { number, .. } => bytes_to_native_string(number),
            Self::LastNumber { direction, number } => join_number(direction.name(), number),
        }
    }

    /// Canonical Telephony device-event SAL bytes.
    pub fn encode(&self) -> Result<Vec<u8>, EncodeError> {
        let (opcode, mut arguments) = match self {
            Self::LineOnHook => (0x01, Vec::new()),
            Self::LineOffHook {
                direction,
                reason,
                number,
            } => {
                let reason = match reason {
                    OffHookReason::Voice => 1,
                    OffHookReason::Data => 2,
                    OffHookReason::Other => 3,
                };
                let reason = match direction {
                    TelephonyDirection::In => reason,
                    TelephonyDirection::Out => reason << 4,
                };
                let mut arguments = vec![reason];
                arguments.extend_from_slice(number);
                (0x02, arguments)
            }
            Self::DialOutFailure { reason } => {
                let reason = match reason {
                    DialFailure::NoDialtone => 1,
                    DialFailure::NoAnswer => 2,
                    DialFailure::NoAckPrompt => 3,
                    DialFailure::Unobtainable => 4,
                    DialFailure::Busy => 5,
                };
                (0x03, vec![reason])
            }
            Self::DialInFailure => (0x04, Vec::new()),
            Self::Ringing { qualifier, number } => {
                let mut arguments = qualifier.iter().copied().collect::<Vec<_>>();
                arguments.extend_from_slice(number);
                (0x05, arguments)
            }
            Self::LastNumber { direction, number } => {
                let mut arguments = vec![direction.value()];
                arguments.extend_from_slice(number);
                (0x06, arguments)
            }
            Self::InternetConnectionRequestMade => (0x07, Vec::new()),
        };
        let length = arguments.len() + 1;
        let prefix = sal_length_prefix(length)?;
        let mut out = Vec::with_capacity(length + 1);
        out.push(prefix);
        out.push(opcode);
        out.append(&mut arguments);
        Ok(out)
    }
}

/// A decoded Telephony SAL classified as a command or device event.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum TelephonySal {
    /// Command observed on the shared network.
    Command(TelephonyCommand),
    /// Device event observed on the shared network.
    Event(TelephonyEvent),
}

/// Decode one or more Telephony SAL messages.
pub fn decode_sals(mut data: &[u8]) -> Result<Vec<TelephonySal>, DecodeError> {
    let mut messages = Vec::new();
    while !data.is_empty() {
        let Some(prefix) = data.first().copied() else {
            break;
        };
        let encoded_length = if prefix & 0x80 != 0 {
            usize::from(prefix & 0x1f)
        } else {
            usize::from(prefix & 0x07)
        };
        if encoded_length == 0 {
            return Err(DecodeError::new("invalid Telephony SAL length"));
        }
        let total = encoded_length + 1;
        if data.len() < total {
            return Err(DecodeError::new("truncated Telephony SAL"));
        }
        messages.push(decode_one(&data[..total])?);
        data = &data[total..];
    }
    Ok(messages)
}

fn decode_one(bytes: &[u8]) -> Result<TelephonySal, DecodeError> {
    let opcode = bytes[1];
    let arguments = &bytes[2..];
    let command = match (opcode, arguments) {
        (0x80, [mode]) if matches!(mode, 0 | 1) => Some(TelephonyCommand::IsolateSecondaryOutlet {
            isolated: *mode == 1,
        }),
        (0x81, [direction]) => Some(TelephonyCommand::RecallLastNumberRequest {
            direction: TelephonyDirection::decode(*direction)?,
        }),
        (0x82, []) => Some(TelephonyCommand::RejectIncomingCall),
        (0x83, number @ [_, ..]) if number.len() <= 16 => Some(TelephonyCommand::Divert {
            number: number.to_vec(),
            declared_length: number.len() as u8,
        }),
        (0x84, []) => Some(TelephonyCommand::ClearDiversion),
        _ => None,
    };
    if let Some(command) = command {
        return Ok(TelephonySal::Command(command));
    }
    let event = match opcode {
        0x01 if arguments.is_empty() => TelephonyEvent::LineOnHook,
        0x02 if !arguments.is_empty() => {
            let (direction, reason) = OffHookReason::decode(arguments[0])?;
            TelephonyEvent::LineOffHook {
                direction,
                reason,
                number: arguments[1..].to_vec(),
            }
        }
        0x03 if arguments.len() == 1 => TelephonyEvent::DialOutFailure {
            reason: DialFailure::decode(arguments[0])?,
        },
        0x04 if arguments.is_empty() => TelephonyEvent::DialInFailure,
        0x05 => TelephonyEvent::Ringing {
            qualifier: arguments.first().copied(),
            number: arguments.get(1..).unwrap_or_default().to_vec(),
        },
        0x06 if !arguments.is_empty() => TelephonyEvent::LastNumber {
            direction: TelephonyDirection::decode(arguments[0])?,
            number: arguments[1..].to_vec(),
        },
        0x07 if arguments.is_empty() => TelephonyEvent::InternetConnectionRequestMade,
        _ => {
            return Err(DecodeError::new(format!(
                "unknown or invalid Telephony SAL opcode 0x{opcode:02x}"
            )))
        }
    };
    Ok(TelephonySal::Event(event))
}

fn bytes_to_native_string(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| char::from(*byte)).collect()
}

fn join_number(prefix: &str, number: &[u8]) -> String {
    match number.len() {
        0 => prefix.to_owned(),
        // Retain C-Gate 3.4's observed/decompiled one-byte formatting bug:
        // it inserts a separator only when the decoded number is longer than
        // one character, so a single digit is concatenated to the preceding
        // direction/reason token.
        1 => format!("{prefix}{}", bytes_to_native_string(number)),
        _ => format!("{prefix} {}", bytes_to_native_string(number)),
    }
}

fn sal_length_prefix(length: usize) -> Result<u8, EncodeError> {
    match length {
        1..=7 => Ok(0x08 + length as u8),
        8..=31 => Ok(0xa0 + length as u8),
        _ => Err(EncodeError::new("Telephony SAL payload is too long")),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn captured_commands_round_trip() {
        let cases = [
            (TelephonyCommand::ClearDiversion, vec![0x09, 0x84]),
            (TelephonyCommand::RejectIncomingCall, vec![0x09, 0x82]),
            (
                TelephonyCommand::IsolateSecondaryOutlet { isolated: true },
                vec![0x0a, 0x80, 1],
            ),
            (
                TelephonyCommand::RecallLastNumberRequest {
                    direction: TelephonyDirection::In,
                },
                vec![0x0a, 0x81, 2],
            ),
            (
                TelephonyCommand::divert(b"1234567890123456".to_vec()).unwrap(),
                [vec![0xb1, 0x83], b"1234567890123456".to_vec()].concat(),
            ),
        ];
        for (command, bytes) in cases {
            assert_eq!(command.encode().unwrap(), bytes);
            assert_eq!(
                decode_sals(&bytes).unwrap(),
                vec![TelephonySal::Command(command)]
            );
        }
    }

    #[test]
    fn captured_device_events_decode() {
        let bytes = [
            0x09, 0x01, 0x0a, 0x02, 0x01, 0x0a, 0x03, 5, 0x09, 0x04, 0x0c, 0x05, 0, b'1', b'2',
            0x0c, 0x06, 1, b'3', b'4', 0x09, 0x07,
        ];
        let decoded = decode_sals(&bytes).unwrap();
        assert_eq!(decoded.len(), 7);
        assert_eq!(
            decoded[1],
            TelephonySal::Event(TelephonyEvent::LineOffHook {
                direction: TelephonyDirection::In,
                reason: OffHookReason::Voice,
                number: Vec::new(),
            })
        );
        assert_eq!(
            decoded[4],
            TelephonySal::Event(TelephonyEvent::Ringing {
                qualifier: Some(0),
                number: b"12".to_vec(),
            })
        );
        assert_eq!(
            TelephonyEvent::LineOffHook {
                direction: TelephonyDirection::Out,
                reason: OffHookReason::Data,
                number: b"1".to_vec(),
            }
            .event_arguments(),
            "out data1"
        );
        assert_eq!(
            TelephonyEvent::LastNumber {
                direction: TelephonyDirection::In,
                number: b"1".to_vec(),
            }
            .event_arguments(),
            "in1"
        );
    }

    #[test]
    fn malformed_forms_fail_closed_and_native_unicode_bug_can_be_reproduced() {
        for bytes in [
            &[0x08, 0x84][..],
            &[0x0a, 0x80][..],
            &[0x0a, 0x80, 2][..],
            &[0x0a, 0x81, 3][..],
            &[0xa1, 0x83][..],
        ] {
            assert!(decode_sals(bytes).is_err(), "{bytes:02X?}");
        }
        let native_bug = TelephonyCommand::Divert {
            number: vec![0xff, 0xff],
            declared_length: 1,
        };
        assert_eq!(native_bug.encode().unwrap(), vec![0xa2, 0x83, 0xff, 0xff]);
        assert!(decode_sals(&native_bug.encode().unwrap()).is_err());
    }
}
