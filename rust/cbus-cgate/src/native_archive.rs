//! Native C-Gate 3.4 `PROJECT ARCHIVE`/`RESTORE` project interchange.
//!
//! Build 2001 archives by copying the repository's project file, selected by
//! the archive name's case-insensitive suffix: `.zip` writes one deflated
//! entry, `.gz` writes one GZIP member and any other suffix writes a raw copy.
//! Relative names resolve below `Projects/archived/`. The default
//! `sqlite-file` repository stores a private Schneider SQLite database in a
//! `tagdb.db` entry; the legacy `file` repository stores its Installation XML
//! in a `tagdb.xml` entry. See `rust/testdata/fixtures/native_cgate_project_archive.json`.
//!
//! cmqttd keeps archives inside its controlled FILE namespace. RESTORE admits
//! either payload: Installation XML, or a bounded read-only subset of the
//! Schneider schema-14 SQLite database. Every Network is replayed through the
//! complete `DBSETXML Network` parser on a staged model, so OIDs are kept and
//! any construct that parser cannot represent fails the whole restore.
//! Project-level XML that cmqttd does not model (`Config`,
//! `InstallationDetail`, other Project children) is retained opaquely and
//! written back by the next ARCHIVE. ARCHIVE writes the native `file`
//! repository layout with OIDs; cmqttd never writes Schneider SQLite.

use std::io::{Cursor, Read, Write};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicU64, Ordering};

use serde_json::{Map, Value};

use crate::{
    err, fresh_oid, valid_uuid, xml_escape, xml_fragment_with_inherited_namespaces,
    xml_open_tag_end, DbXmlExtras, Project, Response, Server,
};

/// Native `project.default.archive-dir` default, relative to the FILE root.
pub(crate) const ARCHIVE_ROOT: &str = "Projects/archived/";
/// Largest decoded project payload admitted from, or written to, an archive.
pub(crate) const MAX_PAYLOAD_BYTES: u64 = 16 * 1024 * 1024;
/// Largest admitted expansion of a compressed payload. Native schema-14
/// SQLite archives expand about 38:1; this bounds deflate bombs well below
/// the absolute cap for small inputs.
pub(crate) const MAX_EXPANSION_RATIO: u64 = 1024;
/// Reserved `db_xml_extras` key under a project for unmodeled native
/// Installation/Project content. It is not a UUID, so no object can own it.
pub(crate) const ENVELOPE_KEY: &str = "#native-installation";

const SQLITE_MAGIC: &[u8] = b"SQLite format 3\0";
const SCHNEIDER_SCHEMA_VERSION: i64 = 14;
const DEFAULT_DB_VERSION: &str = "2.3";
const DEFAULT_VERSION: &str = "1.0";
const OID_ELEMENTS: &[&str] = &[
    "Network",
    "Interface",
    "Property",
    "Application",
    "Group",
    "NetVar",
    "Level",
    "Unit",
    "Languages",
    "Language",
];
const DEFAULT_INSTALLATION_DETAIL: &str = "<InstallationDetail><SystemLocation>[unknown]</SystemLocation><HardwarePlatform>[unknown]</HardwarePlatform><Hostname>[unknown]</Hostname><OSName>[unknown]</OSName><OSVersion>[unknown]</OSVersion><HardwareLocation>[unknown]</HardwareLocation><MaintenanceEmail>[unknown]</MaintenanceEmail><Installer><Name>[unknown]</Name></Installer></InstallationDetail>";

static TEMP_SEQUENCE: AtomicU64 = AtomicU64::new(0);

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Container {
    Zip,
    Gzip,
    Raw,
}

/// Native suffix selection: `gt.a(File)`/`gt.b(File)` compare the final
/// four or three characters case-insensitively.
fn container(token: &str) -> Container {
    let lower = token.to_ascii_lowercase();
    if lower.ends_with(".zip") {
        Container::Zip
    } else if lower.ends_with(".gz") {
        Container::Gzip
    } else {
        Container::Raw
    }
}

fn failed(tag: &str, reason: impl AsRef<str>) -> Response {
    err(
        tag,
        408,
        &format!("408 Operation failed: Archive failed: {}", reason.as_ref()),
    )
}

/// Map a native relative archive name into the controlled FILE namespace.
/// Native C-Gate also accepts absolute host paths; cmqttd never does.
fn archive_path(token: &str) -> Result<String, String> {
    let illegal = || format!("Illegal path {token}");
    if token.is_empty()
        || token.starts_with(['/', '\\', '~', '%'])
        || token.contains(':')
        || token.contains("..")
        || token.chars().any(char::is_control)
        || token.ends_with(['/', '\\'])
    {
        return Err(illegal());
    }
    Ok(format!("{ARCHIVE_ROOT}{}", token.replace('\\', "/")))
}

/// `PROJECT ARCHIVE project name` into the native `file` repository layout.
pub(crate) fn archive(server: &mut Server, tag: &str, project: &str, token: &str) -> Response {
    let path = match archive_path(token) {
        Ok(path) => path,
        Err(error) => return failed(tag, error),
    };
    if !server.projects.contains_key(project) {
        return failed(tag, format!("Project {project} not found"));
    }
    if token.to_ascii_lowercase().ends_with(".db") {
        return failed(
            tag,
            "cmqttd cannot write a Schneider SQLite project database; archive as .zip, .gz or .xml",
        );
    }
    match crate::file::regular_file_exists(server, &path) {
        Ok(true) => return failed(tag, "Destination file exists"),
        Ok(false) => {}
        Err(error) => return failed(tag, error),
    }
    let document = match installation_document(server, project) {
        Ok(document) => document,
        Err(error) => return failed(tag, error),
    };
    let bytes = match encode(container(token), document.as_bytes()) {
        Ok(bytes) => bytes,
        Err(error) => return failed(tag, error),
    };
    if bytes.len() as u64 > MAX_PAYLOAD_BYTES {
        return failed(tag, "archive exceeds 16 MiB");
    }
    let mut staged = server.clone();
    if let Err(error) = crate::file::create_parent_directories(&mut staged, &path)
        .and_then(|()| crate::file::write_bytes(&mut staged, &path, bytes))
    {
        return failed(tag, error);
    }
    *server = staged;
    crate::ok(tag, vec![], "200 OK.")
}

