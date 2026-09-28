"""Bounded 2/2.1/2.2-to-2.3 conversion of Python-repaired legacy XML.

The original C-Gate's earlier stylesheets can change Unit and PP data. The
source-bound profiles admit KEYGL5 5.5.00 and KEYB2/KEYB4 1.6 units and
apply their matching parameter removals; other units use native TRANSFORM.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import re
from xml.dom import Node

from .project_repair import DEFAULT_MAX_BYTES, ProjectRepairError, _named, _parse, _string


_VERSION_23 = b"<DBVersion>2.3</DBVersion>"
_SOURCE_VERSIONS = {
    "2": b"<DBVersion>2</DBVersion>",
    "2.1": b"<DBVersion>2.1</DBVersion>",
    "2.2": b"<DBVersion>2.2</DBVersion>",
}
_START = b'<?xml version="1.0" encoding="utf-8"?><Installation>'
_END = b"</Installation>\n"
_PROJECT_NAME = re.compile(r"[A-Z][A-Z0-9_]{0,7}\Z")
_PP_TOKEN = re.compile(rb'<PP Name="([A-Za-z0-9_ ]+)" Value="[^"<>]*"/>')
_V2_PP_REMOVED = frozenset({
    "KeyMaskAllowed", "KeyMaskSave", "KeyCurrentMask", "KeyMaskNetworkVariable",
    "KeyMaskNetworkVariableLevels", "KeyOffsetAllowed", "KeyOffsetSave",
    "KeyCurrentOffset", "KeyOffsets", "KeyOffsetNetworkVariable",
    "KeyOffsetNetworkVariableLevels", "FeatureSet", "Remote1Identity",
    "Remote2Identity", "Remote1KeyMap", "Remote2KeyMap",
    *(f"KeyEnableMask{n}" for n in range(1, 5)),
    *(f"Key{n}{suffix}" for n in range(9, 17)
      for suffix in ("CommandLookup", "Parameter1", "Parameter2", "BlockMap")),
})
_V21_PP_REMOVED = frozenset(f"Remote{n}{suffix}" for n in range(3, 9)
                             for suffix in ("Identity", "KeyMap"))
_V21_NEO_WITHOUT_APPLICATION_REMOVED = frozenset({
    "KeyDisableGroupInvert", "CorridorLinkEnable", "NightlightColour", "DisableIRNEC",
})
_V2_PP_EXPANDED_OR_RENAMED = frozenset(("KeyExtraLongPressDuration", "EnableNightlightPCx"))
_UNIT_PROFILES = frozenset({
    ("KEYGL5", "5.5.00"), ("KEYB2", "1.6"), ("KEYB4", "1.6"),
})


class LegacyProjectTransformError(ValueError):
    """Input is outside the verified, portable legacy conversion domain."""


@dataclass(frozen=True)
class LegacyProjectTransformResult:
    transformed_xml: bytes
    source_sha256: str
    project_address: str | None
    source_db_version: str
    removed_programming_parameters: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {
            "source_sha256": self.source_sha256,
            "output_sha256": sha256(self.transformed_xml).hexdigest(),
            "output_bytes": len(self.transformed_xml),
            "source_db_version": self.source_db_version, "output_db_version": "2.3",
            "project_address": self.project_address,
            "native_load_verified": False, "physical_io_attempted": False,
            "source_modified": False,
            "removed_programming_parameters": list(self.removed_programming_parameters),
        }


def _earlier_unit_removals(document, data: bytes, source_version: str) -> tuple[tuple[str, ...], bytes]:
    """Match pinned no-firmware-change profiles of the original stylesheets.

    Exact canonical PP tokens let us remove only nodes selected by those XSLT
    templates while retaining unrelated source bytes. The KEYB2/KEYB4 1.6
    absent-Application rule is from v21tov22.xslt. Other special Unit templates
    and PP expansion/rename cases are deliberately excluded.
    """
    elements = document.getElementsByTagName("*")
    units = [node for node in elements if node.nodeName.rsplit(":", 1)[-1] == "Unit"]
    pps = [node for node in elements if node.nodeName.rsplit(":", 1)[-1] == "PP"]
    if not units and not pps:
        return (), data
    if any(not _named(unit, "Unit") or not _named(unit.parentNode, "Network") for unit in units):
        raise LegacyProjectTransformError("Earlier-version Unit migration requires native XSLT for this shape")
    if any(not _named(pp, "PP") or pp.parentNode not in units for pp in pps):
        raise LegacyProjectTransformError("Earlier-version PP migration requires direct, unnamespaced Unit parameters")
    # Original XSLT serialization collapses explicit empty pairs. The portable
    # byte edit is admitted only when this serializer effect cannot diverge.
    if re.search(rb'<([A-Za-z][A-Za-z0-9_.-]*)(?:\s[^<>]*)?></\1>', data):
        raise LegacyProjectTransformError("Earlier-version Unit XML has noncanonical empty elements")
    neo_without_application: set[Node] = set()
    for unit in units:
        unit_type = [node for node in unit.childNodes if _named(node, "UnitType")]
        firmware = [node for node in unit.childNodes if _named(node, "FirmwareVersion")]
        if (len(unit_type) != 1 or len(firmware) != 1 or
                (_string(unit_type[0]), _string(firmware[0])) not in _UNIT_PROFILES):
            raise LegacyProjectTransformError(
                "Earlier-version Unit migration is verified only for KEYGL5 5.5.00 and KEYB2/KEYB4 1.6")
        if _string(unit_type[0]) in ("KEYB2", "KEYB4") and not any(
                _named(child, "PP") and child.getAttribute("Name") == "Application"
                for child in unit.childNodes):
            neo_without_application.add(unit)
    tokens = list(_PP_TOKEN.finditer(data))
    if (len(tokens) != len(pps) or len(re.findall(rb'<PP(?:\s|>)', data)) != len(pps) or
            any(set(pp.attributes.keys()) != {"Name", "Value"} for pp in pps)):
        raise LegacyProjectTransformError("Earlier-version PP nodes require canonical Name/Value tokens")
    names = tuple(pp.getAttribute("Name") for pp in pps)
    if names != tuple(token.group(1).decode("ascii") for token in tokens):
        raise LegacyProjectTransformError("Earlier-version PP token order differs from parsed XML")
    if source_version == "2" and _V2_PP_EXPANDED_OR_RENAMED.intersection(names):
        raise LegacyProjectTransformError("Earlier-version PP expansion or rename requires native XSLT")
    removed = _V21_PP_REMOVED | (_V2_PP_REMOVED if source_version == "2" else frozenset())
    fragments: list[bytes] = []
    found: list[str] = []
    offset = 0
    for name, pp, token in zip(names, pps, tokens):
        if (name in removed or
                (pp.parentNode in neo_without_application and
                 name in _V21_NEO_WITHOUT_APPLICATION_REMOVED)):
            fragments.append(data[offset:token.start()])
            found.append(name)
            offset = token.end()
    fragments.append(data[offset:])
    return tuple(found), b"".join(fragments)


def transform_repaired_legacy_project(
    data: bytes, *, max_bytes: int = DEFAULT_MAX_BYTES,
) -> LegacyProjectTransformResult:
    """Convert one canonical repaired Installation while preserving other bytes.

    The native cases underlying this subset use a single literal version node
    and a final LF. Earlier versions admit unitless projects and the verified
    KEYGL5 5.5.00 and KEYB2/KEYB4 1.6 profiles; C-Gate's earlier XSLT stages
    can change other units and parameters. Other encodings, DTDs, alternate
    version spelling and XML require separate evidence and are rejected here.
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
    candidates = [version for version, literal in _SOURCE_VERSIONS.items()
                  if data.count(literal) == 1]
    if len(candidates) != 1:
        raise LegacyProjectTransformError("Expected one literal DBVersion 2, 2.1 or 2.2 element")
    source_db_version = candidates[0]
    version_literal = _SOURCE_VERSIONS[source_db_version]
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
                versions[0].firstChild.data != source_db_version):
            raise LegacyProjectTransformError("Expected one direct DBVersion element with the selected source version")
        removed, migrated = (_earlier_unit_removals(document, data, source_db_version)
                             if source_db_version in ("2", "2.1") else ((), data))
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
    output = migrated.replace(version_literal, _VERSION_23, 1)[:-1]
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
    return LegacyProjectTransformResult(output, sha256(data).hexdigest(), address,
                                        source_db_version, removed)
