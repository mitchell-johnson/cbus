"""Original full model lifecycle, explicit cache facts and native persistence."""
from dataclasses import replace
import json
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from uuid import uuid4

from cbus_toolkit.edlt import EdltError, EdltApplyError, _numbers
from cbus_toolkit.edlt_lifecycle import EdltLifecycle, LifecycleCache, LifecycleMetadataError, FORMAT
from cbus_toolkit.unitspec import ParameterSpec, UnitSpec, UnitSpecStore
from tests.test_edlt import fixture as common_fixture, Session

ROOT=Path(__file__).resolve().parents[1]
IMAGE='sha256:23a8bfba16d732eff819f71edeec551e84e576eab40a15ec9e97018f649fb568'


def fixture():
    source=common_fixture();parameters=dict(source.parameters)
    parameters['InvertDisplay']=ParameterSpec('InvertDisplay','bit','synthetic.xml',{
        'Name':'InvertDisplay','Type':'bit','Address':'0x118','BitAddress':'3','BitSize':'1','DefaultValue':'1'})
    return UnitSpec(source.filename,source.metadata,source.sources,parameters)


def cache(editor,current,mode='complete'):
    applications=[56,57,127,136,172,202,203,255]
    if mode.startswith('missing-app'):applications.remove(int(mode[11:]))
    groups=[]
    for row in editor.requirements(current).as_dict()['groups']:
        application,number=row['application'],row['group']
        if application not in applications:continue
        present=number in (0,1,2,12,42,254,255) and not(mode=='missing-group0' and application==56 and number==0)
        record={'application':application,'group':number,'exists':present}
        if present:
            images=[] if number==255 else [mode=='image-present']*4
            if application==56 and number==42:
                if mode=='dynamic-null':images=None
                elif mode=='dynamic-empty':images=[]
                elif mode=='dynamic-short':images=images[:1]
            levels=[0,1,2,42,254,255]
            if application==202 and number==42 and mode in ('missing-level2','missing-level0-and2'):
                levels.remove(2)
                if mode=='missing-level0-and2':levels.remove(0)
            record.update(dynamic_images=images,levels=levels)
        groups.append(record)
    return {'format':FORMAT,'applications':applications,'groups':groups}


