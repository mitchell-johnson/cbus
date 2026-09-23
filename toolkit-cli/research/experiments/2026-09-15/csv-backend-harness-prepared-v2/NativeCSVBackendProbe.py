"""Held original QuickGet/Area instruction harness; no native transport.

Only prepare mode may run before parent review. Execution requires an exact
external admission and launcher association. Existing cached/RTL providers are
explicit fixtures. No PE entrypoint, imports, constructor or exception dispatcher.
"""
from __future__ import annotations
import hashlib,importlib.util,json,os,re,struct,sys,time
from pathlib import Path

BASE=Path(__file__).resolve().parent
REPO=Path('/Users/mitchell/source/cbus/toolkit-cli')
PRIOR=BASE.parent/'projection-pilot-v1/NativeCachedCSVProbe.py'
PRIOR_SHA='0e3acf18fa5d23a38f3a319aa36af374881ffe880926d195c42d7ce539b32e54'
EXE=REPO/'research/vendor/toolkit/app/CBusToolkit.exe';MAP=EXE.with_suffix('.map')
EXE_SHA='9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab'
MAP_SHA='f96f05cef7c2bdf0f295397d97249b50c45db013f3fcaa2c502f76e2c10dd1eb'
TOKEN='b0f8078731a54cc4aa069f00b043d210'
LIBRARIES={'016084c6e70d929249a2abb22f1afda95095294e6cd70f509964ffc54006bf94','7207c8e3d7a63118fb0bca73e01816797fd51b1d8a39a4cbc7abfd562ee59c85'}
# Exact method starts; normal CFG only. Calls are separately admitted below or
# in the accepted frozen support, never automatically followed.
METHODS={
0x6187ac:'LowerCase-Unicode',0x618f9c:'Trim',0x7b78f4:'StringContainsAll',
0x7ef1c4:'BaseAgentLoad',0x7ef46c:'IsInVerbs',0x7ef4f0:'IsVarInVerbs',
0x843c5c:'BaseGenerateCommand',0x843c74:'BaseProcessResult',0x843cec:'HasResponse',0x843de4:'SetCompleted',
0xcb0694:'QuickGetGenerate',0xcb070c:'QuickGetProcessResults',0xcb0a9c:'ExtractParameter',0xcb0c4c:'ProcessParameter',
0xcb0cbc:'SetParameter',0xcb0cdc:'SetSingleResult',0xcb5720:'AgentGetUnit',0xcb5d0c:'AgentLoad',0xcb87f4:'QuickGetSingle',
0xcc3264:'ProjectPrefix',0xcc335c:'QuickGet',0xf2b260:'NetworkProject',0xf2e82c:'UnitAddressPath',0xf2fff8:'UnitNetwork',
0xf479f0:'AddressString',0xf47a10:'AddressInteger',0xf47a58:'OIDAsCGateID',0xf47bf0:'AddressAsCGateID',0xf47c7c:'OIDIsBlank'}
PROVIDERS={0xcac3bc:'owned-communicator',0x8435dc:'owned-command-constructor',0x843860:'owned-command-transport',
0x30001200:'owned-command-continuation',0x30001210:'owned-network-path'}

def digest(raw):return hashlib.sha256(raw).hexdigest()
def require(test,message):
 if not test:raise RuntimeError(message)
def read(path,limit=64*1024*1024):
 import stat
 fd=os.open(path,os.O_RDONLY|os.O_NONBLOCK|os.O_NOFOLLOW);first=None
 try:
  info=os.fstat(fd);require(stat.S_ISREG(info.st_mode) and info.st_size<=limit,'Bounded regular input')
  chunks=[];size=0
  while size<=limit:
   chunk=os.read(fd,min(65536,limit+1-size))
   if not chunk:break
   chunks.append(chunk);size+=len(chunk)
  require(size<=limit,'Input exceeds bound');return b''.join(chunks)
 except BaseException as e:first=e;raise
 finally:
  try:os.close(fd)
  except BaseException:
   if first is None:raise

def load_module(path,raw,name):
 spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec)
 exec(compile(raw,str(path),'exec'),module.__dict__);return module

