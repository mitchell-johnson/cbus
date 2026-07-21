//! Full-system C-Bus-event-to-MQTT tests: lighting SALs, level reports,
//! clock requests and malformed-input resilience, using the committed
//! behavioral expectations for the exact wire bytes and payloads.

mod util;

use serde_json::json;
use std::time::Duration;
use util::*;

fn wire_from_fixture(key: &str) -> Vec<u8> {
    expectations()[key]["wire"]
        .as_str()
        .unwrap()
        .chars()
        .map(|c| c as u8)
        .collect()
}

#[tokio::test]
async fn lighting_on_event_publishes_exact_state_json() {
    let sys = start_default().await;
    wait_started(&sys).await;
    let fix = &expectations()["inject_lighting_on"];
    sys.pci.inject(&wire_from_fixture("inject_lighting_on"));
    let topic = fix["state_topic"].as_str().unwrap();
    require(STARTUP, "state publish", || {
        !sys.broker.find_publishes(topic).is_empty()
    })
    .await;
    let rec = &sys.broker.find_publishes(topic)[0];
    assert_eq!(parse_json(&rec.payload), fix["state_payload"]);
    assert_eq!((rec.qos, rec.retain), (1, true));
}

#[tokio::test]
async fn lighting_on_event_publishes_binary_sensor_on() {
    let sys = start_default().await;
    wait_started(&sys).await;
    let fix = &expectations()["inject_lighting_on"];
    sys.pci.inject(&wire_from_fixture("inject_lighting_on"));
    let topic = fix["sensor_topic"].as_str().unwrap();
    require(STARTUP, "sensor publish", || {
        !sys.broker.find_publishes(topic).is_empty()
    })
    .await;
    let rec = &sys.broker.find_publishes(topic)[0];
    assert_eq!(
        rec.payload,
        fix["sensor_payload"].as_str().unwrap().as_bytes()
    );
    assert_eq!((rec.qos, rec.retain), (1, true));
}

#[tokio::test]
async fn lighting_ramp_event_publishes_brightness_and_transition() {
    let sys = start_default().await;
    wait_started(&sys).await;
    let fix = &expectations()["inject_lighting_ramp"];
    sys.pci.inject(&wire_from_fixture("inject_lighting_ramp"));
    let topic = fix["state_topic"].as_str().unwrap();
    require(STARTUP, "ramp state publish", || {
        !sys.broker.find_publishes(topic).is_empty()
    })
    .await;
    assert_eq!(
        parse_json(&sys.broker.find_publishes(topic)[0].payload),
        fix["state_payload"]
    );
    assert_eq!(
        sys.broker
            .find_publishes(fix["sensor_topic"].as_str().unwrap())[0]
            .payload,
        b"ON"
    );
}

#[tokio::test]
async fn lighting_off_event_publishes_off_state() {
    let sys = start_default().await;
    wait_started(&sys).await;
    // off for group 10, source 5
    sys.pci
        .inject(&pci_wire(&[0x05, 0x05, 0x38, 0x00, 0x01, 0x0a]));
    let topic = "homeassistant/light/cbus_10/state";
    require(STARTUP, "off state publish", || {
        !sys.broker.find_publishes(topic).is_empty()
    })
    .await;
    assert_eq!(
        parse_json(&sys.broker.find_publishes(topic)[0].payload),
        json!({"state": "OFF", "brightness": 0, "transition": 0,
               "cbus_source_addr": 5})
    );
    assert_eq!(
        sys.broker
            .find_publishes("homeassistant/binary_sensor/cbus_10/state")[0]
            .payload,
        b"OFF"
    );
}

#[tokio::test]
async fn ramp_to_level_zero_state_on_sensor_off() {
    let sys = start_default().await;
    wait_started(&sys).await;
    // 12 s ramp (code 0x1A) of group 11 to level 0, source 7
    sys.pci
        .inject(&pci_wire(&[0x05, 0x07, 0x38, 0x00, 0x1a, 0x0b, 0x00]));
    let topic = "homeassistant/light/cbus_11/state";
    require(STARTUP, "ramp-to-zero state", || {
        !sys.broker.find_publishes(topic).is_empty()
    })
    .await;
    // Python parity quirk: the light state stays "ON" with brightness 0,
    // only the binary sensor reports OFF
    assert_eq!(
        parse_json(&sys.broker.find_publishes(topic)[0].payload),
        json!({"state": "ON", "brightness": 0, "transition": 12,
               "cbus_source_addr": 7})
    );
    assert_eq!(
        sys.broker
            .find_publishes("homeassistant/binary_sensor/cbus_11/state")[0]
            .payload,
        b"OFF"
    );
}

