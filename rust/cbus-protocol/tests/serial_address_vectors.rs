//! P3a vectors for the pure selected-serial address codec.
//!
//! The committed file `testdata/vectors/serial_address.jsonl` pins the exact
//! native wire bytes of the Python `pci_serial_address` oracle (encode +
//! receipt classification). This test drives the pure Rust `cbus-protocol`
//! codec only: no I/O, no movement claim. A `matched` receipt establishes
//! packet correlation only; `movement_verified` is always false.

use cbus_protocol::serial_address::{classify_receipt, encode_serial_address};
use serde_json::Value;
use std::collections::HashSet;

const VECTORS: &str = concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../testdata/vectors/serial_address.jsonl"
);

fn rows() -> Vec<Value> {
    let text = std::fs::read_to_string(VECTORS)
        .unwrap_or_else(|e| panic!("missing serial-address vectors {VECTORS}: {e}"));
    let rows: Vec<Value> = text
        .lines()
        .filter(|l| !l.trim().is_empty())
        .map(|l| serde_json::from_str(l).expect("vector line is valid JSON"))
        .collect();
    assert!(!rows.is_empty(), "vector file must not be empty");
    rows
}

fn get_str(item: &Value, id: &str, key: &str) -> String {
    item.get(key)
        .and_then(Value::as_str)
        .unwrap_or_else(|| panic!("{id}: missing string field {key}"))
        .to_string()
}

fn get_u8(item: &Value, id: &str, key: &str) -> u8 {
    let n = item
        .get(key)
        .and_then(Value::as_u64)
        .unwrap_or_else(|| panic!("{id}: missing integer field {key}"));
    u8::try_from(n).unwrap_or_else(|_| panic!("{id}: field {key} out of u8 range"))
}

fn get_bool(item: &Value, id: &str, key: &str) -> bool {
    item.get(key)
        .and_then(Value::as_bool)
        .unwrap_or_else(|| panic!("{id}: missing boolean field {key}"))
}

fn get_str_list(item: &Value, id: &str, key: &str) -> Vec<String> {
    item.get(key)
        .and_then(Value::as_array)
        .unwrap_or_else(|| panic!("{id}: missing array field {key}"))
        .iter()
        .map(|v| {
            v.as_str()
                .unwrap_or_else(|| panic!("{id}: field {key} must hold strings"))
                .to_string()
        })
        .collect()
}

fn get_opt_u8(value: &Value, id: &str, key: &str) -> Option<u8> {
    match value.get(key) {
        None | Some(Value::Null) => None,
        Some(Value::Number(n)) => Some(
            u8::try_from(
                n.as_u64()
                    .unwrap_or_else(|| panic!("{id}: field {key} not an integer")),
            )
            .unwrap_or_else(|_| panic!("{id}: field {key} out of u8 range")),
        ),
        Some(other) => panic!("{id}: field {key} must be an integer or null, got {other}"),
    }
}

