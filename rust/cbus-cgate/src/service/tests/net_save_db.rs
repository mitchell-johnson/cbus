use super::*;

async fn run(service: &Arc<Service>, client: &mut ClientState, command: &str) -> Response {
    service
        .handle(client, &format!("[save-db] {command}"))
        .await
}

async fn command(service: &Arc<Service>, client: &mut ClientState, text: &str) {
    let reply = run(service, client, text).await;
    assert_eq!(
        reply.status,
        if matches!(
            text,
            "DBADDSAFE //HARNESS/254 Unit 6 Added" | "DBADDSAFE //AUX/42 Unit 6 Unit"
        ) {
            301
        } else {
            200
        },
        "{text}: {reply:?}"
    );
}

async fn record(service: &Arc<Service>, project: &str, name: &str) -> crate::TagNetwork {
    service.model.lock().await.projects[project].tag_networks[name].clone()
}

async fn no_io(remote: &mut tokio::io::DuplexStream) {
    assert!(
        tokio::time::timeout(Duration::from_millis(20), remote.read_u8())
            .await
            .is_err()
    );
}

#[tokio::test]
async fn net_save_db_materializes_complete_native_names_properties_and_fresh_property_oids() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    for text in [
        "PROJECT NEW SAVE",
        "PROJECT USE SAVE",
        "NET CREATE 42 Cni 127.0.0.1:1",
        "NET CREATE CustomA Serial /private/tmp/owned-absent-port",
        "NET CREATE Extra Bridge 254/p/42 owned=yes second=two",
        "NET CREATE 0254 Cni 127.0.0.1:2",
        "NET CREATE 256 Cni 127.0.0.1:3",
        "NET CREATE 255 Cni 127.0.0.1:5",
        "NET CREATE 0xff Cni 127.0.0.1:6",
        "NET CREATE Customa Cni 127.0.0.1:4",
        "NET SAVE DB",
    ] {
        command(&service, &mut client, text).await;
    }
    let xml = run(&service, &mut client, "DBGETXML //SAVE").await.lines[0]
        .strip_prefix("347-")
        .unwrap()
        .to_string();
    let parsed = roxmltree::Document::parse(&xml).unwrap();
    let created_order = parsed
        .descendants()
        .filter(|node| node.has_tag_name("Network"))
        .map(|node| {
            node.children()
                .find(|child| child.has_tag_name("Address"))
                .unwrap()
                .text()
                .unwrap()
        })
        .collect::<Vec<_>>();
    assert_eq!(
        created_order,
        ["42", "CustomA", "Extra", "0254", "256", "255", "0xff", "Customa"]
    );
    // Catalogue display remains the separately established lexical list; it
    // must never reorder storage or the native SAVE DB append projection.
    let listed = run(&service, &mut client, "NET LIST").await;
    assert_eq!(listed.status, 131);
    let mut expected_list = created_order
        .iter()
        .map(|name| format!("network={name} State=new InterfaceState=closed"))
        .collect::<Vec<_>>();
    expected_list.sort();
    assert_eq!(
        listed
            .lines
            .iter()
            .chain(std::iter::once(&listed.final_text))
            .cloned()
            .collect::<Vec<_>>(),
        expected_list
    );
    let original = record(&service, "SAVE", "Extra").await;
    for name in ["42", "CustomA", "Extra", "0254", "256", "Customa"] {
        let saved = record(&service, "SAVE", name).await;
        assert_eq!(saved.root.field("Address"), Some(name));
        assert_eq!(
            saved.root.field("TagName"),
            Some(format!("n{name}").as_str())
        );
        assert_eq!(saved.root.field("NetworkNumber"), Some("0xff"));
        assert_eq!(saved.database_network, None);
        assert_eq!(
            run(&service, &mut client, &format!("DBGETXML //SAVE/{name}"))
                .await
                .lines,
            run(
                &service,
                &mut client,
                &format!("DBGETXML !{}", saved.root.field("OID").unwrap())
            )
            .await
            .lines
        );
    }
    assert!(service.model.lock().await.projects["SAVE"]
        .networks
        .is_empty());
    assert_eq!(original.options(), ["owned=yes", "second=two"]);
    command(&service, &mut client, "NET SAVE DB").await;
    let repeated = record(&service, "SAVE", "Extra").await;
    assert_eq!(original.root.field("OID"), repeated.root.field("OID"));
    assert_eq!(
        original.interface().field("OID"),
        repeated.interface().field("OID")
    );
    assert_eq!(original.options(), repeated.options());
    assert_ne!(
        original.interface().children[0].field("OID"),
        repeated.interface().children[0].field("OID")
    );
    let model = service.model.lock().await;
    assert!(!model
        .known_oids
        .contains(original.interface().children[0].field("OID").unwrap()));
    drop(model);
    no_io(&mut remote).await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn net_save_db_keeps_explicit_project_save_boundary_and_restart_identity() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    for text in [
        "PROJECT NEW SAVE",
        "PROJECT USE SAVE",
        "PROJECT SAVE SAVE",
        "NET CREATE 42 Cni 127.0.0.1:1",
        "NET SAVE FILE",
        "NET SAVE DB",
    ] {
        command(&service, &mut client, text).await;
    }
    let before_close = Database::from_server(&*service.model.lock().await);
    std::fs::remove_file(&path).unwrap();
    std::fs::create_dir(&path).unwrap();
    assert_eq!(
        run(&service, &mut client, "PROJECT CLOSE SAVE")
            .await
            .final_text,
        "500 Database commit failed; change rolled back"
    );
    assert!(Database::from_server(&*service.model.lock().await) == before_close);
    assert_eq!(client.current.as_deref(), Some("SAVE"));
    std::fs::remove_dir(&path).unwrap();
    command(&service, &mut client, "PROJECT CLOSE SAVE").await;
    command(&service, &mut client, "PROJECT LOAD SAVE").await;
    assert!(service.model.lock().await.projects["SAVE"]
        .tag_networks
        .is_empty());
    assert_eq!(
        run(&service, &mut client, "NET LIST").await.final_text,
        "132 no networks found"
    );
    command(&service, &mut client, "NET LOAD DB").await;
    assert_eq!(
        run(&service, &mut client, "NET LIST").await.final_text,
        "132 no networks found"
    );
    // A separate FILE snapshot survives this loaded/saved DB boundary.
    command(&service, &mut client, "NET LOAD FILE").await;
    assert_eq!(run(&service, &mut client, "NET LIST").await.status, 131);
    command(&service, &mut client, "NET DELETE 42").await;
    for text in [
        "NET CREATE 42 Cni 127.0.0.1:1",
        "NET SAVE DB",
        "PROJECT SAVE SAVE",
        "PROJECT CLOSE SAVE",
        "PROJECT LOAD SAVE",
    ] {
        command(&service, &mut client, text).await;
    }
    let before = record(&service, "SAVE", "42").await;
    no_io(&mut remote).await;
    drop(service);
    let (pci_client, mut remote) = pci();
    let restarted = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState {
        current: Some("SAVE".to_string()),
        ..Default::default()
    };
    assert_eq!(record(&restarted, "SAVE", "42").await, before);
    command(&restarted, &mut client, "NET DELETE 42").await;
    command(&restarted, &mut client, "NET LOAD DB").await;
    let model = restarted.model.lock().await;
    let key = format!("@cmqttd/net-catalog/v1/{}/active", hex::encode("SAVE"));
    let definitions: serde_json::Value = serde_json::from_str(&model.config_values[&key]).unwrap();
    assert!(definitions[0]["bound_network"].is_null());
    assert!(model.projects["SAVE"].networks.is_empty());
    drop(model);
    no_io(&mut remote).await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn net_save_db_existing_configured_tag_refresh_never_rebinds_and_xml_roundtrips() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    command(
        &service,
        &mut client,
        "DBSETSAFE //HARNESS/254/p/5/UnitName Fixture eDLT",
    )
    .await;
    command(&service, &mut client, "NET CLOSE 254").await;
    let original = service.model.lock().await.projects["HARNESS"].networks[&254].clone();
    for text in [
        "NET DELETE 254",
        "NET CREATE 254 Serial /private/tmp/owned-absent-port one=two",
        "NET SAVE DB",
    ] {
        command(&service, &mut client, text).await;
    }
    let saved = record(&service, "HARNESS", "254").await;
    assert_eq!(saved.root.field("OID"), Some(original.oid.as_str()));
    assert_eq!(
        saved.interface().field("OID"),
        Some(original.interface_oid.as_str())
    );
    assert_eq!(saved.root.field("TagName"), Some(original.name.as_str()));
    assert_eq!(saved.root.field("NetworkNumber"), Some("254"));
    assert_eq!(saved.interface().field("InterfaceType"), Some("Serial"));
    assert_eq!(
        service.model.lock().await.projects["HARNESS"].networks[&254],
        original
    );
    let document = saved.root.document();
    let reply = service
        .handle_document(&mut client, "[save-db] DBSETXML //HARNESS/254", &document)
        .await;
    assert_eq!(reply.status, 301, "{reply:?}");
    assert_eq!(
        service.model.lock().await.projects["HARNESS"].networks[&254].iface_addr,
        original.iface_addr
    );
    let incompatible = document.replace("owned-absent-port", "owned-different-port");
    assert_eq!(
        service
            .handle_document(
                &mut client,
                "[save-db] DBSETXML //HARNESS/254",
                &incompatible
            )
            .await
            .status,
        408
    );
    assert_eq!(record(&service, "HARNESS", "254").await, saved);
    no_io(&mut remote).await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn net_save_db_database_fields_children_copy_archive_and_oid_delete_are_authoritative() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    for text in [
        "PROJECT NEW SAVE",
        "PROJECT USE SAVE",
        "NET CREATE CustomA Cni 127.0.0.1:1 owned=yes second=two",
        "NET SAVE DB",
    ] {
        command(&service, &mut client, text).await;
    }
    let original = record(&service, "SAVE", "CustomA").await;
    let oid = original.root.field("OID").unwrap();
    let iface = original.interface().field("OID").unwrap();
    let property = original.interface().children[0].field("OID").unwrap();
    for text in [
        format!("DBSET !{oid}/TagName Updated"),
        format!("DBSET !{iface}/InterfaceAddress 127.0.0.1:2"),
        format!("DBSET !{property}/Value changed"),
    ] {
        command(&service, &mut client, &text).await;
    }
    assert_eq!(
        record(&service, "SAVE", "CustomA").await.options(),
        ["owned=changed", "second=two"]
    );
    command(&service, &mut client, &format!("DBDELETE !{property}")).await;
    assert_eq!(
        record(&service, "SAVE", "CustomA").await.options(),
        ["second=two"]
    );
    for text in [
        "PROJECT SAVE SAVE",
        "PROJECT COPY SAVE COPIED",
        "PROJECT ARCHIVE SAVE cmqttd:save",
        "PROJECT RESTORE RESTORED cmqttd:save",
        "PROJECT NEW DEST",
        "PROJECT USE SAVE",
    ] {
        command(&service, &mut client, text).await;
    }
    assert_eq!(
        run(&service, &mut client, "DBCOPY //SAVE/CustomA DEST")
            .await
            .status,
        301
    );
    let copy = record(&service, "COPIED", "CustomA").await;
    assert_eq!(copy, record(&service, "RESTORED", "CustomA").await);
    assert_ne!(
        copy.root.field("OID"),
        record(&service, "DEST", "CustomA").await.root.field("OID")
    );
    command(&service, &mut client, &format!("DBDELETE !{oid}")).await;
    assert!(!run(&service, &mut client, "DBGETXML //SAVE")
        .await
        .lines
        .join("")
        .contains("<Address>CustomA</Address>"));
    assert_eq!(
        run(&service, &mut client, "DBGETXML //SAVE/CustomA")
            .await
            .status,
        401
    );
    assert_eq!(
        run(&service, &mut client, &format!("DBGETXML !{oid}"))
            .await
            .status,
        401
    );
    command(&service, &mut client, "NET SAVE DB").await;
    assert_ne!(
        record(&service, "SAVE", "CustomA").await.root.field("OID"),
        Some(oid)
    );
    no_io(&mut remote).await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn net_save_db_native_literal_number_vectors_and_generic_get_preservation() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    let mut baseline = Vec::new();
    for target in ["cgate", "projects", "cbus"] {
        for property in ["Name", "Type"] {
            baseline.push(run(&service, &mut client, &format!("GET {target} {property}")).await);
        }
    }
    for text in [
        "PROJECT NEW NSAVE",
        "PROJECT USE NSAVE",
        "NET CREATE 42 Cni 127.0.0.1:1",
        "NET CREATE cgate Cni 127.0.0.1:1",
        "NET CREATE projects Cni 127.0.0.1:1",
        "NET CREATE cbus Cni 127.0.0.1:1",
        "NET SAVE DB",
    ] {
        command(&service, &mut client, text).await;
    }
    for (command_text, reply) in [
        (
            "DBGET //NSAVE/42/NetworkNumber",
            "342 42/NetworkNumber=0xff",
        ),
        (
            "GET //NSAVE/42 NetworkNumber",
            "402 Operation not supported by: //NSAVE/42 (Parameter networknumber not found)",
        ),
    ] {
        assert_eq!(
            run(&service, &mut client, command_text).await.final_text,
            reply
        );
    }
    for value in ["255", "0xff"] {
        command(
            &service,
            &mut client,
            &format!("DBSET //NSAVE/42/NetworkNumber {value}"),
        )
        .await;
        assert_eq!(
            run(&service, &mut client, "DBGET //NSAVE/42/NetworkNumber")
                .await
                .final_text,
            format!("342 42/NetworkNumber={value}")
        );
    }
    // Project selection itself affects generic metadata, so bind both samples
    // to the same selected project before testing collisions.
    client.current = Some("HARNESS".to_string());
    let mut index = 0;
    for target in ["cgate", "projects", "cbus"] {
        for property in ["Name", "Type"] {
            assert_eq!(
                run(&service, &mut client, &format!("GET {target} {property}")).await,
                baseline[index]
            );
            index += 1;
        }
    }
    no_io(&mut remote).await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn net_save_db_commit_failure_rolls_back_all_tag_and_oid_state() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    for text in [
        "PROJECT NEW SAVE",
        "PROJECT USE SAVE",
        "NET CREATE 42 Cni 127.0.0.1:1",
    ] {
        command(&service, &mut client, text).await;
    }
    let before = Database::from_server(&*service.model.lock().await);
    std::fs::remove_file(&path).unwrap();
    std::fs::create_dir(&path).unwrap();
    assert_eq!(run(&service, &mut client, "NET SAVE DB").await.status, 500);
    assert!(Database::from_server(&*service.model.lock().await) == before);
    no_io(&mut remote).await;
    std::fs::remove_dir(path).unwrap();
}

