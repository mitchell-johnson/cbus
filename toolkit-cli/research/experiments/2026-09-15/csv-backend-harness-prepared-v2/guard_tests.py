"""Host-only guard tests. Never construct vendor objects, sockets or services."""
import copy,importlib.util,json,os,sys,tempfile,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
BASE=Path(__file__).resolve().parent

def module(name):
 p=BASE/(name+'.py');spec=importlib.util.spec_from_file_location('guard_'+name,p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
host=module('backend_support');native=module('run_native');probe=module('NativeCSVBackendProbe');replay=module('replay_native');launcher=module('run_original')

class Guards(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(prefix='guard-only-',dir=BASE);self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
 def test_case_schema_and_boolean_confusion(self):
  a=json.loads(host.read(BASE/'cases.json'));probe.validate(a)
  for change in (lambda c:c.__setitem__(0,None),lambda c:c[0].__setitem__('expected_completed',[1]),lambda c:c[0].__setitem__('action','execute-shell')):
   invalid=copy.deepcopy(a);change(invalid)
   with self.assertRaises(RuntimeError):probe.validate(invalid)
  b=json.loads(host.read(BASE/'native-cases.json'));native.validate(b);b[0]['area']=True
  with self.assertRaises(RuntimeError):native.validate(b)
 def test_fifo_symlink_and_read_growth(self):
  fifo=self.root/'fifo';os.mkfifo(fifo);start=time.monotonic()
  for read in (host.read,native.read,probe.read,launcher.read):
   with self.assertRaises(RuntimeError):read(fifo)
  self.assertLess(time.monotonic()-start,1)
  target=self.root/'real';target.write_bytes(b'a');link=self.root/'link';link.symlink_to(target)
  for read in (host.read,native.read,probe.read,launcher.read):
   with self.assertRaises(OSError):read(link)
   with patch.object(os,'read',side_effect=(b'ab',b'')):
    with self.assertRaises(RuntimeError):read(target,1)
 def test_read_interruption_identity_survives_close(self):
  source=self.root/'input';source.write_bytes(b'a')
  for read in (host.read,native.read,probe.read,launcher.read):
   first=KeyboardInterrupt('read');second=SystemExit('close');original=os.close
   def close(fd):original(fd);raise second
   with patch.object(os,'read',side_effect=first),patch.object(os,'close',side_effect=close):
    with self.assertRaises(KeyboardInterrupt) as caught:read(source)
   self.assertIs(caught.exception,first)
 def test_output_containment_before_write(self):
  outside=self.root/'other';outside.mkdir();link=self.root/'link';link.symlink_to(outside,target_is_directory=True)
  with self.assertRaises(RuntimeError):host.new_output(BASE,link/'capture',nested='capture')
  self.assertEqual(list(outside.iterdir()),[])
  with self.assertRaises(RuntimeError):host.existing_output(BASE,link/'report.json','report.json')
  host.new_output(BASE,self.root/'capture',nested='capture')
  with self.assertRaises(RuntimeError):host.new_output(BASE,self.root/'capture')
 def test_command_grammar_and_fixture_quoting(self):
  client=SimpleNamespace(command=lambda command:None,connected=True);g=native.Guard(client,'CSVBA01',12345,[],time.monotonic()+60)
  g.admit('PP SET CSVSESSION Application "56\\ 255"')
  self.assertEqual(native.quote('56 255'),'"56\\ 255"')
  for c in ('PP SET CSVSESSION Application "56 255"','NET OPEN //CSVBA01/254','PROJECT USE USER','REPOSITORY USE 2','pp quickget //CSVBA01/!foreign AreaGroupAddress','PP SET CSVSESSION GroupAddress "1"'):
   with self.assertRaises(RuntimeError):g.admit(c)
  g.phase='read'
  for c in ('PP END CSVSESSION','PROJECT SAVE CSVBA01','DBSETSAFE //CSVBA01/254/p/4/UnitName x'):
   with self.assertRaises(RuntimeError):g.admit(c)
  g.admit('pp quickget //CSVBA01/254/p/4 AreaGroupAddress')
 def test_command_first_interruption_latches_without_diagnostic_dispatch(self):
  class First(KeyboardInterrupt):
   @property
   def response(self):raise SystemExit('diagnostic')
   def __str__(self):raise SystemExit('format')
  first=First();calls=[]
  def command(value):calls.append(value);raise first
  g=native.Guard(SimpleNamespace(command=command),'CSVBA01',12345,[],time.monotonic()+60)
  for c in ('PP UNITS','PP END CSVSESSION'):
   with self.assertRaises(KeyboardInterrupt) as got:g.command(c)
   self.assertIs(got.exception,first)
  self.assertEqual(calls,['PP UNITS']);self.assertEqual(g.rows[0]['diagnostic_error']['type'],'SystemExit')
 def test_command_deadline_precedes_client(self):
  calls=[];g=native.Guard(SimpleNamespace(command=calls.append),'CSVBA01',12345,[],0)
  with self.assertRaises(RuntimeError):g.command('PP UNITS')
  self.assertEqual(calls,[])
 def test_response_continuation_duplicate_and_wrong_status(self):
  self.assertEqual(native.params(SimpleNamespace(code=315,lines=['315-A=12','315 B=13'])),{'A':'12','B':'13'})
  for code,lines in ((True,['315 A=12']),(315,[]),(315,['315 A=12','315 B=13']),(315,['315-A=12']),(315,['315-A=12','315 A=13']),(408,['408 missing'])):
   with self.assertRaises(RuntimeError):native.params(SimpleNamespace(code=code,lines=lines))
 def test_wire_overflow_preserves_received_prefix(self):
  tap=native.Tap(SimpleNamespace(recv=lambda n:b'abcd'),[]);tap.size=16*1024*1024-2
  with self.assertRaises(RuntimeError):tap.recv(4)
  self.assertEqual(tap.trace,[{'direction':'receive','hex':'6162','bytes':4,'truncated':True}])
 def test_report_primary_survives_secondary_fsync_close(self):
  first=KeyboardInterrupt('body');second=SystemExit('fsync');report={'passed':False};f=host.Failures(report);f.retain('body',first)
  with patch.object(os,'fsync',side_effect=second):host.finish(self.root,report,f)
  self.assertIs(f.first,first);self.assertFalse(report['passed']);self.assertEqual(report['secondary_errors'][0]['type'],'SystemExit')
  self.assertFalse((self.root/'report.json').exists());self.assertTrue((self.root/'report.pending.json').exists())
 def test_archive_exact_bytes_before_execution(self):
  inputs={self.root/'one':b'abc',self.root/'two':b'\x00\xff'};index=host.archive(self.root,inputs)
  self.assertEqual([r['sha256'] for r in index],[host.digest(x) for x in inputs.values()]);self.assertTrue((self.root/'inputs.tar.gz').exists())
 def test_original_requested_attempted_and_reached_are_distinct(self):
  self.assertEqual(probe.execution_evidence([]),{'original_invocations_attempted':0,'original_instruction_entries':0,'original_execution':False})
  attempted=SimpleNamespace(invoke_attempts=1,original_entries=0)
  self.assertFalse(probe.execution_evidence([attempted])['original_execution'])
  reached=SimpleNamespace(invoke_attempts=2,original_entries=100)
  self.assertEqual(probe.execution_evidence([attempted,reached]),{'original_invocations_attempted':3,'original_instruction_entries':100,'original_execution':True})
 def test_actual_loaded_wrapper_paths_and_hashes(self):
  first=self.root/'wrapper.py';second=self.root/'extra.py';first.write_text('VALUE=1\n');second.write_text('VALUE=2\n')
  supplied={name:SimpleNamespace(__file__=str(first)) for name in ('pefile','unicorn','capstone')}
  supplied['capstone.extra']=SimpleNamespace(__file__=str(second))
  with patch.dict(sys.modules,supplied):
   observed=probe.python_sources();self.assertEqual(observed['capstone.extra'],{'path':str(second),'sha256':host.digest(b'VALUE=2\n')})
   second.write_text('VALUE=3\n');self.assertNotEqual(probe.python_sources()['capstone.extra'],observed['capstone.extra'])

 def test_replay_uses_literal_native_scalars_and_area(self):
  from xml.etree import ElementTree as ET
  expected=json.loads(host.read(BASE/'native-cases.json'));rows=[]
  oid='12345678-1234-1234-1234-123456789012'
  for c in expected:
   root=ET.Element('Installation');project=ET.SubElement(root,'Project');network=ET.SubElement(project,'Network');unit=ET.SubElement(network,'Unit')
   for k,v in {'UnitName':'Native exact name','TagName':'Native exact tag','UnitType':c['unit_type'],'CatalogNumber':'CAT','SerialNumber':'1.2.3','FirmwareVersion':c['firmware'],'OID':oid,'Address':'4'}.items():ET.SubElement(unit,k).text=v
   app=ET.SubElement(network,'Application');ET.SubElement(app,'Address').text='56';ET.SubElement(app,'TagName').text='Native app'
   for address in c['groups']:
    group=ET.SubElement(app,'Group')
    for k,v in {'Address':str(address),'TagName':'Original '+str(address),'OID':'owned-group-'+str(address)}.items():ET.SubElement(group,k).text=v
   raw=ET.tostring(root,encoding='unicode');row={'case':c,'capture_complete':True,'xml_before':raw,'xml_after':raw,'oid':oid}
   if c['area'] is not None:
    value=hex(c['area']);row.update(reads=[{'target':'//'+c['project']+'/!'+oid,'parameter':'AreaGroupAddress','value':value,'lines':['315 AreaGroupAddress='+value]}],parameters_before={'AreaGroupAddress':value},parameters_after={'AreaGroupAddress':value})
   rows.append(row)
  report={'format':'csv-backend-native4-v1','passed':True,'native_capture_complete':True,'fixtures':rows}
  result=replay.project_cases(report,expected)
  self.assertEqual([r['expected_partial_save'] for r in result],[False,False,True,False]);self.assertEqual(result[0]['fields']['part_name'],'Native exact name')
  self.assertEqual(result[0]['responses'],['315 AreaGroupAddress=0xc']);self.assertEqual(result[3]['responses'],[])
  bad=copy.deepcopy(report);bad['fixtures'][0]['reads'][0].update(value='0xd',lines=['315 AreaGroupAddress=0xd'])
  with self.assertRaises(RuntimeError):replay.project_cases(bad,expected)
  bad=copy.deepcopy(report);bad['fixtures'][0]['reads'][0]['lines']=['315 OtherParameter=0xc']
  with self.assertRaises(RuntimeError):replay.project_cases(bad,expected)

 def test_json_duplicates_and_replay_rejects_partial_native(self):
  for raw in (b'{"x":1,"x":2}',b'{"x":NaN}'):
   with self.assertRaises((ValueError,RuntimeError)):host.strict_json(raw)
  with self.assertRaises(RuntimeError):replay.project_cases({'format':'csv-backend-native4-v1','passed':False},[])

if __name__=='__main__':unittest.main(verbosity=2)