#[test]
fn serial_address_vectors() {
    let rows = rows();
    let mut ids = HashSet::new();
    for item in &rows {
        let id = get_str(item, "<row>", "id");
        assert!(ids.insert(id.clone()), "duplicate vector id {id}");
        let kind = get_str(item, &id, "kind");
        match kind.as_str() {
            "encode" => {
                let serial = get_str(item, &id, "serial");
                let destination = get_u8(item, &id, "destination");
                let command_checksum = get_bool(item, &id, "command_checksum");
                let confirmation = get_str(item, &id, "confirmation");
                assert_eq!(
                    confirmation.len(),
                    1,
                    "{id}: confirmation must be one character"
                );
                let expected = get_str(item, &id, "expect_frame_ascii");
                let frame = encode_serial_address(
                    &serial,
                    destination,
                    command_checksum,
                    confirmation.as_bytes()[0],
                )
                .unwrap_or_else(|e| panic!("{id}: encode rejected valid input: {e}"));
                assert_eq!(frame, expected.as_bytes(), "{id}: encode wire bytes differ");
            }
            "encode_error" => {
                let serial = get_str(item, &id, "serial");
                let destination = get_u8(item, &id, "destination");
                let command_checksum = get_bool(item, &id, "command_checksum");
                let confirmation = get_str(item, &id, "confirmation");
                assert_eq!(
                    confirmation.len(),
                    1,
                    "{id}: confirmation must be one character"
                );
                assert!(
                    encode_serial_address(
                        &serial,
                        destination,
                        command_checksum,
                        confirmation.as_bytes()[0]
                    )
                    .is_err(),
                    "{id}: encode accepted invalid input"
                );
            }
            "receipt" => {
                let raw_ascii = get_str(item, &id, "raw_ascii");
                let serial = get_str(item, &id, "serial");
                let destination = get_u8(item, &id, "destination");
                let local_unit = get_u8(item, &id, "local_unit");
                let confirmation = get_str(item, &id, "confirmation");
                let expect_status = get_str(item, &id, "expect_status");
                let expect_matched = get_bool(item, &id, "expect_matched");
                let receipt = classify_receipt(
                    raw_ascii.as_bytes(),
                    &serial,
                    destination,
                    local_unit,
                    confirmation.as_bytes()[0],
                )
                .unwrap_or_else(|e| panic!("{id}: classifier rejected valid arguments: {e}"));
                assert_eq!(
                    receipt.status.as_str(),
                    expect_status,
                    "{id}: receipt status differs (issues: {:?})",
                    receipt.issues
                );
                assert_eq!(
                    receipt.matched(),
                    expect_matched,
                    "{id}: receipt matched flag differs"
                );
                // Correlation only: the pure codec never verifies movement.
                assert!(
                    !receipt.movement_verified(),
                    "{id}: movement must never verify in the pure codec"
                );
                // Classification details pinned per vector (oracle-derived;
                // invalid-frame rows pin Rust framing semantics).
                assert_eq!(
                    receipt.issues,
                    get_str_list(item, &id, "expect_issues"),
                    "{id}: receipt issues differ"
                );
                assert_eq!(
                    receipt.errors,
                    get_str_list(item, &id, "expect_errors"),
                    "{id}: receipt errors differ"
                );
                let confirmations: Vec<String> = receipt
                    .confirmations
                    .iter()
                    .map(|(code, status)| format!("{}{}", *code as char, status))
                    .collect();
                assert_eq!(
                    confirmations,
                    get_str_list(item, &id, "expect_confirmations"),
                    "{id}: receipt confirmations differ"
                );
                let notifications: Vec<String> = receipt
                    .notifications
                    .iter()
                    .map(|c| c.to_string())
                    .collect();
                assert_eq!(
                    notifications,
                    get_str_list(item, &id, "expect_notifications"),
                    "{id}: receipt notifications differ"
                );
                assert_eq!(
                    hex::encode(&receipt.pending).to_uppercase(),
                    get_str(item, &id, "expect_pending_hex"),
                    "{id}: receipt pending bytes differ"
                );
                let expect_replies = item
                    .get("expect_replies")
                    .and_then(Value::as_array)
                    .unwrap_or_else(|| panic!("{id}: missing array field expect_replies"));
                assert_eq!(
                    receipt.replies.len(),
                    expect_replies.len(),
                    "{id}: reply count differs"
                );
                for (index, expect_reply) in expect_replies.iter().enumerate() {
                    let reply = &receipt.replies[index];
                    assert_eq!(
                        reply.header,
                        get_opt_u8(expect_reply, &id, "header"),
                        "{id}: reply {index} header differs"
                    );
                    assert_eq!(
                        reply.source,
                        get_opt_u8(expect_reply, &id, "source"),
                        "{id}: reply {index} source differs"
                    );
                    assert_eq!(
                        reply.destination,
                        get_opt_u8(expect_reply, &id, "destination"),
                        "{id}: reply {index} destination differs"
                    );
                    assert_eq!(
                        hex::encode(&reply.route).to_uppercase(),
                        expect_reply
                            .get("route_hex")
                            .and_then(Value::as_str)
                            .unwrap_or_else(|| panic!("{id}: reply {index} missing route_hex")),
                        "{id}: reply {index} route differs"
                    );
                    assert_eq!(
                        reply.serial,
                        expect_reply
                            .get("serial")
                            .and_then(Value::as_str)
                            .unwrap_or_else(|| panic!("{id}: reply {index} missing serial")),
                        "{id}: reply {index} serial differs"
                    );
                    assert_eq!(
                        reply.serial_known,
                        expect_reply
                            .get("serial_known")
                            .and_then(Value::as_bool)
                            .unwrap_or_else(|| panic!("{id}: reply {index} missing serial_known")),
                        "{id}: reply {index} known flag differs"
                    );
                    assert_eq!(
                        hex::encode(reply.opaque_tail).to_uppercase(),
                        expect_reply
                            .get("opaque_tail_hex")
                            .and_then(Value::as_str)
                            .unwrap_or_else(|| panic!(
                                "{id}: reply {index} missing opaque_tail_hex"
                            )),
                        "{id}: reply {index} opaque tail differs"
                    );
                }
                if let Some(expect_serial) = item.get("expect_serial").and_then(Value::as_str) {
                    assert!(
                        !receipt.replies.is_empty(),
                        "{id}: expected a decoded reply"
                    );
                    assert_eq!(
                        receipt.replies[0].serial, expect_serial,
                        "{id}: decoded reply serial differs"
                    );
                    let expect_known = get_bool(item, &id, "expect_known");
                    assert_eq!(
                        receipt.replies[0].serial_known, expect_known,
                        "{id}: decoded reply known flag differs"
                    );
                    if let Some(tail) = item.get("expect_tail_hex").and_then(Value::as_str) {
                        assert_eq!(
                            hex::encode(receipt.replies[0].opaque_tail).to_uppercase(),
                            tail,
                            "{id}: opaque tail differs"
                        );
                    }
                }
            }
            other => panic!("{id}: unknown vector kind {other}"),
        }
    }
}
