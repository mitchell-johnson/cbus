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
CGATE_CONTRACT_PATH = PACKAGE / "cgate-contract-inventory.json"
LEDGER_PATH = PACKAGE / "capabilities.json"
MATRIX_PATH = REPOSITORY / "rust" / "cbus-cgate" / "src" / "capability_matrix.rs"
MANUAL_PATH = REPOSITORY / "rust" / "cbus-cgate" / "src" / "manual.rs"
SERVICE_PATH = REPOSITORY / "rust" / "cbus-cgate" / "src" / "service.rs"
EVENT_MODE_PATH = REPOSITORY / "rust" / "cbus-cgate" / "src" / "lib.rs"
NATIVE_SESSION_PATH = (
    ROOT / "research" / "experiments" / "2026-09-25" / "cgate-session-native-acceptance.json"
)
NATIVE_SESSION_SOURCE_REF = (
    "research/experiments/2026-09-25/cgate-session-native-acceptance.json"
)
FUNCTIONAL_PILOT_PATH = ROOT / "research" / "functional-obligation-pilot.json"
SESSION_DIFFERENTIAL_PATH = (
    ROOT / "research" / "fixtures" / "cgate-session-differential-cmqttd.json"
)
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
    for package in re.findall(r'^- \[[ xX]\] \*\*(P\d+\.\d{2})\*\*', text, re.M):
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


def canonical_digest(value: dict) -> str:
    return sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def authorization_policy_digest() -> str:
    text = SERVICE_PATH.read_text(encoding="utf-8")
    start = text.index("fn requires_programming_auth(")
    end = text.index("\nfn local_command(", start)
    return sha256(text[start:end].encode()).hexdigest()


