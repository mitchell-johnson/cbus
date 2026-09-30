//! Native-backed command admission through the real cmqttd process.
//! The peer policy must leave the independent MQTT/PCI path operational.

mod util;

use std::time::Duration;
use tokio::{
    io::{AsyncBufReadExt, AsyncWriteExt, BufReader},
    net::TcpStream,
};
use util::*;

fn listener_address(sys: &System) -> String {
    sys.daemon
        .stderr()
        .lines()
        .find_map(|line| line.split_once("C-Gate service listening on "))
        .map(|(_, address)| address.trim().to_string())
        .expect("C-Gate listener address")
}

async fn connect_command(
    sys: &System,
) -> (
    BufReader<tokio::net::tcp::OwnedReadHalf>,
    tokio::net::tcp::OwnedWriteHalf,
) {
    require(STARTUP, "C-Gate listener", || {
        sys.daemon.stderr().contains("C-Gate service listening on ")
    })
    .await;
    let stream = TcpStream::connect(listener_address(sys)).await.unwrap();
    let (reader, writer) = stream.into_split();
    let mut reader = BufReader::new(reader);
    let mut greeting = String::new();
    reader.read_line(&mut greeting).await.unwrap();
    assert_eq!(greeting, "201 cmqttd C-Gate service ready\r\n");
    (reader, writer)
}

async fn command(
    reader: &mut BufReader<tokio::net::tcp::OwnedReadHalf>,
    writer: &mut tokio::net::tcp::OwnedWriteHalf,
    tag: &str,
    body: &str,
) -> Vec<String> {
    writer
        .write_all(format!("[{tag}] {body}\r\n").as_bytes())
        .await
        .unwrap();
    let mut rows = Vec::new();
    loop {
        let mut line = String::new();
        assert_ne!(reader.read_line(&mut line).await.unwrap(), 0);
        let line = line.trim_end_matches(['\r', '\n']);
        let payload = line.strip_prefix(&format!("[{tag}] ")).unwrap();
        let done = payload.as_bytes().get(3) == Some(&b' ');
        rows.push(payload.to_string());
        if done {
            return rows;
        }
    }
}

async fn denied_connection_stays_silent(sys: &System) {
    let mut peer = TcpStream::connect(listener_address(sys)).await.unwrap();
    assert!(
        tokio::time::timeout(Duration::from_millis(350), peer.readable())
            .await
            .is_err(),
        "denied peer unexpectedly received a greeting or EOF"
    );
    peer.write_all(b"NOOP\r\n").await.unwrap();
    assert!(
        tokio::time::timeout(Duration::from_millis(350), peer.readable())
            .await
            .is_err(),
        "denied peer unexpectedly received a command reply or EOF"
    );
}

