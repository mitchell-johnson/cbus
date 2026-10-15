use cbus_cgate::{AccessLevel, Server};

fn harness() -> (Server, String, String) {
    let mut s = Server::new(AccessLevel::Program);
    assert_eq!(s.handle("[1] PROJECT NEW T131").status, 200);
    assert_eq!(
        s.handle("[2] DBCREATENET 254 Local Cni 127.0.0.1:10001")
            .status,
        200
    );
    assert_eq!(
        s.handle("[3] DBADDSAFE //T131/254 Application 80 App80")
            .status,
        301
    );
    assert_eq!(
        s.handle("[4] DBADDSAFE //T131/254/80 Group 8 Grp8").status,
        301
    );
    let add = s.handle("[5] DBADDSAFE //T131/254/80/8 Level 4 Lvl4");
    assert_eq!(add.status, 301, "{}", add.final_text);
    let oid = add.final_text.strip_prefix("301 OID=").unwrap().to_string();
    assert_eq!(
        s.handle(&format!("[6] DBSETSAFE !{oid}/Value 77")).status,
        200
    );
    (s, oid, "T131".to_string())
}

fn netvar_harness() -> (Server, String, String) {
    let mut s = Server::new(AccessLevel::Program);
    assert_eq!(s.handle("[1] PROJECT NEW TN131").status, 200);
    assert_eq!(
        s.handle("[2] DBCREATENET 254 Local Cni 127.0.0.1:10001")
            .status,
        200
    );
    assert_eq!(
        s.handle("[3] DBADDSAFE //TN131/254 Application 56 Lighting")
            .status,
        301
    );
    assert_eq!(
        s.handle("[4] DBADDSAFE //TN131/254/56 NetVar 4 Variable")
            .status,
        301
    );
    let add = s.handle("[5] DBADDSAFE //TN131/254/56/4 Level 42 High");
    assert_eq!(add.status, 301, "{add:?}");
    let oid = add.final_text.strip_prefix("301 OID=").unwrap().to_string();
    assert_eq!(
        s.handle(&format!("[6] DBSETSAFE !{oid}/Value 23")).status,
        200
    );
    (s, oid, "TN131".to_string())
}

#[test]
fn ordinary_numeric_level_value_updates_typed_owner() {
    let (mut s, oid, _) = harness();
    // Ordinary numeric write must update the same typed owner, not an alias.
    let set = s.handle("[7] DBSETSAFE //T131/254/80/8/4/Value 99");
    assert_eq!(set.status, 200, "{}", set.final_text);
    let via_oid = s.handle(&format!("[8] DBGET !{oid}/Value"));
    assert_eq!(via_oid.status, 342, "{}", via_oid.final_text);
    assert!(
        via_oid.final_text.ends_with("=99"),
        "issued-OID readback must be 99: {}",
        via_oid.final_text
    );
    let via_numeric = s.handle("[9] DBGET //T131/254/80/8/4/Value");
    assert_eq!(via_numeric.status, 342, "{}", via_numeric.final_text);
    assert!(
        via_numeric.final_text.ends_with("=99"),
        "numeric readback must be 99: {}",
        via_numeric.final_text
    );
    // Fresh Level XML must also carry Value 99.
    let xml = s.handle(&format!("[10] DBGETXML !{oid}"));
    assert_eq!(xml.status, 200, "{}", xml.final_text);
    assert!(
        xml.lines.iter().any(|line| line.contains("Value=\"99\"")),
        "Level XML must carry Value 99: {:?}",
        xml.lines
    );
    // Ordinary owners admit bytes only, like the issued-OID initializer:
    // raw/out-of-range tails are refused, never stored as raw or an alias.
    for (tag, tail) in [("11", "oops"), ("12", "256"), ("13", "-1")] {
        let refused = s.handle(&format!("[{tag}] DBSETSAFE //T131/254/80/8/4/Value {tail}"));
        assert_eq!(refused.status, 400, "{tail}: {}", refused.final_text);
    }
    let stable = s.handle(&format!("[14] DBGET !{oid}/Value"));
    assert_eq!(stable.status, 342, "{}", stable.final_text);
    assert!(
        stable.final_text.ends_with("=99"),
        "refused writes must leave 99 intact: {}",
        stable.final_text
    );
    let xml = s.handle(&format!("[15] DBGETXML !{oid}"));
    assert_eq!(xml.status, 200, "{}", xml.final_text);
    assert!(
        xml.lines.iter().any(|line| line.contains("Value=\"99\"")),
        "Level XML must still carry Value 99: {:?}",
        xml.lines
    );
}

