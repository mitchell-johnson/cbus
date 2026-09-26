//! Media Transport application SAL commands and reports implemented by C-Gate 3.4.
//!
//! Media Transport uses application 0xC0.  Every public C-Gate command is
//! also a valid observation on the shared bus, so this module deliberately
//! models one lossless message enum for both directions.

use crate::{DecodeError, EncodeError};

/// One native C-Gate Media Transport message.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum MediaTransportMessage {
    /// Stop playback for a media-link group.
    Stop {
        /// Media-link group.
        group: u8,
    },
    /// Start playback for a media-link group.
    Play {
        /// Media-link group.
        group: u8,
    },
    /// Pause or resume playback (operation 0 or 255).
    Pause {
        /// Media-link group.
        group: u8,
        /// Native operation value.
        operation: u8,
    },
    /// Select a category (0..=127).
    SetCategory {
        /// Media-link group.
        group: u8,
        /// Category number.
        category: u8,
    },
    /// Select a selection (0..=32767).
    SetSelection {
        /// Media-link group.
        group: u8,
        /// Selection number.
        selection: u16,
    },
    /// Select a track (0..=2147483647).
    SetTrack {
        /// Media-link group.
        group: u8,
        /// Track number.
        track: u32,
    },
    /// Disable or enable shuffle (operation 0 or 255).
    Shuffle {
        /// Media-link group.
        group: u8,
        /// Native operation value.
        operation: u8,
    },
    /// Set the repeat modifier.
    Repeat {
        /// Media-link group.
        group: u8,
        /// Native operation value.
        operation: u8,
    },
    /// Select the preceding or following category.
    NextCategory {
        /// Media-link group.
        group: u8,
        /// Native operation value.
        operation: u8,
    },
    /// Select the preceding or following selection.
    NextSelection {
        /// Media-link group.
        group: u8,
        /// Native operation value.
        operation: u8,
    },
    /// Select the preceding or following track.
    NextTrack {
        /// Media-link group.
        group: u8,
        /// Native operation value.
        operation: u8,
    },
    /// Fast-forward at a native supported rate.
    Forward {
        /// Media-link group.
        group: u8,
        /// Native speed value.
        operation: u8,
    },
    /// Rewind at a native supported rate.
    Rewind {
        /// Media-link group.
        group: u8,
        /// Native speed value.
        operation: u8,
    },
    /// Set source power state.
    SourcePower {
        /// Media-link group.
        group: u8,
        /// Native operation value.
        operation: u8,
    },
    /// Report the total number of tracks.
    TotalTracks {
        /// Media-link group.
        group: u8,
        /// Track count.
        tracks: u32,
    },
    /// Request current output status.
    StatusRequest {
        /// Media-link group.
        group: u8,
    },
    /// Request an enumeration page.
    Enumerate {
        /// Media-link group.
        group: u8,
        /// Enumeration kind (category, selection, or track).
        enumeration_type: u8,
        /// First entry requested.
        start: u8,
    },
    /// Report the size of an enumeration page.
    EnumerationSize {
        /// Media-link group.
        group: u8,
        /// Enumeration kind (category, selection, or track).
        enumeration_type: u8,
        /// First entry in this page.
        start: u8,
        /// Number of entries in this page.
        size: u8,
    },
    /// Report a track-name fragment.
    TrackName {
        /// Media-link group.
        group: u8,
        /// Which-name-identification code.
        wni: u8,
        /// Native two-bit total-packets field.
        total: u8,
        /// Native two-bit packet index.
        index: u8,
        /// Raw name-fragment bytes.
        text: Vec<u8>,
    },
    /// Report a selection-name fragment.
    SelectionName {
        /// Media-link group.
        group: u8,
        /// Which-name-identification code.
        wni: u8,
        /// Native two-bit total-packets field.
        total: u8,
        /// Native two-bit packet index.
        index: u8,
        /// Raw name-fragment bytes.
        text: Vec<u8>,
    },
    /// Report a category-name fragment.
    CategoryName {
        /// Media-link group.
        group: u8,
        /// Which-name-identification code.
        wni: u8,
        /// Native two-bit total-packets field.
        total: u8,
        /// Native two-bit packet index.
        index: u8,
        /// Raw name-fragment bytes.
        text: Vec<u8>,
    },
}

