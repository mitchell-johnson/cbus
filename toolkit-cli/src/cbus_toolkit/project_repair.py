"""Portable equivalents of C-Gate's lexical repair and two repair stylesheets.

This operates on bytes, without changing a file or C-Gate repository. The XML
stages support bounded XML 1.0/UTF-8 without DTDs. Output preserves XML semantics,
not vendor serialization bytes; a repaired document has not been load-tested.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import re
from xml.dom import Node, minidom
from xml.parsers import expat

DEFAULT_MAX_BYTES = 8 * 1024 * 1024
XMLNS = "http://www.w3.org/2000/xmlns/"


class ProjectRepairError(ValueError):
    """Repair failed or exceeded the explicitly supported input domain."""

    def __init__(self, message: str, *, stage: str):
        super().__init__(message)
        self.stage = stage


def _limit(value: int, name: str, maximum: int) -> None:
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError(f"{name} must be an integer from 1 to {maximum}")


def _input(data: bytes, max_bytes: int) -> None:
    _limit(max_bytes, "max_bytes", 64 * 1024 * 1024)
    if type(data) is not bytes:
        raise TypeError("XML input must be bytes")
    if len(data) > max_bytes:
        raise ProjectRepairError("XML exceeds max_bytes", stage="bounds")


def _lines(text: str, ending: str) -> str:
    # BufferedReader.readLine recognizes CR, LF and CRLF, but not VT/FF/NEL.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if text and not text.endswith("\n"):
        text += "\n"
    return text.replace("\n", ending)


def preprocess_project_xml(data: bytes, *, line_ending: str = "lf",
                           max_bytes: int = DEFAULT_MAX_BYTES) -> bytes:
    """Run the original angle-bracket state machine and Java UTF-8 replacement.

    The algorithm deliberately does not recognize quotes, comments or CDATA.
    It can change valid XML into invalid XML. No missing EOF bracket is added.
    """
    _input(data, max_bytes)
    if line_ending not in ("lf", "crlf"):
        raise ValueError("line_ending must be 'lf' or 'crlf'")
    # Java treats a malformed encoded surrogate (including its valid truncated
    # prefix) as one replacement; Python's default decoder replaces each byte.
    data = re.sub(b"\xed[\xa0-\xbf][\x80-\xbf]?", b"\xef\xbf\xbd", data)
    text = data.decode("utf-8", "replace")
    inside = False
    result = []
    for char in text:
        if char == "<":
            if inside:
                result.append(">")
            inside = True
            result.append(char)
        elif char == ">":
            if inside:
                result.append(char)
                inside = False
        else:
            result.append(char)
    output = _lines("".join(result), "\n" if line_ending == "lf" else "\r\n").encode("utf-8")
    if len(output) > max_bytes:
        raise ProjectRepairError("Preprocessed XML exceeds max_bytes", stage="manual")
    return output


def _parse(data: bytes, stage: str, max_nodes: int, max_depth: int) -> minidom.Document:
    # Expat also auto-detects UTF-16. The original repair pipeline reads UTF-8,
    # and direct XML-stage support is intentionally limited to that encoding.
    try:
        data.decode("utf-8", "strict")
    except UnicodeError as error:
        raise ProjectRepairError("XML stages require valid UTF-8", stage=stage) from error
    if b"\x00" in data:
        raise ProjectRepairError("NUL and UTF-16 XML are unsupported", stage=stage)
    parser = expat.ParserCreate()
    depth, nodes = 0, 1  # Include the document itself.

    def declaration(version, encoding, standalone):
        if version != "1.0" or encoding is not None and encoding.lower() not in ("utf-8", "utf8"):
            raise ProjectRepairError("XML stages require XML 1.0 with UTF-8 encoding", stage=stage)

    def doctype(*_):
        raise ProjectRepairError("DTD and entity declarations are unsupported", stage=stage)

    def count(amount=1):
        nonlocal nodes
        nodes += amount
        if nodes > max_nodes:
            raise ProjectRepairError("XML exceeds max_nodes", stage=stage)

    def start(name, attributes):
        nonlocal depth, nodes
        depth += 1
        # Include attribute nodes and their text before constructing the DOM.
        count(1 + 2 * len(attributes))
        if depth > max_depth:
            raise ProjectRepairError("XML exceeds max_depth", stage=stage)

    def end(*_):
        nonlocal depth
        depth -= 1

    parser.XmlDeclHandler = declaration
    parser.StartDoctypeDeclHandler = doctype
    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CommentHandler = lambda *_: count()
    parser.ProcessingInstructionHandler = lambda *_: count()
    # Conservative: adjacent parser text events may become one DOM text node.
    parser.CharacterDataHandler = lambda data: count() if data else None
    try:
        parser.Parse(data, True)
        document = minidom.parseString(data)
    except (expat.ExpatError, UnicodeError) as error:
        raise ProjectRepairError(f"XML is not well formed: {error}", stage=stage) from error
    pending = [document]
    nodes = 0
    while pending:
        node = pending.pop()
        nodes += 1
        if nodes > max_nodes:
            document.unlink()
            raise ProjectRepairError("XML exceeds max_nodes", stage=stage)
        pending.extend(node.childNodes)
    return document


def _named(node: Node, name: str) -> bool:
    return node.nodeType == Node.ELEMENT_NODE and not node.namespaceURI and node.nodeName == name


def _string(node: Node) -> str:
    if node.nodeType in (Node.TEXT_NODE, Node.CDATA_SECTION_NODE):
        return node.data
    return "".join(_string(child) for child in node.childNodes)


def _addresses(node: Node) -> list[str]:
    return [_string(child) for child in node.childNodes if _named(child, "Address")]


def _transform(document: minidom.Document, stage: str) -> minidom.Document:
    result = minidom.Document()
    # XSLT keys refer to the original stage input, before OID removal or any
    # child transform. The second stylesheet builds fresh keys on stage1 output.
    first = {}
    pending = [document]
    while pending:
        node = pending.pop()
        pending.extend(reversed(node.childNodes))
        if _named(node, "Group") and _named(node.parentNode, "Application"):
            addresses = _addresses(node)
            key = (id(node.parentNode), addresses[0] if addresses else "")
            first.setdefault(key, node)

    def text_element(name: str, value: str) -> minidom.Element:
        element = result.createElement(name)
        if value:
            element.appendChild(result.createTextNode(value))
        return element

    def copy(node: Node, parent: Node, *, wrapped: bool = False) -> None:
        if stage == "repair" and _named(node, "OID"):
            return
        if stage == "repair" and _named(node, "Project") and node.parentNode is document and not wrapped:
            wrapper = result.createElement("Installation")
            parent.appendChild(wrapper)
            for name, value in (("DBVersion", "2.2"), ("Version", "1.0"), ("Modified", "2010-01-01T13:01:46.657+10:30")):
                wrapper.appendChild(text_element(name, value))
            copy(node, wrapper, wrapped=True)
            detail = result.createElement("InstallationDetail")
            wrapper.appendChild(detail)
            for name, value in (("SystemLocation", "[unknown]"), ("HardwarePlatform", "[unknown]"), ("Hostname", ""), ("OSName", "Windows XP"), ("OSVersion", "5.1"), ("HardwareLocation", "[unknown]"), ("MaintenanceEmail", "[unknown]")):
                detail.appendChild(text_element(name, value))
            installer = result.createElement("Installer")
            installer.appendChild(text_element("Name", "[unknown]"))
            detail.appendChild(installer)
            return
        if node.nodeType == Node.ELEMENT_NODE:
            group = _named(node, "Group") and _named(node.parentNode, "Application")
            addresses = _addresses(node) if group else []
            special = group and (stage == "tidy" or "255" in addresses)
            if special:
                key = (id(node.parentNode), addresses[0] if addresses else "")
                if first[key] is not node:
                    return
            element = result.createElementNS(node.namespaceURI, node.nodeName)
            for attribute in node.attributes.values():
                if not special or attribute.namespaceURI == XMLNS:
                    # minidom may represent an explicit xmlns="" as None.
                    element.setAttributeNS(attribute.namespaceURI, attribute.name,
                                           attribute.value if attribute.value is not None else "")
            parent.appendChild(element)
            for child in node.childNodes:
                if not (special and stage == "repair" and _named(child, "TagName")):
                    copy(child, element)
            if special and stage == "repair":
                element.appendChild(text_element("TagName", "<Unused>"))
        elif node.nodeType in (Node.TEXT_NODE, Node.CDATA_SECTION_NODE):
            parent.appendChild(result.createTextNode(node.data))
        elif node.nodeType in (Node.COMMENT_NODE, Node.PROCESSING_INSTRUCTION_NODE):
            parent.appendChild(result.importNode(node, True))

    for child in document.childNodes:
        copy(child, result)
    return result


def _serialize(document: minidom.Document) -> str:
    # Python3.10 minidom does not escape attribute whitespace; later releases
    # do. Character references must survive the next XML parse on both versions.
    parts = ['<?xml version="1.0" encoding="utf-8"?>']

    def escaped(value: str, *, attribute: bool = False) -> str:
        value = value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\r", "&#13;")
        if attribute:
            value = value.replace('"', "&quot;").replace("\t", "&#9;").replace("\n", "&#10;")
        return value

    def write(node: Node) -> None:
        if node.nodeType == Node.ELEMENT_NODE:
            parts.append("<" + node.nodeName)
            for attr in node.attributes.values():
                parts.append(" " + attr.name + '="' + escaped(attr.value, attribute=True) + '"')
            if not node.childNodes:
                parts.append("/>")
                return
            parts.append(">")
            for child in node.childNodes:
                write(child)
            parts.append("</" + node.nodeName + ">")
        elif node.nodeType in (Node.TEXT_NODE, Node.CDATA_SECTION_NODE):
            parts.append(escaped(node.data))
        elif node.nodeType in (Node.COMMENT_NODE, Node.PROCESSING_INSTRUCTION_NODE):
            parts.append(node.toxml())

    for child in document.childNodes:
        write(child)
    return "".join(parts)


def transform_project_repair_xml(data: bytes, *, stage: str, line_ending: str = "lf",
                                 max_bytes: int = DEFAULT_MAX_BYTES,
                                 max_nodes: int = 100_000, max_depth: int = 128) -> bytes:
    """Apply either repair.xslt or tidyduplicategroups.xslt semantics in Python."""
    _input(data, max_bytes)
    _limit(max_nodes, "max_nodes", 1_000_000)
    _limit(max_depth, "max_depth", 256)
    if stage not in ("repair", "tidy"):
        raise ValueError("stage must be 'repair' or 'tidy'")
    if line_ending not in ("lf", "crlf"):
        raise ValueError("line_ending must be 'lf' or 'crlf'")
    document = _parse(data, stage, max_nodes, max_depth)
    result = None
    try:
        result = _transform(document, stage)
        serialized = _serialize(result)
        output = _lines(serialized, "\n" if line_ending == "lf" else "\r\n").encode("utf-8")
        if len(output) > max_bytes:
            raise ProjectRepairError("Transformed XML exceeds max_bytes", stage=stage)
        return output
    finally:
        document.unlink()
        if result is not None:
            result.unlink()


@dataclass(frozen=True)
class ProjectRepairResult:
    source_sha256: str
    preprocessed_xml: bytes
    repaired_xml: bytes
    line_ending: str
    db_version: str | None

    def as_dict(self) -> dict:
        return {
            "source_sha256": self.source_sha256,
            "preprocessed_sha256": sha256(self.preprocessed_xml).hexdigest(),
            "output_sha256": sha256(self.repaired_xml).hexdigest(),
            "output_bytes": len(self.repaired_xml), "line_ending": self.line_ending,
            "db_version": self.db_version, "repair_complete": True,
            "output_well_formed": True, "native_load_verified": False,
            "native_loadable": None, "physical_io_attempted": False,
            "file_modified": False, "vendor_serialization_bytes": False,
        }


def repair_project_xml(data: bytes, *, line_ending: str = "lf",
                       max_bytes: int = DEFAULT_MAX_BYTES,
                       max_nodes: int = 100_000, max_depth: int = 128) -> ProjectRepairResult:
    """Preprocess, repair and deduplicate, returning detached bytes and evidence."""
    _input(data, max_bytes)
    _limit(max_nodes, "max_nodes", 1_000_000)
    _limit(max_depth, "max_depth", 256)
    options = dict(line_ending=line_ending, max_bytes=max_bytes,
                   max_nodes=max_nodes, max_depth=max_depth)
    preprocessed = preprocess_project_xml(data, line_ending=line_ending, max_bytes=max_bytes)
    repaired = transform_project_repair_xml(preprocessed, stage="repair", **options)
    output = transform_project_repair_xml(repaired, stage="tidy", **options)
    document = _parse(output, "verify", max_nodes, max_depth)
    try:
        versions = [_string(child) for child in document.documentElement.childNodes if _named(child, "DBVersion")]
        version = versions[0] if _named(document.documentElement, "Installation") and len(versions) == 1 else None
    finally:
        document.unlink()
    return ProjectRepairResult(sha256(data).hexdigest(), preprocessed, output, line_ending, version)
