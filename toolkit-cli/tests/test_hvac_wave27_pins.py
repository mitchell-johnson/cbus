"""Wave-27 offline pins for HVAC guards with zero prior test refs.

Covers only guards in cbus_toolkit/edlt_hvac.py that no existing test
references: existing precision/units repair, standby RestoreLevel on apply,
truncated record and foreign plan on apply.
Offline: synthetic fixture + Session only, no Toolkit/C-Gate/hardware.
"""
import unittest
from dataclasses import replace

from cbus_toolkit.edlt import EdltError, _field
from cbus_toolkit.edlt_hvac import EdltHVACTemperatureWidget
from tests.test_edlt import Session
from tests.test_edlt_hvac import fixture


class HvacWave27Pins(unittest.TestCase):
    def setUp(self):
        self.spec = fixture()
        self.editor = EdltHVACTemperatureWidget(self.spec)
        self.session = Session(self.spec)

    def plan(self, current=None, **options):
        settings = dict(page=1, position=1, group=255)
        settings.update(options)
        return self.editor.plan(
            self.session.values() if current is None else current, **settings
        )

    def test_existing_precision_requires_decimal_places(self):
        current = {**self.plan().expected, **self.plan().changes}
        current[_field(6, 3)] = (255,)
        with self.assertRaisesRegex(
            EdltError, r'Existing HVAC precision; supply decimal_places to repair'
        ):
            self.plan(current)
        self.assertEqual(self.plan(current, decimal_places=2).decimal_places, 2)

    def test_existing_units_requires_units(self):
        current = {**self.plan().expected, **self.plan().changes}
        current[_field(6, 4)] = (255,)
        with self.assertRaisesRegex(
            EdltError, r'Existing HVAC units; supply units to repair'
        ):
            self.plan(current)
        self.assertEqual(self.plan(current, units='fahrenheit').units, 'fahrenheit')

    def test_standby_restore_level_rejected_on_apply(self):
        standby = self.plan(page=0, position=1)
        self.assertIsNone(standby.restore_level)
        forged = replace(standby, restore_level=0)
        with self.assertRaisesRegex(
            EdltError, r'Standby widgets have no RestoreLevel'
        ):
            self.editor.apply(self.session, forged)

    def test_truncated_record_and_foreign_plan_rejected_on_apply(self):
        plan = self.plan()
        truncated = replace(plan, record=bytes(31))
        with self.assertRaisesRegex(
            EdltError, r'Plan records must contain32 bytes'
        ):
            self.editor.apply(self.session, truncated)
        with self.assertRaisesRegex(EdltError, r'Use an HVAC plan'):
            self.editor.apply(self.session, {'not': 'a plan'})


if __name__ == '__main__':
    unittest.main()
