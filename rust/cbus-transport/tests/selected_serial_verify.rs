//! P3g: `verify` orchestration over a validated selected-serial plan.
//!
//! Duplex scripted PCI (mirrors `tests/inventory.rs`): the valid plan row
//! from `testdata/vectors/selected_serial_plan.jsonl` embeds the synthetic
//! fixture (`before`: 16 -> [100966.1187] state 1, 255 -> [101136.1558,
//! 101136.1559] state 2; `expected_after`: 6 -> [101136.1558] state 2,
//! 16 unchanged, 255 -> [101136.1559] state 2). Each test replays one
//! post-state through the collector and asserts the oracle classification:
//! expected change, unchanged, unexpected change, and uncertain (MMI
//! rejection truncates the after-collection).
//!
//! Only read requests reach the scripted peer. No address mutation or journal
//! writes occur; no physical endpoint is used.

use std::sync::Arc;
use std::time::Duration;

use cbus_protocol::cal::Cal;
use cbus_protocol::packet::Packet;
use cbus_transport::verify::VerifyOutcome;
use cbus_transport::verify::{verify_plan, VerifyOptions};
use cbus_transport::PciClient;
use tokio::io::{AsyncBufReadExt, AsyncReadExt, AsyncWriteExt, BufReader};

const IDENTIFY_QUIET: Duration = Duration::from_secs(2);

fn valid_plan_doc() -> serde_json::Value {
    let line = include_str!("../../testdata/vectors/selected_serial_plan.jsonl")
        .lines()
        .next()
        .expect("vector file must have a valid plan row");
    let outer: serde_json::Value = serde_json::from_str(line).expect("vector line must be JSON");
    outer["document"].clone()
}

fn expected_plan_doc() -> Vec<u8> {
    let doc = valid_plan_doc();
    assert_eq!(doc["serial"], serde_json::Value::from("101136.1558"));
    assert_eq!(doc["destination"], serde_json::Value::from(6));
    serde_json::to_vec(&doc).unwrap()
}