impl MediaTransportMessage {
    /// Return the lower-case native C-Gate event name.
    pub fn event_name(&self) -> &'static str {
        match self {
            Self::Stop { .. } => "stop",
            Self::Play { .. } => "play",
            Self::Pause { .. } => "pause",
            Self::SetCategory { .. } => "set_category",
            Self::SetSelection { .. } => "set_selection",
            Self::SetTrack { .. } => "set_track",
            Self::Shuffle { .. } => "shuffle",
            Self::Repeat { .. } => "repeat",
            Self::NextCategory { .. } => "next_category",
            Self::NextSelection { .. } => "next_selection",
            Self::NextTrack { .. } => "next_track",
            Self::Forward { .. } => "forward",
            Self::Rewind { .. } => "rewind",
            Self::SourcePower { .. } => "source_power",
            Self::TotalTracks { .. } => "total_tracks",
            Self::StatusRequest { .. } => "status_request",
            Self::Enumerate { .. } => "enumerate",
            Self::EnumerationSize { .. } => "enumeration_size",
            Self::TrackName { .. } => "track_name",
            Self::SelectionName { .. } => "selection_name",
            Self::CategoryName { .. } => "category_name",
        }
    }

    /// Return the addressed media-link group.
    pub fn group(&self) -> u8 {
        match self {
            Self::Stop { group }
            | Self::Play { group }
            | Self::Pause { group, .. }
            | Self::SetCategory { group, .. }
            | Self::SetSelection { group, .. }
            | Self::SetTrack { group, .. }
            | Self::Shuffle { group, .. }
            | Self::Repeat { group, .. }
            | Self::NextCategory { group, .. }
            | Self::NextSelection { group, .. }
            | Self::NextTrack { group, .. }
            | Self::Forward { group, .. }
            | Self::Rewind { group, .. }
            | Self::SourcePower { group, .. }
            | Self::TotalTracks { group, .. }
            | Self::StatusRequest { group }
            | Self::Enumerate { group, .. }
            | Self::EnumerationSize { group, .. }
            | Self::TrackName { group, .. }
            | Self::SelectionName { group, .. }
            | Self::CategoryName { group, .. } => *group,
        }
    }

    /// Format native C-Gate event arguments.
    pub fn event_arguments(&self) -> String {
        let group = self.group();
        match self {
            Self::Stop { .. } | Self::Play { .. } | Self::StatusRequest { .. } => {
                format!("group={group}")
            }
            Self::Pause { operation, .. }
            | Self::Shuffle { operation, .. }
            | Self::Repeat { operation, .. }
            | Self::NextCategory { operation, .. }
            | Self::NextSelection { operation, .. }
            | Self::NextTrack { operation, .. }
            | Self::Forward { operation, .. }
            | Self::Rewind { operation, .. }
            | Self::SourcePower { operation, .. } => {
                format!("group={group} operation={operation}")
            }
            Self::SetCategory { category, .. } => format!("group={group} category={category}"),
            Self::SetSelection { selection, .. } => {
                format!("group={group} selection={selection}")
            }
            Self::SetTrack { track, .. } => format!("group={group} track={track}"),
            Self::TotalTracks { tracks, .. } => format!("group={group} tracks={tracks}"),
            Self::Enumerate {
                enumeration_type,
                start,
                ..
            } => format!("group={group} type={enumeration_type} start={start}"),
            Self::EnumerationSize {
                enumeration_type,
                start,
                size,
                ..
            } => format!("group={group} type={enumeration_type} start={start} size={size}"),
            Self::TrackName {
                wni,
                total,
                index,
                text,
                ..
            }
            | Self::SelectionName {
                wni,
                total,
                index,
                text,
                ..
            }
            | Self::CategoryName {
                wni,
                total,
                index,
                text,
                ..
            } => format!(
                "group={group} wni={wni} total={total} sequence={index} text=\"{}\"",
                escape_text(text)
            ),
        }
    }

    /// Exact SAL bytes excluding the point-to-multipoint envelope.
    pub fn encode(&self) -> Result<Vec<u8>, EncodeError> {
        match self {
            Self::Stop { group } => Ok(vec![0x01, *group]),
            Self::Play { group } => Ok(vec![0x79, *group]),
            Self::Pause { group, operation } => {
                validate_toggle_encode(*operation)?;
                Ok(vec![0x0a, *group, *operation])
            }
            Self::SetCategory { group, category } => {
                if *category > 127 {
                    return Err(EncodeError::new("Media Transport category is out of range"));
                }
                Ok(vec![0x12, *group, *category])
            }
            Self::SetSelection { group, selection } => {
                if *selection > 32767 {
                    return Err(EncodeError::new(
                        "Media Transport selection is out of range",
                    ));
                }
                let value = selection.to_be_bytes();
                Ok(vec![0x1b, *group, value[0], value[1]])
            }
            Self::SetTrack { group, track } => integer32_sal(0x25, *group, *track, "track"),
            Self::Shuffle { group, operation } => {
                validate_toggle_encode(*operation)?;
                Ok(vec![0x2a, *group, *operation])
            }
            Self::Repeat { group, operation } => Ok(vec![0x32, *group, *operation]),
            Self::NextCategory { group, operation } => Ok(vec![0x3a, *group, *operation]),
            Self::NextSelection { group, operation } => Ok(vec![0x42, *group, *operation]),
            Self::NextTrack { group, operation } => Ok(vec![0x4a, *group, *operation]),
            Self::Forward { group, operation } => {
                validate_speed_encode(*operation)?;
                Ok(vec![0x52, *group, *operation])
            }
            Self::Rewind { group, operation } => {
                validate_speed_encode(*operation)?;
                Ok(vec![0x5a, *group, *operation])
            }
            Self::SourcePower { group, operation } => Ok(vec![0x62, *group, *operation]),
            Self::TotalTracks { group, tracks } => {
                integer32_sal(0x6d, *group, *tracks, "track count")
            }
            Self::StatusRequest { group } => Ok(vec![0x71, *group]),
            Self::Enumerate {
                group,
                enumeration_type,
                start,
            } => {
                validate_enumeration_type_encode(*enumeration_type)?;
                Ok(vec![0x73, *group, *enumeration_type, *start])
            }
            Self::EnumerationSize {
                group,
                enumeration_type,
                start,
                size,
            } => {
                validate_enumeration_type_encode(*enumeration_type)?;
                if *size > 15 {
                    return Err(EncodeError::new(
                        "Media Transport enumeration size is out of range",
                    ));
                }
                Ok(vec![0x74, *group, *enumeration_type, *start, *size])
            }
            Self::TrackName {
                group,
                wni,
                total,
                index,
                text,
            } => name_sal(0x80, *group, *wni, *total, *index, text),
            Self::SelectionName {
                group,
                wni,
                total,
                index,
                text,
            } => name_sal(0xa0, *group, *wni, *total, *index, text),
            Self::CategoryName {
                group,
                wni,
                total,
                index,
                text,
            } => name_sal(0xc0, *group, *wni, *total, *index, text),
        }
    }
}

