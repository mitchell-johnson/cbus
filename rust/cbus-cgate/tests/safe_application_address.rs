//! Issue #125: typed Application Address via `DBSETSAFE`.
//!
//! Both `DBSETSAFE //PROJECT/NET/APPLICATION/Address byte` and
//! `DBSETSAFE !AppOID/Address byte` must perform the canonical remap
//! (path, descendants, creation-order slot, OIDs preserved; 408/409
//! conflicts pre-mutation), never an opaque `200`. Adjacent Application
//! TagName/Description selectors must refuse missing objects instead of
//! acknowledging opaquely (which previously let a later Address remap
//! resurrect a phantom).

use cbus_cgate::{AccessLevel, Server};

fn harness() -> (Server, String) {
    let mut s = Server::new(AccessLevel::Program);
    assert_eq!(s.handle("[1] PROJECT NEW T125A").status, 200);
    assert_eq!(
        s.handle("[2] DBCREATENET 254 Local Cni 127.0.0.1:10001")
            .status,
        200
    );
    assert_eq!(
        s.handle("[3] DBADDSAFE //T125A/254 Application 80 App80")
            .status,
        301
    );
    assert_eq!(
        s.handle("[4] DBADDSAFE //T125A/254/80 Group 8 Grp8").status,
        301
    );
    let level = s.handle("[5] DBADDSAFE //T125A/254/80/8 Level 4 Lvl4");
    assert_eq!(level.status, 301, "{level:?}");
    let oid = level
        .final_text
        .strip_prefix("301 OID=")
        .unwrap()
        .to_string();
    assert_eq!(
        s.handle(&format!("[6] DBSETSAFE !{oid}/Value 77")).status,
        200
    );
    let app = s.handle("[7] DBGETXML //T125A/254/80");
    assert_eq!(app.status, 200, "{app:?}");
    let app_oid = app.lines[0]
        .split("<OID>")
        .nth(1)
        .and_then(|rest| rest.split("</OID>").next())
        .expect("application OID in document")
        .to_string();
    (s, app_oid)
}

#[test]
fn safe_address_moves_path_descendants_and_identity_for_both_selectors() {
    let (mut s, app_oid) = harness();
    // Numeric SAFE readdress: canonical path moves, OID preserved.
    let moved = s.handle("[8] DBSETSAFE //T125A/254/80/Address 81");
    assert_eq!(moved.status, 200, "{moved:?}");
    assert_eq!(moved.final_text, "200 OK", "{moved:?}");
    let app = s.handle("[9] DBGETXML //T125A/254/81");
    assert_eq!(app.status, 200, "{app:?}");
    assert!(
        app.lines[0].contains("<Address>81</Address>"),
        "{:?}",
        app.lines
    );
    assert!(
        app.lines[0].contains(&format!("<OID>{app_oid}</OID>")),
        "{:?}",
        app.lines
    );
    assert!(
        app.lines[0].contains("<TagName>App80</TagName>"),
        "{:?}",
        app.lines
    );
    assert_eq!(s.handle("[10] DBGETXML //T125A/254/80").status, 401);
    // Descendants travel with names, order and values intact.
    assert_eq!(s.handle("[11] DBGETXML //T125A/254/81/8").status, 200);
    let value = s.handle("[12] DBGET //T125A/254/81/8/4/Value");
    assert_eq!(value.status, 342, "{value:?}");
    assert!(value.final_text.ends_with("=77"), "{value:?}");
    // Issued-OID SAFE readdress performs the same canonical move.
    let moved = s.handle(&format!("[13] DBSETSAFE !{app_oid}/Address 82"));
    assert_eq!(moved.status, 200, "{moved:?}");
    let app = s.handle("[14] DBGETXML //T125A/254/82");
    assert_eq!(app.status, 200, "{app:?}");
    assert!(
        app.lines[0].contains("<Address>82</Address>"),
        "{:?}",
        app.lines
    );
    assert!(
        app.lines[0].contains(&format!("<OID>{app_oid}</OID>")),
        "{:?}",
        app.lines
    );
    assert_eq!(s.handle("[15] DBGETXML //T125A/254/81").status, 401);
    let oid_address = s.handle(&format!("[16] DBGET !{app_oid}/Address"));
    assert_eq!(oid_address.status, 342, "{oid_address:?}");
    assert!(oid_address.final_text.ends_with("=82"), "{oid_address:?}");
}

