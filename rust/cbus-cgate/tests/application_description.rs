//! Owned model regressions for the Application/Group Description contract.
//! The scalar store and the owned-model XML import/export share one canonical
//! field. Native C-Gate placement, default omission and empty handling remain
//! unproven (#75); these are not native acceptance vectors.

use cbus_cgate::{format_response, AccessLevel, Server};

fn vector() -> serde_json::Value {
    let value: serde_json::Value = serde_json::from_str(include_str!(
        "../../testdata/vectors/cgate_application_description_scalar.json"
    ))
    .unwrap();
    assert_eq!(value["format"], "cbus-application-description-scalar-v1");
    assert_eq!(value["scope"]["original_execution"], false);
    assert_eq!(value["scope"]["xml_description_admission"], "owned-model");
    assert_eq!(
        value["scope"]["xml_roundtrip_vector"],
        "cgate_application_description_xml_roundtrip.jsonl"
    );
    // Scalar acknowledgement is unchanged by the XML round-trip work; the
    // live XML contract moved to cgate_application_description_xml_roundtrip.
    assert_eq!(
        value["scope"]["native_xml_acceptance_issue"], 75,
        "{value:?}"
    );
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
        } else if body.starts_with("DBCREATENET ") {
            assert_eq!(response.status, 301, "{response:?}");
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
    // Scalar changes appear in the owned-model export after Address and
    // change nothing else in the bounded XML graph.
    let described = xml(&mut server);
    assert_ne!(described, initial);
    let joined = described.join("\n");
    for (case, oid) in value["cases"].as_array().unwrap().iter().zip(&issued) {
        let address = case["path"].as_str().unwrap().rsplit('/').next().unwrap();
        let canonical = case["canonical_reply"].as_str().unwrap();
        let text = canonical.split_once("/Description=").unwrap().1.trim_end();
        assert!(
            joined.contains(&format!(
                "<OID>{oid}</OID><TagName>{}</TagName><Address>{address}</Address><Description>{text}</Description>",
                case["tag_name"].as_str().unwrap()
            )),
            "{joined}"
        );
    }
    assert_eq!(
        joined
            .replace(
                "<Description>Revised Application description</Description>",
                ""
            )
            .replace("<Description>Revised Group description</Description>", ""),
        initial.join("\n")
    );
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
    assert_eq!(xml(&mut server), described);
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

fn roundtrip_rows() -> Vec<serde_json::Value> {
    let rows =
        include_str!("../../testdata/vectors/cgate_application_description_xml_roundtrip.jsonl")
            .lines()
            .filter(|line| !line.trim().is_empty())
            .map(|line| serde_json::from_str::<serde_json::Value>(line).unwrap())
            .collect::<Vec<_>>();
    for row in &rows {
        assert_eq!(
            row["format"],
            "cgate-application-description-xml-roundtrip-v1"
        );
        assert_eq!(row["issue"], 75);
    }
    let scope = &rows[0];
    assert_eq!(scope["kind"], "scope");
    assert_eq!(scope["model"], "owned-model");
    assert_eq!(scope["native_placement_order"], "unproven");
    assert_eq!(scope["native_xml_acceptance"], false);
    assert_eq!(scope["original_execution"], false);
    rows
}

fn expand(text: &str, roles: &[(String, String)]) -> String {
    roles.iter().fold(text.to_string(), |text, (role, oid)| {
        text.replace(&format!("{{{role}}}"), oid)
    })
}

fn snapshot(server: &mut Server, roles: &[(String, String)]) -> Vec<String> {
    let mut output = xml(server);
    for (_, oid) in roles {
        output.push(read(server, oid));
    }
    output
}

#[test]
fn application_description_xml_roundtrip_matches_owned_vector() {
    let rows = roundtrip_rows();
    let scope = &rows[0];
    let mut server = Server::new(AccessLevel::Program);
    let mut issued = Vec::new();
    for command in scope["seed_commands"].as_array().unwrap() {
        let body = command.as_str().unwrap();
        let response = server.handle(&format!("[seed] {body}"));
        if body.starts_with("DBCREATENET ") {
            assert_eq!(response.status, 301, "{response:?}");
        } else if let Some(oid) = response.final_text.strip_prefix("301 OID=") {
            issued.push(oid.to_string());
        } else {
            assert_eq!(response.status, 200, "{response:?}");
        }
    }
    let roles = scope["oid_roles"]
        .as_array()
        .unwrap()
        .iter()
        .map(|role| role.as_str().unwrap().to_string())
        .zip(issued)
        .collect::<Vec<_>>();
    assert_eq!(roles.len(), 2);
    let mut kinds = std::collections::BTreeSet::new();
    for row in &rows[1..] {
        let id = row["id"].as_str().unwrap();
        let request = format!("[d] {}", expand(row["request"].as_str().unwrap(), &roles));
        let before = snapshot(&mut server, &roles);
        let response = match row["document"].as_str() {
            Some(document) => server.handle_document(&request, &expand(document, &roles)),
            None => server.handle(&request),
        };
        match (row["wire"].as_str(), row["xml"].as_str()) {
            (Some(wire), None) => {
                assert_eq!(format_response(&response), expand(wire, &roles), "{id}")
            }
            (None, Some(document)) => {
                assert_eq!(response.status, 200, "{id}: {response:?}");
                assert_eq!(
                    response.lines,
                    vec![format!("347-{}", expand(document, &roles))],
                    "{id}"
                );
            }
            _ => assert_eq!(response.status, 200, "{id}: {response:?}"),
        }
        if row["preserves_state"] == true {
            assert_eq!(snapshot(&mut server, &roles), before, "{id}");
        }
        kinds.insert(id.split('-').next().unwrap().to_string());
    }
    for kind in ["accept", "lifecycle", "refuse", "reload", "scalar", "xml"] {
        assert!(kinds.contains(kind), "{kind}");
    }
}

#[test]
fn application_description_xml_survives_project_copy_and_application_copy() {
    let rows = roundtrip_rows();
    let mut server = Server::new(AccessLevel::Program);
    let mut issued = Vec::new();
    for command in rows[0]["seed_commands"].as_array().unwrap() {
        let body = command.as_str().unwrap();
        let response = server.handle(&format!("[seed] {body}"));
        if body.starts_with("DBCREATENET ") {
            continue;
        }
        if let Some(oid) = response.final_text.strip_prefix("301 OID=") {
            issued.push(oid.to_string());
        }
    }
    let (app, group) = (&issued[0], &issued[1]);
    let document = format!(
        "<Application><OID>{app}</OID><TagName>Fresh Application</TagName><Address>48</Address><Description>Copied &amp; kept</Description><Group><OID>{group}</OID><TagName>Fresh Group</TagName><Address>42</Address><Description>Group kept</Description></Group></Application>"
    );
    let imported = server.handle_document("[xml] DBSETXML //DESC/254/48", &document);
    assert_eq!(imported.status, 301, "{imported:?}");
    // Same-path SAFE re-creation keeps the canonical Description.
    let again = server.handle("[again] DBADDSAFE //DESC/254/48 Group 42 Fresh Group");
    assert_eq!(again.final_text, format!("301 OID={group}"), "{again:?}");
    assert_eq!(
        read(&mut server, group),
        format!("[read] 342 !{group}/Description=Group kept\n")
    );
    let source = xml(&mut server);
    assert!(source
        .join("")
        .contains("<Address>48</Address><Description>Copied &amp; kept</Description>"));
    assert_eq!(server.handle("[copy] PROJECT COPY DESC DUP").status, 200);
    assert_eq!(server.handle("[use] PROJECT USE DUP").status, 200);
    let duplicate = server.handle("[dup] DBGETXML //DUP/254/48");
    let duplicate = duplicate.lines.join("");
    assert!(
        duplicate.contains("<Address>48</Address><Description>Copied &amp; kept</Description>")
            && duplicate.contains("<Address>42</Address><Description>Group kept</Description>"),
        "{duplicate}"
    );
    assert_eq!(server.handle("[use] PROJECT USE DESC").status, 200);
    let copied = server.handle("[copy] DBCOPYSAFE //DESC/254/48 //DESC/254 49 Copied Application");
    assert_eq!(copied.status, 301, "{copied:?}");
    let oid = copied
        .final_text
        .strip_prefix("301 OID=")
        .unwrap()
        .to_string();
    assert_ne!(&oid, app);
    assert_eq!(
        read(&mut server, &oid),
        format!("[read] 342 !{oid}/Description=Copied & kept\n")
    );
    let copy_xml = server
        .handle("[copyxml] DBGETXML //DESC/254/49")
        .lines
        .join("");
    assert!(
        copy_xml.contains("<Address>49</Address><Description>Copied &amp; kept</Description>")
            && copy_xml.contains("<Address>42</Address><Description>Group kept</Description>"),
        "{copy_xml}"
    );
    // The source is unchanged by either copy.
    assert_eq!(
        xml(&mut server)
            .join("")
            .matches("Copied &amp; kept")
            .count(),
        2
    );
    // A complete combined Network replacement carries nested Application
    // and Group Descriptions through the same canonical store.
    let network = server.handle("[net] DBGETXML //DESC/254");
    assert_eq!(network.status, 200, "{network:?}");
    let network = network.lines[0].strip_prefix("347-").unwrap().to_string();
    let edited = network.replacen(
        "<Description>Group kept</Description>",
        "<Description>Network replaced</Description>",
        1,
    );
    assert_ne!(edited, network);
    let replaced = server.handle_document("[net] DBSETXML //DESC/254", &edited);
    assert_eq!(replaced.status, 301, "{replaced:?}");
    assert_eq!(
        read(&mut server, group),
        format!("[read] 342 !{group}/Description=Network replaced\n")
    );
    assert_eq!(
        server.handle("[net] DBGETXML //DESC/254").lines,
        vec![format!("347-{edited}")]
    );
}

#[test]
fn application_xml_description_is_exported_and_reimports_stably() {
    // Issue #75: supersedes the former refusal pin. The scalar vector's
    // `xml_description_admission` scope moved to the xml-roundtrip vector;
    // this asserts the live contract from the service side of the boundary.
    let value = vector();
    let (mut server, issued) = seed(&value);
    let initial = xml(&mut server);
    let body = format!(
        "<Application><OID>{}</OID><TagName>Fresh Application</TagName><Address>48</Address><Description>Proved XML</Description></Application>",
        issued[0]
    );
    let admitted = server.handle_document("[xml] DBSETXML //DESC/254/48", &body);
    assert_eq!(admitted.status, 301, "{admitted:?}");
    assert_eq!(
        read(&mut server, &issued[0]),
        format!("[read] 342 !{}/Description=Proved XML\n", issued[0])
    );
    let described = xml(&mut server);
    assert_ne!(described, initial);
    assert!(
        described
            .join("\n")
            .contains("<Description>Proved XML</Description>"),
        "{described:?}"
    );
}