/// Decode one or more Media Transport SAL messages.
pub fn decode_sals(data: &[u8]) -> Result<Vec<MediaTransportMessage>, DecodeError> {
    let mut messages = Vec::new();
    let mut offset = 0;
    while offset < data.len() {
        let header = data[offset];
        let len = if matches!(header & 0xe0, 0x80 | 0xa0 | 0xc0) {
            usize::from(header & 0x1f) + 1
        } else {
            usize::from(header & 0x07) + 1
        };
        if len < 2 || data.len() - offset < len {
            return Err(DecodeError::new("truncated Media Transport SAL"));
        }
        messages.push(decode_one(&data[offset..offset + len])?);
        offset += len;
    }
    Ok(messages)
}

fn decode_one(bytes: &[u8]) -> Result<MediaTransportMessage, DecodeError> {
    let header = bytes[0];
    let group = bytes[1];
    let message = match (header, bytes) {
        (0x01, [_, _]) => MediaTransportMessage::Stop { group },
        (0x79, [_, _]) => MediaTransportMessage::Play { group },
        (0x0a, [_, _, operation]) if matches!(operation, 0 | 255) => MediaTransportMessage::Pause {
            group,
            operation: *operation,
        },
        (0x12, [_, _, category]) if *category <= 127 => MediaTransportMessage::SetCategory {
            group,
            category: *category,
        },
        (0x1b, [_, _, hi, lo]) => MediaTransportMessage::SetSelection {
            group,
            selection: checked_i16(u16::from_be_bytes([*hi, *lo]), "selection")?,
        },
        (0x25, [_, _, a, b, c, d]) => MediaTransportMessage::SetTrack {
            group,
            track: checked_i32(u32::from_be_bytes([*a, *b, *c, *d]), "track")?,
        },
        (0x2a, [_, _, operation]) if matches!(operation, 0 | 255) => {
            MediaTransportMessage::Shuffle {
                group,
                operation: *operation,
            }
        }
        (0x32, [_, _, operation]) => MediaTransportMessage::Repeat {
            group,
            operation: *operation,
        },
        (0x3a, [_, _, operation]) => MediaTransportMessage::NextCategory {
            group,
            operation: *operation,
        },
        (0x42, [_, _, operation]) => MediaTransportMessage::NextSelection {
            group,
            operation: *operation,
        },
        (0x4a, [_, _, operation]) => MediaTransportMessage::NextTrack {
            group,
            operation: *operation,
        },
        (0x52, [_, _, operation]) if valid_speed(*operation) => MediaTransportMessage::Forward {
            group,
            operation: *operation,
        },
        (0x5a, [_, _, operation]) if valid_speed(*operation) => MediaTransportMessage::Rewind {
            group,
            operation: *operation,
        },
        (0x62, [_, _, operation]) => MediaTransportMessage::SourcePower {
            group,
            operation: *operation,
        },
        (0x6d, [_, _, a, b, c, d]) => MediaTransportMessage::TotalTracks {
            group,
            tracks: checked_i32(u32::from_be_bytes([*a, *b, *c, *d]), "track count")?,
        },
        (0x71, [_, _]) => MediaTransportMessage::StatusRequest { group },
        (0x73, [_, _, enumeration_type, start]) if *enumeration_type <= 2 => {
            MediaTransportMessage::Enumerate {
                group,
                enumeration_type: *enumeration_type,
                start: *start,
            }
        }
        (0x74, [_, _, enumeration_type, start, size]) if *enumeration_type <= 2 && *size <= 15 => {
            MediaTransportMessage::EnumerationSize {
                group,
                enumeration_type: *enumeration_type,
                start: *start,
                size: *size,
            }
        }
        (0x82..=0x8d, _) => decode_name(0x80, bytes)?,
        (0xa2..=0xad, _) => decode_name(0xa0, bytes)?,
        (0xc2..=0xcd, _) => decode_name(0xc0, bytes)?,
        _ => {
            return Err(DecodeError::new(format!(
                "unknown or invalid Media Transport SAL header 0x{header:02x}"
            )))
        }
    };
    Ok(message)
}

