//! Source-composed language objects in the owned model; native receipts and
//! GUI callback execution remain separate acceptance obligations.
use cbus_cgate::{format_response, AccessLevel, Server};

fn vector() -> serde_json::Value {
    serde_json::from_str(include_str!(
        "../../testdata/vectors/cgate_network_languages.json"
    ))
    .unwrap()
}

fn seed() -> (Server, String) {
    let mut server = Server::new(AccessLevel::Program);
    for command in vector()["seed"].as_array().unwrap() {
        let response = server.handle(&format!("[seed] {}", command.as_str().unwrap()));
        assert_eq!(response.status, 200, "{response:?}");
    }
    let (oid, _) = network_identity(&mut server);
    (server, oid)
}

fn network_identity(server: &mut Server) -> (String, String) {
    let response = server.handle("[identity] DBGETXML //LANG/254");
    assert_eq!(response.status, 200, "{response:?}");
    let document = response.lines[0].strip_prefix("347-").unwrap();
    let parsed = roxmltree::Document::parse(document).unwrap();
    let root = parsed.root_element();
    let oid = root
        .children()
        .find(|node| node.has_tag_name("OID"))
        .unwrap()
        .text()
        .unwrap()
        .to_string();
    let interface = root
        .children()
        .find(|node| node.has_tag_name("Interface"))
        .unwrap();
    let interface_oid = interface
        .children()
        .find(|node| node.has_tag_name("OID"))
        .unwrap()
        .text()
        .unwrap()
        .to_string();
    (oid, interface_oid)
}

fn add(server: &mut Server, parent: &str, kind: &str) -> String {
    let response = server.handle(&format!("[add] DBADD {parent} {kind}"));
    assert_eq!(response.status, 301, "{response:?}");
    assert!(response.lines.is_empty());
    response
        .final_text
        .strip_prefix("301 OID=")
        .unwrap()
        .to_string()
}

fn xml(server: &mut Server) -> String {
    let response = server.handle("[xml] DBGETXML //LANG");
    assert_eq!(response.status, 200, "{response:?}");
    response.lines.join("\n")
}

#[test]
fn network_languages_creation_oid_readback_and_saved_reload() {
    let (mut server, network) = seed();
    let initial = xml(&mut server);
    assert_eq!(
        server
            .handle(&format!("[missing] DBGET !{network}/Languages"))
            .status,
        401
    );
    assert_eq!(xml(&mut server), initial);
    let collection = add(&mut server, &format!("!{network}"), "Languages");
    let mut issued = Vec::new();
    for row in vector()["rows"].as_array().unwrap() {
        let oid = add(&mut server, &format!("!{network}/Languages"), "Language");
        for (field, value) in [
            ("ID", row["id"].as_str().unwrap()),
            ("TagValue", row["name"].as_str().unwrap()),
        ] {
            let response = server.handle(&format!("[set] DBSET !{oid}/{field} {value}"));
            assert_eq!(
                format_response(&response),
                vector()["setter_reply"].as_str().unwrap()
            );
            let read = server.handle(&format!("[read] DBGET !{oid}/{field}"));
            assert_eq!(
                format_response(&read),
                format!("[read] 342 !{oid}/{field}={value}\n")
            );
        }
        issued.push(oid);
    }
    let after = xml(&mut server);
    assert!(after.contains("Français &amp; 日本語"));
    for oid in &issued {
        assert!(after.contains(oid));
    }
    assert!(after.contains(&collection));
    let rows = server.handle(&format!("[list] DBGET !{collection}/Language/OID"));
    assert_eq!(rows.status, 342);
    assert_eq!(rows.lines.len(), 2);
    for (index, oid) in issued.iter().enumerate() {
        assert!(format_response(&rows).contains(&format!("Language[{}]/OID={oid}", index + 1)));
    }
    for command in [
        "PROJECT SAVE LANG",
        "PROJECT CLOSE LANG",
        "PROJECT LOAD LANG",
        "PROJECT USE LANG",
    ] {
        let response = server.handle(&format!("[project] {command}"));
        assert_eq!(response.status, 200, "{response:?}");
    }
    assert_eq!(xml(&mut server), after);
    for (row, oid) in vector()["rows"].as_array().unwrap().iter().zip(issued) {
        let read = server.handle(&format!("[read] DBGET !{oid}/ID"));
        assert_eq!(
            format_response(&read),
            row["id_reply"].as_str().unwrap().replace("{oid}", &oid)
        );
    }
}

