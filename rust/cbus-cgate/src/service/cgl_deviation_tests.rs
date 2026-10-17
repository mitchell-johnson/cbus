//! Explicit dispositions for the four remaining native CGL differences,
//! plus the durable multi-network checks from issue #25.
//!
//! Application creation order is resolved; these tests pin what is
//! deliberately different and why, against the committed native capture in
//! `testdata/fixtures/native_cgate_cgl_routes.json` (read here through the
//! shared `replay` module, never re-executed):
//! * groups/levels export in address order: no committed native export
//!   discriminates creation from address order, so a resolving change must
//!   wait on such a capture;
//! * `createdBy` names cmqttd instead of impersonating the native server;
//! * failure texts keep the native status and prefix but omit Jackson's
//!   `fasterxml` detail after it;
//! * an import that would create a nameless object is refused before
//!   mutation, because native accepts it and then cannot `PROJECT SAVE`;
//! * no CGL command syntax reaches `CglImportConfiguration` (pinned at the
//!   service help surface in `service/tests.rs`).
//!   The final test proves imported labels survive save/close/load/use plus
//!   `NET LOAD DB` on every routable network, with routes intact.

use super::*;
use crate::AccessLevel;
use serde_json::Value;

fn new_cgl_project(server: &mut Server, project: &str, networks: &[(u8, &str)]) {
    let created = server.handle(&format!("[new] PROJECT NEW {project}"));
    assert!(created.status < 400, "{created:?}");
    for (address, name) in networks {
        let created = server.handle(&format!(
            "[net] DBCREATENET {address} {name} Cni 127.0.0.2:29999"
        ));
        assert!(created.status < 400, "{created:?}");
    }
}

fn add_bridge_unit(server: &mut Server, project: &str, network: u8, target: u8, unit_type: &str) {
    let added = server.handle(&format!(
        "[bridge] DBADDSAFE //{project}/{network} Unit {target} U{network}x{target}"
    ));
    assert_eq!(added.status, 301, "{added:?}");
    let typed = server.handle(&format!(
        "[bridge-type] DBSETSAFE //{project}/{network}/p/{target}/UnitType {unit_type}"
    ));
    assert_eq!(typed.status, 200, "{typed:?}");
}

/// Export with generated metadata masked, as the replay comparators do.
fn masked_export(server: &mut Server, command: &str) -> (Value, String) {
    let response = server.handle(command);
    assert_eq!(response.status, 344, "{response:?}");
    assert_eq!(response.lines.len(), 2, "{response:?}");
    assert_eq!(response.lines[0], "343-Begin CGL snippet");
    let mut document: Value = serde_json::from_str(&response.lines[1][4..]).unwrap();
    document["createdBy"] = Value::from("<creator>");
    document["createdTime"] = Value::from("<timestamp>");
    (document, response.final_text)
}

fn addresses(items: &Value) -> Vec<u64> {
    items
        .as_array()
        .unwrap()
        .iter()
        .map(|item| item["address"].as_u64().unwrap())
        .collect()
}

#[test]
fn groups_and_levels_export_in_address_order_while_applications_keep_creation_order() {
    let mut server = Server::new(AccessLevel::Program);
    new_cgl_project(&mut server, "ORDER", &[(254, "Local")]);
    let imported = server.handle_document(
        "[import] CGL IMPORT ORDER",
        r#"{"cglVersion":"1.1","localNetwork":254,"networks":[{"address":254,"applications":[
            {"address":9,"name":"Second","groups":[
                {"address":9,"name":"Nine","levels":[{"address":200,"name":"High"},{"address":7,"name":"Low"}]},
                {"address":3,"name":"Three"}]},
            {"address":2,"name":"First"}]}]}"#,
    );
    assert_eq!(imported.status, 200, "{imported:?}");
    let (document, terminal) = masked_export(&mut server, "[export] CGL EXPORT ORDER 254");
    let applications = &document["networks"][0]["applications"];
    // Applications keep creation order even though 2 < 9 numerically.
    assert_eq!(addresses(applications), [9, 2]);
    let groups = &applications[0]["groups"];
    // Groups and levels keep address order instead. No committed native
    // export separates native chronology from address order here, so this
    // disposition stays explicit until such a capture exists.
    assert_eq!(addresses(groups), [3, 9]);
    assert_eq!(addresses(&groups[1]["levels"]), [7, 200]);
    assert_eq!(terminal, "344 End CGL snippet [numberOfExportedObjects:6]");
}