async fn setup() -> (Arc<PciClient>, BufReader<tokio::io::DuplexStream>) {
    let (client, remote) = tokio::io::duplex(8192);
    let (rd, wr) = tokio::io::split(client);
    let (tx, _rx) = tokio::sync::mpsc::unbounded_channel();
    let pci = PciClient::new(Box::new(rd), Box::new(wr), tx);
    pci.pci_reset().await.unwrap();
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

fn before_states() -> [u8; 256] {
    let mut states = [0u8; 256];
    states[16] = 1;
    states[255] = 2;
    states
}

fn expected_states() -> [u8; 256] {
    let mut states = [0u8; 256];
    states[6] = 2;
    states[16] = 1;
    states[255] = 2;
    states
}

#[tokio::test(start_paused = true)]
async fn verify_observes_expected_change() {
    let doc = expected_plan_doc();
    let (pci, mut remote) = setup().await;
    let worker = tokio::spawn({
        let pci = pci.clone();
        async move {
            verify_plan(&doc, &pci, VerifyOptions::default())
                .await
                .unwrap()
        }
    });

    // Fresh inventory replays the post-move state: collector MMI, probes in
    // ascending address order, then the explicit MMI bookend.
    let states = expected_states();
    serve_mmi(&mut remote, &states).await;
    serve_probes(
        &mut remote,
        &[
            serial_probe(6, vec![serial_a()]),
            serial_probe(16, vec![serial_c()]),
            serial_probe(255, vec![serial_b()]),
        ],
    )
    .await;
    serve_mmi(&mut remote, &states).await;

    let evidence = worker.await.unwrap();
    assert_eq!(evidence.outcome, VerifyOutcome::ObservedExpectedChange);
    assert!(evidence.expected_identity_change);
    assert!(evidence.unexpected_changes.is_empty());
    assert!(evidence.after_collection_complete);
    assert!(evidence.errors.is_empty());
    assert!(!evidence.atomic_observation);
    assert!(!evidence.firmware_persistence_verified);
    assert!(!evidence.physical_compatibility_verified);
    assert!(evidence.exclusive_ownership_required);
    assert!(!evidence.movement_verified);
    assert!(!evidence.persistence_verified);
    assert!(!evidence.plan_transport_settings_enforced);
    assert!(!evidence.endpoint_binding_verified);
    assert!(!evidence.local_serial_binding_verified);
    assert!(!evidence.raw_transport_evidence_verified);
    assert!(evidence.underlying_read_retries_possible);
    assert_eq!(evidence.whole_operation_replays, 0);
    assert!(evidence.non_commissioning_traffic_may_interleave);
    assert!(!evidence.wire_quiescence_after_return_verified);
    assert!(evidence.discard_client_after_deadline_or_cancellation);
}

#[tokio::test(start_paused = true)]
async fn verify_observes_unchanged() {
    let doc = expected_plan_doc();
    let (pci, mut remote) = setup().await;
    let worker = tokio::spawn({
        let pci = pci.clone();
        async move {
            verify_plan(&doc, &pci, VerifyOptions::default())
                .await
                .unwrap()
        }
    });

    // Fresh inventory replays the pre-move state.
    let states = before_states();
    serve_mmi(&mut remote, &states).await;
    serve_probes(
        &mut remote,
        &[
            serial_probe(16, vec![serial_c()]),
            serial_probe(255, vec![serial_a(), serial_b()]),
        ],
    )
    .await;
    serve_mmi(&mut remote, &states).await;

    let evidence = worker.await.unwrap();
    assert_eq!(evidence.outcome, VerifyOutcome::ObservedUnchanged);
    assert!(!evidence.expected_identity_change);
    assert!(evidence.after_collection_complete);
    assert!(evidence.errors.is_empty());
    // Diffs are always computed against the embedded expectation.
    let changed: Vec<u8> = evidence
        .unexpected_changes
        .iter()
        .map(|diff| diff.address)
        .collect();
    assert_eq!(changed, vec![6, 255]);
}

#[tokio::test(start_paused = true)]
async fn verify_observes_unexpected_change() {
    let doc = expected_plan_doc();
    let (pci, mut remote) = setup().await;
    let worker = tokio::spawn({
        let pci = pci.clone();
        async move {
            verify_plan(&doc, &pci, VerifyOptions::default())
                .await
                .unwrap()
        }
    });

    // Swapping serials at 6 and 255 differs from both planned snapshots,
    // but preserves a complete collection without cross-address duplicates.
    let states = expected_states();
    serve_mmi(&mut remote, &states).await;
    serve_probes(
        &mut remote,
        &[
            serial_probe(6, vec![serial_b()]),
            serial_probe(16, vec![serial_c()]),
            serial_probe(255, vec![serial_a()]),
        ],
    )
    .await;
    serve_mmi(&mut remote, &states).await;

    let evidence = worker.await.unwrap();
    assert_eq!(evidence.outcome, VerifyOutcome::ObservedUnexpectedChange);
    assert!(!evidence.expected_identity_change);
    assert!(evidence.after_collection_complete);
    assert!(evidence.errors.is_empty());
    let changed: Vec<u8> = evidence
        .unexpected_changes
        .iter()
        .map(|diff| diff.address)
        .collect();
    assert_eq!(changed, vec![6, 255]);
    for diff in &evidence.unexpected_changes {
        if diff.address == 6 {
            assert_eq!(diff.expected_serials, vec!["101136.1558".to_string()]);
            assert_eq!(diff.observed_serials, vec!["101136.1559".to_string()]);
            assert_eq!((diff.expected_state, diff.observed_state), (2, 2));
        }
    }
}

#[tokio::test(start_paused = true)]
async fn verify_reports_uncertain_on_truncated_inventory() {
    let doc = expected_plan_doc();
    let (pci, mut remote) = setup().await;
    let worker = tokio::spawn({
        let pci = pci.clone();
        async move {
            verify_plan(&doc, &pci, VerifyOptions::default())
                .await
                .unwrap()
        }
    });

    // The PCI rejects the collection MMI: no complete after-observation.
    let request = line(&mut remote).await;
    assert!(request.starts_with(b"\\05FF00FAFF0003"));
    let code = request[request.len() - 2];
    remote.get_mut().write_all(&[code, b'#']).await.unwrap();

    let evidence = worker.await.unwrap();
    assert_eq!(evidence.outcome, VerifyOutcome::Uncertain);
    assert!(!evidence.expected_identity_change);
    assert!(!evidence.after_collection_complete);
    assert!(!evidence.errors.is_empty());
    assert!(evidence.unexpected_changes.is_empty());
}

#[tokio::test(start_paused = true)]
async fn verify_reports_uncertain_on_mmi_state_value_drift() {
    let doc = expected_plan_doc();
    let (pci, mut remote) = setup().await;
    let worker = tokio::spawn({
        let pci = pci.clone();
        async move {
            verify_plan(&doc, &pci, VerifyOptions::default())
                .await
                .unwrap()
        }
    });

    // Value-only drift between the collector-opening MMI and the closing
    // bookend read: same presence set (6, 16, 255 all still present), but
    // the state value at 6 changed. The old presence-only membership check
    // would have passed this with false certainty; full 256-state bookend
    // equality must reject it as Uncertain on a complete collection.
    let opening = expected_states();
    serve_mmi(&mut remote, &opening).await;
    serve_probes(
        &mut remote,
        &[
            serial_probe(6, vec![serial_a()]),
            serial_probe(16, vec![serial_c()]),
            serial_probe(255, vec![serial_b()]),
        ],
    )
    .await;
    let mut closing = expected_states();
    closing[6] = 1;
    assert_ne!(opening, closing);
    assert_ne!(closing[6], 0);
    serve_mmi(&mut remote, &closing).await;

    let evidence = worker.await.unwrap();
    assert_eq!(evidence.outcome, VerifyOutcome::Uncertain);
    assert!(!evidence.expected_identity_change);
    assert!(evidence.after_collection_complete);
    assert!(!evidence.errors.is_empty());
    assert!(evidence.unexpected_changes.is_empty());
}

#[tokio::test(start_paused = true)]
async fn verify_reports_uncertain_on_serial_at_two_addresses() {
    let doc = expected_plan_doc();
    let (pci, mut remote) = setup().await;
    let worker = tokio::spawn({
        let pci = pci.clone();
        async move {
            verify_plan(&doc, &pci, VerifyOptions::default())
                .await
                .unwrap()
        }
    });

    // The selected serial is scripted at two addresses (6 and 255). The
    // collector itself stays complete and non-partial (no per-address
    // errors), so the old classifier would have reported an unexpected
    // change with complete=true; the cross-address seen-set must reject
    // it as Uncertain, still with complete=true because the collection
    // completed before validation failed.
    let states = expected_states();
    serve_mmi(&mut remote, &states).await;
    serve_probes(
        &mut remote,
        &[
            serial_probe(6, vec![serial_a()]),
            serial_probe(16, vec![serial_c()]),
            serial_probe(255, vec![serial_a(), serial_b()]),
        ],
    )
    .await;
    serve_mmi(&mut remote, &states).await;

    let evidence = worker.await.unwrap();
    assert_eq!(evidence.outcome, VerifyOutcome::Uncertain);
    assert!(!evidence.expected_identity_change);
    assert!(evidence.after_collection_complete);
    assert!(!evidence.errors.is_empty());
    assert!(evidence.unexpected_changes.is_empty());
}

async fn assert_no_request(remote: &mut BufReader<tokio::io::DuplexStream>) {
    let mut byte = [0u8; 1];
    assert!(
        tokio::time::timeout(Duration::from_millis(1), remote.read_exact(&mut byte))
            .await
            .is_err(),
        "unexpected request after verification/preflight"
    );
}

fn expected_probes(serials: Vec<Vec<u8>>) -> Vec<(u8, u8, Vec<Vec<u8>>)> {
    vec![
        serial_probe(6, serials),
        serial_probe(16, vec![serial_c()]),
        serial_probe(255, vec![serial_b()]),
    ]
}

#[tokio::test(start_paused = true)]
async fn invalid_plan_is_rejected_before_any_request() {
    let (pci, mut remote) = setup().await;
    let mut doc = valid_plan_doc();
    doc["expected_after"]["states"][6] = 0.into();
    assert!(verify_plan(
        &serde_json::to_vec(&doc).unwrap(),
        &pci,
        VerifyOptions::default()
    )
    .await
    .is_err());
    assert_no_request(&mut remote).await;
}

#[tokio::test(start_paused = true)]
async fn invalid_collection_deadline_sends_nothing() {
    let (pci, mut remote) = setup().await;
    let mut options = VerifyOptions::default();
    options.inventory.total_deadline = Duration::ZERO;
    let evidence = verify_plan(&expected_plan_doc(), &pci, options)
        .await
        .unwrap();
    assert_eq!(evidence.outcome, VerifyOutcome::Uncertain);
    assert!(!evidence.after_collection_complete);
    assert!(evidence.errors[0].contains("deadlines"));
    assert_no_request(&mut remote).await;
}

#[tokio::test(start_paused = true)]
async fn failed_closing_mmi_is_not_a_complete_collection() {
    let (pci, mut remote) = setup().await;
    let worker = tokio::spawn(async move {
        verify_plan(&expected_plan_doc(), &pci, VerifyOptions::default())
            .await
            .unwrap()
    });
    serve_mmi(&mut remote, &expected_states()).await;
    serve_probes(&mut remote, &expected_probes(vec![serial_a()])).await;
    let request = line(&mut remote).await;
    assert!(request.starts_with(b"\\05FF00FAFF0003"));
    let code = request[request.len() - 2];
    remote.write_all(&[code, b'#']).await.unwrap();
    let evidence = worker.await.unwrap();
    assert_eq!(evidence.outcome, VerifyOutcome::Uncertain);
    assert!(!evidence.after_collection_complete);
    assert!(evidence.errors[0].starts_with("after_mmi:"));
    assert_no_request(&mut remote).await;
}

#[tokio::test(start_paused = true)]
async fn identical_serial_duplicates_are_accepted_but_conflicting_blocks_are_not() {
    for conflicting in [false, true] {
        let (pci, mut remote) = setup().await;
        let worker = tokio::spawn(async move {
            verify_plan(&expected_plan_doc(), &pci, VerifyOptions::default())
                .await
                .unwrap()
        });
        let mut duplicate = serial_a();
        if conflicting {
            duplicate[0] ^= 1;
        }
        serve_mmi(&mut remote, &expected_states()).await;
        serve_probes(&mut remote, &[serial_probe(6, vec![serial_a(), duplicate])]).await;
        if !conflicting {
            serve_probes(
                &mut remote,
                &[
                    serial_probe(16, vec![serial_c()]),
                    serial_probe(255, vec![serial_b()]),
                ],
            )
            .await;
            serve_mmi(&mut remote, &expected_states()).await;
        }
        let evidence = worker.await.unwrap();
        if conflicting {
            assert_eq!(evidence.outcome, VerifyOutcome::Uncertain);
            assert!(!evidence.after_collection_complete);
            assert!(evidence.errors[0].contains("conflicting identity blocks"));
        } else {
            assert_eq!(evidence.outcome, VerifyOutcome::ObservedExpectedChange);
            assert!(evidence.after_collection_complete);
            assert!(evidence.errors.is_empty());
        }
        assert_no_request(&mut remote).await;
    }
}

#[tokio::test(start_paused = true)]
async fn unknown_and_malformed_serials_preserve_partial_error_without_followup_mmi() {
    for raw in [vec![0u8; 12], vec![0u8; 11]] {
        let (pci, mut remote) = setup().await;
        let worker = tokio::spawn(async move {
            verify_plan(&expected_plan_doc(), &pci, VerifyOptions::default())
                .await
                .unwrap()
        });
        serve_mmi(&mut remote, &expected_states()).await;
        serve_probes(&mut remote, &[serial_probe(6, vec![raw])]).await;
        let evidence = worker.await.unwrap();
        assert_eq!(evidence.outcome, VerifyOutcome::Uncertain);
        assert!(!evidence.after_collection_complete);
        assert!(evidence
            .errors
            .iter()
            .any(|error| error.contains("address 6 IDENTIFY4")));
        assert_no_request(&mut remote).await;
    }
}

#[tokio::test(start_paused = true)]
async fn mmi_error_state_cannot_be_classified_as_a_healthy_change() {
    let (pci, mut remote) = setup().await;
    let worker = tokio::spawn(async move {
        verify_plan(&expected_plan_doc(), &pci, VerifyOptions::default())
            .await
            .unwrap()
    });
    let mut states = expected_states();
    states[6] = 3;
    serve_mmi(&mut remote, &states).await;
    serve_probes(&mut remote, &expected_probes(vec![serial_a()])).await;
    serve_mmi(&mut remote, &states).await;
    let evidence = worker.await.unwrap();
    assert_eq!(evidence.outcome, VerifyOutcome::Uncertain);
    assert!(evidence.after_collection_complete);
    assert!(evidence.errors[0].contains("MMI reports an error state"));
    assert_no_request(&mut remote).await;
}

#[tokio::test(start_paused = true)]
async fn missing_plan_local_address_cannot_supply_a_complete_observation() {
    let (pci, mut remote) = setup().await;
    let worker = tokio::spawn(async move {
        verify_plan(&expected_plan_doc(), &pci, VerifyOptions::default())
            .await
            .unwrap()
    });
    // Missing local presence stops before any serial or closing request.
    serve_mmi(&mut remote, &[0; 256]).await;
    let evidence = worker.await.unwrap();
    assert_eq!(evidence.outcome, VerifyOutcome::Uncertain);
    assert!(!evidence.after_collection_complete);
    assert!(evidence.errors[0].contains("absent plan local address"));
    assert_no_request(&mut remote).await;
}

#[tokio::test(start_paused = true)]
async fn raw_plan_duplicate_keys_and_both_size_bounds_are_rejected_before_io() {
    use cbus_transport::plan::MAX_PLAN_BYTES;
    let (pci, mut remote) = setup().await;
    let valid = String::from_utf8(expected_plan_doc()).unwrap();
    let duplicate = valid.replacen("{", "{\"source\":255,", 1).into_bytes();
    let mut inflated = valid_plan_doc();
    inflated["before"]["timing"]["extra"] = "é".repeat(MAX_PLAN_BYTES / 6).into();
    let canonical_oversize = serde_json::to_vec(&inflated).unwrap();
    assert!(canonical_oversize.len() < MAX_PLAN_BYTES);
    for (raw, reason) in [
        (duplicate, "duplicate_field"),
        (vec![b' '; MAX_PLAN_BYTES + 1], "oversize"),
        (canonical_oversize, "canonical_oversize"),
    ] {
        let error = verify_plan(&raw, &pci, VerifyOptions::default())
            .await
            .unwrap_err();
        assert!(error.to_string().contains(reason), "{error}");
        assert_no_request(&mut remote).await;
    }
}

#[tokio::test(start_paused = true)]
async fn confirmed_quiet_empty_serial_window_is_complete_but_uncertain() {
    let (pci, mut remote) = setup().await;
    let worker = tokio::spawn(async move {
        verify_plan(&expected_plan_doc(), &pci, VerifyOptions::default())
            .await
            .unwrap()
    });
    serve_mmi(&mut remote, &expected_states()).await;
    serve_probes(&mut remote, &expected_probes(vec![])).await;
    serve_mmi(&mut remote, &expected_states()).await;
    let evidence = worker.await.unwrap();
    assert_eq!(evidence.outcome, VerifyOutcome::Uncertain);
    assert!(evidence.after_collection_complete);
    assert!(evidence.errors[0].contains("address 6 has no known serial"));
    assert_no_request(&mut remote).await;
}

#[tokio::test(start_paused = true)]
async fn unrelated_type_and_firmware_replies_do_not_enter_serial_validation() {
    let (pci, mut remote) = setup().await;
    let worker = tokio::spawn(async move {
        verify_plan(&expected_plan_doc(), &pci, VerifyOptions::default())
            .await
            .unwrap()
    });
    serve_mmi(&mut remote, &expected_states()).await;
    // The verifier requests only IDENTIFY4; malformed unsolicited 1/2 payloads
    // must not substitute for, or invalidate, a valid serial observation.
    let request = line(&mut remote).await;
    assert_eq!(&request[..11], b"\\4606002104");
    let code = request[request.len() - 2];
    remote.write_all(&[code, b'.']).await.unwrap();
    reply(&mut remote, 6, &identify_reply(1, &[0xff])).await;
    reply(&mut remote, 6, &identify_reply(2, &[])).await;
    reply(&mut remote, 6, &identify_reply(4, &serial_a())).await;
    tokio::task::yield_now().await;
    tokio::time::advance(IDENTIFY_QUIET).await;
    serve_probes(
        &mut remote,
        &[
            serial_probe(16, vec![serial_c()]),
            serial_probe(255, vec![serial_b()]),
        ],
    )
    .await;
    serve_mmi(&mut remote, &expected_states()).await;
    let evidence = worker.await.unwrap();
    assert_eq!(evidence.outcome, VerifyOutcome::ObservedExpectedChange);
    assert!(evidence.errors.is_empty());
}

#[tokio::test(start_paused = true)]
async fn concurrent_programming_and_mmi_wait_until_the_whole_snapshot_finishes() {
    for competing_mmi in [false, true] {
        let (pci, mut remote) = setup().await;
        let verify_client = pci.clone();
        let worker = tokio::spawn(async move {
            verify_plan(
                &expected_plan_doc(),
                &verify_client,
                VerifyOptions::default(),
            )
            .await
            .unwrap()
        });
        serve_mmi(&mut remote, &expected_states()).await;
        // Both observation lanes are held now. A queued competing operation
        // cannot steal an untagged reply or change the commissioning sequence.
        let competitor = tokio::spawn(async move {
            if competing_mmi {
                pci.install_mmi().await.map(|_| ())
            } else {
                pci.identify_all(7, 4).await.map(|_| ())
            }
        });
        tokio::task::yield_now().await;
        serve_probes(&mut remote, &expected_probes(vec![serial_a()])).await;
        assert!(!competitor.is_finished());
        serve_mmi(&mut remote, &expected_states()).await;
        assert_eq!(
            worker.await.unwrap().outcome,
            VerifyOutcome::ObservedExpectedChange
        );
        if competing_mmi {
            serve_mmi(&mut remote, &expected_states()).await;
        } else {
            serve_probes(&mut remote, &[serial_probe(7, vec![serial_a()])]).await;
        }
        competitor.await.unwrap().unwrap();
        assert_no_request(&mut remote).await;
    }
}

#[tokio::test(start_paused = true)]
async fn either_faulted_lane_rejects_verification_before_an_opening_mmi() {
    for fault_mmi in [false, true] {
        let (pci, mut remote) = setup().await;
        let bad_client = pci.clone();
        let bad = tokio::spawn(async move {
            if fault_mmi {
                bad_client.install_mmi().await.map(|_| ())
            } else {
                bad_client.identify_all(7, 4).await.map(|_| ())
            }
        });
        let request = line(&mut remote).await;
        let code = request[request.len() - 2];
        remote.write_all(&[code, b'#']).await.unwrap();
        assert!(bad.await.unwrap().is_err());
        let evidence = verify_plan(&expected_plan_doc(), &pci, VerifyOptions::default())
            .await
            .unwrap();
        assert_eq!(evidence.outcome, VerifyOutcome::Uncertain);
        assert!(!evidence.after_collection_complete);
        assert!(evidence.errors[0].contains("needs reconnect"));
        assert_no_request(&mut remote).await;
    }
}

#[tokio::test(start_paused = true)]
async fn total_deadline_includes_closing_mmi_and_caller_bounds_replace_plan_timing() {
    let plan = valid_plan_doc();
    assert_eq!(plan["settings"]["overall_timeout"], 5.0);
    assert_eq!(plan["settings"]["command_checksum"], false);
    let (pci, mut remote) = setup().await;
    let mut options = VerifyOptions::default();
    options.inventory.total_deadline = Duration::from_secs(8);
    let worker = tokio::spawn(async move {
        verify_plan(&expected_plan_doc(), &pci, options)
            .await
            .unwrap()
    });
    serve_mmi(&mut remote, &expected_states()).await;
    serve_probes(&mut remote, &expected_probes(vec![serial_a()])).await;
    // Three shared-client quiet windows already exceed the plan's five seconds.
    // The closing request still belongs to our single eight-second Rust budget.
    let request = line(&mut remote).await;
    assert!(request.starts_with(b"\\05FF00FAFF0003"));
    let code = request[request.len() - 2];
    remote.write_all(&[code, b'.']).await.unwrap();
    let evidence = worker.await.unwrap();
    assert_eq!(evidence.outcome, VerifyOutcome::Uncertain);
    assert!(!evidence.after_collection_complete);
    assert!(evidence.errors[0].contains("total observation deadline"));
    assert!(!evidence.plan_transport_settings_enforced);
    assert!(!evidence.wire_quiescence_after_return_verified);
    assert!(evidence.discard_client_after_deadline_or_cancellation);
    assert!(evidence.underlying_read_retries_possible);
    assert_eq!(evidence.whole_operation_replays, 0);
    assert_no_request(&mut remote).await;
}

#[tokio::test(start_paused = true)]
async fn excessive_caller_deadlines_are_rejected_without_io() {
    let (pci, mut remote) = setup().await;
    for total in [false, true] {
        let mut options = VerifyOptions::default();
        if total {
            options.inventory.total_deadline = Duration::from_secs(3601);
        } else {
            options.inventory.per_address_timeout = Duration::from_secs(301);
        }
        let evidence = verify_plan(&expected_plan_doc(), &pci, options)
            .await
            .unwrap();
        assert_eq!(evidence.outcome, VerifyOutcome::Uncertain);
        assert!(!evidence.after_collection_complete);
        assert!(evidence.errors[0].contains("deadlines"));
        assert_no_request(&mut remote).await;
    }
}

#[tokio::test(start_paused = true)]
async fn deadline_bounds_lane_acquisition_and_releases_the_first_guard() {
    let (pci, mut remote) = setup().await;
    let prior_client = pci.clone();
    let prior = tokio::spawn(async move { prior_client.identify_all(7, 4).await });
    let request = line(&mut remote).await;
    let code = request[request.len() - 2];
    remote.write_all(&[code, b'.']).await.unwrap();
    reply(&mut remote, 7, &identify_reply(4, &serial_a())).await;
    let verify_client = pci.clone();
    let mut options = VerifyOptions::default();
    options.inventory.total_deadline = Duration::from_millis(100);
    let worker = tokio::spawn(async move {
        verify_plan(&expected_plan_doc(), &verify_client, options)
            .await
            .unwrap()
    });
    // The earlier IDENTIFY still owns the programming lane until its quiet
    // window ends. Verification times out while acquiring the pair of guards.
    let evidence = worker.await.unwrap();
    assert_eq!(evidence.outcome, VerifyOutcome::Uncertain);
    assert!(evidence.errors[0].contains("total observation deadline"));
    assert!(!evidence.after_collection_complete);
    assert_no_request(&mut remote).await;
    tokio::time::advance(IDENTIFY_QUIET).await;
    assert_eq!(prior.await.unwrap().unwrap(), vec![serial_a()]);
    // The acquired MMI guard was released when the pending combined admission
    // was cancelled. A subsequent request can run normally.
    let later = tokio::spawn(async move { pci.install_mmi().await });
    serve_mmi(&mut remote, &expected_states()).await;
    assert_eq!(later.await.unwrap().unwrap(), expected_states());
}

#[tokio::test(start_paused = true)]
async fn cancelling_an_unconfirmed_serial_read_removes_its_retry_registration() {
    for total in [false, true] {
        let (pci, mut remote) = setup().await;
        let verify_client = pci.clone();
        let mut options = VerifyOptions::default();
        if total {
            options.inventory.total_deadline = Duration::from_millis(200);
        } else {
            options.inventory.per_address_timeout = Duration::from_millis(200);
        }
        let worker = tokio::spawn(async move {
            verify_plan(&expected_plan_doc(), &verify_client, options)
                .await
                .unwrap()
        });
        serve_mmi(&mut remote, &expected_states()).await;
        let request = line(&mut remote).await;
        assert_eq!(&request[..11], b"\\4606002104");
        // Withhold confirmation: the shared client registers this read for
        // retries, but the shorter caller timeout must cancel that registration.
        let evidence = worker.await.unwrap();
        assert_eq!(evidence.outcome, VerifyOutcome::Uncertain);
        assert!(!evidence.after_collection_complete);
        tokio::time::advance(Duration::from_secs(15)).await;
        assert_no_request(&mut remote).await;
        let second = verify_plan(&expected_plan_doc(), &pci, VerifyOptions::default())
            .await
            .unwrap();
        assert!(second.errors[0].contains("needs reconnect"));
        assert_no_request(&mut remote).await;
    }
}
