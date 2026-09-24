"""Differential acceptance harness scaffolding (Phase 4).

Ledger/census + fresh-wheel + differential harness scaffolding only.

This module does NOT claim Toolkit parity. It loads the authoritative
38-area ledger in ``capabilities.json`` (``census_complete: false``) and
exposes an explicitly empty/red differential matrix: every ledger area maps
to unassessed workflow and negative-path slots with no accepted evidence.

No endpoints, credentials, or vendor specifications are invented or read
here. Reserved ledger fields are preserved verbatim.
"""
from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path

DIFFERENTIAL_STATUSES = ("pending", "unassessed")

# Per-area workflow/negative-path slot names. Slots exist so future phases
# can record independent original-Toolkit comparisons; they start empty.
WORKFLOW_SLOTS = ("nominal_workflow", "error_path", "device_firmware_variation")
NEGATIVE_SLOTS = ("invalid_input", "unsupported_profile", "hardware_divergence")


def ledger_path_text() -> str:
    return files("cbus_toolkit").joinpath("capabilities.json").read_text(
        encoding="utf-8"
    )


def ledger_path() -> Path:
    # Retained for backwards compatibility; prefer ledger_path_text() so
    # zip/zipapp fresh-wheel installs keep working (Traversable is not
    # always a real filesystem Path).
    return Path(str(files("cbus_toolkit").joinpath("capabilities.json")))


def load_ledger(path: Path | None = None) -> dict:
    if path is not None:
        source = Path(path)
        context = str(source)
        try:
            with source.open("r", encoding="utf-8") as handle:
                ledger = json.load(handle)
        except FileNotFoundError as exc:
            raise ValueError(f"Ledger not found: {context}") from exc
        except json.JSONDecodeError as exc:
            raise ValueError(f"Ledger is not valid JSON: {context}") from exc
    else:
        context = "cbus_toolkit/capabilities.json"
        try:
            ledger = json.loads(ledger_path_text())
        except FileNotFoundError as exc:
            raise ValueError(f"Ledger not found: {context}") from exc
        except json.JSONDecodeError as exc:
            raise ValueError(f"Ledger is not valid JSON: {context}") from exc
    if not isinstance(ledger, dict):
        raise ValueError("Ledger must be a JSON object")
    if "features" not in ledger or not isinstance(ledger["features"], list):
        raise ValueError("Ledger requires a 'features' array")
    # Preserve reserved fields; do not mutate census_complete here.
    return ledger


def ledger_area_ids(ledger: dict) -> list[str]:
    features = ledger.get("features")
    if not isinstance(features, list):
        raise ValueError("Ledger requires a 'features' array")
    seen: set[str] = set()
    ids: list[str] = []
    for entry in features:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            raise ValueError("Every ledger feature requires a string 'id'")
        area_id = entry["id"]
        if area_id in seen:
            raise ValueError(f"Duplicate ledger area id: {area_id}")
        seen.add(area_id)
        ids.append(area_id)
    return ids


def build_matrix(ledger: dict | None = None) -> dict:
    ledger = ledger if ledger is not None else load_ledger()
    features = ledger.get("features")
    if not isinstance(features, list):
        raise ValueError("Ledger requires a 'features' array")
    areas: dict[str, dict] = {}
    for entry in features:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            raise ValueError("Every ledger feature requires a string 'id'")
        area_id = entry["id"]
        if area_id in areas:
            raise ValueError(f"Duplicate ledger area id: {area_id}")
        status = entry.get("status", "unknown")
        if not isinstance(status, str):
            raise ValueError(f"Ledger area {area_id} has non-string 'status'")
        limits = entry.get("limits", "")
        if not isinstance(limits, str):
            raise ValueError(f"Ledger area {area_id} has non-string 'limits'")
        evidence = entry.get("evidence", [])
        if not isinstance(evidence, list) or not all(
            isinstance(item, str) for item in evidence
        ):
            raise ValueError(
                f"Ledger area {area_id} has non-string-list 'evidence'"
            )
        areas[area_id] = {
            "ledger_id": area_id,
            "ledger_status": status,
            "ledger_limits": limits,
            "ledger_evidence": list(evidence),
            # Differential state: always starts red/empty. No accepted
            # Toolkit comparisons exist yet.
            "differential_status": DIFFERENTIAL_STATUSES[0],
            "workflows": {slot: DIFFERENTIAL_STATUSES[1] for slot in WORKFLOW_SLOTS},
            "negative_paths": {
                slot: DIFFERENTIAL_STATUSES[1] for slot in NEGATIVE_SLOTS
            },
            "evidence_paths": [],
        }
    return {
        "census_complete": ledger.get("census_complete") is True,
        "ledger_areas": len(areas),
        "accepted_areas": 0,
        "complete": False,
        "areas": areas,
    }


def area_status(matrix: dict, ledger_id: str) -> dict:
    try:
        entry = matrix["areas"][ledger_id]
    except KeyError as exc:
        raise KeyError(f"Unknown ledger area: {ledger_id}") from exc
    return {
        "ledger_id": entry["ledger_id"],
        "ledger_status": entry["ledger_status"],
        "ledger_limits": entry["ledger_limits"],
        "ledger_evidence": list(entry["ledger_evidence"]),
        "differential_status": entry["differential_status"],
        "workflows": dict(entry["workflows"]),
        "negative_paths": dict(entry["negative_paths"]),
        "evidence_paths": list(entry["evidence_paths"]),
    }


def summary(matrix: dict) -> dict:
    return {
        "ledger_areas": matrix["ledger_areas"],
        "accepted_areas": matrix["accepted_areas"],
        "complete": matrix["complete"],
        "census_complete": matrix["census_complete"],
    }


def evidence_paths_for(matrix: dict, ledger_id: str) -> list[str]:
    return list(area_status(matrix, ledger_id)["evidence_paths"])
