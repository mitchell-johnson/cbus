use cbus_cgate::{format_response, is_event_line, parse_command, AccessLevel, Server};
use std::path::PathBuf;

fn catalogue_dir() -> PathBuf {
    static ID: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
    let directory = std::env::temp_dir().join(format!(
        "cbus-cgate-repository-transform-{}-{}",
        std::process::id(),
        ID.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
    ));
    std::fs::create_dir_all(&directory).unwrap();
    std::fs::write(
        directory.join("applications.xml"),
        "<?xml version=\"1.0\"?>\n<Applications><Application Address=\"56\" Name=\"Lighting\"/></Applications>\n",
    )
    .unwrap();
    std::fs::write(
        directory.join("cbusunits.xml"),
        r#"<CBusUnits><Calculator><MinImpedance>400</MinImpedance><MaxImpedance>1500</MaxImpedance><MaxSupplyCurrent>2000</MaxSupplyCurrent></Calculator><Units><Unit><CatalogNumber>5034N</CatalogNumber><CurrentDrawn>18</CurrentDrawn><CurrentSupplied>0</CurrentSupplied><Impedance>110000</Impedance></Unit><Unit><CatalogNumber>5500BUR</CatalogNumber><CurrentDrawn>0</CurrentDrawn><CurrentSupplied>0</CurrentSupplied><Impedance>1000</Impedance></Unit><Unit><CatalogNumber>5500PS</CatalogNumber><CurrentDrawn>0</CurrentDrawn><CurrentSupplied>350</CurrentSupplied><Impedance>20000</Impedance></Unit></Units></CBusUnits>"#,
    )
    .unwrap();
    directory
}

fn assert_broadcast_event(line: &str, session: u64, content: &str) {
    let body = line
        .strip_prefix("#e# ")
        .unwrap_or_else(|| panic!("missing event marker: {line:?}"));
    let (timestamp, payload) = body
        .split_once(" 703 ")
        .unwrap_or_else(|| panic!("missing native 703 envelope: {line:?}"));
    chrono::NaiveDateTime::parse_from_str(timestamp, "%Y%m%d-%H%M%S%.3f")
        .unwrap_or_else(|error| panic!("invalid native timestamp {timestamp:?}: {error}"));
    assert_eq!(payload, format!("cmd{session} - broadcast_event {content}"));
    assert_eq!(cbus_cgate::event_reporting_level(line), Some(3));
    assert!(is_event_line(line));
}

#[test]
fn greeting_and_noop() {
    assert!(Server::greeting().starts_with("201 "));
    let mut s = Server::new(AccessLevel::Program);
    let r = s.handle("[7] NOOP");
    assert_eq!(r.status, 200);
    let wire = format_response(&r);
    assert!(wire.contains("[7] 200 OK"));
}

#[test]
fn monitor_denies_project_new() {
    let mut s = Server::new(AccessLevel::Monitor);
    let r = s.handle("[1] PROJECT NEW TEST");
    assert_eq!(r.status, 420);
}

#[test]
fn config_refuses_connection() {
    let mut s = Server::new(AccessLevel::Config);
    let r = s.handle("[1] PROJECT LIST");
    assert_eq!(r.status, 421);
}

#[test]
fn unknown_command_is_400() {
    let mut s = Server::new(AccessLevel::Program);
    let r = s.handle("[1] FROBNICATE WIDGETS");
    assert_eq!(r.status, 400);
}

#[test]
fn missing_tag_is_rejected() {
    assert!(parse_command("NOOP").is_err());
}

#[test]
fn event_lines_never_complete_commands() {
    for line in [
        "#e# x",
        "#s# x",
        "#c# x",
        "###!!!Event buffer overflow. Events have been missed.!!!###",
    ] {
        assert!(is_event_line(line), "{line}");
    }
    assert!(!is_event_line("[1] 200 OK"));
}

#[test]
fn broadcast_event_matches_native_reply_help_payload_and_level() {
    let mut server = Server::new(AccessLevel::Program);
    server.set_command_session(Some(3));

    let help = server.handle("[help] HELP BROADCAST_EVENT");
    assert_eq!(help.status, 101);
    assert_eq!(
        format_response(&help).lines().collect::<Vec<_>>(),
        [
            "[help] 101-Help: Syntax:  BROADCAST_EVENT SP event-class [event-text]",
            "[help] 101-Help: Send a broadcast event to the event and status change ports.",
            "[help] 101-Help:  event-class is the class of this event.",
            "[help] 101 Help:  event-text (optional) is the text that will be sent as an event.",
        ]
    );

    let missing = server.handle("[missing] BROADCAST_EVENT");
    assert_eq!(missing.status, 400);
    assert_eq!(missing.final_text, "400 Syntax Error.");
    assert!(server.drain_events().is_empty());

    for (tag, command, content) in [
        ("minimal", "BROADCAST_EVENT SP", "SP "),
        ("class", "BROADCAST_EVENT SP class", "SP class"),
        (
            "payload",
            "BROADCAST_EVENT SP class payload text",
            "SP class payload text",
        ),
        (
            "arbitrary",
            "BROADCAST_EVENT XX class payload",
            "XX class payload",
        ),
        (
            "dequoted",
            r#"BROADCAST_EVENT SP "quoted\ payload \"and\\slash""#,
            r#"SP quoted payload "and\slash"#,
        ),
    ] {
        let response = server.handle(&format!("[{tag}] {command}"));
        assert_eq!(response.status, 200, "{command}");
        assert!(response.lines.is_empty(), "{command}");
        assert_eq!(response.final_text, "200 OK.", "{command}");
        let events = server.drain_events();
        assert_eq!(events.len(), 1, "{command}");
        assert_broadcast_event(&events[0], 3, content);
    }

    let level_three = cbus_cgate::EventMode::parse("e3s0c0").unwrap();
    let level_two = cbus_cgate::EventMode::parse("e2s0c0").unwrap();
    let sample = "#e# 20260926-211833.803 703 cmd3 - broadcast_event SP class";
    assert!(level_three.delivers_line(sample));
    assert!(!level_two.delivers_line(sample));
}

#[test]
fn full_project_network_cycle() {
    let mut s = Server::new(AccessLevel::Program).with_programming(true);
    assert_eq!(s.handle("[1] PROJECT NEW TEST").status, 200);
    assert_eq!(s.handle("[2] NET OPEN //TEST/254").status, 404);
    assert_eq!(
        s.handle("[3] DBCREATENET 254 Local Cni 127.0.0.1:10001")
            .status,
        200
    );
    assert_eq!(s.handle("[4] NET OPEN //TEST/254").status, 200);
    assert_eq!(s.handle("[5] NET SYNC //TEST/254").status, 200);
    let st = s.handle("[6] NET STATE //TEST/254");
    assert_eq!(st.status, 200);
    assert!(st.lines.iter().any(|l| l.contains("ok")));
    assert_eq!(s.handle("[7] DBGET //TEST/254/56").status, 200);
    assert_eq!(s.handle("[8] PP LOCK mylock //TEST/254").status, 200);
    assert_eq!(s.handle("[9] PROJECT SAVE").status, 200);
    assert!(!s.drain_events().is_empty());
}

#[test]
fn native_general_object_and_tree_commands_share_one_honest_model() {
    let mut s = Server::new(AccessLevel::Program).with_programming(true);
    assert_eq!(s.handle("[1] PROJECT NEW GENERAL").status, 200);
    assert_eq!(
        s.handle("[2] DBCREATENET 254 Local Cni 127.0.0.1:10001")
            .status,
        200
    );

    // Native NEW is idempotent and ignores GROUP trailing tokens. PHANTOM
    // requires its initial byte; NEW UNIT creates only the database record.
    for command in [
        "[3] NEW GROUP //GENERAL/254/56/1 ignored trailing tokens",
        "[4] NEW GROUP //GENERAL/254/56/1",
        "[5] NEW PHANTOM //GENERAL/254/56/4 128",
        "[6] NEW UNIT //GENERAL/254/p/20 KEYE1 2.5.00",
        "[7] NEW UNIT //GENERAL/254/p/20 KEYE1 2.5.00",
    ] {
        assert_eq!(s.handle(command).status, 200, "{command}");
    }
    assert_eq!(s.handle("[8] NEW PHANTOM //GENERAL/254/56/5").status, 401);
    assert_eq!(s.handle("[9] NEW IGROUP //GENERAL/254/56/6").status, 400);
    assert_eq!(
        s.handle("[9a] NEW UNIT //GENERAL/254/p/22/Type KEYE1 2.5.00")
            .status,
        400
    );

    let network_parameters = s.handle("[9b] SHOW //GENERAL/254 ?");
    assert_eq!(network_parameters.status, 300);
    assert!(network_parameters
        .final_text
        .contains("Parameters=DBUnitAddressesNew,DBUnitAddressesMissing"));

    let unit = s.handle("[9c] SHOW //GENERAL/254/p/20 *");
    assert_eq!(unit.status, 300);
    assert_eq!(unit.final_text, "300 //GENERAL/254/p/20: Version2=null");
    assert!(unit
        .lines
        .iter()
        .any(|line| line == "300-//GENERAL/254/p/20: Application=255"));
    assert!(unit.lines.iter().any(|line| {
        line == "408-Operation failed: //GENERAL/254/p/20 (Can not get parameter from unit)"
    }));

    for (address, phantom) in [(1, false), (4, true)] {
        let group = s.handle(&format!("[9d-{address}] SHOW //GENERAL/254/56/{address} *"));
        assert_eq!(group.status, 300);
        assert_eq!(
            group.final_text,
            format!("300 //GENERAL/254/56/{address}: Units=")
        );
        assert!(group
            .lines
            .iter()
            .any(|line| { line == &format!("300-//GENERAL/254/56/{address}: Type=group") }));
        assert_eq!(
            s.handle(&format!(
                "[9e-{address}] SHOW //GENERAL/254/56/{address} Level"
            ))
            .final_text,
            format!("300 //GENERAL/254/56/{address}: Level=0")
        );
        if phantom {
            assert_eq!(
                s.handle(&format!(
                    "[9f-{address}] SHOW //GENERAL/254/56/{address} Type"
                ))
                .final_text,
                format!("300 //GENERAL/254/56/{address}: Type=group")
            );
        }
    }

    let tree = s.handle("[10] TREE //GENERAL/254 WITHSYNC");
    assert_eq!(tree.status, 320);
    assert_eq!(tree.final_text, "320 -end-");
    assert!(tree.lines.iter().any(|line| line == "320-  Unit count=0"));
    assert!(tree
        .lines
        .iter()
        .any(|line| line.contains("//GENERAL/254/p/20 ($14) type=KEYE1")));
    assert!(tree
        .lines
        .iter()
        .any(|line| line.contains("//GENERAL/254/56/1 ($1) level=0")));
    assert!(tree.lines.iter().any(|line| {
        line.contains("//GENERAL/254/56/4 ($4) level=0") && line.ends_with("(phantom)")
    }));
    assert!(tree
        .lines
        .first()
        .is_some_and(|line| line.ends_with("state=error")));
    assert!(!tree
        .lines
        .iter()
        .any(|line| line.contains("Application 255")));
    let net_tree = s.handle("[10a] NET TREE //GENERAL/254");
    assert_eq!(net_tree.status, tree.status);
    assert_eq!(net_tree.lines, tree.lines);
    assert_eq!(net_tree.final_text, tree.final_text);

    let report = s.handle("[11] REPORT //GENERAL/254");
    assert_eq!(report.status, tree.status);
    assert_eq!(report.lines, tree.lines);
    assert_eq!(report.final_text, tree.final_text);

    let xml = s.handle("[12] TREEXMLDETAIL //GENERAL/254");
    assert_eq!(xml.status, 344);
    assert_eq!(
        xml.lines.first().map(String::as_str),
        Some("343-Begin XML Snippet")
    );
    assert!(xml
        .lines
        .iter()
        .any(|line| line == "347-  <Type>KEYE1</Type>"));
    assert!(xml
        .lines
        .iter()
        .any(|line| line == "347-  <Address>20</Address>"));
    assert!(xml
        .lines
        .iter()
        .any(|line| line.starts_with("347-  <State>")));

    let show = s.handle("[13] SHOW //GENERAL/254/p/20 Type");
    let get = s.handle("[14] GET //GENERAL/254/p/20 Type");
    assert_eq!(show.status, 300);
    assert_eq!(show.lines, get.lines);
    assert_eq!(show.final_text, get.final_text);

    let missing = s.handle("[16] TREE //GENERAL/253");
    assert_eq!(missing.status, 401);
    assert_eq!(
        missing.final_text,
        "401 Bad object or device ID: Network not found"
    );
    let project_report = s.handle("[17] REPORT //GENERAL");
    assert_eq!(project_report.status, 402);
    assert_eq!(
        project_report.final_text,
        "402 Operation not supported by: //GENERAL"
    );
    let project_xml = s.handle("[18] TREEXML //GENERAL");
    assert_eq!(project_xml.status, 344);
    assert_eq!(
        project_xml.lines,
        [
            "343-Begin XML Snippet",
            "402-Operation not supported by: //GENERAL"
        ]
    );
    assert!(
        format_response(&project_xml).contains("[18] 402-Operation not supported by: //GENERAL\n")
    );
    assert_eq!(
        s.handle("[19] BROADCAST_EVENT").final_text,
        "400 Syntax Error."
    );

    // Direct model callers normally fall back to cmd0. Pin a non-zero source
    // here so this general-object regression also proves that the transport's
    // command-session identity is carried into the native event envelope.
    s.set_command_session(Some(17));
    let broadcast = s.handle("[15] BROADCAST_EVENT SP class payload text");
    assert_eq!(broadcast.final_text, "200 OK.");
    let event = s
        .drain_events()
        .iter()
        .find(|event| event.contains("broadcast_event SP class payload text"))
        .expect("BROADCAST_EVENT must enqueue the native event envelope")
        .clone();
    assert_broadcast_event(&event, 17, "SP class payload text");
}

