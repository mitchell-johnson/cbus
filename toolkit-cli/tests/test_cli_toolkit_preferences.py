from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cbus_toolkit import cli
from test_toolkit_preferences_controls import initial, display


class PreferencesCLITests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.path=Path(temp.name)/'state.json'
        self.state={'format':'cbus-toolkit-preferences-state-v1','values':initial(),'display_values':display()}
        self.path.write_text(json.dumps(self.state))

    def invoke(self,*arguments,status=0):
        out,err=io.StringIO(),io.StringIO()
        with redirect_stdout(out),redirect_stderr(err), \
            patch('cbus_toolkit.cgate.CGateClient',side_effect=AssertionError('Offline preferences must not connect')), \
            patch('cbus_toolkit.windows_preferences.WindowsPreferenceRegistry',side_effect=AssertionError('Offline preferences must not access registry')):
            actual=cli.main(list(map(str,arguments)))
        self.assertEqual(actual,status,out.getvalue()+err.getvalue())
        return json.loads(out.getvalue() or err.getvalue())

    def test_schema_complete40_and_no_invented_defaults(self):
        result=self.invoke('preferences','schema')
        self.assertEqual(len(result['registered_preferences']),40)
        self.assertEqual(len(result['display_preferences']),5)
        self.assertEqual(sum(not x['skip_save'] for x in result['registered_preferences']),35)
        self.assertFalse(result['registry_accessed']);self.assertFalse(result['startup_defaults_inferred'])
        self.assertTrue(all('default' not in x for x in result['registered_preferences']))

    def test_controls_plan_order_repeated_controls_and_retained_state_output(self):
        before=self.path.read_bytes()
        controls=self.invoke('preferences','controls',self.path)
        self.assertEqual(controls['controls']['cmbJavaHeapMax'],'256')
        a=self.invoke('preferences','plan',self.path,'--edit','chkApplicationLog=false','--edit','chkLoadChangePort=true',
                     '--edit','cmbJavaHeapMax="512"','--edit','spnFeedbackLogSize=99999','--edit','rdoTagNamesUseHex=true')
        self.assertFalse(a['values']['ApplicationLogDisable'])
        self.assertEqual(a['values']['JavaHeapMin'],32);self.assertEqual(a['values']['JavaHeapMax'],512)
        self.assertEqual(a['values']['FeedbackLogSize'],9900)
        self.assertTrue(a['display_values']['tag_hex']);self.assertTrue(a['display_values']['tag_override'])
        self.assertEqual(a['state']['format'],self.state['format'])
        self.assertEqual(a['state']['values'],a['values'])
        self.assertEqual(self.path.read_bytes(),before)
        b=self.invoke('preferences','plan',self.path,'--edit','chkLoadChangePort=true','--edit','chkApplicationLog=false')
        self.assertTrue(b['values']['ApplicationLogDisable'])
        self.assertFalse(b['storage_applied'])
        c=self.invoke('preferences','plan',self.path,'--edit','chkLoadChangePort=false','--edit','chkLoadChangePort=true')
        self.assertEqual(c['controls']['message_resource_ids'],[0xb054])

    def test_reject_malformed_duplicate_nonfinite_incomplete_and_unknown_state(self):
        for text in ('{"format":1,"format":2}', '[NaN]', '{}', 'null',
                     json.dumps({**self.state,'values':[]}),json.dumps({**self.state,'extra':1}),
                     json.dumps({**self.state,'display_values':{**display(),'tag_hex':2}})):
            self.path.write_text(text)
            self.invoke('preferences','controls',self.path,status=1)
        self.path.write_text(' '* (1024*1024+1))
        self.assertIn('1 MiB',self.invoke('preferences','controls',self.path,status=1)['error'])

    def test_edit_validation_prevents_partial_file_changes(self):
        before=self.path.read_bytes()
        for edit in ('missing-equals','bad=true','cmbJavaHeapMax=512','cmbJavaHeapMax="6A4"',
                     'chkFeedbackLog=1','chkFeedbackLog=NaN','rdbShutdownAsk=false',
                     'rgSortGroups=2','cmbTemperatureUnit=-1','spnFeedbackLogSize=true'):
            self.invoke('preferences','plan',self.path,'--edit','chkFeedbackLog=true','--edit',edit,status=1)
            self.assertEqual(self.path.read_bytes(),before)
        result=self.invoke('preferences','plan',self.path,'--edit','chkLoadChangePort=false',
                           '--edit','chkApplicationLog=true',status=1)
        self.assertIn('disabled',result['error'])


    def test_registry_save_preview_has43_planned_calls_and_no_registry_access(self):
        result=self.invoke('preferences','registry-save',self.path,'--dry-run')
        self.assertEqual(len(result['operations']),43)
        self.assertFalse(result['registry_accessed']);self.assertFalse(result['writes_applied'])
        self.assertTrue(all('completed' not in row and 'write_succeeded' not in row for row in result['operations']))
        self.assertEqual([row['name'] for row in result['operations'][:5]],
                         ['DisplayHexAddress','DisplayAddressValue','SortModeApplications','SortModeGroups','SortModeLevels'])

    def test_registry_save_and_load_expose_full_state_and_missing_default_writes(self):
        from test_toolkit_preferences_store import Registry
        registry=Registry()
        with patch('cbus_toolkit.toolkit_preferences_cli.registry_backend',return_value=registry):
            saved=self.invoke('preferences','registry-save',self.path)
            self.assertTrue(saved['complete']);self.assertTrue(saved['registry_accessed'])
            self.assertEqual(len(saved['state']['values']),40)
            self.assertEqual(saved['state']['values'],self.state['values'])
            loaded=self.invoke('preferences','registry-load',self.path)
            self.assertTrue(loaded['complete']);self.assertEqual(len(loaded['state']['values']),40)
            self.assertEqual([row['name'] for row in loaded['default_writes']],
                             ['', '', 'ShowDatabaseLabelsOption'])
        self.assertEqual(json.loads(self.path.read_text()),self.state)

    def test_native_input_validation_precedes_backend_creation(self):
        self.state['values']['Default Site']='embedded\0nul'
        self.path.write_text(json.dumps(self.state))
        with patch('cbus_toolkit.toolkit_preferences_cli.registry_backend',side_effect=AssertionError('No registry open')):
            for action in ('registry-load','registry-save'):
                self.invoke('preferences',action,self.path,status=1)

    def test_registry_partial_save_stops_and_preserves_first_error_prefix(self):
        from test_toolkit_preferences_store import Registry
        registry=Registry()
        def fault(row):
            if row[0]=='write' and row[3]=='ApplicationLogDisable':raise OSError('owned write failure')
        registry.fault=fault
        with patch('cbus_toolkit.toolkit_preferences_cli.registry_backend',return_value=registry):
            result=self.invoke('preferences','registry-save',self.path,status=1)
        self.assertFalse(result['complete']);self.assertFalse(result['algorithm_completed'])
        self.assertEqual(result['operations'][-1]['name'],'ApplicationLogDisable')
        self.assertFalse(result['operations'][-1]['completed'])
        self.assertEqual(sum(row[0]=='write' and row[3]=='ApplicationLogDisable' for row in registry.calls),1)
        self.assertEqual(result['error']['message'],'owned write failure')
        self.assertFalse(result['transactional'])

    def test_registry_interrupt_keeps_evidence_when_exception_rejects_attribute(self):
        from test_toolkit_preferences_store import Registry
        class RejectEvidence(KeyboardInterrupt):
            def __setattr__(self,name,value):
                if name=='toolkit_preferences_evidence':raise SystemExit('blocked evidence assignment')
                return super().__setattr__(name,value)
        for kind in (KeyboardInterrupt,RejectEvidence):
            registry=Registry();error=kind('owned interruption')
            def fault(row):
                if row[0]=='write' and row[3]=='SortModeGroups':raise error
            registry.fault=fault
            with patch('cbus_toolkit.toolkit_preferences_cli.registry_backend',return_value=registry):
                result=self.invoke('preferences','registry-save',self.path,status=130)
            evidence=result['toolkit_preferences_evidence']
            self.assertFalse(evidence['complete'])
            self.assertEqual(evidence['operations'][-1]['name'],'SortModeGroups')
            self.assertEqual(len(registry.calls),4)


if __name__=='__main__':unittest.main()
