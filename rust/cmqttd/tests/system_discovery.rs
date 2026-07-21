//! Full-system Home Assistant discovery tests: project-file label
//! configs, /set subscriptions, retained flags and lazy discovery for
//! unknown groups, against the committed behavioral expectations.

mod util;

use serde_json::{json, Value};
use util::*;

async fn require_config(sys: &System, topic: &str) -> Value {
    require(STARTUP, "discovery config publish", || {
        !sys.broker.find_publishes(topic).is_empty()
    })
    .await;
    parse_json(&sys.broker.find_publishes(topic)[0].payload)
}

/// The fixture label_config entry for one group.
fn label_config(group: u64, app: u64) -> &'static Value {
    expectations()["label_configs"]
        .as_array()
        .unwrap()
        .iter()
        .find(|c| c["group_addr"] == json!(group) && c["app_addr"] == json!(app))
        .unwrap()
}

#[tokio::test]
async fn kitchen_bench_config_exact() {
    let sys = start_default().await;
    let fix = label_config(1, 56);
    let got = require_config(&sys, fix["config_topic"].as_str().unwrap()).await;
    assert_eq!(got, fix["config"]);
}

#[tokio::test]
async fn lounge_config_exact() {
    let sys = start_default().await;
    let fix = label_config(10, 56);
    let got = require_config(&sys, fix["config_topic"].as_str().unwrap()).await;
    assert_eq!(got, fix["config"]);
}

#[tokio::test]
async fn deck_alt_app_config_exact() {
    let sys = start_default().await;
    let fix = label_config(11, 48);
    let got = require_config(&sys, fix["config_topic"].as_str().unwrap()).await;
    assert_eq!(got, fix["config"]);
}

#[tokio::test]
async fn binary_sensor_config_for_labelled_group() {
    let sys = start_default().await;
    let got = require_config(&sys, "homeassistant/binary_sensor/cbus_1/config").await;
    assert_eq!(
        got,
        json!({
            "name": "Kitchen Bench (as binary sensor)",
            "unique_id": "cbus_bin_sensor_1",
            "stat_t": "homeassistant/binary_sensor/cbus_1/state",
            "device": {
                "identifiers": ["cbus_bin_sensor_1"],
                "connections": [["cbus_group_address", "1"],
                                ["cbus_application_address", "56"]],
                "sw_version": "cmqttd https://github.com/mitchell-johnson/cbus",
                "name": "C-Bus Light 001",
                "manufacturer": "Clipsal",
                "model": "C-Bus Lighting Application",
                "via_device": "cmqttd",
            },
        })
    );
}

#[tokio::test]
async fn set_topics_subscribed_for_every_project_group() {
    let sys = start_default().await;
    for topic in [
        "homeassistant/light/cbus_1/set",
        "homeassistant/light/cbus_10/set",
        "homeassistant/light/cbus_048_011/set",
    ] {
        require(STARTUP, topic, || sys.broker.has_subscription(topic)).await;
    }
}

#[tokio::test]
async fn discovery_configs_are_retained_qos1() {
    let sys = start_default().await;
    wait_started(&sys).await;
    let configs: Vec<_> = sys
        .broker
        .publishes()
        .into_iter()
        .filter(|p| p.topic.ends_with("/config"))
        .collect();
    assert!(configs.len() >= 7, "meta + 3 lights + 3 sensors");
    for c in &configs {
        assert_eq!((c.qos, c.retain), (1, true), "{}", c.topic);
    }
}

#[tokio::test]
async fn unknown_group_event_lazily_publishes_default_config_first() {
    let sys = start_default().await;
    wait_started(&sys).await;
    // group 2 is not in the project file
    sys.pci
        .inject(&pci_wire(&[0x05, 0x99, 0x38, 0x00, 0x79, 0x02]));
    let state_topic = "homeassistant/light/cbus_2/state";
    let config_topic = expectations()["lazy_config_ga2"]["topic"].as_str().unwrap();
    require(STARTUP, "lazy state publish", || {
        !sys.broker.find_publishes(state_topic).is_empty()
    })
    .await;
    let config = sys.broker.find_publishes(config_topic);
    assert!(!config.is_empty(), "config must be published for group 2");
    assert_eq!(
        parse_json(&config[0].payload),
        expectations()["lazy_config_ga2"]["config"],
        "lazy config uses the default C-Bus Light 002 name"
    );
    // ordering: the discovery config precedes the first state publish
    let first_state = &sys.broker.find_publishes(state_topic)[0];
    assert!(
        config[0].ts <= first_state.ts,
        "config must precede the state publish"
    );
}

#[tokio::test]
async fn known_group_event_does_not_republish_config() {
    let sys = start_default().await;
    wait_started(&sys).await;
    let config_topic = "homeassistant/light/cbus_1/config";
    require(STARTUP, "startup config", || {
        !sys.broker.find_publishes(config_topic).is_empty()
    })
    .await;
    let before = sys.broker.find_publishes(config_topic).len();
    sys.pci
        .inject(&pci_wire(&[0x05, 0x99, 0x38, 0x00, 0x79, 0x01]));
    require(STARTUP, "state publish for group 1", || {
        !sys.broker
            .find_publishes("homeassistant/light/cbus_1/state")
            .is_empty()
    })
    .await;
    assert_eq!(
        sys.broker.find_publishes(config_topic).len(),
        before,
        "config already published at startup must not repeat"
    );
}

#[tokio::test]
async fn lazy_config_not_republished_on_second_event() {
    let sys = start_default().await;
    wait_started(&sys).await;
    sys.pci
        .inject(&pci_wire(&[0x05, 0x99, 0x38, 0x00, 0x79, 0x03]));
    let state_topic = "homeassistant/light/cbus_3/state";
    require(STARTUP, "first state publish", || {
        !sys.broker.find_publishes(state_topic).is_empty()
    })
    .await;
    sys.pci
        .inject(&pci_wire(&[0x05, 0x99, 0x38, 0x00, 0x01, 0x03]));
    require(STARTUP, "second state publish", || {
        sys.broker.find_publishes(state_topic).len() >= 2
    })
    .await;
    assert_eq!(
        sys.broker
            .find_publishes("homeassistant/light/cbus_3/config")
            .len(),
        1,
        "lazy discovery config is published exactly once"
    );
}
