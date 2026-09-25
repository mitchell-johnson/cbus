//! P4a executable service-routing capability matrix for issue #10.
//!
//! Classification only: every maintained C-Gate command path (the 224
//! public-manual headings plus the 268 bytecode registrations, 431 unique
//! paths) classified by how cmqttd's physical `Service::handle` routes it.
//! No backend changes, no dispatch changes, no capability flips.

use cbus_cgate::capability_matrix::{RoutingClass, CAPABILITY_MATRIX, SUPPLEMENT_ROUTING};
use cbus_cgate::manual::{DECOMPILED_COMMAND_GROUPS, DOCUMENTED_COMMANDS};
use std::collections::{BTreeMap, BTreeSet};

/// The inventoried path universe, derived from the same `manual.rs` exports
/// the mock-coverage tests use. A new command without a matrix row fails.
fn inventory_paths() -> BTreeSet<String> {
    let mut names = BTreeSet::new();
    for name in DOCUMENTED_COMMANDS {
        names.insert((*name).to_string());
    }
    for (root, subcommands) in DECOMPILED_COMMAND_GROUPS {
        for subcommand in *subcommands {
            names.insert(format!("{root} {subcommand}"));
        }
    }
    names
}

#[test]
fn matrix_artifact_exists_and_covers_every_inventoried_path_exactly_once() {
    assert!(
        !CAPABILITY_MATRIX.is_empty(),
        "capability matrix artifact must not be empty"
    );
    let inventory = inventory_paths();
    assert_eq!(inventory.len(), 431, "inventory union must stay 431 paths");

    let mut seen = BTreeSet::new();
    let mut extras = Vec::new();
    for entry in CAPABILITY_MATRIX {
        assert!(
            seen.insert(entry.path),
            "duplicate matrix row for path: {}",
            entry.path
        );
        if !inventory.contains(entry.path) {
            extras.push(entry.path);
        }
        assert!(
            !entry.evidence.is_empty(),
            "matrix row must show its work: {}",
            entry.path
        );
    }
    assert!(
        extras.is_empty(),
        "matrix rows outside the inventory: {extras:?}"
    );

    let matrix_paths: BTreeSet<&str> = CAPABILITY_MATRIX.iter().map(|entry| entry.path).collect();
    let missing: Vec<&String> = inventory
        .iter()
        .filter(|path| !matrix_paths.contains(path.as_str()))
        .collect();
    assert!(
        missing.is_empty(),
        "inventoried paths without a matrix row: {missing:?}"
    );
    assert_eq!(CAPABILITY_MATRIX.len(), 431);
}

#[test]
fn matrix_class_counts_pin_the_routing_gap() {
    let mut counts: BTreeMap<RoutingClass, usize> = BTreeMap::new();
    for entry in CAPABILITY_MATRIX {
        *counts.entry(entry.class).or_default() += 1;
    }
    let class_count = |class: RoutingClass| counts.get(&class).copied().unwrap_or(0);
    // Pinned 2026-09-25 after remediation: NET LIST + NET LIST_ALL moved
    // fail_closed_502 -> local_database (admitted by local_command, served
    // by the model with no PCI I/O); ENABLE REMOVE moved physical ->
    // local_database (model response, no PCI I/O); GETSTATE moved physical
    // -> local_database (observed-cache read, no per-read PCI I/O).
    // NET UNRAVELUNIT moved fail_closed_502 -> physical after the bounded
    // duplicate-address-255 MATCHDB backend was added; unsupported shapes
    // remain an explicit 502 within that service branch.
    assert_eq!(class_count(RoutingClass::Physical), 30);
    assert_eq!(class_count(RoutingClass::LocalDatabase), 36);
    assert_eq!(class_count(RoutingClass::FailClosed502), 364);
    assert_eq!(class_count(RoutingClass::Obsolete400), 1);
    // Rejected4xx is empty by construction today (arity-gated 4xx readings
    // share paths with other classes); the emptiness itself is pinned here
    // so drift is caught.
    assert_eq!(class_count(RoutingClass::Rejected4xx), 0);
    let total: usize = counts.values().sum();
    assert_eq!(total, 431);
}

