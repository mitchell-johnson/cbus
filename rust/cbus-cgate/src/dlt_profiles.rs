//! DLT/eDLT profile admission shared with the Python Toolkit CLI.
//!
//! `dlt_profiles.json` is generated from `cbus_toolkit.dlt_profiles` by
//! `toolkit-cli/research/export_dlt_admission.py`; a Python test fails when
//! the committed copy drifts. [`refusal`] ports the Python `refusal`
//! decision exactly, including its reason text, and
//! `testdata/vectors/dlt_profile_admission.jsonl` pins both implementations
//! to the same decisions. cmqttd's physical eDLT commands (`LABEL CLEAREDLT`
//! and `DO ... FactoryDefault`) ask the `edlt-label-clear` workflow, which the
//! Python label-clear and factory-default guards also use. Native C-Gate
//! `CBusEdlt` class behavior (NET SYNC enrichment, vendor properties, the
//! mock's method table) depends only on [`is_edlt_class`].

use std::collections::BTreeMap;
use std::sync::OnceLock;

use serde::Deserialize;

/// Workflow used by cmqttd's guarded physical eDLT controls.
pub const EDLT_LABEL_CLEAR: &str = "edlt-label-clear";

const TABLE_FORMAT: &str = "cbus-dlt-profile-admission-v1";

#[derive(Debug, Deserialize)]
struct Table {
    format: String,
    i_dlt_min_version: String,
    profiles: Vec<Profile>,
    workflows: Vec<Workflow>,
    help_only_catalog_names: BTreeMap<String, String>,
    undefined_help_types: BTreeMap<String, String>,
    spec_only_types: BTreeMap<String, String>,
}

#[derive(Debug, Deserialize)]
struct Profile {
    unit_type: String,
    family: String,
    style: String,
    spec_filename: String,
    catalog_numbers: Vec<String>,
    revisions: Vec<Revision>,
}

#[derive(Debug, Deserialize)]
struct Revision {
    min: String,
    max: String,
    internal: bool,
}

#[derive(Debug, Deserialize)]
struct Workflow {
    name: String,
    identity: Vec<String>,
    firmware_form: String,
    admitted: Vec<(String, Option<String>, Option<String>)>,
}

/// The requested workflow is not in the shared table.
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
#[error("Unknown DLT workflow: {0}")]
pub struct UnknownWorkflow(String);

fn table() -> &'static Table {
    static TABLE: OnceLock<Table> = OnceLock::new();
    TABLE.get_or_init(|| {
        let table: Table = serde_json::from_str(include_str!("dlt_profiles.json"))
            .expect("embedded DLT admission table is valid JSON");
        assert_eq!(
            table.format, TABLE_FORMAT,
            "embedded DLT admission table format"
        );
        table
    })
}

/// Whether `unit_type` is catalogued with the C-Gate `CBusEdlt` class
/// (the `edlt` profile family), ignoring ASCII case like native type tokens.
pub fn is_edlt_class(unit_type: &str) -> bool {
    table().profiles.iter().any(|profile| {
        profile.family == "edlt" && profile.unit_type.eq_ignore_ascii_case(unit_type)
    })
}

