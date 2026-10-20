//! Bounded issue #74 corrections: canonical numeric COPY destinations route
//! through the exact associated owner, the plain-Level LOAD sweep preserves
//! unsupported retained XML atomically, and the missing-descendant Value
//! getter preserves the lexical-root error.
//!
//! Owned-model behavior only; no original/vendor/hardware acceptance.

use super::*;

async fn run(service: &Arc<Service>, client: &mut ClientState, command: &str) -> Response {
    service
        .handle(client, &format!("[issue-74] {command}"))
        .await
}

async fn ok_command(service: &Arc<Service>, client: &mut ClientState, command: &str) {
    let response = run(service, client, command).await;
    let expected = if command.starts_with("DBCREATENET ") {
        301
    } else {
        200
    };
    assert_eq!(response.status, expected, "{command}: {response:?}");
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

async fn no_io(remote: &mut tokio::io::DuplexStream) {
    assert!(
        tokio::time::timeout(Duration::from_millis(20), remote.read_u8())
            .await
            .is_err()
    );
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
async fn associated_numeric_copy_destination_routes_through_exact_owner() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    let group = associated_level_setup(&service, &mut client).await;
    let plain = created(
        &service,
        &mut client,
        &format!("DBADDSAFE !{group} Level 9 PlainSource"),
    )
    .await;
    ok_command(
        &service,
        &mut client,
        &format!("DBSETSAFE !{plain}/Value 77"),
    )
    .await;
    let netvar = created(
        &service,
        &mut client,
        "DBADDSAFE //ASSOC/Renamed/56 NetVar 4 Variable",
    )
    .await;
    let netvar_level = created(
        &service,
        &mut client,
        &format!("DBADDSAFE !{netvar} Level 42 High"),
    )
    .await;
    ok_command(
        &service,
        &mut client,
        &format!("DBSET !{netvar_level}/Value 23"),
    )
    .await;
    let completed = created(&service, &mut client, &format!("DBADD !{group} Level")).await;
    for command in [
        format!("DBSET !{completed}/Value 78"),
        format!("DBSET !{completed}/TagName Completed"),
        format!("DBSET !{completed}/Address 8"),
    ] {
        ok_command(&service, &mut client, &command).await;
    }
    ok_command(&service, &mut client, "PROJECT SAVE ASSOC").await;
    let before_source = xml(&service, &mut client, &format!("!{plain}")).await;
    let numeric = created(
        &service,
        &mut client,
        &format!("DBCOPYSAFE !{plain} //ASSOC/11/56/1 12 NumericCopy"),
    )
    .await;
    assert_ne!(numeric, plain);
    assert_eq!(
        scalar(&service, &mut client, &format!("!{numeric}/Value")).await,
        "77"
    );
    let unsafe_copy = created(
        &service,
        &mut client,
        &format!("DBCOPY !{plain} //ASSOC/11/56/1"),
    )
    .await;
    assert_ne!(unsafe_copy, plain);
    let lexical = created(
        &service,
        &mut client,
        "DBCOPYSAFE //ASSOC/Renamed/56/1/9 //ASSOC/11/56/1 13 NumericLexicalCopy",
    )
    .await;
    assert_ne!(lexical, plain);
    assert_eq!(
        scalar(&service, &mut client, &format!("!{lexical}/Value")).await,
        "77"
    );
    let netvar_copy = created(
        &service,
        &mut client,
        &format!("DBCOPYSAFE !{netvar_level} //ASSOC/11/56/4 43 NetVarNumericCopy"),
    )
    .await;
    assert_eq!(
        scalar(&service, &mut client, &format!("!{netvar_copy}/Value")).await,
        "23"
    );
    let control = created(
        &service,
        &mut client,
        &format!("DBCOPYSAFE !{plain} //ASSOC/Renamed/56/1 14 LexicalCopy"),
    )
    .await;
    assert_ne!(control, plain);
    for command in [
        format!("DBCOPYSAFE !{plain} //ASSOC/11/56/9 15 Ghost"),
        format!("DBCOPYSAFE !{plain} //ASSOC/11/99 15 Ghost"),
    ] {
        let response = run(&service, &mut client, &command).await;
        assert_eq!(response.status, 401, "{command}: {response:?}");
    }
    assert_eq!(
        xml(&service, &mut client, &format!("!{plain}")).await,
        before_source
    );
    for command in [
        "PROJECT SAVE ASSOC",
        "PROJECT CLOSE ASSOC",
        "PROJECT LOAD ASSOC",
        "PROJECT USE ASSOC",
    ] {
        ok_command(&service, &mut client, command).await;
    }
    assert_eq!(
        scalar(&service, &mut client, &format!("!{numeric}/Value")).await,
        "77"
    );
    // LOAD may materialize the admitted absent collection on the source; the
    // typed value and identity stay owned while unrelated bytes are preserved.
    assert_eq!(
        scalar(&service, &mut client, &format!("!{plain}/Value")).await,
        "77"
    );
    assert!(xml(&service, &mut client, &format!("!{plain}"))
        .await
        .contains("Value=\"77\""));
    no_io(&mut remote).await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn associated_plain_level_load_preserves_unsupported_xml_atomically() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    let group = associated_level_setup(&service, &mut client).await;
    let absent = created(
        &service,
        &mut client,
        &format!("DBADDSAFE !{group} Level 20 Absent"),
    )
    .await;
    ok_command(
        &service,
        &mut client,
        &format!("DBSETSAFE !{absent}/Value 20"),
    )
    .await;
    let strict = created(
        &service,
        &mut client,
        &format!("DBADDSAFE !{group} Level 21 Strict"),
    )
    .await;
    ok_command(
        &service,
        &mut client,
        &format!("DBSETSAFE !{strict}/Value 21"),
    )
    .await;
    {
        let mut model = service.model.lock().await;
        let key = Server::unit_document_key("ASSOC", &strict);
        model.db_xml_extras.entry(key).or_default().children = vec!["<TagsDLT/>".to_string()];
    }
    let unsupported: Vec<(&str, Vec<String>)> = vec![
        ("pi", vec!["<?unknown value?><TagsDLT/>".to_string()]),
        ("comment", vec!["<!--retained--><TagsDLT/>".to_string()]),
        ("namespaced", vec!["<x:TagsDLT/>".to_string()]),
        ("bom", vec!["\u{FEFF}<TagsDLT/>".to_string()]),
        (
            "attr",
            vec!["<TagsDLT marker=\"unsupported\"/>".to_string()],
        ),
        ("nonempty", vec!["<TagsDLT><TagDLT/></TagsDLT>".to_string()]),
    ];
    let mut oids = Vec::new();
    for (index, (label, children)) in unsupported.iter().enumerate() {
        let address = (30 + index) as u8;
        let oid = created(
            &service,
            &mut client,
            &format!("DBADDSAFE !{group} Level {address} {label}"),
        )
        .await;
        ok_command(&service, &mut client, &format!("DBSETSAFE !{oid}/Value 77")).await;
        {
            let mut model = service.model.lock().await;
            let key = Server::unit_document_key("ASSOC", &oid);
            let extras = model.db_xml_extras.entry(key).or_default();
            extras.children = children.clone();
            extras.saved_level_tags_pending = true;
        }
        oids.push((label.to_string(), oid, children.clone()));
    }
    {
        let mut model = service.model.lock().await;
        for oid in [&absent, &strict] {
            let key = Server::unit_document_key("ASSOC", oid);
            model
                .db_xml_extras
                .entry(key)
                .or_default()
                .saved_level_tags_pending = true;
        }
    }
    ok_command(&service, &mut client, "PROJECT SAVE ASSOC").await;
    let before: Vec<(String, Vec<String>)> = {
        let model = service.model.lock().await;
        oids.iter()
            .map(|(label, oid, _)| {
                let key = Server::unit_document_key("ASSOC", oid);
                let extras = model.db_xml_extras.get(&key).cloned().unwrap_or_default();
                (label.clone(), extras.children)
            })
            .collect()
    };
    ok_command(&service, &mut client, "PROJECT LOAD ASSOC").await;
    {
        let model = service.model.lock().await;
        for (label, oid, children) in &oids {
            let key = Server::unit_document_key("ASSOC", oid);
            let extras = model.db_xml_extras.get(&key).cloned().unwrap_or_default();
            assert_eq!(&extras.children, children, "{label}");
            assert!(extras.saved_level_tags_pending, "{label} marker must stay");
        }
        for oid in [&absent, &strict] {
            let key = Server::unit_document_key("ASSOC", oid);
            let extras = model.db_xml_extras.get(&key).cloned().unwrap_or_default();
            assert!(!extras.saved_level_tags_pending, "{oid}");
            assert!(
                extras.children.iter().any(|c| c.starts_with("<TagsDLT")),
                "{oid} must have collection"
            );
        }
    }
    ok_command(&service, &mut client, "PROJECT LOAD ASSOC").await;
    {
        let model = service.model.lock().await;
        for (index, (label, oid, _)) in oids.iter().enumerate() {
            let key = Server::unit_document_key("ASSOC", oid);
            let extras = model.db_xml_extras.get(&key).cloned().unwrap_or_default();
            assert_eq!(extras.children, before[index].1, "{label} second LOAD");
            assert!(
                extras.saved_level_tags_pending,
                "{label} marker second LOAD"
            );
        }
    }
    no_io(&mut remote).await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn associated_missing_descendant_value_getter_preserves_lexical_error() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    let group = associated_level_setup(&service, &mut client).await;
    let plain = created(
        &service,
        &mut client,
        &format!("DBADDSAFE !{group} Level 9 Plain"),
    )
    .await;
    ok_command(
        &service,
        &mut client,
        &format!("DBSETSAFE !{plain}/Value 77"),
    )
    .await;
    // Independent numeric-looking Network "11" wins lexically; insert it by
    // cloning the associated record so private tag bookkeeping stays valid.
    {
        let mut model = service.model.lock().await;
        let associated = model.projects["ASSOC"].tag_networks["Renamed"].clone();
        let mut independent = associated;
        for (key, value) in independent.root.fields.iter_mut() {
            if key == "Address" {
                *value = "11".to_string();
            } else if key == "OID" {
                *value = crate::fresh_oid();
            } else if key == "TagName" {
                *value = "n11".to_string();
            }
        }
        independent.database_network = None;
        model
            .projects
            .get_mut("ASSOC")
            .unwrap()
            .tag_networks
            .insert("11".to_string(), independent);
    }
    ok_command(&service, &mut client, "PROJECT SAVE ASSOC").await;
    let missing = run(&service, &mut client, "DBGET //ASSOC/11/56/1/9/Value").await;
    assert_eq!(missing.status, 401, "{missing:?}");
    assert!(
        missing.final_text.contains("Index out of range"),
        "{missing:?}"
    );
    assert_eq!(
        scalar(&service, &mut client, &format!("!{plain}/Value")).await,
        "77"
    );
    assert_eq!(
        scalar(&service, &mut client, "//ASSOC/Renamed/56/1/9/Value").await,
        "77"
    );
    let refused = run(
        &service,
        &mut client,
        "DBSETSAFE //ASSOC/11/56/1/9/Value 99",
    )
    .await;
    assert_eq!(refused.status, 401, "{refused:?}");
    assert_eq!(
        scalar(&service, &mut client, &format!("!{plain}/Value")).await,
        "77"
    );
    no_io(&mut remote).await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn associated_numeric_value_getter_keeps_independent_missing_descendant_error() {
    // A numeric-parent copy owns //ASSOC/11/56/1/12. An independent
    // numeric-looking Network "11" without that subtree must keep its
    // lexical missing-descendant refusal instead of falling through to the
    // associated numeric owner's Value getter.
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    let group = associated_level_setup(&service, &mut client).await;
    let plain = created(
        &service,
        &mut client,
        &format!("DBADDSAFE !{group} Level 9 PlainSource"),
    )
    .await;
    ok_command(
        &service,
        &mut client,
        &format!("DBSETSAFE !{plain}/Value 77"),
    )
    .await;
    let numeric = created(
        &service,
        &mut client,
        &format!("DBCOPYSAFE !{plain} //ASSOC/11/56/1 12 NumericCopy"),
    )
    .await;
    assert_eq!(
        scalar(&service, &mut client, &format!("!{numeric}/Value")).await,
        "77"
    );
    // Independent numeric-looking Network "11" wins lexically but owns no 56
    // subtree: move its cloned Application address aside so the requested
    // descendant is genuinely missing under that root.
    {
        let mut model = service.model.lock().await;
        let associated = model.projects["ASSOC"].tag_networks["Renamed"].clone();
        let mut independent = associated;
        for (key, value) in independent.root.fields.iter_mut() {
            if key == "Address" {
                *value = "11".to_string();
            } else if key == "OID" {
                *value = crate::fresh_oid();
            } else if key == "TagName" {
                *value = "n11".to_string();
            }
        }
        for child in independent
            .root
            .children
            .iter_mut()
            .filter(|child| child.element == "Application")
        {
            for (key, value) in child.fields.iter_mut() {
                if key == "Address" {
                    *value = "57".to_string();
                }
            }
        }
        independent.database_network = None;
        model
            .projects
            .get_mut("ASSOC")
            .unwrap()
            .tag_networks
            .insert("11".to_string(), independent);
    }
    ok_command(&service, &mut client, "PROJECT SAVE ASSOC").await;
    let missing = run(&service, &mut client, "DBGET //ASSOC/11/56/1/12/Value").await;
    assert_eq!(missing.status, 401, "{missing:?}");
    assert!(
        missing.final_text.contains("Index out of range"),
        "{missing:?}"
    );
    let refused = run(
        &service,
        &mut client,
        "DBSETSAFE //ASSOC/11/56/1/12/Value 99",
    )
    .await;
    assert_eq!(refused.status, 401, "{refused:?}");
    assert_eq!(
        scalar(&service, &mut client, &format!("!{numeric}/Value")).await,
        "77"
    );
    no_io(&mut remote).await;
    std::fs::remove_file(path).unwrap();
}

#[test]
fn associated_numeric_copy_vector_pins_issue74_wire_contract() {
    let text = include_str!("../../../../testdata/vectors/cgate_associated_numeric_copy.jsonl");
    let rows: Vec<serde_json::Value> = text
        .lines()
        .filter(|line| !line.trim().is_empty())
        .map(|line| serde_json::from_str(line).expect("copy row must parse"))
        .collect();
    assert_eq!(rows.len(), 8);
    let expected = [
        (
            "DBCOPYSAFE !<source-Level-OID> //LAB/11/56/1 12 NumericCopy",
            301_u64,
        ),
        ("DBCOPY !<source-Level-OID> //LAB/11/56/1", 301_u64),
        (
            "DBCOPYSAFE //LAB/Renamed/56/1/9 //LAB/11/56/1 13 NumericLexicalCopy",
            301_u64,
        ),
        (
            "DBCOPYSAFE !<netvar-Level-OID> //LAB/11/56/4 43 NetVarNumericCopy",
            301_u64,
        ),
        (
            "DBCOPYSAFE !<source-Level-OID> //LAB/Renamed/56/1 14 LexicalCopy",
            301_u64,
        ),
        (
            "DBCOPYSAFE !<source-Level-OID> //LAB/11/56/9 15 Ghost",
            401_u64,
        ),
        (
            "DBCOPYSAFE !<source-Level-OID> //LAB/11/99 15 Ghost",
            401_u64,
        ),
        (
            "DBCOPYSAFE !<raw-Level-OID> //LAB/11/56/1 16 RawCopy",
            408_u64,
        ),
    ];
    for (row, (request, status)) in rows.iter().zip(expected) {
        assert_eq!(
            row["format"].as_str().unwrap(),
            "cbus-associated-numeric-copy-v1"
        );
        assert_eq!(row["issue"].as_u64().unwrap(), 74);
        assert_eq!(row["target"].as_str().unwrap(), "copy");
        assert_eq!(row["request"].as_str().unwrap(), request);
        assert_eq!(row["status"].as_u64().unwrap(), status);
        assert_eq!(row["wire"].as_u64().unwrap(), status);
    }
}
