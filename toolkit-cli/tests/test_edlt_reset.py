"""Raw Reset state, issued transitions, preflight and interrupted staging."""
from dataclasses import replace
import unittest
from unittest.mock import patch

from cbus_toolkit.edlt import EdltError, EdltApplyError
from cbus_toolkit.edlt_lifecycle import EdltLifecycle, LifecycleMetadataError
from cbus_toolkit.edlt_reset import (EdltResetControls, ResetPhase, _RawState,
                                    _EXCLUDED, RAW_FORMAT)
from cbus_toolkit.unitspec import UnitSpec, ParameterSpec
from tests.test_edlt_lifecycle import fixture as lifecycle_fixture
from tests.test_edlt import Session


def fixture():
    """Synthetic exact-size schema for guard tests, not a vendor default oracle."""
    source = lifecycle_fixture(); parameters = {}
    for name, parameter in source.parameters.items():
        fields = dict(parameter.fields)
        if parameter.type not in ('string', 'sixbit'):
            fields['DefaultValue'] = ' '.join('$' + format(int(t, 0), 'X') for t in parameter.default.split())
        parameters[name] = replace(parameter, fields=fields)
    def add(name, default, address, kind='int', size=1, bits=8):
        parameters[name] = ParameterSpec(name, kind, 'owned-reset-fixture.xml', {
            'Name': name, 'Type': kind, 'DefaultValue': default, 'Address': hex(address),
            'ArraySize': str(size), 'BitSize': str(bits)})
    for name, default, address, kind, size in (
            ('UnitName', 'NEWUNIT ', 0x30, 'string', 8), ('Project', 'OWNED   ', 0x40, 'string', 8),
            ('UnitAddress', '$14', 0x20, 'int', 1), ('NetworkAddress', '$FE', 0x48, 'int', 1),
            ('SerialNumber', '$1 $2 $3 $4', 0x49, 'int', 4), ('EnableLevelStore', '$0', 0x4d, 'int', 1)):
        add(name, default, address, kind, size)
    names = ('BacklightActiveBrightnessControlGroup', 'BacklightIdleBrightnessControlGroup',
        'IndicatorActiveBrightnessControlGroup', 'IndicatorIdleBrightnessControlGroup',
        'IndicatorOnColourControlGroup', 'IndicatorOffColourControlGroup', 'QuickStatusGroup',
        'CorridorLinkingLinkGroup', 'CorridorLinkingOfficeGroup', 'CorridorLinkingCorridorGroup',
        'KeySetsEnableGroup', 'ProximityGroup', 'ProximityMode')
    for index, name in enumerate(names): add(name, '$0' if name == 'ProximityMode' else '$FF', 0x60 + index)
    while len(parameters) < 874: add('OwnedPadding' + str(len(parameters)), '$0', 0x80)
    return UnitSpec(source.filename, source.metadata, source.sources, parameters)


def metadata(mode='complete'):
    apps = [56, 57, 127, 136, 172, 202, 203, 255]; numbers = [255, 0, 1, 2, 12, 42, 254]
    return {'format': 'cbus-edlt-application-cache-v1', 'applications_complete': True,
        'applications': [{'address': a, 'name': 'Owned application' + str(a),
            'formatted_display': 'Owned application' + str(a)} for a in apps],
        'group_lists': [{'application': a, 'complete': True, 'groups': [
            {'address': g, 'name': '<Unused>' if g == 255 else 'Owned group' + str(g),
             'formatted_display': '<Unused>' if g == 255 else 'Owned group' + str(g)} for g in numbers]} for a in apps],
        'lifecycle': {'format': 'cbus-edlt-lifecycle-cache-v1', 'applications': apps,
            'groups': [{'application': a, 'group': g, 'exists': True,
                'dynamic_images': [] if g == 255 else [False] * 4,
                'levels': [x for x in (0, 1, 2, 42, 254, 255)
                    if not (mode == 'missing-level2' and a == 202 and g == 42 and x == 2)]}
                for a in apps for g in numbers]}}


