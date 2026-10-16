//! One staged owner for an addressable Application's SAFE identity fields.
//!
//! Retained target HELP* documents decimal-byte/sibling uniqueness rules.
//! Exact Address mutation/error envelopes, same-value and lexical/case policy
//! still lack a target mutation capture; the corresponding tests are owned
//! regressions, not an original-server oracle.

use crate::{err, ok, status, DbXmlKind, DbXmlTarget, Response, Server};
use std::collections::HashSet;

#[cfg(test)]
#[path = "application_set_tests.rs"]
mod tests;

impl Server {
    /// Return None only when another established object/field owner applies.
    pub(crate) fn try_set_application_safe(
        &mut self,
        tag: &str,
        words: &[&str],
    ) -> Option<Response> {
        let (raw, field) = words.get(1)?.rsplit_once('/')?;
        if !matches!(field, "Address" | "TagName") {
            return None;
        }
        // Keep the captured Unit/cross-kind winning-OID resolver in dbset.
        if raw.strip_prefix('!').is_some_and(|oid| {
            self.duplicated_unit_oid_in_current_project(oid)
                || self.unique_unit_path_by_oid(oid).is_some()
        }) {
            return None;
        }
        let numeric = if raw.starts_with('!') {
            false
        } else {
            let parts = raw.trim_matches('/').split('/').collect::<Vec<_>>();
            (raw.starts_with("//") && parts.len() == 3)
                || (!raw.starts_with("//") && parts.len() == 2)
        };
        if !numeric {
            let project = self.current.as_deref()?;
            let object = self.pending_object(project, raw.strip_prefix('!')?)?;
            if object.element != "Application" {
                return None;
            }
        }
        let target = match self.resolve_db_xml_target(raw) {
            Ok(target) if target.kind == DbXmlKind::Application => target,
            Ok(_) => return None,
            Err((code, reason)) => return Some(err(tag, code, &format!("{code} {reason}"))),
        };
        let value = words.get(2..).unwrap_or_default().join(" ");
        if field == "Address" && self.duplicated_application_oid(&target.project, &target.oid) {
            return Some(err(
                tag,
                409,
                "409 Unsupported duplicate Application Address mutation",
            ));
        }
        let result = if field == "Address" {
            if value.is_empty() || !value.bytes().all(|byte| byte.is_ascii_digit()) {
                return Some(err(
                    tag,
                    408,
                    "408 Operation failed: Application Address must contain decimal digits only",
                ));
            }
            match value.parse::<u8>() {
                Ok(destination) => self.readdress_application(&target, destination, &value),
                Err(_) => Err("Application Address must be in 0..255".to_string()),
            }
        } else {
            if value.trim().is_empty() {
                return Some(err(
                    tag,
                    401,
                    "401 Bad object or device ID: TagName can't be null or blank",
                ));
            }
            if value.contains('#') {
                return Some(err(tag, status::BAD_REQUEST, "400 Invalid field value"));
            }
            self.rename_application_safe(&target, &value)
        };
        Some(match result {
            // Keep the existing ordinary SAFE successful envelope. Captured
            // shared-OID routing wraps it as 200 OK. in the existing owner.
            Ok(()) => ok(tag, vec![], "200 OK"),
            Err(reason) => err(tag, 408, &format!("408 Operation failed: {reason}")),
        })
    }