#[test]
fn ordinary_netvar_level_value_updates_typed_owner() {
    let (mut s, oid, _) = netvar_harness();
    let set = s.handle("[7] DBSETSAFE //TN131/254/56/4/42/Value 99");
    assert_eq!(set.status, 200, "{set:?}");
    for path in [
        format!("!{oid}/Value"),
        "//TN131/254/56/4/42/Value".to_string(),
    ] {
        let got = s.handle(&format!("[8] DBGET {path}"));
        assert_eq!(got.status, 342, "{path}: {got:?}");
        assert!(got.final_text.ends_with("=99"), "{path}: {got:?}");
    }
    let xml = s.handle(&format!("[9] DBGETXML !{oid}"));
    assert_eq!(xml.status, 200, "{xml:?}");
    assert!(
        xml.lines.iter().any(|line| line.contains("Value=\"99\"")),
        "{:?}",
        xml.lines
    );
    // Group/NetVar isolation: the Group Level from the other harness is
    // untouched (different project, no cross-talk).
    for (tag, tail) in [("10", "oops"), ("11", "256")] {
        let refused = s.handle(&format!(
            "[{tag}] DBSETSAFE //TN131/254/56/4/42/Value {tail}"
        ));
        assert_eq!(refused.status, 400, "{tail}: {refused:?}");
    }
    // Unsafe raw tails keep the issued-OID byte grammar: 408, never raw.
    let raw = s.handle("[12] DBSET //TN131/254/56/4/42/Value oops");
    assert_eq!(raw.status, 408, "{raw:?}");
    let stable = s.handle(&format!("[13] DBGET !{oid}/Value"));
    assert_eq!(stable.status, 342, "{stable:?}");
    assert!(stable.final_text.ends_with("=99"), "{stable:?}");
    let xml = s.handle(&format!("[14] DBGETXML !{oid}"));
    assert_eq!(xml.status, 200, "{xml:?}");
    assert!(
        xml.lines.iter().any(|line| line.contains("Value=\"99\"")),
        "{:?}",
        xml.lines
    );
    assert!(
        !xml.lines.iter().any(|line| line.contains("oops")),
        "raw must never enter XML: {:?}",
        xml.lines
    );
}

#[test]
fn ordinary_numeric_and_oid_setters_stay_consistent() {
    let (mut s, oid, _) = harness();
    // Numeric then OID: both address the same typed record.
    assert_eq!(
        s.handle("[7] DBSETSAFE //T131/254/80/8/4/Value 10").status,
        200
    );
    assert_eq!(
        s.handle(&format!("[8] DBSETSAFE !{oid}/Value 20")).status,
        200
    );
    for path in [
        format!("!{oid}/Value"),
        "//T131/254/80/8/4/Value".to_string(),
    ] {
        let got = s.handle(&format!("[9] DBGET {path}"));
        assert_eq!(got.status, 342, "{path}: {got:?}");
        assert!(got.final_text.ends_with("=20"), "{path}: {got:?}");
    }
    // OID setter keeps its byte grammar as well.
    let bad_oid = s.handle(&format!("[10] DBSETSAFE !{oid}/Value oops"));
    assert_eq!(bad_oid.status, 400, "{bad_oid:?}");
    let bad_unsafe_oid = s.handle(&format!("[11] DBSET !{oid}/Value oops"));
    assert_eq!(bad_unsafe_oid.status, 408, "{bad_unsafe_oid:?}");
    let bad_unsafe_numeric = s.handle("[12] DBSET //T131/254/80/8/4/Value oops");
    assert_eq!(bad_unsafe_numeric.status, 408, "{bad_unsafe_numeric:?}");
    let stable = s.handle(&format!("[13] DBGET !{oid}/Value"));
    assert!(stable.final_text.ends_with("=20"), "{stable:?}");
}

