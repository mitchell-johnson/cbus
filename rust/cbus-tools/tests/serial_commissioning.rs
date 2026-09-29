//! RED-first CLI tests for `serial-verify` / `serial-apply`.
//!
//! Invocation pattern follows `tests/cli.rs`: the real `cbus-tools` binary
//! runs as a subprocess (`CARGO_BIN_EXE_cbus-tools`, built automatically by
//! `cargo test`), speaking to a scripted loopback PCI peer over TCP.
//!
//! The peer mirrors the transport lane's scripted duplex fixtures
//! (`cbus-transport/tests/selected_serial_verify.rs`): the committed vector
//! plan moves `101136.1558` to destination 6 with local unit 16. Post-move
//! state is `6 -> [101136.1558] (2), 16 -> [100966.1187] (1),
//! 255 -> [101136.1559] (2)`; pre-move state is `16 -> [100966.1187] (1),
//! 255 -> [101136.1558, 101136.1559] (2)`.
//!
//! Real-time note: each IDENTIFY4 probe costs the client's fixed 2 s quiet
//! window, so scripted tests take ~10 s (verify) / ~15 s (apply). `--timeout
//! 30` bounds the observation so a regression fails instead of hanging.

use cbus_test_support::proc::{run, temp_path};
use cbus_tools::commissioning_lease::EndpointLease;
use serde_json::Value;
use std::io::{BufRead, BufReader, Write};
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};

const BIN: &str = env!("CARGO_BIN_EXE_cbus-tools");

fn remove_reported_attempt_marker(output: &str) {
    let value: Value = serde_json::from_str(output.trim()).unwrap();
    let path = value["attempt_identity"]
        .as_str()
        .expect("apply evidence must report its attempt marker");
    std::fs::remove_file(path).expect("remove test attempt marker");
}

// ------------------------------------------------------------ plan fixture

fn vector_plan_document() -> Value {
    let text = std::fs::read_to_string(
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../testdata/vectors/selected_serial_plan.jsonl"),
    )
    .unwrap();
    let line = text.lines().next().expect("vector file must have rows");
    let outer: Value = serde_json::from_str(line).expect("vector line must be JSON");
    outer["document"].clone()
}

/// Write the committed vector plan with its endpoint (top-level and `before`
/// copies together, preserving internal consistency) rewritten to `port`.
fn plan_file_for_port(port: u16, tag: &str) -> PathBuf {
    plan_file_for_port_with_checksum(port, tag, false)
}

fn plan_file_for_port_with_checksum(port: u16, tag: &str, command_checksum: bool) -> PathBuf {
    let mut doc = vector_plan_document();
    assert_eq!(doc["serial"], Value::from("101136.1558"));
    assert_eq!(doc["destination"], Value::from(6));
    doc["endpoint"]["host"] = Value::from("127.0.0.1");
    doc["endpoint"]["port"] = Value::from(port);
    doc["before"]["endpoint"]["host"] = Value::from("127.0.0.1");
    doc["before"]["endpoint"]["port"] = Value::from(port);
    if command_checksum {
        fn add_checksum(encoded: &str) -> String {
            let wire = hex::decode(encoded).unwrap();
            let confirmed = matches!(wire.get(wire.len() - 2), Some(b'g'..=b'z'));
            let body_end = wire.len() - 1 - usize::from(confirmed);
            let command = hex::decode(&wire[1..body_end]).unwrap();
            let checksum = 0u8.wrapping_sub(
                command
                    .iter()
                    .fold(0u8, |sum, byte| sum.wrapping_add(*byte)),
            );
            let mut checksummed = vec![b'\\'];
            checksummed.extend_from_slice(hex::encode_upper(command).as_bytes());
            checksummed.extend_from_slice(format!("{checksum:02X}").as_bytes());
            if confirmed {
                checksummed.push(wire[wire.len() - 2]);
            }
            checksummed.push(b'\r');
            hex::encode(checksummed)
        }
        fn rewrite(value: &mut Value) {
            match value {
                Value::Array(items) => items.iter_mut().for_each(rewrite),
                Value::Object(object) => {
                    object.values_mut().for_each(rewrite);
                    if let Some(Value::String(request)) = object.get_mut("request_hex") {
                        *request = add_checksum(request);
                    }
                }
                _ => {}
            }
        }
        rewrite(&mut doc);
        doc["settings"]["command_checksum"] = Value::Bool(true);
    }
    let path = temp_path(tag);
    std::fs::write(&path, serde_json::to_vec(&doc).unwrap()).unwrap();
    path
}

// ------------------------------------------------------- scripted PCI peer

fn serial_a() -> Vec<u8> {
    // 101136.1558: the selected serial moved to the destination.
    vec![
        0x38, 0xff, 0xff, 0xff, 0xff, 0x18, 0xb1, 0x06, 0x16, 0xa2, 0x00, 0x05,
    ]
}

fn serial_b() -> Vec<u8> {
    // 101136.1559: the serial that stays at 255.
    vec![
        0x38, 0xff, 0xff, 0xff, 0xff, 0x18, 0xb1, 0x06, 0x17, 0xa2, 0x00, 0x05,
    ]
}

fn serial_c() -> Vec<u8> {
    // 100966.1187: the pinned local PCI serial at 16.
    vec![
        0xff, 0xff, 0xff, 0x00, 0x00, 0x18, 0xa6, 0x64, 0xa3, 0xb1, 0x00, 0x05,
    ]
}

fn post_move_states() -> [u8; 256] {
    let mut states = [0u8; 256];
    states[6] = 2;
    states[16] = 1;
    states[255] = 2;
    states
}

fn pre_move_states() -> [u8; 256] {
    let mut states = [0u8; 256];
    states[16] = 1;
    states[255] = 2;
    states
}

fn mmi_line(start: u8, count: usize, states: &[u8; 256]) -> Vec<u8> {
    use cbus_protocol::packet::Packet;
    let block = states[usize::from(start)..usize::from(start) + count].to_vec();
    let mut line = Packet::StandardStatus {
        application: 0xff,
        block_start: start,
        states: block,
    }
    .encode_packet()
    .unwrap();
    line.extend_from_slice(b"\r\n");
    line
}

fn checksum_line(bytes: Vec<u8>) -> Vec<u8> {
    encode_line(bytes, true)
}

/// Hex-encode a reply in the session mode: checksummed frames append the
/// checksum byte, bare frames omit it (as a checksum-off session receives
/// them). MMI status blocks are exempt: they always carry checksums.
fn encode_line(mut bytes: Vec<u8>, checksummed: bool) -> Vec<u8> {
    if checksummed {
        let sum = bytes.iter().fold(0u8, |acc, b| acc.wrapping_add(*b));
        bytes.push(0u8.wrapping_sub(sum));
    }
    let mut line = bytes
        .iter()
        .map(|b| format!("{b:02X}"))
        .collect::<String>()
        .into_bytes();
    line.extend_from_slice(b"\r\n");
    line
}

fn identify_line(unit: u8, payload: &[u8], checksummed: bool) -> Vec<u8> {
    if unit == 16 {
        // The attached PCI's own IDENTIFY response is a bare CAL. This pins
        // the CLI requirement to establish the validated local-unit hint
        // before verify/apply inventory collection.
        let cal = cbus_protocol::cal::Cal::Reply {
            parameter: 4,
            data: payload.to_vec(),
        }
        .encode();
        encode_line(cal, checksummed)
    } else {
        identify_reply_line(unit, 4, payload, checksummed)
    }
}