#[test]
fn monitor_cannot_create_new_database_objects() {
    let mut server = Server::new(AccessLevel::Monitor);
    for command in [
        "[1] NEW UNIT //P/254/p/1 KEYE1 2.5.00",
        "[2] NEW GROUP //P/254/56/1",
        "[3] NEW PHANTOM //P/254/56/2 1",
    ] {
        assert_eq!(server.handle(command).status, 420, "{command}");
    }
}

#[test]
fn general_object_help_matches_the_retained_native_fixture() {
    let evidence: serde_json::Value = serde_json::from_str(include_str!(
        "../../testdata/fixtures/native_cgate_general_tree.json"
    ))
    .unwrap();
    let mut server = Server::new(AccessLevel::Program).with_programming(true);
    for (index, item) in evidence["help"].as_array().unwrap().iter().enumerate() {
        let command = item["command"].as_str().unwrap();
        let tag = format!("help-{index}");
        let response = server.handle(&format!("[{tag}] {command}"));
        let actual = format_response(&response)
            .lines()
            .map(|line| line.strip_prefix(&format!("[{tag}] ")).unwrap().to_string())
            .collect::<Vec<_>>();
        let expected = item["lines"]
            .as_array()
            .unwrap()
            .iter()
            .map(|line| line.as_str().unwrap().to_string())
            .collect::<Vec<_>>();
        assert_eq!(actual, expected, "{command}");
    }
}

#[test]
fn new_object_transcript_matches_the_retained_native_fixture_exactly() {
    let evidence: serde_json::Value = serde_json::from_str(include_str!(
        "../../testdata/fixtures/native_cgate_general_tree.json"
    ))
    .unwrap();
    let mut server = Server::new(AccessLevel::Program).with_programming(true);
    for (index, item) in evidence["new_object_transcript"]
        .as_array()
        .unwrap()
        .iter()
        .enumerate()
    {
        let command = item["command"].as_str().unwrap();
        let tag = format!("new-{index}");
        let response = server.handle(&format!("[{tag}] {command}"));
        let actual = format_response(&response)
            .lines()
            .map(|line| line.strip_prefix(&format!("[{tag}] ")).unwrap().to_string())
            .collect::<Vec<_>>();
        let expected = item["lines"]
            .as_array()
            .unwrap()
            .iter()
            .map(|line| line.as_str().unwrap().to_string())
            .collect::<Vec<_>>();
        assert_eq!(actual, expected, "{command}");
    }
}

#[test]
fn show_object_matrix_matches_the_retained_native_fixture() {
    let evidence: serde_json::Value = serde_json::from_str(include_str!(
        "../../testdata/fixtures/native_cgate_show_objects.json"
    ))
    .unwrap();
    let mut server = Server::new(AccessLevel::Program).with_programming(true);
    for (index, item) in evidence["rows"].as_array().unwrap().iter().enumerate() {
        let command = item["command"].as_str().unwrap();
        let tag = format!("show-{index}");
        let response = server.handle(&format!("[{tag}] {command}"));
        let normalize = |line: String| {
            if let Some((prefix, _)) = line.split_once("NextSyncTime=") {
                format!("{prefix}NextSyncTime=<scheduled>")
            } else {
                line
            }
        };
        let actual = format_response(&response)
            .lines()
            .map(|line| normalize(line.strip_prefix(&format!("[{tag}] ")).unwrap().to_string()))
            .collect::<Vec<_>>();
        let expected = item["lines"]
            .as_array()
            .unwrap()
            .iter()
            .map(|line| normalize(line.as_str().unwrap().to_string()))
            .collect::<Vec<_>>();
        assert_eq!(actual, expected, "{command}");
    }
}

#[test]
fn oid_is_a_native_301_uuid_factory_not_a_database_object() {
    let mut s = Server::new(AccessLevel::Program).with_programming(true);
    let first = s.handle("[1] OID ignored tail");
    let second = s.handle("[2] OID");
    assert_eq!(first.status, 301);
    assert_eq!(second.status, 301);
    let first = first.final_text.strip_prefix("301 OID=").unwrap();
    let second = second.final_text.strip_prefix("301 OID=").unwrap();
    assert_ne!(first, second);
    let parts = first.split('-').collect::<Vec<_>>();
    assert_eq!(
        parts.iter().map(|part| part.len()).collect::<Vec<_>>(),
        [8, 4, 4, 4, 12]
    );
    assert_eq!(parts[2].as_bytes()[0], b'1');
    assert!(matches!(parts[3].as_bytes()[0], b'8' | b'9' | b'a' | b'b'));
    assert_eq!(parts[4], second.split('-').nth(4).unwrap());
    assert!(first
        .chars()
        .filter(|character| *character != '-')
        .all(|character| character.is_ascii_hexdigit()));
    assert_eq!(s.handle(&format!("[3] DBGET !{first}/OID")).status, 401);
}

#[test]
fn edlt_factory_default_method_has_a_bounded_mock_contract() {
    let mut s = Server::new(AccessLevel::Program).with_programming(true);
    assert_eq!(s.handle("[1] PROJECT NEW TEST").status, 200);
    assert_eq!(
        s.handle("[2] DBCREATENET 254 Local Cni 127.0.0.1:10001")
            .status,
        200
    );
    assert_eq!(
        s.handle("[3] DBADDSAFE //TEST/254 Unit 5 Kitchen_eDLT")
            .status,
        200
    );
    assert_eq!(
        s.handle("[4] DBSETSAFE //TEST/254/p/5/UnitType KEYGL5")
            .status,
        200
    );
    let reset = s.handle("[5] DO //TEST/254/p/5 FactoryDefault");
    assert_eq!(reset.status, 202);
    assert!(reset.lines.is_empty());
    assert_eq!(reset.final_text, "202 Done: //TEST/254/p/5");
    for (command, status) in [
        ("[6] DO //TEST/254/p/5 FactoryDefault extra", 400),
        ("[7] DO //TEST/254/p/6 FactoryDefault", 401),
        ("[8] DO //TEST/254/p/5 UnknownMethod", 402),
    ] {
        assert_eq!(s.handle(command).status, status, "{command}");
    }
}

#[test]
fn level_lifecycle_group_xml_and_copy() {
    let mut s = Server::new(AccessLevel::Program).with_programming(true);
    assert_eq!(s.handle("[1] PROJECT NEW TEST").status, 200);
    assert_eq!(
        s.handle("[2] DBCREATENET 254 Local Cni 127.0.0.1:10001")
            .status,
        200
    );
    // Creation answers 301 with a fresh OID; the group document reports
    // the row with no Value attribute while native NULL.
    let added = s.handle("[3] DBADDSAFE //TEST/254/56/1 Level 1 Evening");
    assert_eq!(added.status, 301);
    let oid = added.final_text.rsplit('=').next().unwrap().to_string();
    let doc = s.handle("[4] DBGETXML //TEST/254/56/1");
    assert_eq!(doc.status, 200);
    assert!(
        doc.lines
            .iter()
            .any(|l| l.contains("<Group><Level><TagName>Evening</TagName></Level></Group>")),
        "{:?}",
        doc.lines
    );
    // The level document root reads `Level` for the copy kind probe.
    let single = s.handle(&format!("[5] DBGETXML !{oid}"));
    assert_eq!(single.status, 200);
    assert!(
        single
            .lines
            .iter()
            .any(|l| l.contains("<Level><TagName>Evening</TagName></Level>")),
        "{:?}",
        single.lines
    );
    // Value reads NULL before initialization, then the initialized byte.
    let null = s.handle(&format!("[6] DBGET !{oid}/Value"));
    assert_eq!(null.status, 342);
    assert!(null.final_text.ends_with("=null"), "{}", null.final_text);
    assert_eq!(
        s.handle(&format!("[7] DBSETSAFE !{oid}/Value 42")).status,
        200
    );
    let back = s.handle(&format!("[8] DBGET !{oid}/Value"));
    assert!(back.final_text.ends_with("=42"), "{}", back.final_text);
    let doc = s.handle("[9] DBGETXML //TEST/254/56/1");
    assert!(
        doc.lines
            .iter()
            .any(|l| l.contains("<Level Value=\"42\"><TagName>Evening</TagName></Level>")),
        "{:?}",
        doc.lines
    );
    // Non-byte values are rejected, not stored.
    assert_eq!(
        s.handle(&format!("[10] DBSETSAFE !{oid}/Value 999")).status,
        400
    );
    // Copying a level answers the 301 flow with a fresh, NULL record.
    let copied = s.handle(&format!("[11] DBCOPYSAFE !{oid} //TEST/254/56/1 2 Night"));
    assert_eq!(copied.status, 301);
    let copy_oid = copied.final_text.rsplit('=').next().unwrap().to_string();
    assert_ne!(copy_oid, oid);
    let doc = s.handle("[12] DBGETXML //TEST/254/56/1");
    assert!(
        doc.lines.iter().any(|l| l.contains(
            "<Level Value=\"42\"><TagName>Evening</TagName></Level>\
             <Level><TagName>Night</TagName></Level>"
        )),
        "{:?}",
        doc.lines
    );
    // Deleting a level drops its row and retires its identity.
    assert_eq!(s.handle(&format!("[13] DBDELETE !{oid}")).status, 200);
    assert_eq!(s.handle(&format!("[14] DBGET !{oid}/OID")).status, 401);
    let doc = s.handle("[15] DBGETXML //TEST/254/56/1");
    assert!(
        doc.lines
            .iter()
            .any(|l| l.contains("<Level><TagName>Night</TagName></Level>")),
        "{:?}",
        doc.lines
    );
    assert!(
        doc.lines.iter().all(|l| !l.contains("Evening")),
        "{:?}",
        doc.lines
    );
}

#[test]
fn level_netvar_document_and_rename_travel() {
    let mut s = Server::new(AccessLevel::Program).with_programming(true);
    assert_eq!(s.handle("[1] PROJECT NEW TEST").status, 200);
    assert_eq!(
        s.handle("[2] DBCREATENET 254 Local Cni 127.0.0.1:10001")
            .status,
        200
    );
    let added = s.handle("[3] DBADDSAFE //TEST/254/201/1 NetVar 7 Gain");
    assert_eq!(added.status, 301);
    let doc = s.handle("[4] DBGETXML //TEST/254/201/1");
    assert_eq!(doc.status, 200);
    assert!(
        doc.lines
            .iter()
            .any(|l| l.contains("<NetVar><Level><TagName>Gain</TagName></Level></NetVar>")),
        "{:?}",
        doc.lines
    );
    // A network rename carries level parents along.
    assert_eq!(s.handle("[5] DBRENAMENETSAFE 254 250").status, 200);
    let doc = s.handle("[6] DBGETXML //TEST/250/201/1");
    assert!(
        doc.lines
            .iter()
            .any(|l| l.contains("<TagName>Gain</TagName>")),
        "{:?}",
        doc.lines
    );
    let stale = s.handle("[7] DBGETXML //TEST/254/201/1");
    assert_eq!(stale.status, 401);
}

/// Mock determinism for the guarded one-shot label clear: the accepted
/// reply is exactly one `200 OK.` line (note the period), malformed shapes
/// fail closed, and each accepted clear records one `#e#` event.
#[test]
fn label_clearedlt_contract_and_event() {
    let mut s = Server::new(AccessLevel::Program);
    let clear = s.handle("[1] LABEL CLEAREDLT //TEST/252/p/30");
    assert_eq!(clear.status, 200);
    assert!(clear.lines.is_empty());
    assert_eq!(clear.final_text, "200 OK.");
    // Case-insensitive verb, exact same reply shape.
    for line in [
        "[2] LABEL clearedlt //TEST/252/p/30",
        "[2b] LABEL ClearEdlt //TEST/252/p/30",
    ] {
        let response = s.handle(line);
        assert_eq!(response.status, 200, "{line}");
        assert!(response.lines.is_empty(), "{line}");
        assert_eq!(response.final_text, "200 OK.", "{line}");
    }
    // Malformed shapes and targets fail closed.
    for (line, fragment) in [
        ("[3] LABEL CLEAREDLT", "only supports CLEAR or CLEAREDLT"),
        ("[4] LABEL CLEAR //TEST/252/p/30", "requires an application"),
        (
            "[5] LABEL CLEAREDLT //TEST/252/p/30 extra",
            "only supports CLEAR or CLEAREDLT",
        ),
        ("[6] LABEL CLEAREDLT //TEST/252/p/#", "Invalid clear target"),
    ] {
        let response = s.handle(line);
        assert_eq!(response.status, 400, "{line}");
        assert!(response.final_text.contains(fragment), "{line}");
    }
    let events = s.drain_events();
    assert_eq!(events.len(), 3);
    assert!(events
        .iter()
        .all(|event| event == "#e# labels cleared //TEST/252/p/30"));
}

