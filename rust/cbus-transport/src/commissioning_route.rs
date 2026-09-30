//! Conservative project-topology binding for selected-serial execution.
//!
//! Mirrors the conventional route rules in Python `commissioning_route.py`:
//! the source is a directly attached CNI/Serial network, each Bridge names
//! `parent/p/far_side_address`, and every outbound transition has a BRIDGE2N
//! unit at that far-side address. This is source-derived topology evidence,
//! never proof that a physical bridge accepted or delivered a request.
//!
//! The bounded reader admits UTF-8 legacy XML and ordinary stored/deflated
//! CBZ archives. DTDs, ZIP64 directories, multidisk archives and ambiguous documents are
//! refused. Nothing is extracted to the filesystem or sent to an endpoint.

use crate::plan::ValidatedPlan;
use ring::digest::{digest, SHA256};
use roxmltree::{Document, Node, ParsingOptions};
use serde_json::{json, Value};
use std::collections::{HashMap, HashSet};
use std::fmt;
use std::fs::{self, OpenOptions};
use std::io::{Cursor, Read};
use std::path::{Path, PathBuf};

const MAX_DOCUMENT_BYTES: u64 = 128 * 1024 * 1024;
const MAX_XML_NODES: u32 = 1_000_000;
const MAX_BRIDGES: usize = 6;

/// A pre-I/O topology refusal, with the shared Python failure vocabulary.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RouteBindingError {
    reason: &'static str,
    message: String,
}

impl RouteBindingError {
    fn new(message: impl Into<String>) -> Self {
        Self {
            reason: "route_binding",
            message: message.into(),
        }
    }

    /// Stable refusal class: `route_binding` or `wrong_route`.
    pub fn reason(&self) -> &'static str {
        self.reason
    }

    /// Human-readable refusal detail.
    pub fn message(&self) -> &str {
        &self.message
    }
}

impl fmt::Display for RouteBindingError {
    fn fmt(&self, output: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(output, "{}: {}", self.reason, self.message)
    }
}

impl std::error::Error for RouteBindingError {}

type Result<T> = std::result::Result<T, RouteBindingError>;

/// A route recomputed from the exact project bytes named by a validated plan.
/// Private fields prevent callers from constructing unverified evidence.
#[derive(Debug, Clone)]
pub struct RouteBinding {
    project_path: PathBuf,
    project_sha256: String,
    source_network: u8,
    target_network: u8,
    route: Vec<u8>,
}

impl RouteBinding {
    /// Re-read the bound path immediately before creating send-intent evidence
    /// or handing a stateful request to transport. This is a fresh digest
    /// check, not a filesystem lock or physical topology observation.
    pub fn assert_fresh(&self) -> Result<()> {
        let actual = project_digest(&read_project_snapshot(&self.project_path)?);
        if actual != self.project_sha256 {
            return Err(RouteBindingError::new(format!(
                "Project topology is stale or was substituted: expected {}, got {actual}",
                self.project_sha256
            )));
        }
        Ok(())
    }

    /// Refuse a binding reused with a different route/digest, then re-read its
    /// snapshot. Public execution entry points must call this before PCI I/O.
    pub fn validate_plan(&self, plan: &ValidatedPlan) -> Result<()> {
        validate_plan_route(plan)?;
        if plan.route.as_deref() != Some(self.route.as_slice())
            || plan.project_sha256.as_deref() != Some(self.project_sha256.as_str())
        {
            return Err(RouteBindingError::new(
                "Route binding does not belong to this plan's route and project SHA-256",
            ));
        }
        self.assert_fresh()
    }

    /// Reviewable evidence with the same keys as the Python coordinator.
    pub fn evidence(&self) -> Value {
        json!({
            "project_path": self.project_path.to_str().expect("binding paths are validated UTF-8"),
            "project_sha256": self.project_sha256,
            "source_network": self.source_network,
            "target_network": self.target_network,
            "route": self.route,
            "route_rederived": true,
            "physical_bridge_acceptance_verified": false,
        })
    }
}

/// Validate direct/routed argument consistency and recompute the exact route
/// from a bounded project snapshot. Call before acquiring an endpoint or
/// creating recovery files. Direct plans admit no project/network arguments.
pub fn validate_route_binding(
    plan: &ValidatedPlan,
    project: Option<&Path>,
    source_network: Option<u8>,
    target_network: Option<u8>,
) -> Result<Option<RouteBinding>> {
    validate_plan_route(plan)?;
    let Some(route) = plan.route.as_ref() else {
        if project.is_some() || source_network.is_some() || target_network.is_some() {
            return Err(RouteBindingError::new(
                "A direct plan takes no project or network binding",
            ));
        }
        return Ok(None);
    };
    let (Some(path), Some(source), Some(target)) = (project, source_network, target_network) else {
        return Err(RouteBindingError::new(
            "A routed plan requires its project file, source network and target network",
        ));
    };
    let path = if path.is_absolute() {
        path.to_path_buf()
    } else {
        std::env::current_dir()
            .map_err(|error| {
                RouteBindingError::new(format!("Cannot resolve project path: {error}"))
            })?
            .join(path)
    };
    if path.to_str().is_none() {
        return Err(RouteBindingError::new(
            "Project path must be UTF-8 for exact recovery evidence",
        ));
    }
    let snapshot = read_project_snapshot(&path)?;
    let actual = project_digest(&snapshot);
    if plan.project_sha256.as_deref() != Some(actual.as_str()) {
        return Err(RouteBindingError::new(
            "Project snapshot does not match plan project_sha256",
        ));
    }
    let networks = snapshot_networks(&snapshot)?;
    let derived = resolve_route(&networks, source, target)?;
    if &derived != route {
        return Err(RouteBindingError {
            reason: "wrong_route",
            message: format!(
                "Plan route {route:?} differs from project route {derived:?} for networks {source}->{target}; refused before any I/O"
            ),
        });
    }
    Ok(Some(RouteBinding {
        project_path: path,
        project_sha256: actual,
        source_network: source,
        target_network: target,
        route: derived,
    }))
}

