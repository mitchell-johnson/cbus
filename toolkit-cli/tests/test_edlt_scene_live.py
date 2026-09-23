"""Independent literal scene capture/broadcast, retained state and fault boundaries."""
from dataclasses import replace
import base64
import hashlib
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import uuid4

from cbus_toolkit.cgate import CGateError, CGateResponse
from cbus_toolkit.edlt import EdltError
from cbus_toolkit.edlt_scene_live import NativeEdltSceneLive, SceneLiveOutcome
from cbus_toolkit.edlt_scene_manager import EdltSceneManager, SceneCaptureLevel
from tests.test_edlt_scene_manager import cache, fixture, Session, op

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'research/fixtures/edlt-scene-live-vectors.json'

def vectors(): return json.loads(DATA.read_text())
def reply(line): return CGateResponse((line,), line, int(line[:3]))
def get(group, value): return reply(f'300 //OWNED/254/56/{group}: Level={value}')

class Client:
    connected = True
    def __init__(self, *replies): self.replies = list(replies); self.commands = []
    def command(self, text):
        self.commands.append(text)
        result = self.replies.pop(0)
        if isinstance(result, BaseException): raise result
        return result

class SceneLiveTests(unittest.TestCase):
    def setUp(self):
        self.spec = fixture(); self.manager = EdltSceneManager(self.spec); self.session = Session(self.spec)
        self.source = {**self.session.current, **{k:v for k,v in vectors()['input'].items() if k in self.spec.parameters}}
        self.session.current = dict(self.source)
        self.state = self.manager.load(self.source, metadata=cache())

    def live(self, client): return NativeEdltSceneLive(self.manager, client, network='//OWNED/254')

    def test_complete_capture_preserves_retained_references_and_original_full_pp(self):
        client = Client(get(12,37),get(42,203)); live = self.live(client)
        result = live.capture(self.state)
        self.assertTrue(result.complete); self.assertTrue(result.sequence_finished)
        self.assertEqual(client.commands, ['GET //OWNED/254/56/12 Level','GET //OWNED/254/56/42 Level'])
        self.assertEqual([i.level for i in result.state.scenes[0].items],[37,203])
        for before,after in zip(self.state.scenes[0].items,result.state.scenes[0].items):
            self.assertIs(before.group,after.group)
            self.assertEqual((before.item_id,before.ramp_rate,before.can_edit),(after.item_id,after.ramp_rate,after.can_edit))
        self.assertEqual(self.state.scenes[1:],result.state.scenes[1:])
        self.assertEqual([i.level for i in self.state.scenes[0].items],[10,200])
        plan=self.manager.prepare_save(result.state)
        expected=self.manager.snapshot({**self.source,**{k:v for k,v in vectors()['cases']['capture']['final'].items() if k in self.spec.parameters}})
        # Minimal specs still verify retained serialization; full native specs cover every CRC.
        self.assertEqual(plan.before_save['SceneBucket'],expected['SceneBucket'])
        self.assertTrue(self.manager.apply(self.session,plan)['verified'])
        self.assertEqual(live.last_evidence,result.as_dict())
        self.assertFalse(result.as_dict()['physical_device_verified'])

    def test_legacy_zero_rejections_and_normalization_never_become_verified_or_persistable(self):
        for value,level,status in [('not-a-number',0,'legacy-zero'),('2147483648',0,'legacy-zero'),('-1',0,'normalized'),('256',255,'normalized')]:
            with self.subTest(value=value):
                result=self.live(Client(get(12,37),get(42,value))).capture(self.state)
                self.assertFalse(result.complete);self.assertTrue(result.sequence_finished)
                self.assertEqual([i.level for i in result.state.scenes[0].items],[37,level])
                self.assertEqual(result.items[1].status,status)
                with self.assertRaisesRegex(EdltError,'incomplete'):self.manager.prepare_save(result.state)
        rejected=CGateError(reply('401 Owned rejection'))
        result=self.live(Client(rejected,get(42,203))).capture(self.state)
        self.assertEqual([i.level for i in result.state.scenes[0].items],[0,203]);self.assertFalse(result.complete)
        self.assertEqual(result.items[0].reply_code,401)

    def test_missing_malformed_wrong_address_and_transport_stop_on_exact_partial_prefix(self):
        for failure in [reply('300 //OWNED/254/56/42: Other=80'),get(12,203),reply('200 OK'),reply('600 Busy'),
                        CGateResponse(('300 //OWNED/254/56/42: Level=203',),'mismatch',300),TimeoutError('timed out')]:
            with self.subTest(failure=type(failure).__name__):
                client=Client(get(12,37),failure);result=self.live(client).capture(self.state)
                self.assertFalse(result.complete);self.assertFalse(result.sequence_finished)
                self.assertEqual([i.level for i in result.state.scenes[0].items],[37,200])
                self.assertEqual(len(client.commands),2)
                self.assertEqual(result.items[1].outcome_uncertain,isinstance(failure,TimeoutError))
                with self.assertRaisesRegex(EdltError,'incomplete'):self.manager.prepare_save(result.state)

    def test_broadcast_current_all_rejection_and_uncertain_stop_retain_cross_application_refs(self):
        state=self.manager.edit(self.state,operations=[op('set-application',selector=1),op('add-groups',groups=[12])]).state
        client=Client(CGateError(reply('401 Owned rejection')),reply('200 OK'),reply('200 OK'));live=self.live(client)
        preflight=live.validate_broadcast(state,scope='all');self.assertEqual(client.commands,[])
        self.assertEqual([r.command for r in preflight],['RAMP //OWNED/254/56/12 10 0 FORCE','RAMP //OWNED/254/56/42 200 0 FORCE','RAMP //OWNED/254/57/12 0 0 FORCE'])
        outcome=live.broadcast(state,scope='all');self.assertIs(outcome.state,state);self.assertFalse(outcome.complete)
        self.assertTrue(outcome.sequence_finished);self.assertEqual([r.status for r in outcome.items],['rejected','accepted','accepted'])
        self.assertEqual(client.commands,[r.command for r in preflight])
        client=Client(reply('200 OK'),OSError('lost ACK'),reply('200 OK'));live=self.live(client)
        outcome=live.broadcast(state,scope='all');self.assertFalse(outcome.sequence_finished);self.assertEqual(len(client.commands),2)
        self.assertTrue(outcome.items[-1].outcome_uncertain);self.assertIs(outcome.state,state)
        client=Client(reply('200 OK'));outcome=self.live(client).broadcast(state,item=2)
        self.assertTrue(outcome.complete);self.assertEqual(client.commands,['RAMP //OWNED/254/56/42 200 0 FORCE'])

    def test_preflight_invalid_arguments_disconnected_noops_and_reused_evidence_reset(self):
        client=Client();live=self.live(client)
        for kwargs in [{'scene':0},{'scene':True},{'scope':'future'},{'scope':'all','item':1},{'item':0},{'item':True},{'item':3}]:
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(EdltError):live.validate_broadcast(self.state,**kwargs)
        for network in ['OWNED/254','//OWNED/0254','//OWNED/256','//OWNED/254/56','//OWNED/254\nRAMP','//TOOLONG12/254']:
            with self.assertRaises(EdltError):NativeEdltSceneLive(self.manager,client,network=network)
        self.assertEqual(client.commands,[])
        client.connected=False
        self.assertEqual(len(live.validate_broadcast(self.state,scope='all')),2)
        failed=live.capture(self.state);self.assertEqual(len(failed.items),0);self.assertFalse(failed.complete)
        self.assertIsNotNone(live.last_evidence)
        with self.assertRaises(EdltError):live.broadcast(self.state,item=99)
        self.assertIsNone(live.last_evidence);self.assertIsNone(live.last_outcome);self.assertIsNone(live.last_error)
        for operation in ('capture','broadcast'):
            outcome=getattr(live,operation)(self.state,scene=3)
            self.assertTrue(outcome.complete);self.assertEqual(outcome.requested_count,0)
        self.assertEqual(client.commands,[])

    def test_actual_tagged_socket_split_replies_rejection_continuation_and_lost_reply(self):
        from cbus_toolkit.cgate import CGateClient
        from tests.test_cgate import peer
        with peer([[b'[1] 300 //OWNED/254/56/12: Lev',b'el=37\r\n'],
                   [b'[2] 300 //OWNED/254/56/42: Level=203\r\n']]) as (address,commands):
            with CGateClient(*address,timeout=1) as client:
                result=self.live(client).capture(self.state);self.assertTrue(result.complete)
            self.assertEqual(commands,[b'[1] GET //OWNED/254/56/12 Level\r\n',b'[2] GET //OWNED/254/56/42 Level\r\n'])
        with peer([[b'[1] 401 Owned rejection\r\n'],[b'[2] 200 OK\r\n']]) as (address,commands):
            with CGateClient(*address,timeout=1) as client:
                result=self.live(client).broadcast(self.state,scope='all')
                self.assertTrue(result.sequence_finished);self.assertFalse(result.complete);self.assertTrue(client.connected)
            self.assertEqual(commands,[b'[1] RAMP //OWNED/254/56/12 10 0 FORCE\r\n',b'[2] RAMP //OWNED/254/56/42 200 0 FORCE\r\n'])
        with peer([[b'[1] 200 OK\r\n'],[]]) as (address,commands):
            with CGateClient(*address,timeout=1) as client:
                live=self.live(client);result=live.broadcast(self.state,scope='all')
                self.assertFalse(result.sequence_finished);self.assertFalse(client.connected)
                self.assertIsInstance(live.last_error,RuntimeError)
                self.assertIn('before a complete reply',str(live.last_error))
                self.assertIs(live.last_error.edlt_scene_live_evidence,live.last_evidence)
                self.assertTrue(result.items[-1].outcome_uncertain)
            self.assertEqual(len(commands),2)

    def test_capture_transition_rejects_forgery_wrong_order_and_unverified_branch(self):
        ids=[i.item_id for i in self.state.scenes[0].items]
        for readings,finished in [([SceneCaptureLevel(ids[1],1,True)],False),([SceneCaptureLevel(ids[0],1,True)],True),([],1),([{'item_id':ids[0],'level':1,'verified':True}],False)]:
            with self.assertRaises(EdltError):self.manager.capture_levels(self.state,scene=1,readings=readings,finished=finished)
        other=EdltSceneManager(self.spec)
        with self.assertRaises(EdltError):other.live_items(self.state,scene=1)
        with self.assertRaises(EdltError):self.manager.live_items(replace(self.state,complete=False),scene=1)
        partial=self.manager.capture_levels(self.state,scene=1,readings=[SceneCaptureLevel(ids[0],37,False)],finished=False)
        with self.assertRaisesRegex(EdltError,'review-only'):self.manager.live_items(partial,scene=1)
        with self.assertRaisesRegex(EdltError,'incomplete'):self.manager.prepare_save(partial)
        full=self.manager.edit(self.state,operations=[op('set-level',item_id=ids[0],level=10)]*256).state
        client=Client()
        with self.assertRaisesRegex(EdltError,'256'):self.live(client).capture(full)
        self.assertEqual(client.commands,[])

    def test_first_state_or_evidence_failure_is_retained_after_completed_reads(self):
        class Refusing(KeyboardInterrupt):
            def __setattr__(self,key,value):raise SystemExit('secondary attachment')
        for point in ('state','evidence'):
            for failure in (OSError('state/output failed'),Refusing('first after reads')):
                with self.subTest(point=point,failure=type(failure).__name__):
                    client=Client(get(12,37),get(42,203));live=self.live(client)
                    original=self.manager.capture_levels
                    def issue(*args,**kwargs):
                        if kwargs['finished']:raise failure
                        return original(*args,**kwargs)
                    with patch.object(self.manager,'capture_levels',side_effect=issue) if point=='state' else patch.object(SceneLiveOutcome,'as_dict',side_effect=failure):
                        if point=='evidence' or isinstance(failure,KeyboardInterrupt):
                            with self.assertRaises(type(failure)) as caught:live.capture(self.state)
                            self.assertIs(caught.exception,failure)
                        else:
                            result=live.capture(self.state);self.assertFalse(result.complete);self.assertIsNone(result.state)
                    self.assertIs(live.last_error,failure);self.assertEqual(len(client.commands),2)
                    self.assertEqual(live.last_evidence['attempted_count'],2)
                    self.assertFalse(live.last_evidence['complete'])

    def test_interruption_preserves_first_object_even_evidence_attachment_and_export_fail(self):
        class Refusing(KeyboardInterrupt):
            def __setattr__(self,key,value):raise SystemExit('secondary attachment')
        for operation in ('capture','broadcast'):
            for export_error in (False,True):
                with self.subTest(operation=operation,export_error=export_error):
                    interrupted=Refusing('first');client=Client(get(12,37) if operation=='capture' else reply('200 OK'),interrupted)
                    live=self.live(client)
                    with patch.object(SceneLiveOutcome,'as_dict',side_effect=SystemExit('secondary export')) if export_error else patch.object(SceneLiveOutcome,'as_dict',SceneLiveOutcome.as_dict):
                        with self.assertRaises(Refusing) as caught:
                            if operation=='capture':live.capture(self.state)
                            else:live.broadcast(self.state,scope='all')
                    self.assertIs(caught.exception,interrupted);self.assertIs(live.last_error,interrupted);self.assertEqual(len(client.commands),2)
                    self.assertIsNotNone(live.last_evidence);self.assertFalse(live.last_evidence['complete'])
                    self.assertEqual(live.last_outcome.items[-1].status,'transport-error')
                    if operation=='capture':self.assertEqual([i.level for i in live.last_outcome.state.scenes[0].items],[37,200])