#[test]
fn nameless_import_is_refused_before_mutation_at_each_depth() {
    // Native accepts these documents and then cannot PROJECT SAVE; the
    // committed capture proves it (nameless scenario: 200 import, NOT NULL
    // failure on save). cmqttd refuses the whole document first instead.
    let fixture: Value = serde_json::from_str(replay::FIXTURE).unwrap();
    let nameless = fixture["scenarios"]
        .as_array()
        .unwrap()
        .iter()
        .find(|scenario| scenario["name"] == "nameless")
        .unwrap();
    let steps = nameless["steps"].as_array().unwrap();
    let native_import = steps
        .iter()
        .find(|step| step["command"] == "CGL IMPORT CGLN")
        .unwrap();
    assert_eq!(
        native_import["reply"].as_array().unwrap().last().unwrap(),
        "200 OK."
    );
    let native_save = steps
        .iter()
        .find(|step| step["command"] == "PROJECT SAVE CGLN")
        .unwrap();
    assert!(native_save["reply"]
        .as_array()
        .unwrap()
        .last()
        .unwrap()
        .as_str()
        .unwrap()
        .contains("NOT NULL constraint failed"));

    for (label, document) in [
        (
            "application",
            r#"{"cglVersion":"1.1","localNetwork":254,"networks":[{"address":254,"applications":[{"address":56}]}]}"#,
        ),
        (
            "group",
            r#"{"cglVersion":"1.1","localNetwork":254,"networks":[{"address":254,"applications":[{"address":56,"name":"L","groups":[{"address":1}]}]}]}"#,
        ),
        (
            "level",
            r#"{"cglVersion":"1.1","localNetwork":254,"networks":[{"address":254,"applications":[{"address":56,"name":"L","groups":[{"address":1,"name":"G","levels":[{"address":7}]}]}]}]}"#,
        ),
    ] {
        let mut server = Server::new(AccessLevel::Program);
        new_cgl_project(&mut server, "NAMELESS", &[(254, "Local")]);
        let before = server.handle("[before] CGL EXPORT NAMELESS 254");
        assert_eq!(before.status, 344, "{label}");
        let refused =
            server.handle_document(&format!("[refuse-{label}] CGL IMPORT NAMELESS"), document);
        assert_eq!(refused.status, 408, "{label}: {refused:?}");
        assert_eq!(
            refused.final_text,
            "408 Operation failed: CGL import failed: a new application, group or level needs a name",
            "{label}"
        );
        let after = server.handle("[after] CGL EXPORT NAMELESS 254");
        assert_eq!(after.status, before.status, "{label}");
        assert_eq!(after.lines[0], before.lines[0], "{label}");
        assert_eq!(after.final_text, before.final_text, "{label}");
        // Only generated metadata may differ; the label graph is untouched.
        let mut before_document: Value = serde_json::from_str(&before.lines[1][4..]).unwrap();
        let mut after_document: Value = serde_json::from_str(&after.lines[1][4..]).unwrap();
        for document in [&mut before_document, &mut after_document] {
            document["createdBy"] = Value::from("<creator>");
            document["createdTime"] = Value::from("<timestamp>");
        }
        assert_eq!(after_document, before_document, "{label}");
        assert!(
            !server
                .db_fields
                .keys()
                .any(|key| key.starts_with("//NAMELESS/254/56")),
            "{label}"
        );
    }
}

