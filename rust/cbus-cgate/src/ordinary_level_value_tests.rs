//! Private owning regressions; no original-server or physical acceptance.
use crate::*;

const PROJECT: &str = "LVSAFE";
const PATH: &str = "//LVSAFE/254/80/8/4";

fn vector() -> serde_json::Value {
    serde_json::from_str(include_str!(
        "../../testdata/vectors/ordinary_level_value_safe_owned.json"
    ))
    .unwrap()
}

fn command(model: &mut Server, body: &str) -> Response {
    model.handle(&format!("[owned] {body}"))
}

fn seed() -> Server {
    let mut model = Server::new(AccessLevel::Program);
    assert_eq!(command(&mut model, "PROJECT NEW LVSAFE").status, 200);
    assert_eq!(
        command(&mut model, "DBCREATENET 254 Local Cni nowhere").status,
        200
    );
    assert_eq!(
        command(&mut model, "DBADDSAFE //LVSAFE/254 Application 80 App").status,
        301
    );
    let literal = vector();
    let result = model.handle_document(
        "[owned] DBSETXML //LVSAFE/254/80",
        literal["application_xml"].as_str().unwrap(),
    );
    assert_eq!(result.status, 301, "{result:?}");
    assert_eq!(
        result.final_text,
        "301 OID=aaaaaaaa-aaaa-4aaa-8aaa-000000000080"
    );
    model
}

fn xml(model: &mut Server, path: &str) -> String {
    let response = command(model, &format!("DBGETXML {path}"));
    assert_eq!(response.status, 200, "{response:?}");
    assert_eq!(response.lines.len(), 1);
    response.lines[0].strip_prefix("347-").unwrap().to_string()
}

fn state(model: &Server) -> serde_json::Value {
    serde_json::json!({
        "projects": model.projects, "saved_projects": model.saved_projects,
        "current": model.current, "fields": model.db_fields,
        "objects": model.objects, "known_oids": model.known_oids,
        "pending": model.db_pending, "levels": model.db_levels,
        "extras": model.db_xml_extras, "unit_documents": model.unit_documents,
        "unit_pp_fields": model.unit_pp_fields, "unit_pp_values": model.unit_pp_values,
        "runtime": model.cgl_runtime, "events": model.events,
        "retired_oids": model.invalidated_unit_oid_lookups,
    })
}

fn assert_read(model: &mut Server, path: &str, expected: &str) {
    let response = command(model, &format!("DBGET {path}/Value"));
    assert_eq!(response.status, 342, "{response:?}");
    assert!(response.lines.is_empty());
    assert_eq!(response.final_text, format!("342 {path}/Value={expected}"));
}

#[test]
fn ordinary_numeric_safe_value_updates_entire_graph_and_both_readbacks() {
    let literal = vector();
    let oid = literal["level_oid"].as_str().unwrap();
    for route in [PATH, "254/80/8/4"] {
        let mut model = seed();
        let before = xml(&mut model, "//LVSAFE");
        assert_eq!(before.matches("Value=\"77\"").count(), 1);
        let projects = model.projects.clone();
        let extras = model.db_xml_extras.clone();
        let known = model.known_oids.clone();
        let response = command(&mut model, &format!("DBSETSAFE {route}/Value 99"));
        assert_eq!(response.status, 200);
        assert_eq!(response.final_text, "200 OK");
        assert_eq!(
            xml(&mut model, "//LVSAFE"),
            before.replace("Value=\"77\"", "Value=\"99\"")
        );
        assert_eq!(model.projects, projects);
        assert_eq!(model.db_xml_extras, extras);
        assert_eq!(model.known_oids, known);
        assert_eq!(model.db_fields[&format!("{PATH}/Value")], "99");
        assert_eq!(
            model.pending_object(PROJECT, oid).unwrap().fields["Value"],
            "99"
        );
        assert_read(&mut model, PATH, "99");
        assert_read(&mut model, &format!("!{oid}"), "99");
    }
}

