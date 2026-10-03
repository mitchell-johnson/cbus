use super::*;

fn large_fixture() -> String {
    let payload = "0123456789abcdef".repeat(4 * 1024);
    let units = (5..9).map(|address| format!(
        r#"<Unit><Address>{address}</Address><TagName>Large Synthetic</TagName><UnitType>KEYGL5</UnitType><FirmwareVersion>5.5.00</FirmwareVersion>
          <PP Name="PayloadA" Value="{payload}"/><PP Name="PayloadB" Value="{payload}"/>
          <Opaque>retained synthetic extension</Opaque>
        </Unit>"#
    )).collect::<String>();
    format!(
        r#"<Installation><Project><TagName>CAPACITY</TagName>
      <Network><Address>254</Address><TagName>Local</TagName>
        <Interface><InterfaceType>CNI</InterfaceType><InterfaceAddress>127.0.0.1:10001</InterfaceAddress></Interface>
        {units}
      </Network></Project></Installation>"#
    )
}

#[tokio::test]
async fn sixteen_large_backups_remain_simultaneous_and_reload_after_restart() {
    let xml = large_fixture();
    let path = state_path();
    let (pci, mut remote) = pci();
    let service = Service::new(&xml, None, path.clone(), pci.clone(), None).unwrap();
    let mut owner = ClientState::default();
    assert_eq!(
        service
            .handle(&mut owner, "[lock] PP LOCK OWNER //CAPACITY/254")
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut owner, "[start] PP START OWNED OWNER")
            .await
            .status,
        200
    );
    let mut other = ClientState::default();
    let source = service
        .handle(&mut owner, "[source] DBGETXML //CAPACITY/254")
        .await;
    assert_eq!(source.status, 200);
    let physical = {
        let mut model = service.model.lock().await;
        let network = model
            .projects
            .get_mut("CAPACITY")
            .unwrap()
            .networks
            .get_mut(&254)
            .unwrap();
        network.physical.insert(5, network.units[&5].clone());
        network.levels.insert((56, 27), 143);
        network.physical.clone()
    };
    let mut sizes = Vec::new();
    for index in 0..16 {
        let project = format!("BACKUP{index:02}");
        let response = service
            .handle(
                &mut owner,
                &format!("[copy{index}] PROJECT COPY CAPACITY {project}"),
            )
            .await;
        assert_eq!(response.status, 200, "{project}: {:?}", response.final_text);
        assert_eq!(
            service
                .handle(&mut owner, &format!("[save{index}] PROJECT SAVE {project}"))
                .await
                .status,
            200
        );
        owner.current = Some(project.clone());
        let copied = service
            .handle(
                &mut owner,
                &format!("[read{index}] DBGETXML //{project}/254"),
            )
            .await;
        assert_eq!(copied.status, 200);
        assert_eq!(copied.lines, source.lines);
        sizes.push(std::fs::metadata(&path).unwrap().len());
        let model = service.model.lock().await;
        assert_eq!(model.projects["CAPACITY"].networks[&254].physical, physical);
        assert_eq!(
            model.projects["CAPACITY"].networks[&254]
                .levels
                .get(&(56, 27)),
            Some(&143)
        );
        assert!(model.projects[&project].networks[&254].physical.is_empty());
    }
    let final_bytes = *sizes.last().unwrap();
    assert!(
        final_bytes > 32 * 1024 * 1024,
        "workload must reproduce old limit: {sizes:?}"
    );
    assert!(final_bytes <= repository_io::MAX_BYTES);
    assert!(sizes.windows(2).all(|pair| pair[1] > pair[0]));
    assert_eq!(
        service
            .handle(&mut other, "[foreign] PP GET OWNED PayloadA")
            .await
            .status,
        420
    );
    assert_eq!(owner.sessions.with(|sessions| sessions.len()), 1);
    assert_eq!(owner.locks.with(|locks| locks.len()), 1);
    let snapshots = REPOSITORY_SNAPSHOTS.with(|count| count.get());
    let persisted = std::fs::read(&path).unwrap();
    for index in 0..16 {
        other.current = Some(format!("BACKUP{index:02}"));
        for text in [
            format!("DBGETXML //BACKUP{index:02}/254"),
            format!("DBGET //BACKUP{index:02}/254/p/5/TagName"),
            "DBGETXML //MISSING/254".to_string(),
            "DBGETXML".to_string(),
        ] {
            let _ = service
                .handle(&mut other, &format!("[readonly] {text}"))
                .await;
        }
    }
    assert_eq!(REPOSITORY_SNAPSHOTS.with(|count| count.get()), snapshots);
    assert_eq!(std::fs::read(&path).unwrap(), persisted);
    let mut byte = [0];
    assert!(
        tokio::time::timeout(Duration::from_millis(10), remote.read(&mut byte))
            .await
            .is_err()
    );
    drop(service);
    let restarted = Service::new(&xml, None, path.clone(), pci, None).unwrap();
    let mut client = ClientState::default();
    for index in 0..16 {
        let project = format!("BACKUP{index:02}");
        assert_eq!(
            restarted
                .handle(&mut client, &format!("[load] PROJECT LOAD {project}"))
                .await
                .status,
            200
        );
        let readback = restarted
            .handle(&mut client, &format!("[reload] DBGETXML //{project}/254"))
            .await;
        assert_eq!(readback.status, 200);
        assert_eq!(readback.lines, source.lines);
    }
    let model = restarted.model.lock().await;
    assert_eq!(model.projects.len(), 17);
    assert_eq!(model.saved_projects.len(), 17);
    assert!(model.sessions.is_empty());
    assert!(model.locks.is_empty());
    assert!(model.projects["CAPACITY"].networks[&254]
        .physical
        .is_empty());
    assert!(model.projects["CAPACITY"].networks[&254].levels.is_empty());
    drop(model);
    println!("capacity workload: sixteen simultaneous backups, {final_bytes} serialized bytes; all 64 DBGET/DBGETXML reads snapshot-free; fresh restart retains all seventeen saved graphs");
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn failed_stream_commit_rolls_back_model_and_preserves_owned_session() {
    let directory = state_path().with_extension("directory");
    std::fs::create_dir(&directory).unwrap();
    let path = directory.join("state.json");
    let (pci, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let mut owner = ClientState::default();
    assert_eq!(
        service
            .handle(&mut owner, "[lock] PP LOCK OWNER //HARNESS/254")
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut owner, "[start] PP START OWNED OWNER")
            .await
            .status,
        200
    );
    let before = service.model.lock().await.clone();
    let persisted = std::fs::read(&path).unwrap();
    std::fs::remove_file(&path).unwrap();
    std::fs::create_dir(&path).unwrap();
    std::fs::write(path.join("old-image"), &persisted).unwrap();
    let failed = service
        .handle(&mut owner, "[copy] PROJECT COPY HARNESS REFUSED")
        .await;
    assert_eq!(failed.status, 500);
    let after = service.model.lock().await;
    assert!(Database::from_server(&before) == Database::from_server(&after));
    assert!(!after.projects.contains_key("REFUSED"));
    assert!(after.sessions.contains_key("OWNED"));
    assert!(after.locks.contains_key("OWNER"));
    drop(after);
    assert!(owner.sessions.contains("OWNED"));
    assert!(owner.locks.contains("OWNER"));
    assert_eq!(std::fs::read(path.join("old-image")).unwrap(), persisted);
    assert_eq!(std::fs::read_dir(&directory).unwrap().count(), 1);
    std::fs::remove_dir_all(directory).unwrap();
}

#[tokio::test]
async fn oversized_repository_is_rejected_before_deserialization_and_never_reset() {
    let path = state_path();
    let file = std::fs::File::create(&path).unwrap();
    file.set_len(repository_io::MAX_BYTES + 1).unwrap();
    let (pci, _remote) = pci();
    let error = match Service::new(&fixture(), None, path.clone(), pci, None) {
        Ok(_) => panic!("oversized repository must refuse startup"),
        Err(error) => error,
    };
    assert!(error.to_string().contains("exceeds"));
    assert_eq!(
        std::fs::metadata(&path).unwrap().len(),
        repository_io::MAX_BYTES + 1
    );
    std::fs::remove_file(path).unwrap();
}
