#!/usr/bin/env python3
"""Generate the provisional, packaged parity register from committed inventories.

This generator accounts for source surfaces without pretending that a help
topic, heading, anchor, command route or broad feature row is one accepted
function.  P0 closes only after the provisional scope items are reviewed and
deduplicated into defined functional obligations.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = ROOT.parent
PACKAGE = ROOT / "src" / "cbus_toolkit"
SURFACE_PATH = ROOT / "docs" / "toolkit-surface.json"
EXECUTABLE_SURFACE_PATH = ROOT / "docs" / "toolkit-executable-surface.json"
LEDGER_PATH = PACKAGE / "capabilities.json"
MATRIX_PATH = REPOSITORY / "rust" / "cbus-cgate" / "src" / "capability_matrix.rs"
ROADMAP_PATH = REPOSITORY / "docs" / "parity-review-and-roadmap.md"
REGISTER_PATH = PACKAGE / "parity-obligations.json"
EVIDENCE_PATH = PACKAGE / "parity-evidence.json"

FAMILY_LEDGER = {
    "projects": ("legacy-project-editing", "native-cgate3-projects"),
    "networks": ("interface-discovery-and-setup", "network-scan-unravel-routing"),
    "applications": ("groups-applications-control",),
    "application_log": ("cgate-command-transport",),
    "unit_database": ("native-unit-defaults-and-database-editing",),
    "commissioning": ("physical-unit-addressing", "serial-directed-commissioning"),
    "global_programming": ("unit-read-write-verify",),
    "templates": ("toolkit-unit-templates",),
    "conversion": ("unit-copy-convert-reset",),
    "dynamic_labels": ("dlt-edlt-widgets-and-labels", "scenes-triggers-labels"),
    "scenes": ("scenes-triggers-labels",),
    "timers": ("classic-key-presets", "neo-core-key-presets"),
    "output_logic": ("all-unit-parameter-encoding",),
    "thermostat_schedule": ("thermostat-configuration",),
    "macros": ("classic-key-presets", "neo-core-key-presets"),
    "wireless": ("interface-discovery-and-setup",),
    "controllers": ("groups-applications-control",),
    "cgl": ("cgl-import-export",),
    "reports": ("toolkit-database-report-export",),
    "topology": ("network-scan-unravel-routing",),
    "firmware": ("firmware-update",),
    "diagnostics": ("network-calculator-diagnostics",),
    "barcode": ("toolkit-differential-acceptance",),
    "protocol_reference": ("groups-applications-control",),
    "unit_types": ("vendor-catalog-inventory", "all-unit-parameter-encoding"),
    "device_configuration": ("all-unit-parameter-encoding",),
}


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def roadmap_maps() -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    text = ROADMAP_PATH.read_text(encoding="utf-8")
    items: dict[str, list[str]] = {}
    for package in re.findall(r'^- \[ \] \*\*(P\d+\.\d{2})\*\*', text, re.M):
        items.setdefault(package.split(".")[0], []).append(package)
    if sum(map(len, items.values())) != 59:
        raise ValueError("Roadmap must expose all 59 stable work item IDs")
    ledger_packages: dict[str, list[str]] = {}
    for ledger_id, packages in re.findall(
        r'^\| `([^`]+)` \| [IWP] \| .*? \| ([^|]+) \|$', text, re.M
    ):
        package_ids = re.findall(r'P(?:1[01]|[0-9])', packages)
        ledger_packages[ledger_id] = package_ids
    return items, ledger_packages


def capability_paths() -> tuple[list[dict], list[dict]]:
    text = MATRIX_PATH.read_text(encoding="utf-8")
    primary_text, supplement_text = text.split(
        "pub const SUPPLEMENT_ROUTING", maxsplit=1
    )
    pattern = re.compile(
        r'CapabilityEntry \{ path: "([^"]+)", class: RoutingClass::(\w+), evidence: "([^"]*)" \}'
    )

    def rows(part: str) -> list[dict]:
        return [
            {"path": path, "routing_class": routing, "routing_evidence": evidence}
            for path, routing, evidence in pattern.findall(part)
        ]

    primary, supplement = rows(primary_text), rows(supplement_text)
    if len(primary) != 431:
        raise ValueError(f"Expected 431 primary C-Gate paths, found {len(primary)}")
    return primary, supplement


def executable_surface() -> dict:
    surface = load_json(EXECUTABLE_SURFACE_PATH)
    if surface.get("schema_version") != 1:
        raise ValueError("Executable surface requires schema_version 1")
    counts = surface.get("counts")
    resources = surface.get("resources")
    if not isinstance(counts, dict) or not isinstance(resources, list):
        raise ValueError("Executable surface requires counts and resources")
    if counts.get("parse_errors") != 0:
        raise ValueError("Executable surface contains parse errors")
    if counts.get("parsed_form_resources") != len(resources):
        raise ValueError("Executable form count does not match resources")
    resource_names = [row.get("resource_name") for row in resources if isinstance(row, dict)]
    if len(resource_names) != len(resources) or len(resource_names) != len(set(resource_names)):
        raise ValueError("Executable resources require unique names")
    component_count = 0
    event_count = 0
    for resource in resources:
        components = resource.get("components")
        events = resource.get("event_bindings")
        if not isinstance(components, list) or not isinstance(events, list):
            raise ValueError(f"{resource['resource_name']} requires components and events")
        paths = [row.get("path") for row in components if isinstance(row, dict)]
        if len(paths) != len(components) or len(paths) != len(set(paths)):
            raise ValueError(f"{resource['resource_name']} has invalid component paths")
        for event in events:
            if not isinstance(event, dict) or event.get("component_path") not in paths:
                raise ValueError(f"{resource['resource_name']} has an invalid event binding")
        component_count += len(components)
        event_count += len(events)
    if counts.get("components") != component_count or counts.get("event_bindings") != event_count:
        raise ValueError("Executable component/event counts do not match resources")
    return surface


def build() -> tuple[dict, dict]:
    surface = load_json(SURFACE_PATH)
    executable = executable_surface()
    ledger = load_json(LEDGER_PATH)
    work_items, ledger_packages = roadmap_maps()
    ledger_ids = {feature["id"] for feature in ledger["features"]}
    sys.path.insert(0, str(ROOT / "src"))
    from cbus_toolkit.device_dialogs import list_dialogs

    dialog_ledger = {
        row["dialog_id"]: row["ledger_id"] for row in list_dialogs()
    }
    primary_paths, supplement_paths = capability_paths()
    scope_items: list[dict] = []

    def obligation_ids(ledger_targets: list[str] | tuple[str, ...]) -> list[str]:
        targets = sorted(set(ledger_targets) & ledger_ids)
        return [f"ledger:{target}" for target in targets] or ["ledger:toolkit-surface-census"]

    def topic_targets(topic: dict) -> list[str]:
        targets: list[str] = []
        for family in topic.get("family_ids", []):
            targets.extend(FAMILY_LEDGER.get(family, ()))
        return targets or ["toolkit-surface-census"]

    for topic in surface["topics"]:
        targets = topic_targets(topic)
        scope_items.append(
            {
                "id": f"scope:topic:{topic['id']}",
                "kind": "topic",
                "source_id": topic["id"],
                "source_sha256": topic["page"]["sha256"],
                "obligation_ids": obligation_ids(targets),
                "disposition": "provisional_obligation",
            }
        )
        for ordinal, heading in enumerate(topic["page"]["headings"]):
            scope_items.append(
                {
                    "id": f"scope:heading:{topic['file']}:{ordinal}",
                    "kind": "heading",
                    "source_id": f"{topic['id']}#heading-{ordinal}",
                    "source_sha256": heading["sha256"],
                    "obligation_ids": obligation_ids(targets),
                    "disposition": "pending_analysis",
                }
            )
        for ordinal, anchor in enumerate(topic["page"]["anchors"]):
            scope_items.append(
                {
                    "id": f"scope:anchor:{topic['file']}:{ordinal}",
                    "kind": "anchor",
                    "source_id": f"{topic['id']}#anchor-{ordinal}",
                    "source_sha256": anchor.get("sha256", topic["page"]["sha256"]),
                    "obligation_ids": obligation_ids(targets),
                    "disposition": "pending_analysis",
                }
            )
    for dialog in surface["device_dialog_candidates"]:
        scope_items.append(
            {
                "id": f"scope:dialog:{dialog['id']}",
                "kind": "dialog",
                "source_id": dialog["id"],
                "obligation_ids": obligation_ids([dialog_ledger[dialog["id"]]]),
                "disposition": "provisional_obligation",
            }
        )
    for topic_id in surface["macro_reference"]["leaf_topic_ids"]:
        scope_items.append(
            {
                "id": f"scope:macro:{topic_id}",
                "kind": "macro_leaf",
                "source_id": topic_id,
                "obligation_ids": obligation_ids(
                    ["classic-key-presets", "neo-core-key-presets", "all-unit-parameter-encoding"]
                ),
                "disposition": "pending_analysis",
            }
        )
    for row in surface["unindexed_html"]:
        scope_items.append(
            {
                "id": f"scope:unindexed:{row['file']}",
                "kind": "unindexed_html",
                "source_id": row["file"],
                "source_sha256": row["sha256"],
                "obligation_ids": obligation_ids(["toolkit-surface-census"]),
                "disposition": "pending_analysis",
            }
        )
    for command in surface["public_commands"]:
        scope_items.append(
            {
                "id": f"scope:public-command:{command['id']}",
                "kind": "public_command",
                "source_id": command["id"],
                "source_sha256": command["source"]["syntax_sha256"],
                "obligation_ids": obligation_ids(["cgate-command-transport"]),
                "disposition": "provisional_obligation",
            }
        )
    for kind, paths in (("cgate_primary_path", primary_paths), ("cgate_supplement_path", supplement_paths)):
        for row in paths:
            path_id = sha256(row["path"].encode("utf-8")).hexdigest()[:16]
            scope_items.append(
                {
                    "id": f"scope:{kind}:{path_id}",
                    "kind": kind,
                    "source_id": row["path"],
                    "routing_class": row["routing_class"],
                    "contract_status": "primary_path_only",
                    "contract_axes": {
                        "selectors": "unresolved",
                        "session_states": "unresolved",
                        "target_forms": "unresolved",
                        "authorization": "unresolved",
                        "response_event_envelopes": "unresolved",
                        "effects": "routing_class_only",
                    },
                    "obligation_ids": obligation_ids(["cgate-command-transport"]),
                    "disposition": "provisional_obligation",
                }
            )
    for resource in executable["resources"]:
        resource_name = resource["resource_name"]
        resource_key = sha256(resource_name.encode("utf-8")).hexdigest()[:16]
        resource_obligations = obligation_ids(["toolkit-surface-census"])
        scope_items.append(
            {
                "id": f"scope:executable-form:{resource_key}",
                "kind": "executable_form",
                "source_id": resource_name,
                "source_sha256": resource["resource_sha256"],
                "obligation_ids": resource_obligations,
                "disposition": "provisional_obligation",
            }
        )
        for component in resource["components"]:
            source_id = f"{resource_name}/{component['path']}"
            item_key = sha256(source_id.encode("utf-8")).hexdigest()[:20]
            scope_items.append(
                {
                    "id": f"scope:executable-control:{item_key}",
                    "kind": "executable_control",
                    "source_id": source_id,
                    "component_class": component["class"],
                    "obligation_ids": resource_obligations,
                    "disposition": "pending_analysis",
                }
            )
        for event in resource["event_bindings"]:
            source_id = (
                f"{resource_name}/{event['component_path']}"
                f"#{event['property']}={event['handler']}"
            )
            item_key = sha256(source_id.encode("utf-8")).hexdigest()[:20]
            scope_items.append(
                {
                    "id": f"scope:executable-event:{item_key}",
                    "kind": "executable_event",
                    "source_id": source_id,
                    "obligation_ids": resource_obligations,
                    "disposition": "pending_analysis",
                }
            )

    status_map = {
        "implemented": "implemented",
        "in_progress": "in_progress",
        "pending": "pending",
    }
    obligations = []
    for feature in ledger["features"]:
        packages = ledger_packages.get(feature["id"], ["P0", "P11"])
        issue_ids = sorted({item for package in packages for item in work_items[package]})
        obligations.append(
            {
                "id": f"ledger:{feature['id']}",
                "ledger_id": feature["id"],
                "work_item_ids": issue_ids,
                "definition_status": "provisional",
                "implementation_status": status_map[feature["status"]],
                "applicability_status": "unresolved",
                "outcome": f"Resolve and accept the complete version-specific functional scope represented by {feature['id']}",
                "source_refs": [
                    "capabilities.json",
                    "toolkit-surface.json",
                    "toolkit-executable-surface.json",
                ],
                "acceptance": {
                    dimension: "unassessed"
                    for dimension in (
                        "nominal",
                        "error",
                        "invalid_input",
                        "profile_variation",
                        "original_differential",
                        "physical",
                        "persistence_recovery",
                    )
                },
                "evidence_ids": [],
            }
        )

    by_kind: dict[str, int] = {}
    for item in scope_items:
        by_kind[item["kind"]] = by_kind.get(item["kind"], 0) + 1
    source_inventory = [
        {"id": "indexed_topics", "scope_kind": "topic", "count": by_kind["topic"], "resolved": False},
        {"id": "page_headings", "scope_kind": "heading", "count": by_kind["heading"], "resolved": False},
        {"id": "page_anchors", "scope_kind": "anchor", "count": by_kind["anchor"], "resolved": False},
        {"id": "device_dialog_candidates", "scope_kind": "dialog", "count": by_kind["dialog"], "resolved": False},
        {"id": "macro_reference_leaves", "scope_kind": "macro_leaf", "count": by_kind["macro_leaf"], "resolved": False},
        {"id": "unindexed_html", "scope_kind": "unindexed_html", "count": by_kind["unindexed_html"], "resolved": False},
        {"id": "public_command_blocks", "scope_kind": "public_command", "count": by_kind["public_command"], "resolved": False},
        {"id": "cgate_primary_paths", "scope_kind": "cgate_primary_path", "count": by_kind["cgate_primary_path"], "resolved": False},
        {"id": "cgate_supplement_paths", "scope_kind": "cgate_supplement_path", "count": by_kind["cgate_supplement_path"], "resolved": False},
        {"id": "executable_form_resources", "scope_kind": "executable_form", "count": by_kind["executable_form"], "resolved": False},
        {"id": "executable_controls", "scope_kind": "executable_control", "count": by_kind["executable_control"], "resolved": False},
        {"id": "executable_event_bindings", "scope_kind": "executable_event", "count": by_kind["executable_event"], "resolved": False},
        {"id": "undocumented_toolkit_branches", "count": None, "resolved": False},
        {"id": "cgate_selector_state_effect_contracts", "count": by_kind["cgate_primary_path"] + by_kind["cgate_supplement_path"], "resolved": False},
        {"id": "catalogue_device_firmware_profiles", "count": surface["counts"]["catalogue_firmware_revisions"], "resolved": False},
    ]
    evidence = {
        "schema_version": 1,
        "target": ledger["target"],
        "records": [],
    }
    evidence_raw = (json.dumps(evidence, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    register = {
        "schema_version": 1,
        "target": ledger["target"],
        "denominator_version": "provisional-2026-09-27.2",
        "census_complete": False,
        "purpose": "Provisional exhaustive source accounting; not yet a deduplicated functional denominator or acceptance claim.",
        "source_digests": {
            "toolkit_surface": digest(SURFACE_PATH),
            "toolkit_executable_surface": digest(EXECUTABLE_SURFACE_PATH),
            "toolkit_executable_binary": executable["sources"]["executable"]["sha256"],
            "toolkit_map": executable["sources"]["map"]["sha256"],
            "feature_ledger": digest(LEDGER_PATH),
            "cgate_capability_matrix": digest(MATRIX_PATH),
            "roadmap": digest(ROADMAP_PATH),
        },
        "evidence_bundle_sha256": sha256(evidence_raw).hexdigest(),
        "source_inventory": source_inventory,
        "scope_items": scope_items,
        "obligations": obligations,
    }
    return register, evidence


def render(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    register, evidence = build()
    outputs = {REGISTER_PATH: render(register), EVIDENCE_PATH: render(evidence)}
    if args.check:
        stale = [str(path.relative_to(ROOT)) for path, content in outputs.items() if not path.is_file() or path.read_text(encoding="utf-8") != content]
        if stale:
            raise SystemExit("stale parity files: " + ", ".join(stale))
    else:
        for path, content in outputs.items():
            path.write_text(content, encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "current" if args.check else "generated",
                "scope_items": len(register["scope_items"]),
                "obligations": len(register["obligations"]),
                "evidence_records": len(evidence["records"]),
                "census_complete": register["census_complete"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
