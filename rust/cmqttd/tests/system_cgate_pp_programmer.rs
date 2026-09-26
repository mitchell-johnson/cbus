//! Real cmqttd process: maintained PP administration and PROGRAMMER queue
//! metadata use only bounded local state/catalogue data, while physical queue
//! execution and patch writes remain fail-closed. MQTT stays live throughout.

mod util;

use tokio::{
    io::{AsyncBufReadExt, AsyncWriteExt, BufReader},
    net::TcpStream,
};
use util::*;

async fn command(
    reader: &mut BufReader<tokio::net::tcp::OwnedReadHalf>,
    writer: &mut tokio::net::tcp::OwnedWriteHalf,
    tag: &str,
    text: &str,
) -> Vec<String> {
    writer
        .write_all(format!("[{tag}] {text}\r\n").as_bytes())
        .await
        .unwrap();
    let prefix = format!("[{tag}] ");
    let mut reply = Vec::new();
    loop {
        let mut line = String::new();
        assert_ne!(reader.read_line(&mut line).await.unwrap(), 0);
        let line = line.trim_end_matches(['\r', '\n']);
        let payload = line
            .strip_prefix(&prefix)
            .unwrap_or_else(|| panic!("expected {prefix:?}, got {line:?}"));
        let complete = payload.as_bytes().get(3) == Some(&b' ');
        reply.push(payload.to_string());
        if complete {
            return reply;
        }
    }
}

async fn connect(
    system: &System,
) -> (
    BufReader<tokio::net::tcp::OwnedReadHalf>,
    tokio::net::tcp::OwnedWriteHalf,
) {
    require(STARTUP, "C-Gate listener", || {
        system
            .daemon
            .stderr()
            .contains("C-Gate service listening on ")
    })
    .await;
    let address = system
        .daemon
        .stderr()
        .lines()
        .find_map(|line| line.split_once("C-Gate service listening on "))
        .map(|(_, address)| address.trim().to_string())
        .unwrap();
    let stream = TcpStream::connect(address).await.unwrap();
    let (reader, writer) = stream.into_split();
    let mut reader = BufReader::new(reader);
    let mut greeting = String::new();
    reader.read_line(&mut greeting).await.unwrap();
    assert_eq!(greeting, "201 cmqttd C-Gate service ready\r\n");
    (reader, writer)
}

fn options(state: &std::path::Path, unitspec: &std::path::Path) -> Options {
    Options {
        extra: vec![
            "--cgate-bind".into(),
            "127.0.0.1:0".into(),
            "--cgate-state".into(),
            state.to_string_lossy().into_owned(),
            "--cgate-unitspec".into(),
            unitspec.to_string_lossy().into_owned(),
        ],
        ..Default::default()
    }
}

fn write_catalogue(directory: &std::path::Path) {
    std::fs::create_dir_all(directory).unwrap();
    std::fs::write(
        directory.join("cbusunits.xml"),
        r#"<?xml version="1.0" encoding="utf-8"?>
<CBusUnits><Units><Unit><Description>System Fixture</Description><CatalogNumber>SYS-1</CatalogNumber><FirmwareRevisions><Revision><UnitType>TEST</UnitType><MinVersion>1.0</MinVersion><MaxVersion>1.9.99</MaxVersion><UnitSpecName>TEST.xml</UnitSpecName></Revision></FirmwareRevisions></Unit></Units><FileVersion>1.0</FileVersion><Author>Fixture</Author><Status>Released</Status><ApprovalDate>Today</ApprovalDate></CBusUnits>"#,
    )
    .unwrap();
    std::fs::write(
        directory.join("TEST.xml"),
        r#"<UnitSpecification><Parameters><Param><Name>First</Name><Type>int</Type><Address>$00</Address><DefaultValue>$01</DefaultValue></Param><Param><Name>Tenth</Name><Type>int</Type><Address>$09</Address><DefaultValue>$FF</DefaultValue></Param></Parameters></UnitSpecification>"#,
    )
    .unwrap();
}

