//! Large retained backups through the real daemon, with a fresh process
//! readback and continued MQTT delivery against independently scripted PCI.
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
        let payload = line.strip_prefix(&prefix).expect("tagged response");
        let done = payload.as_bytes().get(3) == Some(&b' ');
        reply.push(line);
        if done {
            return reply;
        }
    }
}

fn xml(reply: &[String]) -> String {
    reply
        .iter()
        .filter_map(|line| line.split_once("347-").map(|(_, text)| text))
        .collect::<Vec<_>>()
        .join("\n")
}

#[tokio::test]
async fn sixteen_large_saved_backups_survive_process_restart_and_mqtt_remains_live() {
    let project = cbus_test_support::proc::temp_path("capacity-project.xml");
    let state = cbus_test_support::proc::temp_path("capacity-state.json");
    let payload = "0123456789abcdef".repeat(4 * 1024);
    let units = (5..9).map(|address| format!(r#"<Unit><Address>{address}</Address><TagName>Synthetic</TagName><UnitType>KEYGL5</UnitType><FirmwareVersion>5.5.00</FirmwareVersion><PP Name="PayloadA" Value="{payload}"/><PP Name="PayloadB" Value="{payload}"/><Opaque>kept</Opaque></Unit>"#)).collect::<String>();
    std::fs::write(&project,format!(r#"<Installation><Project><TagName>CAPACITY</TagName><Network><Address>254</Address><TagName>Local</TagName><Interface><InterfaceType>CNI</InterfaceType><InterfaceAddress>127.0.0.1:10001</InterfaceAddress></Interface><Application><Address>56</Address><TagName>Lighting</TagName><Group><Address>1</Address><TagName>Fixture</TagName></Group></Application>{units}</Network></Project></Installation>"#)).unwrap();
    let mut source = String::new();
    for epoch in 0..2 {
        let mut sys = start_with(Options {
            project: false,
            extra: vec![
                "-P".into(),
                project.to_string_lossy().into_owned(),
                "-S".into(),
                "0".into(),
                "--no-clock".into(),
                "--cgate-bind".into(),
                "127.0.0.1:0".into(),
                "--cgate-state".into(),
                state.to_string_lossy().into_owned(),
            ],
            ..Default::default()
        })
        .await;
        wait_started(&sys).await;
        require(STARTUP, "C-Gate capacity listener", || {
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
        let capabilities = command(&mut reader, &mut writer, "cap", "CMQTT CAPABILITIES").await;
        let value: serde_json::Value = serde_json::from_str(
            capabilities
                .iter()
                .find_map(|line| line.split_once("200-").map(|(_, text)| text))
                .unwrap(),
        )
        .unwrap();
        let expected: serde_json::Value = serde_json::from_str(include_str!(
            "../../testdata/vectors/cgate_repository_storage.json"
        ))
        .unwrap();
        for (key, expected) in expected.as_object().unwrap() {
            assert_eq!(&value[key], expected, "capability {key}");
        }
        if epoch == 0 {
            source = xml(&command(
                &mut reader,
                &mut writer,
                "source",
                "DBGETXML //CAPACITY/254",
            )
            .await);
            assert!(source.contains("retained") || source.contains("kept"));
        }
        // Startup independently queues exactly this configured application
        // sweep even with periodic resync disabled. Finish that known work
        // before proving the repository commands emit no PCI traffic.
        require(STARTUP, "configured application startup sweep", || {
            sys.pci.count_payload("05FF007A38004A") == 1
                && sys.pci.count_payload("05FF00730738004A") == 1
        })
        .await;
        let pci_before = sys.pci.frames().len();
        for index in 0..16 {
            let backup = format!("BACKUP{index:02}");
            if epoch == 0 {
                let copied = command(
                    &mut reader,
                    &mut writer,
                    "copy",
                    &format!("PROJECT COPY CAPACITY {backup}"),
                )
                .await;
                assert_eq!(copied.last().unwrap(), "[copy] 200 OK.");
                let saved = command(
                    &mut reader,
                    &mut writer,
                    "save",
                    &format!("PROJECT SAVE {backup}"),
                )
                .await;
                assert_eq!(saved.last().unwrap(), "[save] 200 OK");
            } else {
                let loaded = command(
                    &mut reader,
                    &mut writer,
                    "load",
                    &format!("PROJECT LOAD {backup}"),
                )
                .await;
                assert_eq!(loaded.last().unwrap(), "[load] 200 OK.");
            }
            let selected = command(
                &mut reader,
                &mut writer,
                "use",
                &format!("PROJECT USE {backup}"),
            )
            .await;
            assert_eq!(selected.last().unwrap(), "[use] 200 OK.");
            let readback = command(
                &mut reader,
                &mut writer,
                "xml",
                &format!("DBGETXML //{backup}/254"),
            )
            .await;
            assert_eq!(readback.last().unwrap(), "[xml] 344 End XML snippet");
            assert_eq!(xml(&readback), source);
        }
        assert_eq!(
            sys.pci.frames().len(),
            pci_before,
            "repository workflow performs no PCI I/O"
        );
        let bytes = std::fs::metadata(&state).unwrap().len();
        assert!(bytes > 32 * 1024 * 1024);
        assert!(bytes <= 256 * 1024 * 1024);
        let light = "053800790149";
        let count = sys.pci.count_payload(light);
        sys.broker
            .inject("homeassistant/light/cbus_1/set", br#"{"state":"ON"}"#);
        require(
            COMMAND_DRAIN,
            "MQTT confirmed lighting after large repository work",
            || sys.pci.count_payload(light) > count,
        )
        .await;
        assert!(sys.daemon.is_running());
        println!("daemon capacity epoch {epoch}: sixteen simultaneous backups; {bytes} serialized bytes; full graph readback and MQTT delivery passed");
        drop(reader);
        drop(writer);
        drop(sys);
    }
    std::fs::remove_file(state).unwrap();
    std::fs::remove_file(project).unwrap();
}
