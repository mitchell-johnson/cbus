//! Owned Application-copy interactions grounded in the target3.4 HELP* contract.
//! These are regression oracles, not fresh native mutation transcripts.
use cbus_cgate::{AccessLevel, Server};
use std::collections::BTreeSet;

fn vector() -> serde_json::Value {
    serde_json::from_str(include_str!(
        "../../testdata/vectors/application_copy_safe_owned.json"
    ))
    .unwrap()
}
fn seed() -> Server {
    let mut server = Server::new(AccessLevel::Program);
    assert_eq!(server.handle("[new] PROJECT NEW COPY").status, 200);
    assert_eq!(
        server
            .handle("[net] DBCREATENET 254 Local Cni nowhere")
            .status,
        200
    );
    assert_eq!(
        server
            .handle("[dest] DBCREATENET 253 Other Cni nowhere")
            .status,
        200
    );
    for (address, name) in [
        (72, "A72"),
        (0, "Zero"),
        (71, "A71"),
        (66, "A66"),
        (56, "Source"),
    ] {
        assert_eq!(
            server
                .handle(&format!(
                    "[add] DBADDSAFE //COPY/254 Application {address} {name}"
                ))
                .status,
            301
        );
    }
    let literal = vector();
    let expected = literal["source_xml"].as_str().unwrap();
    let parsed = roxmltree::Document::parse(expected).unwrap();
    let null_level = parsed
        .descendants()
        .find(|node| node.has_tag_name("Level") && node.attribute("Value").is_none())
        .unwrap();
    let placeholder = null_level
        .children()
        .find(|node| node.has_tag_name("OID"))
        .unwrap()
        .text()
        .unwrap();
    // Complete DBSETXML requires numeric Value. The public Level constructor
    // separately establishes NULL, with a fresh OID and no label collection.
    let mut admitted = expected.to_string();
    admitted.replace_range(null_level.range(), "");
    let replaced = server.handle_document("[source] DBSETXML //COPY/254/56", &admitted);
    assert_eq!(replaced.status, 301, "{replaced:?}");
    assert_eq!(
        replaced.final_text,
        "301 OID=aaaaaaaa-aaaa-4aaa-8aaa-000000000056"
    );
    let created = server.handle("[null] DBADDSAFE //COPY/254/56/7 Level 3 Null level");
    assert_eq!(created.status, 301, "{created:?}");
    let issued = created.final_text.strip_prefix("301 OID=").unwrap();
    assert_ne!(issued, placeholder);
    let identity = server.handle(&format!("[identity] DBGET !{issued}/OID"));
    assert_eq!(identity.status, 342, "{identity:?}");
    assert!(identity.final_text.ends_with(&format!("={issued}")));
    let value = server.handle(&format!("[value] DBGET !{issued}/Value"));
    assert_eq!(value.status, 342, "{value:?}");
    assert!(value.final_text.ends_with("=null"));
    let current = xml(&mut server, "//COPY/254/56");
    assert_eq!(shape(&current), shape(expected));
    let mut expected_oids = oids(expected);
    assert!(expected_oids.remove(placeholder));
    assert!(expected_oids.insert(issued.to_string()));
    assert_eq!(oids(&current), expected_oids);
    assert_eq!(expected_oids.len(), 9);
    server
}
fn xml(server: &mut Server, path: &str) -> String {
    if let Some(project) = path
        .strip_prefix("//")
        .and_then(|tail| tail.split('/').next())
    {
        assert_eq!(
            server
                .handle(&format!("[use] PROJECT USE {project}"))
                .status,
            200
        );
    }
    let result = server.handle(&format!("[xml] DBGETXML {path}"));
    assert_eq!(result.status, 200, "{result:?}");
    result.lines[0].strip_prefix("347-").unwrap().to_string()
}
fn shape(text: &str) -> String {
    let document = roxmltree::Document::parse(text).unwrap();
    let mut output = text.to_string();
    for node in document
        .descendants()
        .filter(|node| node.has_tag_name("OID"))
        .collect::<Vec<_>>()
        .into_iter()
        .rev()
    {
        output.replace_range(node.range(), "<OID>IDENTITY</OID>");
    }
    output
}
// The copied Level is a pending XML owner. Existing SAVE/LOAD handling
// appends empty tags on LOAD, unlike the original plain NULL constructor.
// Preserve the entire document and insert only the exact copied Group7/Level3.
fn copied_null_level_after_load(text: &str, application: u8) -> String {
    let document = roxmltree::Document::parse(text).unwrap();
    let address = application.to_string();
    let applications = document
        .descendants()
        .filter(|node| {
            node.has_tag_name("Application")
                && node.children().any(|child| {
                    child.has_tag_name("Address") && child.text() == Some(address.as_str())
                })
        })
        .collect::<Vec<_>>();
    assert_eq!(applications.len(), 1);
    let group = applications[0]
        .children()
        .find(|node| {
            node.has_tag_name("Group")
                && node
                    .children()
                    .any(|child| child.has_tag_name("Address") && child.text() == Some("7"))
        })
        .unwrap();
    let levels = group
        .children()
        .filter(|node| {
            node.has_tag_name("Level")
                && node
                    .children()
                    .any(|child| child.has_tag_name("Address") && child.text() == Some("3"))
        })
        .collect::<Vec<_>>();
    assert_eq!(levels.len(), 1);
    let level = levels[0];
    assert!(level.attribute("Value").is_none());
    assert_eq!(
        level
            .children()
            .filter(|node| node.is_element())
            .map(|node| node.tag_name().name())
            .collect::<Vec<_>>(),
        vec!["OID", "TagName", "Address"]
    );
    let end = level.range().end - "</Level>".len();
    assert_eq!(&text[end..level.range().end], "</Level>");
    let mut expected = text.to_string();
    expected.insert_str(end, "<TagsDLT/>");
    assert_eq!(oids(&expected), oids(text));
    expected
}
fn oids(text: &str) -> BTreeSet<String> {
    roxmltree::Document::parse(text)
        .unwrap()
        .descendants()
        .filter(|node| node.has_tag_name("OID"))
        .map(|node| node.text().unwrap().to_string())
        .collect()
}
fn order(server: &mut Server, network: u8) -> Vec<u64> {
    let result = server.handle(&format!("[order] CGL EXPORT COPY {network} *"));
    assert_eq!(result.status, 344, "{result:?}");
    let payload = result
        .lines
        .iter()
        .find_map(|line| line.strip_prefix("347-"))
        .unwrap();
    let value: serde_json::Value = serde_json::from_str(payload).unwrap();
    value["networks"][0]["applications"]
        .as_array()
        .unwrap()
        .iter()
        .map(|app| app["address"].as_u64().unwrap())
        .collect()
}
fn assert_copy(
    server: &mut Server,
    source: &str,
    destination: &str,
    address: u8,
    name: &str,
    receipt: &str,
) {
    let before = xml(server, source);
    let copied = xml(server, destination);
    let expected = before
        .replacen(
            "<TagName>Source</TagName>",
            &format!("<TagName>{name}</TagName>"),
            1,
        )
        .replacen(
            "<Address>56</Address>",
            &format!("<Address>{address}</Address>"),
            1,
        );
    assert_eq!(shape(&copied), shape(&expected));
    let old = oids(&before);
    let new = oids(&copied);
    assert_eq!(old.len(), 9);
    assert_eq!(new.len(), 9);
    assert!(old.is_disjoint(&new));
    assert!(copied.contains(&format!("<OID>{receipt}</OID>")));
    assert_eq!(xml(server, source), before);
}

