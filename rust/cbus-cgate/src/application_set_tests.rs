//! Owned regression cases; not an original Application Address wire oracle.
use crate::*;

fn command(model: &mut Server, body: &str) -> Response {
    model.handle(&format!("[owned] {body}"))
}

fn server() -> Server {
    let mut model = Server::new(AccessLevel::Program).with_programming(true);
    assert_eq!(command(&mut model, "PROJECT NEW SAFEAPP").status, 200);
    assert_eq!(
        command(&mut model, "DBCREATENET 254 Local Cni 127.0.0.1:1").status,
        200
    );
    for address in [72, 0, 71, 66, 50] {
        assert_eq!(
            command(
                &mut model,
                &format!("DBADDSAFE //SAFEAPP/254 Application {address} App{address}")
            )
            .status,
            301
        );
    }
    model
}

fn state(model: &Server) -> serde_json::Value {
    serde_json::json!({"fields": model.db_fields, "objects": model.objects,
        "pending": model.db_pending, "levels": model.db_levels,
        "extras": model.db_xml_extras, "runtime": model.cgl_runtime,
        "order": model.projects["SAFEAPP"].networks[&254].application_creation_order})
}

fn oid(model: &Server, address: u8) -> String {
    model
        .resolve_db_xml_target(&format!("//SAFEAPP/254/{address}"))
        .unwrap()
        .oid
}

#[test]
fn numeric_and_oid_safe_moves_preserve_descendants_and_creation_slot() {
    for by_oid in [false, true] {
        let mut model = server();
        let original_oid = oid(&model, 71);
        let group = command(&mut model, "DBADDSAFE //SAFEAPP/254/71 Group 1 Child");
        assert_eq!(group.status, 301);
        let level = command(&mut model, "DBADDSAFE //SAFEAPP/254/71/1 Level 7 Existing");
        assert_eq!(level.status, 301);
        let level_oid = level.final_text.trim_start_matches("301 OID=");
        model.level_mut(level_oid).unwrap().raw_value = Some("oops".to_string());
        let previous_level = model.level(level_oid).unwrap().clone();
        let missing = command(
            &mut model,
            "DBADDSAFE //SAFEAPP/254/71/1 Level 8 MissingValue",
        );
        assert_eq!(missing.status, 301);
        let missing_oid = missing.final_text.trim_start_matches("301 OID=");
        let previous_missing = model.level(missing_oid).unwrap().clone();
        assert_eq!(previous_missing.effective_value(), None);
        let neighbour = model.resolve_db_xml_target("//SAFEAPP/254/50").unwrap();
        let neighbour_fields = model
            .pending_object("SAFEAPP", &neighbour.oid)
            .unwrap()
            .clone();
        let target = if by_oid {
            format!("!{original_oid}")
        } else {
            "//SAFEAPP/254/71".to_string()
        };
        let response = command(&mut model, &format!("DBSETSAFE {target}/Address 70"));
        assert_eq!(response.status, 200, "{}", response.final_text);
        assert_eq!(oid(&model, 70), original_oid);
        assert!(model.resolve_db_xml_target("//SAFEAPP/254/71").is_err());
        assert_eq!(
            model.projects["SAFEAPP"].networks[&254]
                .application_creation_order
                .addresses,
            [72, 0, 70, 66, 50]
        );
        assert!(!model.objects.contains("//SAFEAPP/254/71-GROUP-1"));
        assert!(model.objects.contains("//SAFEAPP/254/70-GROUP-1"));
        assert!(!model.objects.contains("//SAFEAPP/254-APPLICATION-71"));
        assert!(model.objects.contains("//SAFEAPP/254-APPLICATION-70"));
        let moved = model.level(level_oid).unwrap();
        let mut expected = previous_level;
        expected.parent = "//SAFEAPP/254/70/1".to_string();
        assert_eq!(*moved, expected);
        let mut expected_missing = previous_missing;
        expected_missing.parent = "//SAFEAPP/254/70/1".to_string();
        assert_eq!(*model.level(missing_oid).unwrap(), expected_missing);
        assert_eq!(
            *model.pending_object("SAFEAPP", &neighbour.oid).unwrap(),
            neighbour_fields
        );
        assert_eq!(
            command(&mut model, "DBSETSAFE //SAFEAPP/254/71/TagName Ghost").status,
            401
        );
        assert!(!model.db_fields.contains_key("//SAFEAPP/254/71/TagName"));
    }
}