#[tokio::test]
async fn config_admission_changes_new_sessions_and_preserves_mqtt_pci() {
    let native: serde_json::Value = serde_json::from_str(include_str!(
        "../../testdata/fixtures/native_cgate_config_connection_admission.json"
    ))
    .unwrap();
    assert_eq!(
        native["schema"],
        "native-cgate-config-connection-admission-v1"
    );
    for child in [
        "default", "runtime", "denied", "allowed", "multiple", "hostname",
    ] {
        assert_eq!(
            native["oracle"]["children"][child]["cleanup_complete"],
            true
        );
    }
    assert_eq!(
        native["runtime"]["after_set"]["outcome"],
        "connected-no-greeting-timeout"
    );
    assert_eq!(native["runtime"]["after_reallow"]["outcome"], "greeting");
    assert_eq!(
        native["runtime"]["after_reload"]["outcome"],
        "connected-no-greeting-timeout"
    );
    assert_eq!(
        native["fresh_denied"]["outcome"],
        "connected-no-greeting-timeout"
    );
    let hostname_tls: serde_json::Value = serde_json::from_str(include_str!(
        "../../testdata/fixtures/native_cgate_config_hostname_tls_admission.json"
    ))
    .unwrap();
    assert_eq!(
        hostname_tls["schema"],
        "native-cgate-config-hostname-tls-admission-v1"
    );
    assert_eq!(hostname_tls["baseline"]["tls"]["outcome"], "greeting");
    assert_eq!(
        hostname_tls["tls_cases"][3]["tls"]["outcome"],
        "handshake-timeout"
    );

    let state = cbus_test_support::proc::temp_path("cgate-config-admission.json");
    let options = || Options {
        extra: vec![
            "--cgate-bind".into(),
            "127.0.0.1:0".into(),
            "--cgate-state".into(),
            state.to_string_lossy().into_owned(),
        ],
        ..Default::default()
    };
    let mut first = start_with(options()).await;
    wait_started(&first).await;
    let (mut reader, mut writer) = connect_command(&first).await;
    let caps = command(&mut reader, &mut writer, "caps", "CMQTT CAPABILITIES").await;
    let caps: serde_json::Value =
        serde_json::from_str(caps[0].strip_prefix("200-").unwrap()).unwrap();
    assert_eq!(caps["config_command_admission_numeric_ip"], true);
    assert_eq!(caps["config_command_admission_localhost"], true);
    assert_eq!(caps["config_command_admission_hostnames"], true);
    assert_eq!(caps["config_command_admission_tls"], true);
    assert_eq!(caps["config_command_admission_ipv4_mapped"], true);
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "default",
            "CONFIG GET accept-connections-from"
        )
        .await,
        ["303 accept-connections-from=all"]
    );
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "multiple",
            "CONFIG SET accept-connections-from 192.0.2.55 127.0.0.1"
        )
        .await,
        ["200 OK."]
    );
    let (multi_reader, multi_writer) = connect_command(&first).await;
    drop((multi_reader, multi_writer));
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "localhost",
            "CONFIG SET accept-connections-from localhost"
        )
        .await,
        ["200 OK."]
    );
    let (local_reader, local_writer) = connect_command(&first).await;
    drop((local_reader, local_writer));
    for (tag, value) in [
        ("uppercase", "LOCALHOST"),
        ("qualified", "localhost."),
        ("mapped", "::ffff:127.0.0.1"),
        ("all-uppercase", "ALL"),
    ] {
        assert_eq!(
            command(
                &mut reader,
                &mut writer,
                tag,
                &format!("CONFIG SET accept-connections-from {value}")
            )
            .await,
            ["200 OK."]
        );
        let (new_reader, new_writer) = connect_command(&first).await;
        drop((new_reader, new_writer));
    }
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "deny",
            "CONFIG SET accept-connections-from 192.0.2.55"
        )
        .await,
        ["200 OK."]
    );
    denied_connection_stays_silent(&first).await;
    assert_eq!(
        command(&mut reader, &mut writer, "existing", "NOOP").await,
        ["200 OK."]
    );
    assert_eq!(
        command(&mut reader, &mut writer, "save", "CONFIG SAVE global").await,
        ["200 OK."]
    );

    let payload = "053800790149";
    let before = first.pci.count_payload(payload);
    first
        .broker
        .inject("homeassistant/light/cbus_1/set", br#"{"state":"ON"}"#);
    require(COMMAND_DRAIN, "MQTT while C-Gate peer denied", || {
        first.pci.count_payload(payload) > before
    })
    .await;
    assert!(first.daemon.is_running());

    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "reallow",
            "CONFIG SET accept-connections-from all"
        )
        .await,
        ["200 OK."]
    );
    let (reallowed_reader, reallowed_writer) = connect_command(&first).await;
    drop((reallowed_reader, reallowed_writer));
    assert_eq!(
        command(&mut reader, &mut writer, "reload", "CONFIG LOAD global").await,
        ["200 OK."]
    );
    denied_connection_stays_silent(&first).await;
    drop((reader, writer, first));

    let mut second = start_with(options()).await;
    wait_started(&second).await;
    denied_connection_stays_silent(&second).await;
    assert_eq!(second.broker.connections(), 1);
    assert!(second.daemon.is_running());
    drop(second);
    std::fs::remove_file(state).unwrap();
}