fn validate_plan_route(plan: &ValidatedPlan) -> Result<()> {
    match (&plan.route, &plan.project_sha256) {
        (None, None) => Ok(()),
        (Some(route), Some(sha256))
            if (1..=MAX_BRIDGES).contains(&route.len())
                && route.iter().all(|byte| (1..=254).contains(byte))
                && route.iter().collect::<HashSet<_>>().len() == route.len()
                && route[0] != plan.local_unit
                && sha256.len() == 64
                && sha256
                    .bytes()
                    .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte)) =>
        {
            Ok(())
        }
        _ => Err(RouteBindingError::new(
            "Invalid or inconsistent plan route/project_sha256 binding",
        )),
    }
}

fn project_digest(snapshot: &[u8]) -> String {
    hex::encode(digest(&SHA256, snapshot).as_ref())
}

fn read_project_snapshot(path: &Path) -> Result<Vec<u8>> {
    fn check(metadata: &fs::Metadata) -> Result<()> {
        if !metadata.is_file() {
            return Err(RouteBindingError::new(
                "Project snapshot must be a regular file",
            ));
        }
        if metadata.len() > MAX_DOCUMENT_BYTES {
            return Err(RouteBindingError::new(
                "Project file exceeds the configured size limit",
            ));
        }
        Ok(())
    }
    let io_error =
        |error| RouteBindingError::new(format!("Unable to read project snapshot: {error}"));
    check(&fs::metadata(path).map_err(io_error)?)?;
    let mut options = OpenOptions::new();
    options.read(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        // A FIFO substituted after metadata() must not block open().
        options.custom_flags(libc::O_NONBLOCK | libc::O_CLOEXEC);
    }
    let file = options.open(path).map_err(io_error)?;
    check(&file.metadata().map_err(io_error)?)?;
    let mut snapshot = Vec::new();
    file.take(MAX_DOCUMENT_BYTES + 1)
        .read_to_end(&mut snapshot)
        .map_err(io_error)?;
    if snapshot.len() as u64 > MAX_DOCUMENT_BYTES {
        return Err(RouteBindingError::new(
            "Project file exceeds the configured size limit",
        ));
    }
    Ok(snapshot)
}

#[derive(Debug)]
struct Network {
    interface_type: String,
    interface_address: String,
    units: HashMap<u8, String>,
}

fn snapshot_networks(snapshot: &[u8]) -> Result<HashMap<u8, Network>> {
    if !snapshot.starts_with(b"PK") {
        return xml_networks(snapshot)?.ok_or_else(|| {
            RouteBindingError::new("Expected a legacy Project or Installation XML document")
        });
    }
    let (count, directory_start) = validate_zip_directory(snapshot)?;
    let mut archive = zip::ZipArchive::new(Cursor::new(snapshot))
        .map_err(|error| RouteBindingError::new(format!("Invalid CBZ archive: {error}")))?;
    if archive.len() != count || archive.central_directory_start() != directory_start {
        return Err(RouteBindingError::new(
            "Duplicate or inconsistent CBZ members",
        ));
    }
    let mut project = None;
    let mut expanded = 0u64;
    for index in 0..count {
        let mut member = archive.by_index(index).map_err(|error| {
            RouteBindingError::new(format!("Unable to read CBZ member: {error}"))
        })?;
        let expected_size = member.size();
        expanded = expanded.checked_add(expected_size).ok_or_else(|| {
            RouteBindingError::new("Expanded CBZ archive exceeds the configured size limit")
        })?;
        if expanded > MAX_DOCUMENT_BYTES
            || member.encrypted()
            || !matches!(
                member.compression(),
                zip::CompressionMethod::Stored | zip::CompressionMethod::Deflated
            )
        {
            return Err(RouteBindingError::new(
                "Oversized or unsupported CBZ member",
            ));
        }
        let is_xml = member.name().to_ascii_lowercase().ends_with(".xml");
        let mut payload = Vec::new();
        // Read every member to validate actual lengths and CRCs, including
        // opaque nonproject members, without extracting any paths.
        (&mut member)
            .take(expected_size + 1)
            .read_to_end(&mut payload)
            .map_err(|error| RouteBindingError::new(format!("Invalid CBZ member: {error}")))?;
        if payload.len() as u64 != expected_size {
            return Err(RouteBindingError::new(
                "CBZ member size differs from its declared size",
            ));
        }
        if is_xml {
            if let Some(networks) = xml_networks(&payload)? {
                if project.replace(networks).is_some() {
                    return Err(RouteBindingError::new(
                        "CBZ contains multiple project XML members",
                    ));
                }
            }
        }
    }
    project.ok_or_else(|| RouteBindingError::new("CBZ contains no supported legacy XML project"))
}