/// Python `repr()` of one text value, as the shared reasons render it.
fn py_repr(value: &str) -> String {
    let quote = if value.contains('\'') && !value.contains('"') {
        '"'
    } else {
        '\''
    };
    let mut out = String::with_capacity(value.len() + 2);
    out.push(quote);
    for c in value.chars() {
        match c {
            '\\' => out.push_str("\\\\"),
            '\t' => out.push_str("\\t"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            c if c == quote => {
                out.push('\\');
                out.push(c);
            }
            c if (c as u32) < 0x20 || (0x7f..0xa0).contains(&(c as u32)) => {
                out.push_str(&format!("\\x{:02x}", c as u32));
            }
            c if c.is_control() => out.push_str(&format!("\\u{:04x}", c as u32)),
            c => out.push(c),
        }
    }
    out.push(quote);
    out
}

fn repr_option(value: Option<&str>) -> String {
    value.map_or_else(|| "None".to_string(), py_repr)
}

fn digits(text: &str, min: usize, max: usize) -> bool {
    (min..=max).contains(&text.len()) && text.bytes().all(|b| b.is_ascii_digit())
}

/// `M.m.pp` from a physical IDENTIFY firmware such as `05.05.00`.
fn physical_firmware(value: &str) -> Option<String> {
    let parts: Vec<&str> = value.split('.').collect();
    if parts.len() != 3 || !parts.iter().all(|part| digits(part, 1, 2)) {
        return None;
    }
    let number = |part: &str| part.parse::<u32>().expect("validated digits");
    Some(format!(
        "{}.{}.{:02}",
        number(parts[0]),
        number(parts[1]),
        number(parts[2])
    ))
}

/// Python `_VERSION`: two to four dot-separated components of 1..=4 digits.
fn database_version(value: &str) -> bool {
    let parts: Vec<&str> = value.split('.').collect();
    (2..=4).contains(&parts.len()) && parts.iter().all(|part| digits(part, 1, 4))
}

/// C-Gate numeric-component comparison (non-numeric characters ignored,
/// missing trailing components equal zero). Inputs are validated versions.
fn compare_versions(left: &str, right: &str) -> std::cmp::Ordering {
    fn components(version: &str) -> Vec<u64> {
        let cleaned: String = version
            .chars()
            .filter(|c| c.is_ascii_digit() || *c == '.')
            .collect();
        cleaned
            .trim_end_matches('.')
            .split('.')
            .map(|part| part.parse().unwrap_or(0))
            .collect()
    }
    let (mut first, mut second) = (components(left), components(right));
    let count = first.len().max(second.len());
    first.resize(count, 0);
    second.resize(count, 0);
    first.cmp(&second)
}

fn contains(revision: &Revision, firmware: &str) -> bool {
    compare_versions(firmware, &revision.min).is_ge()
        && compare_versions(firmware, &revision.max).is_le()
}

fn firmware_matches(rule: Option<&str>, firmware: &str) -> bool {
    match rule {
        None => true,
        Some(rule) => match rule.split_once("..") {
            Some((low, high)) => {
                physical_firmware(firmware).as_deref() == Some(firmware)
                    && compare_versions(firmware, low).is_ge()
                    && compare_versions(firmware, high).is_le()
            }
            None => firmware == rule,
        },
    }
}

fn unknown_type_reason(table: &Table, unit_type: &str) -> String {
    if let Some(reason) = table.undefined_help_types.get(unit_type) {
        return reason.clone();
    }
    if let Some(reason) = table.spec_only_types.get(unit_type) {
        return reason.clone();
    }
    format!(
        "{} is not a DLT or eDLT unit type in the retained catalogue",
        py_repr(unit_type)
    )
}

/// Why `(unit_type, firmware, catalog_number)` is outside `workflow`, or
/// `None` when admitted. Reasons are identical to the Python registry's.
pub fn refusal(
    workflow: &str,
    unit_type: &str,
    firmware: Option<&str>,
    catalog_number: Option<&str>,
) -> Result<Option<String>, UnknownWorkflow> {
    let table = table();
    let rule = table
        .workflows
        .iter()
        .find(|row| row.name == workflow)
        .ok_or_else(|| UnknownWorkflow(py_repr(workflow)))?;
    let Some(profile) = table.profiles.iter().find(|row| row.unit_type == unit_type) else {
        return Ok(Some(unknown_type_reason(table, unit_type)));
    };
    let for_type: Vec<_> = rule
        .admitted
        .iter()
        .filter(|row| row.0 == unit_type)
        .collect();
    if for_type.is_empty() {
        let reason = if profile.family == "classic-dlt" && workflow.starts_with("edlt-") {
            format!(
                "{unit_type} is a classic {} ({} / I_DLT.xml) without eDLT widgets or unit-resident static label text",
                profile.style, profile.spec_filename
            )
        } else if profile.family == "edlt" && workflow.starts_with("classic-") {
            "KEYGL5 is an eDLT; per-key label variants (LabelFlavour) are classic I_DLT.xml fields \
             that KEYGL5.xml does not declare"
                .to_string()
        } else {
            format!(
                "{unit_type} ({}) has no retained evidence for the {workflow} workflow",
                profile.style
            )
        };
        return Ok(Some(reason));
    }
    if !rule.identity.iter().any(|field| field == "firmware") {
        return Ok(None);
    }
    let canonical = match firmware {
        Some(value) if rule.firmware_form == "physical" => physical_firmware(value),
        Some(value) if database_version(value) => Some(value.to_string()),
        _ => None,
    };
    let Some(canonical) = canonical else {
        return Ok(Some(format!(
            "{unit_type} firmware {} is not a recognised version string",
            repr_option(firmware)
        )));
    };
    let containing: Vec<_> = profile
        .revisions
        .iter()
        .filter(|row| contains(row, &canonical))
        .collect();
    let [revision] = containing.as_slice() else {
        return Ok(Some(format!(
            "{unit_type} firmware {canonical} is outside every C-Gate catalogue revision"
        )));
    };
    let matching: Vec<_> = for_type
        .iter()
        .filter(|row| firmware_matches(row.1.as_deref(), &canonical))
        .collect();
    let internal = || {
        format!(
            "{unit_type} firmware {canonical} is in catalogue revision {}..{}, which C-Gate marks IsInternal",
            revision.min, revision.max
        )
    };
    if matching.is_empty() {
        let reason = if profile.family == "edlt" {
            if revision.internal {
                internal()
            } else if physical_firmware(&canonical).as_deref() != Some(canonical.as_str()) {
                format!(
                    "{unit_type} firmware {} is not the canonical catalogue spelling M.m.pp",
                    py_repr(&canonical)
                )
            } else {
                let evidence: Vec<&str> = for_type
                    .iter()
                    .map(|row| row.1.as_deref().unwrap_or("None"))
                    .collect();
                format!(
                    "KEYGL5 firmware {canonical} (catalogue revision {}..{}) shares KEYGL5.xml, but \
                     {workflow} evidence is retained only for {} and it is not extrapolated",
                    revision.min,
                    revision.max,
                    evidence.join(", ")
                )
            }
        } else if compare_versions(&canonical, &table.i_dlt_min_version).is_lt() {
            format!(
                "{unit_type} firmware {canonical} is below I_DLT.xml MinVersion {}, the specification \
                 that declares the label variant fields",
                table.i_dlt_min_version
            )
        } else if revision.internal {
            internal()
        } else {
            format!("{unit_type} firmware {canonical} has no retained evidence for {workflow}")
        };
        return Ok(Some(reason));
    }
    if !rule.identity.iter().any(|field| field == "catalog_number") {
        return Ok(None);
    }
    let wildcard = |row: &&&(String, Option<String>, Option<String>)| row.2.as_deref() == Some("*");
    if catalog_number.is_none() && matching.iter().all(wildcard) {
        return Ok(None);
    }
    if let Some(catalog) = catalog_number {
        if table.help_only_catalog_names.contains_key(catalog) {
            return Ok(Some(format!(
                "{} is a Toolkit help catalogue name that does not exist in the C-Gate catalogue \
                 (catalogue numbers for {unit_type}: {})",
                py_repr(catalog),
                profile.catalog_numbers.join(", ")
            )));
        }
    }
    if !catalog_number
        .is_some_and(|catalog| profile.catalog_numbers.iter().any(|row| row == catalog))
    {
        return Ok(Some(format!(
            "Catalogue number {} is not a C-Gate catalogue number for {unit_type}",
            repr_option(catalog_number)
        )));
    }
    let catalog = catalog_number.expect("checked above");
    if matching
        .iter()
        .any(|row| matches!(row.2.as_deref(), Some("*")) || row.2.as_deref() == Some(catalog))
    {
        return Ok(None);
    }
    Ok(Some(format!(
        "Catalogue number {catalog} shares {} with 5055EDL, but only 5055EDL evidence is retained",
        profile.spec_filename
    )))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn embedded_table_matches_the_python_registry_shape() {
        let table = table();
        assert_eq!(table.format, TABLE_FORMAT);
        assert!(is_edlt_class("KEYGL5") && is_edlt_class("keygl5"));
        assert!(!is_edlt_class("KEYBL5") && !is_edlt_class("KEYE1"));
        assert!(table
            .workflows
            .iter()
            .any(|row| row.name == EDLT_LABEL_CLEAR));
    }

    #[test]
    fn label_clear_admits_only_the_evidenced_revision() {
        let clear = |firmware| refusal(EDLT_LABEL_CLEAR, "KEYGL5", Some(firmware), None).unwrap();
        assert_eq!(clear("5.5.00"), None);
        assert!(clear("5.4.00")
            .unwrap()
            .contains("retained only for 5.5.00"));
        assert!(clear("5.6.00").unwrap().contains("IsInternal"));
        assert!(clear("").unwrap().contains("''"));
        assert_eq!(
            refusal("bogus", "KEYGL5", None, None),
            Err(UnknownWorkflow("'bogus'".into()))
        );
    }

    #[test]
    fn python_repr_quoting() {
        assert_eq!(py_repr("KEY"), "'KEY'");
        assert_eq!(py_repr("it's"), "\"it's\"");
        assert_eq!(py_repr("a'\"b"), "'a\\'\"b'");
        assert_eq!(py_repr("x\n\\\u{1}"), "'x\\n\\\\\\x01'");
    }
}
