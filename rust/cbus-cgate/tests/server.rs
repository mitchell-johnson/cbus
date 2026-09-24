use cbus_cgate::{format_response, is_event_line, parse_command, AccessLevel, Server};

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
        ("[3] LABEL CLEAREDLT", "only supports CLEAREDLT"),
        ("[4] LABEL CLEAR //TEST/252/p/30", "only supports CLEAREDLT"),
        (
            "[5] LABEL CLEAREDLT //TEST/252/p/30 extra",
            "only supports CLEAREDLT",
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
    let gone = s.handle("[14] GET //TEST/254/p/30 *");
    assert_eq!(gone.status, 401);
    let arrived = s.handle("[15] GET //TEST/254/p/32 *");
    assert_eq!(arrived.status, 300);
    assert!(arrived
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