/// `PROJECT RESTORE project name` from a native or cmqttd archive.
pub(crate) fn restore(server: &mut Server, tag: &str, project: &str, token: &str) -> Response {
    let path = match archive_path(token) {
        Ok(path) => path,
        Err(error) => return failed(tag, error),
    };
    if server.projects.contains_key(project) {
        return failed(tag, "Destination file exists");
    }
    let bytes = match crate::file::read_bytes(server, &path) {
        Ok(bytes) => bytes,
        Err(error) => return failed(tag, error),
    };
    let imported = match decode(container(token), &bytes).and_then(|payload| import(&payload)) {
        Ok(imported) => imported,
        Err(error) => return failed(tag, error),
    };
    let mut staged = server.clone();
    staged.projects.insert(
        project.to_string(),
        Project {
            tag_networks: Default::default(),
            name: project.to_string(),
            networks: Default::default(),
        },
    );
    staged
        .invalidated_unit_oid_lookups
        .retain(|(name, _)| name != project);
    staged.current = Some(project.to_string());
    for (address, document) in &imported.networks {
        let mut parsed = match crate::TagNetwork::parse(
            document,
            None,
            crate::next_network_seq(&staged.projects[project]),
        ) {
            Ok(record) => record,
            Err(error) => {
                // Assigned legacy rows retain the historical DBSETXML error
                // envelope. New string records have no numeric owner and use
                // the complete tag-record admission error directly.
                if let Ok(number) = address.parse::<u8>() {
                    if number.to_string() == *address {
                        let _ = staged.handle(&format!(
                            "[restore] DBCREATENET {number} RESTORE{number} Cni 127.0.0.1:1"
                        ));
                        let legacy = staged.handle_document(
                            &format!("[restore] DBSETXML //{project}/{address}"),
                            document,
                        );
                        if legacy.status >= 400 {
                            return failed(
                                tag,
                                format!("Network {address}: {}", legacy.final_text),
                            );
                        }
                    }
                }
                return failed(tag, error);
            }
        };
        let assigned = address.parse::<u8>().ok().filter(|number| {
            number.to_string() == *address && parsed.root.field("NetworkNumber") == Some(address)
        });
        if let Some(number) = assigned {
            let created = staged.handle(&format!(
                "[restore] DBCREATENET {number} RESTORE{number} Cni 127.0.0.1:1"
            ));
            if created.status >= 400 {
                return failed(tag, format!("Network {address}: {}", created.final_text));
            }
            parsed.database_network = Some(number);
            staged.register_tag_network(project, parsed);
            if let Err(error) = staged.sync_tag_database_children(project, address) {
                return failed(tag, format!("Network {address}: {error}"));
            }
        } else {
            staged.register_tag_network(project, parsed);
        }
    }
    if imported.envelope != DbXmlExtras::default() {
        staged.db_xml_extras.insert(
            Server::unit_document_key(project, ENVELOPE_KEY),
            imported.envelope,
        );
    }
    // RESTORE neither selects the project nor publishes the helper
    // commands' model-change events.
    staged.current = server.current.clone();
    staged.events = server.events.clone();
    staged.events_lost = server.events_lost;
    *server = staged;
    crate::ok(tag, vec![], "200 OK.")
}

fn encode(container: Container, payload: &[u8]) -> Result<Vec<u8>, String> {
    match container {
        Container::Raw => Ok(payload.to_vec()),
        Container::Gzip => {
            // Native GZIPOutputStream writes MTIME 0, XFL 0 and OS 0.
            let mut encoder = flate2::GzBuilder::new()
                .operating_system(0)
                .write(Vec::new(), flate2::Compression::default());
            encoder
                .write_all(payload)
                .map_err(|error| error.to_string())?;
            let mut bytes = encoder.finish().map_err(|error| error.to_string())?;
            if bytes.len() > 9 {
                bytes[8] = 0;
            }
            Ok(bytes)
        }
        Container::Zip => {
            let mut writer = zip::ZipWriter::new(Cursor::new(Vec::new()));
            let options = zip::write::SimpleFileOptions::default()
                .compression_method(zip::CompressionMethod::Deflated);
            writer
                .start_file("tagdb.xml", options)
                .map_err(|error| error.to_string())?;
            writer
                .write_all(payload)
                .map_err(|error| error.to_string())?;
            Ok(writer
                .finish()
                .map_err(|error| error.to_string())?
                .into_inner())
        }
    }
}

/// Unpack one bounded project payload.
fn decode(container: Container, bytes: &[u8]) -> Result<Vec<u8>, String> {
    let limit = MAX_PAYLOAD_BYTES.min(
        (bytes.len() as u64)
            .saturating_mul(MAX_EXPANSION_RATIO)
            .max(64 * 1024),
    );
    match container {
        Container::Raw => {
            if bytes.len() as u64 > MAX_PAYLOAD_BYTES {
                return Err("project payload exceeds 16 MiB".to_string());
            }
            Ok(bytes.to_vec())
        }
        Container::Gzip => {
            let decoder = flate2::read::MultiGzDecoder::new(bytes);
            bounded_read(decoder, limit).map_err(|error| format!("GZIP archive: {error}"))
        }
        Container::Zip => {
            let mut archive = zip::ZipArchive::new(Cursor::new(bytes))
                .map_err(|error| format!("ZIP archive: {error}"))?;
            if archive.len() != 1 {
                return Err(format!(
                    "ZIP archive must contain exactly one tagdb.xml or tagdb.db entry, found {}",
                    archive.len()
                ));
            }
            let entry = archive
                .by_index(0)
                .map_err(|error| format!("ZIP archive: {error}"))?;
            let name = entry.name().to_string();
            if name != "tagdb.xml" && name != "tagdb.db" {
                return Err(format!("Zip entry tagdb.xml not found (found {name})"));
            }
            if entry.encrypted() || entry.is_dir() {
                return Err(format!("Zip entry {name} is not a plain file"));
            }
            if !matches!(
                entry.compression(),
                zip::CompressionMethod::Stored | zip::CompressionMethod::Deflated
            ) {
                return Err(format!(
                    "Zip entry {name} uses an unsupported compression method"
                ));
            }
            if entry.size() > limit {
                return Err(format!("Zip entry {name} expands beyond the archive limit"));
            }
            let payload =
                bounded_read(entry, limit).map_err(|error| format!("Zip entry {name}: {error}"))?;
            let is_sqlite = payload.starts_with(SQLITE_MAGIC);
            if (name == "tagdb.db") != is_sqlite {
                return Err(format!(
                    "Zip entry {name} does not contain the expected payload"
                ));
            }
            Ok(payload)
        }
    }
}

