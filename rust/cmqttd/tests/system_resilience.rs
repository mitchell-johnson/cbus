//! Full-system fault-path tests: retransmission of unconfirmed frames,
//! connection loss, signal-driven shutdown, TLS/CLI startup failures and
//! reconnect behaviour in ESP32 mode.

mod util;

use cbus_test_support::proc::{run, temp_path, Daemon};
use std::time::Duration;
use util::*;

// ------------------------------------------------------------ retransmit
// Status requests are codeless, so confirmed traffic comes from MQTT
// commands; the fake PCI withholds the first confirmed frame of any kind.

/// OFF for group 10 -> the exact confirmed PCI frame "053800010AB8".
const CMD_TOPIC: &str = "homeassistant/light/cbus_10/set";
const CMD_PAYLOAD: &[u8] = br#"{"state": "OFF"}"#;
const CMD_FRAME: &str = "053800010AB8";

#[tokio::test]
async fn unconfirmed_command_retransmitted_byte_identical() {
    let sys = start_with(Options {
        withhold_first_conf: true,
        ..Default::default()
    })
    .await;
    wait_started(&sys).await;
    sys.broker.inject(CMD_TOPIC, CMD_PAYLOAD);
    // the fake PCI withholds the confirmation of the first confirmed
    // frame; the client must resend the identical frame (payload AND
    // confirmation char — withheld_seen only counts exact matches)
    require(Duration::from_secs(20), "first retransmit", || {
        sys.pci.withheld_seen() >= 2
    })
    .await;
    require(Duration::from_secs(10), "second retransmit", || {
        sys.pci.withheld_seen() >= 3
    })
    .await;
    // the withheld frame really is the injected command's
    assert!(sys.pci.count_payload(CMD_FRAME) >= 3);
}

#[tokio::test]
async fn unconfirmed_frame_abandoned_after_three_attempts() {
    let sys = start_with(Options {
        withhold_first_conf: true,
        ..Default::default()
    })
    .await;
    wait_started(&sys).await;
    sys.broker.inject(CMD_TOPIC, CMD_PAYLOAD);
    require(Duration::from_secs(20), "three attempts", || {
        sys.pci.withheld_seen() >= 3
    })
    .await;
    // after 3 total attempts the code is abandoned: no fourth send
    tokio::time::sleep(Duration::from_secs(3)).await;
    assert_eq!(sys.pci.withheld_seen(), 3);
}

