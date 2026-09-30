#!/usr/bin/env python3
"""Map the 118 Toolkit device-dialog candidates to unit types, editors and ledger rows.

Each help dialog candidate is joined to exact unit-type evidence from the
committed help census, to the private catalogue and decoded unit-specification
metadata, to the unit/node-manager factory registrations recovered statically
from the original executable, and from there to the dialog-director form
classes present in the committed executable surface.  Ledger routing then
selects the most specific existing feature-ledger row.

Vendor inputs stay outside Git.  The committed output records identifiers,
firmware/version strings, class names and input digests only: no help prose,
catalogue descriptions, parameter definitions or instruction bytes.  Every
dialog either resolves on all three facets (unit types, editor forms and a
specific ledger row) or carries explicit unresolved reasons.  Nothing here is
acceptance evidence; the map only identifies the scope each dialog occupies.

Usage::

    python research/map_dialog_candidates.py --exe .../CBusToolkit.exe \\
        --catalog .../cbusunits.xml --spec-dir "$CBUS_UNITSPEC_DIR" [--check]
    python research/map_dialog_candidates.py --validate | --refresh

The vendor paths default to CBUS_TOOLKIT_EXE (MAP beside it),
CBUS_CATALOG_PATH or CBUS_LOCAL_CGATE_VENDOR, and CBUS_UNITSPEC_DIR.

``--validate`` needs no vendor files: it checks the committed map's input
digests and rebuilds every dialog row from the committed facts.  ``--refresh``
re-derives the dialog rows from those facts after an offline input changes.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import struct
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SURFACE_PATH = ROOT / "docs" / "toolkit-surface.json"
EXECUTABLE_SURFACE_PATH = ROOT / "docs" / "toolkit-executable-surface.json"
LEDGER_PATH = ROOT / "src" / "cbus_toolkit" / "capabilities.json"
OUTPUT_PATH = ROOT / "docs" / "toolkit-dialog-map.json"

SCHEMA_VERSION = 2
FORMAT = "cbus-toolkit-dialog-map-v2"
EXPECTED_DIALOGS = 118
GENERIC_LEDGER_IDS = frozenset({"toolkit-differential-acceptance", "toolkit-surface-census"})
CATALOGUE_SOURCE = "research/vendor/cgate/app/unitspec/cbusunits.xml"

# Ledger rows whose recorded limits name exact unit types.  The builder
# requires each type to occur literally in that row's ``limits`` text, so this
# table cannot silently drift from the feature ledger.
LEDGER_EXACT_UNIT_TYPES = {
    "classic-key-presets": ("KEY1", "KEY2", "KEY4", "BCN2B", "BCN4B", "KEYV1SP"),
    "dlt-edlt-widgets-and-labels": ("KEYGL5",),
    "interface-discovery-and-setup": ("WGATE5F", "WGATE5N"),
    "neo-core-key-presets": ("KEYA3", "KEYB4", "KEYE1", "KEYM4"),
    "sensors-wizard-semantics": (
        "SENPILL", "SENPIROA", "SENPIRIA", "SENPIRIB", "IOPE1R1", "IOPE2R2", "IOPE2C4",
    ),
    "thermostat-configuration": ("PC_TSA", "PC_TSA5", "PC_TSB", "PC_TSB5"),
}

# Version strings in a dialog title, e.g. "(2.4.00)" or "(firmware 1.00)".
FIRMWARE_HINT_RE = re.compile(r"\((?:firmware\s+)?(\d+\.\d+(?:\.\d+)?)\)")
TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")
HELP_TOPIC_RE = re.compile(r"help:(\d+)\.htm")

UNRESOLVED = {
    "no_help_unit_type": "No exact unit-type or catalogue token, no non-navigation unit-type reference cross-link in the committed help metadata and no executable help link (TFormHelp.LoadConstants) to the dialog, its product topic or a same-titled linked topic.",
    "conflicting_help_links": "Unit-type reference pages and the product/dialog pages cross-link to disjoint unit types, and no executable help link chooses between them.",
    "unknown_unit_type": "A help unit type is absent from the catalogue, decoded specifications, static unit factory and unit-dialog factory.",
    "help_unit_type_absent_from_executable": "A help unit type is absent from the catalogue, decoded specifications, static unit factory and unit-dialog factory, and neither a terminated UTF-16 literal nor a short string of its name occurs in the Toolkit executable: Toolkit 1.18 has no static path that instantiates or edits it (only TRegisterExtraUnits' external INI registration could add it at run time).",
    "firmware_hint_unmatched": "No catalogue, specification or factory firmware range contains the version named in the dialog title.",
    "no_static_node_manager": "No TUnitNodeManagerFactory or TUnitDialogFactory registration exists for a mapped unit type; EditUnit's CommonCBusUnit fallback director would find no unit dialog for it.",
    "no_director": "The registered node manager references no dialog-director class and no TUnitDialogFactory registration exists for the unit type.",
    "no_dialog_form": "The dialog director chain or unit-dialog registration references no form present in the executable surface.",
    "generic_ledger_only": "No specific ledger row names the mapped unit types or shares their editor, and the help-branch triage is generic; only the generic differential row applies.",
}


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def render(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def spec_directory_digest(directory: Path) -> tuple[str, int]:
    """Digest of (name, content digest) for every ``*.xml`` spec, name-sorted."""
    lines = []
    for path in sorted(directory.glob("*.xml"), key=lambda item: item.name):
        lines.append(f"{path.name}\t{digest(path)}\n")
    if not lines:
        raise ValueError("Unit specification directory contains no *.xml files")
    return sha256("".join(lines).encode("utf-8")).hexdigest(), len(lines)


# --------------------------------------------------------------------------
# Static recovery from the original executable (vendor input, research only)
# --------------------------------------------------------------------------

VMT_SELF_OFFSET = 88  # Delphi 32-bit: vmtSelfPtr = -88
VMT_CLASS_NAME = -56
VMT_PARENT = -48


class _Image:
    """Read-only view of the original PE image plus its MAP symbols."""

    def __init__(self, exe_raw: bytes, map_raw: bytes) -> None:
        import pefile

        self.pe = pefile.PE(data=exe_raw, fast_load=True)
        if self.pe.FILE_HEADER.Machine != 0x14C:
            raise ValueError("Expected the pinned x86 Toolkit image")
        self.base = self.pe.OPTIONAL_HEADER.ImageBase
        sections = {
            section.Name.rstrip(b"\0").decode("ascii"): section
            for section in self.pe.sections
        }
        self.sections = sections
        segment_bases = {
            1: self.base + sections[".text"].VirtualAddress,
            2: self.base + sections[".itext"].VirtualAddress,
            3: self.base + sections[".data"].VirtualAddress,
            4: self.base + sections[".bss"].VirtualAddress,
        }
        self.code_end = segment_bases[3]
        self.symbols: dict[int, set[str]] = {}
        self.by_name: dict[str, int] = {}
        for line in map_raw.decode("cp1252").splitlines():
            match = re.fullmatch(r"\s*000([1-4]):([0-9A-Fa-f]{8})\s+(\S+)\s*", line)
            if match:
                address = int(match[2], 16) + segment_bases[int(match[1])]
                self.symbols.setdefault(address, set()).add(match[3])
                self.by_name.setdefault(match[3], address)
        self.code_starts = sorted(
            address for address in self.symbols if address < self.code_end
        )
        self.methods: dict[str, list[tuple[str, int]]] = defaultdict(list)
        for address, names in self.symbols.items():
            if address >= self.code_end:
                continue
            for name in names:
                match = re.fullmatch(r"CIS_\w+\.(T\w+)\.(\w+)", name)
                if match:
                    self.methods[match[1]].append((match[2], address))
        for entries in self.methods.values():
            entries.sort()
        import capstone

        self.decoder = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        self._class_cache: dict[int, list[str] | None] = {}

    def symbol(self, name: str) -> int:
        try:
            return self.by_name[name]
        except KeyError as exc:
            raise ValueError(f"Missing original MAP symbol: {name}") from exc

    def dword(self, address: int) -> int:
        return struct.unpack("<I", self.pe.get_data(address - self.base, 4))[0]

    def short_string(self, address: int) -> str:
        length = self.pe.get_data(address - self.base, 1)[0]
        return self.pe.get_data(address - self.base + 1, length).decode("latin-1")

    def unicode_literal(self, address: int) -> str | None:
        """A constant Delphi UnicodeString (code page 1200, refcount -1)."""
        try:
            code_page, element, refcount, length = struct.unpack(
                "<HHiI", self.pe.get_data(address - self.base - 12, 12)
            )
        except Exception:
            return None
        if code_page != 1200 or element != 2 or refcount != -1 or not 0 < length <= 64:
            return None
        return self.pe.get_data(address - self.base, length * 2).decode("utf-16-le")

    def class_chain(self, self_pointer: int) -> list[str] | None:
        """Class names from a VMT self-pointer slot up to TObject, else None."""
        if self_pointer in self._class_cache:
            return self._class_cache[self_pointer]
        chain: list[str] | None = []
        current = self_pointer
        try:
            while current:
                vmt = self.dword(current)
                if vmt != current + VMT_SELF_OFFSET or len(chain) > 64:
                    chain = None
                    break
                chain.append(self.short_string(self.dword(vmt + VMT_CLASS_NAME)))
                current = self.dword(vmt + VMT_PARENT)
        except Exception:
            chain = None
        if chain is not None and (not chain or chain[-1] != "TObject"):
            chain = None
        self._class_cache[self_pointer] = chain
        return chain

    def procedure(self, address: int) -> list[Any]:
        from bisect import bisect_right

        index = bisect_right(self.code_starts, address) - 1
        start = self.code_starts[index]
        end = self.code_starts[index + 1]
        if not 0 < end - start <= 1 << 20:
            raise ValueError(f"Unbounded original procedure at {start:#x}")
        return list(self.decoder.disasm(self.pe.get_data(start - self.base, end - start), start))

    def call_sites(self, targets: set[int]) -> list[tuple[int, int]]:
        sites = []
        for name in (".text", ".itext"):
            section = self.sections[name]
            data = self.pe.get_data(section.VirtualAddress, section.Misc_VirtualSize)
            origin = self.base + section.VirtualAddress
            for match in re.finditer(rb"\xe8", data):
                offset = match.start()
                if offset + 5 > len(data):
                    break
                target = origin + offset + 5 + struct.unpack("<i", data[offset + 1:offset + 5])[0]
                if target in targets:
                    sites.append((origin + offset, target))
        return sorted(sites)

    def class_refs(self, address: int) -> list[list[str]]:
        refs = []
        for instruction in self.procedure(address):
            for operand in re.findall(r"dword ptr \[(0x[0-9a-f]+)\]", instruction.op_str):
                chain = self.class_chain(int(operand, 16))
                if chain:
                    refs.append(chain)
        return refs


def _registrations(image: _Image) -> dict[str, Any]:
    """Decode every static RegisterUnitType/RegisterNodeManager call site.

    Initialisation sections load the factory singleton into EAX, the class
    reference into ECX and a constant type string into EDX; RegisterUnitType
    additionally pushes the minimum and maximum firmware strings.  A site
    whose arguments are not all constants is reported unresolved.
    """
    unit_factory = image.symbol("CIS_TCISUnitFactory.UnitFactory")
    node_factory = image.symbol("CIS_TCISUnitNodeManagerFactory.UnitNodeManagerFactory")
    register_unit = image.symbol("CIS_TCISUnitFactory.TUnitTypeFactory.RegisterUnitType")
    register_node = image.symbol(
        "CIS_TCISUnitNodeManagerFactory.TUnitNodeManagerFactory.RegisterNodeManager"
    )
    sites = image.call_sites({register_unit, register_node})
    by_procedure: dict[int, list[int]] = defaultdict(list)
    for site, _ in sites:
        start = image.procedure(site)[0].address
        by_procedure[start].append(site)
    units: list[dict] = []
    nodes: list[dict] = []
    unresolved: list[dict] = []
    for start in sorted(by_procedure):
        state: dict[str, tuple[str, int]] = {}
        pushed: list[tuple[str, int]] = []
        for instruction in image.procedure(start):
            mnemonic, operands = instruction.mnemonic, instruction.op_str
            if mnemonic == "mov":
                match = re.fullmatch(r"(e[a-d]x), dword ptr \[(0x[0-9a-f]+)\]", operands)
                if match:
                    state[match[1]] = ("memory", int(match[2], 16))
                    continue
                if operands == "eax, dword ptr [eax]" and state.get("eax", ("", 0))[0] == "memory":
                    state["eax"] = ("variable", image.dword(state["eax"][1]))
                    continue
                match = re.fullmatch(r"(e[a-d]x), (0x[0-9a-f]+)", operands)
                if match:
                    state[match[1]] = ("immediate", int(match[2], 16))
                    continue
                match = re.match(r"(e[a-d]x),", operands)
                if match:
                    state[match[1]] = ("unknown", 0)
                continue
            if mnemonic == "push":
                match = re.fullmatch(r"0x[0-9a-f]+", operands)
                pushed.append(("immediate", int(operands, 16)) if match else ("unknown", 0))
                continue
            if mnemonic != "call":
                continue
            target = int(operands, 16) if operands.startswith("0x") else None
            if target in (register_unit, register_node):
                owner = sorted(image.symbols.get(start, {"?"}))[0]
                factory = state.get("eax", ("unknown", 0))
                class_ref = state.get("ecx", ("unknown", 0))
                type_ref = state.get("edx", ("unknown", 0))
                chain = image.class_chain(class_ref[1]) if class_ref[0] == "memory" else None
                type_name = image.unicode_literal(type_ref[1]) if type_ref[0] == "immediate" else None
                expected_factory = unit_factory if target == register_unit else node_factory
                record: dict[str, Any] = {"procedure": owner}
                firmware: list[str | None] = []
                if target == register_unit:
                    firmware = [
                        image.unicode_literal(value) if kind == "immediate" else None
                        for kind, value in pushed[-2:]
                    ]
                if (
                    factory != ("variable", expected_factory)
                    or chain is None
                    or type_name is None
                    or (target == register_unit and (len(firmware) != 2 or None in firmware))
                ):
                    record["factory"] = "unit" if target == register_unit else "node_manager"
                    record["reason"] = "Arguments are computed at run time, not constant at the call site."
                    unresolved.append(record)
                elif target == register_unit:
                    units.append({
                        "unit_type": type_name,
                        "min_firmware": firmware[0],
                        "max_firmware": firmware[1],
                        "unit_class": chain[0],
                    })
                else:
                    nodes.append({"unit_type": type_name, "node_manager": chain[0], "chain": chain})
            state, pushed = {}, []
    return {
        "unit_call_sites": sum(1 for _, target in sites if target == register_unit),
        "node_manager_call_sites": sum(1 for _, target in sites if target == register_node),
        "units": units,
        "nodes": nodes,
        "unresolved": sorted(unresolved, key=lambda row: (row["factory"], row["procedure"])),
    }


def _directors_for_node_manager(image: _Image, chain: list[str]) -> tuple[list[str], str | None]:
    """Dialog-director classes referenced by the nearest node-manager class."""
    for class_name in chain:
        if class_name == "TNodeManager":
            break
        found: list[str] = []
        for _, address in image.methods.get(class_name, []):
            for ref in image.class_refs(address):
                if "TDialogDirector" in ref and ref[0] not in found:
                    found.append(ref[0])
        if found:
            return sorted(found), class_name
    return [], None


def _forms_for_director(image: _Image, chain: list[str]) -> dict[str, Any]:
    """Forms/frames referenced by a director class and its director ancestors.

    Dialog forms (TfKipperBaseGUI descendants) come from the nearest class in
    the chain that references any, so an override replaces an ancestor's form.
    Auxiliary forms and frames are the union across the director chain.
    """
    dialog_forms: list[str] = []
    defined_by = None
    auxiliary: set[str] = set()
    frames: set[str] = set()
    for class_name in chain:
        if class_name == "TDialogDirector":
            break
        local: list[str] = []
        for _, address in image.methods.get(class_name, []):
            for ref in image.class_refs(address):
                if "TfKipperBaseGUI" in ref[1:]:
                    if ref[0] not in local:
                        local.append(ref[0])
                elif "TCustomForm" in ref[1:] and ref[0] != "TfKipperBaseGUI":
                    auxiliary.add(ref[0])
                elif "TFrame" in ref[1:]:
                    frames.add(ref[0])
        if local and not dialog_forms:
            dialog_forms, defined_by = sorted(local), class_name
    return {
        "dialog_forms": dialog_forms,
        "dialog_forms_defined_by": defined_by,
        "auxiliary_forms": sorted(auxiliary - set(dialog_forms)),
        "frames": sorted(frames),
    }


COMMON_DESCRIPTOR = "CommonCBusUnit"


def _unit_dialog_registrations(image: _Image) -> dict[str, Any]:
    """Decode every static TUnitDialogFactory.RegisterUnitDialog call site.

    Form initialisation sections load the factory singleton into EAX, the
    form class reference into ECX and a constant type string into EDX, and
    push a third string argument (nil at every static site).
    """
    factory = image.symbol("CIS_TUnitDialogFactory.UnitDialogFactory")
    register = image.symbol("CIS_TUnitDialogFactory.TUnitDialogFactory.RegisterUnitDialog")
    sites = image.call_sites({register})
    registrations: list[dict] = []
    unresolved: list[dict] = []
    for start in sorted({image.procedure(site)[0].address for site, _ in sites}):
        state: dict[str, tuple[str, int]] = {}
        pushed: list[tuple[str, int]] = []
        for instruction in image.procedure(start):
            mnemonic, operands = instruction.mnemonic, instruction.op_str
            if mnemonic == "mov":
                match = re.fullmatch(r"(e[a-d]x), dword ptr \[(0x[0-9a-f]+)\]", operands)
                if match:
                    state[match[1]] = ("memory", int(match[2], 16))
                elif operands == "eax, dword ptr [eax]" and state.get("eax", ("", 0))[0] == "memory":
                    state["eax"] = ("variable", image.dword(state["eax"][1]))
                elif match := re.fullmatch(r"(e[a-d]x), (0x[0-9a-f]+)", operands):
                    state[match[1]] = ("immediate", int(match[2], 16))
                elif match := re.match(r"(e[a-d]x),", operands):
                    state[match[1]] = ("unknown", 0)
                continue
            if mnemonic == "push":
                pushed.append(
                    ("immediate", int(operands, 16))
                    if re.fullmatch(r"0x[0-9a-f]+|0", operands) else ("unknown", 0)
                )
                continue
            if mnemonic != "call":
                continue
            if operands.startswith("0x") and int(operands, 16) == register:
                class_ref = state.get("ecx", ("unknown", 0))
                type_ref = state.get("edx", ("unknown", 0))
                chain = image.class_chain(class_ref[1]) if class_ref[0] == "memory" else None
                type_name = image.unicode_literal(type_ref[1]) if type_ref[0] == "immediate" else None
                owner = sorted(image.symbols.get(start, {"?"}))[0]
                if (
                    state.get("eax") != ("variable", factory)
                    or chain is None
                    or "TCustomForm" not in chain
                    or type_name is None
                    or pushed[-1:] != [("immediate", 0)]
                ):
                    unresolved.append({
                        "procedure": owner,
                        "reason": "Arguments are computed at run time, not constant at the call site.",
                    })
                else:
                    registrations.append({
                        "unit_type": type_name,
                        "form_class": chain[0],
                        "form_chain": chain[: chain.index("TForm")],
                        "third_argument": None,
                    })
            state, pushed = {}, []
    return {"call_sites": len(sites), "registrations": registrations, "unresolved": unresolved}


def _common_director_fallback(image: _Image) -> dict[str, Any]:
    """Prove the static EditUnit fallback that reaches the unit-dialog factory.

    ``TCBusUnitGUIAgent.EditUnit`` asks the node-manager factory for a
    director by object, then by the unit type, and when both return nil by
    the constant ``CommonCBusUnit`` descriptor.  ``TddCommonCBusUnit.
    Initialise`` looks the unit type up with ``TUnitDialogFactory.
    GetUnitDialog``.  Both facts are required; a changed image raises.
    """
    edit_unit = "CIS_TCBusUnitGUIAgent.TCBusUnitGUIAgent.EditUnit"
    by_object = image.symbol("CIS_TCISUnitNodeManagerFactory.TUnitNodeManagerFactory.GetDirectorClassByObject")
    by_type = image.symbol("CIS_TCISUnitNodeManagerFactory.TUnitNodeManagerFactory.GetDirectorClass")
    get_dialog = image.symbol("CIS_TUnitDialogFactory.TUnitDialogFactory.GetUnitDialog")
    initialise = "CIS_TddCommonCBusUnit.TddCommonCBusUnit.Initialise"
    order: list[str] = []
    pending_literal = None
    for instruction in image.procedure(image.symbol(edit_unit)):
        if instruction.mnemonic == "mov" and (match := re.fullmatch(r"edx, (0x[0-9a-f]+)", instruction.op_str)):
            pending_literal = image.unicode_literal(int(match[1], 16))
        elif instruction.mnemonic == "call" and instruction.op_str.startswith("0x"):
            target = int(instruction.op_str, 16)
            if target == by_object:
                order.append("by_object")
            elif target == by_type:
                order.append(f"by_descriptor:{pending_literal}" if pending_literal else "by_unit_type")
            pending_literal = None
    if order[-3:] != ["by_object", "by_unit_type", f"by_descriptor:{COMMON_DESCRIPTOR}"]:
        raise ValueError("EditUnit no longer falls back to the CommonCBusUnit director")
    callers = {
        sorted(image.symbols.get(image.procedure(site)[0].address, {"?"}))[0]
        for site, _ in image.call_sites({get_dialog})
    }
    if callers != {initialise}:
        raise ValueError("GetUnitDialog callers changed")
    return {
        "procedure": edit_unit,
        "director_lookup_order": order[-3:],
        "fallback_descriptor": COMMON_DESCRIPTOR,
        "unit_dialog_lookup": f"{initialise} -> TUnitDialogFactory.GetUnitDialog(unit type)",
    }


def _help_links(image: _Image) -> list[dict]:
    """The TFormHelp.LoadConstants ``Name=<context id>`` table, in load order.

    Keys are unit types, unit classes or form classes; each context id is a
    help topic number.  Every entry is an IntToStr of an immediate followed by
    a constant ``Name=`` literal; any other shape raises.
    """
    int_to_str = {
        address for address, names in image.symbols.items() if "SysUtils.IntToStr" in names
    }
    rows: list[dict] = []
    value = pending = None
    for instruction in image.procedure(image.symbol("CIS_TKipperHelp.TFormHelp.LoadConstants")):
        operands = instruction.op_str
        if instruction.mnemonic == "mov" and (match := re.fullmatch(r"eax, (0x[0-9a-f]+|\d+)", operands)):
            value = int(match[1], 0)
        elif instruction.mnemonic == "call" and operands.startswith("0x") and int(operands, 16) in int_to_str:
            pending, value = value, None
        elif instruction.mnemonic == "mov" and (match := re.fullmatch(r"edx, (0x[0-9a-f]+)", operands)):
            literal = image.unicode_literal(int(match[1], 16))
            if literal and literal.endswith("="):
                if pending is None:
                    raise ValueError(f"Help constant {literal!r} has no immediate context id")
                rows.append({"key": literal[:-1], "context_id": pending})
                pending = None
    if not rows:
        raise ValueError("No help constants recovered")
    return rows


def _forms_for_form_class(image: _Image, chain: list[str]) -> dict[str, Any]:
    """Frames and auxiliary forms a registered unit form's own methods reference."""
    auxiliary: set[str] = set()
    frames: set[str] = set()
    for class_name in chain:
        for _, address in image.methods.get(class_name, []):
            for ref in image.class_refs(address):
                if "TFrame" in ref[1:]:
                    frames.add(ref[0])
                elif "TCustomForm" in ref[1:] and ref[0] not in chain and ref[0] not in ("TForm", "TfrmCBusUnitBase"):
                    auxiliary.add(ref[0])
    return {"auxiliary_forms": sorted(auxiliary), "frames": sorted(frames)}


