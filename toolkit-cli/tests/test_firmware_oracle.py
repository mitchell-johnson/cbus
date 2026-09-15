"""Guard tests use fake runtime bytes/processes, never a physical serial device."""
from pathlib import Path
import hashlib
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from research import firmware_oracle as api


class FirmwareOracleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.runtime = self.root/'runtime'; self.app = self.root/'app'
        runtime = {}; vendor = {}
        for directory, names, hashes in ((self.runtime, ('bin/mono-sgen64','lib/mono/4.5/mcs.exe','etc/mono/config'), runtime),
                (self.app, ('FirmwareUpdater.exe','Firmware/eDLTFirmware/eDLTFirmware_1.7.0.zip'), vendor)):
            for name in names:
                path=directory/name; path.parent.mkdir(parents=True,exist_ok=True); data=('fake '+name).encode();path.write_bytes(data);hashes[name]=hashlib.sha256(data).hexdigest()
        for target,value in (('RUNTIME_HASHES',runtime),('VENDOR_HASHES',vendor)):
            context=patch.object(api,target,value);context.start();self.addCleanup(context.stop)
        context=patch.object(api.platform,'system',return_value='Darwin');context.start();self.addCleanup(context.stop)

    def oracle(self, **options):
        instance=api.MacOSFirmwareOracle(self.app,mono_root=self.runtime,**options);self.addCleanup(instance.close);return instance

    @staticmethod
    def success(args, **kwargs):
        if 'NativeFirmwareProbe.cs' in args:
            (Path(kwargs['cwd'])/'NativeFirmwareProbe.exe').write_bytes(b'fake compiled bytes')
        return subprocess.CompletedProcess(args,0,'actual fixture output','')

    def test_explicit_backend_root_platform_and_timeout_before_execution(self):
        with patch.dict(os.environ,{},clear=True):
            self.assertEqual(api.selected_firmware_backend(),'docker')
            with self.assertRaisesRegex(ValueError,'ROOT'):api.MacOSFirmwareOracle(self.app)
        for value in ('windows','automatic','',False):
            with patch.dict(os.environ,{'CBUS_FIRMWARE_ORACLE_BACKEND':str(value)}),self.assertRaises(ValueError):api.selected_firmware_backend()
        with patch.object(api.subprocess,'run',side_effect=AssertionError('no process')) as run:
            for value in (False,0,-1,61,float('nan')):
                with self.assertRaises(ValueError):self.oracle(timeout=value)
            with patch.object(api.platform,'system',return_value='Linux'),self.assertRaises(ValueError):self.oracle()
            run.assert_not_called()

    def test_runtime_vendor_probe_and_inventory_changes_reject_before_compile(self):
        for path in (self.runtime/'bin/mono-sgen64',self.app/'FirmwareUpdater.exe'):
            old=path.read_bytes();path.write_bytes(b'modified')
            with patch.object(api.subprocess,'run',side_effect=AssertionError('no process')),self.assertRaisesRegex(ValueError,'artifact'):self.oracle()
            path.write_bytes(old)
        rogue=self.app/'Firmware/eDLTFirmware/rogue.zip';rogue.write_bytes(b'x')
        with self.assertRaisesRegex(ValueError,'inventory'):self.oracle()
        rogue.unlink()
        with patch.object(api,'PROBE_SHA256','0'*64),self.assertRaisesRegex(ValueError,'probe differs'):self.oracle()
        instance=self.oracle();(self.runtime/'etc/mono/config').write_bytes(b'changed after planning')
        with patch.object(api.subprocess,'run',side_effect=AssertionError('no process')),self.assertRaises(ValueError):instance.compile()

    def test_structured_commands_literal_binding_clean_environment_and_actual_results(self):
        with patch.dict(os.environ,{'MONO_ENV_OPTIONS':'--bad','MONO_GAC_PREFIX':'/wrong','DYLD_INSERT_LIBRARIES':'/wrong'}):instance=self.oracle()
        with patch.object(api.subprocess,'run',side_effect=self.success) as run:
            compiled=instance.compile();native=instance.run()
            self.assertEqual((compiled.returncode,native.stdout),(0,'actual fixture output'))
            self.assertEqual((instance.work/'NativeFirmwareProbe.cs').read_bytes(),api.Path(api.__file__).with_name('NativeFirmwareProbe.cs').read_bytes())
            self.assertEqual((instance.work/'NativeFirmwareProbe.exe.config').read_bytes(),api.DLLMAP)
            self.assertIn(b'libSystem.B.dylib',api.DLLMAP)
            self.assertEqual(len(run.call_args_list),2)
            for call in run.call_args_list:
                self.assertNotIn('sh',call.args[0]);self.assertNotIn('docker',call.args[0])
                for name in ('MONO_ENV_OPTIONS','MONO_GAC_PREFIX','DYLD_INSERT_LIBRARIES'):self.assertNotIn(name,call.kwargs['env'])
            self.assertEqual(run.call_args_list[1].args[0][-1],str((self.app/'Firmware/eDLTFirmware/eDLTFirmware_1.7.0.zip').resolve()))
            self.assertTrue(instance.evidence['run_attempted']);self.assertFalse(instance.evidence['physical_hardware_accessed'])
            returned=instance.evidence;returned['runtime_hashes'].clear();self.assertTrue(instance.evidence['runtime_hashes'])
            with self.assertRaises(RuntimeError):instance.compile()
            with self.assertRaises(RuntimeError):instance.run()
        work=instance.work;instance.close();self.assertFalse(work.exists())

    def test_nonzero_compile_and_runtime_failures_never_retry(self):
        with patch.object(api.subprocess,'run',return_value=subprocess.CompletedProcess([],3,'compile partial','compile error')) as run:
            instance=self.oracle();result=instance.compile();self.assertEqual((result.returncode,result.stderr),(3,'compile error'))
            with self.assertRaises(RuntimeError):instance.run()
            self.assertEqual(run.call_count,1)
        instance=self.oracle()
        with patch.object(api.subprocess,'run',side_effect=self.success):instance.compile()
        with patch.object(api.subprocess,'run',return_value=subprocess.CompletedProcess([],5,'partial','native error')) as run:
            result=instance.run();self.assertEqual((result.returncode,result.stdout,result.stderr),(5,'partial','native error'))
            with self.assertRaises(RuntimeError):instance.run()
            self.assertEqual(run.call_count,1)

    def test_changed_owned_executable_or_binding_stops_before_execution(self):
        for filename in ('NativeFirmwareProbe.exe','NativeFirmwareProbe.exe.config','NativeFirmwareProbe.cs'):
            instance=self.oracle()
            with patch.object(api.subprocess,'run',side_effect=self.success):instance.compile()
            (instance.work/filename).write_bytes(b'changed')
            with patch.object(api.subprocess,'run',side_effect=AssertionError('no process')),self.assertRaises(ValueError):instance.run()

    def test_interruption_closes_owned_directory_and_prevents_retry(self):
        instance=self.oracle();interrupt=KeyboardInterrupt('injected original interrupt')
        with patch.object(api.subprocess,'run',side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt) as caught:
                with instance:instance.compile()
            self.assertIs(caught.exception,interrupt)
        self.assertFalse(instance.work.exists())
        with self.assertRaises(RuntimeError):instance.compile()


if __name__=='__main__':unittest.main()