def scene_values(header=(2,0,42,2,26),items=(),**overrides):
    record=bytes(header)+bytes(value for item in items for value in item)
    return {'SceneCount':(0,),'Scene1StartAddress':(0,),'SceneBucket':tuple(record.ljust(232,b'\xff')),**overrides}


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.spec=fixture();self.editor=EdltLifecycle(self.spec);self.session=Session(self.spec)
        self.source=self.editor.snapshot(self.session.values())

    def plan(self,source=None,mode='complete'):
        source=self.source if source is None else source
        return self.editor.plan(source,metadata=cache(self.editor,source,mode))

    def test_full_load_default_phases_and_navigation_raw_preserved(self):
        source={**self.source,'PrimaryApplication':(255,)};plan=self.plan(source)
        self.assertEqual(plan.after_load['PrimaryApplication'],(56,));self.assertEqual(plan.after_load['InvertDisplay'],(0,))
        self.assertEqual(plan.after_load['ConfigVersionMajor'],(1,));self.assertEqual(plan.after_load['ConfigVersionMinor'],(0,))
        self.assertEqual([plan.after_load[f'Widget{i}WidgetType'] for i in range(1,22)],[(0,)]*21)
        self.assertEqual(plan.before_save['Widget6WidgetType'],(255,));self.assertEqual(plan.before_save['Widget7WidgetType'],(0,))
        self.assertEqual(plan.before_save['SceneCount'],(8,));self.assertEqual(plan.before_save['SceneBucket'][:40],tuple([2,0,255,255,255]*8))
        self.assertEqual(plan.before_save['SceneBucket'][40:],(255,)*192)
        self.assertEqual([plan.before_save[f'Scene{i}StartAddress'][0] for i in range(1,9)],list(range(0,40,5)))
        self.assertEqual(plan.before_save['NavWidgetType'],(255,));self.assertEqual(plan.before_save['Application'],(56,57))
        document=plan.as_dict();self.assertEqual(set(document['phases']),{'after_load','before_save','crc'})
        self.assertEqual(len(document['phases']['crc']),5);self.assertFalse(document['database_metadata_created'])
        self.assertFalse(document['cache_freshness_verified']);self.assertFalse(document['physical_device_verified'])

    def test_hidden_constructors_before_tail_clear_and_restore_type_change(self):
        source={**self.source,'Widget6WidgetType':(255,),'Widget7WidgetType':(2,),
            'Widget7WidgetByteValue1':(16,),'Widget7WidgetByteValue6':(42,),'Widget7RestoreLevel':(77,),
            'Widget8WidgetType':(14,),'Widget8WidgetByteValue9':(42,),'Widget8RestoreLevel':(88,),
            'Widget9WidgetType':(0,),'Widget9RestoreLevel':(99,),'Widget8WidgetByteValue31':(173,)}
        plan=self.plan(source,'image-present')
        self.assertEqual(plan.after_load['Widget7WidgetByteValue1'],(32,));self.assertEqual(plan.after_load['Widget7WidgetType'],(0,))
        self.assertEqual(tuple(plan.after_load[f'Widget8WidgetByteValue{i}'][0] for i in (7,8,9)),(10,23,255))
        self.assertEqual(plan.after_load['Widget8WidgetType'],(0,));self.assertEqual(plan.after_load['Widget8WidgetByteValue31'],(173,))
        self.assertEqual(tuple(plan.after_load[f'Widget{i}RestoreLevel'][0] for i in (7,8,9)),(0,0,99))
        facts=self.editor.requirements(source).as_dict()['groups'];self.assertTrue(any('hidden tails' in reason for row in facts for reason in row['facts']['exists']))

    def test_original_enable_macro_input_rule_and_forcing_reference(self):
        for previous,expected in (((0,0),255),((10,0),255),((23,0),42),((0,23),42),((24,24),42),((10,23),42)):
            source={**self.source,'Widget6WidgetType':(14,),'Widget6WidgetByteValue7':(previous[0],),
                'Widget6WidgetByteValue8':(previous[1],),'Widget6WidgetByteValue9':(42,)}
            plan=self.plan(source)
            self.assertEqual(tuple(plan.after_load[f'Widget6WidgetByteValue{i}'][0] for i in (7,8,9)),(10,23,expected))
        for kind in (4,16):
            for status in (0,5,6,7,10,15):
                source={**self.source,'Widget6WidgetType':(kind,),'Widget6WidgetByteValue1':(status,), 'Widget6WidgetByteValue10':(42,)}
                plan=self.plan(source);self.assertEqual(plan.before_save['Widget6WidgetByteValue1'],(5,))
                self.assertEqual(plan.before_save['Widget6WidgetByteValue10'],(42 if status==5 else 0,))
        for kind,offset in ((2,12),(5,9)):
            plan=self.plan({**self.source,'Widget6WidgetType':(kind,)})
            self.assertEqual(plan.after_load[f'Widget6WidgetByteValue{offset}'],(0,));self.assertEqual(plan.before_save[f'Widget6WidgetByteValue{offset}'],(1,))

    def test_original_mra_source_survivors_unknown_types_and_standby(self):
        source={**self.source,'Widget2WidgetType':(7,),'Widget2WidgetByteValue1':(0xed,),
            'Widget6WidgetType':(8,),'Widget6WidgetByteValue1':(0x12,), 'Widget7WidgetType':(255,),
            'Widget8WidgetType':(9,),'Widget8WidgetByteValue1':(0x53,), 'Widget8RestoreLevel':(77,)}
        plan=self.plan(source);self.assertEqual(plan.before_save['Widget6WidgetByteValue1'],(0xea,))
        self.assertEqual(plan.before_save['Widget8WidgetByteValue1'],(0x53,));self.assertEqual(plan.as_dict()['mra_source_widget'],2)
        for kind in (17,127,254):
            plan=self.plan({**self.source,'Widget6WidgetType':(kind,),'Widget6RestoreLevel':(173,)})
            self.assertEqual(plan.before_save['Widget6WidgetType'],(kind,));self.assertEqual(plan.before_save['Widget6RestoreLevel'],(173,))
            self.assertEqual(plan.before_save['Widget7WidgetType'],(255,))
        plan=self.plan({**self.source,'Widget6WidgetType':(1,),'Widget6RestoreLevel':(173,)})
        self.assertEqual(plan.after_load['Widget6WidgetType'],(0,));self.assertEqual(plan.after_load['Widget6RestoreLevel'],(0,))

    def test_secondary_fallback_in_original_order_and_fixed_apps(self):
        for kind in (2,3,4,5,6,14,15,16):
            source={**self.source,'SecondaryApplication':(255,),'Widget6WidgetType':(kind,),'Widget6WidgetByteValue1':(128,)}
            plan=self.plan(source);self.assertEqual(plan.after_load['Widget6WidgetByteValue1'],(128 if kind in (6,14) else 0,))
        source={**self.source,'SecondaryApplication':(255,),'Widget6WidgetType':(255,),'Widget7WidgetType':(3,), 'Widget7WidgetByteValue1':(128,)}
        self.assertEqual(self.plan(source).after_load['Widget7WidgetByteValue1'],(128,))

    def test_dynamic_image_null_absent_short_and_effective_index(self):
        source={**self.source,'Widget6WidgetType':(2,),'Widget6WidgetByteValue1':(32,),'Widget6WidgetByteValue6':(42,)}
        self.assertEqual(self.plan(source,'dynamic-null').after_load['Widget6WidgetByteValue1'],(32,))
        self.assertEqual(self.plan(source).after_load['Widget6WidgetByteValue1'],(16,))
        with self.assertRaisesRegex(LifecycleMetadataError,'indexes outside'):self.plan(source,'dynamic-empty')
        with self.assertRaisesRegex(LifecycleMetadataError,'indexes outside'):self.plan({**source,'Widget6WidgetByteValue13':(3,)},'dynamic-short')
        plan=self.plan({**source,'Widget6WidgetByteValue13':(5,)},'dynamic-short')
        self.assertEqual(plan.after_load['Widget6WidgetByteValue13'],(5,));self.assertEqual(plan.after_load['Widget6WidgetByteValue1'],(16,))
        plan=self.plan({**source,'Widget6WidgetByteValue6':(99,)})
        self.assertEqual(plan.after_load['Widget6WidgetByteValue1'],(32,));self.assertEqual(plan.after_load['Widget6WidgetByteValue6'],(99,))
        metadata=cache(self.editor,source);del next(g for g in metadata['groups'] if g['application']==56 and g['group']==42)['dynamic_images']
        with self.assertRaisesRegex(LifecycleMetadataError,'Unknown cached image'):self.editor.plan(source,metadata=metadata)

    def test_scene_masks_duplicate_pointers_missing_references_and_utf8_preservation(self):
        source={**self.source,**scene_values((0xfe,1,42,2,26),((0xf1,12,123),),Scene1StartAddress=(65535,),Scene2StartAddress=(0,),Scene3StartAddress=(0,))}
        source['StaticTextString0']=tuple(b'\xff\xfe\0'.ljust(64,b'\0'))
        plan=self.plan(source);self.assertEqual(plan.before_save['SceneBucket'][:21],tuple([2,0,255,255,255,2,1,42,2,26,17,12,123,2,1,42,2,26,17,12,123]))
        self.assertEqual(plan.before_save['StaticTextString0'],source['StaticTextString0']);self.assertEqual(plan.as_dict()['scene_item_count'],2)
        source={**self.source,**scene_values((2,0,99,2,26))};self.assertEqual(self.plan(source).before_save['SceneBucket'][:5],(2,0,255,255,26))
        source={**self.source,**scene_values()}
        self.assertEqual(self.plan(source,'missing-level2').before_save['SceneBucket'][:5],(2,0,42,0,26))
        self.assertEqual(self.plan(source,'missing-level0-and2').before_save['SceneBucket'][:5],(2,0,42,255,26))
        with self.assertRaises(LifecycleMetadataError) as caught:self.plan({**self.source,**scene_values((2,1,42,2,26),((0,99,123),))})
        self.assertEqual(caught.exception.as_dict()['original_stage'],'before_save')

    def test_scene_bounds_reject_original_zero_padding_quirk_and_repack_overflow(self):
        for pointer in (232,233,254):
            with self.assertRaisesRegex(EdltError,'outside'):self.plan({**self.source,'Scene1StartAddress':(pointer,)})
        with self.assertRaisesRegex(EdltError,'header is truncated'):self.plan({**self.source,'Scene1StartAddress':(231,)})
        with self.assertRaisesRegex(EdltError,'item data'):self.plan({**self.source,**scene_values((2,80,42,2,26))})
        source={**self.source,**scene_values((2,32,42,2,26),[(0,12,123)]*32), 'Scene2StartAddress':(0,), 'Scene3StartAddress':(0,)}
        with self.assertRaisesRegex(EdltError,'repacked'):self.plan(source)
        with self.assertRaises(EdltError):self.plan({**self.source,'SceneCount':(255,)})

    def test_metadata_strict_duplicates_unknown_vs_absent_and_schema(self):
        metadata=cache(self.editor,self.source)
        self.assertEqual(LifecycleCache.from_dict(metadata).as_dict(),metadata)
        bads=[{**metadata,'extra':1},{**metadata,'applications':[56,56]},{**metadata,'applications':[True]},
              {**metadata,'groups':metadata['groups']*2}]
        for edits in ({'exists':1},{'group':True},{'dynamic_images':[1]},{'levels':[0,0]},{'levels':[False]},
                      {'exists':False,'dynamic_images':None},{'levels':None}):
            bads.append({**metadata,'groups':[{**metadata['groups'][0],**edits}]})
        for bad in bads:
            with self.assertRaises(EdltError):LifecycleCache.from_dict(bad)
        with self.assertRaisesRegex(LifecycleMetadataError,'Unknown cached group'):self.editor.plan(self.source,metadata={**metadata,'groups':[]})
        with self.assertRaises(LifecycleMetadataError) as caught:self.plan(mode='missing-app203')
        self.assertEqual(caught.exception.original_stage,'after_load')
        parameters=dict(self.spec.parameters);parameters['InvertDisplay']=replace(parameters['InvertDisplay'],fields={**parameters['InvertDisplay'].fields,'BitAddress':'4'})
        with self.assertRaisesRegex(EdltError,'layout'):EdltLifecycle(replace(self.spec,parameters=parameters))

    def test_forged_and_stale_plans_identity_and_success(self):
        plan=self.plan()
        bad=replace(plan,after_load={**plan.after_load,'ConfigVersionMajor':(True,)})
        with self.assertRaises(EdltError):self.editor.apply(self.session,bad)
        with self.assertRaisesRegex(EdltError,'differs'):self.editor.apply(self.session,replace(plan,evidence='{}'))
        self.assertEqual(self.session.calls,[])
        self.session.current['InvertDisplay']='0'
        with self.assertRaisesRegex(EdltError,'changed since'):self.editor.apply(self.session,plan)
        self.session.current=dict(plan.expected);self.session.source='//HARDWARE/254/p/20'
        with self.assertRaisesRegex(EdltError,'database'):self.editor.apply(self.session,plan)
        self.session.source='/db//EDLTTEST/254/p/20';self.assertTrue(self.editor.apply(self.session,plan)['verified'])
        self.assertEqual(self.editor.snapshot(self.session.values()),{**plan.expected,**plan.changes})

    def test_rollback_disconnect_and_interruptions(self):
        plan=self.plan();self.session.failure=next(iter(plan.changes))
        with self.assertRaises(EdltApplyError) as caught:self.editor.apply(self.session,plan)
        self.assertTrue(caught.exception.as_dict()['rollback_verified']);self.assertEqual(self.editor.snapshot(self.session.values()),dict(plan.expected))
        for exception in (KeyboardInterrupt('owned interrupt'),SystemExit(4)):
            calls=[]
            def fail(name,value):calls.append(name);raise exception
            self.session.set=fail
            with self.assertRaises(type(exception)) as caught:self.editor.apply(self.session,plan)
            self.assertIs(caught.exception,exception);self.assertEqual(len(calls),1)
            self.assertEqual(exception.edlt_lifecycle_evidence['attempted_parameters'],calls)
        calls=[]
        def disconnect(name,value):calls.append(name);self.session.connected=False;raise OSError('connection lost')
        self.session.set=disconnect
        with self.assertRaises(EdltApplyError) as caught:self.editor.apply(self.session,plan)
        self.assertFalse(caught.exception.as_dict()['rollback_verified']);self.assertEqual(len(calls),1)

    def test_interrupted_rollback_preserves_primary_evidence(self):
        plan=self.plan();calls=[];interrupted=KeyboardInterrupt('rollback interrupt')
        def fail(name,value):
            calls.append(name)
            if len(calls)==1:raise RuntimeError('initial failure')
            raise interrupted
        self.session.set=fail
        with self.assertRaises(KeyboardInterrupt) as caught:self.editor.apply(self.session,plan)
        self.assertIs(caught.exception,interrupted);self.assertEqual(len(calls),2)
        self.assertEqual(interrupted.edlt_lifecycle_evidence['original_error']['error'],'initial failure')


    def test_original_failure_evidence_requires_pinned_stage_type_and_partial_state(self):
        text=('initial:Probe\t0x0\nfailure-stage:afterload\n'
              'failure:System.ArgumentOutOfRangeException: Index was out of range.\npartial:Probe\t0x0\n')
        good=subprocess.CompletedProcess([],1,text,'')
        self.assertEqual(verify_original_failure('dynamic-empty-0',good,parse_stages(text),1)['stage'],'afterload')
        bad=[subprocess.CompletedProcess([],0,text,''),subprocess.CompletedProcess([],1,text,'loader warning'),
             subprocess.CompletedProcess([],1,text.replace('afterload','setup'),''),
             subprocess.CompletedProcess([],1,text.replace('System.ArgumentOutOfRangeException','System.NullReferenceException'),''),
             subprocess.CompletedProcess([],1,text.replace('partial:Probe\t0x0\n',''),''),
             subprocess.CompletedProcess([],1,text+'complete:true\n','')]
        for observed in bad:
            with self.assertRaisesRegex(ValueError,'pinned stage/type'):
                verify_original_failure('dynamic-empty-0',observed,parse_stages(observed.stdout),1)


