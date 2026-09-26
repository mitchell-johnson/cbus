//! P4a executable service-routing capability matrix for issue #10.
//!
//! Classification only: every maintained C-Gate command path (the 224
//! public-manual headings plus the 268 bytecode registrations, 431 unique
//! paths) classified by how cmqttd's physical `Service::handle` routes it.
//! Backend changes update the corresponding row and pinned class counts in the
//! same commit, so the executable ledger cannot drift from service routing.

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
    // remain an explicit 502 within that service branch. NET SYNCNEW moved
    // fail_closed_502 -> physical with five-pass MMI and native duplicate
    // challenges for its targeted and general forms. NET
    // SET_PROJECT_IDENTIFY moved fail_closed_502 -> physical with a verified
    // parameter-35 write to the first non-error state-one-or-two unit that
    // yields exactly one valid known serial during the bounded observation window.
    // EVENT, QUIT, SESSION_ID, SESSION_ID ALL, and SESSION_ID TAG are now
    // native-shaped per-connection operations in the real cmqttd endpoint.
    // PP RESET_TO_DEFAULTS is locally staged when an exact unit
    // specification is installed; it performs no bus I/O or database write.
    // LABEL KFIGET and KFISET moved fail_closed_502 -> physical with their
    // native confirmed CAL sequences and source-correlated responses. LABEL
    // CLEAR moved fail_closed_502 -> physical with its native exact-once,
    // confirmation-only all-key and one-key CAL forms.
    // AIRCON root help moved fail_closed_502 -> local_database, and all 11
    // maintained AIRCON commands moved fail_closed_502 -> physical with exact
    // native 3.4 SAL encoding and correlated PCI confirmation.
    // SECURITY root help moved fail_closed_502 -> local_database, and all
    // seven maintained SECURITY commands moved fail_closed_502 -> physical
    // with exact native 3.4 SAL encoding and correlated PCI confirmation.
    // AUDIO root help moved fail_closed_502 -> local_database, and all 19
    // maintained AUDIO commands moved fail_closed_502 -> physical with exact
    // retained 3.4 SAL encoding and active-generation PCI confirmation.
    // MEASUREMENT root help moved fail_closed_502 -> local_database, and DATA
    // moved fail_closed_502 -> physical with exact native 3.4 SAL encoding,
    // active-generation PCI confirmation, and dynamic GET state.
    // MEDIATRANSPORT root help moved fail_closed_502 -> local_database, and
    // all 21 maintained commands/reports moved fail_closed_502 -> physical
    // with exact native 3.4 SAL encoding and correlated PCI confirmation.
    // TELEPHONY root help moved fail_closed_502 -> local_database, and all
    // five maintained TELEPHONY commands moved fail_closed_502 -> physical
    // with exact native 3.4 SAL encoding and active-generation confirmation.
    // PROJECT ARCHIVE/RESTORE/RENAME/COPY/DELETE and REPOSITORY LIST moved
    // fail_closed_502 -> local_database with durable internal snapshots,
    // guarded secondary-project lifecycle, and a read-only cmqttd-json row.
    // DBNETWORKPATH moved fail_closed_502 -> local_database with native 136
    // COMPACT and 137 OID topology resolution and no PCI traffic.
    // All nine maintained CONFIG paths moved fail_closed_502 ->
    // local_database with the retained native catalogue, scoped durable
    // values and bounded cmqttd-json LOAD/SAVE snapshots.
    // All seven maintained FILE paths moved fail_closed_502 ->
    // local_database with retained native base64, digest, directory and
    // replacement-backup semantics over the sandboxed durable virtual root.
    // All five maintained ACCESS paths plus LOGIN and LOGOUT moved
    // fail_closed_502 -> local_database with retained native grammar, role
    // filtering and session authentication over digest-only credentials and
    // sandboxed snapshots.
    // The eleven maintained AIRCON commands and NET PROJECT_IDENTIFY moved
    // fail_closed_502 -> physical. PROJECT_IDENTIFY uses the selected shared
    // interface's native read-only MMI/parameter-35 workflow.
    // The complete maintained PORT family moved seven paths out of the
    // generic 502: root help, local serial/interface enumeration and native
    // REFRESH behavior are local; both discovery protocols and PROBE use
    // explicit physical network/port I/O.
    // All 128 retained DALI paths are now routed: 103 physical leaves, six
    // local help roots and nineteen local catalogue/session/database leaves.
    // Typed DALI_ONLY/FULL session plans retain a narrower fail-before-I/O
    // selector boundary, while the evidenced EXT_ONLY path is physical.
    // Eleven local/session administration paths moved fail_closed_502 ->
    // local_database: PROJECT root/DIRFULL, DBGETJSON root and three NAC
    // projections, EVENT_CHANNEL LIST/SUB/UNSUB, and advisory LOCK/UNLOCK.
    // Thirteen PP administrative/catalogue/session-memory paths and seven
    // PROGRAMMER queue-metadata paths moved fail_closed_502 -> local_database.
    // PP WRITE_PATCH and PROGRAMMER TRIGGER START remain fail-closed physical
    // execution boundaries.
    // DEPLOY_QUEUE DELETE, DELETE_ALL and LIST moved fail_closed_502 ->
    // local_database over the volatile PROGRAMMER task-group queue. ADD stays
    // conservatively fail-closed because only its empty/all-cancelled no-op
    // form is local, while any executable instruction refuses before
    // mutation. RETRY remains fail-closed because it would re-execute work.
    // NET lifecycle adds two exact physical paths, nine local catalogue/help
    // paths and one native-obsolete path, moving twelve rows out of 502.
    // Nine retained family-help roots move fail_closed_502 -> local_database.
    // Seven maintained application leaves moved fail_closed_502 -> physical:
    // IDENTIFY ON/OFF/RAMP/TERMINATERAMP, SHORTMESSAGE REFRESH/SEND, and
    // EREPORT MESSAGE. Root help rows retain their independently evidenced
    // local classification boundary.
    // Legacy DBRENAMENET/DBRENAMENETSAFE, DBSET and DBTAGLIST move four
    // rows to local_database with selected-project persistence and explicit
    // repairs for native duplicate/non-numeric address corruption. DBADD,
    // DBCOPY, DBCREATE, DBNEW, DBUPDATE and DBVERIFY remain fail-closed.
    // APPLICATIONS GET_CATALOG, CALCULATOR TEST, CGL IMPORT and CGL EXPORT
    // move fail_closed_502 -> local_database with bounded operator catalogue
    // inputs and durable label-only CGL 1.1 semantics.
    // Ten general/object paths move fail_closed_502 -> local_database: both
    // native comment spellings, OID, BROADCAST_EVENT, SHOW, REPORT, all three
    // TREE renderings and durable NEW object creation.
    assert_eq!(class_count(RoutingClass::Physical), 215);
    assert_eq!(class_count(RoutingClass::LocalDatabase), 177);
    assert_eq!(class_count(RoutingClass::FailClosed502), 37);
    assert_eq!(class_count(RoutingClass::Obsolete400), 2);
    // Rejected4xx is empty by construction today (arity-gated 4xx readings
    // share paths with other classes); the emptiness itself is pinned here
    // so drift is caught.
    assert_eq!(class_count(RoutingClass::Rejected4xx), 0);
    let total: usize = counts.values().sum();
    assert_eq!(total, 431);
}

