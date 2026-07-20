//! Packet model + encoders. Port of `base_packet.py` and the per-type
//! `encode()` methods in `{pm,pp,dm,confirm,error,po,reset,scs}_packet.py`.

use crate::cal::Cal;
use crate::common::{
    add_cbus_checksum, DAT_POINT_TO_MULTIPOINT, DAT_POINT_TO_POINT,
    DAT_POINT_TO_POINT_TO_MULTIPOINT,
};
use crate::sal::Sal;
use crate::EncodeError;

/// Envelope fields shared by the addressed packet types.
#[derive(Debug, Clone, PartialEq)]
pub struct Meta {
    pub checksum: bool,
    pub priority_class: u8, // 0..=3
    pub source_address: Option<u8>,
    /// the confirmation *char* (client->PCI frames only)
    pub confirmation: Option<u8>,
}

impl Meta {
    pub fn new(checksum: bool, priority_class: u8) -> Self {
        Meta {
            checksum,
            priority_class,
            source_address: None,
            confirmation: None,
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub enum Packet {
    // specials
    PowerOn,
    PciError,
    Reset,
    SmartConnect,
    Confirmation {
        code: u8,
        success: bool,
    },
    /// decode error under strict rules (payload/exception not modelled)
    Invalid,
    /// bare CAL returned by the client "device management CAL" path
    BareCal(Cal),
    DeviceManagement {
        meta: Meta,
        parameter: u8,
        value: u8,
    },
    PointToMultipoint {
        meta: Meta,
        application: u8,
        sals: Vec<Sal>,
    },
    PointToPoint {
        meta: Meta,
        unit_address: u8,
        bridged: bool,
        hops: Vec<u8>,
        cals: Vec<Cal>,
    },
}

/// flags byte per `base_packet.py:53-57`: note the (buggy) `rc & 0x02` mask;
/// rc is always 0 here so the term vanishes.
fn flags(dat: u8, dp: bool, priority_class: u8) -> u8 {
    (dat & 0x07) | (if dp { 0x20 } else { 0 }) | ((priority_class & 0x03) << 6)
}

fn header(meta: &Meta, dat: u8, dp: bool) -> Vec<u8> {
    let f = flags(dat, dp, meta.priority_class);
    match meta.source_address {
        None => vec![f],
        Some(s) => vec![f, s],
    }
}

impl Packet {
    pub fn meta(&self) -> Option<&Meta> {
        match self {
            Packet::DeviceManagement { meta, .. }
            | Packet::PointToMultipoint { meta, .. }
            | Packet::PointToPoint { meta, .. } => Some(meta),
            _ => None,
        }
    }

    pub fn meta_mut(&mut self) -> Option<&mut Meta> {
        match self {
            Packet::DeviceManagement { meta, .. }
            | Packet::PointToMultipoint { meta, .. }
            | Packet::PointToPoint { meta, .. } => Some(meta),
            _ => None,
        }
    }

    /// Raw binary encoding (BasePacket.encode), incl. checksum when
    /// `meta.checksum`. Specials encode to their raw tokens.
    pub fn encode(&self) -> Result<Vec<u8>, EncodeError> {
        match self {
            Packet::Reset => Ok(b"~".to_vec()),
            Packet::SmartConnect => Ok(b"|".to_vec()),
            Packet::PowerOn => Ok(b"++".to_vec()),
            Packet::PciError => Ok(b"!".to_vec()),
            Packet::Confirmation { code, success } => {
                Ok(vec![*code, if *success { b'.' } else { b'#' }])
            }
            Packet::Invalid => Err(EncodeError::new("invalid packet payload not modelled")),
            Packet::BareCal(cal) => Ok(cal.encode()),
            Packet::DeviceManagement {
                meta,
                parameter,
                value,
            } => {
                let mut p = header(meta, DAT_POINT_TO_POINT_TO_MULTIPOINT, true);
                p.extend_from_slice(&[*parameter, 0, *value]);
                Ok(finish(p, meta))
            }
            Packet::PointToMultipoint {
                meta,
                application,
                sals,
            } => {
                let mut p = header(meta, DAT_POINT_TO_MULTIPOINT, false);
                p.extend_from_slice(&[*application, 0]);
                for sal in sals {
                    p.extend_from_slice(&sal.encode()?);
                }
                Ok(finish(p, meta))
            }
            Packet::PointToPoint {
                meta,
                unit_address,
                bridged,
                cals,
                ..
            } => {
                if *bridged {
                    return Err(EncodeError::new("bridged ptp packets"));
                }
                let mut p = header(meta, DAT_POINT_TO_POINT, false);
                p.extend_from_slice(&[*unit_address, 0]);
                for cal in cals {
                    p.extend_from_slice(&cal.encode());
                }
                Ok(finish(p, meta))
            }
        }
    }

    /// BasePacket.encode_packet: base16 uppercase ASCII of `encode()` for
    /// addressed packets; the raw token for special packets. Bare CALs have
    /// no encode_packet in Python (AttributeError).
    pub fn encode_packet(&self) -> Result<Vec<u8>, EncodeError> {
        match self {
            Packet::Reset
            | Packet::SmartConnect
            | Packet::PowerOn
            | Packet::PciError
            | Packet::Confirmation { .. } => self.encode(),
            Packet::Invalid => Err(EncodeError::new("invalid packet payload not modelled")),
            Packet::BareCal(_) => Err(EncodeError::new("bare CAL has no encode_packet")),
            _ => Ok(hex::encode_upper(self.encode()?).into_bytes()),
        }
    }
}

fn finish(p: Vec<u8>, meta: &Meta) -> Vec<u8> {
    if meta.checksum {
        add_cbus_checksum(&p)
    } else {
        p
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn specials() {
        assert_eq!(Packet::Reset.encode_packet().unwrap(), b"~");
        assert_eq!(Packet::PowerOn.encode_packet().unwrap(), b"++");
        assert_eq!(
            Packet::Confirmation {
                code: b'h',
                success: true
            }
            .encode_packet()
            .unwrap(),
            b"h."
        );
        assert_eq!(
            Packet::Confirmation {
                code: b'g',
                success: false
            }
            .encode_packet()
            .unwrap(),
            b"g#"
        );
    }

    #[test]
    fn pm_light_on() {
        // \0538007901 + checksum 49
        let p = Packet::PointToMultipoint {
            meta: Meta::new(true, 0),
            application: 0x38,
            sals: vec![Sal::LightingOn {
                application: 0x38,
                group_address: 1,
            }],
        };
        assert_eq!(p.encode_packet().unwrap(), b"053800790149");
    }

    #[test]
    fn dm_flags() {
        // DM default priority CLASS_2 -> flags 0xA3
        let p = Packet::DeviceManagement {
            meta: Meta::new(false, 2),
            parameter: 0x21,
            value: 0xff,
        };
        assert_eq!(p.encode_packet().unwrap(), b"A32100FF");
    }
}