def _literal_presence(exe_raw: bytes, names: list[str]) -> dict[str, dict[str, bool]]:
    """Whether each name occurs as a terminated UTF-16 or Delphi short-string literal."""
    result = {}
    for name in sorted(set(names)):
        utf16 = name.encode("utf-16-le")
        ascii_name = name.encode("latin-1")
        result[name] = {
            "utf16_literal": re.search(rb"(?<![\x21-\x7e]\x00)" + re.escape(utf16) + rb"\x00\x00", exe_raw) is not None,
            "short_string": bytes([len(ascii_name)]) + ascii_name in exe_raw,
        }
    return result


def extract_vendor_facts(
    exe_path: Path, map_path: Path, catalog_path: Path, spec_dir: Path
) -> dict[str, Any]:
    sys.path.insert(0, str(ROOT / "src"))
    from cbus_toolkit.unitspec import UnitCatalog, UnitSpecStore

    surface = load_json(SURFACE_PATH)
    executable = load_json(EXECUTABLE_SURFACE_PATH)
    exe_raw, map_raw = exe_path.read_bytes(), map_path.read_bytes()
    exe_sha, map_sha = sha256(exe_raw).hexdigest(), sha256(map_raw).hexdigest()
    if exe_sha != executable["sources"]["executable"]["sha256"]:
        raise ValueError("Toolkit executable differs from the executable surface source")
    if map_sha != executable["sources"]["map"]["sha256"]:
        raise ValueError("Toolkit MAP differs from the executable surface source")
    catalog_sha = digest(catalog_path)
    census_catalog = [
        row["sha256"] for row in surface["source_artifacts"] if row["path"] == CATALOGUE_SOURCE
    ]
    if census_catalog != [catalog_sha]:
        raise ValueError("Unit catalogue differs from the help census source artifact")
    spec_sha, spec_count = spec_directory_digest(spec_dir)

    catalogue = UnitCatalog.load(catalog_path)
    specs = UnitSpecStore(spec_dir).list_specs()
    image = _Image(exe_raw, map_raw)
    registrations = _registrations(image)

    unit_types: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "catalogue_numbers": set(),
        "alternative_catalogue_numbers": set(),
        "catalogue_revisions": set(),
        "spec_files": set(),
        "factory_registrations": set(),
        "node_managers": set(),
    })
    for record in catalogue.records:
        entry = unit_types[record["unit_type"]]
        entry["catalogue_numbers"].add(record["catalog_number"])
        entry["alternative_catalogue_numbers"].update(record["alternatives"])
        entry["catalogue_revisions"].add((
            record["minimum_version"],
            record["maximum_version"],
            record["spec_filename"],
            record["revision"].get("ClassName", ""),
        ))
    for spec in specs:
        if spec["unit_type"]:
            unit_types[spec["unit_type"]]["spec_files"].add(
                (spec["filename"], spec["minimum_version"], spec["maximum_version"])
            )
    for row in registrations["units"]:
        unit_types[row["unit_type"]]["factory_registrations"].add(
            (row["min_firmware"], row["max_firmware"], row["unit_class"])
        )
    node_chains: dict[str, list[str]] = {}
    for row in registrations["nodes"]:
        unit_types[row["unit_type"]]["node_managers"].add(row["node_manager"])
        node_chains[row["node_manager"]] = row["chain"]

    node_managers: dict[str, dict[str, Any]] = {}
    director_refs: dict[str, list[str]] = {}
    for name in sorted(node_chains):
        directors, defined_by = _directors_for_node_manager(image, node_chains[name])
        node_managers[name] = {"directors": directors, "directors_defined_by": defined_by}
        for director in directors:
            director_refs.setdefault(director, [])
    director_chains = {}
    for address, names in image.symbols.items():
        for symbol in names:
            match = re.fullmatch(r"CIS_\w+\.\.(Tdd\w+)", symbol)
            if match and match[1] in director_refs:
                chain = image.class_chain(address)
                if chain and chain[0] == match[1]:
                    director_chains[match[1]] = chain
    missing = sorted(set(director_refs) - set(director_chains))
    if missing:
        raise ValueError(f"Director class references without a VMT: {missing}")
    directors = {
        name: _forms_for_director(image, director_chains[name])
        for name in sorted(director_chains)
    }
    dialog_registrations = _unit_dialog_registrations(image)
    fallback = _common_director_fallback(image)
    fallback_managers = sorted(unit_types.get(COMMON_DESCRIPTOR, {}).get("node_managers", ()))
    fallback_directors = sorted({
        director for manager in fallback_managers for director in node_managers[manager]["directors"]
    })
    if len(fallback_directors) != 1:
        raise ValueError("The CommonCBusUnit descriptor no longer names exactly one director")
    unit_forms = {}
    for row in dialog_registrations["registrations"]:
        unit_forms.setdefault(row["form_class"], _forms_for_form_class(image, row["form_chain"]))
    product_types = {
        name for name, entry in unit_types.items()
        if entry["catalogue_numbers"] or entry["factory_registrations"]
    }
    topics = {topic["id"]: topic for topic in surface["topics"]}
    help_only = sorted(
        {topics[topic_id]["title"] for topic_id in surface["unit_type_reference_entries"]}
        - product_types
        - {row["unit_type"] for row in dialog_registrations["registrations"]}
    )
    help_links = _help_links(image)
    if sha256(exe_path.read_bytes()).hexdigest() != exe_sha or digest(map_path) != map_sha:
        raise ValueError("Original files changed during inspection")

    def rows(values: set[tuple], keys: tuple[str, ...]) -> list[dict]:
        return [dict(zip(keys, value)) for value in sorted(values)]

    type_rows = {}
    for name in sorted(unit_types):
        entry = unit_types[name]
        type_rows[name] = {
            "catalogue_numbers": sorted(entry["catalogue_numbers"]),
            "alternative_catalogue_numbers": sorted(entry["alternative_catalogue_numbers"]),
            "catalogue_revisions": rows(
                entry["catalogue_revisions"],
                ("min_firmware", "max_firmware", "spec_file", "catalogue_class"),
            ),
            "spec_files": rows(entry["spec_files"], ("spec_file", "min_firmware", "max_firmware")),
            "factory_registrations": rows(
                entry["factory_registrations"], ("min_firmware", "max_firmware", "unit_class")
            ),
            "node_managers": sorted(entry["node_managers"]),
        }
    return {
        "inputs": {
            "toolkit_executable": {"sha256": exe_sha},
            "toolkit_map": {"sha256": map_sha},
            "unit_catalogue": {"sha256": catalog_sha, "source": CATALOGUE_SOURCE},
            "unitspec_directory": {
                "sha256": spec_sha,
                "files": spec_count,
                "digest_rule": "sha256 over name-sorted lines '<file>\\t<sha256>\\n' for every *.xml",
            },
        },
        "unit_factory": {
            "status": "recovered_static_registrations",
            "method": (
                "Static decode of every call to TUnitTypeFactory.RegisterUnitType and "
                "TUnitNodeManagerFactory.RegisterNodeManager: factory singleton in EAX, VMT "
                "class reference in ECX, constant UnicodeString type in EDX and pushed "
                "minimum/maximum firmware strings; class names read from the VMT."
            ),
            "unit_call_sites": registrations["unit_call_sites"],
            "unit_registrations": len(registrations["units"]),
            "node_manager_call_sites": registrations["node_manager_call_sites"],
            "node_manager_registrations": len(registrations["nodes"]),
            "unresolved_call_sites": registrations["unresolved"],
            "original_executed": False,
        },
        "unit_types": type_rows,
        "node_managers": node_managers,
        "directors": directors,
        "unit_dialog_factory": {
            "status": "recovered_static_registrations",
            "method": (
                "Static decode of every call to TUnitDialogFactory.RegisterUnitDialog: factory "
                "singleton in EAX, form class reference in ECX, constant UnicodeString type in "
                "EDX and a pushed nil third string; plus the TCBusUnitGUIAgent.EditUnit director "
                "lookup order whose last step is the constant CommonCBusUnit descriptor."
            ),
            "call_sites": dialog_registrations["call_sites"],
            "registrations": dialog_registrations["registrations"],
            "unresolved_call_sites": dialog_registrations["unresolved"],
            "director_fallback": {
                **fallback,
                "node_managers": fallback_managers,
                "director": fallback_directors[0],
            },
            "forms": unit_forms,
            "original_executed": False,
        },
        "help_links": {
            "status": "recovered_static_table",
            "method": (
                "Static decode of TFormHelp.LoadConstants: each IntToStr(immediate context id) "
                "concatenated to a constant 'Name=' literal; keys are unit types, unit classes "
                "or form classes and context ids are help topic numbers."
            ),
            "entries": help_links,
            "original_executed": False,
        },
        "help_only_unit_types": _literal_presence(exe_raw, help_only),
    }