#[test]
fn general_object_and_tree_rows_retain_native_evidence() {
    let fixture: serde_json::Value = serde_json::from_str(include_str!(
        "../../testdata/fixtures/native_cgate_general_tree.json"
    ))
    .expect("native general/tree evidence must remain valid JSON");
    assert_eq!(fixture["oracle"]["version"], "3.4.0");
    assert_eq!(fixture["oracle"]["build"], 2001);
    assert_eq!(
        fixture["oracle"]["jar_sha256"],
        "3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630"
    );
    assert_eq!(fixture["oracle"]["site_project_used"], false);
    assert_eq!(fixture["oracle"]["real_cbus_contacted"], false);
    for path in [
        "#",
        "//",
        "BROADCAST_EVENT",
        "NEW",
        "OID",
        "REPORT",
        "SHOW",
        "TREE",
        "TREEXML",
        "TREEXMLDETAIL",
    ] {
        let entry = CAPABILITY_MATRIX
            .iter()
            .find(|entry| entry.path == path)
            .unwrap_or_else(|| panic!("missing {path}"));
        assert_eq!(entry.class, RoutingClass::LocalDatabase, "{path}");
        assert!(
            entry.evidence.contains("native") || matches!(path, "#" | "//"),
            "{path} must retain native evidence"
        );
    }
}

#[test]
fn remaining_application_rows_retain_native_wire_and_repair_evidence() {
    let fixture: serde_json::Value = serde_json::from_str(include_str!(
        "../../testdata/fixtures/native_cgate_remaining_applications.json"
    ))
    .expect("remaining application evidence must remain valid JSON");
    let flags: serde_json::Value = serde_json::from_str(include_str!(
        "../../testdata/fixtures/native_cgate_shortmessage_flags.json"
    ))
    .expect("Short Message flag evidence must remain valid JSON");
    assert_eq!(fixture["oracle"]["version"], "3.4.0.2001");
    assert_eq!(fixture["identify"]["application"], 251);
    assert_eq!(fixture["shortmessage"]["application"], 173);
    assert_eq!(fixture["ereport"]["application"], 206);
    assert_eq!(flags["coherent_inbound"][3]["sal_hex"], "872BD11234564142");
    for path in [
        "IDENTIFY OFF",
        "IDENTIFY ON",
        "IDENTIFY RAMP",
        "IDENTIFY TERMINATERAMP",
        "SHORTMESSAGE REFRESH",
        "SHORTMESSAGE SEND",
        "EREPORT MESSAGE",
    ] {
        let entry = CAPABILITY_MATRIX
            .iter()
            .find(|entry| entry.path == path)
            .unwrap_or_else(|| panic!("missing {path}"));
        assert_eq!(entry.class, RoutingClass::Physical, "{path}");
        assert!(entry.evidence.contains("native_cgate_"), "{path}");
    }
    let send = CAPABILITY_MATRIX
        .iter()
        .find(|entry| entry.path == "SHORTMESSAGE SEND")
        .unwrap();
    assert!(send.evidence.contains("repairs native 3.4"));
    assert!(send.evidence.contains("without replay"));
}

