//! Selected-serial `apply`: option-gated one-shot send plus post-send verify.
//!
//! Duplex scripted PCI (mirrors `tests/selected_serial_verify.rs`) plus a
//! real loopback TCP peer for the one-shot send. The valid plan row from
//! `testdata/vectors/selected_serial_plan.jsonl` selects `101136.1558` to
//! destination 6 with local unit 16; each test rewrites the plan endpoint to
//! its own ephemeral loopback listener (top-level and `before` copies
//! together, preserving internal consistency) and scripts the PCI side:
//! one local-options recall (`recall_parameter(16, 66, 1)`, wire pattern
//! mirrored from the `NET UNRAVELUNIT` service test), then the fresh
//! pre-inventory (a bookended MMI + IDENTIFY4 walk in ascending address
//! order), followed, after the send, by an independent observation with the
//! same bookended shape.

use cbus_protocol::cal::Cal;
use cbus_protocol::packet::Packet;
use cbus_transport::apply::{apply_plan, load_recovery, ApplyError, ApplyOnce, ApplyOptions};
use cbus_transport::plan::validate_plan_document;
use cbus_transport::verify::VerifyOutcome;
use cbus_transport::PciClient;
use std::sync::Arc;
use std::time::Duration;
use tokio::io::{AsyncBufReadExt, AsyncReadExt, AsyncWriteExt, BufReader};
use tokio::net::TcpListener;

const IDENTIFY_QUIET: Duration = Duration::from_secs(2);
const ADDRESS_QUIET: Duration = Duration::from_secs(2);

fn valid_plan_doc() -> serde_json::Value {
    let line = include_str!("../../testdata/vectors/selected_serial_plan.jsonl")
        .lines()
        .next()
        .expect("vector file must have a valid plan row");
    let outer: serde_json::Value = serde_json::from_str(line).expect("vector line must be JSON");
    outer["document"].clone()
}

fn valid_plan_doc_bytes() -> Vec<u8> {
    serde_json::to_vec(&valid_plan_doc()).unwrap()
}

/// Rewrite the plan endpoint (top-level and `before` copies together) to an
/// ephemeral loopback listener, preserving the internal endpoint consistency
/// the validator checks.
fn plan_bytes_for_port(port: u16) -> Vec<u8> {
    let mut doc = valid_plan_doc();
    assert_eq!(doc["serial"], serde_json::Value::from("101136.1558"));
    assert_eq!(doc["destination"], serde_json::Value::from(6));
    doc["endpoint"]["host"] = serde_json::Value::from("127.0.0.1");
    doc["endpoint"]["port"] = serde_json::Value::from(port);
    doc["before"]["endpoint"]["host"] = serde_json::Value::from("127.0.0.1");
    doc["before"]["endpoint"]["port"] = serde_json::Value::from(port);
    serde_json::to_vec(&doc).unwrap()
}

fn enable_command_checksum_in_plan(mut document: serde_json::Value) -> Vec<u8> {
    fn checksum_request_hex(encoded: &str) -> String {
        let wire = hex::decode(encoded).expect("request_hex must be hex");
        assert_eq!(wire.first(), Some(&b'\\'));
        assert_eq!(wire.last(), Some(&b'\r'));
        let confirmed = matches!(wire.get(wire.len() - 2), Some(b'g'..=b'z'));
        let body_end = wire.len() - 1 - usize::from(confirmed);
        let command = hex::decode(&wire[1..body_end]).expect("request body must be hex");
        let checksum = 0u8.wrapping_sub(
            command
                .iter()
                .fold(0u8, |sum, byte| sum.wrapping_add(*byte)),
        );
        let mut checksummed = Vec::new();
        checksummed.push(b'\\');
        checksummed.extend_from_slice(hex::encode_upper(command).as_bytes());
        checksummed.extend_from_slice(format!("{checksum:02X}").as_bytes());
        if confirmed {
            checksummed.push(wire[wire.len() - 2]);
        }
        checksummed.push(b'\r');
        hex::encode(checksummed)
    }

    fn rewrite(value: &mut serde_json::Value) {
        match value {
            serde_json::Value::Array(items) => {
                for item in items {
                    rewrite(item);
                }
            }
            serde_json::Value::Object(object) => {
                for child in object.values_mut() {
                    rewrite(child);
                }
                if let Some(serde_json::Value::String(request)) = object.get_mut("request_hex") {
                    *request = checksum_request_hex(request);
                }
            }
            _ => {}
        }
    }

    rewrite(&mut document);
    document["settings"]["command_checksum"] = serde_json::Value::Bool(true);
    serde_json::to_vec(&document).unwrap()
}

fn checksummed_plan_bytes_for_port(port: u16) -> Vec<u8> {
    let document: serde_json::Value = serde_json::from_slice(&plan_bytes_for_port(port)).unwrap();
    enable_command_checksum_in_plan(document)
}
fn journal_path(name: &str) -> std::path::PathBuf {
    let path = std::env::temp_dir().join(format!(
        "cbus-apply-test-{}-{name}.json",
        std::process::id()
    ));
    let _ = std::fs::remove_file(&path);
    path
}

async fn setup() -> (Arc<PciClient>, BufReader<tokio::io::DuplexStream>) {
    let (client, remote) = tokio::io::duplex(8192);
    let (rd, wr) = tokio::io::split(client);
    let (tx, _rx) = tokio::sync::mpsc::unbounded_channel();
    let pci = PciClient::new(Box::new(rd), Box::new(wr), tx);
    pci.pci_reset().await.unwrap();
    pci.set_local_unit_hint(16).unwrap();
    let mut remote = BufReader::new(remote);
    for _ in 0..8 {
        let mut frame = Vec::new();
        remote.read_until(b'\r', &mut frame).await.unwrap();
    }
    (pci, remote)
}

async fn line(remote: &mut BufReader<tokio::io::DuplexStream>) -> Vec<u8> {
    let mut bytes = Vec::new();
    remote.read_until(b'\r', &mut bytes).await.unwrap();
    bytes
}

