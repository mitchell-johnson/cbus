//! Real cmqttd process: native C-Gate SECURITY commands share the MQTT PCI,
//! use exact Security SAL, require confirmation, and fail closed before I/O.

mod util;

use serde_json::json;
use tokio::{
    io::{AsyncBufReadExt, AsyncWriteExt, BufReader},
    net::TcpStream,
};
use util::*;

const TOKEN: &str = "throwaway-security-system-token-0123456789abcdef";

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
async fn security_native_family_is_confirmed_authenticated_and_keeps_mqtt_live() {
    let state = cbus_test_support::proc::temp_path("cgate-security.json");
    let token = cbus_test_support::proc::temp_path("cgate-security.token");
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

    let help = command(&mut reader, &mut writer, "h", "SECURITY ?").await;
    assert_eq!(help.first().unwrap(), "101-Help: SECURITY commands:");
    assert_eq!(
        help.last().unwrap(),
        "101 Help:  SECURITY TAMPER - Raise or drop tamper status for the security device"
    );
    let capabilities = command(&mut reader, &mut writer, "c", "CMQTT CAPABILITIES").await;
    assert!(capabilities[0].contains("\"security_control\":true"));
    assert!(capabilities[0].contains("\"security_application\":208"));
    assert!(capabilities[0].contains("\"security_delivery_semantics\":\"pci-confirmed-broadcast\""));
    assert!(capabilities[0].contains("\"security_event_fanout\":true"));
    assert!(capabilities[0].contains("\"security_mqtt_state\":false"));

    let arm = checksummed("05D0000AA201");
    let before = sys.pci.count_payload(&arm);
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "locked",
            "SECURITY ARM 254/208 away"
        )
        .await
        .last()
        .unwrap(),
        "420 LOGIN required"
    );
    assert_eq!(sys.pci.count_payload(&arm), before);

    // Read/request commands stay available under the mutation-only gate.
    for (tag, text, native) in [
        ("sr", "SECURITY STATUS_REQUEST 254/$D0 1", "05D00009A0"),
        ("zn", "SECURITY REQUEST_ZONE_NAME 254/208 1", "05D0000AA701"),
    ] {
        let payload = checksummed(native);
        let before = sys.pci.count_payload(&payload);
        assert_eq!(
            command(&mut reader, &mut writer, tag, text)
                .await
                .last()
                .unwrap(),
            "200 OK."
        );
        assert_eq!(sys.pci.count_payload(&payload), before + 1);
    }
    assert_eq!(
        command(&mut reader, &mut writer, "login", &format!("LOGIN {TOKEN}"))
            .await
            .last()
            .unwrap(),
        "200 OK"
    );

    let commands = [
        ("SECURITY STATUS_REQUEST 254/208 2", "05D00009A1"),
        ("SECURITY ARM //HARNESS/254/208 away", "05D0000AA201"),
        ("SECURITY ARM 254/208 NIGHT", "05D0000AA202"),
        ("SECURITY ARM 254/208 day", "05D0000AA203"),
        ("SECURITY ARM 254/208 vacation", "05D0000AA204"),
        ("SECURITY ARM 254/208 highest", "05D0000AA2FF"),
        ("SECURITY TAMPER 254/208 RAISE", "05D00079A3"),
        ("SECURITY TAMPER 254/208 drop", "05D00001A3"),
        ("SECURITY RAISE_ALARM 254/208", "05D00079A4"),
        ("SECURITY EMULATE_KEYPAD 254/208 0", "05D0000AA500"),
        ("SECURITY EMULATE_KEYPAD 254/208 $41", "05D0000AA541"),
        ("SECURITY EMULATE_KEYPAD 254/208 -1", "05D0000AA5FF"),
        ("SECURITY EMULATE_KEYPAD 254/208 2147483647", "05D0000AA5FF"),
        ("SECURITY DISPLAY_MESSAGE 254/208", "05D000E1A6"),
        (
            "SECURITY DISPLAY_MESSAGE 254/208 HELLO",
            "05D000E6A648454C4C4F",
        ),
        (
            "SECURITY DISPLAY_MESSAGE 254/208 \\x41\\x42",
            "05D000E3A64142",
        ),
        (
            "SECURITY DISPLAY_MESSAGE 254/208 12345678901234567",
            "05D000F2A63132333435363738393031323334353637",
        ),
        ("SECURITY REQUEST_ZONE_NAME 254/208 $7F", "05D0000AA77F"),
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
        "SECURITY STATUS_REQUEST 254/208 0",
        "SECURITY STATUS_REQUEST 254/207 1",
        "SECURITY STATUS_REQUEST 254/208 1 EXTRA",
        "SECURITY ARM 254/208 bogus",
        "SECURITY TAMPER 254/208 bogus",
        "SECURITY EMULATE_KEYPAD 254/208 2147483648",
        "SECURITY DISPLAY_MESSAGE 254/208 123456789012345678",
        "SECURITY DISPLAY_MESSAGE 254/208 HELLO WORLD",
        "SECURITY DISPLAY_MESSAGE 254/208 \\q",
        "SECURITY DISPLAY_MESSAGE 254/208 \\xGG",
        "SECURITY REQUEST_ZONE_NAME 254/208 0",
        "SECURITY REQUEST_ZONE_NAME 254/208 128",
        "SECURITY REQUEST_ZONE_NAME 254/208 x",
    ]
    .into_iter()
    .enumerate()
    {
        let reply = command(&mut reader, &mut writer, &format!("bad-{index}"), text).await;
        if text.ends_with("\\xGG") {
            assert_eq!(
                reply.last().unwrap(),
                "405 Parameter out of range: 254/208 (For input string: \"GG\")"
            );
        } else {
            assert!(reply.last().unwrap().starts_with('4'), "{text}: {reply:?}");
        }
    }
    assert_eq!(sys.pci.frames().len(), before_frames);

    assert_eq!(
        command(&mut reader, &mut writer, "events", "EVENT ON")
            .await
            .last()
            .unwrap(),
        "200 OK."
    );

    sys.pci.inject(&pci_wire(&[5, 4, 0xd0, 0, 0x0a, 0x86, 7]));
    let mut event = String::new();
    tokio::time::timeout(STARTUP, reader.read_line(&mut event))
        .await
        .unwrap()
        .unwrap();
    assert_eq!(
        event.trim_end_matches(['\r', '\n']),
        "#e# security zone_unsealed //HARNESS/254/208/7 sourceUnit=4"
    );
    let mut zone_name = vec![5, 4, 0xd0, 0, 0xad, 0x8d, 7];
    zone_name.extend_from_slice(b"A B\\C\0\x7f1234");
    sys.pci.inject(&pci_wire(&zone_name));
    event.clear();
    tokio::time::timeout(STARTUP, reader.read_line(&mut event))
        .await
        .unwrap()
        .unwrap();
    assert_eq!(
        event.trim_end_matches(['\r', '\n']),
        "#e# security zone_name //HARNESS/254/208/7 A\\x20B\\\\C\\x00\\x7F1234 sourceUnit=4"
    );
    assert_eq!(
        command(&mut reader, &mut writer, "events-off", "EVENT OFF")
            .await
            .last()
            .unwrap(),
        "200 OK."
    );

    let status = checksummed("05D00009A0");
    sys.pci.reject_next_confirmation();
    let before = sys.pci.count_payload(&status);
    let rejected = command(
        &mut reader,
        &mut writer,
        "nak",
        "SECURITY STATUS_REQUEST 254/208 1",
    )
    .await;
    assert!(
        rejected
            .last()
            .unwrap()
            .starts_with("502 Security delivery failed: PCI rejected command"),
        "{rejected:?}"
    );
    assert_eq!(sys.pci.count_payload(&status), before + 1);
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "again",
            "SECURITY STATUS_REQUEST 254/208 1"
        )
        .await
        .last()
        .unwrap(),
        "200 OK."
    );

    // MQTT remains active in both directions on the shared PCI.
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
    require(COMMAND_DRAIN, "MQTT command after SECURITY", || {
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
            "SECURITY RAISE_ALARM 254/208"
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