class RawStateTests(unittest.TestCase):
    def test_original_token_aliases_partial_write_and_initializing_flags(self):
        raw = _RawState({'a': '0xff $ff $xAB 0xffffffff', 'text': 'OLD TAIL'})
        self.assertEqual(raw.raw()['a'], '0xff 0xFF 0xAB 0xff')
        raw.set('text', 'NEW'); self.assertEqual(raw.raw()['text'], 'NEW TAIL')
        raw.set('a', '0xFF'); self.assertEqual(raw.dirty, set())
        raw.initializing = False; raw.set('a', '0xff'); self.assertEqual(raw.dirty, {'a'})
        raw.integer('a', 999); self.assertEqual(raw.tokens['a'][0], '0xFF')
        raw.integer('a', -1); self.assertEqual(raw.tokens['a'][0], '0x0')

    def test_snapshot_preserves_tokens_dirty_and_trailing_empty_fields(self):
        raw = _RawState({'text': 'A   ', 'empty': '   '}, ('text',))
        phase = raw.phase(); self.assertEqual(phase.raw, {'text': 'A   ', 'empty': ''})
        self.assertEqual(phase.tokens['empty'], ('', '', '', ''))
        copy = _RawState.from_phase(phase); self.assertEqual(copy.phase(), phase)
        with self.assertRaises(TypeError): phase.tokens['text'] = ('x',)
        raw.set('text', 'B'); self.assertEqual(phase.raw['text'], 'A   ')


