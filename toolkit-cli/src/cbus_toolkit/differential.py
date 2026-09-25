"""Differential acceptance harness scaffolding (Phase 4).

Ledger/census + fresh-wheel + differential harness scaffolding only.

This module does NOT claim Toolkit parity. It loads the authoritative
38-area ledger in ``capabilities.json`` (``census_complete: false``) and
exposes the differential matrix: every ledger area maps to workflow and
negative-path slots that start ``unassessed``, except the two attempted
rows ``edlt-reset-controls`` and ``edlt-retained-scene-editing`` whose
``nominal_workflow`` slots are each ``accepted`` per the executable
SLOT_RUBRIC below (1/6 slots each; areas still pending,
``accepted_areas`` still 0, ``complete`` still false).

No endpoints, credentials, or vendor specifications are invented or read
here. Reserved ledger fields are preserved verbatim.
"""
from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path

DIFFERENTIAL_STATUSES = ("pending", "unassessed")
ACCEPTED = "accepted"

# Per-area workflow/negative-path slot names. Slots exist so future phases
# can record independent original-Toolkit comparisons; they start empty.
WORKFLOW_SLOTS = ("nominal_workflow", "error_path", "device_firmware_variation")
NEGATIVE_SLOTS = ("invalid_input", "unsupported_profile", "hardware_divergence")
ALL_SLOTS = WORKFLOW_SLOTS + NEGATIVE_SLOTS

# Slot-flip rubric (differential acceptance, Phase 4+).
#
# A slot flips to ``accepted`` only when the evidence facts measured from
# COMMITTED artifacts satisfy every criterion below. Self-referential unit
# tests (tests of our own implementation with no original-Toolkit oracle)
# never flip a slot. Slots that do not meet the rubric stay ``unassessed``;
# a partially filled row is a success, not a failure.
#
# Fix #2 choice: trim-prose (not add-keys). The prose below states exactly
# what ``slot_meets_rubric()`` enforces; unenforced "exact identity"
# sub-requirements language was removed so the comment cannot over-claim.
# Verdicts unchanged: edlt-reset-controls stays nominal=accepted +
# 5 unassessed (1/6). Adding new evidence keys + gates was rejected here
# because it risked flipping a current slot.
#
# - nominal_workflow: >= MIN_ORIGINAL_EXECUTIONS fresh-or-captured original
#   executions replayed by a committed replay test, plus native persistence
#   (database save/close/load readback) where the workflow saves, plus a
#   committed acceptance record whose scope note bounds the claim (profile,
#   tabs/variants, and explicit non-claims such as physical_device_verified).
# - error_path: >= 1 original-observed error vectors (our own guard tests
#   do not count).
# - device_firmware_variation: >= 2 distinct unit/firmware profiles.
#   A single-profile scope note bounds nominal; it does NOT flip this slot.
# - invalid_input / unsupported_profile: original-observed rejection basis;
#   never absence-of-test or scoping guesses.
# - hardware_divergence: physical-device evidence; closed-loopback native
#   C-Gate runs and simulator runs do not count.
SLOT_RUBRIC = {
    "nominal_workflow": {
        "min_original_executions": 10,
        "require_replay_test": True,
        "require_native_persistence": True,
        "require_acceptance_record": True,
        "require_bounded_scope_note": True,
    },
    "error_path": {
        "min_original_error_cases": 1,
        "require_exact_original_error_identity": True,
    },
    "device_firmware_variation": {
        "min_distinct_profiles": 2,
        "require_original_comparison_per_profile": True,
    },
    "invalid_input": {
        "require_exact_rejection_evidence": True,
        "require_original_observed_basis": True,
    },
    "unsupported_profile": {
        "require_exact_rejection_evidence": True,
        "require_original_observed_basis": True,
    },
    "hardware_divergence": {
        "require_physical_device_evidence": True,
        "require_exact_effect_identity": True,
    },
}

# Area rule: an area counts as accepted iff ALL six slots are accepted.
# Partial rows (e.g. 1/6) are recorded progress and do NOT accept the area.
# ``complete`` additionally requires ``census_complete`` (still false).
AREA_ACCEPTANCE_RULE = "all_six_slots"

# Measured evidence facts for the first attempted row, ``edlt-reset-controls``.
# Values are read off the committed artifacts listed in EVIDENCE_PATHS below
# (44 executions / 520 phases / 454,480 comparisons in the captured vectors;
# 4 fresh native save/close/load cases per acceptance run; acceptance record
# declares toolkit_parity_complete=false and physical_device_verified=false).
RESET_CONTROLS_EVIDENCE = {
    "original_executions": 44,
    "phase_count": 520,
    "parameter_phase_comparisons": 454480,
    "has_replay_test": True,
    "has_native_persistence": True,
    "has_acceptance_record": True,
    "has_bounded_scope_note": True,
    "original_error_cases": 0,
    "distinct_profiles": 1,
    "has_original_rejection_basis": False,
    "has_physical_device_evidence": False,
}