def literal_cases():
    cases=[]
    def add(label,values=None,mode='complete',negative=None):cases.append((label,values or {},mode,negative))
    add('defaults')
    for kind in (*range(18),127,254,255):add('kind-'+str(kind),{'Widget6WidgetType':(kind,),'Widget6RestoreLevel':(173,)})
    add('global-versions',{'PrimaryApplication':(255,),'InvertDisplay':(1,)})
    add('tail-constructors',{'Widget6WidgetType':(255,),'Widget7WidgetType':(2,),'Widget7WidgetByteValue1':(16,),
        'Widget7WidgetByteValue6':(42,),'Widget7RestoreLevel':(77,), 'Widget8WidgetType':(14,),
        'Widget8WidgetByteValue9':(42,),'Widget8RestoreLevel':(88,),'Widget9WidgetType':(0,),'Widget9RestoreLevel':(99,)},'image-present')
    add('standby-and-functional',{'Widget2WidgetType':(11,),'Widget3WidgetType':(13,),'Widget6WidgetType':(10,),
        'Widget6RestoreLevel':(173,),'Widget21WidgetType':(10,),'Widget21WidgetByteValue31':(173,)})
    add('mra-survivors',{'Widget2WidgetType':(7,),'Widget2WidgetByteValue1':(0xed,), 'Widget6WidgetType':(8,),
        'Widget6WidgetByteValue1':(0x12,), 'Widget7WidgetType':(255,), 'Widget8WidgetType':(9,),'Widget8WidgetByteValue1':(0x53,)})
    for kind in (2,3,4,5,6,14,15,16):add('disabled-secondary-'+str(kind),{'SecondaryApplication':(255,),'Widget6WidgetType':(kind,), 'Widget6WidgetByteValue1':(128,)})
    for application in (127,136):add('application-'+str(application),{'PrimaryApplication':(application,),'Widget6WidgetType':(2,)},'wide-applications')
    for mode in ('image-present','image-absent','dynamic-null','dynamic-empty','dynamic-short'):
        for index in (0,3,5):
            add(mode+'-'+str(index),{'Widget6WidgetType':(2,),'Widget6WidgetByteValue1':(32,),
                'Widget6WidgetByteValue6':(42,),'Widget6WidgetByteValue13':(index,)},mode,
                'original-failure' if mode=='dynamic-empty' or (mode=='dynamic-short' and index==3) else None)
    for kind in (4,16):
        for status in (0,5,6,7,10,15):add('status-'+str(kind)+'-'+str(status),{'Widget6WidgetType':(kind,),
            'Widget6WidgetByteValue1':(status,),'Widget6WidgetByteValue10':(42,)})
    add('scene-flags',scene_values((0xfe,1,42,2,26),((0xf1,12,123),)))
    add('scene-shared-pointer',scene_values((2,0,42,2,26),Scene1StartAddress=(65535,),Scene2StartAddress=(0,),Scene3StartAddress=(0,)))
    add('scene-secondary',scene_values((3,1,42,2,26),((0xf1,12,123),),SecondaryApplication=(255,)))
    add('scene-trigger-missing',scene_values((2,0,99,2,26)))
    add('scene-action-missing',scene_values(), 'missing-level2')
    add('scene-action-zero-missing',scene_values(), 'missing-level0-and2')
    add('scene-output-missing',scene_values((2,1,42,2,26),((0,99,123),)),negative='original-failure')
    add('scene-count255',{'SceneCount':(255,)},negative='bounded-source')
    add('scene-pointer254',{'Scene1StartAddress':(254,)},negative='bounded-source')
    add('utf8-and-navigation',{'StaticTextString0':tuple(b'\xff\xfe\0'.ljust(64,b'\0')),'NavWidgetType':(255,)})
    for application in (56,202,203):add('missing-app-'+str(application),{'Widget6WidgetType':(2,)},'missing-app'+str(application),'original-failure')
    return cases


