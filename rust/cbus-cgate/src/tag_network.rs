//! Complete native tag Network records, independent of physical addressing.
//!
//! A runtime name is a string. In particular, the native SAVE DB result for
//! name `42` has Address `42` and NetworkNumber `0xff`; this is not physical
//! network 42. The numeric Network map remains the transport/topology owner.

use std::collections::{BTreeMap, HashSet};

use crate::{err, fresh_oid, xml_escape, Project, Response, Server};

#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
enum TagContent {
    Field(usize),
    Child(usize),
    Retained(usize),
}

#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct TagNode {
    pub element: String,
    pub fields: Vec<(String, String)>,
    #[serde(default, skip_serializing_if = "BTreeMap::is_empty")]
    pub attributes: BTreeMap<String, String>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub children: Vec<TagNode>,
    /// Namespace/comment/structured scalar fragments already retained by the
    /// authoritative native database mapper. Never discard them on NET SAVE.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub retained_xml: Vec<String>,
    /// Native scalar and child order is significant for exact XML readback.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    content_order: Vec<TagContent>,
}

#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct TagNetwork {
    pub root: TagNode,
    /// Existing numeric database tree represented by this authoritative tag
    /// record. This is an association, never a new physical interface binding.
    #[serde(default)]
    pub database_network: Option<u8>,
    #[serde(default)]
    pub created_seq: u64,
}

impl TagNode {
    pub(crate) fn new(element: &str, fields: &[(&str, &str)]) -> Self {
        Self {
            element: element.to_string(),
            fields: fields
                .iter()
                .map(|(k, v)| (k.to_string(), v.to_string()))
                .collect(),
            attributes: BTreeMap::new(),
            children: Vec::new(),
            retained_xml: Vec::new(),
            content_order: (0..fields.len()).map(TagContent::Field).collect(),
        }
    }

    pub(crate) fn field(&self, name: &str) -> Option<&str> {
        self.fields
            .iter()
            .find(|(key, _)| key == name)
            .map(|(_, value)| value.as_str())
            .or_else(|| self.attributes.get(name).map(String::as_str))
            .or_else(|| {
                self.children
                    .iter()
                    .find(|child| child.element == "PP" && child.field("Name") == Some(name))
                    .and_then(|child| child.field("Value"))
            })
    }

    fn set(&mut self, name: &str, value: String) {
        if let Some((_, field)) = self.fields.iter_mut().find(|(key, _)| key == name) {
            *field = value;
        } else if let Some(field) = self.attributes.get_mut(name) {
            *field = value;
        } else if let Some(parameter) = self
            .children
            .iter_mut()
            .find(|child| child.element == "PP" && child.field("Name") == Some(name))
        {
            parameter.attributes.insert("Value".to_string(), value);
        } else if self.element == "Unit"
            && !crate::DB_XML_UNIT_SCALARS.contains(&name)
            && !matches!(name, "OID" | "TagName" | "Address")
        {
            let mut parameter = Self::new("PP", &[]);
            parameter
                .attributes
                .insert("Name".to_string(), name.to_string());
            parameter.attributes.insert("Value".to_string(), value);
            self.push_child(parameter);
        } else if self.element == "Level" && name == "Value" {
            self.attributes.insert(name.to_string(), value);
        } else {
            self.retain_fragments(|fragment| !fragment.starts_with(&format!("<{name}")));
            self.push_field(name.to_string(), value);
        }
    }

    fn push_child(&mut self, child: Self) {
        self.content_order
            .push(TagContent::Child(self.children.len()));
        self.children.push(child);
    }

    fn push_field(&mut self, name: String, value: String) {
        self.content_order
            .push(TagContent::Field(self.fields.len()));
        self.fields.push((name, value));
    }

    fn push_retained(&mut self, xml: String) {
        self.content_order
            .push(TagContent::Retained(self.retained_xml.len()));
        self.retained_xml.push(xml);
    }

    fn retain_children(&mut self, mut keep: impl FnMut(&Self) -> bool) {
        let mut mapping = Vec::new();
        let mut next = 0;
        self.children.retain(|child| {
            let retained = keep(child);
            mapping.push(retained.then_some(next));
            next += usize::from(retained);
            retained
        });
        self.content_order.retain_mut(|entry| match entry {
            TagContent::Child(index) => match mapping.get(*index).copied().flatten() {
                Some(new) => {
                    *index = new;
                    true
                }
                None => false,
            },
            _ => true,
        });
    }

    fn replace_database_children(&mut self, children: Vec<Self>) {
        let selected = |child: &Self| matches!(child.element.as_str(), "Unit" | "Application");
        let old_selected = self.children.iter().map(selected).collect::<Vec<_>>();
        let insertion = self.content_order.iter().position(|entry| {
            matches!(entry, TagContent::Child(index) if old_selected.get(*index) == Some(&true))
        }).unwrap_or_else(|| self.content_order.iter().position(|entry| matches!(entry, TagContent::Retained(_))).unwrap_or(self.content_order.len()));
        let mut removed_before = 0;
        for entry in self.content_order.iter().take(insertion) {
            if matches!(entry, TagContent::Child(index) if old_selected.get(*index) == Some(&true))
            {
                removed_before += 1;
            }
        }
        self.retain_children(|child| !selected(child));
        let start = self.children.len();
        let count = children.len();
        self.children.extend(children);
        self.content_order.splice(
            insertion - removed_before..insertion - removed_before,
            (start..start + count).map(TagContent::Child),
        );
    }

    fn retain_fields(&mut self, mut keep: impl FnMut(&(String, String)) -> bool) {
        let mut mapping = Vec::new();
        let mut next = 0;
        self.fields.retain(|field| {
            let retained = keep(field);
            mapping.push(retained.then_some(next));
            next += usize::from(retained);
            retained
        });
        self.content_order.retain_mut(|entry| match entry {
            TagContent::Field(index) => match mapping.get(*index).copied().flatten() {
                Some(new) => {
                    *index = new;
                    true
                }
                None => false,
            },
            _ => true,
        });
    }