#[test]
fn ordinary_missing_and_foreign_values_refuse_without_alias() {
    let (mut s, oid, _) = harness();
    // Missing Level shape refuses; it must not create a scalar alias.
    let missing = s.handle("[7] DBSETSAFE //T131/254/80/8/9/Value 99");
    assert_eq!(missing.status, 401, "{missing:?}");
    let missing_get = s.handle("[8] DBGET //T131/254/80/8/9/Value");
    assert_eq!(missing_get.status, 401, "{missing_get:?}");
    // Foreign project shape refuses while selected project is T131.
    assert_eq!(s.handle("[9] PROJECT NEW OTHER").status, 200);
    assert_eq!(
        s.handle("[10] DBCREATENET 254 Elsewhere Cni 127.0.0.1:9")
            .status,
        200
    );
    assert_eq!(s.handle("[11] PROJECT USE T131").status, 200);
    let foreign = s.handle("[12] DBSETSAFE //OTHER/254/80/8/4/Value 99");
    assert_eq!(foreign.status, 401, "{foreign:?}");
    let foreign_get = s.handle("[13] DBGET //OTHER/254/80/8/4/Value");
    assert_eq!(foreign_get.status, 401, "{foreign_get:?}");
    // The established owner is untouched.
    let stable = s.handle(&format!("[14] DBGET !{oid}/Value"));
    assert!(stable.final_text.ends_with("=77"), "{stable:?}");
    // No alias was stored for the missing path: a later real Level at that
    // address starts NULL, not 99.
    let add = s.handle("[15] DBADDSAFE //T131/254/80/8 Level 9 Fresh9");
    assert_eq!(add.status, 301, "{add:?}");
    let fresh_oid = add.final_text.strip_prefix("301 OID=").unwrap().to_string();
    let fresh = s.handle(&format!("[16] DBGET !{fresh_oid}/Value"));
    assert_eq!(fresh.status, 342, "{fresh:?}");
    assert!(fresh.final_text.ends_with("=null"), "{fresh:?}");
}

#[test]
fn ordinary_invalid_values_leave_baseline_intact() {
    let (mut s, oid, _) = harness();
    assert_eq!(
        s.handle("[7] DBSETSAFE //T131/254/80/8/4/Value 55").status,
        200
    );
    for (tag, command, status) in [
        ("8", "DBSETSAFE //T131/254/80/8/4/Value oops", 400),
        ("9", "DBSETSAFE //T131/254/80/8/4/Value 256", 400),
        ("10", "DBSETSAFE //T131/254/80/8/4/Value -1", 400),
        ("11", "DBSETSAFE //T131/254/80/8/4/Value 3.5", 400),
        ("12", "DBSET //T131/254/80/8/4/Value oops", 408),
        ("13", "DBSET //T131/254/80/8/4/Value 256", 408),
    ] {
        let response = s.handle(&format!("[{tag}] {command}"));
        assert_eq!(response.status, status, "{command}: {response:?}");
    }
    let stable = s.handle(&format!("[15] DBGET !{oid}/Value"));
    assert!(stable.final_text.ends_with("=55"), "{stable:?}");
    let xml = s.handle(&format!("[16] DBGETXML !{oid}"));
    assert!(
        xml.lines.iter().any(|line| line.contains("Value=\"55\"")),
        "{:?}",
        xml.lines
    );
}

