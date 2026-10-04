//! Native CGL 1.1 exchange over cmqttd's durable database label graph.
//!
//! The rules follow owned C-Gate 3.4.0.2001 captures in
//! `testdata/fixtures/native_cgate_cgl_routes.json`. CGL moves only project
//! network/application/group/level labels: it never opens a host path,
//! starts a network, sends PCI traffic or programs an automation controller.
//!
//! Routes come from database bridge Units, not from network interface
//! records: a Unit whose `UnitType` starts with `BRIDGE` or contains `GATE`
//! on network N is a directional edge to the network whose address equals
//! the Unit address. At most six networks follow the local one, and the
//! first shortest path in database Unit order wins.
//!
//! Application export follows retained creation order. Repositories without
//! that history use the explicit unknown-history numeric fallback. Selected
//! remaining differences from native are deliberate and documented: groups
//! and levels export in address order (native keeps creation order),
//! `createdBy` names cmqttd, Jackson exception detail is not
//! reproduced after the native prefix, and an import that would create a
//! nameless object is refused before mutation because native accepts it but
//! can then never save the project.

use std::collections::{BTreeMap, BTreeSet, HashMap, VecDeque};

use chrono::{DateTime, NaiveDate, NaiveDateTime, SecondsFormat, Utc};
use serde::Serialize;
use serde_json::{Map, Value};

use crate::{err, fresh_oid, DbLevel, Project, Response, Server};

/// C-Bus source routes carry at most six bridge hops.
const MAX_ROUTE: usize = 6;
const CREATED_BY: &str = "cmqttd";
const IMPORT_FAILED: &str = "408 Operation failed: CGL import failed: Import failed.  Exception: ";
const NPE: &str = "java.lang.NullPointerException";
const PARSE_FAILED: &str = "400 Syntax Error: CGL validation failed: Import Failed: ";
const VALIDATION_FAILED: &str =
    "400 Syntax Error: CGL validation failed: Validation failed.  Exception: ";

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct ExportRoot {
    cgl_version: &'static str,
    created_by: &'static str,
    created_time: String,
    local_network: u8,
    networks: Vec<ExportNetwork>,
}

#[derive(Serialize)]
struct ExportNetwork {
    address: u8,
    name: String,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    route: Vec<u8>,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    applications: Vec<ExportApplication>,
}

#[derive(Serialize)]
struct ExportApplication {
    address: u8,
    #[serde(rename = "type")]
    application_type: u8,
    name: String,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    groups: Vec<ExportGroup>,
}

#[derive(Serialize)]
struct ExportGroup {
    address: u8,
    name: String,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    levels: Vec<ExportLevel>,
}

#[derive(Serialize)]
struct ExportLevel {
    address: u8,
    name: String,
}

/// Application types retained by native export; every other application is
/// exported as Lighting (56).
fn export_type(application: u8) -> u8 {
    match application {
        25 | 172 | 173 | 192 | 202 | 203 | 205 | 206 | 208 | 213 | 223 | 224 | 228 | 251 => {
            application
        }
        _ => 56,
    }
}

fn is_bridge_type(unit_type: &str) -> bool {
    unit_type.starts_with("BRIDGE") || unit_type.contains("GATE")
}

/// Networks in native project order: creation sequence, then address for
/// records restored without one.
fn project_order(project: &Project) -> Vec<u8> {
    let mut networks = project
        .networks
        .values()
        .map(|network| {
            (
                network.created_seq == 0,
                network.created_seq,
                network.address,
            )
        })
        .collect::<Vec<_>>();
    networks.sort_unstable();
    networks
        .into_iter()
        .map(|(_, _, address)| address)
        .collect()
}

/// Directional bridge edges from `network` in database Unit order: complete
/// Network XML order first, then cmqttd-issued OIDs, which increase with
/// creation, then address.
fn bridge_edges(project: &Project, network: u8) -> Vec<u8> {
    let Some(record) = project.networks.get(&network) else {
        return Vec::new();
    };
    let mut units = record
        .units
        .values()
        .map(|unit| {
            let position = record
                .unit_xml_order
                .iter()
                .position(|address| *address == unit.address)
                .unwrap_or(usize::MAX);
            (
                position,
                unit.oid.clone(),
                unit.address,
                unit.field("UnitType"),
            )
        })
        .collect::<Vec<_>>();
    units.sort();
    units
        .into_iter()
        .filter(|(_, _, address, unit_type)| {
            is_bridge_type(unit_type) && project.networks.contains_key(address)
        })
        .map(|(_, _, address, _)| address)
        .collect()
}