def python_sources():
 observed={}
 for name,module in tuple(sys.modules.items()):
  if name=='pefile' or name=='capstone' or name.startswith('capstone.') or name=='unicorn' or name.startswith('unicorn.'):
   source=getattr(module,'__file__',None)
   require(type(source) is str,'Loaded research module source path')
   path=Path(source).resolve(strict=True)
   require(path.suffix=='.py','Expected loaded Python research wrapper')
   observed[name]={'path':str(path),'sha256':digest(read(path))}
 require(all(name in observed for name in ('pefile','capstone','unicorn')),'Actual loaded wrapper roots')
 return observed

def execution_evidence(machines):
 attempts=sum(machine.invoke_attempts for machine in machines)
 entries=sum(machine.original_entries for machine in machines)
 return {'original_invocations_attempted':attempts,'original_instruction_entries':entries,'original_execution':entries>0}


def support(inputs):
 prior=load_module(PRIOR,inputs[PRIOR],'csv_backend_frozen_projection')
 m,image=prior.load_support(inputs[EXE],inputs[MAP])
 starts=set()
 for line in inputs[MAP].decode('ascii').splitlines():
  match=re.match(r'^\s+0001:([0-9A-Fa-f]{8})\s+(\S+)\s*$',line)
  if match:starts.add(int(match[1],16)+0x601000)
 starts=sorted(starts);decoder=m.capstone.Cs(m.capstone.CS_ARCH_X86,m.capstone.CS_MODE_32)
 image.backend_calls=[];image.backend_finally=[]
 for start,name in METHODS.items():
  require(start in starts,'Exact method start');end=next(x for x in starts if x>start)
  require(end-start<=8192,'Method span bound');pending=[start];decoded={}
  while pending:
   a=pending.pop()
   if a in decoded:continue
   require(start<=a<end,'Branch escapes method '+name+' '+hex(a))
   ins=next(decoder.disasm(image.pe.get_data(a-image.base,16),a,count=1),None)
   require(ins is not None and a+ins.size<=end,'Complete original instruction')
   require(ins.mnemonic not in ('int','syscall','sysenter','in','out','hlt'),'Forbidden instruction')
   decoded[a]=ins
   if ins.mnemonic=='push' and re.fullmatch(r'0x[0-9a-f]+',ins.op_str) and image.pe.get_data(a-image.base-3,3)==b'\x64\x89\x10':
    target=int(ins.op_str,16);require(start<=target<end,'Finally continuation escape')
    pending.append(target);image.backend_finally.append({'method':name,'push':hex(a),'target':hex(target)})
   if ins.mnemonic.startswith('ret'):continue
   if ins.mnemonic=='jmp':
    require(re.fullmatch(r'0x[0-9a-f]+',ins.op_str),'Indirect jump excluded')
    target=int(ins.op_str,16)
    if target not in (0x606c24,0x606a9c,0x604a8c):pending.append(target)
    continue
   if ins.mnemonic.startswith('j') or ins.mnemonic.startswith('loop'):
    require(re.fullmatch(r'0x[0-9a-f]+',ins.op_str),'Branch format')
    pending.append(int(ins.op_str,16))
   pending.append(a+ins.size)
   if ins.mnemonic=='call':image.backend_calls.append({'method':name,'from':hex(a),'target':ins.op_str})
  for a,ins in decoded.items():
   require(a not in image.instructions,'Duplicate instruction admission');image.instructions[a]=(name,ins.bytes)
  image.spans.append({'name':name,'start':hex(start),'end_bound':hex(end),'span_sha256':digest(image.pe.get_data(start-image.base,end-start)),
   'instruction_count':len(decoded),'instructions_sha256':digest(b''.join(struct.pack('<I',a)+bytes(decoded[a].bytes) for a in sorted(decoded)))})
 return prior,m,image

