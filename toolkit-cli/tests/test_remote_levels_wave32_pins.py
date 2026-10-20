"""Wave-32 offline pins for thermostat remote Level guards (P5.05).

Each test pins a branch of ``toolkit-cli/src/cbus_toolkit/thermostat_remote_levels.py``
with zero prior test refs (verified via ``grep -rn --fixed-strings`` across
``tests/`` before writing; each exact string below returned 0 hits):
- ``normalize_level_prompts`` (defaults/order/shape guard).
- ``project_remote_levels`` (missing/unused/disabled/decline guards).
- ``Level prompts must map setback/schedule to accept or decline``.
- ``Level prompt response must be accept or decline: ``.
- ``Basic thermostat has no schedule Level prompt to accept``.

Synthetic RemoteGroup/RemoteLevel only; no hardware, vendor EXE, C-Gate, or radio.
"""
import unittest

from cbus_toolkit.thermostat_remote_levels import (
    RemoteLevelCreation,
    normalize_level_prompts,
    project_remote_levels,
)
from cbus_toolkit.thermostat_remote_references import RemoteGroup, RemoteLevel
from cbus_toolkit.thermostat_templates import ThermostatTemplateError


def make_group(application, address, present, *, identity='oid-g'):
    levels = tuple(
        RemoteLevel(n, str(n), 'oid-%d-%d-%d' % (application, address, n),
                    'Level %d' % n, '<meta/>')
        for n in present
    )
    return RemoteGroup(application, address, identity, 'G%d' % address,
                       'NetVar', '<meta/>', levels)


def prompts(setback='accept', schedule='decline'):
    return normalize_level_prompts({'setback': setback, 'schedule': schedule},
                                   'programmable')


class RemoteLevelsWave32Pins(unittest.TestCase):
    def test_normalize_defaults_order_and_shape_guard(self):
        self.assertEqual(normalize_level_prompts(None, 'programmable'),
                         (('setback', 'decline'), ('schedule', 'decline')))
        self.assertEqual(normalize_level_prompts({}, 'programmable'),
                         (('setback', 'decline'), ('schedule', 'decline')))
        self.assertEqual(normalize_level_prompts({'schedule': 'accept'}, 'programmable'),
                         (('setback', 'decline'), ('schedule', 'accept')))
        for bad in ([], True, {'other': 'accept'}, {1: 'accept'}, {True: 'accept'}):
            with self.subTest(value=bad), self.assertRaisesRegex(
                ThermostatTemplateError,
                'Level prompts must map setback/schedule to accept or decline',
            ):
                normalize_level_prompts(bad, 'programmable')

    def test_response_value_and_basic_family_guards(self):
        for phase in ('setback', 'schedule'):
            other = 'schedule' if phase == 'setback' else 'setback'
            for bad in (True, 1, 'ACCEPT', 'yes', None):
                with self.subTest(phase=phase, bad=bad), self.assertRaisesRegex(
                    ThermostatTemplateError,
                    'Level prompt response must be accept or decline: ' + phase,
                ):
                    normalize_level_prompts({phase: bad, other: 'decline'},
                                            'programmable')
        with self.assertRaisesRegex(
            ThermostatTemplateError,
            'Basic thermostat has no schedule Level prompt to accept',
        ):
            normalize_level_prompts({'setback': 'decline', 'schedule': 'accept'}, 'basic')
        self.assertEqual(
            normalize_level_prompts({'setback': 'accept', 'schedule': 'decline'}, 'basic'),
            (('setback', 'accept'), ('schedule', 'decline')))

    def test_missing_and_unused_groups_never_require(self):
        creations, receipts = project_remote_levels(
            {}, family='programmable', setback_source=2,
            schedule_enabled=True, prompts=prompts('accept', 'accept'))
        self.assertEqual(creations, ())
        for phase in ('setback', 'schedule'):
            receipt = receipts[phase]
            self.assertFalse(receipt['required'])
            self.assertFalse(receipt['offered'])
            self.assertFalse(receipt['executed'])
            self.assertIsNone(receipt['response_used'])
            self.assertEqual(receipt['created_count'], 0)
            for record in receipt['roles']:
                self.assertIsNone(record['application'])
                self.assertIsNone(record['group'])
                self.assertIsNone(record['group_identity'])
                self.assertTrue(record['unused'])
                self.assertEqual(record['missing_addresses'], [])
                self.assertEqual(record['created_addresses'], [])
        # Address-255 groups are unused with no missing addresses even when enabled.
        unused = make_group(56, 255, ())
        creations, receipts = project_remote_levels(
            {'setback_on': unused, 'setback_off': unused},
            family='programmable', setback_source=1,
            schedule_enabled=False, prompts=prompts('accept', 'decline'))
        self.assertEqual(creations, ())
        receipt = receipts['setback']
        self.assertFalse(receipt['required'])
        self.assertFalse(receipt['executed'])
        self.assertIsNone(receipt['response_used'])
        for record in receipt['roles']:
            self.assertTrue(record['unused'])
            self.assertEqual(record['missing_addresses'], [])

    def test_enabled_missing_accept_creates_decline_and_disabled_are_noops(self):
        present = tuple(range(2, 32))
        refs = {'setback_on': make_group(203, 21, present),
                'setback_off': make_group(203, 22, present)}
        creations, receipts = project_remote_levels(
            refs, family='programmable', setback_source=2,
            schedule_enabled=False, prompts=prompts('accept', 'decline'))
        self.assertEqual(len(creations), 2)
        first = creations[0]
        self.assertIs(type(first), RemoteLevelCreation)
        self.assertEqual(first.kind, 'Level')
        self.assertEqual(first.key, (203, 21, 1))
        self.assertEqual((first.application, first.group, first.address, first.value,
                          first.initial_name, first.name, first.role, first.phase),
                         (203, 21, 1, 1, 'Level 1', 'Setbk Enable Zone:unsw',
                          'setback_on', 'setback'))
        self.assertEqual(first.as_dict()['name'], 'Setbk Enable Zone:unsw')
        self.assertEqual([(c.group, c.address, c.role) for c in creations],
                         [(21, 1, 'setback_on'), (22, 1, 'setback_off')])
        setback = receipts['setback']
        self.assertTrue(setback['required'] and setback['offered'] and setback['executed'])
        self.assertEqual(setback['response_used'], 'accept')
        self.assertEqual(setback['created_count'], 2)
        self.assertEqual([r['created_addresses'] for r in setback['roles']], [[1], [1]])
        # Schedule disabled: never required even with missing groups absent.
        self.assertFalse(receipts['schedule']['required'])
        # Decline keeps required/offered but executes nothing.
        creations, receipts = project_remote_levels(
            refs, family='programmable', setback_source=2,
            schedule_enabled=False, prompts=prompts('decline', 'decline'))
        self.assertEqual(creations, ())
        declined = receipts['setback']
        self.assertTrue(declined['required'] and declined['offered'])
        self.assertFalse(declined['executed'])
        self.assertEqual(declined['response_used'], 'decline')
        self.assertEqual(declined['created_count'], 0)
        # Disabled source: never required even with missing addresses present.
        _, receipts = project_remote_levels(
            refs, family='programmable', setback_source=0,
            schedule_enabled=False, prompts=prompts('accept', 'decline'))
        self.assertFalse(receipts['setback']['required'])
        self.assertIsNone(receipts['setback']['response_used'])


if __name__ == '__main__':
    unittest.main()