/// Routed IDENTIFY reply with the requested CAL parameter and payload.
fn identify_reply_line(unit: u8, parameter: u8, data: &[u8], checksummed: bool) -> Vec<u8> {
    use cbus_protocol::cal::Cal;
    let cal = Cal::Reply {
        parameter,
        data: data.to_vec(),
    }
    .encode();
    let mut bytes = vec![0x86, unit, 0x10, 0x01, 0x00];
    bytes.extend(cal);
    encode_line(bytes, checksummed)
}

/// Local-options recall reply for unit 16 carrying one option byte
/// (mirrors the `NET UNRAVELUNIT` wire shape in the transport apply test).
fn recall_line(option: u8, checksummed: bool) -> Vec<u8> {
    encode_line(vec![0x86, 16, 0x10, 0x00, 0x82, 0x42, option], checksummed)
}

fn selected_serial_receipt_line() -> Vec<u8> {
    checksum_line(vec![
        0x86, 6, 16, 0x00, 0x87, 0x00, 0x18, 0xb1, 0x06, 0x16, 0xfa, 0xce,
    ])
}

struct PeerScript {
    /// PRE-move script: served until the one-shot send is accepted.
    /// Verify tests set no post script and serve this for the whole session.
    states: [u8; 256],
    /// IDENTIFY4 payloads keyed by unit; duplicates re-served tolerantly.
    probes: Vec<(u8, Vec<Vec<u8>>)>,
    /// Answer `recall_parameter(16, 66, 1)` with this option byte.
    option: Option<u8>,
    /// Accept one exact selected-serial request on the existing session, with
    /// the expected outer-checksum setting. `None` rejects any address send.
    address_checksum: Option<bool>,
    /// Emit the exact selected-serial receipt after accepting the address
    /// request. A positive confirmation is still emitted when this is false.
    address_receipt: bool,
    /// POST-move script: served after the shared-session send is accepted.
    /// `None` keeps the static single-phase behavior (verify tests).
    post_states: Option<[u8; 256]>,
    /// POST-move IDENTIFY4 payloads keyed by unit (`None` = static).
    post_probes: Option<Vec<(u8, Vec<Vec<u8>>)>>,
}

impl PeerScript {
    fn reply_for(&self, unit: u8) -> Vec<Vec<u8>> {
        self.probes
            .iter()
            .find(|(u, _)| *u == unit)
            .map(|(_, p)| p.clone())
            .unwrap_or_default()
    }

    /// Phase-selected MMI states: PRE until the send is accepted, POST after.
    /// Ordering is safe: the acceptor sets the flag on the send request
    /// line, which precedes send-completion, which precedes the
    /// after-inventory. `None` post script serves the single phase always.
    fn states_for(&self, sent: &AtomicBool) -> &[u8; 256] {
        if sent.load(Ordering::SeqCst) {
            self.post_states.as_ref().unwrap_or(&self.states)
        } else {
            &self.states
        }
    }

    /// Phase-selected IDENTIFY4 payloads. While a post script exists it is
    /// authoritative after the send (a unit absent post-send proves no
    /// reply rather than serving a stale pre-move payload).
    fn probes_for(&self, unit: u8, sent: &AtomicBool) -> Vec<Vec<u8>> {
        if sent.load(Ordering::SeqCst) {
            if let Some(post) = &self.post_probes {
                return post
                    .iter()
                    .find(|(u, _)| *u == unit)
                    .map(|(_, p)| p.clone())
                    .unwrap_or_default();
            }
        }
        self.reply_for(unit)
    }
}

/// Every client request line the peer received, in order.
type RequestLog = std::sync::Arc<std::sync::Mutex<Vec<Vec<u8>>>>;

fn handle_session(
    stream: std::net::TcpStream,
    script: &PeerScript,
    first: Vec<u8>,
    sent: &AtomicBool,
    log: &RequestLog,
) -> std::io::Result<()> {
    let mut reader = BufReader::new(stream.try_clone()?);
    let mut writer = stream;
    let mut pending = Some(first);
    loop {
        let line = match pending.take() {
            Some(line) => line,
            None => {
                let mut line = Vec::new();
                if reader.read_until(b'\r', &mut line)? == 0 {
                    return Ok(()); // EOF: CLI went away
                }
                line
            }
        };
        if line.is_empty() || line[0] != b'\\' {
            continue; // init / basic-mode frames need no acknowledgement
        }
        log.lock().unwrap().push(line.clone());
        // A trailing g..z byte is the confirmation code (confirmed read);
        // checksummed-but-unconfirmed frames (e.g. the local-options
        // recall) carry none. Hex digits never collide with g..z, so the
        // last byte alone decides.
        let body = &line[1..line.len() - 1]; // strip backslash + CR
        let confirmed = matches!(body.last(), Some(b'g'..=b'z'));
        let hexpart = if confirmed {
            &body[..body.len() - 1]
        } else {
            body
        };
        if confirmed {
            // Ack immediately so the client never retransmits.
            writer.write_all(&[*body.last().unwrap(), b'.'])?;
        }
        // Requests arrive checksummed or bare according to the plan's
        // session mode; CAL replies echo the request form, while MMI status
        // blocks always carry checksums.
        if hexpart == b"05FF00FAFF0003" || hexpart == b"05FF00FAFF00" {
            for (start, count) in [(0u8, 88usize), (88, 88), (176, 80)] {
                writer.write_all(&mmi_line(start, count, script.states_for(sent)))?;
            }
            writer.flush()?;
        } else if hexpart.len() > 4 {
            let bytes = hex::decode(hexpart).unwrap_or_else(|e| {
                panic!(
                    "client frame must be hex ({e}): {:?}",
                    String::from_utf8_lossy(&line)
                )
            });
            if bytes.len() >= 6 && bytes[0] == 0x46 && bytes[3] == 0x1A {
                let option = script.option.expect("unexpected local-options recall");
                writer.write_all(&recall_line(option, bytes.len() == 7))?;
                writer.flush()?;
            } else if bytes.len() >= 11 && bytes[..5] == [0x05, 0xff, 0x00, 0x0f, 0x00] {
                let command_checksum = script
                    .address_checksum
                    .expect("unexpected selected-serial address request");
                let expected = cbus_protocol::serial_address::encode_serial_address(
                    "101136.1558",
                    6,
                    command_checksum,
                    b'g',
                )
                .unwrap();
                assert_eq!(line, expected, "CLI must send the strict plan bytes");
                assert!(
                    !sent.swap(true, Ordering::SeqCst),
                    "selected-serial request must not be replayed"
                );
                if script.address_receipt {
                    writer.write_all(&selected_serial_receipt_line())?;
                    writer.flush()?;
                }
            } else if bytes.len() >= 5 && bytes[0] == 0x46 && bytes[3] == 0x21 {
                let unit = bytes[1];
                let attribute = bytes[4];
                // A checksummed IDENTIFY carries a sixth checksum byte.
                let checksummed = bytes.len() == 6;
                match attribute {
                    4 => {
                        for payload in script.probes_for(unit, sent) {
                            writer.write_all(&identify_line(unit, &payload, checksummed))?;
                        }
                        writer.flush()?;
                        // then silence: the client completes the probe on its
                        // fixed 2 s quiet window
                    }
                    // Retained for other commissioning callers; selected-
                    // serial verify/apply uses IDENTIFY4 only.
                    1 | 2 => {
                        let text = if attribute == 1 {
                            format!("TYPE{unit}")
                        } else {
                            format!("FW{unit}")
                        };
                        writer.write_all(&identify_reply_line(
                            unit,
                            attribute,
                            text.as_bytes(),
                            checksummed,
                        ))?;
                        writer.flush()?;
                    }
                    _ => {
                        panic!(
                            "unexpected IDENTIFY attribute {attribute}: {}",
                            String::from_utf8_lossy(&line)
                        );
                    }
                }
            } else {
                panic!(
                    "unexpected confirmed frame: {}",
                    String::from_utf8_lossy(&line)
                );
            }
        }
    }
}