# --------------------------------------------------------------------------
# Pure assembly from committed inputs plus recorded facts
# --------------------------------------------------------------------------


def _browse_neighbours(surface: dict) -> dict[str, set[str]]:
    order = sorted(surface["topics"], key=lambda topic: topic["ordinal"])
    neighbours: dict[str, set[str]] = {}
    for index, topic in enumerate(order):
        adjacent = set()
        if index:
            adjacent.add(order[index - 1]["file"])
        if index + 1 < len(order):
            adjacent.add(order[index + 1]["file"])
        neighbours[topic["id"]] = adjacent
    return neighbours


def _content_links(topic: dict, neighbours: dict[str, set[str]]) -> set[str]:
    """Linked topic files, excluding previous/next browse-sequence links."""
    return set(topic["page"]["linked_topic_files"]) - neighbours[topic["id"]]


def _catalogue_index(unit_types: dict[str, dict]) -> dict[str, set[str]]:
    index: dict[str, set[str]] = defaultdict(set)
    for name, entry in unit_types.items():
        for number in entry["catalogue_numbers"] + entry["alternative_catalogue_numbers"]:
            if "*" not in number:
                index[number].add(name)
    return index


def _version_components(version: str) -> list[int] | None:
    cleaned = re.sub(r"[^0-9.]", "", version).rstrip(".")
    if not cleaned or any(not part for part in cleaned.split(".")):
        return None
    return [int(part) for part in cleaned.split(".")]


