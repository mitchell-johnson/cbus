"""Independent source-table comparison; this is not original GUI acceptance."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

import pytest

from cbus_toolkit.project_documentation_devices import classic_key_macro

ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / "research/fixtures/project-documentor-classic-key-macro-source-comparison.json"


def test_retained_original_source_macro_comparison():
    receipt = json.loads(RECEIPT.read_text())
    assert receipt["acceptance"] == "independent_original_source_table_comparison"
    assert receipt["native_execution"] is False
    assert receipt["original_generated_page_captured"] is False
    assert receipt["equal"] is True
    assert receipt["checked_vectors_and_contexts"] == 27 * 65536
    for scenario in receipt["scenario_results"]:
        assert scenario["mismatches"] == 0
        assert scenario["source_result_sha256"] == scenario["runtime_result_sha256"]
    for case in receipt["cases"]:
        assert classic_key_macro(tuple(case["commands"]), case["application"],
                                 case["stored1"], case["stored2"]) == tuple(case["expected"])


def test_original_source_macro_comparison_reproduction():
    executable, map_file = os.getenv("CBUS_TOOLKIT_EXE"), os.getenv("CBUS_TOOLKIT_MAP")
    if not executable or not map_file:
        pytest.skip("Explicit pinned vendor EXE/MAP paths are required")
    pytest.importorskip("pefile")
    pytest.importorskip("capstone")
    sys.path.insert(0, str(ROOT / "research"))
    from project_documentor_classic_key_macro_original import compare
    assert compare(Path(executable), Path(map_file)) == json.loads(RECEIPT.read_text())
