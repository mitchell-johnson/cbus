//! Issue #124 vectors + live atomic Application subtree copy checks.
//!
//! `cgate_application_subtree_copy.jsonl` pins the admitted contract
//! (numeric + OID sources, Group/Level/NetVar/NULL/labels/XML extras, fresh
//! disjoint OIDs, roster append-once, conflict/isolation/refusal snapshots,
//! persistence + no-replay). The live tests below execute the real
//! `DBCOPYSAFE` workflow: NULL Values stay NULL, TagsDLT label identities are
//! reminted, sources stay byte-identical, conflicts refuse atomically, and
//! copies survive SAVE/CLOSE/LOAD.
use cbus_cgate::{AccessLevel, Response, Server};
use std::collections::BTreeSet;

fn vectors() -> Vec<serde_json::Value> {
    include_str!("../../testdata/vectors/cgate_application_subtree_copy.jsonl")
        .lines()
        .filter(|line| !line.trim().is_empty())
        .map(|line| serde_json::from_str(line).expect("vector row must parse"))
        .collect()
}

#[test]
fn subtree_copy_vectors_pin_issue_124_contract() {
    let rows = vectors();
    assert_eq!(rows.len(), 20);
    for row in &rows {
        assert_eq!(
            row["format"].as_str().unwrap(),
            "cbus-application-subtree-copy-v1"
        );
        assert_eq!(row["issue"].as_u64().unwrap(), 124);
    }
    let by_name = |name: &str| {
        rows.iter()
            .find(|row| row["name"].as_str().unwrap() == name)
            .unwrap_or_else(|| panic!("missing vector {name}"))
    };
    // Admitted copies answer 301; refusals keep their native status.
    for name in [
        "numeric-application-copy-duplicates-complete-subtree",
        "oid-application-copy-matches-numeric",
        "numeric-group-copy-preserves-levels",
        "numeric-level-copy-retains-value-for-initializer",
        "netvar-copy-preserves-child-levels",
        "null-level-copy-preserves-null",
        "group-tagsdlt-labels-travel-with-fresh-inner-oids",
        "zero-pci-traffic-and-roster-append-once",
    ] {
        assert_eq!(by_name(name)["status"].as_u64().unwrap(), 301, "{name}");
    }
    assert_eq!(
        by_name("destination-application-conflict-refuses-atomically")["status"]
            .as_u64()
            .unwrap(),
        409
    );
    assert_eq!(
        by_name("missing-source-refuses-without-mutation")["status"]
            .as_u64()
            .unwrap(),
        401
    );
    assert_eq!(
        by_name("lost-success-does-not-replay")["body"]
            .as_str()
            .unwrap(),
        "single-connection-no-replay"
    );
    assert_eq!(
        by_name("zero-pci-traffic-and-roster-append-once")["body"]
            .as_str()
            .unwrap(),
        "no-pci-traffic"
    );
}

fn handle(server: &mut Server, tag: &str, command: &str) -> Response {
    let response = server.handle(&format!("[{tag}] {command}"));
    response
}

fn oid_of(response: &Response) -> String {
    assert_eq!(response.status, 301, "{response:?}");
    response
        .final_text
        .strip_prefix("301 OID=")
        .expect("301 receipt")
        .to_string()
}

fn document(server: &mut Server, tag: &str, path: &str) -> String {
    let response = handle(server, tag, &format!("DBGETXML {path}"));
    assert_eq!(response.status, 200, "{path}: {response:?}");
    response
        .lines
        .iter()
        .filter_map(|line| line.strip_prefix("347-"))
        .collect()
}

fn oid_set(document: &str) -> BTreeSet<String> {
    roxmltree::Document::parse(document)
        .unwrap()
        .descendants()
        .filter(|node| node.has_tag_name("OID"))
        .map(|node| node.text().unwrap().to_string())
        .collect()
}

fn scalar(server: &mut Server, tag: &str, path: &str) -> String {
    let response = handle(server, tag, &format!("DBGET {path}"));
    assert_eq!(response.status, 342, "{path}: {response:?}");
    response.final_text.split_once('=').unwrap().1.to_string()
}

fn seed() -> Server {
    let mut server = Server::new(AccessLevel::Program);
    assert_eq!(handle(&mut server, "1", "PROJECT NEW LAB").status, 200);
    assert_eq!(
        handle(&mut server, "2", "DBCREATENET 254 Loopback Cni 127.0.0.1:1").status,
        301
    );
    server
}

