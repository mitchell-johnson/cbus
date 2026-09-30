//! C-Bus project (CBZ) label extraction.
//! Accepts both a one-file zip (`.cbz`) and bare XML.

use crate::discovery::AppLabels;
use std::collections::BTreeMap;
use std::io::Read;
use std::path::Path;

/// Maximum on-disk project size and expanded XML size, matching the Python
/// Toolkit's `MAX_DOCUMENT_BYTES` policy (128 MiB).
pub const MAX_DOCUMENT_BYTES: usize = 128 * 1024 * 1024;

/// Error reading a C-Bus project backup.
#[derive(Debug, thiserror::Error)]
pub enum CbzError {
    /// The file could not be read.
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
    /// The archive/XML was not a usable C-Bus project backup.
    #[error("{0}")]
    Cbz(String),
}

/// Tag, attribute, and field-name normalization: lowercase, strip `_`, and
/// trim all trailing `s` characters.
pub fn normalise(name: &str) -> String {
    let lowered: String = name.to_lowercase().chars().filter(|&c| c != '_').collect();
    lowered.trim_end_matches('s').to_string()
}

/// Field lookup checks attributes first and then child elements; children
/// override attributes.
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
    // Reject special files before opening them, then validate the descriptor
    // too: the path can change between the metadata check and open.
    check_project_metadata(&std::fs::metadata(path)?)?;
    let file = open_regular_project(path)?;
    let raw = read_project_bytes(file, MAX_DOCUMENT_BYTES)?;
    extract_xml(&raw, MAX_DOCUMENT_BYTES)
}

fn check_project_metadata(metadata: &std::fs::Metadata) -> Result<(), CbzError> {
    if !metadata.is_file() {
        return Err(CbzError::Cbz("Project file must be a regular file".into()));
    }
    if metadata.len() > MAX_DOCUMENT_BYTES as u64 {
        return Err(CbzError::Cbz("Project file exceeds the size limit".into()));
    }
    Ok(())
}

fn open_regular_project(path: &Path) -> Result<std::fs::File, CbzError> {
    let mut options = std::fs::OpenOptions::new();
    options.read(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        // A FIFO substituted after the pre-open check must not block open.
        // Keep symlinks to regular files compatible with ordinary XML input.
        options.custom_flags(libc::O_NONBLOCK);
    }
    let file = options.open(path)?;
    check_project_metadata(&file.metadata()?)?;
    Ok(file)
}

fn read_project_bytes(reader: impl Read, limit: usize) -> Result<Vec<u8>, CbzError> {
    let mut raw = Vec::new();
    // File length may grow after descriptor inspection. Bound actual bytes,
    // independently of both path and descriptor metadata.
    reader.take(limit as u64 + 1).read_to_end(&mut raw)?;
    if raw.len() > limit {
        return Err(CbzError::Cbz("Project file exceeds the size limit".into()));
    }
    Ok(raw)
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
            let gaddr = u8::try_from(gaddr).map_err(|_| {
                CbzError::Cbz(format!("group address out of range (0..255), got {gaddr}"))
            })?;
            let gname = get_field(group, "tag_name").unwrap_or_default();
            groups.insert(gaddr, gname);
        }
        labels.insert(addr, (name, groups));
    }
    Ok(labels)
}