#[test]
fn legacy_database_rows_pin_local_and_fail_closed_boundaries() {
    let fixture: serde_json::Value = serde_json::from_str(include_str!(
        "../../testdata/fixtures/native_cgate_legacy_database.json"
    ))
    .expect("native legacy-database evidence must remain valid JSON");
    assert_eq!(fixture["oracle"]["version"], "3.4.0 build 2001");
    assert_eq!(
        fixture["oracle"]["jar_sha256"],
        "3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630"
    );

    for path in ["DBRENAMENET", "DBRENAMENETSAFE", "DBSET", "DBTAGLIST"] {
        let row = CAPABILITY_MATRIX
            .iter()
            .find(|row| row.path == path)
            .unwrap_or_else(|| panic!("missing {path}"));
        assert_eq!(row.class, RoutingClass::LocalDatabase, "{path}");
        assert!(
            row.evidence.contains("native_cgate_legacy_database.json"),
            "{path}"
        );
    }
    for path in [
        "DBADD", "DBCOPY", "DBCREATE", "DBNEW", "DBUPDATE", "DBVERIFY",
    ] {
        let row = CAPABILITY_MATRIX
            .iter()
            .find(|row| row.path == path)
            .unwrap_or_else(|| panic!("missing {path}"));
        assert_eq!(row.class, RoutingClass::FailClosed502, "{path}");
        assert!(
            row.evidence.contains("native_cgate_legacy_database.json"),
            "{path}"
        );
    }
}

#[test]
fn pp_administration_and_programmer_queue_retain_native_evidence_and_boundaries() {
    let fixture: serde_json::Value = serde_json::from_str(include_str!(
        "../../testdata/fixtures/native_cgate_pp_programmer.json"
    ))
    .expect("native PP/PROGRAMMER evidence must remain valid JSON");
    assert_eq!(fixture["oracle"]["version"], "3.4.0.2001");
    assert_eq!(
        fixture["oracle"]["jar_sha256"],
        "3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630"
    );
    assert_eq!(
        fixture["native_shapes"]["raw_after_set"],
        "316 RawData=0102030400000000"
    );
    assert_eq!(fixture["native_shapes"]["test_duration_seconds"], 3);
    assert_eq!(
        fixture["cmqttd_boundaries"]["programmer_start"],
        "502; executing queued PP/DALI instructions needs an evidenced physical scheduler and is never simulated."
    );

    for path in [
        "PP CANCEL_LOCK",
        "PP CATALOG_INFO",
        "PP DEBUG",
        "PP GET_RAW_DATA",
        "PP GET_UNIT_CATALOG",
        "PP GET_UNIT_SPEC",
        "PP LIST_CATALOG_NUMBERS",
        "PP LIST_LOCK",
        "PP LOAD_FROM_FILE",
        "PP PATCH_VERSION",
        "PP RELOAD_CATALOG",
        "PP SET_RAW_DATA",
        "PP UNITS",
        "PROGRAMMER ADD_INSTRUCTION",
        "PROGRAMMER CANCEL_INSTRUCTION",
        "PROGRAMMER CREATE",
        "PROGRAMMER DELETE",
        "PROGRAMMER LIST",
        "PROGRAMMER STATUS",
        "PROGRAMMER TEST",
    ] {
        let entry = CAPABILITY_MATRIX
            .iter()
            .find(|entry| entry.path == path)
            .unwrap_or_else(|| panic!("missing {path}"));
        assert_eq!(entry.class, RoutingClass::LocalDatabase, "{path}");
        assert!(
            entry.evidence.contains("native_cgate_pp_programmer.json"),
            "{path}"
        );
    }
    for path in ["PP WRITE_PATCH", "PROGRAMMER TRIGGER"] {
        let entry = CAPABILITY_MATRIX
            .iter()
            .find(|entry| entry.path == path)
            .unwrap_or_else(|| panic!("missing {path}"));
        assert_eq!(entry.class, RoutingClass::FailClosed502, "{path}");
        assert!(
            entry.evidence.contains("never") || entry.evidence.contains("physical"),
            "{path}"
        );
    }
}

#[test]
fn deploy_queue_retains_native_evidence_and_execution_boundaries() {
    let fixture: serde_json::Value = serde_json::from_str(include_str!(
        "../../testdata/fixtures/native_cgate_deploy_queue.json"
    ))
    .expect("native DEPLOY_QUEUE evidence must remain valid JSON");
    assert_eq!(fixture["oracle"]["version"], "3.4.0.2001");
    assert_eq!(
        fixture["oracle"]["jar_sha256"],
        "3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630"
    );
    assert_eq!(
        fixture["owned_bytecode"]["registered_handlers"]["ADD"],
        "kd"
    );
    assert_eq!(
        fixture["native_shapes"]["task_group_summary_field_order"],
        serde_json::json!([
            "progName",
            "progState",
            "taskName",
            "taskRoute",
            "createdTime",
            "startedTime",
            "endedTime",
            "remainingSeconds"
        ])
    );
    assert_eq!(
        fixture["event_envelopes"]["subscription_independent_of_EVENT_mode"],
        true
    );
    assert_eq!(
        fixture["cmqttd_boundaries"]["RETRY"],
        "Always 502 after native identity/state validation because retry reinitializes and re-executes work; queue and events remain unchanged."
    );
}

