//! Shared infrastructure for the full-system tests: an in-process MQTT
//! 3.1.1 mini broker, a scripted fake C-Bus PCI TCP server, helpers to
//! spawn the real workspace binaries and condition-polling waits.
//!
//! Rust-native port of `rust-migration-harness/lib/{mini_broker,fake_pci}.py`
//! so the cargo test suite needs no Python.

pub mod broker;
pub mod pci;
pub mod proc;
pub mod wait;
