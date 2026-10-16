//! Exact-path, post-rename faults prove recovery without damaging a filesystem.
use super::*;

fn uncertain(response: &Response) {
    let vector: serde_json::Value = serde_json::from_str(include_str!(
        "../../../../testdata/vectors/cgate_repository_uncertainty.json"
    ))
    .unwrap();
    assert_eq!(response.status, vector["status"].as_u64().unwrap() as u16);
    assert_eq!(response.final_text, vector["final"].as_str().unwrap());
    assert!(response.lines.is_empty());
}

async fn agrees_with_disk(service: &Service, path: &Path) -> Database {
    let disk: Database = repository_io::load(path).unwrap();
    assert_eq!(
        serde_json::to_value(&disk).unwrap(),
        serde_json::to_value(Database::from_server(&*service.model.lock().await)).unwrap()
    );
    disk
}

#[tokio::test]
async fn applied_uncertain_commits_preserve_all_local_families_and_restart() {
    let cases: &[(&str, &[&str])] = &[
        ("DBSETSAFE //HARNESS/254/p/5/TagName Applied", &[]),
        ("PROJECT NEW APPLIED", &[]),
        ("CONFIG SET heartbeat-time 7", &[]),
        ("FILE MKDIR applied", &[]),
        ("NET CREATE ADDED cni 127.0.0.1:10002", &[]),
        ("ACCESS ADD user synthetic owned-test-password Monitor", &[]),
        (
            "ACCESS DELETE 1",
            &["ACCESS ADD user synthetic owned-test-password Monitor"],
        ),
        (
            "ACCESS SAVE applied",
            &["ACCESS ADD user synthetic owned-test-password Monitor"],
        ),
        (
            "ACCESS LOAD applied",
            &[
                "ACCESS ADD user synthetic owned-test-password Monitor",
                "ACCESS SAVE applied",
                "ACCESS ADD user later owned-later-password Monitor",
            ],
        ),
        ("PROJECT REPAIR HARNESS", &[]),
        ("TRANSFORM PROJECT HARNESS", &[]),
        ("LOG EXTRACT 1 applied.log", &["NOOP"]),
        ("SCENE RECORD house applied", &[]),
        (
            "PP SAVE_TO_SOURCE OWNED",
            &[
                "PP LOCK OWNER //HARNESS/254",
                "PP START OWNED OWNER",
                "PP LOAD OWNED /db//HARNESS/254/p/5",
                "PP SET OWNED StaticTextString0 Applied",
            ],
        ),
    ];
    for (command, setup) in cases {
        let path = state_path();
        let (pci, mut remote) = pci();
        let service = Service::new(&fixture(), None, path.clone(), pci.clone(), None).unwrap();
        let mut client = ClientState {
            current: Some("HARNESS".to_string()),
            ..Default::default()
        };
        for command in *setup {
            let response = service
                .handle(&mut client, &format!("[setup] {command}"))
                .await;
            assert!(response.status < 400, "{command}: {response:?}");
        }
        let before = std::fs::read(&path).unwrap();
        let _fault = repository_io::fail_next_directory_sync(&path);
        let response = service
            .handle(&mut client, &format!("[fault] {command}"))
            .await;
        uncertain(&response);
        let applied = agrees_with_disk(&service, &path).await;
        if !command.contains("REPAIR") && !command.starts_with("TRANSFORM PROJECT") {
            assert_ne!(std::fs::read(&path).unwrap(), before, "{command}");
        }
        assert!(
            client.current == service.model.lock().await.current,
            "{command}"
        );
        if command.starts_with("PP SAVE") {
            assert!(client.sessions.contains("OWNED"));
            assert!(client.locks.contains("OWNER"));
        }
        assert!(
            tokio::time::timeout(Duration::from_millis(5), remote.read_u8())
                .await
                .is_err(),
            "local recovery touched PCI: {command}"
        );
        let mut expected_restart = serde_json::to_value(&applied).unwrap();
        if *command == "PROJECT NEW APPLIED" {
            let config = expected_restart["config_values"].as_object_mut().unwrap();
            for (suffix, value) in [
                ("active", "[]"),
                ("snapshot/db", "[]"),
                ("db-source-materialized", "true"),
            ] {
                config.insert(
                    format!("@cmqttd/net-catalog/v1/4150504c494544/{suffix}"),
                    value.into(),
                );
            }
        }
        drop(service);
        let restarted = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
        assert_eq!(
            expected_restart,
            serde_json::to_value(agrees_with_disk(&restarted, &path).await).unwrap(),
            "{command}"
        );
        std::fs::remove_file(path).unwrap();
    }
}

