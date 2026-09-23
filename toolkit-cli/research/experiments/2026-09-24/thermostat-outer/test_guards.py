"""Host-only fixtures/admission tests; emulator start is forbidden here."""
from pathlib import Path
import copy,importlib.util,json,os,tempfile,unittest
from unittest.mock import patch
BASE=Path(__file__).resolve().parent
def load(name):
 p=BASE/(name+'.py');spec=importlib.util.spec_from_file_location('outer_guard_'+name,p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
probe=load('probe');driver=load('run');hyp=load('make_cases')
class Guards(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.m=probe.load_prior();cls.img=probe.image(cls.m);cls.cases=json.loads(probe.read(BASE/'cases.json',256*1024));probe.validate(cls.cases)
 def test_exact_frozen_hypotheses(self):
  self.assertEqual(self.cases,hyp.build());self.assertEqual(len(self.img.spans),31)
  for address in (0x113086a,0x1130894,0x11308dc,0x1130924,0x7de5e8,0x7ed530):self.assertEqual(self.img.instructions[address][1],b'\xc3')
 def test_counts_shared_roles_and_denied_prefixes(self):
  e=[c['expected'] for c in self.cases]
  self.assertEqual([r['storage_completed'] for r in e],[0,0,0,0,3,1,2,1,2,1,1,1])
  self.assertEqual(e[4]['level_completed'],186);self.assertEqual(e[5]['level_completed'],62)
  self.assertEqual((e[10]['lock'],e[10]['pending'],e[10]['delay_active']),(0,True,True))
  self.assertEqual((e[11]['level_attempts'],e[11]['level_completed'],e[11]['lock']),(65,64,1))
  self.assertEqual(e[11]['groups'][1]['levels'],[{'address':1,'value':1,'tag':'Sched Disable Zone:unsw'},{'address':2,'value':2,'tag':'Level 2'}])
 def test_schema_rejects_foreign_boolean_and_duplicate_inputs(self):
  for edit in (lambda c:c[0].update(enabled=1),lambda c:c[0]['roles'].update(on='FOREIGN'),lambda c:c[0]['groups'][0].update(address=True),lambda c:c[0]['groups'][1].update(identity='A'),lambda c:c[0].update(deny_level_save=True)):
   c=copy.deepcopy(self.cases);edit(c)
   with self.assertRaises(RuntimeError):probe.validate(c)
 def test_constructed_group_map_without_original_execution(self):
  m=self.m;Machine=probe.machine_type(m)
  with patch.object(m.unicorn.Uc,'emu_start',side_effect=AssertionError('No original execution permitted')) as start:
   machine=Machine(self.img,self.cases[6]);self.assertEqual(machine.invocations,0);self.assertEqual(machine.executed,{})
   self.assertEqual(machine.refs[machine.get(machine.role_attrs['on']+0x78)],machine.refs[machine.get(machine.role_attrs['off']+0x78)])
   self.assertNotEqual(machine.groups['A'],machine.groups['B']);self.assertEqual(len(machine.collections[machine.get(machine.groups['A']+0xd0)]),19);self.assertEqual(machine.collections[machine.get(machine.groups['B']+0xd0)],[])
   for l,g in machine.level_owner.items():self.assertEqual(machine.manager_group[machine.get(l+0x94)],g)
   self.assertEqual(machine.state()['groups'],self.cases[6]['groups']);start.assert_not_called()
 def test_compare_rejects_wrong_order_and_mutated_state(self):
  c=self.cases[4];e=c['expected'];r={'completed':e['completed'],'trace':copy.deepcopy(e['trace']),'state':{k:copy.deepcopy(v) for k,v in e.items() if k not in ('trace','completed')}};probe.compare(r,c)
  r['trace'][0],r['trace'][1]=r['trace'][1],r['trace'][0]
  with self.assertRaises(RuntimeError):probe.compare(r,c)
  r['trace']=copy.deepcopy(e['trace']);r['state']['groups'][0]['levels'][0]['value']=255
  with self.assertRaises(RuntimeError):probe.compare(r,c)
 def test_fifo_and_read_interruption_preserve_first(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/'fifo';os.mkfifo(p)
   for fn in (probe.read,driver.read):
    with self.assertRaises((ValueError,RuntimeError)):fn(p,128)
   q=Path(td)/'file';q.write_bytes(b'abc');original_close=os.close
   for fn in (probe.read,driver.read):
    first=KeyboardInterrupt('read');second=SystemExit('close')
    def close(fd):original_close(fd);raise second
    with patch.object(os,'read',side_effect=first),patch.object(os,'close',side_effect=close):
     with self.assertRaises(KeyboardInterrupt) as got:fn(q,128)
    self.assertIs(got.exception,first)
 def test_child_input_runtime_and_order_associations(self):
  inputs={str(BASE/'probe.py'):'code',str(BASE/'cases.json'):'cases','python':'exe','library':'lib','module':'mod'}
  rt={'executable':'python','executable_sha256':'exe','libraries':{'library':'lib'},'loaded_python_modules':{'wrapper':{'path':'module','sha256':'mod'}}}
  child={'format':'thermostat-outer-original12-v1','inputs_before':dict(inputs),'inputs_after':dict(inputs),'runtime_before':rt,'runtime_after':rt,'secondary_errors':[],'passed':True,'original_requested':True,'original_executed':True,'results':[{'id':c['id'],'case':c,'original_entries':1,'matched_expected':True} for c in self.cases]}
  self.assertEqual(len(driver.associate(child,inputs,self.cases)['case_ids']),12)
  for edit in (lambda d:d['runtime_before']['loaded_python_modules']['wrapper'].update(sha256='wrong'),lambda d:d['results'][0].update(id='O02'),lambda d:d['inputs_before'].update({str(BASE/'probe.py'):'wrong'})):
   d=copy.deepcopy(child);edit(d)
   with self.assertRaises(ValueError):driver.associate(d,inputs,self.cases)
 def test_fresh_rejects_existing_and_external_destinations(self):
  for path in (BASE/'probe.py',BASE.parent/'outside',BASE/'..'/'outside'):
   with self.assertRaises(ValueError):driver.fresh(path)
if __name__=='__main__':unittest.main(verbosity=2)