fn mmi_block(start: u8, count: usize, states: &[u8; 256]) -> Vec<u8> {
    let block = states[usize::from(start)..usize::from(start) + count].to_vec();
    let wire = Packet::StandardStatus {
        application: 0xff,
        block_start: start,
        states: block,
    }
    .encode_packet()
    .unwrap();
    let mut line = wire;
    line.extend_from_slice(b"\r\n");
    line
}

async fn serve_mmi(remote: &mut BufReader<tokio::io::DuplexStream>, states: &[u8; 256]) {
    let request = line(remote).await;
    assert!(
        request.starts_with(b"\\05FF00FAFF0003"),
        "expected MMI request, got {:?}",
        String::from_utf8_lossy(&request)
    );
    assert_eq!(request.len(), b"\\05FF00FAFF0003g\r".len());
    let code = request[request.len() - 2];
    remote.get_mut().write_all(&[code, b'.']).await.unwrap();
    for (start, count) in [(0u8, 88usize), (88, 88), (176, 80)] {
        remote
            .write_all(&mmi_block(start, count, states))
            .await
            .unwrap();
    }
}

async fn reply(remote: &mut BufReader<tokio::io::DuplexStream>, unit: u8, cal: &[u8]) {
    let mut bytes = vec![0x86, unit, 0x10, 0x01, 0x00];
    bytes.extend(cal);
    let sum = bytes.iter().fold(0u8, |acc, b| acc.wrapping_add(*b));
    bytes.push(0u8.wrapping_sub(sum));
    let wire = format!(
        "{}\r\n",
        bytes.iter().map(|b| format!("{b:02X}")).collect::<String>()
    );
    remote.get_mut().write_all(wire.as_bytes()).await.unwrap();
}

fn identify_reply(attribute: u8, data: &[u8]) -> Vec<u8> {
    Cal::Reply {
        parameter: attribute,
        data: data.to_vec(),
    }
    .encode()
}

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

/// Serve one scripted IDENTIFY probe sequence in collector order.
async fn serve_probes(
    remote: &mut BufReader<tokio::io::DuplexStream>,
    script: &[(u8, u8, Vec<Vec<u8>>)],
) {
    for (unit, attribute, payloads) in script {
        let request = line(remote).await;
        assert!(
            request.starts_with(b"\\46"),
            "expected IDENTIFY request, got {:?}",
            String::from_utf8_lossy(&request)
        );
        assert_eq!(request.len(), 15);
        let command = hex::decode(&request[1..request.len() - 2]).unwrap();
        assert_eq!(&command[..5], &[0x46, *unit, 0, 0x21, *attribute]);
        assert_eq!(
            command
                .iter()
                .fold(0u8, |sum, byte| sum.wrapping_add(*byte)),
            0
        );
        let code = request[request.len() - 2];
        remote.get_mut().write_all(&[code, b'.']).await.unwrap();
        for payload in payloads {
            reply(remote, *unit, &identify_reply(*attribute, payload)).await;
        }
        tokio::task::yield_now().await;
        tokio::time::advance(IDENTIFY_QUIET).await;
        tokio::task::yield_now().await;
    }
}

fn serial_probe(unit: u8, serials: Vec<Vec<u8>>) -> (u8, u8, Vec<Vec<u8>>) {
    (unit, 4, serials)
}

fn expected_states() -> [u8; 256] {
    let mut states = [0u8; 256];
    states[6] = 2;
    states[16] = 1;
    states[255] = 2;
    states
}

fn expected_probes() -> Vec<(u8, u8, Vec<Vec<u8>>)> {
    vec![
        serial_probe(6, vec![serial_a()]),
        serial_probe(16, vec![serial_c()]),
        serial_probe(255, vec![serial_b()]),
    ]
}

fn serial_d() -> Vec<u8> {
    // 101136.1560: a distinct known serial used only to occupy the
    // destination in the occupied-destination precondition test.
    vec![
        0x38, 0xff, 0xff, 0xff, 0xff, 0x18, 0xb1, 0x06, 0x18, 0xa2, 0x00, 0x05,
    ]
}

/// MMI states of the unmoved bus, matching the embedded plan `before`:
/// local unit 16 present, source 255 holding the two known serials.
fn before_states() -> [u8; 256] {
    let mut states = [0u8; 256];
    states[16] = 1;
    states[255] = 2;
    states
}

/// MMI states of the post-move bus (the plan's `expected_after`): the
/// selected serial already sits at destination 6.
fn post_move_states() -> [u8; 256] {
    let mut states = [0u8; 256];
    states[6] = 2;
    states[16] = 1;
    states[255] = 2;
    states
}

/// MMI states with the destination occupied since planning: address 6 is
/// present while source 255 still holds both known serials.
fn occupied_states() -> [u8; 256] {
    let mut states = [0u8; 256];
    states[6] = 1;
    states[16] = 1;
    states[255] = 2;
    states
}

/// Script a complete fresh pre-inventory for the unmoved bus: opening MMI,
/// IDENTIFY4 for each present address, then an identical closing MMI.
async fn serve_before_inventory(remote: &mut BufReader<tokio::io::DuplexStream>) {
    let states = before_states();
    serve_mmi(remote, &states).await;
    serve_probes(
        remote,
        &[
            serial_probe(16, vec![serial_c()]),
            serial_probe(255, vec![serial_a(), serial_b()]),
        ],
    )
    .await;
    serve_mmi(remote, &states).await;
}

/// Script a complete fresh pre-inventory for the post-move bus. The
/// bookends agree, but the exact snapshot is already `expected_after`, so a
/// pre-move plan must be refused.
async fn serve_post_move_inventory(remote: &mut BufReader<tokio::io::DuplexStream>) {
    let states = post_move_states();
    serve_mmi(remote, &states).await;
    serve_probes(
        remote,
        &[
            serial_probe(6, vec![serial_a()]),
            serial_probe(16, vec![serial_c()]),
            serial_probe(255, vec![serial_b()]),
        ],
    )
    .await;
    serve_mmi(remote, &states).await;
}