    fn retain_fragments(&mut self, mut keep: impl FnMut(&String) -> bool) {
        let mut mapping = Vec::new();
        let mut next = 0;
        self.retained_xml.retain(|fragment| {
            let retained = keep(fragment);
            mapping.push(retained.then_some(next));
            next += usize::from(retained);
            retained
        });
        self.content_order.retain_mut(|entry| match entry {
            TagContent::Retained(index) => match mapping.get(*index).copied().flatten() {
                Some(new) => {
                    *index = new;
                    true
                }
                None => false,
            },
            _ => true,
        });
    }

    pub(crate) fn document(&self) -> String {
        let mut xml = format!("<{}", self.element);
        for (key, value) in &self.attributes {
            xml.push_str(&format!(" {key}=\"{}\"", xml_escape(value)));
        }
        if self.element == "PP"
            && self.fields.is_empty()
            && self.children.is_empty()
            && self.retained_xml.is_empty()
        {
            xml.push_str("/>");
            return xml;
        }
        xml.push('>');
        let mut fields = vec![false; self.fields.len()];
        let mut children = vec![false; self.children.len()];
        let mut fragments = vec![false; self.retained_xml.len()];
        // Older JSON records have no order metadata. Their established fields,
        // children, fragments order remains the compatibility fallback.
        let fallback = (0..self.fields.len())
            .map(TagContent::Field)
            .chain((0..self.children.len()).map(TagContent::Child))
            .chain((0..self.retained_xml.len()).map(TagContent::Retained));
        for entry in self.content_order.iter().cloned().chain(fallback) {
            match entry {
                TagContent::Field(index) if fields.get(index) == Some(&false) => {
                    let (key, value) = &self.fields[index];
                    xml.push_str(&format!("<{key}>{}</{key}>", xml_escape(value)));
                    fields[index] = true;
                }
                TagContent::Child(index) if children.get(index) == Some(&false) => {
                    xml.push_str(&self.children[index].document());
                    children[index] = true;
                }
                TagContent::Retained(index) if fragments.get(index) == Some(&false) => {
                    xml.push_str(&self.retained_xml[index]);
                    fragments[index] = true;
                }
                _ => {}
            }
        }
        xml.push_str(&format!("</{}>", self.element));
        xml
    }

    pub(crate) fn oids(&self) -> Vec<String> {
        self.field("OID")
            .into_iter()
            .map(str::to_string)
            .chain(self.children.iter().flat_map(Self::oids))
            .collect()
    }

    fn find_oid(&self, oid: &str, indices: &mut Vec<usize>) -> bool {
        if self.field("OID") == Some(oid) {
            return true;
        }
        for (index, child) in self.children.iter().enumerate() {
            indices.push(index);
            if child.find_oid(oid, indices) {
                return true;
            }
            indices.pop();
        }
        false
    }

    fn at(&self, indices: &[usize]) -> &Self {
        indices
            .iter()
            .fold(self, |node, index| &node.children[*index])
    }

    fn at_mut(&mut self, indices: &[usize]) -> &mut Self {
        let mut node = self;
        for index in indices {
            node = &mut node.children[*index];
        }
        node
    }

    fn refresh_oids(&mut self) {
        if self.field("OID").is_some() {
            let oid = fresh_oid();
            if let Some(alias) = self.attributes.get_mut("oid") {
                *alias = oid.clone();
            }
            self.set("OID", oid);
        }
        for child in &mut self.children {
            child.refresh_oids();
        }
    }
}

fn parse_node(node: roxmltree::Node<'_, '_>) -> Result<TagNode, String> {
    if node.tag_name().namespace().is_some() {
        return Err("Namespaced database object is unsupported".to_string());
    }
    let mut result = TagNode::new(node.tag_name().name(), &[]);
    for namespace in node.namespaces() {
        let key = namespace
            .name()
            .map_or_else(|| "xmlns".to_string(), |prefix| format!("xmlns:{prefix}"));
        result.attributes.insert(key, namespace.uri().to_string());
    }
    for attribute in node.attributes() {
        let name = attribute
            .namespace()
            .and_then(|uri| node.lookup_prefix(uri))
            .map_or_else(
                || attribute.name().to_string(),
                |prefix| format!("{prefix}:{}", attribute.name()),
            );
        result
            .attributes
            .insert(name, attribute.value().to_string());
    }
    if node
        .children()
        .any(|child| child.is_text() && !child.text().unwrap_or_default().trim().is_empty())
    {
        return Err("Significant text outside database scalar fields is unsupported".to_string());
    }
    for child in node.children().filter(|c| !c.is_text()) {
        if !child.is_element() || child.tag_name().namespace().is_some() {
            let source = node.document().input_text();
            result.push_retained(if child.is_element() {
                crate::xml_fragment_with_inherited_namespaces(child, source)?
            } else {
                source[child.range()].to_string()
            });
            continue;
        }
        if matches!(
            child.tag_name().name(),
            "Interface"
                | "Property"
                | "Application"
                | "Group"
                | "NetVar"
                | "Level"
                | "Unit"
                | "PP"
                | "TagsDLT"
        ) {
            result.push_child(parse_node(child)?);
        } else if child.children().any(|c| !c.is_text()) || child.attributes().len() != 0 {
            if matches!(
                child.tag_name().name(),
                "OID"
                    | "Address"
                    | "TagName"
                    | "NetworkNumber"
                    | "InterfaceType"
                    | "InterfaceAddress"
                    | "Name"
                    | "Value"
            ) {
                return Err("Database identity scalar must be plain text".to_string());
            }
            result.push_retained(crate::xml_fragment_with_inherited_namespaces(
                child,
                node.document().input_text(),
            )?);
        } else {
            let key = child.tag_name().name();
            if result.fields.iter().any(|(field, _)| field == key)
                && matches!(
                    key,
                    "OID"
                        | "Address"
                        | "TagName"
                        | "NetworkNumber"
                        | "InterfaceType"
                        | "InterfaceAddress"
                        | "Name"
                        | "Value"
                )
            {
                return Err(format!("Duplicate {key}"));
            }
            result.push_field(
                key.to_string(),
                child.children().filter_map(|part| part.text()).collect(),
            );
        }
    }
    Ok(result)
}