/// Spawn a one-client loopback peer and return its port. The listener closes
/// after accepting the PCI session, so any concurrent second socket is
/// refused. The one handler exits on CLI EOF; a hung CLI is bounded by its
/// own `--timeout`.
fn spawn_peer_with_send_observer(script: PeerScript) -> (u16, std::sync::Arc<AtomicBool>) {
    let (port, sent, _) = spawn_peer_logged(script);
    (port, sent)
}

/// [`spawn_peer_with_send_observer`] that also exposes the request log.
fn spawn_peer_logged(script: PeerScript) -> (u16, std::sync::Arc<AtomicBool>, RequestLog) {
    let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    let port = listener.local_addr().unwrap().port();
    let script = std::sync::Arc::new(script);
    // Phase flag: false serves PRE-move, true serves POST-move. The existing
    // session flips it only after observing the exact address request.
    let sent = std::sync::Arc::new(AtomicBool::new(false));
    let send_observer = sent.clone();
    let log = RequestLog::default();
    let request_log = log.clone();
    std::thread::spawn(move || {
        let Ok((stream, _)) = listener.accept() else {
            return;
        };
        drop(listener);
        let mut reader = BufReader::new(stream.try_clone().unwrap());
        let mut first = Vec::new();
        if reader.read_until(b'\r', &mut first).is_err() || first.is_empty() {
            return;
        }
        if let Err(e) = handle_session(stream, &script, first, &sent, &log) {
            panic!("peer session failed: {e}");
        }
    });
    (port, send_observer, request_log)
}

fn spawn_peer(script: PeerScript) -> u16 {
    spawn_peer_with_send_observer(script).0
}

fn closed_port() -> u16 {
    let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    let port = listener.local_addr().unwrap().port();
    drop(listener);
    port
}

#[test]
fn serial_commands_refuse_a_cooperating_endpoint_lease_before_connect_or_journal() {
    let port = closed_port();
    let plan = plan_file_for_port(port, "lease-conflict-plan.json");
    let journal = temp_path("lease-conflict-journal.json");
    let addr = format!("127.0.0.1:{port}");
    let held = EndpointLease::acquire("127.0.0.1", port).unwrap();

    let (verify_status, verify_out, verify_err) = run(
        BIN,
        &[
            "serial-verify",
            "--pci",
            &addr,
            "--plan",
            plan.to_str().unwrap(),
            "--timeout",
            "1",
        ],
    );
    assert_eq!(verify_status.code(), Some(1), "{verify_err}");
    assert!(verify_out.is_empty());
    assert!(
        verify_err.contains("commissioning lease: another process is commissioning this endpoint"),
        "{verify_err}"
    );

    let (apply_status, apply_out, apply_err) = run(
        BIN,
        &[
            "serial-apply",
            "--pci",
            &addr,
            "--plan",
            plan.to_str().unwrap(),
            "--journal",
            journal.to_str().unwrap(),
            "--timeout",
            "1",
        ],
    );
    assert_eq!(apply_status.code(), Some(1), "{apply_err}");
    assert!(apply_out.is_empty());
    assert!(
        apply_err.contains("commissioning lease: another process is commissioning this endpoint"),
        "{apply_err}"
    );
    assert!(
        !journal.exists(),
        "a denied apply must not create a journal"
    );

    drop(held);
    let (_status, _out, after_release) = run(
        BIN,
        &[
            "serial-verify",
            "--pci",
            &addr,
            "--plan",
            plan.to_str().unwrap(),
            "--timeout",
            "1",
        ],
    );
    assert!(after_release.contains("connect:"), "{after_release}");
    std::fs::remove_file(&plan).ok();
}

// ------------------------------------------------------------------ verify

#[test]
fn serial_verify_observes_expected_change() {
    let port = spawn_peer(PeerScript {
        states: post_move_states(),
        probes: vec![
            (6, vec![serial_a()]),
            (16, vec![serial_c()]),
            (255, vec![serial_b()]),
        ],
        option: None,
        address_checksum: None,
        address_receipt: false,
        post_states: None,
        post_probes: None,
    });
    let plan = plan_file_for_port(port, "verify-post.json");
    let addr = format!("127.0.0.1:{port}");
    let (status, out, err) = run(
        BIN,
        &[
            "serial-verify",
            "--pci",
            &addr,
            "--plan",
            plan.to_str().unwrap(),
            "--timeout",
            "30",
        ],
    );
    std::fs::remove_file(&plan).ok();
    assert!(status.success(), "exit 0 on expected change: {err}");
    let v: Value = serde_json::from_str(out.trim()).expect("JSON evidence on stdout");
    assert_eq!(v["outcome"], "observed_expected_change", "{v}");
    assert_eq!(v["expected_identity_change"], true, "{v}");
}

#[test]
fn serial_verify_observes_unchanged() {
    let port = spawn_peer(PeerScript {
        states: pre_move_states(),
        probes: vec![(16, vec![serial_c()]), (255, vec![serial_a(), serial_b()])],
        option: None,
        address_checksum: None,
        address_receipt: false,
        post_states: None,
        post_probes: None,
    });
    let plan = plan_file_for_port(port, "verify-pre.json");
    let addr = format!("127.0.0.1:{port}");
    let (status, out, err) = run(
        BIN,
        &[
            "serial-verify",
            "--pci",
            &addr,
            "--plan",
            plan.to_str().unwrap(),
            "--timeout",
            "30",
        ],
    );
    std::fs::remove_file(&plan).ok();
    assert_eq!(status.code(), Some(1), "exit 1 on unchanged: {out} {err}");
    let v: Value = serde_json::from_str(out.trim()).expect("JSON evidence on stdout");
    assert_eq!(v["outcome"], "observed_unchanged", "{v}");
    assert_eq!(v["expected_identity_change"], false, "{v}");
}

