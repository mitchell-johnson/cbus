"""Frozen original Project token/dirty cases; no factory/save bridge or I/O."""
from dataclasses import replace
import base64
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from cbus_toolkit.edlt import EdltError
from cbus_toolkit.edlt_global_preparation import (
    EdltGlobalPreparation, GlobalPreparationContext, ProjectState,
    assign_project, initialize_project,
)
from cbus_toolkit.edlt_global_programming import CATEGORIES
from tests.test_edlt_global_programming import fixture

ROOT = Path(__file__).resolve().parents[1]
VECTOR_PATH = ROOT/'research/fixtures/edlt-global-preparation-vectors.json'
VECTOR_SHA256 = '879a11a7076b2e124f09530cbcc9152cd7cd7126e87fa8be7558f796a95096fa'


def vectors():
    data=VECTOR_PATH.read_bytes()
    if hashlib.sha256(data).hexdigest()!=VECTOR_SHA256:
        raise AssertionError('Original preparation vectors changed')
    return json.loads(data)


def state(row):
    return ProjectState(None if row['tokens'] is None else tuple(row['tokens']),
                        row['backing'], row['dirty'], row['initializing'])


def projection(value):
    return {key:part for key,part in value.as_dict().items() if key!='physical_encoding_verified'}


class ProjectStateTests(unittest.TestCase):
    def test_ten_original_project_setter_vectors(self):
        rows=vectors()['partial_project_cases']
        self.assertEqual(len(rows),10)
        for row in rows:
            with self.subTest(name=row['name']):
                before=state(row['before']);assignment=assign_project(before,row['assigned'])
                self.assertEqual(projection(before),row['before'])
                self.assertEqual(projection(assignment.after),row['after'])
                self.assertEqual(len(assignment.notification_states),row['notifications'])
                self.assertIs(assignment.before,before)
                self.assertTrue(assignment.setter_called)
                for middle in assignment.notification_states:
                    self.assertEqual(middle.backing,before.backing)
                self.assertFalse(assignment.as_dict()['notifications_executed'])

    def test_original_notification_failure_intermediate_state_is_retained(self):
        row=vectors()['negative_original_notification']
        first=row['project_stages']['before-actual-wrapper-preamble']
        expected=row['project_stages']['partial']
        assignment=assign_project(ProjectState(tuple(first['tokens']),'',first['dirty']), 'NetPrj')
        self.assertEqual(len(assignment.notification_states),1)
        partial=assignment.notification_states[0]
        self.assertEqual(partial.value,expected['value'])
        self.assertEqual(list(partial.tokens),expected['tokens'])
        self.assertEqual(partial.dirty,expected['dirty'])
        identity=next(line for line in row['identities'] if line.startswith('identity:partial:'))
        fields=dict(part.split('=',1) for part in identity.split(':',2)[2].split(':'))
        self.assertEqual(partial.backing,base64.b64decode(fields['backing']).decode())
        self.assertEqual(assignment.after.backing,'NetPrj')

    def test_positional_tokens_preserve_old_tail_and_assignment_notification_order(self):
        before=ProjectState.from_raw('A B TAIL',backing='BASE')
        assignment=assign_project(before,'X Y')
        self.assertEqual([row.tokens for row in assignment.notification_states],
                         [('X','B','TAIL'),('X','Y','TAIL')])
        self.assertEqual([row.backing for row in assignment.notification_states],['BASE','BASE'])
        self.assertEqual(assignment.after.value,'X Y TAIL')
        self.assertEqual(assignment.after.backing,'X Y')
        self.assertEqual(before.value,'A B TAIL')
        equal=assign_project(assignment.after,'X Y')
        self.assertTrue(equal.after.dirty)
        self.assertEqual(equal.notification_states,())

    def test_original_token_aliases_and_empty_getter_do_not_truncate(self):
        row=ProjectState.from_raw('0xffffffff $xAB $ab $Xab 0xFFFFFFFF')
        self.assertEqual(row.tokens,('0xff','0xAB','0xAB','0xXAB','0xFFFFFFFF'))
        blank=ProjectState.from_raw('        ')
        self.assertEqual(blank.tokens,('',)*9)
        self.assertEqual(blank.value,'')
        initialized=initialize_project(blank,'FORMPRJ')
        self.assertEqual(initialized.after.value,'FORMPRJ        ')
        self.assertEqual(initialized.after.tokens,('FORMPRJ',)+('',)*8)
        self.assertFalse(initialize_project(initialized.after,'OTHER').setter_called)
        missing=ProjectState(None,'')
        self.assertEqual(initialize_project(missing,'FORM').after,ProjectState(None,'FORM'))

    def test_exact_types_bounds_and_control_characters(self):
        class Child(ProjectState): pass
        for make in [lambda:ProjectState(('a',),'',0),lambda:ProjectState(('a',),'',False,1),
                     lambda:ProjectState(None,'',True),lambda:ProjectState(['a']),
                     lambda:ProjectState(()),lambda:ProjectState(('a b',)),
                     lambda:ProjectState(('a',)*65),lambda:ProjectState(('x'*257,)),
                     lambda:ProjectState.from_raw('x\n'),lambda:ProjectState.from_raw('é'),
                     lambda:ProjectState.from_raw('x'*4097),lambda:ProjectState.from_raw(True),
                     lambda:assign_project(Child(('a',)),'B'),lambda:assign_project({},'B'),
                     lambda:assign_project(ProjectState(('a',)),None),
                     lambda:assign_project(ProjectState(('a',)),'x\r'),
                     lambda:Child.from_raw('a')]:
            with self.subTest(make=make),self.assertRaises(EdltError):make()


