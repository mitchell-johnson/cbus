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
            .contains("300 //HARNESS/254/56/1: level=0")
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
            .contains("300 //HARNESS/254/56/1: level=0"),
        "a PCI confirmation and optimistic MQTT echo must not replace the durable default"
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

/// Direct observations interleaved with a bridged C-Gate command and an MQTT
/// command keep bus order on both interfaces. Each observed group carries the
/// same source unit in its native C-Gate load-change row and its MQTT state;
/// neither confirmed command is reported as an attributed observation.
#[tokio::test]
async fn routed_and_direct_lighting_keep_order_and_source_identity_across_interfaces() {
    let project = cbus_test_support::proc::temp_path("lighting-order-project.xml");
    let state = cbus_test_support::proc::temp_path("lighting-order-cgate.json");
    std::fs::write(
        &project,
        r#"<Installation><Project oid="project-topology"><TagName>TOPO</TagName>
        <Network oid="network-254"><TagName>Local</TagName><Address>254</Address>
          <Interface><InterfaceType>CNI</InterfaceType><InterfaceAddress>127.0.0.1:10001</InterfaceAddress></Interface>
          <Unit oid="pci"><Address>16</Address><UnitType>PC_CNI2</UnitType></Unit>
          <Unit oid="bridge-near"><Address>253</Address><UnitType>BRIDGE2N</UnitType></Unit>
          <Application oid="app"><TagName>Lighting</TagName><Address>56</Address>
            <Group oid="group"><TagName>Local Light</TagName><Address>1</Address></Group>
          </Application>
        </Network>
        <Network oid="network-253"><TagName>Remote</TagName><Address>253</Address>
          <Interface><InterfaceType>Bridge</InterfaceType><InterfaceAddress>254/p/253</InterfaceAddress></Interface>
          <Unit oid="remote"><Address>4</Address><UnitType>KEYE1</UnitType></Unit>
          <Unit oid="bridge-far"><Address>254</Address><UnitType>BRIDGE2N</UnitType></Unit>
          <Application oid="remote-app"><TagName>Remote Lighting</TagName><Address>56</Address>
            <Group oid="remote-group"><TagName>Remote Light</TagName><Address>1</Address></Group>
          </Application>
        </Network></Project></Installation>"#,
    )
    .unwrap();
    let sys = start_with(Options {
        project: false,
        extra: vec![
            "-P".into(),
            project.to_string_lossy().into_owned(),
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
    let address = sys
        .daemon
        .stderr()
        .lines()
        .find_map(|line| {
            line.split_once("C-Gate service listening on ")
                .map(|(_, address)| address.trim().to_string())
        })
        .unwrap();
    let connect = || async {
        let stream = TcpStream::connect(&address).await.unwrap();
        let (reader, writer) = stream.into_split();
        let mut reader = BufReader::new(reader);
        let mut greeting = String::new();
        reader.read_line(&mut greeting).await.unwrap();
        assert!(greeting.starts_with("201 "));
        (reader, writer)
    };
    let (mut events_reader, mut events_writer) = connect().await;
    assert!(
        cgate_command(&mut events_reader, &mut events_writer, "EVENT e7s1c0")
            .await
            .contains("200")
    );
    let (mut reader, mut writer) = connect().await;
    let rows = std::sync::Arc::new(std::sync::Mutex::new(Vec::<String>::new()));
    let collector = tokio::spawn({
        let rows = rows.clone();
        async move {
            let _keep = events_writer;
            loop {
                let mut line = String::new();
                if events_reader.read_line(&mut line).await.unwrap_or(0) == 0 {
                    break;
                }
                rows.lock().unwrap().push(line.trim_end().to_string());
            }
        }
    });
    let lighting_rows = |rows: &std::sync::Mutex<Vec<String>>| {
        rows.lock()
            .unwrap()
            .iter()
            .filter(|row| {
                row.starts_with("#s# lighting ")
                    || row.contains(" 730 ")
                    || row.starts_with("#e# lighting ")
            })
            .cloned()
            .collect::<Vec<_>>()
    };
    let observed = |group: u8, state: &'static str, source: u8| {
        let sys = &sys;
        async move {
            require(STARTUP, "attributed MQTT state", || {
                sys.broker
                    .retained(&format!("homeassistant/light/cbus_{group}/state"))
                    .is_some_and(|payload| {
                        let payload = parse_json(&payload);
                        payload["state"] == state && payload["cbus_source_addr"] == source
                    })
            })
            .await;
        }
    };

    // 1. Direct observation from unit 4.
    sys.pci
        .inject(&pci_wire(&[0x05, 0x04, 0x38, 0x00, 0x79, 0x01]));
    observed(1, "ON", 4).await;
    require(STARTUP, "group 1 load-change row", || {
        lighting_rows(&rows)
            .iter()
            .any(|row| row.starts_with("#s# lighting on //TOPO/254/56/1 "))
    })
    .await;
    let group_one_publishes = sys
        .broker
        .find_publishes("homeassistant/light/cbus_1/state")
        .len();

    // 2. Bridged command; a direct observation from unit 5 arrives while it
    // waits for its PCI confirmation.
    let routed = cgate_command(&mut reader, &mut writer, "ON //TOPO/253/56/1");
    let peer = async {
        require(COMMAND_DRAIN, "routed lighting PPM", || {
            sys.pci.count_payload("03FD0938790145") == 1
        })
        .await;
        sys.pci
            .inject(&pci_wire(&[0x05, 0x05, 0x38, 0x00, 0x01, 0x02]));
    };
    let (routed, ()) = tokio::join!(routed, peer);
    assert!(routed.contains("200 OK"), "{routed:?}");
    observed(2, "OFF", 5).await;

    // 3. MQTT command for group 3, confirmed by the PCI.
    sys.broker
        .inject_qos1("homeassistant/light/cbus_3/set", br#"{"state": "ON"}"#);
    require(COMMAND_DRAIN, "MQTT command confirmation", || {
        sys.broker
            .find_publishes("cmqttd/cbus/command_result")
            .iter()
            .filter_map(|publish| {
                serde_json::from_slice::<serde_json::Value>(&publish.payload).ok()
            })
            .any(|payload| payload["group"] == 3 && payload["delivery"] == "confirmed")
    })
    .await;
    assert_eq!(sys.pci.count_payload("053800790347"), 1);

    // 4. Direct instant ramp from unit 6.
    sys.pci
        .inject(&pci_wire(&[0x05, 0x06, 0x38, 0x00, 0x02, 0x04, 0x80]));
    require(STARTUP, "attributed MQTT ramp", || {
        sys.broker
            .retained("homeassistant/light/cbus_4/state")
            .is_some_and(|payload| {
                let payload = parse_json(&payload);
                payload["brightness"] == 128 && payload["cbus_source_addr"] == 6
            })
    })
    .await;
    require(STARTUP, "group 4 load-change row", || {
        lighting_rows(&rows)
            .iter()
            .any(|row| row.starts_with("#s# lighting ramp //TOPO/254/56/4 "))
    })
    .await;

    let lighting = lighting_rows(&rows);
    let status = lighting
        .iter()
        .filter(|row| row.starts_with("#s# "))
        .cloned()
        .collect::<Vec<_>>();
    // Direct observations in bus order, each with its physical source.
    // Only group 1 is a database Group and so carries an OID.
    assert_eq!(status.len(), 3, "{lighting:?}");
    assert!(status[0].starts_with("#s# lighting on //TOPO/254/56/1  #sourceunit=4 OID="));
    assert!(!status[0].ends_with("OID="), "{status:?}");
    assert_eq!(
        status[1],
        "#s# lighting off //TOPO/254/56/2  #sourceunit=5 OID="
    );
    assert_eq!(
        status[2],
        "#s# lighting ramp //TOPO/254/56/4 128 0 #sourceunit=6 OID="
    );
    for (row, source) in status.iter().zip([4, 5, 6]) {
        let address = row.split(' ').nth(3).unwrap();
        let advice = lighting
            .iter()
            .filter(|line| line.contains(&format!(" 730 {address} ")))
            .collect::<Vec<_>>();
        assert_eq!(advice.len(), 1, "{lighting:?}");
        assert!(advice[0].contains(&format!(" sourceunit={source} ramptime=0")));
    }
    // The bridged command is reported only as cmqttd's command row, between
    // the observations that preceded and followed it; it is not attributed
    // to a source unit and it does not touch the local group-1 MQTT state.
    let position = |needle: &str| lighting.iter().position(|row| row.contains(needle));
    let command_row = position("#e# lighting //TOPO/253/56/1 ON 255").expect("routed command row");
    assert!(position("//TOPO/254/56/1 ").unwrap() < command_row);
    assert!(command_row < position("//TOPO/254/56/4 ").unwrap());
    assert!(!lighting
        .iter()
        .any(|row| row.contains("//TOPO/253/56/1 ") && row.contains("sourceunit")));
    assert_eq!(
        sys.broker
            .find_publishes("homeassistant/light/cbus_1/state")
            .len(),
        group_one_publishes
    );
    // The MQTT command is not a C-Gate observation of group 3.
    assert!(!lighting.iter().any(|row| row.contains("//TOPO/254/56/3")));
    // MQTT publishes follow the same order as the C-Gate rows.
    let first_publish = |group: u8, source: u8| {
        sys.broker
            .find_publishes(&format!("homeassistant/light/cbus_{group}/state"))
            .into_iter()
            .find(|publish| parse_json(&publish.payload)["cbus_source_addr"] == source)
            .unwrap()
            .ts
    };
    assert!(first_publish(1, 4) < first_publish(2, 5));
    assert!(first_publish(2, 5) < first_publish(4, 6));

    collector.abort();
    std::fs::remove_file(project).ok();
    std::fs::remove_file(state).ok();
}

/// A production unit broadcasts unsolicited extended binary status for
/// application 56 every few seconds: block 0 (groups 0..=41 OFF except
/// group 32 ON, 42..=43 missing) and all-missing blocks 0x58 and 0xB0.
const UNSOLICITED_MMI: [&[u8]; 3] = [
    b"86041000F9403800AAAAAAAAAAAAAAAAA9AA0A000000000000000000000048\r\n",
    b"86041000F94038580000000000000000000000000000000000000000009D\r\n",
    b"86041000F74038B00000000000000000000000000000000000000047\r\n",
];

#[tokio::test]
async fn repeated_unsolicited_status_reports_publish_only_changes() {
    let state = cbus_test_support::proc::temp_path("mmi-dedupe-cgate.json");
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
    let address = sys
        .daemon
        .stderr()
        .lines()
        .find_map(|line| {
            line.split_once("C-Gate service listening on ")
                .map(|(_, address)| address.trim().to_string())
        })
        .unwrap();
    let stream = TcpStream::connect(&address).await.unwrap();
    let (reader, mut writer) = stream.into_split();
    let mut reader = BufReader::new(reader);
    let mut greeting = String::new();
    reader.read_line(&mut greeting).await.unwrap();
    assert!(greeting.starts_with("201 "));
    assert!(cgate_command(&mut reader, &mut writer, "EVENT e7s1c0")
        .await
        .contains("200"));
    let rows = std::sync::Arc::new(std::sync::Mutex::new(Vec::<String>::new()));
    let collector = tokio::spawn({
        let rows = rows.clone();
        async move {
            let _keep = writer;
            loop {
                let mut line = String::new();
                if reader.read_line(&mut line).await.unwrap_or(0) == 0 {
                    break;
                }
                rows.lock().unwrap().push(line.trim_end().to_string());
            }
        }
    });
    let level_rows = |group: u8| {
        let row = format!("#e# lighting //HARNESS/254/56/{group} level=");
        rows.lock()
            .unwrap()
            .iter()
            .filter(|line| line.starts_with(&row))
            .cloned()
            .collect::<Vec<_>>()
    };
    let states = |group: u8| {
        sys.broker
            .find_publishes(&format!("homeassistant/light/cbus_{group}/state"))
            .into_iter()
            .map(|publish| parse_json(&publish.payload))
            .collect::<Vec<_>>()
    };
    let sensors = |group: u8| {
        sys.broker
            .find_publishes(&format!("homeassistant/binary_sensor/cbus_{group}/state"))
            .into_iter()
            .map(|publish| String::from_utf8(publish.payload).unwrap())
            .collect::<Vec<_>>()
    };
    // Events reach MQTT and C-Gate in bus order, so an ON for a spare group
    // proves every earlier report was handled by both consumers.
    let barrier = |group: u8| {
        let sys = &sys;
        let rows = rows.clone();
        async move {
            sys.pci
                .inject(&pci_wire(&[0x05, 0x07, 0x38, 0x00, 0x79, group]));
            require(STARTUP, "barrier MQTT state", || !states(group).is_empty()).await;
            let row = format!("#s# lighting on //HARNESS/254/56/{group} ");
            require(STARTUP, "barrier C-Gate row", || {
                rows.lock()
                    .unwrap()
                    .iter()
                    .any(|line| line.starts_with(&row))
            })
            .await;
        }
    };

    // Group 32 is known at brightness 128 before the unit starts reporting.
    sys.pci
        .inject(&pci_wire(&[0x05, 0x05, 0x38, 0x00, 0x02, 32, 0x80]));
    require(STARTUP, "group 32 ramp", || {
        states(32)
            .first()
            .is_some_and(|state| state["brightness"] == 128)
    })
    .await;

    for _ in 0..3 {
        for line in UNSOLICITED_MMI {
            sys.pci.inject(line);
        }
    }
    barrier(200).await;

    let off = serde_json::json!({"state": "OFF", "cbus_source_addr": 0, "brightness": 0});
    for group in (0u8..=41).filter(|&group| group != 32) {
        assert_eq!(states(group), std::slice::from_ref(&off), "group {group}");
        assert_eq!(sensors(group), ["OFF"], "group {group}");
        assert_eq!(
            level_rows(group),
            [format!("#e# lighting //HARNESS/254/56/{group} level=0")],
            "group {group}"
        );
    }
    // A brightness-less binary ON leaves the known level alone.
    assert_eq!(states(32).len(), 1, "{:?}", states(32));
    assert_eq!(
        parse_json(
            &sys.broker
                .retained("homeassistant/light/cbus_32/state")
                .unwrap()
        )["brightness"],
        128
    );
    assert_eq!(sensors(32), ["ON"]);
    assert!(level_rows(32).is_empty());
    for group in (42u8..=199).chain(201..=255) {
        assert!(states(group).is_empty(), "missing group {group}");
    }

    // A genuine change in the same broadcast publishes once: group 32 turns
    // OFF and group 40 turns ON with an unknown level.
    let changed = pci_wire(&[
        0x86, 0x04, 0x10, 0x00, 0xf9, 0x40, 0x38, 0x00, 0xaa, 0xaa, 0xaa, 0xaa, 0xaa, 0xaa, 0xaa,
        0xaa, 0xaa, 0xaa, 0x09, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    ]);
    for _ in 0..3 {
        sys.pci.inject(&changed);
        sys.pci.inject(UNSOLICITED_MMI[1]);
        sys.pci.inject(UNSOLICITED_MMI[2]);
    }
    barrier(201).await;
    assert_eq!(states(32).len(), 2, "{:?}", states(32));
    assert_eq!(states(32)[1], off);
    assert_eq!(sensors(32), ["ON", "OFF"]);
    assert_eq!(level_rows(32), ["#e# lighting //HARNESS/254/56/32 level=0"]);
    assert_eq!(
        states(40),
        [
            off.clone(),
            serde_json::json!({"state": "ON", "cbus_source_addr": 0})
        ]
    );
    assert_eq!(sensors(40), ["OFF", "ON"]);
    assert_eq!(level_rows(40).len(), 1);
    for group in (0u8..=39).filter(|&group| group != 32) {
        assert_eq!(states(group).len(), 1, "group {group}");
        assert_eq!(level_rows(group).len(), 1, "group {group}");
    }

    collector.abort();
    std::fs::remove_file(state).ok();
}
