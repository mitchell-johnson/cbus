use cbus_cgate::{AccessLevel, Server};

fn harness() -> Server {
    let mut s = Server::new(AccessLevel::Program);
    assert_eq!(s.handle("[1] PROJECT NEW TMOVE").status, 200);
    assert_eq!(
        s.handle("[2] DBCREATENET 254 Local Cni 127.0.0.1:10001")
            .status,
        200
    );
    assert_eq!(
        s.handle("[3] DBADDSAFE //TMOVE/254 Application 80 App80")
            .status,
        301
    );
    assert_eq!(
        s.handle("[4] DBADDSAFE //TMOVE/254/80 Group 8 Grp8").status,
        301
    );
    let level = s.handle("[5] DBADDSAFE //TMOVE/254/80/8 Level 4 Lvl4");
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
    s
}

#[test]
fn safe_application_readdress_moves_canonical_path_and_descendants() {
    let mut s = harness();
    // Numeric SAFE readdress performs the move.
    let moved = s.handle("[7] DBSETSAFE //TMOVE/254/80/Address 81");
    assert_eq!(moved.status, 200, "{moved:?}");
    let app = s.handle("[8] DBGETXML //TMOVE/254/81");
    assert_eq!(app.status, 200, "{app:?}");
    assert!(
        app.lines[0].contains("<Address>81</Address>"),
        "{:?}",
        app.lines
    );
    assert_eq!(s.handle("[9] DBGETXML //TMOVE/254/80").status, 401);
    // Descendants travel: group and level read back under the new path.
    let group = s.handle("[10] DBGETXML //TMOVE/254/81/8");
    assert_eq!(group.status, 200, "{group:?}");
    let value = s.handle("[11] DBGET //TMOVE/254/81/8/4/Value");
    assert_eq!(value.status, 342, "{value:?}");
    assert!(value.final_text.ends_with("=77"), "{value:?}");
}

#[test]
fn safe_application_readdress_via_oid_and_conflicts() {
    let mut s = harness();
    let app = s.handle("[7] DBGETXML //TMOVE/254/80");
    assert_eq!(app.status, 200, "{app:?}");
    let doc = app.lines[0].clone();
    let oid = doc
        .split("<OID>")
        .nth(1)
        .and_then(|rest| rest.split("</OID>").next())
        .expect("application OID in document")
        .to_string();
    // Issued-OID SAFE readdress performs the same move.
    assert_eq!(
        s.handle(&format!("[8] DBSETSAFE !{oid}/Address 82")).status,
        200
    );
    assert_eq!(s.handle("[9] DBGETXML //TMOVE/254/82").status, 200);
    assert_eq!(s.handle("[10] DBGETXML //TMOVE/254/80").status, 401);
    // Application TagName stays addressable through both selectors (audit).
    assert_eq!(
        s.handle("[11] DBSETSAFE //TMOVE/254/82/TagName Renamed")
            .status,
        200
    );
    assert_eq!(
        s.handle(&format!("[12] DBSETSAFE !{oid}/TagName Renamed2"))
            .status,
        200
    );
    let renamed = s.handle(&format!("[13] DBGET !{oid}/TagName"));
    assert_eq!(renamed.status, 342, "{renamed:?}");
    assert!(renamed.final_text.ends_with("=Renamed2"), "{renamed:?}");
    // Conflicting and no-op addresses.
    assert_eq!(
        s.handle("[14] DBADDSAFE //TMOVE/254 Application 83 Other83")
            .status,
        301
    );
    assert_eq!(
        s.handle("[15] DBSETSAFE //TMOVE/254/82/Address 83").status,
        408
    );
    assert_eq!(s.handle("[16] DBGETXML //TMOVE/254/82").status, 200);
    assert_eq!(
        s.handle("[17] DBSETSAFE //TMOVE/254/82/Address 82").status,
        200
    );
    assert_eq!(s.handle("[18] DBGETXML //TMOVE/254/82").status, 200);
}
