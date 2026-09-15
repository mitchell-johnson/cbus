import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('registry_run',HERE/'run.py')
driver=importlib.util.module_from_spec(spec);spec.loader.exec_module(driver)


def synthetic_capture():
    plan=json.loads((HERE/'input.json').read_text())
    rows=[{'stage':'original-pins'}, {'stage':'root-created','root':'HKEY_CURRENT_USER\\Software\\'+plan['root_name'],'disposition':1}]
    for case in plan['cases']:
        f=case['fixture']
        if f['value_kind'] is None:continue
        raw=(f['value']+'\0').encode('utf-16-le') if f['value_kind']=='REG_SZ' else f['value'].to_bytes(4,'little')
        rows.append({'stage':'fixture','subkey':f['subkey'],'entry':f['entry'],'type':1 if f['value_kind']=='REG_SZ' else 4,'bytes_hex':raw.hex().upper()})
    for case in plan['cases']:
        c=case['condition'];path=c['fileOrRegistryKeyPath']
        if path.startswith('HKCU\\'):path='HKEY_CURRENT_USER'+path[4:]
        rows.append({'stage':'provider-witness','id':case['id'],'path':path,'entry':'Test' if c['whatToCheck']==3 else c['registryEntryNameOrProductCode'],
                     'default_value':{'kind':'System.Int32','value':1} if c['whatToCheck']==3 else {'kind':'System.String','value':'23021957-xxx-yy-z-27331bfa-adf0-46be-8d44-18b1a831affe'},
                     'result':{k:case['expected_provider_witness'][k] for k in ('kind','value')},'original_call_intercepted':False})
        rows.append({'stage':'original-call-admitted','id':case['id']})
        expected=case['expected_original'];error=None
        if 'error_type' in expected:error={'type':expected['error_type'],'message':expected['message']}
        rows.append({'stage':'original-return','observation':{'id':case['id'],'result':expected.get('result'),'error':error}})
    rows += [{'stage':'assemblies-after'}, {'stage':'complete','passed':True,'original_rows':12,'root_created':True,'root_absence_verified':True,'handles_closed':True,'handle_close_failures':0,'failures':[],'first_error':None}]
    return plan,rows