def _contains(version: str, minimum: str, maximum: str) -> bool:
    """C-Gate numeric-component comparison; blank bounds are open."""
    wanted = _version_components(version)
    if wanted is None:
        return False

    def compare(left: list[int], right: list[int]) -> int:
        width = max(len(left), len(right))
        left, right = left + [0] * (width - len(left)), right + [0] * (width - len(right))
        return (left > right) - (left < right)

    for bound, sign in ((minimum, 1), (maximum, -1)):
        if bound:
            parsed = _version_components(bound)
            if parsed is None or compare(wanted, parsed) * sign < 0:
                return False
    return True


def _help_link_types(help_links: dict, unit_types: dict[str, dict]) -> dict[str, list[tuple[str, str]]]:
    """Help topic id -> [(LoadConstants key, unit type)] for keys naming unit types.

    A key names a unit type directly or is a unit class that the static unit
    factory registers for it.  Form-class keys identify no unit type.
    """
    by_class: dict[str, set[str]] = defaultdict(set)
    for name, entry in unit_types.items():
        for row in entry["factory_registrations"]:
            by_class[row["unit_class"]].add(name)
    result: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for row in help_links["entries"]:
        named = {row["key"]} if row["key"] in unit_types else by_class.get(row["key"], set())
        for unit_type in sorted(named):
            pair = (row["key"], unit_type)
            topic_id = f"help:{row['context_id']}.htm"
            if pair not in result[topic_id]:
                result[topic_id].append(pair)
    return result


