"""Multi Level CLI with literal original DLL vectors and native persistence."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from uuid import uuid4


class EdltMultiLevelCLITests(unittest.TestCase):
    def cli(self,*args,status=0):
        result=subprocess.run([sys.executable,'-m','cbus_toolkit',*map(str,args)],capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,status,result.stdout+result.stderr)
        return json.loads(result.stdout or result.stderr)

    def test_wrong_profile_rejects_offline_plan(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'wrong.json'
            path.write_text(json.dumps({'format':'cbus-cli-parameters-v1','unit_type':'KEYGL5',
                'catalog_number':'5055EDL','firmware':'5.4.00','parameters':{}}))
            result=self.cli('edlt','multilevel-plan',path,'--page',1,'--position',1,'--group',42,status=1)
            self.assertIn('identity differs',result['error'])

    @unittest.skipUnless(os.environ.get('CBUS_CGATE_TEST_HOST') and os.environ.get('CBUS_UNITSPEC_DIR'),
                         'Set native C-Gate and unit specifications for Multi Level CLI acceptance')
    def test_default_custom_levels_applications_preview_and_save_reload(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase,NativeProjects
        project='MC'+uuid4().hex[:6].upper(); network='//'+project+'/254'
        host,port=os.environ['CBUS_CGATE_TEST_HOST'],int(os.environ.get('CBUS_CGATE_TEST_PORT','20023'))
        args=('cgate','--host',host,'--port',port,'--timeout',20,'unit','--lock-address',network,
              '--source','/db'+network+'/p/20')
        location=('--page',1,'--position',1,'--group',42)
        custom=(*location,'--application','secondary','--levels',3,'--low-threshold',253,'--high-threshold',254,
                '--label-text','Ceiling','--off-text','Stopped','--low-text','Slow','--medium-text','Normal','--high-text','Fast')
        with tempfile.TemporaryDirectory() as folder, CGateClient(host,port,timeout=30) as client:
            projects,database=NativeProjects(client),NativeDatabase(client)
            projects.operation('new',project)
            try:
                database.create_network(project,254,'MultiLevel_CLI','Cni','127.0.0.1:29999')
                database.create_unit(network,20,'eDLT','KEYGL5','5.5.00',catalog_number='5055EDL')
                self.cli(*args,'set','SecondaryApplication',57)
                original=self.cli(*args,'show'); snapshot=Path(folder)/'original.json'
                self.cli(*args,'export',snapshot)
                default=self.cli('edlt','multilevel-plan',snapshot,*location)
                self.assertEqual(default['record_hex'].upper(),
                    '1005868600002A54AAFF0C0D0E0F000000000000000000000000000000000000')
                self.assertEqual([row['index'] for row in default['default_allocations']],[12,13,14,15])
                self.assertTrue(all(row['reused'] for row in default['default_allocations']))
                self.assertIsNone(default['static_allocation'])
                plan=self.cli('edlt','multilevel-plan',snapshot,*custom)
                self.assertEqual(plan['record_hex'].upper(),
                    '10B5868600002AFDFE3F3E3D3C3B000000000000000000000000000000000000')
                preview=self.cli(*args,'--dry-run','edlt-multilevel',*custom)
                self.assertFalse(preview['saved']); self.assertTrue(preview['verified'])
                self.assertEqual(preview['changes'],plan['changes']); self.assertEqual(self.cli(*args,'show'),original)
                applied=self.cli(*args,'edlt-multilevel',*custom)
                self.assertTrue(applied['saved']); self.assertFalse(applied['physical_device_verified'])
                self.assertEqual(applied['parameters'],preview['parameters'])
                projects.operation('save',project); projects.operation('close',project); projects.operation('load',project)
                self.assertEqual(self.cli(*args,'show'),applied['parameters'])
                for levels,thresholds in ((1,b'\0\0'),(2,b'\x7f\x7f'),(3,b'\x54\xaa')):
                    value=self.cli(*args,'edlt-multilevel',*location,'--application','secondary','--levels',levels)
                    self.assertEqual(bytes.fromhex(value['record_hex'])[7:9],thresholds)
                    self.assertEqual(bytes.fromhex(value['record_hex'])[10:14],bytes((62,61,60,59)))
                for app in (96,127,136):
                    self.cli(*args,'set','SecondaryApplication',app)
                    value=self.cli(*args,'edlt-multilevel',*location,'--application','secondary')
                    self.assertEqual(value['application'],app)
                    self.assertEqual(self.cli(*args,'show'),value['parameters'])
                for invalid in (('--low-threshold',0),('--high-threshold',84),('--levels',1,'--medium-text','Hidden')):
                    self.assertIn('error',self.cli(*args,'edlt-multilevel',*location,*invalid,status=1))
                self.assertEqual(self.cli(*args,'show'),value['parameters'])
                result=self.cli(*args,'--destination',network+'/p/20','edlt-multilevel',*location,status=1)
                self.assertIn('database destinations only',result['error'])
                self.assertEqual(self.cli(*args,'show'),value['parameters'])
            finally:
                projects.operation('close',project); projects.operation('delete',project)


if __name__=='__main__':unittest.main()
