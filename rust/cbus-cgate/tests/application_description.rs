//! Owned model regression for the scalar Description contract used by Add.
//! This does not establish native XML Description serialization (#75).

use cbus_cgate::{format_response, AccessLevel, Server};

fn vector() -> serde_json::Value {
    let value: serde_json::Value = serde_json::from_str(include_str!(
        "../../testdata/vectors/cgate_application_description_scalar.json"
    ))
    .unwrap();
    assert_eq!(value["format"], "cbus-application-description-scalar-v1");
    assert_eq!(value["scope"]["original_execution"], false);
    assert_eq!(value["scope"]["xml_description_admission"], false);
    value
}

fn seed(value: &serde_json::Value) -> (Server, Vec<String>) {
    let mut server = Server::new(AccessLevel::Program);
    let mut issued = Vec::new();
    for command in value["seed_commands"].as_array().unwrap() {
        let body = command.as_str().unwrap();
        let response = server.handle(&format!("[seed] {body}"));
        if body.starts_with("DBADDSAFE ") {
            assert_eq!(response.status, 301, "{response:?}");
            assert!(response.lines.is_empty());
            issued.push(
                response
                    .final_text
                    .strip_prefix("301 OID=")
                    .unwrap()
                    .to_string(),
            );
        } else {
            assert_eq!(response.status, 200, "{response:?}");
        }
    }
    assert_eq!(issued.len(), 3);
    assert_ne!(issued[0], issued[1]);
    assert_ne!(issued[0], issued[2]);
    (server, issued)
}

fn xml(server: &mut Server) -> Vec<String> {
    let response = server.handle("[xml] DBGETXML //DESC");
    assert_eq!(response.status, 200, "{response:?}");
    response.lines
}

fn read(server: &mut Server, oid: &str) -> String {
    format_response(&server.handle(&format!("[read] DBGET !{oid}/Description")))
}

#[test]
fn application_and_group_description_scalar_survives_saved_project_reload() {
    let value = vector();
    let (mut server, issued) = seed(&value);
    let initial = xml(&mut server);
    for (case, oid) in value["cases"].as_array().unwrap().iter().zip(&issued) {
        assert_eq!(
            read(&mut server, oid),
            value["empty_oid_reply"].as_str().unwrap()
        );
        let path = case["path"].as_str().unwrap();
        for (address, key, expected) in [
            (format!("!{oid}"), "oid_setter_value", "oid_reply"),
            (
                path.to_string(),
                "canonical_setter_value",
                "canonical_reply",
            ),
        ] {
            let setter = server.handle(&format!(
                "[set] DBSETSAFE {address}/Description {}",
                case[key].as_str().unwrap()
            ));
            assert_eq!(format_response(&setter), "[set] 200 OK\n");
            assert_eq!(
                read(&mut server, oid),
                case[expected].as_str().unwrap().replace("{oid}", oid)
            );
        }
        let identity = server.handle(&format!("[identity] DBGET !{oid}/OID"));
        assert_eq!(
            format_response(&identity),
            format!("[identity] 342 !{oid}/OID={oid}\n")
        );
        let name = server.handle(&format!("[name] DBGET !{oid}/TagName"));
        assert_eq!(
            name.final_text,
            format!("342 !{oid}/TagName={}", case["tag_name"].as_str().unwrap())
        );
    }
    // The scalar change must preserve the whole bounded XML graph, including
    // its existing omission of Description. No new XML field is admitted.
    assert_eq!(xml(&mut server), initial);
    for command in [
        "PROJECT SAVE DESC",
        "PROJECT CLOSE DESC",
        "PROJECT LOAD DESC",
        "PROJECT USE DESC",
    ] {
        assert_eq!(server.handle(&format!("[project] {command}")).status, 200);
    }
    for (case, oid) in value["cases"].as_array().unwrap().iter().zip(&issued) {
        assert_eq!(
            read(&mut server, oid),
            case["canonical_reply"]
                .as_str()
                .unwrap()
                .replace("{oid}", oid)
        );
    }
    assert_eq!(
        read(&mut server, &issued[2]),
        value["empty_oid_reply"].as_str().unwrap()
    );
    assert_eq!(xml(&mut server), initial);
}

#[test]
fn application_description_refusals_preserve_value_and_project_identity() {
    let value = vector();
    let (mut server, issued) = seed(&value);
    let oid = &issued[0];
    assert_eq!(
        server
            .handle(&format!("[set] DBSETSAFE !{oid}/Description Retained"))
            .status,
        200
    );
    let initial = xml(&mut server);
    for refusal in value["refusals"].as_array().unwrap() {
        let body = refusal["command"]
            .as_str()
            .unwrap()
            .replace("{oid}", oid)
            .replace("{path}", "//DESC/254/48");
        assert_eq!(
            format_response(&server.handle(&format!("[refuse] {body}"))),
            refusal["reply"].as_str().unwrap()
        );
        assert_eq!(
            read(&mut server, oid),
            format!("[read] 342 !{oid}/Description=Retained\n")
        );
        assert_eq!(xml(&mut server), initial);
    }
    assert_eq!(server.handle("[other] PROJECT NEW OTHER").status, 200);
    assert_eq!(
        format_response(&server.handle(&format!("[foreign] DBSETSAFE !{oid}/Description Leaked"))),
        "[foreign] 401 Object not found\n"
    );
    assert_eq!(
        format_response(&server.handle(&format!("[foreign] DBGET !{oid}/Description"))),
        "[foreign] 401 Object not found\n"
    );
    assert_eq!(server.handle("[select] PROJECT USE DESC").status, 200);
    assert_eq!(
        read(&mut server, oid),
        format!("[read] 342 !{oid}/Description=Retained\n")
    );
    assert_eq!(xml(&mut server), initial);
}

#[test]
fn scalar_description_does_not_admit_application_xml_description() {
    let value = vector();
    let (mut server, issued) = seed(&value);
    let initial = xml(&mut server);
    let body = format!(
        "<Application><OID>{}</OID><TagName>Fresh Application</TagName><Address>48</Address><Description>Unproved XML</Description></Application>",
        issued[0]
    );
    let rejected = server.handle_document("[xml] DBSETXML //DESC/254/48", &body);
    assert_eq!(rejected.status, 400, "{rejected:?}");
    assert_eq!(xml(&mut server), initial);
    assert_eq!(
        read(&mut server, &issued[0]),
        value["empty_oid_reply"].as_str().unwrap()
    );
}
