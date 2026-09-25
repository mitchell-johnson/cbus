use super::*;
use tokio::io::{AsyncBufReadExt, AsyncReadExt, AsyncWriteExt, BufReader};

fn fixture() -> String {
    include_str!("../../../testdata/fixtures/project.xml").replace("</Network>",
        "<Unit><Address>5</Address><TagName>Fixture eDLT</TagName><UnitType>KEYGL5</UnitType><FirmwareVersion>5.5.00</FirmwareVersion><PP Name=\"StaticTextString0\" Value=\"Fixture\"/></Unit></Network>")
}

fn state_path() -> PathBuf {
    static ID: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
    std::env::temp_dir().join(format!(
        "cmqttd-service-{}-{}.json",
        std::process::id(),
        ID.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
    ))
}

fn pci() -> (Arc<PciClient>, tokio::io::DuplexStream) {
    let (client, remote) = tokio::io::duplex(8192);
    let (rd, wr) = tokio::io::split(client);
    let (tx, _) = tokio::sync::mpsc::unbounded_channel();
    (PciClient::new(Box::new(rd), Box::new(wr), tx), remote)
}

#[tokio::test]
async fn database_survives_restart_but_live_state_and_sessions_do_not() {
    let path = state_path();
    let (pci, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci.clone(), None).unwrap();
    let mut client = ClientState::default();
    assert_eq!(
        service
            .handle(
                &mut client,
                "[1] DBSETSAFE //HARNESS/254/p/5/TagName Changed"
            )
            .await
            .status,
        200
    );
    service
        .observe(&CBusEvent::LightingOn {
            source: Some(4),
            app: 56,
            group: 1,
        })
        .await;
    assert!(service
        .handle(&mut client, "[2] GET //HARNESS/254/56/1 level")
        .await
        .final_text
        .ends_with("level=255"));
    assert_eq!(
        service
            .handle(&mut client, "[2a] SCENE RECORD house evening")
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut client, "[3] PP LOCK L //HARNESS/254")
            .await
            .status,
        200
    );
    let restarted = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let model = restarted.model.lock().await;
    assert_eq!(
        model.projects["HARNESS"].networks[&254].units[&5].fields["TagName"],
        "Changed"
    );
    assert!(model.projects["HARNESS"].networks[&254].levels.is_empty());
    assert!(model.projects["HARNESS"].networks[&254].physical.is_empty());
    assert!(model.locks.is_empty());
    assert_eq!(
        model.scene_snapshots["house/evening"],
        vec![("//HARNESS/254/56/1".to_string(), 255)]
    );
    drop(model);
    assert_eq!(
        restarted
            .handle(&mut client, "[4] GET //HARNESS/254/56/1 level")
            .await
            .status,
        408
    );
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn programming_ownership_and_unimplemented_hardware_are_enforced() {
    let path = state_path();
    let (pci, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let mut first = ClientState::default();
    let mut second = ClientState::default();
    assert_eq!(
        service
            .handle(&mut first, "[1] PP LOCK L //HARNESS/254")
            .await
            .status,
        200
    );
    assert_eq!(
        service.handle(&mut second, "[2] PP START S L").await.status,
        420
    );
    assert_eq!(
        service.handle(&mut first, "[3] PP START S L").await.status,
        200
    );
    assert_eq!(
        service
            .handle(&mut second, "[4] PP SET S Field value")
            .await
            .status,
        420
    );
    assert_eq!(
        service
            .handle(&mut first, "[5] PP SAVE S //HARNESS/254/p/5")
            .await
            .status,
        408
    );
    for command in [
        "AIRCON REFRESH //HARNESS/254/172 1",
        "PP WRITE_PATCH S anything",
    ] {
        assert_eq!(
            service
                .handle(&mut first, &format!("[5] {command}"))
                .await
                .status,
            502,
            "{command}"
        );
    }
    assert_eq!(
        service
            .handle(&mut first, "[5] SET //HARNESS/254/p/5 Address 5")
            .await
            .status,
        400
    );
    assert_eq!(
        service
            .handle(&mut first, "[6] PP LOAD S /db//HARNESS/254/p/5")
            .await
            .status,
        200
    );
    std::fs::remove_file(path).unwrap();
}

#[tokio::test(start_paused = true)]
async fn physical_readdress_is_guarded_acknowledged_and_keeps_database_address() {
    async fn pci_line<R: tokio::io::AsyncBufRead + Unpin>(reader: &mut R) -> Vec<u8> {
        let mut line = Vec::new();
        reader.read_until(b'\r', &mut line).await.unwrap();
        line
    }
    async fn pci_reply<W: tokio::io::AsyncWrite + Unpin>(writer: &mut W, source: u8, cal: &[u8]) {
        let mut bytes = vec![0x86, source, 0x10, 0x00];
        bytes.extend_from_slice(cal);
        let sum = bytes.iter().fold(0u8, |sum, byte| sum.wrapping_add(*byte));
        bytes.push(0u8.wrapping_sub(sum));
        let mut wire = hex::encode_upper(bytes).into_bytes();
        wire.extend_from_slice(b"\r\n");
        writer.write_all(&wire).await.unwrap();
    }

    let path = state_path();
    let (pci, remote) = pci();
    let (remote_read, mut remote_write) = tokio::io::split(remote);
    let mut remote_read = BufReader::new(remote_read);
    let reset = tokio::spawn({
        let pci = pci.clone();
        async move { pci.pci_reset().await }
    });
    for _ in 0..8 {
        pci_line(&mut remote_read).await;
    }
    reset.await.unwrap().unwrap();

    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    {
        let mut model = service.model.lock().await;
        let network = model
            .projects
            .get_mut("HARNESS")
            .unwrap()
            .networks
            .get_mut(&254)
            .unwrap();
        network
            .physical
            .insert(5, network.units.get(&5).unwrap().clone());
    }
    let moving = tokio::spawn({
        let service = service.clone();
        async move {
            let mut client = ClientState::default();
            service
                .handle(&mut client, "[1] SET //HARNESS/254/p/5 Address 6")
                .await
        }
    });

    let source_check = pci_line(&mut remote_read).await;
    assert!(source_check.starts_with(b"\\4605002104"));
    let source_code = source_check[source_check.len() - 2];
    remote_write.write_all(&[source_code, b'.']).await.unwrap();
    pci_reply(
        &mut remote_write,
        5,
        &[
            0x8d, 4, 0x38, 0xff, 0xff, 0xff, 0xff, 0x18, 0xb1, 0x06, 0x16, 0xa2, 0, 5,
        ],
    )
    .await;
    tokio::time::advance(Duration::from_secs(2)).await;
    tokio::task::yield_now().await;

    let destination_check = pci_line(&mut remote_read).await;
    assert!(destination_check.starts_with(b"\\4606002104"));
    let destination_code = destination_check[destination_check.len() - 2];
    remote_write
        .write_all(&[destination_code, b'.'])
        .await
        .unwrap();
    tokio::time::advance(Duration::from_secs(2)).await;
    tokio::task::yield_now().await;

    let unlock = pci_line(&mut remote_read).await;
    assert!(unlock.starts_with(b"\\4605001120"));
    let unlock_code = unlock[unlock.len() - 2];
    pci_reply(&mut remote_write, 5, &[0x82, 0x20, 0x5a]).await;
    remote_write.write_all(&[unlock_code, b'.']).await.unwrap();
    let store = pci_line(&mut remote_read).await;
    assert!(store.starts_with(b"\\460500A3204E065A"));
    let store_code = store[store.len() - 2];
    pci_reply(&mut remote_write, 6, &[0x32, 0x20, 0x4e]).await;
    remote_write.write_all(&[store_code, b'.']).await.unwrap();

    let response = moving.await.unwrap();
    assert_eq!(response.status, 200);
    assert_eq!(response.final_text, "200 OK: //HARNESS/254/p/6");
    let model = service.model.lock().await;
    let network = &model.projects["HARNESS"].networks[&254];
    assert!(network.units.contains_key(&5));
    assert!(!network.units.contains_key(&6));
    assert!(!network.physical.contains_key(&5));
    assert_eq!(network.physical[&6].address, 6);
    drop(model);
    std::fs::remove_file(path).unwrap();
}

#[test]
fn physical_identity_fields_decode_without_inventing_unknown_serials() {
    assert_eq!(identity_text(b"KEYGL5  ", "type").unwrap(), "KEYGL5");
    assert_eq!(identity_text(b"5.5.00  ", "firmware").unwrap(), "5.5.00");
    assert_eq!(
        serial_number(&[0x38, 0xff, 0xff, 0xff, 0xff, 0x18, 0xb1, 0x06, 0x16, 0xa2, 0x00, 0x05,])
            .unwrap()
            .as_deref(),
        Some("101136.1558")
    );
    let mut unknown = [0xff; 12];
    unknown[5..9].fill(0);
    assert_eq!(serial_number(&unknown).unwrap(), None);
    assert!(serial_number(&unknown[..11]).is_err());
    assert!(identity_text(b"        ", "type").is_err());
}

#[tokio::test]
async fn failed_persistence_rolls_back_database_changes() {
    let path = state_path();
    let (pci, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    std::fs::remove_file(&path).unwrap();
    std::fs::create_dir(&path).unwrap();
    let response = service
        .handle(
            &mut ClientState::default(),
            "[1] DBSETSAFE //HARNESS/254/p/5/TagName Changed",
        )
        .await;
    assert_eq!(response.status, 500);
    assert_eq!(
        service.model.lock().await.projects["HARNESS"].networks[&254].units[&5].fields["TagName"],
        "Fixture eDLT"
    );
    service
        .observe(&CBusEvent::LightingOn {
            source: Some(4),
            app: 56,
            group: 1,
        })
        .await;
    assert_eq!(
        service
            .handle(
                &mut ClientState::default(),
                "[2] SCENE RECORD house evening"
            )
            .await
            .status,
        500
    );
    assert!(service.model.lock().await.scene_snapshots.is_empty());
    std::fs::remove_dir(path).unwrap();
}

#[tokio::test]
async fn corrupt_database_is_not_overwritten() {
    let path = state_path();
    std::fs::write(&path, b"broken").unwrap();
    let (pci, _remote) = pci();
    assert!(Service::new(&fixture(), None, path.clone(), pci, None).is_err());
    assert_eq!(std::fs::read(&path).unwrap(), b"broken");
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn reconnect_opens_network_and_discards_observed_levels() {
    let path = state_path();
    let (old, _old_remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), old, None).unwrap();
    service
        .observe(&CBusEvent::LightingOn {
            source: Some(4),
            app: 56,
            group: 1,
        })
        .await;
    let (new, _new_remote) = pci();
    service.set_pci(new).await;
    let model = service.model.lock().await;
    let net = &model.projects["HARNESS"].networks[&254];
    assert_eq!(net.state, NetworkState::Open);
    assert!(net.levels.is_empty());
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn observed_trigger_enable_and_clock_state_is_live_and_cleared_on_disconnect() {
    let path = state_path();
    let (pci, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    service
        .observe(&CBusEvent::TriggerEvent {
            source: Some(7),
            group: 4,
            selector: 88,
        })
        .await;
    service
        .observe(&CBusEvent::EnableSet {
            source: Some(8),
            variable: 5,
            value: 66,
        })
        .await;
    service
        .observe(&CBusEvent::ClockDate {
            source: Some(9),
            year: 2026,
            month: 9,
            day: 24,
        })
        .await;
    service
        .observe(&CBusEvent::TemperatureBroadcast {
            source: Some(10),
            group: 3,
            temperature: 21.25,
        })
        .await;
    assert_eq!(
        service.model.lock().await.application_state["TEMPERATURE BROADCAST"],
        "//HARNESS/254/25/3 21.25"
    );
    let mut client = ClientState::default();
    let trigger = service
        .handle(&mut client, "[1] GET //HARNESS/254/202/4 *")
        .await;
    assert_eq!(trigger.status, 300);
    assert!(trigger
        .lines
        .iter()
        .any(|line| line.contains("EventLevel=5")));
    assert!(trigger.final_text.contains("State=ok"));
    assert_eq!(
        service
            .handle(&mut client, "[2] GET //HARNESS/254/202/4 Level")
            .await
            .status,
        402
    );
    assert!(service
        .handle(&mut client, "[3] GET //HARNESS/254/202 Groups")
        .await
        .final_text
        .ends_with("Groups=4"));
    assert!(service
        .handle(&mut client, "[4] GET //HARNESS/254/203/5 Level")
        .await
        .final_text
        .ends_with("Level=66"));
    assert!(service
        .handle(&mut client, "[5] CLOCK DATE 254/223")
        .await
        .final_text
        .ends_with("Date set to: 2026-09-24"));
    service.observe(&CBusEvent::ConnectionLost).await;
    assert!(!service
        .model
        .lock()
        .await
        .application_state
        .contains_key("TEMPERATURE BROADCAST"));
    assert_eq!(
        service
            .handle(&mut client, "[6] GET //HARNESS/254/203/5 Level")
            .await
            .status,
        408
    );
    assert!(service
        .handle(&mut client, "[7] CLOCK DATE 254/223")
        .await
        .final_text
        .ends_with("Date set to: 1970-01-01"));
    std::fs::remove_file(path).unwrap();
}

#[test]
fn temperature_syntax_is_bounded_and_accepts_symbolic_application_addresses() {
    assert_eq!(parse_application("$19"), Some(25));
    assert_eq!(parse_application("25"), Some(25));
    assert_eq!(parse_application("$100"), None);
    assert_eq!(parse_temperature("21.3"), Some(21.3));
    assert_eq!(parse_temperature("21"), Some(21.0));
    assert_eq!(parse_temperature("21.25"), None);
    assert_eq!(parse_temperature("-1"), None);
    assert_eq!(parse_temperature("63.8"), None);
    assert_eq!(format_temperature(21.25), "21.25");
    assert_eq!(format_temperature(20.0), "20");
}

#[tokio::test]
async fn fragmented_command_survives_event_delivery_and_disconnect_releases_locks() {
    let path = state_path();
    let (pci, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let server = tokio::spawn(service.clone().serve(listener));
    let stream = TcpStream::connect(addr).await.unwrap();
    let (rd, mut wr) = stream.into_split();
    let mut rd = BufReader::new(rd);
    let mut line = String::new();
    rd.read_line(&mut line).await.unwrap();
    assert!(line.starts_with("201 "));
    wr.write_all(b"[1] EVENT ON\r\n").await.unwrap();
    line.clear();
    rd.read_line(&mut line).await.unwrap();
    wr.write_all(b"[2] PP LOCK L ").await.unwrap();
    service
        .observe(&CBusEvent::LightingOn {
            source: Some(7),
            app: 56,
            group: 1,
        })
        .await;
    line.clear();
    rd.read_line(&mut line).await.unwrap();
    assert!(line.starts_with("#e#"));
    wr.write_all(b"//HARNESS/254\r\n").await.unwrap();
    loop {
        line.clear();
        rd.read_line(&mut line).await.unwrap();
        if line.starts_with("[2]") {
            break;
        }
    }
    assert!(line.contains("200 OK"));
    drop(wr);
    drop(rd);
    tokio::time::timeout(Duration::from_secs(2), async {
        loop {
            if service.model.lock().await.locks.is_empty() {
                break;
            }
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
    server.abort();
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn line_bound_is_enforced_before_newline() {
    let (mut tx, rx) = tokio::io::duplex(8192);
    let mut rd = BufReader::new(rx);
    let writer = tokio::spawn(async move {
        let _ = tx.write_all(&vec![b'x'; MAX_LINE + 1]).await;
        let mut b = [0];
        let _ = tx.read(&mut b).await;
    });
    let response = bounded_line(&mut rd, &mut Vec::new()).await;
    assert!(response.unwrap_err().to_string().contains("1 MiB"));
    writer.abort();
}

/// Issue #12 Phase 1: capabilities must advertise observation while honestly
/// reporting that no device-cache readback exists and no full compatibility
/// is claimed.
#[tokio::test]
async fn capabilities_report_observation_without_device_readback() {
    let path = state_path();
    let (pci, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let mut client = ClientState::default();
    let response = service.handle(&mut client, "[1] CMQTT CAPABILITIES").await;
    assert_eq!(response.status, 200);
    assert_eq!(response.lines.len(), 1);
    let document: serde_json::Value = serde_json::from_str(&response.lines[0]).unwrap();
    assert_eq!(document["full_cgate_compatibility"], false);
    assert_eq!(document["dynamic_labels"], true);
    assert_eq!(document["dynamic_label_observation"], true);
    assert_eq!(document["dynamic_label_device_readback"], false);
    std::fs::remove_file(path).unwrap();
}

/// Issue #12 Phase 1: an empty observation cache reports observed-only
/// provenance — never a complete device readback.
#[tokio::test]
async fn labels_empty_document_pins_observed_only_provenance() {
    let path = state_path();
    let (pci, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let mut client = ClientState::default();
    let response = service
        .handle(&mut client, "[1] CMQTT LABELS //HARNESS/254")
        .await;
    assert_eq!(response.status, 200);
    assert_eq!(response.lines.len(), 1);
    let document: serde_json::Value = serde_json::from_str(&response.lines[0]).unwrap();
    assert_eq!(document["format"], "cmqttd-observed-dynamic-labels-v1");
    assert_eq!(document["source"], "observed-sal-traffic");
    assert_eq!(document["complete"], false);
    assert_eq!(document["device_readback"], false);
    assert_eq!(document["reset_on_reconnect"], true);
    assert_eq!(document["capacity"], MAX_LABEL_OBSERVATIONS);
    assert_eq!(document["observations"].as_array().unwrap().len(), 0);
    assert_eq!(document["address"], "//HARNESS/254");
    assert_eq!(document["project"], "HARNESS");
    assert_eq!(document["network"], 254);
    // Unit-scoped address on the configured network is accepted too.
    let unit = service
        .handle(&mut client, "[2] CMQTT LABELS //HARNESS/254/p/5")
        .await;
    assert_eq!(unit.status, 200);
    // Bare canonical network forms accepted; trailing-slash forms rejected.
    for address in ["254", "HARNESS/254"] {
        let response = service
            .handle(&mut client, &format!("[3] CMQTT LABELS {address}"))
            .await;
        assert_eq!(response.status, 200, "{address}");
    }
    for address in ["//HARNESS/254/", "//HARNESS/254/p/5/"] {
        let response = service
            .handle(&mut client, &format!("[4] CMQTT LABELS {address}"))
            .await;
        assert_eq!(response.status, 400, "{address}");
    }
    std::fs::remove_file(path).unwrap();
}

/// Issue #12 Phase 1: label observations are scoped to the configured
/// network; foreign projects or networks are rejected, never invented.
#[tokio::test]
async fn labels_reject_foreign_network() {
    let path = state_path();
    let (pci, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let mut client = ClientState::default();
    for address in [
        "//OTHER/254",
        "//HARNESS/253",
        "//OTHER/254/p/5",
        "//HARNESS/253/p/5",
        "//HARNESS/254/p/5/extra",
    ] {
        let response = service
            .handle(&mut client, &format!("[1] CMQTT LABELS {address}"))
            .await;
        assert_eq!(response.status, 400, "{address}");
    }
    std::fs::remove_file(path).unwrap();
}

/// Issue #12 Phase 1: the bounded observation ring evicts the oldest entry
/// at capacity while sequence numbers stay strictly monotonic.
#[tokio::test]
async fn observed_label_ring_evicts_oldest_at_capacity() {
    let path = state_path();
    let (pci, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let payload = vec![0xa4, 0x01, 0x00, 0x00, 0x41];
    for _ in 0..MAX_LABEL_OBSERVATIONS + 3 {
        service
            .record_label("received", Some(5), 56, &payload)
            .await;
    }
    let labels = service.observed_labels.lock().await;
    assert_eq!(labels.observations.len(), MAX_LABEL_OBSERVATIONS);
    assert_eq!(labels.next_sequence, (MAX_LABEL_OBSERVATIONS + 3) as u64);
    let first = labels.observations.front().unwrap();
    let last = labels.observations.back().unwrap();
    assert_eq!(first.sequence, 3);
    assert_eq!(last.sequence, (MAX_LABEL_OBSERVATIONS + 3) as u64 - 1);
    assert_eq!(first.payload_hex, "a401000041");
    let mut previous = None;
    for observation in labels.observations.iter() {
        if let Some(previous) = previous {
            assert!(observation.sequence > previous);
        }
        previous = Some(observation.sequence);
    }
    drop(labels);
    // The served wire document reflects the same eviction window.
    let mut client = ClientState::default();
    let response = service
        .handle(&mut client, "[1] CMQTT LABELS //HARNESS/254")
        .await;
    assert_eq!(response.status, 200);
    let document: serde_json::Value = serde_json::from_str(&response.lines[0]).unwrap();
    let observations = document["observations"].as_array().unwrap();
    assert_eq!(observations.len(), MAX_LABEL_OBSERVATIONS);
    assert_eq!(observations[0]["sequence"], 3);
    assert_eq!(
        observations[MAX_LABEL_OBSERVATIONS - 1]["sequence"],
        (MAX_LABEL_OBSERVATIONS + 3) as u64 - 1
    );
    std::fs::remove_file(path).unwrap();
}

/// Issue #12 Phase 1: genuine bus label traffic surfaces as `received`
/// observations and a dropped connection discards them (they were never a
/// persistent device-cache readback).
#[tokio::test]
async fn observed_dynamic_label_surfaces_received_and_clears_on_disconnect() {
    let path = state_path();
    let (pci, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    service
        .observe(&CBusEvent::DynamicLabel {
            source: Some(5),
            application: 56,
            payload: vec![0xa4, 0x01, 0x00, 0x00, 0x41],
        })
        .await;
    let mut client = ClientState::default();
    let response = service
        .handle(&mut client, "[1] CMQTT LABELS //HARNESS/254")
        .await;
    assert_eq!(response.status, 200);
    let document: serde_json::Value = serde_json::from_str(&response.lines[0]).unwrap();
    let observations = document["observations"].as_array().unwrap();
    assert_eq!(observations.len(), 1);
    assert_eq!(observations[0]["direction"], "received");
    assert_eq!(observations[0]["source_unit"], 5);
    assert_eq!(observations[0]["application"], 56);
    assert_eq!(observations[0]["payload_hex"], "a401000041");
    assert_eq!(document["complete"], false);
    assert_eq!(document["device_readback"], false);
    service.observe(&CBusEvent::ConnectionLost).await;
    let cleared = service
        .handle(&mut client, "[2] CMQTT LABELS //HARNESS/254")
        .await;
    let cleared: serde_json::Value = serde_json::from_str(&cleared.lines[0]).unwrap();
    assert_eq!(cleared["observations"].as_array().unwrap().len(), 0);
    std::fs::remove_file(path).unwrap();
}

/// Issue #12 Phase 1: the send-confirmed record path serves rows matching
/// the exact key contract the Python `decode_observed_labels` requires
/// (`sequence/direction/source_unit/application/payload_hex` — no extras).
#[tokio::test]
async fn sent_confirmed_observation_row_matches_decoder_contract() {
    let path = state_path();
    let (pci, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    service
        .record_label("sent-confirmed", None, 56, &[0xa4, 0x01, 0x00, 0x00, 0x41])
        .await;
    let mut client = ClientState::default();
    let response = service
        .handle(&mut client, "[1] CMQTT LABELS //HARNESS/254")
        .await;
    assert_eq!(response.status, 200);
    let document: serde_json::Value = serde_json::from_str(&response.lines[0]).unwrap();
    let observations = document["observations"].as_array().unwrap();
    assert_eq!(observations.len(), 1);
    let row = observations[0].as_object().unwrap();
    let mut keys: Vec<&str> = row.keys().map(String::as_str).collect();
    keys.sort_unstable();
    assert_eq!(
        keys,
        [
            "application",
            "direction",
            "payload_hex",
            "sequence",
            "source_unit"
        ]
    );
    assert_eq!(row["sequence"], 0);
    assert_eq!(row["direction"], "sent-confirmed");
    assert!(row["source_unit"].is_null());
    assert_eq!(row["application"], 56);
    assert_eq!(row["payload_hex"], "a401000041");
    std::fs::remove_file(path).unwrap();
}

/// Issue #10 Phase 5 entry: UNRAVEL has no physical backend yet and must
/// fail closed with 502 — never simulated success. Unknown methods stay 402.
#[tokio::test]
async fn do_unravel_fails_closed_until_physical_backend_exists() {
    let path = state_path();
    let (pci, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let mut client = ClientState::default();
    let response = service
        .handle(&mut client, "[1] DO //HARNESS/254 UNRAVEL")
        .await;
    assert_eq!(response.status, 502);
    assert!(
        response.final_text.contains("physical backend"),
        "{}",
        response.final_text
    );
    let unknown = service
        .handle(&mut client, "[2] DO //HARNESS/254/56/1 FROBNICATE")
        .await;
    assert_eq!(unknown.status, 402);
    let short = service.handle(&mut client, "[3] DO").await;
    assert_eq!(short.status, 400);
    let missing_method = service
        .handle(&mut client, "[4] DO //HARNESS/254/56/1")
        .await;
    assert_eq!(missing_method.status, 400);
    std::fs::remove_file(path).unwrap();
}

/// Issue #10 Phase 5 entry: native NET UNRAVEL[UNIT] likewise has no
/// physical backend yet and fails closed with the generic 502 — never a
/// simulator-only success standing in for physical I/O.
#[tokio::test]
async fn net_unravel_fails_closed_until_physical_backend_exists() {
    let path = state_path();
    let (pci, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let mut client = ClientState::default();
    for line in [
        "[1] NET UNRAVEL //HARNESS/254",
        "[2] NET UNRAVELUNIT //HARNESS/254 20",
        // The fail-closed gate precedes argument validation: even a bare
        // verb reports 502, never a mock 400.
        "[3] NET UNRAVEL",
    ] {
        let response = service.handle(&mut client, line).await;
        assert_eq!(response.status, 502, "{line}");
        assert_eq!(
            response.final_text, "502 Command requires a physical backend that is not implemented",
            "{line}"
        );
    }
    std::fs::remove_file(path).unwrap();
}

/// Native C-Gate declares CHECK_UNRAVEL obsolete and returns 400 without
/// running it; the service answers likewise instead of the generic 502.
#[tokio::test]
async fn net_check_unravel_is_obsolete_400() {
    let path = state_path();
    let (pci, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let mut client = ClientState::default();
    for line in [
        "[1] NET CHECK_UNRAVEL //HARNESS/254",
        "[2] NET CHECK_UNRAVEL",
    ] {
        let response = service.handle(&mut client, line).await;
        assert_eq!(response.status, 400, "{line}");
        assert_eq!(
            response.final_text, "400 NET CHECK_UNRAVEL is obsolete",
            "{line}"
        );
    }
    std::fs::remove_file(path).unwrap();
}

/// P2 partial-write evidence: when a physical PP SAVE fails after a
/// confirmed range write, the service must never report success, must
/// report how many writes were confirmed, and must retain dirty flags.
#[tokio::test]
async fn physical_pp_save_reports_partial_write_evidence_and_retains_dirty() {
    async fn pci_line<R: tokio::io::AsyncBufRead + Unpin>(reader: &mut R) -> Vec<u8> {
        let mut line = Vec::new();
        reader.read_until(b'\r', &mut line).await.unwrap();
        line
    }
    async fn pci_reply<W: tokio::io::AsyncWrite + Unpin>(writer: &mut W, source: u8, cal: &[u8]) {
        let mut bytes = vec![0x86, source, 0x10, 0x00];
        bytes.extend_from_slice(cal);
        let sum = bytes.iter().fold(0u8, |sum, byte| sum.wrapping_add(*byte));
        bytes.push(0u8.wrapping_sub(sum));
        let mut wire = hex::encode_upper(bytes).into_bytes();
        wire.extend_from_slice(b"\r\n");
        writer.write_all(&wire).await.unwrap();
    }

    let path = state_path();
    let spec_dir = std::env::temp_dir().join(format!(
        "cmqttd-pp-partial-{}-{}.d",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    std::fs::create_dir_all(&spec_dir).unwrap();
    std::fs::write(
        spec_dir.join("TESTUNIT.xml"),
        r#"<UnitSpecification><Parameters>
        <Param><Name>Alpha</Name><Type>int</Type><Address>$20</Address><ArraySize>2</ArraySize><ProgramMethod>direct</ProgramMethod><Protection>none</Protection></Param>
        <Param><Name>Beta</Name><Type>int</Type><Address>$30</Address><ArraySize>2</ArraySize><ProgramMethod>direct</ProgramMethod><Protection>none</Protection></Param>
        </Parameters></UnitSpecification>"#,
    )
    .unwrap();

    let (pci, remote) = pci();
    let (remote_read, mut remote_write) = tokio::io::split(remote);
    let mut remote_read = BufReader::new(remote_read);
    let reset = tokio::spawn({
        let pci = pci.clone();
        async move { pci.pci_reset().await }
    });
    for _ in 0..8 {
        pci_line(&mut remote_read).await;
    }
    reset.await.unwrap().unwrap();

    let service =
        Service::new(&fixture(), None, path.clone(), pci, Some(spec_dir.clone())).unwrap();
    let mut client = ClientState::default();
    for line in [
        "[1] PP LOCK L //HARNESS/254",
        "[2] PP START S L",
        "[3] PP NEW S TESTUNIT 1.2.03",
        "[4] PP SET S Alpha 0x56 0x78",
        "[5] PP SET S Beta 0xAB 0xCD",
    ] {
        let response = service.handle(&mut client, line).await;
        assert_eq!(response.status, 200, "{line}: {}", response.final_text);
    }

    let checker = service.clone();
    let saving = tokio::spawn(async move {
        service
            .handle(&mut client, "[9] PP SAVE S //HARNESS/254/p/5")
            .await
    });

    let request = pci_line(&mut remote_read).await;
    assert!(
        request.windows(4).any(|window| window == b"2101"),
        "{request:?}"
    );
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    pci_reply(
        &mut remote_write,
        5,
        &[0x89, 0x01, b'T', b'E', b'S', b'T', b'U', b'N', b'I', b'T'],
    )
    .await;
    let request = pci_line(&mut remote_read).await;
    assert!(
        request.windows(4).any(|window| window == b"2102"),
        "{request:?}"
    );
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    pci_reply(
        &mut remote_write,
        5,
        &[0x87, 0x02, b'1', b'.', b'2', b'.', b'0', b'3'],
    )
    .await;

    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\4605001A2002"), "{request:?}");
    pci_reply(&mut remote_write, 5, &[0x83, 0x20, 0x00, 0x00]).await;
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\4605001A3002"), "{request:?}");
    pci_reply(&mut remote_write, 5, &[0x83, 0x30, 0x00, 0x00]).await;

    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\460500A42000"), "{request:?}");
    pci_reply(&mut remote_write, 5, &[0x32, 0x20, 0x00]).await;
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\4605001A2002"), "{request:?}");
    pci_reply(&mut remote_write, 5, &[0x83, 0x20, 0x56, 0x78]).await;

    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\460500A43000"), "{request:?}");
    pci_reply(&mut remote_write, 5, &[0x32, 0x30, 0x01]).await;

    let response = saving.await.unwrap();
    assert_eq!(
        response.status, 502,
        "partial PP SAVE must never report success: {}",
        response.final_text
    );
    assert!(
        response
            .final_text
            .starts_with("502 Physical PP save failed after 1 confirmed write(s):"),
        "reason must report partial-write evidence: {}",
        response.final_text
    );
    assert!(
        response.final_text.contains("unit rejected"),
        "underlying diagnostic must be preserved: {}",
        response.final_text
    );

    let model = checker.model.lock().await;
    let session = model
        .sessions
        .get("S")
        .expect("session survives failed save");
    assert!(session.dirty.contains("Alpha"), "dirty={:?}", session.dirty);
    assert!(session.dirty.contains("Beta"), "dirty={:?}", session.dirty);
    drop(model);

    std::fs::remove_file(&path).unwrap();
    std::fs::remove_file(spec_dir.join("TESTUNIT.xml")).unwrap();
    std::fs::remove_dir(&spec_dir).unwrap();
}

/// P2 partial-write evidence for the NVM-commit path: when every STORE
/// write is confirmed but Save-to-NVM fails, the 502 reason must still
/// report how many writes were confirmed, and dirty flags are retained.
/// The EXECUTE/POLL failure pattern mirrors
/// `definitive_save_to_nvm_failures_do_not_fault_programming_lane` in
/// `cbus-transport`: a definitive status reply closes the transaction
/// without faulting the programming lane.
#[tokio::test]
async fn physical_pp_save_nvm_failure_reports_confirmed_writes_and_retains_dirty() {
    async fn pci_line<R: tokio::io::AsyncBufRead + Unpin>(reader: &mut R) -> Vec<u8> {
        let mut line = Vec::new();
        reader.read_until(b'\r', &mut line).await.unwrap();
        line
    }
    async fn pci_reply<W: tokio::io::AsyncWrite + Unpin>(writer: &mut W, source: u8, cal: &[u8]) {
        let mut bytes = vec![0x86, source, 0x10, 0x00];
        bytes.extend_from_slice(cal);
        let sum = bytes.iter().fold(0u8, |sum, byte| sum.wrapping_add(*byte));
        bytes.push(0u8.wrapping_sub(sum));
        let mut wire = hex::encode_upper(bytes).into_bytes();
        wire.extend_from_slice(b"\r\n");
        writer.write_all(&wire).await.unwrap();
    }

    let path = state_path();
    let spec_dir = std::env::temp_dir().join(format!(
        "cmqttd-pp-nvm-{}-{}.d",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    std::fs::create_dir_all(&spec_dir).unwrap();
    // Gamma is never staged, so it needs no PCI scripting; its NCC program
    // method only switches the service onto the Save-to-NVM commit path.
    std::fs::write(
        spec_dir.join("TESTUNIT.xml"),
        r#"<UnitSpecification><Parameters>
        <Param><Name>Alpha</Name><Type>int</Type><Address>$20</Address><ArraySize>2</ArraySize><ProgramMethod>direct</ProgramMethod><Protection>none</Protection></Param>
        <Param><Name>Beta</Name><Type>int</Type><Address>$30</Address><ArraySize>2</ArraySize><ProgramMethod>direct</ProgramMethod><Protection>none</Protection></Param>
        <Param><Name>Gamma</Name><Type>int</Type><Address>$40</Address><ArraySize>2</ArraySize><ProgramMethod>ncc</ProgramMethod><Protection>none</Protection></Param>
        </Parameters></UnitSpecification>"#,
    )
    .unwrap();

    let (pci, remote) = pci();
    let (remote_read, mut remote_write) = tokio::io::split(remote);
    let mut remote_read = BufReader::new(remote_read);
    let reset = tokio::spawn({
        let pci = pci.clone();
        async move { pci.pci_reset().await }
    });
    for _ in 0..8 {
        pci_line(&mut remote_read).await;
    }
    reset.await.unwrap().unwrap();

    let service =
        Service::new(&fixture(), None, path.clone(), pci, Some(spec_dir.clone())).unwrap();
    let mut client = ClientState::default();
    for line in [
        "[1] PP LOCK L //HARNESS/254",
        "[2] PP START S L",
        "[3] PP NEW S TESTUNIT 1.2.03",
        "[4] PP SET S Alpha 0x56 0x78",
        "[5] PP SET S Beta 0xAB 0xCD",
    ] {
        let response = service.handle(&mut client, line).await;
        assert_eq!(response.status, 200, "{line}: {}", response.final_text);
    }

    let checker = service.clone();
    let saving = tokio::spawn(async move {
        service
            .handle(&mut client, "[9] PP SAVE S //HARNESS/254/p/5")
            .await
    });

    let request = pci_line(&mut remote_read).await;
    assert!(
        request.windows(4).any(|window| window == b"2101"),
        "{request:?}"
    );
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    pci_reply(
        &mut remote_write,
        5,
        &[0x89, 0x01, b'T', b'E', b'S', b'T', b'U', b'N', b'I', b'T'],
    )
    .await;
    let request = pci_line(&mut remote_read).await;
    assert!(
        request.windows(4).any(|window| window == b"2102"),
        "{request:?}"
    );
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    pci_reply(
        &mut remote_write,
        5,
        &[0x87, 0x02, b'1', b'.', b'2', b'.', b'0', b'3'],
    )
    .await;

    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\4605001A2002"), "{request:?}");
    pci_reply(&mut remote_write, 5, &[0x83, 0x20, 0x00, 0x00]).await;
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\4605001A3002"), "{request:?}");
    pci_reply(&mut remote_write, 5, &[0x83, 0x30, 0x00, 0x00]).await;

    // Both STORE writes succeed with matching readbacks.
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\460500A42000"), "{request:?}");
    pci_reply(&mut remote_write, 5, &[0x32, 0x20, 0x00]).await;
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\4605001A2002"), "{request:?}");
    pci_reply(&mut remote_write, 5, &[0x83, 0x20, 0x56, 0x78]).await;

    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\460500A43000"), "{request:?}");
    pci_reply(&mut remote_write, 5, &[0x32, 0x30, 0x00]).await;
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\4605001A3002"), "{request:?}");
    pci_reply(&mut remote_write, 5, &[0x83, 0x30, 0xAB, 0xCD]).await;

    // The NCC catalogue forces a Save-to-NVM commit; fail it with the
    // definitive EXECUTE busy status. Extended exchanges carry no PCI
    // confirmation character.
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\460500E3810004"), "{request:?}");
    pci_reply(&mut remote_write, 5, &[0xe4, 0x83, 0, 4, 2]).await;

    let response = saving.await.unwrap();
    assert_eq!(
        response.status, 502,
        "NVM-commit failure must never report success: {}",
        response.final_text
    );
    assert!(
        response
            .final_text
            .starts_with("502 Physical PP Save-to-NVM failed after 2 confirmed write(s):"),
        "reason must report partial-write evidence: {}",
        response.final_text
    );
    assert!(
        response.final_text.contains("busy"),
        "underlying diagnostic must be preserved: {}",
        response.final_text
    );

    let model = checker.model.lock().await;
    let session = model
        .sessions
        .get("S")
        .expect("session survives failed save");
    assert!(session.dirty.contains("Alpha"), "dirty={:?}", session.dirty);
    assert!(session.dirty.contains("Beta"), "dirty={:?}", session.dirty);
    drop(model);

    std::fs::remove_file(&path).unwrap();
    std::fs::remove_file(spec_dir.join("TESTUNIT.xml")).unwrap();
    std::fs::remove_dir(&spec_dir).unwrap();
}

/// Drop-guard for the three new PP SAVE tests below: removes the temp state
/// file plus the spec dir on drop so cleanup still runs if an assert panics.
struct PpSaveCleanup {
    state: PathBuf,
    spec_dir: PathBuf,
}

impl PpSaveCleanup {
    fn new(state: PathBuf, spec_dir: PathBuf) -> Self {
        Self { state, spec_dir }
    }
}

impl Drop for PpSaveCleanup {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.state);
        let _ = std::fs::remove_file(self.spec_dir.join("TESTUNIT.xml"));
        let _ = std::fs::remove_dir(&self.spec_dir);
    }
}

/// P2 zero-confirmed pin: when the FIRST STORE fails, the 502 reason must
/// still carry the `after 0 confirmed write(s):` evidence prefix (including
/// the pluralised zero-case grammar), preserve the underlying diagnostic,
/// and retain every dirty flag.
#[tokio::test]
async fn physical_pp_save_first_store_failure_reports_zero_confirmed_and_retains_dirty() {
    async fn pci_line<R: tokio::io::AsyncBufRead + Unpin>(reader: &mut R) -> Vec<u8> {
        let mut line = Vec::new();
        reader.read_until(b'\r', &mut line).await.unwrap();
        line
    }
    async fn pci_reply<W: tokio::io::AsyncWrite + Unpin>(writer: &mut W, source: u8, cal: &[u8]) {
        let mut bytes = vec![0x86, source, 0x10, 0x00];
        bytes.extend_from_slice(cal);
        let sum = bytes.iter().fold(0u8, |sum, byte| sum.wrapping_add(*byte));
        bytes.push(0u8.wrapping_sub(sum));
        let mut wire = hex::encode_upper(bytes).into_bytes();
        wire.extend_from_slice(b"\r\n");
        writer.write_all(&wire).await.unwrap();
    }

    let path = state_path();
    let spec_dir = std::env::temp_dir().join(format!(
        "cmqttd-pp-zero-{}-{}.d",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    std::fs::create_dir_all(&spec_dir).unwrap();
    std::fs::write(
        spec_dir.join("TESTUNIT.xml"),
        r#"<UnitSpecification><Parameters>
        <Param><Name>Alpha</Name><Type>int</Type><Address>$20</Address><ArraySize>2</ArraySize><ProgramMethod>direct</ProgramMethod><Protection>none</Protection></Param>
        <Param><Name>Beta</Name><Type>int</Type><Address>$30</Address><ArraySize>2</ArraySize><ProgramMethod>direct</ProgramMethod><Protection>none</Protection></Param>
        </Parameters></UnitSpecification>"#,
    )
    .unwrap();
    let _cleanup = PpSaveCleanup::new(path.clone(), spec_dir.clone());

    let (pci, remote) = pci();
    let (remote_read, mut remote_write) = tokio::io::split(remote);
    let mut remote_read = BufReader::new(remote_read);
    let reset = tokio::spawn({
        let pci = pci.clone();
        async move { pci.pci_reset().await }
    });
    for _ in 0..8 {
        pci_line(&mut remote_read).await;
    }
    reset.await.unwrap().unwrap();

    let service =
        Service::new(&fixture(), None, path.clone(), pci, Some(spec_dir.clone())).unwrap();
    let mut client = ClientState::default();
    for line in [
        "[1] PP LOCK L //HARNESS/254",
        "[2] PP START S L",
        "[3] PP NEW S TESTUNIT 1.2.03",
        "[4] PP SET S Alpha 0x56 0x78",
        "[5] PP SET S Beta 0xAB 0xCD",
    ] {
        let response = service.handle(&mut client, line).await;
        assert_eq!(response.status, 200, "{line}: {}", response.final_text);
    }

    let checker = service.clone();
    let saving = tokio::spawn(async move {
        service
            .handle(&mut client, "[9] PP SAVE S //HARNESS/254/p/5")
            .await
    });

    let request = pci_line(&mut remote_read).await;
    assert!(
        request.windows(4).any(|window| window == b"2101"),
        "{request:?}"
    );
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    pci_reply(
        &mut remote_write,
        5,
        &[0x89, 0x01, b'T', b'E', b'S', b'T', b'U', b'N', b'I', b'T'],
    )
    .await;
    let request = pci_line(&mut remote_read).await;
    assert!(
        request.windows(4).any(|window| window == b"2102"),
        "{request:?}"
    );
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    pci_reply(
        &mut remote_write,
        5,
        &[0x87, 0x02, b'1', b'.', b'2', b'.', b'0', b'3'],
    )
    .await;

    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\4605001A2002"), "{request:?}");
    pci_reply(&mut remote_write, 5, &[0x83, 0x20, 0x00, 0x00]).await;
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\4605001A3002"), "{request:?}");
    pci_reply(&mut remote_write, 5, &[0x83, 0x30, 0x00, 0x00]).await;

    // The FIRST STORE fails (right parameter, wrong tag), so no write is
    // ever confirmed. Beta is never attempted.
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\460500A42000"), "{request:?}");
    pci_reply(&mut remote_write, 5, &[0x32, 0x20, 0x01]).await;

    // Negative read: no retry, readback, or next-range STORE may follow the
    // definitive failure. The save future is concurrently pending, so any
    // stray write would appear on the wire promptly; a 750ms window is
    // generous enough to avoid flakes on a loaded machine while still
    // proving deterministically that the failure path emits nothing further.
    assert!(
        tokio::time::timeout(Duration::from_millis(750), pci_line(&mut remote_read))
            .await
            .is_err(),
        "no further wire bytes expected after definitive STORE failure"
    );

    let response = saving.await.unwrap();
    assert_eq!(
        response.status, 502,
        "failed PP SAVE must never report success: {}",
        response.final_text
    );
    assert!(
        response
            .final_text
            .starts_with("502 Physical PP save failed after 0 confirmed write(s):"),
        "reason must report the zero-confirmed evidence: {}",
        response.final_text
    );
    assert!(
        response.final_text.contains("unit rejected"),
        "underlying diagnostic must be preserved: {}",
        response.final_text
    );

    let model = checker.model.lock().await;
    let session = model
        .sessions
        .get("S")
        .expect("session survives failed save");
    assert!(session.dirty.contains("Alpha"), "dirty={:?}", session.dirty);
    assert!(session.dirty.contains("Beta"), "dirty={:?}", session.dirty);
    assert_eq!(session.dirty.len(), 2, "dirty={:?}", session.dirty);
    drop(model);

    // Cleanup runs via the PpSaveCleanup drop-guard.
}

/// P2 multi-space pin: the shared `confirmed` counter must span STORE arms.
/// A successful Standard write followed by a failed Paged write reports
/// `after 1 confirmed write(s):`, proving the count is not per-space.
#[tokio::test]
async fn physical_pp_save_counts_paged_write_toward_confirmed_total() {
    async fn pci_line<R: tokio::io::AsyncBufRead + Unpin>(reader: &mut R) -> Vec<u8> {
        let mut line = Vec::new();
        reader.read_until(b'\r', &mut line).await.unwrap();
        line
    }
    async fn pci_reply<W: tokio::io::AsyncWrite + Unpin>(writer: &mut W, source: u8, cal: &[u8]) {
        let mut bytes = vec![0x86, source, 0x10, 0x00];
        bytes.extend_from_slice(cal);
        let sum = bytes.iter().fold(0u8, |sum, byte| sum.wrapping_add(*byte));
        bytes.push(0u8.wrapping_sub(sum));
        let mut wire = hex::encode_upper(bytes).into_bytes();
        wire.extend_from_slice(b"\r\n");
        writer.write_all(&wire).await.unwrap();
    }

    let path = state_path();
    let spec_dir = std::env::temp_dir().join(format!(
        "cmqttd-pp-multispace-{}-{}.d",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    std::fs::create_dir_all(&spec_dir).unwrap();
    std::fs::write(
        spec_dir.join("TESTUNIT.xml"),
        r#"<UnitSpecification><Parameters>
        <Param><Name>Alpha</Name><Type>int</Type><Address>$20</Address><ArraySize>2</ArraySize><ProgramMethod>direct</ProgramMethod><Protection>none</Protection></Param>
        <Param><Name>Paged1</Name><Type>int</Type><Address>$100</Address><ArraySize>2</ArraySize><ProgramMethod>paged</ProgramMethod><Protection>none</Protection></Param>
        </Parameters></UnitSpecification>"#,
    )
    .unwrap();
    let _cleanup = PpSaveCleanup::new(path.clone(), spec_dir.clone());

    let (pci, remote) = pci();
    let (remote_read, mut remote_write) = tokio::io::split(remote);
    let mut remote_read = BufReader::new(remote_read);
    let reset = tokio::spawn({
        let pci = pci.clone();
        async move { pci.pci_reset().await }
    });
    for _ in 0..8 {
        pci_line(&mut remote_read).await;
    }
    reset.await.unwrap().unwrap();

    let service =
        Service::new(&fixture(), None, path.clone(), pci, Some(spec_dir.clone())).unwrap();
    let mut client = ClientState::default();
    for line in [
        "[1] PP LOCK L //HARNESS/254",
        "[2] PP START S L",
        "[3] PP NEW S TESTUNIT 1.2.03",
        "[4] PP SET S Alpha 0x56 0x78",
        "[5] PP SET S Paged1 0x01 0x02",
    ] {
        let response = service.handle(&mut client, line).await;
        assert_eq!(response.status, 200, "{line}: {}", response.final_text);
    }

    let checker = service.clone();
    let saving = tokio::spawn(async move {
        service
            .handle(&mut client, "[9] PP SAVE S //HARNESS/254/p/5")
            .await
    });

    let request = pci_line(&mut remote_read).await;
    assert!(
        request.windows(4).any(|window| window == b"2101"),
        "{request:?}"
    );
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    pci_reply(
        &mut remote_write,
        5,
        &[0x89, 0x01, b'T', b'E', b'S', b'T', b'U', b'N', b'I', b'T'],
    )
    .await;
    let request = pci_line(&mut remote_read).await;
    assert!(
        request.windows(4).any(|window| window == b"2102"),
        "{request:?}"
    );
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    pci_reply(
        &mut remote_write,
        5,
        &[0x87, 0x02, b'1', b'.', b'2', b'.', b'0', b'3'],
    )
    .await;

    // Save pre-reads run per merged (space, range): Standard before Paged.
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\4605001A2002"), "{request:?}");
    pci_reply(&mut remote_write, 5, &[0x83, 0x20, 0x00, 0x00]).await;
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\4605001B010002"), "{request:?}");
    pci_reply(&mut remote_write, 5, &[0x83, 0x00, 0x00, 0x00]).await;

    // Writes run in unit-spec order: the Standard STORE succeeds first.
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\460500A42000"), "{request:?}");
    pci_reply(&mut remote_write, 5, &[0x32, 0x20, 0x00]).await;
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\4605001A2002"), "{request:?}");
    pci_reply(&mut remote_write, 5, &[0x83, 0x20, 0x56, 0x78]).await;

    // The Paged STORE then fails (page select succeeds, tagged STORE is
    // rejected with the wrong tag). The shared counter must still report
    // the one confirmed Standard write.
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\4605003901"), "{request:?}");
    pci_reply(&mut remote_write, 5, &[0x81, 0x01]).await;
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\460500A40000"), "{request:?}");
    pci_reply(&mut remote_write, 5, &[0x32, 0x00, 0x01]).await;

    // Negative read: no retry, readback, or further STORE may follow the
    // definitive paged failure. The save future is concurrently pending, so
    // any stray write would appear on the wire promptly; a 750ms window is
    // generous enough to avoid flakes on a loaded machine while still
    // proving deterministically that the failure path emits nothing further.
    assert!(
        tokio::time::timeout(Duration::from_millis(750), pci_line(&mut remote_read))
            .await
            .is_err(),
        "no further wire bytes expected after definitive paged STORE failure"
    );

    let response = saving.await.unwrap();
    assert_eq!(
        response.status, 502,
        "partial PP SAVE must never report success: {}",
        response.final_text
    );
    assert!(
        response
            .final_text
            .starts_with("502 Physical PP save failed after 1 confirmed write(s):"),
        "reason must count the Standard write across space arms: {}",
        response.final_text
    );
    assert!(
        response.final_text.contains("unit rejected"),
        "underlying diagnostic must be preserved: {}",
        response.final_text
    );

    let model = checker.model.lock().await;
    let session = model
        .sessions
        .get("S")
        .expect("session survives failed save");
    assert!(session.dirty.contains("Alpha"), "dirty={:?}", session.dirty);
    assert!(
        session.dirty.contains("Paged1"),
        "dirty={:?}",
        session.dirty
    );
    assert_eq!(session.dirty.len(), 2, "dirty={:?}", session.dirty);
    drop(model);

    // Cleanup runs via the PpSaveCleanup drop-guard.
}

/// P2 unchanged-skip pin: an item whose staged value equals the pre-read
/// (`modified == original`) is skipped via `continue` without counting.
/// With the middle of three dirty params unchanged and the third STORE
/// failing, the evidence must read 1, not 2.
#[tokio::test]
async fn physical_pp_save_skips_unchanged_items_without_counting() {
    async fn pci_line<R: tokio::io::AsyncBufRead + Unpin>(reader: &mut R) -> Vec<u8> {
        let mut line = Vec::new();
        reader.read_until(b'\r', &mut line).await.unwrap();
        line
    }
    async fn pci_reply<W: tokio::io::AsyncWrite + Unpin>(writer: &mut W, source: u8, cal: &[u8]) {
        let mut bytes = vec![0x86, source, 0x10, 0x00];
        bytes.extend_from_slice(cal);
        let sum = bytes.iter().fold(0u8, |sum, byte| sum.wrapping_add(*byte));
        bytes.push(0u8.wrapping_sub(sum));
        let mut wire = hex::encode_upper(bytes).into_bytes();
        wire.extend_from_slice(b"\r\n");
        writer.write_all(&wire).await.unwrap();
    }

    let path = state_path();
    let spec_dir = std::env::temp_dir().join(format!(
        "cmqttd-pp-skip-{}-{}.d",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    std::fs::create_dir_all(&spec_dir).unwrap();
    std::fs::write(
        spec_dir.join("TESTUNIT.xml"),
        r#"<UnitSpecification><Parameters>
        <Param><Name>Alpha</Name><Type>int</Type><Address>$20</Address><ArraySize>2</ArraySize><ProgramMethod>direct</ProgramMethod><Protection>none</Protection></Param>
        <Param><Name>Beta</Name><Type>int</Type><Address>$30</Address><ArraySize>2</ArraySize><ProgramMethod>direct</ProgramMethod><Protection>none</Protection></Param>
        <Param><Name>Gamma</Name><Type>int</Type><Address>$40</Address><ArraySize>2</ArraySize><ProgramMethod>direct</ProgramMethod><Protection>none</Protection></Param>
        </Parameters></UnitSpecification>"#,
    )
    .unwrap();
    let _cleanup = PpSaveCleanup::new(path.clone(), spec_dir.clone());

    let (pci, remote) = pci();
    let (remote_read, mut remote_write) = tokio::io::split(remote);
    let mut remote_read = BufReader::new(remote_read);
    let reset = tokio::spawn({
        let pci = pci.clone();
        async move { pci.pci_reset().await }
    });
    for _ in 0..8 {
        pci_line(&mut remote_read).await;
    }
    reset.await.unwrap().unwrap();

    let service =
        Service::new(&fixture(), None, path.clone(), pci, Some(spec_dir.clone())).unwrap();
    let mut client = ClientState::default();
    for line in [
        "[1] PP LOCK L //HARNESS/254",
        "[2] PP START S L",
        "[3] PP NEW S TESTUNIT 1.2.03",
        // Beta is staged dirty but matches the scripted pre-read below, so
        // the save must skip it without touching the wire or the counter.
        "[4] PP SET S Alpha 0x56 0x78",
        "[5] PP SET S Beta 0x00 0x00",
        "[6] PP SET S Gamma 0xAB 0xCD",
    ] {
        let response = service.handle(&mut client, line).await;
        assert_eq!(response.status, 200, "{line}: {}", response.final_text);
    }

    let checker = service.clone();
    let saving = tokio::spawn(async move {
        service
            .handle(&mut client, "[9] PP SAVE S //HARNESS/254/p/5")
            .await
    });

    let request = pci_line(&mut remote_read).await;
    assert!(
        request.windows(4).any(|window| window == b"2101"),
        "{request:?}"
    );
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    pci_reply(
        &mut remote_write,
        5,
        &[0x89, 0x01, b'T', b'E', b'S', b'T', b'U', b'N', b'I', b'T'],
    )
    .await;
    let request = pci_line(&mut remote_read).await;
    assert!(
        request.windows(4).any(|window| window == b"2102"),
        "{request:?}"
    );
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    pci_reply(
        &mut remote_write,
        5,
        &[0x87, 0x02, b'1', b'.', b'2', b'.', b'0', b'3'],
    )
    .await;

    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\4605001A2002"), "{request:?}");
    pci_reply(&mut remote_write, 5, &[0x83, 0x20, 0x00, 0x00]).await;
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\4605001A3002"), "{request:?}");
    pci_reply(&mut remote_write, 5, &[0x83, 0x30, 0x00, 0x00]).await;
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\4605001A4002"), "{request:?}");
    pci_reply(&mut remote_write, 5, &[0x83, 0x40, 0x00, 0x00]).await;

    // Alpha STORE succeeds; Beta emits no STORE at all; Gamma STORE fails.
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\460500A42000"), "{request:?}");
    pci_reply(&mut remote_write, 5, &[0x32, 0x20, 0x00]).await;
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\4605001A2002"), "{request:?}");
    pci_reply(&mut remote_write, 5, &[0x83, 0x20, 0x56, 0x78]).await;

    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\460500A44000"), "{request:?}");
    pci_reply(&mut remote_write, 5, &[0x32, 0x40, 0x01]).await;

    // Negative read: no retry, readback, or further STORE may follow the
    // definitive Gamma failure (Beta was skipped without touching the wire).
    // The save future is concurrently pending, so any stray write would
    // appear on the wire promptly; a 750ms window is generous enough to
    // avoid flakes on a loaded machine while still proving deterministically
    // that the failure path emits nothing further.
    assert!(
        tokio::time::timeout(Duration::from_millis(750), pci_line(&mut remote_read))
            .await
            .is_err(),
        "no further wire bytes expected after definitive STORE failure"
    );

    let response = saving.await.unwrap();
    assert_eq!(
        response.status, 502,
        "partial PP SAVE must never report success: {}",
        response.final_text
    );
    assert!(
        response
            .final_text
            .starts_with("502 Physical PP save failed after 1 confirmed write(s):"),
        "skipped Beta must not be counted (would read 2 otherwise): {}",
        response.final_text
    );
    assert!(
        response.final_text.contains("unit rejected"),
        "underlying diagnostic must be preserved: {}",
        response.final_text
    );

    let model = checker.model.lock().await;
    let session = model
        .sessions
        .get("S")
        .expect("session survives failed save");
    assert!(session.dirty.contains("Alpha"), "dirty={:?}", session.dirty);
    assert!(session.dirty.contains("Beta"), "dirty={:?}", session.dirty);
    assert!(session.dirty.contains("Gamma"), "dirty={:?}", session.dirty);
    assert_eq!(session.dirty.len(), 3, "dirty={:?}", session.dirty);
    drop(model);

    // Cleanup runs via the PpSaveCleanup drop-guard.
}

/// P2 factory-skip pin: a dirty param whose spec declares
/// `Protection: factory` (or `special`) is acknowledged unwriteable by an
/// ordinary SAVE — it is inserted into `cleared` WITHOUT any wire write,
/// so on success it is dropped from `dirty` along with the params that
/// were actually written. This pins the plan-filter asymmetry
/// deliberately: factory-skipped params clear silently, while tag-filtered
/// params (see the next test) stay dirty. If a future change starts
/// writing factory params to the wire, the negative read below fails; if
/// it stops clearing them, the `dirty.is_empty()` assert fails.
#[tokio::test]
async fn physical_pp_save_factory_protected_clears_dirty_without_write() {
    async fn pci_line<R: tokio::io::AsyncBufRead + Unpin>(reader: &mut R) -> Vec<u8> {
        let mut line = Vec::new();
        reader.read_until(b'\r', &mut line).await.unwrap();
        line
    }
    async fn pci_reply<W: tokio::io::AsyncWrite + Unpin>(writer: &mut W, source: u8, cal: &[u8]) {
        let mut bytes = vec![0x86, source, 0x10, 0x00];
        bytes.extend_from_slice(cal);
        let sum = bytes.iter().fold(0u8, |sum, byte| sum.wrapping_add(*byte));
        bytes.push(0u8.wrapping_sub(sum));
        let mut wire = hex::encode_upper(bytes).into_bytes();
        wire.extend_from_slice(b"\r\n");
        writer.write_all(&wire).await.unwrap();
    }

    let path = state_path();
    let spec_dir = std::env::temp_dir().join(format!(
        "cmqttd-pp-factory-{}-{}.d",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    std::fs::create_dir_all(&spec_dir).unwrap();
    std::fs::write(
        spec_dir.join("TESTUNIT.xml"),
        r#"<UnitSpecification><Parameters>
        <Param><Name>Alpha</Name><Type>int</Type><Address>$20</Address><ArraySize>2</ArraySize><ProgramMethod>direct</ProgramMethod><Protection>none</Protection></Param>
        <Param><Name>FactParam</Name><Type>int</Type><Address>$30</Address><ArraySize>2</ArraySize><ProgramMethod>direct</ProgramMethod><Protection>factory</Protection></Param>
        </Parameters></UnitSpecification>"#,
    )
    .unwrap();
    let _cleanup = PpSaveCleanup::new(path.clone(), spec_dir.clone());

    let (pci, remote) = pci();
    let (remote_read, mut remote_write) = tokio::io::split(remote);
    let mut remote_read = BufReader::new(remote_read);
    let reset = tokio::spawn({
        let pci = pci.clone();
        async move { pci.pci_reset().await }
    });
    for _ in 0..8 {
        pci_line(&mut remote_read).await;
    }
    reset.await.unwrap().unwrap();

    let service =
        Service::new(&fixture(), None, path.clone(), pci, Some(spec_dir.clone())).unwrap();
    let mut client = ClientState::default();
    for line in [
        "[1] PP LOCK L //HARNESS/254",
        "[2] PP START S L",
        "[3] PP NEW S TESTUNIT 1.2.03",
        "[4] PP SET S Alpha 0x56 0x78",
        "[5] PP SET S FactParam 0x11 0x22",
    ] {
        let response = service.handle(&mut client, line).await;
        assert_eq!(response.status, 200, "{line}: {}", response.final_text);
    }

    let checker = service.clone();
    let saving = tokio::spawn(async move {
        service
            .handle(&mut client, "[9] PP SAVE S //HARNESS/254/p/5")
            .await
    });

    let request = pci_line(&mut remote_read).await;
    assert!(
        request.windows(4).any(|window| window == b"2101"),
        "{request:?}"
    );
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    pci_reply(
        &mut remote_write,
        5,
        &[0x89, 0x01, b'T', b'E', b'S', b'T', b'U', b'N', b'I', b'T'],
    )
    .await;
    let request = pci_line(&mut remote_read).await;
    assert!(
        request.windows(4).any(|window| window == b"2102"),
        "{request:?}"
    );
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    pci_reply(
        &mut remote_write,
        5,
        &[0x87, 0x02, b'1', b'.', b'2', b'.', b'0', b'3'],
    )
    .await;

    // Only Alpha is pre-read: FactParam is factory-skipped in the planner
    // before any range is merged, so its address never touches the wire.
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\4605001A2002"), "{request:?}");
    pci_reply(&mut remote_write, 5, &[0x83, 0x20, 0x00, 0x00]).await;

    // Alpha STORE succeeds with a matching readback.
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\460500A42000"), "{request:?}");
    pci_reply(&mut remote_write, 5, &[0x32, 0x20, 0x00]).await;
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\4605001A2002"), "{request:?}");
    pci_reply(&mut remote_write, 5, &[0x83, 0x20, 0x56, 0x78]).await;

    let response = saving.await.unwrap();
    assert_eq!(
        response.status, 200,
        "SAVE with only factory-skipped remainder must succeed: {}",
        response.final_text
    );
    assert_eq!(response.final_text, "200 OK", "{}", response.final_text);

    // Negative read: FactParam must never be written. The save future has
    // resolved, so any STORE/readback for $30 would already be on the wire;
    // a 750ms window is generous enough to avoid flakes on a loaded machine
    // while still proving deterministically that nothing further was emitted.
    assert!(
        tokio::time::timeout(Duration::from_millis(750), pci_line(&mut remote_read))
            .await
            .is_err(),
        "no further wire bytes expected: factory param must not be written"
    );

    let model = checker.model.lock().await;
    let session = model
        .sessions
        .get("S")
        .expect("session survives successful save");
    assert!(
        session.dirty.is_empty(),
        "factory-skipped FactParam clears without write: dirty={:?}",
        session.dirty
    );
    drop(model);

    // Cleanup runs via the PpSaveCleanup drop-guard.
}

/// P2 tag-filter pin: a dirty param whose spec `<Tag>` children do not
/// include the SAVE's tag selection is NOT attempted under this tag
/// selection — the planner `continue`s WITHOUT inserting it into `cleared`,
/// so on success it REMAINS dirty for a later save with matching tags.
/// Only Alpha (tagged `core`) is written and cleared; Beta (untagged)
/// stays dirty with `dirty.len() == 1`. If a future change clears
/// tag-filtered params, the `dirty.len()` assert fails; if it attempts
/// them, the scripted wire sequence mismatches (an unexpected $30 pre-read
/// or STORE appears where the Alpha STORE is expected).
#[tokio::test]
async fn physical_pp_save_tag_filter_retains_untagged_dirty() {
    async fn pci_line<R: tokio::io::AsyncBufRead + Unpin>(reader: &mut R) -> Vec<u8> {
        let mut line = Vec::new();
        reader.read_until(b'\r', &mut line).await.unwrap();
        line
    }
    async fn pci_reply<W: tokio::io::AsyncWrite + Unpin>(writer: &mut W, source: u8, cal: &[u8]) {
        let mut bytes = vec![0x86, source, 0x10, 0x00];
        bytes.extend_from_slice(cal);
        let sum = bytes.iter().fold(0u8, |sum, byte| sum.wrapping_add(*byte));
        bytes.push(0u8.wrapping_sub(sum));
        let mut wire = hex::encode_upper(bytes).into_bytes();
        wire.extend_from_slice(b"\r\n");
        writer.write_all(&wire).await.unwrap();
    }

    let path = state_path();
    let spec_dir = std::env::temp_dir().join(format!(
        "cmqttd-pp-tagfilter-{}-{}.d",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    std::fs::create_dir_all(&spec_dir).unwrap();
    std::fs::write(
        spec_dir.join("TESTUNIT.xml"),
        r#"<UnitSpecification><Parameters>
        <Param><Name>Alpha</Name><Type>int</Type><Address>$20</Address><ArraySize>2</ArraySize><ProgramMethod>direct</ProgramMethod><Protection>none</Protection><Tag>core</Tag></Param>
        <Param><Name>Beta</Name><Type>int</Type><Address>$30</Address><ArraySize>2</ArraySize><ProgramMethod>direct</ProgramMethod><Protection>none</Protection></Param>
        </Parameters></UnitSpecification>"#,
    )
    .unwrap();
    let _cleanup = PpSaveCleanup::new(path.clone(), spec_dir.clone());

    let (pci, remote) = pci();
    let (remote_read, mut remote_write) = tokio::io::split(remote);
    let mut remote_read = BufReader::new(remote_read);
    let reset = tokio::spawn({
        let pci = pci.clone();
        async move { pci.pci_reset().await }
    });
    for _ in 0..8 {
        pci_line(&mut remote_read).await;
    }
    reset.await.unwrap().unwrap();

    let service =
        Service::new(&fixture(), None, path.clone(), pci, Some(spec_dir.clone())).unwrap();
    let mut client = ClientState::default();
    for line in [
        "[1] PP LOCK L //HARNESS/254",
        "[2] PP START S L",
        "[3] PP NEW S TESTUNIT 1.2.03",
        "[4] PP SET S Alpha 0x56 0x78",
        "[5] PP SET S Beta 0xAB 0xCD",
    ] {
        let response = service.handle(&mut client, line).await;
        assert_eq!(response.status, 200, "{line}: {}", response.final_text);
    }

    let checker = service.clone();
    let saving = tokio::spawn(async move {
        service
            .handle(&mut client, "[9] PP SAVE S //HARNESS/254/p/5 core")
            .await
    });

    let request = pci_line(&mut remote_read).await;
    assert!(
        request.windows(4).any(|window| window == b"2101"),
        "{request:?}"
    );
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    pci_reply(
        &mut remote_write,
        5,
        &[0x89, 0x01, b'T', b'E', b'S', b'T', b'U', b'N', b'I', b'T'],
    )
    .await;
    let request = pci_line(&mut remote_read).await;
    assert!(
        request.windows(4).any(|window| window == b"2102"),
        "{request:?}"
    );
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    pci_reply(
        &mut remote_write,
        5,
        &[0x87, 0x02, b'1', b'.', b'2', b'.', b'0', b'3'],
    )
    .await;

    // Only Alpha ($20) is pre-read: Beta carries no `core` tag so the
    // planner skips it before range merging. If Beta were attempted, its
    // $30 pre-read would appear here and fail the prefix assert.
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\4605001A2002"), "{request:?}");
    pci_reply(&mut remote_write, 5, &[0x83, 0x20, 0x00, 0x00]).await;

    // Alpha STORE succeeds with a matching readback.
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\460500A42000"), "{request:?}");
    pci_reply(&mut remote_write, 5, &[0x32, 0x20, 0x00]).await;
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\4605001A2002"), "{request:?}");
    pci_reply(&mut remote_write, 5, &[0x83, 0x20, 0x56, 0x78]).await;

    let response = saving.await.unwrap();
    assert_eq!(
        response.status, 200,
        "tag-filtered SAVE must succeed for the selected params: {}",
        response.final_text
    );
    assert_eq!(response.final_text, "200 OK", "{}", response.final_text);

    // Negative read: Beta must never be attempted under this tag selection.
    // The save future has resolved, so any $30 STORE/readback would already
    // be on the wire; a 750ms window is generous enough to avoid flakes on
    // a loaded machine while still proving deterministically that nothing
    // further was emitted.
    assert!(
        tokio::time::timeout(Duration::from_millis(750), pci_line(&mut remote_read))
            .await
            .is_err(),
        "no further wire bytes expected: Beta must not be attempted under tag `core`"
    );

    let model = checker.model.lock().await;
    let session = model
        .sessions
        .get("S")
        .expect("session survives successful save");
    assert!(
        !session.dirty.contains("Alpha"),
        "selected Alpha is written and cleared: dirty={:?}",
        session.dirty
    );
    assert!(
        session.dirty.contains("Beta"),
        "tag-filtered Beta remains dirty for a later save: dirty={:?}",
        session.dirty
    );
    assert_eq!(session.dirty.len(), 1, "dirty={:?}", session.dirty);
    drop(model);

    // Cleanup runs via the PpSaveCleanup drop-guard.
}
