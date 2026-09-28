//! Real cmqttd process: the maintained ACCESS family is role-aware, durable,
//! redacts credentials, never reaches the host filesystem or PCI, and repairs
//! the native unresolved-address connection-poisoning defect.

mod util;

use tokio::{
    io::{AsyncBufReadExt, AsyncWriteExt, BufReader},
    net::TcpStream,
};
use util::*;

const TOKEN: &str = "throwaway-access-system-token-0123456789abcdef";

async fn response(
    reader: &mut BufReader<tokio::net::tcp::OwnedReadHalf>,
    tag: &str,
) -> Vec<String> {
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
    response(reader, tag).await
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
    connect_at(sys, listener_address(sys)).await
}

fn listener_address(sys: &System) -> std::net::SocketAddr {
    sys.daemon
        .stderr()
        .lines()
        .find_map(|line| line.split_once("C-Gate service listening on "))
        .map(|(_, address)| address.trim().parse().unwrap())
        .unwrap()
}

async fn connect_at(
    sys: &System,
    address: std::net::SocketAddr,
) -> (
    BufReader<tokio::net::tcp::OwnedReadHalf>,
    tokio::net::tcp::OwnedWriteHalf,
) {
    require(STARTUP, "C-Gate listener", || {
        sys.daemon.stderr().contains("C-Gate service listening on ")
    })
    .await;
    let stream = TcpStream::connect(address).await.unwrap();
    let (reader, writer) = stream.into_split();
    let mut reader = BufReader::new(reader);
    let mut greeting = String::new();
    reader.read_line(&mut greeting).await.unwrap();
    assert_eq!(greeting, "201 cmqttd C-Gate service ready\r\n");
    (reader, writer)
}

fn options(state: &std::path::Path, token: &std::path::Path) -> Options {
    options_for(state, Some(token), "127.0.0.1:0")
}

fn options_for(state: &std::path::Path, token: Option<&std::path::Path>, bind: &str) -> Options {
    let mut extra = vec![
        "--cgate-bind".into(),
        bind.into(),
        "--cgate-state".into(),
        state.to_string_lossy().into_owned(),
    ];
    if let Some(token) = token {
        extra.extend([
            "--cgate-auth-file".into(),
            token.to_string_lossy().into_owned(),
        ]);
    }
    Options {
        extra,
        ..Default::default()
    }
}

fn non_loopback_ipv4() -> std::net::IpAddr {
    if_addrs::get_if_addrs()
        .unwrap()
        .into_iter()
        .map(|interface| interface.ip())
        .find(|address| address.is_ipv4() && !address.is_loopback() && !address.is_unspecified())
        .expect("system test requires one non-loopback IPv4 address")
}

