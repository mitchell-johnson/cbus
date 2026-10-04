"""Conversion XML comparison with inherited whitespace semantics.

Formatting-only indentation of an unprotected element container is ignored.
Opaque mixed content, leaf values and xml:space="preserve" character data are
compared without trimming. This does not compare XML serialization choices.
"""
from __future__ import annotations

from xml.dom import Node, minidom
from xml.parsers import expat
from xml.sax.saxutils import quoteattr

from .barcode_database import _unit_document

XML_NAMESPACE = "http://www.w3.org/XML/1998/namespace"
_XML_WHITESPACE = frozenset(" \t\r\n")


def comparison_policy() -> dict[str, bool]:
    return {
        "formatting_only_container_indentation_compared": False,
        "xml_space_preserve_override_enforced": True,
        "mixed_content_text_whitespace_compared": True,
        "whitespace_only_leaf_values_compared": True,
    }


def _local_space(node: Node, inherited: str) -> str:
    if node.nodeType == Node.ELEMENT_NODE and node.hasAttributeNS(XML_NAMESPACE, "space"):
        value = node.getAttributeNS(XML_NAMESPACE, "space")
        if value not in {"default", "preserve"}:
            raise ValueError("Conversion XML requires xml:space default or preserve")
        return value
    return inherited


def xml_space(node: Node | None) -> str:
    """Return the actual inherited scope, including this node's own override."""
    chain = []
    while node is not None:
        chain.append(node)
        node = node.parentNode
    scope = "default"
    for ancestor in reversed(chain):
        scope = _local_space(ancestor, scope)
    return scope


def _only_xml_whitespace(value: str) -> bool:
    return all(character in _XML_WHITESPACE for character in value)


def _shape(node: Node, inherited: str):
    if node.nodeType == Node.ELEMENT_NODE:
        scope = _local_space(node, inherited)
        has_elements = any(child.nodeType == Node.ELEMENT_NODE for child in node.childNodes)
        mixed = any(
            child.nodeType == Node.CDATA_SECTION_NODE
            or child.nodeType == Node.TEXT_NODE and not _only_xml_whitespace(child.data)
            for child in node.childNodes
        )
        ignore_indentation = has_elements and not mixed and scope != "preserve"
        children = tuple(
            _shape(child, scope)
            for child in node.childNodes
            if not (
                ignore_indentation
                and child.nodeType == Node.TEXT_NODE
                and _only_xml_whitespace(child.data)
            )
        )
        return (node.namespaceURI, node.tagName, tuple(sorted(node.attributes.items())), children)
    if node.nodeType in {Node.TEXT_NODE, Node.CDATA_SECTION_NODE}:
        return (node.nodeType, node.data)
    return (node.nodeType, getattr(node, "target", None), getattr(node, "data", None))


def shape(node: Node, *, inherited_xml_space: str | None = None):
    """Compare a DOM subtree with its real ancestors or an explicit clone scope.

    Detached clones must pass the scope of their original parent. Text after a
    child belongs to this parent's scope, so a child's override cannot erase it.
    """
    inherited = xml_space(node.parentNode) if inherited_xml_space is None else inherited_xml_space
    if inherited not in {"default", "preserve"}:
        raise ValueError("Invalid inherited conversion XML whitespace scope")
    return _shape(node, inherited)


def contextual_unit(raw: bytes, context_node: Node | None = None):
    """Parse detached Unit XML with its real parent's namespace bindings.

    Declarations belong to a temporary wrapper, not the Unit's attributes or
    stored XML. Local declarations in the Unit keep their normal precedence.
    DTDs remain forbidden, and the detached payload has the existing size bound.
    """
    if context_node is None:
        return _unit_document(raw)
    if len(raw) > 4 * 1024 * 1024:
        raise ValueError("Unit XML exceeds the database document limit")
    chain = []
    parent = context_node.parentNode
    while parent is not None:
        chain.append(parent)
        parent = parent.parentNode
    declarations = {}
    for ancestor in reversed(chain):
        if ancestor.nodeType == Node.ELEMENT_NODE:
            for name, value in ancestor.attributes.items():
                if name == "xmlns" or name.startswith("xmlns:"):
                    declarations[name] = value
    opening = "<ConversionContext" + "".join(" " + name + "=" + quoteattr(value)
                                            for name, value in sorted(declarations.items())) + ">"
    parser = expat.ParserCreate()
    def reject_doctype(*_args):
        raise ValueError("DTD and entity declarations are not supported")
    parser.StartDoctypeDeclHandler = reject_doctype
    try:
        wrapped = (opening + raw.decode("utf-8") + "</ConversionContext>").encode()
        parser.Parse(wrapped, True)
        wrapper = minidom.parseString(wrapped).documentElement
        elements = [child for child in wrapper.childNodes if child.nodeType == Node.ELEMENT_NODE]
        if (len(elements) != 1 or elements[0].tagName != "Unit" or elements[0].namespaceURI
                or any(child.nodeType == Node.TEXT_NODE and not _only_xml_whitespace(child.data)
                       for child in wrapper.childNodes)):
            raise ValueError("Expected an unnamespaced Unit readback")
        return elements[0]
    except (expat.ExpatError, UnicodeError) as error:
        raise ValueError("Unit readback is not a valid XML document") from error


def unit_shape(raw: bytes, *, context_node: Node | None = None, inherited_xml_space: str | None = None):
    scope = xml_space(context_node.parentNode) if context_node is not None else "default"
    if inherited_xml_space is not None:
        scope = inherited_xml_space
    return shape(contextual_unit(raw, context_node), inherited_xml_space=scope)
