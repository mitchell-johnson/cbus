//! cmqttd's pure logic (no network): topic conventions, HA discovery
//! payload builders, CBZ project-file label extraction, `/set` command
//! parsing.

#![deny(missing_docs)]

pub mod cbz;
pub mod command;
pub mod discovery;
pub mod topics;
pub mod vector_check;

pub use command::{parse_set_command, SetCommand};
pub use discovery::AppLabels;
