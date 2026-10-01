//! Closed database journeys. Original observations are separately retained;
//! these tests establish local state, persistence and absence of PCI traffic.
use super::*;

async fn run(service: &Arc<Service>, client: &mut ClientState, command: &str) -> Response {
    service
        .handle(client, &format!("[named-db] {command}"))
        .await
}

async fn ok_command(service: &Arc<Service>, client: &mut ClientState, command: &str) {
    let response = run(service, client, command).await;
    assert_eq!(response.status, 200, "{command}: {response:?}");
}

async fn created(service: &Arc<Service>, client: &mut ClientState, command: &str) -> String {
    let response = run(service, client, command).await;
    assert_eq!(response.status, 301, "{command}: {response:?}");
    response
        .final_text
        .strip_prefix("301 OID=")
        .unwrap()
        .to_string()
}

async fn scalar(service: &Arc<Service>, client: &mut ClientState, path: &str) -> String {
    let response = run(service, client, &format!("DBGET {path}")).await;
    assert_eq!(response.status, 342, "{path}: {response:?}");
    response.final_text.split_once('=').unwrap().1.to_string()
}

async fn xml(service: &Arc<Service>, client: &mut ClientState, path: &str) -> String {
    let response = run(service, client, &format!("DBGETXML {path}")).await;
    assert_eq!(response.status, 200, "{path}: {response:?}");
    response
        .lines
        .iter()
        .filter_map(|line| line.strip_prefix("347-"))
        .collect()
}

fn oid_set(document: &str) -> std::collections::BTreeSet<String> {
    roxmltree::Document::parse(document)
        .unwrap()
        .descendants()
        .filter(|node| node.has_tag_name("OID"))
        .map(|node| node.text().unwrap().to_string())
        .collect()
}

async fn setup(service: &Arc<Service>, client: &mut ClientState) {
    for command in [
        "PROJECT NEW NAMED",
        "PROJECT USE NAMED",
        "NET CREATE Neighbor Cni 127.0.0.1:1",
        "NET CREATE CustomA Cni 127.0.0.1:1 owned=yes second=two",
        "NET SAVE DB",
        "PROJECT SAVE NAMED",
    ] {
        ok_command(service, client, command).await;
    }
}

async fn no_io(remote: &mut tokio::io::DuplexStream) {
    assert!(
        tokio::time::timeout(Duration::from_millis(20), remote.read_u8())
            .await
            .is_err()
    );
}

struct Graph {
    app: String,
    group: String,
    level: String,
    variable: String,
    variable_level: String,
}

async fn graph(service: &Arc<Service>, client: &mut ClientState) -> Graph {
    let app = created(
        service,
        client,
        "DBADDSAFE //NAMED/CustomA Application 56 Lighting",
    )
    .await;
    let group = created(service, client, &format!("DBADDSAFE !{app} Group 1 Main")).await;
    let level = created(
        service,
        client,
        &format!("DBADDSAFE !{group} Level 7 Evening"),
    )
    .await;
    assert_eq!(
        run(service, client, &format!("DBGET !{level}/Value"))
            .await
            .status,
        401
    );
    assert_eq!(
        scalar(service, client, &format!("!{level}/OID")).await,
        level
    );
    ok_command(service, client, &format!("DBSETSAFE !{level}/Value 77")).await;
    let variable = created(
        service,
        client,
        &format!("DBADDSAFE !{app} NetVar 4 Variable"),
    )
    .await;
    assert_eq!(
        run(service, client, &format!("DBGET !{variable}/Value"))
            .await
            .status,
        401
    );
    let variable_level = created(
        service,
        client,
        &format!("DBADDSAFE !{variable} Level 42 High"),
    )
    .await;
    ok_command(
        service,
        client,
        &format!("DBSETSAFE !{variable_level}/Value 23"),
    )
    .await;
    Graph {
        app,
        group,
        level,
        variable,
        variable_level,
    }
}