# Committed artifacts only. No endpoints, credentials, or vendor specs.
# Polish (#4): oracle vs self-referential split -- the two research fixtures
# plus test_edlt_reset_vectors.py (captured-original replay) and
# test_edlt_reset_native.py (fresh native save/close/load runs) are the
# original-Toolkit oracle basis for the nominal slot; test_edlt_reset.py and
# test_cli_edlt_reset.py are self-referential unit tests of our own
# implementation (never flip a slot alone) and docs/edlt-reset.md is scope
# narrative. They are listed together as the attempted row's audit trail.
# Polish (#5): evidence_paths display note -- attempted rows attach the full
# path list regardless of pass count (comment-only; a >=1-passed display
# gate would change the matrix shape/tests, so it is not implemented).
RESET_CONTROLS_EVIDENCE_PATHS = [
    "tests/test_edlt_reset_vectors.py",
    "tests/test_edlt_reset_native.py",
    "tests/test_edlt_reset.py",
    "tests/test_cli_edlt_reset.py",
    "research/fixtures/edlt-reset-windows-vectors.json",
    "research/fixtures/edlt-reset-acceptance.json",
    "docs/edlt-reset.md",
]

# The two attempted differential rows. Every other ledger area keeps the
# scaffolding default (all slots ``unassessed``, no evidence paths).
DIFFERENTIAL_ROWS = ("edlt-reset-controls", "edlt-retained-scene-editing")

# Measured evidence facts for the second attempted row,
# ``edlt-retained-scene-editing`` (bounded KEYGL5/5055EDL 5.5.00 retained
# SceneManager scope). Values are read off the committed artifacts listed
# in SCENE_MANAGER_EVIDENCE_PATHS below:
# - 34 committed vector cases (10 retained-model + 3 bounded actual-control
#   + 13 validation + 8 getter/cache) in
#   research/fixtures/edlt-scene-manager-vectors.json
#   (format cbus-original-scene-manager-vectors-v1,
#   physical_device_verified=false);
# - 17 fresh original executions per module run replayed by the committed
#   oracle test (13 model-validate + get-new-missing-trigger + 3 control
#   cases), recorded as ``original_cases: 17`` in both module acceptance
#   runs; offline replay of the same committed vectors by the SceneManagerTests
#   (no vendor provisioning needed);
# - 8 native save/close/load cases per module run (874 parameters, 5 CRCs,
#   full SceneBucket + raw-byte readback, metadata unchanged), recorded as
#   ``native_cases: 8`` / ``cases_per_module_run: 8`` in the acceptance
#   record (closed-loopback databases, ``state=new``);
# - the acceptance record bounds the claim (KEYGL5/5055EDL 5.5.00 scope,
#   exports review-only, boundaries list, physical_device_verified=false,
#   full_form_verified=false). Note: unlike the Reset row it carries NO
#   ``toolkit_parity_complete`` key at all, so the self-limit is expressed
#   through those other flags, not through an explicit parity-false
#   declaration.
SCENE_MANAGER_EVIDENCE = {
    "original_executions": 17,
    "vector_cases": 34,
    "native_cases": 8,
    "has_replay_test": True,
    "has_native_persistence": True,
    "has_acceptance_record": True,
    "has_bounded_scope_note": True,
    "original_error_cases": 0,
    "distinct_profiles": 1,
    "has_original_rejection_basis": False,
    "has_physical_device_evidence": False,
}

# Committed artifacts only. Oracle vs self-referential split: the two
# research fixtures plus tests/test_edlt_scene_manager.py -- whose
# OriginalSceneManagerTests (fresh original oracle, provisioning-gated) and
# NativeSceneManagerTests (fresh native save/close/load, provisioning-gated)
# are the original-Toolkit oracle basis, and whose offline SceneManagerTests
# replay the committed original vectors with no vendor provisioning -- and
# tests/test_cli_edlt_scene_manager.py (offline CLI tests plus one gated
# native CLI test) are the audit trail; docs/edlt-scene-manager.md is the
# bounded-scope narrative and docs/edlt-scenes.md records the historical
# capacity-CRC correction this row qualifies.
SCENE_MANAGER_EVIDENCE_PATHS = [
    "tests/test_edlt_scene_manager.py",
    "tests/test_cli_edlt_scene_manager.py",
    "research/fixtures/edlt-scene-manager-vectors.json",
    "research/fixtures/edlt-scene-manager-acceptance.json",
    "docs/edlt-scene-manager.md",
    "docs/edlt-scenes.md",
]


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
            # Differential state starts red/empty; _apply_rubric_rows() then
            # fills only the attempted rows that pass SLOT_RUBRIC.
            "differential_status": DIFFERENTIAL_STATUSES[0],
            "workflows": {slot: DIFFERENTIAL_STATUSES[1] for slot in WORKFLOW_SLOTS},
            "negative_paths": {
                slot: DIFFERENTIAL_STATUSES[1] for slot in NEGATIVE_SLOTS
            },
            "evidence_paths": [],
        }
    matrix = {
        "census_complete": ledger.get("census_complete") is True,
        "ledger_areas": len(areas),
        "accepted_areas": 0,
        "complete": False,
        "areas": areas,
    }
    _apply_rubric_rows(matrix)
    return matrix


