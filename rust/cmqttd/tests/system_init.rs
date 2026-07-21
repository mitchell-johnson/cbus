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
        .map(|f| f["payload"].as_str().unwrap().to_string())
        .filter(|p| p.starts_with("A3"))
        .collect();
    let got: Vec<String> = dm_init_frames(&sys)
        .into_iter()
        .map(|f| f.payload)
        .collect();
    assert_eq!(got[..4], expect[..]);
}

#[tokio::test]
async fn dm_init_frames_carry_no_confirmation() {
    let sys = start_default().await;
    require(STARTUP, "4 DM init frames", || {
        dm_init_frames(&sys).len() >= 4
    })
    .await;
    // deployed-faithful: the PCI is still echoing in basic mode during
    // init; requesting confirmations here caused retry storms on the
    // real CNI
    for f in dm_init_frames(&sys).iter().take(4) {
        assert_eq!(f.conf, None, "init DM frame must be codeless: {f:?}");
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
        sys.broker.has_subscription("homeassistant/light/+/set")
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
async fn status_sweep_is_configured_blocks_binary_then_level() {
    let sys = start_default().await;
    let sweep = configured_sweep();
    require(Duration::from_secs(30), "configured status sweep", || {
        sys.pci
            .payloads()
            .iter()
            .filter(|p| is_status_request(p))
            .count()
            >= sweep.len()
    })
    .await;
    // exactly the blocks holding the project's labelled groups, apps
    // ascending, binary status before level status per block
    let observed: Vec<String> = sys
        .pci
        .payloads()
        .into_iter()
        .filter(|p| is_status_request(p))
        .take(sweep.len())
        .collect();
    assert_eq!(observed, sweep);
}

#[tokio::test]
async fn status_requests_carry_no_confirmation() {
    let sys = start_default().await;
    let sweep = configured_sweep();
    require(Duration::from_secs(30), "configured status sweep", || {
        sys.pci
            .frames()
            .iter()
            .filter(|f| is_status_request(&f.payload))
            .count()
            >= sweep.len()
    })
    .await;
    // deployed-faithful: status reports are their own replies; asking
    // for confirmations creates a retry backlog that starves them
    for f in sys
        .pci
        .frames()
        .iter()
        .filter(|f| is_status_request(&f.payload))
    {
        assert_eq!(f.conf, None, "status request must be codeless: {f:?}");
    }
}

/// The test that would have caught the live regression: the full init
/// sequence (3 resets, smart connect, 4 DM frames) must be on the wire
/// before ANY other frame — the repo Python interleaved status requests
/// into the init sequence, garbling replies on the real CNI.
#[tokio::test]
async fn init_sequence_completes_before_any_status_request() {
    let sys = start_default().await;
    require(Duration::from_secs(30), "first status request", || {
        sys.pci.payloads().iter().any(|p| is_status_request(p))
    })
    .await;
    let frames = sys.pci.frames();
    let is_init = |f: &cbus_test_support::pci::ClientFrame| {
        f.is_reset || f.is_smart_connect || f.payload.starts_with("A3")
    };
    let first_other = frames
        .iter()
        .position(|f| !is_init(f))
        .expect("a status request was seen");
    assert!(
        frames[..first_other].iter().filter(|f| is_init(f)).count() >= 8,
        "full init (3 resets + | + 4 DM) must precede all other traffic; got {:?}",
        frames[..first_other.min(10)]
            .iter()
            .map(|f| f.payload.clone())
            .collect::<Vec<_>>()
    );
    assert!(
        !frames[first_other..].iter().any(&is_init),
        "init frames must not reappear after other traffic started"
    );
}

#[tokio::test]
async fn status_resync_flag_repeats_the_sweep() {
    // -S 1: the configured sweep is re-queued every second
    let sys = start_with(Options {
        extra: vec!["-S".into(), "1".into()],
        ..Default::default()
    })
    .await;
    let sweep_len = configured_sweep().len();
    require(Duration::from_secs(30), "sweep runs at least twice", || {
        sys.pci
            .payloads()
            .iter()
            .filter(|p| is_status_request(p))
            .count()
            >= 2 * sweep_len
    })
    .await;
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
    // the default labels ({56: ("Lighting", {})}) configure no real
    // groups, so no status sweep runs either
    tokio::time::sleep(Duration::from_millis(500)).await;
    assert!(
        !sys.pci.payloads().iter().any(|p| is_status_request(p)),
        "no labelled groups -> no status sweep"
    );
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