#[tokio::test]
async fn named_safe_graph_exact_scalar_wire_contract_matches_original_vector() {
    let vector: serde_json::Value = serde_json::from_str(include_str!(
        "../../../../testdata/vectors/cgate_named_safe_graph.json"
    ))
    .unwrap();
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    for command in [
        "PROJECT NEW LAB",
        "PROJECT USE LAB",
        "NET CREATE CustomA Cni 127.0.0.1:1",
        "NET SAVE DB",
    ] {
        ok_command(&service, &mut client, command).await;
    }
    let mut roles = std::collections::BTreeMap::<String, String>::new();
    for case in vector["cases"].as_array().unwrap() {
        let mut command = case["command"].as_str().unwrap().to_string();
        for (role, oid) in &roles {
            command = command.replace(role, oid);
        }
        assert!(!command.contains('%'), "unbound role: {command}");
        let response = run(&service, &mut client, &command).await;
        assert_eq!(
            u64::from(response.status),
            case["status"].as_u64().unwrap(),
            "{}: {response:?}",
            case["label"]
        );
        let expected = case["reply"]
            .as_array()
            .unwrap()
            .iter()
            .map(|line| line.as_str().unwrap().to_string())
            .collect::<Vec<_>>();
        if response.status == 301 {
            assert_eq!(expected.len(), 1);
            let role = expected[0].strip_prefix("301 OID=").unwrap().to_string();
            let oid = response
                .final_text
                .strip_prefix("301 OID=")
                .unwrap()
                .to_string();
            assert!(roles.values().all(|existing| existing != &oid));
            assert!(roles.insert(role, oid).is_none());
        }
        let actual = response
            .lines
            .iter()
            .chain(std::iter::once(&response.final_text))
            .map(|line| {
                let mut line = line.clone();
                for (role, oid) in &roles {
                    line = line.replace(oid, role);
                }
                line
            })
            .collect::<Vec<_>>();
        assert_eq!(actual, expected, "{}: {command}", case["label"]);
    }
    assert_eq!(roles.len(), 5);
    no_io(&mut remote).await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn named_safe_graph_preserves_fields_neighbors_and_identity_across_save_reload_restart() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    setup(&service, &mut client).await;
    let neighbor = xml(&service, &mut client, "//NAMED/Neighbor").await;
    let graph = graph(&service, &mut client).await;
    ok_command(
        &service,
        &mut client,
        &format!("DBSETSAFE !{}/TagName Edited Lighting", graph.app),
    )
    .await;
    ok_command(
        &service,
        &mut client,
        &format!("DBSETSAFE !{}/TagName Edited Main", graph.group),
    )
    .await;
    let before = xml(&service, &mut client, "//NAMED/CustomA").await;
    let oids = oid_set(&before);
    assert_eq!(
        run(&service, &mut client, "DBVALIDATE //NAMED/CustomA")
            .await
            .status,
        233
    );
    assert_eq!(xml(&service, &mut client, "//NAMED/CustomA").await, before);
    for command in [
        "PROJECT SAVE NAMED",
        "PROJECT CLOSE NAMED",
        "PROJECT LOAD NAMED",
        "PROJECT USE NAMED",
    ] {
        ok_command(&service, &mut client, command).await;
    }
    let reloaded = xml(&service, &mut client, "//NAMED/CustomA").await;
    assert_eq!(oid_set(&reloaded), oids);
    // This OID-less collection selector is a local terminal-reply safety
    // check. The exact native TagsDLT selector contract remains uncaptured.
    for oid in [&graph.level, &graph.variable_level] {
        assert_eq!(
            run(&service, &mut client, &format!("DBGET !{oid}/TagsDLT/OID"))
                .await
                .status,
            401
        );
    }
    assert_eq!(
        xml(&service, &mut client, "//NAMED/CustomA").await,
        reloaded
    );
    assert_eq!(
        scalar(&service, &mut client, &format!("!{}/Value", graph.level)).await,
        "77"
    );
    assert_eq!(
        scalar(
            &service,
            &mut client,
            &format!("!{}/Value", graph.variable_level)
        )
        .await,
        "23"
    );
    assert_eq!(
        scalar(&service, &mut client, &format!("!{}/TagName", graph.app)).await,
        "Edited Lighting"
    );
    assert_eq!(
        xml(&service, &mut client, "//NAMED/Neighbor").await,
        neighbor
    );
    no_io(&mut remote).await;
    drop(service);
    let (pci_client, mut remote) = pci();
    let restarted = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    ok_command(&restarted, &mut client, "PROJECT USE NAMED").await;
    assert_eq!(
        xml(&restarted, &mut client, "//NAMED/CustomA").await,
        reloaded
    );
    assert_eq!(
        xml(&restarted, &mut client, "//NAMED/Neighbor").await,
        neighbor
    );
    no_io(&mut remote).await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn named_safe_add_and_copy_collisions_wrong_parents_and_group_bounds_are_atomic() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    setup(&service, &mut client).await;
    let graph = graph(&service, &mut client).await;
    let before = Database::from_server(&*service.model.lock().await);
    let bytes = std::fs::read(&path).unwrap();
    for command in [
        "DBADDSAFE //NAMED/CustomA Application 56 Duplicate".to_string(),
        format!("DBADDSAFE !{} Group 1 Duplicate", graph.app),
        format!("DBADDSAFE !{} Level 7 Duplicate", graph.group),
        format!("DBADDSAFE !{} NetVar 4 Duplicate", graph.app),
        format!("DBCOPYSAFE !{} //NAMED/CustomA 56 Duplicate", graph.app),
        format!("DBCOPYSAFE !{} !{} 1 Duplicate", graph.group, graph.app),
        format!("DBCOPYSAFE !{} !{} 7 Duplicate", graph.level, graph.group),
        format!("DBCOPYSAFE !{} !{} 4 Duplicate", graph.variable, graph.app),
        "DBADDSAFE //NAMED/CustomA Group 2 Wrong".to_string(),
        format!("DBADDSAFE !{} NetVar 2 Wrong", graph.group),
        format!("DBADDSAFE !{} Level 2 Wrong", graph.app),
        format!("DBADDSAFE !{} Group 256 Wrong", graph.app),
        format!("DBADDSAFE !{} Group -1 Wrong", graph.app),
        format!("DBADDSAFE !{} Group oops Wrong", graph.app),
    ] {
        let reply = run(&service, &mut client, &command).await;
        assert_eq!(reply.status, 401, "{command}: {reply:?}");
        assert!(
            Database::from_server(&*service.model.lock().await) == before,
            "{command}"
        );
        assert_eq!(std::fs::read(&path).unwrap(), bytes, "{command}");
    }
    for address in [0, 255] {
        created(
            &service,
            &mut client,
            &format!("DBADDSAFE !{} Group {address} Boundary", graph.app),
        )
        .await;
    }
    no_io(&mut remote).await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn named_independent_interface_delete_retains_graph_and_missing_alias_lifecycle() {
    for by_oid in [false, true] {
        let path = state_path();
        let (pci_client, mut remote) = pci();
        let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
        let mut client = ClientState::default();
        setup(&service, &mut client).await;
        let interface = scalar(&service, &mut client, "//NAMED/CustomA/Interface/OID").await;
        let root = scalar(&service, &mut client, "//NAMED/CustomA/OID").await;
        let neighbor = xml(&service, &mut client, "//NAMED/Neighbor").await;
        let app = created(
            &service,
            &mut client,
            "DBADDSAFE //NAMED/CustomA Application 61 Retained",
        )
        .await;
        let target = if by_oid {
            format!("!{interface}")
        } else {
            "//NAMED/CustomA/Interface".to_string()
        };
        ok_command(&service, &mut client, &format!("DBDELETE {target}")).await;
        let document = xml(&service, &mut client, "//NAMED/CustomA").await;
        assert!(!document.contains("<Interface>"));
        assert_eq!(
            scalar(&service, &mut client, "//NAMED/CustomA/OID").await,
            root
        );
        assert_eq!(
            scalar(&service, &mut client, &format!("!{app}/Address")).await,
            "61"
        );
        assert_eq!(
            run(&service, &mut client, &format!("DBGET !{interface}/OID"))
                .await
                .status,
            401
        );
        let before = Database::from_server(&*service.model.lock().await);
        let bytes = std::fs::read(&path).unwrap();
        for field in ["InterfaceType", "InterfaceAddress"] {
            for prefix in ["//NAMED/CustomA".to_string(), format!("!{root}")] {
                let response = run(&service, &mut client, &format!("DBGET {prefix}/{field}")).await;
                assert_eq!(response.status, 401, "{response:?}");
                assert!(response
                    .final_text
                    .contains(&format!("Element {field} not found")));
                for verb in ["DBSETSAFE", "DBSET"] {
                    let response = run(
                        &service,
                        &mut client,
                        &format!("{verb} {prefix}/{field} Replacement"),
                    )
                    .await;
                    assert_eq!(response.status, 401, "{response:?}");
                    assert!(response.final_text.contains("Field not found"));
                }
            }
        }
        assert!(Database::from_server(&*service.model.lock().await) == before);
        assert_eq!(std::fs::read(&path).unwrap(), bytes);
        assert_eq!(
            run(&service, &mut client, "DBVALIDATE //NAMED/CustomA")
                .await
                .status,
            233
        );
        for command in [
            "PROJECT SAVE NAMED",
            "PROJECT CLOSE NAMED",
            "PROJECT LOAD NAMED",
            "PROJECT USE NAMED",
            "NET LOAD DB",
        ] {
            ok_command(&service, &mut client, command).await;
        }
        assert_eq!(
            xml(&service, &mut client, "//NAMED/CustomA").await,
            document
        );
        assert_eq!(
            xml(&service, &mut client, "//NAMED/Neighbor").await,
            neighbor
        );
        let before = Database::from_server(&*service.model.lock().await);
        let bytes = std::fs::read(&path).unwrap();
        // Original NET SAVE after deletion reports internal error. The local
        // controlled 408 preserves graph/catalog/repository and session life.
        assert_eq!(run(&service, &mut client, "NET SAVE DB").await.status, 408);
        assert!(Database::from_server(&*service.model.lock().await) == before);
        assert_eq!(std::fs::read(&path).unwrap(), bytes);
        no_io(&mut remote).await;
        drop(service);
        let (pci_client, mut remote) = pci();
        let restarted = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
        ok_command(&restarted, &mut client, "PROJECT USE NAMED").await;
        ok_command(&restarted, &mut client, "NET LOAD DB").await;
        assert_eq!(
            xml(&restarted, &mut client, "//NAMED/CustomA").await,
            document
        );
        assert_eq!(
            xml(&restarted, &mut client, "//NAMED/Neighbor").await,
            neighbor
        );
        assert_eq!(
            run(
                &restarted,
                &mut client,
                "DBGET //NAMED/CustomA/InterfaceType"
            )
            .await
            .status,
            401
        );
        let before = Database::from_server(&*restarted.model.lock().await);
        let bytes = std::fs::read(&path).unwrap();
        assert_eq!(
            run(&restarted, &mut client, "NET SAVE DB").await.status,
            408
        );
        assert!(Database::from_server(&*restarted.model.lock().await) == before);
        assert_eq!(std::fs::read(&path).unwrap(), bytes);
        no_io(&mut remote).await;
        std::fs::remove_file(path).unwrap();
    }
}

#[tokio::test]
async fn named_independent_numeric_key_without_interface_does_not_fence_other_xml() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    for command in [
        "PROJECT USE HARNESS",
        "DBNEW",
        "NET SAVE DB",
        "NET CREATE Other Cni 127.0.0.1:1",
        "NET SAVE DB",
    ] {
        ok_command(&service, &mut client, command).await;
    }
    {
        let model = service.model.lock().await;
        assert!(model.projects["HARNESS"].networks[&254].oid.is_empty());
        assert_eq!(
            model.projects["HARNESS"].tag_networks["254"].database_network,
            None
        );
    }
    ok_command(&service, &mut client, "DBDELETE //HARNESS/254/Interface").await;
    let missing = xml(&service, &mut client, "//HARNESS/254").await;
    assert!(!missing.contains("<Interface>"));
    let runtime = service.model.lock().await.projects["HARNESS"].networks[&254].clone();
    let document = xml(&service, &mut client, "//HARNESS/Other").await;
    assert!(document.contains("<TagName>nOther</TagName>"));
    let edited = document.replace(
        "<TagName>nOther</TagName>",
        "<TagName>Other edited</TagName>",
    );
    let bytes = std::fs::read(&path).unwrap();
    let response = service
        .handle_document(&mut client, "[named-db] DBSETXML //HARNESS/Other", &edited)
        .await;
    assert_eq!(response.status, 301, "{response:?}");
    assert_eq!(
        scalar(&service, &mut client, "//HARNESS/Other/TagName").await,
        "Other edited"
    );
    assert_eq!(xml(&service, &mut client, "//HARNESS/254").await, missing);
    assert_eq!(
        service.model.lock().await.projects["HARNESS"].networks[&254],
        runtime
    );
    assert_ne!(std::fs::read(&path).unwrap(), bytes);
    assert_eq!(
        run(&service, &mut client, "DBGET //HARNESS/254/InterfaceType")
            .await
            .status,
        401
    );
    no_io(&mut remote).await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn named_associated_configured_owner_keeps_document_binding_immutable() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    for command in [
        "PROJECT USE HARNESS",
        "DBSETSAFE //HARNESS/254/p/5/UnitName Fixture eDLT",
        "NET SAVE DB",
    ] {
        ok_command(&service, &mut client, command).await;
    }
    assert_eq!(
        service.model.lock().await.projects["HARNESS"].tag_networks["254"].database_network,
        Some(254)
    );
    let document = xml(&service, &mut client, "//HARNESS/254").await;
    let accepted = service
        .handle_document(&mut client, "[named-db] DBSETXML //HARNESS/254", &document)
        .await;
    assert_eq!(accepted.status, 301, "{accepted:?}");
    let document = xml(&service, &mut client, "//HARNESS/254").await;
    let before = Database::from_server(&*service.model.lock().await);
    let bytes = std::fs::read(&path).unwrap();
    let original_number = scalar(&service, &mut client, "//HARNESS/254/NetworkNumber").await;
    let original_type = scalar(&service, &mut client, "//HARNESS/254/InterfaceType").await;
    let original_address = scalar(&service, &mut client, "//HARNESS/254/InterfaceAddress").await;
    for (old, new) in [
        (
            "<Address>254</Address>".to_string(),
            "<Address>253</Address>".to_string(),
        ),
        (
            format!("<NetworkNumber>{original_number}</NetworkNumber>"),
            "<NetworkNumber>253</NetworkNumber>".to_string(),
        ),
        (
            format!("<InterfaceType>{original_type}</InterfaceType>"),
            "<InterfaceType>Serial</InterfaceType>".to_string(),
        ),
        (
            format!("<InterfaceAddress>{original_address}</InterfaceAddress>"),
            "<InterfaceAddress>127.0.0.1:1</InterfaceAddress>".to_string(),
        ),
    ] {
        assert!(document.contains(&old));
        let replacement = document.replacen(&old, &new, 1);
        let response = service
            .handle_document(
                &mut client,
                "[named-db] DBSETXML //HARNESS/254",
                &replacement,
            )
            .await;
        assert_eq!(response.status, 408, "{old}: {response:?}");
        assert!(Database::from_server(&*service.model.lock().await) == before);
        assert_eq!(std::fs::read(&path).unwrap(), bytes);
        assert_eq!(xml(&service, &mut client, "//HARNESS/254").await, document);
    }
    no_io(&mut remote).await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn named_associated_interface_delete_keeps_complete_numeric_invariant_atomic() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    setup(&service, &mut client).await;
    for command in [
        "DBCREATENET 11 Eleven Cni 127.0.0.1:1",
        "NET LOAD DB",
        "NET SAVE DB",
    ] {
        ok_command(&service, &mut client, command).await;
    }
    assert_eq!(
        service.model.lock().await.projects["NAMED"].tag_networks["11"].database_network,
        Some(11)
    );
    let interface = scalar(&service, &mut client, "//NAMED/11/Interface/OID").await;
    let before = Database::from_server(&*service.model.lock().await);
    let bytes = std::fs::read(&path).unwrap();
    for target in ["//NAMED/11/Interface".to_string(), format!("!{interface}")] {
        assert_eq!(
            run(&service, &mut client, &format!("DBDELETE {target}"))
                .await
                .status,
            408
        );
        assert!(Database::from_server(&*service.model.lock().await) == before);
        assert_eq!(std::fs::read(&path).unwrap(), bytes);
    }
    assert_eq!(
        scalar(&service, &mut client, "//NAMED/11/InterfaceType").await,
        "Cni"
    );
    no_io(&mut remote).await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn named_safe_network_rename_collision_refuses_without_losing_either_owner() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    setup(&service, &mut client).await;
    for command in [
        "NET CREATE 1 Cni 127.0.0.1:1",
        "NET CREATE 2 Cni 127.0.0.1:1",
        "NET SAVE DB",
        "DBCREATENET 11 Eleven Cni 127.0.0.1:1",
        "DBCREATENET 12 Twelve Cni 127.0.0.1:1",
        "NET LOAD DB",
        "NET SAVE DB",
    ] {
        ok_command(&service, &mut client, command).await;
    }
    {
        let model = service.model.lock().await;
        assert_eq!(
            model.projects["NAMED"].tag_networks["1"].database_network,
            None
        );
        assert_eq!(
            model.projects["NAMED"].tag_networks["2"].database_network,
            None
        );
        assert_eq!(
            model.projects["NAMED"].tag_networks["11"].database_network,
            Some(11)
        );
        assert_eq!(
            model.projects["NAMED"].tag_networks["12"].database_network,
            Some(12)
        );
    }
    let first = scalar(&service, &mut client, "//NAMED/1/OID").await;
    let custom = scalar(&service, &mut client, "//NAMED/CustomA/OID").await;
    let neighbor = scalar(&service, &mut client, "//NAMED/Neighbor/OID").await;
    let before = Database::from_server(&*service.model.lock().await);
    let bytes = std::fs::read(&path).unwrap();
    for command in [
        "DBRENAMENETSAFE 1 2".to_string(),
        "DBRENAMENETSAFE //NAMED/1 2".to_string(),
        format!("DBRENAMENETSAFE !{first} 2"),
        "DBRENAMENETSAFE 11 12".to_string(),
        "DBRENAMENETSAFE CustomA Neighbor".to_string(),
    ] {
        let response = run(&service, &mut client, &command).await;
        assert_eq!(response.status, 408, "{command}: {response:?}");
        assert!(Database::from_server(&*service.model.lock().await) == before);
        assert_eq!(std::fs::read(&path).unwrap(), bytes);
    }
    // The captured unsafe scalar Address operation deliberately permits
    // duplicate lexical identities. SAFE rename must not remove that route.
    ok_command(
        &service,
        &mut client,
        "DBSET //NAMED/CustomA/Address Neighbor",
    )
    .await;
    for oid in [&custom, &neighbor] {
        assert_eq!(
            scalar(&service, &mut client, &format!("!{oid}/Address")).await,
            "Neighbor"
        );
    }
    ok_command(&service, &mut client, "PROJECT SAVE NAMED").await;
    no_io(&mut remote).await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn named_raw_safe_and_unsafe_scalar_writes_preserve_native_literal_values() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    setup(&service, &mut client).await;
    let graph = graph(&service, &mut client).await;
    assert_eq!(
        service.model.lock().await.projects["NAMED"].tag_networks["CustomA"].database_network,
        None
    );
    let neighbor = xml(&service, &mut client, "//NAMED/Neighbor").await;
    // The owned original scalar capture admits these exact lexemes for both
    // commands. This independent record does not delegate to numeric Value
    // parsing; complete external XML and typed CLI validation are separate.
    for verb in ["DBSETSAFE", "DBSET"] {
        for value in ["255", "0xff", "999", "oops", "-1"] {
            ok_command(
                &service,
                &mut client,
                &format!("{verb} //NAMED/CustomA/NetworkNumber {value}"),
            )
            .await;
            ok_command(
                &service,
                &mut client,
                &format!("{verb} !{}/Value {value}", graph.level),
            )
            .await;
            assert_eq!(
                scalar(&service, &mut client, "//NAMED/CustomA/NetworkNumber").await,
                value
            );
            assert_eq!(
                scalar(&service, &mut client, &format!("!{}/Value", graph.level)).await,
                value
            );
            let document = xml(&service, &mut client, "//NAMED/CustomA").await;
            let parsed = roxmltree::Document::parse(&document).unwrap();
            assert_eq!(
                parsed
                    .root_element()
                    .children()
                    .find(|node| node.has_tag_name("NetworkNumber"))
                    .unwrap()
                    .text(),
                Some(value)
            );
            assert_eq!(
                parsed
                    .descendants()
                    .find(|node| node.has_tag_name("Level")
                        && node.children().any(|child| child.has_tag_name("OID")
                            && child.text() == Some(graph.level.as_str())))
                    .unwrap()
                    .attribute("Value"),
                Some(value)
            );
            assert_eq!(
                xml(&service, &mut client, "//NAMED/Neighbor").await,
                neighbor
            );
        }
    }
    assert_eq!(
        run(&service, &mut client, "DBVALIDATE //NAMED/CustomA")
            .await
            .status,
        233
    );
    for command in [
        "PROJECT SAVE NAMED",
        "PROJECT CLOSE NAMED",
        "PROJECT LOAD NAMED",
        "PROJECT USE NAMED",
    ] {
        ok_command(&service, &mut client, command).await;
    }
    assert_eq!(
        scalar(&service, &mut client, "//NAMED/CustomA/NetworkNumber").await,
        "-1"
    );
    assert_eq!(
        scalar(&service, &mut client, &format!("!{}/Value", graph.level)).await,
        "-1"
    );
    assert_eq!(
        xml(&service, &mut client, "//NAMED/Neighbor").await,
        neighbor
    );
    no_io(&mut remote).await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn named_complete_external_xml_keeps_strict_scalar_admission_atomic() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    setup(&service, &mut client).await;
    let graph = graph(&service, &mut client).await;
    let document = xml(&service, &mut client, "//NAMED/CustomA").await;
    let before = Database::from_server(&*service.model.lock().await);
    let bytes = std::fs::read(&path).unwrap();
    assert!(document.contains("<NetworkNumber>0xff</NetworkNumber>"));
    let level_document = xml(&service, &mut client, &format!("!{}", graph.level)).await;
    assert!(level_document.contains("Value=\"77\""));
    // Local complete-document admission is deliberately stricter than owned
    // raw scalar editing. A refusal must not replace or persist any subtree.
    for value in ["999", "oops", "-1"] {
        for (target, replacement) in [
            (
                "//NAMED/CustomA".to_string(),
                document.replace(
                    "<NetworkNumber>0xff</NetworkNumber>",
                    &format!("<NetworkNumber>{value}</NetworkNumber>"),
                ),
            ),
            (
                format!("!{}", graph.level),
                level_document.replace("Value=\"77\"", &format!("Value=\"{value}\"")),
            ),
        ] {
            let response = service
                .handle_document(
                    &mut client,
                    &format!("[named-db] DBSETXML {target}"),
                    &replacement,
                )
                .await;
            assert_eq!(response.status, 408, "{target} {value}: {response:?}");
            assert!(Database::from_server(&*service.model.lock().await) == before);
            assert_eq!(std::fs::read(&path).unwrap(), bytes);
            assert_eq!(
                xml(&service, &mut client, "//NAMED/CustomA").await,
                document
            );
        }
    }
    no_io(&mut remote).await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn named_safe_copy_refreshes_entire_oid_closure_and_retains_values_and_source_xml() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    setup(&service, &mut client).await;
    let graph = graph(&service, &mut client).await;
    for (source, parent, address, name, expected_value) in [
        (
            &graph.app,
            "//NAMED/CustomA".to_string(),
            57,
            "Copy App",
            None,
        ),
        (
            &graph.group,
            format!("!{}", graph.app),
            9,
            "Copy Group",
            None,
        ),
        (
            &graph.level,
            format!("!{}", graph.group),
            8,
            "Copy Level",
            Some("77"),
        ),
        (
            &graph.variable,
            format!("!{}", graph.app),
            5,
            "Copy Variable",
            None,
        ),
    ] {
        let source_xml = xml(&service, &mut client, &format!("!{source}")).await;
        let source_oids = oid_set(&source_xml);
        let copied = created(
            &service,
            &mut client,
            &format!("DBCOPYSAFE !{source} {parent} {address} {name}"),
        )
        .await;
        let copied_xml = xml(&service, &mut client, &format!("!{copied}")).await;
        let copied_oids = oid_set(&copied_xml);
        assert_eq!(copied_oids.len(), source_oids.len());
        assert!(source_oids.is_disjoint(&copied_oids));
        assert_eq!(
            scalar(&service, &mut client, &format!("!{copied}/Address")).await,
            address.to_string()
        );
        assert_eq!(
            scalar(&service, &mut client, &format!("!{copied}/TagName")).await,
            name
        );
        if let Some(value) = expected_value {
            assert_eq!(
                scalar(&service, &mut client, &format!("!{copied}/Value")).await,
                value
            );
        }
        assert_eq!(
            xml(&service, &mut client, &format!("!{source}")).await,
            source_xml
        );
    }
    no_io(&mut remote).await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn named_pending_child_first_names_only_graph_survives_project_reload_and_daemon_restart() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    setup(&service, &mut client).await;
    let app = created(&service, &mut client, "DBADD //NAMED/CustomA Application").await;
    let group = created(&service, &mut client, &format!("DBADD !{app} Group")).await;
    let level = created(&service, &mut client, &format!("DBADD !{group} Level")).await;
    let variable = created(&service, &mut client, &format!("DBADD !{app} NetVar")).await;
    let variable_level = created(&service, &mut client, &format!("DBADD !{variable} Level")).await;
    assert_eq!(
        run(&service, &mut client, "DBGETXML //NAMED/CustomA")
            .await
            .status,
        444
    );
    for (oid, name) in [
        (&level, "Child Level"),
        (&group, "Child Group"),
        (&variable_level, "Variable Level"),
        (&variable, "Variable"),
        (&app, "Parent App"),
    ] {
        ok_command(
            &service,
            &mut client,
            &format!("DBSET !{oid}/TagName {name}"),
        )
        .await;
    }
    for (oid, value) in [(&level, 11), (&variable_level, 13)] {
        ok_command(
            &service,
            &mut client,
            &format!("DBSET !{oid}/Value {value}"),
        )
        .await;
    }
    let before = xml(&service, &mut client, "//NAMED/CustomA").await;
    let parsed = roxmltree::Document::parse(&before).unwrap();
    for element in ["Application", "Group", "Level", "NetVar"] {
        assert!(parsed
            .descendants()
            .filter(|n| n.has_tag_name(element))
            .all(|n| n.children().all(|c| !c.has_tag_name("Address"))));
    }
    for command in [
        "PROJECT SAVE NAMED",
        "PROJECT CLOSE NAMED",
        "PROJECT LOAD NAMED",
        "PROJECT USE NAMED",
    ] {
        ok_command(&service, &mut client, command).await;
    }
    let reloaded = xml(&service, &mut client, "//NAMED/CustomA").await;
    assert_eq!(oid_set(&reloaded), oid_set(&before));
    for oid in [&app, &group, &level, &variable, &variable_level] {
        assert_eq!(
            scalar(&service, &mut client, &format!("!{oid}/OID")).await,
            *oid
        );
        assert_eq!(
            run(&service, &mut client, &format!("DBGET !{oid}/Address"))
                .await
                .status,
            401
        );
    }
    no_io(&mut remote).await;
    drop(service);
    let (pci_client, mut remote) = pci();
    let restarted = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    ok_command(&restarted, &mut client, "PROJECT USE NAMED").await;
    assert_eq!(
        xml(&restarted, &mut client, "//NAMED/CustomA").await,
        reloaded
    );
    ok_command(
        &restarted,
        &mut client,
        &format!("DBSET !{group}/Address 2"),
    )
    .await;
    ok_command(
        &restarted,
        &mut client,
        &format!("DBSET !{level}/Address 7"),
    )
    .await;
    ok_command(&restarted, &mut client, &format!("DBSET !{app}/Address 56")).await;
    assert_eq!(
        scalar(&restarted, &mut client, "//NAMED/CustomA/56/2/7/Value").await,
        "11"
    );
    no_io(&mut remote).await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn named_pending_missing_name_and_level_value_refuse_save_without_replacing_saved_baseline() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    setup(&service, &mut client).await;
    let baseline = xml(&service, &mut client, "//NAMED/CustomA").await;
    let app = created(&service, &mut client, "DBADD //NAMED/CustomA Application").await;
    ok_command(&service, &mut client, &format!("DBSET !{app}/Address 60")).await;
    let before = Database::from_server(&*service.model.lock().await);
    let bytes = std::fs::read(&path).unwrap();
    assert_eq!(
        run(&service, &mut client, "DBGETXML //NAMED/CustomA")
            .await
            .status,
        444
    );
    let failed = run(&service, &mut client, "PROJECT SAVE NAMED").await;
    assert_eq!(failed.status, 408, "{failed:?}");
    assert!(failed.final_text.contains("tagged_entity.tag_name"));
    assert!(Database::from_server(&*service.model.lock().await) == before);
    assert_eq!(std::fs::read(&path).unwrap(), bytes);
    assert_eq!(
        scalar(&service, &mut client, &format!("!{app}/Address")).await,
        "60"
    );
    for command in [
        "PROJECT CLOSE NAMED",
        "PROJECT LOAD NAMED",
        "PROJECT USE NAMED",
    ] {
        ok_command(&service, &mut client, command).await;
    }
    assert_eq!(
        xml(&service, &mut client, "//NAMED/CustomA").await,
        baseline
    );
    assert_eq!(
        run(&service, &mut client, &format!("DBGET !{app}/OID"))
            .await
            .status,
        401
    );
    let app = created(
        &service,
        &mut client,
        "DBADDSAFE //NAMED/CustomA Application 56 Lighting",
    )
    .await;
    let group = created(
        &service,
        &mut client,
        &format!("DBADDSAFE !{app} Group 1 Main"),
    )
    .await;
    let level = created(
        &service,
        &mut client,
        &format!("DBADDSAFE !{group} Level 7 Null"),
    )
    .await;
    assert_eq!(
        run(&service, &mut client, &format!("DBGETXML !{level}"))
            .await
            .status,
        200
    );
    let failed = run(&service, &mut client, "PROJECT SAVE NAMED").await;
    assert_eq!(failed.status, 408, "{failed:?}");
    assert!(failed.final_text.contains("level_tag.value"));
    ok_command(
        &service,
        &mut client,
        &format!("DBSETSAFE !{level}/Value 7"),
    )
    .await;
    ok_command(&service, &mut client, "PROJECT SAVE NAMED").await;
    no_io(&mut remote).await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn named_pending_unsafe_address_lexemes_and_sibling_creation_order_survive_reload() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    setup(&service, &mut client).await;
    let app = created(
        &service,
        &mut client,
        "DBADDSAFE //NAMED/CustomA Application 56 Lighting",
    )
    .await;
    let mut groups = Vec::new();
    for address in ["9", "2", "2", "256", "-1", "oops"] {
        let oid = created(&service, &mut client, &format!("DBADD !{app} Group")).await;
        ok_command(
            &service,
            &mut client,
            &format!("DBSET !{oid}/Address {address}"),
        )
        .await;
        ok_command(
            &service,
            &mut client,
            &format!("DBSET !{oid}/TagName Group {address}"),
        )
        .await;
        groups.push((oid, address));
    }
    for command in [
        "PROJECT SAVE NAMED",
        "PROJECT CLOSE NAMED",
        "PROJECT LOAD NAMED",
        "PROJECT USE NAMED",
    ] {
        ok_command(&service, &mut client, command).await;
    }
    let document = xml(&service, &mut client, &format!("!{app}")).await;
    let parsed = roxmltree::Document::parse(&document).unwrap();
    assert_eq!(
        parsed
            .descendants()
            .filter(|n| n.has_tag_name("Group"))
            .map(|n| n
                .children()
                .find(|c| c.has_tag_name("Address"))
                .unwrap()
                .text()
                .unwrap())
            .collect::<Vec<_>>(),
        ["9", "2", "2", "256", "-1", "oops"]
    );
    for (oid, address) in groups {
        assert_eq!(
            scalar(&service, &mut client, &format!("!{oid}/Address")).await,
            address
        );
    }
    no_io(&mut remote).await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn named_pending_owner_survives_network_rename_and_is_retired_after_delete_and_project_reuse()
{
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    setup(&service, &mut client).await;
    let app = created(&service, &mut client, "DBADD //NAMED/CustomA Application").await;
    let group = created(&service, &mut client, &format!("DBADD !{app} Group")).await;
    ok_command(&service, &mut client, "DBRENAMENET CustomA CustomB").await;
    for (oid, name, address) in [(&group, "Child", 2), (&app, "Parent", 56)] {
        ok_command(
            &service,
            &mut client,
            &format!("DBSET !{oid}/TagName {name}"),
        )
        .await;
        ok_command(
            &service,
            &mut client,
            &format!("DBSET !{oid}/Address {address}"),
        )
        .await;
    }
    assert_eq!(
        scalar(&service, &mut client, "//NAMED/CustomB/56/2/OID").await,
        group
    );
    ok_command(&service, &mut client, &format!("DBDELETE !{app}")).await;
    // Local coherent retirement is deliberate; the original leaves stale
    // descendant OID fields until a subsequent saved project reload.
    for oid in [&app, &group] {
        assert_eq!(
            run(&service, &mut client, &format!("DBGET !{oid}/OID"))
                .await
                .status,
            401
        );
    }
    for command in [
        "PROJECT SAVE NAMED",
        "PROJECT CLOSE NAMED",
        "PROJECT DELETE NAMED",
        "PROJECT NEW NAMED",
        "PROJECT USE NAMED",
        "NET CREATE CustomB Cni 127.0.0.1:1",
        "NET SAVE DB",
    ] {
        ok_command(&service, &mut client, command).await;
    }
    let fresh = created(&service, &mut client, "DBADD //NAMED/CustomB Application").await;
    assert_ne!(fresh, app);
    for oid in [&app, &group] {
        assert_eq!(
            run(&service, &mut client, &format!("DBGET !{oid}/OID"))
                .await
                .status,
            401
        );
    }
    no_io(&mut remote).await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn named_unsafe_deep_network_copy_census_completes_fresh_graph_and_retains_number_metadata_values(
) {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    setup(&service, &mut client).await;
    graph(&service, &mut client).await;
    ok_command(
        &service,
        &mut client,
        "DBSET //NAMED/CustomA/NetworkNumber 17",
    )
    .await;
    let source = xml(&service, &mut client, "//NAMED/CustomA").await;
    let copied = created(
        &service,
        &mut client,
        "DBCOPY //NAMED/CustomA Installation/Project",
    )
    .await;
    assert_eq!(
        scalar(&service, &mut client, &format!("!{copied}/NetworkNumber")).await,
        "17"
    );
    for field in ["Address", "TagName"] {
        assert_eq!(
            run(&service, &mut client, &format!("DBGET !{copied}/{field}"))
                .await
                .status,
            401
        );
    }
    assert_eq!(
        run(&service, &mut client, &format!("DBGETXML !{copied}"))
            .await
            .status,
        444
    );
    let app = scalar(
        &service,
        &mut client,
        &format!("!{copied}/Application[1]/OID"),
    )
    .await;
    let group = scalar(&service, &mut client, &format!("!{app}/Group[1]/OID")).await;
    let level = scalar(&service, &mut client, &format!("!{group}/Level[1]/OID")).await;
    let variable = scalar(&service, &mut client, &format!("!{app}/NetVar[1]/OID")).await;
    let variable_level = scalar(&service, &mut client, &format!("!{variable}/Level[1]/OID")).await;
    let interface = scalar(
        &service,
        &mut client,
        &format!("!{copied}/Interface[1]/OID"),
    )
    .await;
    assert_eq!(
        scalar(
            &service,
            &mut client,
            &format!("!{copied}/Interface[2]/OID")
        )
        .await,
        interface
    );
    assert_eq!(
        run(
            &service,
            &mut client,
            &format!("DBGET !{copied}/Application[2]/OID")
        )
        .await
        .status,
        401
    );
    let census = run(
        &service,
        &mut client,
        &format!("DBGET !{copied}/Application/OID"),
    )
    .await;
    assert_eq!(census.status, 342);
    assert!(census.final_text.ends_with(&format!("={app}")));
    for (oid, name) in [
        (&variable_level, "Copied Variable Level"),
        (&level, "Copied Level"),
        (&group, "Copied Group"),
        (&variable, "Copied Variable"),
        (&app, "Copied App"),
        (&copied, "Copied Network"),
    ] {
        ok_command(
            &service,
            &mut client,
            &format!("DBSET !{oid}/TagName {name}"),
        )
        .await;
    }
    assert_eq!(
        scalar(&service, &mut client, &format!("!{level}/Value")).await,
        "77"
    );
    assert_eq!(
        scalar(&service, &mut client, &format!("!{variable_level}/Value")).await,
        "23"
    );
    let names_only = xml(&service, &mut client, &format!("!{copied}")).await;
    let fresh_oids = oid_set(&names_only);
    assert_eq!(fresh_oids.len(), oid_set(&source).len());
    assert!(fresh_oids.is_disjoint(&oid_set(&source)));
    let copied_document = roxmltree::Document::parse(&names_only).unwrap();
    let properties = copied_document
        .descendants()
        .filter(|node| node.has_tag_name("Property"))
        .map(|node| {
            let field = |name| {
                node.children()
                    .find(|child| child.has_tag_name(name))
                    .unwrap()
                    .text()
                    .unwrap()
            };
            (field("Name"), field("Value"))
        })
        .collect::<Vec<_>>();
    assert_eq!(properties, [("owned", "yes"), ("second", "two")]);
    for command in [
        "PROJECT SAVE NAMED",
        "PROJECT CLOSE NAMED",
        "PROJECT LOAD NAMED",
        "PROJECT USE NAMED",
    ] {
        ok_command(&service, &mut client, command).await;
    }
    assert_eq!(
        scalar(&service, &mut client, &format!("!{copied}/NetworkNumber")).await,
        "17"
    );
    for (oid, address) in [
        (&copied, "Copy"),
        (&app, "57"),
        (&group, "2"),
        (&level, "8"),
        (&variable, "5"),
        (&variable_level, "43"),
    ] {
        ok_command(
            &service,
            &mut client,
            &format!("DBSET !{oid}/Address {address}"),
        )
        .await;
    }
    assert_eq!(
        scalar(&service, &mut client, "//NAMED/Copy/57/2/8/Value").await,
        "77"
    );
    assert_eq!(
        scalar(&service, &mut client, "//NAMED/Copy/57/5/43/Value").await,
        "23"
    );
    assert_eq!(
        oid_set(&xml(&service, &mut client, "//NAMED/Copy").await),
        fresh_oids
    );
    // Source reload may add empty Level TagsDLT. No copied mutation may alter
    // the already reloaded source snapshot.
    let reloaded_source = xml(&service, &mut client, "//NAMED/CustomA").await;
    ok_command(
        &service,
        &mut client,
        &format!("DBSET !{copied}/TagName Edited Copy"),
    )
    .await;
    assert_eq!(
        xml(&service, &mut client, "//NAMED/CustomA").await,
        reloaded_source
    );
    no_io(&mut remote).await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn named_database_repository_commit_failure_rolls_back_pending_copy_completion_and_delete() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    setup(&service, &mut client).await;
    let graph = graph(&service, &mut client).await;
    let pending = created(&service, &mut client, "DBADD //NAMED/CustomA Application").await;
    ok_command(
        &service,
        &mut client,
        &format!("DBSET !{pending}/TagName Pending"),
    )
    .await;
    let before = Database::from_server(&*service.model.lock().await);
    let bytes = std::fs::read(&path).unwrap();
    std::fs::remove_file(&path).unwrap();
    std::fs::create_dir(&path).unwrap();
    for command in [
        "DBADD //NAMED/CustomA Application".to_string(),
        "DBADDSAFE //NAMED/CustomA Application 60 Added".to_string(),
        format!("DBSET !{pending}/Address 61"),
        format!("DBSETSAFE !{}/Value 12", graph.level),
        format!("DBCOPYSAFE !{} //NAMED/CustomA 57 Copy", graph.app),
        "DBCOPY //NAMED/CustomA Installation/Project".to_string(),
        format!("DBDELETE !{}", graph.app),
        "DBRENAMENET CustomA CustomB".to_string(),
    ] {
        let failed = run(&service, &mut client, &command).await;
        assert_eq!(
            failed.final_text, "500 Database commit failed; change rolled back",
            "{command}: {failed:?}"
        );
        assert!(
            Database::from_server(&*service.model.lock().await) == before,
            "{command}"
        );
        assert_eq!(client.current.as_deref(), Some("NAMED"));
        assert!(path.is_dir());
    }
    std::fs::remove_dir(&path).unwrap();
    std::fs::write(&path, bytes).unwrap();
    no_io(&mut remote).await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn named_pending_external_dbsetxml_stays_strict_and_cross_project_selection_is_operation_specific(
) {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    setup(&service, &mut client).await;
    let app = created(&service, &mut client, "DBADD //NAMED/CustomA Application").await;
    ok_command(
        &service,
        &mut client,
        &format!("DBSET !{app}/TagName Named only"),
    )
    .await;
    let document = xml(&service, &mut client, "//NAMED/CustomA").await;
    let before = Database::from_server(&*service.model.lock().await);
    let bytes = std::fs::read(&path).unwrap();
    let response = service
        .handle_document(
            &mut client,
            "[named-db] DBSETXML //NAMED/CustomA",
            &document,
        )
        .await;
    assert!(response.status >= 400, "{response:?}");
    assert!(Database::from_server(&*service.model.lock().await) == before);
    assert_eq!(std::fs::read(&path).unwrap(), bytes);
    ok_command(&service, &mut client, "PROJECT USE HARNESS").await;
    // OID mutations remain selected-project scoped; native qualified SAFE
    // creation can instead target the named project's absolute parent.
    for command in [
        format!("DBSETSAFE !{app}/TagName Other"),
        format!("DBCOPYSAFE !{app} //NAMED/CustomA 58 Other"),
    ] {
        assert_eq!(run(&service, &mut client, &command).await.status, 401);
        assert!(Database::from_server(&*service.model.lock().await) == before);
        assert_eq!(std::fs::read(&path).unwrap(), bytes);
    }
    let other_before = xml(&service, &mut client, "//HARNESS").await;
    let absolute = created(
        &service,
        &mut client,
        "DBADDSAFE //NAMED/CustomA Application 58 Absolute",
    )
    .await;
    assert_eq!(client.current.as_deref(), Some("HARNESS"));
    assert_eq!(xml(&service, &mut client, "//HARNESS").await, other_before);
    ok_command(&service, &mut client, "PROJECT USE NAMED").await;
    assert_eq!(
        scalar(&service, &mut client, &format!("!{absolute}/Address")).await,
        "58"
    );
    no_io(&mut remote).await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn named_absolute_add_and_oid_mutations_require_login_before_any_database_change() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    setup(&service, &mut client).await;
    let graph = graph(&service, &mut client).await;
    let before = Database::from_server(&*service.model.lock().await);
    let bytes = std::fs::read(&path).unwrap();
    service
        .set_auth_token_hash(crate::auth::sha256(b"named-db-test-token"))
        .unwrap();
    for command in [
        "DBADD //NAMED/CustomA Application".to_string(),
        "DBADDSAFE //NAMED/CustomA Application 60 Denied".to_string(),
        format!("DBSET !{}/TagName Denied", graph.app),
        format!("DBSETSAFE !{}/TagName Denied", graph.app),
        "DBCOPY //NAMED/CustomA Installation/Project".to_string(),
        format!("DBCOPYSAFE !{} //NAMED/CustomA 57 Denied", graph.app),
        format!("DBDELETE !{}", graph.app),
    ] {
        assert_eq!(
            run(&service, &mut client, &command).await.status,
            420,
            "{command}"
        );
        assert!(
            Database::from_server(&*service.model.lock().await) == before,
            "{command}"
        );
        assert_eq!(std::fs::read(&path).unwrap(), bytes, "{command}");
    }
    ok_command(&service, &mut client, "LOGIN named-db-test-token").await;
    ok_command(&service, &mut client, "PROJECT USE HARNESS").await;
    let absolute = created(
        &service,
        &mut client,
        "DBADDSAFE //NAMED/CustomA Application 60 Admitted",
    )
    .await;
    assert_eq!(client.current.as_deref(), Some("HARNESS"));
    ok_command(&service, &mut client, "PROJECT USE NAMED").await;
    assert_eq!(
        scalar(&service, &mut client, &format!("!{absolute}/TagName")).await,
        "Admitted"
    );
    no_io(&mut remote).await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn named_internal_root_keys_never_overwrite_another_raw_address_owner() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    setup(&service, &mut client).await;
    let source = xml(&service, &mut client, "//NAMED/CustomA").await;
    let first = created(
        &service,
        &mut client,
        "DBCOPY //NAMED/CustomA Installation/Project",
    )
    .await;
    let second = created(
        &service,
        &mut client,
        "DBCOPY //NAMED/CustomA Installation/Project",
    )
    .await;
    for (oid, name) in [(&first, "First Copy"), (&second, "Second Copy")] {
        ok_command(
            &service,
            &mut client,
            &format!("DBSET !{oid}/TagName {name}"),
        )
        .await;
    }
    // This is a local ownership safety case, not an original capture of this
    // particular Address lexeme. A caller's value must never be a map key
    // that silently overwrites a different pending root.
    ok_command(
        &service,
        &mut client,
        &format!("DBSET !{first}/Address !{second}"),
    )
    .await;
    ok_command(
        &service,
        &mut client,
        &format!("DBSET !{second}/Address CustomA"),
    )
    .await;
    assert_eq!(
        service.model.lock().await.projects["NAMED"]
            .tag_networks
            .len(),
        4
    );
    assert_eq!(
        scalar(&service, &mut client, &format!("!{first}/Address")).await,
        format!("!{second}")
    );
    assert_eq!(
        scalar(&service, &mut client, &format!("!{second}/Address")).await,
        "CustomA"
    );
    assert_eq!(xml(&service, &mut client, "//NAMED/CustomA").await, source);
    ok_command(
        &service,
        &mut client,
        &format!("DBSET !{first}/TagName First Edited"),
    )
    .await;
    for command in [
        "PROJECT SAVE NAMED",
        "PROJECT CLOSE NAMED",
        "PROJECT LOAD NAMED",
        "PROJECT USE NAMED",
    ] {
        ok_command(&service, &mut client, command).await;
    }
    assert_eq!(
        service.model.lock().await.projects["NAMED"]
            .tag_networks
            .len(),
        4
    );
    assert_eq!(
        scalar(&service, &mut client, &format!("!{first}/TagName")).await,
        "First Edited"
    );
    assert_eq!(
        scalar(&service, &mut client, &format!("!{second}/TagName")).await,
        "Second Copy"
    );
    no_io(&mut remote).await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn named_project_oid_has_one_active_owner_survives_restart_and_retires_on_project_delete() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    setup(&service, &mut client).await;
    let project_oid = scalar(&service, &mut client, "Installation/Project/OID").await;
    let before = Database::from_server(&*service.model.lock().await);
    let bytes = std::fs::read(&path).unwrap();
    // These wrapper operations are outside the admitted direct-identity and
    // copy-destination scope. Require a terminal refusal, never opaque success
    // or an invented descendant resolution; exact native forms remain open.
    for command in [
        format!("DBGET !{project_oid}/Network/OID"),
        format!("DBGET !{project_oid}/anything/OID"),
        format!("DBSETSAFE !{project_oid}/TagName Other"),
        format!("DBSETSAFE !{project_oid}/Value 3"),
        format!("DBDELETE !{project_oid}"),
    ] {
        assert_eq!(
            run(&service, &mut client, &command).await.status,
            401,
            "{command}"
        );
        assert!(
            Database::from_server(&*service.model.lock().await) == before,
            "{command}"
        );
        assert_eq!(std::fs::read(&path).unwrap(), bytes, "{command}");
    }
    assert!(service
        .model
        .lock()
        .await
        .active_db_oids("NAMED")
        .contains(&project_oid));
    assert_eq!(
        scalar(&service, &mut client, &format!("!{project_oid}/OID")).await,
        project_oid
    );
    ok_command(&service, &mut client, "DBDELETE //NAMED/CustomA").await;
    assert_eq!(
        scalar(&service, &mut client, "Installation/Project/OID").await,
        project_oid
    );
    ok_command(&service, &mut client, "PROJECT SAVE NAMED").await;
    // A legacy/incomplete global index must be rebuilt from the single
    // authoritative envelope owner, without reallocating its identity.
    let mut image =
        serde_json::to_value(Database::from_server(&*service.model.lock().await)).unwrap();
    image["known_oids"]
        .as_array_mut()
        .unwrap()
        .retain(|oid| oid.as_str() != Some(&project_oid));
    let reference = format!("!{project_oid}");
    image["objects"]
        .as_array_mut()
        .unwrap()
        .retain(|object| object.as_str() != Some(&reference));
    std::fs::write(&path, serde_json::to_vec(&image).unwrap()).unwrap();
    no_io(&mut remote).await;
    drop(service);
    let (pci_client, mut remote) = pci();
    let restarted = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    ok_command(&restarted, &mut client, "PROJECT USE NAMED").await;
    assert_eq!(
        scalar(&restarted, &mut client, "Installation/Project/OID").await,
        project_oid
    );
    assert!(restarted
        .model
        .lock()
        .await
        .active_db_oids("NAMED")
        .contains(&project_oid));
    assert!(restarted.model.lock().await.objects.contains(&reference));
    let persisted: serde_json::Value =
        serde_json::from_slice(&std::fs::read(&path).unwrap()).unwrap();
    assert!(persisted["known_oids"]
        .as_array()
        .unwrap()
        .iter()
        .any(|oid| oid.as_str() == Some(&project_oid)));
    assert!(persisted["objects"]
        .as_array()
        .unwrap()
        .iter()
        .any(|object| object.as_str() == Some(&reference)));
    for command in [
        "PROJECT CLOSE NAMED",
        "PROJECT DELETE NAMED",
        "PROJECT NEW NAMED",
        "PROJECT USE NAMED",
    ] {
        ok_command(&restarted, &mut client, command).await;
    }
    assert_eq!(
        run(
            &restarted,
            &mut client,
            &format!("DBGET !{project_oid}/OID")
        )
        .await
        .status,
        401
    );
    assert!(!restarted
        .model
        .lock()
        .await
        .active_db_oids("NAMED")
        .contains(&project_oid));
    assert!(!restarted
        .model
        .lock()
        .await
        .known_oids
        .contains(&project_oid));
    no_io(&mut remote).await;
    std::fs::remove_file(path).unwrap();
}
