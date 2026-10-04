//! Replays `cgate_cgl_routes.jsonl`, the CGL 1.1 wire vectors derived from
//! the owned native C-Gate 3.4.0.2001 capture, against the cgate-mock model.
//!
//! Each vector group starts from an empty server and runs in file order.
//! Setup rows only need to succeed; binding failures keep the native
//! prefix (Jackson exception detail is not reproduced); exports compare
//! JSON with generated metadata masked and exact Application order. The
//! remaining Group/Level order disposition is canonicalized separately.

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
        if let Some(applications) = network
            .get_mut("applications")
            .and_then(Value::as_array_mut)
        {
            for application in applications {
                if let Some(groups) = application.get_mut("groups") {
                    sort(groups, &["levels"]);
                }
            }
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