/// Native CGL route from `start` to `end`: the networks after `start`.
///
/// Native C-Gate enumerates every simple path of at most six networks and
/// keeps the first shortest one in Unit order. The same path is the
/// lexicographically first shortest walk, found here from reverse distances
/// without the exponential enumeration.
fn cgl_route(project: &Project, start: u8, end: u8) -> Option<Vec<u8>> {
    if start == end || !project.networks.contains_key(&start) {
        return None;
    }
    let edges = project
        .networks
        .keys()
        .map(|network| (*network, bridge_edges(project, *network)))
        .collect::<HashMap<_, _>>();
    let mut distance = HashMap::from([(end, 0usize)]);
    let mut queue = VecDeque::from([end]);
    while let Some(target) = queue.pop_front() {
        let next = distance[&target] + 1;
        if next > MAX_ROUTE {
            continue;
        }
        for (source, targets) in &edges {
            if *source != start && targets.contains(&target) && !distance.contains_key(source) {
                distance.insert(*source, next);
                queue.push_back(*source);
            }
        }
    }
    let mut remaining = *edges[&start]
        .iter()
        .filter_map(|next| distance.get(next))
        .min()?
        + 1;
    if remaining > MAX_ROUTE {
        return None;
    }
    let mut route = Vec::new();
    let mut current = start;
    while current != end {
        remaining -= 1;
        current = *edges[&current]
            .iter()
            .find(|next| **next != start && distance.get(next) == Some(&remaining))?;
        route.push(current);
    }
    Some(route)
}

/// The local network plus every project network with a CGL route from it.
fn routable(project: &Project, local: i64) -> BTreeSet<i64> {
    let mut networks = BTreeSet::from([local]);
    if let Ok(local) = u8::try_from(local) {
        for network in project.networks.keys() {
            if cgl_route(project, local, *network).is_some() {
                networks.insert(i64::from(*network));
            }
        }
    }
    networks
}

/// Native comma-delimited integer list; `None` selects everything.
fn parse_selection(raw: Option<&str>, label: &str) -> Result<Option<BTreeSet<u8>>, String> {
    let Some(raw) = raw.filter(|raw| *raw != "*") else {
        return Ok(None);
    };
    let mut values = BTreeSet::new();
    for value in raw.split(',').filter(|value| !value.is_empty()) {
        let value = value
            .parse::<i64>()
            .map_err(|_| format!("400 Syntax Error: Invalid integer parameter : {label}"))?;
        let value = u8::try_from(value).map_err(|_| {
            format!("400 Syntax Error: Integer parameter is out of range : {label}")
        })?;
        values.insert(value);
    }
    Ok(Some(values))
}

fn selected(selection: &Option<BTreeSet<u8>>, address: u8) -> bool {
    selection
        .as_ref()
        .is_none_or(|selection| selection.contains(&address))
}

fn created_time() -> String {
    Utc::now().to_rfc3339_opts(SecondsFormat::Millis, false)
}

/// Application and group tag names on one network, keyed by address.
fn network_labels(
    model: &Server,
    project_name: &str,
    network_address: u8,
) -> BTreeMap<u8, (String, BTreeMap<u8, String>)> {
    let mut applications = BTreeMap::<u8, (String, BTreeMap<u8, String>)>::new();
    let mut groups = Vec::new();
    for (path, value) in &model.db_fields {
        let parts = path.trim_start_matches('/').split('/').collect::<Vec<_>>();
        match parts.as_slice() {
            [project, network, application, "TagName"]
                if *project == project_name && network.parse::<u8>() == Ok(network_address) =>
            {
                if let Ok(application) = application.parse::<u8>() {
                    applications.entry(application).or_default().0 = value.clone();
                }
            }
            [project, network, application, group, "TagName"]
                if *project == project_name && network.parse::<u8>() == Ok(network_address) =>
            {
                if let (Ok(application), Ok(group)) =
                    (application.parse::<u8>(), group.parse::<u8>())
                {
                    groups.push((application, group, value.clone()));
                }
            }
            _ => {}
        }
    }
    for (application, group, name) in groups {
        if let Some((_, groups)) = applications.get_mut(&application) {
            groups.insert(group, name);
        }
    }
    applications
}