def cgate_contract_inventory(
    primary_paths: list[dict], supplement_paths: list[dict]
) -> dict:
    inventory = load_json(CGATE_CONTRACT_PATH)
    if inventory.get("schema_version") != 1:
        raise ValueError("C-Gate contract inventory requires schema_version 1")
    axis_schema = inventory.get("axis_schema")
    expected_axis_schema = {
        "selector_grammar": ["command_path", "argument_arity", "value_domains"],
        "session_states": ["connection", "recovery_mode", "selection_and_locks"],
        "target_forms": ["address_shape", "route_shape"],
        "authorization": ["connection_policy", "programming_gate", "handler_roles"],
        "response_event_envelopes": [
            "tag_and_completion_framing",
            "command_envelope",
            "event_fanout",
        ],
        "effects_routing": ["routing_class", "physical_io_boundary", "state_effect"],
        "implementation_acceptance": [
            "endpoint_route",
            "native_obsolescence",
            "functional_acceptance",
        ],
    }
    if axis_schema != expected_axis_schema:
        raise ValueError("C-Gate contract inventory axis schema changed")
    sources = inventory.get("sources")
    expected_sources = {
        "capability_matrix": digest(MATRIX_PATH),
        "manual": digest(MANUAL_PATH),
        "service": digest(SERVICE_PATH),
        "event_mode": digest(EVENT_MODE_PATH),
        "authorization_policy": authorization_policy_digest(),
        "toolkit_surface": digest(SURFACE_PATH),
        "native_session_acceptance": digest(NATIVE_SESSION_PATH),
    }
    if not isinstance(sources, dict):
        raise ValueError("C-Gate contract inventory requires sources")
    for source_name, source_digest in expected_sources.items():
        if sources.get(source_name) != {"sha256": source_digest}:
            raise ValueError(f"C-Gate contract source changed: {source_name}")
    contracts = inventory.get("contracts")
    if not isinstance(contracts, list) or len(contracts) != 442:
        raise ValueError("C-Gate contract inventory requires exactly 442 contracts")
    matrix_rows = {
        row["path"]: (kind, row)
        for kind, paths in (("primary", primary_paths), ("supplement", supplement_paths))
        for row in paths
    }
    contract_by_path: dict[str, dict] = {}
    axis_counts: dict[str, dict[str, int]] = {
        axis_name: {} for axis_name in expected_axis_schema
    }
    subaxis_counts: dict[str, dict[str, int]] = {}
    for contract in contracts:
        if not isinstance(contract, dict):
            raise ValueError("Every C-Gate contract must be an object")
        path = contract.get("path")
        if not isinstance(path, str) or path not in matrix_rows:
            raise ValueError(f"C-Gate contract has unknown path: {path!r}")
        if path in contract_by_path:
            raise ValueError(f"Duplicate C-Gate contract path: {path}")
        kind, matrix_row = matrix_rows[path]
        if contract.get("inventory") != kind:
            raise ValueError(f"C-Gate contract inventory class changed: {path}")
        if contract.get("routing_evidence") != matrix_row["routing_evidence"]:
            raise ValueError(f"C-Gate routing evidence changed: {path}")
        expected_id = f"cgate-contract:{sha256(path.encode()).hexdigest()[:16]}"
        if contract.get("id") != expected_id:
            raise ValueError(f"C-Gate contract id changed: {path}")
        axes = contract.get("axes")
        if not isinstance(axes, dict) or set(axes) != set(expected_axis_schema):
            raise ValueError(f"C-Gate contract axes changed: {path}")
        if contract.get("axes_sha256") != canonical_digest(axes):
            raise ValueError(f"C-Gate contract axes digest changed: {path}")
        unsigned = {key: value for key, value in contract.items() if key != "contract_sha256"}
        if contract.get("contract_sha256") != canonical_digest(unsigned):
            raise ValueError(f"C-Gate contract digest changed: {path}")
        for axis_name, subaxis_names in expected_axis_schema.items():
            axis = axes[axis_name]
            if not isinstance(axis, dict) or set(axis) != {"status", "subaxes"}:
                raise ValueError(f"{path}.{axis_name} has an invalid axis")
            subaxes = axis["subaxes"]
            if not isinstance(subaxes, dict) or list(subaxes) != subaxis_names:
                raise ValueError(f"{path}.{axis_name} has invalid subaxes")
            resolved_count = 0
            for subaxis_name, subaxis in subaxes.items():
                if not isinstance(subaxis, dict) or subaxis.get("status") not in {
                    "resolved",
                    "unresolved",
                }:
                    raise ValueError(f"{path}.{axis_name}.{subaxis_name} has invalid status")
                refs = subaxis.get("source_refs")
                if (
                    not isinstance(refs, list)
                    or not refs
                    or not all(isinstance(ref, str) and ref for ref in refs)
                    or len(refs) != len(set(refs))
                ):
                    raise ValueError(f"{path}.{axis_name}.{subaxis_name} has invalid source refs")
                if subaxis["status"] == "resolved":
                    resolved_count += 1
                    if "value" not in subaxis or "reason" in subaxis:
                        raise ValueError(f"{path}.{axis_name}.{subaxis_name} lacks a resolved value")
                elif not isinstance(subaxis.get("reason"), str) or not subaxis["reason"].strip():
                    raise ValueError(f"{path}.{axis_name}.{subaxis_name} lacks an unresolved reason")
                key = f"{axis_name}.{subaxis_name}"
                counts = subaxis_counts.setdefault(key, {})
                counts[subaxis["status"]] = counts.get(subaxis["status"], 0) + 1
            expected_status = (
                "resolved"
                if resolved_count == len(subaxes)
                else "unresolved"
                if resolved_count == 0
                else "partial"
            )
            if axis["status"] != expected_status:
                raise ValueError(f"{path}.{axis_name} aggregate status changed")
            counts = axis_counts[axis_name]
            counts[expected_status] = counts.get(expected_status, 0) + 1
        contract_by_path[path] = contract
    if set(contract_by_path) != set(matrix_rows):
        raise ValueError("C-Gate contract paths differ from the capability matrix")
    counts = inventory.get("counts")
    expected_counts = {
        "paths": 442,
        "primary_paths": 431,
        "supplement_paths": 11,
        "declarative_argument_arities": 70,
        "public_help_syntax_hashes": 209,
        "native_handler_role_observations": 345,
        "native_handler_role_unresolved": 345,
        "axis_status": {
            key: dict(sorted(value.items())) for key, value in axis_counts.items()
        },
        "subaxis_status": {
            key: dict(sorted(value.items())) for key, value in subaxis_counts.items()
        },
    }
    if counts != expected_counts:
        raise ValueError("C-Gate contract inventory counts changed")
    return inventory


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


