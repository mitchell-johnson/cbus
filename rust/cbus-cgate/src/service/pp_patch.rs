//! Bounded, operator-supplied patch manifests for `PP WRITE_PATCH`.
//!
//! Schneider's `patchset.zip` is proprietary and is not shipped with
//! cmqttd.  This module provides an explicit JSON replacement in the
//! controlled C-Gate `FILE` namespace.  Selection retains the native unit
//! type / inclusive firmware / catalogue / target-version dimensions while
//! requiring an expected current patch version before any write can begin.

use serde::Deserialize;
use std::collections::HashSet;

use crate::{file, Server, Unit};

pub(crate) const SCHEMA: &str = "cmqttd.pp-patch/v1";
pub(crate) const PROJECT_MANIFEST: &str = "patchsets/cmqttd-patches.json";
const MAX_MANIFEST_BYTES: usize = 1024 * 1024;
const MAX_PATCHES: usize = 1024;
const MAX_BLOCKS: usize = 4096;
// The two non-overlapping native ranges contain 128 + 8 bytes.
const MAX_PATCH_BYTES: usize = 136;

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
struct Manifest {
    schema: String,
    version: String,
    patches: Vec<PatchDocument>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct PatchDocument {
    unit_type: String,
    min_firmware: String,
    max_firmware: String,
    #[serde(default)]
    catalog_number: Option<String>,
    patch_version: String,
    current_patch_versions: Vec<String>,
    #[serde(default = "default_patch_version_parameter")]
    patch_version_parameter: u8,
    blocks: Vec<BlockDocument>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct BlockDocument {
    parameter: u8,
    data_hex: String,
    #[serde(default)]
    unlock: bool,
}

fn default_patch_version_parameter() -> u8 {
    // C-Gate 3.4's CBusUnit constructor initializes N() to decimal 242 and
    // mi.java uses N() for both patch-version unlock and tagged STORE.
    0xf2
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct ResolvedBlock {
    pub parameter: u8,
    pub data: Vec<u8>,
    pub unlock: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct ResolvedPatch {
    pub manifest_path: String,
    pub manifest_version: String,
    pub manifest_sha256: String,
    pub unit_type: String,
    pub min_firmware: String,
    pub max_firmware: String,
    pub target_version: u8,
    pub current_versions: Vec<u8>,
    pub patch_version_parameter: u8,
    pub blocks: Vec<ResolvedBlock>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct ManifestInfo {
    pub version: String,
    pub debug: Vec<String>,
}

pub(crate) fn manifest_info(model: &Server, project: &str) -> Result<ManifestInfo, String> {
    let (path, _sha256, manifest) = load_manifest(model, project)?;
    let mut debug = Vec::new();
    for (index, patch) in manifest.patches.iter().enumerate() {
        debug.push(format!("347-Patch name: {path}#{}", index + 1));
        for block in &patch.blocks {
            let block_type = if block.parameter == 247 {
                3
            } else if block.unlock {
                1
            } else {
                0
            };
            let bytes = hex::decode(&block.data_hex)
                .expect("load_manifest validated every debug block before projection");
            let bytes = bytes
                .iter()
                .map(|byte| format!(" ${byte:x}"))
                .collect::<String>();
            debug.push(format!(
                "347-type: {block_type} start add: ${:x} bytes:{bytes}",
                block.parameter
            ));
        }
        if index + 1 != manifest.patches.len() {
            debug.push("347-".to_string());
        }
    }
    Ok(ManifestInfo {
        version: manifest.version,
        debug,
    })
}

pub(crate) fn select(
    model: &Server,
    project: &str,
    unit: &Unit,
    target_version: u8,
) -> Result<ResolvedPatch, String> {
    let (manifest_path, manifest_sha256, manifest) = load_manifest(model, project)?;
    let catalog_number = unit
        .fields
        .get("CatalogNumber")
        .or_else(|| unit.fields.get("CatalogueNumber"))
        .cloned();
    let mut matches = Vec::new();
    for patch in manifest.patches {
        if patch.unit_type == unit.unit_type
            && firmware_in_range(&unit.firmware, &patch.min_firmware, &patch.max_firmware)?
            && parse_version(&patch.patch_version)? == target_version
            && patch
                .catalog_number
                .as_ref()
                .is_none_or(|expected| catalog_number.as_ref() == Some(expected))
        {
            matches.push(patch);
        }
    }
    let Some(document) = matches.pop() else {
        return Err(format!(
            "No matching patch for type={} firmware={} catalog={} version={target_version:02X}",
            unit.unit_type,
            unit.firmware,
            catalog_number.as_deref().unwrap_or("<none>")
        ));
    };
    if !matches.is_empty() {
        return Err("Patch manifest contains more than one matching patch".to_string());
    }
    resolve_document(
        manifest_path,
        manifest.version,
        manifest_sha256,
        document,
        target_version,
    )
}

fn load_manifest(model: &Server, project: &str) -> Result<(String, String, Manifest), String> {
    let project_path = format!("%{project}%/{PROJECT_MANIFEST}");
    let candidates = [project_path, PROJECT_MANIFEST.to_string()];
    let mut selected = None;
    for path in candidates {
        if let Ok(bytes) = file::read_bytes(model, &path) {
            selected = Some((path, bytes));
            break;
        }
    }
    let Some((path, bytes)) = selected else {
        return Err(format!(
            "No patch manifest; upload {PROJECT_MANIFEST} with FILE UPLOAD"
        ));
    };
    if bytes.is_empty() || bytes.len() > MAX_MANIFEST_BYTES {
        return Err("Patch manifest must contain 1..1048576 bytes".to_string());
    }
    let manifest: Manifest = serde_json::from_slice(&bytes)
        .map_err(|error| format!("Invalid patch manifest JSON: {error}"))?;
    if manifest.schema != SCHEMA {
        return Err(format!(
            "Unsupported patch manifest schema {:?}; expected {SCHEMA}",
            manifest.schema
        ));
    }
    validate_token("manifest version", &manifest.version, 128)?;
    if manifest.patches.is_empty() || manifest.patches.len() > MAX_PATCHES {
        return Err(format!(
            "Patch manifest must contain 1..{MAX_PATCHES} patches"
        ));
    }
    // PATCH_VERSION must never advertise a structurally invalid document.
    // Resolve every selector against its own declared target to exercise all
    // string, address, range, overlap and byte-count checks at load time.
    for document in &manifest.patches {
        let target = parse_version(&document.patch_version)?;
        resolve_document(
            path.clone(),
            manifest.version.clone(),
            String::new(),
            document.clone(),
            target,
        )?;
    }
    let sha256 = crate::manual::sha256_hex(&bytes);
    Ok((path, sha256, manifest))
}

fn resolve_document(
    manifest_path: String,
    manifest_version: String,
    manifest_sha256: String,
    document: PatchDocument,
    target_version: u8,
) -> Result<ResolvedPatch, String> {
    validate_token("unitType", &document.unit_type, 128)?;
    validate_token("minFirmware", &document.min_firmware, 64)?;
    validate_token("maxFirmware", &document.max_firmware, 64)?;
    if document.min_firmware > document.max_firmware {
        return Err("Patch target firmware range is reversed".to_string());
    }
    if let Some(catalog) = &document.catalog_number {
        validate_token("catalogNumber", catalog, 128)?;
    }
    if parse_version(&document.patch_version)? != target_version {
        return Err("Selected patch version does not match the command".to_string());
    }
    if target_version == u8::MAX {
        return Err(
            "Patch target FF is reserved for the native interrupted-write sentinel".to_string(),
        );
    }
    if document.current_patch_versions.is_empty() {
        return Err("Patch must declare at least one currentPatchVersions value".to_string());
    }
    if document.patch_version_parameter != 0xf2 {
        return Err(format!(
            "Unsupported patchVersionParameter {}; native C-Gate 3.4 uses 242 (0xF2)",
            document.patch_version_parameter
        ));
    }
    let mut current_versions = Vec::with_capacity(document.current_patch_versions.len());
    for version in document.current_patch_versions {
        let version = parse_version(&version)?;
        if !current_versions.contains(&version) {
            current_versions.push(version);
        }
    }
    if document.blocks.is_empty() || document.blocks.len() > MAX_BLOCKS {
        return Err(format!("Patch must contain 1..{MAX_BLOCKS} blocks"));
    }
    let mut claimed = HashSet::new();
    let mut bytes_total = 0usize;
    let mut blocks = Vec::with_capacity(document.blocks.len());
    for block in document.blocks {
        let data = hex::decode(&block.data_hex).map_err(|error| {
            format!("Invalid dataHex for parameter {}: {error}", block.parameter)
        })?;
        if data.is_empty() || data.len() > 12 {
            return Err(format!(
                "Patch block at parameter {} must contain 1..12 bytes",
                block.parameter
            ));
        }
        let end = usize::from(block.parameter) + data.len();
        let in_native_range = (114..=241).contains(&block.parameter) && end <= 242
            || (247..=254).contains(&block.parameter) && end <= 255;
        if !in_native_range {
            return Err(format!(
                "Patch block {}..{} is outside native patch memory ranges 114..241 and 247..254",
                block.parameter,
                end - 1
            ));
        }
        for parameter in usize::from(block.parameter)..end {
            if !claimed.insert(parameter as u8) {
                return Err(format!("Patch blocks overlap at parameter {parameter}"));
            }
        }
        bytes_total += data.len();
        if bytes_total > MAX_PATCH_BYTES {
            return Err(format!("Patch exceeds the {MAX_PATCH_BYTES}-byte limit"));
        }
        blocks.push(ResolvedBlock {
            parameter: block.parameter,
            data,
            // Native patch files always use the custom unlock path at 0xF7.
            unlock: block.unlock || block.parameter == 247,
        });
    }
    Ok(ResolvedPatch {
        manifest_path,
        manifest_version,
        manifest_sha256,
        unit_type: document.unit_type,
        min_firmware: document.min_firmware,
        max_firmware: document.max_firmware,
        target_version,
        current_versions,
        patch_version_parameter: document.patch_version_parameter,
        blocks,
    })
}

fn validate_token(label: &str, value: &str, maximum: usize) -> Result<(), String> {
    if value.is_empty()
        || value.len() > maximum
        || !value.bytes().all(|byte| {
            byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b'-' | b':' | b'/' | b'+')
        })
    {
        return Err(format!(
            "Invalid {label}; expected 1..{maximum} safe ASCII token characters"
        ));
    }
    Ok(())
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum VersionParseError {
    Syntax,
    OutOfRange,
}

impl std::fmt::Display for VersionParseError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Syntax => formatter.write_str("Invalid patch version syntax"),
            Self::OutOfRange => formatter.write_str("Patch version is outside the byte range"),
        }
    }
}

impl From<VersionParseError> for String {
    fn from(error: VersionParseError) -> Self {
        error.to_string()
    }
}

pub(crate) fn parse_version(value: &str) -> Result<u8, VersionParseError> {
    let value = value.trim();
    let (digits, radix) = if let Some(digits) = value
        .strip_prefix("0x")
        .or_else(|| value.strip_prefix("0X"))
        .or_else(|| value.strip_prefix('$'))
    {
        (digits, 16)
    } else if let Some(digits) = value
        .strip_prefix("0b")
        .or_else(|| value.strip_prefix("0B"))
    {
        (digits, 2)
    } else {
        (value, 16)
    };
    // Java Integer.parseInt accepts a sign after mJ strips its radix prefix.
    // mc treats its -1 sentinel as syntax, while other parsed non-byte values
    // reach mi and become a PatchException. Preserve that status split.
    let (sign, digits) = if let Some(digits) = digits.strip_prefix('+') {
        (1_i64, digits)
    } else if let Some(digits) = digits.strip_prefix('-') {
        (-1_i64, digits)
    } else {
        (1_i64, digits)
    };
    let valid_digit = |byte: u8| match radix {
        2 => matches!(byte, b'0' | b'1'),
        _ => byte.is_ascii_hexdigit(),
    };
    if digits.is_empty() || digits.len() > 32 || !digits.bytes().all(valid_digit) {
        return Err(VersionParseError::Syntax);
    }
    let magnitude = i64::from_str_radix(digits, radix).map_err(|_| VersionParseError::Syntax)?;
    let parsed = magnitude
        .checked_mul(sign)
        .ok_or(VersionParseError::Syntax)?;
    if !(i32::MIN as i64..=i32::MAX as i64).contains(&parsed) || parsed == -1 {
        return Err(VersionParseError::Syntax);
    }
    u8::try_from(parsed).map_err(|_| VersionParseError::OutOfRange)
}

pub(crate) fn firmware_in_range(
    firmware: &str,
    minimum: &str,
    maximum: &str,
) -> Result<bool, String> {
    validate_token("firmware", firmware, 64)?;
    validate_token("minimum firmware", minimum, 64)?;
    validate_token("maximum firmware", maximum, 64)?;
    if minimum > maximum {
        return Err("Patch target firmware range is reversed".to_string());
    }
    Ok(firmware >= minimum && firmware <= maximum)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{AccessLevel, Project};
    use std::collections::HashMap;

    fn model_with_manifest(document: &str) -> (Server, Unit) {
        let mut model = Server::new(AccessLevel::Program);
        model.projects.insert(
            "P".into(),
            Project {
                name: "P".into(),
                networks: HashMap::new(),
            },
        );
        model.file_store.insert("%P%/patchsets/".into(), Vec::new());
        model.file_store.insert(
            "%P%/patchsets/cmqttd-patches.json".into(),
            document.as_bytes().to_vec(),
        );
        let mut unit = Unit::blank(5, "test");
        unit.unit_type = "KEYGL5".into();
        unit.firmware = "5.5.00".into();
        (model, unit)
    }

    #[test]
    fn exact_target_selects_and_decodes_bounded_native_blocks() {
        let (model, unit) = model_with_manifest(
            r#"{"schema":"cmqttd.pp-patch/v1","version":"test-1","patches":[{"unitType":"KEYGL5","minFirmware":"5.0","maxFirmware":"6.0","patchVersion":"01","currentPatchVersions":["00"],"blocks":[{"parameter":114,"dataHex":"aabb"},{"parameter":247,"dataHex":"cc"}]}]}"#,
        );
        let patch = select(&model, "P", &unit, 1).unwrap();
        assert_eq!(patch.manifest_version, "test-1");
        assert_eq!(patch.current_versions, [0]);
        assert_eq!(patch.blocks[0].data, [0xaa, 0xbb]);
        assert!(!patch.blocks[0].unlock);
        assert!(patch.blocks[1].unlock);
    }

    #[test]
    fn malformed_ambiguous_and_out_of_range_documents_fail_closed() {
        for document in [
            r#"{"schema":"wrong","version":"x","patches":[]}"#,
            r#"{"schema":"cmqttd.pp-patch/v1","version":"x","patches":[{"unitType":"KEYGL5","minFirmware":"5","maxFirmware":"6","patchVersion":"01","currentPatchVersions":[],"blocks":[{"parameter":114,"dataHex":"aa"}]}]}"#,
            r#"{"schema":"cmqttd.pp-patch/v1","version":"x","patches":[{"unitType":"KEYGL5","minFirmware":"5","maxFirmware":"6","patchVersion":"01","currentPatchVersions":["00"],"blocks":[{"parameter":113,"dataHex":"aa"}]}]}"#,
            r#"{"schema":"cmqttd.pp-patch/v1","version":"x","patches":[{"unitType":"KEYGL5","minFirmware":"5","maxFirmware":"6","patchVersion":"01","currentPatchVersions":["00"],"blocks":[{"parameter":114,"dataHex":"aa"},{"parameter":114,"dataHex":"bb"}]}]}"#,
            r#"{"schema":"cmqttd.pp-patch/v1","version":"x","patches":[{"unitType":"KEYGL5","minFirmware":"5","maxFirmware":"6","patchVersion":"01","currentPatchVersions":["00"],"patchVersionParameter":5,"blocks":[{"parameter":114,"dataHex":"aa"}]}]}"#,
            r#"{"schema":"cmqttd.pp-patch/v1","version":"x","patches":[{"unitType":"KEYGL5","minFirmware":"5","maxFirmware":"6","patchVersion":"FF","currentPatchVersions":["00"],"blocks":[{"parameter":114,"dataHex":"aa"}]}]}"#,
        ] {
            let (model, unit) = model_with_manifest(document);
            assert!(select(&model, "P", &unit, 1).is_err(), "{document}");
        }
    }

    #[test]
    fn firmware_ranges_retain_native_case_sensitive_lexical_ordering() {
        let (model, mut unit) = model_with_manifest(
            r#"{"schema":"cmqttd.pp-patch/v1","version":"lexical","patches":[{"unitType":"KEYGL5","minFirmware":"9.5","maxFirmware":"9.9","patchVersion":"01","currentPatchVersions":["00"],"blocks":[{"parameter":114,"dataHex":"aa"}]}]}"#,
        );
        unit.firmware = "10.0".into();
        assert!(select(&model, "P", &unit, 1)
            .unwrap_err()
            .contains("No matching patch"));
        unit.firmware = "9.6".into();
        assert!(select(&model, "P", &unit, 1).is_ok());
        unit.firmware = "9.4".into();
        assert!(select(&model, "P", &unit, 1)
            .unwrap_err()
            .contains("No matching patch"));
    }

    #[test]
    fn catalog_constrained_patch_requires_saved_catalog_metadata() {
        let (model, mut unit) = model_with_manifest(
            r#"{"schema":"cmqttd.pp-patch/v1","version":"catalog","patches":[{"unitType":"KEYGL5","minFirmware":"5.0","maxFirmware":"6.0","catalogNumber":"5085EDLW","patchVersion":"01","currentPatchVersions":["00"],"blocks":[{"parameter":114,"dataHex":"aa"}]}]}"#,
        );
        assert!(select(&model, "P", &unit, 1)
            .unwrap_err()
            .contains("No matching patch"));
        unit.fields
            .insert("CatalogNumber".to_string(), "5085EDLW".to_string());
        assert!(select(&model, "P", &unit, 1).is_ok());
    }

    #[test]
    fn command_versions_accept_native_hex_prefixes_and_reject_non_bytes() {
        for spelling in [
            "01", "0x01", "0X01", "$01", "0b1", "0B0001", "+01", "0x+01", "$+01", "0b+1",
            "00000001",
        ] {
            assert_eq!(parse_version(spelling).unwrap(), 1, "{spelling}");
        }
        for spelling in ["", "0x", "$", "-1", "xyz", "999999999999999999999"] {
            assert_eq!(
                parse_version(spelling).unwrap_err(),
                VersionParseError::Syntax,
                "{spelling}"
            );
        }
        for spelling in ["100", "-2", "0x-2"] {
            assert_eq!(
                parse_version(spelling).unwrap_err(),
                VersionParseError::OutOfRange,
                "{spelling}"
            );
        }
    }

    #[test]
    fn patch_version_rejects_response_injection_and_invalid_inner_documents() {
        for document in [
            r#"{"schema":"cmqttd.pp-patch/v1","version":"safe\r\n[evil] 200 OK","patches":[{"unitType":"KEYGL5","minFirmware":"5","maxFirmware":"6","patchVersion":"01","currentPatchVersions":["00"],"blocks":[{"parameter":114,"dataHex":"aa"}]}]}"#,
            r#"{"schema":"cmqttd.pp-patch/v1","version":"safe","patches":[{"unitType":"KEYGL5\nINJECT","minFirmware":"5","maxFirmware":"6","patchVersion":"01","currentPatchVersions":["00"],"blocks":[{"parameter":114,"dataHex":"aa"}]}]}"#,
            r#"{"schema":"cmqttd.pp-patch/v1","version":"safe","patches":[{"unitType":"KEYGL5","minFirmware":"5","maxFirmware":"6","patchVersion":"01","currentPatchVersions":["00"],"blocks":[{"parameter":114,"dataHex":"aa"},{"parameter":114,"dataHex":"bb"}]}]}"#,
        ] {
            let (model, _) = model_with_manifest(document);
            assert!(manifest_info(&model, "P").is_err(), "{document}");
        }
    }

    #[test]
    fn debug_projection_preserves_manifest_order_and_blank_patch_separator() {
        let (model, _) = model_with_manifest(
            r#"{"schema":"cmqttd.pp-patch/v1","version":"debug","patches":[{"unitType":"A","minFirmware":"1","maxFirmware":"2","patchVersion":"01","currentPatchVersions":["00"],"blocks":[{"parameter":114,"dataHex":"aa"}]},{"unitType":"B","minFirmware":"1","maxFirmware":"2","patchVersion":"02","currentPatchVersions":["00"],"blocks":[{"parameter":247,"dataHex":"bb"}]}]}"#,
        );
        let info = manifest_info(&model, "P").unwrap();
        assert_eq!(
            info.debug,
            [
                "347-Patch name: %P%/patchsets/cmqttd-patches.json#1",
                "347-type: 0 start add: $72 bytes: $aa",
                "347-",
                "347-Patch name: %P%/patchsets/cmqttd-patches.json#2",
                "347-type: 3 start add: $f7 bytes: $bb",
            ]
        );
    }
}
