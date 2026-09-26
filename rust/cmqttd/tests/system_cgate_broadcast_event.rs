//! Real cmqttd process: BROADCAST_EVENT stays local to the command service,
//! uses native timestamped 703 envelopes, and reaches only EVENT subscribers.

mod util;

use tokio::{
    io::{AsyncBufReadExt, AsyncWriteExt, BufReader},
    net::TcpStream,
};
use util::*;

async fn connect(
    address: &str,
) -> (
    BufReader<tokio::net::tcp::OwnedReadHalf>,
    tokio::net::tcp::OwnedWriteHalf,
) {
    let stream = tokio::time::timeout(STARTUP, TcpStream::connect(address))
        .await
        .expect("C-Gate connect timed out")
        .unwrap();
    let (reader, writer) = stream.into_split();
    let mut reader = BufReader::new(reader);
    let mut greeting = String::new();
    tokio::time::timeout(STARTUP, reader.read_line(&mut greeting))
        .await
        .expect("C-Gate greeting timed out")
        .unwrap();
    assert_eq!(greeting, "201 cmqttd C-Gate service ready\r\n");
    (reader, writer)
}

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
        tokio::time::timeout(STARTUP, reader.read_line(&mut line))
            .await
            .unwrap_or_else(|_| panic!("command timed out: {text}"))
            .unwrap();
        let line = line.trim_end_matches(['\r', '\n']);
        let payload = line
            .strip_prefix(&prefix)
            .unwrap_or_else(|| panic!("unexpected line while reading {text:?}: {line:?}"));
        let complete = payload.as_bytes().get(3) == Some(&b' ');
        reply.push(payload.to_string());
        if complete {
            return reply;
        }
    }
}

fn assert_broadcast_event(line: &str, session: u64, content: &str) {
    let body = line
        .strip_prefix("#e# ")
        .unwrap_or_else(|| panic!("missing event marker: {line:?}"));
    let (timestamp, payload) = body
        .split_once(" 703 ")
        .unwrap_or_else(|| panic!("missing native 703 envelope: {line:?}"));
    chrono::NaiveDateTime::parse_from_str(timestamp, "%Y%m%d-%H%M%S%.3f").unwrap();
    assert_eq!(payload, format!("cmd{session} - broadcast_event {content}"));
    assert_eq!(cbus_cgate::event_reporting_level(line), Some(3));
}

#[tokio::test]
async fn broadcast_event_fans_out_without_pci_or_mqtt_disruption() {
    let state = cbus_test_support::proc::temp_path("cgate-broadcast-event.json");
    let sys = start_with(Options {
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

    // Producer connects first and therefore owns native session cmd3.
    let (mut producer_reader, mut producer_writer) = connect(&address).await;
    let (mut event_reader, mut event_writer) = connect(&address).await;
    assert_eq!(
        command(
            &mut producer_reader,
            &mut producer_writer,
            "session",
            "SESSION_ID",
        )
        .await,
        ["300 sessionID=cmd3"]
    );

    let capabilities = command(
        &mut producer_reader,
        &mut producer_writer,
        "capabilities",
        "CMQTT CAPABILITIES",
    )
    .await;
    let document: serde_json::Value = serde_json::from_str(
        capabilities[0]
            .strip_prefix("200-")
            .expect("capability JSON continuation"),
    )
    .unwrap();
    assert_eq!(document["broadcast_event"], true);
    assert_eq!(document["broadcast_event_code"], 703);
    assert_eq!(document["broadcast_event_level"], 3);
    assert_eq!(document["broadcast_event_fanout"], true);
    assert_eq!(document["broadcast_event_persistence"], false);

    assert_eq!(
        command(
            &mut event_reader,
            &mut event_writer,
            "events",
            "EVENT e3s0c0",
        )
        .await,
        ["200 OK."]
    );
    assert_eq!(
        command(
            &mut producer_reader,
            &mut producer_writer,
            "minimal",
            "BROADCAST_EVENT SP",
        )
        .await,
        ["200 OK."]
    );
    let mut event = String::new();
    tokio::time::timeout(STARTUP, event_reader.read_line(&mut event))
        .await
        .expect("minimal BROADCAST_EVENT timed out")
        .unwrap();
    assert_broadcast_event(event.trim_end_matches(['\r', '\n']), 3, "SP ");

    assert_eq!(
        command(
            &mut producer_reader,
            &mut producer_writer,
            "payload",
            "BROADCAST_EVENT XX class payload text",
        )
        .await,
        ["200 OK."]
    );
    event.clear();
    tokio::time::timeout(STARTUP, event_reader.read_line(&mut event))
        .await
        .expect("payload BROADCAST_EVENT timed out")
        .unwrap();
    assert_broadcast_event(
        event.trim_end_matches(['\r', '\n']),
        3,
        "XX class payload text",
    );

    assert_eq!(
        command(&mut event_reader, &mut event_writer, "off", "EVENT OFF",).await,
        ["200 OK."]
    );
    assert_eq!(
        command(
            &mut producer_reader,
            &mut producer_writer,
            "hidden",
            "BROADCAST_EVENT SP class hidden",
        )
        .await,
        ["200 OK."]
    );
    let mut unexpected = String::new();
    assert!(
        tokio::time::timeout(
            std::time::Duration::from_millis(150),
            event_reader.read_line(&mut unexpected),
        )
        .await
        .is_err(),
        "EVENT OFF client received {unexpected:?}"
    );

    // This is command-service traffic only: the shared daemon remains
    // subscribed to MQTT and BROADCAST_EVENT needs no C-Bus confirmation.
    assert!(sys.broker.has_subscription("homeassistant/light/+/set"));
    assert_eq!(
        command(
            &mut producer_reader,
            &mut producer_writer,
            "missing",
            "BROADCAST_EVENT",
        )
        .await,
        ["400 Syntax Error."]
    );

    std::fs::remove_file(state).ok();
}