#[test]
fn safe_address_and_tagname_refuse_without_mutation_or_phantom() {
    let (mut s, app_oid) = harness();
    assert_eq!(
        s.handle("[8] DBADDSAFE //T125A/254 Application 83 Other83")
            .status,
        301
    );
    // 408 conflict: state untouched.
    let conflict = s.handle("[9] DBSETSAFE //T125A/254/80/Address 83");
    assert_eq!(conflict.status, 408, "{conflict:?}");
    let app = s.handle("[10] DBGETXML //T125A/254/80");
    assert_eq!(app.status, 200, "{app:?}");
    assert!(
        app.lines[0].contains("<Address>80</Address>"),
        "{:?}",
        app.lines
    );
    // No-op readdress is accepted and stable.
    assert_eq!(
        s.handle("[11] DBSETSAFE //T125A/254/80/Address 80").status,
        200
    );
    assert_eq!(s.handle("[12] DBGETXML //T125A/254/80").status, 200);
    // Missing numeric source is refused, never opaquely acknowledged, and
    // creates no phantom object a later write could resurrect.
    assert_eq!(
        s.handle("[13] DBSETSAFE //T125A/254/99/Address 78").status,
        401
    );
    assert_eq!(s.handle("[14] DBGETXML //T125A/254/78").status, 401);
    assert_eq!(s.handle("[15] DBGETXML //T125A/254/99").status, 401);
    // Adjacent TagName audit: missing numeric and unknown OID TagName are
    // refused, not opaquely stored.
    assert_eq!(
        s.handle("[16] DBSETSAFE //T125A/254/99/TagName Foo").status,
        401
    );
    assert_eq!(s.handle("[17] DBGETXML //T125A/254/99").status, 401);
    assert_eq!(
        s.handle("[18] DBSETSAFE !00000000-0000-0000-0000-00000000ffff/TagName Foo")
            .status,
        401
    );
    assert_eq!(
        s.handle("[19] DBSETSAFE !00000000-0000-0000-0000-00000000ffff/Address 78")
            .status,
        401
    );
    // Non-byte destination is refused before any mutation.
    let bad = s.handle("[20] DBSETSAFE //T125A/254/80/Address oops");
    assert_eq!(bad.status, 408, "{bad:?}");
    assert_eq!(s.handle("[21] DBGETXML //T125A/254/80").status, 200);
    // Valid TagName stays typed through both selectors (audit control).
    assert_eq!(
        s.handle("[22] DBSETSAFE //T125A/254/80/TagName Renamed")
            .status,
        200
    );
    assert_eq!(
        s.handle(&format!("[23] DBSETSAFE !{app_oid}/TagName Renamed2"))
            .status,
        200
    );
    let renamed = s.handle(&format!("[24] DBGET !{app_oid}/TagName"));
    assert_eq!(renamed.status, 342, "{renamed:?}");
    assert!(renamed.final_text.ends_with("=Renamed2"), "{renamed:?}");
}

#[test]
fn safe_address_selector_is_case_insensitive_but_canonical() {
    let (mut s, app_oid) = harness();
    // Lowercase `address` performs the same canonical remap; the pending
    // record keeps the canonical `Address` key so XML readback observes it.
    let moved = s.handle("[8] DBSETSAFE //T125A/254/80/address 81");
    assert_eq!(moved.status, 200, "{moved:?}");
    let app = s.handle("[9] DBGETXML //T125A/254/81");
    assert_eq!(app.status, 200, "{app:?}");
    assert!(
        app.lines[0].contains("<Address>81</Address>"),
        "{:?}",
        app.lines
    );
    assert!(
        app.lines[0].contains(&format!("<OID>{app_oid}</OID>")),
        "{:?}",
        app.lines
    );
    assert_eq!(s.handle("[10] DBGETXML //T125A/254/80").status, 401);
}

