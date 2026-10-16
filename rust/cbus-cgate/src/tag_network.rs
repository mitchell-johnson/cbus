//! Native tag Network records, independent of physical addressing.
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
    #[serde(default, skip_serializing_if = "std::ops::Not::not")]
    saved_level_tags_pending: bool,
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
            // Incomplete native identities still have schema order, regardless
            // of whether the caller supplied Address or TagName first.
            if matches!(name, "TagName" | "Address") {
                let added = self.fields.len() - 1;
                self.content_order
                    .retain(|entry| *entry != TagContent::Field(added));
                let position = self
                    .content_order
                    .iter()
                    .enumerate()
                    .filter_map(|(position, entry)| match entry {
                        TagContent::Field(index)
                            if self.fields[*index].0 == "OID"
                                || (name == "Address" && self.fields[*index].0 == "TagName") =>
                        {
                            Some(position + 1)
                        }
                        _ => None,
                    })
                    .max()
                    .unwrap_or(0);
                self.content_order
                    .insert(position, TagContent::Field(added));
            }
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
        if matches!(self.element.as_str(), "PP" | "TagsDLT")
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

    fn clear_copy_identities(&mut self) {
        if matches!(
            self.element.as_str(),
            "Network" | "Application" | "Group" | "NetVar" | "Level"
        ) {
            self.retain_fields(|(key, _)| !matches!(key.as_str(), "Address" | "TagName"));
            self.attributes.remove("Address");
            self.attributes.remove("TagName");
        }
        for child in &mut self.children {
            child.clear_copy_identities();
        }
    }

    fn null_tag_name(&self) -> bool {
        (matches!(
            self.element.as_str(),
            "Network" | "Application" | "Group" | "NetVar" | "Level"
        ) && self.field("TagName").is_none())
            || self.children.iter().any(Self::null_tag_name)
    }

    fn null_level_value(&self) -> bool {
        (self.element == "Level" && self.field("Value").is_none())
            || self.children.iter().any(Self::null_level_value)
    }

    fn untyped_level_value(&self) -> bool {
        (self.element == "Level"
            && self
                .field("Value")
                .is_some_and(|value| value.parse::<u8>().is_err()))
            || self.children.iter().any(Self::untyped_level_value)
    }

    fn materialize_level_tags(&mut self) {
        if self.element == "Level"
            && !self.children.iter().any(|child| child.element == "TagsDLT")
            && !self
                .retained_xml
                .iter()
                .any(|xml| xml.starts_with("<TagsDLT"))
        {
            self.push_child(Self::new("TagsDLT", &[]));
        }
        for child in &mut self.children {
            child.materialize_level_tags();
        }
    }

    fn needs_level_tags(&self) -> bool {
        (self.element == "Level"
            && !self.children.iter().any(|child| child.element == "TagsDLT")
            && !self
                .retained_xml
                .iter()
                .any(|xml| xml.starts_with("<TagsDLT")))
            || self.children.iter().any(Self::needs_level_tags)
    }

    fn unprobed_copy_payload(&self) -> bool {
        self.element == "Unit"
            || self.retained_xml.iter().any(|fragment| {
                // Structured fragments remain losslessly owned, but copying
                // hidden identities without a modeled census would falsely
                // promise a fresh closure. Refuse this unprobed form intact.
                let wrapped = format!("<fragment>{fragment}</fragment>");
                roxmltree::Document::parse(&wrapped).map_or(true, |document| {
                    document.descendants().any(|node| {
                        node.is_element()
                            && (node.tag_name().name() == "OID"
                                || node
                                    .attributes()
                                    .any(|attribute| attribute.name().eq_ignore_ascii_case("oid")))
                    })
                })
            })
            || self.children.iter().any(Self::unprobed_copy_payload)
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
                | "Languages"
                | "Language"
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

/// Complete native Network language rows. The Toolkit language agent uses
/// these ID/TagValue objects separately from Group/Level TagsDLT labels.
pub(crate) fn parse_network_languages(node: roxmltree::Node<'_, '_>) -> Result<String, String> {
    let collection = parse_node(node)?;
    if collection.element != "Languages"
        || !collection.attributes.is_empty()
        || !collection.retained_xml.is_empty()
        || collection.fields.iter().any(|(name, _)| name != "OID")
        || collection
            .field("OID")
            .is_none_or(|oid| !crate::valid_uuid(oid))
    {
        return Err("Invalid Network Languages collection".to_string());
    }
    for row in &collection.children {
        if row.element != "Language"
            || !row.attributes.is_empty()
            || !row.children.is_empty()
            || !row.retained_xml.is_empty()
            || row
                .fields
                .iter()
                .any(|(name, _)| !matches!(name.as_str(), "OID" | "ID" | "TagValue"))
            || row.field("OID").is_none_or(|oid| !crate::valid_uuid(oid))
            || row.field("ID").is_none_or(|id| id.parse::<i32>().is_err())
            || row.field("TagValue").is_none()
            || ["OID", "ID", "TagValue"]
                .iter()
                .any(|name| row.fields.iter().filter(|(key, _)| key == name).count() != 1)
        {
            return Err("Invalid Network Language row".to_string());
        }
    }
    Ok(collection.document())
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
                "Languages" => {
                    parse_network_languages(child)?;
                }
                "OID" | "Address" | "TagName" | "NetworkNumber" | "Interface" | "Description" => {}
                other => return Err(format!("Unsupported Network child {other}")),
            }
        }
        if root
            .children
            .iter()
            .filter(|child| child.element == "Languages")
            .count()
            > 1
        {
            return Err("Duplicate Network Languages collection".to_string());
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
            saved_level_tags_pending: false,
        })
    }

    #[cfg(test)]
    pub(crate) fn interface(&self) -> &TagNode {
        self.optional_interface().expect("validated Interface")
    }

    pub(crate) fn optional_interface(&self) -> Option<&TagNode> {
        self.root
            .children
            .iter()
            .find(|child| child.element == "Interface")
    }

    pub(crate) fn options(&self) -> Vec<String> {
        self.optional_interface()
            .into_iter()
            .flat_map(|interface| &interface.children)
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

fn child_type(token: &str) -> bool {
    matches!(
        token,
        "Interface"
            | "Property"
            | "Application"
            | "Group"
            | "NetVar"
            | "Level"
            | "Unit"
            | "TagsDLT"
            | "TagDLT"
            | "Languages"
            | "Language"
    )
}

fn indexed_type(token: &str) -> Option<(&str, usize)> {
    let (kind, index) = token.split_once('[')?;
    child_type(kind).then_some(())?;
    let index = index.strip_suffix(']')?.parse::<usize>().ok()?;
    (index > 0).then_some((kind, index - 1))
}

fn walk_tag_path(
    root: &TagNode,
    mut indices: Vec<usize>,
    suffix: &str,
    allow_application_coordinates: bool,
) -> Result<(Vec<usize>, Option<String>), String> {
    let tokens = suffix
        .split('/')
        .filter(|part| !part.is_empty())
        .collect::<Vec<_>>();
    // Keep the exact Address/Name winner across all siblings. A canonical
    // Application coordinate is only a fallback for a typed numeric owner.
    let child_by_coordinate = |node: &TagNode, token: &str| {
        node.children
            .iter()
            .position(|child| {
                child.field("Address") == Some(token) || child.field("Name") == Some(token)
            })
            .or_else(|| {
                if !allow_application_coordinates {
                    return None;
                }
                let address = token
                    .parse::<u8>()
                    .ok()
                    .filter(|address| address.to_string() == token)?;
                node.children.iter().position(|child| {
                    child.element == "Application"
                        && child
                            .field("Address")
                            .and_then(|value| value.parse::<u8>().ok())
                            == Some(address)
                })
            })
    };
    let mut offset = 0;
    while offset < tokens.len() {
        let node = root.at(&indices);
        let token = tokens[offset];
        if offset + 2 == tokens.len() && child_type(token) && tokens[offset + 1] == "OID" {
            return Ok((indices, Some(format!("{token}/OID"))));
        }
        if offset + 1 == tokens.len()
            && !child_type(token)
            && indexed_type(token).is_none()
            && (node.field(token).is_some() || child_by_coordinate(node, token).is_none())
        {
            return Ok((indices, Some(token.to_string())));
        }
        let index = if let Some((kind, ordinal)) = indexed_type(token) {
            let ordinal = if kind == "Interface" { 0 } else { ordinal };
            node.children
                .iter()
                .enumerate()
                .filter(|(_, child)| child.element == kind)
                .nth(ordinal)
                .map(|(index, _)| index)
        } else if child_type(token) {
            node.children
                .iter()
                .position(|child| child.element == token)
        } else if token == "p" {
            offset += 1;
            let address = tokens.get(offset).ok_or("Unit address required")?;
            node.children.iter().position(|child| {
                child.element == "Unit" && child.field("Address") == Some(*address)
            })
        } else {
            child_by_coordinate(node, token)
        }
        .ok_or_else(|| {
            format!("Bad object or device ID: Index out of range in address part {token}")
        })?;
        indices.push(index);
        offset += 1;
    }
    Ok((indices, None))
}

struct AssociatedLevelOperand {
    canonical: String,
    element: String,
    oid: String,
    addressed: bool,
}

impl Server {
    pub(crate) fn named_project_oid(&self, project: &str) -> Option<&str> {
        self.db_xml_extras
            .get(&Self::unit_document_key(
                project,
                crate::native_archive::ENVELOPE_KEY,
            ))?
            .attributes
            .get("project-oid")
            .map(String::as_str)
    }

    fn ensure_named_project_oid(&mut self, project: &str) {
        if self.named_project_oid(project).is_none() {
            let oid = fresh_oid();
            self.db_xml_extras
                .entry(Self::unit_document_key(
                    project,
                    crate::native_archive::ENVELOPE_KEY,
                ))
                .or_default()
                .attributes
                .insert("project-oid".to_string(), oid.clone());
        }
        if let Some(oid) = self.named_project_oid(project).map(str::to_string) {
            self.known_oids.insert(oid.clone());
            self.objects.insert(format!("!{oid}"));
        }
    }

    pub(crate) fn named_tag_save_error(&self, project: &str) -> Option<&'static str> {
        let records = &self.projects.get(project)?.tag_networks;
        if records
            .values()
            .filter(|record| record.database_network.is_none())
            .any(|record| record.root.null_tag_name())
        {
            return Some("NOT NULL constraint failed: tagged_entity.tag_name");
        }
        records
            .values()
            .filter(|record| record.database_network.is_none())
            .any(|record| record.root.null_level_value())
            .then_some("NOT NULL constraint failed: level_tag.value")
    }

    pub(crate) fn named_tag_xml_null(&self, project: &str) -> bool {
        self.projects.get(project).is_some_and(|project| {
            project
                .tag_networks
                .values()
                .filter(|record| record.database_network.is_none())
                .any(|record| record.root.null_tag_name())
        })
    }

    pub(crate) fn save_named_level_tags(&mut self, project: &str) {
        if let Some(project) = self.projects.get_mut(project) {
            for record in project
                .tag_networks
                .values_mut()
                .filter(|record| record.database_network.is_none())
            {
                record.saved_level_tags_pending = record.root.needs_level_tags();
            }
        }
    }

    pub(crate) fn load_named_level_tags(&mut self, project: &str) {
        if let Some(project) = self.projects.get_mut(project) {
            for record in project.tag_networks.values_mut().filter(|record| {
                record.database_network.is_none() && record.saved_level_tags_pending
            }) {
                record.root.materialize_level_tags();
                record.saved_level_tags_pending = false;
            }
        }
    }

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

    /// Mirror only this already-owned Application scalar into any stored
    /// numeric overlay. Do not re-admit an untouched Unit/PP/raw Level tree.
    pub(crate) fn sync_application_tag_field(
        &mut self,
        project: &str,
        network: u8,
        oid: &str,
        old_address: u8,
        field: &str,
        value: &str,
    ) {
        if let Some(project) = self.projects.get_mut(project) {
            for record in project
                .tag_networks
                .values_mut()
                .filter(|record| record.database_network == Some(network))
            {
                for application in record.root.children.iter_mut().filter(|node| {
                    node.element == "Application"
                        && node.field("OID") == Some(oid)
                        && node
                            .field("Address")
                            .and_then(|address| address.parse::<u8>().ok())
                            == Some(old_address)
                }) {
                    application.set(field, value.to_string());
                }
            }
        }
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
                saved_level_tags_pending: false,
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
                saved_level_tags_pending: false,
            }
        };
        let interface = record
            .root
            .children
            .iter_mut()
            .find(|node| node.element == "Interface")
            .ok_or("Network Interface is missing")?;
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
        self.ensure_named_project_oid(project);
        self.register_tag_network(project, record);
        self.retire_inactive_db_oids(&old_oids);
        Ok(())
    }

    fn tag_selection(&self, path: &str) -> Result<Option<Selection>, String> {
        self.tag_selection_in(path, self.current.as_deref())
    }

    fn tag_selection_in(
        &self,
        path: &str,
        project: Option<&str>,
    ) -> Result<Option<Selection>, String> {
        self.tag_selection_in_with_application_coordinates(path, project, false)
    }

    fn tag_selection_in_with_application_coordinates(
        &self,
        path: &str,
        project: Option<&str>,
        allow_application_coordinates: bool,
    ) -> Result<Option<Selection>, String> {
        let Some(project) = project else {
            return Ok(None);
        };
        let Some(record) = self.projects.get(project) else {
            return Ok(None);
        };
        if let Some(rest) = path.strip_prefix('!') {
            let (oid, suffix) = rest
                .split_once('/')
                .map_or((rest, ""), |(oid, suffix)| (oid, suffix));
            // A numeric database descendant keeps its established owner,
            // including duplicate-OID selection and transitive invalidation.
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
                || (self.current.as_deref() == Some(project) && self.level_key(oid).is_some())
            {
                return Ok(None);
            }
            for key in record.tag_networks.keys() {
                let network = self.current_tag_record(project, key)?;
                let mut indices = Vec::new();
                if network.root.find_oid(oid, &mut indices) {
                    let (indices, field) = walk_tag_path(
                        &network.root,
                        indices,
                        suffix,
                        allow_application_coordinates && network.database_network.is_some(),
                    )?;
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
        let (address, suffix) = relative.split_once('/').unwrap_or((relative, ""));
        // Keys are internal identities for unnamed/duplicate Networks. The
        // lexical Address comes only from the authoritative node, never OID
        // keys or parsing a numeric-looking name into a physical address.
        let key = record
            .tag_networks
            .iter()
            .filter(|(_, tag)| tag.root.field("Address") == Some(address))
            .min_by_key(|(key, tag)| (tag.created_seq, *key))
            .map(|(key, _)| key);
        let Some(key) = key else { return Ok(None) };
        let network = self.current_tag_record(project, key)?;
        let selected = walk_tag_path(
            &network.root,
            Vec::new(),
            suffix,
            allow_application_coordinates && network.database_network.is_some(),
        );
        match selected {
            Ok((indices, field)) => Ok(Some(Selection {
                project: project.to_string(),
                key: key.clone(),
                indices,
                field,
            })),
            Err(_)
                if network
                    .database_network
                    .is_some_and(|number| number.to_string() == address)
                    && !suffix.split('/').any(|part| {
                        part == "Languages"
                            || indexed_type(part).is_some_and(|(kind, _)| kind == "Languages")
                    }) =>
            {
                Ok(None)
            }
            Err(error) => Err(error),
        }
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
        self.projects.get(project).is_some_and(|project| {
            project.tag_networks.values().any(|record| {
                record.database_network.is_none() && record.root.field("Address") == Some(name)
            })
        })
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
                        .chain(
                            record
                                .optional_interface()
                                .into_iter()
                                .flat_map(TagNode::oids),
                        )
                        .chain(
                            record
                                .root
                                .children
                                .iter()
                                .filter(|child| child.element == "Languages")
                                .flat_map(TagNode::oids),
                        )
                        .collect::<Vec<_>>()
                } else {
                    record.root.oids()
                }
            })
            .collect()
    }

    pub(crate) fn register_tag_network(&mut self, project: &str, record: TagNetwork) {
        let address = record.root.field("Address");
        let mut key = address
            .filter(|address| {
                self.projects[project]
                    .tag_networks
                    .get(*address)
                    .is_none_or(|existing| existing.root.field("OID") == record.root.field("OID"))
            })
            .map(str::to_string)
            .unwrap_or_else(|| {
                format!("!{}", record.root.field("OID").expect("internal root OID"))
            });
        let base = format!("!{}", record.root.field("OID").expect("internal root OID"));
        let mut suffix = 0_u64;
        while self.projects[project]
            .tag_networks
            .get(&key)
            .is_some_and(|existing| existing.root.field("OID") != record.root.field("OID"))
        {
            suffix += 1;
            key = format!("{base}#{suffix}");
        }
        for oid in record.root.oids() {
            self.known_oids.insert(oid.clone());
            self.objects.insert(format!("!{oid}"));
        }
        if let Some(address) = address {
            self.objects.insert(format!("//{project}/{address}"));
        }
        self.projects
            .get_mut(project)
            .expect("validated project")
            .tag_networks
            .insert(key, record);
    }

    fn replace_internal_tag_record(
        &mut self,
        project: &str,
        key: &str,
        record: TagNetwork,
    ) -> Result<(), String> {
        if record.database_network.is_some() {
            return self.replace_tag_record(project, key, record);
        }
        // This is an already-owned internal graph, not external complete XML
        // admission. Absent identities and literal unsafe Addresses persist
        // under that one owner without creating numeric or pending mirrors.
        let old = self.current_tag_record(project, key)?;
        self.projects
            .get_mut(project)
            .expect("project")
            .tag_networks
            .remove(key);
        self.register_tag_network(project, record);
        self.retire_inactive_db_oids(&old.root.oids());
        Ok(())
    }

    /// Language edits own only the Network language collection. Replaying
    /// the complete numeric Unit/Application mapper here would change
    /// unrelated raw programming records and physical inventory.
    fn replace_language_record(&mut self, project: &str, key: &str, record: TagNetwork) {
        let old_oids = self.projects[project].tag_networks[key].root.oids();
        if record.database_network.is_some() {
            let oid = record.root.field("OID").expect("Network OID");
            let extras = self
                .db_xml_extras
                .entry(Self::unit_document_key(project, oid))
                .or_default();
            extras
                .children
                .retain(|xml| !xml.starts_with("<Languages>"));
            extras.children.extend(
                record
                    .root
                    .children
                    .iter()
                    .filter(|child| child.element == "Languages")
                    .map(TagNode::document),
            );
        }
        self.projects
            .get_mut(project)
            .expect("selected project")
            .tag_networks
            .remove(key);
        self.register_tag_network(project, record);
        self.retire_inactive_db_oids(&old_oids);
    }

    /// Legacy numeric databases do not always have a tag overlay. Resolve
    /// their actual Network OID and compose a temporary authoritative tree
    /// for this language command. Reads never materialize persistent state;
    /// successful mutations install the tree once.
    fn numeric_language_command(&mut self, tag: &str, words: &[&str]) -> Option<Response> {
        let verb = words.first()?.to_ascii_uppercase();
        let target = *words.get(1)?;
        let add = matches!(verb.as_str(), "DBADD" | "DBADDSAFE")
            && words
                .get(2)
                .is_some_and(|element| element.eq_ignore_ascii_case("Languages"));
        let qualified = target
            .strip_prefix("//")
            .and_then(|rest| rest.split_once('/'))
            .map(|(project, _)| project);
        let project = qualified.or(self.current.as_deref())?.to_string();
        let owner = self.projects.get(&project)?;
        let language_owner = target.strip_prefix('!').and_then(|rest| {
            let oid = rest.split('/').next()?;
            owner.networks.values().find(|network| {
                let Some(extras) = self
                    .db_xml_extras
                    .get(&Self::unit_document_key(&project, &network.oid))
                else {
                    return false;
                };
                let mut oids = Vec::new();
                crate::db_xml_language_oids(extras, &mut oids);
                oids.iter().any(|(candidate, _)| candidate == oid)
            })
        });
        if !add
            && language_owner.is_none()
            && !target.split('/').any(|part| {
                part == "Languages"
                    || indexed_type(part).is_some_and(|(kind, _)| kind == "Languages")
            })
        {
            return None;
        }
        let network = if let Some(rest) = target.strip_prefix('!') {
            let oid = rest.split('/').next()?;
            language_owner.or_else(|| owner.networks.values().find(|network| network.oid == oid))
        } else {
            let relative = target
                .strip_prefix(&format!("//{project}/"))
                .unwrap_or(target);
            let address = relative.split('/').next()?;
            owner
                .networks
                .values()
                .find(|network| network.address.to_string() == address)
        }?;
        if owner
            .tag_networks
            .values()
            .any(|record| record.database_network == Some(network.address))
        {
            return None;
        }
        if !matches!(
            verb.as_str(),
            "DBGET" | "DBGETXML" | "DBADD" | "DBADDSAFE" | "DBSET" | "DBSETSAFE" | "DBDELETE"
        ) {
            return None;
        }
        if add
            && target.trim_end_matches('/') != format!("!{}", network.oid)
            && target.trim_end_matches('/') != format!("//{project}/{}", network.address)
            && target != network.address.to_string()
        {
            return None;
        }
        let document = self.network_xml_document(&project, network.address, network);
        let parsed = match roxmltree::Document::parse(&document) {
            Ok(parsed) => parsed,
            Err(error) => return Some(err(tag, 408, &format!("408 Operation failed: {error}"))),
        };
        let root = match parse_node(parsed.root_element()) {
            Ok(root) => root,
            Err(error) => return Some(err(tag, 408, &format!("408 Operation failed: {error}"))),
        };
        // This is an already-owned numeric graph, not a new complete XML
        // submission. Preserve incomplete/raw descendants without trying to
        // re-admit them under external Unit/Application schema rules.
        let record = TagNetwork {
            root,
            database_network: Some(network.address),
            created_seq: network.created_seq,
            saved_level_tags_pending: false,
        };
        let mut staged = self.clone();
        staged.register_tag_network(&project, record);
        let response = staged.tag_database_command(tag, words)?;
        if !matches!(verb.as_str(), "DBGET" | "DBGETXML") && response.status < 400 {
            *self = staged;
        }
        Some(response)
    }

    fn named_child_allowed(parent: &str, child: &str) -> bool {
        matches!(
            (parent, child),
            ("Network", "Application" | "Unit" | "Languages")
                | ("Languages", "Language")
                | ("Application", "Group" | "NetVar")
                | ("Group" | "NetVar", "Level")
        )
    }

    fn named_address_collision(
        parent: &TagNode,
        element: &str,
        address: &str,
        own_oid: Option<&str>,
    ) -> bool {
        parent.children.iter().any(|child| {
            child.element == element
                && child.field("Address") == Some(address)
                && (own_oid.is_none() || child.field("OID") != own_oid)
        })
    }

    fn add_named_tag_child(
        &mut self,
        tag: &str,
        words: &[&str],
        selected: &Selection,
        record: &TagNetwork,
    ) -> Response {
        let safe = words[0].eq_ignore_ascii_case("DBADDSAFE");
        if (safe && words.len() < 5) || (!safe && words.len() != 3) {
            return err(tag, 400, "400 Syntax Error.");
        }
        let parent = record.root.at(&selected.indices);
        let element = match words[2].to_ascii_lowercase().as_str() {
            "application" => "Application",
            "group" => "Group",
            "netvar" => "NetVar",
            "level" => "Level",
            "unit" => "Unit",
            "languages" => "Languages",
            "language" => "Language",
            _ => return err(tag, 401, "401 Bad object or device ID: Field not found"),
        };
        if selected.field.is_some() || !Self::named_child_allowed(&parent.element, element) {
            return err(tag, 401, "401 Bad object or device ID: Field not found");
        }
        if matches!(element, "Languages" | "Language") {
            if safe {
                return err(
                    tag,
                    400,
                    "400 Language objects require DBADD without an Address",
                );
            }
            if element == "Languages"
                && parent
                    .children
                    .iter()
                    .any(|child| child.element == "Languages")
            {
                return err(tag, 409, "409 Languages collection already exists");
            }
            let mut staged = self.clone();
            let oid = staged.issue_oid();
            let mut replacement = record.clone();
            replacement
                .root
                .at_mut(&selected.indices)
                .push_child(TagNode::new(element, &[("OID", &oid)]));
            staged.replace_language_record(&selected.project, &selected.key, replacement);
            *self = staged;
            return Response {
                tag: tag.to_string(),
                lines: Vec::new(),
                final_text: format!("301 OID={oid}"),
                status: 301,
            };
        }
        if safe {
            let Ok(address) = words[3].parse::<u8>() else {
                return err(tag, 401, "401 Bad object or device ID: Invalid address");
            };
            let collision = if element == "Unit" {
                // New Unit addresses identify a byte slot. Existing named
                // XML can retain alternate decimal spellings, so compare
                // those numerically before creating the canonical slot.
                parent.children.iter().any(|child| {
                    child.element == "Unit"
                        && child
                            .field("Address")
                            .and_then(|value| value.parse::<u8>().ok())
                            == Some(address)
                })
            } else {
                Self::named_address_collision(parent, element, words[3], None)
            };
            if collision {
                return err(
                    tag,
                    401,
                    "401 Bad object or device ID: Element address in use",
                );
            }
            if element == "Unit" && words[4..].join(" ").contains('#') {
                return err(tag, 400, "400 Invalid tag name");
            }
        }
        let mut staged = self.clone();
        let oid = if element == "Unit" {
            staged.issue_oid()
        } else {
            fresh_oid()
        };
        let mut child = TagNode::new(element, &[("OID", &oid)]);
        if safe {
            let name = words[4..].join(" ");
            child.set("TagName", name.clone());
            let address = if element == "Unit" {
                words[3]
                    .parse::<u8>()
                    .expect("validated Unit address")
                    .to_string()
            } else {
                words[3].to_string()
            };
            child.set("Address", address);
            if element == "Unit" {
                child.set("UnitName", name);
            }
        }
        let mut replacement = record.clone();
        replacement.root.at_mut(&selected.indices).push_child(child);
        match staged.replace_internal_tag_record(&selected.project, &selected.key, replacement) {
            Ok(()) => {
                *self = staged;
                Response {
                    tag: tag.to_string(),
                    lines: Vec::new(),
                    final_text: format!("301 OID={oid}"),
                    status: 301,
                }
            }
            Err(error) => err(tag, 408, &format!("408 Operation failed: {error}")),
        }
    }

    fn copy_named_tag_node(
        &mut self,
        tag: &str,
        words: &[&str],
        selected: &Selection,
        record: &TagNetwork,
    ) -> Response {
        let safe = words[0].eq_ignore_ascii_case("DBCOPYSAFE");
        if (safe && words.len() < 5) || (!safe && words.len() != 3) || selected.field.is_some() {
            return err(tag, 400, "400 Syntax Error.");
        }
        let source = record.root.at(&selected.indices);
        if !matches!(
            source.element.as_str(),
            "Network" | "Application" | "Group" | "NetVar" | "Level"
        ) {
            return err(tag, 408, "408 Operation failed: Object type mismatch");
        }
        let mut staged = self.clone();
        let mut copied = source.clone();
        copied.refresh_oids();
        let oid = copied.field("OID").expect("copied OID").to_string();
        if source.element == "Network" {
            let qualified = format!("//{}/Installation/Project", selected.project);
            let project_oid = staged.named_project_oid(&selected.project);
            let internal_parent = words[2] == "Installation/Project"
                || words[2] == qualified
                || project_oid.is_some_and(|oid| words[2] == format!("!{oid}"));
            if !safe && internal_parent && source.unprobed_copy_payload() {
                return err(tag, 408, "408 Operation failed: Mixed unsafe Network copy with Unit or unmodeled OID-bearing payload is unsupported");
            }
            let destination = words[2].trim_start_matches("//");
            // Preserve the previously supported complete cross-project form;
            // the captured same-project form deliberately clears identities.
            let project_parent =
                !destination.contains('/') && staged.projects.contains_key(destination);
            let cross_project = project_parent && destination != selected.project;
            if !(internal_parent || cross_project || safe && project_parent) {
                let mismatch =
                    words[2] == "Installation" || words[2] == format!("//{}", selected.project);
                return if mismatch {
                    err(tag, 408, "408 Operation failed: Object type mismatch")
                } else {
                    err(tag, 401, "401 Bad object or device ID: Object not found")
                };
            }
            if !safe && internal_parent {
                copied.clear_copy_identities();
            }
            if safe {
                copied.set("Address", words[3].to_string());
                copied.set("TagName", words[4..].join(" "));
            }
            let destination = if project_parent {
                destination
            } else {
                &selected.project
            };
            let created_seq = crate::next_network_seq(&staged.projects[destination]);
            let replacement = TagNetwork {
                root: copied,
                database_network: None,
                created_seq,
                saved_level_tags_pending: false,
            };
            if safe {
                if let Err(error) = staged.insert_tag_copy(destination, replacement) {
                    return err(tag, 408, &format!("408 Operation failed: {error}"));
                }
            } else {
                staged.register_tag_network(destination, replacement);
            }
        } else {
            if source.unprobed_copy_payload() {
                return err(tag, 408, "408 Operation failed: Named child copy with Unit or unmodeled OID-bearing payload is unsupported");
            }
            let destination = match staged.tag_selection(words[2]) {
                Ok(Some(destination)) => destination,
                _ => return err(tag, 401, "401 Bad object or device ID: Object not found"),
            };
            if destination.project != selected.project || destination.field.is_some() {
                return err(tag, 401, "401 Bad object or device ID: Object not found");
            }
            let mut target = match staged.current_tag_record(&destination.project, &destination.key)
            {
                Ok(target) if target.database_network.is_none() => target,
                _ => {
                    return err(
                        tag,
                        408,
                        "408 Operation failed: Independent named destination required",
                    )
                }
            };
            let parent = target.root.at_mut(&destination.indices);
            if !Self::named_child_allowed(&parent.element, &copied.element) {
                return err(tag, 401, "401 Bad object or device ID: Field not found");
            }
            if safe {
                if words[3].parse::<u8>().is_err() {
                    return err(tag, 401, "401 Bad object or device ID: Invalid address");
                }
                if Self::named_address_collision(parent, &copied.element, words[3], None) {
                    return err(
                        tag,
                        401,
                        "401 Bad object or device ID: Element address in use",
                    );
                }
                copied.set("Address", words[3].to_string());
                copied.set("TagName", words[4..].join(" "));
            } else {
                copied.clear_copy_identities();
            }
            parent.push_child(copied);
            if let Err(error) =
                staged.replace_internal_tag_record(&destination.project, &destination.key, target)
            {
                return err(tag, 408, &format!("408 Operation failed: {error}"));
            }
        }
        *self = staged;
        Response {
            tag: tag.to_string(),
            lines: Vec::new(),
            final_text: format!("301 OID={oid}"),
            status: 301,
        }
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
        let prefix = format!("//{project}/{address}/");
        if self
            .db_levels
            .values()
            .any(|level| level.parent.starts_with(&prefix) && level.raw_value.is_some())
        {
            return Err(
                "Associated raw Level Value cannot be re-admitted as complete XML".to_string(),
            );
        }
        let plain_variables = self
            .db_levels
            .values()
            .filter(|level| {
                level.netvar
                    && level.parent.starts_with(&prefix)
                    && !self
                        .db_pending
                        .values()
                        .any(|pending| pending.project == project && pending.oid == level.oid)
            })
            .cloned()
            .collect::<Vec<_>>();
        for variable in &plain_variables {
            if variable.value.is_some() {
                return Err(
                    "Associated NetVar parent Value cannot be projected losslessly".to_string(),
                );
            }
            let path = format!("{}/{}", variable.parent, variable.address);
            if std::iter::once(variable.oid.as_str())
                .chain(
                    self.db_levels
                        .values()
                        .filter(|level| level.parent == path)
                        .map(|level| level.oid.as_str()),
                )
                .any(|oid| {
                    self.db_xml_extras
                        .get(&Self::unit_document_key(project, oid))
                        .is_some_and(|extras| extras != &crate::DbXmlExtras::default())
                })
            {
                return Err(
                    "Associated NetVar retained payload cannot be projected losslessly".to_string(),
                );
            }
        }
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
        if result.is_ok() {
            // Keep a plain typed NetVar's original owner/readback rather than
            // replacing it with a new pending mirror during rehydration.
            self.db_pending.retain(|_, pending| {
                !(pending.project == project
                    && pending.element == "NetVar"
                    && plain_variables.iter().any(|variable| {
                        variable.oid == pending.oid
                            && pending.path.as_deref()
                                == Some(
                                    format!("{}/{}", variable.parent, variable.address).as_str(),
                                )
                    }))
            });
        }
        self.projects
            .get_mut(project)
            .expect("project")
            .tag_networks
            .insert(key.to_string(), overlay);
        result
    }

    // Resolve only a stable numeric database owner. This never changes the
    // physical network resolver and never parses a named/internal storage key.
    fn associated_level_owner(&self, project: &str, raw: &str) -> Option<u8> {
        let mut path = raw.to_string();
        let mut seen = HashSet::new();
        for _ in 0..=self.db_pending.len() {
            if !seen.insert(path.clone()) {
                return None;
            }
            if let Some(oid) = path.strip_prefix('!') {
                if oid.is_empty() || oid.contains('/') {
                    return None;
                }
                path = self.pending_object(project, oid)?.parent.clone();
                continue;
            }
            let (owner_project, number) = self.network_of(&path)?;
            if owner_project != project {
                return None;
            }
            return self
                .projects
                .get(project)?
                .tag_networks
                .values()
                .any(|record| record.database_network == Some(number))
                .then_some(number);
        }
        None
    }

    fn associated_level_operand(
        &self,
        raw: &str,
    ) -> Result<Option<AssociatedLevelOperand>, String> {
        let Some(project) = self.current.as_deref() else {
            return Ok(None);
        };
        let Some(project_record) = self.projects.get(project) else {
            return Ok(None);
        };
        if let Some(oid) = raw.strip_prefix('!') {
            // Several general legacy resolvers strip suffixes. Never call
            // those with a scalar/descendant spelling as a Level operand.
            if oid.is_empty() || oid.contains('/') {
                return Err("Level operands require a bare OID".to_string());
            }
            if self
                .invalidated_unit_oid_lookups
                .contains(&(project.to_string(), oid.to_string()))
                || project_record
                    .networks
                    .values()
                    .any(|network| network.units.values().any(|unit| unit.oid == oid))
            {
                return Err("Level operand resolves to a retired or Unit identity".to_string());
            }
            // Preserve the established pending winner, including xml_order.
            // pending_for_project is not a path resolver: it returns !OID.
            if let Some(object) = self.pending_object(project, oid) {
                let route = object.path.as_deref().unwrap_or(&object.parent);
                if self.associated_level_owner(project, route).is_some() {
                    return Ok(Some(AssociatedLevelOperand {
                        canonical: object.path.clone().unwrap_or_else(|| raw.to_string()),
                        element: object.element.clone(),
                        oid: oid.to_string(),
                        addressed: object.path.is_some(),
                    }));
                }
            }
            if let Some(level) = self.level(oid) {
                if self
                    .associated_level_owner(project, &level.parent)
                    .is_some()
                {
                    return Ok(Some(AssociatedLevelOperand {
                        canonical: format!("{}/{}", level.parent, level.address),
                        element: if level.netvar { "NetVar" } else { "Level" }.to_string(),
                        oid: oid.to_string(),
                        addressed: true,
                    }));
                }
            }
        }
        let Some(selected) = self.tag_selection_in(raw, Some(project))? else {
            return Ok(None);
        };
        let record = self.current_tag_record(project, &selected.key)?;
        let Some(number) = record.database_network else {
            return Ok(None);
        };
        if selected.field.is_some() {
            return Err("A scalar field is not a Level operand".to_string());
        }
        let mut canonical = format!("//{project}/{number}");
        let mut node = &record.root;
        for index in selected.indices {
            node = &node.children[index];
            if !matches!(
                node.element.as_str(),
                "Application" | "Group" | "NetVar" | "Level"
            ) {
                return Err("Unsupported associated Level route".to_string());
            }
            let address = node
                .field("Address")
                .and_then(|value| value.parse::<u8>().ok())
                .ok_or_else(|| "Level route has no byte Address".to_string())?;
            canonical.push_str(&format!("/{address}"));
        }
        let oid = node
            .field("OID")
            .ok_or_else(|| "Level route has no identity".to_string())?;
        // Require a real legacy identity at that path, never just path length.
        let typed_identity = self.level(oid).filter(|level| {
            format!("{}/{}", level.parent, level.address) == canonical
                && node.element == if level.netvar { "NetVar" } else { "Level" }
        });
        if typed_identity.is_none() {
            let target = self
                .resolve_db_xml_target(&canonical)
                .map_err(|(_, reason)| reason)?;
            if target.oid != oid || target.kind.element() != node.element {
                return Err("Associated Level route identity disagrees with its owner".to_string());
            }
        }
        Ok(Some(AssociatedLevelOperand {
            canonical,
            element: node.element.clone(),
            oid: oid.to_string(),
            addressed: true,
        }))
    }

    // Admit only the already modeled empty label collection and its deferred
    // load marker. Nonempty labels and arbitrary decorations remain refused.
    pub(crate) fn associated_empty_level_copy_payload(extras: &crate::DbXmlExtras) -> bool {
        if !extras.namespaces.is_empty()
            || !extras.attributes.is_empty()
            || extras.children.len() > 1
        {
            return false;
        }
        let Some(fragment) = extras.children.first() else {
            return true;
        };
        let Ok(document) = roxmltree::Document::parse(fragment) else {
            return false;
        };
        let root = document.root_element();
        let markup = &fragment[root.range()];
        // The DOM hides XML declarations and the built-in xmlns:xml binding.
        // Require the entire retained fragment to be this element and permit
        // only whitespace/self-closing syntax after its exact opening name.
        let opening = markup.split_once('>').map(|(opening, _)| opening);
        let empty_opening = opening
            .and_then(|opening| opening.strip_prefix("<TagsDLT"))
            .is_some_and(|tail| {
                tail.trim_end()
                    .strip_suffix('/')
                    .unwrap_or(tail)
                    .trim()
                    .is_empty()
            });
        fragment.trim() == markup
            && empty_opening
            && root.has_tag_name("TagsDLT")
            && root.tag_name().namespace().is_none()
            && root.namespaces().len() == 0
            && root.attributes().len() == 0
            && document.root().children().all(|node| {
                node == root || node.is_text() && node.text().unwrap_or_default().trim().is_empty()
            })
            && root
                .children()
                .all(|node| node.is_text() && node.text().unwrap_or_default().trim().is_empty())
    }

    fn associated_numeric_level_value_operand(
        &self,
        raw: &str,
    ) -> Result<Option<AssociatedLevelOperand>, String> {
        if raw.starts_with('!') {
            return Ok(None);
        }
        if let Ok(Some(selection)) = self.tag_selection(raw) {
            if self.projects[&selection.project].tag_networks[&selection.key]
                .database_network
                .is_none()
            {
                // Numeric-looking names keep established lexical ownership.
                // Numeric Value routing is only a fallback for the associated
                // typed owner when no independent named selection wins.
                return Ok(None);
            }
        }
        let path = if raw.starts_with("//") {
            raw.to_string()
        } else if let Some(project) = self.current.as_deref() {
            format!("//{project}/{raw}")
        } else {
            return Ok(None);
        };
        let parts = path.trim_start_matches('/').split('/').collect::<Vec<_>>();
        if parts.len() < 5 || parts[2].eq_ignore_ascii_case("p") {
            return Ok(None);
        }
        let Some(number) = parts[1].parse::<u8>().ok() else {
            return Ok(None);
        };
        let project = parts[0];
        if self
            .associated_level_owner(project, &format!("//{project}/{number}"))
            .is_none()
        {
            return Ok(None);
        }
        if self.current.as_deref() != Some(project) {
            return Err("Associated Level project not selected".to_string());
        }
        let levels = self
            .db_levels
            .values()
            .filter(|level| !level.netvar && format!("{}/{}", level.parent, level.address) == path)
            .collect::<Vec<_>>();
        if levels.len() != 1 {
            return Err("Associated numeric Level has no unique addressed owner".to_string());
        }
        // Reuse the OID fence, including retired/Unit identity precedence and
        // the established winning pending owner, instead of inventing a route.
        match self.associated_level_operand(&format!("!{}", levels[0].oid))? {
            Some(operand)
                if operand.element == "Level" && operand.addressed && operand.canonical == path =>
            {
                Ok(Some(operand))
            }
            _ => Err("Associated numeric Level identity disagrees with its owner".to_string()),
        }
    }

    fn associated_level_value_command(&mut self, tag: &str, words: &[&str]) -> Option<Response> {
        let verb = words.first()?.to_ascii_uppercase();
        let getter = verb == "DBGET";
        if !matches!(verb.as_str(), "DBGET" | "DBSET" | "DBSETSAFE")
            || (getter && words.len() != 2)
            || (!getter && words.len() < 3)
        {
            return None;
        }
        let (object_path, field) = words[1].rsplit_once('/')?;
        if field != "Value" {
            return None;
        }
        let operand = if getter {
            match self.associated_numeric_level_value_operand(object_path) {
                Ok(Some(operand)) => operand,
                Ok(None) => return None,
                Err(reason) => {
                    return Some(err(
                        tag,
                        401,
                        &format!("401 Bad object or device ID: {reason}"),
                    ))
                }
            }
        } else {
            match self.associated_level_operand(object_path) {
                Ok(Some(operand)) if operand.element == "Level" && operand.addressed => operand,
                Ok(None) => match self.associated_numeric_level_value_operand(object_path) {
                    Ok(Some(operand)) => operand,
                    Ok(None) => return None,
                    Err(reason) => {
                        return Some(err(
                            tag,
                            401,
                            &format!("401 Bad object or device ID: {reason}"),
                        ))
                    }
                },
                _ => return None,
            }
        };
        let project = self.current.clone().expect("selected associated owner");
        let level = self.level(&operand.oid)?;
        if format!("{}/{}", level.parent, level.address) != operand.canonical || level.netvar {
            return Some(err(
                tag,
                408,
                "408 Operation failed: Associated Level owner disagrees with its route",
            ));
        }
        // The typed record is authoritative. Refuse any competing or stale
        // completed mirror before mutation rather than silently healing it.
        if self
            .db_pending
            .values()
            .filter(|pending| pending.project == project && pending.oid == operand.oid)
            .any(|pending| {
                pending.element != "Level"
                    || pending.path.as_deref() != Some(operand.canonical.as_str())
                    || {
                        let mirror = pending
                            .fields
                            .get("Value")
                            .filter(|value| !value.is_empty());
                        match (&level.raw_value, level.value) {
                            (Some(raw), _) => mirror != Some(raw),
                            (None, Some(byte)) => {
                                mirror.and_then(|value| value.parse::<u8>().ok()) != Some(byte)
                            }
                            (None, None) => mirror.is_some(),
                        }
                    }
            })
        {
            return Some(err(
                tag,
                408,
                "408 Operation failed: Associated Level Value mirror disagrees with its owner",
            ));
        }
        if getter {
            return Some(Response {
                tag: tag.to_string(),
                lines: Vec::new(),
                status: 342,
                final_text: format!(
                    "342 {}={}",
                    words[1],
                    level
                        .effective_value()
                        .unwrap_or_else(|| "null".to_string())
                ),
            });
        }
        let value = words[2..].join(" ");
        if value.is_empty() || (verb == "DBSETSAFE" && value.contains('#')) {
            return Some(err(tag, 400, "400 Invalid field value"));
        }
        if !value.chars().all(|character| {
            matches!(character,
            '\u{9}' | '\u{A}' | '\u{D}' | '\u{20}'..='\u{D7FF}'
                | '\u{E000}'..='\u{FFFD}' | '\u{10000}'..='\u{10FFFF}')
        }) {
            return Some(err(
                tag,
                408,
                "408 Operation failed: Level Value is not representable in XML",
            ));
        }
        // Keep each established typed initializer grammar; every other
        // nonempty tail remains raw text, with no inferred numeric projection.
        let byte = if verb == "DBSETSAFE" {
            value
                .parse::<i64>()
                .ok()
                .and_then(|value| u8::try_from(value).ok())
        } else {
            value.parse::<u8>().ok()
        };
        let effective = byte.map_or_else(|| value.clone(), |byte| byte.to_string());
        let mut staged = self.clone();
        let level = staged.level_mut(&operand.oid).expect("checked typed Level");
        level.value = byte;
        level.raw_value = byte.is_none().then(|| value.clone());
        for pending in staged.db_pending.values_mut().filter(|pending| {
            pending.project == project
                && pending.oid == operand.oid
                && pending.element == "Level"
                && pending.path.as_deref() == Some(operand.canonical.as_str())
        }) {
            pending
                .fields
                .insert("Value".to_string(), effective.clone());
        }
        // These are readback mirrors of one owner, never opaque second owners.
        staged
            .db_fields
            .insert(format!("!{}/Value", operand.oid), effective.clone());
        staged
            .db_fields
            .insert(format!("{}/Value", operand.canonical), effective);
        *self = staged;
        Some(crate::ok(
            tag,
            vec![],
            if verb == "DBSETSAFE" && words[1].starts_with('!') {
                "200 OK"
            } else {
                "200 OK."
            },
        ))
    }

    // Guard every existing copy projector, including canonical numeric paths
    // which do not select a renamed lexical tag record. No raw Value may become
    // a NULL DatabaseCopyNode before an identity is allocated.
    pub(crate) fn associated_raw_level_copy_source(&self, raw: &str) -> bool {
        let Some(selected) = self.current.as_deref() else {
            return false;
        };
        if let Ok(Some(selection)) = self.tag_selection_in(raw, Some(selected)) {
            if self.projects[&selection.project].tag_networks[&selection.key]
                .database_network
                .is_none()
            {
                // A known independent lexical owner wins before the legacy
                // numeric projector, even when its name looks numeric.
                return false;
            }
        }
        let mut path = if raw.starts_with('!') {
            // The legacy projector strips OID suffixes. This refusal guard
            // must see that same object without admitting the suffix itself.
            let bare = raw.split('/').next().unwrap_or_default();
            match self.associated_level_operand(bare) {
                Ok(Some(operand)) if operand.addressed => operand.canonical,
                _ => return false,
            }
        } else if let Ok(Some(operand)) = self.associated_level_operand(raw) {
            operand.canonical
        } else if raw.starts_with("//") {
            // The legacy source projector strips every leading slash before
            // splitting its numeric path, including a three-slash spelling.
            format!("//{}", raw.trim_start_matches('/').trim_end_matches('/'))
        } else if raw.eq_ignore_ascii_case(selected) {
            format!("//{selected}")
        } else {
            format!("//{selected}/{}", raw.trim_matches('/'))
        };
        let parts = path.trim_start_matches('/').split('/').collect::<Vec<_>>();
        if (2..=5).contains(&parts.len())
            && !parts
                .get(2)
                .is_some_and(|part| part.eq_ignore_ascii_case("p"))
        {
            if let Ok(addresses) = parts[1..]
                .iter()
                .map(|part| part.parse::<u8>())
                .collect::<Result<Vec<_>, _>>()
            {
                path = format!(
                    "//{}/{}",
                    parts[0],
                    addresses
                        .iter()
                        .map(u8::to_string)
                        .collect::<Vec<_>>()
                        .join("/")
                );
            }
        }
        self.db_levels.values().any(|level| {
            let Some((project, _)) = self.network_of(&level.parent) else {
                return false;
            };
            let level_path = format!("{}/{}", level.parent, level.address);
            level.raw_value.is_some()
                && self
                    .associated_level_owner(&project, &level.parent)
                    .is_some()
                && (level_path == path || level_path.starts_with(&format!("{path}/")))
        })
    }

    fn associated_level_command(&mut self, tag: &str, words: &[&str]) -> Option<Response> {
        let verb = words.first()?.to_ascii_uppercase();
        let add = matches!(verb.as_str(), "DBADD" | "DBADDSAFE")
            && words.get(2)?.eq_ignore_ascii_case("Level");
        let copy = matches!(verb.as_str(), "DBCOPY" | "DBCOPYSAFE");
        if !add && !copy {
            return None;
        }
        let safe = verb.ends_with("SAFE");
        if (safe && words.len() != 5) || (!safe && words.len() < 3) {
            return None;
        }
        let failure =
            |reason: &str| err(tag, 401, &format!("401 Bad object or device ID: {reason}"));
        if add
            && words[1]
                .strip_prefix("//")
                .and_then(|path| path.split('/').next())
                .is_some_and(|project| self.current.as_deref() != Some(project))
        {
            // No internal storage-key precondition: explicit project differs
            // from selection (including None). Fence only
            // the exact winning lexical root with a proven numeric owner.
            let associated_owner = words[1].strip_prefix("//").and_then(|path| {
                let mut parts = path.split('/');
                let project = self.projects.get(parts.next()?)?;
                let address = parts.next()?;
                project
                    .tag_networks
                    .iter()
                    .filter(|(_, record)| record.root.field("Address") == Some(address))
                    .min_by_key(|(key, record)| (record.created_seq, *key))
                    .and_then(|(_, record)| record.database_network)
                    .filter(|number| project.networks.contains_key(number))
            });
            if associated_owner.is_some() {
                return Some(failure("Associated Level project not selected"));
            }
        }
        let source = if copy {
            if words[1].strip_prefix('!').is_some_and(|raw| {
                let oid = raw.split('/').next().unwrap_or_default();
                self.current
                    .as_deref()
                    .and_then(|project| self.projects.get(project))
                    .is_some_and(|project| {
                        project
                            .networks
                            .values()
                            .any(|network| network.units.values().any(|unit| unit.oid == oid))
                    })
            }) {
                // Keep the existing duplicate Unit/path resolution in dbcopy.
                return None;
            }
            // Unit copy/duplicate-OID policy is outside this handler. A
            // malformed suffix on a known Level is still a Level refusal.
            let known_level_oid = words[1].strip_prefix('!').is_some_and(|raw| {
                let oid = raw.split('/').next().unwrap_or_default();
                self.level(oid).is_some_and(|level| !level.netvar)
                    || self
                        .current
                        .as_deref()
                        .and_then(|project| self.pending_object(project, oid))
                        .is_some_and(|object| object.element == "Level")
            });
            match self.associated_level_operand(words[1]) {
                Ok(Some(source)) if source.element == "Level" => Some(source),
                Err(reason) if known_level_oid => return Some(failure(&reason)),
                _ => return None,
            }
        } else {
            None
        };
        let parent_word = if copy { words[2] } else { words[1] };
        let parent = match self.associated_level_operand(parent_word) {
            Ok(Some(parent)) => parent,
            Ok(None) => {
                // Independent named rows retain their TagNode handler. If a
                // source already chose the associated owner, do not hand its
                // child to an unrelated graph or opaque fallback.
                return source
                    .as_ref()
                    .map(|_| failure("Associated Level destination not found"));
            }
            Err(reason) => return Some(failure(&reason)),
        };
        if !matches!(parent.element.as_str(), "Group" | "NetVar") {
            return Some(failure("Level parent must be a Group or NetVar"));
        }
        if safe && !parent.addressed {
            return Some(failure(
                "SAFE Level parent must have an addressed owner path",
            ));
        }
        if safe {
            // Validate before issuing any OID, preserving existing byte/name
            // CLI grammar. Raw independent scalar lexemes remain untouched.
            let address = match words[3].parse::<u8>() {
                Ok(address) => address,
                Err(_) => return Some(err(tag, 400, "400 Invalid database address")),
            };
            if words[4].is_empty() || words[4].contains('#') {
                return Some(err(tag, 400, "400 Invalid tag name"));
            }
            if self
                .db_levels
                .values()
                .any(|level| level.parent == parent.canonical && level.address == address)
            {
                return Some(failure("Level Address already exists"));
            }
        }
        let mut rewritten = words.to_vec();
        if let Some(source) = source {
            if self
                .level(&source.oid)
                .is_some_and(|level| level.raw_value.is_some())
            {
                return Some(err(
                    tag,
                    408,
                    "408 Operation failed: Associated raw Level copy is unsupported",
                ));
            }
            let project = self.current.as_deref().expect("associated selected owner");
            let extras_key = Self::unit_document_key(project, &source.oid);
            let source_extras = self
                .db_xml_extras
                .get(&extras_key)
                .cloned()
                .unwrap_or_default();
            if !Self::associated_empty_level_copy_payload(&source_extras)
                || self
                    .pending_object(project, &source.oid)
                    .is_some_and(|pending| {
                        pending.fields.keys().any(|field| {
                            !matches!(field.as_str(), "OID" | "Address" | "TagName" | "Value")
                        }) || self.db_pending.values().any(|child| {
                            child.project == project && child.parent == format!("!{}", source.oid)
                        })
                    })
            {
                return Some(err(tag, 408, "408 Operation failed: Associated Level copy with retained payload is unsupported"));
            }
            if source.addressed {
                if let (Some(level), Some(pending)) = (
                    self.level(&source.oid),
                    self.pending_object(project, &source.oid),
                ) {
                    let mirror = pending
                        .fields
                        .get("Value")
                        .filter(|value| !value.is_empty());
                    if mirror.map(|value| value.parse::<u8>().ok()) != level.value.map(Some) {
                        return Some(err(tag, 408, "408 Operation failed: Associated Level Value mirror disagrees with its owner"));
                    }
                }
            }
            if safe && (!source.addressed || self.level(&source.oid).is_none()) {
                return Some(failure("SAFE Level source has no typed record"));
            }
            // An incomplete unsafe destination remains outside the existing
            // copy owner: do not fabricate an addressed route or project.
            if !parent.addressed {
                return Some(failure("Associated copy destination is not addressed"));
            }
            let source_oid = format!("!{}", source.oid);
            rewritten[1] = &source_oid;
            rewritten[2] = &parent.canonical;
            let source_value = self.level(&source.oid).map(|level| level.value);
            let mut staged = self.clone();
            let response = if safe {
                staged.dbcopy(tag, &rewritten)
            } else {
                staged
                    .handle_manual_command(tag, &rewritten, &rewritten.join(" "))
                    .expect("DBCOPY has an established manual owner")
            };
            if response.status != 301 {
                return Some(response);
            }
            let Some(oid) = response
                .final_text
                .strip_prefix("301 OID=")
                .filter(|oid| !oid.is_empty() && *oid != source.oid)
            else {
                return Some(err(
                    tag,
                    408,
                    "408 Operation failed: Invalid associated Level copy receipt",
                ));
            };
            if safe {
                let Some(level) = staged.level_mut(oid) else {
                    return Some(err(
                        tag,
                        408,
                        "408 Operation failed: Associated Level copy owner missing",
                    ));
                };
                // One staged operation owns Value and the admitted empty XML
                // payload before301, without a second command/implicit save.
                level.value = source_value.expect("typed Level checked");
            } else if staged
                .pending_object(project, oid)
                .is_none_or(|pending| pending.element != "Level")
            {
                return Some(err(
                    tag,
                    408,
                    "408 Operation failed: Associated pending Level copy owner missing",
                ));
            }
            let mut destination_extras = source_extras;
            if !destination_extras.children.is_empty() {
                // A copied supported empty collection uses the existing
                // canonical representation; source bytes remain untouched.
                destination_extras.children = vec!["<TagsDLT/>".to_string()];
            }
            staged.store_db_xml_extras(project, oid, &destination_extras);
            *self = staged;
            Some(response)
        } else {
            rewritten[1] = &parent.canonical;
            Some(if safe {
                self.dbadd(tag, &rewritten)
            } else {
                self.handle_manual_command(tag, &rewritten, &rewritten.join(" "))
                    .expect("DBADD has an established manual owner")
            })
        }
    }

    pub(crate) fn tag_database_command(&mut self, tag: &str, words: &[&str]) -> Option<Response> {
        if let Some(response) = self.numeric_language_command(tag, words) {
            return Some(response);
        }
        let verb = words.first()?.to_ascii_uppercase();
        if verb == "DBGET" && words.len() == 2 {
            let path = words[1];
            let qualified = path
                .strip_prefix("//")
                .and_then(|rest| rest.split_once("/Installation/Project/OID"))
                .filter(|(_, suffix)| suffix.is_empty())
                .map(|(project, _)| project);
            let project = qualified.or(self.current.as_deref());
            if let Some(oid) = project.and_then(|project| self.named_project_oid(project)) {
                if qualified.is_some()
                    || path == "Installation/Project/OID"
                    || path == format!("!{oid}/OID")
                {
                    return Some(Response {
                        tag: tag.to_string(),
                        lines: Vec::new(),
                        final_text: format!("342 {path}={oid}"),
                        status: 342,
                    });
                }
            }
        }
        if matches!(
            verb.as_str(),
            "DBGET"
                | "DBSET"
                | "DBSETSAFE"
                | "DBDELETE"
                | "DBADD"
                | "DBADDSAFE"
                | "DBCOPY"
                | "DBCOPYSAFE"
        ) {
            if let Some(rest) = words.get(1).and_then(|path| path.strip_prefix('!')) {
                let (oid, suffix) = rest.split_once('/').unwrap_or((rest, ""));
                if self
                    .current
                    .as_deref()
                    .and_then(|project| self.named_project_oid(project))
                    == Some(oid)
                {
                    // Only wrapper identity and the Network-copy destination
                    // are modeled. Do not fabricate a Project descendant or
                    // acknowledge writes into a second opaque field store.
                    if matches!(verb.as_str(), "DBSET" | "DBSETSAFE")
                        && suffix.eq_ignore_ascii_case("OID")
                    {
                        return Some(err(
                            tag,
                            408,
                            "408 Operation failed: OID field can not be changed",
                        ));
                    }
                    return Some(err(
                        tag,
                        401,
                        "401 Bad object or device ID: Unsupported Project OID operation",
                    ));
                }
            }
        }
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
                | "DBVALIDATE"
        ) {
            return None;
        }
        if let Some(response) = self.associated_level_value_command(tag, words) {
            return Some(response);
        }
        if let Some(response) = self.associated_level_command(tag, words) {
            return Some(response);
        }
        if matches!(verb.as_str(), "DBCOPY" | "DBCOPYSAFE")
            && words
                .get(1)
                .is_some_and(|source| self.associated_raw_level_copy_source(source))
        {
            return Some(err(
                tag,
                408,
                "408 Operation failed: Associated raw Level subtree copy is unsupported",
            ));
        }
        let path = words.get(1)?;
        let qualified_project = path
            .strip_prefix("//")
            .and_then(|rest| rest.split('/').next());
        let selection_project =
            if matches!(verb.as_str(), "DBGET" | "DBGETXML" | "DBADD" | "DBADDSAFE") {
                qualified_project.or(self.current.as_deref())
            } else {
                self.current.as_deref()
            };
        let selected = match self.tag_selection_in_with_application_coordinates(
            path,
            selection_project,
            matches!(verb.as_str(), "DBGET" | "DBGETXML" | "DBSETSAFE"),
        ) {
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
            Err(error) => return Some(err(tag, 401, &format!("401 {error}"))),
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
            let Some(interface) = record.optional_interface() else {
                return Some(err(
                    tag,
                    401,
                    if matches!(verb.as_str(), "DBSET" | "DBSETSAFE") {
                        "401 Bad object or device ID: Field not found"
                    } else if selected.field.as_deref() == Some("InterfaceType") {
                        "401 Bad object or device ID: Element InterfaceType not found"
                    } else {
                        "401 Bad object or device ID: Element InterfaceAddress not found"
                    },
                ));
            };
            interface
        } else {
            record.root.at(&selected.indices)
        };
        if matches!(verb.as_str(), "DBCOPY" | "DBCOPYSAFE")
            && record.database_network.is_some()
            && node.untyped_level_value()
        {
            return Some(err(
                tag,
                408,
                "408 Operation failed: Associated raw Level subtree copy is unsupported",
            ));
        }
        if verb == "DBVALIDATE" {
            if words.len() != 2 || selected.field.is_some() {
                return Some(err(tag, 400, "400 Syntax Error."));
            }
            if node.null_tag_name() || node.null_level_value() {
                return Some(err(
                    tag,
                    408,
                    "408 Operation failed: Incomplete named graph cannot be validated",
                ));
            }
            return Some(Response {
                tag: tag.to_string(),
                lines: Vec::new(),
                final_text: format!("233 {}: Valid", node.element),
                status: 233,
            });
        }
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
                    if node.null_tag_name() {
                        err(tag, 444, "444 Unable to get XML: Object is null")
                    } else {
                        Self::db_xml_response(tag, node.document())
                    }
                } else {
                    err(tag, 401, "401 Object not found")
                });
            }
            return Some(if let Some(field) = selected.field {
                if let Some(kind) = field.strip_suffix("/OID").filter(|kind| child_type(kind)) {
                    let children = node
                        .children
                        .iter()
                        .filter(|child| child.element == kind)
                        .collect::<Vec<_>>();
                    if children.is_empty() {
                        return Some(err(
                            tag,
                            401,
                            &format!("401 Bad object or device ID: Field {kind} not found"),
                        ));
                    }
                    let base = path.strip_suffix(&field).unwrap_or(path);
                    let mut rows = children
                        .iter()
                        .enumerate()
                        .filter_map(|(index, child)| {
                            child.field("OID").map(|oid| {
                                if kind == "Interface" {
                                    format!("{base}Interface/OID={oid}")
                                } else {
                                    format!("{base}{kind}[{}]/OID={oid}", index + 1)
                                }
                            })
                        })
                        .collect::<Vec<_>>();
                    let Some(last) = rows.pop() else {
                        return Some(err(
                            tag,
                            401,
                            "401 Bad object or device ID: Element OID not found.",
                        ));
                    };
                    return Some(Response {
                        tag: tag.to_string(),
                        lines: rows.into_iter().map(|row| format!("342-{row}")).collect(),
                        final_text: format!("342 {last}"),
                        status: 342,
                    });
                }
                let Some(value) = node.field(&field) else {
                    return Some(err(
                        tag,
                        401,
                        if matches!(field.as_str(), "Address" | "TagName" | "Value")
                            && !(node.element == "NetVar" && field == "Value")
                        {
                            "401 Bad object or device ID: Object is null"
                        } else {
                            "401 Bad object or device ID: Element Value not found."
                        },
                    ));
                };
                let output_path = if selected.indices.is_empty() {
                    path.strip_prefix(&format!("//{}/", selected.project))
                        .unwrap_or(path)
                } else {
                    path
                };
                let output_path = output_path
                    .split('/')
                    .map(|part| {
                        if indexed_type(part).is_some_and(|(kind, _)| kind == "Interface") {
                            "Interface"
                        } else {
                            part
                        }
                    })
                    .collect::<Vec<_>>()
                    .join("/");
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
            && !words.get(2).is_some_and(|element| {
                matches!(
                    element.to_ascii_lowercase().as_str(),
                    "languages" | "language"
                )
            })
        {
            // Existing numeric children retain their established pending and
            // typed creation owner. Reads rehydrate from that current owner.
            return None;
        }
        if matches!(verb.as_str(), "DBADD" | "DBADDSAFE") {
            return Some(self.add_named_tag_child(tag, words, &selected, &record));
        }
        if matches!(node.element.as_str(), "Languages" | "Language")
            && matches!(
                verb.as_str(),
                "DBSET" | "DBSETSAFE" | "DBDELETE" | "DBCOPY" | "DBCOPYSAFE"
            )
        {
            if matches!(verb.as_str(), "DBCOPY" | "DBCOPYSAFE") {
                return Some(err(
                    tag,
                    408,
                    "408 Operation failed: standalone language copy is unsupported",
                ));
            }
            let mut replacement = record.clone();
            if verb == "DBDELETE" {
                if words.len() != 2 || selected.field.is_some() {
                    return Some(err(tag, 400, "400 Syntax Error."));
                }
                let (last, parent) = selected.indices.split_last().expect("language child");
                let mut index = 0;
                replacement.root.at_mut(parent).retain_children(|_| {
                    let keep = index != *last;
                    index += 1;
                    keep
                });
            } else {
                let Some(field @ ("ID" | "TagValue")) = selected
                    .field
                    .as_deref()
                    .filter(|_| node.element == "Language")
                else {
                    return Some(err(
                        tag,
                        401,
                        "401 Bad object or device ID: Field not found",
                    ));
                };
                if verb == "DBSETSAFE" && words.len() < 3 {
                    return Some(err(tag, 400, "400 Field value required"));
                }
                let mut value = words.get(2..).unwrap_or_default().join(" ");
                if field == "ID" {
                    let Ok(id) = value.parse::<i32>() else {
                        return Some(err(
                            tag,
                            408,
                            "408 Operation failed: Language ID must be an integer",
                        ));
                    };
                    value = id.to_string();
                }
                if !value.chars().all(|character| {
                    matches!(character,
                    '\u{9}' | '\u{A}' | '\u{D}' | '\u{20}'..='\u{D7FF}'
                        | '\u{E000}'..='\u{FFFD}' | '\u{10000}'..='\u{10FFFF}')
                }) {
                    return Some(err(
                        tag,
                        408,
                        "408 Operation failed: Language value is not representable in XML",
                    ));
                }
                replacement.root.at_mut(&selected.indices).set(field, value);
            }
            self.replace_language_record(&selected.project, &selected.key, replacement);
            return Some(crate::ok(tag, Vec::new(), "200 OK."));
        }
        if matches!(verb.as_str(), "DBCOPY" | "DBCOPYSAFE") && record.database_network.is_none() {
            return Some(self.copy_named_tag_node(tag, words, &selected, &record));
        }
        if let Some(address) = record.database_network {
            if (node.element == "Unit"
                || (path.starts_with('!')
                    && matches!(
                        node.element.as_str(),
                        "Application" | "Group" | "Level" | "NetVar"
                    ))
                || (matches!(node.element.as_str(), "Application" | "Group")
                    && selected.field.as_deref() == Some("TagName"))
                || (node.element == "Application"
                    && selected.field.as_deref() == Some("Address")
                    && verb == "DBSETSAFE"))
                && matches!(verb.as_str(), "DBSET" | "DBSETSAFE" | "DBDELETE")
            {
                // The existing database owner also mirrors Application/Group
                // TagName and SAFE Application Address edits. Replacing the
                // whole Network for that scalar
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
                    let coordinate = current.field("Address").unwrap_or_default();
                    if verb == "DBSETSAFE" && current.element == "Application" {
                        // An Application retains the admitted Address lexeme
                        // in XML, but its typed owner uses a decimal path.
                        let canonical =
                            coordinate.parse::<u8>().ok().map(|value| value.to_string());
                        path.push_str(canonical.as_deref().unwrap_or(coordinate));
                    } else {
                        path.push_str(coordinate);
                    }
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
                        if record.database_network.is_none() {
                            let admitted = node.element == "Unit"
                                || matches!(field, "TagName" | "Address" | "Description")
                                || (node.element == "Network"
                                    && matches!(
                                        field,
                                        "NetworkNumber" | "InterfaceType" | "InterfaceAddress"
                                    ))
                                || (node.element == "Interface"
                                    && matches!(field, "InterfaceType" | "InterfaceAddress"))
                                || (node.element == "Property"
                                    && matches!(field, "Name" | "Value"))
                                || (node.element == "Level" && field == "Value");
                            if !admitted {
                                return Some(err(
                                    tag,
                                    401,
                                    "401 Bad object or device ID: Field not found",
                                ));
                            }
                            if verb == "DBSETSAFE" && field == "Address" {
                                if (node.element == "Network" && !valid_address(&value))
                                    || (node.element != "Network" && value.parse::<u8>().is_err())
                                {
                                    return Some(err(
                                        tag,
                                        401,
                                        "401 Bad object or device ID: Invalid address",
                                    ));
                                }
                                let collision =
                                    if let Some((_, parent)) = selected.indices.split_last() {
                                        Self::named_address_collision(
                                            record.root.at(parent),
                                            &node.element,
                                            &value,
                                            node.field("OID"),
                                        )
                                    } else {
                                        self.projects[&selected.project].tag_networks.values().any(
                                            |other| {
                                                other.root.field("Address") == Some(value.as_str())
                                                    && other.root.field("OID") != node.field("OID")
                                            },
                                        ) || canonical_address(&value).is_some_and(|address| {
                                            self.projects[&selected.project]
                                                .networks
                                                .contains_key(&address)
                                        })
                                    };
                                if collision {
                                    return Some(err(
                                        tag,
                                        401,
                                        "401 Bad object or device ID: Element address in use",
                                    ));
                                }
                            }
                        }
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
                            .replace_internal_tag_record(
                                &selected.project,
                                &selected.key,
                                replacement,
                            )
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
                        .replace_internal_tag_record(&selected.project, &selected.key, replacement)
                        .map(|()| "200 OK.".to_string())
                }
            }
            "DBRENAMENET" | "DBRENAMENETSAFE" => {
                if words.len() != 3
                    || !selected.indices.is_empty()
                    || selected.field.is_some()
                    || !valid_address(words[2])
                {
                    Err("Invalid network rename".to_string())
                } else if verb == "DBRENAMENETSAFE"
                    && record.root.field("Address") != Some(words[2])
                    && (staged.projects[&selected.project]
                        .tag_networks
                        .values()
                        .any(|other| {
                            other.root.field("Address") == Some(words[2])
                                && other.root.field("OID") != record.root.field("OID")
                        })
                        || canonical_address(words[2]).is_some_and(|address| {
                            record.database_network != Some(address)
                                && staged.projects[&selected.project]
                                    .networks
                                    .contains_key(&address)
                        }))
                {
                    Err("Destination Network already exists".to_string())
                } else {
                    let mut replacement = record.clone();
                    replacement.root.set("Address", words[2].to_string());
                    staged
                        .replace_internal_tag_record(&selected.project, &selected.key, replacement)
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
        let parsed = match roxmltree::Document::parse(document) {
            Ok(parsed) => parsed,
            Err(error) => return Some(err(tag, 446, &format!("446 Unable to set XML: {error}"))),
        };
        if record.database_network.is_none()
            && selected.indices.len() == 1
            && record.root.at(&selected.indices).element == "Unit"
        {
            // A Unit replacement owns only that Unit. Re-admitting the whole
            // Network would reject or project unrelated raw/incomplete data.
            // Keep external Network admission strict, and validate the complete
            // replacement Unit and its identity conflicts before one commit.
            let unit = match crate::parse_db_xml_unit(parsed.root_element()) {
                Ok(unit) => unit,
                Err(error) if error == crate::DB_XML_UNIT_NAME_REQUIRED => {
                    return Some(crate::db_xml_missing_unit_name(tag, false));
                }
                Err(error) => return Some(err(tag, 400, &format!("400 {error}"))),
            };
            let replacement = match parse_node(parsed.root_element()) {
                Ok(node) => node,
                Err(error) => {
                    return Some(err(tag, 446, &format!("446 Unable to set XML: {error}")))
                }
            };
            let target_index = selected.indices[0];
            if record
                .root
                .children
                .iter()
                .enumerate()
                .any(|(index, child)| {
                    index != target_index
                        && child.element == "Unit"
                        && child.field("Address") == replacement.field("Address")
                })
            {
                return Some(err(
                    tag,
                    409,
                    "409 DBSETXML destination unit address already exists",
                ));
            }
            let own = record.root.oids().into_iter().collect::<HashSet<_>>();
            let active = self.active_db_oids(&selected.project);
            if replacement
                .oids()
                .iter()
                .any(|oid| active.contains(oid) && !own.contains(oid))
            {
                return Some(err(
                    tag,
                    409,
                    "409 DBSETXML OID already exists in the selected project",
                ));
            }
            fn identities<'a>(node: &'a TagNode, rows: &mut Vec<(&'a str, &'a str)>) {
                if let Some(oid) = node.field("OID") {
                    rows.push((oid, &node.element));
                }
                for child in &node.children {
                    identities(child, rows);
                }
            }
            fn conflicts(node: &TagNode, oid: &str, kind: &str, target: &TagNode) -> bool {
                if std::ptr::eq(node, target) {
                    return false;
                }
                (node.field("OID") == Some(oid)
                    && !matches!(
                        (node.element.as_str(), kind),
                        ("Unit" | "Application", "Unit" | "Application")
                    ))
                    || node
                        .children
                        .iter()
                        .any(|child| conflicts(child, oid, kind, target))
            }
            let mut submitted = Vec::new();
            identities(&replacement, &mut submitted);
            let mut seen = BTreeMap::new();
            for (oid, kind) in submitted {
                if !crate::valid_uuid(oid) {
                    return Some(err(
                        tag,
                        400,
                        "400 DBSETXML Unit has an invalid subtree OID",
                    ));
                }
                let duplicate = seen.insert(oid, kind).is_some_and(|previous| {
                    !matches!(
                        (previous, kind),
                        ("Unit" | "Application", "Unit" | "Application")
                    )
                });
                if duplicate
                    || conflicts(&record.root, oid, kind, record.root.at(&selected.indices))
                {
                    return Some(err(
                        tag,
                        409,
                        "409 DBSETXML document contains unsupported duplicate OIDs",
                    ));
                }
            }
            let mut replacement_record = record;
            *replacement_record.root.at_mut(&selected.indices) = replacement;
            let mut staged = self.clone();
            return Some(
                match staged.replace_internal_tag_record(
                    &selected.project,
                    &selected.key,
                    replacement_record,
                ) {
                    Ok(()) => {
                        *self = staged;
                        Response {
                            tag: tag.to_string(),
                            lines: Vec::new(),
                            final_text: format!("301 OID={}", unit.oid),
                            status: 301,
                        }
                    }
                    Err(error) => err(tag, 408, &format!("408 Operation failed: {error}")),
                },
            );
        }
        let replacement = match parse_node(parsed.root_element())
            .map_err(|_| roxmltree::Error::NoRootNode)
        {
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