def functional_pilot(surface: dict, contract_by_path: dict[str, dict]) -> list[dict]:
    """Bind a narrow session-family definition to retained original sources.

    The help extraction and native trace are separate sources. A changed or
    missing one must stop regeneration rather than silently refresh an anchor.
    This does not turn the broader C-Gate path contracts into accepted work.
    """
    from cbus_toolkit.parity import CGATE_SESSION_PILOT_IDS

    pilot = load_json(FUNCTIONAL_PILOT_PATH)
    if (
        set(pilot) != {"schema_version", "target", "family", "native_oracle", "obligations"}
        or pilot.get("schema_version") != 1
        or pilot.get("target") != load_json(LEDGER_PATH)["target"]
        or pilot.get("family") != "C-Gate SESSION_ID on an owned loopback command session"
    ):
        raise ValueError("Functional pilot schema or target changed")
    oracle = pilot.get("native_oracle")
    if (
        not isinstance(oracle, dict)
        or set(oracle) != {"path", "sha256", "vendor_jar_sha256"}
        or oracle.get("path") != NATIVE_SESSION_SOURCE_REF
    ):
        raise ValueError("Functional pilot requires the owned native session source")
    if not NATIVE_SESSION_PATH.is_file():
        raise ValueError("Functional pilot native acceptance source is missing")
    if oracle.get("sha256") != digest(NATIVE_SESSION_PATH):
        raise ValueError("Functional pilot native acceptance source is stale")
    native = load_json(NATIVE_SESSION_PATH)
    environment = native.get("environment")
    cleanup = native.get("cleanup")
    if (
        native.get("format") != "cbus-cgate-session-native-acceptance-v1"
        or native.get("passed") is not True
        or native.get("vendor_jar_sha256") != oracle.get("vendor_jar_sha256")
        or not isinstance(environment, dict)
        or environment.get("physical_networks_opened") is not False
        or not isinstance(cleanup, dict)
        or cleanup.get("cleanup_complete") is not True
    ):
        raise ValueError("Functional pilot native acceptance source is not the owned loopback capture")
    native_cases = {
        (case.get("command"), case.get("status"))
        for case in native.get("cases", [])
        if isinstance(case, dict)
    }
    public_by_id = {command["id"]: command for command in surface["public_commands"]}
    definitions = pilot.get("obligations")
    if not isinstance(definitions, list) or {
        row.get("path") for row in definitions if isinstance(row, dict)
    } != set(CGATE_SESSION_PILOT_IDS) or len(definitions) != len(CGATE_SESSION_PILOT_IDS):
        raise ValueError("Functional pilot must define the three SESSION_ID variants")
    obligations = []
    for row in definitions:
        if set(row) != {
            "id", "path", "public_command_id", "source_anchor", "contract_sha256",
            "native_cases", "outcome", "preconditions", "preservation",
            "implementation_basis", "differential_gap", "physical_candidate_reason",
        }:
            raise ValueError("Functional pilot definition schema changed")
        path = row["path"]
        obligation_id = CGATE_SESSION_PILOT_IDS[path]
        public = public_by_id.get(f"cgate:{path}")
        contract = contract_by_path.get(path)
        if row.get("id") != obligation_id or row.get("public_command_id") != f"cgate:{path}":
            raise ValueError(f"Functional pilot has an unstable ID: {path}")
        if public is None or row.get("source_anchor") != public["source"]:
            raise ValueError(f"Functional pilot public-help anchor is missing or stale: {path}")
        if contract is None or row.get("contract_sha256") != contract["contract_sha256"]:
            raise ValueError(f"Functional pilot C-Gate contract anchor is missing or stale: {path}")
        cases = row.get("native_cases")
        if (
            not isinstance(cases, list)
            or not cases
            or any(
                not isinstance(case, dict)
                or set(case) != {"command", "status"}
                or not isinstance(case["command"], str)
                or not (
                    case["command"] == path or case["command"].startswith(path + " ")
                )
                or isinstance(case["status"], bool)
                or not isinstance(case["status"], int)
                or (case["command"], case["status"]) not in native_cases
                for case in cases
            )
            or len({(case["command"], case["status"]) for case in cases}) != len(cases)
        ):
            raise ValueError(f"Functional pilot native case anchor is missing or stale: {path}")
        for field in ("outcome", "implementation_basis", "differential_gap", "physical_candidate_reason"):
            if not isinstance(row.get(field), str) or not row[field].strip():
                raise ValueError(f"Functional pilot {path} requires {field}")
        for field in ("preconditions", "preservation"):
            values = row.get(field)
            if not isinstance(values, list) or not values or not all(
                isinstance(value, str) and value.strip() for value in values
            ):
                raise ValueError(f"Functional pilot {path} requires {field}")
        public_scope_id = f"scope:public-command:{public['id']}"
        path_scope_id = f"scope:cgate_primary_path:{sha256(path.encode()).hexdigest()[:16]}"
        obligations.append(
            {
                "id": obligation_id,
                "kind": "cgate_function",
                "ledger_id": "cgate-command-transport",
                "work_item_ids": ["P0.03"],
                "source_id": path,
                "source_scope_item_ids": [public_scope_id, path_scope_id],
                "source_anchor": row["source_anchor"],
                "contract_id": contract["id"],
                "contract_sha256": contract["contract_sha256"],
                "native_oracle": {**oracle, "cases": cases},
                "definition_status": "defined",
                "implementation_status": "in_progress",
                "implementation_basis": row["implementation_basis"],
                "implementation": {
                    "owner": "rust/cbus-cgate/src/service.rs#Service::handle",
                    "cli_entry_point": "cbus-toolkit cgate run <command-file>",
                    "test_ids": [
                        "rust/cbus-cgate/src/service/tests.rs::native_session_event_alias_and_quit_are_connection_local",
                    ],
                },
                "applicability_status": "unresolved",
                "applicability": {
                    "profile": "owned C-Gate 3.4.0.2001 loopback command session without a project or physical network",
                    "physical_candidate": "not_applicable_pending_receipt",
                    "physical_candidate_reason": row["physical_candidate_reason"],
                    "unresolved_profiles": ["TLS and non-loopback peers", "ACCESS/LOGIN policy variants"],
                },
                "outcome": row["outcome"],
                "preconditions": row["preconditions"],
                "preservation": row["preservation"],
                "source_refs": [
                    f"toolkit-surface.json#{public['id']}",
                    f"cgate-contract-inventory.json#{contract['id']}",
                    f"{oracle['path']}#cases",
                    "rust/cbus-cgate/src/service.rs#Service::handle",
                ],
                "differential_gap": row["differential_gap"],
                "acceptance": {
                    dimension: "unassessed"
                    for dimension in (
                        "nominal", "error", "invalid_input", "profile_variation",
                        "original_differential", "physical", "persistence_recovery",
                    )
                },
                "evidence_ids": [],
            }
        )
    return obligations


