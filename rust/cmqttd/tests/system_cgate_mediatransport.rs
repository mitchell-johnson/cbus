//! Real cmqttd process: native C-Gate MEDIATRANSPORT commands share the
//! MQTT PCI, use exact application-192 SAL, require confirmation, and fail
//! closed before I/O on unsupported or malformed input.

mod util;

use serde_json::json;
use tokio::{
    io::{AsyncBufReadExt, AsyncWriteExt, BufReader},
    net::TcpStream,
};
use util::*;

const TOKEN: &str = "throwaway-mediatransport-system-token-0123456789abcdef";

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
async fn mediatransport_native_family_is_confirmed_authenticated_and_keeps_mqtt_live() {
    let state = cbus_test_support::proc::temp_path("cgate-mediatransport.json");
    let token = cbus_test_support::proc::temp_path("cgate-mediatransport.token");
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

    let help = command(&mut reader, &mut writer, "h", "MEDIATRANSPORT ?").await;
    assert_eq!(help.first().unwrap(), "101-Help: MEDIATRANSPORT commands:");
    assert_eq!(
        help.last().unwrap(),
        "101 Help:  MEDIATRANSPORT TRACK_NAME - The name, in characters, of the track being played (or to be played) by the output device in <Media Link Group>"
    );
    let capabilities = command(&mut reader, &mut writer, "c", "CMQTT CAPABILITIES").await;
    assert!(capabilities[0].contains("\"mediatransport_control\":true"));
    assert!(capabilities[0].contains("\"mediatransport_application\":192"));
    assert!(capabilities[0]
        .contains("\"mediatransport_delivery_semantics\":\"pci-confirmed-broadcast\""));
    assert!(capabilities[0].contains("\"mediatransport_retry_policy\":\"exactly-once-no-replay\""));
    assert!(capabilities[0].contains("\"mediatransport_event_fanout\":true"));
    assert!(capabilities[0].contains("\"mediatransport_mqtt_state\":false"));
    assert!(capabilities[0].contains("\"enumeration_size\""));

    let play = checksummed("05C0007902");
    let before = sys.pci.count_payload(&play);
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "locked",
            "MEDIATRANSPORT PLAY 254/192 2"
        )
        .await
        .last()
        .unwrap(),
        "420 LOGIN required"
    );
    assert_eq!(sys.pci.count_payload(&play), before);

    // Status and enumeration requests remain open under the mutation-only
    // optional LOGIN boundary.
    for (tag, text, native) in [
        (
            "status",
            "MEDIATRANSPORT STATUS_REQUEST 254/$C0 2",
            "05C0007102",
        ),
        (
            "enumerate",
            "MEDIATRANSPORT ENUMERATE 254/192 2 2 255",
            "05C000730202FF",
        ),
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
        ("MEDIATRANSPORT STOP 254/192 2", "05C0000102"),
        ("MEDIATRANSPORT PLAY //HARNESS/254/192 2", "05C0007902"),
        ("MEDIATRANSPORT PAUSE 254/192 2 0", "05C0000A0200"),
        ("MEDIATRANSPORT SET_CATEGORY 254/192 2 127", "05C00012027F"),
        (
            "MEDIATRANSPORT SET_SELECTION 254/192 2 32767",
            "05C0001B027FFF",
        ),
        (
            "MEDIATRANSPORT SET_TRACK 254/192 2 2147483647",
            "05C00025027FFFFFFF",
        ),
        ("MEDIATRANSPORT SHUFFLE 254/192 2 255", "05C0002A02FF"),
        ("MEDIATRANSPORT REPEAT 254/192 2 128", "05C000320280"),
        ("MEDIATRANSPORT NEXT_CATEGORY 254/192 2 1", "05C0003A0201"),
        ("MEDIATRANSPORT NEXT_SELECTION 254/192 2 0", "05C000420200"),
        ("MEDIATRANSPORT NEXT_TRACK 254/192 $2 $FF", "05C0004A02FF"),
        ("MEDIATRANSPORT NEXT_TRACK 254/192 0b10 0xA", "05C0004A020A"),
        ("MEDIATRANSPORT FORWARD 254/192 2 12", "05C00052020C"),
        ("MEDIATRANSPORT REWIND 254/192 2 10", "05C0005A020A"),
        ("MEDIATRANSPORT SOURCE_POWER 254/192 2 255", "05C0006202FF"),
        (
            "MEDIATRANSPORT TOTAL_TRACKS 254/192 2 2147483647",
            "05C0006D027FFFFFFF",
        ),
        ("MEDIATRANSPORT STATUS_REQUEST 254/192 2", "05C0007102"),
        ("MEDIATRANSPORT ENUMERATE 254/192 2 2 255", "05C000730202FF"),
        (
            "MEDIATRANSPORT ENUMERATION_SIZE 254/192 2 1 254 15",
            "05C000740201FE0F",
        ),
        (
            "MEDIATRANSPORT TRACK_NAME 254/192 2 0 0 0 12345678901",
            "05C0008D02003132333435363738393031",
        ),
        (
            "MEDIATRANSPORT SELECTION_NAME 254/192 2 7 3 2 Alpha Beta",
            "05C000AC027E416C7068612042657461",
        ),
        (
            "MEDIATRANSPORT CATEGORY_NAME 254/192 2 1 1 0 iPod",
            "05C000C6021469506F64",
        ),
        (
            "MEDIATRANSPORT CATEGORY_NAME 254/192 2 0 0 0",
            "05C000C20200",
        ),
        (
            r#"MEDIATRANSPORT TRACK_NAME 254/192 2 0 0 0 "A\ B\"C\\D""#,
            "05C00089020041204222435C44",
        ),
        // Captured native signed-byte compatibility quirk.
        (
            "MEDIATRANSPORT TRACK_NAME 254/192 0 0 0 0 ééééé",
            "05C0008C0000FFFFFFFFFFFFFFFFFFFF",
        ),
    ];
    for (index, (text, native_payload)) in commands.into_iter().enumerate() {
        let payload = checksummed(native_payload);
        let before = sys.pci.count_payload(&payload);
        let reply = command(&mut reader, &mut writer, &index.to_string(), text).await;
        assert_eq!(reply.last().unwrap(), "200 OK.", "{text}: {reply:?}");
        assert_eq!(sys.pci.count_payload(&payload), before + 1, "{text}");
    }

    let before_frames = sys.pci.frames().len();
    for (tag, text, expected) in [
        (
            "bad-application",
            "MEDIATRANSPORT PLAY 254/191 2",
            "402 Operation not supported by: 254/191",
        ),
        (
            "bad-network",
            "MEDIATRANSPORT PLAY 253/192 2",
            "401 Bad object or device ID: 253/192 (Network not found)",
        ),
        (
            "bad-project",
            "MEDIATRANSPORT PLAY //OTHER/254/192 2",
            "401 Bad object or device ID: //OTHER/254/192 (Object not found)",
        ),
        (
            "subcommand-question",
            "MEDIATRANSPORT PLAY ?",
            "401 Bad object or device ID: ? (Network not found)",
        ),
    ] {
        assert_eq!(
            command(&mut reader, &mut writer, tag, text)
                .await
                .last()
                .unwrap(),
            expected
        );
    }
    for (index, text) in [
        "MEDIATRANSPORT PLAY 254/192 -1",
        "MEDIATRANSPORT PLAY 254/192 256",
        "MEDIATRANSPORT PLAY 254/192 2 EXTRA",
        "MEDIATRANSPORT PLAY 254/192 0xGG",
        "MEDIATRANSPORT PAUSE 254/192 2 1",
        "MEDIATRANSPORT FORWARD 254/192 2 1",
        "MEDIATRANSPORT REWIND 254/192 2 255",
        "MEDIATRANSPORT SET_CATEGORY 254/192 2 128",
        "MEDIATRANSPORT SET_SELECTION 254/192 2 32768",
        "MEDIATRANSPORT SET_TRACK 254/192 2 2147483648",
        "MEDIATRANSPORT ENUMERATE 254/192 2 3 0",
        "MEDIATRANSPORT ENUMERATION_SIZE 254/192 2 1 0 16",
        "MEDIATRANSPORT CATEGORY_NAME 254/192 2 3 0 0 name",
        "MEDIATRANSPORT CATEGORY_NAME 254/192 2 0 4 0 name",
        "MEDIATRANSPORT CATEGORY_NAME 254/192 2 0 0 4 name",
        "MEDIATRANSPORT CATEGORY_NAME 254/192 2 0 0 0 123456789012",
        "MEDIATRANSPORT CATEGORY_NAME 254/192 2 0 0 0 éééééé",
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
    let mqtt_before = sys.broker.publishes().len();
    sys.pci.inject(&pci_wire(&[
        5, 4, 0xc0, 0, 0xc6, 2, 0x14, b'i', b'P', b'o', b'd',
    ]));
    let mut event = String::new();
    tokio::time::timeout(STARTUP, reader.read_line(&mut event))
        .await
        .unwrap()
        .unwrap();
    assert_eq!(
        event.trim_end_matches(['\r', '\n']),
        "#e# mediatransport category_name //HARNESS/254/192 group=2 wni=1 total=1 sequence=0 text=\"iPod\" sourceUnit=4"
    );
    // Native command parsing reserves outbound WNI 3/4, while the native
    // decoder still surfaces both values. Preserve that asymmetric boundary.
    sys.pci
        .inject(&pci_wire(&[5, 4, 0xc0, 0, 0x83, 2, 0x30, b'A']));
    event.clear();
    tokio::time::timeout(STARTUP, reader.read_line(&mut event))
        .await
        .unwrap()
        .unwrap();
    assert_eq!(
        event.trim_end_matches(['\r', '\n']),
        "#e# mediatransport track_name //HARNESS/254/192 group=2 wni=3 total=0 sequence=0 text=\"A\" sourceUnit=4"
    );
    tokio::task::yield_now().await;
    assert!(sys.broker.publishes()[mqtt_before..]
        .iter()
        .all(|publish| !publish.topic.contains("mediatransport")));
    assert_eq!(
        command(&mut reader, &mut writer, "events-off", "EVENT OFF")
            .await
            .last()
            .unwrap(),
        "200 OK."
    );

    let status = checksummed("05C0007102");
    sys.pci.reject_next_confirmation();
    let before = sys.pci.count_payload(&status);
    let rejected = command(
        &mut reader,
        &mut writer,
        "nak",
        "MEDIATRANSPORT STATUS_REQUEST 254/192 2",
    )
    .await;
    assert!(
        rejected
            .last()
            .unwrap()
            .starts_with("502 Media Transport delivery failed: PCI rejected command"),
        "{rejected:?}"
    );
    assert_eq!(sys.pci.count_payload(&status), before + 1);
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "again",
            "MEDIATRANSPORT STATUS_REQUEST 254/192 2"
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
    require(COMMAND_DRAIN, "MQTT command after Media Transport", || {
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
            "MEDIATRANSPORT STOP 254/192 2"
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