#[tokio::test]
async fn multi_sal_event_publishes_every_group() {
    let sys = start_default().await;
    wait_started(&sys).await;
    sys.pci
        .inject(&pci_wire(&[0x05, 0x05, 0x38, 0x00, 0x79, 0x01, 0x79, 0x0a]));
    for topic in [
        "homeassistant/light/cbus_1/state",
        "homeassistant/light/cbus_10/state",
    ] {
        require(STARTUP, topic, || {
            !sys.broker.find_publishes(topic).is_empty()
        })
        .await;
    }
}

#[tokio::test]
async fn alt_lighting_app_event_uses_padded_topic() {
    let sys = start_default().await;
    wait_started(&sys).await;
    // app 0x30 (48), group 11, source 5
    sys.pci
        .inject(&pci_wire(&[0x05, 0x05, 0x30, 0x00, 0x79, 0x0b]));
    let topic = "homeassistant/light/cbus_048_011/state";
    require(STARTUP, "alt-app state publish", || {
        !sys.broker.find_publishes(topic).is_empty()
    })
    .await;
    assert_eq!(
        parse_json(&sys.broker.find_publishes(topic)[0].payload),
        json!({"state": "ON", "brightness": 255, "transition": 0,
               "cbus_source_addr": 5})
    );
}

#[tokio::test]
async fn level_report_publishes_per_group_states_exactly() {
    let sys = start_default().await;
    wait_started(&sys).await;
    let fix = &expectations()["inject_level_report"];
    sys.pci.inject(&wire_from_fixture("inject_level_report"));
    for expect in fix["expect_states"].as_array().unwrap() {
        let topic = expect["topic"].as_str().unwrap();
        require(STARTUP, topic, || {
            !sys.broker.find_publishes(topic).is_empty()
        })
        .await;
        assert_eq!(
            parse_json(&sys.broker.find_publishes(topic)[0].payload),
            expect["payload"],
            "{topic}"
        );
    }
}

#[tokio::test]
async fn level_report_null_slot_skipped_but_advances_group() {
    let sys = start_default().await;
    wait_started(&sys).await;
    sys.pci.inject(&wire_from_fixture("inject_level_report"));
    // the report's first (null) slot belongs to group 0: groups 1..3 get
    // states, group 0 must not
    require(STARTUP, "level report states", || {
        !sys.broker
            .find_publishes("homeassistant/light/cbus_3/state")
            .is_empty()
    })
    .await;
    assert!(sys
        .broker
        .find_publishes("homeassistant/light/cbus_0/state")
        .is_empty());
}

#[tokio::test]
async fn clock_request_answered_with_date_time_frame() {
    let sys = start_default().await;
    wait_started(&sys).await;
    sys.pci.inject(&wire_from_fixture("inject_clock_request"));
    require(STARTUP, "clock update frame", || {
        sys.pci.payloads().iter().any(|p| p.starts_with("05DF00"))
    })
    .await;
    let payloads = sys.pci.payloads();
    let clock = payloads.iter().find(|p| p.starts_with("05DF00")).unwrap();
    let bytes = hex::decode(clock).expect("hex payload");
    // PM to app 0xDF: date SAL (0E 02 yy yy mm dd wd) then time SAL
    // (0D 01 hh mm ss FF) then checksum — 17 bytes total
    assert_eq!(bytes.len(), 17, "{clock}");
    assert_eq!(&bytes[..3], &[0x05, 0xdf, 0x00]);
    assert_eq!(&bytes[3..5], &[0x0e, 0x02], "date SAL header");
    assert_eq!(&bytes[10..12], &[0x0d, 0x01], "time SAL header");
    assert_eq!(bytes[15], 0xff, "DST byte must be 0xFF");
    assert!(cbus_protocol::common::validate_cbus_checksum(&bytes));
}

#[tokio::test]
async fn no_clock_flag_suppresses_clock_answer() {
    let sys = start_with(Options {
        extra: vec!["-C".into()],
        ..Default::default()
    })
    .await;
    wait_started(&sys).await;
    sys.pci.inject(&wire_from_fixture("inject_clock_request"));
    // positive control proving the event pipeline still runs
    sys.pci
        .inject(&pci_wire(&[0x05, 0x05, 0x38, 0x00, 0x79, 0x01]));
    require(STARTUP, "control state publish", || {
        !sys.broker
            .find_publishes("homeassistant/light/cbus_1/state")
            .is_empty()
    })
    .await;
    assert!(
        !sys.pci.payloads().iter().any(|p| p.starts_with("05DF00")),
        "-C must suppress the clock reply"
    );
}