#[test]
fn ordinary_level_value_survives_save_close_load() {
    let (mut s, oid, _) = harness();
    assert_eq!(
        s.handle("[7] DBSETSAFE //T131/254/80/8/4/Value 88").status,
        200
    );
    let before = s.handle(&format!("[8] DBGETXML !{oid}"));
    assert_eq!(before.status, 200, "{before:?}");
    assert!(
        before.lines[0].contains("Value=\"88\""),
        "{:?}",
        before.lines
    );
    for (tag, command) in [
        ("9", "PROJECT SAVE T131"),
        ("10", "PROJECT CLOSE T131"),
        ("11", "PROJECT LOAD T131"),
        ("12", "PROJECT USE T131"),
    ] {
        let response = s.handle(&format!("[{tag}] {command}"));
        assert_eq!(response.status, 200, "{command}: {response:?}");
    }
    let via_oid = s.handle(&format!("[13] DBGET !{oid}/Value"));
    assert_eq!(via_oid.status, 342, "{via_oid:?}");
    assert!(via_oid.final_text.ends_with("=88"), "{via_oid:?}");
    let via_numeric = s.handle("[14] DBGET //T131/254/80/8/4/Value");
    assert_eq!(via_numeric.status, 342, "{via_numeric:?}");
    assert!(via_numeric.final_text.ends_with("=88"), "{via_numeric:?}");
    let after = s.handle(&format!("[15] DBGETXML !{oid}"));
    assert_eq!(after.status, 200, "{after:?}");
    assert!(after.lines[0].contains("Value=\"88\""), "{:?}", after.lines);
    assert!(after.lines[0].contains(&oid), "{:?}", after.lines);
    // Sibling data preserved: Group/Application readback still carries tags.
    let group = s.handle("[16] DBGETXML //T131/254/80/8");
    assert_eq!(group.status, 200, "{group:?}");
    assert!(
        group.lines[0].contains("<TagName>Grp8</TagName>"),
        "{:?}",
        group.lines
    );
    // A second numeric write after reload still owns the record.
    assert_eq!(
        s.handle("[17] DBSETSAFE //T131/254/80/8/4/Value 89").status,
        200
    );
    let reread = s.handle(&format!("[18] DBGET !{oid}/Value"));
    assert!(reread.final_text.ends_with("=89"), "{reread:?}");
}

#[test]
fn ordinary_copied_level_descendant_keeps_numeric_ownership() {
    // The maintained OID Level copy flow (DBCOPYSAFE !oid) is the narrow
    // copied-descendant profile: the destination has a fresh OID, the source
    // value is NULL for the caller initializer, and numeric writes must own
    // the copy without touching the source.
    let (mut s, src_oid, _) = harness();
    let copy = s.handle(&format!(
        "[7] DBCOPYSAFE !{src_oid} //T131/254/80/8 9 Copy9"
    ));
    assert_eq!(copy.status, 301, "{copy:?}");
    let copy_oid = copy
        .final_text
        .strip_prefix("301 OID=")
        .unwrap()
        .to_string();
    assert_ne!(copy_oid, src_oid);
    // Fresh copy starts NULL; initialize it as the native workflow does.
    let null = s.handle(&format!("[8] DBGET !{copy_oid}/Value"));
    assert_eq!(null.status, 342, "{null:?}");
    assert!(null.final_text.ends_with("=null"), "{null:?}");
    assert_eq!(
        s.handle(&format!("[9] DBSETSAFE !{copy_oid}/Value 77"))
            .status,
        200
    );
    // Numeric write owns the copy.
    assert_eq!(
        s.handle("[10] DBSETSAFE //T131/254/80/8/9/Value 99").status,
        200
    );
    let copy_value = s.handle(&format!("[11] DBGET !{copy_oid}/Value"));
    assert!(copy_value.final_text.ends_with("=99"), "{copy_value:?}");
    let copy_xml = s.handle(&format!("[12] DBGETXML !{copy_oid}"));
    assert!(
        copy_xml
            .lines
            .iter()
            .any(|line| line.contains("Value=\"99\"")),
        "{:?}",
        copy_xml.lines
    );
    // Source isolation: the original Level still reads its pre-copy value.
    let src_value = s.handle(&format!("[13] DBGET !{src_oid}/Value"));
    assert!(src_value.final_text.ends_with("=77"), "{src_value:?}");
    // Invalid numeric tails on the copy refuse without touching either owner.
    let refused = s.handle("[14] DBSETSAFE //T131/254/80/8/9/Value oops");
    assert_eq!(refused.status, 400, "{refused:?}");
    let still_copy = s.handle(&format!("[15] DBGET !{copy_oid}/Value"));
    assert!(still_copy.final_text.ends_with("=99"), "{still_copy:?}");
    let still_src = s.handle(&format!("[16] DBGET !{src_oid}/Value"));
    assert!(still_src.final_text.ends_with("=77"), "{still_src:?}");
}

