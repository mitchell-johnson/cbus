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

async fn connect_command_session(
    address: std::net::SocketAddr,
) -> (
    BufReader<tokio::net::tcp::OwnedReadHalf>,
    tokio::net::tcp::OwnedWriteHalf,
) {
    let stream = TcpStream::connect(address).await.unwrap();
    let (reader, writer) = stream.into_split();
    let mut reader = BufReader::new(reader);
    let mut greeting = String::new();
    reader.read_line(&mut greeting).await.unwrap();
    assert_eq!(greeting, "201 cmqttd C-Gate service ready\r\n");
    (reader, writer)
}

async fn command_lines(
    reader: &mut BufReader<tokio::net::tcp::OwnedReadHalf>,
    writer: &mut tokio::net::tcp::OwnedWriteHalf,
    tag: &str,
    command: &str,
) -> Vec<String> {
    writer
        .write_all(format!("[{tag}] {command}\r\n").as_bytes())
        .await
        .unwrap();
    let prefix = format!("[{tag}] ");
    let mut lines = Vec::new();
    loop {
        let mut line = String::new();
        assert_ne!(reader.read_line(&mut line).await.unwrap(), 0);
        let line = line.trim_end_matches(['\r', '\n']).to_string();
        let payload = line
            .strip_prefix(&prefix)
            .unwrap_or_else(|| panic!("unexpected response line: {line}"));
        let complete = payload.as_bytes().get(3) == Some(&b' ');
        lines.push(line);
        if complete {
            return lines;
        }
    }
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

#[tokio::test]
async fn pp_reset_to_defaults_is_spec_backed_staged_and_persisted_only_by_save() {
    let path = state_path();
    let spec_dir = state_path().with_extension("unitspec");
    std::fs::create_dir_all(&spec_dir).unwrap();
    std::fs::write(
        spec_dir.join("KEYGL5.xml"),
        r#"<UnitSpecification><Parameters>
        <Param><Name>StaticTextString0</Name><Type>string</Type><Address>$20</Address><DefaultValue>Factory text</DefaultValue></Param>
        <Param><Name>UnitName</Name><Type>string</Type><Address>$21</Address><DefaultValue>Factory name</DefaultValue></Param>
        <Param><Name>WithoutDefault</Name><Type>int</Type><Address>$22</Address></Param>
        </Parameters></UnitSpecification>"#,
    )
    .unwrap();
    let (pci_client, mut remote) = pci();
    let service = Service::new(
        &fixture(),
        None,
        path.clone(),
        pci_client,
        Some(spec_dir.clone()),
    )
    .unwrap();
    let mut owner = ClientState::default();
    for line in [
        "[1] PP LOCK L //HARNESS/254",
        "[2] PP START S L",
        "[3] PP LOAD S /db//HARNESS/254/p/5",
        "[4] PP SET S StaticTextString0 Custom",
        "[5] PP SET S AdHoc staged-only",
    ] {
        let response = service.handle(&mut owner, line).await;
        assert_eq!(response.status, 200, "{line}: {}", response.final_text);
    }
    let before_database = service.model.lock().await.projects["HARNESS"].networks[&254].units[&5]
        .fields["StaticTextString0"]
        .clone();
    assert_eq!(before_database, "Fixture");

    let mut foreign = ClientState::default();
    assert_eq!(
        service
            .handle(&mut foreign, "[6] PP RESET_TO_DEFAULTS S")
            .await
            .status,
        420
    );
    let reset = service
        .handle(&mut owner, "[7] PP RESET_TO_DEFAULTS S")
        .await;
    assert_eq!(reset.status, 200, "{}", reset.final_text);
    {
        let model = service.model.lock().await;
        let session = &model.sessions["S"];
        assert_eq!(
            session.params,
            HashMap::from([
                ("StaticTextString0".to_string(), "Factory text".to_string()),
                ("UnitName".to_string(), "Factory name".to_string()),
            ])
        );
        assert_eq!(
            session.dirty,
            HashSet::from(["StaticTextString0".to_string(), "UnitName".to_string()])
        );
        // RESET is staged only; the database still holds its original value.
        assert_eq!(
            model.projects["HARNESS"].networks[&254].units[&5].fields["StaticTextString0"],
            "Fixture"
        );
    }
    assert!(
        tokio::time::timeout(Duration::from_millis(20), remote.read_u8())
            .await
            .is_err(),
        "RESET_TO_DEFAULTS must not perform PCI I/O"
    );

    assert_eq!(
        service
            .handle(&mut owner, "[8] PP SAVE_TO_SOURCE S")
            .await
            .status,
        200
    );
    assert_eq!(service.handle(&mut owner, "[9] PP END S").await.status, 200);
    assert_eq!(
        service.handle(&mut owner, "[10] PP UNLOCK L").await.status,
        200
    );
    let (pci, _remote) = pci();
    let restarted =
        Service::new(&fixture(), None, path.clone(), pci, Some(spec_dir.clone())).unwrap();
    let model = restarted.model.lock().await;
    let fields = &model.projects["HARNESS"].networks[&254].units[&5].fields;
    assert_eq!(fields["StaticTextString0"], "Factory text");
    assert_eq!(fields["UnitName"], "Factory name");
    assert!(!fields.contains_key("AdHoc"));
    assert!(model.sessions.is_empty());
    drop(model);

    std::fs::remove_file(path).unwrap();
    std::fs::remove_dir_all(spec_dir).unwrap();
}

#[tokio::test]
async fn pp_reset_to_defaults_without_exact_spec_fails_unchanged_and_without_pci() {
    let path = state_path();
    let (pci, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let mut owner = ClientState::default();
    for line in [
        "[1] PP LOCK L //HARNESS/254",
        "[2] PP START S L",
        "[3] PP LOAD S /db//HARNESS/254/p/5",
        "[4] PP SET S StaticTextString0 Custom",
    ] {
        assert_eq!(service.handle(&mut owner, line).await.status, 200, "{line}");
    }
    let before = service.model.lock().await.sessions["S"].clone();
    let response = service
        .handle(&mut owner, "[5] PP RESET_TO_DEFAULTS S")
        .await;
    assert_eq!(response.status, 408);
    assert_eq!(
        response.final_text,
        "408 RESET_TO_DEFAULTS requires a loaded unit specification"
    );
    assert_eq!(service.model.lock().await.sessions["S"], before);
    assert!(
        tokio::time::timeout(Duration::from_millis(20), remote.read_u8())
            .await
            .is_err(),
        "failed RESET_TO_DEFAULTS must not perform PCI I/O"
    );
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn pp_reset_to_defaults_with_invalid_spec_fails_unchanged_and_without_pci() {
    let path = state_path();
    let spec_dir = state_path().with_extension("invalid-unitspec");
    std::fs::create_dir_all(&spec_dir).unwrap();
    std::fs::write(
        spec_dir.join("KEYGL5.xml"),
        r#"<UnitSpecification><Parameters>
        <Param><Name>StaticTextString0</Name><Type>string</Type></Param>
        </Parameters></UnitSpecification>"#,
    )
    .unwrap();
    let (pci_client, mut remote) = pci();
    let service = Service::new(
        &fixture(),
        None,
        path.clone(),
        pci_client,
        Some(spec_dir.clone()),
    )
    .unwrap();
    let mut owner = ClientState::default();
    for line in [
        "[1] PP LOCK L //HARNESS/254",
        "[2] PP START S L",
        "[3] PP LOAD S /db//HARNESS/254/p/5",
        "[4] PP SET S StaticTextString0 Custom",
    ] {
        assert_eq!(service.handle(&mut owner, line).await.status, 200, "{line}");
    }
    let before = service.model.lock().await.sessions["S"].clone();
    let response = service
        .handle(&mut owner, "[5] PP RESET_TO_DEFAULTS S")
        .await;
    assert_eq!(response.status, 408);
    assert_eq!(
        response.final_text,
        "408 RESET_TO_DEFAULTS requires a loaded unit specification"
    );
    assert_eq!(service.model.lock().await.sessions["S"], before);
    assert!(
        tokio::time::timeout(Duration::from_millis(20), remote.read_u8())
            .await
            .is_err(),
        "failed RESET_TO_DEFAULTS must not perform PCI I/O"
    );
    std::fs::remove_file(path).unwrap();
    std::fs::remove_dir_all(spec_dir).unwrap();
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
async fn native_session_event_alias_and_quit_are_connection_local() {
    let path = state_path();
    let (pci, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let server = tokio::spawn(service.clone().serve(listener));
    let (mut first_reader, mut first_writer) = connect_command_session(address).await;
    let (mut second_reader, mut second_writer) = connect_command_session(address).await;

    assert_eq!(
        command_lines(&mut first_reader, &mut first_writer, "1", "SESSION_ID").await,
        ["[1] 300 sessionID=cmd3"]
    );
    assert_eq!(
        command_lines(&mut second_reader, &mut second_writer, "2", "SESSION_ID").await,
        ["[2] 300 sessionID=cmd5"]
    );
    let all = command_lines(
        &mut first_reader,
        &mut first_writer,
        "3",
        "SESSION_ID ALL ignored-by-native",
    )
    .await;
    assert_eq!(all.len(), 2);
    assert!(all[0].starts_with("[3] 300-sessionID=cmd3 origin=/127.0.0.1:"));
    assert!(all[0].contains(" from="));
    assert!(all[1].starts_with("[3] 300 sessionID=cmd5 origin=/127.0.0.1:"));

    assert_eq!(
        command_lines(
            &mut first_reader,
            &mut first_writer,
            "4",
            "SESSION_ID TAG C-Bus   Toolkit test",
        )
        .await,
        ["[4] 200 OK."]
    );
    let tagged = command_lines(
        &mut second_reader,
        &mut second_writer,
        "5",
        "SESSION_ID ALL",
    )
    .await;
    assert!(tagged[0].ends_with(" tag=C-Bus Toolkit test"));
    assert_eq!(
        command_lines(
            &mut first_reader,
            &mut first_writer,
            "6",
            "SESSION_ID TAG replacement",
        )
        .await,
        ["[6] 408 Operation failed: tag name has already been set"]
    );
    assert_eq!(
        command_lines(&mut first_reader, &mut first_writer, "7", "SESSION_ID TAG",).await,
        ["[7] 400 Syntax Error: tag name not supplied"]
    );

    assert_eq!(
        command_lines(&mut first_reader, &mut first_writer, "8", "EVENTS").await,
        ["[8] 306 e0s0c0"]
    );
    assert_eq!(
        command_lines(&mut first_reader, &mut first_writer, "9", "EVENTS ON").await,
        ["[9] 200 OK."]
    );
    assert_eq!(
        command_lines(&mut first_reader, &mut first_writer, "10", "EVENT").await,
        ["[10] 306 e+s0c0"]
    );

    assert_eq!(
        command_lines(&mut first_reader, &mut first_writer, "11", "QUIT").await,
        ["[11] 204 Closing connection."]
    );
    let mut eof = String::new();
    assert_eq!(first_reader.read_line(&mut eof).await.unwrap(), 0);
    let remaining = command_lines(
        &mut second_reader,
        &mut second_writer,
        "12",
        "SESSION_ID ALL",
    )
    .await;
    assert_eq!(remaining.len(), 1);
    assert!(remaining[0].starts_with("[12] 300 sessionID=cmd5 "));
    assert!(!remaining[0].contains("cmd3"));

    assert_eq!(
        command_lines(&mut second_reader, &mut second_writer, "13", "EXIT").await,
        ["[13] 204 Closing connection."]
    );
    eof.clear();
    assert_eq!(second_reader.read_line(&mut eof).await.unwrap(), 0);

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
    assert_eq!(document["label_clear"], true);
    assert_eq!(document["label_kfi"], true);
    assert_eq!(document["dynamic_label_observation"], true);
    assert_eq!(document["dynamic_label_device_readback"], false);
    assert_eq!(document["edlt_factory_default"], true);
    assert_eq!(document["edlt_widget_groups"], true);
    assert_eq!(document["edlt_extended_firmware"], true);
    assert_eq!(document["edlt_applications"], true);
    assert_eq!(document["network_syncnew"], true);
    assert_eq!(document["network_set_project_identify"], true);
    assert_eq!(document["net_unravelunit_matchdb_duplicate_255"], true);
    assert_eq!(document["pp_reset_to_defaults"], true);
    assert_eq!(document["event_subscriptions"], true);
    assert_eq!(document["session_id"], true);
    assert_eq!(document["quit"], true);
    assert_eq!(
        document["do_methods"],
        serde_json::json!(["factorydefault", "lighting", "sync"])
    );
    // Dormant default: no --cgate-auth-file, so the LOGIN gate is off.
    assert_eq!(document["cgate_auth"], false);
    std::fs::remove_file(path).unwrap();
}

/// The armed LOGIN gate is discoverable via capabilities, without needing
/// a denied-write probe.
#[tokio::test]
async fn capabilities_report_armed_login_gate() {
    let (service, path) = authed_service();
    let mut client = ClientState::default();
    let response = service.handle(&mut client, "[1] CMQTT CAPABILITIES").await;
    assert_eq!(response.status, 200);
    let document: serde_json::Value = serde_json::from_str(&response.lines[0]).unwrap();
    assert_eq!(document["cgate_auth"], true);
    std::fs::remove_file(path).ok();
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
    assert_eq!(document["requested_address"], "//HARNESS/254");
    assert_eq!(document["observation_scope"], "network");
    assert_eq!(document["recipient_verified"], false);
    assert_eq!(document["project"], "HARNESS");
    assert_eq!(document["network"], 254);
    // A unit-shaped request still exposes the network-wide observations and
    // does not imply that the requested unit received them.
    let unit = service
        .handle(&mut client, "[2] CMQTT LABELS //HARNESS/254/p/5")
        .await;
    assert_eq!(unit.status, 200);
    assert_eq!(unit.lines.len(), 1);
    let unit_document: serde_json::Value = serde_json::from_str(&unit.lines[0]).unwrap();
    assert_eq!(unit_document["address"], "//HARNESS/254/p/5");
    assert_eq!(unit_document["requested_address"], "//HARNESS/254/p/5");
    assert_eq!(unit_document["observation_scope"], "network");
    assert_eq!(unit_document["recipient_verified"], false);
    assert_eq!(unit_document["device_readback"], false);
    assert_eq!(unit_document["observations"], document["observations"]);
    // Bare canonical network forms accepted; trailing-slash forms rejected.
    for address in ["254", "HARNESS/254"] {
        let response = service
            .handle(&mut client, &format!("[3] CMQTT LABELS {address}"))
            .await;
        assert_eq!(response.status, 200, "{address}");
        let document: serde_json::Value = serde_json::from_str(&response.lines[0]).unwrap();
        assert_eq!(document["requested_address"], address);
        assert_eq!(document["observation_scope"], "network");
        assert_eq!(document["recipient_verified"], false);
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

#[tokio::test(start_paused = true)]
async fn do_edlt_factory_default_is_guarded_and_sent_once() {
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
    service
        .record_label("received", Some(5), 56, &[0xa4, 1, 0, 0, b'X'])
        .await;
    let mut client = ClientState::default();
    let request = service.handle(&mut client, "[1] DO //HARNESS/254/p/5 FactoryDefault");
    let peer = async {
        let wire = pci_line(&mut remote_read).await;
        assert_eq!(&wire[..wire.len() - 2], b"\\46050900A4FF43B2B262");
        let confirmation = wire[wire.len() - 2];
        remote_write.write_all(&[confirmation, b'.']).await.unwrap();
        pci_reply(&mut remote_write, 5, &[0x32, 0xff, 0x43]).await;
    };
    let (response, ()) = tokio::join!(request, peer);
    assert_eq!(response.status, 202);
    assert_eq!(response.final_text, "202 Done: //HARNESS/254/p/5");
    assert!(service.observed_labels.lock().await.observations.is_empty());

    for command in [
        "[2] DO //HARNESS/254/p/4 FactoryDefault",
        "[3] DO //HARNESS/253/p/5 FactoryDefault",
        "[4] DO //HARNESS/254/p/5 FactoryDefault extra",
    ] {
        assert!(
            service.handle(&mut client, command).await.status >= 400,
            "{command}"
        );
    }
    std::fs::remove_file(path).unwrap();
}

#[tokio::test(start_paused = true)]
async fn physical_label_clear_matches_native_wire_and_confirmation_contract() {
    async fn pci_line<R: tokio::io::AsyncBufRead + Unpin>(reader: &mut R) -> Vec<u8> {
        let mut line = Vec::new();
        reader.read_until(b'\r', &mut line).await.unwrap();
        line
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
    service
        .record_label("received", Some(5), 56, &[0xa4, 1, 0, 0, b'X'])
        .await;
    let mut events = service.events.subscribe();
    let mut client = ClientState::default();

    let all = service.handle(&mut client, "[1] LABEL CLEAR //HARNESS/254/56 5");
    let peer = async {
        let wire = pci_line(&mut remote_read).await;
        assert_eq!(&wire[..wire.len() - 2], b"\\460500A3FF0027EC");
        let confirmation = wire[wire.len() - 2];
        remote_write.write_all(&[confirmation, b'.']).await.unwrap();
    };
    let (response, ()) = tokio::join!(all, peer);
    assert_eq!(response.status, 200, "{response:?}");
    assert_eq!(response.final_text, "200 OK");
    assert!(service.observed_labels.lock().await.observations.is_empty());
    assert!(
        events.try_recv().is_err(),
        "native LABEL CLEAR does not emit a synthetic event"
    );

    // Native C-Gate considers either correlated PCI confirmation outcome to
    // complete this command. No unit ACK/readback follows the confirmation.
    let one = service.handle(&mut client, "[2] LABEL CLEAR //HARNESS/254/202 5 8");
    let peer = async {
        let wire = pci_line(&mut remote_read).await;
        assert_eq!(&wire[..wire.len() - 2], b"\\460500A4FF006608A4");
        let confirmation = wire[wire.len() - 2];
        remote_write.write_all(&[confirmation, b'#']).await.unwrap();
    };
    let (response, ()) = tokio::join!(one, peer);
    assert_eq!(response.status, 200, "{response:?}");
    assert_eq!(response.final_text, "200 OK");
    assert!(
        events.try_recv().is_err(),
        "keyed native LABEL CLEAR does not emit a synthetic event"
    );

    let missing = service.handle(&mut client, "[3] LABEL CLEAR //HARNESS/254/95 5 1");
    let peer = async {
        let wire = pci_line(&mut remote_read).await;
        assert_eq!(&wire[..wire.len() - 2], b"\\460500A4FF006601AB");
        tokio::time::advance(Duration::from_secs(2)).await;
        tokio::task::yield_now().await;
    };
    let (response, ()) = tokio::join!(missing, peer);
    assert_eq!(response.status, 408, "{response:?}");
    assert!(
        response
            .final_text
            .starts_with("408 //HARNESS/254/95 (command failed:"),
        "{response:?}"
    );
    let mut unexpected = Vec::new();
    assert!(
        tokio::time::timeout(
            Duration::from_millis(1),
            remote_read.read_until(b'\r', &mut unexpected)
        )
        .await
        .is_err(),
        "LABEL CLEAR must not replay after a missing confirmation: {unexpected:?}"
    );

    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn physical_label_clear_parser_rejects_bad_scope_and_values_without_io() {
    let path = state_path();
    let (pci, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let mut client = ClientState::default();
    for command in [
        "[1] LABEL CLEAR",
        "[2] LABEL CLEAR //HARNESS/254/56",
        "[3] LABEL CLEAR //HARNESS/254/56 5 1 extra",
        "[4] LABEL CLEAR //OTHER/254/56 5",
        "[5] LABEL CLEAR //HARNESS/253/56 5",
        "[6] LABEL CLEAR //HARNESS/254/25 5",
        "[7] LABEL CLEAR //HARNESS/254/56 256",
        "[8] LABEL CLEAR //HARNESS/254/56 unit",
        "[9] LABEL CLEAR //HARNESS/254/56 5 0",
        "[10] LABEL CLEAR //HARNESS/254/56 5 9",
        "[11] LABEL CLEAR //HARNESS/254/56 5 key",
    ] {
        let response = service.handle(&mut client, command).await;
        assert!(response.status >= 400, "{command}: {response:?}");
    }
    let mut byte = [0u8; 1];
    assert!(
        tokio::time::timeout(Duration::from_millis(1), remote.read(&mut byte))
            .await
            .is_err()
    );
    std::fs::remove_file(path).unwrap();
}

#[tokio::test(start_paused = true)]
async fn physical_label_kfi_commands_match_native_wire_and_responses() {
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
    async fn kfi_get_preamble<R, W>(reader: &mut R, writer: &mut W) -> u8
    where
        R: tokio::io::AsyncBufRead + Unpin,
        W: tokio::io::AsyncWrite + Unpin,
    {
        for expected in [
            b"\\460500A3FF00090A".as_slice(),
            b"\\460500A5FF0082001C73".as_slice(),
            b"\\460500A5FF008404FF8A".as_slice(),
        ] {
            let request = pci_line(reader).await;
            assert_eq!(&request[..request.len() - 2], expected);
            let code = request[request.len() - 2];
            writer.write_all(&[code, b'.']).await.unwrap();
            pci_reply(writer, 5, &[0x32, 0xff, 0]).await;
        }
        let request = pci_line(reader).await;
        assert_eq!(&request[..request.len() - 2], b"\\460500213D57");
        request[request.len() - 2]
    }
    async fn kfi_reply<W: tokio::io::AsyncWrite + Unpin>(
        writer: &mut W,
        source: u8,
        packed: [u8; 4],
    ) {
        let mut cal = vec![0x8d, cbus_protocol::kfi::ATTRIBUTE, 0x80];
        cal.extend_from_slice(&packed);
        cal.extend_from_slice(&[0; 7]);
        pci_reply(writer, source, &cal).await;
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
    let mut client = ClientState::default();
    let get = service.handle(&mut client, "[1] LABEL KFIGET //HARNESS/254/56 5");
    let peer = async {
        let code = kfi_get_preamble(&mut remote_read, &mut remote_write).await;
        // Wrong-source data is unrelated and must not complete the command.
        kfi_reply(&mut remote_write, 4, [0xff; 4]).await;
        kfi_reply(&mut remote_write, 5, [0x21, 0x43, 0x65, 0x87]).await;
        remote_write.write_all(&[code, b'.']).await.unwrap();
        tokio::time::advance(Duration::from_secs(2)).await;
        tokio::task::yield_now().await;
    };
    let (response, ()) = tokio::join!(get, peer);
    assert_eq!(response.status, 300, "{response:?}");
    assert_eq!(
        response.lines,
        vec![
            "300-kfi1=1",
            "300-kfi2=2",
            "300-kfi3=3",
            "300-kfi4=4",
            "300-kfi5=5",
            "300-kfi6=6",
            "300-kfi7=7",
        ]
    );
    assert_eq!(response.final_text, "300 kfi8=8");

    let set = service.handle(
        &mut client,
        "[2] LABEL KFISET //HARNESS/254/56 5 1 2 3 4 5 6 7 8",
    );
    let peer = async {
        for expected in [
            b"\\460500A3FF00090A".as_slice(),
            b"\\460500A5FF0084214329".as_slice(),
            b"\\460500A5FF00846587A1".as_slice(),
            b"\\460500A4FF006BACFB".as_slice(),
        ] {
            let request = pci_line(&mut remote_read).await;
            assert_eq!(&request[..request.len() - 2], expected);
            let code = request[request.len() - 2];
            remote_write.write_all(&[code, b'.']).await.unwrap();
            pci_reply(&mut remote_write, 5, &[0x32, 0xff, 0]).await;
        }
    };
    let (response, ()) = tokio::join!(set, peer);
    assert_eq!(response.status, 200, "{response:?}");

    // Decompiled kz treats the application as a LabelSupportingApplication
    // scope/class check. kv receives no application ID and intentionally uses
    // the same fixed 0x1c selector for this non-Lighting application.
    let no_response = service.handle(&mut client, "[3] LABEL KFIGET //HARNESS/254/202 5");
    let peer = async {
        let code = kfi_get_preamble(&mut remote_read, &mut remote_write).await;
        remote_write.write_all(&[code, b'.']).await.unwrap();
        tokio::time::advance(Duration::from_secs(2)).await;
        tokio::task::yield_now().await;
    };
    let (response, ()) = tokio::join!(no_response, peer);
    assert_eq!(response.status, 524);
    assert_eq!(response.final_text, "524 No response.");

    let multiple = service.handle(&mut client, "[4] LABEL KFIGET //HARNESS/254/56 5");
    let peer = async {
        let code = kfi_get_preamble(&mut remote_read, &mut remote_write).await;
        remote_write.write_all(&[code, b'.']).await.unwrap();
        kfi_reply(&mut remote_write, 5, [0x21, 0x43, 0x65, 0x87]).await;
        kfi_reply(&mut remote_write, 5, [0x10, 0x32, 0x54, 0x76]).await;
    };
    let (response, ()) = tokio::join!(multiple, peer);
    assert_eq!(response.status, 524);
    assert_eq!(response.final_text, "524 Too many responses.");

    // Decompiled command wrappers map setup/write failures through
    // MethodException to the native 408 application-scoped envelope.
    let rejected = service.handle(
        &mut client,
        "[5] LABEL KFISET //HARNESS/254/56 5 1 2 3 4 5 6 7 8",
    );
    let peer = async {
        let request = pci_line(&mut remote_read).await;
        assert_eq!(&request[..request.len() - 2], b"\\460500A3FF00090A");
        let code = request[request.len() - 2];
        remote_write.write_all(&[code, b'.']).await.unwrap();
        pci_reply(&mut remote_write, 5, &[0x32, 0xff, 0]).await;

        let request = pci_line(&mut remote_read).await;
        assert_eq!(&request[..request.len() - 2], b"\\460500A5FF0084214329");
        let code = request[request.len() - 2];
        remote_write.write_all(&[code, b'.']).await.unwrap();
        pci_reply(&mut remote_write, 5, &[0x3b, 0xff, 0]).await;
    };
    let (response, ()) = tokio::join!(rejected, peer);
    assert_eq!(response.status, 408);
    assert!(
        response
            .final_text
            .starts_with("408 //HARNESS/254/56 (command failed:"),
        "{response:?}"
    );
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn physical_label_kfi_parser_rejects_bad_arity_scope_and_values_without_io() {
    let path = state_path();
    let (pci, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let mut client = ClientState::default();
    for command in [
        "[1] LABEL KFIGET //HARNESS/254/56",
        "[2] LABEL KFIGET //HARNESS/254/56 5 extra",
        "[3] LABEL KFIGET //OTHER/254/56 5",
        "[4] LABEL KFIGET //HARNESS/254/25 5",
        "[5] LABEL KFIGET //HARNESS/254/56 256",
        "[6] LABEL KFISET //HARNESS/254/56 5 0 1 2 3 4 5 6",
        "[7] LABEL KFISET //HARNESS/254/56 5 0 1 2 3 4 5 6 16",
        "[8] LABEL KFISET //HARNESS/254/56 5 0 1 2 3 4 5 6 seven",
        "[9] LABEL KFISET //HARNESS/254/56 5 0 1 2 3 4 5 6 7 extra",
    ] {
        let response = service.handle(&mut client, command).await;
        assert!(response.status >= 400, "{command}: {response:?}");
    }
    let mut byte = [0u8; 1];
    assert!(
        tokio::time::timeout(Duration::from_millis(1), remote.read(&mut byte))
            .await
            .is_err()
    );
    std::fs::remove_file(path).unwrap();
}

/// Broader native UNRAVEL shapes remain fail-closed until cycles, occupied
/// displacement, bridges and native fallback have equivalent evidence.
#[tokio::test]
async fn broader_net_unravel_shapes_fail_closed() {
    let path = state_path();
    let (pci, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let mut client = ClientState::default();
    for line in [
        "[1] NET UNRAVEL //HARNESS/254",
        "[2] NET UNRAVELUNIT //HARNESS/254 20",
    ] {
        let response = service.handle(&mut client, line).await;
        assert_eq!(response.status, 502, "{line}");
        assert!(response.final_text.contains("requires NET UNRAVELUNIT"));
    }
    assert_eq!(
        service.handle(&mut client, "[3] NET UNRAVEL").await.status,
        400
    );
    std::fs::remove_file(path).unwrap();
}

#[tokio::test(start_paused = true)]
async fn bounded_matchdb_unravel_uses_selected_serial_and_verifies_full_inventory() {
    async fn pci_line<R: tokio::io::AsyncBufRead + Unpin>(reader: &mut R) -> Vec<u8> {
        let mut line = Vec::new();
        reader.read_until(b'\r', &mut line).await.unwrap();
        line
    }
    async fn direct_reply<W: tokio::io::AsyncWrite + Unpin>(
        writer: &mut W,
        source: u8,
        cal: &[u8],
    ) {
        let mut bytes = vec![0x86, source, 0x10, 0x00];
        bytes.extend_from_slice(cal);
        let sum = bytes.iter().fold(0u8, |sum, byte| sum.wrapping_add(*byte));
        bytes.push(0u8.wrapping_sub(sum));
        let mut wire = hex::encode_upper(bytes).into_bytes();
        wire.extend_from_slice(b"\r\n");
        writer.write_all(&wire).await.unwrap();
    }
    fn packed(serial: &str) -> [u8; 4] {
        cbus_protocol::serial_address::parse_native_serial(serial)
            .unwrap()
            .packed
    }
    fn identity(serial: &str, address: u8) -> Vec<u8> {
        let mut data = vec![0x38, 0xff, 0xff, 0xff, 0xff];
        data.extend_from_slice(&packed(serial));
        data.extend_from_slice(&[0xa2, 0, address]);
        data
    }
    fn mmi_block(start: u8, count: usize, present: &[usize]) -> Vec<u8> {
        let mut states = vec![0u8; count];
        for address in present {
            states[*address - usize::from(start)] = 1;
        }
        let mut wire = cbus_protocol::packet::Packet::StandardStatus {
            application: 0xff,
            block_start: start,
            states,
        }
        .encode_packet()
        .unwrap();
        wire.extend_from_slice(b"\r\n");
        wire
    }
    async fn mmi<R, W>(reader: &mut R, writer: &mut W, present: &[usize])
    where
        R: tokio::io::AsyncBufRead + Unpin,
        W: tokio::io::AsyncWrite + Unpin,
    {
        let request = pci_line(reader).await;
        assert!(request.starts_with(b"\\05FF00FAFF"), "{request:?}");
        let code = request[request.len() - 2];
        writer.write_all(&[code, b'.']).await.unwrap();
        for (start, count) in [(0, 88), (88, 88), (176, 80)] {
            let block_present = present
                .iter()
                .copied()
                .filter(|address| (start..start + count).contains(address))
                .collect::<Vec<_>>();
            writer
                .write_all(&mmi_block(start as u8, count, &block_present))
                .await
                .unwrap();
        }
        tokio::task::yield_now().await;
    }
    async fn identify<R, W>(reader: &mut R, writer: &mut W, address: u8, serials: &[&str])
    where
        R: tokio::io::AsyncBufRead + Unpin,
        W: tokio::io::AsyncWrite + Unpin,
    {
        let request = pci_line(reader).await;
        assert!(request.starts_with(format!("\\46{address:02X}002104").as_bytes()));
        let code = request[request.len() - 2];
        writer.write_all(&[code, b'.']).await.unwrap();
        for serial in serials {
            let mut cal = vec![0x8d, 4];
            cal.extend_from_slice(&identity(serial, address));
            direct_reply(writer, address, &cal).await;
        }
        tokio::time::advance(Duration::from_secs(2)).await;
        tokio::task::yield_now().await;
    }
    async fn local_options<R, W>(reader: &mut R, writer: &mut W)
    where
        R: tokio::io::AsyncBufRead + Unpin,
        W: tokio::io::AsyncWrite + Unpin,
    {
        let request = pci_line(reader).await;
        assert!(request.starts_with(b"\\4610001A4201"), "{request:?}");
        direct_reply(writer, 16, &[0x82, 0x42, 5]).await;
    }
    async fn selected<R, W>(reader: &mut R, writer: &mut W, serial: &str, destination: u8)
    where
        R: tokio::io::AsyncBufRead + Unpin,
        W: tokio::io::AsyncWrite + Unpin,
    {
        let request = pci_line(reader).await;
        assert!(request.starts_with(b"\\05FF000F00"), "{request:?}");
        let encoded_serial = hex::encode_upper(packed(serial));
        assert!(request
            .windows(encoded_serial.len())
            .any(|window| window == encoded_serial.as_bytes()));
        let code = request[request.len() - 2];
        writer.write_all(&[code, b'.']).await.unwrap();
        let mut cal = vec![0x87, 0];
        cal.extend_from_slice(&packed(serial));
        cal.extend_from_slice(&[0, 0]);
        direct_reply(writer, destination, &cal).await;
        tokio::time::advance(Duration::from_secs(2)).await;
        tokio::task::yield_now().await;
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
        for (address, serial, unit_type) in [
            (6, "101136.1558", "KEYE1"),
            (7, "101136.1559", "KEYE1"),
            (16, "100966.1187", "PC_CNI"),
        ] {
            let mut unit = Unit::blank(address, "");
            unit.serial = serial.to_string();
            unit.unit_type = unit_type.to_string();
            unit.firmware = "2.5.00".to_string();
            network.units.insert(address, unit);
        }
    }
    let unravel = tokio::spawn({
        let service = service.clone();
        async move {
            service
                .handle(
                    &mut ClientState::default(),
                    "[1] NET UNRAVELUNIT //HARNESS/254 255 MATCHDB",
                )
                .await
        }
    });

    mmi(&mut remote_read, &mut remote_write, &[16, 255]).await;
    identify(&mut remote_read, &mut remote_write, 16, &["100966.1187"]).await;
    identify(
        &mut remote_read,
        &mut remote_write,
        255,
        &["101136.1558", "101136.1559"],
    )
    .await;
    local_options(&mut remote_read, &mut remote_write).await;
    identify(&mut remote_read, &mut remote_write, 6, &[]).await;
    identify(&mut remote_read, &mut remote_write, 7, &[]).await;

    selected(&mut remote_read, &mut remote_write, "101136.1558", 6).await;
    identify(&mut remote_read, &mut remote_write, 6, &["101136.1558"]).await;
    selected(&mut remote_read, &mut remote_write, "101136.1559", 7).await;
    identify(&mut remote_read, &mut remote_write, 7, &["101136.1559"]).await;

    mmi(&mut remote_read, &mut remote_write, &[6, 7, 16]).await;
    identify(&mut remote_read, &mut remote_write, 6, &["101136.1558"]).await;
    identify(&mut remote_read, &mut remote_write, 7, &["101136.1559"]).await;
    identify(&mut remote_read, &mut remote_write, 16, &["100966.1187"]).await;
    local_options(&mut remote_read, &mut remote_write).await;

    let response = unravel.await.unwrap();
    assert_eq!(response.status, 200, "{}", response.final_text);
    let model = service.model.lock().await;
    let network = &model.projects["HARNESS"].networks[&254];
    assert!(!network.physical.contains_key(&255));
    assert_eq!(network.physical[&6].serial, "101136.1558");
    assert_eq!(network.physical[&7].serial, "101136.1559");
    assert_eq!(network.physical[&16].serial, "100966.1187");
    assert_eq!(network.units[&6].address, 6);
    assert_eq!(network.units[&7].address, 7);
    drop(model);
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
    pci_reply(&mut remote_write, 5, &[0x3b, 0x30, 0x00]).await;

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

    // The FIRST STORE receives the matching tagged NAK, so no write is ever
    // confirmed. Beta is never attempted.
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\460500A42000"), "{request:?}");
    pci_reply(&mut remote_write, 5, &[0x3b, 0x20, 0x00]).await;

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

    // The Paged STORE then fails (page select succeeds, tagged STORE receives
    // its matching NAK). The shared counter must still report the one
    // confirmed Standard write.
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\4605003901"), "{request:?}");
    pci_reply(&mut remote_write, 5, &[0x81, 0x01]).await;
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\460500A40000"), "{request:?}");
    pci_reply(&mut remote_write, 5, &[0x3b, 0x00, 0x00]).await;

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
    pci_reply(&mut remote_write, 5, &[0x3b, 0x40, 0x00]).await;

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

    // Cleanup runs via the PpSaveCleanup drop-guard (tag-filter test).
}

/// P3d: physical NET SYNC that observes MULTIPLE distinct serials at one
/// address must surface the conflict on the event channel instead of
/// silently collapsing the stored serial to "". The response stays 200;
/// the scalar snapshot keeps "" while the sorted duplicate set is retained
/// on `serial_alternates`.
#[tokio::test(start_paused = true)]
async fn physical_net_sync_surfaces_duplicate_serial_conflict_on_events() {
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
    fn mmi_block(start: u8, count: usize, present: &[usize]) -> Vec<u8> {
        let mut states = vec![0u8; count];
        for address in present {
            states[*address - usize::from(start)] = 1;
        }
        let mut wire = cbus_protocol::packet::Packet::StandardStatus {
            application: 0xff,
            block_start: start,
            states,
        }
        .encode_packet()
        .unwrap();
        wire.extend_from_slice(b"\r\n");
        wire
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
    let mut events = service.events.subscribe();
    let syncing = tokio::spawn({
        let service = service.clone();
        async move {
            service
                .handle(&mut ClientState::default(), "[1] NET SYNC //HARNESS/254")
                .await
        }
    });

    // Local-interface discovery: the fixture has no PC_PCI/PC_CNI unit.
    assert_eq!(pci_line(&mut remote_read).await, b"@1A2001\r");
    remote_write.write_all(b"8220104E\r\n").await.unwrap();
    tokio::task::yield_now().await;

    // Installation MMI: only address 5 is present.
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\05FF00FAFF"), "{request:?}");
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    remote_write
        .write_all(&mmi_block(0, 88, &[5]))
        .await
        .unwrap();
    remote_write
        .write_all(&mmi_block(88, 88, &[]))
        .await
        .unwrap();
    remote_write
        .write_all(&mmi_block(176, 80, &[]))
        .await
        .unwrap();
    tokio::task::yield_now().await;

    // Unit type + firmware via identify_first (confirm, then first reply).
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
        &[0x87, 0x01, b'K', b'E', b'Y', b'G', b'L', b'5'],
    )
    .await;
    tokio::task::yield_now().await;
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
        &[0x87, 0x02, b'5', b'.', b'5', b'.', b'0', b'0'],
    )
    .await;
    tokio::task::yield_now().await;

    // Serial probe returns TWO distinct valid IDENTIFY4 replies.
    let first = [
        0x38, 0xff, 0xff, 0xff, 0xff, 0x18, 0xb1, 0x06, 0x16, 0xa2, 0x00, 0x05,
    ];
    let mut second = first;
    second[8] = 0x17;
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\4605002104"), "{request:?}");
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    let mut first_cal = vec![0x8d, 4];
    first_cal.extend_from_slice(&first);
    let mut second_cal = vec![0x8d, 4];
    second_cal.extend_from_slice(&second);
    pci_reply(&mut remote_write, 5, &first_cal).await;
    tokio::time::advance(Duration::from_secs(1)).await;
    tokio::task::yield_now().await;
    assert!(
        !syncing.is_finished(),
        "quiet interval must still be open after the first serial reply"
    );
    pci_reply(&mut remote_write, 5, &second_cal).await;
    tokio::time::advance(Duration::from_secs(2)).await;
    tokio::task::yield_now().await;

    // Retained classfile order is exact: extended FirmwareVersion from
    // parameter 0xFB/9, Application/Application2 from OEM address 16/2,
    // then WidgetGroups from parameter 0xFA/44.
    assert_eq!(pci_line(&mut remote_read).await, b"\\4605001AFB0997\r");
    let firmware = cbus_protocol::Cal::Reply {
        parameter: 0xfb,
        data: b"01.05.00\0".to_vec(),
    }
    .encode();
    pci_reply(&mut remote_write, 5, &firmware).await;

    assert_eq!(
        pci_line(&mut remote_read).await,
        b"\\46050900A400411000B7\r"
    );
    pci_reply(&mut remote_write, 5, &[0x32, 0, 0x41]).await;
    assert_eq!(pci_line(&mut remote_read).await, b"\\460509001A01028F\r");
    pci_reply(&mut remote_write, 5, &[0x83, 1, 56, 255]).await;

    assert_eq!(pci_line(&mut remote_read).await, b"\\4605001AFA2C75\r");
    let widget_bytes = (0..44u8).collect::<Vec<_>>();
    for fragment in widget_bytes.chunks(22) {
        let cal = cbus_protocol::Cal::Reply {
            parameter: 0xfa,
            data: fragment.to_vec(),
        }
        .encode();
        pci_reply(&mut remote_write, 5, &cal).await;
    }

    let response = syncing.await.unwrap();
    assert_eq!(
        response.status, 200,
        "conflict must not fail SYNC: {response:?}"
    );

    // The scalar stays collapsed (SerialNumber getter/SET semantics
    // unchanged) while the duplicate set is retained in memory, sorted.
    let model = service.model.lock().await;
    let snapshot = model.projects["HARNESS"].networks[&254]
        .physical
        .get(&5)
        .expect("address 5 was present in the scripted MMI");
    assert_eq!(
        snapshot.serial, "",
        "stored serial stays collapsed: {snapshot:?}"
    );
    assert_eq!(
        snapshot.serial_alternates,
        vec!["101136.1558".to_string(), "101136.1559".to_string()],
        "duplicate set must be retained sorted: {snapshot:?}"
    );
    assert_eq!(snapshot.unit_type, "KEYGL5");
    assert_eq!(snapshot.firmware, "5.5.00");
    assert_eq!(snapshot.field("Version"), "5.5.00");
    assert_eq!(snapshot.field("FirmwareVersion"), "01.05.00");
    assert_eq!(snapshot.field("Application"), "56");
    assert_eq!(snapshot.field("Application2"), "255");
    assert_eq!(
        snapshot.field("WidgetGroups"),
        (0..44)
            .map(|value| value.to_string())
            .collect::<Vec<_>>()
            .join(",")
    );
    let configured = &model.projects["HARNESS"].networks[&254].units[&5];
    assert_eq!(configured.unit_type, "KEYGL5");
    assert_eq!(configured.field("FirmwareVersion"), "5.5.00");
    drop(model);

    let get = service
        .handle(
            &mut ClientState::default(),
            "[1g] GET //HARNESS/254/p/5 WidgetGroups",
        )
        .await;
    assert_eq!(get.status, 300);
    assert_eq!(
        get.final_text,
        format!(
            "300 //HARNESS/254/p/5: WidgetGroups={}",
            (0..44)
                .map(|value| value.to_string())
                .collect::<Vec<_>>()
                .join(",")
        )
    );
    for (sequence, field, value) in [
        ("1f", "FirmwareVersion", "01.05.00"),
        ("1v", "Version", "5.5.00"),
        ("1a", "Application", "56"),
        ("1a2", "Application2", "255"),
    ] {
        let get = service
            .handle(
                &mut ClientState::default(),
                &format!("[{sequence}] GET //HARNESS/254/p/5 {field}"),
            )
            .await;
        assert_eq!(get.status, 300, "{field}: {get:?}");
        assert_eq!(
            get.final_text,
            format!("300 //HARNESS/254/p/5: {field}={value}")
        );
    }

    let mut seen = Vec::new();
    while let Ok(event) = events.try_recv() {
        seen.push(event);
    }
    assert!(
        seen.iter().any(|event| event.contains("sync ok")),
        "sync-ok event must still be emitted: {seen:?}"
    );
    assert!(
        seen.iter()
            .any(|event| event == "#e# net 254 sync duplicate 5 101136.1558 101136.1559"),
        "RED: no exact duplicate event with sorted serials: {seen:?}"
    );
    let duplicate_pos = seen
        .iter()
        .position(|event| event == "#e# net 254 sync duplicate 5 101136.1558 101136.1559")
        .expect("exact duplicate event must be present");
    let ok_pos = seen
        .iter()
        .position(|event| event == "#e# net 254 sync ok")
        .expect("sync-ok event must be present");
    assert!(
        duplicate_pos < ok_pos,
        "duplicate event must precede sync ok: {seen:?}"
    );

    // A later optional 0xFB timeout keeps a valid identity SYNC successful.
    // It faults the programming lane before the remaining optional reads, and
    // commit invalidates every older eDLT-only volatile property rather than
    // serving stale values or substituting IDENTIFY2 for FirmwareVersion.
    let syncing_again = tokio::spawn({
        let service = service.clone();
        async move {
            service
                .handle(&mut ClientState::default(), "[2] NET SYNC //HARNESS/254")
                .await
        }
    });
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\05FF00FAFF"), "{request:?}");
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    remote_write
        .write_all(&mmi_block(0, 88, &[5]))
        .await
        .unwrap();
    remote_write
        .write_all(&mmi_block(88, 88, &[]))
        .await
        .unwrap();
    remote_write
        .write_all(&mmi_block(176, 80, &[]))
        .await
        .unwrap();

    let request = pci_line(&mut remote_read).await;
    assert!(request.windows(4).any(|window| window == b"2101"));
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    pci_reply(
        &mut remote_write,
        5,
        &[0x87, 0x01, b'K', b'E', b'Y', b'G', b'L', b'5'],
    )
    .await;
    let request = pci_line(&mut remote_read).await;
    assert!(request.windows(4).any(|window| window == b"2102"));
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    pci_reply(
        &mut remote_write,
        5,
        &[0x87, 0x02, b'5', b'.', b'5', b'.', b'0', b'0'],
    )
    .await;
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\4605002104"), "{request:?}");
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    tokio::time::advance(Duration::from_secs(2)).await;
    tokio::task::yield_now().await;
    assert_eq!(pci_line(&mut remote_read).await, b"\\4605001AFB0997\r");
    tokio::time::advance(Duration::from_secs(10)).await;
    tokio::task::yield_now().await;
    let response = syncing_again.await.unwrap();
    assert_eq!(
        response.status, 200,
        "optional eDLT metadata failure: {response:?}"
    );
    let model = service.model.lock().await;
    let snapshot = &model.projects["HARNESS"].networks[&254].physical[&5];
    assert_eq!(snapshot.unit_type, "KEYGL5");
    assert_eq!(snapshot.field("Version"), "5.5.00");
    for field in [
        "FirmwareVersion",
        "Application",
        "Application2",
        "WidgetGroups",
    ] {
        assert!(
            !snapshot.fields.contains_key(field),
            "stale {field}: {snapshot:?}"
        );
    }
    drop(model);
    for (sequence, field) in [
        ("2f", "FirmwareVersion"),
        ("2a", "Application"),
        ("2a2", "Application2"),
        ("2g", "WidgetGroups"),
    ] {
        assert_eq!(
            service
                .handle(
                    &mut ClientState::default(),
                    &format!("[{sequence}] GET //HARNESS/254/p/5 {field}"),
                )
                .await
                .status,
            404,
            "stale {field} must be unavailable"
        );
    }
    let version = service
        .handle(
            &mut ClientState::default(),
            "[2v] GET //HARNESS/254/p/5 Version",
        )
        .await;
    assert_eq!(version.status, 300);
    assert!(version.final_text.ends_with("Version=5.5.00"));
    assert!(service
        .pci
        .read()
        .await
        .read_edlt_extended_firmware(5)
        .await
        .unwrap_err()
        .to_string()
        .contains("needs reconnect"));

    std::fs::remove_file(path).unwrap();
}

#[derive(Clone, Copy)]
enum OptionalEdltFailure {
    ApplicationRecall,
    WidgetGroups,
}

async fn run_partial_edlt_sync_failure(failure: OptionalEdltFailure) -> Unit {
    async fn line<R: tokio::io::AsyncBufRead + Unpin>(reader: &mut R) -> Vec<u8> {
        let mut line = Vec::new();
        reader.read_until(b'\r', &mut line).await.unwrap();
        line
    }
    async fn reply<W: tokio::io::AsyncWrite + Unpin>(writer: &mut W, source: u8, cal: &[u8]) {
        let mut bytes = vec![0x86, source, 0x10, 0x00];
        bytes.extend_from_slice(cal);
        let sum = bytes.iter().fold(0u8, |sum, byte| sum.wrapping_add(*byte));
        bytes.push(0u8.wrapping_sub(sum));
        let mut wire = hex::encode_upper(bytes).into_bytes();
        wire.extend_from_slice(b"\r\n");
        writer.write_all(&wire).await.unwrap();
    }
    fn mmi(start: u8, count: usize, present: &[usize]) -> Vec<u8> {
        let mut states = vec![0u8; count];
        for address in present {
            states[*address - usize::from(start)] = 1;
        }
        let mut wire = cbus_protocol::Packet::StandardStatus {
            application: 0xff,
            block_start: start,
            states,
        }
        .encode_packet()
        .unwrap();
        wire.extend_from_slice(b"\r\n");
        wire
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
        line(&mut remote_read).await;
    }
    reset.await.unwrap().unwrap();

    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let mut stale = Unit::blank(5, "");
    stale.unit_type = "KEYGL5".into();
    stale.firmware = "old-identify".into();
    for (field, value) in [
        ("FirmwareVersion", "old-extended"),
        ("Application", "1"),
        ("Application2", "2"),
        ("WidgetGroups", "old-widget-groups"),
    ] {
        stale.fields.insert(field.into(), value.into());
    }
    service
        .model
        .lock()
        .await
        .projects
        .get_mut("HARNESS")
        .unwrap()
        .networks
        .get_mut(&254)
        .unwrap()
        .physical
        .insert(5, stale);

    let syncing = tokio::spawn({
        let service = service.clone();
        async move {
            service
                .handle(&mut ClientState::default(), "[p] NET SYNC //HARNESS/254")
                .await
        }
    });

    assert_eq!(line(&mut remote_read).await, b"@1A2001\r");
    remote_write.write_all(b"8220104E\r\n").await.unwrap();
    let request = line(&mut remote_read).await;
    assert!(request.starts_with(b"\\05FF00FAFF"), "{request:?}");
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    for block in [mmi(0, 88, &[5]), mmi(88, 88, &[]), mmi(176, 80, &[])] {
        remote_write.write_all(&block).await.unwrap();
    }

    for (attribute, value) in [(1, &b"KEYGL5"[..]), (2, &b"5.5.00"[..])] {
        let request = line(&mut remote_read).await;
        assert!(
            request
                .windows(4)
                .any(|window| window == [0x32, 0x31, 0x30, b'0' + attribute]),
            "{request:?}"
        );
        let code = request[request.len() - 2];
        remote_write.write_all(&[code, b'.']).await.unwrap();
        let mut cal = vec![0x80 | (value.len() as u8 + 1), attribute];
        cal.extend_from_slice(value);
        reply(&mut remote_write, 5, &cal).await;
    }

    let request = line(&mut remote_read).await;
    assert!(request.starts_with(b"\\4605002104"), "{request:?}");
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    let identity = [
        0x38, 0xff, 0xff, 0xff, 0xff, 0x18, 0xb1, 0x06, 0x16, 0xa2, 0x00, 0x05,
    ];
    let mut cal = vec![0x8d, 4];
    cal.extend_from_slice(&identity);
    reply(&mut remote_write, 5, &cal).await;
    tokio::time::advance(Duration::from_secs(2)).await;
    tokio::task::yield_now().await;

    assert_eq!(line(&mut remote_read).await, b"\\4605001AFB0997\r");
    let firmware = cbus_protocol::Cal::Reply {
        parameter: 0xfb,
        data: b"02.00.00\0".to_vec(),
    }
    .encode();
    reply(&mut remote_write, 5, &firmware).await;
    assert_eq!(line(&mut remote_read).await, b"\\46050900A400411000B7\r");
    reply(&mut remote_write, 5, &[0x32, 0, 0x41]).await;
    assert_eq!(line(&mut remote_read).await, b"\\460509001A01028F\r");

    if matches!(failure, OptionalEdltFailure::WidgetGroups) {
        reply(&mut remote_write, 5, &[0x83, 1, 57, 202]).await;
        assert_eq!(line(&mut remote_read).await, b"\\4605001AFA2C75\r");
    }
    tokio::time::advance(Duration::from_secs(10)).await;
    tokio::task::yield_now().await;

    let response = syncing.await.unwrap();
    assert_eq!(
        response.status, 200,
        "optional metadata failure: {response:?}"
    );
    assert!(
        tokio::time::timeout(Duration::from_secs(1), line(&mut remote_read))
            .await
            .is_err(),
        "a timed-out optional request must not replay or start a later request"
    );
    let snapshot =
        service.model.lock().await.projects["HARNESS"].networks[&254].physical[&5].clone();
    std::fs::remove_file(path).unwrap();
    snapshot
}

#[tokio::test(start_paused = true)]
async fn physical_net_sync_retains_only_metadata_fresh_before_each_optional_failure() {
    let application_failure =
        run_partial_edlt_sync_failure(OptionalEdltFailure::ApplicationRecall).await;
    assert_eq!(application_failure.field("Version"), "5.5.00");
    assert_eq!(
        application_failure.fields.get("FirmwareVersion"),
        Some(&"02.00.00".to_string())
    );
    for field in ["Application", "Application2", "WidgetGroups"] {
        assert!(
            !application_failure.fields.contains_key(field),
            "stale {field}: {application_failure:?}"
        );
    }

    let widget_failure = run_partial_edlt_sync_failure(OptionalEdltFailure::WidgetGroups).await;
    assert_eq!(widget_failure.field("Version"), "5.5.00");
    assert_eq!(
        widget_failure.fields.get("FirmwareVersion"),
        Some(&"02.00.00".to_string())
    );
    assert_eq!(
        widget_failure.fields.get("Application"),
        Some(&"57".to_string())
    );
    assert_eq!(
        widget_failure.fields.get("Application2"),
        Some(&"202".to_string())
    );
    assert!(
        !widget_failure.fields.contains_key("WidgetGroups"),
        "stale WidgetGroups: {widget_failure:?}"
    );
}

/// Single-serial negative pin: one IDENTIFY4 reply stores that serial and
/// emits no `sync duplicate` event.
#[tokio::test(start_paused = true)]
async fn physical_net_sync_single_serial_emits_no_duplicate_event() {
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
    fn mmi_block(start: u8, count: usize, present: &[usize]) -> Vec<u8> {
        let mut states = vec![0u8; count];
        for address in present {
            states[*address - usize::from(start)] = 1;
        }
        let mut wire = cbus_protocol::packet::Packet::StandardStatus {
            application: 0xff,
            block_start: start,
            states,
        }
        .encode_packet()
        .unwrap();
        wire.extend_from_slice(b"\r\n");
        wire
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
    // Native subtype selection comes from the configured database. A fresh
    // IDENTIFY1 that says KEYGL5 is not sufficient to probe parameter 0xFA.
    service
        .model
        .lock()
        .await
        .projects
        .get_mut("HARNESS")
        .unwrap()
        .networks
        .get_mut(&254)
        .unwrap()
        .units
        .get_mut(&5)
        .unwrap()
        .unit_type = "KEYE1".into();
    let mut events = service.events.subscribe();
    let syncing = tokio::spawn({
        let service = service.clone();
        async move {
            service
                .handle(&mut ClientState::default(), "[1] NET SYNC //HARNESS/254")
                .await
        }
    });

    // Local-interface discovery: the fixture has no PC_PCI/PC_CNI unit.
    assert_eq!(pci_line(&mut remote_read).await, b"@1A2001\r");
    remote_write.write_all(b"8220104E\r\n").await.unwrap();
    tokio::task::yield_now().await;

    // Installation MMI: only address 5 is present.
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\05FF00FAFF"), "{request:?}");
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    remote_write
        .write_all(&mmi_block(0, 88, &[5]))
        .await
        .unwrap();
    remote_write
        .write_all(&mmi_block(88, 88, &[]))
        .await
        .unwrap();
    remote_write
        .write_all(&mmi_block(176, 80, &[]))
        .await
        .unwrap();
    tokio::task::yield_now().await;

    // Unit type + firmware via identify_first (confirm, then first reply).
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
        &[0x87, 0x01, b'K', b'E', b'Y', b'G', b'L', b'5'],
    )
    .await;
    tokio::task::yield_now().await;
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
        &[0x87, 0x02, b'5', b'.', b'5', b'.', b'0', b'0'],
    )
    .await;
    tokio::task::yield_now().await;

    // Serial probe returns a SINGLE valid IDENTIFY4 reply.
    let serial = [
        0x38, 0xff, 0xff, 0xff, 0xff, 0x18, 0xb1, 0x06, 0x16, 0xa2, 0x00, 0x05,
    ];
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\4605002104"), "{request:?}");
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    let mut cal = vec![0x8d, 4];
    cal.extend_from_slice(&serial);
    pci_reply(&mut remote_write, 5, &cal).await;
    tokio::time::advance(Duration::from_secs(2)).await;
    tokio::task::yield_now().await;

    let response = syncing.await.unwrap();
    assert_eq!(response.status, 200, "single-serial SYNC: {response:?}");

    let model = service.model.lock().await;
    let snapshot = model.projects["HARNESS"].networks[&254]
        .physical
        .get(&5)
        .expect("address 5 was present in the scripted MMI");
    assert_eq!(snapshot.serial, "101136.1558", "{snapshot:?}");
    assert!(
        snapshot.serial_alternates.is_empty(),
        "single serial stores empty alternates: {snapshot:?}"
    );
    assert_eq!(
        snapshot.unit_type, "KEYGL5",
        "fresh physical identity is retained"
    );
    assert!(!snapshot.fields.contains_key("WidgetGroups"));
    drop(model);

    assert!(
        tokio::time::timeout(Duration::from_secs(1), pci_line(&mut remote_read))
            .await
            .is_err(),
        "a DB-mismatched physical KEYGL5 must not receive a WidgetGroups recall"
    );

    let mut seen = Vec::new();
    while let Ok(event) = events.try_recv() {
        seen.push(event);
    }
    assert!(
        seen.iter().any(|event| event == "#e# net 254 sync ok"),
        "sync-ok event must still be emitted: {seen:?}"
    );
    assert!(
        !seen.iter().any(|event| event.contains("sync duplicate")),
        "single serial must not emit a duplicate event: {seen:?}"
    );

    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn physical_syncnew_rejects_an_already_modeled_target_without_bus_io() {
    let path = state_path();
    let (pci, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let response = service
        .handle(
            &mut ClientState::default(),
            "[1] NET SYNCNEW //HARNESS/254 5",
        )
        .await;
    assert_eq!(response.status, 408);
    assert_eq!(
        response.final_text,
        "408 Operation failed: Unit already in model"
    );
    assert!(
        tokio::time::timeout(Duration::from_millis(25), remote.read_u8())
            .await
            .is_err(),
        "an already modeled target must fail before physical I/O"
    );
    std::fs::remove_file(path).unwrap();
}

#[tokio::test(start_paused = true)]
async fn physical_syncnew_target_runs_native_discovery_and_stores_new_identity() {
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
    fn mmi_block(start: u8, count: usize, address: usize, state: u8) -> Vec<u8> {
        let mut states = vec![0u8; count];
        if (usize::from(start)..usize::from(start) + count).contains(&address) {
            states[address - usize::from(start)] = state;
        }
        let mut wire = cbus_protocol::packet::Packet::StandardStatus {
            application: 0xff,
            block_start: start,
            states,
        }
        .encode_packet()
        .unwrap();
        wire.extend_from_slice(b"\r\n");
        wire
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
    let syncing = tokio::spawn({
        let service = service.clone();
        async move {
            service
                .handle(
                    &mut ClientState::default(),
                    "[41] NET SYNCNEW //HARNESS/254 6",
                )
                .await
        }
    });

    assert_eq!(pci_line(&mut remote_read).await, b"@1A2001\r");
    remote_write.write_all(b"8220104E\r\n").await.unwrap();
    tokio::task::yield_now().await;

    for _ in 0..5 {
        let request = pci_line(&mut remote_read).await;
        assert!(request.starts_with(b"\\05FF00FAFF"), "{request:?}");
        let code = request[request.len() - 2];
        remote_write.write_all(&[code, b'.']).await.unwrap();
        remote_write
            .write_all(&mmi_block(0, 88, 6, 1))
            .await
            .unwrap();
        remote_write
            .write_all(&mmi_block(88, 88, 6, 1))
            .await
            .unwrap();
        remote_write
            .write_all(&mmi_block(176, 80, 6, 1))
            .await
            .unwrap();
        tokio::task::yield_now().await;
    }

    for (attempt, expected) in [
        (0u8, b"\\460600118023".as_slice()),
        (1u8, b"\\460600118122".as_slice()),
        (2u8, b"\\460600118221".as_slice()),
    ] {
        let request = pci_line(&mut remote_read).await;
        assert_eq!(&request[..request.len() - 2], expected);
        let code = request[request.len() - 2];
        remote_write.write_all(&[code, b'.']).await.unwrap();
        pci_reply(&mut remote_write, 6, &[0x82, 0x80 + attempt, 0x33]).await;
        tokio::task::yield_now().await;
        tokio::time::advance(Duration::from_secs(2)).await;
        tokio::task::yield_now().await;
    }

    for (attribute, text) in [(1u8, b"KEYE1".as_slice()), (2u8, b"1.2.30".as_slice())] {
        let request = pci_line(&mut remote_read).await;
        assert!(
            request
                .windows(4)
                .any(|window| { window == format!("21{attribute:02X}").as_bytes() }),
            "{request:?}"
        );
        let code = request[request.len() - 2];
        remote_write.write_all(&[code, b'.']).await.unwrap();
        let mut cal = vec![0x81 + text.len() as u8, attribute];
        cal.extend_from_slice(text);
        pci_reply(&mut remote_write, 6, &cal).await;
        tokio::task::yield_now().await;
    }

    let serial = [
        0x38, 0xff, 0xff, 0xff, 0xff, 0x18, 0xb1, 0x06, 0x16, 0xa2, 0x00, 0x05,
    ];
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\4606002104"), "{request:?}");
    let code = request[request.len() - 2];
    let mut cal = vec![0x8d, 4];
    cal.extend_from_slice(&serial);
    pci_reply(&mut remote_write, 6, &cal).await;
    tokio::task::yield_now().await;
    remote_write.write_all(&[code, b'.']).await.unwrap();
    tokio::task::yield_now().await;
    tokio::time::advance(Duration::from_secs(2)).await;
    tokio::task::yield_now().await;

    let response = syncing.await.unwrap();
    assert_eq!(response.status, 303, "{response:?}");
    assert_eq!(response.lines.len(), 11, "{response:?}");
    assert_eq!(response.lines[0], "120-completed MMI 1 of 5.");
    assert_eq!(response.lines[4], "120-completed MMI 5 of 5.");
    assert_eq!(response.lines[5], "120-unit found");
    assert_eq!(response.lines[6], "120-duplicate test 1/3");
    assert_eq!(response.lines[10], "120-identifying unit");
    assert_eq!(
        response.final_text,
        "303 New Unit Found: address=6 type=KEYE1 version=1.2.30 serial=101136.1558"
    );
    let wire = format_response(&response);
    assert!(wire.contains("[41] 120-completed MMI 1 of 5.\n"));
    assert!(wire.ends_with(
        "[41] 303 New Unit Found: address=6 type=KEYE1 version=1.2.30 serial=101136.1558\n"
    ));

    let model = service.model.lock().await;
    let network = &model.projects["HARNESS"].networks[&254];
    assert!(!network.units.contains_key(&6));
    assert_eq!(network.physical[&6].unit_type, "KEYE1");
    assert_eq!(network.physical[&6].firmware, "1.2.30");
    assert_eq!(network.physical[&6].serial, "101136.1558");
    drop(model);
    std::fs::remove_file(path).unwrap();
}

#[tokio::test(start_paused = true)]
async fn physical_syncnew_all_reports_mmi_duplicate_and_drops_live_identity() {
    async fn pci_line<R: tokio::io::AsyncBufRead + Unpin>(reader: &mut R) -> Vec<u8> {
        let mut line = Vec::new();
        reader.read_until(b'\r', &mut line).await.unwrap();
        line
    }
    fn mmi_block(start: u8, count: usize, address: usize, state: u8) -> Vec<u8> {
        let mut states = vec![0u8; count];
        if (usize::from(start)..usize::from(start) + count).contains(&address) {
            states[address - usize::from(start)] = state;
        }
        let mut wire = cbus_protocol::packet::Packet::StandardStatus {
            application: 0xff,
            block_start: start,
            states,
        }
        .encode_packet()
        .unwrap();
        wire.extend_from_slice(b"\r\n");
        wire
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
        model
            .projects
            .get_mut("HARNESS")
            .unwrap()
            .networks
            .get_mut(&254)
            .unwrap()
            .physical
            .insert(7, Unit::blank(7, "101.7"));
    }
    let syncing = tokio::spawn({
        let service = service.clone();
        async move {
            service
                .handle(
                    &mut ClientState::default(),
                    "[42] NET SYNCNEW //HARNESS/254",
                )
                .await
        }
    });
    assert_eq!(pci_line(&mut remote_read).await, b"@1A2001\r");
    remote_write.write_all(b"8220104E\r\n").await.unwrap();
    tokio::task::yield_now().await;
    for _ in 0..5 {
        let request = pci_line(&mut remote_read).await;
        let code = request[request.len() - 2];
        remote_write.write_all(&[code, b'.']).await.unwrap();
        remote_write
            .write_all(&mmi_block(0, 88, 7, 3))
            .await
            .unwrap();
        remote_write
            .write_all(&mmi_block(88, 88, 7, 3))
            .await
            .unwrap();
        remote_write
            .write_all(&mmi_block(176, 80, 7, 3))
            .await
            .unwrap();
        tokio::task::yield_now().await;
    }
    let response = syncing.await.unwrap();
    assert_eq!(response.status, 303, "{response:?}");
    assert_eq!(response.final_text, "303 Duplicate Units Found: address=7");
    assert!(
        !service.model.lock().await.projects["HARNESS"].networks[&254]
            .physical
            .contains_key(&7)
    );
    std::fs::remove_file(path).unwrap();
}

#[tokio::test(start_paused = true)]
async fn physical_project_identify_writes_native_sixbit_parameter_and_verifies_readback() {
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
    fn mmi_block(start: u8, count: usize, addresses: &[(usize, u8)]) -> Vec<u8> {
        let mut states = vec![0u8; count];
        for &(address, state) in addresses {
            if (usize::from(start)..usize::from(start) + count).contains(&address) {
                states[address - usize::from(start)] = state;
            }
        }
        let mut wire = cbus_protocol::packet::Packet::StandardStatus {
            application: 0xff,
            block_start: start,
            states,
        }
        .encode_packet()
        .unwrap();
        wire.extend_from_slice(b"\r\n");
        wire
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
    let mut events = service.events.subscribe();
    let setting = tokio::spawn({
        let service = service.clone();
        async move {
            service
                .handle(
                    &mut ClientState::default(),
                    "[43] NET SET_PROJECT_IDENTIFY //HARNESS/254 \"?\\ ?\"",
                )
                .await
        }
    });

    // Establish the local PCI address before source-correlating IDENTIFY.
    assert_eq!(pci_line(&mut remote_read).await, b"@1A2001\r");
    remote_write.write_all(b"8220104E\r\n").await.unwrap();
    tokio::task::yield_now().await;

    // One complete, positively confirmed MMI identifies two unambiguous
    // candidates. Address 5 returns an unusable identity, so selection must
    // continue to address 6 before any STORE.
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\05FF00FAFF"), "{request:?}");
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    for block in [
        mmi_block(0, 88, &[(5, 1), (6, 1)]),
        mmi_block(88, 88, &[(5, 1), (6, 1)]),
        mmi_block(176, 80, &[(5, 1), (6, 1)]),
    ] {
        remote_write.write_all(&block).await.unwrap();
    }
    tokio::task::yield_now().await;

    let identify = pci_line(&mut remote_read).await;
    assert!(identify.starts_with(b"\\4605002101"), "{identify:?}");
    let code = identify[identify.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    pci_reply(&mut remote_write, 5, &[0x82, 1, b' ']).await;
    tokio::task::yield_now().await;

    let identify = pci_line(&mut remote_read).await;
    assert!(identify.starts_with(b"\\4606002101"), "{identify:?}");
    let code = identify[identify.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    pci_reply(
        &mut remote_write,
        6,
        &[0x86, 1, b'K', b'E', b'Y', b'E', b'1'],
    )
    .await;
    tokio::task::yield_now().await;

    // MMI state one is not sufficient evidence of a unique physical unit.
    // The service completes an IDENTIFY4 quiet window and admits the STORE
    // only when exactly one valid known serial replied.
    let identify = pci_line(&mut remote_read).await;
    assert!(identify.starts_with(b"\\4606002104"), "{identify:?}");
    let code = identify[identify.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    pci_reply(
        &mut remote_write,
        6,
        &[
            0x8d, 4, 0x38, 0xff, 0xff, 0xff, 0xff, 0x18, 0xb1, 0x06, 0x16, 0xa2, 0x00, 0x05,
        ],
    )
    .await;
    tokio::time::advance(Duration::from_secs(2)).await;
    tokio::task::yield_now().await;

    // Native parameter 35 canonicalizes both '?' and space to six-bit value
    // 30. The service accepts success only after direct RECALL returns the
    // same bytes, and its cache must reflect those verified bytes rather than
    // the non-canonical input spelling.
    assert_eq!(
        pci_line(&mut remote_read).await,
        b"\\460600A8234679E79E79E79EA7\r"
    );
    pci_reply(&mut remote_write, 6, &[0x32, 0x23, 0x46]).await;
    assert_eq!(pci_line(&mut remote_read).await, b"\\4606001A230671\r");
    pci_reply(
        &mut remote_write,
        6,
        &[0x87, 0x23, 0x79, 0xe7, 0x9e, 0x79, 0xe7, 0x9e],
    )
    .await;

    let response = setting.await.unwrap();
    assert_eq!(response.status, 200, "{response:?}");
    assert_eq!(response.final_text, "200 OK.");
    let model = service.model.lock().await;
    let network = &model.projects["HARNESS"].networks[&254];
    assert!(
        !network.units.contains_key(&6),
        "the commissioning write must not invent a database unit"
    );
    assert_eq!(network.physical[&6].unit_type, "KEYE1");
    assert_eq!(network.physical[&6].fields["ProjectName"], "        ");
    drop(model);
    let property = service
        .handle(
            &mut ClientState::default(),
            "[46] GET //HARNESS/254/p/6 ProjectName",
        )
        .await;
    assert_eq!(property.status, 300, "{property:?}");
    assert_eq!(
        property.final_text,
        "300 //HARNESS/254/p/6: ProjectName=        "
    );
    assert!(
        events.try_recv().is_err(),
        "native project-identify does not emit a synthetic event"
    );
    std::fs::remove_file(path).unwrap();
}

#[tokio::test(start_paused = true)]
async fn physical_project_identify_fails_closed_before_store_and_on_bad_readback() {
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
    fn mmi_block(start: u8, count: usize, address: usize, state: u8) -> Vec<u8> {
        let mut states = vec![0u8; count];
        if (usize::from(start)..usize::from(start) + count).contains(&address) {
            states[address - usize::from(start)] = state;
        }
        let mut wire = cbus_protocol::packet::Packet::StandardStatus {
            application: 0xff,
            block_start: start,
            states,
        }
        .encode_packet()
        .unwrap();
        wire.extend_from_slice(b"\r\n");
        wire
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

    // A loaded network that is not the service's bound physical endpoint is
    // valid in the database model, but must fail closed without returning a
    // synthetic success or issuing PCI traffic.
    let other_network = service
        .handle(
            &mut ClientState::default(),
            "[43] DBCREATENET 253 Other Cni 127.0.0.1:10002",
        )
        .await;
    assert_eq!(other_network.status, 200, "{other_network:?}");
    let unbound = service
        .handle(
            &mut ClientState::default(),
            "[43a] NET SET_PROJECT_IDENTIFY //HARNESS/253 TEST",
        )
        .await;
    assert_eq!(unbound.status, 502, "{unbound:?}");
    assert_eq!(
        unbound.final_text,
        "502 Command requires a physical backend that is not implemented"
    );
    assert!(
        tokio::time::timeout(Duration::from_millis(25), remote_read.read_u8())
            .await
            .is_err(),
        "a valid but unbound network must not issue physical I/O"
    );

    let invalid = service
        .handle(
            &mut ClientState::default(),
            "[44] NET SET_PROJECT_IDENTIFY //HARNESS/254 TOOLONG99",
        )
        .await;
    assert_eq!(invalid.status, 400, "{invalid:?}");
    assert!(
        tokio::time::timeout(Duration::from_millis(25), remote_read.read_u8())
            .await
            .is_err(),
        "invalid text must fail before physical I/O"
    );
    let bad_character = service
        .handle(
            &mut ClientState::default(),
            "[44b] NET SET_PROJECT_IDENTIFY //HARNESS/254 {",
        )
        .await;
    assert_eq!(bad_character.status, 408, "{bad_character:?}");
    assert_eq!(
        bad_character.final_text,
        "408 Operation failed: Character out of sixbit range"
    );
    assert!(
        tokio::time::timeout(Duration::from_millis(25), remote_read.read_u8())
            .await
            .is_err(),
        "six-bit encoding failure must occur before physical I/O"
    );

    let setting = tokio::spawn({
        let service = service.clone();
        async move {
            service
                .handle(
                    &mut ClientState::default(),
                    "[45] NET SET_PROJECT_IDENTIFY //HARNESS/254 TEST",
                )
                .await
        }
    });
    assert_eq!(pci_line(&mut remote_read).await, b"@1A2001\r");
    remote_write.write_all(b"8220104E\r\n").await.unwrap();
    tokio::task::yield_now().await;
    let request = pci_line(&mut remote_read).await;
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    for block in [
        mmi_block(0, 88, 6, 3),
        mmi_block(88, 88, 6, 3),
        mmi_block(176, 80, 6, 3),
    ] {
        remote_write.write_all(&block).await.unwrap();
    }
    tokio::task::yield_now().await;

    let response = setting.await.unwrap();
    assert_eq!(response.status, 408, "{response:?}");
    assert_eq!(
        response.final_text,
        "408 Operation failed: Can't find unit to set project name in"
    );
    assert!(
        tokio::time::timeout(Duration::from_millis(25), remote_read.read_u8())
            .await
            .is_err(),
        "duplicate MMI state must not issue IDENTIFY or STORE"
    );
    assert!(
        service.model.lock().await.projects["HARNESS"].networks[&254]
            .physical
            .is_empty()
    );

    // A state-one MMI address can still hide multiple physical units. Two
    // distinct serial replies must therefore abort before parameter 35 is
    // written, even though IDENTIFY1 returned a usable type.
    let duplicate_serials = tokio::spawn({
        let service = service.clone();
        async move {
            service
                .handle(
                    &mut ClientState::default(),
                    "[45b] NET SET_PROJECT_IDENTIFY //HARNESS/254 TEST",
                )
                .await
        }
    });
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\05FF00FAFF"), "{request:?}");
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    for block in [
        mmi_block(0, 88, 6, 1),
        mmi_block(88, 88, 6, 1),
        mmi_block(176, 80, 6, 1),
    ] {
        remote_write.write_all(&block).await.unwrap();
    }
    tokio::task::yield_now().await;
    let identify = pci_line(&mut remote_read).await;
    assert!(identify.starts_with(b"\\4606002101"), "{identify:?}");
    let code = identify[identify.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    pci_reply(
        &mut remote_write,
        6,
        &[0x86, 1, b'K', b'E', b'Y', b'E', b'1'],
    )
    .await;
    tokio::task::yield_now().await;
    let identify = pci_line(&mut remote_read).await;
    assert!(identify.starts_with(b"\\4606002104"), "{identify:?}");
    let code = identify[identify.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    for serial_tail in [0x16, 0x17] {
        pci_reply(
            &mut remote_write,
            6,
            &[
                0x8d,
                4,
                0x38,
                0xff,
                0xff,
                0xff,
                0xff,
                0x18,
                0xb1,
                0x06,
                serial_tail,
                0xa2,
                0x00,
                0x05,
            ],
        )
        .await;
    }
    tokio::time::advance(Duration::from_secs(2)).await;
    tokio::task::yield_now().await;
    let response = duplicate_serials.await.unwrap();
    assert_eq!(response.status, 408, "{response:?}");
    assert_eq!(
        response.final_text,
        "408 Operation failed: Can't find unit to set project name in"
    );
    assert!(
        tokio::time::timeout(Duration::from_millis(25), remote_read.read_u8())
            .await
            .is_err(),
        "multiple serial replies must not issue STORE"
    );

    // Seed an older volatile value so the failed readback below proves it is
    // invalidated rather than continuing to serve stale physical state.
    {
        let mut model = service.model.lock().await;
        let network = model
            .projects
            .get_mut("HARNESS")
            .unwrap()
            .networks
            .get_mut(&254)
            .unwrap();
        let mut unit = Unit::blank(6, "");
        unit.fields
            .insert("ProjectName".to_string(), "OLD     ".to_string());
        network.physical.insert(6, unit);
    }

    // A STORE ACK is not enough: a mismatching parameter-35 RECALL fails the
    // operation and must invalidate an older ProjectName in the physical cache.
    let mismatch = tokio::spawn({
        let service = service.clone();
        async move {
            service
                .handle(
                    &mut ClientState::default(),
                    "[46] NET SET_PROJECT_IDENTIFY //HARNESS/254 TEST",
                )
                .await
        }
    });
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\05FF00FAFF"), "{request:?}");
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    for block in [
        mmi_block(0, 88, 6, 1),
        mmi_block(88, 88, 6, 1),
        mmi_block(176, 80, 6, 1),
    ] {
        remote_write.write_all(&block).await.unwrap();
    }
    tokio::task::yield_now().await;
    let identify = pci_line(&mut remote_read).await;
    assert!(identify.starts_with(b"\\4606002101"), "{identify:?}");
    let code = identify[identify.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    pci_reply(
        &mut remote_write,
        6,
        &[0x86, 1, b'K', b'E', b'Y', b'E', b'1'],
    )
    .await;
    tokio::task::yield_now().await;
    let identify = pci_line(&mut remote_read).await;
    assert!(identify.starts_with(b"\\4606002104"), "{identify:?}");
    let code = identify[identify.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    pci_reply(
        &mut remote_write,
        6,
        &[
            0x8d, 4, 0x38, 0xff, 0xff, 0xff, 0xff, 0x18, 0xb1, 0x06, 0x16, 0xa2, 0x00, 0x05,
        ],
    )
    .await;
    tokio::time::advance(Duration::from_secs(2)).await;
    tokio::task::yield_now().await;
    assert_eq!(
        pci_line(&mut remote_read).await,
        b"\\460600A82346CE4CB379E79ED8\r"
    );
    pci_reply(&mut remote_write, 6, &[0x32, 0x23, 0x46]).await;
    assert_eq!(pci_line(&mut remote_read).await, b"\\4606001A230671\r");
    pci_reply(&mut remote_write, 6, &[0x87, 0x23, 0, 0, 0, 0, 0, 0]).await;
    let response = mismatch.await.unwrap();
    assert_eq!(response.status, 408, "{response:?}");
    assert_eq!(
        response.final_text,
        "408 Operation failed: project name save failed - store to unit failed"
    );
    let model = service.model.lock().await;
    let cached = &model.projects["HARNESS"].networks[&254].physical[&6];
    assert!(
        !cached.fields.contains_key("ProjectName"),
        "failed readback must invalidate a stale cached project identity"
    );
    drop(model);
    std::fs::remove_file(path).unwrap();
}

// Auth first-slice loopback tests (cmqttd-local shared-secret gate).
//
// Explicitly NOT native access.txt parity: no native LOGIN captures exist,
// so these tests pin the cmqttd-local contract only — `420 LOGIN failed`
// for a wrong secret (native status TBD, never 401-as-native), `200 OK`
// for LOGIN/LOGOUT session handling, and `420 LOGIN required` for gated
// programming verbs. Test secrets are throwaway literals, never site data.
const AUTH_TOKEN: &[u8] = b"throwaway-loopback-token-0123456789abcdef";

fn authed_service() -> (Arc<Service>, PathBuf) {
    let path = state_path();
    let (pci, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    service
        .set_auth_token_hash(crate::auth::sha256(AUTH_TOKEN))
        .expect("fresh service has no auth hash yet");
    (service, path)
}

fn response_text(response: &Response) -> String {
    let mut text = response.lines.join("\n");
    text.push('\n');
    text.push_str(&response.final_text);
    text
}

#[tokio::test]
async fn auth_gate_dormant_without_auth_file_is_byte_identical() {
    // No auth file configured: LOGIN/LOGOUT fall through to the generic
    // 502 exactly as before, and programming verbs stay ungated.
    let path = state_path();
    let (pci, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let mut client = ClientState::default();
    let login = service.handle(&mut client, "[1] LOGIN anything").await;
    assert_eq!(login.status, 502);
    assert_eq!(
        login.final_text, "502 Command requires a physical backend that is not implemented",
        "dormant LOGIN must be byte-identical to the generic 502"
    );
    let logout = service.handle(&mut client, "[2] LOGOUT").await;
    assert_eq!(logout.status, 502);
    assert_eq!(
        logout.final_text, "502 Command requires a physical backend that is not implemented",
        "dormant LOGOUT must be byte-identical to the generic 502"
    );
    assert_eq!(
        service
            .handle(&mut client, "[3] PP LOCK L //HARNESS/254")
            .await
            .status,
        200
    );
    std::fs::remove_file(path).ok();
}

#[tokio::test]
async fn auth_wrong_secret_denied_and_gate_holds() {
    let (service, path) = authed_service();
    let mut client = ClientState::default();
    // Wrong secret: contract status 420 (native TBD, never 401-as-native).
    let denied = service
        .handle(&mut client, "[1] LOGIN wrong-secret-value")
        .await;
    assert_eq!(denied.status, 420);
    assert!(
        denied.final_text.contains("LOGIN failed"),
        "unexpected denial text: {denied:?}"
    );
    // Programming verbs stay denied while unauthenticated.
    for command in [
        "[2] PP LOCK L //HARNESS/254",
        "[3] PP START S L",
        "[4] PP NEW S //HARNESS/254/p/5",
        "[5] PP SET S Field value",
        "[6] PP SAVE S //HARNESS/254/p/5",
        "[7] PP SAVE_TO_SOURCE S",
        "[8] PP LOAD S //HARNESS/254/p/5",
        "[9] PROJECT NEW AUTHTEST",
        "[10] PROJECT SAVE",
        "[11] DBSETSAFE //HARNESS/254/p/5/TagName Changed",
        "[12] SET //HARNESS/254/p/5 Address 6",
        "[13] LABEL CLEAREDLT //HARNESS/254/p/5",
        "[14] LABEL CLEAR //HARNESS/254/56 5",
        "[15] LABEL KFIGET //HARNESS/254/56 5",
        "[16] LABEL KFISET //HARNESS/254/56 5 0 1 2 3 4 5 6 7",
        "[17] SCENE RECORD house evening",
        "[18] DO //HARNESS/254/p/5 FactoryDefault",
        "[19] NET UNRAVELUNIT //HARNESS/254 255 MATCHDB",
        "[20] NET SET_PROJECT_IDENTIFY //HARNESS/254 TEST",
    ] {
        let response = service.handle(&mut client, command).await;
        assert_eq!(response.status, 420, "{command}: {response:?}");
        assert!(
            response.final_text.contains("LOGIN required"),
            "{command}: {response:?}"
        );
    }
    std::fs::remove_file(path).ok();
}

#[tokio::test]
async fn auth_login_unlocks_programming_and_logout_relocks() {
    let (service, path) = authed_service();
    let mut client = ClientState::default();
    assert_eq!(
        service
            .handle(&mut client, "[1] PP LOCK L //HARNESS/254")
            .await
            .status,
        420
    );
    let ok = service
        .handle(
            &mut client,
            "[2] LOGIN throwaway-loopback-token-0123456789abcdef",
        )
        .await;
    assert_eq!(ok.status, 200);
    assert_eq!(
        service
            .handle(&mut client, "[3] PP LOCK L //HARNESS/254")
            .await
            .status,
        200
    );
    assert_eq!(
        service.handle(&mut client, "[4] PP START S L").await.status,
        200
    );
    assert_eq!(service.handle(&mut client, "[5] LOGOUT").await.status, 200);
    // Session-local flag cleared: programming denied again.
    assert_eq!(
        service
            .handle(&mut client, "[6] PP LOCK M //HARNESS/254")
            .await
            .status,
        420
    );
    std::fs::remove_file(path).ok();
}

#[tokio::test]
async fn auth_second_connection_unaffected_by_first() {
    let (service, path) = authed_service();
    let mut first = ClientState::default();
    let mut second = ClientState::default();
    assert_eq!(
        service
            .handle(
                &mut first,
                "[1] LOGIN throwaway-loopback-token-0123456789abcdef"
            )
            .await
            .status,
        200
    );
    // Second connection is still unauthenticated.
    assert_eq!(
        service
            .handle(&mut second, "[2] PP LOCK L //HARNESS/254")
            .await
            .status,
        420
    );
    // First connection logging out does not touch the second, and the
    // second can still authenticate independently.
    assert_eq!(service.handle(&mut first, "[3] LOGOUT").await.status, 200);
    assert_eq!(
        service
            .handle(
                &mut second,
                "[4] LOGIN throwaway-loopback-token-0123456789abcdef"
            )
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut second, "[5] PP LOCK L //HARNESS/254")
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut first, "[6] PP LOCK M //HARNESS/254")
            .await
            .status,
        420
    );
    std::fs::remove_file(path).ok();
}

#[tokio::test]
async fn auth_failed_login_clears_flag_and_rejects_bad_arity() {
    let (service, path) = authed_service();
    let mut client = ClientState::default();
    assert_eq!(
        service
            .handle(
                &mut client,
                "[1] LOGIN throwaway-loopback-token-0123456789abcdef"
            )
            .await
            .status,
        200
    );
    // A failed LOGIN de-authenticates the connection.
    assert_eq!(
        service.handle(&mut client, "[2] LOGIN wrong").await.status,
        420
    );
    assert_eq!(
        service
            .handle(&mut client, "[3] PP LOCK L //HARNESS/254")
            .await
            .status,
        420
    );
    // LOGIN arity is strict: bare and multi-token forms are 400.
    assert_eq!(service.handle(&mut client, "[4] LOGIN").await.status, 400);
    assert_eq!(
        service.handle(&mut client, "[5] LOGIN a b").await.status,
        400
    );
    // A malformed LOGIN also de-authenticates a live session: re-login,
    // send bad arity, and the gate must hold again.
    assert_eq!(
        service
            .handle(
                &mut client,
                "[6] LOGIN throwaway-loopback-token-0123456789abcdef"
            )
            .await
            .status,
        200
    );
    assert_eq!(
        service.handle(&mut client, "[7] LOGIN a b").await.status,
        400
    );
    assert_eq!(
        service
            .handle(&mut client, "[8] PP LOCK L //HARNESS/254")
            .await
            .status,
        420
    );
    std::fs::remove_file(path).ok();
}

#[tokio::test]
async fn auth_reads_and_bus_control_stay_open() {
    // Read-only verbs and bus-control paths never require LOGIN: the gate
    // covers durable/unit/session mutation only.
    let (service, path) = authed_service();
    let mut client = ClientState::default();
    assert_eq!(
        service
            .handle(&mut client, "[1] CMQTT CAPABILITIES")
            .await
            .status,
        200
    );
    assert_eq!(
        service.handle(&mut client, "[2] PROJECT LIST").await.status,
        200
    );
    assert_eq!(
        service
            .handle(&mut client, "[3] PROJECT USE HARNESS")
            .await
            .status,
        200
    );
    // No live level observed: the read path itself answers 408, not 420.
    assert_eq!(
        service
            .handle(&mut client, "[4] GET //HARNESS/254/56/1 level")
            .await
            .status,
        408
    );
    // PP session reads are not gated (a missing session answers from the
    // model, never 420).
    let info = service.handle(&mut client, "[5] PP INFO nosuch").await;
    assert_ne!(info.status, 420, "{info:?}");
    let get = service.handle(&mut client, "[6] PP GET nosuch").await;
    assert_ne!(get.status, 420, "{get:?}");
    std::fs::remove_file(path).ok();
}

#[tokio::test]
async fn auth_secret_never_in_responses_or_events() {
    let (service, path) = authed_service();
    let mut events = service.events.subscribe();
    let mut client = ClientState::default();
    let attempts = [
        "[1] LOGIN wrong-secret-value",
        "[2] PP LOCK L //HARNESS/254",
        "[3] LOGIN throwaway-loopback-token-0123456789abcdef",
        "[4] LOGOUT",
    ];
    for command in attempts {
        let response = service.handle(&mut client, command).await;
        let text = response_text(&response);
        assert!(
            !text.contains("throwaway-loopback-token-0123456789abcdef"),
            "{command} echoed the secret: {text:?}"
        );
        assert!(
            !text.contains("wrong-secret-value"),
            "{command} echoed the candidate: {text:?}"
        );
    }
    // Neither failed logins, denials, LOGIN success nor LOGOUT emit events
    // (and therefore can never carry secret material on the event channel).
    assert!(
        events.try_recv().is_err(),
        "auth traffic must not emit bus events"
    );
    std::fs::remove_file(path).ok();
}

#[tokio::test]
async fn auth_db_project_and_scene_mutations_gate_together() {
    // The gate covers every local path that mutates durable state: DB
    // verbs, PROJECT lifecycle verbs and SCENE RECORD (persisted
    // snapshots). Post-login they serve locally again.
    let (service, path) = authed_service();
    let mut client = ClientState::default();
    assert_eq!(
        service
            .handle(
                &mut client,
                "[1] DBSETSAFE //HARNESS/254/p/5/TagName Changed"
            )
            .await
            .status,
        420
    );
    assert_eq!(
        service
            .handle(
                &mut client,
                "[2] LOGIN throwaway-loopback-token-0123456789abcdef"
            )
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(
                &mut client,
                "[3] DBSETSAFE //HARNESS/254/p/5/TagName Changed"
            )
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut client, "[4] PROJECT NEW AUTHTEST")
            .await
            .status,
        200
    );
    std::fs::remove_file(path).ok();
}