fn bounded_read(reader: impl Read, limit: u64) -> Result<Vec<u8>, String> {
    let mut output = Vec::new();
    reader
        .take(limit + 1)
        .read_to_end(&mut output)
        .map_err(|error| error.to_string())?;
    if output.len() as u64 > limit {
        return Err("payload expands beyond the archive limit".to_string());
    }
    Ok(output)
}

#[derive(Debug, Default)]
struct ImportedProject {
    networks: Vec<(String, String)>,
    envelope: DbXmlExtras,
}

fn import(payload: &[u8]) -> Result<ImportedProject, String> {
    if payload.starts_with(SQLITE_MAGIC) {
        let document = sqlite_installation_document(payload)?;
        return parse_installation(&document);
    }
    let text = std::str::from_utf8(payload)
        .map_err(|_| "project XML is not UTF-8".to_string())?
        .trim_start_matches('\u{feff}');
    parse_installation(text)
}

/// Split a native Installation document into complete Network documents and
/// retained project-level content.
fn parse_installation(source: &str) -> Result<ImportedProject, String> {
    let upper = source.to_ascii_uppercase();
    if upper.contains("<!DOCTYPE") || upper.contains("<!ENTITY") {
        return Err("project XML must not contain DTD or entity declarations".to_string());
    }
    let document = roxmltree::Document::parse(source)
        .map_err(|error| format!("project XML is not well-formed: {error}"))?;
    let root = document.root_element();
    if root.tag_name().namespace().is_some() || root.tag_name().name() != "Installation" {
        return Err("project XML root must be Installation".to_string());
    }
    let mut imported = ImportedProject::default();
    let mut projects = 0;
    for child in root.children().filter(roxmltree::Node::is_element) {
        let namespaced = child.tag_name().namespace().is_some();
        match (namespaced, child.tag_name().name()) {
            (false, "OID") => retain_scalar(&mut imported.envelope, "installation-oid", child)?,
            (false, "DBVersion") => retain_scalar(&mut imported.envelope, "db-version", child)?,
            (false, "Version") => retain_scalar(&mut imported.envelope, "version", child)?,
            // ARCHIVE records its own modification time.
            (false, "Modified") => {}
            (false, "Project") => {
                projects += 1;
                parse_project(child, source, &mut imported)?;
            }
            (false, "InstallationDetail") => {
                if imported
                    .envelope
                    .children
                    .iter()
                    .any(|fragment| fragment.starts_with("<InstallationDetail"))
                {
                    return Err("project XML contains duplicate InstallationDetail".to_string());
                }
                imported
                    .envelope
                    .children
                    .push(xml_fragment_with_inherited_namespaces(child, source)?);
            }
            (_, name) => {
                return Err(format!(
                    "unsupported Installation element {name}; cmqttd cannot place it on ARCHIVE"
                ))
            }
        }
    }
    if projects != 1 {
        return Err("project XML must contain exactly one Project".to_string());
    }
    Ok(imported)
}

fn parse_project(
    project: roxmltree::Node<'_, '_>,
    source: &str,
    imported: &mut ImportedProject,
) -> Result<(), String> {
    for child in project.children().filter(roxmltree::Node::is_element) {
        let namespaced = child.tag_name().namespace().is_some();
        match (namespaced, child.tag_name().name()) {
            (false, "OID") => retain_scalar(&mut imported.envelope, "project-oid", child)?,
            (false, "Description") => retain_scalar(&mut imported.envelope, "description", child)?,
            // RESTORE names the project; native load renames it likewise.
            (false, "TagName" | "Address") => {}
            (false, "Network") => {
                let address = child
                    .children()
                    .find(|node| node.has_tag_name("Address"))
                    .and_then(|node| node.text())
                    .filter(|text| crate::tag_network::valid_address(text))
                    .map(str::to_string)
                    .ok_or_else(|| "project XML Network has no valid Address".to_string())?;
                if imported.networks.iter().any(|(known, _)| *known == address) {
                    return Err(format!("project XML repeats Network {address}"));
                }
                imported
                    .networks
                    .push((address, with_generated_oids(child, source)?));
            }
            _ => imported
                .envelope
                .children
                .push(xml_fragment_with_inherited_namespaces(child, source)?),
        }
    }
    Ok(())
}

fn retain_scalar(
    envelope: &mut DbXmlExtras,
    key: &str,
    node: roxmltree::Node<'_, '_>,
) -> Result<(), String> {
    if node.attributes().len() != 0 || node.children().any(|child| child.is_element()) {
        return Err(format!(
            "project XML {} must be text-only",
            node.tag_name().name()
        ));
    }
    let value = node.text().unwrap_or_default().to_string();
    if key.ends_with("-oid") && !valid_uuid(&value) {
        return Err(format!(
            "project XML {} has an invalid OID",
            node.tag_name().name()
        ));
    }
    if envelope.attributes.insert(key.to_string(), value).is_some() {
        return Err(format!("project XML repeats {}", node.tag_name().name()));
    }
    Ok(())
}

