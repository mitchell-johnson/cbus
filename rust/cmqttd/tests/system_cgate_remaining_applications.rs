//! Real cmqttd process: Identify, Short Message, and Error Reporting use the
//! shared MQTT PCI, exact typed SAL, one correlated confirmation without
//! replay, strict pre-I/O validation, and source-preserving event fanout.

mod util;

use serde_json::{json, Value};
use tokio::{
    io::{AsyncBufReadExt, AsyncWriteExt, BufReader},
    net::TcpStream,
};
use util::*;

const TOKEN: &str = "throwaway-remaining-apps-system-token-0123456789abcdef";

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
async fn remaining_applications_are_exact_once_authenticated_and_keep_mqtt_live() {
    let state = cbus_test_support::proc::temp_path("cgate-remaining-apps.json");
    let token = cbus_test_support::proc::temp_path("cgate-remaining-apps.token");
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

    let capabilities = command(&mut reader, &mut writer, "caps", "CMQTT CAPABILITIES").await;
    let capabilities: Value =
        serde_json::from_str(capabilities[0].strip_prefix("200-").unwrap()).unwrap();
    assert_eq!(capabilities["identify_application"], 251);
    assert_eq!(capabilities["shortmessage_application"], 173);
    assert_eq!(capabilities["ereport_application"], 206);
    assert_eq!(
        capabilities["shortmessage_send_compatibility"],
        "repaired-coherent-utf8-native-decoder-layout"
    );
    assert_eq!(
        capabilities["shortmessage_native_3_4_malformed_send_reproduced"],
        false
    );

    let identify_on = checksummed("05FB007901");
    let short_refresh = checksummed("05AD000104");
    let short_send = checksummed("05AD0086080474657374");
    let ereport_ack = checksummed("05CE0025FFC7FFFFFF");

    // Optional authentication gates physical mutations and report injection,
    // while the Short Message refresh request remains available.
    for (tag, text, payload) in [
        ("locked-id", "IDENTIFY ON 254/251/1", &identify_on),
        (
            "locked-short",
            "SHORTMESSAGE SEND 254/173 1 0 4 - - test",
            &short_send,
        ),
        (
            "locked-report",
            "EREPORT MESSAGE 254/206 ACK 1023 n n n 7 255 255 255",
            &ereport_ack,
        ),
    ] {
        let before = sys.pci.count_payload(payload);
        assert_eq!(
            command(&mut reader, &mut writer, tag, text)
                .await
                .last()
                .unwrap(),
            "420 LOGIN required"
        );
        assert_eq!(sys.pci.count_payload(payload), before);
    }
    let before = sys.pci.count_payload(&short_refresh);
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "refresh-open",
            "SHORTMESSAGE REFRESH 254/$AD 4"
        )
        .await
        .last()
        .unwrap(),
        "200 OK."
    );
    assert_eq!(sys.pci.count_payload(&short_refresh), before + 1);
    assert_eq!(
        command(&mut reader, &mut writer, "login", &format!("LOGIN {TOKEN}"))
            .await
            .last()
            .unwrap(),
        "200 OK"
    );

    // Exact command vectors, including repaired coherent SEND layouts.
    let commands = [
        (
            "IDENTIFY ON 254/251/1",
            "05FB007901",
            "200 OK: //HARNESS/254/251/1",
        ),
        (
            "IDENTIFY OFF //HARNESS/254/251/1",
            "05FB000101",
            "200 OK: //HARNESS/254/251/1",
        ),
        (
            "IDENTIFY RAMP 254/251/1 128 20s",
            "05FB00220180",
            "200 OK: //HARNESS/254/251/1",
        ),
        (
            "IDENTIFY RAMP 254/251/1 128",
            "05FB00020180",
            "200 OK: //HARNESS/254/251/1",
        ),
        (
            "IDENTIFY RAMP 254/251/1 50% 1m",
            "05FB003A017F",
            "200 OK: //HARNESS/254/251/1",
        ),
        (
            "IDENTIFY TERMINATERAMP 254/251/1 FORCE",
            "05FB000901",
            "200 OK: //HARNESS/254/251/1",
        ),
        ("SHORTMESSAGE REFRESH 254/173 63", "05AD00013F", "200 OK."),
        (
            "SHORTMESSAGE SEND 254/173 1 0 4 - - test",
            "05AD0086080474657374",
            "200 OK.",
        ),
        (
            "SHORTMESSAGE SEND 254/173 5 3 17 4660 86 \"AB\"",
            "05AD00872BD11234564142",
            "200 OK.",
        ),
        (
            "SHORTMESSAGE SEND 254/173 0 0 0 - - \"\"",
            "05AD00820000",
            "200 OK.",
        ),
        (
            "EREPORT MESSAGE 254/$CE ACK 1023 n n n 7 255 255 255",
            "05CE0025FFC7FFFFFF",
            "200 OK.",
        ),
        (
            "EREPORT MESSAGE 254/206 RECENT 0 y 1 0 0 0",
            "05CE0005003000FFFF",
            "200 OK.",
        ),
        (
            "EREPORT MESSAGE 254/206 ERROR_REPORT 1 1 0 1 4 1 2",
            "05CE0015006C0102FF",
            "200 OK.",
        ),
        (
            "EREPORT MESSAGE 254/206 CLEAR 2 0 1 1 3 2 3 4",
            "05CE0035009B020304",
            "200 OK.",
        ),
    ];
    for (index, (text, native, expected)) in commands.into_iter().enumerate() {
        let payload = checksummed(native);
        let before = sys.pci.count_payload(&payload);
        let reply = command(&mut reader, &mut writer, &index.to_string(), text).await;
        assert_eq!(reply.last().unwrap(), expected, "{text}: {reply:?}");
        assert_eq!(sys.pci.count_payload(&payload), before + 1, "{text}");
    }

    // Every selector, arity, and range failure occurs before PCI I/O.
    let before_frames = sys.pci.frames().len();
    for (index, text) in [
        "IDENTIFY ON",
        "IDENTIFY ON 253/251/1",
        "IDENTIFY ON 254/250/1",
        "IDENTIFY ON 254/251/1 EXTRA EXTRA",
        "IDENTIFY RAMP 254/251/1 256 20",
        "IDENTIFY RAMP 254/251/1 101% 20",
        "IDENTIFY RAMP 254/251/1 128 1h",
        "SHORTMESSAGE REFRESH 254/173 64",
        "SHORTMESSAGE REFRESH 254/172 4",
        "SHORTMESSAGE REFRESH 253/173 4",
        "SHORTMESSAGE SEND 254/173 8 1 4 - - test",
        "SHORTMESSAGE SEND 254/173 7 8 4 - - test",
        "SHORTMESSAGE SEND 254/173 7 1 64 - - test",
        "SHORTMESSAGE SEND 254/173 7 1 4 65536 - test",
        "SHORTMESSAGE SEND 254/173 7 1 4 - 256 test",
        "SHORTMESSAGE SEND 254/173 7 1 4 - - 123456789012345",
        "EREPORT MESSAGE 254/205 ACK 0 n n n 0 0",
        "EREPORT MESSAGE 253/206 ACK 0 n n n 0 0",
        "EREPORT MESSAGE 254/206 ACK 1024 n n n 0 0",
        "EREPORT MESSAGE 254/206 ACK 0 maybe n n 0 0",
        "EREPORT MESSAGE 254/206 ACK 0 n n n 8 0",
        "EREPORT MESSAGE 254/206 ACK 0 n n n 0 0 0 0 EXTRA",
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
    for (body, expected) in [
        (
            vec![5, 4, 251, 0, 121, 1],
            "#e# identify on //HARNESS/254/251/1 sourceUnit=4",
        ),
        (
            vec![5, 4, 173, 0, 0x87, 0x2b, 0xd1, 0x12, 0x34, 0x56, b'A', b'B'],
            "#e# shortmessage send //HARNESS/254/173 total=40 sequence=3 info-type=17 number=4660 symbol=86 text=\"AB\" sourceUnit=4",
        ),
        (
            vec![5, 4, 206, 0, 0x25, 0xff, 0xc7, 0xff, 0xff, 0xff],
            "#e# ereport message //HARNESS/254/206 ACK 1023 n n n 7 255 255 255 sourceUnit=4",
        ),
    ] {
        sys.pci.inject(&pci_wire(&body));
        let mut event = String::new();
        tokio::time::timeout(STARTUP, reader.read_line(&mut event))
            .await
            .unwrap()
            .unwrap();
        assert_eq!(event.trim_end_matches(['\r', '\n']), expected);
    }
    assert_eq!(
        sys.broker.publishes().len(),
        mqtt_before,
        "these application observations must not invent MQTT publications"
    );

    // A NAK is terminal and the exact-once SEND is never replayed.
    sys.pci.reject_next_confirmation();
    let before = sys.pci.count_payload(&short_send);
    let rejected = command(
        &mut reader,
        &mut writer,
        "nak",
        "SHORTMESSAGE SEND 254/173 1 0 4 - - test",
    )
    .await;
    assert!(
        rejected
            .last()
            .unwrap()
            .starts_with("502 Short Message delivery failed: PCI rejected command"),
        "{rejected:?}"
    );
    assert_eq!(sys.pci.count_payload(&short_send), before + 1);

    // Ordinary MQTT lighting remains live over the same reader and PCI.
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
    require(COMMAND_DRAIN, "MQTT command after remaining apps", || {
        sys.pci.count_payload(lighting) == before + 1
    })
    .await;

    assert!(sys.daemon.is_running());
    drop(sys);
    std::fs::remove_file(state).unwrap();
    std::fs::remove_file(token).unwrap();
}