#[test]
fn access_rows_retain_native_roles_persistence_and_safety_repair_evidence() {
    let fixture: serde_json::Value = serde_json::from_str(include_str!(
        "../../testdata/fixtures/native_cgate_access.json"
    ))
    .expect("native ACCESS evidence must remain valid JSON");
    assert_eq!(fixture["oracle"]["version"], "3.4.0.2001");
    assert_eq!(
        fixture["oracle"]["jar_sha256"],
        "3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630"
    );
    assert_eq!(fixture["inventory"]["count"], 5);
    assert_eq!(fixture["inventory"]["effective_family_minimum"], "Clipsal");
    assert_eq!(
        fixture["native_defects_and_unsafe_edges"]["unresolved_add"]["row_was_still_inserted"],
        true
    );
    assert_eq!(
        fixture["cmqttd_safety_boundary"]["passwords"],
        "one-way digest at rest; ACCESS LIST renders <redacted>"
    );
    for entry in CAPABILITY_MATRIX.iter().filter(|entry| {
        entry.path.starts_with("ACCESS ") || matches!(entry.path, "LOGIN" | "LOGOUT")
    }) {
        assert_eq!(entry.class, RoutingClass::LocalDatabase, "{}", entry.path);
        assert!(
            entry.evidence.contains("native_cgate_access.json"),
            "{}",
            entry.path
        );
    }
}

#[test]
fn local_admin_rows_retain_native_oracle_and_boundary_evidence() {
    let fixture: serde_json::Value = serde_json::from_str(include_str!(
        "../../testdata/fixtures/native_cgate_local_admin.json"
    ))
    .expect("native local-admin evidence must remain valid JSON");
    assert_eq!(fixture["oracle"]["version"], "3.4.0 build 2001");
    assert_eq!(
        fixture["oracle"]["jar_sha256"],
        "3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630"
    );
    assert_eq!(fixture["oracle"]["live_cbus_endpoint"], false);
    assert_eq!(fixture["oracle"]["cleanup_complete"], true);
    assert_eq!(fixture["project"]["help"].as_array().unwrap().len(), 18);
    assert_eq!(
        fixture["project"]["dirfull_saved_project"],
        "123 project=\"TEST\" desc=\"TEST\""
    );
    assert_eq!(
        fixture["dbgetjson"]["nac_objects_list_without_definition"],
        serde_json::json!(["346 []"])
    );
    assert_eq!(
        fixture["dbgetjson"]["nac_routing_table_without_definition"],
        serde_json::json!(["345-Begin of JSON", "346-[]", "347 End of JSON"])
    );
    assert_eq!(
        fixture["event_channel"]["list"].as_array().unwrap().len(),
        5
    );
    assert_eq!(
        fixture["event_channel"]["sub_repeat"],
        "201 Service ready: already subscribed"
    );
    assert_eq!(
        fixture["advisory_locks"]["decompiled_responses"]["unlock_failed"],
        "426 <object-signature>: Unlock failed."
    );
    assert!(fixture["advisory_locks"]["runtime_probe_boundary"]
        .as_str()
        .unwrap()
        .contains("401 Network not found"));
}

#[test]
fn dali_rows_retain_native_help_wire_and_specialized_routing() {
    let fixture: serde_json::Value = serde_json::from_str(include_str!(
        "../../testdata/fixtures/native_cgate_dali_help.json"
    ))
    .expect("native DALI evidence must remain valid JSON");
    assert_eq!(fixture["format"], "native-cgate-dali-help-v1");
    assert_eq!(fixture["oracle"]["version"], "3.4.0.2001");
    assert_eq!(
        fixture["oracle"]["jar_sha256"],
        "3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630"
    );
    assert_eq!(fixture["oracle"]["listener_ownership_verified"], true);
    assert_eq!(fixture["paths"].as_object().unwrap().len(), 128);

    let dali_rows: Vec<_> = CAPABILITY_MATRIX
        .iter()
        .filter(|entry| entry.path.starts_with("DALI "))
        .collect();
    assert_eq!(dali_rows.len(), 128);
    assert_eq!(
        dali_rows
            .iter()
            .filter(|entry| entry.class == RoutingClass::Physical)
            .count(),
        103
    );
    assert_eq!(
        dali_rows
            .iter()
            .filter(|entry| entry.class == RoutingClass::LocalDatabase)
            .count(),
        25
    );
    assert_eq!(
        dali_rows
            .iter()
            .filter(|entry| entry.class == RoutingClass::FailClosed502)
            .count(),
        0
    );

    for root in [
        "DALI CATALOG",
        "DALI EMERGENCY",
        "DALI ERROR_REPORTING",
        "DALI GATEWAY",
        "DALI MEASUREMENT",
        "DALI SESSION",
    ] {
        let entry = CAPABILITY_MATRIX
            .iter()
            .find(|entry| entry.path == root)
            .unwrap();
        assert_eq!(entry.class, RoutingClass::LocalDatabase, "{root}");
        assert!(entry.evidence.contains("native_cgate_dali_help.json"));
    }

    for path in [
        "DALI ADDRESS_UNKNOWN",
        "DALI EMERGENCY REST",
        "DALI FACTORY_RESET",
        "DALI WINK_ECG_ON",
    ] {
        let entry = CAPABILITY_MATRIX
            .iter()
            .find(|entry| entry.path == path)
            .unwrap();
        assert_eq!(entry.class, RoutingClass::Physical, "{path}");
        assert!(entry.evidence.contains("PciClient::dali_command"));
    }

    for path in [
        "DALI CATALOG LIST",
        "DALI GATEWAY LIST",
        "DALI SESSION LIST",
    ] {
        let entry = CAPABILITY_MATRIX
            .iter()
            .find(|entry| entry.path == path)
            .unwrap();
        assert_eq!(entry.class, RoutingClass::LocalDatabase, "{path}");
    }
    for path in [
        "DALI ERROR_REPORTING MODE",
        "DALI MEASUREMENT LAMP_RUNNING_TIME",
        "DALI SESSION EXTRACT",
    ] {
        let entry = CAPABILITY_MATRIX
            .iter()
            .find(|entry| entry.path == path)
            .unwrap();
        assert_eq!(entry.class, RoutingClass::Physical, "{path}");
    }
}