impl TagNetwork {
    pub(crate) fn parse(
        document: &str,
        database_network: Option<u8>,
        created_seq: u64,
    ) -> Result<Self, String> {
        if document.len() > 16 * 1024 * 1024
            || document.to_ascii_uppercase().contains("<!DOCTYPE")
            || document.to_ascii_uppercase().contains("<!ENTITY")
        {
            return Err("Unsafe or oversized Network XML".to_string());
        }
        let parsed = roxmltree::Document::parse(document).map_err(|e| e.to_string())?;
        let root = parse_node(parsed.root_element())?;
        if root.element != "Network" {
            return Err("Expected Network root".to_string());
        }
        for field in ["OID", "Address", "TagName", "NetworkNumber"] {
            let value = root
                .field(field)
                .filter(|v| !v.is_empty())
                .ok_or_else(|| format!("Network is missing {field}"))?;
            if field == "OID" && !crate::valid_uuid(value) {
                return Err("Invalid Network OID".to_string());
            }
        }
        if !valid_address(root.field("Address").unwrap_or_default()) {
            return Err("Invalid Network Address".to_string());
        }
        let number = root.field("NetworkNumber").unwrap_or_default();
        if number != "0xff" && number.parse::<u8>().is_err() {
            return Err("Invalid NetworkNumber".to_string());
        }
        let interfaces = root
            .children
            .iter()
            .filter(|child| child.element == "Interface")
            .collect::<Vec<_>>();
        if interfaces.len() != 1 {
            return Err("Network requires exactly one Interface".to_string());
        }
        let interface = interfaces[0];
        for field in ["OID", "InterfaceType", "InterfaceAddress"] {
            if interface.field(field).is_none_or(|v| v.is_empty()) {
                return Err(format!("Interface is missing {field}"));
            }
        }
        for child in &interface.children {
            if child.element != "Property"
                || child.field("OID").is_none()
                || child.field("Name").is_none()
                || child.field("Value").is_none()
            {
                return Err("Invalid Interface Property".to_string());
            }
        }
        for child in parsed
            .root_element()
            .children()
            .filter(|n| n.is_element() && n.tag_name().namespace().is_none())
        {
            match child.tag_name().name() {
                "Unit" => {
                    crate::parse_db_xml_unit(child)?;
                }
                "Application" => {
                    crate::parse_db_xml_object(child)?;
                }
                "OID" | "Address" | "TagName" | "NetworkNumber" | "Interface" | "Description" => {}
                other => return Err(format!("Unsupported Network child {other}")),
            }
        }
        for element in ["Unit", "Application"] {
            let mut addresses = HashSet::new();
            for child in root
                .children
                .iter()
                .filter(|child| child.element == element)
            {
                if !addresses.insert(child.field("Address").unwrap_or_default()) {
                    return Err(format!("Duplicate {element} Address"));
                }
            }
        }
        let mut seen = BTreeMap::new();
        fn identities<'a>(node: &'a TagNode, rows: &mut Vec<(&'a str, &'a str)>) {
            if let Some(oid) = node.field("OID") {
                rows.push((oid, &node.element));
            }
            for child in &node.children {
                identities(child, rows);
            }
        }
        let mut identities_found = Vec::new();
        identities(&root, &mut identities_found);
        for (oid, kind) in identities_found {
            if !crate::valid_uuid(oid) {
                return Err("Invalid subtree OID".to_string());
            }
            if let Some(previous) = seen.insert(oid, kind) {
                if !matches!(
                    (previous, kind),
                    ("Unit" | "Application", "Unit" | "Application")
                ) {
                    return Err("Duplicate subtree OID".to_string());
                }
            }
        }
        Ok(Self {
            root,
            database_network,
            created_seq,
        })
    }

    pub(crate) fn interface(&self) -> &TagNode {
        self.root
            .children
            .iter()
            .find(|child| child.element == "Interface")
            .expect("validated Interface")
    }

    pub(crate) fn options(&self) -> Vec<String> {
        self.interface()
            .children
            .iter()
            .map(|property| {
                format!(
                    "{}={}",
                    property.field("Name").unwrap_or_default(),
                    property.field("Value").unwrap_or_default()
                )
            })
            .collect()
    }
}

fn canonical_address(value: &str) -> Option<u8> {
    value
        .parse::<u8>()
        .ok()
        .filter(|address| address.to_string() == value)
}

pub(crate) fn valid_address(value: &str) -> bool {
    !value.is_empty()
        && !value
            .chars()
            .any(|c| c.is_whitespace() || c.is_control() || matches!(c, '/' | '\\' | '#'))
}

#[derive(Clone)]
struct Selection {
    project: String,
    key: String,
    indices: Vec<usize>,
    field: Option<String>,
}

impl Server {
    fn validate_numeric_tag_source(
        &self,
        project: &str,
        network: &crate::Network,
    ) -> Result<(), String> {
        for unit in network.units.values() {
            let key = self.stored_unit_document_key(project, &unit.oid, unit.address);
            if let Some(template) = self.unit_documents.get(&key) {
                let parsed = roxmltree::Document::parse(template)
                    .map_err(|error| format!("Current Unit template is invalid: {error}"))?;
                for field in parsed.root_element().children().filter(|node| {
                    node.is_element()
                        && node.tag_name().namespace().is_none()
                        && crate::DB_XML_UNIT_SCALARS.contains(&node.tag_name().name())
                }) {
                    if field.children().any(|part| !part.is_text())
                        || field
                            .children()
                            .filter_map(|part| part.text())
                            .collect::<String>()
                            != field.text().unwrap_or_default()
                    {
                        return Err("Structured or segmented numeric Unit scalar cannot be projected losslessly".to_string());
                    }
                }
            }
        }
        Ok(())
    }