#[test]
fn serial_verify_rejects_pci_mismatch_before_connect() {
    // Both ports are closed: a connection attempt would fail with a connect
    // error, so the endpoint-mismatch message proves refusal before any I/O.
    let plan_port = closed_port();
    let cli_port = closed_port();
    assert_ne!(plan_port, cli_port);
    let plan = plan_file_for_port(plan_port, "verify-mismatch.json");
    let addr = format!("127.0.0.1:{cli_port}");
    let (status, out, err) = run(
        BIN,
        &[
            "serial-verify",
            "--pci",
            &addr,
            "--plan",
            plan.to_str().unwrap(),
        ],
    );
    std::fs::remove_file(&plan).ok();
    assert_eq!(status.code(), Some(1), "mismatch must fail: {err}");
    assert!(err.contains("endpoint mismatch"), "{err}");
    assert!(err.contains("plan is authoritative"), "{err}");
    assert!(
        out.trim().is_empty(),
        "hard errors must keep stdout empty: {out:?}"
    );
}

#[test]
fn serial_verify_rejects_corrupt_plan_before_connect() {
    let dead = closed_port();
    let plan = temp_path("corrupt-plan.json");
    std::fs::write(&plan, b"{not valid json").unwrap();
    let addr = format!("127.0.0.1:{dead}");
    let (status, out, err) = run(
        BIN,
        &[
            "serial-verify",
            "--pci",
            &addr,
            "--plan",
            plan.to_str().unwrap(),
        ],
    );
    std::fs::remove_file(&plan).ok();
    assert_eq!(status.code(), Some(1), "corrupt plan must fail: {err}");
    assert!(
        out.trim().is_empty(),
        "hard errors must keep stdout empty: {out:?}"
    );
    assert!(err.contains("plan"), "{err}");
    assert!(
        !err.contains("connect"),
        "must fail before connecting: {err}"
    );
}

// ------------------------------------------------------------------- apply

#[test]
fn serial_apply_moves_and_journals() {
    // Phased peer mirroring the oracle's two-phase reality: PRE-move
    // MMI/IDENTIFY4 until the one-shot send is accepted (fresh-inventory
    // preconditions must match plan.before), then POST-move after, so the
    // post-send observation classifies the expected change.
    let port = spawn_peer(PeerScript {
        states: pre_move_states(),
        probes: vec![(16, vec![serial_c()]), (255, vec![serial_a(), serial_b()])],
        option: Some(5),
        address_checksum: Some(false),
        address_receipt: true,
        post_states: Some(post_move_states()),
        post_probes: Some(vec![
            (6, vec![serial_a()]),
            (16, vec![serial_c()]),
            (255, vec![serial_b()]),
        ]),
    });
    let plan = plan_file_for_port(port, "apply-happy.json");
    let journal = temp_path("apply-happy-journal.json");
    let addr = format!("127.0.0.1:{port}");
    let (status, out, err) = run(
        BIN,
        &[
            "serial-apply",
            "--pci",
            &addr,
            "--plan",
            plan.to_str().unwrap(),
            "--journal",
            journal.to_str().unwrap(),
            "--timeout",
            "30",
        ],
    );
    std::fs::remove_file(&plan).ok();
    assert!(status.success(), "exit 0 on expected change: {err}");
    let v: Value = serde_json::from_str(out.trim()).expect("JSON evidence on stdout");
    assert_eq!(v["outcome"], "observed_expected_change", "{v}");
    assert_eq!(v["journal"], journal.to_str().unwrap(), "{v}");
    let journal_text = std::fs::read_to_string(&journal).expect("journal must exist");
    std::fs::remove_file(&journal).ok();
    remove_reported_attempt_marker(&out);
    assert!(
        journal_text.contains("cbus-selected-serial-apply-v1"),
        "{journal_text}"
    );
    assert!(
        journal_text.contains("observed_expected_change"),
        "{journal_text}"
    );
}

#[test]
fn serial_apply_expected_after_succeeds_without_a_matching_receipt() {
    let (port, sent) = spawn_peer_with_send_observer(PeerScript {
        states: pre_move_states(),
        probes: vec![(16, vec![serial_c()]), (255, vec![serial_a(), serial_b()])],
        option: Some(5),
        address_checksum: Some(false),
        address_receipt: false,
        post_states: Some(post_move_states()),
        post_probes: Some(vec![
            (6, vec![serial_a()]),
            (16, vec![serial_c()]),
            (255, vec![serial_b()]),
        ]),
    });
    let plan = plan_file_for_port(port, "apply-no-receipt.json");
    let journal = temp_path("apply-no-receipt-journal.json");
    let addr = format!("127.0.0.1:{port}");
    let (status, out, err) = run(
        BIN,
        &[
            "serial-apply",
            "--pci",
            &addr,
            "--plan",
            plan.to_str().unwrap(),
            "--journal",
            journal.to_str().unwrap(),
            "--timeout",
            "30",
        ],
    );
    std::fs::remove_file(&plan).ok();
    assert!(
        status.success(),
        "expected after-state must exit 0: {out} {err}"
    );
    assert!(
        sent.load(Ordering::SeqCst),
        "the scripted peer must observe exactly one selected-serial send"
    );
    let evidence: Value = serde_json::from_str(out.trim()).expect("JSON evidence on stdout");
    assert_eq!(
        evidence["outcome"], "observed_expected_change",
        "{evidence}"
    );
    assert_eq!(evidence["receipt_matched"], false, "{evidence}");

    let journal_text = std::fs::read_to_string(&journal).expect("journal must exist");
    std::fs::remove_file(&journal).ok();
    remove_reported_attempt_marker(&out);
    let journal_value: Value = serde_json::from_str(&journal_text).unwrap();
    assert_eq!(journal_value["sends"], 1, "{journal_value}");
    assert_eq!(journal_value["receipt_matched"], false, "{journal_value}");
    assert_eq!(
        journal_value["outcome"], "observed_expected_change",
        "{journal_value}"
    );
}

#[test]
fn serial_apply_uses_exact_checksummed_request_on_one_connection() {
    let (port, _, log) = spawn_peer_logged(PeerScript {
        states: pre_move_states(),
        probes: vec![(16, vec![serial_c()]), (255, vec![serial_a(), serial_b()])],
        option: Some(5),
        address_checksum: Some(true),
        address_receipt: true,
        post_states: Some(post_move_states()),
        post_probes: Some(vec![
            (6, vec![serial_a()]),
            (16, vec![serial_c()]),
            (255, vec![serial_b()]),
        ]),
    });
    let plan = plan_file_for_port_with_checksum(port, "apply-checksummed.json", true);
    let journal = temp_path("apply-checksummed-journal.json");
    let addr = format!("127.0.0.1:{port}");
    let (status, out, err) = run(
        BIN,
        &[
            "serial-apply",
            "--pci",
            &addr,
            "--plan",
            plan.to_str().unwrap(),
            "--journal",
            journal.to_str().unwrap(),
            "--timeout",
            "30",
        ],
    );
    std::fs::remove_file(&plan).ok();
    std::fs::remove_file(&journal).ok();
    remove_reported_attempt_marker(&out);
    assert!(
        status.success(),
        "checksummed apply must succeed: {out} {err}"
    );
    let evidence: Value = serde_json::from_str(out.trim()).unwrap();
    assert_eq!(
        evidence["outcome"], "observed_expected_change",
        "{evidence}"
    );
    assert_eq!(evidence["receipt_matched"], true, "{evidence}");
    assert_eq!(evidence["command_checksum"], true, "{evidence}");
    // A checksummed plan keeps every observation frame checksummed.
    assert_session_frames(&log.lock().unwrap(), true);
}