def _help_evidence(dialog: dict, topics: dict, reference_by_file: dict, neighbours: dict,
                   catalogue_index: dict, known_types: set[str],
                   help_link_types: dict[str, list[tuple[str, str]]]) -> dict[str, Any]:
    topic = topics[dialog["topic_id"]]
    subtree = set(dialog["descendant_topic_ids"])
    product_id = topic["parent_id"]
    product_file = topics[product_id]["file"] if product_id else None

    evidence: list[dict] = []
    text = " ".join([dialog["title"], *dialog["device_path"]])
    for token in sorted(set(TOKEN_RE.findall(text))):
        if token in known_types:
            evidence.append({"unit_type": token, "basis": "title_unit_type_token", "token": token})
        for unit_type in sorted(catalogue_index.get(token, ())):
            evidence.append({"unit_type": unit_type, "basis": "title_catalogue_token", "token": token})
    for file_name, (reference_id, unit_type) in sorted(reference_by_file.items()):
        links = _content_links(topics[reference_id], neighbours)
        if topic["file"] in links:
            evidence.append({
                "unit_type": unit_type,
                "basis": "reference_links_dialog_topic",
                "reference_topic_id": reference_id,
            })
        if product_file and product_file in links:
            evidence.append({
                "unit_type": unit_type,
                "basis": "reference_links_product_topic",
                "reference_topic_id": reference_id,
            })
    for source_id in sorted(subtree | ({product_id} if product_id else set())):
        for file_name in sorted(_content_links(topics[source_id], neighbours)):
            if file_name in reference_by_file:
                reference_id, unit_type = reference_by_file[file_name]
                evidence.append({
                    "unit_type": unit_type,
                    "basis": "dialog_or_product_links_reference",
                    "reference_topic_id": reference_id,
                    "source_topic_id": source_id,
                })

    help_evidence = len(evidence)
    # Executable help links (TFormHelp.LoadConstants) name the topic Toolkit
    # opens for a unit type or class.  They decide only where the help
    # metadata selects nothing or conflicts.
    linked_topics = [(dialog["topic_id"], "executable_help_link_dialog_topics")]
    linked_topics += [(topic_id, "executable_help_link_dialog_topics") for topic_id in sorted(subtree)]
    if product_id:
        linked_topics.append((product_id, "executable_help_link_product_topic"))
    for file_name in sorted(_content_links(topic, neighbours)):
        target_id = f"help:{file_name}"
        if target_id in topics and dialog["title"] == f"{topics[target_id]['title']} dialog box":
            linked_topics.append((target_id, "executable_help_link_titled_topic"))
    for target_id, basis in linked_topics:
        for key, unit_type in help_link_types.get(target_id, ()):
            evidence.append({
                "unit_type": unit_type,
                "basis": basis,
                "help_link_key": key,
                "help_topic_id": target_id,
            })

    def types(*bases: str) -> set[str]:
        return {row["unit_type"] for row in evidence if row["basis"] in bases}

    direct = types("title_unit_type_token", "title_catalogue_token", "reference_links_dialog_topic")
    inbound = types("reference_links_product_topic")
    outbound = types("dialog_or_product_links_reference")
    if direct:
        selected, rule = direct, "direct"
    elif inbound and outbound:
        selected, rule = inbound & outbound, "bidirectional_product_links"
    else:
        selected, rule = inbound | outbound, "one_directional_product_link"
    reason = None
    if not help_evidence:
        rule, reason = "none", "no_help_unit_type"
    elif not selected:
        rule, reason = "conflict", "conflicting_help_links"
    candidates = direct | inbound | outbound
    linked = types(
        "executable_help_link_dialog_topics",
        "executable_help_link_product_topic",
        "executable_help_link_titled_topic",
    )
    if reason and linked:
        chosen = linked & candidates if reason == "conflicting_help_links" else linked
        if chosen:
            selected, rule, reason = chosen, f"executable_help_link_{rule}", None
    return {
        "evidence": evidence,
        "selection_rule": rule,
        "selected": sorted(selected),
        "other_candidates": sorted(candidates - selected),
        "reason": reason,
    }


def _ranges_for(entry: dict) -> list[tuple[str, str]]:
    return (
        [(row["min_firmware"], row["max_firmware"]) for row in entry["catalogue_revisions"]]
        + [(row["min_firmware"], row["max_firmware"]) for row in entry["spec_files"]]
        + [(row["min_firmware"], row["max_firmware"]) for row in entry["factory_registrations"]]
    )


KEY_PRESET_RECEIPT = ROOT / "research" / "fixtures" / "key-preset-family-equivalence.json"
KEY_PRESET_LEDGER_FAMILIES = {"classic-key-presets": "classic", "neo-core-key-presets": "neo"}


def _admitted_key_preset_types() -> dict[str, set[str]]:
    """Unit types the committed key-preset family receipt admits, per ledger row."""
    if not KEY_PRESET_RECEIPT.is_file():
        return {}
    families = json.loads(KEY_PRESET_RECEIPT.read_text(encoding="utf-8"))["families"]
    return {
        ledger_id: {
            row["unit_type"]
            for row in families[family]["types"]
            if row.get("decision") == "admitted"
        }
        for ledger_id, family in KEY_PRESET_LEDGER_FAMILIES.items()
    }


# --------------------------------------------------------------------------
# Implemented editors and control -> parameter receipts (P5.01, #38)
# --------------------------------------------------------------------------

# Committed Toolkit CLI editors that reproduce part of a dialog.  A dialog
# links to an editor when one of its in-scope unit types is admitted by the
# editor.  ``control_receipt`` names a committed static source review whose
# ``controls`` rows bind named form controls to unit parameters; editors
# without one are linked but map no controls.
IMPLEMENTED_EDITORS: tuple[dict[str, Any], ...] = (
    {
        "id": "din-output-settings",
        "ledger_id": "all-unit-parameter-encoding",
        "modules": ["src/cbus_toolkit/din_output_settings.py"],
        "documentation": "docs/din-output-settings.md",
        "receipts": [
            "research/fixtures/din-output-settings-source-review.json",
            "research/fixtures/din-output-settings-native-acceptance.json",
            "research/fixtures/din-output-level-original-vectors.json",
        ],
        "control_receipt": {"path": "research/fixtures/din-output-settings-source-review.json", "section": None},
        "unit_types_from": ("receipt_profiles", "research/fixtures/din-output-settings-source-review.json"),
    },
    {
        "id": "iope-settings",
        "ledger_id": "sensors-wizard-semantics",
        "modules": ["src/cbus_toolkit/iope_settings.py", "src/cbus_toolkit/iope_cli.py"],
        "documentation": "docs/iope-settings.md",
        "receipts": [
            "research/fixtures/iope-settings-source-review.json",
            "research/fixtures/iope-settings-native-acceptance.json",
        ],
        "control_receipt": {"path": "research/fixtures/iope-settings-source-review.json", "section": None},
        "unit_types_from": ("receipt_profiles", "research/fixtures/iope-settings-source-review.json"),
    },
    {
        "id": "wireless-gateway-remote-switch",
        "ledger_id": "interface-discovery-and-setup",
        "modules": ["src/cbus_toolkit/wireless_gateway.py", "src/cbus_toolkit/wireless_cli.py"],
        "documentation": "docs/wireless.md",
        "receipts": [
            "research/fixtures/wireless-source-review.json",
            "research/fixtures/wireless-gateway-native-acceptance.json",
        ],
        "control_receipt": {"path": "research/fixtures/wireless-source-review.json", "section": "gateway"},
        "unit_types_from": ("literal", ("WGATE5F",)),
        # The receipt names the help dialog it reproduces; help selects only
        # WGATE5N there, whose gateway class the editor refuses.
        "dialog_ids_from": ("research/fixtures/wireless-source-review.json", "gateway"),
    },
    {
        "id": "wireless-unit-globals",
        "ledger_id": "interface-discovery-and-setup",
        "modules": ["src/cbus_toolkit/wireless_unit_globals.py", "src/cbus_toolkit/wireless_cli.py"],
        "documentation": "docs/wireless.md",
        "receipts": [
            "research/fixtures/wireless-source-review.json",
            "research/fixtures/wireless-unit-globals-native-acceptance.json",
        ],
        "control_receipt": {"path": "research/fixtures/wireless-source-review.json", "section": "unit_globals"},
        "unit_types_from": ("wireless_unit_globals", "research/fixtures/wireless-source-review.json"),
    },
    {
        "id": "multisensor-settings",
        "ledger_id": "sensors-wizard-semantics",
        "modules": ["src/cbus_toolkit/sensors.py"],
        "documentation": "docs/sensors.md",
        "receipts": ["docs/sensor-profile-review.json", "docs/sensor-acceptance-summary.json"],
        "control_receipt": None,
        "unit_types_from": ("literal", ("SENPILL",)),
    },
    {
        "id": "pir-sensor-settings",
        "ledger_id": "sensors-wizard-semantics",
        "modules": ["src/cbus_toolkit/pir_sensors.py"],
        "documentation": "docs/sensors.md",
        "receipts": ["docs/pir-sensor-review.json", "docs/pir-sensor-acceptance-summary.json"],
        "control_receipt": None,
        "unit_types_from": ("literal", ("SENPIROA", "SENPIRIA", "SENPIRIB")),
    },
    {
        "id": "thermostat-settings",
        "ledger_id": "thermostat-configuration",
        "modules": ["src/cbus_toolkit/thermostat_settings.py", "src/cbus_toolkit/thermostat_settings_guard.py"],
        "documentation": "docs/thermostat-settings.md",
        "receipts": ["research/experiments/2026-09-30/thermostat-settings-native-acceptance.json"],
        "control_receipt": None,
        "unit_types_from": ("literal", ("PC_TSA", "PC_TSA5", "PC_TSB", "PC_TSB5")),
    },
    {
        "id": "classic-key-presets",
        "ledger_id": "classic-key-presets",
        "modules": ["src/cbus_toolkit/macros.py", "src/cbus_toolkit/key_options_cli.py"],
        "documentation": "docs/macros.md",
        "receipts": [
            "research/fixtures/key-preset-family-equivalence.json",
            "docs/classic-key-family-acceptance-summary.json",
        ],
        "control_receipt": None,
        "unit_types_from": ("key_preset_family", "classic-key-presets"),
    },
    {
        "id": "neo-key-presets-and-indicators",
        "ledger_id": "neo-core-key-presets",
        "modules": [
            "src/cbus_toolkit/extended_macros.py",
            "src/cbus_toolkit/neo_indicators.py",
            "src/cbus_toolkit/key_options_cli.py",
        ],
        "documentation": "docs/extended-macros.md",
        "receipts": [
            "research/fixtures/key-preset-family-equivalence.json",
            "docs/extended-macros-acceptance-summary.json",
        ],
        "control_receipt": None,
        "unit_types_from": ("key_preset_family", "neo-core-key-presets"),
    },
    {
        "id": "edlt",
        "ledger_id": "dlt-edlt-widgets-and-labels",
        "modules": ["src/cbus_toolkit/edlt.py", "src/cbus_toolkit/edlt_parent_form.py"],
        "documentation": "docs/edlt.md",
        "receipts": ["research/fixtures/edlt-parent-form-evidence.json", "docs/edlt-remaining-controls.md"],
        "control_receipt": None,
        "unit_types_from": ("literal", ("KEYGL5",)),
    },
)

