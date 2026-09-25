//! Cross-interface lighting consistency: MQTT delivery is confirmation-gated,
//! then physical level readback refreshes the embedded C-Gate cache.

mod util;

use tokio::{
    io::{AsyncBufReadExt, AsyncWriteExt, BufReader},
    net::TcpStream,
};
use util::*;

async fn cgate_command(
    reader: &mut BufReader<tokio::net::tcp::OwnedReadHalf>,
    writer: &mut tokio::net::tcp::OwnedWriteHalf,
    text: &str,
) -> String {
    writer
        .write_all(format!("[1] {text}\r\n").as_bytes())
        .await
        .unwrap();
    let mut result = String::new();
    loop {
        let mut line = String::new();
        assert_ne!(reader.read_line(&mut line).await.unwrap(), 0);
        result.push_str(&line);
        if line.starts_with("[1]") && line.as_bytes().get(7) == Some(&b' ') {
            return result;
        }
    }
}

#[tokio::test]
async fn confirmed_mqtt_command_requests_physical_level_without_manufacturing_cgate_state() {
    let state = cbus_test_support::proc::temp_path("mqtt-readback-cgate.json");
    let sys = start_with(Options {
        extra: vec![
            "--cgate-bind".into(),
            "127.0.0.1:0".into(),
            "--cgate-state".into(),
            state.to_string_lossy().into_owned(),
        ],
        ..Default::default()
    })
    .await;
    wait_started(&sys).await;
    require(STARTUP, "C-Gate listener", || {
        sys.daemon.stderr().contains("C-Gate service listening on ")
    })
    .await;
    require(STARTUP, "startup status sweep", || {
        configured_sweep()
            .iter()
            .all(|payload| sys.pci.count_payload(payload) >= 1)
    })
    .await;
    let readbacks_before = sys.pci.count_payload("05FF00730738004A");

    let logs = sys.daemon.stderr();
    let address = logs
        .lines()
        .find_map(|line| {
            line.split_once("C-Gate service listening on ")
                .map(|(_, address)| address.trim())
        })
        .unwrap();
    let stream = TcpStream::connect(address).await.unwrap();
    let (reader, mut writer) = stream.into_split();
    let mut reader = BufReader::new(reader);
    let mut greeting = String::new();
    reader.read_line(&mut greeting).await.unwrap();
    assert!(greeting.starts_with("201 "));
    assert!(
        cgate_command(&mut reader, &mut writer, "GET //HARNESS/254/56/1 level")
            .await
            .contains("408 No live level")
    );

    sys.broker
        .inject_qos1("homeassistant/light/cbus_1/set", br#"{"state": "ON"}"#);
    require(STARTUP, "MQTT command confirmation", || {
        sys.broker
            .find_publishes("cmqttd/cbus/command_result")
            .iter()
            .filter_map(|publish| {
                serde_json::from_slice::<serde_json::Value>(&publish.payload).ok()
            })
            .any(|payload| {
                payload["group"] == 1
                    && payload["delivery"] == "confirmed"
                    && payload["readback"] == "queued"
            })
    })
    .await;
    assert_eq!(sys.pci.count_payload("053800790149"), 1);
    require(STARTUP, "physical level readback request", || {
        sys.pci.count_payload("05FF00730738004A") > readbacks_before
    })
    .await;
    require(STARTUP, "requested-state compatibility echo", || {
        sys.broker
            .retained("homeassistant/light/cbus_1/state")
            .is_some_and(|payload| {
                let payload = parse_json(&payload);
                payload["state"] == "ON" && payload["cbus_source_addr"].is_null()
            })
    })
    .await;
    assert!(
        cgate_command(&mut reader, &mut writer, "GET //HARNESS/254/56/1 level")
            .await
            .contains("408 No live level"),
        "a PCI confirmation and optimistic MQTT echo are not physical level evidence"
    );

    // Exact retained level-report fixture: group 0 absent, group 1 = 255,
    // group 2 = 0, group 3 = 128. Only this observation populates C-Gate.
    sys.pci.inject(b"06991000EB07380000005555AAAAAA6A15\r\n");
    let deadline = tokio::time::Instant::now() + STARTUP;
    loop {
        let response =
            cgate_command(&mut reader, &mut writer, "GET //HARNESS/254/56/1 level").await;
        if response.contains("level=255") {
            break;
        }
        assert!(
            tokio::time::Instant::now() < deadline,
            "level report never reached C-Gate: {response:?}"
        );
        tokio::time::sleep(std::time::Duration::from_millis(20)).await;
    }
    require(
        STARTUP,
        "physical report replaces compatibility echo",
        || {
            sys.broker
                .retained("homeassistant/light/cbus_1/state")
                .is_some_and(|payload| {
                    let payload = parse_json(&payload);
                    payload["state"] == "ON"
                        && payload["brightness"] == 255
                        && payload["cbus_source_addr"] == 0
                })
        },
    )
    .await;

    std::fs::remove_file(state).ok();
}

#[tokio::test]
async fn physical_event_before_confirmation_is_not_overwritten_by_command_echo() {
    let sys = start_default().await;
    wait_started(&sys).await;
    sys.pci
        .set_conf_delay(std::time::Duration::from_millis(500));

    sys.broker
        .inject("homeassistant/light/cbus_10/set", br#"{"state":"ON"}"#);
    require(STARTUP, "outbound command", || {
        sys.pci.count_payload("053800790A40") == 1
    })
    .await;

    // A real source-bearing OFF arrives while the ON command is awaiting its
    // PCI confirmation. It is newer physical evidence for this exact group.
    sys.pci
        .inject(&pci_wire(&[0x05, 0x05, 0x38, 0x00, 0x01, 0x0a]));
    require(STARTUP, "physical event before confirmation", || {
        sys.broker
            .retained("homeassistant/light/cbus_10/state")
            .is_some_and(|payload| {
                let payload = parse_json(&payload);
                payload["state"] == "OFF" && payload["cbus_source_addr"] == 5
            })
    })
    .await;
    require(STARTUP, "confirmed command receipt", || {
        sys.broker
            .find_publishes("cmqttd/cbus/command_result")
            .iter()
            .filter_map(|publish| {
                serde_json::from_slice::<serde_json::Value>(&publish.payload).ok()
            })
            .any(|payload| payload["group"] == 10 && payload["delivery"] == "confirmed")
    })
    .await;

    let retained = sys
        .broker
        .retained("homeassistant/light/cbus_10/state")
        .expect("physical state must remain retained");
    let retained = parse_json(&retained);
    assert_eq!(retained["state"], "OFF");
    assert_eq!(retained["cbus_source_addr"], 5);
    assert!(
        sys.broker
            .find_publishes("homeassistant/light/cbus_10/state")
            .iter()
            .all(|publish| !parse_json(&publish.payload)["cbus_source_addr"].is_null()),
        "the older requested-state echo must be suppressed"
    );
}

#[tokio::test]
async fn unrelated_physical_event_does_not_suppress_command_echo() {
    let sys = start_default().await;
    wait_started(&sys).await;
    sys.pci
        .set_conf_delay(std::time::Duration::from_millis(500));

    sys.broker
        .inject("homeassistant/light/cbus_10/set", br#"{"state":"ON"}"#);
    require(STARTUP, "outbound command", || {
        sys.pci.count_payload("053800790A40") == 1
    })
    .await;

    // An observation for group 11 must not affect group 10's echo decision.
    sys.pci
        .inject(&pci_wire(&[0x05, 0x05, 0x38, 0x00, 0x01, 0x0b]));
    require(STARTUP, "unrelated physical event", || {
        sys.broker
            .retained("homeassistant/light/cbus_11/state")
            .is_some_and(|payload| parse_json(&payload)["cbus_source_addr"] == 5)
    })
    .await;
    require(STARTUP, "same-group compatibility echo", || {
        sys.broker
            .retained("homeassistant/light/cbus_10/state")
            .is_some_and(|payload| {
                let payload = parse_json(&payload);
                payload["state"] == "ON" && payload["cbus_source_addr"].is_null()
            })
    })
    .await;
    let unrelated = sys
        .broker
        .retained("homeassistant/light/cbus_11/state")
        .expect("unrelated physical state must remain retained");
    assert_eq!(parse_json(&unrelated)["cbus_source_addr"], 5);
}
