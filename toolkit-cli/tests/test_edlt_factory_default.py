"""Guarded physical eDLT FactoryDefault requests and honest receipts."""
from dataclasses import replace
import unittest

from cbus_toolkit.cgate import CGateError
from cbus_toolkit.edlt_factory_default import (
    EdltFactoryDefault,
    EdltFactoryDefaultPlan,
    EdltFactoryDefaultUncertain,
)
from tests.test_physical_addressing import PhysicalClient, NET, reply


class FactoryClient(PhysicalClient):
    def __init__(self):
        super().__init__()
        self.factory_result = reply("202 Done: " + NET + "/p/5")
        self.factory_exception = None

    def command(self, command):
        if command.startswith("DO ") and command.endswith(" FactoryDefault"):
            self.commands.append(command)
            if self.factory_exception is not None:
                self.connected = False
                raise self.factory_exception
            return self.factory_result
        return super().command(command)


class EdltFactoryDefaultTests(unittest.TestCase):
    def setUp(self):
        self.client = FactoryClient()
        self.manager = EdltFactoryDefault(self.client)
        self.source = NET + "/p/5"

    def plan(self):
        return self.manager.plan(self.source, expected_serial="101183.1666")

    def test_plan_and_request_repeat_identity_guards_then_send_once(self):
        plan = self.plan()
        self.assertEqual(plan.as_dict()["native_command"], "DO " + self.source + " FactoryDefault")
        self.assertFalse(plan.as_dict()["request_attempted"])
        self.assertFalse(any(command.startswith("DO ") for command in self.client.commands))
        result = self.manager.request(plan)
        self.assertEqual(result["outcome"], "native_accepted")
        self.assertTrue(result["factory_default_control_accepted"])
        self.assertFalse(result["physical_factory_reset_verified"])
        self.assertFalse(result["factory_defaults_readback_verified"])
        self.assertFalse(result["address_preserved_verified"])
        self.assertFalse(result["device_reboot_verified"])
        self.assertFalse(result["persistence_verified"])
        self.assertFalse(result["database_updated"])
        self.assertEqual(result["automatic_retries"], 0)
        self.assertEqual(self.client.commands[-1], "DO " + self.source + " FactoryDefault")
        self.assertEqual(sum(command.startswith("DO ") for command in self.client.commands), 1)

    def test_wrong_profile_invalid_path_forged_or_stale_plan_never_sends(self):
        for source in (None, "/db" + self.source, NET + "/p/0", NET + "/p/255", NET + "/p/05"):
            with self.subTest(source=source), self.assertRaises(ValueError):
                self.manager.plan(source, expected_serial="101183.1666")
        for field, value in (("Type", "KEYGL4"), ("Version", "5.4.00"), ("State", "sync")):
            client = FactoryClient()
            client.units[5][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                EdltFactoryDefault(client).plan(self.source, expected_serial="101183.1666")
            self.assertFalse(any(command.startswith("DO ") for command in client.commands))
        plan = self.plan()
        for forged in (
            replace(plan, database_hash="changed"),
            replace(plan, unit_type="KEYGL4"),
            replace(plan, inventory=plan.inventory + (plan.inventory[0],)),
        ):
            with self.assertRaises(ValueError):
                self.manager.request(forged)
        self.client.units[5]["SerialNumber"] = "123.456"
        with self.assertRaises(ValueError):
            self.manager.request(plan)
        self.assertFalse(any(command.startswith("DO ") for command in self.client.commands))

    def test_complete_rejection_and_lost_reply_remain_distinct_without_replay(self):
        client = FactoryClient()
        manager = EdltFactoryDefault(client)
        plan = manager.plan(self.source, expected_serial="101183.1666")
        client.factory_exception = CGateError(reply("502 eDLT factory default failed: unit rejected"))
        rejected = manager.request(plan)
        self.assertEqual(rejected["outcome"], "native_rejected")
        self.assertTrue(rejected["device_side_effect_possible"])
        self.assertEqual(sum(command.startswith("DO ") for command in client.commands), 1)

        client = FactoryClient()
        manager = EdltFactoryDefault(client)
        plan = manager.plan(self.source, expected_serial="101183.1666")
        client.factory_exception = ConnectionError("lost reset reply")
        with self.assertRaises(EdltFactoryDefaultUncertain) as caught:
            manager.request(plan)
        self.assertEqual(caught.exception.details["outcome"], "outcome_uncertain")
        self.assertEqual(sum(command.startswith("DO ") for command in client.commands), 1)
        self.assertEqual(client.commands[-1], "DO " + self.source + " FactoryDefault")

    def test_noncanonical_plan_and_interruption_preserve_first_evidence(self):
        class DerivedPlan(EdltFactoryDefaultPlan):
            pass

        plan = self.plan()
        with self.assertRaises(ValueError):
            self.manager.request(DerivedPlan(**plan.__dict__))
        interruption = KeyboardInterrupt("stop after send")
        self.client.factory_exception = interruption
        with self.assertRaises(KeyboardInterrupt) as caught:
            self.manager.request(plan)
        self.assertIs(caught.exception, interruption)
        self.assertIs(interruption.edlt_factory_default_evidence, self.manager.last_evidence)
        self.assertEqual(self.manager.last_evidence["outcome"], "outcome_uncertain")
        self.assertEqual(sum(command.startswith("DO ") for command in self.client.commands), 1)


if __name__ == "__main__":
    unittest.main()