    pub(crate) fn current_tag_record(
        &self,
        project: &str,
        name: &str,
    ) -> Result<TagNetwork, String> {
        let mut record = self
            .projects
            .get(project)
            .and_then(|project| project.tag_networks.get(name))
            .ok_or_else(|| "Tag Network not found".to_string())?
            .clone();
        if let Some(address) = record.database_network {
            if let Some(network) = self.projects[project].networks.get(&address) {
                self.validate_numeric_tag_source(project, network)?;
                let document = self.network_xml_document(project, address, network);
                let parsed = roxmltree::Document::parse(&document)
                    .map_err(|error| format!("Current database Network XML is invalid: {error}"))?;
                let current = parse_node(parsed.root_element())?;
                record.root.replace_database_children(
                    current
                        .children
                        .into_iter()
                        .filter(|child| matches!(child.element.as_str(), "Unit" | "Application"))
                        .collect(),
                );
                for fragment in current.retained_xml {
                    if !record.root.retained_xml.contains(&fragment) {
                        record.root.push_retained(fragment);
                    }
                }
            }
        }
        Ok(record)
    }

    pub(crate) fn project_network_documents(&self, project: &str) -> Result<Vec<String>, String> {
        let record = self
            .projects
            .get(project)
            .ok_or_else(|| "Project not found".to_string())?;
        let mut rows = Vec::new();
        for (address, network) in &record.networks {
            if network.oid.is_empty()
                || record
                    .tag_networks
                    .values()
                    .any(|tag| tag.database_network == Some(*address))
            {
                continue;
            }
            rows.push((
                network.created_seq,
                address.to_string(),
                self.network_xml_document(project, *address, network),
            ));
        }
        for name in record.tag_networks.keys() {
            let tag = self.current_tag_record(project, name)?;
            rows.push((tag.created_seq, name.clone(), tag.root.document()));
        }
        rows.sort_by(|left, right| {
            (left.0 == 0, left.0, &left.1).cmp(&(right.0 == 0, right.0, &right.1))
        });
        Ok(rows.into_iter().map(|(_, _, document)| document).collect())
    }

    pub(crate) fn save_tag_definition(
        &mut self,
        project: &str,
        name: &str,
        interface_type: &str,
        interface_address: &str,
        options: &[String],
    ) -> Result<(), String> {
        let mut record = if self.projects[project].tag_networks.contains_key(name) {
            self.current_tag_record(project, name)?
        } else if let Some((address, network)) = name
            .parse::<u8>()
            .ok()
            .filter(|address| address.to_string() == name)
            .and_then(|address| {
                self.projects[project]
                    .networks
                    .get(&address)
                    .filter(|network| {
                        !network.oid.is_empty()
                            && !self.projects[project]
                                .tag_networks
                                .values()
                                .any(|tag| tag.database_network == Some(address))
                    })
                    .map(|network| (address, network))
            })
        {
            self.validate_numeric_tag_source(project, network)?;
            let document = self.network_xml_document(project, address, network);
            let parsed =
                roxmltree::Document::parse(&document).map_err(|error| error.to_string())?;
            // An already-owned numeric tree can include legacy partial Unit
            // rows. Saving interface metadata preserves that tree; it is not
            // a new complete DBSETXML submission that may reject old rows.
            TagNetwork {
                root: parse_node(parsed.root_element())?,
                database_network: Some(address),
                created_seq: network.created_seq,
            }
        } else {
            let oid = fresh_oid();
            let interface_oid = fresh_oid();
            let mut root = TagNode::new(
                "Network",
                &[
                    ("OID", &oid),
                    ("TagName", &format!("n{name}")),
                    ("Address", name),
                    ("NetworkNumber", "0xff"),
                ],
            );
            root.push_child(TagNode::new(
                "Interface",
                &[
                    ("OID", &interface_oid),
                    ("InterfaceType", interface_type),
                    ("InterfaceAddress", interface_address),
                ],
            ));
            TagNetwork {
                root,
                database_network: None,
                created_seq: crate::next_network_seq(&self.projects[project]),
            }
        };
        let interface = record
            .root
            .children
            .iter_mut()
            .find(|node| node.element == "Interface")
            .expect("Interface");
        interface.set("InterfaceType", interface_type.to_string());
        interface.set("InterfaceAddress", interface_address.to_string());
        // Native tokenization splits whitespace and '=' into sequential pairs;
        // a lone flag yields no Property, duplicate keys remain ordered, and
        // every SAVE creates fresh Property identities.
        interface.retain_children(|_| false);
        let tokens = options.join(" ").replace('=', " ");
        let mut tokens = tokens.split_whitespace();
        while let (Some(name), Some(value)) = (tokens.next(), tokens.next()) {
            interface.push_child(TagNode::new(
                "Property",
                &[("OID", &fresh_oid()), ("Name", name), ("Value", value)],
            ));
        }
        let old_oids = self.projects[project]
            .tag_networks
            .get(name)
            .map(|record| record.root.oids())
            .unwrap_or_default();
        self.register_tag_network(project, record);
        self.retire_inactive_db_oids(&old_oids);
        Ok(())
    }