#[test]
fn file_rows_retain_native_binary_directory_and_backup_evidence() {
    let fixture: serde_json::Value = serde_json::from_str(include_str!(
        "../../testdata/fixtures/native_cgate_file.json"
    ))
    .expect("native FILE evidence must remain valid JSON");
    assert_eq!(fixture["oracle"]["version"], "3.4.0.2001");
    assert_eq!(
        fixture["oracle"]["jar_sha256"],
        "3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630"
    );
    assert_eq!(fixture["inventory"]["count"], 7);
    assert_eq!(fixture["round_trip"]["base64_line_width"], 76);
    assert_eq!(
        fixture["replacement"]["behavior"],
        "existing target is renamed to target.0 before the new decoded payload is promoted; an older target.0 is deleted"
    );
    assert_eq!(fixture["cmqttd_boundary"]["host_filesystem"], false);
    for entry in CAPABILITY_MATRIX
        .iter()
        .filter(|entry| entry.path.starts_with("FILE "))
    {
        assert_eq!(entry.class, RoutingClass::LocalDatabase, "{}", entry.path);
        assert!(
            entry.evidence.contains("native_cgate_file.json"),
            "{}",
            entry.path
        );
    }
}

#[test]
fn config_rows_retain_native_catalog_scope_and_liveness_repair_evidence() {
    let fixture: serde_json::Value = serde_json::from_str(include_str!(
        "../../testdata/fixtures/native_cgate_config.json"
    ))
    .expect("native CONFIG evidence must remain valid JSON");
    assert_eq!(fixture["oracle"]["version"], "3.4.0 build 2001");
    assert_eq!(
        fixture["oracle"]["jar_sha256"],
        "3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630"
    );
    assert_eq!(fixture["inventory"]["catalog_entries"], 148);
    assert_eq!(fixture["inventory"]["info_entries"], 142);
    assert_eq!(fixture["inventory"]["get_all_entries"], 122);
    assert!(
        fixture["observed_native_defects"]["obget_unknown_or_wrong_scope"]
            .as_str()
            .unwrap()
            .contains("sends no response")
    );
    for entry in CAPABILITY_MATRIX
        .iter()
        .filter(|entry| entry.path == "CONFIG" || entry.path.starts_with("CONFIG "))
    {
        assert_eq!(entry.class, RoutingClass::LocalDatabase, "{}", entry.path);
        assert!(
            entry.evidence.contains("native_cgate_config.json")
                || entry.evidence.contains("Service::config"),
            "{}",
            entry.path
        );
    }
}

#[test]
fn port_rows_retain_native_discovery_and_probe_evidence() {
    let fixture: serde_json::Value = serde_json::from_str(include_str!(
        "../../testdata/fixtures/native_cgate_port.json"
    ))
    .expect("native PORT evidence must remain valid JSON");
    assert_eq!(fixture["oracle"]["version"], "3.4.0 build 2001");
    assert_eq!(
        fixture["oracle"]["jar_sha256"],
        "3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630"
    );
    assert_eq!(fixture["commands"].as_array().unwrap().len(), 7);
    assert_eq!(fixture["legacy_discovery"]["query_hex"], "000000f8");
    assert_eq!(
        fixture["cni2_discovery"]["udp_source_and_destination_port"],
        20050
    );
    assert!(fixture["cni2_discovery"]["synthetic_native_response"]
        .as_str()
        .unwrap()
        .contains("serial=00100700.3526"));
    assert!(fixture["probe"]["wire"].as_str().unwrap().contains("@2104"));
    assert_eq!(fixture["etherlite"]["tcp_port"], 10001);

    let root = CAPABILITY_MATRIX
        .iter()
        .find(|entry| entry.path == "PORT")
        .unwrap();
    assert_eq!(root.class, RoutingClass::LocalDatabase);
    for entry in CAPABILITY_MATRIX
        .iter()
        .filter(|entry| entry.path.starts_with("PORT "))
    {
        let expected = if matches!(entry.path, "PORT CNISCAN" | "PORT CNISCAN2" | "PORT PROBE") {
            RoutingClass::Physical
        } else {
            RoutingClass::LocalDatabase
        };
        assert_eq!(entry.class, expected, "{}", entry.path);
        assert!(
            entry.evidence.contains("native_cgate_port.json"),
            "{}",
            entry.path
        );
    }
}

#[test]
fn aircon_rows_retain_native_command_boundaries_and_report_evidence() {
    let fixture: serde_json::Value = serde_json::from_str(include_str!(
        "../../testdata/fixtures/native_cgate_aircon.json"
    ))
    .expect("native AIRCON evidence must remain valid JSON");
    assert_eq!(fixture["oracle"]["version"], "3.4.0.2001");
    assert_eq!(fixture["commands"].as_array().unwrap().len(), 11);
    assert_eq!(
        fixture["oracle"]["jar_sha256"],
        "3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630"
    );
    let boundary = fixture["boundary_examples"].as_array().unwrap();
    assert!(boundary.iter().any(|row| {
        row["command"].as_str().unwrap().contains("2147483647")
            && row["payload_hex"] == "05AC002F010153FF001740"
    }));
    assert!(boundary.iter().any(|row| {
        row["command"].as_str().unwrap().contains(" 1 , 3")
            && row["payload_hex"] == "05AC002F01005300000000"
    }));
    assert_eq!(
        fixture["inbound_reports"]["sample_sal_hex"]
            .as_array()
            .unwrap()
            .len(),
        8
    );
    for entry in CAPABILITY_MATRIX
        .iter()
        .filter(|entry| entry.path.starts_with("AIRCON "))
    {
        assert_eq!(entry.class, RoutingClass::Physical, "{}", entry.path);
        assert!(
            entry.evidence.contains("native_cgate_aircon.json"),
            "{}",
            entry.path
        );
    }
}