/// The mock keeps native `LABEL CLEAR` distinct from `CLEAREDLT`: both
/// all-key and one-key forms validate deterministically and return only their
/// command response, while malformed application/unit/key values have no
/// side effect.
#[test]
fn label_clear_cache_contract_has_no_synthetic_event() {
    let mut s = Server::new(AccessLevel::Program);
    for line in [
        "[1] LABEL CLEAR //TEST/252/56 0",
        "[2] label clear //TEST/252/202 255 1",
        "[3] LABEL CLEAR /252/203 5 8",
        "[3b] LABEL CLEAR //TEST/252/$38 5",
    ] {
        let response = s.handle(line);
        assert_eq!(response.status, 200, "{line}: {response:?}");
        assert_eq!(response.final_text, "200 OK", "{line}");
    }
    assert!(s.drain_events().is_empty());

    for line in [
        "[4] LABEL CLEAR",
        "[5] LABEL CLEAR //TEST/252/56",
        "[6] LABEL CLEAR //TEST/252/56 5 1 extra",
        "[7] LABEL CLEAR //TEST/252/p/5",
        "[9] LABEL CLEAR //TEST/252/56 256",
        "[10] LABEL CLEAR //TEST/252/56 nope",
        "[11] LABEL CLEAR //TEST/252/56 5 0",
        "[12] LABEL CLEAR //TEST/252/56 5 9",
        "[13] LABEL CLEAR //TEST/252/56 5 nope",
    ] {
        let response = s.handle(line);
        assert_eq!(response.status, 400, "{line}: {response:?}");
    }
    let unsupported = s.handle("[8] LABEL CLEAR //TEST/252/25 5");
    assert_eq!(unsupported.status, 402, "{unsupported:?}");
    assert!(unsupported.final_text.contains("does not support labels"));
    assert!(s.drain_events().is_empty());
}

/// Mock determinism for the LABEL key-file helpers: KFISET stores a value
/// under the target, KFIGET reads it back, and a valueless KFISET fails.
#[test]
fn label_kfi_round_trip_and_valueless_reject() {
    let mut s = Server::new(AccessLevel::Program);
    // Never-set targets report 300 with an empty value, never 404.
    let unset = s.handle("[0] LABEL KFIGET //TEST/252/p/99");
    assert_eq!(unset.status, 300);
    assert_eq!(unset.final_text, "300 ");
    let stored = s.handle("[1] LABEL KFISET //TEST/252/p/30 myvalue");
    assert_eq!(stored.status, 200);
    let fetched = s.handle("[2] LABEL KFIGET //TEST/252/p/30");
    assert_eq!(fetched.status, 300);
    assert!(fetched.lines.is_empty());
    assert_eq!(fetched.final_text, "300 myvalue");
    // Distinct targets do not share one slot; multi-word values join.
    let other = s.handle("[3] LABEL KFISET //TEST/252/p/31 hello world");
    assert_eq!(other.status, 200);
    let refetched = s.handle("[4] LABEL KFIGET //TEST/252/p/30");
    assert_eq!(refetched.final_text, "300 myvalue");
    let other_fetched = s.handle("[5] LABEL KFIGET //TEST/252/p/31");
    assert_eq!(other_fetched.final_text, "300 hello world");
    // A valueless KFISET fails and preserves the stored value; a second
    // KFISET overwrites it.
    let missing = s.handle("[6] LABEL KFISET //TEST/252/p/30");
    assert_eq!(missing.status, 400);
    assert!(missing.final_text.contains("requires a target and value"));
    let preserved = s.handle("[7] LABEL KFIGET //TEST/252/p/30");
    assert_eq!(preserved.final_text, "300 myvalue");
    let overwrite = s.handle("[8] LABEL KFISET //TEST/252/p/30 newvalue");
    assert_eq!(overwrite.status, 200);
    let replaced = s.handle("[9] LABEL KFIGET //TEST/252/p/30");
    assert_eq!(replaced.final_text, "300 newvalue");
}

/// The sole local scalar-SET exception pins the owned native capture used by
/// guarded Toolkit physical workflows: default two, exact zero mutation,
/// native reply/readback, and no event. Invalid, foreign, missing and broader
/// non-Address forms remain closed without changing the accepted value.
#[test]
fn scalar_set_network_retries_zero_is_exact_and_volatile() {
    let mut s = Server::new(AccessLevel::Program);
    assert_eq!(s.handle("[1] PROJECT NEW TEST").status, 200);
    assert_eq!(
        s.handle("[2] DBCREATENET 254 Local Cni 127.0.0.1:10001")
            .status,
        200
    );
    let default = s.handle("[3] GET //TEST/254 Retries");
    assert_eq!(default.status, 300);
    assert_eq!(default.final_text, "300 //TEST/254: Retries=2");
    s.drain_events();

    let set = s.handle("[4] SET //TEST/254 Retries 0");
    assert_eq!(set.status, 200);
    assert!(set.lines.is_empty());
    assert_eq!(set.final_text, "200 OK: //TEST/254");
    assert!(s.drain_events().is_empty());
    let readback = s.handle("[5] GET //TEST/254 Retries");
    assert_eq!(readback.status, 300);
    assert_eq!(readback.final_text, "300 //TEST/254: Retries=0");

    for command in [
        "SET //TEST/254 Retries 2",
        "SET //TEST/254 Retries -1",
        "SET //TEST/254 Retries",
        "SET /254 Retries 0",
        "SET //TEST/254/p/1 Retries 0",
        "SET //TEST/254 AutoUpdate no",
    ] {
        let rejected = s.handle(&format!("[bad] {command}"));
        assert!(rejected.status >= 400, "{command}: {rejected:?}");
        assert_eq!(
            s.handle("[check] GET //TEST/254 Retries").final_text,
            "300 //TEST/254: Retries=0",
            "{command} changed runtime state"
        );
        assert!(s.drain_events().is_empty(), "{command} emitted an event");
    }

    assert_eq!(s.handle("[6] PROJECT NEW OTHER").status, 200);
    s.drain_events();
    let foreign = s.handle("[7] SET //TEST/254 Retries 0");
    assert_eq!(foreign.status, 404);
    assert!(foreign.final_text.contains("Project not selected"));
    assert!(s.drain_events().is_empty());
    assert_eq!(s.handle("[8] PROJECT USE TEST").status, 200);
    let missing = s.handle("[9] SET //TEST/253 Retries 0");
    assert_eq!(missing.status, 404);
    assert!(missing.final_text.contains("Network not found"));
    assert_eq!(
        s.handle("[10] GET //TEST/254 Retries").final_text,
        "300 //TEST/254: Retries=0"
    );
    assert!(s.drain_events().is_empty());
}

#[test]
fn network_retries_do_not_cross_database_snapshot_boundaries() {
    let mut server = Server::new(AccessLevel::Program);
    assert_eq!(server.handle("[1] PROJECT NEW SOURCE").status, 200);
    assert_eq!(
        server
            .handle("[2] DBCREATENET 254 Local Cni 127.0.0.1:10001")
            .status,
        200
    );
    assert_eq!(server.handle("[3] SET //SOURCE/254 Retries 0").status, 200);
    let get = |server: &mut Server, tag: &str, project: &str| {
        server
            .handle(&format!("[{tag}] GET //{project}/254 Retries"))
            .final_text
    };

    assert_eq!(server.handle("[4] PROJECT COPY SOURCE COPY").status, 200);
    assert_eq!(
        get(&mut server, "5", "SOURCE"),
        "300 //SOURCE/254: Retries=0"
    );
    assert_eq!(server.handle("[6] PROJECT USE COPY").status, 200);
    assert_eq!(get(&mut server, "7", "COPY"), "300 //COPY/254: Retries=2");

    assert_eq!(server.handle("[8] PROJECT USE SOURCE").status, 200);
    assert_eq!(
        server
            .handle("[9] PROJECT ARCHIVE SOURCE /tmp/retries.arc")
            .status,
        200
    );
    assert_eq!(
        get(&mut server, "10", "SOURCE"),
        "300 //SOURCE/254: Retries=0"
    );
    assert_eq!(
        server
            .handle("[11] PROJECT RESTORE RESTORED /tmp/retries.arc")
            .status,
        200
    );
    assert_eq!(server.handle("[12] PROJECT USE RESTORED").status, 200);
    assert_eq!(
        get(&mut server, "13", "RESTORED"),
        "300 //RESTORED/254: Retries=2"
    );
    assert_eq!(
        server
            .handle("[14] PROJECT LOAD LOADED /tmp/retries.arc")
            .status,
        200
    );
    assert_eq!(
        get(&mut server, "15", "LOADED"),
        "300 //LOADED/254: Retries=2"
    );

    assert_eq!(server.handle("[16] PROJECT USE SOURCE").status, 200);
    assert_eq!(server.handle("[17] DBSAVE retries.db").status, 200);
    assert_eq!(
        get(&mut server, "18", "SOURCE"),
        "300 //SOURCE/254: Retries=0"
    );
    assert_eq!(server.handle("[19] DBLOAD retries.db").status, 200);
    assert_eq!(
        get(&mut server, "20", "SOURCE"),
        "300 //SOURCE/254: Retries=2"
    );
}

/// Mock determinism for the scalar address move: the reply confirms the
/// destination in the exact native shape, the database record stays put,
/// and guard rails fail closed in existence-before-occupancy order.
#[test]
fn scalar_set_move_contract_and_guards() {
    let mut s = Server::new(AccessLevel::Program);
    assert_eq!(s.handle("[1] PROJECT NEW TEST").status, 200);
    assert_eq!(
        s.handle("[2] DBCREATENET 254 Local Cni 127.0.0.1:10001")
            .status,
        200
    );
    assert_eq!(s.handle("[3] PROJECT USE TEST").status, 200);
    assert_eq!(
        s.handle("[4] DBADDSAFE //TEST/254 Unit 30 Study").status,
        200
    );
    assert_eq!(
        s.handle("[5] DBADDSAFE //TEST/254 Unit 31 Spare").status,
        200
    );
    // Malformed shapes fail before any lookup.
    for (line, fragment) in [
        (
            "[6] SET //TEST/254/p/30",
            "source path and Address destination",
        ),
        (
            "[7] SET //TEST/254/p/30 Name 31",
            "source path and Address destination",
        ),
        (
            "[8] SET //TEST/254/p/30 Address 256",
            "Invalid destination address",
        ),
        (
            "[9] SET //TEST/254/p/30 Address x",
            "Invalid destination address",
        ),
        (
            "[9b] SET //TEST/254/p/30 Address -1",
            "Invalid destination address",
        ),
        ("[10] SET //TEST/254/p/# Address 40", "Invalid source path"),
    ] {
        let response = s.handle(line);
        assert_eq!(response.status, 400, "{line}");
        assert!(response.final_text.contains(fragment), "{line}");
    }
    // Boundary addresses 0 and 255 move on a scratch unit.
    assert_eq!(
        s.handle("[10b] DBADDSAFE //TEST/254 Unit 40 Scratch")
            .status,
        200
    );
    let zero = s.handle("[10c] SET //TEST/254/p/40 Address 0");
    assert_eq!(zero.status, 200);
    assert_eq!(zero.final_text, "200 OK: //TEST/254/p/0");
    let max = s.handle("[10d] SET //TEST/254/p/0 Address 255");
    assert_eq!(max.status, 200);
    assert_eq!(max.final_text, "200 OK: //TEST/254/p/255");
    // A selected-away project refuses the move before any lookup.
    assert_eq!(s.handle("[10e] PROJECT NEW T2").status, 200);
    assert_eq!(s.handle("[10f] PROJECT USE T2").status, 200);
    let noselect = s.handle("[10g] SET //TEST/254/p/30 Address 33");
    assert_eq!(noselect.status, 404);
    assert!(noselect.final_text.contains("Project not selected"));
    assert_eq!(s.handle("[10h] PROJECT USE TEST").status, 200);
    // Missing source beats occupied destination (existence first). The
    // occupied unit is proven physically present first.
    let missing = s.handle("[11] SET //TEST/254/p/99 Address 31");
    assert_eq!(missing.status, 401);
    let present = s.handle("[11b] GET //TEST/254/p/31 *");
    assert_eq!(present.status, 300);
    let occupied = s.handle("[12] SET //TEST/254/p/30 Address 31");
    assert_eq!(occupied.status, 409);
    // The move confirms the destination; the physical record travels
    // while the database record stays put (unit reads observe physical,
    // DBGETXML observes the database layer).
    let moved = s.handle("[13] SET //TEST/254/p/30 Address 32");
    assert_eq!(moved.status, 200);
    assert!(moved.lines.is_empty());
    assert_eq!(moved.final_text, "200 OK: //TEST/254/p/32");
    // The independently retained database record remains readable at the old
    // address after only the physical unit moves. Physical inventory and
    // addressed object lookup deliberately expose those two layers.
    let database_record = s.handle("[14] GET //TEST/254/p/30 *");
    assert_eq!(database_record.status, 300);
    let arrived = s.handle("[15] GET //TEST/254/p/32 *");
    assert_eq!(arrived.status, 300);
    assert!(!arrived
        .lines
        .iter()
        .chain(std::iter::once(&arrived.final_text))
        .any(|line| line.contains("UnitName=Study")));
    let db = s.handle("[16] DBGETXML //TEST/254/p/30");
    assert_eq!(db.status, 200);
    assert!(db
        .lines
        .iter()
        .filter(|line| line.starts_with("347-"))
        .any(|line| line.contains("Study")));
    // Post-move state machine: move back, stale source stays 401,
    // re-occupancy stays 409.
    let back = s.handle("[17] SET //TEST/254/p/32 Address 30");
    assert_eq!(back.status, 200);
    assert_eq!(back.final_text, "200 OK: //TEST/254/p/30");
    let stale = s.handle("[18] SET //TEST/254/p/32 Address 33");
    assert_eq!(stale.status, 401);
    let reoccupied = s.handle("[19] SET //TEST/254/p/30 Address 31");
    assert_eq!(reoccupied.status, 409);
    let events = s.drain_events();
    assert!(events.iter().any(|event| event == "#e# unit moved 30 32"));
}

