//! Real cmqttd process: the complete C-Gate AUDIO family shares the MQTT
//! PCI, uses retained native SAL, requires active-generation confirmation,
//! and leaves unrelated MQTT traffic live.

mod util;

use serde_json::json;
use tokio::{
    io::{AsyncBufReadExt, AsyncWriteExt, BufReader},
    net::TcpStream,
};
use util::*;

const TOKEN: &str = "throwaway-audio-system-token-0123456789abcdef";

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
async fn audio_native_family_is_confirmed_authenticated_and_keeps_mqtt_live() {
    let state = cbus_test_support::proc::temp_path("cgate-audio.json");
    let token = cbus_test_support::proc::temp_path("cgate-audio.token");
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

    let help = command(&mut reader, &mut writer, "h", "AUDIO ?").await;
    assert_eq!(help.first().unwrap(), "101-Help: AUDIO commands:");
    assert_eq!(
        help.last().unwrap(),
        "101 Help:  AUDIO ZONE_FEED_LABEL_REQUEST - Send a Zone Feed Label Request command"
    );
    let capabilities = command(&mut reader, &mut writer, "c", "CMQTT CAPABILITIES").await;
    assert!(capabilities[0].contains("\"audio_control\":true"));
    assert!(capabilities[0].contains("\"audio_application\":205"));
    assert!(capabilities[0].contains("\"audio_delivery_semantics\":\"pci-confirmed-broadcast\""));
    assert!(capabilities[0].contains("\"audio_event_fanout\":true"));
    assert!(capabilities[0].contains("\"audio_mqtt_state\":false"));
    let capability_json: serde_json::Value =
        serde_json::from_str(capabilities[0].strip_prefix("200-").unwrap()).unwrap();
    assert_eq!(
        capability_json["audio_commands"].as_array().unwrap().len(),
        19
    );
    assert_eq!(
        capability_json["audio_events"].as_array().unwrap().len(),
        21
    );
    assert!(capability_json["audio_events"]
        .as_array()
        .unwrap()
        .contains(&json!("label")));
    assert!(capability_json["audio_events"]
        .as_array()
        .unwrap()
        .contains(&json!("load_icon")));

    let on = checksummed("05CD007954");
    let before = sys.pci.count_payload(&on);
    assert_eq!(
        command(&mut reader, &mut writer, "locked", "AUDIO ON 254/205 1 2 4")
            .await
            .last()
            .unwrap(),
        "420 LOGIN required"
    );
    assert_eq!(sys.pci.count_payload(&on), before);

    // Request/report commands stay available under the mutation-only gate.
    let request = checksummed("05CD0002E750");
    let before = sys.pci.count_payload(&request);
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "request",
            "AUDIO REQUEST_CURRENT_FEED 254/$CD 1 2",
        )
        .await
        .last()
        .unwrap(),
        "200 OK."
    );
    assert_eq!(sys.pci.count_payload(&request), before + 1);
    assert_eq!(
        command(&mut reader, &mut writer, "login", &format!("LOGIN {TOKEN}"))
            .await
            .last()
            .unwrap(),
        "200 OK"
    );

    let commands = [
        ("AUDIO CURRENT_FEED 254/205 1 2 4 4", "05CD0022E854"),
        ("AUDIO DYNAMIC_1 254/205 1 2", "05CD00025600"),
        ("AUDIO DYNAMIC_2 254/205 1 2", "05CD000256FF"),
        ("AUDIO HIGH_PRIORITY 254/205 2 99 7", "05CD003AC263"),
        ("AUDIO MUTE 254/205 1 2 7", "05CD00025507"),
        ("AUDIO NEXT_FEED 254/205 1 2", "05CD00025602"),
        ("AUDIO NEXT_LANGUAGE 254/205 1 2", "05CD00025611"),
        ("AUDIO OFF 254/205 1 2 4", "05CD000154"),
        ("AUDIO ON //HARNESS/254/205 Z $C8", "05CD0079C8"),
        ("AUDIO OUTPUT_COMMON_CONTROL 254/205 0", "05CD0002E500"),
        (
            "AUDIO OUTPUT_DEVICE_STATUS_REQUEST 254/205 0",
            "05CD0002E300",
        ),
        ("AUDIO OUTPUT_ERROR_CODE 254/205 1 2 7", "05CD0002E657"),
        ("AUDIO PREVIOUS_FEED 254/205 1 2", "05CD00025605"),
        ("AUDIO RAMP 254/205 1 2 4 123 15", "05CD007A547B"),
        ("AUDIO REQUEST_CURRENT_FEED 254/205 Z 255", "05CD0002E7F8"),
        ("AUDIO SET_FEED 254/205 1 2 4 1", "05CD000AE954"),
        ("AUDIO TERMINATERAMP 254/205 1 2 4", "05CD000954"),
        ("AUDIO ZONE_DESCRIPTOR_REQUEST 254/205 1 2", "05CD0002E050"),
        (
            "AUDIO ZONE_FEED_LABEL_REQUEST 254/205 Z 255",
            "05CD0002E2F8",
        ),
    ];
    for (index, (text, native_payload)) in commands.into_iter().enumerate() {
        let payload = checksummed(native_payload);
        let before = sys.pci.count_payload(&payload);
        let reply = command(&mut reader, &mut writer, &index.to_string(), text).await;
        assert_eq!(reply.last().unwrap(), "200 OK.", "{text}: {reply:?}");
        assert_eq!(sys.pci.count_payload(&payload), before + 1, "{text}");
    }

    // Retain two native parser anomalies as explicit compatibility cases.
    let warning_payload = checksummed("05CD00025508");
    let warning = command(
        &mut reader,
        &mut writer,
        "mute8",
        "AUDIO MUTE 254/205 1 2 8",
    )
    .await;
    assert_eq!(
        warning,
        [
            "400-Syntax Error: Integer parameter is out of range : <mode>",
            "200 OK."
        ]
    );
    assert!(sys.pci.count_payload(&warning_payload) >= 1);
    let sentinel = checksummed("05CD0002E3FF");
    let before = sys.pci.count_payload(&sentinel);
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "sentinel",
            "AUDIO OUTPUT_DEVICE_STATUS_REQUEST 254/205",
        )
        .await
        .last()
        .unwrap(),
        "200 OK."
    );
    assert_eq!(sys.pci.count_payload(&sentinel), before + 1);

    let before_frames = sys.pci.frames().len();
    for (index, text) in [
        "AUDIO ON 254/205 3 0 0",
        "AUDIO CURRENT_FEED 254/205 0 0 0 5",
        "AUDIO OUTPUT_ERROR_CODE 254/205 0 0 8",
        "AUDIO RAMP 254/205 0 0 0 0 16",
        "AUDIO SET_FEED 254/205 0 0 0 2",
        "AUDIO ON 253/205 0 0 0",
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
    sys.pci
        .inject(&pci_wire(&[5, 4, 0xcd, 0, 0x22, 0xe8, 0xbf]));
    let mut event = String::new();
    tokio::time::timeout(STARTUP, reader.read_line(&mut event))
        .await
        .unwrap()
        .unwrap();
    assert_eq!(
        event.trim_end_matches(['\r', '\n']),
        "#e# audio current_feed //HARNESS/254/205 2 7 7 4 sourceUnit=4"
    );
    sys.pci.inject(&pci_wire(&[
        5, 4, 0xcd, 0, 0xa7, 0x4c, 0x20, 1, b'E', b'D', b'L', b'T',
    ]));
    event.clear();
    tokio::time::timeout(STARTUP, reader.read_line(&mut event))
        .await
        .unwrap()
        .unwrap();
    assert_eq!(
        event.trim_end_matches(['\r', '\n']),
        "#e# audio label //HARNESS/254/205 1 1 4 0 1 1 45444C54 sourceUnit=4"
    );
    assert_eq!(
        command(&mut reader, &mut writer, "events-off", "EVENT OFF")
            .await
            .last()
            .unwrap(),
        "200 OK."
    );

    let status = checksummed("05CD0002E300");
    sys.pci.reject_next_confirmation();
    let before = sys.pci.count_payload(&status);
    let rejected = command(
        &mut reader,
        &mut writer,
        "nak",
        "AUDIO OUTPUT_DEVICE_STATUS_REQUEST 254/205 0",
    )
    .await;
    assert!(
        rejected
            .last()
            .unwrap()
            .starts_with("502 Audio delivery failed: PCI rejected command"),
        "{rejected:?}"
    );
    assert_eq!(sys.pci.count_payload(&status), before + 1);
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "again",
            "AUDIO OUTPUT_DEVICE_STATUS_REQUEST 254/205 0",
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
    require(COMMAND_DRAIN, "MQTT command after AUDIO", || {
        sys.pci.count_payload(lighting) == before + 1
    })
    .await;

    assert!(sys.daemon.is_running());
    drop(sys);
    std::fs::remove_file(state).unwrap();
    std::fs::remove_file(token).unwrap();
}
