//! Real cmqttd process: a physical move interrupted after its STORE reached
//! the PCI leaves a durable journal. The restarted daemon refuses new moves
//! on that network until a read-only verification and an explicit clear.

mod util;

use std::path::Path;
use tokio::{
    io::{AsyncBufReadExt, AsyncWriteExt, BufReader},
    net::{tcp::OwnedReadHalf, tcp::OwnedWriteHalf, TcpStream},
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
    let mut states = vec![0u8; count];
    for address in present {
        states[*address - usize::from(start)] = 1;
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

async fn start(state: &Path, project: &Path) -> System {
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
    sys
}

async fn connect(sys: &System) -> (BufReader<OwnedReadHalf>, OwnedWriteHalf) {
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
    let (reader, writer) = stream.into_split();
    let mut reader = BufReader::new(reader);
    let mut greeting = String::new();
    reader.read_line(&mut greeting).await.unwrap();
    assert!(greeting.starts_with("201 "), "{greeting:?}");
    (reader, writer)
}

async fn send(writer: &mut OwnedWriteHalf, tag: &str, text: &str) {
    writer
        .write_all(format!("[{tag}] {text}\r\n").as_bytes())
        .await
        .unwrap();
}

/// Tagged response lines through the final status line.
async fn response(reader: &mut BufReader<OwnedReadHalf>, tag: &str) -> Vec<String> {
    let prefix = format!("[{tag}] ");
    let mut lines = Vec::new();
    loop {
        let mut line = String::new();
        assert_ne!(reader.read_line(&mut line).await.unwrap(), 0);
        let Some(payload) = line.trim_end().strip_prefix(&prefix) else {
            continue;
        };
        let last = payload.as_bytes().get(3) == Some(&b' ');
        lines.push(payload.to_string());
        if last {
            return lines;
        }
    }
}

async fn command(
    reader: &mut BufReader<OwnedReadHalf>,
    writer: &mut OwnedWriteHalf,
    tag: &str,
    text: &str,
) -> Vec<String> {
    send(writer, tag, text).await;
    response(reader, tag).await
}

fn json_line(lines: &[String]) -> serde_json::Value {
    let line = lines
        .iter()
        .find_map(|line| line.get(4..).filter(|body| body.starts_with('{')))
        .unwrap_or_else(|| panic!("no JSON line in {lines:?}"));
    serde_json::from_str(line).unwrap()
}

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
    wait_for_payload(sys, "installation MMI request", "05FF00FAFF", occurrence).await;
    for (start, count) in [(0, 88), (88, 88), (176, 80)] {
        let block = present
            .iter()
            .copied()
            .filter(|address| (start..start + count).contains(address))
            .collect::<Vec<_>>();
        sys.pci
            .inject(&installation_mmi_block(start as u8, count, &block));
    }
}

async fn answer_identity(sys: &System, address: u8, occurrence: usize, serials: &[&str]) {
    let prefix = format!("46{address:02X}002104");
    wait_for_payload(sys, "IDENTIFY4 request", &prefix, occurrence).await;
    for serial in serials {
        let mut body = vec![0x86, address, 0x10, 0x00, 0x8d, 4];
        body.extend_from_slice(&serial_identity(serial, address));
        sys.pci.inject(&pci_wire(&body));
    }
}

#[tokio::test]
async fn killed_unravel_after_store_is_refused_on_restart_until_verify_and_clear() {
    let state = cbus_test_support::proc::temp_path("move-journal-cgate.json");
    let project = cbus_test_support::proc::temp_path("move-journal-project.xml");
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
    let store =
        cbus_protocol::serial_address::encode_serial_address("101136.1559", 7, true, b'g').unwrap();
    let store = std::str::from_utf8(&store[1..store.len() - 2])
        .unwrap()
        .to_string();

    // First daemon: run the preflight, then kill -9 once the first
    // selected-serial STORE is on the PCI wire.
    let mut sys = start(&state, &project).await;
    let (_reader, mut writer) = connect(&sys).await;
    send(
        &mut writer,
        "1",
        "NET UNRAVELUNIT //HARNESS/254 255 MATCHDB",
    )
    .await;
    inject_mmi(&sys, 1, &[16, 255]).await;
    answer_identity(&sys, 16, 1, &["100966.1187"]).await;
    answer_identity(&sys, 255, 1, &["101136.1558", "101136.1559"]).await;
    wait_for_payload(&sys, "local PCI option request", "4610001A4201", 1).await;
    sys.pci
        .inject(&pci_wire(&[0x86, 16, 0x10, 0x00, 0x82, 0x42, 5]));
    // Native order: descending numeric serial, so 101136.1559 moves first.
    answer_identity(&sys, 7, 1, &[]).await;
    answer_identity(&sys, 6, 1, &[]).await;
    wait_for_payload(&sys, "selected-serial STORE", &store, 1).await;
    sys.daemon.signal("KILL");
    assert!(sys.daemon.wait_exit(STARTUP).await.is_some());
    drop(sys);

    // Restarted daemon on the same state path.
    let sys = start(&state, &project).await;
    assert!(
        sys.daemon
            .stderr()
            .contains("incomplete physical move journal"),
        "startup must report the incomplete journal"
    );
    let (mut reader, mut writer) = connect(&sys).await;
    let listed = command(&mut reader, &mut writer, "2", "CMQTT MOVE-JOURNAL LIST").await;
    let listed = json_line(&listed);
    let id = listed["incomplete"][0].as_str().unwrap().to_string();
    assert_eq!(listed["blocked_networks"], serde_json::json!([254]));
    assert_eq!(listed["journals"][0]["send_may_have_occurred"], true);

    for (tag, text) in [
        ("3", "NET UNRAVELUNIT //HARNESS/254 255 MATCHDB"),
        ("4", "SET //HARNESS/254/p/5 Address 9"),
    ] {
        let refused = command(&mut reader, &mut writer, tag, text).await;
        let last = refused.last().unwrap();
        assert!(
            last.starts_with("409 ") && last.contains(&id),
            "{refused:?}"
        );
    }
    let capabilities = command(&mut reader, &mut writer, "5", "CMQTT CAPABILITIES").await;
    assert_eq!(
        json_line(&capabilities)["move_journal_blocked_networks"],
        serde_json::json!([254])
    );
    let early = command(
        &mut reader,
        &mut writer,
        "6",
        &format!("CMQTT MOVE-JOURNAL CLEAR {id}"),
    )
    .await;
    assert!(early.last().unwrap().starts_with("409 "), "{early:?}");
    // Nothing physical was attempted by the refused commands.
    assert!(
        sys.pci
            .frames()
            .iter()
            .all(|frame| !frame.payload.starts_with("05FF00FAFF")),
        "refused commands must not reach the PCI"
    );

    // Read-only verification: the first unit moved before the kill.
    send(&mut writer, "7", &format!("CMQTT MOVE-JOURNAL VERIFY {id}")).await;
    inject_mmi(&sys, 1, &[7, 16, 255]).await;
    answer_identity(&sys, 7, 1, &["101136.1559"]).await;
    answer_identity(&sys, 16, 1, &["100966.1187"]).await;
    answer_identity(&sys, 255, 1, &["101136.1558"]).await;
    let verified = response(&mut reader, "7").await;
    assert!(verified.last().unwrap().starts_with("200 "), "{verified:?}");
    let verified = json_line(&verified);
    assert_eq!(verified["outcome"], "observed_mixed");
    assert_eq!(verified["moved"], serde_json::json!([true, false]));
    assert_eq!(verified["replay_authorized"], false);
    assert!(
        sys.pci
            .frames()
            .iter()
            .all(|frame| !frame.payload.starts_with("05FF000F00")),
        "verification must never send an address request"
    );

    let cleared = command(
        &mut reader,
        &mut writer,
        "8",
        &format!("CMQTT MOVE-JOURNAL CLEAR {id}"),
    )
    .await;
    assert!(cleared.last().unwrap().starts_with("200 "), "{cleared:?}");
    let capabilities = command(&mut reader, &mut writer, "9", "CMQTT CAPABILITIES").await;
    assert_eq!(
        json_line(&capabilities)["move_journal_blocked_networks"],
        serde_json::json!([])
    );
    drop(sys);
    let journal_dir = state.with_file_name(format!(
        "{}.move-journal",
        state.file_name().unwrap().to_string_lossy()
    ));
    std::fs::remove_dir_all(journal_dir).unwrap();
    std::fs::remove_file(state).unwrap();
    std::fs::remove_file(project).unwrap();
}