/// Assert every MMI, IDENTIFY and recall request used one checksum mode.
fn assert_session_frames(log: &[Vec<u8>], checksummed: bool) {
    let mmi = if checksummed {
        b"05FF00FAFF0003".as_slice()
    } else {
        b"05FF00FAFF00".as_slice()
    };
    let hex_body = |line: &Vec<u8>| -> Vec<u8> {
        let body = &line[1..line.len() - 1];
        match body.last() {
            Some(b'g'..=b'z') => body[..body.len() - 1].to_vec(),
            _ => body.to_vec(),
        }
    };
    let bodies: Vec<Vec<u8>> = log.iter().map(hex_body).collect();
    assert!(
        bodies.iter().any(|body| body.as_slice() == mmi),
        "expected MMI in the plan's checksum mode: {log:?}"
    );
    for body in &bodies {
        if body.starts_with(b"05FF00FAFF00") {
            assert_eq!(body.as_slice(), mmi, "MMI mode mismatch: {log:?}");
        } else if body.starts_with(b"46") && body.get(6..8) == Some(b"21".as_slice()) {
            let expected = if checksummed { 12 } else { 10 };
            assert_eq!(body.len(), expected, "IDENTIFY mode mismatch: {log:?}");
        } else if body.starts_with(b"46") && body.get(6..8) == Some(b"1A".as_slice()) {
            let expected = if checksummed { 14 } else { 12 };
            assert_eq!(body.len(), expected, "recall mode mismatch: {log:?}");
        }
    }
}

#[test]
fn serial_apply_speaks_the_plans_checksum_off_session() {
    let (port, _, log) = spawn_peer_logged(PeerScript {
        states: pre_move_states(),
        probes: vec![(16, vec![serial_c()]), (255, vec![serial_a(), serial_b()])],
        option: Some(5),
        address_checksum: Some(false),
        address_receipt: true,
        post_states: Some(post_move_states()),
        post_probes: Some(vec![
            (6, vec![serial_a()]),
            (16, vec![serial_c()]),
            (255, vec![serial_b()]),
        ]),
    });
    let plan = plan_file_for_port(port, "apply-bare-session.json");
    let journal = temp_path("apply-bare-session-journal.json");
    let addr = format!("127.0.0.1:{port}");
    let (status, out, err) = run(
        BIN,
        &[
            "serial-apply",
            "--pci",
            &addr,
            "--plan",
            plan.to_str().unwrap(),
            "--journal",
            journal.to_str().unwrap(),
            "--timeout",
            "30",
        ],
    );
    std::fs::remove_file(&plan).ok();
    std::fs::remove_file(&journal).ok();
    remove_reported_attempt_marker(&out);
    assert!(
        status.success(),
        "bare-session apply must succeed: {out} {err}"
    );
    let evidence: Value = serde_json::from_str(out.trim()).unwrap();
    assert_eq!(
        evidence["outcome"], "observed_expected_change",
        "{evidence}"
    );
    assert_eq!(evidence["command_checksum"], false, "{evidence}");
    // A checksum-off plan speaks bare observation frames end to end, while
    // the peer's always-checksummed MMI blocks still parse.
    assert_session_frames(&log.lock().unwrap(), false);
}

#[test]
fn serial_apply_refuses_missing_shared_store_before_connect() {
    let dead = closed_port();
    let plan = plan_file_for_port(dead, "apply-missing-store.json");
    let journal = temp_path("apply-missing-store-journal.json");
    let store = temp_path("apply-missing-store-directory");
    assert!(!store.exists());
    let addr = format!("127.0.0.1:{dead}");
    let (status, out, err) = run(
        BIN,
        &[
            "serial-apply",
            "--pci",
            &addr,
            "--plan",
            plan.to_str().unwrap(),
            "--journal",
            journal.to_str().unwrap(),
            "--attempt-store",
            store.to_str().unwrap(),
        ],
    );
    assert_eq!(
        status.code(),
        Some(1),
        "missing store must fail: {out} {err}"
    );
    assert!(err.contains("cannot resolve shared store"), "{err}");
    assert!(!err.contains("connect"), "must fail before PCI: {err}");
    assert!(out.trim().is_empty());
    assert!(!journal.exists());
    std::fs::remove_file(plan).unwrap();
}

#[test]
fn serial_apply_refuses_existing_journal_before_connect() {
    let plan_port = closed_port();
    let plan = plan_file_for_port(plan_port, "apply-exists.json");
    let journal = temp_path("apply-exists-journal.json");
    std::fs::write(&journal, b"{}").unwrap();
    // --pci matches the plan endpoint on a closed port: only the
    // pre-connect journal check can fire before the refused connection.
    let addr = format!("127.0.0.1:{plan_port}");
    let (status, out, err) = run(
        BIN,
        &[
            "serial-apply",
            "--pci",
            &addr,
            "--plan",
            plan.to_str().unwrap(),
            "--journal",
            journal.to_str().unwrap(),
        ],
    );
    std::fs::remove_file(&plan).ok();
    std::fs::remove_file(&journal).ok();
    assert_eq!(status.code(), Some(1), "existing journal must fail: {err}");
    assert!(err.contains("already exists"), "{err}");
    assert!(
        out.trim().is_empty(),
        "hard errors must keep stdout empty: {out:?}"
    );
    assert!(
        !err.contains("connect"),
        "must fail before connecting: {err}"
    );
}

#[test]
fn serial_commands_refuse_a_routed_plan_before_connect_or_journal() {
    let dead = closed_port();
    let plan = plan_file_for_port(dead, "routed-plan.json");
    let mut doc: Value = serde_json::from_slice(&std::fs::read(&plan).unwrap()).unwrap();
    doc["route"] = serde_json::json!([1]);
    doc["project_sha256"] = Value::from("ab".repeat(32));
    std::fs::write(&plan, serde_json::to_vec(&doc).unwrap()).unwrap();
    let journal = temp_path("routed-journal.json");
    let addr = format!("127.0.0.1:{dead}");
    for args in [
        vec![
            "serial-verify",
            "--pci",
            &addr,
            "--plan",
            plan.to_str().unwrap(),
        ],
        vec![
            "serial-apply",
            "--pci",
            &addr,
            "--plan",
            plan.to_str().unwrap(),
            "--journal",
            journal.to_str().unwrap(),
        ],
    ] {
        let (status, out, err) = run(BIN, &args);
        assert_eq!(status.code(), Some(1), "routed plan must fail: {err}");
        assert!(err.contains("routed_execution_unsupported"), "{err}");
        assert!(
            !err.contains("connect"),
            "must fail before connecting: {err}"
        );
        assert!(
            out.trim().is_empty(),
            "hard errors must keep stdout empty: {out:?}"
        );
    }
    std::fs::remove_file(&plan).ok();
    assert!(!journal.exists(), "no journal may exist after a refusal");
}