#[tokio::test]
async fn net_save_db_replays_fifteen_source_bound_literal_vectors() {
    let raw = include_bytes!(
        "../../../../testdata/fixtures/native_cgate_net_save_db_materialization.json"
    );
    let digest = hex::encode(crate::auth::sha256(raw));
    assert_eq!(
        digest,
        "933f54f4532db59f9f6b8cec610d8e4376aceda9429018c515062f83e0359a7b"
    );
    let native: serde_json::Value = serde_json::from_slice(raw).unwrap();
    let mut count = 0;
    for line in
        include_str!("../../../../testdata/vectors/cgate_net_save_db_materialization.jsonl").lines()
    {
        let vector: serde_json::Value = serde_json::from_str(line).unwrap();
        assert_eq!(vector["source_fixture_sha256"], digest);
        let source = native["commands"]
            .as_array()
            .unwrap()
            .iter()
            .find(|row| row["label"] == vector["source_label"])
            .unwrap();
        assert_eq!(source["command"], vector["command"]);
        let expected: Vec<String> = serde_json::from_value(vector["reply"].clone()).unwrap();
        let captured: Vec<String> = source["response"]
            .as_array()
            .unwrap()
            .iter()
            .map(|line| {
                line.as_str()
                    .unwrap()
                    .split_once("] ")
                    .unwrap()
                    .1
                    .to_string()
            })
            .collect();
        assert_eq!(
            expected, captured,
            "derived vector must retain literal native reply"
        );
        let path = state_path();
        let (pci_client, mut remote) = pci();
        let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
        let mut client = ClientState::default();
        for setup in vector["setup"].as_array().unwrap() {
            command(&service, &mut client, setup.as_str().unwrap()).await;
        }
        let reply = run(&service, &mut client, vector["command"].as_str().unwrap()).await;
        let actual: Vec<String> = format_response(&reply)
            .lines()
            .map(|line| line.split_once("] ").unwrap().1.to_string())
            .collect();
        assert_eq!(actual, expected, "{}", vector["id"]);
        no_io(&mut remote).await;
        std::fs::remove_file(path).unwrap();
        count += 1;
    }
    assert_eq!(count, 15);
}

