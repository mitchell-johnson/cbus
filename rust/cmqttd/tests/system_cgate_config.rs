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
    let capabilities = command(&mut reader, &mut writer, "caps", "CMQTT CAPABILITIES").await;
    let capabilities: serde_json::Value =
        serde_json::from_str(capabilities[0].strip_prefix("200-").unwrap()).unwrap();
    assert_eq!(
        capabilities["config_restart_effects"],
        serde_json::json!([
            "command.show-responses",
            "command.show-time",
            "event-millis"
        ])
    );

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
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "show-time",
            "CONFIG SET command.show-time yes",
        )
        .await,
        ["200 OK."]
    );
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "hide-responses",
            "CONFIG SET command.show-responses no",
        )
        .await,
        ["200 OK."]
    );

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
    let (mut event_reader, mut event_writer) = connect(&restarted).await;
    assert_eq!(
        command(
            &mut event_reader,
            &mut event_writer,
            "subscribe",
            "EVENT e7s0c0",
        )
        .await,
        ["200 OK."]
    );
    assert_eq!(
        command(&mut reader, &mut writer, "timed", "NOOP").await,
        ["200 OK"]
    );
    let (timed, trace) = tokio::time::timeout(std::time::Duration::from_secs(2), async {
        let mut trace = Vec::new();
        loop {
            let mut line = String::new();
            event_reader.read_line(&mut line).await.unwrap();
            if line.contains("Command: [timed]") || line.contains("Response: [timed]") {
                trace.push(line.trim_end_matches(['\r', '\n']).to_string());
            }
            if line.contains("commandId=timed time=") {
                break (line, trace);
            }
        }
    })
    .await
    .expect("restarted listener did not publish CONFIG command timing");
    let timed = timed.trim_end_matches(['\r', '\n']);
    let (timestamp, payload) = timed
        .strip_prefix("#e# ")
        .unwrap()
        .split_once(" 767 cmd")
        .unwrap();
    chrono::NaiveDateTime::parse_from_str(timestamp, "%Y%m%d-%H%M%S%.3f").unwrap();
    let (_, milliseconds) = payload.split_once(" - commandId=timed time=").unwrap();
    milliseconds.parse::<u128>().unwrap();
    assert_eq!(trace.len(), 1, "startup no suppresses 766 response events");
    assert!(trace[0].contains(" 761 cmd"));
    assert!(trace[0].ends_with(" - Command: [timed] NOOP"));
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "login-again",
            &format!("LOGIN {TOKEN}")
        )
        .await,
        ["200 OK"]
    );
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "show-responses",
            "CONFIG SET command.show-responses yes",
        )
        .await,
        ["200 OK."]
    );
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "read-responses",
            "CONFIG GET command.show-responses",
        )
        .await,
        ["303 command.show-responses=yes"]
    );
    assert!(restarted.daemon.is_running());
    drop(event_reader);
    drop(event_writer);
    drop(reader);
    drop(writer);
    drop(restarted);

    let mut enabled = start_with(options(&state, &token)).await;
    wait_started(&enabled).await;
    let (mut reader, mut writer) = connect(&enabled).await;
    let (mut event_reader, mut event_writer) = connect(&enabled).await;
    assert_eq!(
        command(
            &mut event_reader,
            &mut event_writer,
            "subscribe",
            "EVENT e9s0c0"
        )
        .await,
        ["200 OK."]
    );
    let info = command(
        &mut reader,
        &mut writer,
        "multi",
        "CONFIG INFO allow-fast-start",
    )
    .await;
    let native: serde_json::Value = serde_json::from_str(include_str!(
        "../../testdata/fixtures/native_cgate_config_command_show_responses.json"
    ))
    .unwrap();
    let expected = native["cases"]["startup_default"][2]["response"]
        .as_array()
        .unwrap()
        .iter()
        .map(|row| {
            row.as_str()
                .unwrap()
                .trim_start_matches("[info-network] ")
                .to_string()
        })
        .collect::<Vec<_>>();
    assert_eq!(info, expected);
    let trace = tokio::time::timeout(std::time::Duration::from_secs(2), async {
        let mut trace = Vec::new();
        while trace.len() < info.len() + 1 {
            let mut line = String::new();
            assert_ne!(event_reader.read_line(&mut line).await.unwrap(), 0);
            if line.contains("Command: [multi]") || line.contains("Response: [multi]") {
                trace.push(line.trim_end_matches(['\r', '\n']).to_string());
            }
        }
        trace
    })
    .await
    .expect("native 761/766 CONFIG trace did not arrive");
    assert!(trace[0].contains(" 761 cmd"));
    assert!(trace[0].ends_with(" - Command: [multi] CONFIG INFO allow-fast-start"));
    for (event, response) in trace[1..].iter().zip(&info) {
        assert!(event.contains(" 766 cmd"));
        assert!(event.ends_with(&format!(" - Response: [multi] {response}")));
    }
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "secret",
            &format!("LOGIN {TOKEN}")
        )
        .await,
        ["200 OK"]
    );
    let redacted = tokio::time::timeout(std::time::Duration::from_secs(2), async {
        let mut redacted = Vec::new();
        while redacted.len() < 2 {
            let mut line = String::new();
            assert_ne!(event_reader.read_line(&mut line).await.unwrap(), 0);
            if line.contains("[secret] <redacted command>")
                || line.contains(" - Response: <redacted>")
            {
                redacted.push(line);
            }
        }
        redacted
    })
    .await
    .expect("credential event redaction did not arrive");
    assert!(redacted.iter().all(|line| !line.contains(TOKEN)));
    let payload = "053800790149";
    let before = enabled.pci.count_payload(payload);
    enabled
        .broker
        .inject("homeassistant/light/cbus_1/set", br#"{"state":"ON"}"#);
    require(COMMAND_DRAIN, "MQTT command after CONFIG restart", || {
        enabled.pci.count_payload(payload) > before
    })
    .await;
    assert!(enabled.daemon.is_running());
    drop(enabled);
    std::fs::remove_file(state).unwrap();
    std::fs::remove_file(token).unwrap();
}

