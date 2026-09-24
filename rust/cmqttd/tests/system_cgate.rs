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
    assert!(command(&mut reader, &mut writer, "NET SYNC //HARNESS/254")
        .await
        .contains("502 Command requires"));
    drop(sys);
    std::fs::remove_file(path).unwrap();
}
