"""Offline replay and optional fresh original acceptance for fragment-only layouts."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import unittest

from cbus_toolkit.memory import MemoryCodec, MemoryImage
from cbus_toolkit.unitspec import ParameterSpec, UnitSpec
from research.verify_memory_fragments import run


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/native-memory-fragment-acceptance.json"
EXPECTED_LAYOUTS = {
    "LabelFlavourLSB": {
        "type": "bit",
        "address": "$60",
        "array_size": "8",
        "bit_size": "",
        "bit_address": "3",
        "array_skip": "",
        "endian": "",
    },
    "LabelFlavourMSB": {
        "type": "bit",
        "address": "$60",
        "array_size": "8",
        "bit_size": "",
        "bit_address": "6",
        "array_skip": "",
        "endian": "",
    },
}
EXPECTED_CASES = {
    ("LabelFlavourLSB", 0): (3, 0xA5, [1, 0, 1, 0, 1, 0, 1, 0], "ada2a5a5a5a5a5a5"),
    ("LabelFlavourLSB", 1): (3, 0x5A, [0, 1, 0, 1, 0, 1, 0, 1], "525d5a5a5a5a5a5a"),
    ("LabelFlavourMSB", 0): (6, 0xA5, [1, 0, 1, 0, 1, 0, 1, 0], "6595a5a5a5a5a5a5"),
    ("LabelFlavourMSB", 1): (6, 0x5A, [0, 1, 0, 1, 0, 1, 0, 1], "9a6a5a5a5a5a5a5a"),
}


def codec(name: str, bit_address: int) -> MemoryCodec:
    fields = {
        "Name": name,
        "Type": "bit",
        "Address": "$60",
        "ArraySize": "8",
        "BitAddress": str(bit_address),
        "Protection": "checksum",
        "DefaultValue": "0 0 0 0 0 0 0 0",
    }
    parameter = ParameterSpec(name, "bit", "I_DLTF.xml", fields)
    specification = UnitSpec("I_DLTF.xml", {}, ("I_DLTF.xml",), {name: parameter})
    return MemoryCodec(specification)


class FragmentAcceptanceReplayTests(unittest.TestCase):
    def test_all_original_fragment_trials_replay_through_production_codec(self):
        evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
        self.assertEqual(
            evidence["format"], "cbus-native-memory-fragment-acceptance-v1"
        )
        self.assertEqual(
            evidence["summary"],
            {
                "distinct_layouts": 2,
                "passing_layouts": 2,
                "passing_change_trials": 4,
                "failed_change_trials": 0,
            },
        )
        self.assertTrue(evidence["execution"]["network_denied"])
        self.assertFalse(evidence["execution"]["server_started"])
        self.assertFalse(evidence["execution"]["physical_io"])
        self.assertTrue(evidence["inputs_unchanged"])
        self.assertEqual(
            evidence["original"]["terminal"],
            {
                "layouts": 2,
                "trials": 4,
                "original_encoder_invoked": "true",
                "command_service_started": "false",
                "physical_io": "false",
            },
        )
        self.assertEqual(evidence["original"]["layouts"], EXPECTED_LAYOUTS)
        source = evidence["source_sha256"]
        for relative in (
            "research/NativeMemoryFragmentProbe.java",
            "research/verify_memory_fragments.py",
            "src/cbus_toolkit/memory.py",
            "src/cbus_toolkit/unitspec.py",
        ):
            self.assertEqual(
                hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(),
                source[relative],
            )
        seen = set()
        for case in evidence["cases"]:
            key = (case["parameter"], case["trial"])
            self.assertIn(key, EXPECTED_CASES)
            bit_address, seed, value, raw_expected = EXPECTED_CASES[key]
            self.assertEqual(case["layout"], ["bit", 1, bit_address, 0, 8, "little"])
            self.assertEqual(case["seed"], seed)
            self.assertEqual(case["value"], value)
            self.assertEqual(case["native_raw_hex"], raw_expected)
            self.assertEqual(case["native_decoded"], value)
            subject = codec(case["parameter"], case["layout"][2])
            layout = subject.layout(case["parameter"])
            image = MemoryImage.from_bytes(
                bytes([case["seed"]]) * 8, start=layout.address
            )
            changed = subject.encode(case["parameter"], case["value"]).apply(image)
            raw = changed.read(layout.address, 8).hex()
            self.assertEqual(case["status"], "pass")
            self.assertEqual(raw, case["native_raw_hex"])
            self.assertEqual(raw, case["python_raw_hex"])
            self.assertEqual(
                subject.decode(case["parameter"], changed), case["native_decoded"]
            )
            self.assertEqual(case["native_decoded"], case["python_decoded"])
            seen.add(key)
        self.assertEqual(seen, set(EXPECTED_CASES))


@unittest.skipUnless(
    sys.platform == "darwin"
    and all(
        os.environ.get(name)
        for name in (
            "CBUS_LOCAL_CGATE_VENDOR",
            "CBUS_UNITSPEC_DIR",
            "CBUS_CGATE_JAVA",
            "CBUS_CGATE_JAVAC",
        )
    ),
    "Explicit original C-Gate, decrypted specs and Java 11 toolchain required",
)
class FreshFragmentAcceptanceTests(unittest.TestCase):
    def test_fresh_original_fragment_matrix(self):
        report = run(
            vendor=os.environ["CBUS_LOCAL_CGATE_VENDOR"],
            spec_directory=os.environ["CBUS_UNITSPEC_DIR"],
            java=os.environ["CBUS_CGATE_JAVA"],
            javac=os.environ["CBUS_CGATE_JAVAC"],
        )
        self.assertEqual(
            report["summary"],
            {
                "distinct_layouts": 2,
                "passing_layouts": 2,
                "passing_change_trials": 4,
                "failed_change_trials": 0,
            },
        )
        self.assertTrue(report["execution"]["network_denied"])
        self.assertFalse(report["execution"]["server_started"])
        self.assertFalse(report["execution"]["command_service_started"])
        self.assertFalse(report["execution"]["physical_io"])
        self.assertTrue(report["inputs_unchanged"])


if __name__ == "__main__":
    unittest.main()
