//! Sandboxed implementation of C-Gate's repository transformation family.
//!
//! cmqttd cannot expose C-Gate's host `tag/` and `transform/` directories, so
//! command names resolve inside the durable virtual FILE namespace. XML/SQL
//! exchange uses a real SQLite database with an explicit, portable cmqttd
//! schema. This makes every conversion deterministic and reversible without
//! pretending that cmqttd's JSON repository is Schneider's private schema.

use super::{err, ok};
use crate::{file, Response, Server};
use std::{
    fs,
    path::{Path, PathBuf},
    process::{Command, Stdio},
    sync::atomic::{AtomicU64, Ordering},
};

const MAX_TRANSFORM_BYTES: usize = 16 * 1024 * 1024;
const PORTABLE_SCHEMA_VERSION: u32 = 14;
const APPLICATION_ID: u32 = 0x4342_5553; // "CBUS"
static TEMP_SEQUENCE: AtomicU64 = AtomicU64::new(0);

pub(crate) fn command(model: &mut Server, tag: &str, words: &[&str]) -> Response {
    if words.len() < 2 {
        return syntax(tag);
    }
    match words[1].to_ascii_uppercase().as_str() {
        "MIGRATE_SQL" => migrate_sql(model, tag, words),
        "SQL_TO_XML" => sql_to_xml(model, tag, words, false),
        "SQL_TO_XML_CGATE2" => sql_to_xml(model, tag, words, true),
        "XML_TO_SQL" => xml_to_sql(model, tag, words),
        "PROJECT" => transform_project(model, tag, words),
        _ => syntax(tag),
    }
}

fn syntax(tag: &str) -> Response {
    err(tag, 400, "400 Syntax Error.")
}

fn failed(tag: &str, message: impl AsRef<str>) -> Response {
    err(
        tag,
        408,
        &format!(
            "408 Operation failed: Transform failed: {}",
            message.as_ref()
        ),
    )
}

fn migrate_sql(model: &mut Server, tag: &str, words: &[&str]) -> Response {
    if words.len() != 3 {
        return syntax(tag);
    }
    let (source_name, source) = match read_with_extension(model, words[2], ".db") {
        Ok(value) => value,
        Err(error) => return failed(tag, error),
    };
    let database = match TempArtifact::new("migrate", "db", &source) {
        Ok(file) => file,
        Err(error) => return failed(tag, error),
    };
    if let Err(error) = verify_portable_database(database.path()) {
        return failed(tag, error);
    }
    let sql = format!(
        "BEGIN IMMEDIATE; UPDATE cmqttd_project SET schema_version={PORTABLE_SCHEMA_VERSION}; PRAGMA user_version={PORTABLE_SCHEMA_VERSION}; COMMIT;"
    );
    if let Err(error) = sqlite(database.path(), &sql) {
        return failed(tag, error);
    }
    let bytes = match bounded_read(database.path()) {
        Ok(bytes) => bytes,
        Err(error) => return failed(tag, error),
    };
    if let Err(error) = file::write_bytes(model, &source_name, bytes) {
        return failed(tag, error);
    }
    ok(tag, vec![], "200 OK.")
}

fn xml_to_sql(model: &mut Server, tag: &str, words: &[&str]) -> Response {
    if !(3..=4).contains(&words.len()) {
        return syntax(tag);
    }
    let (_, xml) = match read_with_extension(model, words[2], ".xml") {
        Ok(value) => value,
        Err(error) => return failed(tag, error),
    };
    if let Err(error) = validate_xml(&xml) {
        return failed(tag, format!("Failed source load: {error}"));
    }
    let destination = destination_name(words.get(3).copied().unwrap_or(words[2]), ".db");
    if file::read_bytes(model, &destination).is_ok() {
        return failed(tag, format!("Dest filename already exists: {destination}"));
    }
    let database = match TempArtifact::new("xml-to-sql", "db", &[]) {
        Ok(file) => file,
        Err(error) => return failed(tag, error),
    };
    // sqlite's X'..' literal keeps the document byte-for-byte reversible and
    // avoids SQL quoting or command injection entirely.
    let sql = format!(
        "PRAGMA application_id={APPLICATION_ID}; PRAGMA user_version={PORTABLE_SCHEMA_VERSION}; \
         CREATE TABLE cmqttd_project(schema_version INTEGER NOT NULL, cgate_generation INTEGER NOT NULL, project_xml BLOB NOT NULL); \
         INSERT INTO cmqttd_project VALUES({PORTABLE_SCHEMA_VERSION},3,X'{}');",
        hex::encode(&xml)
    );
    if let Err(error) = sqlite(database.path(), &sql) {
        return failed(tag, error);
    }
    let bytes = match bounded_read(database.path()) {
        Ok(bytes) => bytes,
        Err(error) => return failed(tag, error),
    };
    if let Err(error) = file::write_bytes(model, &destination, bytes) {
        return failed(tag, error);
    }
    ok(tag, vec![], "200 OK.")
}

