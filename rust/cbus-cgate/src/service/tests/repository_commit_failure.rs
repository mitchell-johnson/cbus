use super::*;

const UNCERTAIN: &str =
    "500 Repository durability uncertain; inspect state before further changes; do not replay";

fn projection(database: &Database) -> serde_json::Value {
    // Network's live state, retries, physical inventory and levels are serde-
    // skipped, so comparing Database structs would test runtime-only fields.
    // Compare every serialized field and array in its exact retained order.
    serde_json::to_value(database).unwrap()
}

fn startup_projection(database: &Database, catalogs: &[(&str, bool)]) -> serde_json::Value {
    let mut expected = projection(database);
    let values = expected["config_values"].as_object_mut().unwrap();
    for (project, empty) in catalogs {
        // Service startup materializes missing catalogues for copied/new
        // projects. Pin these additions literally; all other data stays exact.
        let prefix = format!("@cmqttd/net-catalog/v1/{}", hex::encode(project.as_bytes()));
        let rows = if *empty {
            "[]"
        } else {
            r#"[{"name":"254","interface_type":"CNI","interface_address":"127.0.0.1:10001","options":[],"bound_network":254}]"#
        };
        for (suffix, value) in [
            ("active", rows),
            ("snapshot/db", rows),
            ("db-source-materialized", "true"),
        ] {
            let key = format!("{prefix}/{suffix}");
            if let Some(existing) = values.get(&key) {
                assert_eq!(
                    existing.as_str(),
                    Some(value),
                    "existing literal catalogue {key}"
                );
            } else {
                values.insert(key, serde_json::Value::String(value.into()));
            }
        }
    }
    expected
}

struct Case {
    command: &'static str,
    document: Option<&'static str>,
    read: &'static str,
    setup: &'static [&'static str],
    repair: bool,
}

const CASES: &[Case] = &[
    Case {
        command: "DBSETSAFE //HARNESS/254/p/5/TagName Changed",
        document: None,
        read: "DBGET //HARNESS/254/p/5/TagName",
        setup: &[],
        repair: false,
    },
    Case {
        command: "DBSETXML //HARNESS/254/p/5/TagName",
        document: Some("Changed"),
        read: "DBGET //HARNESS/254/p/5/TagName",
        setup: &[],
        repair: false,
    },
    Case {
        command: "CONFIG SET sync-time changed",
        document: None,
        read: "CONFIG GET sync-time",
        setup: &[],
        repair: false,
    },
    Case {
        command: "FILE MKDIR %HARNESS%/fault-witness",
        document: None,
        read: "FILE DIR %HARNESS%",
        setup: &[],
        repair: false,
    },
    Case {
        command: "ACCESS ADD user fault-witness synthetic-password Admin",
        document: None,
        read: "ACCESS LIST",
        setup: &[],
        repair: false,
    },
    Case {
        command: "ACCESS DELETE 2",
        document: None,
        read: "ACCESS LIST",
        setup: &["ACCESS ADD user fault-witness synthetic-password Admin"],
        repair: false,
    },
    Case {
        command: "ACCESS SAVE fault-witness",
        document: None,
        read: "ACCESS LIST",
        setup: &["ACCESS ADD user fault-witness synthetic-password Admin"],
        repair: false,
    },
    Case {
        command: "ACCESS LOAD fault-witness",
        document: None,
        read: "ACCESS LIST",
        setup: &[
            "ACCESS ADD user fault-witness synthetic-password Admin",
            "ACCESS SAVE fault-witness",
            "ACCESS ADD user later-witness synthetic-password Monitor",
        ],
        repair: false,
    },
    Case {
        command: "PROJECT COPY HARNESS FAULTCP",
        document: None,
        read: "DBGETXML //FAULTCP/254/p/5",
        setup: &[],
        repair: false,
    },
    Case {
        command: "PROJECT REPAIR HARNESS",
        document: None,
        read: "DBGET //HARNESS/254/p/5/Description",
        setup: &[],
        repair: true,
    },
];