#[test]
fn numeric_whole_application_retains_children_null_values_labels_and_causal_order() {
    let mut server = seed();
    let before = xml(&mut server, "//COPY/254/56");
    assert_eq!(
        shape(&before),
        shape(vector()["source_xml"].as_str().unwrap())
    );
    let result = server.handle("[copy] DBCOPYSAFE //COPY/254/56 //COPY/254 80 Copied source");
    assert_eq!(result.status, 301, "{result:?}");
    let receipt = result.final_text.strip_prefix("301 OID=").unwrap();
    assert_copy(
        &mut server,
        "//COPY/254/56",
        "//COPY/254/80",
        80,
        "Copied source",
        receipt,
    );
    assert_eq!(order(&mut server, 254), vec![72, 0, 71, 66, 56, 80]);
}

#[test]
fn unique_application_and_network_oids_address_the_complete_same_owner() {
    let mut server = seed();
    let network = xml(&mut server, "//COPY/253");
    let doc = roxmltree::Document::parse(&network).unwrap();
    let oid = doc
        .root_element()
        .children()
        .find(|node| node.has_tag_name("OID"))
        .unwrap()
        .text()
        .unwrap();
    let result = server.handle(&format!(
        "[copy] DBCOPYSAFE !aaaaaaaa-aaaa-4aaa-8aaa-000000000056 !{oid} 30 Copied  source"
    ));
    assert_eq!(result.status, 301, "{result:?}");
    assert_copy(
        &mut server,
        "//COPY/254/56",
        "//COPY/253/30",
        30,
        "Copied  source",
        result.final_text.strip_prefix("301 OID=").unwrap(),
    );
    assert_eq!(order(&mut server, 254), vec![72, 0, 71, 66, 56]);
    assert_eq!(order(&mut server, 253), vec![30]);
}