#[test]
fn security_rows_retain_native_command_boundaries_and_decoder_evidence() {
    let fixture: serde_json::Value = serde_json::from_str(include_str!(
        "../../testdata/fixtures/native_cgate_security.json"
    ))
    .expect("native SECURITY evidence must remain valid JSON");
    assert_eq!(fixture["oracle"]["version"], "3.4.0.2001");
    assert_eq!(fixture["commands"].as_array().unwrap().len(), 19);
    assert_eq!(
        fixture["oracle"]["jar_sha256"],
        "3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630"
    );
    assert_eq!(
        fixture["validated_boundaries"]["display_message"],
        "zero or one token; C-Gate escape decoding; at most 17 encoded bytes despite stale help claiming 18"
    );
    assert!(fixture["native_bug_closed"]
        .as_str()
        .unwrap()
        .contains("validates 1..127"));
    let root = CAPABILITY_MATRIX
        .iter()
        .find(|entry| entry.path == "SECURITY")
        .unwrap();
    assert_eq!(root.class, RoutingClass::LocalDatabase);
    for entry in CAPABILITY_MATRIX
        .iter()
        .filter(|entry| entry.path.starts_with("SECURITY "))
    {
        assert_eq!(entry.class, RoutingClass::Physical, "{}", entry.path);
        assert!(
            entry.evidence.contains("native_cgate_security.json"),
            "{}",
            entry.path
        );
    }
}

#[test]
fn audio_rows_retain_native_command_boundaries_and_decoder_evidence() {
    let fixture: serde_json::Value = serde_json::from_str(include_str!(
        "../../testdata/fixtures/native_cgate_audio.json"
    ))
    .expect("native AUDIO evidence must remain valid JSON");
    assert_eq!(fixture["oracle"]["version"], "3.4.0.2001");
    assert_eq!(fixture["commands"].as_array().unwrap().len(), 19);
    assert_eq!(
        fixture["inbound_decoder"]["command_events"]
            .as_array()
            .unwrap()
            .len(),
        19
    );
    assert_eq!(
        fixture["oracle"]["jar_sha256"],
        "3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630"
    );
    assert_eq!(
        fixture["validated_boundaries"]["output_error_code"],
        "native accepts 0..7 despite manual 0..1"
    );
    assert!(fixture["label_load_icon_evidence_gap"]["native_result"]
        .as_str()
        .unwrap()
        .contains("produced no event"));
    let root = CAPABILITY_MATRIX
        .iter()
        .find(|entry| entry.path == "AUDIO")
        .unwrap();
    assert_eq!(root.class, RoutingClass::LocalDatabase);
    for entry in CAPABILITY_MATRIX
        .iter()
        .filter(|entry| entry.path.starts_with("AUDIO "))
    {
        assert_eq!(entry.class, RoutingClass::Physical, "{}", entry.path);
        assert!(
            entry.evidence.contains("native_cgate_audio.json"),
            "{}",
            entry.path
        );
    }
}

#[test]
fn measurement_rows_retain_native_boundaries_and_decoder_evidence() {
    let fixture: serde_json::Value = serde_json::from_str(include_str!(
        "../../testdata/fixtures/native_cgate_measurement.json"
    ))
    .expect("native MEASUREMENT evidence must remain valid JSON");
    assert_eq!(fixture["oracle"]["version"], "3.4.0.2001");
    assert_eq!(
        fixture["oracle"]["jar_sha256"],
        "3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630"
    );
    assert_eq!(fixture["application"], 228);
    assert_eq!(fixture["opcode"], 14);
    assert_eq!(fixture["commands"].as_array().unwrap().len(), 5);
    assert_eq!(fixture["incoming_event"]["event_code"], 702);
    let root = CAPABILITY_MATRIX
        .iter()
        .find(|entry| entry.path == "MEASUREMENT")
        .unwrap();
    assert_eq!(root.class, RoutingClass::LocalDatabase);
    let data = CAPABILITY_MATRIX
        .iter()
        .find(|entry| entry.path == "MEASUREMENT DATA")
        .unwrap();
    assert_eq!(data.class, RoutingClass::Physical);
    assert!(data.evidence.contains("native_cgate_measurement.json"));
}

