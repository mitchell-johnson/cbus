//! Port of `cbus/protocol/cal/*.py` (identify, recall, reply, extended) and
//! the CAL stream decoder from `cbus/protocol/pp_packet.py:82-112`.

use crate::common::{CAL_EXTENDED_STATUS, CAL_IDENTIFY, CAL_RECALL, CAL_REPLY};
use crate::report::StatusReport;
use crate::DecodeError;

/// A Common Application Language message.
#[derive(Debug, Clone, PartialEq)]
pub enum Cal {
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
    /// Wire bytes of this CAL (per `cal/*.py` encode methods).
    pub fn encode(&self) -> Vec<u8> {
        match self {
            Cal::Identify { attribute } => vec![CAL_IDENTIFY, *attribute],
            Cal::Recall { param, count } => vec![CAL_RECALL, *param, *count],
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
    /// Port of `PointToPointPacket.decode_cal`.
    pub fn decode_one(data: &[u8]) -> Result<(Cal, usize), DecodeError> {
        let cmd = *data
            .first()
            .ok_or_else(|| DecodeError::new("empty CAL data"))?;
        if cmd & 0xe0 == CAL_REPLY {
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
            // STANDARD_STATUS: never supported by the Python decoder
            Err(DecodeError::new("standard status cal"))
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
                // Python IndexError on coding/app/block access
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
        } else {
            Err(DecodeError::new(format!("unknown CAL command {:#x}", cmd)))
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn identify_recall() {
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
        // 0x80 (len nibble 0 -> empty reply body) -> Err (Python IndexError)
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
