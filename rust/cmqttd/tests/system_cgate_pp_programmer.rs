//! Real cmqttd process: PROGRAMMER and DEPLOY_QUEUE acknowledge asynchronous
//! execution, expose the native TEST countdown, stop on first instruction
//! fault, and retry only on an explicit request. PP patching stays fail-closed
//! without a verified vendor patchset. MQTT remains live throughout.

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

async fn wait_for(
    reader: &mut BufReader<tokio::net::tcp::OwnedReadHalf>,
    writer: &mut tokio::net::tcp::OwnedWriteHalf,
    text: &str,
    expected: &str,
) -> Vec<String> {
    let deadline = tokio::time::Instant::now() + STARTUP;
    let mut sequence = 0u64;
    loop {
        let reply = command(reader, writer, &format!("wait-{sequence}"), text).await;
        if reply.iter().any(|line| line.contains(expected)) {
            return reply;
        }
        assert!(tokio::time::Instant::now() < deadline, "{text}: {reply:?}");
        sequence += 1;
        tokio::time::sleep(std::time::Duration::from_millis(25)).await;
    }
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
            "database-unit",
            "DBADDSAFE //HARNESS/254 Unit 5 QueueUnit",
        )
        .await,
        ["200 OK"]
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
            "PROGRAMMER ADD_INSTRUCTION P PP_SET S First 7",
        )
        .await,
        ["200 OK: id: 2"]
    );
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "save",
            "PROGRAMMER ADD_INSTRUCTION P PP_SAVE S /db//HARNESS/254/p/5",
        )
        .await,
        ["200 OK: id: 3"]
    );
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "end",
            "PROGRAMMER ADD_INSTRUCTION P PP_END S",
        )
        .await,
        ["200 OK: id: 4"]
    );
    let status = command(&mut reader, &mut writer, "status", "PROGRAMMER STATUS P").await;
    assert_eq!(
        status,
        [
            "130-{\"progState\":\"INIT\",\"queueCount\":4,\"totalCount\":4,\"remainingSeconds\":6}",
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
        ["200 OK: triggered"]
    );
    let running = wait_for(
        &mut reader,
        &mut writer,
        "PROGRAMMER STATUS P",
        "\"progState\":\"RUNNING\"",
    )
    .await;
    assert!(running[0].contains("\"progState\":\"RUNNING\""));
    let running_status: serde_json::Value =
        serde_json::from_str(running[0].strip_prefix("130-").unwrap()).unwrap();
    assert_eq!(running_status["totalCount"], 4);
    assert!(matches!(running_status["queueCount"].as_u64(), Some(3 | 4)));
    assert!(matches!(
        running_status["remainingSeconds"].as_u64(),
        Some(3..=6)
    ));
    let stopped = wait_for(
        &mut reader,
        &mut writer,
        "PROGRAMMER STATUS P",
        "\"progState\":\"STOPPED\"",
    )
    .await;
    assert!(stopped[0].contains("\"remainingSeconds\":0"));
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "saved-value",
            "PP QUICKGET //HARNESS/254/p/5 First",
        )
        .await,
        ["315 First=7"]
    );
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "execute-again",
            "PROGRAMMER TRIGGER P START",
        )
        .await,
        ["400 failed: unsupported programmer transition"]
    );
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "patch",
            "PP WRITE_PATCH //HARNESS/254/p/1 01",
        )
        .await,
        ["502 PP WRITE_PATCH requires a verified vendor patchset and patch protocol executor; no bus command was sent"]
    );

    let (mut event_reader, mut event_writer) = connect(&system).await;
    for (tag, channel) in [
        ("sub-updated", "deploy-queue.updated-entries"),
        ("sub-debug", "deploy-queue.debug"),
        ("sub-started", "deploy-queue.started"),
        ("sub-ended", "deploy-queue.ended"),
    ] {
        assert_eq!(
            command(
                &mut event_reader,
                &mut event_writer,
                tag,
                &format!("EVENT_CHANNEL SUB {channel}"),
            )
            .await,
            ["200 OK: added"]
        );
    }
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "queue-create",
            "PROGRAMMER CREATE QUEUED \"Timed work\" \"Local\"",
        )
        .await,
        ["200 OK: created"]
    );
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "queue-test",
            "PROGRAMMER TEST QUEUED payload",
        )
        .await,
        ["200 OK: id: 1"]
    );
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "queue-add",
            "DEPLOY_QUEUE ADD QUEUED",
        )
        .await,
        ["200 OK: added"]
    );
    let mut events = Vec::new();
    for _ in 0..3 {
        let mut event = String::new();
        tokio::time::timeout(STARTUP, event_reader.read_line(&mut event))
            .await
            .unwrap()
            .unwrap();
        events.push(event.trim_end_matches(['\r', '\n']).to_string());
    }
    assert_eq!(
        events,
        [
            "#event {\"name\":\"deploy-queue.updated-entries\",\"msg\":\"addTaskGroup: QUEUED\"}",
            "#event {\"name\":\"deploy-queue.started\",\"msg\":{\"name\":\"QUEUED\",\"task\":\"Timed work\"}}",
            "#event {\"name\":\"deploy-queue.ended\",\"msg\":{\"name\":\"QUEUED\",\"task\":\"Timed work\",\"status\":\"STOPPED\"}}",
        ]
    );
    let deployed = command(&mut reader, &mut writer, "deploy-list", "DEPLOY_QUEUE LIST").await;
    assert_eq!(deployed.last().unwrap(), "200 OK.");
    assert!(deployed[0].starts_with(
        "130-{\"progName\":\"QUEUED\",\"progState\":\"STOPPED\",\"taskName\":\"Timed work\",\"taskRoute\":\"Local\",\"createdTime\":"
    ));
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "deploy-retry",
            "DEPLOY_QUEUE RETRY QUEUED",
        )
        .await,
        ["200 OK: retry added"]
    );
    let mut retry_events = Vec::new();
    for _ in 0..2 {
        let mut event = String::new();
        tokio::time::timeout(STARTUP, event_reader.read_line(&mut event))
            .await
            .unwrap()
            .unwrap();
        retry_events.push(event.trim_end_matches(['\r', '\n']).to_string());
    }
    assert_eq!(
        retry_events,
        [
            "#event {\"name\":\"deploy-queue.started\",\"msg\":{\"name\":\"QUEUED\",\"task\":\"Timed work\"}}",
            "#event {\"name\":\"deploy-queue.ended\",\"msg\":{\"name\":\"QUEUED\",\"task\":\"Timed work\",\"status\":\"STOPPED\"}}",
        ]
    );

    for (tag, text, expected) in [
        (
            "fail-create",
            "PROGRAMMER CREATE FAIL \"First fault\" \"Local\"",
            "200 OK: created",
        ),
        (
            "fail-add-instruction",
            "PROGRAMMER ADD_INSTRUCTION FAIL PP_SAVE Missing /db//HARNESS/254/p/1",
            "200 OK: id: 1",
        ),
        ("fail-add", "DEPLOY_QUEUE ADD FAIL", "200 OK: added"),
    ] {
        assert_eq!(
            command(&mut reader, &mut writer, tag, text).await,
            [expected],
            "{text}"
        );
    }
    let mut failure_events = Vec::new();
    for _ in 0..4 {
        let mut event = String::new();
        tokio::time::timeout(STARTUP, event_reader.read_line(&mut event))
            .await
            .unwrap()
            .unwrap();
        failure_events.push(event.trim_end_matches(['\r', '\n']).to_string());
    }
    assert_eq!(
        &failure_events[..2],
        [
            "#event {\"name\":\"deploy-queue.updated-entries\",\"msg\":\"addTaskGroup: FAIL\"}",
            "#event {\"name\":\"deploy-queue.started\",\"msg\":{\"name\":\"FAIL\",\"task\":\"First fault\"}}",
        ]
    );
    assert!(failure_events[2].starts_with(
        "#event {\"name\":\"deploy-queue.debug\",\"msg\":{\"automaticReplay\":false,"
    ));
    assert!(failure_events[2].contains("\"instructionType\":\"PP_SAVE\""));
    assert_eq!(
        failure_events[3],
        "#event {\"name\":\"deploy-queue.ended\",\"msg\":{\"name\":\"FAIL\",\"task\":\"First fault\",\"status\":\"ERROR\"}}"
    );
    let failed = wait_for(
        &mut reader,
        &mut writer,
        "PROGRAMMER STATUS FAIL",
        "\"progState\":\"ERROR\"",
    )
    .await;
    assert!(failed[0].contains("\"remainingSeconds\":1"));
    let mut unexpected_event = String::new();
    assert!(
        tokio::time::timeout(
            std::time::Duration::from_millis(150),
            event_reader.read_line(&mut unexpected_event)
        )
        .await
        .is_err(),
        "a failed instruction was replayed without RETRY"
    );
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "deploy-delete-all",
            "DEPLOY_QUEUE DELETE_ALL all",
        )
        .await,
        ["120-deleted: QUEUED", "120-deleted: FAIL", "200 OK: done"]
    );
    let mut delete_event = String::new();
    tokio::time::timeout(STARTUP, event_reader.read_line(&mut delete_event))
        .await
        .unwrap()
        .unwrap();
    assert_eq!(
        delete_event.trim_end_matches(['\r', '\n']),
        "#event {\"name\":\"deploy-queue.updated-entries\",\"msg\":\"removeAllTaskGroups: 2\"}"
    );
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "volatile-create",
            "PROGRAMMER CREATE VOLATILE \"Restart boundary\" \"Local\"",
        )
        .await,
        ["200 OK: created"]
    );
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "volatile-add",
            "DEPLOY_QUEUE ADD VOLATILE",
        )
        .await,
        ["200 OK: added"]
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
    drop(event_reader);
    drop(event_writer);
    drop(system);

    let mut restarted = start_with(options(&state, &unitspec)).await;
    wait_started(&restarted).await;
    let (mut reader, mut writer) = connect(&restarted).await;
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "persisted-value",
            "PP QUICKGET //HARNESS/254/p/5 First",
        )
        .await,
        ["315 First=7"]
    );
    assert_eq!(
        command(&mut reader, &mut writer, "runtime", "PROGRAMMER LIST").await,
        ["450 no programmers registered."]
    );
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "deploy-runtime",
            "DEPLOY_QUEUE LIST",
        )
        .await,
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