#[tokio::test]
async fn net_save_db_later_numeric_unit_pp_application_and_level_edits_remain_authoritative() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    for text in [
        "DBSETSAFE //HARNESS/254/p/5/UnitName Fixture eDLT",
        "NET CLOSE 254",
        "NET SAVE DB",
        "DBSETSAFE //HARNESS/254/p/5/Later first",
        "DBADDSAFE //HARNESS/254 Unit 6 Added",
        "DBSETSAFE //HARNESS/254/p/6/UnitType KEYE1",
        "DBSETSAFE //HARNESS/254/p/6/FirmwareVersion 1.2.67",
        "PP LOCK L //HARNESS/254",
        "PP START S L",
        "PP LOAD S /db//HARNESS/254/p/5",
        "PP SET S Later second",
        "PP SAVE_TO_SOURCE S",
        "PP END S",
        "PP UNLOCK L",
    ] {
        command(&service, &mut client, text).await;
    }
    for text in [
        "DBADDSAFE //HARNESS/254 Application 57 LightingTwo",
        "DBADDSAFE //HARNESS/254/57 Group 8 Lamp",
    ] {
        command(&service, &mut client, text).await;
    }
    let level = run(
        &service,
        &mut client,
        "DBADDSAFE //HARNESS/254/57/8 Level 7 Evening",
    )
    .await;
    assert_eq!(level.status, 301, "{level:?}");
    let oid = level.final_text.strip_prefix("301 OID=").unwrap();
    command(&service, &mut client, &format!("DBSETSAFE !{oid}/Value 37")).await;
    let project = run(&service, &mut client, "DBGETXML //HARNESS")
        .await
        .lines
        .join("");
    assert!(
        project.contains("Name=\"Later\" Value=\"second\""),
        "{project}"
    );
    assert!(project.contains("<UnitName>Added</UnitName>"));
    assert!(project.contains("<TagName>LightingTwo</TagName>"));
    assert!(project.contains("Value=\"37\""));
    assert!(run(&service, &mut client, "DBTAGLIST")
        .await
        .lines
        .iter()
        .any(|line| line.contains("254/57/8/7/TagName=Evening")));
    let unit_oid = service.model.lock().await.projects["HARNESS"].networks[&254].units[&6]
        .oid
        .clone();
    assert_eq!(
        run(&service, &mut client, &format!("DBGETXML !{unit_oid}"))
            .await
            .status,
        200
    );
    command(&service, &mut client, "NET SAVE DB").await;
    assert_eq!(
        run(&service, &mut client, "DBGETXML //HARNESS")
            .await
            .lines
            .join(""),
        project,
        "repeat save must refresh current children rather than resurrect old snapshot"
    );
    for text in [
        "PROJECT SAVE HARNESS",
        "PROJECT ARCHIVE HARNESS latest.zip",
        "PROJECT RESTORE RESTORED latest.zip",
    ] {
        command(&service, &mut client, text).await;
    }
    let archive = run(&service, &mut client, "DBGETXML //RESTORED")
        .await
        .lines
        .join("");
    assert!(archive.contains("Name=\"Later\" Value=\"second\""));
    assert!(archive.contains("Value=\"37\""));
    command(&service, &mut client, "PROJECT USE HARNESS").await;
    command(&service, &mut client, "DBDELETE //HARNESS/254/p/6").await;
    assert_eq!(
        run(&service, &mut client, &format!("DBGETXML !{unit_oid}"))
            .await
            .status,
        401
    );
    assert!(!service
        .model
        .lock()
        .await
        .active_db_oids("HARNESS")
        .contains(&unit_oid));
    no_io(&mut remote).await;
    drop(service);
    let (pci_client, mut remote) = pci();
    let restarted = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let fresh = run(&restarted, &mut client, "DBGETXML //HARNESS")
        .await
        .lines
        .join("");
    assert!(fresh.contains("Name=\"Later\" Value=\"second\""));
    assert!(fresh.contains("Value=\"37\""));
    assert!(!fresh.contains("<UnitName>Added</UnitName>"));
    no_io(&mut remote).await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn net_save_db_retains_opaque_metadata_and_refuses_corrupt_current_projection_without_loss() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    for text in [
        "DBSETSAFE //HARNESS/254/p/5/UnitName Fixture eDLT",
        "NET CLOSE 254",
        "NET SAVE DB",
    ] {
        command(&service, &mut client, text).await;
    }
    let network_oid = service.model.lock().await.projects["HARNESS"].networks[&254]
        .oid
        .clone();
    service.model.lock().await.db_xml_extras.entry(Server::unit_document_key("HARNESS",&network_oid)).or_default().children.push("<v:Metadata xmlns:v=\"urn:owned-fixture\" flag=\"true\"><v:Value>before &amp; after</v:Value></v:Metadata>".to_string());
    let xml = run(&service, &mut client, "DBGETXML //HARNESS")
        .await
        .lines
        .join("");
    assert!(xml.contains("urn:owned-fixture") && xml.contains("before &amp; after"));
    command(&service, &mut client, "NET SAVE DB").await;
    assert_eq!(
        run(&service, &mut client, "DBGETXML //HARNESS")
            .await
            .lines
            .join(""),
        xml
    );
    for text in [
        "PROJECT SAVE HARNESS",
        "PROJECT ARCHIVE HARNESS opaque.zip",
        "PROJECT RESTORE OPAQUE opaque.zip",
    ] {
        command(&service, &mut client, text).await;
    }
    assert!(run(&service, &mut client, "DBGETXML //OPAQUE")
        .await
        .lines
        .join("")
        .contains("before &amp; after"));
    command(&service, &mut client, "PROJECT USE HARNESS").await;
    let unit_oid = service.model.lock().await.projects["HARNESS"].networks[&254].units[&5]
        .oid
        .clone();
    let unit_xml = run(&service, &mut client, "DBGETXML //HARNESS/254/p/5")
        .await
        .lines[0]
        .strip_prefix("347-")
        .unwrap()
        .to_string();
    let key = service
        .model
        .lock()
        .await
        .stored_unit_document_key("HARNESS", &unit_oid, 5);
    let prior = service.model.lock().await.unit_documents.insert(
        key.clone(),
        unit_xml.replace(
            "<UnitName>Fixture eDLT</UnitName>",
            "<UnitName>before<!--owned-comment-->after</UnitName>",
        ),
    );
    let segmented = Database::from_server(&*service.model.lock().await);
    assert_eq!(
        run(&service, &mut client, "DBGETXML //HARNESS")
            .await
            .status,
        408
    );
    assert_eq!(run(&service, &mut client, "NET SAVE DB").await.status, 408);
    assert_eq!(
        run(
            &service,
            &mut client,
            "PROJECT ARCHIVE HARNESS segmented.zip"
        )
        .await
        .status,
        408
    );
    assert!(Database::from_server(&*service.model.lock().await) == segmented);
    let mut model = service.model.lock().await;
    if let Some(prior) = prior {
        model.unit_documents.insert(key, prior);
    } else {
        model.unit_documents.remove(&key);
    }
    drop(model);
    service
        .model
        .lock()
        .await
        .db_xml_extras
        .entry(Server::unit_document_key("HARNESS", &network_oid))
        .or_default()
        .children
        .push("<broken".to_string());
    let before = Database::from_server(&*service.model.lock().await);
    assert_eq!(
        run(&service, &mut client, "DBGETXML //HARNESS")
            .await
            .status,
        408
    );
    assert_eq!(run(&service, &mut client, "NET SAVE DB").await.status, 408);
    assert_eq!(
        run(&service, &mut client, "PROJECT ARCHIVE HARNESS invalid.zip")
            .await
            .status,
        408
    );
    assert!(Database::from_server(&*service.model.lock().await) == before);
    assert!(!service
        .model
        .lock()
        .await
        .file_store
        .contains_key("Projects/archived/invalid.zip"));
    no_io(&mut remote).await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn net_save_db_rename_lexemes_order_and_oid_mutation_guards_preserve_complete_model() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    for text in [
        "DBSETSAFE //HARNESS/254/p/5/UnitName Fixture eDLT",
        "NET CLOSE 254",
        "PROJECT COPY HARNESS AUX",
        "PROJECT USE AUX",
        "NET LOAD DB",
        "NET SAVE DB",
        "DBRENAMENET //AUX/254 Alias",
        "NET DELETE 254",
        "NET CREATE CustomA cni 127.0.0.1:1 owned=yes",
        "NET SAVE DB",
    ] {
        command(&service, &mut client, text).await;
    }
    // Runtime254 is intentionally still present after database rename. Remove
    // it before testing DB LOAD so it cannot cause a legitimate new tag row.
    command(&service, &mut client, "NET LOAD DB").await;
    let loaded = run(&service, &mut client, "NET LIST").await;
    assert!(!loaded.lines.iter().any(|line| line.contains("name=254 ")));
    command(&service, &mut client, "DBRENAMENET //AUX/CustomA 0254").await;
    let xml = run(&service, &mut client, "DBGETXML //AUX")
        .await
        .lines
        .join("");
    assert_eq!(xml.matches("<Address>254</Address>").count(), 0);
    assert!(
        xml.find("<Address>Alias</Address>").unwrap()
            < xml.find("<Address>0254</Address>").unwrap()
    );
    let renamed = record(&service, "AUX", "0254").await;
    let before = Database::from_server(&*service.model.lock().await);
    for oid in [
        renamed.root.field("OID").unwrap(),
        renamed.interface().field("OID").unwrap(),
        renamed.interface().children[0].field("OID").unwrap(),
    ] {
        assert_eq!(
            run(
                &service,
                &mut client,
                &format!("DBSET !{oid}/OID {}", crate::fresh_oid())
            )
            .await
            .final_text,
            "408 Operation failed: OID field can not be changed"
        );
    }
    assert_eq!(
        run(&service, &mut client, "DBCOPY //AUX/0254 AUX")
            .await
            .status,
        // Original named-copy capture returns401 for a bare same-project
        // parent. Installation/Project is the admitted unsafe destination.
        401
    );
    assert!(Database::from_server(&*service.model.lock().await) == before);
    assert_eq!(
        run(&service, &mut client, "DBCOPYSAFE //AUX/0254 AUX 256 Copy")
            .await
            .status,
        301
    );
    assert_eq!(record(&service, "AUX", "256").await.database_network, None);
    no_io(&mut remote).await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn net_save_db_native_xml_import_archive_and_legacy_repository_migration_keep_logical_rows() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    for text in [
        "DBSETSAFE //HARNESS/254/p/5/UnitName Fixture eDLT",
        "NET CLOSE 254",
        "NET CREATE 42 cni 127.0.0.1:1 owned=yes",
        "NET CREATE 0254 Serial /private/tmp/owned-absent-port",
        "NET CREATE CustomA Bridge 254/p/42 duplicate=one duplicate=two",
        "NET SAVE DB",
        "DBSET //HARNESS/42/NetworkNumber 255",
        "PROJECT SAVE HARNESS",
        "PROJECT ARCHIVE HARNESS native.zip",
        "PROJECT RESTORE COPY native.zip",
    ] {
        command(&service, &mut client, text).await;
    }
    let original = run(&service, &mut client, "DBGETXML //HARNESS").await;
    assert_eq!(original.status, 200);
    let xml = original.lines[0].strip_prefix("347-").unwrap();
    assert!(xml.contains("<DBVersion>2.3</DBVersion>"));
    let imported_path = state_path();
    let (pci_client, mut imported_remote) = pci();
    let imported = Service::new(xml, None, imported_path.clone(), pci_client, None).unwrap();
    // Complete native string records retain exact XML/OIDs. The legacy
    // numeric Unit's oid attribute is normalized by the established importer;
    // its scalar identity/PP and every subtree identity must remain equal.
    let imported_xml = run(&imported, &mut client, "DBGETXML //HARNESS")
        .await
        .lines
        .join("");
    let old = roxmltree::Document::parse(xml).unwrap();
    let new = roxmltree::Document::parse(imported_xml.strip_prefix("347-").unwrap()).unwrap();
    for tag in [
        "OID",
        "Address",
        "TagName",
        "UnitName",
        "UnitType",
        "FirmwareVersion",
        "NetworkNumber",
    ] {
        let values = |doc: &roxmltree::Document<'_>| {
            doc.descendants()
                .filter(|node| node.has_tag_name(tag))
                .map(|node| node.text().unwrap_or_default().to_string())
                .collect::<Vec<_>>()
        };
        assert_eq!(values(&old), values(&new), "imported {tag} identity/scalar");
    }
    let pp = |doc: &roxmltree::Document<'_>| {
        doc.descendants()
            .filter(|node| node.has_tag_name("PP"))
            .map(|node| {
                (
                    node.attribute("Name").unwrap_or_default().to_string(),
                    node.attribute("Value").unwrap_or_default().to_string(),
                )
            })
            .collect::<Vec<_>>()
    };
    assert_eq!(pp(&old), pp(&new));

    for name in ["42", "0254", "CustomA"] {
        assert_eq!(
            record(&imported, "HARNESS", name).await,
            record(&service, "HARNESS", name).await
        );
        assert_eq!(record(&service, "COPY", name).await.database_network, None);
    }
    assert_eq!(
        record(&service, "COPY", "254").await.database_network,
        Some(254)
    );
    assert_eq!(
        service.model.lock().await.projects["COPY"].networks.len(),
        1
    );
    assert_eq!(
        imported.model.lock().await.projects["HARNESS"]
            .networks
            .len(),
        1
    );
    no_io(&mut remote).await;
    no_io(&mut imported_remote).await;
    drop(service);
    drop(imported);
    // Older JSON never had a tag_networks key. The default layer must load
    // without fabricating new rows, and rewriting it must remain readable.
    let legacy_path = state_path();
    let (pci_client, _) = pci();
    drop(Service::new(&fixture(), None, legacy_path.clone(), pci_client, None).unwrap());
    let mut legacy: serde_json::Value =
        serde_json::from_slice(&std::fs::read(&legacy_path).unwrap()).unwrap();
    for project in legacy["projects"].as_object_mut().unwrap().values_mut() {
        project.as_object_mut().unwrap().remove("tag_networks");
    }
    std::fs::write(&legacy_path, serde_json::to_vec(&legacy).unwrap()).unwrap();
    let (pci_client, _) = pci();
    let legacy = Service::new(&fixture(), None, legacy_path.clone(), pci_client, None).unwrap();
    assert!(legacy.model.lock().await.projects["HARNESS"]
        .tag_networks
        .is_empty());
    for path in [path, imported_path, legacy_path] {
        std::fs::remove_file(path).unwrap();
    }
}