#[tokio::test]
async fn access_family_is_redacted_sandboxed_durable_and_connection_safe() {
    let state = cbus_test_support::proc::temp_path("cgate-access.json");
    let token = cbus_test_support::proc::temp_path("cgate-access.token");
    std::fs::write(&token, format!("{TOKEN}\n")).unwrap();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&token, std::fs::Permissions::from_mode(0o600)).unwrap();
    }

    {
        let mut sys = start_with(options(&state, &token)).await;
        wait_started(&sys).await;
        let (mut reader, mut writer) = connect(&sys).await;
        let frames_before = sys
            .pci
            .frames()
            .iter()
            .filter(|frame| !is_status_request(&frame.payload))
            .count();

        assert_eq!(
            command(&mut reader, &mut writer, "query", "LOGIN").await,
            ["210 Access level: Clipsal"]
        );
        assert_eq!(
            command(
                &mut reader,
                &mut writer,
                "locked",
                "ACCESS ADD user operator private-password Max",
            )
            .await,
            ["420 LOGIN required"]
        );
        assert_eq!(
            command(&mut reader, &mut writer, "token", &format!("LOGIN {TOKEN}")).await,
            ["200 OK"]
        );
        assert_eq!(
            command(
                &mut reader,
                &mut writer,
                "add",
                "ACCESS ADD user operator private-password Max ignored",
            )
            .await,
            ["200 OK."]
        );
        assert_eq!(
            command(
                &mut reader,
                &mut writer,
                "badhost",
                "ACCESS ADD interface definitely-nohost.invalid Operate",
            )
            .await,
            ["408 Operation failed: Add failed: Can not resolve address 'definitely-nohost.invalid'."]
        );
        let list = command(&mut reader, &mut writer, "list", "ACCESS LIST").await;
        assert!(list
            .iter()
            .any(|line| line.contains("user operator <redacted> Max")));
        assert!(!list.iter().any(|line| line.contains("private-password")));

        assert_eq!(
            command(&mut reader, &mut writer, "save", "ACCESS SAVE policy.txt").await,
            ["200 OK."]
        );
        assert_eq!(
            command(
                &mut reader,
                &mut writer,
                "extra",
                "ACCESS ADD user temporary temporary-password Admin",
            )
            .await,
            ["200 OK."]
        );
        assert_eq!(
            command(&mut reader, &mut writer, "load", "ACCESS LOAD policy.txt").await,
            ["200 OK."]
        );
        let restored = command(&mut reader, &mut writer, "restored", "ACCESS LIST").await;
        assert!(!restored.iter().any(|line| line.contains("temporary")));
        assert_eq!(
            command(
                &mut reader,
                &mut writer,
                "escape",
                "ACCESS LOAD ../outside.txt"
            )
            .await,
            ["408 Operation failed: Access load failed: Illegal path: ../outside.txt"]
        );
        assert_eq!(
            command(
                &mut reader,
                &mut writer,
                "missing",
                "ACCESS LOAD missing.txt"
            )
            .await,
            ["408 Operation failed: Access load failed: Access control snapshot not found"]
        );

        // The vendor daemon refuses this connection after the unresolved ADD.
        // cmqttd validated before mutation, so a fresh connection remains live.
        let (mut second_reader, mut second_writer) = connect(&sys).await;
        assert_eq!(
            command(&mut second_reader, &mut second_writer, "live", "LOGIN").await,
            ["210 Access level: Clipsal"]
        );

        assert_eq!(
            command(&mut reader, &mut writer, "logout", "LOGOUT").await,
            ["200 OK"]
        );
        assert_eq!(
            command(
                &mut reader,
                &mut writer,
                "native",
                "LOGIN operator private-password",
            )
            .await,
            ["211 Access level set to: Max"]
        );

        let caps = command(&mut reader, &mut writer, "caps", "CMQTT CAPABILITIES").await;
        let caps: serde_json::Value =
            serde_json::from_str(caps[0].strip_prefix("200-").unwrap()).unwrap();
        assert_eq!(caps["access_commands"].as_array().unwrap().len(), 5);
        assert_eq!(caps["access_persistence"], "cmqttd-json");
        assert_eq!(caps["access_host_filesystem"], false);
        assert_eq!(caps["access_password_list_redacted"], true);
        assert_eq!(caps["access_unresolved_address_poisoning_repaired"], true);
        assert_eq!(caps["access_connection_admission"], true);
        assert_eq!(
            caps["access_admission_mode"],
            "compatibility-bootstrap-then-explicit"
        );
        assert_eq!(caps["access_token_recovery_admission"], true);
        assert_eq!(caps["access_global_command_level_matrix"], false);
        let floors = caps["access_native_handler_probe_levels"]
            .as_array()
            .unwrap();
        assert_eq!(floors.len(), 431);
        for (path, level) in [
            ("TREE", "Monitor"),
            ("PROJECT DIR", "Admin"),
            ("TRIGGER EVENT", "Program"),
            ("EVENT_CHANNEL LIST", "Program"),
            ("EVENT_CHANNEL SUB", "Program"),
            ("CGL IMPORT", "Program"),
            ("PP GET", "Clipsal"),
            ("PP RESET_TO_DEFAULTS", "Clipsal"),
            ("PROGRAMMER CREATE", "Program"),
            ("DEPLOY_QUEUE RETRY", "Program"),
            ("AUDIO DYNAMIC_1", "Operate"),
            ("SECURITY ARM", "Operate"),
            ("MEDIATRANSPORT PLAY", "Operate"),
            ("CONFIG LOAD", "Admin"),
            ("FILE DOWNLOAD", "Program"),
            ("LABEL KFIGET", "Program"),
            ("MEASUREMENT DATA", "Operate"),
            ("DALI RECALL_MAX", "Program"),
            ("DALI EMERGENCY INHIBIT", "Program"),
            ("DALI GATEWAY PROJECT_CUSTOM", "Program"),
            ("DALI SESSION GET", "Program"),
            ("PORT CNISCAN2", "Program"),
            ("ACCESS LIST", "Clipsal"),
            ("DBGETJSON NAC_TAGMAP", "Admin"),
            ("IDENTIFY ON", "Operate"),
            ("ACCESS ADD", "Clipsal"),
            ("CALCULATOR TEST", "Admin"),
            ("DBNEW", "Admin"),
            ("LOG EXTRACT", "Clipsal"),
            ("NET CHECK_UNRAVEL", "Program"),
            ("NEW", "Operate"),
            ("OID", "Operate"),
            ("REPORT", "Monitor"),
            ("TRANSFORM XML_TO_SQL", "Admin"),
            ("TEST_SPAM LIST", "Program"),
            ("ACCESS LOAD", "Clipsal"),
            ("AIRCON", "Operate"),
            ("FILE UPLOAD", "Program"),
            ("QUIT", "Connect"),
            ("SHUTDOWN", "Admin"),
            ("TEST_SPAM EREPORT", "Program"),
        ] {
            assert!(
                floors
                    .iter()
                    .any(|row| { row["path"] == path && row["minimum"] == level }),
                "missing native handler floor {path}={level}"
            );
        }

        let frames_after = sys
            .pci
            .frames()
            .iter()
            .filter(|frame| !is_status_request(&frame.payload))
            .count();
        assert_eq!(frames_after, frames_before);
        assert!(sys.daemon.is_running());
    }

    let state_text = std::fs::read_to_string(&state).unwrap();
    assert!(!state_text.contains("private-password"));
    assert!(!state_text.contains("temporary-password"));
    {
        let mut sys = start_with(options(&state, &token)).await;
        wait_started(&sys).await;
        let (mut reader, mut writer) = connect(&sys).await;
        assert_eq!(
            command(
                &mut reader,
                &mut writer,
                "restart",
                "LOGIN operator private-password",
            )
            .await,
            ["211 Access level set to: Max"]
        );
        let list = command(&mut reader, &mut writer, "list", "ACCESS LIST").await;
        assert!(list
            .iter()
            .any(|line| line.contains("user operator <redacted> Max")));
        assert!(sys.daemon.is_running());
    }

    std::fs::remove_file(state).unwrap();
    std::fs::remove_file(token).unwrap();
}