/// Inspect the central directory before zip's filename map can erase
/// duplicates. Restrict this reader to ordinary single-disk CBZ; never trust
/// central size/count claims to allocate or decompress without bounds.
fn validate_zip_directory(bytes: &[u8]) -> Result<(usize, u64)> {
    let invalid = || RouteBindingError::new("Malformed or unsupported CBZ central directory");
    let start = bytes.len().saturating_sub(22 + u16::MAX as usize);
    let end = (start..bytes.len().saturating_sub(21))
        .rev()
        .find(|&offset| {
            bytes.get(offset..offset + 4) == Some(b"PK\x05\x06")
                && bytes.get(offset + 20..offset + 22).is_some_and(|value| {
                    offset + 22 + u16::from_le_bytes([value[0], value[1]]) as usize == bytes.len()
                })
        })
        .ok_or_else(invalid)?;
    let short = |offset| u16::from_le_bytes([bytes[offset], bytes[offset + 1]]) as usize;
    let word = |offset| u32::from_le_bytes(bytes[offset..offset + 4].try_into().unwrap()) as usize;
    let count = short(end + 10);
    if short(end + 4) != 0
        || short(end + 6) != 0
        || short(end + 8) != count
        || count == u16::MAX as usize
        || word(end + 12) == u32::MAX as usize
        || word(end + 16) == u32::MAX as usize
    {
        return Err(RouteBindingError::new(
            "ZIP64 and multidisk CBZ archives are unsupported",
        ));
    }
    let directory_start = word(end + 16);
    let mut offset = directory_start;
    if offset.checked_add(word(end + 12)) != Some(end) {
        return Err(invalid());
    }
    let mut names = HashSet::new();
    let mut expanded = 0u64;
    for _ in 0..count {
        if offset.checked_add(46).is_none_or(|next| next > end)
            || bytes.get(offset..offset + 4) != Some(b"PK\x01\x02")
        {
            return Err(invalid());
        }
        if short(offset + 8) & 1 != 0 || !matches!(short(offset + 10), 0 | 8) {
            return Err(RouteBindingError::new(
                "CBZ members must be unencrypted stored or deflated data",
            ));
        }
        if short(offset + 34) != 0 {
            return Err(invalid());
        }
        expanded += word(offset + 24) as u64;
        if expanded > MAX_DOCUMENT_BYTES {
            return Err(RouteBindingError::new(
                "Expanded CBZ archive exceeds the configured size limit",
            ));
        }
        let name_start = offset + 46;
        let name_end = name_start + short(offset + 28);
        let next = name_end + short(offset + 30) + short(offset + 32);
        if next > end || !names.insert(&bytes[name_start..name_end]) {
            return Err(RouteBindingError::new(
                "Duplicate or malformed CBZ member names",
            ));
        }
        offset = next;
    }
    if offset != end {
        return Err(invalid());
    }
    Ok((count, directory_start as u64))
}

fn children<'a, 'input>(node: Node<'a, 'input>, name: &str) -> Vec<Node<'a, 'input>> {
    node.children()
        .filter(|child| {
            child.is_element()
                && child.tag_name().name() == name
                && child.tag_name().namespace() == node.tag_name().namespace()
        })
        .collect()
}

fn scalar(node: Node<'_, '_>, name: &str, required: bool) -> Result<String> {
    let fields = children(node, name);
    if fields.len() > 1 {
        return Err(RouteBindingError::new(format!(
            "Ambiguous {name}: multiple matching fields"
        )));
    }
    let Some(field) = fields.first() else {
        return if required {
            Err(RouteBindingError::new(format!(
                "Missing required {name} field"
            )))
        } else {
            Ok(String::new())
        };
    };
    if field.children().any(|child| child.is_element()) {
        return Err(RouteBindingError::new(format!(
            "{name} must be a scalar field"
        )));
    }
    Ok(field
        .children()
        .filter_map(|child| child.text().filter(|_| child.is_text()))
        .collect())
}

fn decimal_byte(value: &str, label: &str) -> Result<u8> {
    if value.is_empty() || value.len() > 3 || !value.bytes().all(|byte| byte.is_ascii_digit()) {
        return Err(RouteBindingError::new(format!(
            "{label} must be a decimal byte"
        )));
    }
    value
        .parse()
        .map_err(|_| RouteBindingError::new(format!("{label} must be a decimal byte")))
}

fn parent_name(name: &str) -> Option<&'static str> {
    match name {
        "Network" => Some("Project"),
        "Unit" | "Application" => Some("Network"),
        "Group" => Some("Application"),
        "Level" => Some("Group"),
        _ => None,
    }
}

