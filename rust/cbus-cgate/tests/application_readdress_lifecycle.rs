//! Issue #125 gap coverage: save/load durability, complete-replacement
//! interplay and rename interaction for SAFE Application readdress.
//!
//! The core numeric/OID remap, conflict and no-op cases live in
//! `application_readdress.rs`; this file pins the surrounding lifecycle the
//! acceptance criteria require.

use cbus_cgate::{AccessLevel, Server};

fn harness() -> (Server, String) {
    let mut s = Server::new(AccessLevel::Program);
    assert_eq!(s.handle("[1] PROJECT NEW SMOVE").status, 200);
    assert_eq!(
        s.handle("[2] DBCREATENET 254 Local Cni 127.0.0.1:10001")
            .status,
        301
    );
    for (address, name) in [(66u8, "A66"), (71u8, "A71")] {
        let added = s.handle(&format!(
            "[a] DBADDSAFE //SMOVE/254 Application {address} {name}"
        ));
        assert_eq!(added.status, 301, "{added:?}");
    }
    assert_eq!(
        s.handle("[g] DBADDSAFE //SMOVE/254/71 Group 7 G7").status,
        301
    );
    let level = s.handle("[l] DBADDSAFE //SMOVE/254/71/7 Level 3 L3");
    assert_eq!(level.status, 301, "{level:?}");
    assert_eq!(
        s.handle("[v] DBSETSAFE //SMOVE/254/71/7/3/Value 77").status,
        200
    );
    let app = s.handle("[o] DBGETXML //SMOVE/254/71");
    assert_eq!(app.status, 200, "{app:?}");
    let oid = app.lines[0]
        .split("<OID>")
        .nth(1)
        .and_then(|rest| rest.split("</OID>").next())
        .expect("application OID in document")
        .to_string();
    (s, oid)
}

#[test]
fn safe_readdress_survives_project_save_close_load_use() {
    let (mut s, oid) = harness();
    assert_eq!(
        s.handle("[m] DBSETSAFE //SMOVE/254/71/Address 70").status,
        200
    );
    // Rename interaction: TagName rename after the move stays on the new path.
    assert_eq!(
        s.handle("[t] DBSETSAFE //SMOVE/254/70/TagName Moved70")
            .status,
        200
    );
    for command in [
        "[s] PROJECT SAVE SMOVE",
        "[c] PROJECT CLOSE SMOVE",
        "[l] PROJECT LOAD SMOVE",
        "[u] PROJECT USE SMOVE",
    ] {
        let response = s.handle(command);
        assert_eq!(response.status, 200, "{command}: {response:?}");
    }
    // New canonical path durable; old path gone; OID identity preserved.
    let app = s.handle("[n] DBGETXML //SMOVE/254/70");
    assert_eq!(app.status, 200, "{app:?}");
    assert!(
        app.lines[0].contains("<Address>70</Address>"),
        "{:?}",
        app.lines
    );
    assert!(
        app.lines[0].contains("<TagName>Moved70</TagName>"),
        "{:?}",
        app.lines
    );
    assert!(
        app.lines[0].contains(&format!("<OID>{oid}</OID>")),
        "{:?}",
        app.lines
    );
    assert_eq!(s.handle("[o] DBGETXML //SMOVE/254/71").status, 401);
    // Descendant and value read back under the moved path.
    let group = s.handle("[g] DBGETXML //SMOVE/254/70/7");
    assert_eq!(group.status, 200, "{group:?}");
    let value = s.handle("[v] DBGET //SMOVE/254/70/7/3/Value");
    assert_eq!(value.status, 342, "{value:?}");
    assert!(value.final_text.ends_with("=77"), "{value:?}");
    let oid_address = s.handle(&format!("[a] DBGET !{oid}/Address"));
    assert_eq!(oid_address.status, 342, "{oid_address:?}");
    assert!(oid_address.final_text.ends_with("=70"), "{oid_address:?}");
    // Untouched sibling keeps its slot.
    let sibling = s.handle("[s] DBGETXML //SMOVE/254/66");
    assert_eq!(sibling.status, 200, "{sibling:?}");
}

#[test]
fn safe_readdress_interplays_with_complete_replacement_and_project_rename() {
    let (mut s, oid) = harness();
    assert_eq!(
        s.handle("[m] DBSETSAFE //SMOVE/254/71/Address 70").status,
        200
    );
    // Complete replacement of the moved Application is accepted at its new
    // canonical path and preserves the moved OID.
    let replacement = format!(
        "<Application><OID>{oid}</OID><TagName>Replaced</TagName><Address>70</Address></Application>"
    );
    let replaced = s.handle_document("[r] DBSETXML //SMOVE/254/70", &replacement);
    assert_eq!(replaced.status, 301, "{replaced:?}");
    let app = s.handle("[n] DBGETXML //SMOVE/254/70");
    assert_eq!(app.status, 200, "{app:?}");
    assert!(
        app.lines[0].contains("<TagName>Replaced</TagName>"),
        "{:?}",
        app.lines
    );
    // Project rename carries the moved canonical path along.
    assert_eq!(s.handle("[p] PROJECT RENAME SMOVE SMOVED").status, 200);
    assert_eq!(s.handle("[u] PROJECT USE SMOVED").status, 200);
    let renamed = s.handle("[q] DBGETXML //SMOVED/254/70");
    assert_eq!(renamed.status, 200, "{renamed:?}");
    assert!(
        renamed.lines[0].contains(&format!("<OID>{oid}</OID>")),
        "{:?}",
        renamed.lines
    );
    assert_eq!(s.handle("[z] DBGETXML //SMOVE/254/70").status, 404);
}

#[test]
fn safe_readdress_conflict_leaves_state_unchanged() {
    let (mut s, _) = harness();
    assert_eq!(
        s.handle("[m] DBSETSAFE //SMOVE/254/71/Address 70").status,
        200
    );
    // Conflicting move is refused and the established path is untouched.
    let conflict = s.handle("[c] DBSETSAFE //SMOVE/254/70/Address 66");
    assert_eq!(conflict.status, 408, "{conflict:?}");
    let app = s.handle("[n] DBGETXML //SMOVE/254/70");
    assert_eq!(app.status, 200, "{app:?}");
    assert!(
        app.lines[0].contains("<Address>70</Address>"),
        "{:?}",
        app.lines
    );
    // Unknown source is refused, never opaquely acknowledged.
    let missing = s.handle("[x] DBSETSAFE //SMOVE/254/79/Address 78");
    assert_eq!(missing.status, 401, "{missing:?}");
    assert_eq!(s.handle("[y] DBGETXML //SMOVE/254/78").status, 401);
    // Non-byte destination is refused before any mutation.
    let bad = s.handle("[b] DBSETSAFE //SMOVE/254/70/Address oops");
    assert_eq!(bad.status, 408, "{bad:?}");
    assert_eq!(s.handle("[w] DBGETXML //SMOVE/254/70").status, 200);
}