#[test]
fn numeric_then_issued_oid_keeps_exact_live_mirrors_and_noop() {
    let mut model = seed();
    let oid = vector()["level_oid"].as_str().unwrap().to_string();
    assert_eq!(
        command(&mut model, &format!("DBSETSAFE {PATH}/Value 99")).status,
        200
    );
    let before = xml(&mut model, "//LVSAFE");
    assert_eq!(
        command(&mut model, &format!("DBSETSAFE !{oid}/Value 100")).status,
        200
    );
    assert_eq!(
        xml(&mut model, "//LVSAFE"),
        before.replace("Value=\"99\"", "Value=\"100\"")
    );
    assert_read(&mut model, PATH, "100");
    assert_read(&mut model, &format!("!{oid}"), "100");
    let before = state(&model);
    assert_eq!(
        command(&mut model, &format!("DBSETSAFE {PATH}/Value 100")).status,
        200
    );
    assert_eq!(state(&model), before);
}

#[test]
fn existing_oid_byte_lexemes_and_numeric_lexemes_have_equal_graph_effects() {
    let literal = vector();
    let oid = literal["level_oid"].as_str().unwrap();
    for row in literal["valid_byte_cases"].as_array().unwrap() {
        let raw = row[0].as_str().unwrap();
        let expected = row[1].as_str().unwrap();
        for route in [PATH.to_string(), format!("!{oid}")] {
            let mut model = seed();
            let before = xml(&mut model, "//LVSAFE");
            let response = command(&mut model, &format!("DBSETSAFE {route}/Value {raw}"));
            assert_eq!(response.status, 200, "{route} {raw}: {response:?}");
            assert_eq!(
                xml(&mut model, "//LVSAFE"),
                before.replace("Value=\"77\"", &format!("Value=\"{expected}\""))
            );
            assert_read(&mut model, &format!("!{oid}"), expected);
        }
    }
}

#[test]
fn invalid_byte_or_null_text_refuses_atomically_in_both_aliases() {
    let literal = vector();
    let oid = literal["level_oid"].as_str().unwrap();
    for value in literal["invalid_byte_cases"].as_array().unwrap() {
        for route in [PATH.to_string(), format!("!{oid}")] {
            let mut model = seed();
            let before = state(&model);
            let response = command(
                &mut model,
                &format!("DBSETSAFE {route}/Value {}", value.as_str().unwrap()),
            );
            assert_eq!(response.status, 400, "{response:?}");
            assert_eq!(response.final_text, "400 Invalid level value");
            assert_eq!(state(&model), before);
        }
    }
}

#[test]
fn plain_and_copied_pending_null_become_bytes_without_metadata_loss() {
    for with_pending in [false, true] {
        let mut model = seed();
        let result = command(&mut model, "DBADDSAFE //LVSAFE/254/80/8 Level 7 Null");
        assert_eq!(result.status, 301);
        let oid = result
            .final_text
            .strip_prefix("301 OID=")
            .unwrap()
            .to_string();
        let path = "//LVSAFE/254/80/8/7";
        if with_pending {
            // Retained copied-owner fixture, not a new native NULL capture.
            model.insert_db_pending_object(DbPendingObject {
                oid: oid.clone(),
                project: PROJECT.to_string(),
                parent: "//LVSAFE/254/80/8".to_string(),
                element: "Level".to_string(),
                fields: HashMap::from([
                    ("Address".to_string(), "7".to_string()),
                    ("TagName".to_string(), "Null".to_string()),
                ]),
                path: Some(path.to_string()),
                xml_order: None,
            });
            model.db_xml_extras.insert(
                Server::unit_document_key(PROJECT, &oid),
                DbXmlExtras {
                    saved_level_tags_pending: true,
                    ..Default::default()
                },
            );
        }
        let before = xml(&mut model, "//LVSAFE");
        assert_read(&mut model, path, "null");
        assert_read(&mut model, &format!("!{oid}"), "null");
        let extras = model.db_xml_extras.clone();
        let response = command(&mut model, &format!("DBSETSAFE {path}/Value 9"));
        assert_eq!(response.status, 200, "{response:?}");
        let after = xml(&mut model, "//LVSAFE");
        let null_open = format!("<Level><OID>{oid}</OID>");
        assert_eq!(before.matches(&null_open).count(), 1);
        assert_eq!(
            after,
            before.replace(&null_open, &format!("<Level Value=\"9\"><OID>{oid}</OID>"))
        );
        assert_eq!(model.db_xml_extras, extras);
        assert_read(&mut model, path, "9");
        assert_read(&mut model, &format!("!{oid}"), "9");
    }
}