    fn tag_selection(&self, path: &str) -> Result<Option<Selection>, String> {
        let Some(project) = self.current.as_deref() else {
            return Ok(None);
        };
        let Some(record) = self.projects.get(project) else {
            return Ok(None);
        };
        if let Some(rest) = path.strip_prefix('!') {
            let (oid, field) = rest
                .split_once('/')
                .map_or((rest, None), |(oid, field)| (oid, Some(field.to_string())));
            // Numeric database descendants retain their established OID
            // owner, including modeled duplicate selection and deletion
            // invalidation. A materialized XML snapshot must not replace
            // those rules with its first depth-first matching node.
            if self
                .invalidated_unit_oid_lookups
                .contains(&(project.to_string(), oid.to_string()))
                || record
                    .networks
                    .values()
                    .any(|network| network.units.values().any(|unit| unit.oid == oid))
                || self
                    .db_pending
                    .values()
                    .any(|object| object.project == project && object.oid == oid)
                || self.level_key(oid).is_some()
            {
                return Ok(None);
            }
            for key in record.tag_networks.keys() {
                let network = self.current_tag_record(project, key)?;
                let mut indices = Vec::new();
                if network.root.find_oid(oid, &mut indices) {
                    return Ok(Some(Selection {
                        project: project.to_string(),
                        key: key.clone(),
                        indices,
                        field,
                    }));
                }
            }
            return Ok(None);
        }
        let Some(relative) = path
            .strip_prefix(&format!("//{project}/"))
            .or_else(|| (!path.starts_with("//")).then_some(path))
        else {
            return Ok(None);
        };
        let mut parts = relative.split('/');
        let Some(key) = parts.next() else {
            return Ok(None);
        };
        if !record.tag_networks.contains_key(key) {
            return Ok(None);
        }
        let network = self.current_tag_record(project, key)?;
        let mut node = &network.root;
        let mut indices = Vec::new();
        let tokens = parts.collect::<Vec<_>>();
        let mut offset = 0;
        while offset < tokens.len() {
            let token = tokens[offset];
            if offset + 1 == tokens.len()
                && (node.field(token).is_some()
                    || !node.children.iter().any(|child| {
                        child.field("Address") == Some(token)
                            || child.field("Name") == Some(token)
                            || child.element == token
                    }))
            {
                return Ok(Some(Selection {
                    project: project.to_string(),
                    key: key.to_string(),
                    indices,
                    field: Some(token.to_string()),
                }));
            }
            let (element, address, consumed) = if token == "p" {
                (Some("Unit"), tokens.get(offset + 1).copied(), 2)
            } else if token == "Interface" {
                (Some("Interface"), None, 1)
            } else {
                (None, Some(token), 1)
            };
            let Some(index) = node.children.iter().position(|child| {
                element.is_none_or(|e| child.element == e)
                    && address.is_none_or(|a| {
                        child.field("Address") == Some(a) || child.field("Name") == Some(a)
                    })
            }) else {
                return if network
                    .database_network
                    .is_some_and(|address| address.to_string() == key)
                {
                    Ok(None)
                } else {
                    Err("Named Network descendant not found".to_string())
                };
            };
            indices.push(index);
            node = &node.children[index];
            offset += consumed;
        }
        Ok(Some(Selection {
            project: project.to_string(),
            key: key.to_string(),
            indices,
            field: None,
        }))
    }

    fn unselected_tag_target(&self, path: &str) -> bool {
        if let Some(rest) = path.strip_prefix("//") {
            let mut parts = rest.split('/');
            let (Some(project), Some(key)) = (parts.next(), parts.next()) else {
                return false;
            };
            return self.current.as_deref() != Some(project)
                && self
                    .projects
                    .get(project)
                    .is_some_and(|record| record.tag_networks.contains_key(key));
        }
        let Some(rest) = path.strip_prefix('!') else {
            // Bare paths retain the existing selected-project/opaque store
            // boundary. An unrelated project's name is not an implicit
            // qualification of such a path.
            return false;
        };
        let oid = rest.split('/').next().unwrap_or_default();
        if self.oid_in_current_project(oid) {
            // Copies can share OIDs. The selected ordinary database owner
            // retains its established dispatch even if another project has
            // materialized the same identity.
            return false;
        }
        self.projects.iter().any(|(project, record)| {
            self.current.as_deref() != Some(project)
                && record.tag_networks.iter().any(|(key, network)| {
                    self.current_tag_record(project, key)
                        .map(|current| current.root.oids())
                        .unwrap_or_else(|_| network.root.oids())
                        .iter()
                        .any(|candidate| candidate == oid)
                })
        })
    }

    pub(crate) fn independent_tag_target(&self, path: &str) -> bool {
        let path = path.strip_prefix("/db").unwrap_or(path);
        if let Some(rest) = path.strip_prefix('!') {
            let oid = rest.split('/').next().unwrap_or_default();
            return self
                .current
                .as_ref()
                .and_then(|name| self.projects.get(name))
                .is_some_and(|project| {
                    project.tag_networks.values().any(|record| {
                        record.database_network.is_none()
                            && record.root.oids().iter().any(|candidate| candidate == oid)
                    })
                });
        }
        let parts = path.trim_start_matches('/').split('/').collect::<Vec<_>>();
        let (project, name) = if path.starts_with("//") {
            match parts.as_slice() {
                [project, name, ..] => (*project, *name),
                _ => return false,
            }
        } else {
            match parts.as_slice() {
                [project, name, ..] if self.projects.contains_key(*project) => (*project, *name),
                [name, ..] => (self.current.as_deref().unwrap_or_default(), *name),
                _ => return false,
            }
        };
        self.projects
            .get(project)
            .and_then(|project| project.tag_networks.get(name))
            .is_some_and(|record| record.database_network.is_none())
    }

    pub(crate) fn tag_network_oids(project: &Project) -> Vec<String> {
        project
            .tag_networks
            .values()
            .flat_map(|record| {
                if record.database_network.is_some() {
                    // Numeric database children have their own current ownership
                    // census. Snapshot copies must not resurrect deleted child OIDs.
                    record
                        .root
                        .field("OID")
                        .into_iter()
                        .map(str::to_string)
                        .chain(record.interface().oids())
                        .collect::<Vec<_>>()
                } else {
                    record.root.oids()
                }
            })
            .collect()
    }