class Guards(unittest.TestCase):
    def test_regular_bound_fifo_symlink(self):
        with tempfile.TemporaryDirectory(dir=HERE) as name:
            directory=Path(name);file=directory/'file';file.write_bytes(b'ab')
            self.assertEqual(driver.read(file,2),b'ab')
            with self.assertRaises(ValueError):driver.read(file,1)
            fifo=directory/'fifo';os.mkfifo(fifo)
            with self.assertRaises(ValueError):driver.read(fifo)
            link=directory/'link';link.symlink_to(file)
            with self.assertRaises(ValueError):driver.read(link)

    def test_read_first_interruption_across_close(self):
        first=KeyboardInterrupt('read');second=SystemExit('close');close=os.close
        def fail_close(fd):close(fd);raise second
        with patch.object(driver.os,'read',side_effect=first),patch.object(driver.os,'close',side_effect=fail_close):
            with self.assertRaises(KeyboardInterrupt) as captured:driver.read(HERE/'input.json')
        self.assertIs(captured.exception,first)

    def test_write_first_interruption_across_close(self):
        first=KeyboardInterrupt('write');second=SystemExit('close')
        class File:
            def write(self,data):raise first
            def close(self):raise second
        with patch.object(Path,'open',return_value=File()):
            with self.assertRaises(KeyboardInterrupt) as captured:driver.write(HERE/'unused',b'bytes')
        self.assertIs(captured.exception,first)

    def test_first_object_and_final_evidence_error(self):
        first=KeyboardInterrupt();second=SystemExit();failures=driver.Failures()
        failures.remember('original',first)
        def fail():raise second
        failures.attempt('report',fail)
        with self.assertRaises(KeyboardInterrupt) as captured:failures.raise_first()
        self.assertIs(captured.exception,first);self.assertEqual(len(failures.records),2)

    def test_release_before_source_or_guest_io(self):
        with patch.object(driver,'read',side_effect=AssertionError('no IO')):
            with self.assertRaises(ValueError):driver.main('not-authorized')

    def test_exact_literal_capture_and_failures(self):
        plan,rows=synthetic_capture();encode=lambda r:(''.join(json.dumps(x)+'\n' for x in r)).encode()
        self.assertEqual(driver.validate_capture(encode(rows),plan)['original_expected_errors'],2)
        for mutate in [lambda r:r[-1].update(root_absence_verified=False),lambda r:r[-1].update(handles_closed=False),
                       lambda r:r[1].update(disposition=2),lambda r:r[2].update(bytes_hex='00')]:
            changed=copy.deepcopy(rows);mutate(changed)
            with self.assertRaises(ValueError):driver.validate_capture(encode(changed),plan)

    def test_incomplete_or_duplicate_original_records(self):
        plan,rows=synthetic_capture();encoded=(''.join(json.dumps(x)+'\n' for x in rows)).encode()
        with self.assertRaises(ValueError):driver.validate_capture(encoded[:-1],plan)
        rows.insert(-2,next(r for r in rows if r['stage']=='original-return'))
        with self.assertRaises(ValueError):driver.validate_capture((''.join(json.dumps(x)+'\n' for x in rows)).encode(),plan)

    def test_exact_provider_default_identity(self):
        plan,rows=synthetic_capture()
        witness=next(r for r in rows if r['stage']=='provider-witness')
        witness['default_value']={'kind':'System.String','value':'1'}
        with self.assertRaises(ValueError):driver.validate_capture((''.join(json.dumps(x)+'\n' for x in rows)).encode(),plan)

    def test_original_assembly_method_and_scope_correlation(self):
        _,rows=synthetic_capture();contract=json.loads((HERE/'contract.json').read_text());binary='a'*64
        guest='C:\\CBusCliOracle118-88d8\\'+contract['prefix']+'-'
        rows[0].update(process_bits=32,culture='',input_sha256=contract['input_sha256'],sid=contract['user_sid'],
                       type_tokens=contract['type_tokens'],method_tokens={k:v['token'] for k,v in contract['method_pins'].items()},
                       methods={k:v['sha256'] for k,v in contract['method_pins'].items()},public_Evaluate_called=False,provider_remapping=False,
                       mscorlib=r'C:\Windows\Microsoft.NET\Framework\v4.0.30319\mscorlib.dll')
        assemblies=[]
        for name,path,digest in [('SE.DAD.SESU.Common',guest+'se.dad.sesu.common.dll',contract['vendor']['SE.DAD.SESU.Common']['sha256']),
                                 ('mscorlib',rows[0]['mscorlib'],contract['mscorlib_sha256']),
                                 (contract['prefix']+'-probe',guest+'probe.exe',binary)]:
            assemblies.append({'name':name+', Version=1.0.0.0','location':path,'sha256':digest,'mvid':'00000000-0000-0000-0000-000000000000'})
        rows[0]['assemblies']=assemblies;rows[-2]['assemblies']=copy.deepcopy(assemblies)
        rows[1]['sid']=contract['user_sid']
        rows[-1].update(provider_remapping=False,network_call_sites_in_whitelisted_original_graph=0,dynamic_network_instrumentation=False)
        driver.validate_original_provenance(rows,contract,binary)
        for mutate in [lambda r:r[0]['assemblies'][0].update(sha256='b'*64),
                       lambda r:r[-2]['assemblies'][0].update(mvid='10000000-0000-0000-0000-000000000000'),
                       lambda r:r[0]['assemblies'][0].update(location='C:\\unowned\\copy.dll'),
                       lambda r:r[0]['method_tokens'].update({'Condition::.cctor':0}),
                       lambda r:r[0].update(culture='en-US'),lambda r:r[-1].update(dynamic_network_instrumentation=True),
                       lambda r:r[-1].update(network_call_sites_in_whitelisted_original_graph=False)]:
            changed=copy.deepcopy(rows);mutate(changed)
            with self.assertRaises(ValueError):driver.validate_original_provenance(changed,contract,binary)


if __name__=='__main__':unittest.main()
