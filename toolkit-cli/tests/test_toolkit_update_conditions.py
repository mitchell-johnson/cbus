import copy
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from cbus_toolkit import toolkit_update_conditions as subject

FIXTURE = Path(__file__).resolve().parents[1]/'research/fixtures/toolkit-update-conditions-vectors.json'
def encode(value): return json.dumps(value,separators=(',',':')).encode()
def facts(*records): return encode({'format':subject.CONTEXT_FORMAT,'culture':'invariant-ascii','files':list(records)})
def definition(path='owned',how=1,what=1,**extra): return {'whatToCheck':what,'howToCheck':how,'fileOrRegistryKeyPath':path,**extra}
def data(expression,**definitions): return encode({'expression':expression,'conditions':definitions})
def rows(report): return {x['stage']:x for x in report.as_dict()['stages']}
def fixture(): return json.loads(FIXTURE.read_text())


class ConditionVectorTests(unittest.TestCase):
    def test_all_279_supported_stage_arms_match_original_values_errors_and_order(self):
        vectors=fixture();cases={c['id']:c for c in vectors['cases']};observed=0;excluded=0
        for oracle in vectors['observations']:
            c=cases[oracle['id']]
            if c['kind']=='integer':excluded+=1;continue
            with self.subTest(id=c['id'],arm=oracle['arm']):
                document={'events':[],'condition_result_cache':dict(c.get('cache',{})),
                          'normalized_expression':c.get('expression','').lower()}
                actual=None;failure=None
                try:
                    if c['kind'] in ('deserialize','validate'):
                        value=subject._json(c['text'].encode());subject._ascii(value)
                        actual=subject._typed(value)
                        if c['kind']=='validate':subject._validate(actual);actual={'validated':True,'model':actual}
                    elif c['kind']=='version':
                        left,right=subject._version(c['left']),subject._version(c['right'])
                        text=lambda x:None if x is None else '.'.join(map(str,[v for v in x if v!=-1]))
                        actual={'left_parsed':left is not None,'right_parsed':right is not None,
                                'left':text(left),'right':text(right),'comparison':None if left is None or right is None else (left>right)-(left<right)}
                    elif c['kind']=='file':
                        event={'observations':[]}
                        actual=subject._leaf(c['id'],{'what':c['what'],'how':c['how'],'path':c['fixture'],'right':c['right']},vectors['logical_fixture_facts'],event)
                    elif c['kind']=='expression':
                        definitions={name:{'name':name,'value':{'what':1,'how':leaf['how'],'path':leaf['fixture'],'right':None}} for name,leaf in c['leaves'].items()}
                        ast=subject._Parser(c['expression']).parse()
                        actual=subject._evaluate(ast,definitions,vectors['logical_fixture_facts'],document)
                    else:self.fail(c['kind'])
                except subject._Outcome as error:failure=error.details
                if oracle['error'] is None:
                    self.assertIsNone(failure);self.assertEqual(json.dumps(actual,sort_keys=True),json.dumps(oracle['result'],sort_keys=True))
                else:
                    self.assertIsNotNone(failure);self.assertEqual(failure['status'],'failed')
                    self.assertEqual(failure['original_error_type'],oracle['error']['type'])
                    if c['kind']=='file':self.assertEqual(failure['original_error_message'],oracle['error']['message'])
                if c['kind']=='expression':
                    self.assertEqual(document['condition_result_cache'],oracle['state']['condition_cache'])
                    if oracle['arm']=='trace':
                        callbacks=oracle['state']['callbacks'];events=document['events']
                        self.assertEqual([x['lookup_name'] for x in events],[x['name'] for x in callbacks])
                        for event,callback in zip(events,callbacks):
                            self.assertEqual(event['cache_before'],callback['before']);self.assertEqual(event['cache_after'],callback['after'])
                            self.assertIs(event['result'],callback['result'])
                observed+=1
        self.assertEqual((observed,excluded),(279,107))
        self.assertFalse(vectors['initial_plan_retroactively_passed']);self.assertEqual(len(vectors['original_plan_discrepancies']),4)