/// Export the project label graph with native 343/347/344 framing.
///
/// The network list only selects `localNetwork`: the last project network in
/// the list. Every network reachable from it is exported with its route.
pub(crate) fn export(model: &Server, tag: &str, words: &[&str], current: Option<&str>) -> Response {
    let project_name = match words.get(2) {
        Some(name) => *name,
        None => match current {
            Some(name) => name,
            None => return err(tag, 400, "400 Syntax Error: No project in use"),
        },
    };
    let Some(project) = model.projects.get(project_name) else {
        return err(
            tag,
            401,
            &format!("401 Bad object or device ID: {project_name} (Network not found)"),
        );
    };
    let network_selection = match parse_selection(words.get(3).copied(), "<network list>") {
        Ok(selection) => selection,
        Err(text) => return err(tag, 400, &text),
    };
    let application_selection = match parse_selection(words.get(4).copied(), "<application list>") {
        Ok(selection) => selection,
        Err(text) => return err(tag, 400, &text),
    };
    if words.len() > 5 {
        return err(tag, 400, "400 Syntax Error: Too many parameters");
    }
    let order = project_order(project);
    let Some(local) = order
        .iter()
        .rev()
        .copied()
        .find(|network| selected(&network_selection, *network))
    else {
        return Response {
            tag: tag.to_string(),
            lines: vec!["343-Begin CGL snippet".to_string()],
            final_text: "408 Operation failed: CGL export failed: Export failed.  Exception: com.clipsal.cgate.cgl.CglException: Local address is missing.".to_string(),
            status: 408,
        };
    };

    let mut exported_objects = 0usize;
    let mut networks = Vec::new();
    for network_address in order {
        let route = if network_address == local {
            Vec::new()
        } else if let Some(route) = cgl_route(project, local, network_address) {
            route
        } else {
            continue;
        };
        let prefix = format!("//{project_name}/{network_address}");
        let mut applications = Vec::new();
        let mut labels = network_labels(model, project_name, network_address);
        let application_order = project.networks[&network_address]
            .application_addresses_in_creation_order(labels.keys().copied());
        for application in application_order {
            let (name, group_names) = labels
                .remove(&application)
                .expect("ordered application belongs to the live label graph");
            if application == 255 || !selected(&application_selection, application) {
                continue;
            }
            exported_objects += 1;
            let mut groups = Vec::new();
            for (group, group_name) in group_names {
                if group == 255 {
                    continue;
                }
                let parent = format!("{prefix}/{application}/{group}");
                let mut levels = model
                    .db_levels
                    .values()
                    .filter(|level| !level.netvar && level.parent == parent)
                    .map(|level| ExportLevel {
                        address: level.address,
                        name: level.tag.clone(),
                    })
                    .collect::<Vec<_>>();
                levels.sort_by_key(|level| level.address);
                exported_objects += 1 + levels.len();
                groups.push(ExportGroup {
                    address: group,
                    name: group_name,
                    levels,
                });
            }
            applications.push(ExportApplication {
                address: application,
                application_type: export_type(application),
                name,
                groups,
            });
        }
        networks.push(ExportNetwork {
            address: network_address,
            name: project.networks[&network_address].name.clone(),
            route,
            applications,
        });
    }

    let document = ExportRoot {
        cgl_version: "1.1",
        created_by: CREATED_BY,
        created_time: created_time(),
        local_network: local,
        networks,
    };
    let document = match serde_json::to_string(&document) {
        Ok(document) => document,
        Err(error) => return err(tag, 500, &format!("500 CGL serialization failed: {error}")),
    };
    Response {
        tag: tag.to_string(),
        lines: vec![
            "343-Begin CGL snippet".to_string(),
            format!("347-{document}"),
        ],
        final_text: format!("344 End CGL snippet [numberOfExportedObjects:{exported_objects}]"),
        status: 344,
    }
}

/// A CGL document after Jackson-compatible binding. `None` is a JSON null.
struct Root {
    version: Option<String>,
    local_network: Option<i64>,
    networks: Option<Vec<Option<Network>>>,
}

struct Network {
    address: i64,
    name: Option<String>,
    route: Option<Vec<Option<i64>>>,
    applications: Option<Vec<Option<Application>>>,
}

struct Application {
    address: i64,
    name: Option<String>,
    groups: Option<Vec<Option<Group>>>,
}

struct Group {
    address: i64,
    name: Option<String>,
    levels: Option<Vec<Option<Level>>>,
}

struct Level {
    address: i64,
    name: Option<String>,
}

fn fields<'a>(
    value: &'a Value,
    class: &str,
    known: &[&str],
) -> Result<Option<&'a Map<String, Value>>, String> {
    match value {
        Value::Null => Ok(None),
        Value::Object(object) => {
            if let Some(unknown) = object.keys().find(|key| !known.contains(&key.as_str())) {
                return Err(format!(
                    "Unrecognized field \"{unknown}\" (class {class}), not marked as ignorable"
                ));
            }
            Ok(Some(object))
        }
        _ => Err(format!(
            "Cannot deserialize {class} from a non-object value"
        )),
    }
}

/// Jackson `Integer`: numbers truncate, numeric text parses, null stays null.
fn integer(value: Option<&Value>, field: &str) -> Result<Option<i64>, String> {
    let invalid = || format!("Cannot deserialize value of type `int` for \"{field}\"");
    match value {
        None | Some(Value::Null) => Ok(None),
        Some(Value::Number(number)) => {
            let value = number
                .as_i64()
                .or_else(|| number.as_f64().map(|value| value.trunc() as i64))
                .ok_or_else(invalid)?;
            i32::try_from(value).map_err(|_| invalid())?;
            Ok(Some(value))
        }
        Some(Value::String(text)) => {
            let text = text.trim();
            if text.is_empty() {
                return Ok(None);
            }
            let value = text.parse::<i32>().map_err(|_| invalid())?;
            Ok(Some(i64::from(value)))
        }
        Some(_) => Err(invalid()),
    }
}

