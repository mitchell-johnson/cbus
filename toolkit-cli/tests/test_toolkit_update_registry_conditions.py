import copy
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from cbus_toolkit import toolkit_update_conditions as subject
from cbus_toolkit import _toolkit_update_registry_conditions as registry

FIXTURES = Path(__file__).resolve().parents[1] / 'research/fixtures'
PATH = 'HKEY_CURRENT_USER\\Software\\Example'


def encode(value): return json.dumps(value, separators=(',', ':')).encode()
def primitive(value): return {'kind': 'null' if value is None else 'System.Int32' if type(value) is int else 'System.String', 'value': value}
def fact(value, *, path=PATH, entry='Value', default=registry.SENTINEL):
    return {'path': path, 'entry': entry, 'default': primitive(default), 'result': primitive(value)}
def context(*records, files=()):
    return {'format': registry.CONTEXT_FORMAT, 'culture': 'invariant-ascii', 'files': list(files), 'registry_provider': registry.PROVIDER, 'registry_reads': list(records)}
def condition(what=6, how=10, right='0', path=PATH, entry='Value'):
    return {'whatToCheck': what, 'howToCheck': how, 'comparisonRightSideValue': right, 'fileOrRegistryKeyPath': path, 'registryEntryNameOrProductCode': entry}
def data(expression='A', **definitions): return {'expression': expression, 'conditions': definitions or {'A': condition()}}
def stage(report, name='expression_evaluation'): return next(x for x in report.as_dict()['stages'] if x['stage'] == name)


class RegistryVectorsTests(unittest.TestCase):
    def test_all_248_complete_v1_reports_are_byte_identical(self):
        baseline = json.loads((FIXTURES/'toolkit-update-conditions-v1-report-baseline.json').read_bytes())
        self.assertEqual(baseline['source_sha256'], 'da8ebb5837c4e87a5612b63166d4e6a7a2619ef1d9486de081677453cc1fae31')
        self.assertEqual(len(baseline['cases']), 248)
        for case in baseline['cases']:
            with self.subTest(id=case['id']):
                report = subject.ToolkitUpdateConditions().evaluate(case['conditions'].encode(), context=case['context'].encode())
                self.assertEqual(hashlib.sha256(report._document.encode()).hexdigest(), case['report_sha256'])

    def test_twelve_actual_registry_leaves_preserve_one_explicit_exclusion(self):
        vectors = json.loads((FIXTURES/'toolkit-update-registry-conditions-vectors.json').read_bytes())
        self.assertEqual(len(vectors['original_raw_records']), 47)
        provider = vectors['original_provider']
        self.assertTrue(provider['same_original_and_witness']); self.assertFalse(provider['type_remapping'])
        self.assertEqual((provider['source_memberref'], provider['method_token']), (0x0a000054, 0x060000f3))
        self.assertTrue(vectors['cleanup']['root_absence_verified']); self.assertTrue(vectors['cleanup']['handles_closed'])
        self.assertEqual(len(vectors['cleanup']['cleanup']), 11)
        supported = excluded = errors = 0
        for case in vectors['cases']:
            with self.subTest(id=case['id']):
                raw = case['condition']; witness = case['witness']; original = case['original']
                supplied = context({'path': witness['path'], 'entry': witness['entry'], 'default': witness['default_value'], 'result': witness['result']})
                typed = subject._typed({'conditions': {'A': raw}, 'expression': 'A'})['conditions'][0]['value']
                event = {'observations': []}; failure = None; actual = None
                try:
                    actual = registry.leaf(raw['name'], typed, registry.facts(supplied), event)
                except subject._Outcome as error:
                    failure = error.details
                self.assertEqual(event['observations'][0]['result'], witness['result'])
                self.assertFalse(witness['original_call_intercepted'])
                if not case['portable_supported']:
                    excluded += 1; self.assertIs(original['result'], True)
                    self.assertEqual(failure['status'], 'unsupported'); continue
                supported += 1
                if original['error'] is None:
                    self.assertIsNone(failure); self.assertIs(actual, original['result'])
                else:
                    errors += 1; self.assertEqual(failure['status'], 'failed')
                    self.assertEqual(failure['original_error_type'], original['error']['type'])
                    self.assertEqual(failure['original_error_message'], original['error']['message'])
        self.assertEqual((supported, excluded, errors), (11, 1, 2))

    def test_107_original_int32_helpers_keep_all_values_and_exact_errors(self):
        vectors = json.loads((FIXTURES/'toolkit-update-conditions-vectors.json').read_bytes())
        cases = {x['id']: x for x in vectors['cases'] if x['kind'] == 'integer'}
        counts = [0, 0]
        for original in vectors['observations']:
            if original['id'] not in cases: continue
            case = cases[original['id']]
            with self.subTest(id=case['id']):
                if original['error'] is None:
                    counts[0] += 1
                    self.assertIs(registry.compare_int(case['left'], case['right'], case['how']), original['result'])
                else:
                    counts[1] += 1
                    with self.assertRaises(subject._Outcome) as raised:
                        registry.compare_int(case['left'], case['right'], case['how'])
                    self.assertEqual(raised.exception.details['status'], 'failed')
                    self.assertEqual(raised.exception.details['original_error_type'], original['error']['type'])
                    self.assertEqual(raised.exception.details['original_error_message'], original['error']['message'])
        self.assertEqual(counts, [76, 31])