#[test]
fn export_identity_names_cmqttd_while_replay_masks_it() {
    let mut server = Server::new(AccessLevel::Program);
    new_cgl_project(&mut server, "IDENTITY", &[(254, "Local")]);
    let response = server.handle("[export] CGL EXPORT IDENTITY 254");
    assert_eq!(response.status, 344, "{response:?}");
    let document: Value = serde_json::from_str(&response.lines[1][4..]).unwrap();
    // Honest provenance: this server is cmqttd, not C-Gate 3.4.0.2001.
    assert_eq!(document["createdBy"], Value::from("cmqttd"));
    // The shared replay comparator masks exactly this field, so vector
    // comparison never depends on which server wrote the document.
    let native_line = response.lines[1].replacen(
        "\"createdBy\":\"cmqttd\"",
        "\"createdBy\":\"C-Gate v3.4.0 (build 2001)\"",
        1,
    );
    assert_ne!(native_line, response.lines[1]);
    let step = replay::Step {
        scenario: "identity".to_string(),
        command: "CGL EXPORT IDENTITY 254".to_string(),
        document: None,
        expected: serde_json::json!({"reply": [response.lines[0], native_line, response.final_text]}),
    };
    assert!(replay::check(&step, &response).is_ok());
}

#[test]
fn failure_texts_keep_native_status_and_prefix_without_jackson_detail() {
    let fixture: Value = serde_json::from_str(replay::FIXTURE).unwrap();
    let steps: Vec<&Value> = fixture["scenarios"]
        .as_array()
        .unwrap()
        .iter()
        .flat_map(|scenario| scenario["steps"].as_array().unwrap().iter())
        .collect();
    let native = |command: &str, document: &str| -> (u16, String) {
        let step = steps
            .iter()
            .find(|step| {
                step["command"] == command
                    && step.get("document").and_then(Value::as_str) == Some(document)
            })
            .unwrap_or_else(|| panic!("committed fixture lacks {command} {document}"));
        let reply = step["reply"].as_array().unwrap();
        let text = reply.last().unwrap().as_str().unwrap().to_string();
        (text[..3].parse().unwrap(), text)
    };
    let mut server = Server::new(AccessLevel::Program);
    new_cgl_project(&mut server, "FAIL", &[(254, "Local")]);
    // Version, null and address failures match native byte for byte.
    for document in [
        r#"{"cglVersion":"1.0","localNetwork":254,"networks":[]}"#,
        r#"{"localNetwork":254,"networks":[]}"#,
        r#"{"cglVersion":"1.1","networks":[]}"#,
        r#"{"cglVersion":"1.1","localNetwork":254,"networks":[{"address":254,"applications":[{"address":300,"name":"Big"}]}]}"#,
    ] {
        let (status, text) = native("CGL IMPORT CGLP", document);
        let response = server.handle_document("[failure] CGL IMPORT FAIL", document);
        assert_eq!(response.status, status, "{document}");
        assert_eq!(response.final_text, text, "{document}");
    }
    // Binding failures keep only the shared native prefix; the Jackson
    // `fasterxml` detail after it is deliberately not reproduced.
    const PREFIX: &str = "400 Syntax Error: CGL validation failed: Import Failed: ";
    for document in [
        r#"{"cglVersion":"1.1","localNetwork":254,"networks":[],"numberOfExportedObjects":3}"#,
        r#"{"cglVersion":"1.1","localNetwork":254,"bogus":1,"networks":[]}"#,
        r#"{"cglVersion":"1.1","localNetwork":254,"networks":[{"address":254,"extra":true}]}"#,
        r#"{"cglVersion":"1.1","localNetwork":254,"networks":[{"address":254,"applications":[{"address":1,"name":"x","extra":1}]}]}"#,
        r#"{"cglVersion":"1.1","localNetwork":254,"networks":[{"address":254,"applications":[{"address":1,"name":"x","groups":[{"address":1,"name":"g","levels":[{"address":1,"name":"l","extra":1}]}]}]}]}"#,
        r#"{"cglVersion":"1.1","localNetwork":254,"networks":[{"address":254,"applications":[{"address":62,"type":"lighting","name":"A62"}]}]}"#,
    ] {
        let (status, text) = native("CGL IMPORT CGLP", document);
        assert_eq!(status, 400, "{document}");
        assert!(text.starts_with(PREFIX), "{document}");
        let response = server.handle_document("[binding] CGL IMPORT FAIL", document);
        assert_eq!(response.status, 400, "{document}: {response:?}");
        assert!(response.final_text.starts_with(PREFIX), "{response:?}");
        assert!(!response.final_text.contains("fasterxml"), "{response:?}");
        assert!(!response.final_text.contains("at [Source:"), "{response:?}");
    }
}

