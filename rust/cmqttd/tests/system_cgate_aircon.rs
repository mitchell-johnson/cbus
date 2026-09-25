//! Real cmqttd process: native C-Gate AIRCON commands use the same PCI as
//! MQTT, require a confirmed write, and fail closed before I/O on bad input.

mod util;

use serde_json::json;
use tokio::{
    io::{AsyncBufReadExt, AsyncWriteExt, BufReader},
    net::TcpStream,
};
use util::*;

const TOKEN: &str = "throwaway-aircon-system-token-0123456789abcdef";

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
        let payload = line.strip_prefix(&prefix).expect("tagged C-Gate reply");
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
async fn aircon_native_family_is_confirmed_authenticated_and_keeps_mqtt_live() {
    let state = cbus_test_support::proc::temp_path("cgate-aircon.json");
    let token = cbus_test_support::proc::temp_path("cgate-aircon.token");
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

    let help = command(&mut reader, &mut writer, "h", "AIRCON ?").await;
    assert_eq!(help.first().unwrap(), "101-Help: AIRCON commands:");
    assert_eq!(
        help.last().unwrap(),
        "101 Help:  AIRCON SET_ZONE_HVAC_MODE - Broadcast of HVAC mode and level required for a Zone or Zones."
    );
    let capabilities = command(&mut reader, &mut writer, "c", "CMQTT CAPABILITIES").await;
    assert!(capabilities[0].contains("\"aircon_control\":true"));
    assert!(capabilities[0].contains("\"aircon_application\":172"));
    assert!(capabilities[0].contains("\"aircon_delivery_semantics\":\"pci-confirmed-broadcast\""));
    assert!(capabilities[0].contains("\"aircon_event_fanout\":true"));
    assert!(capabilities[0].contains("\"aircon_mqtt_state\":false"));
    assert!(capabilities[0].contains("\"zone_hvac_plant_status\""));

    let ward_off = checksummed("05AC000101");
    let before = sys.pci.count_payload(&ward_off);
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "u",
            "AIRCON SET_WARD_OFF 254/$AC 1"
        )
        .await
        .last()
        .unwrap(),
        "420 LOGIN required"
    );
    assert_eq!(sys.pci.count_payload(&ward_off), before);

    // REFRESH asks devices to report current state; it remains available
    // under the local mutation-only auth policy.
    let refresh = checksummed("05AC002101");
    let before = sys.pci.count_payload(&refresh);
    assert_eq!(
        command(&mut reader, &mut writer, "r", "AIRCON REFRESH 254/$AC 1")
            .await
            .last()
            .unwrap(),
        "200 OK."
    );
    assert_eq!(sys.pci.count_payload(&refresh), before + 1);
    assert_eq!(
        command(&mut reader, &mut writer, "l", &format!("LOGIN {TOKEN}"))
            .await
            .last()
            .unwrap(),
        "200 OK"
    );

    let commands = [
        ("AIRCON REFRESH 254/172 1", "05AC002101"),
        ("AIRCON SET_WARD_OFF //HARNESS/254/172 1", "05AC000101"),
        ("AIRCON SET_WARD_ON 254/$AC 1", "05AC007901"),
        (
            "AIRCON SET_ZONE_HVAC_MODE 254/172 1 0,1,2 3 0 1 0 1 255 23 64",
            "05AC002F010753FF001740",
        ),
        (
            "AIRCON SET_ZONE_HUMIDITY_MODE 254/172 1 0,1,2 3 0 0 0 1 2 40 64",
            "05AC004701074302002840",
        ),
        (
            "AIRCON SET_HVAC_UPPER_GUARD_LIMIT 254/172 1 1,2 27 3 0",
            "05AC00550106001B03",
        ),
        (
            "AIRCON SET_HVAC_LOWER_GUARD_LIMIT 254/172 1 0,1,2 18 3 0",
            "05AC005D0107001203",
        ),
        (
            "AIRCON SET_HVAC_SETBACK_LIMIT 254/172 1 0,1,2 2 3 0",
            "05AC00650107000203",
        ),
        (
            "AIRCON SET_HUMIDITY_UPPER_GUARD_LIMIT 254/172 1 1,2 70 3 0",
            "05AC006D0106004603",
        ),
        (
            "AIRCON SET_HUMIDITY_LOWER_GUARD_LIMIT 254/172 1 0,1,2 20 3 0",
            "05AC00750107001403",
        ),
        (
            "AIRCON SET_HUMIDITY_SETBACK_LIMIT 254/172 1 3,4 15 1 0",
            "05AC007D0118000F01",
        ),
    ];
    for (index, (text, native_payload)) in commands.into_iter().enumerate() {
        let payload = checksummed(native_payload);
        let before = sys.pci.count_payload(&payload);
        let reply = command(&mut reader, &mut writer, &index.to_string(), text).await;
        assert_eq!(reply.last().unwrap(), "200 OK.", "{text}: {reply:?}");
        assert_eq!(sys.pci.count_payload(&payload), before + 1, "{text}");
    }

    // Native Java StringTokenizer semantics ignore empty comma tokens and
    // collapse duplicate zones. The native plant encoder saturates positive
    // signed-int type values at 255; levels and auxiliary levels do not.
    let boundary_commands = [
        (
            "AIRCON SET_ZONE_HVAC_MODE 254/172 1 0,0 3 0 1 0 1 255 23 64",
            "05AC002F010153FF001740",
        ),
        (
            "AIRCON SET_ZONE_HVAC_MODE 254/172 1 ,0 3 0 1 0 1 255 23 64",
            "05AC002F010153FF001740",
        ),
        (
            "AIRCON SET_ZONE_HVAC_MODE 254/172 1 0, 3 0 1 0 1 255 23 64",
            "05AC002F010153FF001740",
        ),
        (
            "AIRCON SET_ZONE_HVAC_MODE 254/172 1 , 3 0 1 0 1 0 0 0",
            "05AC002F01005300000000",
        ),
        (
            "AIRCON SET_ZONE_HVAC_MODE 254/172 1 0 3 0 1 0 1 256 23 64",
            "05AC002F010153FF001740",
        ),
        (
            "AIRCON SET_ZONE_HVAC_MODE 254/172 1 0 3 0 1 0 1 2147483647 23 64",
            "05AC002F010153FF001740",
        ),
        (
            "AIRCON SET_ZONE_HVAC_MODE 254/172 1 0 3 0 1 0 1 255 65535 255",
            "05AC002F010153FFFFFFFF",
        ),
        (
            "AIRCON SET_HVAC_LOWER_GUARD_LIMIT 254/172 1 , 0 0 0",
            "05AC005D0100000000",
        ),
        (
            "AIRCON SET_HVAC_LOWER_GUARD_LIMIT 254/172 1 0 65535 4 1",
            "05AC005D0101FFFF0C",
        ),
    ];
    for (index, (text, native_payload)) in boundary_commands.into_iter().enumerate() {
        let payload = checksummed(native_payload);
        let before = sys.pci.count_payload(&payload);
        let reply = command(&mut reader, &mut writer, &format!("boundary-{index}"), text).await;
        assert_eq!(reply.last().unwrap(), "200 OK.", "{text}: {reply:?}");
        assert_eq!(sys.pci.count_payload(&payload), before + 1, "{text}");
    }

    assert_eq!(
        command(&mut reader, &mut writer, "events", "EVENT ON")
            .await
            .last()
            .unwrap(),
        "200 OK."
    );
    sys.pci
        .inject(&pci_wire(&[5, 4, 0xac, 0, 5, 1, 7, 3, 1, 0]));
    let mut event = String::new();
    tokio::time::timeout(STARTUP, reader.read_line(&mut event))
        .await
        .unwrap()
        .unwrap();
    assert_eq!(
        event.trim_end_matches(['\r', '\n']),
        "#e# aircon zone_hvac_plant_status //HARNESS/254/172 1 0,1,2 3 1 0 sourceUnit=4"
    );
    assert_eq!(
        command(&mut reader, &mut writer, "events-off", "EVENT OFF")
            .await
            .last()
            .unwrap(),
        "200 OK."
    );

    let before_frames = sys.pci.frames().len();
    let bad = command(
        &mut reader,
        &mut writer,
        "bad",
        "AIRCON SET_ZONE_HVAC_MODE 254/172 1 7 3 0 1 0 1 255 23 64",
    )
    .await;
    assert_eq!(
        bad.last().unwrap(),
        "408 Operation failed: 254/172 (Zone index is out of range: 7)"
    );
    assert_eq!(sys.pci.frames().len(), before_frames);

    sys.pci.reject_next_confirmation();
    let before = sys.pci.count_payload(&refresh);
    let rejected = command(&mut reader, &mut writer, "nak", "AIRCON REFRESH 254/172 1").await;
    assert!(
        rejected
            .last()
            .unwrap()
            .starts_with("502 Air-Conditioning delivery failed: PCI rejected command"),
        "{rejected:?}"
    );
    assert_eq!(sys.pci.count_payload(&refresh), before + 1);

    // A late/negative result cannot poison the next confirmation, and MQTT
    // remains on the same PCI in both directions.
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "again",
            "AIRCON REFRESH 254/172 1"
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
    require(COMMAND_DRAIN, "MQTT command after AIRCON", || {
        sys.pci.count_payload(lighting) == before + 1
    })
    .await;

    assert_eq!(
        command(&mut reader, &mut writer, "o", "LOGOUT")
            .await
            .last()
            .unwrap(),
        "200 OK"
    );
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "locked",
            "AIRCON SET_WARD_OFF 254/172 1"
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