#[test]
fn safe_decimal_grammar_conflict_and_same_address_are_atomic() {
    let mut model = server();
    let before = state(&model);
    for value in ["+70", "-0", "0x46", "256", "oops", "70 1", "72"] {
        let result = command(
            &mut model,
            &format!("DBSETSAFE //SAFEAPP/254/71/Address {value}"),
        );
        assert_eq!(result.status, 408, "{value}: {}", result.final_text);
        assert_eq!(state(&model), before);
    }
    assert_eq!(
        command(&mut model, "DBSETSAFE //SAFEAPP/254/71/Address 71").status,
        200
    );
    assert_eq!(state(&model), before);
    // HELP admits digit strings, but target lexical readback is not captured.
    assert_eq!(
        command(&mut model, "DBSETSAFE //SAFEAPP/254/71/Address 070").status,
        200
    );
    assert_eq!(
        model
            .pending_object("SAFEAPP", &oid(&model, 70))
            .unwrap()
            .fields["Address"],
        "070"
    );
}

// An incomplete raw Application reserves its assigned Address without a
// TagName/path. The OID-parent variant is a retained owned-state fixture,
// not a claim about native or public raw DBADD Network-OID admission.
fn assert_incomplete_application_destination_refuses(network_oid_parent: bool) {
    for source_by_oid in [false, true] {
        let mut model = server();
        let source_oid = oid(&model, 71);
        assert_eq!(
            command(&mut model, "DBADDSAFE //SAFEAPP/254/71 Group 1 Child").status,
            301
        );
        let level = command(&mut model, "DBADDSAFE //SAFEAPP/254/71/1 Level 7 Existing");
        assert_eq!(level.status, 301);
        model
            .level_mut(level.final_text.trim_start_matches("301 OID="))
            .unwrap()
            .raw_value = Some("oops".to_string());
        let created = command(&mut model, "DBADD //SAFEAPP/254 Application");
        assert_eq!(created.status, 301);
        let reserved_oid = created.final_text.trim_start_matches("301 OID=");
        assert_eq!(
            command(&mut model, &format!("DBSET !{reserved_oid}/Address 70")).status,
            200
        );
        let parent = if network_oid_parent {
            format!("!{}", model.projects["SAFEAPP"].networks[&254].oid)
        } else {
            "//SAFEAPP/254".to_string()
        };
        if network_oid_parent {
            model
                .db_pending
                .values_mut()
                .find(|object| object.project == "SAFEAPP" && object.oid == reserved_oid)
                .unwrap()
                .parent = parent.clone();
        }
        let reserved = model
            .pending_object("SAFEAPP", reserved_oid)
            .unwrap()
            .clone();
        assert_eq!(reserved.parent, parent);
        assert_eq!(reserved.element, "Application");
        assert_eq!(reserved.fields["Address"], "70");
        assert!(!reserved.fields.contains_key("TagName"));
        assert!(reserved.path.is_none());
        let before = state(&model);
        let before_tables = model.project_tables("SAFEAPP");
        let before_projects = model.projects.clone();
        let before_saved = model.saved_projects.clone();
        let before_known_oids = model.known_oids.clone();
        let before_events = model.events.clone();
        let selected = if source_by_oid {
            format!("!{source_oid}")
        } else {
            "//SAFEAPP/254/71".to_string()
        };
        let response = command(&mut model, &format!("DBSETSAFE {selected}/Address 70"));
        assert_eq!(response.status, 408, "{response:?}");
        assert_eq!(
            response.final_text,
            "408 Operation failed: database Address is already in use"
        );
        assert_eq!(state(&model), before);
        assert_eq!(model.project_tables("SAFEAPP"), before_tables);
        assert_eq!(model.projects, before_projects);
        assert_eq!(model.saved_projects, before_saved);
        // The refusal precedes staging and any allocator call. Avoid a racy
        // process-global NEXT_OID comparison in concurrently running tests.
        assert_eq!(model.known_oids, before_known_oids);
        assert_eq!(model.events, before_events);
        assert_eq!(
            *model.pending_object("SAFEAPP", reserved_oid).unwrap(),
            reserved
        );
        assert_eq!(oid(&model, 71), source_oid);
        assert!(model.resolve_db_xml_target("//SAFEAPP/254/70").is_err());
        assert_eq!(
            model.pending_object("SAFEAPP", &source_oid).unwrap().fields["Address"],
            "71"
        );
        let address = command(&mut model, &format!("DBGET !{source_oid}/Address"));
        assert_eq!(address.status, 342, "{address:?}");
        assert!(address.final_text.ends_with("=71"));
    }
}

