//! Complete admitted Application SAFE copies. The captured HELP DBCOPYSAFE
//! contract pins field retention, fresh descendant OIDs and sibling conflicts.
//! Target3.4 HELP* row58 is documentation, not a fresh mutation transcript.
//! Exact native descendant/error receipts remain a separate acceptance scope.

use super::*;

#[derive(Clone)]
struct ApplicationCopyNode {
    oid: String,
    element: String,
    fields: HashMap<String, String>,
    extras: DbXmlExtras,
    children: Vec<ApplicationCopyNode>,
}

type CopyFailure = (u16, String);

impl Server {
    /// Only the public SAFE Application route receives the original tail.
    /// Existing Unit/Level and named-owner internal callers keep dbcopy intact.
    pub(crate) fn dbcopy_with_body(&mut self, tag: &str, words: &[&str], body: &str) -> Response {
        self.try_copy_application_safe(tag, words, body)
            .unwrap_or_else(|| self.dbcopy(tag, words))
    }

    /// None preserves the existing Unit/Level and captured shared-OID branches.
    /// Some always represents an actual typed copy or an explicit refusal.
    pub(crate) fn try_copy_application_safe(
        &mut self,
        tag: &str,
        words: &[&str],
        body: &str,
    ) -> Option<Response> {
        if words.len() < 5 {
            return None;
        }
        let selected = self.current.as_deref().unwrap_or("");
        let source = words[1];
        // Existing observed duplicate Unit and cross-Network OID precedence
        // belongs to dbcopy. Do not widen/reselect those captured profiles.
        if let Some(oid) = source.strip_prefix('!') {
            if let Some((root, _)) = oid.split_once('/') {
                if self.db_pending.values().any(|object| {
                    object.project == selected
                        && object.oid == root
                        && object.element == "Application"
                }) {
                    return Some(err(
                        tag,
                        408,
                        "408 Application property copy is unsupported",
                    ));
                }
                return None;
            }
            if self.selected_duplicate_unit_path(oid).is_some()
                || self.selected_cross_network_oid_path(oid).is_some()
            {
                return None;
            }
            if !self.db_pending.values().any(|object| {
                object.project == selected && object.oid == oid && object.element == "Application"
            }) {
                return None;
            }
        } else {
            let parts = source.trim_matches('/').split('/').collect::<Vec<_>>();
            let numeric = if source.starts_with("//") {
                parts.len() == 3
            } else {
                parts.len() == 2
            };
            if !numeric {
                return None;
            }
            let numbers = if source.starts_with("//") {
                &parts[1..]
            } else {
                &parts[..]
            };
            if !numbers.iter().all(|part| ascii_byte(part).is_some()) {
                // Independent named-tag rows retain their existing owner.
                return None;
            }
        }
        let Some(name) = application_copy_name_tail(body) else {
            return Some(err(tag, 400, "400 Invalid Application copy tail"));
        };
        let operation = if !valid_target(source) || !valid_target(words[2]) {
            Err((400, "Invalid copy path".to_string()))
        } else if name.trim().is_empty() || name.contains('#') {
            Err((400, "Invalid tag name".to_string()))
        } else if let Some(address) = ascii_byte(words[3]) {
            if self.associated_raw_level_copy_source(source) {
                Err((
                    408,
                    "Associated raw Level subtree copy is unsupported".to_string(),
                ))
            } else {
                self.application_safe_copy(source, words[2], address, name)
            }
        } else {
            Err((400, "Invalid database address".to_string()))
        };
        Some(match operation {
            Ok(oid) => Response {
                tag: tag.to_string(),
                lines: Vec::new(),
                final_text: format!("301 OID={oid}"),
                status: 301,
            },
            Err((code, reason)) => err(tag, code, &format!("{code} {reason}")),
        })
    }

    fn application_safe_copy(
        &mut self,
        source: &str,
        destination: &str,
        address: u8,
        name: &str,
    ) -> Result<String, CopyFailure> {
        let selected = self.current.as_deref().ok_or_else(|| {
            (
                440,
                "There is no tag database to perform this operation on".to_string(),
            )
        })?;
        let (source_project, source_path, source_oid) =
            self.application_copy_source(source, selected)?;
        let (destination_project, destination_path) =
            self.application_copy_destination(destination, selected)?;
        let target = format!("{destination_path}/{address}");
        if self.application_copy_destination_occupied(
            &destination_project,
            &destination_path,
            &target,
            address,
        ) {
            return Err((
                409,
                "Application destination contains retained state".to_string(),
            ));
        }
        let destination_oid_parent = destination_path
            .rsplit_once('/')
            .and_then(|(_, network)| network.parse::<u8>().ok())
            .and_then(|network| {
                self.projects
                    .get(&destination_project)?
                    .networks
                    .get(&network)
            })
            .map(|network| format!("!{}", network.oid));
        if self.db_pending.values().any(|object| {
            object.project == destination_project
                && object.element == "Application"
                && (object.path.as_ref().is_some_and(|path| {
                    path.rsplit_once('/').map(|(parent, _)| parent)
                        == Some(destination_path.as_str())
                }) || (object.path.is_none()
                    && (object.parent == destination_path
                        || destination_oid_parent.as_ref() == Some(&object.parent))))
                && object
                    .path
                    .as_ref()
                    .and_then(|path| self.db_fields.get(&format!("{path}/TagName")))
                    .or_else(|| object.fields.get("TagName"))
                    .is_some_and(|tag| tag == name)
        }) || self.db_fields.iter().any(|(path, tag)| {
            path.strip_suffix("/TagName").is_some_and(|owner| {
                owner.rsplit_once('/').map(|(parent, _)| parent) == Some(destination_path.as_str())
            }) && tag == name
        }) {
            return Err((409, "Application TagName already exists".to_string()));
        }
        if name.trim().is_empty() {
            return Err((400, "Invalid tag name".to_string()));
        }
        let mut identities = HashSet::new();
        let mut paths = HashSet::new();
        let mut node = self.snapshot_application_copy_node(
            &source_project,
            &source_path,
            &source_oid,
            "Application",
            &mut identities,
            &mut paths,
        )?;
        // Every retained scalar under the Application must have an owner. A
        // malformed or incomplete pending child cannot disappear in projection.
        let prefix = format!("{source_path}/");
        for field in self
            .db_fields
            .keys()
            .filter(|field| field.starts_with(&prefix))
        {
            let owner = field.rsplit_once('/').map(|(owner, _)| owner).unwrap_or("");
            if !paths.contains(owner) {
                return Err((
                    408,
                    "Application subtree has unowned scalar fields".to_string(),
                ));
            }
        }
        for object in self
            .db_pending
            .values()
            .filter(|object| object.project == source_project)
        {
            if object
                .path
                .as_ref()
                .is_some_and(|path| path.starts_with(&prefix))
                && !identities.contains(&object.oid)
            {
                return Err((
                    408,
                    "Application subtree contains an unsupported child".to_string(),
                ));
            }
        }
        node.fields
            .insert("Address".to_string(), address.to_string());
        node.fields.insert("TagName".to_string(), name.to_string());
        // No allocation or mutation is performed on the live store until the
        // entire source has been admitted. All insertion is on a separate owner.
        let mut staged = self.clone();
        staged.known_oids.extend(identities.iter().cloned());
        let mut replacements = HashMap::new();
        for old in identities.iter().collect::<BTreeSet<_>>() {
            replacements.insert(old.to_string(), staged.issue_oid());
        }
        let oid = replacements[&node.oid].clone();
        staged.insert_application_copy_node(
            &destination_project,
            &destination_path,
            &node,
            &replacements,
        )?;
        *self = staged;
        Ok(oid)
    }

