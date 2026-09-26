//! Bounded CGL 1.1 exchange over cmqttd's durable database model.
//!
//! Native C-Gate's CGL document is JSON rather than an opaque archive.  This
//! module deliberately implements only the database-label subset cmqttd owns:
//! known project networks, applications, groups and levels.  It never opens a
//! host path, starts a network or claims automation-controller side effects.

use std::collections::{BTreeMap, BTreeSet};

use chrono::{Local, SecondsFormat};
use serde::{Deserialize, Serialize};

use crate::{err, fresh_oid, network_path, DbLevel, Response, Server};

const MAX_CGL_OBJECTS: usize = 10_000;

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct CglDocument {
    cgl_version: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    created_by: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    created_time: Option<String>,
    local_network: u8,
    networks: Vec<CglNetwork>,
}

#[derive(Debug, Deserialize, Serialize)]
struct CglNetwork {
    address: u8,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    name: Option<String>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    route: Vec<u8>,
    #[serde(default)]
    applications: Vec<CglApplication>,
}

#[derive(Debug, Deserialize, Serialize)]
struct CglApplication {
    address: u8,
    #[serde(default, skip_serializing_if = "Option::is_none", rename = "type")]
    application_type: Option<u8>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    name: Option<String>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    groups: Vec<CglGroup>,
}

#[derive(Debug, Deserialize, Serialize)]
struct CglGroup {
    address: u8,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    name: Option<String>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    levels: Vec<CglLevel>,
}

#[derive(Debug, Deserialize, Serialize)]
struct CglLevel {
    address: u8,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    name: Option<String>,
}

fn parse_selection(raw: Option<&str>) -> Result<Option<BTreeSet<u8>>, ()> {
    let Some(raw) = raw else {
        return Ok(None);
    };
    if raw == "*" {
        return Ok(None);
    }
    if raw.is_empty() {
        return Err(());
    }
    let mut values = BTreeSet::new();
    for value in raw.split(',') {
        if value.is_empty() || !values.insert(value.parse::<u8>().map_err(|_| ())?) {
            return Err(());
        }
    }
    Ok(Some(values))
}

fn selected(selection: &Option<BTreeSet<u8>>, address: u8) -> bool {
    selection
        .as_ref()
        .is_none_or(|selection| selection.contains(&address))
}

fn export_limit_error(tag: &str) -> Response {
    err(
        tag,
        408,
        &format!("408 Operation failed: CGL export exceeds the {MAX_CGL_OBJECTS}-object limit"),
    )
}

