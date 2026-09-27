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

    let set_model = command(
        &mut reader,
        &mut writer,
        "model",
        r#"DALI SESSION SET commissioning /cdg/daliLines/0/daliEcgs [null,null,null,{\"shortAddress\":3,\"isKnown\":true,\"deviceTypes\":{\"deviceTypes\":[\"EMERGENCY\"]}}]"#,
    )
    .await;
    assert_eq!(set_model.last().unwrap(), "200 OK.", "{set_model:?}");

    let discover = "061400E481DA1A03";
    let common = "061400E481DA1203";
    let emergency = "061400E481DA1803";
    let before_discover = sys.pci.count_payload(discover);
    let before_common = sys.pci.count_payload(common);
    let before_emergency = sys.pci.count_payload(emergency);
    let request = command(
        &mut reader,
        &mut writer,
        "refresh",
        "DALI SESSION EXTRACT commissioning !dali-gateway-20 A REFRESH_STATUS_INFO 3",
    );
    let peer = async {
        require(COMMAND_DRAIN, "typed DALI status discovery", || {
            sys.pci.count_payload(discover) == before_discover + 1
        })
        .await;
        sys.pci.inject(&pci_wire(&[
            0x86, 20, 0x10, 0, 0xe5, 0x83, 0xda, 0x1a, 0, 3,
        ]));
        require(COMMAND_DRAIN, "typed DALI common status read", || {
            sys.pci.count_payload(common) == before_common + 1
        })
        .await;
        sys.pci.inject(&pci_wire(&[
            0x86, 20, 0x10, 0, 0xe8, 0x83, 0xda, 0x12, 0, 3, 2, 5, 0xa0,
        ]));
        require(COMMAND_DRAIN, "typed DALI emergency status read", || {
            sys.pci.count_payload(emergency) == before_emergency + 1
        })
        .await;
        sys.pci.inject(&pci_wire(&[
            0x86, 20, 0x10, 0, 0xec, 0x83, 0xda, 0x18, 0, 3, 1, 2, 3, 4, 5, 6, 7,
        ]));
    };
    let (refresh, ()) = tokio::join!(request, peer);
    assert_eq!(refresh.last().unwrap(), "200 OK.", "{refresh:?}");
    assert!(refresh
        .iter()
        .any(|line| line == "120-progress: 3/3, plan: GET_EMERGENCY_STATUS_ECG"));
    let common_model = command(
        &mut reader,
        &mut writer,
        "common-model",
        "DALI SESSION GET commissioning /cdg/daliLines/0/daliEcgs/3/commonReadOnlyParams102",
    )
    .await;
    assert!(common_model
        .iter()
        .any(|line| line.contains("\"physicalMinimumLevel\":5")));
    let emergency_model = command(
        &mut reader,
        &mut writer,
        "emergency-model",
        "DALI SESSION GET commissioning /cdg/daliLines/0/daliEcgs/3/emergencyStatus202",
    )
    .await;
    assert!(emergency_model
        .iter()
        .any(|line| line.contains("\"lampTotalTime\":7")));

    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "new-readonly",
            "DALI SESSION NEW readonly"
        )
        .await
        .last()
        .unwrap(),
        "200 OK."
    );
    let empty_mask = vec![0; 8];
    let readonly_steps = [
        ("061400E381DA0D", 13, vec![0]),
        ("061400E382DA07", 7, empty_mask.clone()),
        ("061400E381DA0A", 10, empty_mask.clone()),
        ("061400E381DA0B", 11, empty_mask.clone()),
        ("061400E381DA09", 9, empty_mask.clone()),
        ("061400E381DA03", 3, Vec::new()),
        ("061400E381DA04", 4, empty_mask),
    ];
    let readonly_before = readonly_steps
        .iter()
        .map(|(wire, _, _)| sys.pci.count_payload(wire))
        .collect::<Vec<_>>();
    let request = command(
        &mut reader,
        &mut writer,
        "dali-only",
        "DALI SESSION EXTRACT readonly !dali-gateway-20 A DALI_ONLY 3",
    );
    let peer = async {
        for ((wire, operation, data), before) in readonly_steps.iter().zip(readonly_before.iter()) {
            require(COMMAND_DRAIN, "DALI_ONLY native plan step", || {
                sys.pci.count_payload(wire) == before + 1
            })
            .await;
            let mut reply = vec![
                0x86,
                20,
                0x10,
                0,
                0xe4 + u8::try_from(data.len()).unwrap(),
                0x83,
                0xda,
                *operation,
                0,
            ];
            reply.extend_from_slice(data);
            sys.pci.inject(&pci_wire(&reply));
        }
    };
    let (dali_only, ()) = tokio::join!(request, peer);
    assert_eq!(dali_only.last().unwrap(), "200 OK.", "{dali_only:?}");
    assert!(dali_only
        .iter()
        .any(|line| line == "120-progress: 15/15, plan: GET_EMERGENCY_STATUS_ECG"));
    let known_model = command(
        &mut reader,
        &mut writer,
        "known-model",
        "DALI SESSION GET readonly /cdg/daliLines/0/daliEcgs/3/isKnown",
    )
    .await;
    assert!(known_model.iter().any(|line| line == "120-false"));

    for selector in ["COND_QUICK", "COND_EXTENDED", "RESCAN_FAULT"] {
        let mut preflight = Vec::new();
        if selector == "RESCAN_FAULT" {
            preflight.push(("061400E381DA0E", 14, Vec::new()));
        }
        preflight.push(("061400E382DA04", 4, vec![0x08, 0, 0, 0, 0, 0, 0, 0]));
        preflight.push(("061400E381DA0B", 11, vec![0; 8]));
        let before = preflight
            .iter()
            .map(|(wire, _, _)| sys.pci.count_payload(wire))
            .collect::<Vec<_>>();
        let address_unknown_before = sys.pci.count_payload("061400E381DA02");
        let extract = format!("DALI SESSION EXTRACT readonly !dali-gateway-20 A {selector}");
        let request = command(&mut reader, &mut writer, "mutating", &extract);
        let peer = async {
            for ((wire, operation, data), count) in preflight.iter().zip(before.iter()) {
                require(COMMAND_DRAIN, "DALI mutation preflight step", || {
                    sys.pci.count_payload(wire) == count + 1
                })
                .await;
                let mut reply = vec![
                    0x86,
                    20,
                    0x10,
                    0,
                    0xe4 + u8::try_from(data.len()).unwrap(),
                    0x83,
                    0xda,
                    *operation,
                    0,
                ];
                reply.extend_from_slice(data);
                sys.pci.inject(&pci_wire(&reply));
            }
        };
        let (refused, ()) = tokio::join!(request, peer);
        assert!(
            refused
                .last()
                .unwrap()
                .contains("no device-to-address receipt"),
            "{selector}: {refused:?}"
        );
        assert_eq!(
            sys.pci.count_payload("061400E381DA02"),
            address_unknown_before,
            "{selector} reached ADDRESS_UNKNOWN"
        );
        let unchanged_model = command(
            &mut reader,
            &mut writer,
            "unchanged-model",
            "DALI SESSION GET readonly /cdg/daliLines/0/daliEcgs/3/isKnown",
        )
        .await;
        assert!(
            unchanged_model.iter().any(|line| line == "120-false"),
            "{selector}: {unchanged_model:?}"
        );
    }

    for selector in ["DALI_ONLY", "FULL"] {
        let frame_count = sys.pci.frames().len();
        let unsupported = command(
            &mut reader,
            &mut writer,
            "typed-deploy",
            &format!("DALI SESSION DEPLOY commissioning !dali-gateway-20 BOTH {selector}"),
        )
        .await;
        assert!(
            unsupported
                .last()
                .unwrap()
                .contains("per-field readback receipts"),
            "{selector}: {unsupported:?}"
        );
        assert_eq!(sys.pci.frames().len(), frame_count, "{selector}");
    }
    assert!(sys.daemon.is_running());

    drop(sys);
    for path in [state, token, project] {
        std::fs::remove_file(path).unwrap();
    }
}