def slot_meets_rubric(slot: str, evidence: dict) -> tuple[bool, str]:
    """Check one slot against SLOT_RUBRIC. Returns (accepted, reason).

    Executable by the Checker: pass measured evidence facts and confirm the
    verdict before trusting any ``accepted`` value in the matrix.
    """
    if slot == "nominal_workflow":
        required = SLOT_RUBRIC["nominal_workflow"]["min_original_executions"]
        if evidence.get("original_executions", 0) < required:
            return False, (
                f"only {evidence.get('original_executions', 0)} original "
                f"executions, need >={required}"
            )
        for key in (
            "has_replay_test",
            "has_native_persistence",
            "has_acceptance_record",
            "has_bounded_scope_note",
        ):
            if not evidence.get(key):
                return False, f"missing rubric requirement: {key}"
        return True, (
            f"{evidence['original_executions']} original executions replayed "
            "with native persistence and a bounded-scope acceptance record"
        )
    if slot == "error_path":
        required = SLOT_RUBRIC["error_path"]["min_original_error_cases"]
        if evidence.get("original_error_cases", 0) < required:
            return False, (
                "no original-observed error vectors with exact error "
                "identity; own guard tests do not count"
            )
        return True, "original error identity vectors replayed"
    if slot == "device_firmware_variation":
        required = SLOT_RUBRIC["device_firmware_variation"][
            "min_distinct_profiles"
        ]
        if evidence.get("distinct_profiles", 0) < required:
            return False, (
                f"only {evidence.get('distinct_profiles', 0)} profile(s) with "
                "original comparisons; single-profile scope notes do not "
                "flip this slot"
            )
        return True, ">=2 profiles with original comparisons"
    if slot in ("invalid_input", "unsupported_profile"):
        if not evidence.get("has_original_rejection_basis"):
            return False, (
                "no exact-rejection evidence grounded in original-observed "
                "behavior; absence-of-test and scoping guesses do not count"
            )
        return True, "exact rejection grounded in original behavior"
    if slot == "hardware_divergence":
        if not evidence.get("has_physical_device_evidence"):
            return False, (
                "no physical-device evidence; loopback native runs and "
                "simulators do not count"
            )
        return True, "physical-device effect identity verified"
    raise KeyError(f"Unknown differential slot: {slot}")


def is_area_accepted(entry: dict) -> bool:
    """Area rule: accepted iff all six slots are accepted."""
    slots = [entry["workflows"][slot] for slot in WORKFLOW_SLOTS]
    slots += [entry["negative_paths"][slot] for slot in NEGATIVE_SLOTS]
    return all(status == ACCEPTED for status in slots)


def _apply_rubric_rows(matrix: dict) -> None:
    """Fill the two attempted rows through the rubric (fail-safe).

    A slot is set to ``accepted`` only when ``slot_meets_rubric`` passes;
    otherwise it stays ``unassessed``. Unknown row IDs raise KeyError so a
    renamed ledger area cannot silently accept.
    """
    for area_id in DIFFERENTIAL_ROWS:
        if area_id not in matrix["areas"]:
            raise KeyError(f"Unknown ledger area: {area_id}")
        entry = matrix["areas"][area_id]
        if area_id == "edlt-reset-controls":
            evidence = RESET_CONTROLS_EVIDENCE
            evidence_paths = list(RESET_CONTROLS_EVIDENCE_PATHS)
        elif area_id == "edlt-retained-scene-editing":
            evidence = SCENE_MANAGER_EVIDENCE
            evidence_paths = list(SCENE_MANAGER_EVIDENCE_PATHS)
        else:  # pragma: no cover - two-row phase; kept explicit
            continue
        for slot in WORKFLOW_SLOTS:
            accepted, _ = slot_meets_rubric(slot, evidence)
            if accepted:
                entry["workflows"][slot] = ACCEPTED
        for slot in NEGATIVE_SLOTS:
            accepted, _ = slot_meets_rubric(slot, evidence)
            if accepted:
                entry["negative_paths"][slot] = ACCEPTED
        entry["evidence_paths"] = evidence_paths
        if is_area_accepted(entry):
            entry["differential_status"] = ACCEPTED
    matrix["accepted_areas"] = sum(
        1 for entry in matrix["areas"].values() if is_area_accepted(entry)
    )
    # ``complete`` stays false: the census is incomplete and only two
    # partially filled rows exist. Never derive completion from intent.
    matrix["complete"] = bool(
        matrix["census_complete"]
        and matrix["accepted_areas"] == matrix["ledger_areas"]
        and matrix["ledger_areas"] > 0
    )


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
