"""Bounded 2.2-to-2.3 conversion of Python-repaired legacy project XML.

The original C-Gate v22tov23.xslt is an identity transform except for the
unnamespaced DBVersion element. The byte operation below is intentionally
limited to the generated repair envelope observed in native acceptance.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import re
from xml.dom import Node

from .project_repair import DEFAULT_MAX_BYTES, ProjectRepairError, _named, _parse, _string


_VERSION_22 = b"<DBVersion>2.2</DBVersion>"
_VERSION_23 = b"<DBVersion>2.3</DBVersion>"
_START = b'<?xml version="1.0" encoding="utf-8"?><Installation>'
_END = b"</Installation>\n"
_PROJECT_NAME = re.compile(r"[A-Z][A-Z0-9_]{0,7}\Z")


class LegacyProjectTransformError(ValueError):
    """Input is outside the verified, portable legacy conversion domain."""


@dataclass(frozen=True)
class LegacyProjectTransformResult:
    transformed_xml: bytes
    source_sha256: str
    project_address: str | None

    def as_dict(self) -> dict:
        return {
            "source_sha256": self.source_sha256,
            "output_sha256": sha256(self.transformed_xml).hexdigest(),
            "output_bytes": len(self.transformed_xml),
            "source_db_version": "2.2", "output_db_version": "2.3",
            "project_address": self.project_address,
            "native_load_verified": False, "physical_io_attempted": False,
            "source_modified": False,
        }


def transform_repaired_legacy_project(
    data: bytes, *, max_bytes: int = DEFAULT_MAX_BYTES,
) -> LegacyProjectTransformResult:
    """Convert one canonical repaired Installation while preserving other bytes.

    The four native cases underlying this subset use a single literal version
    node and a final LF. Other encodings, DTDs, alternate version spelling and
    arbitrary project XML require separate evidence and are rejected here.
    """
    if type(max_bytes) is not int or not 1 <= max_bytes <= 64 * 1024 * 1024:
        raise ValueError("max_bytes must be an integer from 1 to 67108864")
    if type(data) is not bytes:
        raise TypeError("XML input must be bytes")
    if len(data) > max_bytes:
        raise LegacyProjectTransformError("Source exceeds max_bytes")
    if not data.startswith(_START) or not data.endswith(_END):
        raise LegacyProjectTransformError("Expected the UTF-8 Python-repaired Installation envelope with final LF")
    if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        raise LegacyProjectTransformError("DTD-bearing XML is outside the legacy conversion subset")
    if data.count(_VERSION_22) != 1:
        raise LegacyProjectTransformError("Expected one literal DBVersion 2.2 element")
    try:
        data.decode("utf-8", "strict")
        document = _parse(data, "legacy-transform", max_bytes, 100_000, 128)
    except (UnicodeError, ProjectRepairError) as error:
        raise LegacyProjectTransformError("Source is not well-formed, bounded UTF-8 XML") from error
    try:
        root = document.documentElement
        if not _named(root, "Installation"):
            raise LegacyProjectTransformError("Expected an unnamespaced Installation")
        versions = [node for node in document.getElementsByTagName("DBVersion") if _named(node, "DBVersion")]
        if (len(versions) != 1 or versions[0].parentNode is not root or
                len(versions[0].childNodes) != 1 or
                versions[0].firstChild.nodeType != Node.TEXT_NODE or
                versions[0].firstChild.data != "2.2"):
            raise LegacyProjectTransformError("Expected one direct DBVersion 2.2 element")
        projects = [node for node in root.childNodes if _named(node, "Project")]
        if len(projects) != 1:
            raise LegacyProjectTransformError("Expected exactly one direct Project element")
        addresses = [node for node in projects[0].childNodes if _named(node, "Address")]
        if len(addresses) > 1:
            raise LegacyProjectTransformError("Project has multiple Address elements")
        address = _string(addresses[0]) if addresses else None
        if address is not None and _PROJECT_NAME.fullmatch(address) is None:
            raise LegacyProjectTransformError("Project Address is outside the verified name domain")
    finally:
        document.unlink()
    output = data.replace(_VERSION_22, _VERSION_23, 1)[:-1]
    try:
        changed = _parse(output, "legacy-transform-verify", max_bytes, 100_000, 128)
    except ProjectRepairError as error:
        raise LegacyProjectTransformError("Converted XML is not well-formed") from error
    try:
        version = [node for node in changed.documentElement.childNodes if _named(node, "DBVersion")]
        if len(version) != 1 or _string(version[0]) != "2.3":
            raise LegacyProjectTransformError("Conversion did not update the root database version")
    finally:
        changed.unlink()
    return LegacyProjectTransformResult(output, sha256(data).hexdigest(), address)
