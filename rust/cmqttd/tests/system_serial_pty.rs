//! Real cmqttd process on `--serial` over a pseudo-terminal. A byte relay
//! joins the pty master to the scripted fake PCI, so the ordinary PCI init,
//! the C-Gate PORT family and MQTT control all cross a real tty line
//! discipline. No physical serial port is opened.
#![cfg(unix)]

mod util;

use cbus_test_support::{broker::MiniBroker, pci::FakePci, proc::Daemon};
use std::io::{Read, Write};
use std::os::fd::FromRawFd;
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::net::TcpStream;
use util::*;

/// Allocate a raw pty; returns (master, slave kept open, slave path).
fn open_pty() -> (std::fs::File, std::fs::File, String) {
    unsafe {
        let master = libc::posix_openpt(libc::O_RDWR | libc::O_NOCTTY);
        assert!(master >= 0, "posix_openpt failed");
        assert_eq!(libc::grantpt(master), 0);
        assert_eq!(libc::unlockpt(master), 0);
        let path = std::ffi::CStr::from_ptr(libc::ptsname(master))
            .to_string_lossy()
            .into_owned();
        let c_path = std::ffi::CString::new(path.clone()).unwrap();
        let slave = libc::open(c_path.as_ptr(), libc::O_RDWR | libc::O_NOCTTY);
        assert!(slave >= 0, "open {path} failed");
        // Raw before cmqttd opens it: no echo of relayed PCI bytes.
        let mut termios = std::mem::zeroed::<libc::termios>();
        assert_eq!(libc::tcgetattr(slave, &mut termios), 0);
        libc::cfmakeraw(&mut termios);
        assert_eq!(libc::tcsetattr(slave, libc::TCSANOW, &termios), 0);
        (
            std::fs::File::from_raw_fd(master),
            std::fs::File::from_raw_fd(slave),
            path,
        )
    }
}

/// Copy bytes both ways between the pty master and the fake PCI's TCP port.
fn relay(master: std::fs::File, pci_port: u16) {
    let tcp = std::net::TcpStream::connect(("127.0.0.1", pci_port)).unwrap();
    tcp.set_nodelay(true).ok();
    let (mut from_tty, mut to_tty) = (master.try_clone().unwrap(), master);
    let (mut to_pci, mut from_pci) = (tcp.try_clone().unwrap(), tcp);
    std::thread::spawn(move || {
        let mut buffer = [0u8; 1024];
        while let Ok(length @ 1..) = from_tty.read(&mut buffer) {
            if to_pci.write_all(&buffer[..length]).is_err() {
                break;
            }
        }
    });
    std::thread::spawn(move || {
        let mut buffer = [0u8; 1024];
        while let Ok(length @ 1..) = from_pci.read(&mut buffer) {
            if to_tty.write_all(&buffer[..length]).is_err() {
                break;
            }
        }
    });
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
    let mut rows = Vec::new();
    loop {
        let mut line = String::new();
        assert_ne!(reader.read_line(&mut line).await.unwrap(), 0);
        let payload = line
            .trim_end_matches(['\r', '\n'])
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

#[tokio::test]
async fn serial_pty_endpoint_is_listed_in_use_refused_by_probe_and_mqtt_stays_live() {
    let broker = MiniBroker::start().await;
    let pci = FakePci::start(false).await;
    let (master, _slave, path) = open_pty();
    relay(master, pci.port());

    let state = cbus_test_support::proc::temp_path("cgate-serial-pty.json");
    let broker_port = broker.port().to_string();
    let project = project_file();
    let mut daemon = Daemon::spawn(
        BIN,
        &[
            "-b",
            "127.0.0.1",
            "-p",
            &broker_port,
            "--broker-disable-tls",
            "--serial",
            &path,
            "-T",
            "0",
            "-v",
            "DEBUG",
            "-P",
            &project,
            "--cgate-bind",
            "127.0.0.1:0",
            "--cgate-state",
            &state.to_string_lossy(),
        ],
    );

    // The unchanged transport init crossed the pty, in order.
    require(STARTUP, "PCI init over the pty", || {
        pci.frames()
            .iter()
            .filter(|frame| frame.payload.starts_with("A3"))
            .count()
            >= 4
    })
    .await;
    let frames = pci.frames();
    assert_eq!(pci.reset_count(), 3, "{frames:?}");
    assert_eq!(pci.smart_connect_count(), 1);
    let init = frames
        .iter()
        .filter(|frame| frame.payload.starts_with("A3"))
        .map(|frame| frame.payload.clone())
        .collect::<Vec<_>>();
    assert_eq!(init, ["A32100FF", "A32200FF", "A342000E", "A3300079"]);
    require(STARTUP, "MQTT wildcard subscription", || {
        broker.has_subscription("homeassistant/light/+/set")
    })
    .await;

    require(STARTUP, "C-Gate listener", || {
        daemon.stderr().contains("C-Gate service listening on ")
    })
    .await;
    let address = daemon
        .stderr()
        .lines()
        .find_map(|line| line.split_once("C-Gate service listening on "))
        .map(|(_, address)| address.trim().to_string())
        .unwrap();
    let (reader, mut writer) = TcpStream::connect(address).await.unwrap().into_split();
    let mut reader = BufReader::new(reader);
    let mut greeting = String::new();
    reader.read_line(&mut greeting).await.unwrap();
    assert_eq!(greeting, "201 cmqttd C-Gate service ready\r\n");

    // The pty is not enumerated by the host port library, yet cmqttd's own
    // selected serial endpoint is always reported in use.
    let name = path.strip_prefix("/dev/").unwrap_or(&path);
    let list = command(&mut reader, &mut writer, "list", "PORT LIST").await;
    assert!(list.last().unwrap().starts_with("125 "), "{list:?}");
    let selected = format!("port={name} status=inuse");
    assert_eq!(
        list.iter().filter(|row| row.ends_with(&selected)).count(),
        1,
        "{list:?}"
    );
    assert!(
        list.iter()
            .filter(|row| row.contains("status=inuse"))
            .count()
            == 1
    );

    // The active endpoint is refused before any open, by bare name and path.
    let before = pci.frames().len();
    for (tag, target) in [("bare", name.to_string()), ("path", path.clone())] {
        assert_eq!(
            command(
                &mut reader,
                &mut writer,
                tag,
                &format!("PORT PROBE serial {target}")
            )
            .await,
            [format!(
                "431 Probe failed: port in use: Port in use: {target}"
            )]
        );
    }
    assert_eq!(pci.frames().len(), before, "PROBE must not write the PCI");

    let payload = "053800790149";
    let sent = pci.count_payload(payload);
    broker.inject("homeassistant/light/cbus_1/set", br#"{"state":"ON"}"#);
    require(COMMAND_DRAIN, "MQTT command over the pty", || {
        pci.count_payload(payload) > sent
    })
    .await;
    assert!(daemon.is_running());

    drop(reader);
    drop(writer);
    drop(daemon);
    let _ = std::fs::remove_file(state);
}