async fn exercise(point: repository_io::FailurePoint) {
    let vector: serde_json::Value = serde_json::from_str(include_str!(
        "../../../../testdata/vectors/repository_commit_failure.json"
    ))
    .unwrap();
    for case in CASES {
        let directory = state_path().with_extension("commit-fault");
        std::fs::create_dir(&directory).unwrap();
        let path = directory.join("state.json");
        let (pci, mut remote) = pci();
        let service = Service::new(&fixture(), None, path.clone(), pci.clone(), None).unwrap();
        let mut owner = ClientState::default();
        for command in ["PP LOCK OWNER //HARNESS/254", "PP START OWNED OWNER"]
            .into_iter()
            .chain(case.setup.iter().copied())
        {
            let reply = service.handle(&mut owner, &format!("[1] {command}")).await;
            assert!(reply.status < 400, "{command}: {reply:?}");
        }
        let before = {
            let mut model = service.model.lock().await;
            let network = model
                .projects
                .get_mut("HARNESS")
                .unwrap()
                .networks
                .get_mut(&254)
                .unwrap();
            network.physical.insert(5, network.units[&5].clone());
            network.levels.insert((56, 1), 143);
            if case.repair {
                network.state = NetworkState::Open;
                network.retries = 7;
                // Repair stages a separate restored projection. Give it a live
                // unsaved property so the old image cannot accidentally satisfy
                // the post-rename restart assertion.
                network
                    .units
                    .get_mut(&5)
                    .unwrap()
                    .fields
                    .insert("Description".into(), "Repair witness".into());
                model.db_fields.insert(
                    "//HARNESS/254/p/5/Description".into(),
                    "Repair witness".into(),
                );
            }
            model.clone()
        };
        let old_bytes = std::fs::read(&path).unwrap();
        let before_read = service
            .handle(&mut owner, &format!("[3] {}", case.read))
            .await;
        let fault = repository_io::inject_failure(&path, point);
        let command = format!("[37] {}", case.command);
        let response = match case.document {
            Some(document) => {
                service
                    .handle_document(&mut owner, &command, document)
                    .await
            }
            None => service.handle(&mut owner, &command).await,
        };
        drop(fault);
        assert_eq!(response.status, 500, "{}: {response:?}", case.command);
        let replaced = point == repository_io::FailurePoint::DirectorySync;
        assert_eq!(
            response.final_text,
            if replaced {
                UNCERTAIN
            } else if case.repair {
                "500 Project repair commit failed; change rolled back"
            } else {
                "500 Database commit failed; change rolled back"
            },
            "{}",
            case.command
        );
        let key = if replaced {
            "post_rename"
        } else if case.repair {
            "pre_rename_repair"
        } else {
            "pre_rename"
        };
        assert_eq!(
            crate::format_response(&response),
            vector[key].as_str().unwrap(),
            "{}",
            case.command
        );

        let current_bytes = std::fs::read(&path).unwrap();
        let durable: Database = repository_io::load(&path).unwrap();
        let model = service.model.lock().await;
        assert_eq!(model.sessions, before.sessions, "{}", case.command);
        assert_eq!(model.locks, before.locks, "{}", case.command);
        let current_network = &model.projects["HARNESS"].networks[&254];
        let old_network = &before.projects["HARNESS"].networks[&254];
        assert_eq!(
            current_network.physical, old_network.physical,
            "{}",
            case.command
        );
        assert_eq!(
            current_network.levels, old_network.levels,
            "{}",
            case.command
        );
        assert_eq!(current_network.state, old_network.state, "{}", case.command);
        assert_eq!(
            current_network.retries, old_network.retries,
            "{}",
            case.command
        );
        if replaced {
            assert_ne!(current_bytes, old_bytes, "{}", case.command);
            assert_eq!(
                projection(&durable),
                projection(&Database::from_server(&model)),
                "{}",
                case.command
            );
        } else {
            assert_eq!(current_bytes, old_bytes, "{}", case.command);
            assert!(
                Database::from_server(&model) == Database::from_server(&before),
                "{}",
                case.command
            );
        }
        drop(model);
        assert!(owner.sessions.contains("OWNED"));
        assert!(owner.locks.contains("OWNER"));
        let mut foreign = ClientState::default();
        assert_eq!(
            service
                .handle(&mut foreign, "[4] PP GET OWNED Witness")
                .await
                .status,
            420
        );
        let live_read = service
            .handle(&mut owner, &format!("[3] {}", case.read))
            .await;
        if !replaced {
            assert_eq!(live_read.lines, before_read.lines, "{}", case.command);
            assert_eq!(
                live_read.final_text, before_read.final_text,
                "{}",
                case.command
            );
        }
        // Only reads follow the uncertain response: no retry/save can hide the
        // failure by making another replacement durable.
        assert_eq!(std::fs::read(&path).unwrap(), current_bytes);
        assert_eq!(std::fs::read_dir(&directory).unwrap().count(), 1);
        assert!(
            tokio::time::timeout(Duration::from_millis(10), remote.read_u8())
                .await
                .is_err(),
            "{} reached PCI",
            case.command
        );
        drop(service);
        let restarted = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
        let mut fresh = ClientState::default();
        let restart_read = restarted
            .handle(&mut fresh, &format!("[3] {}", case.read))
            .await;
        if replaced || !case.repair {
            assert_eq!(restart_read.lines, live_read.lines, "{}", case.command);
            assert_eq!(
                restart_read.final_text, live_read.final_text,
                "{}",
                case.command
            );
        }
        let model = restarted.model.lock().await;
        let seeded = if replaced && case.command == "PROJECT COPY HARNESS FAULTCP" {
            vec![("FAULTCP", false)]
        } else {
            vec![]
        };
        let expected_restart = startup_projection(&durable, &seeded);
        assert_eq!(
            expected_restart,
            projection(&Database::from_server(&model)),
            "{} restart projection",
            case.command
        );
        assert!(model.sessions.is_empty());
        assert!(model.locks.is_empty());
        assert!(model.projects["HARNESS"].networks[&254].physical.is_empty());
        assert!(model.projects["HARNESS"].networks[&254].levels.is_empty());
        drop(model);
        let restart_bytes = std::fs::read(&path).unwrap();
        assert_eq!(
            serde_json::from_slice::<serde_json::Value>(&restart_bytes).unwrap(),
            expected_restart
        );
        if seeded.is_empty() {
            assert_eq!(restart_bytes, current_bytes);
        }
        std::fs::remove_dir_all(directory).unwrap();
    }
}

