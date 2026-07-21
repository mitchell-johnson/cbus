//! Full-system MQTT-command-to-PCI tests: a /set publish must produce the
//! exact point-to-multipoint frame on the PCI (smart mode, checksummed,
//! confirmed) and an MQTT state echo. Commands take the flow controller's
//! priority lane, ahead of any queued startup status sweep.

mod util;

use serde_json::{json, Value};
use util::*;

/// Inject a /set publish and wait for the exact PCI payload, then return
/// the state-echo publishes seen on `echo_topic` after the frame.
async fn command_roundtrip(
    sys: &System,
    topic: &str,
    payload: &Value,
    expect_pci: &str,
    echo_topic: &str,
    expect_echo: &Value,
) {
    sys.broker.inject(topic, payload.to_string().as_bytes());
    require(COMMAND_DRAIN, "command frame on PCI", || {
        sys.pci.count_payload(expect_pci) >= 1
    })
    .await;
    let frame = sys
        .pci
        .frames()
        .into_iter()
        .find(|f| f.payload == expect_pci)
        .unwrap();
    assert!(!frame.basic, "commands are smart-mode (\\-prefixed) frames");
    let conf = frame.conf.expect("commands request confirmation");
    assert!(b"hijklmnopqrstuvwxyzg".contains(&conf));
    require(COMMAND_DRAIN, "MQTT state echo", || {
        sys.broker
            .find_publishes(echo_topic)
            .iter()
            .any(|p| serde_json::from_slice::<Value>(&p.payload).ok().as_ref() == Some(expect_echo))
    })
    .await;
}

#[tokio::test]
async fn set_off_default_app_reaches_pci_and_echoes() {
    let sys = start_default().await;
    wait_started(&sys).await;
    let fix = &expectations()["mqtt_cmd_off_default_app"];
    command_roundtrip(
        &sys,
        fix["topic"].as_str().unwrap(),
        &fix["payload"],
        fix["expect_pci_payload"].as_str().unwrap(),
        fix["echo_state_topic"].as_str().unwrap(),
        &fix["echo_state_payload"],
    )
    .await;
}

#[tokio::test]
async fn set_on_alt_app_reaches_pci_and_echoes() {
    let sys = start_default().await;
    wait_started(&sys).await;
    let fix = &expectations()["mqtt_cmd_on_alt_app"];
    command_roundtrip(
        &sys,
        fix["topic"].as_str().unwrap(),
        &fix["payload"],
        fix["expect_pci_payload"].as_str().unwrap(),
        fix["echo_state_topic"].as_str().unwrap(),
        &fix["echo_state_payload"],
    )
    .await;
}

#[tokio::test]
async fn set_on_full_brightness_sends_lighting_on() {
    let sys = start_default().await;
    wait_started(&sys).await;
    // ON at default brightness 255 / transition 0 -> plain lighting-on
    command_roundtrip(
        &sys,
        "homeassistant/light/cbus_1/set",
        &json!({"state": "ON"}),
        "053800790149",
        "homeassistant/light/cbus_1/state",
        &json!({"state": "ON", "brightness": 255, "transition": 0,
                "cbus_source_addr": null}),
    )
    .await;
}

#[tokio::test]
async fn set_brightness_and_transition_sends_ramp() {
    let sys = start_default().await;
    wait_started(&sys).await;
    // 12 s transition -> ramp code 0x1A, level 128
    command_roundtrip(
        &sys,
        "homeassistant/light/cbus_1/set",
        &json!({"state": "ON", "brightness": 128, "transition": 12}),
        "0538001A018028",
        "homeassistant/light/cbus_1/state",
        &json!({"state": "ON", "brightness": 128, "transition": 12,
                "cbus_source_addr": null}),
    )
    .await;
}

#[tokio::test]
async fn set_brightness_without_transition_sends_instant_ramp() {
    let sys = start_default().await;
    wait_started(&sys).await;
    // brightness < 255 with transition 0 -> instant ramp (code 0x02)
    command_roundtrip(
        &sys,
        "homeassistant/light/cbus_1/set",
        &json!({"state": "ON", "brightness": 10}),
        "05380002010AB6",
        "homeassistant/light/cbus_1/state",
        &json!({"state": "ON", "brightness": 10, "transition": 0,
                "cbus_source_addr": null}),
    )
    .await;
}

