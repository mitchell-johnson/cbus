"""Literal explicit DIN control histories; no original instructions execute."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import unittest

from cbus_toolkit.din_output_controls import CONTROL_PLAN_FORMAT, DinControlPlan
from cbus_toolkit.din_output_settings import DinOutputEditor, DinSettingsError, PROFILES
from cbus_toolkit.unitspec import ParameterSpec
from test_din_output_save import NoSession, seed
from test_din_output_settings import fixture, session


ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / 'research/fixtures/din-output-controls-source-review.json'


def make(unit_type='DIMDN4', **values):
    live = session(unit_type)
    live.current.update({key: ' '.join(map(str, row)) for key, row in values.items()})
    return live, DinOutputEditor(live.spec, unit_type)


def final(plan, name):
    return plan.changes.get(name, plan.expected[name])


class DinControlHistoryTest(unittest.TestCase):
    def test_all_profiles_stagger_literals_mapping_and_one_save(self):
        literals = {
            'RELDN4': [63, 127, 191, 255],
            'RELDN8': [30, 61, 91, 122, 153, 183, 214, 255],
            'RELDN8B': [30, 61, 91, 122, 153, 183, 214, 255],
            'RELDN12': [20, 40, 61, 81, 102, 122, 142, 163, 183, 204, 224, 255],
            'DIMDN4': [63, 127, 191, 255], 'DIMDN4F': [63, 127, 191, 255],
            'DIMDN8': [40, 71, 102, 132, 163, 193, 224, 255],
            'DIMDN8F': [40, 71, 102, 132, 163, 193, 224, 255],
        }
        for unit_type, profile in PROFILES.items():
            for save in (False, True):
                with self.subTest(unit_type=unit_type, toolkit_save=save):
                    live = seed(unit_type)
                    editor = DinOutputEditor(live.spec, unit_type)
                    before = editor.snapshot(live.values())
                    operation = {'op': 'stagger-turn-on' if profile.relay else 'stagger-maximum',
                                 'step_percent': 100 // profile.channels}
                    plan = editor.control_plan(live.values(), [operation], toolkit_save=save)
                    field = 'MinDimmingLevel' if profile.relay else 'MaxDimmingLevel'
                    self.assertEqual([final(plan, field)[index] for index in profile.indices], literals[unit_type])
                    self.assertEqual(DinControlPlan.from_dict(json.loads(json.dumps(plan.as_dict()))), plan)
                    self.assertEqual(plan.as_dict()['format'], CONTROL_PLAN_FORMAT)
                    self.assertEqual(plan.settings_plan.toolkit_save, save)
                    if unit_type == 'RELDN8':
                        self.assertEqual(final(plan, 'MaxDimmingLevel'), (201, 202, 203, 0) if save else before['MaxDimmingLevel'])
                        self.assertEqual(final(plan, 'MinDimmingLevel')[11], before['MinDimmingLevel'][11])
                    # Every other field stays owned by the separate save projector.
                    expected_other = editor._toolkit_save(before) if save else before
                    for name in set(before) - {field, 'MinDimmingLevel'}:
                        self.assertEqual(tuple(final(plan, name)), tuple(expected_other[name]), name)
                    result = editor.apply(live, plan)
                    self.assertTrue(result['verified'])
                    self.assertEqual(result['format'], CONTROL_PLAN_FORMAT)
                    self.assertEqual(editor.snapshot(live.values()), dict(plan.expected, **plan.changes))
                    self.assertEqual(live.current['UnitAddress'], '255')

    def test_all_delay_choices_literal_and_sync_commit_order(self):
        cases = {
            5: (5, 10, 15, 20, 25, 30, 35, 40),
            10: (10, 20, 30, 40, 50, 60, 61, 62),
            20: (20, 40, 60, 62, 64, 66, 68, 70),
            30: (30, 60, 63, 66, 69, 72, 75, 78),
        }
        for unit_type in ('DIMDN4', 'DIMDN4F', 'DIMDN8', 'DIMDN8F'):
            live, editor = make(unit_type)
            for step, expected in cases.items():
                with self.subTest(unit_type=unit_type, step=step):
                    plan = editor.control_plan(live.values(), [
                        {'op': 'synchronise', 'tab': 'recovery', 'enabled': True},
                        {'op': 'stagger-recovery-delay', 'step_seconds': step},
                    ])
                    self.assertEqual(final(plan, 'PowerUpDelay'), expected[:editor.profile.channels])
                    self.assertFalse(plan.final_controls['synchronise']['recovery'])
        live, editor = make()
        plan = editor.control_plan(live.values(), [
            {'op': 'synchronise', 'tab': 'recovery', 'enabled': True},
            {'op': 'recovery-delay', 'channel': 2, 'raw': 61},
        ])
        self.assertEqual(final(plan, 'PowerUpDelay'), (61, 61, 61, 61))
        events = plan.control_history[1]['events']
        self.assertEqual([event['channel'] for event in events if event['event'] == 'parameter-write'], [1, 3, 4, 2])
        # Delay sync ignores level store (all fixture channels have it enabled).
        self.assertEqual(final(plan, 'LevelStoreEnable'), (1, 1, 1, 1))

    def test_synchronised_coupling_history_and_stagger_cancels_sync(self):
        live, editor = make(MinDimmingLevel=[0] * 4, MaxDimmingLevel=[51, 127, 178, 229])
        operations = [
            {'op': 'synchronise', 'tab': 'turn-on', 'enabled': True},
            {'op': 'minimum', 'channel': 1, 'percent': 30},
            {'op': 'maximum', 'channel': 2, 'percent': 20},
            {'op': 'stagger-minimum', 'step_percent': 1},
            {'op': 'minimum', 'channel': 1, 'percent': 10},
        ]
        plan = editor.control_plan(live.values(), operations)
        first = plan.control_history[1]
        self.assertEqual(first['controls']['positions']['minimum'], (30, 30, 30, 30))
        self.assertEqual(first['controls']['positions']['maximum'], (31, 31, 31, 31))
        self.assertEqual([event['slider'] for event in first['events'] if event['event'] == 'synchronise'],
                         ['maximum', 'minimum'])
        self.assertEqual(plan.control_history[2]['controls']['positions']['minimum'], (19, 19, 19, 19))
        self.assertEqual(final(plan, 'MinDimmingLevel'), (25, 5, 7, 10))
        self.assertEqual(final(plan, 'MaxDimmingLevel'), (51, 51, 51, 51))
        self.assertFalse(plan.final_controls['synchronise']['turn-on'])
        reversed_plan = editor.control_plan(live.values(), [operations[0], operations[2], operations[1]])
        self.assertEqual(final(reversed_plan, 'MinDimmingLevel'), (76, 76, 76, 76))

    def test_same_position_preserves_noncanonical_raw_and_no_propagation(self):
        live, editor = make(MinDimmingLevel=[26, 51, 76, 102])
        plan = editor.control_plan(live.values(), [
            {'op': 'synchronise', 'tab': 'turn-on', 'enabled': True},
            {'op': 'minimum', 'channel': 1, 'percent': 10},
        ])
        self.assertEqual(plan.changes, {})
        self.assertEqual(plan.control_history[1]['events'], ({
            'event': 'same-position', 'channel': 1, 'slider': 'minimum', 'value': 10},))
        # Checking Synchronise alone never copies any slider.
        self.assertEqual(plan.control_history[0]['controls']['positions']['minimum'], (10, 20, 30, 40))

    def test_clamped_coupling_depends_on_whether_partner_position_changes(self):
        cases = (
            ([0] * 4, [229] * 4, 'minimum', 100, 252, 255),
            ([0] * 4, [255] * 4, 'minimum', 100, 255, 255),
            ([25] * 4, [229] * 4, 'maximum', 0, 0, 2),
            ([0] * 4, [229] * 4, 'maximum', 0, 0, 0),
        )
        for mins, maxes, slider, percent, expected_min, expected_max in cases:
            with self.subTest(slider=slider, mins=mins[0], maxes=maxes[0]):
                live, editor = make(MinDimmingLevel=mins, MaxDimmingLevel=maxes)
                plan = editor.control_plan(live.values(), [{'op': slider, 'channel': 1, 'percent': percent}])
                self.assertEqual(final(plan, 'MinDimmingLevel')[0], expected_min)
                self.assertEqual(final(plan, 'MaxDimmingLevel')[0], expected_max)

    def test_sync_endpoints_keep_distinct_sender_and_guarded_target_positions(self):
        live, editor = make(MinDimmingLevel=[0] * 4, MaxDimmingLevel=[255, 252, 252, 252])
        plan = editor.control_plan(live.values(), [
            {'op': 'synchronise', 'tab': 'turn-on', 'enabled': True},
            {'op': 'minimum', 'channel': 1, 'percent': 100},
        ])
        self.assertEqual(final(plan, 'MinDimmingLevel'), (255, 252, 252, 252))
        self.assertEqual(final(plan, 'MaxDimmingLevel'), (255, 255, 255, 255))
        live, editor = make(MinDimmingLevel=[0, 2, 2, 2], MaxDimmingLevel=[255] * 4)
        plan = editor.control_plan(live.values(), [
            {'op': 'synchronise', 'tab': 'turn-on', 'enabled': True},
            {'op': 'maximum', 'channel': 1, 'percent': 0},
        ])
        self.assertEqual(final(plan, 'MinDimmingLevel'), (0, 0, 0, 0))
        self.assertEqual(final(plan, 'MaxDimmingLevel'), (0, 2, 2, 2))
        live, editor = make(MinDimmingLevel=[0] * 4, MaxDimmingLevel=[253] * 4)
        plan = editor.control_plan(live.values(), [{'op': 'minimum', 'channel': 1, 'percent': 100}])
        self.assertEqual(final(plan, 'MinDimmingLevel')[0], 255)
        self.assertEqual(final(plan, 'MaxDimmingLevel')[0], 253)

    def test_strict_schema_hidden_controls_and_initial_delay_boundary(self):
        live, editor = make()
        bad = ([], {}, [None], [{'op': 'minimum', 'channel': True, 'percent': 1}],
               [{'op': 'minimum', 'channel': 1, 'percent': 1.0}],
               [{'op': 'minimum', 'channel': 1, 'percent': 1, 'extra': 0}],
               [{'op': 'stagger-minimum', 'step_percent': 26}],
               [{'op': 'stagger-recovery-delay', 'step_seconds': 15}],
               [{'op': 'synchronise', 'tab': 'turn-on', 'enabled': 1}],
               [{'op': 'recovery-level', 'channel': 1, 'percent': 10}],
               [{'op': 'stagger-turn-on', 'step_percent': 1}])
        for operations in bad:
            with self.subTest(operations=operations), self.assertRaises(DinSettingsError):
                editor.control_plan(live.values(), operations)
        for op in ('maximum', 'stagger-maximum', 'stagger-minimum', 'recovery-delay', 'stagger-recovery-delay'):
            live, relay = make('RELDN8')
            row = {'op': op, **({'channel': 1, 'percent': 10} if op == 'maximum' else
                               {'channel': 1, 'raw': 10} if op == 'recovery-delay' else
                               {'step_seconds': 10} if op == 'stagger-recovery-delay' else {'step_percent': 1})}
            with self.subTest(op=op), self.assertRaisesRegex(DinSettingsError, 'hides'):
                relay.control_plan(live.values(), [row])
        live, editor = make(PowerUpDelay=[0, 5, 5, 5])
        with self.assertRaisesRegex(DinSettingsError, 'initial clamp'):
            editor.control_plan(live.values(), [{'op': 'recovery-delay', 'channel': 2, 'raw': 10}])
        # Unrelated turn-on control can retain inspectable out-of-domain delay.
        self.assertEqual(final(editor.control_plan(live.values(), [
            {'op': 'minimum', 'channel': 1, 'percent': 10}]), 'PowerUpDelay'), (0, 5, 5, 5))
        plan = editor.control_plan(live.values(), [{'op': 'synchronise', 'tab': 'recovery', 'enabled': True}])
        self.assertEqual(plan.initial_controls['positions']['recovery-delay'], (5, 5, 5, 5))

    def test_imported_history_replay_stale_and_width_guard_before_writes(self):
        live, editor = make()
        plan = editor.control_plan(live.values(), [{'op': 'minimum', 'channel': 1, 'percent': 10}])
        original = plan.as_dict()
        mutations = (
            lambda doc: doc['operations'][0].update(percent=20),
            lambda doc: doc['control_history'][0]['events'].clear(),
            lambda doc: doc['final_controls']['synchronise'].update({'turn-on': True}),
            lambda doc: doc['changes']['MinDimmingLevel'].__setitem__(0, True),
            lambda doc: doc['settings_plan']['expected']['PowerUpDelay'].__setitem__(0, 5.0),
            lambda doc: doc.update(toolkit_save=True),
        )
        for mutate in mutations:
            document = deepcopy(original)
            mutate(document)
            with self.assertRaises(DinSettingsError):
                editor.apply(NoSession(), DinControlPlan.from_dict(document))
        # Both duplicate summaries changed coherently still cannot bypass replay.
        document = deepcopy(original)
        document['changes']['MinDimmingLevel'][0] = 51
        document['settings_plan']['changes']['MinDimmingLevel'][0] = 51
        with self.assertRaisesRegex(DinSettingsError, 'ordered control history'):
            editor.apply(NoSession(), DinControlPlan.from_dict(document))
        forged = replace(plan, operations=({'op': 'minimum', 'channel': 1, 'percent': True},))
        with self.assertRaises(DinSettingsError):
            editor.apply(NoSession(), forged)
        live.current['RestrikeDelay'] = '61'
        with self.assertRaisesRegex(DinSettingsError, 'changed since'):
            editor.apply(live, plan)
        self.assertEqual(live.calls, [])
        live, _ = make()
        live.spec = fixture('DIMDN4')
        parameter = live.spec.parameters['MinDimmingLevel']
        live.spec.parameters['MinDimmingLevel'] = ParameterSpec(
            parameter.name, parameter.type, parameter.source, dict(parameter.fields, BitSize='4'))
        with self.assertRaisesRegex(DinSettingsError, 'BitSize'):
            editor.apply(live, plan)
        self.assertEqual(live.calls, [])


class DinControlSourceTest(unittest.TestCase):
    def test_source_scope_and_literal_constant(self):
        receipt = json.loads(RECEIPT.read_text())
        self.assertFalse(receipt['original_code_executed'])
        self.assertEqual(receipt['plan_format'], CONTROL_PLAN_FORMAT)
        self.assertEqual(set(receipt['profiles']), set(PROFILES))
        self.assertEqual(receipt['delay_stagger']['extended_hex'], '911ea89cddc2afc6fb3f')
        self.assertGreaterEqual(len(receipt['methods']), 30)

    @unittest.skipUnless(os.environ.get('CBUS_TOOLKIT_EXE'), 'requires pinned original bytes for static hash check only')
    def test_static_method_and_constant_bytes_without_execution(self):
        import pefile

        receipt = json.loads(RECEIPT.read_text())
        raw = Path(os.environ['CBUS_TOOLKIT_EXE']).read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), receipt['toolkit_exe_sha256'])
        pe = pefile.PE(data=raw)
        for method in receipt['methods']:
            start, end = int(method['start'], 16), int(method['end'], 16)
            data = pe.get_data(start - pe.OPTIONAL_HEADER.ImageBase, end - start)
            self.assertEqual(hashlib.sha256(data).hexdigest(), method['sha256'], method['name'])
        data = pe.get_data(0xef76ec - pe.OPTIONAL_HEADER.ImageBase, 10)
        self.assertEqual(data.hex(), receipt['delay_stagger']['extended_hex'])
