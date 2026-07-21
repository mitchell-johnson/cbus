//! CBZ / Toolkit-XML label extraction: malformed archives, malformed XML,
//! the tag/attribute normalisation rules and field-precedence quirks.

use cbus_mqtt::cbz::{normalise, read_cbz_labels, CbzError};
use std::io::Write as _;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicUsize, Ordering};

static UNIQUE: AtomicUsize = AtomicUsize::new(0);

/// Write `content` to a fresh temp file and return its path.
fn temp_file(ext: &str, content: &[u8]) -> PathBuf {
    let n = UNIQUE.fetch_add(1, Ordering::Relaxed);
    let path = std::env::temp_dir().join(format!("cbz-edge-{}-{n}.{ext}", std::process::id()));
    std::fs::write(&path, content).unwrap();
    path
}

fn labels_of(xml: &str) -> Result<cbus_mqtt::discovery::AppLabels, CbzError> {
    let path = temp_file("xml", xml.as_bytes());
    let r = read_cbz_labels(&path, None);
    std::fs::remove_file(&path).ok();
    r
}

const MINIMAL: &str = r#"<Installation>
  <Project>
    <Network TagName="Net A">
      <Application Address="56" TagName="Lighting">
        <Group Address="1" TagName="Kitchen"/>
      </Application>
    </Network>
  </Project>
</Installation>"#;

#[test]
fn minimal_project_parses() {
    let labels = labels_of(MINIMAL).unwrap();
    assert_eq!(labels[&56].0, "Lighting");
    assert_eq!(labels[&56].1[&1], "Kitchen");
}

#[test]
fn nonexistent_file_is_io_error() {
    let e = read_cbz_labels(Path::new("/nonexistent/project.cbz"), None).unwrap_err();
    assert!(matches!(e, CbzError::Io(_)));
}

#[test]
fn garbage_is_xml_parse_error() {
    let e = labels_of("this is not xml at all {").unwrap_err();
    assert!(e.to_string().contains("XML parse error"), "{e}");
}

#[test]
fn empty_file_is_xml_parse_error() {
    let e = labels_of("").unwrap_err();
    assert!(e.to_string().contains("XML parse error"), "{e}");
}

#[test]
fn missing_project_element() {
    let e = labels_of("<Installation><Other/></Installation>").unwrap_err();
    assert!(e.to_string().contains("no Project"), "{e}");
}

#[test]
fn missing_networks() {
    let e = labels_of("<Installation><Project/></Installation>").unwrap_err();
    assert!(e.to_string().contains("No networks found"), "{e}");
}

#[test]
fn named_network_not_found() {
    let path = temp_file("xml", MINIMAL.as_bytes());
    let e = read_cbz_labels(&path, Some("Net B")).unwrap_err();
    std::fs::remove_file(&path).ok();
    assert!(e.to_string().contains("'Net B' not found"), "{e}");
}

#[test]
fn named_network_selected_among_several() {
    let xml = r#"<Installation><Project>
      <Network TagName="First">
        <Application Address="56" TagName="A"/>
      </Network>
      <Network TagName="Second">
        <Application Address="56" TagName="B"/>
      </Network>
    </Project></Installation>"#;
    let path = temp_file("xml", xml.as_bytes());
    let by_name = read_cbz_labels(&path, Some("Second")).unwrap();
    let by_default = read_cbz_labels(&path, None).unwrap();
    std::fs::remove_file(&path).ok();
    assert_eq!(by_name[&56].0, "B");
    // no name: the first network wins
    assert_eq!(by_default[&56].0, "A");
}

#[test]
fn application_missing_address_errors() {
    let e = labels_of(
        r#"<Installation><Project><Network>
           <Application TagName="Lighting"/>
           </Network></Project></Installation>"#,
    )
    .unwrap_err();
    assert!(e.to_string().contains("application missing address"), "{e}");
}

#[test]
fn group_missing_address_errors() {
    let e = labels_of(
        r#"<Installation><Project><Network>
           <Application Address="56"><Group TagName="X"/></Application>
           </Network></Project></Installation>"#,
    )
    .unwrap_err();
    assert!(e.to_string().contains("group missing address"), "{e}");
}

#[test]
fn non_numeric_address_errors() {
    let e = labels_of(
        r#"<Installation><Project><Network>
           <Application Address="fifty-six"/>
           </Network></Project></Installation>"#,
    )
    .unwrap_err();
    assert!(e.to_string().contains("invalid literal for int()"), "{e}");
}

