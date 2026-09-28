use cbus_cgate::{AccessLevel, Server};
use serde_json::Value;

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

fn native_status(row: &Value) -> u16 {
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

fn native_xml(row: &Value) -> String {
    let tag = row["tag"].as_u64().unwrap();
    row["response_lines"][2]
        .as_str()
        .unwrap()
        .strip_prefix(&format!("[{tag}] 347-"))
        .unwrap()
        .trim_end_matches("\r\n")
        .to_string()
}

fn assert_read(server: &mut Server, row: &Value, copied_oid: Option<(&str, &str)>) {
    let command = row["command"].as_str().unwrap();
    let result = server.handle(&format!("[{}] {command}", row["tag"].as_u64().unwrap()));
    if native_status(row) == 401 {
        assert_eq!(result.status, 401, "{command}: {result:?}");
        return;
    }
    assert_eq!(result.status, 200, "{command}: {result:?}");
    let mut expected = native_xml(row);
    if let Some((native_oid, rust_oid)) = copied_oid {
        expected = expected.replace(native_oid, rust_oid);
    }
    let expected = roxmltree::Document::parse(&expected).unwrap();
    let observed =
        roxmltree::Document::parse(result.lines[0].strip_prefix("347-").unwrap()).unwrap();
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
        let field = |root: roxmltree::Node<'_, '_>| {
            root.children()
                .find(|child| child.has_tag_name(name))
                .and_then(|child| child.text())
                .map(str::to_string)
        };
        assert_eq!(field(observed), field(expected), "{command}: {name}");
    }
    let unit_address = |root: roxmltree::Node<'_, '_>| {
        root.children()
            .find(|child| {
                child.has_tag_name("PP") && child.attribute("Name") == Some("UnitAddress")
            })
            .and_then(|child| child.attribute("Value"))
            .map(str::to_string)
    };
    assert_eq!(
        unit_address(observed),
        unit_address(expected),
        "{command}: PP UnitAddress"
    );
}

#[test]
fn application_unit_shared_oid_mutations_match_owned_native_capture() {
    let native: Value = serde_json::from_str(include_str!(
        "../../testdata/fixtures/native_cgate_cross_kind_oid_mutations.json"
    ))
    .unwrap();
    assert_eq!(native["schema"], "native-cgate-cross-kind-oid-mutations-v1");
    assert_eq!(native["oracle"]["owned_loopback_listeners"], true);
    assert_eq!(native["oracle"]["cleanup_complete"], true);
    assert_eq!(native["oracle"]["physical_endpoint"], false);
    let vectors = include_str!("../../testdata/vectors/cgate_cross_kind_oid_mutations.jsonl")
        .lines()
        .map(|line| serde_json::from_str::<Value>(line).unwrap())
        .collect::<Vec<_>>();
    let cases = native["cases"].as_array().unwrap();
    assert_eq!(cases.len(), vectors.len());
    let mut server = Server::new(AccessLevel::Program);
    for row in native["setup"].as_array().unwrap().iter().take(3) {
        let result = server.handle(&format!(
            "[{}] {}",
            row["tag"].as_u64().unwrap(),
            row["command"].as_str().unwrap()
        ));
        assert!(matches!(result.status, 200 | 301), "{result:?}");
    }
    let baseline = server.handle("[baseline] DBGETXML //XCROSS/254");
    let baseline =
        roxmltree::Document::parse(baseline.lines[0].strip_prefix("347-").unwrap()).unwrap();
    let oid = |node: roxmltree::Node<'_, '_>| {
        node.children()
            .find(|child| child.has_tag_name("OID"))
            .unwrap()
            .text()
            .unwrap()
            .to_string()
    };
    let network_oid = oid(baseline.root_element());
    let interface_oid = oid(baseline
        .descendants()
        .find(|node| node.has_tag_name("Interface"))
        .unwrap());
    let substitute = |value: &str| {
        value
            .replace(native["network_oid"].as_str().unwrap(), &network_oid)
            .replace(native["interface_oid"].as_str().unwrap(), &interface_oid)
    };

    for (case, vector) in cases.iter().zip(vectors.iter()) {
        let name = case["name"].as_str().unwrap();
        assert_eq!(
            vector["name"],
            format!("{}_{}", case["submission_order"].as_str().unwrap(), name)
        );
        let reset = &case["reset"];
        let result = server.handle_document(
            &format!(
                "[{}] {}",
                reset["tag"].as_u64().unwrap(),
                reset["command"].as_str().unwrap()
            ),
            &substitute(&document(reset)),
        );
        assert_eq!(result.status, 301, "{}: {result:?}", vector["name"]);
        for row in case["before"].as_array().unwrap() {
            assert_read(&mut server, row, None);
        }
        assert_read(&mut server, &case["oid_before"], None);
        let applied = &case["applied"];
        let command = applied["command"].as_str().unwrap();
        assert!(command.starts_with(vector["command"].as_str().unwrap()));
        let line = format!("[{}] {command}", applied["tag"].as_u64().unwrap());
        let result = if name == "set_xml" {
            server.handle_document(&line, &document(applied))
        } else {
            server.handle(&line)
        };
        let copied_oid = if name == "copy_safe" {
            assert_eq!(result.status, 301, "{name}: {result:?}");
            Some((
                applied["response_lines"][0]
                    .as_str()
                    .unwrap()
                    .split("OID=")
                    .nth(1)
                    .unwrap()
                    .trim()
                    .to_string(),
                result
                    .final_text
                    .strip_prefix("301 OID=")
                    .unwrap()
                    .to_string(),
            ))
        } else {
            let native_receipt = applied["response_lines"][0]
                .as_str()
                .unwrap()
                .strip_prefix(&format!("[{}] ", applied["tag"].as_u64().unwrap()))
                .unwrap()
                .trim_end_matches("\r\n");
            assert_eq!(result.final_text, native_receipt, "{name}");
            None
        };
        let copied = copied_oid
            .as_ref()
            .map(|(original, observed)| (original.as_str(), observed.as_str()));
        for row in case["after"].as_array().unwrap() {
            assert_read(&mut server, row, copied);
        }
        assert_read(&mut server, &case["oid_after"], copied);
        for row in case["lifecycle"].as_array().unwrap() {
            let result = server.handle(&format!(
                "[{}] {}",
                row["tag"].as_u64().unwrap(),
                row["command"].as_str().unwrap()
            ));
            assert_eq!(result.status, 200, "{name}: {result:?}");
        }
        for row in case["reloaded"].as_array().unwrap() {
            assert_read(&mut server, row, copied);
        }
        assert_read(&mut server, &case["oid_reloaded"], copied);
    }
}
