//! Runtime support for the generated golden-vector tests.
//!
//! `build.rs` emits one `#[test]` per vector in
//! `rust-migration-harness/vectors/*.jsonl`; each generated test calls
//! [`run_vector`] with its file, line index and vector id. The vectors are
//! read from the harness directory at test run time (never copied), so the
//! committed JSONL files stay the single source of truth.
//!
//! The per-suite check logic mirrors `cbus-vector-check` (the harness
//! contract in rust-migration-harness/README.md §4); the two are kept
//! deliberately independent so a bug in one shows up as a disagreement.

#![deny(missing_docs)]

use cbus_protocol::common::{cbus_checksum, duration_to_ramp_rate, ramp_rate_to_duration};
use cbus_protocol::decode::decode_packet;
use cbus_protocol::json::{packet_from_json, packet_to_json};
use serde_json::Value;
use std::collections::HashMap;
use std::sync::{Mutex, OnceLock};

/// Committed golden vectors, resolved relative to this crate so the tests
/// work from any working directory (including CI).
pub const VECTORS_DIR: &str = concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../rust-migration-harness/vectors"
);

/// All vectors of one JSONL file, parsed once per process and cached.
fn file_vectors(fname: &str) -> &'static [Value] {
    static CACHE: OnceLock<Mutex<HashMap<String, &'static [Value]>>> = OnceLock::new();
    let cache = CACHE.get_or_init(Default::default);
    let mut map = cache.lock().unwrap();
    if let Some(v) = map.get(fname) {
        return v;
    }
    let path = format!("{VECTORS_DIR}/{fname}");
    let content = std::fs::read_to_string(&path)
        .unwrap_or_else(|e| panic!("cannot read golden vectors {path}: {e}"));
    let parsed: Vec<Value> = content
        .lines()
        .filter(|l| !l.trim().is_empty())
        .map(|l| serde_json::from_str(l).expect("vector line is valid JSON"))
        .collect();
    let leaked: &'static [Value] = Box::leak(parsed.into_boxed_slice());
    map.insert(fname.to_string(), leaked);
    leaked
}

/// Evaluate the vector at `index` of `fname`, panicking with the failure
/// reason. `id` guards against the vector file drifting out of sync with
/// the generated tests (a stale build would silently test the wrong line).
pub fn run_vector(fname: &str, index: usize, id: &str) {
    let vectors = file_vectors(fname);
    let v = vectors
        .get(index)
        .unwrap_or_else(|| panic!("{fname} has no line {index} (vector {id}); rebuild the crate"));
    let got_id = v.get("id").and_then(Value::as_str).unwrap_or("?");
    assert_eq!(
        got_id, id,
        "{fname}:{index} changed underneath the generated tests; rebuild the crate"
    );
    let result = match fname {
        "decode_from_pci.jsonl" | "decode_to_pci.jsonl" => check_decode(v),
        "encode.jsonl" => check_encode(v),
        "checksum.jsonl" => check_checksum(v),
        "ramp_rates.jsonl" => check_ramp(v),
        "mqtt_topics.jsonl" => cbus_mqtt::vector_check::check_topic(v),
        "ha_discovery.jsonl" => cbus_mqtt::vector_check::check_ha(v),
        other => Err(format!("unknown vector file {other}")),
    };
    if let Err(reason) = result {
        panic!("{id}: {reason}");
    }
}

fn need_str<'a>(v: &'a Value, k: &str) -> Result<&'a str, String> {
    v.get(k)
        .and_then(Value::as_str)
        .ok_or_else(|| format!("vector missing {k}"))
}

fn need_bool(v: &Value, k: &str) -> Result<bool, String> {
    v.get(k)
        .and_then(Value::as_bool)
        .ok_or_else(|| format!("vector missing {k}"))
}

fn need_u64(v: &Value, k: &str) -> Result<u64, String> {
    v.get(k)
        .and_then(Value::as_u64)
        .ok_or_else(|| format!("vector missing {k}"))
}

