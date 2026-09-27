//! Administrative C-Gate operations remain local and leave the shared MQTT
//! and PCI command path operational.

mod util;

use tokio::{
    io::{AsyncBufReadExt, AsyncWriteExt, BufReader},
    net::TcpStream,
};
use util::*;

async fn command(
    reader: &mut BufReader<tokio::net::tcp::OwnedReadHalf>,
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
        assert_ne!(reader.read_line(&mut line).await.unwrap(), 0);
        let line = line.trim_end_matches(['\r', '\n']).to_string();
        let payload = line.strip_prefix(&prefix).expect("tagged C-Gate reply");
        let complete = payload.as_bytes().get(3) == Some(&b' ');
        reply.push(line);
        if complete {
            return reply;
        }
    }
}

#[tokio::test]
async fn administrative_documents_and_mqtt_share_the_running_daemon() {
    let state = cbus_test_support::proc::temp_path("cgate-admin.json");
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

    for (tag, text) in [
        ("1", "PROJECT NEW AUX"),
        ("2", "PROJECT ARCHIVE AUX cmqttd:internal-slot"),
        ("3", "PROJECT RENAME AUX AUX2"),
        ("4", "PROJECT RESTORE AUX3 cmqttd:internal-slot"),
        ("5", "PROJECT USE HARNESS"),
    ] {
        let reply = command(&mut reader, &mut writer, tag, text).await;
        assert!(
            reply.last().unwrap().contains("200 OK"),
            "{text}: {reply:?}"
        );
    }
    let repository = command(&mut reader, &mut writer, "6", "REPOSITORY LIST").await;
    assert_eq!(repository.len(), 1);
    assert!(repository[0].contains("123 index=1 type=cmqttd-json path="));
    assert!(repository[0].ends_with(" current=yes"));

    assert!(command(&mut reader, &mut writer, "7", "PROJECT USE AUX2")
        .await
        .last()
        .unwrap()
        .contains("200 OK"));
    assert!(command(
        &mut reader,
        &mut writer,
        "8",
        "DBCREATENET 1 Auxiliary Cni loopback",
    )
    .await
    .last()
    .unwrap()
    .contains("200 OK"));
    let added = command(&mut reader, &mut writer, "9", "DBADD 1 Application").await;
    let application_oid = added
        .last()
        .unwrap()
        .split_once("301 OID=")
        .map(|(_, oid)| oid)
        .expect("application OID")
        .to_string();
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "10",
            &format!("DBSET !{application_oid}/Address 56"),
        )
        .await
        .last()
        .unwrap(),
        "[10] 200 OK."
    );
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "11",
            &format!("DBSET !{application_oid}/TagName Original"),
        )
        .await
        .last()
        .unwrap(),
        "[11] 200 OK."
    );
    let typed = concat!(
        "<Application><OID>70000000-0000-4000-8000-000000000001</OID>",
        "<TagName>Daemon typed</TagName><Address>58</Address>",
        "<Group><OID>70000000-0000-4000-8000-000000000002</OID>",
        "<TagName>Scenes</TagName><Address>10</Address>",
        "<Level Value=\"128\"><OID>70000000-0000-4000-8000-000000000003</OID>",
        "<TagName>Evening</TagName><Address>1</Address></Level></Group></Application>"
    );
    writer
        .write_all(
            format!("[12] DBSETXML !{application_oid} << END_TYPED\r\n{typed}\r\nEND_TYPED\r\n")
                .as_bytes(),
        )
        .await
        .unwrap();
    let mut typed_reply = String::new();
    reader.read_line(&mut typed_reply).await.unwrap();
    assert_eq!(
        typed_reply,
        "[12] 301 OID=70000000-0000-4000-8000-000000000001\r\n"
    );
    let typed_readback = command(&mut reader, &mut writer, "13", "DBGETXML //AUX2/1/58").await;
    assert!(typed_readback
        .iter()
        .any(|line| line.contains("<Level Value=\"128\">")));
    assert!(
        command(&mut reader, &mut writer, "14", "PROJECT USE HARNESS")
            .await
            .last()
            .unwrap()
            .contains("200 OK")
    );

    let before_network_document = sys.pci.payloads();
    let network = concat!(
        "<Network xmlns:x=\"urn:system-topology\"><OID>53000000-0000-4000-8000-000000000001</OID>",
        "<TagName>System topology</TagName><Address>254</Address><NetworkNumber>254</NetworkNumber>",
        "<Interface><OID>53000000-0000-4000-8000-000000000002</OID><InterfaceType>CNI</InterfaceType>",
        "<InterfaceAddress>127.0.0.1:10001</InterfaceAddress></Interface>",
        "<Unit x:source=\"system\"><OID>53000000-0000-4000-8000-000000000003</OID>",
        "<TagName>System unit</TagName><Address>5</Address><UnitType>KEYGL5</UnitType><UnitName>System unit</UnitName>",
        "<FirmwareVersion>5.5.00</FirmwareVersion><PP Name=\"StaticTextString0\" Value=\"System\"/>",
        "<!--kept--><x:Opaque>yes</x:Opaque></Unit></Network>"
    );
    writer
        .write_all(
            format!("[15] DBSETXML //HARNESS/254 << END_NETWORK\r\n{network}\r\nEND_NETWORK\r\n")
                .as_bytes(),
        )
        .await
        .unwrap();
    let mut network_reply = String::new();
    reader.read_line(&mut network_reply).await.unwrap();
    assert_eq!(
        network_reply,
        "[15] 301 OID=53000000-0000-4000-8000-000000000001\r\n"
    );
    let network_unit = command(&mut reader, &mut writer, "16", "DBGETXML //HARNESS/254/p/5").await;
    assert!(network_unit
        .iter()
        .any(|line| line.contains("xmlns:x=\"urn:system-topology\"")));
    assert!(network_unit
        .iter()
        .any(|line| line.contains("<x:Opaque>yes</x:Opaque>")));
    assert_eq!(sys.pci.payloads(), before_network_document);

    writer
        .write_all(b"[17] DBSETXML //HARNESS/254/p/5/TagName << END\r\nSystem document\r\nEND\r\n")
        .await
        .unwrap();
    let mut document_reply = String::new();
    reader.read_line(&mut document_reply).await.unwrap();
    assert_eq!(document_reply, "[17] 200 OK\r\n");

    let capabilities = command(&mut reader, &mut writer, "18", "CMQTT CAPABILITIES").await;
    let capabilities: serde_json::Value = serde_json::from_str(
        capabilities[0]
            .split_once(" 200-")
            .map(|(_, json)| json)
            .expect("capability JSON"),
    )
    .unwrap();
    assert_eq!(capabilities["database_document_network_units"], true);
    assert_eq!(
        capabilities["database_document_configured_network"],
        "same-address-same-interface-binding"
    );
    assert_eq!(capabilities["database_document_physical_io"], false);

    let payload = "053800790149";
    let before = sys.pci.count_payload(payload);
    sys.broker
        .inject("homeassistant/light/cbus_1/set", br#"{"state":"ON"}"#);
    require(
        COMMAND_DRAIN,
        "MQTT command after C-Gate administration",
        || sys.pci.count_payload(payload) > before,
    )
    .await;
    assert!(sys.daemon.is_running());
    drop(sys);
    std::fs::remove_file(state).unwrap();
}

