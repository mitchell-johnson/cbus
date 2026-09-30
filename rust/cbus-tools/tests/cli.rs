//! Full-system CLI tests for cbus-tools: decode / dump-labels argument
//! handling and output, plus interrogate against a scripted TCP unit.

use cbus_test_support::proc::{run, temp_path};
use serde_json::Value;
use std::io::{Read as _, Write as _};
use std::path::PathBuf;

const BIN: &str = env!("CARGO_BIN_EXE_cbus-tools");

fn fixture_project() -> String {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../testdata/fixtures/project.xml")
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
    for sub in [
        "decode",
        "dump-labels",
        "interrogate",
        "cni-discover",
        "cni-scan",
    ] {
        assert!(out.contains(sub), "missing {sub} in help: {out}");
    }
}

#[test]
fn unknown_subcommand_usage_error() {
    let (status, _out, err) = run(BIN, &["frobnicate"]);
    assert_eq!(status.code(), Some(2));
    assert!(!err.is_empty());
}

// --------------------------------------------------------- CNI discovery

#[test]
fn cni_discover_reports_valid_duplicate_hidden_and_malformed_datagrams() {
    let socket = std::net::UdpSocket::bind("127.0.0.1:0").unwrap();
    socket
        .set_read_timeout(Some(std::time::Duration::from_secs(2)))
        .unwrap();
    let port = socket.local_addr().unwrap().port();
    let peer = std::thread::spawn(move || {
        let mut query = [0u8; 64];
        let (size, source) = socket.recv_from(&mut query).unwrap();
        assert_eq!(
            &query[..size],
            cbus_protocol::cni_discovery::DISCOVERY_QUERY
        );
        let visible =
            hex::decode("cb81000020e8f5528101000101810b00022711811d000101800100028c26").unwrap();
        let hidden =
            hex::decode("cb810000000000028101000102810b00022711811d000100800100020000").unwrap();
        let malformed = vec![b'X'; 1_024];
        for payload in [&visible[..], &visible[..], &hidden[..], &malformed[..]] {
            socket.send_to(payload, source).unwrap();
        }
    });
    let port = port.to_string();
    let (status, out, err) = run(
        BIN,
        &[
            "cni-discover",
            "--bind",
            "127.0.0.1",
            "--listen-port",
            "0",
            "--destination",
            "127.0.0.1",
            "--discovery-port",
            &port,
            "--timeout",
            "0.1",
            "--max-datagrams",
            "16",
        ],
    );
    peer.join().unwrap();
    assert!(status.success(), "{err}");
    let report: Value = serde_json::from_str(&out).unwrap();
    assert_eq!(report["format"], "cbus-cni-discovery-v1");
    assert_eq!(report["devices"].as_array().unwrap().len(), 1);
    assert_eq!(report["devices"][0]["endpoint"], "127.0.0.1:10001");
    assert_eq!(report["devices"][0]["product"], "cni2");
    assert_eq!(report["devices"][0]["unknown1_hex"], "20e8f552");
    assert!(report["devices"][0].get("device_id_hex").is_none());
    assert_eq!(report["duplicates_ignored"], 1);
    assert_eq!(report["hidden_ignored"], 1);
    assert_eq!(report["malformed"].as_array().unwrap().len(), 1);
    assert_eq!(report["malformed"][0]["raw_length"], 1_024);
    assert_eq!(report["malformed"][0]["raw_truncated"], true);
    assert_eq!(
        report["malformed"][0]["raw_hex"].as_str().unwrap().len(),
        128
    );
    assert_eq!(report["query_sent_once"], true);
    assert_eq!(report["tcp_connection_opened"], false);
    assert_eq!(report["absence_proven"], false);
}

#[test]
fn cni_discover_rejects_unbounded_inputs_before_socket_io() {
    for args in [
        vec!["cni-discover", "--timeout", "0"],
        vec!["cni-discover", "--timeout", "301"],
        vec!["cni-discover", "--max-datagrams", "0"],
        vec!["cni-discover", "--max-datagrams", "4097"],
        vec!["cni-discover", "--discovery-port", "0"],
    ] {
        let (status, _out, err) = run(BIN, &args);
        assert_eq!(status.code(), Some(1), "{args:?}: {err}");
        assert!(err.contains("CNI discovery"), "{args:?}: {err}");
    }
}

