//! C-Bus Audio application ($CD) SAL commands and observations.
//!
//! The byte layouts are pinned to the retained C-Gate 3.4.0.2001 command
//! encoders and application decoder. Audio traffic is broadcast; a PCI
//! confirmation establishes delivery to the interface, not acceptance by an
//! audio unit.

use crate::{DecodeError, EncodeError};

/// Native Audio group address.
///
/// Decoded values 0..=191 carry a multiplexer, zone, and three-bit
/// command-specific function. The command grammar accepts `Z function` across
/// the full byte range, although values below 192 are indistinguishable from
/// a multiplexer/zone address when observed again.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AudioAddress {
    /// Multiplexer/zone address with the command-specific low three bits.
    Zone {
        /// Multiplexer 0..=2.
        multiplexer: u8,
        /// Zone 0..=7.
        zone: u8,
        /// Function, feed, error, or code 0..=7.
        function: u8,
    },
    /// Raw `Z` function address.
    Function(u8),
}

impl AudioAddress {
    /// Build a checked multiplexer/zone address.
    pub fn zone(multiplexer: u8, zone: u8, function: u8) -> Result<Self, EncodeError> {
        if multiplexer > 2 || zone > 7 || function > 7 {
            return Err(EncodeError::new("Audio zone address is out of range"));
        }
        Ok(Self::Zone {
            multiplexer,
            zone,
            function,
        })
    }

    fn encode(self) -> Result<u8, EncodeError> {
        match self {
            Self::Zone {
                multiplexer,
                zone,
                function,
            } if multiplexer <= 2 && zone <= 7 && function <= 7 => {
                Ok((multiplexer << 6) | (zone << 3) | function)
            }
            Self::Zone { .. } => Err(EncodeError::new("Audio zone address is out of range")),
            Self::Function(function) => Ok(function),
        }
    }

    fn encode_with(self, low: u8) -> Result<u8, EncodeError> {
        if low > 7 {
            return Err(EncodeError::new("Audio function is out of range"));
        }
        match self {
            Self::Zone {
                multiplexer, zone, ..
            } if multiplexer <= 2 && zone <= 7 => Ok((multiplexer << 6) | (zone << 3) | low),
            Self::Zone { .. } => Err(EncodeError::new("Audio zone address is out of range")),
            Self::Function(function) => Ok((function & 0xf8) | low),
        }
    }

    fn decode(raw: u8) -> Self {
        if raw <= 191 {
            Self::Zone {
                multiplexer: raw >> 6,
                zone: (raw >> 3) & 7,
                function: raw & 7,
            }
        } else {
            Self::Function(raw)
        }
    }

    fn decode_target(raw: u8) -> Self {
        match Self::decode(raw) {
            Self::Zone {
                multiplexer, zone, ..
            } => Self::Zone {
                multiplexer,
                zone,
                function: 0,
            },
            function @ Self::Function(_) => function,
        }
    }

    fn target_arguments(self) -> String {
        match self {
            Self::Zone {
                multiplexer, zone, ..
            } => format!("{multiplexer} {zone}"),
            Self::Function(function) => format!("Z {function}"),
        }
    }

    fn coded_arguments(self) -> String {
        match self {
            Self::Zone {
                multiplexer,
                zone,
                function,
            } => format!("{multiplexer} {zone} {function}"),
            Self::Function(function) => format!("Z {function}"),
        }
    }
}