#[tokio::test]
async fn unprobed_native_floors_deny_over_real_tcp_without_pci_or_state_mutation() {
    let state = cbus_test_support::proc::temp_path("cgate-unprobed-access.json");
    let mut sys = start_with(options_for(&state, None, "127.0.0.1:0")).await;
    wait_started(&sys).await;
    let (mut reader, mut writer) = connect(&sys).await;

    for level in ["Connect", "Monitor", "Operate", "Admin", "Program", "Debug"] {
        let name = level.to_ascii_lowercase();
        let reply = command(
            &mut reader,
            &mut writer,
            &format!("setup-{name}"),
            &format!("ACCESS ADD user role-{name} pw-{name} {level}"),
        )
        .await;
        assert_eq!(reply, ["200 OK."]);
    }
    let before = std::fs::read(&state).unwrap();
    let frames_before = sys
        .pci
        .frames()
        .iter()
        .filter(|frame| !is_status_request(&frame.payload))
        .count();
    let vectors = include_str!("../../testdata/vectors/cgate_unprobed_authorization.jsonl")
        .lines()
        .map(|line| serde_json::from_str::<serde_json::Value>(line).unwrap())
        .collect::<Vec<_>>();
    assert_eq!(vectors.len(), 22);
    for (index, vector) in vectors.iter().enumerate() {
        let level = vector["denied_role"].as_str().unwrap();
        let name = level.to_ascii_lowercase();
        assert_eq!(
            command(
                &mut reader,
                &mut writer,
                &format!("login-{index}"),
                &format!("LOGIN role-{name} pw-{name}"),
            )
            .await,
            [format!("211 Access level set to: {level}")]
        );
        assert_eq!(
            command(
                &mut reader,
                &mut writer,
                &format!("deny-{index}"),
                vector["command"].as_str().unwrap(),
            )
            .await,
            ["420 Access denied."]
        );
    }
    assert_eq!(std::fs::read(&state).unwrap(), before);
    let frames_after = sys
        .pci
        .frames()
        .iter()
        .filter(|frame| !is_status_request(&frame.payload))
        .count();
    assert_eq!(frames_after, frames_before);
    assert!(sys.daemon.is_running());
    drop(sys);
    std::fs::remove_file(state).unwrap();
}