#[tokio::test]
async fn post_rename_directory_sync_failure_keeps_visible_state_and_reports_uncertainty() {
    exercise(repository_io::FailurePoint::DirectorySync).await;
}

#[tokio::test]
async fn pre_rename_failure_preserves_image_model_sessions_and_physical_state() {
    exercise(repository_io::FailurePoint::BeforeRename).await;
}

#[tokio::test]
async fn uncertain_project_lifecycle_updates_selection_and_startup_bookkeeping() {
    for (command, selected, remaining) in [
        (
            "PROJECT NEW EXTRA",
            Some("EXTRA"),
            vec![("AUX", true), ("EXTRA", false)],
        ),
        (
            "PROJECT RENAME AUX RENAMED",
            Some("RENAMED"),
            vec![("RENAMED", true)],
        ),
        ("PROJECT DELETE AUX", None, vec![]),
        ("PROJECT CLOSE AUX", None, vec![]),
    ] {
        let path = state_path();
        let (pci, mut remote) = pci();
        let mut service = Service::new(&fixture(), None, path.clone(), pci.clone(), None).unwrap();
        Arc::get_mut(&mut service).unwrap().startup_projects = Some(Mutex::new(BTreeMap::from([
            ("HARNESS".into(), true),
            ("AUX".into(), true),
        ])));
        let mut owner = ClientState::default();
        for setup in [
            "PROJECT COPY HARNESS AUX",
            "PROJECT SAVE AUX",
            "PROJECT USE AUX",
            "DBSETSAFE //AUX/254/p/5/TagName Unsaved",
            "PP LOCK OWNER //HARNESS/254",
            "PP START OWNED OWNER",
        ] {
            let reply = service.handle(&mut owner, &format!("[2] {setup}")).await;
            assert!(reply.status < 400, "{setup}: {reply:?}");
        }
        *service.startup_projects.as_ref().unwrap().lock().await =
            BTreeMap::from([("HARNESS".into(), true), ("AUX".into(), true)]);
        let before_bytes = std::fs::read(&path).unwrap();
        let fault =
            repository_io::inject_failure(&path, repository_io::FailurePoint::DirectorySync);
        let reply = service.handle(&mut owner, &format!("[1] {command}")).await;
        drop(fault);
        assert_eq!(reply.final_text, UNCERTAIN, "{command}");
        assert_eq!(owner.current.as_deref(), selected, "{command}");
        let expected = std::iter::once(("HARNESS".to_string(), true))
            .chain(
                remaining
                    .into_iter()
                    .map(|(name, started)| (name.to_string(), started)),
            )
            .collect::<BTreeMap<_, _>>();
        assert_eq!(
            *service.startup_projects.as_ref().unwrap().lock().await,
            expected,
            "{command}"
        );
        let current_bytes = std::fs::read(&path).unwrap();
        assert_ne!(current_bytes, before_bytes, "{command}");
        let persisted: Database = repository_io::load(&path).unwrap();
        let model = service.model.lock().await;
        assert_eq!(model.current.as_deref(), selected, "{command}");
        assert_eq!(
            projection(&persisted),
            projection(&Database::from_server(&model)),
            "{command}"
        );
        assert!(model.sessions.contains_key("OWNED"));
        assert!(model.locks.contains_key("OWNER"));
        drop(model);
        assert_eq!(
            service
                .handle(&mut owner, "[5] PROJECT USE")
                .await
                .final_text,
            selected.map_or("123 project=null".to_string(), |name| format!(
                "123 project={name}"
            )),
            "{command}"
        );
        assert_eq!(std::fs::read(&path).unwrap(), current_bytes);
        assert!(
            tokio::time::timeout(Duration::from_millis(10), remote.read_u8())
                .await
                .is_err()
        );
        drop(service);
        let restarted = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
        let seeded = match command {
            "PROJECT NEW EXTRA" => vec![("AUX", false), ("EXTRA", true)],
            "PROJECT RENAME AUX RENAMED" => vec![("RENAMED", false)],
            "PROJECT CLOSE AUX" => vec![("AUX", false)],
            "PROJECT DELETE AUX" => vec![],
            _ => unreachable!(),
        };
        let expected_restart = startup_projection(&persisted, &seeded);
        assert_eq!(
            expected_restart,
            projection(&Database::from_server(&*restarted.model.lock().await)),
            "{command} restart"
        );
        let restart_bytes = std::fs::read(&path).unwrap();
        assert_eq!(
            serde_json::from_slice::<serde_json::Value>(&restart_bytes).unwrap(),
            expected_restart
        );
        if seeded.is_empty() {
            assert_eq!(restart_bytes, current_bytes);
        }
        std::fs::remove_file(path).unwrap();
    }
}