#[test]
fn mediatransport_rows_retain_native_boundaries_and_decoder_evidence() {
    let fixture: serde_json::Value = serde_json::from_str(include_str!(
        "../../testdata/fixtures/native_cgate_mediatransport.json"
    ))
    .expect("native MEDIATRANSPORT evidence must remain valid JSON");
    assert_eq!(fixture["oracle"]["version"], "3.4.0.2001");
    assert_eq!(fixture["commands"].as_array().unwrap().len(), 24);
    assert_eq!(
        fixture["oracle"]["jar_sha256"],
        "3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630"
    );
    assert_eq!(fixture["application"]["decimal"], 192);
    assert_eq!(
        fixture["oracle"]["command_parser_class_sha256"],
        "7ae66677a8b82950214e52af91f1b3d8a8339f7d62c0f0617fb3a402760fe2f3"
    );
    assert_eq!(
        fixture["oracle"]["dequote_helper_class_sha256"],
        "7d5aed3401676c3e896e008a030a6d4a55e417d1d6ddf200734b938ca9ed7c7d"
    );
    assert!(fixture["native_quirks"]["unicode_name_encoder"]
        .as_str()
        .unwrap()
        .contains("ten FF bytes"));
    assert!(fixture["acceptance_boundary"]
        .as_str()
        .unwrap()
        .contains("Media-device acceptance"));
    let root = CAPABILITY_MATRIX
        .iter()
        .find(|entry| entry.path == "MEDIATRANSPORT")
        .unwrap();
    assert_eq!(root.class, RoutingClass::LocalDatabase);
    let commands = CAPABILITY_MATRIX
        .iter()
        .filter(|entry| entry.path.starts_with("MEDIATRANSPORT "))
        .collect::<Vec<_>>();
    assert_eq!(commands.len(), 21);
    for entry in commands {
        assert_eq!(entry.class, RoutingClass::Physical, "{}", entry.path);
        assert!(
            entry.evidence.contains("native_cgate_mediatransport.json"),
            "{}",
            entry.path
        );
    }
}

#[test]
fn telephony_rows_retain_native_boundaries_and_decoder_evidence() {
    let fixture: serde_json::Value = serde_json::from_str(include_str!(
        "../../testdata/fixtures/native_cgate_telephony.json"
    ))
    .expect("native TELEPHONY evidence must remain valid JSON");
    assert_eq!(fixture["oracle"]["version"], "3.4.0.2001");
    assert_eq!(
        fixture["oracle"]["jar_sha256"],
        "3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630"
    );
    assert_eq!(fixture["application"]["decimal"], 224);
    assert_eq!(fixture["commands"].as_array().unwrap().len(), 10);
    assert_eq!(fixture["inbound_events"].as_array().unwrap().len(), 17);
    assert_eq!(
        fixture["validated_boundaries"]["divert_number"],
        "exactly one whitespace-delimited token; Java UTF-16 length 1..16; quotes and backslash escape spelling are literal, not shell-style decoded"
    );
    assert!(fixture["validated_boundaries"]["single_byte_number_event"]
        .as_str()
        .unwrap()
        .contains("out data1"));
    assert!(fixture["commands"].as_array().unwrap().iter().any(|row| {
        row["command"].as_str().unwrap().ends_with('é') && row["payload_hex"] == "05E000A283FFFF"
    }));
    let root = CAPABILITY_MATRIX
        .iter()
        .find(|entry| entry.path == "TELEPHONY")
        .unwrap();
    assert_eq!(root.class, RoutingClass::LocalDatabase);
    for entry in CAPABILITY_MATRIX
        .iter()
        .filter(|entry| entry.path.starts_with("TELEPHONY "))
    {
        assert_eq!(entry.class, RoutingClass::Physical, "{}", entry.path);
        assert!(
            entry.evidence.contains("native_cgate_telephony.json"),
            "{}",
            entry.path
        );
    }
}

#[test]
fn administrative_subset_is_local_while_vendor_formats_stay_fail_closed() {
    let class = |path| {
        CAPABILITY_MATRIX
            .iter()
            .find(|entry| entry.path == path)
            .unwrap_or_else(|| panic!("missing capability row {path}"))
            .class
    };
    for path in [
        "PROJECT ARCHIVE",
        "PROJECT RESTORE",
        "PROJECT RENAME",
        "PROJECT COPY",
        "PROJECT DELETE",
        "REPOSITORY LIST",
        "DBSETXML",
        "APPLICATIONS GET_CATALOG",
        "CALCULATOR TEST",
        "CGL IMPORT",
        "CGL EXPORT",
    ] {
        assert_eq!(class(path), RoutingClass::LocalDatabase, "{path}");
    }
    for path in [
        "REPOSITORY USE",
        "PROJECT REPAIR",
        "TRANSFORM MIGRATE_SQL",
        "TRANSFORM PROJECT",
        "TRANSFORM SQL_TO_XML",
        "TRANSFORM SQL_TO_XML_CGATE2",
        "TRANSFORM XML_TO_SQL",
    ] {
        assert_eq!(class(path), RoutingClass::FailClosed502, "{path}");
    }
}

#[test]
fn repository_transform_fixture_pins_local_exchange_and_fail_closed_boundaries() {
    let fixture: serde_json::Value = serde_json::from_str(include_str!(
        "../../testdata/fixtures/native_cgate_repository_transform.json"
    ))
    .expect("native repository/transform evidence must remain valid JSON");
    assert_eq!(fixture["oracle"]["version"], "3.4.0.2001");
    assert_eq!(
        fixture["oracle"]["jar_sha256"],
        "3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630"
    );
    assert_eq!(
        fixture["calculator_test"]["success_case"]["lines"][0],
        "134-result: OK"
    );
    assert_eq!(fixture["cgl_1_1"]["observed_rules"]["version"], "1.1");
    assert_eq!(fixture["repository_use"]["scope"], "server-global");

    for path in [
        "APPLICATIONS GET_CATALOG",
        "CALCULATOR TEST",
        "CGL EXPORT",
        "CGL IMPORT",
    ] {
        let row = CAPABILITY_MATRIX
            .iter()
            .find(|entry| entry.path == path)
            .unwrap_or_else(|| panic!("missing capability row {path}"));
        assert_eq!(row.class, RoutingClass::LocalDatabase, "{path}");
        assert!(
            row.evidence
                .contains("native_cgate_repository_transform.json"),
            "{path}"
        );
    }
    for path in [
        "REPOSITORY USE",
        "TRANSFORM MIGRATE_SQL",
        "TRANSFORM PROJECT",
        "TRANSFORM SQL_TO_XML",
        "TRANSFORM SQL_TO_XML_CGATE2",
        "TRANSFORM XML_TO_SQL",
    ] {
        let row = CAPABILITY_MATRIX
            .iter()
            .find(|entry| entry.path == path)
            .unwrap_or_else(|| panic!("missing capability row {path}"));
        assert_eq!(row.class, RoutingClass::FailClosed502, "{path}");
        assert!(
            row.evidence
                .contains("native_cgate_repository_transform.json"),
            "{path}"
        );
    }
}

