//! Real daemon: C-Gate and MQTT share one PCI and observe the same bus reports.
mod util;
use tokio::{
    io::{AsyncBufReadExt, AsyncWriteExt, BufReader},
    net::TcpStream,
};
use util::*;

fn serial_identity(serial: &str, address: u8) -> Vec<u8> {
    let packed = cbus_protocol::serial_address::parse_native_serial(serial)
        .unwrap()
        .packed;
    let mut data = vec![0x38, 0xff, 0xff, 0xff, 0xff];
    data.extend_from_slice(&packed);
    data.extend_from_slice(&[0xa2, 0, address]);
    data
}

fn installation_mmi_block(start: u8, count: usize, present: &[usize]) -> Vec<u8> {
    installation_mmi_block_with_state(start, count, present, 1)
}

fn installation_mmi_block_with_state(
    start: u8,
    count: usize,
    present: &[usize],
    state: u8,
) -> Vec<u8> {
    assert!((1..=3).contains(&state));
    let mut states = vec![0u8; count];
    for address in present {
        states[*address - usize::from(start)] = state;
    }
    let mut wire = cbus_protocol::packet::Packet::StandardStatus {
        application: 0xff,
        block_start: start,
        states,
    }
    .encode_packet()
    .unwrap();
    wire.extend_from_slice(b"\r\n");
    wire
}

fn routed_installation_mmi_block(
    bridges: &[u8],
    start: u8,
    count: usize,
    present: &[usize],
) -> Vec<u8> {
    let mut states = vec![0u8; count];
    for address in present {
        if (usize::from(start)..usize::from(start) + count).contains(address) {
            states[*address - usize::from(start)] = 1;
        }
    }
    let direct = cbus_protocol::Packet::PointToPoint {
        meta: cbus_protocol::Meta {
            checksum: true,
            priority_class: 2,
            source_address: Some(4),
            confirmation: None,
        },
        unit_address: 16,
        bridged: false,
        hops: vec![],
        cals: vec![cbus_protocol::Cal::ExtendedStatus {
            externally_initiated: false,
            child_application: 0xff,
            block_start: start,
            report: cbus_protocol::report::StatusReport::Binary(states),
        }],
    }
    .encode()
    .unwrap();
    let mut routed = vec![direct[0], bridges[0], 0x10, bridges.len() as u8];
    routed.extend_from_slice(&bridges[1..]);
    routed.push(4);
    routed.extend_from_slice(&direct[4..direct.len() - 1]);
    pci_wire(&routed)
}