fn sql_to_xml(model: &mut Server, tag: &str, words: &[&str], cgate2: bool) -> Response {
    if !(3..=4).contains(&words.len()) {
        return syntax(tag);
    }
    let (_, source) = match read_with_extension(model, words[2], ".db") {
        Ok(value) => value,
        Err(error) => return failed(tag, error),
    };
    let database = match TempArtifact::new("sql-to-xml", "db", &source) {
        Ok(file) => file,
        Err(error) => return failed(tag, error),
    };
    if let Err(error) = verify_portable_database(database.path()) {
        return failed(tag, error);
    }
    let raw = match sqlite_output(
        database.path(),
        "SELECT hex(project_xml) FROM cmqttd_project LIMIT 1;",
    ) {
        Ok(output) => output,
        Err(error) => return failed(tag, error),
    };
    let mut xml = match hex::decode(raw.trim()) {
        Ok(bytes) if !bytes.is_empty() => bytes,
        _ => return failed(tag, "portable database contains no project XML"),
    };
    if let Err(error) = validate_xml(&xml) {
        return failed(tag, format!("Failed dest save: {error}"));
    }
    if cgate2 {
        xml = mark_cgate2(xml);
    }
    let destination = destination_name(words.get(3).copied().unwrap_or(words[2]), ".xml");
    if file::read_bytes(model, &destination).is_ok() {
        return failed(tag, format!("Dest filename already exists: {destination}"));
    }
    if let Err(error) = file::write_bytes(model, &destination, xml) {
        return failed(tag, error);
    }
    ok(tag, vec![], "200 OK.")
}

fn transform_project(model: &mut Server, tag: &str, words: &[&str]) -> Response {
    let mut index = 2;
    let test_only = words
        .get(index)
        .is_some_and(|word| word.eq_ignore_ascii_case("--test"));
    if test_only {
        index += 1;
    }
    if words.len() < index + 2 || words.len() > index + 3 {
        return syntax(tag);
    }
    let project = words[index];
    let stylesheet = words[index + 1];
    let output = words.get(index + 2).copied().unwrap_or(project);
    let (_, source) = match read_with_extension(model, project, ".xml") {
        Ok(value) => value,
        Err(error) => return failed(tag, error),
    };
    let stylesheet = match file::read_bytes(model, stylesheet) {
        Ok(bytes) => bytes,
        Err(error) => return failed(tag, error),
    };
    if let Err(error) = safe_stylesheet(&stylesheet) {
        return failed(tag, error);
    }
    if let Err(error) = validate_xml(&source) {
        return failed(tag, error);
    }
    let source_file = match TempArtifact::new("project-source", "xml", &source) {
        Ok(file) => file,
        Err(error) => return failed(tag, error),
    };
    let stylesheet_file = match TempArtifact::new("project-style", "xslt", &stylesheet) {
        Ok(file) => file,
        Err(error) => return failed(tag, error),
    };
    let result_file = match TempArtifact::new("project-result", "xml", &[]) {
        Ok(file) => file,
        Err(error) => return failed(tag, error),
    };
    let result = Command::new("xsltproc")
        .args(["--nonet", "--maxdepth", "256", "--maxvars", "100000"])
        .arg("--output")
        .arg(result_file.path())
        .arg(stylesheet_file.path())
        .arg(source_file.path())
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::piped())
        .output();
    match result {
        Ok(output) if output.status.success() => {}
        Ok(output) => return failed(tag, String::from_utf8_lossy(&output.stderr).trim()),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            return failed(tag, "xsltproc is not installed")
        }
        Err(error) => return failed(tag, error.to_string()),
    }
    let transformed = match bounded_read(result_file.path()) {
        Ok(bytes) if !bytes.is_empty() => bytes,
        Ok(_) => return failed(tag, "transform produced an empty file."),
        Err(error) => return failed(tag, error),
    };
    if let Err(error) = validate_xml(&transformed) {
        return failed(tag, error);
    }
    if !test_only {
        let destination = destination_name(output, ".xml");
        if let Err(error) = file::write_bytes(model, &destination, transformed) {
            return failed(tag, error);
        }
    }
    ok(tag, vec![], "200 OK.")
}

fn read_with_extension(
    model: &Server,
    requested: &str,
    extension: &str,
) -> Result<(String, Vec<u8>), String> {
    if let Ok(bytes) = file::read_bytes(model, requested) {
        return Ok((requested.to_string(), bytes));
    }
    let candidate = destination_name(requested, extension);
    match file::read_bytes(model, &candidate) {
        Ok(bytes) => Ok((candidate, bytes)),
        Err(_) => Err(format!("Src filename does not exist: {candidate}")),
    }
}