/// Mock determinism for DBVALIDATE: status 233 with every line (including
/// the final) in the exact native `233[- ]<path>: Valid` shape; malformed
/// shapes fail closed. Mock-only pins: no project-selection gating and no
/// existence check, both pending native capture before any parity claim.
#[test]
fn dbvalidate_envelope_shape_and_rejects() {
    let mut s = Server::new(AccessLevel::Program);
    let valid = s.handle("[1] DBVALIDATE //TEST/254/p/20");
    assert_eq!(valid.status, 233);
    assert_eq!(valid.lines, vec!["233-//TEST/254/p/20: Valid"]);
    assert_eq!(valid.final_text, "233 //TEST/254/p/20: Valid");
    // Shape-only: absent paths validate the same way.
    let absent = s.handle("[2] DBVALIDATE //TEST/254/p/99");
    assert_eq!(absent.status, 233);
    assert_eq!(absent.lines, vec!["233-//TEST/254/p/99: Valid"]);
    assert_eq!(absent.final_text, "233 //TEST/254/p/99: Valid");
    for (line, fragment) in [
        ("[3] DBVALIDATE", "requires a path"),
        ("[4] DBVALIDATE //TEST/254/p/20 extra", "requires a path"),
        ("[5] DBVALIDATE //TEST/254/p/#", "requires a path"),
    ] {
        let response = s.handle(line);
        assert_eq!(response.status, 400, "{line}");
        assert!(response.final_text.contains(fragment), "{line}");
    }
}

/// Mock determinism for DBDELETE: boundary-checked prefix removal takes the
/// database unit but leaves physical presence and numeric siblings alone;
/// repeats and absent paths fail closed; unselected projects are refused.
/// The DB read layer observes the removal and the unit OID retires.
#[test]
fn dbdelete_boundary_repeat_and_unselected() {
    let mut s = Server::new(AccessLevel::Program);
    assert_eq!(s.handle("[1] PROJECT NEW TEST").status, 200);
    assert_eq!(
        s.handle("[2] DBCREATENET 254 Local Cni 127.0.0.1:10001")
            .status,
        200
    );
    assert_eq!(s.handle("[3] PROJECT USE TEST").status, 200);
    for (tag, addr, name) in [("4", 20, "A"), ("5", 200, "B"), ("6", 30, "C")] {
        assert_eq!(
            s.handle(&format!("[{tag}] DBADDSAFE //TEST/254 Unit {addr} {name}"))
                .status,
            200
        );
    }
    // Capture unit 20's OID from the network document while it exists;
    // deletion must retire it. Unit snippets carry no OID themselves.
    let netdoc = s.handle("[6b] DBGETXML //TEST/254");
    assert_eq!(netdoc.status, 200);
    let oid = netdoc
        .lines
        .iter()
        .chain(std::iter::once(&netdoc.final_text))
        .find(|line| line.contains("<Address>20</Address>"))
        .and_then(|line| {
            let start = line.find("<OID>")? + "<OID>".len();
            let end = line.find("</OID>")?;
            Some(line[start..end].to_string())
        })
        .expect("network XML carries unit 20 with its OID");
    let resolved = s.handle(&format!("[6c] DBGET !{oid}/OID"));
    assert_eq!(resolved.status, 342);
    assert_eq!(resolved.final_text, format!("342 !{oid}/OID={oid}"));
    let deleted = s.handle("[7] DBDELETE //TEST/254/p/20");
    assert_eq!(deleted.status, 200);
    assert_eq!(deleted.final_text, "200 OK");
    // Repeat and never-present paths fail closed; p/20 must not wipe p/200.
    for (line, status, fragment) in [
        ("[8] DBDELETE //TEST/254/p/20", 404, "Object not found"),
        ("[9] DBDELETE //TEST/254/p/3", 404, "Object not found"),
        ("[10] DBDELETE", 400, "requires a path"),
    ] {
        let response = s.handle(line);
        assert_eq!(response.status, status, "{line}");
        assert!(response.final_text.contains(fragment), "{line}");
    }
    // Physical presence and siblings survive the database removal
    // (mock-only layer split, like the scalar move: unit reads observe
    // physical, DB reads observe the database layer).
    for addr in [200, 30] {
        let present = s.handle(&format!("[11] GET //TEST/254/p/{addr} *"));
        assert_eq!(present.status, 300);
    }
    // The DB read layer observes the removal; the sibling still reads.
    let db_gone = s.handle("[11b] DBGET //TEST/254/p/20");
    assert_eq!(db_gone.status, 401);
    let db_sibling = s.handle("[11c] DBGET //TEST/254/p/200");
    assert_eq!(db_sibling.status, 200);
    let xml_sibling = s.handle("[11d] DBGETXML //TEST/254/p/200");
    assert_eq!(xml_sibling.status, 200);
    // Unselected projects are refused before any lookup, even for an
    // existing object: select away first since PROJECT NEW selects.
    let mut unselected = Server::new(AccessLevel::Program);
    assert_eq!(unselected.handle("[1] PROJECT NEW T2").status, 200);
    assert_eq!(
        unselected
            .handle("[2] DBCREATENET 254 Local Cni 127.0.0.1:10001")
            .status,
        200
    );
    assert_eq!(
        unselected
            .handle("[3] DBADDSAFE //T2/254 Unit 20 Present")
            .status,
        200
    );
    assert_eq!(unselected.handle("[4] PROJECT NEW T3").status, 200);
    assert_eq!(unselected.handle("[5] PROJECT USE T3").status, 200);
    let noselect = unselected.handle("[6] DBDELETE //T2/254/p/20");
    assert_eq!(noselect.status, 404);
    assert!(noselect.final_text.contains("Project not selected"));
    // Unit OID retires with the record: resolvable before, gone after.
    let retired = s.handle(&format!("[19b] DBGET !{oid}/OID"));
    assert_eq!(retired.status, 401);
    let events = s.drain_events();
    assert!(events.iter().any(|e| e == "#e# db unit 20 deleted"));
    assert_eq!(
        events
            .iter()
            .filter(|e| e == &"#e# db unit 20 deleted")
            .count(),
        1
    );
}

/// Mock determinism for DBCOPYSAFE unit copies: the copy lands as a new
/// database record with the given name and a fresh OID; occupied
/// destinations conflict; missing sources copy opaquely with 200
/// (mock-only pin, pending native capture). The `!oid` level-source 301
/// flow lives in `level_lifecycle_group_xml_and_copy`, not here.
#[test]
fn dbcopy_unit_copy_fresh_identity_and_conflicts() {
    let mut s = Server::new(AccessLevel::Program);
    assert_eq!(s.handle("[1] PROJECT NEW TEST").status, 200);
    assert_eq!(
        s.handle("[2] DBCREATENET 254 Local Cni 127.0.0.1:10001")
            .status,
        200
    );
    assert_eq!(s.handle("[3] PROJECT USE TEST").status, 200);
    assert_eq!(s.handle("[4] DBADDSAFE //TEST/254 Unit 20 Src").status, 200);
    let copied = s.handle("[5] DBCOPYSAFE //TEST/254/p/20 //TEST/254 21 Hall");
    assert_eq!(copied.status, 200);
    assert_eq!(copied.final_text, "200 OK");
    // The copy reads back as a database record under the new name, and the
    // source record is unaffected (no aliasing).
    let doc = s.handle("[6] DBGETXML //TEST/254/p/21");
    assert_eq!(doc.status, 200);
    assert!(doc
        .lines
        .iter()
        .chain(std::iter::once(&doc.final_text))
        .any(|line| line.contains("<Unit address=\"21\" name=\"Hall\"/>")));
    let srcdoc = s.handle("[6b] DBGETXML //TEST/254/p/20");
    assert!(srcdoc
        .lines
        .iter()
        .chain(std::iter::once(&srcdoc.final_text))
        .any(|line| line.contains("Src") && !line.contains("Hall")));
    // Fresh identity: the two records resolve distinct OIDs.
    let netdoc = s.handle("[6c] DBGETXML //TEST/254");
    assert_eq!(netdoc.status, 200);
    let oid_of = |addr: u8| {
        netdoc
            .lines
            .iter()
            .chain(std::iter::once(&netdoc.final_text))
            .find(|line| line.contains(&format!("<Address>{addr}</Address>")))
            .and_then(|line| {
                // The document can carry every unit on one line: search
                // for the OID after this unit's own address anchor.
                let anchor = line.find(&format!("<Address>{addr}</Address>"))?;
                let after = &line[anchor..];
                let start = after.find("<OID>")? + "<OID>".len();
                let end = after.find("</OID>")?;
                Some(after[start..end].to_string())
            })
            .expect("network XML carries the unit with its OID")
    };
    assert_ne!(oid_of(20), oid_of(21));
    // Copying onto an occupied address conflicts.
    let conflict = s.handle("[7] DBCOPYSAFE //TEST/254/p/20 //TEST/254 21 Hall");
    assert_eq!(conflict.status, 409);
    // A missing source copies opaquely with 200 (no 404 on this path).
    let opaque = s.handle("[8] DBCOPYSAFE //TEST/254/p/99 //TEST/254 40 X");
    assert_eq!(opaque.status, 200);
    // Malformed shapes fail closed.
    for (line, status, fragment) in [
        ("[9] DBCOPYSAFE //TEST/254/p/20", 400, "source, parent"),
        (
            "[10] DBCOPYSAFE //TEST/254/p/20 //TEST/254 256 X",
            400,
            "Invalid database address",
        ),
        (
            "[11] DBCOPYSAFE //TEST/254/p/20 //TEST/254 22 #",
            400,
            "Invalid tag name",
        ),
        (
            "[12] DBCOPYSAFE //TEST/254/p/20 //TEST/253 22 X",
            404,
            "Network not found",
        ),
    ] {
        let response = s.handle(line);
        assert_eq!(response.status, status, "{line}");
        assert!(response.final_text.contains(fragment), "{line}");
    }
    // Mixed-case verbs fold like the rest of the surface.
    let mixed = s.handle("[13] DBcopysafe //TEST/254/p/20 //TEST/254 22 Mixed");
    assert_eq!(mixed.status, 200);
}

/// Mock determinism for DBSETSAFE unit fields: absent units fail with 401,
/// stored fields mirror into later GET reads, values join across words.
#[test]
fn dbset_unit_field_store_readback_and_absent() {
    let mut s = Server::new(AccessLevel::Program);
    assert_eq!(s.handle("[1] PROJECT NEW TEST").status, 200);
    assert_eq!(
        s.handle("[2] DBCREATENET 254 Local Cni 127.0.0.1:10001")
            .status,
        200
    );
    assert_eq!(s.handle("[3] PROJECT USE TEST").status, 200);
    assert_eq!(
        s.handle("[4] DBADDSAFE //TEST/254 Unit 30 Study").status,
        200
    );
    // No record on either layer: 401, never an invented store. (An
    // unknown *network* instead stores opaquely with 200: unit_of only
    // resolves existing networks, so the 401 guard is bypassed.)
    let absent = s.handle("[5] DBSETSAFE //TEST/254/p/99/TagName X");
    assert_eq!(absent.status, 401);
    let absent_net = s.handle("[5b] DBSETSAFE //TEST/253/p/99/TagName X");
    assert_eq!(absent_net.status, 200);
    // Malformed shapes and values fail closed.
    for (line, fragment) in [
        ("[6] DBSETSAFE", "requires a path and value"),
        ("[7] DBSETSAFE //TEST/254/p/#/TagName X", "requires a path"),
        (
            "[8] DBSETSAFE //TEST/254/p/30/TagName #",
            "Invalid field value",
        ),
    ] {
        let response = s.handle(line);
        assert_eq!(response.status, 400, "{line}");
        assert!(response.final_text.contains(fragment), "{line}");
    }
    // TagName is a database field rather than a native unit SHOW/GET
    // property, both before and after it is stored.
    let baseline = s.handle("[8b] GET //TEST/254/p/30 TagName");
    assert_eq!(baseline.status, 402);
    // Multi-word values join and remain available through DBGET.
    let stored = s.handle("[9] DBSETSAFE //TEST/254/p/30/TagName Two Words");
    assert_eq!(stored.status, 200);
    let read = s.handle("[10] GET //TEST/254/p/30 TagName");
    assert_eq!(read.status, 402);
    let dbread = s.handle("[10b] DBGET //TEST/254/p/30/TagName");
    assert_eq!(dbread.status, 200);
    assert!(dbread
        .lines
        .iter()
        .chain(std::iter::once(&dbread.final_text))
        .any(|line| line.contains("Two Words")));
}

