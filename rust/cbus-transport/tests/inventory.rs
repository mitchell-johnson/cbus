//! Duplicate-preserving full-inventory collector acceptance tests.
//!
//! Duplex scripted PCI (mirrors `pci/mmi.rs` + `pci/programming.rs`
//! harnesses): MMI shows addresses 5+9 present; address 5 answers
//! IDENTIFY1/2 + TWO distinct IDENTIFY4 serials; address 9 answers
//! IDENTIFY1/2 + one serial. The collector must return both addresses
//! with both serials at 5 preserved (no collapse), plus coverage flag.
//!
//! This test pins the public `cbus_transport::inventory` contract.

use std::sync::Arc;
use std::time::Duration;

use cbus_protocol::cal::Cal;
use cbus_protocol::packet::{Meta, Packet};
use cbus_protocol::report::StatusReport;
use cbus_transport::inventory::{collect_full_inventory, InventoryOptions};
use cbus_transport::PciClient;
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};

const IDENTIFY_QUIET: Duration = Duration::from_secs(2);

fn options() -> InventoryOptions {
    InventoryOptions {
        per_address_timeout: Duration::from_secs(30),
        total_deadline: Duration::from_secs(120),
    }
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

fn mmi_block(start: u8, count: usize, present: &[usize]) -> Vec<u8> {
    let mut states = vec![0; count];
    for address in present {
        states[*address - usize::from(start)] = 1;
    }
    let wire = Packet::StandardStatus {
        application: 0xff,
        block_start: start,
        states,
    }
    .encode_packet()
    .unwrap();
    let mut line = wire;
    line.extend_from_slice(b"\r\n");
    line
}

async fn reply(remote: &mut BufReader<tokio::io::DuplexStream>, unit: u8, cal: &[u8]) {
    // Captured response route, mirroring the programming harness;
    // independent of the request encoder.
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
    // Wire-faithful Reply CAL: the opcode carries the length nibble, so
    // short IDENTIFY1/2 payloads must not reuse the IDENTIFY4 0x8D form.
    Cal::Reply {
        parameter: attribute,
        data: data.to_vec(),
    }
    .encode()
}

fn serial_a() -> Vec<u8> {
    vec![
        0x38, 0xff, 0xff, 0xff, 0xff, 0x18, 0xb1, 0x06, 0x16, 0xa2, 0x00, 0x05,
    ]
}

fn serial_b() -> Vec<u8> {
    vec![
        0x38, 0xff, 0xff, 0xff, 0xff, 0x18, 0xb1, 0x06, 0x17, 0xa2, 0x00, 0x05,
    ]
}

fn serial_c() -> Vec<u8> {
    vec![
        0xff, 0xff, 0xff, 0x00, 0x00, 0x18, 0xa6, 0x64, 0xa3, 0xb1, 0x00, 0x05,
    ]
}

/// Serve one scripted IDENTIFY probe: read the request, confirm it, then
/// emit the canned replies for that (unit, attribute).
async fn serve_probe(
    remote: &mut BufReader<tokio::io::DuplexStream>,
    unit5_type: &[u8],
    unit5_fw: &[u8],
    unit9_type: &[u8],
    unit9_fw: &[u8],
) {
    let request = line(remote).await;
    assert!(
        request.starts_with(b"\\46"),
        "expected IDENTIFY request, got {:?}",
        String::from_utf8_lossy(&request)
    );
    let unit = u8::from_str_radix(&String::from_utf8_lossy(&request[3..5]), 16).unwrap();
    let attribute = u8::from_str_radix(&String::from_utf8_lossy(&request[9..11]), 16).unwrap();
    let code = request[request.len() - 2];
    remote.get_mut().write_all(&[code, b'.']).await.unwrap();
    match (unit, attribute) {
        (5, 1) => reply(remote, 5, &identify_reply(1, unit5_type)).await,
        (5, 2) => reply(remote, 5, &identify_reply(2, unit5_fw)).await,
        (5, 4) => {
            reply(remote, 5, &identify_reply(4, &serial_a())).await;
            reply(remote, 5, &identify_reply(4, &serial_b())).await;
        }
        (9, 1) => reply(remote, 9, &identify_reply(1, unit9_type)).await,
        (9, 2) => reply(remote, 9, &identify_reply(2, unit9_fw)).await,
        (9, 4) => {
            reply(remote, 9, &identify_reply(4, &serial_c())).await;
        }
        other => panic!("unexpected scripted probe {other:?}"),
    }
    tokio::task::yield_now().await;
    tokio::time::advance(IDENTIFY_QUIET).await;
    tokio::task::yield_now().await;
}

#[tokio::test(start_paused = true)]
async fn duplicate_serials_preserved_across_full_inventory() {
    let (pci, mut remote) = setup().await;
    let worker = tokio::spawn({
        let pci = pci.clone();
        async move { collect_full_inventory(&pci, options()).await }
    });

    // MMI phase: addresses 5 and 9 present.
    let request = line(&mut remote).await;
    assert!(request.starts_with(b"\\05FF00FAFF0003"));
    let code = request[request.len() - 2];
    remote.get_mut().write_all(&[code, b'.']).await.unwrap();
    remote.write_all(&mmi_block(0, 88, &[5, 9])).await.unwrap();
    remote.write_all(&mmi_block(88, 88, &[])).await.unwrap();
    remote.write_all(&mmi_block(176, 80, &[])).await.unwrap();

    // Six IDENTIFY probes, address order 5 then 9.
    for _ in 0..6 {
        serve_probe(&mut remote, b"DIMMER", b"1.0.0", b"RELAY", b"2.1.0").await;
    }

    let inventory = worker.await.unwrap().unwrap();
    assert!(inventory.coverage_complete);
    assert!(!inventory.partial, "{inventory:#?}");
    assert_eq!(inventory.units.len(), 2);

    let five = &inventory.units[0];
    let nine = &inventory.units[1];
    assert_eq!(five.address, 5);
    assert_eq!(nine.address, 9);

    // Duplicate identities at 5 are preserved verbatim: no collapse.
    assert_eq!(five.serial_replies.len(), 2);
    assert_eq!(five.serial_replies[0].raw, serial_a());
    assert_eq!(five.serial_replies[1].raw, serial_b());
    assert_ne!(five.serial_replies[0].serial, five.serial_replies[1].serial);
    assert!(five.serial_replies.iter().all(|r| r.parse_error.is_none()));

    assert_eq!(nine.serial_replies.len(), 1);
    assert_eq!(nine.serial_replies[0].raw, serial_c());
    assert!(nine.serial_replies[0].serial.is_some());

    assert_eq!(five.unit_type.as_deref(), Some("DIMMER"));
    assert_eq!(five.firmware.as_deref(), Some("1.0.0"));
    assert_eq!(nine.unit_type.as_deref(), Some("RELAY"));
    assert_eq!(nine.firmware.as_deref(), Some("2.1.0"));
    assert!(five.errors.is_empty());
    assert!(nine.errors.is_empty());

    // Decoded wire-adjacent spot checks (packed bytes 5..9).
    assert_eq!(
        five.serial_replies[0].serial.as_deref(),
        Some("101136.1558")
    );
    assert_eq!(
        five.serial_replies[1].serial.as_deref(),
        Some("101136.1559")
    );
    assert_eq!(
        nine.serial_replies[0].serial.as_deref(),
        Some("100966.1187")
    );
}

#[tokio::test(start_paused = true)]
async fn silent_address_records_unknown_identity_without_failing() {
    let (pci, mut remote) = setup().await;
    let worker = tokio::spawn({
        let pci = pci.clone();
        async move { collect_full_inventory(&pci, options()).await }
    });

    let request = line(&mut remote).await;
    assert!(request.starts_with(b"\\05FF00FAFF0003"));
    let code = request[request.len() - 2];
    remote.get_mut().write_all(&[code, b'.']).await.unwrap();
    remote.write_all(&mmi_block(0, 88, &[7])).await.unwrap();
    remote.write_all(&mmi_block(88, 88, &[])).await.unwrap();
    remote.write_all(&mmi_block(176, 80, &[])).await.unwrap();

    // Address 7 is MMI-present but answers nothing: confirm each probe,
    // emit no replies, let the bounded quiet window prove silence.
    for _ in 0..3 {
        let request = line(&mut remote).await;
        assert!(request.starts_with(b"\\46"));
        let code = request[request.len() - 2];
        remote.get_mut().write_all(&[code, b'.']).await.unwrap();
        tokio::time::advance(IDENTIFY_QUIET).await;
        tokio::task::yield_now().await;
    }

    let inventory = worker.await.unwrap().unwrap();
    assert!(inventory.coverage_complete);
    assert!(inventory.partial);
    assert_eq!(inventory.units.len(), 1);
    let unit = &inventory.units[0];
    assert_eq!(unit.address, 7);
    assert_eq!(unit.unit_type, None);
    assert_eq!(unit.firmware, None);
    assert!(unit.serial_replies.is_empty());
    assert!(!unit.errors.is_empty());
}

#[tokio::test(start_paused = true)]
async fn mmi_transport_failure_is_overall_error() {
    let (pci, mut remote) = setup().await;
    let worker = tokio::spawn({
        let pci = pci.clone();
        async move { collect_full_inventory(&pci, options()).await }
    });

    // PCI rejects the MMI: the whole collection fails, no partial result.
    let request = line(&mut remote).await;
    assert!(request.starts_with(b"\\05FF00FAFF0003"));
    let code = request[request.len() - 2];
    remote.get_mut().write_all(&[code, b'#']).await.unwrap();

    let error = worker.await.unwrap().unwrap_err();
    assert!(
        error.to_string().contains("rejected"),
        "unexpected error: {error}"
    );
}

/// Byte-identical IDENTIFY4 duplicates are two observations, not one:
/// the same twelve bytes twice must both be preserved in order.
#[tokio::test(start_paused = true)]
async fn byte_identical_duplicate_serials_both_preserved_in_order() {
    let (pci, mut remote) = setup().await;
    let worker = tokio::spawn({
        let pci = pci.clone();
        async move { collect_full_inventory(&pci, options()).await }
    });

    // MMI phase: address 5 present.
    let request = line(&mut remote).await;
    assert!(request.starts_with(b"\\05FF00FAFF0003"));
    let code = request[request.len() - 2];
    remote.get_mut().write_all(&[code, b'.']).await.unwrap();
    remote.write_all(&mmi_block(0, 88, &[5])).await.unwrap();
    remote.write_all(&mmi_block(88, 88, &[])).await.unwrap();
    remote.write_all(&mmi_block(176, 80, &[])).await.unwrap();

    // Three IDENTIFY probes; the IDENTIFY4 probe answers the same
    // twelve bytes twice.
    for _ in 0..3 {
        let request = line(&mut remote).await;
        assert!(
            request.starts_with(b"\\46"),
            "expected IDENTIFY request, got {:?}",
            String::from_utf8_lossy(&request)
        );
        let unit = u8::from_str_radix(&String::from_utf8_lossy(&request[3..5]), 16).unwrap();
        let attribute = u8::from_str_radix(&String::from_utf8_lossy(&request[9..11]), 16).unwrap();
        let code = request[request.len() - 2];
        remote.get_mut().write_all(&[code, b'.']).await.unwrap();
        match (unit, attribute) {
            (5, 1) => reply(&mut remote, 5, &identify_reply(1, b"DIMMER")).await,
            (5, 2) => reply(&mut remote, 5, &identify_reply(2, b"1.0.0")).await,
            (5, 4) => {
                reply(&mut remote, 5, &identify_reply(4, &serial_a())).await;
                reply(&mut remote, 5, &identify_reply(4, &serial_a())).await;
            }
            other => panic!("unexpected scripted probe {other:?}"),
        }
        tokio::task::yield_now().await;
        tokio::time::advance(IDENTIFY_QUIET).await;
        tokio::task::yield_now().await;
    }

    let inventory = worker.await.unwrap().unwrap();
    assert!(inventory.coverage_complete);
    assert!(!inventory.partial, "{inventory:#?}");
    assert_eq!(inventory.units.len(), 1);
    let five = &inventory.units[0];
    assert_eq!(five.address, 5);
    assert_eq!(five.serial_replies.len(), 2);
    assert_eq!(five.serial_replies[0].raw, serial_a());
    assert_eq!(five.serial_replies[1].raw, serial_a());
    assert_eq!(five.serial_replies[0].serial, five.serial_replies[1].serial);
    assert!(five.serial_replies[0].serial.is_some());
    assert!(five.serial_replies.iter().all(|r| r.parse_error.is_none()));
    assert!(five.errors.is_empty());
}

/// A mid-walk probe failure faults the shared programming lane, so later
/// addresses record needs-reconnect errors while the walk still
/// completes (bounded by the timeouts, never a hang) as a partial
/// inventory with earlier data intact.
#[tokio::test(start_paused = true)]
async fn mid_walk_probe_failure_faults_lane_and_walk_completes_partial() {
    // SHORT timeouts: just above the single 2s IDENTIFY quiet window
    // this walk needs, far below the 30s/120s of the other tests. The
    // paused clock makes this fast (no real sleeping) and flake-free.
    let short = InventoryOptions {
        per_address_timeout: Duration::from_secs(3),
        total_deadline: Duration::from_secs(20),
    };
    let (pci, mut remote) = setup().await;
    let worker = tokio::spawn({
        let pci = pci.clone();
        async move { collect_full_inventory(&pci, short).await }
    });

    // MMI phase: addresses 5, 6, and 7 present.
    let request = line(&mut remote).await;
    assert!(request.starts_with(b"\\05FF00FAFF0003"));
    let code = request[request.len() - 2];
    remote.get_mut().write_all(&[code, b'.']).await.unwrap();
    remote
        .write_all(&mmi_block(0, 88, &[5, 6, 7]))
        .await
        .unwrap();
    remote.write_all(&mmi_block(88, 88, &[])).await.unwrap();
    remote.write_all(&mmi_block(176, 80, &[])).await.unwrap();

    // Address 5 IDENTIFY1/2: reply-before-confirmation, so identify_first
    // returns without consuming a quiet window (no clock advance needed).
    for (attribute, payload) in [(1u8, b"DIMMER".as_slice()), (2u8, b"1.0.0".as_slice())] {
        let request = line(&mut remote).await;
        assert!(
            request.starts_with(b"\\46"),
            "expected IDENTIFY request, got {:?}",
            String::from_utf8_lossy(&request)
        );
        let unit = u8::from_str_radix(&String::from_utf8_lossy(&request[3..5]), 16).unwrap();
        let got = u8::from_str_radix(&String::from_utf8_lossy(&request[9..11]), 16).unwrap();
        assert_eq!((unit, got), (5, attribute));
        let code = request[request.len() - 2];
        reply(&mut remote, 5, &identify_reply(attribute, payload)).await;
        tokio::task::yield_now().await;
        remote.get_mut().write_all(&[code, b'.']).await.unwrap();
        tokio::task::yield_now().await;
    }
    // Address 5 IDENTIFY4: confirmation, two distinct replies, then the
    // single 2s quiet window this walk needs.
    {
        let request = line(&mut remote).await;
        assert!(
            request.starts_with(b"\\46"),
            "expected IDENTIFY request, got {:?}",
            String::from_utf8_lossy(&request)
        );
        let unit = u8::from_str_radix(&String::from_utf8_lossy(&request[3..5]), 16).unwrap();
        let attribute = u8::from_str_radix(&String::from_utf8_lossy(&request[9..11]), 16).unwrap();
        assert_eq!((unit, attribute), (5, 4));
        let code = request[request.len() - 2];
        remote.get_mut().write_all(&[code, b'.']).await.unwrap();
        reply(&mut remote, 5, &identify_reply(4, &serial_a())).await;
        reply(&mut remote, 5, &identify_reply(4, &serial_b())).await;
        tokio::task::yield_now().await;
        tokio::time::advance(IDENTIFY_QUIET).await;
        tokio::task::yield_now().await;
    }

    // Address 6 IDENTIFY1: the PCI rejects the probe, faulting the
    // shared programming lane until reconnect.
    {
        let request = line(&mut remote).await;
        assert!(
            request.starts_with(b"\\46"),
            "expected IDENTIFY request, got {:?}",
            String::from_utf8_lossy(&request)
        );
        let code = request[request.len() - 2];
        remote.get_mut().write_all(&[code, b'#']).await.unwrap();
        tokio::task::yield_now().await;
    }

    // No further remote traffic: the faulted lane fails the rest
    // locally. Awaiting the worker proves the walk completes (no hang).
    let inventory = worker.await.unwrap().unwrap();
    assert!(inventory.coverage_complete);
    assert!(inventory.partial);
    assert_eq!(
        inventory
            .units
            .iter()
            .map(|u| u.address)
            .collect::<Vec<_>>(),
        vec![5, 6, 7]
    );

    // Earlier address data intact.
    let five = &inventory.units[0];
    assert_eq!(five.unit_type.as_deref(), Some("DIMMER"));
    assert_eq!(five.firmware.as_deref(), Some("1.0.0"));
    assert_eq!(five.serial_replies.len(), 2);
    assert_eq!(five.serial_replies[0].raw, serial_a());
    assert_eq!(five.serial_replies[1].raw, serial_b());
    assert!(five.errors.is_empty());

    // The failed address records the rejection, then needs-reconnect.
    let six = &inventory.units[1];
    assert_eq!(six.address, 6);
    assert_eq!(six.serial_replies.len(), 0);
    assert_eq!(six.unit_type, None);
    assert_eq!(six.firmware, None);
    assert_eq!(six.errors.len(), 3);
    assert!(
        six.errors[0].contains("IDENTIFY1 failed") && six.errors[0].contains("rejected"),
        "unexpected first error: {}",
        six.errors[0]
    );
    assert!(
        six.errors[1].contains("needs reconnect"),
        "unexpected second error: {}",
        six.errors[1]
    );
    assert!(
        six.errors[2].contains("needs reconnect"),
        "unexpected third error: {}",
        six.errors[2]
    );

    // Later addresses are needs-reconnect errors, not silent success.
    let seven = &inventory.units[2];
    assert_eq!(seven.address, 7);
    assert_eq!(seven.unit_type, None);
    assert_eq!(seven.firmware, None);
    assert!(seven.serial_replies.is_empty());
    assert_eq!(seven.errors.len(), 3);
    assert!(
        seven.errors.iter().all(|e| e.contains("needs reconnect")),
        "unexpected errors: {:?}",
        seven.errors
    );
}

/// The addressed-block MMI route correlates like the broadcast route, so
/// the collector must accept it as coverage too.
#[tokio::test(start_paused = true)]
async fn addressed_mmi_blocks_count_as_coverage() {
    let (pci, mut remote) = setup().await;
    let worker = tokio::spawn({
        let pci = pci.clone();
        async move { collect_full_inventory(&pci, options()).await }
    });

    let request = line(&mut remote).await;
    let code = request[request.len() - 2];
    remote.get_mut().write_all(&[code, b'.']).await.unwrap();
    for (start, count, present) in [
        (0u8, 88usize, vec![5, 9]),
        (88, 88, vec![]),
        (176, 80, vec![]),
    ] {
        let mut states = vec![0; count];
        for address in present {
            states[address - usize::from(start)] = 1;
        }
        let wire = Packet::PointToPoint {
            meta: Meta {
                checksum: true,
                priority_class: 2,
                source_address: Some(16),
                confirmation: None,
            },
            unit_address: 16,
            bridged: false,
            hops: vec![],
            cals: vec![Cal::ExtendedStatus {
                externally_initiated: false,
                child_application: 0xff,
                block_start: start,
                report: StatusReport::Binary(states),
            }],
        }
        .encode_packet()
        .unwrap();
        let mut line = wire;
        line.extend_from_slice(b"\r\n");
        remote.write_all(&line).await.unwrap();
    }

    for _ in 0..6 {
        serve_probe(&mut remote, b"DIMMER", b"1.0.0", b"RELAY", b"2.1.0").await;
    }

    let inventory = worker.await.unwrap().unwrap();
    assert!(inventory.coverage_complete);
    assert!(!inventory.partial);
    assert_eq!(
        inventory
            .units
            .iter()
            .map(|u| u.address)
            .collect::<Vec<_>>(),
        vec![5, 9]
    );
}