/// Jackson `String`: scalars coerce to their text.
fn text(value: Option<&Value>, field: &str) -> Result<Option<String>, String> {
    match value {
        None | Some(Value::Null) => Ok(None),
        Some(Value::String(text)) => Ok(Some(text.clone())),
        Some(Value::Number(number)) => Ok(Some(number.to_string())),
        Some(Value::Bool(value)) => Ok(Some(value.to_string())),
        Some(_) => Err(format!(
            "Cannot deserialize value of type `java.lang.String` for \"{field}\""
        )),
    }
}

/// Jackson `java.util.Date`: epoch milliseconds or one of its standard forms.
fn date(value: Option<&Value>) -> Result<(), String> {
    let text = match value {
        None | Some(Value::Null) | Some(Value::Number(_)) => return Ok(()),
        Some(Value::String(text)) => text,
        Some(_) => return Err("Cannot deserialize value of type `java.util.Date`".to_string()),
    };
    let accepted = DateTime::parse_from_rfc3339(text).is_ok()
        || DateTime::parse_from_str(text, "%Y-%m-%dT%H:%M:%S%.f%z").is_ok()
        || NaiveDateTime::parse_from_str(text, "%Y-%m-%dT%H:%M:%S%.f").is_ok()
        || NaiveDate::parse_from_str(text, "%Y-%m-%d").is_ok()
        || DateTime::parse_from_rfc2822(text).is_ok()
        || text.parse::<i64>().is_ok();
    if accepted {
        Ok(())
    } else {
        Err(format!(
            "Cannot deserialize value of type `java.util.Date` from String \"{text}\""
        ))
    }
}

fn list<T>(
    value: Option<&Value>,
    field: &str,
    mut item: impl FnMut(&Value) -> Result<T, String>,
) -> Result<Option<Vec<T>>, String> {
    match value {
        None => Ok(Some(Vec::new())),
        Some(Value::Null) => Ok(None),
        Some(Value::Array(values)) => values
            .iter()
            .map(&mut item)
            .collect::<Result<_, _>>()
            .map(Some),
        Some(_) => Err(format!(
            "Cannot deserialize value of type `java.util.ArrayList` for \"{field}\""
        )),
    }
}

fn level(value: &Value) -> Result<Option<Level>, String> {
    let Some(object) = fields(
        value,
        "com.clipsal.cgate.cgl.model.Level",
        &["address", "name"],
    )?
    else {
        return Ok(None);
    };
    Ok(Some(Level {
        address: integer(object.get("address"), "address")?.unwrap_or(0),
        name: text(object.get("name"), "name")?,
    }))
}

fn group(value: &Value) -> Result<Option<Group>, String> {
    let Some(object) = fields(
        value,
        "com.clipsal.cgate.cgl.model.Group",
        &["address", "name", "levels"],
    )?
    else {
        return Ok(None);
    };
    Ok(Some(Group {
        address: integer(object.get("address"), "address")?.unwrap_or(0),
        name: text(object.get("name"), "name")?,
        levels: list(object.get("levels"), "levels", level)?,
    }))
}

fn application(value: &Value) -> Result<Option<Application>, String> {
    let Some(object) = fields(
        value,
        "com.clipsal.cgate.cgl.model.Application",
        &["address", "type", "name", "groups"],
    )?
    else {
        return Ok(None);
    };
    // Native binds `type` but never imports it.
    integer(object.get("type"), "type")?;
    Ok(Some(Application {
        address: integer(object.get("address"), "address")?.unwrap_or(0),
        name: text(object.get("name"), "name")?,
        groups: list(object.get("groups"), "groups", group)?,
    }))
}

fn network(value: &Value) -> Result<Option<Network>, String> {
    let Some(object) = fields(
        value,
        "com.clipsal.cgate.cgl.model.Network",
        &["address", "name", "route", "applications"],
    )?
    else {
        return Ok(None);
    };
    Ok(Some(Network {
        address: integer(object.get("address"), "address")?.unwrap_or(0),
        name: text(object.get("name"), "name")?,
        route: list(object.get("route"), "route", |value| {
            integer(Some(value), "route")
        })?,
        applications: list(object.get("applications"), "applications", application)?,
    }))
}

