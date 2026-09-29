"""Native PROGRAMMER/DEPLOY_QUEUE lifecycle evidence against the KEY4 PCI simulator."""
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from research import native_programmer_lifecycle as lifecycle

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "rust/testdata/fixtures/native_cgate_programmer_lifecycle.json"


def load():
    return json.loads(FIXTURE.read_text())


def scenario(fixture, name):
    return next(item for item in fixture["scenarios"] if item["name"] == name)


def replies(item):
    """First reply to each command outside polling steps."""
    found = {}
    for step in item["steps"]:
        if "command" in step and "until" not in step:
            found.setdefault(step["command"], step["reply"])
    return found


class CommittedLifecycleFixtureTests(unittest.TestCase):
    """Offline checks that the committed transcript supports each recorded fact."""

    def test_fixture_is_current_for_its_capture_script_and_simulator(self):
        fixture = load()
        self.assertEqual(fixture["format"], lifecycle.FORMAT)
        self.assertEqual(fixture["capture_script_sha256"],
                         hashlib.sha256(Path(lifecycle.__file__).read_bytes()).hexdigest())
        self.assertEqual(fixture["simulator_fixture_sha256"], hashlib.sha256(
            (ROOT / "toolkit-cli/research/fixtures/key4-synthetic.json").read_bytes()).hexdigest())
        self.assertEqual(fixture["oracle"]["jar_sha256"],
                         "3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630")
        self.assertTrue(fixture["oracle"]["cleanup_complete"])
        self.assertEqual(fixture["native_facts"], lifecycle.NATIVE_FACTS)
        text = FIXTURE.read_text()
        for private in ("127.0.0.1", "/Users/", "/Volumes/", "OID=0", "OID=1"):
            self.assertNotIn(private, text)

    def test_partial_fault_and_explicit_retry(self):
        item = scenario(load(), "deploy_fault_partial_and_retry")
        status = replies(item)["PROGRAMMER STATUS P2"]
        self.assertEqual(json.loads(status[0][4:]),
                         {"progState": "ERROR", "queueCount": 1, "totalCount": 5, "remainingSeconds": 1})
        memory = {step["simulator_unit_name_bytes"]: step["hex"] for step in item["steps"]
                  if "simulator_unit_name_bytes" in step}
        self.assertNotEqual(memory["after_partial_P2"], memory["after_retry_P2"])
        self.assertEqual(replies(item)["DEPLOY_QUEUE RETRY P2"], ["200 OK: retry added"])
        # One final reply line per executed instruction.
        echoes = Counter(line.split(" ", 1)[0] for line in item["unsolicited"]["A"]
                         if line.split("] ", 1)[1][3:4] == " ")
        # Five instructions ran three times, except the fault's successor on the first run.
        self.assertEqual(echoes["[a4]"], 3)
        self.assertEqual(echoes["[a5]"], 2)
        self.assertIn("[a4] 408 Operation failed: Unit save failed (no response from unit)", item["unsolicited"]["A"])
        events = Counter(json.loads(event)["msg"] if isinstance(json.loads(event)["msg"], str)
                         else json.loads(event)["name"] for event in item["events"].keys()
                         for _ in range(item["events"][event]))
        self.assertEqual(events["removeTaskGroup: P2"], 2)
        self.assertEqual(events["addTaskGroup: P2"], 3)
        self.assertEqual(events["deploy-queue.started"], 3)
        self.assertEqual(item["injected_no_reply_stores"], 2)

    def test_queue_admission_and_error_texts(self):
        fixture = load()
        serial = replies(scenario(fixture, "serial_queue_pending_delete"))
        self.assertEqual(serial["DEPLOY_QUEUE DELETE Q1"], ["502 failed: could not remove programmer"])
        self.assertEqual(serial["DEPLOY_QUEUE DELETE Q3"], ["200 OK: deleted"])
        self.assertEqual(serial["DEPLOY_QUEUE RETRY Q2"], ["502 illegal state: INIT"])
        self.assertEqual(serial["DEPLOY_QUEUE DELETE_ALL PENDING"], ["120-deleted: Q2", "200 OK: done"])
        cancel = replies(scenario(fixture, "cancel_stop_and_retry_reinit"))
        self.assertEqual(cancel["PROGRAMMER CANCEL_INSTRUCTION C1 9"],
                         ["402 Operation not supported by: failed: command not found"])
        self.assertEqual(cancel["PROGRAMMER TRIGGER C1 START"],
                         ["400 Syntax Error: failed: transition of START is not allowed on STOPPED"])
        self.assertEqual(cancel["PROGRAMMER ADD_INSTRUCTION C1 PP_END S"],
                         ["402 Operation not supported by: failed: programmer in unsupported state"])
        terminal = replies(scenario(fixture, "terminal_add_and_retry_admission"))
        self.assertEqual(terminal["DEPLOY_QUEUE RETRY T1"], ["501 failed: could not retry programmer"])
        self.assertEqual(terminal["DEPLOY_QUEUE ADD E1"], ["200 OK: added"])
        orphan = replies(scenario(fixture, "delete_running_and_late_instruction"))
        self.assertEqual(orphan["DEPLOY_QUEUE DELETE_ALL"],
                         ["501-failed: could not delete programmer: D1", "200 OK: done"])

    def test_deadlock_and_restart_volatility(self):
        fixture = load()
        deadlock = scenario(fixture, "started_pause_resume_deadlock")
        resume = next(step for step in deadlock["steps"] if step.get("command") == "PROGRAMMER TRIGGER W1 RESUME")
        self.assertEqual(resume["reply"], [])
        self.assertIn("no_reply_within_seconds", resume)
        restart = replies(scenario(fixture, "restart_volatility"))
        self.assertEqual(restart["PROGRAMMER LIST"], ["450 no programmers registered."])
        self.assertEqual(restart["DEPLOY_QUEUE LIST"], ["450 no programmers registered."])
        self.assertEqual(restart["PP UNITS"], ["122 no open sessions"])
        self.assertEqual(restart["PP LIST_LOCK"], ["122 no open locks"])


@unittest.skipUnless(os.environ.get("CBUS_CGATE_JAVA") and os.environ.get("CBUS_LOCAL_CGATE_VENDOR"),
                     "Set Java and original vendor directory for owned local programmer lifecycle acceptance")
class NativeProgrammerLifecycleTests(unittest.TestCase):
    def test_owned_native_recapture_matches_committed_transcript(self):
        with tempfile.TemporaryDirectory() as directory:
            report = lifecycle.capture(output_dir=directory)
            destination = os.environ.get("CBUS_NATIVE_PROGRAMMER_LIFECYCLE_REPORT")
            if destination:
                path = Path(destination)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(report, indent=2) + "\n")
            self.assertTrue(report["local_service"]["cleanup_complete"])
            self.assertEqual(report["unsupported_simulator_requests"], [])
            self.assertEqual(lifecycle.comparable(report), load()["scenarios"])


if __name__ == "__main__":
    unittest.main()