#[tokio::test]
async fn net_save_db_independent_lexical_aliases_cannot_reach_physical_interface_or_numeric_database_children(
) {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    for text in ["NET CREATE 0254 cni 127.0.0.1:1", "NET SAVE DB"] {
        command(&service, &mut client, text).await;
    }
    let before = Database::from_server(&*service.model.lock().await);
    let oid = record(&service, "HARNESS", "0254")
        .await
        .root
        .field("OID")
        .unwrap()
        .to_string();
    for text in [
        "ON 0254/56/1",
        "ON //HARNESS/0254/56/1",
        "LIGHTING ON 0254/56/1",
        "LIGHTING ON //HARNESS/0254/56/1",
        "UNIT IDENTIFY //HARNESS/0254/p/5",
        "PP LOAD S //HARNESS/0254/p/5",
        "PP LOAD S /db//HARNESS/0254/p/5",
        &format!("NET OPEN !{oid}"),
    ] {
        assert_eq!(run(&service, &mut client, text).await.status, 404, "{text}");
    }
    for text in [
        "DBGETXML //HARNESS/0254/p/5",
        "DBSET //HARNESS/0254/p/5/UnitName Wrong",
        "DBDELETE //HARNESS/0254/p/5",
    ] {
        assert!(
            run(&service, &mut client, text).await.status >= 400,
            "{text}"
        );
    }
    assert!(Database::from_server(&*service.model.lock().await) == before);
    command(&service, &mut client, "BROADCAST_EVENT X //HARNESS/0254").await;
    assert_eq!(
        run(&service, &mut client, "GET //HARNESS/254 State")
            .await
            .status,
        300
    );
    assert_eq!(
        run(&service, &mut client, "GET //HARNESS/0254 Name")
            .await
            .final_text,
        "300 //HARNESS/0254: Name=0254"
    );
    no_io(&mut remote).await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn net_save_db_safe_application_group_creation_has_one_authoritative_tree_before_and_after_save(
) {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    for text in [
        "DBSETSAFE //HARNESS/254/p/5/UnitName Fixture eDLT",
        "NET CLOSE 254",
        "DBADDSAFE //HARNESS/254 Application 57 CreatedApp",
        "DBADDSAFE //HARNESS/254/57 Group 8 CreatedGroup",
    ] {
        command(&service, &mut client, text).await;
    }
    let before = run(&service, &mut client, "DBGETXML //HARNESS/254")
        .await
        .lines
        .join("");
    assert!(
        before.contains("<TagName>CreatedApp</TagName>")
            && before.contains("<TagName>CreatedGroup</TagName>")
    );
    command(&service, &mut client, "NET SAVE DB").await;
    assert!(run(&service, &mut client, "DBGETXML //HARNESS/254")
        .await
        .lines
        .join("")
        .contains("<TagName>CreatedGroup</TagName>"));
    for text in [
        "DBSETSAFE //HARNESS/254/57/8/TagName UpdatedGroup",
        "PROJECT SAVE HARNESS",
        "PROJECT CLOSE HARNESS",
        "PROJECT LOAD HARNESS",
    ] {
        command(&service, &mut client, text).await;
    }
    assert!(run(&service, &mut client, "DBGETXML //HARNESS/254")
        .await
        .lines
        .join("")
        .contains("<TagName>UpdatedGroup</TagName>"));
    no_io(&mut remote).await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn net_save_db_deleted_named_rows_do_not_resurrect_from_materialized_snapshot_but_legacy_snapshots_migrate(
) {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    for text in [
        "PROJECT NEW NDEL",
        "PROJECT USE NDEL",
        "NET CREATE CustomA Cni 127.0.0.1:1",
        "NET SAVE DB",
        "PROJECT SAVE NDEL",
    ] {
        command(&service, &mut client, text).await;
    }
    let saved = record(&service, "NDEL", "CustomA").await;
    command(
        &service,
        &mut client,
        &format!("DBDELETE !{}", saved.root.field("OID").unwrap()),
    )
    .await;
    command(&service, &mut client, "NET DELETE CustomA").await;
    command(&service, &mut client, "NET LOAD DB").await;
    assert_eq!(
        run(&service, &mut client, "NET LIST").await.final_text,
        "132 no networks found"
    );
    assert!(!run(&service, &mut client, "DBGETXML //NDEL")
        .await
        .lines
        .join("")
        .contains("<Network>"));
    assert_eq!(
        run(&service, &mut client, "DBGETXML //NDEL/CustomA")
            .await
            .status,
        401
    );
    // A pre-feature catalogue has no materialized-source marker and keeps
    // its explicitly supported custom-name migration fallback.
    command(&service, &mut client, "PROJECT NEW LEGACY").await;
    command(&service, &mut client, "PROJECT USE LEGACY").await;
    let prefix = format!("@cmqttd/net-catalog/v1/{}", hex::encode("LEGACY"));
    service.model.lock().await.config_values.insert(format!("{prefix}/snapshot/db"), serde_json::json!([{"name":"CABIN","interface_type":"Serial","interface_address":"/private/tmp/owned-legacy-port","options":["retained=yes"],"bound_network":null}]).to_string());
    command(&service, &mut client, "NET LOAD DB").await;
    assert_eq!(
        run(&service, &mut client, "NET LIST").await.final_text,
        "network=CABIN State=new InterfaceState=closed"
    );
    assert!(service.model.lock().await.projects["LEGACY"]
        .tag_networks
        .is_empty());
    no_io(&mut remote).await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn net_save_db_project_name_reuse_retires_runtime_db_ownership_atomically_but_keeps_explicit_file_recovery(
) {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    for text in [
        "PROJECT NEW REUSE",
        "PROJECT USE REUSE",
        "NET CREATE Old Cni 127.0.0.1:1 owned=yes",
        "NET SAVE DB",
        "NET SAVE FILE",
        "PROJECT SAVE REUSE",
    ] {
        command(&service, &mut client, text).await;
    }
    let prefix = format!("@cmqttd/net-catalog/v1/{}", hex::encode("REUSE"));
    let saved_file =
        service.model.lock().await.config_values[&format!("{prefix}/snapshot/file")].clone();
    let other_catalogs = service
        .model
        .lock()
        .await
        .config_values
        .iter()
        .filter(|(key, _)| !key.starts_with(&prefix))
        .map(|(key, value)| (key.clone(), value.clone()))
        .collect::<std::collections::HashMap<_, _>>();
    let before_delete = Database::from_server(&*service.model.lock().await);
    std::fs::remove_file(&path).unwrap();
    std::fs::create_dir(&path).unwrap();
    assert_eq!(
        run(&service, &mut client, "PROJECT DELETE REUSE")
            .await
            .final_text,
        "500 Database commit failed; change rolled back"
    );
    assert!(Database::from_server(&*service.model.lock().await) == before_delete);
    assert_eq!(client.current.as_deref(), Some("REUSE"));
    std::fs::remove_dir(&path).unwrap();
    command(&service, &mut client, "PROJECT DELETE REUSE").await;
    {
        let model = service.model.lock().await;
        assert!(!model.projects.contains_key("REUSE"));
        for suffix in ["active", "snapshot/db", "db-source-materialized"] {
            assert!(!model
                .config_values
                .contains_key(&format!("{prefix}/{suffix}")));
        }
        assert_eq!(
            model.config_values[&format!("{prefix}/snapshot/file")],
            saved_file
        );
    }
    // A NEW after a pre-feature DELETE also clears stale implicit catalogue
    // remnants, including a falsely bound runtime record, before any use.
    let stale = serde_json::json!([{"name":"Ghost","interface_type":"Cni","interface_address":"127.0.0.1:2","options":[],"bound_network":254}]).to_string();
    for suffix in ["active", "snapshot/db"] {
        service
            .model
            .lock()
            .await
            .config_values
            .insert(format!("{prefix}/{suffix}"), stale.clone());
    }
    service.model.lock().await.config_values.insert(
        format!("{prefix}/db-source-materialized"),
        "true".to_string(),
    );
    command(&service, &mut client, "PROJECT NEW REUSE").await;
    command(&service, &mut client, "PROJECT USE REUSE").await;
    assert_eq!(
        run(&service, &mut client, "NET LIST").await.final_text,
        "132 no networks found"
    );
    command(&service, &mut client, "NET LOAD DB").await;
    assert_eq!(
        run(&service, &mut client, "NET LIST").await.final_text,
        "132 no networks found"
    );
    assert!(!run(&service, &mut client, "DBGETXML //REUSE")
        .await
        .lines
        .join("")
        .contains("<Network>"));
    command(&service, &mut client, "NET LOAD FILE").await;
    assert_eq!(
        run(&service, &mut client, "NET LIST").await.final_text,
        "network=Old State=new InterfaceState=closed"
    );
    assert!(!run(&service, &mut client, "DBGETXML //REUSE")
        .await
        .lines
        .join("")
        .contains("<Network>"));
    let model = service.model.lock().await;
    assert_eq!(
        model
            .config_values
            .iter()
            .filter(|(key, _)| !key.starts_with(&prefix))
            .map(|(key, value)| (key.clone(), value.clone()))
            .collect::<std::collections::HashMap<_, _>>(),
        other_catalogs
    );
    let restored: serde_json::Value =
        serde_json::from_str(&model.config_values[&format!("{prefix}/active")]).unwrap();
    assert!(restored[0]["bound_network"].is_null());
    drop(model);
    no_io(&mut remote).await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn net_save_db_associated_network_oid_delete_retires_complete_subtree_sidecars_and_rolls_back_failures(
) {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    let foreign_oids = service.model.lock().await.active_db_oids("HARNESS");
    let foreign_xml = run(&service, &mut client, "DBGETXML //HARNESS").await.lines;
    for text in [
        "PROJECT NEW AUX",
        "PROJECT USE AUX",
        "DBCREATENET 42 Root Cni 127.0.0.1:1",
        "DBADDSAFE //AUX/42 Application 57 App",
        "DBADDSAFE //AUX/42/57 Group 8 Group",
        "DBADDSAFE //AUX/42 Unit 6 Unit",
        "DBSETSAFE //AUX/42/p/6/UnitType KEYE1",
        "DBSETSAFE //AUX/42/p/6/UnitName Unit",
        "DBSETSAFE //AUX/42/p/6/FirmwareVersion 1.2.67",
        "DBSETSAFE //AUX/42/p/6/Preserved parameter",
    ] {
        command(&service, &mut client, text).await;
    }
    let level = run(
        &service,
        &mut client,
        "DBADDSAFE //AUX/42/57/8 Level 7 Evening",
    )
    .await;
    assert_eq!(level.status, 301);
    command(
        &service,
        &mut client,
        &format!(
            "DBSETSAFE !{}/Value 37",
            level.final_text.strip_prefix("301 OID=").unwrap()
        ),
    )
    .await;
    command(&service, &mut client, "NET LOAD DB").await;
    command(&service, &mut client, "NET SAVE DB").await;
    let project_oid = run(
        &service,
        &mut client,
        "DBGET //AUX/Installation/Project/OID",
    )
    .await
    .final_text
    .split_once('=')
    .unwrap()
    .1
    .to_string();
    let root = record(&service, "AUX", "42").await;
    let mut oids = root.root.oids();
    assert!(oids.len() >= 6);
    let pending = run(&service, &mut client, "DBADD //AUX/42 Application").await;
    assert_eq!(pending.status, 301);
    let pending_oid = pending.final_text.strip_prefix("301 OID=").unwrap();
    let child = run(
        &service,
        &mut client,
        &format!("DBADD !{pending_oid} Group"),
    )
    .await;
    assert_eq!(child.status, 301);
    oids.push(pending_oid.to_string());
    oids.push(
        child
            .final_text
            .strip_prefix("301 OID=")
            .unwrap()
            .to_string(),
    );
    let delete = format!("DBDELETE !{}", root.root.field("OID").unwrap());
    let before = Database::from_server(&*service.model.lock().await);
    std::fs::remove_file(&path).unwrap();
    std::fs::create_dir(&path).unwrap();
    assert_eq!(
        run(&service, &mut client, &delete).await.final_text,
        "500 Database commit failed; change rolled back"
    );
    assert!(Database::from_server(&*service.model.lock().await) == before);
    std::fs::remove_dir(&path).unwrap();
    command(&service, &mut client, &delete).await;
    for oid in &oids {
        assert_eq!(
            run(&service, &mut client, &format!("DBGETXML !{oid}"))
                .await
                .status,
            401,
            "XML child must be retired: {oid}"
        );
        assert_eq!(
            run(&service, &mut client, &format!("DBGET !{oid}/TagName"))
                .await
                .status,
            401,
            "scalar child must be retired: {oid}"
        );
    }
    assert_eq!(
        run(&service, &mut client, "DBGETXML //AUX/42").await.status,
        401
    );
    let model = service.model.lock().await;
    assert!(model.projects["AUX"].networks.is_empty());
    assert!(model.projects["AUX"].tag_networks.is_empty());
    assert!(!model
        .db_pending
        .values()
        .any(|object| object.project == "AUX"));
    assert!(!model
        .db_levels
        .values()
        .any(|level| level.parent.starts_with("//AUX/42/")));
    assert!(!model
        .db_fields
        .keys()
        .any(|field| field.starts_with("//AUX/42/")
            || oids.iter().any(|oid| field.starts_with(&format!("!{oid}")))));
    for oid in &oids {
        // The deterministic test allocator can share an issued identity
        // with the preloaded fixture. A surviving foreign owner must keep
        // its global index, while no deleted selected-project view survives.
        assert_eq!(
            model.known_oids.contains(oid),
            foreign_oids.contains(oid),
            "global OID ownership {oid}"
        );
        assert!(!model.active_db_oids("AUX").contains(oid));
    }
    let unit_prefix = "AUX\u{1f}";
    assert!(!model
        .unit_documents
        .keys()
        .any(|key| key.starts_with(unit_prefix)));
    assert!(!model
        .unit_pp_fields
        .keys()
        .any(|key| key.starts_with(unit_prefix)));
    assert!(!model
        .unit_pp_values
        .keys()
        .any(|key| key.starts_with(unit_prefix)));
    // The Project survives deletion of its Network. Its single envelope
    // owner is not a deleted Unit sidecar; every other AUX extra must retire.
    let envelope_key = Server::unit_document_key("AUX", crate::native_archive::ENVELOPE_KEY);
    assert!(model
        .db_xml_extras
        .keys()
        .filter(|key| key.starts_with(unit_prefix))
        .all(|key| key == &envelope_key));
    assert_eq!(
        model.db_xml_extras[&envelope_key].attributes["project-oid"],
        project_oid
    );
    assert_eq!(model.active_db_oids("HARNESS"), foreign_oids);
    drop(model);
    assert_eq!(
        run(&service, &mut client, "DBGETXML //HARNESS").await.lines,
        foreign_xml
    );
    command(&service, &mut client, "PROJECT SAVE AUX").await;
    command(&service, &mut client, "PROJECT CLOSE AUX").await;
    command(&service, &mut client, "PROJECT LOAD AUX").await;
    assert!(!run(&service, &mut client, "DBGETXML //AUX")
        .await
        .lines
        .join("")
        .contains("<Network>"));
    no_io(&mut remote).await;
    drop(service);
    let (pci_client, mut remote) = pci();
    let restarted = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    assert_eq!(
        run(
            &restarted,
            &mut client,
            "DBGET //AUX/Installation/Project/OID"
        )
        .await
        .final_text
        .split_once('=')
        .unwrap()
        .1,
        project_oid
    );
    for oid in &oids {
        assert_eq!(
            run(&restarted, &mut client, &format!("DBGETXML !{oid}"))
                .await
                .status,
            401
        );
    }
    no_io(&mut remote).await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn net_save_db_named_safe_copy_refuses_invalid_address_atomically_and_valid_copy_remains_readable(
) {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    for text in [
        "PROJECT NEW AUX",
        "PROJECT USE AUX",
        "NET CREATE Source Cni 127.0.0.1:1 owned=yes",
        "NET SAVE DB",
    ] {
        command(&service, &mut client, text).await;
    }
    let before = Database::from_server(&*service.model.lock().await);
    let bytes = std::fs::read(&path).unwrap();
    for address in ["bad/name", "bad\\name", "bad#name"] {
        let failed = run(
            &service,
            &mut client,
            &format!("DBCOPYSAFE //AUX/Source AUX {address} Copy"),
        )
        .await;
        assert_eq!(failed.status, 408, "{failed:?}");
        assert!(failed.final_text.contains("Invalid Network Address"));
        assert!(Database::from_server(&*service.model.lock().await) == before);
        assert_eq!(std::fs::read(&path).unwrap(), bytes);
    }
    let copied = run(
        &service,
        &mut client,
        "DBCOPYSAFE //AUX/Source AUX 0254 Copy",
    )
    .await;
    assert_eq!(copied.status, 301);
    let oid = copied.final_text.strip_prefix("301 OID=").unwrap();
    assert_eq!(
        run(&service, &mut client, "DBGETXML //AUX/0254")
            .await
            .status,
        200
    );
    assert_eq!(
        run(&service, &mut client, &format!("DBGETXML !{oid}"))
            .await
            .status,
        200
    );
    command(&service, &mut client, "PROJECT SAVE AUX").await;
    command(&service, &mut client, "PROJECT ARCHIVE AUX copy-valid.zip").await;
    command(&service, &mut client, "PROJECT RESTORE COPY copy-valid.zip").await;
    assert_eq!(
        run(&service, &mut client, "PROJECT USE COPY").await.status,
        200
    );
    assert_eq!(
        run(&service, &mut client, "DBGETXML //COPY/0254")
            .await
            .status,
        200
    );
    assert_eq!(
        record(&service, "COPY", "0254").await.database_network,
        None
    );
    no_io(&mut remote).await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn net_save_db_unselected_known_tag_mutations_refuse_without_opaque_success() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut selected = ClientState::default();
    for text in [
        "PROJECT NEW AUX",
        "PROJECT USE AUX",
        "NET CREATE CustomA Cni 127.0.0.1:1 owned=yes",
        "NET SAVE DB",
    ] {
        command(&service, &mut selected, text).await;
    }
    let tag = record(&service, "AUX", "CustomA").await;
    let selectors = [
        "//AUX/CustomA/TagName".to_string(),
        "//AUX/CustomA/Interface/InterfaceAddress".to_string(),
        format!("!{}/TagName", tag.root.field("OID").unwrap()),
        format!(
            "!{}/InterfaceAddress",
            tag.interface().field("OID").unwrap()
        ),
        format!(
            "!{}/Value",
            tag.interface().children[0].field("OID").unwrap()
        ),
    ];
    let before = Database::from_server(&*service.model.lock().await);
    let bytes = std::fs::read(&path).unwrap();
    for current in [None, Some("HARNESS".to_string())] {
        let mut unrelated = ClientState {
            current,
            ..ClientState::default()
        };
        for selector in &selectors {
            for verb in ["DBSET", "DBSETSAFE"] {
                let response = run(
                    &service,
                    &mut unrelated,
                    &format!("{verb} {selector} UnselectedEdit"),
                )
                .await;
                assert_eq!(response.final_text, "401 Object not found", "{response:?}");
                assert!(Database::from_server(&*service.model.lock().await) == before);
                assert_eq!(std::fs::read(&path).unwrap(), bytes);
            }
        }
    }
    assert_eq!(record(&service, "AUX", "CustomA").await, tag);

    // Unknown qualified scalar paths keep the legacy opaque store, and
    // ordinary numeric Unit/OID ownership keeps its established mutation.
    let mut numeric = ClientState::default();
    command(&service, &mut numeric, "PROJECT USE HARNESS").await;
    command(
        &service,
        &mut numeric,
        "DBSETSAFE //AUX/CustomA-other/TagName OpaqueControl",
    )
    .await;
    assert_eq!(
        service.model.lock().await.db_fields["//AUX/CustomA-other/TagName"],
        "OpaqueControl"
    );
    command(
        &service,
        &mut numeric,
        "DBSETSAFE //HARNESS/254/p/5/UnitName OrdinaryControl",
    )
    .await;
    assert!(run(&service, &mut numeric, "DBGETXML //HARNESS/254/p/5")
        .await
        .lines
        .join("")
        .contains("OrdinaryControl"));

    command(&service, &mut selected, "PROJECT USE AUX").await;
    command(
        &service,
        &mut selected,
        "DBSETSAFE //AUX/CustomA/TagName SelectedEdit",
    )
    .await;
    command(
        &service,
        &mut selected,
        &format!("DBSET !{}/TagName OidEdit", tag.root.field("OID").unwrap()),
    )
    .await;
    assert_eq!(
        record(&service, "AUX", "CustomA")
            .await
            .root
            .field("TagName"),
        Some("OidEdit")
    );
    no_io(&mut remote).await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn net_save_db_preserves_modeled_duplicate_oid_selection_and_delete_invalidation() {
    const SHARED: &str = "11111111-1111-4111-8111-111111111111";
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    for text in [
        "PROJECT NEW XDUP",
        "PROJECT USE XDUP",
        "DBCREATENET 253 Local Cni 127.0.0.1:1",
    ] {
        command(&service, &mut client, text).await;
    }
    let initial = run(&service, &mut client, "DBGETXML //XDUP/253").await;
    let parsed =
        roxmltree::Document::parse(initial.lines[0].strip_prefix("347-").unwrap()).unwrap();
    let oid = |node: roxmltree::Node<'_, '_>| {
        node.children()
            .find(|child| child.has_tag_name("OID"))
            .unwrap()
            .text()
            .unwrap()
            .to_string()
    };
    let network_oid = oid(parsed.root_element());
    let interface_oid = oid(parsed
        .descendants()
        .find(|node| node.has_tag_name("Interface"))
        .unwrap());
    let document = format!(
        "<Network><OID>{network_oid}</OID><TagName>Local</TagName><Address>253</Address><NetworkNumber>253</NetworkNumber><Interface><OID>{interface_oid}</OID><InterfaceType>Cni</InterfaceType><InterfaceAddress>127.0.0.1:1</InterfaceAddress></Interface><Application><OID>{SHARED}</OID><TagName>Lighting</TagName><Address>56</Address></Application><Unit><OID>{SHARED}</OID><TagName>First</TagName><Address>20</Address><UnitType>KEYE1</UnitType><UnitName>First room</UnitName><FirmwareVersion>1.2.67</FirmwareVersion><PP Name=\"UnitAddress\" Value=\"20\"/></Unit><Unit><OID>{SHARED}</OID><TagName>Second</TagName><Address>21</Address><UnitType>KEYE1</UnitType><UnitName>Second room</UnitName><FirmwareVersion>1.2.68</FirmwareVersion><PP Name=\"UnitAddress\" Value=\"21\"/></Unit></Network>"
    );
    assert_eq!(
        service
            .handle_document(&mut client, "[save-db] DBSETXML //XDUP/253", &document)
            .await
            .status,
        301
    );
    let before = run(&service, &mut client, &format!("DBGETXML !{SHARED}")).await;
    assert!(before.lines[0].contains("<Address>21</Address>"));
    assert_eq!(
        run(&service, &mut client, &format!("DBGET !{SHARED}/TagName"))
            .await
            .final_text,
        format!("342 !{SHARED}/TagName=Second")
    );
    command(&service, &mut client, "NET LOAD DB").await;
    command(&service, &mut client, "NET SAVE DB").await;
    assert_eq!(
        run(&service, &mut client, &format!("DBGETXML !{SHARED}"))
            .await
            .lines,
        before.lines
    );
    assert_eq!(
        run(&service, &mut client, &format!("DBGET !{SHARED}/TagName"))
            .await
            .final_text,
        format!("342 !{SHARED}/TagName=Second")
    );
    command(&service, &mut client, &format!("DBDELETE !{SHARED}")).await;
    for text in [
        format!("DBGETXML !{SHARED}"),
        format!("DBGET !{SHARED}/TagName"),
        format!("DBGET !{SHARED}/OID"),
    ] {
        assert_eq!(
            run(&service, &mut client, &text).await.status,
            401,
            "{text}"
        );
    }
    assert_eq!(
        run(&service, &mut client, "DBGETXML //XDUP/253/p/20")
            .await
            .status,
        200
    );
    assert_eq!(
        run(&service, &mut client, "DBGETXML //XDUP/253/56")
            .await
            .status,
        200
    );
    no_io(&mut remote).await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn net_save_db_unrelated_application_scalar_preserves_admitted_legacy_pp_decorations() {
    let xml = r#"<Installation><Project><TagName>SYNTH</TagName>
      <Network xmlns:v="urn:example"><TagName>Local</TagName><Address>254</Address>
        <Interface><InterfaceType>Cni</InterfaceType><InterfaceAddress>127.0.0.1:1</InterfaceAddress></Interface>
        <Application><TagName>Original</TagName><Address>57</Address></Application>
        <Unit v:flag="kept"><TagName>Sample eDLT</TagName><Address>5</Address>
          <UnitType>KEYGL5</UnitType><UnitName>Room</UnitName><FirmwareVersion>5.5.00</FirmwareVersion>
          <PP Name="EEPROM Checksum" Value="0x0" v:mark="yes"><v:Extra>nested</v:Extra></PP>
          <v:Opaque>preserved</v:Opaque>
        </Unit>
      </Network>
    </Project></Installation>"#;
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(xml, None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    command(
        &service,
        &mut client,
        "DBSETSAFE //SYNTH/254/57/TagName Before",
    )
    .await;
    command(&service, &mut client, "NET CLOSE 254").await;
    command(&service, &mut client, "NET SAVE DB").await;
    let before = run(&service, &mut client, "DBGETXML //SYNTH/254/p/5")
        .await
        .lines;
    let parsed = roxmltree::Document::parse(before[0].strip_prefix("347-").unwrap()).unwrap();
    let unit = parsed.root_element();
    assert_eq!(unit.attribute(("urn:example", "flag")), Some("kept"));
    let pp = unit
        .children()
        .find(|node| node.has_tag_name("PP"))
        .unwrap();
    assert_eq!(pp.attribute("Name"), Some("EEPROM Checksum"));
    assert_eq!(pp.attribute("Value"), Some("0x0"));
    assert_eq!(pp.attribute(("urn:example", "mark")), Some("yes"));
    assert_eq!(
        pp.children()
            .find(|node| node.has_tag_name(("urn:example", "Extra")))
            .and_then(|node| node.text()),
        Some("nested")
    );
    assert_eq!(
        unit.children()
            .find(|node| node.has_tag_name(("urn:example", "Opaque")))
            .and_then(|node| node.text()),
        Some("preserved")
    );
    command(
        &service,
        &mut client,
        "DBSETSAFE //SYNTH/254/57/TagName After",
    )
    .await;
    assert_eq!(
        run(&service, &mut client, "DBGET //SYNTH/254/57/TagName")
            .await
            .final_text,
        "342 //SYNTH/254/57/TagName=After"
    );
    assert_eq!(
        run(&service, &mut client, "DBGETXML //SYNTH/254/p/5")
            .await
            .lines,
        before
    );
    // Retention of an already admitted project shape does not admit decorated
    // PP elements in a new complete DBSETXML replacement.
    let document = run(&service, &mut client, "DBGETXML //SYNTH/254")
        .await
        .lines[0]
        .strip_prefix("347-")
        .unwrap()
        .to_string();
    assert_eq!(
        service
            .handle_document(&mut client, "[save-db] DBSETXML //SYNTH/254", &document)
            .await
            .status,
        408
    );
    assert_eq!(
        run(&service, &mut client, "DBGETXML //SYNTH/254/p/5")
            .await
            .lines,
        before
    );
    no_io(&mut remote).await;
    std::fs::remove_file(path).unwrap();
}