/// Maintained C-Gate 3.4 Audio commands. Every command is also an inbound
/// Audio event when observed on the PCI receive stream.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum AudioCommand {
    /// Report the selected feed and gain for a zone.
    CurrentFeed {
        /// Target zone, with the feed stored in the address function bits.
        address: AudioAddress,
        /// Gain code carried by the rate nibble.
        gain: u8,
    },
    /// Request dynamic operation 1 for a zone.
    Dynamic1 {
        /// Target zone.
        address: AudioAddress,
    },
    /// Request dynamic operation 2 for a zone.
    Dynamic2 {
        /// Target zone.
        address: AudioAddress,
    },
    /// Select one feed and level using the high-priority form.
    HighPriority {
        /// Audio multiplexer 0..=2.
        multiplexer: u8,
        /// Requested output level.
        level: u8,
        /// Feed code carried by the rate nibble.
        feed: u8,
    },
    /// Change the mute mode for a zone.
    Mute {
        /// Target zone.
        address: AudioAddress,
        /// Native mute-mode byte.
        mode: u8,
    },
    /// Select the next feed for a zone.
    NextFeed {
        /// Target zone.
        address: AudioAddress,
    },
    /// Select the next language for a zone.
    NextLanguage {
        /// Target zone.
        address: AudioAddress,
    },
    /// Turn an addressed audio function off.
    Off {
        /// Zone and function code, or raw Z function.
        address: AudioAddress,
    },
    /// Turn an addressed audio function on.
    On {
        /// Zone and function code, or raw Z function.
        address: AudioAddress,
    },
    /// Broadcast an output common-control operation.
    OutputCommonControl {
        /// Native control byte; C-Gate's omitted sentinel is `0xFF`.
        control: u8,
    },
    /// Ask output devices to report status.
    OutputDeviceStatusRequest {
        /// Native parameter byte; C-Gate's omitted sentinel is `0xFF`.
        parameter: u8,
    },
    /// Broadcast one output error code.
    OutputErrorCode {
        /// Zone with the error code stored in the address function bits.
        address: AudioAddress,
    },
    /// Select the previous feed for a zone.
    PreviousFeed {
        /// Target zone.
        address: AudioAddress,
    },
    /// Ramp an addressed function to a level.
    Ramp {
        /// Zone and function code, or raw Z function.
        address: AudioAddress,
        /// Requested output level.
        level: u8,
        /// Native four-bit ramp-rate code.
        rate: u8,
    },
    /// Ask a zone to report its current feed.
    RequestCurrentFeed {
        /// Target zone.
        address: AudioAddress,
    },
    /// Select a feed for a zone.
    SetFeed {
        /// Target zone, with the feed stored in the address function bits.
        address: AudioAddress,
        /// Feed-change option carried by the rate nibble.
        option: u8,
    },
    /// Terminate a ramp on an addressed function.
    TerminateRamp {
        /// Zone and function code, or raw Z function.
        address: AudioAddress,
    },
    /// Ask a zone to report its descriptor.
    ZoneDescriptorRequest {
        /// Target zone.
        address: AudioAddress,
    },
    /// Ask a zone to report feed labels.
    ZoneFeedLabelRequest {
        /// Target zone.
        address: AudioAddress,
    },
}

/// Audio-only observations that have no command-line command.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum AudioEvent {
    /// Standard Audio label payload.
    Label {
        /// Zone and label tag number.
        address: AudioAddress,
        /// Native label options byte.
        options: u8,
        /// Native language code.
        language: u8,
        /// Uninterpreted label bytes.
        bytes: Vec<u8>,
    },
    /// Standard Audio icon payload.
    LoadIcon {
        /// Zone and icon tag number.
        address: AudioAddress,
        /// Native icon options byte.
        options: u8,
        /// Uninterpreted icon bytes.
        bytes: Vec<u8>,
    },
}

/// One decoded Audio SAL.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum AudioSal {
    /// One command that can also be observed as an event.
    Command(AudioCommand),
    /// One event-only label or icon payload.
    Event(AudioEvent),
}

