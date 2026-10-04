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
const ON_FRAME: &str = "053800790A40";
const LEVEL_READBACK: &str = "05FF00730738004A";

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
async fn late_confirmation_holds_immediate_opposite_qos1_command_fifo() {
    let sys = start_default().await;
    wait_started(&sys).await;
    require(STARTUP, "startup status sweep", || {
        configured_sweep()
            .iter()
            .all(|payload| sys.pci.count_payload(payload) >= 1)
    })
    .await;
    let readbacks_before = sys.pci.count_payload(LEVEL_READBACK);
    sys.pci.set_conf_delay(Duration::from_millis(400));

    sys.broker.inject_qos1(CMD_TOPIC, CMD_PAYLOAD);
    sys.broker.inject_qos1(CMD_TOPIC, br#"{"state": "ON"}"#);
    require(Duration::from_secs(5), "first command frame", || {
        sys.pci.count_payload(CMD_FRAME) == 1
    })
    .await;
    require(Duration::from_secs(2), "both MQTT PUBACKs", || {
        sys.broker.injected_pubacks() >= 2
    })
    .await;
    tokio::time::sleep(Duration::from_millis(100)).await;
    assert_eq!(
        sys.pci.count_payload(ON_FRAME),
        0,
        "ON must wait for OFF's correlated late confirmation"
    );
    assert!(
        sys.broker
            .find_publishes("homeassistant/light/cbus_10/state")
            .is_empty(),
        "socket transmission is not a successful state transition"
    );

    require(
        Duration::from_secs(5),
        "opposite command after confirmation",
        || sys.pci.count_payload(ON_FRAME) == 1,
    )
    .await;
    require(Duration::from_secs(5), "one readback per command", || {
        sys.pci.count_payload(LEVEL_READBACK) >= readbacks_before + 2
    })
    .await;
    require(Duration::from_secs(5), "confirmed command receipts", || {
        sys.broker
            .find_publishes("cmqttd/cbus/command_result")
            .iter()
            .filter_map(|publish| {
                serde_json::from_slice::<serde_json::Value>(&publish.payload).ok()
            })
            .filter(|payload| {
                payload["group"] == 10
                    && payload["delivery"] == "confirmed"
                    && payload["readback"] == "queued"
            })
            .count()
            >= 2
    })
    .await;

    let commands = sys
        .pci
        .frames()
        .into_iter()
        .filter(|frame| frame.payload == CMD_FRAME || frame.payload == ON_FRAME)
        .map(|frame| frame.payload)
        .collect::<Vec<_>>();
    assert_eq!(commands, vec![CMD_FRAME.to_string(), ON_FRAME.to_string()]);
}

#[tokio::test]
async fn lost_confirmation_blocks_opposite_command_and_reports_uncertain() {
    let sys = start_with(Options {
        withhold_first_conf: true,
        ..Default::default()
    })
    .await;
    wait_started(&sys).await;
    // The first command's confirmation is withheld. An immediate opposite
    // command is accepted by MQTT but must not overtake its unresolved PCI
    // delivery lifecycle.
    sys.broker.inject(CMD_TOPIC, CMD_PAYLOAD);
    sys.broker
        .inject("homeassistant/light/cbus_1/set", br#"{"state": "ON"}"#);
    require(Duration::from_secs(20), "withheld frame retried", || {
        sys.pci.withheld_seen() >= 3
    })
    .await;
    assert_eq!(
        sys.pci.count_payload("053800790149"),
        0,
        "later command must remain behind unresolved delivery"
    );
    assert!(
        sys.broker
            .find_publishes("homeassistant/light/cbus_10/state")
            .is_empty(),
        "an unconfirmed command must not get a success-looking state echo"
    );

    require(
        Duration::from_secs(20),
        "uncertain delivery receipt",
        || {
            sys.broker
                .find_publishes("cmqttd/cbus/command_result")
                .iter()
                .filter_map(|publish| {
                    serde_json::from_slice::<serde_json::Value>(&publish.payload).ok()
                })
                .any(|payload| {
                    payload["group"] == 10
                        && payload["delivery"] == "uncertain"
                        && payload["readback"] == "not-requested"
                })
        },
    )
    .await;
    require(
        Duration::from_secs(10),
        "later command after bounded failure",
        || sys.pci.count_payload("053800790149") == 1,
    )
    .await;
    assert_eq!(
        sys.pci.count_payload("053800790149"),
        1,
        "the later command is submitted exactly once after bounded failure"
    );
}

// --------------------------------------------------------- connection loss

#[tokio::test]
async fn pci_disconnect_plain_tcp_exits() {
    let mut sys = start_default().await;
    wait_started(&sys).await;
    require(STARTUP, "initial connected state", || {
        sys.broker
            .retained("homeassistant/binary_sensor/cbus_cmqttd/state")
            .as_deref()
            == Some(b"ON")
    })
    .await;
    sys.pci.kick();
    let status = sys
        .daemon
        .wait_exit(Duration::from_secs(10))
        .await
        .expect("daemon must exit after losing the PCI in -t mode");
    assert!(status.success(), "clean shutdown expected, got {status:?}");
    require(
        Duration::from_secs(2),
        "retained disconnected state",
        || {
            sys.broker
                .retained("homeassistant/binary_sensor/cbus_cmqttd/state")
                .as_deref()
                == Some(b"OFF")
        },
    )
    .await;
}

#[tokio::test]
async fn esp32_wifi_mode_reconnects_and_reinitialises() {
    let broker = cbus_test_support::broker::MiniBroker::start().await;
    let pci = cbus_test_support::pci::FakePci::start(false).await;
    let broker_port = broker.port().to_string();
    let wifi = format!("127.0.0.1:{}", pci.port());
    let project = project_file();
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
            "-P",
            &project,
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
    require(STARTUP, "initial configured status sweep", || {
        configured_sweep()
            .iter()
            .all(|payload| sys.pci.count_payload(payload) >= 1)
    })
    .await;
    require(STARTUP, "initial connected state", || {
        sys.broker
            .retained("homeassistant/binary_sensor/cbus_cmqttd/state")
            .as_deref()
            == Some(b"ON")
    })
    .await;
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
    require(
        Duration::from_secs(15),
        "forced post-reconnect status sweep",
        || {
            configured_sweep()
                .iter()
                .all(|payload| sys.pci.count_payload(payload) >= 2)
        },
    )
    .await;
    require(
        Duration::from_secs(15),
        "disconnect and reconnect state",
        || {
            let states = sys
                .broker
                .find_publishes("homeassistant/binary_sensor/cbus_cmqttd/state")
                .into_iter()
                .map(|publish| publish.payload)
                .collect::<Vec<_>>();
            states
                .windows(3)
                .any(|window| window == [b"ON".to_vec(), b"OFF".to_vec(), b"ON".to_vec()])
        },
    )
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
    assert_eq!(
        sys.broker
            .retained("homeassistant/binary_sensor/cbus_cmqttd/state")
            .as_deref(),
        Some(b"OFF".as_slice()),
        "a clean disconnect suppresses the will, so shutdown must publish OFF"
    );
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
    assert_eq!(
        sys.broker
            .retained("homeassistant/binary_sensor/cbus_cmqttd/state")
            .as_deref(),
        Some(b"OFF".as_slice()),
        "a clean disconnect suppresses the will, so shutdown must publish OFF"
    );
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

// ------------------------------------------------ broker/CNI recovery (P11.03)

const SET_WILDCARD: &str = "homeassistant/light/+/set";
const BRIDGE_STATE: &str = "homeassistant/binary_sensor/cbus_cmqttd/state";
const META_CONFIG: &str = "homeassistant/binary_sensor/cbus_cmqttd/config";
const GROUP1_CONFIG: &str = "homeassistant/light/cbus_1/config";
const GROUP10_CONFIG: &str = "homeassistant/light/cbus_10/config";

fn retained_is(sys: &System, topic: &str, payload: &[u8]) -> bool {
    sys.broker.retained(topic).as_deref() == Some(payload)
}

#[tokio::test]
async fn broker_restart_resubscribes_and_republishes_discovery() {
    let sys = start_default().await;
    wait_started(&sys).await;
    require(STARTUP, "initial retained discovery and state", || {
        retained_is(&sys, BRIDGE_STATE, b"ON")
            && sys.broker.retained(META_CONFIG).is_some()
            && sys.broker.retained(GROUP1_CONFIG).is_some()
            && sys.broker.retained(GROUP10_CONFIG).is_some()
    })
    .await;
    require(STARTUP, "startup status sweep", || {
        configured_sweep()
            .iter()
            .all(|payload| sys.pci.count_payload(payload) >= 1)
    })
    .await;
    let discovery_before = [META_CONFIG, GROUP1_CONFIG, GROUP10_CONFIG]
        .map(|topic| sys.broker.retained(topic).expect("retained discovery"));
    let sweeps_before = sys.pci.count_payload(&configured_sweep()[0]);

    // Crash the broker: sockets drop without DISCONNECT and the broker
    // comes back with no sessions, subscriptions or retained messages.
    let mark = sys.broker.publishes().len();
    let connections_before = sys.broker.connections();
    sys.broker.restart();
    assert!(!sys.broker.has_subscription(SET_WILDCARD));
    assert!(sys.broker.retained(GROUP1_CONFIG).is_none());

    require(STARTUP, "MQTT reconnect", || {
        sys.broker.connections() > connections_before
    })
    .await;
    require(STARTUP, "command wildcard resubscribed", || {
        sys.broker.has_subscription(SET_WILDCARD)
    })
    .await;
    require(STARTUP, "discovery and bridge state republished", || {
        retained_is(&sys, BRIDGE_STATE, b"ON")
            && [META_CONFIG, GROUP1_CONFIG, GROUP10_CONFIG]
                .iter()
                .all(|topic| sys.broker.retained(topic).is_some())
    })
    .await;
    // Byte-identical discovery: Home Assistant keeps the same entities.
    for (topic, before) in [META_CONFIG, GROUP1_CONFIG, GROUP10_CONFIG]
        .iter()
        .zip(discovery_before.iter())
    {
        assert_eq!(
            sys.broker.retained(topic).as_ref(),
            Some(before),
            "{topic} changed across the broker restart"
        );
    }

    // No fabricated state: the daemon observed no light state before the
    // crash (the fake PCI answers no sweep), so it republishes none and does
    // not repeat the startup sweep. Light state returns with the next
    // genuine observation or the periodic -S resync.
    tokio::time::sleep(Duration::from_secs(2)).await;
    let after = &sys.broker.publishes()[mark..];
    assert!(
        !after
            .iter()
            .any(|p| p.topic.starts_with("homeassistant/light/") && p.topic.ends_with("/state")),
        "light state published after broker restart without bus evidence"
    );
    assert_eq!(
        sys.pci.count_payload(&configured_sweep()[0]),
        sweeps_before,
        "an MQTT reconnect must not repeat the startup status sweep"
    );

    // A genuine bus event after the restart is retained again.
    sys.pci
        .inject(&pci_wire(&[0x05, 0x05, 0x38, 0x00, 0x79, 0x01]));
    require(STARTUP, "post-restart observed state retained", || {
        sys.broker
            .retained("homeassistant/light/cbus_1/state")
            .is_some_and(|payload| parse_json(&payload)["state"] == "ON")
    })
    .await;

    // A command published after the restart reaches the PCI exactly once.
    let commands_before = sys.pci.count_payload(CMD_FRAME);
    sys.broker.inject(CMD_TOPIC, CMD_PAYLOAD);
    require(COMMAND_DRAIN, "post-restart command frame", || {
        sys.pci.count_payload(CMD_FRAME) == commands_before + 1
    })
    .await;
    assert!(sys.broker.errors().is_empty(), "{:?}", sys.broker.errors());
}

/// A broker that loses its retained store gets back the light state cmqttd
/// had published from bus observations and PCI-confirmed command echoes,
/// byte-identical, together with the lazily discovered group's config.
/// Groups never observed stay absent and the startup sweep is not repeated.
#[tokio::test]
async fn broker_restart_republishes_observed_light_state() {
    let sys = start_default().await;
    wait_started(&sys).await;
    require(STARTUP, "startup status sweep", || {
        configured_sweep()
            .iter()
            .all(|payload| sys.pci.count_payload(payload) >= 1)
    })
    .await;
    let sweeps_before = sys.pci.count_payload(&configured_sweep()[0]);

    // Labelled group 1 ON and unlabelled group 200 OFF from the bus, and a
    // confirmed OFF command echo for labelled group 10.
    sys.pci
        .inject(&pci_wire(&[0x05, 0x05, 0x38, 0x00, 0x79, 0x01]));
    sys.pci
        .inject(&pci_wire(&[0x05, 0x05, 0x38, 0x00, 0x01, 200]));
    sys.broker.inject(CMD_TOPIC, CMD_PAYLOAD);
    let state_topics = [
        "homeassistant/light/cbus_1/state",
        "homeassistant/binary_sensor/cbus_1/state",
        "homeassistant/light/cbus_200/state",
        "homeassistant/binary_sensor/cbus_200/state",
        "homeassistant/light/cbus_10/state",
        "homeassistant/binary_sensor/cbus_10/state",
    ];
    let lazy_config = "homeassistant/light/cbus_200/config";
    let initial_state_ready = cbus_test_support::wait::wait_until(COMMAND_DRAIN, || {
        state_topics
            .iter()
            .chain([&lazy_config])
            .all(|topic| sys.broker.retained(topic).is_some())
    })
    .await;
    if !initial_state_ready {
        let retained: Vec<_> = state_topics
            .iter()
            .chain([&lazy_config])
            .map(|topic| (*topic, sys.broker.retained(topic)))
            .collect();
        panic!(
            "timed out after {COMMAND_DRAIN:?} waiting for: observed and confirmed state retained; \
             before broker restart\nretained={retained:?}\npci_frames={:?}\n\
             command_results={:?}\nbroker_connections={}\nsubscriptions={:?}\n\
             broker_errors={:?}\ndaemon_stderr:\n{}",
            sys.pci.frames(),
            sys.broker.find_publishes("cmqttd/cbus/command_result"),
            sys.broker.connections(),
            sys.broker.subscriptions(),
            sys.broker.errors(),
            sys.daemon.stderr(),
        );
    }
    let before: Vec<Vec<u8>> = state_topics
        .iter()
        .chain([&lazy_config])
        .map(|topic| sys.broker.retained(topic).unwrap())
        .collect();

    let mark = sys.broker.publishes().len();
    let connections_before = sys.broker.connections();
    sys.broker.restart();
    assert!(sys.broker.retained(state_topics[0]).is_none());
    require(STARTUP, "MQTT reconnect", || {
        sys.broker.connections() > connections_before
    })
    .await;
    require(
        STARTUP,
        "light state and lazy discovery republished",
        || {
            state_topics
                .iter()
                .chain([&lazy_config])
                .all(|topic| sys.broker.retained(topic).is_some())
        },
    )
    .await;
    for (topic, before) in state_topics.iter().chain([&lazy_config]).zip(&before) {
        assert_eq!(
            sys.broker.retained(topic).as_ref(),
            Some(before),
            "{topic} changed across the broker restart"
        );
    }

    tokio::time::sleep(Duration::from_secs(2)).await;
    let mut republished: Vec<String> = sys.broker.publishes()[mark..]
        .iter()
        .filter(|p| p.topic.ends_with("/state") && p.topic != BRIDGE_STATE)
        .map(|p| {
            assert!(p.retain, "{} republished unretained", p.topic);
            p.topic.clone()
        })
        .collect();
    republished.sort();
    let mut expected: Vec<String> = state_topics.iter().map(|t| t.to_string()).collect();
    expected.sort();
    assert_eq!(
        republished, expected,
        "exactly the observed states, once each"
    );
    assert_eq!(
        sys.pci.count_payload(&configured_sweep()[0]),
        sweeps_before,
        "an MQTT reconnect must not repeat the startup status sweep"
    );
    assert!(sys.broker.errors().is_empty(), "{:?}", sys.broker.errors());
}

/// Plain `-t` CNI mode has no in-process reconnect: on TCP loss cmqttd
/// retains bridge state OFF and exits 0 so the container supervisor
/// (`restart: always`) starts a fresh process. This asserts that policy and
/// that the restarted process fully recovers against the same broker.
#[tokio::test]
async fn cni_tcp_drop_exits_and_supervisor_restart_recovers() {
    let mut sys = start_default().await;
    wait_started(&sys).await;
    require(STARTUP, "initial sweep and bridge state", || {
        retained_is(&sys, BRIDGE_STATE, b"ON")
            && configured_sweep()
                .iter()
                .all(|payload| sys.pci.count_payload(payload) >= 1)
    })
    .await;
    let discovery_before = sys.broker.retained(GROUP1_CONFIG).expect("discovery");

    sys.pci.kick();
    let status = sys
        .daemon
        .wait_exit(Duration::from_secs(10))
        .await
        .expect("plain TCP mode exits on CNI loss");
    assert!(status.success(), "clean exit expected, got {status:?}");
    require(Duration::from_secs(2), "retained bridge OFF", || {
        retained_is(&sys, BRIDGE_STATE, b"OFF")
    })
    .await;
    // The retained light config survives the process exit on the broker.
    assert_eq!(
        sys.broker.retained(GROUP1_CONFIG),
        Some(discovery_before.clone())
    );

    // The supervisor restart: a fresh process with identical arguments.
    let broker_port = sys.broker.port().to_string();
    let pci_addr = format!("127.0.0.1:{}", sys.pci.port());
    let project = project_file();
    sys.daemon = cbus_test_support::proc::Daemon::spawn(
        BIN,
        &[
            "-b",
            "127.0.0.1",
            "-p",
            &broker_port,
            "--broker-disable-tls",
            "-t",
            &pci_addr,
            "-T",
            "0",
            "-v",
            "DEBUG",
            "-P",
            &project,
        ],
    );
    require(STARTUP, "CNI reconnect", || sys.pci.connections() >= 2).await;
    require(STARTUP, "re-init smart connect", || {
        sys.pci.smart_connect_count() >= 2
    })
    .await;
    require(STARTUP, "fresh configured sweep", || {
        configured_sweep()
            .iter()
            .all(|payload| sys.pci.count_payload(payload) >= 2)
    })
    .await;
    require(STARTUP, "retained bridge ON after restart", || {
        retained_is(&sys, BRIDGE_STATE, b"ON")
    })
    .await;
    assert_eq!(sys.broker.retained(GROUP1_CONFIG), Some(discovery_before));

    let commands_before = sys.pci.count_payload(CMD_FRAME);
    sys.broker.inject(CMD_TOPIC, CMD_PAYLOAD);
    require(COMMAND_DRAIN, "command after supervisor restart", || {
        sys.pci.count_payload(CMD_FRAME) == commands_before + 1
    })
    .await;
}

/// Two independent MQTT subscribers (e.g. Home Assistant plus a logger)
/// each receive every state publish of a bus-event burst, in bus order.
#[tokio::test]
async fn two_client_mqtt_fanout_under_event_burst() {
    use rumqttc::{AsyncClient, Event, MqttOptions, Packet, QoS};
    use std::sync::{Arc, Mutex};

    type PublishLog = Arc<Mutex<Vec<(String, Vec<u8>)>>>;
    const FILTER: &str = "homeassistant/light/+/state";
    const BURST: u8 = 60;

    let sys = start_default().await;
    wait_started(&sys).await;
    require(STARTUP, "startup status sweep", || {
        configured_sweep()
            .iter()
            .all(|payload| sys.pci.count_payload(payload) >= 1)
    })
    .await;

    let mut received = Vec::new();
    for name in ["fanout-a", "fanout-b"] {
        let log: PublishLog = Arc::default();
        let mut options = MqttOptions::new(name, "127.0.0.1", sys.broker.port());
        options.set_keep_alive(Duration::from_secs(30));
        let (client, mut eventloop) = AsyncClient::new(options, 16);
        client.subscribe(FILTER, QoS::AtMostOnce).await.unwrap();
        let sink = log.clone();
        tokio::spawn(async move {
            // keep the client alive for the task's lifetime
            let _client = client;
            while let Ok(event) = eventloop.poll().await {
                if let Event::Incoming(Packet::Publish(publish)) = event {
                    sink.lock()
                        .unwrap()
                        .push((publish.topic, publish.payload.to_vec()));
                }
            }
        });
        received.push(log);
    }
    require(STARTUP, "both subscribers attached", || {
        sys.broker
            .subscriptions()
            .iter()
            .filter(|filter| *filter == FILTER)
            .count()
            == 2
    })
    .await;
    // Settle past any late startup readback so the burst window is clean.
    tokio::time::sleep(Duration::from_millis(500)).await;
    let mark = sys.broker.publishes().len();
    for log in &received {
        log.lock().unwrap().clear();
    }

    // Burst: instant ramps of group 1 through levels 1..=BURST, interleaved
    // with ON/OFF toggles of group 10, written back to back by the CNI.
    for level in 1..=BURST {
        sys.pci
            .inject(&pci_wire(&[0x05, 0x05, 0x38, 0x00, 0x02, 0x01, level]));
        let toggle = if level % 2 == 0 { 0x79 } else { 0x01 };
        sys.pci
            .inject(&pci_wire(&[0x05, 0x05, 0x38, 0x00, toggle, 0x0a]));
    }

    let expected_len = 2 * BURST as usize;
    let published = || {
        sys.broker.publishes()[mark..]
            .iter()
            .filter(|p| cbus_test_support::broker::topic_matches(FILTER, &p.topic))
            .map(|p| (p.topic.clone(), p.payload.clone()))
            .collect::<Vec<_>>()
    };
    require(
        Duration::from_secs(30),
        "every burst state published",
        || published().len() >= expected_len,
    )
    .await;
    require(
        Duration::from_secs(30),
        "every subscriber caught up",
        || {
            received
                .iter()
                .all(|log| log.lock().unwrap().len() >= expected_len)
        },
    )
    .await;
    tokio::time::sleep(Duration::from_millis(300)).await;

    let published = published();
    assert_eq!(published.len(), expected_len, "one state per bus event");
    let levels = published
        .iter()
        .filter(|(topic, _)| topic == "homeassistant/light/cbus_1/state")
        .map(|(_, payload)| parse_json(payload)["brightness"].as_u64().unwrap())
        .collect::<Vec<_>>();
    assert_eq!(
        levels,
        (1..=BURST as u64).collect::<Vec<_>>(),
        "bus order kept"
    );
    let toggles = published
        .iter()
        .filter(|(topic, _)| topic == "homeassistant/light/cbus_10/state")
        .map(|(_, payload)| parse_json(payload)["state"].as_str().unwrap().to_owned())
        .collect::<Vec<_>>();
    assert_eq!(toggles.len(), BURST as usize);
    assert_eq!(toggles.last().map(String::as_str), Some("ON"));
    for (index, log) in received.iter().enumerate() {
        assert_eq!(
            *log.lock().unwrap(),
            published,
            "subscriber {index} diverged from the daemon's publish order"
        );
    }
}

#[tokio::test]
async fn invalid_mqtt_credentials_fail_before_opening_the_pci() {
    let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    listener.set_nonblocking(true).unwrap();
    let addr = listener.local_addr().unwrap().to_string();
    for security_args in [
        vec!["-c", "/nonexistent/cmqttd-ca.pem"],
        vec!["--broker-disable-tls", "-A", "/nonexistent/cmqttd-auth"],
    ] {
        let mut args = vec!["-b", "127.0.0.1", "-t", &addr, "-T", "0"];
        args.extend(security_args);
        let mut daemon = Daemon::spawn(BIN, &args);
        let status = daemon
            .wait_exit(Duration::from_secs(10))
            .await
            .expect("bad MQTT configuration must fail promptly");
        assert!(!status.success());
        assert!(
            daemon.stderr().contains("cannot read"),
            "{}",
            daemon.stderr()
        );
        assert!(
            matches!(listener.accept(), Err(error) if error.kind() == std::io::ErrorKind::WouldBlock),
            "invalid configuration must not open or reset the PCI"
        );
    }
}

/// Exercise the actual CONNECT will and shutdown PUBLISH against a separate
/// MQTT observer. This catches both missing wills and clean-disconnect paths
/// that suppress the will without first clearing retained availability.
#[tokio::test]
async fn mqtt_observer_sees_retained_off_after_graceful_exit_and_crash() {
    use rumqttc::{AsyncClient, Event, MqttOptions, Packet, QoS};
    const TOPIC: &str = "homeassistant/binary_sensor/cbus_cmqttd/state";

    for signal in ["TERM", "KILL"] {
        let mut sys = start_default().await;
        wait_started(&sys).await;
        require(STARTUP, "initial connected availability", || {
            sys.broker.retained(TOPIC).as_deref() == Some(b"ON")
        })
        .await;
        let options = MqttOptions::new(
            format!("availability-observer-{signal}"),
            "127.0.0.1",
            sys.broker.port(),
        );
        let (observer, mut events) = AsyncClient::new(options, 10);
        observer.subscribe(TOPIC, QoS::AtLeastOnce).await.unwrap();
        let (states, mut received) = tokio::sync::mpsc::unbounded_channel();
        let poller = tokio::spawn(async move {
            while let Ok(event) = events.poll().await {
                if let Event::Incoming(Packet::Publish(publish)) = event {
                    if publish.topic == TOPIC {
                        let _ = states.send(publish.payload);
                    }
                }
            }
        });
        require(STARTUP, "availability observer subscription", || {
            sys.broker.has_subscription(TOPIC)
        })
        .await;
        sys.daemon.signal(signal);
        let status = sys
            .daemon
            .wait_exit(Duration::from_secs(10))
            .await
            .expect("daemon exit");
        assert_eq!(status.success(), signal == "TERM");
        let observed = tokio::time::timeout(Duration::from_secs(5), received.recv())
            .await
            .expect("observer must receive OFF")
            .expect("observer channel remains open");
        assert_eq!(observed.as_ref(), b"OFF", "signal {signal}");
        assert_eq!(
            sys.broker.retained(TOPIC).as_deref(),
            Some(b"OFF".as_slice())
        );
        assert_eq!(
            sys.broker.clean_disconnects(),
            usize::from(signal == "TERM")
        );
        poller.abort();
    }
}

#[tokio::test]
async fn invalid_cgate_security_fails_before_opening_the_pci_or_creating_state() {
    let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    listener.set_nonblocking(true).unwrap();
    let addr = listener.local_addr().unwrap().to_string();
    let project = project_file();
    let certificate = testdata_dir().join("fixtures/cgate-tls-test-cert.pem");
    let key = testdata_dir().join("fixtures/cgate-tls-test-key.pem");
    let missing = temp_path("missing-cgate-security");
    let invalid = temp_path("invalid-cgate-security");
    std::fs::write(&invalid, b"invalid security material\n").unwrap();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&invalid, std::fs::Permissions::from_mode(0o600)).unwrap();
    }
    let state = temp_path("invalid-cgate-security-state.json");
    for security_args in [
        vec!["--cgate-auth-file", missing.to_str().unwrap()],
        vec!["--cgate-auth-file", invalid.to_str().unwrap()],
        vec![
            "--cgate-tls-cert",
            certificate.to_str().unwrap(),
            "--cgate-tls-key",
            missing.to_str().unwrap(),
        ],
        vec![
            "--cgate-tls-cert",
            certificate.to_str().unwrap(),
            "--cgate-tls-key",
            invalid.to_str().unwrap(),
        ],
        vec![
            "--cgate-tls-cert",
            certificate.to_str().unwrap(),
            "--cgate-tls-key",
            key.to_str().unwrap(),
            "--cgate-tls-client-ca",
            missing.to_str().unwrap(),
        ],
    ] {
        let mut args = vec![
            "-b",
            "127.0.0.1",
            "--broker-disable-tls",
            "-t",
            &addr,
            "-T",
            "0",
            "-P",
            &project,
            "--cgate-bind",
            "127.0.0.1:0",
            "--cgate-state",
            state.to_str().unwrap(),
        ];
        args.extend(security_args);
        let mut daemon = Daemon::spawn(BIN, &args);
        let status = daemon
            .wait_exit(Duration::from_secs(10))
            .await
            .expect("invalid C-Gate security must fail promptly");
        assert!(!status.success());
        assert!(
            daemon.stderr().contains("cannot start C-Gate service"),
            "{}",
            daemon.stderr()
        );
        assert!(
            matches!(listener.accept(), Err(error) if error.kind() == std::io::ErrorKind::WouldBlock),
            "invalid C-Gate security must not open or reset the PCI"
        );
        assert!(
            !state.exists(),
            "invalid security must not create C-Gate state"
        );
    }
    std::fs::remove_file(invalid).unwrap();
}