    /// Refuse every retained destination boundary, including opaque orphan
    /// fields that do not yet constitute an addressable database object.
    /// This runs before source staging and before any identity allocation.
    fn application_copy_destination_occupied(
        &self,
        project: &str,
        parent: &str,
        target: &str,
        address: u8,
    ) -> bool {
        let slash = format!("{target}/");
        let hyphen = format!("{target}-");
        let marker = format!("{parent}-APPLICATION-{address}");
        let marker_slash = format!("{marker}/");
        let marker_hyphen = format!("{marker}-");
        let retained_path = |path: &str| {
            path == target
                || path.starts_with(&slash)
                || path.starts_with(&hyphen)
                || path == marker
                || path.starts_with(&marker_slash)
                || path.starts_with(&marker_hyphen)
        };
        if self.database_address_exists(target)
            || self.db_fields.keys().any(|path| retained_path(path))
            || self.objects.iter().any(|path| retained_path(path))
            || self
                .db_levels
                .values()
                .any(|level| retained_path(&level.parent))
        {
            return true;
        }
        let parent_oid = parent
            .rsplit_once('/')
            .and_then(|(_, network)| network.parse::<u8>().ok())
            .and_then(|network| self.projects.get(project)?.networks.get(&network))
            .map(|network| format!("!{}", network.oid));
        self.db_pending.values().any(|object| {
            object.project == project
                && (object.path.as_deref().is_some_and(retained_path)
                    || retained_path(&object.parent)
                    || (object.element == "Application"
                        && (object.parent == parent
                            || parent_oid.as_ref() == Some(&object.parent))
                        && object
                            .fields
                            .get("Address")
                            .and_then(|value| ascii_byte(value))
                            == Some(address)))
        })
    }

    fn application_copy_source(
        &self,
        raw: &str,
        selected: &str,
    ) -> Result<(String, String, String), CopyFailure> {
        let matches = if let Some(oid) = raw.strip_prefix('!') {
            self.db_pending
                .values()
                .filter(|object| {
                    object.project == selected
                        && object.oid == oid
                        && object.element == "Application"
                })
                .collect::<Vec<_>>()
        } else {
            let expanded = if raw.starts_with("//") {
                raw.to_string()
            } else {
                format!("//{selected}/{}", raw.trim_matches('/'))
            };
            let parts = expanded.trim_matches('/').split('/').collect::<Vec<_>>();
            if parts.len() != 3 {
                return Err((408, "Application source path is unsupported".to_string()));
            }
            let network =
                ascii_byte(parts[1]).ok_or_else(|| (400, "Invalid source Network".to_string()))?;
            let application = ascii_byte(parts[2])
                .ok_or_else(|| (400, "Invalid source Application".to_string()))?;
            let path = format!("//{}/{network}/{application}", parts[0]);
            self.db_pending
                .values()
                .filter(|object| {
                    object.element == "Application" && object.path.as_deref() == Some(path.as_str())
                })
                .collect::<Vec<_>>()
        };
        if matches.len() > 1 {
            return Err((409, "Application source identity is ambiguous".to_string()));
        }
        let object = matches.first().ok_or_else(|| {
            (
                401,
                "Complete typed Application source not found".to_string(),
            )
        })?;
        let path = object.path.clone().ok_or_else(|| {
            (
                408,
                "Application source is not fully materialized".to_string(),
            )
        })?;
        Ok((object.project.clone(), path, object.oid.clone()))
    }

    fn application_copy_destination(
        &self,
        raw: &str,
        selected: &str,
    ) -> Result<(String, String), CopyFailure> {
        if let Some(oid) = raw.strip_prefix('!') {
            let networks = self
                .projects
                .get(selected)
                .into_iter()
                .flat_map(|project| project.networks.values())
                .filter(|network| network.oid == oid)
                .collect::<Vec<_>>();
            if networks.len() != 1 {
                return Err((
                    401,
                    "Destination Network identity not found or ambiguous".to_string(),
                ));
            }
            return Ok((
                selected.to_string(),
                format!("//{selected}/{}", networks[0].address),
            ));
        }
        let path = if raw.starts_with("//") {
            raw.trim_end_matches('/').to_string()
        } else {
            format!("//{selected}/{}", raw.trim_matches('/'))
        };
        let parts = path.trim_matches('/').split('/').collect::<Vec<_>>();
        if parts.len() != 2 {
            return Err((
                408,
                "Source and destination parent element types do not match".to_string(),
            ));
        }
        let network =
            ascii_byte(parts[1]).ok_or_else(|| (400, "Invalid destination Network".to_string()))?;
        if !self
            .projects
            .get(parts[0])
            .is_some_and(|project| project.networks.contains_key(&network))
        {
            return Err((401, "Destination Network not found".to_string()));
        }
        Ok((parts[0].to_string(), format!("//{}/{network}", parts[0])))
    }