#[test]
fn ordinary_refused_writes_never_replay_or_alias() {
    let (mut s, oid, _) = harness();
    assert_eq!(
        s.handle("[7] DBSETSAFE //T131/254/80/8/4/Value 60").status,
        200
    );
    // Each refusal is terminal: it leaves the typed owner intact, emits no
    // alias, and never replays a prior write. Database Value writes emit no
    // PCI or broadcast events; draining proves no hidden retry.
    for (tag, command, status) in [
        ("8", "DBSETSAFE //T131/254/80/8/4/Value oops", 400),
        ("9", "DBSET //T131/254/80/8/4/Value oops", 408),
        ("10", "DBSETSAFE //T131/254/80/8/9/Value 99", 401),
    ] {
        let response = s.handle(&format!("[{tag}] {command}"));
        assert_eq!(response.status, status, "{command}: {response:?}");
    }
    let _drained = s.drain_events();
    let stable = s.handle(&format!("[11] DBGET !{oid}/Value"));
    assert_eq!(stable.status, 342, "{stable:?}");
    assert!(stable.final_text.ends_with("=60"), "{stable:?}");
    let numeric = s.handle("[12] DBGET //T131/254/80/8/4/Value");
    assert!(numeric.final_text.ends_with("=60"), "{numeric:?}");
    // The refused missing address still has no owner: a later Level there
    // starts NULL, proving no alias was stored.
    let add = s.handle("[13] DBADDSAFE //T131/254/80/8 Level 9 Fresh9");
    assert_eq!(add.status, 301, "{add:?}");
}

fn level_oid_in_group_xml(lines: &[String]) -> String {
    let document: String = lines.concat();
    // Group XML carries the Group OID first, then one OID per Level.
    // The single-Level harnesses below always have exactly two.
    let oids: Vec<String> = document
        .match_indices("<OID>")
        .filter_map(|(start, _)| {
            let rest = &document[start + "<OID>".len()..];
            rest.split_once("</OID>").map(|(oid, _)| oid.to_string())
        })
        .collect();
    assert_eq!(oids.len(), 2, "single-Level Group XML: {document}");
    oids[1].clone()
}

