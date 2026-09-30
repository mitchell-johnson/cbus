//! Database PP names must not replace identically named unit metadata.
use super::*;

pub(crate) fn fixture() -> Server {
    let mut server = Server::new(AccessLevel::Program).with_programming(true);
    for command in [
        "[test] PROJECT NEW PPSTORE",
        "[test] PROJECT USE PPSTORE",
        "[test] DBCREATENET 254 Local Cni 127.0.0.1:1",
        "[test] DBADDSAFE //PPSTORE/254 Unit 20 Original",
        "[test] DBSETSAFE //PPSTORE/254/p/20/UnitType SYNTH",
        "[test] DBSETSAFE //PPSTORE/254/p/20/FirmwareVersion 1.0.00",
    ] {
        assert_eq!(server.handle(command).status, 200, "{command}");
    }
    let oid = server.projects["PPSTORE"].networks[&254].units[&20]
        .oid
        .clone();
    let xml = format!("<Unit><OID>{oid}</OID><TagName>Original</TagName><Address>20</Address><UnitType>SYNTH</UnitType><UnitName>Original</UnitName><FirmwareVersion>1.0.00</FirmwareVersion><PP Name=\"UnitType\" Value=\"0x12 0x34\"/><PP Name=\"UnknownParameter\" Value=\"verbatim value\"/></Unit>");
    let reply = server.handle_document("[test] DBSETXML //PPSTORE/254/p/20", &xml);
    assert_eq!(reply.status, 301, "{reply:?}");
    server
}

pub(crate) fn assert_namespace(server: &Server, project: &str, address: u8) {
    let unit = &server.projects[project].networks[&254].units[&address];
    assert_eq!(unit.field("UnitType"), "SYNTH");
    let pp = server.stored_unit_pp_values(project, unit);
    assert_eq!(pp["UnitType"], "0x12 0x34");
    assert_eq!(pp["UnknownParameter"], "verbatim value");
    let xml = server.unit_xml_document(project, unit);
    assert!(xml.contains("<UnitType>SYNTH</UnitType>"), "{xml}");
    assert!(
        xml.contains("<PP Name=\"UnitType\" Value=\"0x12 0x34\"/>"),
        "{xml}"
    );
}

#[test]
fn scalar_and_pp_names_survive_xml_copy_address_and_saved_project() {
    let mut server = fixture();
    assert_namespace(&server, "PPSTORE", 20);
    assert_eq!(
        server
            .handle("[test] DBCOPYSAFE //PPSTORE/254/p/20 //PPSTORE/254 21 Copy")
            .status,
        200
    );
    assert_namespace(&server, "PPSTORE", 21);
    let moved = server
        .unit_xml_document(
            "PPSTORE",
            &server.projects["PPSTORE"].networks[&254].units[&21],
        )
        .replace("<Address>21</Address>", "<Address>22</Address>");
    assert_eq!(
        server
            .handle_document("[move] DBSETXML //PPSTORE/254/p/21", &moved)
            .status,
        301
    );
    assert_namespace(&server, "PPSTORE", 22);
    assert_eq!(server.handle("[test] PROJECT SAVE PPSTORE").status, 200);
    assert_eq!(server.handle("[test] PROJECT CLOSE PPSTORE").status, 200);
    assert_eq!(server.handle("[test] PROJECT LOAD PPSTORE").status, 200);
    assert_namespace(&server, "PPSTORE", 20);
    assert_namespace(&server, "PPSTORE", 22);
}

#[test]
fn project_tables_roundtrip_preserves_pp_and_legacy_does_not_invent_identity_values() {
    let mut server = fixture();
    let encoded = serde_json::to_vec(&server.project_tables("PPSTORE")).unwrap();
    let tables: ProjectTables = serde_json::from_slice(&encoded).unwrap();
    server
        .projects
        .insert("COPY".to_string(), server.projects["PPSTORE"].clone());
    server.apply_project_tables("PPSTORE", "COPY", tables);
    assert_namespace(&server, "COPY", 20);
    let mut legacy: serde_json::Value = serde_json::from_slice(&encoded).unwrap();
    legacy.as_object_mut().unwrap().remove("unit_pp_values");
    let old: ProjectTables = serde_json::from_value(legacy).unwrap();
    server
        .projects
        .insert("LEGACY".to_string(), server.projects["PPSTORE"].clone());
    server.apply_project_tables("PPSTORE", "LEGACY", old);
    let unit = &server.projects["LEGACY"].networks[&254].units[&20];
    let values = server.stored_unit_pp_values("LEGACY", unit);
    assert!(!values.contains_key("UnitType"));
    assert_eq!(values["UnknownParameter"], "verbatim value");
    let xml = server.unit_xml_document("LEGACY", unit);
    assert!(xml.contains("<UnitType>SYNTH</UnitType>"), "{xml}");
    assert!(!xml.contains("<PP Name=\"UnitType\""), "{xml}");
    assert!(!xml.contains("Value=\"\""), "{xml}");
}

