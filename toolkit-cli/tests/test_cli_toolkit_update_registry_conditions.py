"""Offline v2 CLI integration with exact source bytes and retained evidence."""
from contextlib import redirect_stdout, redirect_stderr
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cbus_toolkit import cli, toolkit_update_conditions as core
from cbus_toolkit import toolkit_update_conditions_cli as helper
from cbus_toolkit import _toolkit_update_registry_conditions as registry
from tests.test_toolkit_update_registry_conditions import context, condition, fact, data, encode, PATH


class RegistryConditionsCLITests(unittest.TestCase):
    def files(self, directory, definition, records, expression='A', extra=None):
        raw = encode(data(expression, A=definition, **(extra or {})))
        ctx = encode(context(*records))
        source=Path(directory)/'conditions.json';source.write_bytes(raw)
        facts=Path(directory)/'context.json';facts.write_bytes(ctx)
        return ['--compact','update-condition-stages',str(source),'--context',str(facts)]

    def invoke(self, args, expected):
        out,err=io.StringIO(),io.StringIO()
        with redirect_stdout(out),redirect_stderr(err),patch('socket.socket',side_effect=AssertionError('No network')):
            status=cli.main(args)
        self.assertEqual(status,expected,out.getvalue()+err.getvalue())
        return json.loads(out.getvalue() or err.getvalue())

    def test_true_false_and_exact_typed_source_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            for number,result in ((-2147483648,True),(0,False)):
                args=self.files(directory,condition(right='-2147483648'),[fact(number)])
                raw,ctx=Path(args[2]).read_bytes(),Path(args[4]).read_bytes()
                value=self.invoke(args,0)
                self.assertIs(value['condition_result_under_supplied_context'],result)
                self.assertEqual(value['profile'],registry.PROFILE)
                self.assertEqual(value['source']['context_file_sha256'],hashlib.sha256(ctx).hexdigest())
                self.assertEqual(value['source']['conditions_file_sha256'],hashlib.sha256(raw).hexdigest())
                self.assertEqual(value['events'][0]['observations'][0]['result'],{'kind':'System.Int32','value':number})
                self.assertEqual((Path(args[2]).read_bytes(),Path(args[4]).read_bytes()),(raw,ctx))
                for key in ('registry_accessed','context_verified','registry_provider_verified','machine_observations_performed','package_applicability_evaluated','publisher_trust_evaluated'):
                    self.assertIs(value[key],False)
                self.assertIsNone(value['updates_available'])

    def test_missing_value_shortcut_and_original_error_vs_unsupported(self):
        with tempfile.TemporaryDirectory() as directory:
            args=self.files(directory,condition(how=11,right=None),[fact(registry.SENTINEL)])
            self.assertIs(self.invoke(args,0)['condition_result_under_supplied_context'],True)
            args=self.files(directory,condition(how=11,right='BAD-RHS'),[fact('')])
            value=self.invoke(args,1)
            self.assertEqual(value['stages'][-1]['status'],'failed')
            self.assertEqual(value['stages'][-1]['original_error_message'],'value defined for integer comparison cannot be converted to int: bad-rhs')
            args=self.files(directory,condition(what=5,how=12,right='a'),[fact('Z')])
            value=self.invoke(args,1);self.assertEqual(value['stages'][-1]['status'],'unsupported')
            self.assertEqual(len(value['events'][0]['observations']),1)
            args=self.files(directory,condition(what=3,how=99),[])
            value=self.invoke(args,1);self.assertEqual(value['stages'][-1]['status'],'unsupported')
            self.assertEqual(value['events'][0]['observations'][0]['status'],'unknown')

    def test_schema_errors_are_eager_but_leaf_queries_and_cache_are_lazy(self):
        with tempfile.TemporaryDirectory() as directory:
            args=self.files(directory,condition(),[fact(0)],'A AND a OR B',{'B':condition(path='HKLM\\Unproved')})
            value=self.invoke(args,0)
            self.assertEqual([x['resolution'] for x in value['events']],['leaf','cached'])
            self.assertEqual(value['unrequested_definition_names'],['B'])
            bad=context(fact(True));Path(args[4]).write_bytes(encode(bad))
            value=self.invoke(args,1);self.assertEqual(value['stages'][1]['status'],'unsupported')
            self.assertEqual(value['events'],[])

    def test_first_interruption_retains_v2_prior_cache_and_rejects_stale_reuse(self):
        class First(KeyboardInterrupt):
            def __setattr__(self,name,value):raise SystemExit('secondary attachment')
        first=First('stopped');original=registry.leaf
        def stop_second(name,*args):
            if name=='b':raise first
            return original(name,*args)
        with tempfile.TemporaryDirectory() as directory:
            args=self.files(directory,condition(),[fact(0)],'A AND B',{'B':condition()})
            parsed=cli.build_parser().parse_args(args)
            with patch.object(registry,'leaf',side_effect=stop_second),self.assertRaises(KeyboardInterrupt) as caught:
                helper.run(parsed)
            self.assertIs(caught.exception,first)
            value=helper.error_payload(first,parsed)['toolkit_update_conditions_evidence']
            self.assertEqual(value['condition_result_cache'],{'a':True});self.assertEqual(value['profile'],registry.PROFILE)
            value['events'].clear()
            self.assertEqual(len(helper.error_payload(first,parsed)['toolkit_update_conditions_evidence']['events']),2)
            self.assertEqual(helper.error_payload(KeyboardInterrupt(),parsed),{})
            parsed.context=Path(directory)/'missing'
            with self.assertRaises(OSError):helper.run(parsed)
            self.assertEqual(helper.error_payload(first,parsed),{})

    def test_completed_v2_false_result_survives_report_export_failure(self):
        first=ValueError('report export')
        with tempfile.TemporaryDirectory() as directory:
            args=self.files(directory,condition(right='1'),[fact(0)])
            with patch.object(core.ConditionStageReport,'as_dict',side_effect=first):
                value=self.invoke(args,1)['toolkit_update_conditions_evidence']
            self.assertIs(value['condition_result_under_supplied_context'],False)
            self.assertEqual(value['profile'],registry.PROFILE)
            self.assertEqual(value['condition_result_cache'],{'a':False})
            self.assertTrue(value['evidence_export_failed']);self.assertIn('source',value)


if __name__=='__main__':unittest.main()