#[tokio::test]
async fn worker_save_uncertainty_stops_before_later_instruction_without_replay() {
    let path = state_path();
    let (pci, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci.clone(), None).unwrap();
    let mut owner = ClientState::default();
    for command in [
        "PP LOCK OWNER //HARNESS/254",
        "PP START OWNED OWNER",
        "PP LOAD OWNED /db//HARNESS/254/p/5",
        "PP SET OWNED StaticTextString0 Saved witness",
        "PROGRAMMER CREATE FAULT Synthetic Route",
        "PROGRAMMER ADD_INSTRUCTION FAULT PP_SAVE OWNED /db//HARNESS/254/p/5",
        "PROGRAMMER ADD_INSTRUCTION FAULT PP_SET OWNED StaticTextString0 Must not execute",
    ] {
        let response = service.handle(&mut owner, &format!("[1] {command}")).await;
        assert!(response.status < 400, "{command}: {response:?}");
    }
    let serial = {
        let mut model = service.model.lock().await;
        let programmer = model.programmers.get_mut("fault").unwrap();
        programmer.state = ProgrammerState::Running;
        programmer.serial
    };
    let before_bytes = std::fs::read(&path).unwrap();
    let fault = repository_io::inject_failure(&path, repository_io::FailurePoint::DirectorySync);
    service
        .clone()
        .run_programmer(owner.clone(), "fault".into(), serial, false)
        .await;
    drop(fault);
    let bytes = std::fs::read(&path).unwrap();
    assert_ne!(bytes, before_bytes);
    let persisted: Database = repository_io::load(&path).unwrap();
    let model = service.model.lock().await;
    let programmer = &model.programmers["fault"];
    assert_eq!(programmer.state, ProgrammerState::Error);
    assert_eq!(programmer.instructions.len(), 2);
    assert!(programmer.instructions[0].failed);
    assert!(!programmer.instructions[0].completed);
    assert!(!programmer.instructions[1].active);
    assert!(!programmer.instructions[1].completed);
    assert!(!programmer.instructions[1].failed);
    assert_eq!(
        model.sessions["OWNED"].params["StaticTextString0"],
        "Saved witness"
    );
    assert!(model.sessions["OWNED"].dirty.is_empty());
    assert_eq!(
        projection(&persisted),
        projection(&Database::from_server(&model))
    );
    drop(model);
    assert_eq!(
        service
            .handle(&mut owner, "[6] PP GET OWNED StaticTextString0")
            .await
            .final_text,
        "315 StaticTextString0=Saved witness"
    );
    assert_eq!(
        service
            .handle(&mut owner, "[7] PROGRAMMER TRIGGER FAULT START")
            .await
            .final_text,
        "400 Syntax Error: failed: transition of START is not allowed on ERROR"
    );
    assert_eq!(std::fs::read(&path).unwrap(), bytes);
    assert!(
        tokio::time::timeout(Duration::from_millis(10), remote.read_u8())
            .await
            .is_err()
    );
    drop(service);
    let restarted = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let model = restarted.model.lock().await;
    assert_eq!(
        projection(&persisted),
        projection(&Database::from_server(&model))
    );
    assert_eq!(
        model.projects["HARNESS"].networks[&254].units[&5].fields["StaticTextString0"],
        "Saved witness"
    );
    assert!(model.sessions.is_empty());
    assert!(model.programmers.is_empty());
    drop(model);
    assert_eq!(std::fs::read(&path).unwrap(), bytes);
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn repair_preserves_ordinary_and_configured_shell_runtime_at_each_commit_boundary() {
    let vector: serde_json::Value = serde_json::from_str(include_str!(
        "../../../../testdata/vectors/repository_commit_failure.json"
    ))
    .unwrap();
    for (shell, point) in [
        (false, None),
        (true, None),
        (true, Some(repository_io::FailurePoint::BeforeRename)),
        (true, Some(repository_io::FailurePoint::DirectorySync)),
    ] {
        let directory = state_path().with_extension("shell-repair");
        std::fs::create_dir(&directory).unwrap();
        let path = directory.join("state.json");
        let (pci, mut remote) = pci();
        let mut service = Service::new(&fixture(), None, path.clone(), pci.clone(), None).unwrap();
        let physical_unit =
            service.model.lock().await.projects["HARNESS"].networks[&254].units[&5].clone();
        let mut owner = ClientState::default();
        if shell {
            assert_eq!(service.handle(&mut owner, "[1] DBNEW").await.status, 200);
            // DBNEW retains a saved image whose OIDs are canonically admitted
            // by startup restoration. Establish that restarted baseline before
            // isolating repair's commit boundary and the one staged marker.
            let before_startup = std::fs::read(&path).unwrap();
            let mut expected_startup: serde_json::Value =
                serde_json::from_slice(&before_startup).unwrap();
            let canonical_ids = {
                let model = service.model.lock().await;
                let mut ids = model
                    .known_oids
                    .iter()
                    .cloned()
                    .collect::<std::collections::BTreeSet<_>>();
                for image in model.saved_projects.values() {
                    assert!(image.project.tag_networks.is_empty());
                    assert!(image.tables.db_levels.is_empty());
                    for network in image.project.networks.values() {
                        ids.insert(network.oid.clone());
                        ids.insert(network.interface_oid.clone());
                        ids.extend(network.units.values().map(|unit| unit.oid.clone()));
                    }
                    ids.extend(
                        image
                            .tables
                            .db_pending
                            .iter()
                            .map(|object| object.oid.clone()),
                    );
                }
                ids
            };
            assert!(canonical_ids.len() > expected_startup["known_oids"].as_array().unwrap().len());
            expected_startup["known_oids"] = serde_json::to_value(canonical_ids).unwrap();
            drop(service);
            service = Service::new(&fixture(), None, path.clone(), pci.clone(), None).unwrap();
            owner = ClientState::default();
            assert_eq!(
                projection(&Database::from_server(&*service.model.lock().await)),
                expected_startup
            );
            let after_startup = std::fs::read(&path).unwrap();
            assert_ne!(after_startup, before_startup);
            assert_eq!(
                serde_json::from_slice::<serde_json::Value>(&after_startup).unwrap(),
                expected_startup
            );
        }
        for command in [
            "PP LOCK OWNER //HARNESS/254",
            "PP START OWNED OWNER",
            "PP NEW OWNED KEYGL5 5.5.00",
            "PP SET OWNED Witness Retained",
        ] {
            let response = service.handle(&mut owner, &format!("[2] {command}")).await;
            assert!(response.status < 400, "{command}: {response:?}");
        }
        let old_bytes = std::fs::read(&path).unwrap();
        let old_image: serde_json::Value = serde_json::from_slice(&old_bytes).unwrap();
        let before = {
            let mut model = service.model.lock().await;
            let network = model
                .projects
                .get_mut("HARNESS")
                .unwrap()
                .networks
                .get_mut(&254)
                .unwrap();
            assert_eq!(network.oid.is_empty(), shell);
            network.physical.insert(5, physical_unit);
            network.levels.insert((56, 1), 143);
            network.state = NetworkState::Open;
            network.retries = 7;
            model
                .db_fields
                .insert("//HARNESS/Description".into(), "Repair witness".into());
            model.clone()
        };
        let mut staged_image = old_image.clone();
        staged_image["db_fields"]["//HARNESS/Description"] = serde_json::json!("Repair witness");
        assert_eq!(projection(&Database::from_server(&before)), staged_image);
        let fault = point.map(|point| repository_io::inject_failure(&path, point));
        let response = service
            .handle(&mut owner, "[37] PROJECT REPAIR HARNESS")
            .await;
        drop(fault);
        let pre_rename = point == Some(repository_io::FailurePoint::BeforeRename);
        let expected_text = match point {
            None => "200 OK.",
            Some(repository_io::FailurePoint::BeforeRename) => {
                "500 Project repair commit failed; change rolled back"
            }
            Some(repository_io::FailurePoint::DirectorySync) => UNCERTAIN,
        };
        assert_eq!(
            response.final_text, expected_text,
            "shell={shell}, point={point:?}"
        );
        let wire_key = match point {
            None => "repair_success",
            Some(repository_io::FailurePoint::BeforeRename) => "pre_rename_repair",
            Some(repository_io::FailurePoint::DirectorySync) => "post_rename",
        };
        assert_eq!(
            crate::format_response(&response),
            vector[wire_key].as_str().unwrap()
        );
        let model = service.model.lock().await;
        assert_eq!(model.sessions, before.sessions);
        assert_eq!(model.locks, before.locks);
        assert_eq!(
            model.projects["HARNESS"].networks[&254],
            before.projects["HARNESS"].networks[&254]
        );
        assert_eq!(projection(&Database::from_server(&model)), staged_image);
        drop(model);
        let current_bytes = std::fs::read(&path).unwrap();
        assert_eq!(
            serde_json::from_slice::<serde_json::Value>(&current_bytes).unwrap(),
            if pre_rename { old_image } else { staged_image }
        );
        if pre_rename {
            assert_eq!(current_bytes, old_bytes);
        } else {
            assert_ne!(current_bytes, old_bytes);
        }
        assert!(owner.sessions.contains("OWNED"));
        assert!(owner.locks.contains("OWNER"));
        let mut foreign = ClientState::default();
        assert_eq!(
            service
                .handle(&mut foreign, "[4] PP GET OWNED Witness")
                .await
                .status,
            420
        );
        assert_eq!(
            service
                .handle(&mut owner, "[6] PP GET OWNED Witness")
                .await
                .final_text,
            "315 Witness=Retained"
        );
        assert_eq!(std::fs::read(&path).unwrap(), current_bytes);
        assert_eq!(std::fs::read_dir(&directory).unwrap().count(), 1);
        assert!(
            tokio::time::timeout(Duration::from_millis(10), remote.read_u8())
                .await
                .is_err()
        );
        drop(service);
        let restarted = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
        let model = restarted.model.lock().await;
        assert_eq!(
            projection(&Database::from_server(&model)),
            serde_json::from_slice::<serde_json::Value>(&current_bytes).unwrap()
        );
        assert_eq!(
            model.projects["HARNESS"].networks[&254].oid.is_empty(),
            shell
        );
        assert!(model.projects["HARNESS"].networks[&254].physical.is_empty());
        assert!(model.projects["HARNESS"].networks[&254].levels.is_empty());
        assert!(model.sessions.is_empty());
        assert!(model.locks.is_empty());
        drop(model);
        assert_eq!(std::fs::read(&path).unwrap(), current_bytes);
        std::fs::remove_dir_all(directory).unwrap();
    }
}