#[tokio::test]
async fn other_frames_still_confirmed_while_one_is_withheld() {
    let sys = start_with(Options {
        withhold_first_conf: true,
        ..Default::default()
    })
    .await;
    wait_started(&sys).await;
    // first command's confirmation is withheld...
    sys.broker.inject(CMD_TOPIC, CMD_PAYLOAD);
    // ...a different command afterwards is confirmed and never retried
    sys.broker
        .inject("homeassistant/light/cbus_1/set", br#"{"state": "ON"}"#);
    require(Duration::from_secs(20), "withheld frame retried", || {
        sys.pci.withheld_seen() >= 3
    })
    .await;
    assert_eq!(
        sys.pci.count_payload("053800790149"),
        1,
        "the confirmed command must be sent exactly once"
    );
}

// --------------------------------------------------------- connection loss

#[tokio::test]
async fn pci_disconnect_plain_tcp_exits() {
    let mut sys = start_default().await;
    wait_started(&sys).await;
    sys.pci.kick();
    let status = sys
        .daemon
        .wait_exit(Duration::from_secs(10))
        .await
        .expect("daemon must exit after losing the PCI in -t mode");
    assert!(status.success(), "clean shutdown expected, got {status:?}");
}

#[tokio::test]
async fn esp32_wifi_mode_reconnects_and_reinitialises() {
    let broker = cbus_test_support::broker::MiniBroker::start().await;
    let pci = cbus_test_support::pci::FakePci::start(false).await;
    let broker_port = broker.port().to_string();
    let wifi = format!("127.0.0.1:{}", pci.port());
    let daemon = Daemon::spawn(
        BIN,
        &[
            "-b",
            "127.0.0.1",
            "-p",
            &broker_port,
            "--broker-disable-tls",
            "--esp32-wifi",
            &wifi,
            "--esp32-reconnect-interval",
            "1",
            "-T",
            "0",
            "-v",
            "DEBUG",
        ],
    );
    let sys = System {
        broker,
        pci,
        daemon,
    };
    wait_started(&sys).await;
    assert_eq!(sys.pci.connections(), 1);
    sys.pci.kick();
    require(Duration::from_secs(15), "reconnection", || {
        sys.pci.connections() >= 2
    })
    .await;
    // the fresh connection redoes the full init sequence
    require(Duration::from_secs(15), "re-init resets", || {
        sys.pci.reset_count() >= 6
    })
    .await;
    require(Duration::from_secs(15), "re-init smart connect", || {
        sys.pci.smart_connect_count() >= 2
    })
    .await;
}

#[tokio::test]
async fn broker_down_daemon_keeps_pci_running() {
    // point the daemon at a dead broker port: MQTT retries forever, the
    // PCI side still initialises
    let pci = cbus_test_support::pci::FakePci::start(false).await;
    let dead = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    let dead_port = dead.local_addr().unwrap().port().to_string();
    drop(dead);
    let addr = format!("127.0.0.1:{}", pci.port());
    let mut daemon = Daemon::spawn(
        BIN,
        &[
            "-b",
            "127.0.0.1",
            "-p",
            &dead_port,
            "--broker-disable-tls",
            "-t",
            &addr,
            "-T",
            "0",
            "-v",
            "DEBUG",
        ],
    );
    require(STARTUP, "PCI init without broker", || {
        pci.payloads().len() >= 4
    })
    .await;
    tokio::time::sleep(Duration::from_secs(2)).await;
    assert!(daemon.is_running(), "MQTT retry loop must not exit");
}

// ------------------------------------------------------ signal shutdown

#[tokio::test]
async fn sigint_sends_clean_mqtt_disconnect_and_exits_zero() {
    let mut sys = start_default().await;
    wait_started(&sys).await;
    sys.daemon.signal("INT");
    let status = sys
        .daemon
        .wait_exit(Duration::from_secs(10))
        .await
        .expect("daemon must exit on SIGINT");
    assert!(status.success(), "exit code 0 expected, got {status:?}");
    require(Duration::from_secs(2), "clean MQTT DISCONNECT", || {
        sys.broker.clean_disconnects() >= 1
    })
    .await;
}

#[tokio::test]
async fn sigterm_sends_clean_mqtt_disconnect_and_exits_zero() {
    let mut sys = start_default().await;
    wait_started(&sys).await;
    sys.daemon.signal("TERM");
    let status = sys
        .daemon
        .wait_exit(Duration::from_secs(10))
        .await
        .expect("daemon must exit on SIGTERM");
    assert!(status.success(), "exit code 0 expected, got {status:?}");
    require(Duration::from_secs(2), "clean MQTT DISCONNECT", || {
        sys.broker.clean_disconnects() >= 1
    })
    .await;
}

// -------------------------------------------------- startup failure paths

#[tokio::test]
async fn unreachable_pci_exits_nonzero() {
    let dead = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    let port = dead.local_addr().unwrap().port();
    drop(dead);
    let addr = format!("127.0.0.1:{port}");
    let (status, _out, err) = run(
        BIN,
        &[
            "-b",
            "127.0.0.1",
            "--broker-disable-tls",
            "-t",
            &addr,
            "-T",
            "0",
        ],
    );
    assert!(!status.success());
    assert!(err.contains("cannot connect"), "stderr: {err}");
}

#[tokio::test]
async fn tls_missing_ca_file_exits_nonzero() {
    let pci = cbus_test_support::pci::FakePci::start(false).await;
    let addr = format!("127.0.0.1:{}", pci.port());
    let (status, _out, err) = run(
        BIN,
        &[
            "-b",
            "127.0.0.1",
            "-t",
            &addr,
            "-c",
            "/nonexistent/ca.pem",
            "-T",
            "0",
        ],
    );
    assert!(!status.success());
    assert!(err.contains("cannot read"), "stderr: {err}");
}

#[tokio::test]
async fn tls_empty_ca_dir_exits_nonzero() {
    let pci = cbus_test_support::pci::FakePci::start(false).await;
    let addr = format!("127.0.0.1:{}", pci.port());
    let dir = temp_path("ca-dir");
    std::fs::create_dir_all(&dir).unwrap();
    let (status, _out, err) = run(
        BIN,
        &[
            "-b",
            "127.0.0.1",
            "-t",
            &addr,
            "-c",
            dir.to_str().unwrap(),
            "-T",
            "0",
        ],
    );
    std::fs::remove_dir_all(&dir).ok();
    assert!(!status.success());
    assert!(err.contains("no CA certificates found"), "stderr: {err}");
}

#[tokio::test]
async fn client_cert_without_key_exits_nonzero() {
    let pci = cbus_test_support::pci::FakePci::start(false).await;
    let addr = format!("127.0.0.1:{}", pci.port());
    let cert = temp_path("client.pem");
    std::fs::write(&cert, "").unwrap();
    let (status, _out, err) = run(
        BIN,
        &[
            "-b",
            "127.0.0.1",
            "-t",
            &addr,
            "-k",
            cert.to_str().unwrap(),
            "-T",
            "0",
        ],
    );
    std::fs::remove_file(&cert).ok();
    assert!(!status.success());
    assert!(err.contains("must be specified"), "stderr: {err}");
}

#[tokio::test]
async fn missing_project_file_exits_nonzero() {
    let pci = cbus_test_support::pci::FakePci::start(false).await;
    let addr = format!("127.0.0.1:{}", pci.port());
    let (status, _out, err) = run(
        BIN,
        &[
            "-b",
            "127.0.0.1",
            "--broker-disable-tls",
            "-t",
            &addr,
            "-P",
            "/nonexistent/project.cbz",
            "-T",
            "0",
        ],
    );
    assert!(!status.success());
    assert!(err.contains("error reading project file"), "stderr: {err}");
}

#[tokio::test]
async fn unknown_network_name_exits_nonzero() {
    let pci = cbus_test_support::pci::FakePci::start(false).await;
    let addr = format!("127.0.0.1:{}", pci.port());
    let project = project_file();
    let (status, _out, err) = run(
        BIN,
        &[
            "-b",
            "127.0.0.1",
            "--broker-disable-tls",
            "-t",
            &addr,
            "-P",
            &project,
            "-N",
            "No",
            "Such",
            "Network",
            "-T",
            "0",
        ],
    );
    assert!(!status.success());
    // -N words are joined with spaces before the lookup
    assert!(err.contains("'No Such Network' not found"), "stderr: {err}");
}

#[tokio::test]
async fn multi_word_network_name_accepted() {
    // fixtures/project.xml names its network "Harness Network"
    let sys = start_with(Options {
        extra: vec!["-N".into(), "Harness".into(), "Network".into()],
        ..Default::default()
    })
    .await;
    wait_started(&sys).await;
    require(STARTUP, "labelled config publish", || {
        !sys.broker
            .find_publishes("homeassistant/light/cbus_1/config")
            .is_empty()
    })
    .await;
}

#[tokio::test]
async fn invalid_tcp_spec_exits_with_usage_error() {
    let (status, _out, err) = run(
        BIN,
        &["-b", "127.0.0.1", "--broker-disable-tls", "-t", "nocolon"],
    );
    assert_eq!(status.code(), Some(2));
    assert!(err.contains("invalid TCP address"), "stderr: {err}");
}

#[tokio::test]
async fn missing_connection_argument_exits_with_usage_error() {
    let (status, _out, err) = run(BIN, &["-b", "127.0.0.1", "--broker-disable-tls"]);
    assert_eq!(status.code(), Some(2));
    assert!(!err.is_empty());
}

#[tokio::test]
async fn conflicting_connection_arguments_rejected() {
    let (status, _out, err) = run(
        BIN,
        &[
            "-b",
            "127.0.0.1",
            "--broker-disable-tls",
            "-t",
            "127.0.0.1:1",
            "--esp32-discover",
        ],
    );
    assert_eq!(status.code(), Some(2));
    assert!(!err.is_empty());
}

#[tokio::test]
async fn invalid_verbosity_rejected() {
    let (status, _out, err) = run(
        BIN,
        &[
            "-b",
            "127.0.0.1",
            "--broker-disable-tls",
            "-t",
            "127.0.0.1:1",
            "-v",
            "CHATTY",
        ],
    );
    assert_eq!(status.code(), Some(2));
    assert!(!err.is_empty());
}

// ----------------------------------------------------------- timesync

#[tokio::test]
async fn timesync_interval_sends_periodic_clock_frames() {
    let sys = start_with(Options {
        timesync: "1".into(),
        ..Default::default()
    })
    .await;
    require(Duration::from_secs(15), "two timesync frames", || {
        sys.pci
            .payloads()
            .iter()
            .filter(|p| p.starts_with("05DF00"))
            .count()
            >= 2
    })
    .await;
}

#[tokio::test]
async fn auth_file_accepted_and_daemon_connects() {
    let auth = temp_path("auth.txt");
    std::fs::write(&auth, "user\npassword\n").unwrap();
    let sys = start_with(Options {
        extra: vec!["-A".into(), auth.to_string_lossy().into_owned()],
        ..Default::default()
    })
    .await;
    wait_started(&sys).await;
    std::fs::remove_file(&auth).ok();
    assert!(sys.broker.errors().is_empty());
}