#[tokio::test]
async fn native_family_help_is_exact_over_tcp_and_keeps_mqtt_live() {
    let evidence: serde_json::Value = serde_json::from_str(include_str!(
        "../../testdata/fixtures/native_cgate_family_help.json"
    ))
    .unwrap();
    let state = cbus_test_support::proc::temp_path("cgate-family-help.json");
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

    let mut id = 0_u32;
    for family in evidence["families"].as_array().unwrap() {
        let name = family["family"].as_str().unwrap();
        for text in [
            name.to_string(),
            format!("{name} ?"),
            format!("HELP {name}"),
        ] {
            id += 1;
            let tag = id.to_string();
            let expected = family["root"]
                .as_array()
                .unwrap()
                .iter()
                .map(|row| {
                    format!(
                        "[{tag}] 101{}{}",
                        if row["continuation"].as_bool().unwrap() {
                            '-'
                        } else {
                            ' '
                        },
                        row["text"].as_str().unwrap()
                    )
                })
                .collect::<Vec<_>>();
            assert_eq!(
                command(&mut reader, &mut writer, &tag, &text).await,
                expected,
                "{text}"
            );
        }
    }

    let payload = "053800790149";
    let before = sys.pci.count_payload(payload);
    sys.broker
        .inject("homeassistant/light/cbus_1/set", br#"{"state":"ON"}"#);
    require(COMMAND_DRAIN, "MQTT after family help", || {
        sys.pci.count_payload(payload) > before
    })
    .await;
    assert!(sys.daemon.is_running());
    drop(sys);
    std::fs::remove_file(state).unwrap();
}
