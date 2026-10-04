//! Ordinary numeric Level Value writes share the existing issued-OID byte owner.
//!
//! This is an owned consistency fix, not new native raw/null/lexical acceptance.
//! Tag/associated routes and the old unsafe setter are dispatched separately.

use crate::{err, Response, Server};

#[cfg(test)]
#[path = "ordinary_level_value_tests.rs"]
mod tests;

// An OID can be retained by PROJECT COPY in more than one loaded project.
// Typed/pending owners and canonical aliases are project-scoped; !OID/Value
// in db_fields is not. It cannot identify a selected owner by itself.
struct OrdinaryLevelValueOwner {
    oid: String,
    path: String,
    byte: Option<u8>,
}

impl OrdinaryLevelValueOwner {
    fn matches_byte(&self, value: &str) -> bool {
        !value.is_empty()
            && self
                .byte
                .is_some_and(|byte| value.parse::<u8>().ok() == Some(byte))
    }
}

impl Server {
    pub(crate) fn try_ordinary_level_value_command(
        &mut self,
        tag: &str,
        words: &[&str],
    ) -> Option<Response> {
        let getter = words.first()?.eq_ignore_ascii_case("DBGET");
        if !getter && !words[0].eq_ignore_ascii_case("DBSETSAFE") {
            return None;
        }
        let (raw, field) = words.get(1)?.rsplit_once('/')?;
        if field != "Value" || raw.starts_with('!') {
            return None;
        }
        let qualified = raw.strip_prefix("//");
        let parts = qualified.unwrap_or(raw).split('/').collect::<Vec<_>>();
        let coordinates = if qualified.is_some() {
            if parts.len() != 5 {
                return None;
            }
            &parts[1..]
        } else {
            if parts.len() != 4 {
                return None;
            }
            &parts[..]
        };
        // A named/Unit/scalar route is not an ordinary numeric Level.
        if coordinates
            .iter()
            .any(|part| part.is_empty() || !part.bytes().all(|byte| byte.is_ascii_digit()))
        {
            return None;
        }
        let Some(current) = self.current.as_deref() else {
            return Some(err(tag, 440, "440 No project selected"));
        };
        let project = qualified.map_or(current, |_| parts[0]);
        if project != current {
            return Some(err(tag, 404, "404 Project not selected"));
        }
        let parsed = coordinates
            .iter()
            .map(|part| part.parse::<u8>())
            .collect::<Result<Vec<_>, _>>();
        let Ok(addresses) = parsed else {
            return Some(err(tag, 401, "401 Ordinary numeric Level not found"));
        };
        // Keep this adapter on exact canonical coordinates. Noncanonical,
        // indexed and lexical selectors remain with their established owners.
        if coordinates
            .iter()
            .zip(&addresses)
            .any(|(part, address)| *part != address.to_string().as_str())
        {
            return Some(err(tag, 401, "401 Ordinary numeric Level not found"));
        }
        let Some(project_record) = self.projects.get(project) else {
            return Some(err(tag, 401, "401 Ordinary numeric Level not found"));
        };
        if !project_record.networks.contains_key(&addresses[0]) {
            return Some(err(tag, 404, "404 Network not found"));
        }
        if project_record
            .tag_networks
            .values()
            .any(|record| record.database_network == Some(addresses[0]))
        {
            // Raw lexemes and renamed/associated aliases belong to the prior
            // tag handler. Never reinterpret a declined associated route.
            return None;
        }
        let owner = match self.ordinary_level_value_owner(project, &addresses) {
            Ok(owner) => owner,
            Err((code, message)) => return Some(err(tag, code, message)),
        };
        if self
            .db_fields
            .get(&format!("!{}/Value", owner.oid))
            .is_some_and(|alias| {
                !owner.matches_byte(alias)
                    && !self
                        .ordinary_level_alias_has_other_project_owner(project, &owner.oid, alias)
            })
        {
            return Some(err(
                tag,
                408,
                "408 Operation failed: Ordinary Level Value mirror disagrees with its owner",
            ));
        }
        let OrdinaryLevelValueOwner { oid, path, byte } = owner;
        if getter {
            return Some(Response {
                tag: tag.to_string(),
                lines: vec![],
                final_text: format!(
                    "342 {}={}",
                    words[1],
                    byte.map_or_else(|| "null".to_string(), |value| value.to_string())
                ),
                status: 342,
            });
        }
        let project = project.to_string();
        let mut staged = self.clone();
        let addressed = format!("!{oid}/Value");
        let mut resolved = words.to_vec();
        resolved[1] = &addressed;
        // Keep exactly the existing i64-to-byte initializer grammar and its
        // error envelope. Its only successor is exact live numeric mirror sync.
        let response = staged.dbset(tag, &resolved);
        if response.status != 200 {
            return Some(response);
        }
        let changed = staged.level(&oid).expect("checked selected Level");
        debug_assert!(changed.parent.starts_with(&format!("//{project}/")));
        let value = changed
            .value
            .expect("successful byte initializer")
            .to_string();
        staged.db_fields.insert(format!("{path}/Value"), value);
        *self = staged;
        Some(response)
    }

