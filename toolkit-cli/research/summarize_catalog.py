#!/usr/bin/env python3
"""Write a compact, value-free summary of native catalogue acceptance evidence."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from verify_catalog import now

BASE = Path(__file__).resolve().parents[1]


def summarize(defaults: dict, diagnostics: dict, boundaries: dict | None, boundary_diagnostics: dict | None = None) -> dict:
    default_cases = {case["id"]: case for case in defaults["cases"]}
    if len(default_cases) != len(defaults["cases"]):
        raise ValueError("Default report contains duplicate case IDs")
    diagnostic_cases = {case["id"]: case for case in diagnostics["cases"]}
    rejected = {key for key, case in default_cases.items() if case.get("result", {}).get("status") not in (None, "pass")}
    if set(diagnostic_cases) != rejected:
        raise ValueError("Diagnostic cases do not exactly match the original default exclusions")
    if defaults["catalog"]["sha256"] != diagnostics["catalog_sha256"]:
        raise ValueError("Acceptance and diagnostics use different vendor catalogues")
    original_passes = {key for key, case in default_cases.items() if case.get("result", {}).get("status") == "pass"}
    alternatives = {key for key, case in diagnostic_cases.items() if case["status"] == "alternative_roundtrip_pass"}
    excluded = []
    for key in sorted(rejected - alternatives):
        case = diagnostic_cases[key]
        excluded.append({field: case.get(field) for field in ("id", "unit_type", "firmware", "catalog_number", "spec_filename", "catalog_description", "addressable", "hidden_in_catalog", "error")})
    output = {"format": "cbus-catalog-acceptance-summary-v1", "generated_at": now(),
              "scope": "Offline native unit schema and Python session acceptance at selected catalogue firmware points",
              "does_not_establish": ["physical device programming", "all firmware values between endpoints", "all possible parameter values", "all Toolkit workflows", "100 percent Toolkit parity"],
              "reference": {"greeting": diagnostics["greeting"], "catalog_sha256": defaults["catalog"]["sha256"]},
              "catalog": {field: defaults["catalog"][field] for field in ("unit_entries", "revision_entries", "declared_default_revisions", "unit_entries_without_default", "unit_entries_with_multiple_defaults")},
              "default_new_workflow": {**defaults["summary"], "successful_parameter_comparisons": sum(case["result"].get("parameter_count", 0) for case in default_cases.values() if case.get("result", {}).get("status") == "pass")},
              "alternative_database_load": diagnostics["summary"],
              "combined_default_workflows": {"selected": len(default_cases), "verified_cases": len(original_passes | alternatives),
                                             "excluded_cases": len(excluded), "not_run": defaults["summary"]["not_run"],
                                             "all_selected_cases_passed": len(original_passes | alternatives) == len(default_cases)},
              "excluded_default_cases": excluded,
              "boundary_workflow": {"status": "not_available"},
              "commands": {"default": ".venv/bin/python research/verify_catalog.py --host HOST",
                           "boundaries": ".venv/bin/python research/verify_catalog.py --host HOST --all-revisions --boundaries --output research/runtime/catalog-boundaries.json",
                           "parallel_resume": ".venv/bin/python research/verify_catalog_parallel.py --host HOST --output research/runtime/catalog-boundaries.json --jobs 4",
                           "alternatives": ".venv/bin/python research/diagnose_catalog.py --host HOST",
                           "boundary_alternatives": ".venv/bin/python research/diagnose_catalog.py --host HOST --source research/runtime/catalog-boundaries.json --output research/runtime/catalog-boundary-diagnostics.json",
                           "summary": ".venv/bin/python research/summarize_catalog.py"},
              "runner_options": ["--host", "--port", "--catalog", "--output", "--filter", "--limit", "--resume", "--retry-failures", "--all-revisions", "--boundaries", "--network", "--shard"],
              "execution_constraints": ["explicit test host", "owned disposable projects", "new or closed networks only", "no NET OPEN or physical operations", "no automatic replay after ambiguous transport failure", "native rejections and unrun cases are not passes"]}
    if boundaries is not None:
        if boundaries["catalog"]["sha256"] != defaults["catalog"]["sha256"]:
            raise ValueError("Boundary report uses a different vendor catalogue")
        output["boundary_workflow"] = {**boundaries["summary"], "status": "complete" if boundaries["summary"]["not_run"] == 0 else "incomplete",
                                        "firmware_selection": boundaries["catalog"]["firmware_selection"],
                                        "successful_parameter_comparisons": sum(case["result"].get("parameter_count", 0) for case in boundaries["cases"] if case.get("result", {}).get("status") == "pass")}
        output["boundary_workflow"]["failure_classes"] = [{"status": key[0], "error": key[1], "count": value} for key, value in sorted(Counter((case["result"]["status"], case["result"].get("error", {}).get("message", "")) for case in boundaries["cases"] if case.get("result", {}).get("status") not in (None, "pass")).items())]
    if boundary_diagnostics is not None:
        if boundaries is None:
            raise ValueError("Boundary alternatives require the original boundary report")
        if boundary_diagnostics["catalog_sha256"] != defaults["catalog"]["sha256"]:
            raise ValueError("Boundary alternatives use a different vendor catalogue")
        cases = {case["id"]: case for case in boundaries["cases"]}
        alternatives = {case["id"]: case for case in boundary_diagnostics["cases"]}
        if len(cases) != len(boundaries["cases"]) or len(alternatives) != len(boundary_diagnostics["cases"]):
            raise ValueError("Boundary reports contain duplicate case IDs")
        rejected = {key for key, case in cases.items() if case.get("result", {}).get("status") not in (None, "pass")}
        if set(alternatives) != rejected:
            raise ValueError("Boundary alternatives do not exactly match the original boundary exclusions")
        original_passes = {key for key, case in cases.items() if case.get("result", {}).get("status") == "pass"}
        alternative_passes = {key for key, case in alternatives.items() if case["status"] == "alternative_roundtrip_pass"}
        output["boundary_alternative_database_load"] = boundary_diagnostics["summary"]
        output["combined_boundary_workflows"] = {"selected": len(cases), "verified_cases": len(original_passes | alternative_passes),
                                                "excluded_cases": len(rejected - alternative_passes), "not_run": boundaries["summary"]["not_run"],
                                                "successful_parameter_comparisons": output["boundary_workflow"]["successful_parameter_comparisons"] + sum(alternatives[key]["parameter_count"] for key in alternative_passes),
                                                "all_selected_cases_passed": len(original_passes | alternative_passes) == len(cases)}
        output["excluded_boundary_cases"] = [{field: alternatives[key].get(field) for field in ("id", "unit_type", "firmware", "catalog_number", "spec_filename", "catalog_description", "addressable", "hidden_in_catalog", "error")} for key in sorted(rejected - alternative_passes)]
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--default", type=Path, default=BASE / "research/runtime/catalog-acceptance.json")
    parser.add_argument("--diagnostics", type=Path, default=BASE / "research/runtime/catalog-diagnostics.json")
    parser.add_argument("--boundaries", type=Path, default=BASE / "research/runtime/catalog-boundaries.json")
    parser.add_argument("--boundary-diagnostics", type=Path, default=BASE / "research/runtime/catalog-boundary-diagnostics.json")
    parser.add_argument("--output", type=Path, default=BASE / "docs/catalog-acceptance-summary.json")
    args = parser.parse_args()
    report = summarize(json.loads(args.default.read_text()), json.loads(args.diagnostics.read_text()),
                       json.loads(args.boundaries.read_text()) if args.boundaries.is_file() else None,
                       json.loads(args.boundary_diagnostics.read_text()) if args.boundary_diagnostics.is_file() else None)
    report["evidence"] = []
    for name, path in (("default_acceptance", args.default), ("alternative_diagnostics", args.diagnostics), ("all_revision_boundaries", args.boundaries), ("boundary_alternative_diagnostics", args.boundary_diagnostics)):
        if path.is_file():
            try:
                relative = str(path.resolve().relative_to(BASE))
            except ValueError:
                relative = str(path.resolve())
            report["evidence"].append({"name": name, "local_path": relative, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    report["source_hashes"] = {}
    for relative in ("research/vendor/cgate/app/cgate.jar", "research/vendor/cgate-decompiled.tar", "src/cbus_toolkit/programming.py",
                     "research/verify_catalog.py", "research/verify_catalog_parallel.py", "research/diagnose_catalog.py", "research/summarize_catalog.py"):
        path = BASE / relative
        if path.is_file():
            report["source_hashes"][relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(args.output.resolve()), "combined_default_workflows": report["combined_default_workflows"],
                      "boundary_workflow": report["boundary_workflow"]}), flush=True)


if __name__ == "__main__":
    main()
