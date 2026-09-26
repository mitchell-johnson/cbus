use cbus_cgate::{format_response, AccessLevel, Server};
use serde_json::Value;

struct Fixture {
    name: &'static str,
    schema: &'static str,
    setup_count: usize,
    row_count: usize,
    source: &'static str,
}

const FIXTURES: [Fixture; 5] = [
    Fixture {
        name: "show-audit",
        schema: "native-cgate-show-audit-v1",
        setup_count: 13,
        row_count: 69,
        source: include_str!("../../testdata/fixtures/native_cgate_show_audit.json"),
    },
    Fixture {
        name: "show-appclasses",
        schema: "native-cgate-show-application-classes-v1",
        setup_count: 16,
        row_count: 78,
        source: include_str!("../../testdata/fixtures/native_cgate_show_appclasses.json"),
    },
    Fixture {
        name: "show-parser",
        schema: "native-cgate-show-tree-parser-v1",
        setup_count: 0,
        row_count: 18,
        source: include_str!("../../testdata/fixtures/native_cgate_show_parser.json"),
    },
    Fixture {
        name: "new-bounds",
        schema: "native-cgate-new-bounds-v1",
        setup_count: 0,
        row_count: 25,
        source: include_str!("../../testdata/fixtures/native_cgate_new_bounds.json"),
    },
    Fixture {
        name: "tree-appclasses",
        schema: "native-cgate-tree-application-classes-v1",
        setup_count: 18,
        row_count: 3,
        source: include_str!("../../testdata/fixtures/native_cgate_tree_appclasses.json"),
    },
];

#[derive(Clone, Copy, Default)]
struct Volatility {
    cgate_metrics: bool,
    network_next_sync_time: bool,
    clock_next_update_time: bool,
}

fn volatility(document: &Value, fixture: &str) -> Volatility {
    let mut result = Volatility::default();
    let declarations = document["oracle"]["volatile_values"]
        .as_array()
        .map(Vec::as_slice)
        .unwrap_or_default();
    for declaration in declarations {
        match declaration.as_str().expect("volatile declaration is text") {
            "cgate ComputerName/IPAddress/memory/thread values" => result.cgate_metrics = true,
            "network NextSyncTime" => result.network_next_sync_time = true,
            "Clock PrimaryMasterNextUpdateTime" => result.clock_next_update_time = true,
            other => panic!("{fixture}: unsupported volatile oracle declaration {other:?}"),
        }
    }
    result
}

fn field_value<'a>(line: &'a str, field: &str) -> Option<&'a str> {
    let marker = format!(": {field}=");
    line.find(&marker)
        .map(|offset| &line[offset + marker.len()..])
}

fn normalize_field(line: &str, field: &str, replacement: &str) -> Option<String> {
    let marker = format!(": {field}=");
    line.find(&marker)
        .map(|offset| format!("{}{replacement}", &line[..offset + marker.len()]))
}

fn normalize(line: &str, volatile: Volatility) -> String {
    if volatile.cgate_metrics && line.contains("cgate: ") {
        for field in [
            "ComputerName",
            "IPAddress",
            "MemoryFree",
            "MemoryMaximum",
            "MemoryTotal",
            "MemoryUsed",
            "Threads",
        ] {
            if let Some(normalized) = normalize_field(line, field, "<volatile-cgate>") {
                return normalized;
            }
        }
    }
    if volatile.network_next_sync_time {
        if let Some(normalized) = normalize_field(line, "NextSyncTime", "<scheduled>") {
            return normalized;
        }
    }
    if volatile.clock_next_update_time {
        if let Some(normalized) =
            normalize_field(line, "PrimaryMasterNextUpdateTime", "<scheduled>")
        {
            return normalized;
        }
    }
    line.to_string()
}

fn assert_native_timestamp(value: &str, context: &str) {
    let bytes = value.as_bytes();
    assert!(
        bytes.len() == 15
            && bytes[0..8].iter().all(u8::is_ascii_digit)
            && bytes[8] == b'-'
            && bytes[9..15].iter().all(u8::is_ascii_digit),
        "{context}: dynamic timestamp {value:?} does not match ^[0-9]{{8}}-[0-9]{{6}}$"
    );
}

fn assert_actual_timestamps(lines: &[String], volatile: Volatility, context: &str) {
    for line in lines {
        if volatile.network_next_sync_time {
            if let Some(value) = field_value(line, "NextSyncTime") {
                assert_native_timestamp(value, context);
            }
        }
        if volatile.clock_next_update_time {
            if let Some(value) = field_value(line, "PrimaryMasterNextUpdateTime") {
                assert_native_timestamp(value, context);
            }
        }
    }
}