impl AudioCommand {
    /// Return the lower-case native event name.
    pub fn event_name(&self) -> &'static str {
        match self {
            Self::CurrentFeed { .. } => "current_feed",
            Self::Dynamic1 { .. } => "dynamic_1",
            Self::Dynamic2 { .. } => "dynamic_2",
            Self::HighPriority { .. } => "high_priority",
            Self::Mute { .. } => "mute",
            Self::NextFeed { .. } => "next_feed",
            Self::NextLanguage { .. } => "next_language",
            Self::Off { .. } => "off",
            Self::On { .. } => "on",
            Self::OutputCommonControl { .. } => "output_common_control",
            Self::OutputDeviceStatusRequest { .. } => "output_device_status_request",
            Self::OutputErrorCode { .. } => "output_error_code",
            Self::PreviousFeed { .. } => "previous_feed",
            Self::Ramp { .. } => "ramp",
            Self::RequestCurrentFeed { .. } => "request_current_feed",
            Self::SetFeed { .. } => "set_feed",
            Self::TerminateRamp { .. } => "terminateramp",
            Self::ZoneDescriptorRequest { .. } => "zone_descriptor_request",
            Self::ZoneFeedLabelRequest { .. } => "zone_feed_label_request",
        }
    }

    /// Format positional C-Gate event arguments.
    pub fn event_arguments(&self) -> String {
        match self {
            Self::CurrentFeed { address, gain } => format!("{} {gain}", address.coded_arguments()),
            Self::Dynamic1 { address }
            | Self::Dynamic2 { address }
            | Self::NextFeed { address }
            | Self::NextLanguage { address }
            | Self::PreviousFeed { address }
            | Self::RequestCurrentFeed { address }
            | Self::ZoneDescriptorRequest { address }
            | Self::ZoneFeedLabelRequest { address } => address.target_arguments(),
            Self::HighPriority {
                multiplexer,
                level,
                feed,
            } => format!("{multiplexer} {level} {feed}"),
            Self::Mute { address, mode } => format!("{} {mode}", address.target_arguments()),
            Self::Off { address } | Self::On { address } | Self::TerminateRamp { address } => {
                address.coded_arguments()
            }
            Self::OutputCommonControl { control } => control.to_string(),
            Self::OutputDeviceStatusRequest { parameter } => parameter.to_string(),
            Self::OutputErrorCode { address } => address.coded_arguments(),
            Self::Ramp {
                address,
                level,
                rate,
            } => format!("{} {level} {rate}", address.coded_arguments()),
            Self::SetFeed { address, option } => {
                format!("{} {option}", address.coded_arguments())
            }
        }
    }

    /// Encode exact Audio SAL bytes without the application envelope.
    pub fn encode(&self) -> Result<Vec<u8>, EncodeError> {
        let three = |opcode, first, second| Ok(vec![opcode, first, second]);
        match self {
            Self::CurrentFeed { address, gain } if *gain <= 15 => {
                three((*gain << 3) | 2, 0xe8, address.encode()?)
            }
            Self::CurrentFeed { .. } => Err(EncodeError::new("Audio gain is out of range")),
            Self::Dynamic1 { address } => three(0x02, address.encode_with(6)?, 0),
            Self::Dynamic2 { address } => three(0x02, address.encode_with(6)?, 255),
            Self::HighPriority {
                multiplexer,
                level,
                feed,
            } if *multiplexer <= 2 && *feed <= 15 => {
                three((*feed << 3) | 2, 0xc0 | *multiplexer, *level)
            }
            Self::HighPriority { .. } => Err(EncodeError::new(
                "Audio high-priority value is out of range",
            )),
            Self::Mute { address, mode } => three(0x02, address.encode_with(5)?, *mode),
            Self::NextFeed { address } => three(0x02, address.encode_with(6)?, 2),
            Self::NextLanguage { address } => three(0x02, address.encode_with(6)?, 17),
            Self::Off { address } => Ok(vec![0x01, address.encode()?]),
            Self::On { address } => Ok(vec![0x79, address.encode()?]),
            Self::OutputCommonControl { control } => three(0x02, 0xe5, *control),
            Self::OutputDeviceStatusRequest { parameter } => three(0x02, 0xe3, *parameter),
            Self::OutputErrorCode { address } => three(0x02, 0xe6, address.encode()?),
            Self::PreviousFeed { address } => three(0x02, address.encode_with(6)?, 5),
            Self::Ramp {
                address,
                level,
                rate,
            } if *rate <= 15 => three((*rate << 3) | 2, address.encode()?, *level),
            Self::Ramp { .. } => Err(EncodeError::new("Audio ramp rate is out of range")),
            Self::RequestCurrentFeed { address } => three(0x02, 0xe7, address.encode_with(0)?),
            Self::SetFeed { address, option } if *option <= 15 => {
                three((*option << 3) | 2, 0xe9, address.encode()?)
            }
            Self::SetFeed { .. } => Err(EncodeError::new("Audio feed option is out of range")),
            Self::TerminateRamp { address } => Ok(vec![0x09, address.encode()?]),
            Self::ZoneDescriptorRequest { address } => three(0x02, 0xe0, address.encode_with(0)?),
            Self::ZoneFeedLabelRequest { address } => three(0x02, 0xe2, address.encode_with(0)?),
        }
    }
}