#[test]
fn incomplete_numeric_network_application_address_reservation_refuses_safe_move() {
    assert_incomplete_application_destination_refuses(false);
}

#[test]
fn incomplete_network_oid_application_address_reservation_refuses_safe_move() {
    assert_incomplete_application_destination_refuses(true);
}

#[test]
fn safe_name_uniqueness_preserves_oid_and_order() {
    let mut model = server();
    let original_oid = oid(&model, 71);
    let before = state(&model);
    assert_eq!(
        command(&mut model, "DBSETSAFE //SAFEAPP/254/71/TagName App72").status,
        408
    );
    assert_eq!(state(&model), before);
    assert_eq!(
        command(&mut model, "DBSETSAFE //SAFEAPP/254/71/TagName").status,
        400
    );
    assert_eq!(state(&model), before);
    assert_eq!(
        command(
            &mut model,
            &format!("DBSETSAFE !{original_oid}/TagName Renamed")
        )
        .status,
        200
    );
    assert_eq!(oid(&model, 71), original_oid);
    assert_eq!(
        model
            .pending_object("SAFEAPP", &original_oid)
            .unwrap()
            .fields["TagName"],
        "Renamed"
    );
    assert_eq!(
        model.projects["SAFEAPP"].networks[&254]
            .application_creation_order
            .addresses,
        [72, 0, 71, 66, 50]
    );
}

#[test]
fn incomplete_or_inconsistent_descendant_refuses_before_move() {
    let mut model = server();
    let response = command(&mut model, "DBADD //SAFEAPP/254/71 Group");
    assert_eq!(response.status, 301);
    let before = state(&model);
    assert_eq!(
        command(&mut model, "DBSETSAFE //SAFEAPP/254/71/Address 70").status,
        408
    );
    assert_eq!(state(&model), before);
}

#[test]
fn old_prefix_does_not_rewrite_application_50_and_physical_state_is_unchanged() {
    let mut model = server();
    assert_eq!(
        command(&mut model, "DBADDSAFE //SAFEAPP/254 Application 5 Five").status,
        301
    );
    let fifty = model
        .pending_object("SAFEAPP", &oid(&model, 50))
        .unwrap()
        .clone();
    model
        .projects
        .get_mut("SAFEAPP")
        .unwrap()
        .networks
        .get_mut(&254)
        .unwrap()
        .levels
        .insert((5, 1), 42);
    let levels = model.projects["SAFEAPP"].networks[&254].levels.clone();
    model.cgl_runtime.insert("//SAFEAPP/254/5".to_string());
    model.cgl_runtime.insert("//SAFEAPP/254/5/1".to_string());
    model.cgl_runtime.insert("//SAFEAPP/254/50".to_string());
    assert_eq!(
        command(&mut model, "DBSETSAFE //SAFEAPP/254/5/Address 6").status,
        200
    );
    assert_eq!(*model.pending_object("SAFEAPP", &fifty.oid).unwrap(), fifty);
    assert_eq!(model.projects["SAFEAPP"].networks[&254].levels, levels);
    assert!(!model.cgl_runtime.contains("//SAFEAPP/254/5"));
    assert!(!model.cgl_runtime.contains("//SAFEAPP/254/5/1"));
    assert!(model.cgl_runtime.contains("//SAFEAPP/254/6"));
    assert!(model.cgl_runtime.contains("//SAFEAPP/254/6/1"));
    assert!(model.cgl_runtime.contains("//SAFEAPP/254/50"));
}