#[test]
fn stale_or_incomplete_pending_mirrors_never_get_healed() {
    let oid = vector()["level_oid"].as_str().unwrap().to_string();
    for poison in [
        "missing",
        "empty",
        "wrong-value",
        "wrong-path",
        "wrong-kind",
        "wrong-name",
        "wrong-address",
        "opaque",
        "parent-address",
    ] {
        let mut model = seed();
        let key = model.pending_object_key(PROJECT, &oid).unwrap();
        let pending = model.db_pending.get_mut(&key).unwrap();
        match poison {
            "missing" => {
                pending.fields.remove("Value");
            }
            "empty" => {
                pending.fields.insert("Value".to_string(), "".to_string());
            }
            "wrong-value" => {
                pending.fields.insert("Value".to_string(), "12".to_string());
            }
            "wrong-path" => {
                pending.path = None;
            }
            "wrong-kind" => {
                pending.element = "NetVar".to_string();
            }
            "wrong-name" => {
                pending
                    .fields
                    .insert("TagName".to_string(), "Other".to_string());
            }
            "wrong-address" => {
                pending
                    .fields
                    .insert("Address".to_string(), "9".to_string());
            }
            "opaque" => {
                model.level_mut(&oid).unwrap().raw_value = Some("oops".to_string());
            }
            "parent-address" => {
                let parent_oid = vector()["group_oid"].as_str().unwrap().to_string();
                let parent_key = model.pending_object_key(PROJECT, &parent_oid).unwrap();
                model
                    .db_pending
                    .get_mut(&parent_key)
                    .unwrap()
                    .fields
                    .insert("Address".to_string(), "9".to_string());
            }
            _ => unreachable!(),
        }
        let before = state(&model);
        let getter = command(&mut model, &format!("DBGET {PATH}/Value"));
        assert_eq!(getter.status, 408, "{poison}: {getter:?}");
        assert_eq!(state(&model), before, "read-only {poison}");
        let result = command(&mut model, &format!("DBSETSAFE {PATH}/Value 99"));
        assert_eq!(result.status, 408, "{poison}: {result:?}");
        assert_eq!(state(&model), before, "{poison}");
    }
}

#[test]
fn competing_address_oid_unit_and_retired_owners_refuse_without_allocation() {
    let oid = vector()["level_oid"].as_str().unwrap().to_string();
    for poison in ["address", "oid", "pending", "unit", "retired", "unknown"] {
        let mut model = seed();
        match poison {
            "address" | "oid" => {
                let mut competing = model.level(&oid).unwrap().clone();
                if poison == "address" {
                    competing.oid = "bbbbbbbb-bbbb-4bbb-8bbb-000000000004".to_string();
                } else {
                    competing.address = 20;
                }
                model
                    .db_levels
                    .insert("private-competing-owner".to_string(), competing);
            }
            "pending" => {
                let mut competing = model.pending_object(PROJECT, &oid).unwrap().clone();
                competing.oid = "bbbbbbbb-bbbb-4bbb-8bbb-000000000004".to_string();
                competing.path = None;
                model.insert_db_pending_object(competing);
            }
            "unit" => {
                let mut unit = Unit::blank(20, "Winning Unit");
                unit.oid = oid.clone();
                model
                    .projects
                    .get_mut(PROJECT)
                    .unwrap()
                    .networks
                    .get_mut(&254)
                    .unwrap()
                    .units
                    .insert(20, unit);
            }
            "retired" => {
                model
                    .invalidated_unit_oid_lookups
                    .insert((PROJECT.to_string(), oid.clone()));
            }
            "unknown" => {
                model.known_oids.remove(&oid);
            }
            _ => unreachable!(),
        }
        let before = state(&model);
        let result = command(&mut model, &format!("DBSETSAFE {PATH}/Value 99"));
        assert!(matches!(result.status, 401 | 408), "{poison}: {result:?}");
        assert_eq!(state(&model), before, "{poison}");
        if poison == "unit" {
            // The pre-existing shared Unit OID branch must still win over
            // a private Level claimant; this candidate does not reinterpret it.
            let getter = command(&mut model, &format!("DBGET !{oid}/Value"));
            assert_eq!(getter.status, 401, "{getter:?}");
            let setter = command(&mut model, &format!("DBSETSAFE !{oid}/Value 99"));
            assert_eq!(setter.status, 409, "{setter:?}");
            assert_eq!(
                setter.final_text,
                "409 Ambiguous duplicate Unit OID; use its path"
            );
            assert_eq!(state(&model), before);
        }
    }
}