impl AudioEvent {
    /// Return the lower-case native event name.
    pub fn event_name(&self) -> &'static str {
        match self {
            Self::Label { .. } => "label",
            Self::LoadIcon { .. } => "load_icon",
        }
    }

    /// Format positional C-Gate event arguments.
    pub fn event_arguments(&self) -> String {
        match self {
            Self::Label {
                address,
                options,
                language,
                bytes,
            } => format!(
                "{} {} {} {} {}",
                address.coded_arguments(),
                (options & 6) >> 1,
                (options & 0x60) >> 5,
                language,
                hex::encode_upper(bytes)
            ),
            Self::LoadIcon {
                address,
                options,
                bytes,
            } => format!(
                "{} {options} {} {}",
                address.coded_arguments(),
                (options & 0x60) >> 5,
                hex::encode_upper(bytes)
            ),
        }
    }

    /// Encode the intended standard A0 label/icon layout.
    pub fn encode(&self) -> Result<Vec<u8>, EncodeError> {
        let (address, options, language, bytes) = match self {
            Self::Label {
                address,
                options,
                language,
                bytes,
            } => (*address, *options, Some(*language), bytes),
            Self::LoadIcon {
                address,
                options,
                bytes,
            } => (*address, *options, None, bytes),
        };
        if !matches!(address, AudioAddress::Zone { .. }) {
            return Err(EncodeError::new(
                "Audio labels require a multiplexer address",
            ));
        }
        let load_icon = (options & 6) >> 1 == 2;
        if load_icon != language.is_none() {
            return Err(EncodeError::new(
                "Audio label type does not match the event kind",
            ));
        }
        let header = if language.is_some() { 3 } else { 2 };
        if bytes.len() + header > 31 {
            return Err(EncodeError::new("Audio label payload is too long"));
        }
        let mut payload = vec![
            0xa0 | (bytes.len() + header) as u8,
            address.encode()?,
            options,
        ];
        if let Some(language) = language {
            payload.push(language);
        }
        payload.extend_from_slice(bytes);
        Ok(payload)
    }
}

/// Decode one or more Audio SAL commands.
pub fn decode_sals(mut data: &[u8]) -> Result<Vec<AudioSal>, DecodeError> {
    let mut result = Vec::new();
    while !data.is_empty() {
        let len = match data[0] {
            0x01 | 0x09 | 0x79 => 2,
            opcode if (opcode & 0xe0) == 0xa0 => usize::from(opcode & 0x1f) + 1,
            opcode if opcode & 0x87 == 0x02 => 3,
            opcode => {
                return Err(DecodeError::new(format!(
                    "unknown Audio SAL prefix 0x{opcode:02x}"
                )))
            }
        };
        if data.len() < len {
            return Err(DecodeError::new("truncated Audio SAL"));
        }
        result.push(decode_one(&data[..len])?);
        data = &data[len..];
    }
    Ok(result)
}

fn decode_one(bytes: &[u8]) -> Result<AudioSal, DecodeError> {
    let opcode = bytes[0];
    if matches!(opcode, 0x01 | 0x09 | 0x79) {
        let address = AudioAddress::decode(bytes[1]);
        let command = match opcode {
            0x01 => AudioCommand::Off { address },
            0x09 => AudioCommand::TerminateRamp { address },
            0x79 => AudioCommand::On { address },
            _ => unreachable!(),
        };
        return Ok(AudioSal::Command(command));
    }
    if opcode & 0xe0 == 0xa0 {
        if usize::from(opcode & 0x1f) + 1 != bytes.len() || bytes.len() < 3 {
            return Err(DecodeError::new("invalid Audio label SAL length"));
        }
        let address = AudioAddress::decode(bytes[1]);
        if !matches!(address, AudioAddress::Zone { .. }) {
            return Err(DecodeError::new("Audio label has a Z function address"));
        }
        let options = bytes[2];
        return if (options & 6) >> 1 == 2 {
            Ok(AudioSal::Event(AudioEvent::LoadIcon {
                address,
                options,
                bytes: bytes[3..].to_vec(),
            }))
        } else if bytes.len() >= 4 {
            Ok(AudioSal::Event(AudioEvent::Label {
                address,
                options,
                language: bytes[3],
                bytes: bytes[4..].to_vec(),
            }))
        } else {
            Err(DecodeError::new("Audio label SAL has no language byte"))
        };
    }

    let first = bytes[1];
    let second = bytes[2];
    if opcode == 0x02 {
        let command = match first {
            0xe0 => AudioCommand::ZoneDescriptorRequest {
                address: AudioAddress::decode(second),
            },
            0xe2 => AudioCommand::ZoneFeedLabelRequest {
                address: AudioAddress::decode(second),
            },
            0xe3 => AudioCommand::OutputDeviceStatusRequest { parameter: second },
            0xe5 => AudioCommand::OutputCommonControl { control: second },
            0xe6 => {
                let address = AudioAddress::decode(second);
                if !matches!(address, AudioAddress::Zone { .. }) {
                    return Err(DecodeError::new(
                        "Audio error code has a Z function address",
                    ));
                }
                AudioCommand::OutputErrorCode { address }
            }
            0xe7 => AudioCommand::RequestCurrentFeed {
                address: AudioAddress::decode(second),
            },
            value if value & 7 == 5 => AudioCommand::Mute {
                address: AudioAddress::decode_target(value),
                mode: second,
            },
            value if value & 7 == 6 => {
                let address = AudioAddress::decode_target(value);
                match second {
                    0 => AudioCommand::Dynamic1 { address },
                    2 => AudioCommand::NextFeed { address },
                    5 => AudioCommand::PreviousFeed { address },
                    17 => AudioCommand::NextLanguage { address },
                    255 => AudioCommand::Dynamic2 { address },
                    _ => return Err(DecodeError::new("unknown Audio dynamic operation")),
                }
            }
            _ => return decode_rate_command(opcode, first, second),
        };
        return Ok(AudioSal::Command(command));
    }
    decode_rate_command(opcode, first, second)
}

