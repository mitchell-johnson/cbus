"""Original Global-tab Reset dependency; no form, service or worker execution."""
from dataclasses import replace
import copy
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from cbus_toolkit.edlt import EdltError
from cbus_toolkit.edlt_lifecycle import EdltLifecycle, FactoryResetEdlt
from cbus_toolkit.edlt_reset import EdltResetControls
from cbus_toolkit.edlt_global_preparation import EdltGlobalPreparation, GlobalPreparationContext
from tests.test_edlt_global_preparation import fixture, vectors
from tests.test_edlt_reset import metadata

ROOT = Path(__file__).resolve().parents[1]
CAPTURES = {
    'dependency': ('edlt-reset-factory-dependency-vectors.json',
        '3118283623dc7cb6c3e24905b67e82ab97e65b169e86c960a453e897f7d5f070'),
    'rich': ('edlt-reset-factory-rich-vectors.json',
        '2345882da2600ffd7a0f484d5a10edc89efd29ccf51d879f2bd36445e08582c6'),
}


def capture(kind):
    name, digest = CAPTURES[kind]
    raw = (ROOT / 'research/fixtures' / name).read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise AssertionError('Original factory vectors changed: ' + name)
    return json.loads(raw)


def fields(phase):
    return {name: {'value': value, 'tokens': list(phase.tokens[name]),
                   'dirty': name in phase.dirty_parameters} for name, value in phase.raw.items()}