/// Script a complete fresh pre-inventory whose destination has become
/// occupied since planning. The bookends agree, but the snapshot differs
/// from both `before` and `expected_after`.
async fn serve_occupied_inventory(remote: &mut BufReader<tokio::io::DuplexStream>) {
    let states = occupied_states();
    serve_mmi(remote, &states).await;
    serve_probes(
        remote,
        &[
            serial_probe(6, vec![serial_d()]),
            serial_probe(16, vec![serial_c()]),
            serial_probe(255, vec![serial_a(), serial_b()]),
        ],
    )
    .await;
    serve_mmi(remote, &states).await;
}

/// Answer one live local-options recall for the plan local unit (16),
/// mirroring the `NET UNRAVELUNIT` wire shape: `recall_parameter(16, 66,
/// 1)` sends `\4610001A4201…` and the unit answers one CAL reply carrying
/// the single option byte.
async fn serve_local_options(remote: &mut BufReader<tokio::io::DuplexStream>, option: u8) {
    let request = line(remote).await;
    assert!(
        request.starts_with(b"\\4610001A4201"),
        "expected local-options recall, got {:?}",
        String::from_utf8_lossy(&request)
    );
    let mut bytes = vec![0x86u8, 16, 0x10, 0x00, 0x82, 0x42, option];
    let sum = bytes.iter().fold(0u8, |acc, b| acc.wrapping_add(*b));
    bytes.push(0u8.wrapping_sub(sum));
    let wire = format!(
        "{}\r\n",
        bytes.iter().map(|b| format!("{b:02X}")).collect::<String>()
    );
    remote.get_mut().write_all(wire.as_bytes()).await.unwrap();
    tokio::task::yield_now().await;
}

async fn assert_no_request(remote: &mut BufReader<tokio::io::DuplexStream>) {
    let mut byte = [0u8; 1];
    match tokio::time::timeout(Duration::from_millis(1), remote.read_exact(&mut byte)).await {
        Err(_) => {}
        Ok(Err(error)) if error.kind() == std::io::ErrorKind::UnexpectedEof => {}
        Ok(Ok(_)) => panic!("unexpected request byte after apply: {byte:02X?}"),
        Ok(Err(error)) => panic!("unexpected read error after apply: {error}"),
    }
}

async fn assert_no_connection(listener: &TcpListener) {
    assert!(
        tokio::time::timeout(Duration::from_millis(1), listener.accept())
            .await
            .is_err(),
        "unexpected second send connection"
    );
}

/// Accept the exact one-shot request on the same shared PCI session, return a
/// positive fixed-`g` confirmation plus the exact direct receipt, and let the
/// primitive's quiet interval expire. Any replay remains queued and is caught
/// by [`assert_no_request`].
async fn serve_selected_serial_send(
    remote: &mut BufReader<tokio::io::DuplexStream>,
    expected_request: &[u8],
) {
    let request = line(remote).await;
    assert_eq!(request, expected_request);
    assert_eq!(request.get(request.len() - 2), Some(&b'g'));
    remote.get_mut().write_all(b"g.").await.unwrap();
    let mut receipt = vec![
        0x86, 6, 16, 0x00, 0x87, 0x00, 0x18, 0xb1, 0x06, 0x16, 0xfa, 0xce,
    ];
    let sum = receipt
        .iter()
        .fold(0u8, |acc, byte| acc.wrapping_add(*byte));
    receipt.push(0u8.wrapping_sub(sum));
    let mut wire = hex::encode_upper(receipt).into_bytes();
    wire.extend_from_slice(b"\r\n");
    remote.get_mut().write_all(&wire).await.unwrap();
    tokio::task::yield_now().await;
    tokio::time::advance(ADDRESS_QUIET).await;
    tokio::task::yield_now().await;
}

/// Accept the exact one-shot request and its positive fixed-`g`
/// confirmation, then provide a well-formed receipt for a different serial.
/// The apply result must depend on the independent after-observation rather
/// than treating an unmatched receipt as send failure or replay authorization.
async fn serve_selected_serial_send_with_unmatched_receipt(
    remote: &mut BufReader<tokio::io::DuplexStream>,
    expected_request: &[u8],
) {
    let request = line(remote).await;
    assert_eq!(request, expected_request);
    assert_eq!(request.get(request.len() - 2), Some(&b'g'));
    remote.get_mut().write_all(b"g.").await.unwrap();
    let mut receipt = vec![
        0x86, 6, 16, 0x00, 0x87, 0x00, 0x18, 0xb1, 0x06, 0x17, 0xfa, 0xce,
    ];
    let sum = receipt
        .iter()
        .fold(0u8, |acc, byte| acc.wrapping_add(*byte));
    receipt.push(0u8.wrapping_sub(sum));
    let mut wire = hex::encode_upper(receipt).into_bytes();
    wire.extend_from_slice(b"\r\n");
    remote.get_mut().write_all(&wire).await.unwrap();
    tokio::task::yield_now().await;
    tokio::time::advance(ADDRESS_QUIET).await;
    tokio::task::yield_now().await;
}

fn read_journal(path: &std::path::Path) -> String {
    std::fs::read_to_string(path).expect("journal file must exist")
}

#[tokio::test(start_paused = true)]
async fn apply_moves_selected_serial_and_records_journal() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let doc = checksummed_plan_bytes_for_port(listener.local_addr().unwrap().port());
    let validated = validate_plan_document(&doc).unwrap();
    let expected_request = validated.request_bytes.clone();
    let journal = journal_path("happy");
    let (pci, mut remote) = setup().await;
    let worker = tokio::spawn({
        let pci = pci.clone();
        let journal = journal.clone();
        async move { apply_plan(&doc, &pci, &journal, ApplyOptions::default()).await }
    });

    // Preconditions: a fresh bookended inventory proves the unmoved bus still
    // matches plan.before, then live local option 66 is re-read as 05.
    serve_before_inventory(&mut remote).await;
    serve_local_options(&mut remote, 5).await;
    // The strict-plan bytes are sent exactly once on that same connection.
    serve_selected_serial_send(&mut remote, &expected_request).await;
    // Post-send observation replays the planned post-move state.
    let states = expected_states();
    serve_mmi(&mut remote, &states).await;
    serve_probes(&mut remote, &expected_probes()).await;
    serve_mmi(&mut remote, &states).await;

    let success = worker.await.unwrap().expect("apply must succeed");
    assert_eq!(success.serial, "101136.1558");
    assert_eq!(success.destination, 6);
    assert_eq!(
        success.verify.outcome,
        VerifyOutcome::ObservedExpectedChange
    );
    assert!(success.receipt_matched);
    assert_eq!(success.journal_path, journal);

    let journal_text = read_journal(&journal);
    assert!(journal_text.contains("cbus-selected-serial-apply-v1"));
    assert!(journal_text.contains("after_observed"));
    assert!(journal_text.contains("observed_expected_change"));
    // No second connection and no replay on the shared session.
    assert_no_connection(&listener).await;
    assert_no_request(&mut remote).await;
    std::fs::remove_file(&journal).unwrap();
}

