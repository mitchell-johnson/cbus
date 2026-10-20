use cbus_cgate::{AccessLevel, Server};

fn seed() -> (Server, String) {
    let mut s = Server::new(AccessLevel::Program);
    assert_eq!(s.handle("[1] PROJECT NEW TCOPY").status, 200);
    assert_eq!(
        s.handle("[2] DBCREATENET 254 Local Cni 127.0.0.1:10001")
            .status,
        200
    );
    assert_eq!(
        s.handle("[3] DBADDSAFE //TCOPY/254 Application 70 Src70")
            .status,
        301
    );
    assert_eq!(
        s.handle("[4] DBADDSAFE //TCOPY/254/70 Group 5 Grp5").status,
        301
    );
    let level = s.handle("[5] DBADDSAFE //TCOPY/254/70/5 Level 3 Lvl3");
    assert_eq!(level.status, 301, "{level:?}");
    let level_oid = level
        .final_text
        .strip_prefix("301 OID=")
        .unwrap()
        .to_string();
    assert_eq!(
        s.handle(&format!("[6] DBSETSAFE !{level_oid}/Value 42"))
            .status,
        200
    );
    assert_eq!(
        s.handle("[7] DBSETSAFE //TCOPY/254/70/Description Copied description")
            .status,
        200
    );
    (s, level_oid)
}

#[test]
fn numeric_application_copy_duplicates_complete_subtree() {
    let (mut s, src_level_oid) = seed();
    // Destination conflict refuses before mutation.
    assert_eq!(
        s.handle("[8] DBADDSAFE //TCOPY/254 Application 71 Other71")
            .status,
        301
    );
    assert_eq!(
        s.handle("[9] DBCOPYSAFE //TCOPY/254/70 //TCOPY/254 71 Clash71")
            .status,
        409
    );
    // The real copy answers the 301 OID flow.
    let copied = s.handle("[11] DBCOPYSAFE //TCOPY/254/70 //TCOPY/254 72 Copy70");
    assert_eq!(copied.status, 301, "{copied:?}");
    let app_oid = copied
        .final_text
        .strip_prefix("301 OID=")
        .unwrap()
        .to_string();
    assert_ne!(app_oid, src_level_oid);
    // Source tree is unchanged.
    let source = s.handle("[12] DBGETXML //TCOPY/254/70");
    assert_eq!(source.status, 200, "{source:?}");
    assert!(
        source.lines[0].contains("<Address>70</Address>"),
        "{:?}",
        source.lines
    );
    assert!(
        source.lines[0].contains("<TagName>Src70</TagName>"),
        "{:?}",
        source.lines
    );
    // Destination carries the same groups, levels, values and description
    // under fresh identities.
    let dest = s.handle("[13] DBGETXML //TCOPY/254/72");
    assert_eq!(dest.status, 200, "{dest:?}");
    assert!(
        dest.lines[0].contains("<Address>72</Address>"),
        "{:?}",
        dest.lines
    );
    assert!(
        dest.lines[0].contains("<TagName>Copy70</TagName>"),
        "{:?}",
        dest.lines
    );
    assert!(
        dest.lines[0].contains("<TagName>Grp5</TagName>"),
        "{:?}",
        dest.lines
    );
    assert!(
        dest.lines[0].contains("<TagName>Lvl3</TagName>"),
        "{:?}",
        dest.lines
    );
    assert!(dest.lines[0].contains("Value=\"42\""), "{:?}", dest.lines);
    assert!(!dest.lines[0].contains(&src_level_oid), "{:?}", dest.lines);
    let desc = s.handle(&format!("[14] DBGET !{app_oid}/Description"));
    assert_eq!(desc.status, 342, "{desc:?}");
    assert!(desc.final_text.ends_with("=Copied description"), "{desc:?}");
    // The copied level is an independent owner with the same value.
    let value = s.handle("[15] DBGET //TCOPY/254/72/5/3/Value");
    assert_eq!(value.status, 342, "{value:?}");
    assert!(value.final_text.ends_with("=42"), "{value:?}");
    // Mutating the copy leaves the source alone (graph isolation).
    assert_eq!(
        s.handle("[16] DBSETSAFE //TCOPY/254/72/5/3/Value 43")
            .status,
        200
    );
    let src_value = s.handle(&format!("[17] DBGET !{src_level_oid}/Value"));
    assert!(src_value.final_text.ends_with("=42"), "{src_value:?}");
    // The copy survives save/close/load.
    assert_eq!(s.handle("[18] PROJECT SAVE").status, 200);
    assert_eq!(s.handle("[19] PROJECT CLOSE").status, 200);
    assert_eq!(s.handle("[20] PROJECT LOAD TCOPY").status, 200);
    let reloaded = s.handle("[21] DBGETXML //TCOPY/254/72");
    assert_eq!(reloaded.status, 200, "{reloaded:?}");
    assert!(
        reloaded.lines[0].contains("Value=\"43\""),
        "{:?}",
        reloaded.lines
    );
    let resrc = s.handle("[22] DBGETXML //TCOPY/254/70");
    assert_eq!(resrc.status, 200, "{resrc:?}");
}