#[test]
fn raw_and_safe_share_move_aliases_without_widening_raw_grammar() {
    let mut model = server();
    assert_eq!(
        command(&mut model, "DBADDSAFE //SAFEAPP/254/71 Group 1 Child").status,
        301
    );
    let original_oid = oid(&model, 71);
    assert_eq!(
        command(&mut model, &format!("DBSET !{original_oid}/Address 70")).status,
        200
    );
    assert_eq!(oid(&model, 70), original_oid);
    assert!(!model.objects.contains("//SAFEAPP/254/71-GROUP-1"));
    assert!(model.objects.contains("//SAFEAPP/254/70-GROUP-1"));
}

#[test]
fn address_255_is_database_byte_not_cgl_export_chronology() {
    let mut model = server();
    let original_oid = oid(&model, 71);
    assert_eq!(
        command(&mut model, "DBSETSAFE //SAFEAPP/254/71/Address 255").status,
        200
    );
    assert_eq!(oid(&model, 255), original_oid);
    assert_eq!(
        model.projects["SAFEAPP"].networks[&254]
            .application_creation_order
            .addresses,
        [72, 0, 255, 66, 50]
    );
}

#[test]
fn retained_label_fragments_are_not_re_admitted_as_addressed_descendants() {
    let mut model = server();
    let original_oid = oid(&model, 71);
    let mut extras = DbXmlExtras::default();
    extras.children.push("<TagsDLT><TagDLT><OID>11111111-1111-4111-8111-111111111111</OID><TagValue>Preserved Ω</TagValue></TagDLT></TagsDLT>".to_string());
    let key = Server::unit_document_key("SAFEAPP", &original_oid);
    model.db_xml_extras.insert(key.clone(), extras.clone());
    assert_eq!(
        command(&mut model, "DBSETSAFE //SAFEAPP/254/71/Address 70").status,
        200
    );
    assert_eq!(model.db_xml_extras[&key], extras);
    assert_eq!(oid(&model, 70), original_oid);
}

#[test]
fn selected_project_is_required_for_absolute_numeric_move() {
    let mut model = server();
    assert_eq!(command(&mut model, "PROJECT NEW OTHER").status, 200);
    let before = state(&model);
    assert_eq!(
        command(&mut model, "DBSETSAFE //SAFEAPP/254/71/Address 70").status,
        404
    );
    assert_eq!(state(&model), before);
    assert_eq!(command(&mut model, "PROJECT USE SAFEAPP").status, 200);
    assert_eq!(
        command(&mut model, "DBSETSAFE 254/71/Address 70").status,
        200
    );
    assert!(model.resolve_db_xml_target("//SAFEAPP/254/70").is_ok());
}

#[test]
fn captured_cross_kind_unit_tagname_routing_keeps_success_punctuation() {
    let mut model = server();
    let application_oid = oid(&model, 71);
    let mut unit = Unit::blank(20, "Unit");
    unit.oid = application_oid.clone();
    let network = model
        .projects
        .get_mut("SAFEAPP")
        .unwrap()
        .networks
        .get_mut(&254)
        .unwrap();
    network.units.insert(20, unit);
    network.unit_xml_order.push(20);
    let response = command(
        &mut model,
        &format!("DBSETSAFE !{application_oid}/TagName SelectedUnit"),
    );
    assert_eq!(response.status, 200);
    assert_eq!(response.final_text, "200 OK.");
    assert_eq!(
        model
            .pending_object("SAFEAPP", &application_oid)
            .unwrap()
            .fields["TagName"],
        "App71"
    );
}

#[test]
fn database_address_move_does_not_rewrite_units_pp_or_physical_application() {
    let mut model = server();
    let mut unit = Unit::blank(20, "Preserved unit");
    unit.fields
        .insert("Application".to_string(), "71".to_string());
    let network = model
        .projects
        .get_mut("SAFEAPP")
        .unwrap()
        .networks
        .get_mut(&254)
        .unwrap();
    network.units.insert(20, unit.clone());
    network.physical.insert(20, unit.clone());
    network.levels.insert((71, 1), 42);
    let key = Server::unit_document_key("SAFEAPP", &unit.oid);
    model.unit_pp_values.insert(
        key.clone(),
        BTreeMap::from([
            ("Application".to_string(), "71".to_string()),
            ("Byte0".to_string(), "opaque".to_string()),
        ]),
    );
    let pp = model.unit_pp_values.clone();
    assert_eq!(
        command(&mut model, "DBSETSAFE //SAFEAPP/254/71/Address 70").status,
        200
    );
    assert_eq!(model.projects["SAFEAPP"].networks[&254].units[&20], unit);
    assert_eq!(model.projects["SAFEAPP"].networks[&254].physical[&20], unit);
    assert_eq!(
        model.projects["SAFEAPP"].networks[&254].levels[&(71, 1)],
        42
    );
    assert_eq!(model.unit_pp_values, pp);
}

