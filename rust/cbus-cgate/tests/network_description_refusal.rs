//! Issue #75: Network DBSETXML carrying Description is refused (owned model).
//!
//! The `cgate-application-description-xml-roundtrip-v1` vector states that
//! NetVar/Level/Network Description elements are refused as unsupported, but
//! only NetVar and Level had vector rows and lib-level pins. This test pins
//! the exact wire refusal for Network and proves the stored project export is
//! byte-identical afterwards. Native C-Gate 3.4.0.2001 placement, order and
//! acceptance remain UNPROVEN; this is owned-model behavior only.

use cbus_cgate::{format_response, AccessLevel, Server};

fn vector() -> serde_json::Value {
    let value: serde_json::Value = serde_json::from_str(include_str!(
        "../../testdata/vectors/cgate_application_description_xml_roundtrip.jsonl"
    ))
    .unwrap();
    assert_eq!(
        value["schema"],
        "cgate-application-description-xml-roundtrip-v1"
    );
    assert_eq!(value["issue"], 75);
    assert_eq!(value["native"], "unproven");
    value
}

fn strip_row(line: &str) -> &str {
    line.strip_prefix("347-").unwrap_or(line)
}

#[test]
fn network_description_dbsetxml_is_refused_without_mutation() {
    let value = vector();
    let row = value["refusals"]
        .as_array()
        .unwrap()
        .iter()
        .find(|row| row["command"] == "DBSETXML Network with Description")
        .unwrap_or_else(|| panic!("Network refusal row missing: {value:?}"));
    assert_eq!(
        row["reply"].as_str().unwrap(),
        "400 DBSETXML Network contains unsupported element Description"
    );

    let mut server = Server::new(AccessLevel::Program);
    for command in ["PROJECT NEW NETDESC", "DBCREATENET 254 Local Cni nowhere"] {
        let response = server.handle(&format!("[seed] {command}"));
        assert_eq!(response.status, 200, "{response:?}");
    }
    let baseline = server.handle("[base] DBGETXML //NETDESC/254");
    assert_eq!(baseline.status, 200, "{baseline:?}");
    // Build the refused document from the live export so every element but
    // the inserted Description is exactly what the server already stores.
    let exported = baseline
        .lines
        .iter()
        .map(|line| strip_row(line))
        .collect::<Vec<_>>()
        .join("\n");
    assert!(exported.contains("</Network>"), "{exported}");
    let document = exported.replacen(
        "</Network>",
        "<Description>unproven network description</Description></Network>",
        1,
    );
    assert_ne!(document, exported);

    let refused = server.handle_document("[net] DBSETXML //NETDESC/254", &document);
    assert_eq!(refused.status, 400, "{refused:?}");
    assert_eq!(
        format_response(&refused),
        "[net] 400 DBSETXML Network contains unsupported element Description\n"
    );

    let after = server.handle("[after] DBGETXML //NETDESC/254");
    assert_eq!(after.status, 200, "{after:?}");
    assert_eq!(
        after.lines, baseline.lines,
        "refused Network Description must not mutate the stored project"
    );
    assert!(
        !after
            .lines
            .join("\n")
            .contains("unproven network description"),
        "{after:?}"
    );
}
