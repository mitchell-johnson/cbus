use super::*;
use tokio::io::AsyncReadExt;

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
    for command in [
        "PP LOAD S //HARNESS/254/p/5",
        "PP SAVE S //HARNESS/254/p/5",
        "SET //HARNESS/254/p/5 Address 6",
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
            .handle(&mut first, "[6] PP LOAD S /db//HARNESS/254/p/5")
            .await
            .status,
        200
    );
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