/// Detach one Network and give every modeled object without an OID a fresh
/// identity. The native `file` repository omits OIDs from saved XML and
/// assigns new ones on load; present OIDs are kept exactly.
pub(crate) fn with_generated_oids(
    network: roxmltree::Node<'_, '_>,
    source: &str,
) -> Result<String, String> {
    let fragment = xml_fragment_with_inherited_namespaces(network, source)?;
    let parsed = roxmltree::Document::parse(&fragment)
        .map_err(|_| "detached Network is not well-formed".to_string())?;
    let mut insertions = Vec::new();
    for node in parsed.root_element().descendants().filter(|node| {
        node.is_element()
            && node.tag_name().namespace().is_none()
            && OID_ELEMENTS.contains(&node.tag_name().name())
    }) {
        if node
            .children()
            .any(|child| child.is_element() && child.has_tag_name("OID"))
        {
            continue;
        }
        let start = node.range().start;
        let end = xml_open_tag_end(&fragment, start)
            .ok_or_else(|| "invalid Network XML opening tag".to_string())?;
        if fragment.as_bytes().get(end.saturating_sub(1)) == Some(&b'/') {
            return Err(format!("project XML {} is empty", node.tag_name().name()));
        }
        insertions.push(end + 1);
    }
    let mut output = fragment;
    insertions.sort_unstable();
    for offset in insertions.into_iter().rev() {
        output.insert_str(offset, &format!("<OID>{}</OID>", fresh_oid()));
    }
    Ok(output)
}

/// Native `file` repository Installation XML for one cmqttd project.
fn installation_document(server: &Server, project: &str) -> Result<String, String> {
    let envelope = server
        .db_xml_extras
        .get(&Server::unit_document_key(project, ENVELOPE_KEY))
        .cloned()
        .unwrap_or_default();
    let attribute = |key: &str| envelope.attributes.get(key).map(String::as_str);
    let mut output = String::from("<?xml version=\"1.0\" encoding=\"utf-8\"?>\n<Installation>");
    if let Some(oid) = attribute("installation-oid") {
        output.push_str(&format!("<OID>{}</OID>", xml_escape(oid)));
    }
    output.push_str(&format!(
        "<DBVersion>{}</DBVersion><Version>{}</Version><Modified>{}</Modified>\n<Project>",
        xml_escape(attribute("db-version").unwrap_or(DEFAULT_DB_VERSION)),
        xml_escape(attribute("version").unwrap_or(DEFAULT_VERSION)),
        chrono::Local::now().format("%Y-%m-%dT%H:%M:%S%.3f%:z"),
    ));
    if let Some(oid) = attribute("project-oid") {
        output.push_str(&format!("<OID>{}</OID>", xml_escape(oid)));
    }
    output.push_str(&format!(
        "<TagName>{0}</TagName><Address>{0}</Address>",
        xml_escape(project)
    ));
    if let Some(description) = attribute("description") {
        output.push_str(&format!(
            "<Description>{}</Description>",
            xml_escape(description)
        ));
    }
    output.push('\n');
    for network in server.project_network_documents(project)? {
        output.push_str(&network);
    }
    let mut detail = None;
    for fragment in &envelope.children {
        if fragment.starts_with("<InstallationDetail") {
            detail = Some(fragment.as_str());
        } else {
            output.push_str(fragment);
        }
    }
    output.push_str("</Project>\n");
    output.push_str(detail.unwrap_or(DEFAULT_INSTALLATION_DETAIL));
    output.push_str("</Installation>\n");
    Ok(output)
}

// ---------------------------------------------------------------------------
// Schneider schema-14 SQLite, read-only subset.

/// Tables whose rows are translated into Installation XML.
const HANDLED_TABLES: &[&str] = &[
    "_schema",
    "installation",
    "installation_detail",
    "company_detail",
    "project",
    "tagged_entity",
    "network",
    "interface",
    "application",
    "_group",
    "net_var",
    "level_tag",
    "group_level_tags",
    "net_var_level_tags",
    "tags_dlt_list",
    "tag_dlt",
    "unit",
    "pp_properties",
    "property",
    "config",
    "config_properties",
    "project_configs",
];
/// Migration-seeded DALI catalogue enumerations present in every new
/// database. They carry no project content.
const SEED_TABLES: &[&str] = &["dali_catalog_type", "dali_non_device_param_type"];

const TABLE_COLUMNS: &[(&str, &[&str])] = &[
    ("_schema", &["version", "filename"]),
    (
        "installation",
        &[
            "id",
            "oid",
            "db_version",
            "version",
            "project_id",
            "installation_detail_id",
        ],
    ),
    (
        "installation_detail",
        &[
            "id",
            "oid",
            "system_location",
            "hardware_platform",
            "hostname",
            "os_name",
            "os_version",
            "hardware_location",
            "maintenance_email",
            "note_oid",
            "installer_company_detail_id",
            "consultant_company_detail_id",
            "architect_company_detail_id",
            "owner_company_detail_id",
        ],
    ),
    (
        "company_detail",
        &[
            "id",
            "oid",
            "name",
            "company",
            "address",
            "city",
            "state",
            "postal_code",
            "country",
            "voice_phone",
            "mobile_phone",
            "fax_phone",
            "email",
            "webpage",
        ],
    ),
    ("project", &["id", "oid", "tagged_entity_id"]),
    (
        "tagged_entity",
        &["id", "tag_name", "address", "description", "display_id"],
    ),
    (
        "network",
        &[
            "id",
            "oid",
            "tagged_entity_id",
            "project_id",
            "network_number",
            "network_signature",
            "last_verified",
            "_external",
        ],
    ),
    (
        "interface",
        &[
            "id",
            "oid",
            "interface_type",
            "interface_address",
            "network_id",
        ],
    ),
    (
        "application",
        &["id", "oid", "tagged_entity_id", "network_id"],
    ),
    (
        "_group",
        &[
            "id",
            "oid",
            "tagged_entity_id",
            "application_id",
            "area",
            "phantom",
            "snapshot_id",
            "tags_dlt_list_id",
            "nac_dali_duration_test_timeout",
        ],
    ),
    (
        "net_var",
        &["id", "oid", "tagged_entity_id", "application_id"],
    ),
    (
        "level_tag",
        &["id", "oid", "tagged_entity_id", "value", "tags_dlt_list_id"],
    ),
    ("group_level_tags", &["id", "level_tag_id", "group_id"]),
    ("net_var_level_tags", &["id", "level_tag_id", "net_var_id"]),
    ("tags_dlt_list", &["id"]),
    (
        "tag_dlt",
        &[
            "id",
            "oid",
            "tags_dlt_list_id",
            "language_id",
            "flavour_id",
            "tag_type",
            "tag_value",
        ],
    ),
    (
        "unit",
        &[
            "id",
            "oid",
            "tagged_entity_id",
            "network_id",
            "unit_type",
            "unit_name",
            "serial_number",
            "firmware_version",
            "firmware_version2",
            "last_modified",
            "firmware_checksum",
            "parameter_checksum",
            "catalog_number",
            "burden_enabled",
            "switchable_power_supply_enabled",
            "patch_version",
            "snapshot_id",
            "device_name",
            "group_number",
        ],
    ),
    ("pp_properties", &["id", "property_id", "unit_id"]),
    ("property", &["id", "oid", "name", "value"]),
    ("config", &["id", "oid", "application"]),
    ("config_properties", &["id", "property_id", "config_id"]),
    ("project_configs", &["id", "config_id", "project_id"]),
];

