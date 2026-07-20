//! C-Bus Toolkit project (CBZ) label extraction. Port of
//! `cbus/toolkit/cbz.py` (the walk we need) + `cmqttd.read_cbz_labels`.
//! Accepts both a 1-file zip (.cbz) and bare XML.

use crate::discovery::AppLabels;
use std::collections::BTreeMap;
use std::io::Read;
use std::path::Path;

/// Error reading a Toolkit backup.
#[derive(Debug, thiserror::Error)]
pub enum CbzError {
    /// The file could not be read.
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
    /// The archive/XML was not a usable Toolkit backup.
    #[error("{0}")]
    Cbz(String),
}

/// Tag/attr/field-name normalisation from `cbz.py:42-45`: lowercase,
/// strip '_', trim trailing 's' characters (Python `rstrip('s')` strips
/// *all* trailing 's').
pub fn normalise(name: &str) -> String {
    let lowered: String = name.to_lowercase().chars().filter(|&c| c != '_').collect();
    lowered.trim_end_matches('s').to_string()
}

/// Field lookup like `_Element.from_element`: attributes first, then child
/// elements (children override attributes).
pub fn get_field(node: roxmltree::Node, field: &str) -> Option<String> {
    let want = normalise(field);
    let mut found: Option<String> = None;
    for attr in node.attributes() {
        if normalise(attr.name()) == want {
            found = Some(attr.value().to_string());
        }
    }
    for child in node.children().filter(|c| c.is_element()) {
        if normalise(child.tag_name().name()) == want {
            found = Some(child.text().unwrap_or("").to_string());
        }
    }
    found
}

/// Child elements of `node` whose (normalised) tag matches `field`.
pub fn children<'a, 'input: 'a>(
    node: roxmltree::Node<'a, 'input>,
    field: &str,
) -> Vec<roxmltree::Node<'a, 'input>> {
    let want = normalise(field);
    node.children()
        .filter(|c| c.is_element() && normalise(c.tag_name().name()) == want)
        .collect()
}

fn py_int(s: &str) -> Result<i64, CbzError> {
    s.trim()
        .parse::<i64>()
        .map_err(|_| CbzError::Cbz(format!("invalid literal for int(): {s:?}")))
}

/// Load the XML text of a .cbz (1-file zip) or bare-XML Toolkit backup.
pub fn load_xml(path: &Path) -> Result<String, CbzError> {
    let raw = std::fs::read(path)?;
    extract_xml(&raw)
}

/// Read a .cbz (1-file zip) or bare XML Toolkit backup and extract
/// `{app_addr: (app_name, {group: label})}` for the named network
/// (None = first network).
pub fn read_cbz_labels(path: &Path, network: Option<&str>) -> Result<AppLabels, CbzError> {
    let xml = load_xml(path)?;
    let doc = roxmltree::Document::parse(&xml)
        .map_err(|e| CbzError::Cbz(format!("XML parse error: {e}")))?;
    let installation = doc.root_element();

    let project = children(installation, "project")
        .into_iter()
        .next()
        .ok_or_else(|| CbzError::Cbz("no Project in CBZ".into()))?;
    let networks = children(project, "network");

    let chosen = match network {
        Some(name) => networks
            .iter()
            .find(|n| get_field(**n, "tag_name").as_deref() == Some(name))
            .copied()
            .ok_or_else(|| {
                CbzError::Cbz(format!("CBus network '{name}' not found in project file"))
            })?,
        None => *networks
            .first()
            .ok_or_else(|| CbzError::Cbz("No networks found in CBZ project file".into()))?,
    };

    let mut labels = AppLabels::new();
    for app in children(chosen, "application") {
        let addr = py_int(
            &get_field(app, "address")
                .ok_or_else(|| CbzError::Cbz("application missing address".into()))?,
        )?;
        let name = get_field(app, "tag_name").unwrap_or_default();
        let mut groups: BTreeMap<u8, String> = BTreeMap::new();
        for group in children(app, "group") {
            let gaddr = py_int(
                &get_field(group, "address")
                    .ok_or_else(|| CbzError::Cbz("group missing address".into()))?,
            )?;
            let gname = get_field(group, "tag_name").unwrap_or_default();
            groups.insert(gaddr as u8, gname);
        }
        labels.insert(addr, (name, groups));
    }
    Ok(labels)
}

