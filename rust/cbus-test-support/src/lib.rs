//! Shared infrastructure for the full-system tests: an in-process MQTT
//! 3.1.1 mini broker, a scripted fake C-Bus PCI TCP server, helpers to
//! spawn the real workspace binaries and condition-polling waits.
//!
//! In-process MQTT broker, scripted PCI, process helpers, and polling utilities.
//! so the Cargo test suite needs no external services.

pub mod broker;
pub mod pci;
pub mod proc;
pub mod wait;