class GlobalPreparationTests(unittest.TestCase):
    def setUp(self):
        self.editor=EdltGlobalPreparation(fixture())
        self.rows=vectors()['factory_project_cases']
        self.row=self.rows[0]

    def begin(self,row=None,**kwargs):
        row=self.row if row is None else row
        return self.editor.begin(row['input'], context=GlobalPreparationContext(
            row['source_path'],row['form_project'],row['cached_network_project']),**kwargs)

    def test_two_actual_factory_project_paths_preserve_external874_raw_baseline(self):
        for row in self.rows:
            with self.subTest(source=row['source_project']):
                before=self.begin(row)
                initialized=self.editor.initialize_project(before)
                preamble=self.editor.project_preamble(initialized,destination=row['destination'])
                self.assertEqual(projection(initialized.project),row['after_initial_project'])
                self.assertEqual(projection(preamble.project),row['after_project_preamble'])
                self.assertEqual(dict(preamble.expected_raw),row['input'])
                self.assertEqual(preamble.parameter_order,tuple(row['input']))
                self.assertEqual(len(preamble.raw),874)
                self.assertEqual({k:v for k,v in preamble.raw.items() if k!='Project'},
                                 {k:v for k,v in row['input'].items() if k!='Project'})
                self.assertEqual(preamble.context.source,row['source_path'])
                self.assertNotEqual(preamble.project.value,preamble.context.form_project)
                self.assertEqual(preamble.destination,row['destination'])
                self.assertEqual(preamble.forced_parameters,('OverallCRC',))
                self.assertIn('OverallCRC',preamble.dirty_parameters)
                self.assertIn('Project',preamble.dirty_parameters)
                self.assertGreater(len(preamble.project.value),8)
                with self.assertRaises((EdltError,ValueError)):
                    self.editor.common.snapshot(preamble.raw)

    def test_three_original_worker_forced_field_sets_are_not_numeric_diffs(self):
        source=self.begin()
        for row in vectors()['worker_payload_cases']:
            cats=tuple(name for index,name in enumerate(CATEGORIES) if row['mask']&(1<<index))
            with self.subTest(name=row['name']):
                preamble=self.editor.project_preamble(source,destination=self.row['destination'],categories=cats)
                self.assertEqual(set(preamble.forced_parameters),set(row['forced_names'])-{'GlobalParameterCRC'})
                self.assertEqual(len(preamble.forced_parameters),len(row['ordered_payload'])-1)
                for name in preamble.forced_parameters:
                    self.assertEqual(preamble.raw[name],source.raw[name])
                    self.assertIn(name,preamble.dirty_parameters)
                self.assertNotIn('GlobalParameterCRC',preamble.forced_parameters)
                self.assertTrue(row['original_worker_completed'])
                self.assertFalse(row['worker_completion_proves_destination_update'])
                if row['false_complete']:
                    self.assertTrue(row['rejected_parameters'])
        self.assertEqual(source.stages,('raw-observation',))

    def test_dirty_initialization_mode_and_original_source_identity_retained(self):
        source=self.begin(dirty_parameters=['WidgetsCRC'],initializing=True)
        result=self.editor.project_preamble(source,destination=self.row['destination'],categories=['colour'])
        self.assertFalse(result.project.dirty)
        self.assertEqual(result.project_assignments[-1].notification_states,())
        self.assertIn('WidgetsCRC',result.dirty_parameters)
        self.assertNotIn('Project',result.dirty_parameters)
        for name in ['UnitAddress','SerialNumber','NetworkAddress','UnitName','OverallCRC']:
            self.assertEqual(result.raw[name],source.raw[name])
        self.assertEqual(result.context.as_dict()['source_unit'],20)
        self.assertTrue(result.context.as_dict()['cached_project_differs_from_source'])

    def test_exact_context_destination_and_category_preflight_guards(self):
        class Child(GlobalPreparationContext):pass
        for args in [('//P/0254/p/20','P','P'),('//P/254/p/256','P','P'),
                     ('/P/254/p/20','P','P'),('//P/254/p/20','TOOLONG123','P'),
                     ('//P/254/p/20','P','bad space'),(True,'P','P')]:
            with self.subTest(args=args),self.assertRaises(EdltError):GlobalPreparationContext(*args)
        with self.assertRaises(EdltError):
            self.editor.begin(self.row['input'],context=Child('//P/254/p/20','P','P'))
        source=self.begin()
        for destination in [None,True,'//OTHER/254/p/22',self.row['destination'].replace('/254/','/253/'),
                            self.row['destination'].replace('/22','/022'),self.row['destination'].replace('/22','/256')]:
            with self.subTest(destination=destination),self.assertRaises(EdltError):
                self.editor.project_preamble(source,destination=destination)
        for categories in ['colour',('unknown',),('colour','colour'),(True,),{'colour'}]:
            with self.subTest(categories=categories),self.assertRaises(EdltError):
                self.editor.project_preamble(source,destination=self.row['destination'],categories=categories)

    def test_invalid_complete_profile_and_strict_raw_inputs(self):
        bad=dict(self.row['input']);bad.pop('OverallCRC')
        for values in [bad,{**self.row['input'],'FontStyle':False},{**self.row['input'],'FontStyle':'-1'},
                       {**self.row['input'],'FontStyle':'0x1  '},{**self.row['input'],'FontStyle':'0x1\n'},
                       {**self.row['input'],'Project':'123456789'}, {**self.row['input'],'UnitName':'x'*8193}]:
            with self.subTest(values=list(values)[-1]),self.assertRaises((EdltError,ValueError)):
                self.editor.begin(values,context=GlobalPreparationContext(self.row['source_path'],'FORMPRJ','NetPrj'))
        for dirty in ['Project',['missing'],['Project','Project'],[True]]:
            with self.assertRaises(EdltError):self.begin(dirty_parameters=dirty)
        with self.assertRaises(EdltError):self.begin(initializing=1)
        spec=fixture();params=dict(spec.parameters)
        params['Project']=replace(params['Project'],fields={**params['Project'].fields,'Address':'36'})
        with self.assertRaises(EdltError):EdltGlobalPreparation(replace(spec,parameters=params))
        params=dict(spec.parameters);params.pop('OverallCRC')
        with self.assertRaises(EdltError):EdltGlobalPreparation(replace(spec,parameters=params))

    def test_issued_phase_receipts_reject_forgery_reuse_and_cross_engine(self):
        source=self.begin();initialized=self.editor.initialize_project(source)
        for bad in [replace(source),replace(source,project=ProjectState(('FORGED',))),source.as_dict()]:
            with self.assertRaises(EdltError):self.editor.initialize_project(bad)
        with self.assertRaises(EdltError):EdltGlobalPreparation(fixture()).initialize_project(source)
        with self.assertRaises(EdltError):self.editor.initialize_project(initialized)
        result=self.editor.project_preamble(initialized,destination=self.row['destination'])
        with self.assertRaises(EdltError):self.editor.project_preamble(result,destination=self.row['destination'])
        with self.assertRaises(TypeError):source.raw['Project']='FORGED'
        with self.assertRaises(TypeError):source.expected_raw['Project']='FORGED'
        exported=result.as_dict();exported['raw_model_projection']['Project']='FORGED'
        self.assertNotEqual(result.raw['Project'],'FORGED')

    def test_stage_exports_explicitly_exclude_reset_save_and_global_bridge(self):
        with patch('socket.socket',side_effect=AssertionError('network I/O')):
            source=self.begin();initialized=self.editor.initialize_project(source)
            result=self.editor.project_preamble(initialized,destination=self.row['destination'],categories=tuple(CATEGORIES))
        exported=result.as_dict()
        for key in ['source_preparation_complete','initial_factory_binding_applied','reset_applied',
                    'before_save_applied','global_bridge_enabled','raw_model_physically_encodable_verified',
                    'saved','physical_device_verified']:
            self.assertIs(exported[key],False)
        self.assertTrue(exported['export_is_review_only'])
        self.assertTrue(exported['forced_parameters_are_membership_only'])
        self.assertFalse(exported['wire_order_verified'])
        self.assertEqual(exported['stages'],['raw-observation','conditional-project-initialization','project-and-category-preamble'])
        self.assertFalse(any(hasattr(self.editor,name) for name in ['apply','save','prepare_save','prepare_source','connect']))
        self.assertEqual(len(json.loads(json.dumps(exported))['expected_raw']),874)


if __name__=='__main__':unittest.main()
