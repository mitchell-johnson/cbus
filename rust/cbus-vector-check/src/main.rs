//! Golden-vector runner for the repository's protocol compatibility data.
//! Reads every *.jsonl in the given directory, evaluates each vector, and
//! prints `protocol-vectors: <passed>/<total> PASS|FAIL` as the last line.
//! Exit code 0 iff all pass.

use cbus_cgate::{AccessLevel, Response, Server};
use cbus_protocol::common::{cbus_checksum, duration_to_ramp_rate, ramp_rate_to_duration};
use cbus_protocol::decode::decode_packet;
use cbus_protocol::json::{packet_from_json, packet_to_json, JsonObject};
use cbus_protocol::{Meta, Packet};
use serde_json::Value;

const MAX_FAILURES_PRINTED: usize = 50;

fn main() {
    let mut args = std::env::args().skip(1);
    let dir = match args.next() {
        Some(d) => d,
        None => {
            eprintln!("usage: cbus-vector-check <vectors-dir> [--file <name>]");
            std::process::exit(2);
        }
    };
    let mut only_file: Option<String> = None;
    while let Some(a) = args.next() {
        if a == "--file" {
            only_file = args.next();
        }
    }

    let mut entries: Vec<_> = std::fs::read_dir(&dir)
        .unwrap_or_else(|e| {
            eprintln!("cannot read {dir}: {e}");
            std::process::exit(2);
        })
        .filter_map(|e| e.ok())
        .map(|e| e.path())
        .filter(|p| p.extension().map(|x| x == "jsonl").unwrap_or(false))
        .collect();
    entries.sort();

    let mut total = 0usize;
    let mut passed = 0usize;
    let mut printed = 0usize;

    for path in &entries {
        let fname = path.file_name().unwrap().to_string_lossy().to_string();
        if let Some(only) = &only_file {
            if &fname != only {
                continue;
            }
        }
        let content = std::fs::read_to_string(path).expect("read vector file");
        let mut file_total = 0usize;
        let mut file_passed = 0usize;
        for line in content.lines() {
            if line.trim().is_empty() {
                continue;
            }
            let v: Value = serde_json::from_str(line).expect("vector json");
            file_total += 1;
            let result = check_vector(&fname, &v);
            match result {
                Ok(()) => file_passed += 1,
                Err(reason) => {
                    if printed < MAX_FAILURES_PRINTED {
                        let id = v
                            .get("id")
                            .or_else(|| v.get("name"))
                            .and_then(Value::as_str)
                            .unwrap_or("?");
                        println!("  FAIL {id}: {reason}");
                        printed += 1;
                    }
                }
            }
        }
        total += file_total;
        passed += file_passed;
        let status = if file_passed == file_total {
            "PASS"
        } else {
            "FAIL"
        };
        println!("  {fname}: {file_passed}/{file_total} {status}");
    }

    let ok = passed == total && total > 0;
    println!(
        "protocol-vectors: {passed}/{total} {}",
        if ok { "PASS" } else { "FAIL" }
    );
    std::process::exit(if ok { 0 } else { 1 });
}

fn check_vector(fname: &str, v: &Value) -> Result<(), String> {
    match fname {
        "decode_from_pci.jsonl" | "decode_to_pci.jsonl" => check_decode(v),
        "encode.jsonl"
        | "dali.jsonl"
        | "aircon.jsonl"
        | "audio.jsonl"
        | "measurement.jsonl"
        | "security.jsonl"
        | "access_control.jsonl"
        | "mediatransport.jsonl"
        | "telephony.jsonl"
        | "identify.jsonl"
        | "shortmessage.jsonl"
        | "ereport.jsonl"
        | "network_management.jsonl" => check_encode(v),
        "checksum.jsonl" => check_checksum(v),
        "ramp_rates.jsonl" => check_ramp(v),
        "mqtt_topics.jsonl" => check_topic(v),
        "ha_discovery.jsonl" => check_ha(v),
        "kfi.jsonl" => check_kfi(v),
        "cni_discovery.jsonl" => check_cni_discovery(v),
        "cgate_event_fanout.jsonl" => check_cgate_event_fanout(v),
        "cgate_dbsetxml.jsonl" => check_cgate_dbsetxml(v),
        _ => Err(format!("unimplemented suite {fname}")),
    }
}

