"""Bounded 2/2.1/2.2-to-2.3 conversion of Python-repaired legacy XML.

The original C-Gate's earlier stylesheets can change Unit and PP data. Every
template of the three native migration stylesheets is reproduced as a byte
edit of canonical input; ``NATIVE_TEMPLATE_COVERAGE`` names each template by
its census ID. Input the edit cannot reproduce exactly is rejected.
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
_UNIT_START = re.compile(rb'<(?:cis:)?Unit(?=[\s/>])')
_UNIT_END = re.compile(rb'</(?:cis:)?Unit>')
_FIRMWARE_TOKEN = re.compile(rb'<FirmwareVersion>([0-9A-Za-z._-]+)</FirmwareVersion>')
_UNIT_TYPE_TEXT = re.compile(r"[A-Za-z0-9_]{1,16}\Z")
_FIRMWARE_TEXT = re.compile(r"[0-9A-Za-z._-]{1,32}\Z")
_CIS = "http://www.clipsal.com/cis/schema/2001/cbus.xsd"
_CIS_DECLARATION = b'xmlns:cis="' + _CIS.encode() + b'"'

# v2tov21.xslt: global PP removals, one expansion and one rename.
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
_V2_EXPANDED = "KeyExtraLongPressDuration"
_V2_EXPANSION = (
    ("KeyMaskAllowed", "0x0"), ("KeyMaskSave", "0x0"), ("KeyCurrentMask", "0xffff"),
    *((f"KeyEnableMask{n}", "0xffff") for n in range(1, 5)),
    ("KeyMaskNetworkVariable", "0xff"), ("KeyMaskNetworkVariableLevels", "0xff 0xff 0xff 0xff"),
    ("KeyOffsetAllowed", "0x0"), ("KeyOffsetSave", "0x1"), ("KeyCurrentOffset", "0x0"),
    ("KeyOffsets", "0x0 0x0 0x0 0x0"), ("KeyOffsetNetworkVariable", "0xff"),
    ("KeyOffsetNetworkVariableLevels", "0xff 0xff 0xff 0xff"), ("FeatureSet", "0x0"),
    *((f"Key{n}{suffix}", "0x0 0x0 0x0 0x0 0x0 0x0")
      for suffix in ("CommandLookup", "Parameter1", "Parameter2") for n in range(9, 17)),
    *((f"Key{n}BlockMap", " ".join("1" if bit == n - 1 else "0" for bit in range(16)))
      for n in range(9, 17)),
    ("Remote1Identity", "0xff 0xff 0xff 0xff"), ("Remote2Identity", "0xff 0xff 0xff 0xff"),
    ("Remote1KeyMap", " ".join(["0xff"] * 16)), ("Remote2KeyMap", " ".join(["0xff"] * 16)),
)
_V2_RENAMED = {"EnableNightlightPCx": "EnableNightlightOnPCx"}
# v2tov21.xslt cis:Unit additions; unnamespaced Unit elements never match.
_NEO_TYPES = frozenset({"KEYA1", "KEYAV2", "KEYA3", "KEYAV4", "KEYA6", "KEYA8", "KEYB2",
                        "KEYB4", "KEYB6", "KEYM2", "KEYM4", "KEYM6", "KEYM8"})
_NEO_ADDED_PREFIXES = ("1.6", "1.7", "1.8", "1.9", "1.10", "1.11", "1.12", "2.")
_NEO_ADDED = (("KeyDisableGroupInvert", "1"), ("CorridorLinkEnable", "0"),
              ("NightlightColour", "0"), ("DisableIRNEC", "1"))
_DLT_TYPES = frozenset({"KEYBL5", "KEYML5"})
_DLT_ADDED = (("CorridorLinkEnable", "0"),)
# v21tov22.xslt: global removals, Application-gated removals, wireless
# additions and firmware renames, all on unnamespaced Unit elements.
_V21_PP_REMOVED = frozenset(f"Remote{n}{suffix}" for n in range(3, 9)
                             for suffix in ("Identity", "KeyMap"))
_DLT_WITHOUT_APPLICATION_REMOVED = frozenset({"CorridorLinkEnable"})
_NEO_WITHOUT_APPLICATION_PREFIX = "1.6"
_NEO_WITHOUT_APPLICATION_REMOVED = frozenset({
    "KeyDisableGroupInvert", "CorridorLinkEnable", "NightlightColour", "DisableIRNEC",
})
_WIRELESS_TYPES = frozenset(
    ["WPA2D1", "WPA2R1", "WPAP2D1", "WPAP2R1"] +
    [f"WR{kind}{keys}{variant}"
     for kind, key_counts in (("B", (2, 4, 6)), ("M", (2, 4, 8)), ("P", (2, 4, 6)))
     for keys in key_counts
     for variant in (("D1", "R1") if keys == 2 else ("D1", "D2", "R1", "R2"))])
_WIRELESS_PREFIX = "2.0.0"
_WIRELESS_ADDED = (
    *((f"Remote{n}Identity", "0xff 0xff 0xff 0xff") for n in range(3, 9)),
    *((f"Remote{n}KeyMap", " ".join(["0xff"] * 8)) for n in range(3, 9)),
)
_FIRMWARE_RENAMES = ((frozenset({"PC_CTA"}), "4.00", "4.0.0"),
                     (frozenset({"PCINT4", "PCLOCAL4", "PC_CBTI", "PC_PGA", "PC_IRT2",
                                 "PC_WHAM"}), "4.0.00", "4.0.0"))

_FULL = "full"
_BOUNDED = "bounded"
_REMOVAL_SCOPE = "Removes the canonical direct Unit PP token; other bytes are preserved"
# Census ID -> (extent, scope). research/legacy_transform_template_census.py
# derives portable_coverage from this table; tests keep both in step.
NATIVE_TEMPLATE_COVERAGE: dict[str, tuple[str, str]] = {
    "v2tov21#01-2de8c533": (_BOUNDED, "Identity copy is reproduced by preserving canonical source bytes only"),
    "v2tov21#02-b9f4e06e": (_FULL, "Version literal replaced; the chain ends at 2.3"),
    **{ident: (_FULL, _REMOVAL_SCOPE) for ident in (
        "v2tov21#03-308a4041", "v2tov21#04-d177455e", "v2tov21#05-b8386616",
        "v2tov21#06-bcc80e2b", "v2tov21#07-7c0f72b0", "v2tov21#08-ce84b55f",
        "v2tov21#09-a05e0904", "v2tov21#10-f7f93403", "v2tov21#11-f87648e1",
        "v2tov21#12-29ccede6", "v2tov21#13-e2d5bc5e", "v2tov21#14-d84e824e",
        "v2tov21#15-6b83ecd8", "v2tov21#16-f25b948e", "v2tov21#17-48add032",
        "v2tov21#18-9c86af63", "v2tov21#19-dbb1b420", "v2tov21#20-8b1a3f5e",
        "v2tov21#21-749f4a23", "v2tov21#22-fcb9eb5e", "v2tov21#23-c2e5abb7",
        "v2tov21#24-16049174", "v2tov21#25-9d7b152d", "v2tov21#26-d0e1c375",
        "v2tov21#27-5cfbca7e", "v2tov21#28-d06a75f3", "v2tov21#29-dd855157",
        "v2tov21#30-8d7ccfd6", "v2tov21#31-fc2551fa", "v2tov21#32-1aa5f048",
        "v2tov21#33-e5effba4", "v2tov21#34-065cc102", "v2tov21#35-4d571d7c",
        "v2tov21#36-fb86a711", "v2tov21#37-337bff46", "v2tov21#38-b15ae3ea",
        "v2tov21#39-d6e41109", "v2tov21#40-211aa539", "v2tov21#41-3bc18738",
        "v2tov21#42-f9680f81", "v2tov21#43-997e4f6d", "v2tov21#44-2ce533e6",
        "v2tov21#45-e235a482", "v2tov21#46-307b7559", "v2tov21#47-759fa708",
        "v2tov21#48-f8acea1c", "v2tov21#49-5c9b6ac3", "v2tov21#50-d52368a2",
        "v2tov21#51-1c9195af", "v2tov21#52-fdccdff0", "v2tov21#53-375cdc42",
        "v2tov21#54-32ed8ed4")},
    "v2tov21#55-9e87eeb9": (_FULL, "Keeps the source token and inserts the 52 default PP tokens after it"),
    "v2tov21#56-fd9c07b5": (_FULL, "Renames the canonical PP token, preserving its Value bytes"),
    "v2tov21#57-1338c52b": (_BOUNDED, "Appends Neo or DLT PP tokens inside cis:Unit; each cis:Unit must carry its own exact cis declaration"),
    "v21tov22#01-2de8c533": (_BOUNDED, "Identity copy is reproduced by preserving canonical source bytes only"),
    "v21tov22#02-b9f4e06e": (_FULL, "Version literal replaced; the chain ends at 2.3"),
    "v21tov22#03-98a206ab": (_FULL, "KEYBL5/KEYML5 without Application: CorridorLinkEnable removed"),
    "v21tov22#04-36fd2be7": (_FULL, "13 Neo types, firmware prefix 1.6, without Application: four PP removed"),
    **{ident: (_FULL, _REMOVAL_SCOPE) for ident in (
        "v21tov22#05-5eff873b", "v21tov22#06-4bfcadd9", "v21tov22#07-24e20b0e",
        "v21tov22#08-df6068fd", "v21tov22#09-f651a23c", "v21tov22#10-e0dcbac9",
        "v21tov22#11-2dec8283", "v21tov22#12-fbe19a56", "v21tov22#13-4cbd0f91",
        "v21tov22#14-e753f3fc", "v21tov22#15-86bde686", "v21tov22#16-91d77a09")},
    "v21tov22#17-efb660bf": (_FULL, "Unit copy; 34 wireless types at 2.0.0 with Application get 12 PP tokens"),
    "v21tov22#18-8e846bdd": (_BOUNDED, "PC_CTA 4.00* moved to a final 4.0.0 FirmwareVersion; attribute-bearing Units rejected"),
    "v21tov22#19-c309fdfb": (_BOUNDED, "PCI family 4.0.00* moved to a final 4.0.0 FirmwareVersion; attribute-bearing Units rejected"),
    "v22tov23#01-2de8c533": (_BOUNDED, "Identity copy is reproduced by preserving canonical source bytes only"),
    "v22tov23#02-b9f4e06e": (_FULL, "Version literal replaced"),
}


class LegacyProjectTransformError(ValueError):
    """Input is outside the verified, portable legacy conversion domain."""


@dataclass(frozen=True)
class LegacyProjectTransformResult:
    transformed_xml: bytes
    source_sha256: str
    project_address: str | None
    source_db_version: str
    removed_programming_parameters: tuple[str, ...] = ()
    added_programming_parameters: tuple[str, ...] = ()
    renamed_programming_parameters: tuple[tuple[str, str], ...] = ()
    firmware_version_changes: tuple[tuple[str, str, str], ...] = ()

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
            "added_programming_parameters": list(self.added_programming_parameters),
            "renamed_programming_parameters": [
                {"from": old, "to": new} for old, new in self.renamed_programming_parameters],
            "firmware_version_changes": [
                {"unit_type": unit_type, "from": old, "to": new}
                for unit_type, old, new in self.firmware_version_changes],
        }


@dataclass(frozen=True)
class _Migration:
    removed: tuple[str, ...]
    added: tuple[str, ...]
    renamed: tuple[tuple[str, str], ...]
    firmware: tuple[tuple[str, str, str], ...]
    data: bytes


def _pp_tokens(pairs) -> bytes:
    return b"".join(f'<PP Name="{name}" Value="{value}"/>'.encode() for name, value in pairs)


def _earlier_unit_migration(document, data: bytes, source_version: str) -> _Migration:
    """Apply the Unit/PP templates of v2tov21 (source 2) and v21tov22.

    Stage one sees the source; stage two sees stage one's output. Their
    edits touch disjoint PP names and Unit namespaces, so all edits are
    computed on source offsets. Every edit is either a whole canonical PP
    token, a FirmwareVersion token, or an insertion before a Unit end tag.
    """
    elements = document.getElementsByTagName("*")
    units = [node for node in elements if node.localName == "Unit"]
    pps = [node for node in elements if node.localName == "PP"]
    if not units and not pps:
        return _Migration((), (), (), (), data)
    cis_units = {unit for unit in units if unit.namespaceURI == _CIS and unit.prefix == "cis"}
    if any(not (_named(unit, "Unit") or unit in cis_units) or not _named(unit.parentNode, "Network")
           for unit in units):
        raise LegacyProjectTransformError("Earlier-version Unit migration requires native XSLT for this shape")
    if any(not _named(pp, "PP") or pp.parentNode not in units for pp in pps):
        raise LegacyProjectTransformError("Earlier-version PP migration requires direct, unnamespaced Unit parameters")
    # Original XSLT serialization collapses explicit empty pairs. The portable
    # byte edit is admitted only when this serializer effect cannot diverge.
    if re.search(rb'<([A-Za-z][A-Za-z0-9_.:-]*)(?:\s[^<>]*)?></\1>', data):
        raise LegacyProjectTransformError("Earlier-version Unit XML has noncanonical empty elements")
    starts = list(_UNIT_START.finditer(data))
    ends = list(_UNIT_END.finditer(data))
    if (len(starts) != len(units) or len(ends) != len(units) or
            any(start.start() >= end.start() for start, end in zip(starts, ends)) or
            any(end.start() >= start.start() for end, start in zip(ends, starts[1:]))):
        raise LegacyProjectTransformError("Unit tokens differ from the parsed Unit elements")
    # Native serialization keeps a declaration on each copied cis:Unit; one
    # on an ancestor as well would be redundant and is not reproduced here.
    if cis_units and (data.count(b"xmlns") != len(cis_units) or any(
            data[start.start():data.index(b">", start.start()) + 1] != b"<cis:Unit " + _CIS_DECLARATION + b">"
            for unit, start in zip(units, starts) if unit in cis_units)):
        raise LegacyProjectTransformError("Each cis:Unit must carry its own exact cis declaration and no other namespaces")
    profiles = {}
    for unit, start, end in zip(units, starts, ends):
        unit_type = [node for node in unit.childNodes if _named(node, "UnitType")]
        firmware = [node for node in unit.childNodes if _named(node, "FirmwareVersion")]
        if len(unit_type) != 1 or len(firmware) != 1:
            raise LegacyProjectTransformError("Earlier-version Unit migration requires one UnitType and FirmwareVersion")
        type_text, firmware_text = _string(unit_type[0]), _string(firmware[0])
        if _UNIT_TYPE_TEXT.fullmatch(type_text) is None or _FIRMWARE_TEXT.fullmatch(firmware_text) is None:
            raise LegacyProjectTransformError("Unit type or firmware is outside the canonical identifier domain")
        has_application = any(_named(child, "PP") and child.getAttribute("Name") == "Application"
                              for child in unit.childNodes)
        profiles[unit] = (type_text, firmware_text, has_application, start, end)
    tokens = list(_PP_TOKEN.finditer(data))
    if (len(tokens) != len(pps) or len(re.findall(rb'<PP(?:\s|>)', data)) != len(pps) or
            any(set(pp.attributes.keys()) != {"Name", "Value"} for pp in pps)):
        raise LegacyProjectTransformError("Earlier-version PP nodes require canonical Name/Value tokens")
    names = tuple(pp.getAttribute("Name") for pp in pps)
    if names != tuple(token.group(1).decode("ascii") for token in tokens):
        raise LegacyProjectTransformError("Earlier-version PP token order differs from parsed XML")

    edits: list[tuple[int, int, bytes]] = []
    removed: list[str] = []
    added: list[str] = []
    renamed: list[tuple[str, str]] = []
    firmware_changes: list[tuple[str, str, str]] = []
    from_v2 = source_version == "2"
    for name, pp, token in zip(names, pps, tokens):
        unit = pp.parentNode
        unit_type, firmware, has_application, _, _ = profiles[unit]
        unnamespaced = unit not in cis_units
        if (name in _V21_PP_REMOVED or (from_v2 and name in _V2_PP_REMOVED) or
                (unnamespaced and not has_application and (
                    (unit_type in _DLT_TYPES and name in _DLT_WITHOUT_APPLICATION_REMOVED) or
                    (unit_type in _NEO_TYPES and firmware.startswith(_NEO_WITHOUT_APPLICATION_PREFIX) and
                     name in _NEO_WITHOUT_APPLICATION_REMOVED)))):
            edits.append((token.start(), token.end(), b""))
            removed.append(name)
        elif from_v2 and name == _V2_EXPANDED:
            edits.append((token.end(), token.end(), _pp_tokens(_V2_EXPANSION)))
            added.extend(pair[0] for pair in _V2_EXPANSION)
        elif from_v2 and name in _V2_RENAMED:
            new_name = _V2_RENAMED[name].encode()
            edits.append((token.start(1), token.end(1), new_name))
            renamed.append((name, _V2_RENAMED[name]))
    for unit in units:
        unit_type, firmware, has_application, start, end = profiles[unit]
        if unit in cis_units:
            appended = ()
            if from_v2 and unit_type in _NEO_TYPES and firmware.startswith(_NEO_ADDED_PREFIXES):
                appended = _NEO_ADDED
            elif from_v2 and unit_type in _DLT_TYPES:
                appended = _DLT_ADDED
        elif (unit_type in _WIRELESS_TYPES and firmware.startswith(_WIRELESS_PREFIX) and
              has_application):
            appended = _WIRELESS_ADDED
        else:
            appended = ()
            for types, prefix, replacement in _FIRMWARE_RENAMES:
                if unit_type in types and firmware.startswith(prefix):
                    if unit.attributes.length:
                        raise LegacyProjectTransformError("Firmware rename drops Unit attributes; native XSLT required")
                    span = data[start.start():end.end()]
                    matches = list(_FIRMWARE_TOKEN.finditer(span))
                    if (span.count(b"<FirmwareVersion") != 1 or len(matches) != 1 or
                            matches[0].group(1).decode("ascii") != firmware):
                        raise LegacyProjectTransformError("Firmware rename requires one canonical FirmwareVersion token")
                    offset = start.start()
                    edits.append((offset + matches[0].start(), offset + matches[0].end(), b""))
                    edits.append((end.start(), end.start(),
                                  f"<FirmwareVersion>{replacement}</FirmwareVersion>".encode()))
                    firmware_changes.append((unit_type, firmware, replacement))
        if appended:
            edits.append((end.start(), end.start(), _pp_tokens(appended)))
            added.extend(pair[0] for pair in appended)
    edits.sort(key=lambda edit: (edit[0], edit[1]))
    fragments: list[bytes] = []
    offset = 0
    for begin, finish, replacement in edits:
        if begin < offset:
            raise LegacyProjectTransformError("Overlapping legacy migration edits")
        fragments.extend((data[offset:begin], replacement))
        offset = finish
    fragments.append(data[offset:])
    return _Migration(tuple(removed), tuple(added), tuple(renamed), tuple(firmware_changes),
                      b"".join(fragments))


def transform_repaired_legacy_project(
    data: bytes, *, max_bytes: int = DEFAULT_MAX_BYTES,
) -> LegacyProjectTransformResult:
    """Convert one canonical repaired Installation while preserving other bytes.

    The native cases underlying this subset use a single literal version node
    and a final LF. Earlier versions admit Units whose type and firmware are
    canonical identifiers and whose PP children are canonical tokens; the
    stylesheet templates are applied as byte edits. Other encodings, DTDs,
    alternate version spelling and XML require separate evidence and are
    rejected here.
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
        migration = (_earlier_unit_migration(document, data, source_db_version)
                     if source_db_version in ("2", "2.1") else _Migration((), (), (), (), data))
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
    output = migration.data.replace(version_literal, _VERSION_23, 1)[:-1]
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
                                        source_db_version, migration.removed, migration.added,
                                        migration.renamed, migration.firmware)