struct TempDatabase(PathBuf);

impl TempDatabase {
    fn new(bytes: &[u8]) -> Result<Self, String> {
        let directory = std::env::temp_dir().join("cmqttd-native-archive");
        std::fs::create_dir_all(&directory).map_err(|error| error.to_string())?;
        let path = directory.join(format!(
            "restore-{}-{}.db",
            std::process::id(),
            TEMP_SEQUENCE.fetch_add(1, Ordering::Relaxed)
        ));
        let mut options = std::fs::OpenOptions::new();
        options.write(true).create_new(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        options
            .open(&path)
            .and_then(|mut file| file.write_all(bytes))
            .map_err(|error| error.to_string())?;
        Ok(Self(path))
    }
}

impl Drop for TempDatabase {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.0);
    }
}

/// Run one read-only query that returns a single JSON value.
fn sqlite_json(path: &Path, sql: &str) -> Result<Value, String> {
    let output = Command::new("sqlite3")
        .args([
            "-readonly",
            "-safe",
            "-batch",
            "-noheader",
            "-bail",
            "-list",
        ])
        .arg(path)
        .arg(sql)
        .stdin(Stdio::null())
        .output()
        .map_err(|error| {
            if error.kind() == std::io::ErrorKind::NotFound {
                "sqlite3 is not installed".to_string()
            } else {
                error.to_string()
            }
        })?;
    if !output.status.success() {
        return Err(format!(
            "unsupported Schneider project database: {}",
            String::from_utf8_lossy(&output.stderr).trim()
        ));
    }
    if output.stdout.len() as u64 > MAX_PAYLOAD_BYTES * 4 {
        return Err("Schneider project database projection exceeds its limit".to_string());
    }
    serde_json::from_slice(&output.stdout)
        .map_err(|error| format!("Schneider project database projection: {error}"))
}

fn identifier(name: &str) -> Result<&str, String> {
    if !name.is_empty()
        && name
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || byte == b'_')
    {
        Ok(name)
    } else {
        Err(format!("unsupported Schneider table name {name:?}"))
    }
}

/// Project one bounded Schneider schema-14 database as Installation XML.
fn sqlite_installation_document(bytes: &[u8]) -> Result<String, String> {
    if bytes.len() as u64 > MAX_PAYLOAD_BYTES {
        return Err("Schneider project database exceeds 16 MiB".to_string());
    }
    let database = TempDatabase::new(bytes)?;
    let catalogue = sqlite_json(
        &database.0,
        "SELECT json_object('tables',(SELECT json_group_array(name) FROM sqlite_master WHERE type='table'))",
    )?;
    let tables = catalogue["tables"]
        .as_array()
        .ok_or("Schneider project database has no table catalogue")?
        .iter()
        .filter_map(Value::as_str)
        .map(str::to_string)
        .collect::<Vec<_>>();
    for (table, _) in TABLE_COLUMNS {
        if !tables.iter().any(|name| name == table) {
            return Err(format!(
                "unsupported Schneider project database: missing table {table}"
            ));
        }
    }
    let others = tables
        .iter()
        .filter(|name| {
            !name.starts_with("sqlite_")
                && !HANDLED_TABLES.contains(&name.as_str())
                && !SEED_TABLES.contains(&name.as_str())
        })
        .map(|name| identifier(name))
        .collect::<Result<Vec<_>, _>>()?;
    if !others.is_empty() {
        let counts = others
            .iter()
            .map(|name| format!("'{name}',(SELECT count(*) FROM \"{name}\")"))
            .collect::<Vec<_>>()
            .join(",");
        let counts = sqlite_json(&database.0, &format!("SELECT json_object({counts})"))?;
        let mut populated = others
            .iter()
            .filter(|name| counts[**name].as_i64().unwrap_or(1) != 0)
            .copied()
            .collect::<Vec<_>>();
        populated.sort_unstable();
        if !populated.is_empty() {
            return Err(format!(
                "Schneider project tables are not supported by cmqttd: {}",
                populated.join(", ")
            ));
        }
    }
    let projection = TABLE_COLUMNS
        .iter()
        .map(|(table, columns)| {
            let fields = columns
                .iter()
                .map(|column| format!("'{column}',\"{column}\""))
                .collect::<Vec<_>>()
                .join(",");
            let order = if columns.contains(&"id") { " ORDER BY id" } else { " ORDER BY version" };
            format!(
                "'{table}',(SELECT json_group_array(json_object({fields})) FROM (SELECT * FROM \"{table}\"{order}))"
            )
        })
        .collect::<Vec<_>>()
        .join(",");
    let rows = sqlite_json(&database.0, &format!("SELECT json_object({projection})"))?;
    SchneiderRows::new(&rows)?.installation()
}

