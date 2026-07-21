//! Full-system startup tests: spawn the real cmqttd against the mini
//! broker + fake PCI and assert the exact PCI init sequence, MQTT 3.1.1
//! session setup and the status-request stream, using the committed
//! behavioral expectations as the oracle.

mod util;

use serde_json::Value;
use std::time::Duration;
use util::*;

#[tokio::test]
async fn connects_to_pci_on_startup() {
    let sys = start_default().await;
    require(STARTUP, "PCI TCP connection", || sys.pci.connections() == 1).await;
}

#[tokio::test]
async fn sends_three_resets_then_smart_connect() {
    let sys = start_default().await;
    require(STARTUP, "three ~ resets", || sys.pci.reset_count() == 3).await;
    require(STARTUP, "| smart connect", || {
        sys.pci.smart_connect_count() == 1
    })
    .await;
    // order: the smart connect comes after all three resets
    let frames = sys.pci.frames();
    let smart_pos = frames.iter().position(|f| f.is_smart_connect).unwrap();
    let resets = frames[..smart_pos].iter().filter(|f| f.is_reset).count();
    assert_eq!(resets, 3, "resets must precede the smart connect");
}

#[tokio::test]
async fn dm_init_sequence_payloads_in_fixture_order() {
    let sys = start_default().await;
    require(STARTUP, "4 DM init frames", || {
        dm_init_frames(&sys).len() >= 4
    })
    .await;
    let expect: Vec<String> = expectations()["init_frames"]
        .as_array()
        .unwrap()
        .iter()
        .filter(|f| f["conf"].as_bool().unwrap())
        .map(|f| f["payload"].as_str().unwrap().to_string())
        .collect();
    let got: Vec<String> = dm_init_frames(&sys)
        .into_iter()
        .map(|f| f.payload)
        .collect();
    assert_eq!(got[..4], expect[..]);
}

#[tokio::test]
async fn dm_init_frames_use_distinct_pool_confirmations() {
    let sys = start_default().await;
    require(STARTUP, "4 DM init frames", || {
        dm_init_frames(&sys).len() >= 4
    })
    .await;
    let confs: Vec<u8> = dm_init_frames(&sys)
        .iter()
        .take(4)
        .map(|f| f.conf.expect("init DM frame must carry a confirmation"))
        .collect();
    assert_eq!(confs.len(), 4);
    let mut distinct = confs.clone();
    distinct.sort_unstable();
    distinct.dedup();
    assert_eq!(distinct.len(), 4, "confirmation codes must be distinct");
    for c in confs {
        assert!(
            b"hijklmnopqrstuvwxyzg".contains(&c),
            "code {c:#04x} not in the pool"
        );
    }
}

#[tokio::test]
async fn dm_init_frames_are_basic_mode_without_checksum() {
    let sys = start_default().await;
    require(STARTUP, "4 DM init frames", || {
        dm_init_frames(&sys).len() >= 4
    })
    .await;
    for f in dm_init_frames(&sys).iter().take(4) {
        assert!(f.basic, "init DM frames have no \\ prefix: {f:?}");
        assert_eq!(f.payload.len(), 8, "no checksum byte: {f:?}");
    }
}

#[tokio::test]
async fn speaks_mqtt_311_and_broker_accepts() {
    let sys = start_default().await;
    require(STARTUP, "MQTT connection", || sys.broker.connections() >= 1).await;
    require(STARTUP, "MQTT wildcard subscription", || {
        sys.broker.has_subscription("homeassistant/light/#")
    })
    .await;
    assert_eq!(
        sys.broker.errors(),
        Vec::<String>::new(),
        "broker must accept the protocol level"
    );
}

#[tokio::test]
async fn publishes_exact_meta_config_retained() {
    let sys = start_default().await;
    let topic = expectations()["meta_config"]["topic"].as_str().unwrap();
    require(STARTUP, "meta config publish", || {
        !sys.broker.find_publishes(topic).is_empty()
    })
    .await;
    let rec = &sys.broker.find_publishes(topic)[0];
    assert_eq!(rec.qos, 1);
    assert!(rec.retain);
    let got: Value = parse_json(&rec.payload);
    assert_eq!(got, expectations()["meta_config"]["config"]);
}

