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
    // Baseline: TagName is not seeded by DBADDSAFE, so the later readback
    // must come from the mirror, not setup data.
    let baseline = s.handle("[8b] GET //TEST/254/p/30 TagName");
    assert_eq!(baseline.status, 404);
    // Multi-word values join; the write mirrors into GET reads.
    let stored = s.handle("[9] DBSETSAFE //TEST/254/p/30/TagName Two Words");
    assert_eq!(stored.status, 200);
    let read = s.handle("[10] GET //TEST/254/p/30 TagName");
    assert_eq!(read.status, 300);
    assert!(read
        .lines
        .iter()
        .chain(std::iter::once(&read.final_text))
        .any(|line| line.contains("TagName=Two Words")));
    // The database layer observes the same write (rules out half-mirror).
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
        ("[5] DBRENAMENETSAFE", 400, "network and destination"),
        ("[6] DBRENAMENETSAFE 254 254", 400, "must differ"),
        (
            "[7] DBRENAMENETSAFE 254 999",
            400,
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
    // no networks, hence Network-not-found on the database verb).
    assert_eq!(s.handle("[10a] PROJECT NEW T2").status, 200);
    assert_eq!(s.handle("[10b] PROJECT USE T2").status, 200);
    for (line, fragment) in [
        ("[10c] DBRENAMENETSAFE 254 253", "Network not found"),
        ("[10d] NET RENAME //TEST/254 253", "Project not selected"),
    ] {
        let response = s.handle(line);
        assert_eq!(response.status, 404, "{line}");
        assert!(response.final_text.contains(fragment), "{line}");
    }
    assert_eq!(s.handle("[10e] PROJECT USE TEST").status, 200);
    // Missing source network fails closed.
    let missing = s.handle("[10f] DBRENAMENETSAFE 253 252");
    assert_eq!(missing.status, 404);
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
    assert_eq!(busy.status, 409);
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

/// Mock determinism for NET SET_PROJECT_IDENTIFY: network checked before
/// project, malformed shapes fail closed, unknown projects 404.
#[test]
fn net_set_project_identify_order_and_guards() {
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
    assert_eq!(ok.final_text, "200 OK");
    // Unknown project fails after the network resolves; unknown network
    // fails first — the both-bad case proves the order via the message.
    let noproject = s.handle("[5] NET SET_PROJECT_IDENTIFY //TEST/254 NOPE");
    assert_eq!(noproject.status, 404);
    assert!(noproject.final_text.contains("Project not found"));
    // Unknown network fails before any project lookup.
    let nonet = s.handle("[6] NET SET_PROJECT_IDENTIFY //TEST/250 TEST");
    assert_eq!(nonet.status, 404);
    assert!(nonet.final_text.contains("Network not found"));
    let bothbad = s.handle("[6b] NET SET_PROJECT_IDENTIFY //TEST/250 NOPE");
    assert_eq!(bothbad.status, 404);
    assert!(bothbad.final_text.contains("Network not found"));
    // Selected-away projects are refused.
    assert_eq!(s.handle("[6c] PROJECT NEW T2").status, 200);
    assert_eq!(s.handle("[6d] PROJECT USE T2").status, 200);
    let away = s.handle("[6e] NET SET_PROJECT_IDENTIFY //TEST/254 TEST");
    assert_eq!(away.status, 404);
    assert!(away.final_text.contains("Project not selected"));
    assert_eq!(s.handle("[6f] PROJECT USE TEST").status, 200);
    // Malformed shapes and names fail closed.
    for (line, fragment) in [
        ("[7] NET SET_PROJECT_IDENTIFY", "address and project"),
        (
            "[8] NET SET_PROJECT_IDENTIFY //TEST/254 TEST extra",
            "address and project",
        ),
        (
            "[9] NET SET_PROJECT_IDENTIFY //TEST/254 #",
            "address and project",
        ),
    ] {
        let response = s.handle(line);
        assert_eq!(response.status, 400, "{line}");
        assert!(response.final_text.contains(fragment), "{line}");
    }
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

/// Mock determinism for CALCULATOR TEST: the 134 envelope on every line
/// including the final, unit count from physical presence, and guards.
#[test]
fn calculator_envelope_count_and_guards() {
    let mut s = Server::new(AccessLevel::Program);
    assert_eq!(s.handle("[1] PROJECT NEW TEST").status, 200);
    assert_eq!(
        s.handle("[2] DBCREATENET 254 Local Cni 127.0.0.1:10001")
            .status,
        200
    );
    assert_eq!(s.handle("[3] PROJECT USE TEST").status, 200);
    assert_eq!(s.handle("[4] DBADDSAFE //TEST/254 Unit 20 A").status, 200);
    assert_eq!(s.handle("[5] DBADDSAFE //TEST/254 Unit 21 B").status, 200);
    let calc = s.handle("[6] CALCULATOR TEST //TEST/254");
    assert_eq!(calc.status, 134);
    assert!(calc
        .lines
        .iter()
        .chain(std::iter::once(&calc.final_text))
        .all(|l| l.starts_with("134-") || l.starts_with("134 ")));
    assert!(calc.lines.iter().any(|l| l == "134-units_calculated=2"));
    assert_eq!(calc.final_text, "134 result: OK");
    assert!(calc.lines.iter().any(|l| l == "134-units_not_calculated=0"));
    // Empty networks calculate zero units with the envelope intact.
    assert_eq!(
        s.handle("[6b] DBCREATENET 253 Local Cni 127.0.0.1:10001")
            .status,
        200
    );
    let empty = s.handle("[6c] CALCULATOR TEST //TEST/253");
    assert_eq!(empty.status, 134);
    assert!(empty.lines.iter().any(|l| l == "134-units_calculated=0"));
    // A database-only unit (physical record dropped) is not calculated:
    // the count observes physical presence, not database records.
    assert_eq!(s.handle("[6d] MOCK BUS-DEL //TEST/254 20").status, 200);
    let dbonly = s.handle("[6e] CALCULATOR TEST //TEST/254");
    assert_eq!(dbonly.status, 134);
    assert!(dbonly.lines.iter().any(|l| l == "134-units_calculated=1"));
    for (line, status, fragment) in [
        ("[7] CALCULATOR TEST", 400, "requires a network"),
        (
            "[8] CALCULATOR TEST //TEST/254 extra",
            400,
            "requires a network",
        ),
        ("[9] CALCULATOR TEST //TEST/250", 404, "Network not found"),
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
    // The drop removes physical presence; the database record stays.
    // Bare network forms resolve the same lookup path: an absent address
    // proves the form parses (no extra OID-issuing units are created, so
    // the process-global counter other tests pin is undisturbed).
    let bare = s.handle("[12b] MOCK BUS-DEL 254 21");
    assert_eq!(bare.status, 404);
    assert!(bare.final_text.contains("No physical unit at address"));
    let dropped = s.handle("[13] MOCK BUS-DEL //TEST/254 20");
    assert_eq!(dropped.status, 200);
    assert_eq!(dropped.final_text, "200 OK");
    assert_eq!(s.handle("[14] GET //TEST/254/p/20 *").status, 401);
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
/// single-line field writes, multi-line documents stay opaque, CGL IMPORT
/// counts non-blank lines, and malformed shapes fail closed.
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
        ("[7] CGL IMPORT", "", 400, "does not accept"),
        ("[8] CGL IMPORT NOPE", "a\n", 404, "Project not found"),
        ("[9] FROBNICATE //TEST/254", "x", 400, "does not accept"),
    ] {
        let response = s.handle_document(line, doc);
        assert_eq!(response.status, status, "{line}");
        assert!(response.final_text.contains(fragment), "{line}");
    }
    // Single-line field store mirrors into both read layers (trailing
    // newline trimmed); no-trailing-newline stores identically.
    let stored = s.handle_document("[10] DBSETXML //TEST/254/p/20/UnitName", "LOUNGE\n");
    assert_eq!(stored.status, 200);
    let read = s.handle("[11] GET //TEST/254/p/20 UnitName");
    assert_eq!(read.status, 300);
    assert!(read
        .lines
        .iter()
        .chain(std::iter::once(&read.final_text))
        .any(|line| line.contains("UnitName=LOUNGE")));
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
    let kept = s.handle("[13] GET //TEST/254/p/20 UnitName");
    assert!(kept
        .lines
        .iter()
        .chain(std::iter::once(&kept.final_text))
        .any(|line| line.contains("UnitName=PLAIN")));
    let odoc = s.handle("[13b] DBGET //TEST/254/p/20/UnitName");
    assert_eq!(odoc.status, 200);
    // Unlike DBSETSAFE, document bodies accept `#` without rejection,
    // and the value mirrors like any single-line write.
    let hash = s.handle_document("[13c] DBSETXML //TEST/254/p/20/UnitName", "a#b\n");
    assert_eq!(hash.status, 200);
    let hashed = s.handle("[13d] GET //TEST/254/p/20 UnitName");
    assert!(hashed
        .lines
        .iter()
        .chain(std::iter::once(&hashed.final_text))
        .any(|line| line.contains("UnitName=a#b")));
    // CGL import counts non-blank lines and records the event.
    let import = s.handle_document("[14] CGL IMPORT TEST", "a\n\nb\nc\n");
    assert_eq!(import.status, 200);
    assert!(import.lines.iter().any(|l| l.contains("imported=3")));
    let events = s.drain_events();
    assert!(events.iter().any(|e| e == "#e# cgl import TEST"));
    // Config-level access refuses documents outright.
    let mut config = Server::new(AccessLevel::Config);
    let refused = config.handle_document("[1] DBSETXML //TEST/254/p/20/UnitName", "X");
    assert_eq!(refused.status, 421);
}