#[test]
fn network_languages_scalar_refusals_delete_and_foreign_project_preserve_owners() {
    let (mut server, network) = seed();
    let collection = add(&mut server, &format!("!{network}"), "Languages");
    let first = add(&mut server, &format!("!{collection}"), "Language");
    let second = add(&mut server, &format!("!{collection}"), "Language");
    for (oid, id) in [(&first, "1"), (&second, "2")] {
        assert_eq!(
            server.handle(&format!("[set] DBSET !{oid}/ID {id}")).status,
            200
        );
        assert_eq!(
            server
                .handle(&format!("[set] DBSET !{oid}/TagValue Retained {id}"))
                .status,
            200
        );
    }
    let before = xml(&mut server);
    for verb in ["DBSET", "DBSETSAFE"] {
        for invalid in ["\u{1}", "\u{b}", "\u{fffe}", "\u{ffff}"] {
            let response = server.handle(&format!("[invalid] {verb} !{first}/TagValue {invalid}"));
            assert_eq!(
                format_response(&response),
                if invalid == "\u{1}" || invalid == "\u{b}" {
                    "400 C-Gate command must be a single line without control characters\n"
                } else {
                    "[invalid] 408 Operation failed: Language value is not representable in XML\n"
                }
            );
            assert_eq!(xml(&mut server), before);
            assert_eq!(
                server
                    .handle(&format!("[read] DBGET !{first}/TagValue"))
                    .final_text,
                format!("342 !{first}/TagValue=Retained 1")
            );
        }
    }
    for refusal in vector()["refusals"].as_array().unwrap() {
        let command = refusal["command"]
            .as_str()
            .unwrap()
            .replace("{oid}", &first);
        assert_eq!(
            format_response(&server.handle(&format!("[refuse] {command}"))),
            refusal["reply"].as_str().unwrap()
        );
        assert_eq!(xml(&mut server), before);
    }
    assert_eq!(
        server
            .handle(&format!("[duplicate] DBADD !{network} Languages"))
            .status,
        409
    );
    assert_eq!(xml(&mut server), before);
    assert_eq!(server.handle("[other] PROJECT NEW OTHER").status, 200);
    assert_eq!(
        server
            .handle(&format!("[foreign] DBSET !{first}/ID 9"))
            .status,
        401
    );
    assert_eq!(
        server
            .handle(&format!("[foreign] DBGET !{first}/TagValue"))
            .status,
        401
    );
    assert_eq!(server.handle("[use] PROJECT USE LANG").status, 200);
    assert_eq!(xml(&mut server), before);
    assert_eq!(
        server.handle(&format!("[delete] DBDELETE !{first}")).status,
        200
    );
    let after = xml(&mut server);
    assert!(!after.contains(&first));
    assert!(after.contains(&second));
    assert_eq!(
        server
            .handle(&format!("[deleted] DBGET !{first}/OID"))
            .status,
        401
    );
    assert_eq!(
        server
            .handle(&format!("[delete] DBDELETE !{collection}"))
            .status,
        200
    );
    assert!(!xml(&mut server).contains("<Languages>"));
    assert_eq!(
        server
            .handle(&format!("[deleted] DBGET !{second}/OID"))
            .status,
        401
    );
}

#[test]
fn network_languages_complete_xml_admission_and_atomic_malformed_refusal() {
    let (mut server, network) = seed();
    let (_, interface) = network_identity(&mut server);
    let root = format!("<Network><OID>{network}</OID><TagName>Local</TagName><Address>254</Address><NetworkNumber>254</NetworkNumber><Interface><OID>{interface}</OID><InterfaceType>Cni</InterfaceType><InterfaceAddress>127.0.0.1:1</InterfaceAddress></Interface>{{languages}}</Network>");
    let languages = "<Languages><OID>11000000-0000-4000-8000-000000000001</OID><Language><OID>11000000-0000-4000-8000-000000000002</OID><ID>0</ID><TagValue>1</TagValue></Language><Language><OID>11000000-0000-4000-8000-000000000003</OID><ID>1</ID><TagValue>English</TagValue></Language></Languages>";
    let response = server.handle_document(
        "[import] DBSETXML //LANG/254",
        &root.replace("{languages}", languages),
    );
    assert_eq!(response.status, 301, "{response:?}");
    let before = xml(&mut server);
    assert!(before.contains(languages));
    for malformed in [
        languages.replace("<ID>1</ID>", "<ID>invalid</ID>"),
        languages.replace("<ID>1</ID>", "<ID>1</ID><ID>2</ID>"),
        format!("{languages}{languages}"),
        languages.replace(
            "<TagValue>English</TagValue>",
            "<TagValue><Nested/></TagValue>",
        ),
        languages.replace("000000000003", "000000000002"),
    ] {
        let response = server.handle_document(
            "[bad] DBSETXML //LANG/254",
            &root.replace("{languages}", &malformed),
        );
        assert!(response.status >= 400, "{response:?}");
        assert_eq!(xml(&mut server), before);
    }
    let response =
        server.handle("[rename] DBSET !11000000-0000-4000-8000-000000000003/TagValue New name");
    assert_eq!(response.status, 200, "{response:?}");
    assert!(xml(&mut server).contains("<TagValue>New name</TagValue>"));
}