    pub(crate) fn register_tag_network(&mut self, project: &str, record: TagNetwork) {
        let key = record
            .root
            .field("Address")
            .expect("validated Address")
            .to_string();
        for oid in record.root.oids() {
            self.known_oids.insert(oid.clone());
            self.objects.insert(format!("!{oid}"));
        }
        self.objects.insert(format!("//{project}/{key}"));
        self.projects
            .get_mut(project)
            .expect("validated project")
            .tag_networks
            .insert(key, record);
    }

    /// Synchronize the existing numeric *database* children while keeping its
    /// transport-facing address/interface and volatile fields exactly intact.
    pub(crate) fn sync_tag_database_children(
        &mut self,
        project: &str,
        key: &str,
    ) -> Result<(), String> {
        let record = self.projects[project].tag_networks[key].clone();
        let Some(address) = record.database_network else {
            return Ok(());
        };
        let Some(previous) = self.projects[project].networks.get(&address).cloned() else {
            return Ok(());
        };
        let mut normalized = record.root;
        normalized.set("Address", address.to_string());
        normalized.set("NetworkNumber", address.to_string());
        normalized.retain_fields(|(name, _)| name != "Description");
        normalized.retain_fragments(|fragment| !fragment.starts_with("<Description"));
        let interface = normalized
            .children
            .iter_mut()
            .find(|c| c.element == "Interface")
            .expect("Interface");
        interface.set("InterfaceType", previous.iface_type.clone());
        interface.set("InterfaceAddress", previous.iface_addr.clone());
        interface.retain_children(|_| false);
        let document = normalized.document();
        let parsed = roxmltree::Document::parse(&document).map_err(|e| e.to_string())?;
        let object = crate::parse_db_xml_object(parsed.root_element())?;
        let target = self
            .resolve_db_xml_target(&format!("//{project}/{address}"))
            .map_err(|(_, e)| e)?;
        // The staged overlay is the same owning tree, not a foreign OID
        // claimant. Remove only that record while the numeric mapper checks
        // every other active record; restore it on either result.
        let overlay = self
            .projects
            .get_mut(project)
            .expect("project")
            .tag_networks
            .remove(key)
            .expect("overlay");
        let result = self
            .apply_db_xml_replacement(&target, &object)
            .map_err(|(_, e)| e);
        self.projects
            .get_mut(project)
            .expect("project")
            .tag_networks
            .insert(key.to_string(), overlay);
        result
    }

