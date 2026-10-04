//! Application-order expectations come from the retained native CGL fixture.
//! These owned model tests do not execute C-Gate, a PCI or a controller. The
//! Group/Level creation-order disposition remains outside this feature.

use cbus_cgate::{AccessLevel, Response, Server};
use serde_json::Value;

const FIXTURE: &str = include_str!("../../testdata/fixtures/native_cgate_cgl_routes.json");
const SIMULATOR: &str = "127.0.0.2:29999";

fn fixture() -> Value {
    assert_eq!(
        hex::encode(cbus_cgate::auth::sha256(FIXTURE.as_bytes())),
        "3a818506368c6eb6311125cb7f5a1272b5de6526b653d67b7ae197e043369490"
    );
    serde_json::from_str(FIXTURE).unwrap()
}

fn scenario<'a>(fixture: &'a Value, name: &str) -> &'a [Value] {
    fixture["scenarios"]
        .as_array()
        .unwrap()
        .iter()
        .find(|scenario| scenario["name"] == name)
        .unwrap()["steps"]
        .as_array()
        .unwrap()
}

fn run_step(server: &mut Server, step: &Value) -> Response {
    let line = format!(
        "[native] {}",
        step["command"]
            .as_str()
            .unwrap()
            .replace("<simulator>", SIMULATOR)
    );
    match step["document"].as_str() {
        Some(document) => server.handle_document(&line, document),
        None => server.handle(&line),
    }
}

fn seed_native_prefix() -> Server {
    let fixture = fixture();
    let mut server = Server::new(AccessLevel::Program);
    for step in scenario(&fixture, "chain_setup") {
        // The captured original opening is unrelated to label graph import.
        // The owned model deliberately never starts that network here.
        if step["command"].as_str().unwrap().starts_with("NET OPEN") {
            continue;
        }
        assert!(run_step(&mut server, step).status < 400, "{step:?}");
    }
    let validation = scenario(&fixture, "validation");
    for index in [8, 13, 15, 17, 18] {
        let step = &validation[index];
        let response = run_step(&mut server, step);
        let native_status: u16 = step["reply"]
            .as_array()
            .unwrap()
            .last()
            .unwrap()
            .as_str()
            .unwrap()[..3]
            .parse()
            .unwrap();
        assert_eq!(response.status, native_status, "{step:?}: {response:?}");
    }
    server
}

fn document(response: &Response) -> Value {
    assert_eq!(response.status, 344, "{response:?}");
    assert_eq!(response.lines.len(), 2);
    assert_eq!(response.lines[0], "343-Begin CGL snippet");
    let mut document: Value = serde_json::from_str(
        response.lines[1]
            .strip_prefix("347-")
            .expect("CGL JSON row"),
    )
    .unwrap();
    document["createdBy"] = Value::from("<creator>");
    document["createdTime"] = Value::from("<timestamp>");
    document
}

fn export(server: &mut Server, applications: &str) -> (Value, String) {
    let response = server.handle(&format!("[export] CGL EXPORT CGLP 254 {applications}"));
    (document(&response), response.final_text)
}

fn local_addresses(document: &Value) -> Vec<u8> {
    document["networks"][0]["applications"]
        .as_array()
        .unwrap()
        .iter()
        .map(|application| application["address"].as_u64().unwrap() as u8)
        .collect()
}

#[test]
fn native_partial_408_prefixes_export_literal_application_creation_order() {
    let mut server = seed_native_prefix();
    let response = run_step(&mut server, &scenario(&fixture(), "validation")[23]);
    let actual = document(&response);
    let fixture = fixture();
    let native = &scenario(&fixture, "validation")[23]["reply"];
    let mut expected: Value =
        serde_json::from_str(native[1].as_str().unwrap()[4..].trim()).unwrap();
    expected["createdBy"] = Value::from("<creator>");
    expected["createdTime"] = Value::from("<timestamp>");
    assert_eq!(local_addresses(&actual), [72, 0, 71, 66]);
    // Exact complete export preserves the captured routes, labels, filtering
    // and object count. No sibling-array normalization can hide the order.
    assert_eq!(actual, expected);
    assert_eq!(response.final_text, native[2].as_str().unwrap());
    // Exact export above verifies visible names. The private source test
    // verifies all five retained prefix labels, including excluded address
    // 255; plain CGL labels do not expose typed DBGET scalar values.
}

#[test]
fn runtime_reannouncement_and_saved_reload_preserve_order_and_names() {
    let mut server = seed_native_prefix();
    let (before, terminal) = export(&mut server, "0,66,70,71,72,255");
    for command in [
        "PROJECT SAVE CGLP",
        "PROJECT CLOSE CGLP",
        "PROJECT LOAD CGLP",
        "PROJECT USE CGLP",
        "NET LOAD DB",
    ] {
        let response = server.handle(&format!("[load] {command}"));
        assert_eq!(response.status, 200, "{response:?}");
    }
    let fixture = fixture();
    let step = &scenario(&fixture, "validation")[13];
    let first = run_step(&mut server, step);
    assert_eq!(first.status, 200);
    assert!(first
        .lines
        .iter()
        .any(|line| line.contains("Created new application 254/72")));
    let second = run_step(&mut server, step);
    assert_eq!(second.status, 200);
    assert!(second
        .lines
        .iter()
        .any(|line| line.contains("Imported 0 object(s)")));
    assert_eq!(export(&mut server, "0,66,70,71,72,255"), (before, terminal));
}

#[test]
fn selection_excludes_255_without_reordering_and_later_creation_appends() {
    let mut server = seed_native_prefix();
    let (selected, _) = export(&mut server, "66,72,255");
    assert_eq!(local_addresses(&selected), [72, 66]);
    let added = server.handle_document(
        "[append] CGL IMPORT CGLP",
        r#"{"cglVersion":"1.1","localNetwork":254,"networks":[{"address":254,"applications":[{"address":69,"name":"Later"}]}]}"#,
    );
    assert_eq!(added.status, 200, "{added:?}");
    let (after, terminal) = export(&mut server, "0,66,69,70,71,72,255");
    assert_eq!(local_addresses(&after), [72, 0, 71, 66, 69]);
    assert_eq!(after["networks"][0]["applications"][4]["name"], "Later");
    assert_eq!(terminal, "344 End CGL snippet [numberOfExportedObjects:7]");
}

#[test]
fn binding_and_nameless_refusals_preserve_the_complete_export() {
    let mut server = seed_native_prefix();
    let before = export(&mut server, "*");
    for (data, status) in [
        ("not json", 400),
        (
            r#"{"cglVersion":"1.1","localNetwork":254,"networks":[{"address":254,"applications":[{"address":true,"name":"Invalid"}]}]}"#,
            400,
        ),
        (
            r#"{"cglVersion":"1.1","localNetwork":254,"networks":[{"address":254,"applications":[{"address":300,"name":"Invalid"}]}]}"#,
            408,
        ),
        (
            r#"{"cglVersion":"1.1","localNetwork":254,"networks":[{"address":254,"applications":[{"address":96}]}]}"#,
            408,
        ),
    ] {
        let response = server.handle_document("[refusal] CGL IMPORT CGLP", data);
        assert_eq!(response.status, status, "{response:?}");
        assert_eq!(export(&mut server, "*"), before);
    }
}
