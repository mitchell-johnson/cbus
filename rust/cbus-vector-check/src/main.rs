//! Golden-vector runner for the repository's protocol compatibility data.
//! Reads every *.jsonl in the given directory, evaluates each vector, and
//! prints `protocol-vectors: <passed>/<total> PASS|FAIL` as the last line.
//! Exit code 0 iff all pass.

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
                        let id = v.get("id").and_then(Value::as_str).unwrap_or("?");
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
        "encode.jsonl" | "aircon.jsonl" => check_encode(v),
        "checksum.jsonl" => check_checksum(v),
        "ramp_rates.jsonl" => check_ramp(v),
        "mqtt_topics.jsonl" => check_topic(v),
        "ha_discovery.jsonl" => check_ha(v),
        "kfi.jsonl" => check_kfi(v),
        "cni_discovery.jsonl" => check_cni_discovery(v),
        _ => Err(format!("unimplemented suite {fname}")),
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
    use cbus_protocol::cni_discovery::{decode_discovery_reply, DISCOVERY_QUERY};

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
