"""Host-only: no Image/Machine initializer or original instruction execution."""
from pathlib import Path
import ast,copy,hashlib,importlib.util,json,os,tempfile,types,unittest
from unittest.mock import patch
BASE=Path(__file__).resolve().parent

def module(name,path):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
probe=module('levels_probe_guard',BASE/'probe.py');driver=module('levels_driver_guard',BASE/'run_pilot.py')
class GuardTests(unittest.TestCase):
 def test_record_keeps_event_and_rtl_name_metadata(self):
  fixture=types.SimpleNamespace(events=[])
  probe.Machine.record(fixture,'rtl',name='UStrAsg')
  self.assertEqual(fixture.events,[{'event':'rtl','name':'UStrAsg'}])
  fixture.events=[None]*100000
  with self.assertRaises(probe.HarnessError):probe.Machine.record(fixture,'rtl',name='UStrAsg')
 def test_intel_runtime_dependency_loaded_before_baseline(self):
  before=probe.runtime_evidence()
  self.assertEqual(before['loaded_python_modules']['unicorn.unicorn_py3.arch.intel']['sha256'],'8a04281923b5f4dd65ce5f122e222bd86df3e8efc7eae99086e0d372fd7a1a75')
  self.assertEqual(probe.runtime_evidence(),before)
 def test_regular_bounded_and_fifo_symlink_before_read(self):
  with tempfile.TemporaryDirectory(dir=BASE) as d:
   root=Path(d);p=root/'file';p.write_bytes(b'abc');fifo=root/'fifo';os.mkfifo(fifo);link=root/'link';link.symlink_to(p)
   for reader in (probe.bounded_read,driver.read):
    self.assertEqual(reader(p,3),b'abc')
    with self.assertRaises((ValueError,probe.HarnessError)):reader(p,2)
    with self.assertRaises((ValueError,probe.HarnessError)):reader(fifo,2)
    with self.assertRaises(OSError):reader(link,3)
 def test_original_read_error_retained_across_close_error(self):
  with tempfile.TemporaryDirectory(dir=BASE) as d:
   p=Path(d)/'file';p.write_bytes(b'abc');real_close=os.close
   for reader in (probe.bounded_read,driver.read):
    first=KeyboardInterrupt('read');secondary=SystemExit('close')
    def close(fd):real_close(fd);raise secondary
    with patch('os.read',side_effect=first),patch('os.close',side_effect=close):
     try:reader(p,3)
     except BaseException as error:self.assertIs(error,first)
 def fixture(self):
  expected={k:hashlib.sha256(k.encode()).hexdigest() for k in ('probe_sha256','cases_sha256','exe_sha256')};cases=[{'id':'one'},{'id':'two'}]
  result={'format':'thermostat-levels-original-pilot-v1',**expected,'source_after':expected.copy(),'source_postcheck_errors':[],'results':[{'id':'one'},{'id':'two'}]}
  return result,expected,cases
 def test_association_rejects_each_hash_wrong_order_and_postcheck(self):
  result,expected,cases=self.fixture();self.assertFalse(driver.associate_child(result,expected=expected,cases=cases)['partial'])
  for key in expected:
   value=copy.deepcopy(result);value[key]='0'*64
   with self.assertRaises(ValueError):driver.associate_child(value,expected=expected,cases=cases)
  for value in ({**result,'results':list(reversed(result['results']))},{**result,'results':result['results'][:1]}, {**result,'source_after':{}},{**result,'source_postcheck_errors':['changed']}):
   with self.assertRaises(ValueError):driver.associate_child(value,expected=expected,cases=cases)
 def test_partial_evidence_still_requires_exact_input_and_ordered_prefix(self):
  result,expected,cases=self.fixture();result['results']=result['results'][:1];result['source_after']={}
  self.assertEqual(driver.associate_child(result,expected=expected,cases=cases,partial=True)['ordered_case_ids'],['one'])
  result['results']=[{'id':'two'}]
  with self.assertRaises(ValueError):driver.associate_child(result,expected=expected,cases=cases,partial=True)
 def test_failure_rechecks_every_child_source_and_keeps_first(self):
  cases=(BASE/'cases.json').read_bytes();first=KeyboardInterrupt('original fixture stop');after=False;reads=[]
  class Image:
   raw=b'fixture';spans=[]
   def __init__(self,path):pass
  def reader(path,limit):
   nonlocal after
   name=Path(path).name;reads.append((after,name))
   if name=='cases.json':
    if after:raise SystemExit('secondary source reopen')
    return cases
   return b'fixture'
  def stop(*args):
   nonlocal after
   after=True;raise first
  with tempfile.TemporaryDirectory(dir=BASE) as d:
   out=Path(d)/'capture'
   with patch.object(probe,'Image',Image),patch.object(probe,'bounded_read',reader),patch.object(probe,'runtime_evidence',return_value={'fixture':True}),patch.object(probe,'run_case',side_effect=stop),patch.object(probe.sys,'argv',['probe',driver.TOKEN,'cases.json',str(out),'original.exe']):
    try:probe.main()
    except BaseException as error:self.assertIs(error,first)
   result=json.loads((out/'report.json').read_text());self.assertFalse(result['passed']);self.assertEqual(result['error']['type'],'KeyboardInterrupt')
   self.assertEqual(result['source_postcheck_errors'][0]['type'],'SystemExit')
   self.assertEqual([name for post,name in reads if post],['cases.json','probe.py','original.exe'])
 def test_reviewed_original_ranges_providers_machine_and_cases_unchanged(self):
  def selected(path):
   tree=ast.parse(path.read_text());result={}
   for node in tree.body:
    if isinstance(node,ast.Assign):
     names=[x.id for x in node.targets if isinstance(x,ast.Name)]
     for n in names:
      if n in ('RANGES','RTL','PROVIDERS','ACTION'):result[n]=ast.dump(node,include_attributes=False)
    if isinstance(node,(ast.ClassDef,ast.FunctionDef)) and node.name in ('Machine','validate','run_case'):
     if node.name=='Machine':node.body=[x for x in node.body if not isinstance(x,ast.FunctionDef) or x.name!='record']
     result[node.name]=ast.dump(node,include_attributes=False)
   return result
  self.assertEqual(selected(BASE/'probe.py'),selected(BASE/'pre-review-v2/probe.py'))
  self.assertEqual(hashlib.sha256((BASE/'cases.json').read_bytes()).hexdigest(),'a40ec85ae4995bba9e2c07b11ead669fad7723e4be46b38b294a12eefb650156')
if __name__=='__main__':unittest.main(verbosity=2)