#[test]
fn stale_published_value_alias_is_refused_before_any_typed_mutation() {
    for alias in [
        format!("{PATH}/Value"),
        format!("!{}/Value", vector()["level_oid"].as_str().unwrap()),
    ] {
        let mut model = seed();
        model.db_fields.insert(alias, "99".to_string());
        let before = state(&model);
        assert_eq!(
            command(&mut model, &format!("DBSETSAFE {PATH}/Value 100")).status,
            408
        );
        assert_eq!(state(&model), before);
    }
}

#[test]
fn save_load_and_selected_project_copy_preserve_bytes_and_source_isolation() {
    let mut model = seed();
    let oid = vector()["level_oid"].as_str().unwrap().to_string();
    let source = xml(&mut model, "//LVSAFE");
    assert_eq!(command(&mut model, "PROJECT COPY LVSAFE COPY").status, 200);
    assert_eq!(command(&mut model, "PROJECT USE COPY").status, 200);
    assert_eq!(
        command(&mut model, "DBSETSAFE //COPY/254/80/8/4/Value 99").status,
        200
    );
    let changed = xml(&mut model, "//COPY");
    assert_eq!(command(&mut model, "PROJECT SAVE COPY").status, 200);
    for verb in ["CLOSE", "LOAD", "USE"] {
        assert_eq!(
            command(&mut model, &format!("PROJECT {verb} COPY")).status,
            200
        );
    }
    assert_eq!(xml(&mut model, "//COPY"), changed);
    assert_eq!(xml(&mut model, "//LVSAFE"), source);
    assert_read(&mut model, "//COPY/254/80/8/4", "99");
    assert_read(&mut model, &format!("!{oid}"), "99");
    assert_eq!(command(&mut model, "PROJECT USE LVSAFE").status, 200);
    assert_read(&mut model, &format!("!{oid}"), "77");
    let read_only = state(&model);
    assert_read(&mut model, PATH, "77");
    assert_read(&mut model, "254/80/8/4", "77");
    assert_eq!(state(&model), read_only);
    assert_eq!(xml(&mut model, "//LVSAFE"), source);
    assert_eq!(xml(&mut model, "//COPY"), changed);
    let response = command(&mut model, &format!("DBSETSAFE {PATH}/Value 100"));
    assert_eq!(response.status, 200, "{response:?}");
    assert_eq!(response.final_text, "200 OK");
    assert_eq!(source.matches("Value=\"77\"").count(), 1);
    let source_changed = source.replace("Value=\"77\"", "Value=\"100\"");
    assert_eq!(xml(&mut model, "//LVSAFE"), source_changed);
    assert_eq!(xml(&mut model, "//COPY"), changed);
    assert_read(&mut model, PATH, "100");
    assert_read(&mut model, &format!("!{oid}"), "100");
    assert_eq!(command(&mut model, "PROJECT USE COPY").status, 200);
    let read_only = state(&model);
    assert_read(&mut model, "//COPY/254/80/8/4", "99");
    assert_read(&mut model, "254/80/8/4", "99");
    assert_read(&mut model, &format!("!{oid}"), "99");
    assert_eq!(state(&model), read_only);
    assert_eq!(xml(&mut model, "//COPY"), changed);
    assert_eq!(xml(&mut model, "//LVSAFE"), source_changed);
}