#[test]
fn serial_apply_rejects_corrupt_plan_before_connect() {
    let dead = closed_port();
    let plan = temp_path("apply-corrupt-plan.json");
    std::fs::write(&plan, b"[1,2,3]").unwrap();
    let journal = temp_path("apply-corrupt-journal.json");
    let addr = format!("127.0.0.1:{dead}");
    let (status, out, err) = run(
        BIN,
        &[
            "serial-apply",
            "--pci",
            &addr,
            "--plan",
            plan.to_str().unwrap(),
            "--journal",
            journal.to_str().unwrap(),
        ],
    );
    std::fs::remove_file(&plan).ok();
    assert!(
        !journal.exists(),
        "no journal may exist after a plan rejection"
    );
    assert!(
        out.trim().is_empty(),
        "hard errors must keep stdout empty: {out:?}"
    );
    assert_eq!(status.code(), Some(1), "corrupt plan must fail: {err}");
    assert!(err.contains("plan"), "{err}");
    assert!(
        !err.contains("connect"),
        "must fail before connecting: {err}"
    );
}

#[test]
fn serial_apply_reports_definite_precondition_failure_without_journal() {
    let port = spawn_peer(PeerScript {
        states: pre_move_states(),
        probes: vec![(16, vec![serial_c()]), (255, vec![serial_a(), serial_b()])],
        option: Some(7),
        address_checksum: None,
        address_receipt: false,
        post_states: None,
        post_probes: None,
    });
    let plan = plan_file_for_port(port, "apply-option-drift.json");
    let journal = temp_path("apply-option-drift-journal.json");
    let addr = format!("127.0.0.1:{port}");
    let (status, out, err) = run(
        BIN,
        &[
            "serial-apply",
            "--pci",
            &addr,
            "--plan",
            plan.to_str().unwrap(),
            "--journal",
            journal.to_str().unwrap(),
            "--timeout",
            "30",
        ],
    );
    std::fs::remove_file(&plan).ok();
    assert_eq!(status.code(), Some(1), "precondition failure: {err}");
    let evidence: Value = serde_json::from_str(out.trim()).expect("JSON evidence on stdout");
    assert_eq!(evidence["outcome"], "preconditions_failed", "{evidence}");
    assert_eq!(evidence["expected_identity_change"], false, "{evidence}");
    assert_eq!(evidence["whole_operation_replays"], 0, "{evidence}");
    assert_eq!(evidence["journal"], Value::Null, "{evidence}");
    assert!(
        !journal.exists(),
        "no journal may precede passed preconditions"
    );
}

#[test]
fn serial_apply_reports_classified_post_send_observation() {
    // Phased peer with INTENT PRESERVED (no weakening): the send reaches
    // the wire but the bus never moves, so the post-send observation
    // classifies `observed_unchanged` — a classified failure (exit 1 with
    // JSON evidence in the verify shape + journal), not a hard error.
    // PRE-move serves preconditions (option 05 + inventory equal to
    // plan.before); the post phase serves PRE-move again so the
    // after-observation still sees the unmoved bus.
    let port = spawn_peer(PeerScript {
        states: pre_move_states(),
        probes: vec![(16, vec![serial_c()]), (255, vec![serial_a(), serial_b()])],
        option: Some(5),
        address_checksum: Some(false),
        address_receipt: true,
        post_states: Some(pre_move_states()),
        post_probes: Some(vec![
            (16, vec![serial_c()]),
            (255, vec![serial_a(), serial_b()]),
        ]),
    });
    let plan = plan_file_for_port(port, "apply-unchanged.json");
    let journal = temp_path("apply-unchanged-journal.json");
    let addr = format!("127.0.0.1:{port}");
    let (status, out, err) = run(
        BIN,
        &[
            "serial-apply",
            "--pci",
            &addr,
            "--plan",
            plan.to_str().unwrap(),
            "--journal",
            journal.to_str().unwrap(),
            "--timeout",
            "30",
        ],
    );
    std::fs::remove_file(&plan).ok();
    assert_eq!(
        status.code(),
        Some(1),
        "classified post-send failure must exit 1: {out} {err}"
    );
    let v: Value = serde_json::from_str(out.trim()).expect("JSON evidence on stdout");
    assert_eq!(v["outcome"], "observed_unchanged", "{v}");
    assert_eq!(v["expected_identity_change"], false, "{v}");
    assert_eq!(v["journal"], journal.to_str().unwrap(), "{v}");
    let stdout_diffs = v["unexpected_changes"]
        .as_array()
        .expect("classified stdout evidence must carry per-address diffs");
    assert!(!stdout_diffs.is_empty(), "{v}");
    let journal_text = std::fs::read_to_string(&journal).expect("journal must exist");
    let journal_value: Value = serde_json::from_str(&journal_text).unwrap();
    assert!(journal_value["after_unexpected_changes"]
        .as_array()
        .is_some_and(|diffs| !diffs.is_empty()));
    std::fs::remove_file(&journal).ok();
    remove_reported_attempt_marker(&out);
    assert!(
        journal_text.contains("cbus-selected-serial-apply-v1"),
        "{journal_text}"
    );
    assert!(
        journal_text.contains("observed_unchanged"),
        "{journal_text}"
    );
}

// ------------------------------------------ verify-from-journal (RED first)
//
// `serial-verify --journal FILE` resumes verification from a
// crashed/interrupted apply's journal without the plan file: the journal's
// embedded plan is strictly revalidated (library `load_recovery`) and the
// verify flow is otherwise identical (same endpoint binding, evidence,
// and exit contract), with the evidence referencing the journal path.

// Persistent phased peer: unlike `spawn_peer`, this listener stays up for the
// later verify run. It services one connection at a time, so the apply must do
// preconditions, send, and post-verify on one session. Same port throughout,
// preserving the journal endpoint binding.
fn spawn_persistent_phased_peer(script: PeerScript) -> u16 {
    let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    let port = listener.local_addr().unwrap().port();
    let script = std::sync::Arc::new(script);
    let sent = std::sync::Arc::new(AtomicBool::new(false));
    std::thread::spawn(move || {
        for stream in listener.incoming() {
            let Ok(stream) = stream else { return };
            let mut reader = BufReader::new(stream.try_clone().unwrap());
            let mut first = Vec::new();
            if reader.read_until(b'\r', &mut first).is_err() || first.is_empty() {
                continue;
            }
            if let Err(e) = handle_session(stream, &script, first, &sent, &RequestLog::default()) {
                panic!("peer session failed: {e}");
            }
        }
    });
    port
}