#[test]
fn safe_application_selectors_respect_project_selection() {
    let (mut s, _) = harness();
    assert_eq!(s.handle("[8] PROJECT NEW OTHER").status, 200);
    assert_eq!(s.handle("[9] PROJECT USE OTHER").status, 200);
    // Foreign-project numeric selectors are refused, never opaque; the
    // typed Application owner reports the unselected project (404).
    assert_eq!(
        s.handle("[10] DBSETSAFE //T125A/254/80/Address 81").status,
        404
    );
    assert_eq!(
        s.handle("[11] DBSETSAFE //T125A/254/80/TagName X").status,
        404
    );
    assert_eq!(s.handle("[12] PROJECT USE T125A").status, 200);
    assert_eq!(s.handle("[13] DBGETXML //T125A/254/80").status, 200);
}

#[test]
fn safe_address_refuses_incomplete_sibling_reservation_atomically() {
    let (mut s, _) = harness();
    // Legacy incomplete sibling reserves 81 (Address without TagName).
    let added = s.handle("[8] DBADD //T125A/254 Application");
    assert_eq!(added.status, 301, "{added:?}");
    let reserved = added
        .final_text
        .strip_prefix("301 OID=")
        .expect("incomplete OID")
        .to_string();
    assert_eq!(
        s.handle(&format!("[9] DBSET !{reserved}/Address 81"))
            .status,
        200
    );
    // Typed move onto the reserved byte refuses like an occupied address.
    let refused = s.handle("[10] DBSETSAFE //T125A/254/80/Address 81");
    assert_eq!(refused.status, 408, "{refused:?}");
    assert!(refused.final_text.contains("already in use"), "{refused:?}");
    // Atomic: source, reservation and descendants unchanged.
    assert_eq!(s.handle("[11] DBGETXML //T125A/254/80").status, 200);
    assert_eq!(s.handle("[12] DBGETXML //T125A/254/81").status, 401);
    assert_eq!(s.handle("[13] DBGETXML //T125A/254/81/8").status, 401);
    let value = s.handle("[14] DBGET //T125A/254/80/8/4/Value");
    assert_eq!(value.status, 342, "{value:?}");
    assert!(value.final_text.ends_with("=77"), "{value:?}");
    // The reservation still completes normally afterwards.
    assert_eq!(
        s.handle(&format!("[15] DBSET !{reserved}/TagName Reserved81"))
            .status,
        200
    );
    assert_eq!(s.handle("[16] DBGETXML //T125A/254/81").status, 200);
}

#[test]
fn safe_address_remaps_hyphen_alias_and_isolates_neighbors() {
    let mut s = Server::new(AccessLevel::Program);
    assert_eq!(s.handle("[1] PROJECT NEW TISO").status, 200);
    assert_eq!(
        s.handle("[2] DBCREATENET 254 Local Cni 127.0.0.1:10001")
            .status,
        200
    );
    assert_eq!(
        s.handle("[3] DBADDSAFE //TISO/254 Application 5 App5")
            .status,
        301
    );
    assert_eq!(
        s.handle("[4] DBADDSAFE //TISO/254 Application 50 App50")
            .status,
        301
    );
    assert_eq!(
        s.handle("[5] DBADDSAFE //TISO/254/5 Group 1 G1").status,
        301
    );
    // Moving 5 must not disturb neighboring 50 (slash and hyphen bounds).
    let moved = s.handle("[6] DBSETSAFE //TISO/254/5/Address 6");
    assert_eq!(moved.status, 200, "{moved:?}");
    assert_eq!(moved.final_text, "200 OK", "{moved:?}");
    assert_eq!(s.handle("[7] DBGETXML //TISO/254/6").status, 200);
    assert_eq!(s.handle("[8] DBGETXML //TISO/254/5").status, 401);
    let neighbor = s.handle("[9] DBGETXML //TISO/254/50");
    assert_eq!(neighbor.status, 200, "{neighbor:?}");
    assert!(
        neighbor.lines[0].contains("<TagName>App50</TagName>"),
        "{:?}",
        neighbor.lines
    );
    assert_eq!(s.handle("[10] DBGETXML //TISO/254/6/1").status, 200);
    // Hyphen retirement is observable through the move preflight: the freed
    // address admits a fresh Application while the new address stays
    // occupied for moves.
    assert_eq!(
        s.handle("[11] DBADDSAFE //TISO/254 Application 5 Reuse5")
            .status,
        301
    );
    let occupied = s.handle("[12] DBSETSAFE //TISO/254/50/Address 6");
    assert_eq!(occupied.status, 408, "{occupied:?}");
    assert_eq!(s.handle("[12b] DBGETXML //TISO/254/50").status, 200);
    assert_eq!(s.handle("[12c] DBGETXML //TISO/254/6").status, 200);
    // Group hyphen travels too: move Group 1->2, then reuse 1; moving the
    // reuse onto 2 refuses as occupied.
    assert_eq!(
        s.handle("[13] DBSETSAFE //TISO/254/6/1/Address 2").status,
        200
    );
    assert_eq!(s.handle("[14] DBGETXML //TISO/254/6/2").status, 200);
    assert_eq!(s.handle("[15] DBGETXML //TISO/254/6/1").status, 401);
    assert_eq!(
        s.handle("[16] DBADDSAFE //TISO/254/6 Group 1 Reuse1")
            .status,
        301
    );
    let group_occupied = s.handle("[17] DBSETSAFE //TISO/254/6/1/Address 2");
    assert_eq!(group_occupied.status, 408, "{group_occupied:?}");
}

