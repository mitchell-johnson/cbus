//! Real cmqttd process: native C-Gate TELEPHONY commands share the MQTT PCI,
//! use exact Telephony SAL, require active-generation confirmation, and fail
//! closed before I/O.

mod util;

use serde_json::{json, Value};
use tokio::{
    io::{AsyncBufReadExt, AsyncWriteExt, BufReader},
    net::TcpStream,
};
use util::*;

const TOKEN: &str = "throwaway-telephony-system-token-0123456789abcdef";

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
async fn telephony_native_family_is_confirmed_authenticated_and_keeps_mqtt_live() {
    let state = cbus_test_support::proc::temp_path("cgate-telephony.json");
    let token = cbus_test_support::proc::temp_path("cgate-telephony.token");
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

    let expected_help = [
        "101-Help: TELEPHONY commands:",
        "101-Help:  TELEPHONY ? Help for these commands",
        "101-Help:  TELEPHONY CLEAR_DIVERSION - Command the telephony device to clear any diversion",
        "101-Help:  TELEPHONY DIVERT - Set a diversion for the telephony device",
        "101-Help:  TELEPHONY ISOLATE_SECONDARY_OUTLET - Set the isolation mode for the telephony device",
        "101-Help:  TELEPHONY RECALL_LAST_NUMBER_REQUEST - Request a last number recall from the telephony device",
        "101 Help:  TELEPHONY REJECT_INCOMING_CALL - Command the telephony device to reject the incoming call",
    ];
    assert_eq!(
        command(&mut reader, &mut writer, "help-bare", "TELEPHONY").await,
        expected_help
    );
    assert_eq!(
        command(&mut reader, &mut writer, "help-q", "TELEPHONY ?").await,
        expected_help
    );

    let capabilities = command(&mut reader, &mut writer, "caps", "CMQTT CAPABILITIES").await;
    let capabilities: Value =
        serde_json::from_str(capabilities[0].strip_prefix("200-").unwrap()).unwrap();
    assert_eq!(capabilities["telephony_control"], true);
    assert_eq!(capabilities["telephony_application"], 224);
    assert_eq!(
        capabilities["telephony_delivery_semantics"],
        "pci-confirmed-broadcast"
    );
    assert_eq!(capabilities["telephony_event_fanout"], true);
    assert_eq!(capabilities["telephony_mqtt_state"], false);
    assert_eq!(
        capabilities["telephony_commands"].as_array().unwrap().len(),
        5
    );
    assert_eq!(
        capabilities["telephony_reports"].as_array().unwrap().len(),
        7
    );

    let clear = checksummed("05E0000984");
    let before = sys.pci.count_payload(&clear);
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "locked",
            "TELEPHONY CLEAR_DIVERSION 254/224"
        )
        .await
        .last()
        .unwrap(),
        "420 LOGIN required"
    );
    assert_eq!(sys.pci.count_payload(&clear), before);

    // The last-number request is operation-classified as a read/request and
    // stays usable while the optional mutation gate is armed.
    let recall = checksummed("05E0000A8101");
    let before = sys.pci.count_payload(&recall);
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "request",
            "TELEPHONY RECALL_LAST_NUMBER_REQUEST 254/$E0 OUT"
        )
        .await
        .last()
        .unwrap(),
        "200 OK."
    );
    assert_eq!(sys.pci.count_payload(&recall), before + 1);
    assert_eq!(
        command(&mut reader, &mut writer, "login", &format!("LOGIN {TOKEN}"))
            .await
            .last()
            .unwrap(),
        "200 OK"
    );

    // Each maintained command and each native spelling anomaly is emitted
    // exactly once with its captured C-Gate 3.4 payload.
    let commands = [
        ("TELEPHONY CLEAR_DIVERSION 254/224", "05E0000984"),
        ("TELEPHONY REJECT_INCOMING_CALL 254/$E0", "05E0000982"),
        (
            "TELEPHONY ISOLATE_SECONDARY_OUTLET 254/224 normal",
            "05E0000A8000",
        ),
        (
            "TELEPHONY ISOLATE_SECONDARY_OUTLET //HARNESS/254/224 ISOLATE",
            "05E0000A8001",
        ),
        (
            "TELEPHONY RECALL_LAST_NUMBER_REQUEST 254/224 in",
            "05E0000A8102",
        ),
        ("TELEPHONY DIVERT 254/224 1", "05E000A28331"),
        (
            "TELEPHONY DIVERT 254/224 1234567890123456",
            "05E000B18331323334353637383930313233343536",
        ),
        ("TELEPHONY DIVERT 254/224 \\q", "05E000A3835C71"),
        ("TELEPHONY DIVERT 254/224 \"\"", "05E000A3832222"),
        // Native Java counts one UTF-16 code unit but turns both signed
        // UTF-8 bytes into FF, leaving one undeclared trailing byte.
        ("TELEPHONY DIVERT 254/224 é", "05E000A283FFFF"),
    ];
    for (index, (text, native_payload)) in commands.into_iter().enumerate() {
        let payload = checksummed(native_payload);
        let before = sys.pci.count_payload(&payload);
        let reply = command(&mut reader, &mut writer, &index.to_string(), text).await;
        assert_eq!(reply.last().unwrap(), "200 OK.", "{text}: {reply:?}");
        assert_eq!(sys.pci.count_payload(&payload), before + 1, "{text}");
    }

    let before_frames = sys.pci.frames().len();
    for (index, text) in [
        "TELEPHONY BOGUS",
        "TELEPHONY CLEAR_DIVERSION",
        "TELEPHONY CLEAR_DIVERSION 254/224 EXTRA",
        "TELEPHONY CLEAR_DIVERSION 254/223",
        "TELEPHONY CLEAR_DIVERSION 253/224",
        "TELEPHONY CLEAR_DIVERSION //OTHER/254/224",
        "TELEPHONY CLEAR_DIVERSION ?",
        "TELEPHONY DIVERT 254/224",
        "TELEPHONY DIVERT 254/224 12345678901234567",
        "TELEPHONY DIVERT 254/224 \"12 34\"",
        "TELEPHONY ISOLATE_SECONDARY_OUTLET 254/224 bogus",
        "TELEPHONY RECALL_LAST_NUMBER_REQUEST 254/224 bogus",
    ]
    .into_iter()
    .enumerate()
    {
        let reply = command(&mut reader, &mut writer, &format!("bad-{index}"), text).await;
        assert!(reply.last().unwrap().starts_with('4'), "{text}: {reply:?}");
    }
    assert_eq!(sys.pci.frames().len(), before_frames);

    assert_eq!(
        command(&mut reader, &mut writer, "events", "EVENT ON")
            .await
            .last()
            .unwrap(),
        "200 OK."
    );
    let mqtt_before_telephony = sys.broker.publishes().len();
    sys.pci
        .inject(&pci_wire(&[5, 4, 0xe0, 0, 0x0c, 0x02, 0x20, b'1', b'2']));
    let mut event = String::new();
    tokio::time::timeout(STARTUP, reader.read_line(&mut event))
        .await
        .unwrap()
        .unwrap();
    assert_eq!(
        event.trim_end_matches(['\r', '\n']),
        "#e# telephony line_off_hook //HARNESS/254/224 out data 12 sourceUnit=4"
    );
    sys.pci.inject(&pci_wire(&[5, 4, 0xe0, 0, 0x09, 0x84]));
    event.clear();
    tokio::time::timeout(STARTUP, reader.read_line(&mut event))
        .await
        .unwrap()
        .unwrap();
    assert_eq!(
        event.trim_end_matches(['\r', '\n']),
        "#e# telephony clear_diversion //HARNESS/254/224 sourceUnit=4"
    );
    assert_eq!(
        command(&mut reader, &mut writer, "events-off", "EVENT OFF")
            .await
            .last()
            .unwrap(),
        "200 OK."
    );
    assert_eq!(
        sys.broker.publishes().len(),
        mqtt_before_telephony,
        "Telephony observations must not invent MQTT publications"
    );

    // A NAK rejects this generation; the following generation succeeds and
    // neither command is duplicated.
    sys.pci.reject_next_confirmation();
    let before = sys.pci.count_payload(&recall);
    let rejected = command(
        &mut reader,
        &mut writer,
        "nak",
        "TELEPHONY RECALL_LAST_NUMBER_REQUEST 254/224 out",
    )
    .await;
    assert!(
        rejected
            .last()
            .unwrap()
            .starts_with("502 Telephony delivery failed: PCI rejected command"),
        "{rejected:?}"
    );
    assert_eq!(sys.pci.count_payload(&recall), before + 1);
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "again",
            "TELEPHONY RECALL_LAST_NUMBER_REQUEST 254/224 out"
        )
        .await
        .last()
        .unwrap(),
        "200 OK."
    );
    assert_eq!(sys.pci.count_payload(&recall), before + 2);

    // Telephony has no invented MQTT state schema; ordinary lighting still
    // flows in both directions on the same broker and PCI.
    assert!(sys
        .broker
        .publishes()
        .iter()
        .all(|publish| !publish.topic.to_ascii_lowercase().contains("telephon")));
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
    require(COMMAND_DRAIN, "MQTT command after TELEPHONY", || {
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
            "TELEPHONY REJECT_INCOMING_CALL 254/224"
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