#[test]
fn invalid_database_pp_load_preserves_the_prior_session() {
    static ID: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
    let dir = std::env::temp_dir().join(format!(
        "cbus-pp-namespace-{}-{}",
        std::process::id(),
        ID.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
    ));
    std::fs::create_dir_all(&dir).unwrap();
    std::fs::write(dir.join("SYNTH.xml"), "<UnitSpecification><Parameters><Param><Name>UnitType</Name><Type>int</Type><Address>$10</Address><ArraySize>2</ArraySize><DefaultValue>0 0</DefaultValue></Param></Parameters></UnitSpecification>").unwrap();
    let mut server = fixture().with_unitspec_dir(dir.clone());
    for command in [
        "[test] PP LOCK L //PPSTORE/254",
        "[test] PP START S L",
        "[test] PP LOAD S /db//PPSTORE/254/p/20",
    ] {
        assert_eq!(server.handle(command).status, 200, "{command}");
    }
    let before = server.sessions["S"].clone();
    let oid = server.projects["PPSTORE"].networks[&254].units[&20]
        .oid
        .clone();
    server.replace_unit_pp_values(
        "PPSTORE",
        &oid,
        20,
        vec![("UnitType".to_string(), "invalid 0x34".to_string())],
    );
    let reply = server.handle("[test] PP LOAD S /db//PPSTORE/254/p/20");
    assert_eq!(reply.status, 408);
    assert_eq!(server.sessions["S"].params, before.params);
    assert_eq!(server.sessions["S"].source, before.source);
    assert_eq!(server.sessions["S"].raw, before.raw);
    std::fs::remove_dir_all(dir).unwrap();
}

#[test]
fn pp_save_preserves_scalar_identity_and_explicit_unit_name_collision() {
    let mut server = fixture();
    let unit = server.projects["PPSTORE"].networks[&254].units[&20].clone();
    let xml = server.unit_xml_document("PPSTORE", &unit).replace(
        "</Unit>",
        "<PP Name=\"UnitName\" Value=\"PP label\"/></Unit>",
    );
    assert_eq!(
        server
            .handle_document("[test] DBSETXML //PPSTORE/254/p/20", &xml)
            .status,
        301
    );
    for command in [
        "[test] PP LOCK L //PPSTORE/254",
        "[test] PP START S L",
        "[test] PP LOAD S /db//PPSTORE/254/p/20",
    ] {
        assert_eq!(server.handle(command).status, 200, "{command}");
    }
    let mut staged = server.sessions["S"].clone();
    staged.params.insert("UnitType".into(), "0x56 0x78".into());
    staged
        .params
        .insert("UnitName".into(), "changed PP label".into());
    staged
        .params
        .insert("Type".into(), "must not rename identity".into());
    staged
        .params
        .insert("Version".into(), "must not rename firmware".into());
    server.pp_persist(&staged).unwrap();
    let unit = &server.projects["PPSTORE"].networks[&254].units[&20];
    assert_eq!(unit.unit_type, "SYNTH");
    assert_eq!(unit.firmware, "1.0.00");
    assert_eq!(unit.field("UnitName"), "Original");
    let values = server.stored_unit_pp_values("PPSTORE", unit);
    assert_eq!(values["UnitType"], "0x56 0x78");
    assert_eq!(values["UnitName"], "changed PP label");
}

#[test]
fn database_load_emits_range_warning_with_success_and_keeps_database_value() {
    let dir = std::env::temp_dir().join(format!("cbus-pp-warning-{}", std::process::id()));
    std::fs::create_dir(&dir).unwrap();
    std::fs::write(dir.join("SYNTH.xml"), "<UnitSpecification><Parameters><Param><Name>Application</Name><Type>int</Type><Address>$10</Address><ArraySize>2</ArraySize><MinValue>$00</MinValue><MaxValue>$FF</MaxValue><DefaultValue>$38 $FF</DefaultValue></Param></Parameters></UnitSpecification>").unwrap();
    let mut server = fixture().with_unitspec_dir(dir.clone());
    let unit = server.projects["PPSTORE"].networks[&254].units[&20].clone();
    server.replace_unit_pp_values(
        "PPSTORE",
        &unit.oid,
        20,
        vec![("Application".into(), "-1 0".into())],
    );
    assert_eq!(server.handle("[test] PP LOCK L //PPSTORE/254").status, 200);
    assert_eq!(server.handle("[test] PP START S L").status, 200);
    let reply = server.handle("[test] PP LOAD S /db//PPSTORE/254/p/20");
    assert_eq!(reply.status, 200);
    assert_eq!(reply.lines, vec!["462-Parameter 'Application' value '-1 0' was reset to default value '$38 $FF' as it is out of range '$00' to '$FF'"]);
    assert_eq!(server.sessions["S"].params["Application"], "$38 $FF");
    assert_eq!(
        server.stored_unit_pp_values("PPSTORE", &unit)["Application"],
        "-1 0"
    );
    std::fs::remove_dir_all(dir).unwrap();
}