def write_values(path, values):
    # Real PP GET supplies0x tokens. Original CRC code also parses each token
    # as hexadecimal; feeding decimal fixture overrides corrupts only the oracle.
    path.write_text(''.join(name+'\t'+(value if isinstance(value,str) else ' '.join(hex(n) for n in value))+'\n' for name,value in values.items()))


_WINDOWS_PROBES = {}
_WINDOWS_JOBS = []
_WINDOWS_PROOFS = {}
_WINDOWS_PROVENANCE = {}


def original_backend():
    value=os.environ.get('CBUS_EDLT_LIFECYCLE_ORIGINAL_BACKEND','docker')
    if value not in ('docker','windows'):
        raise ValueError('Lifecycle original backend must be docker or windows')
    return value


def original_evidence(folder):
    paths=[ROOT/'research/NativeEdltLifecycleProbe.cs',Path(__file__).resolve(),ROOT/'src/cbus_toolkit/edlt_lifecycle.py']
    evidence={'backend':original_backend(),'source_sha256':{str(path.relative_to(ROOT)):hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}}
    if original_backend()=='windows':
        key=str(folder.resolve());probe=_WINDOWS_PROBES[key]
        _WINDOWS_PROVENANCE[key].verify(probe.bridge)
        for name,path in _WINDOWS_PROOFS[key]['source_paths'].items():
            if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=_WINDOWS_PROOFS[key]['source_sha256'][name]:
                raise RuntimeError('Original acceptance source changed during execution: '+name)
        evidence.update(compiler='Windows .NET Framework v4.0.30319 csc /platform:x86',
            proof=_WINDOWS_PROOFS[key],vendor_manifest=probe.vendor_manifest,
            jobs=[row for row in _WINDOWS_JOBS if row['probe']==probe.prefix],physical_device_verified=False)
    else:evidence['image']=IMAGE
    return evidence


