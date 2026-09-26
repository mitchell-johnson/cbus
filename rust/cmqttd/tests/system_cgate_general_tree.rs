//! Real-daemon coverage for the native general/object compatibility tranche:
//! silent comments, OID, BROADCAST_EVENT, SHOW/REPORT/TREE XML variants and
//! durable NEW objects all remain local while MQTT and PCI stay live.

mod util;

use std::time::Duration;
use tokio::{
    io::{AsyncBufReadExt, AsyncWriteExt, BufReader},
    net::TcpStream,
};
use util::*;

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
        let read = tokio::time::timeout(Duration::from_secs(10), reader.read_line(&mut line))
            .await
            .unwrap_or_else(|_| panic!("timed out waiting for [{tag}] {text}"))
            .unwrap();
        assert_ne!(read, 0);
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

#[tokio::test]
async fn general_tree_objects_are_native_shaped_local_and_keep_mqtt_live() {
    let evidence: serde_json::Value = serde_json::from_str(include_str!(
        "../../testdata/fixtures/native_cgate_general_tree.json"
    ))
    .unwrap();
    assert_eq!(evidence["oracle"]["version"], "3.4.0");
    assert_eq!(evidence["oracle"]["site_project_used"], false);
    assert_eq!(evidence["comments"][0]["reply"], serde_json::Value::Null);

    let state = cbus_test_support::proc::temp_path("cgate-general-tree.json");
    let mut sys = start_with(Options {
        extra: vec![
            "--cgate-bind".into(),
            "127.0.0.1:0".into(),
            "--cgate-state".into(),
            state.to_string_lossy().into_owned(),
        ],
        ..Default::default()
    })
    .await;
    wait_started(&sys).await;
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
    tokio::time::timeout(Duration::from_secs(10), reader.read_line(&mut greeting))
        .await
        .expect("timed out waiting for C-Gate greeting")
        .unwrap();
    assert_eq!(greeting, "201 cmqttd C-Gate service ready\r\n");

    // Native untagged comments have no reply. The following tagged OID proves
    // the stream remains synchronized after both spellings.
    for comment in [
        "# hash comment\r\n",
        "// slash comment\r\n",
        "#hash-without-space\r\n",
        "//slash-without-space\r\n",
    ] {
        writer.write_all(comment.as_bytes()).await.unwrap();
        let mut unexpected = String::new();
        assert!(tokio::time::timeout(
            Duration::from_millis(100),
            reader.read_line(&mut unexpected)
        )
        .await
        .is_err());
        assert!(unexpected.is_empty());
    }
    writer.write_all(b"[hash] # tagged hash\r\n").await.unwrap();
    let mut tagged_hash = String::new();
    tokio::time::timeout(Duration::from_secs(10), reader.read_line(&mut tagged_hash))
        .await
        .expect("timed out waiting for tagged hash response")
        .unwrap();
    assert_eq!(tagged_hash, "400 Syntax Error.\r\n");
    let tagged_slash = command(&mut reader, &mut writer, "slash", "// tagged slash").await;
    assert_eq!(tagged_slash, ["400 Syntax Error."]);
    writer.write_all(b"[hash2] #tagged-hash\r\n").await.unwrap();
    tagged_hash.clear();
    tokio::time::timeout(Duration::from_secs(10), reader.read_line(&mut tagged_hash))
        .await
        .expect("timed out waiting for compact tagged hash response")
        .unwrap();
    assert_eq!(tagged_hash, "400 Syntax Error.\r\n");
    let tagged_slash = command(&mut reader, &mut writer, "slash2", "//tagged-slash").await;
    assert_eq!(tagged_slash, ["400 Syntax Error."]);

    let before_frames = sys.pci.frames().len();
    let oid = command(&mut reader, &mut writer, "oid", "OID ignored tail").await;
    assert_eq!(oid.len(), 1);
    let oid = oid[0].strip_prefix("301 OID=").unwrap();
    assert_eq!(
        oid.split('-').map(str::len).collect::<Vec<_>>(),
        [8, 4, 4, 4, 12]
    );
    assert!(matches!(
        oid.split('-').nth(3).unwrap().as_bytes()[0],
        b'8' | b'9' | b'a' | b'b'
    ));

    let capabilities = command(&mut reader, &mut writer, "caps", "CMQTT CAPABILITIES").await;
    let capabilities: serde_json::Value = serde_json::from_str(
        capabilities[0]
            .strip_prefix("200-")
            .expect("capability JSON continuation"),
    )
    .unwrap();
    assert_eq!(capabilities["tree_implicit_physical_scan"], false);
    assert_eq!(capabilities["new_objects_database_only"], true);
    assert_eq!(
        capabilities["tree_inventory_source"],
        "observed-physical-cache-plus-durable-database-objects"
    );
    assert_eq!(
        capabilities["oid_factory"],
        "non-resolvable-rfc4122-version-1"
    );
    assert_eq!(capabilities["comment_syntax"]["untagged"], "silent");
    assert_eq!(capabilities["comment_syntax"]["tagged"], "syntax-error");
    assert_eq!(
        capabilities["general_object_commands"]
            .as_array()
            .unwrap()
            .len(),
        9
    );

    for (tag, text) in [
        ("p1", "PROJECT NEW GENERAL"),
        ("p2", "PROJECT USE GENERAL"),
        ("n1", "DBCREATENET 1 General Cni loopback"),
        ("n2", "NEW GROUP //GENERAL/1/56/1 ignored"),
        ("n3", "NEW PHANTOM //GENERAL/1/56/4 128"),
        ("n4", "NEW GROUP //GENERAL/1/202/7"),
        ("n5", "NEW GROUP //GENERAL/1/203/7"),
        ("n6", "NEW UNIT //GENERAL/1/p/20 KEYE1 2.5.00"),
        ("n7", "NEW UNIT //GENERAL/1/p/22 DIMMER4 1.0.00"),
        ("n8", "NEW UNIT //GENERAL/1/p/24 BOGUS 1.0.00"),
        ("b1", "BROADCAST_EVENT SP class payload"),
    ] {
        let reply = command(&mut reader, &mut writer, tag, text).await;
        assert!(
            reply
                .last()
                .is_some_and(|line| matches!(line.as_str(), "200 OK" | "200 OK.")),
            "{text}: {reply:?}"
        );
    }

    let tree = command(
        &mut reader,
        &mut writer,
        "tree",
        "TREE //GENERAL/1 WITHSYNC",
    )
    .await;
    assert!(tree.iter().any(|line| line == "320-  Unit count=0"));
    assert!(tree
        .iter()
        .any(|line| line.contains("//GENERAL/1/p/20 ($14) type=KEYE1")));
    assert!(tree.iter().any(|line| line.ends_with("(phantom)")));
    assert_eq!(tree.last().map(String::as_str), Some("320 -end-"));

    let net_tree = command(&mut reader, &mut writer, "net-tree", "NET TREE //GENERAL/1").await;
    assert_eq!(net_tree, tree);

    let report = command(&mut reader, &mut writer, "report", "REPORT //GENERAL/1").await;
    assert_eq!(
        report
            .iter()
            .map(|line| line.strip_prefix("320").unwrap())
            .collect::<Vec<_>>(),
        tree.iter()
            .map(|line| line.strip_prefix("320").unwrap())
            .collect::<Vec<_>>()
    );
    let xml = command(&mut reader, &mut writer, "xml", "TREEXMLDETAIL //GENERAL/1").await;
    assert_eq!(
        xml.first().map(String::as_str),
        Some("343-Begin XML Snippet")
    );
    assert!(xml.iter().any(|line| line == "347-  <Type>KEYE1</Type>"));
    assert_eq!(xml.last().map(String::as_str), Some("344 End XML Snippet"));

    let show = command(
        &mut reader,
        &mut writer,
        "show",
        "SHOW //GENERAL/1/p/20 Type",
    )
    .await;
    assert_eq!(
        show.last().map(String::as_str),
        Some("300 //GENERAL/1/p/20: Type=KEYE1")
    );

    // Exercise every SHOW object family through the actual cmqttd TCP
    // listener. The detailed native fixture pins the complete ordered
    // property tables and values; these assertions prove the daemon wires
    // those model paths through without touching the PCI.
    let network_parameters =
        command(&mut reader, &mut writer, "show-net-q", "SHOW //GENERAL/1 ?").await;
    assert_eq!(network_parameters.len(), 1);
    assert!(network_parameters[0].starts_with("300 //GENERAL/1: Parameters="));
    assert!(network_parameters[0].contains("InterfaceState"));
    assert!(network_parameters[0].contains("Units"));

    let network_help = command(
        &mut reader,
        &mut writer,
        "show-net-qq",
        "SHOW //GENERAL/1 ??",
    )
    .await;
    assert_eq!(network_help.len(), 40);
    assert!(network_help
        .first()
        .unwrap()
        .starts_with("102-//GENERAL/1: "));
    assert!(network_help
        .last()
        .unwrap()
        .starts_with("102 //GENERAL/1: "));

    let network_values = command(
        &mut reader,
        &mut writer,
        "show-net-star",
        "SHOW //GENERAL/1 *",
    )
    .await;
    assert_eq!(network_values.len(), 40);
    assert!(network_values
        .iter()
        .any(|line| line.ends_with("Units=20,22,24")));
    assert!(network_values
        .iter()
        .any(|line| line.ends_with("InterfaceState=closed")));

    let application = command(
        &mut reader,
        &mut writer,
        "show-app",
        "SHOW //GENERAL/1/56 ?",
    )
    .await;
    assert_eq!(application.len(), 1);
    assert!(application[0].contains("Parameters=State,Name,LearnGroup"));
    let group = command(
        &mut reader,
        &mut writer,
        "show-group",
        "SHOW //GENERAL/1/56/1 ?",
    )
    .await;
    assert_eq!(group.len(), 1);
    assert!(group[0].contains("Parameters=Units,RampTime,Name"));

    let terminal = command(&mut reader, &mut writer, "show-output", "SHOW /p/1/22/1 ?").await;
    assert_eq!(terminal.len(), 1);
    assert!(terminal[0].starts_with("300 //GENERAL/1/p/22/1: Parameters="));
    let generic = command(
        &mut reader,
        &mut writer,
        "show-generic",
        "SHOW //GENERAL/1/p/24 ClassName",
    )
    .await;
    assert_eq!(
        generic.last().map(String::as_str),
        Some("300 //GENERAL/1/p/24: ClassName=com.clipsal.cgate.cbus.core.CBusUnit")
    );

    // GET shares the native object-discovery surface with SHOW. In
    // particular, Trigger and Enable applications must not be intercepted by
    // the live application-level reader: discovery is local and deterministic
    // for both application and child network-variable paths.
    for (application, short_name, class_name) in [
        (
            202,
            "trigger",
            "com.clipsal.cgate.cbus.app.triggercontrol.CBusTriggerControlApplication",
        ),
        (
            203,
            "enable",
            "com.clipsal.cgate.cbus.app.enablecontrol.CBusEnableControlApplication",
        ),
    ] {
        let application_path = format!("//GENERAL/1/{application}");
        let parameters = command(
            &mut reader,
            &mut writer,
            &format!("get-app-{application}-q"),
            &format!("GET {application_path} ?"),
        )
        .await;
        assert_eq!(parameters.len(), 1);
        assert!(parameters[0].starts_with(&format!("300 {application_path}: Parameters=")));

        let help = command(
            &mut reader,
            &mut writer,
            &format!("get-app-{application}-qq"),
            &format!("GET {application_path} ??"),
        )
        .await;
        assert!(help.len() >= 8);
        assert!(help
            .first()
            .unwrap()
            .starts_with(&format!("102-{application_path}: ")));
        assert!(help
            .last()
            .unwrap()
            .starts_with(&format!("102 {application_path}: ")));

        let values = command(
            &mut reader,
            &mut writer,
            &format!("get-app-{application}-star"),
            &format!("GET {application_path} *"),
        )
        .await;
        assert!(values
            .iter()
            .any(|line| line.ends_with(&format!("ShortName={short_name}"))));
        assert!(values
            .iter()
            .any(|line| line.ends_with(&format!("ClassName={class_name}"))));

        let named = command(
            &mut reader,
            &mut writer,
            &format!("get-app-{application}-case"),
            &format!("GET {application_path} cLaSsNaMe"),
        )
        .await;
        assert_eq!(
            named,
            [format!("300 {application_path}: cLaSsNaMe={class_name}")]
        );

        let child_path = format!("{application_path}/7");
        for (suffix, attribute, expected_status) in [
            ("q", "?", "300 "),
            ("qq", "??", "102"),
            ("star", "*", "300"),
        ] {
            let child = command(
                &mut reader,
                &mut writer,
                &format!("get-child-{application}-{suffix}"),
                &format!("GET {child_path} {attribute}"),
            )
            .await;
            assert!(child.first().unwrap().starts_with(expected_status));
            assert!(child.iter().all(|line| line.contains(&child_path)));
        }
        let child_named = command(
            &mut reader,
            &mut writer,
            &format!("get-child-{application}-case"),
            &format!("GET {child_path} sTaTe"),
        )
        .await;
        assert_eq!(child_named, [format!("300 {child_path}: sTaTe=error")]);
    }

    let cgate = command(&mut reader, &mut writer, "show-cgate", "SHOW cgate ?").await;
    assert_eq!(cgate.len(), 1);
    assert!(cgate[0].contains("Parameters=ProjectFreeSpace,State,DatabaseVersion"));
    let projects = command(
        &mut reader,
        &mut writer,
        "show-projects",
        "SHOW projects ??",
    )
    .await;
    assert_eq!(projects.len(), 3);
    assert!(projects.last().unwrap().contains("NetStateInterval"));
    let cbus = command(&mut reader, &mut writer, "show-cbus", "SHOW cbus *").await;
    assert!(cbus.iter().any(|line| line.ends_with("Networks=1")));
    let project = command(&mut reader, &mut writer, "show-project", "SHOW //GENERAL *").await;
    assert!(project.iter().any(|line| line.ends_with("Networks=1")));
    let frames = sys.pci.frames();
    let unexpected_frames = frames[before_frames..]
        .iter()
        .filter(|frame| !is_status_request(&frame.payload))
        .collect::<Vec<_>>();
    assert!(
        unexpected_frames.is_empty(),
        "local C-Gate commands emitted non-background PCI frames: {unexpected_frames:?}"
    );

    let payload = "053800790149";
    let before = sys.pci.count_payload(payload);
    sys.broker
        .inject("homeassistant/light/cbus_1/set", br#"{"state":"ON"}"#);
    require(COMMAND_DRAIN, "MQTT after general commands", || {
        sys.pci.count_payload(payload) > before
    })
    .await;
    assert!(sys.daemon.is_running());
    drop(sys);
    std::fs::remove_file(state).unwrap();
}