#[tokio::test]
async fn dali_native_role_vectors_hold_on_the_real_cgate_listener() {
    let state = cbus_test_support::proc::temp_path("cgate-dali-roles.json");
    let mut sys = start_with(options_for(&state, None, "127.0.0.1:0")).await;
    wait_started(&sys).await;
    let (mut reader, mut writer) = connect(&sys).await;
    for (name, role) in [("admin", "Admin"), ("program", "Program")] {
        assert_eq!(
            command(
                &mut reader,
                &mut writer,
                "add",
                &format!("ACCESS ADD user matrix-{name} matrix-secret-{name} {role}"),
            )
            .await,
            ["200 OK."]
        );
    }
    let before = sys
        .pci
        .frames()
        .iter()
        .filter(|frame| !is_status_request(&frame.payload))
        .count();
    let native: serde_json::Value = serde_json::from_str(include_str!(
        "../../testdata/fixtures/native_cgate_dali_authorization_probe.json"
    ))
    .unwrap();
    let vectors = include_str!("../../testdata/vectors/cgate_dali_authorization.jsonl")
        .lines()
        .map(|line| serde_json::from_str::<serde_json::Value>(line).unwrap())
        .collect::<Vec<_>>();
    assert_eq!(vectors.len(), 5);

    for (name, role) in [("admin", "Admin"), ("program", "Program")] {
        assert_eq!(
            command(
                &mut reader,
                &mut writer,
                "login",
                &format!("LOGIN matrix-{name} matrix-secret-{name}"),
            )
            .await,
            [format!("211 Access level set to: {role}")]
        );
        for (index, vector) in vectors.iter().enumerate() {
            let body = vector["command"].as_str().unwrap();
            let expected = if role == "Admin" {
                assert_eq!(vector["denied_role"], role);
                let expected = vector["denied_reply"].as_str().unwrap();
                assert_eq!(native["roles"][role]["responses"][body], expected);
                expected
            } else {
                assert_eq!(vector["admitted_role"], role);
                let expected = vector["native_at_floor"].as_str().unwrap();
                assert_eq!(native["roles"][role]["responses"][body], expected);
                vector["endpoint_at_floor"].as_str().unwrap_or(expected)
            };
            let reply = command(&mut reader, &mut writer, &format!("d{index}"), body).await;
            assert_eq!(reply, [expected], "{body} at {role}");
        }
    }
    let after = sys
        .pci
        .frames()
        .iter()
        .filter(|frame| !is_status_request(&frame.payload))
        .count();
    assert_eq!(after, before);
    assert!(sys.daemon.is_running());
    drop(sys);
    std::fs::remove_file(state).unwrap();
}

