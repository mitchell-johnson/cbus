"""Independent original bound control plus closed C-Gate /db persistence."""
import hashlib
import json
import os
from pathlib import Path
import sys
import unittest
from uuid import uuid4
from cbus_toolkit.cgate import CGateClient
from cbus_toolkit.edlt_blank import EdltBlankWidget
from cbus_toolkit.native import NativeDatabase,NativeProjects
from cbus_toolkit.programming import Programmer
from cbus_toolkit.unitspec import UnitSpecStore
from tests.test_edlt_lifecycle import cache
ROOT=Path(__file__).resolve().parents[1]
CASES=('family-0','family-1','family-2','family-6','family-7','family-12','family-14','family-127','family-255','standby-1','standby-5','single-fifth','multi-page-4-last')
def digest(raw):return hashlib.sha256(raw).hexdigest()
def tsv(values):return ''.join(k+'\t'+(v if isinstance(v,str) else ' '.join(hex(n) for n in v))+'\n' for k,v in values.items()).encode()
def phases(text):
    result={}
    for line in text.splitlines():
        if line.startswith('pp:'):
            key,value,_=line.split('\t');_,stage,name=key.split(':',2)
            if name in result.setdefault(stage,{}):raise ValueError('Duplicate original parameter')
            result[stage][name]=value
    return result

