import os
import unittest
import uuid
from unittest.mock import patch

from cbus_toolkit.cgate import CGateClient, CGateResponse
from cbus_toolkit.native import NativeDatabase, NativeProjects
from cbus_toolkit.networks import NativeNetworks


class Capture:
    def __init__(self, states=()):
        self.commands = []
        self.states = iter(states)

    def command(self, command):
        self.commands.append(command)
        final = "300 state=" + next(self.states) if command.endswith(" state") else "200 OK."
        return CGateResponse((final,), final, int(final[:3]))


class NetworksTests(unittest.TestCase):
    def test_commissioning_grammar_keeps_operations_explicit(self):
        client = Capture()
        n = NativeNetworks(client)
        n.list()
        n.list("TEST")
        n.open("//TEST/254")
        n.close("//TEST/254")
        n.synchronize("//TEST/254", fast=True, retries=2)
        n.sync_new("//TEST/254", 4)
        n.discover("//TEST/254")
        n.check_units("//TEST/254", [4, 16])
        n.unravel("//TEST/254")
        n.unravel("//TEST/254", units=[4, 5], match_database=True)
        n.clocks("//TEST/254")
        n.clocks("//TEST/254", 3)
        n.clocks("//TEST/254", recover=True)
        n.tree("//TEST/254")
        n.tree("//TEST/254", details=True, sync=["withpsync"])
        n.rename("//TEST/254", 253)
        n.set_project_identity("//TEST/254", "TEST")
        self.assertEqual(client.commands, [
            "NET LIST_ALL", "NET LIST TEST", "NET OPEN //TEST/254", "NET CLOSE //TEST/254",
            "NET SYNC //TEST/254 fast 2", "NET SYNCNEW //TEST/254 4", "NET PINGU //TEST/254",
            "NET CHECKUNIT //TEST/254 4,16", "NET UNRAVEL //TEST/254", "NET UNRAVELUNIT //TEST/254 4,5 matchdb",
            "NET CLOCKS //TEST/254", "NET CLOCKS //TEST/254 3", "NET CLOCKS //TEST/254 R",
            "TREE //TEST/254", "TREEXMLDETAIL //TEST/254 withpsync", "NET RENAME //TEST/254 253",
            "NET SET_PROJECT_IDENTIFY //TEST/254 TEST"])

    def test_invalid_arguments_rejected_before_io(self):
        client = Capture()
        n = NativeNetworks(client)
        calls = [lambda: n.open("//TEST/254\nNOOP"), lambda: n.check_units("//TEST/254", []),
                 lambda: n.check_units("//TEST/254", [256]), lambda: n.clocks("//TEST/254", 3, recover=True),
                 lambda: n.clocks("//TEST/254", 0), lambda: n.clocks("//TEST/254", 11),
                 lambda: n.clocks("//TEST/254", True), lambda: n.clocks("//TEST/254", recover="true"),
                 lambda: n.synchronize("//TEST/254", retries=-1), lambda: n.rename("//TEST/254", True),
                 lambda: n.tree("//TEST/254", sync=["withsync"]),
                 lambda: n.tree("//TEST/254", xml=True, sync=["anything"]),
                 lambda: n.wait_ready("//TEST/254", timeout=float("inf"))]
        for call in calls:
            with self.assertRaises(ValueError):
                call()
        self.assertEqual(client.commands, [])

    def test_readiness_wait_observes_sync_then_ok_without_restarting(self):
        client = Capture(["sync", "sync", "ok"])
        with patch("cbus_toolkit.networks.time.sleep"):
            self.assertEqual(NativeNetworks(client).wait_ready("//TEST/254"), {"ready": True, "state": "ok"})
        self.assertEqual(client.commands, ["GET //TEST/254 state"] * 3)

    def test_readiness_wait_allows_background_startup_after_open(self):
        class Opening(Capture):
            def command(self, command):
                if command.endswith(" TargetInterfaceState"):
                    self.commands.append(command)
                    final = "300 //TEST/254: TargetInterfaceState=running"
                    return CGateResponse((final,), final, 300)
                return super().command(command)
        client = Opening(["new", "sync", "ok"])
        with patch("cbus_toolkit.networks.time.sleep"):
            self.assertTrue(NativeNetworks(client).wait_ready("//TEST/254")["ready"])
        self.assertEqual(client.commands, ["GET //TEST/254 state", "GET //TEST/254 TargetInterfaceState",
                                           "GET //TEST/254 state", "GET //TEST/254 state"])

    def test_readiness_error_and_timeout_never_report_success(self):
        with self.assertRaisesRegex(RuntimeError, "state=error"):
            NativeNetworks(Capture(["error"])).wait_ready("//TEST/254")
        with patch("cbus_toolkit.networks.time.monotonic", side_effect=[1, 3]):
            with self.assertRaisesRegex(RuntimeError, "timed out"):
                NativeNetworks(Capture(["sync"])).wait_ready("//TEST/254", timeout=1)


