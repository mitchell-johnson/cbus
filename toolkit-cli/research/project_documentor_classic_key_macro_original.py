"""Compare ClassicKey documentor macro labels with independently recovered tables.

This is a source-derived comparison, NOT original-method execution or generated
page acceptance. Explicit pinned Toolkit EXE/MAP inputs provide the ordered
macro/micro registrations and KEY application subsets. A separately transcribed
original refresh chain applies the primary-block shutter conversion and subset
filter. All 65,536 JP/SR/LP/LR nibble vectors are compared with the runtime helper
for each retained application/stored-level context. No GUI, network, project or
hardware is accessed; receipts contain synthetic values and hashes only.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
from pathlib import Path
import re
import struct
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "src"))
from key_preset_families import (  # noqa: E402
    Image, EXE_SHA256, MAP_SHA256, TEMPLATE_FACTORY, REGISTER_TEMPLATE,
    micro_function_groups, template_groups, subsets,
)
from project_documentor_static import _Toolkit  # noqa: E402

FORMAT = "cbus-project-documentor-classic-key-macro-source-comparison-v1"
METHODS = (
    "CIS_TKeyMacroFunction.InitialiseKeyMacroFunctionFactory",
    "CIS_TKeyMicroFunctionGroup.InitialiseKeyMicroFunctionGroupFactory",
    "CIS_TKeyMacroFunction.TKeyMacroFunction.RefreshFromMicroFunctions",
    "CIS_TKeyMacroFunction.TKeyMacroFunction.ReconcileTemplateAndGroup",
    "CIS_TInputKey.TInputKey.MacroFunctionRefresh",
    "CIS_TInputKey.TInputKey.IdenticalMacroFunctionRefresh",
    "CIS_TInputKey.TInputKey.RefreshTemplateFromMacroFunction",
    "CIS_TKeyMacrofunctionSubset.TKeyMacroFunctionSubsetFactory.CheckKeyMacroFunctionSubset",
    "CIS_TKeyMacrofunctionSubset.TKeyMacroFunctionSubsetFactory.GetKeyMacroFunctionSubset",
    "CIS_TKeyInputCGateAgent.GetKeyValues",
)
# Pinned source control-flow facts, independent of runtime constants.
IDENTICAL_SHA = "32a9b311c0e6a6597721855cb4b7dd25c125b54c0b56fe263f5eba6c83c5a997"
FILTER_SHA = "d3242358988d92e801a0c22cbc4c04010bb48750119a005398204b8e17d65ad7"
STORED_PAIRS = ((None, None), (0, 0), (249, 0), (252, 0), (255, 0),
                (0, 2), (0, 5), (249, 2), (255, 5))


def _template_labels(image: Image, toolkit: _Toolkit) -> dict[int, str]:
    """Recover RegisterTemplate's description parameter, including resources."""
    _, instructions = image.function(image.address(TEMPLATE_FACTORY), 0x2000)
    register = image.address(REGISTER_TEMPLATE)
    labels, label, function_type = {}, None, None
    for instruction in instructions:
        mnemonic, operands = instruction.mnemonic, instruction.op_str
        if mnemonic == "push" and operands.startswith("0x"):
            literal = toolkit.literal(int(operands, 16))
            if literal is not None:
                label = literal
        match = re.fullmatch(r"eax, dword ptr \[(0x[0-9a-f]+)\]", operands)
        if mnemonic == "mov" and match:
            try:
                resource = toolkit.resource(toolkit.dword(int(match[1], 16)))
            except struct.error:
                resource = None  # Uninitialized global factory, not a resource pointer.
            if resource is not None:
                label = resource
        if mnemonic == "mov" and operands.startswith("dl, "):
            function_type = int(operands[4:], 0)
        elif mnemonic == "xor" and operands == "edx, edx":
            function_type = 0
        elif mnemonic == "call" and operands == hex(register):
            if function_type is None or label is None or function_type in labels:
                raise ValueError("Unresolved original macro template description")
            labels[function_type] = label
    return labels