#[test]
fn ordinary_application_copied_level_keeps_numeric_ownership() {
    // Issue #131 profile: after a complete Application copy the destination
    // Level has a fresh OID and Value="77". A selected-project numeric SAFE
    // write must own that copy (authoritative transition, exact envelope),
    // never alias-ack; raw tails refuse without touching either owner.
    let (mut s, src_oid, _) = harness();
    let copy = s.handle("[7] DBCOPYSAFE //T131/254/80 //T131/254 81 Copy81");
    assert_eq!(copy.status, 301, "{copy:?}");
    assert!(copy.final_text.starts_with("301 OID="), "{copy:?}");
    let copy_app_oid = copy
        .final_text
        .strip_prefix("301 OID=")
        .unwrap()
        .to_string();
    assert_ne!(copy_app_oid, src_oid);
    // The copy retains the source value and sibling data.
    let copied_group = s.handle("[8] DBGETXML //T131/254/81/8");
    assert_eq!(copied_group.status, 200, "{copied_group:?}");
    assert!(
        copied_group.lines[0].contains("Value=\"77\""),
        "{:?}",
        copied_group.lines
    );
    let copy_oid = level_oid_in_group_xml(&copied_group.lines);
    assert_ne!(copy_oid, src_oid);
    let copy_value = s.handle(&format!("[9] DBGET !{copy_oid}/Value"));
    assert_eq!(copy_value.status, 342, "{copy_value:?}");
    assert!(copy_value.final_text.ends_with("=77"), "{copy_value:?}");
    // Numeric SAFE owns the copy with the native numeric envelope.
    let set = s.handle("[10] DBSETSAFE //T131/254/81/8/4/Value 99");
    assert_eq!(set.status, 200, "{set:?}");
    assert_eq!(set.final_text, "200 OK.", "{set:?}");
    for path in [
        format!("!{copy_oid}/Value"),
        "//T131/254/81/8/4/Value".to_string(),
    ] {
        let got = s.handle(&format!("[11] DBGET {path}"));
        assert_eq!(got.status, 342, "{path}: {got:?}");
        assert!(got.final_text.ends_with("=99"), "{path}: {got:?}");
    }
    let copy_xml = s.handle(&format!("[12] DBGETXML !{copy_oid}"));
    assert_eq!(copy_xml.status, 200, "{copy_xml:?}");
    assert!(
        copy_xml
            .lines
            .iter()
            .any(|line| line.contains("Value=\"99\"")),
        "{:?}",
        copy_xml.lines
    );
    assert!(
        copy_xml.lines.iter().any(|line| line.contains(&copy_oid)),
        "copied OID preserved: {:?}",
        copy_xml.lines
    );
    // Source isolation: the original Level still reads 77.
    let src_value = s.handle(&format!("[13] DBGET !{src_oid}/Value"));
    assert!(src_value.final_text.ends_with("=77"), "{src_value:?}");
    let src_xml = s.handle(&format!("[14] DBGETXML !{src_oid}"));
    assert!(
        src_xml
            .lines
            .iter()
            .any(|line| line.contains("Value=\"77\"")),
        "{:?}",
        src_xml.lines
    );
    // Issued-OID setter addresses the same copy; envelopes stay distinct.
    let oid_set = s.handle(&format!("[15] DBSETSAFE !{copy_oid}/Value 98"));
    assert_eq!(oid_set.status, 200, "{oid_set:?}");
    assert_eq!(oid_set.final_text, "200 OK", "{oid_set:?}");
    let reread = s.handle("[16] DBGET //T131/254/81/8/4/Value");
    assert!(reread.final_text.ends_with("=98"), "{reread:?}");
    // Raw/out-of-range tails refuse (SAFE 400, unsafe 408) without touching
    // either owner or entering XML.
    for (tag, command, status) in [
        ("17", "DBSETSAFE //T131/254/81/8/4/Value oops", 400),
        ("18", "DBSETSAFE //T131/254/81/8/4/Value 256", 400),
        ("19", "DBSET //T131/254/81/8/4/Value oops", 408),
    ] {
        let refused = s.handle(&format!("[{tag}] {command}"));
        assert_eq!(refused.status, status, "{command}: {refused:?}");
    }
    let stable_copy = s.handle(&format!("[20] DBGET !{copy_oid}/Value"));
    assert!(stable_copy.final_text.ends_with("=98"), "{stable_copy:?}");
    let stable_src = s.handle(&format!("[21] DBGET !{src_oid}/Value"));
    assert!(stable_src.final_text.ends_with("=77"), "{stable_src:?}");
    let xml = s.handle(&format!("[22] DBGETXML !{copy_oid}"));
    assert!(
        xml.lines.iter().any(|line| line.contains("Value=\"98\"")),
        "{:?}",
        xml.lines
    );
    assert!(
        !xml.lines.iter().any(|line| line.contains("oops")),
        "raw must never enter XML: {:?}",
        xml.lines
    );
    // Save/close/load preserves both owners; a post-reload numeric write
    // still owns the copy.
    for (tag, command) in [
        ("23", "PROJECT SAVE T131"),
        ("24", "PROJECT CLOSE T131"),
        ("25", "PROJECT LOAD T131"),
        ("26", "PROJECT USE T131"),
    ] {
        let response = s.handle(&format!("[{tag}] {command}"));
        assert_eq!(response.status, 200, "{command}: {response:?}");
    }
    let after_copy = s.handle(&format!("[27] DBGET !{copy_oid}/Value"));
    assert!(after_copy.final_text.ends_with("=98"), "{after_copy:?}");
    let after_src = s.handle(&format!("[28] DBGET !{src_oid}/Value"));
    assert!(after_src.final_text.ends_with("=77"), "{after_src:?}");
    assert_eq!(
        s.handle("[29] DBSETSAFE //T131/254/81/8/4/Value 97").status,
        200
    );
    let reread = s.handle(&format!("[30] DBGET !{copy_oid}/Value"));
    assert!(reread.final_text.ends_with("=97"), "{reread:?}");
    let _drained = s.drain_events();
}

