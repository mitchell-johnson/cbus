//! A disposable secondary-project copy/delete workflow remains local while
//! MQTT control continues through the daemon's shared PCI path.

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

fn xml_oid(reply: &[String]) -> &str {
    let xml = reply
        .iter()
        .find(|line| line.contains("347-<Network>"))
        .expect("network XML row");
    xml.split_once("<OID>")
        .and_then(|(_, rest)| rest.split_once("</OID>"))
        .map(|(oid, _)| oid)
        .expect("unit OID in network XML")
}

#[tokio::test]
async fn project_copy_delete_preserves_database_identity_and_mqtt_continuity() {
    let state = cbus_test_support::proc::temp_path("cgate-project-copy-delete.json");
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
        ("2", "DBCREATENET 1 Auxiliary Cni loopback"),
        ("3", "DBADDSAFE //AUX/1 Unit 20 Original"),
        ("4", "DBSETSAFE //AUX/1/p/20/TagName Original"),
    ] {
        let reply = command(&mut reader, &mut writer, tag, text).await;
        assert!(
            reply.last().unwrap().contains("200 OK"),
            "{text}: {reply:?}"
        );
    }
    let source = command(&mut reader, &mut writer, "5", "DBGETXML //AUX/1").await;
    let source_oid = xml_oid(&source).to_string();

    let copied = command(&mut reader, &mut writer, "6", "PROJECT COPY AUX COPY").await;
    assert_eq!(copied.last().unwrap(), "[6] 200 OK.");
    assert_eq!(
        command(&mut reader, &mut writer, "7", "PROJECT USE COPY")
            .await
            .last()
            .unwrap(),
        "[7] 200 OK"
    );
    let destination = command(&mut reader, &mut writer, "8", "DBGETXML //COPY/1").await;
    assert_eq!(xml_oid(&destination), source_oid);
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "9",
            "DBSETSAFE //COPY/1/p/20/TagName ChangedCopy",
        )
        .await
        .last()
        .unwrap(),
        "[9] 200 OK"
    );
    command(&mut reader, &mut writer, "10", "PROJECT USE AUX").await;
    let source_field = command(&mut reader, &mut writer, "11", "DBGET //AUX/1/p/20/TagName").await;
    assert!(
        source_field
            .iter()
            .any(|line| line.contains("//AUX/1/p/20/TagName=Original")),
        "{source_field:?}"
    );

    let protected = command(&mut reader, &mut writer, "12", "PROJECT DELETE HARNESS").await;
    assert_eq!(
        protected.last().unwrap(),
        "[12] 408 The configured hardware project cannot be deleted while the service is running"
    );
    command(&mut reader, &mut writer, "13", "PROJECT USE COPY").await;
    let deleted = command(&mut reader, &mut writer, "14", "PROJECT DELETE COPY").await;
    assert_eq!(deleted.last().unwrap(), "[14] 200 OK.");
    let absent = command(&mut reader, &mut writer, "15", "PROJECT USE COPY").await;
    assert!(absent.last().unwrap().contains("404 Project not found"));

    for (tag, text) in [("16", "PROJECT REPAIR AUX"), ("17", "REPOSITORY USE 1")] {
        let reply = command(&mut reader, &mut writer, tag, text).await;
        assert!(
            reply
                .last()
                .unwrap()
                .contains("502 Command requires a physical backend that is not implemented"),
            "{text}: {reply:?}"
        );
    }

    let payload = "053800790149";
    let before = sys.pci.count_payload(payload);
    sys.broker
        .inject("homeassistant/light/cbus_1/set", br#"{"state":"ON"}"#);
    require(
        COMMAND_DRAIN,
        "MQTT command after project copy/delete",
        || sys.pci.count_payload(payload) > before,
    )
    .await;
    assert!(sys.daemon.is_running());
    drop(sys);
    std::fs::remove_file(state).unwrap();
}