#[test]
fn existing_numeric_tag_overlay_mirrors_only_the_selected_identity_fields() {
    let mut model = server();
    let application_oid = oid(&model, 71);
    assert_eq!(
        command(&mut model, "DBADDSAFE //SAFEAPP/254/71 Group 1 Child").status,
        301
    );
    let level = command(&mut model, "DBADDSAFE //SAFEAPP/254/71/1 Level 7 Existing");
    assert_eq!(level.status, 301);
    let level_oid = level.final_text.trim_start_matches("301 OID=");
    // A scalar move must not re-submit this retained raw Value through the
    // strict complete XML byte parser. No original mutation is executed here.
    model.level_mut(level_oid).unwrap().raw_value = Some("oops".to_string());
    model
        .save_tag_definition("SAFEAPP", "254", "Cni", "127.0.0.1:1", &[])
        .unwrap();
    let mut expected = model.projects["SAFEAPP"].tag_networks["254"].clone();
    let child = expected
        .root
        .children
        .iter_mut()
        .find(|child| {
            child.element == "Application" && child.field("OID") == Some(application_oid.as_str())
        })
        .unwrap();
    for (name, value) in &mut child.fields {
        if name == "Address" {
            *value = "70".to_string();
        } else if name == "TagName" {
            *value = "Renamed Ω".to_string();
        }
    }
    assert_eq!(
        command(&mut model, "DBSETSAFE //SAFEAPP/254/71/Address 70").status,
        200
    );
    assert_eq!(
        command(
            &mut model,
            &format!("DBSETSAFE !{application_oid}/TagName Renamed Ω")
        )
        .status,
        200
    );
    assert_eq!(model.projects["SAFEAPP"].tag_networks["254"], expected);
    assert_eq!(
        model.level(level_oid).unwrap().raw_value.as_deref(),
        Some("oops")
    );
    assert_eq!(model.level(level_oid).unwrap().parent, "//SAFEAPP/254/70/1");
}

#[test]
fn literal_owned_wire_vector_retains_documented_rule_and_policy_boundaries() {
    let vector: serde_json::Value = serde_json::from_str(include_str!(
        "../../testdata/vectors/cgate_application_safe_set.json"
    ))
    .unwrap();
    assert_eq!(vector["target_mutation_native_acceptance"], false);
    for case in vector["cases"].as_array().unwrap() {
        let mut model = server();
        let original_oid = oid(&model, 71);
        let before = state(&model);
        let response = command(&mut model, case["command"].as_str().unwrap());
        assert_eq!(
            u64::from(response.status),
            case["status"].as_u64().unwrap(),
            "{}",
            case["id"]
        );
        assert_eq!(
            response.final_text,
            case["final"].as_str().unwrap(),
            "{}",
            case["id"]
        );
        if case["state_unchanged"].as_bool() == Some(true) {
            assert_eq!(state(&model), before, "{}", case["id"]);
        }
        if let Some(address) = case["result_address"].as_u64() {
            assert_eq!(oid(&model, u8::try_from(address).unwrap()), original_oid);
        }
    }
}