#[test]
fn raw_dbset_and_associated_raw_value_routes_keep_their_existing_owner() {
    let mut model = seed();
    let before = xml(&mut model, "//LVSAFE");
    let oid = vector()["level_oid"].as_str().unwrap().to_string();
    let before_state = state(&model);
    let raw = command(&mut model, &format!("DBSET {PATH}/Value oops"));
    assert_eq!(raw.status, 408, "{raw:?}");
    assert_eq!(
        raw.final_text,
        "408 Operation failed: Level Value must be a byte"
    );
    assert!(raw.lines.is_empty());
    // The existing unsafe owner validates a nonempty byte before updating
    // the typed record or its pending/canonical mirrors. This is not the
    // separate associated raw-lexeme owner exercised below.
    assert_eq!(state(&model), before_state);
    assert_eq!(xml(&mut model, "//LVSAFE"), before);
    assert_eq!(state(&model), before_state);

    // A valid unsafe byte updates only the same typed/pending Value and
    // canonical scalar field. These literal effects follow the unchanged
    // current unsafe source; no successor SAFE hook is used for this control.
    let mut expected_state = model.clone();
    expected_state.level_mut(&oid).unwrap().value = Some(99);
    let pending_key = expected_state.pending_object_key(PROJECT, &oid).unwrap();
    expected_state
        .db_pending
        .get_mut(&pending_key)
        .unwrap()
        .fields
        .insert("Value".to_string(), "99".to_string());
    expected_state
        .db_fields
        .insert(format!("{PATH}/Value"), "99".to_string());
    let raw = command(&mut model, &format!("DBSET {PATH}/Value 99"));
    assert_eq!(raw.status, 200, "{raw:?}");
    assert_eq!(raw.final_text, "200 OK.");
    assert!(raw.lines.is_empty());
    assert_eq!(state(&model), state(&expected_state));
    assert_eq!(before.matches("Value=\"77\"").count(), 1);
    assert_eq!(
        xml(&mut model, "//LVSAFE"),
        before.replace("Value=\"77\"", "Value=\"99\"")
    );
    assert_eq!(state(&model), state(&expected_state));
    assert_eq!(model.level(&oid).unwrap().value, Some(99));
    assert_eq!(model.level(&oid).unwrap().raw_value, None);
    assert_eq!(
        model.pending_object(PROJECT, &oid).unwrap().fields["Value"],
        "99"
    );
    let mut model = seed();
    let before_application = xml(&mut model, "//LVSAFE/254/80");
    let network_oid = model.projects[PROJECT].networks[&254].oid.clone();
    assert_eq!(
        command(&mut model, &format!("DBADD !{network_oid} Languages")).status,
        301
    );
    let response = command(&mut model, &format!("DBSETSAFE {PATH}/Value oops"));
    assert_eq!(response.status, 200, "{response:?}");
    assert_read(&mut model, PATH, "oops");
    assert_read(&mut model, &format!("!{oid}"), "oops");
    assert_eq!(
        xml(&mut model, "//LVSAFE/254/80"),
        before_application.replace("Value=\"77\"", "Value=\"oops\"")
    );
}

#[test]
fn absent_foreign_and_noncanonical_numeric_routes_never_publish_opaque_aliases() {
    let mut model = seed();
    for path in [
        "//LVSAFE/254/80/8/200",
        "//LVSAFE/254/80/8/256",
        "//LVSAFE/254/080/8/4",
    ] {
        let before = state(&model);
        assert_eq!(
            command(&mut model, &format!("DBSETSAFE {path}/Value 99")).status,
            401
        );
        assert_eq!(state(&model), before);
    }
    assert_eq!(command(&mut model, "PROJECT NEW OTHER").status, 200);
    let before = state(&model);
    assert_eq!(
        command(&mut model, &format!("DBSETSAFE {PATH}/Value 99")).status,
        404
    );
    assert_eq!(state(&model), before);
}

