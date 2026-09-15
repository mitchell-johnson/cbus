"""Lossless structural editor for legacy C-Gate XML and Toolkit CBZ archives.

Unknown XML, namespaces, comments, processing instructions and archive members are
retained. An unchanged document is saved byte-for-byte; edited XML may have a
normalised declaration or attribute quoting. This does not implement C-Gate 3 SQL
projects or decode device-specific programming parameters.

Entity paths are ``/network/254/application/56/group/1/level/255`` and
``/network/254/unit/12``; ``/`` addresses the project. Numeric compact paths such
as ``/254/56/1`` are accepted for networks/applications/groups/levels.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import copy
from io import BytesIO
import os
from pathlib import Path
import re
import stat
import tempfile
from typing import Any, Iterator, Mapping
from uuid import uuid4
from xml.dom import Node, minidom
from xml.parsers import expat
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile, ZipInfo, is_zipfile


MAX_DOCUMENT_BYTES = 128 * 1024 * 1024
KINDS = {"network": "Network", "application": "Application", "group": "Group", "level": "Level", "unit": "Unit"}
PARENTS = {"Network": "Project", "Application": "Network", "Group": "Application", "Level": "Group", "Unit": "Network"}
ENTITY_NAMES = set(PARENTS) | {"Project"}
_XML_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_.:-]*$")


class ProjectError(ValueError):
    """Invalid project, unsupported format, path or operation."""


class UnsupportedProjectFormat(ProjectError):
    """The input is not a supported legacy XML or CBZ project."""


class IntegrityError(ProjectError):
    """A mutation would break known structural or explicit OID references."""


def _name(node: Node) -> str:
    return node.localName or node.nodeName


def _elements(node: Node, name: str | None = None) -> list[minidom.Element]:
    return [child for child in node.childNodes if child.nodeType == Node.ELEMENT_NODE and (name is None or (_name(child) == name and child.namespaceURI == node.namespaceURI))]


def _all_elements(node: Node) -> Iterator[minidom.Element]:
    if node.nodeType == Node.ELEMENT_NODE:
        yield node
    for child in _elements(node):
        yield from _all_elements(child)


def _is_entity(node: Node) -> bool:
    if node.nodeType != Node.ELEMENT_NODE:
        return False
    parent = node.parentNode
    tag = _name(node)
    if tag == "Project":
        return parent.nodeType == Node.DOCUMENT_NODE or (parent.nodeType == Node.ELEMENT_NODE and _name(parent) == "Installation" and parent.namespaceURI == node.namespaceURI)
    return tag in PARENTS and parent.nodeType == Node.ELEMENT_NODE and node.namespaceURI == parent.namespaceURI and _name(parent) == PARENTS[tag] and _is_entity(parent)


def _text(node: Node) -> str:
    return "".join(c.data for c in node.childNodes if c.nodeType in (Node.TEXT_NODE, Node.CDATA_SECTION_NODE))


def _child(node: Node, name: str) -> minidom.Element | None:
    values = _elements(node, name)
    if len(values) > 1:
        raise IntegrityError(f"Ambiguous field {name!r}: multiple matching elements")
    return values[0] if values else None


def _field(node: Node, name: str, default: str = "") -> str:
    child = _child(node, name)
    return _text(child) if child is not None else default


def _oid(node: minidom.Element) -> str | None:
    attr = next((node.getAttribute(k) for k in node.attributes.keys() if k.lower() == "oid"), None)
    return attr or _field(node, "OID") or None


def _address(value: Any) -> int:
    if isinstance(value, bool):
        raise ProjectError("Address must be an integer from 0 to 255")
    try:
        result = int(str(value), 16 if str(value).lower().startswith("0x") else 10)
    except (TypeError, ValueError) as exc:
        raise ProjectError("Address must be an integer from 0 to 255") from exc
    if not 0 <= result <= 255:
        raise ProjectError("Address must be an integer from 0 to 255")
    return result


def _xml_string(value: Any) -> str:
    value = str(value)
    if any(ord(c) < 32 and c not in "\t\n\r" or 0xD800 <= ord(c) <= 0xDFFF or ord(c) in (0xFFFE, 0xFFFF) for c in value):
        raise ProjectError("Value contains characters forbidden by XML 1.0")
    return value


def _parse_xml(data: bytes) -> minidom.Document:
    if len(data) > MAX_DOCUMENT_BYTES:
        raise ProjectError("XML document exceeds the configured size limit")
    if data.startswith(b"SQLite format 3\x00"):
        raise UnsupportedProjectFormat("C-Gate 3 SQL/SQLite projects are not supported by the legacy XML editor")
    # Reject DTDs before an XML parser can expand any declared entities.
    checker = expat.ParserCreate()
    def reject_doctype(*_args: Any) -> None:
        raise ProjectError("DTD and entity declarations are not supported")
    checker.StartDoctypeDeclHandler = reject_doctype
    try:
        checker.Parse(data, True)
        document = minidom.parseString(data)
    except (expat.ExpatError, UnicodeError) as exc:
        raise UnsupportedProjectFormat("Input is not a supported legacy XML project") from exc
    root = document.documentElement
    if _name(root) == "Project":
        return document
    if _name(root) != "Installation" or len(_elements(root, "Project")) != 1:
        raise UnsupportedProjectFormat("Expected a Project root or Installation containing exactly one Project; SQL and other formats are unsupported")
    return document


class ProjectDocument:
    """A legacy project and its original archive, edited in memory until save()."""

    def __init__(self, document: minidom.Document, original: bytes | None = None, *, source: Path | None = None, archive_members: list[tuple[ZipInfo, bytes]] | None = None, xml_member: str | None = None, archive_comment: bytes = b"") -> None:
        self.document = document
        self.source = source
        self._original = original
        self._members = archive_members
        self.xml_member = xml_member
        self._archive_comment = archive_comment
        self._dirty = original is None
        self._original_dom = document.toxml()

    @property
    def project(self) -> minidom.Element:
        root = self.document.documentElement
        return root if _name(root) == "Project" else _elements(root, "Project")[0]

    @property
    def format(self) -> str:
        return "legacy-cbz" if self._members is not None else "legacy-xml"

    @classmethod
    def load(cls, path: str | os.PathLike[str], *, xml_member: str | None = None) -> ProjectDocument:
        source = Path(path)
        if source.stat().st_size > MAX_DOCUMENT_BYTES:
            raise ProjectError("Project file exceeds the configured size limit")
        data = source.read_bytes()
        if not is_zipfile(BytesIO(data)):
            if xml_member is not None:
                raise ProjectError("xml_member is only valid for a CBZ archive")
            if data.startswith(b"PK"):
                raise UnsupportedProjectFormat("Malformed or unsupported CBZ archive")
            return cls(_parse_xml(data), data, source=source)
        try:
            with ZipFile(BytesIO(data)) as archive:
                infos = archive.infolist()
                if len({i.filename for i in infos}) != len(infos):
                    raise ProjectError("Duplicate archive member names are ambiguous")
                if sum(i.file_size for i in infos) > MAX_DOCUMENT_BYTES:
                    raise ProjectError("Expanded archive exceeds the configured size limit")
                if any(i.flag_bits & 1 for i in infos):
                    raise UnsupportedProjectFormat("Encrypted CBZ archives are unsupported")
                members = [(copy(info), archive.read(info)) for info in infos]
                candidates: list[tuple[str, minidom.Document]] = []
                for info, payload in members:
                    if xml_member is not None and info.filename != xml_member:
                        continue
                    if xml_member is None and not info.filename.lower().endswith(".xml"):
                        continue
                    try:
                        parsed = _parse_xml(payload)
                    except UnsupportedProjectFormat:
                        continue
                    candidates.append((info.filename, parsed))
                if not candidates:
                    raise UnsupportedProjectFormat("Archive has no supported legacy XML project; C-Gate 3 SQL projects are unsupported")
                if len(candidates) != 1:
                    raise ProjectError("Archive contains multiple project XML members; select one with xml_member")
                member, document = candidates[0]
                return cls(document, data, source=source, archive_members=members, xml_member=member, archive_comment=archive.comment)
        except (BadZipFile, RuntimeError, NotImplementedError) as exc:
            raise UnsupportedProjectFormat("Unable to read this CBZ archive") from exc

    @classmethod
    def from_bytes(cls, data: bytes) -> ProjectDocument:
        """Load XML bytes (archives are loaded through load with an explicit path)."""
        return cls(_parse_xml(data), data)

    @classmethod
    def new(cls, name: str, *, address: str = "1", description: str = "", namespace: str | None = None) -> ProjectDocument:
        """Create minimal legacy XML; no fictitious Toolkit/database version is set."""
        name = _xml_string(name)
        if not name.strip():
            raise ProjectError("Project name must not be empty")
        document = minidom.Document()
        root = document.createElementNS(namespace, "Installation")
        if namespace:
            root.setAttribute("xmlns", namespace)
        document.appendChild(root)
        project = document.createElementNS(namespace, "Project")
        root.appendChild(project)
        result = cls(document)
        for key, value in {"TagName": name, "Address": address, "Description": description}.items():
            result._set_field(project, key, value)
        return result

    def _create(self, parent: minidom.Element, name: str) -> minidom.Element:
        if not _XML_NAME.fullmatch(name) or name.count(":") > 1:
            raise ProjectError(f"Invalid XML name: {name!r}")
        if ":" in name:
            prefix = name.split(":", 1)[0]
            current: Node | None = parent
            while current is not None:
                if current.nodeType == Node.ELEMENT_NODE and current.hasAttribute("xmlns:" + prefix):
                    return self.document.createElementNS(current.getAttribute("xmlns:" + prefix), name)
                current = current.parentNode
            raise ProjectError(f"Namespace prefix {prefix!r} is not declared")
        prefix = parent.prefix
        return self.document.createElementNS(parent.namespaceURI, f"{prefix}:{name}" if prefix else name)

    def resolve(self, path: str = "/") -> minidom.Element:
        if path in ("", "/", "project"):
            return self.project
        if path.startswith("oid:"):
            matches = [e for e in _all_elements(self.project) if _oid(e) == path[4:]]
            if len(matches) != 1:
                raise ProjectError("OID does not identify exactly one element")
            return matches[0]
        parts = path.strip("/").split("/")
        if parts and parts[0].lower() == "project":
            parts.pop(0)
        if parts and parts[0].lower() not in KINDS:
            if len(parts) > 4:
                raise ProjectError("Compact paths support network/application/group/level only")
            parts = [item for pair in zip(("network", "application", "group", "level"), parts) for item in pair]
        if len(parts) % 2:
            raise ProjectError("Entity paths require alternating kind/address components")
        current = self.project
        for kind, value in zip(parts[0::2], parts[1::2]):
            tag = KINDS.get(kind.lower())
            if tag is None or PARENTS[tag] != _name(current):
                raise ProjectError(f"Invalid entity hierarchy at {kind!r}")
            address = _address(value)
            matches = [e for e in _elements(current, tag) if _is_entity(e) and _address(_field(e, "Address")) == address]
            if len(matches) != 1:
                raise ProjectError(f"Path {path!r} does not identify exactly one entity")
            current = matches[0]
        return current

    def path_of(self, node: minidom.Element) -> str:
        parts = []
        current: Node | None = node
        while current is not None and current is not self.project:
            if _is_entity(current) and _name(current) in PARENTS:
                addresses = _elements(current, "Address")
                parts[0:0] = [_name(current).lower(), _text(addresses[0]) if addresses else "?"]
            current = current.parentNode
        return "/" + "/".join(parts)

    def get(self, path: str = "/") -> dict[str, Any]:
        node = self.resolve(path)
        return {"kind": _name(node).lower(), "path": self.path_of(node), "attributes": dict(node.attributes.items()), "fields": {_name(c): _text(c) for c in _elements(node) if not _elements(c) and _name(c) not in ENTITY_NAMES | {"PP"}}, "children": {kind.lower(): len(_elements(node, kind)) for kind, parent in PARENTS.items() if parent == _name(node)}}

    @property
    def metadata(self) -> dict[str, str]:
        return self.get()["fields"]

    def list_entities(self, path: str = "/", *, kind: str | None = None, recursive: bool = False) -> list[dict[str, Any]]:
        node = self.resolve(path)
        if kind is not None and kind.lower() not in KINDS:
            raise ProjectError(f"Unknown entity kind {kind!r}")
        tag = KINDS[kind.lower()] if kind is not None else None
        nodes = list(_all_elements(node))[1:] if recursive else _elements(node)
        return [self.get(self.path_of(e)) for e in nodes if _is_entity(e) and _name(e) in PARENTS and (tag is None or _name(e) == tag)]

    def inspect(self) -> dict[str, Any]:
        return {"format": self.format, "xml_member": self.xml_member, "project": self.get(), "counts": {kind: sum(_is_entity(e) and _name(e) == tag for e in _all_elements(self.project)) for kind, tag in KINDS.items()}, "archive_members": [info.filename for info, _ in self._members] if self._members else [], "validation": self.validate(), "limitations": ["Legacy XML/CBZ only; C-Gate 3 SQL projects are unsupported.", "Device-specific PP/program-block semantics and address references are opaque and are not validated or rewritten.", "Edits preserve XML structure and namespace prefixes; XML declaration and quoting may be normalised."]}

    def validate(self) -> list[dict[str, str]]:
        issues: list[dict[str, str]] = []
        def issue(code: str, node: minidom.Element, message: str, severity: str = "error") -> None:
            issues.append({"severity": severity, "code": code, "path": self.path_of(node), "message": message})
        oids: dict[str, minidom.Element] = {}
        for node in _all_elements(self.document.documentElement):
            for name in ("OID", "Address", "TagName", "Description"):
                if _is_entity(node) and len(_elements(node, name)) > 1:
                    issue("duplicate-field", node, f"Multiple {name} fields")
            try:
                oid = _oid(node)
            except IntegrityError:
                oid = None
            if oid:
                if oid in oids:
                    issue("duplicate-oid", node, "OID is already used by another element")
                oids[oid] = node
            tag = _name(node)
            if tag in PARENTS and node.namespaceURI == self.project.namespaceURI and (_is_entity(node) or _elements(node, "Address")):
                if node.parentNode.nodeType != Node.ELEMENT_NODE or _name(node.parentNode) != PARENTS[tag]:
                    issue("invalid-parent", node, f"{tag} must be a child of {PARENTS[tag]}")
                try:
                    _address(_field(node, "Address"))
                except ProjectError:
                    issue("invalid-address", node, f"{tag} Address must be an integer from 0 to 255")
            if _is_entity(node) and tag == "Level" and node.hasAttribute("Value"):
                try:
                    _address(node.getAttribute("Value"))
                except ProjectError:
                    issue("invalid-level", node, "Level Value must be an integer from 0 to 255")
            for child_tag in PARENTS:
                seen: set[int] = set()
                for child in _elements(node, child_tag):
                    if not _is_entity(child):
                        continue
                    try:
                        address = _address(_field(child, "Address"))
                    except ProjectError:
                        continue
                    if address in seen:
                        issue("duplicate-address", child, f"Duplicate {child_tag} address {address} in one parent")
                    seen.add(address)
            if _is_entity(node) and tag == "Unit":
                seen_names: set[str] = set()
                for pp in _elements(node, "PP"):
                    name = pp.getAttribute("Name")
                    if not pp.hasAttribute("Name") or not pp.hasAttribute("Value"):
                        issue("invalid-parameter", node, "PP requires Name and Value attributes")
                    if name in seen_names:
                        issue("duplicate-parameter", node, f"Duplicate PP name {name!r}")
                    seen_names.add(name)
        return issues

    def assert_valid(self) -> None:
        errors = [i for i in self.validate() if i["severity"] == "error"]
        if errors:
            raise IntegrityError("; ".join(f"{i['path']}: {i['message']}" for i in errors))

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        before = self.document.cloneNode(True)
        dirty = self._dirty
        try:
            yield
            self.assert_valid()
            self._dirty = True
        except Exception:
            self.document = before
            self._dirty = dirty
            raise

    def _field_target(self, node: minidom.Element, field: str, *, create: bool = False) -> tuple[minidom.Element, str | None]:
        parts = field.split("/")
        if not field or any(not p or p in (".", "..") for p in parts):
            raise ProjectError("Field must be a relative XML path without empty or dot components")
        current = node
        for index, part in enumerate(parts):
            if part.startswith("@"):
                if index != len(parts) - 1 or not _XML_NAME.fullmatch(part[1:]):
                    raise ProjectError("An attribute must be the final field path component")
                return current, part[1:]
            if not _XML_NAME.fullmatch(part):
                raise ProjectError(f"Invalid XML field name {part!r}")
            # A bare name matches local names in the project's namespace. A
            # prefixed name is exact, permitting explicitly selected extensions.
            matches = [e for e in _elements(current) if (e.nodeName == part if ":" in part else (_name(e) == part and e.namespaceURI == current.namespaceURI))]
            if len(matches) > 1:
                raise ProjectError(f"Field {field!r} is ambiguous")
            if not matches:
                if not create:
                    raise ProjectError(f"Field {field!r} does not exist")
                child = self._create(current, part)
                current.appendChild(child)
                current = child
            else:
                current = matches[0]
        return current, None

    def get_field(self, path: str, field: str) -> str:
        target, attribute = self._field_target(self.resolve(path), field)
        if attribute is not None:
            if not target.hasAttribute(attribute):
                raise ProjectError(f"Attribute {attribute!r} does not exist")
            return target.getAttribute(attribute)
        if _elements(target):
            raise ProjectError("Field contains nested XML; use raw_xml to inspect it")
        return _text(target)

    def _set_field(self, node: minidom.Element, field: str, value: Any) -> None:
        value = _xml_string(value)
        target, attribute = self._field_target(node, field, create=True)
        if attribute is not None:
            if attribute == "xmlns" or attribute.startswith("xmlns:"):
                raise ProjectError("Namespace declarations cannot be changed through field editing")
            if ":" in attribute:
                # Reuse namespace lookup and validation from element creation.
                namespace = self._create(target, attribute).namespaceURI
                target.setAttributeNS(namespace, attribute, value)
            else:
                target.setAttribute(attribute, value)
            return
        self._set_text(target, value)

    def _set_text(self, target: minidom.Element, value: str) -> None:
        if _elements(target):
            raise ProjectError("Replacing a field containing nested XML would discard data")
        texts = [c for c in target.childNodes if c.nodeType in (Node.TEXT_NODE, Node.CDATA_SECTION_NODE)]
        if texts:
            first = texts[0]
            if first.nodeType == Node.CDATA_SECTION_NODE and "]]>" in value:
                target.replaceChild(self.document.createTextNode(value), first)
            else:
                first.data = value
            for extra in texts[1:]:
                target.removeChild(extra)
        else:
            target.appendChild(self.document.createTextNode(value))

    def set_field(self, path: str, field: str, value: Any) -> dict[str, Any]:
        return self.update(path, {field: value})

    def update(self, path: str, fields: Mapping[str, Any]) -> dict[str, Any]:
        with self._transaction():
            node = self.resolve(path)
            old_oids = {_oid(e) for e in _all_elements(node)} - {None}
            for field, value in fields.items():
                self._set_field(node, field, value)
            removed_oids = old_oids - {_oid(e) for e in _all_elements(node)}
            if removed_oids and self._references(removed_oids):
                raise IntegrityError("Cannot change an OID referenced outside this subtree")
            result = self.get(self.path_of(node))
        return result

    def remove_field(self, path: str, field: str) -> None:
        with self._transaction():
            target, attribute = self._field_target(self.resolve(path), field)
            if attribute is not None:
                if attribute == "xmlns" or attribute.startswith("xmlns:"):
                    raise ProjectError("Namespace declarations cannot be removed")
                if not target.hasAttribute(attribute):
                    raise ProjectError("Attribute does not exist")
                if attribute.lower() == "oid" and self._references({target.getAttribute(attribute)}):
                    raise IntegrityError("Cannot remove a referenced OID")
                target.removeAttribute(attribute)
            else:
                if _name(target) in ENTITY_NAMES or _elements(target):
                    raise ProjectError("Use entity deletion for entities; nested raw XML cannot be removed as a scalar field")
                removed_oid = _text(target) if _name(target) == "OID" else None
                if removed_oid and self._references({removed_oid}, exclude=target):
                    raise IntegrityError("Cannot remove a referenced OID")
                target.parentNode.removeChild(target)

    def add(self, kind: str, parent: str = "/", *, address: int, name: str = "", description: str | None = None, fields: Mapping[str, Any] | None = None) -> dict[str, Any]:
        tag = KINDS.get(kind.lower())
        if tag is None:
            raise ProjectError(f"Unknown entity kind {kind!r}")
        address = _address(address)
        with self._transaction():
            parent_node = self.resolve(parent)
            if _name(parent_node) != PARENTS[tag]:
                raise ProjectError(f"{tag} requires a {PARENTS[tag]} parent")
            node = self._create(parent_node, tag)
            parent_node.appendChild(node)
            # Follow the existing project's OID representation when it has one.
            example = next((e for e in _all_elements(self.project) if _oid(e)), None)
            if example is not None:
                attribute = next((k for k in example.attributes.keys() if k.lower() == "oid"), None)
                self._set_field(node, "@" + attribute if attribute else "OID", str(uuid4()))
            for key, value in {"TagName": name, "Address": str(address)}.items():
                self._set_field(node, key, value)
            if description is not None:
                self._set_field(node, "Description", description)
            if tag == "Level":
                node.setAttribute("Value", str(address))
            for key, value in (fields or {}).items():
                self._set_field(node, key, value)
            result = self.get(self.path_of(node))
        return result

    def _references(self, identifiers: set[str], *, exclude: minidom.Element | None = None) -> list[str]:
        """Find exact explicit OID references; opaque PP address vectors are not inferred."""
        excluded = set(_all_elements(exclude)) if exclude is not None else set()
        references = []
        for element in _all_elements(self.document.documentElement):
            if element in excluded:
                continue
            for attr, value in element.attributes.items():
                if attr.lower() != "oid" and value in identifiers:
                    references.append(self.path_of(element) + "/@" + attr)
            if _name(element) != "OID" and not _elements(element) and _text(element) in identifiers:
                references.append(self.path_of(element) + "/" + _name(element))
        return references

    def delete(self, path: str, *, cascade: bool = False) -> None:
        with self._transaction():
            node = self.resolve(path)
            if node is self.project:
                raise ProjectError("The project root cannot be deleted")
            if any(_name(e) in PARENTS for e in _elements(node)) and not cascade:
                raise IntegrityError("Entity has children; cascade=True is required to delete its subtree")
            identifiers = {_oid(e) for e in _all_elements(node)} - {None}
            if self._references(identifiers, exclude=node):
                raise IntegrityError("Entity is referenced by an explicit OID outside its subtree")
            node.parentNode.removeChild(node)

    def _clone(self, node: minidom.Element) -> minidom.Element:
        clone = node.cloneNode(True)
        mapping: dict[str, str] = {}
        for element in _all_elements(clone):
            identifier = _oid(element)
            if identifier:
                fresh = mapping.setdefault(identifier, str(uuid4()))
                attribute = next((k for k in element.attributes.keys() if k.lower() == "oid"), None)
                self._set_field(element, "@" + attribute if attribute else "OID", fresh)
        for element in _all_elements(clone):
            for attribute, value in list(element.attributes.items()):
                if attribute.lower() != "oid" and value in mapping:
                    element.setAttribute(attribute, mapping[value])
            if _name(element) != "OID" and not _elements(element) and _text(element) in mapping:
                self._set_text(element, mapping[_text(element)])
        return clone

    def copy(self, source: str, parent: str, *, address: int | None = None, name: str | None = None) -> dict[str, Any]:
        return self._transfer(source, parent, address=address, name=name, move=False)

    def move(self, source: str, parent: str, *, address: int | None = None, name: str | None = None) -> dict[str, Any]:
        return self._transfer(source, parent, address=address, name=name, move=True)

    def _transfer(self, source: str, parent: str, *, address: int | None, name: str | None, move: bool) -> dict[str, Any]:
        with self._transaction():
            original = self.resolve(source)
            destination = self.resolve(parent)
            tag = _name(original)
            if tag not in PARENTS or PARENTS[tag] != _name(destination):
                raise ProjectError("Entity type is incompatible with the destination parent")
            namespace_scope: dict[str, str] = {}
            ancestors: list[minidom.Element] = []
            ancestor = original
            while ancestor.nodeType == Node.ELEMENT_NODE:
                ancestors.insert(0, ancestor)
                ancestor = ancestor.parentNode
            for ancestor in ancestors:
                namespace_scope.update({key: value for key, value in ancestor.attributes.items() if key == "xmlns" or key.startswith("xmlns:")})
            node = original if move else self._clone(original)
            for key, value in namespace_scope.items():
                node.setAttribute(key, value)
            if move:
                original.parentNode.removeChild(original)
            destination.appendChild(node)
            if address is not None:
                self._set_field(node, "Address", str(_address(address)))
            if name is not None:
                self._set_field(node, "TagName", name)
            result = self.get(self.path_of(node))
        return result

    def parameters(self, unit: str) -> dict[str, str]:
        node = self.resolve(unit)
        if _name(node) != "Unit":
            raise ProjectError("Programming parameters belong to units")
        parameters = _elements(node, "PP")
        if len({p.getAttribute("Name") for p in parameters}) != len(parameters):
            raise IntegrityError("Unit has duplicate PP names")
        return {p.getAttribute("Name"): p.getAttribute("Value") for p in parameters}

    def set_parameter(self, unit: str, name: str, value: str) -> None:
        name, value = _xml_string(name), _xml_string(value)
        with self._transaction():
            self.parameters(unit)
            node = self.resolve(unit)
            parameter = next((p for p in _elements(node, "PP") if p.getAttribute("Name") == name), None)
            if parameter is None:
                parameter = self._create(node, "PP")
                parameter.setAttribute("Name", name)
                node.appendChild(parameter)
            parameter.setAttribute("Value", value)

    def delete_parameter(self, unit: str, name: str) -> None:
        with self._transaction():
            self.parameters(unit)
            node = self.resolve(unit)
            parameter = next((p for p in _elements(node, "PP") if p.getAttribute("Name") == name), None)
            if parameter is None:
                raise ProjectError("Programming parameter does not exist")
            node.removeChild(parameter)

    def raw_xml(self, path: str | None = None) -> str:
        return self.document.toxml() if path is None else self.resolve(path).toxml()

    def to_xml_bytes(self) -> bytes:
        if not self._dirty and self._original is not None and self.document.toxml() == self._original_dom:
            if self._members is None:
                return self._original
            return next(data for info, data in self._members if info.filename == self.xml_member)
        return self.document.toxml(encoding="utf-8")

    def save(self, path: str | os.PathLike[str] | None = None, *, format: str | None = None) -> Path:
        """Validate, write and fsync a sibling temporary file, then atomically replace.

        Existing documents retain their format regardless of filename. Set format
        to 'xml' or 'cbz' for explicit conversion (XML export excludes attachments).
        """
        target = Path(path) if path is not None else self.source
        if target is None:
            raise ProjectError("A save path is required")
        if target.is_symlink():
            raise ProjectError("Refusing to replace a symbolic-link project path")
        self.assert_valid()
        if format not in (None, "xml", "cbz", "legacy-xml", "legacy-cbz"):
            raise UnsupportedProjectFormat("Output format must be legacy XML or CBZ")
        output_format = self.format if format is None else ("legacy-cbz" if format in ("cbz", "legacy-cbz") else "legacy-xml")
        if self._original is not None and not self._dirty and self.document.toxml() == self._original_dom and output_format == self.format:
            payload = self._original
        elif output_format == "legacy-xml":
            payload = self.to_xml_bytes()
        else:
            buffer = BytesIO()
            with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
                archive.comment = self._archive_comment
                if self._members is not None:
                    for info, member_data in self._members:
                        archive.writestr(copy(info), self.to_xml_bytes() if info.filename == self.xml_member else member_data)
                else:
                    archive.writestr("project.xml", self.to_xml_bytes())
            payload = buffer.getvalue()
        mode = stat.S_IMODE(target.stat().st_mode) if target.exists() else 0o600
        temporary: str | None = None
        try:
            descriptor, temporary = tempfile.mkstemp(prefix="." + target.name + ".", suffix=".tmp", dir=target.parent)
            with os.fdopen(descriptor, "wb") as stream:
                os.fchmod(stream.fileno(), mode)
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
            temporary = None
        finally:
            if temporary is not None:
                Path(temporary).unlink(missing_ok=True)
        return target


# Short alias for callers that use a project repository as their primary object.
Project = ProjectDocument
