#!/usr/bin/env python3
"""Record why physical-bus acceptance does not apply to the scoped SESSION_ID pilot."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = ROOT.parent
NATIVE = ROOT / "research/experiments/2026-09-25/cgate-session-native-acceptance.json"
PILOT = ROOT / "research/functional-obligation-pilot.json"
CONTRACTS = ROOT / "src/cbus_toolkit/cgate-contract-inventory.json"
MATRIX = REPOSITORY / "rust/cbus-cgate/src/capability_matrix.rs"
OUTPUT = ROOT / "research/fixtures/cgate-session-physical-applicability.json"
COMMAND = (
    "PYTHONPATH=src python3 research/cgate_session_physical_applicability.py "
    "--output research/fixtures/cgate-session-physical-applicability.json"
)


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def inputs() -> dict[str, str]:
    return {
        "native_capture": digest(NATIVE),
        "pilot_manifest": digest(PILOT),
        "contract_inventory": digest(CONTRACTS),
        "capability_matrix": digest(MATRIX),
        "capture_script": digest(Path(__file__)),
    }


def decisions() -> list[dict]:
    native = json.loads(NATIVE.read_text(encoding="utf-8"))
    pilot = json.loads(PILOT.read_text(encoding="utf-8"))
    inventory = json.loads(CONTRACTS.read_text(encoding="utf-8"))
    if (
        native.get("format") != "cbus-cgate-session-native-acceptance-v1"
        or native.get("passed") is not True
        or native.get("environment", {}).get("physical_networks_opened") is not False
        or native.get("cleanup", {}).get("cleanup_complete") is not True
        or pilot.get("native_oracle", {}).get("sha256") != digest(NATIVE)
        or pilot["native_oracle"]["vendor_jar_sha256"] != native.get("vendor_jar_sha256")
        or inventory.get("schema_version") != 1
        or inventory.get("sources", {}).get("native_session_acceptance") != {"sha256": digest(NATIVE)}
        or inventory.get("sources", {}).get("capability_matrix") != {"sha256": digest(MATRIX)}
    ):
        raise ValueError("SESSION_ID physical applicability source is stale")
    contracts = {row["path"]: row for row in inventory["contracts"]}
    definitions = pilot.get("obligations")
    if not isinstance(definitions, list) or {row["path"] for row in definitions} != {
        "SESSION_ID", "SESSION_ID ALL", "SESSION_ID TAG"
    }:
        raise ValueError("SESSION_ID physical applicability requires all three functions")
    cases = []
    for definition in definitions:
        path = definition["path"]
        contract = contracts[path]
        effects = contract["axes"]["effects_routing"]["subaxes"]
        if (
            contract["contract_sha256"] != definition["contract_sha256"]
            or effects["routing_class"].get("value") != "LocalDatabase"
            or effects["physical_io_boundary"].get("status") != "resolved"
            or effects["physical_io_boundary"].get("value")
            != "local_database_or_connection_state_no_bus_io"
        ):
            raise ValueError(f"{path} has no verified local-only I/O contract")
        reason = definition["physical_candidate_reason"]
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(f"{path} lacks a physical applicability reason")
        receipt = {
            "obligation_id": definition["id"],
            "dimension": "physical",
            "decision": "not_applicable",
            "reason": reason,
        }
        cases.append({
            "id": f"research/cgate_session_physical_applicability.py::{path.replace(' ', '-')}",
            "obligation_ids": [definition["id"]],
            "dimensions": [],
            "result": "passed",
            "applicability_receipts": [receipt],
            "scope_disposition_receipts": [],
        })
    return cases


def build() -> dict:
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=REPOSITORY, text=True
    ).strip()
    return {
        "format": "cbus-parity-test-report-v1",
        "result": "passed",
        "source_revision": revision,
        "command": COMMAND,
        "exit_code": 0,
        "source_inputs": inputs(),
        "cases": decisions(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    report = build()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"{len(report['cases'])} physical applicability decisions passed")


if __name__ == "__main__":
    main()
