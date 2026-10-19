//! Replays `cgate_cgl_routes.jsonl`, the CGL 1.1 wire vectors derived from
//! the owned native C-Gate 3.4.0.2001 capture, against the cgate-mock model.
//!
//! Each vector group starts from an empty server and runs in file order.
//! Setup rows only need to succeed; binding failures keep the native
//! prefix (Jackson exception detail is not reproduced); exports compare
//! canonical JSON with generated metadata masked and siblings in address
//! order.

use cbus_cgate::{AccessLevel, Response, Server};
use serde_json::{json, Value};

const SIMULATOR: &str = "127.0.0.2:29999";

fn vectors() -> Vec<Value> {
    include_str!("../../testdata/vectors/cgate_cgl_routes.jsonl")
        .lines()
        .map(|line| serde_json::from_str(line).unwrap())
        .collect()
}

fn large_document(generator: &Value) -> String {
    let groups = (0..generator["groups"].as_u64().unwrap())
        .map(|group| {
            let levels = (0..generator["levels_per_group"].as_u64().unwrap())
                .map(|level| json!({"address": level, "name": format!("L{level}")}))
                .collect::<Vec<_>>();
            json!({"address": group, "name": format!("G{group}"), "levels": levels})
        })
        .collect::<Vec<_>>();
    json!({"cglVersion": "1.1", "localNetwork": generator["localNetwork"],
        "networks": [{"address": generator["network"], "applications": [
            {"address": generator["application"], "name": "Large", "groups": groups}]}]})
    .to_string()
}

fn normalize(line: &str) -> String {
    // cgate-mock OIDs are 36-character UUID-shaped strings.
    let mut output = String::new();
    let mut rest = line;
    while let Some(position) = rest.find("OID=") {
        output.push_str(&rest[..position + 4]);
        let tail = &rest[position + 4..];
        let end = tail
            .find(|character: char| !(character.is_ascii_hexdigit() || character == '-'))
            .unwrap_or(tail.len());
        output.push_str("<oid>");
        rest = &tail[end..];
    }
    output.push_str(rest);
    output
}

fn canonical_export(line: &str) -> Value {
    let mut document: Value = serde_json::from_str(&line[4..]).unwrap();
    document["createdBy"] = json!("<creator>");
    document["createdTime"] = json!("<timestamp>");
    fn sort(items: &mut Value, children: &[&str]) {
        let array = items.as_array_mut().unwrap();
        array.sort_by_key(|item| item["address"].as_u64());
        for item in array {
            if let Some((first, rest)) = children.split_first() {
                if let Some(child) = item.get_mut(*first) {
                    sort(child, rest);
                }
            }
        }
    }
    for network in document["networks"].as_array_mut().unwrap() {
        if let Some(applications) = network.get_mut("applications") {
            sort(applications, &["groups", "levels"]);
        }
    }
    document
}

fn check(vector: &Value, response: &Response) -> Result<(), String> {
    let actual = response
        .lines
        .iter()
        .chain(std::iter::once(&response.final_text))
        .map(|line| normalize(line))
        .collect::<Vec<_>>();
    if vector.get("setup").is_some() {
        return (response.status < 400)
            .then_some(())
            .ok_or_else(|| format!("setup failed: {actual:?}"));
    }
    if let Some(expected) = vector.get("expect") {
        let expected = expected
            .as_array()
            .unwrap()
            .iter()
            .map(|line| line.as_str().unwrap().to_string())
            .collect::<Vec<_>>();
        return (actual == expected)
            .then_some(())
            .ok_or_else(|| format!("expected {expected:?}\n got {actual:?}"));
    }
    if let Some(prefix) = vector.get("expect_prefix").and_then(Value::as_str) {
        return (actual.len() == 1 && actual[0].starts_with(prefix))
            .then_some(())
            .ok_or_else(|| format!("expected {prefix}…, got {actual:?}"));
    }
    if let Some(export) = vector.get("expect_export") {
        let same = actual.len() == 3
            && export["first"] == json!(actual[0])
            && export["final"] == json!(actual[2])
            && export["document"] == canonical_export(&actual[1]);
        return same
            .then_some(())
            .ok_or_else(|| format!("export differs: {actual:?}"));
    }
    let summary = &vector["expect_summary"];
    let last = actual.last().unwrap();
    let mut same = summary["lines"] == json!(actual.len())
        && summary["last"].as_str() == Some(&last[..last.len().min(160)]);
    if let Some(digest) = summary.get("sha256") {
        same &= *digest
            == json!(hex::encode(cbus_cgate::auth::sha256(
                actual.join("\n").as_bytes()
            )));
    }
    same.then_some(())
        .ok_or_else(|| format!("summary differs: {} lines, last {last}", actual.len()))
}

