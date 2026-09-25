//! Async framing, PCI client state machine, flow control, and connections.

#![deny(missing_docs)]

pub mod conn;
pub mod flow;
pub mod framing;
pub mod inventory;
pub mod pci;
pub mod serial_address;

pub use conn::Endpoint;
pub use framing::FrameBuffer;
pub use pci::{CBusEvent, PciClient};