#[test]
fn ordinary_application_copied_netvar_level_keeps_numeric_ownership() {
    // NetVar role under an Application copy: the copied NetVar Level keeps
    // its NetVar identity, numeric SAFE owns it, and invalid tails refuse.
    let mut s = Server::new(AccessLevel::Program);
    assert_eq!(s.handle("[1] PROJECT NEW N131").status, 200);
    assert_eq!(
        s.handle("[2] DBCREATENET 254 Local Cni 127.0.0.1:10001")
            .status,
        200
    );
    assert_eq!(
        s.handle("[3] DBADDSAFE //N131/254 Application 56 Lighting")
            .status,
        301
    );
    assert_eq!(
        s.handle("[4] DBADDSAFE //N131/254/56 NetVar 4 Variable")
            .status,
        301
    );
    let add = s.handle("[5] DBADDSAFE //N131/254/56/4 Level 42 High");
    assert_eq!(add.status, 301, "{add:?}");
    let src_oid = add.final_text.strip_prefix("301 OID=").unwrap().to_string();
    assert_eq!(
        s.handle(&format!("[6] DBSETSAFE !{src_oid}/Value 23"))
            .status,
        200
    );
    let copy = s.handle("[7] DBCOPYSAFE //N131/254/56 //N131/254 57 Copy57");
    assert_eq!(copy.status, 301, "{copy:?}");
    let before = s.handle("[8] DBGET //N131/254/57/4/42/Value");
    assert_eq!(before.status, 342, "{before:?}");
    assert!(before.final_text.ends_with("=23"), "{before:?}");
    let set = s.handle("[9] DBSETSAFE //N131/254/57/4/42/Value 99");
    assert_eq!(set.status, 200, "{set:?}");
    assert_eq!(set.final_text, "200 OK.", "{set:?}");
    let after = s.handle("[10] DBGET //N131/254/57/4/42/Value");
    assert!(after.final_text.ends_with("=99"), "{after:?}");
    let src_stable = s.handle(&format!("[11] DBGET !{src_oid}/Value"));
    assert!(src_stable.final_text.ends_with("=23"), "{src_stable:?}");
    for (tag, command, status) in [
        ("12", "DBSETSAFE //N131/254/57/4/42/Value oops", 400),
        ("13", "DBSET //N131/254/57/4/42/Value oops", 408),
    ] {
        let refused = s.handle(&format!("[{tag}] {command}"));
        assert_eq!(refused.status, status, "{command}: {refused:?}");
    }
    let stable = s.handle("[14] DBGET //N131/254/57/4/42/Value");
    assert!(stable.final_text.ends_with("=99"), "{stable:?}");
    for (tag, command) in [
        ("15", "PROJECT SAVE N131"),
        ("16", "PROJECT CLOSE N131"),
        ("17", "PROJECT LOAD N131"),
        ("18", "PROJECT USE N131"),
    ] {
        let response = s.handle(&format!("[{tag}] {command}"));
        assert_eq!(response.status, 200, "{command}: {response:?}");
    }
    let reloaded = s.handle("[19] DBGET //N131/254/57/4/42/Value");
    assert!(reloaded.final_text.ends_with("=99"), "{reloaded:?}");
    let _drained = s.drain_events();
}