def validate(cases):
 require(type(cases) is list and len(cases)==8,'Eight exact cases required')
 expected_ids=['A01','A02','A03','A04','A05','A06','A07','A08']
 require(all(type(c) is dict for c in cases) and [c.get('id') for c in cases]==expected_ids,'Ordered case IDs')
 keys={'id','action','oid','project','network_path','parameter','responses','expected_command','expected_values','expected_completed','expected_result','expected_area'}
 for c in cases:
  require(type(c) is dict and set(c)==keys,'Exact case schema')
  require(c['action'] in ('quickget','area'),'Owned action')
  for key in ('oid','project','network_path','parameter','expected_command','expected_result'):
   v=c[key];require(type(v) is str and len(v)<=1024 and v.isascii() and all(32<=ord(x)<=126 for x in v),'Bounded ASCII fixture text')
  require(c['oid'] in ('OWNED-UNIT-4','BLANK') and c['project']=='CSVOWNED' and c['network_path']=='254' and c['parameter']=='AreaGroupAddress','Finite topology')
  require(type(c['responses']) is list and 1<=len(c['responses'])<=2,'Response count')
  require(all(type(v) is str and 1<=len(v)<=256 and v.isascii() and all(32<=ord(x)<=126 for x in v) for v in c['responses']),'Response text')
  require(type(c['expected_values']) is list and len(c['expected_values'])==len(c['responses']) and all(type(v) is str and len(v)<=256 for v in c['expected_values']),'Expected values')
  require(type(c['expected_completed']) is list and len(c['expected_completed'])==len(c['responses']) and all(type(v) is bool for v in c['expected_completed']),'Expected completion')
  require(c['expected_area'] is None or type(c['expected_area']) is int and c['expected_area'] in (12,255),'Area expectation')
  require((c['action']=='area')==(c['expected_area'] is not None),'Area action association')