fn assert_cgate_metric_shapes(lines: &[String], volatile: Volatility, context: &str) {
    if !volatile.cgate_metrics || !lines.iter().any(|line| line.contains("cgate: Memory")) {
        return;
    }
    let value = |field| {
        let values = lines
            .iter()
            .filter_map(|line| {
                line.contains("cgate: ")
                    .then(|| field_value(line, field))
                    .flatten()
            })
            .collect::<Vec<_>>();
        assert_eq!(
            values.len(),
            1,
            "{context}: expected one volatile cgate {field} row"
        );
        values[0]
    };

    let computer_name = value("ComputerName");
    assert!(
        !computer_name.is_empty()
            && !computer_name.chars().any(char::is_control)
            && (computer_name == "null"
                || computer_name.chars().all(
                    |character| character.is_ascii_alphanumeric() || ".-_".contains(character)
                )),
        "{context}: invalid ComputerName shape {computer_name:?}"
    );

    let ip_address = value("IPAddress");
    let octets = ip_address
        .split('.')
        .map(str::parse::<u8>)
        .collect::<Result<Vec<_>, _>>();
    assert!(
        ip_address == "null" || octets.is_ok_and(|octets| octets.len() == 4),
        "{context}: invalid IPv4 address {ip_address:?}"
    );

    for field in ["MemoryFree", "MemoryMaximum", "MemoryTotal", "MemoryUsed"] {
        let metric = value(field);
        assert!(
            metric.parse::<u64>().is_ok(),
            "{context}: {field} is not an unsigned integer: {metric:?}"
        );
    }
    let threads = value("Threads");
    assert!(
        threads.parse::<u64>().is_ok_and(|count| count > 0),
        "{context}: Threads is not a positive integer: {threads:?}"
    );
}

fn parser_same_state_baseline(fixture: &str, phase: &str, index: usize) -> Option<&'static str> {
    match (fixture, phase, index) {
        ("show-parser", "rows", 11 | 12) => Some("TREE //AUDS2/254"),
        ("show-parser", "rows", 13) => Some("REPORT //AUDS2/254"),
        _ => None,
    }
}

fn replay_entries(
    server: &mut Server,
    fixture: &str,
    phase: &str,
    entries: &[Value],
    volatile: Volatility,
) {
    for (index, row) in entries.iter().enumerate() {
        let command = row["command"].as_str().expect("fixture command is text");
        let tag = format!("native-{fixture}-{phase}-{index}");
        let response = server.handle(&format!("[{tag}] {command}"));
        let context = format!("{fixture}/{phase}[{index}] {command}");
        assert_eq!(
            u64::from(response.status),
            row["code"].as_u64().expect("fixture code is numeric"),
            "{context}: status"
        );

        let actual_wire = format_response(&response);
        assert!(
            actual_wire.ends_with('\n'),
            "{context}: formatted response lost its line terminator"
        );
        let actual = actual_wire.lines().map(str::to_string).collect::<Vec<_>>();
        assert!(
            actual
                .iter()
                .all(|line| line.starts_with(&format!("[{tag}] "))),
            "{context}: formatted response contains an untagged line: {actual:?}"
        );
        assert_actual_timestamps(&actual, volatile, &context);
        assert_cgate_metric_shapes(&actual, volatile, &context);

        let fixture_lines = row["lines"].as_array().expect("fixture lines are an array");
        assert_eq!(
            fixture_lines.last().and_then(Value::as_str),
            row["final"].as_str(),
            "{context}: fixture final line"
        );
        if let Some(baseline_command) = parser_same_state_baseline(fixture, phase, index) {
            let baseline = server.handle(&format!("[{tag}] {baseline_command}"));
            assert_eq!(
                response.status, baseline.status,
                "{context}: same-state baseline status for {baseline_command}"
            );
            assert_eq!(
                actual_wire,
                format_response(&baseline),
                "{context}: differs from same-state baseline {baseline_command}"
            );
            continue;
        }
        let expected = fixture_lines
            .iter()
            .map(|line| {
                format!(
                    "[{tag}] {}",
                    line.as_str().expect("fixture response line is text")
                )
            })
            .collect::<Vec<_>>();
        let actual = actual
            .iter()
            .map(|line| normalize(line, volatile))
            .collect::<Vec<_>>();
        let expected = expected
            .iter()
            .map(|line| normalize(line, volatile))
            .collect::<Vec<_>>();
        assert_eq!(actual, expected, "{context}: exact tagged response");
    }
}

