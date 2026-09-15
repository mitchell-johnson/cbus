"""Held network-denied replay of four successful owned C-Gate captures.

No cold XML importer or real transport. Parsed native facts initialize the same
explicit cached fixture; original builder, command/parser and Area methods run.
"""
from __future__ import annotations
import hashlib,importlib.util,json,os,re,sys,time
from pathlib import Path
from xml.etree import ElementTree as ET
BASE=Path(__file__).resolve().parent
ROOT=Path('/Users/mitchell/source/cbus/toolkit-cli')

def load(path,raw,name):
 spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec)
 exec(compile(raw,str(path),'exec'),module.__dict__);return module

def require(value,message):
 if not value:raise RuntimeError(message)

def text(value,limit=256):
 require(type(value) is str and len(value)<=limit and value.isascii() and all(32<=ord(c)<=126 for c in value),'Bounded native cached text')
 return value

def project_cases(report,expected):
 require(type(report) is dict and report.get('format')=='csv-backend-native4-v1' and report.get('passed') is True and report.get('native_capture_complete') is True,'Accepted native capture')
 rows=report.get('fixtures');require(type(rows) is list and len(rows)==4 and all(type(r) is dict for r in rows) and [r.get('case') for r in rows]==expected,'Native case association')
 result=[]
 for row,case in zip(rows,expected):
  require(row.get('capture_complete') is True and row['xml_before']==row['xml_after'],'Unchanged complete native fixture')
  raw=row['xml_before'];require(type(raw) is str and len(raw)<=1024*1024 and '<!DOCTYPE' not in raw.upper() and '<!ENTITY' not in raw.upper(),'Native XML bound')
  root=ET.fromstring(raw);units=root.findall('.//Unit');require(len(units)==1,'Exactly one unit')
  unit=units[0]
  def field(node,name):
   nodes=node.findall(name);require(len(nodes)==1 and not list(nodes[0]),'Single native scalar '+name)
   return text(nodes[0].text or '')
  fields={key:field(unit,name) for key,name in {'part_name':'UnitName','tag_name':'TagName','unit_type':'UnitType','catalog':'CatalogNumber','serial':'SerialNumber','firmware':'FirmwareVersion'}.items()}
  oid=field(unit,'OID');require(oid==row['oid'] and re.fullmatch(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}',oid),'Exact native OID')
  require(fields['unit_type']==case['unit_type'] and fields['firmware']==case['firmware'] and field(unit,'Address')=='4','Native factory/scalar fields')
  applications=root.findall('.//Application');require(len(applications)==1 and field(applications[0],'Address')=='56','Fixed application cache')
  groups=[]
  for g in applications[0].findall('Group'):
   address=field(g,'Address');require(re.fullmatch(r'[0-9]{1,3}',address),'Group address')
   groups.append({'address':int(address),'tag':field(g,'TagName'),'oid':field(g,'OID')})
  require(len(groups)==len(case['groups']) and {g['address'] for g in groups}==set(case['groups']),'Exact native group cache')
  responses=[]
  if case['unit_type']=='RELAY4':
   target='//'+case['project']+'/!'+oid
   selected=[r for r in row['reads'] if r['target']==target and r['parameter']=='AreaGroupAddress'];require(len(selected)==1,'One literal OID Area reply')
   response=selected[0];require(type(response['lines']) is list and len(response['lines'])==1,'One terminal Area reply')
   require(response['lines'][0]=='315 AreaGroupAddress='+response['value'],'Literal parameter correlation')
   value=text(response['value']);require(re.fullmatch(r'(?:0[xX][0-9a-fA-F]{1,2}|[0-9]{1,3})',value),'Admitted numeric Area spelling')
   numeric=int(value,16) if value.lower().startswith('0x') else int(value)
   require(numeric==case['area'],'Exact expected Area byte')
   require(row['parameters_before']==row['parameters_after'] and row['parameters_before']['AreaGroupAddress']==value,'Native full parameter baseline')
   responses=[text(response['lines'][0])]
  result.append({'id':case['id'],'project':case['project'],'oid':oid,'type':case['unit_type'],'firmware':case['firmware'],
    'fields':fields,'groups':groups,'primary_tag':field(applications[0],'TagName'),'responses':responses,'expected_area':case['area'],
    'expected_partial_save':case['id']=='B03','native_xml_sha256':hashlib.sha256(raw.encode()).hexdigest()})
 return result

def machine_type(probe,prior,m):
 Parent=probe.machine_type(prior,m)
 class Replay(Parent):
  def __init__(self,image,case):
   self.native_case=case
   bc={'action':'area','project':case['project'],'network_path':'254','oid':case['oid'],'parameter':'AreaGroupAddress','responses':case['responses']}
   cached={'type':case['type'],'firmware':case['firmware'],'raw_area':'255','cache_addresses':[g['address'] for g in case['groups']],
           'quick_get':['12','12'],'deny':'save' if case['expected_partial_save'] else None}
   super().__init__(image,bc,cached_case=cached)
  def group(self,address,label,created=False):
   if created:
    require(self.native_case['id']=='B03' and address==0,'Only expected missing13 creation');label='created-13'
   obj=super().group(address,label,created)
   if not created:
    source=next(g for g in self.native_case['groups'] if g['address']==address)
    for offset,key in ((0x9c,'tag'),(0x58,'oid')):
     attr=self.get(obj+offset);_,label=self.attributes[attr];self.attributes[attr]=(source[key],label)
   return obj
  def agent(self,owner,kind):
   result=super().agent(owner,kind)
   if kind=='unit' and self.native_case['type']=='OWNED_UNKNOWN':self.put(result,0x121576c)
   return result
  def construct_unit(self,vmt):
   obj=super().construct_unit(vmt)
   for key,offset in m.FIELDS.items():
    attr=self.get(obj+offset);_,label=self.attributes[attr];self.attributes[attr]=(self.native_case['fields'][key],label)
   self.attributes[self.get(self.primary+0x9c)]=(self.native_case['primary_tag'],'app-Lighting')
   return obj
  def hook(self,u,address,size,user):
   # The prior pilot admitted only created255. This new, finite provider admits
   # the original SetAddress variant for missing13 in B03; no implementation code changes.
   if address==0x30001150 and u.reg_read(m.EAX) in self.address_attributes:
    eax=u.reg_read(m.EAX);edx=u.reg_read(m.EDX)
    require(self.native_case['id']=='B03' and self.address_attributes[eax] in self.created
      and self.variants.get(edx)==('int',13),'Exact new-group address provider')
    self.instructions+=1;require(self.instructions<=1000000,'Instruction bound')
    self.put(eax+0x88,13);self.record('variant-attribute-write',attribute=hex(eax),value=13);self.return_from_provider();return
   return super().hook(u,address,size,user)
  def run_observation(self):
   c=self.native_case;self.phase='factory';self.invoke(0xf34104,self.builder)
   expected='TRELAY4' if c['type']=='RELAY4' else 'TCBusUnitGeneric'
   require(self.selected_class==expected and self.u.reg_read(m.EAX)==self.unit_obj,'Original factory selection')
   before=self.snapshot();require(before['fields']==c['fields'],'Native scalar fixture projection')
   self.phase='area';partial=None
   try:self.invoke(0xd23704 if expected=='TRELAY4' else 0xf34770,self.unit_obj)
   except prior.DeclaredStop as error:
    require(c['expected_partial_save'] and str(error)=='Explicit owned storage save denied','Only expected metadata-save stop')
    partial={'type':type(error).__name__,'message':str(error)}
   require((partial is not None)==c['expected_partial_save'],'Original completion/partial association')
   area=None
   if expected=='TRELAY4':
    require(len(self.commands)==1 and self.freed_commands==self.commands and len(self.response_observations)==1,'One completed original QuickGet')
    state=self.command_state(self.commands[0]);literal='pp quickget //'+c['project']+'/!'+c['oid']+' AreaGroupAddress'
    require(state['command']==literal and state['result']==c['responses'][0].split('=',1)[1] and state['completed'],'Original generated/parser terminal')
    require(self.read(self.get(self.unit_obj+0x160))==state['result'],'Actual AgentLoad field projection')
    if partial is None:
     target=self.get(self.reference_attributes[self.area_attribute]+0x18)
     require(target in self.collections[self.groups],'Retained cache Area reference')
     area=self.get(self.get(target+0x80)+0x88);require(area==c['expected_area'],'Original Area byte')
   else:
    require(self.u.reg_read(m.EAX)==0 and not self.commands and not self.loads and not self.saves and not self.created,'Generic nil/no QuickGet')
   require((len(self.created),len(self.saves))==((1,1) if partial else (0,0)),'Expected metadata mutation phase')
   if partial:
    require(self.get(self.get(self.created[0]+0x80)+0x88)==13 and self.saves[0]['returned'] is False,'Original missing13 partial save')
   require(not self.live_studios,'No retained owned Studio')
   return {'input':c,'before':before,'after':self.snapshot(),'area':area,'completed':partial is None,'declared_stop':partial,
     'command_states':[self.command_state(cmd) for cmd in self.commands],'response_phases':self.response_observations,**self.evidence()}
 return Replay

# The companion launcher supplies only these captured bytes after native cleanup.
def main():
 require(sys.version_info[:2] in ((3,10),(3,13)) and len(sys.argv)==3,'Supported interpreter/report/new output')
 # This import contains no I/O and no native or original constructors.
 support_path=BASE/'backend_support.py'
 # The top-level launcher pins these bytes before this child is created.
 fd=os.open(support_path,os.O_RDONLY|os.O_NONBLOCK|os.O_NOFOLLOW);first=None
 try:
  import stat
  info=os.fstat(fd);require(stat.S_ISREG(info.st_mode) and info.st_size<=65536,'Regular bounded support')
  chunks=[];size=0
  while size<=65536:
   block=os.read(fd,min(65536,65537-size))
   if not block:break
   chunks.append(block);size+=len(block)
  raw=b''.join(chunks);require(size<=65536,'Support bound')
 except BaseException as error:first=error;raise
 finally:
  try:os.close(fd)
  except BaseException:
   if first is None:raise
 host=load(support_path,raw,'csv_replay_host');host.own(BASE)
 native_path=host.existing_output(BASE,Path(sys.argv[1]),'report.json');out=Path(sys.argv[2]);host.new_output(BASE,out,nested='capture')
 marker=host.strict_json(host.read(out.parent/'replay-owned.json',4096))
 names=('replay_native.py','NativeCSVBackendProbe.py','backend_support.py','native-cases.json')
 src={BASE/name:host.read(BASE/name) for name in names}
 native_raw=host.read(native_path,48*1024*1024)
 require(marker=={'format':'csv-backend-replay-launch-v1','owner_token':host.TOKEN,'native_report_sha256':host.digest(native_raw),
     'inputs_sha256':{p.name:host.digest(b) for p,b in src.items()}},'Exact replay launcher association')
 native=host.strict_json(native_raw)
 for path,value in src.items():require(native['before'][str(path)]==host.digest(value)==native['after'][str(path)],'Reviewed native source association')
 expected=host.strict_json(src[BASE/'native-cases.json']);cases=project_cases(native,expected)
 probe=load(BASE/'NativeCSVBackendProbe.py',src[BASE/'NativeCSVBackendProbe.py'],'csv_backend_original_for_replay')
 inputs={probe.PRIOR:host.read(probe.PRIOR),probe.EXE:host.read(probe.EXE),probe.MAP:host.read(probe.MAP),
  ROOT/'research/NativeToolkitDatabaseCSVProbe.py':host.read(ROOT/'research/NativeToolkitDatabaseCSVProbe.py'),**src,native_path:native_raw}
 require(host.digest(inputs[probe.PRIOR])==probe.PRIOR_SHA and host.digest(inputs[probe.EXE])==probe.EXE_SHA and host.digest(inputs[probe.MAP])==probe.MAP_SHA,'Original replay pins')
 host.new_output(BASE,out,nested='capture');out.mkdir();report={'format':'csv-backend-native-replay4-v1','passed':False,'capture_complete':False,'results':[],
  'inputs':{str(p):host.digest(b) for p,b in inputs.items()},'scope':{'native_transport':False,'original_cold_xml_import':False,'original_full_unit_constructors':False,'native_scalars_as_explicit_cached_fixture':True}}
 failures=host.Failures(report);machines=[]
 report.update(original_execution_requested=True,original_execution=False,original_invocations_attempted=0,original_instruction_entries=0)
 try:
  prior,m,image=probe.support(inputs);report['spans']=image.spans
  runtime={str(Path(v).resolve()):host.digest(host.read(Path(v).resolve())) for v in (m.capstone._cs._name,m.unicorn_core.uclib._name)}
  require(set(runtime.values())==probe.LIBRARIES,'Actual original emulator libraries')
  inputs.update({Path(p):host.read(Path(p)) for p in runtime});inputs[Path(sys.executable).resolve()]=host.read(Path(sys.executable).resolve())
  report['runtime']={'libraries':runtime,'python':sys.version,'executable':str(Path(sys.executable).resolve()),'executable_sha256':host.digest(inputs[Path(sys.executable).resolve()])}
  report['inputs']={str(p):host.digest(b) for p,b in inputs.items()}
  Machine=machine_type(probe,prior,m);report['runtime']['python_sources']=probe.python_sources();start=time.monotonic()
  for case in cases:
   require(time.monotonic()-start<60,'Replay batch deadline');row={'id':case['id'],'captured':False};report['results'].append(row)
   machine=Machine(image,case);machines.append(machine)
   try:row.update(machine.run_observation());row['captured']=True
   finally:
    primary=sys.exc_info()[1]
    try:row['partial_evidence']=machine.evidence()
    except BaseException as error:
     if primary is None:raise
     row['evidence_error']=host.error_record(error)
  require(sum(r['completed'] for r in report['results'])==3 and report['results'][2]['declared_stop'] is not None,'Three original completions/one expected partial save')
  report['capture_complete']=True;report['passed']=True
 except BaseException as error:failures.retain('original replay',error)
 finally:
  report.update(probe.execution_evidence(machines))
  if 'runtime' in report and 'python_sources' in report['runtime']:
   observed=failures.attempt('actual loaded Python wrappers',probe.python_sources);report['runtime_python_sources_after']=observed
   if observed is not None:failures.attempt('loaded wrapper equality',lambda:require(observed==report['runtime']['python_sources'],'Loaded Python source set or bytes changed'))
  host.posthashes(inputs,report,failures);host.finish(out,report,failures)
 failures.raise_first();print(json.dumps({'captured':4,'completed':3,'partial':1}))

if __name__=='__main__':main()
