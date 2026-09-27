import os
import unittest
import uuid
from unittest.mock import patch

from cbus_toolkit.cgate import CGateClient, CGateResponse
from cbus_toolkit.native import NativeDatabase, NativeProjects
from cbus_toolkit.networks import LearnGrade, NativeNetworks


class Capture:
    def __init__(self, states=()):
        self.commands = []
        self.states = iter(states)

    def command(self, command):
        self.commands.append(command)
        final = "300 state=" + next(self.states) if command.endswith(" state") else "200 OK."
        return CGateResponse((final,), final, int(final[:3]))


class NetworksTests(unittest.TestCase):
    def test_typed_learn_grades_emit_exact_native_commands(self):
        client = Capture()
        networks = NativeNetworks(client)
        grades = (
            ("init-relay", "1"),
            ("init_dim", "2"),
            ("cancel", "$80"),
            (LearnGrade.EXIT_RELAY, "$81"),
            (130, "$82"),
            ("$83", "$83"),
        )
        receipts = [
            networks.learn("//TEST/254", 56, grade, 1)
            for grade, _token in grades
        ]
        self.assertEqual(
            client.commands,
            [
                f"NET LEARN //TEST/254 56 {token} 1"
                for _grade, token in grades
            ],
        )
        receipt = receipts[2].as_dict()
        self.assertEqual(receipt["format"], "cbus-cgate-network-management-v1")
        self.assertEqual(receipt["operation"], "net-learn")
        self.assertEqual(receipt["network"], "//TEST/254")
        self.assertEqual(receipt["carrier_application"], 56)
        self.assertEqual(receipt["selector"], "learn-grade")
        self.assertEqual(
            receipt["target"],
            {"grade": "cancel", "grade_value": 128, "group": 1},
        )
        self.assertIsNone(receipt["mode"])
        self.assertTrue(receipt["cgate_accepted"])
        self.assertTrue(receipt["interface_delivery_confirmed"])
        for field in (
            "device_action_verified",
            "physical_state_readback",
            "persistence_verified",
            "automatic_replay",
        ):
            self.assertFalse(receipt[field])

    def test_all_typed_locate_selectors_emit_exact_native_commands(self):
        client = Capture()
        networks = NativeNetworks(client)
        receipts = (
            networks.locate_unit("//TEST/254/208", 1, "ON"),
            networks.locate_application("//TEST/254/208", 56, 2),
            networks.locate_group("//TEST/254/208", 56, 1, "OFF"),
            networks.locate_serial("//TEST/254/208", 1, "12345.67", 255),
        )
        self.assertEqual(
            client.commands,
            [
                "NETWORK LOCATE //TEST/254/208 UNIT 1 ON",
                "NETWORK LOCATE //TEST/254/208 APP 56 2",
                "NETWORK LOCATE //TEST/254/208 GROUP 56 1 OFF",
                "NETWORK LOCATE //TEST/254/208 SERIAL 1 12345.67 255",
            ],
        )
        self.assertEqual(
            [receipt.as_dict()["selector"] for receipt in receipts],
            ["unit", "app", "group", "serial"],
        )
        self.assertEqual(
            [receipt.as_dict()["mode"] for receipt in receipts],
            [
                {"value": 1, "name": "on"},
                {"value": 2, "name": "byte"},
                {"value": 0, "name": "off"},
                {"value": 255, "name": "byte"},
            ],
        )
        self.assertEqual(
            receipts[-1].as_dict()["target"],
            {"manufacturer": 1, "serial": "12345.67"},
        )
        self.assertEqual(receipts[-1].as_dict()["carrier_application"], 208)

    def test_network_management_invalid_values_refuse_before_command(self):
        client = Capture()
        networks = NativeNetworks(client)
        calls = (
            lambda: networks.learn("//TEST/254/208", 56, 1, 1),
            lambda: networks.learn("//TEST/256", 56, 1, 1),
            lambda: networks.learn("//TEST/254", True, 1, 1),
            lambda: networks.learn("//TEST/254", 56, 3, 1),
            lambda: networks.learn("//TEST/254", 56, 1, 256),
            lambda: networks.locate_unit("//TEST/254/56", 1, "ON"),
            lambda: networks.locate_unit("//TEST/254/208", True, "ON"),
            lambda: networks.locate_unit("//TEST/254/208", 1, 256),
            lambda: networks.locate_application("//TEST/254/208", 255, 1),
            lambda: networks.locate_group("//TEST/254/208", 56, 255, 1),
            lambda: networks.locate_serial("//TEST/254/208", True, "1.2", 1),
            lambda: networks.locate_serial("//TEST/254/208", 1, "1048576.0", 1),
            lambda: networks.locate_serial("//TEST/254/208", 1, "1.4096", 1),
        )
        for call in calls:
            with self.assertRaises(ValueError):
                call()
        self.assertEqual(client.commands, [])

    def test_network_management_requires_exact_200_receipt(self):
        class Rejected(Capture):
            def command(self, command):
                self.commands.append(command)
                return CGateResponse(
                    ("202 Request accepted.",), "202 Request accepted.", 202,
                )

        client = Rejected()
        with self.assertRaisesRegex(RuntimeError, "NET LEARN did not complete"):
            NativeNetworks(client).learn("//TEST/254", 56, 1, 1)
        self.assertEqual(client.commands, ["NET LEARN //TEST/254 56 1 1"])

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
        n.set_project_identity("//TEST/254", "a-b_")
        n.set_project_identity("//TEST/254", 'A B"\\C')
        n.set_project_identity("//TEST/254", "ſest")
        self.assertEqual(client.commands, [
            "NET LIST_ALL", "NET LIST TEST", "NET OPEN //TEST/254", "NET CLOSE //TEST/254",
            "NET SYNC //TEST/254 fast 2", "NET SYNCNEW //TEST/254 4", "NET PINGU //TEST/254",
            "NET CHECKUNIT //TEST/254 4,16", "NET UNRAVEL //TEST/254", "NET UNRAVELUNIT //TEST/254 4,5 matchdb",
            "NET CLOCKS //TEST/254", "NET CLOCKS //TEST/254 3", "NET CLOCKS //TEST/254 R",
            "TREE //TEST/254", "TREEXMLDETAIL //TEST/254 withpsync", "NET RENAME //TEST/254 253",
            "NET SET_PROJECT_IDENTIFY //TEST/254 TEST", "NET SET_PROJECT_IDENTIFY //TEST/254 a-b_",
            r'NET SET_PROJECT_IDENTIFY //TEST/254 "A\ B\"\\C"',
            "NET SET_PROJECT_IDENTIFY //TEST/254 ſest"])

    def test_invalid_arguments_rejected_before_io(self):
        client = Capture()
        n = NativeNetworks(client)
        calls = [lambda: n.open("//TEST/254\nNOOP"), lambda: n.check_units("//TEST/254", []),
                 lambda: n.check_units("//TEST/254", [256]), lambda: n.clocks("//TEST/254", 3, recover=True),
                 lambda: n.clocks("//TEST/254", 0), lambda: n.clocks("//TEST/254", 11),
                 lambda: n.clocks("//TEST/254", True), lambda: n.clocks("//TEST/254", recover="true"),
                 lambda: n.synchronize("//TEST/254", retries=-1), lambda: n.rename("//TEST/254", True),
                 lambda: n.set_project_identity("//TEST/254", "TOOLONG99"),
                 lambda: n.set_project_identity("//TEST/254", "{"),
                 lambda: n.set_project_identity("//TEST/254", "café"),
                 lambda: n.set_project_identity("//TEST/254", "ßßßßß"),
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
