//! Common Application Language messages and stream decoding.

use crate::common::{CAL_EXTENDED_STATUS, CAL_IDENTIFY, CAL_RECALL, CAL_REPLY};
use crate::report::StatusReport;
use crate::DecodeError;

/// A Common Application Language message.
#[derive(Debug, Clone, PartialEq)]
pub enum Cal {
    /// Write a CAL parameter. Extended-memory selectors use parameter 0.
    Write {
        /// Parameter number.
        parameter: u8,
        /// Payload (at most 30 bytes on the wire).
        data: Vec<u8>,
    },
    /// Unit acknowledgement of a CAL write (distinct from a PCI confirmation).
    Ack {
        /// Parameter acknowledged.
        parameter: u8,
        /// Operation-specific acknowledgement data.
        data: Vec<u8>,
    },
    /// Temporarily unlock one protected programming parameter.
    Unlock {
        /// Parameter number to unlock.
        parameter: u8,
    },
    /// Move a unit using the challenge returned by unlocking parameter 0x20.
    /// The challenge is outside the ordinary `0xA3` CAL length.
    Readdress {
        /// New unit address.
        destination: u8,
        /// One-use challenge returned by the unit.
        challenge: u8,
    },
    /// Rejection of the fixed-length protected-address store.
    ReaddressNak,
    /// A unit rejected a CAL operation. Unlike the length-coded `0x3x`
    /// acknowledgement family, native C-Gate treats `0x3B` as a fixed NAK
    /// prefix followed by operation-specific correlation/error bytes.
    Nak {
        /// Parameter or extended-command group being rejected.
        parameter: u8,
        /// Operation-specific correlation/error bytes.
        data: Vec<u8>,
    },
    /// Start an extended CAL operation (`0x81`).
    Execute {
        /// Extended-command group.
        group: u8,
        /// Operation within the group.
        operation: u8,
        /// Operation-specific request data.
        data: Vec<u8>,
    },
    /// Query an extended CAL operation (`0x82`).
    Poll {
        /// Extended-command group.
        group: u8,
        /// Operation within the group.
        operation: u8,
    },
    /// Extended CAL operation status (`0x83`).
    ExtendedReply {
        /// Extended-command group.
        group: u8,
        /// Operation within the group.
        operation: u8,
        /// Native status code (`0` complete, `1` still running, `2` busy).
        status: u8,
        /// Optional operation-specific response data.
        data: Vec<u8>,
    },
    /// Select the active 256-byte programming page for subsequent STOREs.
    SetPage {
        /// Page number.
        page: u8,
    },
    /// Ask a unit to identify one of its attributes.
    Identify {
        /// Attribute number to identify.
        attribute: u8,
    },
    /// Recall a parameter block from a unit.
    Recall {
        /// First parameter number.
        param: u8,
        /// Number of parameters to recall.
        count: u8,
    },
    /// Recall bytes from an explicit 256-byte programming page.
    PagedRecall {
        /// Page number.
        page: u8,
        /// First parameter within the page.
        param: u8,
        /// Number of parameters to recall.
        count: u8,
    },
    /// A unit's reply to identify/recall.
    Reply {
        /// The parameter (or attribute) being replied to.
        parameter: u8,
        /// Reply payload (clipped to 0x1E bytes on encode).
        data: Vec<u8>,
    },
    /// An extended status report (binary or level).
    ExtendedStatus {
        /// Report was sent unsolicited.
        externally_initiated: bool,
        /// Application the report describes.
        child_application: u8,
        /// First group address covered.
        block_start: u8,
        /// The group states/levels.
        report: StatusReport,
    },
}

