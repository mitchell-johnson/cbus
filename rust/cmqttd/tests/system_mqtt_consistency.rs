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

    std::fs::remove_file(state).ok();
}