#[tokio::test]
async fn terminate_ramp_event_publishes_nothing() {
    let sys = start_default().await;
    wait_started(&sys).await;
    // terminate ramp for group 4 is not relayed to MQTT (like Python)
    sys.pci
        .inject(&pci_wire(&[0x05, 0x05, 0x38, 0x00, 0x09, 0x04]));
    // positive control on another group
    sys.pci
        .inject(&pci_wire(&[0x05, 0x05, 0x38, 0x00, 0x79, 0x01]));
    require(STARTUP, "control state publish", || {
        !sys.broker
            .find_publishes("homeassistant/light/cbus_1/state")
            .is_empty()
    })
    .await;
    assert!(sys
        .broker
        .find_publishes("homeassistant/light/cbus_4/state")
        .is_empty());
}

#[tokio::test]
async fn garbage_from_pci_does_not_kill_daemon() {
    let mut sys = start_default().await;
    wait_started(&sys).await;
    sys.pci.inject(b"ZZZZ\r\n@#$%^&*\r\nnot-a-frame\r\n");
    sys.pci
        .inject(&pci_wire(&[0x05, 0x05, 0x38, 0x00, 0x79, 0x01]));
    require(STARTUP, "state publish after garbage", || {
        !sys.broker
            .find_publishes("homeassistant/light/cbus_1/state")
            .is_empty()
    })
    .await;
    assert!(sys.daemon.is_running());
}

#[tokio::test]
async fn oversized_pci_line_dropped_and_recovers() {
    let sys = start_default().await;
    wait_started(&sys).await;
    // >256 bytes without a terminator: the client's buffer cap drops it
    let mut junk = vec![b'0'; 300];
    junk.extend_from_slice(b"\r\n");
    sys.pci.inject(&junk);
    tokio::time::sleep(Duration::from_millis(200)).await;
    sys.pci
        .inject(&pci_wire(&[0x05, 0x05, 0x38, 0x00, 0x79, 0x0a]));
    require(STARTUP, "state publish after oversized line", || {
        !sys.broker
            .find_publishes("homeassistant/light/cbus_10/state")
            .is_empty()
    })
    .await;
}

#[tokio::test]
async fn power_on_and_pci_error_tokens_tolerated() {
    let sys = start_default().await;
    wait_started(&sys).await;
    sys.pci.inject(b"++\r\n");
    sys.pci.inject(b"!");
    sys.pci
        .inject(&pci_wire(&[0x05, 0x05, 0x38, 0x00, 0x79, 0x01]));
    require(STARTUP, "state publish after specials", || {
        !sys.broker
            .find_publishes("homeassistant/light/cbus_1/state")
            .is_empty()
    })
    .await;
}

#[tokio::test]
async fn spurious_confirmation_tolerated() {
    let sys = start_default().await;
    wait_started(&sys).await;
    // 'q' was never allocated by the client; must be ignored gracefully
    sys.pci.inject(b"q.");
    sys.pci
        .inject(&pci_wire(&[0x05, 0x05, 0x38, 0x00, 0x79, 0x01]));
    require(STARTUP, "state publish after spurious conf", || {
        !sys.broker
            .find_publishes("homeassistant/light/cbus_1/state")
            .is_empty()
    })
    .await;
}

#[tokio::test]
async fn binary_status_report_is_ignored() {
    let sys = start_default().await;
    wait_started(&sys).await;
    // an extended status BINARY report (coding 0x00) is not relayed
    sys.pci.inject(&pci_wire(&[
        0x06,
        0x99,
        0x10,
        0x00,
        0xe4,
        0x00,
        0x38,
        0x00,
        0b01_01_01_01,
    ]));
    // control event
    sys.pci
        .inject(&pci_wire(&[0x05, 0x05, 0x38, 0x00, 0x79, 0x0a]));
    require(STARTUP, "control state publish", || {
        !sys.broker
            .find_publishes("homeassistant/light/cbus_10/state")
            .is_empty()
    })
    .await;
    // groups 0..3 of the binary report must have produced no state
    for ga in [0u8, 1, 2, 3] {
        assert!(
            sys.broker
                .find_publishes(&format!("homeassistant/light/cbus_{ga}/state"))
                .is_empty(),
            "binary report leaked a state for group {ga}"
        );
    }
}