#[tokio::test(start_paused = true)]
async fn expected_after_succeeds_with_an_unmatched_receipt() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let doc = plan_bytes_for_port(listener.local_addr().unwrap().port());
    let expected_request = validate_plan_document(&doc).unwrap().request_bytes;
    let journal = journal_path("expected-after-unmatched-receipt");
    let (pci, mut remote) = setup().await;
    let worker = tokio::spawn({
        let pci = pci.clone();
        let journal = journal.clone();
        async move { apply_plan(&doc, &pci, &journal, ApplyOptions::default()).await }
    });

    serve_before_inventory(&mut remote).await;
    serve_local_options(&mut remote, 5).await;
    serve_selected_serial_send_with_unmatched_receipt(&mut remote, &expected_request).await;
    serve_post_move_inventory(&mut remote).await;

    let success = worker
        .await
        .unwrap()
        .expect("expected after-state must decide success with an unmatched receipt");
    assert_eq!(
        success.verify.outcome,
        VerifyOutcome::ObservedExpectedChange
    );
    assert!(!success.receipt_matched);
    let journal_value: serde_json::Value = serde_json::from_str(&read_journal(&journal)).unwrap();
    assert_eq!(journal_value["sends"], 1);
    assert_eq!(journal_value["receipt_matched"], false);
    assert_eq!(journal_value["outcome"], "observed_expected_change");
    assert_no_connection(&listener).await;
    assert_no_request(&mut remote).await;
    std::fs::remove_file(&journal).unwrap();
}

#[tokio::test(start_paused = true)]
async fn post_send_observation_failure_is_not_a_plan_error() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let doc = plan_bytes_for_port(listener.local_addr().unwrap().port());
    let request = validate_plan_document(&doc).unwrap().request_bytes;
    let journal = journal_path("uncertain");
    let (pci, mut remote) = setup().await;
    let worker = tokio::spawn({
        let pci = pci.clone();
        let journal = journal.clone();
        async move { apply_plan(&doc, &pci, &journal, ApplyOptions::default()).await }
    });

    serve_before_inventory(&mut remote).await;
    serve_local_options(&mut remote, 5).await;
    serve_selected_serial_send(&mut remote, &request).await;
    // The after-inventory is partial: the closing MMI bookend is rejected,
    // so no complete post-send observation exists.
    serve_mmi(&mut remote, &expected_states()).await;
    serve_probes(&mut remote, &expected_probes()).await;
    let request = line(&mut remote).await;
    assert!(request.starts_with(b"\\05FF00FAFF0003"));
    let code = request[request.len() - 2];
    remote.write_all(&[code, b'#']).await.unwrap();

    let error = worker
        .await
        .unwrap()
        .expect_err("uncertain after-state must fail");
    assert!(
        matches!(error, ApplyError::PostSendObservation(_)),
        "post-send failure must use the distinct variant, got {error}"
    );
    assert!(
        !matches!(error, ApplyError::Plan(_)),
        "post-send failure must never map to the no-I/O Plan variant"
    );
    // Error evidence reached the journal even though the send already happened.
    let journal_text = read_journal(&journal);
    assert!(journal_text.contains("post_send_observation"));
    assert!(journal_text.contains("after_mmi"));
    let journal_value: serde_json::Value = serde_json::from_str(&journal_text).unwrap();
    assert_eq!(journal_value["outcome"], "uncertain");
    // Still exactly one send: no replay was attempted after the failure.
    assert_no_connection(&listener).await;
    // Explicit quiescence probe: no after-inventory PCI I/O follows the return.
    assert_no_request(&mut remote).await;
    std::fs::remove_file(&journal).unwrap();
}

#[tokio::test(start_paused = true)]
async fn post_send_unchanged_records_per_address_diffs() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let doc = plan_bytes_for_port(listener.local_addr().unwrap().port());
    let request = validate_plan_document(&doc).unwrap().request_bytes;
    let journal = journal_path("post-send-unchanged");
    let (pci, mut remote) = setup().await;
    let worker = tokio::spawn({
        let pci = pci.clone();
        let journal = journal.clone();
        async move { apply_plan(&doc, &pci, &journal, ApplyOptions::default()).await }
    });

    serve_before_inventory(&mut remote).await;
    serve_local_options(&mut remote, 5).await;
    serve_selected_serial_send(&mut remote, &request).await;
    serve_before_inventory(&mut remote).await;

    let error = worker
        .await
        .unwrap()
        .expect_err("an unchanged post-send bus must fail apply");
    assert!(
        matches!(error, ApplyError::PostSendObservation(_)),
        "{error}"
    );
    let journal_value: serde_json::Value = serde_json::from_str(&read_journal(&journal)).unwrap();
    assert_eq!(journal_value["outcome"], "observed_unchanged");
    assert_eq!(journal_value["after_outcome"], "observed_unchanged");
    let diffs = journal_value["after_unexpected_changes"]
        .as_array()
        .expect("classified observation must retain per-address diffs");
    assert!(!diffs.is_empty(), "journal must not discard real diffs");
    assert!(diffs.iter().any(|diff| diff["address"] == 6));
    assert!(diffs.iter().any(|diff| diff["address"] == 255));
    assert_no_connection(&listener).await;
    assert_no_request(&mut remote).await;
    std::fs::remove_file(&journal).unwrap();
}