class FactoryResetTests(unittest.TestCase):
    def setUp(self):
        self.spec = fixture()
        self.lifecycle = EdltLifecycle(self.spec)
        self.reset = EdltResetControls(self.spec, lifecycle=self.lifecycle)
        self.preparer = EdltGlobalPreparation(self.spec)
        self.row = vectors()['factory_project_cases'][0]
        self.raw, self.cache = dict(self.row['input']), metadata()

    def issue(self, *, raw=None, cache=None, dirty=(), row=None):
        row = self.row if row is None else row
        return self.preparer.factory_context(self.raw if raw is None else raw,
            reset_editor=self.reset, context=GlobalPreparationContext(
                row['source_path'], row['form_project'], row['cached_network_project']),
            metadata=self.cache if cache is None else cache, dirty_parameters=dirty)

    def prepare(self, *, raw=None, cache=None, dirty=(), row=None):
        raw = self.raw if raw is None else raw
        cache = self.cache if cache is None else cache
        return self.reset.prepare_global_factory(raw, metadata=cache,
            preparation_context=self.issue(raw=raw, cache=cache, dirty=dirty, row=row),
            dirty_parameters=dirty)

    def test_two_actual_factories_and_twelve_original_raw_phases(self):
        records = capture('dependency'); rows = vectors()['factory_project_cases']; count = 0
        for record in records['cases']:
            row = rows[record['factory_case_index']]; raw = row['input']
            baseline = {k: {'value': v, 'dirty': False, 'tokens': v.split(' ')} for k, v in raw.items()}
            self.assertEqual(hashlib.sha256(json.dumps(raw, sort_keys=True,
                separators=(',', ':')).encode()).hexdigest(), record['input_sha256'])
            with self.subTest(source=row['source_path']):
                retained = self.prepare(raw=raw, row=row)
                saved = self.reset.prepare_global_factory_save(retained)
                for name, original in record['phases'].items():
                    self.assertEqual(fields(saved.phases[name]), {**baseline, **original['field_changes']}, name)
                    if original['initializing'] is not None:
                        self.assertIs(saved.phases[name].initializing, original['initializing'])
                    count += 1
                assignment = retained.project_assignment.after.as_dict()
                self.assertEqual({k: assignment[k] for k in row['after_initial_project']}, row['after_initial_project'])
                self.assertEqual(retained.raw_phases['after-reset'].raw['NavWidgetType'], '0xFF')
                self.assertEqual(retained.raw_phases['after-global-tab-removal'].raw['NavWidgetType'], '0x0')
                self.assertFalse(saved.as_dict()['third_after_load_performed'])
        self.assertEqual(count, 12)

    def test_five_exact_rich_patterns_all85_original_phases(self):
        document = capture('rich'); count = 0
        self.assertEqual(len(document['cases']), 5)
        for row in document['cases']:
            with self.subTest(source=row['name']):
                state = self.prepare(raw=row['raw_input'], row=row, cache=document['metadata'])
                saved = self.reset.prepare_global_factory_save(state)
                expected = dict(row['original_input_phase'])
                for original in row['phases']:
                    expected.update(original['delta'])
                    name = {'after-conditional-project': 'conditional-project-initialization'}.get(
                        original['stage'], original['stage'])
                    self.assertEqual(len(expected), 874)
                    self.assertEqual(fields(saved.phases[name]), expected, (row['name'], name))
                    self.assertIs(saved.phases[name].initializing, original['initializing'])
                    count += 1
                self.assertTrue(row['handler_and_components_full_shared_phases_equal'])
                self.assertEqual(len(row['workers']), 2)
                self.assertEqual(dict(saved.model_plan.expected), self.reset.snapshot(row['raw_input']))
                if row['name'] == 'rich-scene':
                    self.assertEqual(len(state.base.scenes[0].items), 1)
                    self.assertIsNotNone(state.base.mra.source_widget)
                self.assertIsNone(state.fresh.mra.source_widget)
                self.assertFalse(any(scene.items for scene in state.fresh.scenes))
        self.assertEqual(count, 85)

    def test_exact_owner_two_loads_and_retained_terminal_no_third_load(self):
        with patch.object(self.lifecycle, 'load', wraps=self.lifecycle.load) as load:
            state = self.prepare()
            self.assertEqual(load.call_count, 2)
        self.assertIs(type(state), FactoryResetEdlt)
        self.assertIsNot(state.base, state.fresh)
        self.assertIs(state._origin.owner, self.lifecycle._loaded_owner)
        self.assertEqual(len(state.fresh.scenes), 8)
        self.assertEqual(len(state.widgets), 21)
        self.assertEqual(state.widgets[9].model_family, 'TimeAndDateData')
        self.assertTrue(all(state.widgets[i] is state.fresh.widgets[i] for i in range(21) if i != 9))
        with (patch.object(self.lifecycle, 'load', side_effect=AssertionError('Third AfterLoad')),
              patch('socket.socket', side_effect=AssertionError('Unexpected I/O'))):
            saved = self.reset.prepare_global_factory_save(state)
        self.assertEqual(dict(saved.model_plan.after_load), dict(state.base.after_load))
        self.assertEqual(saved.model_plan.before_save['Widget11WidgetType'], (255,))
        self.assertFalse(saved.as_dict()['saved'])

    def test_project_sidecar_preserves_tail_without_relaxing_codec_or_source(self):
        row = vectors()['factory_project_cases'][1]; original = dict(row['input'])
        state = self.prepare(raw=original, row=row, dirty=['UnitAddress'])
        saved = self.reset.prepare_global_factory_save(state)
        self.assertEqual(dict(state.expected), self.reset.snapshot(original))
        self.assertEqual(state.after_controls['Project'], original['Project'])
        self.assertEqual(saved.model_plan.before_save['Project'], original['Project'])
        for name in ('conditional-project-initialization', 'after-reset', 'final'):
            phase = saved.phases[name]
            self.assertEqual(phase.raw['Project'], row['form_project'] + ' ' * 8)
            self.assertEqual(phase.tokens['Project'], (row['form_project'],) + ('',) * 8)
            self.assertIn('Project', phase.dirty_parameters)
            self.assertIn('UnitAddress', phase.dirty_parameters)
            with self.assertRaises((EdltError, ValueError)): self.reset.snapshot(phase.raw)
        self.assertEqual(original, row['input'])
        self.assertFalse(state.as_dict()['oem_projection']['physical_codec_relaxed'])

    def test_fresh_context_inputs_cannot_change_raw_order_cache_or_dirty(self):
        receipt = self.issue()
        cases = [dict(raw={**self.raw, 'FontStyle': '0x01'}),
            dict(raw=dict(reversed(list(self.raw.items())))), dict(dirty=['Project']),
            dict(cache={**self.cache, 'applications_complete': False})]
        for changes in cases:
            self.reset.last_evidence = {'saved': True}
            with self.subTest(changes=list(changes)), patch.object(self.lifecycle, 'load') as load:
                with self.assertRaises(EdltError):
                    self.reset.prepare_global_factory(changes.get('raw', self.raw),
                        metadata=changes.get('cache', self.cache), preparation_context=receipt,
                        dirty_parameters=changes.get('dirty', ()))
                load.assert_not_called()
                self.assertIsNone(self.reset.last_evidence)

    def test_one_nonidentity_change_and_missing_cache_rejected_before_load(self):
        rich = capture('rich')
        for row in rich['cases']:
            raw = {**row['raw_input'], 'StatusRequestInterval': '0x4'}
            with self.subTest(pattern=row['name']), patch.object(self.lifecycle, 'load') as load:
                with self.assertRaisesRegex(EdltError, 'captured source patterns'):
                    self.prepare(raw=raw, row=row, cache=rich['metadata'])
                load.assert_not_called()
        incomplete = {**self.cache, 'applications_complete': False}
        with patch.object(self.lifecycle, 'load') as load, self.assertRaisesRegex(EdltError, 'complete application'):
            self.prepare(cache=incomplete)
        load.assert_not_called()
        with self.assertRaises(EdltError): self.prepare(raw={**self.raw, 'UnitAddress': '0x15'})
        with self.assertRaises((EdltError, ValueError)): self.prepare(raw={**self.raw, 'Project': 'OVERLONG9'})

    def test_original_layout_defaults_and_shared_constructor_are_required(self):
        for key, value in [('DefaultValue', '$4'), ('ArraySkip', '1'), ('Endian', 'big')]:
            spec = fixture(); parameters = dict(spec.parameters); p = parameters['StatusRequestInterval']
            parameters[p.name] = replace(p, fields={**p.fields, key: value})
            changed = replace(spec, parameters=parameters)
            reset = EdltResetControls(changed); preparer = EdltGlobalPreparation(changed)
            receipt = preparer.factory_context(self.raw, reset_editor=reset,
                context=GlobalPreparationContext(self.row['source_path'], self.row['form_project'], 'NetPrj'),
                metadata=self.cache)
            with self.subTest(field=key), patch.object(reset.lifecycle, 'load') as load:
                with self.assertRaisesRegex(EdltError, 'ordered original layouts and defaults'):
                    reset.prepare_global_factory(self.raw, metadata=self.cache, preparation_context=receipt)
                load.assert_not_called()
        for args in [dict(lifecycle=EdltLifecycle(fixture())), dict(lifecycle=object()),
                     dict(lifecycle=self.lifecycle, firmware='5.6.00')]:
            with self.assertRaises(EdltError): EdltResetControls(self.spec, **args)

    def test_copies_exports_cross_editors_and_changed_retained_objects_rejected(self):
        state = self.prepare()
        for invalid in (replace(state), copy.copy(state), state.as_dict()):
            with self.assertRaises(EdltError): self.reset.prepare_global_factory_save(invalid)
        other = EdltResetControls(self.spec, lifecycle=self.lifecycle)
        with self.assertRaises(EdltError): other.prepare_global_factory_save(state)
        with self.assertRaises(EdltError): EdltLifecycle(self.spec).prepare_save(state)
        for field in ('expected', 'after_controls'):
            value = self.prepare(); changed = dict(getattr(value, field)); changed['FontStyle'] = (True,)
            object.__setattr__(value, field, changed)
            with self.subTest(field=field), self.assertRaises(EdltError):
                self.reset.prepare_global_factory_save(value)
        for mutation in ('scene', 'mra', 'phase'):
            value = self.prepare()
            if mutation == 'scene':
                object.__setattr__(value.fresh, 'scenes', (replace(value.fresh.scenes[0]), *value.fresh.scenes[1:]))
            elif mutation == 'mra': object.__setattr__(value.fresh.mra, 'zone', True)
            else:
                phase = value.raw_phases['after-reset']
                object.__setattr__(phase, 'initializing', 0)
            with self.subTest(mutation=mutation), self.assertRaises(EdltError):
                self.reset.prepare_global_factory_save(value)

    def test_public_reset_tab_and_nav_guards_remain_unchanged(self):
        with self.assertRaisesRegex(EdltError, 'NavWidgetType0 or1'):
            self.reset.plan(self.raw, metadata=self.cache, active_tab='widgets', binding_variant='audited-local-wiring')
        with self.assertRaisesRegex(EdltError, 'Active tab'):
            self.reset.plan(self.raw, metadata=self.cache, active_tab='global', binding_variant='audited-local-wiring')

    def test_interruptions_keep_original_identity_partial_phases_and_no_replay(self):
        class UnprintableInterrupt(KeyboardInterrupt):
            def __str__(self): raise SystemExit('secondary formatting')
            def __setattr__(self, name, value):
                if name == 'edlt_reset_evidence': raise SystemExit('secondary attachment')
                super().__setattr__(name, value)
        for stop_at in ('initial', 'fresh', 'save', 'crc'):
            error = UnprintableInterrupt() if stop_at == 'fresh' else SystemExit(stop_at)
            with self.subTest(stage=stop_at), patch('socket.socket', side_effect=AssertionError('Unexpected I/O')):
                if stop_at in ('initial', 'fresh'):
                    original = self.lifecycle.load; calls = []
                    def load(*args, **kwargs):
                        calls.append(1)
                        if len(calls) == (1 if stop_at == 'initial' else 2): raise error
                        return original(*args, **kwargs)
                    with patch.object(self.lifecycle, 'load', side_effect=load):
                        with self.assertRaises(BaseException) as result: self.prepare()
                    self.assertEqual(len(calls), 1 if stop_at == 'initial' else 2)
                else:
                    state = self.prepare()
                    target, name = (self.lifecycle, 'prepare_save') if stop_at == 'save' else (self.reset, 'crcs')
                    with patch.object(target, name, side_effect=error) as action:
                        with self.assertRaises(BaseException) as result: self.reset.prepare_global_factory_save(state)
                    action.assert_called_once()
                self.assertIs(result.exception, error)
                evidence = self.reset.last_evidence
                self.assertFalse(evidence['saved']); self.assertFalse(evidence['pp_io_performed'])
                self.assertEqual(evidence['automatic_retries'], 0)
                if stop_at == 'fresh':
                    self.assertIn('component-zero-byte1', evidence['completed_phases'])
                    self.assertNotIn('component-after-change', evidence['completed_phases'])
                if stop_at == 'crc': self.assertIn('before-save', evidence['completed_phases'])


if __name__ == '__main__': unittest.main()