fn decode_name(base: u8, bytes: &[u8]) -> Result<MediaTransportMessage, DecodeError> {
    let group = bytes[1];
    let packed = bytes[2];
    // Native C-Gate extracts bits 4..=6 and accepts every observed value.
    // Its command parser reserves outbound WNI 3 and 4, but those values (and
    // the ignored high bit) must not make an inbound report disappear.
    let wni = (packed >> 4) & 7;
    let total = (packed >> 2) & 3;
    let index = packed & 3;
    let text = bytes[3..].to_vec();
    Ok(match base {
        0x80 => MediaTransportMessage::TrackName {
            group,
            wni,
            total,
            index,
            text,
        },
        0xa0 => MediaTransportMessage::SelectionName {
            group,
            wni,
            total,
            index,
            text,
        },
        0xc0 => MediaTransportMessage::CategoryName {
            group,
            wni,
            total,
            index,
            text,
        },
        _ => unreachable!(),
    })
}

fn integer32_sal(header: u8, group: u8, value: u32, field: &str) -> Result<Vec<u8>, EncodeError> {
    if value > i32::MAX as u32 {
        return Err(EncodeError::new(format!(
            "Media Transport {field} is out of range"
        )));
    }
    let bytes = value.to_be_bytes();
    Ok(vec![header, group, bytes[0], bytes[1], bytes[2], bytes[3]])
}

fn name_sal(
    base: u8,
    group: u8,
    wni: u8,
    total: u8,
    index: u8,
    text: &[u8],
) -> Result<Vec<u8>, EncodeError> {
    if !valid_wni(wni) {
        return Err(EncodeError::new("Media Transport WNI is a reserved value"));
    }
    if total > 3 || index > 3 {
        return Err(EncodeError::new(
            "Media Transport name sequence is out of range",
        ));
    }
    if text.len() > 11 {
        return Err(EncodeError::new(
            "Media Transport name is longer than 11 bytes",
        ));
    }
    let mut result = Vec::with_capacity(text.len() + 3);
    result.push(base | (text.len() as u8 + 2));
    result.push(group);
    result.push((wni << 4) | (total << 2) | index);
    result.extend_from_slice(text);
    Ok(result)
}

