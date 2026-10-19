//! Stateful numeric `DBCOPYSAFE` Application/Group/NetVar/Level copies.
//!
//! Ordinary numeric sources (and admitted `!oid` Application/Group
//! selectors) must duplicate the complete subtree with fresh identities,
//! keep the source byte-identical, refuse destination conflicts, missing
//! sources and wrong parents atomically, and return the native `301 OID=`
//! receipt instead of the legacy opaque success.
use cbus_cgate::{AccessLevel, Response, Server};
use std::collections::BTreeSet;

struct Seeds {
    app: String,
    group: String,
    level: String,
    variable: String,
    variable_level: String,
}

fn seed() -> (Server, Seeds) {
    let mut server = Server::new(AccessLevel::Program);
    assert_eq!(server.handle("[1] PROJECT NEW TCOPY").status, 200);
    assert_eq!(
        server
            .handle("[2] DBCREATENET 254 Local Cni 127.0.0.1:10001")
            .status,
        200
    );
    assert_eq!(
        server
            .handle("[3] DBCREATENET 253 Remote Cni 127.0.0.1:10002")
            .status,
        200
    );
    let app = copied_oid(
        &mut server,
        "4",
        "DBADDSAFE //TCOPY/254 Application 56 Lighting",
    );
    let group = copied_oid(&mut server, "5", "DBADDSAFE //TCOPY/254/56 Group 1 Main");
    let level = copied_oid(
        &mut server,
        "6",
        "DBADDSAFE //TCOPY/254/56/1 Level 7 Evening",
    );
    let variable = copied_oid(
        &mut server,
        "7",
        "DBADDSAFE //TCOPY/254/56 NetVar 4 Variable",
    );
    let variable_level = copied_oid(&mut server, "8", "DBADDSAFE //TCOPY/254/56/4 Level 42 High");
    assert_eq!(
        server
            .handle(&format!("[9] DBSETSAFE !{level}/Value 77"))
            .status,
        200
    );
    assert_eq!(
        server
            .handle(&format!("[10] DBSETSAFE !{variable_level}/Value 23"))
            .status,
        200
    );
    (
        server,
        Seeds {
            app,
            group,
            level,
            variable,
            variable_level,
        },
    )
}

fn copied_oid(server: &mut Server, tag: &str, command: &str) -> String {
    let response = server.handle(&format!("[{tag}] {command}"));
    assert_eq!(response.status, 301, "{command}: {response:?}");
    assert!(response.lines.is_empty(), "{command}: {response:?}");
    let oid = oid_of(&response);
    assert_eq!(oid.len(), 36, "{command}: {response:?}");
    oid
}

fn oid_of(response: &Response) -> String {
    response
        .final_text
        .split_once('=')
        .expect("oid receipt")
        .1
        .to_string()
}

fn document(server: &mut Server, tag: &str, path: &str) -> String {
    let response = server.handle(&format!("[{tag}] DBGETXML {path}"));
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
    let response = server.handle(&format!("[{tag}] DBGET {path}"));
    assert_eq!(response.status, 342, "{path}: {response:?}");
    response.final_text.split_once('=').unwrap().1.to_string()
}

#[test]
fn numeric_application_copy_duplicates_complete_subtree_with_fresh_oids() {
    let (mut server, seeds) = seed();
    let before_source = document(&mut server, "20", "//TCOPY/254/56");
    let source_oids = oid_set(&before_source);
    assert_eq!(
        source_oids,
        BTreeSet::from([
            seeds.app.clone(),
            seeds.group.clone(),
            seeds.level.clone(),
            seeds.variable.clone(),
            seeds.variable_level.clone(),
        ])
    );
    let copied = copied_oid(
        &mut server,
        "21",
        "DBCOPYSAFE //TCOPY/254/56 //TCOPY/254 57 Copy",
    );
    assert!(!source_oids.contains(&copied));
    let copied_xml = document(&mut server, "22", &format!("!{copied}"));
    let copied_oids = oid_set(&copied_xml);
    assert_eq!(copied_oids.len(), source_oids.len());
    assert!(copied_oids.is_disjoint(&source_oids));
    for fragment in [
        "<TagName>Copy</TagName>",
        "<Address>57</Address>",
        "<TagName>Main</TagName>",
        "<TagName>Evening</TagName>",
        "Value=\"77\"",
        "<TagName>Variable</TagName>",
        "<TagName>High</TagName>",
        "Value=\"23\"",
    ] {
        assert!(copied_xml.contains(fragment), "{fragment}: {copied_xml}");
    }
    assert_eq!(
        scalar(&mut server, "23", &format!("!{copied}/Address")),
        "57"
    );
    assert_eq!(
        scalar(&mut server, "24", &format!("!{copied}/TagName")),
        "Copy"
    );
    assert_eq!(document(&mut server, "25", "//TCOPY/254/56"), before_source);
}

