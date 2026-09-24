//! Real daemon: C-Gate and MQTT share one PCI and observe the same bus reports.
mod util;
use tokio::{
    io::{AsyncBufReadExt, AsyncWriteExt, BufReader},
    net::TcpStream,
};
use util::*;

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
    assert!(
        command(&mut reader, &mut writer, "GET //HARNESS/254/56/1 level")
            .await
            .contains("408 No live level")
    );
    assert!(command(&mut reader, &mut writer, "ON //HARNESS/254/56/1")
        .await
        .contains("200 OK"));
    assert_eq!(sys.pci.count_payload("053800790149"), 1);
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
    let sync = command(&mut reader, &mut writer, "NET SYNC //HARNESS/254 fast");
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
    assert!(sync.contains("200 OK"), "{sync:?}");
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
    assert_eq!(sys.pci.connections(), 1);
    drop(sys);
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn physical_pp_load_decodes_standard_and_oem_memory_on_shared_pci() {
    let state = cbus_test_support::proc::temp_path("physical-pp-cgate.json");
    let specs = cbus_test_support::proc::temp_path("physical-pp-unitspec");
    std::fs::create_dir_all(&specs).unwrap();
    std::fs::write(
        specs.join("TESTUNIT.xml"),
        r#"<UnitSpecification><Parameters>
        <Param><Name>Standard</Name><Type>int</Type><Address>$20</Address><ArraySize>2</ArraySize><Tag>Core</Tag></Param>
        <Param><Name>Mapped</Name><Type>int</Type><Address>$110</Address><ArraySize>3</ArraySize><BitSize>4</BitSize><BitAddress>4</BitAddress><ArraySkip>1</ArraySkip><ArrayMap>2 3 1</ArrayMap><Tag>Core</Tag></Param>
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
        async fn identify(sys: &System, attribute: u8, data: &[u8]) {
            let prefix = format!("46050021{attribute:02X}");
            require(COMMAND_DRAIN, "physical PP IDENTIFY", || {
                sys.pci
                    .frames()
                    .iter()
                    .any(|frame| frame.payload.starts_with(&prefix))
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
    };
    let (loaded, ()) = tokio::join!(load, responses);
    assert!(loaded.contains("200 OK"), "{loaded:?}");
    let values = command(&mut reader, &mut writer, "PP GET S *").await;
    assert!(values.contains("315-Mapped=0xC 0xA 0xB"), "{values:?}");
    assert!(values.contains("315 Standard=0x12 0x34"), "{values:?}");
    assert!(!values.contains("Excluded="), "{values:?}");
    assert_eq!(sys.pci.connections(), 1);

    drop(sys);
    std::fs::remove_file(state).unwrap();
    std::fs::remove_dir_all(specs).unwrap();
}