def session_differential_evidence() -> dict:
    """Accept only a current, complete cmqttd-vs-original loopback receipt."""
    from cbus_toolkit.parity import CGATE_SESSION_PILOT_IDS

    sys.path.insert(0, str(ROOT / "research"))
    from cgate_session_differential import validate_passed_receipt

    if not SESSION_DIFFERENTIAL_PATH.is_file():
        raise ValueError("Scoped cmqttd SESSION_ID differential receipt is missing")
    receipt = load_json(SESSION_DIFFERENTIAL_PATH)
    validate_passed_receipt(receipt)
    if receipt["product"] != "cmqttd":
        raise ValueError("Scoped SESSION_ID acceptance requires the cmqttd endpoint")
    obligation_ids = sorted({row["obligation_id"] for row in receipt["cases"]})
    if obligation_ids != sorted(CGATE_SESSION_PILOT_IDS.values()):
        raise ValueError("Scoped SESSION_ID differential omitted a functional obligation")
    command = receipt.get("command")
    if not isinstance(command, str) or not command.strip():
        raise ValueError("Scoped SESSION_ID differential lacks its exact command")
    record = {
        "id": "evidence:cgate-session-id-loopback-differential-v1",
        "obligation_ids": obligation_ids,
        "scope_disposition_receipts": [],
        "dimensions": ["original_differential"],
        "result": "passed",
        "test_ids": [
            f"research/cgate_session_differential.py::{row['id']}"
            for row in receipt["cases"]
        ],
        "environment": {
            "kind": "interop",
            "identity": "owned cmqttd loopback listener, synthetic PCI, disposable project and held local broker",
        },
        "oracle": {
            "target": "owned C-Gate 3.4.0.2001 native external command-session payload capture",
            "artifact_sha256": digest(NATIVE_SESSION_PATH),
        },
        "source_revision": receipt["source_revision"],
        "command": command,
        "exit_code": 0,
        "report_verification": {
            "format": "cgate-session-differential-v2",
            "path": SESSION_DIFFERENTIAL_PATH.relative_to(ROOT).as_posix(),
        },
        "artifacts": [
            {
                "role": "input",
                "path": NATIVE_SESSION_SOURCE_REF,
                "sha256": digest(NATIVE_SESSION_PATH),
            },
            {
                "role": "report",
                "path": SESSION_DIFFERENTIAL_PATH.relative_to(ROOT).as_posix(),
                "sha256": digest(SESSION_DIFFERENTIAL_PATH),
            },
        ],
        "skips": [],
    }
    record["record_sha256"] = canonical_digest(record)
    return record