#[test]
fn serial_verify_from_journal_observes_expected_change() {
    // Full circle: apply to a temp journal (happy path), then verify from
    // that journal alone (no plan file) against the same peer, which is
    // still in post-move state. Exit 0 + outcome + journal reference.
    let port = spawn_persistent_phased_peer(PeerScript {
        states: pre_move_states(),
        probes: vec![(16, vec![serial_c()]), (255, vec![serial_a(), serial_b()])],
        option: Some(5),
        address_checksum: Some(false),
        address_receipt: true,
        post_states: Some(post_move_states()),
        post_probes: Some(vec![
            (6, vec![serial_a()]),
            (16, vec![serial_c()]),
            (255, vec![serial_b()]),
        ]),
    });
    let plan = plan_file_for_port(port, "vfj-apply.json");
    let journal = temp_path("vfj-journal.json");
    let addr = format!("127.0.0.1:{port}");
    let (status, apply_out, err) = run(
        BIN,
        &[
            "serial-apply",
            "--pci",
            &addr,
            "--plan",
            plan.to_str().unwrap(),
            "--journal",
            journal.to_str().unwrap(),
            "--timeout",
            "30",
        ],
    );
    assert!(status.success(), "apply must succeed first: {err}");
    let (status, out, err) = run(
        BIN,
        &[
            "serial-verify",
            "--pci",
            &addr,
            "--journal",
            journal.to_str().unwrap(),
            "--timeout",
            "30",
        ],
    );
    std::fs::remove_file(&plan).ok();
    assert!(status.success(), "exit 0 on expected change: {err}");
    let v: Value = serde_json::from_str(out.trim()).expect("JSON evidence on stdout");
    assert_eq!(v["outcome"], "observed_expected_change", "{v}");
    assert_eq!(v["expected_identity_change"], true, "{v}");
    assert_eq!(v["format"], "cbus-selected-serial-verify-v1", "{v}");
    assert_eq!(v["operation"], "verify", "{v}");
    assert_eq!(v["journal"], journal.to_str().unwrap(), "{v}");
    std::fs::remove_file(&journal).ok();
    remove_reported_attempt_marker(&apply_out);
}

#[test]
fn shared_attempt_store_refuses_cross_directory_replay_after_process_exit() {
    let port = spawn_persistent_phased_peer(PeerScript {
        states: pre_move_states(),
        probes: vec![(16, vec![serial_c()]), (255, vec![serial_a(), serial_b()])],
        option: Some(5),
        address_checksum: Some(false),
        address_receipt: true,
        post_states: Some(post_move_states()),
        post_probes: Some(vec![
            (6, vec![serial_a()]),
            (16, vec![serial_c()]),
            (255, vec![serial_b()]),
        ]),
    });
    let plan = plan_file_for_port(port, "shared-attempt-plan.json");
    let root = temp_path("shared-attempt-root");
    let first_dir = root.join("first");
    let second_dir = root.join("second");
    let store = root.join("attempts");
    for path in [&first_dir, &second_dir, &store] {
        std::fs::create_dir_all(path).unwrap();
    }
    let first = first_dir.join("attempt.json");
    let second = second_dir.join("attempt.json");
    let addr = format!("127.0.0.1:{port}");
    let (status, out, err) = run(
        BIN,
        &[
            "serial-apply",
            "--pci",
            &addr,
            "--plan",
            plan.to_str().unwrap(),
            "--journal",
            first.to_str().unwrap(),
            "--attempt-store",
            store.to_str().unwrap(),
            "--timeout",
            "30",
        ],
    );
    assert!(status.success(), "first apply must succeed: {out} {err}");
    let evidence: Value = serde_json::from_str(out.trim()).unwrap();
    let marker = PathBuf::from(evidence["attempt_identity"].as_str().unwrap());
    assert_eq!(
        marker.parent(),
        Some(std::fs::canonicalize(&store).unwrap().as_path())
    );
    let marker_value: Value = serde_json::from_slice(&std::fs::read(&marker).unwrap()).unwrap();
    assert_eq!(marker_value["scope"], "operator_selected_attempt_store");
    assert_eq!(
        marker_value["journal"],
        std::fs::canonicalize(&first_dir)
            .unwrap()
            .join("attempt.json")
            .to_str()
            .unwrap()
    );

    // A restarted process in a different recovery directory must refuse
    // before opening PCI, even if the first main journal is gone. The shared
    // marker remains usable for read-only recovery.
    std::fs::remove_file(&first).unwrap();
    let (status, out, err) = run(
        BIN,
        &[
            "serial-apply",
            "--pci",
            &addr,
            "--plan",
            plan.to_str().unwrap(),
            "--journal",
            second.to_str().unwrap(),
            "--attempt-store",
            store.to_str().unwrap(),
            "--timeout",
            "30",
        ],
    );
    assert_eq!(status.code(), Some(1), "replay must fail: {out} {err}");
    assert!(err.contains("attempt identity already exists"), "{err}");
    assert!(!err.contains("connect"), "must refuse before PCI: {err}");
    assert!(out.trim().is_empty());
    assert!(!second.exists());

    let (status, out, err) = run(
        BIN,
        &[
            "serial-verify",
            "--pci",
            &addr,
            "--journal",
            marker.to_str().unwrap(),
            "--timeout",
            "30",
        ],
    );
    assert!(status.success(), "shared marker recovery: {out} {err}");
    let verification: Value = serde_json::from_str(out.trim()).unwrap();
    assert_eq!(verification["outcome"], "observed_expected_change");

    std::fs::remove_file(&marker).unwrap();
    std::fs::remove_file(&plan).unwrap();
    std::fs::remove_dir_all(&root).unwrap();
}

#[test]
fn durable_attempt_identity_survives_process_exit_and_recovers_without_main_journal() {
    let port = spawn_persistent_phased_peer(PeerScript {
        states: pre_move_states(),
        probes: vec![(16, vec![serial_c()]), (255, vec![serial_a(), serial_b()])],
        option: Some(5),
        address_checksum: Some(false),
        address_receipt: true,
        post_states: Some(post_move_states()),
        post_probes: Some(vec![
            (6, vec![serial_a()]),
            (16, vec![serial_c()]),
            (255, vec![serial_b()]),
        ]),
    });
    let plan = plan_file_for_port(port, "attempt-plan.json");
    let directory = temp_path("attempt-store");
    std::fs::create_dir(&directory).unwrap();
    let journal = directory.join("first.json");
    let second = directory.join("second.json");
    let addr = format!("127.0.0.1:{port}");
    let (status, out, err) = run(
        BIN,
        &[
            "serial-apply",
            "--pci",
            &addr,
            "--plan",
            plan.to_str().unwrap(),
            "--journal",
            journal.to_str().unwrap(),
            "--timeout",
            "30",
        ],
    );
    assert!(status.success(), "first apply must succeed: {out} {err}");
    let evidence: Value = serde_json::from_str(out.trim()).unwrap();
    let marker = PathBuf::from(evidence["attempt_identity"].as_str().unwrap());
    let resolved_directory = std::fs::canonicalize(&directory).unwrap();
    assert_eq!(marker.parent(), Some(resolved_directory.as_path()));
    assert!(marker.is_file());
    let marker_value: Value = serde_json::from_slice(&std::fs::read(&marker).unwrap()).unwrap();
    assert_eq!(marker_value["format"], "cbus-selected-serial-attempt-v1");
    assert_eq!(marker_value["send_may_have_occurred"], true);
    assert_eq!(marker_value["read_only_recovery_only"], true);
    assert_eq!(
        marker_value["journal"],
        resolved_directory.join("first.json").to_str().unwrap()
    );

    // Simulate interruption after the marker was durable but before the
    // main journal was retained. The next process still has a safe read-only
    // recovery path, and a new journal filename cannot re-send the plan.
    std::fs::remove_file(&journal).unwrap();
    let (status, out, err) = run(
        BIN,
        &[
            "serial-verify",
            "--pci",
            &addr,
            "--journal",
            marker.to_str().unwrap(),
            "--timeout",
            "30",
        ],
    );
    assert!(
        status.success(),
        "marker recovery must be read-only: {out} {err}"
    );
    let verify: Value = serde_json::from_str(out.trim()).unwrap();
    assert_eq!(verify["outcome"], "observed_expected_change");
    assert_eq!(verify["journal"], marker.to_str().unwrap());

    let (status, out, err) = run(
        BIN,
        &[
            "serial-apply",
            "--pci",
            &addr,
            "--plan",
            plan.to_str().unwrap(),
            "--journal",
            second.to_str().unwrap(),
            "--timeout",
            "30",
        ],
    );
    assert_eq!(status.code(), Some(1), "replay must fail: {out} {err}");
    assert!(err.contains("attempt identity already exists"), "{err}");
    assert!(
        !err.contains("connect"),
        "must refuse before connecting: {err}"
    );
    assert!(out.trim().is_empty());
    assert!(!second.exists());

    // A tampered marker cannot be used as a source of verified plan intent.
    let mut corrupt = marker_value;
    corrupt["attempt_id"] = Value::from("sha256:bad");
    std::fs::write(&marker, serde_json::to_vec(&corrupt).unwrap()).unwrap();
    let (status, out, err) = run(
        BIN,
        &[
            "serial-verify",
            "--pci",
            &addr,
            "--journal",
            marker.to_str().unwrap(),
            "--timeout",
            "30",
        ],
    );
    assert_eq!(
        status.code(),
        Some(1),
        "corrupt marker must fail: {out} {err}"
    );
    assert!(err.contains("attempt ID"), "{err}");
    assert!(out.trim().is_empty());
    let (status, out, err) = run(
        BIN,
        &[
            "serial-apply",
            "--pci",
            &addr,
            "--plan",
            plan.to_str().unwrap(),
            "--journal",
            second.to_str().unwrap(),
        ],
    );
    assert_eq!(
        status.code(),
        Some(1),
        "tamper must not permit replay: {err}"
    );
    assert!(err.contains("attempt identity already exists"), "{err}");
    assert!(out.trim().is_empty());
    assert!(!second.exists());

    std::fs::remove_file(&marker).unwrap();
    std::fs::remove_file(&plan).unwrap();
    std::fs::remove_dir(&directory).unwrap();
}

