//! Real cmqttd process: the complete maintained C-Gate CONFIG family uses the
//! local atomic repository, never the shared PCI, and leaves MQTT operational.

mod util;

use tokio::{
    io::{AsyncBufReadExt, AsyncWriteExt, BufReader},
    net::TcpStream,
};
use util::*;

const TOKEN: &str = "throwaway-config-system-token-0123456789abcdef";

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
    sys: &System,
) -> (
    BufReader<tokio::net::tcp::OwnedReadHalf>,
    tokio::net::tcp::OwnedWriteHalf,
) {
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
    let (reader, writer) = stream.into_split();
    let mut reader = BufReader::new(reader);
    let mut greeting = String::new();
    reader.read_line(&mut greeting).await.unwrap();
    assert_eq!(greeting, "201 cmqttd C-Gate service ready\r\n");
    (reader, writer)
}

fn options(state: &std::path::Path, token: &std::path::Path) -> Options {
    Options {
        extra: vec![
            "--cgate-bind".into(),
            "127.0.0.1:0".into(),
            "--cgate-state".into(),
            state.to_string_lossy().into_owned(),
            "--cgate-auth-file".into(),
            token.to_string_lossy().into_owned(),
        ],
        ..Default::default()
    }
}

#[tokio::test]
async fn config_native_family_is_scoped_authenticated_durable_and_keeps_mqtt_live() {
    let state = cbus_test_support::proc::temp_path("cgate-config.json");
    let token = cbus_test_support::proc::temp_path("cgate-config.token");
    std::fs::write(&token, format!("{TOKEN}\n")).unwrap();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&token, std::fs::Permissions::from_mode(0o600)).unwrap();
    }

    let mut sys = start_with(options(&state, &token)).await;
    wait_started(&sys).await;
    let (mut reader, mut writer) = connect(&sys).await;

    assert_eq!(
        command(&mut reader, &mut writer, "help", "CONFIG ?").await,
        [
            "101-Help: CONFIG commands:",
            "101-Help:  CONFIG ? Help for these commands",
            "101-Help:  CONFIG GET - ",
            "101-Help:  CONFIG INFO - ",
            "101-Help:  CONFIG LOAD - ",
            "101-Help:  CONFIG OBGET - ",
            "101-Help:  CONFIG OBRESET - ",
            "101-Help:  CONFIG OBSET - ",
            "101-Help:  CONFIG SAVE - ",
            "101 Help:  CONFIG SET - ",
        ]
    );
    let all = command(&mut reader, &mut writer, "all", "CONFIG GET *").await;
    assert_eq!(all.len(), 122);
    assert_eq!(all.first().unwrap(), "303-accept-connections-from=all");
    assert_eq!(all.last().unwrap(), "303 use-tags=yes");
    assert_eq!(
        command(&mut reader, &mut writer, "info", "CONFIG INFO sync-time").await,
        [
            "304-parameter=sync-time",
            "304-value=3600",
            "304-description=Time in seconds between the beginnings of successive sync operations",
            "304-defaultValue=3600",
            "304-scope=network",
            "304 effective=closeopen",
        ]
    );
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "repair",
            "CONFIG OBGET //HARNESS/254 global-event-level",
        )
        .await,
        ["408 Operation failed: config parameter not found"]
    );
    assert_eq!(
        command(&mut reader, &mut writer, "locked", "CONFIG SET sync-time 5").await,
        ["420 LOGIN required"]
    );
    assert_eq!(
        command(&mut reader, &mut writer, "login", &format!("LOGIN {TOKEN}")).await,
        ["200 OK"]
    );

    // The initial configured status sweep may still be draining while these
    // local commands run. Exclude that independently scheduled traffic and
    // pin that CONFIG itself creates no other PCI frame.
    let frames_before = sys
        .pci
        .frames()
        .iter()
        .filter(|frame| !is_status_request(&frame.payload))
        .count();
    for (tag, text, expected) in [
        ("g1", "CONFIG OBSET global sync-time 7", "200 OK."),
        ("gs", "CONFIG SAVE global retained.conf", "200 OK."),
        ("g2", "CONFIG OBSET global sync-time 8", "200 OK."),
        ("gl", "CONFIG LOAD global retained.conf", "200 OK."),
        ("p1", "CONFIG SET sync-time \"two words\"", "200 OK."),
        ("ps", "CONFIG SAVE project", "200 OK."),
        ("p2", "CONFIG SET sync-time changed", "200 OK."),
        ("pl", "CONFIG LOAD project", "200 OK."),
    ] {
        assert_eq!(
            command(&mut reader, &mut writer, tag, text)
                .await
                .last()
                .unwrap(),
            expected,
            "{text}"
        );
    }
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "global-read",
            "CONFIG OBGET global sync-time",
        )
        .await,
        ["303 sync-time=7"]
    );
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "project-read",
            "CONFIG OBGET project sync-time",
        )
        .await,
        ["303 sync-time=two words"]
    );
    assert_eq!(
        sys.pci
            .frames()
            .iter()
            .filter(|frame| !is_status_request(&frame.payload))
            .count(),
        frames_before
    );

    let payload = "053800790149";
    let before = sys.pci.count_payload(payload);
    sys.broker
        .inject("homeassistant/light/cbus_1/set", br#"{"state":"ON"}"#);
    require(COMMAND_DRAIN, "MQTT command after CONFIG workflow", || {
        sys.pci.count_payload(payload) > before
    })
    .await;
    assert!(sys.daemon.is_running());

    drop(reader);
    drop(writer);
    drop(sys);

    let mut restarted = start_with(options(&state, &token)).await;
    wait_started(&restarted).await;
    let (mut reader, mut writer) = connect(&restarted).await;
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "restart-global",
            "CONFIG OBGET global sync-time",
        )
        .await,
        ["303 sync-time=7"]
    );
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "restart-project",
            "CONFIG OBGET project sync-time",
        )
        .await,
        ["303 sync-time=two words"]
    );
    assert!(restarted.daemon.is_running());
    drop(restarted);
    std::fs::remove_file(state).unwrap();
    std::fs::remove_file(token).unwrap();
}