fn is_entity(node: Node<'_, '_>) -> bool {
    if !node.is_element() {
        return false;
    }
    let Some(parent) = node.parent() else {
        return false;
    };
    if node.tag_name().name() == "Project" {
        return parent.is_root()
            || (parent.has_tag_name("Installation")
                && parent.tag_name().namespace() == node.tag_name().namespace());
    }
    parent_name(node.tag_name().name()).is_some_and(|name| {
        parent.has_tag_name(name)
            && parent.tag_name().namespace() == node.tag_name().namespace()
            && is_entity(parent)
    })
}

fn validate_structure(project: Node<'_, '_>) -> Result<()> {
    let mut oids = HashSet::new();
    for node in project
        .document()
        .root_element()
        .descendants()
        .filter(|node| node.is_element())
    {
        let entity = is_entity(node);
        if entity {
            for name in ["OID", "Address", "TagName", "Description"] {
                scalar(node, name, false)?;
            }
        }
        let oid = match node
            .attributes()
            .find(|attribute| attribute.name().eq_ignore_ascii_case("oid"))
        {
            Some(attribute) if !attribute.value().is_empty() => attribute.value().to_owned(),
            _ => scalar(node, "OID", false)?,
        };
        if !oid.is_empty() && !oids.insert(oid) {
            return Err(RouteBindingError::new("Duplicate OID in project document"));
        }
        if node.tag_name().namespace() == project.tag_name().namespace() {
            if let Some(expected_parent) = parent_name(node.tag_name().name()) {
                if entity || !children(node, "Address").is_empty() {
                    if !node
                        .parent()
                        .is_some_and(|parent| parent.has_tag_name(expected_parent))
                    {
                        return Err(RouteBindingError::new("Invalid project entity parent"));
                    }
                    // Routing fields below require decimal bytes. For other
                    // entities retain ordinary project hex/decimal addresses.
                    structural_byte(&scalar(node, "Address", true)?)?;
                }
            }
        }
        if entity {
            if node.tag_name().name() == "Level" {
                if let Some(value) = node.attribute("Value") {
                    structural_byte(value)?;
                }
            }
            for name in ["Network", "Unit", "Application", "Group", "Level"] {
                let mut addresses = HashSet::new();
                for child in children(node, name)
                    .into_iter()
                    .filter(|child| is_entity(*child))
                {
                    if !addresses.insert(structural_byte(&scalar(child, "Address", true)?)?) {
                        return Err(RouteBindingError::new(format!("Duplicate {name} address")));
                    }
                }
            }
            if node.tag_name().name() == "Unit" {
                let mut names = HashSet::new();
                for pp in children(node, "PP") {
                    if pp.attribute("Value").is_none()
                        || pp.attribute("Name").is_none()
                        || !names.insert(pp.attribute("Name"))
                    {
                        return Err(RouteBindingError::new("Invalid or duplicate Unit PP"));
                    }
                }
            }
        }
    }
    Ok(())
}

fn structural_byte(value: &str) -> Result<u8> {
    let value = value.trim();
    let parsed = match value
        .strip_prefix("0x")
        .or_else(|| value.strip_prefix("0X"))
    {
        Some(hex) => u8::from_str_radix(hex, 16),
        None => value.parse(),
    };
    parsed.map_err(|_| RouteBindingError::new("Project entity Address/Value must be a byte"))
}