impl Cal {
    /// Wire bytes of this CAL.
    pub fn encode(&self) -> Vec<u8> {
        match self {
            Cal::Write { parameter, data } | Cal::Ack { parameter, data } => {
                let data = &data[..data.len().min(30)];
                let opcode = if matches!(self, Cal::Write { .. }) {
                    0xa0
                } else {
                    0x30
                };
                let mut out = vec![opcode | (data.len() as u8 + 1), *parameter];
                out.extend_from_slice(data);
                out
            }
            Cal::Unlock { parameter } => vec![0x11, *parameter],
            Cal::Readdress {
                destination,
                challenge,
            } => vec![0xa3, 0x20, 0x4e, *destination, *challenge],
            Cal::ReaddressNak => vec![0x3b, 0x20, 0x4e],
            Cal::Nak { parameter, data } => {
                let mut out = vec![0x3b, *parameter];
                out.extend_from_slice(data);
                out
            }
            Cal::Execute {
                group,
                operation,
                data,
            } => {
                // Schneider's extended-command parser accepts lengths 3..14.
                let data = &data[..data.len().min(11)];
                let mut out = vec![0xe0 | (data.len() as u8 + 3), 0x81, *group, *operation];
                out.extend_from_slice(data);
                out
            }
            Cal::Poll { group, operation } => vec![0xe3, 0x82, *group, *operation],
            Cal::ExtendedReply {
                group,
                operation,
                status,
                data,
            } => {
                let data = &data[..data.len().min(10)];
                let mut out = vec![
                    0xe0 | (data.len() as u8 + 4),
                    0x83,
                    *group,
                    *operation,
                    *status,
                ];
                out.extend_from_slice(data);
                out
            }
            Cal::SetPage { page } => vec![0x39, *page],
            Cal::Identify { attribute } => vec![CAL_IDENTIFY, *attribute],
            Cal::Recall { param, count } => vec![CAL_RECALL, *param, *count],
            Cal::PagedRecall { page, param, count } => vec![0x1b, *page, *param, *count],
            Cal::Reply { parameter, data } => {
                // reply data is clipped to 0x1E bytes on encode
                let data = &data[..data.len().min(0x1e)];
                let mut out = vec![CAL_REPLY | (data.len() as u8 + 1), *parameter];
                out.extend_from_slice(data);
                out
            }
            Cal::ExtendedStatus {
                externally_initiated,
                child_application,
                block_start,
                report,
            } => {
                let rep = report.encode();
                let coding =
                    (if *externally_initiated { 0x40 } else { 0 }) | (report.block_type() & 0x7);
                let mut out = vec![
                    CAL_EXTENDED_STATUS | (rep.len() as u8).wrapping_add(3),
                    coding,
                    *child_application,
                    *block_start,
                ];
                out.extend_from_slice(&rep);
                out
            }
        }
    }

