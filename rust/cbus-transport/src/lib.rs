//! Async framing, PCI client state machine, flow control, and connections.

#![deny(missing_docs)]

pub mod apply;
pub mod cni_discovery;
pub mod conn;
pub mod flow;
pub mod framing;
pub mod inventory;
pub mod journal;
pub mod pci;
pub mod plan;
pub mod serial_address;
pub mod verify;

pub use conn::Endpoint;
pub use framing::FrameBuffer;
pub use pci::{CBusEvent, PciClient};
