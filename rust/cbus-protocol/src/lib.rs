//! Pure C-Bus wire codec with compatibility behavior fixed by golden vectors.
//! No async and no I/O.

#![deny(missing_docs)]

pub mod cal;
pub mod common;
pub mod consts;
pub mod decode;
pub mod json;
pub mod packet;
pub mod pci_observation;
pub mod project_identity;
pub mod report;
pub mod sal;
pub mod serial_address;

pub use cal::Cal;
pub use decode::decode_packet;
pub use packet::{Meta, Packet};
pub use report::StatusReport;
pub use sal::Sal;

/// Error raised while decoding wire data. Maps to `Packet::Invalid` at the
/// packet level by `decode_packet`.
#[derive(Debug, Clone, thiserror::Error)]
#[error("{0}")]
pub struct DecodeError(pub String);

impl DecodeError {
    /// A decode error with the given message.
    pub fn new(msg: impl Into<String>) -> Self {
        DecodeError(msg.into())
    }
}

/// Error raised while encoding an unsupported or invalid value.
#[derive(Debug, Clone, thiserror::Error)]
#[error("{0}")]
pub struct EncodeError(pub String);

impl EncodeError {
    /// An encode error with the given message.
    pub fn new(msg: impl Into<String>) -> Self {
        EncodeError(msg.into())
    }
}