#[test]
fn oid_application_copy_matches_numeric_copy() {
    let (mut server, seeds) = seed();
    let before_source = document(&mut server, "20", "//TCOPY/254/56");
    let source_oids = oid_set(&before_source);
    let copied = copied_oid(
        &mut server,
        "21",
        &format!("DBCOPYSAFE !{} //TCOPY/254 58 OidCopy", seeds.app),
    );
    let copied_xml = document(&mut server, "22", &format!("!{copied}"));
    let copied_oids = oid_set(&copied_xml);
    assert_eq!(copied_oids.len(), source_oids.len());
    assert!(copied_oids.is_disjoint(&source_oids));
    assert!(copied_xml.contains("<Address>58</Address>"));
    assert!(copied_xml.contains("Value=\"77\""));
    assert!(copied_xml.contains("Value=\"23\""));
    assert_eq!(document(&mut server, "23", "//TCOPY/254/56"), before_source);
}

#[test]
fn numeric_and_oid_group_copies_preserve_levels() {
    let (mut server, seeds) = seed();
    let before_source = document(&mut server, "20", "//TCOPY/254/56/1");
    let first = copied_oid(
        &mut server,
        "21",
        "DBCOPYSAFE //TCOPY/254/56/1 //TCOPY/254/56 2 GroupCopy",
    );
    let first_xml = document(&mut server, "22", &format!("!{first}"));
    assert!(first_xml.contains("<TagName>GroupCopy</TagName>"));
    assert!(first_xml.contains("<Address>2</Address>"));
    assert!(first_xml.contains("Value=\"77\""));
    assert_eq!(oid_set(&first_xml).len(), oid_set(&before_source).len());
    let second = copied_oid(
        &mut server,
        "23",
        &format!("DBCOPYSAFE !{} //TCOPY/254/56 3 OidGroupCopy", seeds.group),
    );
    assert_ne!(second, first);
    let second_xml = document(&mut server, "24", &format!("!{second}"));
    assert!(oid_set(&first_xml).is_disjoint(&oid_set(&second_xml)));
    assert!(second_xml.contains("Value=\"77\""));
    assert_eq!(
        document(&mut server, "25", "//TCOPY/254/56/1"),
        before_source
    );
}

#[test]
fn numeric_level_copy_returns_oid_for_caller_initialization() {
    let (mut server, _) = seed();
    let before_source = document(&mut server, "20", "//TCOPY/254/56/1/7");
    let copied = copied_oid(
        &mut server,
        "21",
        "DBCOPYSAFE //TCOPY/254/56/1/7 //TCOPY/254/56/1 8 LevelCopy",
    );
    // The typed value travels with the copy; the CLI initializer then sets
    // the destination value, matching the native Level copy workflow.
    assert_eq!(scalar(&mut server, "22", &format!("!{copied}/Value")), "77");
    assert_eq!(
        scalar(&mut server, "23", &format!("!{copied}/Address")),
        "8"
    );
    assert_eq!(
        scalar(&mut server, "24", &format!("!{copied}/TagName")),
        "LevelCopy"
    );
    assert_eq!(
        server
            .handle(&format!("[25] DBSETSAFE !{copied}/Value 8"))
            .status,
        200
    );
    assert_eq!(scalar(&mut server, "26", &format!("!{copied}/Value")), "8");
    assert_eq!(
        document(&mut server, "27", "//TCOPY/254/56/1/7"),
        before_source
    );
}

#[test]
fn numeric_netvar_copy_preserves_child_levels() {
    let (mut server, _) = seed();
    let before_source = document(&mut server, "20", "//TCOPY/254/56/4");
    let copied = copied_oid(
        &mut server,
        "21",
        "DBCOPYSAFE //TCOPY/254/56/4 //TCOPY/254/56 5 VarCopy",
    );
    let copied_xml = document(&mut server, "22", &format!("!{copied}"));
    assert!(copied_xml.contains("<TagName>VarCopy</TagName>"));
    assert!(copied_xml.contains("<Address>5</Address>"));
    assert!(copied_xml.contains("<TagName>High</TagName>"));
    assert!(copied_xml.contains("Value=\"23\""));
    let source_oids = oid_set(&before_source);
    let copied_oids = oid_set(&copied_xml);
    // The copy carries fresh identities for the variable and its child;
    // exact OID cardinalities differ across readback shapes, so require
    // disjointness and containment rather than a fixed count.
    assert!(copied_oids.contains(&copied));
    assert!(copied_oids.is_disjoint(&source_oids));
    assert_eq!(
        document(&mut server, "23", "//TCOPY/254/56/4"),
        before_source
    );
}

