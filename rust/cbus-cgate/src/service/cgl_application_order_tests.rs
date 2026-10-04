//! Private replay/fallback regression boundaries; no original execution.

use super::*;
use crate::AccessLevel;

fn local_order(server: &mut Server) -> Vec<u8> {
    let response = server.handle("[order] CGL EXPORT ORDER 254");
    assert_eq!(response.status, 344, "{response:?}");
    let value: Value = serde_json::from_str(&response.lines[1][4..]).unwrap();
    value["networks"][0]["applications"]
        .as_array()
        .unwrap()
        .iter()
        .map(|application| application["address"].as_u64().unwrap() as u8)
        .collect()
}

#[test]
fn absent_legacy_history_is_unknown_numeric_prefix_then_new_creations() {
    let mut server = Server::new(AccessLevel::Program);
    for command in [
        "PROJECT NEW ORDER",
        "DBCREATENET 254 Order Cni 127.0.0.2:29999",
    ] {
        assert!(server.handle(&format!("[seed] {command}")).status < 400);
    }
    assert_eq!(
        server.handle_document(
            "[seed] CGL IMPORT ORDER",
            r#"{"cglVersion":"1.1","localNetwork":254,"networks":[{"address":254,"applications":[{"address":72,"name":"First"},{"address":0,"name":"Second"}]}]}"#,
        ).status,
        200
    );
    assert_eq!(local_order(&mut server), [72, 0]);
    // Reconstruct the old on-disk shape, rather than calling a producer
    // expected-order helper. Missing history cannot recover native order.
    let network = &server.projects["ORDER"].networks[&254];
    let mut old = serde_json::to_value(network).unwrap();
    old.as_object_mut()
        .unwrap()
        .remove("application_creation_order");
    let old: crate::Network = serde_json::from_value(old).unwrap();
    assert!(old.application_creation_order.historical_prefix_unknown);
    server
        .projects
        .get_mut("ORDER")
        .unwrap()
        .networks
        .insert(254, old);
    assert_eq!(local_order(&mut server), [0, 72]);
    assert_eq!(
        server.handle_document(
            "[append] CGL IMPORT ORDER",
            r#"{"cglVersion":"1.1","localNetwork":254,"networks":[{"address":254,"applications":[{"address":66,"name":"New"},{"address":72,"name":"Ignored"}]}]}"#,
        ).status,
        200
    );
    assert_eq!(local_order(&mut server), [0, 72, 66]);
    // Plain CGL labels have no typed scalar getter. Preserve the actual
    // opaque success envelope and verify the retained label in its owner.
    let read = server.handle("[name] DBGET //ORDER/254/72/TagName");
    assert_eq!(read.status, 200);
    assert_eq!(read.lines, ["path=//ORDER/254/72/TagName"]);
    assert_eq!(read.final_text, "200 OK");
    assert_eq!(server.db_fields["//ORDER/254/72/TagName"], "First");
}

#[test]
fn native_partial_prefixes_retain_all_five_internal_label_values() {
    let mut server = Server::new(AccessLevel::Program);
    let steps = replay::steps();
    for step in steps.iter().filter(|step| step.scenario == "chain_setup") {
        let command = format!("[seed] {}", step.command);
        let response = match &step.document {
            Some(document) => server.handle_document(&command, document),
            None => server.handle(&command),
        };
        assert!(response.status < 400, "{command}: {response:?}");
    }
    let validation = steps
        .iter()
        .filter(|step| step.scenario == "validation")
        .collect::<Vec<_>>();
    for index in [8, 13, 15, 17, 18] {
        let step = validation[index];
        let command = format!("[prefix] {}", step.command);
        let response = match &step.document {
            Some(document) => server.handle_document(&command, document),
            None => server.handle(&command),
        };
        let native_status: u16 = step.expected["reply"]
            .as_array()
            .unwrap()
            .last()
            .unwrap()
            .as_str()
            .unwrap()[..3]
            .parse()
            .unwrap();
        assert_eq!(response.status, native_status, "{command}: {response:?}");
    }
    // These are owned internal-store assertions, including labels excluded
    // from CGL export, rather than a claim of public DBGET value readback.
    for (path, name) in [
        ("//CGLP/254/71/TagName", "A71"),
        ("//CGLP/254/66/TagName", "A66"),
        ("//CGLP/254/66/1/TagName", "G"),
        ("//CGLP/254/255/TagName", "A255"),
        ("//CGLP/254/255/255/TagName", "G255"),
    ] {
        assert_eq!(server.db_fields[path], name);
    }
}

#[test]
fn replay_oracle_rejects_application_address_sorting() {
    let step = replay::steps()
        .into_iter()
        .find(|step| {
            step.scenario == "validation" && step.command == "CGL EXPORT CGLP 254 0,66,70,71,72,255"
        })
        .unwrap();
    let native = step.expected["reply"].as_array().unwrap();
    let mut response = Response {
        tag: "oracle".to_string(),
        lines: vec![
            native[0].as_str().unwrap().to_string(),
            native[1].as_str().unwrap().to_string(),
        ],
        final_text: native[2].as_str().unwrap().to_string(),
        status: 344,
    };
    assert!(replay::check(&step, &response).is_ok());
    let mut value: Value = serde_json::from_str(&response.lines[1][4..]).unwrap();
    value["networks"][0]["applications"]
        .as_array_mut()
        .unwrap()
        .sort_by_key(|application| application["address"].as_u64());
    response.lines[1] = format!("347-{value}");
    assert!(replay::check(&step, &response).is_err());
}

#[test]
fn complete_retained_corpus_and_replay_dispositions_are_explicit() {
    let fixture: Value = serde_json::from_str(replay::FIXTURE).unwrap();
    let expected = [
        ("no_project", 4),
        ("chain_setup", 34),
        ("export_routes", 12),
        ("import_routes", 2),
        ("local_network_variants", 4),
        ("conflicts", 5),
        ("metadata", 12),
        ("validation", 25),
        ("export_types", 10),
        ("large", 2),
        ("runtime_layer", 11),
        ("topology", 33),
        ("nameless", 9),
    ];
    let scenarios = fixture["scenarios"].as_array().unwrap();
    assert_eq!(scenarios.len(), expected.len());
    let mut total = 0;
    let mut native_only_network_steps = 0;
    for (scenario, (name, count)) in scenarios.iter().zip(expected) {
        assert_eq!(scenario["name"], name);
        let steps = scenario["steps"].as_array().unwrap();
        assert_eq!(steps.len(), count);
        total += steps.len();
        native_only_network_steps += steps
            .iter()
            .filter(|step| {
                let command = step["command"].as_str().unwrap();
                command.starts_with("NET OPEN") || command.starts_with("NET CLOSE")
            })
            .count();
    }
    assert_eq!(total, 163);
    assert_eq!(native_only_network_steps, 2);
    assert_eq!(replay::steps().len(), 161);
    // Nine nameless-policy rows remain explicitly outside native equality,
    // not silently counted as exact native workflow acceptance.
    assert_eq!(
        replay::steps()
            .iter()
            .filter(|step| step.scenario == "nameless")
            .count(),
        9
    );
}