#[tokio::test]
async fn set_invalid_lighting_app_never_reaches_pci() {
    let sys = start_default().await;
    wait_started(&sys).await;
    // app 999 parses but LightingSAL rejects apps outside 0x30..=0x5F
    sys.broker.inject(
        "homeassistant/light/cbus_999_010/set",
        br#"{"state": "OFF"}"#,
    );
    // positive control: a valid command afterwards must still arrive
    sys.broker
        .inject("homeassistant/light/cbus_10/set", br#"{"state": "OFF"}"#);
    require(COMMAND_DRAIN, "control command frame", || {
        sys.pci.count_payload("053800010AB8") >= 1
    })
    .await;
    // the only lighting command frames are the control's
    let lighting: Vec<String> = sys
        .pci
        .payloads()
        .into_iter()
        .filter(|p| !is_status_request(p) && !p.starts_with("A3"))
        .collect();
    assert_eq!(lighting, vec!["053800010AB8".to_string()]);
}

#[tokio::test]
async fn set_malformed_json_ignored() {
    let sys = start_default().await;
    wait_started(&sys).await;
    sys.broker
        .inject("homeassistant/light/cbus_10/set", b"{not json");
    sys.broker
        .inject("homeassistant/light/cbus_10/set", br#"{"state": "OFF"}"#);
    require(COMMAND_DRAIN, "control command frame", || {
        sys.pci.count_payload("053800010AB8") >= 1
    })
    .await;
    assert_eq!(
        sys.pci.count_payload("053800010AB8"),
        1,
        "only the well-formed command may reach the PCI"
    );
}

#[tokio::test]
async fn set_out_of_range_group_ignored() {
    let sys = start_default().await;
    wait_started(&sys).await;
    sys.broker
        .inject("homeassistant/light/cbus_400/set", br#"{"state": "OFF"}"#);
    sys.broker
        .inject("homeassistant/light/cbus_10/set", br#"{"state": "OFF"}"#);
    require(COMMAND_DRAIN, "control command frame", || {
        sys.pci.count_payload("053800010AB8") >= 1
    })
    .await;
    let lighting: Vec<String> = sys
        .pci
        .payloads()
        .into_iter()
        .filter(|p| !is_status_request(p) && !p.starts_with("A3"))
        .collect();
    assert_eq!(lighting, vec!["053800010AB8".to_string()]);
}

#[tokio::test]
async fn retained_set_command_is_ignored() {
    let sys = start_default().await;
    wait_started(&sys).await;
    // a retained /set is stale broker state, not user intent: acting on
    // it would replay old switch commands on every (re)subscribe
    sys.broker
        .inject_retained("homeassistant/light/cbus_10/set", br#"{"state": "OFF"}"#);
    // positive control: a fresh (non-retained) command still works
    sys.broker
        .inject("homeassistant/light/cbus_1/set", br#"{"state": "ON"}"#);
    require(COMMAND_DRAIN, "control command frame", || {
        sys.pci.count_payload("053800790149") >= 1
    })
    .await;
    assert_eq!(
        sys.pci.count_payload("053800010AB8"),
        0,
        "a retained /set must never reach the PCI"
    );
}

#[tokio::test]
async fn state_topic_publish_is_not_a_command() {
    let sys = start_default().await;
    wait_started(&sys).await;
    // a /state publish (as cmqttd itself emits) must never loop back
    sys.broker.inject(
        "homeassistant/light/cbus_10/state",
        br#"{"state": "OFF", "brightness": 0}"#,
    );
    sys.broker
        .inject("homeassistant/light/cbus_1/set", br#"{"state": "ON"}"#);
    require(COMMAND_DRAIN, "control command frame", || {
        sys.pci.count_payload("053800790149") >= 1
    })
    .await;
    assert_eq!(
        sys.pci.count_payload("053800010AB8"),
        0,
        "a /state publish must not become an OFF command"
    );
}