@unittest.skipUnless(os.environ.get('CBUS_WINDOWS_BRIDGE')=='1' and all(os.environ.get(n) for n in ('CBUS_CGATE_TEST_HOST','CBUS_UNITSPEC_DIR','CBUS_TOOLKIT_EXE')),'Select original Windows bridge, native C-Gate and vendor spec')
class NativeBlankTests(unittest.TestCase):
    def test_original_full_native_pp_crc_record_and_save_reload(self):
        from research.windows_bridge import WindowsBridge,WindowsModelProbe
        from research.windows_provenance import resolve_windows_provenance
        spec_dir=Path(os.environ['CBUS_UNITSPEC_DIR']).resolve();app=Path(os.environ['CBUS_TOOLKIT_EXE']).resolve().parent
        editor=EdltBlankWidget(UnitSpecStore(spec_dir).load('KEYGL5.xml'))
        vector_path=ROOT/'research/fixtures/edlt-blank-windows-vectors.json';vectors=json.loads(vector_path.read_text());available={r['name']:r for r in vectors['cases']}
        names=tuple(os.environ.get('CBUS_EDLT_BLANK_NATIVE_CASES',','.join(CASES)).split(','))
        self.assertTrue(names and len(set(names))==len(names) and set(names)<=set(CASES))
        proof=ROOT/'research/runtime/edlt-blank'/('native-'+uuid4().hex[:16]);proof.mkdir(parents=True,exist_ok=False)
        report_path=Path(os.environ.get('CBUS_EDLT_BLANK_NATIVE_REPORT',str(proof/'report.json')));report_path.parent.mkdir(parents=True,exist_ok=True)
        document={'passed':False,'complete_scope':names==CASES,'cases':[],'jobs':[],'cleanup_errors':[],'python':sys.version,'proof_directory':str(proof),'source_sha256':{},'source_paths':{},'physical_device_verified':False,'full_form_initialization_verified':False}
        provenance=resolve_windows_provenance(ROOT,WindowsBridge());document['owned_provenance']=provenance.as_dict()
        paths={'probe.cs':ROOT/'research/NativeEdltBlankProbe.cs','native_test.py':Path(__file__),'KEYGL5.xml':spec_dir/'KEYGL5.xml','vectors.json':vector_path,**provenance.paths}
        for name in ('edlt_blank','edlt_lifecycle','edlt','unitspec','memory','programming','native','cgate','cli','edlt_control_cli'):paths[name+'.py']=ROOT/'src/cbus_toolkit'/(name+'.py')
        for name in ('test_edlt_blank','test_edlt_blank_vectors','test_cli_edlt_blank','test_edlt_lifecycle','test_edlt'):paths[name+'.py']=ROOT/'tests'/(name+'.py')
        for name in ('windows_bridge','windows_provenance'):paths[name+'.py']=ROOT/'research'/(name+'.py')
        for name,path in paths.items():
            raw=path.read_bytes();(proof/name).write_bytes(raw);document['source_sha256'][name]=digest(raw);document['source_paths'][name]=str(path)
        def save():
            data=json.dumps(document,indent=2)+'\n';report_path.write_text(data);(proof/'progress.json').write_text(data)
        def stable():
            provenance.verify(WindowsBridge())
            for name,path in paths.items():self.assertEqual(digest(path.read_bytes()),document['source_sha256'][name],'Input changed: '+name)
        class RecordingBridge(WindowsBridge):
            def run(bridge,*args,**kwargs):
                result=super().run(*args,**kwargs);job={k:v for k,v in result.items() if k not in ('stdout','stderr')}
                for channel in ('stdout','stderr'):
                    raw=result[channel];(proof/(result['job_id']+'.'+channel)).write_bytes(raw);job[channel+'_sha256']=digest(raw)
                document['jobs'].append(job);save();return result
        save();stable();probe=WindowsModelProbe(paths['probe.cs'],app,bridge=RecordingBridge())
        executable=probe.bridge.pull('vendor\\'+probe.prefix+'.exe');(proof/'probe.exe').write_bytes(executable);document.update(vendor_manifest=probe.vendor_manifest,executable_sha256=digest(executable));save()
        project='BK'+uuid4().hex[:6].upper();network='//'+project+'/254';source='/db'+network+'/p/20';document.update(project=project,source=source)
        with CGateClient(os.environ['CBUS_CGATE_TEST_HOST'],int(os.environ.get('CBUS_CGATE_TEST_PORT','20023')),timeout=30) as client:
            projects,database=NativeProjects(client),NativeDatabase(client);projects.operation('new',project)
            try:
                projects.operation('save',project);database.create_network(project,254,'Blank_Fixture','Cni','127.0.0.1:1');database.create_unit(network,20,'eDLT','KEYGL5','5.5.00',catalog_number='5055EDL')
                with Programmer(client).load(network,source) as session:session.reset_defaults();baseline=editor.snapshot(session.values())
                for name in names:
                    stable();row=available[name];record={'case':name,'passed':False};document['cases'].append(record);save()
                    # Preserve native database identity while reproducing each independent original control input.
                    captured=editor.snapshot({**vectors['baseline'],**row['source_changes']})
                    desired={**captured,**{k:baseline[k] for k in ('UnitAddress','Project','NetworkAddress','UnitName','SerialNumber')}}
                    with Programmer(client).load(network,source) as session:
                        current=editor.snapshot(session.values())
                        for key,value in desired.items():
                            if current[key]!=value:session.set(key,value if isinstance(value,str) else ' '.join(map(str,value)))
                        before=editor.snapshot(session.values());files={'KEYGL5.xml':paths['KEYGL5.xml'].read_bytes(),'values.tsv':tsv(before),'overrides.tsv':b''}
                        for filename,raw in files.items():
                            if filename!='KEYGL5.xml':(proof/(name+'-'+filename)).write_bytes(raw)
                        record['input_sha256']={k:digest(v) for k,v in files.items()};save()
                        result=probe.run_result(('KEYGL5.xml','values.tsv','overrides.tsv','blank',str(row['slot'])),files=files);record['job_id']=result['job_id'];save()
                        output=result['stdout'].decode('utf-8-sig');self.assertEqual(result['exit_code'],0,output[-1800:]);self.assertEqual(result['stderr'],b'');self.assertIn('complete:true:physical=false:native-database=false:full-form=false',output)
                        original=phases(output);plan=editor.plan(before,metadata=cache(editor,before),page=row['page'],position=row['position']);final={**plan.expected,**plan.changes}
                        for stage,wanted in (('after-load',plan.after_load),('after-bind',plan.after_load),('after-select',plan.after_controls),('before-save',plan.before_save),('final',final)):
                            actual=editor.snapshot(original[stage]);self.assertEqual(len(actual),874);self.assertEqual(actual,dict(wanted),(name,stage))
                        self.assertTrue(editor.apply(session,plan)['verified']);self.assertEqual(editor.snapshot(session.values()),final)
                        record_address=editor.codec.layout('Widget'+str(row['slot'])+'WidgetType').address
                        wanted=bytes(final['Widget'+str(row['slot'])+('WidgetType' if i==0 else 'WidgetByteValue'+str(i))][0] for i in range(32))
                        raw=bytes.fromhex(session.get_raw_data(record_address,32).lines[-1].split('RawData=')[1]);self.assertEqual(raw,wanted)
                        session.save_to_source()
                    for action in ('save','close','load'):projects.operation(action,project)
                    with Programmer(client).load(network,source) as session:
                        self.assertEqual(editor.snapshot(session.values()),final)
                        self.assertEqual(bytes.fromhex(session.get_raw_data(record_address,32).lines[-1].split('RawData=')[1]),wanted)
                    self.assertTrue(any('state=new' in line for line in client.command('GET '+network+' state').lines))
                    record.update(passed=True,original_parameter_comparisons=874*5,native_parameter_comparisons=874,reload_parameter_comparisons=874,crc_values_compared=5,raw_widget_hex=raw.hex(),saved_reloaded=True,network_state='new');stable();save()
            except BaseException as error:document['failure_type']=type(error).__name__;save();raise
            finally:
                first=sys.exc_info()[1];cleanup=None
                for action in ('close','delete'):
                    if not client.connected:document['cleanup_errors'].append({'action':action,'reason':'connection_lost'});break
                    try:projects.operation(action,project)
                    except BaseException as error:
                        document['cleanup_errors'].append({'action':action,'type':type(error).__name__});cleanup=cleanup or error
                save()
                if first is None and cleanup is not None:raise cleanup
        stable();document['source_after']={k:digest(p.read_bytes()) for k,p in paths.items()};document['passed']=len(document['cases'])==len(names) and all(r['passed'] for r in document['cases']) and not document['cleanup_errors'];save();self.assertTrue(document['passed'])