#[test]
fn whitespace_around_address_tolerated() {
    // Python int() trims surrounding whitespace
    let labels = labels_of(
        r#"<Installation><Project><Network>
           <Application Address=" 56 " TagName="L"/>
           </Network></Project></Installation>"#,
    )
    .unwrap();
    assert!(labels.contains_key(&56));
}

#[test]
fn child_element_overrides_attribute() {
    // from_element: attributes first, then children override
    let labels = labels_of(
        r#"<Installation><Project><Network>
           <Application Address="56" TagName="AttrName">
             <TagName>ChildName</TagName>
           </Application>
           </Network></Project></Installation>"#,
    )
    .unwrap();
    assert_eq!(labels[&56].0, "ChildName");
}

#[test]
fn plural_tags_match_via_rstrip_s() {
    // normalise() strips ALL trailing 's': <Applications> == application
    let labels = labels_of(
        r#"<Installation><Projects><Networks>
           <Applications Address="56" TagName="L">
             <Groups Address="2" TagName="Deck"/>
           </Applications>
           </Networks></Projects></Installation>"#,
    )
    .unwrap();
    assert_eq!(labels[&56].1[&2], "Deck");
}

#[test]
fn app_without_groups_is_empty_map() {
    let labels = labels_of(
        r#"<Installation><Project><Network>
           <Application Address="48" TagName="L48"/>
           </Network></Project></Installation>"#,
    )
    .unwrap();
    assert!(labels[&48].1.is_empty());
}

#[test]
fn duplicate_group_addresses_last_wins() {
    let labels = labels_of(
        r#"<Installation><Project><Network>
           <Application Address="56">
             <Group Address="1" TagName="Old"/>
             <Group Address="1" TagName="New"/>
           </Application>
           </Network></Project></Installation>"#,
    )
    .unwrap();
    assert_eq!(labels[&56].1[&1], "New");
}

#[test]
fn missing_tag_names_default_to_empty() {
    let labels = labels_of(
        r#"<Installation><Project><Network>
           <Application Address="56">
             <Group Address="1"/>
           </Application>
           </Network></Project></Installation>"#,
    )
    .unwrap();
    assert_eq!(labels[&56].0, "");
    assert_eq!(labels[&56].1[&1], "");
}

// ------------------------------------------------------------ zip variants

fn write_zip(files: &[(&str, &[u8])], method: zip::CompressionMethod) -> PathBuf {
    let n = UNIQUE.fetch_add(1, Ordering::Relaxed);
    let path = std::env::temp_dir().join(format!("cbz-edge-{}-{n}.cbz", std::process::id()));
    let mut w = zip::ZipWriter::new(std::fs::File::create(&path).unwrap());
    let opts = zip::write::SimpleFileOptions::default().compression_method(method);
    for (name, data) in files {
        w.start_file(*name, opts).unwrap();
        w.write_all(data).unwrap();
    }
    w.finish().unwrap();
    path
}

#[test]
fn empty_zip_rejected() {
    let path = write_zip(&[], zip::CompressionMethod::Stored);
    let e = read_cbz_labels(&path, None).unwrap_err();
    std::fs::remove_file(&path).ok();
    assert!(e.to_string().contains("Expected 1 file"), "{e}");
}

#[test]
fn deflate_compressed_cbz_accepted() {
    let path = write_zip(
        &[("project.xml", MINIMAL.as_bytes())],
        zip::CompressionMethod::Deflated,
    );
    let labels = read_cbz_labels(&path, None).unwrap();
    std::fs::remove_file(&path).ok();
    assert_eq!(labels[&56].1[&1], "Kitchen");
}

#[test]
fn zip_with_garbage_xml_member_is_parse_error() {
    let path = write_zip(
        &[("project.xml", b"not xml")],
        zip::CompressionMethod::Stored,
    );
    let e = read_cbz_labels(&path, None).unwrap_err();
    std::fs::remove_file(&path).ok();
    assert!(e.to_string().contains("XML parse error"), "{e}");
}

// -------------------------------------------------------------- normalise

#[test]
fn normalise_lowercases_and_strips_underscores() {
    assert_eq!(normalise("Tag_Name"), "tagname");
    assert_eq!(normalise("TagName"), "tagname");
}

#[test]
fn normalise_strips_all_trailing_s() {
    assert_eq!(normalise("Applications"), "application");
    assert_eq!(normalise("Addresss"), "addre");
    assert_eq!(normalise("ss"), "");
}
