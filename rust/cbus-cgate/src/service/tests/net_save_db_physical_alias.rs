use super::*;

async fn setup() -> (Arc<Service>, BufReader<tokio::io::DuplexStream>, PathBuf) {
    let (pci, remote) = pci();
    pci.pci_reset().await.unwrap();
    let mut remote = BufReader::new(remote);
    for _ in 0..8 {
        database_pci_line(&mut remote).await;
    }
    let xml = fixture().replace(
        "</Network>",
        r#"<Unit oid="dali-gateway-20"><Address>20</Address><TagName>DALI Gateway</TagName><UnitType>SYS_DAL2</UnitType><FirmwareVersion>1.10.0</FirmwareVersion><SerialNumber>101136.1558</SerialNumber></Unit></Network>"#,
    );
    let path = state_path();
    let service = Service::new(&xml, None, path.clone(), pci, None).unwrap();
    (service, remote, path)
}

async fn run(service: &Arc<Service>, command: &str) -> Response {
    service
        .handle(
            &mut ClientState::default(),
            &format!("[physical-alias] {command}"),
        )
        .await
}

async fn independent_alias(service: &Arc<Service>) {
    for command in ["NET CREATE 0254 cni 127.0.0.1:1", "NET SAVE DB"] {
        let response = run(service, command).await;
        assert_eq!(response.status, 200, "{command}: {response:?}");
    }
    assert!(
        service.model.lock().await.projects["HARNESS"].tag_networks["0254"]
            .database_network
            .is_none()
    );
}

// Observe the actual service dispatch and fail immediately if it reaches the
// controlled PCI. The pre-fix failure retains the emitted wire in the test log.
async fn no_io_response(
    service: &Arc<Service>,
    remote: &mut BufReader<tokio::io::DuplexStream>,
    command: &str,
) -> Response {
    let mut request = tokio::spawn({
        let service = service.clone();
        let command = command.to_string();
        async move { run(&service, &command).await }
    });
    let response = tokio::select! {
        response = &mut request => response.unwrap(),
        wire = database_pci_line(remote) => {
            request.abort();
            panic!("{command} reached configured PCI: {}", String::from_utf8_lossy(&wire));
        }
    };
    assert!(
        tokio::time::timeout(Duration::from_millis(20), remote.read_u8())
            .await
            .is_err(),
        "{command} left PCI traffic after response: {response:?}"
    );
    response
}

async fn reject(
    service: &Arc<Service>,
    remote: &mut BufReader<tokio::io::DuplexStream>,
    command: &str,
) {
    let response = no_io_response(service, remote, command).await;
    assert_eq!(response.status, 404, "{command}: {response:?}");
    assert_eq!(
        response.final_text,
        "404 Named database Network is not connected to a physical interface"
    );
}

#[tokio::test(start_paused = true)]
async fn net_save_db_physical_alias_dali_known_is_rejected_before_wire() {
    let (service, mut remote, path) = setup().await;
    independent_alias(&service).await;
    reject(
        &service,
        &mut remote,
        "DALI KNOWN EXEC //HARNESS/0254/p/20 B",
    )
    .await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test(start_paused = true)]
async fn net_save_db_physical_alias_dali_address_unknown_is_rejected_before_wire() {
    let (service, mut remote, path) = setup().await;
    independent_alias(&service).await;
    reject(
        &service,
        &mut remote,
        "DALI ADDRESS_UNKNOWN EXEC //HARNESS/0254/p/20 B",
    )
    .await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test(start_paused = true)]
async fn net_save_db_physical_alias_dali_specialized_and_emergency_targets_are_rejected() {
    let (service, mut remote, path) = setup().await;
    independent_alias(&service).await;
    assert_eq!(run(&service, "DALI SESSION NEW work").await.status, 200);
    for command in [
        "DALI KNOWN //HARNESS/0254/p/20 B",
        "DALI EMERGENCY REST EXEC //HARNESS/0254/p/20 A",
        "DALI GATEWAY FACTORY_RESET EXEC //HARNESS/0254/p/20",
        "DALI GATEWAY READ_EXTENDED_PARAMETERS //HARNESS/0254/p/20",
        "DALI GATEWAY SET_EXTENDED_PARAMETERS //HARNESS/0254/p/20 256 170",
        "DALI ERROR_REPORTING STORE_OPTION //HARNESS/0254/p/20",
        "DALI ERROR_REPORTING SET_STORE_OPTION //HARNESS/0254/p/20 170",
        "DALI MEASUREMENT LAMP_RUNNING_TIME //HARNESS/0254/p/20 A 0",
        "DALI MEASUREMENT SET_REQUEST_TRIGGER_GROUP //HARNESS/0254/p/20 170",
        "DALI SESSION EXTRACT work //HARNESS/0254/p/20 A EXT_ONLY",
        "DALI SESSION DEPLOY work //HARNESS/0254/p/20 A EXT_ONLY",
    ] {
        reject(&service, &mut remote, command).await;
    }
    std::fs::remove_file(path).unwrap();
}