class SourceMacroOracle:
    """Ordered source registrations plus the non-AUX classic refresh chain."""

    def __init__(self, executable: Path, map_file: Path):
        image = Image(executable, map_file)  # Checks the entire pinned EXE/MAP hashes.
        self.toolkit = _Toolkit(executable.read_bytes(), map_file.read_bytes())
        self.groups = micro_function_groups(image)
        self.templates = template_groups(image)
        self.subsets = subsets(image)["KEY"]
        self.labels = _template_labels(image, self.toolkit)
        self.methods = {name: self.toolkit.method(name) for name in METHODS}
        if self.methods[METHODS[5]]["sha256"] != IDENTICAL_SHA or \
                self.methods[METHODS[6]]["sha256"] != FILTER_SHA:
            raise ValueError("Original classic macro remap/filter method changed")
        self.first_match = {}
        # ItemAndGroupByMicroFunctions stops on the first matching registration.
        # GetKeyValues passes input-source type0, which disables its source filter.
        for function_type, groups in self.templates.items():
            for group in groups:
                vector = tuple(self.groups[group])
                if all(0 <= command <= 15 for command in vector):
                    self.first_match.setdefault(vector, function_type)

    def resolve(self, commands, application, stored1, stored2):
        function_type = self.first_match.get(tuple(commands), 26)
        # ReconcileTemplateAndGroup's sensor/AUX overrides are false for KEY1/2/4.
        if function_type in (31, 33):
            function_type = 26
        if stored1 is not None and stored2 is not None and application != 202:
            if function_type == 14:
                function_type = {249: 17, 252: 18, 255: 20}.get(stored1, 14)
            elif function_type == 15:
                function_type = {2: 19, 5: 22}.get(stored2, 15)
        allowed = self.subsets.get(str(application), self.subsets["0"])
        if function_type not in allowed:
            function_type = 26
        return function_type, self.labels[function_type]


def compare(executable: Path, map_file: Path) -> dict:
    # Import only the single function under comparison, never its tables.
    from cbus_toolkit.project_documentation_devices import classic_key_macro

    oracle = SourceMacroOracle(executable, map_file)
    scenarios, mismatches, checked = [], [], 0
    for application in (56, 202, 255):
        for stored1, stored2 in STORED_PAIRS:
            original_digest = hashlib.sha256()
            actual_digest = hashlib.sha256()
            mismatch_count = 0
            for commands in itertools.product(range(16), repeat=4):
                expected = oracle.resolve(commands, application, stored1, stored2)
                actual = classic_key_macro(commands, application, stored1, stored2)
                original_digest.update(json.dumps(expected, separators=(",", ":")).encode() + b"\n")
                actual_digest.update(json.dumps(actual, separators=(",", ":")).encode() + b"\n")
                checked += 1
                if tuple(actual) != expected:
                    mismatch_count += 1
                    if len(mismatches) < 20:
                        mismatches.append({"commands": list(commands), "application": application,
                                           "stored1": stored1, "stored2": stored2,
                                           "expected": list(expected), "actual": list(actual)})
            scenarios.append({"application": application, "stored1": stored1, "stored2": stored2,
                              "vectors": 65536, "mismatches": mismatch_count,
                              "source_result_sha256": original_digest.hexdigest(),
                              "runtime_result_sha256": actual_digest.hexdigest()})
    # Compact cases retain each admitted first-match vector and remap boundary.
    vectors = [vector for vector, value in oracle.first_match.items()
               if value in set(oracle.subsets["202"])] + [(1, 2, 3, 4)]
    cases = [{"commands": list(commands), "application": 56, "stored1": 0, "stored2": 0,
              "expected": list(oracle.resolve(commands, 56, 0, 0))} for commands in vectors]
    for commands in ((12, 0, 0, 0), (6, 0, 0, 0)):
        for application in (56, 202, 255):
            for stored1, stored2 in STORED_PAIRS:
                cases.append({"commands": list(commands), "application": application,
                              "stored1": stored1, "stored2": stored2,
                              "expected": list(oracle.resolve(commands, application, stored1, stored2))})
    return {"format": FORMAT, "acceptance": "independent_original_source_table_comparison",
            "native_execution": False, "original_generated_page_captured": False,
            "exe_sha256": EXE_SHA256, "map_sha256": MAP_SHA256,
            "checked_vectors_and_contexts": checked,
            "equal": not any(row["mismatches"] for row in scenarios),
            "scenario_results": scenarios, "mismatch_samples": mismatches,
            "cases": cases, "template_labels": {str(k): oracle.labels[k]
                for k in sorted(set(oracle.subsets["202"]))},
            "methods": {name: {"address": hex(row["start"]), "sha256": row["sha256"]}
                        for name, row in oracle.methods.items()}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--map", dest="map_file", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    receipt = compare(args.exe, args.map_file)
    text = json.dumps(receipt, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0 if receipt["equal"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
