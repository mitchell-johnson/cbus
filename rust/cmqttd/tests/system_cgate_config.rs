//! Real cmqttd process: the complete maintained C-Gate CONFIG family uses the
//! local atomic repository, never the shared PCI, and leaves MQTT operational.

mod util;

use std::time::Duration;
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
async fn project_start_samples_valid_durable_names_at_restart_and_keeps_mqtt_live() {
    let native: serde_json::Value = serde_json::from_str(include_str!(
        "../../testdata/fixtures/native_cgate_config_project_start.json"
    ))
    .unwrap();
    assert_eq!(native["schema"], "native-cgate-config-project-start-v1");
    for child in [
        "seed",
        "single_start",
        "saved_restart",
        "multiple_start",
        "missing_start",
    ] {
        assert_eq!(
            native["oracle"]["children"][child]["cleanup_complete"],
            true
        );
    }
    for line in include_str!("../../testdata/vectors/cgate_config_project_start.jsonl").lines() {
        let vector: serde_json::Value = serde_json::from_str(line).unwrap();
        let case = vector["case"].as_str().unwrap();
        let phase = vector["phase"].as_str().unwrap();
        let index = vector["index"].as_u64().unwrap() as usize;
        let captured = native[case][phase][index]["response"]
            .as_array()
            .unwrap()
            .iter()
            .map(|row| row.as_str().unwrap().split_once("] ").unwrap().1)
            .collect::<Vec<_>>();
        let expected = vector["reply"]
            .as_array()
            .unwrap()
            .iter()
            .map(|row| row.as_str().unwrap())
            .collect::<Vec<_>>();
        assert_eq!(captured, expected, "{}", vector["id"]);
    }

    let state = cbus_test_support::proc::temp_path("cgate-start-project.json");
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
    for name in ["XSTARTA", "XSTARTB"] {
        assert_eq!(
            command(
                &mut reader,
                &mut writer,
                "new",
                &format!("PROJECT NEW {name}")
            )
            .await,
            ["200 OK."]
        );
    }
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "start",
            "CONFIG SET project.start XSTARTA XMISSING XSTARTB"
        )
        .await,
        ["200 OK."]
    );
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "default",
            "CONFIG SET project.default XSTARTB"
        )
        .await,
        ["200 OK."]
    );
    drop((reader, writer, first));

    let mut second = start_with(options()).await;
    wait_started(&second).await;
    let (mut reader, mut writer) = connect(&second).await;
    assert_eq!(
        command(&mut reader, &mut writer, "list", "PROJECT LIST").await,
        [
            "123-project=XSTARTA state=started",
            "123 project=XSTARTB state=started"
        ]
    );
    assert_eq!(
        command(&mut reader, &mut writer, "use", "PROJECT USE").await,
        ["123 project=XSTARTB"]
    );
    let frames_before = second
        .pci
        .frames()
        .iter()
        .filter(|frame| !is_status_request(&frame.payload))
        .count();
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "save",
            "CONFIG SAVE global retained.conf"
        )
        .await,
        ["200 OK."]
    );
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "set",
            "CONFIG SET project.start XSTARTB"
        )
        .await,
        ["200 OK."]
    );
    assert_eq!(
        command(&mut reader, &mut writer, "read", "CONFIG GET project.start").await,
        ["303 project.start=XSTARTB"]
    );
    assert_eq!(
        command(&mut reader, &mut writer, "still", "PROJECT LIST").await,
        [
            "123-project=XSTARTA state=started",
            "123 project=XSTARTB state=started"
        ]
    );
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "load",
            "CONFIG LOAD global retained.conf"
        )
        .await,
        ["200 OK."]
    );
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "restored",
            "CONFIG GET project.start"
        )
        .await,
        ["303 project.start=XSTARTA XMISSING XSTARTB"]
    );
    assert_eq!(
        command(&mut reader, &mut writer, "stop", "PROJECT STOP XSTARTA").await,
        ["200 OK."]
    );
    assert_eq!(
        command(&mut reader, &mut writer, "stopped", "PROJECT LIST").await,
        [
            "123-project=XSTARTA state=stopped",
            "123 project=XSTARTB state=started"
        ]
    );
    assert_eq!(
        command(&mut reader, &mut writer, "close-b", "PROJECT CLOSE XSTARTB").await,
        ["200 OK"]
    );
    assert_eq!(
        command(&mut reader, &mut writer, "load-b", "PROJECT LOAD XSTARTB").await,
        ["200 OK."]
    );
    assert_eq!(
        command(&mut reader, &mut writer, "loaded", "PROJECT LIST").await,
        [
            "123-project=XSTARTA state=stopped",
            "123 project=XSTARTB state=stopped"
        ]
    );
    assert_eq!(
        second
            .pci
            .frames()
            .iter()
            .filter(|frame| !is_status_request(&frame.payload))
            .count(),
        frames_before
    );
    let payload = "053800790149";
    let before = second.pci.count_payload(payload);
    second
        .broker
        .inject("homeassistant/light/cbus_1/set", br#"{"state":"ON"}"#);
    require(
        COMMAND_DRAIN,
        "MQTT command after project.start lifecycle",
        || second.pci.count_payload(payload) > before,
    )
    .await;
    assert!(second.daemon.is_running());
    drop((reader, writer, second));

    let third = start_with(options()).await;
    wait_started(&third).await;
    let (mut reader, mut writer) = connect(&third).await;
    assert_eq!(
        command(&mut reader, &mut writer, "again", "PROJECT LIST").await,
        [
            "123-project=XSTARTA state=started",
            "123 project=XSTARTB state=started"
        ]
    );
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "missing",
            "CONFIG SET project.start XMISSING"
        )
        .await,
        ["200 OK."]
    );
    drop((reader, writer, third));

    let fourth = start_with(options()).await;
    wait_started(&fourth).await;
    let (mut reader, mut writer) = connect(&fourth).await;
    assert_eq!(
        command(&mut reader, &mut writer, "none", "PROJECT LIST").await,
        ["124 no projects found"]
    );
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "stored",
            "CONFIG GET project.start"
        )
        .await,
        ["303 project.start=XMISSING"]
    );
    drop((reader, writer, fourth));
    std::fs::remove_file(state).unwrap();
}