fn destination_name(requested: &str, extension: &str) -> String {
    let lower = requested.to_ascii_lowercase();
    for old in [".db", ".xml"] {
        if lower.ends_with(old) {
            return format!("{}{}", &requested[..requested.len() - old.len()], extension);
        }
    }
    format!("{requested}{extension}")
}

fn validate_xml(bytes: &[u8]) -> Result<(), String> {
    if bytes.len() > MAX_TRANSFORM_BYTES {
        return Err("project XML exceeds 16 MiB".to_string());
    }
    if bytes.contains(&0) {
        return Err("project XML contains NUL".to_string());
    }
    let text = std::str::from_utf8(bytes).map_err(|_| "project XML is not UTF-8".to_string())?;
    if text.to_ascii_uppercase().contains("<!DOCTYPE") {
        return Err("project XML contains a forbidden document type".to_string());
    }
    roxmltree::Document::parse(text)
        .map(|_| ())
        .map_err(|error| format!("project XML is not well formed: {error}"))
}

fn safe_stylesheet(bytes: &[u8]) -> Result<(), String> {
    validate_xml(bytes)?;
    let lower = String::from_utf8_lossy(bytes).to_ascii_lowercase();
    for forbidden in [
        "<!doctype",
        "document(",
        "xsl:include",
        "xsl:import",
        "extension-element-prefixes",
    ] {
        if lower.contains(forbidden) {
            return Err(format!("invalid xslt file: forbidden {forbidden}"));
        }
    }
    Ok(())
}

fn mark_cgate2(mut xml: Vec<u8>) -> Vec<u8> {
    // Preserve all understood project data. The portable database contains
    // only caller supplied XML and therefore has no hidden C-Gate 3 records
    // to discard. Record the requested generation in a processing
    // instruction so a subsequent conversion remains explicit.
    const MARKER: &[u8] = b"<?cmqttd-cgate-generation 2?>";
    if xml.windows(MARKER.len()).any(|window| window == MARKER) {
        return xml;
    }
    let insertion = if xml.starts_with(b"<?xml") {
        xml.windows(2)
            .position(|window| window == b"?>")
            .map_or(0, |offset| offset + 2)
    } else {
        0
    };
    let mut marked = Vec::with_capacity(MARKER.len() + xml.len() + 2);
    marked.extend_from_slice(&xml[..insertion]);
    if insertion != 0 {
        marked.push(b'\n');
    }
    marked.extend_from_slice(MARKER);
    marked.push(b'\n');
    marked.append(&mut xml.split_off(insertion));
    marked
}

fn verify_portable_database(path: &Path) -> Result<(), String> {
    let integrity = sqlite_output(path, "PRAGMA quick_check;")?;
    if integrity.trim() != "ok" {
        return Err(format!(
            "SQLite integrity check failed: {}",
            integrity.trim()
        ));
    }
    let schema = sqlite_output(
        path,
        "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='cmqttd_project';",
    )?;
    if schema.trim() != "1" {
        return Err("unsupported SQLite project schema".to_string());
    }
    let rows = sqlite_output(path, "SELECT count(*) FROM cmqttd_project;")?;
    if rows.trim() != "1" {
        return Err("portable database must contain exactly one project".to_string());
    }
    Ok(())
}

fn sqlite(path: &Path, sql: &str) -> Result<(), String> {
    sqlite_command(path, sql).map(|_| ())
}

fn sqlite_output(path: &Path, sql: &str) -> Result<String, String> {
    let output = sqlite_command(path, sql)?;
    String::from_utf8(output).map_err(|_| "sqlite3 returned non-UTF-8 output".to_string())
}

fn sqlite_command(path: &Path, sql: &str) -> Result<Vec<u8>, String> {
    let output = Command::new("sqlite3")
        .args(["-batch", "-noheader", "-bail"])
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
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(format!("SQLite conversion failed: {}", stderr.trim()));
    }
    if output.stdout.len() > MAX_TRANSFORM_BYTES * 2 + 1024 {
        return Err("SQLite conversion output exceeds limit".to_string());
    }
    Ok(output.stdout)
}

fn bounded_read(path: &Path) -> Result<Vec<u8>, String> {
    let metadata = fs::metadata(path).map_err(|error| error.to_string())?;
    if metadata.len() > MAX_TRANSFORM_BYTES as u64 {
        return Err("transform output exceeds 16 MiB".to_string());
    }
    fs::read(path).map_err(|error| error.to_string())
}

struct TempArtifact {
    path: PathBuf,
}