#[test]
fn leading_zero_safe_address_preserves_subtree_and_live_indexed_literal_aliases() {
    let mut model = server();
    let source_oid = oid(&model, 71);
    assert_eq!(
        command(&mut model, "DBADDSAFE //SAFEAPP/254/71 Group 1 Child").status,
        301
    );
    let group_oid = model
        .resolve_db_xml_target("//SAFEAPP/254/71/1")
        .unwrap()
        .oid;
    let level = command(&mut model, "DBADDSAFE //SAFEAPP/254/71/1 Level 7 Existing");
    assert_eq!(level.status, 301);
    let level_oid = level.final_text.trim_start_matches("301 OID=");
    model.level_mut(level_oid).unwrap().raw_value = Some("oops".to_string());
    assert_eq!(
        command(&mut model, "DBADDSAFE //SAFEAPP/254/71/1 Level 8 Missing").status,
        301
    );
    model
        .save_tag_definition("SAFEAPP", "254", "Cni", "127.0.0.1:1", &[])
        .unwrap();
    let before = command(&mut model, "DBGETXML //SAFEAPP/254/71");
    assert_eq!(before.status, 200, "{before:?}");
    let before = before.lines[0].strip_prefix("347-").unwrap().to_string();
    let known_oids = model.known_oids.clone();
    assert_eq!(
        command(&mut model, "DBSETSAFE //SAFEAPP/254/71/Address 070").status,
        200
    );
    let mut expected = before.replacen("<Address>71</Address>", "<Address>070</Address>", 1);
    assert_ne!(before, expected);
    let record = model.current_tag_record("SAFEAPP", "254").unwrap();
    let applications = record
        .root
        .children
        .iter()
        .filter(|child| child.element == "Application")
        .collect::<Vec<_>>();
    let matches = applications
        .iter()
        .enumerate()
        .filter(|(_, child)| child.field("OID") == Some(source_oid.as_str()))
        .collect::<Vec<_>>();
    assert_eq!(matches.len(), 1);
    let ordinal = matches[0].0 + 1;
    assert_eq!(matches[0].1.field("Address"), Some("070"));
    // The ordinal comes from the fresh source-owned list. No name aliases or
    // guessed positions are used, and the XML Address lexeme stays retained.
    let mut previous_name = "App71";
    for (selector, name) in [
        (
            format!("//SAFEAPP/254/Application[{ordinal}]/TagName"),
            "Indexed",
        ),
        ("//SAFEAPP/254/070/TagName".to_string(), "Literal"),
        ("//SAFEAPP/254/70/TagName".to_string(), "Canonical"),
        (format!("!{source_oid}/TagName"), "Issued"),
    ] {
        let response = command(&mut model, &format!("DBSETSAFE {selector} {name}"));
        assert_eq!(response.status, 200, "{selector}: {response:?}");
        expected = expected.replacen(
            &format!("<TagName>{previous_name}</TagName>"),
            &format!("<TagName>{name}</TagName>"),
            1,
        );
        let current = command(&mut model, "DBGETXML //SAFEAPP/254/70");
        assert_eq!(current.status, 200, "{current:?}");
        assert_eq!(current.lines[0].strip_prefix("347-").unwrap(), expected);
        assert_eq!(oid(&model, 70), source_oid);
        let pending = model.pending_object("SAFEAPP", &source_oid).unwrap();
        assert_eq!(pending.path.as_deref(), Some("//SAFEAPP/254/70"));
        assert_eq!(pending.fields["Address"], "070");
        assert_eq!(pending.fields["TagName"], name);
        assert_eq!(model.known_oids, known_oids);
        assert_eq!(
            model.projects["SAFEAPP"].networks[&254]
                .application_creation_order
                .addresses,
            [72, 0, 70, 66, 50]
        );
        previous_name = name;
    }
    let record = model.current_tag_record("SAFEAPP", "254").unwrap();
    let application = record
        .root
        .children
        .iter()
        .find(|child| {
            child.element == "Application" && child.field("OID") == Some(source_oid.as_str())
        })
        .unwrap();
    let groups = application
        .children
        .iter()
        .filter(|child| child.element == "Group")
        .collect::<Vec<_>>();
    let matches = groups
        .iter()
        .enumerate()
        .filter(|(_, child)| child.field("OID") == Some(group_oid.as_str()))
        .collect::<Vec<_>>();
    assert_eq!(matches.len(), 1);
    let group_ordinal = matches[0].0 + 1;
    assert_eq!(matches[0].1.field("Address"), Some("1"));
    let mut previous_group_name = "Child";
    for (selector, name) in [
        (
            format!("//SAFEAPP/254/Application[{ordinal}]/Group[{group_ordinal}]/TagName"),
            "Indexed child",
        ),
        ("//SAFEAPP/254/070/1/TagName".to_string(), "Literal child"),
    ] {
        let response = command(&mut model, &format!("DBSETSAFE {selector} {name}"));
        assert_eq!(response.status, 200, "{selector}: {response:?}");
        expected = expected.replacen(
            &format!("<TagName>{previous_group_name}</TagName>"),
            &format!("<TagName>{name}</TagName>"),
            1,
        );
        let current = command(&mut model, "DBGETXML //SAFEAPP/254/70");
        assert_eq!(current.status, 200, "{current:?}");
        assert_eq!(current.lines[0].strip_prefix("347-").unwrap(), expected);
        let group = model.resolve_db_xml_target("//SAFEAPP/254/70/1").unwrap();
        assert_eq!(group.oid, group_oid);
        let pending_group = model.pending_object("SAFEAPP", &group_oid).unwrap();
        assert_eq!(pending_group.path.as_deref(), Some("//SAFEAPP/254/70/1"));
        assert_eq!(pending_group.fields["Address"], "1");
        assert_eq!(pending_group.fields["TagName"], name);
        let pending_application = model.pending_object("SAFEAPP", &source_oid).unwrap();
        assert_eq!(pending_application.fields["Address"], "070");
        assert_eq!(pending_application.fields["TagName"], "Issued");
        assert_eq!(oid(&model, 70), source_oid);
        assert_eq!(model.known_oids, known_oids);
        assert_eq!(
            model.projects["SAFEAPP"].networks[&254]
                .application_creation_order
                .addresses,
            [72, 0, 70, 66, 50]
        );
        previous_group_name = name;
    }
}