fn xml_networks(payload: &[u8]) -> Result<Option<HashMap<u8, Network>>> {
    let text = std::str::from_utf8(payload)
        .map_err(|_| RouteBindingError::new("Project XML must be UTF-8"))?;
    // roxmltree accepts but does not interpret XML encoding declarations.
    // Do not reinterpret declared legacy bytes as UTF-8 topology fields.
    let without_bom = text.trim_start_matches('\u{feff}');
    if let Some(declaration) = without_bom
        .strip_prefix("<?xml")
        .filter(|rest| rest.starts_with(char::is_whitespace))
        .and_then(|rest| rest.split("?>").next())
    {
        if let Some(encoding) = declaration.split_once("encoding").map(|(_, value)| value) {
            let value = encoding
                .trim_start()
                .strip_prefix('=')
                .unwrap_or("")
                .trim_start();
            let quote = value.chars().next().unwrap_or('\0');
            let encoding = value
                .get(1..)
                .and_then(|rest| rest.split(quote).next())
                .unwrap_or("");
            if !matches!(quote, '\'' | '"') || !encoding.eq_ignore_ascii_case("utf-8") {
                return Err(RouteBindingError::new("Project XML encoding must be UTF-8"));
            }
        }
    }
    // roxmltree admits an empty DTD even with allow_dtd=false. Refuse that
    // shape too; a conservative lexical check also refuses this in comments.
    if text.contains("<!DOCTYPE") || text.contains("<!ENTITY") {
        return Err(RouteBindingError::new(
            "DTD and entity declarations are unsupported",
        ));
    }
    let document = Document::parse_with_options(
        text,
        ParsingOptions {
            allow_dtd: false,
            nodes_limit: MAX_XML_NODES,
        },
    )
    .map_err(|error| RouteBindingError::new(format!("Invalid project XML: {error}")))?;
    let root = document.root_element();
    let project = match root.tag_name().name() {
        "Project" => root,
        "Installation" => {
            let projects = children(root, "Project");
            if projects.len() != 1 {
                return Err(RouteBindingError::new(
                    "Installation must contain exactly one Project",
                ));
            }
            projects[0]
        }
        _ => return Ok(None),
    };
    validate_structure(project)?;
    // Exact native DBGETXML snapshots identify their Project with Address and
    // omit the legacy TagName. An explicitly blank TagName still fails closed.
    let identity = if children(project, "TagName").is_empty() {
        scalar(project, "Address", true)?
    } else {
        scalar(project, "TagName", true)?
    };
    if identity.trim().is_empty() {
        return Err(RouteBindingError::new("Project identity must not be empty"));
    }
    let mut networks = HashMap::new();
    for node in children(project, "Network") {
        let address = decimal_byte(&scalar(node, "Address", true)?, "Network Address")?;
        let interfaces = children(node, "Interface");
        if interfaces.len() != 1 {
            return Err(RouteBindingError::new(format!(
                "Network {address} must contain exactly one Interface"
            )));
        }
        let mut units = HashMap::new();
        for unit in children(node, "Unit") {
            let address = decimal_byte(&scalar(unit, "Address", true)?, "Unit Address")?;
            let unit_type = scalar(unit, "UnitType", true)?.trim().to_owned();
            if unit_type.is_empty() || units.insert(address, unit_type).is_some() {
                return Err(RouteBindingError::new(
                    "Empty UnitType or duplicate unit address",
                ));
            }
        }
        // Also reject an ambiguous optional network name, as Python does.
        scalar(node, "TagName", false)?;
        let network = Network {
            interface_type: scalar(interfaces[0], "InterfaceType", true)?
                .trim()
                .to_owned(),
            interface_address: scalar(interfaces[0], "InterfaceAddress", false)?
                .trim()
                .to_owned(),
            units,
        };
        if networks.insert(address, network).is_some() {
            return Err(RouteBindingError::new("Duplicate network address"));
        }
    }
    if networks.is_empty() {
        return Err(RouteBindingError::new("Project contains no networks"));
    }
    Ok(Some(networks))
}

fn directly_attached(network: &Network) -> bool {
    network.interface_type.eq_ignore_ascii_case("CNI")
        || network.interface_type.eq_ignore_ascii_case("Serial")
}