#[test]
fn nested_netvar_child_level_uses_its_exact_byte_owner() {
    let mut model = seed();
    let literal = vector();
    let oid = literal["nested_level_oid"].as_str().unwrap();
    let parent_oid = literal["netvar_oid"].as_str().unwrap();
    let path = "//LVSAFE/254/80/9/6";
    let before = xml(&mut model, "//LVSAFE");
    assert_eq!(before.matches("Value=\"66\"").count(), 1);
    let parent = model.level(parent_oid).unwrap().clone();
    assert!(parent.netvar);
    assert_eq!(parent.value, None);
    assert!(!model.level(oid).unwrap().netvar);
    let projects = model.projects.clone();
    let extras = model.db_xml_extras.clone();
    let known = model.known_oids.clone();
    let result = command(&mut model, &format!("DBSETSAFE {path}/Value 42"));
    assert_eq!(result.status, 200, "{result:?}");
    assert_eq!(result.final_text, "200 OK");
    assert_eq!(
        xml(&mut model, "//LVSAFE"),
        before.replace("Value=\"66\"", "Value=\"42\"")
    );
    assert_eq!(model.level(parent_oid).unwrap(), &parent);
    assert_eq!(
        model
            .level(literal["level_oid"].as_str().unwrap())
            .unwrap()
            .value,
        Some(77)
    );
    assert_eq!(model.projects, projects);
    assert_eq!(model.db_xml_extras, extras);
    assert_eq!(model.known_oids, known);
    let read_only = state(&model);
    assert_read(&mut model, path, "42");
    assert_read(&mut model, &format!("!{oid}"), "42");
    assert_eq!(state(&model), read_only);
}

#[test]
fn numeric_getters_refuse_unexplained_oid_caches_without_rebinding_relative_aliases() {
    let oid = vector()["level_oid"].as_str().unwrap().to_string();
    // These are deliberately poisoned owned-model states, not native captures.
    for poison in [
        "no-other-owner",
        "other-byte",
        "other-pending",
        "other-canonical",
    ] {
        let mut model = seed();
        let before = state(&model);
        assert_read(&mut model, PATH, "77");
        assert_eq!(state(&model), before);
        if poison != "no-other-owner" {
            assert_eq!(command(&mut model, "PROJECT COPY LVSAFE COPY").status, 200);
        }
        if matches!(poison, "other-pending" | "other-canonical") {
            let other = model
                .db_levels
                .values_mut()
                .find(|level| level.oid == oid && level.parent == "//COPY/254/80/8")
                .unwrap();
            other.value = Some(99);
        }
        if poison == "other-canonical" {
            let key = model.pending_object_key("COPY", &oid).unwrap();
            model
                .db_pending
                .get_mut(&key)
                .unwrap()
                .fields
                .insert("Value".to_string(), "99".to_string());
            model
                .db_fields
                .insert("//COPY/254/80/8/4/Value".to_string(), "12".to_string());
        }
        model
            .db_fields
            .insert(format!("!{oid}/Value"), "99".to_string());
        let before = state(&model);
        let result = command(&mut model, &format!("DBGET {PATH}/Value"));
        assert_eq!(result.status, 408, "{poison}: {result:?}");
        assert_eq!(
            result.final_text,
            "408 Operation failed: Ordinary Level Value mirror disagrees with its owner"
        );
        assert_eq!(state(&model), before, "{poison}");
    }
    // A legacy relative generic-store cache has no durable project owner. The
    // selected typed owner is read without migrating, deleting or healing it.
    let mut model = seed();
    model
        .db_fields
        .insert("254/80/8/4/Value".to_string(), "12".to_string());
    let before_xml = xml(&mut model, "//LVSAFE");
    let before = state(&model);
    assert_read(&mut model, "254/80/8/4", "77");
    assert_eq!(state(&model), before);
    assert_eq!(
        command(&mut model, "DBSETSAFE 254/80/8/4/Value 99").status,
        200
    );
    assert_eq!(
        xml(&mut model, "//LVSAFE"),
        before_xml.replace("Value=\"77\"", "Value=\"99\"")
    );
    assert_eq!(model.db_fields["254/80/8/4/Value"], "12");
    assert_eq!(model.db_fields[&format!("{PATH}/Value")], "99");
    assert_eq!(model.db_fields[&format!("!{oid}/Value")], "99");
    assert_read(&mut model, "254/80/8/4", "99");
}