fn checked_i16(value: u16, field: &str) -> Result<u16, DecodeError> {
    if value <= i16::MAX as u16 {
        Ok(value)
    } else {
        Err(DecodeError::new(format!(
            "Media Transport {field} is out of range"
        )))
    }
}

fn checked_i32(value: u32, field: &str) -> Result<u32, DecodeError> {
    if value <= i32::MAX as u32 {
        Ok(value)
    } else {
        Err(DecodeError::new(format!(
            "Media Transport {field} is out of range"
        )))
    }
}

fn validate_toggle_encode(operation: u8) -> Result<(), EncodeError> {
    if matches!(operation, 0 | 255) {
        Ok(())
    } else {
        Err(EncodeError::new(
            "Media Transport toggle operation is a reserved value",
        ))
    }
}

fn validate_speed_encode(operation: u8) -> Result<(), EncodeError> {
    if valid_speed(operation) {
        Ok(())
    } else {
        Err(EncodeError::new(
            "Media Transport speed operation is a reserved value",
        ))
    }
}

fn validate_enumeration_type_encode(value: u8) -> Result<(), EncodeError> {
    if value <= 2 {
        Ok(())
    } else {
        Err(EncodeError::new(
            "Media Transport enumeration type is out of range",
        ))
    }
}

fn valid_speed(operation: u8) -> bool {
    matches!(operation, 0 | 2 | 4 | 6 | 8 | 10 | 12)
}

fn valid_wni(wni: u8) -> bool {
    matches!(wni, 0 | 1 | 2 | 5 | 6 | 7)
}

