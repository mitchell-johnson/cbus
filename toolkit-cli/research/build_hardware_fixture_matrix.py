#!/usr/bin/env python3
"""Generate the sanitized P1.04 hardware fixture matrix.

Each row names one physical fixture that a required acceptance case needs:
a device type derived from a decoded unit specification and the C-Gate
catalogue, or an explicit interface, topology, gateway, display, USB or rig
assembly. The committed matrix contains identifiers, catalogue metadata and
input SHA-256 digests only; it never copies specification content.

No fixture is provisioned today. A row can become ``provisioned`` only with a
reference to a private provisioning manifest entry, which stays outside the
repository. Unavailable fixtures keep the dependent physical acceptance
dimensions ``blocked`` in the parity register; they are never not-applicable.

Regeneration needs the private decoded specifications (``CBUS_UNITSPEC_DIR``)
and the original catalogue (``CBUS_LOCAL_CGATE_VENDOR``/unitspec/cbusunits.xml).
``--check`` regenerates from those inputs and fails when they are absent.
``--verify`` checks the committed matrix without vendor inputs.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = ROOT.parent
MATRIX_PATH = ROOT / "research" / "hardware-fixture-matrix.json"
LEDGER_PATH = ROOT / "src" / "cbus_toolkit" / "capabilities.json"
ROADMAP_PATH = REPOSITORY / "docs" / "parity-review-and-roadmap.md"
FORMAT = "cbus-hardware-fixture-matrix-v1"
FIXTURE_ID_RE = re.compile(r"fixture:[a-z0-9-]+:[A-Za-z0-9_.-]+\Z")
PRIVATE_MANIFEST_RE = re.compile(r"private-manifest:sha256:[0-9a-f]{64}\Z")
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
STATUSES = ("unavailable", "provisioned")
KINDS = ("unit_type", "assembly", "programming_class")
OBSERVABLES = (
    "identity",
    "readback",
    "power_cycle_persistence",
    "electrical",
    "output_effect",
    "input_event",
    "rendering",
    "routing",
    "interface_link",
    "wireless_link",
    "ballast_response",
    "usb_enumeration",
    "firmware_transfer",
)
SPEC_ROLES = (
    "catalogued_device",
    "uncatalogued_device_variant",
    "include_only",
    "base_include",
    "template",
    "non_unit_specification",
)
FIXTURE_SPEC_ROLES = {"catalogued_device", "uncatalogued_device_variant"}
UNIT_FAMILIES = (
    "analogue_output",
    "bridge",
    "clock",
    "dali_gateway",
    "dimmer",
    "dlt_display",
    "edlt_display",
    "gateway",
    "key_input",
    "media",
    "miscellaneous",
    "pc_interface",
    "power_supply",
    "relay",
    "sensor",
    "support_general",
    "telephone_interface",
    "thermostat",
    "third_party",
    "touchscreen",
    "wireless_device",
    "wireless_gateway",
)
# Explicit assemblies required independently of the per-type rows.
REQUIRED_ASSEMBLY_FAMILIES = (
    "interface",
    "bridge_topology",
    "wireless_gateway",
    "dali_gateway",
    "dali_ballast",
    "usb_bootloader",
    "edlt_display",
    "dlt_display",
    "power_cycle_rig",
    "electrical_rig",
    "reference_network",
)
FAMILIES = tuple(
    sorted(set(UNIT_FAMILIES) | set(REQUIRED_ASSEMBLY_FAMILIES) | {"programming_method"})
)

UNIT_OBSERVABLES = ("identity", "readback", "power_cycle_persistence")
FAMILY_OBSERVABLES = {
    "analogue_output": ("output_effect", "electrical"),
    "bridge": ("routing",),
    "clock": ("input_event",),
    "dali_gateway": ("ballast_response",),
    "dimmer": ("output_effect", "electrical"),
    "dlt_display": ("rendering", "input_event"),
    "edlt_display": ("rendering", "input_event"),
    "key_input": ("input_event",),
    "media": ("output_effect",),
    "pc_interface": ("interface_link",),
    "power_supply": ("electrical",),
    "relay": ("output_effect", "electrical"),
    "sensor": ("input_event",),
    "thermostat": ("output_effect", "input_event"),
    "touchscreen": ("rendering", "input_event"),
    "wireless_device": ("wireless_link", "output_effect"),
    "wireless_gateway": ("wireless_link", "routing"),
}
UNIT_WORK_ITEMS = ("P1.04", "P4.04", "P11.01")
FAMILY_WORK_ITEMS = {
    "analogue_output": ("P5.03",),
    "bridge": ("P3.01",),
    "dali_gateway": ("P7.01",),
    "dimmer": ("P5.03",),
    "dlt_display": ("P6.01", "P6.03", "P6.06"),
    "edlt_display": ("P6.01", "P6.06"),
    "gateway": ("P7.03",),
    "key_input": ("P5.02",),
    "media": ("P7.03",),
    "pc_interface": ("P3.02",),
    "relay": ("P5.03",),
    "sensor": ("P5.04",),
    "thermostat": ("P5.05",),
    "touchscreen": ("P6.01",),
    "wireless_device": ("P5.07",),
    "wireless_gateway": ("P5.07",),
}

ASSEMBLIES: tuple[dict[str, Any], ...] = (
    {
        "id": "fixture:interface:cni-ethernet",
        "family": "interface",
        "description": "C-Bus Network Interface reached over TCP on an isolated test LAN",
        "required_observables": ["identity", "interface_link", "power_cycle_persistence"],
        "work_items": ["P1.04", "P3.02"],
    },
    {
        "id": "fixture:interface:pci-serial",
        "family": "interface",
        "description": "RS-232 PC Interface on a dedicated serial port",
        "required_observables": ["identity", "interface_link", "power_cycle_persistence"],
        "work_items": ["P1.04", "P3.02"],
    },
    {
        "id": "fixture:interface:pci-usb",
        "family": "interface",
        "description": "USB PC Interface enumerated as a serial device",
        "required_observables": ["identity", "interface_link", "usb_enumeration"],
        "work_items": ["P1.04", "P3.02"],
    },
    *(
        {
            "id": f"fixture:topology:bridges-{depth}",
            "family": "bridge_topology",
            "description": (
                f"Target network reached through {depth} cascaded bridge"
                f"{'s' if depth > 1 else ''} from the interface network, with a "
                "responding unit on the far network"
            ),
            "bridge_count": depth,
            "required_observables": ["routing", "identity", "readback"],
            "work_items": ["P1.04", "P3.01", "P3.03"],
        }
        for depth in range(1, 7)
    ),
    {
        "id": "fixture:gateway:wireless",
        "family": "wireless_gateway",
        "description": "Wireless gateway bound to a wired network with joined wireless units",
        "required_observables": ["wireless_link", "routing", "readback", "power_cycle_persistence"],
        "work_items": ["P1.04", "P5.07"],
    },
    {
        "id": "fixture:dali:gateway",
        "family": "dali_gateway",
        "description": "DALI gateway on a C-Bus network with an attached DALI line",
        "required_observables": ["identity", "readback", "ballast_response", "power_cycle_persistence"],
        "work_items": ["P1.04", "P7.01"],
    },
    {
        "id": "fixture:dali:ballast-set",
        "family": "dali_ballast",
        "description": "Addressed and unaddressed DALI ballasts, including a faulty-lamp case",
        "required_observables": ["ballast_response", "electrical", "output_effect"],
        "work_items": ["P1.04", "P7.01"],
    },
    {
        "id": "fixture:usb:edlt-dfu-bootloader",
        "family": "usb_bootloader",
        "description": "eDLT unit that can enter its USB DFU bootloader on an owned host",
        "required_observables": ["usb_enumeration", "firmware_transfer", "identity", "power_cycle_persistence"],
        "work_items": ["P1.04", "P10.02", "P10.03"],
    },
    {
        "id": "fixture:display:edlt",
        "family": "edlt_display",
        "description": "Powered eDLT (KEYGL5) display on a C-Bus network with observable screen",
        "required_observables": ["rendering", "readback", "input_event", "power_cycle_persistence"],
        "work_items": ["P1.04", "P6.01", "P6.06"],
    },
    {
        "id": "fixture:display:dlt",
        "family": "dlt_display",
        "description": "Legacy Saturn/Neo/Decorator DLT display with observable labels",
        "required_observables": ["rendering", "readback", "input_event", "power_cycle_persistence"],
        "work_items": ["P1.04", "P6.03", "P6.06"],
    },
    {
        "id": "fixture:rig:power-cycle-network",
        "family": "power_cycle_rig",
        "description": "Switched C-Bus power supply that removes and restores network power under test control",
        "required_observables": ["power_cycle_persistence", "readback"],
        "work_items": ["P1.04", "P4.04", "P6.06"],
    },
    {
        "id": "fixture:rig:power-cycle-interface",
        "family": "power_cycle_rig",
        "description": "Controlled disconnect and power removal of the PC interface during a programming session",
        "required_observables": ["power_cycle_persistence", "interface_link"],
        "work_items": ["P1.04", "P4.03", "P4.04"],
    },
    {
        "id": "fixture:rig:electrical",
        "family": "electrical_rig",
        "description": "Instrumented network for burden, voltage, current and output-load observation",
        "required_observables": ["electrical", "output_effect"],
        "work_items": ["P1.04", "P8.05"],
    },
    {
        "id": "fixture:network:application-reference",
        "family": "reference_network",
        "description": (
            "Isolated network with interface, burden, output and input units and an "
            "independent bus monitor for application command effects and events"
        ),
        "required_observables": ["output_effect", "input_event", "identity", "readback"],
        "work_items": ["P1.04", "P7.03", "P7.04"],
    },
)


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def canonical_digest(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def work_item_issues(path: Path = ROADMAP_PATH) -> dict[str, int]:
    text = path.read_text(encoding="utf-8")
    issues = {
        item: int(number)
        for item, number in re.findall(
            r"(?m)^- \[[ xX]\] \*\*(P\d+\.\d{2})\*\* \(\[#(\d+)\]", text
        )
    }
    if len(issues) != 59:
        raise ValueError("Roadmap must link all 59 work items to issues")
    return issues


def _work_items(ids: list[str] | tuple[str, ...], issues: dict[str, int]) -> list[dict]:
    def order(item: str) -> tuple[int, int]:
        package, number = item[1:].split(".")
        return int(package), int(number)

    unknown = sorted(set(ids) - set(issues))
    if unknown:
        raise ValueError(f"Unknown fixture work items: {unknown}")
    return [{"id": item, "issue": issues[item]} for item in sorted(set(ids), key=order)]


def _major(version: str) -> str:
    match = re.match(r"\s*(\d+)", version)
    return str(int(match[1])) if match else "unparsed"


def _catalogue(path: Path) -> dict[str, dict[str, set]]:
    from cbus_toolkit.unitspec import _children, _read_xml, _tag, _value

    root = _read_xml(path)
    if _tag(root) != "CBusUnits":
        raise ValueError("Expected a CBusUnits catalogue")
    by_spec: dict[str, dict[str, set]] = defaultdict(lambda: defaultdict(set))

    def visit(unit, inherited_title: str) -> None:
        title = _value(unit, "UnitTitle") or inherited_title
        subunits = _children(unit, "SubUnits")
        if subunits:
            for container in subunits:
                for child in _children(container, "Unit"):
                    visit(child, title)
            return
        numbers = {_value(unit, "CatalogNumber").strip()} | {
            value.strip()
            for value in _value(unit, "AlternativeCatalogNumbers").split(";")
            if value.strip()
        }
        fields = dict(
            part.split("=", 1) for part in title.split(";") if "=" in part
        )
        for revisions in _children(unit, "FirmwareRevisions"):
            for revision in _children(revisions, "Revision"):
                spec = _value(revision, "UnitSpecName").strip()
                if not spec:
                    continue
                row = by_spec[spec]
                row["catalogue_numbers"].update(number for number in numbers if number)
                row["categories"].add(fields.get("Category", "").strip())
                row["product_families"].add(fields.get("Family", "").strip())
                row["class_names"].add(_value(revision, "ClassName").strip())
                row["unit_types"].add(_value(revision, "UnitType").strip())
                minimum = _value(revision, "MinVersion").strip()
                maximum = _value(revision, "MaxVersion").strip()
                row["firmware_ranges"].add((minimum, maximum))

    for units in _children(root, "Units"):
        for unit in _children(units, "Unit"):
            visit(unit, "")
    return by_spec


def classify_family(categories: set[str], class_names: set[str], product_families: set[str]) -> str:
    """Deterministic device family; the first matching rule wins."""
    joined = " | ".join(sorted(categories))
    if "CBusEdlt" in class_names:
        return "edlt_display"
    if class_names & {"CBusDaliGateway", "CBusDali2Gateway"}:
        return "dali_gateway"
    rules = (
        ("Support Units - PC Interfaces", "pc_interface"),
        ("Support Units - Wireless PCI", "pc_interface"),
        ("Support Units - Bridges", "bridge"),
        ("Support Units - Wireless Gateways", "wireless_gateway"),
        ("Support Units - Gateways", "gateway"),
        ("Input Units - DLT", "dlt_display"),
        ("HVAC - Thermostats", "thermostat"),
        ("Input Units - Sensors", "sensor"),
        ("Output Units - Dimmers", "dimmer"),
        ("Output Units - Relays", "relay"),
        ("Output Units - Marshalling Boxes", "relay"),
        ("Output Units - Analogue", "analogue_output"),
        ("Media Units", "media"),
        ("Touchscreens", "touchscreen"),
        ("Input Units - Clocks", "clock"),
        ("Input Units - ", "key_input"),
        ("I/O Units - ", "wireless_device"),
        ("Support Units - Remote Controls", "wireless_device"),
        ("Support Units - Power Supplies", "power_supply"),
        ("Support Units - Telephone Interfaces", "telephone_interface"),
        ("Third Party Units", "third_party"),
        ("Miscellaneous - ", "miscellaneous"),
        ("Support Units - General", "support_general"),
    )
    for needle, family in rules:
        if needle in joined:
            if family == "gateway" and any(
                family_name.startswith("Wireless") for family_name in product_families
            ):
                return "wireless_gateway"
            return family
    raise ValueError(f"Unclassified catalogue categories: {sorted(categories)}")


def unit_rows(spec_dir: Path, catalogue_path: Path, issues: dict[str, int]) -> tuple[list[dict], list[dict]]:
    from cbus_toolkit.unitspec import UnitSpecStore, _read_xml, _tag

    store = UnitSpecStore(spec_dir)
    catalogue = _catalogue(catalogue_path)
    paths = sorted(spec_dir.glob("*.xml"), key=lambda path: path.name)
    loaded: dict[str, Any] = {}
    inputs: list[dict] = []
    included: set[str] = set()
    for path in paths:
        if _tag(_read_xml(path)) not in ("UnitSpecification", "UnitSpec"):
            continue
        spec = store.load(path.name)
        loaded[path.name] = spec
        included.update(spec.sources[:-1])
    for path in paths:
        name = path.name
        spec = loaded.get(name)
        if spec is None:
            role = "non_unit_specification"
        elif name in catalogue:
            role = "catalogued_device"
        elif name in included:
            role = "include_only"
        elif "_TEMPLATE" in name.upper():
            role = "template"
        elif name.startswith("I_") or spec.unit_type in {"BASIC", "XXXXXXXX"}:
            role = "base_include"
        else:
            role = "uncatalogued_device_variant"
        inputs.append({"filename": name, "sha256": digest(path), "role": role})
    input_by_name = {row["filename"]: row for row in inputs}

    family_by_type: dict[str, set[str]] = defaultdict(set)
    family_by_include: dict[str, set[str]] = defaultdict(set)
    rows: list[dict] = []
    variants: list[str] = []
    for name, spec in sorted(loaded.items()):
        role = input_by_name[name]["role"]
        if role == "uncatalogued_device_variant":
            variants.append(name)
            continue
        if role != "catalogued_device":
            continue
        entry = catalogue[name]
        family = classify_family(
            entry["categories"], entry["class_names"], entry["product_families"]
        )
        family_by_type[spec.unit_type].add(family)
        for source in spec.sources[:-1]:
            family_by_include[source].add(family)
        rows.append(_unit_row(name, spec, family, entry, input_by_name, issues))
    for name in variants:
        # A variant the catalogue never selects inherits the family of the
        # catalogued devices with its unit type, else of the catalogued devices
        # sharing its most direct include.
        spec = loaded[name]
        families = family_by_type.get(spec.unit_type, set())
        if not families and len(spec.sources) > 1:
            families = family_by_include.get(spec.sources[-2], set())
        if len(families) != 1:
            raise ValueError(f"Uncatalogued variant {name} has no unique catalogued family")
        rows.append(
            _unit_row(name, spec, next(iter(families)), None, input_by_name, issues)
        )
    rows.sort(key=lambda row: row["id"])
    return rows, inputs


def _unit_row(
    name: str,
    spec: Any,
    family: str,
    entry: dict[str, set] | None,
    input_by_name: dict[str, dict],
    issues: dict[str, int],
) -> dict:
    methods = sorted(
        {
            parameter.fields.get("ProgramMethod", "").strip().lower()
            for parameter in spec.parameters.values()
            if parameter.fields.get("ProgramMethod", "").strip()
        }
    )
    protections = sorted(
        {
            parameter.fields.get("Protection", "").strip().lower() or "unspecified"
            for parameter in spec.parameters.values()
        }
    )
    ranges = sorted(entry["firmware_ranges"]) if entry else []
    spec_range = [
        spec.metadata.get("MinVersion", "").strip(),
        spec.metadata.get("MaxVersion", "").strip(),
    ]
    # A bare MaxVersion such as "9" is an open upper bound, not a released
    # major version; use actual catalogue revisions whenever they exist.
    majors = sorted(
        {
            _major(version)
            for minimum, maximum in ranges
            for version in (minimum, maximum if "." in maximum else "")
            if version
        }
        if ranges
        else {_major(spec_range[0])} if spec_range[0] else set(),
        key=lambda value: (value == "unparsed", int(value) if value.isdigit() else 0),
    )
    observables = list(UNIT_OBSERVABLES) + [
        item
        for item in FAMILY_OBSERVABLES.get(family, ())
        if item not in UNIT_OBSERVABLES
    ]
    stem = name.rsplit(".", 1)[0]
    return {
        "id": f"fixture:unit:{stem}",
        "kind": "unit_type",
        "family": family,
        "unit_type": spec.unit_type,
        "spec_filename": name,
        "catalogue": {
            "status": "catalogued" if entry else "not_selected_by_catalogue",
            "numbers": sorted(entry["catalogue_numbers"]) if entry else [],
            "categories": sorted(entry["categories"]) if entry else [],
            "class_names": sorted(entry["class_names"]) if entry else [],
            "unit_types": sorted(entry["unit_types"]) if entry else [],
        },
        "firmware": {
            "spec_range": spec_range,
            "catalogue_ranges": [list(pair) for pair in ranges],
            "major_versions": majors,
        },
        "programming": {
            "methods": methods,
            "protection_classes": protections,
        },
        "required_observables": observables,
        "work_items": _work_items(
            list(UNIT_WORK_ITEMS) + list(FAMILY_WORK_ITEMS.get(family, ())), issues
        ),
        "status": "unavailable",
        "private_manifest_ref": None,
        "input_digest": {
            "spec_sha256": input_by_name[name]["sha256"],
            "include_sha256": {
                source: input_by_name[source]["sha256"]
                for source in sorted(spec.sources[:-1])
            },
        },
    }


def programming_rows(units: list[dict], issues: dict[str, int]) -> list[dict]:
    by_method: dict[str, list[dict]] = defaultdict(list)
    for row in units:
        for method in row["programming"]["methods"]:
            by_method[method].append(row)
    rows = []
    for method, members in sorted(by_method.items()):
        rows.append(
            {
                "id": f"fixture:programming:{method}",
                "kind": "programming_class",
                "family": "programming_method",
                "description": (
                    f"A physical unit programmed through ProgramMethod {method}, "
                    "covering each protection class its candidates declare"
                ),
                "program_method": method,
                "protection_classes": sorted(
                    {item for row in members for item in row["programming"]["protection_classes"]}
                ),
                "candidate_fixture_ids": sorted(row["id"] for row in members),
                "required_observables": ["readback", "power_cycle_persistence", "identity"],
                "work_items": _work_items(["P1.04", "P4.01", "P4.02", "P4.04"], issues),
                "status": "unavailable",
                "private_manifest_ref": None,
                "input_digest": {
                    "candidate_rows_sha256": canonical_digest(
                        sorted(row["input_digest"]["spec_sha256"] for row in members)
                    ),
                },
            }
        )
    return rows


def assembly_rows(issues: dict[str, int]) -> list[dict]:
    rows = []
    for template in ASSEMBLIES:
        row = {
            "id": template["id"],
            "kind": "assembly",
            "family": template["family"],
            "description": template["description"],
        }
        if "bridge_count" in template:
            row["bridge_count"] = template["bridge_count"]
        row.update(
            {
                "required_observables": list(template["required_observables"]),
                "work_items": _work_items(template["work_items"], issues),
                "status": "unavailable",
                "private_manifest_ref": None,
                "input_digest": {"definition_sha256": canonical_digest(template)},
            }
        )
        rows.append(row)
    return sorted(rows, key=lambda row: row["id"])


def build(spec_dir: Path, catalogue_path: Path, *, roadmap: Path = ROADMAP_PATH) -> dict:
    sys.path.insert(0, str(ROOT / "src"))
    issues = work_item_issues(roadmap)
    units, inputs = unit_rows(spec_dir, catalogue_path, issues)
    fixtures = assembly_rows(issues) + programming_rows(units, issues) + units
    fixtures.sort(key=lambda row: (KINDS.index(row["kind"]), row["id"]))
    ledger = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    matrix = {
        "format": FORMAT,
        "target": ledger["target"],
        "purpose": (
            "Required physical fixtures for acceptance. Identifiers, catalogue "
            "metadata and input digests only; no unit specification content."
        ),
        "status_rule": (
            "unavailable blocks every dependent physical acceptance case; "
            "provisioned requires a private manifest reference; neither "
            "status is acceptance evidence"
        ),
        "inputs": {
            "catalogue": {"name": "cbusunits.xml", "sha256": digest(catalogue_path)},
            "unit_spec_count": len(inputs),
            "unit_specs": inputs,
        },
        "counts": _counts(fixtures, inputs),
        "fixtures": fixtures,
    }
    matrix["matrix_sha256"] = canonical_digest(matrix)
    validate_matrix(matrix)
    return matrix


def _counts(fixtures: list[dict], inputs: list[dict]) -> dict:
    return {
        "fixtures": len(fixtures),
        "by_kind": dict(sorted(Counter(row["kind"] for row in fixtures).items())),
        "by_family": dict(sorted(Counter(row["family"] for row in fixtures).items())),
        "by_status": dict(sorted(Counter(row["status"] for row in fixtures).items())),
        "unit_specs_by_role": dict(sorted(Counter(row["role"] for row in inputs).items())),
    }


def validate_matrix(matrix: dict) -> dict[str, dict]:
    """Validate the committed matrix without private inputs; return rows by ID."""
    if not isinstance(matrix, dict) or matrix.get("format") != FORMAT:
        raise ValueError("Hardware fixture matrix format changed")
    unsigned = {key: value for key, value in matrix.items() if key != "matrix_sha256"}
    if matrix.get("matrix_sha256") != canonical_digest(unsigned):
        raise ValueError("Hardware fixture matrix digest changed")
    inputs = matrix.get("inputs")
    if (
        not isinstance(inputs, dict)
        or not isinstance(inputs.get("catalogue"), dict)
        or not SHA256_RE.fullmatch(str(inputs["catalogue"].get("sha256")))
        or not isinstance(inputs.get("unit_specs"), list)
        or inputs.get("unit_spec_count") != len(inputs["unit_specs"])
    ):
        raise ValueError("Hardware fixture matrix inputs are invalid")
    spec_digests: dict[str, str] = {}
    for spec in inputs["unit_specs"]:
        if (
            not isinstance(spec, dict)
            or set(spec) != {"filename", "sha256", "role"}
            or not isinstance(spec["filename"], str)
            or spec["filename"] in spec_digests
            or not SHA256_RE.fullmatch(str(spec["sha256"]))
            or spec["role"] not in SPEC_ROLES
        ):
            raise ValueError("Hardware fixture matrix has an invalid unit spec input")
        spec_digests[spec["filename"]] = spec["sha256"]
    fixtures = matrix.get("fixtures")
    if not isinstance(fixtures, list) or not fixtures:
        raise ValueError("Hardware fixture matrix requires fixtures")
    by_id: dict[str, dict] = {}
    unit_specs: set[str] = set()
    for row in fixtures:
        fixture_id = row.get("id") if isinstance(row, dict) else None
        if not isinstance(fixture_id, str) or not FIXTURE_ID_RE.fullmatch(fixture_id):
            raise ValueError(f"Invalid fixture id: {fixture_id!r}")
        if fixture_id in by_id:
            raise ValueError(f"Duplicate fixture id: {fixture_id}")
        if row.get("kind") not in KINDS or row.get("family") not in FAMILIES:
            raise ValueError(f"{fixture_id} has an unknown kind or family")
        observables = row.get("required_observables")
        if (
            not isinstance(observables, list)
            or not observables
            or len(set(observables)) != len(observables)
            or set(observables) - set(OBSERVABLES)
        ):
            raise ValueError(f"{fixture_id} requires known observables")
        work_items = row.get("work_items")
        if (
            not isinstance(work_items, list)
            or not work_items
            or any(
                not isinstance(item, dict)
                or set(item) != {"id", "issue"}
                or not re.fullmatch(r"P(?:1[01]|[0-9])\.\d{2}", str(item["id"]))
                or type(item["issue"]) is not int
                for item in work_items
            )
            or "P1.04" not in {item["id"] for item in work_items}
        ):
            raise ValueError(f"{fixture_id} requires owning work items including P1.04")
        status = row.get("status")
        reference = row.get("private_manifest_ref")
        if status not in STATUSES:
            raise ValueError(f"{fixture_id} has an unknown status")
        if status == "provisioned" and (
            not isinstance(reference, str) or not PRIVATE_MANIFEST_RE.fullmatch(reference)
        ):
            raise ValueError(f"{fixture_id} is provisioned without a private manifest reference")
        if status == "unavailable" and reference is not None:
            raise ValueError(f"{fixture_id} is unavailable but names a private manifest")
        input_digest = row.get("input_digest")
        if not isinstance(input_digest, dict) or not input_digest:
            raise ValueError(f"{fixture_id} requires an input digest")
        if row["kind"] == "unit_type":
            name = row.get("spec_filename")
            if (
                row["family"] not in UNIT_FAMILIES
                or name not in spec_digests
                or input_digest.get("spec_sha256") != spec_digests[name]
                or any(
                    spec_digests.get(include) != value
                    for include, value in input_digest.get("include_sha256", {}).items()
                )
            ):
                raise ValueError(f"{fixture_id} is not bound to its unit spec digest")
            unit_specs.add(name)
        by_id[fixture_id] = row
    for row in by_id.values():
        for candidate in row.get("candidate_fixture_ids", []):
            if by_id.get(candidate, {}).get("kind") != "unit_type":
                raise ValueError(f"{row['id']} names an unknown candidate fixture")
    expected_specs = {
        spec["filename"]
        for spec in inputs["unit_specs"]
        if spec["role"] in FIXTURE_SPEC_ROLES
    }
    if unit_specs != expected_specs:
        raise ValueError("Hardware fixture matrix unit rows differ from device spec inputs")
    assembly_families = {
        row["family"] for row in by_id.values() if row["kind"] == "assembly"
    }
    missing = sorted(set(REQUIRED_ASSEMBLY_FAMILIES) - assembly_families)
    if missing:
        raise ValueError(f"Hardware fixture matrix lacks required families: {missing}")
    if {
        row.get("bridge_count")
        for row in by_id.values()
        if row["family"] == "bridge_topology"
    } != set(range(1, 7)):
        raise ValueError("Hardware fixture matrix requires one to six bridge topologies")
    if matrix.get("counts") != _counts(fixtures, inputs["unit_specs"]):
        raise ValueError("Hardware fixture matrix counts changed")
    return by_id


def render(matrix: dict) -> str:
    return json.dumps(matrix, ensure_ascii=False, indent=2) + "\n"


def load_committed(path: Path = MATRIX_PATH) -> tuple[dict, bytes]:
    raw = path.read_bytes()
    sys.path.insert(0, str(ROOT / "src"))
    from cbus_toolkit.parity import parse_json_document

    return parse_json_document(raw, context=path.name), raw


def default_inputs() -> tuple[Path | None, Path | None]:
    spec_dir = os.environ.get("CBUS_UNITSPEC_DIR")
    vendor = os.environ.get("CBUS_LOCAL_CGATE_VENDOR")
    return (
        Path(spec_dir) if spec_dir else None,
        Path(vendor) / "unitspec" / "cbusunits.xml" if vendor else None,
    )


def main(argv: list[str] | None = None) -> int:
    spec_default, catalogue_default = default_inputs()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unitspec-dir", type=Path, default=spec_default)
    parser.add_argument("--catalogue", type=Path, default=catalogue_default)
    parser.add_argument("--output", type=Path, default=MATRIX_PATH)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="regenerate from private inputs and compare")
    mode.add_argument("--verify", action="store_true", help="validate the committed matrix without private inputs")
    args = parser.parse_args(argv)
    if args.verify:
        matrix, _ = load_committed(args.output)
        rows = validate_matrix(matrix)
        print(json.dumps({"status": "valid", "fixtures": len(rows), **matrix["counts"]}, indent=2))
        return 0
    if (
        args.unitspec_dir is None
        or args.catalogue is None
        or not args.unitspec_dir.is_dir()
        or not args.catalogue.is_file()
    ):
        print(
            "hardware fixture matrix inputs are unavailable: set CBUS_UNITSPEC_DIR and "
            "CBUS_LOCAL_CGATE_VENDOR (or pass --unitspec-dir/--catalogue)",
            file=sys.stderr,
        )
        return 2
    content = render(build(args.unitspec_dir, args.catalogue))
    if args.check:
        if not args.output.is_file() or args.output.read_text(encoding="utf-8") != content:
            print(f"stale hardware fixture matrix: {args.output}", file=sys.stderr)
            return 1
        status = "current"
    else:
        args.output.write_text(content, encoding="utf-8")
        status = "generated"
    matrix = json.loads(content)
    print(json.dumps({"status": status, **matrix["counts"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
