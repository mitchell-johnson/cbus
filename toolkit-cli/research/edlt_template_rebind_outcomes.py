#!/usr/bin/env python3
"""Classify one existing synthetic rebind capture; execute no vendor code or VM.

This is a research report, never an editor receipt or an apply authorization.
Only the complete, hash-pinned 31-case fixture is admitted. The input's full
trace hashes are copied as provenance: compact callbacks omit mechanical calls,
so those full trace hashes cannot be independently recomputed from this file.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


FIXTURE_SHA256 = "626f0f0b81ecfb653423f2200ee754e9be660becbb806e78bc3a4718aa5ec446"
FIXTURE = Path(__file__).with_name("edlt_template_rebind_vectors.json")
FALSE_EVIDENCE_FIELDS = (
    "original_methods_executed_by_clr",
    "original_form_executed",
    "model_callbacks_executed",
    "control_binding_effects_verified",
    "rendering_verified",
    "network_io_attempted",
    "persisted",
)
ERROR_CALLBACKS = {
    "SharpLogger.Log::LogException",
    "System.Windows.Forms.MessageBox::Show",
    "eDLT.FrmBaseUnit::OnFormClosed",
}


def classify_capture(fixture: Path = FIXTURE) -> dict:
    """Read and classify the pinned historical capture, without replaying it."""
    raw = fixture.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != FIXTURE_SHA256:
        raise ValueError("Only the pinned historical 31-case capture is admitted")
    captured = json.loads(raw)
    if captured["format"] != "cbus-edlt-template-rebind-proxy-vectors-v1":
        raise ValueError("Unexpected capture format")
    if captured["passed"] is not True or len(captured["cases"]) != 31:
        raise ValueError("Incomplete historical capture")
    if any(captured[field] is not False for field in FALSE_EVIDENCE_FIELDS):
        raise ValueError("Historical capture evidence boundary changed")

    results = []
    for index, case in enumerate(captured["cases"]):
        failures = [event for event in case["callbacks"] if event.get("proxy_failure")]
        caught_handlers = [event for event in case["callbacks"]
                           if "caught_by_original_il" in event]
        error_callbacks = [event for event in case["callbacks"]
                           if event.get("method") in ERROR_CALLBACKS]
        configured = (case["failure_call_index"] is not None
                      or case["failure_receiver_and_method"] is not None)
        if case["outcome"] == "proxy_failure":
            classification = "propagated_failure"
            if not configured:
                raise ValueError("Unconfigured historical failure")
        elif case["outcome"] == "returned" and configured:
            classification = "returned_with_caught_failure"
            if len(failures) != 1 or not error_callbacks or not caught_handlers:
                raise ValueError("Missing retained caught-failure evidence")
        elif (case["outcome"] == "returned" and not failures
              and not error_callbacks and not caught_handlers):
            classification = "dispatch_only"
        else:
            raise ValueError("Unrecognized historical outcome")

        failure_index = failures[0]["call_index"] if failures else case["failure_call_index"]
        continued = ([event["call_index"] for event in case["callbacks"]
                      if event.get("call_index", 0) > failure_index]
                     if failure_index is not None else [])
        results.append({
            "capture_case_index": index,
            "method": case["method"],
            "expanded": case["expanded"],
            "classification": classification,
            "interpreted_method_returned": case["outcome"] == "returned",
            "configured_failure_call_index": case["failure_call_index"],
            "configured_failure_receiver_and_method": case["failure_receiver_and_method"],
            "recorded_failure_callbacks": failures,
            "failure_callback_omitted_from_compact_capture": configured and not failures,
            "recorded_error_callbacks": error_callbacks,
            "recorded_interpreted_catch_handlers": caught_handlers,
            "recorded_later_callback_count": len(continued),
            "recorded_close_callback": any(event["method"].endswith("::OnFormClosed")
                                           for event in error_callbacks),
            "full_trace_sha256_from_capture": case["trace_sha256"],
            "actual_model_effects_verified": False,
            "actual_control_binding_effects_verified": False,
            "apply_allowed": False,
        })

    counts = dict(sorted(Counter(case["classification"] for case in results).items()))
    if counts != {"dispatch_only": 7, "propagated_failure": 21,
                  "returned_with_caught_failure": 3}:
        raise ValueError("Historical outcome inventory changed")
    return {
        "format": "cbus-edlt-template-rebind-outcomes-v1",
        "scope": "classification of a pinned historical synthetic proxy capture only",
        "capture_sha256": digest,
        "case_count": len(results),
        "classifications": counts,
        "vendor_code_executed_by_classifier": False,
        "il_vm_executed_by_classifier": False,
        "actual_model_effects_verified": False,
        "actual_control_binding_effects_verified": False,
        "original_form_executed": False,
        "control_disposal_verified": False,
        "network_io_attempted": False,
        "persisted": False,
        "apply_allowed": False,
        "cases": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=FIXTURE)
    parser.add_argument("--output", type=Path,
                        help="New report path; an existing file is never overwritten")
    args = parser.parse_args()
    report = classify_capture(args.fixture)
    encoded = json.dumps(report, indent=2) + "\n"
    if args.output is None:
        print(encoded, end="")
    else:
        with args.output.open("x", encoding="utf-8") as destination:
            destination.write(encoded)


if __name__ == "__main__":
    main()