fn decode_rate_command(opcode: u8, first: u8, second: u8) -> Result<AudioSal, DecodeError> {
    if opcode & 0x87 != 0x02 {
        return Err(DecodeError::new("unknown Audio SAL command"));
    }
    let rate = (opcode & 0x78) >> 3;
    let command = match first {
        0..=191 => AudioCommand::Ramp {
            address: AudioAddress::decode(first),
            level: second,
            rate,
        },
        192..=194 => AudioCommand::HighPriority {
            multiplexer: first & 3,
            level: second,
            feed: rate,
        },
        232 => AudioCommand::CurrentFeed {
            address: AudioAddress::decode(second),
            gain: rate,
        },
        233 => AudioCommand::SetFeed {
            address: AudioAddress::decode(second),
            option: rate,
        },
        _ => return Err(DecodeError::new("unknown Audio rate-family command")),
    };
    Ok(AudioSal::Command(command))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn zone(multiplexer: u8, zone: u8, function: u8) -> AudioAddress {
        AudioAddress::zone(multiplexer, zone, function).unwrap()
    }

    #[test]
    fn exact_native_command_layouts_round_trip() {
        let cases = [
            (
                AudioCommand::On {
                    address: zone(1, 2, 4),
                },
                "7954",
            ),
            (
                AudioCommand::Off {
                    address: zone(1, 2, 4),
                },
                "0154",
            ),
            (
                AudioCommand::TerminateRamp {
                    address: zone(1, 2, 4),
                },
                "0954",
            ),
            (
                AudioCommand::Ramp {
                    address: zone(1, 2, 4),
                    level: 123,
                    rate: 15,
                },
                "7a547b",
            ),
            (
                AudioCommand::Dynamic1 {
                    address: zone(1, 2, 0),
                },
                "025600",
            ),
            (
                AudioCommand::Dynamic2 {
                    address: zone(1, 2, 0),
                },
                "0256ff",
            ),
            (
                AudioCommand::NextFeed {
                    address: zone(1, 2, 0),
                },
                "025602",
            ),
            (
                AudioCommand::PreviousFeed {
                    address: zone(1, 2, 0),
                },
                "025605",
            ),
            (
                AudioCommand::NextLanguage {
                    address: zone(1, 2, 0),
                },
                "025611",
            ),
            (
                AudioCommand::Mute {
                    address: zone(1, 2, 0),
                    mode: 255,
                },
                "0255ff",
            ),
            (
                AudioCommand::HighPriority {
                    multiplexer: 2,
                    level: 99,
                    feed: 7,
                },
                "3ac263",
            ),
            (
                AudioCommand::ZoneDescriptorRequest {
                    address: zone(1, 2, 0),
                },
                "02e050",
            ),
            (
                AudioCommand::ZoneFeedLabelRequest {
                    address: zone(1, 2, 0),
                },
                "02e250",
            ),
            (
                AudioCommand::OutputDeviceStatusRequest { parameter: 0 },
                "02e300",
            ),
            (AudioCommand::OutputCommonControl { control: 0 }, "02e500"),
            (
                AudioCommand::OutputErrorCode {
                    address: zone(1, 2, 1),
                },
                "02e651",
            ),
            (
                AudioCommand::RequestCurrentFeed {
                    address: zone(1, 2, 0),
                },
                "02e750",
            ),
            (
                AudioCommand::CurrentFeed {
                    address: zone(1, 2, 4),
                    gain: 4,
                },
                "22e854",
            ),
            (
                AudioCommand::SetFeed {
                    address: zone(1, 2, 4),
                    option: 1,
                },
                "0ae954",
            ),
        ];
        for (command, expected) in cases {
            let expected_name = command.event_name();
            let encoded = command.encode().unwrap();
            assert_eq!(hex::encode(&encoded), expected);
            let decoded = decode_sals(&encoded).unwrap();
            let AudioSal::Command(decoded) = &decoded[0] else {
                panic!("command decoded as event")
            };
            assert_eq!(decoded.event_name(), expected_name);
            assert_eq!(decoded, &command);
            assert_eq!(decoded.encode().unwrap(), encoded);
        }
    }

    #[test]
    fn z_address_transform_matches_native_decoder() {
        let command = AudioCommand::Dynamic1 {
            address: AudioAddress::Function(192),
        };
        let encoded = command.encode().unwrap();
        assert_eq!(hex::encode(&encoded), "02c600");
        assert_eq!(
            decode_sals(&encoded).unwrap(),
            vec![AudioSal::Command(AudioCommand::Dynamic1 {
                address: AudioAddress::Function(198)
            })]
        );
    }

    #[test]
    fn label_and_load_icon_follow_native_audio_split() {
        let label = hex::decode("a74c200145444c54").unwrap();
        assert_eq!(
            decode_sals(&label).unwrap(),
            vec![AudioSal::Event(AudioEvent::Label {
                address: zone(1, 1, 4),
                options: 0x20,
                language: 1,
                bytes: b"EDLT".to_vec(),
            })]
        );
        let icon = hex::decode("a54c44010203").unwrap();
        assert_eq!(
            decode_sals(&icon).unwrap(),
            vec![AudioSal::Event(AudioEvent::LoadIcon {
                address: zone(1, 1, 4),
                options: 0x44,
                bytes: vec![1, 2, 3],
            })]
        );

        let empty_icon = AudioEvent::LoadIcon {
            address: zone(1, 1, 4),
            options: 0x04,
            bytes: Vec::new(),
        };
        assert_eq!(empty_icon.encode().unwrap(), hex::decode("a24c04").unwrap());
        assert_eq!(
            decode_sals(&empty_icon.encode().unwrap()).unwrap(),
            vec![AudioSal::Event(empty_icon)]
        );
        assert!(AudioEvent::Label {
            address: zone(1, 1, 4),
            options: 0x04,
            language: 1,
            bytes: Vec::new(),
        }
        .encode()
        .is_err());
    }

    #[test]
    fn malformed_or_unrepresentable_audio_payloads_fail_closed() {
        assert!(AudioAddress::zone(3, 0, 0).is_err());
        assert!(AudioAddress::zone(0, 8, 0).is_err());
        assert!(AudioAddress::zone(0, 0, 8).is_err());
        assert!(AudioCommand::CurrentFeed {
            address: zone(0, 0, 0),
            gain: 16,
        }
        .encode()
        .is_err());
        assert!(AudioCommand::HighPriority {
            multiplexer: 0,
            level: 0,
            feed: 16,
        }
        .encode()
        .is_err());
        assert!(AudioCommand::Ramp {
            address: zone(0, 0, 0),
            level: 0,
            rate: 16,
        }
        .encode()
        .is_err());
        assert!(AudioCommand::SetFeed {
            address: zone(0, 0, 0),
            option: 16,
        }
        .encode()
        .is_err());

        assert!(decode_sals(&[0x02, 0xe6, 0xc0]).is_err());
        assert!(decode_sals(&[0x02, 0xc3, 0]).is_err());
        assert!(decode_sals(&[0xc3, 0, 0, 0]).is_err());
        assert!(decode_sals(&[0xa3, 0, 0]).is_err());
    }
}