    /// Decode one CAL from the front of `data`; returns (cal, consumed).
    /// Decode the CAL payload of a point-to-point packet.
    pub fn decode_one(data: &[u8]) -> Result<(Cal, usize), DecodeError> {
        let cmd = *data
            .first()
            .ok_or_else(|| DecodeError::new("empty CAL data"))?;
        if data.starts_with(&[0x3b, 0x20, 0x4e]) {
            Ok((Cal::ReaddressNak, 3))
        } else if cmd == 0x3b {
            let parameter = *data
                .get(1)
                .ok_or_else(|| DecodeError::new("truncated CAL negative acknowledgement"))?;
            if data.len() < 3 {
                return Err(DecodeError::new("truncated CAL negative acknowledgement"));
            }
            Ok((
                Cal::Nak {
                    parameter,
                    data: data[2..].to_vec(),
                },
                data.len(),
            ))
        } else if cmd & 0xe0 == 0xa0 || cmd & 0xf0 == 0x30 {
            let length = if cmd & 0xe0 == 0xa0 {
                cmd & 0x1f
            } else {
                cmd & 0x0f
            } as usize;
            if length == 0 || data.len() < length + 1 {
                return Err(DecodeError::new("truncated CAL write/ack"));
            }
            let parameter = data[1];
            let payload = data[2..length + 1].to_vec();
            let cal = if cmd & 0xe0 == 0xa0 {
                Cal::Write {
                    parameter,
                    data: payload,
                }
            } else {
                Cal::Ack {
                    parameter,
                    data: payload,
                }
            };
            Ok((cal, length + 1))
        } else if cmd & 0xe0 == CAL_REPLY {
            let cal_end = ((cmd & 0x1f) + 1) as usize;
            if data.len() < cal_end {
                return Err(DecodeError::new(format!(
                    "Invalid reply CAL, need {} bytes but got {}",
                    cal_end,
                    data.len()
                )));
            }
            let reply_data = &data[1..cal_end];
            // ReplyCAL.decode_cal: parameter=data[0]; IndexError when empty
            let parameter = *reply_data
                .first()
                .ok_or_else(|| DecodeError::new("empty reply CAL"))?;
            Ok((
                Cal::Reply {
                    parameter,
                    data: reply_data[1..].to_vec(),
                },
                cal_end,
            ))
        } else if cmd & 0xe0 == 0xc0 {
            // STANDARD_STATUS is not supported by this decoder.
            Err(DecodeError::new("standard status cal"))
        } else if cmd & 0xe0 == CAL_EXTENDED_STATUS && matches!(data.get(1), Some(0x81..=0x83)) {
            let length = usize::from(cmd & 0x1f);
            let cal_end = length + 1;
            if !(3..=14).contains(&length) || data.len() < cal_end {
                return Err(DecodeError::new("truncated extended CAL command"));
            }
            let verb = data[1];
            let group = data[2];
            let operation = data[3];
            let cal = match verb {
                0x81 => Cal::Execute {
                    group,
                    operation,
                    data: data[4..cal_end].to_vec(),
                },
                0x82 if length == 3 => Cal::Poll { group, operation },
                0x82 => return Err(DecodeError::new("invalid extended CAL poll length")),
                0x83 if length >= 4 => Cal::ExtendedReply {
                    group,
                    operation,
                    status: data[4],
                    data: data[5..cal_end].to_vec(),
                },
                0x83 => return Err(DecodeError::new("extended CAL reply has no status")),
                _ => unreachable!("extended CAL verb was range checked"),
            };
            Ok((cal, cal_end))
        } else if cmd & 0xe0 == CAL_EXTENDED_STATUS {
            let cal_end = ((cmd & 0x1f) + 1) as usize;
            if data.len() < cal_end {
                return Err(DecodeError::new(format!(
                    "Invalid reply CAL, need {} bytes but got {}",
                    cal_end,
                    data.len()
                )));
            }
            let d = &data[1..cal_end];
            if d.len() < 3 {
                // Missing coding/application/block fields are invalid.
                return Err(DecodeError::new("extended status CAL too short"));
            }
            let externally_initiated = d[0] & 0x40 > 0;
            let block_type = d[0] & 0x7;
            let child_application = d[1];
            let block_start = d[2];
            let payload = &d[3..];
            let report = match block_type {
                0x00 => StatusReport::decode_binary(payload),
                0x07 => StatusReport::decode_level(payload)?,
                _ => return Err(DecodeError::new(format!("block_type = {:x}", block_type))),
            };
            Ok((
                Cal::ExtendedStatus {
                    externally_initiated,
                    child_application,
                    block_start,
                    report,
                },
                cal_end,
            ))
        } else if cmd == 0x11 {
            let parameter = *data
                .get(1)
                .ok_or_else(|| DecodeError::new("truncated unlock CAL"))?;
            Ok((Cal::Unlock { parameter }, 2))
        } else if cmd == CAL_IDENTIFY {
            let attribute = *data
                .get(1)
                .ok_or_else(|| DecodeError::new("truncated identify CAL"))?;
            Ok((Cal::Identify { attribute }, 2))
        } else if cmd == CAL_RECALL {
            let param = *data
                .get(1)
                .ok_or_else(|| DecodeError::new("truncated recall CAL"))?;
            let count = *data
                .get(2)
                .ok_or_else(|| DecodeError::new("truncated recall CAL"))?;
            Ok((Cal::Recall { param, count }, 3))
        } else if cmd == 0x1b {
            let page = *data
                .get(1)
                .ok_or_else(|| DecodeError::new("truncated paged recall CAL"))?;
            let param = *data
                .get(2)
                .ok_or_else(|| DecodeError::new("truncated paged recall CAL"))?;
            let count = *data
                .get(3)
                .ok_or_else(|| DecodeError::new("truncated paged recall CAL"))?;
            Ok((Cal::PagedRecall { page, param, count }, 4))
        } else {
            Err(DecodeError::new(format!("unknown CAL command {:#x}", cmd)))
        }
    }