    /// Verify that the addressed graph has one complete, coherent owner.
    /// Opaque Level values are preserved; no byte coercion/re-admission occurs.
    fn validate_application_move(&self, target: &DbXmlTarget) -> Result<(), String> {
        let Some((project, network, source)) = Self::application_path_parts(&target.path) else {
            return Err("Application path is not canonical".to_string());
        };
        if self.current.as_deref() != Some(project)
            || target.project != project
            || !self
                .projects
                .get(project)
                .is_some_and(|p| p.networks.contains_key(&network))
        {
            return Err("Application project/network owner is not selected".to_string());
        }
        if self.duplicated_application_oid(project, &target.oid) {
            return Err("Ambiguous Application identity".to_string());
        }
        let prefix = format!("{}/", target.path);
        let mut owned = HashSet::from([target.oid.clone()]);
        loop {
            let before = owned.len();
            for object in self
                .db_pending
                .values()
                .filter(|object| object.project == project)
            {
                if object
                    .path
                    .as_deref()
                    .is_some_and(|path| path == target.path || path.starts_with(&prefix))
                    || object.parent == target.path
                    || object.parent.starts_with(&prefix)
                    || object
                        .parent
                        .strip_prefix('!')
                        .is_some_and(|oid| owned.contains(oid))
                {
                    owned.insert(object.oid.clone());
                }
            }
            if before == owned.len() {
                break;
            }
        }
        let mut paths = HashSet::new();
        for object in self
            .db_pending
            .values()
            .filter(|object| object.project == project && owned.contains(&object.oid))
        {
            let path = object
                .path
                .as_deref()
                .ok_or("Incomplete Application descendant")?;
            if !paths.insert(path) || !(path == target.path || path.starts_with(&prefix)) {
                return Err("Application descendant identity is ambiguous".to_string());
            }
            if self
                .db_pending
                .values()
                .filter(|other| other.project == project && other.oid == object.oid)
                .count()
                != 1
                || self.projects[project].networks.values().any(|n| {
                    n.oid == object.oid
                        || n.interface_oid == object.oid
                        || n.units.values().any(|u| u.oid == object.oid)
                })
            {
                return Err("Application descendant OID has a competing owner".to_string());
            }
            let (parent, address) = path.rsplit_once('/').ok_or("Invalid descendant path")?;
            let address = address
                .parse::<u8>()
                .map_err(|_| "Invalid descendant Address")?;
            let actual_parent = if let Some(oid) = object.parent.strip_prefix('!') {
                self.pending_object(project, oid)
                    .and_then(|owner| owner.path.clone())
                    .or_else(|| {
                        self.projects[project]
                            .networks
                            .values()
                            .find(|owner| owner.oid == oid)
                            .map(|owner| format!("//{project}/{}", owner.address))
                    })
            } else {
                Some(object.parent.clone())
            };
            if actual_parent.as_deref() != Some(parent)
                || object
                    .fields
                    .get("Address")
                    .and_then(|value| value.parse::<u8>().ok())
                    != Some(address)
                || !object.fields.contains_key("TagName")
            {
                return Err(
                    "Application descendant fields disagree with its path/parent".to_string(),
                );
            }
            if path == target.path
                && (address != source
                    || object.oid != target.oid
                    || object.element != "Application")
            {
                return Err("Application identity disagrees with its selected path".to_string());
            }
        }
        if !paths.contains(target.path.as_str()) {
            return Err("Typed Application identity is unavailable".to_string());
        }
        let mut level_paths = HashSet::new();
        for level in self
            .db_levels
            .values()
            .filter(|level| level.parent == target.path || level.parent.starts_with(&prefix))
        {
            let path = format!("{}/{}", level.parent, level.address);
            if !level_paths.insert(path.clone()) {
                return Err("Application Level address has competing owners".to_string());
            }
            if let Some(mirror) = self.pending_object(project, &level.oid) {
                if mirror.path.as_deref() != Some(path.as_str())
                    || mirror.element != if level.netvar { "NetVar" } else { "Level" }
                    || mirror.fields.get("TagName").map(String::as_str) != Some(level.tag.as_str())
                    || mirror
                        .fields
                        .get("Value")
                        .filter(|value| !value.is_empty())
                        .map(String::as_str)
                        != level.effective_value().as_deref()
                {
                    return Err("Application Level mirror disagrees with its owner".to_string());
                }
            }
            if self.db_levels.values().any(|other| {
                other.oid == level.oid
                    && (other.parent != level.parent || other.address != level.address)
            }) {
                return Err("Application Level OID has a competing owner".to_string());
            }
        }
        Ok(())
    }

