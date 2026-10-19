"""Map every main-menu leaf to its implemented CLI coverage or gap.

The committed document pins all 22 leaves of the ``main_menu_tree`` in
``docs/toolkit-surface.json`` in surface order. Each leaf resolves to one of:

- ``mapped``: a menu option covered by an implemented CLI capability
  (native project operations via ``native-cgate3-projects``, C-Gate
  connect/disconnect via ``cgate-command-transport``),
- ``pending``: preference tabs, interface setup, network discovery, project
  repair and options with no certain CLI mapping, with an explicit reason.

This is scope routing, not acceptance; mapped rows name the implementing
capability, pending rows name their gap.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SURFACE_PATH = ROOT / "docs" / "toolkit-surface.json"
CAPABILITIES_PATH = ROOT / "src" / "cbus_toolkit" / "capabilities.json"
OUTPUT_PATH = ROOT / "docs" / "toolkit-menu-option-map.json"

FORMAT = "cbus-toolkit-menu-option-map-v1"
SCHEMA_VERSION = 1

#: Menu leaves covered by implemented capabilities, by help topic.
MAPPED_OPTIONS = {
    # Native project operations: `cbus-toolkit cgate project ...`.
    "help:6821.htm": ("project_operation", "native-cgate3-projects"),
    "help:6822.htm": ("project_operation", "native-cgate3-projects"),
    "help:6836.htm": ("project_operation", "native-cgate3-projects"),
    "help:6837.htm": ("project_operation", "native-cgate3-projects"),
    # C-Gate session connect/disconnect over TCP/TLS/tagged framing.
    "help:6803.htm": ("cgate_connection", "cgate-command-transport"),
    "help:6807.htm": ("cgate_connection", "cgate-command-transport"),
    "help:6808.htm": ("cgate_connection", "cgate-command-transport"),
    "help:6804.htm": ("cgate_connection", "cgate-command-transport"),
    "help:6805.htm": ("cgate_connection", "cgate-command-transport"),
}

REASONS = {
    "preference_scope": "A preference tab owned by the unfinished preferences workflow; preference runtime behavior remains unassessed.",
    "interface_setup": "Interface setup owned by the unfinished interface discovery workflow; physical interface acceptance remains unassessed.",
    "network_discovery": "Network discovery owned by the unfinished scan/commissioning workflows; discovery acceptance remains unassessed.",
    "project_repair": "Project repair owned by the unfinished native repair workflow; repair acceptance remains unassessed.",
    "uncertain_cli_mapping": "No certain CLI command maps to this menu option; claiming coverage would be speculation.",
    "empty_menu_branch": "A menu branch with no documented leaf options; its contents remain unassessed.",
}

VENDOR_INPUTS = ("surface", "capabilities")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_committed() -> dict:
    return load_json(OUTPUT_PATH)


def committed_inputs() -> dict[str, dict]:
    return {
        "surface": {"path": "docs/toolkit-surface.json", "sha256": digest(SURFACE_PATH)},
        "capabilities": {
            "path": "src/cbus_toolkit/capabilities.json",
            "sha256": digest(CAPABILITIES_PATH),
        },
    }


def leaf_roster(tree: dict) -> list[tuple[str, str]]:
    leaves: list[tuple[str, str]] = []

    def walk(node: dict) -> None:
        children = node.get("children", [])
        if not children:
            leaves.append((node["topic_id"], node.get("title", "")))
        else:
            for child in children:
                walk(child)

    walk(tree)
    return leaves


def pending_reason(topic_id: str, title: str) -> str:
    if "Preference" in title or title.endswith("tab"):
        return "preference_scope"
    if "interface" in title.lower():
        return "interface_setup"
    if "Find C-Bus Networks" in title:
        return "network_discovery"
    if "Repair" in title:
        return "project_repair"
    if title in ("Refresh option", "Import projects option", "Export projects option"):
        return "uncertain_cli_mapping"
    if title.endswith("menu options"):
        return "empty_menu_branch"
    raise ValueError(f"Menu leaf has no triage rule: {topic_id} {title!r}")


def build_document(
    menu_tree: dict, capability_status: dict[str, str]
) -> dict:
    rows = []
    for topic_id, title in leaf_roster(menu_tree):
        if topic_id in MAPPED_OPTIONS:
            kind, feature = MAPPED_OPTIONS[topic_id]
            if capability_status.get(feature) != "implemented":
                raise ValueError(f"Mapped menu leaf names an unfinished capability: {topic_id}")
            rows.append({
                "leaf_id": topic_id,
                "title": title,
                "status": "mapped",
                "kind": kind,
                "capability": feature,
                "reasons": [],
            })
        else:
            code = pending_reason(topic_id, title)
            rows.append({
                "leaf_id": topic_id,
                "title": title,
                "status": "pending",
                "kind": "pending",
                "reasons": [{"code": code, "detail": REASONS[code], "subjects": [title]}],
            })
    counts: dict[str, object] = {
        "leaves": len(rows),
        "mapped": sum(row["status"] == "mapped" for row in rows),
        "pending": sum(row["status"] == "pending" for row in rows),
    }
    reason_counts: dict[str, int] = {}
    for row in rows:
        for reason in row["reasons"]:
            reason_counts[reason["code"]] = reason_counts.get(reason["code"], 0) + 1
    counts["pending_reasons"] = dict(sorted(reason_counts.items()))
    return {
        "schema_version": SCHEMA_VERSION,
        "format": FORMAT,
        "target": "C-Bus Toolkit 1.18.0.2754",
        "purpose": (
            "Deterministic map from each main-menu leaf to its implemented "
            "CLI capability, or its explicit gap."
        ),
        "inputs": committed_inputs(),
        "leaves": rows,
        "counts": counts,
    }


def validate_document(document: dict) -> dict:
    if document.get("schema_version") != SCHEMA_VERSION or document.get("format") != FORMAT:
        raise ValueError("Menu option map has an unknown schema or format")
    inputs = document.get("inputs")
    if not isinstance(inputs, dict) or sorted(inputs) != sorted(VENDOR_INPUTS):
        raise ValueError("Menu option map has incomplete or unexpected inputs")
    for name in VENDOR_INPUTS:
        entry = inputs[name]
        actual = digest(ROOT / entry["path"])
        if entry["sha256"] != actual:
            raise ValueError(f"Menu option map input changed: {name}")
    leaves = document.get("leaves")
    if not isinstance(leaves, list) or not leaves:
        raise ValueError("Menu option map has no leaves")
    seen = set()
    for row in leaves:
        leaf_id = row.get("leaf_id")
        if leaf_id in seen:
            raise ValueError(f"Duplicate menu leaf: {leaf_id}")
        seen.add(leaf_id)
        if row.get("status") == "mapped":
            if row.get("reasons"):
                raise ValueError(f"Mapped menu leaf carries reasons: {leaf_id}")
            if row["kind"] not in ("project_operation", "cgate_connection"):
                raise ValueError(f"Mapped menu leaf has an unknown kind: {leaf_id}")
            if not isinstance(row.get("capability"), str) or not row["capability"]:
                raise ValueError(f"Mapped menu leaf names no capability: {leaf_id}")
        elif row.get("status") == "pending":
            reasons = row.get("reasons")
            if not reasons:
                raise ValueError(f"Pending menu leaf names no reason: {leaf_id}")
            for reason in reasons:
                if set(reason) != {"code", "detail", "subjects"}:
                    raise ValueError(f"Pending menu leaf has a malformed reason: {leaf_id}")
                if reason["detail"] != REASONS.get(reason["code"]):
                    raise ValueError(f"Pending menu leaf has an unknown reason: {leaf_id}")
                if not reason["subjects"]:
                    raise ValueError(f"Pending menu leaf reason names no subject: {leaf_id}")
        else:
            raise ValueError(f"Menu leaf has an unknown status: {leaf_id}")
    counts = document.get("counts", {})
    if counts.get("leaves") != len(leaves):
        raise ValueError("Menu option map counts disagree with its roster")
    if counts.get("mapped", 0) + counts.get("pending", 0) != len(leaves):
        raise ValueError("Menu option map status counts disagree with its roster")
    return document


def render(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def live_capabilities() -> dict[str, str]:
    return {
        feature["id"]: feature["status"]
        for feature in load_json(CAPABILITIES_PATH)["features"]
    }