#[test]
fn cni_scan_reports_each_route_without_inventing_absence() {
    let socket = std::net::UdpSocket::bind("127.0.0.1:0").unwrap();
    socket
        .set_read_timeout(Some(std::time::Duration::from_secs(2)))
        .unwrap();
    let port = socket.local_addr().unwrap().port().to_string();
    let peer = std::thread::spawn(move || {
        let mut query = [0u8; 64];
        let (size, source) = socket.recv_from(&mut query).unwrap();
        assert_eq!(
            &query[..size],
            cbus_protocol::cni_discovery::DISCOVERY_QUERY
        );
        let visible =
            hex::decode("cb81000020e8f5528101000101810b00022711811d000101800100028c26").unwrap();
        socket.send_to(&visible, source).unwrap();
    });
    let (status, out, err) = run(
        BIN,
        &[
            "cni-scan",
            "--probe",
            "127.0.0.1@127.0.0.2",
            "--probe",
            "127.0.0.1@127.0.0.1",
            "--listen-port",
            "0",
            "--discovery-port",
            &port,
            "--timeout",
            "0.1",
        ],
    );
    peer.join().unwrap();
    assert!(status.success(), "{err}");
    let report: Value = serde_json::from_str(&out).unwrap();
    assert_eq!(report["format"], "cbus-cni-multi-discovery-v1");
    assert_eq!(report["probe_count"], 2);
    assert_eq!(report["probes"][0]["outcome"], "no_reply_by_deadline");
    assert_eq!(report["probes"][1]["outcome"], "devices_observed");
    assert_eq!(
        report["probes"][1]["observation"]["devices"][0]["endpoint"],
        "127.0.0.1:10001"
    );
    assert_eq!(report["absence_proven"], false);
    assert_eq!(report["tcp_connection_opened"], false);
}

