//! P1 JSON compatibility vectors for the observed dynamic-label cache.
//!
//! The committed file `testdata/vectors/observed_dynamic_labels.jsonl` pins
//! the existing Python `decode_observed_labels` contract (provenance, bounds,
//! partial/corrupt assembly, language/variant/app-group identity) without
//! inventing a physical cache inventory query. There is no Rust
//! observed-cache decoder, so this test validates the file schema and that
//! the existing Rust SAL codecs (`validate_payload` / `decode_sals`)
//! accept the `payload_hex` entries exactly as specified. It never claims
//! device readback and never queries a physical cache.

use cbus_protocol::sal::label::{decode_sals, validate_payload};
use serde_json::Value;
use std::collections::HashSet;

const VECTORS: &str = concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../testdata/vectors/observed_dynamic_labels.jsonl"
);

fn rows() -> Vec<Value> {
    let text = std::fs::read_to_string(VECTORS)
        .unwrap_or_else(|e| panic!("missing observed-label vectors {VECTORS}: {e}"));
    let rows: Vec<Value> = text
        .lines()
        .filter(|l| !l.trim().is_empty())
        .map(|l| serde_json::from_str(l).expect("vector line is valid JSON"))
        .collect();
    assert!(!rows.is_empty(), "vector file must not be empty");
    rows
}

fn valid_applications(app: u64) -> bool {
    (48..=95).contains(&app) || app == 202 || app == 203
}

#[test]
fn observed_dynamic_label_vectors_pin_json_contract() {
    let rows = rows();
    assert!(
        rows.len() >= 10,
        "expected ~10-15 compatibility cases, got {}",
        rows.len()
    );
    let mut ids = HashSet::new();
    for item in &rows {
        let id = item
            .get("id")
            .and_then(Value::as_str)
            .expect("vector has string id");
        assert!(ids.insert(id.to_string()), "duplicate vector id {id}");
        let document = item
            .get("document")
            .and_then(Value::as_object)
            .unwrap_or_else(|| panic!("{id}: vector needs a document object"));
        assert!(
            item.get("expect").is_some() ^ item.get("expect_error").is_some(),
            "{id}: vector needs exactly one of expect / expect_error"
        );
        // Provenance envelope stays present on every row (valid rows carry
        // the safe values; rejection rows intentionally carry the bad value
        // this vector pins). Presence is checked here; semantics are pinned
        // by the Python vector test via decode_observed_labels.
        for key in [
            "format",
            "source",
            "complete",
            "device_readback",
            "capacity",
            "observations",
        ] {
            assert!(document.contains_key(key), "{id}: document missing {key}");
        }
        let observations = document
            .get("observations")
            .and_then(Value::as_array)
            .unwrap_or_else(|| panic!("{id}: observations must be an array"));
        let mut previous: Option<i64> = None;
        let mut row_has_bad_sequence = false;
        if let Some(Value::String(needle)) = item.get("expect_error") {
            row_has_bad_sequence = needle.contains("sequence") || needle.contains("Sequence");
        }
        for obs in observations {
            let obj = obs.as_object().expect("observation must be an object");
            for key in [
                "sequence",
                "direction",
                "source_unit",
                "application",
                "payload_hex",
            ] {
                assert!(obj.contains_key(key), "{id}: observation missing {key}");
            }
            let sequence = obs
                .get("sequence")
                .and_then(Value::as_i64)
                .expect("sequence must be an integer");
            // Strict increase is a Python envelope rule; the intentional
            // bad-sequence rejection row pins the failure, so only enforce
            // it here for rows that are not that rejection case.
            if !row_has_bad_sequence {
                if let Some(prev) = previous {
                    assert!(sequence > prev, "{id}: sequence must strictly increase");
                }
                previous = Some(sequence);
            }
            let direction = obs
                .get("direction")
                .and_then(Value::as_str)
                .expect("direction must be a string");
            assert!(
                direction == "received" || direction == "sent-confirmed",
                "{id}: unexpected direction {direction}"
            );
            let application = obs
                .get("application")
                .and_then(Value::as_u64)
                .expect("application must be an integer");
            assert!(
                valid_applications(application),
                "{id}: unexpected application {application}"
            );
            let payload_hex = obs
                .get("payload_hex")
                .and_then(Value::as_str)
                .expect("payload_hex must be a string");
            let payload = hex::decode(payload_hex).unwrap_or_else(|e| panic!("{id}: bad hex: {e}"));
            // Every payload in this file is an exact wire SAL already
            // produced by the native encoders, so the existing Rust codecs
            // must accept and round-trip each one.
            validate_payload(application as u8, &payload)
                .unwrap_or_else(|e| panic!("{id}: validate_payload rejected {payload_hex}: {e}"));
            let sals = decode_sals(application as u8, &payload)
                .unwrap_or_else(|e| panic!("{id}: decode_sals rejected {payload_hex}: {e}"));
            assert_eq!(sals.len(), 1, "{id}: one SAL per payload_hex");
        }
        if let Some(expect) = item.get("expect") {
            for key in ["entries", "incomplete_transactions", "errors"] {
                if let Some(v) = expect.get(key) {
                    assert!(v.is_u64(), "{id}: expect.{key} must be an integer");
                }
            }
            if let Some(kinds) = expect.get("kinds").and_then(Value::as_array) {
                for kind in kinds {
                    let kind = kind.as_str().expect("kind must be a string");
                    assert!(
                        matches!(
                            kind,
                            "standard" | "unicode-text" | "built-in-icon" | "dynamic-icon" | "raw"
                        ),
                        "{id}: unexpected kind {kind}"
                    );
                }
            }
        } else if let Some(needle) = item.get("expect_error").and_then(Value::as_str) {
            assert!(!needle.is_empty(), "{id}: expect_error must not be empty");
        }
    }
}