/// Bind one document the way native Jackson does: the first JSON value is
/// read (trailing text is ignored), duplicate keys keep their last value and
/// unknown properties fail.
fn parse(document: &str) -> Result<Root, String> {
    let value = serde_json::Deserializer::from_str(document)
        .into_iter::<Value>()
        .next()
        .ok_or_else(|| "No content to map due to end-of-input".to_string())?
        .map_err(|error| format!("JSON parse error: {error}"))?;
    let Some(object) = fields(
        &value,
        "com.clipsal.cgate.cgl.model.Root",
        &[
            "cglVersion",
            "createdBy",
            "createdTime",
            "localNetwork",
            "networks",
        ],
    )?
    else {
        return Err("Cannot deserialize Root from a null value".to_string());
    };
    text(object.get("createdBy"), "createdBy")?;
    date(object.get("createdTime"))?;
    Ok(Root {
        version: text(object.get("cglVersion"), "cglVersion")?,
        local_network: integer(object.get("localNetwork"), "localNetwork")?,
        networks: list(object.get("networks"), "networks", network)?,
    })
}

fn display(name: &Option<String>) -> &str {
    name.as_deref().unwrap_or("null")
}

/// Why an import stopped after it started changing the label graph.
enum Stop {
    /// Native 408 text after `Exception: `; earlier changes are kept.
    Failed(String),
    /// The import would create a nameless tag object.
    Nameless,
}

fn null() -> Stop {
    Stop::Failed(NPE.to_string())
}

fn check_address(address: i64, kind: &str, name: &Option<String>) -> Result<u8, Stop> {
    u8::try_from(address).map_err(|_| {
        Stop::Failed(format!(
            "com.clipsal.cgate.cgl.CglException: Invalid address {address} for {kind} '{}'.",
            display(name)
        ))
    })
}

struct Outcome {
    lines: Vec<String>,
    skipped: usize,
}

fn apply(model: &mut Server, project_name: &str, root: &Root) -> Result<Outcome, Stop> {
    let local = root.local_network.ok_or_else(null)?;
    let project = model.projects[project_name].clone();
    let routable = routable(&project, local);
    let networks = root.networks.as_ref().ok_or_else(null)?;
    let mut lines = vec![format!(
        "Importing routable networks from local Network {local} ..."
    )];
    let (mut applications, mut groups, mut levels, mut skipped) = (0usize, 0usize, 0usize, 0usize);
    for network in networks {
        let network = network.as_ref().ok_or_else(null)?;
        let network_address = check_address(network.address, "network", &network.name)?;
        if !project.networks.contains_key(&network_address) {
            skipped += 1;
            lines.push(format!(
                "SKIPPED - Network {network_address} does not exist. Please create it and try the import again."
            ));
            continue;
        }
        if !routable.contains(&network.address) {
            skipped += 1;
            let route = network.route.as_ref().ok_or_else(null)?;
            let mut path = local.to_string();
            for step in route {
                path.push_str(" - ");
                path.push_str(&step.map_or_else(|| "null".to_string(), |step| step.to_string()));
            }
            lines.push(format!(
                "SKIPPED - Network {network_address} is not routable to the local network ({local})"
            ));
            lines.push(format!(
                "        - Please create network {network_address} and try the import again with this route: "
            ));
            lines.push(format!("          {path}"));
            continue;
        }
        lines.push(format!("Importing Network {network_address}"));
        for application in network.applications.as_ref().ok_or_else(null)? {
            let application = application.as_ref().ok_or_else(null)?;
            let application_address =
                check_address(application.address, "application", &application.name)?;
            let application_path =
                format!("//{project_name}/{network_address}/{application_address}");
            let mut created = model.cgl_runtime.insert(application_path.clone());
            let key = format!("{application_path}/TagName");
            let durable_created = if let std::collections::hash_map::Entry::Vacant(entry) =
                model.db_fields.entry(key)
            {
                entry.insert(application.name.clone().ok_or(Stop::Nameless)?);
                true
            } else {
                false
            };
            if durable_created {
                // Runtime objects can be announced again after LOAD. Only a
                // first durable label creation belongs in this history.
                model.record_application_created(
                    project_name,
                    network_address,
                    application_address,
                );
                created = true;
            }
            if created {
                applications += 1;
                lines.push(format!(
                    "  Created new application {network_address}/{application_address} ('{}')",
                    display(&application.name)
                ));
            }
            for group in application.groups.as_ref().ok_or_else(null)? {
                let group = group.as_ref().ok_or_else(null)?;
                let group_address = check_address(group.address, "group", &group.name)?;
                let group_path = format!("{application_path}/{group_address}");
                let mut created = model.cgl_runtime.insert(group_path.clone());
                let key = format!("{group_path}/TagName");
                if let std::collections::hash_map::Entry::Vacant(entry) = model.db_fields.entry(key)
                {
                    entry.insert(group.name.clone().ok_or(Stop::Nameless)?);
                    created = true;
                }
                if created {
                    groups += 1;
                    lines.push(format!(
                        "    Created new group {network_address}/{application_address}/{group_address} ('{}')",
                        display(&group.name)
                    ));
                }
                for level in group.levels.as_ref().ok_or_else(null)? {
                    let level = level.as_ref().ok_or_else(null)?;
                    let level_address = check_address(level.address, "level", &level.name)?;
                    let exists = model.db_levels.values().any(|candidate| {
                        !candidate.netvar
                            && candidate.parent == group_path
                            && candidate.address == level_address
                    });
                    if exists {
                        continue;
                    }
                    let name = level.name.clone().ok_or(Stop::Nameless)?;
                    let oid = loop {
                        let candidate = fresh_oid();
                        if !model.known_oids.contains(&candidate)
                            && !model.db_levels.contains_key(&candidate)
                        {
                            break candidate;
                        }
                    };
                    model.known_oids.insert(oid.clone());
                    model.objects.insert(format!("!{oid}"));
                    model.db_levels.insert(
                        oid.clone(),
                        DbLevel {
                            oid,
                            parent: group_path.clone(),
                            address: level_address,
                            tag: name.clone(),
                            value: Some(level_address),
                            raw_value: None,
                            netvar: false,
                        },
                    );
                    levels += 1;
                    lines.push(format!(
                        "      Created new level {network_address}/{application_address}/{group_address}/{level_address} ('{name}')"
                    ));
                }
            }
        }
    }
    lines.push(format!(
        "Imported {} object(s) of {} network(s): {applications} application(s), {groups} group(s), {levels} level(s) ",
        applications + groups + levels,
        networks.len()
    ));
    Ok(Outcome { lines, skipped })
}