#[test]
fn cni_scan_rejects_bad_routes_before_socket_io() {
    for args in [
        vec![
            "cni-scan",
            "--probe",
            "127.0.0.1@127.0.0.1",
            "--probe",
            "127.0.0.1@127.0.0.1",
        ],
        vec!["cni-scan", "--probe", "not-an-ip@127.0.0.1"],
        vec![
            "cni-scan",
            "--probe",
            "127.0.0.1@127.0.0.1",
            "--timeout",
            "301",
        ],
        vec![
            "cni-scan",
            "--probe",
            "127.0.0.1@127.0.0.1",
            "--max-datagrams",
            "4097",
        ],
        vec!["cni-scan", "--probe", "127.0.0.1@127.0.0.1", "--plan-only"],
    ] {
        let (status, _out, err) = run(BIN, &args);
        assert_eq!(status.code(), Some(1), "{args:?}: {err}");
        assert!(
            err.contains("CNI discovery") || err.contains("require --auto-adapters"),
            "{args:?}: {err}"
        );
    }
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
                if frame == b"@1A2001\r" {
                    let _ = stream.write_all(&interrogation_reply(None, 0x20, &[0]));
                }
                // \46 <unit> 00 <cal...><conf>: reply only for unit 0
                if text.starts_with("\\460000") {
                    let parameter = u8::from_str_radix(&text[9..11], 16).unwrap();
                    let mut cal = vec![0x80 | (1 + name.len() as u8), parameter];
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
fn interrogate_unavailable_endpoint_exits_nonzero() {
    // TCP port zero cannot have a listening peer.  Keeping the kernel-selected
    // port from a dropped `127.0.0.1:0` listener is racy: another parallel test
    // can claim that port before this subprocess connects.
    let addr = "127.0.0.1:0";
    let (status, _out, err) = run(
        BIN,
        &[
            "interrogate",
            "--tcp",
            addr,
            "--unit",
            "0",
            "--timeout",
            "0.5",
        ],
    );
    assert_eq!(status.code(), Some(1));
    assert!(!err.is_empty());
}

#[test]
fn dump_labels_group_addresses_handle_utf8_and_whitespace_without_panicking() {
    let path = temp_path("unicode-group-addresses.xml");
    std::fs::write(
        &path,
        "<Installation><Project><Network><Address>254</Address><Unit><Address>1</Address><PP><Name>GroupAddress</Name><Value>0x38\t0XFF 0x01 ☃ xx10 0x100</Value></PP></Unit></Network></Project></Installation>",
    ).unwrap();
    let (status, out, err) = run(BIN, &["dump-labels", path.to_str().unwrap()]);
    std::fs::remove_file(&path).unwrap();
    assert!(status.success(), "{err}");
    let value: Value = serde_json::from_str(&out).unwrap();
    assert_eq!(
        value["254"]["units"]["1"]["groups"],
        serde_json::json!([56, 255, 1])
    );
}

#[test]
fn interrogate_rejects_invalid_timeout_without_panicking() {
    for timeout in ["NaN", "inf", "-1", "0", "1e100"] {
        let argument = format!("--timeout={timeout}");
        let (status, _, err) = run(
            BIN,
            &[
                "interrogate",
                "--tcp",
                "127.0.0.1:0",
                "--unit",
                "0",
                &argument,
            ],
        );
        assert_eq!(status.code(), Some(1), "{timeout}: {err}");
        assert!(err.contains("timeout"), "{timeout}: {err}");
        assert!(!err.contains("panicked"), "{timeout}: {err}");
    }
}

#[test]
fn interrogate_rejects_invalid_port_before_connecting() {
    for endpoint in [
        "127.0.0.1:garbage",
        "127.0.0.1:65536",
        "127.0.0.1:",
        ":10001",
    ] {
        let (status, _, err) = run(BIN, &["interrogate", "--tcp", endpoint, "--unit", "0"]);
        assert_eq!(status.code(), Some(1), "{endpoint}: {err}");
        assert!(err.contains("TCP"), "{endpoint}: {err}");
    }
}

#[test]
fn interrogate_missing_operation_is_rejected_before_connecting() {
    let (status, _, err) = run(BIN, &["interrogate", "--tcp", "127.0.0.1:0"]);
    assert_eq!(status.code(), Some(1));
    assert!(err.contains("pass --unit N or --discover"), "{err}");
}

fn interrogation_reply(source: Option<u8>, parameter: u8, data: &[u8]) -> Vec<u8> {
    let mut raw = match source {
        Some(source) => vec![0x86, source, 16, 0],
        None => vec![],
    };
    raw.extend(
        cbus_protocol::cal::Cal::Reply {
            parameter,
            data: data.to_vec(),
        }
        .encode(),
    );
    let mut wire = hex::encode_upper(cbus_protocol::common::add_cbus_checksum(&raw)).into_bytes();
    wire.extend_from_slice(b"\r\n");
    wire
}

fn scripted_interrogation_replies(replies: Vec<u8>) -> (std::thread::JoinHandle<()>, u16) {
    scripted_interrogation_replies_with_local(replies, Some(16))
}

fn scripted_interrogation_replies_with_local(
    replies: Vec<u8>,
    local_unit: Option<u8>,
) -> (std::thread::JoinHandle<()>, u16) {
    let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    let port = listener.local_addr().unwrap().port();
    let thread = std::thread::spawn(move || {
        let (mut stream, _) = listener.accept().unwrap();
        stream
            .set_read_timeout(Some(std::time::Duration::from_secs(3)))
            .unwrap();
        let mut pending = Vec::new();
        let mut chunk = [0u8; 1024];
        loop {
            let count = match stream.read(&mut chunk) {
                Ok(0) | Err(_) => return,
                Ok(count) => count,
            };
            pending.extend_from_slice(&chunk[..count]);
            while let Some(end) = pending.iter().position(|byte| *byte == b'\r') {
                let frame = pending.drain(..=end).collect::<Vec<_>>();
                if frame == b"@1A2001\r" {
                    if let Some(local) = local_unit {
                        stream
                            .write_all(&interrogation_reply(None, 0x20, &[local]))
                            .unwrap();
                    }
                } else if frame.starts_with(b"\\46") {
                    stream.write_all(&replies).unwrap();
                }
            }
        }
    });
    (thread, port)
}

#[test]
fn interrogate_discovery_ignores_unrelated_or_corrupt_replies() {
    let mut corrupt = interrogation_reply(Some(0), 1, b"CORRUPT!");
    let checksum = corrupt.len() - 4;
    corrupt[checksum] = if corrupt[checksum] == b'0' {
        b'1'
    } else {
        b'0'
    };
    for (case, replies) in [
        (
            "foreign source",
            interrogation_reply(Some(99), 1, b"FOREIGN!"),
        ),
        (
            "foreign parameter",
            interrogation_reply(Some(0), 2, b"WRONGPAR"),
        ),
        (
            "unbound bare reply",
            interrogation_reply(None, 1, b"UNBOUND!"),
        ),
        ("corrupt checksum", corrupt),
    ] {
        let (thread, port) = scripted_interrogation_replies(replies);
        let (status, out, err) = run(
            BIN,
            &[
                "interrogate",
                "--tcp",
                &format!("127.0.0.1:{port}"),
                "--discover",
                "--max-address",
                "0",
                "--timeout",
                "0.1",
            ],
        );
        thread.join().unwrap();
        assert!(status.success(), "{case}: {err}");
        assert!(!out.contains("Unit 0"), "{case}: {out}");
    }
}

#[test]
fn interrogate_discovery_handles_confirmation_before_exact_reply() {
    let mut replies = b"h.".to_vec();
    replies.extend(interrogation_reply(Some(0), 1, b"EXACTONE"));
    let (thread, port) = scripted_interrogation_replies(replies);
    let (status, out, err) = run(
        BIN,
        &[
            "interrogate",
            "--tcp",
            &format!("127.0.0.1:{port}"),
            "--discover",
            "--max-address",
            "0",
            "--timeout",
            "0.1",
        ],
    );
    thread.join().unwrap();
    assert!(status.success(), "{err}");
    assert!(out.contains("Unit 0 (0x00): EXACTONE"), "{out}");
}

#[test]
fn interrogate_without_local_address_requires_addressed_replies() {
    for source in [None, Some(0)] {
        let replies = interrogation_reply(source, 1, b"EXACTONE");
        let (thread, port) = scripted_interrogation_replies_with_local(replies, None);
        let (status, out, err) = run(
            BIN,
            &[
                "interrogate",
                "--tcp",
                &format!("127.0.0.1:{port}"),
                "--discover",
                "--max-address",
                "0",
                "--timeout",
                "0.1",
            ],
        );
        thread.join().unwrap();
        assert!(status.success(), "{err}");
        assert!(err.contains("local PCI address unavailable"), "{err}");
        assert_eq!(
            out.contains("Unit 0 (0x00): EXACTONE"),
            source.is_some(),
            "{out}"
        );
    }
}

#[test]
fn interrogate_skips_noise_and_returns_only_exact_reply() {
    let mut replies = interrogation_reply(Some(99), 1, b"FOREIGN!");
    replies.extend(interrogation_reply(Some(0), 2, b"WRONGPAR"));
    replies.extend_from_slice(b"h.");
    replies.extend(interrogation_reply(Some(0), 1, b"EXACTONE"));
    let (thread, port) = scripted_interrogation_replies(replies);
    let (status, out, err) = run(
        BIN,
        &[
            "interrogate",
            "--tcp",
            &format!("127.0.0.1:{port}"),
            "--discover",
            "--max-address",
            "0",
            "--timeout",
            "0.1",
        ],
    );
    thread.join().unwrap();
    assert!(status.success(), "{err}");
    assert_eq!(out.trim(), "Unit 0 (0x00): EXACTONE");
}
