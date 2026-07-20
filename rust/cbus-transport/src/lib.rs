//! Async framing + PCI client state machine + connections.
//! Port of `buffered_protocol.py`/`cbus_protocol.py` (framing),
//! `pciprotocol.py` (PciClient) and `transport/{base,tcp,serial}.py`.

#![deny(missing_docs)]

pub mod conn;
pub mod framing;
pub mod pci;

pub use conn::Endpoint;
pub use framing::FrameBuffer;
pub use pci::{CBusEvent, PciClient};