/// A CBZ is a 1-file zip of XML; also accept bare XML.
fn extract_xml(raw: &[u8], limit: usize) -> Result<String, CbzError> {
    let cursor = std::io::Cursor::new(raw);
    match zip::ZipArchive::new(cursor) {
        Ok(mut archive) => {
            if archive.len() != 1 {
                return Err(CbzError::Cbz(format!(
                    "Expected 1 file in CBZ archive, got {}",
                    archive.len()
                )));
            }
            let file = archive
                .by_index(0)
                .map_err(|e| CbzError::Cbz(e.to_string()))?;
            if !file.name().ends_with(".xml") {
                return Err(CbzError::Cbz(
                    "The file in this archive does not have a .xml extension. \
                     It is probably not a CBZ."
                        .into(),
                ));
            }
            let declared_size = file.size();
            if declared_size > limit as u64 {
                return Err(CbzError::Cbz("Expanded XML exceeds the size limit".into()));
            }
            let mut out = String::new();
            // ZIP sizes are untrusted. Limit the decompressed stream itself,
            // allowing one overflow byte and EOF/CRC checks at the exact cap.
            file.take(limit as u64 + 1)
                .read_to_string(&mut out)
                .map_err(|e| CbzError::Cbz(e.to_string()))?;
            if out.len() > limit {
                return Err(CbzError::Cbz("Expanded XML exceeds the size limit".into()));
            }
            if out.len() as u64 != declared_size {
                return Err(CbzError::Cbz(
                    "Archive XML size differs from its declared size".into(),
                ));
            }
            Ok(out)
        }
        Err(_) => {
            // Lossy UTF-8 can expand each invalid byte into a three-byte
            // replacement character. Count the actual decoded size before
            // allocating it, retaining the existing lossy-input behavior.
            let decoded_size = raw.utf8_chunks().try_fold(0_usize, |size, chunk| {
                size.checked_add(chunk.valid().len())
                    .and_then(|size| {
                        size.checked_add(if chunk.invalid().is_empty() { 0 } else { 3 })
                    })
                    .filter(|size| *size <= limit)
            });
            let Some(decoded_size) = decoded_size else {
                return Err(CbzError::Cbz("Expanded XML exceeds the size limit".into()));
            };
            let mut out = String::with_capacity(decoded_size);
            for chunk in raw.utf8_chunks() {
                out.push_str(chunk.valid());
                if !chunk.invalid().is_empty() {
                    out.push('\u{fffd}');
                }
            }
            Ok(out)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fixture() -> std::path::PathBuf {
        Path::new(env!("CARGO_MANIFEST_DIR")).join("../testdata/fixtures/project.xml")
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

    fn zipped_xml(xml: &[u8], method: zip::CompressionMethod) -> Vec<u8> {
        use std::io::Write;
        let mut writer = zip::ZipWriter::new(std::io::Cursor::new(Vec::new()));
        writer
            .start_file(
                "project.xml",
                zip::write::SimpleFileOptions::default().compression_method(method),
            )
            .unwrap();
        writer.write_all(xml).unwrap();
        writer.finish().unwrap().into_inner()
    }

    fn central_offset(zip: &[u8]) -> usize {
        let end = zip.windows(4).rposition(|w| w == b"PK\x05\x06").unwrap();
        u32::from_le_bytes(zip[end + 16..end + 20].try_into().unwrap()) as usize
    }

    fn declare_xml_size(zip: &mut [u8], size: u32) {
        let central = central_offset(zip);
        zip[22..26].copy_from_slice(&size.to_le_bytes());
        zip[central + 24..central + 28].copy_from_slice(&size.to_le_bytes());
    }

    #[test]
    fn opened_project_growth_is_bounded_by_actual_bytes() {
        use std::io::Write;
        let path = temp_path("growing.xml");
        std::fs::write(&path, b"<x>initial</x>").unwrap();
        let file = open_regular_project(&path).unwrap();
        std::fs::OpenOptions::new()
            .append(true)
            .open(&path)
            .unwrap()
            .write_all(&[b' '; 64])
            .unwrap();
        let result = read_project_bytes(file, 32);
        std::fs::remove_file(path).unwrap();
        assert!(result.unwrap_err().to_string().contains("size limit"));
        assert_eq!(read_project_bytes(&[b'x'; 32][..], 32).unwrap().len(), 32);
    }

    #[cfg(unix)]
    #[test]
    fn fifo_substituted_after_path_check_cannot_block_open() {
        use std::os::unix::ffi::OsStrExt;
        let path = temp_path("substituted.xml");
        std::fs::write(&path, b"<x/>").unwrap();
        check_project_metadata(&std::fs::metadata(&path).unwrap()).unwrap();
        std::fs::remove_file(&path).unwrap();
        let name = std::ffi::CString::new(path.as_os_str().as_bytes()).unwrap();
        // SAFETY: the path is a valid NUL-terminated string, used only here.
        assert_eq!(unsafe { libc::mkfifo(name.as_ptr(), 0o600) }, 0);
        let opened_path = path.clone();
        let (send, receive) = std::sync::mpsc::channel();
        std::thread::spawn(move || {
            let _ = send.send(open_regular_project(&opened_path));
        });
        let result = receive.recv_timeout(std::time::Duration::from_secs(5));
        std::fs::remove_file(path).unwrap();
        let error = result
            .expect("descriptor open must not wait for a FIFO writer")
            .unwrap_err();
        assert!(error.to_string().contains("regular file"), "{error}");
    }

    #[test]
    fn zipped_xml_accepts_the_exact_expanded_limit_and_checks_crc() {
        let xml = format!("<x>{}</x>", "a".repeat(1024 - 7));
        for method in [
            zip::CompressionMethod::Stored,
            zip::CompressionMethod::Deflated,
        ] {
            let mut zip = zipped_xml(xml.as_bytes(), method);
            assert_eq!(extract_xml(&zip, 1024).unwrap(), xml);
            let central = central_offset(&zip);
            zip[14] ^= 1;
            zip[central + 16] ^= 1;
            assert!(
                extract_xml(&zip, 1024).is_err(),
                "CRC must be checked at EOF"
            );
        }
    }

    #[test]
    fn bare_xml_lossy_utf8_expansion_respects_the_decoded_limit() {
        let raw = b"<x>\xff\xff\xff</x>";
        let decoded = "<x>\u{fffd}\u{fffd}\u{fffd}</x>";
        assert_eq!(extract_xml(raw, decoded.len()).unwrap(), decoded);
        assert!(extract_xml(raw, decoded.len() - 1)
            .unwrap_err()
            .to_string()
            .contains("size limit"));
        let unicode = "<x>Caf\u{e9}</x>";
        assert_eq!(
            extract_xml(unicode.as_bytes(), unicode.len()).unwrap(),
            unicode
        );
    }

    #[test]
    fn zipped_xml_rejects_declared_oversize_and_limit_plus_one() {
        let xml = format!("<x>{}</x>", "a".repeat(1025 - 7));
        let zip = zipped_xml(xml.as_bytes(), zip::CompressionMethod::Deflated);
        assert!(extract_xml(&zip, 1024)
            .unwrap_err()
            .to_string()
            .contains("size limit"));
        let mut zip = zipped_xml(b"<x/>", zip::CompressionMethod::Deflated);
        declare_xml_size(&mut zip, u32::MAX - 1);
        assert!(extract_xml(&zip, 1024)
            .unwrap_err()
            .to_string()
            .contains("size limit"));
    }

    #[test]
    fn forged_small_zip_size_cannot_bypass_actual_expansion_limit() {
        let xml = format!("<x>{}</x>", "a".repeat(4096));
        let mut zip = zipped_xml(xml.as_bytes(), zip::CompressionMethod::Deflated);
        declare_xml_size(&mut zip, 16);
        let error = extract_xml(&zip, 1024).unwrap_err();
        assert!(error.to_string().contains("size limit"), "{error}");
    }

    #[test]
    fn zip_declared_length_must_match_actual_xml_even_below_cap() {
        for method in [
            zip::CompressionMethod::Stored,
            zip::CompressionMethod::Deflated,
        ] {
            let mut zip = zipped_xml(b"<x>complete XML</x>", method);
            declare_xml_size(&mut zip, 4);
            let error = extract_xml(&zip, 1024).unwrap_err();
            assert!(error.to_string().contains("declared size"), "{error}");
        }
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