    fn snapshot_application_copy_node(
        &self,
        project: &str,
        path: &str,
        oid: &str,
        element: &str,
        identities: &mut HashSet<String>,
        paths: &mut HashSet<String>,
    ) -> Result<ApplicationCopyNode, CopyFailure> {
        if !valid_uuid(oid) {
            return Err((408, "Application subtree identity is invalid".to_string()));
        }
        if !identities.insert(oid.to_string()) || !paths.insert(path.to_string()) {
            return Err((
                409,
                "Application subtree repeats an identity or address".to_string(),
            ));
        }
        let records = self
            .db_pending
            .values()
            .filter(|object| object.project == project && object.oid == oid)
            .collect::<Vec<_>>();
        if records.len() > 1
            || records
                .iter()
                .any(|object| object.element != element || object.path.as_deref() != Some(path))
        {
            return Err((
                409,
                "Application subtree has conflicting identity owners".to_string(),
            ));
        }
        let mut fields = records
            .first()
            .map_or_else(HashMap::new, |record| record.fields.clone());
        let levels = self
            .db_levels
            .iter()
            .filter(|(key, level)| {
                level.oid == oid && self.application_copy_level_in_project(project, key, level)
            })
            .map(|(_, level)| level)
            .collect::<Vec<_>>();
        if levels.len() > 1
            || self.projects.get(project).into_iter().any(|project| {
                project.networks.values().any(|network| {
                    network.oid == oid
                        || network.interface_oid == oid
                        || network.units.values().any(|unit| unit.oid == oid)
                })
            })
        {
            return Err((
                409,
                "Application subtree repeats or has foreign identity owner".to_string(),
            ));
        }
        let level = levels.first().map(|level| (*level).clone());
        if let Some(level) = &level {
            if level.raw_value.is_some() {
                return Err((
                    408,
                    "Associated raw Level subtree copy is unsupported".to_string(),
                ));
            }
            fields.insert("Address".to_string(), level.address.to_string());
            fields.insert("TagName".to_string(), level.tag.clone());
            if let Some(value) = level.effective_value() {
                fields.insert("Value".to_string(), value);
            } else {
                fields.remove("Value");
            }
        }
        let direct = format!("{path}/");
        let oid_prefix = format!("!{oid}/");
        // Alias and canonical stores must agree; otherwise choosing one would
        // silently discard retained state. Canonical current scalars supersede
        // the pending construction fields only after this consistency check.
        for (key, value) in &self.db_fields {
            let Some(field) = key.strip_prefix(&oid_prefix) else {
                continue;
            };
            if field.contains('/') {
                return Err((
                    408,
                    "Application subtree has unclassified nested OID fields".to_string(),
                ));
            }
            if self
                .db_fields
                .get(&format!("{direct}{field}"))
                .is_some_and(|canonical| canonical != value)
            {
                return Err((
                    409,
                    "Application subtree has conflicting scalar aliases".to_string(),
                ));
            }
            fields.insert(field.to_string(), value.clone());
        }
        for (key, value) in &self.db_fields {
            let Some(field) = key.strip_prefix(&direct) else {
                continue;
            };
            if !field.contains('/') {
                fields.insert(field.to_string(), value.clone());
            }
        }
        if fields.get("OID").is_some_and(|value| value != oid) {
            return Err((
                409,
                "Application subtree has conflicting OID scalar".to_string(),
            ));
        }
        let address = fields
            .get("Address")
            .and_then(|value| ascii_byte(value))
            .ok_or_else(|| {
                (
                    408,
                    "Application subtree has an incomplete Address".to_string(),
                )
            })?;
        if path.rsplit_once('/').map(|(_, a)| a) != Some(address.to_string().as_str())
            || !fields.contains_key("TagName")
        {
            return Err((
                408,
                "Application subtree has inconsistent address/name fields".to_string(),
            ));
        }
        let mut extras = self
            .db_xml_extras
            .get(&Self::unit_document_key(project, oid))
            .cloned()
            .unwrap_or_default();
        admit_application_copy_extras(&mut extras, identities)?;
        let allowed = match element {
            "Application" => &["Group", "NetVar"][..],
            "Group" | "NetVar" => &["Level"][..],
            _ => &[][..],
        };
        let mut children = BTreeMap::<u8, (String, String)>::new();
        for record in self.db_pending.values().filter(|record| {
            record.project == project
                && (record.parent == path || record.parent == format!("!{oid}"))
        }) {
            if !allowed.contains(&record.element.as_str()) {
                return Err((
                    408,
                    "Application subtree has an unsupported child kind".to_string(),
                ));
            }
            let address = record
                .fields
                .get("Address")
                .and_then(|value| ascii_byte(value))
                .ok_or_else(|| {
                    (
                        408,
                        "Application subtree has an incomplete child".to_string(),
                    )
                })?;
            if children
                .insert(address, (record.oid.clone(), record.element.clone()))
                .is_some()
            {
                return Err((
                    409,
                    "Application subtree has duplicate child Address".to_string(),
                ));
            }
        }
        for level in self.db_levels.values().filter(|level| {
            level.parent == path
                || (level.parent == format!("!{oid}")
                    && self
                        .db_pending
                        .values()
                        .filter(|object| object.oid == oid)
                        .all(|object| object.project == project))
        }) {
            let kind = if level.netvar { "NetVar" } else { "Level" };
            if !allowed.contains(&kind) {
                return Err((408, "Application subtree has a misplaced Level".to_string()));
            }
            if let Some((old, old_kind)) = children.get(&level.address) {
                if old != &level.oid || old_kind != kind {
                    return Err((
                        409,
                        "Application subtree has conflicting Level mirrors".to_string(),
                    ));
                }
            } else {
                children.insert(level.address, (level.oid.clone(), kind.to_string()));
            }
        }
        let children = children
            .into_iter()
            .map(|(address, (oid, kind))| {
                self.snapshot_application_copy_node(
                    project,
                    &format!("{path}/{address}"),
                    &oid,
                    &kind,
                    identities,
                    paths,
                )
            })
            .collect::<Result<Vec<_>, _>>()?;
        Ok(ApplicationCopyNode {
            oid: oid.to_string(),
            element: element.to_string(),
            fields,
            extras,
            children,
        })
    }

    fn application_copy_level_in_project(&self, project: &str, key: &str, level: &DbLevel) -> bool {
        if key.starts_with(&format!("{project}\u{1f}"))
            || level.parent.starts_with(&format!("//{project}/"))
        {
            return true;
        }
        if let Some(parent) = level.parent.strip_prefix('!') {
            let owners = self
                .db_pending
                .values()
                .filter(|object| object.oid == parent)
                .collect::<Vec<_>>();
            return !owners.is_empty() && owners.iter().all(|object| object.project == project);
        }
        false
    }

    fn insert_application_copy_node(
        &mut self,
        project: &str,
        parent: &str,
        node: &ApplicationCopyNode,
        identities: &HashMap<String, String>,
    ) -> Result<(), CopyFailure> {
        let oid = identities[&node.oid].clone();
        let address = node
            .fields
            .get("Address")
            .and_then(|value| ascii_byte(value))
            .ok_or_else(|| (408, "Copy has an incomplete Address".to_string()))?;
        let path = format!("{parent}/{address}");
        if self.database_address_exists(&path) {
            return Err((
                409,
                "Copy destination child Address already exists".to_string(),
            ));
        }
        let mut fields = node.fields.clone();
        if fields.contains_key("OID") {
            fields.insert("OID".to_string(), oid.clone());
        }
        self.insert_db_pending_object(DbPendingObject {
            oid: oid.clone(),
            project: project.to_string(),
            parent: parent.to_string(),
            element: node.element.clone(),
            fields: fields.clone(),
            path: Some(path.clone()),
            xml_order: None,
        });
        self.known_oids.insert(oid.clone());
        self.objects.insert(format!("!{oid}"));
        self.objects.insert(path.clone());
        for (name, value) in &fields {
            self.db_fields
                .insert(format!("{path}/{name}"), value.clone());
        }
        let extras = remap_application_copy_extras(&node.extras, identities)?;
        self.store_db_xml_extras(project, &oid, &extras);
        match node.element.as_str() {
            "Application" => {
                self.record_application_path(&path);
                self.objects
                    .insert(format!("{parent}-APPLICATION-{address}"));
            }
            "Group" => {
                self.objects.insert(format!("{parent}-GROUP-{address}"));
            }
            "Level" | "NetVar" => {
                let value = fields
                    .get("Value")
                    .map(|value| value.parse::<u8>())
                    .transpose()
                    .map_err(|_| (408, "Copy has an unsupported Level Value".to_string()))?;
                self.db_levels.insert(
                    format!("{project}\u{1f}{oid}"),
                    DbLevel {
                        oid: oid.clone(),
                        parent: parent.to_string(),
                        address,
                        tag: fields["TagName"].clone(),
                        value,
                        raw_value: None,
                        netvar: node.element == "NetVar",
                    },
                );
            }
            _ => return Err((408, "Copy has an unsupported object kind".to_string())),
        }
        for child in &node.children {
            self.insert_application_copy_node(project, &path, child, identities)?;
        }
        Ok(())
    }
}

fn application_copy_name_tail(body: &str) -> Option<&str> {
    let mut tail = body;
    for _ in 0..4 {
        tail = tail.trim_start_matches(char::is_whitespace);
        let (offset, separator) = tail
            .char_indices()
            .find(|(_, character)| character.is_whitespace())?;
        tail = &tail[offset + separator.len_utf8()..];
    }
    Some(tail)
}

fn ascii_byte(value: &str) -> Option<u8> {
    (!value.is_empty() && value.bytes().all(|byte| byte.is_ascii_digit()))
        .then(|| value.parse().ok())
        .flatten()
}

