//! Minimal unit-specification reader for catalogue-backed sessions.
//!
//! Supports the unit-specification semantics that programming sessions need:
//! `<Param>` elements (name plus ordered fields, `Tag`
//! children skipped) with `<Includes>` following, resolved-directory
//! containment, repeated-parameter last-wins overrides, structural
//! numeric validation, and the 128-file / 8MiB caps. A file this reader
//! rejects yields no spec, and callers fall back to spec-free behavior.

use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};

/// Authenticated copyright preamble some decrypted signed specs carry
/// ahead of the XML. Only this exact line is
/// accepted, not arbitrary leading junk).
const COPYRIGHT: &[u8] = b"(C) CLIPSAL INTEGRATED SYSTEMS 2003 all rights reserved";
/// Specification size cap, checked on the
/// file metadata before any bytes are read).
const MAX_SPEC_BYTES: u64 = 8 * 1024 * 1024;
/// Include fan-out cap: at most this many files per load.
const MAX_SPEC_FILES: usize = 128;

/// One specification parameter: name plus ordered raw fields.
///
/// Repeated fields use last-value-wins semantics while retaining the first
/// position.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SpecParam {
    /// Parameter name (`Name` child).
    pub name: String,
    /// Ordered `(tag, text)` field pairs, `Tag` children excluded.
    pub fields: Vec<(String, String)>,
}

impl SpecParam {
    /// Raw field value by tag, if present.
    pub fn get(&self, tag: &str) -> Option<&str> {
        self.fields
            .iter()
            .find(|(k, _)| k == tag)
            .map(|(_, v)| v.as_str())
    }

    fn set_field(&mut self, tag: String, value: String) {
        if let Some(slot) = self.fields.iter_mut().find(|(k, _)| *k == tag) {
            slot.1 = value;
        } else {
            self.fields.push((tag, value));
        }
    }
}

/// Parse an integer in the specification grammar: optional sign, then
/// `$`-hex, `0x`-hex or decimal.
fn parse_integer(raw: &str) -> Option<i64> {
    let text = raw.trim();
    // The grammar is ASCII. Reject before slicing at byte offsets so
    // malformed Unicode metadata is an error, never a process panic.
    if !text.is_ascii() {
        return None;
    }
    let (sign, digits) = match text.strip_prefix(['+', '-']) {
        Some(rest) => (if text.starts_with('-') { -1 } else { 1 }, rest),
        None => (1, text),
    };
    let value = if let Some(hex) = digits.strip_prefix('$') {
        if hex.is_empty() || !hex.bytes().all(|b| b.is_ascii_hexdigit()) {
            return None;
        }
        i64::from_str_radix(hex, 16).ok()?
    } else if digits.len() > 2 && digits[..2].eq_ignore_ascii_case("0x") {
        if !digits[2..].bytes().all(|b| b.is_ascii_hexdigit()) {
            return None;
        }
        i64::from_str_radix(&digits[2..], 16).ok()?
    } else if !digits.is_empty() && digits.bytes().all(|b| b.is_ascii_digit()) {
        digits.parse::<i64>().ok()?
    } else {
        return None;
    };
    Some(sign * value)
}

/// Load `<UNIT_TYPE>.xml` from a specification directory.
pub fn load_spec(dir: &Path, unit_type: &str) -> Result<Vec<SpecParam>, String> {
    if unit_type.is_empty()
        || unit_type.contains(['/', '\\'])
        || Path::new(unit_type).is_absolute()
        || Path::new(unit_type)
            .components()
            .any(|c| matches!(c, std::path::Component::ParentDir))
    {
        return Err("Specification filename must be a bare unit type".to_string());
    }
    let canonical_dir = dir
        .canonicalize()
        .map_err(|e| format!("Specification directory is not accessible: {e}"))?;
    let mut loader = Loader {
        dir: &canonical_dir,
        visited: HashSet::new(),
        params: Vec::new(),
        index: HashMap::new(),
    };
    loader.visit(&format!("{unit_type}.xml"))?;
    Ok(loader.params)
}

struct Loader<'a> {
    dir: &'a Path,
    visited: HashSet<PathBuf>,
    params: Vec<SpecParam>,
    index: HashMap<String, usize>,
}

