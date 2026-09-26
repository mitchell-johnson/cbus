//! Real cmqttd process: native C-Gate MEASUREMENT DATA shares the MQTT PCI,
//! uses the captured application-228 SAL, requires confirmation, and fans
//! observed samples out to event clients.

mod util;

use serde_json::json;
use tokio::{
    io::{AsyncBufReadExt, AsyncWriteExt, BufReader},
    net::TcpStream,
};
use util::*;

const TOKEN: &str = "throwaway-measurement-system-token-0123456789abcdef";

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

fn checksummed(native_payload: &str) -> String {
    let bytes = hex::decode(native_payload).unwrap();
    hex::encode_upper(cbus_protocol::common::add_cbus_checksum(&bytes))
}

#[tokio::test]
async fn measurement_native_family_is_confirmed_authenticated_and_keeps_mqtt_live() {
    let state = cbus_test_support::proc::temp_path("cgate-measurement.json");
    let token = cbus_test_support::proc::temp_path("cgate-measurement.token");
    std::fs::write(&token, format!("{TOKEN}\n")).unwrap();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&token, std::fs::Permissions::from_mode(0o600)).unwrap();
    }
    let mut sys = start_with(Options {
        extra: vec![
            "--cgate-bind".into(),
            "127.0.0.1:0".into(),
            "--cgate-state".into(),
            state.to_string_lossy().into_owned(),
            "--cgate-auth-file".into(),
            token.to_string_lossy().into_owned(),
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

    assert_eq!(
        command(&mut reader, &mut writer, "h", "MEASUREMENT ?").await,
        [
            "101-Help: MEASUREMENT commands:",
            "101-Help:  MEASUREMENT ? Help for these commands",
            "101 Help:  MEASUREMENT DATA - Channel Measurement Data produced by a Measurement Device",
        ]
    );
    let capabilities = command(&mut reader, &mut writer, "c", "CMQTT CAPABILITIES").await;
    assert!(capabilities[0].contains("\"measurement_control\":true"));
    assert!(capabilities[0].contains("\"measurement_application\":228"));
    assert!(capabilities[0].contains("\"measurement_event_fanout\":true"));
    assert!(capabilities[0].contains("\"measurement_mqtt_state\":false"));
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "missing-object",
            "GET //HARNESS/254/228 State"
        )
        .await
        .last()
        .unwrap(),
        "401 Bad object or device ID: //HARNESS/254/228 (Object not found)"
    );

    let sample = checksummed("05E4000E010102FE27FA");
    let before = sys.pci.count_payload(&sample);
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "locked",
            "MEASUREMENT DATA 254/228/1/1 10234 -2 2"
        )
        .await
        .last()
        .unwrap(),
        "420 LOGIN required"
    );
    assert_eq!(sys.pci.count_payload(&sample), before);
    assert_eq!(
        command(&mut reader, &mut writer, "login", &format!("LOGIN {TOKEN}"))
            .await
            .last()
            .unwrap(),
        "200 OK"
    );

    for (index, (text, native)) in [
        (
            "MEASUREMENT DATA 254/228/1/1 10234 -2 2",
            "05E4000E010102FE27FA",
        ),
        (
            "MEASUREMENT DATA //HARNESS/254/228/0/0 -32768 -128 0",
            "05E4000E000000808000",
        ),
        (
            "MEASUREMENT DATA 254/$E4/255/255 32767 127 255",
            "05E4000EFFFFFF7F7FFF",
        ),
        (
            "MEASUREMENT DATA 254/228/2/3 -1 -1 1",
            "05E4000E020301FFFFFF",
        ),
        (
            "MEASUREMENT DATA 254/228/1/1 $7FFF $7F $FF",
            "05E4000E0101FF7F7FFF",
        ),
    ]
    .into_iter()
    .enumerate()
    {
        let payload = checksummed(native);
        let before = sys.pci.count_payload(&payload);
        let reply = command(&mut reader, &mut writer, &index.to_string(), text).await;
        assert_eq!(reply.last().unwrap(), "200 OK.", "{text}: {reply:?}");
        assert_eq!(sys.pci.count_payload(&payload), before + 1, "{text}");
    }

    let invalid = [
        ("MEASUREMENT BOGUS", "400 Syntax Error."),
        (
            "MEASUREMENT DATA",
            "400 Syntax Error: Missing parameter : <channel>",
        ),
        (
            "MEASUREMENT DATA ?",
            "401 Bad object or device ID: ? (Network not found)",
        ),
        (
            "MEASUREMENT DATA 254/228/1/1",
            "400 Syntax Error: Missing parameter : <value>",
        ),
        (
            "MEASUREMENT DATA 254/228/1/1 1",
            "400 Syntax Error: Missing parameter : <multiplier>",
        ),
        (
            "MEASUREMENT DATA 254/228/1/1 1 0",
            "400 Syntax Error: Missing parameter : <units>",
        ),
        (
            "MEASUREMENT DATA 254/228/1/1 1 0 2 EXTRA",
            "400 Syntax Error: Too many parameters",
        ),
        (
            "MEASUREMENT DATA 254/227/1/1 1 0 2",
            "401 Bad object or device ID: 254/227/1/1 (Address not supported by application)",
        ),
        (
            "MEASUREMENT DATA 254/228/-1/1 1 0 2",
            "401 Bad object or device ID: 254/228/-1/1 (Invalid temperature group address)",
        ),
        (
            "MEASUREMENT DATA 254/228/1/256 1 0 2",
            "401 Bad object or device ID: 254/228/1/256 (channel value out of range)",
        ),
        (
            "MEASUREMENT DATA 254/228/1/1 32768 0 2",
            "400 Syntax Error: Integer parameter is out of range : <value>",
        ),
        (
            "MEASUREMENT DATA 254/228/1/1 x 0 2",
            "400 Syntax Error: Invalid integer parameter : <value>",
        ),
        (
            "MEASUREMENT DATA 254/228/1/1 1 128 2",
            "400 Syntax Error: Integer parameter is out of range : <multiplier>",
        ),
        (
            "MEASUREMENT DATA 254/228/1/1 1 0 256",
            "400 Syntax Error: Integer parameter is out of range : <units>",
        ),
    ];
    let before_frames = sys.pci.frames().len();
    for (index, (text, expected)) in invalid.into_iter().enumerate() {
        let reply = command(&mut reader, &mut writer, &format!("bad-{index}"), text).await;
        assert_eq!(reply.last().unwrap(), expected, "{text}: {reply:?}");
    }
    assert_eq!(sys.pci.frames().len(), before_frames);

    assert_eq!(
        command(&mut reader, &mut writer, "events", "EVENT ON")
            .await
            .last()
            .unwrap(),
        "200 OK."
    );
    sys.pci.inject(&pci_wire(&[
        5, 100, 0xe4, 0, 0x0e, 1, 1, 2, 0xfe, 0x27, 0xfa,
    ]));
    let mut event = String::new();
    tokio::time::timeout(STARTUP, reader.read_line(&mut event))
        .await
        .unwrap()
        .unwrap();
    assert_eq!(
        event.trim_end_matches(['\r', '\n']),
        "#e# measurement data //HARNESS/254/228/1/1 10234 -2 2 sourceUnit=100"
    );
    let data = command(
        &mut reader,
        &mut writer,
        "get",
        "GET //HARNESS/254/228/1/1 Data",
    )
    .await;
    assert!(
        data.last()
            .unwrap()
            .starts_with("300 //HARNESS/254/228/1/1: Data=10234,-2,2,"),
        "{data:?}"
    );
    assert_eq!(
        command(&mut reader, &mut writer, "devices", "GET 254/$E4 Devices")
            .await
            .last()
            .unwrap(),
        "300 //HARNESS/254/228: Devices=0,1,2,255"
    );
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "channels",
            "GET //HARNESS/254/228/2 Channels"
        )
        .await
        .last()
        .unwrap(),
        "300 //HARNESS/254/228/2: Channels=3"
    );
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "unknown-data",
            "GET //HARNESS/254/228/2/3 Data"
        )
        .await
        .last()
        .unwrap(),
        "300 //HARNESS/254/228/2/3: Data=0,0,0,-1"
    );
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "unknown-property",
            "GET //HARNESS/254/228/2/3 Value"
        )
        .await
        .last()
        .unwrap(),
        "402 Operation not supported by: //HARNESS/254/228/2/3 (Parameter value not found)"
    );
    assert_eq!(
        command(&mut reader, &mut writer, "events-off", "EVENT OFF")
            .await
            .last()
            .unwrap(),
        "200 OK."
    );

    sys.pci.reject_next_confirmation();
    let before = sys.pci.count_payload(&sample);
    let rejected = command(
        &mut reader,
        &mut writer,
        "nak",
        "MEASUREMENT DATA 254/228/1/1 10234 -2 2",
    )
    .await;
    assert!(
        rejected
            .last()
            .unwrap()
            .starts_with("502 Measurement data delivery failed: PCI rejected command"),
        "{rejected:?}"
    );
    assert_eq!(sys.pci.count_payload(&sample), before + 1);
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "again",
            "MEASUREMENT DATA 254/228/1/1 10234 -2 2"
        )
        .await
        .last()
        .unwrap(),
        "200 OK."
    );

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
    require(COMMAND_DRAIN, "MQTT command after MEASUREMENT", || {
        sys.pci.count_payload(lighting) == before + 1
    })
    .await;

    assert_eq!(
        command(&mut reader, &mut writer, "logout", "LOGOUT")
            .await
            .last()
            .unwrap(),
        "200 OK"
    );
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "locked2",
            "MEASUREMENT DATA 254/228/1/1 1 0 2"
        )
        .await
        .last()
        .unwrap(),
        "420 LOGIN required"
    );
    assert!(sys.daemon.is_running());
    drop(sys);
    std::fs::remove_file(state).unwrap();
    std::fs::remove_file(token).unwrap();
}