/// A CBZ is a 1-file zip of XML; also accept bare XML.
fn extract_xml(raw: &[u8]) -> Result<String, CbzError> {
    let cursor = std::io::Cursor::new(raw);
    match zip::ZipArchive::new(cursor) {
        Ok(mut archive) => {
            if archive.len() != 1 {
                return Err(CbzError::Cbz(format!(
                    "Expected 1 file in CBZ archive, got {}",
                    archive.len()
                )));
            }
            let mut file = archive
                .by_index(0)
                .map_err(|e| CbzError::Cbz(e.to_string()))?;
            if !file.name().ends_with(".xml") {
                return Err(CbzError::Cbz(
                    "The file in this archive does not have a .xml extension. \
                     It is probably not a CBZ."
                        .into(),
                ));
            }
            let mut out = String::new();
            file.read_to_string(&mut out)
                .map_err(|e| CbzError::Cbz(e.to_string()))?;
            Ok(out)
        }
        Err(_) => Ok(String::from_utf8_lossy(raw).into_owned()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fixture() -> std::path::PathBuf {
        Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../rust-migration-harness/fixtures/project.xml")
    }

    #[test]
    fn reads_fixture_labels() {
        let labels = read_cbz_labels(&fixture(), None).unwrap();
        assert_eq!(labels[&56].0, "Lighting");
        assert_eq!(labels[&56].1[&1], "Kitchen Bench");
        assert_eq!(labels[&56].1[&10], "Lounge");
        assert_eq!(labels[&48].1[&11], "Deck");
    }

    #[test]
    fn network_selection() {
        assert!(read_cbz_labels(&fixture(), Some("Harness Network")).is_ok());
        assert!(read_cbz_labels(&fixture(), Some("Nope")).is_err());
    }

    fn write_zip(path: &Path, files: &[(&str, &[u8])]) {
        use std::io::Write;
        let mut w = zip::ZipWriter::new(std::fs::File::create(path).unwrap());
        let opts = zip::write::SimpleFileOptions::default()
            .compression_method(zip::CompressionMethod::Stored);
        for (name, data) in files {
            w.start_file(*name, opts).unwrap();
            w.write_all(data).unwrap();
        }
        w.finish().unwrap();
    }

    fn temp_path(name: &str) -> std::path::PathBuf {
        std::env::temp_dir().join(format!("cbz-test-{}-{name}", std::process::id()))
    }

    #[test]
    fn reads_zipped_cbz() {
        let xml = std::fs::read(fixture()).unwrap();
        let path = temp_path("ok.cbz");
        write_zip(&path, &[("project.xml", &xml)]);
        let labels = read_cbz_labels(&path, None).unwrap();
        std::fs::remove_file(&path).ok();
        assert_eq!(labels[&56].1[&1], "Kitchen Bench");
        assert_eq!(labels[&48].1[&11], "Deck");
    }

    #[test]
    fn zip_must_hold_one_xml() {
        let xml = std::fs::read(fixture()).unwrap();
        let two = temp_path("two.cbz");
        write_zip(&two, &[("a.xml", &xml), ("b.xml", &xml)]);
        let r = read_cbz_labels(&two, None);
        std::fs::remove_file(&two).ok();
        assert!(r.is_err(), "2-file archive must be rejected");

        let notxml = temp_path("notxml.cbz");
        write_zip(&notxml, &[("project.txt", &xml)]);
        let r = read_cbz_labels(&notxml, None);
        std::fs::remove_file(&notxml).ok();
        assert!(r.is_err(), "non-.xml member must be rejected");
    }
}
