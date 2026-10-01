use super::*;

async fn run(service: &Arc<Service>, client: &mut ClientState, command: &str) -> Response {
    service
        .handle(client, &format!("[db-load] {command}"))
        .await
}

async fn ok_command(service: &Arc<Service>, client: &mut ClientState, command: &str) {
    let reply = run(service, client, command).await;
    assert_eq!(reply.status, 200, "{command}: {reply:?}");
}

async fn definitions(service: &Arc<Service>, project: &str) -> serde_json::Value {
    let key = format!("@cmqttd/net-catalog/v1/{}/active", hex::encode(project));
    let model = service.model.lock().await;
    model.config_values.get(&key).map_or_else(
        || serde_json::json!([]),
        |value| serde_json::from_str(value).unwrap(),
    )
}

#[tokio::test]
async fn net_db_load_materializes_fresh_and_sequential_closed_definitions_without_io() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    for command in [
        "PROJECT NEW FRESH",
        "PROJECT USE FRESH",
        "NET LOAD DB",
        "NET LOAD FILE",
    ] {
        ok_command(&service, &mut client, command).await;
    }
    assert_eq!(
        run(&service, &mut client, "NET LIST").await.final_text,
        "132 no networks found"
    );
    for command in [
        "DBCREATENET 254 CniSeed Cni 127.0.0.1:1",
        "NET LOAD DB",
        "NET LOAD DB",
        "DBCREATENET 253 SerialSeed Serial /private/tmp/owned-absent-cbus-port",
        "NET LOAD DB",
        "DBCREATENET 252 BridgeSeed Bridge 254/p/252",
        "NET LOAD DB",
        "NET LOAD FILE",
    ] {
        ok_command(&service, &mut client, command).await;
    }
    let before = definitions(&service, "FRESH").await;
    assert_eq!(before.as_array().unwrap().len(), 3);
    assert_eq!(before[0]["name"], "254");
    assert_eq!(before[0]["interface_type"], "Cni");
    assert_eq!(before[0]["bound_network"], 254);
    assert_eq!(before[1]["name"], "253");
    assert_eq!(before[1]["interface_type"], "Serial");
    assert_eq!(before[2]["name"], "252");
    assert_eq!(before[2]["interface_type"], "Bridge");
    let list = run(&service, &mut client, "NET LIST").await;
    assert_eq!(list.status, 131);
    assert!(list
        .lines
        .iter()
        .chain([&list.final_text])
        .all(|row| row.contains("State=new InterfaceState=closed")));
    assert!(
        tokio::time::timeout(Duration::from_millis(20), remote.read_u8())
            .await
            .is_err()
    );
    drop(service);
    let (replacement, _remote) = pci();
    let restarted = Service::new(&fixture(), None, path.clone(), replacement, None).unwrap();
    assert_eq!(definitions(&restarted, "FRESH").await, before);
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn net_db_load_refreshes_tag_fields_and_preserves_unrelated_runtime_names() {
    let path = state_path();
    let (pci_client, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    for command in [
        "PROJECT NEW FRESH",
        "PROJECT USE FRESH",
        "DBCREATENET 254 Seed Cni 127.0.0.1:1",
        "NET LOAD DB",
        "NET RENAME 254 CustomA",
        "NET CREATE Extra Serial /private/tmp/owned-other-port alpha=beta",
        "NET LOAD DB",
        "DBSET //FRESH/254/InterfaceType Serial",
        "DBSET //FRESH/254/InterfaceAddress /private/tmp/owned-refreshed-port",
    ] {
        ok_command(&service, &mut client, command).await;
    }
    let before = definitions(&service, "FRESH").await;
    assert_eq!(
        before
            .as_array()
            .unwrap()
            .iter()
            .map(|definition| definition["name"].as_str().unwrap())
            .collect::<Vec<_>>(),
        ["CustomA", "Extra", "254"]
    );
    assert_eq!(before[2]["interface_address"], "127.0.0.1:1");
    ok_command(&service, &mut client, "NET LOAD DB").await;
    let after = definitions(&service, "FRESH").await;
    assert_eq!(after[2]["interface_type"], "Serial");
    assert_eq!(
        after[2]["interface_address"],
        "/private/tmp/owned-refreshed-port"
    );
    assert_eq!(after[0], before[0]);
    assert_eq!(after[1], before[1]);
    for command in [
        "NET DELETE 254",
        "NET CREATE 254 Cni 127.0.0.1:2 stale=yes",
        "NET LOAD DB",
    ] {
        ok_command(&service, &mut client, command).await;
    }
    let conflict_refreshed = definitions(&service, "FRESH").await;
    assert_eq!(
        conflict_refreshed[2]["interface_type"],
        after[2]["interface_type"]
    );
    assert_eq!(
        conflict_refreshed[2]["interface_address"],
        after[2]["interface_address"]
    );
    assert_eq!(conflict_refreshed[2]["options"], serde_json::json!([]));
    assert_eq!(
        conflict_refreshed[2]["bound_network"],
        serde_json::Value::Null,
        "metadata refresh must not bind a CREATE-only definition"
    );
    assert_eq!(conflict_refreshed[0], after[0]);
    assert_eq!(conflict_refreshed[1], after[1]);
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn net_db_load_ignores_stale_numeric_snapshots_but_retains_legacy_named_snapshots() {
    let path = state_path();
    let (pci_client, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    for command in [
        "PROJECT NEW FRESH",
        "PROJECT USE FRESH",
        "DBCREATENET 254 Seed Cni 127.0.0.1:1",
        "NET LOAD DB",
        "NET CREATE CABIN Serial /private/tmp/owned-legacy-port retained=yes",
        "NET SAVE DB",
        "DBSET //FRESH/254/InterfaceAddress 127.0.0.1:2",
        "NET DELETE 254",
        "NET DELETE CABIN",
        "NET LOAD DB",
    ] {
        ok_command(&service, &mut client, command).await;
    }
    let restored = definitions(&service, "FRESH").await;
    assert_eq!(restored[0]["interface_address"], "127.0.0.1:2");
    assert_eq!(restored[1]["name"], "CABIN");
    assert_eq!(restored[1]["options"], serde_json::json!(["retained=yes"]));
    for command in ["DBDELETE //FRESH/254", "NET LOAD DB"] {
        ok_command(&service, &mut client, command).await;
    }
    assert_eq!(
        definitions(&service, "FRESH").await,
        restored,
        "tag removal must retain active runtime definition"
    );
    for command in ["NET DELETE 254", "NET LOAD DB"] {
        ok_command(&service, &mut client, command).await;
    }
    let after = definitions(&service, "FRESH").await;
    assert_eq!(after.as_array().unwrap().len(), 1);
    assert_eq!(
        after[0]["name"], "CABIN",
        "stale snapshot must not resurrect removed numeric row"
    );
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn net_db_load_explicit_project_isolation_and_malformed_snapshot_rollback() {
    let path = state_path();
    let (pci_client, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    for command in [
        "PROJECT NEW OTHER",
        "PROJECT USE OTHER",
        "DBCREATENET 10 Seed Cni 127.0.0.1:1",
        "PROJECT USE HARNESS",
        "NET LOAD DB OTHER",
    ] {
        ok_command(&service, &mut client, command).await;
    }
    assert_eq!(client.current.as_deref(), Some("HARNESS"));
    assert_eq!(definitions(&service, "OTHER").await[0]["name"], "10");
    assert_eq!(definitions(&service, "HARNESS").await[0]["name"], "254");
    let before = definitions(&service, "OTHER").await;
    let before_bytes = std::fs::read(&path).unwrap();
    service.model.lock().await.config_values.insert(
        format!(
            "@cmqttd/net-catalog/v1/{}/snapshot/db",
            hex::encode("OTHER")
        ),
        "malformed".to_string(),
    );
    let reply = run(&service, &mut client, "NET LOAD DB OTHER").await;
    assert_eq!(reply.status, 500);
    assert_eq!(definitions(&service, "OTHER").await, before);
    assert_eq!(std::fs::read(&path).unwrap(), before_bytes);
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn net_db_load_commit_failure_rolls_back_and_configured_runtime_is_not_rebound() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client.clone(), None).unwrap();
    let mut client = ClientState::default();
    let before = definitions(&service, "HARNESS").await;
    let physical_before = {
        let mut model = service.model.lock().await;
        let network = model
            .projects
            .get_mut("HARNESS")
            .unwrap()
            .networks
            .get_mut(&254)
            .unwrap();
        network.iface_addr = "127.0.0.1:2".to_string();
        network.levels.insert((56, 1), 42);
        network.physical.insert(5, network.units[&5].clone());
        network.retries = 7;
        (network.state, network.physical.clone(), network.retries)
    };
    std::fs::remove_file(&path).unwrap();
    std::fs::create_dir(&path).unwrap();
    let failed = run(&service, &mut client, "NET LOAD DB").await;
    assert_eq!(
        failed.final_text,
        "500 Database commit failed; change rolled back"
    );
    assert_eq!(definitions(&service, "HARNESS").await, before);
    std::fs::remove_dir(&path).unwrap();
    ok_command(&service, &mut client, "NET LOAD DB").await;
    assert_eq!(
        definitions(&service, "HARNESS").await[0]["interface_address"],
        "127.0.0.1:2"
    );
    assert!(Arc::ptr_eq(&pci_client, &*service.pci.read().await));
    {
        let model = service.model.lock().await;
        let network = &model.projects["HARNESS"].networks[&254];
        assert_eq!(
            (network.state, network.physical.clone(), network.retries),
            physical_before
        );
        assert_eq!(network.levels[&(56, 1)], 42);
    }
    assert!(
        tokio::time::timeout(Duration::from_millis(20), remote.read_u8())
            .await
            .is_err()
    );
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn net_db_load_does_not_materialize_nondurable_runtime_shell() {
    let path = state_path();
    let (pci_client, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    service
        .model
        .lock()
        .await
        .projects
        .get_mut("HARNESS")
        .unwrap()
        .networks
        .get_mut(&254)
        .unwrap()
        .oid
        .clear();
    ok_command(&service, &mut client, "NET CLOSE 254").await;
    ok_command(&service, &mut client, "NET DELETE 254").await;
    ok_command(&service, &mut client, "NET LOAD DB").await;
    assert_eq!(
        definitions(&service, "HARNESS").await,
        serde_json::json!([])
    );
    assert_eq!(run(&service, &mut client, "NET LIST").await.status, 132);
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn net_db_load_refresh_keeps_immutable_binding_and_noncanonical_legacy_names() {
    let path = state_path();
    let (pci_client, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    for command in [
        "NET RENAME 254 253",
        "DBCREATENET 253 Other Serial /private/tmp/owned-absent-port",
        "NET CREATE 0254 Serial /private/tmp/owned-zero-port",
        "NET CREATE 256 Cni 127.0.0.1:1",
        "NET SAVE DB",
        "NET DELETE 0254",
        "NET DELETE 256",
        "NET LOAD DB",
    ] {
        ok_command(&service, &mut client, command).await;
    }
    let rows = definitions(&service, "HARNESS").await;
    let row = rows
        .as_array()
        .unwrap()
        .iter()
        .find(|row| row["name"] == "253")
        .unwrap();
    // SAVE DB now follows the captured native refresh contract: the runtime
    // definition renamed from254 replaces tag253's Serial metadata with its
    // own CNI metadata. Neither existing physical database model is rebound.
    assert_eq!(row["interface_type"], "CNI");
    let model = service.model.lock().await;
    assert_eq!(
        model.projects["HARNESS"].networks[&253].iface_type,
        "Serial"
    );
    assert_eq!(
        model.projects["HARNESS"].tag_networks["253"]
            .interface()
            .field("InterfaceType"),
        Some("CNI")
    );
    drop(model);
    assert_eq!(
        row["bound_network"], 254,
        "refresh must not retarget the binding retained by RENAME"
    );
    for name in ["0254", "256"] {
        assert!(
            rows.as_array()
                .unwrap()
                .iter()
                .any(|row| row["name"] == name),
            "noncanonical legacy name {name} must survive"
        );
    }
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn net_db_load_definition_get_uses_catalogue_fields_until_explicit_refresh() {
    let path = state_path();
    let (pci_client, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    for command in [
        "PROJECT NEW FRESH",
        "PROJECT USE FRESH",
        "DBCREATENET 254 Seed Cni 127.0.0.1:1",
    ] {
        ok_command(&service, &mut client, command).await;
    }
    assert_eq!(definitions(&service, "FRESH").await, serde_json::json!([]));
    for command in [
        "NET LOAD DB",
        "DBSET //FRESH/254/InterfaceType Serial",
        "DBSET //FRESH/254/InterfaceAddress /private/tmp/owned-absent-port",
    ] {
        ok_command(&service, &mut client, command).await;
    }
    assert_eq!(
        run(&service, &mut client, "GET //FRESH/254 InterfaceAddress")
            .await
            .final_text,
        "300 //FRESH/254: InterfaceAddress=127.0.0.1:1"
    );
    assert_eq!(
        run(&service, &mut client, "GET //FRESH/254 Type")
            .await
            .final_text,
        "300 //FRESH/254: Type=Cni"
    );
    ok_command(&service, &mut client, "NET LOAD DB").await;
    for (field, value) in [
        ("Name", "254"),
        ("Type", "Serial"),
        ("InterfaceAddress", "/private/tmp/owned-absent-port"),
        ("Interface", "/private/tmp/owned-absent-port"),
        ("Options", ""),
    ] {
        assert_eq!(
            run(&service, &mut client, &format!("GET //FRESH/254 {field}"))
                .await
                .final_text,
            format!("300 //FRESH/254: {field}={value}")
        );
    }
    for command in [
        "NET RENAME 254 CustomA",
        "NET CREATE Extra Cni 127.0.0.1:2 owned=yes order=second",
        "NET LOAD DB",
    ] {
        ok_command(&service, &mut client, command).await;
    }
    assert_eq!(
        run(&service, &mut client, "GET //FRESH/CustomA Name")
            .await
            .final_text,
        "300 //FRESH/CustomA: Name=CustomA"
    );
    assert_eq!(
        run(&service, &mut client, "GET //FRESH/Extra Options")
            .await
            .final_text,
        "300 //FRESH/Extra: Options=owned=yes order=second"
    );
    assert_eq!(
        run(&service, &mut client, "GET //FRESH/Extra Type")
            .await
            .final_text,
        "300 //FRESH/Extra: Type=Cni"
    );
    for command in [
        "GET cgate Type",
        "GET cgate Name",
        "GET projects Type",
        "GET projects Name",
        "GET //HARNESS/254/p/5 Type",
        "GET //HARNESS/254/p/5 Name",
        "GET //HARNESS/254/p/5 UnitType",
        "GET //HARNESS/254/56/1 Name",
        "GET //MISSING/254 Type",
    ] {
        let expected = {
            let mut model = service.model.lock().await.clone();
            model.current = client.current.clone();
            model.handle(&format!("[db-load] {command}"))
        };
        assert_eq!(
            run(&service, &mut client, command).await,
            expected,
            "unmatched catalogue selector must retain established GET behavior: {command}"
        );
    }
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn net_db_load_replays_literal_original_envelopes_and_source_bindings() {
    let fixture: serde_json::Value = serde_json::from_str(include_str!(
        "../../../../testdata/fixtures/native_cgate_net_db_reconciliation.json"
    ))
    .unwrap();
    let native = fixture["commands"].as_array().unwrap();
    let substitute = |value: &str| {
        value
            .replace("%FIXTURE_SECOND_CNI_PORT%", "2")
            .replace("%FIXTURE_CNI_PORT%", "1")
            .replace("%OWNED_WORK%", "/private/tmp/owned-native-net-vector")
    };
    let mut count = 0;
    for line in
        include_str!("../../../../testdata/vectors/cgate_net_db_reconciliation.jsonl").lines()
    {
        let vector: serde_json::Value = serde_json::from_str(line).unwrap();
        let source = native
            .iter()
            .find(|row| row["label"] == vector["source_label"])
            .unwrap();
        assert_eq!(
            substitute(source["command"].as_str().unwrap()),
            vector["command"].as_str().unwrap()
        );
        let native_reply: Vec<String> = source["response"]
            .as_array()
            .unwrap()
            .iter()
            .map(|row| substitute(row.as_str().unwrap().split_once("] ").unwrap().1))
            .collect();
        let expected: Vec<String> = serde_json::from_value(vector["reply"].clone()).unwrap();
        assert_eq!(
            native_reply, expected,
            "literal vector must remain bound to captured response"
        );
        let path = state_path();
        let (pci_client, mut remote) = pci();
        let service =
            Service::new(&super::fixture(), None, path.clone(), pci_client, None).unwrap();
        let mut client = ClientState::default();
        for setup in vector["setup"].as_array().unwrap() {
            ok_command(&service, &mut client, setup.as_str().unwrap()).await;
        }
        let response = run(&service, &mut client, vector["command"].as_str().unwrap()).await;
        let actual: Vec<String> = format_response(&response)
            .lines()
            .map(|line| line.split_once("] ").unwrap().1.to_string())
            .collect();
        assert_eq!(actual, expected, "original source vector {}", vector["id"]);
        assert!(
            tokio::time::timeout(Duration::from_millis(1), remote.read_u8())
                .await
                .is_err(),
            "literal replay must not write PCI"
        );
        std::fs::remove_file(path).unwrap();
        count += 1;
    }
    assert_eq!(count, 30);
}

#[tokio::test]
async fn net_db_load_file_collision_retains_atomic_cmqttd_deviation() {
    let path = state_path();
    let (pci_client, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    for command in [
        "PROJECT NEW FRESH",
        "PROJECT USE FRESH",
        "NET CREATE CABIN Cni 127.0.0.1:1",
        "NET CREATE SHED Cni 127.0.0.1:2",
        "NET SAVE FILE",
        "NET DELETE CABIN",
    ] {
        ok_command(&service, &mut client, command).await;
    }
    let before = definitions(&service, "FRESH").await;
    let saved_bytes = std::fs::read(&path).unwrap();
    assert_eq!(
        run(&service, &mut client, "NET LOAD FILE").await.final_text,
        "408 Operation failed: Problem loading: Network name already in use"
    );
    assert_eq!(definitions(&service, "FRESH").await, before, "cmqttd deliberately rolls back the whole load, unlike native's observed partial insertion before408");
    assert_eq!(std::fs::read(&path).unwrap(), saved_bytes);
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn net_db_load_definition_get_requires_explicit_paths_when_legal_names_collide() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    let oid = service.model.lock().await.projects["HARNESS"].networks[&254]
        .oid
        .clone();
    let names = [
        "cgate".to_string(),
        "projects".to_string(),
        "cbus".to_string(),
        format!("!{oid}"),
    ];
    let fields = ["Name", "Type", "InterfaceAddress", "Interface", "Options"];
    let mut baseline = Vec::new();
    for name in &names {
        for field in &fields {
            let command = format!("GET {name} {field}");
            baseline.push((command.clone(), run(&service, &mut client, &command).await));
        }
    }
    for name in &names {
        ok_command(
            &service,
            &mut client,
            &format!("NET CREATE {name} Serial owned-absent-selector-port owned=yes"),
        )
        .await;
    }
    for (command, expected) in baseline {
        assert_eq!(
            run(&service, &mut client, &command).await,
            expected,
            "legal runtime name must not shadow generic GET selector: {command}"
        );
    }
    for name in &names {
        for (field, value) in [
            ("Name", name.as_str()),
            ("Type", "Serial"),
            ("InterfaceAddress", "owned-absent-selector-port"),
            ("Interface", "owned-absent-selector-port"),
            ("Options", "owned=yes"),
        ] {
            let address = format!("//HARNESS/{name}");
            let command = format!("GET {address} {field}");
            assert_eq!(
                run(&service, &mut client, &command).await.final_text,
                format!("300 {address}: {field}={value}"),
                "explicit definition path remains readable: {command}"
            );
        }
    }
    for address in [
        "/cgate",
        "//cgate",
        "///HARNESS/cgate",
        "//HARNESS//cgate",
        "//HARNESS/cgate/",
        "//HARNESS/cgate/extra",
        "//HARNESS/",
        "//",
    ] {
        let command = format!("GET {address} Type");
        let expected = {
            let mut model = service.model.lock().await.clone();
            model.current = client.current.clone();
            model.handle(&format!("[db-load] {command}"))
        };
        assert_eq!(
            run(&service, &mut client, &command).await,
            expected,
            "noncanonical path must retain generic GET dispatch: {command}"
        );
    }
    assert!(
        tokio::time::timeout(Duration::from_millis(20), remote.read_u8())
            .await
            .is_err(),
        "selector dispatch remains local"
    );
    std::fs::remove_file(path).unwrap();
}