def original(folder, specs, mode='complete', extra=(), *, compile=False):
    app=Path(os.environ['CBUS_TOOLKIT_EXE']).resolve().parent
    if original_backend()=='windows':
        from research.windows_bridge import WindowsModelProbe, WindowsBridge
        from research.windows_provenance import resolve_windows_provenance
        key=str(folder.resolve())
        if compile:
            proof_dir=ROOT/'research/runtime/edlt-lifecycle'/('windows-'+uuid4().hex[:16])
            proof_dir.mkdir(parents=True,exist_ok=False)
            proof={'directory':str(proof_dir.relative_to(ROOT)),'source_sha256':{},'source_paths':{}}
            provenance=resolve_windows_provenance(ROOT,WindowsBridge())
            _WINDOWS_PROVENANCE[key]=provenance
            proof['owned_provenance']=provenance.as_dict()
            for name,path in [('probe.cs',folder/'NativeEdltLifecycleProbe.cs'),('test_edlt_lifecycle.py',Path(__file__).resolve()),
                              ('edlt_lifecycle.py',ROOT/'src/cbus_toolkit/edlt_lifecycle.py'),('windows_bridge.py',ROOT/'research/windows_bridge.py'),
                              ('KEYGL5.xml',specs/'KEYGL5.xml'),('edlt.py',ROOT/'src/cbus_toolkit/edlt.py'),
                              ('unitspec.py',ROOT/'src/cbus_toolkit/unitspec.py'),('programming.py',ROOT/'src/cbus_toolkit/programming.py'),
                              ('cgate.py',ROOT/'src/cbus_toolkit/cgate.py'),('native.py',ROOT/'src/cbus_toolkit/native.py'),
                              ('windows_provenance.py',ROOT/'research/windows_provenance.py'),
                              ('NativeWindowsBridge.cs',ROOT/'research/NativeWindowsBridge.cs'),
                              *provenance.paths.items()]:
                raw=path.read_bytes();(proof_dir/name).write_bytes(raw);proof['source_sha256'][name]=hashlib.sha256(raw).hexdigest()
                proof['source_paths'][name]=str((ROOT/'research/NativeEdltLifecycleProbe.cs' if name=='probe.cs' else path).resolve())
            runtime=provenance.paths['windows-runtime.json']
            raw=runtime.read_bytes();proof['runtime_sha256']=hashlib.sha256(raw).hexdigest()
            ready=provenance.paths['bridge-ready.json']
            raw=ready.read_bytes();(proof_dir/'bridge-ready.json').write_bytes(raw)
            proof['bridge_ready_sha256']=hashlib.sha256(raw).hexdigest()
            proof['bridge_protocol']=json.loads(raw)['format']
            if proof['bridge_protocol']!='cbus-windows-bridge-v2':
                raise RuntimeError('Lifecycle acceptance requires the admitted-job v2 bridge')
            class RecordingBridge(WindowsBridge):
                def run(self,script,**kwargs):
                    result=super().run(script,**kwargs)
                    jid=result['job_id']
                    raw=script.replace('\r\n','\n').replace('\n','\r\n').encode('utf-8') if isinstance(script,str) else script
                    (proof_dir/(jid+'.cmd')).write_bytes(raw)
                    (proof_dir/(jid+'.result.json')).write_text(json.dumps({k:v for k,v in result.items() if k not in ('stdout','stderr')},indent=2)+'\n')
                    for channel in ('stdout','stderr'):
                        if result[channel] is not None:(proof_dir/(jid+'.'+channel+'.txt')).write_bytes(result[channel])
                    return result
            probe=WindowsModelProbe(folder/'NativeEdltLifecycleProbe.cs',app,bridge=RecordingBridge())
            _WINDOWS_PROBES[key]=probe;_WINDOWS_PROOFS[key]=proof
            executable=probe.bridge.pull('vendor\\'+probe.prefix+'.exe');(proof_dir/'probe.exe').write_bytes(executable)
            proof['executable_sha256']=hashlib.sha256(executable).hexdigest();proof['prefix']=probe.prefix
            (proof_dir/'proof.json').write_text(json.dumps(proof,indent=2)+'\n')
            return subprocess.CompletedProcess(['Windows csc /platform:x86'],0,'','')
        original_evidence(folder)  # Check the source snapshot before another original execution.
        probe=_WINDOWS_PROBES[key]
        files={'KEYGL5.xml':(specs/'KEYGL5.xml').read_bytes(),'values.tsv':(folder/'values.tsv').read_bytes(),
               'overrides.tsv':(folder/'overrides.tsv').read_bytes()}
        result=probe.run_result(('KEYGL5.xml','values.tsv','overrides.tsv',mode,*extra),files=files)
        stdout=result['stdout'].decode('utf-8-sig');stderr=result['stderr'].decode('utf-8-sig')
        _WINDOWS_JOBS.append({'job_id':result['job_id'],'probe':probe.prefix,'exit_code':result['exit_code'],
            'mode':mode,'extra':list(extra),'inputs_sha256':{name:hashlib.sha256(raw).hexdigest() for name,raw in files.items()},
            'stdout_sha256':hashlib.sha256(result['stdout']).hexdigest(),'stderr_sha256':hashlib.sha256(result['stderr']).hexdigest()})
        proof_dir=ROOT/_WINDOWS_PROOFS[key]['directory']
        (proof_dir/'progress.json').write_text(json.dumps(original_evidence(folder),indent=2)+'\n')
        return subprocess.CompletedProcess([probe.prefix,mode,*extra],result['exit_code'],stdout,stderr)
    command=['mcs','-r:/input/CBusLogicModel.dll','-r:System.Drawing','-r:System.Xml.Linq','NativeEdltLifecycleProbe.cs'] if compile else [
        'mono','NativeEdltLifecycleProbe.exe','/spec/KEYGL5.xml','values.tsv','overrides.tsv',mode,*extra]
    result=subprocess.run(['docker','run','--rm','--network','none','-v',str(app)+':/input:ro',
        '-v',str(folder)+':/work','-v',str(specs)+':/spec:ro','-w','/work','-e','MONO_PATH=/input',IMAGE,*command],
        capture_output=True,text=True,timeout=60)
    return result