#[test]
fn serial_verify_from_journal_rejects_corrupt_journal_before_connect() {
    let dead = closed_port();
    let journal = temp_path("vfj-corrupt.json");
    std::fs::write(&journal, b"{not valid json").unwrap();
    let addr = format!("127.0.0.1:{dead}");
    let (status, out, err) = run(
        BIN,
        &[
            "serial-verify",
            "--pci",
            &addr,
            "--journal",
            journal.to_str().unwrap(),
        ],
    );
    std::fs::remove_file(&journal).ok();
    assert_eq!(status.code(), Some(1), "corrupt journal must fail: {err}");
    assert!(
        out.trim().is_empty(),
        "hard errors must keep stdout empty: {out:?}"
    );
    assert!(err.contains("journal") || err.contains("recovery"), "{err}");
    assert!(
        !err.contains("connect"),
        "must fail before connecting: {err}"
    );
}

#[test]
fn serial_verify_from_journal_rejects_non_apply_journal_before_connect() {
    // A journal envelope from a non-apply operation: right JSON shape,
    // wrong format tag, no embedded plan. Must fail cleanly before any I/O.
    let dead = closed_port();
    let journal = temp_path("vfj-nonapply.json");
    std::fs::write(
        &journal,
        serde_json::to_vec(&serde_json::json!({
            "format": "cbus-selected-serial-verify-v1",
            "operation": "verify",
            "outcome": "observed_expected_change",
        }))
        .unwrap(),
    )
    .unwrap();
    let addr = format!("127.0.0.1:{dead}");
    let (status, out, err) = run(
        BIN,
        &[
            "serial-verify",
            "--pci",
            &addr,
            "--journal",
            journal.to_str().unwrap(),
        ],
    );
    std::fs::remove_file(&journal).ok();
    assert_eq!(status.code(), Some(1), "non-apply journal must fail: {err}");
    assert!(
        out.trim().is_empty(),
        "hard errors must keep stdout empty: {out:?}"
    );
    assert!(err.contains("journal") || err.contains("recovery"), "{err}");
    assert!(
        !err.contains("connect"),
        "must fail before connecting: {err}"
    );
}

#[test]
fn serial_verify_from_journal_rejects_endpoint_mismatch_before_connect() {
    // Valid apply journal first (happy-path apply), then verify from that
    // journal with a different closed --pci. Mirrors
    // `serial_verify_rejects_pci_mismatch_before_connect`: the embedded
    // endpoint binding must refuse before any I/O.
    let port = spawn_peer(PeerScript {
        states: pre_move_states(),
        probes: vec![(16, vec![serial_c()]), (255, vec![serial_a(), serial_b()])],
        option: Some(5),
        address_checksum: Some(false),
        address_receipt: true,
        post_states: Some(post_move_states()),
        post_probes: Some(vec![
            (6, vec![serial_a()]),
            (16, vec![serial_c()]),
            (255, vec![serial_b()]),
        ]),
    });
    let plan = plan_file_for_port(port, "vfj-mismatch-apply.json");
    let journal = temp_path("vfj-mismatch-journal.json");
    let addr = format!("127.0.0.1:{port}");
    let (status, apply_out, err) = run(
        BIN,
        &[
            "serial-apply",
            "--pci",
            &addr,
            "--plan",
            plan.to_str().unwrap(),
            "--journal",
            journal.to_str().unwrap(),
            "--timeout",
            "30",
        ],
    );
    std::fs::remove_file(&plan).ok();
    assert!(status.success(), "apply must succeed first: {err}");
    let cli_port = closed_port();
    assert_ne!(port, cli_port);
    let cli_addr = format!("127.0.0.1:{cli_port}");
    let (status, out, err) = run(
        BIN,
        &[
            "serial-verify",
            "--pci",
            &cli_addr,
            "--journal",
            journal.to_str().unwrap(),
        ],
    );
    std::fs::remove_file(&journal).ok();
    remove_reported_attempt_marker(&apply_out);
    assert_eq!(status.code(), Some(1), "mismatch must fail: {err}");
    assert!(err.contains("endpoint mismatch"), "{err}");
    assert!(err.contains("plan is authoritative"), "{err}");
    assert!(
        out.trim().is_empty(),
        "hard errors must keep stdout empty: {out:?}"
    );
    assert!(
        !err.contains("connect"),
        "must fail before connecting: {err}"
    );
}

#[test]
fn serial_verify_rejects_plan_and_journal_together() {
    // --plan and --journal are mutually exclusive (clap usage error).
    let dead = closed_port();
    let plan = plan_file_for_port(dead, "vfj-conflict.json");
    let journal = temp_path("vfj-conflict-journal.json");
    let addr = format!("127.0.0.1:{dead}");
    let (status, out, err) = run(
        BIN,
        &[
            "serial-verify",
            "--pci",
            &addr,
            "--plan",
            plan.to_str().unwrap(),
            "--journal",
            journal.to_str().unwrap(),
        ],
    );
    std::fs::remove_file(&plan).ok();
    assert_eq!(status.code(), Some(2), "conflicting flags must fail: {err}");
    assert!(err.contains("cannot be used with"), "{err}");
    assert!(
        out.trim().is_empty(),
        "usage errors must keep stdout empty: {out:?}"
    );
}