fn admit_application_copy_extras(
    extras: &mut DbXmlExtras,
    identities: &mut HashSet<String>,
) -> Result<(), CopyFailure> {
    if !extras.attributes.is_empty() || !extras.namespaces.is_empty() {
        return Err((
            408,
            "Application copy contains unclassified namespaced metadata".to_string(),
        ));
    }
    for xml in &extras.children {
        let document = roxmltree::Document::parse(xml)
            .map_err(|_| (408, "Copy metadata is not valid XML".to_string()))?;
        if document.root_element().tag_name().name() != "TagsDLT"
            || document.root_element().tag_name().namespace().is_some()
        {
            return Err((
                408,
                "Application copy contains unclassified XML metadata".to_string(),
            ));
        }
        if document.root_element().attributes().len() != 0 {
            return Err((
                408,
                "Application copy contains unclassified TagsDLT attributes".to_string(),
            ));
        }
        for tag in document
            .root_element()
            .children()
            .filter(|node| node.is_element())
        {
            if !tag.has_tag_name("TagDLT")
                || tag.tag_name().namespace().is_some()
                || tag.attributes().len() != 0
            {
                return Err((
                    408,
                    "Application copy contains unclassified TagsDLT child".to_string(),
                ));
            }
            let oid_fields = tag
                .children()
                .filter(|node| node.has_tag_name("OID"))
                .collect::<Vec<_>>();
            if oid_fields.len() != 1 {
                return Err((
                    408,
                    "Application copy TagDLT identity is incomplete".to_string(),
                ));
            }
            for field in tag.children().filter(|node| node.is_element()) {
                if !["OID", "LanguageID", "FlavourID", "TagType", "TagValue"]
                    .contains(&field.tag_name().name())
                    || field.tag_name().namespace().is_some()
                    || field.attributes().len() != 0
                    || field.children().any(|node| node.is_element())
                {
                    return Err((
                        408,
                        "Application copy contains unclassified TagDLT fields".to_string(),
                    ));
                }
            }
            if oid_fields[0].children().count() != 1
                || !oid_fields[0].children().all(|child| child.is_text())
            {
                return Err((
                    408,
                    "Application copy identity metadata is not plain text".to_string(),
                ));
            }
            let oid = oid_fields[0].text().unwrap_or("");
            if !valid_uuid(oid) || !identities.insert(oid.to_string()) {
                return Err((
                    409,
                    "Application copy metadata repeats or has invalid OID".to_string(),
                ));
            }
        }
    }
    Ok(())
}