/// Mock determinism for the network rename chain: DBRENAMENETSAFE moves the
/// database network, NET RENAME moves it again, units travel with their
/// network on both layers, and guard rails fail closed.
#[test]
fn network_rename_chain_moves_units_and_guards() {
    let mut s = Server::new(AccessLevel::Program);
    assert_eq!(s.handle("[1] PROJECT NEW TEST").status, 200);
    assert_eq!(
        s.handle("[2] DBCREATENET 254 Local Cni 127.0.0.1:10001")
            .status,
        200
    );
    assert_eq!(s.handle("[3] PROJECT USE TEST").status, 200);
    assert_eq!(
        s.handle("[4] DBADDSAFE //TEST/254 Unit 20 Traveller")
            .status,
        200
    );
    // Malformed shapes fail before any lookup.
    for (line, status, fragment) in [
        ("[5] DBRENAMENETSAFE", 400, "No network given"),
        ("[6] DBRENAMENETSAFE 254 254", 401, "same address"),
        (
            "[7] DBRENAMENETSAFE 254 999",
            401,
            "Invalid network address",
        ),
        ("[8] NET RENAME //TEST/254", 400, "address and destination"),
        (
            "[9] NET RENAME //TEST/254 253 bogus",
            400,
            "Unknown rename argument",
        ),
        ("[9b] NET RENAME //TEST/254 254", 400, "must differ"),
        (
            "[9c] NET RENAME //TEST/ABC 252",
            400,
            "Invalid network address",
        ),
        ("[9d] NET RENAME //TEST/250 252", 404, "Network not found"),
    ] {
        let response = s.handle(line);
        assert_eq!(response.status, status, "{line}");
        assert!(response.final_text.contains(fragment), "{line}");
    }
    // Unselected projects refuse both verbs before any lookup. NOTE:
    // PROJECT NEW selects, so select away to T2 (which exists but holds
    // no networks, hence the native missing-element response).
    assert_eq!(s.handle("[10a] PROJECT NEW T2").status, 200);
    assert_eq!(s.handle("[10b] PROJECT USE T2").status, 200);
    for (line, fragment) in [
        ("[10c] DBRENAMENETSAFE 254 253", "Element 254 not found"),
        ("[10d] NET RENAME //TEST/254 253", "Project not selected"),
    ] {
        let response = s.handle(line);
        assert_eq!(
            response.status,
            if line.contains("DBRENAMENET") {
                401
            } else {
                404
            },
            "{line}"
        );
        assert!(response.final_text.contains(fragment), "{line}");
    }
    assert_eq!(s.handle("[10e] PROJECT USE TEST").status, 200);
    // Missing source network fails closed.
    let missing = s.handle("[10f] DBRENAMENETSAFE 253 252");
    assert_eq!(missing.status, 401);
    // The database rename moves the network; the old path is gone.
    let moved = s.handle("[11] DBRENAMENETSAFE 254 253");
    assert_eq!(moved.status, 200);
    assert_eq!(s.handle("[12] NET OPEN //TEST/254").status, 404);
    assert_eq!(s.handle("[13] NET OPEN //TEST/253").status, 200);
    // The unit travels with its network on both layers; stale paths 401.
    let arrived = s.handle("[14] GET //TEST/253/p/20 *");
    assert_eq!(arrived.status, 300);
    let dbdoc = s.handle("[15] DBGETXML //TEST/253/p/20");
    assert_eq!(dbdoc.status, 200);
    assert_eq!(s.handle("[15b] GET //TEST/254/p/20 *").status, 401);
    // Same-project stale DB path: 401 Network not found (project scoping
    // still matches, unlike the cross-project rename case).
    assert_eq!(s.handle("[15c] DBGETXML //TEST/254/p/20").status, 401);
    // Occupied destinations conflict with the source restored.
    assert_eq!(
        s.handle("[15d] DBCREATENET 252 Local Cni 127.0.0.1:10001")
            .status,
        200
    );
    let busy = s.handle("[15e] DBRENAMENETSAFE 253 252");
    assert_eq!(busy.status, 401);
    assert_eq!(s.handle("[15f] NET OPEN //TEST/253").status, 200);
    let busy = s.handle("[15g] NET RENAME //TEST/253 252");
    assert_eq!(busy.status, 409);
    assert_eq!(s.handle("[15h] NET OPEN //TEST/253").status, 200);
    // NET RENAME moves it again, with reference fixing by default.
    let renamed = s.handle("[16] NET RENAME //TEST/253 251 nofixrefs");
    assert_eq!(renamed.status, 200);
    assert_eq!(s.handle("[17] NET OPEN //TEST/251").status, 200);
    assert_eq!(s.handle("[17b] NET OPEN //TEST/253").status, 404);
    let arrived = s.handle("[18] GET //TEST/251/p/20 *");
    assert_eq!(arrived.status, 300);
    let dbdoc = s.handle("[18b] DBGETXML //TEST/251/p/20");
    assert_eq!(dbdoc.status, 200);
    assert_eq!(s.handle("[18c] GET //TEST/253/p/20 *").status, 401);
    let events = s.drain_events();
    assert!(events.iter().any(|e| e == "#e# net renamed 254 253"));
    assert!(events.iter().any(|e| e == "#e# net renamed 253 251"));
}