    /// Decode one client-to-PCI CAL. Opcode `0x39` is direction-sensitive:
    /// on this path it is the native two-byte page selector, while incoming
    /// `0x39` remains the length-coded eight-byte ACK handled by
    /// [`Self::decode_one`].
    pub fn decode_one_to_pci(data: &[u8]) -> Result<(Cal, usize), DecodeError> {
        if data.starts_with(&[0xa3, 0x20, 0x4e]) {
            let destination = *data
                .get(3)
                .ok_or_else(|| DecodeError::new("truncated readdress CAL"))?;
            let challenge = *data
                .get(4)
                .ok_or_else(|| DecodeError::new("truncated readdress CAL"))?;
            Ok((
                Cal::Readdress {
                    destination,
                    challenge,
                },
                5,
            ))
        } else if data.first() == Some(&0x39) {
            let page = *data
                .get(1)
                .ok_or_else(|| DecodeError::new("truncated page selection CAL"))?;
            Ok((Cal::SetPage { page }, 2))
        } else {
            Self::decode_one(data)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn identify_recall() {
        assert_eq!(Cal::Unlock { parameter: 0x20 }.encode(), vec![0x11, 0x20]);
        let (c, n) = Cal::decode_one(&[0x11, 0x20, 0xff]).unwrap();
        assert_eq!(c, Cal::Unlock { parameter: 0x20 });
        assert_eq!(n, 2);
        assert_eq!(
            Cal::Readdress {
                destination: 6,
                challenge: 0x5a
            }
            .encode(),
            vec![0xa3, 0x20, 0x4e, 6, 0x5a]
        );
        assert_eq!(
            Cal::decode_one_to_pci(&[0xa3, 0x20, 0x4e, 6, 0x5a]).unwrap(),
            (
                Cal::Readdress {
                    destination: 6,
                    challenge: 0x5a
                },
                5
            )
        );
        assert_eq!(
            Cal::decode_one(&[0x3b, 0x20, 0x4e]).unwrap(),
            (Cal::ReaddressNak, 3)
        );
        assert_eq!(Cal::SetPage { page: 4 }.encode(), vec![0x39, 4]);
        let (c, n) = Cal::decode_one_to_pci(&[0x39, 4, 0xff]).unwrap();
        assert_eq!(c, Cal::SetPage { page: 4 });
        assert_eq!(n, 2);
        let ack = Cal::Ack {
            parameter: 4,
            data: vec![0; 8],
        };
        let encoded = ack.encode();
        assert_eq!(Cal::decode_one(&encoded).unwrap(), (ack, 10));
        assert_eq!(Cal::Identify { attribute: 2 }.encode(), vec![0x21, 0x02]);
        assert_eq!(
            Cal::Recall {
                param: 0xfa,
                count: 0x2c
            }
            .encode(),
            vec![0x1a, 0xfa, 0x2c]
        );
        let (c, n) = Cal::decode_one(&[0x21, 0x02, 0xff]).unwrap();
        assert_eq!(c, Cal::Identify { attribute: 2 });
        assert_eq!(n, 2);
        let (c, n) = Cal::decode_one(&[0x1a, 0xfa, 0x2c]).unwrap();
        assert_eq!(
            c,
            Cal::Recall {
                param: 0xfa,
                count: 0x2c
            }
        );
        assert_eq!(n, 3);
        assert_eq!(
            Cal::PagedRecall {
                page: 4,
                param: 0x20,
                count: 12
            }
            .encode(),
            vec![0x1b, 4, 0x20, 12]
        );
        let (c, n) = Cal::decode_one(&[0x1b, 4, 0x20, 12, 0xff]).unwrap();
        assert_eq!(
            c,
            Cal::PagedRecall {
                page: 4,
                param: 0x20,
                count: 12
            }
        );
        assert_eq!(n, 4);
        assert_eq!(
            Cal::Execute {
                group: 0,
                operation: 4,
                data: vec![]
            }
            .encode(),
            vec![0xe3, 0x81, 0, 4]
        );
        assert_eq!(
            Cal::Poll {
                group: 0,
                operation: 4
            }
            .encode(),
            vec![0xe3, 0x82, 0, 4]
        );
        assert_eq!(
            Cal::decode_one(&[0xe4, 0x83, 0, 4, 1]).unwrap(),
            (
                Cal::ExtendedReply {
                    group: 0,
                    operation: 4,
                    status: 1,
                    data: vec![]
                },
                5
            )
        );
        assert_eq!(
            Cal::decode_one(&[0x3b, 0, 4, 2]).unwrap(),
            (
                Cal::Nak {
                    parameter: 0,
                    data: vec![4, 2]
                },
                4
            )
        );
    }

    #[test]
    fn reply() {
        // header = 0x80 | (len+1)
        let c = Cal::Reply {
            parameter: 1,
            data: b"PC_CNIED".to_vec(),
        };
        let enc = c.encode();
        assert_eq!(enc[0], 0x80 | 9);
        assert_eq!(enc[1], 1);
        let (d, n) = Cal::decode_one(&enc).unwrap();
        assert_eq!(d, c);
        assert_eq!(n, enc.len());
        // truncated reply -> Err
        assert!(Cal::decode_one(&[0x89, 0x01]).is_err());
        // 0x80 (length nibble zero) produces an invalid empty reply body.
        assert!(Cal::decode_one(&[0x80]).is_err());
        // clipping to 0x1e data bytes
        let c = Cal::Reply {
            parameter: 1,
            data: vec![0xaa; 0x40],
        };
        let enc = c.encode();
        assert_eq!(enc.len(), 2 + 0x1e);
        assert_eq!(enc[0], 0x80 | 0x1f);
    }

    #[test]
    fn extended_status() {
        let c = Cal::ExtendedStatus {
            externally_initiated: false,
            child_application: 0x38,
            block_start: 0,
            report: StatusReport::Level(vec![Some(255), Some(0)]),
        };
        let enc = c.encode();
        assert_eq!(enc[0], 0xe0 | 7);
        assert_eq!(enc[1], 0x07);
        let (d, n) = Cal::decode_one(&enc).unwrap();
        assert_eq!(d, c);
        assert_eq!(n, enc.len());
        // standard status -> Err
        assert!(Cal::decode_one(&[0xc5, 0x38, 0x00, 0x00, 0x00, 0x00]).is_err());
    }
}
