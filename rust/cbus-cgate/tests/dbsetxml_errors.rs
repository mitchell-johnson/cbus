//! Replays the owned native C-Gate 3.4 DBSETXML error and conflict matrix.
//!
//! Every vector in `cgate_dbsetxml_errors.jsonl` names a captured request.
//! A refused request must leave both the Network and the Unit unchanged;
//! between vectors, PROJECT CLOSE/LOAD restores the saved baseline exactly
//! as it did on native C-Gate.

use cbus_cgate::{AccessLevel, Server};

fn fixture() -> serde_json::Value {
    serde_json::from_str(include_str!(
        "../../testdata/fixtures/native_cgate_dbsetxml_errors.json"
    ))
    .unwrap()
}

fn vectors() -> Vec<serde_json::Value> {
    include_str!("../../testdata/vectors/cgate_dbsetxml_errors.jsonl")
        .lines()
        .map(|line| serde_json::from_str(line).unwrap())
        .collect()
}

fn request(native: &serde_json::Value, tag: u64) -> (String, String) {
    let row = native["cases"]
        .as_array()
        .unwrap()
        .iter()
        .find(|row| row["tag"].as_u64() == Some(tag))
        .unwrap();
    let request = row["request"].as_str().unwrap();
    let (head, rest) = request.split_once(&format!(" << END{tag}\r\n")).unwrap();
    let document = rest.strip_suffix(&format!("\r\nEND{tag}\r\n")).unwrap();
    (head.to_string(), document.to_string())
}

#[test]
fn dbsetxml_error_matrix_matches_native_statuses_without_mutation() {
    let native = fixture();
    assert_eq!(native["schema"], "native-cgate-dbsetxml-errors-v1");
    let vectors = vectors();
    assert_eq!(vectors.len(), 44);
    let mut server = Server::new(AccessLevel::Program);
    for line in [
        "[1] PROJECT NEW XERR",
        "[2] PROJECT USE XERR",
        "[3] DBCREATENET 254 Local Cni 127.0.0.1:1",
    ] {
        assert_eq!(server.handle(line).status, 200, "{line}");
    }
    let initial = server.handle("[4] DBGETXML //XERR/254");
    let parsed =
        roxmltree::Document::parse(initial.lines[0].strip_prefix("347-").unwrap()).unwrap();
    let oid = |node: roxmltree::Node<'_, '_>| {
        node.children()
            .find(|child| child.has_tag_name("OID"))
            .unwrap()
            .text()
            .unwrap()
            .to_string()
    };
    let network_oid = oid(parsed.root_element());
    let interface_oid = oid(parsed
        .descendants()
        .find(|node| node.has_tag_name("Interface"))
        .unwrap());
    let substitute = |value: &str| {
        value
            .replace(native["network_oid"].as_str().unwrap(), &network_oid)
            .replace(native["interface_oid"].as_str().unwrap(), &interface_oid)
    };
    let (_, base) = request(&native, 104);
    assert_eq!(
        server
            .handle_document("[5] DBSETXML //XERR/254", &substitute(&base))
            .status,
        301
    );
    assert_eq!(server.handle("[6] PROJECT SAVE XERR").status, 200);
    let reads = ["DBGETXML //XERR/254", "DBGETXML //XERR/254/p/20"];
    let snapshot = |server: &mut Server| {
        reads
            .iter()
            .map(|read| server.handle(&format!("[r] {read}")).lines)
            .collect::<Vec<_>>()
    };
    let baseline = snapshot(&mut server);
    for vector in vectors {
        let name = vector["name"].as_str().unwrap();
        let tag = vector["set_tag"].as_u64().unwrap();
        let (head, document) = request(&native, tag);
        let response = server.handle_document(&substitute(&head), &substitute(&document));
        assert_eq!(
            u64::from(response.status),
            vector["rust_status"].as_u64().unwrap(),
            "{name}: {response:?}"
        );
        if vector["disposition"]
            .as_str()
            .unwrap()
            .starts_with("native")
        {
            assert_eq!(
                u64::from(response.status),
                vector["native_status"].as_u64().unwrap(),
                "{name}"
            );
        }
        if let Some(reply) = vector["rust_reply"].as_str() {
            assert_eq!(response.final_text, reply, "{name}");
        }
        if let Some(prefix) = vector["rust_reply_prefix"].as_str() {
            assert!(
                response.final_text.starts_with(prefix),
                "{name}: {response:?}"
            );
        }
        if response.status >= 400 {
            assert_eq!(
                snapshot(&mut server),
                baseline,
                "{name} mutated the database"
            );
        }
        for line in [
            "[c] PROJECT CLOSE XERR",
            "[l] PROJECT LOAD XERR",
            "[u] PROJECT USE XERR",
        ] {
            assert_eq!(server.handle(line).status, 200, "{name}: {line}");
        }
        assert_eq!(snapshot(&mut server), baseline, "{name} was not reverted");
    }
}
