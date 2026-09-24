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