async fn upload_manifest(service: &Arc<Service>) {
    assert_eq!(
        run(service, "FILE MKDIR %HARNESS%/patchsets").await.status,
        200
    );
    let manifest = r#"{"schema":"cmqttd.pp-patch/v1","version":"physical-alias-test","patches":[{"unitType":"KEYGL5","minFirmware":"5.0","maxFirmware":"6.0","patchVersion":"01","currentPatchVersions":["00"],"blocks":[{"parameter":114,"dataHex":"aabb"}]}]}"#;
    let response = service
        .handle_document(
            &mut ClientState::default(),
            "[upload] FILE UPLOAD %HARNESS%/patchsets/cmqttd-patches.json",
            &base64::engine::general_purpose::STANDARD.encode(manifest),
        )
        .await;
    assert_eq!(response.status, 200, "{response:?}");
}

#[tokio::test(start_paused = true)]
async fn net_save_db_physical_alias_pp_patch_is_rejected_before_manifest_or_wire() {
    let (service, mut remote, path) = setup().await;
    independent_alias(&service).await;
    // Authorization still runs before the independent-ownership rejection.
    service.model.lock().await.allow_programming = false;
    assert_eq!(
        no_io_response(
            &service,
            &mut remote,
            "PP WRITE_PATCH //HARNESS/0254/p/5 01"
        )
        .await
        .status,
        420
    );
    service.model.lock().await.allow_programming = true;
    reject(
        &service,
        &mut remote,
        "PP WRITE_PATCH //HARNESS/0254/p/5 01 SIMULATE",
    )
    .await;
    upload_manifest(&service).await;
    for command in [
        "PP WRITE_PATCH //HARNESS/0254/p/5 01",
        "PP WRITE_PATCH //HARNESS/0254/p/5 01 SIMULATE",
    ] {
        reject(&service, &mut remote, command).await;
    }
    std::fs::remove_file(path).unwrap();
}

#[tokio::test(start_paused = true)]
async fn net_save_db_physical_alias_pp_patch_with_manifest_is_rejected_before_wire() {
    let (service, mut remote, path) = setup().await;
    independent_alias(&service).await;
    upload_manifest(&service).await;
    reject(
        &service,
        &mut remote,
        "PP WRITE_PATCH //HARNESS/0254/p/5 01",
    )
    .await;
    std::fs::remove_file(path).unwrap();
}

#[tokio::test(start_paused = true)]
async fn net_save_db_physical_alias_legacy_spellings_still_reach_configured_gateway_and_patch_admission(
) {
    let (service, mut remote, path) = setup().await;
    independent_alias(&service).await;
    // Only the exact 0254 spelling is independently owned. Other historical
    // decimal aliases must retain the configured gateway behavior.
    for target in [
        "//HARNESS/254/p/20",
        "//HARNESS/00254/p/20",
        "!dali-gateway-20",
    ] {
        let request = tokio::spawn({
            let service = service.clone();
            let command = format!("DALI KNOWN EXEC {target} B");
            async move { run(&service, &command).await }
        });
        assert_eq!(database_pci_line(&mut remote).await, b"\\061400E381DA87\r");
        let mut reply = vec![0x86, 20, 0x10, 0x00, 0xe6, 0x83, 0xda, 0x87, 0, 0xaa, 0x55];
        let sum = reply.iter().fold(0u8, |sum, byte| sum.wrapping_add(*byte));
        reply.push(0u8.wrapping_sub(sum));
        remote
            .get_mut()
            .write_all(format!("{}\r\n", hex::encode_upper(reply)).as_bytes())
            .await
            .unwrap();
        let response = request.await.unwrap();
        assert_eq!(response.status, 200, "{target}: {response:?}");
        assert!(response
            .lines
            .contains(&"320-ResponsePayload=AA55".to_string()));
    }
    let missing = no_io_response(
        &service,
        &mut remote,
        "PP WRITE_PATCH //HARNESS/00254/p/5 01 SIMULATE",
    )
    .await;
    assert_eq!(missing.status, 408, "{missing:?}");
    assert!(missing.final_text.contains("No patch manifest"));
    upload_manifest(&service).await;
    for target in ["//HARNESS/254/p/5", "//HARNESS/00254/p/5"] {
        let response = no_io_response(
            &service,
            &mut remote,
            &format!("PP WRITE_PATCH {target} 01 SIMULATE"),
        )
        .await;
        assert_eq!(response.status, 200, "{target}: {response:?}");
        assert!(response
            .lines
            .iter()
            .any(|line| line.contains("physical-alias-test sha256")));
    }
    std::fs::remove_file(path).unwrap();
}
