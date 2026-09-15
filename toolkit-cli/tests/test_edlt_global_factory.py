"""Original full-factory vectors and issued preparation/category composition."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from cbus_toolkit.edlt import EdltError
from cbus_toolkit.edlt_global_preparation import (EdltGlobalPreparation,
    GlobalPreparationContext, _validate_prepared_factory)
from cbus_toolkit.edlt_global_programming import EdltGlobalProgramming, CATEGORIES, _payload_native_value
from cbus_toolkit.edlt_reset import EdltResetControls
from tests.test_edlt_global_programming import fixture
from tests.test_edlt_global_preparation import vectors as project_vectors
from tests.test_edlt_reset import metadata as project_metadata

ROOT = Path(__file__).resolve().parents[1]
VECTOR_PATH = ROOT / 'research/fixtures/edlt-reset-factory-rich-vectors.json'
VECTOR_HASH = '2345882da2600ffd7a0f484d5a10edc89efd29ccf51d879f2bd36445e08582c6'


def vectors():
    data = VECTOR_PATH.read_bytes()
    assert hashlib.sha256(data).hexdigest() == VECTOR_HASH
    return json.loads(data)


def projection(phase):
    return {name: {'value': phase.raw[name], 'tokens': list(tokens),
        'dirty': name in phase.dirty_parameters} for name, tokens in phase.tokens.items()}


class FactoryGlobalTests(unittest.TestCase):
    def setUp(self):
        self.spec = fixture()
        self.engine = EdltGlobalProgramming(self.spec)
        self.preparer = EdltGlobalPreparation(self.spec)
        self.data = vectors()
        self.row = self.data['cases'][0]

    def prepare(self, row=None, **changes):
        row = self.row if row is None else row
        args = dict(metadata=self.data['metadata'], global_engine=self.engine,
            context=GlobalPreparationContext(row['source_path'], row['form_project'], row['cached_network_project']))
        args.update(changes)
        return self.preparer.prepare_factory(row['raw_input'], **args)

    def test_all_five_original_factory_families_and_ten_literal_workers(self):
        with patch('socket.socket', side_effect=AssertionError('Unexpected network I/O')):
            for row in self.data['cases']:
                with self.subTest(source=row['name']):
                    value = self.prepare(row)
                    source = self.engine.prepare_factory_source(value)
                    self.assertEqual(value.expected_raw, row['raw_input'])
                    self.assertEqual(value.expected, self.engine.snapshot(row['raw_input']))
                    self.assertEqual(source.expected['NavWidgetType'], (255,))
                    self.assertEqual(source.final['NavWidgetType'], (0,))
                    original = row['original_input_phase']
                    expanded = {}
                    for phase in row['phases']:
                        original = {**original, **phase['delta']}; expanded[phase['stage']] = original
                        if phase['stage'] in ('before-save', 'final'): continue
                        name = 'conditional-project-initialization' if phase['stage']=='after-conditional-project' else phase['stage']
                        self.assertEqual(projection(value.raw_phases[name]), original)
                        self.assertIs(value.raw_phases[name].initializing, phase['initializing'])
                    for worker in row['workers']:
                        categories = tuple(CATEGORIES) if worker['mask']==15 else ()
                        payload = self.engine.select(source, categories=categories)
                        literal = [[name, _payload_native_value(payload, name, v)] for name, v in payload.ordered_payload]
                        self.assertEqual(literal, worker['ordered_payload'])
                        final = projection(value.raw_phases['final'])
                        for name, _ in payload.ordered_payload:
                            if name != 'GlobalParameterCRC': final[name] = {**final[name], 'dirty':True}
                        self.assertEqual(final, {**expanded['after-global-tab-removal'], **worker['post_removal_to_worker_delta']})
                        self.assertEqual(payload.values['GlobalParameterCRC'], (0,0))
                        self.assertNotEqual(source.final['GlobalParameterCRC'], (0,0))
                        self.assertNotIn('Project', payload.values)
                        self.assertEqual(source.final['Project'], source.expected['Project'])
                    self.assertTrue(value.as_dict()['factory_model_preparation_applied'])
                    self.assertFalse(value.as_dict()['full_form_executed'])

    def test_exactly_two_loads_and_one_terminal_save_then_frozen_reuse(self):
        with patch.object(self.engine.lifecycle, 'load', wraps=self.engine.lifecycle.load) as load:
            with patch.object(self.engine.lifecycle, 'prepare_save', wraps=self.engine.lifecycle.prepare_save) as save:
                prepared = self.prepare()
                self.assertEqual(load.call_count, 2); self.assertEqual(save.call_count, 1)
                source = self.engine.prepare_factory_source(prepared)
                for mask in range(16):
                    categories = tuple(name for i,name in enumerate(CATEGORIES) if mask & (1<<i))
                    payload = self.engine.select(source, categories=categories)
                    merge = self.engine.merge(payload, source.expected)
                    self.assertEqual(len(payload.ordered_payload), 2 + sum(len(CATEGORIES[name]) for name in categories))
                    self.assertEqual(merge.final['UnitAddress'], source.expected['UnitAddress'])
                    self.assertEqual(merge.final['Project'], source.expected['Project'])
                self.assertEqual(load.call_count, 2); self.assertEqual(save.call_count, 1)

    def test_original_default_like_projects_and_false_complete_worker_literals(self):
        document=project_vectors()
        for row in document['factory_project_cases']:
            value=self.preparer.prepare_factory(row['input'],metadata=project_metadata(),
                context=GlobalPreparationContext(row['source_path'],row['form_project'],row['cached_network_project']),global_engine=self.engine)
            observed=value.project_assignment.after.as_dict()
            self.assertEqual({name:observed[name] for name in row['after_project_preamble']},row['after_project_preamble'])
            source=self.engine.prepare_factory_source(value)
            for worker in document['worker_payload_cases']:
                payload=self.engine.select(source,categories=tuple(CATEGORIES) if worker['mask']==15 else ())
                self.assertEqual([[name,_payload_native_value(payload,name,v)] for name,v in payload.ordered_payload],
                    [[entry['parameter'],entry['value']] for entry in worker['ordered_payload']])
                self.assertEqual({name:value.raw_phases['final'].raw[name] for name in worker['source_crcs']},worker['source_crcs'])
        rejected=next(row for row in document['worker_payload_cases'] if row['false_complete'])
        self.assertTrue(rejected['original_worker_completed'])
        self.assertFalse(rejected['worker_completion_proves_destination_update'])
        self.assertEqual(rejected['rejected_parameters'],['FontStyle'])

    def test_wrong_order_pattern_metadata_and_engine_rejected_before_load(self):
        for raw in (dict(reversed(list(self.row['raw_input'].items()))),
                    {**self.row['raw_input'], 'FontStyle':'0x7'},
                    {**self.row['raw_input'], 'NavWidgetType':'0x0'}):
            with patch.object(self.engine.lifecycle, 'load', side_effect=AssertionError('Unexpected load')):
                with self.assertRaises(EdltError):
                    self.preparer.prepare_factory(raw, metadata=self.data['metadata'],
                        context=GlobalPreparationContext(self.row['source_path'],self.row['form_project'],'NetPrj'),global_engine=self.engine)
        with self.assertRaises(EdltError): self.prepare(metadata={})
        with self.assertRaises(EdltError): self.prepare(global_engine=EdltGlobalProgramming(fixture()))

    def test_issued_receipts_copies_cross_engine_and_full_phase_forgery_rejected(self):
        prepared = self.prepare()
        for bad in (replace(prepared), prepared.as_dict(), None):
            with self.assertRaises(EdltError): self.engine.prepare_factory_source(bad)
        with self.assertRaises(EdltError): EdltGlobalProgramming(self.spec).prepare_factory_source(prepared)
        for field, value in [('expected',{**prepared.expected,'FontStyle':(False,)}),
                             ('expected_raw',{**prepared.expected_raw,'Project':'CHANGED'}),
                             ('model_plan','{}')]:
            fresh = self.prepare();object.__setattr__(fresh,field,value)
            with self.assertRaises(EdltError):self.engine.prepare_factory_source(fresh)
        with self.assertRaises(TypeError):prepared.raw_phases['final'].tokens['Project']=('changed',)

    def test_literal_renderer_keeps_decimal_boolean_and_rejects_false_equality(self):
        prepared=self.prepare();source=self.engine.prepare_factory_source(prepared)
        payload=self.engine.select(source,categories=tuple(CATEGORIES))
        self.assertEqual(_payload_native_value(payload,'EnableTimerFlash',(1,)), '1')
        self.assertEqual(_payload_native_value(payload,'OverallCRC',(191,127)), '0xbf 0x7f')
        for value in ((True,), (2,), [1]):
            with self.assertRaises(EdltError):_payload_native_value(payload,'EnableTimerFlash',value)
        with self.assertRaises(EdltError):_payload_native_value(payload,'Project',(1,))

    def test_factory_sidecar_cannot_be_removed_to_bypass_native_source_guard(self):
        prepared=self.prepare();source=self.engine.prepare_factory_source(prepared)
        object.__setattr__(source,'factory_preparation',None)
        with self.assertRaisesRegex(EdltError,'factory preparation identity'):
            self.engine.select(source,categories=())
        ordinary=self.engine.prepare_source(self.row['raw_input'],metadata=prepared.metadata.lifecycle)
        object.__setattr__(ordinary,'factory_preparation',prepared)
        with self.assertRaisesRegex(EdltError,'factory preparation identity'):
            self.engine.select(ordinary,categories=())

    def test_original_interruption_unprintable_error_and_failed_attachment_survive(self):
        class RejectAttach(KeyboardInterrupt):
            def __setattr__(self,name,value):
                if name=='edlt_global_preparation_evidence':raise SystemExit('secondary attachment')
                return super().__setattr__(name,value)
        class Unprintable(RuntimeError):
            def __str__(self):raise SystemExit('secondary formatting')
        for original in (KeyboardInterrupt('first'),SystemExit('first'),RejectAttach('first'),Unprintable()):
            with patch.object(EdltResetControls,'prepare_global_factory_save',side_effect=original):
                with self.assertRaises(BaseException) as caught:self.prepare()
            self.assertIs(caught.exception,original)
            self.assertEqual(self.preparer.last_evidence['stage'],'terminal_source_save')
            self.assertFalse(self.preparer.last_evidence['complete'])
            self.assertFalse(self.preparer.last_evidence['io_performed'])


if __name__=='__main__':unittest.main()