#[tokio::test]
async fn bridged_pingu_keeps_mqtt_live_and_plain_tcp_fault_is_clean() {
    let project = cbus_test_support::proc::temp_path("bridged-project.xml");
    let state = cbus_test_support::proc::temp_path("bridged-cgate.json");
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
    let mut sys = start_with(Options {
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
    require(STARTUP, "bridged C-Gate listener", || {
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
    let stream = TcpStream::connect(address).await.unwrap();
    let (reader, mut writer) = stream.into_split();
    let mut reader = BufReader::new(reader);
    let mut greeting = String::new();
    reader.read_line(&mut greeting).await.unwrap();

    async fn command(
        reader: &mut BufReader<tokio::net::tcp::OwnedReadHalf>,
        writer: &mut tokio::net::tcp::OwnedWriteHalf,
        text: &str,
    ) -> String {
        writer
            .write_all(format!("[9] {text}\r\n").as_bytes())
            .await
            .unwrap();
        let mut result = String::new();
        loop {
            let mut line = String::new();
            reader.read_line(&mut line).await.unwrap();
            result.push_str(&line);
            if line.starts_with("[9]") && line.as_bytes().get(7) == Some(&b' ') {
                return result;
            }
        }
    }

    let path = command(&mut reader, &mut writer, "DBNETWORKPATH 254 253 COMPACT").await;
    assert!(path.contains("136 FD"), "{path:?}");
    let capabilities = command(&mut reader, &mut writer, "CMQTT CAPABILITIES").await;
    assert!(capabilities.contains("\"bridged_read_only_discovery\":true"));
    assert!(capabilities.contains("\"bridged_network_max_hops\":6"));

    let pingu = command(&mut reader, &mut writer, "NET PINGU //TOPO/253");
    let peer = async {
        require(STARTUP, "native routed installation MMI", || {
            sys.pci.count_payload("03FD09FFFAFF00FF") == 1
        })
        .await;
        // Direct-network MQTT traffic remains live during the untagged remote
        // MMI observation on the same physical connection.
        sys.pci.inject(&pci_wire(&[5, 4, 56, 0, 121, 1]));
        require(STARTUP, "MQTT state during routed MMI", || {
            sys.broker
                .publishes()
                .iter()
                .any(|publish| publish.topic == "homeassistant/light/cbus_1/state")
        })
        .await;
        // A complete-looking first block from another route must be ignored.
        sys.pci
            .inject(&routed_installation_mmi_block(&[252], 0, 88, &[7]));
        for (start, count) in [(0, 88), (88, 88), (176, 80)] {
            sys.pci
                .inject(&routed_installation_mmi_block(&[253], start, count, &[4]));
        }
    };
    let (pingu, ()) = tokio::join!(pingu, peer);
    assert!(pingu.contains("302-Units=4"), "{pingu:?}");
    assert_eq!(sys.pci.connections(), 1);

    let before = sys.pci.frames().len();
    let mutation = command(&mut reader, &mut writer, "ON //TOPO/253/56/1").await;
    assert!(
        mutation.contains("404 Network is not connected"),
        "{mutation:?}"
    );
    let after = sys.pci.frames().len();
    assert_eq!(after, before, "remote mutation must fail before PCI I/O");

    sys.pci.kick();
    let status = sys
        .daemon
        .wait_exit(STARTUP)
        .await
        .expect("plain TCP cmqttd must terminate after losing its one PCI");
    assert!(
        status.success(),
        "clean transport-loss shutdown: {status:?}"
    );
    assert_eq!(sys.pci.connections(), 1);

    drop(sys);
    std::fs::remove_file(project).unwrap();
    std::fs::remove_file(state).unwrap();
}

#[tokio::test]
async fn cgate_mqtt_share_one_connection_and_unknown_levels_are_not_zero() {
    let path = cbus_test_support::proc::temp_path("cgate.json");
    let sys = start_with(Options {
        extra: vec![
            "--cgate-bind".into(),
            "127.0.0.1:0".into(),
            "--cgate-state".into(),
            path.to_string_lossy().into_owned(),
        ],
        ..Default::default()
    })
    .await;
    require(STARTUP, "C-Gate listener", || {
        sys.daemon.stderr().contains("C-Gate service listening on ")
    })
    .await;
    let logs = sys.daemon.stderr();
    let addr = logs
        .lines()
        .find_map(|line| {
            line.split_once("C-Gate service listening on ")
                .map(|(_, addr)| addr.trim())
        })
        .unwrap();
    let stream = TcpStream::connect(addr).await.unwrap();
    let (reader, mut writer) = stream.into_split();
    let mut reader = BufReader::new(reader);
    let mut line = String::new();
    reader.read_line(&mut line).await.unwrap();
    assert!(line.starts_with("201 "));
    async fn command(
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
            reader.read_line(&mut line).await.unwrap();
            result.push_str(&line);
            if line.starts_with("[1]") && line.as_bytes().get(7) == Some(&b' ') {
                return result;
            }
        }
    }
    async fn command_until(
        reader: &mut BufReader<tokio::net::tcp::OwnedReadHalf>,
        writer: &mut tokio::net::tcp::OwnedWriteHalf,
        text: &str,
        expected: &str,
    ) -> String {
        let deadline = tokio::time::Instant::now() + STARTUP;
        loop {
            let response = command(reader, writer, text).await;
            if response.contains(expected) {
                return response;
            }
            assert!(
                tokio::time::Instant::now() < deadline,
                "{text} never contained {expected:?}: {response:?}"
            );
            tokio::time::sleep(std::time::Duration::from_millis(10)).await;
        }
    }
    async fn answer_identify(
        sys: &System,
        unit: u8,
        attribute: u8,
        occurrence: usize,
        replies: &[&[u8]],
    ) {
        let prefix = format!("46{unit:02X}0021{attribute:02X}");
        require(COMMAND_DRAIN, "IDENTIFY request", || {
            sys.pci
                .frames()
                .iter()
                .filter(|frame| frame.payload.starts_with(&prefix))
                .count()
                >= occurrence
        })
        .await;
        for data in replies {
            let mut body = vec![
                0x86,
                unit,
                0x10,
                0x01,
                0x00,
                0x80 | (data.len() as u8 + 1),
                attribute,
            ];
            body.extend_from_slice(data);
            sys.pci.inject(&pci_wire(&body));
        }
    }
    async fn answer_kfi_write(sys: &System, payload: &str, occurrence: usize) {
        require(COMMAND_DRAIN, "KFI parameter-FF write", || {
            sys.pci.count_payload(payload) >= occurrence
        })
        .await;
        sys.pci
            .inject(&pci_wire(&[0x86, 5, 0x10, 0x01, 0x00, 0x32, 0xff, 0]));
    }
    let capabilities = command(&mut reader, &mut writer, "CMQTT CAPABILITIES").await;
    assert!(capabilities.contains("\"do_methods\":[\"factorydefault\",\"lighting\",\"sync\"]"));
    assert!(capabilities.contains("\"full_cgate_compatibility\":false"));
    assert!(capabilities.contains("\"dynamic_label_device_readback\":false"));
    assert!(capabilities.contains("\"label_clear\":true"));
    assert!(capabilities.contains("\"label_kfi\":true"));
    assert!(capabilities.contains("\"edlt_widget_groups\":true"));
    assert!(capabilities.contains("\"edlt_extended_firmware\":true"));
    assert!(capabilities.contains("\"edlt_applications\":true"));
    assert!(
        command(&mut reader, &mut writer, "GET //HARNESS/254/56/1 level")
            .await
            .contains("408 No live level")
    );
    assert!(command(&mut reader, &mut writer, "ON //HARNESS/254/56/1")
        .await
        .contains("200 OK"));
    assert_eq!(sys.pci.count_payload("053800790149"), 1);
    for (method, payload) in [
        ("OFF", "0538000101C1"),
        ("ON", "053800790149"),
        ("RAMP 64 0", "05380002014080"),
        ("TERMINATERAMP", "0538000901B9"),
    ] {
        let response = command(
            &mut reader,
            &mut writer,
            &format!("DO //HARNESS/254/56/1 {method}"),
        )
        .await;
        assert!(
            response.contains("202 Done: //HARNESS/254/56/1"),
            "{method}: {response:?}"
        );
        assert!(sys.pci.count_payload(payload) >= 1, "{method}: {payload}");
    }
    // Successful delivery does not manufacture an observed brightness.
    assert!(
        command(&mut reader, &mut writer, "GET //HARNESS/254/56/1 level")
            .await
            .contains("408 No live level")
    );
    sys.pci.inject(&pci_wire(&[5, 4, 56, 0, 121, 1]));
    require(STARTUP, "bus state in MQTT", || {
        sys.broker
            .publishes()
            .iter()
            .any(|p| p.topic == "homeassistant/light/cbus_1/state")
    })
    .await;
    assert!(
        command(&mut reader, &mut writer, "GET //HARNESS/254/56/1 level")
            .await
            .contains("level=255")
    );
    assert!(command(&mut reader, &mut writer, "SCENE PLAY house absent")
        .await
        .contains("401 Scene not found"));
    assert!(
        command(&mut reader, &mut writer, "SCENE RECORD house evening")
            .await
            .contains("200 OK")
    );
    assert!(String::from_utf8(std::fs::read(&path).unwrap())
        .unwrap()
        .contains("house/evening"));
    assert!(
        command(&mut reader, &mut writer, "RAMP //HARNESS/254/56/1 128 4")
            .await
            .contains("200 OK")
    );
    assert!(
        command(&mut reader, &mut writer, "GET //HARNESS/254/56/1 level")
            .await
            .contains("408 No live level")
    );
    assert!(
        command(&mut reader, &mut writer, "SCENE PLAY house evening")
            .await
            .contains("200 OK")
    );
    assert_eq!(sys.pci.count_payload("0538000201FFC1"), 1);
    // Command confirmation is not a physical level report.
    assert!(
        command(&mut reader, &mut writer, "GET //HARNESS/254/56/1 level")
            .await
            .contains("408 No live level")
    );
    assert!(
        command(&mut reader, &mut writer, "TERMINATERAMP //HARNESS/254/56/2")
            .await
            .contains("200 OK")
    );
    assert_eq!(sys.pci.count_payload("0538000902B8"), 1);
    assert!(command(
        &mut reader,
        &mut writer,
        "TRIGGER EVENT //HARNESS/254/202/1 123"
    )
    .await
    .contains("200 OK"));
    assert_eq!(sys.pci.count_payload("05CA0002017BB3"), 1);
    assert!(command(
        &mut reader,
        &mut writer,
        "TRIGGER INDICATORKILL //HARNESS/254/202/1"
    )
    .await
    .contains("200 OK"));
    assert_eq!(sys.pci.count_payload("05CA00090127"), 1);
    assert!(command(
        &mut reader,
        &mut writer,
        "ENABLE SET //HARNESS/254/203/1 127"
    )
    .await
    .contains("200 OK"));
    assert_eq!(sys.pci.count_payload("05CB0002017FAE"), 1);
    assert!(command(
        &mut reader,
        &mut writer,
        "LIGHTING LABEL //HARNESS/254/56 0 1 - F2 0 4c6f756e6765"
    )
    .await
    .contains("200 OK"));
    assert_eq!(sys.pci.count_payload("053800A90140004C6F756E67656F"), 1);
    assert!(command(
        &mut reader,
        &mut writer,
        "TRIGGER LABEL //HARNESS/254/202 0 7 9 F3 0 5363656e65"
    )
    .await
    .contains("200 OK"));
    assert_eq!(sys.pci.count_payload("05CA00A9076109005363656E6529"), 1);
    assert!(command(
        &mut reader,
        &mut writer,
        "TRIGGER UNICODELABEL //HARNESS/254/202 2 8 - F0 RAW e5a49ce99693"
    )
    .await
    .contains("200 OK"));
    assert_eq!(sys.pci.count_payload("05CA00CA080E0002E5A49CE9969318"), 1);
    assert!(command(
        &mut reader,
        &mut writer,
        "ENABLE LABEL //HARNESS/254/203 0 9 0 F0 ICON 258"
    )
    .await
    .contains("200 OK"));
    assert_eq!(sys.pci.count_payload("05CB00A70903000001010279"), 1);
    assert!(command(
        &mut reader,
        &mut writer,
        "LIGHTING LABEL //HARNESS/254/56 7 3 - F0 DYNAMIC 65535 8 7 2 01020408102040"
    )
    .await
    .contains("200 OK"));
    for payload in [
        "053800A403080020F4",
        "053800A8030407FFFF080702FE",
        "053800A80304010204081020D5",
        "053800A3030440D9",
        "053800A403080022F2",
    ] {
        assert_eq!(sys.pci.count_payload(payload), 1, "{payload}");
    }
    assert_eq!(sys.pci.count_payload("053800A403080021F3"), 2);
    assert!(command(
        &mut reader,
        &mut writer,
        "LIGHTING LABEL //HARNESS/254/56 3 1 - F0 SET_LANGUAGE"
    )
    .await
    .contains("200 OK"));
    assert_eq!(sys.pci.count_payload("053800A301060316"), 1);

    let kfi_get = command(&mut reader, &mut writer, "LABEL KFIGET //HARNESS/254/56 5");
    let kfi_peer = async {
        for payload in [
            "460500A3FF00090A",
            "460500A5FF0082001C73",
            "460500A5FF008404FF8A",
        ] {
            answer_kfi_write(&sys, payload, 1).await;
        }
        require(COMMAND_DRAIN, "KFI IDENTIFY 0x3D", || {
            sys.pci.count_payload("460500213D57") == 1
        })
        .await;
        let mut reply = vec![0x86, 5, 0x10, 0x01, 0x00, 0x8d, 0x3d, 0x80];
        reply.extend_from_slice(&[0x21, 0x43, 0x65, 0x87]);
        reply.extend_from_slice(&[0; 7]);
        sys.pci.inject(&pci_wire(&reply));
    };
    let (kfi_get, ()) = tokio::join!(kfi_get, kfi_peer);
    assert!(kfi_get.contains("300-kfi1=1"), "{kfi_get:?}");
    assert!(kfi_get.contains("300 kfi8=8"), "{kfi_get:?}");

    let kfi_set = command(
        &mut reader,
        &mut writer,
        "LABEL KFISET //HARNESS/254/56 5 1 2 3 4 5 6 7 8",
    );
    let kfi_peer = async {
        for (payload, occurrence) in [
            ("460500A3FF00090A", 2),
            ("460500A5FF0084214329", 1),
            ("460500A5FF00846587A1", 1),
            ("460500A4FF006BACFB", 1),
        ] {
            answer_kfi_write(&sys, payload, occurrence).await;
        }
    };
    let (kfi_set, ()) = tokio::join!(kfi_set, kfi_peer);
    assert!(kfi_set.contains("200 OK"), "{kfi_set:?}");

    let observed = command(&mut reader, &mut writer, "CMQTT LABELS //HARNESS/254/p/5").await;
    assert!(observed.contains("cmqttd-observed-dynamic-labels-v1"));
    assert!(observed.contains("observed-sal-traffic"));
    assert!(observed.contains("\"observation_scope\":\"network\""));
    assert!(observed.contains("\"requested_address\":\"//HARNESS/254/p/5\""));
    assert!(observed.contains("\"recipient_verified\":false"));
    assert!(observed.contains("\"complete\":false"));
    assert!(observed.contains("\"device_readback\":false"));
    assert!(observed.contains("\"direction\":\"sent-confirmed\""));
    assert!(observed.contains("a90140004c6f756e6765"));
    assert!(observed.contains("ca080e0002e5a49ce99693"));
    assert!(observed.contains("a403080022"));
    let mut incoming_label = vec![5, 9, 56, 0];
    incoming_label.extend_from_slice(&[0xa6, 2, 0, 0, b'B', b'u', b's']);
    sys.pci.inject(&pci_wire(&incoming_label));
    let observed = command_until(
        &mut reader,
        &mut writer,
        "CMQTT LABELS //HARNESS/254",
        "a6020000427573",
    )
    .await;
    assert!(observed.contains("\"observation_scope\":\"network\""));
    assert!(observed.contains("\"requested_address\":\"//HARNESS/254\""));
    assert!(observed.contains("\"recipient_verified\":false"));
    assert!(observed.contains("\"device_readback\":false"));
    assert!(observed.contains("\"direction\":\"received\""));
    assert!(observed.contains("\"source_unit\":9"));
    assert!(
        command(&mut reader, &mut writer, "LABEL CLEAR //HARNESS/254/56 5")
            .await
            .contains("200 OK")
    );
    assert_eq!(sys.pci.count_payload("460500A3FF0027EC"), 1);
    assert!(command(
        &mut reader,
        &mut writer,
        "LABEL CLEAR //HARNESS/254/203 5 8"
    )
    .await
    .contains("200 OK"));
    assert_eq!(sys.pci.count_payload("460500A4FF006608A4"), 1);
    let observed = command(&mut reader, &mut writer, "CMQTT LABELS //HARNESS/254").await;
    assert!(observed.contains("\"observations\":[]"), "{observed:?}");
    assert!(command(
        &mut reader,
        &mut writer,
        "ENABLE UNICODELABEL //HARNESS/254/203 0 1 - F0 RAW 41"
    )
    .await
    .contains("400 ENABLE has no UNICODELABEL"));
    assert!(command(
        &mut reader,
        &mut writer,
        "LABEL CLEAREDLT //HARNESS/254/p/5"
    )
    .await
    .contains("401 Unit not found"));
    assert!(command(
        &mut reader,
        &mut writer,
        "DBADDSAFE //HARNESS/254 Unit 5 Fixture_eDLT"
    )
    .await
    .contains("200 OK"));
    assert!(command(
        &mut reader,
        &mut writer,
        "DBSETSAFE //HARNESS/254/p/5/UnitType KEYGL5"
    )
    .await
    .contains("200 OK"));
    let clear = command(
        &mut reader,
        &mut writer,
        "LABEL CLEAREDLT //HARNESS/254/p/5",
    );
    let clear_reply = async {
        require(COMMAND_DRAIN, "eDLT label clear control", || {
            sys.pci.count_payload("46050900A4FF43C1EA1B") == 1
        })
        .await;
        sys.pci
            .inject(&pci_wire(&[0x86, 5, 0x10, 0x01, 0x00, 0x32, 0xff, 0x43]));
    };
    let (clear, ()) = tokio::join!(clear, clear_reply);
    assert!(clear.contains("200 OK."), "{clear:?}");
    assert_eq!(sys.pci.count_payload("46050900A4FF43C1EA1B"), 1);
    let observed = command(&mut reader, &mut writer, "CMQTT LABELS //HARNESS/254/p/5").await;
    assert!(observed.contains("\"observations\":[]"), "{observed:?}");

    // The destructive CBusEdlt object method uses its distinct captured OEM
    // control exactly once. A 202 means the source-correlated ACK arrived; it
    // does not claim post-reboot defaults or persistence.
    let reset = command(
        &mut reader,
        &mut writer,
        "DO //HARNESS/254/p/5 FactoryDefault",
    );
    let reset_reply = async {
        require(COMMAND_DRAIN, "eDLT factory-default control", || {
            sys.pci.count_payload("46050900A4FF43B2B262") == 1
        })
        .await;
        sys.pci
            .inject(&pci_wire(&[0x86, 5, 0x10, 0x01, 0x00, 0x32, 0xff, 0x43]));
    };
    let (reset, ()) = tokio::join!(reset, reset_reply);
    assert!(reset.contains("202 Done: //HARNESS/254/p/5"), "{reset:?}");
    assert_eq!(sys.pci.count_payload("46050900A4FF43B2B262"), 1);
    // Attribute-suffixed and foreign scopes are not a network or unit.
    for address in [
        "CMQTT LABELS //HARNESS/254/p/5/TagName",
        "CMQTT LABELS //OTHER/254",
        "CMQTT LABELS //OTHER/254/p/5",
    ] {
        assert!(
            command(&mut reader, &mut writer, address)
                .await
                .contains("400 CMQTT LABELS requires the configured network or unit"),
            "{address}"
        );
    }
    assert!(
        command(&mut reader, &mut writer, "GET //HARNESS/254/203/1 Level")
            .await
            .contains("Level=127")
    );
    assert!(command(
        &mut reader,
        &mut writer,
        "ENABLE REMOVE //HARNESS/254/203/1"
    )
    .await
    .contains("200 OK"));
    assert_eq!(sys.pci.count_payload("05CB0002017FAE"), 1);
    assert!(
        command(&mut reader, &mut writer, "CLOCK DATE 254/223 2026-09-24")
            .await
            .contains("232 Date set to: 2026-09-24")
    );
    assert_eq!(sys.pci.count_payload("05DF000E0207EA091803F7"), 1);
    assert!(
        command(&mut reader, &mut writer, "CLOCK TIME 254/223 12:34:56")
            .await
            .contains("232 Time set to: 12:34:56")
    );
    assert_eq!(sys.pci.count_payload("05DF000D010C2238FFA9"), 1);
    assert!(
        command(&mut reader, &mut writer, "CLOCK REQUEST_REFRESH 254/223")
            .await
            .contains("200 OK")
    );
    assert_eq!(sys.pci.count_payload("05DF00110308"), 1);
    assert!(command(
        &mut reader,
        &mut writer,
        "TEMPERATURE BROADCAST //HARNESS/254/$19/1 21.3"
    )
    .await
    .contains("200 OK"));
    assert_eq!(sys.pci.count_payload("0519000201558A"), 1);
    assert!(command(
        &mut reader,
        &mut writer,
        "TEMPERATURE BROADCAST //HARNESS/254/25/1 64"
    )
    .await
    .contains("405 Temperature is out of range"));
    assert_eq!(sys.pci.count_payload("0519000201558A"), 1);
    assert!(command(
        &mut reader,
        &mut writer,
        "TRIGGER EVENT //HARNESS/254/203/1 1"
    )
    .await
    .contains("400 Trigger Control application must be 202"));
    assert!(
        command(&mut reader, &mut writer, "ENABLE SET //HARNESS/254/202/1 1")
            .await
            .contains("400 Enable Control application must be 203")
    );

    // Incoming non-lighting application traffic updates C-Gate's live cache
    // and remains outside MQTT's lighting topic contract.
    sys.pci.inject(&pci_wire(&[5, 9, 202, 0, 2, 1, 100]));
    sys.pci.inject(&pci_wire(&[5, 9, 203, 0, 2, 1, 66]));
    assert!(command_until(
        &mut reader,
        &mut writer,
        "GET //HARNESS/254/203/1 Level",
        "Level=66"
    )
    .await
    .contains("Level=66"));
    assert!(
        command(&mut reader, &mut writer, "GET //HARNESS/254/202/1 Level")
            .await
            .contains("402 Parameter not found")
    );
    assert!(
        command(&mut reader, &mut writer, "GET //HARNESS/254/202 Groups")
            .await
            .contains("Groups=1")
    );
    let pingu = command(&mut reader, &mut writer, "NET PINGU //HARNESS/254");
    let mmi = async {
        require(STARTUP, "installation MMI request", || {
            sys.pci.count_payload("05FF00FAFF0003") == 1
        })
        .await;
        sys.pci
            .inject(b"D8FF000000000001000000000000000000000000000000000028\r\n");
        sys.pci
            .inject(b"D8FF5800000000000000000000000000000000000000000000D1\r\n");
        sys.pci
            .inject(b"D6FFB00000000000000000000000000000000000000080FB\r\n");
    };
    let (pingu, ()) = tokio::join!(pingu, mmi);
    assert!(pingu.contains("302-Units=16, 255"), "{pingu:?}");
    assert!(pingu.contains("200 OK."), "{pingu:?}");
    assert!(command(&mut reader, &mut writer, "GET //HARNESS/254 Units")
        .await
        .contains("Units=16, 255"));
    sys.broker
        .inject("homeassistant/light/cbus_1/set", br#"{"state":"OFF"}"#);
    require(COMMAND_DRAIN, "MQTT command on shared PCI", || {
        sys.pci.count_payload("0538000101C1") > 0
    })
    .await;
    assert_eq!(sys.pci.connections(), 1);
    let type_16 = b"PC_CNIED".as_slice();
    let type_255 = b"KEYE1   ".as_slice();
    let firmware_16 = b"5.5.00  ".as_slice();
    let firmware_255 = b"2.5.00  ".as_slice();
    let serial_16 = [
        0xff, 0xff, 0xff, 0x00, 0x00, 0x18, 0xa6, 0x64, 0xa3, 0xb1, 0x00, 0x05,
    ];
    let serial_255_a = [
        0x38, 0xff, 0xff, 0xff, 0xff, 0x18, 0xb1, 0x06, 0x16, 0xa2, 0x00, 0x05,
    ];
    let serial_255_b = [
        0x38, 0xff, 0xff, 0xff, 0xff, 0x18, 0xb1, 0x06, 0x17, 0xa2, 0x00, 0x05,
    ];
    let sync = command(&mut reader, &mut writer, "DO //HARNESS/254 SYNC");
    let identities = async {
        require(STARTUP, "BASIC local-address request", || {
            sys.pci
                .frames()
                .iter()
                .any(|frame| frame.basic && frame.payload == "1A2001")
        })
        .await;
        sys.pci.inject(b"8220104E\r\n");
        require(STARTUP, "synchronization installation MMI request", || {
            sys.pci.count_payload("05FF00FAFF0003") == 2
        })
        .await;
        sys.pci
            .inject(b"D8FF000000000001000000000000000000000000000000000028\r\n");
        sys.pci
            .inject(b"D8FF5800000000000000000000000000000000000000000000D1\r\n");
        sys.pci
            .inject(b"D6FFB00000000000000000000000000000000000000080FB\r\n");
        answer_identify(&sys, 16, 1, 1, &[type_16]).await;
        answer_identify(&sys, 16, 2, 1, &[firmware_16]).await;
        answer_identify(&sys, 16, 4, 1, &[&serial_16]).await;
        answer_identify(&sys, 255, 1, 1, &[type_255]).await;
        answer_identify(&sys, 255, 2, 1, &[firmware_255]).await;
        answer_identify(&sys, 255, 4, 1, &[&serial_255_a, &serial_255_b]).await;
    };
    let (sync, ()) = tokio::join!(sync, identities);
    assert!(sync.contains("202 Done: //HARNESS/254"), "{sync:?}");
    assert!(command(&mut reader, &mut writer, "GET //HARNESS/254 Units")
        .await
        .contains("Units=16, 255"));
    assert!(
        command(&mut reader, &mut writer, "GET //HARNESS/254/p/16 Type")
            .await
            .contains("Type=PC_CNIED")
    );
    assert!(command(
        &mut reader,
        &mut writer,
        "GET //HARNESS/254/p/16 SerialNumber"
    )
    .await
    .contains("SerialNumber=100966.1187"));
    let clocks = command(&mut reader, &mut writer, "NET CLOCKS //HARNESS/254");
    let clock_status = async {
        answer_identify(&sys, 16, 16, 1, &[&[0x03, 0x00, 0x00, 0xff]]).await;
        answer_identify(&sys, 255, 16, 1, &[&[0x80, 0x00, 0x00, 0xff]]).await;
    };
    let (clocks, ()) = tokio::join!(clocks, clock_status);
    assert!(
        clocks.contains(
            "120-address=16 output_units=1 clocks_enabled=1 clocks_active=1 burdens_enabled=0"
        ),
        "{clocks:?}"
    );
    assert!(
        clocks.contains(
            "120-address=255 output_units=1 clocks_enabled=0 clocks_active=0 burdens_enabled=1"
        ),
        "{clocks:?}"
    );
    assert!(clocks.contains("200 OK."), "{clocks:?}");
    assert!(
        command(&mut reader, &mut writer, "NET CLOCKS //HARNESS/254 11")
            .await
            .contains("400 Clock target must be in 1..10")
    );
    assert!(command(
        &mut reader,
        &mut writer,
        "GET //HARNESS/254/p/255 SerialNumber"
    )
    .await
    .contains("SerialNumber="));

    let check = command(
        &mut reader,
        &mut writer,
        "NET CHECKUNIT //HARNESS/254 16,255,99",
    );
    let checked = async {
        answer_identify(&sys, 16, 4, 2, &[&serial_16]).await;
        answer_identify(&sys, 255, 4, 2, &[&serial_255_a, &serial_255_b]).await;
        answer_identify(&sys, 99, 4, 1, &[]).await;
    };
    let (check, ()) = tokio::join!(check, checked);
    assert!(
        check.contains("120-Single unit detected at address: 16"),
        "{check:?}"
    );
    assert!(
        check.contains("120-Duplicate units detected at address: 255"),
        "{check:?}"
    );
    assert!(
        check.contains("120-No units detected at address: 99"),
        "{check:?}"
    );
    assert!(check.contains("200 OK."), "{check:?}");
    assert!(
        command(&mut reader, &mut writer, "DO //HARNESS/254 UNRAVEL")
            .await
            .contains("502 DO UNRAVEL requires a physical backend")
    );
    assert_eq!(sys.pci.connections(), 1);
    drop(sys);
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn keygl5_sync_populates_native_metadata_properties_in_classfile_order() {
    let state = cbus_test_support::proc::temp_path("widgetgroups-cgate.json");
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
    require(STARTUP, "C-Gate listener", || {
        sys.daemon.stderr().contains("C-Gate service listening on ")
    })
    .await;
    let addr = sys
        .daemon
        .stderr()
        .lines()
        .find_map(|line| {
            line.split_once("C-Gate service listening on ")
                .map(|(_, addr)| addr.trim().to_string())
        })
        .unwrap();
    let stream = TcpStream::connect(&addr).await.unwrap();
    let (reader, mut writer) = stream.into_split();
    let mut reader = BufReader::new(reader);
    let mut greeting = String::new();
    reader.read_line(&mut greeting).await.unwrap();
    assert!(greeting.starts_with("201 "));

    async fn command(
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
            reader.read_line(&mut line).await.unwrap();
            result.push_str(&line);
            if line.starts_with("[1]") && line.as_bytes().get(7) == Some(&b' ') {
                return result;
            }
        }
    }

    async fn answer_identify(sys: &System, unit: u8, attribute: u8, data: &[u8]) {
        let prefix = format!("46{unit:02X}0021{attribute:02X}");
        require(COMMAND_DRAIN, "KEYGL5 IDENTIFY request", || {
            sys.pci
                .frames()
                .iter()
                .any(|frame| frame.payload.starts_with(&prefix))
        })
        .await;
        let mut body = vec![
            0x86,
            unit,
            0x10,
            0x01,
            0x00,
            0x80 | (data.len() as u8 + 1),
            attribute,
        ];
        body.extend_from_slice(data);
        sys.pci.inject(&pci_wire(&body));
    }

    assert!(command(
        &mut reader,
        &mut writer,
        "DBADDSAFE //HARNESS/254 Unit 5 Fixture_eDLT",
    )
    .await
    .contains("200 OK"));
    assert!(command(
        &mut reader,
        &mut writer,
        "DBSETSAFE //HARNESS/254/p/5/UnitType KEYGL5",
    )
    .await
    .contains("200 OK"));

    let sync = command(&mut reader, &mut writer, "NET SYNC //HARNESS/254");
    let peer = async {
        require(STARTUP, "BASIC local-address request", || {
            sys.pci
                .frames()
                .iter()
                .any(|frame| frame.basic && frame.payload == "1A2001")
        })
        .await;
        sys.pci.inject(b"8220104E\r\n");
        require(STARTUP, "WidgetGroups synchronization MMI", || {
            sys.pci.count_payload("05FF00FAFF0003") == 1
        })
        .await;
        // Real direct networks can report a healthy, uniquely identified unit
        // as state two. The single complete IDENTIFY4 window below is the
        // independent uniqueness guard for source-address-only OEM reads.
        sys.pci
            .inject(&installation_mmi_block_with_state(0, 88, &[5], 2));
        sys.pci
            .inject(&installation_mmi_block_with_state(88, 88, &[], 2));
        sys.pci
            .inject(&installation_mmi_block_with_state(176, 80, &[], 2));

        answer_identify(&sys, 5, 1, b"KEYGL5").await;
        answer_identify(&sys, 5, 2, b"5.5.00").await;
        answer_identify(&sys, 5, 4, &serial_identity("101136.1558", 5)).await;

        require(COMMAND_DRAIN, "KEYGL5 extended-firmware recall", || {
            sys.pci.count_payload("460509001AFB098E") == 1
        })
        .await;
        let firmware = cbus_protocol::Cal::Reply {
            parameter: 0xfb,
            data: b"01.05.00\0".to_vec(),
        }
        .encode();
        let mut body = vec![0x86, 5, 0x10, 0x01, 0x00];
        body.extend(firmware);
        sys.pci.inject(&pci_wire(&body));

        require(COMMAND_DRAIN, "KEYGL5 application address selector", || {
            sys.pci.count_payload("46050900A400411000B7") == 1
        })
        .await;
        sys.pci
            .inject(&pci_wire(&[0x86, 5, 0x10, 0x01, 0x00, 0x32, 0, 0x41]));
        require(COMMAND_DRAIN, "KEYGL5 application recall", || {
            sys.pci.count_payload("460509001A01028F") == 1
        })
        .await;
        sys.pci
            .inject(&pci_wire(&[0x86, 5, 0x10, 0x01, 0x00, 0x83, 1, 56, 255]));

        require(COMMAND_DRAIN, "KEYGL5 WidgetGroups recall", || {
            sys.pci.count_payload("460509001AFA2C6C") == 1
        })
        .await;
        let mut values = [0xff; 44];
        values[12..20].copy_from_slice(&[0x38, 0x1b, 0x38, 0x19, 0x38, 0x21, 0x38, 0x18]);
        for fragment in values.chunks(16) {
            let cal = cbus_protocol::Cal::Reply {
                parameter: 0xfa,
                data: fragment.to_vec(),
            }
            .encode();
            let mut body = vec![0x86, 5, 0x10, 0x01, 0x00];
            body.extend(cal);
            sys.pci.inject(&pci_wire(&body));
        }
    };
    let (sync, ()) = tokio::join!(sync, peer);
    assert!(sync.contains("200 OK"), "{sync:?}");
    assert_eq!(sys.pci.count_payload("460509001AFB098E"), 1);
    assert_eq!(sys.pci.count_payload("46050900A400411000B7"), 1);
    assert_eq!(sys.pci.count_payload("460509001A01028F"), 1);
    assert_eq!(sys.pci.count_payload("460509001AFA2C6C"), 1);
    let frames = sys.pci.frames();
    let position = |payload: &str| {
        frames
            .iter()
            .position(|frame| frame.payload == payload)
            .unwrap_or_else(|| panic!("missing {payload}"))
    };
    assert!(
        position("460509001AFB098E") < position("46050900A400411000B7")
            && position("46050900A400411000B7") < position("460509001A01028F")
            && position("460509001A01028F") < position("460509001AFA2C6C"),
        "retained CBusEdlt classfile order: {frames:?}"
    );

    let mut expected_values = [0xff; 44];
    expected_values[12..20].copy_from_slice(&[0x38, 0x1b, 0x38, 0x19, 0x38, 0x21, 0x38, 0x18]);
    let expected = expected_values
        .iter()
        .map(u8::to_string)
        .collect::<Vec<_>>()
        .join(",");
    let property = command(
        &mut reader,
        &mut writer,
        "GET //HARNESS/254/p/5 WidgetGroups",
    )
    .await;
    assert!(
        property.contains(&format!("300 //HARNESS/254/p/5: WidgetGroups={expected}")),
        "{property:?}"
    );
    let firmware = command(
        &mut reader,
        &mut writer,
        "GET //HARNESS/254/p/5 FirmwareVersion",
    )
    .await;
    assert!(
        firmware.contains("FirmwareVersion=01.05.00"),
        "{firmware:?}"
    );
    let version = command(&mut reader, &mut writer, "GET //HARNESS/254/p/5 Version").await;
    assert!(version.contains("Version=5.5.00"), "{version:?}");
    let application = command(
        &mut reader,
        &mut writer,
        "GET //HARNESS/254/p/5 Application",
    )
    .await;
    assert!(application.contains("Application=56"), "{application:?}");
    let application2 = command(
        &mut reader,
        &mut writer,
        "GET //HARNESS/254/p/5 Application2",
    )
    .await;
    assert!(
        application2.contains("Application2=255"),
        "{application2:?}"
    );

    drop(sys);
    std::fs::remove_file(state).unwrap();
}

#[tokio::test]
async fn bounded_matchdb_unravel_runs_through_real_daemon_and_shared_pci() {
    let state = cbus_test_support::proc::temp_path("physical-unravel-cgate.json");
    let project = cbus_test_support::proc::temp_path("physical-unravel-project.xml");
    let units = r#"
      <Unit><Address>6</Address><TagName>First target</TagName><UnitType>KEYE1</UnitType><SerialNumber>101136.1558</SerialNumber><FirmwareVersion>2.5.00</FirmwareVersion></Unit>
      <Unit><Address>7</Address><TagName>Second target</TagName><UnitType>KEYE1</UnitType><SerialNumber>101136.1559</SerialNumber><FirmwareVersion>2.5.00</FirmwareVersion></Unit>
      <Unit><Address>16</Address><TagName>Local CNI</TagName><UnitType>PC_CNI</UnitType><SerialNumber>100966.1187</SerialNumber><FirmwareVersion>5.5.00</FirmwareVersion></Unit>
    "#;
    std::fs::write(
        &project,
        include_str!("../../testdata/fixtures/project.xml")
            .replace("    </Network>", &format!("{units}    </Network>")),
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

    async fn wait_for_payload(sys: &System, description: &str, prefix: &str, occurrence: usize) {
        require(COMMAND_DRAIN, description, || {
            sys.pci
                .frames()
                .iter()
                .filter(|frame| frame.payload.starts_with(prefix))
                .count()
                >= occurrence
        })
        .await;
    }
    async fn inject_mmi(sys: &System, occurrence: usize, present: &[usize]) {
        wait_for_payload(
            sys,
            "unravel installation MMI request",
            "05FF00FAFF",
            occurrence,
        )
        .await;
        for (start, count) in [(0, 88), (88, 88), (176, 80)] {
            let block_present = present
                .iter()
                .copied()
                .filter(|address| (start..start + count).contains(address))
                .collect::<Vec<_>>();
            sys.pci
                .inject(&installation_mmi_block(start as u8, count, &block_present));
        }
    }
    async fn answer_identity(sys: &System, address: u8, occurrence: usize, serials: &[&str]) {
        let prefix = format!("46{address:02X}002104");
        wait_for_payload(sys, "unravel IDENTIFY4 request", &prefix, occurrence).await;
        for serial in serials {
            let data = serial_identity(serial, address);
            let mut body = vec![0x86, address, 0x10, 0x00, 0x8d, 4];
            body.extend_from_slice(&data);
            sys.pci.inject(&pci_wire(&body));
        }
    }
    async fn answer_local_options(sys: &System, occurrence: usize) {
        wait_for_payload(
            sys,
            "unravel local PCI option request",
            "4610001A4201",
            occurrence,
        )
        .await;
        sys.pci
            .inject(&pci_wire(&[0x86, 16, 0x10, 0x00, 0x82, 0x42, 5]));
    }
    async fn answer_selected_serial(sys: &System, serial: &str, destination: u8) {
        let expected =
            cbus_protocol::serial_address::encode_serial_address(serial, destination, true, b'g')
                .unwrap();
        let expected = std::str::from_utf8(&expected[1..expected.len() - 2]).unwrap();
        wait_for_payload(sys, "selected-serial address request", expected, 1).await;
        if destination == 6 {
            sys.pci.inject(&pci_wire(&[5, 4, 56, 0, 121, 1]));
        }
        let packed = cbus_protocol::serial_address::parse_native_serial(serial)
            .unwrap()
            .packed;
        let mut body = vec![0x86, destination, 0x10, 0x00, 0x87, 0];
        body.extend_from_slice(&packed);
        body.extend_from_slice(&[0, 0]);
        sys.pci.inject(&pci_wire(&body));
    }

    let command = async {
        writer
            .write_all(b"[42] NET UNRAVELUNIT //HARNESS/254 255 MATCHDB\r\n")
            .await
            .unwrap();
        let mut result = String::new();
        loop {
            let mut line = String::new();
            reader.read_line(&mut line).await.unwrap();
            result.push_str(&line);
            if line.starts_with("[42] ") && line.as_bytes().get(8) == Some(&b' ') {
                break result;
            }
        }
    };
    let bus = async {
        inject_mmi(&sys, 1, &[16, 255]).await;
        answer_identity(&sys, 16, 1, &["100966.1187"]).await;
        answer_identity(&sys, 255, 1, &["101136.1558", "101136.1559"]).await;
        answer_local_options(&sys, 1).await;
        answer_identity(&sys, 6, 1, &[]).await;
        answer_identity(&sys, 7, 1, &[]).await;

        answer_selected_serial(&sys, "101136.1558", 6).await;
        answer_identity(&sys, 6, 2, &["101136.1558"]).await;
        answer_selected_serial(&sys, "101136.1559", 7).await;
        answer_identity(&sys, 7, 2, &["101136.1559"]).await;

        inject_mmi(&sys, 2, &[6, 7, 16]).await;
        answer_identity(&sys, 6, 3, &["101136.1558"]).await;
        answer_identity(&sys, 7, 3, &["101136.1559"]).await;
        answer_identity(&sys, 16, 2, &["100966.1187"]).await;
        answer_local_options(&sys, 2).await;
    };
    let (response, ()) = tokio::join!(command, bus);
    assert!(response.contains("[42] 200 OK"), "{response:?}");

    for (serial, destination) in [("101136.1558", 6), ("101136.1559", 7)] {
        let expected =
            cbus_protocol::serial_address::encode_serial_address(serial, destination, true, b'g')
                .unwrap();
        let expected = std::str::from_utf8(&expected[1..expected.len() - 2]).unwrap();
        assert_eq!(
            sys.pci.count_payload(expected),
            1,
            "{serial} -> {destination}"
        );
    }
    require(STARTUP, "lighting event in MQTT during unravel", || {
        sys.broker
            .publishes()
            .iter()
            .any(|publish| publish.topic == "homeassistant/light/cbus_1/state")
    })
    .await;
    assert_eq!(sys.pci.connections(), 1);
    drop(sys);
    std::fs::remove_file(state).unwrap();
    std::fs::remove_file(project).unwrap();
}

#[tokio::test]
async fn physical_readdress_runs_once_through_real_daemon_and_shared_pci() {
    let state = cbus_test_support::proc::temp_path("physical-readdress-cgate.json");
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

    let command = async {
        writer
            .write_all(b"[9] SET //HARNESS/254/p/5 Address 6\r\n")
            .await
            .unwrap();
        let mut result = String::new();
        loop {
            let mut line = String::new();
            reader.read_line(&mut line).await.unwrap();
            result.push_str(&line);
            if line.starts_with("[9]") && line.as_bytes().get(7) == Some(&b' ') {
                break result;
            }
        }
    };
    let bus = async {
        require(COMMAND_DRAIN, "readdress source identity check", || {
            sys.pci
                .frames()
                .iter()
                .any(|frame| frame.payload.starts_with("4605002104"))
        })
        .await;
        let serial = [
            0x38, 0xff, 0xff, 0xff, 0xff, 0x18, 0xb1, 0x06, 0x16, 0xa2, 0x00, 0x05,
        ];
        let mut identity = vec![0x86, 5, 0x10, 0x01, 0x00, 0x8d, 4];
        identity.extend(serial);
        sys.pci.inject(&pci_wire(&identity));
        require(COMMAND_DRAIN, "readdress empty destination check", || {
            sys.pci
                .frames()
                .iter()
                .any(|frame| frame.payload.starts_with("4606002104"))
        })
        .await;
        require(COMMAND_DRAIN, "readdress unlock", || {
            sys.pci
                .frames()
                .iter()
                .any(|frame| frame.payload.starts_with("4605001120"))
        })
        .await;
        sys.pci
            .inject(&pci_wire(&[0x86, 5, 0x10, 0x01, 0x00, 0x82, 0x20, 0x5a]));
        require(COMMAND_DRAIN, "protected address STORE", || {
            sys.pci
                .frames()
                .iter()
                .any(|frame| frame.payload == "460500A3204E065A")
        })
        .await;
        sys.pci.inject(&pci_wire(&[5, 4, 56, 0, 121, 1]));
        sys.pci
            .inject(&pci_wire(&[0x86, 6, 0x10, 0x01, 0x00, 0x32, 0x20, 0x4e]));
    };
    let (response, ()) = tokio::join!(command, bus);
    assert!(
        response.contains("[9] 200 OK: //HARNESS/254/p/6"),
        "{response:?}"
    );
    assert_eq!(
        sys.pci
            .frames()
            .iter()
            .filter(|frame| frame.payload == "460500A3204E065A")
            .count(),
        1
    );
    require(STARTUP, "lighting event in MQTT during readdress", || {
        sys.broker
            .publishes()
            .iter()
            .any(|publish| publish.topic == "homeassistant/light/cbus_1/state")
    })
    .await;
    assert_eq!(sys.pci.connections(), 1);
    drop(sys);
    std::fs::remove_file(state).unwrap();
}

#[tokio::test]
async fn physical_pp_load_and_save_use_all_supported_routes_on_shared_pci() {
    let state = cbus_test_support::proc::temp_path("physical-pp-cgate.json");
    let specs = cbus_test_support::proc::temp_path("physical-pp-unitspec");
    std::fs::create_dir_all(&specs).unwrap();
    std::fs::write(
        specs.join("TESTUNIT.xml"),
        r#"<UnitSpecification><Parameters>
        <Param><Name>Standard</Name><Type>int</Type><Address>$20</Address><ArraySize>2</ArraySize><ProgramMethod>direct</ProgramMethod><Protection>checksum</Protection><Tag>Core</Tag></Param>
        <Param><Name>Locked</Name><Type>int</Type><Address>$22</Address><ProgramMethod>direct</ProgramMethod><Protection>lock</Protection><Tag>Core</Tag></Param>
        <Param><Name>Paged</Name><Type>int</Type><Address>$1FE</Address><ArraySize>4</ArraySize><ProgramMethod>paged</ProgramMethod><Protection>none</Protection><Tag>Core</Tag></Param>
        <Param><Name>Ncc</Name><Type>int</Type><Address>$300</Address><ArraySize>2</ArraySize><ProgramMethod>ncc</ProgramMethod><Protection>checksum</Protection><Tag>Core</Tag></Param>
        <Param><Name>Mapped</Name><Type>int</Type><Address>$110</Address><ArraySize>3</ArraySize><BitSize>4</BitSize><BitAddress>4</BitAddress><ArraySkip>1</ArraySkip><ArrayMap>2 3 1</ArrayMap><ProgramMethod>edlt</ProgramMethod><Protection>none</Protection><Tag>Core</Tag></Param>
        <Param><Name>Giu</Name><Type>int</Type><Address>$130</Address><ProgramMethod>giu</ProgramMethod><Protection>none</Protection><Tag>Core</Tag></Param>
        <Param><Name>Goc2</Name><Type>int</Type><Address>$140</Address><ArraySize>2</ArraySize><ProgramMethod>goc2</ProgramMethod><Protection>none</Protection><Tag>Core</Tag></Param>
        <Param><Name>Excluded</Name><Type>string</Type><Address>$120</Address><ArraySize>4</ArraySize><Tag>Other</Tag></Param>
        </Parameters></UnitSpecification>"#,
    )
    .unwrap();
    let sys = start_with(Options {
        extra: vec![
            "--cgate-bind".into(),
            "127.0.0.1:0".into(),
            "--cgate-state".into(),
            state.to_string_lossy().into_owned(),
            "--cgate-unitspec".into(),
            specs.to_string_lossy().into_owned(),
        ],
        ..Default::default()
    })
    .await;
    wait_started(&sys).await;
    require(STARTUP, "C-Gate listener", || {
        sys.daemon.stderr().contains("C-Gate service listening on ")
    })
    .await;
    let logs = sys.daemon.stderr();
    let addr = logs
        .lines()
        .find_map(|line| {
            line.split_once("C-Gate service listening on ")
                .map(|(_, addr)| addr.trim())
        })
        .unwrap();
    let stream = TcpStream::connect(addr).await.unwrap();
    let (reader, mut writer) = stream.into_split();
    let mut reader = BufReader::new(reader);
    let mut greeting = String::new();
    reader.read_line(&mut greeting).await.unwrap();
    assert!(greeting.starts_with("201 "));

    async fn command(
        reader: &mut BufReader<tokio::net::tcp::OwnedReadHalf>,
        writer: &mut tokio::net::tcp::OwnedWriteHalf,
        text: &str,
    ) -> String {
        writer
            .write_all(format!("[7] {text}\r\n").as_bytes())
            .await
            .unwrap();
        let mut result = String::new();
        loop {
            let mut line = String::new();
            reader.read_line(&mut line).await.unwrap();
            result.push_str(&line);
            if line.starts_with("[7]") && line.as_bytes().get(7) == Some(&b' ') {
                return result;
            }
        }
    }

    assert!(command(&mut reader, &mut writer, "PROJECT USE HARNESS")
        .await
        .contains("200 OK"));
    assert!(command(&mut reader, &mut writer, "PP LOCK L //HARNESS/254")
        .await
        .contains("200 OK"));
    assert!(command(&mut reader, &mut writer, "PP START S L")
        .await
        .contains("200 OK"));

    let load = command(&mut reader, &mut writer, "PP LOAD S //HARNESS/254/p/5 Core");
    let responses = async {
        async fn identify(sys: &System, attribute: u8, data: &[u8], occurrence: usize) {
            let prefix = format!("46050021{attribute:02X}");
            require(COMMAND_DRAIN, "physical PP IDENTIFY", || {
                sys.pci
                    .frames()
                    .iter()
                    .filter(|frame| frame.payload.starts_with(&prefix))
                    .count()
                    >= occurrence
            })
            .await;
            let mut body = vec![
                0x86,
                5,
                0x10,
                0x01,
                0x00,
                0x80 | (data.len() as u8 + 1),
                attribute,
            ];
            body.extend_from_slice(data);
            sys.pci.inject(&pci_wire(&body));
        }
        identify(&sys, 1, b"TESTUNIT", 1).await;
        identify(&sys, 2, b"1.2.03", 1).await;

        require(COMMAND_DRAIN, "standard PP parameter recall", || {
            sys.pci
                .frames()
                .iter()
                .any(|frame| frame.payload.starts_with("4605001A2002"))
        })
        .await;
        sys.pci.inject(&pci_wire(&[
            0x86, 5, 0x10, 0x01, 0x00, 0x83, 0x20, 0x12, 0x34,
        ]));
        require(COMMAND_DRAIN, "locked PP parameter recall", || {
            sys.pci
                .frames()
                .iter()
                .any(|frame| frame.payload.starts_with("4605001A2201"))
        })
        .await;
        sys.pci
            .inject(&pci_wire(&[0x86, 5, 0x10, 0x01, 0x00, 0x82, 0x22, 0x9a]));

        require(COMMAND_DRAIN, "paged PP recall at page boundary", || {
            sys.pci
                .frames()
                .iter()
                .any(|frame| frame.payload == "4605001B01FE02")
        })
        .await;
        sys.pci.inject(&pci_wire(&[
            0x86, 5, 0x10, 0x01, 0x00, 0x83, 0xfe, 0xaa, 0xbb,
        ]));
        require(COMMAND_DRAIN, "paged PP recall continuation", || {
            sys.pci
                .frames()
                .iter()
                .any(|frame| frame.payload == "4605001B020002")
        })
        .await;
        sys.pci.inject(&pci_wire(&[
            0x86, 5, 0x10, 0x01, 0x00, 0x83, 0x00, 0xcc, 0xdd,
        ]));
        require(COMMAND_DRAIN, "NCC PP recall", || {
            sys.pci
                .frames()
                .iter()
                .any(|frame| frame.payload == "4605001B030002")
        })
        .await;
        sys.pci.inject(&pci_wire(&[
            0x86, 5, 0x10, 0x01, 0x00, 0x83, 0x00, 0x11, 0x22,
        ]));

        require(COMMAND_DRAIN, "OEM PP memory selector", || {
            sys.pci
                .frames()
                .iter()
                .any(|frame| frame.payload.starts_with("46050900A400411000"))
        })
        .await;
        sys.pci
            .inject(&pci_wire(&[0x86, 5, 0x10, 0x01, 0x00, 0x32, 0x00, 0x41]));
        require(COMMAND_DRAIN, "OEM PP memory recall", || {
            sys.pci
                .frames()
                .iter()
                .any(|frame| frame.payload.starts_with("460509001A0105"))
        })
        .await;
        sys.pci.inject(&pci_wire(&[
            0x86, 5, 0x10, 0x01, 0x00, 0x86, 0x01, 0xa1, 0x77, 0xb2, 0x88, 0xc3,
        ]));

        require(COMMAND_DRAIN, "GIU PP memory selector", || {
            sys.pci
                .frames()
                .iter()
                .any(|frame| frame.payload.starts_with("46050900A400413000"))
        })
        .await;
        sys.pci
            .inject(&pci_wire(&[0x86, 5, 0x10, 0x01, 0x00, 0x32, 0x00, 0x41]));
        require(COMMAND_DRAIN, "GIU PP memory recall", || {
            sys.pci
                .frames()
                .iter()
                .any(|frame| frame.payload.starts_with("460509001A0101"))
        })
        .await;
        sys.pci
            .inject(&pci_wire(&[0x86, 5, 0x10, 0x01, 0x00, 0x82, 0x01, 0x44]));

        require(COMMAND_DRAIN, "GOC2 PP address selector", || {
            sys.pci
                .frames()
                .iter()
                .any(|frame| frame.payload.starts_with("460500A4FF420040"))
        })
        .await;
        sys.pci
            .inject(&pci_wire(&[0x86, 5, 0x10, 0x01, 0x00, 0x32, 0xff, 0x42]));
        require(COMMAND_DRAIN, "GOC2 PP recall", || {
            sys.pci
                .frames()
                .iter()
                .any(|frame| frame.payload.starts_with("4605001AFF02"))
        })
        .await;
        sys.pci.inject(&pci_wire(&[
            0x86, 5, 0x10, 0x01, 0x00, 0x83, 0xff, 0x45, 0x46,
        ]));
    };
    let (loaded, ()) = tokio::join!(load, responses);
    assert!(loaded.contains("200 OK"), "{loaded:?}");
    let values = command(&mut reader, &mut writer, "PP GET S *").await;
    assert!(values.contains("315-Mapped=0xC 0xA 0xB"), "{values:?}");
    assert!(values.contains("315-Giu=0x44"), "{values:?}");
    assert!(values.contains("315-Goc2=0x45 0x46"), "{values:?}");
    assert!(values.contains("315-Locked=0x9A"), "{values:?}");
    assert!(values.contains("315-Ncc=0x11 0x22"), "{values:?}");
    assert!(
        values.contains("315-Paged=0xAA 0xBB 0xCC 0xDD"),
        "{values:?}"
    );
    assert!(values.contains("315 Standard=0x12 0x34"), "{values:?}");
    assert!(!values.contains("Excluded="), "{values:?}");

    assert!(
        command(&mut reader, &mut writer, "PP SET S Standard 0x56 0x78")
            .await
            .contains("200 OK")
    );
    assert!(
        command(&mut reader, &mut writer, "PP SET S Mapped 0x1 0x2 0x3")
            .await
            .contains("200 OK")
    );
    assert!(command(&mut reader, &mut writer, "PP SET S Locked 0xBC")
        .await
        .contains("200 OK"));
    assert!(command(
        &mut reader,
        &mut writer,
        "PP SET S Paged 0x01 0x02 0x03 0x04"
    )
    .await
    .contains("200 OK"));
    assert!(command(&mut reader, &mut writer, "PP SET S Ncc 0x05 0x06")
        .await
        .contains("200 OK"));
    assert!(command(&mut reader, &mut writer, "PP SET S Giu 0x55")
        .await
        .contains("200 OK"));
    assert!(command(&mut reader, &mut writer, "PP SET S Goc2 0x66 0x77")
        .await
        .contains("200 OK"));
    let save = command(&mut reader, &mut writer, "PP SAVE S //HARNESS/254/p/5 Core");
    let save_responses = async {
        async fn identify(sys: &System, attribute: u8, data: &[u8]) {
            let prefix = format!("46050021{attribute:02X}");
            require(COMMAND_DRAIN, "physical PP SAVE identity", || {
                sys.pci
                    .frames()
                    .iter()
                    .filter(|frame| frame.payload.starts_with(&prefix))
                    .count()
                    >= 2
            })
            .await;
            let mut body = vec![
                0x86,
                5,
                0x10,
                0x01,
                0x00,
                0x80 | (data.len() as u8 + 1),
                attribute,
            ];
            body.extend_from_slice(data);
            sys.pci.inject(&pci_wire(&body));
        }
        identify(&sys, 1, b"TESTUNIT").await;
        identify(&sys, 2, b"1.2.03").await;

        require(COMMAND_DRAIN, "standard PP save pre-read", || {
            sys.pci
                .frames()
                .iter()
                .filter(|frame| frame.payload.starts_with("4605001A2003"))
                .count()
                >= 1
        })
        .await;
        sys.pci.inject(&pci_wire(&[
            0x86, 5, 0x10, 0x01, 0x00, 0x84, 0x20, 0x12, 0x34, 0x9a,
        ]));
        require(
            COMMAND_DRAIN,
            "paged PP save pre-read at page boundary",
            || {
                sys.pci
                    .frames()
                    .iter()
                    .filter(|frame| frame.payload == "4605001B01FE02")
                    .count()
                    >= 2
            },
        )
        .await;
        sys.pci.inject(&pci_wire(&[
            0x86, 5, 0x10, 0x01, 0x00, 0x83, 0xfe, 0xaa, 0xbb,
        ]));
        require(COMMAND_DRAIN, "paged PP save pre-read continuation", || {
            sys.pci
                .frames()
                .iter()
                .filter(|frame| frame.payload == "4605001B020002")
                .count()
                >= 2
        })
        .await;
        sys.pci.inject(&pci_wire(&[
            0x86, 5, 0x10, 0x01, 0x00, 0x83, 0x00, 0xcc, 0xdd,
        ]));
        require(COMMAND_DRAIN, "NCC PP save pre-read", || {
            sys.pci
                .frames()
                .iter()
                .filter(|frame| frame.payload == "4605001B030002")
                .count()
                >= 2
        })
        .await;
        sys.pci.inject(&pci_wire(&[
            0x86, 5, 0x10, 0x01, 0x00, 0x83, 0x00, 0x11, 0x22,
        ]));
        require(COMMAND_DRAIN, "OEM PP save pre-read selector", || {
            sys.pci
                .frames()
                .iter()
                .filter(|frame| frame.payload.starts_with("46050900A400411000"))
                .count()
                >= 2
        })
        .await;
        sys.pci
            .inject(&pci_wire(&[0x86, 5, 0x10, 0x01, 0x00, 0x32, 0x00, 0x41]));
        require(COMMAND_DRAIN, "OEM PP save pre-read", || {
            sys.pci
                .frames()
                .iter()
                .filter(|frame| frame.payload.starts_with("460509001A0105"))
                .count()
                >= 2
        })
        .await;
        sys.pci.inject(&pci_wire(&[
            0x86, 5, 0x10, 0x01, 0x00, 0x86, 0x01, 0xa1, 0x77, 0xb2, 0x88, 0xc3,
        ]));

        require(COMMAND_DRAIN, "GIU PP save pre-read selector", || {
            sys.pci
                .frames()
                .iter()
                .filter(|frame| frame.payload.starts_with("46050900A400413000"))
                .count()
                >= 2
        })
        .await;
        sys.pci
            .inject(&pci_wire(&[0x86, 5, 0x10, 0x01, 0x00, 0x32, 0x00, 0x41]));
        require(COMMAND_DRAIN, "GIU PP save pre-read", || {
            sys.pci
                .frames()
                .iter()
                .filter(|frame| frame.payload.starts_with("460509001A0101"))
                .count()
                >= 2
        })
        .await;
        sys.pci
            .inject(&pci_wire(&[0x86, 5, 0x10, 0x01, 0x00, 0x82, 0x01, 0x44]));

        require(COMMAND_DRAIN, "GOC2 PP save pre-read selector", || {
            sys.pci
                .frames()
                .iter()
                .filter(|frame| frame.payload.starts_with("460500A4FF420040"))
                .count()
                >= 2
        })
        .await;
        sys.pci
            .inject(&pci_wire(&[0x86, 5, 0x10, 0x01, 0x00, 0x32, 0xff, 0x42]));
        require(COMMAND_DRAIN, "GOC2 PP save pre-read", || {
            sys.pci
                .frames()
                .iter()
                .filter(|frame| frame.payload.starts_with("4605001AFF02"))
                .count()
                >= 2
        })
        .await;
        sys.pci.inject(&pci_wire(&[
            0x86, 5, 0x10, 0x01, 0x00, 0x83, 0xff, 0x45, 0x46,
        ]));

        require(COMMAND_DRAIN, "standard PP STORE", || {
            sys.pci
                .frames()
                .iter()
                .any(|frame| frame.payload.starts_with("460500A420005678"))
        })
        .await;
        sys.pci
            .inject(&pci_wire(&[0x86, 5, 0x10, 0x01, 0x00, 0x32, 0x20, 0x00]));
        require(COMMAND_DRAIN, "standard PP STORE readback", || {
            sys.pci
                .frames()
                .iter()
                .filter(|frame| frame.payload.starts_with("4605001A2002"))
                .count()
                >= 2
        })
        .await;
        sys.pci.inject(&pci_wire(&[
            0x86, 5, 0x10, 0x01, 0x00, 0x83, 0x20, 0x56, 0x78,
        ]));

        require(COMMAND_DRAIN, "locked PP unlock", || {
            sys.pci
                .frames()
                .iter()
                .any(|frame| frame.payload.starts_with("4605001122") && frame.conf.is_some())
        })
        .await;
        sys.pci
            .inject(&pci_wire(&[0x86, 5, 0x10, 0x01, 0x00, 0x82, 0x22, 0x5a]));
        require(COMMAND_DRAIN, "locked PP STORE", || {
            sys.pci
                .frames()
                .iter()
                .any(|frame| frame.payload.starts_with("460500A32200BC"))
        })
        .await;
        sys.pci
            .inject(&pci_wire(&[0x86, 5, 0x10, 0x01, 0x00, 0x32, 0x22, 0x00]));
        require(COMMAND_DRAIN, "locked PP STORE readback", || {
            sys.pci
                .frames()
                .iter()
                .filter(|frame| frame.payload.starts_with("4605001A2201"))
                .count()
                >= 2
        })
        .await;
        sys.pci
            .inject(&pci_wire(&[0x86, 5, 0x10, 0x01, 0x00, 0x82, 0x22, 0xbc]));

        require(COMMAND_DRAIN, "paged PP page 1 selection", || {
            sys.pci
                .frames()
                .iter()
                .any(|frame| frame.payload == "4605003901")
        })
        .await;
        sys.pci
            .inject(&pci_wire(&[0x86, 5, 0x10, 0x01, 0x00, 0x81, 0x01]));
        require(COMMAND_DRAIN, "paged PP first STORE", || {
            sys.pci
                .frames()
                .iter()
                .any(|frame| frame.payload.starts_with("460500A4FE000102"))
        })
        .await;
        sys.pci
            .inject(&pci_wire(&[0x86, 5, 0x10, 0x01, 0x00, 0x32, 0xfe, 0x00]));
        require(COMMAND_DRAIN, "paged PP page 2 selection", || {
            sys.pci
                .frames()
                .iter()
                .any(|frame| frame.payload == "4605003902")
        })
        .await;
        sys.pci
            .inject(&pci_wire(&[0x86, 5, 0x10, 0x01, 0x00, 0x81, 0x02]));
        require(COMMAND_DRAIN, "paged PP second STORE", || {
            sys.pci
                .frames()
                .iter()
                .any(|frame| frame.payload.starts_with("460500A400010304"))
        })
        .await;
        sys.pci
            .inject(&pci_wire(&[0x86, 5, 0x10, 0x01, 0x00, 0x32, 0x00, 0x01]));
        require(COMMAND_DRAIN, "paged PP first readback", || {
            sys.pci
                .frames()
                .iter()
                .filter(|frame| frame.payload == "4605001B01FE02")
                .count()
                >= 3
        })
        .await;
        sys.pci.inject(&pci_wire(&[
            0x86, 5, 0x10, 0x01, 0x00, 0x83, 0xfe, 0x01, 0x02,
        ]));
        require(COMMAND_DRAIN, "paged PP second readback", || {
            sys.pci
                .frames()
                .iter()
                .filter(|frame| frame.payload == "4605001B020002")
                .count()
                >= 3
        })
        .await;
        sys.pci.inject(&pci_wire(&[
            0x86, 5, 0x10, 0x01, 0x00, 0x83, 0x00, 0x03, 0x04,
        ]));

        require(COMMAND_DRAIN, "NCC PP page selection", || {
            sys.pci
                .frames()
                .iter()
                .any(|frame| frame.payload == "4605003903")
        })
        .await;
        sys.pci
            .inject(&pci_wire(&[0x86, 5, 0x10, 0x01, 0x00, 0x81, 0x03]));
        require(COMMAND_DRAIN, "NCC PP STORE", || {
            sys.pci
                .frames()
                .iter()
                .any(|frame| frame.payload.starts_with("460500A400000506"))
        })
        .await;
        sys.pci
            .inject(&pci_wire(&[0x86, 5, 0x10, 0x01, 0x00, 0x32, 0x00, 0x00]));
        require(COMMAND_DRAIN, "NCC PP readback", || {
            sys.pci
                .frames()
                .iter()
                .filter(|frame| frame.payload == "4605001B030002")
                .count()
                >= 3
        })
        .await;
        sys.pci.inject(&pci_wire(&[
            0x86, 5, 0x10, 0x01, 0x00, 0x83, 0x00, 0x05, 0x06,
        ]));

        require(COMMAND_DRAIN, "OEM PP STORE selector", || {
            sys.pci
                .frames()
                .iter()
                .filter(|frame| frame.payload.starts_with("46050900A400411000"))
                .count()
                >= 3
        })
        .await;
        sys.pci
            .inject(&pci_wire(&[0x86, 5, 0x10, 0x01, 0x00, 0x32, 0x00, 0x41]));
        require(COMMAND_DRAIN, "OEM PP STORE data", || {
            sys.pci
                .frames()
                .iter()
                .any(|frame| frame.payload.starts_with("46050900A701422177328813"))
        })
        .await;
        sys.pci
            .inject(&pci_wire(&[0x86, 5, 0x10, 0x01, 0x00, 0x32, 0x01, 0x42]));
        require(COMMAND_DRAIN, "OEM PP STORE readback selector", || {
            sys.pci
                .frames()
                .iter()
                .filter(|frame| frame.payload.starts_with("46050900A400411000"))
                .count()
                >= 4
        })
        .await;
        sys.pci
            .inject(&pci_wire(&[0x86, 5, 0x10, 0x01, 0x00, 0x32, 0x00, 0x41]));
        require(COMMAND_DRAIN, "OEM PP STORE readback", || {
            sys.pci
                .frames()
                .iter()
                .filter(|frame| frame.payload.starts_with("460509001A0105"))
                .count()
                >= 3
        })
        .await;
        sys.pci.inject(&pci_wire(&[
            0x86, 5, 0x10, 0x01, 0x00, 0x86, 0x01, 0x21, 0x77, 0x32, 0x88, 0x13,
        ]));

        require(COMMAND_DRAIN, "GIU PP halt", || {
            sys.pci
                .frames()
                .iter()
                .any(|frame| frame.payload.starts_with("46050900A3FC0300"))
        })
        .await;
        sys.pci
            .inject(&pci_wire(&[0x86, 5, 0x10, 0x01, 0x00, 0x32, 0xfc, 0x03]));
        require(COMMAND_DRAIN, "GIU PP STORE selector", || {
            sys.pci
                .frames()
                .iter()
                .filter(|frame| frame.payload.starts_with("46050900A400413000"))
                .count()
                >= 3
        })
        .await;
        sys.pci
            .inject(&pci_wire(&[0x86, 5, 0x10, 0x01, 0x00, 0x32, 0x00, 0x41]));
        require(COMMAND_DRAIN, "GIU PP STORE data", || {
            sys.pci
                .frames()
                .iter()
                .any(|frame| frame.payload.starts_with("46050900A3014255"))
        })
        .await;
        sys.pci
            .inject(&pci_wire(&[0x86, 5, 0x10, 0x01, 0x00, 0x32, 0x01, 0x42]));
        require(COMMAND_DRAIN, "GIU PP resume", || {
            sys.pci
                .frames()
                .iter()
                .any(|frame| frame.payload.starts_with("46050900A3FC0301"))
        })
        .await;
        sys.pci
            .inject(&pci_wire(&[0x86, 5, 0x10, 0x01, 0x00, 0x32, 0xfc, 0x03]));
        require(COMMAND_DRAIN, "GIU PP readback selector", || {
            sys.pci
                .frames()
                .iter()
                .filter(|frame| frame.payload.starts_with("46050900A400413000"))
                .count()
                >= 4
        })
        .await;
        sys.pci
            .inject(&pci_wire(&[0x86, 5, 0x10, 0x01, 0x00, 0x32, 0x00, 0x41]));
        require(COMMAND_DRAIN, "GIU PP readback", || {
            sys.pci
                .frames()
                .iter()
                .filter(|frame| frame.payload.starts_with("460509001A0101"))
                .count()
                >= 3
        })
        .await;
        sys.pci
            .inject(&pci_wire(&[0x86, 5, 0x10, 0x01, 0x00, 0x82, 0x01, 0x55]));

        require(COMMAND_DRAIN, "GOC2 PP STORE", || {
            sys.pci
                .frames()
                .iter()
                .any(|frame| frame.payload.starts_with("460500A6FF0000406677"))
        })
        .await;
        sys.pci
            .inject(&pci_wire(&[0x86, 5, 0x10, 0x01, 0x00, 0x32, 0xff, 0x00]));
        require(COMMAND_DRAIN, "GOC2 PP readback selector", || {
            sys.pci
                .frames()
                .iter()
                .filter(|frame| frame.payload.starts_with("460500A4FF420040"))
                .count()
                >= 3
        })
        .await;
        sys.pci
            .inject(&pci_wire(&[0x86, 5, 0x10, 0x01, 0x00, 0x32, 0xff, 0x42]));
        require(COMMAND_DRAIN, "GOC2 PP readback", || {
            sys.pci
                .frames()
                .iter()
                .filter(|frame| frame.payload.starts_with("4605001AFF02"))
                .count()
                >= 3
        })
        .await;
        sys.pci.inject(&pci_wire(&[
            0x86, 5, 0x10, 0x01, 0x00, 0x83, 0xff, 0x66, 0x77,
        ]));

        require(COMMAND_DRAIN, "C-Bus 3 Save-to-NVM EXECUTE", || {
            sys.pci
                .frames()
                .iter()
                .any(|frame| frame.payload == "460500E3810004" && frame.conf.is_none())
        })
        .await;
        // The same PCI remains the live MQTT feed during the NVM operation.
        sys.pci.inject(&pci_wire(&[5, 4, 56, 0, 121, 2]));
        sys.pci.inject(&pci_wire(&[
            0x86, 5, 0x10, 0x01, 0x00, 0xe4, 0x83, 0x00, 0x04, 0x01,
        ]));
        require(COMMAND_DRAIN, "C-Bus 3 Save-to-NVM first POLL", || {
            sys.pci
                .frames()
                .iter()
                .any(|frame| frame.payload == "460500E3820004" && frame.conf.is_none())
        })
        .await;
        sys.pci.inject(&pci_wire(&[
            0x86, 5, 0x10, 0x01, 0x00, 0xe4, 0x83, 0x00, 0x04, 0x01,
        ]));
        require(COMMAND_DRAIN, "C-Bus 3 Save-to-NVM completion POLL", || {
            sys.pci
                .frames()
                .iter()
                .filter(|frame| frame.payload == "460500E3820004" && frame.conf.is_none())
                .count()
                >= 2
        })
        .await;
        sys.pci.inject(&pci_wire(&[
            0x86, 5, 0x10, 0x01, 0x00, 0xe4, 0x83, 0x00, 0x04, 0x00,
        ]));
    };
    let (saved, ()) = tokio::join!(save, save_responses);
    assert!(saved.contains("200 OK"), "{saved:?}");
    require(STARTUP, "lighting event in MQTT during Save-to-NVM", || {
        sys.broker
            .publishes()
            .iter()
            .any(|publish| publish.topic == "homeassistant/light/cbus_2/state")
    })
    .await;
    let nvm_executes = sys
        .pci
        .frames()
        .iter()
        .filter(|frame| frame.payload == "460500E3810004" && frame.conf.is_none())
        .count();
    assert_eq!(nvm_executes, 1);

    let standard_reads = sys
        .pci
        .frames()
        .iter()
        .filter(|frame| frame.payload.starts_with("4605001A2002"))
        .count();
    let memory_selectors = sys
        .pci
        .frames()
        .iter()
        .filter(|frame| frame.payload.starts_with("46050900A400411000"))
        .count();
    let standard_stores = sys
        .pci
        .frames()
        .iter()
        .filter(|frame| frame.payload.starts_with("460500A420005678"))
        .count();
    let memory_stores = sys
        .pci
        .frames()
        .iter()
        .filter(|frame| frame.payload.starts_with("46050900A701422177328813"))
        .count();
    let unlocks = sys
        .pci
        .frames()
        .iter()
        .filter(|frame| frame.payload.starts_with("4605001122"))
        .count();
    let locked_stores = sys
        .pci
        .frames()
        .iter()
        .filter(|frame| frame.payload.starts_with("460500A32200BC"))
        .count();
    let page_selections = sys
        .pci
        .frames()
        .iter()
        .filter(|frame| frame.payload.starts_with("46050039"))
        .count();
    let paged_stores = sys
        .pci
        .frames()
        .iter()
        .filter(|frame| {
            frame.payload.starts_with("460500A4FE000102")
                || frame.payload.starts_with("460500A400010304")
                || frame.payload.starts_with("460500A400000506")
        })
        .count();
    let giu_stores = sys
        .pci
        .frames()
        .iter()
        .filter(|frame| frame.payload.starts_with("46050900A3014255"))
        .count();
    let goc_stores = sys
        .pci
        .frames()
        .iter()
        .filter(|frame| frame.payload.starts_with("460500A6FF0000406677"))
        .count();
    let save_again = command(&mut reader, &mut writer, "PP SAVE_TO_SOURCE S Core");
    let identity_responses = async {
        for (attribute, data) in [(1, b"TESTUNIT".as_slice()), (2, b"1.2.03".as_slice())] {
            let prefix = format!("46050021{attribute:02X}");
            require(COMMAND_DRAIN, "unchanged PP SAVE identity", || {
                sys.pci
                    .frames()
                    .iter()
                    .filter(|frame| frame.payload.starts_with(&prefix))
                    .count()
                    >= 3
            })
            .await;
            let mut body = vec![
                0x86,
                5,
                0x10,
                0x01,
                0x00,
                0x80 | (data.len() as u8 + 1),
                attribute,
            ];
            body.extend_from_slice(data);
            sys.pci.inject(&pci_wire(&body));
        }
    };
    let (saved_again, ()) = tokio::join!(save_again, identity_responses);
    assert!(saved_again.contains("200 OK"), "{saved_again:?}");
    let frames = sys.pci.frames();
    assert_eq!(
        frames
            .iter()
            .filter(|frame| frame.payload.starts_with("4605001A2002"))
            .count(),
        standard_reads
    );
    assert_eq!(
        frames
            .iter()
            .filter(|frame| frame.payload.starts_with("46050900A400411000"))
            .count(),
        memory_selectors
    );
    assert_eq!(
        frames
            .iter()
            .filter(|frame| frame.payload.starts_with("460500A420005678"))
            .count(),
        standard_stores
    );
    assert_eq!(
        frames
            .iter()
            .filter(|frame| frame.payload.starts_with("46050900A701422177328813"))
            .count(),
        memory_stores
    );
    assert_eq!(
        frames
            .iter()
            .filter(|frame| frame.payload.starts_with("4605001122"))
            .count(),
        unlocks
    );
    assert_eq!(
        frames
            .iter()
            .filter(|frame| frame.payload.starts_with("460500A32200BC"))
            .count(),
        locked_stores
    );
    assert_eq!(
        frames
            .iter()
            .filter(|frame| frame.payload.starts_with("46050039"))
            .count(),
        page_selections
    );
    assert_eq!(
        frames
            .iter()
            .filter(|frame| {
                frame.payload.starts_with("460500A4FE000102")
                    || frame.payload.starts_with("460500A400010304")
                    || frame.payload.starts_with("460500A400000506")
            })
            .count(),
        paged_stores
    );
    assert_eq!(
        frames
            .iter()
            .filter(|frame| frame.payload.starts_with("46050900A3014255"))
            .count(),
        giu_stores
    );
    assert_eq!(
        frames
            .iter()
            .filter(|frame| frame.payload.starts_with("460500A6FF0000406677"))
            .count(),
        goc_stores
    );
    assert_eq!(
        frames
            .iter()
            .filter(|frame| frame.payload == "460500E3810004" && frame.conf.is_none())
            .count(),
        nvm_executes
    );
    assert_eq!(sys.pci.connections(), 1);

    drop(sys);
    std::fs::remove_file(state).unwrap();
    std::fs::remove_dir_all(specs).unwrap();
}