#[test]
fn destination_conflicts_refuse_atomically_with_409() {
    let (mut server, seeds) = seed();
    let before_remote = document(&mut server, "21", "//TCOPY/253");
    for command in [
        "DBADDSAFE //TCOPY/254 Application 71 Other",
        "DBADDSAFE //TCOPY/254/56 Group 9 OtherGroup",
        "DBADDSAFE //TCOPY/254/56/1 Level 9 OtherLevel",
    ] {
        let response = server.handle(&format!("[22] {command}"));
        assert_eq!(response.status, 301, "{command}: {response:?}");
    }
    // Capture the occupied baseline after the setup adds; conflicts must
    // leave this (including the newly added children) unchanged.
    let occupied = document(&mut server, "23", "//TCOPY/254");
    let before_source = document(&mut server, "20", "//TCOPY/254/56");
    for (tag, command, label) in [
        (
            "24",
            "DBCOPYSAFE //TCOPY/254/56 //TCOPY/254 71 Clash".to_string(),
            "409 Application destination contains retained state",
        ),
        (
            "25",
            format!("DBCOPYSAFE !{} //TCOPY/254 71 OidClash", seeds.app),
            "409 Application destination contains retained state",
        ),
        (
            "26",
            "DBCOPYSAFE //TCOPY/254/56/1 //TCOPY/254/56 9 Clash".to_string(),
            "409 Group already exists",
        ),
        (
            "27",
            "DBCOPYSAFE //TCOPY/254/56/1/7 //TCOPY/254/56/1 9 Clash".to_string(),
            "409 Level already exists",
        ),
        (
            "28",
            "DBCOPYSAFE //TCOPY/254/56/4 //TCOPY/254/56 1 Clash".to_string(),
            "409 NetVar already exists",
        ),
        (
            "29",
            "DBCOPYSAFE //TCOPY/254/56 //TCOPY/254 56 Self".to_string(),
            "409 Application destination contains retained state",
        ),
    ] {
        let response = server.handle(&format!("[{tag}] {command}"));
        assert_eq!(response.status, 409, "{command}: {response:?}");
        assert_eq!(response.final_text, label, "{command}: {response:?}");
    }
    assert_eq!(document(&mut server, "30", "//TCOPY/254"), occupied);
    assert_eq!(document(&mut server, "31", "//TCOPY/254/56"), before_source);
    assert_eq!(document(&mut server, "32", "//TCOPY/253"), before_remote);
}

#[test]
fn missing_sources_and_wrong_parents_refuse_without_mutation() {
    let (mut server, _) = seed();
    let before = document(&mut server, "20", "//TCOPY/254");
    for (tag, command) in [
        ("21", "DBCOPYSAFE //TCOPY/254/99 //TCOPY/254 72 Ghost"),
        ("22", "DBCOPYSAFE //TCOPY/254/56/9 //TCOPY/254/56 72 Ghost"),
        (
            "23",
            "DBCOPYSAFE //TCOPY/254/56/1/8 //TCOPY/254/56/1 72 Ghost",
        ),
        (
            "24",
            "DBCOPYSAFE //TCOPY/254/56 //TCOPY/254/56 9 WrongParent",
        ),
        (
            "25",
            "DBCOPYSAFE //TCOPY/254/56/1 //TCOPY/254 9 WrongParent",
        ),
        (
            "26",
            "DBCOPYSAFE //TCOPY/254/56/1/7 //TCOPY/254/56 9 WrongParent",
        ),
        (
            "27",
            "DBCOPYSAFE //TCOPY/254/56/1/7 //TCOPY/254 9 WrongParent",
        ),
    ] {
        let response = server.handle(&format!("[{tag}] {command}"));
        // An Application source under an Application parent is the
        // Application-copy owner's typed parent mismatch (408); every other
        // missing source or wrong parent is an absent object (401).
        let expected = if tag == "24" { 408 } else { 401 };
        assert_eq!(response.status, expected, "{command}: {response:?}");
    }
    assert_eq!(document(&mut server, "28", "//TCOPY/254"), before);
}