    pub(crate) fn tag_database_command(&mut self, tag: &str, words: &[&str]) -> Option<Response> {
        let verb = words.first()?.to_ascii_uppercase();
        if !matches!(
            verb.as_str(),
            "GET"
                | "DBGET"
                | "DBGETXML"
                | "DBSET"
                | "DBSETSAFE"
                | "DBDELETE"
                | "DBRENAMENET"
                | "DBRENAMENETSAFE"
                | "DBCOPY"
                | "DBCOPYSAFE"
                | "DBADD"
                | "DBADDSAFE"
        ) {
            return None;
        }
        let path = words.get(1)?;
        let selected = match self.tag_selection(path) {
            Ok(Some(selected)) => selected,
            Ok(None) => {
                // Known tag targets require explicit project selection.
                // Letting mutation fall through to the legacy opaque scalar
                // store would acknowledge success without editing the tree.
                if matches!(
                    verb.as_str(),
                    "DBSET"
                        | "DBSETSAFE"
                        | "DBDELETE"
                        | "DBRENAMENET"
                        | "DBRENAMENETSAFE"
                        | "DBCOPY"
                        | "DBCOPYSAFE"
                        | "DBADD"
                        | "DBADDSAFE"
                ) && self.unselected_tag_target(path)
                {
                    return Some(err(tag, 401, "401 Object not found"));
                }
                return None;
            }
            Err(error) => return Some(err(tag, 408, &format!("408 Operation failed: {error}"))),
        };
        let record = match self.current_tag_record(&selected.project, &selected.key) {
            Ok(record) => record,
            Err(error) => return Some(err(tag, 408, &format!("408 Operation failed: {error}"))),
        };
        let node = if selected.indices.is_empty()
            && matches!(
                selected.field.as_deref(),
                Some("InterfaceType" | "InterfaceAddress")
            ) {
            record.interface()
        } else {
            record.root.at(&selected.indices)
        };
        if verb == "GET" {
            // This retained refusal is a runtime property boundary, not a
            // projection of database scalar fields into the GET namespace.
            if words.len() == 3
                && words[2].eq_ignore_ascii_case("NetworkNumber")
                && selected.indices.is_empty()
                && selected.field.is_none()
                && (path.starts_with("//") || path.starts_with('!'))
            {
                return Some(err(tag,402,&format!("402 Operation not supported by: //{}/{} (Parameter networknumber not found)",selected.project,selected.key)));
            }
            return None;
        }
        if matches!(verb.as_str(), "DBGET" | "DBGETXML") {
            if words.len() != 2 {
                return Some(err(tag, 400, "400 Syntax Error."));
            }
            if verb == "DBGETXML" {
                return Some(if selected.field.is_none() {
                    Self::db_xml_response(tag, node.document())
                } else {
                    err(tag, 401, "401 Object not found")
                });
            }
            return Some(if let Some(field) = selected.field {
                let Some(value) = node.field(&field) else {
                    return Some(err(tag, 401, "401 Object not found"));
                };
                let output_path = if selected.indices.is_empty() {
                    path.strip_prefix(&format!("//{}/", selected.project))
                        .unwrap_or(path)
                } else {
                    path
                };
                Response {
                    tag: tag.to_string(),
                    lines: Vec::new(),
                    final_text: format!("342 {output_path}={value}"),
                    status: 342,
                }
            } else {
                Response {
                    tag: tag.to_string(),
                    lines: node
                        .fields
                        .iter()
                        .map(|(k, v)| format!("342-{path}/{k}={v}"))
                        .collect(),
                    final_text: "200 OK".to_string(),
                    status: 200,
                }
            });
        }
        if matches!(verb.as_str(), "DBSET" | "DBSETSAFE")
            && selected.field.as_deref() == Some("OID")
        {
            return Some(err(
                tag,
                408,
                "408 Operation failed: OID field can not be changed",
            ));
        }
        if matches!(verb.as_str(), "DBADD" | "DBADDSAFE")
            && record
                .database_network
                .is_some_and(|address| address.to_string() == selected.key)
        {
            // Existing numeric children retain their established pending and
            // typed creation owner. Reads rehydrate from that current owner.
            return None;
        }
        if matches!(verb.as_str(), "DBADD" | "DBADDSAFE") {
            // Incomplete child creation has a separate native pending-object
            // contract. Do not acknowledge a dropped or invented child.
            return Some(err(tag,408,"408 Operation failed: incomplete child creation in a named Network is unsupported; submit complete DBSETXML"));
        }
        if let Some(address) = record.database_network {
            if (node.element == "Unit"
                || (path.starts_with('!')
                    && matches!(
                        node.element.as_str(),
                        "Application" | "Group" | "Level" | "NetVar"
                    ))
                || (matches!(node.element.as_str(), "Application" | "Group")
                    && selected.field.as_deref() == Some("TagName")))
                && matches!(verb.as_str(), "DBSET" | "DBSETSAFE" | "DBDELETE")
            {
                // The existing database owner also mirrors Application/Group
                // TagName edits. Replacing the whole Network for that scalar
                // would re-admit untouched imported Units under strict
                // DBSETXML rules that reject legacy PP decorations.
                let mut path = format!("//{}/{address}", selected.project);
                let mut current = &record.root;
                for index in &selected.indices {
                    current = &current.children[*index];
                    if current.element == "Unit" {
                        path.push_str("/p");
                    }
                    path.push('/');
                    path.push_str(current.field("Address").unwrap_or_default());
                }
                if let Some(field) = &selected.field {
                    path.push('/');
                    path.push_str(field);
                }
                let mut rewritten = words.to_vec();
                if !words[1].starts_with('!') {
                    rewritten[1] = &path;
                }
                return Some(match verb.as_str() {
                    "DBSET" => self.dbset_unsafe(tag, &rewritten),
                    "DBSETSAFE" => self.dbset(tag, &rewritten),
                    "DBDELETE" => self.dbdelete(tag, &rewritten),
                    _ => unreachable!(),
                });
            }
        }
        let mut staged = self.clone();
        let result = match verb.as_str() {
            "DBSET" | "DBSETSAFE" => {
                if let Some(field) = selected.field.as_deref() {
                    if words.len() < 3 && verb == "DBSETSAFE" {
                        Err("Field value required".to_string())
                    } else {
                        let value = words.get(2..).unwrap_or_default().join(" ");
                        let mut replacement = record.clone();
                        if selected.indices.is_empty()
                            && matches!(field, "InterfaceType" | "InterfaceAddress")
                        {
                            replacement
                                .root
                                .children
                                .iter_mut()
                                .find(|node| node.element == "Interface")
                                .expect("Interface")
                                .set(field, value);
                        } else {
                            replacement.root.at_mut(&selected.indices).set(field, value);
                        }
                        staged
                            .replace_tag_record(&selected.project, &selected.key, replacement)
                            .map(|()| "200 OK.".to_string())
                    }
                } else {
                    Err("A scalar field is required".to_string())
                }
            }

            "DBDELETE" => {
                if words.len() != 2 || selected.field.is_some() {
                    Err("Object required".to_string())
                } else if selected.indices.is_empty() {
                    staged
                        .delete_tag_record(&selected.project, &selected.key, &record)
                        .map(|()| "200 OK.".to_string())
                } else {
                    let mut replacement = record.clone();
                    let (last, parent) = selected.indices.split_last().expect("child");
                    let mut index = 0;
                    replacement.root.at_mut(parent).retain_children(|_| {
                        let keep = index != *last;
                        index += 1;
                        keep
                    });
                    staged
                        .replace_tag_record(&selected.project, &selected.key, replacement)
                        .map(|()| "200 OK.".to_string())
                }
            }
            "DBRENAMENET" | "DBRENAMENETSAFE" => {
                if words.len() != 3
                    || !selected.indices.is_empty()
                    || selected.field.is_some()
                    || (verb == "DBRENAMENETSAFE" && words[2].parse::<u8>().is_err())
                {
                    Err("Invalid network rename".to_string())
                } else {
                    let mut replacement = record.clone();
                    replacement.root.set("Address", words[2].to_string());
                    staged
                        .replace_tag_record(&selected.project, &selected.key, replacement)
                        .map(|()| "200 OK.".to_string())
                }
            }
            "DBCOPY" | "DBCOPYSAFE" => {
                if !selected.indices.is_empty()
                    || selected.field.is_some()
                    || !(3..=5).contains(&words.len())
                {
                    Err("Invalid Network copy".to_string())
                } else {
                    let destination = words[2].trim_start_matches("//");
                    if destination.contains('/') || !staged.projects.contains_key(destination) {
                        Err("Destination project not found".to_string())
                    } else if destination == selected.project && verb == "DBCOPY" {
                        Err("Same-project incomplete Network copy is unsupported; use complete DBCOPYSAFE".to_string())
                    } else {
                        let mut replacement = record.clone();
                        replacement.database_network = None;
                        replacement.created_seq =
                            crate::next_network_seq(&staged.projects[destination]);
                        replacement.root.refresh_oids();
                        if verb == "DBCOPYSAFE" {
                            if words.len() != 5 {
                                return Some(err(tag, 400, "400 Syntax Error."));
                            }
                            replacement.root.set("Address", words[3].to_string());
                            replacement.root.set("TagName", words[4].to_string());
                        }
                        staged.insert_tag_copy(destination, replacement)
                    }
                }
            }
            _ => unreachable!(),
        };
        Some(match result {
            Ok(text) => {
                *self = staged;
                let status = if text.starts_with("301") { 301 } else { 200 };
                Response {
                    tag: tag.to_string(),
                    lines: Vec::new(),
                    final_text: text,
                    status,
                }
            }
            Err(message) => err(tag, 408, &format!("408 Operation failed: {message}")),
        })
    }

