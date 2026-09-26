//! Real cmqttd process: the complete maintained C-Gate PORT family uses host
//! enumeration, retained UDP discovery, and an isolated temporary PCI probe.
//! The test addresses loopback only and never contacts a site C-Bus endpoint.

mod util;

use tokio::{
    io::{AsyncBufReadExt, AsyncReadExt, AsyncWriteExt, BufReader},
    net::{TcpListener, TcpStream},
};
use util::*;

const TOKEN: &str = "throwaway-port-system-token-0123456789abcdef";

async fn reply(reader: &mut BufReader<tokio::net::tcp::OwnedReadHalf>, tag: &str) -> Vec<String> {
    let prefix = format!("[{tag}] ");
    let mut rows = Vec::new();
    loop {
        let mut line = String::new();
        assert_ne!(reader.read_line(&mut line).await.unwrap(), 0);
        let line = line.trim_end_matches(['\r', '\n']);
        let payload = line
            .strip_prefix(&prefix)
            .unwrap_or_else(|| panic!("expected tag {tag:?}, got {line:?}"))
            .to_string();
        let complete = payload.as_bytes().get(3) == Some(&b' ');
        rows.push(payload);
        if complete {
            return rows;
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
    reply(reader, tag).await
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
async fn port_family_matches_native_loopback_discovery_and_isolated_probe() {
    let state = cbus_test_support::proc::temp_path("cgate-port.json");
    let token = cbus_test_support::proc::temp_path("cgate-port.token");
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
        command(&mut reader, &mut writer, "help", "PORT ?").await,
        [
            "101-Help: PORT commands:",
            "101-Help:  PORT ? Help for these commands",
            "101-Help:  PORT CNISCAN - Scan an IP address range for C-Bus Network Interfaces",
            "101-Help:  PORT CNISCAN2 - Scan an IP address range for C-Bus Network Interfaces",
            "101-Help:  PORT IFLIST - Return a list of IP interfaces on the C-Gate server",
            "101-Help:  PORT LIST - Return a list of local serial ports",
            "101-Help:  PORT PROBE - Probe a port for a C-Bus network connection",
            "101 Help:  PORT REFRESH - Refresh the known local serial ports",
        ]
    );
    assert_eq!(
        command(&mut reader, &mut writer, "bad", "PORT BOGUS").await,
        ["400 Syntax Error."]
    );

    let serial = command(&mut reader, &mut writer, "list", "PORT LIST").await;
    assert!(matches!(
        serial.last().unwrap().split_once(' ').unwrap().0,
        "125" | "126"
    ));
    assert!(serial.iter().all(|row| !row.contains("port=/dev/")));

    let interfaces = command(&mut reader, &mut writer, "if", "PORT IFLIST").await;
    assert!(matches!(
        interfaces.last().unwrap().split_once(' ').unwrap().0,
        "127" | "128"
    ));
    assert!(interfaces.iter().all(|row| !row.contains("address=127.")));

    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "locked",
            "PORT CNISCAN 127.0.0.1 FAST"
        )
        .await,
        ["420 LOGIN required"]
    );
    assert_eq!(
        command(&mut reader, &mut writer, "login", &format!("LOGIN {TOKEN}")).await,
        ["200 OK"]
    );
    assert_eq!(
        command(&mut reader, &mut writer, "refresh", "PORT REFRESH").await,
        ["408 Operation failed: This command is not applicable.  The list of ports is automatically updated."]
    );
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "legacy",
            "PORT CNISCAN 127.0.0.1 FAST ignored",
        )
        .await,
        ["130 no CNIs found"]
    );
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "cni2",
            "PORT CNISCAN2 127.0.0.1 127.0.0.1 FAST ignored",
        )
        .await,
        ["130 no CNIs found"]
    );

    // cmqttd's already-owned transport is never reopened or interrupted.
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "inuse",
            &format!("PORT PROBE socket 127.0.0.1:{}", sys.pci.port()),
        )
        .await,
        [format!(
            "431 Probe failed: port in use: Port in use: 127.0.0.1:{}",
            sys.pci.port()
        )]
    );

    let refused = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let refused_port = refused.local_addr().unwrap().port();
    drop(refused);
    let refused_reply = command(
        &mut reader,
        &mut writer,
        "refused",
        &format!("PORT PROBE socket 127.0.0.1:{refused_port}"),
    )
    .await;
    assert_eq!(
        refused_reply,
        ["408 Operation failed: Connection refused (Connection refused)"]
    );

    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "etherlite-missing",
            "PORT PROBE etherlite 127.0.0.1",
        )
        .await,
        ["500 Internal error."]
    );
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "etherlite-bad",
            "PORT PROBE etherlite 127.0.0.1:x",
        )
        .await,
        ["408 Operation failed: Port not found: 127.0.0.1:x"]
    );
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "serial-missing",
            "PORT PROBE serial definitely-no-such-cbus-port",
        )
        .await,
        ["408 Operation failed: Port not found: definitely-no-such-cbus-port"]
    );

    assert_eq!(
        command(&mut reader, &mut writer, "type", "PORT PROBE bogus nowhere").await,
        ["408 Operation failed: Unable to load class:com.clipsal.cgate.cbus.net.CBusBogusNetwork for network type:bogus (com.clipsal.cgate.cbus.net.CBusBogusNetwork)"]
    );

    // A disposable echo endpoint pins CBusBaseNetwork.bb(), the native PORT
    // PROBE wire operation, and proves it does not borrow the shared PCI.
    let probe = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let probe_port = probe.local_addr().unwrap().port();
    let probe_server = tokio::spawn(async move {
        let (mut stream, _) = probe.accept().await.unwrap();
        let mut reset = [0u8; 2];
        stream.read_exact(&mut reset).await.unwrap();
        assert_eq!(reset, [0x11, b'\r']);
        let mut query = [0u8; 6];
        stream.read_exact(&mut query).await.unwrap();
        assert_eq!(&query, b"@2104\r");
        stream.write_all(&query).await.unwrap();
        stream.write_all(b"12345678.1234\r").await.unwrap();
    });
    writer
        .write_all(
            format!("[probe] PORT PROBE socket 127.0.0.1:{probe_port} ignored\r\n").as_bytes(),
        )
        .await
        .unwrap();
    assert_eq!(
        reply(&mut reader, "probe").await,
        ["230 Probe succeeded: C-Bus network detected (PCIserial=12345678 1234 )"]
    );
    probe_server.await.unwrap();
    assert!(sys.daemon.is_running());

    let payload = "053800790149";
    let before = sys.pci.count_payload(payload);
    sys.broker
        .inject("homeassistant/light/cbus_1/set", br#"{"state":"ON"}"#);
    require(COMMAND_DRAIN, "MQTT command after PORT workflow", || {
        sys.pci.count_payload(payload) > before
    })
    .await;
    assert!(sys.daemon.is_running());

    drop(reader);
    drop(writer);
    drop(sys);
    let _ = std::fs::remove_file(state);
    let _ = std::fs::remove_file(token);
}