#[test]
fn retained_show_new_and_tree_matrices_match_exact_tagged_output() {
    let mut server = Server::new(AccessLevel::Program).with_programming(true);
    for fixture in FIXTURES {
        let document: Value =
            serde_json::from_str(fixture.source).expect("native fixture is valid JSON");
        assert_eq!(document["schema"], fixture.schema, "{}", fixture.name);
        let setup = document["setup"]
            .as_array()
            .map(Vec::as_slice)
            .unwrap_or(&[]);
        let rows = document["rows"]
            .as_array()
            .expect("fixture rows are an array");
        assert_eq!(setup.len(), fixture.setup_count, "{} setup", fixture.name);
        assert_eq!(rows.len(), fixture.row_count, "{} rows", fixture.name);
        assert_eq!(document["oracle"]["version"], "3.4.0", "{}", fixture.name);
        assert_eq!(document["oracle"]["build"], 2001, "{}", fixture.name);
        assert_eq!(
            document["oracle"]["jar_sha256"],
            "3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630",
            "{}",
            fixture.name
        );
        let volatile = volatility(&document, fixture.name);
        replay_entries(&mut server, fixture.name, "setup", setup, volatile);
        replay_entries(&mut server, fixture.name, "rows", rows, volatile);
    }
}

fn assert_tagged_single_line_wire(wire: &str, tag: &str) {
    assert!(wire.ends_with('\n'));
    assert!(!wire.contains('\r'), "wire contains a raw carriage return");
    let prefix = format!("[{tag}] ");
    assert!(
        wire.lines().all(|line| line.starts_with(&prefix)),
        "an injected line escaped the response tag: {wire:?}"
    );
}

#[test]
fn show_and_treexml_escape_cr_lf_before_tagged_wire_formatting() {
    let mut server = Server::new(AccessLevel::Program).with_programming(true);
    for (tag, command) in [
        ("project", "PROJECT NEW INJECT"),
        ("use", "PROJECT USE INJECT"),
        ("network", "NET CREATE 254 cni 127.0.0.1:9"),
        ("group", "NEW GROUP //INJECT/254/56/1"),
        ("unit", "NEW UNIT //INJECT/254/p/20 BOGUS opaque"),
    ] {
        assert_eq!(
            server.handle(&format!("[{tag}] {command}")).status,
            200,
            "{command}"
        );
    }

    assert_eq!(
        server
            .handle_document(
                "[set-group-name] DBSETXML //INJECT/254/56/1/Name",
                "first\rsecond\nthird",
            )
            .status,
        200
    );
    let show_wire = format_response(&server.handle("[show-injection] SHOW //INJECT/254/56/1 Name"));
    assert_eq!(
        show_wire,
        "[show-injection] 300 //INJECT/254/56/1: Name=first\\rsecond\\nthird\n"
    );
    assert_tagged_single_line_wire(&show_wire, "show-injection");
    assert_eq!(show_wire.lines().count(), 1);

    assert_eq!(
        server
            .handle_document(
                "[set-unit-name] DBSETXML //INJECT/254/p/20/UnitName",
                "unit\rname",
            )
            .status,
        200
    );
    assert_eq!(
        server
            .handle_document(
                "[set-unit-type] DBSETXML //INJECT/254/p/20/UnitType",
                "BOGUS\rTYPE",
            )
            .status,
        200
    );
    assert_eq!(
        server
            .handle_document(
                "[set-unit-state] DBSETXML //INJECT/254/p/20/State",
                "error\rSTATE",
            )
            .status,
        200
    );
    // A multiline unit document remains opaque and cannot become an XML row.
    assert_eq!(
        server
            .handle_document(
                "[set-part-name] DBSETXML //INJECT/254/p/20/PartName",
                "blocked\nline",
            )
            .status,
        200
    );

    let tree_wire = format_response(&server.handle("[tree-injection] TREE //INJECT/254"));
    assert_tagged_single_line_wire(&tree_wire, "tree-injection");
    assert!(tree_wire.contains("type=BOGUS"));
    assert!(tree_wire.contains("state=error"));
    assert!(!tree_wire.contains("TYPE"));
    assert!(!tree_wire.contains("STATE"));

    let xml_wire = format_response(&server.handle("[xml-injection] TREEXMLDETAIL //INJECT/254"));
    assert_tagged_single_line_wire(&xml_wire, "xml-injection");
    assert!(xml_wire.contains("[xml-injection] 347-  <Type>BOGUS</Type>\n"));
    assert!(xml_wire.contains("[xml-injection] 347-  <PartName></PartName>\n"));
    assert!(xml_wire.contains("[xml-injection] 347-  <State>new</State>\n"));
    assert!(!xml_wire.contains("TYPE"));
    assert!(!xml_wire.contains("STATE"));
    assert!(!xml_wire.contains("blocked"));
}