impl Loader<'_> {
    /// Resolve `name` inside the specification directory, following the
    /// Relative names only, no `..` segments, and symlinks
    /// resolved with containment re-checked.
    fn resolve(&self, name: &str) -> Result<PathBuf, String> {
        if name.is_empty() || name.contains('\\') || Path::new(name).is_absolute() {
            return Err(
                "Specification filename must be relative to the specification directory"
                    .to_string(),
            );
        }
        if Path::new(name)
            .components()
            .any(|c| matches!(c, std::path::Component::ParentDir))
        {
            return Err("Specification include escapes its directory".to_string());
        }
        let path = self
            .dir
            .join(name)
            .canonicalize()
            .map_err(|_| format!("Specification file {name:?} does not exist"))?;
        if !path.starts_with(self.dir) {
            return Err("Specification include escapes its directory".to_string());
        }
        if !path.is_file() {
            return Err(format!("Specification file {name:?} does not exist"));
        }
        Ok(path)
    }

    fn visit(&mut self, name: &str) -> Result<(), String> {
        let path = self.resolve(name)?;
        if self.visited.contains(&path) {
            return Err(format!(
                "Specification {name:?} was included more than once (cycle or repeated include)"
            ));
        }
        if self.visited.len() >= MAX_SPEC_FILES {
            return Err("Specification include limit exceeded".to_string());
        }
        self.visited.insert(path.clone());
        if path.metadata().map(|m| m.len()).unwrap_or(u64::MAX) > MAX_SPEC_BYTES {
            return Err("Specification exceeds the size limit".to_string());
        }
        let data = std::fs::read(&path).map_err(|e| format!("Cannot read {name:?}: {e}"))?;
        let mut text = data.as_slice();
        if let Some(rest) = text.strip_prefix(COPYRIGHT) {
            text = rest
                .strip_prefix(b"\r\n")
                .or_else(|| rest.strip_prefix(b"\n"))
                .unwrap_or(rest);
        }
        // Vendor specifications are ASCII/UTF-8 in practice. Declared
        // non-UTF-8 encodings are not supported.
        let text = std::str::from_utf8(text)
            .map_err(|_| format!("Malformed specification {name:?}: not UTF-8"))?;
        let doc = roxmltree::Document::parse(text)
            .map_err(|e| format!("Malformed specification {name:?}: {e}"))?;
        let root = doc.root_element();
        if root.tag_name().name() != "UnitSpecification" && root.tag_name().name() != "UnitSpec" {
            return Err(format!("{name:?} is not a unit specification"));
        }
        for includes in root
            .children()
            .filter(|n| n.is_element() && n.tag_name().name() == "Includes")
        {
            for include in includes
                .children()
                .filter(|n| n.is_element() && n.tag_name().name() == "Include")
            {
                let nested: String = include.text().unwrap_or("").trim().to_string();
                self.visit(&nested)?;
            }
        }
        for container in root
            .children()
            .filter(|n| n.is_element() && n.tag_name().name() == "Parameters")
        {
            for element in container
                .children()
                .filter(|n| n.is_element() && n.tag_name().name() == "Param")
            {
                self.push_param(name, element)?;
            }
        }
        Ok(())
    }

    fn push_param(&mut self, source: &str, element: roxmltree::Node<'_, '_>) -> Result<(), String> {
        let mut param = SpecParam {
            name: String::new(),
            fields: Vec::new(),
        };
        let mut seen_name = false;
        let mut seen_kind = false;
        for child in element.children().filter(|n| n.is_element()) {
            let tag = child.tag_name().name().to_string();
            if tag == "Tag" {
                continue;
            }
            let value: String = child.text().unwrap_or("").to_string();
            match tag.as_str() {
                "Name" => {
                    if seen_name {
                        return Err(format!(
                            "Repeated scalar specification field 'Name' in {source:?}"
                        ));
                    }
                    seen_name = true;
                    param.name = value.trim().to_string();
                    // The field map carries raw text; only the parameter key is stripped.
                    param.set_field(tag, value);
                }
                "Type" => {
                    if seen_kind {
                        return Err(format!(
                            "Repeated scalar specification field 'Type' in {source:?}"
                        ));
                    }
                    seen_kind = true;
                    param.set_field(tag, value);
                }
                _ => param.set_field(tag, value),
            }
        }
        let kind = param
            .get("Type")
            .map(|raw| raw.trim().to_lowercase())
            .unwrap_or_default();
        let address_raw = param.get("Address").unwrap_or("").to_string();
        if param.name.is_empty() || kind.is_empty() || address_raw.is_empty() {
            return Err(format!(
                "Parameter in {source:?} requires Name, Type and Address"
            ));
        }
        // Structural numeric metadata is parsed now. Unexpected default and
        // range contents stay visible for
        // explicit validation by callers.
        let address = parse_integer(&address_raw)
            .ok_or_else(|| format!("Invalid numeric parameter metadata for {:?}", param.name))?;
        let array_size = parse_integer(
            param
                .get("ArraySize")
                .filter(|v| !v.is_empty())
                .unwrap_or("1"),
        )
        .ok_or_else(|| format!("Invalid numeric parameter metadata for {:?}", param.name))?;
        let bit_size = parse_integer(
            param
                .get("BitSize")
                .filter(|v| !v.is_empty())
                .unwrap_or("8"),
        )
        .ok_or_else(|| format!("Invalid numeric parameter metadata for {:?}", param.name))?;
        if address < 0 || array_size < 1 || !(1..=64).contains(&bit_size) {
            return Err(format!(
                "Invalid numeric parameter metadata for {:?}",
                param.name
            ));
        }
        for key in ["ArraySkip", "BitAddress"] {
            let raw = param.get(key).filter(|v| !v.is_empty()).unwrap_or("0");
            let value = parse_integer(raw).ok_or_else(|| {
                format!("Invalid numeric parameter metadata for {:?}", param.name)
            })?;
            if value < 0 {
                return Err(format!("Negative {key} for {:?}", param.name));
            }
        }
        // Later includes override earlier ones; dict order (first-seen
        // position) is kept.
        if let Some(&pos) = self.index.get(param.name.as_str()) {
            self.params[pos] = param;
        } else {
            self.index.insert(param.name.clone(), self.params.len());
            self.params.push(param);
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn scratch(name: &str) -> PathBuf {
        let path = std::env::temp_dir().join(format!(
            "cgate-unitspec-test-{}-{}",
            std::process::id(),
            name
        ));
        let _ = std::fs::remove_dir_all(&path);
        std::fs::create_dir_all(&path).expect("scratch dir");
        path
    }

    fn write(dir: &Path, name: &str, body: &str) {
        std::fs::write(
            dir.join(name),
            format!("<UnitSpecification>{body}</UnitSpecification>"),
        )
        .expect("write spec");
    }

    #[test]
    fn loads_parameters() {
        let dir = scratch("loads");
        write(
            &dir,
            "KEYGL5.xml",
            "<Parameters><Param><Name>Application</Name><Type>int</Type><Address>$21</Address>\
             <DefaultValue>$FF $FF</DefaultValue></Param></Parameters>",
        );
        let params = load_spec(&dir, "KEYGL5").expect("spec loads");
        assert_eq!(params.len(), 1);
        let app = params
            .iter()
            .find(|p| p.name == "Application")
            .expect("Application");
        assert_eq!(app.get("Address"), Some("$21"));
        assert_eq!(app.get("DefaultValue"), Some("$FF $FF"));
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn rejects_escape_and_cycles() {
        let dir = scratch("paths");
        assert!(load_spec(&dir, "../x").is_err());
        assert!(load_spec(&dir, "").is_err());
        assert!(load_spec(&dir, "NOPE-MISSING-TYPE").is_err());
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn later_includes_override_earlier() {
        let dir = scratch("override");
        write(
            &dir,
            "a.xml",
            "<Parameters><Param><Name>P</Name><Type>int</Type><Address>$01</Address>\
             <DefaultValue>$11</DefaultValue></Param>\
             <Param><Name>Only</Name><Type>int</Type><Address>$02</Address></Param></Parameters>",
        );
        write(
            &dir,
            "b.xml",
            "<Parameters><Param><Name>P</Name><Type>int</Type><Address>$01</Address>\
             <DefaultValue>$22</DefaultValue></Param></Parameters>",
        );
        write(
            &dir,
            "main.xml",
            "<Includes><Include>a.xml</Include><Include>b.xml</Include></Includes>\
             <Parameters><Param><Name>Own</Name><Type>int</Type><Address>$03</Address></Param></Parameters>",
        );
        let params = load_spec(&dir, "main").expect("override chain loads");
        // First-seen positions are kept (P, Only, Own); the last value wins.
        let names: Vec<&str> = params.iter().map(|p| p.name.as_str()).collect();
        assert_eq!(names, vec!["P", "Only", "Own"]);
        assert_eq!(
            params
                .iter()
                .find(|p| p.name == "P")
                .unwrap()
                .get("DefaultValue"),
            Some("$22")
        );
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn rejects_repeated_include_and_bad_metadata() {
        let dir = scratch("reject");
        write(
            &dir,
            "loop.xml",
            "<Includes><Include>loop.xml</Include></Includes><Parameters></Parameters>",
        );
        assert!(load_spec(&dir, "loop").is_err());
        write(
            &dir,
            "badaddr.xml",
            "<Parameters><Param><Name>P</Name><Type>int</Type><Address>nope</Address></Param></Parameters>",
        );
        assert!(load_spec(&dir, "badaddr").is_err());
        write(
            &dir,
            "badsize.xml",
            "<Parameters><Param><Name>P</Name><Type>int</Type><Address>$01</Address>\
             <ArraySize>0</ArraySize></Param></Parameters>",
        );
        assert!(load_spec(&dir, "badsize").is_err());
        write(
            &dir,
            "badbits.xml",
            "<Parameters><Param><Name>P</Name><Type>int</Type><Address>$01</Address>\
             <BitSize>99</BitSize></Param></Parameters>",
        );
        assert!(load_spec(&dir, "badbits").is_err());
        write(
            &dir,
            "negskip.xml",
            "<Parameters><Param><Name>P</Name><Type>int</Type><Address>$01</Address>\
             <ArraySkip>-1</ArraySkip></Param></Parameters>",
        );
        assert!(load_spec(&dir, "negskip").is_err());
        write(
            &dir,
            "twice.xml",
            "<Parameters><Param><Name>P</Name><Name>Q</Name><Type>int</Type>\
             <Address>$01</Address></Param></Parameters>",
        );
        assert!(load_spec(&dir, "twice").is_err());
        write(
            &dir,
            "incomplete.xml",
            "<Parameters><Param><Name>P</Name><Type>int</Type></Param></Parameters>",
        );
        assert!(load_spec(&dir, "incomplete").is_err());
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn rejects_non_ascii_and_repeated_sign_numeric_metadata() {
        let dir = scratch("numeric-grammar");
        for value in ["€", "😀", "aé", "$+1", "0x+1", "--1", "+-1"] {
            write(
                &dir,
                "bad.xml",
                &format!("<Parameters><Param><Name>P</Name><Type>int</Type><Address>{value}</Address></Param></Parameters>"),
            );
            assert!(load_spec(&dir, "bad").is_err(), "accepted {value:?}");
        }
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn rejects_dotdot_include_segments() {
        let dir = scratch("segments");
        write(
            &dir,
            "main.xml",
            "<Includes><Include>sub/../evil.xml</Include></Includes><Parameters></Parameters>",
        );
        assert!(load_spec(&dir, "main").is_err());
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn rejects_wide_fanout() {
        let dir = scratch("fanout");
        let mut includes = String::new();
        for i in 0..(MAX_SPEC_FILES + 2) {
            let name = format!("leaf{i}.xml");
            write(
                &dir,
                &name,
                &format!(
                    "<Parameters><Param><Name>L{i}</Name><Type>int</Type>\
                     <Address>${i:02X}</Address></Param></Parameters>"
                ),
            );
            includes.push_str(&format!("<Include>{name}</Include>"));
        }
        write(
            &dir,
            "main.xml",
            &format!("<Includes>{includes}</Includes><Parameters></Parameters>"),
        );
        assert!(load_spec(&dir, "main").is_err());
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    #[cfg(unix)]
    fn rejects_symlink_escape() {
        use std::os::unix::fs::symlink;
        let outside = scratch("outside");
        write(
            &outside,
            "secret.xml",
            "<Parameters><Param><Name>S</Name><Type>int</Type><Address>$01</Address></Param></Parameters>",
        );
        let dir = scratch("linkdir");
        symlink(outside.join("secret.xml"), dir.join("evil.xml")).expect("symlink");
        write(
            &dir,
            "main.xml",
            "<Includes><Include>evil.xml</Include></Includes><Parameters></Parameters>",
        );
        assert!(load_spec(&dir, "main").is_err());
        let _ = std::fs::remove_dir_all(&dir);
        let _ = std::fs::remove_dir_all(&outside);
    }
}