#[tokio::test]
async fn project_default_selects_loaded_project_only_after_restart_without_interrupting_mqtt() {
    let native: serde_json::Value = serde_json::from_str(include_str!(
        "../../testdata/fixtures/native_cgate_config_project_default.json"
    ))
    .unwrap();
    assert_eq!(native["schema"], "native-cgate-config-project-default-v1");
    assert_eq!(native["oracle"]["first_child"]["cleanup_complete"], true);
    assert_eq!(native["oracle"]["second_child"]["cleanup_complete"], true);
    for line in include_str!("../../testdata/vectors/cgate_config_project_default.jsonl").lines() {
        let vector: serde_json::Value = serde_json::from_str(line).unwrap();
        let child = vector["native_child"].as_str().unwrap();
        let index = vector["native_index"].as_u64().unwrap() as usize;
        let captured = native[child][index]["response"][0].as_str().unwrap();
        assert_eq!(
            captured.split_once("] ").unwrap().1,
            vector["reply"].as_str().unwrap(),
            "{}",
            vector["id"]
        );
    }

    let state = cbus_test_support::proc::temp_path("cgate-default-project.json");
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
        command(&mut reader, &mut writer, "initial", "PROJECT USE").await,
        ["123 project=null"]
    );
    assert_eq!(
        command(&mut reader, &mut writer, "create", "PROJECT NEW XDFLT").await,
        ["200 OK."]
    );
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "set",
            "CONFIG SET project.default XDFLT"
        )
        .await,
        ["200 OK."]
    );
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "read",
            "CONFIG GET project.default"
        )
        .await,
        ["303 project.default=XDFLT"]
    );
    let (mut pending_reader, mut pending_writer) = connect(&first).await;
    assert_eq!(
        command(
            &mut pending_reader,
            &mut pending_writer,
            "pending",
            "PROJECT USE"
        )
        .await,
        ["123 project=null"]
    );
    drop((reader, writer, pending_reader, pending_writer, first));

    let mut second = start_with(options()).await;
    wait_started(&second).await;
    let (mut reader, mut writer) = connect(&second).await;
    assert_eq!(
        command(&mut reader, &mut writer, "loaded", "PROJECT USE").await,
        ["123 project=XDFLT"]
    );
    let frames_before = second
        .pci
        .frames()
        .iter()
        .filter(|frame| !is_status_request(&frame.payload))
        .count();
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "set-later",
            "CONFIG SET project.default XOTHER"
        )
        .await,
        ["200 OK."]
    );
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "read-later",
            "CONFIG GET project.default"
        )
        .await,
        ["303 project.default=XOTHER"]
    );
    let (mut next_reader, mut next_writer) = connect(&second).await;
    assert_eq!(
        command(&mut next_reader, &mut next_writer, "still", "PROJECT USE").await,
        ["123 project=XDFLT"]
    );
    assert_eq!(
        command(&mut reader, &mut writer, "switch", "PROJECT USE HARNESS").await,
        ["200 OK."]
    );
    assert_eq!(
        command(&mut reader, &mut writer, "switched", "PROJECT USE").await,
        ["123 project=HARNESS"]
    );
    assert_eq!(
        command(
            &mut next_reader,
            &mut next_writer,
            "independent",
            "PROJECT USE"
        )
        .await,
        ["123 project=XDFLT"]
    );
    assert_eq!(
        second
            .pci
            .frames()
            .iter()
            .filter(|frame| !is_status_request(&frame.payload))
            .count(),
        frames_before
    );
    let payload = "053800790149";
    let before = second.pci.count_payload(payload);
    second
        .broker
        .inject("homeassistant/light/cbus_1/set", br#"{"state":"ON"}"#);
    require(
        COMMAND_DRAIN,
        "MQTT command after project.default selection",
        || second.pci.count_payload(payload) > before,
    )
    .await;
    assert!(second.daemon.is_running());
    drop((reader, writer, next_reader, next_writer, second));

    // The saved value is still visible, but an absent target project cannot
    // become a session default after the next restart.
    let third = start_with(options()).await;
    wait_started(&third).await;
    let (mut reader, mut writer) = connect(&third).await;
    assert_eq!(
        command(&mut reader, &mut writer, "missing", "PROJECT USE").await,
        ["123 project=null"]
    );
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "stored",
            "CONFIG GET project.default"
        )
        .await,
        ["303 project.default=XOTHER"]
    );
    assert_eq!(
        command(&mut reader, &mut writer, "later-load", "PROJECT NEW XOTHER").await,
        ["200 OK."]
    );
    let (mut later_reader, mut later_writer) = connect(&third).await;
    assert_eq!(
        command(
            &mut later_reader,
            &mut later_writer,
            "now-loaded",
            "PROJECT USE"
        )
        .await,
        ["123 project=XOTHER"]
    );
    drop((reader, writer, later_reader, later_writer, third));
    std::fs::remove_file(state).unwrap();
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
    assert_eq!(capabilities["config_event_transport_server"], true);
    assert_eq!(capabilities["config_event_transport_socket"], true);
    assert_eq!(capabilities["config_event_catalogue_complete"], false);
    assert_eq!(
        capabilities["config_restart_effects"],
        serde_json::json!([
            "command.show-responses",
            "command.show-time",
            "event-host",
            "event-millis",
            "event-mode",
            "event-port",
            "global-event-level",
            "heartbeat-time",
            "project.default",
            "project.start"
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
            "EVENT e9s0c0",
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

async fn next_heartbeat(
    reader: &mut BufReader<tokio::net::tcp::OwnedReadHalf>,
    native_wire: &str,
) -> std::time::Instant {
    tokio::time::timeout(Duration::from_secs(5), async {
        loop {
            let mut line = String::new();
            assert_ne!(reader.read_line(&mut line).await.unwrap(), 0);
            let Some(body) = line.strip_prefix("#e# ") else {
                continue;
            };
            let Some((timestamp, payload)) = body.trim_end().split_once(' ') else {
                continue;
            };
            if payload != "700 cgate - Heartbeat." {
                continue;
            }
            chrono::NaiveDateTime::parse_from_str(timestamp, "%Y%m%d-%H%M%S%.3f").unwrap();
            assert_eq!(native_wire, "#e# <timestamp> 700 cgate - Heartbeat.");
            return std::time::Instant::now();
        }
    })
    .await
    .expect("native-shaped C-Gate heartbeat was not delivered")
}

async fn assert_no_heartbeat(
    reader: &mut BufReader<tokio::net::tcp::OwnedReadHalf>,
    interval: Duration,
) {
    let deadline = tokio::time::Instant::now() + interval;
    loop {
        let mut line = String::new();
        match tokio::time::timeout_at(deadline, reader.read_line(&mut line)).await {
            Err(_) => return,
            Ok(Ok(0)) => panic!("C-Gate event connection closed"),
            Ok(Ok(_)) => assert!(!line.contains(" 700 cgate - Heartbeat."), "{line}"),
            Ok(Err(error)) => panic!("C-Gate event read failed: {error}"),
        }
    }
}

#[tokio::test]
async fn heartbeat_time_uses_native_envelope_and_changes_only_on_restart() {
    let native: serde_json::Value = serde_json::from_str(include_str!(
        "../../testdata/fixtures/native_cgate_config_heartbeat.json"
    ))
    .unwrap();
    let cases = native["cases"].as_array().unwrap();
    assert_eq!(cases.len(), 3);
    assert_eq!(cases[0]["before_set"]["count"], 0);
    assert_eq!(cases[1]["startup_heartbeat_time"], "1");
    assert_eq!(cases[2]["startup_heartbeat_time"], "2");
    assert_eq!(cases[1]["set_reply"], "[set] 200 OK.");
    assert_eq!(cases[1]["readback_reply"], "[get] 303 heartbeat-time=0");
    let native_wire = cases[1]["before_set"]["normalized_wire"].as_str().unwrap();
    assert_eq!(cases[2]["before_set"]["normalized_wire"], native_wire);

    let state = cbus_test_support::proc::temp_path("cgate-heartbeat-config.json");
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
    let (mut monitor, mut subscription) = connect(&first).await;
    assert_eq!(
        command(&mut monitor, &mut subscription, "event", "EVENT e9s0c0").await,
        ["200 OK."]
    );
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "one",
            "CONFIG SET heartbeat-time 1"
        )
        .await,
        ["200 OK."]
    );
    assert_no_heartbeat(&mut monitor, Duration::from_millis(1300)).await;
    drop((reader, writer, monitor, subscription, first));

    let mut second = start_with(options()).await;
    wait_started(&second).await;
    let (mut reader, mut writer) = connect(&second).await;
    let (mut monitor, mut subscription) = connect(&second).await;
    assert_eq!(
        command(&mut monitor, &mut subscription, "event", "EVENT e9s0c0").await,
        ["200 OK."]
    );
    let first_beat = next_heartbeat(&mut monitor, native_wire).await;
    let second_beat = next_heartbeat(&mut monitor, native_wire).await;
    assert!((0.6..1.5).contains(&second_beat.duration_since(first_beat).as_secs_f64()));
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "two",
            "CONFIG SET heartbeat-time 2"
        )
        .await,
        ["200 OK."]
    );
    let next = next_heartbeat(&mut monitor, native_wire).await;
    let next_after = next_heartbeat(&mut monitor, native_wire).await;
    assert!((0.6..1.5).contains(&next_after.duration_since(next).as_secs_f64()));
    let payload = "053800790149";
    let before = second.pci.count_payload(payload);
    second
        .broker
        .inject("homeassistant/light/cbus_1/set", br#"{"state":"ON"}"#);
    require(
        COMMAND_DRAIN,
        "MQTT command during C-Gate heartbeat",
        || second.pci.count_payload(payload) > before,
    )
    .await;
    assert!(second.daemon.is_running());
    drop((reader, writer, monitor, subscription, second));

    let third = start_with(options()).await;
    wait_started(&third).await;
    let (mut reader, mut writer) = connect(&third).await;
    let (mut monitor, mut subscription) = connect(&third).await;
    assert_eq!(
        command(&mut monitor, &mut subscription, "event", "EVENT e9s0c0").await,
        ["200 OK."]
    );
    let first_beat = next_heartbeat(&mut monitor, native_wire).await;
    let second_beat = next_heartbeat(&mut monitor, native_wire).await;
    assert!((1.5..2.7).contains(&second_beat.duration_since(first_beat).as_secs_f64()));
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "zero",
            "CONFIG SET heartbeat-time 0"
        )
        .await,
        ["200 OK."]
    );
    next_heartbeat(&mut monitor, native_wire).await;
    drop((reader, writer, monitor, subscription, third));

    let fourth = start_with(options()).await;
    wait_started(&fourth).await;
    let (mut monitor, mut subscription) = connect(&fourth).await;
    assert_eq!(
        command(&mut monitor, &mut subscription, "event", "EVENT e9s0c0").await,
        ["200 OK."]
    );
    assert_no_heartbeat(&mut monitor, Duration::from_millis(2300)).await;
    drop((monitor, subscription, fourth));
    std::fs::remove_file(state).unwrap();
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