#[tokio::test]
async fn remaining_native_role_vectors_hold_on_the_real_cgate_listener() {
    let state = cbus_test_support::proc::temp_path("cgate-remaining-roles.json");
    let mut sys = start_with(options_for(&state, None, "127.0.0.1:0")).await;
    wait_started(&sys).await;
    let (mut reader, mut writer) = connect(&sys).await;
    for role in ["Monitor", "Operate", "Admin", "Program", "Debug", "Clipsal"] {
        assert_eq!(
            command(
                &mut reader,
                &mut writer,
                "add",
                &format!("ACCESS ADD user matrix-{role} disposable-{role} {role}"),
            )
            .await,
            ["200 OK."]
        );
    }
    let native: serde_json::Value = serde_json::from_str(include_str!(
        "../../testdata/fixtures/native_cgate_remaining_authorization_probe.json"
    ))
    .unwrap();
    let vectors = include_str!("../../testdata/vectors/cgate_remaining_authorization.jsonl")
        .lines()
        .map(|line| serde_json::from_str::<serde_json::Value>(line).unwrap())
        .collect::<Vec<_>>();
    assert_eq!(vectors.len(), 6);
    let before = sys
        .pci
        .frames()
        .iter()
        .filter(|frame| !is_status_request(&frame.payload))
        .count();

    for (index, vector) in vectors.iter().enumerate() {
        let body = vector["command"].as_str().unwrap();
        for (denied, role) in [
            (true, vector["denied_role"].as_str().unwrap()),
            (false, vector["admitted_role"].as_str().unwrap()),
        ] {
            assert_eq!(
                command(
                    &mut reader,
                    &mut writer,
                    &format!("login-{index}"),
                    &format!("LOGIN matrix-{role} disposable-{role}"),
                )
                .await,
                [format!("211 Access level set to: {role}")]
            );
            let reply = command(&mut reader, &mut writer, &format!("v{index}"), body).await;
            if denied {
                let expected = vector["denied_reply"].as_str().unwrap();
                assert_eq!(native["roles"][role]["responses"][body], expected);
                assert_eq!(reply, [expected], "{body} at {role}");
            } else {
                assert_eq!(
                    native["roles"][role]["responses"][body],
                    vector["native_at_floor"]
                );
                assert!(
                    !reply.last().unwrap().starts_with("420 "),
                    "{body} at {role}: {reply:?}"
                );
            }
        }
    }
    let after = sys
        .pci
        .frames()
        .iter()
        .filter(|frame| !is_status_request(&frame.payload))
        .count();
    assert_eq!(after, before);
    assert!(sys.daemon.is_running());
    drop(sys);
    std::fs::remove_file(state).unwrap();
}

#[tokio::test]
async fn docker_proxy_peer_bootstraps_then_uses_token_only_recovery() {
    let state = cbus_test_support::proc::temp_path("cgate-access-docker.json");
    let token = cbus_test_support::proc::temp_path("cgate-access-docker.token");
    std::fs::write(&token, format!("{TOKEN}\n")).unwrap();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&token, std::fs::Permissions::from_mode(0o600)).unwrap();
    }
    let host = non_loopback_ipv4();

    {
        let mut sys = start_with(options_for(&state, Some(&token), "0.0.0.0:0")).await;
        wait_started(&sys).await;
        let listener = listener_address(&sys);
        let target = std::net::SocketAddr::new(host, listener.port());

        // Fresh and pre-ACCESS repositories must remain reachable through a
        // Docker-published listener whose local and peer addresses are both
        // non-loopback bridge addresses.
        let (mut reader, mut writer) = connect_at(&sys, target).await;
        assert_eq!(
            command(&mut reader, &mut writer, "fresh", "LOGIN").await,
            ["210 Access level: Clipsal"]
        );
        assert_eq!(
            command(&mut reader, &mut writer, "token", &format!("LOGIN {TOKEN}")).await,
            ["200 OK"]
        );
        assert_eq!(
            command(
                &mut reader,
                &mut writer,
                "policy",
                "ACCESS ADD interface 192.0.2.254 Operate",
            )
            .await,
            ["200 OK."]
        );

        // Once explicit address policy exists, an unmatched Docker/NAT peer
        // gets only a closed recovery session until the independent token is
        // presented. Native ACCESS users cannot bypass address admission.
        let (mut recovery_reader, mut recovery_writer) = connect_at(&sys, target).await;
        assert_eq!(
            command(&mut recovery_reader, &mut recovery_writer, "level", "LOGIN").await,
            ["210 Access level: None"]
        );
        assert_eq!(
            command(
                &mut recovery_reader,
                &mut recovery_writer,
                "closed",
                "ACCESS LIST",
            )
            .await,
            ["420 LOGIN required"]
        );
        for (tag, text) in [
            ("event-query", "EVENT"),
            ("event-on", "EVENT ON"),
            ("events-mode", "EVENTS e5s1c1"),
        ] {
            assert_eq!(
                command(&mut recovery_reader, &mut recovery_writer, tag, text).await,
                ["420 LOGIN required"],
                "restricted peer must not query or mutate its event subscription"
            );
        }
        assert_eq!(
            command(
                &mut recovery_reader,
                &mut recovery_writer,
                "recover",
                &format!("LOGIN {TOKEN}"),
            )
            .await,
            ["200 OK"]
        );
        assert_eq!(
            command(
                &mut recovery_reader,
                &mut recovery_writer,
                "event-after",
                "EVENT"
            )
            .await,
            ["306 e0s0c0"],
            "rejected subscription changes must leave the default mode intact"
        );
        assert_eq!(
            command(
                &mut recovery_reader,
                &mut recovery_writer,
                "list",
                "ACCESS LIST",
            )
            .await
            .last()
            .unwrap(),
            "135 line=2 entry=interface 192.0.2.254 Operate"
        );
        assert!(sys.daemon.is_running());
    }

    // Without the separately configured recovery credential, the same
    // explicitly unmatched peer receives native 421 admission refusal.
    {
        let mut sys = start_with(options_for(&state, None, "0.0.0.0:0")).await;
        wait_started(&sys).await;
        let listener = listener_address(&sys);
        let target = std::net::SocketAddr::new(host, listener.port());
        let stream = TcpStream::connect(target).await.unwrap();
        let (reader, _writer) = stream.into_split();
        let mut reader = BufReader::new(reader);
        let mut line = String::new();
        assert_ne!(reader.read_line(&mut line).await.unwrap(), 0);
        assert_eq!(line, "421 Connection refused.\r\n");
        line.clear();
        assert_eq!(reader.read_line(&mut line).await.unwrap(), 0);
        assert!(sys.daemon.is_running());
    }

    let state_text = std::fs::read_to_string(&state).unwrap();
    assert!(state_text.contains("\"access_admission_enforced\":true"));
    std::fs::remove_file(state).unwrap();
    std::fs::remove_file(token).unwrap();
}