#[tokio::test]
async fn status_requests_start_with_first_lighting_app_block() {
    let sys = start_default().await;
    let first = expectations()["status_requests"]["30:00"].as_str().unwrap();
    require(STARTUP, "first status request", || {
        sys.pci.count_payload(first) >= 1
    })
    .await;
}

#[tokio::test]
async fn status_requests_byte_match_fixture_and_order() {
    let sys = start_default().await;
    require(Duration::from_secs(30), "10 status requests", || {
        sys.pci
            .payloads()
            .iter()
            .filter(|p| p.starts_with("05FF0073"))
            .count()
            >= 10
    })
    .await;
    let fixture = expectations()["status_requests"].as_object().unwrap();
    let observed: Vec<String> = sys
        .pci
        .payloads()
        .into_iter()
        .filter(|p| p.starts_with("05FF0073"))
        .take(10)
        .collect();
    // every frame byte-matches a fixture entry...
    for p in &observed {
        assert!(
            fixture.values().any(|v| v.as_str() == Some(p)),
            "unexpected status request frame {p}"
        );
    }
    // ...and the stream walks app 0x30's blocks in order (0,32,...)
    let expect_first: Vec<&str> = ["30:00", "30:20", "30:40", "30:60", "30:80"]
        .iter()
        .map(|k| fixture[*k].as_str().unwrap())
        .collect();
    assert_eq!(observed[..5], expect_first[..]);
}

#[tokio::test]
async fn status_requests_are_throttled_not_burst() {
    let sys = start_default().await;
    require(Duration::from_secs(30), "6 status requests", || {
        sys.pci
            .frames()
            .iter()
            .filter(|f| f.payload.starts_with("05FF0073"))
            .count()
            >= 6
    })
    .await;
    let times: Vec<_> = sys
        .pci
        .frames()
        .iter()
        .filter(|f| f.payload.starts_with("05FF0073"))
        .take(6)
        .map(|f| f.ts)
        .collect();
    // 0.2 s throttle: allow generous scheduler jitter but reject a burst
    for pair in times.windows(2).skip(1) {
        let gap = pair[1].duration_since(pair[0]);
        assert!(
            gap >= Duration::from_millis(100),
            "status requests burst through the throttle: gap {gap:?}"
        );
    }
}

#[tokio::test]
async fn no_project_file_publishes_no_light_configs_at_startup() {
    let sys = start_no_project().await;
    wait_started(&sys).await;
    let configs: Vec<String> = sys
        .broker
        .publishes()
        .into_iter()
        .map(|p| p.topic)
        .filter(|t| t.starts_with("homeassistant/light/") && t.ends_with("/config"))
        .collect();
    assert_eq!(configs, Vec::<String>::new());
}

#[tokio::test]
async fn debug_verbosity_writes_stderr_logs() {
    let sys = start_default().await;
    wait_started(&sys).await;
    assert!(
        !sys.daemon.stderr().is_empty(),
        "-v DEBUG must produce log output"
    );
}

#[tokio::test]
async fn log_file_option_writes_file() {
    let log_path = cbus_test_support::proc::temp_path("cmqttd.log");
    let sys = start_with(Options {
        extra: vec!["-l".into(), log_path.to_string_lossy().into_owned()],
        ..Default::default()
    })
    .await;
    wait_started(&sys).await;
    let content = std::fs::read_to_string(&log_path).unwrap_or_default();
    std::fs::remove_file(&log_path).ok();
    assert!(!content.is_empty(), "-l must write the log file");
}

#[tokio::test]
async fn daemon_stays_running_after_startup() {
    let mut sys = start_default().await;
    wait_started(&sys).await;
    assert!(sys.daemon.is_running());
}
