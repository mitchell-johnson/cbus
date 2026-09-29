//! Real cmqttd process: inbound Access Control (application 213) SAL from the
//! scripted PCI reaches C-Gate event subscribers in the native event layout,
//! malformed frames stay silent, and CLOSE/LOCK and MQTT share the same PCI.

mod util;

use serde_json::json;
use tokio::{
    io::{AsyncBufReadExt, AsyncWriteExt, BufReader},
    net::{tcp::OwnedReadHalf, TcpStream},
};
use util::*;

async fn command(
    reader: &mut BufReader<OwnedReadHalf>,
    writer: &mut tokio::net::tcp::OwnedWriteHalf,
    tag: &str,
    text: &str,
) -> Vec<String> {
    writer
        .write_all(format!("[{tag}] {text}\r\n").as_bytes())
        .await
        .unwrap();
    let prefix = format!("[{tag}] ");
    let mut reply = Vec::new();
    loop {
        let mut line = String::new();
        assert_ne!(
            read_cgate_nontrace_into(reader, &mut line).await.unwrap(),
            0
        );
        let line = line.trim_end_matches(['\r', '\n']).to_string();
        let payload = line
            .strip_prefix(&prefix)
            .unwrap_or_else(|| panic!("expected tag prefix {prefix:?}, got {line:?}"));
        let complete = payload.as_bytes().get(3) == Some(&b' ');
        reply.push(payload.to_string());
        if complete {
            return reply;
        }
    }
}

async fn next_event(reader: &mut BufReader<OwnedReadHalf>) -> String {
    let mut event = String::new();
    tokio::time::timeout(STARTUP, read_cgate_nontrace_into(reader, &mut event))
        .await
        .unwrap()
        .unwrap();
    event.trim_end_matches(['\r', '\n']).to_string()
}

fn checksummed(native_payload: &str) -> String {
    let bytes = hex::decode(native_payload).unwrap();
    hex::encode_upper(cbus_protocol::common::add_cbus_checksum(&bytes))
}

