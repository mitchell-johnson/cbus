//! One generated `#[test]` per committed golden vector (see build.rs).
//! The vectors themselves are loaded from `rust-migration-harness/vectors/`
//! at run time — the harness JSONL files stay the single source of truth.

use cbus_golden_tests as support;

include!(concat!(env!("OUT_DIR"), "/golden_generated.rs"));
