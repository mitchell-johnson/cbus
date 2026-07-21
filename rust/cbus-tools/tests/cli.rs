//! Full-system CLI tests for cbus-tools: decode / dump-labels argument
//! handling and output, plus interrogate against a scripted TCP unit.

use cbus_test_support::proc::{run, temp_path};
use serde_json::Value;
use std::io::{Read as _, Write as _};
use std::path::PathBuf;

const BIN: &str = env!("CARGO_BIN_EXE_cbus-tools");

fn fixture_project() -> String {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../rust-migration-harness/fixtures/project.xml")
        .to_string_lossy()
        .into_owned()
}

// ----------------------------------------------------------------- decode

#[test]
fn decode_pm_lighting_on_event() {
    let (status, out, _err) = run(BIN, &["decode", "05013800790148"]);
    assert!(status.success());
    // terminator convenience: the frame decodes after \r\n is appended
    assert!(out.contains("consumed: 16"), "{out}");
    assert!(out.contains("\"sal\":\"lighting_on\""), "{out}");
    assert!(out.contains("\"source_address\":1"), "{out}");
}

#[test]
fn decode_special_power_on() {
    let (status, out, _err) = run(BIN, &["decode", "+"]);
    assert!(status.success());
    assert!(out.contains("consumed: 1"), "{out}");
    assert!(out.contains("power_on"), "{out}");
}

#[test]
fn decode_client_frame_with_confirmation() {
    let (status, out, _err) = run(BIN, &["decode", "-c", "\\053800790149g"]);
    assert!(status.success());
    assert!(out.contains("\"confirmation\":\"g\""), "{out}");
    assert!(out.contains("\"sal\":\"lighting_on\""), "{out}");
}

#[test]
fn decode_no_checksum_flag() {
    let (status, out, _err) = run(BIN, &["decode", "-C", "050138007901"]);
    assert!(status.success());
    assert!(out.contains("\"sal\":\"lighting_on\""), "{out}");
}

#[test]
fn decode_bad_checksum_strict_reports_invalid() {
    let (status, out, _err) = run(BIN, &["decode", "05013800790100"]);
    assert!(status.success());
    assert!(out.contains("\"type\":\"invalid\""), "{out}");
}

#[test]
fn decode_bad_checksum_lenient_still_decodes() {
    let (status, out, _err) = run(BIN, &["decode", "-S", "05013800790100"]);
    assert!(status.success());
    assert!(out.contains("\"sal\":\"lighting_on\""), "{out}");
}

#[test]
fn decode_cancel_token_reports_none() {
    // client-side '?' cancels the pending command: bytes consumed, no
    // packet produced
    let (status, out, _err) = run(BIN, &["decode", "-c", "AB?"]);
    assert!(status.success());
    assert!(out.contains("consumed: 3"), "{out}");
    assert!(out.contains("packet: None"), "{out}");
}

#[test]
fn decode_missing_argument_usage_error() {
    let (status, _out, err) = run(BIN, &["decode"]);
    assert_eq!(status.code(), Some(2));
    assert!(!err.is_empty());
}

#[test]
fn help_exits_zero_and_lists_subcommands() {
    let (status, out, _err) = run(BIN, &["--help"]);
    assert!(status.success());
    for sub in ["decode", "dump-labels", "interrogate"] {
        assert!(out.contains(sub), "missing {sub} in help: {out}");
    }
}

#[test]
fn unknown_subcommand_usage_error() {
    let (status, _out, err) = run(BIN, &["frobnicate"]);
    assert_eq!(status.code(), Some(2));
    assert!(!err.is_empty());
}

// ------------------------------------------------------------ dump-labels

#[test]
fn dump_labels_fixture_structure() {
    let (status, out, _err) = run(BIN, &["dump-labels", &fixture_project()]);
    assert!(status.success());
    let v: Value = serde_json::from_str(out.trim()).expect("JSON output");
    let net = &v["254"];
    assert_eq!(net["name"], "Harness Network");
    assert_eq!(net["networknumber"], 1);
    assert_eq!(net["applications"]["56"]["name"], "Lighting");
    assert_eq!(net["applications"]["56"]["groups"]["1"], "Kitchen Bench");
    assert_eq!(net["applications"]["56"]["groups"]["10"], "Lounge");
    assert_eq!(net["applications"]["48"]["groups"]["11"], "Deck");
    assert_eq!(net["units"], serde_json::json!({}));
}

#[test]
fn dump_labels_pretty_indents() {
    let (status, out, _err) = run(BIN, &["dump-labels", "-p", "2", &fixture_project()]);
    assert!(status.success());
    assert!(out.starts_with("{\n  \""), "{out}");
    // pretty and compact forms parse to the same value
    let (_, compact, _) = run(BIN, &["dump-labels", &fixture_project()]);
    let a: Value = serde_json::from_str(out.trim()).unwrap();
    let b: Value = serde_json::from_str(compact.trim()).unwrap();
    assert_eq!(a, b);
}

