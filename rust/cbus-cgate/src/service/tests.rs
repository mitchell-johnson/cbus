use super::*;
use base64::Engine as _;
use tokio::io::{AsyncBufReadExt, AsyncReadExt, AsyncWriteExt, BufReader};

#[test]
fn imported_project_dlt_metadata_and_spaced_pp_names_survive_dbgetxml_and_upgrade() {
    let xml = r#"<Installation><Project><TagName>SYNTH</TagName>
      <Network><TagName>Local</TagName><Address>254</Address>
        <Interface><InterfaceType>CNI</InterfaceType><InterfaceAddress>127.0.0.1:10001</InterfaceAddress></Interface>
        <Application><TagName>Lighting</TagName><Address>56</Address>
          <Group><TagName>Sample Group</TagName><Address>27</Address>
            <TagsDLT><TagDLT><LanguageID>1</LanguageID><FlavourID>1</FlavourID>
              <TagType>TEXT</TagType><TagValue>Synthetic Label</TagValue></TagDLT></TagsDLT>
          </Group>
        </Application>
        <Unit><TagName>Sample eDLT</TagName><Address>5</Address><UnitType>KEYGL5</UnitType>
          <FirmwareVersion>5.5.00</FirmwareVersion><SerialNumber>100.5</SerialNumber>
          <PP Name="EEPROM Checksum" Value="0x0"/>
        </Unit>
      </Network>
    </Project></Installation>"#;
    let (mut model, project, _) = import_project(xml, None).unwrap();
    seed_project_xml_metadata(&mut model, xml, &project).unwrap();
    let reply = model.handle("[xml] DBGETXML //SYNTH/254");
    assert_eq!(reply.status, 200);
    let document = reply.lines[0].strip_prefix("347-").unwrap();
    let parsed = roxmltree::Document::parse(document).unwrap();
    let label = parsed
        .descendants()
        .find(|node| node.has_tag_name("TagValue"))
        .unwrap();
    assert_eq!(label.text(), Some("Synthetic Label"));
    let pp = parsed
        .descendants()
        .find(|node| node.has_tag_name("PP"))
        .unwrap();
    assert_eq!(pp.attribute("Name"), Some("EEPROM Checksum"));
    assert_eq!(
        parsed
            .descendants()
            .filter(|node| node.has_tag_name("Group"))
            .count(),
        1
    );
    assert_eq!(
        model
            .handle("[rename] DBSETSAFE //SYNTH/254/56/27/TagName Updated")
            .status,
        200
    );
    let renamed = model.handle("[renamed] DBGETXML //SYNTH/254/56/27");
    let parsed =
        roxmltree::Document::parse(renamed.lines[0].strip_prefix("347-").unwrap()).unwrap();
    assert_eq!(
        parsed
            .root_element()
            .children()
            .find(|node| node.has_tag_name("TagName"))
            .and_then(|node| node.text()),
        Some("Updated")
    );
    let imported_group_oid = model
        .db_pending
        .values()
        .find(|object| object.path.as_deref() == Some("//SYNTH/254/56/27"))
        .unwrap()
        .oid
        .clone();
    let by_oid = model.handle(&format!("[oid] DBGET !{imported_group_oid}/TagName"));
    assert_eq!(
        by_oid.final_text,
        format!("342 !{imported_group_oid}/TagName=Updated")
    );
    assert_eq!(
        model
            .handle(&format!(
                "[rename-oid] DBSETSAFE !{imported_group_oid}/TagName OID Updated"
            ))
            .status,
        200
    );
    let by_path = model.handle("[path] DBGETXML //SYNTH/254/56/27");
    let parsed =
        roxmltree::Document::parse(by_path.lines[0].strip_prefix("347-").unwrap()).unwrap();
    assert_eq!(
        parsed
            .root_element()
            .children()
            .find(|node| node.has_tag_name("TagName"))
            .and_then(|node| node.text()),
        Some("OID Updated")
    );

    let durable = Database::from_server(&model);
    let mut legacy = serde_json::to_value(&durable).unwrap();
    let object = legacy.as_object_mut().unwrap();
    object.remove("imported_project_metadata");
    object.remove("unit_documents");
    object.remove("unit_pp_fields");
    object.remove("db_xml_extras");
    object.remove("db_pending");
    let legacy: Database = serde_json::from_value(legacy).unwrap();
    assert!(!legacy.imported_project_metadata);
    let (mut upgraded, project, _) = import_project(xml, None).unwrap();
    legacy.restore(&mut upgraded).unwrap();
    seed_project_xml_metadata(&mut upgraded, xml, &project).unwrap();
    let upgraded_reply = upgraded.handle("[upgraded] DBGETXML //SYNTH/254");
    assert_eq!(upgraded_reply.status, 200);
    let upgraded_document = upgraded_reply.lines[0].strip_prefix("347-").unwrap();
    let parsed = roxmltree::Document::parse(upgraded_document).unwrap();
    assert_eq!(
        parsed
            .descendants()
            .filter(|node| node.has_tag_name("TagDLT"))
            .count(),
        1
    );
    assert_eq!(
        parsed
            .descendants()
            .filter(|node| node.has_tag_name("PP"))
            .count(),
        1
    );
    seed_project_xml_metadata(&mut upgraded, xml, &project).unwrap();
    let repeated = upgraded.handle("[again] DBGETXML //SYNTH/254");
    let parsed =
        roxmltree::Document::parse(repeated.lines[0].strip_prefix("347-").unwrap()).unwrap();
    assert_eq!(
        parsed
            .descendants()
            .filter(|node| node.has_tag_name("TagDLT"))
            .count(),
        1
    );

    let group_oid = upgraded
        .db_pending
        .values()
        .find(|object| object.path.as_deref() == Some("//SYNTH/254/56/27"))
        .unwrap()
        .oid
        .clone();
    let key = Server::unit_document_key("SYNTH", &group_oid);
    upgraded.db_xml_extras.get_mut(&key).unwrap().children = vec![
        "<TagsDLT><TagDLT><LanguageID>1</LanguageID><FlavourID>1</FlavourID><TagType>TEXT</TagType><TagValue>Durable Edit</TagValue></TagDLT></TagsDLT>".to_string(),
    ];
    seed_project_xml_metadata(&mut upgraded, xml, &project).unwrap();
    let edited = upgraded.handle("[edited] DBGETXML //SYNTH/254");
    let parsed = roxmltree::Document::parse(edited.lines[0].strip_prefix("347-").unwrap()).unwrap();
    let values = parsed
        .descendants()
        .filter(|node| node.has_tag_name("TagValue"))
        .filter_map(|node| node.text())
        .collect::<Vec<_>>();
    assert_eq!(values, ["Durable Edit"]);
}

#[test]
fn imported_tagsdlt_materializes_inherited_namespace_prefix() {
    let xml = r#"<Installation><Project><TagName>SYNTH</TagName><Network xmlns:v="urn:example">
      <TagName>Local</TagName><Address>254</Address>
      <Application><TagName>Lighting</TagName><Address>56</Address>
        <Group><TagName>Sample</TagName><Address>27</Address>
          <TagsDLT><v:Note>opaque</v:Note><TagDLT><LanguageID>1</LanguageID>
            <FlavourID>1</FlavourID><TagType>TEXT</TagType><TagValue>Safe</TagValue>
          </TagDLT></TagsDLT>
        </Group>
      </Application>
    </Network></Project></Installation>"#;
    let (mut model, project, _) = import_project(xml, None).unwrap();
    seed_project_xml_metadata(&mut model, xml, &project).unwrap();
    let reply = model.handle("[xml] DBGETXML //SYNTH/254");
    let parsed = roxmltree::Document::parse(reply.lines[0].strip_prefix("347-").unwrap()).unwrap();
    assert_eq!(
        parsed
            .descendants()
            .filter(|node| node.has_tag_name("TagDLT"))
            .count(),
        1
    );
    let note = parsed
        .descendants()
        .find(|node| node.has_tag_name("Note"))
        .unwrap();
    assert_eq!(note.tag_name().namespace(), Some("urn:example"));
}

#[test]
fn imported_tagsdlt_with_default_namespace_fails_closed() {
    let xml = r#"<Installation><Project><TagName>SYNTH</TagName><Network>
      <TagName>Local</TagName><Address>254</Address>
      <Application><TagName>Lighting</TagName><Address>56</Address>
        <Group><TagName>Sample</TagName><Address>27</Address>
          <TagsDLT xmlns="urn:unexpected"><TagDLT><TagValue>Opaque</TagValue></TagDLT></TagsDLT>
        </Group>
      </Application>
    </Network></Project></Installation>"#;
    let (mut model, project, _) = import_project(xml, None).unwrap();
    let error = seed_project_xml_metadata(&mut model, xml, &project).unwrap_err();
    assert!(error.to_string().contains("default namespace"));
}

#[test]
fn empty_tagsdlt_with_inherited_prefix_remains_well_formed() {
    let xml = r#"<Installation><Project><TagName>SYNTH</TagName>
      <Network xmlns:v="urn:example"><TagName>Local</TagName><Address>254</Address>
        <Application><TagName>Lighting</TagName><Address>56</Address>
          <Group><TagName>Sample</TagName><Address>27</Address><TagsDLT/></Group>
        </Application>
      </Network>
    </Project></Installation>"#;
    let (mut model, project, _) = import_project(xml, None).unwrap();
    seed_project_xml_metadata(&mut model, xml, &project).unwrap();
    let reply = model.handle("[xml] DBGETXML //SYNTH/254");
    let parsed = roxmltree::Document::parse(reply.lines[0].strip_prefix("347-").unwrap()).unwrap();
    assert_eq!(
        parsed
            .descendants()
            .filter(|node| node.has_tag_name("TagsDLT"))
            .count(),
        1
    );
}

#[test]
fn local_namespace_declaration_with_spaces_is_not_duplicated() {
    let xml = r#"<Installation><Project><TagName>SYNTH</TagName>
      <Network xmlns:v="urn:example"><TagName>Local</TagName><Address>254</Address>
        <Application><TagName>Lighting</TagName><Address>56</Address>
          <Group><TagName>Sample</TagName><Address>27</Address>
            <TagsDLT xmlns:v = "urn:example"><v:Note>kept</v:Note>
              <TagDLT><LanguageID>1</LanguageID><FlavourID>1</FlavourID>
                <TagType>TEXT</TagType><TagValue>Safe</TagValue></TagDLT>
            </TagsDLT>
          </Group>
        </Application>
      </Network>
    </Project></Installation>"#;
    let (mut model, project, _) = import_project(xml, None).unwrap();
    seed_project_xml_metadata(&mut model, xml, &project).unwrap();
    let reply = model.handle("[xml] DBGETXML //SYNTH/254");
    assert_eq!(reply.status, 200);
    let detached = reply.lines[0].strip_prefix("347-").unwrap();
    let parsed = roxmltree::Document::parse(detached).unwrap();
    assert_eq!(
        parsed
            .descendants()
            .filter(|node| node.has_tag_name("TagDLT"))
            .count(),
        1
    );
    assert!(!detached.contains("xmlns:v=\"urn:example\" xmlns:v"));
}

#[tokio::test]
async fn imported_unit_inherited_namespace_and_pp_extensions_survive_restart() {
    let xml = r#"<Installation><Project><TagName>SYNTH</TagName>
      <Network xmlns:v="urn:example"><TagName>Local</TagName><Address>254</Address>
        <Unit v:flag="kept"><TagName>Sample eDLT</TagName><Address>5</Address>
          <UnitType>KEYGL5</UnitType><FirmwareVersion>5.5.00</FirmwareVersion>
          <PP Name="EEPROM Checksum" Value="0x0" v:mark="yes"><v:Extra>nested</v:Extra></PP>
          <v:Opaque>preserved</v:Opaque>
        </Unit>
      </Network>
    </Project></Installation>"#;
    let path = state_path();
    let (pci, _remote) = pci();
    for _ in 0..2 {
        let service = Service::new(xml, None, path.clone(), pci.clone(), None).unwrap();
        let response = service
            .handle(&mut ClientState::default(), "[xml] DBGETXML //SYNTH/254")
            .await;
        assert_eq!(response.status, 200);
        let parsed =
            roxmltree::Document::parse(response.lines[0].strip_prefix("347-").unwrap()).unwrap();
        let unit = parsed
            .descendants()
            .find(|node| node.has_tag_name("Unit"))
            .unwrap();
        assert_eq!(unit.attribute(("urn:example", "flag")), Some("kept"));
        let pp = unit
            .children()
            .find(|node| node.has_tag_name("PP"))
            .unwrap();
        assert_eq!(pp.attribute("Name"), Some("EEPROM Checksum"));
        assert_eq!(pp.attribute(("urn:example", "mark")), Some("yes"));
        assert_eq!(
            pp.children()
                .find(|node| node.has_tag_name("Extra"))
                .and_then(|node| node.text()),
            Some("nested")
        );
        assert_eq!(
            unit.children()
                .find(|node| node.has_tag_name("Opaque"))
                .and_then(|node| node.text()),
            Some("preserved")
        );
    }
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn ambiguous_legacy_group_keeps_edits_and_disables_saved_label_capability() {
    let xml = r#"<Installation><Project><TagName>SYNTH</TagName><Network>
      <TagName>Local</TagName><Address>254</Address>
      <Application><TagName>Lighting</TagName><Address>56</Address>
        <Group><TagName>Source Group</TagName><Address>27</Address><TagsDLT><TagDLT>
          <LanguageID>1</LanguageID><FlavourID>1</FlavourID><TagType>TEXT</TagType>
          <TagValue>Source Label</TagValue></TagDLT></TagsDLT></Group>
      </Application>
    </Network></Project></Installation>"#;
    let path = state_path();
    let (mut legacy_model, project, _) = import_project(xml, None).unwrap();
    let group_path = "//SYNTH/254/56/27";
    seed_imported_object(
        &mut legacy_model,
        &project,
        "//SYNTH/254/56",
        group_path,
        "Group",
        27,
    )
    .unwrap();
    legacy_model.db_fields.insert(
        format!("{group_path}/TagName"),
        "Durable Rename".to_string(),
    );
    let mut legacy = serde_json::to_value(Database::from_server(&legacy_model)).unwrap();
    let fields = legacy.as_object_mut().unwrap();
    fields.remove("imported_project_metadata");
    fields.remove("saved_project_group_dlt_labels_complete");
    std::fs::write(&path, serde_json::to_vec(&legacy).unwrap()).unwrap();
    let (pci, _remote) = pci();
    let mut saved_bytes = None;
    for _ in 0..2 {
        let service = Service::new(xml, None, path.clone(), pci.clone(), None).unwrap();
        let mut client = ClientState::default();
        let capabilities = service
            .handle(&mut client, "[caps] CMQTT CAPABILITIES")
            .await;
        assert_eq!(capabilities.status, 200);
        let capabilities: serde_json::Value = serde_json::from_str(&capabilities.lines[0]).unwrap();
        assert_eq!(capabilities["saved_project_group_dlt_labels"], false);
        let xml_reply = service
            .handle(&mut client, "[xml] DBGETXML //SYNTH/254")
            .await;
        assert_eq!(xml_reply.status, 200);
        let parsed =
            roxmltree::Document::parse(xml_reply.lines[0].strip_prefix("347-").unwrap()).unwrap();
        assert_eq!(
            parsed
                .descendants()
                .filter(|node| node.has_tag_name("TagDLT"))
                .count(),
            0
        );
        assert!(xml_reply.lines[0].contains("Durable Rename"));
        assert_eq!(
            service.handle(&mut client, "[ver] APIVER").await.status,
            138
        );
        let current = std::fs::read(&path).unwrap();
        let stored: Database = serde_json::from_slice(&current).unwrap();
        assert!(stored.imported_project_metadata);
        assert!(!stored.saved_project_group_dlt_labels_complete);
        if let Some(previous) = saved_bytes.replace(current.clone()) {
            assert_eq!(current, previous);
        }
    }
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn deleting_imported_application_removes_descendant_dlt_without_touching_copy() {
    let xml = r#"<Installation><Project><TagName>SYNTH</TagName><Network>
      <TagName>Local</TagName><Address>254</Address>
      <Application><TagName>Lighting</TagName><Address>56</Address>
        <Group><TagName>Original</TagName><Address>27</Address><TagsDLT><TagDLT>
          <LanguageID>1</LanguageID><FlavourID>1</FlavourID><TagType>TEXT</TagType>
          <TagValue>Saved Tag</TagValue></TagDLT></TagsDLT></Group>
      </Application>
    </Network></Project></Installation>"#;
    let path = state_path();
    let (pci, _remote) = pci();
    let service = Service::new(xml, None, path.clone(), pci.clone(), None).unwrap();
    let group_oid = service
        .model
        .lock()
        .await
        .db_pending
        .values()
        .find(|object| object.path.as_deref() == Some("//SYNTH/254/56/27"))
        .unwrap()
        .oid
        .clone();
    let mut client = ClientState::default();
    assert_eq!(
        service
            .handle(&mut client, "[copy] PROJECT COPY SYNTH COPY")
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut client, "[use] PROJECT USE SYNTH")
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut client, "[delete] DBDELETE //SYNTH/254/56")
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut client, &format!("[stale] DBGETXML !{group_oid}"))
            .await
            .status,
        401
    );
    assert_eq!(
        service
            .handle(
                &mut client,
                "[recreate] DBADDSAFE //SYNTH/254 Application 56 Replacement"
            )
            .await
            .status,
        200
    );
    let after_recreate = service
        .handle(&mut client, "[no-tag] DBGETXML //SYNTH/254")
        .await;
    let parsed =
        roxmltree::Document::parse(after_recreate.lines[0].strip_prefix("347-").unwrap()).unwrap();
    assert_eq!(
        parsed
            .descendants()
            .filter(|node| node.has_tag_name("TagDLT"))
            .count(),
        0
    );
    assert_eq!(
        service
            .handle(&mut client, "[use] PROJECT USE COPY")
            .await
            .status,
        200
    );
    let copy = service
        .handle(&mut client, "[copy-xml] DBGETXML //COPY/254")
        .await;
    let parsed = roxmltree::Document::parse(copy.lines[0].strip_prefix("347-").unwrap()).unwrap();
    assert_eq!(
        parsed
            .descendants()
            .filter(|node| node.has_tag_name("TagDLT"))
            .count(),
        1
    );
    assert_eq!(
        service
            .handle(&mut client, &format!("[copy-oid] DBGETXML !{group_oid}"))
            .await
            .status,
        200
    );
    let saved = std::fs::read(&path).unwrap();
    drop(service);

    let restarted = Service::new(xml, None, path.clone(), pci, None).unwrap();
    assert_eq!(
        restarted
            .handle(&mut client, "[use] PROJECT USE SYNTH")
            .await
            .status,
        200
    );
    let source = restarted
        .handle(&mut client, "[source] DBGETXML //SYNTH/254")
        .await;
    let parsed = roxmltree::Document::parse(source.lines[0].strip_prefix("347-").unwrap()).unwrap();
    assert_eq!(
        parsed
            .descendants()
            .filter(|node| node.has_tag_name("TagDLT"))
            .count(),
        0
    );
    assert_eq!(
        restarted
            .handle(&mut client, "[use] PROJECT USE COPY")
            .await
            .status,
        200
    );
    let copy = restarted
        .handle(&mut client, "[copy] DBGETXML //COPY/254")
        .await;
    let parsed = roxmltree::Document::parse(copy.lines[0].strip_prefix("347-").unwrap()).unwrap();
    assert_eq!(
        parsed
            .descendants()
            .filter(|node| node.has_tag_name("TagDLT"))
            .count(),
        1
    );
    let before: serde_json::Value = serde_json::from_slice(&saved).unwrap();
    let after: serde_json::Value = serde_json::from_slice(&std::fs::read(&path).unwrap()).unwrap();
    for field in ["db_pending", "db_xml_extras", "db_fields"] {
        assert_eq!(after[field], before[field], "{field} changed after restart");
    }
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn legacy_state_file_upgrades_once_and_restart_keeps_project_dlt_xml() {
    let xml = r#"<Installation><Project><TagName>SYNTH</TagName><Network>
      <TagName>Local</TagName><Address>254</Address>
      <Application><TagName>Lighting</TagName><Address>56</Address>
        <Group><TagName>Sample</TagName><Address>27</Address><TagsDLT><TagDLT>
          <LanguageID>1</LanguageID><FlavourID>1</FlavourID><TagType>TEXT</TagType>
          <TagValue>Saved Tag</TagValue></TagDLT></TagsDLT></Group></Application>
      <Unit><Address>5</Address><TagName>Sample eDLT</TagName><UnitType>KEYGL5</UnitType>
        <FirmwareVersion>5.5.00</FirmwareVersion><PP Name="EEPROM Checksum" Value="0x0"/>
      </Unit>
    </Network></Project></Installation>"#;
    let path = state_path();
    let (legacy_model, _, _) = import_project(xml, None).unwrap();
    let mut legacy = serde_json::to_value(Database::from_server(&legacy_model)).unwrap();
    legacy
        .as_object_mut()
        .unwrap()
        .remove("imported_project_metadata");
    std::fs::write(&path, serde_json::to_vec(&legacy).unwrap()).unwrap();

    let (pci, _remote) = pci();
    let service = Service::new(xml, None, path.clone(), pci.clone(), None).unwrap();
    let mut client = ClientState::default();
    let response = service
        .handle(&mut client, "[first] DBGETXML //SYNTH/254")
        .await;
    let first_xml = response.lines[0].strip_prefix("347-").unwrap();
    let parsed = roxmltree::Document::parse(first_xml).unwrap();
    assert_eq!(
        parsed
            .descendants()
            .filter(|node| node.has_tag_name("TagDLT"))
            .count(),
        1
    );
    assert_eq!(
        parsed
            .descendants()
            .filter(|node| node.has_tag_name("PP"))
            .count(),
        1
    );
    let first_saved = std::fs::read(&path).unwrap();
    let saved: Database = serde_json::from_slice(&first_saved).unwrap();
    assert!(saved.imported_project_metadata);
    drop(service);

    let restarted = Service::new(xml, None, path.clone(), pci, None).unwrap();
    let response = restarted
        .handle(&mut client, "[again] DBGETXML //SYNTH/254")
        .await;
    let restarted_xml = response.lines[0].strip_prefix("347-").unwrap();
    let parsed = roxmltree::Document::parse(restarted_xml).unwrap();
    assert_eq!(
        parsed
            .descendants()
            .filter(|node| node.has_tag_name("TagDLT"))
            .count(),
        1
    );
    assert_eq!(
        parsed
            .descendants()
            .filter(|node| node.has_tag_name("PP"))
            .count(),
        1
    );
    assert_eq!(std::fs::read(&path).unwrap(), first_saved);
    std::fs::remove_file(path).unwrap();
}

/// Private acceptance is opt-in and uses caller-owned inputs only. It writes a
/// temporary copy of the durable state, never the supplied source file.
#[tokio::test]
#[ignore = "requires CBUS_PRIVATE_PROJECT_XML and CBUS_PRIVATE_CGATE_STATE"]
async fn private_existing_database_project_dlt_upgrade() {
    let xml = std::fs::read_to_string(std::env::var("CBUS_PRIVATE_PROJECT_XML").unwrap()).unwrap();
    let old_state = std::fs::read(std::env::var("CBUS_PRIVATE_CGATE_STATE").unwrap()).unwrap();
    let source = roxmltree::Document::parse(&xml).unwrap();
    let project = source
        .descendants()
        .find(|node| node.has_tag_name("Project"))
        .unwrap();
    let name = project
        .children()
        .find(|node| node.has_tag_name("TagName"))
        .and_then(|node| node.text())
        .unwrap();
    let selected_network = project
        .children()
        .find(|node| node.has_tag_name("Network"))
        .unwrap();
    let network_address = selected_network
        .children()
        .find(|node| node.has_tag_name("Address"))
        .and_then(|node| node.text())
        .unwrap();
    let expected_labels = selected_network
        .descendants()
        .filter(|node| node.has_tag_name("TagDLT"))
        .count();
    let path = state_path();
    std::fs::write(&path, old_state).unwrap();
    let (pci, _remote) = pci();
    let service = Service::new(&xml, None, path.clone(), pci.clone(), None).unwrap();
    let command = format!("[private] DBGETXML //{name}/{network_address}");
    let mut client = ClientState::default();
    let reply = service.handle(&mut client, &command).await;
    assert_eq!(reply.status, 200);
    let parsed = roxmltree::Document::parse(reply.lines[0].strip_prefix("347-").unwrap()).unwrap();
    let actual_labels = parsed
        .descendants()
        .filter(|node| node.has_tag_name("TagDLT"))
        .count();
    assert_eq!(actual_labels, expected_labels);
    let upgraded_state = std::fs::read(&path).unwrap();
    let stored: Database = serde_json::from_slice(&upgraded_state).unwrap();
    assert!(stored.imported_project_metadata);
    assert!(stored.saved_project_group_dlt_labels_complete);
    if let Ok(output_path) = std::env::var("CBUS_PRIVATE_MIGRATED_STATE") {
        std::fs::write(output_path, &upgraded_state).unwrap();
    }
    drop(service);
    let restarted = Service::new(&xml, None, path.clone(), pci, None).unwrap();
    let reply = restarted.handle(&mut client, &command).await;
    let parsed = roxmltree::Document::parse(reply.lines[0].strip_prefix("347-").unwrap()).unwrap();
    assert_eq!(
        parsed
            .descendants()
            .filter(|node| node.has_tag_name("TagDLT"))
            .count(),
        expected_labels
    );
    assert_eq!(std::fs::read(&path).unwrap(), upgraded_state);
    std::fs::remove_file(path).unwrap();
}

fn fixture() -> String {
    include_str!("../../../testdata/fixtures/project.xml").replace("</Network>",
        "<Unit oid=\"00000000-0000-0000-0000-00000000000c\"><Address>5</Address><TagName>Fixture eDLT</TagName><UnitType>KEYGL5</UnitType><FirmwareVersion>5.5.00</FirmwareVersion><PP Name=\"StaticTextString0\" Value=\"Fixture\"/></Unit></Network>")
}

fn topology_fixture() -> String {
    r#"<Installation><Project oid="project-topology">
      <TagName>TOPO</TagName>
      <Network oid="network-254">
        <TagName>Local</TagName><Address>254</Address>
        <Interface><InterfaceType>CNI</InterfaceType><InterfaceAddress>127.0.0.1:10001</InterfaceAddress></Interface>
        <Unit oid="pci-16"><Address>16</Address><UnitType>PC_CNI2</UnitType></Unit>
        <Unit oid="bridge-253-near"><Address>253</Address><UnitType>BRIDGE2N</UnitType></Unit>
      </Network>
      <Network oid="network-253">
        <TagName>Remote</TagName><Address>253</Address>
        <Interface><InterfaceType>Bridge</InterfaceType><InterfaceAddress>254/p/253</InterfaceAddress></Interface>
        <Unit oid="remote-4"><Address>4</Address><UnitType>KEYE1</UnitType></Unit>
        <Unit oid="bridge-254-far"><Address>254</Address><UnitType>BRIDGE2N</UnitType></Unit>
      </Network>
    </Project></Installation>"#
        .to_string()
}

async fn routed_pci_reply<W: tokio::io::AsyncWrite + Unpin>(
    writer: &mut W,
    bridges: &[u8],
    unit: u8,
    cal: &[u8],
) {
    let mut bytes = vec![0x86, bridges[0], 0x10, bridges.len() as u8];
    bytes.extend_from_slice(&bridges[1..]);
    bytes.push(unit);
    bytes.extend_from_slice(cal);
    let sum = bytes.iter().fold(0u8, |sum, byte| sum.wrapping_add(*byte));
    bytes.push(0u8.wrapping_sub(sum));
    let mut wire = hex::encode_upper(bytes).into_bytes();
    wire.extend_from_slice(b"\r\n");
    writer.write_all(&wire).await.unwrap();
}

fn routed_mmi_block(bridges: &[u8], start: u8, count: usize, present: &[(usize, u8)]) -> Vec<u8> {
    let mut states = vec![0u8; count];
    for (address, state) in present {
        if (usize::from(start)..usize::from(start) + count).contains(address) {
            states[*address - usize::from(start)] = *state;
        }
    }
    let direct = Packet::PointToPoint {
        meta: Meta {
            checksum: true,
            priority_class: 2,
            source_address: Some(4),
            confirmation: None,
        },
        unit_address: 16,
        bridged: false,
        hops: vec![],
        cals: vec![cbus_protocol::cal::Cal::ExtendedStatus {
            externally_initiated: false,
            child_application: 0xff,
            block_start: start,
            report: cbus_protocol::report::StatusReport::Binary(states),
        }],
    }
    .encode()
    .unwrap();
    let mut routed = vec![direct[0], bridges[0], 0x10, bridges.len() as u8];
    routed.extend_from_slice(&bridges[1..]);
    routed.push(4);
    routed.extend_from_slice(&direct[4..direct.len() - 1]);
    let mut wire =
        hex::encode_upper(cbus_protocol::common::add_cbus_checksum(&routed)).into_bytes();
    wire.extend_from_slice(b"\r\n");
    wire
}

fn state_path() -> PathBuf {
    static ID: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
    std::env::temp_dir().join(format!(
        "cmqttd-service-{}-{}.json",
        std::process::id(),
        ID.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
    ))
}

fn repository_transform_unitspec() -> PathBuf {
    let directory = state_path().with_extension("repository-transform-unitspec");
    std::fs::create_dir_all(&directory).unwrap();
    std::fs::write(
        directory.join("applications.xml"),
        "<?xml version=\"1.0\"?>\n<Applications><Application Address=\"56\" Name=\"Lighting\"/></Applications>\n",
    )
    .unwrap();
    std::fs::write(
        directory.join("cbusunits.xml"),
        r#"<CBusUnits><Calculator><MinImpedance>400</MinImpedance><MaxImpedance>1500</MaxImpedance><MaxSupplyCurrent>2000</MaxSupplyCurrent></Calculator><Units><Unit><CatalogNumber>5034N</CatalogNumber><CurrentDrawn>18</CurrentDrawn><CurrentSupplied>0</CurrentSupplied><Impedance>110000</Impedance></Unit><Unit><CatalogNumber>5500BUR</CatalogNumber><CurrentDrawn>0</CurrentDrawn><CurrentSupplied>0</CurrentSupplied><Impedance>1000</Impedance></Unit><Unit><CatalogNumber>5500PS</CatalogNumber><CurrentDrawn>0</CurrentDrawn><CurrentSupplied>350</CurrentSupplied><Impedance>20000</Impedance></Unit></Units></CBusUnits>"#,
    )
    .unwrap();
    directory
}

fn pci() -> (Arc<PciClient>, tokio::io::DuplexStream) {
    let (client, remote) = tokio::io::duplex(8192);
    let (rd, wr) = tokio::io::split(client);
    let (tx, _) = tokio::sync::mpsc::unbounded_channel();
    (PciClient::new(Box::new(rd), Box::new(wr), tx), remote)
}

async fn database_pci_line<R: tokio::io::AsyncBufRead + Unpin>(reader: &mut R) -> Vec<u8> {
    let mut line = Vec::new();
    reader.read_until(b'\r', &mut line).await.unwrap();
    line
}

async fn database_pci_reply<W: tokio::io::AsyncWrite + Unpin>(
    writer: &mut W,
    source: u8,
    cal: &[u8],
) {
    let mut bytes = vec![0x86, source, 0x10, 0x00];
    bytes.extend_from_slice(cal);
    let sum = bytes.iter().fold(0u8, |sum, byte| sum.wrapping_add(*byte));
    bytes.push(0u8.wrapping_sub(sum));
    let mut wire = hex::encode_upper(bytes).into_bytes();
    wire.extend_from_slice(b"\r\n");
    writer.write_all(&wire).await.unwrap();
}

fn database_mmi_block(start: u8, count: usize, present: u8) -> Vec<u8> {
    let mut states = vec![0u8; count];
    if (usize::from(start)..usize::from(start) + count).contains(&usize::from(present)) {
        states[usize::from(present) - usize::from(start)] = 1;
    }
    let mut wire = cbus_protocol::packet::Packet::StandardStatus {
        application: 0xff,
        block_start: start,
        states,
    }
    .encode_packet()
    .unwrap();
    wire.extend_from_slice(b"\r\n");
    wire
}

/// Serve one complete direct NET SYNC with a single non-eDLT unit.  The
/// identity is intentionally ordinary so the refresh has no optional OEM
/// reads after the serial quiet interval.
async fn serve_database_sync<R, W>(
    reader: &mut R,
    writer: &mut W,
    address: u8,
    unit_type: &str,
    firmware: &str,
) where
    R: tokio::io::AsyncBufRead + Unpin,
    W: tokio::io::AsyncWrite + Unpin,
{
    let mut request = database_pci_line(reader).await;
    if request == b"@1A2001\r" {
        writer.write_all(b"8220104E\r\n").await.unwrap();
        request = database_pci_line(reader).await;
    }
    assert!(request.starts_with(b"\\05FF00FAFF"), "{request:?}");
    let code = request[request.len() - 2];
    writer.write_all(&[code, b'.']).await.unwrap();
    for (start, count) in [(0, 88), (88, 88), (176, 80)] {
        writer
            .write_all(&database_mmi_block(start, count, address))
            .await
            .unwrap();
    }

    for (attribute, value) in [(1, unit_type.as_bytes()), (2, firmware.as_bytes())] {
        let request = database_pci_line(reader).await;
        assert!(
            request
                .windows(4)
                .any(|window| window == [b'2', b'1', b'0', b'0' + attribute]),
            "{request:?}"
        );
        let code = request[request.len() - 2];
        writer.write_all(&[code, b'.']).await.unwrap();
        let mut cal = vec![0x80 | (value.len() as u8 + 1), attribute];
        cal.extend_from_slice(value);
        database_pci_reply(writer, address, &cal).await;
    }

    let request = database_pci_line(reader).await;
    assert!(request.starts_with(format!("\\46{address:02X}002104").as_bytes()));
    let code = request[request.len() - 2];
    writer.write_all(&[code, b'.']).await.unwrap();
    let mut identity = vec![0x8d, 4, 0x38, 0xff, 0xff, 0xff, 0xff];
    identity.extend_from_slice(&[0x18, 0xb1, 0x06, 0x16, 0xa2, 0x00, address]);
    database_pci_reply(writer, address, &identity).await;
    tokio::time::advance(Duration::from_secs(2)).await;
    tokio::task::yield_now().await;
}

fn assert_native_broadcast_event(line: &str, session: u64, content: &str) {
    let body = line
        .strip_prefix("#e# ")
        .unwrap_or_else(|| panic!("missing event marker: {line:?}"));
    let (timestamp, payload) = body
        .split_once(" 703 ")
        .unwrap_or_else(|| panic!("missing native 703 envelope: {line:?}"));
    chrono::NaiveDateTime::parse_from_str(timestamp, "%Y%m%d-%H%M%S%.3f").unwrap();
    assert_eq!(payload, format!("cmd{session} - broadcast_event {content}"));
    assert_eq!(crate::event_reporting_level(line), Some(3));
}

fn assert_native_command_entry_event(line: &str, session: u64, command: &str) {
    let body = line.strip_prefix("#e# ").expect("event marker");
    let (timestamp, payload) = body.split_once(" 761 ").expect("native 761 envelope");
    chrono::NaiveDateTime::parse_from_str(timestamp, "%Y%m%d-%H%M%S%.3f").unwrap();
    assert_eq!(payload, format!("cmd{session} - Command: {command}"));
    assert_eq!(crate::event_reporting_level(line), Some(1));
}

fn assert_native_command_time_event(line: &str, session: u64, command_id: &str) {
    let body = line.strip_prefix("#e# ").expect("event marker");
    let (timestamp, payload) = body.split_once(" 767 ").expect("native 767 envelope");
    chrono::NaiveDateTime::parse_from_str(timestamp, "%Y%m%d-%H%M%S%.3f").unwrap();
    let millis = payload
        .strip_prefix(&format!("cmd{session} - commandId={command_id} time="))
        .expect("native command timing payload");
    millis
        .parse::<u128>()
        .expect("nonnegative millisecond duration");
    assert_eq!(crate::event_reporting_level(line), Some(7));
}

async fn next_command_trace_event(events: &mut tokio::sync::broadcast::Receiver<String>) -> String {
    tokio::time::timeout(Duration::from_secs(1), events.recv())
        .await
        .expect("command event timed out")
        .expect("command event channel closed")
}

async fn assert_native_command_trace(
    events: &mut tokio::sync::broadcast::Receiver<String>,
    session: u64,
    command: &str,
    response: &[&str],
    timed_tag: Option<&str>,
) {
    let command_event = next_command_trace_event(events).await;
    assert_native_command_entry_event(&command_event, session, command);
    for expected in response {
        let event = next_command_trace_event(events).await;
        let body = event.strip_prefix("#e# ").expect("event marker");
        let (timestamp, payload) = body.split_once(" 766 ").expect("native 766 envelope");
        chrono::NaiveDateTime::parse_from_str(timestamp, "%Y%m%d-%H%M%S%.3f").unwrap();
        assert_eq!(payload, format!("cmd{session} - Response: {expected}"));
        assert_eq!(crate::event_reporting_level(&event), Some(6));
    }
    if let Some(tag) = timed_tag {
        assert_native_command_time_event(&next_command_trace_event(events).await, session, tag);
    } else {
        assert!(
            tokio::time::timeout(Duration::from_millis(30), events.recv())
                .await
                .is_err(),
            "unexpected command timing event"
        );
    }
}

#[tokio::test]
async fn retained_family_help_roots_match_native_fixture_for_all_three_forms() {
    let evidence: serde_json::Value = serde_json::from_str(include_str!(
        "../../../testdata/fixtures/native_cgate_family_help.json"
    ))
    .unwrap();
    let path = state_path();
    let (pci_client, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();

    for family in evidence["families"].as_array().unwrap() {
        let name = family["family"].as_str().unwrap();
        let rows = family["root"].as_array().unwrap();
        let texts = rows
            .iter()
            .map(|row| row["text"].as_str().unwrap().to_string())
            .collect::<Vec<_>>();
        assert!(rows[..rows.len() - 1]
            .iter()
            .all(|row| row["code"] == 101 && row["continuation"] == true));
        assert_eq!(rows.last().unwrap()["code"], 101);
        assert_eq!(rows.last().unwrap()["continuation"], false);

        let mut replies = Vec::new();
        for (suffix, command) in [
            ("root", name.to_string()),
            ("question", format!("{name} ?")),
            ("help", format!("HELP {name}")),
        ] {
            let response = service
                .handle(&mut client, &format!("[{name}-{suffix}] {command}"))
                .await;
            assert_eq!(response.status, 101, "{command}");
            assert_eq!(response.lines, texts[..texts.len() - 1], "{command}");
            assert_eq!(
                response.final_text,
                format!("101 {}", texts.last().unwrap()),
                "{command}"
            );
            replies.push((response.lines, response.final_text));
        }
        assert_eq!(replies[0], replies[1], "{name} root versus question mark");
        assert_eq!(replies[0], replies[2], "{name} root versus HELP");
    }

    std::fs::remove_file(path).unwrap();
}

async fn connect_command_session(
    address: std::net::SocketAddr,
) -> (
    BufReader<tokio::net::tcp::OwnedReadHalf>,
    tokio::net::tcp::OwnedWriteHalf,
) {
    let stream = TcpStream::connect(address).await.unwrap();
    let (reader, writer) = stream.into_split();
    let mut reader = BufReader::new(reader);
    let mut greeting = String::new();
    reader.read_line(&mut greeting).await.unwrap();
    assert_eq!(greeting, "201 cmqttd C-Gate service ready\r\n");
    (reader, writer)
}

/// Command and response trace events share an EVENT-enabled command socket
/// with replies. Keep reply assertions exact while admitting only the three
/// native-shaped trace codes; an application event still fails a reply read.
async fn command_socket_reply_line(
    reader: &mut BufReader<tokio::net::tcp::OwnedReadHalf>,
    line: &mut String,
) -> usize {
    loop {
        line.clear();
        let read = reader.read_line(line).await.unwrap();
        if read == 0 {
            return 0;
        }
        let event = line.trim_end_matches(['\r', '\n']);
        let Some(body) = event.strip_prefix("#e# ") else {
            return read;
        };
        let (timestamp, rest) = body.split_once(' ').expect("trace code");
        chrono::NaiveDateTime::parse_from_str(timestamp, "%Y%m%d-%H%M%S%.3f")
            .expect("trace timestamp");
        let (code, payload) = rest.split_once(' ').expect("trace payload");
        let (session, content) = payload
            .strip_prefix("cmd")
            .and_then(|payload| payload.split_once(" - "))
            .expect("trace session");
        session.parse::<u64>().expect("numeric trace session");
        match code {
            "761" => assert!(content.starts_with("Command: "), "{event}"),
            "766" => assert!(content.starts_with("Response: "), "{event}"),
            "767" => {
                assert!(content.starts_with("commandId="), "{event}");
                assert!(content.contains(" time="), "{event}");
            }
            _ => panic!("unexpected event on command socket: {event}"),
        }
    }
}

async fn command_lines(
    reader: &mut BufReader<tokio::net::tcp::OwnedReadHalf>,
    writer: &mut tokio::net::tcp::OwnedWriteHalf,
    tag: &str,
    command: &str,
) -> Vec<String> {
    writer
        .write_all(format!("[{tag}] {command}\r\n").as_bytes())
        .await
        .unwrap();
    let prefix = format!("[{tag}] ");
    let mut lines = Vec::new();
    loop {
        let mut line = String::new();
        assert_ne!(command_socket_reply_line(reader, &mut line).await, 0);
        let line = line.trim_end_matches(['\r', '\n']).to_string();
        let payload = line
            .strip_prefix(&prefix)
            .unwrap_or_else(|| panic!("unexpected response line: {line}"));
        let complete = payload.as_bytes().get(3) == Some(&b' ');
        lines.push(line);
        if complete {
            return lines;
        }
    }
}

#[tokio::test]
async fn net_lifecycle_help_catalog_persistence_and_obsolete_boundary_are_native_shaped() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();

    let help = service.handle(&mut client, "[root] NET").await;
    assert_eq!(help.status, 101);
    assert_eq!(help.lines.len(), 23);
    assert_eq!(help.lines[0], "Help: NET commands:");
    assert_eq!(
        help.final_text,
        "101 Help:  NET UNRAVELUNIT - Unravel a unit address."
    );
    assert_eq!(
        service
            .handle(&mut client, "[help] HELP NETWORK LOCATE")
            .await
            .final_text,
        "101 Help:  <mode> is ON, OFF, or a number in the range 0 through 255"
    );
    assert_eq!(
        service
            .handle(&mut client, "[old] NET STATE_INTERVAL anything")
            .await
            .final_text,
        "400 Syntax Error: This command is obsolete.  Please use 'set projects NetStateInterval X' instead."
    );

    assert_eq!(
        service
            .handle(
                &mut client,
                "[create] NET CREATE GARAGE cni 127.0.0.1:10001 alpha=beta",
            )
            .await
            .final_text,
        "200 OK."
    );
    let list = service.handle(&mut client, "[list] NET LIST").await;
    assert_eq!(list.status, 131);
    assert!(format_response(&list).contains("network=GARAGE State=new InterfaceState=closed"));
    assert_eq!(
        service
            .handle(&mut client, "[save] NET SAVE FILE")
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut client, "[rename] NET RENAME GARAGE SHED")
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut client, "[delete] NET DELETE SHED")
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut client, "[duplicate] NET LOAD FILE")
            .await
            .final_text,
        "408 Operation failed: Problem loading: Network name already in use"
    );
    assert_eq!(
        service
            .handle(&mut client, "[new-project] PROJECT NEW EMPTY")
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut client, "[use-project] PROJECT USE EMPTY")
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(
                &mut client,
                "[create-empty] NET CREATE CABIN cni loopback.invalid:1"
            )
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut client, "[save-empty] NET SAVE FILE")
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut client, "[delete-empty] NET DELETE CABIN")
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut client, "[load-empty] NET LOAD FILE")
            .await
            .status,
        200
    );
    assert!(
        tokio::time::timeout(Duration::from_millis(20), remote.read_u8())
            .await
            .is_err(),
        "catalogue/help/obsolete commands must not write to the PCI"
    );

    drop(service);
    let (replacement, _replacement_remote) = pci();
    let restarted = Service::new(&fixture(), None, path.clone(), replacement, None).unwrap();
    let mut restarted_client = ClientState::default();
    assert_eq!(
        restarted
            .handle(&mut restarted_client, "[restart-use] PROJECT USE EMPTY")
            .await
            .status,
        200
    );
    let list = restarted
        .handle(&mut restarted_client, "[restart] NET LIST")
        .await;
    assert!(format_response(&list).contains("network=CABIN State=new InterfaceState=closed"));
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn network_and_project_runtime_lifecycle_preserves_shared_mqtt_transport() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client.clone(), None).unwrap();
    let mut client = ClientState::default();

    let close = service
        .handle(&mut client, "[1] NET CLOSE //HARNESS/254")
        .await;
    assert_eq!(close.status, 200, "{close:?}");
    assert_eq!(close.final_text, "200 OK: //HARNESS/254");
    assert_eq!(
        service.model.lock().await.projects["HARNESS"].networks[&254].state,
        NetworkState::Closed
    );
    assert!(
        pci_client.is_connected(),
        "logical close must retain MQTT PCI"
    );

    let open = service
        .handle(&mut client, "[2] NET OPEN //HARNESS/254")
        .await;
    assert_eq!(open.status, 200, "{open:?}");
    assert_eq!(open.lines.first().unwrap(), "120-initializing");
    assert_eq!(open.lines.last().unwrap(), "120-open complete");
    assert_eq!(
        service.model.lock().await.projects["HARNESS"].networks[&254].state,
        NetworkState::Open
    );

    assert_eq!(
        service
            .handle(&mut client, "[3] PROJECT STOP HARNESS")
            .await
            .status,
        200
    );
    assert_eq!(
        service.model.lock().await.projects["HARNESS"].networks[&254].state,
        NetworkState::Closed
    );
    assert!(pci_client.is_connected());
    assert_eq!(
        service
            .handle(&mut client, "[4] PROJECT START HARNESS ignored-like-native")
            .await
            .status,
        200
    );
    assert_eq!(
        service.model.lock().await.projects["HARNESS"].networks[&254].state,
        NetworkState::Open
    );

    assert_eq!(
        service
            .handle(&mut client, "[5] NET CREATE AUX cni 127.0.0.1:1")
            .await
            .status,
        200
    );
    let unbound = service.handle(&mut client, "[6] NET OPEN AUX").await;
    assert_eq!(unbound.status, 408, "{unbound:?}");
    assert!(unbound.final_text.contains("no runtime binding"));
    assert_eq!(
        service
            .handle(&mut client, "[7] TOPOLOGY EXPLORE")
            .await
            .final_text,
        "408 Operation failed: No interfaces to explore"
    );
    let malformed = service
        .handle(&mut client, "[8] TOPOLOGY EXPLORE not-an-interface")
        .await;
    assert_eq!(malformed.status, 408);
    assert_eq!(
        malformed.lines,
        ["470-Bad interface specification for NET0 not-an-interface"]
    );
    assert!(
        tokio::time::timeout(Duration::from_millis(20), remote.read_u8())
            .await
            .is_err(),
        "logical lifecycle and rejected topology commands must not touch PCI"
    );
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn net_lifecycle_mutations_and_network_locate_require_login_before_io() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    service
        .set_auth_token_hash(crate::auth::sha256(b"net-lifecycle-test-token"))
        .unwrap();
    let mut client = ClientState::default();
    assert_eq!(service.handle(&mut client, "[help] NET").await.status, 101);
    assert_eq!(
        service.handle(&mut client, "[list] NET LIST").await.status,
        131
    );
    for command in [
        "NET CREATE TEMP cni 127.0.0.1:1",
        "NET DELETE 254",
        "NET FLUSH 254",
        "NET LEARN 254 56 1 1",
        "NET LOAD DB",
        "NET OPEN 254",
        "NET CLOSE 254",
        "NET RENAME 254 LOCAL",
        "NET SAVE DB",
        "PROJECT START HARNESS",
        "PROJECT STOP HARNESS",
        "DO //HARNESS/254 UNRAVEL",
        "NETWORK LOCATE 254/208 UNIT 1 ON",
    ] {
        let response = service
            .handle(&mut client, &format!("[locked] {command}"))
            .await;
        assert_eq!(response.final_text, "420 LOGIN required", "{command}");
    }
    assert!(
        tokio::time::timeout(Duration::from_millis(20), remote.read_u8())
            .await
            .is_err(),
        "unauthenticated NET mutations must fail before PCI I/O"
    );
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn net_save_load_explicit_project_targets_only_the_named_project() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    assert_eq!(
        service
            .handle(
                &mut client,
                "[create] NET CREATE GARAGE cni loopback.invalid:1"
            )
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut client, "[new] PROJECT NEW OTHER")
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut client, "[use] PROJECT USE OTHER")
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(
                &mut client,
                "[create-other] NET CREATE CABIN cni loopback.invalid:2",
            )
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut client, "[save-other] NET SAVE FILE OTHER")
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut client, "[delete-other] NET DELETE CABIN")
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut client, "[use-harness] PROJECT USE HARNESS")
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut client, "[load-other] NET LOAD FILE OTHER")
            .await
            .status,
        200
    );
    let harness = service
        .handle(&mut client, "[list-harness] NET LIST HARNESS")
        .await;
    assert!(format_response(&harness).contains("network=GARAGE"));
    assert!(!format_response(&harness).contains("network=CABIN"));
    let other = service
        .handle(&mut client, "[list-other] NET LIST OTHER")
        .await;
    assert!(format_response(&other).contains("network=CABIN"));
    assert!(!format_response(&other).contains("network=GARAGE"));

    assert_eq!(
        service
            .handle(&mut client, "[save-db-other] NET SAVE DB OTHER")
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut client, "[delete-qualified] NET DELETE //OTHER/CABIN")
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut client, "[load-db-other] NET LOAD DB OTHER")
            .await
            .status,
        200
    );
    assert!(format_response(
        &service
            .handle(&mut client, "[list-restored] NET LIST OTHER")
            .await
    )
    .contains("network=CABIN"));

    for (command, expected) in [
        (
            "NET CREATE GARAGE cni loopback.invalid:1",
            "408 Operation failed: Network name already in use",
        ),
        (
            "NET RENAME GARAGE GARAGE",
            "408 Operation failed: New name is in use",
        ),
        (
            "NET SAVE BOGUS OTHER",
            "400 Syntax Error: <destination> must be 'DB' or 'FILE'.",
        ),
        (
            "NET LOAD BOGUS OTHER",
            "400 Syntax Error: <source> must be 'DB' or 'FILE'.",
        ),
        (
            "NET SAVE FILE MISSING",
            "401 Bad object or device ID: MISSING (Network not found)",
        ),
    ] {
        assert_eq!(
            service
                .handle(&mut client, &format!("[native-error] {command}"))
                .await
                .final_text,
            expected,
            "{command}"
        );
    }
    assert!(
        tokio::time::timeout(Duration::from_millis(20), remote.read_u8())
            .await
            .is_err(),
        "explicit-project catalogue validation must remain local"
    );
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn net_learn_and_network_locate_use_exact_once_confirmed_native_frames() {
    let path = state_path();
    let (pci_client, remote) = pci();
    let (remote_read, mut remote_write) = tokio::io::split(remote);
    let mut remote_read = BufReader::new(remote_read);
    let reset = tokio::spawn({
        let pci = pci_client.clone();
        async move { pci.pci_reset().await }
    });
    for _ in 0..8 {
        let mut line = Vec::new();
        remote_read.read_until(b'\r', &mut line).await.unwrap();
    }
    reset.await.unwrap().unwrap();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();

    for (command, prefix) in [
        (
            "NET LEARN //HARNESS/254 56 1 1",
            b"\\053800030101FE".as_slice(),
        ),
        (
            "NETWORK LOCATE //HARNESS/254/208 UNIT 1 ON",
            b"\\05D00013FF0101".as_slice(),
        ),
        (
            "NETWORK LOCATE //HARNESS/254/208 SERIAL 1 12345.67 255",
            b"\\05D000160103039043FF".as_slice(),
        ),
    ] {
        let task = tokio::spawn({
            let service = service.clone();
            let command = command.to_string();
            async move {
                service
                    .handle(
                        &mut ClientState::default(),
                        &format!("[physical] {command}"),
                    )
                    .await
            }
        });
        let mut frame = Vec::new();
        remote_read.read_until(b'\r', &mut frame).await.unwrap();
        assert!(frame.starts_with(prefix), "{command}: {frame:?}");
        let confirmation = frame[frame.len() - 2];
        remote_write.write_all(&[confirmation, b'.']).await.unwrap();
        assert_eq!(task.await.unwrap().status, 200, "{command}");
    }

    let rejected = tokio::spawn({
        let service = service.clone();
        async move {
            service
                .handle(
                    &mut ClientState::default(),
                    "[nak] NETWORK LOCATE 254/208 GROUP 56 1 OFF",
                )
                .await
        }
    });
    let mut frame = Vec::new();
    remote_read.read_until(b'\r', &mut frame).await.unwrap();
    assert!(frame.starts_with(b"\\05D00013380100"), "{frame:?}");
    let confirmation = frame[frame.len() - 2];
    remote_write.write_all(&[confirmation, b'#']).await.unwrap();
    assert_eq!(rejected.await.unwrap().status, 502);
    assert!(
        tokio::time::timeout(Duration::from_millis(30), remote_read.read_u8())
            .await
            .is_err(),
        "a definitive NAK must not replay NETWORK LOCATE"
    );
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn bridged_pingu_discovers_only_the_target_network_cache() {
    let path = state_path();
    let (pci_client, remote) = pci();
    let (remote_read, mut remote_write) = tokio::io::split(remote);
    let mut remote_read = BufReader::new(remote_read);
    let reset = tokio::spawn({
        let pci = pci_client.clone();
        async move { pci.pci_reset().await }
    });
    for _ in 0..8 {
        let mut line = Vec::new();
        remote_read.read_until(b'\r', &mut line).await.unwrap();
    }
    reset.await.unwrap().unwrap();
    let service = Service::new(&topology_fixture(), None, path.clone(), pci_client, None).unwrap();
    let command = tokio::spawn({
        let service = service.clone();
        async move {
            service
                .handle(&mut ClientState::default(), "[1] NET PINGU //TOPO/253")
                .await
        }
    });
    let mut request = Vec::new();
    remote_read.read_until(b'\r', &mut request).await.unwrap();
    assert!(request.starts_with(b"\\03FD09FFFAFF00FF"), "{request:?}");
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    for (start, count) in [(0, 88), (88, 88), (176, 80)] {
        remote_write
            .write_all(&routed_mmi_block(&[253], start, count, &[(4, 1)]))
            .await
            .unwrap();
    }
    let response = command.await.unwrap();
    assert_eq!(response.status, 200, "{response:?}");
    assert_eq!(response.lines, ["302-Units=4"]);
    let model = service.model.lock().await;
    assert_eq!(
        model.projects["TOPO"].networks[&253]
            .physical
            .keys()
            .copied()
            .collect::<Vec<_>>(),
        [4]
    );
    assert!(model.projects["TOPO"].networks[&254].physical.is_empty());
    drop(model);
    std::fs::remove_file(path).unwrap();
}

#[tokio::test(start_paused = true)]
async fn bridged_sync_populates_identity_rejects_cross_route_and_clears_on_reconnect() {
    async fn line<R: tokio::io::AsyncBufRead + Unpin>(reader: &mut R) -> Vec<u8> {
        tokio::time::timeout(Duration::from_secs(3), async {
            let mut line = Vec::new();
            reader.read_until(b'\r', &mut line).await.unwrap();
            line
        })
        .await
        .expect("timed out waiting for identity PCI request")
    }

    let path = state_path();
    let (pci_client, remote) = pci();
    let (remote_read, mut remote_write) = tokio::io::split(remote);
    let mut remote_read = BufReader::new(remote_read);
    let reset = tokio::spawn({
        let pci = pci_client.clone();
        async move { pci.pci_reset().await }
    });
    for _ in 0..8 {
        line(&mut remote_read).await;
    }
    reset.await.unwrap().unwrap();
    let service = Service::new(&topology_fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut events = service.events.subscribe();
    let command = tokio::spawn({
        let service = service.clone();
        async move {
            service
                .handle(
                    &mut ClientState::default(),
                    "[2] NET SYNC //TOPO/253 fast 0",
                )
                .await
        }
    });

    let request = line(&mut remote_read).await;
    assert!(request.starts_with(b"\\03FD09FFFAFF00FF"), "{request:?}");
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    for (start, count) in [(0, 88), (88, 88), (176, 80)] {
        remote_write
            .write_all(&routed_mmi_block(&[253], start, count, &[(4, 1)]))
            .await
            .unwrap();
    }

    for (attribute, value) in [(1u8, b"KEYE1".as_slice()), (2u8, b"1.2.30".as_slice())] {
        let request = line(&mut remote_read).await;
        assert!(
            request.starts_with(format!("\\46FD090421{attribute:02X}").as_bytes()),
            "{request:?}"
        );
        let code = request[request.len() - 2];
        let mut cal = vec![0x80 | (value.len() as u8 + 1), attribute];
        cal.extend_from_slice(value);
        routed_pci_reply(&mut remote_write, &[253], 4, &cal).await;
        remote_write.write_all(&[code, b'.']).await.unwrap();
    }

    let request = line(&mut remote_read).await;
    assert!(request.starts_with(b"\\46FD09042104"), "{request:?}");
    let code = request[request.len() - 2];
    // Same unit on a different route cannot seed the remote cache.
    let serial = [
        0x38, 0xff, 0xff, 0xff, 0xff, 0x18, 0xb1, 0x06, 0x16, 0xa2, 0x00, 0x05,
    ];
    let mut cal = vec![0x8d, 4];
    cal.extend_from_slice(&serial);
    routed_pci_reply(&mut remote_write, &[252], 4, &cal).await;
    routed_pci_reply(&mut remote_write, &[253], 4, &cal).await;
    remote_write.write_all(&[code, b'.']).await.unwrap();
    tokio::time::advance(Duration::from_secs(2)).await;
    tokio::task::yield_now().await;

    let response = command.await.unwrap();
    assert_eq!(response.status, 200, "{response:?}");
    {
        let model = service.model.lock().await;
        let unit = &model.projects["TOPO"].networks[&253].physical[&4];
        assert_eq!(unit.unit_type, "KEYE1");
        assert_eq!(unit.firmware, "1.2.30");
        assert_eq!(unit.serial, "101136.1558");
        assert!(model.projects["TOPO"].networks[&254].physical.is_empty());
    }
    assert_eq!(events.recv().await.unwrap(), "#e# net 253 sync ok");

    {
        let mut model = service.model.lock().await;
        let project = model.projects.get_mut("TOPO").unwrap();
        project
            .networks
            .get_mut(&254)
            .unwrap()
            .physical
            .insert(7, Unit::blank(7, "KEYE1"));
        project
            .networks
            .get_mut(&254)
            .unwrap()
            .levels
            .insert((56, 1), 255);
        project
            .networks
            .get_mut(&253)
            .unwrap()
            .levels
            .insert((56, 2), 128);
    }
    let (replacement, _remote) = pci();
    service.set_pci(replacement).await;
    let model = service.model.lock().await;
    for address in [254, 253] {
        let network = &model.projects["TOPO"].networks[&address];
        assert!(network.physical.is_empty());
        assert!(network.levels.is_empty());
        assert_eq!(network.state, NetworkState::Open);
    }
    drop(model);
    std::fs::remove_file(path).unwrap();
}

#[tokio::test(start_paused = true)]
async fn bridged_sync_populates_route_correlated_edlt_metadata() {
    async fn line<R: tokio::io::AsyncBufRead + Unpin>(reader: &mut R) -> Vec<u8> {
        let mut line = Vec::new();
        reader.read_until(b'\r', &mut line).await.unwrap();
        line
    }

    let xml = topology_fixture().replace(
        r#"<Unit oid="remote-4"><Address>4</Address><UnitType>KEYE1</UnitType></Unit>"#,
        r#"<Unit oid="remote-4"><Address>4</Address><UnitType>KEYE1</UnitType></Unit>
        <Unit oid="remote-edlt-5"><Address>5</Address><TagName>Remote eDLT</TagName><UnitType>KEYGL5</UnitType><FirmwareVersion>5.5.00</FirmwareVersion></Unit>"#,
    );
    let path = state_path();
    let (pci_client, remote) = pci();
    let (remote_read, mut remote_write) = tokio::io::split(remote);
    let mut remote_read = BufReader::new(remote_read);
    let reset = tokio::spawn({
        let pci = pci_client.clone();
        async move { pci.pci_reset().await }
    });
    for _ in 0..8 {
        line(&mut remote_read).await;
    }
    reset.await.unwrap().unwrap();

    let service = Service::new(&xml, None, path.clone(), pci_client, None).unwrap();
    let command = tokio::spawn({
        let service = service.clone();
        async move {
            service
                .handle(
                    &mut ClientState::default(),
                    "[edlt] NET SYNC //TOPO/253 fast 0",
                )
                .await
        }
    });

    let request = line(&mut remote_read).await;
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    for (start, count) in [(0, 88), (88, 88), (176, 80)] {
        remote_write
            .write_all(&routed_mmi_block(&[253], start, count, &[(5, 1)]))
            .await
            .unwrap();
    }

    for (attribute, value) in [(1u8, b"KEYGL5".as_slice()), (2u8, b"5.5.00".as_slice())] {
        let request = line(&mut remote_read).await;
        let code = request[request.len() - 2];
        let mut cal = vec![0x80 | (value.len() as u8 + 1), attribute];
        cal.extend_from_slice(value);
        routed_pci_reply(&mut remote_write, &[253], 5, &cal).await;
        remote_write.write_all(&[code, b'.']).await.unwrap();
    }

    let request = line(&mut remote_read).await;
    let code = request[request.len() - 2];
    let serial = [
        0x38, 0xff, 0xff, 0xff, 0xff, 0x18, 0xb1, 0x06, 0x16, 0xa2, 0x00, 0x05,
    ];
    let mut cal = vec![0x8d, 4];
    cal.extend_from_slice(&serial);
    routed_pci_reply(&mut remote_write, &[253], 5, &cal).await;
    remote_write.write_all(&[code, b'.']).await.unwrap();
    tokio::time::advance(Duration::from_secs(2)).await;
    tokio::task::yield_now().await;

    assert_eq!(line(&mut remote_read).await, b"\\46FD09051AFB0991\r");
    routed_pci_reply(
        &mut remote_write,
        &[253],
        5,
        &[0x85, 0xfb, b'0', b'1', b'.', b'0'],
    )
    .await;
    routed_pci_reply(
        &mut remote_write,
        &[253],
        5,
        &[0x86, 0xfb, b'5', b'.', b'0', b'0', 0],
    )
    .await;

    assert_eq!(line(&mut remote_read).await, b"\\46FD0905A400411000BA\r");
    routed_pci_reply(&mut remote_write, &[253], 5, &[0x32, 0, 0x41]).await;
    assert_eq!(line(&mut remote_read).await, b"\\46FD09051A010292\r");
    routed_pci_reply(&mut remote_write, &[253], 5, &[0x83, 1, 56, 255]).await;

    assert_eq!(line(&mut remote_read).await, b"\\46FD09051AFA2C6F\r");
    let groups = (0..44u8).collect::<Vec<_>>();
    for chunk in groups.chunks(16) {
        let mut cal = vec![0x80 | (chunk.len() as u8 + 1), 0xfa];
        cal.extend_from_slice(chunk);
        routed_pci_reply(&mut remote_write, &[253], 5, &cal).await;
    }

    let response = command.await.unwrap();
    assert_eq!(response.status, 200, "{response:?}");
    let model = service.model.lock().await;
    let unit = &model.projects["TOPO"].networks[&253].physical[&5];
    assert_eq!(unit.unit_type, "KEYGL5");
    assert_eq!(unit.fields["FirmwareVersion"], "01.05.00");
    assert_eq!(unit.fields["Application"], "56");
    assert_eq!(unit.fields["Application2"], "255");
    assert_eq!(
        unit.fields["WidgetGroups"],
        groups
            .iter()
            .map(u8::to_string)
            .collect::<Vec<_>>()
            .join(",")
    );
    drop(model);
    std::fs::remove_file(path).unwrap();
}

#[tokio::test(start_paused = true)]
async fn bridged_syncnew_all_discovers_into_only_the_target_cache() {
    async fn line<R: tokio::io::AsyncBufRead + Unpin>(reader: &mut R) -> Vec<u8> {
        let mut line = Vec::new();
        reader.read_until(b'\r', &mut line).await.unwrap();
        line
    }

    let path = state_path();
    let (pci_client, remote) = pci();
    let (remote_read, mut remote_write) = tokio::io::split(remote);
    let mut remote_read = BufReader::new(remote_read);
    let reset = tokio::spawn({
        let pci = pci_client.clone();
        async move { pci.pci_reset().await }
    });
    for _ in 0..8 {
        line(&mut remote_read).await;
    }
    reset.await.unwrap().unwrap();
    let service = Service::new(&topology_fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut events = service.events.subscribe();
    let command = tokio::spawn({
        let service = service.clone();
        async move {
            service
                .handle(
                    &mut ClientState::default(),
                    "[syncnew] NET SYNCNEW //TOPO/253",
                )
                .await
        }
    });

    for _ in 0..5 {
        let request = line(&mut remote_read).await;
        assert!(request.starts_with(b"\\03FD09FFFAFF00FF"), "{request:?}");
        let code = request[request.len() - 2];
        remote_write.write_all(&[code, b'.']).await.unwrap();
        for (start, count) in [(0, 88), (88, 88), (176, 80)] {
            remote_write
                .write_all(&routed_mmi_block(&[253], start, count, &[(4, 1)]))
                .await
                .unwrap();
        }
    }

    for (attribute, value) in [(1u8, b"KEYE1".as_slice()), (2u8, b"1.2.30".as_slice())] {
        let request = line(&mut remote_read).await;
        assert!(
            request.starts_with(format!("\\46FD090421{attribute:02X}").as_bytes()),
            "{request:?}"
        );
        let code = request[request.len() - 2];
        // A matching source address on another route cannot satisfy this
        // routed discovery transaction.
        let mut cal = vec![0x80 | (value.len() as u8 + 1), attribute];
        cal.extend_from_slice(value);
        routed_pci_reply(&mut remote_write, &[252], 4, &cal).await;
        routed_pci_reply(&mut remote_write, &[253], 4, &cal).await;
        remote_write.write_all(&[code, b'.']).await.unwrap();
    }

    let request = line(&mut remote_read).await;
    assert!(request.starts_with(b"\\46FD09042104"), "{request:?}");
    let code = request[request.len() - 2];
    let serial = [
        0x38, 0xff, 0xff, 0xff, 0xff, 0x18, 0xb1, 0x06, 0x16, 0xa2, 0x00, 0x05,
    ];
    let mut cal = vec![0x8d, 4];
    cal.extend_from_slice(&serial);
    routed_pci_reply(&mut remote_write, &[253], 4, &cal).await;
    remote_write.write_all(&[code, b'.']).await.unwrap();
    tokio::time::advance(Duration::from_secs(2)).await;
    tokio::task::yield_now().await;

    let response = command.await.unwrap();
    assert_eq!(response.status, 303, "{response:?}");
    assert_eq!(response.lines.len(), 5, "{response:?}");
    assert_eq!(response.lines[0], "120-completed MMI 1 of 5.");
    assert_eq!(response.lines[4], "120-completed MMI 5 of 5.");
    assert_eq!(
        response.final_text,
        "303 New Unit Found: address=4 type=KEYE1 version=1.2.30 serial=101136.1558"
    );
    {
        let model = service.model.lock().await;
        let unit = &model.projects["TOPO"].networks[&253].physical[&4];
        assert_eq!(unit.unit_type, "KEYE1");
        assert_eq!(unit.firmware, "1.2.30");
        assert_eq!(unit.serial, "101136.1558");
        assert!(model.projects["TOPO"].networks[&254].physical.is_empty());
    }
    assert_eq!(events.recv().await.unwrap(), "#e# net 253 syncnew unit 4");
    std::fs::remove_file(path).unwrap();
}

#[tokio::test(start_paused = true)]
async fn bridged_syncnew_target_runs_route_correlated_duplicate_and_identity_discovery() {
    async fn line<R: tokio::io::AsyncBufRead + Unpin>(reader: &mut R) -> Vec<u8> {
        let mut line = Vec::new();
        reader.read_until(b'\r', &mut line).await.unwrap();
        line
    }

    let path = state_path();
    let (pci_client, remote) = pci();
    let (remote_read, mut remote_write) = tokio::io::split(remote);
    let mut remote_read = BufReader::new(remote_read);
    let reset = tokio::spawn({
        let pci = pci_client.clone();
        async move { pci.pci_reset().await }
    });
    for _ in 0..8 {
        line(&mut remote_read).await;
    }
    reset.await.unwrap().unwrap();
    let service = Service::new(&topology_fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut events = service.events.subscribe();
    let command = tokio::spawn({
        let service = service.clone();
        async move {
            service
                .handle(
                    &mut ClientState::default(),
                    "[target] NET SYNCNEW //TOPO/253 5",
                )
                .await
        }
    });

    for _ in 0..5 {
        let request = line(&mut remote_read).await;
        assert!(request.starts_with(b"\\03FD09FFFAFF00FF"), "{request:?}");
        let code = request[request.len() - 2];
        remote_write.write_all(&[code, b'.']).await.unwrap();
        for (start, count) in [(0, 88), (88, 88), (176, 80)] {
            remote_write
                .write_all(&routed_mmi_block(&[253], start, count, &[(5, 1)]))
                .await
                .unwrap();
        }
    }

    for (attempt, expected) in [
        (0u8, b"\\46FD090511801E".as_slice()),
        (1u8, b"\\46FD090511811D".as_slice()),
        (2u8, b"\\46FD090511821C".as_slice()),
    ] {
        let request = line(&mut remote_read).await;
        assert_eq!(&request[..request.len() - 2], expected);
        let code = request[request.len() - 2];
        // A matching unit/parameter on the neighbouring route is ignored.
        routed_pci_reply(&mut remote_write, &[252], 5, &[0x82, 0x80 + attempt, 0x22]).await;
        routed_pci_reply(&mut remote_write, &[253], 5, &[0x82, 0x80 + attempt, 0x33]).await;
        tokio::task::yield_now().await;
        remote_write.write_all(&[code, b'.']).await.unwrap();
        tokio::time::advance(Duration::from_secs(2)).await;
        tokio::task::yield_now().await;
    }

    for (attribute, value) in [(1u8, b"KEYE1".as_slice()), (2u8, b"1.2.30".as_slice())] {
        let request = line(&mut remote_read).await;
        assert!(
            request.starts_with(format!("\\46FD090521{attribute:02X}").as_bytes()),
            "{request:?}"
        );
        let code = request[request.len() - 2];
        let mut cal = vec![0x80 | (value.len() as u8 + 1), attribute];
        cal.extend_from_slice(value);
        routed_pci_reply(&mut remote_write, &[252], 5, &cal).await;
        routed_pci_reply(&mut remote_write, &[253], 5, &cal).await;
        tokio::task::yield_now().await;
        remote_write.write_all(&[code, b'.']).await.unwrap();
    }

    let serial = [
        0x38, 0xff, 0xff, 0xff, 0xff, 0x18, 0xb1, 0x06, 0x16, 0xa2, 0x00, 0x05,
    ];
    let request = line(&mut remote_read).await;
    assert_eq!(&request[..request.len() - 2], b"\\46FD090521048A");
    let code = request[request.len() - 2];
    let mut cal = vec![0x8d, 4];
    cal.extend_from_slice(&serial);
    routed_pci_reply(&mut remote_write, &[253], 5, &cal).await;
    remote_write.write_all(&[code, b'.']).await.unwrap();
    tokio::time::advance(Duration::from_secs(2)).await;
    tokio::task::yield_now().await;

    let response = command.await.unwrap();
    assert_eq!(response.status, 303, "{response:?}");
    assert_eq!(response.lines.len(), 11, "{response:?}");
    assert_eq!(response.lines[0], "120-completed MMI 1 of 5.");
    assert_eq!(response.lines[4], "120-completed MMI 5 of 5.");
    assert_eq!(response.lines[5], "120-unit found");
    assert_eq!(response.lines[6], "120-duplicate test 1/3");
    assert_eq!(response.lines[10], "120-identifying unit");
    assert_eq!(
        response.final_text,
        "303 New Unit Found: address=5 type=KEYE1 version=1.2.30 serial=101136.1558"
    );
    let model = service.model.lock().await;
    let remote_network = &model.projects["TOPO"].networks[&253];
    assert_eq!(remote_network.physical[&5].unit_type, "KEYE1");
    assert_eq!(remote_network.physical[&5].firmware, "1.2.30");
    assert_eq!(remote_network.physical[&5].serial, "101136.1558");
    assert!(model.projects["TOPO"].networks[&254].physical.is_empty());
    drop(model);
    assert_eq!(events.recv().await.unwrap(), "#e# net 253 syncnew unit 5");
    std::fs::remove_file(path).unwrap();
}

#[tokio::test(start_paused = true)]
async fn bridged_syncnew_target_lost_confirmation_retires_without_cache_or_event() {
    async fn line<R: tokio::io::AsyncBufRead + Unpin>(reader: &mut R) -> Vec<u8> {
        let mut line = Vec::new();
        reader.read_until(b'\r', &mut line).await.unwrap();
        line
    }

    let path = state_path();
    let (pci_client, remote) = pci();
    let observed_pci = pci_client.clone();
    let (remote_read, mut remote_write) = tokio::io::split(remote);
    let mut remote_read = BufReader::new(remote_read);
    let reset = tokio::spawn({
        let pci = pci_client.clone();
        async move { pci.pci_reset().await }
    });
    for _ in 0..8 {
        line(&mut remote_read).await;
    }
    reset.await.unwrap().unwrap();
    let service = Service::new(&topology_fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut events = service.events.subscribe();
    let command = tokio::spawn({
        let service = service.clone();
        async move {
            service
                .handle(
                    &mut ClientState::default(),
                    "[timeout] NET SYNCNEW //TOPO/253 5",
                )
                .await
        }
    });

    for _ in 0..5 {
        let request = line(&mut remote_read).await;
        assert!(request.starts_with(b"\\03FD09FFFAFF00FF"), "{request:?}");
        let code = request[request.len() - 2];
        remote_write.write_all(&[code, b'.']).await.unwrap();
        for (start, count) in [(0, 88), (88, 88), (176, 80)] {
            remote_write
                .write_all(&routed_mmi_block(&[253], start, count, &[(5, 1)]))
                .await
                .unwrap();
        }
    }

    let request = line(&mut remote_read).await;
    assert_eq!(&request[..request.len() - 2], b"\\46FD090511801E");
    // A matching reply is deliberately insufficient: the command's positive
    // confirmation never arrives, so the exchange remains uncertain and the
    // whole PCI generation must be retired rather than replayed or committed.
    routed_pci_reply(&mut remote_write, &[253], 5, &[0x82, 0x80, 0x33]).await;
    tokio::time::advance(Duration::from_secs(10)).await;
    tokio::task::yield_now().await;

    let response = command.await.unwrap();
    assert_eq!(response.status, 408, "{response:?}");
    assert_eq!(
        response.final_text,
        "408 Operation failed: Duplicate test failed:duplicate-address probe timed out"
    );
    assert_eq!(
        observed_pci.programming_lane_state(),
        ProgrammingLaneState::ReconnectRequired
    );
    assert!(!observed_pci.is_connected());
    assert!(
        !service.model.lock().await.projects["TOPO"].networks[&253]
            .physical
            .contains_key(&5),
        "an incomplete duplicate exchange must not commit the staged unit"
    );
    assert!(matches!(
        events.try_recv(),
        Err(tokio::sync::broadcast::error::TryRecvError::Empty)
    ));
    std::fs::remove_file(path).unwrap();
}

#[tokio::test(start_paused = true)]
async fn bridged_syncnew_reconnect_discards_the_staged_cache_and_event() {
    async fn line<R: tokio::io::AsyncBufRead + Unpin>(reader: &mut R) -> Vec<u8> {
        let mut line = Vec::new();
        reader.read_until(b'\r', &mut line).await.unwrap();
        line
    }

    let path = state_path();
    let (pci_client, remote) = pci();
    let (remote_read, mut remote_write) = tokio::io::split(remote);
    let mut remote_read = BufReader::new(remote_read);
    let reset = tokio::spawn({
        let pci = pci_client.clone();
        async move { pci.pci_reset().await }
    });
    for _ in 0..8 {
        line(&mut remote_read).await;
    }
    reset.await.unwrap().unwrap();
    let service = Service::new(&topology_fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut events = service.events.subscribe();
    let command = tokio::spawn({
        let service = service.clone();
        async move {
            service
                .handle(
                    &mut ClientState::default(),
                    "[generation] NET SYNCNEW //TOPO/253",
                )
                .await
        }
    });

    for _ in 0..5 {
        let request = line(&mut remote_read).await;
        let code = request[request.len() - 2];
        remote_write.write_all(&[code, b'.']).await.unwrap();
        for (start, count) in [(0, 88), (88, 88), (176, 80)] {
            remote_write
                .write_all(&routed_mmi_block(&[253], start, count, &[(4, 1)]))
                .await
                .unwrap();
        }
    }
    for (attribute, value) in [(1u8, b"KEYE1".as_slice()), (2u8, b"1.2.30".as_slice())] {
        let request = line(&mut remote_read).await;
        let code = request[request.len() - 2];
        let mut cal = vec![0x80 | (value.len() as u8 + 1), attribute];
        cal.extend_from_slice(value);
        routed_pci_reply(&mut remote_write, &[253], 4, &cal).await;
        remote_write.write_all(&[code, b'.']).await.unwrap();
    }
    let request = line(&mut remote_read).await;
    let code = request[request.len() - 2];
    let serial = [
        0x38, 0xff, 0xff, 0xff, 0xff, 0x18, 0xb1, 0x06, 0x16, 0xa2, 0x00, 0x05,
    ];
    let mut cal = vec![0x8d, 4];
    cal.extend_from_slice(&serial);
    let gate = service.pci_generation_gate.lock().await;
    routed_pci_reply(&mut remote_write, &[253], 4, &cal).await;
    remote_write.write_all(&[code, b'.']).await.unwrap();
    tokio::time::advance(Duration::from_secs(2)).await;
    tokio::task::yield_now().await;
    service.pci_generation.fetch_add(1, Ordering::AcqRel);
    drop(gate);

    let response = command.await.unwrap();
    assert_eq!(response.status, 408, "{response:?}");
    assert_eq!(
        response.final_text,
        "408 Operation failed: Discovery invalidated by PCI reconnect"
    );
    assert!(
        service.model.lock().await.projects["TOPO"].networks[&253]
            .physical
            .is_empty(),
        "a stale routed identity must not repopulate the volatile cache"
    );
    assert!(matches!(
        events.try_recv(),
        Err(tokio::sync::broadcast::error::TryRecvError::Empty)
    ));
    std::fs::remove_file(path).unwrap();
}

#[tokio::test(start_paused = true)]
async fn bridged_checkunit_reconnect_returns_408_without_a_stale_event() {
    let path = state_path();
    let (pci_client, remote) = pci();
    let (remote_read, mut remote_write) = tokio::io::split(remote);
    let mut remote_read = BufReader::new(remote_read);
    let reset = tokio::spawn({
        let pci = pci_client.clone();
        async move { pci.pci_reset().await }
    });
    for _ in 0..8 {
        let mut line = Vec::new();
        remote_read.read_until(b'\r', &mut line).await.unwrap();
    }
    reset.await.unwrap().unwrap();
    let service = Service::new(&topology_fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut events = service.events.subscribe();
    let command = tokio::spawn({
        let service = service.clone();
        async move {
            service
                .handle(
                    &mut ClientState::default(),
                    "[3] NET CHECKUNIT //TOPO/253 4",
                )
                .await
        }
    });

    let mut request = Vec::new();
    remote_read.read_until(b'\r', &mut request).await.unwrap();
    assert!(request.starts_with(b"\\46FD09042104"), "{request:?}");
    let code = request[request.len() - 2];
    let serial = [
        0x38, 0xff, 0xff, 0xff, 0xff, 0x18, 0xb1, 0x06, 0x16, 0xa2, 0x00, 0x05,
    ];
    let mut cal = vec![0x8d, 4];
    cal.extend_from_slice(&serial);
    routed_pci_reply(&mut remote_write, &[253], 4, &cal).await;
    remote_write.write_all(&[code, b'.']).await.unwrap();

    let (replacement, _replacement_remote) = pci();
    service.set_pci(replacement).await;
    tokio::time::advance(Duration::from_secs(2)).await;
    tokio::task::yield_now().await;
    let response = command.await.unwrap();
    assert_eq!(response.status, 408, "{response:?}");
    assert!(response.final_text.contains("invalidated by PCI reconnect"));
    assert!(matches!(
        events.try_recv(),
        Err(tokio::sync::broadcast::error::TryRecvError::Empty)
    ));
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn aircon_help_and_native_validation_fail_before_pci_io() {
    let path = state_path();
    let (pci, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let mut client = ClientState::default();

    let help = service.handle(&mut client, "[h] AIRCON").await;
    assert_eq!(help.status, 101);
    let help = format_response(&help);
    assert!(help.starts_with("[h] 101-Help: AIRCON commands:\n"));
    assert!(help.ends_with(
        "[h] 101 Help:  AIRCON SET_ZONE_HVAC_MODE - Broadcast of HVAC mode and level required for a Zone or Zones.\n"
    ));

    let cases = [
        ("AIRCON BOGUS", 400, "400 Syntax Error."),
        (
            "AIRCON REFRESH 254/172",
            400,
            "400 Syntax Error: Missing parameter : <ward>",
        ),
        (
            "AIRCON REFRESH 254/172 1 EXTRA",
            400,
            "400 Syntax Error: Too many parameters",
        ),
        (
            "AIRCON REFRESH 254/171 1",
            402,
            "402 Operation not supported by: 254/171",
        ),
        (
            "AIRCON REFRESH //OTHER/254/172 1",
            404,
            "404 Network is not connected to this service",
        ),
        (
            "AIRCON REFRESH 254/172 x",
            405,
            "405 Parameter out of range: 254/172 (For input string: \"x\")",
        ),
        (
            "AIRCON REFRESH 254/172 256",
            408,
            "408 Operation failed: 254/172 (bad ward number: 256)",
        ),
        (
            "AIRCON SET_ZONE_HVAC_MODE 254/172 1 7 3 0 1 0 1 255 23 64",
            408,
            "408 Operation failed: 254/172 (Zone index is out of range: 7)",
        ),
        (
            "AIRCON SET_ZONE_HVAC_MODE 254/172 1 0,1,2 5 0 1 0 1 255 23 64",
            408,
            "408 Operation failed: 254/172 (HVAC Plant Mode is out of range: 5)",
        ),
        (
            "AIRCON SET_ZONE_HUMIDITY_MODE 254/172 1 0,1,2 4 0 0 0 1 2 40 64",
            408,
            "408 Operation failed: 254/172 (Humidity Plant Mode is out of range: 4)",
        ),
        (
            "AIRCON SET_ZONE_HVAC_MODE 254/172 1 0,1,2 3 2 1 0 1 255 23 64",
            400,
            "400 Syntax Error: Invalid boolean parameter : <rawlevel>",
        ),
        (
            "AIRCON SET_ZONE_HVAC_MODE 254/172 1 0,1,2 3 0 1 0 1 255 65536 64",
            400,
            "400 Syntax Error: Integer parameter is out of range : <level>",
        ),
        (
            "AIRCON SET_ZONE_HVAC_MODE 254/172 1 0 3 0 1 0 1 -1 23 64",
            408,
            "408 Operation failed: 254/172 (HVAC Plant Type is out of range: -1)",
        ),
        (
            "AIRCON SET_ZONE_HVAC_MODE 254/172 1 0 3 0 1 0 1 2147483648 23 64",
            400,
            "400 Syntax Error: Invalid integer parameter : <type>",
        ),
        (
            "AIRCON SET_ZONE_HVAC_MODE 254/172 1 0 3 0 1 0 1 255 23 256",
            400,
            "400 Syntax Error: Integer parameter is out of range : <auxlevel>",
        ),
    ];
    for (index, (command, status, final_text)) in cases.into_iter().enumerate() {
        let response = service
            .handle(&mut client, &format!("[{index}] {command}"))
            .await;
        assert_eq!(response.status, status, "{command}: {response:?}");
        assert_eq!(response.final_text, final_text, "{command}");
    }
    assert!(
        tokio::time::timeout(std::time::Duration::from_millis(20), remote.read_u8())
            .await
            .is_err(),
        "invalid AIRCON commands must not reach PCI"
    );
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn armed_auth_gate_covers_mutations_but_not_help() {
    let path = state_path();
    let (pci_client, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    service
        .set_auth_token_hash(crate::auth::sha256(b"aircon-test-token"))
        .unwrap();
    let mut client = ClientState::default();
    assert_eq!(
        service.handle(&mut client, "[1] AIRCON ?").await.status,
        101
    );
    for (line, final_text) in [
        (
            "[cgl] CGL IMPORT ?",
            "101 Help: syntax: CGL IMPORT <project-name> << <end-tag>>",
        ),
        (
            "[repository] REPOSITORY USE ?",
            "101 Help: syntax: REPOSITORY USE NUMERIC_INDEX",
        ),
        (
            "[transform] TRANSFORM PROJECT ?",
            "101 Help: syntax: TRANSFORM PROJECT [--test] <project-name> [<xslt-file-name> [<output-project-name>]]",
        ),
    ] {
        let response = service.handle(&mut client, line).await;
        assert_eq!(response.status, 101, "{line}: {response:?}");
        assert_eq!(response.final_text, final_text, "{line}");
    }
    let mut restricted = ClientState {
        recovery_only: true,
        ..ClientState::default()
    };
    assert_eq!(
        service
            .handle(&mut restricted, "[restricted] CGL IMPORT ?")
            .await
            .final_text,
        "420 LOGIN required"
    );
    let mut monitor = ClientState {
        access_level: Some(CgateAccessLevel::Monitor),
        ..ClientState::default()
    };
    assert_eq!(
        service
            .handle(&mut monitor, "[role] CGL EXPORT ?")
            .await
            .final_text,
        "420 Access denied."
    );
    assert_eq!(
        service
            .handle(&mut client, "[import] CGL IMPORT HARNESS")
            .await
            .final_text,
        "420 LOGIN required"
    );
    assert!(!super::requires_programming_auth(
        "AIRCON",
        "REFRESH",
        &["AIRCON".into(), "REFRESH".into()]
    ));
    let response = service
        .handle(&mut client, "[2] AIRCON SET_WARD_OFF 254/$AC 1")
        .await;
    assert_eq!(response.status, 420);
    assert_eq!(response.final_text, "420 LOGIN required");
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn observed_aircon_status_and_command_are_fanned_to_event_clients() {
    let path = state_path();
    let (pci, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let mut events = service.events.subscribe();

    service
        .observe(&CBusEvent::AirconStatus {
            source: Some(4),
            status: cbus_protocol::sal::aircon::AirconStatus::ZoneHvacPlantStatus {
                ward: 1,
                zones: 7,
                plant_type: 3,
                status: 1,
                error: 0,
            },
        })
        .await;
    assert_eq!(
        events.try_recv().unwrap(),
        "#e# aircon zone_hvac_plant_status //HARNESS/254/172 1 0,1,2 3 1 0 sourceUnit=4"
    );

    service
        .observe(&CBusEvent::AirconCommand {
            source: None,
            command: AirconCommand::Refresh { ward: 1 },
        })
        .await;
    assert_eq!(
        events.try_recv().unwrap(),
        "#e# aircon refresh //HARNESS/254/172 1 sourceUnit=0"
    );

    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn audio_help_validation_routing_and_auth_fail_before_pci_io() {
    let path = state_path();
    let (pci, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    service
        .set_auth_token_hash(crate::auth::sha256(b"audio-test-token"))
        .unwrap();
    let mut client = ClientState::default();

    let help = service.handle(&mut client, "[h] AUDIO").await;
    assert_eq!(help.status, 101);
    let help = format_response(&help);
    assert!(help.starts_with("[h] 101-Help: AUDIO commands:\n"));
    assert!(help.ends_with(
        "[h] 101 Help:  AUDIO ZONE_FEED_LABEL_REQUEST - Send a Zone Feed Label Request command\n"
    ));

    for request in [
        "CURRENT_FEED",
        "OUTPUT_DEVICE_STATUS_REQUEST",
        "OUTPUT_ERROR_CODE",
        "REQUEST_CURRENT_FEED",
        "ZONE_DESCRIPTOR_REQUEST",
        "ZONE_FEED_LABEL_REQUEST",
    ] {
        assert!(!super::requires_programming_auth(
            "AUDIO",
            request,
            &["AUDIO".into(), request.into()]
        ));
    }
    let locked = service
        .handle(&mut client, "[locked] AUDIO ON 254/205 1 2 4")
        .await;
    assert_eq!(locked.final_text, "420 LOGIN required");

    for (command, status) in [
        ("AUDIO BOGUS", 400),
        ("AUDIO ON 254/204 1 2 4", 420),
        ("AUDIO REQUEST_CURRENT_FEED //OTHER/254/205 1 2", 401),
        ("AUDIO REQUEST_CURRENT_FEED 254/204 1 2", 402),
        ("AUDIO REQUEST_CURRENT_FEED 254/205 3 2", 400),
        ("AUDIO REQUEST_CURRENT_FEED 254/205 1 8", 400),
        ("AUDIO REQUEST_CURRENT_FEED 254/205 Z 256", 400),
        ("AUDIO OUTPUT_DEVICE_STATUS_REQUEST 254/205 1", 400),
        ("AUDIO CURRENT_FEED 254/205 1 2 4 5", 400),
    ] {
        let response = service.handle(&mut client, &format!("[v] {command}")).await;
        assert_eq!(response.status, status, "{command}: {response:?}");
    }
    assert!(
        tokio::time::timeout(std::time::Duration::from_millis(20), remote.read_u8())
            .await
            .is_err(),
        "rejected AUDIO commands must not reach PCI"
    );
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn audio_native_error_envelopes_are_exact_and_make_no_pci_write() {
    let path = state_path();
    let (pci, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let mut client = ClientState::default();
    let cases = [
        ("AUDIO BOGUS", "400 Syntax Error."),
        (
            "AUDIO ON",
            "400 Syntax Error: Missing parameter : <application>",
        ),
        (
            "AUDIO ON 254/205",
            "400 Syntax Error: Missing parameter : <multiplexer>",
        ),
        (
            "AUDIO ON 254/205 0 0",
            "400 Syntax Error: Missing parameter : <function code>",
        ),
        (
            "AUDIO ON 254/205 0 0 0 EXTRA",
            "400 Syntax Error: Too many parameters",
        ),
        (
            "AUDIO CURRENT_FEED ?",
            "401 Bad object or device ID: ? (Network not found)",
        ),
        (
            "AUDIO ON //OTHER/254/205 0 0 0",
            "401 Bad object or device ID: //OTHER/254/205 (Object not found)",
        ),
        (
            "AUDIO ON 253/205 0 0 0",
            "401 Bad object or device ID: 253/205 (Network not found)",
        ),
        (
            "AUDIO ON 254/204 0 0 0",
            "402 Operation not supported by: 254/204",
        ),
        (
            "AUDIO ON 254/205 X 0",
            "400 Syntax Error: Invalid integer parameter : <multiplexer>",
        ),
        (
            "AUDIO ON 254/205 Z",
            "400 Syntax Error: Missing parameter : <zone code>",
        ),
        (
            "AUDIO CURRENT_FEED 254/205 0 0 0 5",
            "400 Syntax Error: Integer parameter is out of range : <gain>",
        ),
        (
            "AUDIO OUTPUT_COMMON_CONTROL 254/205 1",
            "400 Syntax Error: Integer parameter is out of range : <control code>",
        ),
        (
            "AUDIO OUTPUT_ERROR_CODE 254/205 Z 0 0",
            "400 Syntax Error: Too many parameters",
        ),
        (
            "AUDIO MUTE 254/205 0 0 -1",
            "400 Syntax Error: Integer parameter is out of range : <mode>",
        ),
        (
            "AUDIO RAMP 254/205 0 0 0 0 16",
            "400 Syntax Error: Integer parameter is out of range : <rate>",
        ),
        (
            "AUDIO SET_FEED 254/205 Z 0 2",
            "400 Syntax Error: Integer parameter is out of range : <option>",
        ),
    ];
    for (index, (command, expected)) in cases.into_iter().enumerate() {
        let response = service
            .handle(&mut client, &format!("[error-{index}] {command}"))
            .await;
        assert_eq!(response.final_text, expected, "{command}");
    }
    assert!(
        tokio::time::timeout(Duration::from_millis(20), remote.read_u8())
            .await
            .is_err(),
        "invalid AUDIO forms must fail before PCI I/O"
    );
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn every_audio_command_uses_native_confirmed_sal() {
    let path = state_path();
    let (pci, remote) = pci();
    let (remote_read, mut remote_write) = tokio::io::split(remote);
    let mut remote_read = BufReader::new(remote_read);
    let reset = tokio::spawn({
        let pci = pci.clone();
        async move { pci.pci_reset().await }
    });
    for _ in 0..8 {
        let mut line = Vec::new();
        remote_read.read_until(b'\r', &mut line).await.unwrap();
    }
    reset.await.unwrap().unwrap();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();

    let cases = [
        ("AUDIO CURRENT_FEED 254/205 1 2 4 4", "\\05CD0022E854"),
        ("AUDIO DYNAMIC_1 254/205 1 2", "\\05CD00025600"),
        ("AUDIO DYNAMIC_2 254/205 1 2", "\\05CD000256FF"),
        ("AUDIO HIGH_PRIORITY 254/205 2 99 7", "\\05CD003AC263"),
        ("AUDIO MUTE 254/205 1 2 1", "\\05CD00025501"),
        ("AUDIO NEXT_FEED 254/205 1 2", "\\05CD00025602"),
        ("AUDIO NEXT_LANGUAGE 254/205 1 2", "\\05CD00025611"),
        ("AUDIO OFF 254/205 1 2 4", "\\05CD000154"),
        ("AUDIO ON 254/205 Z 200", "\\05CD0079C8"),
        ("AUDIO OUTPUT_COMMON_CONTROL 254/205 0", "\\05CD0002E500"),
        (
            "AUDIO OUTPUT_DEVICE_STATUS_REQUEST 254/205 0",
            "\\05CD0002E300",
        ),
        ("AUDIO OUTPUT_ERROR_CODE 254/205 1 2 7", "\\05CD0002E657"),
        ("AUDIO PREVIOUS_FEED 254/205 1 2", "\\05CD00025605"),
        ("AUDIO RAMP 254/205 1 2 4 123 15", "\\05CD007A547B"),
        ("AUDIO REQUEST_CURRENT_FEED 254/205 1 2", "\\05CD0002E750"),
        ("AUDIO SET_FEED 254/205 1 2 4 1", "\\05CD000AE954"),
        ("AUDIO TERMINATERAMP 254/205 1 2 4", "\\05CD000954"),
        (
            "AUDIO ZONE_DESCRIPTOR_REQUEST 254/205 1 2",
            "\\05CD0002E050",
        ),
        (
            "AUDIO ZONE_FEED_LABEL_REQUEST 254/205 1 2",
            "\\05CD0002E250",
        ),
    ];
    for (index, (command, expected)) in cases.into_iter().enumerate() {
        let sending = tokio::spawn({
            let service = service.clone();
            let line = format!("[{index}] {command}");
            async move { service.handle(&mut ClientState::default(), &line).await }
        });
        let mut frame = Vec::new();
        remote_read.read_until(b'\r', &mut frame).await.unwrap();
        assert!(
            frame.starts_with(expected.as_bytes()),
            "{command}: {frame:?}"
        );
        let confirmation = frame[frame.len() - 2];
        remote_write.write_all(&[confirmation, b'.']).await.unwrap();
        let response = sending.await.unwrap();
        assert_eq!(response.final_text, "200 OK.", "{command}: {response:?}");
    }
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn observed_audio_commands_labels_and_icons_are_fanned_to_event_clients() {
    let path = state_path();
    let (pci, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let mut events = service.events.subscribe();
    service
        .observe(&CBusEvent::AudioCommand {
            source: Some(4),
            command: AudioCommand::CurrentFeed {
                address: AudioAddress::zone(1, 2, 4).unwrap(),
                gain: 3,
            },
        })
        .await;
    assert_eq!(
        events.try_recv().unwrap(),
        "#e# audio current_feed //HARNESS/254/205 1 2 4 3 sourceUnit=4"
    );
    service
        .observe(&CBusEvent::AudioEvent {
            source: None,
            event: cbus_protocol::sal::audio::AudioEvent::Label {
                address: AudioAddress::zone(1, 1, 4).unwrap(),
                options: 32,
                language: 1,
                bytes: b"EDLT".to_vec(),
            },
        })
        .await;
    assert_eq!(
        events.try_recv().unwrap(),
        "#e# audio label //HARNESS/254/205 1 1 4 0 1 1 45444C54 sourceUnit=0"
    );
    service
        .observe(&CBusEvent::AudioEvent {
            source: Some(5),
            event: cbus_protocol::sal::audio::AudioEvent::LoadIcon {
                address: AudioAddress::zone(1, 1, 4).unwrap(),
                options: 68,
                bytes: vec![1, 2, 3],
            },
        })
        .await;
    assert_eq!(
        events.try_recv().unwrap(),
        "#e# audio load_icon //HARNESS/254/205 1 1 4 68 2 010203 sourceUnit=5"
    );
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn security_invalid_forms_fail_before_io_and_mutations_require_auth() {
    let path = state_path();
    let (pci, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    service
        .set_auth_token_hash(crate::auth::sha256(b"security-test-token"))
        .unwrap();
    let mut client = ClientState::default();
    assert_eq!(
        service.handle(&mut client, "[h] SECURITY ?").await.status,
        101
    );
    assert!(!super::requires_programming_auth(
        "SECURITY",
        "STATUS_REQUEST",
        &["SECURITY".into(), "STATUS_REQUEST".into()]
    ));
    assert!(!super::requires_programming_auth(
        "SECURITY",
        "REQUEST_ZONE_NAME",
        &["SECURITY".into(), "REQUEST_ZONE_NAME".into()]
    ));
    let response = service
        .handle(&mut client, "[locked] SECURITY ARM 254/208 away")
        .await;
    assert_eq!(response.final_text, "420 LOGIN required");

    for (index, (command, status, final_text)) in [
        (
            "SECURITY STATUS_REQUEST 254/208 0",
            408,
            "408 Operation failed: 254/208 (bad status number)",
        ),
        ("SECURITY ARM 254/208 bogus", 420, "420 LOGIN required"),
        (
            "SECURITY REQUEST_ZONE_NAME 254/208 0",
            405,
            "405 Parameter out of range: 254/208 (Invalid Zone)",
        ),
        (
            "SECURITY REQUEST_ZONE_NAME 254/208 128",
            405,
            "405 Parameter out of range: 254/208 (Invalid Zone)",
        ),
        (
            "SECURITY REQUEST_ZONE_NAME 254/208 x",
            400,
            "400 Syntax Error: Invalid integer parameter : <zone>",
        ),
        (
            "SECURITY STATUS_REQUEST 254/207 1",
            402,
            "402 Operation not supported by: 254/207",
        ),
    ]
    .into_iter()
    .enumerate()
    {
        let response = service
            .handle(&mut client, &format!("[{index}] {command}"))
            .await;
        assert_eq!(response.status, status, "{command}: {response:?}");
        assert_eq!(response.final_text, final_text, "{command}");
    }
    assert!(
        tokio::time::timeout(std::time::Duration::from_millis(20), remote.read_u8())
            .await
            .is_err(),
        "rejected SECURITY commands must not reach PCI"
    );
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn observed_security_events_use_native_names_addresses_and_byte_escaping() {
    let path = state_path();
    let (pci, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let mut events = service.events.subscribe();
    service
        .observe(&CBusEvent::SecurityEvent {
            source: Some(4),
            event: cbus_protocol::sal::security::SecurityEvent::ZoneName {
                zone: 7,
                name: b"A B\\C\0\x7f1234".to_vec(),
            },
        })
        .await;
    assert_eq!(
        events.try_recv().unwrap(),
        "#e# security zone_name //HARNESS/254/208/7 A\\x20B\\\\C\\x00\\x7F1234 sourceUnit=4"
    );
    service
        .observe(&CBusEvent::SecurityCommand {
            source: None,
            command: SecurityCommand::RequestZoneName { zone: 127 },
        })
        .await;
    assert_eq!(
        events.try_recv().unwrap(),
        "#e# security request_zone_name //HARNESS/254/208/127 sourceUnit=0"
    );
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn telephony_help_errors_and_auth_are_native_and_fail_before_io() {
    let path = state_path();
    let (pci, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    service
        .set_auth_token_hash(crate::auth::sha256(b"telephony-test-token"))
        .unwrap();
    let mut client = ClientState::default();

    let help = service.handle(&mut client, "[h] TELEPHONY ?").await;
    assert_eq!(help.status, 101);
    assert_eq!(
        format_response(&help),
        concat!(
            "[h] 101-Help: TELEPHONY commands:\n",
            "[h] 101-Help:  TELEPHONY ? Help for these commands\n",
            "[h] 101-Help:  TELEPHONY CLEAR_DIVERSION - Command the telephony device to clear any diversion\n",
            "[h] 101-Help:  TELEPHONY DIVERT - Set a diversion for the telephony device\n",
            "[h] 101-Help:  TELEPHONY ISOLATE_SECONDARY_OUTLET - Set the isolation mode for the telephony device\n",
            "[h] 101-Help:  TELEPHONY RECALL_LAST_NUMBER_REQUEST - Request a last number recall from the telephony device\n",
            "[h] 101 Help:  TELEPHONY REJECT_INCOMING_CALL - Command the telephony device to reject the incoming call\n",
        )
    );
    assert!(!super::requires_programming_auth(
        "TELEPHONY",
        "RECALL_LAST_NUMBER_REQUEST",
        &["TELEPHONY".into(), "RECALL_LAST_NUMBER_REQUEST".into()]
    ));
    assert!(super::requires_programming_auth(
        "TELEPHONY",
        "DIVERT",
        &["TELEPHONY".into(), "DIVERT".into()]
    ));
    let locked = service
        .handle(&mut client, "[locked] TELEPHONY CLEAR_DIVERSION 254/224")
        .await;
    assert_eq!(locked.final_text, "420 LOGIN required");

    for (index, (command, expected)) in [
        ("TELEPHONY BOGUS", "400 Syntax Error."),
        (
            "TELEPHONY RECALL_LAST_NUMBER_REQUEST",
            "400 Syntax Error: Missing parameter : <application>",
        ),
        (
            "TELEPHONY RECALL_LAST_NUMBER_REQUEST 254/224",
            "400 Syntax Error: Missing parameter : <direction>",
        ),
        (
            "TELEPHONY RECALL_LAST_NUMBER_REQUEST 254/224 bogus",
            "400 Syntax Error: unknown <direction>",
        ),
        (
            "TELEPHONY RECALL_LAST_NUMBER_REQUEST 254/224 in EXTRA",
            "400 Syntax Error: Too many parameters",
        ),
        (
            "TELEPHONY RECALL_LAST_NUMBER_REQUEST ? in",
            "401 Bad object or device ID: ? (Network not found)",
        ),
        (
            "TELEPHONY RECALL_LAST_NUMBER_REQUEST //OTHER/254/224 in",
            "401 Bad object or device ID: //OTHER/254/224 (Object not found)",
        ),
        (
            "TELEPHONY RECALL_LAST_NUMBER_REQUEST 253/224 in",
            "401 Bad object or device ID: 253/224 (Network not found)",
        ),
        (
            "TELEPHONY RECALL_LAST_NUMBER_REQUEST 254/223 in",
            "402 Operation not supported by: 254/223",
        ),
        (
            "TELEPHONY DIVERT 254/224 12345678901234567",
            "420 LOGIN required",
        ),
    ]
    .into_iter()
    .enumerate()
    {
        let response = service
            .handle(&mut client, &format!("[{index}] {command}"))
            .await;
        assert_eq!(response.final_text, expected, "{command}");
    }
    assert!(
        tokio::time::timeout(Duration::from_millis(20), remote.read_u8())
            .await
            .is_err(),
        "rejected TELEPHONY forms must fail before PCI I/O"
    );
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn telephony_probed_role_responses_resolve_absent_target_without_pci() {
    let native: serde_json::Value = serde_json::from_str(include_str!(
        "../../../testdata/fixtures/native_cgate_authorization_probe.json"
    ))
    .unwrap();
    assert_eq!(native["oracle"]["cleanup_complete"], true);
    let path = state_path();
    let (pci, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let before = std::fs::read(&path).unwrap();
    for (subcommand, native_command) in [
        ("CLEAR_DIVERSION", "TELEPHONY CLEAR_DIVERSION 254/224"),
        (
            "RECALL_LAST_NUMBER_REQUEST",
            "TELEPHONY RECALL_LAST_NUMBER_REQUEST 254/224 out",
        ),
    ] {
        let command = native_command.replace("254/224", "253/224");
        for (role, current) in [
            (CgateAccessLevel::Monitor, None),
            (CgateAccessLevel::Operate, None),
            (CgateAccessLevel::Admin, Some("HARNESS".to_string())),
        ] {
            let mut client = ClientState {
                current,
                access_level: Some(role),
                ..ClientState::default()
            };
            let reply = service
                .handle(&mut client, &format!("[role] {command}"))
                .await;
            let native_reply = native["roles"][role.name()]["responses"][native_command]
                .as_str()
                .unwrap()
                .replace("254/224", "253/224");
            assert_eq!(reply.final_text, native_reply, "{subcommand} at {role:?}");
        }
    }
    // Resolving the known configured network must still deny physical
    // delivery below Program, regardless of whether the project is selected.
    for role in [CgateAccessLevel::Operate, CgateAccessLevel::Admin] {
        let mut client = ClientState {
            access_level: Some(role),
            ..ClientState::default()
        };
        for command in [
            "TELEPHONY CLEAR_DIVERSION 254/224",
            "TELEPHONY RECALL_LAST_NUMBER_REQUEST 254/224 out",
        ] {
            assert_eq!(
                service
                    .handle(&mut client, &format!("[known] {command}"))
                    .await
                    .final_text,
                "420 Access denied."
            );
        }
    }
    // Unprobed forms keep their established Program gate and response.
    let mut client = ClientState {
        access_level: Some(CgateAccessLevel::Operate),
        ..ClientState::default()
    };
    assert_eq!(
        service
            .handle(&mut client, "[other] TELEPHONY DIVERT 253/224 123")
            .await
            .final_text,
        "420 Access denied: TELEPHONY (Program access required)"
    );
    assert_eq!(std::fs::read(&path).unwrap(), before);
    assert!(
        tokio::time::timeout(Duration::from_millis(20), remote.read_u8())
            .await
            .is_err(),
        "denied and absent TELEPHONY targets must not write PCI"
    );
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn observed_telephony_commands_and_events_use_native_fanout() {
    let path = state_path();
    let (pci, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let mut events = service.events.subscribe();
    service
        .observe(&CBusEvent::TelephonyEvent {
            source: Some(4),
            event: cbus_protocol::sal::telephony::TelephonyEvent::LineOffHook {
                direction: TelephonyDirection::Out,
                reason: cbus_protocol::sal::telephony::OffHookReason::Data,
                number: b"12".to_vec(),
            },
        })
        .await;
    assert_eq!(
        events.try_recv().unwrap(),
        "#e# telephony line_off_hook //HARNESS/254/224 out data 12 sourceUnit=4"
    );
    service
        .observe(&CBusEvent::TelephonyCommand {
            source: None,
            command: TelephonyCommand::ClearDiversion,
        })
        .await;
    assert_eq!(
        events.try_recv().unwrap(),
        "#e# telephony clear_diversion //HARNESS/254/224 sourceUnit=0"
    );
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn confirmed_telephony_on_retired_pci_generation_fails_closed() {
    let path = state_path();
    let (old_pci, old_remote) = pci();
    let (old_read, mut old_write) = tokio::io::split(old_remote);
    let mut old_read = BufReader::new(old_read);
    let reset = tokio::spawn({
        let pci = old_pci.clone();
        async move { pci.pci_reset().await }
    });
    for _ in 0..8 {
        let mut line = Vec::new();
        old_read.read_until(b'\r', &mut line).await.unwrap();
    }
    reset.await.unwrap().unwrap();
    let service = Service::new(&fixture(), None, path.clone(), old_pci, None).unwrap();
    let command = tokio::spawn({
        let service = service.clone();
        async move {
            service
                .handle(
                    &mut ClientState::default(),
                    "[g] TELEPHONY RECALL_LAST_NUMBER_REQUEST 254/224 out",
                )
                .await
        }
    });
    let mut frame = Vec::new();
    old_read.read_until(b'\r', &mut frame).await.unwrap();
    assert!(frame.starts_with(b"\\05E0000A8101"), "{frame:?}");
    let confirmation = frame[frame.len() - 2];
    let (replacement, _replacement_remote) = pci();
    tokio::time::timeout(Duration::from_secs(2), service.set_pci(replacement))
        .await
        .expect("set_pci must complete");
    old_write.write_all(&[confirmation, b'.']).await.unwrap();
    let response = tokio::time::timeout(Duration::from_secs(2), command)
        .await
        .expect("retired generation command must complete")
        .unwrap();
    assert_eq!(response.status, 502, "{response:?}");
    assert_eq!(
        response.final_text,
        "502 Telephony delivery failed: PCI connection generation changed"
    );
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn confirmed_application_on_retired_pci_generation_fails_closed() {
    let path = state_path();
    let (old_pci, old_remote) = pci();
    let (old_read, mut old_write) = tokio::io::split(old_remote);
    let mut old_read = BufReader::new(old_read);
    let reset = tokio::spawn({
        let pci = old_pci.clone();
        async move { pci.pci_reset().await }
    });
    for _ in 0..8 {
        let mut line = Vec::new();
        old_read.read_until(b'\r', &mut line).await.unwrap();
    }
    reset.await.unwrap().unwrap();
    let service = Service::new(&fixture(), None, path.clone(), old_pci, None).unwrap();
    let command = tokio::spawn({
        let service = service.clone();
        async move {
            service
                .handle(
                    &mut ClientState::default(),
                    "[g] SECURITY STATUS_REQUEST 254/208 1",
                )
                .await
        }
    });
    let mut frame = Vec::new();
    old_read.read_until(b'\r', &mut frame).await.unwrap();
    assert!(frame.starts_with(b"\\05D00009A0"), "{frame:?}");
    let confirmation = frame[frame.len() - 2];
    let (replacement, _replacement_remote) = pci();
    tokio::time::timeout(Duration::from_secs(2), service.set_pci(replacement))
        .await
        .expect("set_pci must complete");
    old_write.write_all(&[confirmation, b'.']).await.unwrap();
    let response = tokio::time::timeout(Duration::from_secs(2), command)
        .await
        .expect("retired generation command must complete")
        .unwrap();
    assert_eq!(response.status, 502, "{response:?}");
    assert_eq!(
        response.final_text,
        "502 Security delivery failed: PCI connection generation changed"
    );
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn confirmed_audio_on_retired_pci_generation_fails_closed() {
    let path = state_path();
    let (old_pci, old_remote) = pci();
    let (old_read, mut old_write) = tokio::io::split(old_remote);
    let mut old_read = BufReader::new(old_read);
    let reset = tokio::spawn({
        let pci = old_pci.clone();
        async move { pci.pci_reset().await }
    });
    for _ in 0..8 {
        let mut line = Vec::new();
        old_read.read_until(b'\r', &mut line).await.unwrap();
    }
    reset.await.unwrap().unwrap();
    let service = Service::new(&fixture(), None, path.clone(), old_pci, None).unwrap();
    let command = tokio::spawn({
        let service = service.clone();
        async move {
            service
                .handle(
                    &mut ClientState::default(),
                    "[g] AUDIO REQUEST_CURRENT_FEED 254/205 1 2",
                )
                .await
        }
    });
    let mut frame = Vec::new();
    old_read.read_until(b'\r', &mut frame).await.unwrap();
    assert!(frame.starts_with(b"\\05CD0002E750"), "{frame:?}");
    let confirmation = frame[frame.len() - 2];
    let (replacement, _replacement_remote) = pci();
    tokio::time::timeout(Duration::from_secs(2), service.set_pci(replacement))
        .await
        .expect("set_pci must complete");
    old_write.write_all(&[confirmation, b'.']).await.unwrap();
    let response = tokio::time::timeout(Duration::from_secs(2), command)
        .await
        .expect("retired generation command must complete")
        .unwrap();
    assert_eq!(response.status, 502, "{response:?}");
    assert_eq!(
        response.final_text,
        "502 Audio delivery failed: PCI connection generation changed"
    );
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn mediatransport_confirmation_from_retired_generation_fails_closed() {
    let path = state_path();
    let (old_pci, old_remote) = pci();
    let (old_read, mut old_write) = tokio::io::split(old_remote);
    let mut old_read = BufReader::new(old_read);
    let reset = tokio::spawn({
        let pci = old_pci.clone();
        async move { pci.pci_reset().await }
    });
    for _ in 0..8 {
        let mut line = Vec::new();
        old_read.read_until(b'\r', &mut line).await.unwrap();
    }
    reset.await.unwrap().unwrap();
    let service = Service::new(&fixture(), None, path.clone(), old_pci, None).unwrap();
    let command = tokio::spawn({
        let service = service.clone();
        async move {
            service
                .handle(
                    &mut ClientState::default(),
                    "[g] MEDIATRANSPORT STATUS_REQUEST 254/192 2",
                )
                .await
        }
    });
    let mut frame = Vec::new();
    old_read.read_until(b'\r', &mut frame).await.unwrap();
    assert!(frame.starts_with(b"\\05C0007102"), "{frame:?}");
    let confirmation = frame[frame.len() - 2];
    let (replacement, _replacement_remote) = pci();
    tokio::time::timeout(Duration::from_secs(2), service.set_pci(replacement))
        .await
        .expect("set_pci must complete");
    old_write.write_all(&[confirmation, b'.']).await.unwrap();
    let response = tokio::time::timeout(Duration::from_secs(2), command)
        .await
        .expect("retired generation command must complete")
        .unwrap();
    assert_eq!(response.status, 502, "{response:?}");
    assert_eq!(
        response.final_text,
        "502 Media Transport delivery failed: PCI connection generation changed"
    );
    std::fs::remove_file(path).unwrap();
}

#[test]
fn mediatransport_native_integer_and_dequoted_text_grammar_is_retained() {
    assert_eq!(parse_media_integer("g", "0b1010", "operation").unwrap(), 10);
    assert_eq!(parse_media_integer("g", "0B1010", "operation").unwrap(), 10);
    assert_eq!(parse_media_integer("g", "0x7f", "category").unwrap(), 127);
    assert_eq!(parse_media_integer("g", "0X7F", "category").unwrap(), 127);
    assert_eq!(parse_media_integer("g", "$7F", "category").unwrap(), 127);
    assert_eq!(parse_media_integer("g", "127", "category").unwrap(), 127);
    assert!(parse_media_integer("g", "0xGG", "category").is_err());

    assert_eq!(media_text(&["\"A\\", "B\\\"C\\\\D\""]), "A B\"C\\D");
    assert_eq!(media_text(&["\"A\\", "B"]), "A B");
    assert_eq!(media_text(&["plain\\", "text"]), "plain\\ text");
}

#[tokio::test]
async fn database_survives_restart_but_live_state_and_sessions_do_not() {
    let path = state_path();
    let (pci, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci.clone(), None).unwrap();
    let mut client = ClientState::default();
    assert_eq!(
        service
            .handle(
                &mut client,
                "[1] DBSETSAFE //HARNESS/254/p/5/TagName Changed"
            )
            .await
            .status,
        200
    );
    service
        .observe(&CBusEvent::LightingOn {
            source: Some(4),
            app: 56,
            group: 1,
        })
        .await;
    assert!(service
        .handle(&mut client, "[2] GET //HARNESS/254/56/1 level")
        .await
        .final_text
        .ends_with("level=255"));
    assert_eq!(
        service
            .handle(&mut client, "[2a] SCENE RECORD house evening")
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut client, "[3] PP LOCK L //HARNESS/254")
            .await
            .status,
        200
    );
    let restarted = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let model = restarted.model.lock().await;
    assert_eq!(
        model.projects["HARNESS"].networks[&254].units[&5].fields["TagName"],
        "Changed"
    );
    assert!(model.projects["HARNESS"].networks[&254].levels.is_empty());
    assert!(model.projects["HARNESS"].networks[&254].physical.is_empty());
    assert!(model.locks.is_empty());
    assert_eq!(
        model.scene_snapshots["house/evening"],
        vec![("//HARNESS/254/56/1".to_string(), 255)]
    );
    drop(model);
    assert_eq!(
        restarted
            .handle(&mut client, "[4] GET //HARNESS/254/56/1 level")
            .await
            .status,
        300
    );
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn new_units_groups_and_phantoms_survive_service_restart_as_database_only_objects() {
    let path = state_path();
    let (pci_client, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client.clone(), None).unwrap();
    let mut client = ClientState::default();
    for command in [
        "[new-group] NEW GROUP //HARNESS/254/56/44",
        "[new-phantom] NEW PHANTOM //HARNESS/254/56/45 91",
        "[new-unit] NEW UNIT //HARNESS/254/p/20 KEYE1 2.5.00",
    ] {
        let response = service.handle(&mut client, command).await;
        assert_eq!(response.status, 200, "{command}: {response:?}");
    }
    drop(service);

    let restarted = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut restarted_client = ClientState::default();
    let unit = restarted
        .handle(
            &mut restarted_client,
            "[show-unit] SHOW //HARNESS/254/p/20 Type",
        )
        .await;
    assert_eq!(unit.final_text, "300 //HARNESS/254/p/20: Type=KEYE1");
    let group = restarted
        .handle(
            &mut restarted_client,
            "[show-group] SHOW //HARNESS/254/56/44 *",
        )
        .await;
    assert_eq!(group.status, 300);
    assert!(group
        .lines
        .iter()
        .any(|line| line == "300-//HARNESS/254/56/44: Level=0"));
    let tree = restarted
        .handle(&mut restarted_client, "[tree] TREE //HARNESS/254")
        .await;
    assert_eq!(tree.status, 320);
    assert!(tree.lines.iter().any(|line| line == "320-  Unit count=0"));
    assert!(tree
        .lines
        .iter()
        .any(|line| line.contains("//HARNESS/254/p/20 ($14) type=KEYE1")));
    assert!(tree
        .lines
        .iter()
        .any(|line| { line.contains("//HARNESS/254/56/45 ($2d)") && line.ends_with("(phantom)") }));
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn legacy_database_network_oid_is_migrated_once_and_persisted() {
    let path = state_path();
    let (first_pci, _remote) = pci();
    drop(Service::new(&fixture(), None, path.clone(), first_pci, None).unwrap());

    let mut document: serde_json::Value =
        serde_json::from_slice(&std::fs::read(&path).unwrap()).unwrap();
    document["projects"]["HARNESS"]["networks"]["254"]
        .as_object_mut()
        .unwrap()
        .remove("oid");
    std::fs::write(&path, serde_json::to_vec(&document).unwrap()).unwrap();

    let (pci, _remote) = pci();
    let migrated = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let oid = migrated.model.lock().await.projects["HARNESS"].networks[&254]
        .oid
        .clone();
    assert!(!oid.is_empty());
    drop(migrated);

    let saved: serde_json::Value = serde_json::from_slice(&std::fs::read(&path).unwrap()).unwrap();
    assert_eq!(saved["projects"]["HARNESS"]["networks"]["254"]["oid"], oid);
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn programming_ownership_and_unimplemented_hardware_are_enforced() {
    let path = state_path();
    let (pci, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let mut first = ClientState::default();
    let mut second = ClientState::default();
    assert_eq!(
        service
            .handle(&mut first, "[1] PP LOCK L //HARNESS/254")
            .await
            .status,
        200
    );
    assert_eq!(
        service.handle(&mut second, "[2] PP START S L").await.status,
        420
    );
    assert_eq!(
        service.handle(&mut first, "[3] PP START S L").await.status,
        200
    );
    assert_eq!(
        service
            .handle(&mut second, "[4] PP SET S Field value")
            .await
            .status,
        420
    );
    assert_eq!(
        service
            .handle(&mut first, "[5] PP SAVE S //HARNESS/254/p/5")
            .await
            .status,
        408
    );
    assert_eq!(
        service
            .handle(&mut first, "[5] AUDIO PLAY //HARNESS/254/192 1")
            .await
            .status,
        400,
        "the implemented AUDIO family retains native unknown-subcommand syntax"
    );
    assert_eq!(
        service
            .handle(&mut first, "[5] PP WRITE_PATCH //HARNESS/254/p/5 01",)
            .await
            .status,
        408
    );
    assert_eq!(
        service
            .handle(&mut first, "[5] SET //HARNESS/254/p/5 Address 5")
            .await
            .status,
        400
    );
    assert_eq!(
        service
            .handle(&mut first, "[6] PP LOAD S /db//HARNESS/254/p/5")
            .await
            .status,
        200
    );
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn pp_admin_and_programmer_queue_execute_without_automatic_replay() {
    let path = state_path();
    let (pci, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let mut owner = ClientState::default();
    let mut other = ClientState::default();

    assert_eq!(
        service
            .handle(&mut owner, "[1] PP LOCK L //HARNESS/254")
            .await
            .status,
        200
    );
    assert_eq!(
        service.handle(&mut owner, "[2] PP START S L").await.status,
        200
    );
    assert_eq!(
        service
            .handle(&mut owner, "[3] PP NEW S KEY1 1.2.67")
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut other, "[4] PP GET_RAW_DATA S 0 8")
            .await
            .status,
        420
    );
    assert_eq!(
        service
            .handle(&mut other, "[5] PP DEBUG mem S 0")
            .await
            .status,
        420
    );
    assert_eq!(
        service
            .handle(&mut owner, "[6] PP SET_RAW_DATA S 0 01020304")
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut owner, "[7] PP GET_RAW_DATA S 0 8")
            .await
            .final_text,
        "316 RawData=0102030400000000"
    );

    assert_eq!(
        service
            .handle(
                &mut owner,
                "[8] PROGRAMMER CREATE P \"Task Name\" \"Display Route\"",
            )
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut owner, "[9] PROGRAMMER TEST P diagnostic payload")
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut owner, "[10] PROGRAMMER ADD_INSTRUCTION P PP_END S")
            .await
            .status,
        200
    );
    let before = service.handle(&mut owner, "[11] PROGRAMMER STATUS P").await;
    assert!(before.lines[0].contains("\"remainingSeconds\":4"));
    let start = service
        .handle(&mut owner, "[12] PROGRAMMER TRIGGER P START")
        .await;
    assert_eq!(start.status, 200);
    assert_eq!(start.final_text, "200 OK: triggered");
    tokio::time::timeout(Duration::from_secs(5), async {
        loop {
            let status = service
                .handle(&mut owner, "[wait] PROGRAMMER STATUS P")
                .await;
            if status.lines[0].contains("\"progState\":\"STOPPED\"") {
                break;
            }
            tokio::time::sleep(Duration::from_millis(25)).await;
        }
    })
    .await
    .unwrap();
    let after = service.handle(&mut owner, "[13] PROGRAMMER STATUS P").await;
    assert!(after.lines[0].contains("\"queueCount\":0"));
    assert!(after.lines[0].contains("\"totalCount\":2"));
    assert!(after.lines[0].contains("\"remainingSeconds\":0"));
    assert_eq!(
        service
            .handle(&mut other, "[13a] PP LOCK OTHER //HARNESS/254")
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut other, "[13b] PP START S OTHER")
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut other, "[13c] PP NEW S KEY1 1.2.67")
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut owner, "[13d] PP SET S First stale-owner")
            .await
            .status,
        420,
        "queued PP_END must revoke the accepting connection's ownership"
    );
    assert_eq!(
        service
            .handle(&mut owner, "[14] PROGRAMMER TRIGGER P START")
            .await
            .status,
        400,
        "a second START never replays confirmed work"
    );

    assert!(
        tokio::time::timeout(std::time::Duration::from_millis(25), remote.read_u8())
            .await
            .is_err(),
        "local PP/PROGRAMMER administration wrote to the PCI"
    );
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn programmer_worker_observes_pause_cancel_resume_and_stop() {
    let path = state_path();
    let (pci, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let mut client = ClientState::default();

    for line in [
        "[1] PROGRAMMER CREATE Paused \"Pause and cancel\" local",
        "[2] PROGRAMMER TEST Paused payload",
        "[3] PROGRAMMER ADD_INSTRUCTION Paused PP_END Missing",
    ] {
        assert_eq!(
            service.handle(&mut client, line).await.status,
            200,
            "{line}"
        );
    }
    assert_eq!(
        service
            .handle(&mut client, "[4] PROGRAMMER TRIGGER Paused START")
            .await
            .final_text,
        "200 OK: triggered"
    );
    tokio::time::timeout(Duration::from_secs(2), async {
        loop {
            let status = service
                .handle(&mut client, "[wait-running] PROGRAMMER STATUS Paused")
                .await;
            if status.lines[0].contains("\"progState\":\"RUNNING\"") {
                break;
            }
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
    assert_eq!(
        service
            .handle(&mut client, "[5] PROGRAMMER TRIGGER Paused PAUSE")
            .await
            .status,
        200
    );
    let paused = service
        .handle(&mut client, "[6] PROGRAMMER STATUS Paused")
        .await;
    assert!(paused.lines[0].contains("\"progState\":\"PAUSED\""));
    tokio::time::sleep(Duration::from_millis(1_100)).await;
    assert_eq!(
        service
            .handle(&mut client, "[7] PROGRAMMER STATUS Paused")
            .await
            .lines,
        paused.lines,
        "a paused TEST countdown must not advance"
    );
    assert_eq!(
        service
            .handle(&mut client, "[8] PROGRAMMER CANCEL_INSTRUCTION Paused 2")
            .await
            .final_text,
        "200 OK: cancelled"
    );
    assert_eq!(
        service
            .handle(&mut client, "[9] PROGRAMMER TRIGGER Paused RESUME")
            .await
            .status,
        200
    );
    tokio::time::timeout(Duration::from_secs(5), async {
        loop {
            let status = service
                .handle(&mut client, "[wait-stopped] PROGRAMMER STATUS Paused")
                .await;
            if status.lines[0].contains("\"progState\":\"STOPPED\"") {
                assert!(status.lines[0].contains("\"remainingSeconds\":0"));
                break;
            }
            tokio::time::sleep(Duration::from_millis(25)).await;
        }
    })
    .await
    .unwrap();

    for line in [
        "[10] PROGRAMMER CREATE Halted \"Explicit stop\" local",
        "[11] PROGRAMMER TEST Halted payload",
    ] {
        assert_eq!(
            service.handle(&mut client, line).await.status,
            200,
            "{line}"
        );
    }
    assert_eq!(
        service
            .handle(&mut client, "[12] PROGRAMMER TRIGGER Halted START")
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut client, "[13] PROGRAMMER TRIGGER Halted STOP")
            .await
            .status,
        200
    );
    tokio::time::sleep(Duration::from_millis(1_100)).await;
    let halted = service
        .handle(&mut client, "[14] PROGRAMMER STATUS Halted")
        .await;
    assert!(halted.lines[0].contains("\"progState\":\"STOPPED\""));
    assert!(halted.lines[0].contains("\"remainingSeconds\":3"));
    tokio::time::sleep(Duration::from_millis(1_100)).await;
    assert_eq!(
        service
            .handle(&mut client, "[15] PROGRAMMER STATUS Halted")
            .await
            .lines,
        halted.lines,
        "STOP must prevent later consumption or replay"
    );
    assert!(
        tokio::time::timeout(Duration::from_millis(25), remote.read_u8())
            .await
            .is_err(),
        "TEST lifecycle control emitted PCI traffic"
    );
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn deploy_queue_executes_and_retries_only_when_explicitly_requested() {
    let path = state_path();
    let (pci, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let mut client = ClientState::default();

    assert_eq!(
        service
            .handle(
                &mut client,
                "[1] PROGRAMMER CREATE Empty \"No work\" \"Local\"",
            )
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut client, "[2] DEPLOY_QUEUE ADD Empty")
            .await
            .final_text,
        "200 OK: added"
    );
    tokio::time::timeout(Duration::from_secs(2), async {
        loop {
            let list = service
                .handle(&mut client, "[wait] DEPLOY_QUEUE LIST")
                .await;
            if list.lines[0].contains("\"progState\":\"STOPPED\"") {
                break;
            }
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
    let list = service.handle(&mut client, "[3] DEPLOY_QUEUE LIST").await;
    assert_eq!(list.status, 200);
    assert!(list.lines[0].contains("\"progState\":\"STOPPED\""));

    assert_eq!(
        service
            .handle(
                &mut client,
                "[4] PROGRAMMER CREATE Work \"Physical\" \"//HARNESS/254\"",
            )
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut client, "[5] PROGRAMMER TEST Work payload")
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut client, "[7] DEPLOY_QUEUE ADD Work")
            .await
            .final_text,
        "200 OK: added"
    );
    tokio::time::timeout(Duration::from_secs(5), async {
        loop {
            let status = service
                .handle(&mut client, "[8] PROGRAMMER STATUS Work")
                .await;
            if status.lines[0].contains("\"progState\":\"STOPPED\"") {
                break;
            }
            tokio::time::sleep(Duration::from_millis(25)).await;
        }
    })
    .await
    .unwrap();
    assert_eq!(
        service
            .handle(&mut client, "[9] DEPLOY_QUEUE RETRY Work")
            .await
            .final_text,
        "200 OK: retry added"
    );
    tokio::time::timeout(Duration::from_secs(5), async {
        loop {
            let status = service
                .handle(&mut client, "[10] PROGRAMMER STATUS Work")
                .await;
            if status.lines[0].contains("\"progState\":\"STOPPED\"") {
                break;
            }
            tokio::time::sleep(Duration::from_millis(25)).await;
        }
    })
    .await
    .unwrap();
    assert!(
        tokio::time::timeout(std::time::Duration::from_millis(25), remote.read_u8())
            .await
            .is_err(),
        "deployment queue administration wrote to the PCI"
    );
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn programmer_dali_instruction_grammar_reuses_public_dispatch() {
    let path = state_path();
    let (pci, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let mut client = ClientState::default();
    for (id, kind, arguments) in [
        (1, "DALI_READ", vec!["//HARNESS/254/p/5".to_string()]),
        (2, "DALI_PROGRAM", vec!["//HARNESS/254/p/5".to_string()]),
        (
            3,
            "DALI",
            vec![
                "RECALL_MAX".to_string(),
                "//HARNESS/254/p/5".to_string(),
                "A".to_string(),
            ],
        ),
    ] {
        let instruction = ProgrammerInstruction {
            id,
            kind: kind.to_string(),
            arguments,
            priority: 0,
            seconds: 1,
            cancelled: false,
            completed: false,
            active: false,
            remaining_seconds: 1,
        };
        let response = service
            .execute_programmer_instruction(&mut client, "grammar", &instruction)
            .await;
        assert_eq!(response.status, 401, "{kind}: {response:?}");
        assert!(
            response.final_text.contains("Bad object or device ID"),
            "{kind}: {}",
            response.final_text
        );
        assert!(
            !response.final_text.contains("SubCommand not found"),
            "{kind} must preserve the public DALI command/target order"
        );
    }
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn pp_write_patch_pins_selector_and_simulates_explicit_manifest_without_pci_io() {
    let path = state_path();
    let (pci, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let mut client = ClientState::default();
    let missing_version = service.handle(&mut client, "[pv0] PP PATCH_VERSION").await;
    assert_eq!(missing_version.status, 408, "{missing_version:?}");
    assert!(missing_version
        .final_text
        .contains("patchset.zip not Found"));
    for (line, status, text) in [
        (
            "[1] PP WRITE_PATCH //HARNESS/254/p/5",
            400,
            "not enough arguments",
        ),
        ("[2] PP WRITE_PATCH invalid 01", 401, "Bad address"),
        (
            "[2a] PP WRITE_PATCH //HARNESS/254/p/5/FirmwareVersion 01",
            401,
            "Bad address",
        ),
        (
            "[2b] PP WRITE_PATCH //HARNESS/254/p/0 01",
            400,
            "unit address from 1 through 254",
        ),
        (
            "[2c] PP WRITE_PATCH //HARNESS/254/p/255 01",
            400,
            "unit address from 1 through 254",
        ),
        (
            "[3] PP WRITE_PATCH //HARNESS/254/p/5 100",
            408,
            "bad patch version",
        ),
        (
            "[3b] PP WRITE_PATCH //HARNESS/254/p/5 -1",
            400,
            "bad patch version",
        ),
        (
            "[3c] PP WRITE_PATCH //HARNESS/254/p/5 -2",
            408,
            "bad patch version",
        ),
        (
            "[4] PP WRITE_PATCH //HARNESS/254/p/5 01 SIMULATE ignored",
            408,
            "No patch manifest",
        ),
    ] {
        let response = service.handle(&mut client, line).await;
        assert_eq!(response.status, status, "{line}: {response:?}");
        assert!(response.final_text.contains(text), "{line}: {response:?}");
    }
    assert!(
        tokio::time::timeout(Duration::from_millis(25), remote.read_u8())
            .await
            .is_err(),
        "invalid or unconfigured WRITE_PATCH emitted PCI traffic"
    );

    assert_eq!(
        service
            .handle(&mut client, "[mkdir] FILE MKDIR %HARNESS%/patchsets")
            .await
            .status,
        200
    );
    let manifest = r#"{"schema":"cmqttd.pp-patch/v1","version":"house-1","patches":[{"unitType":"KEYGL5","minFirmware":"5.0","maxFirmware":"6.0","patchVersion":"01","currentPatchVersions":["00"],"blocks":[{"parameter":114,"dataHex":"aabb"},{"parameter":247,"dataHex":"cc"}]}]}"#;
    let encoded = base64::engine::general_purpose::STANDARD.encode(manifest);
    assert_eq!(
        service
            .handle_document(
                &mut client,
                "[upload] FILE UPLOAD %HARNESS%/patchsets/cmqttd-patches.json",
                &encoded,
            )
            .await
            .status,
        200
    );
    let version = service.handle(&mut client, "[v] PP PATCH_VERSION").await;
    assert_eq!(version.status, 301, "{version:?}");
    assert_eq!(version.final_text, "301 version=house-1");
    {
        let mut model = service.model.lock().await;
        model.access = AccessLevel::Admin;
    }
    let denied = service
        .handle(&mut client, "[denied-version] PP PATCH_VERSION DEBUG")
        .await;
    assert_eq!(denied.status, 420, "{denied:?}");
    assert!(denied.lines.is_empty());
    service.model.lock().await.access = AccessLevel::Program;
    service.model.lock().await.allow_programming = false;
    let denied = service
        .handle(&mut client, "[disabled-version] PP PATCH_VERSION")
        .await;
    assert_eq!(denied.status, 420, "{denied:?}");
    let denied = service
        .handle(
            &mut client,
            "[disabled-write] PP WRITE_PATCH //HARNESS/254/p/5 01 simulate",
        )
        .await;
    assert_eq!(denied.status, 420, "{denied:?}");
    service.model.lock().await.allow_programming = true;
    let debug = service
        .handle(&mut client, "[vd] PP PATCH_VERSION DeBuG ignored")
        .await;
    assert_eq!(debug.status, 347, "{debug:?}");
    assert_eq!(debug.final_text, "347 type: 3 start add: $f7 bytes: $cc");
    assert_eq!(
        debug.lines,
        [
            "301-version=house-1",
            "347-Patch name: %HARNESS%/patchsets/cmqttd-patches.json#1",
            "347-type: 0 start add: $72 bytes: $aa $bb",
        ]
    );
    let unknown_debug = service
        .handle(&mut client, "[vu] PP PATCH_VERSION other DEBUG")
        .await;
    assert!(unknown_debug.lines.is_empty());

    let mismatch = service
        .handle(
            &mut client,
            &format!(
                "[sha] PP WRITE_PATCH //HARNESS/254/p/5 01 EXPECT_SHA256={}",
                "0".repeat(64)
            ),
        )
        .await;
    assert_eq!(mismatch.status, 409, "{mismatch:?}");
    assert!(mismatch.final_text.contains("does not match"));
    let simulated = service
        .handle(
            &mut client,
            "[sim] PP WRITE_PATCH //HARNESS/254/p/5 01 SiMuLaTe ignored",
        )
        .await;
    assert_eq!(simulated.status, 200, "{simulated:?}");
    assert!(simulated
        .lines
        .iter()
        .any(|line| line.contains("(simulate)")));
    assert!(simulated.lines.iter().any(|line| line.contains("sha256 ")));
    assert!(simulated
        .lines
        .iter()
        .any(|line| line.contains("block 2 of 2 at $f7:cc unlock")));
    assert!(
        tokio::time::timeout(Duration::from_millis(25), remote.read_u8())
            .await
            .is_err(),
        "SIMULATE emitted PCI traffic"
    );

    let unsafe_manifest = r#"{"schema":"cmqttd.pp-patch/v1","version":"safe\r\n[evil] 200 OK","patches":[{"unitType":"KEYGL5","minFirmware":"5.0","maxFirmware":"6.0","patchVersion":"01","currentPatchVersions":["00"],"blocks":[{"parameter":114,"dataHex":"aa"}]}]}"#;
    let encoded = base64::engine::general_purpose::STANDARD.encode(unsafe_manifest);
    assert_eq!(
        service
            .handle_document(
                &mut client,
                "[unsafe] FILE UPLOAD %HARNESS%/patchsets/cmqttd-patches.json",
                &encoded,
            )
            .await
            .status,
        200
    );
    let rejected = service
        .handle(&mut client, "[pvbad] PP PATCH_VERSION")
        .await;
    assert_eq!(rejected.status, 408, "{rejected:?}");
    assert!(rejected.lines.is_empty());
    assert!(!rejected.final_text.contains('\r'));
    assert!(!rejected.final_text.contains('\n'));
    std::fs::remove_file(path).unwrap();
}

#[test]
fn patch_result_progress_reports_the_actual_physical_disposition() {
    let patch = pp_patch::ResolvedPatch {
        manifest_path: "%P%/patchsets/cmqttd-patches.json".to_string(),
        manifest_version: "v1".to_string(),
        manifest_sha256: "a".repeat(64),
        unit_type: "KEYGL5".to_string(),
        min_firmware: "5".to_string(),
        max_firmware: "6".to_string(),
        target_version: 1,
        current_versions: vec![0],
        patch_version_parameter: 0xf2,
        blocks: vec![pp_patch::ResolvedBlock {
            parameter: 0x72,
            data: vec![0xaa],
            unlock: false,
        }],
    };
    let full = patch_result_progress(&patch, PatchApplyDisposition::AppliedFullPipeline);
    assert!(full.iter().any(|line| line.contains("patch disable")));
    let repaired = patch_result_progress(&patch, PatchApplyDisposition::RepairedEnableOnly);
    assert!(repaired.iter().any(|line| line.contains("repaired")));
    assert!(!repaired.iter().any(|line| line.contains("patch disable")));
    let read_only = patch_result_progress(&patch, PatchApplyDisposition::AlreadyVerifiedReadOnly);
    assert!(read_only
        .iter()
        .any(|line| line.contains("no physical mutation")));
    assert!(!read_only.iter().any(|line| line.contains("patch disable")));
}

#[tokio::test]
async fn pp_write_patch_requires_exactly_one_live_identity_before_any_store() {
    async fn line<R: tokio::io::AsyncBufRead + Unpin>(reader: &mut R) -> Vec<u8> {
        let mut line = Vec::new();
        reader.read_until(b'\r', &mut line).await.unwrap();
        line
    }
    async fn reply<W: tokio::io::AsyncWrite + Unpin>(writer: &mut W, source: u8, cal: &[u8]) {
        let mut bytes = vec![0x86, source, 0x10, 0x01, 0x00];
        bytes.extend_from_slice(cal);
        let sum = bytes.iter().fold(0u8, |sum, byte| sum.wrapping_add(*byte));
        bytes.push(0u8.wrapping_sub(sum));
        let mut wire = hex::encode_upper(bytes).into_bytes();
        wire.extend_from_slice(b"\r\n");
        writer.write_all(&wire).await.unwrap();
    }

    let path = state_path();
    let (pci, remote) = pci();
    let (remote_read, mut remote_write) = tokio::io::split(remote);
    let mut remote_read = BufReader::new(remote_read);
    let reset = tokio::spawn({
        let pci = pci.clone();
        async move { pci.pci_reset().await }
    });
    for _ in 0..8 {
        line(&mut remote_read).await;
    }
    reset.await.unwrap().unwrap();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let mut client = ClientState::default();
    assert_eq!(
        service
            .handle(&mut client, "[mkdir] FILE MKDIR %HARNESS%/patchsets")
            .await
            .status,
        200
    );
    let manifest = r#"{"schema":"cmqttd.pp-patch/v1","version":"identity-test","patches":[{"unitType":"KEYGL5","minFirmware":"5.0","maxFirmware":"6.0","patchVersion":"01","currentPatchVersions":["00"],"blocks":[{"parameter":114,"dataHex":"aabb"}]}]}"#;
    let encoded = base64::engine::general_purpose::STANDARD.encode(manifest);
    assert_eq!(
        service
            .handle_document(
                &mut client,
                "[upload] FILE UPLOAD %HARNESS%/patchsets/cmqttd-patches.json",
                &encoded,
            )
            .await
            .status,
        200
    );

    let no_reply = tokio::spawn({
        let service = service.clone();
        async move {
            service
                .handle(
                    &mut ClientState::default(),
                    "[none] PP WRITE_PATCH //HARNESS/254/p/5 01",
                )
                .await
        }
    });
    let request = line(&mut remote_read).await;
    assert!(request.starts_with(b"\\4605002101"), "{request:?}");
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    tokio::time::sleep(Duration::from_millis(2100)).await;
    let response = tokio::time::timeout(Duration::from_secs(3), no_reply)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(response.status, 401, "{response:?}");
    assert!(response.final_text.contains("did not answer IDENTIFY"));

    let duplicates = tokio::spawn({
        let service = service.clone();
        async move {
            service
                .handle(
                    &mut ClientState::default(),
                    "[duplicate] PP WRITE_PATCH //HARNESS/254/p/5 $01",
                )
                .await
        }
    });
    let request = line(&mut remote_read).await;
    assert!(request.starts_with(b"\\4605002101"), "{request:?}");
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    let mut cal = vec![0x80 | (b"KEYGL5".len() as u8 + 1), 1];
    cal.extend_from_slice(b"KEYGL5");
    reply(&mut remote_write, 5, &cal).await;
    reply(&mut remote_write, 5, &cal).await;
    tokio::time::sleep(Duration::from_millis(2100)).await;
    let response = tokio::time::timeout(Duration::from_secs(3), duplicates)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(response.status, 409, "{response:?}");
    assert!(response.final_text.contains("More than one physical unit"));
    assert!(
        tokio::time::timeout(Duration::from_millis(25), line(&mut remote_read))
            .await
            .is_err(),
        "identity failure continued to firmware, unlock, or STORE"
    );
    std::fs::remove_file(path).unwrap();
}

#[tokio::test(start_paused = true)]
async fn pp_write_patch_physical_pipeline_persists_version_and_rejects_commit_races() {
    async fn line<R: tokio::io::AsyncBufRead + Unpin>(reader: &mut R) -> Vec<u8> {
        tokio::time::timeout(Duration::from_secs(2), async {
            let mut line = Vec::new();
            reader.read_until(b'\r', &mut line).await.unwrap();
            line
        })
        .await
        .expect("timed out waiting for scripted PCI request")
    }
    async fn reply<W: tokio::io::AsyncWrite + Unpin>(writer: &mut W, source: u8, cal: &[u8]) {
        let mut bytes = vec![0x86, source, 0x10, 0x01, 0x00];
        bytes.extend_from_slice(cal);
        let sum = bytes.iter().fold(0u8, |sum, byte| sum.wrapping_add(*byte));
        bytes.push(0u8.wrapping_sub(sum));
        let mut wire = hex::encode_upper(bytes).into_bytes();
        wire.extend_from_slice(b"\r\n");
        writer.write_all(&wire).await.unwrap();
    }
    async fn identify<R, W>(reader: &mut R, writer: &mut W, attribute: u8, value: &[u8])
    where
        R: tokio::io::AsyncBufRead + Unpin,
        W: tokio::io::AsyncWrite + Unpin,
    {
        let request = line(reader).await;
        assert!(
            request.starts_with(format!("\\46050021{attribute:02X}").as_bytes()),
            "{request:?}"
        );
        let code = request[request.len() - 2];
        writer.write_all(&[code, b'.']).await.unwrap();
        let mut cal = vec![0x80 | (value.len() as u8 + 1), attribute];
        cal.extend_from_slice(value);
        reply(writer, 5, &cal).await;
        tokio::task::yield_now().await;
        tokio::time::advance(Duration::from_secs(2)).await;
        tokio::task::yield_now().await;
    }
    async fn recall<R, W>(reader: &mut R, writer: &mut W, parameter: u8, data: &[u8])
    where
        R: tokio::io::AsyncBufRead + Unpin,
        W: tokio::io::AsyncWrite + Unpin,
    {
        let request = line(reader).await;
        assert!(
            request.starts_with(format!("\\4605001A{parameter:02X}{:02X}", data.len()).as_bytes()),
            "{request:?}"
        );
        let mut cal = vec![0x80 | (data.len() as u8 + 1), parameter];
        cal.extend_from_slice(data);
        reply(writer, 5, &cal).await;
    }
    async fn unlock<R, W>(reader: &mut R, writer: &mut W, parameter: u8) -> u8
    where
        R: tokio::io::AsyncBufRead + Unpin,
        W: tokio::io::AsyncWrite + Unpin,
    {
        let request = line(reader).await;
        assert!(
            request.starts_with(format!("\\46050011{parameter:02X}").as_bytes()),
            "{request:?}"
        );
        let code = request[request.len() - 2];
        let challenge = 0x5a;
        reply(writer, 5, &[0x82, parameter, challenge]).await;
        writer.write_all(&[code, b'.']).await.unwrap();
        challenge
    }
    async fn store<R, W>(
        reader: &mut R,
        writer: &mut W,
        parameter: u8,
        tag: u8,
        data: &[u8],
        locked: bool,
    ) where
        R: tokio::io::AsyncBufRead + Unpin,
        W: tokio::io::AsyncWrite + Unpin,
    {
        let challenge = if locked {
            Some(unlock(reader, writer, parameter).await)
        } else {
            None
        };
        let effective_tag = if parameter == 0xf7 {
            challenge.unwrap()
        } else {
            tag
        };
        let request = line(reader).await;
        let marker = format!(
            "{parameter:02X}{effective_tag:02X}{}",
            hex::encode_upper(data)
        );
        assert!(request
            .windows(marker.len())
            .any(|window| window == marker.as_bytes()));
        reply(writer, 5, &[0x32, parameter, effective_tag]).await;
        recall(reader, writer, parameter, data).await;
    }
    async fn drive<R, W>(
        reader: &mut R,
        writer: &mut W,
        current_version: u8,
        target_version: u8,
        service: &Arc<Service>,
        mutation: u8,
    ) where
        R: tokio::io::AsyncBufRead + Unpin,
        W: tokio::io::AsyncWrite + Unpin,
    {
        identify(reader, writer, 1, b"KEYGL5").await;
        identify(reader, writer, 2, b"5.5.00").await;
        recall(reader, writer, 0xf2, &[current_version]).await;
        store(reader, writer, 0x70, 0x85, &[0xff, 0xff], true).await;
        store(reader, writer, 0xf2, 0x86, &[0xff], true).await;
        store(reader, writer, 0x72, 0x73, &[0xaa, 0xbb], false).await;
        store(reader, writer, 0xf7, 0x73, &[0xcc], true).await;
        // Distinct native full verification pass.
        recall(reader, writer, 0x72, &[0xaa, 0xbb]).await;
        recall(reader, writer, 0xf7, &[0xcc]).await;
        store(reader, writer, 0xf2, 0x86, &[target_version], true).await;
        store(reader, writer, 0x70, 0x85, &[0x9d, 0x40], true).await;

        let final_request = line(reader).await;
        assert!(final_request.starts_with(b"\\4605001AF201"));
        if mutation == 1 {
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
                .units
                .get_mut(&5)
                .unwrap()
                .fields
                .insert("UnitName".to_string(), "Concurrent replacement".to_string());
        } else if mutation == 2 {
            service
                .model
                .lock()
                .await
                .file_store
                .remove("%HARNESS%/patchsets/cmqttd-patches.json");
        }
        reply(writer, 5, &[0x82, 0xf2, target_version]).await;
    }

    let path = state_path();
    let (pci_client, remote) = pci();
    let (remote_read, mut remote_write) = tokio::io::split(remote);
    let mut remote_read = BufReader::new(remote_read);
    let reset = tokio::spawn({
        let pci = pci_client.clone();
        async move { pci.pci_reset().await }
    });
    for _ in 0..8 {
        line(&mut remote_read).await;
    }
    reset.await.unwrap().unwrap();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    {
        let mut model = service.model.lock().await;
        let network = model
            .projects
            .get_mut("HARNESS")
            .unwrap()
            .networks
            .get_mut(&254)
            .unwrap();
        let mut physical = network.units[&5].clone();
        physical
            .fields
            .insert("PatchVersion".to_string(), "0".to_string());
        network.physical.insert(5, physical);
    }
    let mut events = service.events.subscribe();
    let mut client = ClientState::default();
    assert_eq!(
        service
            .handle(&mut client, "[mkdir] FILE MKDIR %HARNESS%/patchsets")
            .await
            .status,
        200
    );

    for (target, current, tag, mutation) in [
        (0xaf, 0x00, "first", 0),
        (0xb0, 0xaf, "record-race", 1),
        (0xb1, 0xb0, "manifest-race", 2),
    ] {
        if mutation == 2 {
            // Restore the deliberately raced record before starting the
            // independent manifest-replacement case.
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
                .units
                .get_mut(&5)
                .unwrap()
                .fields
                .insert("UnitName".to_string(), "Fixture eDLT".to_string());
        }
        let manifest = format!(
            r#"{{"schema":"cmqttd.pp-patch/v1","version":"physical-{tag}","patches":[{{"unitType":"KEYGL5","minFirmware":"5.0","maxFirmware":"6.0","patchVersion":"{target:02X}","currentPatchVersions":["{current:02X}"],"blocks":[{{"parameter":114,"dataHex":"aabb"}},{{"parameter":247,"dataHex":"cc"}}]}}]}}"#
        );
        let encoded = base64::engine::general_purpose::STANDARD.encode(manifest);
        assert_eq!(
            service
                .handle_document(
                    &mut client,
                    "[upload] FILE UPLOAD %HARNESS%/patchsets/cmqttd-patches.json",
                    &encoded,
                )
                .await
                .status,
            200
        );
        let command = tokio::spawn({
            let service = service.clone();
            async move {
                service
                    .handle(
                        &mut ClientState::default(),
                        &format!("[{tag}] PP WRITE_PATCH //HARNESS/254/p/5 {target:02X}"),
                    )
                    .await
            }
        });
        drive(
            &mut remote_read,
            &mut remote_write,
            current,
            target,
            &service,
            mutation,
        )
        .await;
        let response = command.await.unwrap();
        assert_eq!(
            service.model.lock().await.projects["HARNESS"].networks[&254].physical[&5].fields
                ["PatchVersion"],
            target.to_string(),
            "verified physical truth must update even when durable commit is rejected"
        );
        if mutation == 1 {
            assert_eq!(response.status, 409, "{response:?}");
            assert!(response.final_text.contains("record changed"));
        } else if mutation == 2 {
            assert_eq!(response.status, 409, "{response:?}");
            assert!(response.final_text.contains("manifest changed"));
        } else {
            assert_eq!(response.status, 200, "{response:?}");
            let event = events.recv().await.unwrap();
            assert!(event.contains("version=AF"), "{event}");
            assert!(event.contains("manifest_sha256="), "{event}");
            let get = service
                .handle(
                    &mut ClientState::default(),
                    "[get-patch] GET //HARNESS/254/p/5 PatchVersion",
                )
                .await;
            assert_eq!(get.status, 300, "{get:?}");
            assert!(get.final_text.contains("PatchVersion=175"), "{get:?}");
        }
    }

    {
        let model = service.model.lock().await;
        let unit = &model.projects["HARNESS"].networks[&254].units[&5];
        assert_eq!(unit.fields["PatchVersion"], "175");
        assert_eq!(unit.fields["PatchManifestVersion"], "physical-first");
        assert_eq!(unit.fields["PatchManifestSha256"].len(), 64);
    }
    assert!(
        tokio::time::timeout(Duration::from_millis(25), events.recv())
            .await
            .is_err()
    );

    // The rejected concurrent in-memory edit was never persisted; restart
    // retains the first verified patch receipt and its provenance.
    let (restart_pci, _restart_remote) = pci();
    let restarted = Service::new(&fixture(), None, path.clone(), restart_pci, None).unwrap();
    let model = restarted.model.lock().await;
    let unit = &model.projects["HARNESS"].networks[&254].units[&5];
    assert_eq!(unit.fields["PatchVersion"], "175");
    assert_eq!(unit.fields["PatchManifestVersion"], "physical-first");
    assert_eq!(unit.fields["PatchManifestSha256"].len(), 64);
    drop(model);
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn deploy_queue_event_channels_deliver_only_to_subscribed_connections() {
    let path = state_path();
    let (pci, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let server = tokio::spawn(service.clone().serve(listener));
    let (mut event_reader, mut event_writer) = connect_command_session(address).await;
    let (mut producer_reader, mut producer_writer) = connect_command_session(address).await;

    for (tag, channel) in [
        ("sub1", "deploy-queue.updated-entries"),
        ("sub2", "deploy-queue.started"),
        ("sub3", "deploy-queue.ended"),
    ] {
        assert_eq!(
            command_lines(
                &mut event_reader,
                &mut event_writer,
                tag,
                &format!("EVENT_CHANNEL SUB {channel}"),
            )
            .await,
            [format!("[{tag}] 200 OK: added")]
        );
    }
    assert_eq!(
        command_lines(
            &mut producer_reader,
            &mut producer_writer,
            "create",
            "PROGRAMMER CREATE Empty \"No work\" \"Local\"",
        )
        .await,
        ["[create] 200 OK: created"]
    );
    assert_eq!(
        command_lines(
            &mut producer_reader,
            &mut producer_writer,
            "add",
            "DEPLOY_QUEUE ADD Empty",
        )
        .await,
        ["[add] 200 OK: added"]
    );
    let mut events = Vec::new();
    for _ in 0..3 {
        let mut line = String::new();
        tokio::time::timeout(Duration::from_secs(2), event_reader.read_line(&mut line))
            .await
            .unwrap()
            .unwrap();
        events.push(line.trim_end_matches(['\r', '\n']).to_string());
    }
    assert_eq!(
        events,
        [
            "#event {\"name\":\"deploy-queue.updated-entries\",\"msg\":\"addTaskGroup: Empty\"}",
            "#event {\"name\":\"deploy-queue.started\",\"msg\":{\"name\":\"Empty\",\"task\":\"No work\"}}",
            "#event {\"name\":\"deploy-queue.ended\",\"msg\":{\"name\":\"Empty\",\"task\":\"No work\",\"status\":\"STOPPED\"}}",
        ]
    );
    // The producer did not subscribe. Its next command must be framed
    // directly, with no deploy event leaking through EVENT/EVENTS handling.
    assert_eq!(
        command_lines(
            &mut producer_reader,
            &mut producer_writer,
            "list",
            "DEPLOY_QUEUE LIST",
        )
        .await
        .last()
        .unwrap(),
        "[list] 200 OK."
    );
    server.abort();
    std::fs::remove_file(path).unwrap();
}

#[test]
fn pp_admin_and_programmer_auth_classification_keeps_reads_open() {
    for subcommand in [
        "CANCEL_LOCK",
        "LOAD_FROM_FILE",
        "SET_RAW_DATA",
        "RELOAD_CATALOG",
        "WRITE_PATCH",
    ] {
        assert!(super::requires_programming_auth(
            "PP",
            subcommand,
            &["PP".into(), subcommand.into()]
        ));
    }
    for subcommand in [
        "CATALOG_INFO",
        "GET_RAW_DATA",
        "GET_UNIT_CATALOG",
        "GET_UNIT_SPEC",
        "LIST_CATALOG_NUMBERS",
        "LIST_LOCK",
        "PATCH_VERSION",
        "UNITS",
    ] {
        assert!(!super::requires_programming_auth(
            "PP",
            subcommand,
            &["PP".into(), subcommand.into()]
        ));
    }
    for subcommand in [
        "CREATE",
        "DELETE",
        "ADD_INSTRUCTION",
        "CANCEL_INSTRUCTION",
        "TEST",
        "TRIGGER",
    ] {
        assert!(super::requires_programming_auth(
            "PROGRAMMER",
            subcommand,
            &["PROGRAMMER".into(), subcommand.into()]
        ));
    }
    for subcommand in ["LIST", "STATUS"] {
        assert!(!super::requires_programming_auth(
            "PROGRAMMER",
            subcommand,
            &["PROGRAMMER".into(), subcommand.into()]
        ));
    }
    for subcommand in ["ADD", "DELETE", "DELETE_ALL", "RETRY"] {
        assert!(super::requires_programming_auth(
            "DEPLOY_QUEUE",
            subcommand,
            &["DEPLOY_QUEUE".into(), subcommand.into()]
        ));
    }
    assert!(!super::requires_programming_auth(
        "DEPLOY_QUEUE",
        "LIST",
        &["DEPLOY_QUEUE".into(), "LIST".into()]
    ));
}

#[tokio::test]
async fn pp_reset_to_defaults_is_spec_backed_staged_and_persisted_only_by_save() {
    let path = state_path();
    let spec_dir = state_path().with_extension("unitspec");
    std::fs::create_dir_all(&spec_dir).unwrap();
    std::fs::write(
        spec_dir.join("KEYGL5.xml"),
        r#"<UnitSpecification><Parameters>
        <Param><Name>StaticTextString0</Name><Type>string</Type><Address>$20</Address><DefaultValue>Factory text</DefaultValue></Param>
        <Param><Name>UnitName</Name><Type>string</Type><Address>$21</Address><DefaultValue>Factory name</DefaultValue></Param>
        <Param><Name>WithoutDefault</Name><Type>int</Type><Address>$22</Address></Param>
        </Parameters></UnitSpecification>"#,
    )
    .unwrap();
    let (pci_client, mut remote) = pci();
    let service = Service::new(
        &fixture(),
        None,
        path.clone(),
        pci_client,
        Some(spec_dir.clone()),
    )
    .unwrap();
    let mut owner = ClientState::default();
    for line in [
        "[1] PP LOCK L //HARNESS/254",
        "[2] PP START S L",
        "[3] PP LOAD S /db//HARNESS/254/p/5",
        "[4] PP SET S StaticTextString0 Custom",
        "[5] PP SET S AdHoc staged-only",
    ] {
        let response = service.handle(&mut owner, line).await;
        assert_eq!(response.status, 200, "{line}: {}", response.final_text);
    }
    let before_database = service.model.lock().await.projects["HARNESS"].networks[&254].units[&5]
        .fields["StaticTextString0"]
        .clone();
    assert_eq!(before_database, "Fixture");

    let mut foreign = ClientState::default();
    assert_eq!(
        service
            .handle(&mut foreign, "[6] PP RESET_TO_DEFAULTS S")
            .await
            .status,
        420
    );
    let reset = service
        .handle(&mut owner, "[7] PP RESET_TO_DEFAULTS S")
        .await;
    assert_eq!(reset.status, 200, "{}", reset.final_text);
    {
        let model = service.model.lock().await;
        let session = &model.sessions["S"];
        assert_eq!(
            session.params,
            HashMap::from([
                ("StaticTextString0".to_string(), "Factory text".to_string()),
                ("UnitName".to_string(), "Factory name".to_string()),
            ])
        );
        assert_eq!(
            session.dirty,
            HashSet::from(["StaticTextString0".to_string(), "UnitName".to_string()])
        );
        // RESET is staged only; the database still holds its original value.
        assert_eq!(
            model.projects["HARNESS"].networks[&254].units[&5].fields["StaticTextString0"],
            "Fixture"
        );
    }
    assert!(
        tokio::time::timeout(Duration::from_millis(20), remote.read_u8())
            .await
            .is_err(),
        "RESET_TO_DEFAULTS must not perform PCI I/O"
    );

    assert_eq!(
        service
            .handle(&mut owner, "[8] PP SAVE_TO_SOURCE S")
            .await
            .status,
        200
    );
    assert_eq!(service.handle(&mut owner, "[9] PP END S").await.status, 200);
    assert_eq!(
        service.handle(&mut owner, "[10] PP UNLOCK L").await.status,
        200
    );
    let (pci, _remote) = pci();
    let restarted =
        Service::new(&fixture(), None, path.clone(), pci, Some(spec_dir.clone())).unwrap();
    let model = restarted.model.lock().await;
    let fields = &model.projects["HARNESS"].networks[&254].units[&5].fields;
    assert_eq!(fields["StaticTextString0"], "Factory text");
    assert_eq!(fields["UnitName"], "Factory name");
    assert!(!fields.contains_key("AdHoc"));
    assert!(model.sessions.is_empty());
    drop(model);

    std::fs::remove_file(path).unwrap();
    std::fs::remove_dir_all(spec_dir).unwrap();
}

#[tokio::test]
async fn pp_reset_to_defaults_without_exact_spec_fails_unchanged_and_without_pci() {
    let path = state_path();
    let (pci, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let mut owner = ClientState::default();
    for line in [
        "[1] PP LOCK L //HARNESS/254",
        "[2] PP START S L",
        "[3] PP LOAD S /db//HARNESS/254/p/5",
        "[4] PP SET S StaticTextString0 Custom",
    ] {
        assert_eq!(service.handle(&mut owner, line).await.status, 200, "{line}");
    }
    let before = service.model.lock().await.sessions["S"].clone();
    let response = service
        .handle(&mut owner, "[5] PP RESET_TO_DEFAULTS S")
        .await;
    assert_eq!(response.status, 408);
    assert_eq!(
        response.final_text,
        "408 RESET_TO_DEFAULTS requires a loaded unit specification"
    );
    assert_eq!(service.model.lock().await.sessions["S"], before);
    assert!(
        tokio::time::timeout(Duration::from_millis(20), remote.read_u8())
            .await
            .is_err(),
        "failed RESET_TO_DEFAULTS must not perform PCI I/O"
    );
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn pp_reset_to_defaults_with_invalid_spec_fails_unchanged_and_without_pci() {
    let path = state_path();
    let spec_dir = state_path().with_extension("invalid-unitspec");
    std::fs::create_dir_all(&spec_dir).unwrap();
    std::fs::write(
        spec_dir.join("KEYGL5.xml"),
        r#"<UnitSpecification><Parameters>
        <Param><Name>StaticTextString0</Name><Type>string</Type></Param>
        </Parameters></UnitSpecification>"#,
    )
    .unwrap();
    let (pci_client, mut remote) = pci();
    let service = Service::new(
        &fixture(),
        None,
        path.clone(),
        pci_client,
        Some(spec_dir.clone()),
    )
    .unwrap();
    let mut owner = ClientState::default();
    for line in [
        "[1] PP LOCK L //HARNESS/254",
        "[2] PP START S L",
        "[3] PP LOAD S /db//HARNESS/254/p/5",
        "[4] PP SET S StaticTextString0 Custom",
    ] {
        assert_eq!(service.handle(&mut owner, line).await.status, 200, "{line}");
    }
    let before = service.model.lock().await.sessions["S"].clone();
    let response = service
        .handle(&mut owner, "[5] PP RESET_TO_DEFAULTS S")
        .await;
    assert_eq!(response.status, 408);
    assert_eq!(
        response.final_text,
        "408 RESET_TO_DEFAULTS requires a loaded unit specification"
    );
    assert_eq!(service.model.lock().await.sessions["S"], before);
    assert!(
        tokio::time::timeout(Duration::from_millis(20), remote.read_u8())
            .await
            .is_err(),
        "failed RESET_TO_DEFAULTS must not perform PCI I/O"
    );
    std::fs::remove_file(path).unwrap();
    std::fs::remove_dir_all(spec_dir).unwrap();
}

#[tokio::test(start_paused = true)]
async fn physical_readdress_is_guarded_acknowledged_and_keeps_database_address() {
    async fn pci_line<R: tokio::io::AsyncBufRead + Unpin>(reader: &mut R) -> Vec<u8> {
        let mut line = Vec::new();
        reader.read_until(b'\r', &mut line).await.unwrap();
        line
    }
    async fn pci_reply<W: tokio::io::AsyncWrite + Unpin>(writer: &mut W, source: u8, cal: &[u8]) {
        let mut bytes = vec![0x86, source, 0x10, 0x00];
        bytes.extend_from_slice(cal);
        let sum = bytes.iter().fold(0u8, |sum, byte| sum.wrapping_add(*byte));
        bytes.push(0u8.wrapping_sub(sum));
        let mut wire = hex::encode_upper(bytes).into_bytes();
        wire.extend_from_slice(b"\r\n");
        writer.write_all(&wire).await.unwrap();
    }

    let path = state_path();
    let (pci, remote) = pci();
    let (remote_read, mut remote_write) = tokio::io::split(remote);
    let mut remote_read = BufReader::new(remote_read);
    let reset = tokio::spawn({
        let pci = pci.clone();
        async move { pci.pci_reset().await }
    });
    for _ in 0..8 {
        pci_line(&mut remote_read).await;
    }
    reset.await.unwrap().unwrap();

    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    {
        let mut model = service.model.lock().await;
        let network = model
            .projects
            .get_mut("HARNESS")
            .unwrap()
            .networks
            .get_mut(&254)
            .unwrap();
        network
            .physical
            .insert(5, network.units.get(&5).unwrap().clone());
    }
    let moving = tokio::spawn({
        let service = service.clone();
        async move {
            let mut client = ClientState::default();
            service
                .handle(&mut client, "[1] SET //HARNESS/254/p/5 Address 6")
                .await
        }
    });

    let source_check = pci_line(&mut remote_read).await;
    assert!(source_check.starts_with(b"\\4605002104"));
    let source_code = source_check[source_check.len() - 2];
    remote_write.write_all(&[source_code, b'.']).await.unwrap();
    pci_reply(
        &mut remote_write,
        5,
        &[
            0x8d, 4, 0x38, 0xff, 0xff, 0xff, 0xff, 0x18, 0xb1, 0x06, 0x16, 0xa2, 0, 5,
        ],
    )
    .await;
    tokio::time::advance(Duration::from_secs(2)).await;
    tokio::task::yield_now().await;

    let destination_check = pci_line(&mut remote_read).await;
    assert!(destination_check.starts_with(b"\\4606002104"));
    let destination_code = destination_check[destination_check.len() - 2];
    remote_write
        .write_all(&[destination_code, b'.'])
        .await
        .unwrap();
    tokio::time::advance(Duration::from_secs(2)).await;
    tokio::task::yield_now().await;

    let unlock = pci_line(&mut remote_read).await;
    assert!(unlock.starts_with(b"\\4605001120"));
    let unlock_code = unlock[unlock.len() - 2];
    pci_reply(&mut remote_write, 5, &[0x82, 0x20, 0x5a]).await;
    remote_write.write_all(&[unlock_code, b'.']).await.unwrap();
    let store = pci_line(&mut remote_read).await;
    assert!(store.starts_with(b"\\460500A3204E065A"));
    let store_code = store[store.len() - 2];
    pci_reply(&mut remote_write, 6, &[0x32, 0x20, 0x4e]).await;
    remote_write.write_all(&[store_code, b'.']).await.unwrap();

    let response = moving.await.unwrap();
    assert_eq!(response.status, 200);
    assert_eq!(response.final_text, "200 OK: //HARNESS/254/p/6");
    let model = service.model.lock().await;
    let network = &model.projects["HARNESS"].networks[&254];
    assert!(network.units.contains_key(&5));
    assert!(!network.units.contains_key(&6));
    assert!(!network.physical.contains_key(&5));
    assert_eq!(network.physical[&6].address, 6);
    drop(model);
    std::fs::remove_file(path).unwrap();
}

#[tokio::test(start_paused = true)]
async fn routed_physical_readdress_commits_only_the_target_network() {
    async fn line<R: tokio::io::AsyncBufRead + Unpin>(reader: &mut R) -> Vec<u8> {
        let mut line = Vec::new();
        reader.read_until(b'\r', &mut line).await.unwrap();
        line
    }

    let path = state_path();
    let (pci_client, remote) = pci();
    let (remote_read, mut remote_write) = tokio::io::split(remote);
    let mut remote_read = BufReader::new(remote_read);
    let reset = tokio::spawn({
        let pci = pci_client.clone();
        async move { pci.pci_reset().await }
    });
    for _ in 0..8 {
        line(&mut remote_read).await;
    }
    reset.await.unwrap().unwrap();

    let service = Service::new(&topology_fixture(), None, path.clone(), pci_client, None).unwrap();
    {
        let mut model = service.model.lock().await;
        let project = model.projects.get_mut("TOPO").unwrap();
        let local = project.networks.get_mut(&254).unwrap();
        local.physical.insert(16, local.units[&16].clone());
        let remote = project.networks.get_mut(&253).unwrap();
        remote.physical.insert(4, remote.units[&4].clone());
    }
    let mut events = service.events.subscribe();
    let moving = tokio::spawn({
        let service = service.clone();
        async move {
            service
                .handle(
                    &mut ClientState::default(),
                    "[route] SET //TOPO/253/p/4 Address 6",
                )
                .await
        }
    });

    let source = line(&mut remote_read).await;
    assert!(source.starts_with(b"\\46FD09042104"), "{source:?}");
    let source_code = source[source.len() - 2];
    let serial = [
        0x38, 0xff, 0xff, 0xff, 0xff, 0x18, 0xb1, 0x06, 0x16, 0xa2, 0x00, 0x04,
    ];
    let mut identify = vec![0x8d, 4];
    identify.extend_from_slice(&serial);
    routed_pci_reply(&mut remote_write, &[253], 4, &identify).await;
    remote_write.write_all(&[source_code, b'.']).await.unwrap();
    tokio::time::advance(Duration::from_secs(2)).await;
    tokio::task::yield_now().await;

    let destination = line(&mut remote_read).await;
    assert!(
        destination.starts_with(b"\\46FD09062104"),
        "{destination:?}"
    );
    let destination_code = destination[destination.len() - 2];
    remote_write
        .write_all(&[destination_code, b'.'])
        .await
        .unwrap();
    tokio::time::advance(Duration::from_secs(2)).await;
    tokio::task::yield_now().await;

    let unlock = line(&mut remote_read).await;
    assert_eq!(&unlock[..unlock.len() - 2], b"\\46FD090411207F");
    let unlock_code = unlock[unlock.len() - 2];
    routed_pci_reply(&mut remote_write, &[252], 4, &[0x82, 0x20, 0x11]).await;
    routed_pci_reply(&mut remote_write, &[253], 4, &[0x82, 0x20, 0x5a]).await;
    remote_write.write_all(&[unlock_code, b'.']).await.unwrap();

    let store = line(&mut remote_read).await;
    assert_eq!(&store[..store.len() - 2], b"\\46FD0904A3204E065A3F");
    let store_code = store[store.len() - 2];
    routed_pci_reply(&mut remote_write, &[252], 6, &[0x32, 0x20, 0x4e]).await;
    routed_pci_reply(&mut remote_write, &[253], 4, &[0x32, 0x20, 0x4e]).await;
    remote_write.write_all(&[store_code, b'.']).await.unwrap();
    tokio::task::yield_now().await;
    assert!(
        !moving.is_finished(),
        "wrong route or old source completed readdress"
    );
    routed_pci_reply(&mut remote_write, &[253], 6, &[0x32, 0x20, 0x4e]).await;

    let response = moving.await.unwrap();
    assert_eq!(response.status, 200, "{response:?}");
    assert_eq!(response.final_text, "200 OK: //TOPO/253/p/6");
    assert_eq!(events.recv().await.unwrap(), "#e# unit moved 4 6");
    let model = service.model.lock().await;
    let project = &model.projects["TOPO"];
    assert_eq!(
        project.networks[&254]
            .physical
            .keys()
            .copied()
            .collect::<Vec<_>>(),
        [16]
    );
    assert!(project.networks[&253].units.contains_key(&4));
    assert!(!project.networks[&253].units.contains_key(&6));
    assert!(!project.networks[&253].physical.contains_key(&4));
    assert_eq!(project.networks[&253].physical[&6].address, 6);
    drop(model);
    std::fs::remove_file(path).unwrap();
}

#[tokio::test(start_paused = true)]
async fn routed_physical_readdress_reconnect_rejects_stale_commit() {
    async fn line<R: tokio::io::AsyncBufRead + Unpin>(reader: &mut R) -> Vec<u8> {
        let mut line = Vec::new();
        reader.read_until(b'\r', &mut line).await.unwrap();
        line
    }

    let path = state_path();
    let (pci_client, remote) = pci();
    let (remote_read, mut remote_write) = tokio::io::split(remote);
    let mut remote_read = BufReader::new(remote_read);
    let reset = tokio::spawn({
        let pci = pci_client.clone();
        async move { pci.pci_reset().await }
    });
    for _ in 0..8 {
        line(&mut remote_read).await;
    }
    reset.await.unwrap().unwrap();
    let service = Service::new(&topology_fixture(), None, path.clone(), pci_client, None).unwrap();
    {
        let mut model = service.model.lock().await;
        let remote = model
            .projects
            .get_mut("TOPO")
            .unwrap()
            .networks
            .get_mut(&253)
            .unwrap();
        remote.physical.insert(4, remote.units[&4].clone());
    }
    let mut events = service.events.subscribe();
    let moving = tokio::spawn({
        let service = service.clone();
        async move {
            service
                .handle(
                    &mut ClientState::default(),
                    "[stale] SET //TOPO/253/p/4 Address 6",
                )
                .await
        }
    });

    let source = line(&mut remote_read).await;
    let source_code = source[source.len() - 2];
    let mut identify = vec![0x8d, 4];
    identify.extend_from_slice(&[
        0x38, 0xff, 0xff, 0xff, 0xff, 0x18, 0xb1, 0x06, 0x16, 0xa2, 0x00, 0x04,
    ]);
    routed_pci_reply(&mut remote_write, &[253], 4, &identify).await;
    remote_write.write_all(&[source_code, b'.']).await.unwrap();
    tokio::time::advance(Duration::from_secs(2)).await;
    tokio::task::yield_now().await;

    let destination = line(&mut remote_read).await;
    let destination_code = destination[destination.len() - 2];
    remote_write
        .write_all(&[destination_code, b'.'])
        .await
        .unwrap();
    tokio::time::advance(Duration::from_secs(2)).await;
    tokio::task::yield_now().await;

    let unlock = line(&mut remote_read).await;
    let unlock_code = unlock[unlock.len() - 2];
    routed_pci_reply(&mut remote_write, &[253], 4, &[0x82, 0x20, 0x5a]).await;
    remote_write.write_all(&[unlock_code, b'.']).await.unwrap();
    let store = line(&mut remote_read).await;
    let store_code = store[store.len() - 2];

    // Force set_pci to advance the generation after the physical STORE has
    // started but before the old task can enter its cache/event commit.
    let model_guard = service.model.lock().await;
    let (replacement, _replacement_remote) = pci();
    let replacing = tokio::spawn({
        let service = service.clone();
        async move { service.set_pci(replacement).await }
    });
    for _ in 0..100 {
        if service.pci_generation.load(Ordering::Acquire) == 1 {
            break;
        }
        tokio::task::yield_now().await;
    }
    assert_eq!(service.pci_generation.load(Ordering::Acquire), 1);
    routed_pci_reply(&mut remote_write, &[253], 6, &[0x32, 0x20, 0x4e]).await;
    remote_write.write_all(&[store_code, b'.']).await.unwrap();
    tokio::task::yield_now().await;
    drop(model_guard);
    replacing.await.unwrap();

    let response = moving.await.unwrap();
    assert_eq!(response.status, 408, "{response:?}");
    assert_eq!(
        response.final_text,
        "408 Readdress invalidated by PCI reconnect"
    );
    assert!(events.try_recv().is_err(), "stale move event escaped");
    assert!(
        service.model.lock().await.projects["TOPO"].networks[&253]
            .physical
            .is_empty(),
        "the old generation repopulated the replacement cache"
    );
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn routed_physical_readdress_requires_topology_before_pci_io() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&topology_fixture(), None, path.clone(), pci_client, None).unwrap();
    let response = service
        .handle(
            &mut ClientState::default(),
            "[missing] SET //TOPO/252/p/4 Address 6",
        )
        .await;
    assert_eq!(response.status, 408, "{response:?}");
    assert!(
        response
            .final_text
            .contains("Physical network route unavailable"),
        "{response:?}"
    );
    assert!(
        tokio::time::timeout(Duration::from_millis(20), remote.read_u8())
            .await
            .is_err(),
        "unresolved readdress route performed PCI I/O"
    );
    std::fs::remove_file(path).unwrap();
}

#[test]
fn physical_identity_fields_decode_without_inventing_unknown_serials() {
    assert_eq!(identity_text(b"KEYGL5  ", "type").unwrap(), "KEYGL5");
    assert_eq!(identity_text(b"5.5.00  ", "firmware").unwrap(), "5.5.00");
    assert_eq!(
        serial_number(&[0x38, 0xff, 0xff, 0xff, 0xff, 0x18, 0xb1, 0x06, 0x16, 0xa2, 0x00, 0x05,])
            .unwrap()
            .as_deref(),
        Some("101136.1558")
    );
    let mut unknown = [0xff; 12];
    unknown[5..9].fill(0);
    assert_eq!(serial_number(&unknown).unwrap(), None);
    assert!(serial_number(&unknown[..11]).is_err());
    assert!(identity_text(b"        ", "type").is_err());
}

#[tokio::test]
async fn failed_persistence_rolls_back_database_changes() {
    let path = state_path();
    let (pci, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    std::fs::remove_file(&path).unwrap();
    std::fs::create_dir(&path).unwrap();
    let response = service
        .handle(
            &mut ClientState::default(),
            "[1] DBSETSAFE //HARNESS/254/p/5/TagName Changed",
        )
        .await;
    assert_eq!(response.status, 500);
    assert_eq!(
        service.model.lock().await.projects["HARNESS"].networks[&254].units[&5].fields["TagName"],
        "Fixture eDLT"
    );
    assert_eq!(
        service
            .handle(
                &mut ClientState::default(),
                "[config] CONFIG SET sync-time changed",
            )
            .await
            .status,
        500
    );
    assert_eq!(
        service
            .handle(
                &mut ClientState::default(),
                "[config-read] CONFIG GET sync-time",
            )
            .await
            .final_text,
        "303 sync-time=3600"
    );
    assert_eq!(
        service
            .handle(
                &mut ClientState::default(),
                "[1a] PROJECT ARCHIVE HARNESS cmqttd:rollback-slot",
            )
            .await
            .status,
        500
    );
    assert!(service.model.lock().await.database_files.is_empty());
    {
        let mut model = service.model.lock().await;
        let mut auxiliary = model.projects["HARNESS"].clone();
        auxiliary.name = "AUX".to_string();
        model.projects.insert("AUX".to_string(), auxiliary);
    }
    assert_eq!(
        service
            .handle(&mut ClientState::default(), "[1b] PROJECT COPY AUX COPY",)
            .await
            .status,
        500
    );
    assert!(!service.model.lock().await.projects.contains_key("COPY"));
    assert_eq!(
        service
            .handle(&mut ClientState::default(), "[1c] PROJECT DELETE AUX",)
            .await
            .status,
        500
    );
    assert!(service.model.lock().await.projects.contains_key("AUX"));
    service
        .observe(&CBusEvent::LightingOn {
            source: Some(4),
            app: 56,
            group: 1,
        })
        .await;
    assert_eq!(
        service
            .handle(
                &mut ClientState::default(),
                "[2] SCENE RECORD house evening"
            )
            .await
            .status,
        500
    );
    assert!(service.model.lock().await.scene_snapshots.is_empty());
    std::fs::remove_dir(path).unwrap();
}

#[tokio::test]
async fn corrupt_database_is_not_overwritten() {
    let path = state_path();
    std::fs::write(&path, b"broken").unwrap();
    let (pci, _remote) = pci();
    assert!(Service::new(&fixture(), None, path.clone(), pci, None).is_err());
    assert_eq!(std::fs::read(&path).unwrap(), b"broken");
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn reconnect_opens_network_and_discards_observed_levels() {
    let path = state_path();
    let (old, _old_remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), old, None).unwrap();
    service
        .observe(&CBusEvent::LightingOn {
            source: Some(4),
            app: 56,
            group: 1,
        })
        .await;
    let (new, _new_remote) = pci();
    service.set_pci(new).await;
    let model = service.model.lock().await;
    let net = &model.projects["HARNESS"].networks[&254];
    assert_eq!(net.state, NetworkState::Open);
    assert!(net.levels.is_empty());
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn stale_lighting_epoch_cannot_invalidate_a_replacement_observation() {
    let path = state_path();
    let (old, _old_remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), old, None).unwrap();
    let (generation, old_pci) = service.current_pci_epoch().await;

    let (replacement, _replacement_remote) = pci();
    service.set_pci(replacement).await;
    service
        .observe(&CBusEvent::LightingOn {
            source: Some(4),
            app: 56,
            group: 1,
        })
        .await;

    assert!(service
        .invalidate_level_for_epoch(generation, &old_pci, 254, 56, 1)
        .await
        .is_err());
    assert_eq!(
        service.model.lock().await.projects["HARNESS"].networks[&254]
            .levels
            .get(&(56, 1)),
        Some(&255)
    );
    std::fs::remove_file(path).unwrap();
}

#[tokio::test(start_paused = true)]
async fn timed_direct_lighting_ramp_requests_final_physical_level_after_native_duration() {
    let path = state_path();
    let (pci_client, remote) = pci();
    let (remote_read, mut remote_write) = tokio::io::split(remote);
    let mut remote_read = BufReader::new(remote_read);
    let reset = tokio::spawn({
        let pci = pci_client.clone();
        async move { pci.pci_reset().await }
    });
    for _ in 0..8 {
        database_pci_line(&mut remote_read).await;
    }
    reset.await.unwrap().unwrap();

    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let ramp = tokio::spawn({
        let service = service.clone();
        async move {
            service
                .handle(
                    &mut ClientState::default(),
                    "[timed] RAMP //HARNESS/254/56/1 77 1",
                )
                .await
        }
    });
    let request = database_pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\0538000A014D"), "{request:?}");
    remote_write
        .write_all(&[request[request.len() - 2], b'.'])
        .await
        .unwrap();
    assert_eq!(ramp.await.unwrap().status, 200);
    let immediate = database_pci_line(&mut remote_read).await;
    assert!(immediate.starts_with(b"\\05FF00"), "{immediate:?}");

    // The first physical reply is an intermediate brightness. The requested
    // target must not be synthesized into GET, even after the ramp command's
    // delivery confirmation or after the final request has been sent.
    service
        .observe(&CBusEvent::LevelReport {
            app: 56,
            block_start: 0,
            levels: vec![None, Some(11)],
        })
        .await;
    assert!(service
        .handle(
            &mut ClientState::default(),
            "[level] GET //HARNESS/254/56/1 level"
        )
        .await
        .final_text
        .contains("level=11"));
    tokio::time::advance(Duration::from_secs(4)).await;
    assert!(
        tokio::time::timeout(
            Duration::from_millis(1),
            database_pci_line(&mut remote_read)
        )
        .await
        .is_err(),
        "the final status request must wait beyond the snapped four-second ramp"
    );
    tokio::time::advance(Duration::from_millis(500)).await;
    assert_eq!(database_pci_line(&mut remote_read).await, immediate);
    assert!(service
        .handle(
            &mut ClientState::default(),
            "[level] GET //HARNESS/254/56/1 level"
        )
        .await
        .final_text
        .contains("level=11"));
    service
        .observe(&CBusEvent::LevelReport {
            app: 56,
            block_start: 0,
            levels: vec![None, Some(77)],
        })
        .await;
    assert!(service
        .handle(
            &mut ClientState::default(),
            "[level] GET //HARNESS/254/56/1 level"
        )
        .await
        .final_text
        .contains("level=77"));

    let immediate_ramp = tokio::spawn({
        let service = service.clone();
        async move {
            service
                .handle(
                    &mut ClientState::default(),
                    "[instant] RAMP //HARNESS/254/56/1 64 0",
                )
                .await
        }
    });
    let request = database_pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\053800020140"), "{request:?}");
    remote_write
        .write_all(&[request[request.len() - 2], b'.'])
        .await
        .unwrap();
    assert_eq!(immediate_ramp.await.unwrap().status, 200);
    assert_eq!(database_pci_line(&mut remote_read).await, immediate);
    tokio::time::advance(Duration::from_secs(5)).await;
    assert!(
        tokio::time::timeout(
            Duration::from_millis(1),
            database_pci_line(&mut remote_read)
        )
        .await
        .is_err(),
        "zero-duration ramps must not schedule a second status request"
    );
    std::fs::remove_file(path).unwrap();
}

#[tokio::test(start_paused = true)]
async fn later_direct_command_cancels_superseded_ramp_final_read() {
    let path = state_path();
    let (pci_client, remote) = pci();
    let (remote_read, mut remote_write) = tokio::io::split(remote);
    let mut remote_read = BufReader::new(remote_read);
    let reset = tokio::spawn({
        let pci = pci_client.clone();
        async move { pci.pci_reset().await }
    });
    for _ in 0..8 {
        database_pci_line(&mut remote_read).await;
    }
    reset.await.unwrap().unwrap();

    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let first = tokio::spawn({
        let service = service.clone();
        async move {
            service
                .handle(
                    &mut ClientState::default(),
                    "[first] RAMP //HARNESS/254/56/1 77 1",
                )
                .await
        }
    });
    let request = database_pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\0538000A014D"), "{request:?}");
    remote_write
        .write_all(&[request[request.len() - 2], b'.'])
        .await
        .unwrap();
    assert_eq!(first.await.unwrap().status, 200);
    let status_request = database_pci_line(&mut remote_read).await;
    assert!(
        status_request.starts_with(b"\\05FF00"),
        "{status_request:?}"
    );

    tokio::time::advance(Duration::from_secs(1)).await;
    let second = tokio::spawn({
        let service = service.clone();
        async move {
            service
                .handle(
                    &mut ClientState::default(),
                    "[second] RAMP //HARNESS/254/56/1 64 1",
                )
                .await
        }
    });
    let request = database_pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\0538000A0140"), "{request:?}");
    remote_write
        .write_all(&[request[request.len() - 2], b'.'])
        .await
        .unwrap();
    assert_eq!(second.await.unwrap().status, 200);
    assert_eq!(database_pci_line(&mut remote_read).await, status_request);

    // The first request would have matured here, but its group was replaced.
    tokio::time::advance(Duration::from_millis(3500)).await;
    assert!(
        tokio::time::timeout(
            Duration::from_millis(1),
            database_pci_line(&mut remote_read)
        )
        .await
        .is_err(),
        "superseded ramp must not issue a final status request"
    );
    tokio::time::advance(Duration::from_secs(1)).await;
    assert_eq!(database_pci_line(&mut remote_read).await, status_request);

    let third = tokio::spawn({
        let service = service.clone();
        async move {
            service
                .handle(
                    &mut ClientState::default(),
                    "[third] RAMP //HARNESS/254/56/1 128 1",
                )
                .await
        }
    });
    let request = database_pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\0538000A0180"), "{request:?}");
    remote_write
        .write_all(&[request[request.len() - 2], b'.'])
        .await
        .unwrap();
    assert_eq!(third.await.unwrap().status, 200);
    assert_eq!(database_pci_line(&mut remote_read).await, status_request);

    let off = tokio::spawn({
        let service = service.clone();
        async move {
            service
                .handle(&mut ClientState::default(), "[off] OFF //HARNESS/254/56/1")
                .await
        }
    });
    let request = database_pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\0538000101"), "{request:?}");
    remote_write
        .write_all(&[request[request.len() - 2], b'.'])
        .await
        .unwrap();
    assert_eq!(off.await.unwrap().status, 200);
    assert_eq!(database_pci_line(&mut remote_read).await, status_request);
    tokio::time::advance(Duration::from_secs(5)).await;
    assert!(
        tokio::time::timeout(
            Duration::from_millis(1),
            database_pci_line(&mut remote_read)
        )
        .await
        .is_err(),
        "OFF must cancel the pending ramp final status request"
    );
    std::fs::remove_file(path).unwrap();
}

#[tokio::test(start_paused = true)]
async fn timed_ramp_final_readback_skips_routed_network_and_replaced_pci() {
    let path = state_path();
    let (pci_client, remote) = pci();
    let (remote_read, mut remote_write) = tokio::io::split(remote);
    let mut remote_read = BufReader::new(remote_read);
    let reset = tokio::spawn({
        let pci = pci_client.clone();
        async move { pci.pci_reset().await }
    });
    for _ in 0..8 {
        database_pci_line(&mut remote_read).await;
    }
    reset.await.unwrap().unwrap();

    let service = Service::new(&topology_fixture(), None, path.clone(), pci_client, None).unwrap();
    let routed = tokio::spawn({
        let service = service.clone();
        async move {
            service
                .handle(
                    &mut ClientState::default(),
                    "[routed] RAMP //TOPO/253/56/1 77 1",
                )
                .await
        }
    });
    let request = database_pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\03FD09380A014D"), "{request:?}");
    remote_write
        .write_all(&[request[request.len() - 2], b'.'])
        .await
        .unwrap();
    assert_eq!(routed.await.unwrap().status, 200);
    tokio::time::advance(Duration::from_secs(5)).await;
    assert!(
        tokio::time::timeout(
            Duration::from_millis(1),
            database_pci_line(&mut remote_read)
        )
        .await
        .is_err(),
        "routed ramps must not request a direct-network status block"
    );

    let direct = tokio::spawn({
        let service = service.clone();
        async move {
            service
                .handle(
                    &mut ClientState::default(),
                    "[direct] RAMP //TOPO/254/56/1 77 1",
                )
                .await
        }
    });
    let request = database_pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\0538000A014D"), "{request:?}");
    remote_write
        .write_all(&[request[request.len() - 2], b'.'])
        .await
        .unwrap();
    assert_eq!(direct.await.unwrap().status, 200);
    let immediate = database_pci_line(&mut remote_read).await;
    assert!(immediate.starts_with(b"\\05FF00"), "{immediate:?}");

    let (replacement, _replacement_remote) = pci();
    service.set_pci(replacement).await;
    tokio::time::advance(Duration::from_secs(5)).await;
    let old_wire = tokio::time::timeout(
        Duration::from_millis(1),
        database_pci_line(&mut remote_read),
    )
    .await;
    assert!(
        match &old_wire {
            Err(_) => true,
            Ok(line) => line.is_empty(),
        },
        "an old PCI generation must not emit a delayed status request after replacement: {old_wire:?}"
    );
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn reconnect_after_lighting_confirmation_suppresses_old_success_event() {
    let path = state_path();
    let (original_pci, remote) = pci();
    let (remote_read, mut remote_write) = tokio::io::split(remote);
    let mut remote_read = BufReader::new(remote_read);
    let reset = tokio::spawn({
        let pci = original_pci.clone();
        async move { pci.pci_reset().await }
    });
    for _ in 0..8 {
        let mut wire = Vec::new();
        remote_read.read_until(b'\r', &mut wire).await.unwrap();
    }
    reset.await.unwrap().unwrap();

    let service = Service::new(&fixture(), None, path.clone(), original_pci, None).unwrap();
    let mut events = service.events.subscribe();
    let command = tokio::spawn({
        let service = service.clone();
        async move {
            service
                .handle(
                    &mut ClientState::default(),
                    "[1] LIGHTING ON //HARNESS/254/56/1",
                )
                .await
        }
    });
    let mut wire = Vec::new();
    remote_read.read_until(b'\r', &mut wire).await.unwrap();
    let confirmation = wire[wire.len() - 2];

    let model_guard = service.model.lock().await;
    let (replacement, _replacement_remote) = pci();
    let replacing = tokio::spawn({
        let service = service.clone();
        async move { service.set_pci(replacement).await }
    });
    for _ in 0..100 {
        if service.pci_generation.load(Ordering::Acquire) == 1 {
            break;
        }
        tokio::task::yield_now().await;
    }
    assert_eq!(service.pci_generation.load(Ordering::Acquire), 1);
    remote_write.write_all(&[confirmation, b'.']).await.unwrap();
    tokio::task::yield_now().await;
    drop(model_guard);
    replacing.await.unwrap();

    let response = command.await.unwrap();
    assert_eq!(response.status, 408, "{response:?}");
    assert_eq!(
        response.final_text,
        "408 Lighting delivery invalidated by PCI reconnect"
    );
    assert!(events.try_recv().is_err());
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn reconnect_between_confirmation_and_state_commit_rejects_all_live_control_echoes() {
    #[derive(Clone, Copy)]
    enum CachedValue {
        Level(u8, u8),
        Application(&'static str),
    }

    let cases = [
        (
            "[1] TRIGGER EVENT //HARNESS/254/202/4 88",
            CachedValue::Level(202, 4),
            "Trigger delivery invalidated",
        ),
        (
            "[2] ENABLE SET //HARNESS/254/203/5 66",
            CachedValue::Level(203, 5),
            "Enable delivery invalidated",
        ),
        (
            "[3] CLOCK DATE 254/223 2026-09-26",
            CachedValue::Application("CLOCK DATE"),
            "Clock update invalidated",
        ),
        (
            "[4] TEMPERATURE BROADCAST //HARNESS/254/25/3 21.0",
            CachedValue::Application("TEMPERATURE BROADCAST"),
            "Temperature broadcast invalidated",
        ),
    ];

    for (line, cached, error) in cases {
        let path = state_path();
        let (original_pci, remote) = pci();
        let (remote_read, mut remote_write) = tokio::io::split(remote);
        let mut remote_read = BufReader::new(remote_read);
        let reset = tokio::spawn({
            let pci = original_pci.clone();
            async move { pci.pci_reset().await }
        });
        for _ in 0..8 {
            let mut wire = Vec::new();
            remote_read.read_until(b'\r', &mut wire).await.unwrap();
        }
        reset.await.unwrap().unwrap();

        let service = Service::new(&fixture(), None, path.clone(), original_pci, None).unwrap();
        let mut events = service.events.subscribe();
        let command = tokio::spawn({
            let service = service.clone();
            async move { service.handle(&mut ClientState::default(), line).await }
        });
        let mut wire = Vec::new();
        remote_read.read_until(b'\r', &mut wire).await.unwrap();
        assert!(!wire.is_empty(), "{line}");
        let confirmation = wire[wire.len() - 2];

        // set_pci owns the generation gate and waits on this model lock.
        // Deliver the old confirmation only after its generation changed, so
        // the command deterministically reaches its guarded commit second.
        let model_guard = service.model.lock().await;
        let (replacement, _replacement_remote) = pci();
        let replacing = tokio::spawn({
            let service = service.clone();
            async move { service.set_pci(replacement).await }
        });
        for _ in 0..100 {
            if service.pci_generation.load(Ordering::Acquire) == 1 {
                break;
            }
            tokio::task::yield_now().await;
        }
        assert_eq!(service.pci_generation.load(Ordering::Acquire), 1);
        remote_write.write_all(&[confirmation, b'.']).await.unwrap();
        tokio::task::yield_now().await;
        drop(model_guard);
        replacing.await.unwrap();

        let response = command.await.unwrap();
        assert_eq!(response.status, 408, "{line}: {response:?}");
        assert!(response.final_text.contains(error), "{line}: {response:?}");
        let model = service.model.lock().await;
        match cached {
            CachedValue::Level(application, group) => assert!(!model.projects["HARNESS"].networks
                [&254]
                .levels
                .contains_key(&(application, group))),
            CachedValue::Application(key) => {
                assert!(!model.application_state.contains_key(key))
            }
        }
        drop(model);
        assert!(
            events.try_recv().is_err(),
            "{line}: an old-generation success event escaped"
        );
        std::fs::remove_file(path).unwrap();
    }
}

#[tokio::test]
async fn observed_trigger_enable_and_clock_state_is_live_and_cleared_on_disconnect() {
    let path = state_path();
    let (pci, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    service
        .observe(&CBusEvent::TriggerEvent {
            source: Some(7),
            group: 4,
            selector: 88,
        })
        .await;
    service
        .observe(&CBusEvent::EnableSet {
            source: Some(8),
            variable: 5,
            value: 66,
        })
        .await;
    service
        .observe(&CBusEvent::ClockDate {
            source: Some(9),
            year: 2026,
            month: 9,
            day: 24,
        })
        .await;
    service
        .observe(&CBusEvent::TemperatureBroadcast {
            source: Some(10),
            group: 3,
            temperature: 21.25,
        })
        .await;
    assert_eq!(
        service.model.lock().await.application_state["TEMPERATURE BROADCAST"],
        "//HARNESS/254/25/3 21.25"
    );
    let mut client = ClientState::default();
    let trigger = service
        .handle(&mut client, "[1] GET //HARNESS/254/202/4 *")
        .await;
    assert_eq!(trigger.status, 300);
    assert!(trigger
        .lines
        .iter()
        .any(|line| line.contains("EventLevel=9")));
    assert!(trigger.final_text.contains("State=open"), "{trigger:?}");
    assert_eq!(
        service
            .handle(&mut client, "[2] GET //HARNESS/254/202/4 Level")
            .await
            .status,
        402
    );
    assert!(service
        .handle(&mut client, "[3] GET //HARNESS/254/202 Groups")
        .await
        .final_text
        .ends_with("Groups=4"));
    assert!(service
        .handle(&mut client, "[4] GET //HARNESS/254/203/5 Level")
        .await
        .final_text
        .ends_with("Level=66"));
    assert!(service
        .handle(&mut client, "[5] CLOCK DATE 254/223")
        .await
        .final_text
        .ends_with("Date set to: 2026-09-24"));
    service.observe(&CBusEvent::ConnectionLost).await;
    assert!(!service
        .model
        .lock()
        .await
        .application_state
        .contains_key("TEMPERATURE BROADCAST"));
    assert_eq!(
        service
            .handle(&mut client, "[6] GET //HARNESS/254/203/5 Level")
            .await
            .status,
        401
    );
    assert!(service
        .handle(&mut client, "[7] CLOCK DATE 254/223")
        .await
        .final_text
        .ends_with("Date set to: 1970-01-01"));
    std::fs::remove_file(path).unwrap();
}

#[test]
fn temperature_syntax_is_bounded_and_accepts_symbolic_application_addresses() {
    assert_eq!(parse_application("$19"), Some(25));
    assert_eq!(parse_application("25"), Some(25));
    assert_eq!(parse_application("$100"), None);
    assert_eq!(parse_temperature("21.3"), Some(21.3));
    assert_eq!(parse_temperature("21"), Some(21.0));
    assert_eq!(parse_temperature("21.25"), None);
    assert_eq!(parse_temperature("-1"), None);
    assert_eq!(parse_temperature("63.8"), None);
    assert_eq!(format_temperature(21.25), "21.25");
    assert_eq!(format_temperature(20.0), "20");
}

#[tokio::test]
async fn fragmented_command_survives_event_delivery_and_disconnect_releases_locks() {
    let path = state_path();
    let (pci, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let server = tokio::spawn(service.clone().serve(listener));
    let stream = TcpStream::connect(addr).await.unwrap();
    let (rd, mut wr) = stream.into_split();
    let mut rd = BufReader::new(rd);
    let mut line = String::new();
    rd.read_line(&mut line).await.unwrap();
    assert!(line.starts_with("201 "));
    wr.write_all(b"[1] EVENT ON\r\n").await.unwrap();
    line.clear();
    rd.read_line(&mut line).await.unwrap();
    wr.write_all(b"[2] PP LOCK L ").await.unwrap();
    service
        .observe(&CBusEvent::LightingOn {
            source: Some(7),
            app: 56,
            group: 1,
        })
        .await;
    line.clear();
    rd.read_line(&mut line).await.unwrap();
    assert!(line.starts_with("#e#"));
    wr.write_all(b"//HARNESS/254\r\n").await.unwrap();
    loop {
        line.clear();
        rd.read_line(&mut line).await.unwrap();
        if line.starts_with("[2]") {
            break;
        }
    }
    assert!(line.contains("200 OK"));
    drop(wr);
    drop(rd);
    tokio::time::timeout(Duration::from_secs(2), async {
        loop {
            if service.model.lock().await.locks.is_empty() {
                break;
            }
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
    server.abort();
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn broadcast_event_is_local_authenticated_and_has_no_pci_side_effect() {
    let path = state_path();
    let (pci, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    service
        .set_auth_token_hash(crate::auth::sha256(b"broadcast-event-test-token"))
        .unwrap();
    let mut events = service.events.subscribe();
    let mut client = ClientState {
        command_session: Some(3),
        ..ClientState::default()
    };

    let blocked = service
        .handle(&mut client, "[blocked] BROADCAST_EVENT SP class payload")
        .await;
    assert_eq!(blocked.status, 420);
    assert_eq!(blocked.final_text, "420 LOGIN required");
    assert!(events.try_recv().is_err());

    assert_eq!(
        service
            .handle(&mut client, "[login] LOGIN broadcast-event-test-token")
            .await
            .status,
        200
    );
    let response = service
        .handle(&mut client, "[send] BROADCAST_EVENT XX class payload")
        .await;
    assert_eq!(response.status, 200);
    assert!(response.lines.is_empty());
    assert_eq!(response.final_text, "200 OK.");
    let event = tokio::time::timeout(Duration::from_secs(2), events.recv())
        .await
        .expect("broadcast event timed out")
        .unwrap();
    assert_native_broadcast_event(&event, 3, "XX class payload");
    assert!(
        tokio::time::timeout(Duration::from_millis(50), remote.read_u8())
            .await
            .is_err(),
        "BROADCAST_EVENT must not write to the PCI"
    );
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn network_retries_zero_is_local_volatile_and_restart_resets_default() {
    let path = state_path();
    let (initial_pci, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), initial_pci, None).unwrap();
    let mut client = ClientState::default();
    let mut events = service.events.subscribe();
    let durable_before = std::fs::read(&path).unwrap();

    let before = service
        .handle(&mut client, "[before] GET //HARNESS/254 Retries")
        .await;
    assert_eq!(before.status, 300);
    assert_eq!(before.final_text, "300 //HARNESS/254: Retries=2");
    let set = service
        .handle(&mut client, "[set] SET //HARNESS/254 Retries 0")
        .await;
    assert_eq!(set.status, 200);
    assert!(set.lines.is_empty());
    assert_eq!(set.final_text, "200 OK: //HARNESS/254");
    let after = service
        .handle(&mut client, "[after] GET //HARNESS/254 Retries")
        .await;
    assert_eq!(after.status, 300);
    assert_eq!(after.final_text, "300 //HARNESS/254: Retries=0");

    for (line, expected) in [
        ("[value] SET //HARNESS/254 Retries 2", 400),
        ("[missing-value] SET //HARNESS/254 Retries", 400),
        ("[relative] SET /254 Retries 0", 400),
        ("[foreign] SET //OTHER/254 Retries 0", 404),
        ("[missing] SET //HARNESS/253 Retries 0", 404),
        ("[broader] SET //HARNESS/254 AutoUpdate no", 502),
    ] {
        let rejected = service.handle(&mut client, line).await;
        assert_eq!(rejected.status, expected, "{line}");
        let preserved = service
            .handle(&mut client, "[preserved] GET //HARNESS/254 Retries")
            .await;
        assert_eq!(preserved.final_text, "300 //HARNESS/254: Retries=0");
    }

    assert!(events.try_recv().is_err(), "network SET emitted an event");
    assert_eq!(
        std::fs::read(&path).unwrap(),
        durable_before,
        "volatile retry preparation rewrote the durable database"
    );
    assert!(
        tokio::time::timeout(Duration::from_millis(25), remote.read_u8())
            .await
            .is_err(),
        "network SET wrote to the PCI"
    );

    drop(service);
    let (restart_pci, _restart_remote) = pci();
    let restarted = Service::new(&fixture(), None, path.clone(), restart_pci, None).unwrap();
    let mut restarted_client = ClientState::default();
    let restarted_value = restarted
        .handle(&mut restarted_client, "[restart] GET //HARNESS/254 Retries")
        .await;
    assert_eq!(restarted_value.status, 300);
    assert_eq!(restarted_value.final_text, "300 //HARNESS/254: Retries=2");
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn broadcast_event_fans_out_between_embedded_command_connections() {
    let path = state_path();
    let (pci, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let server = tokio::spawn(service.clone().serve(listener));
    // Producer is the first accepted connection and therefore cmd3.
    let (mut producer_reader, mut producer_writer) = connect_command_session(address).await;
    let (mut event_reader, mut event_writer) = connect_command_session(address).await;

    assert_eq!(
        command_lines(&mut event_reader, &mut event_writer, "on", "EVENT e3s0c0").await,
        ["[on] 200 OK."]
    );
    assert_eq!(
        command_lines(
            &mut producer_reader,
            &mut producer_writer,
            "send",
            "BROADCAST_EVENT SP class payload text",
        )
        .await,
        ["[send] 200 OK."]
    );
    let mut event = String::new();
    tokio::time::timeout(Duration::from_secs(2), event_reader.read_line(&mut event))
        .await
        .expect("subscribed client did not receive BROADCAST_EVENT command trace")
        .unwrap();
    assert_native_command_entry_event(
        event.trim_end_matches(['\r', '\n']),
        3,
        "[send] BROADCAST_EVENT SP class payload text",
    );
    event.clear();
    tokio::time::timeout(Duration::from_secs(2), event_reader.read_line(&mut event))
        .await
        .expect("subscribed client did not receive BROADCAST_EVENT application event")
        .unwrap();
    let event = event.trim_end_matches(['\r', '\n']);
    assert_native_broadcast_event(event, 3, "SP class payload text");

    assert_eq!(
        command_lines(&mut event_reader, &mut event_writer, "off", "EVENT OFF").await,
        ["[off] 200 OK."]
    );
    assert_eq!(
        command_lines(
            &mut producer_reader,
            &mut producer_writer,
            "after-off",
            "BROADCAST_EVENT SP class hidden",
        )
        .await,
        ["[after-off] 200 OK."]
    );
    let mut unexpected = String::new();
    assert!(
        tokio::time::timeout(
            Duration::from_millis(100),
            event_reader.read_line(&mut unexpected)
        )
        .await
        .is_err(),
        "EVENT OFF client received {unexpected:?}"
    );

    server.abort();
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn native_session_event_alias_and_quit_are_connection_local() {
    let path = state_path();
    let (pci, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let server = tokio::spawn(service.clone().serve(listener));
    let (mut first_reader, mut first_writer) = connect_command_session(address).await;
    let (mut second_reader, mut second_writer) = connect_command_session(address).await;

    assert_eq!(
        command_lines(&mut first_reader, &mut first_writer, "1", "SESSION_ID").await,
        ["[1] 300 sessionID=cmd3"]
    );
    assert_eq!(
        command_lines(&mut second_reader, &mut second_writer, "2", "SESSION_ID").await,
        ["[2] 300 sessionID=cmd5"]
    );
    let all = command_lines(
        &mut first_reader,
        &mut first_writer,
        "3",
        "SESSION_ID ALL ignored-by-native",
    )
    .await;
    assert_eq!(all.len(), 3);
    assert!(all[0].starts_with("[3] 300-sessionID=cmd1 origin=internal from="));
    assert!(all[0].ends_with(" tag=Console"));
    assert!(all[1].starts_with("[3] 300-sessionID=cmd3 origin=/127.0.0.1:"));
    assert!(all[1].contains(" from="));
    assert!(all[2].starts_with("[3] 300 sessionID=cmd5 origin=/127.0.0.1:"));

    assert_eq!(
        command_lines(
            &mut first_reader,
            &mut first_writer,
            "4",
            "SESSION_ID TAG C-Bus   Toolkit test",
        )
        .await,
        ["[4] 200 OK."]
    );
    let tagged = command_lines(
        &mut second_reader,
        &mut second_writer,
        "5",
        "SESSION_ID ALL",
    )
    .await;
    assert!(tagged[1].ends_with(" tag=C-Bus Toolkit test"));
    assert_eq!(
        command_lines(
            &mut first_reader,
            &mut first_writer,
            "6",
            "SESSION_ID TAG replacement",
        )
        .await,
        ["[6] 408 Operation failed: tag name has already been set"]
    );
    assert_eq!(
        command_lines(&mut first_reader, &mut first_writer, "7", "SESSION_ID TAG",).await,
        ["[7] 400 Syntax Error: tag name not supplied"]
    );

    assert_eq!(
        command_lines(&mut first_reader, &mut first_writer, "8", "EVENTS").await,
        ["[8] 306 e0s0c0"]
    );
    assert_eq!(
        command_lines(&mut first_reader, &mut first_writer, "9", "EVENTS ON").await,
        ["[9] 200 OK."]
    );
    assert_eq!(
        command_lines(&mut first_reader, &mut first_writer, "10", "EVENT").await,
        ["[10] 306 e+s0c0"]
    );

    assert_eq!(
        command_lines(&mut first_reader, &mut first_writer, "11", "QUIT").await,
        ["[11] 204 Closing connection."]
    );
    let mut eof = String::new();
    assert_eq!(
        command_socket_reply_line(&mut first_reader, &mut eof).await,
        0
    );
    let remaining = command_lines(
        &mut second_reader,
        &mut second_writer,
        "12",
        "SESSION_ID ALL",
    )
    .await;
    assert_eq!(remaining.len(), 2);
    assert!(remaining[0].starts_with("[12] 300-sessionID=cmd1 origin=internal from="));
    assert!(remaining[1].starts_with("[12] 300 sessionID=cmd5 "));
    assert!(!remaining.iter().any(|line| line.contains("cmd3")));

    assert_eq!(
        command_lines(&mut second_reader, &mut second_writer, "13", "EXIT").await,
        ["[13] 204 Closing connection."]
    );
    eof.clear();
    assert_eq!(
        command_socket_reply_line(&mut second_reader, &mut eof).await,
        0
    );

    server.abort();
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn native_session_selector_matrix_matches_owned_cgate_capture() {
    let native: serde_json::Value = serde_json::from_str(include_str!(
        "../../../testdata/fixtures/native_cgate_session_selectors.json"
    ))
    .unwrap();
    assert_eq!(
        native["vendor_jar_sha256"],
        "3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630"
    );
    assert_eq!(
        native["java_sha256"],
        "94e156397958bb83fda31ee16200580fd083b0fc0ed4a9ce795cfa44ff8e72f4"
    );
    assert_eq!(native["physical_networks_opened"], false);
    assert_eq!(native["captures"][0]["listeners_loopback_only"], true);
    assert_eq!(native["captures"][0]["listener_count"], 6);
    for capture in native["captures"].as_array().unwrap() {
        assert!(
            capture["cleanup"]["cleanup_complete"] == true || capture["cleanup_complete"] == true
        );
    }

    async fn compare(
        reader: &mut BufReader<tokio::net::tcp::OwnedReadHalf>,
        writer: &mut tokio::net::tcp::OwnedWriteHalf,
        case: &serde_json::Value,
    ) {
        let expected = if let Some(lines) = case["reply"].as_array() {
            lines
                .iter()
                .map(|line| line.as_str().unwrap().to_string())
                .collect::<Vec<_>>()
        } else {
            vec![case["reply"].as_str().unwrap().to_string()]
        };
        let tag = expected[0]
            .strip_prefix('[')
            .unwrap()
            .split_once(']')
            .unwrap()
            .0;
        let command = case["command"].as_str().unwrap();
        assert_eq!(
            command_lines(reader, writer, tag, command).await,
            expected,
            "{command}"
        );
        if case["eof_after_reply"] == true {
            let mut eof = String::new();
            assert_eq!(
                command_socket_reply_line(reader, &mut eof).await,
                0,
                "{command}"
            );
        }
    }

    let path = state_path();
    let (pci, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let server = tokio::spawn(service.serve(listener));

    let matrix = native["captures"][0]["cases"].as_array().unwrap();
    let (mut reader, mut writer) = connect_command_session(address).await;
    for case in matrix.iter().filter(|case| case["connection"] == "a") {
        compare(&mut reader, &mut writer, case).await;
    }
    for connection in ["b", "c", "d", "e"] {
        let (mut reader, mut writer) = connect_command_session(address).await;
        for case in matrix
            .iter()
            .filter(|case| case["connection"] == connection)
        {
            compare(&mut reader, &mut writer, case).await;
        }
    }
    for trial in native["captures"][1]["trials"].as_array().unwrap() {
        let (mut reader, mut writer) = connect_command_session(address).await;
        for case in trial.as_array().unwrap() {
            compare(&mut reader, &mut writer, case).await;
        }
    }
    for trial in native["captures"][2]["cases"].as_array().unwrap() {
        let (mut reader, mut writer) = connect_command_session(address).await;
        for case in trial["entries"].as_array().unwrap() {
            compare(&mut reader, &mut writer, case).await;
        }
    }
    server.abort();
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn line_bound_is_enforced_before_newline() {
    let (mut tx, rx) = tokio::io::duplex(8192);
    let mut rd = BufReader::new(rx);
    let writer = tokio::spawn(async move {
        let _ = tx.write_all(&vec![b'x'; MAX_LINE + 1]).await;
        let mut b = [0];
        let _ = tx.read(&mut b).await;
    });
    let response = bounded_line(&mut rd, &mut Vec::new()).await;
    assert!(response.unwrap_err().to_string().contains("1 MiB"));
    writer.abort();
}

#[tokio::test]
async fn document_total_bound_drains_through_the_delimiter() {
    let line = vec![b'x'; MAX_LINE - 1];
    let mut input = Vec::with_capacity(MAX_DOCUMENT + MAX_LINE + 64);
    for _ in 0..17 {
        input.extend_from_slice(&line);
        input.push(b'\n');
    }
    input.extend_from_slice(b"END\nNOOP\n");
    let mut reader = BufReader::new(input.as_slice());
    assert!(matches!(
        bounded_document(&mut reader, "END").await.unwrap(),
        DocumentRead::Exceeded
    ));
    let mut pending = Vec::new();
    assert_eq!(
        bounded_line(&mut reader, &mut pending).await.unwrap(),
        Some("NOOP".to_string())
    );
}

/// Issue #12 Phase 1: capabilities must advertise observation while honestly
/// reporting that no device-cache readback exists and no full compatibility
/// is claimed.
#[tokio::test]
async fn capabilities_report_observation_without_device_readback() {
    let path = state_path();
    let (pci, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let mut client = ClientState::default();
    let response = service.handle(&mut client, "[1] CMQTT CAPABILITIES").await;
    assert_eq!(response.status, 200);
    assert_eq!(response.lines.len(), 1);
    let document: serde_json::Value = serde_json::from_str(&response.lines[0]).unwrap();
    assert_eq!(document["full_cgate_compatibility"], false);
    assert_eq!(document["full_cgate_command_path_coverage"], true);
    assert_eq!(document["cgate_inventory_paths"], 431);
    assert_eq!(document["cgate_non_obsolete_paths"], 429);
    assert_eq!(document["cgate_physical_paths"], 230);
    assert_eq!(document["cgate_local_session_paths"], 199);
    assert_eq!(document["cgate_fail_closed_paths"], 0);
    assert_eq!(document["cgate_obsolete_paths"], 2);
    assert_eq!(document["cgate_rejected_paths"], 0);
    assert_eq!(document["pci_generation"], 0);
    assert_eq!(document["pci_connected"], true);
    assert_eq!(document["programming_lane_state"], "ready");
    assert_eq!(
        document["cgate_compatibility_limitations"]
            .as_array()
            .unwrap()
            .len(),
        6
    );
    assert_eq!(document["broadcast_event"], true);
    assert_eq!(document["broadcast_event_code"], 703);
    assert_eq!(document["broadcast_event_level"], 3);
    assert_eq!(document["broadcast_event_fanout"], true);
    assert_eq!(document["broadcast_event_persistence"], false);
    assert_eq!(document["dynamic_labels"], true);
    assert_eq!(document["label_clear"], true);
    assert_eq!(document["label_kfi"], true);
    assert_eq!(document["label_management_routed"], true);
    assert_eq!(document["label_management_routed_max_hops"], 6);
    assert_eq!(
        document["label_management_routed_commands"],
        serde_json::json!(["clear", "clearedlt", "kfiget", "kfiset", "factorydefault"])
    );
    assert_eq!(document["dynamic_label_observation"], true);
    assert_eq!(document["dynamic_label_device_readback"], false);
    assert_eq!(document["edlt_factory_default"], true);
    assert_eq!(document["edlt_widget_groups"], true);
    assert_eq!(document["edlt_extended_firmware"], true);
    assert_eq!(document["edlt_applications"], true);
    assert_eq!(document["edlt_sync_metadata_routed"], true);
    assert_eq!(document["edlt_sync_metadata_routed_max_hops"], 6);
    assert_eq!(
        document["edlt_sync_metadata_routed_fields"],
        serde_json::json!([
            "FirmwareVersion",
            "Application",
            "Application2",
            "WidgetGroups"
        ])
    );
    assert_eq!(document["network_syncnew"], true);
    assert_eq!(document["network_project_identify"], true);
    assert_eq!(document["network_set_project_identify"], true);
    assert_eq!(document["unit_readdress"], true);
    assert_eq!(document["unit_readdress_routed"], true);
    assert_eq!(document["unit_readdress_routed_max_hops"], 6);
    assert_eq!(
        document["unit_readdress_routed_delivery_semantics"],
        "reply-network-route-source-destination-ack-correlated-exactly-once-no-replay"
    );
    assert_eq!(
        document["unit_readdress_routed_state_scope"],
        "target-network-volatile-cache-only"
    );
    assert_eq!(
        document["unit_readdress_routed_physical_persistence_verified"],
        false
    );
    assert_eq!(document["bridged_read_only_discovery"], true);
    assert_eq!(document["bridged_syncnew_general"], true);
    assert_eq!(document["bridged_project_identity_write"], true);
    assert_eq!(
        document["bridged_mutation_commands"],
        serde_json::json!([
            "LIGHTING",
            "DO lighting",
            "TRIGGER",
            "ENABLE SET",
            "NET LEARN",
            "NETWORK LOCATE",
            "AIRCON",
            "AUDIO",
            "SECURITY",
            "MEASUREMENT DATA",
            "MEDIATRANSPORT",
            "TELEPHONY",
            "IDENTIFY",
            "SHORTMESSAGE",
            "EREPORT MESSAGE",
            "ACCESS_CONTROL",
            "LIGHTING|TRIGGER|ENABLE LABEL",
            "LABEL CLEAR|CLEAREDLT|KFIGET|KFISET",
            "DO FactoryDefault",
            "CLOCK",
            "TEMPERATURE BROADCAST",
            "SCENE PLAY",
            "NET SET_PROJECT_IDENTIFY",
            "NET UNRAVEL",
            "NET UNRAVELUNIT",
            "DO UNRAVEL",
            "SET Address",
            "PP SAVE",
            "PP SAVE_TO_SOURCE"
        ])
    );
    assert_eq!(document["dynamic_labels_routed"], true);
    assert_eq!(document["clock_control_routed"], true);
    assert_eq!(document["temperature_broadcast_routed"], true);
    assert_eq!(document["named_scene_playback_routed"], true);
    assert_eq!(
        document["routed_scene_preflight"],
        "all-target-routes-before-first-write"
    );
    assert_eq!(document["physical_application_routed_control"], true);
    assert_eq!(
        document["physical_application_routed_families"],
        serde_json::json!([
            "lighting",
            "trigger",
            "enable-set",
            "network-management",
            "aircon",
            "audio",
            "security",
            "measurement",
            "media-transport",
            "telephony",
            "identify",
            "short-message",
            "error-reporting",
            "access-control",
            "dynamic-label",
            "clock",
            "temperature",
            "named-scene-playback"
        ])
    );
    assert_eq!(document["specialist_application_routed_max_hops"], 6);
    assert_eq!(document["specialist_application_routed_readback"], false);
    assert_eq!(
        document["physical_application_routed_delivery_semantics"],
        "pci-confirmed-exactly-once-no-replay-no-device-readback"
    );
    assert_eq!(
        document["physical_application_routed_state_scope"],
        "target-network-only"
    );
    assert_eq!(document["physical_application_routed_readback"], false);
    assert_eq!(document["network_management_routed"], true);
    assert_eq!(document["network_management_routed_max_hops"], 6);
    assert_eq!(document["network_management_routed_readback"], false);
    assert_eq!(
        document["network_management_routed_selectors"],
        serde_json::json!(["learn", "unit", "application", "group", "serial"])
    );
    assert_eq!(document["bridged_network_max_hops"], 6);
    assert_eq!(
        document["bridged_read_only_commands"],
        serde_json::json!([
            "DBNETWORKPATH",
            "NET PINGU",
            "NET SYNC",
            "NET SYNCNEW",
            "NET CHECKUNIT",
            "DO SYNC",
            "PP LOAD"
        ])
    );
    assert_eq!(document["net_unravelunit_matchdb_duplicate_255"], true);
    assert_eq!(document["net_unravel"], true);
    assert_eq!(document["net_unravel_direct_safe_planner"], true);
    assert_eq!(document["net_unravel_routed_safe_planner"], true);
    assert_eq!(document["net_unravel_routed_max_hops"], 6);
    assert_eq!(
        document["net_unravel_routed_state_scope"],
        "target-network-only"
    );
    assert_eq!(
        document["net_unravel_routed_delivery_semantics"],
        "reply-network-route-and-serial-correlated-exactly-once-no-replay"
    );
    assert_eq!(document["net_unravel_physical_persistence_accepted"], false);
    assert_eq!(document["net_open_close_preserves_mqtt"], true);
    assert_eq!(document["project_runtime_start_stop"], true);
    assert_eq!(document["topology_explore"], true);
    assert_eq!(document["net_lifecycle_fail_closed"], serde_json::json!([]));
    assert_eq!(document["pp_reset_to_defaults"], true);
    assert_eq!(document["physical_pp_routed_load"], true);
    assert_eq!(document["physical_pp_routed_save"], true);
    assert_eq!(
        document["physical_pp_routed_methods"],
        serde_json::json!([
            "dali", "direct", "edlt", "giu", "goc", "goc2", "gocbyt", "ncc", "paged", "sgiu"
        ])
    );
    assert_eq!(
        document["physical_pp_routed_save_protection"],
        serde_json::json!(["none", "checksum", "lock"])
    );
    assert_eq!(
        document["physical_pp_routed_lock_methods"],
        serde_json::json!(["direct", "ncc", "paged"])
    );
    assert_eq!(
        document["physical_pp_routed_unsupported_methods"],
        serde_json::json!([])
    );
    assert_eq!(document["physical_pp_routed_lock"], true);
    assert_eq!(document["physical_pp_routed_nvm_commit"], true);
    assert_eq!(
        document["physical_pp_routed_nvm_delivery_semantics"],
        "reply-network-unit-group-operation-correlated-execute-poll-exactly-once-no-replay"
    );
    assert_eq!(
        document["physical_pp_routed_state_scope"],
        "owned-session-target-network"
    );
    assert_eq!(document["pp_raw_session_memory"], true);
    assert_eq!(
        document["pp_catalog_scope"],
        "configured-unitspec-directory-only"
    );
    assert_eq!(document["pp_write_patch"], true);
    assert_eq!(
        document["pp_local_administration"]
            .as_array()
            .unwrap()
            .len(),
        13
    );
    assert_eq!(document["programmer_queue"], true);
    assert_eq!(document["programmer_execution"], true);
    assert_eq!(
        document["programmer_instruction_types"]
            .as_array()
            .unwrap()
            .len(),
        9
    );
    assert_eq!(
        document["programmer_delivery_semantics"],
        "source-correlated-exactly-once-no-automatic-replay"
    );
    assert_eq!(document["programmer_runtime_persistence"], false);
    assert_eq!(document["programmer_commands"].as_array().unwrap().len(), 8);
    assert_eq!(
        document["deploy_queue_commands"].as_array().unwrap().len(),
        5
    );
    assert_eq!(
        document["deploy_queue_local_administration"],
        serde_json::json!(["delete", "delete_all", "list"])
    );
    assert_eq!(document["deploy_queue_empty_programmer_add"], true);
    assert_eq!(document["deploy_queue_execution"], true);
    assert_eq!(document["deploy_queue_retry"], true);
    assert_eq!(
        document["deploy_queue_receipt"],
        "accepted-before-terminal-state"
    );
    assert_eq!(
        document["deploy_queue_delivery_semantics"],
        "first-fault-stop-no-automatic-replay-explicit-retry"
    );
    assert_eq!(document["deploy_queue_runtime_persistence"], false);
    assert_eq!(
        document["deploy_queue_event_delivery"]
            .as_array()
            .unwrap()
            .len(),
        3
    );
    assert_eq!(document["deploy_queue_debug_events"], true);
    assert_eq!(document["event_subscriptions"], true);
    assert_eq!(document["session_id"], true);
    assert_eq!(document["quit"], true);
    assert_eq!(document["document_framing"], true);
    assert_eq!(document["database_documents"], true);
    assert_eq!(
        document["database_document_scope"],
        serde_json::json!([
            "scalar-field",
            "typed-unit",
            "typed-level",
            "typed-netvar",
            "typed-group",
            "typed-application",
            "typed-network",
            "typed-network-with-unit"
        ])
    );
    assert_eq!(document["database_document_network_units"], true);
    assert_eq!(
        document["database_document_configured_network"],
        "same-address-same-interface-binding"
    );
    assert_eq!(document["database_document_physical_io"], false);
    assert_eq!(
        document["legacy_database_local_commands"],
        serde_json::json!([
            "dbadd",
            "dbcopy",
            "dbnew",
            "dbrenamenet",
            "dbrenamenetsafe",
            "dbset",
            "dbtaglist"
        ])
    );
    assert_eq!(
        document["legacy_database_physical_commands"],
        serde_json::json!(["dbcreate", "dbupdate", "dbverify"])
    );
    assert_eq!(
        document["legacy_database_fail_closed"],
        serde_json::json!([])
    );
    assert_eq!(document["legacy_database_incomplete_oid_objects"], true);
    assert_eq!(document["legacy_database_recursive_copy"], true);
    assert_eq!(document["legacy_database_physical_refresh"], true);
    assert_eq!(document["legacy_database_verify_differences"], true);
    assert_eq!(document["project_archive_restore"], "cmqttd-internal");
    assert_eq!(document["project_rename_secondary"], true);
    assert_eq!(document["project_copy"], "cmqttd-internal");
    assert_eq!(document["project_delete_secondary"], "cmqttd-internal");
    assert_eq!(document["repository_list"], true);
    assert_eq!(document["repository_type"], "cmqttd-json");
    assert_eq!(document["file_commands"].as_array().unwrap().len(), 7);
    assert_eq!(document["file_storage"], "cmqttd-json");
    assert_eq!(
        document["file_binary_transfer"],
        "base64-here-document-and-345-347-346-envelope"
    );
    assert_eq!(document["file_host_filesystem"], false);
    assert_eq!(document["cgl_import"], true);
    assert_eq!(document["cgl_export"], true);
    assert_eq!(
        document["cgl_scope"],
        "bounded-cgl-1.1-database-labels-and-known-routes"
    );
    assert_eq!(document["cgl_controller_side_effects"], false);
    assert_eq!(
        document["applications_catalog"],
        "configured-unitspec-directory-applications.xml"
    );
    assert_eq!(
        document["network_calculator"],
        "configured-cbusunits-database-records"
    );
    assert_eq!(document["network_calculator_physical_measurement"], false);
    assert_eq!(document["repository_use"], true);
    assert_eq!(document["project_repair"], true);
    assert_eq!(
        document["portable_repository_sqlite_schema"],
        "cmqttd-portable-project-v14"
    );
    assert_eq!(document["vendor_repository_transforms"], false);
    assert_eq!(document["macro_execution"], true);
    assert_eq!(document["shutdown_confirm"], true);
    assert_eq!(document["log_extract"], true);
    assert_eq!(document["convertunit_database"], true);
    assert_eq!(
        document["native_family_help_roots"],
        serde_json::json!([
            "applications",
            "calculator",
            "cgl",
            "clock",
            "enable",
            "ereport",
            "identify",
            "lighting",
            "repository",
            "shortmessage",
            "temperature",
            "test_spam",
            "transform",
            "trigger"
        ])
    );
    assert_eq!(
        document["do_methods"],
        serde_json::json!(["factorydefault", "lighting", "sync", "unravel"])
    );
    // Dormant default: no --cgate-auth-file, so the LOGIN gate is off.
    assert_eq!(document["cgate_auth"], false);
    std::fs::remove_file(path).unwrap();
}

/// The armed LOGIN gate is discoverable via capabilities, without needing
/// a denied-write probe.
#[tokio::test]
async fn capabilities_report_armed_login_gate() {
    let (service, path) = authed_service();
    let mut client = ClientState::default();
    let response = service.handle(&mut client, "[1] CMQTT CAPABILITIES").await;
    assert_eq!(response.status, 200);
    let document: serde_json::Value = serde_json::from_str(&response.lines[0]).unwrap();
    assert_eq!(document["cgate_auth"], true);
    std::fs::remove_file(path).ok();
}

/// Issue #12 Phase 1: an empty observation cache reports observed-only
/// provenance — never a complete device readback.
#[tokio::test]
async fn labels_empty_document_pins_observed_only_provenance() {
    let path = state_path();
    let (pci, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let mut client = ClientState::default();
    let response = service
        .handle(&mut client, "[1] CMQTT LABELS //HARNESS/254")
        .await;
    assert_eq!(response.status, 200);
    assert_eq!(response.lines.len(), 1);
    let document: serde_json::Value = serde_json::from_str(&response.lines[0]).unwrap();
    assert_eq!(document["format"], "cmqttd-observed-dynamic-labels-v1");
    assert_eq!(document["source"], "observed-sal-traffic");
    assert_eq!(document["complete"], false);
    assert_eq!(document["device_readback"], false);
    assert_eq!(document["reset_on_reconnect"], true);
    assert_eq!(document["capacity"], MAX_LABEL_OBSERVATIONS);
    assert_eq!(document["observations"].as_array().unwrap().len(), 0);
    assert_eq!(document["address"], "//HARNESS/254");
    assert_eq!(document["requested_address"], "//HARNESS/254");
    assert_eq!(document["observation_scope"], "network");
    assert_eq!(document["recipient_verified"], false);
    assert_eq!(document["project"], "HARNESS");
    assert_eq!(document["network"], 254);
    // A unit-shaped request still exposes the network-wide observations and
    // does not imply that the requested unit received them.
    let unit = service
        .handle(&mut client, "[2] CMQTT LABELS //HARNESS/254/p/5")
        .await;
    assert_eq!(unit.status, 200);
    assert_eq!(unit.lines.len(), 1);
    let unit_document: serde_json::Value = serde_json::from_str(&unit.lines[0]).unwrap();
    assert_eq!(unit_document["address"], "//HARNESS/254/p/5");
    assert_eq!(unit_document["requested_address"], "//HARNESS/254/p/5");
    assert_eq!(unit_document["observation_scope"], "network");
    assert_eq!(unit_document["recipient_verified"], false);
    assert_eq!(unit_document["device_readback"], false);
    assert_eq!(unit_document["observations"], document["observations"]);
    // Bare canonical network forms accepted; trailing-slash forms rejected.
    for address in ["254", "HARNESS/254"] {
        let response = service
            .handle(&mut client, &format!("[3] CMQTT LABELS {address}"))
            .await;
        assert_eq!(response.status, 200, "{address}");
        let document: serde_json::Value = serde_json::from_str(&response.lines[0]).unwrap();
        assert_eq!(document["requested_address"], address);
        assert_eq!(document["observation_scope"], "network");
        assert_eq!(document["recipient_verified"], false);
    }
    for address in ["//HARNESS/254/", "//HARNESS/254/p/5/"] {
        let response = service
            .handle(&mut client, &format!("[4] CMQTT LABELS {address}"))
            .await;
        assert_eq!(response.status, 400, "{address}");
    }
    std::fs::remove_file(path).unwrap();
}

/// Issue #12 Phase 1: label observations are scoped to the configured
/// network; foreign projects or networks are rejected, never invented.
#[tokio::test]
async fn labels_reject_foreign_network() {
    let path = state_path();
    let (pci, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let mut client = ClientState::default();
    for address in [
        "//OTHER/254",
        "//HARNESS/253",
        "//OTHER/254/p/5",
        "//HARNESS/253/p/5",
        "//HARNESS/254/p/5/extra",
    ] {
        let response = service
            .handle(&mut client, &format!("[1] CMQTT LABELS {address}"))
            .await;
        assert_eq!(response.status, 400, "{address}");
    }
    std::fs::remove_file(path).unwrap();
}

/// Issue #12 Phase 1: the bounded observation ring evicts the oldest entry
/// at capacity while sequence numbers stay strictly monotonic.
#[tokio::test]
async fn observed_label_ring_evicts_oldest_at_capacity() {
    let path = state_path();
    let (pci, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let payload = vec![0xa4, 0x01, 0x00, 0x00, 0x41];
    for _ in 0..MAX_LABEL_OBSERVATIONS + 3 {
        service
            .record_label("received", Some(5), 56, &payload)
            .await;
    }
    let labels = service.observed_labels.lock().await;
    assert_eq!(labels.observations.len(), MAX_LABEL_OBSERVATIONS);
    assert_eq!(labels.next_sequence, (MAX_LABEL_OBSERVATIONS + 3) as u64);
    let first = labels.observations.front().unwrap();
    let last = labels.observations.back().unwrap();
    assert_eq!(first.sequence, 3);
    assert_eq!(last.sequence, (MAX_LABEL_OBSERVATIONS + 3) as u64 - 1);
    assert_eq!(first.payload_hex, "a401000041");
    let mut previous = None;
    for observation in labels.observations.iter() {
        if let Some(previous) = previous {
            assert!(observation.sequence > previous);
        }
        previous = Some(observation.sequence);
    }
    drop(labels);
    // The served wire document reflects the same eviction window.
    let mut client = ClientState::default();
    let response = service
        .handle(&mut client, "[1] CMQTT LABELS //HARNESS/254")
        .await;
    assert_eq!(response.status, 200);
    let document: serde_json::Value = serde_json::from_str(&response.lines[0]).unwrap();
    let observations = document["observations"].as_array().unwrap();
    assert_eq!(observations.len(), MAX_LABEL_OBSERVATIONS);
    assert_eq!(observations[0]["sequence"], 3);
    assert_eq!(
        observations[MAX_LABEL_OBSERVATIONS - 1]["sequence"],
        (MAX_LABEL_OBSERVATIONS + 3) as u64 - 1
    );
    std::fs::remove_file(path).unwrap();
}

/// Issue #12 Phase 1: genuine bus label traffic surfaces as `received`
/// observations and a dropped connection discards them (they were never a
/// persistent device-cache readback).
#[tokio::test]
async fn observed_dynamic_label_surfaces_received_and_clears_on_disconnect() {
    let path = state_path();
    let (pci, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    service
        .observe(&CBusEvent::DynamicLabel {
            source: Some(5),
            application: 56,
            payload: vec![0xa4, 0x01, 0x00, 0x00, 0x41],
        })
        .await;
    let mut client = ClientState::default();
    let response = service
        .handle(&mut client, "[1] CMQTT LABELS //HARNESS/254")
        .await;
    assert_eq!(response.status, 200);
    let document: serde_json::Value = serde_json::from_str(&response.lines[0]).unwrap();
    let observations = document["observations"].as_array().unwrap();
    assert_eq!(observations.len(), 1);
    assert_eq!(observations[0]["direction"], "received");
    assert_eq!(observations[0]["source_unit"], 5);
    assert_eq!(observations[0]["application"], 56);
    assert_eq!(observations[0]["payload_hex"], "a401000041");
    assert_eq!(document["complete"], false);
    assert_eq!(document["device_readback"], false);
    service.observe(&CBusEvent::ConnectionLost).await;
    let cleared = service
        .handle(&mut client, "[2] CMQTT LABELS //HARNESS/254")
        .await;
    let cleared: serde_json::Value = serde_json::from_str(&cleared.lines[0]).unwrap();
    assert_eq!(cleared["observations"].as_array().unwrap().len(), 0);
    std::fs::remove_file(path).unwrap();
}

/// Issue #12 Phase 1: the send-confirmed record path serves rows matching
/// the exact key contract the Python `decode_observed_labels` requires
/// (`sequence/direction/source_unit/application/payload_hex` — no extras).
#[tokio::test]
async fn sent_confirmed_observation_row_matches_decoder_contract() {
    let path = state_path();
    let (pci, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    service
        .record_label("sent-confirmed", None, 56, &[0xa4, 0x01, 0x00, 0x00, 0x41])
        .await;
    let mut client = ClientState::default();
    let response = service
        .handle(&mut client, "[1] CMQTT LABELS //HARNESS/254")
        .await;
    assert_eq!(response.status, 200);
    let document: serde_json::Value = serde_json::from_str(&response.lines[0]).unwrap();
    let observations = document["observations"].as_array().unwrap();
    assert_eq!(observations.len(), 1);
    let row = observations[0].as_object().unwrap();
    let mut keys: Vec<&str> = row.keys().map(String::as_str).collect();
    keys.sort_unstable();
    assert_eq!(
        keys,
        [
            "application",
            "direction",
            "payload_hex",
            "sequence",
            "source_unit"
        ]
    );
    assert_eq!(row["sequence"], 0);
    assert_eq!(row["direction"], "sent-confirmed");
    assert!(row["source_unit"].is_null());
    assert_eq!(row["application"], 56);
    assert_eq!(row["payload_hex"], "a401000041");
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn reconnect_between_label_confirmation_and_record_discards_old_observation() {
    let path = state_path();
    let (original_pci, remote) = pci();
    let (remote_read, mut remote_write) = tokio::io::split(remote);
    let mut remote_read = BufReader::new(remote_read);
    let reset = tokio::spawn({
        let pci = original_pci.clone();
        async move { pci.pci_reset().await }
    });
    for _ in 0..8 {
        let mut wire = Vec::new();
        remote_read.read_until(b'\r', &mut wire).await.unwrap();
    }
    reset.await.unwrap().unwrap();

    let service = Service::new(&fixture(), None, path.clone(), original_pci, None).unwrap();
    let command = tokio::spawn({
        let service = service.clone();
        async move {
            service
                .handle(
                    &mut ClientState::default(),
                    "[1] LIGHTING LABEL //HARNESS/254/56 0 1 - F0 0 41",
                )
                .await
        }
    });
    let mut wire = Vec::new();
    remote_read.read_until(b'\r', &mut wire).await.unwrap();
    assert!(!wire.is_empty());
    let confirmation = wire[wire.len() - 2];

    let labels_guard = service.observed_labels.lock().await;
    let (replacement, _replacement_remote) = pci();
    let replacing = tokio::spawn({
        let service = service.clone();
        async move { service.set_pci(replacement).await }
    });
    for _ in 0..100 {
        if service.pci_generation.load(Ordering::Acquire) == 1 {
            break;
        }
        tokio::task::yield_now().await;
    }
    assert_eq!(service.pci_generation.load(Ordering::Acquire), 1);
    remote_write.write_all(&[confirmation, b'.']).await.unwrap();
    tokio::task::yield_now().await;
    drop(labels_guard);
    replacing.await.unwrap();

    let response = command.await.unwrap();
    assert_eq!(response.status, 408, "{response:?}");
    assert_eq!(
        response.final_text,
        "408 Label delivery invalidated by PCI reconnect"
    );
    assert!(service.observed_labels.lock().await.observations.is_empty());
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn reconnect_between_label_clear_confirmation_and_invalidation_preserves_new_observation() {
    let path = state_path();
    let (original_pci, remote) = pci();
    let (remote_read, mut remote_write) = tokio::io::split(remote);
    let mut remote_read = BufReader::new(remote_read);
    let reset = tokio::spawn({
        let pci = original_pci.clone();
        async move { pci.pci_reset().await }
    });
    for _ in 0..8 {
        let mut wire = Vec::new();
        remote_read.read_until(b'\r', &mut wire).await.unwrap();
    }
    reset.await.unwrap().unwrap();

    let service = Service::new(&fixture(), None, path.clone(), original_pci, None).unwrap();
    let command = tokio::spawn({
        let service = service.clone();
        async move {
            service
                .handle(
                    &mut ClientState::default(),
                    "[1] LABEL CLEAR //HARNESS/254/56 5",
                )
                .await
        }
    });
    let mut wire = Vec::new();
    remote_read.read_until(b'\r', &mut wire).await.unwrap();
    let confirmation = wire[wire.len() - 2];

    let labels_guard = service.observed_labels.lock().await;
    let model_guard = service.model.lock().await;
    let (replacement, _replacement_remote) = pci();
    let replacing = tokio::spawn({
        let service = service.clone();
        async move { service.set_pci(replacement).await }
    });
    for _ in 0..100 {
        if service.pci_generation.load(Ordering::Acquire) == 1 {
            break;
        }
        tokio::task::yield_now().await;
    }
    assert_eq!(service.pci_generation.load(Ordering::Acquire), 1);
    tokio::task::yield_now().await;
    remote_write.write_all(&[confirmation, b'.']).await.unwrap();
    let recording = tokio::spawn({
        let service = service.clone();
        async move {
            service
                .record_label("received", Some(5), 56, &[0xa4, 1, 0, 0, b'N'])
                .await
        }
    });
    drop(labels_guard);
    recording.await.unwrap();
    drop(model_guard);
    replacing.await.unwrap();

    let response = command.await.unwrap();
    assert_eq!(response.status, 408, "{response:?}");
    assert_eq!(
        response.final_text,
        "408 Label cache clear invalidated by PCI reconnect"
    );
    let labels = service.observed_labels.lock().await;
    assert_eq!(labels.observations.len(), 1);
    assert_eq!(labels.observations[0].payload_hex, "a40100004e");
    drop(labels);
    std::fs::remove_file(path).unwrap();
}

/// DO UNRAVEL is now a physical alias. Resolution and method grammar still
/// fail before I/O, while the transport behavior is covered by the general
/// unravel transaction test below.
#[tokio::test]
async fn do_unravel_resolves_before_physical_io() {
    let path = state_path();
    let (pci, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let mut client = ClientState::default();
    let response = service
        .handle(&mut client, "[1] DO //OTHER/254 UNRAVEL")
        .await;
    assert_eq!(response.status, 404);
    let unknown = service
        .handle(&mut client, "[2] DO //HARNESS/254/56/1 FROBNICATE")
        .await;
    assert_eq!(unknown.status, 402);
    let short = service.handle(&mut client, "[3] DO").await;
    assert_eq!(short.status, 400);
    let missing_method = service
        .handle(&mut client, "[4] DO //HARNESS/254/56/1")
        .await;
    assert_eq!(missing_method.status, 400);
    std::fs::remove_file(path).unwrap();
}

#[tokio::test(start_paused = true)]
async fn do_edlt_factory_default_is_guarded_and_sent_once() {
    async fn pci_line<R: tokio::io::AsyncBufRead + Unpin>(reader: &mut R) -> Vec<u8> {
        let mut line = Vec::new();
        reader.read_until(b'\r', &mut line).await.unwrap();
        line
    }
    async fn pci_reply<W: tokio::io::AsyncWrite + Unpin>(writer: &mut W, source: u8, cal: &[u8]) {
        let mut bytes = vec![0x86, source, 0x10, 0x00];
        bytes.extend_from_slice(cal);
        let sum = bytes.iter().fold(0u8, |sum, byte| sum.wrapping_add(*byte));
        bytes.push(0u8.wrapping_sub(sum));
        let mut wire = hex::encode_upper(bytes).into_bytes();
        wire.extend_from_slice(b"\r\n");
        writer.write_all(&wire).await.unwrap();
    }

    let path = state_path();
    let (pci, remote) = pci();
    let (remote_read, mut remote_write) = tokio::io::split(remote);
    let mut remote_read = BufReader::new(remote_read);
    let reset = tokio::spawn({
        let pci = pci.clone();
        async move { pci.pci_reset().await }
    });
    for _ in 0..8 {
        pci_line(&mut remote_read).await;
    }
    reset.await.unwrap().unwrap();

    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    service
        .record_label("received", Some(5), 56, &[0xa4, 1, 0, 0, b'X'])
        .await;
    let mut client = ClientState::default();
    let request = service.handle(&mut client, "[1] DO //HARNESS/254/p/5 FactoryDefault");
    let peer = async {
        let wire = pci_line(&mut remote_read).await;
        assert_eq!(&wire[..wire.len() - 2], b"\\46050900A4FF43B2B262");
        let confirmation = wire[wire.len() - 2];
        remote_write.write_all(&[confirmation, b'.']).await.unwrap();
        pci_reply(&mut remote_write, 5, &[0x32, 0xff, 0x43]).await;
    };
    let (response, ()) = tokio::join!(request, peer);
    assert_eq!(response.status, 202);
    assert_eq!(response.final_text, "202 Done: //HARNESS/254/p/5");
    assert!(service.observed_labels.lock().await.observations.is_empty());

    for command in [
        "[2] DO //HARNESS/254/p/4 FactoryDefault",
        "[3] DO //HARNESS/253/p/5 FactoryDefault",
        "[4] DO //HARNESS/254/p/5 FactoryDefault extra",
    ] {
        assert!(
            service.handle(&mut client, command).await.status >= 400,
            "{command}"
        );
    }
    std::fs::remove_file(path).unwrap();
}

#[tokio::test(start_paused = true)]
async fn routed_label_kfi_and_edlt_commands_use_target_network_only() {
    async fn pci_line<R: tokio::io::AsyncBufRead + Unpin>(reader: &mut R) -> Vec<u8> {
        let mut line = Vec::new();
        reader.read_until(b'\r', &mut line).await.unwrap();
        line
    }

    async fn confirm_line<R, W>(reader: &mut R, writer: &mut W, expected: &[u8])
    where
        R: tokio::io::AsyncBufRead + Unpin,
        W: tokio::io::AsyncWrite + Unpin,
    {
        let wire = pci_line(reader).await;
        assert_eq!(&wire[..wire.len() - 2], expected);
        writer
            .write_all(&[wire[wire.len() - 2], b'.'])
            .await
            .unwrap();
    }

    let xml = topology_fixture().replace(
        r#"<Unit oid="remote-4"><Address>4</Address><UnitType>KEYE1</UnitType></Unit>"#,
        r#"<Unit oid="remote-4"><Address>4</Address><UnitType>KEYE1</UnitType></Unit>
        <Unit oid="remote-edlt-5"><Address>5</Address><TagName>Remote eDLT</TagName><UnitType>KEYGL5</UnitType><FirmwareVersion>5.5.00</FirmwareVersion></Unit>"#,
    );
    let path = state_path();
    let (pci, remote) = pci();
    let (remote_read, mut remote_write) = tokio::io::split(remote);
    let mut remote_read = BufReader::new(remote_read);
    let reset = tokio::spawn({
        let pci = pci.clone();
        async move { pci.pci_reset().await }
    });
    for _ in 0..8 {
        pci_line(&mut remote_read).await;
    }
    reset.await.unwrap().unwrap();

    let service = Service::new(&xml, None, path.clone(), pci, None).unwrap();
    service
        .record_label("received", Some(4), 56, &[0xa4, 1, 0, 0, b'L'])
        .await;
    let mut client = ClientState::default();
    let bridges = [253];

    let command = service.handle(&mut client, "[1] LABEL CLEAR //TOPO/253/56 5 8");
    let peer = confirm_line(
        &mut remote_read,
        &mut remote_write,
        b"\\46FD0905A4FF0066089E",
    );
    let (response, ()) = tokio::join!(command, peer);
    assert_eq!(response.status, 200, "{response:?}");

    let command = service.handle(
        &mut client,
        "[2] LABEL KFISET //TOPO/253/56 5 1 2 3 4 5 6 7 8",
    );
    let peer = async {
        for expected in [
            b"\\46FD0905A3FF000904".as_slice(),
            b"\\46FD0905A5FF0084214323".as_slice(),
            b"\\46FD0905A5FF008465879B".as_slice(),
            b"\\46FD0905A4FF006BACF5".as_slice(),
        ] {
            confirm_line(&mut remote_read, &mut remote_write, expected).await;
            routed_pci_reply(&mut remote_write, &bridges, 5, &[0x32, 0xff, 0]).await;
        }
    };
    let (response, ()) = tokio::join!(command, peer);
    assert_eq!(response.status, 200, "{response:?}");

    let command = service.handle(&mut client, "[3] LABEL KFIGET //TOPO/253/56 5");
    let peer = async {
        for expected in [
            b"\\46FD0905A3FF000904".as_slice(),
            b"\\46FD0905A5FF0082001C6D".as_slice(),
            b"\\46FD0905A5FF008404FF84".as_slice(),
        ] {
            confirm_line(&mut remote_read, &mut remote_write, expected).await;
            routed_pci_reply(&mut remote_write, &bridges, 5, &[0x32, 0xff, 0]).await;
        }
        confirm_line(&mut remote_read, &mut remote_write, b"\\46FD0905213D51").await;
        routed_pci_reply(
            &mut remote_write,
            &bridges,
            5,
            &[
                0x8d, 0x3d, 0x80, 0x21, 0x43, 0x65, 0x87, 0, 0, 0, 0, 0, 0, 0,
            ],
        )
        .await;
    };
    let (response, ()) = tokio::join!(command, peer);
    assert_eq!(response.status, 300, "{response:?}");
    assert_eq!(response.final_text, "300 kfi8=8");

    let command = service.handle(&mut client, "[4] LABEL CLEAREDLT //TOPO/253/p/5");
    let peer = async {
        confirm_line(
            &mut remote_read,
            &mut remote_write,
            b"\\46FD0905A4FF43C1EA1E",
        )
        .await;
        routed_pci_reply(&mut remote_write, &bridges, 5, &[0x32, 0xff, 0x43]).await;
    };
    let (response, ()) = tokio::join!(command, peer);
    assert_eq!(response.status, 200, "{response:?}");

    let command = service.handle(&mut client, "[5] DO //TOPO/253/p/5 FactoryDefault");
    let peer = async {
        confirm_line(
            &mut remote_read,
            &mut remote_write,
            b"\\46FD0905A4FF43B2B265",
        )
        .await;
        routed_pci_reply(&mut remote_write, &bridges, 5, &[0x32, 0xff, 0x43]).await;
    };
    let (response, ()) = tokio::join!(command, peer);
    assert_eq!(response.status, 202, "{response:?}");

    let labels = service.observed_labels.lock().await;
    assert_eq!(labels.observations.len(), 1);
    assert_eq!(labels.observations[0].payload_hex, "a40100004c");
    drop(labels);
    std::fs::remove_file(path).unwrap();
}

#[tokio::test(start_paused = true)]
async fn physical_label_clear_matches_native_wire_and_confirmation_contract() {
    async fn pci_line<R: tokio::io::AsyncBufRead + Unpin>(reader: &mut R) -> Vec<u8> {
        let mut line = Vec::new();
        reader.read_until(b'\r', &mut line).await.unwrap();
        line
    }

    let path = state_path();
    let (pci, remote) = pci();
    let (remote_read, mut remote_write) = tokio::io::split(remote);
    let mut remote_read = BufReader::new(remote_read);
    let reset = tokio::spawn({
        let pci = pci.clone();
        async move { pci.pci_reset().await }
    });
    for _ in 0..8 {
        pci_line(&mut remote_read).await;
    }
    reset.await.unwrap().unwrap();

    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    service
        .record_label("received", Some(5), 56, &[0xa4, 1, 0, 0, b'X'])
        .await;
    let mut events = service.events.subscribe();
    let mut client = ClientState::default();

    let all = service.handle(&mut client, "[1] LABEL CLEAR //HARNESS/254/56 5");
    let peer = async {
        let wire = pci_line(&mut remote_read).await;
        assert_eq!(&wire[..wire.len() - 2], b"\\460500A3FF0027EC");
        let confirmation = wire[wire.len() - 2];
        remote_write.write_all(&[confirmation, b'.']).await.unwrap();
    };
    let (response, ()) = tokio::join!(all, peer);
    assert_eq!(response.status, 200, "{response:?}");
    assert_eq!(response.final_text, "200 OK");
    assert!(service.observed_labels.lock().await.observations.is_empty());
    assert!(
        events.try_recv().is_err(),
        "native LABEL CLEAR does not emit a synthetic event"
    );

    // Native C-Gate considers either correlated PCI confirmation outcome to
    // complete this command. No unit ACK/readback follows the confirmation.
    let one = service.handle(&mut client, "[2] LABEL CLEAR //HARNESS/254/202 5 8");
    let peer = async {
        let wire = pci_line(&mut remote_read).await;
        assert_eq!(&wire[..wire.len() - 2], b"\\460500A4FF006608A4");
        let confirmation = wire[wire.len() - 2];
        remote_write.write_all(&[confirmation, b'#']).await.unwrap();
    };
    let (response, ()) = tokio::join!(one, peer);
    assert_eq!(response.status, 200, "{response:?}");
    assert_eq!(response.final_text, "200 OK");
    assert!(
        events.try_recv().is_err(),
        "keyed native LABEL CLEAR does not emit a synthetic event"
    );

    let missing = service.handle(&mut client, "[3] LABEL CLEAR //HARNESS/254/95 5 1");
    let peer = async {
        let wire = pci_line(&mut remote_read).await;
        assert_eq!(&wire[..wire.len() - 2], b"\\460500A4FF006601AB");
        tokio::time::advance(Duration::from_secs(2)).await;
        tokio::task::yield_now().await;
    };
    let (response, ()) = tokio::join!(missing, peer);
    assert_eq!(response.status, 408, "{response:?}");
    assert!(
        response
            .final_text
            .starts_with("408 //HARNESS/254/95 (command failed:"),
        "{response:?}"
    );
    let mut unexpected = Vec::new();
    let followup = tokio::time::timeout(
        Duration::from_millis(1),
        remote_read.read_until(b'\r', &mut unexpected),
    )
    .await;
    assert!(
        unexpected.is_empty() && !matches!(followup, Ok(Ok(received)) if received != 0),
        "LABEL CLEAR must not replay after a missing confirmation: {unexpected:?}"
    );

    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn physical_label_clear_parser_rejects_bad_scope_and_values_without_io() {
    let path = state_path();
    let (pci, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let mut client = ClientState::default();
    for command in [
        "[1] LABEL CLEAR",
        "[2] LABEL CLEAR //HARNESS/254/56",
        "[3] LABEL CLEAR //HARNESS/254/56 5 1 extra",
        "[4] LABEL CLEAR //OTHER/254/56 5",
        "[5] LABEL CLEAR //HARNESS/253/56 5",
        "[6] LABEL CLEAR //HARNESS/254/25 5",
        "[7] LABEL CLEAR //HARNESS/254/56 256",
        "[8] LABEL CLEAR //HARNESS/254/56 unit",
        "[9] LABEL CLEAR //HARNESS/254/56 5 0",
        "[10] LABEL CLEAR //HARNESS/254/56 5 9",
        "[11] LABEL CLEAR //HARNESS/254/56 5 key",
    ] {
        let response = service.handle(&mut client, command).await;
        assert!(response.status >= 400, "{command}: {response:?}");
    }
    let mut byte = [0u8; 1];
    assert!(
        tokio::time::timeout(Duration::from_millis(1), remote.read(&mut byte))
            .await
            .is_err()
    );
    std::fs::remove_file(path).unwrap();
}

#[tokio::test(start_paused = true)]
async fn physical_label_kfi_commands_match_native_wire_and_responses() {
    async fn pci_line<R: tokio::io::AsyncBufRead + Unpin>(reader: &mut R) -> Vec<u8> {
        let mut line = Vec::new();
        reader.read_until(b'\r', &mut line).await.unwrap();
        line
    }
    async fn pci_reply<W: tokio::io::AsyncWrite + Unpin>(writer: &mut W, source: u8, cal: &[u8]) {
        let mut bytes = vec![0x86, source, 0x10, 0x00];
        bytes.extend_from_slice(cal);
        let sum = bytes.iter().fold(0u8, |sum, byte| sum.wrapping_add(*byte));
        bytes.push(0u8.wrapping_sub(sum));
        let mut wire = hex::encode_upper(bytes).into_bytes();
        wire.extend_from_slice(b"\r\n");
        writer.write_all(&wire).await.unwrap();
    }
    async fn kfi_get_preamble<R, W>(reader: &mut R, writer: &mut W) -> u8
    where
        R: tokio::io::AsyncBufRead + Unpin,
        W: tokio::io::AsyncWrite + Unpin,
    {
        for expected in [
            b"\\460500A3FF00090A".as_slice(),
            b"\\460500A5FF0082001C73".as_slice(),
            b"\\460500A5FF008404FF8A".as_slice(),
        ] {
            let request = pci_line(reader).await;
            assert_eq!(&request[..request.len() - 2], expected);
            let code = request[request.len() - 2];
            writer.write_all(&[code, b'.']).await.unwrap();
            pci_reply(writer, 5, &[0x32, 0xff, 0]).await;
        }
        let request = pci_line(reader).await;
        assert_eq!(&request[..request.len() - 2], b"\\460500213D57");
        request[request.len() - 2]
    }
    async fn kfi_reply<W: tokio::io::AsyncWrite + Unpin>(
        writer: &mut W,
        source: u8,
        packed: [u8; 4],
    ) {
        let mut cal = vec![0x8d, cbus_protocol::kfi::ATTRIBUTE, 0x80];
        cal.extend_from_slice(&packed);
        cal.extend_from_slice(&[0; 7]);
        pci_reply(writer, source, &cal).await;
    }

    let path = state_path();
    let (pci, remote) = pci();
    let (remote_read, mut remote_write) = tokio::io::split(remote);
    let mut remote_read = BufReader::new(remote_read);
    let reset = tokio::spawn({
        let pci = pci.clone();
        async move { pci.pci_reset().await }
    });
    for _ in 0..8 {
        pci_line(&mut remote_read).await;
    }
    reset.await.unwrap().unwrap();

    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let mut client = ClientState::default();
    let get = service.handle(&mut client, "[1] LABEL KFIGET //HARNESS/254/56 5");
    let peer = async {
        let code = kfi_get_preamble(&mut remote_read, &mut remote_write).await;
        // Wrong-source data is unrelated and must not complete the command.
        kfi_reply(&mut remote_write, 4, [0xff; 4]).await;
        kfi_reply(&mut remote_write, 5, [0x21, 0x43, 0x65, 0x87]).await;
        remote_write.write_all(&[code, b'.']).await.unwrap();
        tokio::time::advance(Duration::from_secs(2)).await;
        tokio::task::yield_now().await;
    };
    let (response, ()) = tokio::join!(get, peer);
    assert_eq!(response.status, 300, "{response:?}");
    assert_eq!(
        response.lines,
        vec![
            "300-kfi1=1",
            "300-kfi2=2",
            "300-kfi3=3",
            "300-kfi4=4",
            "300-kfi5=5",
            "300-kfi6=6",
            "300-kfi7=7",
        ]
    );
    assert_eq!(response.final_text, "300 kfi8=8");

    let set = service.handle(
        &mut client,
        "[2] LABEL KFISET //HARNESS/254/56 5 1 2 3 4 5 6 7 8",
    );
    let peer = async {
        for expected in [
            b"\\460500A3FF00090A".as_slice(),
            b"\\460500A5FF0084214329".as_slice(),
            b"\\460500A5FF00846587A1".as_slice(),
            b"\\460500A4FF006BACFB".as_slice(),
        ] {
            let request = pci_line(&mut remote_read).await;
            assert_eq!(&request[..request.len() - 2], expected);
            let code = request[request.len() - 2];
            remote_write.write_all(&[code, b'.']).await.unwrap();
            pci_reply(&mut remote_write, 5, &[0x32, 0xff, 0]).await;
        }
    };
    let (response, ()) = tokio::join!(set, peer);
    assert_eq!(response.status, 200, "{response:?}");

    // Decompiled kz treats the application as a LabelSupportingApplication
    // scope/class check. kv receives no application ID and intentionally uses
    // the same fixed 0x1c selector for this non-Lighting application.
    let no_response = service.handle(&mut client, "[3] LABEL KFIGET //HARNESS/254/202 5");
    let peer = async {
        let code = kfi_get_preamble(&mut remote_read, &mut remote_write).await;
        remote_write.write_all(&[code, b'.']).await.unwrap();
        tokio::time::advance(Duration::from_secs(2)).await;
        tokio::task::yield_now().await;
    };
    let (response, ()) = tokio::join!(no_response, peer);
    assert_eq!(response.status, 524);
    assert_eq!(response.final_text, "524 No response.");

    let multiple = service.handle(&mut client, "[4] LABEL KFIGET //HARNESS/254/56 5");
    let peer = async {
        let code = kfi_get_preamble(&mut remote_read, &mut remote_write).await;
        remote_write.write_all(&[code, b'.']).await.unwrap();
        kfi_reply(&mut remote_write, 5, [0x21, 0x43, 0x65, 0x87]).await;
        kfi_reply(&mut remote_write, 5, [0x10, 0x32, 0x54, 0x76]).await;
    };
    let (response, ()) = tokio::join!(multiple, peer);
    assert_eq!(response.status, 524);
    assert_eq!(response.final_text, "524 Too many responses.");

    // Decompiled command wrappers map setup/write failures through
    // MethodException to the native 408 application-scoped envelope.
    let rejected = service.handle(
        &mut client,
        "[5] LABEL KFISET //HARNESS/254/56 5 1 2 3 4 5 6 7 8",
    );
    let peer = async {
        let request = pci_line(&mut remote_read).await;
        assert_eq!(&request[..request.len() - 2], b"\\460500A3FF00090A");
        let code = request[request.len() - 2];
        remote_write.write_all(&[code, b'.']).await.unwrap();
        pci_reply(&mut remote_write, 5, &[0x32, 0xff, 0]).await;

        let request = pci_line(&mut remote_read).await;
        assert_eq!(&request[..request.len() - 2], b"\\460500A5FF0084214329");
        let code = request[request.len() - 2];
        remote_write.write_all(&[code, b'.']).await.unwrap();
        pci_reply(&mut remote_write, 5, &[0x3b, 0xff, 0]).await;
    };
    let (response, ()) = tokio::join!(rejected, peer);
    assert_eq!(response.status, 408);
    assert!(
        response
            .final_text
            .starts_with("408 //HARNESS/254/56 (command failed:"),
        "{response:?}"
    );
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn physical_label_kfi_parser_rejects_bad_arity_scope_and_values_without_io() {
    let path = state_path();
    let (pci, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let mut client = ClientState::default();
    for command in [
        "[1] LABEL KFIGET //HARNESS/254/56",
        "[2] LABEL KFIGET //HARNESS/254/56 5 extra",
        "[3] LABEL KFIGET //OTHER/254/56 5",
        "[4] LABEL KFIGET //HARNESS/254/25 5",
        "[5] LABEL KFIGET //HARNESS/254/56 256",
        "[6] LABEL KFISET //HARNESS/254/56 5 0 1 2 3 4 5 6",
        "[7] LABEL KFISET //HARNESS/254/56 5 0 1 2 3 4 5 6 16",
        "[8] LABEL KFISET //HARNESS/254/56 5 0 1 2 3 4 5 6 seven",
        "[9] LABEL KFISET //HARNESS/254/56 5 0 1 2 3 4 5 6 7 extra",
    ] {
        let response = service.handle(&mut client, command).await;
        assert!(response.status >= 400, "{command}: {response:?}");
    }
    let mut byte = [0u8; 1];
    assert!(
        tokio::time::timeout(Duration::from_millis(1), remote.read(&mut byte))
            .await
            .is_err()
    );
    std::fs::remove_file(path).unwrap();
}

/// General UNRAVEL forms are physical; malformed and foreign forms still
/// reject before the shared PCI sees traffic.
#[tokio::test]
async fn general_net_unravel_rejects_invalid_scope_before_io() {
    let path = state_path();
    let (pci, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let mut client = ClientState::default();
    let response = service
        .handle(&mut client, "[1] NET UNRAVEL //OTHER/254")
        .await;
    assert_eq!(response.status, 404);
    let response = service
        .handle(&mut client, "[2] NET UNRAVELUNIT //HARNESS/254 nope")
        .await;
    assert_eq!(response.status, 400);
    assert_eq!(
        service.handle(&mut client, "[3] NET UNRAVEL").await.status,
        400
    );
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn routed_unravel_rejects_incomplete_topology_before_io() {
    let path = state_path();
    let xml = topology_fixture().replace(
        "<Unit oid=\"bridge-253-near\"><Address>253</Address><UnitType>BRIDGE2N</UnitType></Unit>",
        "<Unit oid=\"bridge-253-near\"><Address>252</Address><UnitType>BRIDGE2N</UnitType></Unit>",
    );
    let (pci, mut remote) = pci();
    let service = Service::new(&xml, None, path.clone(), pci, None).unwrap();
    let response = service
        .handle(
            &mut ClientState::default(),
            "[route] NET UNRAVEL //TOPO/253 MATCHDB",
        )
        .await;
    assert_eq!(response.status, 408, "{response:?}");
    assert!(response.final_text.contains("Physical route unavailable"));
    assert!(
        tokio::time::timeout(Duration::from_millis(30), remote.read_u8())
            .await
            .is_err(),
        "unresolved route must refuse before PCI I/O"
    );
    std::fs::remove_file(path).unwrap();
}

#[tokio::test(start_paused = true)]
async fn bounded_matchdb_unravel_uses_selected_serial_and_verifies_full_inventory() {
    async fn pci_line<R: tokio::io::AsyncBufRead + Unpin>(reader: &mut R) -> Vec<u8> {
        let mut line = Vec::new();
        reader.read_until(b'\r', &mut line).await.unwrap();
        line
    }
    async fn direct_reply<W: tokio::io::AsyncWrite + Unpin>(
        writer: &mut W,
        source: u8,
        cal: &[u8],
    ) {
        let mut bytes = vec![0x86, source, 0x10, 0x00];
        bytes.extend_from_slice(cal);
        let sum = bytes.iter().fold(0u8, |sum, byte| sum.wrapping_add(*byte));
        bytes.push(0u8.wrapping_sub(sum));
        let mut wire = hex::encode_upper(bytes).into_bytes();
        wire.extend_from_slice(b"\r\n");
        writer.write_all(&wire).await.unwrap();
    }
    fn packed(serial: &str) -> [u8; 4] {
        cbus_protocol::serial_address::parse_native_serial(serial)
            .unwrap()
            .packed
    }
    fn identity(serial: &str, address: u8) -> Vec<u8> {
        let mut data = vec![0x38, 0xff, 0xff, 0xff, 0xff];
        data.extend_from_slice(&packed(serial));
        data.extend_from_slice(&[0xa2, 0, address]);
        data
    }
    fn mmi_block(start: u8, count: usize, present: &[usize]) -> Vec<u8> {
        let mut states = vec![0u8; count];
        for address in present {
            states[*address - usize::from(start)] = 1;
        }
        let mut wire = cbus_protocol::packet::Packet::StandardStatus {
            application: 0xff,
            block_start: start,
            states,
        }
        .encode_packet()
        .unwrap();
        wire.extend_from_slice(b"\r\n");
        wire
    }
    async fn mmi<R, W>(reader: &mut R, writer: &mut W, present: &[usize])
    where
        R: tokio::io::AsyncBufRead + Unpin,
        W: tokio::io::AsyncWrite + Unpin,
    {
        let request = pci_line(reader).await;
        assert!(request.starts_with(b"\\05FF00FAFF"), "{request:?}");
        let code = request[request.len() - 2];
        writer.write_all(&[code, b'.']).await.unwrap();
        for (start, count) in [(0, 88), (88, 88), (176, 80)] {
            let block_present = present
                .iter()
                .copied()
                .filter(|address| (start..start + count).contains(address))
                .collect::<Vec<_>>();
            writer
                .write_all(&mmi_block(start as u8, count, &block_present))
                .await
                .unwrap();
        }
        tokio::task::yield_now().await;
    }
    async fn identify<R, W>(reader: &mut R, writer: &mut W, address: u8, serials: &[&str])
    where
        R: tokio::io::AsyncBufRead + Unpin,
        W: tokio::io::AsyncWrite + Unpin,
    {
        let request = pci_line(reader).await;
        assert!(request.starts_with(format!("\\46{address:02X}002104").as_bytes()));
        let code = request[request.len() - 2];
        writer.write_all(&[code, b'.']).await.unwrap();
        for serial in serials {
            let mut cal = vec![0x8d, 4];
            cal.extend_from_slice(&identity(serial, address));
            direct_reply(writer, address, &cal).await;
        }
        tokio::time::advance(Duration::from_secs(2)).await;
        tokio::task::yield_now().await;
    }
    async fn local_options<R, W>(reader: &mut R, writer: &mut W)
    where
        R: tokio::io::AsyncBufRead + Unpin,
        W: tokio::io::AsyncWrite + Unpin,
    {
        let request = pci_line(reader).await;
        assert!(request.starts_with(b"\\4610001A4201"), "{request:?}");
        direct_reply(writer, 16, &[0x82, 0x42, 5]).await;
    }
    async fn selected<R, W>(reader: &mut R, writer: &mut W, serial: &str, destination: u8)
    where
        R: tokio::io::AsyncBufRead + Unpin,
        W: tokio::io::AsyncWrite + Unpin,
    {
        let request = pci_line(reader).await;
        assert!(request.starts_with(b"\\05FF000F00"), "{request:?}");
        let encoded_serial = hex::encode_upper(packed(serial));
        assert!(request
            .windows(encoded_serial.len())
            .any(|window| window == encoded_serial.as_bytes()));
        let code = request[request.len() - 2];
        writer.write_all(&[code, b'.']).await.unwrap();
        let mut cal = vec![0x87, 0];
        cal.extend_from_slice(&packed(serial));
        cal.extend_from_slice(&[0, 0]);
        direct_reply(writer, destination, &cal).await;
        tokio::time::advance(Duration::from_secs(2)).await;
        tokio::task::yield_now().await;
    }

    let path = state_path();
    let (original_pci, remote) = pci();
    let (remote_read, mut remote_write) = tokio::io::split(remote);
    let mut remote_read = BufReader::new(remote_read);
    let reset = tokio::spawn({
        let pci = original_pci.clone();
        async move { pci.pci_reset().await }
    });
    for _ in 0..8 {
        pci_line(&mut remote_read).await;
    }
    reset.await.unwrap().unwrap();

    let service = Service::new(&fixture(), None, path.clone(), original_pci, None).unwrap();
    {
        let mut model = service.model.lock().await;
        let network = model
            .projects
            .get_mut("HARNESS")
            .unwrap()
            .networks
            .get_mut(&254)
            .unwrap();
        for (address, serial, unit_type) in [
            (6, "101136.1558", "KEYE1"),
            (7, "101136.1559", "KEYE1"),
            (16, "100966.1187", "PC_CNI"),
        ] {
            let mut unit = Unit::blank(address, "");
            unit.serial = serial.to_string();
            unit.unit_type = unit_type.to_string();
            unit.firmware = "2.5.00".to_string();
            network.units.insert(address, unit);
        }
    }
    let unravel = tokio::spawn({
        let service = service.clone();
        async move {
            service
                .handle(
                    &mut ClientState::default(),
                    "[1] NET UNRAVELUNIT //HARNESS/254 255 MATCHDB",
                )
                .await
        }
    });

    mmi(&mut remote_read, &mut remote_write, &[16, 255]).await;
    identify(&mut remote_read, &mut remote_write, 16, &["100966.1187"]).await;
    identify(
        &mut remote_read,
        &mut remote_write,
        255,
        &["101136.1558", "101136.1559"],
    )
    .await;
    local_options(&mut remote_read, &mut remote_write).await;
    identify(&mut remote_read, &mut remote_write, 6, &[]).await;
    identify(&mut remote_read, &mut remote_write, 7, &[]).await;

    selected(&mut remote_read, &mut remote_write, "101136.1558", 6).await;
    identify(&mut remote_read, &mut remote_write, 6, &["101136.1558"]).await;
    selected(&mut remote_read, &mut remote_write, "101136.1559", 7).await;
    identify(&mut remote_read, &mut remote_write, 7, &["101136.1559"]).await;

    mmi(&mut remote_read, &mut remote_write, &[6, 7, 16]).await;
    identify(&mut remote_read, &mut remote_write, 6, &["101136.1558"]).await;
    identify(&mut remote_read, &mut remote_write, 7, &["101136.1559"]).await;
    identify(&mut remote_read, &mut remote_write, 16, &["100966.1187"]).await;
    local_options(&mut remote_read, &mut remote_write).await;

    let response = unravel.await.unwrap();
    assert_eq!(response.status, 200, "{}", response.final_text);
    let model = service.model.lock().await;
    let network = &model.projects["HARNESS"].networks[&254];
    assert!(!network.physical.contains_key(&255));
    assert_eq!(network.physical[&6].serial, "101136.1558");
    assert_eq!(network.physical[&7].serial, "101136.1559");
    assert_eq!(network.physical[&16].serial, "100966.1187");
    assert_eq!(network.units[&6].address, 6);
    assert_eq!(network.units[&7].address, 7);
    drop(model);

    // The general whole-network backend is also the DO UNRAVEL backend.
    // With a healthy unique inventory it performs the two native inventory
    // passes, sends no address write, and returns the method envelope.
    let healthy = tokio::spawn({
        let service = service.clone();
        async move {
            service
                .handle(&mut ClientState::default(), "[1b] DO //HARNESS/254 UNRAVEL")
                .await
        }
    });
    for _ in 0..2 {
        mmi(&mut remote_read, &mut remote_write, &[6, 7, 16]).await;
        identify(&mut remote_read, &mut remote_write, 6, &["101136.1558"]).await;
        identify(&mut remote_read, &mut remote_write, 7, &["101136.1559"]).await;
        identify(&mut remote_read, &mut remote_write, 16, &["100966.1187"]).await;
    }
    let healthy = healthy.await.unwrap();
    assert_eq!(healthy.status, 202, "{healthy:?}");
    assert_eq!(healthy.final_text, "202 Done: //HARNESS/254");
    assert!(healthy
        .lines
        .iter()
        .any(|line| line == "120-Unravel: Complete."));

    let mut events = service.events.subscribe();
    let reconnecting = tokio::spawn({
        let service = service.clone();
        async move {
            service
                .handle(
                    &mut ClientState::default(),
                    "[2] NET UNRAVELUNIT //HARNESS/254 255 MATCHDB",
                )
                .await
        }
    });
    mmi(&mut remote_read, &mut remote_write, &[16, 255]).await;
    identify(&mut remote_read, &mut remote_write, 16, &["100966.1187"]).await;
    identify(
        &mut remote_read,
        &mut remote_write,
        255,
        &["101136.1558", "101136.1559"],
    )
    .await;
    local_options(&mut remote_read, &mut remote_write).await;
    identify(&mut remote_read, &mut remote_write, 6, &[]).await;
    identify(&mut remote_read, &mut remote_write, 7, &[]).await;
    selected(&mut remote_read, &mut remote_write, "101136.1558", 6).await;
    identify(&mut remote_read, &mut remote_write, 6, &["101136.1558"]).await;
    selected(&mut remote_read, &mut remote_write, "101136.1559", 7).await;
    identify(&mut remote_read, &mut remote_write, 7, &["101136.1559"]).await;
    mmi(&mut remote_read, &mut remote_write, &[6, 7, 16]).await;
    identify(&mut remote_read, &mut remote_write, 6, &["101136.1558"]).await;
    identify(&mut remote_read, &mut remote_write, 7, &["101136.1559"]).await;
    identify(&mut remote_read, &mut remote_write, 16, &["100966.1187"]).await;

    let options_request = pci_line(&mut remote_read).await;
    assert!(
        options_request.starts_with(b"\\4610001A4201"),
        "{options_request:?}"
    );
    let model_guard = service.model.lock().await;
    let (replacement, _replacement_remote) = pci();
    let replacing = tokio::spawn({
        let service = service.clone();
        async move { service.set_pci(replacement).await }
    });
    for _ in 0..100 {
        if service.pci_generation.load(Ordering::Acquire) == 1 {
            break;
        }
        tokio::task::yield_now().await;
    }
    assert_eq!(service.pci_generation.load(Ordering::Acquire), 1);
    direct_reply(&mut remote_write, 16, &[0x82, 0x42, 5]).await;
    tokio::task::yield_now().await;
    drop(model_guard);
    replacing.await.unwrap();

    let response = reconnecting.await.unwrap();
    assert_eq!(response.status, 408, "{response:?}");
    assert_eq!(
        response.final_text,
        "408 Unravel invalidated by PCI reconnect after 2 move(s)"
    );
    assert!(
        service.model.lock().await.projects["HARNESS"].networks[&254]
            .physical
            .is_empty(),
        "the old final inventory must not repopulate the replacement cache"
    );
    assert!(
        events.try_recv().is_err(),
        "no staged old-generation move or success event may escape"
    );
    std::fs::remove_file(path).unwrap();
}

#[tokio::test(start_paused = true)]
async fn routed_matchdb_unravel_correlates_every_reply_and_commits_only_target() {
    async fn line<R: tokio::io::AsyncBufRead + Unpin>(reader: &mut R) -> Vec<u8> {
        let mut line = Vec::new();
        reader.read_until(b'\r', &mut line).await.unwrap();
        line
    }
    fn packed(serial: &str) -> [u8; 4] {
        cbus_protocol::serial_address::parse_native_serial(serial)
            .unwrap()
            .packed
    }
    fn identity(serial: &str, address: u8) -> Vec<u8> {
        let mut data = vec![0x38, 0xff, 0xff, 0xff, 0xff];
        data.extend_from_slice(&packed(serial));
        data.extend_from_slice(&[0xa2, 0, address]);
        data
    }
    async fn mmi<R, W>(reader: &mut R, writer: &mut W, present: &[usize])
    where
        R: tokio::io::AsyncBufRead + Unpin,
        W: tokio::io::AsyncWrite + Unpin,
    {
        let request = line(reader).await;
        assert!(request.starts_with(b"\\03FD09FFFAFF00FF"), "{request:?}");
        let code = request[request.len() - 2];
        writer.write_all(&[code, b'.']).await.unwrap();
        for (start, count) in [(0, 88), (88, 88), (176, 80)] {
            writer
                .write_all(&routed_mmi_block(
                    &[253],
                    start,
                    count,
                    &present
                        .iter()
                        .copied()
                        .map(|address| (address, 1))
                        .collect::<Vec<_>>(),
                ))
                .await
                .unwrap();
        }
        tokio::task::yield_now().await;
    }
    async fn identify<R, W>(reader: &mut R, writer: &mut W, address: u8, serials: &[&str])
    where
        R: tokio::io::AsyncBufRead + Unpin,
        W: tokio::io::AsyncWrite + Unpin,
    {
        let request = line(reader).await;
        assert!(
            request.starts_with(format!("\\46FD09{address:02X}2104").as_bytes()),
            "{request:?}"
        );
        let code = request[request.len() - 2];
        writer.write_all(&[code, b'.']).await.unwrap();
        for serial in serials {
            let mut cal = vec![0x8d, 4];
            cal.extend_from_slice(&identity(serial, address));
            routed_pci_reply(writer, &[253], address, &cal).await;
        }
        tokio::time::advance(Duration::from_secs(2)).await;
        tokio::task::yield_now().await;
    }
    async fn local_options<R, W>(reader: &mut R, writer: &mut W)
    where
        R: tokio::io::AsyncBufRead + Unpin,
        W: tokio::io::AsyncWrite + Unpin,
    {
        let request = line(reader).await;
        assert!(request.starts_with(b"\\4610001A4201"), "{request:?}");
        let mut bytes = vec![0x86, 16, 0x10, 0x00, 0x82, 0x42, 5];
        let sum = bytes.iter().fold(0u8, |sum, byte| sum.wrapping_add(*byte));
        bytes.push(0u8.wrapping_sub(sum));
        let mut wire = hex::encode_upper(bytes).into_bytes();
        wire.extend_from_slice(b"\r\n");
        writer.write_all(&wire).await.unwrap();
    }
    async fn selected<R, W>(reader: &mut R, writer: &mut W, serial: &str, destination: u8)
    where
        R: tokio::io::AsyncBufRead + Unpin,
        W: tokio::io::AsyncWrite + Unpin,
    {
        let request = line(reader).await;
        let expected = cbus_protocol::serial_address::encode_serial_address_routed(
            serial,
            destination,
            &[253],
            true,
            b'g',
        )
        .unwrap();
        assert_eq!(
            &request[..request.len() - 2],
            &expected[..expected.len() - 2]
        );
        let code = request[request.len() - 2];
        writer.write_all(&[code, b'.']).await.unwrap();
        let mut cal = vec![0x87, 0];
        cal.extend_from_slice(&packed(serial));
        cal.extend_from_slice(&[0, 0]);
        routed_pci_reply(writer, &[253], destination, &cal).await;
        tokio::time::advance(Duration::from_secs(2)).await;
        tokio::task::yield_now().await;
    }

    let xml = topology_fixture()
        .replace(
            "<Unit oid=\"pci-16\"><Address>16</Address><UnitType>PC_CNI2</UnitType></Unit>",
            "<Unit oid=\"pci-16\"><Address>16</Address><UnitType>PC_CNI2</UnitType><SerialNumber>100966.1187</SerialNumber></Unit>",
        )
        .replace(
            "<Unit oid=\"remote-4\"><Address>4</Address><UnitType>KEYE1</UnitType></Unit>",
            "<Unit oid=\"remote-6\"><Address>6</Address><UnitType>KEYE1</UnitType><SerialNumber>101136.1558</SerialNumber></Unit><Unit oid=\"remote-7\"><Address>7</Address><UnitType>KEYE1</UnitType><SerialNumber>101136.1559</SerialNumber></Unit>",
        );
    let path = state_path();
    let (pci, remote) = pci();
    let (remote_read, mut remote_write) = tokio::io::split(remote);
    let mut remote_read = BufReader::new(remote_read);
    let reset = tokio::spawn({
        let pci = pci.clone();
        async move { pci.pci_reset().await }
    });
    for _ in 0..8 {
        line(&mut remote_read).await;
    }
    reset.await.unwrap().unwrap();
    let service = Service::new(&xml, None, path.clone(), pci, None).unwrap();
    {
        let mut model = service.model.lock().await;
        model
            .projects
            .get_mut("TOPO")
            .unwrap()
            .networks
            .get_mut(&254)
            .unwrap()
            .physical
            .insert(42, Unit::blank(42, "local-cache-sentinel"));
    }
    let command = tokio::spawn({
        let service = service.clone();
        async move {
            service
                .handle(
                    &mut ClientState::default(),
                    "[r] NET UNRAVELUNIT //TOPO/253 255 MATCHDB",
                )
                .await
        }
    });

    mmi(&mut remote_read, &mut remote_write, &[255]).await;
    identify(
        &mut remote_read,
        &mut remote_write,
        255,
        &["101136.1558", "101136.1559"],
    )
    .await;
    local_options(&mut remote_read, &mut remote_write).await;
    identify(&mut remote_read, &mut remote_write, 6, &[]).await;
    identify(&mut remote_read, &mut remote_write, 7, &[]).await;
    selected(&mut remote_read, &mut remote_write, "101136.1558", 6).await;
    identify(&mut remote_read, &mut remote_write, 6, &["101136.1558"]).await;
    selected(&mut remote_read, &mut remote_write, "101136.1559", 7).await;
    identify(&mut remote_read, &mut remote_write, 7, &["101136.1559"]).await;
    mmi(&mut remote_read, &mut remote_write, &[6, 7]).await;
    identify(&mut remote_read, &mut remote_write, 6, &["101136.1558"]).await;
    identify(&mut remote_read, &mut remote_write, 7, &["101136.1559"]).await;
    local_options(&mut remote_read, &mut remote_write).await;

    let response = command.await.unwrap();
    assert_eq!(response.status, 200, "{response:?}");
    let model = service.model.lock().await;
    let mut target_addresses = model.projects["TOPO"].networks[&253]
        .physical
        .keys()
        .copied()
        .collect::<Vec<_>>();
    target_addresses.sort_unstable();
    assert_eq!(target_addresses, [6, 7]);
    assert_eq!(
        model.projects["TOPO"].networks[&254].physical[&42].fields["UnitName"],
        "local-cache-sentinel"
    );
    assert_eq!(
        model.projects["TOPO"].networks[&253].state,
        NetworkState::Ok
    );
    drop(model);
    std::fs::remove_file(path).unwrap();
}

/// Native C-Gate declares CHECK_UNRAVEL obsolete and returns 400 without
/// running it; the service answers likewise instead of the generic 502.
#[tokio::test]
async fn net_check_unravel_is_obsolete_400() {
    let path = state_path();
    let (pci, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let mut client = ClientState::default();
    for line in [
        "[1] NET CHECK_UNRAVEL //HARNESS/254",
        "[2] NET CHECK_UNRAVEL",
    ] {
        let response = service.handle(&mut client, line).await;
        assert_eq!(response.status, 400, "{line}");
        assert_eq!(
            response.final_text, "400 NET CHECK_UNRAVEL is obsolete",
            "{line}"
        );
    }
    std::fs::remove_file(path).unwrap();
}

/// P2 partial-write evidence: when a physical PP SAVE fails after a
/// confirmed range write, the service must never report success, must
/// report how many writes were confirmed, and must retain dirty flags.
#[tokio::test]
async fn physical_pp_save_reports_partial_write_evidence_and_retains_dirty() {
    async fn pci_line<R: tokio::io::AsyncBufRead + Unpin>(reader: &mut R) -> Vec<u8> {
        let mut line = Vec::new();
        reader.read_until(b'\r', &mut line).await.unwrap();
        line
    }
    async fn pci_reply<W: tokio::io::AsyncWrite + Unpin>(writer: &mut W, source: u8, cal: &[u8]) {
        let mut bytes = vec![0x86, source, 0x10, 0x00];
        bytes.extend_from_slice(cal);
        let sum = bytes.iter().fold(0u8, |sum, byte| sum.wrapping_add(*byte));
        bytes.push(0u8.wrapping_sub(sum));
        let mut wire = hex::encode_upper(bytes).into_bytes();
        wire.extend_from_slice(b"\r\n");
        writer.write_all(&wire).await.unwrap();
    }

    let path = state_path();
    let spec_dir = std::env::temp_dir().join(format!(
        "cmqttd-pp-partial-{}-{}.d",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    std::fs::create_dir_all(&spec_dir).unwrap();
    std::fs::write(
        spec_dir.join("TESTUNIT.xml"),
        r#"<UnitSpecification><Parameters>
        <Param><Name>Alpha</Name><Type>int</Type><Address>$20</Address><ArraySize>2</ArraySize><ProgramMethod>direct</ProgramMethod><Protection>none</Protection></Param>
        <Param><Name>Beta</Name><Type>int</Type><Address>$30</Address><ArraySize>2</ArraySize><ProgramMethod>direct</ProgramMethod><Protection>none</Protection></Param>
        </Parameters></UnitSpecification>"#,
    )
    .unwrap();
    let (pci, remote) = pci();
    let (remote_read, mut remote_write) = tokio::io::split(remote);
    let mut remote_read = BufReader::new(remote_read);
    let reset = tokio::spawn({
        let pci = pci.clone();
        async move { pci.pci_reset().await }
    });
    for _ in 0..8 {
        pci_line(&mut remote_read).await;
    }
    reset.await.unwrap().unwrap();

    let service =
        Service::new(&fixture(), None, path.clone(), pci, Some(spec_dir.clone())).unwrap();
    let mut client = ClientState::default();
    for line in [
        "[1] PP LOCK L //HARNESS/254",
        "[2] PP START S L",
        "[3] PP NEW S TESTUNIT 1.2.03",
        "[4] PP SET S Alpha 0x56 0x78",
        "[5] PP SET S Beta 0xAB 0xCD",
    ] {
        let response = service.handle(&mut client, line).await;
        assert_eq!(response.status, 200, "{line}: {}", response.final_text);
    }

    let checker = service.clone();
    let saving = tokio::spawn(async move {
        service
            .handle(&mut client, "[9] PP SAVE S //HARNESS/254/p/5")
            .await
    });

    let request = pci_line(&mut remote_read).await;
    assert!(
        request.windows(4).any(|window| window == b"2101"),
        "{request:?}"
    );
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    pci_reply(
        &mut remote_write,
        5,
        &[0x89, 0x01, b'T', b'E', b'S', b'T', b'U', b'N', b'I', b'T'],
    )
    .await;
    let request = pci_line(&mut remote_read).await;
    assert!(
        request.windows(4).any(|window| window == b"2102"),
        "{request:?}"
    );
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    pci_reply(
        &mut remote_write,
        5,
        &[0x87, 0x02, b'1', b'.', b'2', b'.', b'0', b'3'],
    )
    .await;

    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\4605001A2002"), "{request:?}");
    pci_reply(&mut remote_write, 5, &[0x83, 0x20, 0x00, 0x00]).await;
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\4605001A3002"), "{request:?}");
    pci_reply(&mut remote_write, 5, &[0x83, 0x30, 0x00, 0x00]).await;

    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\460500A42000"), "{request:?}");
    pci_reply(&mut remote_write, 5, &[0x32, 0x20, 0x00]).await;
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\4605001A2002"), "{request:?}");
    pci_reply(&mut remote_write, 5, &[0x83, 0x20, 0x56, 0x78]).await;

    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\460500A43000"), "{request:?}");
    pci_reply(&mut remote_write, 5, &[0x3b, 0x30, 0x00]).await;

    let response = saving.await.unwrap();
    assert_eq!(
        response.status, 502,
        "partial PP SAVE must never report success: {}",
        response.final_text
    );
    assert!(
        response
            .final_text
            .starts_with("502 Physical PP save failed after 1 confirmed write(s):"),
        "reason must report partial-write evidence: {}",
        response.final_text
    );
    assert!(
        response.final_text.contains("unit rejected"),
        "underlying diagnostic must be preserved: {}",
        response.final_text
    );

    let model = checker.model.lock().await;
    let session = model
        .sessions
        .get("S")
        .expect("session survives failed save");
    assert!(session.dirty.contains("Alpha"), "dirty={:?}", session.dirty);
    assert!(session.dirty.contains("Beta"), "dirty={:?}", session.dirty);
    drop(model);

    std::fs::remove_file(&path).unwrap();
    std::fs::remove_file(spec_dir.join("TESTUNIT.xml")).unwrap();
    std::fs::remove_dir(&spec_dir).unwrap();
}

/// P2 partial-write evidence for the NVM-commit path: when every STORE
/// write is confirmed but Save-to-NVM fails, the 502 reason must still
/// report how many writes were confirmed, and dirty flags are retained.
/// The EXECUTE/POLL failure pattern mirrors
/// `definitive_save_to_nvm_failures_do_not_fault_programming_lane` in
/// `cbus-transport`: a definitive status reply closes the transaction
/// without faulting the programming lane.
#[tokio::test]
async fn physical_pp_save_nvm_failure_reports_confirmed_writes_and_retains_dirty() {
    async fn pci_line<R: tokio::io::AsyncBufRead + Unpin>(reader: &mut R) -> Vec<u8> {
        let mut line = Vec::new();
        reader.read_until(b'\r', &mut line).await.unwrap();
        line
    }
    async fn pci_reply<W: tokio::io::AsyncWrite + Unpin>(writer: &mut W, source: u8, cal: &[u8]) {
        let mut bytes = vec![0x86, source, 0x10, 0x00];
        bytes.extend_from_slice(cal);
        let sum = bytes.iter().fold(0u8, |sum, byte| sum.wrapping_add(*byte));
        bytes.push(0u8.wrapping_sub(sum));
        let mut wire = hex::encode_upper(bytes).into_bytes();
        wire.extend_from_slice(b"\r\n");
        writer.write_all(&wire).await.unwrap();
    }

    let path = state_path();
    let spec_dir = std::env::temp_dir().join(format!(
        "cmqttd-pp-nvm-{}-{}.d",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    std::fs::create_dir_all(&spec_dir).unwrap();
    // Gamma is never staged, so it needs no PCI scripting; its NCC program
    // method only switches the service onto the Save-to-NVM commit path.
    std::fs::write(
        spec_dir.join("TESTUNIT.xml"),
        r#"<UnitSpecification><Parameters>
        <Param><Name>Alpha</Name><Type>int</Type><Address>$20</Address><ArraySize>2</ArraySize><ProgramMethod>direct</ProgramMethod><Protection>none</Protection></Param>
        <Param><Name>Beta</Name><Type>int</Type><Address>$30</Address><ArraySize>2</ArraySize><ProgramMethod>direct</ProgramMethod><Protection>none</Protection></Param>
        <Param><Name>Gamma</Name><Type>int</Type><Address>$40</Address><ArraySize>2</ArraySize><ProgramMethod>ncc</ProgramMethod><Protection>none</Protection></Param>
        </Parameters></UnitSpecification>"#,
    )
    .unwrap();

    let (pci, remote) = pci();
    let (remote_read, mut remote_write) = tokio::io::split(remote);
    let mut remote_read = BufReader::new(remote_read);
    let reset = tokio::spawn({
        let pci = pci.clone();
        async move { pci.pci_reset().await }
    });
    for _ in 0..8 {
        pci_line(&mut remote_read).await;
    }
    reset.await.unwrap().unwrap();

    let service =
        Service::new(&fixture(), None, path.clone(), pci, Some(spec_dir.clone())).unwrap();
    let mut client = ClientState::default();
    for line in [
        "[1] PP LOCK L //HARNESS/254",
        "[2] PP START S L",
        "[3] PP NEW S TESTUNIT 1.2.03",
        "[4] PP SET S Alpha 0x56 0x78",
        "[5] PP SET S Beta 0xAB 0xCD",
    ] {
        let response = service.handle(&mut client, line).await;
        assert_eq!(response.status, 200, "{line}: {}", response.final_text);
    }

    let checker = service.clone();
    let saving = tokio::spawn(async move {
        service
            .handle(&mut client, "[9] PP SAVE S //HARNESS/254/p/5")
            .await
    });

    let request = pci_line(&mut remote_read).await;
    assert!(
        request.windows(4).any(|window| window == b"2101"),
        "{request:?}"
    );
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    pci_reply(
        &mut remote_write,
        5,
        &[0x89, 0x01, b'T', b'E', b'S', b'T', b'U', b'N', b'I', b'T'],
    )
    .await;
    let request = pci_line(&mut remote_read).await;
    assert!(
        request.windows(4).any(|window| window == b"2102"),
        "{request:?}"
    );
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    pci_reply(
        &mut remote_write,
        5,
        &[0x87, 0x02, b'1', b'.', b'2', b'.', b'0', b'3'],
    )
    .await;

    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\4605001A2002"), "{request:?}");
    pci_reply(&mut remote_write, 5, &[0x83, 0x20, 0x00, 0x00]).await;
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\4605001A3002"), "{request:?}");
    pci_reply(&mut remote_write, 5, &[0x83, 0x30, 0x00, 0x00]).await;

    // Both STORE writes succeed with matching readbacks.
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\460500A42000"), "{request:?}");
    pci_reply(&mut remote_write, 5, &[0x32, 0x20, 0x00]).await;
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\4605001A2002"), "{request:?}");
    pci_reply(&mut remote_write, 5, &[0x83, 0x20, 0x56, 0x78]).await;

    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\460500A43000"), "{request:?}");
    pci_reply(&mut remote_write, 5, &[0x32, 0x30, 0x00]).await;
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\4605001A3002"), "{request:?}");
    pci_reply(&mut remote_write, 5, &[0x83, 0x30, 0xAB, 0xCD]).await;

    // The NCC catalogue forces a Save-to-NVM commit; fail it with the
    // definitive EXECUTE busy status. Extended exchanges carry no PCI
    // confirmation character.
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\460500E3810004"), "{request:?}");
    pci_reply(&mut remote_write, 5, &[0xe4, 0x83, 0, 4, 2]).await;

    let response = saving.await.unwrap();
    assert_eq!(
        response.status, 502,
        "NVM-commit failure must never report success: {}",
        response.final_text
    );
    assert!(
        response
            .final_text
            .starts_with("502 Physical PP Save-to-NVM failed after 2 confirmed write(s):"),
        "reason must report partial-write evidence: {}",
        response.final_text
    );
    assert!(
        response.final_text.contains("busy"),
        "underlying diagnostic must be preserved: {}",
        response.final_text
    );

    let model = checker.model.lock().await;
    let session = model
        .sessions
        .get("S")
        .expect("session survives failed save");
    assert!(session.dirty.contains("Alpha"), "dirty={:?}", session.dirty);
    assert!(session.dirty.contains("Beta"), "dirty={:?}", session.dirty);
    drop(model);

    std::fs::remove_file(&path).unwrap();
    std::fs::remove_file(spec_dir.join("TESTUNIT.xml")).unwrap();
    std::fs::remove_dir(&spec_dir).unwrap();
}

/// Drop-guard for the three new PP SAVE tests below: removes the temp state
/// file plus the spec dir on drop so cleanup still runs if an assert panics.
struct PpSaveCleanup {
    state: PathBuf,
    spec_dir: PathBuf,
}

impl PpSaveCleanup {
    fn new(state: PathBuf, spec_dir: PathBuf) -> Self {
        Self { state, spec_dir }
    }
}

impl Drop for PpSaveCleanup {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.state);
        let _ = std::fs::remove_file(self.spec_dir.join("TESTUNIT.xml"));
        let _ = std::fs::remove_dir(&self.spec_dir);
    }
}

/// P2 zero-confirmed pin: when the FIRST STORE fails, the 502 reason must
/// still carry the `after 0 confirmed write(s):` evidence prefix (including
/// the pluralised zero-case grammar), preserve the underlying diagnostic,
/// and retain every dirty flag.
#[tokio::test]
async fn physical_pp_save_first_store_failure_reports_zero_confirmed_and_retains_dirty() {
    async fn pci_line<R: tokio::io::AsyncBufRead + Unpin>(reader: &mut R) -> Vec<u8> {
        let mut line = Vec::new();
        reader.read_until(b'\r', &mut line).await.unwrap();
        line
    }
    async fn pci_reply<W: tokio::io::AsyncWrite + Unpin>(writer: &mut W, source: u8, cal: &[u8]) {
        let mut bytes = vec![0x86, source, 0x10, 0x00];
        bytes.extend_from_slice(cal);
        let sum = bytes.iter().fold(0u8, |sum, byte| sum.wrapping_add(*byte));
        bytes.push(0u8.wrapping_sub(sum));
        let mut wire = hex::encode_upper(bytes).into_bytes();
        wire.extend_from_slice(b"\r\n");
        writer.write_all(&wire).await.unwrap();
    }

    let path = state_path();
    let spec_dir = std::env::temp_dir().join(format!(
        "cmqttd-pp-zero-{}-{}.d",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    std::fs::create_dir_all(&spec_dir).unwrap();
    std::fs::write(
        spec_dir.join("TESTUNIT.xml"),
        r#"<UnitSpecification><Parameters>
        <Param><Name>Alpha</Name><Type>int</Type><Address>$20</Address><ArraySize>2</ArraySize><ProgramMethod>direct</ProgramMethod><Protection>none</Protection></Param>
        <Param><Name>Beta</Name><Type>int</Type><Address>$30</Address><ArraySize>2</ArraySize><ProgramMethod>direct</ProgramMethod><Protection>none</Protection></Param>
        </Parameters></UnitSpecification>"#,
    )
    .unwrap();
    let _cleanup = PpSaveCleanup::new(path.clone(), spec_dir.clone());

    let (pci, remote) = pci();
    let (remote_read, mut remote_write) = tokio::io::split(remote);
    let mut remote_read = BufReader::new(remote_read);
    let reset = tokio::spawn({
        let pci = pci.clone();
        async move { pci.pci_reset().await }
    });
    for _ in 0..8 {
        pci_line(&mut remote_read).await;
    }
    reset.await.unwrap().unwrap();

    let service =
        Service::new(&fixture(), None, path.clone(), pci, Some(spec_dir.clone())).unwrap();
    let mut client = ClientState::default();
    for line in [
        "[1] PP LOCK L //HARNESS/254",
        "[2] PP START S L",
        "[3] PP NEW S TESTUNIT 1.2.03",
        "[4] PP SET S Alpha 0x56 0x78",
        "[5] PP SET S Beta 0xAB 0xCD",
    ] {
        let response = service.handle(&mut client, line).await;
        assert_eq!(response.status, 200, "{line}: {}", response.final_text);
    }

    let checker = service.clone();
    let saving = tokio::spawn(async move {
        service
            .handle(&mut client, "[9] PP SAVE S //HARNESS/254/p/5")
            .await
    });

    let request = pci_line(&mut remote_read).await;
    assert!(
        request.windows(4).any(|window| window == b"2101"),
        "{request:?}"
    );
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    pci_reply(
        &mut remote_write,
        5,
        &[0x89, 0x01, b'T', b'E', b'S', b'T', b'U', b'N', b'I', b'T'],
    )
    .await;
    let request = pci_line(&mut remote_read).await;
    assert!(
        request.windows(4).any(|window| window == b"2102"),
        "{request:?}"
    );
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    pci_reply(
        &mut remote_write,
        5,
        &[0x87, 0x02, b'1', b'.', b'2', b'.', b'0', b'3'],
    )
    .await;

    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\4605001A2002"), "{request:?}");
    pci_reply(&mut remote_write, 5, &[0x83, 0x20, 0x00, 0x00]).await;
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\4605001A3002"), "{request:?}");
    pci_reply(&mut remote_write, 5, &[0x83, 0x30, 0x00, 0x00]).await;

    // The FIRST STORE receives the matching tagged NAK, so no write is ever
    // confirmed. Beta is never attempted.
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\460500A42000"), "{request:?}");
    pci_reply(&mut remote_write, 5, &[0x3b, 0x20, 0x00]).await;

    // Negative read: no retry, readback, or next-range STORE may follow the
    // definitive failure. The save future is concurrently pending, so any
    // stray write would appear on the wire promptly; a 750ms window is
    // generous enough to avoid flakes on a loaded machine while still
    // proving deterministically that the failure path emits nothing further.
    let followup =
        tokio::time::timeout(Duration::from_millis(750), pci_line(&mut remote_read)).await;
    assert!(
        followup.is_err() || followup.is_ok_and(|wire| wire.is_empty()),
        "no further wire bytes expected after definitive STORE failure"
    );

    let response = saving.await.unwrap();
    assert_eq!(
        response.status, 502,
        "failed PP SAVE must never report success: {}",
        response.final_text
    );
    assert!(
        response
            .final_text
            .starts_with("502 Physical PP save failed after 0 confirmed write(s):"),
        "reason must report the zero-confirmed evidence: {}",
        response.final_text
    );
    assert!(
        response.final_text.contains("unit rejected"),
        "underlying diagnostic must be preserved: {}",
        response.final_text
    );

    let model = checker.model.lock().await;
    let session = model
        .sessions
        .get("S")
        .expect("session survives failed save");
    assert!(session.dirty.contains("Alpha"), "dirty={:?}", session.dirty);
    assert!(session.dirty.contains("Beta"), "dirty={:?}", session.dirty);
    assert_eq!(session.dirty.len(), 2, "dirty={:?}", session.dirty);
    drop(model);

    // Cleanup runs via the PpSaveCleanup drop-guard.
}

/// P2 multi-space pin: the shared `confirmed` counter must span STORE arms.
/// A successful Standard write followed by a failed Paged write reports
/// `after 1 confirmed write(s):`, proving the count is not per-space.
#[tokio::test]
async fn physical_pp_save_counts_paged_write_toward_confirmed_total() {
    async fn pci_line<R: tokio::io::AsyncBufRead + Unpin>(reader: &mut R) -> Vec<u8> {
        let mut line = Vec::new();
        reader.read_until(b'\r', &mut line).await.unwrap();
        line
    }
    async fn pci_reply<W: tokio::io::AsyncWrite + Unpin>(writer: &mut W, source: u8, cal: &[u8]) {
        let mut bytes = vec![0x86, source, 0x10, 0x00];
        bytes.extend_from_slice(cal);
        let sum = bytes.iter().fold(0u8, |sum, byte| sum.wrapping_add(*byte));
        bytes.push(0u8.wrapping_sub(sum));
        let mut wire = hex::encode_upper(bytes).into_bytes();
        wire.extend_from_slice(b"\r\n");
        writer.write_all(&wire).await.unwrap();
    }

    let path = state_path();
    let spec_dir = std::env::temp_dir().join(format!(
        "cmqttd-pp-multispace-{}-{}.d",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    std::fs::create_dir_all(&spec_dir).unwrap();
    std::fs::write(
        spec_dir.join("TESTUNIT.xml"),
        r#"<UnitSpecification><Parameters>
        <Param><Name>Alpha</Name><Type>int</Type><Address>$20</Address><ArraySize>2</ArraySize><ProgramMethod>direct</ProgramMethod><Protection>none</Protection></Param>
        <Param><Name>Paged1</Name><Type>int</Type><Address>$100</Address><ArraySize>2</ArraySize><ProgramMethod>paged</ProgramMethod><Protection>none</Protection></Param>
        </Parameters></UnitSpecification>"#,
    )
    .unwrap();
    let _cleanup = PpSaveCleanup::new(path.clone(), spec_dir.clone());

    let (pci, remote) = pci();
    let (remote_read, mut remote_write) = tokio::io::split(remote);
    let mut remote_read = BufReader::new(remote_read);
    let reset = tokio::spawn({
        let pci = pci.clone();
        async move { pci.pci_reset().await }
    });
    for _ in 0..8 {
        pci_line(&mut remote_read).await;
    }
    reset.await.unwrap().unwrap();

    let service =
        Service::new(&fixture(), None, path.clone(), pci, Some(spec_dir.clone())).unwrap();
    let mut client = ClientState::default();
    for line in [
        "[1] PP LOCK L //HARNESS/254",
        "[2] PP START S L",
        "[3] PP NEW S TESTUNIT 1.2.03",
        "[4] PP SET S Alpha 0x56 0x78",
        "[5] PP SET S Paged1 0x01 0x02",
    ] {
        let response = service.handle(&mut client, line).await;
        assert_eq!(response.status, 200, "{line}: {}", response.final_text);
    }

    let checker = service.clone();
    let saving = tokio::spawn(async move {
        service
            .handle(&mut client, "[9] PP SAVE S //HARNESS/254/p/5")
            .await
    });

    let request = pci_line(&mut remote_read).await;
    assert!(
        request.windows(4).any(|window| window == b"2101"),
        "{request:?}"
    );
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    pci_reply(
        &mut remote_write,
        5,
        &[0x89, 0x01, b'T', b'E', b'S', b'T', b'U', b'N', b'I', b'T'],
    )
    .await;
    let request = pci_line(&mut remote_read).await;
    assert!(
        request.windows(4).any(|window| window == b"2102"),
        "{request:?}"
    );
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    pci_reply(
        &mut remote_write,
        5,
        &[0x87, 0x02, b'1', b'.', b'2', b'.', b'0', b'3'],
    )
    .await;

    // Save pre-reads run per merged (space, range): Standard before Paged.
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\4605001A2002"), "{request:?}");
    pci_reply(&mut remote_write, 5, &[0x83, 0x20, 0x00, 0x00]).await;
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\4605001B010002"), "{request:?}");
    pci_reply(&mut remote_write, 5, &[0x83, 0x00, 0x00, 0x00]).await;

    // Writes run in unit-spec order: the Standard STORE succeeds first.
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\460500A42000"), "{request:?}");
    pci_reply(&mut remote_write, 5, &[0x32, 0x20, 0x00]).await;
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\4605001A2002"), "{request:?}");
    pci_reply(&mut remote_write, 5, &[0x83, 0x20, 0x56, 0x78]).await;

    // The Paged STORE then fails (page select succeeds, tagged STORE receives
    // its matching NAK). The shared counter must still report the one
    // confirmed Standard write.
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\4605003901"), "{request:?}");
    pci_reply(&mut remote_write, 5, &[0x81, 0x01]).await;
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\460500A40000"), "{request:?}");
    pci_reply(&mut remote_write, 5, &[0x3b, 0x00, 0x00]).await;

    // Negative read: no retry, readback, or further STORE may follow the
    // definitive paged failure. The save future is concurrently pending, so
    // any stray write would appear on the wire promptly; a 750ms window is
    // generous enough to avoid flakes on a loaded machine while still
    // proving deterministically that the failure path emits nothing further.
    let followup =
        tokio::time::timeout(Duration::from_millis(750), pci_line(&mut remote_read)).await;
    assert!(
        followup.is_err() || followup.is_ok_and(|wire| wire.is_empty()),
        "no further wire bytes expected after definitive paged STORE failure"
    );

    let response = saving.await.unwrap();
    assert_eq!(
        response.status, 502,
        "partial PP SAVE must never report success: {}",
        response.final_text
    );
    assert!(
        response
            .final_text
            .starts_with("502 Physical PP save failed after 1 confirmed write(s):"),
        "reason must count the Standard write across space arms: {}",
        response.final_text
    );
    assert!(
        response.final_text.contains("unit rejected"),
        "underlying diagnostic must be preserved: {}",
        response.final_text
    );

    let model = checker.model.lock().await;
    let session = model
        .sessions
        .get("S")
        .expect("session survives failed save");
    assert!(session.dirty.contains("Alpha"), "dirty={:?}", session.dirty);
    assert!(
        session.dirty.contains("Paged1"),
        "dirty={:?}",
        session.dirty
    );
    assert_eq!(session.dirty.len(), 2, "dirty={:?}", session.dirty);
    drop(model);

    // Cleanup runs via the PpSaveCleanup drop-guard.
}

/// P2 unchanged-skip pin: an item whose staged value equals the pre-read
/// (`modified == original`) is skipped via `continue` without counting.
/// With the middle of three dirty params unchanged and the third STORE
/// failing, the evidence must read 1, not 2.
#[tokio::test]
async fn physical_pp_save_skips_unchanged_items_without_counting() {
    async fn pci_line<R: tokio::io::AsyncBufRead + Unpin>(reader: &mut R) -> Vec<u8> {
        let mut line = Vec::new();
        reader.read_until(b'\r', &mut line).await.unwrap();
        line
    }
    async fn pci_reply<W: tokio::io::AsyncWrite + Unpin>(writer: &mut W, source: u8, cal: &[u8]) {
        let mut bytes = vec![0x86, source, 0x10, 0x00];
        bytes.extend_from_slice(cal);
        let sum = bytes.iter().fold(0u8, |sum, byte| sum.wrapping_add(*byte));
        bytes.push(0u8.wrapping_sub(sum));
        let mut wire = hex::encode_upper(bytes).into_bytes();
        wire.extend_from_slice(b"\r\n");
        writer.write_all(&wire).await.unwrap();
    }

    let path = state_path();
    let spec_dir = std::env::temp_dir().join(format!(
        "cmqttd-pp-skip-{}-{}.d",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    std::fs::create_dir_all(&spec_dir).unwrap();
    std::fs::write(
        spec_dir.join("TESTUNIT.xml"),
        r#"<UnitSpecification><Parameters>
        <Param><Name>Alpha</Name><Type>int</Type><Address>$20</Address><ArraySize>2</ArraySize><ProgramMethod>direct</ProgramMethod><Protection>none</Protection></Param>
        <Param><Name>Beta</Name><Type>int</Type><Address>$30</Address><ArraySize>2</ArraySize><ProgramMethod>direct</ProgramMethod><Protection>none</Protection></Param>
        <Param><Name>Gamma</Name><Type>int</Type><Address>$40</Address><ArraySize>2</ArraySize><ProgramMethod>direct</ProgramMethod><Protection>none</Protection></Param>
        </Parameters></UnitSpecification>"#,
    )
    .unwrap();
    let _cleanup = PpSaveCleanup::new(path.clone(), spec_dir.clone());

    let (pci, remote) = pci();
    let (remote_read, mut remote_write) = tokio::io::split(remote);
    let mut remote_read = BufReader::new(remote_read);
    let reset = tokio::spawn({
        let pci = pci.clone();
        async move { pci.pci_reset().await }
    });
    for _ in 0..8 {
        pci_line(&mut remote_read).await;
    }
    reset.await.unwrap().unwrap();

    let service =
        Service::new(&fixture(), None, path.clone(), pci, Some(spec_dir.clone())).unwrap();
    let mut client = ClientState::default();
    for line in [
        "[1] PP LOCK L //HARNESS/254",
        "[2] PP START S L",
        "[3] PP NEW S TESTUNIT 1.2.03",
        // Beta is staged dirty but matches the scripted pre-read below, so
        // the save must skip it without touching the wire or the counter.
        "[4] PP SET S Alpha 0x56 0x78",
        "[5] PP SET S Beta 0x00 0x00",
        "[6] PP SET S Gamma 0xAB 0xCD",
    ] {
        let response = service.handle(&mut client, line).await;
        assert_eq!(response.status, 200, "{line}: {}", response.final_text);
    }

    let checker = service.clone();
    let saving = tokio::spawn(async move {
        service
            .handle(&mut client, "[9] PP SAVE S //HARNESS/254/p/5")
            .await
    });

    let request = pci_line(&mut remote_read).await;
    assert!(
        request.windows(4).any(|window| window == b"2101"),
        "{request:?}"
    );
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    pci_reply(
        &mut remote_write,
        5,
        &[0x89, 0x01, b'T', b'E', b'S', b'T', b'U', b'N', b'I', b'T'],
    )
    .await;
    let request = pci_line(&mut remote_read).await;
    assert!(
        request.windows(4).any(|window| window == b"2102"),
        "{request:?}"
    );
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    pci_reply(
        &mut remote_write,
        5,
        &[0x87, 0x02, b'1', b'.', b'2', b'.', b'0', b'3'],
    )
    .await;

    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\4605001A2002"), "{request:?}");
    pci_reply(&mut remote_write, 5, &[0x83, 0x20, 0x00, 0x00]).await;
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\4605001A3002"), "{request:?}");
    pci_reply(&mut remote_write, 5, &[0x83, 0x30, 0x00, 0x00]).await;
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\4605001A4002"), "{request:?}");
    pci_reply(&mut remote_write, 5, &[0x83, 0x40, 0x00, 0x00]).await;

    // Alpha STORE succeeds; Beta emits no STORE at all; Gamma STORE fails.
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\460500A42000"), "{request:?}");
    pci_reply(&mut remote_write, 5, &[0x32, 0x20, 0x00]).await;
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\4605001A2002"), "{request:?}");
    pci_reply(&mut remote_write, 5, &[0x83, 0x20, 0x56, 0x78]).await;

    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\460500A44000"), "{request:?}");
    pci_reply(&mut remote_write, 5, &[0x3b, 0x40, 0x00]).await;

    // Negative read: no retry, readback, or further STORE may follow the
    // definitive Gamma failure (Beta was skipped without touching the wire).
    // The save future is concurrently pending, so any stray write would
    // appear on the wire promptly; a 750ms window is generous enough to
    // avoid flakes on a loaded machine while still proving deterministically
    // that the failure path emits nothing further.
    let followup =
        tokio::time::timeout(Duration::from_millis(750), pci_line(&mut remote_read)).await;
    assert!(
        followup.is_err() || followup.is_ok_and(|wire| wire.is_empty()),
        "no further wire bytes expected after definitive STORE failure"
    );

    let response = saving.await.unwrap();
    assert_eq!(
        response.status, 502,
        "partial PP SAVE must never report success: {}",
        response.final_text
    );
    assert!(
        response
            .final_text
            .starts_with("502 Physical PP save failed after 1 confirmed write(s):"),
        "skipped Beta must not be counted (would read 2 otherwise): {}",
        response.final_text
    );
    assert!(
        response.final_text.contains("unit rejected"),
        "underlying diagnostic must be preserved: {}",
        response.final_text
    );

    let model = checker.model.lock().await;
    let session = model
        .sessions
        .get("S")
        .expect("session survives failed save");
    assert!(session.dirty.contains("Alpha"), "dirty={:?}", session.dirty);
    assert!(session.dirty.contains("Beta"), "dirty={:?}", session.dirty);
    assert!(session.dirty.contains("Gamma"), "dirty={:?}", session.dirty);
    assert_eq!(session.dirty.len(), 3, "dirty={:?}", session.dirty);
    drop(model);

    // Cleanup runs via the PpSaveCleanup drop-guard.
}

/// P2 factory-skip pin: a dirty param whose spec declares
/// `Protection: factory` (or `special`) is acknowledged unwriteable by an
/// ordinary SAVE — it is inserted into `cleared` WITHOUT any wire write,
/// so on success it is dropped from `dirty` along with the params that
/// were actually written. This pins the plan-filter asymmetry
/// deliberately: factory-skipped params clear silently, while tag-filtered
/// params (see the next test) stay dirty. If a future change starts
/// writing factory params to the wire, the negative read below fails; if
/// it stops clearing them, the `dirty.is_empty()` assert fails.
#[tokio::test]
async fn physical_pp_save_factory_protected_clears_dirty_without_write() {
    async fn pci_line<R: tokio::io::AsyncBufRead + Unpin>(reader: &mut R) -> Vec<u8> {
        let mut line = Vec::new();
        reader.read_until(b'\r', &mut line).await.unwrap();
        line
    }
    async fn pci_reply<W: tokio::io::AsyncWrite + Unpin>(writer: &mut W, source: u8, cal: &[u8]) {
        let mut bytes = vec![0x86, source, 0x10, 0x00];
        bytes.extend_from_slice(cal);
        let sum = bytes.iter().fold(0u8, |sum, byte| sum.wrapping_add(*byte));
        bytes.push(0u8.wrapping_sub(sum));
        let mut wire = hex::encode_upper(bytes).into_bytes();
        wire.extend_from_slice(b"\r\n");
        writer.write_all(&wire).await.unwrap();
    }

    let path = state_path();
    let spec_dir = std::env::temp_dir().join(format!(
        "cmqttd-pp-factory-{}-{}.d",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    std::fs::create_dir_all(&spec_dir).unwrap();
    std::fs::write(
        spec_dir.join("TESTUNIT.xml"),
        r#"<UnitSpecification><Parameters>
        <Param><Name>Alpha</Name><Type>int</Type><Address>$20</Address><ArraySize>2</ArraySize><ProgramMethod>direct</ProgramMethod><Protection>none</Protection></Param>
        <Param><Name>FactParam</Name><Type>int</Type><Address>$30</Address><ArraySize>2</ArraySize><ProgramMethod>direct</ProgramMethod><Protection>factory</Protection></Param>
        </Parameters></UnitSpecification>"#,
    )
    .unwrap();
    let _cleanup = PpSaveCleanup::new(path.clone(), spec_dir.clone());

    let (pci, remote) = pci();
    let (remote_read, mut remote_write) = tokio::io::split(remote);
    let mut remote_read = BufReader::new(remote_read);
    let reset = tokio::spawn({
        let pci = pci.clone();
        async move { pci.pci_reset().await }
    });
    for _ in 0..8 {
        pci_line(&mut remote_read).await;
    }
    reset.await.unwrap().unwrap();

    let service =
        Service::new(&fixture(), None, path.clone(), pci, Some(spec_dir.clone())).unwrap();
    let mut client = ClientState::default();
    for line in [
        "[1] PP LOCK L //HARNESS/254",
        "[2] PP START S L",
        "[3] PP NEW S TESTUNIT 1.2.03",
        "[4] PP SET S Alpha 0x56 0x78",
        "[5] PP SET S FactParam 0x11 0x22",
    ] {
        let response = service.handle(&mut client, line).await;
        assert_eq!(response.status, 200, "{line}: {}", response.final_text);
    }

    let checker = service.clone();
    let saving = tokio::spawn(async move {
        service
            .handle(&mut client, "[9] PP SAVE S //HARNESS/254/p/5")
            .await
    });

    let request = pci_line(&mut remote_read).await;
    assert!(
        request.windows(4).any(|window| window == b"2101"),
        "{request:?}"
    );
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    pci_reply(
        &mut remote_write,
        5,
        &[0x89, 0x01, b'T', b'E', b'S', b'T', b'U', b'N', b'I', b'T'],
    )
    .await;
    let request = pci_line(&mut remote_read).await;
    assert!(
        request.windows(4).any(|window| window == b"2102"),
        "{request:?}"
    );
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    pci_reply(
        &mut remote_write,
        5,
        &[0x87, 0x02, b'1', b'.', b'2', b'.', b'0', b'3'],
    )
    .await;

    // Only Alpha is pre-read: FactParam is factory-skipped in the planner
    // before any range is merged, so its address never touches the wire.
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\4605001A2002"), "{request:?}");
    pci_reply(&mut remote_write, 5, &[0x83, 0x20, 0x00, 0x00]).await;

    // Alpha STORE succeeds with a matching readback.
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\460500A42000"), "{request:?}");
    pci_reply(&mut remote_write, 5, &[0x32, 0x20, 0x00]).await;
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\4605001A2002"), "{request:?}");
    pci_reply(&mut remote_write, 5, &[0x83, 0x20, 0x56, 0x78]).await;

    let response = saving.await.unwrap();
    assert_eq!(
        response.status, 200,
        "SAVE with only factory-skipped remainder must succeed: {}",
        response.final_text
    );
    assert_eq!(response.final_text, "200 OK", "{}", response.final_text);

    // Negative read: FactParam must never be written. The save future has
    // resolved, so any STORE/readback for $30 would already be on the wire;
    // a 750ms window is generous enough to avoid flakes on a loaded machine
    // while still proving deterministically that nothing further was emitted.
    assert!(
        tokio::time::timeout(Duration::from_millis(750), pci_line(&mut remote_read))
            .await
            .is_err(),
        "no further wire bytes expected: factory param must not be written"
    );

    let model = checker.model.lock().await;
    let session = model
        .sessions
        .get("S")
        .expect("session survives successful save");
    assert!(
        session.dirty.is_empty(),
        "factory-skipped FactParam clears without write: dirty={:?}",
        session.dirty
    );
    drop(model);

    // Cleanup runs via the PpSaveCleanup drop-guard.
}

/// P2 tag-filter pin: a dirty param whose spec `<Tag>` children do not
/// include the SAVE's tag selection is NOT attempted under this tag
/// selection — the planner `continue`s WITHOUT inserting it into `cleared`,
/// so on success it REMAINS dirty for a later save with matching tags.
/// Only Alpha (tagged `core`) is written and cleared; Beta (untagged)
/// stays dirty with `dirty.len() == 1`. If a future change clears
/// tag-filtered params, the `dirty.len()` assert fails; if it attempts
/// them, the scripted wire sequence mismatches (an unexpected $30 pre-read
/// or STORE appears where the Alpha STORE is expected).
#[tokio::test]
async fn physical_pp_save_tag_filter_retains_untagged_dirty() {
    async fn pci_line<R: tokio::io::AsyncBufRead + Unpin>(reader: &mut R) -> Vec<u8> {
        let mut line = Vec::new();
        reader.read_until(b'\r', &mut line).await.unwrap();
        line
    }
    async fn pci_reply<W: tokio::io::AsyncWrite + Unpin>(writer: &mut W, source: u8, cal: &[u8]) {
        let mut bytes = vec![0x86, source, 0x10, 0x00];
        bytes.extend_from_slice(cal);
        let sum = bytes.iter().fold(0u8, |sum, byte| sum.wrapping_add(*byte));
        bytes.push(0u8.wrapping_sub(sum));
        let mut wire = hex::encode_upper(bytes).into_bytes();
        wire.extend_from_slice(b"\r\n");
        writer.write_all(&wire).await.unwrap();
    }

    let path = state_path();
    let spec_dir = std::env::temp_dir().join(format!(
        "cmqttd-pp-tagfilter-{}-{}.d",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    std::fs::create_dir_all(&spec_dir).unwrap();
    std::fs::write(
        spec_dir.join("TESTUNIT.xml"),
        r#"<UnitSpecification><Parameters>
        <Param><Name>Alpha</Name><Type>int</Type><Address>$20</Address><ArraySize>2</ArraySize><ProgramMethod>direct</ProgramMethod><Protection>none</Protection><Tag>core</Tag></Param>
        <Param><Name>Beta</Name><Type>int</Type><Address>$30</Address><ArraySize>2</ArraySize><ProgramMethod>direct</ProgramMethod><Protection>none</Protection></Param>
        </Parameters></UnitSpecification>"#,
    )
    .unwrap();
    let _cleanup = PpSaveCleanup::new(path.clone(), spec_dir.clone());

    let (pci, remote) = pci();
    let (remote_read, mut remote_write) = tokio::io::split(remote);
    let mut remote_read = BufReader::new(remote_read);
    let reset = tokio::spawn({
        let pci = pci.clone();
        async move { pci.pci_reset().await }
    });
    for _ in 0..8 {
        pci_line(&mut remote_read).await;
    }
    reset.await.unwrap().unwrap();

    let service =
        Service::new(&fixture(), None, path.clone(), pci, Some(spec_dir.clone())).unwrap();
    let mut client = ClientState::default();
    for line in [
        "[1] PP LOCK L //HARNESS/254",
        "[2] PP START S L",
        "[3] PP NEW S TESTUNIT 1.2.03",
        "[4] PP SET S Alpha 0x56 0x78",
        "[5] PP SET S Beta 0xAB 0xCD",
    ] {
        let response = service.handle(&mut client, line).await;
        assert_eq!(response.status, 200, "{line}: {}", response.final_text);
    }

    let checker = service.clone();
    let saving = tokio::spawn(async move {
        service
            .handle(&mut client, "[9] PP SAVE S //HARNESS/254/p/5 core")
            .await
    });

    let request = pci_line(&mut remote_read).await;
    assert!(
        request.windows(4).any(|window| window == b"2101"),
        "{request:?}"
    );
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    pci_reply(
        &mut remote_write,
        5,
        &[0x89, 0x01, b'T', b'E', b'S', b'T', b'U', b'N', b'I', b'T'],
    )
    .await;
    let request = pci_line(&mut remote_read).await;
    assert!(
        request.windows(4).any(|window| window == b"2102"),
        "{request:?}"
    );
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    pci_reply(
        &mut remote_write,
        5,
        &[0x87, 0x02, b'1', b'.', b'2', b'.', b'0', b'3'],
    )
    .await;

    // Only Alpha ($20) is pre-read: Beta carries no `core` tag so the
    // planner skips it before range merging. If Beta were attempted, its
    // $30 pre-read would appear here and fail the prefix assert.
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\4605001A2002"), "{request:?}");
    pci_reply(&mut remote_write, 5, &[0x83, 0x20, 0x00, 0x00]).await;

    // Alpha STORE succeeds with a matching readback.
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\460500A42000"), "{request:?}");
    pci_reply(&mut remote_write, 5, &[0x32, 0x20, 0x00]).await;
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\4605001A2002"), "{request:?}");
    pci_reply(&mut remote_write, 5, &[0x83, 0x20, 0x56, 0x78]).await;

    let response = saving.await.unwrap();
    assert_eq!(
        response.status, 200,
        "tag-filtered SAVE must succeed for the selected params: {}",
        response.final_text
    );
    assert_eq!(response.final_text, "200 OK", "{}", response.final_text);

    // Negative read: Beta must never be attempted under this tag selection.
    // The save future has resolved, so any $30 STORE/readback would already
    // be on the wire; a 750ms window is generous enough to avoid flakes on
    // a loaded machine while still proving deterministically that nothing
    // further was emitted.
    assert!(
        tokio::time::timeout(Duration::from_millis(750), pci_line(&mut remote_read))
            .await
            .is_err(),
        "no further wire bytes expected: Beta must not be attempted under tag `core`"
    );

    let model = checker.model.lock().await;
    let session = model
        .sessions
        .get("S")
        .expect("session survives successful save");
    assert!(
        !session.dirty.contains("Alpha"),
        "selected Alpha is written and cleared: dirty={:?}",
        session.dirty
    );
    assert!(
        session.dirty.contains("Beta"),
        "tag-filtered Beta remains dirty for a later save: dirty={:?}",
        session.dirty
    );
    assert_eq!(session.dirty.len(), 1, "dirty={:?}", session.dirty);
    drop(model);

    // Cleanup runs via the PpSaveCleanup drop-guard (tag-filter test).
}

/// P3d: physical NET SYNC that observes MULTIPLE distinct serials at one
/// address must surface the conflict on the event channel instead of
/// silently collapsing the stored serial to "". The response stays 200;
/// the scalar snapshot keeps "" while the sorted duplicate set is retained
/// on `serial_alternates`. Source-address-only eDLT metadata reads are
/// forbidden because their replies cannot be attributed to either unit.
#[tokio::test(start_paused = true)]
async fn physical_net_sync_surfaces_duplicate_serial_conflict_on_events() {
    async fn pci_line<R: tokio::io::AsyncBufRead + Unpin>(reader: &mut R) -> Vec<u8> {
        let mut line = Vec::new();
        reader.read_until(b'\r', &mut line).await.unwrap();
        line
    }
    async fn pci_reply<W: tokio::io::AsyncWrite + Unpin>(writer: &mut W, source: u8, cal: &[u8]) {
        let mut bytes = vec![0x86, source, 0x10, 0x00];
        bytes.extend_from_slice(cal);
        let sum = bytes.iter().fold(0u8, |sum, byte| sum.wrapping_add(*byte));
        bytes.push(0u8.wrapping_sub(sum));
        let mut wire = hex::encode_upper(bytes).into_bytes();
        wire.extend_from_slice(b"\r\n");
        writer.write_all(&wire).await.unwrap();
    }
    fn mmi_block(start: u8, count: usize, present: &[usize]) -> Vec<u8> {
        let mut states = vec![0u8; count];
        for address in present {
            states[*address - usize::from(start)] = 1;
        }
        let mut wire = cbus_protocol::packet::Packet::StandardStatus {
            application: 0xff,
            block_start: start,
            states,
        }
        .encode_packet()
        .unwrap();
        wire.extend_from_slice(b"\r\n");
        wire
    }

    let path = state_path();
    let (pci, remote) = pci();
    let (remote_read, mut remote_write) = tokio::io::split(remote);
    let mut remote_read = BufReader::new(remote_read);
    let reset = tokio::spawn({
        let pci = pci.clone();
        async move { pci.pci_reset().await }
    });
    for _ in 0..8 {
        pci_line(&mut remote_read).await;
    }
    reset.await.unwrap().unwrap();

    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    // Prove an ambiguous refresh clears older metadata rather than serving it
    // as though the duplicate address represented one physical unit.
    let mut stale = Unit::blank(5, "");
    stale.unit_type = "KEYGL5".into();
    for (field, value) in [
        ("FirmwareVersion", "old-extended"),
        ("Application", "1"),
        ("Application2", "2"),
        ("WidgetGroups", "old-widget-groups"),
    ] {
        stale.fields.insert(field.into(), value.into());
    }
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
        .physical
        .insert(5, stale);
    let mut events = service.events.subscribe();
    let syncing = tokio::spawn({
        let service = service.clone();
        async move {
            service
                .handle(&mut ClientState::default(), "[1] NET SYNC //HARNESS/254")
                .await
        }
    });

    // Local-interface discovery: the fixture has no PC_PCI/PC_CNI unit.
    assert_eq!(pci_line(&mut remote_read).await, b"@1A2001\r");
    remote_write.write_all(b"8220104E\r\n").await.unwrap();
    tokio::task::yield_now().await;

    // Installation MMI: only address 5 is present.
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\05FF00FAFF"), "{request:?}");
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    remote_write
        .write_all(&mmi_block(0, 88, &[5]))
        .await
        .unwrap();
    remote_write
        .write_all(&mmi_block(88, 88, &[]))
        .await
        .unwrap();
    remote_write
        .write_all(&mmi_block(176, 80, &[]))
        .await
        .unwrap();
    tokio::task::yield_now().await;

    // Unit type + firmware via identify_first (confirm, then first reply).
    let request = pci_line(&mut remote_read).await;
    assert!(
        request.windows(4).any(|window| window == b"2101"),
        "{request:?}"
    );
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    pci_reply(
        &mut remote_write,
        5,
        &[0x87, 0x01, b'K', b'E', b'Y', b'G', b'L', b'5'],
    )
    .await;
    tokio::task::yield_now().await;
    let request = pci_line(&mut remote_read).await;
    assert!(
        request.windows(4).any(|window| window == b"2102"),
        "{request:?}"
    );
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    pci_reply(
        &mut remote_write,
        5,
        &[0x87, 0x02, b'5', b'.', b'5', b'.', b'0', b'0'],
    )
    .await;
    tokio::task::yield_now().await;

    // Serial probe returns TWO distinct valid IDENTIFY4 replies.
    let first = [
        0x38, 0xff, 0xff, 0xff, 0xff, 0x18, 0xb1, 0x06, 0x16, 0xa2, 0x00, 0x05,
    ];
    let mut second = first;
    second[8] = 0x17;
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\4605002104"), "{request:?}");
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    let mut first_cal = vec![0x8d, 4];
    first_cal.extend_from_slice(&first);
    let mut second_cal = vec![0x8d, 4];
    second_cal.extend_from_slice(&second);
    pci_reply(&mut remote_write, 5, &first_cal).await;
    tokio::time::advance(Duration::from_secs(1)).await;
    tokio::task::yield_now().await;
    assert!(
        !syncing.is_finished(),
        "quiet interval must still be open after the first serial reply"
    );
    pci_reply(&mut remote_write, 5, &second_cal).await;
    tokio::time::advance(Duration::from_secs(2)).await;
    tokio::task::yield_now().await;

    let response = syncing.await.unwrap();
    assert_eq!(
        response.status, 200,
        "conflict must not fail SYNC: {response:?}"
    );

    // The scalar stays collapsed (SerialNumber getter/SET semantics
    // unchanged) while the duplicate set is retained in memory, sorted.
    let model = service.model.lock().await;
    let snapshot = model.projects["HARNESS"].networks[&254]
        .physical
        .get(&5)
        .expect("address 5 was present in the scripted MMI");
    assert_eq!(
        snapshot.serial, "",
        "stored serial stays collapsed: {snapshot:?}"
    );
    assert_eq!(
        snapshot.serial_alternates,
        vec!["101136.1558".to_string(), "101136.1559".to_string()],
        "duplicate set must be retained sorted: {snapshot:?}"
    );
    assert_eq!(snapshot.unit_type, "KEYGL5");
    assert_eq!(snapshot.firmware, "5.5.00");
    assert_eq!(snapshot.field("Version"), "5.5.00");
    for field in [
        "FirmwareVersion",
        "Application",
        "Application2",
        "WidgetGroups",
    ] {
        assert!(
            !snapshot.fields.contains_key(field),
            "ambiguous or stale {field}: {snapshot:?}"
        );
    }
    let configured = &model.projects["HARNESS"].networks[&254].units[&5];
    assert_eq!(configured.unit_type, "KEYGL5");
    assert_eq!(configured.field("FirmwareVersion"), "5.5.00");
    drop(model);

    for (sequence, field) in [
        ("1f", "FirmwareVersion"),
        ("1a", "Application"),
        ("1a2", "Application2"),
        ("1g", "WidgetGroups"),
    ] {
        let get = service
            .handle(
                &mut ClientState::default(),
                &format!("[{sequence}] GET //HARNESS/254/p/5 {field}"),
            )
            .await;
        assert_eq!(get.status, 402, "ambiguous {field}: {get:?}");
    }
    let version = service
        .handle(
            &mut ClientState::default(),
            "[1v] GET //HARNESS/254/p/5 Version",
        )
        .await;
    assert_eq!(version.status, 300);
    assert!(version.final_text.ends_with("Version=5.5.00"));

    assert!(
        tokio::time::timeout(Duration::from_secs(1), pci_line(&mut remote_read))
            .await
            .is_err(),
        "duplicate-address SYNC must not issue source-only eDLT metadata requests"
    );

    let mut seen = Vec::new();
    while let Ok(event) = events.try_recv() {
        seen.push(event);
    }
    assert!(
        seen.iter().any(|event| event.contains("sync ok")),
        "sync-ok event must still be emitted: {seen:?}"
    );
    assert!(
        seen.iter()
            .any(|event| event == "#e# net 254 sync duplicate 5 101136.1558 101136.1559"),
        "RED: no exact duplicate event with sorted serials: {seen:?}"
    );
    let duplicate_pos = seen
        .iter()
        .position(|event| event == "#e# net 254 sync duplicate 5 101136.1558 101136.1559")
        .expect("exact duplicate event must be present");
    let ok_pos = seen
        .iter()
        .position(|event| event == "#e# net 254 sync ok")
        .expect("sync-ok event must be present");
    assert!(
        duplicate_pos < ok_pos,
        "duplicate event must precede sync ok: {seen:?}"
    );

    std::fs::remove_file(path).unwrap();
}

#[derive(Clone, Copy, Debug)]
enum AmbiguousRawSerialReplies {
    KnownAndUnknown,
    RepeatedKnown,
}

async fn run_state_two_ambiguous_raw_serial_sync(case: AmbiguousRawSerialReplies) {
    async fn pci_line<R: tokio::io::AsyncBufRead + Unpin>(reader: &mut R) -> Vec<u8> {
        let mut line = Vec::new();
        reader.read_until(b'\r', &mut line).await.unwrap();
        line
    }
    async fn pci_reply<W: tokio::io::AsyncWrite + Unpin>(writer: &mut W, source: u8, cal: &[u8]) {
        let mut bytes = vec![0x86, source, 0x10, 0x00];
        bytes.extend_from_slice(cal);
        let sum = bytes.iter().fold(0u8, |sum, byte| sum.wrapping_add(*byte));
        bytes.push(0u8.wrapping_sub(sum));
        let mut wire = hex::encode_upper(bytes).into_bytes();
        wire.extend_from_slice(b"\r\n");
        writer.write_all(&wire).await.unwrap();
    }
    fn mmi_block(start: u8, count: usize, present: &[usize]) -> Vec<u8> {
        let mut states = vec![0u8; count];
        for address in present {
            states[*address - usize::from(start)] = 2;
        }
        let mut wire = cbus_protocol::packet::Packet::StandardStatus {
            application: 0xff,
            block_start: start,
            states,
        }
        .encode_packet()
        .unwrap();
        wire.extend_from_slice(b"\r\n");
        wire
    }

    let path = state_path();
    let (pci, remote) = pci();
    let (remote_read, mut remote_write) = tokio::io::split(remote);
    let mut remote_read = BufReader::new(remote_read);
    let reset = tokio::spawn({
        let pci = pci.clone();
        async move { pci.pci_reset().await }
    });
    for _ in 0..8 {
        pci_line(&mut remote_read).await;
    }
    reset.await.unwrap().unwrap();

    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let mut stale = Unit::blank(5, "");
    stale.unit_type = "KEYGL5".into();
    stale.firmware = "old-identify".into();
    for (field, value) in [
        ("FirmwareVersion", "old-extended"),
        ("Application", "1"),
        ("Application2", "2"),
        ("WidgetGroups", "old-widget-groups"),
    ] {
        stale.fields.insert(field.into(), value.into());
    }
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
        .physical
        .insert(5, stale);
    let mut events = service.events.subscribe();
    let syncing = tokio::spawn({
        let service = service.clone();
        async move {
            service
                .handle(&mut ClientState::default(), "[raw] NET SYNC //HARNESS/254")
                .await
        }
    });

    assert_eq!(pci_line(&mut remote_read).await, b"@1A2001\r");
    remote_write.write_all(b"8220104E\r\n").await.unwrap();

    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\05FF00FAFF"), "{request:?}");
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    for block in [
        mmi_block(0, 88, &[5]),
        mmi_block(88, 88, &[]),
        mmi_block(176, 80, &[]),
    ] {
        remote_write.write_all(&block).await.unwrap();
    }

    for (attribute, value) in [(1, &b"KEYGL5"[..]), (2, &b"5.5.00"[..])] {
        let request = pci_line(&mut remote_read).await;
        assert!(
            request
                .windows(4)
                .any(|window| window == [0x32, 0x31, 0x30, b'0' + attribute]),
            "{request:?}"
        );
        let code = request[request.len() - 2];
        remote_write.write_all(&[code, b'.']).await.unwrap();
        let mut cal = vec![0x80 | (value.len() as u8 + 1), attribute];
        cal.extend_from_slice(value);
        pci_reply(&mut remote_write, 5, &cal).await;
    }

    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\4605002104"), "{request:?}");
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    let known = [
        0x38, 0xff, 0xff, 0xff, 0xff, 0x18, 0xb1, 0x06, 0x16, 0xa2, 0x00, 0x05,
    ];
    let unknown = [
        0x38, 0xff, 0xff, 0xff, 0xff, 0x00, 0x00, 0x00, 0x00, 0xa2, 0x00, 0x05,
    ];
    let replies = match case {
        AmbiguousRawSerialReplies::KnownAndUnknown => [known, unknown],
        AmbiguousRawSerialReplies::RepeatedKnown => [known, known],
    };
    for reply in replies {
        let mut cal = vec![0x8d, 4];
        cal.extend_from_slice(&reply);
        pci_reply(&mut remote_write, 5, &cal).await;
        tokio::time::advance(Duration::from_secs(1)).await;
        tokio::task::yield_now().await;
        assert!(
            !syncing.is_finished(),
            "{case:?}: the collection window closed before all raw replies"
        );
    }
    tokio::time::advance(Duration::from_secs(2)).await;
    tokio::task::yield_now().await;

    let response = syncing.await.unwrap();
    assert_eq!(response.status, 200, "{case:?}: {response:?}");
    assert!(
        tokio::time::timeout(Duration::from_secs(1), pci_line(&mut remote_read))
            .await
            .is_err(),
        "{case:?}: ambiguous raw replies must not trigger OEM metadata traffic"
    );

    let model = service.model.lock().await;
    let snapshot = model.projects["HARNESS"].networks[&254]
        .physical
        .get(&5)
        .expect("address 5 was present in the scripted state-two MMI");
    assert_eq!(
        snapshot.serial, "101136.1558",
        "{case:?}: the established scalar cache representation must remain unchanged"
    );
    assert!(
        snapshot.serial_alternates.is_empty(),
        "{case:?}: repeated or unknown serial replies do not create distinct alternates"
    );
    for field in [
        "FirmwareVersion",
        "Application",
        "Application2",
        "WidgetGroups",
    ] {
        assert!(
            !snapshot.fields.contains_key(field),
            "{case:?}: stale {field} must be removed: {snapshot:?}"
        );
    }
    drop(model);

    for (sequence, field) in [
        ("raw-f", "FirmwareVersion"),
        ("raw-a", "Application"),
        ("raw-a2", "Application2"),
        ("raw-g", "WidgetGroups"),
    ] {
        let get = service
            .handle(
                &mut ClientState::default(),
                &format!("[{sequence}] GET //HARNESS/254/p/5 {field}"),
            )
            .await;
        assert_eq!(get.status, 402, "{case:?}: stale {field}: {get:?}");
    }

    let mut seen = Vec::new();
    while let Ok(event) = events.try_recv() {
        seen.push(event);
    }
    assert!(
        seen.iter().any(|event| event == "#e# net 254 sync ok"),
        "{case:?}: sync-ok event must still be emitted: {seen:?}"
    );
    assert!(
        !seen.iter().any(|event| event.contains("sync duplicate")),
        "{case:?}: the existing distinct-known-serial event representation changed: {seen:?}"
    );

    std::fs::remove_file(path).unwrap();
}

/// Metadata attribution requires one raw known IDENTIFY4 reply. A state-two
/// unit remains ineligible when the quiet window also contains an unknown
/// reply or repeats the same known reply, even though the established cache
/// representation still has one distinct known serial in both cases.
#[tokio::test(start_paused = true)]
async fn physical_net_sync_state_two_rejects_ambiguous_raw_serial_replies() {
    for case in [
        AmbiguousRawSerialReplies::KnownAndUnknown,
        AmbiguousRawSerialReplies::RepeatedKnown,
    ] {
        run_state_two_ambiguous_raw_serial_sync(case).await;
    }
}

#[derive(Clone, Copy)]
enum OptionalEdltFailure {
    ApplicationRecall,
    WidgetGroups,
}

async fn run_partial_edlt_sync_timeout(failure: OptionalEdltFailure) {
    async fn line<R: tokio::io::AsyncBufRead + Unpin>(reader: &mut R) -> Vec<u8> {
        let mut line = Vec::new();
        reader.read_until(b'\r', &mut line).await.unwrap();
        line
    }
    async fn reply<W: tokio::io::AsyncWrite + Unpin>(writer: &mut W, source: u8, cal: &[u8]) {
        let mut bytes = vec![0x86, source, 0x10, 0x00];
        bytes.extend_from_slice(cal);
        let sum = bytes.iter().fold(0u8, |sum, byte| sum.wrapping_add(*byte));
        bytes.push(0u8.wrapping_sub(sum));
        let mut wire = hex::encode_upper(bytes).into_bytes();
        wire.extend_from_slice(b"\r\n");
        writer.write_all(&wire).await.unwrap();
    }
    fn mmi(start: u8, count: usize, present: &[usize]) -> Vec<u8> {
        let mut states = vec![0u8; count];
        for address in present {
            states[*address - usize::from(start)] = 1;
        }
        let mut wire = cbus_protocol::Packet::StandardStatus {
            application: 0xff,
            block_start: start,
            states,
        }
        .encode_packet()
        .unwrap();
        wire.extend_from_slice(b"\r\n");
        wire
    }

    let path = state_path();
    let (pci, remote) = pci();
    let (remote_read, mut remote_write) = tokio::io::split(remote);
    let mut remote_read = BufReader::new(remote_read);
    let reset = tokio::spawn({
        let pci = pci.clone();
        async move { pci.pci_reset().await }
    });
    for _ in 0..8 {
        line(&mut remote_read).await;
    }
    reset.await.unwrap().unwrap();

    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let mut stale = Unit::blank(5, "");
    stale.unit_type = "KEYGL5".into();
    stale.firmware = "old-identify".into();
    for (field, value) in [
        ("FirmwareVersion", "old-extended"),
        ("Application", "1"),
        ("Application2", "2"),
        ("WidgetGroups", "old-widget-groups"),
    ] {
        stale.fields.insert(field.into(), value.into());
    }
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
        .physical
        .insert(5, stale);

    let syncing = tokio::spawn({
        let service = service.clone();
        async move {
            service
                .handle(&mut ClientState::default(), "[p] NET SYNC //HARNESS/254")
                .await
        }
    });

    assert_eq!(line(&mut remote_read).await, b"@1A2001\r");
    remote_write.write_all(b"8220104E\r\n").await.unwrap();
    let request = line(&mut remote_read).await;
    assert!(request.starts_with(b"\\05FF00FAFF"), "{request:?}");
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    for block in [mmi(0, 88, &[5]), mmi(88, 88, &[]), mmi(176, 80, &[])] {
        remote_write.write_all(&block).await.unwrap();
    }

    for (attribute, value) in [(1, &b"KEYGL5"[..]), (2, &b"5.5.00"[..])] {
        let request = line(&mut remote_read).await;
        assert!(
            request
                .windows(4)
                .any(|window| window == [0x32, 0x31, 0x30, b'0' + attribute]),
            "{request:?}"
        );
        let code = request[request.len() - 2];
        remote_write.write_all(&[code, b'.']).await.unwrap();
        let mut cal = vec![0x80 | (value.len() as u8 + 1), attribute];
        cal.extend_from_slice(value);
        reply(&mut remote_write, 5, &cal).await;
    }

    let request = line(&mut remote_read).await;
    assert!(request.starts_with(b"\\4605002104"), "{request:?}");
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    let identity = [
        0x38, 0xff, 0xff, 0xff, 0xff, 0x18, 0xb1, 0x06, 0x16, 0xa2, 0x00, 0x05,
    ];
    let mut cal = vec![0x8d, 4];
    cal.extend_from_slice(&identity);
    reply(&mut remote_write, 5, &cal).await;
    tokio::time::advance(Duration::from_secs(2)).await;
    tokio::task::yield_now().await;

    assert_eq!(line(&mut remote_read).await, b"\\460509001AFB098E\r");
    let firmware = cbus_protocol::Cal::Reply {
        parameter: 0xfb,
        data: b"02.00.00\0".to_vec(),
    }
    .encode();
    reply(&mut remote_write, 5, &firmware).await;
    assert_eq!(line(&mut remote_read).await, b"\\46050900A400411000B7\r");
    reply(&mut remote_write, 5, &[0x32, 0, 0x41]).await;
    assert_eq!(line(&mut remote_read).await, b"\\460509001A01028F\r");

    if matches!(failure, OptionalEdltFailure::WidgetGroups) {
        reply(&mut remote_write, 5, &[0x83, 1, 57, 202]).await;
        assert_eq!(line(&mut remote_read).await, b"\\460509001AFA2C6C\r");
    }
    tokio::time::advance(Duration::from_secs(10)).await;
    tokio::task::yield_now().await;

    let response = syncing.await.unwrap();
    assert_eq!(response.status, 408, "metadata timeout: {response:?}");
    let failed_field = match failure {
        OptionalEdltFailure::ApplicationRecall => "Application/Application2",
        OptionalEdltFailure::WidgetGroups => "WidgetGroups",
    };
    assert!(
        response.final_text.starts_with(&format!(
            "408 Physical metadata synchronization failed at unit 5 {failed_field}: "
        )),
        "the caller must receive the exact failed unit and field: {response:?}"
    );
    assert!(
        response.final_text.contains("timed out")
            && response.final_text.ends_with("PCI generation retired"),
        "the transport cause must remain visible: {response:?}"
    );
    if let Ok(bytes) = tokio::time::timeout(Duration::from_secs(1), line(&mut remote_read)).await {
        assert!(
            bytes.is_empty(),
            "a timed-out optional request replayed or started a later request: {bytes:?}"
        );
    }
    assert!(
        service.model.lock().await.projects["HARNESS"].networks[&254]
            .physical
            .is_empty(),
        "a retired PCI generation must invalidate the complete staged snapshot"
    );
    let capabilities = service
        .handle(&mut ClientState::default(), "[health] CMQTT CAPABILITIES")
        .await;
    let document: serde_json::Value = serde_json::from_str(&capabilities.lines[0]).unwrap();
    assert_eq!(document["pci_connected"], false);
    assert_eq!(
        document["programming_lane_state"], "reconnect-required",
        "operators must be able to distinguish a retired generation"
    );
    std::fs::remove_file(path).unwrap();
}

#[tokio::test(start_paused = true)]
async fn physical_net_sync_reports_metadata_timeout_and_discards_retired_generation() {
    run_partial_edlt_sync_timeout(OptionalEdltFailure::ApplicationRecall).await;
    run_partial_edlt_sync_timeout(OptionalEdltFailure::WidgetGroups).await;
}

#[tokio::test(start_paused = true)]
async fn physical_net_sync_reconnect_during_optional_metadata_does_not_commit_stale_snapshot() {
    async fn line<R: tokio::io::AsyncBufRead + Unpin>(reader: &mut R) -> Vec<u8> {
        let mut line = Vec::new();
        reader.read_until(b'\r', &mut line).await.unwrap();
        line
    }
    async fn reply<W: tokio::io::AsyncWrite + Unpin>(writer: &mut W, source: u8, cal: &[u8]) {
        let mut bytes = vec![0x86, source, 0x10, 0x00];
        bytes.extend_from_slice(cal);
        let sum = bytes.iter().fold(0u8, |sum, byte| sum.wrapping_add(*byte));
        bytes.push(0u8.wrapping_sub(sum));
        let mut wire = hex::encode_upper(bytes).into_bytes();
        wire.extend_from_slice(b"\r\n");
        writer.write_all(&wire).await.unwrap();
    }
    fn mmi(start: u8, count: usize, present: &[usize]) -> Vec<u8> {
        let mut states = vec![0u8; count];
        for address in present {
            states[*address - usize::from(start)] = 1;
        }
        let mut wire = cbus_protocol::Packet::StandardStatus {
            application: 0xff,
            block_start: start,
            states,
        }
        .encode_packet()
        .unwrap();
        wire.extend_from_slice(b"\r\n");
        wire
    }

    let path = state_path();
    let (old_pci, remote) = pci();
    let (remote_read, mut remote_write) = tokio::io::split(remote);
    let mut remote_read = BufReader::new(remote_read);
    let reset = tokio::spawn({
        let old_pci = old_pci.clone();
        async move { old_pci.pci_reset().await }
    });
    for _ in 0..8 {
        line(&mut remote_read).await;
    }
    reset.await.unwrap().unwrap();

    let service = Service::new(&fixture(), None, path.clone(), old_pci, None).unwrap();
    let mut events = service.events.subscribe();
    let syncing = tokio::spawn({
        let service = service.clone();
        async move {
            service
                .handle(&mut ClientState::default(), "[r] NET SYNC //HARNESS/254")
                .await
        }
    });

    assert_eq!(line(&mut remote_read).await, b"@1A2001\r");
    remote_write.write_all(b"8220104E\r\n").await.unwrap();
    let request = line(&mut remote_read).await;
    assert!(request.starts_with(b"\\05FF00FAFF"), "{request:?}");
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    for block in [mmi(0, 88, &[5]), mmi(88, 88, &[]), mmi(176, 80, &[])] {
        remote_write.write_all(&block).await.unwrap();
    }

    for (attribute, value) in [(1, &b"KEYGL5"[..]), (2, &b"5.5.00"[..])] {
        let request = line(&mut remote_read).await;
        assert!(
            request
                .windows(4)
                .any(|window| window == [0x32, 0x31, 0x30, b'0' + attribute]),
            "{request:?}"
        );
        let code = request[request.len() - 2];
        remote_write.write_all(&[code, b'.']).await.unwrap();
        let mut cal = vec![0x80 | (value.len() as u8 + 1), attribute];
        cal.extend_from_slice(value);
        reply(&mut remote_write, 5, &cal).await;
    }

    let request = line(&mut remote_read).await;
    assert!(request.starts_with(b"\\4605002104"), "{request:?}");
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    let identity = [
        0x38, 0xff, 0xff, 0xff, 0xff, 0x18, 0xb1, 0x06, 0x16, 0xa2, 0x00, 0x05,
    ];
    let mut cal = vec![0x8d, 4];
    cal.extend_from_slice(&identity);
    reply(&mut remote_write, 5, &cal).await;
    tokio::time::advance(Duration::from_secs(2)).await;
    tokio::task::yield_now().await;

    // Replace the service PCI while the old generation waits for the first
    // optional metadata response. The old task must never repopulate the
    // cache cleared by set_pci or report sync success.
    assert_eq!(line(&mut remote_read).await, b"\\460509001AFB098E\r");
    let (replacement, _replacement_remote) = pci();
    service.set_pci(replacement).await;
    tokio::time::advance(Duration::from_secs(10)).await;
    tokio::task::yield_now().await;

    let response = syncing.await.unwrap();
    assert_eq!(response.status, 408, "stale sync must fail: {response:?}");
    assert!(
        response.final_text.starts_with(
            "408 Physical metadata synchronization failed at unit 5 FirmwareVersion:"
        ) && response
            .final_text
            .ends_with("invalidated by PCI reconnect"),
        "the original metadata failure and reconnect invalidation must both remain visible: {response:?}"
    );
    let model = service.model.lock().await;
    let network = &model.projects["HARNESS"].networks[&254];
    assert!(network.physical.is_empty(), "stale cache: {network:?}");
    assert_eq!(network.state, NetworkState::Open);
    drop(model);

    let mut seen = Vec::new();
    while let Ok(event) = events.try_recv() {
        seen.push(event);
    }
    assert!(
        !seen.iter().any(|event| event.contains("sync ok")),
        "reconnected stale sync emitted success: {seen:?}"
    );
    std::fs::remove_file(path).unwrap();
}

/// MMI state three is a native error flag. Even one valid IDENTIFY4 reply
/// cannot make source-address-only eDLT metadata attributable to one unit.
#[tokio::test(start_paused = true)]
async fn physical_net_sync_state_three_skips_edlt_metadata() {
    async fn pci_line<R: tokio::io::AsyncBufRead + Unpin>(reader: &mut R) -> Vec<u8> {
        let mut line = Vec::new();
        reader.read_until(b'\r', &mut line).await.unwrap();
        line
    }
    async fn pci_reply<W: tokio::io::AsyncWrite + Unpin>(writer: &mut W, source: u8, cal: &[u8]) {
        let mut bytes = vec![0x86, source, 0x10, 0x00];
        bytes.extend_from_slice(cal);
        let sum = bytes.iter().fold(0u8, |sum, byte| sum.wrapping_add(*byte));
        bytes.push(0u8.wrapping_sub(sum));
        let mut wire = hex::encode_upper(bytes).into_bytes();
        wire.extend_from_slice(b"\r\n");
        writer.write_all(&wire).await.unwrap();
    }
    fn mmi_block(start: u8, count: usize, present: &[usize]) -> Vec<u8> {
        let mut states = vec![0u8; count];
        for address in present {
            states[*address - usize::from(start)] = 3;
        }
        let mut wire = cbus_protocol::packet::Packet::StandardStatus {
            application: 0xff,
            block_start: start,
            states,
        }
        .encode_packet()
        .unwrap();
        wire.extend_from_slice(b"\r\n");
        wire
    }

    let path = state_path();
    let (pci, remote) = pci();
    let (remote_read, mut remote_write) = tokio::io::split(remote);
    let mut remote_read = BufReader::new(remote_read);
    let reset = tokio::spawn({
        let pci = pci.clone();
        async move { pci.pci_reset().await }
    });
    for _ in 0..8 {
        pci_line(&mut remote_read).await;
    }
    reset.await.unwrap().unwrap();

    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let mut events = service.events.subscribe();
    let syncing = tokio::spawn({
        let service = service.clone();
        async move {
            service
                .handle(&mut ClientState::default(), "[1] NET SYNC //HARNESS/254")
                .await
        }
    });

    // Local-interface discovery: the fixture has no PC_PCI/PC_CNI unit.
    assert_eq!(pci_line(&mut remote_read).await, b"@1A2001\r");
    remote_write.write_all(b"8220104E\r\n").await.unwrap();
    tokio::task::yield_now().await;

    // Installation MMI: only address 5 is present.
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\05FF00FAFF"), "{request:?}");
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    remote_write
        .write_all(&mmi_block(0, 88, &[5]))
        .await
        .unwrap();
    remote_write
        .write_all(&mmi_block(88, 88, &[]))
        .await
        .unwrap();
    remote_write
        .write_all(&mmi_block(176, 80, &[]))
        .await
        .unwrap();
    tokio::task::yield_now().await;

    // Unit type + firmware via identify_first (confirm, then first reply).
    let request = pci_line(&mut remote_read).await;
    assert!(
        request.windows(4).any(|window| window == b"2101"),
        "{request:?}"
    );
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    pci_reply(
        &mut remote_write,
        5,
        &[0x87, 0x01, b'K', b'E', b'Y', b'G', b'L', b'5'],
    )
    .await;
    tokio::task::yield_now().await;
    let request = pci_line(&mut remote_read).await;
    assert!(
        request.windows(4).any(|window| window == b"2102"),
        "{request:?}"
    );
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    pci_reply(
        &mut remote_write,
        5,
        &[0x87, 0x02, b'5', b'.', b'5', b'.', b'0', b'0'],
    )
    .await;
    tokio::task::yield_now().await;

    // Serial probe returns a SINGLE valid IDENTIFY4 reply.
    let serial = [
        0x38, 0xff, 0xff, 0xff, 0xff, 0x18, 0xb1, 0x06, 0x16, 0xa2, 0x00, 0x05,
    ];
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\4605002104"), "{request:?}");
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    let mut cal = vec![0x8d, 4];
    cal.extend_from_slice(&serial);
    pci_reply(&mut remote_write, 5, &cal).await;
    tokio::time::advance(Duration::from_secs(2)).await;
    tokio::task::yield_now().await;

    let response = syncing.await.unwrap();
    assert_eq!(response.status, 200, "state-three SYNC: {response:?}");

    let model = service.model.lock().await;
    let snapshot = model.projects["HARNESS"].networks[&254]
        .physical
        .get(&5)
        .expect("address 5 was present in the scripted MMI");
    assert_eq!(snapshot.serial, "101136.1558", "{snapshot:?}");
    assert!(
        snapshot.serial_alternates.is_empty(),
        "single serial stores empty alternates: {snapshot:?}"
    );
    assert_eq!(
        snapshot.unit_type, "KEYGL5",
        "fresh physical identity is retained"
    );
    for field in [
        "FirmwareVersion",
        "Application",
        "Application2",
        "WidgetGroups",
    ] {
        assert!(
            !snapshot.fields.contains_key(field),
            "state-three {field} must be unavailable: {snapshot:?}"
        );
    }
    drop(model);

    assert!(
        tokio::time::timeout(Duration::from_secs(1), pci_line(&mut remote_read))
            .await
            .is_err(),
        "MMI state three must not receive any source-only eDLT metadata request"
    );

    for (sequence, field) in [
        ("s3f", "FirmwareVersion"),
        ("s3a", "Application"),
        ("s3a2", "Application2"),
        ("s3g", "WidgetGroups"),
    ] {
        let get = service
            .handle(
                &mut ClientState::default(),
                &format!("[{sequence}] GET //HARNESS/254/p/5 {field}"),
            )
            .await;
        assert_eq!(get.status, 402, "state-three {field}: {get:?}");
    }

    let mut seen = Vec::new();
    while let Ok(event) = events.try_recv() {
        seen.push(event);
    }
    assert!(
        seen.iter().any(|event| event == "#e# net 254 sync ok"),
        "sync-ok event must still be emitted: {seen:?}"
    );
    assert!(
        !seen.iter().any(|event| event.contains("sync duplicate")),
        "single serial must not emit a duplicate event: {seen:?}"
    );

    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn physical_syncnew_rejects_an_already_modeled_target_without_bus_io() {
    let path = state_path();
    let (pci, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let response = service
        .handle(
            &mut ClientState::default(),
            "[1] NET SYNCNEW //HARNESS/254 5",
        )
        .await;
    assert_eq!(response.status, 408);
    assert_eq!(
        response.final_text,
        "408 Operation failed: Unit already in model"
    );
    assert!(
        tokio::time::timeout(Duration::from_millis(25), remote.read_u8())
            .await
            .is_err(),
        "an already modeled target must fail before physical I/O"
    );
    std::fs::remove_file(path).unwrap();
}

#[tokio::test(start_paused = true)]
async fn project_identify_uses_shared_interface_and_native_parameter_35() {
    async fn line<R: tokio::io::AsyncBufRead + Unpin>(reader: &mut R) -> Vec<u8> {
        let mut line = Vec::new();
        reader.read_until(b'\r', &mut line).await.unwrap();
        line
    }
    async fn reply<W: tokio::io::AsyncWrite + Unpin>(writer: &mut W, source: u8, cal: &[u8]) {
        let mut bytes = vec![0x86, source, 0x10, 0x00];
        bytes.extend_from_slice(cal);
        let sum = bytes.iter().fold(0u8, |sum, byte| sum.wrapping_add(*byte));
        bytes.push(0u8.wrapping_sub(sum));
        let mut wire = hex::encode_upper(bytes).into_bytes();
        wire.extend_from_slice(b"\r\n");
        writer.write_all(&wire).await.unwrap();
    }
    fn mmi(start: u8, count: usize) -> Vec<u8> {
        let mut states = vec![0; count];
        if (usize::from(start)..usize::from(start) + count).contains(&4) {
            states[4 - usize::from(start)] = 1;
        }
        let mut wire = Packet::StandardStatus {
            application: 0xff,
            block_start: start,
            states,
        }
        .encode_packet()
        .unwrap();
        wire.extend_from_slice(b"\r\n");
        wire
    }

    let path = state_path();
    let (pci, remote) = pci();
    let (remote_read, mut remote_write) = tokio::io::split(remote);
    let mut remote_read = BufReader::new(remote_read);
    let reset = tokio::spawn({
        let pci = pci.clone();
        async move { pci.pci_reset().await }
    });
    for _ in 0..8 {
        let _ = line(&mut remote_read).await;
    }
    reset.await.unwrap().unwrap();
    let service = Service::new(&topology_fixture(), None, path.clone(), pci, None).unwrap();
    let identifying = tokio::spawn({
        let service = service.clone();
        async move {
            service
                .handle(
                    &mut ClientState::default(),
                    "[pi] NET PROJECT_IDENTIFY cni@127.0.0.1:10001",
                )
                .await
        }
    });

    let request = line(&mut remote_read).await;
    assert!(request.starts_with(b"\\05FF00FAFF00"), "{request:?}");
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    for (start, count) in [(0, 88), (88, 88), (176, 80)] {
        remote_write.write_all(&mmi(start, count)).await.unwrap();
    }
    tokio::task::yield_now().await;

    for (attribute, payload) in [(1, b"RELAY4  ".as_slice()), (2, b"1.0.00  ".as_slice())] {
        let request = line(&mut remote_read).await;
        assert!(
            request
                .windows(4)
                .any(|window| window == format!("21{attribute:02X}").as_bytes()),
            "{request:?}"
        );
        let code = request[request.len() - 2];
        remote_write.write_all(&[code, b'.']).await.unwrap();
        let mut cal = vec![0x81 + payload.len() as u8, attribute];
        cal.extend_from_slice(payload);
        reply(&mut remote_write, 4, &cal).await;
        tokio::task::yield_now().await;
    }

    let request = line(&mut remote_read).await;
    assert!(request.starts_with(b"\\4604001A2102"), "{request:?}");
    reply(&mut remote_write, 4, &[0x83, 33, 0, 0]).await;

    let request = line(&mut remote_read).await;
    assert!(request.starts_with(b"\\4604001A2306"), "{request:?}");
    let mut cal = vec![0x87, 35];
    cal.extend_from_slice(&[0xce, 0x4c, 0xb3, 0x79, 0xe7, 0x9e]);
    reply(&mut remote_write, 4, &cal).await;

    let response = identifying.await.unwrap();
    assert_eq!(response.status, 305, "{response:?}");
    assert_eq!(response.final_text, "305 Project=TEST UnitCount=1");
    assert!(
        service.model.lock().await.projects["TOPO"].networks[&254]
            .physical
            .is_empty(),
        "PROJECT_IDENTIFY must not populate the project cache"
    );
    std::fs::remove_file(path).unwrap();
}

#[tokio::test(start_paused = true)]
async fn topology_explore_reuses_shared_interface_and_reports_physical_identity() {
    async fn line<R: tokio::io::AsyncBufRead + Unpin>(reader: &mut R) -> Vec<u8> {
        let mut line = Vec::new();
        reader.read_until(b'\r', &mut line).await.unwrap();
        line
    }
    async fn reply<W: tokio::io::AsyncWrite + Unpin>(writer: &mut W, source: u8, cal: &[u8]) {
        let mut bytes = vec![0x86, source, 0x10, 0x00];
        bytes.extend_from_slice(cal);
        let sum = bytes.iter().fold(0u8, |sum, byte| sum.wrapping_add(*byte));
        bytes.push(0u8.wrapping_sub(sum));
        let mut wire = hex::encode_upper(bytes).into_bytes();
        wire.extend_from_slice(b"\r\n");
        writer.write_all(&wire).await.unwrap();
    }
    fn mmi(start: u8, count: usize) -> Vec<u8> {
        let mut states = vec![0; count];
        if (usize::from(start)..usize::from(start) + count).contains(&4) {
            states[4 - usize::from(start)] = 1;
        }
        let mut wire = Packet::StandardStatus {
            application: 0xff,
            block_start: start,
            states,
        }
        .encode_packet()
        .unwrap();
        wire.extend_from_slice(b"\r\n");
        wire
    }

    let path = state_path();
    let (pci, remote) = pci();
    let (remote_read, mut remote_write) = tokio::io::split(remote);
    let mut remote_read = BufReader::new(remote_read);
    let reset = tokio::spawn({
        let pci = pci.clone();
        async move { pci.pci_reset().await }
    });
    for _ in 0..8 {
        let _ = line(&mut remote_read).await;
    }
    reset.await.unwrap().unwrap();
    let service = Service::new(&topology_fixture(), None, path.clone(), pci, None).unwrap();
    service
        .set_port_endpoint(Endpoint::parse_tcp("127.0.0.1:10001").unwrap())
        .unwrap();
    let exploring = tokio::spawn({
        let service = service.clone();
        async move {
            service
                .handle(
                    &mut ClientState::default(),
                    "[topo] TOPOLOGY EXPLORE socket@127.0.0.1:10001",
                )
                .await
        }
    });

    let request = line(&mut remote_read).await;
    assert!(request.starts_with(b"\\05FF00FAFF00"), "{request:?}");
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    for (start, count) in [(0, 88), (88, 88), (176, 80)] {
        remote_write.write_all(&mmi(start, count)).await.unwrap();
    }
    tokio::task::yield_now().await;

    for (attribute, payload) in [(1, b"RELAY4  ".as_slice()), (2, b"1.0.00  ".as_slice())] {
        let request = line(&mut remote_read).await;
        assert!(
            request
                .windows(4)
                .any(|window| window == format!("21{attribute:02X}").as_bytes()),
            "{request:?}"
        );
        let code = request[request.len() - 2];
        remote_write.write_all(&[code, b'.']).await.unwrap();
        let mut cal = vec![0x81 + payload.len() as u8, attribute];
        cal.extend_from_slice(payload);
        reply(&mut remote_write, 4, &cal).await;
        tokio::task::yield_now().await;
    }

    let request = line(&mut remote_read).await;
    assert!(request.starts_with(b"\\4604001A2102"), "{request:?}");
    reply(&mut remote_write, 4, &[0x83, 33, 0, 0]).await;

    let request = line(&mut remote_read).await;
    assert!(request.starts_with(b"\\4604001A2306"), "{request:?}");
    let mut cal = vec![0x87, 35];
    cal.extend_from_slice(&[0xce, 0x4c, 0xb3, 0x79, 0xe7, 0x9e]);
    reply(&mut remote_write, 4, &cal).await;

    let response = exploring.await.unwrap();
    assert_eq!(response.status, 324, "{response:?}");
    assert_eq!(
        response.lines,
        [
            "323-Network Found NET0 127.0.0.1:10001",
            "321-Network Serial NET0 TEST"
        ]
    );
    assert_eq!(response.final_text, "324 Bridges Found NET0 1");
    assert!(
        service.model.lock().await.projects["TOPO"].networks[&254]
            .physical
            .is_empty(),
        "topology exploration must not mutate the runtime unit cache"
    );
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn project_identify_pins_native_grammar_and_refuses_a_second_interface() {
    let path = state_path();
    let (pci, mut remote) = pci();
    let service = Service::new(&topology_fixture(), None, path.clone(), pci, None).unwrap();
    let mut client = ClientState::default();
    let missing = service
        .handle(&mut client, "[1] NET PROJECT_IDENTIFY")
        .await;
    assert_eq!(
        missing.final_text,
        "400 Syntax Error: Missing parameter : <interface>"
    );
    let extra = service
        .handle(
            &mut client,
            "[2] NET PROJECT_IDENTIFY cni@127.0.0.1:10001 EXTRA",
        )
        .await;
    assert_eq!(extra.final_text, "400 Syntax Error: Too many parameters");
    let malformed = service
        .handle(&mut client, "[3] NET PROJECT_IDENTIFY cni@")
        .await;
    assert_eq!(
        malformed.lines,
        ["470-Bad interface specification for NET0 cni@"]
    );
    assert_eq!(
        malformed.final_text,
        "408 Operation failed: Can not open network (bad interface specification"
    );
    let other = service
        .handle(&mut client, "[4] NET PROJECT_IDENTIFY cni@127.0.0.1:10002")
        .await;
    assert_eq!(other.status, 502);
    assert!(
        tokio::time::timeout(Duration::from_millis(25), remote.read_u8())
            .await
            .is_err(),
        "a non-shared interface must fail before physical I/O"
    );
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn project_identify_reconnect_generation_invalidates_the_result() {
    async fn line<R: tokio::io::AsyncBufRead + Unpin>(reader: &mut R) -> Vec<u8> {
        let mut line = Vec::new();
        reader.read_until(b'\r', &mut line).await.unwrap();
        line
    }
    fn empty_mmi(start: u8, count: usize) -> Vec<u8> {
        let mut wire = Packet::StandardStatus {
            application: 0xff,
            block_start: start,
            states: vec![0; count],
        }
        .encode_packet()
        .unwrap();
        wire.extend_from_slice(b"\r\n");
        wire
    }

    let path = state_path();
    let (pci, remote) = pci();
    let (remote_read, mut remote_write) = tokio::io::split(remote);
    let mut remote_read = BufReader::new(remote_read);
    let reset = tokio::spawn({
        let pci = pci.clone();
        async move { pci.pci_reset().await }
    });
    for _ in 0..8 {
        let _ = line(&mut remote_read).await;
    }
    reset.await.unwrap().unwrap();
    let service = Service::new(&topology_fixture(), None, path.clone(), pci, None).unwrap();
    let identifying = tokio::spawn({
        let service = service.clone();
        async move {
            service
                .handle(
                    &mut ClientState::default(),
                    "[generation] NET PROJECT_IDENTIFY cni@127.0.0.1:10001",
                )
                .await
        }
    });
    let request = line(&mut remote_read).await;
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();

    let gate = service.pci_generation_gate.lock().await;
    for (start, count) in [(0, 88), (88, 88), (176, 80)] {
        remote_write
            .write_all(&empty_mmi(start, count))
            .await
            .unwrap();
    }
    tokio::task::yield_now().await;
    service.pci_generation.fetch_add(1, Ordering::AcqRel);
    drop(gate);

    let response = identifying.await.unwrap();
    assert_eq!(response.status, 408, "{response:?}");
    assert_eq!(
        response.final_text,
        "408 Operation failed: PCI reconnected during project discovery"
    );
    std::fs::remove_file(path).unwrap();
}

#[tokio::test(start_paused = true)]
async fn physical_syncnew_target_runs_native_discovery_and_stores_new_identity() {
    async fn pci_line<R: tokio::io::AsyncBufRead + Unpin>(reader: &mut R) -> Vec<u8> {
        let mut line = Vec::new();
        reader.read_until(b'\r', &mut line).await.unwrap();
        line
    }
    async fn pci_reply<W: tokio::io::AsyncWrite + Unpin>(writer: &mut W, source: u8, cal: &[u8]) {
        let mut bytes = vec![0x86, source, 0x10, 0x00];
        bytes.extend_from_slice(cal);
        let sum = bytes.iter().fold(0u8, |sum, byte| sum.wrapping_add(*byte));
        bytes.push(0u8.wrapping_sub(sum));
        let mut wire = hex::encode_upper(bytes).into_bytes();
        wire.extend_from_slice(b"\r\n");
        writer.write_all(&wire).await.unwrap();
    }
    fn mmi_block(start: u8, count: usize, address: usize, state: u8) -> Vec<u8> {
        let mut states = vec![0u8; count];
        if (usize::from(start)..usize::from(start) + count).contains(&address) {
            states[address - usize::from(start)] = state;
        }
        let mut wire = cbus_protocol::packet::Packet::StandardStatus {
            application: 0xff,
            block_start: start,
            states,
        }
        .encode_packet()
        .unwrap();
        wire.extend_from_slice(b"\r\n");
        wire
    }

    let path = state_path();
    let (pci, remote) = pci();
    let (remote_read, mut remote_write) = tokio::io::split(remote);
    let mut remote_read = BufReader::new(remote_read);
    let reset = tokio::spawn({
        let pci = pci.clone();
        async move { pci.pci_reset().await }
    });
    for _ in 0..8 {
        pci_line(&mut remote_read).await;
    }
    reset.await.unwrap().unwrap();

    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let syncing = tokio::spawn({
        let service = service.clone();
        async move {
            service
                .handle(
                    &mut ClientState::default(),
                    "[41] NET SYNCNEW //HARNESS/254 6",
                )
                .await
        }
    });

    assert_eq!(pci_line(&mut remote_read).await, b"@1A2001\r");
    remote_write.write_all(b"8220104E\r\n").await.unwrap();
    tokio::task::yield_now().await;

    for _ in 0..5 {
        let request = pci_line(&mut remote_read).await;
        assert!(request.starts_with(b"\\05FF00FAFF"), "{request:?}");
        let code = request[request.len() - 2];
        remote_write.write_all(&[code, b'.']).await.unwrap();
        remote_write
            .write_all(&mmi_block(0, 88, 6, 1))
            .await
            .unwrap();
        remote_write
            .write_all(&mmi_block(88, 88, 6, 1))
            .await
            .unwrap();
        remote_write
            .write_all(&mmi_block(176, 80, 6, 1))
            .await
            .unwrap();
        tokio::task::yield_now().await;
    }

    for (attempt, expected) in [
        (0u8, b"\\460600118023".as_slice()),
        (1u8, b"\\460600118122".as_slice()),
        (2u8, b"\\460600118221".as_slice()),
    ] {
        let request = pci_line(&mut remote_read).await;
        assert_eq!(&request[..request.len() - 2], expected);
        let code = request[request.len() - 2];
        remote_write.write_all(&[code, b'.']).await.unwrap();
        pci_reply(&mut remote_write, 6, &[0x82, 0x80 + attempt, 0x33]).await;
        tokio::task::yield_now().await;
        tokio::time::advance(Duration::from_secs(2)).await;
        tokio::task::yield_now().await;
    }

    for (attribute, text) in [(1u8, b"KEYE1".as_slice()), (2u8, b"1.2.30".as_slice())] {
        let request = pci_line(&mut remote_read).await;
        assert!(
            request
                .windows(4)
                .any(|window| { window == format!("21{attribute:02X}").as_bytes() }),
            "{request:?}"
        );
        let code = request[request.len() - 2];
        remote_write.write_all(&[code, b'.']).await.unwrap();
        let mut cal = vec![0x81 + text.len() as u8, attribute];
        cal.extend_from_slice(text);
        pci_reply(&mut remote_write, 6, &cal).await;
        tokio::task::yield_now().await;
    }

    let serial = [
        0x38, 0xff, 0xff, 0xff, 0xff, 0x18, 0xb1, 0x06, 0x16, 0xa2, 0x00, 0x05,
    ];
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\4606002104"), "{request:?}");
    let code = request[request.len() - 2];
    let mut cal = vec![0x8d, 4];
    cal.extend_from_slice(&serial);
    pci_reply(&mut remote_write, 6, &cal).await;
    tokio::task::yield_now().await;
    remote_write.write_all(&[code, b'.']).await.unwrap();
    tokio::task::yield_now().await;
    tokio::time::advance(Duration::from_secs(2)).await;
    tokio::task::yield_now().await;

    let response = syncing.await.unwrap();
    assert_eq!(response.status, 303, "{response:?}");
    assert_eq!(response.lines.len(), 11, "{response:?}");
    assert_eq!(response.lines[0], "120-completed MMI 1 of 5.");
    assert_eq!(response.lines[4], "120-completed MMI 5 of 5.");
    assert_eq!(response.lines[5], "120-unit found");
    assert_eq!(response.lines[6], "120-duplicate test 1/3");
    assert_eq!(response.lines[10], "120-identifying unit");
    assert_eq!(
        response.final_text,
        "303 New Unit Found: address=6 type=KEYE1 version=1.2.30 serial=101136.1558"
    );
    let wire = format_response(&response);
    assert!(wire.contains("[41] 120-completed MMI 1 of 5.\n"));
    assert!(wire.ends_with(
        "[41] 303 New Unit Found: address=6 type=KEYE1 version=1.2.30 serial=101136.1558\n"
    ));

    let model = service.model.lock().await;
    let network = &model.projects["HARNESS"].networks[&254];
    assert!(!network.units.contains_key(&6));
    assert_eq!(network.physical[&6].unit_type, "KEYE1");
    assert_eq!(network.physical[&6].firmware, "1.2.30");
    assert_eq!(network.physical[&6].serial, "101136.1558");
    drop(model);
    std::fs::remove_file(path).unwrap();
}

#[tokio::test(start_paused = true)]
async fn physical_syncnew_all_reports_mmi_duplicate_and_drops_live_identity() {
    async fn pci_line<R: tokio::io::AsyncBufRead + Unpin>(reader: &mut R) -> Vec<u8> {
        let mut line = Vec::new();
        reader.read_until(b'\r', &mut line).await.unwrap();
        line
    }
    fn mmi_block(start: u8, count: usize, address: usize, state: u8) -> Vec<u8> {
        let mut states = vec![0u8; count];
        if (usize::from(start)..usize::from(start) + count).contains(&address) {
            states[address - usize::from(start)] = state;
        }
        let mut wire = cbus_protocol::packet::Packet::StandardStatus {
            application: 0xff,
            block_start: start,
            states,
        }
        .encode_packet()
        .unwrap();
        wire.extend_from_slice(b"\r\n");
        wire
    }

    let path = state_path();
    let (pci, remote) = pci();
    let (remote_read, mut remote_write) = tokio::io::split(remote);
    let mut remote_read = BufReader::new(remote_read);
    let reset = tokio::spawn({
        let pci = pci.clone();
        async move { pci.pci_reset().await }
    });
    for _ in 0..8 {
        pci_line(&mut remote_read).await;
    }
    reset.await.unwrap().unwrap();

    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    {
        let mut model = service.model.lock().await;
        model
            .projects
            .get_mut("HARNESS")
            .unwrap()
            .networks
            .get_mut(&254)
            .unwrap()
            .physical
            .insert(7, Unit::blank(7, "101.7"));
    }
    let syncing = tokio::spawn({
        let service = service.clone();
        async move {
            service
                .handle(
                    &mut ClientState::default(),
                    "[42] NET SYNCNEW //HARNESS/254",
                )
                .await
        }
    });
    assert_eq!(pci_line(&mut remote_read).await, b"@1A2001\r");
    remote_write.write_all(b"8220104E\r\n").await.unwrap();
    tokio::task::yield_now().await;
    for _ in 0..5 {
        let request = pci_line(&mut remote_read).await;
        let code = request[request.len() - 2];
        remote_write.write_all(&[code, b'.']).await.unwrap();
        remote_write
            .write_all(&mmi_block(0, 88, 7, 3))
            .await
            .unwrap();
        remote_write
            .write_all(&mmi_block(88, 88, 7, 3))
            .await
            .unwrap();
        remote_write
            .write_all(&mmi_block(176, 80, 7, 3))
            .await
            .unwrap();
        tokio::task::yield_now().await;
    }
    let response = syncing.await.unwrap();
    assert_eq!(response.status, 303, "{response:?}");
    assert_eq!(response.final_text, "303 Duplicate Units Found: address=7");
    assert!(
        !service.model.lock().await.projects["HARNESS"].networks[&254]
            .physical
            .contains_key(&7)
    );
    std::fs::remove_file(path).unwrap();
}

#[tokio::test(start_paused = true)]
async fn physical_project_identify_verifies_readback_and_reconnect_invalidates_cache_commit() {
    async fn pci_line<R: tokio::io::AsyncBufRead + Unpin>(reader: &mut R) -> Vec<u8> {
        let mut line = Vec::new();
        reader.read_until(b'\r', &mut line).await.unwrap();
        line
    }
    async fn pci_reply<W: tokio::io::AsyncWrite + Unpin>(writer: &mut W, source: u8, cal: &[u8]) {
        let mut bytes = vec![0x86, source, 0x10, 0x00];
        bytes.extend_from_slice(cal);
        let sum = bytes.iter().fold(0u8, |sum, byte| sum.wrapping_add(*byte));
        bytes.push(0u8.wrapping_sub(sum));
        let mut wire = hex::encode_upper(bytes).into_bytes();
        wire.extend_from_slice(b"\r\n");
        writer.write_all(&wire).await.unwrap();
    }
    fn mmi_block(start: u8, count: usize, addresses: &[(usize, u8)]) -> Vec<u8> {
        let mut states = vec![0u8; count];
        for &(address, state) in addresses {
            if (usize::from(start)..usize::from(start) + count).contains(&address) {
                states[address - usize::from(start)] = state;
            }
        }
        let mut wire = cbus_protocol::packet::Packet::StandardStatus {
            application: 0xff,
            block_start: start,
            states,
        }
        .encode_packet()
        .unwrap();
        wire.extend_from_slice(b"\r\n");
        wire
    }

    let path = state_path();
    let (original_pci, remote) = pci();
    let (remote_read, mut remote_write) = tokio::io::split(remote);
    let mut remote_read = BufReader::new(remote_read);
    let reset = tokio::spawn({
        let pci = original_pci.clone();
        async move { pci.pci_reset().await }
    });
    for _ in 0..8 {
        pci_line(&mut remote_read).await;
    }
    reset.await.unwrap().unwrap();

    let service = Service::new(&fixture(), None, path.clone(), original_pci, None).unwrap();
    let mut events = service.events.subscribe();
    let setting = tokio::spawn({
        let service = service.clone();
        async move {
            service
                .handle(
                    &mut ClientState::default(),
                    "[43] NET SET_PROJECT_IDENTIFY //HARNESS/254 \"?\\ ?\"",
                )
                .await
        }
    });

    // Establish the local PCI address before source-correlating IDENTIFY.
    assert_eq!(pci_line(&mut remote_read).await, b"@1A2001\r");
    remote_write.write_all(b"8220104E\r\n").await.unwrap();
    tokio::task::yield_now().await;

    // One complete, positively confirmed MMI identifies two unambiguous
    // candidates. Address 5 returns an unusable identity, so selection must
    // continue to address 6 before any STORE.
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\05FF00FAFF"), "{request:?}");
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    for block in [
        mmi_block(0, 88, &[(5, 1), (6, 2)]),
        mmi_block(88, 88, &[(5, 1), (6, 2)]),
        mmi_block(176, 80, &[(5, 1), (6, 2)]),
    ] {
        remote_write.write_all(&block).await.unwrap();
    }
    tokio::task::yield_now().await;

    let identify = pci_line(&mut remote_read).await;
    assert!(identify.starts_with(b"\\4605002101"), "{identify:?}");
    let code = identify[identify.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    pci_reply(&mut remote_write, 5, &[0x82, 1, b' ']).await;
    tokio::task::yield_now().await;

    let identify = pci_line(&mut remote_read).await;
    assert!(identify.starts_with(b"\\4606002101"), "{identify:?}");
    let code = identify[identify.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    pci_reply(
        &mut remote_write,
        6,
        &[0x86, 1, b'K', b'E', b'Y', b'E', b'1'],
    )
    .await;
    tokio::task::yield_now().await;

    // State two is a non-error present state on real direct networks. It is
    // not sufficient evidence of a unique physical unit, so the service
    // completes an IDENTIFY4 quiet window and admits the STORE only when
    // exactly one valid known serial replied.
    let identify = pci_line(&mut remote_read).await;
    assert!(identify.starts_with(b"\\4606002104"), "{identify:?}");
    let code = identify[identify.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    pci_reply(
        &mut remote_write,
        6,
        &[
            0x8d, 4, 0x38, 0xff, 0xff, 0xff, 0xff, 0x18, 0xb1, 0x06, 0x16, 0xa2, 0x00, 0x05,
        ],
    )
    .await;
    tokio::time::advance(Duration::from_secs(2)).await;
    tokio::task::yield_now().await;

    // Native parameter 35 canonicalizes both '?' and space to six-bit value
    // 30. The service accepts success only after direct RECALL returns the
    // same bytes, and its cache must reflect those verified bytes rather than
    // the non-canonical input spelling.
    assert_eq!(
        pci_line(&mut remote_read).await,
        b"\\460600A8234679E79E79E79EA7\r"
    );
    pci_reply(&mut remote_write, 6, &[0x32, 0x23, 0x46]).await;
    assert_eq!(pci_line(&mut remote_read).await, b"\\4606001A230671\r");
    pci_reply(
        &mut remote_write,
        6,
        &[0x87, 0x23, 0x79, 0xe7, 0x9e, 0x79, 0xe7, 0x9e],
    )
    .await;

    let response = setting.await.unwrap();
    assert_eq!(response.status, 200, "{response:?}");
    assert_eq!(response.final_text, "200 OK.");
    let model = service.model.lock().await;
    let network = &model.projects["HARNESS"].networks[&254];
    assert!(
        !network.units.contains_key(&6),
        "the commissioning write must not invent a database unit"
    );
    assert_eq!(network.physical[&6].unit_type, "KEYE1");
    assert_eq!(network.physical[&6].fields["ProjectName"], "        ");
    drop(model);
    let property = service
        .handle(
            &mut ClientState::default(),
            "[46] GET //HARNESS/254/p/6 ProjectName",
        )
        .await;
    assert_eq!(property.status, 300, "{property:?}");
    assert_eq!(
        property.final_text,
        "300 //HARNESS/254/p/6: ProjectName=        "
    );
    assert!(
        events.try_recv().is_err(),
        "native project-identify does not emit a synthetic event"
    );

    // Repeat the verified physical transaction, but start a reconnect after
    // the final RECALL is on the wire and before its result can update the
    // volatile cache. The replacement must clear the old snapshot and the
    // completed request must return 408 instead of repopulating it.
    let reconnecting_write = tokio::spawn({
        let service = service.clone();
        async move {
            service
                .handle(
                    &mut ClientState::default(),
                    "[47] NET SET_PROJECT_IDENTIFY //HARNESS/254 \"?\\ ?\"",
                )
                .await
        }
    });

    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\05FF00FAFF"), "{request:?}");
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    for block in [
        mmi_block(0, 88, &[(5, 1), (6, 2)]),
        mmi_block(88, 88, &[(5, 1), (6, 2)]),
        mmi_block(176, 80, &[(5, 1), (6, 2)]),
    ] {
        remote_write.write_all(&block).await.unwrap();
    }
    tokio::task::yield_now().await;

    let identify = pci_line(&mut remote_read).await;
    assert!(identify.starts_with(b"\\4605002101"), "{identify:?}");
    let code = identify[identify.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    pci_reply(&mut remote_write, 5, &[0x82, 1, b' ']).await;
    tokio::task::yield_now().await;

    let identify = pci_line(&mut remote_read).await;
    assert!(identify.starts_with(b"\\4606002101"), "{identify:?}");
    let code = identify[identify.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    pci_reply(
        &mut remote_write,
        6,
        &[0x86, 1, b'K', b'E', b'Y', b'E', b'1'],
    )
    .await;
    tokio::task::yield_now().await;

    let identify = pci_line(&mut remote_read).await;
    assert!(identify.starts_with(b"\\4606002104"), "{identify:?}");
    let code = identify[identify.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    pci_reply(
        &mut remote_write,
        6,
        &[
            0x8d, 4, 0x38, 0xff, 0xff, 0xff, 0xff, 0x18, 0xb1, 0x06, 0x16, 0xa2, 0x00, 0x05,
        ],
    )
    .await;
    tokio::time::advance(Duration::from_secs(2)).await;
    tokio::task::yield_now().await;

    assert_eq!(
        pci_line(&mut remote_read).await,
        b"\\460600A8234679E79E79E79EA7\r"
    );
    pci_reply(&mut remote_write, 6, &[0x32, 0x23, 0x46]).await;
    assert_eq!(pci_line(&mut remote_read).await, b"\\4606001A230671\r");

    let model_guard = service.model.lock().await;
    let (replacement, _replacement_remote) = pci();
    let replacing = tokio::spawn({
        let service = service.clone();
        async move { service.set_pci(replacement).await }
    });
    for _ in 0..100 {
        if service.pci_generation.load(Ordering::Acquire) == 1 {
            break;
        }
        tokio::task::yield_now().await;
    }
    assert_eq!(service.pci_generation.load(Ordering::Acquire), 1);
    pci_reply(
        &mut remote_write,
        6,
        &[0x87, 0x23, 0x79, 0xe7, 0x9e, 0x79, 0xe7, 0x9e],
    )
    .await;
    tokio::task::yield_now().await;
    drop(model_guard);
    replacing.await.unwrap();

    let response = reconnecting_write.await.unwrap();
    assert_eq!(response.status, 408, "{response:?}");
    assert_eq!(
        response.final_text,
        "408 Operation failed: PCI reconnected during project identity update"
    );
    assert!(
        service.model.lock().await.projects["HARNESS"].networks[&254]
            .physical
            .is_empty(),
        "the completed old-generation readback must not repopulate the replacement cache"
    );
    std::fs::remove_file(path).unwrap();
}

#[tokio::test(start_paused = true)]
async fn bridged_project_identity_store_is_route_correlated_and_updates_only_target_cache() {
    let path = state_path();
    let (pci_client, remote) = pci();
    let (remote_read, mut remote_write) = tokio::io::split(remote);
    let mut remote_read = BufReader::new(remote_read);
    let reset = tokio::spawn({
        let pci = pci_client.clone();
        async move { pci.pci_reset().await }
    });
    for _ in 0..8 {
        database_pci_line(&mut remote_read).await;
    }
    reset.await.unwrap().unwrap();

    let service = Service::new(&topology_fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut events = service.events.subscribe();
    let setting = tokio::spawn({
        let service = service.clone();
        async move {
            service
                .handle(
                    &mut ClientState::default(),
                    "[rpi] NET SET_PROJECT_IDENTIFY //TOPO/253 TEST",
                )
                .await
        }
    });

    let request = database_pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\03FD09FFFAFF00FF"), "{request:?}");
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    for (start, count) in [(0, 88), (88, 88), (176, 80)] {
        remote_write
            .write_all(&routed_mmi_block(&[253], start, count, &[(4, 1)]))
            .await
            .unwrap();
    }

    let request = database_pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\46FD09042101"), "{request:?}");
    let code = request[request.len() - 2];
    database_pci_reply(&mut remote_write, 4, &[0x86, 1, b'B', b'A', b'D']).await;
    routed_pci_reply(&mut remote_write, &[252], 4, &[0x86, 1, b'B', b'A', b'D']).await;
    routed_pci_reply(
        &mut remote_write,
        &[253],
        4,
        &[0x86, 1, b'K', b'E', b'Y', b'E', b'1'],
    )
    .await;
    remote_write.write_all(&[code, b'.']).await.unwrap();

    let request = database_pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\46FD09042104"), "{request:?}");
    let code = request[request.len() - 2];
    let serial = [
        0x8d, 4, 0x38, 0xff, 0xff, 0xff, 0xff, 0x18, 0xb1, 0x06, 0x16, 0xa2, 0x00, 0x05,
    ];
    database_pci_reply(&mut remote_write, 4, &serial).await;
    routed_pci_reply(&mut remote_write, &[252], 4, &serial).await;
    routed_pci_reply(&mut remote_write, &[253], 4, &serial).await;
    remote_write.write_all(&[code, b'.']).await.unwrap();
    tokio::time::advance(Duration::from_secs(2)).await;
    tokio::task::yield_now().await;

    assert_eq!(
        database_pci_line(&mut remote_read).await,
        b"\\46FD0904A82346CE4CB379E79ED4\r"
    );
    database_pci_reply(&mut remote_write, 4, &[0x32, 0x23, 0x46]).await;
    routed_pci_reply(&mut remote_write, &[252], 4, &[0x32, 0x23, 0x46]).await;
    routed_pci_reply(&mut remote_write, &[253], 5, &[0x32, 0x23, 0x46]).await;
    routed_pci_reply(&mut remote_write, &[253], 4, &[0x32, 0x23, 0x47]).await;
    routed_pci_reply(&mut remote_write, &[253], 4, &[0x32, 0x23, 0x46]).await;

    assert_eq!(
        database_pci_line(&mut remote_read).await,
        b"\\46FD09041A23066D\r"
    );
    database_pci_reply(
        &mut remote_write,
        4,
        &[0x87, 0x23, 0xce, 0x4c, 0xb3, 0x79, 0xe7, 0x9e],
    )
    .await;
    routed_pci_reply(
        &mut remote_write,
        &[252],
        4,
        &[0x87, 0x23, 0xce, 0x4c, 0xb3, 0x79, 0xe7, 0x9e],
    )
    .await;
    routed_pci_reply(
        &mut remote_write,
        &[253],
        4,
        &[0x87, 0x24, 0xce, 0x4c, 0xb3, 0x79, 0xe7, 0x9e],
    )
    .await;
    routed_pci_reply(
        &mut remote_write,
        &[253],
        4,
        &[0x87, 0x23, 0xce, 0x4c, 0xb3, 0x79, 0xe7, 0x9e],
    )
    .await;

    let response = setting.await.unwrap();
    assert_eq!(response.status, 200, "{response:?}");
    assert_eq!(response.final_text, "200 OK.");
    let model = service.model.lock().await;
    assert_eq!(
        model.projects["TOPO"].networks[&253].physical[&4].fields["ProjectName"],
        "TEST    "
    );
    assert!(model.projects["TOPO"].networks[&254].physical.is_empty());
    drop(model);
    assert!(
        events.try_recv().is_err(),
        "project identity mutation must not invent an event"
    );

    let property = service
        .handle(
            &mut ClientState::default(),
            "[get-rpi] GET //TOPO/253/p/4 ProjectName",
        )
        .await;
    assert_eq!(property.status, 300, "{property:?}");
    assert!(property.final_text.ends_with("ProjectName=TEST    "));
    std::fs::remove_file(path).unwrap();
}

#[tokio::test(start_paused = true)]
async fn bridged_pp_load_save_correlates_route_and_keeps_session_on_target_network() {
    async fn answer_identity<R, W>(reader: &mut R, writer: &mut W, attribute: u8, value: &[u8])
    where
        R: tokio::io::AsyncBufRead + Unpin,
        W: tokio::io::AsyncWrite + Unpin,
    {
        let request = database_pci_line(reader).await;
        assert!(
            request.starts_with(format!("\\46FD090421{attribute:02X}").as_bytes()),
            "{request:?}"
        );
        let code = request[request.len() - 2];
        let mut reply = vec![0x80 | (value.len() as u8 + 1), attribute];
        reply.extend_from_slice(value);
        database_pci_reply(writer, 4, &reply).await;
        routed_pci_reply(writer, &[252], 4, &reply).await;
        routed_pci_reply(writer, &[253], 5, &reply).await;
        routed_pci_reply(writer, &[253], 4, &reply).await;
        writer.write_all(&[code, b'.']).await.unwrap();
    }

    let path = state_path();
    let spec_dir = state_path().with_extension("routed-pp-unitspec");
    std::fs::create_dir_all(&spec_dir).unwrap();
    std::fs::write(
        spec_dir.join("TESTUNIT.xml"),
        r#"<UnitSpecification><Parameters>
        <Param><Name>Standard</Name><Type>int</Type><Address>$20</Address><ArraySize>2</ArraySize><ProgramMethod>direct</ProgramMethod><Protection>checksum</Protection><Tag>Core</Tag></Param>
        <Param><Name>Locked</Name><Type>int</Type><Address>$22</Address><ProgramMethod>direct</ProgramMethod><Protection>lock</Protection><Tag>Lock</Tag></Param>
        <Param><Name>Paged</Name><Type>int</Type><Address>$120</Address><ProgramMethod>paged</ProgramMethod><Protection>none</Protection><Tag>Paged</Tag></Param>
        </Parameters></UnitSpecification>"#,
    )
    .unwrap();
    std::fs::write(
        spec_dir.join("TESTNVM.xml"),
        r#"<UnitSpecification><Parameters>
        <Param><Name>Standard</Name><Type>int</Type><Address>$20</Address><ArraySize>2</ArraySize><ProgramMethod>direct</ProgramMethod><Protection>checksum</Protection><Tag>Core</Tag></Param>
        <Param><Name>UnrelatedNcc</Name><Type>int</Type><Address>$120</Address><ProgramMethod>ncc</ProgramMethod><Protection>none</Protection><Tag>Other</Tag></Param>
        </Parameters></UnitSpecification>"#,
    )
    .unwrap();
    let (pci_client, remote) = pci();
    let (remote_read, mut remote_write) = tokio::io::split(remote);
    let mut remote_read = BufReader::new(remote_read);
    let reset = tokio::spawn({
        let pci = pci_client.clone();
        async move { pci.pci_reset().await }
    });
    for _ in 0..8 {
        database_pci_line(&mut remote_read).await;
    }
    reset.await.unwrap().unwrap();

    let service = Service::new(
        &topology_fixture(),
        None,
        path.clone(),
        pci_client,
        Some(spec_dir.clone()),
    )
    .unwrap();
    let mut client = ClientState::default();
    for command in [
        "[pp-lock] PP LOCK REMOTE //TOPO/253",
        "[pp-start] PP START S REMOTE",
    ] {
        let response = service.handle(&mut client, command).await;
        assert_eq!(response.status, 200, "{command}: {response:?}");
    }

    let loading = tokio::spawn({
        let service = service.clone();
        let mut client = client.clone();
        async move {
            service
                .handle(&mut client, "[pp-load] PP LOAD S //TOPO/253/p/4 Core")
                .await
        }
    });
    answer_identity(&mut remote_read, &mut remote_write, 1, b"TESTUNIT").await;
    answer_identity(&mut remote_read, &mut remote_write, 2, b"1.2.03").await;
    assert_eq!(
        database_pci_line(&mut remote_read).await,
        b"\\46FD09041A200274\r"
    );
    database_pci_reply(&mut remote_write, 4, &[0x83, 0x20, 0x99, 0x99]).await;
    routed_pci_reply(&mut remote_write, &[252], 4, &[0x83, 0x20, 0xaa, 0xbb]).await;
    routed_pci_reply(&mut remote_write, &[253], 5, &[0x83, 0x20, 0xcc, 0xdd]).await;
    routed_pci_reply(&mut remote_write, &[253], 4, &[0x83, 0x21, 0xee, 0xff]).await;
    routed_pci_reply(&mut remote_write, &[253], 4, &[0x83, 0x20, 0x12, 0x34]).await;
    let loaded = loading.await.unwrap();
    assert_eq!(loaded.status, 200, "{loaded:?}");
    {
        let model = service.model.lock().await;
        let session = &model.sessions["S"];
        assert_eq!(session.source.as_deref(), Some("//TOPO/253/p/4"));
        assert_eq!(session.params["Standard"], "0x12 0x34");
        assert!(model.projects["TOPO"].networks[&254].physical.is_empty());
        assert!(model.projects["TOPO"].networks[&253].physical.is_empty());
    }

    assert_eq!(
        service
            .handle(&mut client, "[pp-set] PP SET S Standard 0x56 0x78")
            .await
            .status,
        200
    );
    let saving = tokio::spawn({
        let service = service.clone();
        let mut client = client.clone();
        async move {
            service
                .handle(&mut client, "[pp-save] PP SAVE_TO_SOURCE S")
                .await
        }
    });
    answer_identity(&mut remote_read, &mut remote_write, 1, b"TESTUNIT").await;
    answer_identity(&mut remote_read, &mut remote_write, 2, b"1.2.03").await;
    assert_eq!(
        database_pci_line(&mut remote_read).await,
        b"\\46FD09041A200274\r"
    );
    routed_pci_reply(&mut remote_write, &[253], 4, &[0x83, 0x20, 0x12, 0x34]).await;
    assert_eq!(
        database_pci_line(&mut remote_read).await,
        b"\\46FD0904A4200056781E\r"
    );
    routed_pci_reply(&mut remote_write, &[252], 4, &[0x32, 0x20, 0x00]).await;
    routed_pci_reply(&mut remote_write, &[253], 5, &[0x32, 0x20, 0x00]).await;
    routed_pci_reply(&mut remote_write, &[253], 4, &[0x32, 0x21, 0x00]).await;
    routed_pci_reply(&mut remote_write, &[253], 4, &[0x32, 0x20, 0x01]).await;
    routed_pci_reply(&mut remote_write, &[253], 4, &[0x32, 0x20, 0x00]).await;
    assert_eq!(
        database_pci_line(&mut remote_read).await,
        b"\\46FD09041A200274\r"
    );
    routed_pci_reply(&mut remote_write, &[252], 4, &[0x83, 0x20, 0x56, 0x78]).await;
    routed_pci_reply(&mut remote_write, &[253], 4, &[0x83, 0x20, 0x56, 0x78]).await;
    let saved = saving.await.unwrap();
    assert_eq!(saved.status, 200, "{saved:?}");
    {
        let model = service.model.lock().await;
        let session = &model.sessions["S"];
        assert!(session.dirty.is_empty());
        assert_eq!(session.source.as_deref(), Some("//TOPO/253/p/4"));
        assert!(model.projects["TOPO"].networks[&254].physical.is_empty());
        assert!(model.projects["TOPO"].networks[&253].physical.is_empty());
    }

    for command in [
        "[pp-start-lock] PP START L REMOTE",
        "[pp-new-lock] PP NEW L TESTUNIT 1.2.03",
        "[pp-set-lock] PP SET L Locked 0x06",
    ] {
        let response = service.handle(&mut client, command).await;
        assert_eq!(response.status, 200, "{command}: {response:?}");
    }
    let saving_lock = tokio::spawn({
        let service = service.clone();
        let mut client = client.clone();
        async move {
            service
                .handle(&mut client, "[pp-save-lock] PP SAVE L //TOPO/253/p/4 Lock")
                .await
        }
    });
    answer_identity(&mut remote_read, &mut remote_write, 1, b"TESTUNIT").await;
    answer_identity(&mut remote_read, &mut remote_write, 2, b"1.2.03").await;
    assert_eq!(
        database_pci_line(&mut remote_read).await,
        b"\\46FD09041A220173\r"
    );
    routed_pci_reply(&mut remote_write, &[253], 4, &[0x82, 0x22, 0x01]).await;

    let unlock = database_pci_line(&mut remote_read).await;
    assert_eq!(&unlock[..unlock.len() - 2], b"\\46FD090411227D");
    let unlock_confirmation = unlock[unlock.len() - 2];
    database_pci_reply(&mut remote_write, 4, &[0x82, 0x22, 0x11]).await;
    routed_pci_reply(&mut remote_write, &[252], 4, &[0x82, 0x22, 0x22]).await;
    routed_pci_reply(&mut remote_write, &[253], 5, &[0x82, 0x22, 0x33]).await;
    routed_pci_reply(&mut remote_write, &[253], 4, &[0x82, 0x23, 0x44]).await;
    routed_pci_reply(&mut remote_write, &[253], 4, &[0x82, 0x22, 0x5a]).await;
    remote_write
        .write_all(&[unlock_confirmation, b'.'])
        .await
        .unwrap();

    assert_eq!(
        database_pci_line(&mut remote_read).await,
        b"\\46FD0904A3220006E5\r"
    );
    routed_pci_reply(&mut remote_write, &[252], 4, &[0x32, 0x22, 0]).await;
    routed_pci_reply(&mut remote_write, &[253], 5, &[0x32, 0x22, 0]).await;
    routed_pci_reply(&mut remote_write, &[253], 4, &[0x32, 0x23, 0]).await;
    routed_pci_reply(&mut remote_write, &[253], 4, &[0x32, 0x22, 1]).await;
    routed_pci_reply(&mut remote_write, &[253], 4, &[0x32, 0x22, 0]).await;
    assert_eq!(
        database_pci_line(&mut remote_read).await,
        b"\\46FD09041A220173\r"
    );
    routed_pci_reply(&mut remote_write, &[253], 4, &[0x82, 0x22, 0x06]).await;
    let locked_saved = saving_lock.await.unwrap();
    assert_eq!(locked_saved.status, 200, "{locked_saved:?}");
    assert!(service.model.lock().await.sessions["L"].dirty.is_empty());

    for command in [
        "[pp-start-unsupported] PP START U REMOTE",
        "[pp-new-unsupported] PP NEW U TESTUNIT 1.2.03",
        "[pp-set-unsupported] PP SET U Paged 0x42",
    ] {
        let response = service.handle(&mut client, command).await;
        assert_eq!(response.status, 200, "{command}: {response:?}");
    }
    let saving_paged = tokio::spawn({
        let service = service.clone();
        let mut client = client.clone();
        async move {
            service
                .handle(
                    &mut client,
                    "[pp-save-paged] PP SAVE U //TOPO/253/p/4 Paged",
                )
                .await
        }
    });
    answer_identity(&mut remote_read, &mut remote_write, 1, b"TESTUNIT").await;
    answer_identity(&mut remote_read, &mut remote_write, 2, b"1.2.03").await;
    assert_eq!(
        database_pci_line(&mut remote_read).await,
        b"\\46FD09041B01200173\r"
    );
    database_pci_reply(&mut remote_write, 4, &[0x82, 0x20, 0x11]).await;
    routed_pci_reply(&mut remote_write, &[252], 4, &[0x82, 0x20, 0x22]).await;
    routed_pci_reply(&mut remote_write, &[253], 5, &[0x82, 0x20, 0x33]).await;
    routed_pci_reply(&mut remote_write, &[253], 4, &[0x82, 0x21, 0x44]).await;
    routed_pci_reply(&mut remote_write, &[253], 4, &[0x82, 0x20, 0x11]).await;
    assert_eq!(
        database_pci_line(&mut remote_read).await,
        b"\\46FD0904390176\r"
    );
    routed_pci_reply(&mut remote_write, &[253], 4, &[0x81, 1]).await;
    assert_eq!(
        database_pci_line(&mut remote_read).await,
        b"\\46FD0904A3200042AB\r"
    );
    routed_pci_reply(&mut remote_write, &[253], 4, &[0x32, 0x20, 0]).await;
    assert_eq!(
        database_pci_line(&mut remote_read).await,
        b"\\46FD09041B01200173\r"
    );
    routed_pci_reply(&mut remote_write, &[253], 4, &[0x82, 0x20, 0x42]).await;
    let paged_saved = saving_paged.await.unwrap();
    assert_eq!(paged_saved.status, 200, "{paged_saved:?}");
    assert!(service.model.lock().await.sessions["U"].dirty.is_empty());

    for command in [
        "[pp-start-nvm] PP START N REMOTE",
        "[pp-new-nvm] PP NEW N TESTNVM 1.2.03",
        "[pp-set-nvm] PP SET N Standard 0x56 0x78",
    ] {
        let response = service.handle(&mut client, command).await;
        assert_eq!(response.status, 200, "{command}: {response:?}");
    }
    let saving_nvm = tokio::spawn({
        let service = service.clone();
        let mut client = client.clone();
        async move {
            service
                .handle(&mut client, "[pp-save-nvm] PP SAVE N //TOPO/253/p/4 Core")
                .await
        }
    });
    answer_identity(&mut remote_read, &mut remote_write, 1, b"TESTNVM").await;
    answer_identity(&mut remote_read, &mut remote_write, 2, b"1.2.03").await;
    assert_eq!(
        database_pci_line(&mut remote_read).await,
        b"\\46FD09041A200274\r"
    );
    routed_pci_reply(&mut remote_write, &[253], 4, &[0x83, 0x20, 0x12, 0x34]).await;
    assert_eq!(
        database_pci_line(&mut remote_read).await,
        b"\\46FD0904A4200056781E\r"
    );
    routed_pci_reply(&mut remote_write, &[253], 4, &[0x32, 0x20, 0]).await;
    assert_eq!(
        database_pci_line(&mut remote_read).await,
        b"\\46FD09041A200274\r"
    );
    routed_pci_reply(&mut remote_write, &[253], 4, &[0x83, 0x20, 0x56, 0x78]).await;

    assert_eq!(
        database_pci_line(&mut remote_read).await,
        b"\\46FD0904E381000448\r"
    );
    // Direct, neighbouring-route, wrong-unit and wrong-operation replies
    // cannot complete a routed NVM commit.
    database_pci_reply(&mut remote_write, 4, &[0xe4, 0x83, 0, 4, 0]).await;
    routed_pci_reply(&mut remote_write, &[252], 4, &[0xe4, 0x83, 0, 4, 0]).await;
    routed_pci_reply(&mut remote_write, &[253], 5, &[0xe4, 0x83, 0, 4, 0]).await;
    routed_pci_reply(&mut remote_write, &[253], 4, &[0xe4, 0x83, 0, 5, 0]).await;
    routed_pci_reply(&mut remote_write, &[253], 4, &[0xe4, 0x83, 0, 4, 1]).await;
    assert_eq!(
        database_pci_line(&mut remote_read).await,
        b"\\46FD0904E382000447\r"
    );
    routed_pci_reply(&mut remote_write, &[253], 4, &[0xe4, 0x83, 0, 4, 1]).await;
    tokio::time::advance(Duration::from_millis(500)).await;
    tokio::task::yield_now().await;
    assert_eq!(
        database_pci_line(&mut remote_read).await,
        b"\\46FD0904E382000447\r"
    );
    routed_pci_reply(&mut remote_write, &[253], 4, &[0xe4, 0x83, 0, 4, 0]).await;

    let nvm_saved = saving_nvm.await.unwrap();
    assert_eq!(nvm_saved.status, 200, "{nvm_saved:?}");
    assert!(service.model.lock().await.sessions["N"].dirty.is_empty());

    std::fs::remove_file(path).unwrap();
    std::fs::remove_dir_all(spec_dir).unwrap();
}

#[tokio::test]
async fn bridged_standard_application_control_is_exact_once_and_target_scoped() {
    let path = state_path();
    let xml = topology_fixture().replace(
        "</Project>",
        r#"<Network oid="network-252">
        <TagName>Unroutable</TagName><Address>252</Address>
        <Interface><InterfaceType>Bridge</InterfaceType><InterfaceAddress>253/p/252</InterfaceAddress></Interface>
        </Network></Project>"#,
    );
    let (pci_client, remote) = pci();
    let (remote_read, mut remote_write) = tokio::io::split(remote);
    let mut remote_read = BufReader::new(remote_read);
    let reset = tokio::spawn({
        let pci = pci_client.clone();
        async move { pci.pci_reset().await }
    });
    for _ in 0..8 {
        database_pci_line(&mut remote_read).await;
    }
    reset.await.unwrap().unwrap();

    let service = Service::new(&xml, None, path.clone(), pci_client, None).unwrap();
    {
        let mut model = service.model.lock().await;
        let project = model.projects.get_mut("TOPO").unwrap();
        project.networks.get_mut(&254).unwrap().levels =
            HashMap::from([((56, 1), 11), ((202, 2), 12), ((203, 3), 13)]);
        project.networks.get_mut(&253).unwrap().levels =
            HashMap::from([((56, 1), 99), ((202, 2), 98), ((203, 3), 97)]);
    }

    let mut lighting_events = service.events.subscribe();
    let lighting = tokio::spawn({
        let service = service.clone();
        async move {
            service
                .handle(
                    &mut ClientState::default(),
                    "[routed-lighting] ON //TOPO/253/56/1",
                )
                .await
        }
    });
    let request = database_pci_line(&mut remote_read).await;
    assert_eq!(&request[..request.len() - 2], b"\\03FD0938790145");
    let code = request[request.len() - 2];
    let wrong = if code == b'z' { b'y' } else { b'z' };
    remote_write.write_all(&[wrong, b'.']).await.unwrap();
    routed_pci_reply(&mut remote_write, &[252], 4, &[0x82, 1, 0]).await;
    tokio::task::yield_now().await;
    assert!(!lighting.is_finished());
    remote_write.write_all(&[code, b'.']).await.unwrap();
    let response = lighting.await.unwrap();
    assert_eq!(response.status, 200, "{response:?}");
    assert_eq!(
        lighting_events.recv().await.unwrap(),
        "#e# lighting //TOPO/253/56/1 ON 255"
    );
    {
        let model = service.model.lock().await;
        assert_eq!(model.projects["TOPO"].networks[&254].levels[&(56, 1)], 11);
        assert!(!model.projects["TOPO"].networks[&253]
            .levels
            .contains_key(&(56, 1)));
    }
    assert!(
        tokio::time::timeout(Duration::from_millis(20), remote_read.read_u8())
            .await
            .is_err(),
        "routed lighting must not invent a status-readback exchange"
    );

    let do_lighting = tokio::spawn({
        let service = service.clone();
        async move {
            service
                .handle(
                    &mut ClientState::default(),
                    "[routed-do] DO //TOPO/253/56/1 OFF",
                )
                .await
        }
    });
    let request = database_pci_line(&mut remote_read).await;
    assert_eq!(&request[..request.len() - 2], b"\\03FD09380101BD");
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    let response = do_lighting.await.unwrap();
    assert_eq!(response.status, 202, "{response:?}");
    assert_eq!(response.final_text, "202 Done: //TOPO/253/56/1");

    let mut trigger_events = service.events.subscribe();
    let trigger = tokio::spawn({
        let service = service.clone();
        async move {
            service
                .handle(
                    &mut ClientState::default(),
                    "[routed-trigger] TRIGGER EVENT //TOPO/253/202/2 55",
                )
                .await
        }
    });
    let request = database_pci_line(&mut remote_read).await;
    assert_eq!(&request[..request.len() - 2], b"\\03FD09CA020237F2");
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    let response = trigger.await.unwrap();
    assert_eq!(response.status, 200, "{response:?}");
    assert_eq!(
        trigger_events.recv().await.unwrap(),
        "#e# trigger //TOPO/253/202/2 event action=55 sourceUnit=0"
    );
    {
        let model = service.model.lock().await;
        assert_eq!(model.projects["TOPO"].networks[&254].levels[&(202, 2)], 12);
        assert_eq!(model.projects["TOPO"].networks[&253].levels[&(202, 2)], 55);
    }

    let trigger_kill = tokio::spawn({
        let service = service.clone();
        async move {
            service
                .handle(
                    &mut ClientState::default(),
                    "[routed-trigger-kill] TRIGGER INDICATORKILL //TOPO/253/202/2",
                )
                .await
        }
    });
    let request = database_pci_line(&mut remote_read).await;
    assert_eq!(&request[..request.len() - 2], b"\\03FD09CA090222");
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    assert_eq!(trigger_kill.await.unwrap().status, 200);

    let mut enable_events = service.events.subscribe();
    let enable = tokio::spawn({
        let service = service.clone();
        async move {
            service
                .handle(
                    &mut ClientState::default(),
                    "[routed-enable] ENABLE SET //TOPO/253/203/3 77",
                )
                .await
        }
    });
    let request = database_pci_line(&mut remote_read).await;
    assert_eq!(&request[..request.len() - 2], b"\\03FD09CB02034DDA");
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    let response = enable.await.unwrap();
    assert_eq!(response.status, 200, "{response:?}");
    assert_eq!(
        enable_events.recv().await.unwrap(),
        "#e# enable //TOPO/253/203/3 set value=77 sourceUnit=0"
    );
    {
        let model = service.model.lock().await;
        assert_eq!(model.projects["TOPO"].networks[&254].levels[&(203, 3)], 13);
        assert_eq!(model.projects["TOPO"].networks[&253].levels[&(203, 3)], 77);
    }

    for (command, status) in [
        ("ON //TOPO/253/202/1", 400),
        ("ON //TOPO/252/56/1", 408),
        ("ENABLE SET //OTHER/253/203/3 1", 404),
    ] {
        let response = service
            .handle(
                &mut ClientState::default(),
                &format!("[unsupported] {command}"),
            )
            .await;
        assert_eq!(response.status, status, "{command}: {response:?}");
        assert!(
            tokio::time::timeout(Duration::from_millis(20), remote_read.read_u8())
                .await
                .is_err(),
            "unsupported routed application command wrote to PCI: {command}"
        );
    }

    let stale = tokio::spawn({
        let service = service.clone();
        async move {
            service
                .handle(
                    &mut ClientState::default(),
                    "[stale] ENABLE SET //TOPO/253/203/3 88",
                )
                .await
        }
    });
    let request = database_pci_line(&mut remote_read).await;
    assert_eq!(&request[..request.len() - 2], b"\\03FD09CB020358CF");
    let code = request[request.len() - 2];
    let (replacement, _replacement_remote) = pci();
    service.set_pci(replacement).await;
    remote_write.write_all(&[code, b'.']).await.unwrap();
    let response = stale.await.unwrap();
    assert_eq!(response.status, 408, "{response:?}");
    assert_eq!(
        service.model.lock().await.projects["TOPO"].networks[&253]
            .levels
            .get(&(203, 3)),
        None,
        "the replacement generation's invalidation must not be overwritten"
    );

    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn bridged_specialist_application_families_use_exact_route_and_one_shot_confirmation() {
    let path = state_path();
    let xml = topology_fixture().replace(
        "</Project>",
        r#"<Network oid="network-252">
        <TagName>Unroutable</TagName><Address>252</Address>
        <Interface><InterfaceType>Bridge</InterfaceType><InterfaceAddress>253/p/252</InterfaceAddress></Interface>
        </Network></Project>"#,
    );
    let (pci_client, remote) = pci();
    let (remote_read, mut remote_write) = tokio::io::split(remote);
    let mut remote_read = BufReader::new(remote_read);
    let reset = tokio::spawn({
        let pci = pci_client.clone();
        async move { pci.pci_reset().await }
    });
    for _ in 0..8 {
        database_pci_line(&mut remote_read).await;
    }
    reset.await.unwrap().unwrap();

    let service = Service::new(&xml, None, path.clone(), pci_client, None).unwrap();
    let cases: Vec<(&str, u8, Vec<u8>)> = vec![
        (
            "MEASUREMENT DATA //TOPO/253/228/1/1 10234 -2 2",
            228,
            vec![0x0e, 0x01, 0x01, 0x02, 0xfe, 0x27, 0xfa],
        ),
        ("AIRCON REFRESH //TOPO/253/172 1", 172, vec![0x21, 0x01]),
        ("AUDIO ON //TOPO/253/205 Z 255", 205, vec![0x79, 0xff]),
        (
            "SECURITY STATUS_REQUEST //TOPO/253/208 1",
            208,
            vec![0x09, 0xa0],
        ),
        (
            "MEDIATRANSPORT STOP //TOPO/253/192 2",
            192,
            vec![0x01, 0x02],
        ),
        (
            "TELEPHONY CLEAR_DIVERSION //TOPO/253/224",
            224,
            vec![0x09, 0x84],
        ),
        ("IDENTIFY ON //TOPO/253/251/1", 251, vec![0x79, 0x01]),
        (
            "SHORTMESSAGE REFRESH //TOPO/253/173 4",
            173,
            vec![0x01, 0x04],
        ),
        (
            "EREPORT MESSAGE //TOPO/253/206 ACK 1023 n n n 7 255 255 255",
            206,
            vec![0x25, 0xff, 0xc7, 0xff, 0xff, 0xff],
        ),
        (
            "ACCESS_CONTROL CLOSE //TOPO/253/213 1 2",
            213,
            vec![0x02, 0x01, 0x02],
        ),
    ];

    for (index, (command, application, sal)) in cases.into_iter().enumerate() {
        let delivery = tokio::spawn({
            let service = service.clone();
            let command = command.to_string();
            async move {
                service
                    .handle(
                        &mut ClientState::default(),
                        &format!("[specialist-{index}] {command}"),
                    )
                    .await
            }
        });
        let request = database_pci_line(&mut remote_read).await;
        let mut expected = vec![0x03, 253, 0x09, application];
        expected.extend_from_slice(&sal);
        let checksum = 0u8.wrapping_sub(
            expected
                .iter()
                .fold(0u8, |sum, byte| sum.wrapping_add(*byte)),
        );
        expected.push(checksum);
        let expected = format!("\\{}", hex::encode_upper(expected));
        assert_eq!(
            &request[..request.len() - 2],
            expected.as_bytes(),
            "{command}"
        );
        let code = request[request.len() - 2];
        if index == 0 {
            let wrong = if code == b'z' { b'y' } else { b'z' };
            remote_write.write_all(&[wrong, b'.']).await.unwrap();
            routed_pci_reply(&mut remote_write, &[252], 4, &[0x82, 1, 0]).await;
            tokio::task::yield_now().await;
            assert!(
                !delivery.is_finished(),
                "foreign route traffic or an unrelated confirmation completed {command}"
            );
        }
        remote_write.write_all(&[code, b'.']).await.unwrap();
        let response = delivery.await.unwrap();
        assert_eq!(response.status, 200, "{command}: {response:?}");
    }

    for command in [
        "AIRCON REFRESH //TOPO/252/172 1",
        "SECURITY STATUS_REQUEST //OTHER/253/208 1",
    ] {
        let response = service
            .handle(&mut ClientState::default(), &format!("[refuse] {command}"))
            .await;
        assert!(response.status >= 400, "{command}: {response:?}");
        assert!(
            tokio::time::timeout(Duration::from_millis(20), remote_read.read_u8())
                .await
                .is_err(),
            "unroutable specialist application wrote to PCI: {command}"
        );
    }

    let stale = tokio::spawn({
        let service = service.clone();
        async move {
            service
                .handle(
                    &mut ClientState::default(),
                    "[stale-specialist] AIRCON REFRESH //TOPO/253/172 1",
                )
                .await
        }
    });
    let request = database_pci_line(&mut remote_read).await;
    let code = request[request.len() - 2];
    let (replacement, _replacement_remote) = pci();
    service.set_pci(replacement).await;
    remote_write.write_all(&[code, b'.']).await.unwrap();
    let response = stale.await.unwrap();
    assert_eq!(response.status, 502, "{response:?}");
    assert!(response.final_text.contains("generation changed"));

    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn bridged_labels_clocks_temperature_and_named_scenes_are_exact_and_target_scoped() {
    let path = state_path();
    let xml = topology_fixture().replace(
        "</Project>",
        r#"<Network oid="network-252">
        <TagName>Unroutable</TagName><Address>252</Address>
        <Interface><InterfaceType>Bridge</InterfaceType><InterfaceAddress>253/p/252</InterfaceAddress></Interface>
        </Network></Project>"#,
    );
    let (pci_client, remote) = pci();
    let (remote_read, mut remote_write) = tokio::io::split(remote);
    let mut remote_read = BufReader::new(remote_read);
    let reset = tokio::spawn({
        let pci = pci_client.clone();
        async move { pci.pci_reset().await }
    });
    for _ in 0..8 {
        database_pci_line(&mut remote_read).await;
    }
    reset.await.unwrap().unwrap();

    let service = Service::new(&xml, None, path.clone(), pci_client, None).unwrap();
    let cases = [
        (
            "label",
            "LIGHTING LABEL //TOPO/253/56 0 1 - F0 0 41",
            b"\\03FD0938A401000041D9".as_slice(),
        ),
        (
            "clock-refresh",
            "CLOCK REQUEST_REFRESH //TOPO/253/223",
            b"\\03FD09DF110304".as_slice(),
        ),
        (
            "clock-date",
            "CLOCK DATE //TOPO/253/223 2026-09-27",
            b"\\03FD09DF0E0207EA091B06ED".as_slice(),
        ),
        (
            "temperature",
            "TEMPERATURE BROADCAST //TOPO/253/25/3 21.0",
            b"\\03FD091902035485".as_slice(),
        ),
    ];
    for (index, (tag, command, expected)) in cases.into_iter().enumerate() {
        let pending = tokio::spawn({
            let service = service.clone();
            let command = command.to_string();
            async move {
                service
                    .handle(&mut ClientState::default(), &format!("[{tag}] {command}"))
                    .await
            }
        });
        let request = match tokio::time::timeout(
            Duration::from_millis(200),
            database_pci_line(&mut remote_read),
        )
        .await
        {
            Ok(request) => request,
            Err(_) if pending.is_finished() => {
                panic!(
                    "{command} returned before PCI I/O: {:?}",
                    pending.await.unwrap()
                )
            }
            Err(_) => panic!("{command} did not write its routed frame"),
        };
        assert_eq!(&request[..request.len() - 2], expected, "{command}");
        let code = request[request.len() - 2];
        if index == 0 {
            let wrong = if code == b'z' { b'y' } else { b'z' };
            remote_write.write_all(&[wrong, b'.']).await.unwrap();
            routed_pci_reply(&mut remote_write, &[252], 4, &[0x82, 1, 0]).await;
            tokio::task::yield_now().await;
            assert!(
                !pending.is_finished(),
                "foreign traffic completed routed {command}"
            );
        }
        remote_write.write_all(&[code, b'.']).await.unwrap();
        let response = pending.await.unwrap();
        assert!(response.status < 400, "{command}: {response:?}");
    }

    assert!(
        service.observed_labels.lock().await.observations.is_empty(),
        "a routed label must not be attributed to the configured-network observation cache"
    );
    let model = service.model.lock().await;
    assert!(!model.application_state.contains_key("CLOCK DATE"));
    assert!(!model
        .application_state
        .contains_key("TEMPERATURE BROADCAST"));
    drop(model);

    service.model.lock().await.scene_snapshots.insert(
        "house/remote".to_string(),
        vec![("//TOPO/253/56/1".to_string(), 42)],
    );
    let scene = tokio::spawn({
        let service = service.clone();
        async move {
            service
                .handle(
                    &mut ClientState::default(),
                    "[scene] SCENE PLAY house remote",
                )
                .await
        }
    });
    let request = database_pci_line(&mut remote_read).await;
    assert_eq!(
        &request[..request.len() - 2],
        b"\\03FD093802012A92",
        "named-scene routed ramp wire changed"
    );
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    assert_eq!(scene.await.unwrap().status, 200);
    assert!(
        tokio::time::timeout(Duration::from_millis(20), remote_read.read_u8())
            .await
            .is_err(),
        "routed scene playback must not invent a direct-network status readback"
    );

    service.model.lock().await.scene_snapshots.insert(
        "house/bad-route".to_string(),
        vec![("//TOPO/252/56/1".to_string(), 99)],
    );
    let response = service
        .handle(
            &mut ClientState::default(),
            "[bad-scene] SCENE PLAY house bad-route",
        )
        .await;
    assert_eq!(response.status, 408, "{response:?}");
    assert!(
        tokio::time::timeout(Duration::from_millis(20), remote_read.read_u8())
            .await
            .is_err(),
        "an unroutable scene must fail in preflight before physical I/O"
    );

    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn bridged_network_management_is_exact_once_route_correlated_and_generation_guarded() {
    let path = state_path();
    let xml = topology_fixture().replace(
        "</Project>",
        r#"<Network oid="network-252">
        <TagName>Unroutable</TagName><Address>252</Address>
        <Interface><InterfaceType>Bridge</InterfaceType><InterfaceAddress>253/p/252</InterfaceAddress></Interface>
        </Network></Project>"#,
    );
    let (pci_client, remote) = pci();
    let (remote_read, mut remote_write) = tokio::io::split(remote);
    let mut remote_read = BufReader::new(remote_read);
    let reset = tokio::spawn({
        let pci = pci_client.clone();
        async move { pci.pci_reset().await }
    });
    for _ in 0..8 {
        database_pci_line(&mut remote_read).await;
    }
    reset.await.unwrap().unwrap();

    let service = Service::new(&xml, None, path.clone(), pci_client, None).unwrap();
    let cases = [
        (
            "learn",
            "NET LEARN //TOPO/253 56 1 1",
            b"\\03FD0938030101FEBC".as_slice(),
        ),
        (
            "locate-unit",
            "NETWORK LOCATE //TOPO/253/208 UNIT 1 ON",
            b"\\03FD09D013FF010113".as_slice(),
        ),
        (
            "locate-application",
            "NETWORK LOCATE //TOPO/253/208 APP 56 2",
            b"\\03FD09D01338FF02DB".as_slice(),
        ),
        (
            "locate-group",
            "NETWORK LOCATE //TOPO/253/208 GROUP 56 1 OFF",
            b"\\03FD09D013380100DB".as_slice(),
        ),
        (
            "locate-serial",
            "NETWORK LOCATE //TOPO/253/208 SERIAL 1 12345.67 255",
            b"\\03FD09D0160103039043FF38".as_slice(),
        ),
    ];

    for (index, (tag, command, expected)) in cases.into_iter().enumerate() {
        let pending = tokio::spawn({
            let service = service.clone();
            let command = command.to_string();
            async move {
                service
                    .handle(&mut ClientState::default(), &format!("[{tag}] {command}"))
                    .await
            }
        });
        let request = database_pci_line(&mut remote_read).await;
        assert_eq!(&request[..request.len() - 2], expected, "{command}");
        let code = request[request.len() - 2];
        if index == 0 {
            let wrong = if code == b'z' { b'y' } else { b'z' };
            remote_write.write_all(&[wrong, b'.']).await.unwrap();
            routed_pci_reply(&mut remote_write, &[252], 4, &[0x82, 1, 0]).await;
            tokio::task::yield_now().await;
            assert!(
                !pending.is_finished(),
                "unrelated confirmation or Reply Network completed {command}"
            );
        }
        remote_write.write_all(&[code, b'.']).await.unwrap();
        let response = pending.await.unwrap();
        assert_eq!(response.status, 200, "{command}: {response:?}");
    }

    for command in [
        "NET LEARN //TOPO/252 56 1 1",
        "NETWORK LOCATE //TOPO/252/208 UNIT 1 ON",
        "NET LEARN //OTHER/253 56 1 1",
    ] {
        let response = service
            .handle(
                &mut ClientState::default(),
                &format!("[unroutable] {command}"),
            )
            .await;
        assert!(
            matches!(response.status, 408 | 502),
            "{command}: {response:?}"
        );
        assert!(
            tokio::time::timeout(Duration::from_millis(20), remote_read.read_u8())
                .await
                .is_err(),
            "unsupported network-management route wrote to PCI: {command}"
        );
    }

    let stale = tokio::spawn({
        let service = service.clone();
        async move {
            service
                .handle(
                    &mut ClientState::default(),
                    "[stale-net-management] NETWORK LOCATE //TOPO/253/208 UNIT 2 ON",
                )
                .await
        }
    });
    let request = database_pci_line(&mut remote_read).await;
    let code = request[request.len() - 2];
    let (replacement, _replacement_remote) = pci();
    service.set_pci(replacement).await;
    remote_write.write_all(&[code, b'.']).await.unwrap();
    let response = stale.await.unwrap();
    assert_eq!(response.status, 408, "{response:?}");
    assert!(response.final_text.contains("invalidated by PCI reconnect"));

    std::fs::remove_file(path).unwrap();
}

#[tokio::test(start_paused = true)]
async fn bridged_project_identity_bad_readback_invalidates_only_target_without_replay() {
    let path = state_path();
    let (pci_client, remote) = pci();
    let (remote_read, mut remote_write) = tokio::io::split(remote);
    let mut remote_read = BufReader::new(remote_read);
    let reset = tokio::spawn({
        let pci = pci_client.clone();
        async move { pci.pci_reset().await }
    });
    for _ in 0..8 {
        database_pci_line(&mut remote_read).await;
    }
    reset.await.unwrap().unwrap();

    let service = Service::new(
        &topology_fixture(),
        None,
        path.clone(),
        pci_client.clone(),
        None,
    )
    .unwrap();
    {
        let mut model = service.model.lock().await;
        let project = model.projects.get_mut("TOPO").unwrap();
        project
            .networks
            .get_mut(&253)
            .unwrap()
            .physical
            .entry(4)
            .or_insert_with(|| Unit::blank(4, "KEYE1"))
            .fields
            .insert("ProjectName".to_string(), "OLD     ".to_string());
        project
            .networks
            .get_mut(&254)
            .unwrap()
            .physical
            .entry(7)
            .or_insert_with(|| Unit::blank(7, "KEYE1"))
            .fields
            .insert("ProjectName".to_string(), "KEEP    ".to_string());
    }

    let setting = tokio::spawn({
        let service = service.clone();
        async move {
            service
                .handle(
                    &mut ClientState::default(),
                    "[rpi-bad] NET SET_PROJECT_IDENTIFY //TOPO/253 TEST",
                )
                .await
        }
    });

    let request = database_pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\03FD09FFFAFF00FF"), "{request:?}");
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    for (start, count) in [(0, 88), (88, 88), (176, 80)] {
        remote_write
            .write_all(&routed_mmi_block(&[253], start, count, &[(4, 1)]))
            .await
            .unwrap();
    }

    let request = database_pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\46FD09042101"), "{request:?}");
    let code = request[request.len() - 2];
    routed_pci_reply(
        &mut remote_write,
        &[253],
        4,
        &[0x86, 1, b'K', b'E', b'Y', b'E', b'1'],
    )
    .await;
    remote_write.write_all(&[code, b'.']).await.unwrap();

    let request = database_pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\46FD09042104"), "{request:?}");
    let code = request[request.len() - 2];
    routed_pci_reply(
        &mut remote_write,
        &[253],
        4,
        &[
            0x8d, 4, 0x38, 0xff, 0xff, 0xff, 0xff, 0x18, 0xb1, 0x06, 0x16, 0xa2, 0x00, 0x05,
        ],
    )
    .await;
    remote_write.write_all(&[code, b'.']).await.unwrap();
    tokio::time::advance(Duration::from_secs(2)).await;
    tokio::task::yield_now().await;

    assert_eq!(
        database_pci_line(&mut remote_read).await,
        b"\\46FD0904A82346CE4CB379E79ED4\r"
    );
    routed_pci_reply(&mut remote_write, &[253], 4, &[0x32, 0x23, 0x46]).await;
    assert_eq!(
        database_pci_line(&mut remote_read).await,
        b"\\46FD09041A23066D\r"
    );
    routed_pci_reply(
        &mut remote_write,
        &[253],
        4,
        &[0x87, 0x23, 0, 0, 0, 0, 0, 0],
    )
    .await;

    let response = setting.await.unwrap();
    assert_eq!(response.status, 408, "{response:?}");
    assert_eq!(
        response.final_text,
        "408 Operation failed: project name save failed - store to unit failed"
    );
    assert_eq!(
        pci_client.programming_lane_state(),
        cbus_transport::pci::ProgrammingLaneState::ReconnectRequired
    );
    let model = service.model.lock().await;
    assert!(
        !model.projects["TOPO"].networks[&253].physical[&4]
            .fields
            .contains_key("ProjectName"),
        "uncertain routed readback must invalidate the target cache"
    );
    assert_eq!(
        model.projects["TOPO"].networks[&254].physical[&7].fields["ProjectName"], "KEEP    ",
        "target invalidation must not clear the root-network cache"
    );
    drop(model);
    let trailing = tokio::time::timeout(Duration::from_millis(25), remote_read.read_u8()).await;
    match trailing {
        Err(_) => {}
        Ok(Err(error)) if error.kind() == std::io::ErrorKind::UnexpectedEof => {}
        other => panic!("uncertain routed STORE was replayed: {other:?}"),
    }
    std::fs::remove_file(path).unwrap();
}

#[tokio::test(start_paused = true)]
async fn physical_project_identify_fails_closed_before_store_and_on_bad_readback() {
    async fn pci_line<R: tokio::io::AsyncBufRead + Unpin>(reader: &mut R) -> Vec<u8> {
        let mut line = Vec::new();
        reader.read_until(b'\r', &mut line).await.unwrap();
        line
    }
    async fn pci_reply<W: tokio::io::AsyncWrite + Unpin>(writer: &mut W, source: u8, cal: &[u8]) {
        let mut bytes = vec![0x86, source, 0x10, 0x00];
        bytes.extend_from_slice(cal);
        let sum = bytes.iter().fold(0u8, |sum, byte| sum.wrapping_add(*byte));
        bytes.push(0u8.wrapping_sub(sum));
        let mut wire = hex::encode_upper(bytes).into_bytes();
        wire.extend_from_slice(b"\r\n");
        writer.write_all(&wire).await.unwrap();
    }
    fn mmi_block(start: u8, count: usize, address: usize, state: u8) -> Vec<u8> {
        let mut states = vec![0u8; count];
        if (usize::from(start)..usize::from(start) + count).contains(&address) {
            states[address - usize::from(start)] = state;
        }
        let mut wire = cbus_protocol::packet::Packet::StandardStatus {
            application: 0xff,
            block_start: start,
            states,
        }
        .encode_packet()
        .unwrap();
        wire.extend_from_slice(b"\r\n");
        wire
    }

    let path = state_path();
    let (pci, remote) = pci();
    let (remote_read, mut remote_write) = tokio::io::split(remote);
    let mut remote_read = BufReader::new(remote_read);
    let reset = tokio::spawn({
        let pci = pci.clone();
        async move { pci.pci_reset().await }
    });
    for _ in 0..8 {
        pci_line(&mut remote_read).await;
    }
    reset.await.unwrap().unwrap();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();

    // A loaded network that is not the service's bound physical endpoint is
    // valid in the database model, but must fail closed without returning a
    // synthetic success or issuing PCI traffic.
    let other_network = service
        .handle(
            &mut ClientState::default(),
            "[43] DBCREATENET 253 Other Cni 127.0.0.1:10002",
        )
        .await;
    assert_eq!(other_network.status, 200, "{other_network:?}");
    let unbound = service
        .handle(
            &mut ClientState::default(),
            "[43a] NET SET_PROJECT_IDENTIFY //HARNESS/253 TEST",
        )
        .await;
    assert_eq!(unbound.status, 408, "{unbound:?}");
    assert_eq!(
        unbound.final_text,
        "408 Physical network route unavailable: networks do not share a bridge root"
    );
    assert!(
        tokio::time::timeout(Duration::from_millis(25), remote_read.read_u8())
            .await
            .is_err(),
        "a valid but unbound network must not issue physical I/O"
    );

    let invalid = service
        .handle(
            &mut ClientState::default(),
            "[44] NET SET_PROJECT_IDENTIFY //HARNESS/254 TOOLONG99",
        )
        .await;
    assert_eq!(invalid.status, 400, "{invalid:?}");
    assert!(
        tokio::time::timeout(Duration::from_millis(25), remote_read.read_u8())
            .await
            .is_err(),
        "invalid text must fail before physical I/O"
    );
    let bad_character = service
        .handle(
            &mut ClientState::default(),
            "[44b] NET SET_PROJECT_IDENTIFY //HARNESS/254 {",
        )
        .await;
    assert_eq!(bad_character.status, 408, "{bad_character:?}");
    assert_eq!(
        bad_character.final_text,
        "408 Operation failed: Character out of sixbit range"
    );
    assert!(
        tokio::time::timeout(Duration::from_millis(25), remote_read.read_u8())
            .await
            .is_err(),
        "six-bit encoding failure must occur before physical I/O"
    );

    let setting = tokio::spawn({
        let service = service.clone();
        async move {
            service
                .handle(
                    &mut ClientState::default(),
                    "[45] NET SET_PROJECT_IDENTIFY //HARNESS/254 TEST",
                )
                .await
        }
    });
    assert_eq!(pci_line(&mut remote_read).await, b"@1A2001\r");
    remote_write.write_all(b"8220104E\r\n").await.unwrap();
    tokio::task::yield_now().await;
    let request = pci_line(&mut remote_read).await;
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    for block in [
        mmi_block(0, 88, 6, 3),
        mmi_block(88, 88, 6, 3),
        mmi_block(176, 80, 6, 3),
    ] {
        remote_write.write_all(&block).await.unwrap();
    }
    tokio::task::yield_now().await;

    let response = setting.await.unwrap();
    assert_eq!(response.status, 408, "{response:?}");
    assert_eq!(
        response.final_text,
        "408 Operation failed: Can't find unit to set project name in"
    );
    assert!(
        tokio::time::timeout(Duration::from_millis(25), remote_read.read_u8())
            .await
            .is_err(),
        "MMI error state must not issue IDENTIFY or STORE"
    );
    assert!(
        service.model.lock().await.projects["HARNESS"].networks[&254]
            .physical
            .is_empty()
    );

    // A state-two MMI address can still hide multiple physical units. Two
    // distinct serial replies must therefore abort before parameter 35 is
    // written, even though IDENTIFY1 returned a usable type.
    let duplicate_serials = tokio::spawn({
        let service = service.clone();
        async move {
            service
                .handle(
                    &mut ClientState::default(),
                    "[45b] NET SET_PROJECT_IDENTIFY //HARNESS/254 TEST",
                )
                .await
        }
    });
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\05FF00FAFF"), "{request:?}");
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    for block in [
        mmi_block(0, 88, 6, 2),
        mmi_block(88, 88, 6, 2),
        mmi_block(176, 80, 6, 2),
    ] {
        remote_write.write_all(&block).await.unwrap();
    }
    tokio::task::yield_now().await;
    let identify = pci_line(&mut remote_read).await;
    assert!(identify.starts_with(b"\\4606002101"), "{identify:?}");
    let code = identify[identify.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    pci_reply(
        &mut remote_write,
        6,
        &[0x86, 1, b'K', b'E', b'Y', b'E', b'1'],
    )
    .await;
    tokio::task::yield_now().await;
    let identify = pci_line(&mut remote_read).await;
    assert!(identify.starts_with(b"\\4606002104"), "{identify:?}");
    let code = identify[identify.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    for serial_tail in [0x16, 0x17] {
        pci_reply(
            &mut remote_write,
            6,
            &[
                0x8d,
                4,
                0x38,
                0xff,
                0xff,
                0xff,
                0xff,
                0x18,
                0xb1,
                0x06,
                serial_tail,
                0xa2,
                0x00,
                0x05,
            ],
        )
        .await;
    }
    tokio::time::advance(Duration::from_secs(2)).await;
    tokio::task::yield_now().await;
    let response = duplicate_serials.await.unwrap();
    assert_eq!(response.status, 408, "{response:?}");
    assert_eq!(
        response.final_text,
        "408 Operation failed: Can't find unit to set project name in"
    );
    assert!(
        tokio::time::timeout(Duration::from_millis(25), remote_read.read_u8())
            .await
            .is_err(),
        "multiple serial replies must not issue STORE"
    );

    // Seed an older volatile value so the failed readback below proves it is
    // invalidated rather than continuing to serve stale physical state.
    {
        let mut model = service.model.lock().await;
        let network = model
            .projects
            .get_mut("HARNESS")
            .unwrap()
            .networks
            .get_mut(&254)
            .unwrap();
        let mut unit = Unit::blank(6, "");
        unit.fields
            .insert("ProjectName".to_string(), "OLD     ".to_string());
        network.physical.insert(6, unit);
    }

    // A STORE ACK is not enough: a mismatching parameter-35 RECALL fails the
    // operation and must invalidate an older ProjectName in the physical cache.
    let mismatch = tokio::spawn({
        let service = service.clone();
        async move {
            service
                .handle(
                    &mut ClientState::default(),
                    "[46] NET SET_PROJECT_IDENTIFY //HARNESS/254 TEST",
                )
                .await
        }
    });
    let request = pci_line(&mut remote_read).await;
    assert!(request.starts_with(b"\\05FF00FAFF"), "{request:?}");
    let code = request[request.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    for block in [
        mmi_block(0, 88, 6, 1),
        mmi_block(88, 88, 6, 1),
        mmi_block(176, 80, 6, 1),
    ] {
        remote_write.write_all(&block).await.unwrap();
    }
    tokio::task::yield_now().await;
    let identify = pci_line(&mut remote_read).await;
    assert!(identify.starts_with(b"\\4606002101"), "{identify:?}");
    let code = identify[identify.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    pci_reply(
        &mut remote_write,
        6,
        &[0x86, 1, b'K', b'E', b'Y', b'E', b'1'],
    )
    .await;
    tokio::task::yield_now().await;
    let identify = pci_line(&mut remote_read).await;
    assert!(identify.starts_with(b"\\4606002104"), "{identify:?}");
    let code = identify[identify.len() - 2];
    remote_write.write_all(&[code, b'.']).await.unwrap();
    pci_reply(
        &mut remote_write,
        6,
        &[
            0x8d, 4, 0x38, 0xff, 0xff, 0xff, 0xff, 0x18, 0xb1, 0x06, 0x16, 0xa2, 0x00, 0x05,
        ],
    )
    .await;
    tokio::time::advance(Duration::from_secs(2)).await;
    tokio::task::yield_now().await;
    assert_eq!(
        pci_line(&mut remote_read).await,
        b"\\460600A82346CE4CB379E79ED8\r"
    );
    pci_reply(&mut remote_write, 6, &[0x32, 0x23, 0x46]).await;
    assert_eq!(pci_line(&mut remote_read).await, b"\\4606001A230671\r");
    pci_reply(&mut remote_write, 6, &[0x87, 0x23, 0, 0, 0, 0, 0, 0]).await;
    let response = mismatch.await.unwrap();
    assert_eq!(response.status, 408, "{response:?}");
    assert_eq!(
        response.final_text,
        "408 Operation failed: project name save failed - store to unit failed"
    );
    let model = service.model.lock().await;
    let cached = &model.projects["HARNESS"].networks[&254].physical[&6];
    assert!(
        !cached.fields.contains_key("ProjectName"),
        "failed readback must invalidate a stale cached project identity"
    );
    drop(model);
    std::fs::remove_file(path).unwrap();
}

// Optional cmqttd recovery-token tests. Native ACCESS user LOGIN is covered
// separately below; the established one-token form retains `200 OK`, wrong
// token `420`, and `200 OK` LOGOUT for deployed clients.
const AUTH_TOKEN: &[u8] = b"throwaway-loopback-token-0123456789abcdef";

#[tokio::test]
async fn access_native_help_errors_roles_and_redacted_rows_are_exact() {
    let path = state_path();
    let (pci, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let mut client = ClientState::default();

    let help = service.handle(&mut client, "[h] ACCESS").await;
    assert_eq!(
        format_response(&help),
        concat!(
            "[h] 101-Help: ACCESS commands:\n",
            "[h] 101-Help:  ACCESS ? Help for these commands\n",
            "[h] 101-Help:  ACCESS ADD - Add an entry to the access control list\n",
            "[h] 101-Help:  ACCESS DELETE - Deletes an entry from the access control list\n",
            "[h] 101-Help:  ACCESS LIST - List current access control entries\n",
            "[h] 101-Help:  ACCESS LOAD - Load an access control file in as the current access control list.\n",
            "[h] 101 Help:  ACCESS SAVE - Save an access control file from the current access control list.\n",
        )
    );
    assert_eq!(
        service
            .handle(&mut client, "[ha] HELP ACCESS LIST")
            .await
            .final_text,
        "101 Help: List current access control entries"
    );
    assert_eq!(
        service.handle(&mut client, "[q] LOGIN").await.final_text,
        "210 Access level: Clipsal"
    );

    for (command, expected) in [
        (
            "ACCESS ADD",
            "408 Operation failed: Add failed: No access control information given",
        ),
        (
            "ACCESS ADD user only",
            "408 Operation failed: Add failed: More information needed on access control line",
        ),
        (
            "ACCESS ADD user only password",
            "408 Operation failed: Add failed: Insufficient arguments. user requires username, password and level",
        ),
        (
            "ACCESS ADD bogus x Program",
            "408 Operation failed: Add failed: Unknown access control type: bogus",
        ),
    ] {
        assert_eq!(
            service
                .handle(&mut client, &format!("[e] {command}"))
                .await
                .final_text,
            expected,
            "{command}"
        );
    }

    for command in [
        "ACCESS ADD user none-user none-pass TotallyBogus",
        "ACCESS ADD user alice admin-pass Admin ignored-tail",
        "ACCESS ADD user root max-pass Max",
        "ACCESS ADD remote 192.0.2.1 Monitor ignored-tail",
    ] {
        assert_eq!(
            service
                .handle(&mut client, &format!("[a] {command}"))
                .await
                .status,
            200,
            "{command}"
        );
    }
    let list = service
        .handle(&mut client, "[list] ACCESS LIST ignored-tail")
        .await;
    assert_eq!(list.status, 135);
    let wire = format_response(&list);
    assert!(wire.contains("entry=user none-user <redacted> None"));
    assert!(wire.contains("entry=user alice <redacted> Admin"));
    assert!(wire.contains("entry=remote 192.0.2.1 Monitor"));
    assert!(!wire.contains("admin-pass"));
    assert!(!wire.contains("max-pass"), "Clipsal LIST hides Max rows");

    let mut admin = ClientState::default();
    assert_eq!(
        service
            .handle(&mut admin, "[login] LOGIN alice admin-pass")
            .await
            .final_text,
        "211 Access level set to: Admin"
    );
    assert_eq!(
        service
            .handle(&mut admin, "[denied] ACCESS LIST")
            .await
            .final_text,
        "420 Access denied."
    );

    let mut root = ClientState::default();
    assert_eq!(
        service
            .handle(&mut root, "[root] LOGIN root max-pass")
            .await
            .final_text,
        "211 Access level set to: Max"
    );
    assert!(
        format_response(&service.handle(&mut root, "[all] ACCESS LIST").await)
            .contains("entry=user root <redacted> Max")
    );

    let state = std::fs::read_to_string(&path).unwrap();
    assert!(!state.contains("none-pass"));
    assert!(!state.contains("admin-pass"));
    assert!(!state.contains("max-pass"));
    drop(service);
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn access_snapshots_are_sandboxed_atomic_and_durable() {
    let path = state_path();
    let (pci_client, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    assert_eq!(
        service
            .handle(
                &mut client,
                "[add] ACCESS ADD user saved saved-password Admin",
            )
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut client, "[save] ACCESS SAVE policy.txt")
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(
                &mut client,
                "[later] ACCESS ADD user later later-password Monitor",
            )
            .await
            .status,
        200
    );
    assert!(
        format_response(&service.handle(&mut client, "[before] ACCESS LIST").await)
            .contains("user later <redacted> Monitor")
    );
    assert_eq!(
        service
            .handle(&mut client, "[replace] ACCESS SAVE policy.txt ignored")
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut client, "[backup] ACCESS LOAD policy.txt.0")
            .await
            .status,
        200
    );
    let restored = format_response(&service.handle(&mut client, "[after] ACCESS LIST").await);
    assert!(restored.contains("user saved <redacted> Admin"));
    assert!(!restored.contains("user later"));
    assert_eq!(
        service
            .handle(&mut client, "[latest] ACCESS LOAD policy.txt")
            .await
            .status,
        200
    );
    assert!(format_response(
        &service
            .handle(&mut client, "[latest-list] ACCESS LIST")
            .await
    )
    .contains("user later <redacted> Monitor"));
    assert_eq!(
        service
            .handle(&mut client, "[restore-backup] ACCESS LOAD policy.txt.0")
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut client, "[default-save] ACCESS SAVE")
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(
                &mut client,
                "[default-extra] ACCESS ADD user default-extra extra-pass Monitor",
            )
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut client, "[default-load] ACCESS LOAD")
            .await
            .status,
        200
    );
    assert!(!format_response(
        &service
            .handle(&mut client, "[default-list] ACCESS LIST")
            .await
    )
    .contains("default-extra"));

    let before_missing = std::fs::read(&path).unwrap();
    assert_eq!(
        service
            .handle(&mut client, "[missing] ACCESS LOAD absent.txt")
            .await
            .status,
        408
    );
    assert_eq!(std::fs::read(&path).unwrap(), before_missing);
    for command in [
        "ACCESS SAVE ../escape.txt",
        "ACCESS LOAD ../escape.txt",
        "ACCESS SAVE missing/child.txt",
    ] {
        assert_eq!(
            service
                .handle(&mut client, &format!("[path] {command}"))
                .await
                .status,
            408,
            "{command}"
        );
    }
    drop(service);

    let (pci_client, _remote) = pci();
    let restarted = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut login = ClientState::default();
    assert_eq!(
        restarted
            .handle(&mut login, "[login] LOGIN saved saved-password")
            .await
            .final_text,
        "211 Access level set to: Admin"
    );
    drop(restarted);
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn access_login_uses_first_duplicate_and_delete_does_not_demote_session() {
    let path = state_path();
    let (pci, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let mut administrator = ClientState::default();
    for command in [
        "ACCESS ADD user duplicate duplicate-pass Monitor",
        "ACCESS ADD user duplicate duplicate-pass Max",
        "ACCESS ADD user root root-pass Max",
        "ACCESS ADD user noaccess noaccess-pass TotallyBogus",
    ] {
        assert_eq!(
            service
                .handle(&mut administrator, &format!("[add] {command}"))
                .await
                .status,
            200
        );
    }
    assert_eq!(
        service
            .handle(&mut administrator, "[root] LOGIN root root-pass")
            .await
            .final_text,
        "211 Access level set to: Max"
    );
    assert_eq!(
        service
            .handle(&mut administrator, "[delete] ACCESS DELETE 4")
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut administrator, "[still] LOGIN")
            .await
            .final_text,
        "210 Access level: Max"
    );

    let mut deleted = ClientState::default();
    assert_eq!(
        service
            .handle(&mut deleted, "[gone] LOGIN root root-pass")
            .await
            .status,
        422
    );
    let mut duplicate = ClientState::default();
    assert_eq!(
        service
            .handle(&mut duplicate, "[duplicate] LOGIN duplicate duplicate-pass",)
            .await
            .final_text,
        "211 Access level set to: Monitor"
    );
    assert_eq!(
        service
            .handle(&mut duplicate, "[denied] ACCESS LIST")
            .await
            .status,
        420
    );
    let mut noaccess = ClientState::default();
    assert_eq!(
        service
            .handle(&mut noaccess, "[none] LOGIN noaccess noaccess-pass")
            .await
            .final_text,
        "211 Access level set to: None"
    );
    assert_eq!(
        service
            .handle(&mut noaccess, "[none-query] LOGIN")
            .await
            .final_text,
        "210 Access level: None"
    );
    assert_eq!(
        service
            .handle(&mut noaccess, "[none-denied] ACCESS LIST")
            .await
            .status,
        420
    );
    assert_eq!(
        service
            .handle(&mut administrator, "[logout] LOGOUT")
            .await
            .final_text,
        "211 Access level set to: Clipsal"
    );
    drop(service);
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn unresolved_access_add_does_not_mutate_or_poison_new_connections() {
    let path = state_path();
    let (pci, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let server = tokio::spawn(service.clone().serve(listener));
    let (mut first_reader, mut first_writer) = connect_command_session(address).await;
    let reply = command_lines(
        &mut first_reader,
        &mut first_writer,
        "bad",
        "ACCESS ADD interface definitely-nohost.invalid Operate",
    )
    .await;
    assert_eq!(
        reply,
        ["[bad] 408 Operation failed: Add failed: Can not resolve address 'definitely-nohost.invalid'."]
    );

    let (mut second_reader, mut second_writer) = connect_command_session(address).await;
    assert_eq!(
        command_lines(&mut second_reader, &mut second_writer, "q", "LOGIN").await,
        ["[q] 210 Access level: Clipsal"]
    );
    let list = command_lines(&mut second_reader, &mut second_writer, "l", "ACCESS LIST").await;
    assert_eq!(list, ["[l] 135 line=1 entry=interface 127.0.0.1 Clipsal"]);

    server.abort();
    std::fs::remove_file(path).unwrap();
}

fn authed_service() -> (Arc<Service>, PathBuf) {
    let path = state_path();
    let (pci, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    service
        .set_auth_token_hash(crate::auth::sha256(AUTH_TOKEN))
        .expect("fresh service has no auth hash yet");
    (service, path)
}

fn response_text(response: &Response) -> String {
    let mut text = response.lines.join("\n");
    text.push('\n');
    text.push_str(&response.final_text);
    text
}

#[tokio::test]
async fn auth_gate_dormant_exposes_native_login_and_leaves_programming_ungated() {
    let path = state_path();
    let (pci, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let mut client = ClientState::default();
    let login = service.handle(&mut client, "[1] LOGIN anything").await;
    assert_eq!(login.status, 422);
    assert_eq!(
        login.final_text, "422 Username and Password do not match.",
        "one word is not a native username/password pair"
    );
    let logout = service.handle(&mut client, "[2] LOGOUT").await;
    assert_eq!(logout.status, 211);
    assert_eq!(
        logout.final_text, "211 Access level set to: Clipsal",
        "native LOGOUT re-evaluates the connection access level"
    );
    assert_eq!(
        service
            .handle(&mut client, "[3] PP LOCK L //HARNESS/254")
            .await
            .status,
        200
    );
    std::fs::remove_file(path).ok();
}

#[tokio::test]
async fn native_handler_floors_isolate_sessions_and_survive_reconnect() {
    let path = state_path();
    let (pci, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let server = tokio::spawn(service.clone().serve(listener));

    let (mut owner_reader, mut owner_writer) = connect_command_session(address).await;
    for (role, name) in [
        ("None", "none"),
        ("Connect", "connect"),
        ("Monitor", "monitor"),
        ("Operate", "operate"),
        ("Admin", "admin"),
        ("Program", "program"),
    ] {
        let response = command_lines(
            &mut owner_reader,
            &mut owner_writer,
            name,
            &format!("ACCESS ADD user {name} test-{name}-password {role}"),
        )
        .await;
        assert!(
            response.last().unwrap().ends_with("200 OK."),
            "{response:?}"
        );
    }

    let (mut monitor_reader, mut monitor_writer) = connect_command_session(address).await;
    let (mut operate_reader, mut operate_writer) = connect_command_session(address).await;
    let (mut admin_reader, mut admin_writer) = connect_command_session(address).await;
    for (reader, writer, role) in [
        (&mut monitor_reader, &mut monitor_writer, "monitor"),
        (&mut operate_reader, &mut operate_writer, "operate"),
        (&mut admin_reader, &mut admin_writer, "admin"),
    ] {
        let reply = command_lines(
            reader,
            writer,
            role,
            &format!("LOGIN {role} test-{role}-password"),
        )
        .await;
        assert_eq!(
            reply,
            [format!(
                "[{role}] 211 Access level set to: {}",
                role[..1].to_ascii_uppercase() + &role[1..]
            )]
        );
    }
    let (mut connect_reader, mut connect_writer) = connect_command_session(address).await;
    assert_eq!(
        command_lines(
            &mut connect_reader,
            &mut connect_writer,
            "connect",
            "LOGIN connect test-connect-password",
        )
        .await,
        ["[connect] 211 Access level set to: Connect"]
    );
    assert_eq!(
        command_lines(&mut connect_reader, &mut connect_writer, "noop", "NOOP").await,
        ["[noop] 200 OK"]
    );
    assert_eq!(
        command_lines(&mut connect_reader, &mut connect_writer, "event", "EVENT").await,
        ["[event] 420 Access denied."]
    );
    assert_eq!(
        command_lines(&mut connect_reader, &mut connect_writer, "api", "APIVER").await,
        ["[api] 420 Access denied."]
    );
    assert_eq!(
        command_lines(
            &mut monitor_reader,
            &mut monitor_writer,
            "monitor-event",
            "EVENT"
        )
        .await,
        ["[monitor-event] 306 e0s0c0"]
    );
    let help = command_lines(
        &mut monitor_reader,
        &mut monitor_writer,
        "monitor-help",
        "HELP *",
    )
    .await;
    assert_eq!(help, ["[monitor-help] 404 Help topic not found"]);

    // Denied commands still publish native command/response traces, but must
    // neither mutate global configuration nor fan an application event.
    let mut events = service.events.subscribe();
    assert_eq!(
        command_lines(
            &mut operate_reader,
            &mut operate_writer,
            "cfg-denied",
            "CONFIG SET clock.master yes",
        )
        .await,
        ["[cfg-denied] 420 Access denied."]
    );
    assert_native_command_trace(
        &mut events,
        7,
        "[cfg-denied] CONFIG SET clock.master yes",
        &["[cfg-denied] 420 Access denied."],
        None,
    )
    .await;
    assert_eq!(
        command_lines(
            &mut monitor_reader,
            &mut monitor_writer,
            "event-denied",
            "BROADCAST_EVENT SP blocked",
        )
        .await,
        ["[event-denied] 420 Access denied."]
    );
    assert_native_command_trace(
        &mut events,
        5,
        "[event-denied] BROADCAST_EVENT SP blocked",
        &["[event-denied] 420 Access denied."],
        None,
    )
    .await;
    assert_eq!(
        command_lines(
            &mut operate_reader,
            &mut operate_writer,
            "project-denied",
            "PROJECT LIST",
        )
        .await,
        ["[project-denied] 420 Access denied."]
    );
    assert_eq!(
        command_lines(
            &mut monitor_reader,
            &mut monitor_writer,
            "session-denied",
            "SESSION_ID",
        )
        .await,
        ["[session-denied] 420 Access denied."]
    );
    assert_eq!(
        command_lines(
            &mut admin_reader,
            &mut admin_writer,
            "cfg-read",
            "CONFIG GET clock.master",
        )
        .await,
        ["[cfg-read] 303 clock.master=no"]
    );
    assert_eq!(
        command_lines(
            &mut operate_reader,
            &mut operate_writer,
            "broadcast",
            "BROADCAST_EVENT SP accepted",
        )
        .await,
        ["[broadcast] 200 OK."]
    );
    assert_eq!(
        command_lines(
            &mut admin_reader,
            &mut admin_writer,
            "admin-list",
            "PROJECT LIST",
        )
        .await
        .last()
        .unwrap(),
        "[admin-list] 200 OK"
    );
    assert_eq!(
        command_lines(
            &mut admin_reader,
            &mut admin_writer,
            "access-denied",
            "ACCESS LIST",
        )
        .await,
        ["[access-denied] 420 Access denied."]
    );

    // Expanded native floors also apply on the socket path, before missing
    // target resolution, event delivery or any physical command is issued.
    assert_ne!(
        command_lines(
            &mut monitor_reader,
            &mut monitor_writer,
            "tree-admitted",
            "TREE //MISSING",
        )
        .await
        .last()
        .unwrap(),
        "[tree-admitted] 420 Access denied."
    );
    assert_eq!(
        command_lines(
            &mut operate_reader,
            &mut operate_writer,
            "project-dir-denied",
            "PROJECT DIR",
        )
        .await,
        ["[project-dir-denied] 420 Access denied."]
    );
    assert_eq!(
        command_lines(
            &mut admin_reader,
            &mut admin_writer,
            "trigger-denied",
            "TRIGGER EVENT 254/202/1 1",
        )
        .await,
        ["[trigger-denied] 420 Access denied."]
    );
    assert_eq!(
        command_lines(
            &mut admin_reader,
            &mut admin_writer,
            "channel-denied",
            "EVENT_CHANNEL LIST",
        )
        .await,
        ["[channel-denied] 420 Access denied."]
    );
    let (mut program_reader, mut program_writer) = connect_command_session(address).await;
    assert_eq!(
        command_lines(
            &mut program_reader,
            &mut program_writer,
            "program-login",
            "LOGIN program test-program-password",
        )
        .await,
        ["[program-login] 211 Access level set to: Program"]
    );
    assert_ne!(
        command_lines(
            &mut program_reader,
            &mut program_writer,
            "channel-admitted",
            "EVENT_CHANNEL LIST",
        )
        .await
        .last()
        .unwrap(),
        "[channel-admitted] 420 Access denied."
    );
    let mut byte = [0];
    assert!(
        tokio::time::timeout(Duration::from_millis(10), remote.read(&mut byte))
            .await
            .is_err(),
        "an authorization-only probe reached PCI"
    );

    // A failed native user login retains the current role, while a successful
    // lower-role login and LOGOUT change only this command connection.
    assert_eq!(
        command_lines(
            &mut operate_reader,
            &mut operate_writer,
            "wrong",
            "LOGIN operate wrong",
        )
        .await,
        ["[wrong] 422 Username and Password do not match."]
    );
    assert_eq!(
        command_lines(&mut operate_reader, &mut operate_writer, "still", "LOGIN").await,
        ["[still] 210 Access level: Operate"]
    );
    assert_eq!(
        command_lines(
            &mut operate_reader,
            &mut operate_writer,
            "lower",
            "LOGIN none test-none-password",
        )
        .await,
        ["[lower] 211 Access level set to: None"]
    );
    assert_eq!(
        command_lines(&mut operate_reader, &mut operate_writer, "none", "NOOP").await,
        ["[none] 420 Access denied."]
    );
    assert_eq!(
        command_lines(&mut operate_reader, &mut operate_writer, "out", "LOGOUT").await,
        ["[out] 211 Access level set to: Clipsal"]
    );
    assert_eq!(
        command_lines(&mut admin_reader, &mut admin_writer, "independent", "LOGIN").await,
        ["[independent] 210 Access level: Admin"]
    );

    drop(monitor_reader);
    drop(monitor_writer);
    let (mut reconnect_reader, mut reconnect_writer) = connect_command_session(address).await;
    assert_eq!(
        command_lines(
            &mut reconnect_reader,
            &mut reconnect_writer,
            "fresh",
            "LOGIN"
        )
        .await,
        ["[fresh] 210 Access level: Clipsal"]
    );
    assert_eq!(
        command_lines(
            &mut reconnect_reader,
            &mut reconnect_writer,
            "persisted",
            "LOGIN monitor test-monitor-password",
        )
        .await,
        ["[persisted] 211 Access level set to: Monitor"]
    );

    server.abort();
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn expanded_native_handler_floors_deny_before_dispatch_or_mutation() {
    let path = state_path();
    let (pci, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let before = std::fs::read(&path).unwrap();
    let mut events = service.events.subscribe();
    let evidence: serde_json::Value = serde_json::from_str(include_str!(
        "../../../testdata/fixtures/native_cgate_authorization_expansion_probe.json"
    ))
    .unwrap();

    for (path_name, minimum) in crate::access::NATIVE_PROBED_ADDITIONAL_COMMANDS {
        let command = evidence["commands"]
            .as_array()
            .unwrap()
            .iter()
            .filter_map(serde_json::Value::as_str)
            .find(|command| *command == *path_name || command.starts_with(&format!("{path_name} ")))
            .unwrap();
        for level in [
            CgateAccessLevel::None,
            CgateAccessLevel::Connect,
            CgateAccessLevel::Monitor,
            CgateAccessLevel::Operate,
            CgateAccessLevel::Admin,
            CgateAccessLevel::Program,
            CgateAccessLevel::Debug,
            CgateAccessLevel::Clipsal,
        ] {
            if level >= *minimum {
                continue;
            }
            let mut client = ClientState {
                access_level: Some(level),
                ..ClientState::default()
            };
            let reply = service
                .handle(&mut client, &format!("[matrix] {command}"))
                .await;
            assert_eq!(
                reply.final_text,
                "420 Access denied.",
                "{command} at {}: {reply:?}",
                level.name()
            );
            assert_eq!(std::fs::read(&path).unwrap(), before, "{command}");
            assert!(events.try_recv().is_err(), "{command} emitted an event");
            let mut byte = [0];
            assert!(
                tokio::time::timeout(Duration::from_millis(1), remote.read(&mut byte))
                    .await
                    .is_err(),
                "{command} reached PCI"
            );
        }
    }

    // Handler admission is distinct from its later syntax/object checks.
    for (level, command) in [
        (CgateAccessLevel::Monitor, "TREE //MISSING"),
        (CgateAccessLevel::Operate, "LOCK //MISSING"),
        (CgateAccessLevel::Admin, "PROJECT DIR"),
        (CgateAccessLevel::Program, "CGL IMPORT ?"),
    ] {
        let mut client = ClientState {
            access_level: Some(level),
            ..ClientState::default()
        };
        let reply = service
            .handle(&mut client, &format!("[admitted] {command}"))
            .await;
        assert_ne!(reply.final_text, "420 Access denied.", "{command}");
    }

    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn expanded_native_cgl_import_floor_denies_document_before_mutation() {
    let path = state_path();
    let (pci, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let before = std::fs::read(&path).unwrap();
    let mut events = service.events.subscribe();
    let mut admin = ClientState {
        access_level: Some(CgateAccessLevel::Admin),
        ..ClientState::default()
    };
    let reply = service
        .handle_document(&mut admin, "[import] CGL IMPORT HARNESS", "invalid-cgl")
        .await;
    assert_eq!(reply.final_text, "420 Access denied.");
    assert_eq!(std::fs::read(&path).unwrap(), before);
    assert!(events.try_recv().is_err());
    let mut byte = [0];
    assert!(
        tokio::time::timeout(Duration::from_millis(10), remote.read(&mut byte))
            .await
            .is_err(),
        "denied CGL import reached PCI"
    );

    let mut program = ClientState {
        access_level: Some(CgateAccessLevel::Program),
        ..ClientState::default()
    };
    let reply = service
        .handle_document(&mut program, "[import] CGL IMPORT HARNESS", "invalid-cgl")
        .await;
    assert_ne!(reply.final_text, "420 Access denied.");
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn dbsetxml_native_admin_floor_and_recovery_admission_precede_document_mutation() {
    let path = state_path();
    let (pci, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let target = "[doc] DBSETXML //HARNESS/254/p/5/TagName";
    let before = std::fs::read(&path).unwrap();

    let mut monitor = ClientState {
        access_level: Some(CgateAccessLevel::Monitor),
        ..ClientState::default()
    };
    assert_eq!(
        service
            .handle_document(&mut monitor, target, "DeniedName")
            .await
            .final_text,
        "420 Access denied."
    );
    assert_eq!(std::fs::read(&path).unwrap(), before);

    let mut recovery = ClientState {
        access_level: Some(CgateAccessLevel::Admin),
        recovery_only: true,
        ..ClientState::default()
    };
    assert_eq!(
        service
            .handle_document(&mut recovery, target, "DeniedName")
            .await
            .final_text,
        "420 LOGIN required"
    );
    assert_eq!(std::fs::read(&path).unwrap(), before);

    let mut admin = ClientState {
        access_level: Some(CgateAccessLevel::Admin),
        ..ClientState::default()
    };
    let allowed = service
        .handle_document(&mut admin, target, "AllowedName")
        .await;
    assert_eq!(allowed.status, 200, "{allowed:?}");
    assert_ne!(std::fs::read(&path).unwrap(), before);
    assert!(
        tokio::time::timeout(Duration::from_millis(20), remote.read_u8())
            .await
            .is_err(),
        "local DBSETXML must not write to PCI"
    );
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn auth_wrong_secret_denied_and_gate_holds() {
    let (service, path) = authed_service();
    let mut client = ClientState::default();
    // Wrong recovery token retains the deployed 420 contract. Native
    // two-argument user failures use the separately tested 422 response.
    let denied = service
        .handle(&mut client, "[1] LOGIN wrong-secret-value")
        .await;
    assert_eq!(denied.status, 420);
    assert!(
        denied.final_text.contains("LOGIN failed"),
        "unexpected denial text: {denied:?}"
    );
    // Programming verbs stay denied while unauthenticated.
    for command in [
        "[2] PP LOCK L //HARNESS/254",
        "[3] PP START S L",
        "[4] PP NEW S //HARNESS/254/p/5",
        "[5] PP SET S Field value",
        "[6] PP SAVE S //HARNESS/254/p/5",
        "[7] PP SAVE_TO_SOURCE S",
        "[8] PP LOAD S //HARNESS/254/p/5",
        "[9] PROJECT NEW AUTHTEST",
        "[10] PROJECT SAVE",
        "[11] DBSETSAFE //HARNESS/254/p/5/TagName Changed",
        "[12] SET //HARNESS/254/p/5 Address 6",
        "[13] LABEL CLEAREDLT //HARNESS/254/p/5",
        "[14] LABEL CLEAR //HARNESS/254/56 5",
        "[15] LABEL KFIGET //HARNESS/254/56 5",
        "[16] LABEL KFISET //HARNESS/254/56 5 0 1 2 3 4 5 6 7",
        "[17] SCENE RECORD house evening",
        "[18] DO //HARNESS/254/p/5 FactoryDefault",
        "[19] NET UNRAVELUNIT //HARNESS/254 255 MATCHDB",
        "[20] NET SET_PROJECT_IDENTIFY //HARNESS/254 TEST",
        "[21] PROJECT ARCHIVE HARNESS slot",
        "[22] PROJECT RESTORE RESTORED slot",
        "[23] PROJECT RENAME OTHER RENAMED",
        "[24] REPOSITORY USE 1",
        "[25] PROJECT COPY HARNESS COPY",
        "[26] PROJECT DELETE OTHER",
        "[27] PORT CNISCAN 127.0.0.1 FAST",
        "[28] PORT CNISCAN2 127.0.0.1 127.0.0.1 FAST",
        "[29] PORT PROBE socket 127.0.0.1:1",
        "[30] PORT REFRESH",
        "[31] NEW GROUP //HARNESS/254/56/44",
        "[32] BROADCAST_EVENT SP auth-test",
        "[33] PP WRITE_PATCH //HARNESS/254/p/5 01",
        "[34] PROGRAMMER TRIGGER Missing START",
        "[35] DEPLOY_QUEUE ADD Missing",
    ] {
        let response = service.handle(&mut client, command).await;
        assert_eq!(response.status, 420, "{command}: {response:?}");
        assert!(
            response.final_text.contains("LOGIN required"),
            "{command}: {response:?}"
        );
    }
    std::fs::remove_file(path).ok();
}

#[tokio::test]
async fn auth_login_unlocks_programming_and_logout_relocks() {
    let (service, path) = authed_service();
    let mut client = ClientState::default();
    assert_eq!(
        service
            .handle(&mut client, "[1] PP LOCK L //HARNESS/254")
            .await
            .status,
        420
    );
    let ok = service
        .handle(
            &mut client,
            "[2] LOGIN throwaway-loopback-token-0123456789abcdef",
        )
        .await;
    assert_eq!(ok.status, 200);
    assert_eq!(
        service
            .handle(&mut client, "[3] PP LOCK L //HARNESS/254")
            .await
            .status,
        200
    );
    assert_eq!(
        service.handle(&mut client, "[4] PP START S L").await.status,
        200
    );
    assert_eq!(service.handle(&mut client, "[5] LOGOUT").await.status, 200);
    // Session-local flag cleared: programming denied again.
    assert_eq!(
        service
            .handle(&mut client, "[6] PP LOCK M //HARNESS/254")
            .await
            .status,
        420
    );
    std::fs::remove_file(path).ok();
}

#[tokio::test]
async fn auth_second_connection_unaffected_by_first() {
    let (service, path) = authed_service();
    let mut first = ClientState::default();
    let mut second = ClientState::default();
    assert_eq!(
        service
            .handle(
                &mut first,
                "[1] LOGIN throwaway-loopback-token-0123456789abcdef"
            )
            .await
            .status,
        200
    );
    // Second connection is still unauthenticated.
    assert_eq!(
        service
            .handle(&mut second, "[2] PP LOCK L //HARNESS/254")
            .await
            .status,
        420
    );
    // First connection logging out does not touch the second, and the
    // second can still authenticate independently.
    assert_eq!(service.handle(&mut first, "[3] LOGOUT").await.status, 200);
    assert_eq!(
        service
            .handle(
                &mut second,
                "[4] LOGIN throwaway-loopback-token-0123456789abcdef"
            )
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut second, "[5] PP LOCK L //HARNESS/254")
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut first, "[6] PP LOCK M //HARNESS/254")
            .await
            .status,
        420
    );
    std::fs::remove_file(path).ok();
}

#[tokio::test]
async fn auth_failed_login_clears_flag_and_rejects_bad_arity() {
    let (service, path) = authed_service();
    let mut client = ClientState::default();
    assert_eq!(
        service
            .handle(
                &mut client,
                "[1] LOGIN throwaway-loopback-token-0123456789abcdef"
            )
            .await
            .status,
        200
    );
    // A failed LOGIN de-authenticates the connection.
    assert_eq!(
        service.handle(&mut client, "[2] LOGIN wrong").await.status,
        420
    );
    assert_eq!(
        service
            .handle(&mut client, "[3] PP LOCK L //HARNESS/254")
            .await
            .status,
        420
    );
    // Bare LOGIN is the native access-level query. Two or more arguments are
    // a native username/password login (and therefore 422 when unmatched).
    assert_eq!(service.handle(&mut client, "[4] LOGIN").await.status, 210);
    assert_eq!(
        service.handle(&mut client, "[5] LOGIN a b").await.status,
        422
    );
    // A failed native user LOGIN also clears the optional mutation gate:
    // re-login with the token, send an unmatched user pair, and the gate holds.
    assert_eq!(
        service
            .handle(
                &mut client,
                "[6] LOGIN throwaway-loopback-token-0123456789abcdef"
            )
            .await
            .status,
        200
    );
    assert_eq!(
        service.handle(&mut client, "[7] LOGIN a b").await.status,
        422
    );
    assert_eq!(
        service
            .handle(&mut client, "[8] PP LOCK L //HARNESS/254")
            .await
            .status,
        420
    );
    std::fs::remove_file(path).ok();
}

#[tokio::test]
async fn auth_reads_and_bus_control_stay_open() {
    // Read-only verbs and bus-control paths never require LOGIN: the gate
    // covers durable/unit/session mutation only.
    let (service, path) = authed_service();
    let mut client = ClientState::default();
    assert_eq!(
        service
            .handle(&mut client, "[1] CMQTT CAPABILITIES")
            .await
            .status,
        200
    );
    assert_eq!(
        service.handle(&mut client, "[2] PROJECT LIST").await.status,
        200
    );
    assert_eq!(
        service
            .handle(&mut client, "[3] PROJECT USE HARNESS")
            .await
            .status,
        200
    );
    // The durable group exists in the project database, so its default level
    // remains readable without LOGIN even before a live bus observation.
    assert_eq!(
        service
            .handle(&mut client, "[4] GET //HARNESS/254/56/1 level")
            .await
            .status,
        300
    );
    // PP session reads are not gated (a missing session answers from the
    // model, never 420).
    let info = service.handle(&mut client, "[5] PP INFO nosuch").await;
    assert_ne!(info.status, 420, "{info:?}");
    let get = service.handle(&mut client, "[6] PP GET nosuch").await;
    assert_ne!(get.status, 420, "{get:?}");
    std::fs::remove_file(path).ok();
}

#[tokio::test]
async fn auth_secret_never_in_responses_or_events() {
    let (service, path) = authed_service();
    let mut events = service.events.subscribe();
    let mut client = ClientState::default();
    let attempts = [
        "[1] LOGIN wrong-secret-value",
        "[2] PP LOCK L //HARNESS/254",
        "[3] LOGIN throwaway-loopback-token-0123456789abcdef",
        "[4] LOGOUT",
    ];
    for command in attempts {
        let response = service.handle(&mut client, command).await;
        let text = response_text(&response);
        assert!(
            !text.contains("throwaway-loopback-token-0123456789abcdef"),
            "{command} echoed the secret: {text:?}"
        );
        assert!(
            !text.contains("wrong-secret-value"),
            "{command} echoed the candidate: {text:?}"
        );
    }
    // Neither failed logins, denials, LOGIN success nor LOGOUT emit events
    // (and therefore can never carry secret material on the event channel).
    assert!(
        events.try_recv().is_err(),
        "auth traffic must not emit bus events"
    );
    std::fs::remove_file(path).ok();
}

#[tokio::test]
async fn auth_db_project_and_scene_mutations_gate_together() {
    // The gate covers every local path that mutates durable state: DB
    // verbs, PROJECT lifecycle verbs and SCENE RECORD (persisted
    // snapshots). Post-login they serve locally again.
    let (service, path) = authed_service();
    let mut client = ClientState::default();
    assert_eq!(
        service
            .handle(
                &mut client,
                "[1] DBSETSAFE //HARNESS/254/p/5/TagName Changed"
            )
            .await
            .status,
        420
    );
    assert_eq!(
        service
            .handle(
                &mut client,
                "[2] LOGIN throwaway-loopback-token-0123456789abcdef"
            )
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(
                &mut client,
                "[3] DBSETSAFE //HARNESS/254/p/5/TagName Changed"
            )
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut client, "[4] PROJECT NEW AUTHTEST")
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(
                &mut client,
                "[5] PROJECT ARCHIVE AUTHTEST cmqttd:auth-snapshot",
            )
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut client, "[6] PROJECT RENAME AUTHTEST AUTHRENAMED")
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(
                &mut client,
                "[7] PROJECT RESTORE AUTHRESTORED cmqttd:auth-snapshot",
            )
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut client, "[8] PROJECT COPY AUTHRENAMED COPYAUTH")
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut client, "[9] PROJECT DELETE COPYAUTH")
            .await
            .status,
        200
    );
    std::fs::remove_file(path).ok();
}

#[tokio::test]
async fn project_archive_restore_and_secondary_rename_are_durable_database_only() {
    let path = state_path();
    let (pci, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci.clone(), None).unwrap();
    let mut client = ClientState::default();
    for command in [
        "[1] PROJECT NEW AUX",
        "[2] DBCREATENET 1 Auxiliary Cni loopback",
        "[3] DBADDSAFE //AUX/1 Unit 20 Original",
        "[4] DBSETSAFE //AUX/1/p/20/TagName Archived",
        "[4a] DBSETSAFE //AUX/1/p/20/UnitName Unrelated",
    ] {
        let response = service.handle(&mut client, command).await;
        assert_eq!(response.status, 200, "{command}: {response:?}");
    }
    let archived = service
        .handle(&mut client, "[5] PROJECT ARCHIVE AUX cmqttd:archive-one")
        .await;
    assert_eq!(archived.final_text, "200 OK.");
    assert_eq!(
        service
            .handle(
                &mut client,
                "[6] DBSETSAFE //AUX/1/p/20/TagName ChangedAfterArchive"
            )
            .await
            .status,
        200
    );
    let renamed = service
        .handle(&mut client, "[7] PROJECT RENAME AUX RENAMED")
        .await;
    assert_eq!(renamed.final_text, "200 OK.");
    assert_eq!(client.current.as_deref(), Some("RENAMED"));
    let restored = service
        .handle(
            &mut client,
            "[8] PROJECT RESTORE RESTORED cmqttd:archive-one",
        )
        .await;
    assert_eq!(restored.final_text, "200 OK.");
    {
        let model = service.model.lock().await;
        let original = &model.projects["RENAMED"].networks[&1].units[&20];
        let restored = &model.projects["RESTORED"].networks[&1];
        assert_eq!(original.fields["TagName"], "ChangedAfterArchive");
        assert_eq!(restored.units[&20].fields["TagName"], "Archived");
        assert_eq!(restored.units[&20].fields["UnitName"], "Unrelated");
        assert!(restored.physical.is_empty());
        assert!(restored.levels.is_empty());
        assert_eq!(restored.state, NetworkState::Closed);
        assert!(model.projects.contains_key("HARNESS"));
    }

    drop(service);
    let restarted = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let mut restarted_client = ClientState::default();
    assert_eq!(
        restarted
            .handle(
                &mut restarted_client,
                "[9] PROJECT RESTORE RESTORED2 cmqttd:archive-one"
            )
            .await
            .final_text,
        "200 OK."
    );
    let model = restarted.model.lock().await;
    assert_eq!(
        model.projects["RESTORED2"].networks[&1].units[&20].fields["TagName"],
        "Archived"
    );
    assert!(model.projects["RESTORED2"].networks[&1].physical.is_empty());
    drop(model);
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn project_copy_and_secondary_delete_are_durable_database_only() {
    let path = state_path();
    let (pci, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci.clone(), None).unwrap();
    let mut client = ClientState::default();
    for command in [
        "[1] PROJECT NEW AUX",
        "[2] DBCREATENET 1 Auxiliary Cni loopback",
        "[3] DBADDSAFE //AUX/1 Unit 20 Original",
        "[4] DBSETSAFE //AUX/1/p/20/TagName Copied",
        "[5] DBSETSAFE //AUX/1/p/20/UnitName Unrelated",
    ] {
        let response = service.handle(&mut client, command).await;
        assert_eq!(response.status, 200, "{command}: {response:?}");
    }
    let level = service
        .handle(&mut client, "[6] DBADDSAFE //AUX/1/56/1 Level 7 Seven")
        .await;
    let level_oid = level
        .final_text
        .strip_prefix("301 OID=")
        .expect("level OID")
        .to_string();
    assert_eq!(
        service
            .handle(&mut client, &format!("[7] DBSETSAFE !{level_oid}/Value 77"),)
            .await
            .status,
        200
    );
    let source_unit_oid = {
        let mut model = service.model.lock().await;
        let network = model
            .projects
            .get_mut("AUX")
            .unwrap()
            .networks
            .get_mut(&1)
            .unwrap();
        let unit = network.units[&20].clone();
        let source_unit_oid = unit.oid.clone();
        network.physical.insert(20, unit);
        network.levels.insert((56, 1), 99);
        network.state = NetworkState::Open;
        source_unit_oid
    };

    let copied = service
        .handle(&mut client, "[8] PROJECT COPY AUX COPY")
        .await;
    assert_eq!(copied.final_text, "200 OK.");
    assert_eq!(client.current.as_deref(), Some("AUX"));
    {
        let model = service.model.lock().await;
        let source = &model.projects["AUX"].networks[&1];
        let copy = &model.projects["COPY"].networks[&1];
        assert_eq!(copy.units[&20].fields["TagName"], "Copied");
        assert_eq!(copy.units[&20].fields["UnitName"], "Unrelated");
        assert_eq!(copy.units[&20].oid, source_unit_oid);
        assert!(copy.physical.is_empty());
        assert!(copy.levels.is_empty());
        assert_eq!(copy.state, NetworkState::Closed);
        assert_eq!(source.physical[&20].oid, source_unit_oid);
        assert_eq!(source.levels[&(56, 1)], 99);
        assert_eq!(source.state, NetworkState::Open);
        assert_eq!(
            model
                .db_levels
                .values()
                .filter(|level| level.oid == level_oid)
                .count(),
            2
        );
        assert!(model.projects.contains_key("HARNESS"));
    }
    assert_eq!(
        service
            .handle(
                &mut client,
                "[9] DBSETSAFE //COPY/1/p/20/TagName ChangedCopy",
            )
            .await
            .status,
        200
    );
    assert_eq!(
        service.model.lock().await.projects["AUX"].networks[&1].units[&20].fields["TagName"],
        "Copied"
    );

    drop(service);
    let restarted = Service::new(&fixture(), None, path.clone(), pci.clone(), None).unwrap();
    assert_eq!(
        restarted.model.lock().await.projects["COPY"].networks[&1].units[&20].fields["TagName"],
        "ChangedCopy"
    );
    let mut restarted_client = ClientState::default();
    assert_eq!(
        restarted
            .handle(
                &mut restarted_client,
                &format!("[9a] DBGET !{level_oid}/Value"),
            )
            .await
            .status,
        401
    );
    assert_eq!(
        restarted
            .handle(
                &mut restarted_client,
                &format!("[9b] DBSETSAFE !{level_oid}/Value 88"),
            )
            .await
            .status,
        401
    );
    assert_eq!(
        restarted
            .handle(&mut restarted_client, "[10] PROJECT USE COPY")
            .await
            .status,
        200
    );
    assert_eq!(
        restarted
            .handle(
                &mut restarted_client,
                &format!("[10a] DBGET !{level_oid}/Value"),
            )
            .await
            .final_text,
        format!("342 !{level_oid}/Value=77")
    );
    let deleted = restarted
        .handle(&mut restarted_client, "[11] PROJECT DELETE COPY")
        .await;
    assert_eq!(deleted.final_text, "200 OK.");
    assert_eq!(restarted_client.current, None);
    assert!(!restarted.model.lock().await.projects.contains_key("COPY"));
    drop(restarted);

    let second_restart = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let model = second_restart.model.lock().await;
    assert!(!model.projects.contains_key("COPY"));
    assert!(model.projects.contains_key("AUX"));
    assert!(model.projects.contains_key("HARNESS"));
    assert_eq!(
        model
            .db_levels
            .values()
            .filter(|level| level.oid == level_oid)
            .count(),
        1
    );
    drop(model);
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn local_catalog_calculator_and_cgl_exchange_are_exact_and_durable() {
    let path = state_path();
    let unitspec = repository_transform_unitspec();
    let (pci, mut remote) = pci();
    let service = Service::new(
        &fixture(),
        None,
        path.clone(),
        pci.clone(),
        Some(unitspec.clone()),
    )
    .unwrap();
    let mut client = ClientState::default();

    let applications = service
        .handle(&mut client, "[catalog] APPLICATIONS GET_CATALOG")
        .await;
    assert_eq!(applications.status, 344);
    assert_eq!(
        applications.lines,
        [
            "343-Begin XML Snippet",
            "347-<?xml version=\"1.0\"?>",
            "347-<Applications><Application Address=\"56\" Name=\"Lighting\"/></Applications>",
        ]
    );
    assert_eq!(applications.final_text, "344 End XML Snippet");

    for command in [
        "[u5-catalog] DBSETSAFE //HARNESS/254/p/5/CatalogNumber 5034N",
        "[u5-type] DBSETSAFE //HARNESS/254/p/5/UnitType KEY4",
        "[u6] DBADDSAFE //HARNESS/254 Unit 6 Burden",
        "[u6-catalog] DBSETSAFE //HARNESS/254/p/6/CatalogNumber 5500BUR",
        "[u6-type] DBSETSAFE //HARNESS/254/p/6/UnitType BURDEN",
        "[u7] DBADDSAFE //HARNESS/254 Unit 7 Supply",
        "[u7-catalog] DBSETSAFE //HARNESS/254/p/7/CatalogNumber 5500PS",
        "[u7-type] DBSETSAFE //HARNESS/254/p/7/UnitType POWER",
    ] {
        let response = service.handle(&mut client, command).await;
        assert_eq!(response.status, 200, "{command}: {response:?}");
    }
    let calculation = service
        .handle(
            &mut client,
            "[calculator] CALCULATOR TEST //HARNESS/254 ignored",
        )
        .await;
    assert_eq!(calculation.status, 134);
    assert_eq!(
        calculation.lines,
        [
            "134-result: OK",
            "134-current_supply(mA)=350",
            "134-current_consumption(mA)=18",
            "134-impedance(ohms)=944.0",
            "134-units_calculated=3",
        ]
    );
    assert_eq!(calculation.final_text, "134 units_not_calculated=0");

    let document = r#"{"cglVersion":"1.1","localNetwork":254,"networks":[{"address":254,"applications":[{"address":57,"type":57,"name":"Local Application","groups":[{"address":2,"name":"Hall","levels":[{"address":255,"name":"On"}]}]}]}]}"#;
    let imported = service
        .handle_document(&mut client, "[import] CGL IMPORT HARNESS", document)
        .await;
    assert_eq!(imported.status, 200, "{imported:?}");
    assert!(imported
        .lines
        .iter()
        .any(|line| line.contains("Created new application 254/57")));
    assert_eq!(imported.final_text, "200 OK.");
    let exported = service
        .handle(&mut client, "[export] CGL EXPORT HARNESS 254 57")
        .await;
    assert_eq!(exported.status, 344);
    assert_eq!(
        exported.final_text,
        "344 End CGL snippet [numberOfExportedObjects:3]"
    );
    let exported_json: serde_json::Value =
        serde_json::from_str(exported.lines[1].strip_prefix("347-").unwrap()).unwrap();
    assert_eq!(
        exported_json["networks"][0]["applications"][0]["groups"][0]["name"],
        "Hall"
    );
    assert!(
        tokio::time::timeout(Duration::from_millis(20), remote.read_u8())
            .await
            .is_err()
    );

    drop(service);
    let restarted =
        Service::new(&fixture(), None, path.clone(), pci, Some(unitspec.clone())).unwrap();
    let mut restarted_client = ClientState::default();
    let exported = restarted
        .handle(
            &mut restarted_client,
            "[restart-export] CGL EXPORT HARNESS 254 57",
        )
        .await;
    let exported_json: serde_json::Value =
        serde_json::from_str(exported.lines[1].strip_prefix("347-").unwrap()).unwrap();
    assert_eq!(
        exported_json["networks"][0]["applications"][0]["groups"][0]["levels"][0]["name"],
        "On"
    );

    std::fs::remove_file(path).unwrap();
    std::fs::remove_dir_all(unitspec).unwrap();
}

#[tokio::test]
async fn administrative_guards_keep_configured_binding_and_reject_unknown_transform_inputs() {
    let path = state_path();
    let before = std::fs::read(&path).ok();
    let (pci, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let state_before = std::fs::read(&path).unwrap();
    let mut client = ClientState::default();
    let configured = service
        .handle(&mut client, "[1] PROJECT RENAME HARNESS MOVED")
        .await;
    assert_eq!(configured.status, 408);
    assert!(configured
        .final_text
        .contains("configured hardware project"));
    assert!(service.model.lock().await.projects.contains_key("HARNESS"));
    assert_eq!(
        serde_json::from_slice::<serde_json::Value>(&std::fs::read(&path).unwrap()).unwrap(),
        serde_json::from_slice::<serde_json::Value>(&state_before).unwrap()
    );
    assert_eq!(
        service
            .handle(&mut client, "[2] PROJECT RENAME HARNESS")
            .await
            .status,
        400
    );
    let vendor_path = path.with_extension("vendor.zip");
    for command in [
        format!("[2a] PROJECT ARCHIVE HARNESS {}", vendor_path.display()),
        format!("[2b] PROJECT RESTORE COPY {}", vendor_path.display()),
    ] {
        let response = service.handle(&mut client, &command).await;
        assert_eq!(response.status, 408, "{command}: {response:?}");
        assert!(response.final_text.contains("cmqttd: archive key"));
    }
    assert!(!vendor_path.exists());
    let configured_delete = service
        .handle(&mut client, "[3] PROJECT DELETE HARNESS")
        .await;
    assert_eq!(configured_delete.status, 408);
    assert!(configured_delete
        .final_text
        .contains("configured hardware project"));
    assert!(service.model.lock().await.projects.contains_key("HARNESS"));
    for (command, status) in [
        ("[5] PROJECT REPAIR HARNESS", 200),
        ("[6] REPOSITORY USE 1", 200),
        ("[7] TRANSFORM MIGRATE_SQL project.db", 408),
        ("[8] TRANSFORM PROJECT HARNESS", 200),
        ("[9] TRANSFORM SQL_TO_XML project.db", 408),
        ("[10] TRANSFORM SQL_TO_XML_CGATE2 project.db", 408),
        ("[11] TRANSFORM XML_TO_SQL project.xml", 408),
    ] {
        let response = service.handle(&mut client, command).await;
        assert_eq!(response.status, status, "{command}: {response:?}");
    }
    assert_eq!(
        serde_json::from_slice::<serde_json::Value>(&std::fs::read(&path).unwrap()).unwrap(),
        serde_json::from_slice::<serde_json::Value>(&state_before).unwrap()
    );
    assert_eq!(
        service
            .handle(&mut client, "[12] CGL EXPORT HARNESS * *")
            .await
            .status,
        344
    );
    drop(service);
    if before.is_none() {
        std::fs::remove_file(path).unwrap();
    }
}

#[tokio::test]
async fn repository_list_is_one_exact_read_only_cmqttd_descriptor() {
    let path = state_path();
    let (pci, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let mut client = ClientState::default();
    let response = service.handle(&mut client, "[repo] REPOSITORY LIST").await;
    assert_eq!(response.status, 123);
    assert!(response.lines.is_empty());
    assert_eq!(
        response.final_text,
        format!(
            "123 index=1 type=cmqttd-json path={} current=yes",
            path.display()
        )
    );
    assert_eq!(
        service
            .handle(&mut client, "[bad] REPOSITORY LIST extra")
            .await
            .final_text,
        "400 REPOSITORY LIST takes no arguments"
    );
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn document_semantics_validate_before_mutation_and_remain_authenticated() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    let oid = service.model.lock().await.projects["HARNESS"].networks[&254].units[&5]
        .oid
        .clone();
    let replacement = format!(
        "<Unit source=\"service-test\"><OID>{oid}</OID><Address>5</Address><TagName>Document eDLT</TagName><UnitType>KEYGL5</UnitType><UnitName>Document eDLT</UnitName><FirmwareVersion>5.5.00</FirmwareVersion><PP Name=\"StaticTextString0\" Value=\"Replaced\"/><Opaque><Nested>kept</Nested></Opaque></Unit>"
    );
    let dbset = service
        .handle_document(
            &mut client,
            "[doc] DBSETXML //HARNESS/254/p/5",
            &replacement,
        )
        .await;
    assert_eq!(dbset.status, 301, "{dbset:?}");
    assert_eq!(dbset.final_text, format!("301 OID={oid}"));
    assert!(
        tokio::time::timeout(Duration::from_millis(20), remote.read_u8())
            .await
            .is_err(),
        "DBSETXML must not write to PCI"
    );
    let state_after = std::fs::read(&path).unwrap();
    let invalid = service
        .handle_document(&mut client, "[cgl] CGL IMPORT HARNESS", "opaque\n")
        .await;
    assert_eq!(invalid.status, 400, "{invalid:?}");
    assert!(invalid.final_text.contains("Invalid CGL"));
    assert_eq!(
        service.model.lock().await.projects["HARNESS"].networks[&254].units[&5].fields["TagName"],
        "Document eDLT"
    );
    assert_eq!(std::fs::read(&path).unwrap(), state_after);
    let xml = service
        .handle(&mut client, "[xml] DBGETXML //HARNESS/254/p/5")
        .await;
    assert!(xml.lines[0].contains("<TagName>Document eDLT</TagName>"));
    assert!(xml.lines[0].contains("<PP Name=\"StaticTextString0\" Value=\"Replaced\"/>"));
    assert!(!xml.lines[0].contains("source=\"service-test\""));
    assert!(!xml.lines[0].contains("<Nested>kept</Nested>"));
    drop(service);
    let (restart_pci, _remote) = pci();
    let restarted = Service::new(&fixture(), None, path.clone(), restart_pci, None).unwrap();
    let restarted_xml = restarted
        .handle(
            &mut ClientState::default(),
            "[restart] DBGETXML //HARNESS/254/p/5",
        )
        .await;
    assert!(restarted_xml.lines[0].contains("<TagName>Document eDLT</TagName>"));
    assert!(restarted_xml.lines[0].contains("<PP Name=\"StaticTextString0\" Value=\"Replaced\"/>"));
    assert!(!restarted_xml.lines[0].contains("<Nested>kept</Nested>"));
    let mut archive_client = ClientState::default();
    assert_eq!(
        restarted
            .handle(
                &mut archive_client,
                "[archive] PROJECT ARCHIVE HARNESS cmqttd:typed-unit",
            )
            .await
            .status,
        200
    );
    assert_eq!(
        restarted
            .handle(
                &mut archive_client,
                "[restore] PROJECT RESTORE COPY cmqttd:typed-unit",
            )
            .await
            .status,
        200
    );
    assert_eq!(
        restarted
            .handle(&mut archive_client, "[use-copy] PROJECT USE COPY")
            .await
            .status,
        200
    );
    let restored_copy = restarted
        .handle(&mut archive_client, "[copy-xml] DBGETXML //COPY/254/p/5")
        .await;
    assert!(restored_copy.lines[0].contains("<TagName>Document eDLT</TagName>"));
    assert!(restored_copy.lines[0].contains("<PP Name=\"StaticTextString0\" Value=\"Replaced\"/>"));
    assert!(!restored_copy.lines[0].contains("source=\"service-test\""));
    assert!(!restored_copy.lines[0].contains("<Nested>kept</Nested>"));
    drop(restarted);
    let (second_restart_pci, _remote) = pci();
    let second_restart =
        Service::new(&fixture(), None, path.clone(), second_restart_pci, None).unwrap();
    let mut copy_client = ClientState::default();
    assert_eq!(
        second_restart
            .handle(&mut copy_client, "[select-copy] PROJECT USE COPY")
            .await
            .status,
        200
    );
    let durable_copy = second_restart
        .handle(&mut copy_client, "[durable-copy] DBGETXML //COPY/254/p/5")
        .await;
    assert!(durable_copy.lines[0].contains("<TagName>Document eDLT</TagName>"));
    assert!(durable_copy.lines[0].contains("<PP Name=\"StaticTextString0\" Value=\"Replaced\"/>"));
    assert!(!durable_copy.lines[0].contains("source=\"service-test\""));
    assert!(!durable_copy.lines[0].contains("<Nested>kept</Nested>"));

    let (authed, auth_path) = authed_service();
    let mut authenticated = ClientState::default();
    for line in ["[1] DBSETXML //HARNESS/254/p/5", "[2] CGL IMPORT HARNESS"] {
        assert_eq!(
            authed
                .handle_document(&mut authenticated, line, "opaque\n")
                .await
                .status,
            420,
            "{line}"
        );
    }
    assert_eq!(
        authed
            .handle(
                &mut authenticated,
                "[3] LOGIN throwaway-loopback-token-0123456789abcdef",
            )
            .await
            .status,
        200
    );
    let auth_oid = authed.model.lock().await.projects["HARNESS"].networks[&254].units[&5]
        .oid
        .clone();
    let authenticated_replacement = format!(
        "<Unit><OID>{auth_oid}</OID><Address>5</Address><TagName>Authenticated</TagName><UnitType>KEYGL5</UnitType><UnitName>Authenticated</UnitName><FirmwareVersion>5.5.00</FirmwareVersion></Unit>"
    );
    assert_eq!(
        authed
            .handle_document(
                &mut authenticated,
                "[4] DBSETXML //HARNESS/254/p/5",
                &authenticated_replacement,
            )
            .await
            .status,
        301
    );
    assert_eq!(
        authed
            .handle_document(&mut authenticated, "[5] CGL IMPORT HARNESS", "opaque\n",)
            .await
            .status,
        400
    );
    std::fs::remove_file(path).unwrap();
    std::fs::remove_file(auth_path).unwrap();
}

#[tokio::test]
async fn duplicate_oid_units_keep_independent_documents_through_service_restart() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    assert_eq!(
        service
            .handle(&mut client, "[1] PROJECT NEW XDUP")
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut client, "[2] PROJECT USE XDUP")
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut client, "[3] DBCREATENET 253 Local Cni 127.0.0.1:1")
            .await
            .status,
        200
    );
    let initial = service.handle(&mut client, "[4] DBGETXML //XDUP/253").await;
    let parsed =
        roxmltree::Document::parse(initial.lines[0].strip_prefix("347-").unwrap()).unwrap();
    let oid = |node: roxmltree::Node<'_, '_>| {
        node.children()
            .find(|child| child.has_tag_name("OID"))
            .unwrap()
            .text()
            .unwrap()
            .to_string()
    };
    let network_oid = oid(parsed.root_element());
    let interface_oid = oid(parsed
        .descendants()
        .find(|node| node.has_tag_name("Interface"))
        .unwrap());
    let shared = "11111111-1111-4111-8111-111111111111";
    let document = format!(
        "<Network><OID>{network_oid}</OID><TagName>Local</TagName><Address>253</Address><NetworkNumber>253</NetworkNumber><Interface><OID>{interface_oid}</OID><InterfaceType>Cni</InterfaceType><InterfaceAddress>127.0.0.1:1</InterfaceAddress></Interface><Application><OID>{shared}</OID><TagName>Lighting</TagName><Address>56</Address></Application><Unit><OID>{shared}</OID><TagName>First</TagName><Address>20</Address><UnitType>KEYE1</UnitType><UnitName>First room</UnitName><FirmwareVersion>1.2.67</FirmwareVersion><PP Name=\"UnitAddress\" Value=\"20\"/></Unit><Unit><OID>{shared}</OID><TagName>Second</TagName><Address>21</Address><UnitType>KEYE1</UnitType><UnitName>Second room</UnitName><FirmwareVersion>1.2.68</FirmwareVersion><PP Name=\"UnitAddress\" Value=\"21\"/></Unit></Network>"
    );
    assert_eq!(
        service
            .handle_document(&mut client, "[5] DBSETXML //XDUP/253", &document)
            .await
            .status,
        301
    );
    let first = service
        .handle(&mut client, "[6] DBGETXML //XDUP/253/p/20")
        .await
        .lines[0]
        .clone();
    let second = service
        .handle(&mut client, "[7] DBGETXML //XDUP/253/p/21")
        .await
        .lines[0]
        .clone();
    assert!(first.contains("<PP Name=\"UnitAddress\" Value=\"20\"/>"));
    assert!(second.contains("<PP Name=\"UnitAddress\" Value=\"21\"/>"));
    assert_eq!(
        service
            .handle(&mut client, "[save] PROJECT SAVE XDUP")
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut client, "[close] PROJECT CLOSE XDUP")
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut client, "[load] PROJECT LOAD XDUP")
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut client, "[use] PROJECT USE XDUP")
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut client, "[post-load] DBGETXML //XDUP/253/p/20")
            .await
            .lines[0],
        first
    );
    assert_eq!(
        service
            .handle(&mut client, "[post-load] DBGETXML //XDUP/253/p/21")
            .await
            .lines[0],
        second
    );
    assert!(
        tokio::time::timeout(Duration::from_millis(20), remote.read_u8())
            .await
            .is_err()
    );
    drop(service);

    let (restart_pci, _remote) = pci();
    let restarted = Service::new(&fixture(), None, path.clone(), restart_pci, None).unwrap();
    let mut client = ClientState::default();
    assert_eq!(
        restarted
            .handle(&mut client, "[8] PROJECT USE XDUP")
            .await
            .status,
        200
    );
    assert_eq!(
        restarted
            .handle(&mut client, "[9] DBGETXML //XDUP/253/p/20")
            .await
            .lines[0],
        first
    );
    assert_eq!(
        restarted
            .handle(&mut client, "[10] DBGETXML //XDUP/253/p/21")
            .await
            .lines[0],
        second
    );
    let tree = restarted
        .handle(&mut client, "[11] DBGETXML //XDUP/253")
        .await
        .lines[0]
        .clone();
    assert_eq!(tree.matches(&format!("<OID>{shared}</OID>")).count(), 3);
    let replacement = format!(
        "<Unit><OID>{shared}</OID><TagName>Second</TagName><Address>21</Address><UnitType>KEYE1</UnitType><UnitName>Changed room</UnitName><FirmwareVersion>1.2.69</FirmwareVersion><PP Name=\"UnitAddress\" Value=\"21\"/></Unit>"
    );
    assert_eq!(
        restarted
            .handle_document(&mut client, "[12] DBSETXML //XDUP/253/p/21", &replacement)
            .await
            .status,
        301
    );
    assert_eq!(
        restarted
            .handle(&mut client, "[13] DBGETXML //XDUP/253/p/20")
            .await
            .lines[0],
        first
    );
    drop(restarted);

    let (second_restart_pci, _remote) = pci();
    let second_restart =
        Service::new(&fixture(), None, path.clone(), second_restart_pci, None).unwrap();
    let mut client = ClientState::default();
    assert_eq!(
        second_restart
            .handle(&mut client, "[14] PROJECT USE XDUP")
            .await
            .status,
        200
    );
    assert_eq!(
        second_restart
            .handle(&mut client, "[15] DBGETXML //XDUP/253/p/20")
            .await
            .lines[0],
        first
    );
    let changed = second_restart
        .handle(&mut client, "[16] DBGETXML //XDUP/253/p/21")
        .await
        .lines[0]
        .clone();
    assert!(changed.contains("<UnitName>Changed room</UnitName>"));
    assert!(changed.contains("<PP Name=\"UnitAddress\" Value=\"21\"/>"));
    assert_eq!(
        second_restart
            .handle(&mut client, "[17] DBGETXML //XDUP/253/56")
            .await
            .status,
        200
    );
    drop(second_restart);
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn duplicate_application_oid_keeps_both_paths_through_service_restart() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    for command in [
        "[1] PROJECT NEW XAPP",
        "[2] PROJECT USE XAPP",
        "[3] DBCREATENET 254 Local Cni 127.0.0.1:1",
    ] {
        assert_eq!(service.handle(&mut client, command).await.status, 200);
    }
    let initial = service.handle(&mut client, "[4] DBGETXML //XAPP/254").await;
    let parsed =
        roxmltree::Document::parse(initial.lines[0].strip_prefix("347-").unwrap()).unwrap();
    let oid = |node: roxmltree::Node<'_, '_>| {
        node.children()
            .find(|child| child.has_tag_name("OID"))
            .unwrap()
            .text()
            .unwrap()
            .to_string()
    };
    let network_oid = oid(parsed.root_element());
    let interface_oid = oid(parsed
        .descendants()
        .find(|node| node.has_tag_name("Interface"))
        .unwrap());
    let shared = "33333333-3333-4333-8333-333333333333";
    let document = format!(
        "<Network><OID>{network_oid}</OID><TagName>Local</TagName><Address>254</Address><NetworkNumber>254</NetworkNumber><Interface><OID>{interface_oid}</OID><InterfaceType>Cni</InterfaceType><InterfaceAddress>127.0.0.1:1</InterfaceAddress></Interface><Application><OID>{shared}</OID><TagName>First</TagName><Address>56</Address></Application><Application><OID>{shared}</OID><TagName>Second</TagName><Address>57</Address></Application></Network>"
    );
    assert_eq!(
        service
            .handle_document(&mut client, "[5] DBSETXML //XAPP/254", &document)
            .await
            .status,
        301
    );
    let first = service
        .handle(&mut client, "[6] DBGETXML //XAPP/254/56")
        .await
        .lines[0]
        .clone();
    let second = service
        .handle(&mut client, "[7] DBGETXML //XAPP/254/57")
        .await
        .lines[0]
        .clone();
    assert_ne!(first, second);
    assert_eq!(
        service
            .handle(&mut client, "[8] PROJECT SAVE XAPP")
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut client, "[9] PROJECT CLOSE XAPP")
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut client, "[10] PROJECT LOAD XAPP")
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut client, "[11] PROJECT USE XAPP")
            .await
            .status,
        200
    );
    assert!(
        tokio::time::timeout(Duration::from_millis(20), remote.read_u8())
            .await
            .is_err()
    );
    drop(service);

    let (restart_pci, _remote) = pci();
    let restarted = Service::new(&fixture(), None, path.clone(), restart_pci, None).unwrap();
    let mut client = ClientState::default();
    assert_eq!(
        restarted
            .handle(&mut client, "[12] PROJECT USE XAPP")
            .await
            .status,
        200
    );
    assert_eq!(
        restarted
            .handle(&mut client, "[13] DBGETXML //XAPP/254/56")
            .await
            .lines[0],
        first
    );
    assert_eq!(
        restarted
            .handle(&mut client, "[14] DBGETXML //XAPP/254/57")
            .await
            .lines[0],
        second
    );
    assert_eq!(
        restarted
            .handle(&mut client, &format!("[15] DBGETXML !{shared}"))
            .await
            .lines[0],
        second
    );
    let replacement = format!(
        "<Application><OID>{shared}</OID><TagName>Changed</TagName><Address>57</Address></Application>"
    );
    assert_eq!(
        restarted
            .handle_document(&mut client, "[16] DBSETXML //XAPP/254/57", &replacement)
            .await
            .status,
        301
    );
    assert_eq!(
        restarted
            .handle(&mut client, "[17] DBGETXML //XAPP/254/56")
            .await
            .lines[0],
        first
    );
    drop(restarted);

    let (restart_pci, _remote) = pci();
    let restarted = Service::new(&fixture(), None, path.clone(), restart_pci, None).unwrap();
    let mut client = ClientState::default();
    assert_eq!(
        restarted
            .handle(&mut client, "[18] PROJECT USE XAPP")
            .await
            .status,
        200
    );
    let tree = restarted
        .handle(&mut client, "[19] DBGETXML //XAPP/254")
        .await
        .lines[0]
        .clone();
    assert_eq!(tree.matches(&format!("<OID>{shared}</OID>")).count(), 2);
    assert!(tree.contains("<TagName>First</TagName><Address>56</Address>"));
    assert!(tree.contains("<TagName>Changed</TagName><Address>57</Address>"));
    drop(restarted);
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn nested_same_oid_application_children_survive_repository_restart() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    for command in [
        "[1] PROJECT NEW XNEST",
        "[2] PROJECT USE XNEST",
        "[3] DBCREATENET 254 Local Cni 127.0.0.1:1",
    ] {
        assert_eq!(service.handle(&mut client, command).await.status, 200);
    }
    let initial = service
        .handle(&mut client, "[4] DBGETXML //XNEST/254")
        .await;
    let parsed =
        roxmltree::Document::parse(initial.lines[0].strip_prefix("347-").unwrap()).unwrap();
    let oid = |node: roxmltree::Node<'_, '_>| {
        node.children()
            .find(|child| child.has_tag_name("OID"))
            .unwrap()
            .text()
            .unwrap()
            .to_string()
    };
    let network_oid = oid(parsed.root_element());
    let interface_oid = oid(parsed
        .descendants()
        .find(|node| node.has_tag_name("Interface"))
        .unwrap());
    let shared = "33333333-3333-4333-8333-333333333333";
    let first = format!("<Application><OID>{shared}</OID><TagName>First</TagName><Address>56</Address><Group><OID>44444444-4444-4444-8444-000000000056</OID><TagName>Group56</TagName><Address>1</Address></Group></Application>");
    let second = format!("<Application><OID>{shared}</OID><TagName>Second</TagName><Address>57</Address><NetVar><OID>44444444-4444-4444-8444-000000000057</OID><TagName>NetVar57</TagName><Address>1</Address></NetVar></Application>");
    let document = format!(
        "<Network><OID>{network_oid}</OID><TagName>Local</TagName><Address>254</Address><NetworkNumber>254</NetworkNumber><Interface><OID>{interface_oid}</OID><InterfaceType>Cni</InterfaceType><InterfaceAddress>127.0.0.1:1</InterfaceAddress></Interface>{first}{second}</Network>"
    );
    assert_eq!(
        service
            .handle_document(&mut client, "[5] DBSETXML //XNEST/254", &document)
            .await
            .status,
        301
    );
    let expected = service
        .handle(&mut client, "[6] DBGETXML //XNEST/254")
        .await
        .lines[0]
        .clone();
    assert!(expected.contains(&first));
    assert!(expected.contains(&second));
    assert_eq!(
        service
            .handle(&mut client, "[7] PROJECT SAVE XNEST")
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut client, "[8] PROJECT CLOSE XNEST")
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut client, "[9] PROJECT LOAD XNEST")
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut client, "[10] PROJECT USE XNEST")
            .await
            .status,
        200
    );
    assert!(
        tokio::time::timeout(Duration::from_millis(20), remote.read_u8())
            .await
            .is_err()
    );
    drop(service);

    let (restart_pci, _remote) = pci();
    let restarted = Service::new(&fixture(), None, path.clone(), restart_pci, None).unwrap();
    let mut client = ClientState::default();
    assert_eq!(
        restarted
            .handle(&mut client, "[11] PROJECT USE XNEST")
            .await
            .status,
        200
    );
    assert_eq!(
        restarted
            .handle(&mut client, "[12] DBGETXML //XNEST/254")
            .await
            .lines[0],
        expected
    );
    let selected = restarted
        .handle(&mut client, &format!("[13] DBGETXML !{shared}"))
        .await;
    assert!(selected.lines[0].contains(&second));
    let changed = first.replace("<TagName>First</TagName>", "<TagName>Changed</TagName>");
    assert_eq!(
        restarted
            .handle_document(&mut client, "[14] DBSETXML //XNEST/254/56", &changed)
            .await
            .status,
        301
    );
    let after = restarted
        .handle(&mut client, "[15] DBGETXML //XNEST/254")
        .await
        .lines[0]
        .clone();
    assert!(after.contains(&changed));
    assert!(after.contains(&second));
    drop(restarted);

    let (restart_pci, _remote) = pci();
    let restarted = Service::new(&fixture(), None, path.clone(), restart_pci, None).unwrap();
    let mut client = ClientState::default();
    assert_eq!(
        restarted
            .handle(&mut client, "[16] PROJECT USE XNEST")
            .await
            .status,
        200
    );
    assert_eq!(
        restarted
            .handle(&mut client, "[17] DBGETXML //XNEST/254")
            .await
            .lines[0],
        after
    );
    drop(restarted);
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn nested_same_oid_levels_materialize_on_load_and_survive_repository_restart() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    let shared = "33333333-3333-4333-8333-333333333333";
    let mut loaded = Vec::new();
    for (project, kind) in [("XLGR", "Group"), ("XLNV", "NetVar")] {
        for command in [
            format!("[new] PROJECT NEW {project}"),
            format!("[use] PROJECT USE {project}"),
            "[net] DBCREATENET 254 Local Cni 127.0.0.1:1".to_string(),
        ] {
            assert_eq!(service.handle(&mut client, &command).await.status, 200);
        }
        let initial = service
            .handle(&mut client, &format!("[base] DBGETXML //{project}/254"))
            .await;
        let parsed =
            roxmltree::Document::parse(initial.lines[0].strip_prefix("347-").unwrap()).unwrap();
        let oid = |node: roxmltree::Node<'_, '_>| {
            node.children()
                .find(|child| child.has_tag_name("OID"))
                .unwrap()
                .text()
                .unwrap()
                .to_string()
        };
        let network_oid = oid(parsed.root_element());
        let interface_oid = oid(parsed
            .descendants()
            .find(|node| node.has_tag_name("Interface"))
            .unwrap());
        let applications = (56..=57)
            .map(|address| {
                format!(
                    "<Application><OID>{shared}</OID><TagName>App{address}</TagName><Address>{address}</Address><{kind}><OID>44444444-4444-4444-8444-0000000000{address}</OID><TagName>{kind}{address}</TagName><Address>1</Address><Level Value=\"{address}\"><OID>55555555-5555-4555-8555-0000000000{address}</OID><TagName>Level{address}</TagName><Address>2</Address></Level></{kind}></Application>"
                )
            })
            .collect::<String>();
        let document = format!(
            "<Network><OID>{network_oid}</OID><TagName>Local</TagName><Address>254</Address><NetworkNumber>254</NetworkNumber><Interface><OID>{interface_oid}</OID><InterfaceType>Cni</InterfaceType><InterfaceAddress>127.0.0.1:1</InterfaceAddress></Interface>{applications}</Network>"
        );
        assert_eq!(
            service
                .handle_document(
                    &mut client,
                    &format!("[set] DBSETXML //{project}/254"),
                    &document
                )
                .await
                .status,
            301
        );
        let read = |tag: &str| format!("[{tag}] DBGETXML //{project}/254");
        let before = service.handle(&mut client, &read("before")).await;
        assert_eq!(before.lines[0].matches("<Level Value=").count(), 2);
        assert_eq!(before.lines[0].matches("<TagsDLT/>").count(), 0);
        assert_eq!(
            service
                .handle(&mut client, &format!("[save] PROJECT SAVE {project}"))
                .await
                .status,
            200
        );
        let after_save = service.handle(&mut client, &read("saved")).await;
        assert_eq!(after_save.lines[0], before.lines[0]);
        assert_eq!(
            service
                .handle(&mut client, &format!("[close] PROJECT CLOSE {project}"))
                .await
                .status,
            200
        );
        assert_eq!(
            service
                .handle(&mut client, &format!("[load] PROJECT LOAD {project}"))
                .await
                .status,
            200
        );
        let after_load = service.handle(&mut client, &read("loaded")).await;
        assert_eq!(after_load.lines[0].matches("<TagsDLT/>").count(), 2);
        let level = format!("//{project}/254/56/1/2");
        let direct = service
            .handle(&mut client, &format!("[direct] DBGETXML {level}"))
            .await;
        assert_eq!(direct.status, if kind == "Group" { 200 } else { 500 });
        let by_oid = service
            .handle(
                &mut client,
                "[oid] DBGETXML !55555555-5555-4555-8555-000000000056",
            )
            .await;
        assert_eq!(by_oid.status, 200);
        assert!(by_oid.lines[0].contains("<TagsDLT/>"));
        loaded.push((project, after_load.lines[0].clone()));
    }
    assert!(
        tokio::time::timeout(Duration::from_millis(20), remote.read_u8())
            .await
            .is_err()
    );
    drop(service);

    let (restart_pci, _remote) = pci();
    let restarted = Service::new(&fixture(), None, path.clone(), restart_pci, None).unwrap();
    let mut client = ClientState::default();
    for (project, expected) in loaded {
        assert_eq!(
            restarted
                .handle(&mut client, &format!("[use] PROJECT USE {project}"))
                .await
                .status,
            200
        );
        assert_eq!(
            restarted
                .handle(&mut client, &format!("[read] DBGETXML //{project}/254"))
                .await
                .lines[0],
            expected
        );
    }
    drop(restarted);
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn reversed_four_application_oid_order_survives_repository_restart() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    for command in [
        "[1] PROJECT NEW XQUAD",
        "[2] PROJECT USE XQUAD",
        "[3] DBCREATENET 254 Local Cni 127.0.0.1:1",
    ] {
        assert_eq!(service.handle(&mut client, command).await.status, 200);
    }
    let initial = service
        .handle(&mut client, "[4] DBGETXML //XQUAD/254")
        .await;
    let parsed =
        roxmltree::Document::parse(initial.lines[0].strip_prefix("347-").unwrap()).unwrap();
    let oid = |node: roxmltree::Node<'_, '_>| {
        node.children()
            .find(|child| child.has_tag_name("OID"))
            .unwrap()
            .text()
            .unwrap()
            .to_string()
    };
    let network_oid = oid(parsed.root_element());
    let interface_oid = oid(parsed
        .descendants()
        .find(|node| node.has_tag_name("Interface"))
        .unwrap());
    let shared = "33333333-3333-4333-8333-333333333333";
    let application = |address: u8, name: &str| {
        format!("<Application><OID>{shared}</OID><TagName>{name}</TagName><Address>{address}</Address></Application>")
    };
    let document = format!(
        "<Network><OID>{network_oid}</OID><TagName>Local</TagName><Address>254</Address><NetworkNumber>254</NetworkNumber><Interface><OID>{interface_oid}</OID><InterfaceType>Cni</InterfaceType><InterfaceAddress>127.0.0.1:1</InterfaceAddress></Interface>{}{}{}{}</Network>",
        application(59, "Fourth"), application(57, "Second"),
        application(56, "First"), application(58, "Third")
    );
    assert_eq!(
        service
            .handle_document(&mut client, "[5] DBSETXML //XQUAD/254", &document)
            .await
            .status,
        301
    );
    assert_eq!(
        service
            .handle(&mut client, "[6] PROJECT SAVE XQUAD")
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut client, "[7] PROJECT CLOSE XQUAD")
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut client, "[8] PROJECT LOAD XQUAD")
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut client, "[9] PROJECT USE XQUAD")
            .await
            .status,
        200
    );
    let expected_tree = service
        .handle(&mut client, "[10] DBGETXML //XQUAD/254")
        .await
        .lines[0]
        .clone();
    let mut last = 0;
    for address in [59, 57, 56, 58] {
        let marker = format!("<Address>{address}</Address></Application>");
        let position = expected_tree.find(&marker).unwrap();
        assert!(position > last);
        last = position;
    }
    assert!(
        tokio::time::timeout(Duration::from_millis(20), remote.read_u8())
            .await
            .is_err(),
        "database-only replacement must not reach PCI"
    );
    drop(service);

    let (restart_pci, _remote) = pci();
    let restarted = Service::new(&fixture(), None, path.clone(), restart_pci, None).unwrap();
    let mut client = ClientState::default();
    assert_eq!(
        restarted
            .handle(&mut client, "[11] PROJECT USE XQUAD")
            .await
            .status,
        200
    );
    assert_eq!(
        restarted
            .handle(&mut client, "[12] DBGETXML //XQUAD/254")
            .await
            .lines[0],
        expected_tree
    );
    let selected = restarted
        .handle(&mut client, &format!("[13] DBGETXML !{shared}"))
        .await;
    assert_eq!(selected.status, 200);
    assert!(selected.lines[0].contains("<Address>58</Address>"));
    let replacement = application(59, "ChangedFourth");
    assert_eq!(
        restarted
            .handle_document(&mut client, "[14] DBSETXML //XQUAD/254/59", &replacement)
            .await
            .status,
        301
    );
    assert_eq!(
        restarted
            .handle(&mut client, &format!("[15] DBGETXML !{shared}"))
            .await
            .lines[0],
        selected.lines[0]
    );
    drop(restarted);

    let (restart_pci, _remote) = pci();
    let restarted = Service::new(&fixture(), None, path.clone(), restart_pci, None).unwrap();
    let mut client = ClientState::default();
    assert_eq!(
        restarted
            .handle(&mut client, "[16] PROJECT USE XQUAD")
            .await
            .status,
        200
    );
    let tree = restarted
        .handle(&mut client, "[17] DBGETXML //XQUAD/254")
        .await
        .lines[0]
        .clone();
    assert!(tree.contains("<TagName>ChangedFourth</TagName><Address>59</Address>"));
    assert_eq!(tree.matches(&format!("<OID>{shared}</OID>")).count(), 4);
    assert!(restarted
        .handle(&mut client, &format!("[18] DBGETXML !{shared}"))
        .await
        .lines[0]
        .contains("<Address>58</Address>"));
    drop(restarted);
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn typed_container_dbsetxml_is_durable_atomic_and_never_reaches_pci() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    assert_eq!(
        service
            .handle(&mut client, "[1] PROJECT NEW XMLA")
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut client, "[2] DBCREATENET 200 Auxiliary Cni 127.0.0.1:1")
            .await
            .status,
        200
    );
    let created = service
        .handle(&mut client, "[3] DBADD 200 Application")
        .await;
    let old_oid = created
        .final_text
        .strip_prefix("301 OID=")
        .unwrap()
        .to_string();
    assert_eq!(
        service
            .handle(&mut client, &format!("[4] DBSET !{old_oid}/Address 56"),)
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(
                &mut client,
                &format!("[5] DBSET !{old_oid}/TagName Original"),
            )
            .await
            .status,
        200
    );
    let document = concat!(
        "<Application><OID>40000000-0000-4000-8000-000000000001</OID>",
        "<TagName>Durable</TagName><Address>58</Address>",
        "<Group><OID>40000000-0000-4000-8000-000000000002</OID>",
        "<TagName>Scenes</TagName><Address>12</Address>",
        "<Level Value=\"42\"><OID>40000000-0000-4000-8000-000000000003</OID>",
        "<TagName>Low</TagName><Address>1</Address></Level></Group></Application>"
    );
    let replaced = service
        .handle_document(&mut client, &format!("[6] DBSETXML !{old_oid}"), document)
        .await;
    assert_eq!(replaced.status, 301, "{replaced:?}");
    assert_eq!(
        replaced.final_text,
        "301 OID=40000000-0000-4000-8000-000000000001"
    );
    assert!(
        tokio::time::timeout(Duration::from_millis(20), remote.read_u8())
            .await
            .is_err(),
        "typed DBSETXML must not write to PCI"
    );
    let persisted = std::fs::read(&path).unwrap();
    let duplicate = document.replace(
        "40000000-0000-4000-8000-000000000002",
        "40000000-0000-4000-8000-000000000001",
    );
    assert!(
        service
            .handle_document(
                &mut client,
                "[7] DBSETXML !40000000-0000-4000-8000-000000000001",
                &duplicate,
            )
            .await
            .status
            >= 400
    );
    assert_eq!(std::fs::read(&path).unwrap(), persisted);
    drop(service);

    let (restart_pci, _remote) = pci();
    let restarted = Service::new(&fixture(), None, path.clone(), restart_pci, None).unwrap();
    let mut restarted_client = ClientState::default();
    assert_eq!(
        restarted
            .handle(&mut restarted_client, "[8] PROJECT USE XMLA")
            .await
            .status,
        200
    );
    let readback = restarted
        .handle(&mut restarted_client, "[9] DBGETXML //XMLA/200/58")
        .await;
    assert_eq!(readback.status, 200, "{readback:?}");
    assert!(readback.lines[0].contains("<Level Value=\"42\">"));

    // A malformed configured-network document reaches schema validation; the
    // bounded same-address/same-interface replacement contract is exercised
    // separately below.
    let configured_oid = restarted.model.lock().await.projects["HARNESS"].networks[&254]
        .oid
        .clone();
    let refused = restarted
        .handle_document(
            &mut ClientState::default(),
            &format!("[10] DBSETXML !{configured_oid}"),
            "<Network/>",
        )
        .await;
    assert_eq!(refused.status, 400);
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn configured_network_dbsetxml_replaces_database_topology_without_rebinding_or_pci_io() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    let original = {
        let mut model = service.model.lock().await;
        let network = model
            .projects
            .get_mut("HARNESS")
            .unwrap()
            .networks
            .get_mut(&254)
            .unwrap();
        let physical = network.units[&5].clone();
        network.physical.insert(5, physical);
        network.levels.insert((56, 1), 77);
        network.state = NetworkState::Open;
        network.retries = 7;
        network.clone()
    };
    let document = format!(
        "<Network xmlns:x=\"urn:configured\" x:revision=\"2\"><OID>52000000-0000-4000-8000-000000000001</OID><TagName>Configured replacement</TagName><Address>254</Address><NetworkNumber>254</NetworkNumber><Interface><OID>52000000-0000-4000-8000-000000000002</OID><InterfaceType>{}</InterfaceType><InterfaceAddress>{}</InterfaceAddress></Interface><Unit x:source=\"document\"><OID>52000000-0000-4000-8000-000000000003</OID><TagName>Replacement eDLT</TagName><Address>6</Address><UnitType>KEYGL5</UnitType><UnitName>Replacement eDLT</UnitName><FirmwareVersion>5.5.00</FirmwareVersion><PP Name=\"StaticTextString0\" Value=\"Topology\"/><!--unit--><x:Opaque>kept</x:Opaque></Unit><Application><OID>52000000-0000-4000-8000-000000000004</OID><TagName>Lighting</TagName><Address>56</Address></Application><!--network--></Network>",
        original.iface_type, original.iface_addr
    );
    let replaced = service
        .handle_document(&mut client, "[replace] DBSETXML //HARNESS/254", &document)
        .await;
    assert_eq!(replaced.status, 301, "{replaced:?}");
    assert_eq!(
        replaced.final_text,
        "301 OID=52000000-0000-4000-8000-000000000001"
    );
    {
        let model = service.model.lock().await;
        let network = &model.projects["HARNESS"].networks[&254];
        assert_eq!(network.name, "Configured replacement");
        assert_eq!(network.oid, "52000000-0000-4000-8000-000000000001");
        assert_eq!(
            network.interface_oid,
            "52000000-0000-4000-8000-000000000002"
        );
        assert_eq!(network.iface_type, original.iface_type);
        assert_eq!(network.iface_addr, original.iface_addr);
        assert_eq!(network.state, NetworkState::Open);
        assert_eq!(network.retries, 7);
        assert_eq!(network.levels.get(&(56, 1)), Some(&77));
        assert_eq!(network.physical.get(&5).map(|unit| unit.address), Some(5));
        assert!(!network.units.contains_key(&5));
        assert_eq!(network.units[&6].fields["TagName"], "Replacement eDLT");
    }
    let unit_xml = service
        .handle(&mut client, "[unit] DBGETXML //HARNESS/254/p/6")
        .await;
    assert_eq!(unit_xml.status, 200, "{unit_xml:?}");
    assert!(!unit_xml.lines[0].contains("xmlns:x=\"urn:configured\""));
    assert!(!unit_xml.lines[0].contains("x:source=\"document\""));
    assert!(!unit_xml.lines[0].contains("<!--unit-->"));
    assert!(!unit_xml.lines[0].contains("<x:Opaque>kept</x:Opaque>"));
    let persisted = std::fs::read(&path).unwrap();

    let changed_binding = document.replace(
        &format!(
            "<InterfaceAddress>{}</InterfaceAddress>",
            original.iface_addr
        ),
        "<InterfaceAddress>127.0.0.1:65535</InterfaceAddress>",
    );
    let refused_binding = service
        .handle_document(&mut client, "[binding] DBSETXML 254", &changed_binding)
        .await;
    assert_eq!(refused_binding.status, 408, "{refused_binding:?}");
    assert!(refused_binding
        .final_text
        .contains("physical interface binding is immutable"));
    assert_eq!(std::fs::read(&path).unwrap(), persisted);

    let moved = document
        .replace("<Address>254</Address>", "<Address>253</Address>")
        .replace(
            "<NetworkNumber>254</NetworkNumber>",
            "<NetworkNumber>253</NetworkNumber>",
        );
    let refused_move = service
        .handle_document(
            &mut client,
            "[move] DBSETXML !52000000-0000-4000-8000-000000000001",
            &moved,
        )
        .await;
    assert_eq!(refused_move.status, 408, "{refused_move:?}");
    assert!(refused_move
        .final_text
        .contains("configured network address is immutable"));
    assert_eq!(std::fs::read(&path).unwrap(), persisted);
    {
        let model = service.model.lock().await;
        let network = &model.projects["HARNESS"].networks[&254];
        assert_eq!(network.oid, "52000000-0000-4000-8000-000000000001");
        assert_eq!(network.state, NetworkState::Open);
        assert_eq!(network.levels.get(&(56, 1)), Some(&77));
        assert!(network.physical.contains_key(&5));
        assert!(network.units.contains_key(&6));
        assert!(!model.projects["HARNESS"].networks.contains_key(&253));
    }
    assert!(
        tokio::time::timeout(Duration::from_millis(20), remote.read_u8())
            .await
            .is_err(),
        "configured Network DBSETXML must not write to PCI"
    );

    drop(service);
    let (restart_pci, _remote) = pci();
    let restarted = Service::new(&fixture(), None, path.clone(), restart_pci, None).unwrap();
    let mut restarted_client = ClientState::default();
    let restarted_unit = restarted
        .handle(
            &mut restarted_client,
            "[restart] DBGETXML //HARNESS/254/p/6",
        )
        .await;
    assert_eq!(restarted_unit.status, 200, "{restarted_unit:?}");
    assert!(restarted_unit.lines[0].contains("<TagName>Replacement eDLT</TagName>"));
    assert!(!restarted_unit.lines[0].contains("<x:Opaque>kept</x:Opaque>"));
    assert!(
        restarted.model.lock().await.projects["HARNESS"].networks[&254]
            .physical
            .is_empty()
    );
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn tcp_here_documents_preserve_tags_drain_limits_and_close_on_truncation() {
    let path = state_path();
    let (pci, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let oid = service.model.lock().await.projects["HARNESS"].networks[&254].units[&5]
        .oid
        .clone();
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let server = tokio::spawn(service.clone().serve(listener));
    let (mut reader, mut writer) = connect_command_session(address).await;

    writer
        .write_all(format!("[doc] DBSETXML //HARNESS/254/p/5 << END\r\n<Unit><OID>{oid}</OID><Address>5</Address><TagName>TCP eDLT</TagName><UnitType>KEYGL5</UnitType><UnitName>TCP eDLT</UnitName><FirmwareVersion>5.5.00</FirmwareVersion></Unit>\r\nEND\r\n").as_bytes())
        .await
        .unwrap();
    let mut reply = String::new();
    reader.read_line(&mut reply).await.unwrap();
    assert_eq!(reply, format!("[doc] 301 OID={oid}\r\n"));
    let readback = command_lines(
        &mut reader,
        &mut writer,
        "get",
        "DBGET //HARNESS/254/p/5/TagName",
    )
    .await;
    assert!(readback.iter().any(|line| line.contains("TCP eDLT")));

    writer
        .write_all(b"[xml] DBGETXML //HARNESS/254/p/5\r\n")
        .await
        .unwrap();
    let mut xml_rows = Vec::new();
    for _ in 0..4 {
        let mut row = Vec::new();
        assert_ne!(reader.read_until(b'\n', &mut row).await.unwrap(), 0);
        xml_rows.push(row);
    }
    assert_eq!(xml_rows[0], b"[xml] 343-Begin XML snippet\r\n");
    assert_eq!(
        xml_rows[1],
        b"[xml] 347-<?xml version=\"1.0\" encoding=\"utf-8\"?>\n"
    );
    assert!(xml_rows[2].starts_with(b"[xml] 347-<Unit>"));
    assert!(xml_rows[2].ends_with(b"</Unit>\r\n"));
    assert_eq!(xml_rows[3], b"[xml] 344 End XML snippet\r\n");
    assert_eq!(
        command_lines(&mut reader, &mut writer, "afterxml", "NOOP").await,
        ["[afterxml] 200 OK"]
    );
    assert_eq!(
        command_lines(
            &mut reader,
            &mut writer,
            "absent",
            "DBGETXML //HARNESS/254/p/21",
        )
        .await,
        ["[absent] 401 Bad object or device ID: Element 21 not found."]
    );

    let mut oversized = Vec::with_capacity(MAX_LINE + 64);
    oversized.extend_from_slice(b"[large] DBSETXML //HARNESS/254/p/5/TagName << END\r\n");
    oversized.extend(std::iter::repeat_n(b'x', MAX_LINE + 1));
    oversized.extend_from_slice(b"\r\nEND\r\n[after] NOOP\r\n");
    writer.write_all(&oversized).await.unwrap();
    reply.clear();
    reader.read_line(&mut reply).await.unwrap();
    assert_eq!(reply, "[large] 400 document exceeded configured limit\r\n");
    reply.clear();
    reader.read_line(&mut reply).await.unwrap();
    assert_eq!(reply, "[after] 200 OK\r\n");

    let (mut truncated_reader, mut truncated_writer) = connect_command_session(address).await;
    truncated_writer
        .write_all(b"[cut] DBSETXML //HARNESS/254/p/5/TagName << END\r\npartial\r\n")
        .await
        .unwrap();
    truncated_writer.shutdown().await.unwrap();
    reply.clear();
    truncated_reader.read_line(&mut reply).await.unwrap();
    assert_eq!(reply, "[cut] 400 truncated here-document\r\n");
    reply.clear();
    assert_eq!(truncated_reader.read_line(&mut reply).await.unwrap(), 0);

    server.abort();
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn config_catalog_scopes_snapshots_and_restart_are_durable_without_pci_io() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();

    let help = service.handle(&mut client, "[h] CONFIG ?").await;
    assert_eq!(help.status, 101);
    assert_eq!(help.lines.len(), 9);
    assert_eq!(help.final_text, "101 Help:  CONFIG SET - ");

    let all = service.handle(&mut client, "[all] CONFIG GET *").await;
    assert_eq!(all.status, 303);
    assert_eq!(all.lines.len() + 1, 122);
    assert_eq!(all.lines[0], "accept-connections-from=all");
    assert_eq!(all.final_text, "303 use-tags=yes");
    assert_eq!(
        service
            .handle(&mut client, "[get] CONFIG GET sync-time")
            .await
            .final_text,
        "303 sync-time=3600"
    );

    assert_eq!(
        service
            .handle(&mut client, "[set] CONFIG SET sync-time 123")
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut client, "[global] CONFIG OBGET global sync-time")
            .await
            .final_text,
        "303 sync-time=3600"
    );
    assert_eq!(
        service
            .handle(&mut client, "[project] CONFIG OBGET project sync-time")
            .await
            .final_text,
        "303 sync-time=123"
    );
    assert_eq!(
        service
            .handle(
                &mut client,
                "[network] CONFIG OBGET //HARNESS/254 sync-time",
            )
            .await
            .final_text,
        "303 sync-time=123"
    );
    assert_eq!(
        service
            .handle(
                &mut client,
                "[network-set] CONFIG OBSET //HARNESS/254 sync-time 124",
            )
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut client, "[save-project] CONFIG SAVE project")
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(
                &mut client,
                "[reset-project] CONFIG OBRESET project sync-time"
            )
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(
                &mut client,
                "[reset-read] CONFIG OBGET //HARNESS/254 sync-time",
            )
            .await
            .final_text,
        "303 sync-time=3600"
    );
    assert_eq!(
        service
            .handle(&mut client, "[load-project] CONFIG LOAD project")
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(
                &mut client,
                "[restored-network] CONFIG OBGET //HARNESS/254 sync-time",
            )
            .await
            .final_text,
        "303 sync-time=124"
    );

    assert_eq!(
        service
            .handle(&mut client, "[global-set] CONFIG OBSET global sync-time 7",)
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(
                &mut client,
                "[global-save] CONFIG SAVE global retained.conf",
            )
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(
                &mut client,
                "[global-set-2] CONFIG OBSET global sync-time 8",
            )
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(
                &mut client,
                "[global-load] CONFIG LOAD global retained.conf",
            )
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut client, "[global-read] CONFIG OBGET global sync-time")
            .await
            .final_text,
        "303 sync-time=7"
    );

    let missing = service
        .handle(&mut client, "[missing] CONFIG OBGET global not-a-parameter")
        .await;
    assert_eq!(missing.status, 408);
    let wrong_scope = service
        .handle(
            &mut client,
            "[scope] CONFIG OBGET //HARNESS/254 global-event-level",
        )
        .await;
    assert_eq!(wrong_scope.status, 408);

    let capabilities = service
        .handle(&mut client, "[caps] CMQTT CAPABILITIES")
        .await;
    let document: serde_json::Value = serde_json::from_str(&capabilities.lines[0]).unwrap();
    assert_eq!(
        document["config_commands"],
        serde_json::json!(["get", "info", "load", "obget", "obreset", "obset", "save", "set"])
    );
    assert_eq!(document["config_catalog_parameters"], 148);
    assert_eq!(document["config_get_parameters"], 122);
    assert_eq!(document["config_persistence"], "cmqttd-json");
    assert_eq!(document["config_runtime_reconfiguration"], false);
    assert_eq!(
        document["config_restart_effects"],
        serde_json::json!([
            "command.show-responses",
            "command.show-time",
            "event-millis"
        ])
    );
    assert_eq!(document["config_native_obget_missing_reply_repaired"], true);

    let mut byte = [0u8; 1];
    assert!(
        tokio::time::timeout(Duration::from_millis(10), remote.read(&mut byte))
            .await
            .is_err()
    );
    drop(service);

    let (pci, _remote) = pci();
    let restarted = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    assert_eq!(
        restarted
            .handle(
                &mut ClientState::default(),
                "[restart] CONFIG OBGET global sync-time",
            )
            .await
            .final_text,
        "303 sync-time=7"
    );
    std::fs::remove_file(path).unwrap();
}

async fn assert_native_event_millis_case(
    reader: &mut BufReader<tokio::net::tcp::OwnedReadHalf>,
    writer: &mut tokio::net::tcp::OwnedWriteHalf,
    events: &mut tokio::sync::broadcast::Receiver<String>,
    case: &serde_json::Value,
) {
    let expected_response = case["response"]
        .as_array()
        .unwrap()
        .iter()
        .map(|line| line.as_str().unwrap())
        .collect::<Vec<_>>();
    let tag = expected_response[0]
        .strip_prefix('[')
        .unwrap()
        .split_once(']')
        .unwrap()
        .0;
    let body = case["command"].as_str().unwrap();
    assert_eq!(
        command_lines(reader, writer, tag, body).await,
        expected_response,
        "{body}"
    );
    for expected in case["events"].as_array().unwrap() {
        let line = loop {
            let line = next_command_trace_event(events).await;
            if line == "#s# broadcast_event XX class payload" {
                continue;
            }
            break line;
        };
        let (timestamp, payload) = line
            .strip_prefix("#e# ")
            .and_then(|body| body.split_once(' '))
            .unwrap_or_else(|| panic!("native event envelope: {line:?}"));
        let format = match expected["timestamp_shape"].as_str().unwrap() {
            "YYYYMMDD-HHMMSS.mmm" => {
                assert_eq!(timestamp.len(), 19, "{line}");
                "%Y%m%d-%H%M%S%.3f"
            }
            "YYYYMMDD-HHMMSS" => {
                assert_eq!(timestamp.len(), 15, "{line}");
                "%Y%m%d-%H%M%S"
            }
            other => panic!("unexpected retained timestamp shape: {other}"),
        };
        chrono::NaiveDateTime::parse_from_str(timestamp, format).unwrap();
        let (code, message) = payload.split_once(" - ").unwrap();
        let (code, session) = code.split_once(' ').unwrap();
        assert_eq!(
            code.parse::<u16>().unwrap(),
            expected["code"].as_u64().unwrap() as u16
        );
        assert!(session.starts_with("cmd"), "{line}");
        session[3..].parse::<u64>().unwrap();
        assert_eq!(message, expected["text"].as_str().unwrap());
    }
}

#[tokio::test]
async fn config_event_millis_follows_native_restart_precision_for_traces_and_broadcast() {
    let evidence: serde_json::Value = serde_json::from_str(include_str!(
        "../../../testdata/fixtures/native_cgate_config_event_millis.json"
    ))
    .unwrap();
    let cases = &evidence["cases"];
    let path = state_path();

    for (phase, selected) in [
        ("default_then_set_no", &[1, 2, 3, 4][..]),
        ("startup_no_then_set_yes", &[1, 2, 3, 5][..]),
        ("startup_yes", &[0][..]),
    ] {
        let (pci_client, mut remote) = pci();
        let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
        let mut events = service.events.subscribe();
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let server = tokio::spawn(service.clone().serve(listener));
        let (mut reader, mut writer) = connect_command_session(address).await;
        for &index in selected {
            assert_native_event_millis_case(
                &mut reader,
                &mut writer,
                &mut events,
                &cases[phase][index],
            )
            .await;
        }
        assert!(events.try_recv().is_err(), "extra event in {phase}");
        assert!(
            tokio::time::timeout(Duration::from_millis(20), remote.read_u8())
                .await
                .is_err(),
            "CONFIG or BROADCAST_EVENT wrote to PCI"
        );
        drop(reader);
        drop(writer);
        server.abort();
        drop(service);
    }
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn config_event_millis_formats_767_without_fraction_after_restart() {
    let evidence: serde_json::Value = serde_json::from_str(include_str!(
        "../../../testdata/fixtures/native_cgate_config_event_millis.json"
    ))
    .unwrap();
    let native = &evidence["cases"]["startup_no_with_timing"][0]["events"];
    let path = state_path();
    let (pci_client, _remote) = pci();
    let first = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    assert_eq!(
        first
            .handle(&mut client, "[no] CONFIG SET event-millis no")
            .await
            .status,
        200
    );
    assert_eq!(
        first
            .handle(&mut client, "[yes] CONFIG SET command.show-time yes")
            .await
            .status,
        200
    );
    drop(first);

    let (pci_client, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut events = service.events.subscribe();
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let server = tokio::spawn(service.clone().serve(listener));
    let (mut reader, mut writer) = connect_command_session(address).await;
    assert_eq!(
        command_lines(&mut reader, &mut writer, "timed", "NOOP").await,
        ["[timed] 200 OK"]
    );
    for expected in native.as_array().unwrap() {
        let line = next_command_trace_event(&mut events).await;
        let (timestamp, payload) = line
            .strip_prefix("#e# ")
            .and_then(|body| body.split_once(' '))
            .unwrap();
        assert_eq!(timestamp.len(), 15, "{line}");
        chrono::NaiveDateTime::parse_from_str(timestamp, "%Y%m%d-%H%M%S").unwrap();
        assert_eq!(expected["timestamp_shape"], "YYYYMMDD-HHMMSS");
        let (code, message) = payload.split_once(" - ").unwrap();
        let (code, session) = code.split_once(' ').unwrap();
        assert_eq!(code.parse::<u64>().unwrap(), expected["code"]);
        assert!(session.starts_with("cmd"), "{line}");
        match code {
            "761" => assert_eq!(message, "Command: [timed] NOOP"),
            "766" => assert_eq!(message, "Response: [timed] 200 OK"),
            "767" => {
                let duration = message.strip_prefix("commandId=timed time=").unwrap();
                duration.parse::<u128>().unwrap();
                assert_eq!(expected["text"], "commandId=timed time=<nonnegative-ms>");
            }
            other => panic!("unexpected native timing event: {other}"),
        }
    }
    drop(reader);
    drop(writer);
    server.abort();
    drop(service);
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn config_command_show_time_activates_only_after_restart_and_preserves_running_state() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut events = service.events.subscribe();
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let server = tokio::spawn(service.clone().serve(listener));
    let (mut reader, mut writer) = connect_command_session(address).await;

    assert_eq!(
        command_lines(&mut reader, &mut writer, "before", "NOOP").await,
        ["[before] 200 OK"]
    );
    assert_native_command_trace(&mut events, 3, "[before] NOOP", &["[before] 200 OK"], None).await;
    assert_eq!(
        command_lines(
            &mut reader,
            &mut writer,
            "set",
            "CONFIG SET command.show-time yes",
        )
        .await,
        ["[set] 200 OK."]
    );
    assert_native_command_trace(
        &mut events,
        3,
        "[set] CONFIG SET command.show-time yes",
        &["[set] 200 OK."],
        None,
    )
    .await;
    assert_eq!(
        command_lines(
            &mut reader,
            &mut writer,
            "read",
            "CONFIG GET command.show-time"
        )
        .await,
        ["[read] 303 command.show-time=yes"]
    );
    assert_native_command_trace(
        &mut events,
        3,
        "[read] CONFIG GET command.show-time",
        &["[read] 303 command.show-time=yes"],
        None,
    )
    .await;
    assert_eq!(
        command_lines(&mut reader, &mut writer, "still-off", "NOOP").await,
        ["[still-off] 200 OK"]
    );
    assert_native_command_trace(
        &mut events,
        3,
        "[still-off] NOOP",
        &["[still-off] 200 OK"],
        None,
    )
    .await;
    assert!(
        tokio::time::timeout(Duration::from_millis(30), remote.read_u8())
            .await
            .is_err()
    );
    drop(reader);
    drop(writer);
    server.abort();
    drop(service);

    let (pci_client, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut events = service.events.subscribe();
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let server = tokio::spawn(service.clone().serve(listener));
    let (mut reader, mut writer) = connect_command_session(address).await;
    assert_eq!(
        command_lines(&mut reader, &mut writer, "on", "NOOP").await,
        ["[on] 200 OK"]
    );
    assert_native_command_trace(&mut events, 3, "[on] NOOP", &["[on] 200 OK"], Some("on")).await;

    assert_eq!(
        command_lines(
            &mut reader,
            &mut writer,
            "bad",
            "CONFIG SET no-such-parameter yes",
        )
        .await,
        ["[bad] 408 Operation failed: config parameter not found"]
    );
    assert_native_command_trace(
        &mut events,
        3,
        "[bad] CONFIG SET no-such-parameter yes",
        &["[bad] 408 Operation failed: config parameter not found"],
        Some("bad"),
    )
    .await;
    assert_eq!(
        command_lines(
            &mut reader,
            &mut writer,
            "unset",
            "CONFIG SET command.show-time no",
        )
        .await,
        ["[unset] 200 OK."]
    );
    assert_native_command_trace(
        &mut events,
        3,
        "[unset] CONFIG SET command.show-time no",
        &["[unset] 200 OK."],
        Some("unset"),
    )
    .await;
    assert_eq!(
        command_lines(&mut reader, &mut writer, "still-on", "NOOP").await,
        ["[still-on] 200 OK"]
    );
    assert_native_command_trace(
        &mut events,
        3,
        "[still-on] NOOP",
        &["[still-on] 200 OK"],
        Some("still-on"),
    )
    .await;
    drop(reader);
    drop(writer);
    server.abort();
    drop(service);

    let (pci_client, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut events = service.events.subscribe();
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let server = tokio::spawn(service.clone().serve(listener));
    let (mut reader, mut writer) = connect_command_session(address).await;
    assert_eq!(
        command_lines(&mut reader, &mut writer, "off", "NOOP").await,
        ["[off] 200 OK"]
    );
    assert_native_command_trace(&mut events, 3, "[off] NOOP", &["[off] 200 OK"], None).await;
    drop(reader);
    drop(writer);
    server.abort();
    drop(service);
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn config_command_show_responses_uses_native_multiline_events_and_restart_boundary() {
    let evidence: serde_json::Value = serde_json::from_str(include_str!(
        "../../../testdata/fixtures/native_cgate_config_command_show_responses.json"
    ))
    .unwrap();
    let native_info = evidence["cases"]["startup_default"][2]["response"]
        .as_array()
        .unwrap()
        .iter()
        .map(|row| row.as_str().unwrap().replace("[info-network]", "[multi]"))
        .collect::<Vec<_>>();
    let native_info = native_info.iter().map(String::as_str).collect::<Vec<_>>();
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut events = service.events.subscribe();
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let server = tokio::spawn(service.clone().serve(listener));
    let (mut reader, mut writer) = connect_command_session(address).await;
    assert_eq!(
        command_lines(
            &mut reader,
            &mut writer,
            "multi",
            "CONFIG INFO allow-fast-start"
        )
        .await,
        native_info
    );
    assert_native_command_trace(
        &mut events,
        3,
        "[multi] CONFIG INFO allow-fast-start",
        &native_info,
        None,
    )
    .await;
    assert_eq!(
        command_lines(
            &mut reader,
            &mut writer,
            "disable",
            "CONFIG SET command.show-responses no"
        )
        .await,
        ["[disable] 200 OK."]
    );
    assert_native_command_trace(
        &mut events,
        3,
        "[disable] CONFIG SET command.show-responses no",
        &["[disable] 200 OK."],
        None,
    )
    .await;
    assert_eq!(
        command_lines(&mut reader, &mut writer, "still-on", "NOOP").await,
        ["[still-on] 200 OK"]
    );
    assert_native_command_trace(
        &mut events,
        3,
        "[still-on] NOOP",
        &["[still-on] 200 OK"],
        None,
    )
    .await;
    assert!(
        tokio::time::timeout(Duration::from_millis(30), remote.read_u8())
            .await
            .is_err()
    );
    drop(reader);
    drop(writer);
    server.abort();
    drop(service);

    let (pci_client, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut events = service.events.subscribe();
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let server = tokio::spawn(service.clone().serve(listener));
    let (mut reader, mut writer) = connect_command_session(address).await;
    assert_eq!(
        command_lines(&mut reader, &mut writer, "off", "NOOP").await,
        ["[off] 200 OK"]
    );
    assert_native_command_trace(&mut events, 3, "[off] NOOP", &[], None).await;
    assert_eq!(
        command_lines(
            &mut reader,
            &mut writer,
            "bad",
            "CONFIG SET no-such-parameter yes"
        )
        .await,
        ["[bad] 408 Operation failed: config parameter not found"]
    );
    assert_native_command_trace(
        &mut events,
        3,
        "[bad] CONFIG SET no-such-parameter yes",
        &[],
        None,
    )
    .await;
    assert_eq!(
        command_lines(
            &mut reader,
            &mut writer,
            "enable",
            "CONFIG SET command.show-responses yes"
        )
        .await,
        ["[enable] 200 OK."]
    );
    assert_native_command_trace(
        &mut events,
        3,
        "[enable] CONFIG SET command.show-responses yes",
        &[],
        None,
    )
    .await;
    assert_eq!(
        command_lines(
            &mut reader,
            &mut writer,
            "read",
            "CONFIG GET command.show-responses"
        )
        .await,
        ["[read] 303 command.show-responses=yes"]
    );
    assert_native_command_trace(
        &mut events,
        3,
        "[read] CONFIG GET command.show-responses",
        &[],
        None,
    )
    .await;
    drop(reader);
    drop(writer);
    server.abort();
    drop(service);

    let (pci_client, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut events = service.events.subscribe();
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let server = tokio::spawn(service.clone().serve(listener));
    let (mut reader, mut writer) = connect_command_session(address).await;
    assert_eq!(
        command_lines(&mut reader, &mut writer, "restarted", "NOOP").await,
        ["[restarted] 200 OK"]
    );
    assert_native_command_trace(
        &mut events,
        3,
        "[restarted] NOOP",
        &["[restarted] 200 OK"],
        None,
    )
    .await;
    drop(reader);
    drop(writer);
    server.abort();
    drop(service);
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn config_command_trace_delivers_once_to_its_own_event_subscriber() {
    let path = state_path();
    let (pci_client, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let server = tokio::spawn(service.clone().serve(listener));
    let (mut reader, mut writer) = connect_command_session(address).await;
    assert_eq!(
        command_lines(&mut reader, &mut writer, "subscribe", "EVENT e9s0c0").await,
        ["[subscribe] 200 OK."]
    );
    let mut line = String::new();
    reader.read_line(&mut line).await.unwrap();
    assert!(line.contains(" 766 cmd3 - Response: [subscribe] 200 OK."));
    writer.write_all(b"[self] NOOP\r\n").await.unwrap();
    line.clear();
    reader.read_line(&mut line).await.unwrap();
    assert!(line.contains(" 761 cmd3 - Command: [self] NOOP"));
    line.clear();
    reader.read_line(&mut line).await.unwrap();
    assert_eq!(line, "[self] 200 OK\r\n");
    line.clear();
    reader.read_line(&mut line).await.unwrap();
    assert!(line.contains(" 766 cmd3 - Response: [self] 200 OK"));
    assert!(
        tokio::time::timeout(Duration::from_millis(30), reader.read_line(&mut line))
            .await
            .is_err(),
        "own broadcast copy duplicated a command event"
    );
    drop(reader);
    drop(writer);
    server.abort();
    drop(service);
    std::fs::remove_file(path).unwrap();
}

#[test]
fn config_command_trace_redacts_credentials() {
    for command in [
        "[login] LOGIN private-value",
        "[add] ACCESS ADD user private-value Program",
        "[config] CONFIG SET secure.keystore-password private-value",
        "[read] CONFIG GET secure.keystore-password",
    ] {
        assert!(command_has_credential(command));
        let redacted = redact_command_event(command);
        assert!(redacted.contains("<redacted command>"));
        assert!(!redacted.contains("private-value"));
    }
    assert_eq!(
        redact_command_event("[login] LOGIN private-value"),
        "[login] <redacted command>"
    );
    assert!(!command_has_credential(
        "[plain] CONFIG SET command.show-responses no"
    ));
}

#[tokio::test]
async fn config_mutations_require_login_while_catalog_reads_stay_open() {
    let (service, path) = authed_service();
    let mut client = ClientState::default();
    assert_eq!(
        service
            .handle(&mut client, "[read] CONFIG GET sync-time")
            .await
            .status,
        303
    );
    assert_eq!(
        service
            .handle(&mut client, "[locked] CONFIG SET sync-time 55")
            .await
            .final_text,
        "420 LOGIN required"
    );
    assert_eq!(
        service
            .handle(
                &mut client,
                "[login] LOGIN throwaway-loopback-token-0123456789abcdef",
            )
            .await
            .status,
        200
    );
    for command in [
        "CONFIG SET sync-time 55",
        "CONFIG OBSET global sync-time 56",
        "CONFIG OBRESET project sync-time",
        "CONFIG SAVE global auth.conf",
        "CONFIG LOAD global auth.conf",
    ] {
        assert_eq!(
            service
                .handle(&mut client, &format!("[mutate] {command}"))
                .await
                .status,
            200,
            "{command}"
        );
    }
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn config_native_grammar_errors_and_mixed_envelopes_are_pinned() {
    let path = state_path();
    let (pci, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let mut client = ClientState::default();

    for (command, status, final_text) in [
        ("CONFIG BOGUS", 400, "400 Syntax Error."),
        ("CONFIG GET", 400, "400 Syntax Error."),
        (
            "CONFIG GET no-such-param",
            408,
            "408 Operation failed: config parameter not found",
        ),
        (
            "CONFIG GET SYNC-TIME",
            408,
            "408 Operation failed: config parameter not found",
        ),
        ("CONFIG INFO", 400, "400 Syntax Error."),
        (
            "CONFIG INFO no-such-param",
            408,
            "408 Operation failed: config parameter not found",
        ),
        (
            "CONFIG INFO secure.enable",
            408,
            "408 Operation failed: project property not found",
        ),
        (
            "CONFIG OBGET",
            400,
            "400 Syntax Error: Missing parameter : <object>",
        ),
        (
            "CONFIG OBGET global",
            400,
            "400 Syntax Error: Missing parameter : <config-parameter>",
        ),
        (
            "CONFIG OBSET",
            400,
            "400 Syntax Error: Missing parameter : <object>",
        ),
        (
            "CONFIG OBSET global",
            400,
            "400 Syntax Error: Missing parameter : <config-parameter>",
        ),
        (
            "CONFIG OBSET global sync-time 3600",
            408,
            "408 Operation failed: Config value is still the same.",
        ),
        (
            "CONFIG OBRESET",
            400,
            "400 Syntax Error: Missing parameter : <object>",
        ),
        ("CONFIG OBRESET global sync-time", 440, "440 No object specified."),
        ("CONFIG LOAD", 400, "400 Syntax Error."),
        ("CONFIG LOAD bogus", 400, "400 Syntax Error."),
        (
            "CONFIG LOAD global missing.conf",
            408,
            "408 Operation failed: Global config load from missing.conf failed:Config file not found",
        ),
        ("CONFIG SAVE", 400, "400 Syntax Error."),
        ("CONFIG SAVE bogus", 400, "400 Syntax Error."),
        (
            "CONFIG SET secure.enable yes",
            408,
            "408 Operation failed: Can't set an obsolete option.",
        ),
    ] {
        let response = service
            .handle(&mut client, &format!("[case] {command}"))
            .await;
        assert_eq!(response.status, status, "{command}: {response:?}");
        assert_eq!(response.final_text, final_text, "{command}");
    }

    let info = service
        .handle(&mut client, "[info] CONFIG INFO sync-time trailing words")
        .await;
    assert_eq!(
        info.lines,
        [
            "parameter=sync-time",
            "value=3600",
            "description=Time in seconds between the beginnings of successive sync operations",
            "defaultValue=3600",
            "scope=network",
        ]
    );
    assert_eq!(info.final_text, "304 effective=closeopen");

    assert_eq!(
        service
            .handle(
                &mut client,
                "[unit] CONFIG OBGET //HARNESS/254/p/5 sync-time",
            )
            .await
            .final_text,
        "440 Not an object with config parameters."
    );
    assert_eq!(
        service
            .handle(
                &mut client,
                "[missing-unit] CONFIG OBGET //HARNESS/254/p/6 sync-time",
            )
            .await
            .final_text,
        "401 Bad object or device ID: //HARNESS/254/p/6 (Unit not found)"
    );

    assert_eq!(
        service
            .handle(&mut client, "[null] CONFIG SET sync-time")
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut client, "[null-get] CONFIG GET sync-time ignored")
            .await
            .final_text,
        "303 sync-time="
    );
    assert_eq!(
        service
            .handle(&mut client, "[quoted] CONFIG SET sync-time \"two words\"",)
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut client, "[quoted-get] CONFIG GET sync-time")
            .await
            .final_text,
        "303 sync-time=two words"
    );
    assert_eq!(
        service
            .handle(
                &mut client,
                "[quoted-tail] CONFIG SET sync-time \"a b\" ignored tail",
            )
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut client, "[quoted-tail-get] CONFIG GET sync-time")
            .await
            .final_text,
        "303 sync-time=a b ignored tail"
    );

    let load_all = service
        .handle(&mut client, "[load-all] CONFIG LOAD all")
        .await;
    assert_eq!(load_all.lines, ["OK."]);
    assert_eq!(load_all.final_text, "200 OK.");
    let save_all = service
        .handle(&mut client, "[save-all] CONFIG SAVE all ignored extra")
        .await;
    assert!(save_all.lines.is_empty());
    assert_eq!(save_all.final_text, "200 OK.");

    std::fs::remove_file(path).unwrap();
}

#[test]
fn config_no_current_project_preserves_native_load_save_mixed_statuses() {
    let mut model = Server::new(AccessLevel::Program);
    for (body, expected_lines, expected_final) in [
        (
            "CONFIG LOAD project",
            Vec::<String>::new(),
            "408 Operation failed: No project in use",
        ),
        (
            "CONFIG LOAD all",
            vec!["200-OK.".to_string()],
            "408 Operation failed: No project in use",
        ),
        (
            "CONFIG SAVE project",
            vec!["408-Operation failed: No project in use".to_string()],
            "200 OK.",
        ),
        (
            "CONFIG SAVE all",
            vec!["408-Operation failed: No project in use".to_string()],
            "200 OK.",
        ),
    ] {
        let words = body.split_whitespace().collect::<Vec<_>>();
        let upper = words
            .iter()
            .map(|word| word.to_ascii_uppercase())
            .collect::<Vec<_>>();
        let response = config_command(&mut model, "case", body, &words, &upper, None);
        assert_eq!(response.lines, expected_lines, "{body}");
        assert_eq!(response.final_text, expected_final, "{body}");
    }
}

#[tokio::test]
async fn local_admin_help_project_and_nac_json_match_native_envelopes() {
    let path = state_path();
    let (pci, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let mut client = ClientState::default();

    let project_help = service.handle(&mut client, "[project] PROJECT").await;
    assert_eq!(project_help.status, 101);
    assert_eq!(project_help.lines.len(), 17);
    assert_eq!(project_help.lines[0], "Help: PROJECT commands:");
    assert_eq!(
        project_help.final_text,
        "101 Help:  PROJECT USE - Set the current project to be used by this command session"
    );
    assert_eq!(
        service
            .handle(&mut client, "[dir] PROJECT DIRFULL")
            .await
            .final_text,
        "123 project=\"HARNESS\" desc=\"HARNESS\""
    );

    let help = service.handle(&mut client, "[json-help] DBGETJSON").await;
    assert_eq!(help.lines.len(), 4);
    assert_eq!(help.final_text, "101 Help:  DBGETJSON NAC_TAGMAP - ");
    assert_eq!(
        format_response(
            &service
                .handle(
                    &mut client,
                    "[objects] DBGETJSON NAC_OBJECTS_LIST //HARNESS/254/p/5 yes",
                )
                .await,
        ),
        "[objects] 346 []\n"
    );
    assert_eq!(
        format_response(
            &service
                .handle(
                    &mut client,
                    "[routing] DBGETJSON NAC_ROUTING_TABLE //HARNESS/254/p/5",
                )
                .await,
        ),
        "[routing] 345-Begin of JSON\n[routing] 346-[]\n[routing] 347 End of JSON\n"
    );
    let tagmap = service
        .handle(&mut client, "[tags] DBGETJSON NAC_TAGMAP //HARNESS/254/p/5")
        .await;
    assert_eq!(tagmap.status, 347);
    assert_eq!(tagmap.lines[0], "345-Begin of JSON");
    let document: serde_json::Value =
        serde_json::from_str(tagmap.lines[1].strip_prefix("346-").unwrap()).unwrap();
    assert_eq!(document[0]["address"], "0");
    assert_eq!(document[0]["cbustagmap"]["network"], "Harness Network");
    assert_eq!(document[1]["address"], "0/48");
    assert_eq!(document[1]["cbustagmap"]["application"], "Lighting 48");
    assert!(document.as_array().unwrap().iter().any(|row| {
        row["address"] == "0/56/10"
            && row["cbustagmap"]["group"] == "Lounge"
            && row["cbustagmap"]["levels"] == serde_json::json!([])
    }));
    assert_eq!(tagmap.final_text, "347 End of JSON");

    let missing = service
        .handle(
            &mut client,
            "[missing] DBGETJSON NAC_TAGMAP //HARNESS/254/p/99",
        )
        .await;
    assert_eq!(missing.status, 401);
    assert!(missing.final_text.ends_with("(Unit not found)"));
    let caps = service
        .handle(&mut client, "[caps] CMQTT CAPABILITIES")
        .await;
    let caps: serde_json::Value = serde_json::from_str(&caps.lines[0]).unwrap();
    assert_eq!(caps["project_dirfull"], true);
    assert_eq!(caps["database_json_nac_object_definitions"], false);
    assert_eq!(
        caps["database_json_tagmap_scope"],
        "network-application-group-level-tags"
    );
    assert!(
        tokio::time::timeout(Duration::from_millis(10), remote.read_u8())
            .await
            .is_err(),
        "local project and JSON reads must not write to PCI"
    );
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn event_channel_catalog_and_subscriptions_are_connection_local() {
    let path = state_path();
    let (pci, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let mut first = ClientState::default();
    let mut second = ClientState::default();

    let help = service.handle(&mut first, "[help] EVENT_CHANNEL").await;
    assert_eq!(help.status, 101);
    assert_eq!(
        help.final_text,
        "101 Help:  EVENT_CHANNEL UNSUB - Unsubscribe from event channel specified"
    );
    let list = service
        .handle(&mut first, "[list] EVENT_CHANNEL LIST")
        .await;
    let wire = format_response(&list);
    assert!(wire.starts_with("[list] 130-{\"name\":\"deploy-queue.updated-entries\""));
    assert!(wire.ends_with("[list] 200 OK.\n"));

    assert_eq!(
        service
            .handle(
                &mut first,
                "[sub] EVENT_CHANNEL SUB deploy-queue.updated-entries",
            )
            .await
            .final_text,
        "200 OK: added"
    );
    assert_eq!(
        service
            .handle(
                &mut first,
                "[again] EVENT_CHANNEL SUB deploy-queue.updated-entries",
            )
            .await
            .final_text,
        "201 Service ready: already subscribed"
    );
    assert_eq!(
        service
            .handle(
                &mut second,
                "[other] EVENT_CHANNEL SUB deploy-queue.updated-entries",
            )
            .await
            .final_text,
        "200 OK: added"
    );
    assert_eq!(
        service
            .handle(
                &mut first,
                "[unsub] EVENT_CHANNEL UNSUB deploy-queue.updated-entries",
            )
            .await
            .final_text,
        "200 OK: removed"
    );
    let invalid = service
        .handle(&mut first, "[bad] EVENT_CHANNEL SUB invalid")
        .await;
    assert_eq!(invalid.lines, ["451-channel does not exist."]);
    assert_eq!(
        format_response(&invalid),
        "[bad] 451-channel does not exist.\n[bad] 400 Syntax Error: Invalid parameter for <channel-type>: invalid\n"
    );
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn advisory_locks_enforce_ownership_and_logout_release() {
    let path = state_path();
    let (pci, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let mut first = ClientState::default();
    let mut second = ClientState::default();
    let object = "//HARNESS/254/p/5";

    let locked = service
        .handle(&mut first, &format!("[lock] LOCK {object}"))
        .await;
    assert_eq!(locked.final_text, format!("225 {object}: Locked."));
    let conflicted = service
        .handle(&mut second, &format!("[conflict] LOCK {object}"))
        .await;
    assert_eq!(conflicted.status, 425);
    assert_eq!(
        conflicted.final_text,
        format!("425 {object}: Already locked by:direct1")
    );
    assert_eq!(
        service
            .handle(&mut second, &format!("[wrong] UNLOCK {object}"))
            .await
            .final_text,
        format!("426 {object}: Unlock failed.")
    );
    assert_eq!(
        service.handle(&mut first, "[query] LOGIN").await.status,
        210,
        "LOGIN query must retain locks"
    );
    assert_eq!(
        service
            .handle(&mut second, &format!("[still] LOCK {object}"))
            .await
            .status,
        425
    );
    assert_eq!(
        service.handle(&mut first, "[logout] LOGOUT").await.status,
        211
    );
    assert_eq!(
        service
            .handle(&mut second, &format!("[after] LOCK {object}"))
            .await
            .status,
        225
    );
    assert_eq!(
        service
            .handle(&mut second, &format!("[unlock] UNLOCK {object}"))
            .await
            .final_text,
        format!("226 {object}: Unlocked.")
    );
    assert_eq!(
        service
            .handle(&mut first, "[missing] LOCK //HARNESS/254/p/99")
            .await
            .status,
        401
    );
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn advisory_locks_are_released_when_real_command_connection_ends() {
    let path = state_path();
    let (pci, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let server = tokio::spawn(service.clone().serve(listener));
    let (mut first_reader, mut first_writer) = connect_command_session(address).await;
    let (mut second_reader, mut second_writer) = connect_command_session(address).await;
    let object = "//HARNESS/254/p/5";

    assert_eq!(
        command_lines(
            &mut first_reader,
            &mut first_writer,
            "lock",
            &format!("LOCK {object}"),
        )
        .await,
        [format!("[lock] 225 {object}: Locked.")]
    );
    assert_eq!(
        command_lines(
            &mut second_reader,
            &mut second_writer,
            "blocked",
            &format!("LOCK {object}"),
        )
        .await,
        [format!("[blocked] 425 {object}: Already locked by:cmd3")]
    );
    drop(first_writer);
    drop(first_reader);
    tokio::time::timeout(Duration::from_secs(2), async {
        loop {
            if service.advisory_locks.lock().await.is_empty() {
                break;
            }
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
    assert_eq!(
        command_lines(
            &mut second_reader,
            &mut second_writer,
            "retry",
            &format!("LOCK {object}"),
        )
        .await,
        [format!("[retry] 225 {object}: Locked.")]
    );
    server.abort();
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn armed_auth_gate_protects_event_mutations_and_advisory_locks() {
    let (service, path) = authed_service();
    let mut client = ClientState::default();
    assert_eq!(
        service
            .handle(&mut client, "[list] EVENT_CHANNEL LIST")
            .await
            .status,
        200
    );
    for command in [
        "EVENT_CHANNEL SUB deploy-queue.debug",
        "DEPLOY_QUEUE ADD Missing",
        "DEPLOY_QUEUE DELETE Missing",
        "DEPLOY_QUEUE DELETE_ALL",
        "DEPLOY_QUEUE RETRY Missing",
        "LOCK //HARNESS/254/p/5",
        "UNLOCK //HARNESS/254/p/5",
    ] {
        assert_eq!(
            service
                .handle(&mut client, &format!("[blocked] {command}"))
                .await
                .final_text,
            "420 LOGIN required",
            "{command}"
        );
    }
    assert_eq!(
        service
            .handle(
                &mut client,
                &format!("[login] LOGIN {}", std::str::from_utf8(AUTH_TOKEN).unwrap()),
            )
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut client, "[lock] LOCK //HARNESS/254/p/5")
            .await
            .status,
        225
    );
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn legacy_database_local_subset_is_durable_and_never_touches_pci() {
    let evidence: serde_json::Value = serde_json::from_str(include_str!(
        "../../../testdata/fixtures/native_cgate_legacy_database.json"
    ))
    .unwrap();
    assert_eq!(evidence["oracle"]["version"], "3.4.0 build 2001");
    assert_eq!(
        evidence["oracle"]["jar_sha256"],
        "3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630"
    );

    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();
    for (tag, command) in [
        ("1", "PROJECT NEW AUX"),
        ("2", "DBCREATENET 1 Auxiliary Cni nowhere"),
        ("3", "DBADDSAFE //AUX/1 Unit 20 Original"),
        ("4", "DBADDSAFE //AUX/1 Unit 21 Occupied"),
        ("5", "DBSET //AUX/1/p/20/TagName Legacy Unit"),
    ] {
        assert_eq!(
            service
                .handle(&mut client, &format!("[{tag}] {command}"))
                .await
                .status,
            200,
            "{command}"
        );
    }
    let filtered = service.handle(&mut client, "[6] DBTAGLIST legacy").await;
    assert_eq!(filtered.status, 342);
    assert_eq!(filtered.final_text, "342 1/p/20/TagName=Legacy Unit");

    let duplicate = service
        .handle(&mut client, "[7] DBSET //AUX/1/p/20/Address 21")
        .await;
    assert_eq!(duplicate.status, 408);
    assert!(duplicate.final_text.contains("duplicate unit addresses"));
    assert_eq!(
        service
            .handle(&mut client, "[8] DBSET //AUX/1/p/20/Address 22")
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut client, "[9] DBRENAMENETSAFE 1 2")
            .await
            .status,
        200
    );
    let tags = service.handle(&mut client, "[10] DBTAGLIST").await;
    let rendered = format_response(&tags);
    assert!(rendered.contains("2/p/22/TagName=Legacy Unit"));

    let add = service
        .handle(&mut client, "[11] DBADD //AUX/2 Unit ignored")
        .await;
    assert_eq!(add.status, 301);
    let oid = add.final_text.trim_start_matches("301 OID=");
    assert_eq!(
        service
            .handle(&mut client, &format!("[11a] DBSET !{oid}/Address 23"))
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut client, &format!("[11b] DBSET !{oid}/TagName Pending"))
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut client, "[12] DBCOPY //AUX/2/p/22 //AUX/2 trailing")
            .await
            .status,
        301
    );
    for (tag, command) in [
        ("13", "DBCREATE"),
        ("15", "DBUPDATE //AUX/2"),
        ("16", "DBVERIFY"),
    ] {
        let response = service
            .handle(&mut client, &format!("[{tag}] {command}"))
            .await;
        assert_eq!(response.status, 408, "{command}: {response:?}");
        assert!(response.final_text.contains("not connected"));
    }
    assert_eq!(
        service
            .handle(&mut client, "[14] DBNEW trailing")
            .await
            .status,
        200
    );

    assert_eq!(
        service
            .handle(&mut client, "[17] PROJECT USE HARNESS")
            .await
            .status,
        200
    );
    let configured = service
        .handle(&mut client, "[18] DBRENAMENETSAFE 254 252")
        .await;
    assert_eq!(configured.status, 408);
    assert!(configured
        .final_text
        .contains("configured hardware project"));
    assert!(
        tokio::time::timeout(Duration::from_millis(20), remote.read_u8())
            .await
            .is_err(),
        "legacy database operations must not write to PCI"
    );

    drop(service);
    let (replacement, _replacement_remote) = pci();
    let restarted = Service::new(&fixture(), None, path.clone(), replacement, None).unwrap();
    let mut restarted_client = ClientState::default();
    assert_eq!(
        restarted
            .handle(&mut restarted_client, "[19] PROJECT USE AUX")
            .await
            .status,
        200
    );
    let persisted = restarted
        .handle(&mut restarted_client, "[20] DBTAGLIST legacy")
        .await;
    assert_eq!(persisted.status, 401);
    assert!(persisted.final_text.contains("No objects found"));
    std::fs::remove_file(path).unwrap();
}

#[tokio::test(start_paused = true)]
async fn legacy_database_physical_lifecycle_syncs_commits_and_survives_restart() {
    let path = state_path();
    let (pci_client, remote) = pci();
    let (remote_read, mut remote_write) = tokio::io::split(remote);
    let mut remote_read = BufReader::new(remote_read);
    let reset = tokio::spawn({
        let pci_client = pci_client.clone();
        async move { pci_client.pci_reset().await }
    });
    for _ in 0..8 {
        database_pci_line(&mut remote_read).await;
    }
    reset.await.unwrap().unwrap();

    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();

    // Persist an incomplete DBADD record before any physical work.  Its NULL
    // address/name and assigned UnitType must survive the daemon boundary.
    let pending = service
        .handle(&mut client, "[1] DBADD //HARNESS/254 Unit trailing")
        .await;
    assert_eq!(pending.status, 301);
    let pending_oid = pending
        .final_text
        .trim_start_matches("301 OID=")
        .to_string();
    assert_eq!(
        service
            .handle(
                &mut client,
                &format!("[2] DBSET !{pending_oid}/UnitType KEYM4"),
            )
            .await
            .status,
        200
    );

    // Database-address validation wins before physical I/O. An absent target
    // must not consume the interface transaction that follows.
    assert_eq!(
        service
            .handle(&mut client, "[2a] DBUPDATE //HARNESS/99 UnitDelete")
            .await
            .status,
        401
    );

    // DBVERIFY refreshes the PCI first.  The fixture database has unit 5;
    // live inventory has only unit 6, so both sides of the mismatch appear.
    let verify = service.handle(&mut client, "[3] DBVERIFY trailing");
    let peer = serve_database_sync(&mut remote_read, &mut remote_write, 6, "RELAY4", "1.0.00");
    let (verify, ()) = tokio::join!(verify, peer);
    assert_eq!(verify.status, 408, "{verify:?}");
    assert_eq!(verify.lines.len(), 2, "{verify:?}");

    // UnitDelete refreshes again and atomically replaces the database
    // inventory. No PCI write beyond the read-only SYNC exchange occurs.
    let update = service.handle(&mut client, "[4] DBUPDATE //HARNESS/254 UnitDelete ignored");
    let peer = serve_database_sync(&mut remote_read, &mut remote_write, 6, "RELAY4", "1.0.00");
    let (update, ()) = tokio::join!(update, peer);
    assert_eq!(update.status, 200, "{update:?}");

    let verify = service.handle(&mut client, "[5] DBVERIFY");
    let peer = serve_database_sync(&mut remote_read, &mut remote_write, 6, "RELAY4", "1.0.00");
    let (verify, ()) = tokio::join!(verify, peer);
    assert_eq!(verify.status, 200, "{verify:?}");
    drop(service);

    let (restart_pci, _restart_remote) = pci();
    let restarted = Service::new(&fixture(), None, path.clone(), restart_pci, None).unwrap();
    let mut restarted_client = ClientState::default();
    assert_eq!(
        restarted
            .handle(
                &mut restarted_client,
                &format!("[6] DBGET !{pending_oid}/UnitType"),
            )
            .await
            .final_text,
        format!("342 !{pending_oid}/UnitType=KEYM4")
    );
    assert_eq!(
        restarted
            .handle(
                &mut restarted_client,
                "[7] DBGET //HARNESS/254/p/6/UnitType"
            )
            .await
            .status,
        200
    );
    assert_eq!(
        restarted
            .handle(&mut restarted_client, "[8] DBGET //HARNESS/254/p/5")
            .await
            .status,
        401
    );
    assert_eq!(
        restarted
            .handle(
                &mut restarted_client,
                &format!("[9] DBSET !{pending_oid}/Address 7"),
            )
            .await
            .status,
        200
    );
    assert_eq!(
        restarted
            .handle(
                &mut restarted_client,
                &format!("[10] DBSET !{pending_oid}/TagName Restarted"),
            )
            .await
            .status,
        200
    );
    assert!(format_response(
        &restarted
            .handle(&mut restarted_client, "[11] DBTAGLIST Restarted")
            .await
    )
    .contains("254/p/7/TagName=Restarted"));
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn administrative_runtime_commands_are_stateful_durable_and_redact_secrets() {
    let path = state_path();
    let (pci_client, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();

    assert_eq!(
        service
            .handle(&mut client, "[repo] REPOSITORY USE 1")
            .await
            .final_text,
        "200 OK."
    );
    assert_eq!(
        service
            .handle(&mut client, "[bad-repo] REPOSITORY USE 2")
            .await
            .status,
        408
    );
    assert_eq!(
        service
            .handle(&mut client, "[repair] PROJECT REPAIR HARNESS")
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(
                &mut client,
                "[check] CONVERTUNIT CHECK 1 //HARNESS/254/p/5 KEYGL5 5035TX",
            )
            .await
            .final_text,
        "200 yes"
    );
    assert_eq!(
        service
            .handle(
                &mut client,
                "[convert] CONVERTUNIT CONVERT 1 //HARNESS/254/p/5 KEYE1 5031NMM",
            )
            .await
            .status,
        200
    );

    let uploaded = service
        .handle_document(
            &mut client,
            "[upload] FILE UPLOAD macro.txt",
            "Tk9PUApBUElWRVIK",
        )
        .await;
    assert_eq!(uploaded.status, 200, "{uploaded:?}");
    let run = service.handle(&mut client, "[run] RUN macro.txt").await;
    assert_eq!(run.status, 200, "{run:?}");
    assert_eq!(
        run.lines,
        ["110-macro.txt", "112-NOOP", "112-APIVER", "111-macro.txt"]
    );
    assert_eq!(
        service
            .handle(&mut client, "[quiet] RUN macro.txt QUIET")
            .await
            .lines,
        Vec::<String>::new()
    );
    assert_eq!(
        service
            .handle_document(
                &mut client,
                "[loop-upload] FILE UPLOAD loop.txt",
                "UlVOIGxvb3AudHh0Cg==",
            )
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut client, "[loop] RUN loop.txt")
            .await
            .status,
        412
    );

    let _ = service
        .handle(&mut client, "[login] LOGIN operator top-secret")
        .await;
    assert_eq!(
        service
            .handle(&mut client, "[extract] LOG EXTRACT 1 audit.log")
            .await
            .status,
        200
    );
    let audit = {
        let model = service.model.lock().await;
        String::from_utf8(crate::file::read_bytes(&model, "audit.log").unwrap()).unwrap()
    };
    assert!(audit.contains("LOGIN <redacted>"));
    assert!(!audit.contains("top-secret"));
    assert!(audit.contains("PROJECT REPAIR HARNESS"));

    let mut shutdown = service.subscribe_shutdown();
    assert_eq!(
        service
            .handle(&mut client, "[premature] CONFIRM")
            .await
            .status,
        408
    );
    assert_eq!(
        service
            .handle(&mut client, "[shutdown] SHUTDOWN")
            .await
            .status,
        600
    );
    assert_eq!(
        service
            .handle(&mut client, "[confirm] CONFIRM")
            .await
            .status,
        206
    );
    tokio::time::timeout(Duration::from_millis(100), shutdown.recv())
        .await
        .unwrap()
        .unwrap();

    assert!(
        tokio::time::timeout(Duration::from_millis(20), remote.read_u8())
            .await
            .is_err(),
        "administrative database commands must not write to PCI"
    );
    drop(service);

    let (replacement, _replacement_remote) = pci();
    let restarted = Service::new(&fixture(), None, path.clone(), replacement, None).unwrap();
    assert_eq!(
        restarted.model.lock().await.projects["HARNESS"].networks[&254].units[&5].unit_type,
        "KEYE1"
    );
    assert_eq!(
        restarted.model.lock().await.projects["HARNESS"].networks[&254].units[&5].fields
            ["CatalogNumber"],
        "5031NMM"
    );
    {
        let model = restarted.model.lock().await;
        assert!(crate::file::read_bytes(&model, "audit.log").is_ok());
    }
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn access_control_close_and_lock_use_exact_once_native_frames() {
    let path = state_path();
    let (pci_client, remote) = pci();
    let (remote_read, mut remote_write) = tokio::io::split(remote);
    let mut remote_read = BufReader::new(remote_read);
    let reset = tokio::spawn({
        let pci = pci_client.clone();
        async move { pci.pci_reset().await }
    });
    for _ in 0..8 {
        let mut line = Vec::new();
        remote_read.read_until(b'\r', &mut line).await.unwrap();
    }
    reset.await.unwrap().unwrap();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();

    for (command, expected) in [
        (
            "ACCESSCONTROL CLOSE //HARNESS/254/213 7 9",
            b"\\05D50002070914".as_slice(),
        ),
        (
            "ACCESS_CONTROL LOCK //HARNESS/254/213 7 9",
            b"\\05D5000A07090C".as_slice(),
        ),
    ] {
        let task = tokio::spawn({
            let service = service.clone();
            let command = command.to_string();
            async move {
                service
                    .handle(
                        &mut ClientState::default(),
                        &format!("[access-control] {command}"),
                    )
                    .await
            }
        });
        let mut frame = Vec::new();
        remote_read.read_until(b'\r', &mut frame).await.unwrap();
        assert!(frame.starts_with(expected), "{command}: {frame:?}");
        let confirmation = frame[frame.len() - 2];
        remote_write.write_all(&[confirmation, b'.']).await.unwrap();
        assert_eq!(task.await.unwrap().status, 200, "{command}");
    }

    for command in [
        "ACCESSCONTROL CLOSE //HARNESS/254/56 7 9",
        "ACCESSCONTROL LOCK //HARNESS/254/213 256 9",
    ] {
        assert!(
            service
                .handle(&mut ClientState::default(), &format!("[bad] {command}"))
                .await
                .status
                >= 400
        );
    }
    assert!(
        tokio::time::timeout(Duration::from_millis(20), remote_read.read_u8())
            .await
            .is_err(),
        "invalid Access Control commands must fail before PCI I/O"
    );
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn test_spam_runs_lists_stops_and_removes_background_sessions() {
    let path = state_path();
    let (pci_client, remote) = pci();
    let (remote_read, mut remote_write) = tokio::io::split(remote);
    let mut remote_read = BufReader::new(remote_read);
    let reset = tokio::spawn({
        let pci = pci_client.clone();
        async move { pci.pci_reset().await }
    });
    for _ in 0..8 {
        let mut line = Vec::new();
        remote_read.read_until(b'\r', &mut line).await.unwrap();
    }
    reset.await.unwrap().unwrap();
    let service = Service::new(&fixture(), None, path.clone(), pci_client, None).unwrap();
    let mut client = ClientState::default();

    let started = service
        .handle(
            &mut client,
            "[lighting] TEST_SPAM LIGHTING //HARNESS/254 1 1",
        )
        .await;
    assert_eq!(started.status, 200, "{started:?}");
    assert!(started.lines[0].starts_with("301-id="));
    let mut lighting = Vec::new();
    remote_read.read_until(b'\r', &mut lighting).await.unwrap();
    assert!(lighting.starts_with(b"\\0538"), "{lighting:?}");
    remote_write
        .write_all(&[lighting[lighting.len() - 2], b'.'])
        .await
        .unwrap();
    tokio::time::timeout(Duration::from_millis(200), async {
        loop {
            if service
                .handle(&mut client, "[list] TEST_SPAM LIST")
                .await
                .status
                == 350
            {
                break;
            }
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();

    let started = service
        .handle(
            &mut client,
            "[ereport] TEST_SPAM EREPORT //HARNESS/254 60000",
        )
        .await;
    let id = started.lines[0]
        .strip_prefix("301-id=")
        .unwrap()
        .parse::<u64>()
        .unwrap();
    let listed = service
        .handle(&mut client, "[list-active] TEST_SPAM LIST")
        .await;
    assert_eq!(listed.status, 300);
    assert!(listed.final_text.contains("type=ereport"));
    let mut ereport = Vec::new();
    remote_read.read_until(b'\r', &mut ereport).await.unwrap();
    assert!(ereport.starts_with(b"\\05CE"), "{ereport:?}");
    let stopped = service
        .handle(&mut client, &format!("[stop] TEST_SPAM STOP {id}"))
        .await;
    assert_eq!(stopped.status, 200, "{stopped:?}");
    remote_write
        .write_all(&[ereport[ereport.len() - 2], b'.'])
        .await
        .unwrap();
    tokio::time::timeout(Duration::from_millis(200), async {
        loop {
            if service
                .handle(&mut client, "[list-empty] TEST_SPAM LIST")
                .await
                .status
                == 350
            {
                break;
            }
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn programming_native_handler_floors_deny_before_dispatch_or_mutation() {
    let path = state_path();
    let (pci, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let before = std::fs::read(&path).unwrap();
    let mut events = service.events.subscribe();
    let evidence: serde_json::Value = serde_json::from_str(include_str!(
        "../../../testdata/fixtures/native_cgate_programming_authorization_probe.json"
    ))
    .unwrap();

    for (path_name, minimum) in crate::access::NATIVE_PROBED_PROGRAMMING_COMMANDS {
        let command = evidence["commands"]
            .as_array()
            .unwrap()
            .iter()
            .filter_map(serde_json::Value::as_str)
            .find(|command| *command == *path_name || command.starts_with(&format!("{path_name} ")))
            .unwrap();
        for level in [
            CgateAccessLevel::None,
            CgateAccessLevel::Connect,
            CgateAccessLevel::Monitor,
            CgateAccessLevel::Operate,
            CgateAccessLevel::Admin,
            CgateAccessLevel::Program,
            CgateAccessLevel::Debug,
            CgateAccessLevel::Clipsal,
        ] {
            if level >= *minimum {
                continue;
            }
            let mut client = ClientState {
                access_level: Some(level),
                ..ClientState::default()
            };
            let reply = service
                .handle(&mut client, &format!("[matrix] {command}"))
                .await;
            assert_eq!(
                reply.final_text,
                "420 Access denied.",
                "{command} at {}: {reply:?}",
                level.name()
            );
            assert_eq!(std::fs::read(&path).unwrap(), before, "{command}");
            assert!(events.try_recv().is_err(), "{command} emitted an event");
            let mut byte = [0];
            assert!(
                tokio::time::timeout(Duration::from_millis(1), remote.read(&mut byte))
                    .await
                    .is_err(),
                "{command} reached PCI"
            );
        }
    }

    let model = service.model.lock().await;
    assert!(model.sessions.is_empty());
    assert!(model.locks.is_empty());
    assert!(model.programmers.is_empty());
    assert!(model.deploy_queue.is_empty());
    drop(model);
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn programming_login_downgrade_and_logout_preserve_owned_session() {
    let path = state_path();
    let (pci, mut remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let mut owner = ClientState::default();
    for command in [
        "[1] ACCESS ADD user programmer owned-test-password Program",
        "[2] PP LOCK Owned //HARNESS/254",
        "[3] PP START Session Owned",
    ] {
        assert_eq!(
            service.handle(&mut owner, command).await.status,
            200,
            "{command}"
        );
    }
    assert_eq!(
        service
            .handle(&mut owner, "[4] LOGIN programmer owned-test-password")
            .await
            .status,
        211
    );
    let before = std::fs::read(&path).unwrap();
    assert_eq!(
        service
            .handle(&mut owner, "[5] PP END Session")
            .await
            .final_text,
        "420 Access denied."
    );
    assert!(service.model.lock().await.sessions.contains_key("Session"));
    assert!(owner.sessions.contains("Session"));
    assert_eq!(std::fs::read(&path).unwrap(), before);
    // A fresh Clipsal connection has the role but not the PP ownership.
    let mut other = ClientState::default();
    assert_eq!(
        service
            .handle(&mut other, "[6] PP END Session")
            .await
            .status,
        420
    );
    assert!(service.model.lock().await.sessions.contains_key("Session"));
    // The Program role can manage its own empty programmer queue.
    assert_eq!(
        service
            .handle(&mut owner, "[7] PROGRAMMER CREATE Queue Owned local")
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut owner, "[8] PROGRAMMER DELETE Queue")
            .await
            .status,
        200
    );
    assert_eq!(service.handle(&mut owner, "[9] LOGOUT").await.status, 211);
    assert_eq!(
        service
            .handle(&mut owner, "[10] PP END Session")
            .await
            .status,
        200
    );
    assert_eq!(
        service
            .handle(&mut owner, "[11] PP UNLOCK Owned")
            .await
            .status,
        200
    );
    let mut byte = [0];
    assert!(
        tokio::time::timeout(Duration::from_millis(10), remote.read(&mut byte))
            .await
            .is_err()
    );
    std::fs::remove_file(path).unwrap();
}