def parse_stages(output):
    stages={name:{} for name in ('initial','afterload','beforesave','crc','partial')}
    for line in output.splitlines():
        phase,_,tail=line.partition(':')
        if phase in stages and '\t' in tail:
            name,value=tail.split('\t',1);stages[phase][name]=value
    return stages


_ORIGINAL_FAILURES={
    **{name:('afterload','System.ArgumentOutOfRangeException',None) for name in
       ('dynamic-empty-0','dynamic-empty-3','dynamic-empty-5','dynamic-short-3')},
    **{name:('afterload','System.NullReferenceException',None) for name in
       ('missing-app-56','missing-app-202','missing-app-203')},
    'scene-output-missing':('beforesave','System.Reflection.TargetInvocationException','System.NullReferenceException'),
}


def verify_original_failure(label, observed, stages, parameter_count):
    # Pinned from original output, not from whichever error the Python model raises.
    stage,kind,inner=_ORIGINAL_FAILURES[label]
    lines=observed.stdout.splitlines()
    actual_stages=[line.partition(':')[2] for line in lines if line.startswith('failure-stage:')]
    failures=[line for line in lines if line.startswith('failure:')]
    wanted_counts={name:parameter_count if name in ('initial','partial') or (name=='afterload' and stage=='beforesave') else 0
                   for name in ('initial','afterload','beforesave','crc','partial')}
    if (observed.returncode!=1 or observed.stderr or actual_stages!=[stage] or len(failures)!=1
            or not failures[0].startswith('failure:'+kind+':')
            or (inner is not None and '---> '+inner+':' not in failures[0])
            or 'complete:true' in lines or {name:len(values) for name,values in stages.items()}!=wanted_counts):
        raise ValueError('Original failure differs from the pinned stage/type/partial evidence: '+label)
    return {'stage':stage,'type':kind,'inner_type':inner,'phase_parameter_counts':wanted_counts}


