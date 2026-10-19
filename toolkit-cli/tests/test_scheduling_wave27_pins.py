"""Wave27 narrow offline pins for thermostat scheduling guards (P5.05).

Offline only: no I/O, no native writes, no network. Pins model-level guards
in thermostat_scheduling.py with no prior coverage.
"""
import unittest

from cbus_toolkit.thermostat_scheduling import ScheduleGroup, ThermostatScheduling


class SchedulingWave27Pins(unittest.TestCase):
    def test_dangling_role_reference_rejected_at_load(self):
        model = ThermostatScheduling()
        with self.assertRaisesRegex(ValueError, 'null or reference'):
            model.load([ScheduleGroup('a', 1)], on='ghost', enabled=True)

    def test_empty_nul_and_oversize_group_identity_rejected(self):
        model = ThermostatScheduling()
        for bad in ('', 'a\0b', 'x' * 129):
            with self.subTest(bad=repr(bad)[:20]):
                with self.assertRaisesRegex(ValueError, 'nonempty bounded text'):
                    model.load([ScheduleGroup(bad, 1)], on=bad, enabled=True)

    def test_noncallable_level_and_storage_providers_rejected(self):
        model = ThermostatScheduling()
        state = model.load([ScheduleGroup('a', 1)], on='a', enabled=True)
        with self.assertRaisesRegex(ValueError, 'callable or absent'):
            model.create_levels(state, policy='direct', level_save=42)
        with self.assertRaisesRegex(ValueError, 'callable or absent'):
            model.create_levels(state, policy='direct', storage_save='nope')

    def test_noncallable_end_save_lock_provider_rejected(self):
        model = ThermostatScheduling()
        state = model.load([ScheduleGroup('a', 1)], on='a', enabled=True,
                           save_lock=1, pending_save=True)
        with self.assertRaisesRegex(ValueError, 'callable or absent'):
            model.end_save_lock(state, storage_save=7)


if __name__ == '__main__':
    unittest.main()