// Name-only raw Applications are durable reservations before Address/path
// materialization. The actual Network-OID parent variant is an owned retained
// state fixture; the constructor itself uses the admitted numeric raw route.
fn assert_incomplete_application_name_reservation_refuses(network_oid_parent: bool) {
    for source_by_oid in [false, true] {
        let mut model = server();
        let source_oid = oid(&model, 71);
        assert_eq!(
            command(&mut model, "DBADDSAFE //SAFEAPP/254/71 Group 1 Child").status,
            301
        );
        let level = command(&mut model, "DBADDSAFE //SAFEAPP/254/71/1 Level 7 Existing");
        assert_eq!(level.status, 301);
        model
            .level_mut(level.final_text.trim_start_matches("301 OID="))
            .unwrap()
            .raw_value = Some("oops".to_string());
        assert_eq!(
            command(&mut model, "DBADDSAFE //SAFEAPP/254/71/1 Level 8 Missing").status,
            301
        );
        assert_eq!(command(&mut model, "PROJECT SAVE SAFEAPP").status, 200);
        let created = command(&mut model, "DBADD //SAFEAPP/254 Application");
        assert_eq!(created.status, 301, "{created:?}");
        let reserved_oid = created.final_text.strip_prefix("301 OID=").unwrap();
        let assigned = command(
            &mut model,
            &format!("DBSET !{reserved_oid}/TagName Reserved"),
        );
        assert_eq!(assigned.status, 200, "{assigned:?}");
        let parent = if network_oid_parent {
            format!("!{}", model.projects["SAFEAPP"].networks[&254].oid)
        } else {
            "//SAFEAPP/254".to_string()
        };
        if network_oid_parent {
            model
                .db_pending
                .values_mut()
                .find(|object| object.project == "SAFEAPP" && object.oid == reserved_oid)
                .unwrap()
                .parent = parent.clone();
        }
        let reserved = model
            .pending_object("SAFEAPP", reserved_oid)
            .unwrap()
            .clone();
        assert_eq!(reserved.parent, parent);
        assert_eq!(reserved.element, "Application");
        assert_eq!(reserved.fields["TagName"], "Reserved");
        assert!(!reserved.fields.contains_key("Address"));
        assert!(reserved.path.is_none());
        let source_xml = command(&mut model, "DBGETXML //SAFEAPP/254/71");
        assert_eq!(source_xml.status, 200, "{source_xml:?}");
        let before = state(&model);
        let tables = model.project_tables("SAFEAPP");
        let projects = model.projects.clone();
        let saved = model.saved_projects.clone();
        let known = model.known_oids.clone();
        let events = model.events.clone();
        let selected = if source_by_oid {
            format!("!{source_oid}")
        } else {
            "//SAFEAPP/254/71".to_string()
        };
        let response = command(
            &mut model,
            &format!("DBSETSAFE {selected}/TagName Reserved"),
        );
        assert_eq!(response.status, 408, "{response:?}");
        assert_eq!(
            response.final_text,
            "408 Operation failed: Application TagName is already in use"
        );
        assert_eq!(state(&model), before);
        assert_eq!(model.project_tables("SAFEAPP"), tables);
        assert_eq!(model.projects, projects);
        assert_eq!(model.saved_projects, saved);
        assert_eq!(model.known_oids, known);
        assert_eq!(model.events, events);
        assert_eq!(model.current.as_deref(), Some("SAFEAPP"));
        assert_eq!(
            *model.pending_object("SAFEAPP", reserved_oid).unwrap(),
            reserved
        );
        assert_eq!(oid(&model, 71), source_oid);
        let source = model.pending_object("SAFEAPP", &source_oid).unwrap();
        assert_eq!(source.fields["Address"], "71");
        assert_eq!(source.fields["TagName"], "App71");
        assert_eq!(command(&mut model, "DBGETXML //SAFEAPP/254/71"), source_xml);
        // The refusal guard precedes staging/allocator calls. Compare the
        // model's issued-OID set, not the shared process-global NEXT_OID.
    }
}