# Form controls that hold a value (not layout, labels, buttons or actions).
EDITABLE_CONTROL_RE = re.compile(
    r"(CheckBox|ComboBox|Combo|Edit|TrackBar|RadioGroup|RadioButton|ApplicationSwitcher|ListBox|Memo)$"
)
CONTROL_TOKEN_RE = re.compile(r"[a-z]{2,4}[A-Z][A-Za-z0-9]*(?:\.\.[A-Za-z0-9]+)?(?:/[A-Za-z0-9]+)*")


def _editor_unit_types(editor: dict) -> list[str]:
    kind, value = editor["unit_types_from"]
    if kind == "literal":
        return sorted(value)
    if kind == "key_preset_family":
        return sorted(_admitted_key_preset_types().get(value, set()))
    receipt = load_json(ROOT / value)
    if kind == "receipt_profiles":
        return sorted(
            row["unit_type"] for row in receipt["profiles"] if row.get("admitted", True)
        )
    if kind == "wireless_unit_globals":
        return sorted(receipt["unit_globals"]["profiles"]["unit_types"])
    raise ValueError(f"Unknown editor unit-type source: {kind}")


def _control_patterns(text: str) -> list[re.Pattern]:
    """Regexes for the component names one receipt ``control`` string names.

    ``chkLA1..chkLA4`` and ``cmbGlobal1..4RecallLevel`` are ranges,
    ``cmbRampRateGlobal1/2/3`` lists digit alternatives, and an ``N`` or ``K``
    between a lower- and an upper-case letter stands for an index.
    """
    patterns: list[re.Pattern] = []
    for token in CONTROL_TOKEN_RE.findall(text):
        names: list[str] = []
        if ".." in token:
            left, right = token.split("..", 1)
            prefix = re.match(r"(.*?)(\d+)$", left)
            if not prefix:
                continue
            end = re.match(r"(?:" + re.escape(prefix[1]) + r")?(\d+)(.*)$", right)
            if not end:
                continue
            names += [f"{prefix[1]}{index}{end[2]}" for index in range(int(prefix[2]), int(end[1]) + 1)]
        else:
            first, *alternatives = token.split("/")
            names.append(first)
            stem = re.match(r"(.*?)(\d+)$", first)
            for alternative in alternatives:
                if stem and alternative.isdigit():
                    names.append(f"{stem[1]}{alternative}")
                elif re.fullmatch(CONTROL_TOKEN_RE, alternative):
                    names.append(alternative)
        for name in names:
            parts = re.split(r"(?<=[a-z])[NK](?=[A-Z])", name)
            patterns.append(re.compile(r"\d+".join(re.escape(part) for part in parts)))
    return patterns


def _embedded_resources(root_names: list[str], executable: dict) -> list[str]:
    """Form resources plus every frame/sub-form their DFM components embed."""
    by_name = {row["resource_name"]: row for row in executable["resources"]}
    by_class = {row["root_class"]: row["resource_name"] for row in executable["resources"]}
    seen: list[str] = []
    pending = [name for name in root_names if name in by_name]
    while pending:
        name = pending.pop(0)
        if name in seen:
            continue
        seen.append(name)
        for component in by_name[name]["components"][1:]:
            nested = by_class.get(component["class"])
            if nested and nested not in seen:
                pending.append(nested)
    return sorted(seen)


def _receipt_form_resources(editors: list[dict], executable: dict) -> list[str]:
    """Form resources a control receipt pins by digest; a stale digest raises."""
    by_name = {item["resource_name"]: item for item in executable["resources"]}
    names: list[str] = []
    for editor in editors:
        if editor["control_receipt"] is None:
            continue
        receipt = load_json(ROOT / editor["control_receipt"]["path"])
        pinned = receipt["inputs"].get("form_resource_sha256", {})
        section = editor["control_receipt"]["section"]
        # A sectioned receipt names the forms of each section separately.
        wanted = sorted(receipt[section].get("forms", pinned)) if section else sorted(pinned)
        for name in wanted:
            value = pinned.get(name)
            if name not in by_name or by_name[name]["resource_sha256"] != value:
                raise ValueError(f"{editor['control_receipt']['path']} pins a stale form resource {name}")
            names.append(name)
    return names


def _control_coverage(row: dict, editors: list[dict], executable: dict) -> dict[str, Any]:
    by_name = {item["resource_name"]: item for item in executable["resources"]}
    resources = _embedded_resources(
        row["form_resources"] + row["frame_resources"] + _receipt_form_resources(editors, executable),
        executable,
    )
    controls = [
        (name, component["name"], component["class"])
        for name in resources
        for component in by_name[name]["components"][1:]
        if EDITABLE_CONTROL_RE.search(component["class"])
    ]
    mapped: dict[tuple[str, str], dict] = {}
    receipt_rows = 0
    for editor in editors:
        spec = editor["control_receipt"]
        if spec is None:
            continue
        receipt = load_json(ROOT / spec["path"])
        section = receipt[spec["section"]] if spec["section"] else receipt
        for entry in section["controls"]:
            receipt_rows += 1
            form = entry.get("form")
            parameter = entry.get("parameter") or entry.get("binding") or ", ".join(entry.get("parameters", []))
            for pattern in _control_patterns(entry["control"]):
                for resource, name, _ in controls:
                    if form and by_name[resource]["root_class"] != form:
                        continue
                    if pattern.fullmatch(name):
                        mapped.setdefault((resource, name), {
                            "resource": resource,
                            "control": name,
                            "parameter": parameter,
                            "receipt": spec["path"],
                        })
    result = {
        "resources": resources,
        "controls_total": len(controls),
        "controls_mapped": len(mapped),
        "receipt_control_rows": receipt_rows,
        "mapped_controls": [mapped[key] for key in sorted(mapped)],
        "basis": (
            "control_receipt" if any(editor["control_receipt"] for editor in editors)
            else "no_control_level_receipt"
        ),
    }
    if not controls:
        result["denominator_note"] = (
            "The bound form resources carry no editable controls; the dialog's pages are "
            "created at run time by classes this static map does not bind to resources."
        )
    return result


def _link_editors(rows: list[dict], executable: dict) -> None:
    admitted = {editor["id"]: set(_editor_unit_types(editor)) for editor in IMPLEMENTED_EDITORS}
    named_dialogs = {
        editor["id"]: set(load_json(ROOT / editor["dialog_ids_from"][0])[editor["dialog_ids_from"][1]]["dialog_ids"])
        if "dialog_ids_from" in editor else set()
        for editor in IMPLEMENTED_EDITORS
    }
    for row in rows:
        scoped = {
            unit["unit_type"] for unit in row["unit_types"]
            if unit["known"] and unit.get("firmware_hint_matches", True)
        }
        editors = [
            editor for editor in IMPLEMENTED_EDITORS
            if scoped & admitted[editor["id"]] or row["dialog_id"] in named_dialogs[editor["id"]]
        ]
        if not editors:
            continue
        row["implemented_editors"] = [
            {
                "id": editor["id"],
                "ledger_id": editor["ledger_id"],
                "unit_types": sorted(scoped & admitted[editor["id"]]),
                "link_basis": (
                    "admitted_unit_type" if scoped & admitted[editor["id"]] else "receipt_names_dialog"
                ),
                "modules": editor["modules"],
                "documentation": editor["documentation"],
                "receipts": editor["receipts"],
                "control_receipt": editor["control_receipt"]["path"] if editor["control_receipt"] else None,
            }
            for editor in editors
        ]
        row["control_coverage"] = _control_coverage(row, editors, executable)


def check_editor_paths() -> None:
    """Every linked editor module, document and receipt must exist.

    Only the receipts that feed the derivation (unit-type rosters, control
    rows and pinned form digests) change the map; a deterministic rebuild
    detects those.  Module and prose edits do not stale the map.
    """
    paths = sorted({
        path for editor in IMPLEMENTED_EDITORS
        for path in editor["modules"] + [editor["documentation"]] + editor["receipts"]
    })
    missing = [path for path in paths if not (ROOT / path).is_file()]
    if missing:
        raise ValueError(f"Implemented-editor inputs are missing: {missing}")