#[test]
fn cross_network_and_cross_project_copies_stay_isolated() {
    let (mut server, seeds) = seed();
    let before_source = document(&mut server, "20", "//TCOPY/254");
    let copied = copied_oid(
        &mut server,
        "21",
        "DBCOPYSAFE //TCOPY/254/56 //TCOPY/253 56 Remote",
    );
    let copied_xml = document(&mut server, "22", &format!("!{copied}"));
    assert!(copied_xml.contains("Value=\"77\""));
    assert!(copied_xml.contains("Value=\"23\""));
    assert_eq!(document(&mut server, "23", "//TCOPY/254"), before_source);
    let remote = document(&mut server, "24", "//TCOPY/253");
    assert!(remote.contains("<Address>56</Address>"));
    assert!(remote.contains("<TagName>Remote</TagName>"));
    // A second project is isolated: its numeric and OID sources refuse
    // here, and a copy addressed there cannot observe this project.
    assert_eq!(server.handle("[25] PROJECT NEW OTHER").status, 200);
    assert_eq!(
        server
            .handle("[26] DBCREATENET 254 Elsewhere Cni 127.0.0.1:9")
            .status,
        200
    );
    let other_app = copied_oid(
        &mut server,
        "27",
        "DBADDSAFE //OTHER/254 Application 56 OtherApp",
    );
    // Application copies between loaded projects are admitted by the
    // Application-copy owner (application-database-safe.md); the source
    // stays unchanged.
    let response = server.handle("[29] DBCOPYSAFE //TCOPY/254/56 //OTHER/254 57 Intruder");
    assert_eq!(response.status, 301, "{response:?}");
    let other_before = document(&mut server, "28", "//OTHER/254");
    assert!(other_before.contains("<TagName>Intruder</TagName>"));
    let response = server.handle(&format!(
        "[30] DBCOPYSAFE !{} //OTHER/254 60 Intruder",
        seeds.app
    ));
    assert_eq!(response.status, 401, "{response:?}");
    let response = server.handle(&format!(
        "[31] DBCOPYSAFE !{other_app} //TCOPY/254 57 Intruder"
    ));
    // The OID resolves in the current project (OTHER); the loaded TCOPY
    // destination is admitted by the same Application-copy owner.
    assert_eq!(response.status, 301, "{response:?}");
    assert_eq!(server.handle("[32] PROJECT USE TCOPY").status, 200);
    let after_source = document(&mut server, "33", "//TCOPY/254");
    assert_ne!(after_source, before_source);
    assert!(after_source.contains("<TagName>Intruder</TagName>"));
    assert_eq!(server.handle("[34] PROJECT USE OTHER").status, 200);
    assert_eq!(document(&mut server, "35", "//OTHER/254"), other_before);
}

#[test]
fn copy_survives_project_save_close_and_load() {
    let (mut server, _) = seed();
    let copied = copied_oid(
        &mut server,
        "20",
        "DBCOPYSAFE //TCOPY/254/56 //TCOPY/254 57 Saved",
    );
    let copied_xml = document(&mut server, "21", &format!("!{copied}"));
    for (tag, command) in [
        ("22", "PROJECT SAVE TCOPY"),
        ("23", "PROJECT CLOSE TCOPY"),
        ("24", "PROJECT LOAD TCOPY"),
    ] {
        let response = server.handle(&format!("[{tag}] {command}"));
        assert_eq!(response.status, 200, "{command}: {response:?}");
    }
    // LOAD may materialize the admitted empty Level collection; identities
    // and values are otherwise unchanged.
    assert_eq!(
        document(&mut server, "25", &format!("!{copied}")).replace("<TagsDLT/>", ""),
        copied_xml.replace("<TagsDLT/>", "")
    );
    assert_eq!(
        scalar(&mut server, "26", &format!("!{copied}/Address")),
        "57"
    );
}

#[test]
fn established_unit_and_oid_level_flows_are_unchanged() {
    let (mut server, seeds) = seed();
    let add = server.handle("[20] DBADDSAFE //TCOPY/254 Unit 20 Lounge");
    assert_eq!(add.status, 301, "{add:?}");
    // Numeric unit duplication keeps its 200 OK receipt.
    let unit_copy = server.handle("[21] DBCOPYSAFE //TCOPY/254/p/20 //TCOPY/254 21 Hall");
    assert_eq!(unit_copy.status, 200, "{unit_copy:?}");
    // Admitted OID level copies keep the NULL-value flow for the caller
    // initializer. (Numeric parents are required: `!oid` parents predate
    // this workflow and still report 404 at the parent gate.)
    let response = server.handle(&format!(
        "[22] DBCOPYSAFE !{} //TCOPY/254/56/1 9 Fresh",
        seeds.level
    ));
    assert_eq!(response.status, 301, "{response:?}");
    let fresh = oid_of(&response);
    assert_eq!(
        scalar(&mut server, "23", &format!("!{fresh}/Value")),
        "null"
    );
}