/// Export the modeled CGL 1.1 label graph with native 343/347/344 framing.
pub(crate) fn export(model: &Server, tag: &str, words: &[&str], local_network: u8) -> Response {
    if !(3..=5).contains(&words.len()) {
        return err(tag, 400, "400 Syntax Error.");
    }
    let project_name = words[2];
    let Some(project) = model.projects.get(project_name) else {
        return err(
            tag,
            401,
            &format!("401 Bad object or device ID: {project_name} (Object not found)"),
        );
    };
    let network_selection = match parse_selection(words.get(3).copied()) {
        Ok(selection) => selection,
        Err(()) => return err(tag, 400, "400 Syntax Error."),
    };
    let application_selection = match parse_selection(words.get(4).copied()) {
        Ok(selection) => selection,
        Err(()) => return err(tag, 400, "400 Syntax Error."),
    };

    let mut network_addresses = project.networks.keys().copied().collect::<Vec<_>>();
    network_addresses.sort_unstable();
    let mut exported_objects = 0usize;
    let mut networks = Vec::new();
    for network_address in network_addresses {
        if !selected(&network_selection, network_address) {
            continue;
        }
        let network = &project.networks[&network_address];
        let route = if network_address == local_network {
            Vec::new()
        } else if let Ok(route) = network_path(project, local_network, network_address) {
            route
        } else {
            // CGL is a routable-network exchange. Omitting a network with no
            // proven route is safer than emitting an invented empty route.
            continue;
        };
        let prefix = format!("//{project_name}/{network_address}");
        let mut application_names = BTreeMap::<u8, String>::new();
        let mut group_names = BTreeMap::<(u8, u8), String>::new();
        for (path, value) in &model.db_fields {
            let parts = path.trim_start_matches('/').split('/').collect::<Vec<_>>();
            match parts.as_slice() {
                [project, network, application, "TagName"]
                    if *project == project_name && network.parse::<u8>() == Ok(network_address) =>
                {
                    if let Ok(application) = application.parse::<u8>() {
                        application_names.insert(application, value.clone());
                    }
                }
                [project, network, application, group, "TagName"]
                    if *project == project_name && network.parse::<u8>() == Ok(network_address) =>
                {
                    if let (Ok(application), Ok(group)) =
                        (application.parse::<u8>(), group.parse::<u8>())
                    {
                        group_names.insert((application, group), value.clone());
                    }
                }
                _ => {}
            }
        }
        for level in model.db_levels.values().filter(|level| !level.netvar) {
            let parts = level
                .parent
                .trim_start_matches('/')
                .split('/')
                .collect::<Vec<_>>();
            if let [project, network, application, group] = parts.as_slice() {
                if *project == project_name && network.parse::<u8>() == Ok(network_address) {
                    if let (Ok(application), Ok(group)) =
                        (application.parse::<u8>(), group.parse::<u8>())
                    {
                        application_names
                            .entry(application)
                            .or_insert_with(|| application.to_string());
                        group_names
                            .entry((application, group))
                            .or_insert_with(|| group.to_string());
                    }
                }
            }
        }
        for (application, _) in group_names.keys() {
            application_names
                .entry(*application)
                .or_insert_with(|| application.to_string());
        }

        let mut applications = Vec::new();
        for (application, application_name) in application_names {
            if !selected(&application_selection, application) {
                continue;
            }
            let mut groups = Vec::new();
            for ((candidate_application, group), group_name) in &group_names {
                if *candidate_application != application {
                    continue;
                }
                let parent = format!("{prefix}/{application}/{group}");
                let mut levels = model
                    .db_levels
                    .values()
                    .filter(|level| !level.netvar && level.parent == parent)
                    .map(|level| CglLevel {
                        address: level.address,
                        name: Some(level.tag.clone()),
                    })
                    .take(MAX_CGL_OBJECTS + 1)
                    .collect::<Vec<_>>();
                levels.sort_by_key(|level| level.address);
                exported_objects = exported_objects
                    .saturating_add(levels.len())
                    .saturating_add(1);
                if exported_objects > MAX_CGL_OBJECTS {
                    return export_limit_error(tag);
                }
                groups.push(CglGroup {
                    address: *group,
                    name: Some(group_name.clone()),
                    levels,
                });
            }
            exported_objects = exported_objects.saturating_add(1);
            if exported_objects > MAX_CGL_OBJECTS {
                return export_limit_error(tag);
            }
            applications.push(CglApplication {
                address: application,
                application_type: Some(application),
                name: Some(application_name),
                groups,
            });
        }
        networks.push(CglNetwork {
            address: network_address,
            name: Some(network.name.clone()),
            route,
            applications,
        });
    }

    let document = CglDocument {
        cgl_version: "1.1".to_string(),
        created_by: Some("cmqttd".to_string()),
        created_time: Some(Local::now().to_rfc3339_opts(SecondsFormat::Millis, false)),
        local_network,
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

fn validate(document: &CglDocument) -> Result<(), String> {
    if document.cgl_version != "1.1" {
        return Err("Expected a CGL 1.1 document".to_string());
    }
    let mut count = 0usize;
    let mut networks = BTreeSet::new();
    for network in &document.networks {
        validate_name(network.name.as_deref())?;
        if !networks.insert(network.address) {
            return Err(format!("duplicate network address {}", network.address));
        }
        let mut applications = BTreeSet::new();
        for application in &network.applications {
            validate_name(application.name.as_deref())?;
            count += 1;
            if !applications.insert(application.address) {
                return Err(format!(
                    "duplicate application address {}",
                    application.address
                ));
            }
            let mut groups = BTreeSet::new();
            for group in &application.groups {
                validate_name(group.name.as_deref())?;
                count += 1;
                if !groups.insert(group.address) {
                    return Err(format!("duplicate group address {}", group.address));
                }
                let mut levels = BTreeSet::new();
                for level in &group.levels {
                    validate_name(level.name.as_deref())?;
                    count += 1;
                    if !levels.insert(level.address) {
                        return Err(format!("duplicate level address {}", level.address));
                    }
                }
            }
        }
    }
    if count > MAX_CGL_OBJECTS {
        return Err(format!(
            "CGL document exceeds the {MAX_CGL_OBJECTS}-object limit"
        ));
    }
    Ok(())
}

fn validate_name(name: Option<&str>) -> Result<(), String> {
    if name.is_some_and(|name| {
        name.len() > 4096 || name.chars().any(|character| character.is_control())
    }) {
        Err("names must be bounded text without control characters".to_string())
    } else {
        Ok(())
    }
}

fn importable_network(
    model: &Server,
    project_name: &str,
    document: &CglDocument,
    network: &CglNetwork,
) -> bool {
    let Some(project) = model.projects.get(project_name) else {
        return false;
    };
    if !project.networks.contains_key(&network.address) {
        return false;
    }
    let expected = if network.address == document.local_network {
        Vec::new()
    } else {
        let Ok(route) = network_path(project, document.local_network, network.address) else {
            return false;
        };
        route
    };
    network.route.is_empty() || network.route == expected
}

/// Import a validated CGL 1.1 document into known local database objects.
/// Existing tag names are intentionally preserved, matching native C-Gate.
pub(crate) fn import(model: &mut Server, tag: &str, words: &[&str], document: &str) -> Response {
    if words.len() != 3 {
        return err(tag, 400, "400 Syntax Error.");
    }
    let project_name = words[2];
    if !model.projects.contains_key(project_name) {
        return err(tag, 401, "401 Bad object or device ID: Project not found");
    }
    let document: CglDocument = match serde_json::from_str(document) {
        Ok(document) => document,
        Err(error) => return err(tag, 400, &format!("400 Invalid CGL: {error}")),
    };
    if let Err(error) = validate(&document) {
        return err(tag, 400, &format!("400 Invalid CGL: {error}"));
    }

    let mut lines = vec![format!(
        "380-Importing routable networks from local Network {} ...",
        document.local_network
    )];
    let mut applications = 0usize;
    let mut groups = 0usize;
    let mut levels = 0usize;
    let mut skipped = 0usize;

    for network in &document.networks {
        if !importable_network(model, project_name, &document, network) {
            skipped += 1;
            lines.push(format!(
                "380-SKIPPED - Network {} does not exist or is not routable. Please create it and try the import again.",
                network.address
            ));
            continue;
        }
        lines.push(format!("380-Importing Network {}", network.address));
        for application in &network.applications {
            let application_path = format!(
                "//{project_name}/{}/{}",
                network.address, application.address
            );
            if let std::collections::hash_map::Entry::Vacant(entry) =
                model.db_fields.entry(format!("{application_path}/TagName"))
            {
                let name = application
                    .name
                    .clone()
                    .unwrap_or_else(|| application.address.to_string());
                entry.insert(name.clone());
                applications += 1;
                lines.push(format!(
                    "380-  Created new application {}/{} ('{name}')",
                    network.address, application.address
                ));
            }
            for group in &application.groups {
                let group_path = format!("{application_path}/{}", group.address);
                if let std::collections::hash_map::Entry::Vacant(entry) =
                    model.db_fields.entry(format!("{group_path}/TagName"))
                {
                    let name = group
                        .name
                        .clone()
                        .unwrap_or_else(|| group.address.to_string());
                    entry.insert(name.clone());
                    groups += 1;
                    lines.push(format!(
                        "380-    Created new group {}/{}/{} ('{name}')",
                        network.address, application.address, group.address
                    ));
                }
                for level in &group.levels {
                    let exists = model.db_levels.values().any(|candidate| {
                        !candidate.netvar
                            && candidate.parent == group_path
                            && candidate.address == level.address
                    });
                    if exists {
                        continue;
                    }
                    let name = level
                        .name
                        .clone()
                        .unwrap_or_else(|| level.address.to_string());
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
                            address: level.address,
                            tag: name.clone(),
                            value: None,
                            netvar: false,
                        },
                    );
                    levels += 1;
                    lines.push(format!(
                        "380-      Created new level {}/{}/{}/{} ('{name}')",
                        network.address, application.address, group.address, level.address
                    ));
                }
            }
        }
    }
    let objects = applications + groups + levels;
    lines.push(format!(
        "380-Imported {objects} object(s) of {} network(s): {applications} application(s), {groups} group(s), {levels} level(s) ",
        document.networks.len()
    ));
    if skipped == 0 {
        Response {
            tag: tag.to_string(),
            lines,
            final_text: "200 OK.".to_string(),
            status: 200,
        }
    } else {
        Response {
            tag: tag.to_string(),
            lines,
            final_text: format!("380 CGL import not completed: Skipped {skipped} network(s). "),
            status: 380,
        }
    }
}