#[tokio::test(start_paused = true)]
async fn post_send_unexpected_change_preserves_classified_outcome() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let doc = plan_bytes_for_port(listener.local_addr().unwrap().port());
    let request = validate_plan_document(&doc).unwrap().request_bytes;
    let journal = journal_path("post-send-unexpected");
    let (pci, mut remote) = setup().await;
    let worker = tokio::spawn({
        let pci = pci.clone();
        let journal = journal.clone();
        async move { apply_plan(&doc, &pci, &journal, ApplyOptions::default()).await }
    });

    serve_before_inventory(&mut remote).await;
    serve_local_options(&mut remote, 5).await;
    serve_selected_serial_send(&mut remote, &request).await;
    serve_occupied_inventory(&mut remote).await;

    let error = worker
        .await
        .unwrap()
        .expect_err("an unexpected complete after-state must fail apply");
    assert!(
        matches!(error, ApplyError::PostSendObservation(_)),
        "{error}"
    );
    let journal_value: serde_json::Value = serde_json::from_str(&read_journal(&journal)).unwrap();
    assert_eq!(journal_value["outcome"], "observed_unexpected_change");
    assert_eq!(journal_value["after_outcome"], "observed_unexpected_change");
    assert_eq!(journal_value["after_collection_complete"], true);
    assert!(journal_value["after_unexpected_changes"]
        .as_array()
        .is_some_and(|diffs| !diffs.is_empty()));
    assert_no_connection(&listener).await;
    assert_no_request(&mut remote).await;
    std::fs::remove_file(&journal).unwrap();
}
#[tokio::test(start_paused = true)]
async fn local_option_drift_fails_preconditions_without_journal_or_send() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let doc = plan_bytes_for_port(listener.local_addr().unwrap().port());
    let journal = journal_path("drift");
    let (pci, mut remote) = setup().await;
    let worker = tokio::spawn({
        let pci = pci.clone();
        let journal = journal.clone();
        async move { apply_plan(&doc, &pci, &journal, ApplyOptions::default()).await }
    });

    // Drifted option byte: preconditions must fail before journal and send.
    serve_before_inventory(&mut remote).await;
    serve_local_options(&mut remote, 7).await;

    let error = worker.await.unwrap().expect_err("option drift must fail");
    assert!(
        matches!(error, ApplyError::Preconditions(_)),
        "option drift must fail preconditions, got {error}"
    );
    assert!(error.to_string().contains("05"), "got {error}");
    assert!(
        !journal.exists(),
        "precondition failure must leave no journal"
    );
    assert_no_connection(&listener).await;
    assert_no_request(&mut remote).await;
}

#[tokio::test(start_paused = true)]
async fn invalid_fresh_observation_bounds_fail_before_any_io() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let doc = plan_bytes_for_port(listener.local_addr().unwrap().port());
    let journal = journal_path("invalid-fresh-bounds");
    let (pci, mut remote) = setup().await;
    let mut options = ApplyOptions::default();
    options.verify.inventory.total_deadline = Duration::from_secs(3_601);

    let error = apply_plan(&doc, &pci, &journal, options)
        .await
        .expect_err("invalid observation bounds must fail");
    assert!(matches!(error, ApplyError::Preconditions(_)), "{error}");
    assert!(error.to_string().contains("deadlines"), "{error}");
    assert!(!journal.exists());
    assert_no_connection(&listener).await;
    assert_no_request(&mut remote).await;
}

#[tokio::test(start_paused = true)]
async fn fresh_inventory_bookend_drift_fails_without_journal_or_send() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let doc = plan_bytes_for_port(listener.local_addr().unwrap().port());
    let journal = journal_path("fresh-bookend-drift");
    let (pci, mut remote) = setup().await;
    let worker = tokio::spawn({
        let pci = pci.clone();
        let journal = journal.clone();
        async move { apply_plan(&doc, &pci, &journal, ApplyOptions::default()).await }
    });

    let opening = before_states();
    serve_mmi(&mut remote, &opening).await;
    serve_probes(
        &mut remote,
        &[
            serial_probe(16, vec![serial_c()]),
            serial_probe(255, vec![serial_a(), serial_b()]),
        ],
    )
    .await;
    let mut closing = opening;
    closing[6] = 1;
    serve_mmi(&mut remote, &closing).await;

    let error = worker
        .await
        .unwrap()
        .expect_err("MMI bookend drift must fail");
    assert!(matches!(error, ApplyError::Preconditions(_)), "{error}");
    assert!(error.to_string().contains("bookended"), "{error}");
    assert!(!journal.exists());
    assert_no_connection(&listener).await;
    assert_no_request(&mut remote).await;
}
#[tokio::test(start_paused = true)]
async fn shared_transaction_error_is_recorded_as_send_not_journal() {
    let (pci, mut remote) = setup().await;
    let journal = journal_path("transport");
    let doc = valid_plan_doc_bytes();
    let expected_request = validate_plan_document(&doc).unwrap().request_bytes;
    // Malformed shared-session input happens only after the durable intent
    // record and exact one-shot request. It must be a journal-backed Send error.
    let worker = tokio::spawn({
        let pci = pci.clone();
        let journal = journal.clone();
        async move { apply_plan(&doc, &pci, &journal, ApplyOptions::default()).await }
    });

    serve_before_inventory(&mut remote).await;
    serve_local_options(&mut remote, 5).await;
    assert_eq!(line(&mut remote).await, expected_request);
    remote
        .get_mut()
        .write_all(b"86061000870018B10616000000\r\n")
        .await
        .unwrap();

    let error = worker
        .await
        .unwrap()
        .expect_err("malformed shared-session input must fail");
    assert!(
        matches!(error, ApplyError::Send(_)),
        "transaction failure must use the Send variant, got {error}"
    );
    assert!(
        !matches!(error, ApplyError::Journal(_)),
        "transaction failure must not be mislabeled as a journal failure"
    );
    let journal_text = read_journal(&journal);
    assert!(journal_text.contains("cbus-selected-serial-apply-v1"));
    assert!(journal_text.contains("send_intent_recorded"));
    assert!(journal_text.contains("\"send_attempted\":true"));
    assert!(journal_text.contains("send:"), "{journal_text}");
    let journal_value: serde_json::Value = serde_json::from_str(&journal_text).unwrap();
    assert_eq!(journal_value["exchange_send_attempted"], true);
    assert_eq!(journal_value["send_completed"], true);
    assert_eq!(journal_value["sends"], 1);
    assert_eq!(journal_value["exchange_termination"], "capture_error");
    assert_no_request(&mut remote).await;
    std::fs::remove_file(&journal).unwrap();
}