@unittest.skipUnless(all(os.environ.get(k) for k in ('CBUS_TOOLKIT_EXE','CBUS_UNITSPEC_DIR')), 'Set original Toolkit and exact specs')
class OriginalSceneLiveTests(unittest.TestCase):
    def test_original_capture_broadcast_callback_completion_and_full_pp_literals(self):
        from research.original_oracle import OriginalModelOracle
        source=ROOT/'research/NativeEdltSceneLiveProbe.cs';data=vectors();records=[]
        spec=Path(os.environ['CBUS_UNITSPEC_DIR'])/'KEYGL5.xml'
        values=''.join(k+'\t'+v+'\n' for k,v in data['input'].items()).encode()
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),data['source_probe_sha256'])
        with OriginalModelOracle(source,Path(os.environ['CBUS_TOOLKIT_EXE']).parent,references=('eDLT.dll','SharpCGateCommunicator.dll'),gui=True,docker_image='sha256:23a8bfba16d732eff819f71edeec551e84e576eab40a15ec9e97018f649fb568') as oracle:
            for name,expected in data['cases'].items():
                result=oracle.run_result(('KEYGL5.xml','values.tsv',name),files={'KEYGL5.xml':spec.read_bytes(),'values.tsv':values})
                self.assertEqual(result.returncode,0,result.stdout[-4000:]+result.stderr)
                self.assertIn('complete:true:',result.stdout);self.assertIn('manager-disposed:true',result.stdout)
                self.assertIn('peer-disposed:true',result.stdout);self.assertIn('eof=True',result.stdout)
                phases={};wire=[]
                for line in result.stdout.splitlines():
                    if line.startswith('pp\t'):
                        _,stage,field,value,_=line.split('\t');phases.setdefault(stage,{})[field]=base64.b64decode(value).decode()
                    if line.startswith('wire-tx-hex:'):wire.append(bytes.fromhex(line.split(':',1)[1]).decode())
                self.assertTrue(all(len(p)==874 for p in phases.values()))
                self.assertEqual(phases['after-original-crc'],expected['final'],name)
                self.assertEqual(wire,expected['wire'],name)
                if name.startswith('broadcast'):
                    callbacks=[line for line in result.stdout.splitlines() if line.startswith('async\tafter-original-callback\t')]
                    self.assertEqual(len(callbacks),len(wire)-1)
                    self.assertTrue(all('|status=Succ|' in row or '|status=Failed|' in row for row in callbacks))
                records.append({'case':name,'full_parameters':874,'wire':wire,'stdout_sha256':hashlib.sha256(result.stdout.encode()).hexdigest(),'process_evidence':result.process_evidence})
        output=Path(os.environ.get('CBUS_EDLT_SCENE_LIVE_ORIGINAL_REPORT',ROOT/'research/runtime/edlt-scene-live/original-test-report.json'))
        output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps({'passed':True,'cases':records,'physical_device_verified':False},indent=2)+'\n')