#[tokio::test]
async fn native_media_role_floors_deny_before_bus_io() {
    let state = cbus_test_support::proc::temp_path("cgate-media-roles.json");
    let mut sys = start_with(options_for(&state, None, "127.0.0.1:0")).await;
    wait_started(&sys).await;
    let (mut reader, mut writer) = connect(&sys).await;
    for (tag, body) in [
        (
            "add-monitor",
            "ACCESS ADD user monitor temporary-monitor Monitor",
        ),
        (
            "add-operate",
            "ACCESS ADD user operate temporary-operate Operate",
        ),
    ] {
        assert_eq!(
            command(&mut reader, &mut writer, tag, body).await,
            ["200 OK."]
        );
    }
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "low",
            "LOGIN monitor temporary-monitor"
        )
        .await,
        ["211 Access level set to: Monitor"]
    );
    let probes = [
        "AUDIO DYNAMIC_1 //MISSING/254/203 1 1",
        "SECURITY ARM //MISSING/254/203 1",
        "MEDIATRANSPORT PLAY //MISSING/254/203 1",
    ];
    let frames_before = sys
        .pci
        .frames()
        .iter()
        .filter(|frame| !is_status_request(&frame.payload))
        .count();
    for (index, probe) in probes.iter().enumerate() {
        let reply = command(&mut reader, &mut writer, &format!("denied-{index}"), probe).await;
        assert_eq!(reply, ["420 Access denied."], "{probe}");
    }
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "high",
            "LOGIN operate temporary-operate"
        )
        .await,
        ["211 Access level set to: Operate"]
    );
    for (index, probe) in probes.iter().enumerate() {
        let reply = command(&mut reader, &mut writer, &format!("reached-{index}"), probe).await;
        assert!(
            reply
                .last()
                .is_some_and(|line| line.starts_with("401 ") || line.starts_with("404 ")),
            "{probe}: {reply:?}"
        );
    }
    let frames_after = sys
        .pci
        .frames()
        .iter()
        .filter(|frame| !is_status_request(&frame.payload))
        .count();
    assert_eq!(frames_after, frames_before);
    assert!(sys.daemon.is_running());
    drop(sys);
    std::fs::remove_file(state).unwrap();
}