#[tokio::test(start_paused = true)]
async fn invalid_plan_fails_before_any_io() {
    let (pci, mut remote) = setup().await;
    let journal = journal_path("badplan");
    let mut doc = valid_plan_doc();
    doc["expected_after"]["states"][6] = serde_json::Value::from(0);
    let raw = serde_json::to_vec(&doc).unwrap();
    let error = apply_plan(&raw, &pci, &journal, ApplyOptions::default())
        .await
        .expect_err("invalid plan must fail");
    assert!(
        matches!(error, ApplyError::Plan(_)),
        "pre-send validation must use the Plan variant, got {error}"
    );
    assert!(!journal.exists(), "plan failure must leave no journal");
    assert_no_request(&mut remote).await;
}

#[tokio::test(start_paused = true)]
async fn apply_uses_the_validators_sanitized_plan_value() {
    const PLACEHOLDER: &str = "__ignored_large_python_integer__";
    let mut doc = valid_plan_doc();
    doc["before"]["timing"]["ignored_python_integer"] = serde_json::Value::from(PLACEHOLDER);
    let encoded = serde_json::to_string(&doc).unwrap();
    let raw = encoded
        .replacen(
            &format!("\"{PLACEHOLDER}\""),
            &format!("1{}", "0".repeat(1_000)),
            1,
        )
        .into_bytes();
    // The strict scanner accepts this Python-sized ignored integer and
    // sanitizes it for serde. Re-parsing the original bytes directly would
    // fail before the live option check.
    cbus_transport::plan::validate_plan_document_with_value(&raw).unwrap();

    let journal = journal_path("sanitized-plan");
    let (pci, mut remote) = setup().await;
    let worker = tokio::spawn({
        let pci = pci.clone();
        let journal = journal.clone();
        async move { apply_plan(&raw, &pci, &journal, ApplyOptions::default()).await }
    });
    serve_before_inventory(&mut remote).await;
    serve_local_options(&mut remote, 7).await;
    let error = worker.await.unwrap().expect_err("option drift must fail");
    assert!(matches!(error, ApplyError::Preconditions(_)), "{error}");
    assert!(!journal.exists());
    assert_no_request(&mut remote).await;
}

#[tokio::test(start_paused = true)]
async fn replay_same_plan_different_path_fails_without_second_send() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let doc = plan_bytes_for_port(listener.local_addr().unwrap().port());
    let first_journal = journal_path("replay-first");
    let second_journal = journal_path("replay-second");
    let third_journal = journal_path("replay-third");
    let (pci, mut remote) = setup().await;
    let once = std::sync::Arc::new(ApplyOnce::new(&doc));
    let worker = tokio::spawn({
        let once = std::sync::Arc::clone(&once);
        let pci = pci.clone();
        let journal = first_journal.clone();
        async move { once.apply(&pci, &journal, ApplyOptions::default()).await }
    });

    // First apply runs the full happy path: options, fresh inventory, one
    // send, observation.
    serve_before_inventory(&mut remote).await;
    serve_local_options(&mut remote, 5).await;
    let request = validate_plan_document(&doc).unwrap().request_bytes;
    serve_selected_serial_send(&mut remote, &request).await;
    let states = expected_states();
    serve_mmi(&mut remote, &states).await;
    serve_probes(&mut remote, &expected_probes()).await;
    serve_mmi(&mut remote, &states).await;
    worker.await.unwrap().expect("first apply must succeed");

    // Same coordinator, different journal path: refused with no I/O at all.
    let error = once
        .apply(&pci, &second_journal, ApplyOptions::default())
        .await
        .expect_err("replay must fail");
    assert!(
        matches!(error, ApplyError::AlreadyApplied(_)),
        "replay must use the AlreadyApplied variant, got {error}"
    );
    assert!(
        !second_journal.exists(),
        "replay refusal must not create a second journal"
    );

    // The free function is guarded too: same bytes, yet another path.
    let error = apply_plan(&doc, &pci, &third_journal, ApplyOptions::default())
        .await
        .expect_err("free-function replay must fail");
    assert!(
        matches!(error, ApplyError::AlreadyApplied(_)),
        "free-function replay must use AlreadyApplied, got {error}"
    );
    assert!(
        !third_journal.exists(),
        "free-function replay must not create another journal"
    );

    // Wire-counted: exactly one send reached the listener, and the refused
    // replays issued no further PCI requests either.
    assert_no_connection(&listener).await;
    assert_no_request(&mut remote).await;
    std::fs::remove_file(&first_journal).unwrap();
}