#[test]
fn no_spec_load_save_does_not_fabricate_scalar_metadata_pp() {
    let mut server = fixture();
    for command in [
        "[lock] PP LOCK L //PPSTORE/254",
        "[start] PP START S L",
        "[load] PP LOAD S /db//PPSTORE/254/p/20",
    ] {
        assert_eq!(server.handle(command).status, 200, "{command}");
    }
    let params = &server.sessions["S"].params;
    assert_eq!(params["UnitType"], "0x12 0x34");
    assert_eq!(params["UnknownParameter"], "verbatim value");
    for scalar in [
        "OID",
        "TagName",
        "Address",
        "UnitName",
        "FirmwareVersion",
        "CatalogNumber",
        "Type",
        "Version",
    ] {
        assert!(
            !params.contains_key(scalar),
            "unexpected metadata PP {scalar}"
        );
    }
    assert_eq!(server.handle("[save] PP SAVE_TO_SOURCE S").status, 200);
    let unit = &server.projects["PPSTORE"].networks[&254].units[&20];
    let pp = server.stored_unit_pp_values("PPSTORE", unit);
    assert_eq!(pp.len(), 2);
    assert_namespace(&server, "PPSTORE", 20);
}

#[test]
fn spec_save_replaces_old_pp_in_spec_order_and_preserves_channels() {
    let dir = std::env::temp_dir().join(format!("cbus-pp-save-replacement-{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    std::fs::write(dir.join("SYNTH.xml"), "<UnitSpecification><Parameters><Param><Name>ZFirst</Name><Type>int</Type><Address>$12</Address><DefaultValue>7</DefaultValue></Param><Param><Name>UnitType</Name><Type>int</Type><Address>$10</Address><ArraySize>2</ArraySize><DefaultValue>0 0</DefaultValue></Param><Param><Name>AThird</Name><Type>int</Type><Address>$13</Address><DefaultValue>8</DefaultValue></Param></Parameters></UnitSpecification>").unwrap();
    let mut server = fixture().with_unitspec_dir(dir.clone());
    let unit = server.projects["PPSTORE"].networks[&254].units[&20].clone();
    let xml = server.unit_xml_document("PPSTORE", &unit).replace("</Unit>", "<DeviceName>Retained device</DeviceName><OutputChannel><OID>12345678-1234-1234-1234-123456789012</OID><TagName>Channel1</TagName><Address>1</Address></OutputChannel></Unit>");
    assert_eq!(
        server
            .handle_document("[test] DBSETXML //PPSTORE/254/p/20", &xml)
            .status,
        301
    );
    for command in [
        "[test] PP LOCK L //PPSTORE/254",
        "[test] PP START S L",
        "[test] PP LOAD S /db//PPSTORE/254/p/20",
        "[test] PP SAVE_TO_SOURCE S",
    ] {
        assert_eq!(server.handle(command).status, 200, "{command}");
    }
    let unit = &server.projects["PPSTORE"].networks[&254].units[&20];
    assert_eq!(unit.field("UnitType"), "SYNTH");
    assert!(!unit.fields.contains_key("UnknownParameter"));
    assert!(!server
        .db_fields
        .contains_key("//PPSTORE/254/p/20/UnknownParameter"));
    let output = server.unit_xml_document("PPSTORE", unit);
    let doc = roxmltree::Document::parse(&output).unwrap();
    let names = doc
        .root_element()
        .children()
        .filter(|child| child.has_tag_name("PP"))
        .map(|child| child.attribute("Name").unwrap())
        .collect::<Vec<_>>();
    assert_eq!(names, ["ZFirst", "UnitType", "AThird"]);
    assert!(output.contains("<DeviceName>Retained device</DeviceName>"));
    assert!(output.contains("<OutputChannel><OID>12345678-1234-1234-1234-123456789012</OID><TagName>Channel1</TagName><Address>1</Address></OutputChannel>"));
    assert!(!output.contains("UnknownParameter"));
    assert_eq!(server.handle("[test] PROJECT SAVE PPSTORE").status, 200);
    assert_eq!(server.handle("[test] PROJECT CLOSE PPSTORE").status, 200);
    assert_eq!(server.handle("[test] PROJECT LOAD PPSTORE").status, 200);
    let unit = &server.projects["PPSTORE"].networks[&254].units[&20];
    assert_eq!(server.unit_xml_document("PPSTORE", unit), output);
    std::fs::remove_dir_all(dir).unwrap();
}
