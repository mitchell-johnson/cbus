//! Full-system tests for the cbus-simulator binary: spawn the real fake
//! PCI and drive it over TCP like a C-Bus client would — power-on
//! notification, basic-mode echo, smart connect, SRCHK checksum
//! enforcement and master-application status replies.

use cbus_test_support::proc::Daemon;
use std::time::Duration;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::TcpStream;

const BIN: &str = env!("CARGO_BIN_EXE_cbus-simulator");

/// Spawn the simulator on a free port (retrying the pick-then-bind race)
/// and open one client connection to it. A successful connect may reach
/// a concurrent test's daemon that picked the same port and is about to
/// die, so verify our daemon survived the bind and that the simulator's
/// "++" greeting is actually arriving before handing the stream out.
async fn spawn_sim() -> (Daemon, TcpStream) {
    'retry: for _ in 0..10 {
        let port = {
            let l = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
            l.local_addr().unwrap().port()
        };
        let mut daemon = Daemon::spawn(BIN, &["127.0.0.1", &port.to_string()]);
        for _ in 0..150 {
            if let Ok(stream) = TcpStream::connect(("127.0.0.1", port)).await {
                // a daemon that lost the bind race exits promptly
                tokio::time::sleep(Duration::from_millis(100)).await;
                if !daemon.is_running() {
                    continue 'retry;
                }
                let mut peek = [0u8; 1];
                match tokio::time::timeout(Duration::from_secs(3), stream.peek(&mut peek)).await {
                    Ok(Ok(n)) if n > 0 => return (daemon, stream),
                    _ => continue 'retry, // dead/foreign daemon
                }
            }
            if !daemon.is_running() {
                continue 'retry; // lost the port race: retry with a fresh port
            }
            tokio::time::sleep(Duration::from_millis(20)).await;
        }
    }
    panic!("could not start cbus-simulator on any port");
}

/// Read whatever arrives until `idle` passes with no data.
async fn read_for(stream: &mut TcpStream, idle: Duration) -> Vec<u8> {
    let mut out = Vec::new();
    let mut buf = [0u8; 4096];
    loop {
        match tokio::time::timeout(idle, stream.read(&mut buf)).await {
            Ok(Ok(n)) if n > 0 => out.extend_from_slice(&buf[..n]),
            _ => break,
        }
    }
    out
}

/// Read until `needle` appears (panics on timeout), returning everything.
async fn read_until(stream: &mut TcpStream, needle: &[u8], timeout: Duration) -> Vec<u8> {
    let deadline = tokio::time::Instant::now() + timeout;
    let mut out = Vec::new();
    let mut buf = [0u8; 4096];
    while !out.windows(needle.len().max(1)).any(|w| w == needle) {
        let now = tokio::time::Instant::now();
        if now >= deadline {
            panic!(
                "timed out waiting for {:?}; got {:?}",
                String::from_utf8_lossy(needle),
                String::from_utf8_lossy(&out)
            );
        }
        match tokio::time::timeout(deadline - now, stream.read(&mut buf)).await {
            Ok(Ok(n)) if n > 0 => out.extend_from_slice(&buf[..n]),
            _ => panic!(
                "connection closed waiting for {:?}; got {:?}",
                String::from_utf8_lossy(needle),
                String::from_utf8_lossy(&out)
            ),
        }
    }
    out
}

const WAIT: Duration = Duration::from_secs(5);

/// Consume the power-up notification every fresh connection receives.
async fn drain_pun(stream: &mut TcpStream) {
    read_until(stream, b"++\r\n", WAIT).await;
}

/// Enter smart mode and consume the basic-mode echo of the `|` frame
/// itself (the echo happens before the mode switch is applied).
async fn smart_connect(stream: &mut TcpStream) {
    stream.write_all(b"|\r").await.unwrap();
    read_until(stream, b"|\r", WAIT).await;
}

#[tokio::test]
async fn sends_power_on_notification_on_connect() {
    let (_d, mut s) = spawn_sim().await;
    let got = read_until(&mut s, b"++\r\n", WAIT).await;
    assert!(got.starts_with(b"++\r\n"));
}

#[tokio::test]
async fn second_client_also_gets_power_on() {
    let (_d, mut s1) = spawn_sim().await;
    drain_pun(&mut s1).await;
    let addr = s1.peer_addr().unwrap();
    let mut s2 = TcpStream::connect(addr).await.unwrap();
    read_until(&mut s2, b"++\r\n", WAIT).await;
}

#[tokio::test]
async fn basic_mode_echoes_and_confirms_dm() {
    let (_d, mut s) = spawn_sim().await;
    drain_pun(&mut s).await;
    s.write_all(b"A32100FFh\r").await.unwrap();
    let got = read_until(&mut s, b"h.", WAIT).await;
    let text = String::from_utf8_lossy(&got).into_owned();
    assert!(text.contains("A32100FFh\r"), "local echo missing: {text:?}");
    // the confirmation comes after the echo
    assert!(text.find("A32100FFh\r").unwrap() < text.find("h.").unwrap());
}

#[tokio::test]
async fn unknown_dm_parameter_echoed_but_not_confirmed() {
    let (_d, mut s) = spawn_sim().await;
    drain_pun(&mut s).await;
    s.write_all(b"A39900FFi\r").await.unwrap();
    let got = read_for(&mut s, Duration::from_millis(700)).await;
    let text = String::from_utf8_lossy(&got).into_owned();
    assert!(text.contains("A39900FFi\r"), "echo expected: {text:?}");
    assert!(!text.contains("i."), "must not confirm: {text:?}");
}