#[test]
fn dump_labels_output_file() {
    let path = temp_path("labels.json");
    let (status, out, _err) = run(
        BIN,
        &[
            "dump-labels",
            "-o",
            path.to_str().unwrap(),
            &fixture_project(),
        ],
    );
    assert!(status.success());
    assert!(out.is_empty(), "no stdout when -o is given: {out}");
    let content = std::fs::read_to_string(&path).unwrap();
    std::fs::remove_file(&path).ok();
    let v: Value = serde_json::from_str(&content).unwrap();
    assert_eq!(
        v["254"]["applications"]["56"]["groups"]["1"],
        "Kitchen Bench"
    );
}

#[test]
fn dump_labels_missing_file_exits_nonzero() {
    let (status, _out, err) = run(BIN, &["dump-labels", "/nonexistent/project.cbz"]);
    assert_eq!(status.code(), Some(1));
    assert!(err.contains("error"), "{err}");
}

#[test]
fn dump_labels_garbage_xml_exits_nonzero() {
    let path = temp_path("garbage.xml");
    std::fs::write(&path, "not xml {").unwrap();
    let (status, _out, err) = run(BIN, &["dump-labels", path.to_str().unwrap()]);
    std::fs::remove_file(&path).ok();
    assert_eq!(status.code(), Some(1));
    assert!(err.contains("error"), "{err}");
}

// ------------------------------------------------------------ interrogate

/// A scripted "unit 0" behind a fake CNI: replies to identify/recall
/// point-to-point frames for unit 0 with a reply CAL carrying `name`.
fn scripted_unit(name: &'static [u8]) -> (std::thread::JoinHandle<()>, u16) {
    let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    let port = listener.local_addr().unwrap().port();
    let handle = std::thread::spawn(move || {
        let Ok((mut stream, _)) = listener.accept() else {
            return;
        };
        let mut buf = Vec::new();
        let mut chunk = [0u8; 1024];
        loop {
            let n = match stream.read(&mut chunk) {
                Ok(0) | Err(_) => return,
                Ok(n) => n,
            };
            buf.extend_from_slice(&chunk[..n]);
            while let Some(pos) = buf.iter().position(|&b| b == b'\r') {
                let frame: Vec<u8> = buf.drain(..pos + 1).collect();
                let text = String::from_utf8_lossy(&frame).into_owned();
                // \46 <unit> 00 <cal...><conf>: reply only for unit 0
                if text.starts_with("\\460000") {
                    // reply CAL: header 0x80|(1+len), param 0x01, data
                    let mut cal = vec![0x80 | (1 + name.len() as u8), 0x01];
                    cal.extend_from_slice(name);
                    let sum: u32 = cal.iter().map(|&b| b as u32).sum();
                    cal.push((sum.wrapping_neg() & 0xff) as u8);
                    let mut line = cal
                        .iter()
                        .map(|b| format!("{b:02X}"))
                        .collect::<String>()
                        .into_bytes();
                    line.extend_from_slice(b"\r\n");
                    let _ = stream.write_all(&line);
                }
            }
        }
    });
    (handle, port)
}

#[test]
fn interrogate_requires_unit_or_discover() {
    let (_h, port) = scripted_unit(b"TESTUNIT");
    let addr = format!("127.0.0.1:{port}");
    let (status, _out, err) = run(BIN, &["interrogate", "--tcp", &addr, "--timeout", "0.3"]);
    assert_eq!(status.code(), Some(1));
    assert!(err.contains("pass --unit N or --discover"), "{err}");
}

#[test]
fn interrogate_discover_finds_scripted_unit() {
    let (_h, port) = scripted_unit(b"TESTUNIT");
    let addr = format!("127.0.0.1:{port}");
    let (status, out, _err) = run(
        BIN,
        &[
            "interrogate",
            "--tcp",
            &addr,
            "--discover",
            "--max-address",
            "1",
            "--timeout",
            "0.5",
        ],
    );
    assert!(status.success());
    assert!(out.contains("Unit 0 (0x00): TESTUNIT"), "{out}");
    // unit 1 never replies and must not be reported
    assert!(!out.contains("Unit 1"), "{out}");
}

#[test]
fn interrogate_unit_reports_attributes() {
    let (_h, port) = scripted_unit(b"DIMMER12");
    let addr = format!("127.0.0.1:{port}");
    let (status, out, _err) = run(
        BIN,
        &[
            "interrogate",
            "--tcp",
            &addr,
            "--unit",
            "0",
            "--timeout",
            "0.5",
        ],
    );
    assert!(status.success());
    assert!(out.contains("attr 0x01"), "{out}");
    assert!(out.contains("attr 0xFA"), "{out}");
    assert!(out.contains("Unit 0 (0x00): DIMMER12"), "{out}");
}

#[test]
fn interrogate_connection_refused_exits_nonzero() {
    let dead = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    let port = dead.local_addr().unwrap().port();
    drop(dead);
    let addr = format!("127.0.0.1:{port}");
    let (status, _out, err) = run(
        BIN,
        &[
            "interrogate",
            "--tcp",
            &addr,
            "--unit",
            "0",
            "--timeout",
            "0.5",
        ],
    );
    assert_eq!(status.code(), Some(1));
    assert!(!err.is_empty());
}