fn escape_text(bytes: &[u8]) -> String {
    String::from_utf8_lossy(bytes)
        .chars()
        .flat_map(char::escape_default)
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn all_captured_command_shapes_round_trip() {
        let cases = vec![
            (MediaTransportMessage::Stop { group: 2 }, vec![0x01, 2]),
            (MediaTransportMessage::Play { group: 2 }, vec![0x79, 2]),
            (
                MediaTransportMessage::Pause {
                    group: 2,
                    operation: 255,
                },
                vec![0x0a, 2, 255],
            ),
            (
                MediaTransportMessage::SetCategory {
                    group: 2,
                    category: 127,
                },
                vec![0x12, 2, 127],
            ),
            (
                MediaTransportMessage::SetSelection {
                    group: 2,
                    selection: 32767,
                },
                vec![0x1b, 2, 0x7f, 0xff],
            ),
            (
                MediaTransportMessage::SetTrack {
                    group: 2,
                    track: 0x01020304,
                },
                vec![0x25, 2, 1, 2, 3, 4],
            ),
            (
                MediaTransportMessage::Shuffle {
                    group: 2,
                    operation: 0,
                },
                vec![0x2a, 2, 0],
            ),
            (
                MediaTransportMessage::Repeat {
                    group: 2,
                    operation: 128,
                },
                vec![0x32, 2, 128],
            ),
            (
                MediaTransportMessage::NextCategory {
                    group: 2,
                    operation: 1,
                },
                vec![0x3a, 2, 1],
            ),
            (
                MediaTransportMessage::NextSelection {
                    group: 2,
                    operation: 0,
                },
                vec![0x42, 2, 0],
            ),
            (
                MediaTransportMessage::NextTrack {
                    group: 2,
                    operation: 255,
                },
                vec![0x4a, 2, 255],
            ),
            (
                MediaTransportMessage::Forward {
                    group: 2,
                    operation: 12,
                },
                vec![0x52, 2, 12],
            ),
            (
                MediaTransportMessage::Rewind {
                    group: 2,
                    operation: 10,
                },
                vec![0x5a, 2, 10],
            ),
            (
                MediaTransportMessage::SourcePower {
                    group: 2,
                    operation: 255,
                },
                vec![0x62, 2, 255],
            ),
            (
                MediaTransportMessage::TotalTracks {
                    group: 2,
                    tracks: i32::MAX as u32,
                },
                vec![0x6d, 2, 0x7f, 0xff, 0xff, 0xff],
            ),
            (
                MediaTransportMessage::StatusRequest { group: 2 },
                vec![0x71, 2],
            ),
            (
                MediaTransportMessage::Enumerate {
                    group: 2,
                    enumeration_type: 2,
                    start: 255,
                },
                vec![0x73, 2, 2, 255],
            ),
            (
                MediaTransportMessage::EnumerationSize {
                    group: 2,
                    enumeration_type: 1,
                    start: 254,
                    size: 15,
                },
                vec![0x74, 2, 1, 254, 15],
            ),
            (
                MediaTransportMessage::TrackName {
                    group: 2,
                    wni: 0,
                    total: 0,
                    index: 0,
                    text: b"12345678901".to_vec(),
                },
                [vec![0x8d, 2, 0], b"12345678901".to_vec()].concat(),
            ),
            (
                MediaTransportMessage::SelectionName {
                    group: 2,
                    wni: 7,
                    total: 3,
                    index: 2,
                    text: b"Alpha Beta".to_vec(),
                },
                [vec![0xac, 2, 0x7e], b"Alpha Beta".to_vec()].concat(),
            ),
            (
                MediaTransportMessage::CategoryName {
                    group: 2,
                    wni: 1,
                    total: 1,
                    index: 0,
                    text: b"iPod".to_vec(),
                },
                vec![0xc6, 2, 0x14, b'i', b'P', b'o', b'd'],
            ),
        ];
        for (message, bytes) in cases {
            assert_eq!(message.encode().unwrap(), bytes);
            assert_eq!(decode_sals(&bytes).unwrap(), vec![message]);
        }
    }

    #[test]
    fn concatenated_and_empty_names_decode_losslessly() {
        let bytes = [vec![0x01, 2, 0xc2, 3, 0], vec![0x79, 4]].concat();
        assert_eq!(
            decode_sals(&bytes).unwrap(),
            vec![
                MediaTransportMessage::Stop { group: 2 },
                MediaTransportMessage::CategoryName {
                    group: 3,
                    wni: 0,
                    total: 0,
                    index: 0,
                    text: vec![],
                },
                MediaTransportMessage::Play { group: 4 },
            ]
        );
    }

    #[test]
    fn inbound_reserved_wni_values_follow_native_decoder_bits() {
        assert_eq!(
            decode_sals(&[0x83, 2, 0x30, b'A']).unwrap(),
            vec![MediaTransportMessage::TrackName {
                group: 2,
                wni: 3,
                total: 0,
                index: 0,
                text: b"A".to_vec(),
            }]
        );
        assert_eq!(
            decode_sals(&[0xa3, 2, 0xc0, b'B']).unwrap(),
            vec![MediaTransportMessage::SelectionName {
                group: 2,
                wni: 4,
                total: 0,
                index: 0,
                text: b"B".to_vec(),
            }]
        );
    }

    #[test]
    fn invalid_and_truncated_forms_fail_closed() {
        for bytes in [
            &[0x0a, 2, 1][..],
            &[0x52, 2, 1][..],
            &[0x1b, 2, 0x80, 0][..],
            &[0x25, 2, 0x80, 0, 0, 0][..],
            &[0x73, 2, 3, 0][..],
            &[0x74, 2, 2, 0, 16][..],
            &[0xcd, 2, 0][..],
        ] {
            assert!(decode_sals(bytes).is_err(), "{bytes:02X?}");
        }
        assert!(MediaTransportMessage::TrackName {
            group: 2,
            wni: 3,
            total: 0,
            index: 0,
            text: vec![],
        }
        .encode()
        .is_err());
    }

    #[test]
    fn application_dispatch_precedes_dynamic_label_prefixes() {
        let expected = MediaTransportMessage::SelectionName {
            group: 2,
            wni: 7,
            total: 3,
            index: 2,
            text: b"Alpha Beta".to_vec(),
        };
        assert_eq!(
            crate::sal::decode_sals(
                crate::common::APP_MEDIA_TRANSPORT,
                &[0xac, 2, 0x7e, b'A', b'l', b'p', b'h', b'a', b' ', b'B', b'e', b't', b'a'],
            )
            .unwrap(),
            vec![crate::sal::Sal::MediaTransport(expected)]
        );
    }
}