class ResetTests(unittest.TestCase):
    def setUp(self):
        self.spec = fixture(); self.editor = EdltResetControls(self.spec)
        self.raw = _RawState(self.editor.defaults).raw()
        self.raw.update(NavWidgetType='0x1', Widget6WidgetType='0x2', Widget6WidgetByteValue6='0x2a',
                        Widget6RestoreLevel='0xad', Widget6WidgetByteValue31='0xab', EnableLevelStore='0x1')

    def plan(self, **changes):
        options = dict(metadata=metadata(), active_tab='general',
            binding_variant='audited-local-wiring', dirty_parameters=['UnitAddress'])
        options.update(changes)
        return self.editor.plan(self.raw, **options)

    def session(self):
        session = Session(self.spec); session.current = dict(self.raw)
        # This fake holds raw native PP strings to test exact pre-staging guard.
        session.values = lambda: dict(session.current)
        session.set = lambda name, value: (session.calls.append((name, value)), session.current.__setitem__(name, value))[-1]
        return session

    def test_raw_envelopes_keep_native_strings_and_reject_numeric_or_wrong_profile(self):
        document = self.editor.raw_document(self.raw)
        self.assertEqual(document['format'], RAW_FORMAT)
        self.assertEqual(self.editor.read_raw_document(document), self.raw)
        self.assertEqual(self.editor.read_raw_document({**document, 'format': 'cbus-cli-parameters-v1'}), self.raw)
        for bad in ({**document, 'firmware': None}, {**document, 'extra': 1},
                    {**document, 'parameters': {**self.raw, 'EnableLevelStore': [1]}}):
            with self.assertRaises(EdltError): self.editor.read_raw_document(bad)
        for value in ('0x1\n', '0x1  0x2', '0b1', True):
            with self.assertRaises(EdltError): self.editor.raw_input({**self.raw, 'EnableLevelStore': value})

    def test_tabs_defaults_dirty_and_previous_store_have_distinct_phases(self):
        general = self.plan()
        self.assertEqual(general.phases['before-reset'].raw['Widget6RestoreLevel'], '0xAD')
        self.assertEqual(general.phases['component-before-change'].raw['EnableLevelStore'], '0x0')
        self.assertEqual(general.phases['component-reset-defaults'].raw['NavWidgetType'], '0xFF')
        self.assertTrue(general.phases['component-reset-defaults'].initializing)
        self.assertFalse(general.phases['component-after-change'].initializing)
        self.assertEqual(general.phases['after-reset'].raw['Widget10WidgetType'], '0xA')
        self.assertEqual(general.phases['after-reset'].raw['Widget10WidgetByteValue1'], '0x2')
        for tab in ('widgets', 'general', 'standby', 'colour'):
            plan = self.plan(active_tab=tab)
            self.assertEqual(plan.phases['final'].raw['NavWidgetType'], '0x0' if tab in ('widgets', 'general') else '0xFF')
            self.assertIn('UnitAddress', plan.phases['final'].dirty_parameters)
            for name in _EXCLUDED:
                self.assertEqual(plan.phases['component-reset-defaults'].raw[name], plan.phases['component-before-change'].raw[name])
            self.assertEqual(plan.phases['final'].raw['UnitName'], 'NEWUNIT ')
            self.assertFalse(plan.as_dict()['physical_factory_reset_performed'])

    def test_exact_issued_reset_and_fresh_model_identity(self):
        captured = []
        original = self.editor.lifecycle.reset_unit_controls
        def run(base, *, reset_context):
            result = original(base, reset_context=reset_context); captured.append(result); return result
        with patch.object(self.editor.lifecycle, 'reset_unit_controls', side_effect=run): plan = self.plan()
        edited = captured[0]; life = self.editor.lifecycle
        self.assertIsNot(edited.fresh, edited.base)
        self.assertTrue(all(a is not b for a, b in zip(edited.fresh.widgets, edited.base.widgets)))
        self.assertTrue(all(a is not b for a, b in zip(edited.fresh.scenes, edited.base.scenes)))
        self.assertEqual(edited.widgets[9].stored_type, 10)
        with patch.object(life, 'load', side_effect=AssertionError('unexpected third load')):
            saved = life.prepare_save(edited)
        self.assertEqual(saved.expected, plan.expected)
        for bad in (replace(edited), replace(edited, base=replace(edited.base))):
            with self.assertRaises(EdltError): life.prepare_save(bad)
        with self.assertRaises(EdltError): EdltLifecycle(self.spec).prepare_save(edited)
        for bad in (replace(edited.context), edited.context.__dict__, None):
            with self.assertRaises(EdltError): life.reset_unit_controls(edited.base, reset_context=bad)
        with self.assertRaises(EdltError): life.reset_unit_controls(replace(edited.base), reset_context=edited.context)
        with self.assertRaises(TypeError): edited.raw_phases['new'] = None

    def test_invalid_cache_tab_dirty_and_control_scope_rejected(self):
        for args in ({'active_tab': 'global'}, {'active_tab': True}, {'binding_variant': None},
                     {'dirty_parameters': ['UnitAddress', 'UnitAddress']}, {'dirty_parameters': [True]}):
            with self.assertRaises(EdltError): self.plan(**args)
        cache = metadata(); cache['applications_complete'] = False
        with self.assertRaises(EdltError): self.plan(metadata=cache)
        cache = metadata(); cache['group_lists'] = []
        with self.assertRaises(LifecycleMetadataError): self.plan(metadata=cache)
        for key, value in (('Widget6WidgetType', '0x3'), ('NavWidgetType', '0xff'), ('QuickStatusGroup', '0x99')):
            with self.assertRaises(EdltError):
                self.editor.plan({**self.raw, key: value}, metadata=metadata(), active_tab='widgets', binding_variant='base-c3')

    def test_missing_defaults_and_incompatible_default_casing_rejected(self):
        for name, default in (('Widget1WidgetType', '$ff'), ('EnableLevelStore', None)):
            parameters = dict(self.spec.parameters); fields = dict(parameters[name].fields)
            if default is None: fields.pop('DefaultValue')
            else: fields['DefaultValue'] = default
            parameters[name] = replace(parameters[name], fields=fields)
            with self.assertRaises(EdltError): EdltResetControls(replace(self.spec, parameters=parameters))

    def test_raw_stale_boolean_phase_and_forged_context_guards_before_io(self):
        plan = self.plan(); session = self.session()
        final = plan.phases['final']
        for bad in (replace(plan, changes={**plan.changes, 'EnableLevelStore': (False,)}),
                    replace(plan, phases={**plan.phases, 'final': replace(final, initializing=0)}),
                    replace(plan, evidence='{}'), replace(plan, specification_sha256='forged')):
            with self.assertRaises(EdltError): self.editor.apply(session, bad)
        self.assertEqual(session.calls, [])
        session.current['Widget6RestoreLevel'] = '0xAD'
        with self.assertRaisesRegex(EdltError, 'Raw PP values changed'): self.editor.apply(session, plan)
        self.assertEqual(session.calls, [])

    def test_raw_import_token_projection_keeps_external_expected_text(self):
        self.raw['Project'] = '   ABC '
        plan = self.plan()
        self.assertEqual(plan.expected_raw['Project'], '   ABC ')
        self.assertEqual(plan.expected['Project'], '   ABC ')
        self.assertEqual(plan.phases['input'].tokens['Project'], ('', '', '', 'ABC', ''))
        self.assertEqual(plan.phases['input'].raw['Project'], 'ABC ')
        self.assertEqual(plan.changes['Project'], 'ABC ')
        session = self.session(); self.assertTrue(self.editor.apply(session, plan)['verified'])

    def test_apply_verifies_all_values_and_clears_old_configure_evidence(self):
        session = self.session(); result = self.editor.apply(session, self.plan())
        self.assertTrue(result['verified']); self.assertFalse(result['saved'])
        session.identity['UnitType'] = 'KEY4'
        with self.assertRaises(EdltError):
            self.editor.configure(session, metadata=metadata(), active_tab='general', binding_variant='base-c3')
        self.assertIsNone(self.editor.last_evidence)

    def test_partial_failure_restoration_and_interruption_keep_original(self):
        plan = self.plan(); session = self.session(); original_set = session.set; calls = []
        failure = OSError('owned stage failure')
        def fail(name, value):
            calls.append(name)
            if len(calls) == 2: raise failure
            original_set(name, value)
        with patch.object(session, 'set', side_effect=fail):
            with self.assertRaises(EdltApplyError) as caught: self.editor.apply(session, plan)
        self.assertIs(caught.exception.cause, failure)
        self.assertEqual(caught.exception.rollback_errors, ())
        self.assertEqual(self.editor.snapshot(session.values()), self.editor.snapshot(self.raw))
        class Unattachable(KeyboardInterrupt):
            def __setattr__(self, name, value): raise RuntimeError('attachment refused')
        for error in (KeyboardInterrupt('stop'), SystemExit(2), Unattachable()):
            session = self.session()
            with patch.object(session, 'set', side_effect=error) as setter:
                with self.assertRaises(type(error)) as interrupted: self.editor.apply(session, plan)
            self.assertIs(interrupted.exception, error); self.assertEqual(setter.call_count, 1)
            self.assertEqual(len(self.editor.last_evidence['attempted_parameters']), 1)
            self.assertFalse(self.editor.last_evidence['saved'])

    def test_disconnected_failure_stops_recovery_and_rollback_interrupt_keeps_primary(self):
        plan = self.plan(); session = self.session(); error = OSError('disconnected')
        session.programmer.client.connected = True
        def disconnect(*args):
            session.programmer.client.connected = False
            raise error
        with patch.object(session, 'set', side_effect=disconnect) as setter:
            with self.assertRaises(EdltApplyError) as caught: self.editor.apply(session, plan)
        self.assertIs(caught.exception.cause, error); self.assertEqual(setter.call_count, 1)
        self.assertTrue(caught.exception.rollback_errors)
        session = self.session(); session.programmer.client.connected = True
        interruption = KeyboardInterrupt('rollback interrupted'); count = 0
        def broken(*args):
            nonlocal count
            count += 1
            if count == 1: raise error
            raise interruption
        with patch.object(session, 'set', side_effect=broken):
            with self.assertRaises(KeyboardInterrupt) as caught: self.editor.apply(session, plan)
        self.assertIs(caught.exception, interruption); self.assertEqual(count, 2)
        self.assertEqual(self.editor.last_evidence['original_error']['type'], 'OSError')