async fn assert_broadcast_event_precision(sys: &System, tag: &str, milliseconds: bool) {
    let (mut subscriber, mut subscription) = connect(sys).await;
    assert_eq!(
        command(&mut subscriber, &mut subscription, "events", "EVENT e9s0c0").await,
        ["200 OK."]
    );
    let (mut producer, mut writer) = connect(sys).await;
    assert_eq!(
        command(
            &mut producer,
            &mut writer,
            tag,
            "BROADCAST_EVENT XX class payload"
        )
        .await,
        ["200 OK."]
    );
    let expected = [
        (
            "761",
            format!("Command: [{tag}] BROADCAST_EVENT XX class payload"),
        ),
        ("703", "broadcast_event XX class payload".to_string()),
        ("766", format!("Response: [{tag}] 200 OK.")),
    ];
    let seen = tokio::time::timeout(std::time::Duration::from_secs(2), async {
        let mut seen = Vec::new();
        while seen.len() < expected.len() {
            let mut line = String::new();
            assert_ne!(subscriber.read_line(&mut line).await.unwrap(), 0);
            let line = line.trim_end_matches(['\r', '\n']);
            if expected.iter().any(|(_, text)| line.ends_with(text)) {
                seen.push(line.to_string());
            }
        }
        seen
    })
    .await
    .expect("broadcast event trace did not arrive");
    for (line, (code, text)) in seen.iter().zip(expected) {
        let (timestamp, payload) = line
            .strip_prefix("#e# ")
            .and_then(|body| body.split_once(' '))
            .unwrap();
        let format = if milliseconds {
            assert_eq!(timestamp.len(), 19, "{line}");
            "%Y%m%d-%H%M%S%.3f"
        } else {
            assert_eq!(timestamp.len(), 15, "{line}");
            "%Y%m%d-%H%M%S"
        };
        chrono::NaiveDateTime::parse_from_str(timestamp, format).unwrap();
        assert!(payload.starts_with(&format!("{code} cmd")), "{line}");
        assert!(payload.ends_with(&format!(" - {text}")), "{line}");
    }
}

#[tokio::test]
async fn event_millis_changes_only_after_daemon_restart() {
    let state = cbus_test_support::proc::temp_path("cgate-event-millis.json");
    let options = || Options {
        extra: vec![
            "--cgate-bind".into(),
            "127.0.0.1:0".into(),
            "--cgate-state".into(),
            state.to_string_lossy().into_owned(),
        ],
        ..Default::default()
    };

    let first = start_with(options()).await;
    wait_started(&first).await;
    let (mut reader, mut writer) = connect(&first).await;
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "set-no",
            "CONFIG SET event-millis no"
        )
        .await,
        ["200 OK."]
    );
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "read-no",
            "CONFIG GET event-millis"
        )
        .await,
        ["303 event-millis=no"]
    );
    assert_broadcast_event_precision(&first, "still-yes", true).await;
    drop(reader);
    drop(writer);
    drop(first);

    let second = start_with(options()).await;
    wait_started(&second).await;
    let (mut reader, mut writer) = connect(&second).await;
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "read-no",
            "CONFIG GET event-millis"
        )
        .await,
        ["303 event-millis=no"]
    );
    assert_broadcast_event_precision(&second, "startup-no", false).await;
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "set-yes",
            "CONFIG SET event-millis yes"
        )
        .await,
        ["200 OK."]
    );
    assert_broadcast_event_precision(&second, "still-no", false).await;
    drop(reader);
    drop(writer);
    drop(second);

    let mut third = start_with(options()).await;
    wait_started(&third).await;
    let (mut reader, mut writer) = connect(&third).await;
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "read-yes",
            "CONFIG GET event-millis"
        )
        .await,
        ["303 event-millis=yes"]
    );
    assert_broadcast_event_precision(&third, "startup-yes", true).await;
    assert!(third.daemon.is_running());
    drop(reader);
    drop(writer);
    drop(third);
    std::fs::remove_file(state).unwrap();
}
