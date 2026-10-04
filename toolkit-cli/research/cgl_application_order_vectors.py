#!/usr/bin/env python3
"""Derive current CGL vectors without erasing captured Application order.

The original capture script and transcript remain historical immutable inputs.
Creator/time and unresolved Group/Level ordering keep their prior disposition.
This projection changes only Application array order in captured exports.
"""
from __future__ import annotations

import argparse
from collections import defaultdict, deque
import json
from pathlib import Path

from research import native_cgl_routes


def vectors(fixture: dict) -> list[dict]:
    rows = native_cgl_routes.vectors(fixture)
    captured = {
        f"cgl-{scenario['name']}-{index}": step
        for scenario in fixture["scenarios"]
        for index, step in enumerate(scenario["steps"])
    }
    for row in rows:
        export = row.get("expect_export")
        if export is None or "native_differs" in row:
            continue
        reply = captured[row["id"]]["reply"]
        source = json.loads(reply[1][4:])
        normalized = export["document"]
        _restore_application_order(source, normalized)
    return rows



def _restore_application_order(source: dict, normalized: dict) -> None:
    if len(source["networks"]) != len(normalized["networks"]):
        raise ValueError("CGL projection changed the captured Network roster")
    for original, network in zip(source["networks"], normalized["networks"], strict=True):
        if original["address"] != network["address"]:
            raise ValueError("CGL projection changed captured Network order")
        if "applications" not in original:
            continue
        by_address = defaultdict(deque)
        for application in network["applications"]:
            by_address[application["address"]].append(application)
        ordered = []
        for application in original["applications"]:
            candidates = by_address[application["address"]]
            if not candidates:
                raise ValueError("CGL projection omitted a captured Application")
            ordered.append(candidates.popleft())
        if any(by_address.values()):
            raise ValueError("CGL projection introduced an Application")
        network["applications"] = ordered


def canonical_export(line: str) -> dict:
    """Mask metadata and unresolved Group/Level order, retain Application order."""
    source = json.loads(line[4:])
    normalized = native_cgl_routes.canonical_export(line)
    _restore_application_order(source, normalized)
    return normalized

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--vectors", type=Path, required=True)
    args = parser.parse_args()
    rows = vectors(json.loads(args.fixture.read_text(encoding="utf-8")))
    args.vectors.write_text("".join(json.dumps(row, separators=(",", ":")) + "\n"
                                    for row in rows), encoding="utf-8")
    print(json.dumps({"rows": len(rows), "capture_executed": False,
                      "application_order_normalized": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