def machine_type(prior,m):
 Cached=prior.machine_type(m)
 from unicorn.x86_const import UC_X86_REG_EBP,UC_X86_REG_EBX,UC_X86_REG_ESI,UC_X86_REG_EDI
 preserved=(UC_X86_REG_EBP,UC_X86_REG_EBX,UC_X86_REG_ESI,UC_X86_REG_EDI)
 class Machine(Cached):
  def __init__(self,image,case,*,cached_case=None):
   self.backend_case=case;self.invoke_attempts=0;self.original_entries=0;self.commands=[];self.freed_commands=[];self.pipeline=None;self.response_observations=[]
   base={'type':'RELAY4','firmware':'4.4','raw_area':'255','cache_addresses':[1,2,3,4,5,6,7,8,12,13,255],'quick_get':['12','12'],'deny':None}
   super().__init__(image,base if cached_case is None else cached_case)
   self.communicator=self.object({});self.labels[self.communicator]='owned-communicator'
  def agent(self,owner,kind):
   if kind!='unit':return super().agent(owner,kind)
   agent=self.real_object(0x124927c,'actual-relay-agent-vmt');self.put(agent+0x78,owner)
   self.u.mem_write(agent+0x7c,b'\x01');self.put(owner+0x78,agent);self.agents[agent]=(owner,kind);self.unit_agent=agent
   return agent
  def construct_unit(self,vmt):
   obj=super().construct_unit(vmt);c=self.backend_case
   self.attributes[self.get(obj+0x58)]=(c['oid'],'oid-unit')
   self.project=self.object({});self.labels[self.project]='project-shell' # Parent field/tag only; no project VMT call.
   self.put(self.project+0x9c,self.attribute(c['project'],'project-tag'))
   self.network=self.object({0x90:0x30001210});self.labels[self.network]='network-shell'
   self.put(self.network+0x54,self.project);self.put(obj+0x54,self.network)
   return obj
  def command_state(self,cmd):
   return {'command':self.read(self.get(cmd+0x7c)),'target':self.read(self.get(cmd+0x90)),
    'parameter':self.read(self.get(cmd+0x94)),'result':self.read(self.get(cmd+0x98)),
    'state':self.u.mem_read(cmd+0x18,1)[0],'completed':self.u.mem_read(cmd+0x18,1)[0] in (1,3),
    'raw_command_hex':bytes(self.u.mem_read(cmd,0x200)).hex()}
  def schedule(self):
   p=self.pipeline;require(p is not None,'Owned active transport continuation')
   if p['last'] is not None:
    require(self.u.reg_read(m.ESP)==p['expected_esp'],'Original scheduled return stack')
    state=self.command_state(p['cmd']);self.record('original-command-phase',phase_name=p['last'],state=state)
    if p['last'].startswith('response-'):self.response_observations.append(state)
   if not p['actions']:
    require(self.get(0)==p['fs'],'Original FS restoration')
    for reg,value in p['preserved'].items():require(self.u.reg_read(reg)==value,'Original callee register preservation')
    self.u.reg_write(m.EAX,1);self.u.reg_write(m.ESP,p['esp']+4);self.u.reg_write(m.EIP,p['return'])
    self.pipeline=None;return
   action=p['actions'].pop(0);p['last']=action['name'];sp=0x20037000
   self.put(sp,0x30001200);p['expected_esp']=sp+4+4*len(action.get('stack',()))
   for index,value in enumerate(action.get('stack',())):self.put(sp+4+4*index,value)
   self.u.reg_write(m.ESP,sp);self.u.reg_write(m.EAX,p['cmd']);self.u.reg_write(m.EDX,0)
   self.u.reg_write(m.ECX,action.get('text',0));self.u.reg_write(m.EIP,action['entry'])
  def hook(self,u,address,size,user):
   if address==0x606200 and u.reg_read(m.EAX) in self.commands:
    cmd=u.reg_read(m.EAX)
    require(self.pipeline is None and self.get(u.reg_read(m.ESP))==0xcc34f5 and cmd not in self.freed_commands,'Owned command free caller')
    self.freed_commands.append(cmd);self.record('owned-command-free',command=self.command_state(cmd));self.return_from_provider();return
   if address not in PROVIDERS:
    result=super().hook(u,address,size,user)
    if address in self.image.instructions:self.original_entries+=1
    return result
   self.instructions+=1;require(self.instructions<=1000000,'Instruction limit')
   eax,edx,ecx,esp=(u.reg_read(r) for r in (m.EAX,m.EDX,m.ECX,m.ESP));kind=PROVIDERS[address]
   if kind=='owned-network-path':
    require(eax==self.network and self.get(esp)==0xf2e881,'Owned network path caller')
    self.put(edx,self.text(self.backend_case['network_path']));self.record(kind,value=self.backend_case['network_path']);self.return_from_provider();return
   if kind=='owned-communicator':
    require(eax==self.unit_agent and self.get(esp)==0xcc339a,'Owned communicator caller');self.return_from_provider(self.communicator);return
   if kind=='owned-command-constructor':
    require(eax==self.image.word(0xcb0580) and edx&255==1 and ecx==self.communicator and self.get(esp)==0xcc33a8 and not self.commands,'Exact command constructor arguments')
    cmd=self.object({});self.labels[cmd]='quickget-command-shell';self.put(cmd,self.image.word(0xcb0580));self.u.mem_write(cmd+0x18,b'\x02')
    self.commands.append(cmd);self.record(kind,class_vmt=hex(eax),caller=hex(self.get(esp)));self.return_from_provider(cmd);return
   if kind=='owned-command-transport':
    require(eax in self.commands and self.get(esp)==0xcc3491 and self.pipeline is None,'Exact owned transport caller')
    actions=[{'name':'generate','entry':0xcb0694}]
    for index,response in enumerate(self.backend_case['responses']):
     actions.append({'name':'response-'+str(index),'entry':0xcb070c,'text':self.text(response),'stack':(0,)})
    self.pipeline={'cmd':eax,'esp':esp,'return':self.get(esp),'fs':self.get(0),'preserved':{r:u.reg_read(r) for r in preserved},'actions':actions,'last':None}
    self.record(kind,initial=self.command_state(eax),responses=self.backend_case['responses']);self.schedule();return
   if kind=='owned-command-continuation':self.schedule();return
   raise RuntimeError('Unexpected owned provider')
  def invoke(self,address,eax,edx=0,ecx=0,stack=()):
   require(self.pipeline is None,'No abandoned native-transport fixture');sp=0x20030000
   self.put(0,0);self.put(sp,0x30000000)
   for index,value in enumerate(stack):self.put(sp+4+4*index,value)
   for reg,value in ((m.ESP,sp),(m.EAX,eax),(m.EDX,edx),(m.ECX,ecx),(m.FLAGS,2)):self.u.reg_write(reg,value)
   self.invoke_attempts+=1
   self.u.emu_start(address,0x30000000,timeout=3000000,count=1000000)
   require(self.u.reg_read(m.EIP)==0x30000000 and self.pipeline is None,'Complete original return')
   require(self.u.reg_read(m.ESP)==sp+4+4*len(stack) and self.get(0)==0,'Original caller stack and FS restoration')
  def run_case(self):
   c=self.backend_case;self.phase='factory';self.invoke(0xf34104,self.builder)
   require(self.selected_class=='TRELAY4' and self.u.reg_read(m.EAX)==self.unit_obj,'Original factory identity')
   before=self.snapshot();self.phase='quickget' if c['action']=='quickget' else 'area'
   result=self.alloc(4)
   if c['action']=='quickget':self.invoke(0xcc335c,self.unit_agent,self.text(c['parameter']),0,(result,))
   else:self.invoke(0xd23704,self.unit_obj)
   require(len(self.commands)==1 and len(self.response_observations)==len(c['responses']),'One command and complete response phases')
   command=self.command_state(self.commands[0]);require(command['command']==c['expected_command'],'Literal generated command')
   require([s['result'] for s in self.response_observations]==c['expected_values'],'Original result sequence')
   require([s['completed'] for s in self.response_observations]==c['expected_completed'],'Original completion sequence')
   observed=self.read(self.get(result)) if c['action']=='quickget' else self.read(self.get(self.unit_obj+0x160))
   require(observed==c['expected_result'],'Outer result/raw Area result')
   area=None
   if c['action']=='area':
    target=self.get(self.reference_attributes[self.area_attribute]+0x18)
    require(target in self.collections[self.groups],'Known Area reference target')
    area=self.get(self.get(target+0x80)+0x88);require(area==c['expected_area'],'Area address')
   require(not self.created and not self.saves and not self.live_studios and self.freed_commands==self.commands,'No metadata creation/save or unreleased owned fixture')
   return {'before':before,'after':self.snapshot(),'command':command,'response_phases':self.response_observations,'result':observed,'area':area,**self.evidence()}
 return Machine