    /// SAFE Application move; raw setters retain their existing admission.
    /// Preserve the input Address lexeme, while its canonical path is decimal.
    pub(crate) fn readdress_application(
        &mut self,
        target: &DbXmlTarget,
        destination: u8,
        value: &str,
    ) -> Result<(), String> {
        self.validate_application_move(target)?;
        let (project, network, source) =
            Self::application_path_parts(&target.path).ok_or("Invalid Application path")?;
        if destination == source {
            return Ok(());
        }
        let destination_path = format!("//{project}/{network}/{destination}");
        let destination_prefix = format!("{destination_path}/");
        let network_oid_parent = format!("!{}", self.projects[project].networks[&network].oid);
        // An incomplete Application already owns its assigned sibling Address,
        // even before TagName permits a canonical path. Preserve either retained
        // parent form instead of moving another identity into that reservation.
        let incomplete_destination = self.db_pending.values().any(|object| {
            object.project == project
                && object.element == "Application"
                && (object.parent == target.parent || object.parent == network_oid_parent)
                && object
                    .fields
                    .get("Address")
                    .and_then(|value| value.parse::<u8>().ok())
                    == Some(destination)
        });
        if incomplete_destination
            || self.database_address_exists(&destination_path)
            || self
                .db_fields
                .keys()
                .any(|key| key == &destination_path || key.starts_with(&destination_prefix))
            || self.objects.iter().any(|key| {
                key == &destination_path
                    || key.starts_with(&destination_prefix)
                    || key.starts_with(&format!("{destination_path}-GROUP-"))
            })
            || self.db_pending.values().any(|object| {
                object.project == project
                    && (object.path.as_deref().is_some_and(|path| {
                        path == destination_path || path.starts_with(&destination_prefix)
                    }) || object.parent == destination_path
                        || object.parent.starts_with(&destination_prefix))
            })
            || self.db_levels.values().any(|level| {
                level.parent == destination_path || level.parent.starts_with(&destination_prefix)
            })
        {
            return Err("database Address is already in use".to_string());
        }
        let mut staged = self.clone();
        staged.remap_prefix(&target.path, &destination_path);
        staged.sync_pending_database_field(project, &target.oid, "Address", value);
        staged
            .db_fields
            .insert(format!("{destination_path}/Address"), value.to_string());
        if staged
            .db_fields
            .contains_key(&format!("!{}/Address", target.oid))
        {
            staged
                .db_fields
                .insert(format!("!{}/Address", target.oid), value.to_string());
        }
        staged.sync_application_tag_field(project, network, &target.oid, source, "Address", value);
        *self = staged;
        Ok(())
    }

    fn rename_application_safe(&mut self, target: &DbXmlTarget, value: &str) -> Result<(), String> {
        let (project, network, address) =
            Self::application_path_parts(&target.path).ok_or("Invalid Application path")?;
        let sibling_prefix = format!("{}/", target.parent);
        let network_oid_parent = self
            .projects
            .get(project)
            .and_then(|project| project.networks.get(&network))
            .map(|network| format!("!{}", network.oid));
        if self.db_fields.iter().any(|(path, name)| {
            path.strip_prefix(&sibling_prefix)
                .and_then(|suffix| suffix.strip_suffix("/TagName"))
                .is_some_and(|other| {
                    other.parse::<u8>().is_ok() && other != address.to_string() && name == value
                })
        }) || self.db_pending.values().any(|object| {
            object.project == project
                && object.element == "Application"
                && (object.path.as_deref().is_some_and(|path| {
                    path != target.path
                        && path.rsplit_once('/').map(|p| p.0) == Some(target.parent.as_str())
                }) || (object.path.is_none()
                    && (object.parent == target.parent
                        || network_oid_parent.as_ref() == Some(&object.parent))))
                && object
                    .fields
                    .get("TagName")
                    .is_some_and(|name| name == value)
        }) {
            return Err("Application TagName is already in use".to_string());
        }
        let key = self
            .db_pending
            .iter()
            .find_map(|(key, object)| {
                (object.project == project
                    && object.path.as_deref() == Some(target.path.as_str())
                    && object.oid == target.oid)
                    .then(|| key.clone())
            })
            .ok_or("Typed Application identity is unavailable")?;
        let mut staged = self.clone();
        staged
            .db_pending
            .get_mut(&key)
            .expect("selected Application")
            .fields
            .insert("TagName".to_string(), value.to_string());
        staged
            .db_fields
            .insert(format!("{}/TagName", target.path), value.to_string());
        if staged
            .db_fields
            .contains_key(&format!("!{}/TagName", target.oid))
        {
            staged
                .db_fields
                .insert(format!("!{}/TagName", target.oid), value.to_string());
        }
        staged.sync_application_tag_field(project, network, &target.oid, address, "TagName", value);
        *self = staged;
        Ok(())
    }
}
