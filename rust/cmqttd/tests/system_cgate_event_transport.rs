//! The real daemon keeps MQTT/PCI alive while the native CONFIG event
//! transport switches between a read-only server and an outbound socket.

mod util;

use std::time::Duration;
use tokio::{
    io::{AsyncBufReadExt, AsyncWriteExt, BufReader},
    net::{TcpListener, TcpStream},
};
use util::*;

async fn command(
    reader: &mut BufReader<tokio::net::tcp::OwnedReadHalf>,
    writer: &mut tokio::net::tcp::OwnedWriteHalf,
    tag: &str,
    body: &str,
) -> String {
    writer
        .write_all(format!("[{tag}] {body}\r\n").as_bytes())
        .await
        .unwrap();
    let mut reply = String::new();
    loop {
        let mut line = String::new();
        reader.read_line(&mut line).await.unwrap();
        assert!(line.starts_with(&format!("[{tag}] ")), "{line:?}");
        reply.push_str(&line);
        if line.as_bytes().get(tag.len() + 6) == Some(&b' ') {
            return reply;
        }
    }
}

async fn command_session(
    sys: &System,
) -> (
    BufReader<tokio::net::tcp::OwnedReadHalf>,
    tokio::net::tcp::OwnedWriteHalf,
) {
    require(STARTUP, "C-Gate command listener", || {
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
    let (reader, writer) = stream.into_split();
    let mut reader = BufReader::new(reader);
    let mut greeting = String::new();
    reader.read_line(&mut greeting).await.unwrap();
    assert_eq!(greeting, "201 cmqttd C-Gate service ready\r\n");
    (reader, writer)
}

async fn next_event(reader: &mut BufReader<tokio::net::tcp::OwnedReadHalf>) -> String {
    let mut line = String::new();
    tokio::time::timeout(Duration::from_secs(5), reader.read_line(&mut line))
        .await
        .expect("event stream stalled")
        .unwrap();
    assert!(line.ends_with("\r\n"), "{line:?}");
    assert!(!line.starts_with("#e#"), "{line:?}");
    line
}

fn options(state: &std::path::Path) -> Options {
    Options {
        extra: vec![
            "--cgate-bind".into(),
            "127.0.0.1:0".into(),
            "--cgate-state".into(),
            state.to_string_lossy().into_owned(),
        ],
        ..Default::default()
    }
}

#[tokio::test]
async fn config_event_server_and_outbound_socket_stream_without_interrupting_mqtt() {
    let native: serde_json::Value = serde_json::from_str(include_str!(
        "../../testdata/fixtures/native_cgate_config_event_transport.json"
    ))
    .unwrap();
    assert_eq!(native["oracle"]["physical_endpoint"], false);
    assert_eq!(
        native["server"]["5"]["same_process_config"]["old_event_port_still_accepts"],
        true
    );
    assert_eq!(
        native["server"]["5"]["same_process_config"]["new_event_port_unbound"],
        true
    );
    assert_eq!(native["socket"]["sink_peer_ip"], "127.0.0.1");
    let state = cbus_test_support::proc::temp_path("cgate-event-transport.json");
    let first = start_with(options(&state)).await;
    wait_started(&first).await;
    require(STARTUP, "C-Gate event listener", || {
        first
            .daemon
            .stderr()
            .contains("C-Gate event service listening on ")
    })
    .await;
    let event_address = first
        .daemon
        .stderr()
        .lines()
        .find_map(|line| line.split_once("C-Gate event service listening on "))
        .map(|(_, address)| address.trim().to_string())
        .unwrap();
    let event_stream = TcpStream::connect(event_address).await.unwrap();
    let (event_reader, event_writer) = event_stream.into_split();
    let mut event_reader = BufReader::new(event_reader);
    let mut blank = String::new();
    assert!(
        tokio::time::timeout(
            Duration::from_millis(100),
            event_reader.read_line(&mut blank)
        )
        .await
        .is_err(),
        "unexpected initial event: {blank:?}; daemon: {}",
        first.daemon.stderr()
    );

    let (mut reader, mut writer) = command_session(&first).await;
    let opened = next_event(&mut event_reader).await;
    assert!(opened.contains(" 803 cmd3 - Host:/127.0.0.1 opened command interface from port: "));
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "b",
            "BROADCAST_EVENT SP class server"
        )
        .await,
        "[b] 200 OK.\r\n"
    );
    let broadcast = next_event(&mut event_reader).await;
    assert!(broadcast.ends_with(" 703 cmd3 - broadcast_event SP class server\r\n"));

    let sink = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let sink_port = sink.local_addr().unwrap().port();
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "mode",
            "CONFIG SET event-mode socket"
        )
        .await,
        "[mode] 200 OK.\r\n"
    );
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "host",
            "CONFIG SET event-host 127.0.0.1"
        )
        .await,
        "[host] 200 OK.\r\n"
    );
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "port",
            &format!("CONFIG SET event-port {sink_port}")
        )
        .await,
        "[port] 200 OK.\r\n"
    );
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "still",
            "BROADCAST_EVENT SP class still-server"
        )
        .await,
        "[still] 200 OK.\r\n"
    );
    let still_server = next_event(&mut event_reader).await;
    assert!(still_server.ends_with(" 703 cmd3 - broadcast_event SP class still-server\r\n"));
    assert!(first.broker.has_subscription("homeassistant/light/+/set"));
    drop((event_reader, event_writer, reader, writer, first));

    let second = start_with(options(&state)).await;
    wait_started(&second).await;
    let (stream, _) = tokio::time::timeout(STARTUP, sink.accept())
        .await
        .expect("cmqttd did not connect to configured event socket")
        .unwrap();
    let (event_reader, event_writer) = stream.into_split();
    let mut event_reader = BufReader::new(event_reader);
    let startup = next_event(&mut event_reader).await;
    assert!(startup.ends_with(" 800 cgate - C-Gate started.\r\n"));
    let (mut reader, mut writer) = command_session(&second).await;
    let opened = next_event(&mut event_reader).await;
    assert!(opened.contains(" 803 cmd3 - Host:/127.0.0.1 opened command interface from port: "));
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "b",
            "BROADCAST_EVENT SP class socket"
        )
        .await,
        "[b] 200 OK.\r\n"
    );
    let broadcast = next_event(&mut event_reader).await;
    assert!(broadcast.ends_with(" 703 cmd3 - broadcast_event SP class socket\r\n"));
    assert!(second.broker.has_subscription("homeassistant/light/+/set"));
    drop((event_reader, event_writer, reader, writer, second, sink));
    std::fs::remove_file(state).unwrap();
}