/// Native NET SET_PROJECT_IDENTIFY grammar: one network and one encodable
/// 1..8-character value. The identify text is not a repository lookup.
#[test]
fn net_set_project_identify_native_grammar_and_guards() {
    let mut s = Server::new(AccessLevel::Program);
    assert_eq!(s.handle("[1] PROJECT NEW TEST").status, 200);
    assert_eq!(
        s.handle("[2] DBCREATENET 254 Local Cni 127.0.0.1:10001")
            .status,
        200
    );
    assert_eq!(s.handle("[3] PROJECT USE TEST").status, 200);
    let ok = s.handle("[4] NET SET_PROJECT_IDENTIFY //TEST/254 TEST");
    assert_eq!(ok.status, 200);
    assert_eq!(ok.final_text, "200 OK.");
    assert_eq!(
        s.handle("[4a] NET SET_PROJECT_IDENTIFY //TEST/254 TEST   \t")
            .status,
        200,
        "native tokenization ignores trailing delimiter whitespace"
    );
    assert_eq!(
        s.handle("[4b] NET SET_PROJECT_IDENTIFY //TEST/254 \"A B\" \t")
            .status,
        200,
        "trailing whitespace must not change a quoted identity"
    );
    // The value is an eight-character unit field, not a loaded-project
    // reference. A different valid value is accepted.
    assert_eq!(
        s.handle("[5] NET SET_PROJECT_IDENTIFY //TEST/254 NOPE")
            .status,
        200
    );
    assert_eq!(
        s.handle(r#"[5a] NET SET_PROJECT_IDENTIFY //TEST/254 "A\ B\"\\""#)
            .status,
        200,
        "mK quoting must retain spaces, quotes and backslashes"
    );
    // The network must still resolve in the selected project.
    let nonet = s.handle("[6] NET SET_PROJECT_IDENTIFY //TEST/250 TEST");
    assert_eq!(nonet.status, 401);
    assert!(nonet.final_text.contains("Network not found"));
    let bothbad = s.handle("[6b] NET SET_PROJECT_IDENTIFY //TEST/250 NOPE");
    assert_eq!(bothbad.status, 401);
    assert!(bothbad.final_text.contains("Network not found"));
    let bad_network_and_text = s.handle("[6bb] NET SET_PROJECT_IDENTIFY //TEST/250 {");
    assert_eq!(bad_network_and_text.status, 401);
    assert!(bad_network_and_text
        .final_text
        .contains("Network not found"));
    // Selected-away projects are refused.
    assert_eq!(s.handle("[6c] PROJECT NEW T2").status, 200);
    assert_eq!(s.handle("[6d] PROJECT USE T2").status, 200);
    let away = s.handle("[6e] NET SET_PROJECT_IDENTIFY //TEST/254 TEST");
    assert_eq!(away.status, 401);
    assert!(away.final_text.contains("Network not found"));
    assert_eq!(s.handle("[6f] PROJECT USE TEST").status, 200);
    // Malformed shapes and out-of-range lengths are parser errors.
    for (line, fragment) in [
        ("[7] NET SET_PROJECT_IDENTIFY", "address and project"),
        (
            "[7b] NET SET_PROJECT_IDENTIFY //TEST/254",
            "Missing parameter",
        ),
        (
            "[8] NET SET_PROJECT_IDENTIFY //TEST/254 TEST extra",
            "Too many parameters",
        ),
        (
            "[9b] NET SET_PROJECT_IDENTIFY //TEST/254 TOOLONG99",
            "too long",
        ),
    ] {
        let response = s.handle(line);
        assert_eq!(response.status, 400, "{line}");
        assert!(response.final_text.contains(fragment), "{line}");
    }
    // Native kS reports a six-bit encoding failure as operation status 408.
    let bad_character = s.handle("[9] NET SET_PROJECT_IDENTIFY //TEST/254 {");
    assert_eq!(bad_character.status, 408);
    assert_eq!(
        bad_character.final_text,
        "408 Operation failed: Character out of sixbit range"
    );
    // Native checks Java character length rather than UTF-8 byte length, so
    // five non-ASCII characters reach the six-bit range check (408, not 400).
    let unicode_character = s.handle("[9c] NET SET_PROJECT_IDENTIFY //TEST/254 ééééé");
    assert_eq!(unicode_character.status, 408);
    assert_eq!(
        unicode_character.final_text,
        "408 Operation failed: Character out of sixbit range"
    );
    // The command is a guard-only ack: setup lifecycle events aside, it
    // emits no identify-related events of its own.
    assert!(s
        .drain_events()
        .iter()
        .all(|e| !e.to_ascii_lowercase().contains("identify")));
}

/// Mock determinism for PROJECT RENAME: exact shapes fail closed, missing
/// sources 404, occupied destinations 409 with restore, the selection
/// follows the rename, and monitor access is denied.
#[test]
fn project_rename_selection_follow_and_guards() {
    let mut s = Server::new(AccessLevel::Program);
    assert_eq!(s.handle("[1] PROJECT NEW TEST").status, 200);
    assert_eq!(
        s.handle("[2] DBCREATENET 254 Local Cni 127.0.0.1:10001")
            .status,
        200
    );
    assert_eq!(s.handle("[3] PROJECT USE TEST").status, 200);
    assert_eq!(
        s.handle("[4] DBADDSAFE //TEST/254 Unit 20 Mover").status,
        200
    );
    for (line, status, fragment) in [
        ("[5] PROJECT RENAME", 400, "source and destination"),
        ("[6] PROJECT RENAME TEST", 400, "source and destination"),
        (
            "[7] PROJECT RENAME TEST T2 extra",
            400,
            "source and destination",
        ),
        ("[8] PROJECT RENAME TEST #", 400, "Invalid project name"),
        ("[9] PROJECT RENAME NOPE T2", 404, "Project not found"),
    ] {
        let response = s.handle(line);
        assert_eq!(response.status, status, "{line}");
        assert!(response.final_text.contains(fragment), "{line}");
    }
    // Occupied destinations conflict with the source restored.
    assert_eq!(s.handle("[10] PROJECT NEW T2").status, 200);
    let busy = s.handle("[11] PROJECT RENAME TEST T2");
    assert_eq!(busy.status, 409);
    let listed = s.handle("[12] PROJECT LIST");
    assert!(listed.lines.iter().any(|l| l == "TEST"));
    // PROJECT NEW T2 above re-selected current; select TEST back first.
    assert_eq!(s.handle("[12b] PROJECT USE TEST").status, 200);
    assert_eq!(s.handle("[12c] NET OPEN //TEST/254").status, 200);
    // The rename moves the project; the selection follows it. (PROJECT
    // NEW T2 above re-selected current, so select TEST back first.)
    assert_eq!(s.handle("[12c] PROJECT USE TEST").status, 200);
    // A database field keyed under the old path proves prefix remapping.
    assert_eq!(
        s.handle("[12d] DBSETSAFE //TEST/254/p/20/TagName Moved")
            .status,
        200
    );
    let moved = s.handle("[13] PROJECT RENAME TEST T3");
    assert_eq!(moved.status, 200);
    let listed = s.handle("[14] PROJECT LIST");
    assert!(listed.lines.iter().any(|l| l == "T3"));
    assert!(!listed.lines.iter().any(|l| l == "TEST"));
    assert_eq!(s.handle("[15] NET OPEN //T3/254").status, 200);
    // Stale old-path reads fail closed on every layer.
    assert_eq!(s.handle("[15b] NET OPEN //TEST/254").status, 404);
    assert_eq!(s.handle("[15c] GET //TEST/254/p/20 *").status, 401);
    assert_eq!(s.handle("[15d] DBGETXML //TEST/254/p/20").status, 404);
    // The unit travels on both layers and the db key followed the rename.
    let arrived = s.handle("[16] GET //T3/254/p/20 *");
    assert_eq!(arrived.status, 300);
    let dbdoc = s.handle("[16b] DBGETXML //T3/254/p/20");
    assert_eq!(dbdoc.status, 200);
    let dbfield = s.handle("[16c] DBGET //T3/254/p/20/TagName");
    assert_eq!(dbfield.status, 200);
    assert!(dbfield
        .lines
        .iter()
        .chain(std::iter::once(&dbfield.final_text))
        .any(|line| line.contains("Moved")));
    let events = s.drain_events();
    assert!(events.iter().any(|e| e == "#e# project T3 renamed"));
    // Monitor access cannot rename.
    let mut monitor = Server::new(AccessLevel::Monitor);
    let denied = monitor.handle("[1] PROJECT RENAME A B");
    assert_eq!(denied.status, 420);
}

/// CALCULATOR TEST consumes durable database units and the configured bounded
/// catalogue, reproducing the retained six-row native result envelope.
#[test]
fn calculator_catalogue_arithmetic_envelope_and_guards() {
    let directory = catalogue_dir();
    let mut s = Server::new(AccessLevel::Program).with_unitspec_dir(directory.clone());
    assert_eq!(s.handle("[1] PROJECT NEW TEST").status, 200);
    assert_eq!(
        s.handle("[2] DBCREATENET 254 Local Cni 127.0.0.1:10001")
            .status,
        200
    );
    assert_eq!(s.handle("[3] PROJECT USE TEST").status, 200);
    for (address, catalog, unit_type) in [
        (1, "5034N", "KEY4"),
        (2, "5500BUR", "BURDEN"),
        (3, "5500PS", "POWER"),
    ] {
        assert_eq!(
            s.handle(&format!(
                "[add-{address}] DBADDSAFE //TEST/254 Unit {address} U{address}"
            ))
            .status,
            200
        );
        assert_eq!(
            s.handle(&format!(
                "[catalog-{address}] DBSETSAFE //TEST/254/p/{address}/CatalogNumber {catalog}"
            ))
            .status,
            200
        );
        assert_eq!(
            s.handle(&format!(
                "[type-{address}] DBSETSAFE //TEST/254/p/{address}/UnitType {unit_type}"
            ))
            .status,
            200
        );
    }
    let calc = s.handle("[6] CALCULATOR TEST //TEST/254 ignored-trailing-token");
    assert_eq!(calc.status, 134);
    assert_eq!(
        calc.lines,
        [
            "134-result: OK",
            "134-current_supply(mA)=350",
            "134-current_consumption(mA)=18",
            "134-impedance(ohms)=944.0",
            "134-units_calculated=3",
        ]
    );
    assert_eq!(calc.final_text, "134 units_not_calculated=0");

    // The calculation uses database records, even when the mock-only physical
    // layer no longer contains the unit.
    assert_eq!(s.handle("[6a] MOCK BUS-DEL //TEST/254 1").status, 200);
    assert_eq!(
        s.handle("[6b] CALCULATOR TEST //TEST/254").lines,
        calc.lines
    );

    // A known load without a supply is a native-shaped FAILED result.
    assert_eq!(
        s.handle("[6b] DBCREATENET 253 Local Cni 127.0.0.1:10001")
            .status,
        200
    );
    assert_eq!(
        s.handle("[6c] DBADDSAFE //TEST/253 Unit 1 Load").status,
        200
    );
    assert_eq!(
        s.handle("[6d] DBSETSAFE //TEST/253/p/1/CatalogNumber 5034N")
            .status,
        200
    );
    assert_eq!(
        s.handle("[6e] DBSETSAFE //TEST/253/p/1/UnitType KEY4")
            .status,
        200
    );
    let failed = s.handle("[6f] CALCULATOR TEST //TEST/253");
    assert_eq!(failed.status, 134);
    assert_eq!(failed.lines[0], "134-result: FAILED");
    assert_eq!(failed.lines[1], "134-current_supply(mA)=0");
    assert_eq!(failed.lines[2], "134-current_consumption(mA)=18");
    assert_eq!(failed.lines[3], "134-impedance(ohms)=110000.0");

    for (line, status, fragment) in [
        ("[7] CALCULATOR TEST", 400, "Syntax Error"),
        ("[9] CALCULATOR TEST //TEST/250", 408, "Can't find network"),
    ] {
        let response = s.handle(line);
        assert_eq!(response.status, status, "{line}");
        assert!(response.final_text.contains(fragment), "{line}");
    }
    // Selected-away projects are refused.
    assert_eq!(s.handle("[10] PROJECT NEW T2").status, 200);
    assert_eq!(s.handle("[11] PROJECT USE T2").status, 200);
    let away = s.handle("[12] CALCULATOR TEST //TEST/254");
    assert_eq!(away.status, 404);
    assert!(away.final_text.contains("Project not selected"));
    std::fs::remove_dir_all(directory).unwrap();
}

#[test]
fn applications_catalogue_is_operator_supplied_validated_xml() {
    let missing = Server::new(AccessLevel::Program).handle("[1] APPLICATIONS GET_CATALOG");
    assert_eq!(missing.status, 408);
    assert_eq!(
        missing.final_text,
        "408 Operation failed: bad application catalog filename: unitspec/applications.xml (No such file or directory)"
    );

    let directory = catalogue_dir();
    let mut server = Server::new(AccessLevel::Program).with_unitspec_dir(directory.clone());
    let response = server.handle("[2] APPLICATIONS GET_CATALOG");
    assert_eq!(response.status, 344);
    assert_eq!(
        response.lines,
        [
            "343-Begin XML Snippet",
            "347-<?xml version=\"1.0\"?>",
            "347-<Applications><Application Address=\"56\" Name=\"Lighting\"/></Applications>",
        ]
    );
    assert_eq!(response.final_text, "344 End XML Snippet");
    assert_eq!(
        server.handle("[3] APPLICATIONS GET_CATALOG extra").status,
        400
    );
    std::fs::remove_dir_all(directory).unwrap();
}

#[test]
fn repository_transform_leaf_help_matches_native_evidence() {
    let mut server = Server::new(AccessLevel::Program);
    for (command, expected) in [
        (
            "[app] APPLICATIONS GET_CATALOG ?",
            "[app] 101-Help: syntax: APPLICATIONS GET_CATALOG\n[app] 101 Help: Get the applications catalog as XML\n",
        ),
        (
            "[calc] CALCULATOR TEST ?",
            "[calc] 101-Help: syntax: CALCULATOR TEST <network-address>\n[calc] 101-Help: Run the calculator for the given network\n[calc] 101 Help: <network-address> is the network to calculate.\n",
        ),
        (
            "[cgl-in] CGL IMPORT ?",
            "[cgl-in] 101 Help: syntax: CGL IMPORT <project-name> << <end-tag>>\n",
        ),
        (
            "[cgl-out] CGL EXPORT ?",
            "[cgl-out] 101 Help: syntax: CGL EXPORT <project-name> [ network_list [application_list] ]\n",
        ),
        (
            "[repo] REPOSITORY USE ?",
            "[repo] 101 Help: syntax: REPOSITORY USE NUMERIC_INDEX\n",
        ),
        (
            "[migrate] TRANSFORM MIGRATE_SQL ?",
            "[migrate] 101 Help: syntax: TRANSFORM MIGRATE_SQL <source-name>\n",
        ),
        (
            "[project] TRANSFORM PROJECT ?",
            "[project] 101 Help: syntax: TRANSFORM PROJECT [--test] <project-name> [<xslt-file-name> [<output-project-name>]]\n",
        ),
        (
            "[sql-xml] TRANSFORM SQL_TO_XML ?",
            "[sql-xml] 101 Help: syntax: TRANSFORM SQL_TO_XML <source-name> [dest-name]\n",
        ),
        (
            "[sql-cg2] TRANSFORM SQL_TO_XML_CGATE2 ?",
            "[sql-cg2] 101 Help: syntax: TRANSFORM SQL_TO_XML_CGATE2 <source-name> [dest-name]\n",
        ),
        (
            "[xml-sql] TRANSFORM XML_TO_SQL ?",
            "[xml-sql] 101 Help: syntax: TRANSFORM XML_TO_SQL <source-name> [dest-name]\n",
        ),
    ] {
        assert_eq!(format_response(&server.handle(command)), expected, "{command}");
    }
}

#[test]
fn bounded_cgl_json_import_export_filters_and_skip_boundaries() {
    let mut server = Server::new(AccessLevel::Program);
    assert_eq!(server.handle("[1] PROJECT NEW TEST").status, 200);
    assert_eq!(
        server
            .handle("[2] DBCREATENET 254 Local Cni 127.0.0.1:10001")
            .status,
        200
    );
    assert_eq!(server.handle("[3] PROJECT USE TEST").status, 200);
    let document = r#"{"cglVersion":"1.1","localNetwork":254,"networks":[{"address":254,"name":"Local","applications":[{"address":56,"type":56,"name":"Lighting","groups":[{"address":1,"name":"Lounge","levels":[{"address":255,"name":"On"}]}]}]}]}"#;
    let imported = server.handle_document("[4] CGL IMPORT TEST", document);
    assert_eq!(imported.status, 200);
    assert_eq!(
        imported.lines,
        [
            "380-Importing routable networks from local Network 254 ...",
            "380-Importing Network 254",
            "380-  Created new application 254/56 ('Lighting')",
            "380-    Created new group 254/56/1 ('Lounge')",
            "380-      Created new level 254/56/1/255 ('On')",
            "380-Imported 3 object(s) of 1 network(s): 1 application(s), 1 group(s), 1 level(s) ",
        ]
    );
    assert_eq!(imported.final_text, "200 OK.");

    let exported = server.handle("[5] CGL EXPORT TEST 254 56");
    assert_eq!(exported.status, 344);
    assert_eq!(exported.lines[0], "343-Begin CGL snippet");
    assert_eq!(
        exported.final_text,
        "344 End CGL snippet [numberOfExportedObjects:3]"
    );
    let payload = exported.lines[1].strip_prefix("347-").unwrap();
    let exported_json: serde_json::Value = serde_json::from_str(payload).unwrap();
    assert_eq!(exported_json["cglVersion"], "1.1");
    assert_eq!(exported_json["localNetwork"], 254);
    assert_eq!(exported_json["networks"][0]["address"], 254);
    assert_eq!(
        exported_json["networks"][0]["applications"][0]["groups"][0]["name"],
        "Lounge"
    );

    // Existing labels are preserved while missing objects are added.
    let changed = r#"{"cglVersion":"1.1","localNetwork":254,"networks":[{"address":254,"applications":[{"address":56,"name":"Changed Lighting","groups":[{"address":1,"name":"Living Room"},{"address":2,"name":"Hall"}]}]}]}"#;
    let changed = server.handle_document("[6] CGL IMPORT TEST", changed);
    assert_eq!(changed.status, 200);
    assert!(changed
        .lines
        .iter()
        .any(|line| line.contains("Created new group 254/56/2 ('Hall')")));
    assert!(changed
        .lines
        .iter()
        .all(|line| !line.contains("Living Room") && !line.contains("Changed Lighting")));
    let exported = server.handle("[7] CGL EXPORT TEST 254 56");
    let exported_json: serde_json::Value =
        serde_json::from_str(exported.lines[1].strip_prefix("347-").unwrap()).unwrap();
    let groups = exported_json["networks"][0]["applications"][0]["groups"]
        .as_array()
        .unwrap();
    assert_eq!(groups[0]["name"], "Lounge");
    assert_eq!(groups[1]["name"], "Hall");

    // An application filter keeps the selected network shell.
    let filtered = server.handle("[8] CGL EXPORT TEST 254 57");
    let filtered_json: serde_json::Value =
        serde_json::from_str(filtered.lines[1].strip_prefix("347-").unwrap()).unwrap();
    assert_eq!(filtered_json["networks"].as_array().unwrap().len(), 1);
    assert!(filtered_json["networks"][0]["applications"]
        .as_array()
        .unwrap()
        .is_empty());

    // Unknown/non-routable networks produce the retained incomplete 380
    // result and do not create a network shell.
    let skipped = r#"{"cglVersion":"1.1","localNetwork":254,"networks":[{"address":253,"name":"Missing","route":[253]}]}"#;
    let skipped = server.handle_document("[9] CGL IMPORT TEST", skipped);
    assert_eq!(skipped.status, 380);
    assert_eq!(
        skipped.final_text,
        "380 CGL import not completed: Skipped 1 network(s). "
    );
    assert!(skipped.lines.iter().any(|line| line.contains("SKIPPED")));

    for (command, status) in [
        ("[10] CGL IMPORT TEST", 400),
        ("[11] REPOSITORY USE 1", 502),
        ("[12] TRANSFORM MIGRATE_SQL project.db", 502),
        ("[13] TRANSFORM PROJECT TEST", 502),
        ("[14] TRANSFORM SQL_TO_XML project.db", 502),
        ("[15] TRANSFORM SQL_TO_XML_CGATE2 project.db", 502),
        ("[16] TRANSFORM XML_TO_SQL project.xml", 502),
    ] {
        assert_eq!(server.handle(command).status, status, "{command}");
    }
}

/// Mock determinism for MOCK BUS-DEL: drops the physical-bus record while
/// the database record stays, with guards for shapes, addresses, networks
/// and selection.
#[test]
fn mock_bus_del_drops_physical_keeps_database() {
    let mut s = Server::new(AccessLevel::Program);
    assert_eq!(s.handle("[1] PROJECT NEW TEST").status, 200);
    assert_eq!(
        s.handle("[2] DBCREATENET 254 Local Cni 127.0.0.1:10001")
            .status,
        200
    );
    assert_eq!(s.handle("[3] PROJECT USE TEST").status, 200);
    assert_eq!(
        s.handle("[4] DBADDSAFE //TEST/254 Unit 20 Ghost").status,
        200
    );
    // Opaque database fields survive the physical drop.
    assert_eq!(
        s.handle("[4c] DBSETSAFE //TEST/254/p/20/TagName Kept")
            .status,
        200
    );
    for (line, status, fragment) in [
        ("[5] MOCK BUS-DEL", 400, "network path and address"),
        (
            "[6] MOCK BUS-DEL //TEST/254 256",
            400,
            "Invalid bus address",
        ),
        (
            "[6b] MOCK BUS-DEL //TEST/254 -1",
            400,
            "Invalid bus address",
        ),
        ("[6c] MOCK BUS-DEL //TEST/254 x", 400, "Invalid bus address"),
        ("[7] MOCK BUS-DEL //TEST/250 20", 404, "Network not found"),
        (
            "[8] MOCK BUS-DEL //TEST/254 99",
            404,
            "No physical unit at address",
        ),
    ] {
        let response = s.handle(line);
        assert_eq!(response.status, status, "{line}");
        assert!(response.final_text.contains(fragment), "{line}");
    }
    // Selected-away projects are refused.
    assert_eq!(s.handle("[9] PROJECT NEW T2").status, 200);
    assert_eq!(s.handle("[10] PROJECT USE T2").status, 200);
    let away = s.handle("[11] MOCK BUS-DEL //TEST/254 20");
    assert_eq!(away.status, 404);
    assert!(away.final_text.contains("Project not selected"));
    assert_eq!(s.handle("[12] PROJECT USE TEST").status, 200);
    // The drop removes physical presence; addressed GET/SHOW still resolve
    // the database object while PINGU and the network Units field stay empty.
    // Bare network forms resolve the same lookup path: an absent address
    // proves the form parses (no extra OID-issuing units are created, so
    // the process-global counter other tests pin is undisturbed).
    let bare = s.handle("[12b] MOCK BUS-DEL 254 21");
    assert_eq!(bare.status, 404);
    assert!(bare.final_text.contains("No physical unit at address"));
    let dropped = s.handle("[13] MOCK BUS-DEL //TEST/254 20");
    assert_eq!(dropped.status, 200);
    assert_eq!(dropped.final_text, "200 OK");
    assert_eq!(
        s.handle("[13b] GET //TEST/254 Units").final_text,
        "300 //TEST/254: Units="
    );
    assert_eq!(s.handle("[14] GET //TEST/254/p/20 *").status, 300);
    let dbdoc = s.handle("[15] DBGETXML //TEST/254/p/20");
    assert_eq!(dbdoc.status, 200);
    let dbfield = s.handle("[15b] DBGET //TEST/254/p/20/TagName");
    assert_eq!(dbfield.status, 200);
    assert!(dbfield
        .lines
        .iter()
        .chain(std::iter::once(&dbfield.final_text))
        .any(|line| line.contains("Kept")));
    // Repeating the drop reports the now-absent physical record.
    let repeat = s.handle("[16] MOCK BUS-DEL //TEST/254 20");
    assert_eq!(repeat.status, 404);
    let events = s.drain_events();
    assert!(events.iter().any(|e| e == "#e# mock bus-del 20"));
    assert_eq!(
        events
            .iter()
            .filter(|e| e == &"#e# mock bus-del 20")
            .count(),
        1
    );
}

/// Mock determinism for here-document commands: DBSETXML stores and mirrors
/// single-line field writes, multi-line documents stay opaque, and malformed
/// document commands fail closed.
#[test]
fn document_store_mirror_import_and_rejects() {
    let mut s = Server::new(AccessLevel::Program);
    assert_eq!(s.handle("[1] PROJECT NEW TEST").status, 200);
    assert_eq!(
        s.handle("[2] DBCREATENET 254 Local Cni 127.0.0.1:10001")
            .status,
        200
    );
    assert_eq!(s.handle("[3] PROJECT USE TEST").status, 200);
    assert_eq!(s.handle("[4] DBADDSAFE //TEST/254 Unit 20 Doc").status, 200);
    // Malformed document verbs fail closed.
    for (line, doc, status, fragment) in [
        // Bare verbs never reach a document arm at all.
        ("[5] DBSETXML", "", 400, "does not accept"),
        (
            "[6] DBSETXML //TEST/254/p/#/UnitName",
            "x",
            400,
            "requires a path",
        ),
        ("[7] CGL IMPORT", "", 400, "Syntax Error"),
        (
            "[8] CGL IMPORT NOPE",
            r#"{"cglVersion":"1.1","localNetwork":254,"networks":[]}"#,
            401,
            "Project not found",
        ),
        ("[9] FROBNICATE //TEST/254", "x", 400, "does not accept"),
    ] {
        let response = s.handle_document(line, doc);
        assert_eq!(response.status, status, "{line}");
        assert!(response.final_text.contains(fragment), "{line}");
    }
    // Single-line field stores mirror into the unit model (trailing newline
    // trimmed), while UnitName remains a database rather than SHOW property.
    let stored = s.handle_document("[10] DBSETXML //TEST/254/p/20/UnitName", "LOUNGE\n");
    assert_eq!(stored.status, 200);
    let read = s.handle("[11] GET //TEST/254/p/20 UnitName");
    assert_eq!(read.status, 402);
    let dbread = s.handle("[11b] DBGET //TEST/254/p/20/UnitName");
    assert_eq!(dbread.status, 200);
    assert!(dbread
        .lines
        .iter()
        .chain(std::iter::once(&dbread.final_text))
        .any(|line| line.contains("LOUNGE")));
    let plain = s.handle_document("[11c] DBSETXML //TEST/254/p/20/UnitName", "PLAIN");
    assert_eq!(plain.status, 200);
    // Multi-line documents stay opaque without mirroring, but the opaque
    // content itself remains readable through the database layer.
    let opaque = s.handle_document("[12] DBSETXML //TEST/254/p/20/UnitName", "one\ntwo\n");
    assert_eq!(opaque.status, 200);
    let kept = s.handle("[13] TREEXMLDETAIL //TEST/254");
    assert_eq!(kept.status, 344);
    assert!(kept
        .lines
        .iter()
        .chain(std::iter::once(&kept.final_text))
        .any(|line| line.contains("<PartName>PLAIN</PartName>")));
    let odoc = s.handle("[13b] DBGET //TEST/254/p/20/UnitName");
    assert_eq!(odoc.status, 200);
    // Unlike DBSETSAFE, document bodies accept `#` without rejection,
    // and the value mirrors like any single-line write.
    let hash = s.handle_document("[13c] DBSETXML //TEST/254/p/20/UnitName", "a#b\n");
    assert_eq!(hash.status, 200);
    let hashed = s.handle("[13d] TREEXMLDETAIL //TEST/254");
    assert_eq!(hashed.status, 344);
    assert!(hashed
        .lines
        .iter()
        .chain(std::iter::once(&hashed.final_text))
        .any(|line| line.contains("<PartName>a#b</PartName>")));
    // Invalid CGL is rejected without treating arbitrary text as an import.
    let import = s.handle_document("[14] CGL IMPORT TEST", "a\n\nb\nc\n");
    assert_eq!(import.status, 400);
    assert!(import.final_text.contains("Invalid CGL"));
    // Config-level access refuses documents outright.
    let mut config = Server::new(AccessLevel::Config);
    let refused = config.handle_document("[1] DBSETXML //TEST/254/p/20/UnitName", "X");
    assert_eq!(refused.status, 421);
}

#[test]
fn legacy_database_scalar_tags_and_network_renames_are_coherent() {
    let evidence: serde_json::Value = serde_json::from_str(include_str!(
        "../../testdata/fixtures/native_cgate_legacy_database.json"
    ))
    .unwrap();
    assert_eq!(
        evidence["schema"],
        "native-cgate-legacy-database-evidence-v1"
    );
    assert_eq!(evidence["oracle"]["version"], "3.4.0 build 2001");

    let mut server = Server::new(AccessLevel::Program);
    assert_eq!(server.handle("[1] PROJECT NEW DBL1").status, 200);
    assert_eq!(
        server
            .handle("[2] DBCREATENET 254 LocalA Cni 127.0.0.1:10001")
            .status,
        200
    );
    assert_eq!(
        server
            .handle("[3] DBCREATENET 253 LocalB Bridge 254/p/253")
            .status,
        200
    );
    assert_eq!(
        server
            .handle("[4] DBADDSAFE //DBL1/254 Unit 20 Original")
            .status,
        200
    );
    let network_xml = server.handle("[6] DBGETXML //DBL1/254");
    let document = network_xml.lines.join("\n");
    let unit = document
        .split("<Unit>")
        .find(|unit| unit.contains("<Address>20</Address>"))
        .expect("address-20 unit document");
    let oid = unit
        .split_once("<OID>")
        .and_then(|(_, value)| value.split_once("</OID>"))
        .map(|(oid, _)| oid)
        .expect("unit OID");

    assert_eq!(
        server
            .handle(&format!("[7] DBSET !{oid}/Address 20"))
            .final_text,
        "200 OK."
    );
    assert_eq!(
        server
            .handle(&format!("[8] DBSET !{oid}/TagName Legacy Unit"))
            .final_text,
        "200 OK."
    );
    assert_eq!(
        server
            .handle(&format!("[9] DBGET !{oid}/Address"))
            .final_text,
        format!("342 !{oid}/Address=20")
    );
    assert_eq!(
        server
            .handle(&format!("[10] DBGET !{oid}/TagName"))
            .final_text,
        format!("342 !{oid}/TagName=Legacy Unit")
    );

    let listing = server.handle("[11] DBTAGLIST");
    let observed = listing
        .lines
        .iter()
        .map(|row| format!("342-{row}"))
        .chain(std::iter::once(listing.final_text.clone()))
        .collect::<Vec<_>>();
    let expected = evidence["dbtaglist"]["selected_project_rows"]
        .as_array()
        .unwrap()
        .iter()
        .map(|row| row.as_str().unwrap().to_string())
        .collect::<Vec<_>>();
    assert_eq!(observed, expected);
    for (tag, pattern) in [("12", "legacy"), ("13", "LEGACY")] {
        let filtered = server.handle(&format!("[{tag}] DBTAGLIST {pattern}"));
        assert_eq!(filtered.status, 342);
        assert_eq!(
            filtered.final_text,
            evidence["dbtaglist"]["case_insensitive_filter"]["reply"]
                .as_str()
                .unwrap()
        );
    }
    assert_eq!(
        server.handle("[14] DBTAGLIST missing").final_text,
        evidence["dbtaglist"]["no_match"].as_str().unwrap()
    );
    assert_eq!(
        server.handle("[15] DBTAGLIST two words").final_text,
        evidence["dbtaglist"]["extra_token"].as_str().unwrap()
    );

    assert_eq!(
        server
            .handle("[16] DBSET //DBL1/254/p/20/TagName Renamed Legacy")
            .final_text,
        "200 OK."
    );
    assert_eq!(
        server
            .handle("[17] DBSET //DBL1/254/p/99/TagName Missing")
            .final_text,
        "401 Bad object or device ID: Element 99 not found."
    );
    assert_eq!(
        server
            .handle("[18] DBSET !ffffffff-ffff-ffff-ffff-ffffffffffff/TagName Missing")
            .final_text,
        "401 Bad object or device ID: Element !ffffffff-ffff-ffff-ffff-ffffffffffff not found."
    );
    assert_eq!(
        server
            .handle(&format!("[19] DBSET !{oid}/OID changed"))
            .final_text,
        "408 Operation failed: OID field can not be changed"
    );
    assert_eq!(
        server
            .handle("[20] DBSETSAFE //DBL1/254/p/20/TagName")
            .final_text,
        "401 Bad object or device ID: TagName can't be null or blank"
    );
    assert_eq!(
        server
            .handle("[21a] DBADDSAFE //DBL1/254 Unit 21 Occupied")
            .status,
        200
    );
    assert_eq!(
        server
            .handle("[21] DBSET //DBL1/254/p/21/TagName Temporary")
            .status,
        200
    );
    assert_eq!(
        server.handle("[22] DBSET //DBL1/254/p/21/TagName").status,
        200
    );

    // Native unsafe DBSET accepts an occupied address and corrupts lookup.
    // The maintained model rejects it before mutation.
    let duplicate = server.handle("[23] DBSET //DBL1/254/p/20/Address 21");
    assert_eq!(duplicate.status, 408);
    assert!(duplicate.final_text.contains("duplicate unit addresses"));
    assert_eq!(
        server
            .handle("[24] DBSET //DBL1/254/p/20/Address 22")
            .status,
        200
    );
    assert_eq!(
        server.handle("[25] DBGET //DBL1/254/p/22/Address").status,
        200
    );
    assert_eq!(
        server.handle("[26] DBGET //DBL1/254/p/20/Address").status,
        401
    );

    assert_eq!(
        server
            .handle("[27] DBRENAMENETSAFE //DBL1/254 252")
            .final_text,
        "401 Bad object or device ID: Invalid network address"
    );
    assert_eq!(
        server.handle("[28] DBRENAMENETSAFE 254 254").final_text,
        "401 Bad object or device ID: Can't rename network to the same address"
    );
    let safe = server.handle("[29] DBRENAMENETSAFE 254 252");
    assert_eq!(safe.final_text, "200 OK.");
    let bridge = server.handle("[30] DBGETXML //DBL1/253");
    assert!(bridge
        .lines
        .iter()
        .any(|line| line.contains("<InterfaceAddress>252/p/253</InterfaceAddress>")));
    let occupied = server.handle("[31] DBRENAMENETSAFE 252 253");
    assert_eq!(occupied.status, 401);
    assert_eq!(
        occupied.final_text,
        "401 Bad object or device ID: New network address in use"
    );
    assert_eq!(server.handle("[32] DBRENAMENET //DBL1/252 251").status, 200);
    assert_eq!(
        server.handle("[33] DBRENAMENET 251 251").final_text,
        "200 OK."
    );
    assert_eq!(server.handle("[34] DBRENAMENET 251 253").status, 408);
    assert_eq!(server.handle("[35] DBRENAMENET 251 nonsense").status, 408);
    let bridge = server.handle("[36] DBGETXML //DBL1/253");
    assert!(bridge
        .lines
        .iter()
        .any(|line| line.contains("<InterfaceAddress>251/p/253</InterfaceAddress>")));

    // Listings are selected-project relative and never leak another loaded
    // project's names.
    assert_eq!(server.handle("[37] PROJECT NEW OTHER").status, 200);
    assert_eq!(
        server
            .handle("[38] DBCREATENET 1 Secret Cni nowhere")
            .status,
        200
    );
    assert_eq!(server.handle("[39] PROJECT USE DBL1").status, 200);
    let listing = server.handle("[40] DBTAGLIST");
    let rendered = listing
        .lines
        .iter()
        .chain(std::iter::once(&listing.final_text))
        .cloned()
        .collect::<Vec<_>>()
        .join("\n");
    assert!(rendered.contains("251/TagName=Local"));
    assert!(!rendered.contains("Secret"));
    assert!(!rendered.contains("//DBL1/"));

    let add = server.handle("[41] DBADD //DBL1/251 Unit ignored trailing");
    assert_eq!(add.status, 301);
    let pending_oid = add.final_text.trim_start_matches("301 OID=");
    assert_eq!(
        server
            .handle(&format!("[42] DBGET !{pending_oid}/Address"))
            .final_text,
        "401 Bad object or device ID: Object is null"
    );
}

#[test]
fn legacy_database_add_copy_and_cross_project_subtrees_use_fresh_oids() {
    let mut server = Server::new(AccessLevel::Program);
    assert_eq!(server.handle("[1] PROJECT NEW SOURCE").status, 200);
    let detail = server.handle("[1a] DBADD Installation InstallationDetail trailing");
    assert_eq!(detail.status, 301);
    let detail_oid = detail.final_text.trim_start_matches("301 OID=").to_string();
    assert_eq!(
        server
            .handle(&format!("[1b] DBSET !{detail_oid}/SystemLocation Lab"))
            .status,
        200
    );
    assert_eq!(
        server
            .handle(&format!("[1c] DBGET !{detail_oid}/SystemLocation"))
            .final_text,
        format!("342 !{detail_oid}/SystemLocation=Lab")
    );
    assert_eq!(
        server
            .handle("[2] DBCREATENET 254 Source Cni nowhere")
            .status,
        200
    );
    let interface = server.handle("[2a] DBADD //SOURCE/254 Interface ignored");
    assert_eq!(interface.status, 301);
    let interface_oid = interface
        .final_text
        .trim_start_matches("301 OID=")
        .to_string();
    assert_eq!(
        server
            .handle(&format!("[2b] DBGET !{interface_oid}/InterfaceType"))
            .status,
        401
    );
    assert_eq!(
        server
            .handle(&format!("[2c] DBSET !{interface_oid}/InterfaceType Bridge"))
            .status,
        200
    );
    assert_eq!(
        server
            .handle(&format!("[2d] DBGET !{interface_oid}/InterfaceType"))
            .final_text,
        format!("342 !{interface_oid}/InterfaceType=Bridge")
    );
    let added = server.handle("[3] DBADD //SOURCE/254 Unit ignored ignored");
    assert_eq!(added.status, 301);
    let oid = added.final_text.trim_start_matches("301 OID=").to_string();
    assert_eq!(
        server.handle(&format!("[4] DBGET !{oid}/Address")).status,
        401
    );
    assert_eq!(
        server.handle(&format!("[5] DBGET !{oid}/TagName")).status,
        401
    );
    for (tag, field, value) in [
        ("6", "UnitType", "KEYGL5"),
        ("7", "Address", "20"),
        ("8", "TagName", "Original"),
    ] {
        assert_eq!(
            server
                .handle(&format!("[{tag}] DBSET !{oid}/{field} {value}"))
                .status,
            200
        );
    }
    assert!(server
        .handle("[9] DBTAGLIST")
        .final_text
        .contains("254/p/20/TagName=Original"));

    let same = server.handle("[10] DBCOPY //SOURCE/254/p/20 //SOURCE/254 trailing");
    assert_eq!(same.status, 301);
    let same_oid = same.final_text.trim_start_matches("301 OID=").to_string();
    assert_ne!(same_oid, oid);
    assert_eq!(
        server
            .handle(&format!("[11] DBGET !{same_oid}/Address"))
            .status,
        401
    );
    assert_eq!(
        server
            .handle(&format!("[12] DBGET !{same_oid}/TagName"))
            .status,
        401
    );
    assert_eq!(
        server
            .handle(&format!("[13] DBGET !{same_oid}/UnitType"))
            .final_text,
        format!("342 !{same_oid}/UnitType=KEYGL5")
    );
    assert_eq!(
        server
            .handle(&format!("[14] DBSET !{same_oid}/Address 21"))
            .status,
        200
    );
    assert_eq!(
        server
            .handle(&format!("[15] DBSET !{same_oid}/TagName Same"))
            .status,
        200
    );

    assert_eq!(server.handle("[16] PROJECT NEW DEST").status, 200);
    assert_eq!(
        server
            .handle("[17] DBCREATENET 1 Destination Cni nowhere")
            .status,
        200
    );
    assert_eq!(server.handle("[18] PROJECT USE SOURCE").status, 200);
    let cross = server.handle("[19] DBCOPY //SOURCE/254/p/20 //DEST/1 ignored");
    assert_eq!(cross.status, 301);
    let cross_oid = cross.final_text.trim_start_matches("301 OID=").to_string();
    assert_ne!(cross_oid, oid);
    assert_eq!(server.handle("[20] PROJECT USE DEST").status, 200);
    let tags = format_response(&server.handle("[21] DBTAGLIST"));
    assert!(tags.contains("1/p/20/TagName=Original"));
    assert_eq!(
        server
            .handle(&format!("[22] DBGET !{cross_oid}/UnitType"))
            .final_text,
        format!("342 !{cross_oid}/UnitType=KEYGL5")
    );

    assert_eq!(server.handle("[23] PROJECT USE SOURCE").status, 200);
    for (command, expected) in [
        ("[23a] DBADDSAFE //SOURCE/254 Application 56 Lighting", 200),
        ("[23b] DBADDSAFE //SOURCE/254/56 Group 7 GroupSeven", 200),
        ("[23c] DBADDSAFE //SOURCE/254/56/7 Level 3 LevelThree", 301),
    ] {
        let response = server.handle(command);
        assert_eq!(response.status, expected, "{command}: {response:?}");
    }
    let netvar = server.handle("[23d] DBADD //SOURCE/254/56 NetVar");
    assert_eq!(netvar.status, 301);
    let netvar_oid = netvar.final_text.trim_start_matches("301 OID=");
    assert_eq!(
        server
            .handle(&format!("[23e] DBSET !{netvar_oid}/Address 8"))
            .status,
        200
    );
    assert_eq!(
        server
            .handle(&format!("[23f] DBSET !{netvar_oid}/TagName Variable"))
            .status,
        200
    );
    let child = server.handle(&format!("[23g] DBADD !{netvar_oid} Level"));
    assert_eq!(child.status, 301);
    let child_oid = child.final_text.trim_start_matches("301 OID=");
    for (tag, field, value) in [
        ("23h", "Address", "1"),
        ("23i", "TagName", "Child"),
        ("23j", "Value", "77"),
    ] {
        assert_eq!(
            server
                .handle(&format!("[{tag}] DBSET !{child_oid}/{field} {value}"))
                .status,
            200
        );
    }
    let same_tree = server.handle("[24] DBCOPY //SOURCE/254/56 //SOURCE/254");
    assert_eq!(same_tree.status, 301);
    let same_tree_oid = same_tree
        .final_text
        .trim_start_matches("301 OID=")
        .to_string();
    assert_eq!(
        server
            .handle(&format!("[25] DBSET !{same_tree_oid}/Address 57"))
            .status,
        200
    );
    assert_eq!(
        server
            .handle(&format!("[26] DBSET !{same_tree_oid}/TagName Copy"))
            .status,
        200
    );
    let source_tags = format_response(&server.handle("[27] DBTAGLIST"));
    assert!(source_tags.contains("254/57/TagName=Copy"));
    assert!(!source_tags.contains("254/57/7/TagName=GroupSeven"));

    let cross_tree = server.handle("[28] DBCOPY //SOURCE/254/56 //DEST/1");
    assert_eq!(cross_tree.status, 301);
    let cross_tree_oid = cross_tree
        .final_text
        .trim_start_matches("301 OID=")
        .to_string();
    assert_eq!(server.handle("[29] PROJECT USE DEST").status, 200);
    let destination_tags = format_response(&server.handle("[30] DBTAGLIST"));
    assert!(destination_tags.contains("1/56/TagName=Lighting"));
    assert!(destination_tags.contains("1/56/7/TagName=GroupSeven"));
    assert!(destination_tags.contains("1/56/7/3/TagName=LevelThree"));
    assert!(destination_tags.contains("1/56/8/TagName=Variable"));
    assert!(destination_tags.contains("1/56/8/1/TagName=Child"));
    assert_eq!(
        server.handle("[31] DBSET //DEST/1/56/Address 58").status,
        200
    );
    assert_eq!(
        server
            .handle(&format!("[32] DBGET !{cross_tree_oid}/Address"))
            .final_text,
        format!("342 !{cross_tree_oid}/Address=58")
    );
    let moved_tags = format_response(&server.handle("[33] DBTAGLIST"));
    assert!(moved_tags.contains("1/58/8/1/TagName=Child"));
    assert!(!moved_tags.contains("1/56/TagName=Lighting"));
    assert_eq!(
        server
            .handle(&format!("[34] DBDELETE !{cross_tree_oid}"))
            .status,
        200
    );
    let deleted_tags = format_response(&server.handle("[35] DBTAGLIST"));
    assert!(!deleted_tags.contains("1/58/"));
}

#[test]
fn legacy_database_create_update_verify_and_new_track_physical_inventory() {
    let mut server = Server::new(AccessLevel::Program);
    assert_eq!(server.handle("[1] PROJECT NEW LIFE").status, 200);
    assert_eq!(
        server
            .handle("[2] DBCREATENET 254 Physical Cni nowhere")
            .status,
        200
    );
    assert_eq!(
        server.handle("[3] DBADDSAFE //LIFE/254 Unit 1 One").status,
        200
    );
    assert_eq!(
        server.handle("[4] DBADDSAFE //LIFE/254 Unit 2 Two").status,
        200
    );
    assert_eq!(
        server
            .handle("[5] DBSET //LIFE/254/p/1/UnitType KEYGL5")
            .status,
        200
    );
    assert_eq!(
        server.handle("[6] SET //LIFE/254/p/1 Address 3").status,
        200
    );
    let different = server.handle("[7] DBVERIFY trailing ignored");
    assert_eq!(different.status, 408);
    assert_eq!(different.lines.len(), 2);
    assert!(different
        .lines
        .iter()
        .all(|line| line.starts_with("345-Difference: ")));

    assert_eq!(server.handle("[8] DBUPDATE Physical").status, 200);
    let retained = server.handle("[9] DBVERIFY");
    assert_eq!(retained.status, 408);
    assert_eq!(retained.lines.len(), 1);
    assert_eq!(
        server
            .handle("[10] DBUPDATE //LIFE/254 UnitDelete ignored")
            .status,
        200
    );
    assert_eq!(server.handle("[11] DBVERIFY").status, 200);
    assert_eq!(server.handle("[12] MOCK BUS-DEL //LIFE/254 2").status, 200);
    assert_eq!(
        server
            .handle("[13] DBUPDATE //LIFE/254/p/2 UnitDelete")
            .status,
        200
    );
    assert_eq!(server.handle("[14] DBGET //LIFE/254/p/2").status, 401);

    // DBCREATE replaces stale address/OID state with a fresh snapshot of
    // the still-live physical inventory.
    assert_eq!(server.handle("[15] DBCREATE trailing ignored").status, 200);
    assert_eq!(server.handle("[16] DBVERIFY").status, 200);
    assert_eq!(server.handle("[17] DBNEW trailing ignored").status, 200);
    let tags = format_response(&server.handle("[18] DBTAGLIST"));
    assert!(tags.contains("LIFE/TagName=LIFE"));
    assert!(!tags.contains("254/TagName="));
}