def main():
 require(sys.version_info[:2] in ((3,10),(3,13)),'Python3.10/3.13 required')
 require(len(sys.argv)==3 and sys.argv[1] in ('prepare','execute'),'prepare|execute + fresh output')
 mode=sys.argv[1];out=Path(sys.argv[2]);parent=out.parent.resolve(strict=True)
 require(not out.exists() and not out.is_symlink() and not out.parent.is_symlink() and (parent==BASE or out.name=='capture' and parent.parent==BASE),'Direct owned output')
 ownership=json.loads(read(BASE.parent/'ownership.json',4096));require(ownership['owner_token']==TOKEN and ownership['root']==str(BASE.parent),'External owner')
 paths=(Path(__file__),BASE/'cases.json',PRIOR,EXE,MAP,REPO/'research/NativeToolkitDatabaseCSVProbe.py')
 inputs={p:read(p) for p in paths};require(digest(inputs[PRIOR])==PRIOR_SHA and digest(inputs[EXE])==EXE_SHA and digest(inputs[MAP])==MAP_SHA,'Original/support pins')
 cases=json.loads(inputs[BASE/'cases.json']);validate(cases)
 if mode=='execute':
  admission=json.loads(read(BASE/'admission.json',4096))
  require(admission=={'format':'csv-backend-original-admission-v1','probe_sha256':digest(inputs[Path(__file__)]),'cases_sha256':digest(inputs[BASE/'cases.json']),'authorization':'root-reviewed-csv-backend-original8-v1'},'Held until exact review admission')
  marker=json.loads(read(parent/'launch-owned.json',4096));require(marker=={'format':'csv-backend-launch-v1','owner_token':TOKEN,'probe_sha256':digest(inputs[Path(__file__)]),'cases_sha256':digest(inputs[BASE/'cases.json'])},'Archived launcher association')
 out.mkdir();report={'format':'csv-backend-original8-v1','capture_complete':False,'preparation_complete':False,'original_execution_requested':mode=='execute','original_execution':False,'original_invocations_attempted':0,'original_instruction_entries':0,'inputs':{str(p):digest(v) for p,v in inputs.items()},'results':[]};first=None;machines=[]
 try:
  prior,m,image=support(inputs);report['spans']=image.spans;report['direct_calls']=image.backend_calls;report['finally_continuations']=image.backend_finally
  report['runtime']={'python':sys.version,'executable':str(Path(sys.executable).resolve()),'executable_sha256':digest(read(Path(sys.executable).resolve())),
   'libraries':{str(Path(v).resolve()):digest(read(Path(v).resolve())) for v in (m.capstone._cs._name,m.unicorn_core.uclib._name)},'versions':{'capstone':m.capstone.__version__,'unicorn':m.unicorn.__version__,'pefile':m.pefile.__version__}}
  require(set(report['runtime']['libraries'].values())==LIBRARIES,'Actual accepted runtime libraries')
  Machine=machine_type(prior,m) if mode=='execute' else None
  report['runtime']['python_sources']=python_sources()
  if mode=='prepare':report['preparation_complete']=True
  else:
   started=time.monotonic()
   for case in cases:
    require(time.monotonic()-started<60,'Process instruction deadline');row={'case':case,'captured':False};report['results'].append(row);machine=Machine(image,case);machines.append(machine)
    try:row.update(machine.run_case());row['captured']=True
    finally:
     pending=sys.exc_info()[1]
     try:row['partial_evidence']=machine.evidence()
     except BaseException:
      if pending is None:raise
   report['capture_complete']=True
 except BaseException as error:first=error;report['error']={'type':type(error).__name__}
 finally:
  report['after']={};report['postcheck_errors']=[]
  def check(label,operation):
   nonlocal first
   try:return operation()
   except BaseException as error:
    try:message=str(error)
    except BaseException:message='<unprintable>'
    report['postcheck_errors'].append({'check':label,'type':type(error).__name__,'message':message[:2048]});report['capture_complete']=False;report['preparation_complete']=False
    if first is None:first=error
  for path,raw in inputs.items():
   value=check(str(path),lambda path=path:digest(read(path)));report['after'][str(path)]=value
   if value is not None:check('source equality '+str(path),lambda value=value,raw=raw:require(value==digest(raw),'Input changed'))
  report.update(execution_evidence(machines))
  report['runtime_after']={}
  for path,value in report.get('runtime',{}).get('libraries',{}).items():
   observed=check(path,lambda path=path:digest(read(Path(path))));report['runtime_after'][path]=observed
   if observed is not None:check('runtime equality '+path,lambda observed=observed,value=value:require(observed==value,'Runtime changed'))
  if 'runtime' in report and 'python_sources' in report['runtime']:
   observed=check('actual loaded Python wrappers',python_sources)
   report['runtime_python_sources_after']=observed
   if observed is not None:check('loaded Python wrapper equality',lambda:require(observed==report['runtime']['python_sources'],'Loaded Python source set or bytes changed'))
  if 'runtime' in report:
   observed=check('runtime executable',lambda:digest(read(Path(report['runtime']['executable']))))
   report['runtime_executable_after_sha256']=observed
   if observed is not None:check('runtime executable equality',lambda:require(observed==report['runtime']['executable_sha256'],'Runtime executable changed'))
  check('report bound',lambda:require(len(json.dumps(report,ensure_ascii=True).encode('ascii'))<=4*1024*1024,'Report bound'))
  if 'prior' in locals():prior.finish(out/'report.json',report,first)
  else:
   # No admitted vendor code could run before support initialization. Preserve
   # first failure through best-effort host-only report output.
   try:(out/'report.json').write_text(json.dumps(report,ensure_ascii=True,indent=2)+'\n')
   except BaseException:
    if first is None:raise
 if first is not None:raise first
 print(json.dumps({'mode':mode,'capture_complete':report['capture_complete'],'preparation_complete':report['preparation_complete'],'report':str(out/'report.json')}))

if __name__=='__main__':main()