async fn event_containing(
    reader: &mut BufReader<tokio::net::tcp::OwnedReadHalf>,
    needle: &str,
    limit: Duration,
) -> Option<String> {
    tokio::time::timeout(limit, async {
        loop {
            let mut line = String::new();
            assert_ne!(reader.read_line(&mut line).await.unwrap(), 0);
            if line.contains(needle) {
                return line.trim_end_matches(['\r', '\n']).to_string();
            }
        }
    })
    .await
    .ok()
}

#[tokio::test]
async fn config_global_event_level_filters_only_cgate_delivery_after_restart() {
    let state = cbus_test_support::proc::temp_path("cgate-global-event-level.json");
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
    let (mut producer, mut writer) = connect(&first).await;
    let (mut plus, mut plus_writer) = connect(&first).await;
    assert_eq!(
        command(&mut plus, &mut plus_writer, "plus", "EVENT e+s0c0").await,
        ["200 OK."]
    );
    let before_pci = first
        .pci
        .frames()
        .iter()
        .filter(|frame| !is_status_request(&frame.payload))
        .count();
    assert_eq!(
        command(
            &mut producer,
            &mut writer,
            "before",
            "BROADCAST_EVENT XX class before-change"
        )
        .await,
        ["200 OK."]
    );
    let event = event_containing(&mut plus, "broadcast_event XX class before-change", STARTUP)
        .await
        .expect("startup level 5 admits 703");
    assert!(!event.starts_with("#e# ") && event.contains(" 703 "));
    assert_eq!(
        command(
            &mut producer,
            &mut writer,
            "set-zero",
            "CONFIG SET global-event-level 0"
        )
        .await,
        ["200 OK."]
    );
    assert_eq!(
        command(
            &mut producer,
            &mut writer,
            "read-zero",
            "CONFIG GET global-event-level"
        )
        .await,
        ["303 global-event-level=0"]
    );
    assert_eq!(
        command(
            &mut producer,
            &mut writer,
            "still-five",
            "BROADCAST_EVENT XX class still-startup-five"
        )
        .await,
        ["200 OK."]
    );
    assert!(event_containing(
        &mut plus,
        "broadcast_event XX class still-startup-five",
        STARTUP
    )
    .await
    .is_some());
    assert_eq!(
        first
            .pci
            .frames()
            .iter()
            .filter(|frame| !is_status_request(&frame.payload))
            .count(),
        before_pci
    );
    drop((producer, writer, plus, plus_writer, first));

    let mut second = start_with(options()).await;
    wait_started(&second).await;
    let (mut producer, mut writer) = connect(&second).await;
    let (mut plus, mut plus_writer) = connect(&second).await;
    let (mut explicit, mut explicit_writer) = connect(&second).await;
    assert_eq!(
        command(&mut plus, &mut plus_writer, "plus", "EVENT e+s0c0").await,
        ["200 OK."]
    );
    assert_eq!(
        command(&mut explicit, &mut explicit_writer, "nine", "EVENT e9s0c0").await,
        ["200 OK."]
    );
    let before_pci = second
        .pci
        .frames()
        .iter()
        .filter(|frame| !is_status_request(&frame.payload))
        .count();
    assert_eq!(
        command(
            &mut producer,
            &mut writer,
            "zero",
            "BROADCAST_EVENT XX class startup-zero"
        )
        .await,
        ["200 OK."]
    );
    let explicit_event = event_containing(
        &mut explicit,
        "broadcast_event XX class startup-zero",
        STARTUP,
    )
    .await
    .expect("explicit e9 overrides startup global level 0");
    assert!(explicit_event.starts_with("#e# ") && explicit_event.contains(" 703 "));
    assert!(event_containing(
        &mut plus,
        "broadcast_event XX class startup-zero",
        Duration::from_millis(250)
    )
    .await
    .is_none());
    assert_eq!(
        command(
            &mut producer,
            &mut writer,
            "set-nine",
            "CONFIG SET global-event-level 9"
        )
        .await,
        ["200 OK."]
    );
    assert_eq!(
        command(
            &mut producer,
            &mut writer,
            "read-nine",
            "CONFIG GET global-event-level"
        )
        .await,
        ["303 global-event-level=9"]
    );
    assert_eq!(
        command(
            &mut producer,
            &mut writer,
            "still-zero",
            "BROADCAST_EVENT XX class still-startup-zero"
        )
        .await,
        ["200 OK."]
    );
    assert!(event_containing(
        &mut explicit,
        "broadcast_event XX class still-startup-zero",
        STARTUP
    )
    .await
    .is_some());
    assert!(event_containing(
        &mut plus,
        "broadcast_event XX class still-startup-zero",
        Duration::from_millis(250)
    )
    .await
    .is_none());
    assert_eq!(
        second
            .pci
            .frames()
            .iter()
            .filter(|frame| !is_status_request(&frame.payload))
            .count(),
        before_pci
    );

    // C-Gate event suppression must not affect physical observations, MQTT
    // state, command delivery, or the C-Gate live-level cache.
    second.pci.inject(&pci_wire(&[5, 4, 56, 0, 121, 1]));
    require(
        STARTUP,
        "physical state through MQTT at C-Gate level zero",
        || {
            second
                .broker
                .retained("homeassistant/light/cbus_1/state")
                .is_some_and(|payload| {
                    let payload = parse_json(&payload);
                    payload["state"] == "ON" && payload["cbus_source_addr"] == 4
                })
        },
    )
    .await;
    assert!(command(
        &mut producer,
        &mut writer,
        "level",
        "GET //HARNESS/254/56/1 level"
    )
    .await
    .iter()
    .any(|line| line.contains("level=255")));
    let outbound = second.pci.count_payload("0538000101C1");
    second
        .broker
        .inject("homeassistant/light/cbus_1/set", br#"{"state":"OFF"}"#);
    require(COMMAND_DRAIN, "MQTT command at C-Gate level zero", || {
        second.pci.count_payload("0538000101C1") > outbound
    })
    .await;
    assert!(second.daemon.is_running());
    drop((
        producer,
        writer,
        plus,
        plus_writer,
        explicit,
        explicit_writer,
        second,
    ));

    let third = start_with(options()).await;
    wait_started(&third).await;
    let (mut producer, mut writer) = connect(&third).await;
    let (mut plus, mut plus_writer) = connect(&third).await;
    assert_eq!(
        command(&mut plus, &mut plus_writer, "plus", "EVENT e+s0c0").await,
        ["200 OK."]
    );
    assert_eq!(
        command(
            &mut producer,
            &mut writer,
            "final",
            "BROADCAST_EVENT XX class startup-nine"
        )
        .await,
        ["200 OK."]
    );
    let trace = event_containing(&mut plus, "Command: [final] BROADCAST_EVENT", STARTUP)
        .await
        .expect("startup level 9 admits command traces");
    assert!(!trace.starts_with("#e# ") && trace.contains(" 761 "));
    assert!(
        event_containing(&mut plus, "broadcast_event XX class startup-nine", STARTUP)
            .await
            .is_some()
    );
    drop((producer, writer, plus, plus_writer, third));
    std::fs::remove_file(state).unwrap();
}

#[tokio::test]
async fn malformed_global_event_level_disables_only_optional_cgate_listener() {
    let native: serde_json::Value = serde_json::from_str(include_str!(
        "../../testdata/fixtures/native_cgate_config_global_event_level.json"
    ))
    .unwrap();
    for (index, value) in ["abc", ""].iter().enumerate() {
        let evidence = &native["malformed_startups"][index];
        assert_eq!(evidence["startup_value"], *value);
        assert_eq!(evidence["number_format_exception"], true);
        assert_eq!(evidence["command_listeners_opened"], false);
        assert_eq!(evidence["owned_child_cleanup_complete"], true);
        let state = cbus_test_support::proc::temp_path("cgate-global-invalid.json");
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
                "set",
                &format!("CONFIG SET global-event-level {value}")
            )
            .await,
            ["200 OK."]
        );
        assert_eq!(
            command(
                &mut reader,
                &mut writer,
                "get",
                "CONFIG GET global-event-level"
            )
            .await,
            [format!("303 global-event-level={value}")]
        );
        drop((reader, writer, first));

        let mut second = start_with(options()).await;
        wait_started(&second).await;
        require(STARTUP, "invalid C-Gate setting diagnostic", || {
            second.daemon.stderr().contains(
                "C-Gate listener disabled: saved CONFIG global-event-level is not a valid integer",
            )
        })
        .await;
        assert!(!second
            .daemon
            .stderr()
            .contains("C-Gate service listening on"));
        let outbound = second.pci.count_payload("053800790149");
        second
            .broker
            .inject("homeassistant/light/cbus_1/set", br#"{"state":"ON"}"#);
        require(
            COMMAND_DRAIN,
            "MQTT command with disabled C-Gate listener",
            || second.pci.count_payload("053800790149") > outbound,
        )
        .await;
        second.pci.inject(&pci_wire(&[5, 4, 56, 0, 121, 1]));
        require(
            STARTUP,
            "physical MQTT state with disabled C-Gate listener",
            || {
                second
                    .broker
                    .retained("homeassistant/light/cbus_1/state")
                    .is_some_and(|payload| {
                        let payload = parse_json(&payload);
                        payload["state"] == "ON" && payload["cbus_source_addr"] == 4
                    })
            },
        )
        .await;
        assert!(second.daemon.is_running());
        drop(second);
        std::fs::remove_file(state).unwrap();
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
