import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

from cbus_toolkit.physical_programming import SUPPORTED_METHODS
from test_cgate import peer


def tagged(number, *lines):
    return [(f"[{number}] {line}\r\n").encode() for line in lines]


def capabilities():
    return {
        "service": "cmqttd",
        "physical_pp_load": True,
        "physical_pp_save": True,
        "physical_pp_routed_load": True,
        "physical_pp_routed_save": True,
        "physical_pp_routed_methods": list(SUPPORTED_METHODS),
        "physical_pp_routed_save_protection": ["none", "checksum", "lock"],
        "physical_pp_routed_lock_methods": ["direct", "ncc", "paged"],
        "physical_pp_routed_unsupported_methods": [],
        "physical_pp_routed_lock": True,
        "physical_pp_routed_nvm_commit": True,
        "physical_pp_routed_delivery_semantics": (
            "reply-network-unit-parameter-tag-correlated-exactly-once-no-replay"
        ),
        "physical_pp_routed_state_scope": "owned-session-target-network",
        "pci_generation": 3,
        "pci_connected": True,
        "programming_lane_state": "ready",
    }


class PhysicalProgrammingCLITests(unittest.TestCase):
    def cli(self, host, port, *arguments, status=0):
        process = subprocess.run(
            [sys.executable, "-m", "cbus_toolkit", "cgate", "--host", host,
             "--port", str(port), "--timeout", "5", "physical-pp", *arguments],
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(process.returncode, status, process.stderr + process.stdout)
        return json.loads(process.stdout if process.stdout else process.stderr)

    def test_apply_uses_exact_native_save_to_source_and_fresh_session(self):
        schema = (
            "<Parameters><Param><Name>Value</Name><Type>int</Type>"
            "<Address>$20</Address><ProgramMethod>direct</ProgramMethod>"
            "<Protection>none</Protection></Param></Parameters>"
        )
        cap = json.dumps(capabilities(), separators=(",", ":"))
        debug = tagged(10, "199---------|20|", "199-    unit>01|", "199- current>02|",
                       "199-  change>ff|", "199 endparam>nn|")
        responses = [
            tagged(1, "200-" + cap, "200 OK"),
            tagged(2, "200 OK"),
            tagged(3, "200 OK"),
            tagged(4, "200 OK"),
            tagged(5, "200 OK"),
            tagged(6, "343-Begin XML snippet", "347-" + schema, "344 End XML snippet"),
            tagged(7, "315 Value=0x01"),
            tagged(8, "200 OK"),
            tagged(9, "315 Value=0x02"),
            debug,
            *(tagged(number, "200 OK") for number in range(11, 18)),
            tagged(18, "343-Begin XML snippet", "347-" + schema, "344 End XML snippet"),
            tagged(19, "315 Value=0x02"),
            tagged(20, "200 OK"),
            tagged(21, "200 OK"),
        ]
        journal = Path(self.enterContext(tempfile.TemporaryDirectory())) / "attempt.json"
        with peer(responses) as ((host, port), sent):
            result = self.cli(
                host, port, "apply", "//TEST/253/p/4", "--method", "direct",
                "--set", "Value", "0x02", "--journal", str(journal),
            )
        document = json.loads(journal.read_text())
        self.assertEqual(document["phase"], "complete")
        self.assertEqual(result["journal"]["attempt_id"], document["attempt_id"])
        self.assertTrue(result["complete"])
        self.assertTrue(result["saved"])
        self.assertTrue(result["fresh_physical_readback_verified"])
        self.assertFalse(result["power_cycle_persistence_verified"])
        commands = [line.decode().rstrip("\r\n") for line in sent]
        self.assertEqual(commands[0], "[1] CMQTT CAPABILITIES")
        self.assertEqual(commands[1], "[2] PROJECT USE TEST")
        write = re.fullmatch(r"\[3\] PP LOCK (cbus_pp_[0-9a-f]{12}_write_lock) //TEST/253", commands[2])
        self.assertIsNotNone(write)
        write_lock = write[1]
        session = write_lock.removesuffix("_lock")
        self.assertEqual(commands[3], f"[4] PP START {session} {write_lock}")
        self.assertEqual(commands[4], f"[5] PP LOAD {session} //TEST/253/p/4")
        self.assertEqual(commands[5], f"[6] PP INFO {session} *")
        self.assertEqual(commands[6], f"[7] PP GET {session} Value")
        self.assertEqual(commands[7], f'[8] PP SET {session} Value "0x02"')
        self.assertEqual(commands[8], f"[9] PP GET {session} Value")
        self.assertEqual(commands[9], f"[10] PP DEBUG mem {session} 20")
        self.assertEqual(commands[10], f"[11] PP SAVE_TO_SOURCE {session}")
        self.assertEqual(commands[11], f"[12] PP END {session}")
        self.assertEqual(commands[12], f"[13] PP UNLOCK {write_lock}")
        self.assertEqual(commands[13], "[14] PROJECT USE TEST")
        verify = re.fullmatch(r"\[15\] PP LOCK (cbus_pp_[0-9a-f]{12}_verify_lock) //TEST/253", commands[14])
        self.assertIsNotNone(verify)
        verify_lock = verify[1]
        verify_session = verify_lock.removesuffix("_lock")
        self.assertEqual(commands[15], f"[16] PP START {verify_session} {verify_lock}")
        self.assertEqual(commands[16], f"[17] PP LOAD {verify_session} //TEST/253/p/4")
        self.assertEqual(commands[17], f"[18] PP INFO {verify_session} *")
        self.assertEqual(commands[18], f"[19] PP GET {verify_session} Value")
        self.assertEqual(commands[19], f"[20] PP END {verify_session}")
        self.assertEqual(commands[20], f"[21] PP UNLOCK {verify_lock}")

    def test_help_lists_all_methods_and_invalid_path_stops_before_connect(self):
        process = subprocess.run(
            [sys.executable, "-m", "cbus_toolkit", "cgate", "physical-pp", "apply", "--help"],
            capture_output=True, text=True,
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        for method in SUPPORTED_METHODS:
            self.assertIn(method, process.stdout)
        process = subprocess.run(
            [sys.executable, "-m", "cbus_toolkit", "cgate", "physical-pp", "inspect",
             "/db//TEST/253/p/4", "--method", "direct"],
            capture_output=True, text=True,
        )
        self.assertEqual(process.returncode, 2)
        self.assertIn("must be //PROJECT/NETWORK/p/UNIT", process.stderr)
        self.assertNotIn("Unable to establish", process.stderr)


if __name__ == "__main__":
    unittest.main()
