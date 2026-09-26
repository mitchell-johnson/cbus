//! Real cmqttd process: specialized DALI memory and session commands share
//! the live PCI with MQTT, retain LOGIN boundaries, and verify writes before
//! reporting success.

mod util;

use tokio::{
    io::{AsyncBufReadExt, AsyncWriteExt, BufReader},
    net::TcpStream,
};
use util::*;

const TOKEN: &str = "throwaway-dali-specialized-token-0123456789abcdef";

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
async fn specialized_dali_memory_sessions_and_mqtt_share_the_real_daemon() {
    let state = cbus_test_support::proc::temp_path("cgate-dali-specialized.json");
    let token = cbus_test_support::proc::temp_path("cgate-dali-specialized.token");
    let project = cbus_test_support::proc::temp_path("cgate-dali-specialized.xml");
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

    let recall = "4614001B020901";
    let before_recall = sys.pci.count_payload(recall);
    let before_lighting = sys.pci.count_payload("0538000101C1");
    let request = command(
        &mut reader,
        &mut writer,
        "read",
        "DALI ERROR_REPORTING STORE_OPTION //HARNESS/254/p/20",
    );
    let peer = async {
        require(COMMAND_DRAIN, "specialized DALI recall", || {
            sys.pci.count_payload(recall) == before_recall + 1
        })
        .await;
        sys.broker
            .inject("homeassistant/light/cbus_1/set", br#"{"state":"OFF"}"#);
        require(
            COMMAND_DRAIN,
            "MQTT remains live during DALI recall",
            || sys.pci.count_payload("0538000101C1") == before_lighting + 1,
        )
        .await;
        sys.pci
            .inject(&pci_wire(&[0x86, 20, 0x10, 0, 0x82, 0x09, 0xab]));
    };
    let (reply, ()) = tokio::join!(request, peer);
    assert_eq!(reply.last().unwrap(), "200 OK.", "{reply:?}");
    assert!(reply.iter().any(|line| line.ends_with("Address=$0209")));
    assert!(reply.iter().any(|line| line.ends_with("$AB")));

    let before_frames = sys.pci.frames().len();
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "locked",
            "DALI ERROR_REPORTING SET_STORE_OPTION //HARNESS/254/p/20 170",
        )
        .await
        .last()
        .unwrap(),
        "420 LOGIN required"
    );
    assert_eq!(sys.pci.frames().len(), before_frames);
    assert_eq!(
        command(&mut reader, &mut writer, "login", &format!("LOGIN {TOKEN}"))
            .await
            .last()
            .unwrap(),
        "200 OK"
    );

    let set = command(
        &mut reader,
        &mut writer,
        "set",
        "DALI ERROR_REPORTING SET_STORE_OPTION //HARNESS/254/p/20 170",
    );
    let peer = async {
        require(COMMAND_DRAIN, "DALI page select", || {
            sys.pci.count_payload("4614003902") >= 1
        })
        .await;
        sys.pci.inject(&pci_wire(&[0x86, 20, 0x10, 0, 0x81, 0x02]));
        require(COMMAND_DRAIN, "DALI paged store", || {
            sys.pci
                .payloads()
                .iter()
                .any(|payload| payload.starts_with("461400A30900AA"))
        })
        .await;
        sys.pci
            .inject(&pci_wire(&[0x86, 20, 0x10, 0, 0x32, 0x09, 0x00]));
        require(COMMAND_DRAIN, "DALI paged write verification", || {
            sys.pci.count_payload(recall) == before_recall + 2
        })
        .await;
        sys.pci
            .inject(&pci_wire(&[0x86, 20, 0x10, 0, 0x82, 0x09, 0xaa]));
    };
    let (reply, ()) = tokio::join!(set, peer);
    assert_eq!(reply.last().unwrap(), "200 OK.", "{reply:?}");

    let frame_count = sys.pci.frames().len();
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "new",
            "DALI SESSION NEW commissioning"
        )
        .await
        .last()
        .unwrap(),
        "200 OK."
    );
    let listed = command(&mut reader, &mut writer, "list", "DALI SESSION LIST").await;
    assert!(listed.iter().any(|line| line.contains("commissioning")));
    let unsupported = command(
        &mut reader,
        &mut writer,
        "full",
        "DALI SESSION DEPLOY commissioning !dali-gateway-20 BOTH FULL",
    )
    .await;
    assert!(unsupported.last().unwrap().starts_with("502 "));
    assert_eq!(sys.pci.frames().len(), frame_count);
    assert!(sys.daemon.is_running());

    drop(sys);
    for path in [state, token, project] {
        std::fs::remove_file(path).unwrap();
    }
}