#[test]
fn multinetwork_import_save_reload_keeps_labels_routes_and_skips() {
    let mut server = Server::new(AccessLevel::Program);
    new_cgl_project(
        &mut server,
        "MULTI",
        &[(254, "Local"), (253, "Remote"), (240, "Island")],
    );
    add_bridge_unit(&mut server, "MULTI", 254, 253, "BRIDGE");
    add_bridge_unit(&mut server, "MULTI", 253, 254, "BRIDGE");
    // 240 holds no bridge units: a one-way island that is never routable.
    let imported = server.handle_document(
        "[import] CGL IMPORT MULTI",
        r#"{"cglVersion":"1.1","localNetwork":254,"networks":[
            {"address":254,"applications":[{"address":56,"name":"L254","groups":[{"address":1,"name":"G1","levels":[{"address":7,"name":"Seven"}]}]}]},
            {"address":253,"route":[9],"applications":[{"address":56,"name":"L253","groups":[{"address":2,"name":"G2"}]}]},
            {"address":240,"applications":[{"address":56,"name":"Stranded"}]},
            {"address":99,"applications":[{"address":56,"name":"Absent"}]}]}"#,
    );
    assert_eq!(imported.status, 380, "{imported:?}");
    assert_eq!(
        imported.final_text,
        "380 CGL import not completed: Skipped 2 network(s). "
    );
    // The supplied route is ignored: 253 imports through the database route.
    assert!(
        imported
            .lines
            .iter()
            .any(|line| line.contains("Importing Network 253")),
        "{imported:?}"
    );
    assert!(
        imported
            .lines
            .iter()
            .any(|line| line.contains("SKIPPED - Network 240 is not routable")),
        "{imported:?}"
    );
    assert!(
        imported
            .lines
            .iter()
            .any(|line| line.contains("SKIPPED - Network 99 does not exist")),
        "{imported:?}"
    );

    let (before, terminal) = masked_export(&mut server, "[export] CGL EXPORT MULTI 254");
    assert_eq!(terminal, "344 End CGL snippet [numberOfExportedObjects:5]");
    // Networks export in project order with database routes; the island
    // stays out.
    assert_eq!(
        before["networks"]
            .as_array()
            .unwrap()
            .iter()
            .map(|network| network["address"].as_u64().unwrap())
            .collect::<Vec<_>>(),
        [254, 253]
    );
    assert_eq!(before["networks"][1]["route"], serde_json::json!([253]));
    assert_eq!(before["networks"][0]["applications"][0]["name"], "L254");
    assert_eq!(before["networks"][1]["applications"][0]["name"], "L253");

    for command in [
        "PROJECT SAVE MULTI",
        "PROJECT CLOSE MULTI",
        "PROJECT LOAD MULTI",
        "PROJECT USE MULTI",
        "NET LOAD DB",
    ] {
        let response = server.handle(&format!("[reload] {command}"));
        assert_eq!(response.status, 200, "{command}: {response:?}");
    }
    let (after, terminal_after) =
        masked_export(&mut server, "[reload-export] CGL EXPORT MULTI 254");
    assert_eq!((after, terminal_after), (before, terminal.clone()));
    // The second network serves as local with the reverse route, labels
    // intact. Export keeps project order (local is not moved first), as in
    // the committed native multi-local exports.
    let (remote, remote_terminal) =
        masked_export(&mut server, "[remote-export] CGL EXPORT MULTI 253");
    assert_eq!(remote["localNetwork"], 253);
    assert_eq!(
        remote["networks"]
            .as_array()
            .unwrap()
            .iter()
            .map(|network| network["address"].as_u64().unwrap())
            .collect::<Vec<_>>(),
        [254, 253]
    );
    assert_eq!(remote["networks"][0]["route"], serde_json::json!([254]));
    assert!(remote["networks"][1].get("route").is_none());
    assert_eq!(remote["networks"][0]["applications"][0]["name"], "L254");
    assert_eq!(remote["networks"][1]["applications"][0]["name"], "L253");
    assert_eq!(
        remote["networks"][0]["applications"][0]["groups"][0]["levels"][0]["name"],
        "Seven"
    );
    assert_eq!(remote_terminal, terminal);
}
