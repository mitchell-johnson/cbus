//! Closed database journeys. Original observations are separately retained;
//! these tests establish local state, persistence and absence of PCI traffic.
use super::*;

fn barcode_unit_vector() -> serde_json::Value {
    serde_json::from_str(include_str!(
        "../../../../testdata/vectors/cgate_barcode_unit_initialization.json"
    ))
    .unwrap()
}

fn without_unit(document: &str, address: &str) -> String {
    let parsed = roxmltree::Document::parse(document).unwrap();
    let unit = parsed
        .root_element()
        .children()
        .find(|node| {
            node.has_tag_name("Unit")
                && node
                    .children()
                    .any(|child| child.has_tag_name("Address") && child.text() == Some(address))
        })
        .unwrap();
    let mut remaining = document.to_string();
    remaining.replace_range(unit.range(), "");
    remaining
}

async fn barcode_unit_document(
    service: &Arc<Service>,
    client: &mut ClientState,
    target: &str,
    document: &str,
) -> Response {
    service
        .handle_document(
            client,
            &format!("[barcode-doc] DBSETXML {target}"),
            document,
        )
        .await
}

#[tokio::test]
async fn barcode_unit_add_initialize_preserves_irregular_owner_and_is_durable_without_pci() {
    let vector = barcode_unit_vector();
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    setup(&service, &mut client).await;
    let graph = graph(&service, &mut client).await;
    let existing_unit = "11111111-1111-4111-8111-111111111111";
    let owner = xml(&service, &mut client, "//NAMED/CustomA").await;
    let decorated = owner.replace("<Network>", "<Network xmlns:meta=\"urn:owned-barcode-test\">").replace(
        "</Network>",
        &format!("<!--keep owner comment--><meta:Payload key=\"untouched\">opaque</meta:Payload><Unit><OID>{existing_unit}</OID><Address>1</Address><TagName>Existing</TagName><UnitName>Existing</UnitName><UnitType>SYNTH</UnitType><FirmwareVersion>1.0.00</FirmwareVersion><PP Name=\"UnitName\" Value=\"PP label\"/><PP Name=\"StaticTextString0\" Value=\"Kitchen label\"/></Unit></Network>"),
    );
    assert_eq!(
        barcode_unit_document(&service, &mut client, "//NAMED/CustomA", &decorated)
            .await
            .status,
        301
    );
    // Complete the existing modeled SAVE/LOAD TagsDLT lifecycle before the
    // preservation baseline; the new Unit workflow must not change it.
    for command in [
        "PROJECT SAVE NAMED",
        "PROJECT CLOSE NAMED",
        "PROJECT LOAD NAMED",
        "PROJECT USE NAMED",
    ] {
        ok_command(&service, &mut client, command).await;
    }
    ok_command(
        &service,
        &mut client,
        &format!("DBSET !{}/Value oops", graph.level),
    )
    .await;
    let incomplete = created(
        &service,
        &mut client,
        "DBADDSAFE //NAMED/CustomA Unit 2 NEWUNIT",
    )
    .await;
    let before = xml(&service, &mut client, "//NAMED/CustomA").await;
    let before_oids = oid_set(&before);
    let neighbor = xml(&service, &mut client, "//NAMED/Neighbor").await;
    let old_unit = xml(&service, &mut client, &format!("!{existing_unit}")).await;
    let incomplete_xml = xml(&service, &mut client, &format!("!{incomplete}")).await;
    let application = xml(&service, &mut client, &format!("!{}", graph.app)).await;
    assert!(before.contains("keep owner comment"));
    assert!(before.contains("meta:Payload"));
    let oid = created(
        &service,
        &mut client,
        vector["safe_add"]["command"].as_str().unwrap(),
    )
    .await;
    assert!(!before_oids.contains(&oid));
    assert_eq!(
        scalar(&service, &mut client, &format!("!{oid}/UnitName")).await,
        "New Kitchen"
    );
    assert_eq!(
        without_unit(&xml(&service, &mut client, "//NAMED/CustomA").await, "8"),
        before
    );
    let document = vector["unit_xml"].as_str().unwrap().replace("%UNIT%", &oid);
    let response =
        barcode_unit_document(&service, &mut client, &format!("!{oid}"), &document).await;
    assert_eq!(response.final_text, format!("301 OID={oid}"));
    assert!(response.lines.is_empty());
    for row in vector["reads"].as_array().unwrap() {
        assert_eq!(
            scalar(
                &service,
                &mut client,
                &row["path"].as_str().unwrap().replace("%UNIT%", &oid)
            )
            .await,
            row["value"].as_str().unwrap().replace("%UNIT%", &oid)
        );
    }
    let after = xml(&service, &mut client, "//NAMED/CustomA").await;
    assert_eq!(without_unit(&after, "8"), before);
    assert!(!xml(&service, &mut client, &format!("!{oid}"))
        .await
        .contains("<PP"));
    assert_eq!(
        xml(&service, &mut client, &format!("!{existing_unit}")).await,
        old_unit
    );
    assert_eq!(
        xml(&service, &mut client, &format!("!{incomplete}")).await,
        incomplete_xml
    );
    assert_eq!(
        xml(&service, &mut client, &format!("!{}", graph.app)).await,
        application
    );
    assert_eq!(
        xml(&service, &mut client, "//NAMED/Neighbor").await,
        neighbor
    );
    assert_eq!(
        scalar(&service, &mut client, &format!("!{}/Value", graph.level)).await,
        "oops"
    );
    let mut expected_oids = before_oids;
    expected_oids.insert(oid.clone());
    assert_eq!(oid_set(&after), expected_oids);
    for command in [
        "PROJECT SAVE NAMED",
        "PROJECT CLOSE NAMED",
        "PROJECT LOAD NAMED",
        "PROJECT USE NAMED",
    ] {
        ok_command(&service, &mut client, command).await;
    }
    assert_eq!(xml(&service, &mut client, "//NAMED/CustomA").await, after);
    no_io(&mut remote).await;
    drop(service);
    let (pci_client, mut remote) = pci();
    let restarted = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    ok_command(&restarted, &mut client, "PROJECT USE NAMED").await;
    assert_eq!(xml(&restarted, &mut client, "//NAMED/CustomA").await, after);
    assert_eq!(
        xml(&restarted, &mut client, "//NAMED/Neighbor").await,
        neighbor
    );
    no_io(&mut remote).await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn barcode_unit_collisions_refuse_atomically_and_existing_units_can_readdress() {
    let vector = barcode_unit_vector();
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    setup(&service, &mut client).await;
    let graph = graph(&service, &mut client).await;
    let occupied = created(
        &service,
        &mut client,
        "DBADDSAFE //NAMED/CustomA Unit 1 NEWUNIT",
    )
    .await;
    let foreign = created(
        &service,
        &mut client,
        "DBADDSAFE //NAMED/Neighbor Unit 1 NEWUNIT",
    )
    .await;
    let oid = created(
        &service,
        &mut client,
        vector["safe_add"]["command"].as_str().unwrap(),
    )
    .await;
    let document = vector["unit_xml"].as_str().unwrap().replace("%UNIT%", &oid);
    assert_eq!(
        barcode_unit_document(&service, &mut client, &format!("!{oid}"), &document)
            .await
            .status,
        301
    );
    let before = xml(&service, &mut client, "//NAMED/CustomA").await;
    let neighbor = xml(&service, &mut client, "//NAMED/Neighbor").await;
    let state = std::fs::read(&path).unwrap();
    for row in vector["refusals"].as_array().unwrap() {
        let command = row["command"].as_str().unwrap().replace("%UNIT%", &oid);
        let response = run(&service, &mut client, &command).await;
        assert_eq!(
            u64::from(response.status),
            row["status"].as_u64().unwrap(),
            "{command}: {response:?}"
        );
        assert_eq!(std::fs::read(&path).unwrap(), state);
    }
    for (rejected, status) in [
        (
            document.replace("<Address>8</Address>", "<Address>1</Address>"),
            409,
        ),
        (document.replace(&oid, &foreign), 409),
        (document.replace(&oid, &graph.group), 409),
        (document.replace("<UnitName>NEWUNIT</UnitName>", ""), 446),
        (document.replace("<UnitType>SYNTH</UnitType>", ""), 400),
    ] {
        let response =
            barcode_unit_document(&service, &mut client, &format!("!{oid}"), &rejected).await;
        assert_eq!(response.status, status, "{rejected}: {response:?}");
        assert_eq!(xml(&service, &mut client, "//NAMED/CustomA").await, before);
        assert_eq!(
            xml(&service, &mut client, "//NAMED/Neighbor").await,
            neighbor
        );
        assert_eq!(std::fs::read(&path).unwrap(), state);
    }
    let moved_oid = "22222222-2222-4222-8222-222222222222";
    let moved = document
        .replace(&oid, moved_oid)
        .replace("<Address>8</Address>", "<Address>9</Address>");
    assert_eq!(
        barcode_unit_document(&service, &mut client, &format!("!{oid}"), &moved)
            .await
            .final_text,
        format!("301 OID={moved_oid}")
    );
    assert_eq!(
        scalar(&service, &mut client, &format!("!{moved_oid}/Address")).await,
        "9"
    );
    assert_eq!(
        run(&service, &mut client, &format!("DBGET !{oid}/OID"))
            .await
            .status,
        401
    );
    assert_eq!(
        run(&service, &mut client, "DBGET //NAMED/CustomA/p/8/OID")
            .await
            .status,
        401
    );
    assert_eq!(
        scalar(&service, &mut client, "//NAMED/CustomA/p/9/OID").await,
        moved_oid
    );
    assert_eq!(
        scalar(&service, &mut client, &format!("!{occupied}/TagName")).await,
        "NEWUNIT"
    );
    // Duplicate default names are allowed; only identity/address collisions
    // are refused. Removing a named target retires its OID lookup.
    let duplicate_name = created(
        &service,
        &mut client,
        "DBADDSAFE //NAMED/CustomA Unit 10 NEWUNIT",
    )
    .await;
    assert_ne!(duplicate_name, moved_oid);
    for row in vector["unit_address_aliases"].as_array().unwrap() {
        let alias_oid = created(&service, &mut client, row["command"].as_str().unwrap()).await;
        assert_eq!(
            scalar(&service, &mut client, &format!("!{alias_oid}/Address")).await,
            row["canonical_address"].as_str().unwrap()
        );
        if row["canonical_address"] == "13" {
            // Generic named Unit XML keeps its existing literal policy.
            // New Unit allocation still must detect this byte as occupied.
            let existing_alias = document
                .replace(&oid, &alias_oid)
                .replace("<Address>8</Address>", "<Address>013</Address>");
            assert_eq!(
                barcode_unit_document(
                    &service,
                    &mut client,
                    &format!("!{alias_oid}"),
                    &existing_alias
                )
                .await
                .status,
                301
            );
            assert_eq!(
                scalar(&service, &mut client, &format!("!{alias_oid}/Address")).await,
                "013"
            );
            let alias_before = xml(&service, &mut client, "//NAMED/CustomA").await;
            let alias_bytes = std::fs::read(&path).unwrap();
            assert_eq!(
                run(
                    &service,
                    &mut client,
                    "DBADDSAFE //NAMED/CustomA Unit 13 AliasOccupied"
                )
                .await
                .status,
                401
            );
            assert_eq!(
                xml(&service, &mut client, "//NAMED/CustomA").await,
                alias_before
            );
            assert_eq!(std::fs::read(&path).unwrap(), alias_bytes);
        }
    }
    assert_eq!(
        xml(&service, &mut client, "//NAMED/Neighbor").await,
        neighbor
    );
    no_io(&mut remote).await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn barcode_unit_unsafe_minimal_creation_and_auth_admission_preserve_state() {
    let vector = barcode_unit_vector();
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    setup(&service, &mut client).await;
    let oid = created(
        &service,
        &mut client,
        vector["unsafe_add"]["command"].as_str().unwrap(),
    )
    .await;
    let document = xml(&service, &mut client, &format!("!{oid}")).await;
    let parsed = roxmltree::Document::parse(&document).unwrap();
    for field in vector["unsafe_add"]["absent_fields"].as_array().unwrap() {
        assert!(!parsed
            .descendants()
            .any(|node| node.has_tag_name(field.as_str().unwrap())));
    }
    assert_eq!(
        oid_set(&document),
        std::collections::BTreeSet::from([oid.clone()])
    );
    service
        .set_auth_token_hash(crate::auth::sha256(b"barcode-test-token"))
        .unwrap();
    let bytes = std::fs::read(&path).unwrap();
    let mut denied = ClientState::default();
    assert_eq!(
        run(
            &service,
            &mut denied,
            "DBADDSAFE //NAMED/CustomA Unit 8 NEWUNIT"
        )
        .await
        .status,
        420
    );
    assert_eq!(
        barcode_unit_document(
            &service,
            &mut denied,
            &format!("!{oid}"),
            &vector["unit_xml"].as_str().unwrap().replace("%UNIT%", &oid)
        )
        .await
        .status,
        420
    );
    assert_eq!(std::fs::read(&path).unwrap(), bytes);
    no_io(&mut remote).await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn barcode_unit_named_document_retains_existing_named_markup_policy() {
    let vector = barcode_unit_vector();
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    setup(&service, &mut client).await;
    let oid = created(
        &service,
        &mut client,
        vector["safe_add"]["command"].as_str().unwrap(),
    )
    .await;
    let before = xml(&service, &mut client, "//NAMED/CustomA").await;
    // Independent named XML already retains opaque markup. Keep that
    // established policy separate from the numeric Unit mapper, which
    // normalizes submitted Unit XML to its scalar/PP schema.
    let document = vector["unit_xml"].as_str().unwrap().replace("%UNIT%", &oid)
        .replace("<Unit>", "<Unit xmlns:meta=\"urn:owned-unit-policy\">")
        .replace("</Unit>", "<!--named markup--><Foo>unknown plain</Foo><meta:Payload key=\"opaque\">retained</meta:Payload><meta:UnitType>opaque type</meta:UnitType></Unit>");
    assert_eq!(
        barcode_unit_document(&service, &mut client, &format!("!{oid}"), &document)
            .await
            .status,
        301
    );
    let unit = xml(&service, &mut client, &format!("!{oid}")).await;
    for retained in [
        "named markup",
        "<Foo>unknown plain</Foo>",
        "meta:Payload",
        "meta:UnitType",
    ] {
        assert!(unit.contains(retained), "{retained}: {unit}");
    }
    assert_eq!(
        scalar(&service, &mut client, &format!("!{oid}/UnitType")).await,
        "SYNTH"
    );
    assert_eq!(
        without_unit(&xml(&service, &mut client, "//NAMED/CustomA").await, "8"),
        without_unit(&before, "8")
    );
    no_io(&mut remote).await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn barcode_unit_numeric_target_initialization_preserves_raw_siblings_and_physical_inventory()
{
    let vector = barcode_unit_vector();
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    let physical = service.model.lock().await.projects["HARNESS"].networks[&254]
        .physical
        .clone();
    for command in ["NET LOAD DB", "NET SAVE DB"] {
        ok_command(&service, &mut client, command).await;
    }
    let level = created(
        &service,
        &mut client,
        "DBADDSAFE //HARNESS/254/56/1 Level 7 Raw",
    )
    .await;
    ok_command(
        &service,
        &mut client,
        &format!("DBSETSAFE !{level}/Value oops"),
    )
    .await;
    let incomplete = created(
        &service,
        &mut client,
        "DBADDSAFE //HARNESS/254 Unit 2 NEWUNIT",
    )
    .await;
    let before = xml(&service, &mut client, "//HARNESS/254").await;
    let old_unit = xml(&service, &mut client, "//HARNESS/254/p/5").await;
    let oid = created(
        &service,
        &mut client,
        "DBADDSAFE //HARNESS/254 Unit 8 New Kitchen",
    )
    .await;
    let document = vector["unit_xml"].as_str().unwrap().replace("%UNIT%", &oid);
    assert_eq!(
        barcode_unit_document(&service, &mut client, &format!("!{oid}"), &document)
            .await
            .final_text,
        format!("301 OID={oid}")
    );
    let after = xml(&service, &mut client, "//HARNESS/254").await;
    assert_eq!(without_unit(&after, "8"), before);
    assert_eq!(
        xml(&service, &mut client, "//HARNESS/254/p/5").await,
        old_unit
    );
    assert_eq!(
        scalar(&service, &mut client, &format!("!{level}/Value")).await,
        "oops"
    );
    assert_eq!(
        scalar(&service, &mut client, &format!("!{incomplete}/UnitName")).await,
        "NEWUNIT"
    );
    assert_eq!(
        service.model.lock().await.projects["HARNESS"].networks[&254].physical,
        physical
    );
    no_io(&mut remote).await;
    drop(service);
    let (pci_client, mut remote) = pci();
    let restarted = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    assert_eq!(xml(&restarted, &mut client, "//HARNESS/254").await, after);
    assert_eq!(
        restarted.model.lock().await.projects["HARNESS"].networks[&254].physical,
        physical
    );
    no_io(&mut remote).await;
    std::fs::remove_file(path).unwrap();
}

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

// Remove only one empty, attribute-free, unnamespaced TagsDLT
// direct child per Level. Every other XML byte/order remains compared exactly.
fn associated_without_empty_level_tags(document: &str) -> String {
    let parsed = roxmltree::Document::parse(document).unwrap();
    let mut ranges = Vec::new();
    for node in parsed
        .descendants()
        .filter(|node| node.has_tag_name("TagsDLT"))
    {
        let Some(parent) = node.parent().filter(|parent| parent.has_tag_name("Level")) else {
            continue;
        };
        if node.tag_name().namespace().is_none()
            && parent.tag_name().namespace().is_none()
            && node.attributes().len() == 0
            && node
                .children()
                .all(|child| child.is_text() && child.text().unwrap_or_default().trim().is_empty())
        {
            assert_eq!(
                parent
                    .children()
                    .filter(|child| child.has_tag_name("TagsDLT"))
                    .count(),
                1
            );
            ranges.push(node.range());
        }
    }
    let mut result = document.to_string();
    for range in ranges.into_iter().rev() {
        result.replace_range(range, "");
    }
    result
}

fn associated_level_xml_value(document: &str) -> Option<String> {
    let parsed = roxmltree::Document::parse(document).unwrap();
    let level = parsed.root_element();
    assert!(level.has_tag_name("Level"));
    level
        .attribute("Value")
        .or_else(|| {
            level
                .children()
                .find(|node| node.has_tag_name("Value"))
                .and_then(|node| node.text())
        })
        .map(str::to_string)
}

// Keep the configured transport project separate from the closed numeric database graph.
async fn associated_level_setup(service: &Arc<Service>, client: &mut ClientState) -> String {
    for command in [
        "PROJECT NEW ASSOC",
        "PROJECT USE ASSOC",
        "DBCREATENET 11 Eleven Cni 127.0.0.1:1",
        "NET LOAD DB",
        "NET SAVE DB",
    ] {
        ok_command(service, client, command).await;
    }
    created(
        service,
        client,
        "DBADDSAFE //ASSOC/11 Application 56 Lighting",
    )
    .await;
    created(service, client, "DBADDSAFE //ASSOC/11/56 Group 1 Main").await;
    let group = scalar(service, client, "//ASSOC/11/56/1/OID").await;
    ok_command(service, client, "DBRENAMENETSAFE 11 Renamed").await;
    {
        let model = service.model.lock().await;
        assert_eq!(
            model.projects["ASSOC"].tag_networks["Renamed"].database_network,
            Some(11)
        );
        assert!(model.projects["ASSOC"].networks.contains_key(&11));
    }
    group
}

#[tokio::test]
async fn numeric_level_oid_tag_name_updates_group_and_netvar_and_survives_reload() {
    let vector: serde_json::Value = serde_json::from_str(include_str!(
        "../../../../testdata/vectors/cgate_level_oid_tag_name.json"
    ))
    .unwrap();
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    for command in [
        "PROJECT NEW LVTAGS",
        "PROJECT USE LVTAGS",
        "DBCREATENET 11 Eleven Cni 127.0.0.1:1",
    ] {
        ok_command(&service, &mut client, command).await;
    }
    let mut levels = Vec::new();
    for parent_case in vector["parents"].as_array().unwrap() {
        let application = parent_case["application"].as_u64().unwrap();
        let application_name = parent_case["application_name"].as_str().unwrap();
        let element = parent_case["element"].as_str().unwrap();
        created(
            &service,
            &mut client,
            &format!("DBADDSAFE //LVTAGS/11 Application {application} {application_name}"),
        )
        .await;
        created(
            &service,
            &mut client,
            &format!("DBADDSAFE //LVTAGS/11/{application} {element} 12 Remote"),
        )
        .await;
        let parent = format!("//LVTAGS/11/{application}/12");
        let oid = created(
            &service,
            &mut client,
            &format!("DBADDSAFE {parent} Level 7 Level 7"),
        )
        .await;
        ok_command(&service, &mut client, &format!("DBSETSAFE !{oid}/Value 31")).await;
        levels.push((oid, element));
    }
    for rename in vector["renames"].as_array().unwrap() {
        let name = rename["TagName"].as_str().unwrap();
        for (oid, element) in &levels {
            let response = run(
                &service,
                &mut client,
                &rename["command"].as_str().unwrap().replace("%OID%", oid),
            )
            .await;
            assert_eq!(response.status, 200);
            assert!(response.lines.is_empty());
            assert_eq!(response.final_text, rename["final"].as_str().unwrap());
            let response = run(&service, &mut client, &format!("DBGET !{oid}/TagName")).await;
            assert_eq!(response.status, 342);
            assert!(response.lines.is_empty());
            assert_eq!(
                response.final_text,
                rename["read_final"].as_str().unwrap().replace("%OID%", oid)
            );
            // The owning Network projection retains the actual Group/NetVar
            // kind; legacy direct group-slice wrappers are a separate surface.
            let document = xml(&service, &mut client, "//LVTAGS/11").await;
            let parsed = roxmltree::Document::parse(&document).unwrap();
            let level = parsed
                .descendants()
                .find(|node| {
                    node.has_tag_name("Level")
                        && node.children().any(|child| {
                            child.has_tag_name("OID") && child.text() == Some(oid.as_str())
                        })
                })
                .unwrap();
            assert!(
                level.parent_element().unwrap().has_tag_name(*element),
                "{document}"
            );
            assert_eq!(level.attribute("Value"), vector["level"]["Value"].as_str());
            for (field, expected) in [
                ("OID", oid.as_str()),
                ("Address", vector["level"]["Address"].as_str().unwrap()),
                ("TagName", name),
            ] {
                assert_eq!(
                    level
                        .children()
                        .find(|node| node.has_tag_name(field))
                        .unwrap()
                        .text(),
                    Some(expected)
                );
            }
        }
        for command in [
            "PROJECT SAVE LVTAGS",
            "PROJECT CLOSE LVTAGS",
            "PROJECT LOAD LVTAGS",
            "PROJECT USE LVTAGS",
        ] {
            ok_command(&service, &mut client, command).await;
        }
        for (oid, element) in &levels {
            assert_eq!(
                scalar(&service, &mut client, &format!("!{oid}/TagName")).await,
                name
            );
            let document = xml(&service, &mut client, "//LVTAGS/11").await;
            let parsed = roxmltree::Document::parse(&document).unwrap();
            let level = parsed
                .descendants()
                .find(|node| {
                    node.has_tag_name("Level")
                        && node.children().any(|child| {
                            child.has_tag_name("OID") && child.text() == Some(oid.as_str())
                        })
                })
                .unwrap();
            assert!(
                level.parent_element().unwrap().has_tag_name(*element),
                "{document}"
            );
            assert_eq!(
                level
                    .children()
                    .find(|node| node.has_tag_name("TagName"))
                    .unwrap()
                    .text(),
                Some(name)
            );
            assert_eq!(
                scalar(&service, &mut client, &format!("!{oid}/Value")).await,
                "31"
            );
        }
    }
    let final_document = xml(&service, &mut client, "//LVTAGS/11").await;
    no_io(&mut remote).await;
    drop(service);
    let (pci_client, mut remote) = pci();
    let restarted = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    ok_command(&restarted, &mut client, "PROJECT USE LVTAGS").await;
    assert_eq!(
        xml(&restarted, &mut client, "//LVTAGS/11").await,
        final_document
    );
    for (oid, _) in &levels {
        assert_eq!(
            scalar(&restarted, &mut client, &format!("!{oid}/TagName")).await,
            "Sched Enable Zone 4 & 5"
        );
        assert_eq!(
            scalar(&restarted, &mut client, &format!("!{oid}/Value")).await,
            "31"
        );
    }
    no_io(&mut remote).await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn renamed_associated_level_add_uses_one_owner_for_path_bare_and_group_oid() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    let group = associated_level_setup(&service, &mut client).await;
    let configured =
        serde_json::to_value(&service.model.lock().await.projects["HARNESS"].networks[&254])
            .unwrap();
    for (parent, address) in [
        ("//ASSOC/Renamed/56/1".to_string(), 7),
        ("Renamed/56/1".to_string(), 8),
        (format!("!{group}"), 9),
    ] {
        let oid = created(
            &service,
            &mut client,
            &format!("DBADDSAFE {parent} Level {address} New"),
        )
        .await;
        assert_eq!(
            scalar(&service, &mut client, &format!("!{oid}/OID")).await,
            oid
        );
        // Existing numeric typed owner represents NULL as terminal342/null.
        assert_eq!(
            scalar(&service, &mut client, &format!("!{oid}/Value")).await,
            "null"
        );
        ok_command(
            &service,
            &mut client,
            &format!("DBSETSAFE !{oid}/Value {address}"),
        )
        .await;
        assert_eq!(
            scalar(&service, &mut client, &format!("!{oid}/Value")).await,
            address.to_string()
        );
        let model = service.model.lock().await;
        assert_eq!(model.level(&oid).unwrap().parent, "//ASSOC/11/56/1");
        assert_eq!(
            model.projects["ASSOC"]
                .tag_networks
                .values()
                .filter(|record| record.database_network == Some(11))
                .count(),
            1
        );
    }
    let before = xml(&service, &mut client, "//ASSOC/Renamed").await;
    assert_eq!(
        roxmltree::Document::parse(&before)
            .unwrap()
            .descendants()
            .filter(|node| node.has_tag_name("Level"))
            .count(),
        3
    );
    for command in [
        "PROJECT SAVE ASSOC",
        "PROJECT CLOSE ASSOC",
        "PROJECT LOAD ASSOC",
        "PROJECT USE ASSOC",
    ] {
        ok_command(&service, &mut client, command).await;
    }
    let reloaded = xml(&service, &mut client, "//ASSOC/Renamed").await;
    // Only the already captured empty Level TagsDLT additions are allowed.
    assert_eq!(
        associated_without_empty_level_tags(&reloaded),
        associated_without_empty_level_tags(&before)
    );
    assert_eq!(oid_set(&reloaded), oid_set(&before));
    assert_eq!(
        serde_json::to_value(&service.model.lock().await.projects["HARNESS"].networks[&254])
            .unwrap(),
        configured
    );
    let (new_pci, mut new_remote) = pci();
    let restarted = Service::new(&fixture(), None, path.clone(), new_pci, None).unwrap();
    let mut restarted_client = ClientState::default();
    ok_command(&restarted, &mut restarted_client, "PROJECT USE ASSOC").await;
    assert_eq!(
        xml(&restarted, &mut restarted_client, "//ASSOC/Renamed").await,
        reloaded
    );
    no_io(&mut remote).await;
    no_io(&mut new_remote).await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn renamed_associated_level_copy_retains_value_until_explicit_caller_initialization() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    let group = associated_level_setup(&service, &mut client).await;
    let source = created(
        &service,
        &mut client,
        &format!("DBADDSAFE !{group} Level 7 Source"),
    )
    .await;
    ok_command(
        &service,
        &mut client,
        &format!("DBSETSAFE !{source}/Value 77"),
    )
    .await;
    let source_xml = xml(&service, &mut client, &format!("!{source}")).await;
    for (source_path, parent, address) in [
        (format!("!{source}"), "//ASSOC/Renamed/56/1".to_string(), 8),
        ("//ASSOC/Renamed/56/1/7".to_string(), format!("!{group}"), 9),
    ] {
        let copy = created(
            &service,
            &mut client,
            &format!("DBCOPYSAFE {source_path} {parent} {address} Copy"),
        )
        .await;
        assert_ne!(copy, source);
        assert_eq!(
            scalar(&service, &mut client, &format!("!{copy}/Value")).await,
            "77"
        );
        ok_command(
            &service,
            &mut client,
            &format!("DBSETSAFE !{copy}/Value {address}"),
        )
        .await;
        assert_eq!(
            scalar(&service, &mut client, &format!("!{copy}/Value")).await,
            address.to_string()
        );
        assert_eq!(
            xml(&service, &mut client, &format!("!{source}")).await,
            source_xml
        );
    }
    // A later unsafe copy also retains the authoritative typed value, while
    // its identity fields are incomplete and completed by explicit commands.
    let pending = created(&service, &mut client, &format!("DBCOPY !{source} !{group}")).await;
    assert_eq!(
        scalar(&service, &mut client, &format!("!{pending}/Value")).await,
        "77"
    );
    ok_command(
        &service,
        &mut client,
        &format!("DBSET !{pending}/TagName UnsafeCopy"),
    )
    .await;
    ok_command(
        &service,
        &mut client,
        &format!("DBSET !{pending}/Address 10"),
    )
    .await;
    assert_eq!(
        scalar(&service, &mut client, &format!("!{pending}/Value")).await,
        "77"
    );
    let completed = xml(&service, &mut client, "//ASSOC/Renamed").await;
    for command in [
        "PROJECT SAVE ASSOC",
        "PROJECT CLOSE ASSOC",
        "PROJECT LOAD ASSOC",
        "PROJECT USE ASSOC",
    ] {
        ok_command(&service, &mut client, command).await;
    }
    let reloaded = xml(&service, &mut client, "//ASSOC/Renamed").await;
    assert_eq!(
        associated_without_empty_level_tags(&reloaded),
        associated_without_empty_level_tags(&completed)
    );
    let (new_pci, mut new_remote) = pci();
    let restarted = Service::new(&fixture(), None, path.clone(), new_pci, None).unwrap();
    let mut restarted_client = ClientState::default();
    ok_command(&restarted, &mut restarted_client, "PROJECT USE ASSOC").await;
    assert_eq!(
        xml(&restarted, &mut restarted_client, "//ASSOC/Renamed").await,
        reloaded
    );
    no_io(&mut remote).await;
    no_io(&mut new_remote).await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn renamed_associated_level_invalid_parent_suffix_and_collision_are_atomic() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    let group = associated_level_setup(&service, &mut client).await;
    let level = created(
        &service,
        &mut client,
        &format!("DBADDSAFE !{group} Level 7 Source"),
    )
    .await;
    ok_command(
        &service,
        &mut client,
        &format!("DBSETSAFE !{level}/Value 7"),
    )
    .await;
    let before = Database::from_server(&*service.model.lock().await);
    let bytes = std::fs::read(&path).unwrap();
    for command in [
        format!("DBADDSAFE !{group}/Address Level 8 Bad"),
        format!("DBADD !{group}/anything Level"),
        format!("DBADDSAFE !{level} Level 8 Bad"),
        format!("DBADDSAFE !{group} Level 7 Duplicate"),
        format!("DBCOPYSAFE !{level}/Value !{group} 8 Bad"),
        format!("DBCOPYSAFE !{level} !{group}/Address 8 Bad"),
        format!("DBCOPYSAFE !{level} !missing-group 8 Bad"),
        "DBADDSAFE //ASSOC/Renamed/56/99 Level 8 Missing".to_string(),
        "DBADDSAFE //ASSOC/Renamed/56/1/TagName Level 8 Scalar".to_string(),
    ] {
        let response = run(&service, &mut client, &command).await;
        assert_eq!(response.status, 401, "{command}: {response:?}");
        assert!(
            Database::from_server(&*service.model.lock().await) == before,
            "{command}"
        );
        assert_eq!(std::fs::read(&path).unwrap(), bytes, "{command}");
    }
    no_io(&mut remote).await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn renamed_associated_level_pending_completion_and_repository_failure_preserve_owner() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    let group = associated_level_setup(&service, &mut client).await;
    for (address, value_first) in [(7, true), (8, false)] {
        let oid = created(&service, &mut client, &format!("DBADD !{group} Level")).await;
        let mut commands = vec![
            format!("DBSET !{oid}/TagName Pending{address}"),
            format!("DBSET !{oid}/Address {address}"),
        ];
        if value_first {
            commands.insert(0, format!("DBSET !{oid}/Value 77"));
        } else {
            commands.push(format!("DBSET !{oid}/Value 77"));
        }
        for command in commands {
            ok_command(&service, &mut client, &command).await;
        }
        assert_eq!(
            scalar(&service, &mut client, &format!("!{oid}/Value")).await,
            "77"
        );
    }
    let pending = created(&service, &mut client, "DBADD //ASSOC/Renamed/56/1 Level").await;
    let before = Database::from_server(&*service.model.lock().await);
    let bytes = std::fs::read(&path).unwrap();
    std::fs::remove_file(&path).unwrap();
    std::fs::create_dir(&path).unwrap();
    for command in [
        format!("DBADDSAFE !{group} Level 9 Safe"),
        "DBADD //ASSOC/Renamed/56/1 Level".to_string(),
        "DBCOPYSAFE //ASSOC/Renamed/56/1/7 //ASSOC/Renamed/56/1 9 Copy".to_string(),
        format!("DBSET !{pending}/TagName Pending"),
    ] {
        assert_eq!(
            run(&service, &mut client, &command).await.final_text,
            "500 Database commit failed; change rolled back",
            "{command}"
        );
        assert!(
            Database::from_server(&*service.model.lock().await) == before,
            "{command}"
        );
        assert_eq!(client.current.as_deref(), Some("ASSOC"));
        assert!(path.is_dir());
    }
    std::fs::remove_dir(&path).unwrap();
    std::fs::write(&path, bytes).unwrap();
    no_io(&mut remote).await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn renamed_associated_addressed_pending_level_value_mirror_matches_scalar_xml_and_both_copies(
) {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    let group = associated_level_setup(&service, &mut client).await;
    let source = created(&service, &mut client, &format!("DBADD !{group} Level")).await;
    for command in [
        format!("DBSET !{source}/Value 7"),
        format!("DBSET !{source}/TagName ImportedShape"),
        format!("DBSET !{source}/Address 7"),
    ] {
        ok_command(&service, &mut client, &command).await;
    }
    // Also import this complete Level through the document boundary; the
    // mirror must then agree after a later scalar update, just as a completed
    // pending Level does. No external incomplete XML is admitted.
    let complete = xml(&service, &mut client, &format!("!{source}")).await;
    assert_eq!(
        service
            .handle_document(
                &mut client,
                &format!("[named-db] DBSETXML !{source}"),
                &complete
            )
            .await
            .status,
        301
    );
    for literal in ["77", "077", "+77"] {
        ok_command(
            &service,
            &mut client,
            &format!("DBSETSAFE !{source}/Value {literal}"),
        )
        .await;
        assert_eq!(
            scalar(&service, &mut client, &format!("!{source}/Value")).await,
            "77"
        );
        assert_eq!(
            associated_level_xml_value(&xml(&service, &mut client, &format!("!{source}")).await)
                .as_deref(),
            Some("77")
        );
    }
    let before = xml(&service, &mut client, &format!("!{source}")).await;
    assert_eq!(associated_level_xml_value(&before).as_deref(), Some("77"));
    {
        let model = service.model.lock().await;
        let pending = model.pending_object("ASSOC", &source).unwrap();
        assert_eq!(pending.path.as_deref(), Some("//ASSOC/11/56/1/7"));
        assert_eq!(pending.fields.get("Value").map(String::as_str), Some("77"));
        assert_eq!(model.level(&source).unwrap().value, Some(77));
    }
    let safe = created(
        &service,
        &mut client,
        &format!("DBCOPYSAFE !{source} !{group} 8 Safe"),
    )
    .await;
    let unsafe_copy = created(&service, &mut client, &format!("DBCOPY !{source} !{group}")).await;
    for oid in [&safe, &unsafe_copy] {
        assert_ne!(oid, &source);
        assert_eq!(
            scalar(&service, &mut client, &format!("!{oid}/Value")).await,
            "77"
        );
    }
    assert_eq!(
        xml(&service, &mut client, &format!("!{source}")).await,
        before
    );
    no_io(&mut remote).await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn renamed_associated_level_unit_oid_and_foreign_selection_never_choose_pending_owner() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    let group = associated_level_setup(&service, &mut client).await;
    {
        // Committed synthetic Unit copied only into this local database
        // fixture; physical inventory and interface binding stay unchanged.
        let mut model = service.model.lock().await;
        let unit = model.projects["HARNESS"].networks[&254].units[&5].clone();
        model
            .projects
            .get_mut("ASSOC")
            .unwrap()
            .networks
            .get_mut(&11)
            .unwrap()
            .units
            .insert(5, unit);
    }
    let unit_oid = service.model.lock().await.projects["ASSOC"].networks[&11].units[&5]
        .oid
        .clone();
    let before = Database::from_server(&*service.model.lock().await);
    let bytes = std::fs::read(&path).unwrap();
    for command in [
        format!("DBADDSAFE !{unit_oid} Level 8 Bad"),
        format!("DBADD !{unit_oid} Level"),
        "DBADDSAFE !missing-group Level 8 Bad".to_string(),
    ] {
        let response = run(&service, &mut client, &command).await;
        assert!(
            matches!(response.status, 401 | 404),
            "{command}: {response:?}"
        );
        assert!(Database::from_server(&*service.model.lock().await) == before);
        assert_eq!(std::fs::read(&path).unwrap(), bytes);
    }
    ok_command(&service, &mut client, "PROJECT NEW OTHER").await;
    ok_command(&service, &mut client, "PROJECT USE OTHER").await;
    let other_before = Database::from_server(&*service.model.lock().await);
    let other_bytes = std::fs::read(&path).unwrap();
    for command in [
        format!("DBADDSAFE !{group} Level 8 Foreign"),
        "DBADDSAFE //ASSOC/Renamed/56/1 Level 8 Foreign".to_string(),
    ] {
        let response = run(&service, &mut client, &command).await;
        assert!(
            matches!(response.status, 401 | 404),
            "{command}: {response:?}"
        );
        assert!(Database::from_server(&*service.model.lock().await) == other_before);
        assert_eq!(std::fs::read(&path).unwrap(), other_bytes);
        assert_eq!(client.current.as_deref(), Some("OTHER"));
    }
    no_io(&mut remote).await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn renamed_associated_level_copy_refuses_retained_payload_and_stale_value_mirror_atomically()
{
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    let group = associated_level_setup(&service, &mut client).await;
    let source = created(&service, &mut client, &format!("DBADD !{group} Level")).await;
    for command in [
        format!("DBSET !{source}/Value 7"),
        format!("DBSET !{source}/TagName Source"),
        format!("DBSET !{source}/Address 7"),
    ] {
        ok_command(&service, &mut client, &command).await;
    }
    for decorated in [true, false] {
        // Controlled local regression fixtures model persisted decorations
        // and a pre-fix stale mirror; neither is new original contract credit.
        {
            let mut model = service.model.lock().await;
            let key = Server::unit_document_key("ASSOC", &source);
            if decorated {
                model
                    .db_xml_extras
                    .entry(key)
                    .or_default()
                    .children
                    .push("<TagsDLT><TagDLT><OID>55555555-5555-4555-8555-000000000005</OID><LanguageID>1</LanguageID><FlavourID>1</FlavourID><TagType>TEXT</TagType><TagValue>Retained</TagValue></TagDLT></TagsDLT>".to_string());
            } else {
                model.db_xml_extras.remove(&key);
                let pending_key = model.pending_object_key("ASSOC", &source).unwrap();
                model
                    .db_pending
                    .get_mut(&pending_key)
                    .unwrap()
                    .fields
                    .insert("Value".to_string(), "3".to_string());
            }
        }
        let before = Database::from_server(&*service.model.lock().await);
        let bytes = std::fs::read(&path).unwrap();
        for command in [
            format!("DBCOPYSAFE !{source} !{group} 8 Copy"),
            format!("DBCOPY //ASSOC/Renamed/56/1/7 !{group}"),
        ] {
            assert_eq!(
                run(&service, &mut client, &command).await.status,
                408,
                "{command}"
            );
            assert!(Database::from_server(&*service.model.lock().await) == before);
            assert_eq!(std::fs::read(&path).unwrap(), bytes);
        }
    }
    no_io(&mut remote).await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn renamed_associated_level_under_existing_netvar_uses_typed_parent_for_path_and_oid() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    for command in [
        "PROJECT NEW ASSOC",
        "PROJECT USE ASSOC",
        "DBCREATENET 11 Eleven Cni 127.0.0.1:1",
        "NET LOAD DB",
        "NET SAVE DB",
    ] {
        ok_command(&service, &mut client, command).await;
    }
    created(
        &service,
        &mut client,
        "DBADDSAFE //ASSOC/11 Application 56 Lighting",
    )
    .await;
    // Existing constructor: this does not add a new NetVar creation
    // route or generalize it to another parent kind.
    let variable = created(
        &service,
        &mut client,
        "DBADDSAFE //ASSOC/11/56 NetVar 4 Variable",
    )
    .await;
    let prior_child = created(
        &service,
        &mut client,
        &format!("DBADDSAFE !{variable} Level 6 Prior"),
    )
    .await;
    ok_command(
        &service,
        &mut client,
        &format!("DBSETSAFE !{prior_child}/Value 33"),
    )
    .await;
    ok_command(&service, &mut client, "DBRENAMENETSAFE 11 Renamed").await;
    assert_eq!(
        scalar(&service, &mut client, &format!("!{prior_child}/Value")).await,
        "33"
    );
    assert_eq!(
        service
            .model
            .lock()
            .await
            .level(&prior_child)
            .unwrap()
            .parent,
        "//ASSOC/11/56/4"
    );
    for (parent, address) in [
        (format!("!{variable}"), 7),
        ("//ASSOC/Renamed/56/4".to_string(), 8),
    ] {
        let level = created(
            &service,
            &mut client,
            &format!("DBADDSAFE {parent} Level {address} New"),
        )
        .await;
        ok_command(
            &service,
            &mut client,
            &format!("DBSETSAFE !{level}/Value {address}"),
        )
        .await;
        let model = service.model.lock().await;
        assert_eq!(model.level(&level).unwrap().parent, "//ASSOC/11/56/4");
        assert!(model.level(&variable).unwrap().netvar);
    }
    assert_eq!(
        scalar(&service, &mut client, &format!("!{variable}/Value")).await,
        "null"
    );
    no_io(&mut remote).await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn independent_qualified_level_add_preserves_other_and_fresh_unselected_sessions() {
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
    created(
        &service,
        &mut client,
        &format!("DBADDSAFE !{app} Group 1 Main"),
    )
    .await;
    let configured =
        serde_json::to_value(&service.model.lock().await.projects["HARNESS"].networks[&254])
            .unwrap();
    ok_command(&service, &mut client, "PROJECT NEW OTHER").await;
    ok_command(&service, &mut client, "PROJECT USE OTHER").await;
    let other = xml(&service, &mut client, "//OTHER").await;
    let first = created(
        &service,
        &mut client,
        "DBADDSAFE //NAMED/CustomA/56/1 Level 7 OtherSelected",
    )
    .await;
    assert_eq!(client.current.as_deref(), Some("OTHER"));
    assert_eq!(xml(&service, &mut client, "//OTHER").await, other);
    let mut fresh = ClientState::default();
    // No configured startup project.default; this is a fresh embedded session.
    assert!(service.startup_default_for_loaded_project().await.is_none());
    let second = created(
        &service,
        &mut fresh,
        "DBADDSAFE //NAMED/CustomA/56/1 Level 8 Unselected",
    )
    .await;
    // Service dispatch retains its existing configured-project fallback.
    assert_eq!(fresh.current.as_deref(), Some("HARNESS"));
    let mut unselected_model = service.model.lock().await.clone();
    unselected_model.set_current_project(None);
    assert_eq!(
        unselected_model
            .handle("[plain] DBADDSAFE //NAMED/CustomA/56/1 Level 9 PlainUnselected")
            .status,
        301
    );
    assert!(unselected_model.current_project().is_none());
    assert_ne!(first, second);
    assert_eq!(
        serde_json::to_value(&service.model.lock().await.projects["HARNESS"].networks[&254])
            .unwrap(),
        configured
    );
    ok_command(&service, &mut client, "PROJECT USE NAMED").await;
    for (oid, value) in [(&first, 7), (&second, 8)] {
        ok_command(
            &service,
            &mut client,
            &format!("DBSETSAFE !{oid}/Value {value}"),
        )
        .await;
    }
    associated_level_setup(&service, &mut client).await;
    // Controlled representation fixture: neither lexical Address is a map
    // key. Both root-order variants must use the actual lexical winner.
    {
        let mut model = service.model.lock().await;
        let mut sibling = model.projects["NAMED"].tag_networks["CustomA"].clone();
        sibling
            .root
            .fields
            .iter_mut()
            .find(|(field, _)| field == "Address")
            .unwrap()
            .1 = "Renamed".to_string();
        sibling.created_seq = 20;
        assert!(sibling.database_network.is_none());
        let project = model.projects.get_mut("ASSOC").unwrap();
        let mut associated = project.tag_networks.remove("Renamed").unwrap();
        associated.created_seq = 10;
        project
            .tag_networks
            .insert("!controlled-associated#1".to_string(), associated);
        project
            .tag_networks
            .insert("!controlled-independent#1".to_string(), sibling);
        assert!(!project.tag_networks.contains_key("Renamed"));
    }
    ok_command(&service, &mut client, "PROJECT USE OTHER").await;
    let before = Database::from_server(&*service.model.lock().await);
    let bytes = std::fs::read(&path).unwrap();
    let mut no_selection = ClientState::default();
    for session in [&mut client, &mut no_selection] {
        assert_eq!(
            run(
                &service,
                session,
                "DBADDSAFE //ASSOC/Renamed/56/1 Level 9 RefusedAssociated"
            )
            .await
            .status,
            401
        );
        assert!(Database::from_server(&*service.model.lock().await) == before);
        assert_eq!(std::fs::read(&path).unwrap(), bytes);
    }
    assert_eq!(client.current.as_deref(), Some("OTHER"));
    assert!(no_selection.current.is_none());
    let mut unselected_model = service.model.lock().await.clone();
    unselected_model.set_current_project(None);
    let unselected_before = Database::from_server(&unselected_model);
    assert_eq!(
        unselected_model
            .handle("[plain] DBADDSAFE //ASSOC/Renamed/56/1 Level 9 RefusedAssociated")
            .status,
        401
    );
    assert!(unselected_model.current_project().is_none());
    assert!(Database::from_server(&unselected_model) == unselected_before);
    {
        let mut model = service.model.lock().await;
        let project = model.projects.get_mut("ASSOC").unwrap();
        project
            .tag_networks
            .get_mut("!controlled-associated#1")
            .unwrap()
            .created_seq = 20;
        project
            .tag_networks
            .get_mut("!controlled-independent#1")
            .unwrap()
            .created_seq = 10;
    }
    let physical_owner = service.model.lock().await.projects["ASSOC"].networks[&11].clone();
    created(
        &service,
        &mut client,
        "DBADDSAFE //ASSOC/Renamed/56/1 Level 9 IndependentWinner",
    )
    .await;
    created(
        &service,
        &mut no_selection,
        "DBADDSAFE //ASSOC/Renamed/56/1 Level 10 IndependentWinnerUnselected",
    )
    .await;
    assert_eq!(client.current.as_deref(), Some("OTHER"));
    assert_eq!(no_selection.current.as_deref(), Some("HARNESS"));
    let mut unselected_model = service.model.lock().await.clone();
    unselected_model.set_current_project(None);
    assert_eq!(
        unselected_model
            .handle("[plain] DBADDSAFE //ASSOC/Renamed/56/1 Level 11 PlainIndependentWinner")
            .status,
        301
    );
    assert!(unselected_model.current_project().is_none());
    // Compare the stable numeric owner's complete serialized state rather
    // than only its tag XML; independent winner ADD must not mutate it.
    assert_eq!(
        serde_json::to_value(&service.model.lock().await.projects["ASSOC"].networks[&11]).unwrap(),
        serde_json::to_value(&physical_owner).unwrap()
    );
    assert_eq!(
        serde_json::to_value(&service.model.lock().await.projects["HARNESS"].networks[&254])
            .unwrap(),
        configured
    );
    assert_eq!(xml(&service, &mut client, "//OTHER").await, other);
    no_io(&mut remote).await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn renamed_associated_null_source_copy_stays_null_until_explicit_initialization() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    let group = associated_level_setup(&service, &mut client).await;
    let source = created(
        &service,
        &mut client,
        &format!("DBADDSAFE !{group} Level 7 NullSource"),
    )
    .await;
    let copy = created(
        &service,
        &mut client,
        &format!("DBCOPYSAFE !{source} !{group} 8 NullCopy"),
    )
    .await;
    assert_ne!(copy, source);
    for oid in [&source, &copy] {
        // Existing numeric typed owner represents NULL as terminal342/null.
        assert_eq!(
            scalar(&service, &mut client, &format!("!{oid}/Value")).await,
            "null"
        );
        assert!(service
            .model
            .lock()
            .await
            .level(oid)
            .unwrap()
            .value
            .is_none());
    }
    let before = Database::from_server(&*service.model.lock().await);
    let bytes = std::fs::read(&path).unwrap();
    let mut fresh = ClientState::default();
    assert!(service.startup_default_for_loaded_project().await.is_none());
    assert_eq!(
        run(
            &service,
            &mut fresh,
            "DBADDSAFE //ASSOC/Renamed/56/1 Level 9 Unselected"
        )
        .await
        .status,
        401
    );
    assert!(fresh.current.is_none());
    assert!(Database::from_server(&*service.model.lock().await) == before);
    assert_eq!(std::fs::read(&path).unwrap(), bytes);
    // Retain the existing associated NULL SAVE200. This
    // differs from independent/native graph NULL refusal; no parity claim.
    ok_command(&service, &mut client, "PROJECT SAVE ASSOC").await;
    for command in [
        "PROJECT CLOSE ASSOC",
        "PROJECT LOAD ASSOC",
        "PROJECT USE ASSOC",
    ] {
        ok_command(&service, &mut client, command).await;
    }
    for oid in [&source, &copy] {
        assert_eq!(
            scalar(&service, &mut client, &format!("!{oid}/Value")).await,
            "null"
        );
        assert!(service
            .model
            .lock()
            .await
            .level(oid)
            .unwrap()
            .value
            .is_none());
    }
    for (oid, value) in [(&source, 7), (&copy, 8)] {
        ok_command(
            &service,
            &mut client,
            &format!("DBSETSAFE !{oid}/Value {value}"),
        )
        .await;
    }
    let initialized = xml(&service, &mut client, "//ASSOC/Renamed").await;
    for command in [
        "PROJECT SAVE ASSOC",
        "PROJECT CLOSE ASSOC",
        "PROJECT LOAD ASSOC",
        "PROJECT USE ASSOC",
    ] {
        ok_command(&service, &mut client, command).await;
    }
    assert_eq!(
        associated_without_empty_level_tags(&xml(&service, &mut client, "//ASSOC/Renamed").await),
        associated_without_empty_level_tags(&initialized)
    );
    no_io(&mut remote).await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn renamed_associated_pending_group_parent_keeps_oid_route_and_completes_durably() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    associated_level_setup(&service, &mut client).await;
    let app = scalar(&service, &mut client, "//ASSOC/Renamed/56/OID").await;
    let group = created(&service, &mut client, &format!("DBADD !{app} Group")).await;
    assert!(service
        .model
        .lock()
        .await
        .pending_object("ASSOC", &group)
        .unwrap()
        .path
        .is_none());
    let child = created(&service, &mut client, &format!("DBADD !{group} Level")).await;
    {
        let model = service.model.lock().await;
        let pending = model.pending_object("ASSOC", &child).unwrap();
        assert_eq!(pending.parent, format!("!{group}"));
        assert!(pending.path.is_none());
    }
    for command in [
        format!("DBSET !{child}/Value 77"),
        format!("DBSET !{child}/TagName Child"),
        format!("DBSET !{child}/Address 7"),
        format!("DBSET !{group}/TagName PendingGroup"),
        format!("DBSET !{group}/Address 9"),
    ] {
        ok_command(&service, &mut client, &command).await;
    }
    assert_eq!(
        service.model.lock().await.level(&child).unwrap().parent,
        "//ASSOC/11/56/9"
    );
    assert_eq!(
        scalar(&service, &mut client, &format!("!{child}/Value")).await,
        "77"
    );
    let source = xml(&service, &mut client, "//ASSOC/Renamed").await;
    for command in [
        "PROJECT SAVE ASSOC",
        "PROJECT CLOSE ASSOC",
        "PROJECT LOAD ASSOC",
        "PROJECT USE ASSOC",
    ] {
        ok_command(&service, &mut client, command).await;
    }
    let reloaded = xml(&service, &mut client, "//ASSOC/Renamed").await;
    assert_eq!(
        associated_without_empty_level_tags(&reloaded),
        associated_without_empty_level_tags(&source)
    );
    let (new_pci, mut new_remote) = pci();
    let restarted = Service::new(&fixture(), None, path.clone(), new_pci, None).unwrap();
    let mut restarted_client = ClientState::default();
    ok_command(&restarted, &mut restarted_client, "PROJECT USE ASSOC").await;
    assert_eq!(
        xml(&restarted, &mut restarted_client, "//ASSOC/Renamed").await,
        reloaded
    );
    no_io(&mut remote).await;
    no_io(&mut new_remote).await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn renamed_associated_level_pending_claimant_cannot_override_live_or_invalidated_unit_oid() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    let group = associated_level_setup(&service, &mut client).await;
    {
        // Committed synthetic Unit copied only into this local database
        // fixture; physical inventory and interface binding stay unchanged.
        let mut model = service.model.lock().await;
        let unit = model.projects["HARNESS"].networks[&254].units[&5].clone();
        model
            .projects
            .get_mut("ASSOC")
            .unwrap()
            .networks
            .get_mut(&11)
            .unwrap()
            .units
            .insert(5, unit);
    }
    let unit_oid = service.model.lock().await.projects["ASSOC"].networks[&11].units[&5]
        .oid
        .clone();
    {
        // Local adversarial snapshot fixture, not a new XML/native admission.
        let mut model = service.model.lock().await;
        let mut claimant = model.pending_object("ASSOC", &group).unwrap().clone();
        claimant.oid = unit_oid.clone();
        claimant.path = None;
        model
            .db_pending
            .insert("private-unit-claimant".to_string(), claimant);
        model
            .invalidated_unit_oid_lookups
            .insert(("ASSOC".to_string(), group.clone()));
    }
    let before = Database::from_server(&*service.model.lock().await);
    let bytes = std::fs::read(&path).unwrap();
    for oid in [&unit_oid, &group] {
        for command in [
            format!("DBADD !{oid} Level"),
            format!("DBADDSAFE !{oid} Level 8 Shadow"),
        ] {
            assert_eq!(
                run(&service, &mut client, &command).await.status,
                401,
                "{command}"
            );
            assert!(Database::from_server(&*service.model.lock().await) == before);
            assert_eq!(std::fs::read(&path).unwrap(), bytes);
        }
    }
    no_io(&mut remote).await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn renamed_associated_level_login_fence_precedes_delegation_and_value_mutation() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    let group = associated_level_setup(&service, &mut client).await;
    let source = created(
        &service,
        &mut client,
        &format!("DBADDSAFE !{group} Level 7 Source"),
    )
    .await;
    ok_command(
        &service,
        &mut client,
        &format!("DBSETSAFE !{source}/Value 77"),
    )
    .await;
    service
        .set_auth_token_hash(crate::auth::sha256(b"private-level-test-token"))
        .unwrap();
    let before = Database::from_server(&*service.model.lock().await);
    let bytes = std::fs::read(&path).unwrap();
    for command in [
        format!("DBADD !{group} Level"),
        format!("DBADDSAFE !{group} Level 8 Denied"),
        format!("DBCOPYSAFE !{source} !{group} 8 Denied"),
        format!("DBCOPY !{source} !{group}"),
        format!("DBSETSAFE !{source}/Value 8"),
    ] {
        assert_eq!(
            run(&service, &mut client, &command).await.status,
            420,
            "{command}"
        );
        assert!(Database::from_server(&*service.model.lock().await) == before);
        assert_eq!(std::fs::read(&path).unwrap(), bytes);
    }
    ok_command(&service, &mut client, "LOGIN private-level-test-token").await;
    created(
        &service,
        &mut client,
        &format!("DBADDSAFE !{group} Level 8 Admitted"),
    )
    .await;
    no_io(&mut remote).await;
    std::fs::remove_file(path).unwrap();
}

async fn plain_numeric_netvar(service: &Arc<Service>, client: &mut ClientState) -> String {
    for command in [
        "PROJECT NEW ASSOC",
        "PROJECT USE ASSOC",
        "DBCREATENET 11 Eleven Cni 127.0.0.1:1",
        "NET LOAD DB",
        "NET SAVE DB",
    ] {
        ok_command(service, client, command).await;
    }
    created(
        service,
        client,
        "DBADDSAFE //ASSOC/11 Application 56 Lighting",
    )
    .await;
    created(service, client, "DBADDSAFE //ASSOC/11/56 NetVar 4 Variable").await
}

#[tokio::test]
async fn associated_netvar_acknowledged_parent_value_refuses_lossy_resync_atomically() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    let variable = plain_numeric_netvar(&service, &mut client).await;
    ok_command(
        &service,
        &mut client,
        &format!("DBSETSAFE !{variable}/Value 017"),
    )
    .await;
    let child = created(
        &service,
        &mut client,
        &format!("DBADDSAFE !{variable} Level 6 Child"),
    )
    .await;
    ok_command(
        &service,
        &mut client,
        &format!("DBSETSAFE !{child}/Value 33"),
    )
    .await;
    assert_eq!(
        scalar(&service, &mut client, &format!("!{variable}/Value")).await,
        "17"
    );
    let before = Database::from_server(&*service.model.lock().await);
    let bytes = std::fs::read(&path).unwrap();
    for command in [
        "DBRENAMENETSAFE 11 Renamed",
        "DBRENAMENET //ASSOC/11 Renamed",
    ] {
        let response = run(&service, &mut client, command).await;
        assert_eq!(response.status, 408, "{command}: {response:?}");
        assert!(response.final_text.contains("NetVar parent Value"));
        assert!(Database::from_server(&*service.model.lock().await) == before);
        assert_eq!(std::fs::read(&path).unwrap(), bytes);
        assert_eq!(client.current.as_deref(), Some("ASSOC"));
    }
    let model = service.model.lock().await;
    assert_eq!(model.level(&variable).unwrap().value, Some(17));
    assert_eq!(
        model
            .db_fields
            .get(&format!("!{variable}/Value"))
            .map(String::as_str),
        Some("017")
    );
    assert_eq!(model.level(&child).unwrap().value, Some(33));
    drop(model);
    no_io(&mut remote).await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn associated_plain_netvar_retained_parent_or_child_xml_refuses_lossy_resync_atomically() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    let variable = plain_numeric_netvar(&service, &mut client).await;
    let child = created(
        &service,
        &mut client,
        &format!("DBADDSAFE !{variable} Level 6 Child"),
    )
    .await;
    ok_command(
        &service,
        &mut client,
        &format!("DBSETSAFE !{child}/Value 33"),
    )
    .await;
    for oid in [&variable, &child] {
        let key = Server::unit_document_key("ASSOC", oid);
        {
            // Controlled retained repository fixture, not external/native
            // namespace admission. A scalar rename must not discard it.
            let mut model = service.model.lock().await;
            let extras = model.db_xml_extras.entry(key.clone()).or_default();
            extras
                .namespaces
                .insert("owned".to_string(), "urn:cbus:owned-regression".to_string());
            extras.children.push("<owned:Retained/>".to_string());
        }
        let before = Database::from_server(&*service.model.lock().await);
        let bytes = std::fs::read(&path).unwrap();
        let response = run(&service, &mut client, "DBRENAMENETSAFE 11 Renamed").await;
        assert_eq!(response.status, 408, "{response:?}");
        assert!(response.final_text.contains("NetVar retained payload"));
        assert!(Database::from_server(&*service.model.lock().await) == before);
        assert_eq!(std::fs::read(&path).unwrap(), bytes);
        service.model.lock().await.db_xml_extras.remove(&key);
    }
    // The same complete modeled parent/child graph succeeds once the
    // unprojectable fixture is absent, preserving both identities/values.
    ok_command(&service, &mut client, "DBRENAMENETSAFE 11 Renamed").await;
    assert_eq!(
        scalar(&service, &mut client, &format!("!{variable}/OID")).await,
        variable
    );
    assert_eq!(
        scalar(&service, &mut client, &format!("!{child}/Value")).await,
        "33"
    );
    no_io(&mut remote).await;
    std::fs::remove_file(path).unwrap();
}

fn empty_tags_count(document: &str) -> usize {
    let parsed = roxmltree::Document::parse(document).unwrap();
    parsed
        .descendants()
        .filter(|node| node.has_tag_name("TagsDLT"))
        .map(|node| {
            assert!(
                node.attributes().len() == 0
                    && node.children().all(|child| child.is_text()
                        && child.text().unwrap_or_default().trim().is_empty())
            );
            1
        })
        .sum()
}

async fn associated_empty_copy_source(
    service: &Arc<Service>,
    client: &mut ClientState,
    group: &str,
) -> String {
    let source = created(service, client, &format!("DBADD !{group} Level")).await;
    for command in [
        format!("DBSET !{source}/Value 77"),
        format!("DBSET !{source}/TagName Source"),
        format!("DBSET !{source}/Address 7"),
    ] {
        ok_command(service, client, &command).await;
    }
    source
}

async fn install_associated_empty_tags(
    service: &Arc<Service>,
    client: &mut ClientState,
    oid: &str,
) {
    let document = xml(service, client, &format!("!{oid}"))
        .await
        .replace("</Level>", "<TagsDLT/></Level>");
    assert_eq!(
        service
            .handle_document(client, &format!("[named-db] DBSETXML !{oid}"), &document)
            .await
            .status,
        301
    );
}

#[tokio::test]
async fn associated_empty_tags_safe_and_unsafe_copy_preserve_payload_value_and_source_through_restart(
) {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    let group = associated_level_setup(&service, &mut client).await;
    let source = associated_empty_copy_source(&service, &mut client, &group).await;
    install_associated_empty_tags(&service, &mut client, &source).await;
    let source_xml = xml(&service, &mut client, &format!("!{source}")).await;
    let configured = serde_json::to_value(&service.model.lock().await.projects["HARNESS"]).unwrap();
    let copy = created(
        &service,
        &mut client,
        &format!("DBCOPYSAFE !{source} !{group} 8 Copy"),
    )
    .await;
    assert_ne!(copy, source);
    assert_eq!(
        scalar(&service, &mut client, &format!("!{copy}/Value")).await,
        "77"
    );
    assert_eq!(
        empty_tags_count(&xml(&service, &mut client, &format!("!{copy}")).await),
        1
    );
    // This is the explicit setter used by the typed CLI, separate from COPY.
    ok_command(&service, &mut client, &format!("DBSETSAFE !{copy}/Value 8")).await;
    assert_eq!(
        scalar(&service, &mut client, &format!("!{copy}/Value")).await,
        "8"
    );
    assert_eq!(
        empty_tags_count(&xml(&service, &mut client, &format!("!{copy}")).await),
        1
    );
    let pending = created(
        &service,
        &mut client,
        &format!("DBCOPY //ASSOC/Renamed/56/1/7 !{group}"),
    )
    .await;
    assert_eq!(
        scalar(&service, &mut client, &format!("!{pending}/Value")).await,
        "77"
    );
    // Existing incomplete associated XML exports core fields only. Keep that
    // envelope unchanged, while retaining extras under the issued owner until
    // completion makes its normal modeled Level XML authoritative.
    assert_eq!(
        empty_tags_count(&xml(&service, &mut client, &format!("!{pending}")).await),
        0
    );
    {
        let model = service.model.lock().await;
        let copied = model.pending_object("ASSOC", &pending).unwrap();
        assert!(
            copied.path.is_none()
                && !copied.fields.contains_key("Address")
                && !copied.fields.contains_key("TagName")
        );
        assert_eq!(
            model.db_xml_extras[&Server::unit_document_key("ASSOC", &pending)].children,
            vec!["<TagsDLT/>".to_string()]
        );
    }
    for command in [
        format!("DBSET !{pending}/Address 9"),
        format!("DBSET !{pending}/TagName PendingCopy"),
    ] {
        ok_command(&service, &mut client, &command).await;
    }
    assert_eq!(
        empty_tags_count(&xml(&service, &mut client, &format!("!{pending}")).await),
        1
    );
    assert_eq!(
        xml(&service, &mut client, &format!("!{source}")).await,
        source_xml
    );
    let graph = xml(&service, &mut client, "//ASSOC/Renamed").await;
    for command in [
        "PROJECT SAVE ASSOC",
        "PROJECT CLOSE ASSOC",
        "PROJECT LOAD ASSOC",
        "PROJECT USE ASSOC",
    ] {
        ok_command(&service, &mut client, command).await;
    }
    assert_eq!(xml(&service, &mut client, "//ASSOC/Renamed").await, graph);
    no_io(&mut remote).await;
    drop(service);
    let (pci_client, mut restart_remote) = pci();
    let restarted = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    ok_command(&restarted, &mut client, "PROJECT USE ASSOC").await;
    assert_eq!(xml(&restarted, &mut client, "//ASSOC/Renamed").await, graph);
    assert_eq!(
        serde_json::to_value(&restarted.model.lock().await.projects["HARNESS"]).unwrap(),
        configured
    );
    assert_eq!(
        xml(&restarted, &mut client, &format!("!{source}")).await,
        source_xml
    );
    no_io(&mut restart_remote).await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn associated_empty_tags_copied_deferred_flag_loads_once_without_pending_or_foreign_owner() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    let group = associated_level_setup(&service, &mut client).await;
    let source = associated_empty_copy_source(&service, &mut client, &group).await;
    // A same-project numeric neighbor has no associated tag overlay. Its
    // plain typed flag must not be swept into this new LOAD owner subset.
    ok_command(
        &service,
        &mut client,
        "DBCREATENET 12 Neighbor Cni 127.0.0.1:1",
    )
    .await;
    for command in [
        "DBADDSAFE //ASSOC/12 Application 56 Lighting",
        "DBADDSAFE //ASSOC/12/56 Group 1 Neighbor",
    ] {
        created(&service, &mut client, command).await;
    }
    let unassociated = created(
        &service,
        &mut client,
        "DBADDSAFE //ASSOC/12/56/1 Level 40 NeighborLevel",
    )
    .await;
    ok_command(
        &service,
        &mut client,
        &format!("DBSETSAFE !{unassociated}/Value 17"),
    )
    .await;
    {
        let mut model = service.model.lock().await;
        assert!(!model.projects["ASSOC"]
            .tag_networks
            .values()
            .any(|record| record.database_network == Some(12)));
        assert!(model.pending_object("ASSOC", &unassociated).is_none());
        model.db_xml_extras.insert(
            Server::unit_document_key("ASSOC", &unassociated),
            crate::DbXmlExtras {
                saved_level_tags_pending: true,
                ..Default::default()
            },
        );
    }
    ok_command(&service, &mut client, "PROJECT SAVE ASSOC").await;
    assert_eq!(
        empty_tags_count(&xml(&service, &mut client, &format!("!{source}")).await),
        0
    );
    let copy = created(
        &service,
        &mut client,
        &format!("DBCOPYSAFE !{source} !{group} 8 Copy"),
    )
    .await;
    ok_command(&service, &mut client, &format!("DBSETSAFE !{copy}/Value 8")).await;
    let pending = created(&service, &mut client, &format!("DBCOPY !{source} !{group}")).await;
    for command in [
        format!("DBSET !{pending}/TagName PendingCopy"),
        format!("DBSET !{pending}/Address 9"),
    ] {
        ok_command(&service, &mut client, &command).await;
    }
    let foreign = "99999999-9999-4999-8999-000000000001";
    let neighbor = "99999999-9999-4999-8999-000000000002";
    // Controlled snapshot fixtures exercise the exact project/association filter.
    // Neither record is a pending Level: no mirror may be fabricated on LOAD.
    {
        let mut model = service.model.lock().await;
        assert!(model.pending_object("ASSOC", &copy).is_none());
        for oid in [&source, &copy, &pending] {
            assert!(
                model.db_xml_extras[&Server::unit_document_key("ASSOC", oid)]
                    .saved_level_tags_pending
            );
        }
        for (project, oid, parent) in [
            ("OTHER", foreign, "//OTHER/254/56/1"),
            ("HARNESS", neighbor, "//HARNESS/254/56/1"),
        ] {
            model.db_levels.insert(
                format!("{project}\u{1f}{oid}"),
                crate::DbLevel {
                    oid: oid.to_string(),
                    parent: parent.to_string(),
                    address: 40,
                    tag: "Unrelated".to_string(),
                    value: Some(17),
                    raw_value: None,
                    netvar: false,
                },
            );
            model.db_xml_extras.insert(
                Server::unit_document_key(project, oid),
                crate::DbXmlExtras {
                    saved_level_tags_pending: true,
                    ..Default::default()
                },
            );
        }
    }
    for oid in [&source, &copy, &pending] {
        assert_eq!(
            empty_tags_count(&xml(&service, &mut client, &format!("!{oid}")).await),
            0
        );
    }
    for command in [
        "PROJECT SAVE ASSOC",
        "PROJECT CLOSE ASSOC",
        "PROJECT LOAD ASSOC",
        "PROJECT USE ASSOC",
    ] {
        ok_command(&service, &mut client, command).await;
    }
    for oid in [&source, &copy, &pending] {
        assert_eq!(
            empty_tags_count(&xml(&service, &mut client, &format!("!{oid}")).await),
            1
        );
        assert!(
            !service.model.lock().await.db_xml_extras[&Server::unit_document_key("ASSOC", oid)]
                .saved_level_tags_pending
        );
    }
    let graph = xml(&service, &mut client, "//ASSOC/Renamed").await;
    ok_command(&service, &mut client, "PROJECT LOAD ASSOC").await;
    assert_eq!(xml(&service, &mut client, "//ASSOC/Renamed").await, graph);
    {
        let model = service.model.lock().await;
        assert!(model.pending_object("ASSOC", &copy).is_none());
        let untouched = &model.db_xml_extras[&Server::unit_document_key("ASSOC", &unassociated)];
        assert!(untouched.saved_level_tags_pending && untouched.children.is_empty());
        for (project, oid) in [("OTHER", foreign), ("HARNESS", neighbor)] {
            let extras = &model.db_xml_extras[&Server::unit_document_key(project, oid)];
            assert!(extras.saved_level_tags_pending && extras.children.is_empty());
        }
    }
    assert_eq!(
        scalar(&service, &mut client, &format!("!{copy}/Value")).await,
        "8"
    );
    assert_eq!(
        scalar(&service, &mut client, &format!("!{source}/Value")).await,
        "77"
    );
    no_io(&mut remote).await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn associated_empty_tags_unsupported_payload_and_repository_failure_are_atomic() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    let group = associated_level_setup(&service, &mut client).await;
    let source = associated_empty_copy_source(&service, &mut client, &group).await;
    let key = Server::unit_document_key("ASSOC", &source);
    for fragment in [
        "<TagsDLT marker=\"unsupported\"/>",
        "<TagsDLT xmlns:x=\"urn:unknown\"/>",
        "<TagsDLT><!--retained--></TagsDLT>",
        "<?unknown value?><TagsDLT/>",
        "<TagsDLT><TagDLT/></TagsDLT>",
        "<TagsDLT/><TagsDLT/>",
    ] {
        service.model.lock().await.db_xml_extras.insert(
            key.clone(),
            crate::DbXmlExtras {
                children: vec![fragment.to_string()],
                ..Default::default()
            },
        );
        let before = Database::from_server(&*service.model.lock().await);
        let bytes = std::fs::read(&path).unwrap();
        for command in [
            format!("DBCOPYSAFE !{source} !{group} 8 Copy"),
            format!("DBCOPY !{source} !{group}"),
        ] {
            assert_eq!(
                run(&service, &mut client, &command).await.status,
                408,
                "{fragment}: {command}"
            );
            assert!(Database::from_server(&*service.model.lock().await) == before);
            assert_eq!(std::fs::read(&path).unwrap(), bytes);
        }
    }
    service.model.lock().await.db_xml_extras.insert(
        key,
        crate::DbXmlExtras {
            children: vec!["<TagsDLT/>".to_string()],
            saved_level_tags_pending: true,
            ..Default::default()
        },
    );
    let before = Database::from_server(&*service.model.lock().await);
    let bytes = std::fs::read(&path).unwrap();
    std::fs::remove_file(&path).unwrap();
    std::fs::create_dir(&path).unwrap();
    for command in [
        format!("DBCOPYSAFE !{source} !{group} 8 Copy"),
        format!("DBCOPY !{source} !{group}"),
    ] {
        assert_eq!(
            run(&service, &mut client, &command).await.final_text,
            "500 Database commit failed; change rolled back"
        );
        assert!(Database::from_server(&*service.model.lock().await) == before);
        assert!(path.is_dir());
    }
    std::fs::remove_dir(&path).unwrap();
    std::fs::write(&path, bytes).unwrap();
    no_io(&mut remote).await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn associated_empty_tags_document_prolog_and_reserved_namespace_refuse_atomically() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    let group = associated_level_setup(&service, &mut client).await;
    let source = associated_empty_copy_source(&service, &mut client, &group).await;
    let key = Server::unit_document_key("ASSOC", &source);
    // Controlled retained-snapshot forms: fresh strict DBSETXML would normalize
    // the supported empty collection and does not establish these raw bytes.
    for fragment in [
        "<?xml version=\"1.0\"?><TagsDLT/>",
        "<TagsDLT xmlns:xml=\"http://www.w3.org/XML/1998/namespace\"/>",
        "\u{feff}<TagsDLT/>",
    ] {
        service.model.lock().await.db_xml_extras.insert(
            key.clone(),
            crate::DbXmlExtras {
                children: vec![fragment.to_string()],
                saved_level_tags_pending: true,
                ..Default::default()
            },
        );
        let before = Database::from_server(&*service.model.lock().await);
        let bytes = std::fs::read(&path).unwrap();
        for command in [
            format!("DBCOPYSAFE !{source} !{group} 8 Copy"),
            format!("DBCOPY !{source} !{group}"),
        ] {
            assert_eq!(
                run(&service, &mut client, &command).await.status,
                408,
                "{fragment}: {command}"
            );
            assert!(Database::from_server(&*service.model.lock().await) == before);
            assert_eq!(std::fs::read(&path).unwrap(), bytes);
            assert_eq!(
                service.model.lock().await.db_xml_extras[&key].children,
                vec![fragment.to_string()]
            );
        }
    }
    no_io(&mut remote).await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn associated_empty_tags_whitespace_and_flag_copy_loads_one_collection_preserving_source() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    let group = associated_level_setup(&service, &mut client).await;
    let source = associated_empty_copy_source(&service, &mut client, &group).await;
    let whitespace_empty = " \n<TagsDLT/>";
    let key = Server::unit_document_key("ASSOC", &source);
    service.model.lock().await.db_xml_extras.insert(
        key.clone(),
        crate::DbXmlExtras {
            children: vec![whitespace_empty.to_string()],
            saved_level_tags_pending: true,
            ..Default::default()
        },
    );
    let source_xml = xml(&service, &mut client, &format!("!{source}")).await;
    let configured = serde_json::to_value(&service.model.lock().await.projects["HARNESS"]).unwrap();
    let copy = created(
        &service,
        &mut client,
        &format!("DBCOPYSAFE !{source} !{group} 8 Copy"),
    )
    .await;
    ok_command(&service, &mut client, &format!("DBSETSAFE !{copy}/Value 8")).await;
    let pending = created(&service, &mut client, &format!("DBCOPY !{source} !{group}")).await;
    for command in [
        format!("DBSET !{pending}/TagName CopyPending"),
        format!("DBSET !{pending}/Address 9"),
    ] {
        ok_command(&service, &mut client, &command).await;
    }
    assert_eq!(
        xml(&service, &mut client, &format!("!{source}")).await,
        source_xml
    );
    {
        let model = service.model.lock().await;
        assert_eq!(
            model.db_xml_extras[&key].children,
            vec![whitespace_empty.to_string()]
        );
        for oid in [&copy, &pending] {
            let extras = &model.db_xml_extras[&Server::unit_document_key("ASSOC", oid)];
            assert_eq!(extras.children, vec!["<TagsDLT/>".to_string()]);
            assert!(extras.saved_level_tags_pending);
        }
    }
    for command in [
        "PROJECT SAVE ASSOC",
        "PROJECT CLOSE ASSOC",
        "PROJECT LOAD ASSOC",
        "PROJECT USE ASSOC",
    ] {
        ok_command(&service, &mut client, command).await;
    }
    for oid in [&source, &copy, &pending] {
        assert_eq!(
            empty_tags_count(&xml(&service, &mut client, &format!("!{oid}")).await),
            1
        );
    }
    assert_eq!(
        xml(&service, &mut client, &format!("!{source}")).await,
        source_xml
    );
    let graph = xml(&service, &mut client, "//ASSOC/Renamed").await;
    ok_command(&service, &mut client, "PROJECT LOAD ASSOC").await;
    assert_eq!(xml(&service, &mut client, "//ASSOC/Renamed").await, graph);
    {
        let model = service.model.lock().await;
        assert_eq!(
            model.db_xml_extras[&key].children,
            vec![whitespace_empty.to_string()]
        );
        for oid in [&source, &copy, &pending] {
            assert!(
                !model.db_xml_extras[&Server::unit_document_key("ASSOC", oid)]
                    .saved_level_tags_pending
            );
        }
        assert_eq!(
            serde_json::to_value(&model.projects["HARNESS"]).unwrap(),
            configured
        );
    }
    assert_eq!(
        scalar(&service, &mut client, &format!("!{copy}/Value")).await,
        "8"
    );
    assert_eq!(
        scalar(&service, &mut client, &format!("!{source}/Value")).await,
        "77"
    );
    no_io(&mut remote).await;
    std::fs::remove_file(path).unwrap();
}

async fn associated_raw_netvar_levels(
    service: &Arc<Service>,
    client: &mut ClientState,
) -> (String, String, String) {
    let variable = created(service, client, "DBADDSAFE //ASSOC/11/56 NetVar 4 Variable").await;
    let plain = created(
        service,
        client,
        &format!("DBADDSAFE !{variable} Level 7 VarPlain"),
    )
    .await;
    let mirrored = created(service, client, &format!("DBADD !{variable} Level")).await;
    for command in [
        format!("DBSETSAFE !{plain}/Value 7"),
        format!("DBSET !{mirrored}/Value 7"),
        format!("DBSET !{mirrored}/TagName VarMirror"),
        format!("DBSET !{mirrored}/Address 8"),
    ] {
        ok_command(service, client, &command).await;
    }
    (plain, mirrored, variable)
}

// Historical native evidence covers independent named records. These cases
// compose that scalar contract with the separately established numeric owner.
#[tokio::test]
async fn associated_raw_level_values_preserve_one_owner_and_exact_mirrors() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    let group = associated_level_setup(&service, &mut client).await;
    let plain = created(
        &service,
        &mut client,
        &format!("DBADDSAFE !{group} Level 7 Plain"),
    )
    .await;
    let mirrored = created(&service, &mut client, &format!("DBADD !{group} Level")).await;
    for command in [
        format!("DBSET !{mirrored}/Value 7"),
        format!("DBSET !{mirrored}/TagName Mirrored"),
        format!("DBSET !{mirrored}/Address 8"),
        format!("DBSETSAFE !{plain}/Value 7"),
    ] {
        ok_command(&service, &mut client, &command).await;
    }
    let (variable_plain, variable_mirrored, variable) =
        associated_raw_netvar_levels(&service, &mut client).await;
    let neighbor = created(
        &service,
        &mut client,
        "DBADDSAFE //ASSOC/Renamed/56 Group 2 Neighbor",
    )
    .await;
    let neighbor_level = created(
        &service,
        &mut client,
        &format!("DBADDSAFE !{neighbor} Level 5 NeighborLevel"),
    )
    .await;
    ok_command(
        &service,
        &mut client,
        &format!("DBSETSAFE !{neighbor_level}/Value 19"),
    )
    .await;
    ok_command(&service, &mut client, "PROJECT USE HARNESS").await;
    let configured = xml(&service, &mut client, "//HARNESS/254").await;
    ok_command(&service, &mut client, "PROJECT USE ASSOC").await;
    let baseline_xml = xml(&service, &mut client, "//ASSOC/Renamed").await;
    let before_oids = oid_set(&baseline_xml);
    let mut raw_writes = 0;
    for (oid, parent, address) in [
        (&plain, 1, 7),
        (&mirrored, 1, 8),
        (&variable_plain, 4, 7),
        (&variable_mirrored, 4, 8),
    ] {
        for verb in ["DBSETSAFE", "DBSET"] {
            for literal in [
                "0xff",
                "999",
                "oops",
                "-1",
                "256",
                "3.5",
                "arbitrary text",
                "雪<&\"",
                "null",
            ] {
                for field in [
                    format!("!{oid}/Value"),
                    format!("//ASSOC/Renamed/56/{parent}/{address}/Value"),
                    format!("Renamed/56/{parent}/{address}/Value"),
                    format!("//ASSOC/11/56/{parent}/{address}/Value"),
                    format!("11/56/{parent}/{address}/Value"),
                ] {
                    ok_command(&service, &mut client, &format!("{verb} {field} {literal}")).await;
                    raw_writes += 1;
                    for read in [
                        format!("!{oid}/Value"),
                        format!("//ASSOC/Renamed/56/{parent}/{address}/Value"),
                        format!("Renamed/56/{parent}/{address}/Value"),
                        format!("//ASSOC/11/56/{parent}/{address}/Value"),
                        format!("11/56/{parent}/{address}/Value"),
                    ] {
                        assert_eq!(scalar(&service, &mut client, &read).await, literal);
                    }
                    assert_eq!(
                        associated_level_xml_value(
                            &xml(&service, &mut client, &format!("!{oid}")).await
                        )
                        .as_deref(),
                        Some(literal)
                    );
                    let whole = xml(&service, &mut client, "//ASSOC/Renamed").await;
                    let parsed = roxmltree::Document::parse(&whole).unwrap();
                    assert_eq!(
                        parsed
                            .descendants()
                            .find(|n| n.has_tag_name("Level")
                                && n.children()
                                    .any(|c| c.has_tag_name("OID") && c.text() == Some(oid)))
                            .unwrap()
                            .attribute("Value"),
                        Some(literal)
                    );
                    assert_eq!(oid_set(&whole), before_oids);
                    let baseline = roxmltree::Document::parse(&baseline_xml).unwrap();
                    let selected = baseline
                        .descendants()
                        .find(|n| {
                            n.has_tag_name("Level")
                                && n.children().any(|c| {
                                    c.has_tag_name("OID") && c.text() == Some(oid.as_str())
                                })
                        })
                        .unwrap();
                    let range = selected.range();
                    let fragment = &baseline_xml[range.clone()];
                    assert_eq!(fragment.matches("Value=\"7\"").count(), 1);
                    let mut expected = baseline_xml.clone();
                    expected.replace_range(
                        range,
                        &fragment.replacen(
                            "Value=\"7\"",
                            &format!("Value=\"{}\"", crate::xml_escape(literal)),
                            1,
                        ),
                    );
                    assert_eq!(whole, expected, "only the selected Value may change");
                    let model = service.model.lock().await;
                    assert_eq!(model.level(oid).unwrap().value, None);
                    if oid == &mirrored || oid == &variable_mirrored {
                        assert_eq!(
                            model
                                .pending_object("ASSOC", oid)
                                .unwrap()
                                .fields
                                .get("Value")
                                .map(String::as_str),
                            Some(literal)
                        );
                    }
                    drop(model);
                    ok_command(
                        &service,
                        &mut client,
                        &format!("DBSETSAFE !{oid}/Value 007"),
                    )
                    .await;
                    assert_eq!(
                        scalar(&service, &mut client, &format!("!{oid}/Value")).await,
                        "7"
                    );
                }
            }
        }
    }
    assert_eq!(raw_writes, 360);
    assert_eq!(
        service.model.lock().await.level(&variable).unwrap().value,
        None
    );
    assert!(service
        .model
        .lock()
        .await
        .level(&variable)
        .unwrap()
        .raw_value
        .is_none());
    ok_command(&service, &mut client, "PROJECT USE HARNESS").await;
    assert_eq!(
        xml(&service, &mut client, "//HARNESS/254").await,
        configured
    );
    no_io(&mut remote).await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn associated_raw_level_save_reload_and_internal_restart_preserve_literal_value() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    let group = associated_level_setup(&service, &mut client).await;
    let source = created(&service, &mut client, &format!("DBADD !{group} Level")).await;
    for command in [
        format!("DBSET !{source}/Value 7"),
        format!("DBSET !{source}/TagName Mirrored"),
        format!("DBSET !{source}/Address 7"),
    ] {
        ok_command(&service, &mut client, &command).await;
    }
    let (_, variable_source, variable) = associated_raw_netvar_levels(&service, &mut client).await;
    for (source, parent, address) in [(&source, 1, 7), (&variable_source, 4, 8)] {
        for literal in ["0xff", "999", "oops", "-1"] {
            ok_command(
                &service,
                &mut client,
                &format!("DBSETSAFE Renamed/56/{parent}/{address}/Value {literal}"),
            )
            .await;
            let before = xml(&service, &mut client, &format!("!{source}")).await;
            for command in [
                "PROJECT SAVE ASSOC",
                "PROJECT CLOSE ASSOC",
                "PROJECT LOAD ASSOC",
                "PROJECT USE ASSOC",
            ] {
                ok_command(&service, &mut client, command).await;
            }
            assert_eq!(
                scalar(&service, &mut client, &format!("!{source}/Value")).await,
                literal
            );
            assert_eq!(
                associated_without_empty_level_tags(
                    &xml(&service, &mut client, &format!("!{source}")).await
                ),
                associated_without_empty_level_tags(&before)
            );
            assert_eq!(
                service
                    .model
                    .lock()
                    .await
                    .pending_object("ASSOC", source)
                    .unwrap()
                    .fields
                    .get("Value")
                    .map(String::as_str),
                Some(literal)
            );
        }
    }
    let (restart_pci, mut restart_remote) = pci();
    let restarted = Service::new(&fixture(), None, path.clone(), restart_pci, None).unwrap();
    let mut restarted_client = ClientState::default();
    ok_command(&restarted, &mut restarted_client, "PROJECT USE ASSOC").await;
    assert_eq!(
        scalar(
            &restarted,
            &mut restarted_client,
            &format!("!{source}/Value")
        )
        .await,
        "-1"
    );
    assert_eq!(
        associated_level_xml_value(
            &xml(&restarted, &mut restarted_client, &format!("!{source}")).await
        )
        .as_deref(),
        Some("-1")
    );
    assert_eq!(
        restarted
            .model
            .lock()
            .await
            .level(&source)
            .unwrap()
            .raw_value
            .as_deref(),
        Some("-1")
    );
    assert_eq!(
        scalar(
            &restarted,
            &mut restarted_client,
            &format!("!{variable_source}/Value")
        )
        .await,
        "-1"
    );
    assert_eq!(
        restarted
            .model
            .lock()
            .await
            .level(&variable_source)
            .unwrap()
            .raw_value
            .as_deref(),
        Some("-1")
    );
    assert_eq!(
        restarted.model.lock().await.level(&variable).unwrap().value,
        None
    );
    assert!(restarted
        .model
        .lock()
        .await
        .level(&variable)
        .unwrap()
        .raw_value
        .is_none());
    let old: crate::DbLevel = serde_json::from_value(serde_json::json!({"oid":source,"parent":"//ASSOC/11/56/1","address":7,"tag":"Legacy","value":77,"netvar":false})).unwrap();
    assert!(old.raw_value.is_none());
    assert_eq!(old.effective_value().as_deref(), Some("77"));
    let encoded = serde_json::to_value(old).unwrap();
    assert!(encoded.get("raw_value").is_none());
    no_io(&mut remote).await;
    no_io(&mut restart_remote).await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn associated_raw_level_copy_resync_and_external_xml_refuse_atomically() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    let group = associated_level_setup(&service, &mut client).await;
    let source = created(
        &service,
        &mut client,
        &format!("DBADDSAFE !{group} Level 7 Raw"),
    )
    .await;
    ok_command(
        &service,
        &mut client,
        &format!("DBSETSAFE !{source}/Value oops"),
    )
    .await;
    let before = Database::from_server(&*service.model.lock().await);
    let bytes = std::fs::read(&path).unwrap();
    for command in [
        format!("DBCOPYSAFE !{source} !{group} 8 Copy"),
        format!("DBCOPY !{source} !{group}"),
        format!("DBCOPY !{group} //ASSOC/Renamed/56"),
        "DBCOPY //ASSOC/Renamed Installation/ASSOC".to_string(),
        "DBCOPY //ASSOC/11/56/1/7 //ASSOC/11/56/1".to_string(),
        "DBCOPY //ASSOC/11/56/1 //ASSOC/11/56".to_string(),
        "DBCOPY //ASSOC/11 Installation/ASSOC".to_string(),
        format!("DBCOPY !{group} //ASSOC/11/56"),
        "DBCOPY //ASSOC/11/56 //ASSOC/11".to_string(),
        "DBCOPY ASSOC HARNESS".to_string(),
        "DBCOPY //ASSOC HARNESS".to_string(),
        "DBCOPY ///ASSOC/11/56/1/7 //ASSOC/11/56/1".to_string(),
        "DBCOPY ////ASSOC/11/56/1 //ASSOC/11/56".to_string(),
        "DBCOPY ///ASSOC HARNESS".to_string(),
        "DBCOPY //ASSOC/011 Installation/ASSOC".to_string(),
        "DBCOPY //ASSOC/+11 Installation/ASSOC".to_string(),
        "DBCOPY //ASSOC/11/056 //ASSOC/11".to_string(),
        "DBCOPY //ASSOC/11/56/01 //ASSOC/11/56".to_string(),
        "DBCOPY //ASSOC/11/56/1/007 //ASSOC/11/56/1".to_string(),
        "DBCOPY //ASSOC/11/56/1/+7 //ASSOC/11/56/1".to_string(),
        format!("DBCOPY !{group}/descendant //ASSOC/11/56"),
        "DBCOPYSAFE //ASSOC/11/56/1/7 //ASSOC/11/56/1 8 Safe".to_string(),
        "DBRENAMENETSAFE Renamed Again".to_string(),
    ] {
        assert_eq!(
            run(&service, &mut client, &command).await.status,
            408,
            "{command}"
        );
        assert!(
            Database::from_server(&*service.model.lock().await) == before,
            "{command}"
        );
        assert_eq!(std::fs::read(&path).unwrap(), bytes, "{command}");
    }
    let document = xml(&service, &mut client, &format!("!{source}")).await;
    assert_eq!(
        service
            .handle_document(
                &mut client,
                &format!("[named-db] DBSETXML !{source}"),
                &document
            )
            .await
            .status,
        400
    );
    assert!(Database::from_server(&*service.model.lock().await) == before);
    assert_eq!(std::fs::read(&path).unwrap(), bytes);
    {
        let mut model = service.model.lock().await;
        assert!(model
            .sync_tag_database_children("ASSOC", "Renamed")
            .is_err());
        assert!(Database::from_server(&model) == before);
    }
    for command in [
        "DBSETSAFE //ASSOC/11/56/1/99/Value oops",
        "DBSET 11/56/1/7/descendant/Value oops",
    ] {
        assert_eq!(run(&service, &mut client, command).await.status, 401);
        assert!(Database::from_server(&*service.model.lock().await) == before);
        assert_eq!(std::fs::read(&path).unwrap(), bytes);
    }
    // A normal typed value clears raw storage and restores the existing copy owner.
    ok_command(
        &service,
        &mut client,
        &format!("DBSETSAFE !{source}/Value +7"),
    )
    .await;
    assert!(service
        .model
        .lock()
        .await
        .level(&source)
        .unwrap()
        .raw_value
        .is_none());
    let copy = created(
        &service,
        &mut client,
        &format!("DBCOPYSAFE !{source} !{group} 8 Copy"),
    )
    .await;
    assert_eq!(
        scalar(&service, &mut client, &format!("!{copy}/Value")).await,
        "7"
    );
    no_io(&mut remote).await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn associated_raw_level_stale_mirror_auth_foreign_and_repository_fences_preserve_state() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    let group = associated_level_setup(&service, &mut client).await;
    let source = created(&service, &mut client, &format!("DBADD !{group} Level")).await;
    for command in [
        format!("DBSET !{source}/Value 7"),
        format!("DBSET !{source}/TagName Mirror"),
        format!("DBSET !{source}/Address 7"),
    ] {
        ok_command(&service, &mut client, &command).await;
    }
    let key = service
        .model
        .lock()
        .await
        .pending_object_key("ASSOC", &source)
        .unwrap();
    service
        .model
        .lock()
        .await
        .db_pending
        .get_mut(&key)
        .unwrap()
        .fields
        .insert("Value".to_string(), "8".to_string());
    let stale_before = Database::from_server(&*service.model.lock().await);
    let stale_bytes = std::fs::read(&path).unwrap();
    for command in [
        format!("DBSETSAFE !{source}/Value oops"),
        "DBSET Renamed/56/1/7/Value -1".to_string(),
    ] {
        assert_eq!(run(&service, &mut client, &command).await.status, 408);
        assert!(Database::from_server(&*service.model.lock().await) == stale_before);
        assert_eq!(std::fs::read(&path).unwrap(), stale_bytes);
    }
    service
        .model
        .lock()
        .await
        .db_pending
        .get_mut(&key)
        .unwrap()
        .fields
        .insert("Value".to_string(), "7".to_string());
    ok_command(&service, &mut client, "PROJECT USE HARNESS").await;
    let foreign_before = Database::from_server(&*service.model.lock().await);
    let foreign_bytes = std::fs::read(&path).unwrap();
    for command in [
        format!("DBSETSAFE !{source}/Value oops"),
        "DBSETSAFE //ASSOC/Renamed/56/1/7/Value oops".to_string(),
        "DBSETSAFE //ASSOC/11/56/1/7/Value oops".to_string(),
    ] {
        assert_eq!(
            run(&service, &mut client, &command).await.status,
            401,
            "{command}"
        );
        assert!(Database::from_server(&*service.model.lock().await) == foreign_before);
        assert_eq!(std::fs::read(&path).unwrap(), foreign_bytes);
    }
    ok_command(&service, &mut client, "PROJECT USE ASSOC").await;
    service
        .set_auth_token_hash(crate::auth::sha256(b"raw-level-local-test"))
        .unwrap();
    let auth_before = Database::from_server(&*service.model.lock().await);
    let auth_bytes = std::fs::read(&path).unwrap();
    for command in [
        format!("DBSETSAFE !{source}/Value 999"),
        "DBSET Renamed/56/1/7/Value -1".to_string(),
    ] {
        assert_eq!(run(&service, &mut client, &command).await.status, 420);
        assert!(Database::from_server(&*service.model.lock().await) == auth_before);
        assert_eq!(std::fs::read(&path).unwrap(), auth_bytes);
    }
    ok_command(&service, &mut client, "LOGIN raw-level-local-test").await;
    let before = Database::from_server(&*service.model.lock().await);
    let bytes = std::fs::read(&path).unwrap();
    std::fs::remove_file(&path).unwrap();
    std::fs::create_dir(&path).unwrap();
    for command in [
        format!("DBSETSAFE !{source}/Value 0xff"),
        "DBSET //ASSOC/Renamed/56/1/7/Value oops".to_string(),
    ] {
        assert_eq!(
            run(&service, &mut client, &command).await.final_text,
            "500 Database commit failed; change rolled back"
        );
        assert!(Database::from_server(&*service.model.lock().await) == before);
        assert!(path.is_dir());
    }
    std::fs::remove_dir(&path).unwrap();
    std::fs::write(&path, bytes).unwrap();
    no_io(&mut remote).await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn associated_raw_level_tagged_wire_matches_local_vector() {
    let vector: serde_json::Value = serde_json::from_str(include_str!(
        "../../../../testdata/vectors/cgate_associated_raw_level_value.json"
    ))
    .unwrap();
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    let group = associated_level_setup(&service, &mut client).await;
    let source = created(
        &service,
        &mut client,
        &format!("DBADDSAFE !{group} Level 7 Raw"),
    )
    .await;
    for case in vector["cases"].as_array().unwrap() {
        let command = case["command"]
            .as_str()
            .unwrap()
            .replace("%LEVEL%", &source)
            .replace("%GROUP%", &group);
        let expected = case["wire"]
            .as_str()
            .unwrap()
            .replace("%LEVEL%", &source)
            .replace("%GROUP%", &group);
        let response = run(&service, &mut client, &command).await;
        assert_eq!(crate::format_response(&response), expected, "{command}");
    }
    no_io(&mut remote).await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn associated_raw_level_byte_aliases_and_literal_null_keep_established_typed_policy() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    let group = associated_level_setup(&service, &mut client).await;
    let mirrored = created(&service, &mut client, &format!("DBADD !{group} Level")).await;
    for command in [
        format!("DBSET !{mirrored}/Value 077"),
        format!("DBSET !{mirrored}/TagName Alias"),
        format!("DBSET !{mirrored}/Address 7"),
    ] {
        ok_command(&service, &mut client, &command).await;
    }
    assert_eq!(
        service
            .model
            .lock()
            .await
            .pending_object("ASSOC", &mirrored)
            .unwrap()
            .fields
            .get("Value")
            .map(String::as_str),
        Some("077")
    );
    for literal in ["77", "077", "+77"] {
        ok_command(
            &service,
            &mut client,
            &format!("DBSETSAFE !{mirrored}/Value {literal}"),
        )
        .await;
        assert_eq!(
            scalar(&service, &mut client, &format!("!{mirrored}/Value")).await,
            "77"
        );
        assert_eq!(
            service
                .model
                .lock()
                .await
                .pending_object("ASSOC", &mirrored)
                .unwrap()
                .fields
                .get("Value")
                .map(String::as_str),
            Some("77")
        );
    }
    ok_command(
        &service,
        &mut client,
        &format!("DBSETSAFE !{mirrored}/Value -0"),
    )
    .await;
    assert_eq!(
        scalar(&service, &mut client, &format!("!{mirrored}/Value")).await,
        "0"
    );
    assert_eq!(
        service.model.lock().await.level(&mirrored).unwrap().value,
        Some(0)
    );
    ok_command(
        &service,
        &mut client,
        &format!("DBSET !{mirrored}/Value -0"),
    )
    .await;
    assert_eq!(
        scalar(&service, &mut client, &format!("!{mirrored}/Value")).await,
        "-0"
    );
    assert_eq!(
        service
            .model
            .lock()
            .await
            .level(&mirrored)
            .unwrap()
            .raw_value
            .as_deref(),
        Some("-0")
    );
    let plain = created(
        &service,
        &mut client,
        &format!("DBADDSAFE !{group} Level 8 Plain"),
    )
    .await;
    ok_command(
        &service,
        &mut client,
        &format!("DBSETSAFE !{plain}/Value null"),
    )
    .await;
    assert_eq!(
        associated_level_xml_value(&xml(&service, &mut client, &format!("!{plain}")).await)
            .as_deref(),
        Some("null")
    );
    assert_eq!(
        service
            .model
            .lock()
            .await
            .level(&plain)
            .unwrap()
            .raw_value
            .as_deref(),
        Some("null")
    );
    ok_command(&service, &mut client, &format!("DBSET !{plain}/Value")).await;
    assert_eq!(
        associated_level_xml_value(&xml(&service, &mut client, &format!("!{plain}")).await),
        None
    );
    assert!(service
        .model
        .lock()
        .await
        .level(&plain)
        .unwrap()
        .raw_value
        .is_none());
    assert_eq!(
        scalar(&service, &mut client, &format!("!{plain}/Value")).await,
        "null"
    );
    let before = Database::from_server(&*service.model.lock().await);
    let bytes = std::fs::read(&path).unwrap();
    assert_eq!(
        run(
            &service,
            &mut client,
            &format!("DBSETSAFE !{plain}/Value bad#tail")
        )
        .await
        .status,
        400
    );
    assert!(Database::from_server(&*service.model.lock().await) == before);
    assert_eq!(std::fs::read(&path).unwrap(), bytes);
    no_io(&mut remote).await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn associated_raw_level_xml_unrepresentable_scalars_refuse_without_poisoning_owner() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    let group = associated_level_setup(&service, &mut client).await;
    let source = created(
        &service,
        &mut client,
        &format!("DBADDSAFE !{group} Level 7 Text"),
    )
    .await;
    ok_command(
        &service,
        &mut client,
        &format!("DBSETSAFE !{source}/Value 7"),
    )
    .await;
    let before = Database::from_server(&*service.model.lock().await);
    let bytes = std::fs::read(&path).unwrap();
    let before_xml = xml(&service, &mut client, "//ASSOC/Renamed").await;
    for verb in ["DBSETSAFE", "DBSET"] {
        for literal in ["bad\u{FFFE}", "bad\u{FFFF}"] {
            let command = format!("{verb} !{source}/Value {literal}");
            assert!(crate::parse_command(&format!("[named-db] {command}")).is_ok());
            assert_eq!(run(&service, &mut client, &command).await.status, 408);
            assert!(Database::from_server(&*service.model.lock().await) == before);
            assert_eq!(std::fs::read(&path).unwrap(), bytes);
            assert_eq!(
                xml(&service, &mut client, "//ASSOC/Renamed").await,
                before_xml
            );
            assert_eq!(
                scalar(&service, &mut client, &format!("!{source}/Value")).await,
                "7"
            );
        }
    }
    no_io(&mut remote).await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn associated_raw_level_copy_guard_preserves_independent_numeric_lexical_owner() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    let group = associated_level_setup(&service, &mut client).await;
    let source = created(
        &service,
        &mut client,
        &format!("DBADDSAFE !{group} Level 7 Raw"),
    )
    .await;
    ok_command(
        &service,
        &mut client,
        &format!("DBSETSAFE !{source}/Value oops"),
    )
    .await;
    let associated_before = xml(&service, &mut client, "//ASSOC/Renamed").await;
    for (index, name) in ["011", "11", "+11"].into_iter().enumerate() {
        let oid = |part: usize| format!("11111111-2222-4333-8444-{:012x}", (index + 1) * 16 + part);
        let level_oid = oid(5);
        let independent = format!(
            r#"<Network><OID>{}</OID><Address>{name}</Address><TagName>Independent</TagName><NetworkNumber>0xff</NetworkNumber><Interface><OID>{}</OID><InterfaceType>Cni</InterfaceType><InterfaceAddress>127.0.0.1:1</InterfaceAddress></Interface><Application><OID>{}</OID><Address>56</Address><TagName>Lighting</TagName><Group><OID>{}</OID><Address>1</Address><TagName>Main</TagName><Level Value="19"><OID>{level_oid}</OID><Address>7</Address><TagName>IndependentLevel</TagName></Level></Group></Application></Network>"#,
            oid(1),
            oid(2),
            oid(3),
            oid(4)
        );
        let record =
            crate::tag_network::TagNetwork::parse(&independent, None, 20 + index as u64).unwrap();
        service
            .model
            .lock()
            .await
            .register_tag_network("ASSOC", record);
        let independent_path = format!("//ASSOC/{name}");
        let independent_before = xml(&service, &mut client, &independent_path).await;
        let fields = [
            format!("{independent_path}/56/1/7/Value"),
            format!("{name}/56/1/7/Value"),
            format!("!{level_oid}/Value"),
        ];
        for verb in ["DBSETSAFE", "DBSET"] {
            for field in &fields {
                ok_command(
                    &service,
                    &mut client,
                    &format!("{verb} {field} independent text"),
                )
                .await;
                for read in &fields {
                    assert_eq!(
                        scalar(&service, &mut client, read).await,
                        "independent text"
                    );
                }
                assert_eq!(
                    xml(&service, &mut client, "//ASSOC/Renamed").await,
                    associated_before
                );
                ok_command(&service, &mut client, &format!("{verb} {field} 19")).await;
                assert_eq!(
                    xml(&service, &mut client, &independent_path).await,
                    independent_before
                );
            }
        }
        assert!(!service
            .model
            .lock()
            .await
            .associated_raw_level_copy_source(&independent_path));
        let copy = created(
            &service,
            &mut client,
            &format!("DBCOPY {independent_path} Installation/Project"),
        )
        .await;
        assert!(!copy.is_empty());
        assert_eq!(
            xml(&service, &mut client, &independent_path).await,
            independent_before
        );
        assert_eq!(
            xml(&service, &mut client, "//ASSOC/Renamed").await,
            associated_before
        );
        assert_eq!(
            scalar(&service, &mut client, &format!("!{source}/Value")).await,
            "oops"
        );
    }
    no_io(&mut remote).await;
    std::fs::remove_file(path).unwrap();
}