const DBSETXML_TYPED_TREE_SEED: &str =
    include_str!("../../testdata/fixtures/cgate_dbsetxml_typed_tree_seed.xml");

/// Exercise a real in-memory C-Gate database transaction. The five synthetic
/// typed-tree rows start from a committed pre-state whose OIDs match their
/// selected targets. The combined Network/Unit row starts from an empty
/// network and compares against the separately captured native readback.
fn check_cgate_dbsetxml(v: &Value) -> Result<(), String> {
    let name = need_str(v, "name")?;
    let setup = need_str(v, "setup")?;
    let basis = need_str(v, "basis")?;
    let target = need_str(v, "target")?;
    let document = need_str(v, "document")?;
    let expected_reply = need_str(v, "reply")?;
    let readback_target = need_str(v, "readback_target")?;
    let expected_readback = need_str(v, "readback")?;
    if document.is_empty() || expected_readback.is_empty() || expected_reply.is_empty() {
        return Err(format!(
            "{name}: document, reply, and readback must be nonempty"
        ));
    }
    if !matches!(setup, "typed-tree" | "native-network-unit") {
        return Err(format!("{name}: unsupported DBSETXML setup {setup:?}"));
    }
    let expected_basis = if setup == "native-network-unit" {
        "native-loopback"
    } else {
        "modeled-fixture"
    };
    if basis != expected_basis {
        return Err(format!(
            "{name}: {basis:?} provenance cannot support {setup:?} setup"
        ));
    }
    if setup == "native-network-unit" {
        let capture: Value = serde_json::from_str(include_str!(
            "../../testdata/fixtures/native_cgate_dbsetxml_combined.json"
        ))
        .map_err(|error| format!("{name}: invalid committed native capture: {error}"))?;
        if capture["schema"] != "native-cgate-dbsetxml-combined-v1"
            || capture["oracle"]["version"] != "3.4.0 build 2001"
            || capture["document"].as_str() != Some(document)
            || capture["reply"].as_str() != Some(expected_reply)
            || capture["network_readback"].as_str() != Some(expected_readback)
        {
            return Err(format!(
                "{name}: native vector does not match the owned loopback capture"
            ));
        }
    }

    let parsed = roxmltree::Document::parse(document)
        .map_err(|error| format!("{name}: invalid replacement XML: {error}"))?;
    let new_oid = direct_xml_field(parsed.root_element(), "OID")
        .ok_or_else(|| format!("{name}: replacement XML has no root OID"))?;
    let expected_target = if setup == "typed-tree" {
        format!("!{new_oid}")
    } else {
        "//XCOMB/254".to_string()
    };
    if readback_target != expected_target {
        return Err(format!(
            "{name}: readback target {readback_target:?} is not the replacement {expected_target:?}"
        ));
    }

    let mut server = Server::new(AccessLevel::Program).with_programming(true);
    expect_status(
        name,
        "PROJECT NEW",
        server.handle("[seed] PROJECT NEW XCOMB"),
        200,
    )?;
    expect_status(
        name,
        "DBCREATENET",
        server.handle("[seed] DBCREATENET 254 Local Cni 127.0.0.1:1"),
        200,
    )?;
    if setup == "typed-tree" {
        let seed = roxmltree::Document::parse(DBSETXML_TYPED_TREE_SEED)
            .map_err(|error| format!("{name}: invalid committed seed XML: {error}"))?;
        let selected_oid = target
            .strip_prefix('!')
            .ok_or_else(|| format!("{name}: typed-tree target must be an OID"))?;
        let selected = seed
            .descendants()
            .filter(|node| node.is_element())
            .find(|node| direct_xml_field(*node, "OID") == Some(selected_oid))
            .ok_or_else(|| format!("{name}: target OID is absent from committed seed"))?;
        if selected.tag_name().name() != parsed.root_element().tag_name().name() {
            return Err(format!(
                "{name}: target type {} differs from replacement type {}",
                selected.tag_name().name(),
                parsed.root_element().tag_name().name()
            ));
        }
        expect_status(
            name,
            "seed DBSETXML",
            server.handle_document("[seed] DBSETXML //XCOMB/254", DBSETXML_TYPED_TREE_SEED),
            301,
        )?;
    } else if target != "//XCOMB/254" {
        return Err(format!(
            "{name}: native-network-unit setup requires //XCOMB/254"
        ));
    }
    expect_xml(
        name,
        "pre-state DBGETXML",
        server.handle(&format!("[before] DBGETXML {target}")),
    )?;

    let write = server.handle_document(&format!("[write] DBSETXML {target}"), document);
    if write.status != 301 || !write.lines.is_empty() || write.final_text != expected_reply {
        return Err(format!(
            "{name}: DBSETXML reply {:?} != {expected_reply:?}",
            write
        ));
    }
    let got = expect_xml(
        name,
        "replacement DBGETXML",
        server.handle(&format!("[read] DBGETXML {readback_target}")),
    )?;
    if got != expected_readback {
        return Err(format!(
            "{name}: DBGETXML readback {got:?} != {expected_readback:?}"
        ));
    }
    if setup == "typed-tree" {
        let retired = server.handle(&format!("[retired] DBGETXML {target}"));
        if retired.status != 401 {
            return Err(format!(
                "{name}: replaced target still resolves: {retired:?}"
            ));
        }
    }
    Ok(())
}