    // Validate an explicitly named loaded owner without changing selection or
    // consulting the ambiguous global OID cache. Canonical and pending mirrors
    // remain strict even when another project retained the same issued OID.
    fn ordinary_level_value_owner(
        &self,
        project: &str,
        addresses: &[u8],
    ) -> Result<OrdinaryLevelValueOwner, (u16, &'static str)> {
        let Some(project_record) = self.projects.get(project) else {
            return Err((401, "401 Ordinary numeric Level not found"));
        };
        if !project_record.networks.contains_key(&addresses[0]) {
            return Err((404, "404 Network not found"));
        }
        if project_record
            .tag_networks
            .values()
            .any(|record| record.database_network == Some(addresses[0]))
        {
            return Err((408, "408 Associated Level has a separate owner"));
        }
        let path = format!(
            "//{project}/{}/{}/{}/{}",
            addresses[0], addresses[1], addresses[2], addresses[3]
        );
        let owners = self
            .db_levels
            .values()
            .filter(|level| !level.netvar && format!("{}/{}", level.parent, level.address) == path)
            .collect::<Vec<_>>();
        if owners.len() != 1 {
            return Err((401, "401 Ordinary numeric Level has no unique owner"));
        }
        let level = owners[0];
        let oid = level.oid.clone();
        let parent = level.parent.clone();
        let byte = level.value;
        if !self.known_oids.contains(&oid)
            || !crate::valid_uuid(&oid)
            || level.raw_value.is_some()
            || self
                .invalidated_unit_oid_lookups
                .contains(&(project.to_string(), oid.clone()))
            || project_record.networks.values().any(|network| {
                network.oid == oid
                    || network.interface_oid == oid
                    || network.units.values().any(|unit| unit.oid == oid)
            })
            || self
                .db_levels
                .values()
                .filter(|other| {
                    other.oid == oid && other.parent.starts_with(&format!("//{project}/"))
                })
                .count()
                != 1
        {
            return Err((
                408,
                "408 Operation failed: Ordinary Level identity is not a unique byte owner",
            ));
        }
        // A complete parent is necessary for an ordinary path; this does not
        // validate or rewrite label/extension metadata unrelated to Value.
        let parents = self
            .db_pending
            .values()
            .filter(|object| {
                object.project == project && object.path.as_deref() == Some(parent.as_str())
            })
            .collect::<Vec<_>>();
        if parents.len() != 1
            || !matches!(parents[0].element.as_str(), "Group" | "NetVar")
            || !self.known_oids.contains(&parents[0].oid)
            || parents[0]
                .fields
                .get("Address")
                .and_then(|value| value.parse::<u8>().ok())
                != Some(addresses[2])
        {
            return Err((
                408,
                "408 Operation failed: Ordinary Level parent is not unique",
            ));
        }
        let parent_oid = &parents[0].oid;
        let mirrors = self
            .db_pending
            .values()
            .filter(|object| {
                object.project == project
                    && (object.oid == oid
                        || object.path.as_deref() == Some(path.as_str())
                        || object.path.is_none()
                            && (object.parent == parent
                                || object.parent == format!("!{parent_oid}"))
                            && object
                                .fields
                                .get("Address")
                                .and_then(|value| value.parse::<u8>().ok())
                                == Some(addresses[3]))
            })
            .collect::<Vec<_>>();
        let coherent = |value: Option<&String>| match (value, byte) {
            (None, None) => true,
            (Some(value), Some(byte)) if !value.is_empty() => {
                value.parse::<u8>().ok() == Some(byte)
            }
            _ => false,
        };
        if mirrors.len() > 1
            || mirrors.iter().any(|object| {
                object.oid != oid
                    || object.element != "Level"
                    || object.path.as_deref() != Some(path.as_str())
                    || !(object.parent == parent || object.parent == format!("!{parent_oid}"))
                    || object
                        .fields
                        .get("Address")
                        .and_then(|value| value.parse::<u8>().ok())
                        != Some(addresses[3])
                    || object.fields.get("TagName") != Some(&level.tag)
                    || !coherent(object.fields.get("Value"))
            })
            || self
                .db_fields
                .get(&format!("{path}/Value"))
                .is_some_and(|value| !coherent(Some(value)))
        {
            return Err((
                408,
                "408 Operation failed: Ordinary Level Value mirror disagrees with its owner",
            ));
        }
        Ok(OrdinaryLevelValueOwner { oid, path, byte })
    }

    // Do not discard unexplained stale values. A different loaded project must
    // contain the same issued identity in one complete coherent byte owner, and
    // its exact byte must explain the otherwise conflicting global cache value.
    // This check neither selects that project nor rewrites any of its state.
    fn ordinary_level_alias_has_other_project_owner(
        &self,
        selected_project: &str,
        oid: &str,
        alias: &str,
    ) -> bool {
        self.db_levels.values().any(|level| {
            if level.netvar || level.oid != oid {
                return false;
            }
            let path = format!("{}/{}", level.parent, level.address);
            let Some(raw) = path.strip_prefix("//") else {
                return false;
            };
            let parts = raw.split('/').collect::<Vec<_>>();
            if parts.len() != 5 || parts[0] == selected_project {
                return false;
            }
            let coordinates = &parts[1..];
            if coordinates
                .iter()
                .any(|part| part.is_empty() || !part.bytes().all(|byte| byte.is_ascii_digit()))
            {
                return false;
            }
            let Ok(addresses) = coordinates
                .iter()
                .map(|part| part.parse::<u8>())
                .collect::<Result<Vec<_>, _>>()
            else {
                return false;
            };
            if coordinates
                .iter()
                .zip(&addresses)
                .any(|(part, address)| *part != address.to_string().as_str())
            {
                return false;
            }
            self.ordinary_level_value_owner(parts[0], &addresses)
                .is_ok_and(|owner| owner.oid == oid && owner.matches_byte(alias))
        })
    }
}