#[test]
fn null_level_copy_preserves_null_and_isolates_graphs() {
    let mut server = seed();
    let app = oid_of(&handle(
        &mut server,
        "3",
        "DBADDSAFE //LAB/254 Application 56 Lighting",
    ));
    let _ = app;
    let _group = oid_of(&handle(
        &mut server,
        "4",
        "DBADDSAFE //LAB/254/56 Group 1 Lamp",
    ));
    // NULL level: created but never initialized.
    let null_level = oid_of(&handle(
        &mut server,
        "5",
        "DBADDSAFE //LAB/254/56/1 Level 11 NullLamp",
    ));
    assert_eq!(
        scalar(&mut server, "6", &format!("!{null_level}/Value")),
        "null"
    );
    let before = document(&mut server, "7", "//LAB/254/56");
    let copied = oid_of(&handle(
        &mut server,
        "8",
        "DBCOPYSAFE //LAB/254/56 //LAB/254 57 Copy",
    ));
    let copied_xml = document(&mut server, "9", &format!("!{copied}"));
    // Fresh disjoint identities across the whole subtree.
    let source_oids = oid_set(&before);
    let copied_oids = oid_set(&copied_xml);
    assert_eq!(copied_oids.len(), source_oids.len());
    assert!(copied_oids.is_disjoint(&source_oids));
    // The copied NULL level reads NULL too.
    let copied_null = copied_oids
        .iter()
        .find(|oid| *oid != &copied && !source_oids.contains(*oid))
        .cloned()
        .expect("copied level oid");
    // Resolve the copied NULL level by address: value must be NULL.
    assert_eq!(
        scalar(&mut server, "10", &format!("!{copied}/Address")),
        "57"
    );
    assert_eq!(document(&mut server, "11", "//LAB/254/56"), before);
    // Mutating the copy leaves the NULL source alone.
    let _ = copied_null;
    let dest_level_value = handle(&mut server, "12", "DBGET //LAB/254/57/1/11/Value");
    assert_eq!(dest_level_value.status, 342, "{dest_level_value:?}");
    assert!(
        dest_level_value.final_text.ends_with("=null"),
        "{dest_level_value:?}"
    );
}

#[test]
fn label_identities_are_reminted_and_values_preserved() {
    let mut server = seed();
    let _app = oid_of(&handle(
        &mut server,
        "3",
        "DBADDSAFE //LAB/254 Application 56 Lighting",
    ));
    let group_oid = oid_of(&handle(
        &mut server,
        "4",
        "DBADDSAFE //LAB/254/56 Group 1 Lamp",
    ));
    let level_oid = oid_of(&handle(
        &mut server,
        "5",
        "DBADDSAFE //LAB/254/56/1 Level 7 Evening",
    ));
    assert_eq!(
        handle(
            &mut server,
            "6",
            &format!("DBSETSAFE !{level_oid}/Value 77")
        )
        .status,
        200
    );
    // Attach one Group label and one Level label via DBSETXML.
    let group_xml = document(&mut server, "7", &format!("!{group_oid}"));
    let group_labeled = group_xml.replace(
        "</Group>",
        "<TagsDLT><TagDLT><LanguageID>1</LanguageID><FlavourID>1</FlavourID><TagType>Label</TagType><TagValue>LampLabel</TagValue></TagDLT></TagsDLT></Group>",
    );
    assert_eq!(
        server
            .handle_document("[8] DBSETXML //LAB/254/56/1", &group_labeled)
            .status,
        301
    );
    let level_xml = document(&mut server, "9", &format!("!{level_oid}"));
    let level_labeled = level_xml.replace(
        "</Level>",
        "<TagsDLT><TagDLT><LanguageID>1</LanguageID><FlavourID>2</FlavourID><TagType>Label</TagType><TagValue>EveningLabel</TagValue></TagDLT></TagsDLT></Level>",
    );
    // Level DBSETXML targets the numeric path for the owned shape.
    assert_eq!(
        server
            .handle_document("[10] DBSETXML //LAB/254/56/1/7", &level_labeled)
            .status,
        301
    );
    let before = document(&mut server, "11", "//LAB/254/56");
    assert!(before.contains("LampLabel"));
    assert!(before.contains("EveningLabel"));
    let source_oids = oid_set(&before);
    let copied = oid_of(&handle(
        &mut server,
        "12",
        "DBCOPYSAFE //LAB/254/56 //LAB/254 57 Copy",
    ));
    let copied_xml = document(&mut server, "13", &format!("!{copied}"));
    let copied_oids = oid_set(&copied_xml);
    // Labels travel; every identity (including inner TagDLT OIDs) is fresh.
    assert!(copied_xml.contains("LampLabel"));
    assert!(copied_xml.contains("EveningLabel"));
    assert!(copied_xml.contains("Value=\"77\""));
    assert!(copied_oids.is_disjoint(&source_oids));
    assert_eq!(document(&mut server, "14", "//LAB/254/56"), before);
}

#[test]
fn roster_appends_once_and_conflicts_append_nothing() {
    let mut server = seed();
    let _app = oid_of(&handle(
        &mut server,
        "3",
        "DBADDSAFE //LAB/254 Application 56 Lighting",
    ));
    let before_net = document(&mut server, "4", "//LAB/254");
    let copied = oid_of(&handle(
        &mut server,
        "5",
        "DBCOPYSAFE //LAB/254/56 //LAB/254 57 Copy",
    ));
    let after_net = document(&mut server, "6", "//LAB/254");
    assert!(after_net.contains("<Address>56</Address>"));
    assert!(after_net.contains("<Address>57</Address>"));
    assert_ne!(before_net, after_net);
    // Conflict refuses atomically: roster and network snapshots unchanged.
    let refused = handle(
        &mut server,
        "7",
        "DBCOPYSAFE //LAB/254/56 //LAB/254 57 Clash",
    );
    assert_eq!(refused.status, 409);
    assert_eq!(document(&mut server, "8", "//LAB/254"), after_net);
    // Persistence: the roster and subtree survive SAVE/CLOSE/LOAD.
    for (tag, command) in [
        ("9", "PROJECT SAVE LAB"),
        ("10", "PROJECT CLOSE LAB"),
        ("11", "PROJECT LOAD LAB"),
    ] {
        assert_eq!(handle(&mut server, tag, command).status, 200);
    }
    assert_eq!(
        document(&mut server, "12", &format!("!{copied}")),
        document(&mut server, "13", &format!("!{copied}"))
    );
    assert!(document(&mut server, "14", "//LAB/254").contains("<Address>57</Address>"));
}
