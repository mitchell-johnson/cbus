//! Pure C-Bus wire codec: a behaviour-for-behaviour port of the Python
//! `cbus` protocol package (including its documented quirks and bugs).
//! No async, no I/O.

#![deny(missing_docs)]

pub mod cal;
pub mod common;
pub mod consts;
pub mod decode;
pub mod json;
pub mod packet;
pub mod report;
pub mod sal;

pub use cal::Cal;
pub use decode::decode_packet;
pub use packet::{Meta, Packet};
pub use report::StatusReport;
pub use sal::Sal;

/// Error raised while decoding wire data. Maps to `Packet::Invalid` at the
/// packet level (like Python exceptions caught in `decode_packet`).
#[derive(Debug, Clone, thiserror::Error)]
#[error("{0}")]
pub struct DecodeError(pub String);

impl DecodeError {
    /// A decode error with the given message.
    pub fn new(msg: impl Into<String>) -> Self {
        DecodeError(msg.into())
    }
}

/// Error raised while encoding (mirrors Python ValueError/NotImplementedError
/// raised by the various `encode()` methods).
#[derive(Debug, Clone, thiserror::Error)]
#[error("{0}")]
pub struct EncodeError(pub String);

impl EncodeError {
    /// An encode error with the given message.
    pub fn new(msg: impl Into<String>) -> Self {
        EncodeError(msg.into())
    }
}