#[tokio::test]
async fn access_control_inbound_events_use_native_text_and_keep_mqtt_live() {
    let state = cbus_test_support::proc::temp_path("cgate-access-control.json");
    let mut sys = start_with(Options {
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
    require(STARTUP, "initial status sweep", || {
        configured_sweep()
            .iter()
            .all(|payload| sys.pci.count_payload(payload) >= 1)
    })
    .await;
    require(STARTUP, "C-Gate listener", || {
        sys.daemon.stderr().contains("C-Gate service listening on ")
    })
    .await;
    let address = sys
        .daemon
        .stderr()
        .lines()
        .find_map(|line| line.split_once("C-Gate service listening on "))
        .map(|(_, address)| address.trim().to_string())
        .unwrap();
    let stream = TcpStream::connect(address).await.unwrap();
    let (reader, mut writer) = stream.into_split();
    let mut reader = BufReader::new(reader);
    let mut greeting = String::new();
    reader.read_line(&mut greeting).await.unwrap();
    assert_eq!(greeting, "201 cmqttd C-Gate service ready\r\n");

    let capabilities = command(&mut reader, &mut writer, "caps", "CMQTT CAPABILITIES").await;
    let capabilities: serde_json::Value =
        serde_json::from_str(capabilities[0].strip_prefix("200-").unwrap()).unwrap();
    assert_eq!(capabilities["access_control_event_fanout"], true);
    assert_eq!(capabilities["access_control_mqtt_state"], false);
    assert_eq!(
        capabilities["access_control_reports"]
            .as_array()
            .unwrap()
            .len(),
        8
    );

    // The outbound commands are unchanged and still confirmed exactly once.
    for (tag, text, native) in [
        ("close", "ACCESSCONTROL CLOSE 254/213 7 9", "05D500020709"),
        ("lock", "ACCESS_CONTROL LOCK 254/213 7 9", "05D5000A0709"),
    ] {
        let payload = checksummed(native);
        let before = sys.pci.count_payload(&payload);
        let reply = command(&mut reader, &mut writer, tag, text).await;
        assert_eq!(reply.last().unwrap(), "200 OK.", "{text}: {reply:?}");
        assert_eq!(sys.pci.count_payload(&payload), before + 1, "{text}");
    }

    assert_eq!(
        command(&mut reader, &mut writer, "events", "EVENT ON")
            .await
            .last()
            .unwrap(),
        "200 OK."
    );

    let mqtt_before = sys.broker.publishes().len();
    // Every opcode C-Gate 3.4 decodes, including the variable-length
    // access requests and a two-message SAL, in native event order.
    let cases: [(&[u8], &[&str]); 7] = [
        (
            &[5, 4, 0xd5, 0, 0x02, 7, 9],
            &["#e# accesscontrol close_access_point //HARNESS/254/213 7 9 sourceUnit=4"],
        ),
        (
            &[5, 4, 0xd5, 0, 0x0a, 7, 9],
            &["#e# accesscontrol lock_access_point //HARNESS/254/213 7 9 sourceUnit=4"],
        ),
        (
            &[5, 5, 0xd5, 0, 0x12, 1, 2],
            &["#e# accesscontrol access_point_left_open //HARNESS/254/213 1 2 sourceUnit=5"],
        ),
        (
            &[5, 5, 0xd5, 0, 0x1a, 1, 2, 0x22, 1, 2],
            &[
                "#e# accesscontrol access_point_forced_open //HARNESS/254/213 1 2 sourceUnit=5",
                "#e# accesscontrol access_point_closed //HARNESS/254/213 1 2 sourceUnit=5",
            ],
        ),
        (
            &[5, 6, 0xd5, 0, 0x32, 0, 254],
            &["#e# accesscontrol exit_request //HARNESS/254/213 0 254 sourceUnit=6"],
        ),
        (
            &[5, 6, 0xd5, 0, 0xa6, 7, 9, 1, 0x12, 0xab, 0x00],
            &["#e# accesscontrol access_request_valid //HARNESS/254/213 7 9 1 12AB00 sourceUnit=6"],
        ),
        (
            &[5, 6, 0xd5, 0, 0xc3, 7, 9, 2],
            &["#e# accesscontrol access_request_invalid //HARNESS/254/213 7 9 2  sourceUnit=6"],
        ),
    ];
    for (body, expected) in cases {
        sys.pci.inject(&pci_wire(body));
        for line in expected {
            assert_eq!(next_event(&mut reader).await, *line, "{body:02X?}");
        }
    }

    // Native range failures, unknown commands and truncation emit nothing;
    // the next valid frame is the next event line.
    for body in [
        &[5, 4, 0xd5, 0, 0x02, 0xff, 9][..],
        &[5, 4, 0xd5, 0, 0xa3, 7, 9, 3],
        &[5, 4, 0xd5, 0, 0x2a, 7, 9],
        &[5, 4, 0xd5, 0, 0xe3, 7, 9, 1],
        &[5, 4, 0xd5, 0, 0xa6, 7, 9, 1],
    ] {
        sys.pci.inject(&pci_wire(body));
    }
    sys.pci.inject(&pci_wire(&[5, 7, 0xd5, 0, 0x22, 3, 4]));
    assert_eq!(
        next_event(&mut reader).await,
        "#e# accesscontrol access_point_closed //HARNESS/254/213 3 4 sourceUnit=7"
    );
    // Access Control observations create no MQTT entity or state.
    tokio::task::yield_now().await;
    assert!(sys.broker.publishes()[mqtt_before..]
        .iter()
        .all(|publish| !publish.topic.contains("access")));
    assert_eq!(
        command(&mut reader, &mut writer, "events-off", "EVENT OFF")
            .await
            .last()
            .unwrap(),
        "200 OK."
    );

    // MQTT remains active in both directions on the shared PCI.
    sys.pci.inject(&pci_wire(&[5, 4, 56, 0, 121, 1]));
    require(STARTUP, "lighting observation reaches MQTT", || {
        sys.broker
            .find_publishes("homeassistant/light/cbus_1/state")
            .iter()
            .any(|publish| {
                parse_json(&publish.payload)
                    == json!({"state":"ON", "brightness":255, "transition":0,
                              "cbus_source_addr":4})
            })
    })
    .await;
    let lighting = "0538000101C1";
    let before = sys.pci.count_payload(lighting);
    sys.broker
        .inject("homeassistant/light/cbus_1/set", br#"{"state":"OFF"}"#);
    require(COMMAND_DRAIN, "MQTT command after Access Control", || {
        sys.pci.count_payload(lighting) == before + 1
    })
    .await;
    assert!(sys.daemon.is_running());
    drop(sys);
    std::fs::remove_file(state).unwrap();
}
