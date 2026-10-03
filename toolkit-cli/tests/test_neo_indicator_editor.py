"""Literal source-owned Neo control cases using a synthetic packed schema."""
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
import unittest

from cbus_toolkit.memory import MemoryImage
from cbus_toolkit.neo_indicator_editor import NeoIndicatorEditor, NeoIndicatorPlan
from cbus_toolkit.pp_editor import PPApplyError, PPEditError
from cbus_toolkit.unitspec import UnitSpec, ParameterSpec
from test_macros import Session

# Hand-authored public schema. Oracles below do not call the production
# projector or conversion helpers to generate expected values.
ROWS = (
    ('IndicatorBrightness', 'int', 0x32, 1, 8, 0, '255'),
    ('GroupAddress', 'int', 0x50, 9, 8, 0, '1 2 3 4 5 6 7 8 9'),
    ('IndicatorPressedLevel', 'int', 0x33, 1, 4, 4, '15'),
    ('TimerDuration', 'int', 0x33, 1, 4, 0, '15'),
    ('EnableNightlight', 'bit', 0x34, 1, 1, 0, '0'),
    ('DisableTimerFlash', 'bit', 0x34, 1, 1, 1, '0'),
    ('NightlightColour', 'bit', 0x34, 1, 1, 2, '0'),
    ('IDBacklightIllumination', 'bit', 0x34, 1, 1, 3, '0'),
    ('FirstKeyThrowAway', 'bit', 0x34, 1, 1, 4, '0'),
    ('EnableNightlightOnPCx', 'bit', 0x34, 1, 1, 5, '0'),
    ('EnableNightlightOnPA6', 'bit', 0x34, 1, 1, 6, '0'),
    ('EnableNightlightControl', 'bit', 0x34, 1, 1, 7, '1'),
    ('IndicatorFunction', 'int', 0x60, 8, 2, 4, '2 2 2 2 2 2 2 2'),
    ('PrimaryColour', 'int', 0x60, 8, 1, 3, '1 1 1 1 1 1 1 1'),
    ('IndicatorBlockAssignment', 'int', 0x60, 8, 3, 0, '7 6 5 4 3 2 1 0'),
    ('PackedNeighbour', 'int', 0x60, 8, 1, 6, '0 1 0 1 0 1 0 1'),
    ('SceneKeySelector', 'int', 0x60, 8, 1, 7, '1 0 1 0 1 0 1 0'),
)
COUNTS = {'KEYM2': 2, 'KEYM4': 4, 'KEYM8': 8, 'KEYA1': 1, 'KEYA3': 3, 'KEYA6': 6, 'KEYA8': 8,
    'KEYAV2': 2, 'KEYAV4': 4, 'KEYB2': 2, 'KEYB4': 4, 'KEYB6': 6, 'KEYH1': 1, 'KEYH2': 2,
    'KEYH3': 3, 'KEYH4': 4, 'KEYC1': 1, 'KEYC2': 2, 'KEYC4': 4, 'KEYCIR4': 4, 'KEYDV1': 1,
    'KEYDV2': 2, 'KEYDV3': 3, 'KEYDV4': 4, 'KEYP2': 2, 'KEYP4': 4, 'KEYP6': 6, 'KEYV1': 1,
    'KEYV2': 2, 'KEYV3': 3}


def fixture(kind='KEYM4'):
    parameters = {}
    for name, typ, address, count, bits, offset, default in ROWS:
        fields = dict(Name=name, Type=typ, Address=str(address), ArraySize=str(count), BitSize=str(bits),
                      BitAddress=str(offset), ArraySkip='0', DefaultValue=default)
        parameters[name] = ParameterSpec(name, typ, 'fixture.xml', fields)
    return UnitSpec(kind + '.xml', {'Type': kind}, ('fixture.xml',), parameters)


def final(plan):
    return {**plan.expected, **plan.changes}


def session(spec):
    result = Session(spec)
    result.firmware, result.catalog_number = '2.5.00', None
    return result


class NoSession:
    def __getattribute__(self, name):
        raise AssertionError('Invalid plan accessed session: ' + name)