/// `CGL IMPORT project` without a here-document.
pub(crate) fn import_without_document(model: &Server, tag: &str, words: &[&str]) -> Response {
    match words.get(2) {
        None => err(
            tag,
            401,
            "401 Bad object or device ID: No project specified",
        ),
        Some(name) if !model.projects.contains_key(*name) => {
            err(tag, 401, "401 Bad object or device ID: Project not found")
        }
        Some(_) => err(tag, 400, "400 Syntax Error: No CGL data supplied"),
    }
}

/// Import a CGL 1.1 label graph into known routable project networks.
///
/// Missing tag objects are created with the document name; existing names
/// are preserved. A 408 after the import started keeps earlier changes, as
/// native C-Gate does; callers must commit the returned model state.
pub(crate) fn import(model: &mut Server, tag: &str, words: &[&str], document: &str) -> Response {
    let Some(project_name) = words.get(2).copied() else {
        return err(
            tag,
            401,
            "401 Bad object or device ID: No project specified",
        );
    };
    if !model.projects.contains_key(project_name) {
        return err(tag, 401, "401 Bad object or device ID: Project not found");
    }
    let root = match parse(document) {
        Ok(root) => root,
        Err(error) => return err(tag, 400, &format!("{PARSE_FAILED}{error}")),
    };
    match root.version.as_deref() {
        None => return err(tag, 400, &format!("{VALIDATION_FAILED}{NPE}")),
        Some("1.1") => {}
        Some(_) => {
            return err(
                tag,
                400,
                &format!(
                "{VALIDATION_FAILED}java.lang.IllegalArgumentException: Unsupported CGL version."
            ),
            )
        }
    }
    let mut trial = model.clone();
    let outcome = apply(&mut trial, project_name, &root);
    let outcome = match outcome {
        Err(Stop::Nameless) => {
            return err(
                tag,
                408,
                "408 Operation failed: CGL import failed: a new application, group or level needs a name",
            )
        }
        Err(Stop::Failed(exception)) => {
            *model = trial;
            return err(tag, 408, &format!("{IMPORT_FAILED}{exception}"));
        }
        Ok(outcome) => {
            *model = trial;
            outcome
        }
    };
    let lines = outcome
        .lines
        .into_iter()
        .map(|line| format!("380-{line}"))
        .collect::<Vec<_>>();
    if outcome.skipped == 0 {
        return Response {
            tag: tag.to_string(),
            lines,
            final_text: "200 OK.".to_string(),
            status: 200,
        };
    }
    let final_text = format!(
        "380 CGL import not completed: Skipped {} network(s). ",
        outcome.skipped
    );
    Response {
        tag: tag.to_string(),
        lines,
        final_text,
        status: 380,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::AccessLevel;

    /// Everything except the deliberate nameless refusal matches the native
    /// transcript on the cgate-mock model.
    #[test]
    fn cgate_mock_replays_native_cgl_capture() {
        let mut server = Server::new(AccessLevel::Program);
        let mut failures = Vec::new();
        for (index, step) in replay::steps().into_iter().enumerate() {
            let line = format!("[{index}] {}", step.command);
            let response = match &step.document {
                Some(document) => server.handle_document(&line, document),
                None => server.handle(&line),
            };
            if step.scenario == "nameless" {
                continue;
            }
            if let Err(error) = replay::check(&step, &response) {
                failures.push(format!("{} / {}: {error}", step.scenario, step.command));
            }
        }
        assert!(failures.is_empty(), "{}", failures.join("\n"));
        // The 408 level failure kept the application and group before it.
        assert_eq!(server.db_fields["//CGLP/254/255/TagName"], "A255");
        assert_eq!(server.db_fields["//CGLP/254/255/255/TagName"], "G255");
    }

    #[test]
    fn export_types_keep_retained_special_applications() {
        for retained in [
            25, 172, 173, 192, 202, 203, 205, 206, 208, 213, 223, 224, 228, 251,
        ] {
            assert_eq!(export_type(retained), retained);
        }
        for mapped in [0, 38, 56, 115, 116, 136, 254] {
            assert_eq!(export_type(mapped), 56);
        }
    }

    #[test]
    fn bridge_types_are_case_sensitive_prefix_or_gate_substring() {
        assert!(is_bridge_type("BRIDGE"));
        assert!(is_bridge_type("BRIDGEX"));
        assert!(is_bridge_type("PCGATEWAY"));
        assert!(!is_bridge_type("bridge"));
        assert!(!is_bridge_type("XBRIDGE"));
        assert!(!is_bridge_type("RELDN12"));
    }

    #[test]
    fn jackson_binding_coerces_scalars_and_rejects_unknown_fields() {
        let root = parse(
            r#"{"cglVersion":1.1,"localNetwork":"254","localNetwork":253,"networks":[{"address":7.9,"route":[null,"3"],"applications":[{"address":null,"type":"56","name":true}]}]} trailing"#,
        )
        .expect("coerced document");
        assert_eq!(root.version.as_deref(), Some("1.1"));
        assert_eq!(root.local_network, Some(253));
        let network = root.networks.unwrap().remove(0).unwrap();
        assert_eq!(network.address, 7);
        assert_eq!(network.route.unwrap(), vec![None, Some(3)]);
        let application = network.applications.unwrap().remove(0).unwrap();
        assert_eq!(
            (application.address, application.name.as_deref()),
            (0, Some("true"))
        );
        for bad in [
            "",
            "[]",
            "not json",
            r#"{"cglVersion":"1.1","bogus":1}"#,
            r#"{"networks":[{"address":true}]}"#,
            r#"{"networks":[{"route":"x"}]}"#,
            r#"{"createdTime":"yesterday"}"#,
            r#"{"networks":[{"applications":[{"type":"lighting"}]}]}"#,
        ] {
            assert!(parse(bad).is_err(), "{bad}");
        }
        for good in [
            r#"{"createdTime":"2020-01-02T03:04:05.678+00:00"}"#,
            r#"{"createdTime":"2020-01-02T03:04:05Z"}"#,
            r#"{"createdTime":"2020-01-02T03:04:05"}"#,
            r#"{"createdTime":"2020-01-02"}"#,
            r#"{"createdTime":1600000000000,"createdBy":5}"#,
        ] {
            assert!(parse(good).is_ok(), "{good}");
        }
    }
}

/// Replay of the owned native capture in
/// `testdata/fixtures/native_cgate_cgl_routes.json`, shared by the cgate-mock
/// model and cmqttd service tests.
#[cfg(test)]
pub(crate) mod replay {
    use serde_json::Value;

    use crate::Response;

    pub(crate) const FIXTURE: &str =
        include_str!("../../../testdata/fixtures/native_cgate_cgl_routes.json");
    const SIMULATOR: &str = "127.0.0.2:29999";

    /// One native step to send: command, optional here-document and the
    /// fixture entry to compare against.
    pub(crate) struct Step {
        pub(crate) scenario: String,
        pub(crate) command: String,
        pub(crate) document: Option<String>,
        pub(crate) expected: Value,
    }

    /// The generator named by the committed large-import step.
    fn large_document(generator: &Value) -> String {
        let groups = (0..generator["groups"].as_u64().unwrap())
            .map(|group| {
                let levels = (0..generator["levels_per_group"].as_u64().unwrap())
                    .map(|level| serde_json::json!({"address": level, "name": format!("L{level}")}))
                    .collect::<Vec<_>>();
                serde_json::json!({"address": group, "name": format!("G{group}"), "levels": levels})
            })
            .collect::<Vec<_>>();
        serde_json::json!({"cglVersion": "1.1", "localNetwork": generator["localNetwork"],
            "networks": [{"address": generator["network"], "applications": [
                {"address": generator["application"], "name": "Large", "groups": groups}]}]})
        .to_string()
    }

    /// Every replayable step in capture order. Opening and closing the
    /// simulated PCI network is native-only setup: CGL never touches it.
    pub(crate) fn steps() -> Vec<Step> {
        let fixture: Value = serde_json::from_str(FIXTURE).unwrap();
        let mut steps = Vec::new();
        for scenario in fixture["scenarios"].as_array().unwrap() {
            for step in scenario["steps"].as_array().unwrap() {
                let command = step["command"].as_str().unwrap();
                if command.starts_with("NET OPEN") || command.starts_with("NET CLOSE") {
                    continue;
                }
                let document = step["document"]
                    .as_str()
                    .map(str::to_string)
                    .or_else(|| step.get("document_generator").map(large_document));
                steps.push(Step {
                    scenario: scenario["name"].as_str().unwrap().to_string(),
                    command: command.replace("<simulator>", SIMULATOR),
                    document,
                    expected: step.clone(),
                });
            }
        }
        steps
    }

    fn normalize(line: &str) -> String {
        let mut output = String::new();
        let bytes = line.as_bytes();
        let mut index = 0;
        while index < line.len() {
            let candidate = &bytes[index..(index + 36).min(bytes.len())];
            let uuid = candidate.len() == 36
                && candidate.iter().enumerate().all(|(position, byte)| {
                    if matches!(position, 8 | 13 | 18 | 23) {
                        *byte == b'-'
                    } else {
                        byte.is_ascii_hexdigit()
                    }
                });
            if uuid {
                output.push_str("<oid>");
                index += 36;
            } else {
                let character = line[index..].chars().next().unwrap();
                output.push(character);
                index += character.len_utf8();
            }
        }
        output
    }

    /// Export JSON with generated metadata masked. Application order is
    /// compared exactly; only the remaining Group/Level order disposition
    /// is canonicalized.
    fn canonical_export(line: &str) -> Value {
        let mut document: Value = serde_json::from_str(&line[4..]).unwrap();
        document["createdBy"] = Value::from("<creator>");
        document["createdTime"] = Value::from("<timestamp>");
        fn sort(items: &mut Value, child: &[&str]) {
            let Some(array) = items.as_array_mut() else {
                return;
            };
            array.sort_by_key(|item| item["address"].as_u64());
            for item in array {
                if let Some((first, rest)) = child.split_first() {
                    if let Some(children) = item.get_mut(*first) {
                        sort(children, rest);
                    }
                }
            }
        }
        for network in document["networks"].as_array_mut().unwrap() {
            if let Some(applications) = network
                .get_mut("applications")
                .and_then(Value::as_array_mut)
            {
                for application in applications {
                    if let Some(groups) = application.get_mut("groups") {
                        sort(groups, &["levels"]);
                    }
                }
            }
        }
        document
    }

    fn lines(response: &Response) -> Vec<String> {
        response
            .lines
            .iter()
            .chain(std::iter::once(&response.final_text))
            .map(|line| normalize(line))
            .collect()
    }

    /// Compare one reply with the native capture; `Err` explains the
    /// difference.
    pub(crate) fn check(step: &Step, response: &Response) -> Result<(), String> {
        let actual = lines(response);
        let expected = &step.expected;
        if expected.get("setup").is_some() {
            return if response.status < 400 {
                Ok(())
            } else {
                Err(format!("setup failed: {actual:?}"))
            };
        }
        if let Some(summary) = expected.get("reply_summary") {
            let last = actual.last().unwrap();
            if summary["lines"].as_u64() != Some(actual.len() as u64)
                || summary["last"].as_array().unwrap().last().unwrap().as_str()
                    != Some(&last[..last.len().min(160)])
            {
                return Err(format!(
                    "summary mismatch: {} lines, last {last}",
                    actual.len()
                ));
            }
            if step.command.starts_with("CGL IMPORT") {
                let digest = hex::encode(crate::auth::sha256(actual.join("\n").as_bytes()));
                if summary["sha256"].as_str() != Some(digest.as_str()) {
                    return Err("large import transcript digest differs".to_string());
                }
            }
            return Ok(());
        }
        if step.command.starts_with("DBGETXML") {
            // Application XML rendering belongs to the database model; the
            // replay tests check the partially imported tags directly.
            return Ok(());
        }
        let native = expected["reply"]
            .as_array()
            .unwrap()
            .iter()
            .map(|line| line.as_str().unwrap().to_string())
            .collect::<Vec<_>>();
        const PARSE: &str = "400 Syntax Error: CGL validation failed: Import Failed: ";
        if native.len() == 1 && native[0].starts_with(PARSE) {
            // Jackson exception detail is not reproduced.
            return if actual.len() == 1 && actual[0].starts_with(PARSE) {
                Ok(())
            } else {
                Err(format!("expected a binding failure, got {actual:?}"))
            };
        }
        if native.len() == 3 && native[1].starts_with("347-{\"cglVersion\"") {
            let same = actual.len() == 3
                && actual[0] == native[0]
                && actual[2] == native[2]
                && canonical_export(&actual[1]) == canonical_export(&native[1]);
            return if same {
                Ok(())
            } else {
                Err(format!(
                    "export differs:\n native {native:?}\n actual {actual:?}"
                ))
            };
        }
        if actual == native {
            Ok(())
        } else {
            Err(format!(
                "reply differs:\n native {native:?}\n actual {actual:?}"
            ))
        }
    }
}

#[cfg(test)]
#[path = "cgl_application_order_tests.rs"]
mod application_order_tests;