def assemble_dialogs(surface: dict, executable: dict, ledger: dict, facts: dict,
                     triage: dict[str, str]) -> list[dict]:
    """Deterministically derive every dialog row from committed inputs and facts."""
    topics = {topic["id"]: topic for topic in surface["topics"]}
    neighbours = _browse_neighbours(surface)
    reference_by_file = {
        topics[topic_id]["file"]: (topic_id, topics[topic_id]["title"])
        for topic_id in surface["unit_type_reference_entries"]
    }
    # Product unit types: catalogued or registered with the static unit factory.
    # Include-only specification types (for example shared base specs) are not.
    unit_types = {
        name: entry for name, entry in facts["unit_types"].items()
        if entry["catalogue_numbers"] or entry["factory_registrations"]
    }
    known_types = set(unit_types)
    catalogue_index = _catalogue_index(unit_types)
    resource_by_class = {
        row["root_class"]: row["resource_name"] for row in executable["resources"]
    }
    features = {feature["id"]: feature for feature in ledger["features"]}
    admitted_presets = _admitted_key_preset_types()
    for ledger_id, exact in LEDGER_EXACT_UNIT_TYPES.items():
        limits = features.get(ledger_id, {}).get("limits") or ""
        for unit_type in exact:
            # The key-preset rows summarize their admitted families in prose;
            # their exact roster lives in the committed family receipt.
            if unit_type in admitted_presets.get(ledger_id, set()):
                continue
            if not re.search(rf"(?<![A-Z0-9]){re.escape(unit_type)}(?![A-Z0-9])", limits):
                raise ValueError(f"Ledger {ledger_id} limits no longer name {unit_type}")

    dialog_factory = facts["unit_dialog_factory"]
    fallback_director = dialog_factory["director_fallback"]["director"]
    # TUnitDialogFactory.GetUnitDialog compares type names case-insensitively.
    unit_dialogs = {
        row["unit_type"].upper(): row["form_class"] for row in dialog_factory["registrations"]
    }
    help_link_types = _help_link_types(facts["help_links"], unit_types)

    def node_directors_of(unit_type: str) -> list[str]:
        return sorted({
            director
            for manager in unit_types.get(unit_type, {}).get("node_managers", [])
            for director in facts["node_managers"][manager]["directors"]
        })

    def dispatch_of(unit_type: str) -> tuple[str, list[str], str | None]:
        """How EditUnit reaches the unit's editor: (path, directors, unit-dialog form)."""
        directors = node_directors_of(unit_type)
        if directors:
            return "node_manager_director", directors, None
        form = unit_dialogs.get(unit_type.upper())
        if form:
            return "common_director_unit_dialog", [fallback_director], form
        if unit_types.get(unit_type, {}).get("node_managers"):
            return "node_manager_without_director", [], None
        return "no_node_manager", [], None

    def editor_keys(unit_type: str) -> set[str]:
        # The shared fallback director says nothing about the editor; the
        # registered unit-dialog form does.
        path, directors, form = dispatch_of(unit_type)
        return {f"form:{form}"} if form else set(directors)

    ledger_editors = {
        ledger_id: sorted({key for unit_type in exact for key in editor_keys(unit_type)})
        for ledger_id, exact in LEDGER_EXACT_UNIT_TYPES.items()
    }

    rows = []
    for dialog in surface["device_dialog_candidates"]:
        reasons: list[str] = []
        subjects: dict[str, list[str]] = defaultdict(list)
        help_result = _help_evidence(
            dialog, topics, reference_by_file, neighbours, catalogue_index, known_types,
            help_link_types,
        )
        if help_result["reason"]:
            reasons.append(help_result["reason"])
        hint_match = FIRMWARE_HINT_RE.search(" ".join([dialog["title"], dialog["device_path"][-1]]))
        hint = hint_match[1] if hint_match else None
        mapped = []
        for unit_type in help_result["selected"]:
            entry = unit_types.get(unit_type)
            if entry is None:
                absent = facts["help_only_unit_types"].get(unit_type)
                code = (
                    "help_unit_type_absent_from_executable"
                    if absent is not None and not any(absent.values())
                    else "unknown_unit_type"
                )
                mapped.append({"unit_type": unit_type, "known": False})
                if code not in reasons:
                    reasons.append(code)
                subjects[code].append(unit_type)
                continue
            path, directors, form = dispatch_of(unit_type)
            row = {
                "unit_type": unit_type,
                "known": True,
                "node_managers": entry["node_managers"],
                "dispatch": path,
                "directors": directors,
            }
            if form:
                row["unit_dialog_form"] = form
            if hint is not None:
                row["firmware_hint_matches"] = any(
                    _contains(hint, low, high) for low, high in _ranges_for(entry)
                )
            mapped.append(row)
        if hint is not None and mapped and not any(row.get("firmware_hint_matches") for row in mapped):
            reasons.append("firmware_hint_unmatched")
        in_scope = [
            row for row in mapped
            if row["known"] and (hint is None or row["firmware_hint_matches"])
        ]

        directors = sorted({director for row in in_scope for director in row["directors"]})
        node_directors = sorted({
            director for row in in_scope if row["dispatch"] == "node_manager_director"
            for director in row["directors"]
        })
        registered_forms = sorted({row["unit_dialog_form"] for row in in_scope if "unit_dialog_form" in row})
        dialog_forms = sorted({
            form for director in node_directors
            for form in facts["directors"][director]["dialog_forms"]
        } | set(registered_forms))
        frames = sorted({
            frame for director in node_directors for frame in facts["directors"][director]["frames"]
        } | {
            frame for form in registered_forms for frame in dialog_factory["forms"][form]["frames"]
        })
        form_resources = sorted(
            resource_by_class[form] for form in dialog_forms if form in resource_by_class
        )
        frame_resources = sorted(
            resource_by_class[frame] for frame in frames if frame in resource_by_class
        )
        if in_scope:
            for code, path in (
                ("no_static_node_manager", "no_node_manager"),
                ("no_director", "node_manager_without_director"),
            ):
                subjects[code] = [row["unit_type"] for row in in_scope if row["dispatch"] == path]
            if subjects["no_static_node_manager"]:
                reasons.append("no_static_node_manager")
            elif subjects["no_director"]:
                reasons.append("no_director")
            elif not form_resources or len(form_resources) != len(dialog_forms):
                reasons.append("no_dialog_form")

        scoped_types = {row["unit_type"] for row in in_scope}
        ledger_ids = sorted(
            ledger_id for ledger_id, exact in LEDGER_EXACT_UNIT_TYPES.items()
            if scoped_types & set(exact)
        )
        basis = "ledger_limits_name_unit_type"
        if not ledger_ids:
            scoped_editors = {key for unit_type in scoped_types for key in editor_keys(unit_type)}
            ledger_ids = sorted(
                ledger_id for ledger_id, shared in ledger_editors.items()
                if scoped_editors & set(shared)
            )
            basis = "shares_dialog_director_with_ledger_unit_type"
        triage_id = triage[dialog["id"]]
        if not ledger_ids:
            ledger_ids, basis = [triage_id], "help_branch_triage"
        if set(ledger_ids) & GENERIC_LEDGER_IDS:
            basis = "generic"
            reasons.append("generic_ledger_only")
            subjects["generic_ledger_only"] = sorted(scoped_types)

        rows.append({
            "dialog_id": dialog["id"],
            "topic_id": dialog["topic_id"],
            "help_topic_ids": list(dialog["descendant_topic_ids"]),
            "firmware_hint": hint,
            "help_unit_type_evidence": help_result["evidence"],
            "unit_type_selection": help_result["selection_rule"],
            "unit_types": mapped,
            "other_help_unit_type_candidates": help_result["other_candidates"],
            "directors": directors,
            "dialog_form_classes": dialog_forms,
            "form_resources": form_resources,
            "frame_resources": frame_resources,
            "ledger_ids": ledger_ids,
            "ledger_basis": basis,
            "triage_ledger_id": triage_id,
            "status": "unresolved" if reasons else "resolved",
            "unresolved_reasons": [
                {"code": code, "detail": UNRESOLVED[code], "subjects": subjects.get(code, [])}
                for code in reasons
            ],
        })
    return rows


def _triage() -> dict[str, str]:
    sys.path.insert(0, str(ROOT / "src"))
    from cbus_toolkit.device_dialogs import list_dialogs

    return {row["dialog_id"]: row["ledger_id"] for row in list_dialogs()}


def committed_inputs() -> dict[str, dict]:
    return {
        "toolkit_surface": {"path": "docs/toolkit-surface.json", "sha256": digest(SURFACE_PATH)},
        "toolkit_executable_surface": {
            "path": "docs/toolkit-executable-surface.json",
            "sha256": digest(EXECUTABLE_SURFACE_PATH),
        },
    }