/// decode_from_pci.jsonl / decode_to_pci.jsonl (README §4): run
/// `decode_packet` and compare consumed count, canonical packet JSON and —
/// when present — the re-serialised `encode_packet()` bytes.
fn check_decode(v: &Value) -> Result<(), String> {
    let wire = hex::decode(need_str(v, "wire_hex")?).map_err(|e| e.to_string())?;
    let checksum = need_bool(v, "checksum")?;
    let strict = need_bool(v, "strict")?;
    let from_pci = need_bool(v, "from_pci")?;
    let (p, consumed) = decode_packet(&wire, checksum, strict, from_pci);

    let expect_consumed = need_u64(v, "expect_consumed")? as usize;
    if consumed != expect_consumed {
        return Err(format!("consumed {consumed} != {expect_consumed}"));
    }
    let got = packet_to_json(p.as_ref());
    let expect = v.get("expect_packet").cloned().unwrap_or(Value::Null);
    if got != expect {
        return Err(format!("packet {got} != {expect}"));
    }
    match v.get("expect_reencode") {
        None | Some(Value::Null) => {}
        Some(Value::String(exp)) => {
            let p = p.ok_or("no packet to reencode")?;
            let re = p
                .encode_packet()
                .map_err(|e| format!("reencode raised {e}"))?;
            // expect_reencode is a latin-1 string
            let expected: Vec<u8> = exp.chars().map(|c| c as u32 as u8).collect();
            if re != expected {
                return Err(format!(
                    "reencode {:?} != {:?}",
                    String::from_utf8_lossy(&re),
                    exp
                ));
            }
        }
        Some(other) => return Err(format!("bad expect_reencode {other}")),
    }
    Ok(())
}

/// encode.jsonl (README §4): build the object from canonical JSON, compare
/// `encode()` bytes and (for packets) `encode_packet()` ASCII.
fn check_encode(v: &Value) -> Result<(), String> {
    let obj = packet_from_json(v.get("packet").ok_or("vector missing packet")?)
        .map_err(|e| format!("from_json: {e}"))?;
    let got = hex::encode(obj.encode().map_err(|e| format!("encode raised {e}"))?);
    let expect = need_str(v, "expect_encode_hex")?;
    if got != expect {
        return Err(format!("encode {got} != {expect}"));
    }
    if let Some(exp) = v.get("expect_encode_packet") {
        let exp = exp.as_str().ok_or("bad expect_encode_packet")?;
        let got2 = obj
            .encode_packet()
            .map_err(|e| format!("encode_packet raised {e}"))?;
        let expected: Vec<u8> = exp.chars().map(|c| c as u32 as u8).collect();
        if got2 != expected {
            return Err(format!(
                "encode_packet {:?} != {:?}",
                String::from_utf8_lossy(&got2),
                exp
            ));
        }
    }
    Ok(())
}

/// checksum.jsonl: `cbus_checksum` over the given bytes.
fn check_checksum(v: &Value) -> Result<(), String> {
    let data = hex::decode(need_str(v, "data_hex")?).map_err(|e| e.to_string())?;
    let got = cbus_checksum(&data) as u64;
    let expect = need_u64(v, "expect_checksum")?;
    if got != expect {
        return Err(format!("checksum {got} != {expect}"));
    }
    Ok(())
}

/// ramp_rates.jsonl: duration→code snap / code→duration exact lookup.
fn check_ramp(v: &Value) -> Result<(), String> {
    let input = need_u64(v, "in")?;
    let expect = need_u64(v, "expect")?;
    let got = match need_str(v, "kind")? {
        "duration_to_rate" => duration_to_ramp_rate(input as i64) as u64,
        "rate_to_duration" => ramp_rate_to_duration(input as u8)
            .ok_or_else(|| format!("invalid ramp rate code {input}"))?
            as u64,
        other => return Err(format!("unknown ramp kind {other}")),
    };
    if got != expect {
        return Err(format!("{got} != {expect}"));
    }
    Ok(())
}
