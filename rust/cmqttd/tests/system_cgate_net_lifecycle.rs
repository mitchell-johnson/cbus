//! Real cmqttd process: the native-evidenced NET catalogue and runtime
//! lifecycle coexist with MQTT while physical management shares its PCI.

mod util;

use serde_json::{json, Value};
use tokio::{
    io::{AsyncBufReadExt, AsyncWriteExt, BufReader},
    net::TcpStream,
};
use util::*;

const TOKEN: &str = "throwaway-net-lifecycle-system-token-0123456789abcdef";

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
        let line = line.trim_end_matches(['\r', '\n']);
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
async fn net_lifecycle_is_durable_confirmed_authenticated_and_keeps_mqtt_live() {
    let state = cbus_test_support::proc::temp_path("cgate-net-lifecycle.json");
    let token = cbus_test_support::proc::temp_path("cgate-net-lifecycle.token");
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

    let net_help = command(&mut reader, &mut writer, "help-net", "NET").await;
    assert_eq!(net_help.len(), 24);
    assert_eq!(net_help[0], "101-Help: NET commands:");
    assert_eq!(
        net_help.last().unwrap(),
        "101 Help:  NET UNRAVELUNIT - Unravel a unit address."
    );
    assert_eq!(
        command(&mut reader, &mut writer, "help-network", "NETWORK")
            .await
            .last()
            .unwrap(),
        "101 Help:  NETWORK LOCATE - Send a locate message on the network application"
    );
    assert_eq!(
        command(&mut reader, &mut writer, "help-topology", "TOPOLOGY")
            .await
            .last()
            .unwrap(),
        "101 Help:  TOPOLOGY EXPLORE - Explore the topology of a set of network connections"
    );
    let capabilities = command(&mut reader, &mut writer, "caps", "CMQTT CAPABILITIES").await;
    let capabilities: Value =
        serde_json::from_str(capabilities[0].strip_prefix("200-").unwrap()).unwrap();
    assert_eq!(capabilities["net_catalog_storage"], "cmqttd-json");
    assert_eq!(capabilities["net_catalog_file_storage"], "cmqttd-internal");
    assert_eq!(capabilities["net_learn"], true);
    assert_eq!(capabilities["network_locate"], true);
    assert_eq!(
        capabilities["network_management_delivery_semantics"],
        "pci-confirmed-exactly-once-no-replay"
    );
    assert_eq!(capabilities["net_lifecycle_fail_closed"], json!([]));
    assert_eq!(capabilities["net_open_close_preserves_mqtt"], true);
    assert_eq!(capabilities["project_runtime_start_stop"], true);
    assert_eq!(capabilities["net_unravel_direct_safe_planner"], true);
    assert_eq!(capabilities["topology_explore_physical"], true);

    let learn = checksummed("053800030101FE");
    let before = sys.pci.count_payload(&learn);
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "locked",
            "NET LEARN //HARNESS/254 56 1 1"
        )
        .await
        .last()
        .unwrap(),
        "420 LOGIN required"
    );
    assert_eq!(sys.pci.count_payload(&learn), before);
    assert_eq!(
        command(&mut reader, &mut writer, "login", &format!("LOGIN {TOKEN}"))
            .await
            .last()
            .unwrap(),
        "200 OK"
    );

    let before_frames = sys.pci.frames().len();
    for (tag, text) in [
        ("create", "NET CREATE GARAGE cni 127.0.0.1:10001 owned=yes"),
        ("save", "NET SAVE FILE"),
        ("rename", "NET RENAME GARAGE SHED"),
        ("flush", "NET FLUSH SHED"),
        ("delete", "NET DELETE SHED"),
    ] {
        assert_eq!(
            command(&mut reader, &mut writer, tag, text)
                .await
                .last()
                .unwrap(),
            "200 OK."
        );
    }
    assert_eq!(
        sys.pci.frames().len(),
        before_frames,
        "local NET catalogue commands must not write to PCI"
    );
    assert_eq!(
        command(&mut reader, &mut writer, "obsolete", "NET STATE_INTERVAL 1")
            .await
            .last()
            .unwrap(),
        "400 Syntax Error: This command is obsolete.  Please use 'set projects NetStateInterval X' instead."
    );

    for (tag, text, native_payload) in [
        ("learn", "NET LEARN //HARNESS/254 56 1 1", "053800030101FE"),
        (
            "locate-unit",
            "NETWORK LOCATE //HARNESS/254/208 UNIT 1 ON",
            "05D00013FF0101",
        ),
        (
            "locate-serial",
            "NETWORK LOCATE 254/$D0 SERIAL 1 12345.67 255",
            "05D000160103039043FF",
        ),
    ] {
        let payload = checksummed(native_payload);
        let before = sys.pci.count_payload(&payload);
        assert_eq!(
            command(&mut reader, &mut writer, tag, text)
                .await
                .last()
                .unwrap(),
            "200 OK."
        );
        assert_eq!(sys.pci.count_payload(&payload), before + 1, "{text}");
    }

    let group_locate = checksummed("05D00013380100");
    sys.pci.reject_next_confirmation();
    let before = sys.pci.count_payload(&group_locate);
    let rejected = command(
        &mut reader,
        &mut writer,
        "nak",
        "NETWORK LOCATE 254/208 GROUP 56 1 OFF",
    )
    .await;
    assert!(
        rejected
            .last()
            .unwrap()
            .starts_with("502 NETWORK LOCATE failed: PCI rejected command"),
        "{rejected:?}"
    );
    assert_eq!(sys.pci.count_payload(&group_locate), before + 1);

    // Runtime close/stop clears volatile C-Gate observations while retaining
    // ownership of cmqttd's shared PCI; open/start restores the bound runtime
    // network without making another CNI connection.
    let before_frames = sys.pci.frames().len();
    for (tag, text) in [
        ("close", "NET CLOSE //HARNESS/254"),
        ("open", "NET OPEN //HARNESS/254"),
        ("stop", "PROJECT STOP HARNESS"),
        ("start", "PROJECT START HARNESS"),
    ] {
        let response = command(&mut reader, &mut writer, tag, text).await;
        assert!(
            response.last().unwrap().starts_with("200 OK"),
            "{text}: {response:?}"
        );
    }
    assert_eq!(sys.pci.frames().len(), before_frames);
    assert_eq!(sys.pci.connections(), 1);
    assert_eq!(
        command(&mut reader, &mut writer, "bad-topo", "TOPOLOGY EXPLORE bad").await,
        [
            "470-Bad interface specification for NET0 bad",
            "408 Operation failed: bad interface specification"
        ]
    );

    // NET management has no MQTT state schema. Ordinary lighting still
    // flows both ways over the same broker and shared fake PCI.
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
    require(COMMAND_DRAIN, "MQTT command after NET management", || {
        sys.pci.count_payload(lighting) == before + 1
    })
    .await;

    assert!(sys.daemon.is_running());
    drop(sys);
    std::fs::remove_file(state).unwrap();
    std::fs::remove_file(token).unwrap();
}