def build_document(facts: dict) -> dict:
    surface = load_json(SURFACE_PATH)
    executable = load_json(EXECUTABLE_SURFACE_PATH)
    ledger = load_json(LEDGER_PATH)
    dialogs = assemble_dialogs(surface, executable, ledger, facts, _triage())
    check_editor_paths()
    _link_editors(dialogs, executable)
    counts = {
        "dialogs": len(dialogs),
        "resolved": sum(row["status"] == "resolved" for row in dialogs),
        "unresolved": sum(row["status"] == "unresolved" for row in dialogs),
        "specific_ledger": sum(row["ledger_basis"] != "generic" for row in dialogs),
        "with_form_resources": sum(bool(row["form_resources"]) for row in dialogs),
        "with_unit_types": sum(bool(row["unit_types"]) for row in dialogs),
    }
    reason_counts: dict[str, int] = defaultdict(int)
    for row in dialogs:
        for reason in row["unresolved_reasons"]:
            reason_counts[reason["code"]] += 1
    counts["unresolved_reasons"] = dict(sorted(reason_counts.items()))
    # Catalogued product types that no help dialog candidate reaches are
    # candidate implicit editor branches for the census (P0.01).
    catalogued = sorted(
        name for name, entry in facts["unit_types"].items() if entry["catalogue_numbers"]
    )
    reached = {
        row["unit_type"] for dialog in dialogs for row in dialog["unit_types"] if row["known"]
    }
    counts["catalogued_unit_types"] = len(catalogued)
    counts["catalogued_unit_types_reached_by_dialogs"] = len(set(catalogued) & reached)
    selection_counts: dict[str, int] = defaultdict(int)
    for row in dialogs:
        selection_counts[row["unit_type_selection"]] += 1
    counts["unit_type_selection"] = dict(sorted(selection_counts.items()))
    counts["dispatch"] = dict(sorted(
        (path, sum(
            any(unit.get("dispatch") == path for unit in row["unit_types"]) for row in dialogs
        ))
        for path in sorted({
            unit["dispatch"] for row in dialogs for unit in row["unit_types"] if "dispatch" in unit
        })
    ))
    coverage_rows = [
        {
            "dialog_id": row["dialog_id"],
            "editors": [editor["id"] for editor in row["implemented_editors"]],
            "controls_mapped": row["control_coverage"]["controls_mapped"],
            "controls_total": row["control_coverage"]["controls_total"],
            "basis": row["control_coverage"]["basis"],
        }
        for row in dialogs if "implemented_editors" in row
    ]
    counts["dialogs_with_implemented_editors"] = len(coverage_rows)
    counts["dialogs_with_control_receipts"] = sum(
        row["basis"] == "control_receipt" for row in coverage_rows
    )
    counts["controls_mapped"] = sum(row["controls_mapped"] for row in coverage_rows)
    counts["controls_in_editor_dialogs"] = sum(row["controls_total"] for row in coverage_rows)
    return {
        "schema_version": SCHEMA_VERSION,
        "format": FORMAT,
        "target": "C-Bus Toolkit 1.18.0.2754",
        "purpose": (
            "Deterministic map from each help device-dialog candidate to exact unit types, "
            "catalogue/firmware ranges, statically registered unit classes and node managers, "
            "dialog-director or unit-dialog-factory forms, executable help links and the most "
            "specific feature-ledger row; for dialogs with implemented CLI editors, the editor "
            "modules and the controls their committed static source reviews bind to unit "
            "parameters. Identification only: a mapped control is not original-differential, "
            "GUI or physical acceptance."
        ),
        "inputs": {**committed_inputs(), **facts["inputs"]},
        "ledger_exact_unit_types": {key: list(value) for key, value in LEDGER_EXACT_UNIT_TYPES.items()},
        "unresolved_reason_codes": dict(UNRESOLVED),
        "unit_factory": facts["unit_factory"],
        "unit_types": facts["unit_types"],
        "node_managers": facts["node_managers"],
        "directors": facts["directors"],
        "unit_dialog_factory": facts["unit_dialog_factory"],
        "help_links": facts["help_links"],
        "help_only_unit_types": facts["help_only_unit_types"],
        "editable_control_class_rule": EDITABLE_CONTROL_RE.pattern,
        "counts": counts,
        "control_coverage_table": coverage_rows,
        "catalogued_unit_types_without_dialog": [name for name in catalogued if name not in reached],
        "dialogs": dialogs,
    }


FACT_KEYS = (
    "inputs", "unit_factory", "unit_types", "node_managers", "directors",
    "unit_dialog_factory", "help_links", "help_only_unit_types",
)
VENDOR_INPUTS = ("toolkit_executable", "toolkit_map", "unit_catalogue", "unitspec_directory")


def validate_document(document: dict) -> dict:
    """Check a map against the committed inputs and rebuild its dialog rows.

    Raises ``ValueError`` on stale or tampered input digests, on a changed
    dialog roster, on a resolved row that lacks a facet, on an unresolved row
    without a reason, or when the dialogs differ from a fresh assembly.
    """
    if document.get("schema_version") != SCHEMA_VERSION or document.get("format") != FORMAT:
        raise ValueError("Dialog map schema changed")
    inputs = document.get("inputs")
    if not isinstance(inputs, dict):
        raise ValueError("Dialog map requires inputs")
    for name, expected in committed_inputs().items():
        if inputs.get(name) != expected:
            raise ValueError(f"Dialog map input changed: {name}")
    executable = load_json(EXECUTABLE_SURFACE_PATH)
    surface = load_json(SURFACE_PATH)
    if inputs.get("toolkit_executable", {}).get("sha256") != executable["sources"]["executable"]["sha256"]:
        raise ValueError("Dialog map input changed: toolkit_executable")
    if inputs.get("toolkit_map", {}).get("sha256") != executable["sources"]["map"]["sha256"]:
        raise ValueError("Dialog map input changed: toolkit_map")
    catalogue = [row["sha256"] for row in surface["source_artifacts"] if row["path"] == CATALOGUE_SOURCE]
    if [inputs.get("unit_catalogue", {}).get("sha256")] != catalogue:
        raise ValueError("Dialog map input changed: unit_catalogue")
    spec = inputs.get("unitspec_directory", {})
    if not isinstance(spec.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", spec["sha256"]):
        raise ValueError("Dialog map input changed: unitspec_directory")
    if set(inputs) != set(committed_inputs()) | set(VENDOR_INPUTS):
        raise ValueError("Dialog map inputs are incomplete or unexpected")
    dialogs = document.get("dialogs")
    if not isinstance(dialogs, list) or len(dialogs) != EXPECTED_DIALOGS:
        raise ValueError(f"Dialog map must contain exactly {EXPECTED_DIALOGS} dialogs")
    expected_ids = [row["id"] for row in surface["device_dialog_candidates"]]
    if [row.get("dialog_id") for row in dialogs] != expected_ids:
        raise ValueError("Dialog map roster differs from the help census")
    for row in dialogs:
        reasons = row.get("unresolved_reasons")
        if row.get("status") == "resolved":
            if reasons or not row.get("unit_types") or not row.get("form_resources") or row.get("ledger_basis") == "generic":
                raise ValueError(f"{row['dialog_id']} claims resolution without every facet")
        elif row.get("status") == "unresolved":
            if not reasons or any(
                not isinstance(reason, dict) or reason.get("code") not in UNRESOLVED
                or reason.get("detail") != UNRESOLVED[reason["code"]]
                or set(reason) != {"code", "detail", "subjects"}
                for reason in reasons
            ):
                raise ValueError(f"{row['dialog_id']} is unresolved without an explicit reason")
        else:
            raise ValueError(f"{row['dialog_id']} has an unknown status")
    facts = {key: document.get(key) for key in FACT_KEYS}
    facts["inputs"] = {key: inputs[key] for key in VENDOR_INPUTS}
    rebuilt = build_document(facts)
    if render(rebuilt) != render(document):
        raise ValueError("Dialog map differs from a deterministic rebuild of its facts")
    return document


def load_committed(path: Path = OUTPUT_PATH) -> dict:
    return validate_document(load_json(path))


def refresh_from_committed_facts(path: Path = OUTPUT_PATH) -> dict:
    """Re-derive the map from its recorded vendor facts, without vendor files.

    Use after an offline input (help census, executable surface roster or
    device-dialog triage) changes.  A changed original executable, MAP,
    catalogue or specification directory still requires ``--check`` with the
    vendor inputs, because the recorded facts are bound to their digests.
    """
    document = load_json(path)
    facts = {key: document[key] for key in FACT_KEYS}
    facts["inputs"] = {key: document["inputs"][key] for key in VENDOR_INPUTS}
    return validate_document(build_document(facts))


def default_catalog() -> Path | None:
    """The catalogue named by CBUS_CATALOG_PATH, else the local C-Gate vendor copy."""
    if os.environ.get("CBUS_CATALOG_PATH"):
        return Path(os.environ["CBUS_CATALOG_PATH"])
    if os.environ.get("CBUS_LOCAL_CGATE_VENDOR"):
        return Path(os.environ["CBUS_LOCAL_CGATE_VENDOR"]) / "unitspec" / "cbusunits.xml"
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--exe", type=Path, default=os.environ.get("CBUS_TOOLKIT_EXE"))
    parser.add_argument("--map", dest="map_path", type=Path)
    parser.add_argument("--catalog", type=Path)
    parser.add_argument("--spec-dir", type=Path, default=os.environ.get("CBUS_UNITSPEC_DIR"))
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--check", action="store_true", help="regenerate from vendor inputs and compare")
    parser.add_argument("--validate", action="store_true", help="validate the committed map without vendor inputs")
    parser.add_argument("--refresh", action="store_true", help="re-derive dialog rows from the committed vendor facts")
    args = parser.parse_args()
    if args.validate:
        document = load_committed(args.output)
        print(json.dumps({"status": "valid", **document["counts"]}, indent=2, sort_keys=True))
        return
    if args.refresh:
        document = refresh_from_committed_facts(args.output)
        args.output.write_text(render(document), encoding="utf-8")
        print(json.dumps({"status": "refreshed", **document["counts"]}, indent=2, sort_keys=True))
        return
    catalog = args.catalog or default_catalog()
    if args.exe is None or catalog is None or args.spec_dir is None:
        parser.error(
            "--exe (CBUS_TOOLKIT_EXE), --catalog (CBUS_CATALOG_PATH or CBUS_LOCAL_CGATE_VENDOR) "
            "and --spec-dir (CBUS_UNITSPEC_DIR) are required"
        )
    map_path = args.map_path or Path(args.exe).with_suffix(".map")
    facts = extract_vendor_facts(Path(args.exe), map_path, catalog, Path(args.spec_dir))
    document = validate_document(build_document(facts))
    content = render(document)
    if args.check:
        if not args.output.is_file() or args.output.read_text(encoding="utf-8") != content:
            raise SystemExit(f"stale dialog map: {args.output}")
    else:
        args.output.write_text(content, encoding="utf-8")
    print(json.dumps({"status": "current" if args.check else "generated", **document["counts"]}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