def build() -> tuple[dict, dict]:
    surface = load_json(SURFACE_PATH)
    executable = executable_surface()
    ledger = load_json(LEDGER_PATH)
    work_items, ledger_packages = roadmap_maps()
    ledger_ids = {feature["id"] for feature in ledger["features"]}
    sys.path.insert(0, str(ROOT / "src"))
    from cbus_toolkit.device_dialogs import list_dialogs
    from cbus_toolkit.parity import (
        CGATE_SESSION_PILOT_IDS,
        WORK_ITEM_IDS,
        cgate_path_obligation_id,
    )

    roadmap_work_item_ids = {
        work_item_id
        for package_work_items in work_items.values()
        for work_item_id in package_work_items
    }
    if roadmap_work_item_ids != WORK_ITEM_IDS:
        raise ValueError(
            "Roadmap work items differ from the authoritative parity roster"
        )

    dialog_ledger = {
        row["dialog_id"]: row["ledger_id"] for row in list_dialogs()
    }
    primary_paths, supplement_paths = capability_paths()
    cgate_contracts = cgate_contract_inventory(primary_paths, supplement_paths)
    contract_by_path = {
        contract["path"]: contract for contract in cgate_contracts["contracts"]
    }
    cgate_path_scopes: list[tuple[dict, dict]] = []
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
        if row.get("id") != f"help-unindexed:{row['file']}":
            raise ValueError(f"Unindexed Toolkit help ID changed: {row['file']}")
        if row.get("review_status") != "static_markup_reviewed_runtime_unassessed":
            raise ValueError(f"Unindexed Toolkit help review status changed: {row['file']}")
        scope_items.append(
            {
                "id": f"scope:unindexed:{row['file']}",
                "kind": "unindexed_html",
                "source_id": row["id"],
                "source_sha256": row["sha256"],
                "static_role": row["reviewed_role"],
                "review_status": row["review_status"],
                "source_path": row["source_path"],
                "source_asset_sha256": canonical_digest(row["asset_sources"]),
                "missing_html_targets": row["missing_html_targets"],
                "obligation_ids": obligation_ids(["toolkit-surface-census"]),
                "disposition": "pending_analysis",
            }
        )
    for command in surface["public_commands"]:
        scope = {
            "id": f"scope:public-command:{command['id']}",
            "kind": "public_command",
            "source_id": command["id"],
            "source_sha256": command["source"]["syntax_sha256"],
            "obligation_ids": obligation_ids(["cgate-command-transport"]),
            "disposition": "provisional_obligation",
        }
        if command["command"] in CGATE_SESSION_PILOT_IDS:
            scope["source_anchor"] = command["source"]
        scope_items.append(scope)
    for kind, paths in (("cgate_primary_path", primary_paths), ("cgate_supplement_path", supplement_paths)):
        for row in paths:
            path_id = sha256(row["path"].encode("utf-8")).hexdigest()[:16]
            contract = contract_by_path[row["path"]]
            scope = {
                "id": f"scope:{kind}:{path_id}",
                "kind": kind,
                "source_id": row["path"],
                "routing_class": row["routing_class"],
                "contract_id": contract["id"],
                "contract_sha256": contract["contract_sha256"],
                "contract_axes_sha256": contract["axes_sha256"],
                "contract_axes": contract["axes"],
                "obligation_ids": [
                    "ledger:cgate-command-transport",
                    cgate_path_obligation_id(row["path"]),
                ],
                "disposition": "provisional_obligation",
            }
            scope_items.append(scope)
            cgate_path_scopes.append((scope, contract))
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

    cgate_work_items = next(
        item["work_item_ids"]
        for item in obligations
        if item["id"] == "ledger:cgate-command-transport"
    )
    for scope, contract in cgate_path_scopes:
        path = scope["source_id"]
        obligations.append(
            {
                "id": cgate_path_obligation_id(path),
                "kind": "cgate_path",
                "ledger_id": "cgate-command-transport",
                "work_item_ids": sorted(set(cgate_work_items) | {"P0.03"}),
                "source_scope_item_id": scope["id"],
                "source_id": path,
                "contract_id": contract["id"],
                "contract_sha256": contract["contract_sha256"],
                "definition_status": "provisional",
                # A dispatch route is not a complete selector/state/effect implementation.
                "implementation_status": "in_progress",
                "implementation_basis": "route_reachable_contract_incomplete",
                "applicability_status": "unresolved",
                "outcome": (
                    f"Clients invoking {path} receive the specified responses, events, "
                    "state changes and physical effects for every applicable selector "
                    "and session state."
                ),
                "source_refs": [
                    f"cgate-contract-inventory.json#{contract['id']}",
                    f"capability_matrix.rs#{path}",
                    "capabilities.json#cgate-command-transport",
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

    session_evidence = session_differential_evidence()
    scope_by_id = {item["id"]: item for item in scope_items}
    for function in functional_pilot(surface, contract_by_path):
        for scope_id in function["source_scope_item_ids"]:
            scope_by_id[scope_id]["obligation_ids"].append(function["id"])
        if function["id"] in session_evidence["obligation_ids"]:
            function["acceptance"]["original_differential"] = "accepted"
            function["evidence_ids"].append(session_evidence["id"])
        obligations.append(function)

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
        {
            "id": "cgate_selector_state_effect_contracts",
            "count": by_kind["cgate_primary_path"] + by_kind["cgate_supplement_path"],
            "resolved": False,
            "contract_inventory_version": cgate_contracts["inventory_version"],
            "axis_status": cgate_contracts["counts"]["axis_status"],
            "subaxis_status": cgate_contracts["counts"]["subaxis_status"],
        },
        {"id": "catalogue_device_firmware_profiles", "count": surface["counts"]["catalogue_firmware_revisions"], "resolved": False},
    ]
    evidence = {
        "schema_version": 1,
        "target": ledger["target"],
        "records": [session_evidence],
    }
    evidence_raw = (json.dumps(evidence, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    register = {
        "schema_version": 1,
        "target": ledger["target"],
        "denominator_version": "provisional-2026-09-28.1",
        "census_complete": False,
        "purpose": "Provisional exhaustive source accounting; not yet a deduplicated functional denominator or acceptance claim.",
        "source_digests": {
            "toolkit_surface": digest(SURFACE_PATH),
            "unindexed_help_review": sha256(
                json.dumps(surface["unindexed_html"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
            "toolkit_executable_surface": digest(EXECUTABLE_SURFACE_PATH),
            "toolkit_executable_binary": executable["sources"]["executable"]["sha256"],
            "toolkit_map": executable["sources"]["map"]["sha256"],
            "feature_ledger": digest(LEDGER_PATH),
            "cgate_capability_matrix": digest(MATRIX_PATH),
            "cgate_contract_inventory": digest(CGATE_CONTRACT_PATH),
            "cgate_session_native_acceptance": digest(NATIVE_SESSION_PATH),
            "functional_obligation_pilot": digest(FUNCTIONAL_PILOT_PATH),
            "cgate_session_differential_cmqttd": digest(SESSION_DIFFERENTIAL_PATH),
            "roadmap": digest(ROADMAP_PATH),
        },
        "evidence_bundle_sha256": sha256(evidence_raw).hexdigest(),
        "work_item_ids": sorted(WORK_ITEM_IDS),
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