impl TempArtifact {
    fn new(purpose: &str, extension: &str, bytes: &[u8]) -> Result<Self, String> {
        if bytes.len() > MAX_TRANSFORM_BYTES {
            return Err("transform input exceeds 16 MiB".to_string());
        }
        let directory = std::env::temp_dir().join("cmqttd-transform");
        fs::create_dir_all(&directory).map_err(|error| error.to_string())?;
        let path = directory.join(format!(
            "{}-{}-{}.{}",
            purpose,
            std::process::id(),
            TEMP_SEQUENCE.fetch_add(1, Ordering::Relaxed),
            extension
        ));
        let mut options = fs::OpenOptions::new();
        options.write(true).create_new(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        std::io::Write::write_all(
            &mut options.open(&path).map_err(|error| error.to_string())?,
            bytes,
        )
        .map_err(|error| error.to_string())?;
        Ok(Self { path })
    }

    fn path(&self) -> &Path {
        &self.path
    }
}

impl Drop for TempArtifact {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.path);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::AccessLevel;

    fn upload(model: &mut Server, name: &str, bytes: &[u8]) {
        file::write_bytes(model, name, bytes.to_vec()).unwrap();
    }

    #[test]
    fn portable_sql_round_trip_migrate_and_cgate2_are_real_files() {
        if Command::new("sqlite3").arg("--version").output().is_err() {
            return;
        }
        let mut model = Server::new(AccessLevel::Program);
        let xml = b"<?xml version=\"1.0\"?><Installation><DBVersion>2.2</DBVersion><Project><TagName>Round trip</TagName></Project></Installation>";
        upload(&mut model, "source.xml", xml);
        assert_eq!(
            command(&mut model, "1", &["TRANSFORM", "XML_TO_SQL", "source"]).status,
            200
        );
        let db = file::read_bytes(&model, "source.db").unwrap();
        assert!(db.starts_with(b"SQLite format 3\0"));
        assert_eq!(
            command(&mut model, "2", &["TRANSFORM", "MIGRATE_SQL", "source"]).status,
            200
        );
        assert_eq!(
            command(
                &mut model,
                "3",
                &["TRANSFORM", "SQL_TO_XML", "source", "copy"]
            )
            .status,
            200
        );
        assert_eq!(file::read_bytes(&model, "copy.xml").unwrap(), xml);
        assert_eq!(
            command(
                &mut model,
                "4",
                &["TRANSFORM", "SQL_TO_XML_CGATE2", "source", "legacy"]
            )
            .status,
            200
        );
        let legacy = file::read_bytes(&model, "legacy.xml").unwrap();
        assert!(legacy
            .windows(b"<?cmqttd-cgate-generation 2?>".len())
            .any(|window| window == b"<?cmqttd-cgate-generation 2?>"));
        validate_xml(&legacy).unwrap();
    }

    #[test]
    fn project_xslt_is_sandboxed_and_test_mode_does_not_write() {
        if Command::new("xsltproc").arg("--version").output().is_err() {
            return;
        }
        let mut model = Server::new(AccessLevel::Program);
        upload(
            &mut model,
            "source.xml",
            b"<Project><TagName>A</TagName></Project>",
        );
        upload(
            &mut model,
            "rename.xslt",
            br#"<?xml version="1.0"?><xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform"><xsl:output method="xml"/><xsl:template match="@*|node()"><xsl:copy><xsl:apply-templates select="@*|node()"/></xsl:copy></xsl:template><xsl:template match="TagName"><TagName>B</TagName></xsl:template></xsl:stylesheet>"#,
        );
        assert_eq!(
            command(
                &mut model,
                "1",
                &[
                    "TRANSFORM",
                    "PROJECT",
                    "--test",
                    "source",
                    "rename.xslt",
                    "out"
                ]
            )
            .status,
            200
        );
        assert!(file::read_bytes(&model, "out.xml").is_err());
        assert_eq!(
            command(
                &mut model,
                "2",
                &["TRANSFORM", "PROJECT", "source", "rename.xslt", "out"]
            )
            .status,
            200
        );
        assert!(
            String::from_utf8(file::read_bytes(&model, "out.xml").unwrap())
                .unwrap()
                .contains("<TagName>B</TagName>")
        );

        upload(
            &mut model,
            "unsafe.xslt",
            br#"<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform"><xsl:template match="/"><xsl:value-of select="document('/etc/passwd')"/></xsl:template></xsl:stylesheet>"#,
        );
        assert_eq!(
            command(
                &mut model,
                "3",
                &["TRANSFORM", "PROJECT", "source", "unsafe.xslt", "bad"]
            )
            .status,
            408
        );
        assert!(file::read_bytes(&model, "bad.xml").is_err());
    }
}