struct SchneiderRows<'a> {
    tables: &'a Map<String, Value>,
    used: std::cell::RefCell<std::collections::HashSet<(&'static str, i64)>>,
}

type Row = Map<String, Value>;

fn text(row: &Row, column: &str) -> Option<String> {
    match row.get(column) {
        Some(Value::String(value)) => Some(value.clone()),
        Some(Value::Number(value)) => Some(value.to_string()),
        _ => None,
    }
}

fn number(row: &Row, column: &str) -> Option<i64> {
    row.get(column).and_then(Value::as_i64)
}

fn element(name: &str, value: &str) -> String {
    format!("<{name}>{}</{name}>", xml_escape(value))
}

fn optional(output: &mut String, name: &str, value: Option<String>) {
    if let Some(value) = value {
        output.push_str(&element(name, &value));
    }
}

impl<'a> SchneiderRows<'a> {
    fn new(value: &'a Value) -> Result<Self, String> {
        let tables = value
            .as_object()
            .ok_or("Schneider project database projection is not an object")?;
        Ok(Self {
            tables,
            used: Default::default(),
        })
    }

    fn rows(&self, table: &str) -> impl Iterator<Item = &'a Row> {
        self.tables
            .get(table)
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .filter_map(Value::as_object)
    }

    fn by_id(&self, table: &'static str, id: Option<i64>) -> Result<&'a Row, String> {
        let id = id.ok_or_else(|| format!("Schneider {table} reference is missing"))?;
        let row = self
            .rows(table)
            .find(|row| number(row, "id") == Some(id))
            .ok_or_else(|| format!("Schneider {table} row {id} is missing"))?;
        self.used.borrow_mut().insert((table, id));
        Ok(row)
    }

    fn children(&self, table: &'static str, column: &str, parent: i64) -> Vec<&'a Row> {
        let rows = self
            .rows(table)
            .filter(|row| number(row, column) == Some(parent))
            .collect::<Vec<_>>();
        let mut used = self.used.borrow_mut();
        for row in &rows {
            if let Some(id) = number(row, "id") {
                used.insert((table, id));
            }
        }
        rows
    }

    fn reject(&self, table: &str, row: &Row, columns: &[&str]) -> Result<(), String> {
        for column in columns {
            if row.get(*column).is_some_and(|value| !value.is_null()) {
                return Err(format!(
                    "Schneider column {table}.{column} is not supported by cmqttd"
                ));
            }
        }
        Ok(())
    }

    fn entity(&self, row: &Row, kind: &str, description: bool) -> Result<(String, String), String> {
        let entity = self.by_id("tagged_entity", number(row, "tagged_entity_id"))?;
        self.reject("tagged_entity", entity, &["display_id"])?;
        if !description {
            self.reject("tagged_entity", entity, &["description"])?;
        }
        let mut output = String::new();
        optional(&mut output, "OID", text(row, "oid"));
        output.push_str(&element(
            "TagName",
            &text(entity, "tag_name").ok_or_else(|| format!("Schneider {kind} has no tag name"))?,
        ));
        optional(&mut output, "Address", text(entity, "address"));
        Ok((output, text(entity, "description").unwrap_or_default()))
    }

    fn tags(&self, list: Option<i64>) -> Result<String, String> {
        let Some(list) = list else {
            return Ok(String::new());
        };
        self.by_id("tags_dlt_list", Some(list))?;
        let tags = self.children("tag_dlt", "tags_dlt_list_id", list);
        if tags.is_empty() {
            return Ok("<TagsDLT/>".to_string());
        }
        let mut output = String::from("<TagsDLT>");
        for tag in tags {
            output.push_str("<TagDLT>");
            optional(&mut output, "OID", text(tag, "oid"));
            optional(&mut output, "LanguageID", text(tag, "language_id"));
            optional(&mut output, "FlavourID", text(tag, "flavour_id"));
            optional(&mut output, "TagType", text(tag, "tag_type"));
            optional(&mut output, "TagValue", text(tag, "tag_value"));
            output.push_str("</TagDLT>");
        }
        output.push_str("</TagsDLT>");
        Ok(output)
    }

    fn levels(
        &self,
        link: &'static str,
        parent_column: &str,
        parent: i64,
    ) -> Result<String, String> {
        let mut output = String::new();
        for link_row in self.children(link, parent_column, parent) {
            let level = self.by_id("level_tag", number(link_row, "level_tag_id"))?;
            let value = text(level, "value").ok_or("Schneider level has no value")?;
            let (identity, _) = self.entity(level, "level", false)?;
            output.push_str(&format!(
                "<Level Value=\"{}\">{identity}{}</Level>",
                xml_escape(&value),
                self.tags(number(level, "tags_dlt_list_id"))?
            ));
        }
        Ok(output)
    }

    fn application(&self, row: &Row) -> Result<String, String> {
        let id = number(row, "id").ok_or("Schneider application has no id")?;
        let (identity, _) = self.entity(row, "application", false)?;
        let mut output = format!("<Application>{identity}");
        for group in self.children("_group", "application_id", id) {
            self.reject(
                "_group",
                group,
                &[
                    "area",
                    "phantom",
                    "snapshot_id",
                    "nac_dali_duration_test_timeout",
                ],
            )?;
            let group_id = number(group, "id").ok_or("Schneider group has no id")?;
            let (identity, _) = self.entity(group, "group", false)?;
            output.push_str(&format!(
                "<Group>{identity}{}{}</Group>",
                self.tags(number(group, "tags_dlt_list_id"))?,
                self.levels("group_level_tags", "group_id", group_id)?
            ));
        }
        for variable in self.children("net_var", "application_id", id) {
            let variable_id = number(variable, "id").ok_or("Schneider NetVar has no id")?;
            let (identity, _) = self.entity(variable, "NetVar", false)?;
            output.push_str(&format!(
                "<NetVar>{identity}{}</NetVar>",
                self.levels("net_var_level_tags", "net_var_id", variable_id)?
            ));
        }
        output.push_str("</Application>");
        Ok(output)
    }

    fn unit(&self, row: &Row) -> Result<String, String> {
        self.reject(
            "unit",
            row,
            &[
                "firmware_version2",
                "last_modified",
                "firmware_checksum",
                "parameter_checksum",
                "burden_enabled",
                "switchable_power_supply_enabled",
                "patch_version",
                "snapshot_id",
            ],
        )?;
        let id = number(row, "id").ok_or("Schneider unit has no id")?;
        let (identity, description) = self.entity(row, "unit", true)?;
        let mut output = format!("<Unit>{identity}");
        if !description.is_empty() {
            output.push_str(&element("Description", &description));
        }
        optional(&mut output, "UnitType", text(row, "unit_type"));
        optional(&mut output, "UnitName", text(row, "unit_name"));
        optional(&mut output, "SerialNumber", text(row, "serial_number"));
        optional(
            &mut output,
            "FirmwareVersion",
            text(row, "firmware_version"),
        );
        for link in self.children("pp_properties", "unit_id", id) {
            let property = self.by_id("property", number(link, "property_id"))?;
            output.push_str(&format!(
                "<PP Name=\"{}\" Value=\"{}\"/>",
                xml_escape(&text(property, "name").unwrap_or_default()),
                xml_escape(&text(property, "value").unwrap_or_default())
            ));
        }
        optional(&mut output, "CatalogNumber", text(row, "catalog_number"));
        optional(&mut output, "DeviceName", text(row, "device_name"));
        optional(&mut output, "GroupNumber", text(row, "group_number"));
        output.push_str("</Unit>");
        Ok(output)
    }

    fn network(&self, row: &Row) -> Result<String, String> {
        self.reject(
            "network",
            row,
            &["network_signature", "last_verified", "_external"],
        )?;
        let id = number(row, "id").ok_or("Schneider network has no id")?;
        let (identity, _) = self.entity(row, "network", false)?;
        let mut output = format!("<Network>{identity}");
        optional(&mut output, "NetworkNumber", text(row, "network_number"));
        let interfaces = self.children("interface", "network_id", id);
        if interfaces.len() != 1 {
            return Err(format!(
                "Schneider network {id} has {} interfaces; cmqttd supports exactly one",
                interfaces.len()
            ));
        }
        let interface = interfaces[0];
        output.push_str("<Interface>");
        optional(&mut output, "OID", text(interface, "oid"));
        optional(
            &mut output,
            "InterfaceType",
            text(interface, "interface_type"),
        );
        optional(
            &mut output,
            "InterfaceAddress",
            text(interface, "interface_address"),
        );
        output.push_str("</Interface>");
        for application in self.children("application", "network_id", id) {
            output.push_str(&self.application(application)?);
        }
        for unit in self.children("unit", "network_id", id) {
            output.push_str(&self.unit(unit)?);
        }
        output.push_str("</Network>");
        Ok(output)
    }

    fn config(&self, project: i64) -> Result<String, String> {
        let mut output = String::new();
        for link in self.children("project_configs", "project_id", project) {
            let config = self.by_id("config", number(link, "config_id"))?;
            let config_id = number(config, "id").ok_or("Schneider config has no id")?;
            output.push_str("<Config>");
            optional(&mut output, "OID", text(config, "oid"));
            optional(&mut output, "Application", text(config, "application"));
            for property_link in self.children("config_properties", "config_id", config_id) {
                let property = self.by_id("property", number(property_link, "property_id"))?;
                output.push_str("<Property>");
                optional(&mut output, "OID", text(property, "oid"));
                output.push_str(&element(
                    "Name",
                    &text(property, "name").unwrap_or_default(),
                ));
                output.push_str(&element(
                    "Value",
                    &text(property, "value").unwrap_or_default(),
                ));
                output.push_str("</Property>");
            }
            output.push_str("</Config>");
        }
        Ok(output)
    }

    fn installation_detail(&self, id: Option<i64>) -> Result<String, String> {
        let detail = self.by_id("installation_detail", id)?;
        self.reject(
            "installation_detail",
            detail,
            &[
                "note_oid",
                "consultant_company_detail_id",
                "architect_company_detail_id",
                "owner_company_detail_id",
            ],
        )?;
        let mut output = String::from("<InstallationDetail>");
        optional(&mut output, "OID", text(detail, "oid"));
        for (column, name) in [
            ("system_location", "SystemLocation"),
            ("hardware_platform", "HardwarePlatform"),
            ("hostname", "Hostname"),
            ("os_name", "OSName"),
            ("os_version", "OSVersion"),
            ("hardware_location", "HardwareLocation"),
            ("maintenance_email", "MaintenanceEmail"),
        ] {
            optional(&mut output, name, text(detail, column));
        }
        if let Some(installer) = number(detail, "installer_company_detail_id") {
            let company = self.by_id("company_detail", Some(installer))?;
            self.reject(
                "company_detail",
                company,
                &[
                    "company",
                    "address",
                    "city",
                    "state",
                    "postal_code",
                    "country",
                    "voice_phone",
                    "mobile_phone",
                    "fax_phone",
                    "email",
                    "webpage",
                ],
            )?;
            output.push_str("<Installer>");
            optional(&mut output, "OID", text(company, "oid"));
            optional(&mut output, "Name", text(company, "name"));
            output.push_str("</Installer>");
        }
        output.push_str("</InstallationDetail>");
        Ok(output)
    }

    fn installation(&self) -> Result<String, String> {
        let version = self
            .rows("_schema")
            .filter_map(|row| number(row, "version"))
            .max();
        if version != Some(SCHNEIDER_SCHEMA_VERSION) {
            return Err(format!(
                "unsupported Schneider project schema version {}",
                version.map_or_else(|| "none".to_string(), |version| version.to_string())
            ));
        }
        let installations = self.rows("installation").collect::<Vec<_>>();
        if installations.len() != 1 {
            return Err("Schneider project database must contain one installation".to_string());
        }
        let installation = installations[0];
        self.used
            .borrow_mut()
            .insert(("installation", number(installation, "id").unwrap_or(0)));
        let project = self.by_id("project", number(installation, "project_id"))?;
        let project_id = number(project, "id").ok_or("Schneider project has no id")?;
        let (identity, description) = self.entity(project, "project", true)?;
        let mut output = String::from("<?xml version=\"1.0\" encoding=\"utf-8\"?>\n<Installation>");
        optional(&mut output, "OID", text(installation, "oid"));
        optional(&mut output, "DBVersion", text(installation, "db_version"));
        optional(&mut output, "Version", text(installation, "version"));
        output.push_str(&format!("<Project>{identity}"));
        if !description.is_empty() {
            output.push_str(&element("Description", &description));
        }
        for network in self.children("network", "project_id", project_id) {
            output.push_str(&self.network(network)?);
        }
        output.push_str(&self.config(project_id)?);
        output.push_str("</Project>");
        output.push_str(&self.installation_detail(number(installation, "installation_detail_id"))?);
        output.push_str("</Installation>");
        self.require_all_rows_used()?;
        Ok(output)
    }

    /// Every content row must have been reached from the installation. An
    /// orphan would otherwise be silently dropped by the XML projection.
    fn require_all_rows_used(&self) -> Result<(), String> {
        let used = self.used.borrow();
        for (table, _) in TABLE_COLUMNS {
            if *table == "_schema" {
                continue;
            }
            let table_name: &'static str = table;
            if let Some(row) = self
                .rows(table)
                .find(|row| number(row, "id").is_none_or(|id| !used.contains(&(table_name, id))))
            {
                return Err(format!(
                    "Schneider {table} row {} is not reachable from the project",
                    number(row, "id").unwrap_or(-1)
                ));
            }
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn archive_names_stay_inside_the_archive_directory() {
        assert_eq!(archive_path("a.zip").unwrap(), "Projects/archived/a.zip");
        assert_eq!(
            archive_path("sub\\a.gz").unwrap(),
            "Projects/archived/sub/a.gz"
        );
        for token in [
            "",
            "/tmp/a.zip",
            "..\\a.zip",
            "a/../../b.zip",
            "C:x.zip",
            "%P%/a",
            "~/a",
            "dir/",
        ] {
            assert!(archive_path(token).is_err(), "{token}");
        }
        assert_eq!(container("A.ZIP"), Container::Zip);
        assert_eq!(container("a.Gz"), Container::Gzip);
        assert_eq!(container("a.zip2"), Container::Raw);
    }

    #[test]
    fn gzip_header_matches_native_and_round_trips() {
        let bytes = encode(Container::Gzip, b"<Installation/>").unwrap();
        assert_eq!(hex::encode(&bytes[..10]), "1f8b0800000000000000");
        assert_eq!(decode(Container::Gzip, &bytes).unwrap(), b"<Installation/>");
    }

    #[test]
    fn zip_containers_are_bounded_and_single_entry() {
        let document = b"<?xml version=\"1.0\"?><Installation/>";
        let zipped = encode(Container::Zip, document).unwrap();
        assert_eq!(decode(Container::Zip, &zipped).unwrap(), document);

        let build = |entries: &[(&str, &[u8])]| {
            let mut writer = zip::ZipWriter::new(Cursor::new(Vec::new()));
            let options = zip::write::SimpleFileOptions::default()
                .compression_method(zip::CompressionMethod::Deflated);
            for (name, bytes) in entries {
                writer.start_file(*name, options).unwrap();
                writer.write_all(bytes).unwrap();
            }
            writer.finish().unwrap().into_inner()
        };
        let two = build(&[("tagdb.xml", document), ("extra.bin", b"x")]);
        assert!(decode(Container::Zip, &two)
            .unwrap_err()
            .contains("exactly one"));
        let named = build(&[("project.xml", document)]);
        assert!(decode(Container::Zip, &named)
            .unwrap_err()
            .starts_with("Zip entry tagdb.xml not found"));
        let mislabeled = build(&[("tagdb.db", document)]);
        assert!(decode(Container::Zip, &mislabeled)
            .unwrap_err()
            .contains("expected payload"));
        let bomb = build(&[("tagdb.xml", &vec![b' '; 17 * 1024 * 1024])]);
        assert!(decode(Container::Zip, &bomb)
            .unwrap_err()
            .contains("expands beyond"));
        let mut encoder = flate2::write::GzEncoder::new(Vec::new(), flate2::Compression::best());
        encoder.write_all(&vec![0; 8 * 1024 * 1024]).unwrap();
        let gz_bomb = encoder.finish().unwrap();
        assert!(decode(Container::Gzip, &gz_bomb)
            .unwrap_err()
            .contains("expands beyond"));
    }

    #[test]
    fn file_repository_xml_gains_oids_and_keeps_project_content() {
        let source = concat!(
            "<?xml version=\"1.0\" encoding=\"utf-8\"?>\n<Installation><DBVersion>2.3</DBVersion>",
            "<Version>1.0</Version><Modified>x</Modified><Project><TagName>SRC</TagName>",
            "<Address>SRC</Address><Description>Synthetic</Description><Network><TagName>Local</TagName>",
            "<Address>254</Address><NetworkNumber>254</NetworkNumber><Interface><InterfaceType>Cni",
            "</InterfaceType><InterfaceAddress>127.0.0.1:1</InterfaceAddress></Interface></Network>",
            "<Config><Application>cgate</Application></Config></Project><InstallationDetail>",
            "<Installer><Name>[unknown]</Name></Installer></InstallationDetail></Installation>"
        );
        let imported = parse_installation(source).unwrap();
        assert_eq!(imported.networks.len(), 1);
        let network = &imported.networks[0].1;
        assert_eq!(network.matches("<OID>").count(), 2, "{network}");
        assert_eq!(imported.envelope.attributes["description"], "Synthetic");
        assert_eq!(imported.envelope.children.len(), 2);
        assert!(parse_installation("<Installation><Other/></Installation>").is_err());
        assert!(parse_installation("<Installation/>").is_err());
    }
}