class RegistryConditionsTests(unittest.TestCase):
    def evaluate(self, definition=None, *records, expression='A', extra=None, files=()):
        raw = data(expression, A=condition() if definition is None else definition, **(extra or {}))
        with patch('socket.socket', side_effect=AssertionError('No sockets')), patch('pathlib.Path.open', side_effect=AssertionError('No file/provider read')):
            return subject.ToolkitUpdateConditions().evaluate(encode(raw), context=encode(context(*records, files=files)))

    def test_typed_default_and_exact_query_identity_no_inference(self):
        wrong = fact(1, entry='Test', default=registry.SENTINEL)
        result = self.evaluate(condition(what=3, how=1, entry=None), wrong)
        self.assertEqual(stage(result)['status'], 'unsupported')
        required = stage(result)['required_registry_query']
        self.assertEqual(required['default'], primitive(1)); self.assertEqual(required['entry'], 'Test')
        right = fact(1, entry='Test', default=1)
        result = self.evaluate(condition(what=3, how=1, entry=None), wrong, right)
        self.assertIs(result.result, True)
        for changed in (fact(1, entry='test', default=1), fact(1, path=PATH.lower().replace('hkey_current_user', 'HKEY_CURRENT_USER'), entry='Test', default=1)):
            self.assertEqual(stage(self.evaluate(condition(what=3, how=1), changed))['status'], 'unsupported')

    def test_existence_null_empty_sentinel_and_primitive_are_distinct(self):
        for value, exists in ((None, False), ('', True), (registry.SENTINEL, False), (registry.SENTINEL.upper(), True), (0, True), (-2147483648, True)):
            for how in (1, 2):
                with self.subTest(value=value, how=how):
                    self.assertIs(self.evaluate(condition(what=4, how=how), fact(value)).result, exists if how == 1 else not exists)
                    # Key existence does not apply the string-sentinel test.
                    self.assertIs(self.evaluate(condition(what=3, how=how), fact(value, entry='Test', default=1)).result, (value is not None) if how == 1 else (value is None))

    def test_content_shortcuts_precede_null_rhs_and_unsupported_comparators(self):
        for value in (None, registry.SENTINEL):
            for what in (5, 6):
                for how in (0, 10, 11, 12, 16, 99):
                    report = self.evaluate(condition(what=what, how=how, right=None), fact(value))
                    self.assertIs(report.result, how == 11)
                    self.assertEqual(report.as_dict()['events'][0]['registry_steps'][-1]['step'], 'missing_content_shortcut')
        report = self.evaluate(condition(how=11, right=None), fact(''))
        self.assertEqual(stage(report)['status'], 'failed'); self.assertIn('ComparisonRightSideValue is null', stage(report)['reason'])
        self.assertIs(self.evaluate(condition(how=11, right='0'), fact('')).result, False)
        self.assertIs(self.evaluate(condition(how=99, right='0'), fact('')).result, False)
        self.assertIs(self.evaluate(condition(how=11, right='\v'), fact(registry.SENTINEL)).result, True)
        self.assertEqual(stage(self.evaluate(condition(how=11, right='bad'), fact('')))['reason'], 'value defined for integer comparison cannot be converted to int: bad')

    def test_integer_rhs_first_and_supported_control_characters(self):
        for text in ('\t12\r\n', ' +00012 ', '-0', '0'*255):
            rhs = '12' if '12' in text else '0'
            self.assertIs(self.evaluate(condition(right=rhs), fact(text)).result, True)
        for lhs, rhs, reason in (('bad-left', 'bad-right', 'defined'), ('', 'bad-right', 'defined'), ('bad-left', '0', 'read')):
            row = stage(self.evaluate(condition(right=rhs), fact(lhs)))
            self.assertEqual(row['status'], 'failed'); self.assertIn(reason, row['reason'])
        # Unproved LHS controls must not be inspected before the RHS failure.
        for control in ('\v', '\f', '\x01', '\x7f'):
            row = stage(self.evaluate(condition(right='bad'), fact(control)))
            self.assertEqual(row['status'], 'failed'); self.assertIn('defined', row['reason'])
            row = stage(self.evaluate(condition(right='0'), fact(control)))
            self.assertEqual(row['status'], 'unsupported')
            row = stage(self.evaluate(condition(right=control), fact('')))
            self.assertEqual(row['status'], 'unsupported')

    def test_string_comparisons_restrict_collation_but_keep_raw_lowercase(self):
        for how, right, result in ((10, 'mIxEd', True), (11, 'mIxEd', False), (17, 'IX', True), (17, '', True), (17, 'absent', False)):
            report = self.evaluate(condition(what=5, how=how, right=right), fact('MiXeD'))
            self.assertIs(report.result, result)
            event = report.as_dict()['events'][0]
            self.assertEqual(event['observations'][0]['result']['value'], 'MiXeD')
            self.assertEqual(event['registry_steps'][1], {'step':'lowercase_lhs','text':'MiXeD','lowered':'mixed'})
        for how in (12, 13, 14, 15, 16):
            self.assertEqual(stage(self.evaluate(condition(what=5, how=how, right='a'), fact('Z')))['status'], 'unsupported')
        self.assertEqual(stage(self.evaluate(condition(what=5, how=17), fact('\t')))['status'], 'unsupported')

    def test_path_entry_validation_and_query_before_invalid_how(self):
        for what, path, entry, fragment in ((3, None, None, 'key path'), (4, None, None, 'key path'), (4, PATH, '', 'entry name'), (5, PATH, None, 'entry name')):
            report = self.evaluate(condition(what=what, path=path, entry=entry))
            self.assertEqual(stage(report)['status'], 'failed'); self.assertIn(fragment, stage(report)['reason'])
            self.assertEqual(report.as_dict()['events'][0]['observations'], [])
        for path in ('HKLM\\Software\\Example', 'hkcu\\Software', 'HKCUX\\Software', 'HKCU\\', 'HKCU\\A\\\\B', 'HKCU\\A\t'):
            self.assertEqual(stage(self.evaluate(condition(path=path)))['status'], 'unsupported')
        for what in (3, 4):
            report = self.evaluate(condition(what=what, how=99))
            self.assertEqual(stage(report)['status'], 'unsupported')
            record = fact(None, entry='Test', default=1) if what == 3 else fact(None)
            report = self.evaluate(condition(what=what, how=99), record)
            self.assertEqual(stage(report)['status'], 'failed')
            self.assertEqual(len(report.as_dict()['events'][0]['observations']), 1)
        report = self.evaluate(condition(path='HKCU\\Software\\Example'), fact(0))
        self.assertIs(report.result, True)
        self.assertEqual(report.as_dict()['events'][0]['path'], 'HKCU\\Software\\Example')
        self.assertEqual(report.as_dict()['events'][0]['observations'][0]['query']['path'], PATH)

    def test_lazy_registry_facts_success_cache_and_mixed_file_leaves(self):
        report = self.evaluate(condition(), fact(0), expression='A AND A AND B', extra={'B':condition(path=PATH+'2')})
        doc = report.as_dict()
        self.assertEqual([x['resolution'] for x in doc['events']], ['leaf','cached','leaf'])
        self.assertEqual(doc['condition_result_cache'], {'a':True})
        self.assertEqual([len(x['observations']) for x in doc['events']], [1,0,1])
        report = self.evaluate(condition(path='HKLM\\X'), expression='true OR A')
        self.assertIs(report.result, True); self.assertEqual(report.as_dict()['events'], [])
        report = self.evaluate(condition(), fact(0), expression='A AND B', extra={'B':condition(what=1,how=1,path='owned')}, files=({'path':'owned','exists':False},))
        self.assertIs(report.result, False)
        for key in ('registry_accessed','context_verified','registry_provider_verified','machine_observations_performed','publisher_trust_evaluated','package_applicability_evaluated'):
            self.assertIs(report.as_dict()[key], False)
        self.assertIsNone(report.as_dict()['updates_available'])

    def test_strict_context_tags_bounds_duplicates_and_eager_schema(self):
        bad=[]
        for field, value in (('format','v2'),('culture','current'),('registry_provider','Registry32'),('registry_reads',{}),('registry_reads',[fact(0)]*9)):
            item=context();item[field]=value;bad.append(item)
        for changed in ({'kind':'System.Int32','value':True},{'kind':'System.Int32','value':2147483648},{'kind':'System.Int32','value':'1'},{'kind':'null','value':0},{'kind':'System.String','value':'x'*257},{'kind':'System.Byte[]','value':[]},{'kind':'System.String','value':'é'}):
            item=fact(0);item['result']=changed;bad.append(context(item))
        for field,value in (('path','HKCU\\Software\\Example'),('path','x'*1025),('entry','x'*257),('entry',''),('default',primitive(0)),('default',primitive(None)),('default',{'kind':'System.Int32','value':True})):
            item=fact(0);item[field]=value;bad.append(context(item))
        bad.extend((context(fact(0),fact(1)), {**context(),'unexpected':True}))
        for item in bad:
            with self.subTest(context=item):
                report=subject.ToolkitUpdateConditions().evaluate(encode(data('true')),context=encode(item))
                self.assertEqual(stage(report,'context_input')['status'],'unsupported')
        for raw in (b'{"x":NaN}', b'['*13+b'0'+b']'*13, b'{"x":'+b'9'*100000+b'}', b'{"x":"\\ud800"}', b'x'*(subject.MAX_JSON_BYTES+1)):
            report=subject.ToolkitUpdateConditions().evaluate(encode(data('true')),context=raw)
            self.assertEqual(stage(report,'context_input')['status'],'failed')

    def test_detached_evidence_fresh_cache_and_first_interruption(self):
        manager=subject.ToolkitUpdateConditions();raw=encode(data());ctx=encode(context(fact(0)))
        report=manager.evaluate(raw,context=ctx);doc=report.as_dict();doc['events'][0]['observations'][0]['result']['value']=99
        self.assertEqual(report.as_dict()['events'][0]['observations'][0]['result']['value'],0)
        unknown=manager.evaluate(raw,context=encode(context()))
        self.assertFalse(unknown.computed);self.assertEqual(unknown.as_dict()['condition_result_cache'],{})
        class First(KeyboardInterrupt):
            def __setattr__(self, name, value): raise SystemExit('secondary attachment')
        first=First('primary');dumps=json.dumps
        def serialize(value,*args,**kwargs):
            if type(value) is dict and 'interrupted' in value:raise SystemExit('secondary serialization')
            return dumps(value,*args,**kwargs)
        with patch.object(registry,'compare_int',side_effect=first),patch.object(subject.json,'dumps',side_effect=serialize):
            with self.assertRaises(KeyboardInterrupt) as raised:manager.evaluate(raw,context=ctx)
        self.assertIs(raised.exception,first);self.assertIs(manager.last_report.cause,first)
        self.assertTrue(manager.last_report.as_dict()['evidence_export_failed'])


if __name__ == '__main__': unittest.main()