#[tokio::test]
async fn smart_connect_disables_echo() {
    let (_d, mut s) = spawn_sim().await;
    drain_pun(&mut s).await;
    s.write_all(b"|\r").await.unwrap();
    s.write_all(b"\\053800790149j\r").await.unwrap();
    let got = read_until(&mut s, b"j.", WAIT).await;
    let text = String::from_utf8_lossy(&got).into_owned();
    assert!(
        !text.contains("053800790149"),
        "no echo in smart mode: {text:?}"
    );
}

#[tokio::test]
async fn reset_restores_basic_mode_echo() {
    let (_d, mut s) = spawn_sim().await;
    drain_pun(&mut s).await;
    s.write_all(b"|\r").await.unwrap();
    s.write_all(b"~\r").await.unwrap();
    s.write_all(b"A32100FFk\r").await.unwrap();
    let got = read_until(&mut s, b"k.", WAIT).await;
    assert!(
        String::from_utf8_lossy(&got).contains("A32100FFk\r"),
        "echo must be back after reset"
    );
}

#[tokio::test]
async fn srchk_rejects_bad_checksum_frames() {
    let (_d, mut s) = spawn_sim().await;
    drain_pun(&mut s).await;
    // interface options: CONNECT | SRCHK | SMART
    s.write_all(b"A3300019l\r").await.unwrap();
    read_until(&mut s, b"l.", WAIT).await;
    // wrong checksum: silently invalid, no confirmation for 'm'
    s.write_all(b"\\05380079FF00m\r").await.unwrap();
    // correct checksum still confirmed
    s.write_all(b"\\053800790149n\r").await.unwrap();
    let got = read_until(&mut s, b"n.", WAIT).await;
    assert!(
        !got.windows(2).any(|w| w == b"m."),
        "bad-checksum frame must not be confirmed"
    );
}

#[tokio::test]
async fn lighting_command_confirmed_in_smart_mode() {
    let (_d, mut s) = spawn_sim().await;
    drain_pun(&mut s).await;
    s.write_all(b"|\r").await.unwrap();
    // two SALs in one frame: exactly one confirmation
    s.write_all(b"\\05380079017902r\r").await.unwrap();
    let got = read_until(&mut s, b"r.", WAIT).await;
    let text = String::from_utf8_lossy(&got).into_owned();
    assert_eq!(text.matches("r.").count(), 1);
}

#[tokio::test]
async fn master_application_status_replies_binary_blocks() {
    let (_d, mut s) = spawn_sim().await;
    drain_pun(&mut s).await;
    // binary status request for the master application (0xFF), basic mode
    s.write_all(b"\\05FF007AFF00o\r").await.unwrap();
    let got = read_until(&mut s, b"o.", WAIT).await;
    let text = String::from_utf8_lossy(&got).into_owned();
    // three StandardCAL blocks: 88+88+79 states -> headers D9/D9/D7
    assert!(text.contains("D9FF00"), "block 0 missing: {text:?}");
    assert!(text.contains("D9FF58"), "block 88 missing: {text:?}");
    assert!(text.contains("D7FFB0"), "block 176 missing: {text:?}");
    // reply lines are checksummed CRLF-terminated hex
    for line in text
        .lines()
        .filter(|l| l.starts_with("D9") || l.starts_with("D7"))
    {
        let bytes = hex::decode(line.trim()).expect("hex reply line");
        assert!(
            cbus_protocol::common::validate_cbus_checksum(&bytes),
            "bad checksum on {line}"
        );
    }
    // the confirmation comes after the reply blocks
    assert!(text.find("D7FFB0").unwrap() < text.find("o.").unwrap());
}

#[tokio::test]
async fn master_application_status_not_available_in_smart_mode() {
    let (_d, mut s) = spawn_sim().await;
    drain_pun(&mut s).await;
    smart_connect(&mut s).await;
    s.write_all(b"\\05FF007AFF00o\r").await.unwrap();
    let got = read_for(&mut s, Duration::from_millis(700)).await;
    assert!(
        got.is_empty(),
        "smart-mode master status must get no reply/confirmation: {:?}",
        String::from_utf8_lossy(&got)
    );
}

#[tokio::test]
async fn level_status_request_not_confirmed() {
    let (_d, mut s) = spawn_sim().await;
    drain_pun(&mut s).await;
    smart_connect(&mut s).await;
    // level status request (0x73 0x07) is unhandled by the simulator
    s.write_all(b"\\05FF0073073800p\r").await.unwrap();
    let got = read_for(&mut s, Duration::from_millis(700)).await;
    assert!(
        got.is_empty(),
        "level status request must be ignored: {:?}",
        String::from_utf8_lossy(&got)
    );
}

#[tokio::test]
async fn garbage_does_not_break_the_session() {
    let (_d, mut s) = spawn_sim().await;
    drain_pun(&mut s).await;
    s.write_all(b"|\r").await.unwrap();
    s.write_all(b"XYZ!!@@\r").await.unwrap();
    s.write_all(b"\\053800790149q\r").await.unwrap();
    read_until(&mut s, b"q.", WAIT).await;
}

#[tokio::test]
async fn clock_updates_accepted_and_confirmed() {
    let (_d, mut s) = spawn_sim().await;
    drain_pun(&mut s).await;
    smart_connect(&mut s).await;
    // clock date+time update (app 0xDF), no checksum in this session
    s.write_all(b"\\05DF000E0207E70714030D01020304FFs\r")
        .await
        .unwrap();
    let got = read_until(&mut s, b"s.", WAIT).await;
    // deliberate divergence from Python: no random debug lighting events
    let text = String::from_utf8_lossy(&got).into_owned();
    assert_eq!(text, "s.", "clock update must only confirm: {text:?}");
}