class ConditionTests(unittest.TestCase):
    def evaluate(self,condition,context=None):
        with patch('socket.socket',side_effect=AssertionError('No socket')),patch('pathlib.Path.open',side_effect=AssertionError('No file read')):
            return subject.ToolkitUpdateConditions().evaluate(condition,context=facts() if context is None else context)

    def test_both_boolean_results_are_completed_without_availability_claim(self):
        for expression,result in [('true',True),('false',False),('true OR missing',True),('false AND missing',False)]:
            report=self.evaluate(data(expression));value=report.as_dict()
            self.assertTrue(report.computed);self.assertIs(report.result,result)
            self.assertIs(value['condition_result_under_supplied_context'],result);self.assertEqual(value['events'],[])
            for name in ('package_applicability_evaluated','metadata_admission_evaluated','publisher_trust_evaluated','context_verified','machine_observations_performed'):
                self.assertIs(value[name],False)
            self.assertIsNone(value['updates_available'])

    def test_lazy_facts_cache_order_and_partial_original_failure(self):
        report=self.evaluate(data('A AND A AND missing',A=definition()),facts({'path':'owned','exists':True}))
        value=report.as_dict();self.assertFalse(report.computed)
        self.assertEqual([x['resolution'] for x in value['events']],['leaf','cached','undefined'])
        self.assertEqual(value['condition_result_cache'],{'a':True})
        self.assertEqual([len(x['observations']) for x in value['events']],[1,0,0])
        self.assertEqual(rows(report)['expression_evaluation']['original_error_type'],subject.CONDITION_ERROR)
        missing=self.evaluate(data('A',A=definition()));self.assertEqual(rows(missing)['expression_evaluation']['status'],'unsupported')
        self.assertEqual(rows(missing)['expression_evaluation']['required_fact'],{'path':'owned','fact':'exists'})
        self.assertEqual(missing.as_dict()['events'][0]['observations'][0]['status'],'unknown')

    def test_rhs_validation_precedes_fact_but_exists_comparator_follows_fact(self):
        for right in (None,'','invalid'):
            report=self.evaluate(data('A',A=definition(what=2,how=10,comparisonRightSideValue=right)))
            self.assertEqual(rows(report)['expression_evaluation']['status'],'failed')
            self.assertEqual(report.as_dict()['events'][0]['observations'],[])
        report=self.evaluate(data('A',A=definition(how=99)))
        self.assertEqual(rows(report)['expression_evaluation']['status'],'unsupported')
        report=self.evaluate(data('A',A=definition(how=99)),facts({'path':'owned','exists':False}))
        self.assertEqual(rows(report)['expression_evaluation']['status'],'failed')
        self.assertEqual(len(report.as_dict()['events'][0]['observations']),1)
        for exists,expected in [(False,False),(True,None)]:
            report=self.evaluate(data('A',A=definition(what=2,how=99,comparisonRightSideValue='1.2')),facts({'path':'owned','exists':exists,'file_version':'1.2'}))
            self.assertIs(report.result,expected)

    def test_null_missing_and_unused_unsupported_are_distinct(self):
        for version,computed in [(None,True),('',True),('not-version',True)]:
            report=self.evaluate(data('A',A=definition(what=2,how=11,comparisonRightSideValue='1.2')),facts({'path':'owned','exists':True,'file_version':version}))
            self.assertEqual(report.computed,computed);self.assertIs(report.result,False)
        missing=self.evaluate(data('A',A=definition(what=2,how=11,comparisonRightSideValue='1.2')),facts({'path':'owned','exists':True}))
        self.assertFalse(missing.computed);self.assertEqual(rows(missing)['expression_evaluation']['status'],'unsupported')
        for leaf in (None,definition(what=3),definition(path='<WINSYSDIR>/x')):
            self.assertTrue(self.evaluate(data('true OR A',A=leaf)).computed)
            report=self.evaluate(data('A',A=leaf));self.assertEqual(rows(report)['expression_evaluation']['status'],'unsupported')

    def test_raw_typed_normalization_and_returned_dicts_are_detached(self):
        raw=data('A',A=definition(how='isTrue',what='fileExists'))
        report=self.evaluate(raw,facts({'path':'owned','exists':True}));value=report.as_dict()
        self.assertEqual(value['conditions_sha256'],hashlib.sha256(raw).hexdigest())
        self.assertEqual(value['raw_typed_data']['expression'],'A');self.assertEqual(value['normalized_expression'],'a')
        self.assertEqual(value['typed_model']['conditions'][0]['value']['what'],1)
        value['events'].clear();value['condition_result_cache']['a']=False
        self.assertEqual(len(report.as_dict()['events']),1);self.assertIs(report.as_dict()['condition_result_cache']['a'],True)
        for raw in (b'{}',b'{"conditions":null}',b'{"expression":null}'):
            value=self.evaluate(raw).as_dict();self.assertEqual(value['typed_model']['conditions'],[])
            self.assertEqual(rows(self.evaluate(raw))['definition_validation']['status'],'failed')

    def test_original_grammar_validation_and_source_composed_nested_not(self):
        for text in ('NOT NOT A','!!A','NOT !A','A AND','(A','A OR OR A','NOT','A A'):
            value=self.evaluate(data(text,A=definition())).as_dict()
            self.assertEqual(next(x for x in value['stages'] if x['stage']=='expression_domain')['status'],'failed')
            self.assertEqual(value['events'],[])
        for text in ('NOT (NOT A)','!(!A)','not(not(not A))'):
            report=self.evaluate(data(text,A=definition()),facts({'path':'owned','exists':True}))
            self.assertTrue(report.computed);self.assertIn('source-composed',report.as_dict()['grammar_provenance'])
        for text in ('1','A + A','Abs(A)','A ? true : false','[A]'):
            self.assertEqual(rows(self.evaluate(data(text,A=definition())))['expression_domain']['status'],'unsupported')

    def test_strict_json_and_finite_input_context_bounds(self):
        for raw in (b'{"expression":"true","expression":"false"}',b'['*13+b'0'+b']'*13,b'{"x":'+b'9'*100000+b'}',b'{"x":NaN}',b'{"x":"\\ud800"}',b'\xff',b' '*(subject.MAX_JSON_BYTES+1)):
            report=self.evaluate(raw);self.assertFalse(report.computed);self.assertEqual(rows(report)['typed_input']['status'],'failed')
        for raw in (data('true',**{str(x):None for x in range(9)}),data('t'*257),data('A',A=definition(path='x'*1025)),data('A',A=definition(comparisonRightSideValue='x'*257)),data('true',A={'whatToCheck':True}),data('é')):
            self.assertEqual(rows(self.evaluate(raw))['typed_input']['status'],'unsupported')
        bad=[facts(*({'path':str(x)} for x in range(9))),facts({'path':'x'},{'path':'x'}),facts({'path':'x','exists':None}),facts({'path':'x','exists':1}),facts({'path':'x','file_version':'1'*257}),encode({'format':subject.CONTEXT_FORMAT,'culture':'current','files':[]})]
        for context in bad:self.assertEqual(rows(self.evaluate(data('true'),context))['context_input']['status'],'unsupported')

    def test_unproved_component_spaces_and_controls_are_explicitly_unsupported(self):
        for right in ('1 .2', '1. 2', '+1.2', '1.2\t'):
            report=self.evaluate(data('A',A=definition(what=2,how=10,comparisonRightSideValue=right)))
            self.assertEqual(rows(report)['expression_evaluation']['status'],'unsupported')
            self.assertEqual(report.as_dict()['events'][0]['observations'],[])
        for how in (16,17):
            report=self.evaluate(data('A',A=definition(what=2,how=how,comparisonRightSideValue='1.2')),facts({'path':'owned','exists':True,'file_version':'1.2\x01'}))
            self.assertEqual(rows(report)['expression_evaluation']['status'],'unsupported')
        # Unknown provider definition data is preserved, even when its unused
        # registry fields have no executable meaning in this file-only profile.
        report=self.evaluate(data('true',A=definition(what=3,registryEntryNameOrProductCode='Keep')))
        self.assertEqual(report.as_dict()['typed_model']['conditions'][0]['value']['entry'],'Keep')

    def test_first_interruption_survives_secondary_evidence_failure_and_reuse(self):
        class Rejected(KeyboardInterrupt):
            def __setattr__(self,name,value):raise SystemExit('attachment')
            def __str__(self):raise SystemExit('render')
        first=Rejected();manager=subject.ToolkitUpdateConditions();original=json.dumps
        def dumps(value,*args,**kwargs):
            if type(value) is dict and 'interrupted' in value:raise SystemExit('serialization')
            return original(value,*args,**kwargs)
        with patch.object(subject,'_leaf',side_effect=first),patch.object(subject.json,'dumps',side_effect=dumps):
            with self.assertRaises(KeyboardInterrupt) as raised:manager.evaluate(data('A',A=definition()),context=facts())
        self.assertIs(raised.exception,first);self.assertIs(manager.last_report.cause,first)
        self.assertTrue(manager.last_report.as_dict()['evidence_export_failed'])
        report=manager.evaluate(b'bad',context=facts());self.assertIsNone(report.cause);self.assertFalse(report.computed)

    def test_report_serialization_interruption_retained_on_expected_failure(self):
        first=KeyboardInterrupt('encode failed');manager=subject.ToolkitUpdateConditions()
        raw=data('NOT NOT A');context=facts()
        with patch.object(subject.json,'dumps',side_effect=first):
            with self.assertRaises(KeyboardInterrupt) as raised:manager.evaluate(raw,context=context)
        self.assertIs(raised.exception,first);self.assertIs(manager.last_report.cause,first)

if __name__=='__main__':unittest.main()