#[tokio::test]
async fn pp_admin_and_programmer_are_local_native_shaped_and_restart_safe() {
    let state = cbus_test_support::proc::temp_path("cgate-pp-programmer.json");
    let unitspec = cbus_test_support::proc::temp_path("cgate-pp-programmer-unitspec");
    write_catalogue(&unitspec);

    let mut system = start_with(options(&state, &unitspec)).await;
    wait_started(&system).await;
    let (mut reader, mut writer) = connect(&system).await;

    let frames_before = system
        .pci
        .frames()
        .iter()
        .filter(|frame| !is_status_request(&frame.payload))
        .count();

    assert_eq!(
        command(&mut reader, &mut writer, "catalog", "PP CATALOG_INFO").await,
        [
            "133-SpecVersion=1.0",
            "133-Author=Fixture",
            "133-Status=Released",
            "133 ApprovalDate=Today",
        ]
    );
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "numbers",
            "PP LIST_CATALOG_NUMBERS TEST 1.2.3",
        )
        .await,
        ["133 catalogNumber=SYS-1 description=System Fixture"]
    );
    let spec = command(
        &mut reader,
        &mut writer,
        "spec",
        "PP GET_UNIT_SPEC TEST.xml",
    )
    .await;
    assert_eq!(spec.first().unwrap(), "343-Begin XML Snippet");
    assert!(spec[2].starts_with("347-<Parameters><Param><Name>First</Name>"));
    assert_eq!(spec.last().unwrap(), "344 End XML Snippet");
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "escape",
            "PP GET_UNIT_SPEC ../TEST.xml",
        )
        .await,
        ["408 Operation failed: Unit spec file ../TEST.xml not found"]
    );

    for (tag, text, expected) in [
        ("lock", "PP LOCK L //HARNESS/254", "200 OK"),
        ("start", "PP START S L", "200 OK"),
        ("new", "PP NEW S TEST 1.2.3", "200 OK"),
        ("set", "PP SET_RAW_DATA S 0 01020304", "200 OK"),
    ] {
        assert_eq!(
            command(&mut reader, &mut writer, tag, text).await,
            [expected],
            "{text}"
        );
    }
    assert_eq!(
        command(&mut reader, &mut writer, "raw", "PP GET_RAW_DATA S 0 8").await,
        ["316 RawData=0102030400000000"]
    );
    let debug = command(&mut reader, &mut writer, "debug", "PP DEBUG mem S 0").await;
    assert_eq!(debug.len(), 9);
    assert_eq!(
        debug.first().unwrap(),
        "199---------|00|01|02|03|04|05|06|07|08|09|0a|0b|0c|0d|0e|0f|"
    );
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "load-file",
            "PP LOAD_FROM_FILE S TEST.xml",
        )
        .await,
        ["200 OK"]
    );
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "raw-default",
            "PP GET_RAW_DATA S 0 16"
        )
        .await,
        ["316 RawData=010000000000000000ff000000000000"]
    );

    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "create",
            "PROGRAMMER CREATE P \"Task Name\" \"Display Route\"",
        )
        .await,
        ["200 OK: created"]
    );
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "test",
            "PROGRAMMER TEST P diagnostic payload",
        )
        .await,
        ["200 OK: id: 1"]
    );
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "add",
            "PROGRAMMER ADD_INSTRUCTION P PP_END S",
        )
        .await,
        ["200 OK: id: 2"]
    );
    let status = command(&mut reader, &mut writer, "status", "PROGRAMMER STATUS P").await;
    assert_eq!(
        status,
        [
            "130-{\"progState\":\"INIT\",\"queueCount\":2,\"totalCount\":2,\"remainingSeconds\":4}",
            "200 OK.",
        ]
    );
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "execute",
            "PROGRAMMER TRIGGER P START",
        )
        .await,
        ["502 Programmer execution backend is not implemented; queue remains unchanged"]
    );
    assert_eq!(
        command(&mut reader, &mut writer, "status2", "PROGRAMMER STATUS P").await[0],
        status[0]
    );
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "patch",
            "PP WRITE_PATCH S TEST anything",
        )
        .await,
        ["502 Command requires a physical backend that is not implemented"]
    );
    assert_eq!(
        system
            .pci
            .frames()
            .iter()
            .filter(|frame| !is_status_request(&frame.payload))
            .count(),
        frames_before
    );

    let mqtt_payload = "053800790149";
    let before_mqtt = system.pci.count_payload(mqtt_payload);
    system
        .broker
        .inject("homeassistant/light/cbus_1/set", br#"{"state":"ON"}"#);
    require(COMMAND_DRAIN, "MQTT after local programming admin", || {
        system.pci.count_payload(mqtt_payload) > before_mqtt
    })
    .await;
    assert!(system.daemon.is_running());

    drop(reader);
    drop(writer);
    drop(system);

    let mut restarted = start_with(options(&state, &unitspec)).await;
    wait_started(&restarted).await;
    let (mut reader, mut writer) = connect(&restarted).await;
    assert_eq!(
        command(&mut reader, &mut writer, "runtime", "PROGRAMMER LIST").await,
        ["450 no programmers registered."]
    );
    assert_eq!(
        command(&mut reader, &mut writer, "locks", "PP LIST_LOCK").await,
        ["122 no open locks"]
    );
    assert_eq!(
        command(&mut reader, &mut writer, "sessions", "PP UNITS").await,
        ["122 no open sessions"]
    );
    assert!(restarted.daemon.is_running());
    drop(restarted);

    std::fs::remove_file(state).unwrap();
    std::fs::remove_dir_all(unitspec).unwrap();
}
