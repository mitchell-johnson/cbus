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
    };
    let (saved, ()) = tokio::join!(save, save_responses);
    assert!(saved.contains("200 OK"), "{saved:?}");

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
    assert_eq!(sys.pci.connections(), 1);

    drop(sys);
    std::fs::remove_file(state).unwrap();
    std::fs::remove_dir_all(specs).unwrap();
}