#[tokio::test]
async fn uncertain_document_commits_keep_xml_and_pending_events() {
    let path = state_path();
    let (pci, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let mut client = ClientState {
        current: Some("HARNESS".to_string()),
        ..Default::default()
    };
    let oid = service.model.lock().await.projects["HARNESS"].networks[&254].units[&5]
        .oid
        .clone();
    let document = format!(
        "<Unit><OID>{oid}</OID><Address>5</Address><TagName>Applied</TagName><UnitType>KEYGL5</UnitType><UnitName>Applied</UnitName><FirmwareVersion>5.5.00</FirmwareVersion></Unit>"
    );
    {
        let _fault = repository_io::fail_next_directory_sync(&path);
        uncertain(
            &service
                .handle_document(&mut client, "[xml] DBSETXML //HARNESS/254/p/5", &document)
                .await,
        );
    }
    agrees_with_disk(&service, &path).await;
    assert!(service
        .handle(&mut client, "[read] DBGETXML //HARNESS/254/p/5")
        .await
        .lines[0]
        .contains("<TagName>Applied</TagName>"));
    let cgl = r#"{"cglVersion":"1.1","localNetwork":254,"networks":[{"address":254,"name":"Local","applications":[{"address":56,"type":56,"name":"Lighting","groups":[{"address":27,"name":"Applied CGL"}]}]}]}"#;
    let mut events = service.events.subscribe();
    service
        .model
        .lock()
        .await
        .push_event("#e# db synthetic pending event".to_string());
    {
        let _fault = repository_io::fail_next_directory_sync(&path);
        uncertain(
            &service
                .handle_document(&mut client, "[cgl] CGL IMPORT HARNESS", cgl)
                .await,
        );
    }
    agrees_with_disk(&service, &path).await;
    let readback = service
        .handle(&mut client, "[read] CGL EXPORT HARNESS 254 56")
        .await;
    assert!(
        readback
            .lines
            .iter()
            .any(|line| line.contains("Applied CGL")),
        "{readback:?}"
    );
    assert!(service.model.lock().await.drain_events().is_empty());
    assert!(
        events.try_recv().is_ok(),
        "committed events must be delivered"
    );
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn uncertain_project_delete_finishes_client_and_startup_bookkeeping() {
    let path = state_path();
    let (pci, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let mut prepare = ClientState::default();
    assert_eq!(
        service
            .handle(&mut prepare, "[config] CONFIG SET project.start HARNESS")
            .await
            .status,
        200
    );
    let pci = service.pci.read().await.clone();
    drop(service);
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    assert!(service.startup_projects.is_some());
    let mut client = ClientState {
        current: Some("HARNESS".to_string()),
        ..Default::default()
    };
    assert_eq!(
        service
            .handle(&mut client, "[new] PROJECT NEW SECOND")
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut client, "[use] PROJECT USE SECOND")
            .await
            .status,
        200
    );
    let _fault = repository_io::fail_next_directory_sync(&path);
    uncertain(
        &service
            .handle(&mut client, "[delete] PROJECT DELETE SECOND")
            .await,
    );
    assert!(client.current.is_none());
    assert!(!service.model.lock().await.projects.contains_key("SECOND"));
    let startup = service.startup_projects.as_ref().unwrap().lock().await;
    assert!(!startup.contains_key("SECOND"));
    assert!(startup.contains_key("HARNESS"));
    drop(startup);
    agrees_with_disk(&service, &path).await;
    std::fs::remove_file(path).unwrap();
}

#[test]
fn post_rename_error_is_classified_once_and_does_not_replace_again() {
    let path = state_path();
    repository_io::save(&path, &serde_json::json!({"old":true})).unwrap();
    let _fault = repository_io::fail_next_directory_sync(&path);
    let error = repository_io::save(&path, &serde_json::json!({"applied":true})).unwrap_err();
    assert!(repository_io::commit_applied(&error));
    let value: serde_json::Value = repository_io::load(&path).unwrap();
    assert_eq!(value, serde_json::json!({"applied":true}));
    assert!(!repository_io::commit_applied(&io::Error::other(
        "directory sync failed"
    )));
    // The one-shot hook was consumed; an explicitly new independent save works.
    repository_io::save(&path, &serde_json::json!({"later":true})).unwrap();
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn post_rename_tcp_reply_is_exact_and_fresh_connection_reads_applied_state() {
    let path = state_path();
    let (pci, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let server = tokio::spawn(service.clone().serve(listener));
    let (mut reader, mut writer) = connect_command_session(address).await;
    {
        let _fault = repository_io::fail_next_directory_sync(&path);
        let response = command_lines(
            &mut reader,
            &mut writer,
            "fault",
            "DBSETSAFE //HARNESS/254/p/5/TagName Applied TCP",
        )
        .await;
        let vector: serde_json::Value = serde_json::from_str(include_str!(
            "../../../../testdata/vectors/cgate_repository_uncertainty.json"
        ))
        .unwrap();
        assert_eq!(
            format!("{}\r\n", response.join("\r\n")),
            vector["wire"].as_str().unwrap()
        );
    }
    drop(writer);
    drop(reader);
    let (mut reader, mut writer) = connect_command_session(address).await;
    let response = command_lines(
        &mut reader,
        &mut writer,
        "read",
        "DBGETXML //HARNESS/254/p/5",
    )
    .await;
    assert!(response
        .iter()
        .any(|line| line.contains("<TagName>Applied TCP</TagName>")));
    agrees_with_disk(&service, &path).await;
    assert!(
        tokio::time::timeout(Duration::from_millis(5), remote.read_u8())
            .await
            .is_err()
    );
    drop(writer);
    drop(reader);
    server.abort();
    let _ = server.await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn post_rename_transform_keeps_portable_artifact_and_file_upload() {
    let path = state_path();
    let (pci, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let mut client = ClientState::default();
    {
        let _fault = repository_io::fail_next_directory_sync(&path);
        let encoded = base64::engine::general_purpose::STANDARD.encode(fixture());
        uncertain(
            &service
                .handle_document(&mut client, "[upload] FILE UPLOAD source.xml", &encoded)
                .await,
        );
    }
    agrees_with_disk(&service, &path).await;
    {
        let _fault = repository_io::fail_next_directory_sync(&path);
        uncertain(
            &service
                .handle(&mut client, "[transform] TRANSFORM XML_TO_SQL source")
                .await,
        );
    }
    agrees_with_disk(&service, &path).await;
    let model = service.model.lock().await;
    assert!(crate::file::read_bytes(&model, "source.db")
        .unwrap()
        .starts_with(b"SQLite format 3\0"));
    assert_eq!(
        crate::file::read_bytes(&model, "source.xml").unwrap(),
        fixture().as_bytes()
    );
    drop(model);
    std::fs::remove_file(path).unwrap();
}