@unittest.skipUnless(all(os.environ.get(name) for name in ('CBUS_UNITSPEC_DIR','CBUS_TOOLKIT_EXE')),'Set original Toolkit/specs for unchanged lifecycle acceptance')
class OriginalLifecycleTests(unittest.TestCase):
    def test_full_original_stages_and_all_enable_input_pairs(self):
        specs=Path(os.environ['CBUS_UNITSPEC_DIR']).resolve();editor=EdltLifecycle(UnitSpecStore(specs).load('KEYGL5.xml'))
        baseline=editor.snapshot(editor.spec.defaults());records=[]
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);(folder/'NativeEdltLifecycleProbe.cs').write_bytes((ROOT/'research/NativeEdltLifecycleProbe.cs').read_bytes())
            compiled=original(folder,specs,compile=True);self.assertEqual(compiled.returncode,0,compiled.stderr)
            write_values(folder/'values.tsv',baseline);(folder/'overrides.tsv').write_text('')
            observed=original(folder,specs,extra=('enable-inputs',));self.assertEqual(observed.returncode,0,observed.stdout+observed.stderr)
            rows=[line.split(':')[1:] for line in observed.stdout.splitlines() if line.startswith('enable:')];self.assertEqual(len(rows),2048)
            for row in rows:
                left,right,after_left,after_right,preset,other=map(int,row)
                self.assertEqual((after_left,after_right,other),(10,23,43))
                self.assertEqual(preset,42 if left in (23,24) or right in (23,24) else 255)
            for label,overrides,mode,negative in literal_cases():
                source={**baseline,**overrides};write_values(folder/'values.tsv',source)
                observed=original(folder,specs,mode);complete='complete:true' in observed.stdout
                stages=parse_stages(observed.stdout)
                row={'case':label,'original_complete':complete,'negative_scope':negative,'exit_code':observed.returncode}
                if negative:
                    row.update(stdout=observed.stdout,stderr=observed.stderr,phase_parameter_counts={phase:len(values) for phase,values in stages.items()})
                if negative:
                    self.assertEqual(complete,negative=='bounded-source',label+observed.stdout[-500:])
                    if negative=='original-failure':row['expected_original_failure']=verify_original_failure(label,observed,stages,len(source))
                    else:self.assertEqual(observed.returncode,0,label+observed.stdout[-500:]+observed.stderr)
                    with self.assertRaises(EdltError):editor.plan(source,metadata=cache(editor,source,mode))
                else:
                    self.assertEqual(observed.returncode,0,label+observed.stdout[-1000:]+observed.stderr)
                    plan=editor.plan(source,metadata=cache(editor,source,mode))
                    for phase,expected in (('afterload',plan.after_load),('beforesave',plan.before_save),('crc',{**plan.expected,**plan.changes})):
                        actual=editor.snapshot(stages[phase])
                        differences={name:(actual[name],expected[name]) for name in actual if actual[name]!=expected[name]}
                        self.assertEqual(differences,{},label+' '+phase)
                    row['parameters_compared']=len(source)*3;row['crc_values_compared']=5
                records.append(row)
        output=Path(os.environ.get('CBUS_EDLT_LIFECYCLE_ORIGINAL_REPORT',ROOT/('research/runtime/edlt-lifecycle/original-windows-report.json' if original_backend()=='windows' else 'research/runtime/edlt-lifecycle/original-report.json')))
        output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps({'passed':True,'cases':records,
            'enable_constructor_pairs':2048,'physical_device_verified':False,'original_ui_binding_initialization':False,'original_evidence':original_evidence(folder)},indent=2)+'\n')