#[tokio::test(start_paused = true)]
async fn canonical_plan_fingerprint_rejects_equivalent_json_encoding() {
    fn reverse_json(value: &serde_json::Value) -> String {
        match value {
            serde_json::Value::Null => "null".to_string(),
            serde_json::Value::Bool(value) => value.to_string(),
            serde_json::Value::Number(value) => value.to_string(),
            serde_json::Value::String(value) => serde_json::to_string(value).unwrap(),
            serde_json::Value::Array(items) => format!(
                "[{}]",
                items.iter().map(reverse_json).collect::<Vec<_>>().join(",")
            ),
            serde_json::Value::Object(object) => {
                let mut keys: Vec<_> = object.keys().collect();
                keys.reverse();
                format!(
                    "{{{}}}",
                    keys.iter()
                        .map(|key| format!(
                            "{}:{}",
                            serde_json::to_string(key).unwrap(),
                            reverse_json(&object[*key])
                        ))
                        .collect::<Vec<_>>()
                        .join(",")
                )
            }
        }
    }

    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let mut first_value: serde_json::Value =
        serde_json::from_slice(&plan_bytes_for_port(listener.local_addr().unwrap().port()))
            .unwrap();
    first_value["endpoint"]["host"] = serde_json::Value::from("0:0:0:0:0:0:0:1");
    first_value["before"]["endpoint"]["host"] = serde_json::Value::from("0:0:0:0:0:0:0:1");
    let doc = serde_json::to_vec(&first_value).unwrap();
    let first_journal = journal_path("canonical-first");
    let second_journal = journal_path("canonical-second");
    let (pci, mut remote) = setup().await;
    let expected_request = validate_plan_document(&doc).unwrap().request_bytes;
    let worker = tokio::spawn({
        let pci = pci.clone();
        let first_journal = first_journal.clone();
        let doc = doc.clone();
        async move { apply_plan(&doc, &pci, &first_journal, ApplyOptions::default()).await }
    });
    serve_before_inventory(&mut remote).await;
    serve_local_options(&mut remote, 5).await;
    assert_eq!(line(&mut remote).await, expected_request);
    remote
        .get_mut()
        .write_all(b"86061000870018B10616000000\r\n")
        .await
        .unwrap();
    assert!(matches!(worker.await.unwrap(), Err(ApplyError::Send(_))));

    let parsed: serde_json::Value = serde_json::from_slice(&doc).unwrap();
    let equivalent = format!(" \n{}\n", reverse_json(&parsed))
        .replace("101136.1558", "101136\\u002e1558")
        .replace("0.02", "2e-2")
        .replace("\"overall_timeout\":5.0", "\"overall_timeout\":5")
        .replace("0:0:0:0:0:0:0:1", "::1")
        .into_bytes();
    assert_ne!(equivalent, doc, "test must change the raw encoding");
    let (_, first_sanitized) =
        cbus_transport::plan::validate_plan_document_with_value(&doc).unwrap();
    let (_, equivalent_sanitized) =
        cbus_transport::plan::validate_plan_document_with_value(&equivalent).unwrap();
    assert_ne!(
        first_sanitized["settings"]["overall_timeout"],
        equivalent_sanitized["settings"]["overall_timeout"],
        "test must cover accepted integer-vs-float equivalence"
    );
    assert_ne!(
        first_sanitized["endpoint"]["host"], equivalent_sanitized["endpoint"]["host"],
        "test must cover accepted equivalent IP spellings"
    );
    let error = apply_plan(&equivalent, &pci, &second_journal, ApplyOptions::default())
        .await
        .expect_err("canonical replay must be refused");
    assert!(matches!(error, ApplyError::AlreadyApplied(_)), "{error}");
    assert!(!second_journal.exists());
    assert_no_connection(&listener).await;
    assert_no_request(&mut remote).await;
    std::fs::remove_file(&first_journal).unwrap();
}

#[tokio::test(start_paused = true)]
async fn same_path_exclusive_create_refuses_without_send() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let doc = plan_bytes_for_port(listener.local_addr().unwrap().port());
    let journal = journal_path("exclusive");
    std::fs::write(&journal, b"reserved").unwrap();
    let (pci, mut remote) = setup().await;
    let worker = tokio::spawn({
        let pci = pci.clone();
        let journal = journal.clone();
        async move { apply_plan(&doc, &pci, &journal, ApplyOptions::default()).await }
    });

    // Preconditions pass (options plus fresh inventory), then the
    // pre-existing file trips exclusive create.
    serve_before_inventory(&mut remote).await;
    serve_local_options(&mut remote, 5).await;

    let error = worker
        .await
        .unwrap()
        .expect_err("occupied journal path must fail");
    assert!(
        matches!(error, ApplyError::Journal(_)),
        "occupied path must use the Journal variant, got {error}"
    );
    assert!(
        error.to_string().contains("exclusive"),
        "occupied path must report the exclusive-create refusal, got {error}"
    );
    assert_no_connection(&listener).await;
    assert_no_request(&mut remote).await;
    std::fs::remove_file(&journal).unwrap();
}

#[tokio::test(start_paused = true)]
async fn load_recovery_round_trips_and_rejects_corrupt() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let doc = plan_bytes_for_port(port);
    let request = validate_plan_document(&doc).unwrap().request_bytes;
    let journal = journal_path("recovery");
    let (pci, mut remote) = setup().await;
    let worker = tokio::spawn({
        let pci = pci.clone();
        let journal = journal.clone();
        async move { apply_plan(&doc, &pci, &journal, ApplyOptions::default()).await }
    });

    serve_before_inventory(&mut remote).await;
    serve_local_options(&mut remote, 5).await;
    serve_selected_serial_send(&mut remote, &request).await;
    let states = expected_states();
    serve_mmi(&mut remote, &states).await;
    serve_probes(&mut remote, &expected_probes()).await;
    serve_mmi(&mut remote, &states).await;
    let success = worker.await.unwrap().expect("apply must succeed");

    // The journal reads back the identical plan.
    let recovered = load_recovery(&journal).expect("journal must reload");
    assert_eq!(recovered.plan.serial, success.serial);
    assert_eq!(recovered.plan.serial, "101136.1558");
    assert_eq!(recovered.plan.destination, success.destination);
    assert_eq!(recovered.plan.destination, 6);
    assert_eq!(recovered.plan.local_unit, 16);
    assert_eq!(recovered.plan.host, "127.0.0.1");
    assert_eq!(recovered.plan.port, port);
    assert!(recovered.send_may_have_occurred);

    // A recovery envelope may never downgrade the durable crash boundary to
    // a definite no-send claim.
    let valid_journal = std::fs::read(&journal).unwrap();
    for field in ["send_intent_recorded", "attempt_recorded", "send_attempted"] {
        let mut weakened: serde_json::Value = serde_json::from_slice(&valid_journal).unwrap();
        weakened[field] = serde_json::Value::Bool(false);
        std::fs::write(&journal, serde_json::to_vec(&weakened).unwrap()).unwrap();
        assert!(
            load_recovery(&journal).is_err(),
            "recovery must reject false {field}"
        );
    }
    std::fs::write(&journal, &valid_journal).unwrap();

    // Duplicate keys at either the recovery envelope or embedded-plan level
    // are ambiguous. Strict recovery must reject them before ordinary JSON
    // parsing can silently keep the last value.
    let valid_text = String::from_utf8(valid_journal.clone()).unwrap();
    let duplicate_envelope =
        valid_text.replacen('{', r#"{"format":"cbus-selected-serial-apply-v1","#, 1);
    std::fs::write(&journal, duplicate_envelope).unwrap();
    assert!(
        matches!(load_recovery(&journal), Err(ApplyError::Journal(_))),
        "top-level duplicate fields must fail as a corrupt journal"
    );
    let duplicate_plan = valid_text.replacen(
        r#""plan":{"#,
        r#""plan":{"format":"cbus-selected-serial-plan-v1","#,
        1,
    );
    assert_ne!(duplicate_plan, valid_text, "test must locate embedded plan");
    std::fs::write(&journal, duplicate_plan).unwrap();
    assert!(
        matches!(load_recovery(&journal), Err(ApplyError::Journal(_))),
        "nested duplicate plan fields must fail as a corrupt journal"
    );
    std::fs::write(&journal, &valid_journal).unwrap();

    // Corrupt content and missing files are errors, never a plan.
    std::fs::write(&journal, b"{not valid json").unwrap();
    assert!(
        load_recovery(&journal).is_err(),
        "corrupt journal must fail"
    );
    std::fs::remove_file(&journal).unwrap();
    assert!(
        load_recovery(&journal).is_err(),
        "missing journal must fail"
    );
    assert_no_connection(&listener).await;
    assert_no_request(&mut remote).await;
}