fn remap_application_copy_extras(
    extras: &DbXmlExtras,
    identities: &HashMap<String, String>,
) -> Result<DbXmlExtras, CopyFailure> {
    let mut result = extras.clone();
    for xml in &mut result.children {
        let document = roxmltree::Document::parse(xml)
            .map_err(|_| (408, "Copy metadata is not valid XML".to_string()))?;
        let edits = document
            .descendants()
            .filter(|node| node.has_tag_name("OID"))
            .map(|node| {
                let value = identities
                    .get(node.text().unwrap_or(""))
                    .ok_or_else(|| (408, "Copy metadata identity was not staged".to_string()))?;
                Ok((node.range(), format!("<OID>{value}</OID>")))
            })
            .collect::<Result<Vec<_>, CopyFailure>>()?;
        for (range, replacement) in edits.into_iter().rev() {
            xml.replace_range(range, &replacement);
        }
    }
    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn seed() -> Server {
        let mut server = Server::new(AccessLevel::Program);
        assert_eq!(server.handle("[new] PROJECT NEW COPY").status, 200);
        assert_eq!(
            server
                .handle("[net] DBCREATENET 254 Local Cni nowhere")
                .status,
            200
        );
        assert_eq!(
            server
                .handle("[dest] DBCREATENET 253 Other Cni nowhere")
                .status,
            200
        );
        for (address, name) in [(72, "A72"), (0, "Zero"), (71, "A71"), (66, "A66")] {
            assert_eq!(
                server
                    .handle(&format!(
                        "[app] DBADDSAFE //COPY/254 Application {address} {name}"
                    ))
                    .status,
                301
            );
        }
        let app = server.handle("[app] DBADDSAFE //COPY/254 Application 56 Source");
        let app_oid = app.final_text.strip_prefix("301 OID=").unwrap().to_string();
        let group = server.handle("[group] DBADDSAFE //COPY/254/56 Group 7 Heat");
        let group_oid = group
            .final_text
            .strip_prefix("301 OID=")
            .unwrap()
            .to_string();
        let level = server.handle("[level] DBADDSAFE //COPY/254/56/7 Level 3 Medium");
        let level_oid = level
            .final_text
            .strip_prefix("301 OID=")
            .unwrap()
            .to_string();
        assert_eq!(
            server
                .handle(&format!("[value] DBSETSAFE !{level_oid}/Value 77"))
                .status,
            200
        );
        // Nonidentity scalar references are copied as fields; outside owners
        // and inbound references are never redirected to the new subtree.
        server.db_fields.insert(
            "//COPY/254/56/Description".into(),
            "Owned complete copy".into(),
        );
        server.db_fields.insert(
            "//COPY/254/56/ExternalReference".into(),
            "//COPY/254/72/1".into(),
        );
        server
            .db_fields
            .insert("//COPY/254/56/7/OptionalField".into(), "unchanged".into());
        server
            .db_fields
            .insert("//COPY/254/72/Reference".into(), format!("!{group_oid}"));
        let tag_oid = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";
        server.db_xml_extras.insert(Server::unit_document_key("COPY",&level_oid),DbXmlExtras {
            children:vec![format!("<TagsDLT><TagDLT><OID>{tag_oid}</OID><LanguageID>1</LanguageID><FlavourID>1</FlavourID><TagType>TEXT</TagType><TagValue>Keep &amp; retain</TagValue></TagDLT></TagsDLT>")],
            ..DbXmlExtras::default()
        });
        assert!(server
            .db_pending
            .values()
            .any(|object| object.oid == app_oid));
        server
    }

    fn command(
        server: &mut Server,
        source: &str,
        parent: &str,
        address: &str,
        name: &str,
    ) -> Response {
        let text = format!("DBCOPYSAFE {source} {parent} {address} {name}");
        server
            .try_copy_application_safe("copy", &text.split_whitespace().collect::<Vec<_>>(), &text)
            .unwrap()
    }

    #[test]
    fn complete_copy_preserves_every_scalar_and_fresh_metadata_oid() {
        let mut server = seed();
        let source = server.project_tables("COPY");
        let source_image = serde_json::to_value(&source).unwrap();
        let old = server
            .db_pending
            .values()
            .filter(|object| {
                object
                    .path
                    .as_ref()
                    .is_some_and(|path| path.starts_with("//COPY/254/56"))
            })
            .map(|object| object.oid.clone())
            .collect::<HashSet<_>>();
        let response = command(
            &mut server,
            "//COPY/254/56",
            "//COPY/253",
            "80",
            "Copied name",
        );
        assert_eq!(response.status, 301, "{response:?}");
        assert_eq!(
            server.db_fields["//COPY/253/80/Description"],
            "Owned complete copy"
        );
        assert_eq!(
            server.db_fields["//COPY/253/80/ExternalReference"],
            "//COPY/254/72/1"
        );
        assert_eq!(
            server.db_fields["//COPY/253/80/7/OptionalField"],
            "unchanged"
        );
        let copied = server
            .db_pending
            .values()
            .filter(|object| {
                object
                    .path
                    .as_ref()
                    .is_some_and(|path| path.starts_with("//COPY/253/80"))
            })
            .collect::<Vec<_>>();
        assert_eq!(copied.len(), 3);
        assert!(copied.iter().all(|object| !old.contains(&object.oid)));
        let level = copied
            .iter()
            .find(|object| object.element == "Level")
            .unwrap();
        let label =
            &server.db_xml_extras[&Server::unit_document_key("COPY", &level.oid)].children[0];
        assert!(!label.contains("cccccccc-cccc-4ccc-8ccc-cccccccccccc"));
        assert!(label.contains("<TagValue>Keep &amp; retain</TagValue>"));
        let label_doc = roxmltree::Document::parse(label).unwrap();
        let tag_oid = label_doc
            .descendants()
            .find(|node| node.has_tag_name("OID"))
            .unwrap()
            .text()
            .unwrap();
        assert!(valid_uuid(tag_oid));
        assert!(!old.contains(tag_oid));
        assert!(copied.iter().all(|object| object.oid != tag_oid));
        // The original prefix and its incoming reference are byte-for-byte
        // unchanged; copied optional fields are asserted independently above.
        let now = serde_json::to_value(server.project_tables("COPY")).unwrap();
        for (key, value) in source_image["db_fields"].as_object().unwrap() {
            assert_eq!(&now["db_fields"][key], value);
        }
        for old in &source.db_pending {
            assert!(server.db_pending.values().any(|current| current == old));
        }
        assert_eq!(
            server.projects["COPY"].networks[&254]
                .application_creation_order
                .addresses,
            vec![72, 0, 71, 66, 56]
        );
        assert_eq!(
            server.projects["COPY"].networks[&253]
                .application_creation_order
                .addresses,
            vec![80]
        );
        assert_eq!(
            server
                .db_levels
                .values()
                .find(|value| value.oid == level.oid)
                .unwrap()
                .value,
            Some(77)
        );
        assert!(server.cgl_runtime.is_empty());
        assert!(!server.saved_projects.contains_key("COPY"));
    }

    #[test]
    fn same_parent_appends_once_and_source_oid_addressing_uses_same_complete_owner() {
        let mut server = seed();
        let oid = server
            .db_pending
            .values()
            .find(|object| object.path.as_deref() == Some("//COPY/254/56"))
            .unwrap()
            .oid
            .clone();
        assert_eq!(
            command(&mut server, &format!("!{oid}"), "//COPY/254", "80", "Copy").status,
            301
        );
        assert_eq!(
            server.projects["COPY"].networks[&254]
                .application_creation_order
                .addresses,
            vec![72, 0, 71, 66, 56, 80]
        );
        let before = server.project_tables("COPY");
        let known = server.known_oids.clone();
        assert_eq!(
            command(&mut server, "//COPY/254/56", "//COPY/254", "80", "Other").status,
            409
        );
        assert_eq!(
            command(&mut server, "//COPY/254/56", "//COPY/254", "81", "Copy").status,
            409
        );
        assert_eq!(server.project_tables("COPY"), before);
        assert_eq!(server.known_oids, known);
    }

    #[test]
    fn retained_destination_state_refuses_before_allocation_or_mutation() {
        for kind in 0..8 {
            let mut server = seed();
            let target = "//COPY/253/80";
            match kind {
                0 => {
                    // Existing SAFE scalar fallback accepts this field without
                    // creating an Application. It must not be overwritten.
                    assert_eq!(
                        server
                            .handle("[orphan] DBSETSAFE //COPY/253/80/Description Retained")
                            .status,
                        200
                    );
                    assert!(!server.database_address_exists(target));
                    assert_eq!(server.db_fields["//COPY/253/80/Description"], "Retained");
                }
                1 => {
                    server
                        .db_fields
                        .insert(format!("{target}/7/Description"), "Retained child".into());
                }
                2 => {
                    server.objects.insert(format!("{target}-GROUP-7"));
                }
                3 => {
                    server.objects.insert("//COPY/253-APPLICATION-80".into());
                }
                4 | 5 => {
                    server.insert_db_pending_object(DbPendingObject {
                        oid: "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee".into(),
                        project: "COPY".into(),
                        parent: target.into(),
                        element: "Group".into(),
                        fields: HashMap::from([("Address".into(), "7".into())]),
                        path: (kind == 4).then(|| format!("{target}/7")),
                        xml_order: None,
                    });
                }
                6 => {
                    server.db_levels.insert(
                        "orphan-level".into(),
                        DbLevel {
                            oid: "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee".into(),
                            parent: format!("{target}/7"),
                            address: 3,
                            tag: "Retained".into(),
                            value: Some(77),
                            raw_value: None,
                            netvar: false,
                        },
                    );
                }
                7 => {
                    let parent = format!("!{}", server.projects["COPY"].networks[&253].oid);
                    server.insert_db_pending_object(DbPendingObject {
                        oid: "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee".into(),
                        project: "COPY".into(),
                        parent,
                        element: "Application".into(),
                        fields: HashMap::from([("Address".into(), "80".into())]),
                        path: None,
                        xml_order: None,
                    });
                }
                _ => unreachable!(),
            }
            let before = server.project_tables("COPY");
            let projects = server.projects.clone();
            let known = server.known_oids.clone();
            let fields = server.db_fields.clone();
            let pending = server.db_pending.clone();
            let levels = server.db_levels.clone();
            let objects = server.objects.clone();
            let response = server.handle("[copy] DBCOPYSAFE //COPY/254/56 //COPY/253 80 Copy");
            assert_eq!(response.status, 409, "kind={kind}: {response:?}");
            assert_eq!(
                response.final_text,
                "409 Application destination contains retained state"
            );
            assert_eq!(server.project_tables("COPY"), before);
            assert_eq!(server.projects, projects);
            assert_eq!(server.known_oids, known);
            assert_eq!(server.db_fields, fields);
            assert_eq!(server.db_pending, pending);
            assert_eq!(server.db_levels, levels);
            assert_eq!(server.objects, objects);
        }
    }

    #[test]
    fn public_dispatch_reaches_typed_copy_before_network_owner_and_uses_exact_boundaries() {
        let mut server = seed();
        server
            .db_fields
            .insert("//COPY/253/800/Description".into(), "Neighbor".into());
        server.objects.insert("//COPY/253-APPLICATION-800".into());
        let response =
            server.handle("[copy] DBCOPYSAFE //COPY/254/56 //COPY/253 80 Repeated  spaces");
        assert_eq!(response.status, 301, "{response:?}");
        assert_eq!(
            server.db_fields["//COPY/253/80/TagName"],
            "Repeated  spaces"
        );
        assert_eq!(server.db_fields["//COPY/253/800/Description"], "Neighbor");
        assert!(server.objects.contains("//COPY/253-APPLICATION-800"));
        assert_eq!(
            server.projects["COPY"].networks[&253]
                .application_creation_order
                .addresses,
            vec![80]
        );
    }

    #[test]
    fn cross_project_copy_changes_only_destination() {
        let mut server = seed();
        assert_eq!(server.handle("[other] PROJECT NEW OTHER").status, 200);
        assert_eq!(
            server
                .handle("[net] DBCREATENET 1 Target Cni nowhere")
                .status,
            200
        );
        assert_eq!(server.handle("[source] PROJECT USE COPY").status, 200);
        let before = server.project_tables("COPY");
        assert_eq!(
            command(&mut server, "//COPY/254/56", "//OTHER/1", "0", "Cross").status,
            301
        );
        assert_eq!(server.project_tables("COPY"), before);
        assert_eq!(server.current.as_deref(), Some("COPY"));
        assert_eq!(
            server.projects["OTHER"].networks[&1]
                .application_creation_order
                .addresses,
            vec![0]
        );
        let copied = server
            .db_pending
            .values()
            .filter(|object| object.project == "OTHER")
            .collect::<Vec<_>>();
        assert_eq!(copied.len(), 3);
        assert!(copied
            .iter()
            .all(|object| object.parent.starts_with("//OTHER/1")));
    }

    #[test]
    fn invalid_destination_and_decimal_grammar_are_atomic() {
        assert_eq!(
            application_copy_name_tail("DBCOPYSAFE //COPY/254/56 //COPY/253 80  Repeated  spaces "),
            Some(" Repeated  spaces ")
        );
        for (parent, address, expected) in [
            ("//COPY/254/56", "81", 408),
            ("//COPY/252", "81", 401),
            ("//COPY/253", "+1", 400),
            ("//COPY/253", "-1", 400),
            ("//COPY/253", "256", 400),
            ("//COPY/253", "one", 400),
        ] {
            let mut server = seed();
            let before = server.project_tables("COPY");
            let projects = server.projects.clone();
            let known = server.known_oids.clone();
            assert_eq!(
                command(&mut server, "//COPY/254/56", parent, address, "Copy").status,
                expected
            );
            assert_eq!(server.project_tables("COPY"), before);
            assert_eq!(server.projects, projects);
            assert_eq!(server.known_oids, known);
        }
    }

    #[test]
    fn unsupported_metadata_does_not_allocate_or_drop_data() {
        for invalid in [
            "<Unknown><OID>cccccccc-cccc-4ccc-8ccc-cccccccccccc</OID></Unknown>",
            "<TagsDLT><TagDLT><TagValue>No identity</TagValue></TagDLT></TagsDLT>",
            "<TagsDLT><TagDLT><OID>cccccccc-cccc-4ccc-8ccc-cccccccccccc</OID><Unknown>Keep me</Unknown></TagDLT></TagsDLT>",
            "<TagsDLT><TagDLT><OID>cccccccc-cccc-4ccc-8ccc-cccccccccccc<!--keep--></OID></TagDLT></TagsDLT>",
            "<TagsDLT><TagDLT><OID>cccccccc-cccc-4ccc-8ccc-cccccccccccc<?keep metadata?></OID></TagDLT></TagsDLT>",
        ] {
            let mut server = seed();
            let level = server.db_levels.values().next().unwrap().oid.clone();
            server
                .db_xml_extras
                .get_mut(&Server::unit_document_key("COPY", &level))
                .unwrap()
                .children = vec![invalid.to_string()];
            let before = server.project_tables("COPY");
            let known = server.known_oids.clone();
            assert_eq!(
                command(&mut server, "//COPY/254/56", "//COPY/253", "80", "Copy").status,
                408
            );
            assert_eq!(server.project_tables("COPY"), before);
            assert_eq!(server.known_oids, known);
        }
    }

    #[test]
    fn raw_value_and_conflicting_aliases_refuse_instead_of_lossy_projection() {
        let mut server = seed();
        let level = server.db_levels.values_mut().next().unwrap();
        level.raw_value = Some("oops".to_string());
        level.value = None;
        let before = server.project_tables("COPY");
        assert_eq!(
            command(&mut server, "//COPY/254/56", "//COPY/253", "80", "Copy").status,
            408
        );
        assert_eq!(server.project_tables("COPY"), before);
        let mut server = seed();
        let app = server
            .db_pending
            .values()
            .find(|object| object.path.as_deref() == Some("//COPY/254/56"))
            .unwrap()
            .oid
            .clone();
        server
            .db_fields
            .insert(format!("!{app}/TagName"), "Conflicting alias".to_string());
        let before = server.project_tables("COPY");
        assert_eq!(
            command(&mut server, "//COPY/254/56", "//COPY/253", "80", "Copy").status,
            409
        );
        assert_eq!(server.project_tables("COPY"), before);
    }

    #[test]
    fn incomplete_numeric_application_and_property_selector_do_not_fall_through() {
        let mut server = seed();
        server
            .db_pending
            .retain(|_, object| object.path.as_deref() != Some("//COPY/254/56"));
        let before = server.project_tables("COPY");
        assert_eq!(
            command(&mut server, "//COPY/254/56", "//COPY/253", "80", "Copy").status,
            401
        );
        assert_eq!(server.project_tables("COPY"), before);
        let mut server = seed();
        let app = server
            .db_pending
            .values()
            .find(|object| object.path.as_deref() == Some("//COPY/254/56"))
            .unwrap()
            .oid
            .clone();
        let before = server.project_tables("COPY");
        assert_eq!(
            command(
                &mut server,
                &format!("!{app}/TagName"),
                "//COPY/253",
                "80",
                "Copy"
            )
            .status,
            408
        );
        assert_eq!(server.project_tables("COPY"), before);
    }

    #[test]
    fn captured_cross_network_shared_oid_leaf_route_is_deferred() {
        let fixture: serde_json::Value = serde_json::from_str(include_str!(
            "../../testdata/fixtures/native_cgate_large_cross_network_oid.json"
        ))
        .unwrap();
        let captured = &fixture["cross_network"][33];
        assert_eq!(captured["shape"], "unit_application");
        assert_eq!(captured["selected_network"], 253);
        assert_eq!(captured["selected_kind"], "Application");
        assert!(captured["applied"]["response_lines"][0]
            .as_str()
            .unwrap()
            .starts_with("[2352] 301 OID="));
        let mut server = Server::new(AccessLevel::Program);
        assert_eq!(server.handle("[new] PROJECT NEW LEGACY").status, 200);
        for (network, name) in [(254, "Local254"), (253, "Local253")] {
            assert_eq!(
                server
                    .handle(&format!("[net] DBCREATENET {network} {name} Cni nowhere"))
                    .status,
                200
            );
        }
        let shared = "11111111-1111-4111-8111-111111111111";
        // Replay the admitted captured leaf profile: Unit20 in the first
        // created Network, Application56 in the second. Only owned parent
        // OIDs and the project selector differ from the retained request.
        for (network, row) in [254, 253]
            .into_iter()
            .zip(captured["inserts"].as_array().unwrap())
        {
            let tag = row["tag"].as_u64().unwrap();
            let request = row["request"].as_str().unwrap();
            let body = request
                .split_once(&format!(" << END{tag}\r\n"))
                .unwrap()
                .1
                .strip_suffix(&format!("\r\nEND{tag}\r\n"))
                .unwrap();
            let record = &server.projects["LEGACY"].networks[&network];
            let literal = body
                .replace(
                    fixture["network_oids"][network.to_string()]
                        .as_str()
                        .unwrap(),
                    &record.oid,
                )
                .replace(
                    fixture["interface_oids"][network.to_string()]
                        .as_str()
                        .unwrap(),
                    &record.interface_oid,
                );
            assert_eq!(
                server
                    .handle_document(&format!("[xml] DBSETXML //LEGACY/{network}"), &literal)
                    .status,
                301
            );
        }
        assert_eq!(
            server.selected_cross_network_oid_path(shared).as_deref(),
            Some("//LEGACY/253/56")
        );
        let words = [
            "DBCOPYSAFE",
            "!11111111-1111-4111-8111-111111111111",
            "//LEGACY/253",
            "30",
            "Copied",
        ];
        assert!(server
            .try_copy_application_safe("copy", &words, &words.join(" "))
            .is_none());
        let observed = server.dbcopy("copy", &words);
        assert_eq!(observed.status, 301);
        assert!(observed.final_text.starts_with("301 OID="));
        let fresh = observed.final_text.strip_prefix("301 OID=").unwrap();
        assert_ne!(fresh, shared);
        assert_eq!(
            server
                .application_xml("read", "LEGACY", "//LEGACY/253/30")
                .lines[0]
                .strip_prefix("347-")
                .unwrap(),
            format!(
                "<Application><OID>{fresh}</OID><TagName>Copied</TagName><Address>30</Address></Application>"
            )
        );
    }
    #[test]
    fn shared_unit_oid_precedence_is_deferred_without_reselecting_application() {
        let duplicate: serde_json::Value = serde_json::from_str(include_str!(
            "../../testdata/fixtures/native_cgate_duplicate_unit_oid_mutations.json"
        ))
        .unwrap();
        let cross_kind: serde_json::Value = serde_json::from_str(include_str!(
            "../../testdata/fixtures/native_cgate_cross_kind_oid_mutations.json"
        ))
        .unwrap();
        let retained_document = |fixture: &serde_json::Value| {
            let row = &fixture["cases"]
                .as_array()
                .unwrap()
                .iter()
                .find(|case| case["name"] == "copy_safe")
                .unwrap()["reset"];
            let tag = row["tag"].as_u64().unwrap();
            row["request"]
                .as_str()
                .unwrap()
                .split_once(&format!(" << END{tag}\r\n"))
                .unwrap()
                .1
                .strip_suffix(&format!("\r\nEND{tag}\r\n"))
                .unwrap()
                .to_string()
        };
        let mut server = Server::new(AccessLevel::Program);
        assert_eq!(server.handle("[new] PROJECT NEW COPY").status, 200);
        assert_eq!(
            server
                .handle("[net] DBCREATENET 254 Local Cni nowhere")
                .status,
            200
        );
        let shared = duplicate["shared_oid"].as_str().unwrap().to_string();
        assert_eq!(cross_kind["shared_oid"].as_str().unwrap(), shared);
        let cross_document = retained_document(&cross_kind);
        let parsed = roxmltree::Document::parse(&cross_document).unwrap();
        let application = parsed
            .root_element()
            .children()
            .find(|node| node.has_tag_name("Application"))
            .unwrap();
        let leaf = &cross_document[application.range()];
        // This owned composition combines the captured two-Unit XML order
        // with the captured cross-kind leaf. It is not a new native capture.
        // Importing the complete document establishes registration order;
        // DBADDSAFE followed by private OID edits does not establish it.
        let record = &server.projects["COPY"].networks[&254];
        let literal = retained_document(&duplicate)
            .replace(duplicate["network_oid"].as_str().unwrap(), &record.oid)
            .replace(
                duplicate["interface_oid"].as_str().unwrap(),
                &record.interface_oid,
            )
            .replacen("<Unit>", &format!("{leaf}<Unit>"), 1);
        assert_eq!(
            server
                .handle_document("[xml] DBSETXML //COPY/254", &literal)
                .status,
            301
        );
        assert_eq!(
            server.projects["COPY"].networks[&254].unit_xml_order,
            [20, 21]
        );
        for address in [20, 21] {
            let unit = server
                .projects
                .get_mut("COPY")
                .unwrap()
                .networks
                .get_mut(&254)
                .unwrap()
                .units
                .get_mut(&address)
                .unwrap();
            assert_eq!(unit.oid, shared);
            unit.fields
                .insert("Witness".to_string(), address.to_string());
        }
        let words = [
            "DBCOPYSAFE",
            &format!("!{shared}"),
            "//COPY/254",
            "30",
            "Copied",
        ];
        assert_eq!(
            server.selected_duplicate_unit_path(&shared).as_deref(),
            Some("//COPY/254/p/21")
        );
        assert!(server
            .try_copy_application_safe("copy", &words, &words.join(" "))
            .is_none());
        let result = server.dbcopy("copy", &words);
        assert_eq!(result.status, 301);
        assert_eq!(
            server.projects["COPY"].networks[&254].units[&30].fields["Witness"],
            "21"
        );
        assert_ne!(
            server.projects["COPY"].networks[&254].units[&30].oid,
            shared
        );
    }

    #[test]
    fn copied_null_getter_requires_the_same_absent_value_typed_owner() {
        let mut server = seed();
        let created = server.handle("[null] DBADDSAFE //COPY/254/56/7 Level 4 Null child");
        assert_eq!(created.status, 301, "{created:?}");
        let source_oid = created
            .final_text
            .strip_prefix("301 OID=")
            .unwrap()
            .to_string();
        assert!(server.pending_object("COPY", &source_oid).is_none());
        let source_read = server.handle(&format!("[source-null] DBGET !{source_oid}/Value"));
        assert_eq!(source_read.status, 342, "{source_read:?}");
        assert_eq!(
            source_read.final_text,
            format!("342 !{source_oid}/Value=null")
        );
        let source_xml = server.handle("[source-xml] DBGETXML //COPY/254/56").lines[0].clone();
        let copied = server.handle("[copy] DBCOPYSAFE //COPY/254/56 //COPY/254 80 Copy with null");
        assert_eq!(copied.status, 301, "{copied:?}");
        let document = server.handle("[copied-xml] DBGETXML //COPY/254/80").lines[0].clone();
        let parsed = roxmltree::Document::parse(document.strip_prefix("347-").unwrap()).unwrap();
        let group = parsed
            .root_element()
            .children()
            .find(|node| {
                node.has_tag_name("Group")
                    && node
                        .children()
                        .any(|child| child.has_tag_name("Address") && child.text() == Some("7"))
            })
            .unwrap();
        let null_level = group
            .children()
            .find(|node| {
                node.has_tag_name("Level")
                    && node
                        .children()
                        .any(|child| child.has_tag_name("Address") && child.text() == Some("4"))
            })
            .unwrap();
        assert!(null_level.attribute("Value").is_none());
        let oid = null_level
            .children()
            .find(|node| node.has_tag_name("OID"))
            .unwrap()
            .text()
            .unwrap()
            .to_string();
        let copied_ids = parsed
            .descendants()
            .filter(|node| node.has_tag_name("OID"))
            .map(|node| node.text().unwrap().to_string())
            .collect::<HashSet<_>>();
        let source_document =
            roxmltree::Document::parse(source_xml.strip_prefix("347-").unwrap()).unwrap();
        let source_ids = source_document
            .descendants()
            .filter(|node| node.has_tag_name("OID"))
            .map(|node| node.text().unwrap().to_string())
            .collect::<HashSet<_>>();
        assert!(copied_ids.contains(&oid));
        assert_ne!(oid, source_oid);
        assert_eq!(copied_ids.len(), source_ids.len());
        assert!(copied_ids.is_disjoint(&source_ids));
        let pending = server.pending_object("COPY", &oid).unwrap();
        assert_eq!(pending.path.as_deref(), Some("//COPY/254/80/7/4"));
        assert!(!pending.fields.contains_key("Value"));
        let before = server.project_tables("COPY");
        let known = server.known_oids.clone();
        let response = server.handle(&format!("[copied-null] DBGET !{oid}/Value"));
        assert_eq!(response.status, 342, "{response:?}");
        assert!(response.lines.is_empty());
        assert_eq!(response.final_text, format!("342 !{oid}/Value=null"));
        assert_eq!(server.project_tables("COPY"), before);
        assert_eq!(server.known_oids, known);
        assert_eq!(
            server.handle("[source-again] DBGETXML //COPY/254/56").lines[0],
            source_xml
        );

        // Deliberately poisoned owned states isolate the NULL exception's
        // boundaries. These are not public construction/native profiles.
        for case in [
            "present-empty",
            "typed-raw",
            "typed-number",
            "foreign-project",
            "mismatched-path",
            "netvar",
        ] {
            let mut poisoned = server.clone();
            let key = poisoned.pending_object_key("COPY", &oid).unwrap();
            match case {
                "present-empty" => {
                    poisoned
                        .db_pending
                        .get_mut(&key)
                        .unwrap()
                        .fields
                        .insert("Value".into(), String::new());
                }
                "typed-raw" => {
                    poisoned.level_mut(&oid).unwrap().raw_value = Some("oops".into());
                }
                "typed-number" => {
                    poisoned.level_mut(&oid).unwrap().value = Some(42);
                }
                "foreign-project" => {
                    assert_eq!(poisoned.handle("[other] PROJECT NEW OTHER").status, 200);
                }
                "mismatched-path" => {
                    poisoned.db_pending.get_mut(&key).unwrap().path =
                        Some("//COPY/254/80/7/5".into());
                }
                "netvar" => {
                    poisoned.level_mut(&oid).unwrap().netvar = true;
                }
                _ => unreachable!(),
            }
            let before = poisoned.project_tables("COPY");
            let known = poisoned.known_oids.clone();
            let current = poisoned.current.clone();
            let response = poisoned.handle(&format!("[negative] DBGET !{oid}/Value"));
            assert_eq!(response.status, 401, "{case}: {response:?}");
            assert!(response.lines.is_empty(), "{case}");
            let expected = if case == "foreign-project" {
                "401 Object not found"
            } else {
                "401 Bad object or device ID: Object is null"
            };
            assert_eq!(response.final_text, expected, "{case}");
            assert_eq!(poisoned.project_tables("COPY"), before, "{case}");
            assert_eq!(poisoned.known_oids, known, "{case}");
            assert_eq!(poisoned.current, current, "{case}");
        }
    }

    // Raw DBADD + TagName reaches this reservation without an Address/path.
    // Moving its parent to the actual live Network OID is an owned retained
    // fixture, not a claim that raw DBADD accepts a Network-OID parent.
    fn assert_incomplete_application_name_blocks_copy(network_oid_parent: bool) {
        for source_by_oid in [false, true] {
            for destination_by_oid in [false, true] {
                let mut server = seed();
                let source_oid = server.resolve_db_xml_target("//COPY/254/56").unwrap().oid;
                assert_eq!(server.handle("[save] PROJECT SAVE COPY").status, 200);
                let created = server.handle("[raw] DBADD //COPY/253 Application");
                assert_eq!(created.status, 301, "{created:?}");
                let reserved_oid = created.final_text.strip_prefix("301 OID=").unwrap();
                let assigned =
                    server.handle(&format!("[name] DBSET !{reserved_oid}/TagName Reserved"));
                assert_eq!(assigned.status, 200, "{assigned:?}");
                let network_oid = server.projects["COPY"].networks[&253].oid.clone();
                let parent = if network_oid_parent {
                    format!("!{network_oid}")
                } else {
                    "//COPY/253".to_string()
                };
                if network_oid_parent {
                    server
                        .db_pending
                        .values_mut()
                        .find(|object| object.project == "COPY" && object.oid == reserved_oid)
                        .unwrap()
                        .parent = parent.clone();
                }
                let reserved = server.pending_object("COPY", reserved_oid).unwrap().clone();
                assert_eq!(reserved.parent, parent);
                assert_eq!(reserved.element, "Application");
                assert_eq!(reserved.fields["TagName"], "Reserved");
                assert!(!reserved.fields.contains_key("Address"));
                assert!(reserved.path.is_none());
                assert!(!server.database_address_exists("//COPY/253/80"));
                let source_xml = server.handle("[read] DBGETXML //COPY/254/56");
                assert_eq!(source_xml.status, 200, "{source_xml:?}");
                let destination_xml = server.handle("[read] DBGETXML //COPY/253");
                assert_eq!(destination_xml.status, 200, "{destination_xml:?}");
                let tables = server.project_tables("COPY");
                let projects = server.projects.clone();
                let saved = server.saved_projects.clone();
                let known = server.known_oids.clone();
                let events = server.events.clone();
                let runtime = server.cgl_runtime.clone();
                let source = if source_by_oid {
                    format!("!{source_oid}")
                } else {
                    "//COPY/254/56".to_string()
                };
                let destination = if destination_by_oid {
                    format!("!{network_oid}")
                } else {
                    "//COPY/253".to_string()
                };
                let response = server.handle(&format!(
                    "[copy] DBCOPYSAFE {source} {destination} 80 Reserved"
                ));
                assert_eq!(response.status, 409, "{response:?}");
                assert_eq!(
                    response.final_text,
                    "409 Application TagName already exists"
                );
                assert_eq!(server.project_tables("COPY"), tables);
                assert_eq!(server.projects, projects);
                assert_eq!(server.saved_projects, saved);
                assert_eq!(server.known_oids, known);
                assert_eq!(server.events, events);
                assert_eq!(server.cgl_runtime, runtime);
                assert_eq!(server.current.as_deref(), Some("COPY"));
                assert_eq!(
                    *server.pending_object("COPY", reserved_oid).unwrap(),
                    reserved
                );
                assert!(!server.database_address_exists("//COPY/253/80"));
                assert_eq!(
                    server.resolve_db_xml_target("//COPY/254/56").unwrap().oid,
                    source_oid
                );
                assert_eq!(server.handle("[read] DBGETXML //COPY/254/56"), source_xml);
                assert_eq!(server.handle("[read] DBGETXML //COPY/253"), destination_xml);
                // Rejection precedes snapshotting and identity allocation;
                // NEXT_OID is process-global and intentionally not compared.
            }
        }
    }

    #[test]
    fn incomplete_numeric_network_application_name_reservation_refuses_safe_copy() {
        assert_incomplete_application_name_blocks_copy(false);
    }

    #[test]
    fn incomplete_network_oid_application_name_reservation_refuses_safe_copy() {
        assert_incomplete_application_name_blocks_copy(true);
    }

    #[test]
    fn application_name_reservations_in_other_networks_and_projects_do_not_block_copy() {
        for foreign_project in [false, true] {
            for network_oid_parent in [false, true] {
                let mut server = seed();
                let project = if foreign_project {
                    assert_eq!(server.handle("[other] PROJECT NEW OTHER").status, 200);
                    assert_eq!(
                        server
                            .handle("[net] DBCREATENET 254 Other Cni nowhere")
                            .status,
                        200
                    );
                    "OTHER"
                } else {
                    "COPY"
                };
                let created = server.handle(&format!("[raw] DBADD //{project}/254 Application"));
                assert_eq!(created.status, 301, "{created:?}");
                let reserved_oid = created.final_text.strip_prefix("301 OID=").unwrap();
                assert_eq!(
                    server
                        .handle(&format!("[name] DBSET !{reserved_oid}/TagName Reserved"))
                        .status,
                    200
                );
                if network_oid_parent {
                    let parent = format!("!{}", server.projects[project].networks[&254].oid);
                    server
                        .db_pending
                        .values_mut()
                        .find(|object| object.project == project && object.oid == reserved_oid)
                        .unwrap()
                        .parent = parent;
                }
                assert_eq!(server.handle("[use] PROJECT USE COPY").status, 200);
                let reserved = server
                    .pending_object(project, reserved_oid)
                    .unwrap()
                    .clone();
                assert!(reserved.path.is_none());
                let before_source = server.handle("[read] DBGETXML //COPY/254/56");
                assert_eq!(before_source.status, 200, "{before_source:?}");
                let foreign_tables = foreign_project.then(|| server.project_tables(project));
                let response =
                    server.handle("[copy] DBCOPYSAFE //COPY/254/56 //COPY/253 80 Reserved");
                assert_eq!(response.status, 301, "{response:?}");
                assert_eq!(
                    *server.pending_object(project, reserved_oid).unwrap(),
                    reserved
                );
                if let Some(tables) = foreign_tables {
                    assert_eq!(server.project_tables(project), tables);
                }
                assert_eq!(
                    server.handle("[read] DBGETXML //COPY/254/56"),
                    before_source
                );
                assert_eq!(server.db_fields["//COPY/253/80/TagName"], "Reserved");
                assert_eq!(
                    server.projects["COPY"].networks[&253]
                        .application_creation_order
                        .addresses,
                    [80]
                );
                assert_eq!(
                    server.projects["COPY"].networks[&254]
                        .application_creation_order
                        .addresses,
                    [72, 0, 71, 66, 56]
                );
            }
        }
    }
}