fn resolve_route(networks: &HashMap<u8, Network>, source: u8, target: u8) -> Result<Vec<u8>> {
    let source_record = networks
        .get(&source)
        .ok_or_else(|| RouteBindingError::new("Source network is absent from the project"))?;
    if !directly_attached(source_record) {
        return Err(RouteBindingError::new("Source network must be directly attached through CNI or Serial; reverse and sibling bridge starts are unsupported"));
    }
    let mut chain = Vec::new();
    let mut seen = HashSet::new();
    let mut current = target;
    loop {
        if !seen.insert(current) {
            return Err(RouteBindingError::new("Bridge topology contains a cycle"));
        }
        let record = networks.get(&current).ok_or_else(|| {
            RouteBindingError::new("Target or bridge parent network is absent from the project")
        })?;
        if !record.interface_type.eq_ignore_ascii_case("Bridge") {
            if !directly_attached(record) {
                return Err(RouteBindingError::new("Unsupported root interface"));
            }
            if current != source {
                return Err(RouteBindingError::new(
                    "Source and target networks are disconnected",
                ));
            }
            break;
        }
        let parts: Vec<_> = record
            .interface_address
            .trim_matches('/')
            .split('/')
            .collect();
        if parts.len() != 3 || !parts[1].eq_ignore_ascii_case("p") {
            return Err(RouteBindingError::new("Malformed Bridge InterfaceAddress"));
        }
        let parent = decimal_byte(parts[0], "Bridge parent")?;
        let unit = decimal_byte(parts[2], "Bridge interface unit")?;
        if unit != current || parent == current {
            return Err(RouteBindingError::new("Bridge InterfaceAddress requires its far-side network address and a distinct parent"));
        }
        chain.push(current);
        if chain.len() > MAX_BRIDGES {
            return Err(RouteBindingError::new(
                "Network path exceeds the supported six-bridge limit",
            ));
        }
        current = parent;
    }
    chain.reverse();
    current = source;
    for &destination in &chain {
        match networks[&current].units.get(&destination) {
            Some(unit_type) if unit_type.eq_ignore_ascii_case("BRIDGE2N") => {}
            _ => {
                return Err(RouteBindingError::new(format!(
                "Network {current} requires a BRIDGE2N unit at conventional address {destination}"
            )))
            }
        }
        current = destination;
    }
    Ok(chain)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use std::sync::atomic::{AtomicU64, Ordering};

    struct Snapshot(PathBuf);

    impl Snapshot {
        fn new(payload: &[u8]) -> Self {
            static NEXT: AtomicU64 = AtomicU64::new(0);
            let directory = std::env::temp_dir().join(format!(
                "cbus-route-binding-{}-{}-{}",
                std::process::id(),
                std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .unwrap()
                    .as_nanos(),
                NEXT.fetch_add(1, Ordering::Relaxed),
            ));
            fs::create_dir(&directory).unwrap();
            let path = directory.join("project.xml");
            fs::write(&path, payload).unwrap();
            Self(path)
        }
    }

    impl Drop for Snapshot {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(self.0.parent().unwrap());
        }
    }

    fn network(address: u8, interface: &str, parent: &str, units: &[(u8, &str)]) -> String {
        let units: String = units
            .iter()
            .map(|(address, unit_type)| {
                format!("<Unit><Address>{address}</Address><UnitType>{unit_type}</UnitType></Unit>")
            })
            .collect();
        format!("<Network><Address>{address}</Address><Interface><InterfaceType>{interface}</InterfaceType><InterfaceAddress>{parent}</InterfaceAddress></Interface>{units}</Network>")
    }

    fn document(networks: &[String]) -> Vec<u8> {
        format!(
            "<Installation><Project><TagName>HOUSE</TagName>{}</Project></Installation>",
            networks.join("")
        )
        .into_bytes()
    }

    fn line(depth: u8) -> Vec<u8> {
        let mut networks = Vec::new();
        for index in 0..=depth {
            let address = 254 - index;
            let units = if index < depth {
                vec![(address - 1, "BRIDGE2N")]
            } else {
                vec![(5, "KEYGL5")]
            };
            networks.push(network(
                address,
                if index == 0 { "CNI" } else { "Bridge" },
                &if index == 0 {
                    "127.0.0.1:10001".into()
                } else {
                    format!("{}/p/{address}", address + 1)
                },
                &units,
            ));
        }
        document(&networks)
    }

    fn plan(snapshot: &[u8], route: Option<Vec<u8>>) -> ValidatedPlan {
        ValidatedPlan {
            serial: "101136.1558".into(),
            destination: 6,
            request_hex: String::new(),
            request_bytes: Vec::new(),
            command_checksum: false,
            source: 255,
            local_unit: 16,
            expected_local_serial: "101136.1500".into(),
            host: "127.0.0.1".into(),
            port: 10001,
            project_sha256: route.as_ref().map(|_| project_digest(snapshot)),
            route,
        }
    }

    fn bind(snapshot: &Snapshot, plan: &ValidatedPlan, target: u8) -> Result<Option<RouteBinding>> {
        validate_route_binding(plan, Some(&snapshot.0), Some(254), Some(target))
    }

    fn cbz(members: &[(&str, &[u8])]) -> Vec<u8> {
        let mut output = zip::ZipWriter::new(Cursor::new(Vec::new()));
        for (name, content) in members {
            output
                .start_file(
                    *name,
                    zip::write::SimpleFileOptions::default()
                        .compression_method(zip::CompressionMethod::Deflated),
                )
                .unwrap();
            output.write_all(content).unwrap();
        }
        output.finish().unwrap().into_inner()
    }

    #[test]
    fn one_to_six_bridges_bind_exact_outgoing_route_and_honest_evidence() {
        for depth in 1..=6 {
            let raw = line(depth);
            let snapshot = Snapshot::new(&raw);
            let route: Vec<u8> = [253, 252, 251, 250, 249, 248][..depth as usize].to_vec();
            let plan = plan(&raw, Some(route.clone()));
            let binding = bind(&snapshot, &plan, 254 - depth).unwrap().unwrap();
            binding.validate_plan(&plan).unwrap();
            assert_eq!(binding.evidence()["route"], json!(route));
            assert_eq!(binding.evidence()["project_sha256"], project_digest(&raw));
            assert_eq!(binding.evidence()["route_rederived"], true);
            assert_eq!(
                binding.evidence()["physical_bridge_acceptance_verified"],
                false
            );
        }
    }

    #[test]
    fn direct_plans_take_no_binding_and_routed_plans_require_all_arguments() {
        let raw = line(1);
        let direct = plan(&raw, None);
        assert!(validate_route_binding(&direct, None, None, None)
            .unwrap()
            .is_none());
        let missing = Path::new("/missing-cbus-test-project");
        for (path, source, target) in [
            (Some(missing), None, None),
            (None, Some(254), None),
            (None, None, Some(253)),
        ] {
            let error = validate_route_binding(&direct, path, source, target).unwrap_err();
            assert!(error.message().contains("direct plan"));
        }
        let routed = plan(&raw, Some(vec![253]));
        for (path, source, target) in [
            (None, Some(254), Some(253)),
            (Some(missing), None, Some(253)),
            (Some(missing), Some(254), None),
        ] {
            assert!(validate_route_binding(&routed, path, source, target)
                .unwrap_err()
                .message()
                .contains("requires"));
        }
    }

    #[test]
    fn wrong_digest_route_and_reused_binding_are_refused() {
        let raw = line(2);
        let snapshot = Snapshot::new(&raw);
        let mut plan = plan(&raw, Some(vec![253, 252]));
        let binding = bind(&snapshot, &plan, 252).unwrap().unwrap();
        plan.route = Some(vec![253]);
        assert_eq!(
            bind(&snapshot, &plan, 252).unwrap_err().reason(),
            "wrong_route"
        );
        assert!(binding.validate_plan(&plan).is_err());
        plan.route = Some(vec![253, 252]);
        plan.project_sha256 = Some("0".repeat(64));
        assert_eq!(
            bind(&snapshot, &plan, 252).unwrap_err().reason(),
            "route_binding"
        );
        assert!(binding.validate_plan(&plan).is_err());
    }

    #[test]
    fn freshness_rejects_changed_deleted_and_nonregular_snapshots() {
        let raw = line(1);
        let snapshot = Snapshot::new(&raw);
        let plan = plan(&raw, Some(vec![253]));
        let binding = bind(&snapshot, &plan, 253).unwrap().unwrap();
        fs::write(&snapshot.0, b"substituted").unwrap();
        assert!(binding
            .assert_fresh()
            .unwrap_err()
            .message()
            .contains("stale"));
        assert!(binding.validate_plan(&plan).is_err());
        fs::remove_file(&snapshot.0).unwrap();
        assert!(binding.assert_fresh().is_err());
        fs::create_dir(&snapshot.0).unwrap();
        assert!(binding
            .assert_fresh()
            .unwrap_err()
            .message()
            .contains("regular file"));
    }

    #[test]
    fn bounded_reader_refuses_oversized_files_and_fifos_without_reading() {
        let snapshot = Snapshot::new(b"");
        OpenOptions::new()
            .write(true)
            .open(&snapshot.0)
            .unwrap()
            .set_len(MAX_DOCUMENT_BYTES + 1)
            .unwrap();
        assert!(read_project_snapshot(&snapshot.0)
            .unwrap_err()
            .message()
            .contains("size limit"));
        #[cfg(unix)]
        {
            use std::os::unix::ffi::OsStrExt;
            fs::remove_file(&snapshot.0).unwrap();
            let path = std::ffi::CString::new(snapshot.0.as_os_str().as_bytes()).unwrap();
            // SAFETY: path is a valid NUL-terminated string in our own temp directory.
            assert_eq!(unsafe { libc::mkfifo(path.as_ptr(), 0o600) }, 0);
            assert!(read_project_snapshot(&snapshot.0)
                .unwrap_err()
                .message()
                .contains("regular file"));
        }
    }

    #[test]
    fn namespace_aware_scalars_ignore_foreign_extensions_but_reject_ambiguity() {
        let raw = String::from_utf8(line(1))
            .unwrap()
            .replace(
                "<Installation>",
                "<Installation xmlns='urn:cbus' xmlns:x='urn:other'>",
            )
            .replace(
                "<Address>254</Address>",
                "<Address>254</Address><x:Address>1</x:Address>",
            );
        let networks = snapshot_networks(raw.as_bytes()).unwrap();
        assert_eq!(resolve_route(&networks, 254, 253).unwrap(), [253]);
        for addition in ["<Address>1</Address>", "<Address><x:n>254</x:n></Address>"] {
            let bad = raw.replace("<Address>254</Address>", addition);
            // First case changes the source address; it cannot bind source 254.
            assert!(snapshot_networks(bad.as_bytes())
                .and_then(|n| resolve_route(&n, 254, 253))
                .is_err());
        }
        let duplicate = raw.replace(
            "<Address>254</Address>",
            "<Address>254</Address><Address>254</Address>",
        );
        assert!(snapshot_networks(duplicate.as_bytes()).is_err());
    }

    #[test]
    fn native_address_identity_routes_exact_snapshots_without_legacy_tagname() {
        for depth in [1, 6] {
            let raw = String::from_utf8(line(depth))
                .unwrap()
                .replace("<TagName>HOUSE</TagName>", "<Address>HOUSE</Address>");
            let networks = snapshot_networks(raw.as_bytes()).unwrap();
            assert_eq!(
                resolve_route(&networks, 254, 254 - depth).unwrap(),
                (254 - depth..=253).rev().collect::<Vec<_>>()
            );
            assert!(raw.contains("<Address>HOUSE</Address>"));
            assert!(!raw.contains("<TagName>HOUSE</TagName>"));
        }
    }

    #[test]
    fn missing_duplicate_native_identity_and_blank_legacy_tagname_refuse() {
        let raw = String::from_utf8(line(1)).unwrap();
        for identity in [
            "",
            "<Address></Address>",
            "<Address>HOUSE</Address><Address>OTHER</Address>",
            "<TagName></TagName><Address>HOUSE</Address>",
        ] {
            let invalid = raw.replace("<TagName>HOUSE</TagName>", identity);
            assert!(snapshot_networks(invalid.as_bytes()).is_err(), "{identity}");
        }
    }

    #[test]
    fn duplicate_entities_fields_oids_and_parameters_refuse_before_routing() {
        let raw = String::from_utf8(line(1)).unwrap();
        let cases = [
            raw.replace(
                "<TagName>HOUSE</TagName>",
                "<TagName>HOUSE</TagName><TagName>HOUSE</TagName>",
            ),
            raw.replace("<Interface>", "<Interface/><Interface>"),
            raw.replace(
                "<UnitType>BRIDGE2N</UnitType>",
                "<UnitType>BRIDGE2N</UnitType><UnitType>BRIDGE2N</UnitType>",
            ),
            raw.replace("<Unit>", "<Unit OID='same'>"),
            raw.replace(
                "</Unit>",
                "<PP Name='a' Value='1'/><PP Name='a' Value='2'/></Unit>",
            ),
            raw.replace(
                "</Unit>",
                "</Unit><Unit><Address>253</Address><UnitType>BRIDGE2N</UnitType></Unit>",
            ),
            raw.replace("</Project>", "<Unit><Address>7</Address></Unit></Project>"),
        ];
        for case in cases {
            assert!(snapshot_networks(case.as_bytes()).is_err(), "{case}");
        }
    }

    #[test]
    fn unsupported_bridge_topologies_are_not_inferred() {
        let raw = String::from_utf8(line(1)).unwrap();
        for (before, after) in [
            ("BRIDGE2N", "RELAY"),
            ("254/p/253", "254/p/252"),
            ("254/p/253", "254/q/253"),
            ("254/p/253", "252/p/253"),
            ("254/p/253", "253/p/253"),
            ("CNI", "IP"),
        ] {
            let bad = raw.replace(before, after);
            assert!(snapshot_networks(bad.as_bytes())
                .and_then(|n| resolve_route(&n, 254, 253))
                .is_err());
        }
        let networks = snapshot_networks(&line(2)).unwrap();
        assert!(resolve_route(&networks, 253, 252)
            .unwrap_err()
            .message()
            .contains("directly attached"));
        assert!(resolve_route(&networks, 253, 254).is_err());
        assert!(resolve_route(&networks, 254, 99).is_err());
        assert!(
            resolve_route(&snapshot_networks(&line(7)).unwrap(), 254, 247)
                .unwrap_err()
                .message()
                .contains("six-bridge")
        );
        let cycle = document(&[
            network(254, "CNI", "local", &[]),
            network(253, "Bridge", "252/p/253", &[(252, "BRIDGE2N")]),
            network(252, "Bridge", "253/p/252", &[(253, "BRIDGE2N")]),
        ]);
        assert!(resolve_route(&snapshot_networks(&cycle).unwrap(), 254, 253)
            .unwrap_err()
            .message()
            .contains("cycle"));
        let disconnected = document(&[
            network(254, "CNI", "local", &[]),
            network(253, "Serial", "other", &[]),
        ]);
        assert!(
            resolve_route(&snapshot_networks(&disconnected).unwrap(), 254, 253)
                .unwrap_err()
                .message()
                .contains("disconnected")
        );
    }

    #[test]
    fn cbz_binds_archive_bytes_and_refuses_multiple_or_duplicate_projects() {
        let raw = line(1);
        let archive = cbz(&[("project.xml", &raw), ("opaque.bin", b"opaque")]);
        let snapshot = Snapshot::new(&archive);
        bind(&snapshot, &plan(&archive, Some(vec![253])), 253).unwrap();
        assert!(bind(&snapshot, &plan(&raw, Some(vec![253])), 253).is_err());
        let multiple = cbz(&[("a.xml", &raw), ("b.xml", &raw)]);
        assert!(snapshot_networks(&multiple)
            .unwrap_err()
            .message()
            .contains("multiple"));
        let mut duplicate = multiple;
        for index in 0..duplicate.len() - 5 {
            if &duplicate[index..index + 5] == b"b.xml" {
                duplicate[index] = b'a';
            }
        }
        assert!(snapshot_networks(&duplicate)
            .unwrap_err()
            .message()
            .contains("Duplicate"));
    }

    #[test]
    fn archive_declared_expansion_codec_encryption_and_crc_fail_closed() {
        let raw = line(1);
        let archive = cbz(&[("project.xml", &raw)]);
        let directory = archive
            .windows(4)
            .position(|window| window == b"PK\x01\x02")
            .unwrap();
        let mut expanded = archive.clone();
        expanded[directory + 24..directory + 28]
            .copy_from_slice(&((MAX_DOCUMENT_BYTES + 1) as u32).to_le_bytes());
        assert!(snapshot_networks(&expanded)
            .unwrap_err()
            .message()
            .contains("size limit"));
        let mut encrypted = archive.clone();
        encrypted[directory + 8] |= 1;
        assert!(snapshot_networks(&encrypted).is_err());
        let mut codec = archive.clone();
        codec[directory + 10] = 12;
        assert!(snapshot_networks(&codec).is_err());
        let mut crc = archive;
        crc[directory + 16] ^= 1;
        assert!(snapshot_networks(&crc).is_err());
    }

    #[test]
    fn dtd_sql_malformed_archives_and_unsupported_encodings_are_refused() {
        for raw in [
            b"<!DOCTYPE Project><Project/>".as_slice(),
            b"SQLite format 3\0",
            b"PKbad",
            b"<Installation><Project/><Project/></Installation>",
            b"<?xml version='1.0' encoding='ISO-8859-1'?><Project/>",
            b"\xff\xfe<\0P\0",
        ] {
            assert!(snapshot_networks(raw).is_err());
        }
    }
}
