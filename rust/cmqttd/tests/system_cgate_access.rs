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