class NeoIndicatorEditorTests(unittest.TestCase):
    def test_all_thirty_profiles_physical_columns_and_predicates(self):
        for kind, count in COUNTS.items():
            with self.subTest(kind=kind):
                spec = fixture(kind)
                editor = NeoIndicatorEditor(spec)
                p = editor.plan(spec.defaults(), [{'led': count, 'style': 'always_on'}])
                self.assertEqual(p.changes['IndicatorFunction'], (2,) * (count - 1) + (1,) + (2,) * (8-count))
                view = p.as_dict()['final_panel']
                self.assertEqual(view['physical_led_count'], count)
                self.assertEqual(view['controls']['id_backlight_enabled']['visible'], kind.startswith('KEYM'))
                self.assertEqual(view['controls']['id_backlight_enabled']['enabled'], kind.startswith('KEYM'))
                self.assertEqual(view['controls']['nightlight_colour']['visible'], kind.startswith(('KEYB', 'KEYH', 'KEYP', 'KEYV')))
                self.assertEqual(view['colour_rows_visible'], not kind.startswith('KEYC'))
                self.assertEqual(NeoIndicatorPlan.from_dict(p.as_dict()).as_dict(), p.as_dict())
                with self.assertRaises(PPEditError):
                    editor.plan(spec.defaults(), [{'led': count + 1, 'style': 'always_on'}])
        for kind in ('KEYE1', 'KEYM6', 'KEYCIR1', 'KEYV1SP', 'KEYGL5', 'KEYM4_A'):
            with self.subTest(refused=kind), self.assertRaises(PPEditError):
                NeoIndicatorEditor(fixture(kind))

    def test_style_colour_order_and_all_eight_normalizations(self):
        spec = fixture()
        editor = NeoIndicatorEditor(spec)
        p = editor.plan(spec.defaults(), [{'led': 2, 'style': 'status_dual'}, {'led': 2, 'on_colour': 'blue'}])
        self.assertEqual(p.changes, {'IndicatorFunction': (2, 3, 2, 2, 2, 2, 2, 2), 'PrimaryColour': (1, 0, 1, 1, 1, 1, 1, 1)})
        self.assertEqual(p.as_dict()['final_panel']['leds'][1]['off_colour'], 'orange')
        off = editor.plan(spec.defaults(), [{'led': 2, 'on_colour': 'blue'}, {'led': 2, 'style': 'always_off'}])
        self.assertEqual(final(off)['PrimaryColour'][1], 0)
        self.assertIsNone(off.as_dict()['final_panel']['leds'][1]['on_colour'])
        with self.assertRaises(PPEditError):
            editor.plan(spec.defaults(), [{'led': 2, 'style': 'always_off'}, {'led': 2, 'on_colour': 'blue'}])
        raw = dict(spec.defaults(), IndicatorFunction='3 0 1 2 3 1 0 3', PrimaryColour='0 1 0 1 0 1 0 1')
        reflection = NeoIndicatorEditor(fixture('KEYA3')).plan(raw, [{'led': 2, 'style': 'status_on'}])
        self.assertEqual(final(reflection)['IndicatorFunction'], (2, 2, 1, 2, 2, 1, 0, 2))
        self.assertEqual(final(reflection)['PrimaryColour'], (1,) * 8)
        self.assertEqual(reflection.as_dict()['final_panel']['leds'][1]['on_colour'], 'blue')
        classic = NeoIndicatorEditor(fixture('KEYC4')).plan(raw, [{'led': 3, 'style': 'always_off'}])
        self.assertEqual(final(classic)['IndicatorFunction'], (2, 0, 0, 2, 2, 1, 0, 2))
        self.assertEqual(final(classic)['PrimaryColour'], (0, 1, 0, 1, 0, 1, 0, 1))
        for name in ('IndicatorPressedLevel', 'TimerDuration', 'FirstKeyThrowAway', 'IDBacklightIllumination',
                     'EnableNightlightOnPA6', 'EnableNightlightOnPCx', 'EnableNightlightControl'):
            self.assertEqual(final(classic)[name], (0,))
        classic = NeoIndicatorEditor(fixture('KEYC4')).plan(dict(raw, EnableNightlight='1',
            EnableNightlightOnPA6='1', EnableNightlightOnPCx='1', IDBacklightIllumination='1'), [])
        for name in ('EnableNightlight', 'EnableNightlightOnPA6', 'EnableNightlightOnPCx', 'IDBacklightIllumination'):
            self.assertEqual(final(classic)[name], (0,))

    def test_catalogue_colour_domains_and_hidden_controls(self):
        for kind, catalog, on, night in [('KEYM4', '5041nmml', 'red', None), ('KEYV2', None, 'green', 'red'),
                                         ('KEYB4', None, 'orange', 'blue')]:
            with self.subTest(kind=kind):
                spec = fixture(kind)
                editor = NeoIndicatorEditor(spec)
                ops = [{'led': 1, 'on_colour': on}]
                if night:
                    ops += [{'nightlight_enabled': True}, {'nightlight_colour': night}]
                p = editor.plan(spec.defaults(), ops, identity={'unit_type': kind, 'firmware': '2.5.00', 'catalog_number': catalog})
                self.assertEqual(final(p)['PrimaryColour'][0], 1)
                if night:
                    self.assertEqual(final(p)['NightlightColour'], (1,))
        for kind, operation in [('KEYM4', {'nightlight_colour': 'blue'}), ('KEYA3', {'led': 1, 'on_colour': 'blue'}),
                               ('KEYC4', {'led': 1, 'style': 'status_dual'}), ('KEYDV2', {'id_backlight_enabled': True}),
                               ('KEYDV2', {'nightlight_colour': 'blue'}), ('KEYB4', {'nightlight_colour': 'blue'}),
                               ('KEYM4', {'EnableNightlightControl': True}), ('KEYM4', {'led': 1, 'off_colour': 'orange'})]:
            with self.subTest(kind=kind, operation=operation), self.assertRaises(PPEditError):
                NeoIndicatorEditor(fixture(kind)).plan(fixture(kind).defaults(), [operation])

    def test_disabled_checked_load_differs_from_explicit_uncheck_and_noop(self):
        for kind, parameter in [('KEYM4', 'EnableNightlightOnPA6'), ('KEYB4', 'EnableNightlightOnPCx'),
                                 ('KEYDV2', 'EnableNightlightOnPA6'), ('KEYA3', 'EnableNightlightOnPCx')]:
            with self.subTest(kind=kind):
                spec = fixture(kind)
                editor = NeoIndicatorEditor(spec)
                raw = dict(spec.defaults(), TimerDuration='0', FirstKeyThrowAway='1', **{parameter: '1'})
                p = editor.plan(raw, [{'key_press_brightness_enabled': False}])
                self.assertEqual(final(p)[parameter], (1,))
                self.assertEqual(final(p)['FirstKeyThrowAway'], (1,))
                self.assertFalse(p.as_dict()['final_panel']['controls']['first_press_ignored']['enabled'])
                p = editor.plan(raw, [{'key_press_brightness_enabled': True}, {'key_press_brightness_enabled': False}])
                self.assertEqual(final(p)[parameter], (int(kind == 'KEYM4'),))
                self.assertEqual(final(p)['FirstKeyThrowAway'], (0,))
                self.assertEqual(final(p)['TimerDuration'], (0,))
                p = editor.plan(dict(raw, **{parameter: '0'}), [])
                self.assertEqual(p.as_dict()['load_normalization']['FirstKeyThrowAway'], [0])

    def test_complete_global_history_source_mapping(self):
        for kind, night in [('KEYM4', 'EnableNightlightOnPA6'), ('KEYDV2', 'EnableNightlightOnPA6'),
                            ('KEYB4', 'EnableNightlightOnPCx'), ('KEYA3', 'EnableNightlightOnPCx')]:
            with self.subTest(kind=kind):
                spec = fixture(kind)
                p = NeoIndicatorEditor(spec).plan(spec.defaults(), [
                    {'brightness_source': 'first_block'}, {'brightness_source': 'fixed'}, {'fixed_brightness_percent': 50},
                    {'key_press_brightness_enabled': False}, {'key_press_brightness_enabled': True},
                    {'key_press_brightness_level': 9}, {'key_press_duration': 4}, {'nightlight_enabled': True},
                    {'first_press_ignored': True}, {'timer_flash_enabled': False}])
                f = final(p)
                self.assertEqual((f['IndicatorBrightness'], f['IndicatorPressedLevel'], f['TimerDuration'], f[night],
                                  f['FirstKeyThrowAway'], f['DisableTimerFlash']), ((127,), (9,), (4,), (1,), (1,), (1,)))
                self.assertEqual(f['GroupAddress'], (1, 2, 3, 4, 5, 6, 7, 8, 9))
                self.assertEqual(f['EnableNightlightControl'], (1,))
                other = 'EnableNightlightOnPCx' if night == 'EnableNightlightOnPA6' else 'EnableNightlightOnPA6'
                empty = NeoIndicatorEditor(spec).plan(dict(spec.defaults(), EnableNightlight='1',
                    IDBacklightIllumination='1', **{other: '1'}), [])
                self.assertEqual(final(empty)['EnableNightlight'], (0,))
                self.assertEqual(final(empty)[other], (0,))
                self.assertEqual(final(empty)['IDBacklightIllumination'], (1,))
                self.assertEqual(empty.as_dict()['initial_panel']['controls']['id_backlight_enabled']['value'],
                                 kind == 'KEYM4')

    def test_brightness_load_noop_reserved_encoding_and_classic_override(self):
        spec = fixture()
        editor = NeoIndicatorEditor(spec)
        for raw, saved in [(0, 0), (1, 1), (2, 1), (3, 1), (4, 4), (5, 5), (6, 6), (8, 8), (128, 128), (255, 255)]:
            with self.subTest(raw=raw):
                p = editor.plan(dict(spec.defaults(), IndicatorBrightness=str(raw)), [])
                self.assertEqual(final(p)['IndicatorBrightness'], (saved,))
        raw = dict(spec.defaults(), IndicatorBrightness='128')
        p = editor.plan(raw, [{'fixed_brightness_percent': 50}])
        self.assertEqual(final(p)['IndicatorBrightness'], (128,))
        p = editor.plan(raw, [{'fixed_brightness_percent': 49}, {'fixed_brightness_percent': 50}])
        self.assertEqual(final(p)['IndicatorBrightness'], (127,))
        for percent, saved in [(0, 4), (1, 5), (2, 6), (3, 7), (50, 127), (100, 255)]:
            with self.subTest(percent=percent):
                p = editor.plan(spec.defaults(), [{'fixed_brightness_percent': percent}])
                self.assertEqual(final(p)['IndicatorBrightness'], (saved,))
        classic = NeoIndicatorEditor(fixture('KEYC4'))
        for raw, saved in [(0, 0), (1, 1), (2, 5), (3, 3), (4, 4), (5, 5), (6, 6)]:
            with self.subTest(classic_raw=raw):
                p = classic.plan(dict(spec.defaults(), IndicatorBrightness=str(raw)), [])
                self.assertEqual(final(p)['IndicatorBrightness'], (saved,))
        p = classic.plan(spec.defaults(), [{'brightness_source': 'first_block'}])
        self.assertEqual(final(p)['IndicatorBrightness'], (255,))
        self.assertEqual(p.as_dict()['final_panel']['controls']['brightness_source']['value'], 'first_block')

    def test_strict_input_and_serialized_replay_before_session(self):
        spec = fixture()
        editor = NeoIndicatorEditor(spec)
        plan = editor.plan(spec.defaults(), [{'led': 1, 'on_colour': 'blue'}])
        for operation in [{'led': True, 'style': 'always_on'}, {'led': 1, 'style': 'always_on', 'on_colour': 'blue'},
                          {'key_press_duration': 0}, {'key_press_duration': 1.0}, {'timer_flash_enabled': 1},
                          {'fixed_brightness_percent': '50'}, {'brightness_group': 3}]:
            with self.subTest(operation=operation), self.assertRaises(PPEditError):
                editor.plan(spec.defaults(), [operation])
        for token in (True, 1.0, '1'):
            doc = plan.as_dict()
            doc['expected']['PrimaryColour'][0] = token
            with self.subTest(token=token), self.assertRaises(PPEditError):
                NeoIndicatorPlan.from_dict(doc)
        mutations = []
        doc = plan.as_dict(); doc['changes']['PrimaryColour'][1] = 0; mutations.append(doc)
        doc = plan.as_dict(); doc['final_panel']['physical_led_count'] = True; mutations.append(doc)
        doc = plan.as_dict(); doc['control_history'][0]['after']['leds'][0]['off_colour'] = 'blue'; mutations.append(doc)
        doc = plan.as_dict(); doc['identity']['extra'] = 'forged'; mutations.append(doc)
        doc = plan.as_dict(); doc['saved'] = True; mutations.append(doc)
        doc = plan.as_dict(); doc['extra'] = False; mutations.append(doc)
        doc = plan.as_dict(); doc['unit_type'] = []; mutations.append(doc)
        doc = plan.as_dict(); doc['operations'] = [{'led': 1, 'style': 'always_off'}, {'led': 1, 'on_colour': 'blue'}]; mutations.append(doc)
        for index, doc in enumerate(mutations):
            with self.subTest(mutation=index), self.assertRaises(PPEditError):
                editor.apply(NoSession(), NeoIndicatorPlan(json.dumps(doc)))
        for field in ('IndicatorFunction', 'GroupAddress'):
            raw = dict(spec.defaults()); raw[field] = [0]
            with self.subTest(field=field), self.assertRaises(PPEditError):
                editor.plan(raw, [])

    def test_apply_stale_schema_identity_restore_and_packed_preservation(self):
        spec = fixture()
        editor = NeoIndicatorEditor(spec)
        original = session(spec)
        plan = editor.plan(original.values(), [{'led': 2, 'style': 'status_dual'}, {'led': 2, 'on_colour': 'blue'}])
        image = MemoryImage({address: 255 for address in [0x32, 0x33, 0x34, *range(0x50, 0x59), *range(0x60, 0x68)]})
        image = editor.codec.encode_many(spec.defaults()).apply(image)
        after = editor.codec.encode_many(plan.changes).apply(image)
        self.assertEqual(after.byte(0x61) & 0xC7, image.byte(0x61) & 0xC7)
        self.assertEqual(after.byte(0x60), image.byte(0x60))
        self.assertTrue(editor.apply(original, plan)['verified'])
        self.assertEqual(len(original.calls), 2)
        with self.assertRaises(PPEditError):
            editor.apply(original, plan)
        self.assertEqual(len(original.calls), 2)
        for stale in ('GroupAddress', 'EnableNightlightControl', 'IndicatorBrightness'):
            other = session(spec)
            other.current[stale] = '0 ' * 9 if stale == 'GroupAddress' else '0'
            with self.subTest(stale=stale), self.assertRaises(PPEditError):
                editor.apply(other, plan)
            self.assertEqual(other.calls, [])
        parameters = dict(spec.parameters)
        parameters['PrimaryColour'] = replace(parameters['PrimaryColour'], fields={**parameters['PrimaryColour'].fields, 'BitSize': '2'})
        other = session(replace(spec, parameters=parameters))
        with self.assertRaises(PPEditError):
            editor.apply(other, plan)
        self.assertEqual(other.calls, [])
        other = session(spec); other.catalog_number = 'other'
        with self.assertRaises(PPEditError):
            editor.apply(other, plan)
        self.assertEqual(other.calls, [])
        other = session(spec); other.failure = 'PrimaryColour'
        with self.assertRaises(PPApplyError) as failure:
            editor.apply(other, plan)
        self.assertEqual(failure.exception.rollback_errors, ())
        self.assertEqual(other.current, spec.defaults())
        self.assertEqual([name for name, _ in other.calls], ['IndicatorFunction', 'PrimaryColour', 'PrimaryColour', 'IndicatorFunction'])

    @unittest.skipUnless(os.environ.get('CBUS_TOOLKIT_EXE') and os.environ.get('CBUS_TOOLKIT_MAP'),
                         'Original Toolkit EXE/MAP explicitly required for static hash verification')
    def test_optional_original_static_review(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'research'))
        from neo_indicator_editor_static import verify
        result = verify(Path(os.environ['CBUS_TOOLKIT_EXE']), Path(os.environ['CBUS_TOOLKIT_MAP']))
        self.assertTrue(result['verified'])
        self.assertFalse(result['original_code_executed'])