#[test]
fn fail_closed_pins_do_unravel_and_whole_network_unravel() {
    let fail_closed: BTreeSet<&str> = CAPABILITY_MATRIX
        .iter()
        .filter(|entry| entry.class == RoutingClass::FailClosed502)
        .map(|entry| entry.path)
        .collect();
    // "DO UNRAVEL" is a method specialization of the inventoried "DO" path
    // (not a separate inventoried path): the DO row carries the explicit
    // 502 evidence for the UNRAVEL method.
    for pinned in ["DO", "NET UNRAVEL"] {
        assert!(
            fail_closed.contains(pinned),
            "fail_closed must contain {pinned}"
        );
    }
    let do_row = CAPABILITY_MATRIX
        .iter()
        .find(|entry| entry.path == "DO")
        .expect("DO row exists");
    assert!(
        do_row.evidence.contains("DO UNRAVEL"),
        "DO row must pin the UNRAVEL 502 evidence"
    );
    let unit_row = CAPABILITY_MATRIX
        .iter()
        .find(|entry| entry.path == "NET UNRAVELUNIT")
        .expect("NET UNRAVELUNIT row exists");
    assert_eq!(unit_row.class, RoutingClass::Physical);
    assert!(unit_row.evidence.contains("255 MATCHDB"));
}

#[test]
fn obsolete_pins_net_check_unravel() {
    let obsolete: BTreeSet<&str> = CAPABILITY_MATRIX
        .iter()
        .filter(|entry| entry.class == RoutingClass::Obsolete400)
        .map(|entry| entry.path)
        .collect();
    assert_eq!(obsolete, BTreeSet::from(["NET CHECK_UNRAVEL"]));
}

#[test]
fn supplement_pins_non_inventoried_service_commands() {
    // Inventory-relative bound: CAPABILITY_MATRIX covers exactly the manual
    // inventory universe (431 rows, asserted above). The supplement below
    // is the explicit, separately-asserted list of known service commands
    // handled by Service::handle that have no inventoried path — not a
    // second inventory. Each arm was verified to exist in handle()
    // dispatch; drop any entry whose arm disappears rather than rehome it.
    let supplement: BTreeMap<&str, RoutingClass> = SUPPLEMENT_ROUTING
        .iter()
        .map(|entry| (entry.path, entry.class))
        .collect();
    assert_eq!(supplement.len(), 6, "supplement list must stay 6 entries");
    assert_eq!(
        supplement.get("CMQTT CAPABILITIES"),
        Some(&RoutingClass::LocalDatabase)
    );
    assert_eq!(
        supplement.get("CMQTT LABELS"),
        Some(&RoutingClass::LocalDatabase)
    );
    assert_eq!(
        supplement.get("UNIT READMEM"),
        Some(&RoutingClass::Physical)
    );
    assert_eq!(
        supplement.get("UNIT IDENTIFY"),
        Some(&RoutingClass::Physical)
    );
    assert_eq!(
        supplement.get("TRIGGER INDICATORKILL"),
        Some(&RoutingClass::Physical)
    );
    assert_eq!(
        supplement.get("LIGHTING STOP"),
        Some(&RoutingClass::Physical)
    );
    for entry in SUPPLEMENT_ROUTING {
        assert!(
            !entry.evidence.is_empty(),
            "supplement row must show its work: {}",
            entry.path
        );
    }
    // Supplement paths must not overlap the inventoried universe.
    let inventory = inventory_paths();
    for entry in SUPPLEMENT_ROUTING {
        assert!(
            !inventory.contains(entry.path),
            "supplement path must stay outside the inventory: {}",
            entry.path
        );
    }
}
