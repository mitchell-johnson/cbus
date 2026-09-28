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
fn seven_and_eight_unit_oid_mutations_match_owned_native_capture() {
    let native: Value = serde_json::from_str(include_str!(
        "../../testdata/fixtures/native_cgate_large_cross_network_oid.json"
    ))
    .unwrap();
    assert_eq!(native["schema"], "native-cgate-large-cross-network-oid-v1");
    assert_eq!(native["oracle"]["owned_loopback_listeners"], true);
    assert_eq!(native["oracle"]["cleanup_complete"], true);
    assert_eq!(native["oracle"]["physical_endpoint"], false);
    let vectors = include_str!("../../testdata/vectors/cgate_large_unit_oid.jsonl")
        .lines()
        .map(|line| serde_json::from_str::<Value>(line).unwrap())
        .collect::<Vec<_>>();
    let cases = native["cardinality"].as_array().unwrap();
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
    let baseline = server.handle("[baseline] DBGETXML //XULARGE/254");
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
            .replace(
                native["network_oids"]["254"].as_str().unwrap(),
                &network_oid,
            )
            .replace(
                native["interface_oids"]["254"].as_str().unwrap(),
                &interface_oid,
            )
    };

    for (case, vector) in cases.iter().zip(vectors.iter()) {
        let name = case["name"].as_str().unwrap();
        let submitted = case["submitted_addresses"].as_array().unwrap();
        assert_eq!(case["submitted_addresses"], vector["submitted_addresses"]);
        assert_eq!(
            vector["name"],
            format!(
                "{}_{}",
                if submitted.len() == 7 {
                    "seven"
                } else {
                    "eight"
                },
                name
            )
        );
        assert_eq!(vector["selected_address"], 22);
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

fn assert_cross_read(server: &mut Server, row: &Value, copied_oid: Option<(&str, &str)>) {
    let command = row["command"].as_str().unwrap();
    let result = server.handle(&format!("[{}] {command}", row["tag"].as_u64().unwrap()));
    if status(row) == 401 {
        assert_eq!(result.status, 401, "{command}: {result:?}");
        return;
    }
    assert_eq!(status(row), 344, "{command}");
    assert_eq!(result.status, 200, "{command}: {result:?}");
    let mut expected = xml(row);
    if let Some((native, rust)) = copied_oid {
        expected = expected.replace(native, rust);
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
fn two_network_unit_and_application_oid_mutations_match_owned_native_capture() {
    let native: Value = serde_json::from_str(include_str!(
        "../../testdata/fixtures/native_cgate_large_cross_network_oid.json"
    ))
    .unwrap();
    let vectors = include_str!("../../testdata/vectors/cgate_cross_network_oid.jsonl")
        .lines()
        .map(|line| serde_json::from_str::<Value>(line).unwrap())
        .collect::<Vec<_>>();
    let cases = native["cross_network"].as_array().unwrap();
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
    let created = &native["created_second_network"];
    let result = server.handle(&format!(
        "[{}] {}",
        created["tag"].as_u64().unwrap(),
        created["command"].as_str().unwrap()
    ));
    assert!(matches!(result.status, 200 | 301), "{result:?}");
    let mut replacements = Vec::new();
    for network in [253, 254] {
        let response = server.handle(&format!(
            "[baseline-{network}] DBGETXML //XULARGE/{network}"
        ));
        let baseline =
            roxmltree::Document::parse(response.lines[0].strip_prefix("347-").unwrap()).unwrap();
        let native_network = native["network_oids"][network.to_string()]
            .as_str()
            .unwrap();
        let native_interface = native["interface_oids"][network.to_string()]
            .as_str()
            .unwrap();
        replacements.push((
            native_network.to_string(),
            field(baseline.root_element(), "OID").unwrap(),
        ));
        replacements.push((
            native_interface.to_string(),
            field(
                baseline
                    .descendants()
                    .find(|node| node.has_tag_name("Interface"))
                    .unwrap(),
                "OID",
            )
            .unwrap(),
        ));
    }
    let substitute = |value: &str| {
        replacements
            .iter()
            .fold(value.to_string(), |current, (native, rust)| {
                current.replace(native, rust)
            })
    };
    for (case, vector) in cases.iter().zip(vectors.iter()) {
        let name = vector["name"].as_str().unwrap();
        assert_eq!(case["accepted"], true, "{name}");
        assert_eq!(
            case["selected_network"], vector["selected_network"],
            "{name}"
        );
        assert_eq!(case["selected_kind"], vector["selected_kind"], "{name}");
        for row in case["cleared"]
            .as_array()
            .unwrap()
            .iter()
            .chain(case["inserts"].as_array().unwrap())
        {
            let result = server.handle_document(
                &format!(
                    "[{}] {}",
                    row["tag"].as_u64().unwrap(),
                    row["command"].as_str().unwrap()
                ),
                &substitute(&document(row)),
            );
            assert_eq!(result.status, status(row), "{name}: {result:?}");
        }
        for row in case["before"].as_array().unwrap() {
            assert_cross_read(&mut server, row, None);
        }
        assert_cross_read(&mut server, &case["oid_before"], None);
        let applied = &case["applied"];
        let command = applied["command"].as_str().unwrap();
        assert!(
            command.starts_with(vector["command"].as_str().unwrap()),
            "{name}"
        );
        let line = format!("[{}] {command}", applied["tag"].as_u64().unwrap());
        let result = if command.starts_with("DBSETXML ") {
            server.handle_document(&line, &document(applied))
        } else {
            server.handle(&line)
        };
        assert_eq!(result.status, status(applied), "{name}: {result:?}");
        let receipt = applied["response_lines"]
            .as_array()
            .unwrap()
            .last()
            .unwrap()
            .as_str()
            .unwrap()
            .strip_prefix(&format!("[{}] ", applied["tag"].as_u64().unwrap()))
            .unwrap()
            .trim_end_matches("\r\n");
        let copied_oid = if case["name"] == "copy_safe" {
            Some((
                receipt.strip_prefix("301 OID=").unwrap().to_string(),
                result
                    .final_text
                    .strip_prefix("301 OID=")
                    .unwrap()
                    .to_string(),
            ))
        } else {
            assert_eq!(result.final_text, receipt, "{name}");
            None
        };
        let copied = copied_oid
            .as_ref()
            .map(|(native, rust)| (native.as_str(), rust.as_str()));
        for row in case["after"].as_array().unwrap() {
            assert_cross_read(&mut server, row, copied);
        }
        assert_cross_read(&mut server, &case["oid_after"], copied);
        for row in case["lifecycle"].as_array().unwrap() {
            let result = server.handle(&format!(
                "[{}] {}",
                row["tag"].as_u64().unwrap(),
                row["command"].as_str().unwrap()
            ));
            assert_eq!(result.status, status(row), "{name}: {result:?}");
        }
        for row in case["reloaded"].as_array().unwrap() {
            assert_cross_read(&mut server, row, copied);
        }
        assert_cross_read(&mut server, &case["oid_reloaded"], copied);
    }
}

#[test]
fn uncaptured_eleven_unit_and_same_address_cross_network_shapes_are_rejected_atomically() {
    const OID: &str = "11111111-1111-4111-8111-111111111111";
    let mut server = Server::new(AccessLevel::Program);
    let created = server.handle("[guard] PROJECT NEW XGUARD");
    assert_eq!(created.status, 200, "{created:?}");
    assert_eq!(server.handle("[guard] PROJECT USE XGUARD").status, 200);
    for network in [254, 253] {
        assert!(matches!(
            server
                .handle(&format!(
                    "[guard] DBCREATENET {network} Local Cni 127.0.0.1:1"
                ))
                .status,
            200 | 301
        ));
    }
    let prefix = |server: &mut Server, network: u8| {
        let result = server.handle(&format!("[guard] DBGETXML //XGUARD/{network}"));
        let xml =
            roxmltree::Document::parse(result.lines[0].strip_prefix("347-").unwrap()).unwrap();
        let oid = field(xml.root_element(), "OID").unwrap();
        let interface = xml
            .descendants()
            .find(|node| node.has_tag_name("Interface"))
            .unwrap();
        let interface_oid = field(interface, "OID").unwrap();
        format!(
            "<Network><OID>{oid}</OID><TagName>Local</TagName><Address>{network}</Address>\
             <NetworkNumber>{network}</NetworkNumber><Interface><OID>{interface_oid}</OID>\
             <InterfaceType>Cni</InterfaceType><InterfaceAddress>127.0.0.1:1</InterfaceAddress>\
             </Interface>"
        )
    };
    let unit = |address: u8| {
        format!(
            "<Unit><OID>{OID}</OID><TagName>Unit{address}</TagName><Address>{address}</Address>\
             <UnitType>KEYE1</UnitType><UnitName>Room</UnitName>\
             <FirmwareVersion>1.2.67</FirmwareVersion></Unit>"
        )
    };
    let network254 = prefix(&mut server, 254);
    let eleven = format!(
        "{}{}{}",
        network254,
        (20..31).map(&unit).collect::<String>(),
        "</Network>"
    );
    assert_eq!(
        server
            .handle_document("[guard] DBSETXML //XGUARD/254", &eleven)
            .status,
        409
    );
    assert_eq!(
        server.handle("[guard] DBGETXML //XGUARD/254/p/20").status,
        401
    );

    // The larger pure-Unit capture does not admit a new mixed shape.
    let mixed_nine = format!(
        "{}<Application><OID>{OID}</OID><TagName>Lighting</TagName><Address>56</Address></Application>{}</Network>",
        network254,
        (20..29).map(&unit).collect::<String>(),
    );
    assert_eq!(
        server
            .handle_document("[guard] DBSETXML //XGUARD/254", &mixed_nine)
            .status,
        409
    );
    assert_eq!(
        server.handle("[guard] DBGETXML //XGUARD/254/p/20").status,
        401
    );

    let first = format!("{}{}</Network>", network254, unit(20));
    assert_eq!(
        server
            .handle_document("[guard] DBSETXML //XGUARD/254", &first)
            .status,
        301
    );
    let second = format!("{}{}</Network>", prefix(&mut server, 253), unit(20));
    assert_eq!(
        server
            .handle_document("[guard] DBSETXML //XGUARD/253", &second)
            .status,
        409
    );
    assert_eq!(
        server.handle("[guard] DBGETXML //XGUARD/253/p/20").status,
        401
    );
    assert_eq!(
        server.handle("[guard] DBGETXML //XGUARD/254/p/20").status,
        200
    );
}
