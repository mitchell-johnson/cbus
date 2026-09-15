"""No Docker/Windows needed: explicit selection and pre-execution input boundaries."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from research.original_oracle import OriginalModelOracle, OriginalOracleError, selected_backend


class OriginalOracleTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.root=Path(self.directory.name);self.source=self.root/'OwnedProbe.cs';self.source.write_text('class OwnedProbe {}')
        self.app=self.root/'app';self.app.mkdir();(self.app/'CBusLogicModel.dll').write_bytes(b'owned-test-placeholder')

    def test_backend_default_is_docker_and_unknown_never_executes(self):
        with patch.dict(os.environ,{},clear=True):self.assertEqual(selected_backend(),'docker')
        with patch.dict(os.environ,{'CBUS_ORIGINAL_MODEL_BACKEND':'windows'}):self.assertEqual(selected_backend(),'windows')
        with patch('research.original_oracle.subprocess.run',side_effect=AssertionError('no execution')):
            for value in ('',None,False,'WINDOWS','automatic'):
                if value is None:
                    with patch.dict(os.environ,{'CBUS_ORIGINAL_MODEL_BACKEND':'typo'}):
                        with self.assertRaises(ValueError):OriginalModelOracle(self.source,self.app)
                else:
                    with self.assertRaises(ValueError):OriginalModelOracle(self.source,self.app,backend=value)

    def test_all_job_input_validation_precedes_lazy_compile(self):
        with patch('research.windows_bridge.WindowsModelProbe',side_effect=AssertionError('no Windows execution')) as windows, patch('research.original_oracle.subprocess.run',side_effect=AssertionError('no Docker execution')) as docker:
            for backend in ('windows','docker'):
                oracle=OriginalModelOracle(self.source,self.app,backend=backend)
                for arguments,files in [('one',{}),(['../outside'],{}),(['..'],{}),(['ok'],{'/absolute.tsv':b'x'}),(['ok'],{'CON':b'x'}),(['ok'],{'values.tsv':'text'}),(['ok'],[]),(['ok'],{'OriginalProbe.exe':b'bad'}),(['ok'],{'a.tsv':b'1','A.tsv':b'2'}),(['@65'],{}),(['@00'],{}),(['@064'],{}),(['@-1'],{}),(['@64&echo'],{}),(['@ 64'],{})]:
                    with self.assertRaises(ValueError):oracle.run(arguments,files=files)
            windows.assert_not_called();docker.assert_not_called()

    def test_invalid_configuration_has_no_process_side_effect(self):
        with patch('research.original_oracle.subprocess.run',side_effect=AssertionError('no execution')):
            for options in ({'references':'eDLT.dll'},{'references':('../bad.dll',)},{'references':('Missing.dll',)},{'gui':1},{'timeout':True},{'timeout':301},{'docker_image':'bad image;cmd'}):
                with self.assertRaises(ValueError):OriginalModelOracle(self.source,self.app,**options)

    def test_windows_selection_does_not_launch_docker_and_preserves_expected_failure(self):
        native={'exit_code':42,'complete':False,'stdout':b'partial\r\n','stderr':b'expected vendor error','job_id':'job-owned'}
        fake=MagicMock();fake.run_result.return_value=native
        with patch('research.windows_bridge.WindowsModelProbe',return_value=fake) as factory,patch('research.original_oracle.subprocess.run',side_effect=AssertionError('Docker forbidden')):
            oracle=OriginalModelOracle(self.source,self.app,backend='windows')
            result=oracle.run_result(('values.tsv','preserve'),files={'values.tsv':b'A\t1\n'})
            self.assertEqual((result.returncode,result.stdout,result.stderr),(42,'partial\r\n','expected vendor error'))
            self.assertEqual(result.process_evidence['job_id'],'job-owned')
            with self.assertRaises(OriginalOracleError):oracle.run()
            self.assertEqual(factory.call_count,1)
            fake.run_result.assert_any_call(('values.tsv','preserve'),files={'values.tsv':b'A\t1\n'})

    def test_docker_is_structured_and_gui_keeps_explicit_xvfb(self):
        results=[subprocess.CompletedProcess([],0,'compile warning',''),subprocess.CompletedProcess([],0,'literal output','runtime warning')]
        with patch('research.original_oracle.subprocess.run',side_effect=results) as run:
            with OriginalModelOracle(self.source,self.app,backend='docker',gui=True) as oracle:
                result=oracle.run_result(('values.tsv','-1'),files={'values.tsv':b'KEY\tVALUE\n'})
                self.assertEqual(Path(oracle._temporary.name,'values.tsv').read_bytes(),b'KEY\tVALUE\n')
                self.assertEqual((result.stdout,result.stderr),('literal output','runtime warning'))
                commands=[call.args[0] for call in run.call_args_list]
                self.assertEqual(commands[0][-6:],['-r:/input/CBusLogicModel.dll','-r:System.Xml.Linq','-r:System.Windows.Forms','-r:System.Drawing','-out:OriginalProbe.exe','OwnedProbe.cs'])
                self.assertEqual(commands[1][-6:],['xvfb-run','-a','mono','OriginalProbe.exe','values.tsv','-1'])
                self.assertTrue(all('sh' not in command and 'none' in command for command in commands))


    def test_bounded_at_token_uses_pinned_compilation_and_immutable_bridge_job(self):
        fake=MagicMock();fake.prefix='probe-'+'a'*16
        fake.source_sha256=__import__('hashlib').sha256(self.source.read_bytes()).hexdigest()
        fake.bridge.path.return_value=r'C:\Owned\vendor'
        fake.bridge.run.return_value={'exit_code':0,'complete':True,'admitted':True,'stdout':b'INDEX64\r\n','stderr':b''}
        with patch('research.windows_bridge.WindowsModelProbe',return_value=fake),patch('research.original_oracle.subprocess.run',side_effect=AssertionError('Docker forbidden')):
            oracle=OriginalModelOracle(self.source,self.app,backend='windows')
            self.assertEqual(oracle.run(('values.tsv','@64'),files={'values.tsv':b'KEY\tVALUE\n'}),'INDEX64\r\n')
            fake.run_result.assert_not_called()
            script=fake.bridge.run.call_args.args[0]
            self.assertIn(fake.prefix+'-values.tsv @64\n',script)
            fake.bridge.push.assert_called_once_with('vendor\\'+fake.prefix+'-values.tsv',b'KEY\tVALUE\n')

    def test_source_staleness_and_compile_failure_never_fall_back(self):
        oracle=OriginalModelOracle(self.source,self.app,backend='docker');self.source.write_text('changed')
        with patch('research.original_oracle.subprocess.run',side_effect=AssertionError('no execution')):
            with self.assertRaises(ValueError):oracle.run()
        with patch('research.original_oracle.subprocess.run',return_value=subprocess.CompletedProcess([],1,'compiler details','failure')) as run:
            with self.assertRaises(OriginalOracleError) as caught:OriginalModelOracle(self.source,self.app,backend='docker').run()
            self.assertEqual(caught.exception.stage,'compile');self.assertEqual(run.call_count,1)


if __name__=='__main__':unittest.main()