#[tokio::test(start_paused = true)]
async fn apply_once_journal_error_consumes_single_operator_decision() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let doc = plan_bytes_for_port(listener.local_addr().unwrap().port());
    let occupied = journal_path("once-journal-occupied");
    let fresh = journal_path("once-journal-fresh");
    std::fs::write(&occupied, b"reserved").unwrap();
    let (pci, mut remote) = setup().await;
    let once = std::sync::Arc::new(ApplyOnce::new(&doc));

    // First attempt: options plus fresh inventory pass, then the
    // pre-existing file trips exclusive create. The one-shot coordinator is
    // still consumed: it represents one operator decision, and retry needs a
    // freshly constructed coordinator after the definite no-send result.
    let worker = tokio::spawn({
        let once = std::sync::Arc::clone(&once);
        let pci = pci.clone();
        let occupied = occupied.clone();
        async move { once.apply(&pci, &occupied, ApplyOptions::default()).await }
    });
    serve_before_inventory(&mut remote).await;
    serve_local_options(&mut remote, 5).await;
    let error = worker
        .await
        .unwrap()
        .expect_err("occupied journal path must fail");
    assert!(
        matches!(error, ApplyError::Journal(_)),
        "occupied path must use the Journal variant, got {error}"
    );
    assert_no_connection(&listener).await;

    // A second call on the same object is refused before any PCI I/O even
    // with a new journal path.
    let result = once.apply(&pci, &fresh, ApplyOptions::default()).await;
    assert!(
        matches!(result, Err(ApplyError::AlreadyApplied(_))),
        "journal-error retry must report AlreadyApplied, got {result:?}"
    );
    assert!(!fresh.exists());
    assert_no_connection(&listener).await;
    assert_no_request(&mut remote).await;
    std::fs::remove_file(&occupied).unwrap();
}

#[tokio::test(start_paused = true)]
async fn stale_bus_state_fails_preconditions_without_journal_or_send() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let doc = plan_bytes_for_port(listener.local_addr().unwrap().port());
    let journal = journal_path("stale");
    let (pci, mut remote) = setup().await;
    let worker = tokio::spawn({
        let pci = pci.clone();
        let journal = journal.clone();
        async move { apply_plan(&doc, &pci, &journal, ApplyOptions::default()).await }
    });

    // Options still read 05, but the peer serves the post-move state for a
    // pre-move plan: the selected serial already sits at destination 6, so
    // the fresh inventory cannot prove equal to plan.before.
    serve_post_move_inventory(&mut remote).await;

    let error = worker.await.unwrap().expect_err("stale bus must fail");
    assert!(
        matches!(error, ApplyError::Preconditions(_)),
        "stale bus must fail preconditions, got {error}"
    );
    assert!(
        error.to_string().contains("fresh_before"),
        "stale bus must fail the fresh-before proof, got {error}"
    );
    assert!(
        !journal.exists(),
        "precondition failure must leave no journal"
    );
    // Wire-counted: no send reached the listener, and no further PCI I/O
    // followed the return.
    assert_no_connection(&listener).await;
    assert_no_request(&mut remote).await;
}

#[tokio::test(start_paused = true)]
async fn occupied_destination_fails_preconditions_without_journal_or_send() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let doc = plan_bytes_for_port(listener.local_addr().unwrap().port());
    let journal = journal_path("occupied");
    let (pci, mut remote) = setup().await;
    let worker = tokio::spawn({
        let pci = pci.clone();
        let journal = journal.clone();
        async move { apply_plan(&doc, &pci, &journal, ApplyOptions::default()).await }
    });

    // Options still read 05, but destination 6 shows MMI non-zero with a
    // serial present since planning: the fresh inventory diverges from
    // plan.before and the destination is no longer independently empty.
    serve_occupied_inventory(&mut remote).await;

    let error = worker
        .await
        .unwrap()
        .expect_err("occupied destination must fail");
    assert!(
        matches!(error, ApplyError::Preconditions(_)),
        "occupied destination must fail preconditions, got {error}"
    );
    assert!(
        error.to_string().contains("fresh_"),
        "occupied destination must fail the fresh inventory preconditions, got {error}"
    );
    assert!(
        !journal.exists(),
        "precondition failure must leave no journal"
    );
    // Wire-counted: no send reached the listener, and no further PCI I/O
    // followed the return.
    assert_no_connection(&listener).await;
    assert_no_request(&mut remote).await;
}
