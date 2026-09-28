use cbus_cgate::{AccessLevel, Server};
use serde_json::Value;

fn status(row: &Value) -> u16 {
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

fn document(row: &Value) -> String {
    let tag = row["tag"].as_u64().unwrap();
    row["request"]
        .as_str()
        .unwrap()
        .split_once(&format!(" << END{tag}\r\n"))
        .unwrap()
        .1
        .strip_suffix(&format!("\r\nEND{tag}\r\n"))
        .unwrap()
        .to_string()
}

fn xml(row: &Value) -> String {
    let tag = row["tag"].as_u64().unwrap();
    row["response_lines"][2]
        .as_str()
        .unwrap()
        .strip_prefix(&format!("[{tag}] 347-"))
        .unwrap()
        .trim_end_matches("\r\n")
        .to_string()
}

fn field(node: roxmltree::Node<'_, '_>, name: &str) -> Option<String> {
    node.children()
        .find(|child| child.has_tag_name(name))
        .and_then(|child| child.text())
        .map(str::to_string)
}

fn assert_read(server: &mut Server, row: &Value, copied_oid: Option<(&str, &str)>) {
    let command = row["command"].as_str().unwrap();
    let response = server.handle(&format!("[{}] {command}", row["tag"].as_u64().unwrap()));
    if status(row) == 401 {
        assert_eq!(response.status, 401, "{command}: {response:?}");
        return;
    }
    assert_eq!(status(row), 344, "{command}");
    assert_eq!(response.status, 200, "{command}: {response:?}");
    let mut expected = xml(row);
    if let Some((native, rust)) = copied_oid {
        expected = expected.replace(native, rust);
    }
    let expected = roxmltree::Document::parse(&expected).unwrap();
    let observed =
        roxmltree::Document::parse(response.lines[0].strip_prefix("347-").unwrap()).unwrap();
    let expected = expected.root_element();
    let observed = observed.root_element();
    assert_eq!(
        observed.tag_name().name(),
        expected.tag_name().name(),
        "{command}"
    );
    for name in [
        "OID",
        "TagName",
        "Address",
        "UnitType",
        "UnitName",
        "FirmwareVersion",
    ] {
        assert_eq!(
            field(observed, name),
            field(expected, name),
            "{command}: {name}"
        );
    }
    let pp_address = |node: roxmltree::Node<'_, '_>| {
        node.children()
            .find(|child| {
                child.has_tag_name("PP") && child.attribute("Name") == Some("UnitAddress")
            })
            .and_then(|child| child.attribute("Value"))
            .map(str::to_string)
    };
    assert_eq!(
        pp_address(observed),
        pp_address(expected),
        "{command}: PP UnitAddress"
    );
}

#[test]
fn nine_and_ten_unit_oid_mutations_match_owned_native_capture() {
    let native: Value = serde_json::from_str(include_str!(
        "../../testdata/fixtures/native_cgate_duplicate_unit_oid_nine_ten.json"
    ))
    .unwrap();
    assert_eq!(
        native["schema"],
        "native-cgate-duplicate-unit-oid-nine-ten-v1"
    );
    assert_eq!(native["oracle"]["owned_loopback_listeners"], true);
    assert_eq!(native["oracle"]["cleanup_complete"], true);
    assert_eq!(native["oracle"]["physical_endpoint"], false);
    let vectors = include_str!("../../testdata/vectors/cgate_duplicate_unit_oid_nine_ten.jsonl")
        .lines()
        .map(|line| serde_json::from_str::<Value>(line).unwrap())
        .collect::<Vec<_>>();
    let cases = native["cases"].as_array().unwrap();
    assert_eq!(cases.len(), vectors.len());

    let mut server = Server::new(AccessLevel::Program);
    for row in native["setup"].as_array().unwrap().iter().take(3) {
        let response = server.handle(&format!(
            "[{}] {}",
            row["tag"].as_u64().unwrap(),
            row["command"].as_str().unwrap()
        ));
        assert!(matches!(response.status, 200 | 301), "{response:?}");
    }
    let baseline = server.handle("[baseline] DBGETXML //XUNINE/254");
    let baseline =
        roxmltree::Document::parse(baseline.lines[0].strip_prefix("347-").unwrap()).unwrap();
    let network_oid = field(baseline.root_element(), "OID").unwrap();
    let interface_oid = field(
        baseline
            .descendants()
            .find(|node| node.has_tag_name("Interface"))
            .unwrap(),
        "OID",
    )
    .unwrap();
    let replace_oids = |value: &str| {
        value
            .replace(native["network_oid"].as_str().unwrap(), &network_oid)
            .replace(native["interface_oid"].as_str().unwrap(), &interface_oid)
    };

    for (case, vector) in cases.iter().zip(vectors.iter()) {
        let name = case["name"].as_str().unwrap();
        let submitted = case["submitted_addresses"].as_array().unwrap();
        assert_eq!(case["submitted_addresses"], vector["submitted_addresses"]);
        assert_eq!(
            vector["name"],
            format!(
                "{}_{}",
                if submitted.len() == 9 { "nine" } else { "ten" },
                name
            )
        );
        assert_eq!(vector["selected_address"], 22);
        assert!(matches!(submitted.len(), 9 | 10));
        let reset = &case["reset"];
        let response = server.handle_document(
            &format!(
                "[{}] {}",
                reset["tag"].as_u64().unwrap(),
                reset["command"].as_str().unwrap()
            ),
            &replace_oids(&document(reset)),
        );
        assert_eq!(response.status, 301, "{name}: {response:?}");
        for row in case["before"].as_array().unwrap() {
            assert_read(&mut server, row, None);
        }
        assert_read(&mut server, &case["oid_before"], None);

        let applied = &case["applied"];
        let command = applied["command"].as_str().unwrap();
        assert!(command.starts_with(vector["command"].as_str().unwrap()));
        let line = format!("[{}] {command}", applied["tag"].as_u64().unwrap());
        let response = if name == "set_xml" {
            server.handle_document(&line, &document(applied))
        } else {
            server.handle(&line)
        };
        assert_eq!(response.status, status(applied), "{name}: {response:?}");
        let native_receipt = applied["response_lines"][0]
            .as_str()
            .unwrap()
            .strip_prefix(&format!("[{}] ", applied["tag"].as_u64().unwrap()))
            .unwrap()
            .trim_end_matches("\r\n");
        let copied_oid = if name == "copy_safe" {
            Some((
                native_receipt.strip_prefix("301 OID=").unwrap(),
                response
                    .final_text
                    .strip_prefix("301 OID=")
                    .unwrap()
                    .to_string(),
            ))
        } else {
            assert_eq!(response.final_text, native_receipt, "{name}");
            None
        };
        let copied_oid = copied_oid
            .as_ref()
            .map(|(native, rust)| (*native, rust.as_str()));
        for row in case["after"].as_array().unwrap() {
            assert_read(&mut server, row, copied_oid);
        }
        assert_read(&mut server, &case["oid_after"], copied_oid);
        for row in case["lifecycle"].as_array().unwrap() {
            let response = server.handle(&format!(
                "[{}] {}",
                row["tag"].as_u64().unwrap(),
                row["command"].as_str().unwrap()
            ));
            assert_eq!(response.status, 200, "{name}: {response:?}");
        }
        for row in case["reloaded"].as_array().unwrap() {
            assert_read(&mut server, row, copied_oid);
        }
        assert_read(&mut server, &case["oid_reloaded"], copied_oid);
    }
}