    fn delete_tag_record(
        &mut self,
        project: &str,
        key: &str,
        record: &TagNetwork,
    ) -> Result<(), String> {
        let mut old_oids = record.root.oids().into_iter().collect::<HashSet<_>>();
        if let Some(address) = record.database_network {
            let target = self
                .resolve_db_xml_target(&format!("//{project}/{address}"))
                .map_err(|(_, error)| error)?;
            old_oids.extend(self.db_xml_subtree_oids(&target));
            // Incomplete native DBADD children have no addressed XML path.
            // Follow their selected-project parent ownership transitively so
            // the same owner's cleanup also removes those pending records.
            let prefix = format!("{}/", target.path);
            loop {
                let previous = old_oids.len();
                let pending = self
                    .db_pending
                    .values()
                    .filter(|object| {
                        object.project == project
                            && (object.parent == target.path
                                || object.parent.starts_with(&prefix)
                                || object
                                    .parent
                                    .strip_prefix('!')
                                    .is_some_and(|oid| old_oids.contains(oid)))
                    })
                    .map(|object| object.oid.clone())
                    .collect::<Vec<_>>();
                old_oids.extend(pending);
                if old_oids.len() == previous {
                    break;
                }
            }
            // The established numeric owner retires every side table as well
            // as the Network: pending application/group/level records, scalar
            // fields, Unit documents/PP and XML decorations must not survive.
            self.remove_db_xml_subtree(&target, &old_oids);
        }
        self.projects
            .get_mut(project)
            .expect("project")
            .tag_networks
            .remove(key);
        self.retire_inactive_db_oids(&old_oids.into_iter().collect::<Vec<_>>());
        Ok(())
    }

    fn insert_tag_copy(&mut self, project: &str, record: TagNetwork) -> Result<String, String> {
        // Caller-provided Address/TagName must satisfy complete authoritative
        // record admission before its key or fresh OIDs become observable.
        let validated = TagNetwork::parse(&record.root.document(), None, record.created_seq)?;
        let key = validated
            .root
            .field("Address")
            .expect("Address")
            .to_string();
        if self.projects[project].tag_networks.contains_key(&key)
            || canonical_address(&key)
                .is_some_and(|address| self.projects[project].networks.contains_key(&address))
        {
            return Err("Destination Network already exists".to_string());
        }
        let oid = validated.root.field("OID").expect("OID").to_string();
        self.register_tag_network(project, validated);
        Ok(format!("301 OID={oid}"))
    }

    fn replace_tag_record(
        &mut self,
        project: &str,
        key: &str,
        record: TagNetwork,
    ) -> Result<(), String> {
        let validated = TagNetwork::parse(
            &record.root.document(),
            record.database_network,
            record.created_seq,
        )?;
        let address = validated.root.field("Address").expect("Address");
        if address != key
            && (self.projects[project].tag_networks.contains_key(address)
                || canonical_address(address)
                    .is_some_and(|a| self.projects[project].networks.contains_key(&a)))
        {
            return Err("Destination Network already exists".to_string());
        }
        let old = self.current_tag_record(project, key)?;
        let own = old.root.oids().into_iter().collect::<HashSet<_>>();
        if validated
            .root
            .oids()
            .iter()
            .any(|oid| !own.contains(oid) && self.active_db_oids(project).contains(oid))
        {
            return Err("OID already exists in selected project".to_string());
        }
        let address = address.to_string();
        self.projects
            .get_mut(project)
            .expect("project")
            .tag_networks
            .remove(key);
        self.register_tag_network(project, validated);
        self.sync_tag_database_children(project, &address)?;
        self.retire_inactive_db_oids(&old.root.oids());
        Ok(())
    }

    pub(crate) fn tag_database_document(
        &mut self,
        tag: &str,
        path: &str,
        document: &str,
    ) -> Option<Response> {
        let selected = match self.tag_selection(path) {
            Ok(Some(selected)) => selected,
            Ok(None) => return None,
            Err(error) => return Some(err(tag, 408, &format!("408 Operation failed: {error}"))),
        };
        if selected.field.is_some() {
            return None;
        }
        if document.len() > 16 * 1024 * 1024
            || document.to_ascii_uppercase().contains("<!DOCTYPE")
            || document.to_ascii_uppercase().contains("<!ENTITY")
        {
            return Some(err(tag, 400, "400 Unsafe or oversized XML"));
        }
        let record = match self.current_tag_record(&selected.project, &selected.key) {
            Ok(record) => record,
            Err(error) => return Some(err(tag, 408, &format!("408 Operation failed: {error}"))),
        };
        let parsed = roxmltree::Document::parse(document);
        let replacement = match parsed.and_then(|doc| {
            parse_node(doc.root_element()).map_err(|_| roxmltree::Error::NoRootNode)
        }) {
            Ok(node) => node,
            Err(error) => return Some(err(tag, 446, &format!("446 Unable to set XML: {error}"))),
        };
        if replacement.element != record.root.at(&selected.indices).element {
            return Some(err(tag, 400, "400 Object type mismatch"));
        }
        let oid = replacement.field("OID").unwrap_or_default().to_string();
        let mut record = record;
        *record.root.at_mut(&selected.indices) = replacement;
        let mut staged = self.clone();
        Some(
            match staged.replace_tag_record(&selected.project, &selected.key, record) {
                Ok(()) => {
                    *self = staged;
                    Response {
                        tag: tag.to_string(),
                        lines: Vec::new(),
                        final_text: format!("301 OID={oid}"),
                        status: 301,
                    }
                }
                Err(message) => err(tag, 408, &format!("408 Operation failed: {message}")),
            },
        )
    }
}
