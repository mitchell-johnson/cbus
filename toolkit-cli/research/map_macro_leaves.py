"""Map every macro-reference leaf to its implemented preset, micro-function or gap.

The committed document pins all 179 leaves of the ``macro_reference`` tree in
``docs/toolkit-surface.json`` in surface order. Each leaf resolves to one of:

- ``preset``: a wired template leaf implemented by ``macros.PRESETS``,
- ``custom``: the wired ``<Custom>`` leaf for non-matching stage vectors,
- ``micro_function``: a wired micro-function leaf in the
  ``TfrmKeyMicroFunctions`` 0..15 domain (``macros.MICRO_FUNCTIONS``),
- ``pending``: shutter, bistable, schedule-move, scene, fan, occupancy,
  wireless, AUX and other-family leaves outside the admitted classic
  key-macro scope, with an explicit reason code.

This is scope routing, not acceptance; mapped rows name the implementing
preset or micro-function code, pending rows name their gap.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SURFACE_PATH = ROOT / "docs" / "toolkit-surface.json"
MACROS_PATH = ROOT / "src" / "cbus_toolkit" / "macros.py"
OUTPUT_PATH = ROOT / "docs" / "toolkit-macro-leaf-map.json"

FORMAT = "cbus-toolkit-macro-leaf-map-v1"
SCHEMA_VERSION = 1

#: Wired ``<Custom>`` leaf: any stage vector outside the preset groups.
CUSTOM_TOPIC = "help:975.htm"

#: Wired micro-function leaves by help topic to ``macros.MICRO_FUNCTIONS`` code.
MICRO_WIRED_TOPICS = {
    "help:977.htm": "idle",
    "help:978.htm": "store1",
    "help:979.htm": "downcycle",
    "help:980.htm": "memory_toggle2",
    "help:981.htm": "down",
    "help:982.htm": "up",
    "help:983.htm": "recall1",
    "help:984.htm": "recall2",
    "help:985.htm": "retrigger_timer",
    "help:986.htm": "start_timer",
    "help:987.htm": "ramp_off",
    "help:988.htm": "ramp_recall1",
    "help:989.htm": "toggle",
    "help:990.htm": "on",
    "help:991.htm": "off",
    "help:992.htm": "end_ramp",
}

REASONS = {
    "wireless_input": "A wireless macro leaf outside the admitted classic wired scope; wireless inputs remain unassessed.",
    "shutter": "A shutter macro leaf outside the admitted classic key-macro scope; shutter configuration remains unassessed.",
    "bistable": "A bistable macro leaf outside the admitted classic key-macro scope; bistable configuration remains unassessed.",
    "schedule_move": "A time-driven move leaf outside the admitted classic key-macro scope; schedule behavior remains unassessed.",
    "scene_widget": "A scene macro leaf outside the admitted classic key-macro scope; scene widgets remain unassessed.",
    "fan": "A fan macro leaf outside the admitted classic key-macro scope; fan configuration remains unassessed.",
    "occupancy": "An occupancy macro leaf outside the admitted classic key-macro scope; occupancy configuration remains unassessed.",
    "aux_subset": "An AUX-subset template leaf with no admitted preset; AUX templates remain unassessed.",
    "other_key_family": "A non-classic key-family template leaf outside the admitted classic scope; other families remain unassessed.",
    "special_micro_function": "A scene, block or POT micro-function leaf outside the 0..15 classic domain; specialist micro-functions remain unassessed.",
    "guide_only": "A guide leaf describing interaction rather than a selectable macro function.",
}

VENDOR_INPUTS = ("surface", "macros")
FACT_KEYS = ("macro_reference",)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_committed() -> dict:
    return load_json(OUTPUT_PATH)


def committed_inputs() -> dict[str, dict]:
    return {
        "surface": {"path": "docs/toolkit-surface.json", "sha256": digest(SURFACE_PATH)},
        "macros": {"path": "src/cbus_toolkit/macros.py", "sha256": digest(MACROS_PATH)},
    }


def facts_of(document: dict) -> dict:
    return {key: document[key] for key in FACT_KEYS}


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
    lowered = title.lower()
    if title.startswith("Using ") or title.endswith("user interaction"):
        return "guide_only"
    if "(wireless)" in lowered:
        return "wireless_input"
    if "shutter" in lowered:
        return "shutter"
    if "bistable" in lowered or "mem toggle" in lowered:
        return "bistable"
    if title in ("Day Move", "Night Move", "Sunset", "Any Move"):
        return "schedule_move"
    if "scene" in lowered or "remote scene trigger" in lowered:
        return "scene_widget"
    if "fan" in lowered:
        return "fan"
    if "occupancy" in lowered:
        return "occupancy"
    if "aux on/off" in lowered:
        return "aux_subset"
    if title.endswith("macro function"):
        return "other_key_family"
    if title.endswith("micro function"):
        return "special_micro_function"
    raise ValueError(f"Macro leaf has no triage rule: {topic_id} {title!r}")


def build_document(facts: dict, presets: dict[str, list[str]], micro_codes: set[str]) -> dict:
    rows = []
    for topic_id, title in leaf_roster(facts["macro_reference"]["tree"]):
        if topic_id in presets:
            rows.append({
                "leaf_id": topic_id,
                "title": title,
                "status": "mapped",
                "kind": "preset",
                "presets": presets[topic_id],
                "reasons": [],
            })
        elif topic_id == CUSTOM_TOPIC:
            rows.append({
                "leaf_id": topic_id,
                "title": title,
                "status": "mapped",
                "kind": "custom",
                "preset": "custom",
                "reasons": [],
            })
        elif topic_id in MICRO_WIRED_TOPICS:
            code = MICRO_WIRED_TOPICS[topic_id]
            if code not in micro_codes:
                raise ValueError(f"Unknown micro-function code: {code}")
            rows.append({
                "leaf_id": topic_id,
                "title": title,
                "status": "mapped",
                "kind": "micro_function",
                "micro_function": code,
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
        "mapped_preset": sum(row["kind"] == "preset" for row in rows),
        "mapped_custom": sum(row["kind"] == "custom" for row in rows),
        "mapped_micro_function": sum(row["kind"] == "micro_function" for row in rows),
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
            "Deterministic map from each macro-reference leaf to its implemented "
            "classic key-macro preset or micro-function, or its explicit gap."
        ),
        "inputs": committed_inputs(),
        "leaves": rows,
        "counts": counts,
    }


def validate_document(document: dict) -> dict:
    if document.get("schema_version") != SCHEMA_VERSION or document.get("format") != FORMAT:
        raise ValueError("Macro leaf map has an unknown schema or format")
    inputs = document.get("inputs")
    if not isinstance(inputs, dict) or sorted(inputs) != sorted(VENDOR_INPUTS):
        raise ValueError("Macro leaf map has incomplete or unexpected inputs")
    for name in VENDOR_INPUTS:
        entry = inputs[name]
        actual = digest(ROOT / entry["path"])
        if entry["sha256"] != actual:
            raise ValueError(f"Macro leaf map input changed: {name}")
    leaves = document.get("leaves")
    if not isinstance(leaves, list) or not leaves:
        raise ValueError("Macro leaf map has no leaves")
    seen = set()
    for row in leaves:
        leaf_id = row.get("leaf_id")
        if leaf_id in seen:
            raise ValueError(f"Duplicate macro leaf: {leaf_id}")
        seen.add(leaf_id)
        if row.get("status") == "mapped":
            if row.get("reasons"):
                raise ValueError(f"Mapped macro leaf carries reasons: {leaf_id}")
            if row["kind"] not in ("preset", "custom", "micro_function"):
                raise ValueError(f"Mapped macro leaf has an unknown kind: {leaf_id}")
            if row["kind"] == "preset" and (
                not isinstance(row.get("presets"), list)
                or not row["presets"]
                or not all(isinstance(name, str) and name for name in row["presets"])
            ):
                raise ValueError(f"Mapped preset leaf names no presets: {leaf_id}")
        elif row.get("status") == "pending":
            reasons = row.get("reasons")
            if not reasons:
                raise ValueError(f"Pending macro leaf names no reason: {leaf_id}")
            for reason in reasons:
                if set(reason) != {"code", "detail", "subjects"}:
                    raise ValueError(f"Pending macro leaf has a malformed reason: {leaf_id}")
                if reason["detail"] != REASONS.get(reason["code"]):
                    raise ValueError(f"Pending macro leaf has an unknown reason: {leaf_id}")
                if not reason["subjects"]:
                    raise ValueError(f"Pending macro leaf reason names no subject: {leaf_id}")
        else:
            raise ValueError(f"Macro leaf has an unknown status: {leaf_id}")
    counts = document.get("counts", {})
    if counts.get("leaves") != len(leaves):
        raise ValueError("Macro leaf map counts disagree with its roster")
    if counts.get("mapped_preset", 0) + counts.get("mapped_custom", 0) + counts.get(
        "mapped_micro_function", 0
    ) + counts.get("pending", 0) != len(leaves):
        raise ValueError("Macro leaf map kind counts disagree with its roster")
    return document


def render(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def live_tables() -> tuple[dict[str, list[str]], set[str]]:
    import sys

    sys.path.insert(0, str(ROOT / "src"))
    from cbus_toolkit.macros import MICRO_FUNCTIONS, PRESETS

    presets: dict[str, list[str]] = {}
    for name, preset in PRESETS.items():
        presets.setdefault(f"help:{preset.help_topic}", []).append(name)
    return presets, set(MICRO_FUNCTIONS)
