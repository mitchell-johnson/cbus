//! Administrative C-Gate operations remain local and leave the shared MQTT
//! and PCI command path operational.

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
        let line = line.trim_end_matches(['\r', '\n']).to_string();
        let payload = line.strip_prefix(&prefix).expect("tagged C-Gate reply");
        let complete = payload.as_bytes().get(3) == Some(&b' ');
        reply.push(line);
        if complete {
            return reply;
        }
    }
}

#[tokio::test]
async fn administrative_documents_and_mqtt_share_the_running_daemon() {
    let state = cbus_test_support::proc::temp_path("cgate-admin.json");
    let mut sys = start_with(Options {
        extra: vec![
            "--cgate-bind".into(),
            "127.0.0.1:0".into(),
            "--cgate-state".into(),
            state.to_string_lossy().into_owned(),
        ],
        ..Default::default()
    })
    .await;
    wait_started(&sys).await;
    require(STARTUP, "C-Gate listener", || {
        sys.daemon.stderr().contains("C-Gate service listening on ")
    })
    .await;
    let address = sys
        .daemon
        .stderr()
        .lines()
        .find_map(|line| line.split_once("C-Gate service listening on "))
        .map(|(_, address)| address.trim().to_string())
        .unwrap();
    let stream = TcpStream::connect(address).await.unwrap();
    let (reader, mut writer) = stream.into_split();
    let mut reader = BufReader::new(reader);
    let mut greeting = String::new();
    reader.read_line(&mut greeting).await.unwrap();
    assert_eq!(greeting, "201 cmqttd C-Gate service ready\r\n");

    for (tag, text) in [
        ("1", "PROJECT NEW AUX"),
        ("2", "PROJECT ARCHIVE AUX cmqttd:internal-slot"),
        ("3", "PROJECT RENAME AUX AUX2"),
        ("4", "PROJECT RESTORE AUX3 cmqttd:internal-slot"),
        ("5", "PROJECT USE HARNESS"),
    ] {
        let reply = command(&mut reader, &mut writer, tag, text).await;
        assert!(
            reply.last().unwrap().contains("200 OK"),
            "{text}: {reply:?}"
        );
    }
    let repository = command(&mut reader, &mut writer, "6", "REPOSITORY LIST").await;
    assert_eq!(repository.len(), 1);
    assert!(repository[0].contains("123 index=1 type=cmqttd-json path="));
    assert!(repository[0].ends_with(" current=yes"));

    writer
        .write_all(b"[7] DBSETXML //HARNESS/254/p/5/TagName << END\r\nSystem document\r\nEND\r\n")
        .await
        .unwrap();
    let mut document_reply = String::new();
    reader.read_line(&mut document_reply).await.unwrap();
    assert_eq!(
        document_reply,
        "[7] 502 Document command semantics are not implemented\r\n"
    );

    let payload = "053800790149";
    let before = sys.pci.count_payload(payload);
    sys.broker
        .inject("homeassistant/light/cbus_1/set", br#"{"state":"ON"}"#);
    require(
        COMMAND_DRAIN,
        "MQTT command after C-Gate administration",
        || sys.pci.count_payload(payload) > before,
    )
    .await;
    assert!(sys.daemon.is_running());
    drop(sys);
    std::fs::remove_file(state).unwrap();
}

#[tokio::test]
async fn native_family_help_is_exact_over_tcp_and_keeps_mqtt_live() {
    let evidence: serde_json::Value = serde_json::from_str(include_str!(
        "../../testdata/fixtures/native_cgate_family_help.json"
    ))
    .unwrap();
    let state = cbus_test_support::proc::temp_path("cgate-family-help.json");
    let mut sys = start_with(Options {
        extra: vec![
            "--cgate-bind".into(),
            "127.0.0.1:0".into(),
            "--cgate-state".into(),
            state.to_string_lossy().into_owned(),
        ],
        ..Default::default()
    })
    .await;
    wait_started(&sys).await;
    require(STARTUP, "C-Gate listener", || {
        sys.daemon.stderr().contains("C-Gate service listening on ")
    })
    .await;
    let address = sys
        .daemon
        .stderr()
        .lines()
        .find_map(|line| line.split_once("C-Gate service listening on "))
        .map(|(_, address)| address.trim().to_string())
        .unwrap();
    let stream = TcpStream::connect(address).await.unwrap();
    let (reader, mut writer) = stream.into_split();
    let mut reader = BufReader::new(reader);
    let mut greeting = String::new();
    reader.read_line(&mut greeting).await.unwrap();
    assert_eq!(greeting, "201 cmqttd C-Gate service ready\r\n");

    let mut id = 0_u32;
    for family in evidence["families"].as_array().unwrap() {
        let name = family["family"].as_str().unwrap();
        for text in [
            name.to_string(),
            format!("{name} ?"),
            format!("HELP {name}"),
        ] {
            id += 1;
            let tag = id.to_string();
            let expected = family["root"]
                .as_array()
                .unwrap()
                .iter()
                .map(|row| {
                    format!(
                        "[{tag}] 101{}{}",
                        if row["continuation"].as_bool().unwrap() {
                            '-'
                        } else {
                            ' '
                        },
                        row["text"].as_str().unwrap()
                    )
                })
                .collect::<Vec<_>>();
            assert_eq!(
                command(&mut reader, &mut writer, &tag, &text).await,
                expected,
                "{text}"
            );
        }
    }

    let payload = "053800790149";
    let before = sys.pci.count_payload(payload);
    sys.broker
        .inject("homeassistant/light/cbus_1/set", br#"{"state":"ON"}"#);
    require(COMMAND_DRAIN, "MQTT after family help", || {
        sys.pci.count_payload(payload) > before
    })
    .await;
    assert!(sys.daemon.is_running());
    drop(sys);
    std::fs::remove_file(state).unwrap();
}