fn direct_xml_field<'a>(node: roxmltree::Node<'a, '_>, field: &str) -> Option<&'a str> {
    node.children()
        .find(|child| child.is_element() && child.tag_name().name() == field)
        .and_then(|child| child.text())
}

fn expect_status(name: &str, step: &str, response: Response, status: u16) -> Result<(), String> {
    if response.status != status {
        return Err(format!("{name}: {step} failed: {response:?}"));
    }
    Ok(())
}

fn expect_xml(name: &str, step: &str, response: Response) -> Result<String, String> {
    if response.status != 200 || response.final_text != "200 OK" || response.lines.len() != 1 {
        return Err(format!(
            "{name}: {step} was not one XML snippet: {response:?}"
        ));
    }
    response.lines[0]
        .strip_prefix("347-")
        .filter(|body| !body.is_empty())
        .map(str::to_owned)
        .ok_or_else(|| format!("{name}: {step} had no nonempty 347 XML body"))
}

fn check_cgate_event_fanout(v: &Value) -> Result<(), String> {
    // Status and timestamped event levels were observed through separate
    // owned native loopback captures. Config remains inferred from pinned
    // BA/BG bytecode, not a native trigger capture.
    let id = need_str(v, "id")?;
    let mode_text = need_str(v, "mode")?;
    let line = need_str(v, "line")?;
    let basis = need_str(v, "basis")?;
    let expected_basis = if line.starts_with("#s# ") {
        "native-loopback"
    } else if line.starts_with("#c# ") {
        "pinned-bytecode"
    } else if line.starts_with("#e# ") {
        "native_cgate_config_global_event_level.json"
    } else {
        return Err(format!("{id}: expected an event, status, or config line"));
    };
    if basis != expected_basis {
        return Err(format!(
            "{id}: {basis:?} provenance cannot support a {expected_basis} row"
        ));
    }
    let mode = cbus_cgate::EventMode::parse(mode_text)
        .ok_or_else(|| format!("{id}: invalid EVENT mode {mode_text:?}"))?;
    let expected = need_bool(v, "deliver")?;
    let actual = mode.delivers_line(line);
    if actual != expected {
        return Err(format!(
            "{id}: EVENT {mode_text} delivered {actual}, expected {expected} for {line:?}"
        ));
    }
    Ok(())
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

fn need_u8(v: &Value, k: &str) -> Result<u8, String> {
    u8::try_from(need_u64(v, k)?).map_err(|_| format!("vector {k} is outside u8"))
}

fn need_kfi_values(v: &Value) -> Result<[u8; cbus_protocol::kfi::COUNT], String> {
    let values = v
        .get("values")
        .and_then(Value::as_array)
        .ok_or("vector missing values")?;
    values
        .iter()
        .map(|value| {
            let value = value
                .as_u64()
                .ok_or("KFI value must be an unsigned integer")?;
            u8::try_from(value).map_err(|_| format!("KFI value {value} is outside u8"))
        })
        .collect::<Result<Vec<_>, _>>()?
        .try_into()
        .map_err(|values: Vec<u8>| {
            format!(
                "expected {} KFI values, got {}",
                cbus_protocol::kfi::COUNT,
                values.len()
            )
        })
}

fn need_frames(v: &Value) -> Result<Vec<String>, String> {
    v.get("frames")
        .and_then(Value::as_array)
        .ok_or("vector missing frames")?
        .iter()
        .map(|frame| {
            frame
                .as_str()
                .map(str::to_owned)
                .ok_or_else(|| "KFI frame must be a string".to_string())
        })
        .collect()
}

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

fn check_encode(v: &Value) -> Result<(), String> {
    let obj = packet_from_json(v.get("packet").ok_or("vector missing packet")?)
        .map_err(|e| format!("from_json: {e}"))?;
    if let Some(encoding) = v.get("encoding").and_then(Value::as_str) {
        if encoding != "programming_request" {
            return Err(format!("unknown encode vector encoding {encoding}"));
        }
        let JsonObject::Cal(cal) = &obj else {
            return Err("programming_request requires a bare CAL object".to_string());
        };
        let got = cbus_protocol::packet::programming_request(need_u8(v, "unit")?, cal)
            .map_err(|e| format!("programming_request raised {e}"))?;
        let raw = hex::decode(need_str(v, "expect_encode_hex")?)
            .map_err(|e| format!("bad expect_encode_hex: {e}"))?;
        let mut expected = vec![b'\\'];
        expected.extend(hex::encode_upper(raw).bytes());
        expected.push(b'\r');
        if got != expected {
            return Err(format!(
                "programming_request {:?} != {:?}",
                String::from_utf8_lossy(&got),
                String::from_utf8_lossy(&expected)
            ));
        }
        if let Some(exp) = v.get("expect_encode_packet") {
            let exp = exp.as_str().ok_or("bad expect_encode_packet")?;
            let expected: Vec<u8> = exp.chars().map(|c| c as u32 as u8).collect();
            if got != expected {
                return Err(format!(
                    "programming_request {:?} != {:?}",
                    String::from_utf8_lossy(&got),
                    exp
                ));
            }
        }
        return Ok(());
    }
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

fn check_checksum(v: &Value) -> Result<(), String> {
    let data = hex::decode(need_str(v, "data_hex")?).map_err(|e| e.to_string())?;
    let got = cbus_checksum(&data) as u64;
    let expect = need_u64(v, "expect_checksum")?;
    if got != expect {
        return Err(format!("checksum {got} != {expect}"));
    }
    Ok(())
}

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

fn check_kfi(v: &Value) -> Result<(), String> {
    fn frames(
        unit: u8,
        requests: impl IntoIterator<Item = cbus_protocol::Cal>,
    ) -> Result<Vec<String>, String> {
        requests
            .into_iter()
            .map(|cal| {
                let packet = Packet::PointToPoint {
                    meta: Meta::new(true, 1),
                    unit_address: unit,
                    bridged: false,
                    hops: vec![],
                    cals: vec![cal],
                };
                let encoded = packet
                    .encode_packet()
                    .map_err(|e| format!("KFI request encode raised {e}"))?;
                let encoded = String::from_utf8(encoded)
                    .map_err(|e| format!("KFI request was not ASCII: {e}"))?;
                Ok(format!("\\{encoded}"))
            })
            .collect()
    }

    match need_str(v, "kind")? {
        "get" => {
            let got = frames(need_u8(v, "unit")?, cbus_protocol::kfi::get_requests())?;
            let expect = need_frames(v)?;
            if got != expect {
                return Err(format!("frames {got:?} != {expect:?}"));
            }
        }
        "set" => {
            let requests = cbus_protocol::kfi::set_requests(need_kfi_values(v)?)
                .map_err(|e| format!("KFI set raised {e}"))?;
            let got = frames(need_u8(v, "unit")?, requests)?;
            let expect = need_frames(v)?;
            if got != expect {
                return Err(format!("frames {got:?} != {expect:?}"));
            }
        }
        "reply" => {
            let data = hex::decode(need_str(v, "data_hex")?).map_err(|e| e.to_string())?;
            let got = cbus_protocol::kfi::decode_reply(&data)
                .map_err(|e| format!("KFI reply decode raised {e}"))?;
            let expect = need_kfi_values(v)?;
            if got != expect {
                return Err(format!("values {got:?} != {expect:?}"));
            }
        }
        "reply_error" => {
            let data = hex::decode(need_str(v, "data_hex")?).map_err(|e| e.to_string())?;
            if let Ok(values) = cbus_protocol::kfi::decode_reply(&data) {
                return Err(format!("KFI reply unexpectedly decoded as {values:?}"));
            }
        }
        "set_error" => {
            if let Ok(requests) = cbus_protocol::kfi::set_requests(need_kfi_values(v)?) {
                return Err(format!("KFI set unexpectedly encoded as {requests:?}"));
            }
        }
        other => return Err(format!("unknown KFI vector kind {other}")),
    }
    Ok(())
}

fn check_cni_discovery(v: &Value) -> Result<(), String> {
    use cbus_protocol::cni_discovery::{
        build_cni2_discovery_query, decode_cni2_discovery_reply, decode_discovery_reply,
        decode_legacy_discovery_reply, Cni2SerialNumber, DISCOVERY_QUERY, LEGACY_DISCOVERY_QUERY,
    };
    use std::net::Ipv4Addr;

    match need_str(v, "kind")? {
        "query" => {
            let got = hex::encode(DISCOVERY_QUERY);
            let expect = need_str(v, "expect_hex")?;
            if got != expect {
                return Err(format!("query {got} != {expect}"));
            }
        }
        "reply" => {
            let wire = hex::decode(need_str(v, "wire_hex")?).map_err(|e| e.to_string())?;
            let reply =
                decode_discovery_reply(&wire).map_err(|e| format!("reply decode raised {e}"))?;
            let got = serde_json::json!({
                "unknown1_hex": hex::encode(reply.unknown1),
                "product_id": reply.product_id,
                "product": reply.product_name(),
                "service_port": reply.service_port,
                "status": reply.status,
                "trailer_hex": hex::encode(reply.trailer),
                "visible_by_default": reply.visible_by_default(),
            });
            let expect = v.get("expect").ok_or("vector missing expect")?;
            if &got != expect {
                return Err(format!("reply {got} != {expect}"));
            }
        }
        "reply_error" => {
            let wire = hex::decode(need_str(v, "wire_hex")?).map_err(|e| e.to_string())?;
            let error = decode_discovery_reply(&wire)
                .expect_err("reply_error vector unexpectedly decoded")
                .to_string();
            let expect = need_str(v, "expect_error")?;
            if !error.contains(expect) {
                return Err(format!("error {error:?} does not contain {expect:?}"));
            }
        }
        "legacy_query" => {
            let got = hex::encode(LEGACY_DISCOVERY_QUERY);
            let expect = need_str(v, "expect_hex")?;
            if got != expect {
                return Err(format!("legacy query {got} != {expect}"));
            }
        }
        "legacy_reply" => {
            let wire = hex::decode(need_str(v, "wire_hex")?).map_err(|e| e.to_string())?;
            let reply = decode_legacy_discovery_reply(&wire)
                .map_err(|e| format!("legacy reply decode raised {e}"))?;
            let got = serde_json::json!({"service_port": reply.service_port});
            let expect = v.get("expect").ok_or("vector missing expect")?;
            if &got != expect {
                return Err(format!("legacy reply {got} != {expect}"));
            }
        }
        "legacy_reply_error" => {
            let wire = hex::decode(need_str(v, "wire_hex")?).map_err(|e| e.to_string())?;
            let error = decode_legacy_discovery_reply(&wire)
                .expect_err("legacy_reply_error vector unexpectedly decoded")
                .to_string();
            let expect = need_str(v, "expect_error")?;
            if !error.contains(expect) {
                return Err(format!("error {error:?} does not contain {expect:?}"));
            }
        }
        "cgate_cni2_query" => {
            let sequence = u32::try_from(need_u64(v, "sequence")?)
                .map_err(|_| "vector sequence is outside u32".to_owned())?;
            let got = hex::encode(build_cni2_discovery_query(sequence));
            let expect = need_str(v, "expect_hex")?;
            if got != expect {
                return Err(format!("C-Gate CNI2 query {got} != {expect}"));
            }
        }
        "cgate_cni2_reply" => {
            let wire = hex::decode(need_str(v, "wire_hex")?).map_err(|e| e.to_string())?;
            let source_ip = need_str(v, "source_ip")?
                .parse::<Ipv4Addr>()
                .map_err(|e| format!("invalid source_ip: {e}"))?;
            let reply = decode_cni2_discovery_reply(&wire, source_ip)
                .map_err(|e| format!("C-Gate CNI2 reply decode raised {e}"))?;
            let got = serde_json::json!({
                "sequence": reply.sequence,
                "product_id": reply.product_id,
                "product": reply.product_name(),
                "ip_address": reply.ip_address.to_string(),
                "service_port": reply.service_port,
                "status": reply.status,
                "status_name": reply.status_name(),
                "mac": reply.mac_string(),
                "serial": reply.serial_number.map(Cni2SerialNumber::cgate_string),
                "cbus_unit_address": reply.cbus_unit_address,
            });
            let expect = v.get("expect").ok_or("vector missing expect")?;
            if &got != expect {
                return Err(format!("C-Gate CNI2 reply {got} != {expect}"));
            }
        }
        "cgate_cni2_reply_error" => {
            let wire = hex::decode(need_str(v, "wire_hex")?).map_err(|e| e.to_string())?;
            let source_ip = need_str(v, "source_ip")?
                .parse::<Ipv4Addr>()
                .map_err(|e| format!("invalid source_ip: {e}"))?;
            let error = decode_cni2_discovery_reply(&wire, source_ip)
                .expect_err("cgate_cni2_reply_error vector unexpectedly decoded")
                .to_string();
            let expect = need_str(v, "expect_error")?;
            if !error.contains(expect) {
                return Err(format!("error {error:?} does not contain {expect:?}"));
            }
        }
        other => return Err(format!("unknown CNI discovery vector kind {other}")),
    }
    Ok(())
}

fn check_topic(v: &Value) -> Result<(), String> {
    cbus_mqtt::vector_check::check_topic(v)
}

fn check_ha(v: &Value) -> Result<(), String> {
    cbus_mqtt::vector_check::check_ha(v)
}

#[cfg(test)]
mod tests {
    use super::{check_vector, expect_xml};
    use cbus_cgate::Response;

    fn dbsetxml_rows() -> Vec<serde_json::Value> {
        include_str!("../../testdata/vectors/cgate_dbsetxml.jsonl")
            .lines()
            .map(|line| serde_json::from_str(line).unwrap())
            .collect()
    }

    #[test]
    fn cgate_dbsetxml_vectors_execute_all_six_transactions() {
        let rows = dbsetxml_rows();
        assert_eq!(rows.len(), 6);
        let mut modeled = 0;
        let mut native = 0;
        for row in rows {
            check_vector("cgate_dbsetxml.jsonl", &row).unwrap();
            match row["basis"].as_str().unwrap() {
                "modeled-fixture" => modeled += 1,
                "native-loopback" => native += 1,
                other => panic!("unexpected evidence basis {other}"),
            }
        }
        assert_eq!((modeled, native), (5, 1));
    }

    #[test]
    fn cgate_dbsetxml_rejects_missing_setup_and_changed_expected_output() {
        let mut row = dbsetxml_rows().remove(0);
        let original = row.clone();
        row["target"] = "!00000000-0000-4000-8000-000000000099".into();
        assert!(check_vector("cgate_dbsetxml.jsonl", &row)
            .unwrap_err()
            .contains("absent from committed seed"));

        row = original.clone();
        row["setup"] = "skip".into();
        assert!(check_vector("cgate_dbsetxml.jsonl", &row)
            .unwrap_err()
            .contains("unsupported DBSETXML setup"));

        row = original.clone();
        row["basis"] = "native-loopback".into();
        assert!(check_vector("cgate_dbsetxml.jsonl", &row)
            .unwrap_err()
            .contains("provenance"));

        row = original.clone();
        row["reply"] = "301 OID=wrong".into();
        assert!(check_vector("cgate_dbsetxml.jsonl", &row)
            .unwrap_err()
            .contains("DBSETXML reply"));

        row = original.clone();
        row["readback"] = "<Level/>".into();
        assert!(check_vector("cgate_dbsetxml.jsonl", &row)
            .unwrap_err()
            .contains("DBGETXML readback"));

        row = original.clone();
        row["readback"] = "".into();
        assert!(check_vector("cgate_dbsetxml.jsonl", &row)
            .unwrap_err()
            .contains("must be nonempty"));

        row = original;
        row["document"] = "<Level>".into();
        assert!(check_vector("cgate_dbsetxml.jsonl", &row)
            .unwrap_err()
            .contains("invalid replacement XML"));
    }

    #[test]
    fn cgate_dbsetxml_rejects_empty_xml_response() {
        let response = Response {
            tag: "read".to_string(),
            lines: Vec::new(),
            final_text: "200 OK".to_string(),
            status: 200,
        };
        assert!(expect_xml("empty", "DBGETXML", response)
            .unwrap_err()
            .contains("not one XML snippet"));
    }

    #[test]
    fn cgate_dbsetxml_native_row_must_match_the_owned_capture() {
        let mut row = dbsetxml_rows().remove(5);
        row["readback"] = "<Network/>".into();
        assert!(check_vector("cgate_dbsetxml.jsonl", &row)
            .unwrap_err()
            .contains("does not match the owned loopback capture"));
    }

    #[test]
    fn cgate_event_fanout_vectors_check_source_distinctions() {
        let rows = include_str!("../../testdata/vectors/cgate_event_fanout.jsonl");
        let mut seen_status = 0;
        let mut seen_config = 0;
        let mut seen_event = 0;
        for row in rows.lines() {
            let value: serde_json::Value = serde_json::from_str(row).unwrap();
            check_vector("cgate_event_fanout.jsonl", &value).unwrap();
            match value["basis"].as_str().unwrap() {
                "native-loopback" => seen_status += 1,
                "pinned-bytecode" => seen_config += 1,
                "native_cgate_config_global_event_level.json" => seen_event += 1,
                other => panic!("unexpected evidence basis {other}"),
            }
        }
        assert_eq!((seen_status, seen_config, seen_event), (4, 4, 10));
    }

    #[test]
    fn cgate_event_fanout_rejects_false_config_observation_and_wrong_expectation() {
        let mut config = serde_json::json!({
            "id": "config-provenance",
            "mode": "e0s0c1",
            "line": "#c# model-change",
            "deliver": true,
            "basis": "native-loopback"
        });
        assert!(check_vector("cgate_event_fanout.jsonl", &config)
            .unwrap_err()
            .contains("provenance"));
        config["basis"] = "pinned-bytecode".into();
        config["deliver"] = false.into();
        assert!(check_vector("cgate_event_fanout.jsonl", &config)
            .unwrap_err()
            .contains("expected false"));
    }
}