#[test]
fn cgate_mock_matches_every_cgl_route_vector() {
    let vectors = vectors();
    assert_eq!(vectors.len(), 158);
    let mut failures = Vec::new();
    let mut group = String::new();
    let mut server = Server::new(AccessLevel::Program);
    for (index, vector) in vectors.iter().enumerate() {
        let name = vector["group"].as_str().unwrap();
        if name != group {
            group = name.to_string();
            server = Server::new(AccessLevel::Program);
        }
        let line = format!(
            "[{index}] {}",
            vector["command"]
                .as_str()
                .unwrap()
                .replace("<simulator>", SIMULATOR)
        );
        let document = vector["document"]
            .as_str()
            .map(str::to_string)
            .or_else(|| vector.get("document_generator").map(large_document));
        let response = match document {
            Some(document) => server.handle_document(&line, &document),
            None => server.handle(&line),
        };
        if let Err(error) = check(vector, &response) {
            failures.push(format!("{}: {error}", vector["id"]));
        }
    }
    assert!(failures.is_empty(), "{}", failures.join("\n"));
}

/// Six-hop one-way label interchange with the native creator identity.
///
/// Golden bytes live in
/// `testdata/vectors/cgate_cgl_sixhop_identity.jsonl`: the head export
/// carries the exact native `createdBy` build string with six-hop routes,
/// the one-way tail exports only itself, and a far-end import with a wrong
/// supplied route still lands only in the label graph. Export borrows the
/// model immutably (`&Server`), so it cannot touch PCI state; wire-level PCI
/// silence for this exchange is proven by
/// `service::tests::sixhop_cgl_identity_exchange_sends_no_pci_traffic`.
/// No physical-controller behavior is claimed: CGL moves labels only.
#[test]
fn sixhop_oneway_export_carries_native_creator_without_pci_traffic() {
    const NATIVE_CREATOR: &str = "C-Gate v3.4.0 (build 2001)";
    let rows: Vec<Value> = include_str!("../../testdata/vectors/cgate_cgl_sixhop_identity.jsonl")
        .lines()
        .map(|line| serde_json::from_str(line).unwrap())
        .collect();
    assert_eq!(rows.len(), 4);
    for (index, row) in rows.iter().enumerate() {
        assert_eq!(row["group"], json!("sixhop-identity"), "row {index}");
    }

    let mut server = Server::new(AccessLevel::Program);
    const SETUP: &[&str] = &[
        "PROJECT NEW CGLI",
        "PROJECT USE CGLI",
        "DBCREATENET 254 Local Cni <simulator>",
        "DBCREATENET 253 Hop1 Bridge 254/p/253",
        "DBCREATENET 252 Hop2 Bridge 253/p/252",
        "DBCREATENET 251 Hop3 Bridge 252/p/251",
        "DBCREATENET 250 Hop4 Bridge 251/p/250",
        "DBCREATENET 249 Hop5 Bridge 250/p/249",
        "DBCREATENET 248 Hop6 Bridge 249/p/248",
        "DBCREATENET 247 Hop7 Bridge 248/p/247",
        "DBCREATENET 240 Island Cni 127.0.0.2:29998",
        "DBADDSAFE //CGLI/254 Unit 253 Bridge253",
        "DBSETSAFE //CGLI/254/p/253/UnitType BRIDGE",
        "DBSETSAFE //CGLI/254/p/253/UnitName BRIDGE",
        "DBADDSAFE //CGLI/253 Unit 252 Bridge252",
        "DBSETSAFE //CGLI/253/p/252/UnitType BRIDGE",
        "DBSETSAFE //CGLI/253/p/252/UnitName BRIDGE",
        "DBADDSAFE //CGLI/252 Unit 251 Bridge251",
        "DBSETSAFE //CGLI/252/p/251/UnitType BRIDGE",
        "DBSETSAFE //CGLI/252/p/251/UnitName BRIDGE",
        "DBADDSAFE //CGLI/251 Unit 250 Bridge250",
        "DBSETSAFE //CGLI/251/p/250/UnitType BRIDGE",
        "DBSETSAFE //CGLI/251/p/250/UnitName BRIDGE",
        "DBADDSAFE //CGLI/250 Unit 249 Bridge249",
        "DBSETSAFE //CGLI/250/p/249/UnitType BRIDGE",
        "DBSETSAFE //CGLI/250/p/249/UnitName BRIDGE",
        "DBADDSAFE //CGLI/249 Unit 248 Bridge248",
        "DBSETSAFE //CGLI/249/p/248/UnitType BRIDGE",
        "DBSETSAFE //CGLI/249/p/248/UnitName BRIDGE",
        "DBADDSAFE //CGLI/248 Unit 247 Bridge247",
        "DBSETSAFE //CGLI/248/p/247/UnitType BRIDGE",
        "DBSETSAFE //CGLI/248/p/247/UnitName BRIDGE",
        "NET LOAD DB",
        "DBADDSAFE //CGLI/254 Application 56 Light",
        "DBADDSAFE //CGLI/254/56 Group 3 Hall",
        "DBADDSAFE //CGLI/254/56/3 Level 2 Wall",
    ];
    for (index, command) in SETUP.iter().enumerate() {
        let line = format!("[{index}] {}", command.replace("<simulator>", SIMULATOR));
        let response = server.handle(&line);
        assert!(response.status < 400, "{command}: {response:?}");
    }

    fn canonical(line: &str, creator: &str) -> Value {
        let mut document: Value = serde_json::from_str(&line[4..]).unwrap();
        assert_eq!(
            document["createdBy"].as_str(),
            Some(creator),
            "createdBy must match native"
        );
        document["createdTime"] = json!("<timestamp>");
        document
    }

    fn assert_no_pci_traces(response: &Response, label: &str) {
        for line in response
            .lines
            .iter()
            .chain(std::iter::once(&response.final_text))
        {
            assert!(
                !line.to_lowercase().contains("pci"),
                "{label} reached PCI state: {line}"
            );
            assert!(!line.starts_with("120-"), "{label} opened PCI: {line}");
        }
    }

    // Head export: every network reachable within six hops, with the native
    // creator identity and the far end still bare.
    let export = server.handle("[100] CGL EXPORT CGLI 254");
    assert_eq!(export.status, 344, "{export:?}");
    assert_no_pci_traces(&export, "head export");
    let expected = &rows[0]["expect_export"];
    assert_eq!(expected["first"].as_str(), Some(export.lines[0].as_str()));
    assert_eq!(expected["final"].as_str(), Some(export.final_text.as_str()));
    let document = canonical(&export.lines[1], NATIVE_CREATOR);
    assert_eq!(document, expected["document"]);
    let addresses = document["networks"]
        .as_array()
        .unwrap()
        .iter()
        .map(|network| network["address"].as_u64().unwrap())
        .collect::<Vec<_>>();
    assert_eq!(addresses, vec![254, 253, 252, 251, 250, 249, 248]);
    assert_eq!(
        document["networks"][6]["route"],
        json!([253, 252, 251, 250, 249, 248])
    );
    assert!(document["networks"][6].get("applications").is_none());

    // Export is read-only: a repeat carries the identical document.
    let repeat = server.handle("[101] CGL EXPORT CGLI 254");
    assert_eq!(canonical(&repeat.lines[1], NATIVE_CREATOR), document);

    // One-way tail: 247 is the seventh hop from 254, so it exports alone.
    let tail = server.handle("[102] CGL EXPORT CGLI 247");
    assert_eq!(tail.status, 344, "{tail:?}");
    assert_no_pci_traces(&tail, "tail export");
    let expected_tail = &rows[1]["expect_export"];
    assert_eq!(
        expected_tail["first"].as_str(),
        Some(tail.lines[0].as_str())
    );
    assert_eq!(
        expected_tail["final"].as_str(),
        Some(tail.final_text.as_str())
    );
    let tail_document = canonical(&tail.lines[1], NATIVE_CREATOR);
    assert_eq!(tail_document, expected_tail["document"]);
    assert_eq!(
        tail_document["networks"],
        json!([{"address": 247, "name": "Hop7"}])
    );

    // Far-end import: the supplied wrong route is ignored (native behavior),
    // the labels land six hops out, and nothing touches PCI state.
    let import_document = rows[2]["document"].as_str().unwrap();
    let import = server.handle_document("[103] CGL IMPORT CGLI", import_document);
    assert_eq!(import.status, 200, "{import:?}");
    assert_no_pci_traces(&import, "far-end import");
    let actual = import
        .lines
        .iter()
        .chain(std::iter::once(&import.final_text))
        .cloned()
        .collect::<Vec<_>>();
    let expected_lines = rows[2]["expect"]
        .as_array()
        .unwrap()
        .iter()
        .map(|line| line.as_str().unwrap().to_string())
        .collect::<Vec<_>>();
    assert_eq!(actual, expected_lines);

    // The far-end labels re-export with their exact six-hop route.
    let after = server.handle("[104] CGL EXPORT CGLI 254");
    assert_eq!(after.status, 344, "{after:?}");
    assert_no_pci_traces(&after, "post-import export");
    let expected_after = &rows[3]["expect_export"];
    assert_eq!(
        expected_after["final"].as_str(),
        Some(after.final_text.as_str())
    );
    let after_document = canonical(&after.lines[1], NATIVE_CREATOR);
    assert_eq!(after_document, expected_after["document"]);
    assert_eq!(
        after_document["networks"][6]["applications"],
        json!([{"address": 202, "type": 202, "name": "Trig", "groups": [
            {"address": 4, "name": "Four", "levels": [
                {"address": 5, "name": "Five"}]}]}])
    );

    // The import is idempotent: a repeat reports zero new objects.
    let again = server.handle_document("[105] CGL IMPORT CGLI", import_document);
    assert_eq!(again.status, 200, "{again:?}");
    assert!(
        again
            .lines
            .last()
            .is_some_and(|line| line.contains("0 object(s)")),
        "{again:?}"
    );

    // The tail is unaffected by the head-local import.
    let tail_again = server.handle("[106] CGL EXPORT CGLI 247");
    assert_eq!(
        canonical(&tail_again.lines[1], NATIVE_CREATOR),
        tail_document
    );
}