#[test]
fn project_copy_delete_rows_point_to_retained_native_evidence() {
    let fixture: serde_json::Value = serde_json::from_str(include_str!(
        "../../testdata/fixtures/native_cgate_project_copy_delete.json"
    ))
    .expect("native project-administration evidence must remain valid JSON");
    assert_eq!(fixture["software"]["cgate_version"], "3.4.0 build 2001");
    assert_eq!(fixture["copy"]["success"]["final"], "200 OK.");
    assert_eq!(fixture["delete"]["success"]["final"], "200 OK.");
    assert_eq!(
        fixture["copy"]["identity"]["source_group_oid"],
        fixture["copy"]["identity"]["copy_group_oid_after_restart"]
    );
    for path in ["PROJECT COPY", "PROJECT DELETE"] {
        let row = CAPABILITY_MATRIX
            .iter()
            .find(|entry| entry.path == path)
            .unwrap_or_else(|| panic!("missing capability row {path}"));
        assert!(
            row.evidence
                .contains("native_cgate_project_copy_delete.json"),
            "{path}"
        );
    }
}

#[test]
fn label_kfi_paths_are_physical_and_evidence_the_operational_get() {
    for path in ["LABEL KFIGET", "LABEL KFISET"] {
        let row = CAPABILITY_MATRIX
            .iter()
            .find(|entry| entry.path == path)
            .unwrap_or_else(|| panic!("missing capability row {path}"));
        assert_eq!(row.class, RoutingClass::Physical, "{path}");
        assert!(row.evidence.contains("parameter-0xFF"), "{path}");
    }
    let get = CAPABILITY_MATRIX
        .iter()
        .find(|entry| entry.path == "LABEL KFIGET")
        .unwrap();
    assert!(get.evidence.contains("GET as programming"));
}

#[test]
fn label_clear_is_physical_and_evidences_confirmation_only_exact_once_delivery() {
    let row = CAPABILITY_MATRIX
        .iter()
        .find(|entry| entry.path == "LABEL CLEAR")
        .expect("LABEL CLEAR row exists");
    assert_eq!(row.class, RoutingClass::Physical);
    assert!(row.evidence.contains("A3 FF 00 27"));
    assert!(row.evidence.contains("A4 FF 00 66"));
    assert!(row.evidence.contains("no unit ACK/readback"));
    assert!(row.evidence.contains("never replays"));
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
fn obsolete_pins_native_net_commands() {
    let obsolete: BTreeSet<&str> = CAPABILITY_MATRIX
        .iter()
        .filter(|entry| entry.class == RoutingClass::Obsolete400)
        .map(|entry| entry.path)
        .collect();
    assert_eq!(
        obsolete,
        BTreeSet::from(["NET CHECK_UNRAVEL", "NET STATE_INTERVAL"])
    );
}

#[test]
fn net_lifecycle_rows_match_sanitized_build_2001_evidence_and_residuals() {
    let fixture: serde_json::Value = serde_json::from_str(include_str!(
        "../../testdata/fixtures/native_cgate_net_lifecycle.json"
    ))
    .expect("native NET lifecycle evidence must remain valid JSON");
    assert_eq!(fixture["oracle"]["version"], "3.4.0");
    assert_eq!(fixture["oracle"]["build"], 2001);
    assert_eq!(fixture["oracle"]["site_project_used"], false);
    assert_eq!(
        fixture["oracle"]["jar_sha256"],
        "3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630"
    );
    for (key, class) in [
        ("local", RoutingClass::LocalDatabase),
        ("physical", RoutingClass::Physical),
        ("obsolete_400", RoutingClass::Obsolete400),
        ("fail_closed", RoutingClass::FailClosed502),
    ] {
        for path in fixture["implemented_classification"][key]
            .as_array()
            .expect("classification is an array")
        {
            let path = path.as_str().expect("path is text");
            let row = CAPABILITY_MATRIX
                .iter()
                .find(|entry| entry.path == path)
                .unwrap_or_else(|| panic!("missing NET lifecycle row {path}"));
            assert_eq!(row.class, class, "{path}");
        }
    }
    assert_eq!(fixture["wire_vectors"].as_array().unwrap().len(), 5);
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
    assert_eq!(supplement.len(), 11, "supplement list must stay 11 entries");
    for path in [
        "APPLICATIONS",
        "CALCULATOR",
        "IDENTIFY",
        "REPOSITORY",
        "TRANSFORM",
    ] {
        assert_eq!(
            supplement.get(path),
            Some(&RoutingClass::LocalDatabase),
            "{path} parent help is local"
        );
    }
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