#[test]
fn cross_project_copy_isolated_from_source_and_can_be_saved_and_reopened() {
    let mut server = seed();
    let source = xml(&mut server, "//COPY");
    assert_eq!(server.handle("[other] PROJECT NEW OTHER").status, 200);
    assert_eq!(
        server
            .handle("[net] DBCREATENET 1 Target Cni nowhere")
            .status,
        200
    );
    assert_eq!(server.handle("[source] PROJECT USE COPY").status, 200);
    let result = server.handle("[copy] DBCOPYSAFE //COPY/254/56 //OTHER/1 0 Cross");
    assert_eq!(result.status, 301, "{result:?}");
    assert_eq!(xml(&mut server, "//COPY"), source);
    assert_copy(
        &mut server,
        "//COPY/254/56",
        "//OTHER/1/0",
        0,
        "Cross",
        result.final_text.strip_prefix("301 OID=").unwrap(),
    );
    assert_eq!(server.handle("[use] PROJECT USE OTHER").status, 200);
    assert_eq!(server.handle("[save] PROJECT SAVE OTHER").status, 200);
    let destination = xml(&mut server, "//OTHER");
    assert_eq!(server.handle("[close] PROJECT CLOSE OTHER").status, 200);
    assert_eq!(server.handle("[load] PROJECT LOAD OTHER").status, 200);
    let loaded = xml(&mut server, "//OTHER");
    assert_eq!(loaded, copied_null_level_after_load(&destination, 0));
    let loaded_document = roxmltree::Document::parse(&loaded).unwrap();
    let null_oid = loaded_document
        .descendants()
        .find(|node| node.has_tag_name("Level") && node.attribute("Value").is_none())
        .unwrap()
        .children()
        .find(|node| node.has_tag_name("OID"))
        .unwrap()
        .text()
        .unwrap();
    let null_value = server.handle(&format!("[null-after-load] DBGET !{null_oid}/Value"));
    assert_eq!(null_value.status, 342, "{null_value:?}");
    assert!(null_value.final_text.ends_with("=null"));
    assert_eq!(
        server
            .handle("[change] DBSETSAFE //OTHER/1/0/8/4/Value 99")
            .status,
        200
    );
    assert_eq!(xml(&mut server, "//COPY"), source);
}

#[test]
fn copy_has_no_implicit_project_save_or_inverse_cleanup() {
    let mut server = seed();
    assert_eq!(server.handle("[save] PROJECT SAVE COPY").status, 200);
    let before = xml(&mut server, "//COPY");
    assert_eq!(
        server
            .handle("[copy] DBCOPYSAFE //COPY/254/56 //COPY/254 80 Copied")
            .status,
        301
    );
    assert_ne!(xml(&mut server, "//COPY"), before);
    assert_eq!(server.handle("[close] PROJECT CLOSE COPY").status, 200);
    assert_eq!(server.handle("[load] PROJECT LOAD COPY").status, 200);
    assert_eq!(xml(&mut server, "//COPY"), before);
    assert_eq!(order(&mut server, 254), vec![72, 0, 71, 66, 56]);
}

#[test]
fn sibling_address_and_tagname_conflicts_refuse_atomically() {
    let mut server = seed();
    assert_eq!(
        server
            .handle("[copy] DBCOPYSAFE //COPY/254/56 //COPY/254 80 Copied")
            .status,
        301
    );
    let before = xml(&mut server, "//COPY");
    for command in [
        "DBCOPYSAFE //COPY/254/56 //COPY/254 80 Other",
        "DBCOPYSAFE //COPY/254/56 //COPY/254 81 Copied",
    ] {
        assert_eq!(server.handle(&format!("[bad] {command}")).status, 409);
        assert_eq!(xml(&mut server, "//COPY"), before);
    }
}

#[test]
fn strict_decimal_destination_and_parent_type_failures_do_not_mutate() {
    for (parent, address, code) in [
        ("//COPY/253", "+1", 400),
        ("//COPY/253", "-1", 400),
        ("//COPY/253", "256", 400),
        ("//COPY/254/56", "81", 408),
        ("//COPY/252", "81", 401),
    ] {
        let mut server = seed();
        let before = xml(&mut server, "//COPY");
        assert_eq!(
            server
                .handle(&format!(
                    "[bad] DBCOPYSAFE //COPY/254/56 {parent} {address} Copy"
                ))
                .status,
            code
        );
        assert_eq!(xml(&mut server, "//COPY"), before);
    }
}

#[test]
fn numeric_leading_zero_inputs_are_normalized_without_changing_the_field_rule() {
    let mut server = seed();
    let result = server.handle("[copy] DBCOPYSAFE //COPY/0254/056 //COPY/0253 030 Copy");
    assert_eq!(result.status, 301, "{result:?}");
    assert_copy(
        &mut server,
        "//COPY/254/56",
        "//COPY/253/30",
        30,
        "Copy",
        result.final_text.strip_prefix("301 OID=").unwrap(),
    );
}