@unittest.skipUnless(all(os.environ.get(k) for k in ('CBUS_UNITSPEC_DIR','CBUS_CGATE_TEST_HOST')), 'Set native C-Gate and exact specs')
class NativeSceneLiveTests(unittest.TestCase):
    def test_capture_then_full874_raw_five_crc_save_reload_and_broadcast_receiver(self):
        import tempfile,time
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.simulator import PCISimulator
        from cbus_toolkit.native import NativeDatabase,NativeProjects
        from cbus_toolkit.programming import Programmer,xml_text
        from cbus_toolkit.unitspec import UnitSpecStore
        from xml.etree import ElementTree as ET
        spec=UnitSpecStore(os.environ['CBUS_UNITSPEC_DIR']).load('KEYGL5.xml');manager=EdltSceneManager(spec)
        source_values=manager.snapshot(vectors()['input']);project='LV'+uuid4().hex[:6].upper()
        network='//'+project+'/254';dbnetwork='//'+project+'/253';source='/db'+dbnetwork+'/p/20'
        def eventually(condition,label):
            deadline=time.monotonic()+10
            while not condition():
                self.assertLess(time.monotonic(),deadline,label);time.sleep(.02)
        def metadata(response):
            root=ET.fromstring(xml_text(response))
            for parent in root.iter():
                for child in list(parent):
                    if child.tag=='PP':parent.remove(child)
            return ET.tostring(root,encoding='unicode')
        with tempfile.TemporaryDirectory(prefix='cbus-scene-live-') as folder:
            path=Path(folder)/'receiver.json';groups={k:0 for k in PCISimulator(profile='synthetic').lighting.groups}
            groups.update({(56,42):0,(57,12):55});sim=PCISimulator(profile='synthetic',state_path=path,response_delay=.01,lighting_groups=groups)
            with sim.running(os.environ.get('CBUS_CGATE_SIMULATOR_BIND','0.0.0.0'),0) as (_,port), CGateClient(os.environ['CBUS_CGATE_TEST_HOST'],int(os.environ.get('CBUS_CGATE_TEST_PORT','20023')),timeout=30) as client:
                projects,database=NativeProjects(client),NativeDatabase(client);projects.operation('new',project);projects.operation('save',project);opened=False
                try:
                    projects.operation('use',project)
                    client.command(f'DBCREATENET 254 SceneLive Cni {os.environ.get("CBUS_CGATE_SIMULATOR_HOST","host.docker.internal")}:{port}')
                    for app in (56,57):client.command(f'DBADDSAFE {network} Application {app} OwnedApp{app}')
                    for app,group in ((56,12),(56,42),(57,12)):client.command(f'DBADDSAFE {network}/{app} Group {group} OwnedGroup{group}')
                    database.create_network(project,253,'SceneCaptureDatabase','Cni','127.0.0.1:1')
                    database.create_unit(dbnetwork,20,'eDLT','KEYGL5','5.5.00',catalog_number='5055EDL')
                    with Programmer(client).load(dbnetwork,source) as session:
                        for key,value in source_values.items():session.set(key,value if isinstance(value,str) else ' '.join(map(str,value)))
                        session.save_to_source()
                    for action in ('save','close','load'):projects.operation(action,project)
                    before_metadata=metadata(database.get(dbnetwork,xml=True))
                    client.command('NET LOAD DB '+project);client.command('NET OPEN '+network);opened=True
                    eventually(lambda:any('state=ok' in line for line in client.command('GET '+network+' state').lines),'healthy owned fixture')
                    for app,group,level in ((56,12,37),(56,42,203)):
                        client.command(f'RAMP {network}/{app}/{group} {level} 0 FORCE')
                        eventually(lambda:sim.lighting.level(app,group)==level,'seed receiver')
                        eventually(lambda:client.command(f'GET {network}/{app}/{group} Level').final.endswith('Level='+str(level)),'seed native cache')
                    with Programmer(client).load(dbnetwork,source) as session:
                        loaded=manager.load(session.values(),metadata=cache());live=NativeEdltSceneLive(manager,client,network=network)
                        captured=live.capture(loaded);self.assertTrue(captured.complete,captured.as_dict())
                        plan=manager.prepare_save(captured.state);expected={**plan.expected,**plan.changes}
                        literal=manager.snapshot(vectors()['cases']['capture']['final'])
                        self.assertEqual(len(expected),874);self.assertEqual(expected,literal)
                        self.assertTrue(manager.apply(session,plan)['verified'])
                        raw=bytes.fromhex(session.get_raw_data(0x2112,232).final.split('RawData=')[1]);self.assertEqual(raw,bytes(literal['SceneBucket']))
                        crcs=bytes.fromhex(session.get_raw_data(0x102,10).final.split('RawData=')[1])
                        self.assertEqual(crcs,bytes(sum((literal[k] for k in ('OverallCRC','GlobalParameterCRC','WidgetsCRC','StaticTextCRC','ScenesCheckSum')),())))
                        session.save_to_source()
                    state=manager.edit(loaded,operations=[op('set-application',selector=1),op('add-groups',groups=[12])]).state
                    before=len(sim.wire_log);broadcast=live.broadcast(state,scope='all');self.assertTrue(broadcast.complete,broadcast.as_dict())
                    for app,group,level in ((56,12,10),(56,42,200),(57,12,0)):
                        eventually(lambda:sim.lighting.level(app,group)==level,'independent broadcast receiver')
                    received=[bytes.fromhex(row['hex']) for row in sim.wire_log[before:] if row['direction']=='rx']
                    # PCI compression may omit a repeated header; each literal suffix is independent of the encoder.
                    expected_payloads=['020C0A','022AC8','020C00']
                    self.assertEqual(len(received),3)
                    self.assertEqual([row[:-2].decode().upper()[-6:] for row in received],expected_payloads)
                    self.assertTrue(received[2].decode().upper().startswith('\\053900'))
                    self.assertFalse([row for row in sim.wire_log if row.get('reason')])
                    self.assertEqual(PCISimulator(profile='synthetic',state_path=path).lighting.snapshot(),sim.lighting.snapshot())
                    client.command('NET CLOSE '+network);opened=False
                    for action in ('save','close','load'):projects.operation(action,project)
                    with Programmer(client).load(dbnetwork,source) as session:self.assertEqual(manager.snapshot(session.values()),expected)
                    self.assertEqual(metadata(database.get(dbnetwork,xml=True)),before_metadata)
                    record={'passed':True,'parameters':874,'capture':captured.as_dict(),'broadcast':broadcast.as_dict(),'raw_scene_sha256':hashlib.sha256(raw).hexdigest(),'original_five_crc_bytes':crcs.hex(),'wire_rx':[row.hex() for row in received],'saved_closed_reloaded':True,'metadata_unchanged':True,'receiver_persisted':True,'physical_device_verified':False}
                finally:
                    if opened:client.command('NET CLOSE '+network)
                    projects.operation('close',project);projects.operation('delete',project)
        output=Path(os.environ.get('CBUS_EDLT_SCENE_LIVE_NATIVE_REPORT',ROOT/'research/runtime/edlt-scene-live/native-test-report.json'))
        output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(record,indent=2)+'\n')
