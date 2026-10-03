"""Literal DIN agent-save cases, independent of the production projector."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import unittest

from cbus_toolkit.din_output_settings import (
    FIELDS, PROFILES, DinOutputEditor, DinPlan, DinSettingsApplyError, DinSettingsError,
    TOOLKIT_SAVE_PLAN_FORMAT)
from cbus_toolkit.memory import MemoryImage
from cbus_toolkit.unitspec import ParameterSpec
from test_din_output_settings import fixture, session


ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / 'research/fixtures/din-output-save-source-review.json'


def seed(unit_type):
    live = session(unit_type)
    size = len(live.current['LevelStoreEnable'].split())
    live.current.update({
        'GroupAddress': ' '.join(str(40 + n) for n in range(16)),
        'LightLevel': ' '.join(str(10 + n) for n in range(16)),
        'LevelStoreEnable': ' '.join(str(1 - n % 2) for n in range(size)),
        'LogicLevelStoreEnable': '1 0 1 0', 'InterLockingChannel': '250',
        'MinDimmingLevel': ' '.join(str(20 + n) for n in range(size)),
        'PowerUpDelay': ' '.join(str(30 + n) for n in range(size)),
        'MaxDimmingLevel': ' '.join(str(200 + n)
                                  for n in range(len(live.current['MaxDimmingLevel'].split()))),
    })
    # Distinct hidden bit tails ensure a short write is not mistaken for padding.
    for name in ('LogicGA13Associations', 'LogicGA14Associations', 'LogicGA15Associations',
                 'LogicGA16Associations', 'LogicFunction', 'RestrikeChannel'):
        live.current[name] = ' '.join('1' for _ in range(size))
    return live


LEVELS = {
    'RELDN4': (255, 11, 255, 13, 0, 0, 0, 0, 0, 0, 0, 0, 22, 23, 24, 25),
    'RELDN8B': (255, 11, 255, 13, 255, 15, 255, 17, 0, 0, 0, 0, 22, 23, 24, 25),
    'RELDN12': (255, 11, 255, 13, 255, 15, 255, 17, 255, 19, 255, 21, 22, 23, 24, 25),
    'RELDN8': (0, 11, 12, 13, 14, 0, 0, 17, 18, 19, 20, 0, 22, 23, 24, 25),
}
LEVELS.update(DIMDN4=LEVELS['RELDN4'], DIMDN4F=LEVELS['RELDN4'],
              DIMDN8=LEVELS['RELDN8B'], DIMDN8F=LEVELS['RELDN8B'])


class NoSession:
    def __getattribute__(self, name):
        raise AssertionError('Invalid plan accessed session: ' + name)


class DinAgentSaveTest(unittest.TestCase):
    def test_all_eight_profiles_literal_projection_and_v1_preservation(self):
        for unit_type, profile in PROFILES.items():
            with self.subTest(unit_type=unit_type):
                live = seed(unit_type)
                editor = DinOutputEditor(live.spec, unit_type)
                before = editor.snapshot(live.values())
                targeted = editor.plan(live.values())
                self.assertEqual(targeted.changes, {})
                self.assertEqual(targeted.as_dict()['format'], 'cbus-din-output-settings-plan-v1')
                self.assertNotIn('toolkit_save', targeted.as_dict())
                plan = editor.plan(live.values(), toolkit_save=True)
                final = dict(plan.expected, **plan.changes)
                self.assertEqual(final['LightLevel'], LEVELS[unit_type])
                self.assertEqual(final['LogicLevelStoreEnable'], (1, 0, 1, 0))
                self.assertEqual(final['InterLockingChannel'], (2,) if profile.relay else (250,))
                self.assertEqual(plan.pre_save_changes, {})
                self.assertEqual(plan.save_normalization, plan.changes)
                self.assertEqual(DinPlan.from_dict(json.loads(json.dumps(plan.as_dict()))), plan)
                self.assertEqual(live.calls, [])
                if unit_type == 'RELDN8':
                    self.assertEqual(final['GroupAddress'],
                                     (255, 41, 42, 43, 44, 255, 255, 47, 48, 49, 50, 255, 52, 53, 54, 55))
                    self.assertEqual(final['MinDimmingLevel'], (0, 21, 22, 23, 24, 0, 0, 27, 28, 29, 30, 31))
                    self.assertEqual(final['PowerUpDelay'], (0, 31, 32, 33, 34, 0, 0, 37, 38, 39, 40, 41))
                    self.assertEqual(final['LogicGA13Associations'], (0, 1, 1, 1, 1, 0, 0, 1, 1, 1, 1, 1))
                    self.assertEqual(final['MaxDimmingLevel'], (201, 202, 203, 0))
                    self.assertFalse(editor.show(live.values())['channels'][1]['toolkit_save_rewrites_recovery_level'])
                else:
                    self.assertEqual(final['GroupAddress'][profile.channels:12],
                                     (255,) * (12 - profile.channels))
                    for name in set(FIELDS) - {'LightLevel', 'GroupAddress', 'InterLockingChannel'}:
                        self.assertEqual(final[name], before[name], name)
                self.assertEqual(final['GroupAddress'][12:], before['GroupAddress'][12:])
                result = editor.apply(live, plan)
                self.assertTrue(result['verified'])
                self.assertFalse(result['saved'])
                self.assertEqual(editor.snapshot(live.values()), final)
                self.assertEqual(live.current['UnitAddress'], '255')
                self.assertEqual(live.current['AreaGroupAddress'], '255')

    def test_requested_controls_then_exactly_one_non_idempotent_save(self):
        live = seed('RELDN8')
        editor = DinOutputEditor(live.spec, 'RELDN8')
        # Channel 1 is raw index 1, and no other block uses its group.
        plan = editor.plan(live.values(), channel=1, level_store=True, min_percent=50, toolkit_save=True)
        self.assertEqual(plan.pre_save_changes['LightLevel'][1], 255)
        self.assertEqual(plan.pre_save_changes['MinDimmingLevel'][1], 127)
        self.assertEqual(plan.changes['LightLevel'][1], 255)
        self.assertEqual(plan.changes['MinDimmingLevel'][1], 127)
        self.assertEqual(plan.changes['MaxDimmingLevel'], (201, 202, 203, 0))
        imported = DinPlan.from_dict(plan.as_dict())
        editor.apply(live, imported)
        second = editor.plan(live.values(), toolkit_save=True)
        self.assertEqual(second.changes['MaxDimmingLevel'], (202, 203, 0, 0))
        self.assertEqual(imported.as_dict()['normalization_passes'], 1)
        with self.assertRaisesRegex(DinSettingsError, 'changed since'):
            editor.apply(live, imported)

    def test_v2_schema_width_neighbor_bits_and_failure_boundaries(self):
        live = seed('RELDN8')
        editor = DinOutputEditor(live.spec, 'RELDN8')
        plan = editor.plan(live.values(), toolkit_save=True)
        before_image = editor.codec.encode_many(plan.expected).apply(MemoryImage.from_bytes(b'\x30' * 256))
        after_image = editor.codec.encode_many(plan.changes).apply(before_image)
        # Bits 4/5 of each shared logic byte are not owned by this editor.
        for index in range(12):
            self.assertEqual(after_image.byte(50 + index) & 0x30, 0x30)
        live.spec = fixture('RELDN8')
        parameter = live.spec.parameters['LogicFunction']
        live.spec.parameters['LogicFunction'] = ParameterSpec(
            parameter.name, parameter.type, parameter.source,
            dict(parameter.fields, BitSize='2'))
        with self.assertRaisesRegex(DinSettingsError, 'BitSize'):
            editor.apply(live, plan)
        self.assertEqual(live.calls, [])
        live = seed('RELDN8')
        live.failure = 'LightLevel'
        with self.assertRaises(DinSettingsApplyError) as error:
            editor.apply(live, plan)
        self.assertEqual(error.exception.attempted[-1], 'LightLevel')
        self.assertEqual(sum(name == 'LightLevel' for name, _ in live.calls), 1)
        self.assertFalse(error.exception.details['saved'])

    def test_strict_flags_arrays_and_imported_projection_before_session_access(self):
        editor = DinOutputEditor(fixture('DIMDN4'))
        for flag in (None, 0, 1, 'true', [], {}):
            with self.subTest(flag=flag), self.assertRaisesRegex(DinSettingsError, 'boolean'):
                editor.plan(fixture('DIMDN4').defaults(), toolkit_save=flag)
        original = editor.plan(seed('DIMDN4').values(), toolkit_save=True).as_dict()
        for name in ('expected', 'changes', 'save_normalization', 'pre_save_changes'):
            for bad in (True, 1.0, '1', -1, 256):
                document = deepcopy(original)
                document[name]['LightLevel'] = [bad] + [0] * 15
                with self.subTest(name=name, bad=bad), self.assertRaises(DinSettingsError):
                    DinPlan.from_dict(document)
        for passes in (0, 2, True, '1'):
            document = deepcopy(original)
            document['normalization_passes'] = passes
            with self.assertRaises(DinSettingsError):
                DinPlan.from_dict(document)
        for mutate in (
            lambda doc: doc['changes'].pop('LightLevel'),
            lambda doc: doc['save_normalization'].pop('LightLevel'),
            lambda doc: doc['pre_save_changes'].update({'LightLevel': doc['expected']['LightLevel']}),
            lambda doc: doc['expected'].pop('RestrikeDelay'),
        ):
            document = deepcopy(original)
            mutate(document)
            with self.assertRaises(DinSettingsError):
                editor.apply(NoSession(), DinPlan.from_dict(document))
        # Direct Python construction must not evade the serialized strictness.
        plan = DinPlan.from_dict(original)
        forged_expected = dict(plan.expected, LightLevel=(True,) + plan.expected['LightLevel'][1:])
        with self.assertRaises(DinSettingsError):
            editor.apply(NoSession(), replace(plan, expected=forged_expected))

    def test_coherent_plan_cannot_bypass_unused_logic_or_whole_snapshot_stale_guards(self):
        live = seed('DIMDN4')
        editor = DinOutputEditor(live.spec)
        plan = editor.plan(live.values(), toolkit_save=True)
        document = plan.as_dict()
        document['pre_save_changes']['GroupAddress'] = list(plan.expected['GroupAddress'])
        document['pre_save_changes']['GroupAddress'][12] = 255
        document['changes']['GroupAddress'][12] = 255
        document['save_normalization']['GroupAddress'][12] = 255
        with self.assertRaisesRegex(DinSettingsError, 'no group address'):
            editor.apply(NoSession(), DinPlan.from_dict(document))
        live.current['RestrikeDelay'] = '61'
        with self.assertRaisesRegex(DinSettingsError, 'changed since'):
            editor.apply(live, plan)
        self.assertEqual(live.calls, [])


class DinSaveSourceReceiptTest(unittest.TestCase):
    def test_scope_pins_and_marshaled_correction_are_explicit(self):
        receipt = json.loads(RECEIPT.read_text())
        self.assertFalse(receipt['original_code_executed'])
        self.assertFalse(receipt['native_server_executed'])
        self.assertEqual(set(receipt['profiles']), set(PROFILES))
        self.assertEqual(receipt['plan_format'], TOOLKIT_SAVE_PLAN_FORMAT)
        self.assertEqual(receipt['reldn8']['max_projection_source_indices'], [1, 2, 3, None])
        self.assertEqual(receipt['reldn8']['max_projection_missing_default'], 0)
        self.assertIn('slot11-retained', receipt['reldn8']['per_channel_tail'])
        self.assertGreaterEqual(len(receipt['methods']), 10)

    @unittest.skipUnless(os.environ.get('CBUS_TOOLKIT_EXE'), 'requires pinned Toolkit bytes for static hash check')
    def test_optional_original_bytes_match_static_method_ranges_without_execution(self):
        import pefile

        receipt = json.loads(RECEIPT.read_text())
        raw = Path(os.environ['CBUS_TOOLKIT_EXE']).read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), receipt['toolkit_exe_sha256'])
        image = pefile.PE(data=raw)
        for method in receipt['methods']:
            start, end = int(method['start'], 16), int(method['end'], 16)
            data = image.get_data(start - image.OPTIONAL_HEADER.ImageBase, end - start)
            self.assertEqual(hashlib.sha256(data).hexdigest(), method['sha256'], method['name'])
