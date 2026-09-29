//! Replays of `native_cgate_object_authorization_probe.json`: owned C-Gate
//! 3.4.0.2001 with a synthetic PCI, per-object parameter and method levels
//! for the root, project, network, application, group and unit objects.

use super::*;
use crate::object_access::{denial, object_path};

fn capture() -> serde_json::Value {
    let path = concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../testdata/fixtures/native_cgate_object_authorization_probe.json"
    );
    serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap()
}

/// Native paths name the probe's disposable project and simulated unit 4;
/// the Rust fixture carries project HARNESS and database unit 5.
fn local(text: &str) -> String {
    text.replace("//AUTHOBJ", "//HARNESS")
        .replace("/p/4", "/p/5")
}

fn at(level: CgateAccessLevel) -> ClientState {
    ClientState {
        access_level: Some(level),
        ..ClientState::default()
    }
}

#[tokio::test]
async fn object_levels_replay_the_native_role_matrix_before_any_pci_io() {
    let native = capture();
    assert_eq!(
        native["native"]["cgate_jar_sha256"],
        "3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630"
    );
    assert_eq!(native["native"]["cleanup_complete"], true);
    let path = state_path();
    let (pci, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let rows = native["matrix"].as_array().unwrap();
    assert_eq!(rows.len(), 22);
    let mut kinds = std::collections::BTreeSet::new();
    let (mut denied, mut admitted) = (0, 0);
    for row in rows {
        let command = local(row["command"].as_str().unwrap());
        kinds.insert(row["object"].as_str().unwrap().to_string());
        for (level_name, response) in row["responses"].as_object().unwrap() {
            let level = CgateAccessLevel::parse(level_name);
            assert_eq!(
                response["session"][0],
                format!("210 Access level: {level_name}")
            );
            let reply = local(
                response["lines"]
                    .as_array()
                    .unwrap()
                    .last()
                    .unwrap()
                    .as_str()
                    .unwrap(),
            );
            let words: Vec<&str> = command.split_whitespace().collect();
            if reply.starts_with("420 ") {
                denied += 1;
                let mut client = at(level);
                let response = service.handle(&mut client, &format!("[t] {command}")).await;
                assert_eq!(response.final_text, reply, "{command} at {level_name}");
            } else {
                // Native went past authorization. The per-object table must
                // not deny; the handler floor must also admit this role.
                admitted += 1;
                let kind = object_path(words[1]).unwrap().kind;
                assert_eq!(
                    denial(kind, words[0], &words, level),
                    None,
                    "{command} at {level_name}"
                );
                let upper: Vec<String> = words.iter().map(|w| w.to_ascii_uppercase()).collect();
                assert!(command_minimum_for(&upper).is_none_or(|minimum| minimum <= level));
            }
        }
    }
    assert_eq!((denied, admitted), (22, 16));
    assert_eq!(
        kinds.into_iter().collect::<Vec<_>>(),
        [
            "application",
            "cgate",
            "group",
            "network",
            "project",
            "unit"
        ]
    );
    assert!(
        tokio::time::timeout(Duration::from_millis(50), remote.read_u8())
            .await
            .is_err(),
        "per-object denials must precede PCI I/O"
    );
    let _ = std::fs::remove_file(path);
}

/// The largest gap before the table: a writable unit parameter reached its
/// physical SET at Operate. Native requires Program, and SET/DO fail closed
/// for units cmqttd has not seen, including terminal child paths.
#[tokio::test]
async fn unit_address_set_requires_program_before_the_physical_readdress() {
    let path = state_path();
    let (pci, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    for (level, command, expected) in [
        (
            CgateAccessLevel::Operate,
            "SET //HARNESS/254/p/5 Address 40",
            "420 Access denied: //HARNESS/254/p/5 (Insufficient access level for write)",
        ),
        (
            CgateAccessLevel::Admin,
            "SET //HARNESS/254/p/77 Address 40",
            "420 Access denied: //HARNESS/254/p/77 (Insufficient access level for write)",
        ),
        (
            CgateAccessLevel::Admin,
            "SET HARNESS/254/p/5/1 Address 40",
            "420 Access denied: HARNESS/254/p/5/1 (Insufficient access level for write)",
        ),
        (
            CgateAccessLevel::Admin,
            "DO //HARNESS/254/p/5 FactoryDefault",
            "420 Access denied: //HARNESS/254/p/5 (Insufficient access level to run method)",
        ),
        (
            CgateAccessLevel::Admin,
            "DO //HARNESS/254 Unravel",
            "420 Access denied: //HARNESS/254 (Insufficient access level to run method)",
        ),
        (
            CgateAccessLevel::Clipsal,
            "SET //HARNESS/254 TxQ 1",
            "420 Access denied: //HARNESS/254 (Insufficient access level for write)",
        ),
    ] {
        let mut client = at(level);
        let response = service.handle(&mut client, &format!("[t] {command}")).await;
        assert_eq!(response.final_text, expected, "{command}");
    }
    assert!(
        tokio::time::timeout(Duration::from_millis(50), remote.read_u8())
            .await
            .is_err(),
        "denied object operations must not write to the PCI"
    );
    // A GET of an object cmqttd does not hold keeps the handler's reply.
    let mut monitor = at(CgateAccessLevel::Monitor);
    let missing = service
        .handle(&mut monitor, "[t] GET //HARNESS/254/p/77 NetVoltage")
        .await;
    assert!(
        !missing.final_text.starts_with("420"),
        "{}",
        missing.final_text
    );
    // Program admits the SET Retries preparation used by Toolkit workflows.
    let mut operate = at(CgateAccessLevel::Operate);
    assert_eq!(
        service
            .handle(&mut operate, "[t] SET //HARNESS/254 Retries 0")
            .await
            .status,
        200
    );
    let _ = std::fs::remove_file(path);
}

#[test]
fn inventory_counts_and_derived_levels_are_pinned() {
    let path = concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/research/secondary-authorization-inventory.json"
    );
    let inventory: serde_json::Value =
        serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap();
    assert_eq!(
        inventory["counts"],
        serde_json::json!({"implemented": 891, "missing": 1, "not_applicable": 142, "partial": 8})
    );
    assert_eq!(inventory["object_model"].as_array().unwrap().len(), 1014);
    let missing: Vec<&str> = inventory["sites"]
        .as_array()
        .unwrap()
        .iter()
        .chain(inventory["object_model"].as_array().unwrap())
        .filter(|row| row["classification"] == "missing")
        .map(|row| row["id"].as_str().unwrap_or("object-row"))
        .collect();
    assert_eq!(missing, ["help-below-floor"]);
}