#[test]
fn application_address_move_vectors_pin_exact_wire() {
    let text = include_str!("../../testdata/vectors/cgate_application_address_move.jsonl");
    let rows: Vec<serde_json::Value> = text
        .lines()
        .filter(|line| !line.trim().is_empty())
        .map(|line| serde_json::from_str(line).expect("vector row must parse"))
        .collect();
    assert_eq!(rows.len(), 12);
    let by_id = |id: &str| {
        rows.iter()
            .find(|row| row["id"].as_str() == Some(id))
            .unwrap_or_else(|| panic!("missing vector {id}"))
    };
    for row in &rows {
        assert_eq!(
            row["format"].as_str().unwrap(),
            "cbus-application-address-move-v1"
        );
        assert_eq!(row["issue"].as_u64().unwrap(), 125);
    }
    assert_eq!(by_id("safe-numeric-move")["status"].as_u64().unwrap(), 200);
    assert_eq!(
        by_id("safe-numeric-move")["final"].as_str().unwrap(),
        "200 OK"
    );
    assert_eq!(by_id("safe-oid-move")["status"].as_u64().unwrap(), 200);
    assert_eq!(by_id("safe-noop")["status"].as_u64().unwrap(), 200);
    assert_eq!(
        by_id("safe-occupied-conflict")["status"].as_u64().unwrap(),
        408
    );
    assert_eq!(
        by_id("safe-incomplete-sibling-refusal")["status"]
            .as_u64()
            .unwrap(),
        408
    );
    assert_eq!(
        by_id("safe-incomplete-sibling-refusal")["final"]
            .as_str()
            .unwrap(),
        "408 Operation failed: database Address is already in use"
    );
    assert_eq!(by_id("hyphen-alias-remap")["status"].as_u64().unwrap(), 200);
    assert_eq!(
        by_id("app-isolation-5-vs-50")["status"].as_u64().unwrap(),
        200
    );
    assert_eq!(
        by_id("missing-source-refusal")["status"].as_u64().unwrap(),
        401
    );
    assert_eq!(by_id("non-byte-refusal")["status"].as_u64().unwrap(), 408);
    assert_eq!(
        by_id("case-insensitive-selector")["status"]
            .as_u64()
            .unwrap(),
        200
    );
    // Spot-check the pinned wire against live behavior: numeric move,
    // incomplete refusal and non-byte refusal reply exactly as vectored.
    let (mut s, _) = harness();
    let moved = s.handle("[90] DBSETSAFE //T125A/254/80/Address 81");
    assert_eq!(moved.status, 200);
    assert_eq!(moved.final_text, "200 OK");
    let (mut t, _) = harness();
    let bad = t.handle("[91] DBSETSAFE //T125A/254/80/Address oops");
    assert_eq!(bad.status, 408);
    assert_eq!(
        bad.final_text,
        "408 Operation failed: Application Address must contain decimal digits only"
    );
}
