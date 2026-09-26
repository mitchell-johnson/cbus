//! Real cmqttd process: retained C-Gate 3.4 DALI core/emergency commands use
//! source-correlated extended CAL on the same live PCI as MQTT traffic.

mod util;

use serde_json::Value;
use tokio::{
    io::{AsyncBufReadExt, AsyncWriteExt, BufReader},
    net::TcpStream,
};
use util::*;

const TOKEN: &str = "throwaway-dali-system-token-0123456789abcdef";

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

#[tokio::test]
async fn dali_core_and_emergency_are_correlated_authenticated_and_keep_mqtt_live() {
    let state = cbus_test_support::proc::temp_path("cgate-dali.json");
    let token = cbus_test_support::proc::temp_path("cgate-dali.token");
    let project = cbus_test_support::proc::temp_path("cgate-dali.xml");
    std::fs::write(&token, format!("{TOKEN}\n")).unwrap();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&token, std::fs::Permissions::from_mode(0o600)).unwrap();
    }
    let xml = std::fs::read_to_string(project_file())
        .unwrap()
        .replace(
            "</Network>",
            r#"<Unit oid="dali-gateway-20"><Address>20</Address><TagName>DALI Gateway</TagName><UnitType>SYS_DAL2</UnitType><FirmwareVersion>1.10.0</FirmwareVersion><SerialNumber>101136.1558</SerialNumber></Unit></Network>"#,
        );
    std::fs::write(&project, xml).unwrap();

    let mut sys = start_with(Options {
        project: false,
        extra: vec![
            "-P".into(),
            project.to_string_lossy().into_owned(),
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

    let help = command(&mut reader, &mut writer, "h", "HELP DALI EMERGENCY REST").await;
    assert_eq!(
        help.first().unwrap(),
        "101-Help: syntax: dali emergency rest [mode=(auto)] <cdg-object-id> <line> [ecg-address=($50)]"
    );
    assert_eq!(
        help.last().unwrap(),
        "101 Help: [ecg-address=($50)] refers to short address, broadcast address or group address"
    );
    let capabilities = command(&mut reader, &mut writer, "c", "CMQTT CAPABILITIES").await;
    let capability_json: Value =
        serde_json::from_str(capabilities[0].strip_prefix("200-").unwrap()).unwrap();
    assert_eq!(capability_json["dali_core_commands"], 48);
    assert_eq!(capability_json["dali_emergency_commands"], 14);
    assert_eq!(capability_json["dali_physical_leaf_commands"], 103);
    assert_eq!(capability_json["dali_local_help_roots"], 6);
    assert_eq!(capability_json["dali_specialized_local_leaf_commands"], 19);
    assert_eq!(
        capability_json["dali_specialized_physical_leaf_commands"],
        41
    );
    assert_eq!(capability_json["dali_specialized_commands_fail_closed"], 0);
    assert_eq!(capability_json["dali_full_compatibility"], false);
    assert_eq!(capability_json["dali_auto_poll_limit"], 10);
    assert_eq!(
        capability_json["dali_delivery_semantics"],
        "source-correlated-exactly-once-no-replay"
    );

    let factory = "061400E881DA01501606B118";
    let before = sys.pci.count_payload(factory);
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "locked",
            "DALI FACTORY_RESET EXEC //HARNESS/254/p/20 A",
        )
        .await
        .last()
        .unwrap(),
        "420 LOGIN required"
    );
    assert_eq!(sys.pci.count_payload(factory), before);

    // A read command remains open under the mutation-only gate. While it is
    // waiting for its correlated gateway reply, MQTT can still use the PCI.
    let known = "061400E381DA87";
    let before_known = sys.pci.count_payload(known);
    let before_lighting = sys.pci.count_payload("0538000101C1");
    let request = command(
        &mut reader,
        &mut writer,
        "known",
        "DALI KNOWN EXEC //HARNESS/254/p/20 B",
    );
    let peer = async {
        require(COMMAND_DRAIN, "DALI execute reaches PCI once", || {
            sys.pci.count_payload(known) == before_known + 1
        })
        .await;
        sys.broker
            .inject("homeassistant/light/cbus_1/set", br#"{"state":"OFF"}"#);
        require(COMMAND_DRAIN, "MQTT command while DALI is pending", || {
            sys.pci.count_payload("0538000101C1") == before_lighting + 1
        })
        .await;
        sys.pci.inject(&pci_wire(&[
            0x86, 20, 0x10, 0x00, 0xe6, 0x83, 0xda, 0x87, 0, 0xaa, 0x55,
        ]));
    };
    let (reply, ()) = tokio::join!(request, peer);
    assert_eq!(reply.last().unwrap(), "200 OK.", "{reply:?}");
    assert!(reply
        .iter()
        .any(|line| line == "120-DaliCommand=KNOWN: $87 (EXECUTE)"));
    assert!(reply.iter().any(|line| line == "320-ResponsePayload=AA55"));
    assert_eq!(sys.pci.count_payload(known), before_known + 1);

    assert_eq!(
        command(&mut reader, &mut writer, "login", &format!("LOGIN {TOKEN}"))
            .await
            .last()
            .unwrap(),
        "200 OK"
    );
    let rest = "061400E481DA5350";
    let before_rest = sys.pci.count_payload(rest);
    let request = command(
        &mut reader,
        &mut writer,
        "rest",
        "DALI EMERGENCY REST EXEC !dali-gateway-20 A",
    );
    let peer = async {
        require(COMMAND_DRAIN, "DALI emergency execute", || {
            sys.pci.count_payload(rest) == before_rest + 1
        })
        .await;
        sys.pci.inject(&pci_wire(&[
            0x86, 20, 0x10, 0x00, 0xe4, 0x83, 0xda, 0x53, 0,
        ]));
    };
    let (reply, ()) = tokio::join!(request, peer);
    assert_eq!(reply.last().unwrap(), "200 OK.", "{reply:?}");
    assert!(reply
        .iter()
        .any(|line| line == "120-DaliCommand=EMERGENCY_RESET: $53 (EXECUTE)"));
    assert_eq!(sys.pci.count_payload(rest), before_rest + 1);

    let before_frames = sys.pci.frames().len();
    for (tag, text) in [
        ("bad-line", "DALI KNOWN EXEC //HARNESS/254/p/20 C"),
        ("bad-unit", "DALI KNOWN EXEC //HARNESS/254/p/21 A"),
        ("native-status", "DALI KNOWN STATUS //HARNESS/254/p/20 A"),
    ] {
        let reply = command(&mut reader, &mut writer, tag, text).await;
        assert!(reply.last().unwrap().starts_with('4'), "{text}: {reply:?}");
    }
    assert_eq!(sys.pci.frames().len(), before_frames);
    assert!(sys.daemon.is_running());

    drop(sys);
    for path in [state, token, project] {
        std::fs::remove_file(path).unwrap();
    }
}