@unittest.skipUnless(os.environ.get("CBUS_CGATE_TEST_HOST"), "set CBUS_CGATE_TEST_HOST for native offline network acceptance")
class NativeNetworksTests(unittest.TestCase):
    def test_native_calculator_pass_and_fail_are_explicit(self):
        name = "K" + uuid.uuid4().hex[:7].upper()
        with CGateClient(os.environ["CBUS_CGATE_TEST_HOST"], int(os.environ.get("CBUS_CGATE_TEST_PORT", "20023"))) as client:
            projects, db, networks = NativeProjects(client), NativeDatabase(client), NativeNetworks(client)
            projects.operation("new", name)
            try:
                address = f"//{name}/254"
                db.create_network(name, 254, "Fixture", "Cni", "127.0.0.1:1")
                for number, kind, catalog in ((1, "KEY4", "5034N"), (2, "BURDEN", "5500BUR")):
                    db.add(address, "unit", number, catalog)
                    db.set(address + f"/p/{number}/UnitType", kind)
                    db.set(address + f"/p/{number}/CatalogNumber", catalog)
                result = networks.calculate(address)
                self.assertFalse(result["passed"])
                self.assertEqual(result["current_supply_ma"], 0)
                self.assertEqual(result["current_consumption_ma"], 18)
                db.add(address, "unit", 3, "Power supply")
                db.set(address + "/p/3/UnitType", "XPS55")
                db.set(address + "/p/3/CatalogNumber", "5500PS")
                result = networks.calculate(address)
                self.assertTrue(result["passed"])
                self.assertEqual(result["current_supply_ma"], 350)
                self.assertEqual(result["impedance_ohms"], 944)
                self.assertEqual(result["units_calculated"], 3)
            finally:
                projects.operation("close", name)

    def test_native_closed_model_list_state_tree_and_rename(self):
        name = "N" + uuid.uuid4().hex[:7].upper()
        with CGateClient(os.environ["CBUS_CGATE_TEST_HOST"], int(os.environ.get("CBUS_CGATE_TEST_PORT", "20023"))) as client:
            projects, db, networks = NativeProjects(client), NativeDatabase(client), NativeNetworks(client)
            projects.operation("new", name)
            try:
                db.create_network(name, 254, "Fixture", "Cni", "127.0.0.1:1")
                self.assertIn("254", " ".join(networks.list(name).lines))
                self.assertIn(networks.state(f"//{name}/254"), ("new", "closed"))
                self.assertIn("<Network>", " ".join(networks.tree(f"//{name}/254", details=True).lines))
                with self.assertRaisesRegex(RuntimeError, "not ready"):
                    networks.wait_ready(f"//{name}/254")
                networks.rename(f"//{name}/254", 253)
                self.assertIn(networks.state(f"//{name}/253"), ("new", "closed"))
            finally:
                projects.operation("close", name)


if __name__ == "__main__":
    unittest.main()
