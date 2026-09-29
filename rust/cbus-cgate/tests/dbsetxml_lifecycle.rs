//! Replays the owned native C-Gate 3.4 DBSETXML unsaved-change lifecycle.
//!
//! `native_cgate_dbsetxml_lifecycle.json` shows that DBSETXML and DBSET edit
//! only the loaded project: CLOSE then LOAD without SAVE restores the saved
//! tree, SAVE makes the edit survive CLOSE/LOAD, and LOAD of an already
//! loaded project keeps its unsaved edits.

use cbus_cgate::{AccessLevel, Response, Server};

fn fixture() -> serde_json::Value {
    serde_json::from_str(include_str!(
        "../../testdata/fixtures/native_cgate_dbsetxml_lifecycle.json"
    ))
    .unwrap()
}

fn status(row: &serde_json::Value) -> u16 {
    row["response_lines"]
        .as_array()
        .unwrap()
        .last()
        .unwrap()
        .as_str()
        .unwrap()
        .split_whitespace()
        .nth(1)
        .unwrap()
        .parse()
        .unwrap()
}

/// `(TagName, Address)` of every Unit in an XML reply, in document order.
fn units(xml: &str) -> Vec<(String, String)> {
    let document = roxmltree::Document::parse(xml).unwrap();
    let root = document.root_element();
    let units = if root.has_tag_name("Unit") {
        vec![root]
    } else {
        root.children()
            .filter(|node| node.has_tag_name("Unit"))
            .collect()
    };
    let text = |node: roxmltree::Node<'_, '_>, name: &str| {
        node.children()
            .find(|child| child.has_tag_name(name))
            .and_then(|child| child.text())
            .unwrap_or_default()
            .to_string()
    };
    units
        .into_iter()
        .map(|unit| (text(unit, "TagName"), text(unit, "Address")))
        .collect()
}

fn native_xml(row: &serde_json::Value) -> String {
    let tag = row["tag"].as_u64().unwrap();
    let prefix = format!("[{tag}] 347-");
    let lines = row["response_lines"].as_array().unwrap();
    lines[2]
        .as_str()
        .unwrap()
        .strip_prefix(&prefix)
        .unwrap()
        .trim_end()
        .to_string()
}

fn rust_xml(response: &Response) -> String {
    response.lines[0].strip_prefix("347-").unwrap().to_string()
}

#[test]
fn unsaved_dbsetxml_is_discarded_by_close_and_kept_by_save_like_native() {
    let native = fixture();
    assert_eq!(native["schema"], "native-cgate-dbsetxml-lifecycle-v1");
    let rows = native["cases"]
        .as_array()
        .unwrap()
        .iter()
        .filter(|row| row["phase"] == "no-autosave" && row["tag"].is_u64())
        .collect::<Vec<_>>();
    assert_eq!(rows.len(), 29);
    let mut server = Server::new(AccessLevel::Program);
    let mut network_oid = String::new();
    let mut interface_oid = String::new();
    for row in rows {
        let tag = row["tag"].as_u64().unwrap();
        let command = row["command"].as_str().unwrap();
        let expected = status(row);
        let response = if command.starts_with("DBSETXML ") {
            let request = row["request"].as_str().unwrap();
            let document = request
                .split_once(&format!(" << END{tag}\r\n"))
                .unwrap()
                .1
                .strip_suffix(&format!("\r\nEND{tag}\r\n"))
                .unwrap()
                .replace(native["network_oid"].as_str().unwrap(), &network_oid)
                .replace(native["interface_oid"].as_str().unwrap(), &interface_oid);
            server.handle_document(&format!("[{tag}] {command}"), &document)
        } else {
            server.handle(&format!("[{tag}] {command}"))
        };
        match expected {
            // Native DBCREATENET returns its OID; the modeled service 200.
            301 if command.starts_with("DBCREATENET") => assert_eq!(response.status, 200),
            344 => {
                assert_eq!(response.status, 200, "{tag} {command}: {response:?}");
                let observed = rust_xml(&response);
                if network_oid.is_empty() {
                    let document = roxmltree::Document::parse(&observed).unwrap();
                    let oid = |node: roxmltree::Node<'_, '_>| {
                        node.children()
                            .find(|child| child.has_tag_name("OID"))
                            .unwrap()
                            .text()
                            .unwrap()
                            .to_string()
                    };
                    network_oid = oid(document.root_element());
                    interface_oid = oid(document
                        .descendants()
                        .find(|node| node.has_tag_name("Interface"))
                        .unwrap());
                }
                assert_eq!(units(&observed), units(&native_xml(row)), "{tag} {command}");
            }
            _ => assert_eq!(response.status, expected, "{tag} {command}: {response:?}"),
        }
    }
}

#[test]
fn never_saved_copy_and_delete_image_boundaries_are_explicit() {
    let mut server = Server::new(AccessLevel::Program);
    assert_eq!(server.handle("[1] PROJECT NEW NEVER").status, 200);
    assert_eq!(server.handle("[2] PROJECT USE NEVER").status, 200);
    assert_eq!(
        server
            .handle("[3] DBCREATENET 254 Local Cni 127.0.0.1:1")
            .status,
        200
    );
    // Native drops a never-saved project on CLOSE (its LOAD then fails with
    // 408). Without a saved image the model keeps it rather than delete it.
    assert_eq!(server.handle("[4] PROJECT CLOSE NEVER").status, 200);
    assert_eq!(server.handle("[5] PROJECT LOAD NEVER").status, 200);
    assert_eq!(server.handle("[6] DBGETXML //NEVER/254").status, 200);

    // A copy is a saved project: closing it keeps the copied tree.
    assert_eq!(server.handle("[7] PROJECT COPY NEVER COPIED").status, 200);
    assert_eq!(server.handle("[8] PROJECT USE COPIED").status, 200);
    assert_eq!(
        server
            .handle("[9] DBSET //COPIED/254/TagName Edited")
            .status,
        200
    );
    assert_eq!(server.handle("[10] PROJECT CLOSE COPIED").status, 200);
    assert_eq!(server.handle("[11] PROJECT LOAD COPIED").status, 200);
    let reverted = server.handle("[12] DBGETXML //COPIED/254");
    assert!(
        reverted.lines[0].contains("<TagName>Local</TagName>"),
        "{reverted:?}"
    );
    // Deleting a project forgets its saved image.
    assert_eq!(server.handle("[13] PROJECT DELETE COPIED").status, 200);
    assert_eq!(server.handle("[14] PROJECT NEW COPIED").status, 200);
    assert_eq!(server.handle("[15] PROJECT CLOSE COPIED").status, 200);
    assert_eq!(server.handle("[16] PROJECT USE COPIED").status, 200);
    assert_eq!(server.handle("[17] DBGETXML //COPIED/254").status, 401);
}