@unittest.skipUnless(all(os.environ.get(name) for name in ('CBUS_CGATE_TEST_HOST','CBUS_UNITSPEC_DIR','CBUS_TOOLKIT_EXE')),'Set native C-Gate, specs and original Toolkit for full lifecycle acceptance')
class NativeLifecycleTests(unittest.TestCase):
    def test_original_full_native_pp_crc_raw_save_and_reload(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeProjects,NativeDatabase
        from cbus_toolkit.programming import Programmer
        specs=Path(os.environ['CBUS_UNITSPEC_DIR']).resolve();editor=EdltLifecycle(UnitSpecStore(specs).load('KEYGL5.xml'))
        project='LF'+uuid4().hex[:6].upper();network='//'+project+'/254';source='/db'+network+'/p/20';records=[]
        selected={'defaults','kind-1','kind-2','kind-3','kind-4','kind-5','kind-6','kind-7','kind-8','kind-9','kind-10',
            'kind-11','kind-12','kind-13','kind-14','kind-15','kind-16','kind-17','kind-127','kind-254','global-versions',
            'tail-constructors','mra-survivors','image-present-0','image-absent-5','dynamic-null-3','scene-flags',
            'scene-shared-pointer','scene-trigger-missing','scene-action-missing','scene-action-zero-missing','utf8-and-navigation',
            'application-127','application-136'}
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);(folder/'NativeEdltLifecycleProbe.cs').write_bytes((ROOT/'research/NativeEdltLifecycleProbe.cs').read_bytes())
            compiled=original(folder,specs,compile=True);self.assertEqual(compiled.returncode,0,compiled.stderr);(folder/'overrides.tsv').write_text('')
            with CGateClient(os.environ['CBUS_CGATE_TEST_HOST'],int(os.environ.get('CBUS_CGATE_TEST_PORT','20023')),timeout=30) as client:
                projects,database=NativeProjects(client),NativeDatabase(client);projects.operation('new',project);projects.operation('save',project)
                try:
                    database.create_network(project,254,'Lifecycle_Fixture','Cni','127.0.0.1:1')
                    database.create_unit(network,20,'eDLT','KEYGL5','5.5.00',catalog_number='5055EDL')
                    with Programmer(client).load(network,source) as session:
                        session.reset_defaults();baseline=editor.snapshot(session.values())
                        for label,overrides,mode,negative in literal_cases():
                            if label not in selected:continue
                            desired={**baseline,**overrides};current=editor.snapshot(session.values())
                            for name,value in desired.items():
                                if value!=current[name]:session.set(name,value if isinstance(value,str) else ' '.join(map(str,value)))
                            before=editor.snapshot(session.values());plan=editor.plan(before,metadata=cache(editor,before,mode))
                            write_values(folder/'values.tsv',before);observed=original(folder,specs,mode)
                            self.assertEqual(observed.returncode,0,label+observed.stdout[-1000:]+observed.stderr)
                            actual=editor.snapshot(parse_stages(observed.stdout)['crc']);expected={**plan.expected,**plan.changes}
                            self.assertEqual({name:(actual[name],expected[name]) for name in actual if actual[name]!=expected[name]}, {}, label)
                            self.assertTrue(editor.apply(session,plan)['verified'])
                            raw=bytes.fromhex(session.get_raw_data(0x2c0,32).lines[-1].split('RawData=')[1])
                            want=bytes(expected['Widget6WidgetType']+tuple(expected[f'Widget6WidgetByteValue{i}'][0] for i in range(1,32)))
                            self.assertEqual(raw,want,label)
                            records.append({'case':label,'parameters_compared':len(expected),'crc_values_compared':5,'widget6_raw_hex':raw.hex()})
                        final=editor.snapshot(session.values());session.save_to_source()
                    for action in ('save','close','load'):projects.operation(action,project)
                    with Programmer(client).load(network,source) as session:self.assertEqual(editor.snapshot(session.values()),final)
                    self.assertTrue(any('state=new' in line for line in client.command('GET '+network+' state').lines))
                finally:projects.operation('close',project);projects.operation('delete',project)
        path=Path(os.environ.get('CBUS_EDLT_LIFECYCLE_REPORT',ROOT/('research/runtime/edlt-lifecycle/native-macos-windows-report.json' if original_backend()=='windows' else 'research/runtime/edlt-lifecycle/native-report.json')))
        path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps({'passed':True,'project':project,'cases':records,
            'saved_reloaded':True,'parameters_compared_on_reload':len(final),'network_state':'new','physical_device_verified':False,
            'native_host':os.environ['CBUS_CGATE_TEST_HOST'],'native_port':int(os.environ.get('CBUS_CGATE_TEST_PORT','20023')),'original_evidence':original_evidence(folder)},indent=2)+'\n')