#[test]
fn incomplete_numeric_network_application_name_reservation_refuses_safe_rename() {
    assert_incomplete_application_name_reservation_refuses(false);
}

#[test]
fn incomplete_network_oid_application_name_reservation_refuses_safe_rename() {
    assert_incomplete_application_name_reservation_refuses(true);
}

#[test]
fn current_application_name_and_unrelated_parent_reservations_remain_admitted() {
    for foreign_project in [false, true] {
        for network_oid_parent in [false, true] {
            let mut model = server();
            let source_oid = oid(&model, 71);
            let before = state(&model);
            let same = command(&mut model, "DBSETSAFE //SAFEAPP/254/71/TagName App71");
            assert_eq!(same.status, 200, "{same:?}");
            assert_eq!(state(&model), before);
            let (project, network) = if foreign_project {
                assert_eq!(command(&mut model, "PROJECT NEW OTHER").status, 200);
                ("OTHER", 254)
            } else {
                ("SAFEAPP", 253)
            };
            assert_eq!(
                command(
                    &mut model,
                    &format!("DBCREATENET {network} Other Cni nowhere")
                )
                .status,
                200
            );
            let created = command(
                &mut model,
                &format!("DBADD //{project}/{network} Application"),
            );
            assert_eq!(created.status, 301, "{created:?}");
            let reserved_oid = created.final_text.strip_prefix("301 OID=").unwrap();
            assert_eq!(
                command(
                    &mut model,
                    &format!("DBSET !{reserved_oid}/TagName Reserved")
                )
                .status,
                200
            );
            if network_oid_parent {
                let parent = format!("!{}", model.projects[project].networks[&network].oid);
                model
                    .db_pending
                    .values_mut()
                    .find(|object| object.project == project && object.oid == reserved_oid)
                    .unwrap()
                    .parent = parent;
            }
            assert_eq!(command(&mut model, "PROJECT USE SAFEAPP").status, 200);
            let reserved = model.pending_object(project, reserved_oid).unwrap().clone();
            let known = model.known_oids.clone();
            let foreign_tables = foreign_project.then(|| model.project_tables(project));
            let response = command(
                &mut model,
                &format!("DBSETSAFE !{source_oid}/TagName Reserved"),
            );
            assert_eq!(response.status, 200, "{response:?}");
            assert_eq!(
                *model.pending_object(project, reserved_oid).unwrap(),
                reserved
            );
            assert_eq!(model.known_oids, known);
            if let Some(tables) = foreign_tables {
                assert_eq!(model.project_tables(project), tables);
            }
            let source = model.pending_object("SAFEAPP", &source_oid).unwrap();
            assert_eq!(source.fields["TagName"], "Reserved");
            assert_eq!(source.fields["Address"], "71");
            assert_eq!(oid(&model, 71), source_oid);
            assert_eq!(
                model.projects["SAFEAPP"].networks[&254]
                    .application_creation_order
                    .addresses,
                [72, 0, 71, 66, 50]
            );
        }
    }
}
