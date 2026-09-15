"""Prepared original instruction pilot. Execution requires reviewed release token.

All database/object/string/variant/storage providers are explicit owned fixtures.
No image entrypoint/import, native API, UI or original exception unwind runs.
"""
from pathlib import Path
import hashlib,json,struct,sys,time
import capstone,pefile,unicorn
from unicorn.unicorn_py3.arch import intel as _uc_intel
from unicorn.x86_const import UC_X86_REG_EAX as EAX,UC_X86_REG_EDX as EDX,UC_X86_REG_ECX as ECX,UC_X86_REG_ESP as ESP,UC_X86_REG_EIP as EIP,UC_X86_REG_EFLAGS as FLAGS
EXE_SHA='9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab'
RANGES=(('CreateLevels',0x1130944,0x1130b0a),('FindLevelByAddress',0xf2742c,0xf275f9),
 ('LevelToZones',0xfda610,0xfda707),('BeginSaveLock',0xf2d370,0xf2d383),
 ('EndSaveLock',0xf2d384,0xf2d3f6),('ProjectStorageSave',0xf2dac8,0xf2db29),
 ('LevelManagerAdd',0xf2724c,0xf27293),('LevelManagerGetItem',0xf272b0,0xf272d1),
 ('GetAddressAsInteger',0xf47a10,0xf47a31),('GetSimpleDecimalAddress',0xf47e88,0xf47eb8),
 ('SetAddressAsInteger',0xf47d64,0xf47dc2),('LevelSetValue',0xf26e44,0xf26ea2))
RTL={0x608924:'UStrAsg',0x608914:'UStrClr',0x60891c:'UStrArrayClr',0x60890c:'UStrAddRef',
 0x608d48:'UStrCat',0x608eec:'UStrCatN',0x609114:'UStrCopy',0x62f578:'VarFromUStr',
 0x62f294:'VarFromInt',0x629f1c:'VarClr',0x61b6e8:'Format-literal-s-d'}
PROVIDERS={0xf2fff8:'Unit.GetNetwork',0xf2b260:'Network.Project',0xf26e28:'Level.GetGroup',
 0xf27efc:'Group.GetApplication',0xf260b4:'Application.GetNetwork',0x7ea9dc:'GetWorkspace',
 0x7ea6ac:'LevelConstructor',0x7e8f74:'Collection.GetItem',0x7f3f28:'StorageFilter',
 0x7f409c:'StorageWrite',0x30001000:'Collection.Count',0x30001010:'Collection.Add',
 0x30001020:'Attribute.SetVariant',0x30001030:'Level.Save'}
ACTION={'Enable':0x11308a4,'Disable':0x11308ec,'Overrd':0x1130934}

def digest(raw):return hashlib.sha256(raw).hexdigest()
def require(value,message):
 if not value:raise HarnessError(message)
class HarnessError(Exception):pass
class ProviderDenied(Exception):pass

def error_dict(error):
 try:message=str(error)
 except BaseException:message='<unavailable>'
 return {'type':type(error).__name__,'message':message[:2048]}

def bounded_read(path,limit):
 import os,stat
 fd=os.open(path,os.O_RDONLY|os.O_NONBLOCK|os.O_NOFOLLOW);parts=[];size=0;first=None
 try:
  state=os.fstat(fd);require(stat.S_ISREG(state.st_mode) and state.st_size<=limit,'Bounded regular input required')
  while True:
   data=os.read(fd,min(65536,limit+1-size))
   if not data:break
   size+=len(data);require(size<=limit,'Input grew beyond its bound');parts.append(data)
  return b''.join(parts)
 except BaseException as error:first=error;raise
 finally:
  try:os.close(fd)
  except BaseException:
   if first is None:raise

class Image:
 def __init__(self,path):
  self.path=path;self.raw=bounded_read(path,64*1024*1024);require(digest(self.raw)==EXE_SHA,'EXE hash')
  self.pe=pefile.PE(data=self.raw);self.base=self.pe.OPTIONAL_HEADER.ImageBase
  require(self.pe.FILE_HEADER.Machine==0x14c and self.base==0x600000,'Original x86 image')
  self.mapped=self.pe.get_memory_mapped_image();self.instructions={};self.spans=[]
  decoder=capstone.Cs(capstone.CS_ARCH_X86,capstone.CS_MODE_32)
  for name,start,end in RANGES:
   raw=self.pe.get_data(start-self.base,end-start);items=list(decoder.disasm(raw,start))
   require(items and items[-1].address+items[-1].size==end,'Incomplete span '+name)
   for item in items:
    require(item.mnemonic not in ('int','syscall','sysenter','in','out'),'Privileged instruction')
    self.instructions[item.address]=(name,item.bytes)
   self.spans.append({'name':name,'start':hex(start),'end':hex(end),'sha256':digest(raw)})
 def word(self,va):return struct.unpack('<I',self.pe.get_data(va-self.base,4))[0]

class Machine:
 def __init__(self,image,case):
  self.image=image;self.case=case;self.u=unicorn.Uc(unicorn.UC_ARCH_X86,unicorn.UC_MODE_32)
  size=(len(image.mapped)+4095)&~4095;self.u.mem_map(image.base,size);self.u.mem_write(image.base,image.mapped)
  self.u.mem_protect(image.base,size,unicorn.UC_PROT_READ|unicorn.UC_PROT_EXEC)
  for a,s in ((0,4096),(0x10000000,0x800000),(0x20000000,0x40000),(0x30000000,0x2000)):self.u.mem_map(a,s)
  self.heap=0x10000000;self.events=[];self.executed={};self.instructions=0;self.attrs={};self.variants={};self.levels=[]
  self.storage_attempts=0;self.storage_completed=0;self.level_attempts=0;self.level_completed=0;self.project_requests=0
  self.project=self.obj({0x80:0xf2dac8});self.network=self.obj({});self.unit=self.obj({});self.application=self.obj({});self.workspace=self.obj({})
  self.group=self.obj({});self.manager=self.obj({0x58:0x30001000,0x68:0x30001010});self.form=self.obj({})
  self.put(self.form+0xc,self.unit);self.put(self.group+0xd0,self.manager);self.put(self.manager+0x30,self.group)
  self.put(self.project+0xc8,case.get('initial_lock',0));self.u.mem_write(self.project+0xcd,bytes([case.get('initial_pending',False)]))
  for data in case.get('existing',[]):
   level=self.new_level(data['address'],data['value'],data['tag']);self.put(level+0x94,self.manager);self.levels.append(level)
  self.initial_ids=list(self.levels)
  self.u.hook_add(unicorn.UC_HOOK_CODE,self.hook);self.u.hook_add(unicorn.UC_HOOK_MEM_WRITE,self.write_guard)
 def get(self,a):return struct.unpack('<I',self.u.mem_read(a,4))[0]
 def put(self,a,n):self.u.mem_write(a,struct.pack('<I',n&0xffffffff))
 def alloc(self,n):
  a=self.heap;self.heap=(self.heap+n+15)&~15;require(self.heap<=0x10800000,'Heap bound');return a
 def obj(self,slots):
  vmt=self.alloc(0x200);obj=self.alloc(0x200);self.put(obj,vmt)
  for offset,code in slots.items():self.put(vmt+offset,code)
  return obj
 def text(self,value):
  data=value.encode('utf-16le');require(len(data)<=8192,'String bound')
  if not data:return 0
  a=self.alloc(len(data)+16);self.u.mem_write(a,struct.pack('<HHiI',1200,2,-1,len(data)//2)+data+b'\0\0');return a+12
 def read(self,a):
  if not a:return ''
  n=self.get(a-4);require(n<=4096,'String read bound');return bytes(self.u.mem_read(a,n*2)).decode('utf-16le')
 def attr(self,value,field):
  a=self.obj({0x7c:0x30001020});self.attrs[a]={'field':field,'value':value}
  if type(value) is int:self.put(a+0x88,value)
  return a
 def new_level(self,address=0,value=0,tag=''):
  level=self.obj({0x7c:0x30001030})
  for offset,field,value in ((0x80,'address',address),(0xb0,'value',value),(0x9c,'tag',tag)):
   self.put(level+offset,self.attr(value,field))
  return level
 def state(self):
  return {'lock':self.get(self.project+0xc8),'pending':bool(self.u.mem_read(self.project+0xcd,1)[0]),
   'levels':[{'identity':hex(l),'address':self.attrs[self.get(l+0x80)]['value'],'value':self.attrs[self.get(l+0xb0)]['value'],'tag':self.attrs[self.get(l+0x9c)]['value'],'manager_identity':hex(self.get(l+0x94))} for l in self.levels],
   'level_save_attempts':self.level_attempts,'level_save_completed':self.level_completed,
   'storage_attempts':self.storage_attempts,'storage_completed':self.storage_completed,'project_requests':self.project_requests}
 def record(self,event,**value):
  require(len(self.events)<100000,'Event/callback bound');self.events.append({'event':event,**value})
 def write_guard(self,u,access,address,size,value,_):
  require((0<=address and address+size<=4096) or (0x10000000<=address and address+size<=0x10800000) or (0x20000000<=address and address+size<=0x20040000),'Original write outside owned fixture')
 def ret(self,pop=0):
  esp=self.u.reg_read(ESP);self.u.reg_write(EIP,self.get(esp));self.u.reg_write(ESP,esp+4+pop)
 def hook(self,u,address,size,_):
  self.instructions+=1;require(self.instructions<=5000000,'Instruction limit')
  eax,edx,ecx,esp=(u.reg_read(r) for r in (EAX,EDX,ECX,ESP));pop=0
  if address in RTL:
   self.record('rtl',name=RTL[address])
   if address==0x60890c:pass
   elif address==0x608924:self.put(eax,edx)
   elif address==0x608914:self.put(eax,0)
   elif address==0x60891c:
    require(edx<=8,'Clear bound')
    for i in range(edx):self.put(eax+4*i,0)
   elif address==0x608d48:self.put(eax,self.text(self.read(self.get(eax))+self.read(edx)))
   elif address==0x608eec:
    require(edx==4,'Concat arity');self.put(eax,self.text(''.join(self.read(self.get(esp+4*i)) for i in range(edx,0,-1))));pop=edx*4
   elif address==0x609114:
    value=self.read(eax);require(1<=edx<=4096 and ecx<=4096,'Copy bounds')
    self.put(self.get(esp+4),self.text(value[edx-1:edx-1+ecx]));pop=4
   elif address in (0x62f578,0x62f294):
    value=self.read(edx) if address==0x62f578 else edx
    if address==0x62f294:require((ecx&255)==252 and edx<=31,'Integer variant domain')
    self.variants[eax]=value
   elif address==0x629f1c:self.variants.pop(eax,None)
   elif address==0x61b6e8:
    require(self.read(eax)=='%s %d' and ecx==1,'Format fixture domain')
    require(self.u.mem_read(edx+4,1)[0]==17 and self.u.mem_read(edx+12,1)[0]==0,'Format TVarRec types')
    value=self.read(self.get(edx))+' '+str(self.get(edx+8));self.put(self.get(esp+4),self.text(value));pop=4
  elif address in PROVIDERS:
   name=PROVIDERS[address]
   if address==0xf2fff8:require(eax==self.unit,'Foreign unit');u.reg_write(EAX,self.network)
   elif address==0xf2b260:require(eax==self.network,'Foreign network');u.reg_write(EAX,self.project)
   elif address==0xf26e28:require(eax in self.levels and self.get(eax+0x94)==self.manager,'Foreign level');u.reg_write(EAX,self.group)
   elif address==0xf27efc:require(eax==self.group,'Foreign group');u.reg_write(EAX,self.application)
   elif address==0xf260b4:require(eax==self.application,'Foreign application');u.reg_write(EAX,self.network)
   elif address==0x7ea9dc:require(eax==self.group,'Workspace owner');u.reg_write(EAX,self.workspace)
   elif address==0x7ea6ac:
    require(eax==self.image.word(0xf237a4) and (edx&255)==1 and ecx==self.workspace,'Constructor identity')
    require(self.get(esp+4)==0 and self.get(esp+8)==1,'Constructor flags')
    level=self.new_level();u.reg_write(EAX,level);pop=8;self.record('fixture_constructor',identity=hex(level))
   elif address in (0x7e8f74,0x30001000,0x30001010):
    require(eax==self.manager,'Collection owner')
    if address==0x7e8f74:require(edx<len(self.levels),'Collection index');u.reg_write(EAX,self.levels[edx])
    elif address==0x30001000:u.reg_write(EAX,len(self.levels))
    else:require(edx not in self.levels and len(self.levels)<64,'Collection add');self.levels.append(edx)
   elif address==0x30001020:
    require(eax in self.attrs and edx in self.variants,'Attribute owner/value')
    value=self.variants[edx];field=self.attrs[eax]['field'];require(type(value) is (str if field=='tag' else int),'Attribute type')
    self.attrs[eax]['value']=value
    if field=='address':self.put(eax+0x88,value)
    self.record('attribute_set',attribute=hex(eax),field=field,value=value)
   elif address==0x30001030:
    require(eax in self.levels,'Level save owner');self.level_attempts+=1
    self.record('level_save_requested',identity=hex(eax),state=self.state())
    if self.level_attempts==self.case.get('deny_level_save'):raise ProviderDenied('Owned level-save provider denied')
    self.level_completed+=1
   elif address==0x7f3f28:
    require(eax==self.project and self.read(edx)=='ProjectSave' and self.read(self.get(ecx))=='ProjectSave' and self.get(esp+4)==0,'Storage filter domain')
    u.reg_write(EAX,int(self.case.get('defer_save',True)));pop=4
    self.record('storage_filter',defer=self.case.get('defer_save',True),state=self.state())
   elif address==0x7f409c:
    require(eax==self.project and self.read(self.get(edx))=='ProjectSave' and ecx==0,'Storage provider domain')
    self.storage_attempts+=1;self.record('storage_requested',state=self.state())
    if self.storage_attempts==self.case.get('deny_storage_save'):raise ProviderDenied('Owned storage provider denied')
    self.storage_completed+=1
   else:raise HarnessError('Unknown fixture provider')
  else:
   item=self.image.instructions.get(address);require(item is not None,'Unapproved instruction '+hex(address))
   name,raw=item;require(bytes(u.mem_read(address,len(raw)))==raw,'Changed original code')
   require(not 0x1130aa0<=address<0x1130ad1,'Original exception handler not admitted')
   if address==0xf2dac8:
    require(eax==self.project,'ProjectSave owner');self.project_requests+=1;self.record('project_save_entry',state=self.state())
   if address in (0xf2d370,0xf2d384):self.record(name+'_entry',state=self.state())
   if address==0xf2742c:self.record('find_level_entry',address=edx,create=bool(ecx&255),state_count=len(self.levels))
   self.executed[name]=self.executed.get(name,0)+1;return
  self.ret(pop)
 def call(self,address,eax,edx=0,ecx=0):
  self.put(0,0);self.put(0x20030000,0x30000000)
  for reg,value in ((ESP,0x20030000),(EAX,eax),(EDX,edx),(ECX,ecx),(FLAGS,2)):self.u.reg_write(reg,value)
  self.u.emu_start(address,0x30000000,timeout=3000000,count=5000000)
  require(self.u.reg_read(EIP)==0x30000000,'Original return not reached')
  require(self.u.reg_read(ESP)==0x20030004,'Original return stack balance')
  require(self.get(0)==0,'Original normal return must restore SEH word')
 def evidence(self):return {'state':self.state(),'events':self.events,'executed_original':self.executed,'instructions':self.instructions,'heap_bytes':self.heap-0x10000000}

def validate(case):
 require(type(case) is dict and type(case.get('id')) is str and 0<len(case['id'])<=80,'Case identity')
 require(case.get('kind') in ('zones','create') and type(case.get('expected')) is dict,'Case type')
 if case['kind']=='zones':
  require(set(case)=={'id','kind','levels','expected'} and case['levels']==list(range(1,32)),'Standalone zone domain')
 else:
  require(set(case)=={'id','kind','actions','existing','initial_lock','initial_pending','defer_save','release_outer_locks','deny_level_save','deny_storage_save','expected'},'Create schema')
  require(type(case['actions']) is list and 1<=len(case['actions'])<=3 and all(a in ACTION for a in case['actions']),'Actions')
  require(type(case['existing']) is list and len(case['existing'])<=31,'Existing bound')
  ids=[]
  for level in case['existing']:
   require(type(level) is dict and set(level)=={'address','value','tag'},'Existing schema')
   require(type(level['address']) is int and 1<=level['address']<=31 and type(level['value']) is int and 0<=level['value']<=255,'Existing numbers')
   require(type(level['tag']) is str and len(level['tag'])<=128 and '\0' not in level['tag'],'Existing label')
   ids.append(level['address'])
  require(len(set(ids))==len(ids),'Existing addresses unique')
  require(type(case['initial_lock']) is int and 0<=case['initial_lock']<=2,'Initial lock')
  require(type(case['initial_pending']) is bool and type(case['release_outer_locks']) is bool and case['defer_save'] is True,'Lock/filter facts')
  for key in ('deny_level_save','deny_storage_save'):
   require(case[key] is None or type(case[key]) is int and 1<=case[key]<=64,'Denial ordinal')
  require(not (case['deny_level_save'] and case['deny_storage_save']),'One denied provider')

def run_case(image,case,row):
 machine=Machine(image,case);row.update({'id':case['id'],'completed':False,'original_exception_unwind_executed':False,'phases':[]});primary=None
 try:
  if case['kind']=='zones':
   labels={}
   for value in case['levels']:
    dest=machine.alloc(4);machine.call(0xfda610,value,dest);labels[str(value)]=machine.read(machine.get(dest))
   row['labels']=labels;require(labels==case['expected']['labels'],'Independent zone label mismatch')
  else:
   row['initial_state']=machine.state()
   for action in case['actions']:
    machine.call(0x1130944,machine.form,machine.group,ACTION[action]);row['phases'].append({'action':action,'returned':True,'state':machine.state()})
   if case['release_outer_locks']:
    for _ in range(case['initial_lock']):
     machine.call(0xf2d384,machine.project);row['phases'].append({'action':'explicit-owned-outer-EndSaveLock','returned':True,'state':machine.state()})
   expected=case['expected'];state=machine.state()
   require(expected['completed'],'Expected denial did not occur')
   values=[{k:v for k,v in l.items() if k in ('address','value','tag')} for l in state['levels']]
   values.sort(key=lambda l:l['address'])
   require(values==expected['final_levels'],'Final retained levels differ')
   require(all(l in machine.levels for l in machine.initial_ids),'Existing identity changed')
   for field,actual in (('created',len(machine.levels)-len(machine.initial_ids)),('level_saves',machine.level_completed),('storage_saves',machine.storage_completed),('project_requests',machine.project_requests),('final_lock',state['lock']),('final_pending',state['pending'])):
    require(actual==expected[field],field+' expectation mismatch')
   # Each newly created level is first saved with FindLevel's default label,
   # then with CreateLevels' final label; existing values never enter this path.
   saved=[e for e in machine.events if e['event']=='level_save_requested']
   for index in range(0,len(saved),2):
    first,second=saved[index:index+2];require(first['identity']==second['identity'],'Save identity/order')
    identity=first['identity'];a=next(l for l in first['state']['levels'] if l['identity']==identity)
    b=next(l for l in second['state']['levels'] if l['identity']==identity)
    require(a['tag']=='Level '+str(a['address']) and a['value']==a['address'],'Original default label/value phase')
    require(b['tag'].startswith('Sched '+case['actions'][0]+' '),'Original retag phase')
  row['completed']=True;row['matched_expected']=True
 except ProviderDenied as error:
  primary=error;row['provider_denial']=error_dict(error)
  require(case['kind']=='create' and not case['expected']['completed'],'Unexpected provider denial')
  state=machine.state()
  if case['deny_storage_save'] is not None:
   require(state['lock']==0 and state['pending'] and len(machine.levels)==31 and machine.level_completed==62 and machine.storage_attempts==1 and machine.storage_completed==0,'Denied final storage prefix')
  else:
   require(state['lock']==1 and state['pending'] and len(machine.levels)==2 and machine.level_attempts==3 and machine.level_completed==2 and machine.storage_attempts==0,'Denied level-save prefix')
   require(state['levels'][0]['tag'].startswith('Sched Enable ') and state['levels'][1]['tag']=='Level 2','Denied level labels')
  row['matched_expected']=True
 except BaseException as error:
  primary=error;row['error']=error_dict(error);raise
 finally:
  try:row.update(machine.evidence())
  except BaseException as error:
   row['matched_expected']=False;row['evidence_error']=error_dict(error)
   if primary is not None:raise BaseException.with_traceback(primary,primary.__traceback__)
   raise
 return row

def runtime_evidence():
 from unicorn.unicorn_py3 import unicorn as core
 import os,stat
 def hashed(path):
  fd=os.open(path,os.O_RDONLY|os.O_NONBLOCK|os.O_NOFOLLOW);first=None;h=hashlib.sha256();size=0
  try:
   st=os.fstat(fd);require(stat.S_ISREG(st.st_mode) and st.st_size<=64*1024*1024,'Runtime regular bound')
   while True:
    raw=os.read(fd,65536)
    if not raw:break
    size+=len(raw);require(size<=64*1024*1024,'Runtime grew');h.update(raw)
   return h.hexdigest()
  except BaseException as error:first=error;raise
  finally:
   try:os.close(fd)
   except BaseException:
    if first is None:raise
 libraries={str(Path(p).resolve()):hashed(Path(p).resolve()) for p in (capstone._cs._name,core.uclib._name)}
 require(set(libraries.values())=={'016084c6e70d929249a2abb22f1afda95095294e6cd70f509964ffc54006bf94','7207c8e3d7a63118fb0bca73e01816797fd51b1d8a39a4cbc7abfd562ee59c85'},'Accepted native emulation library hashes')
 modules={name:{'path':str(Path(m.__file__).resolve()),'sha256':hashed(Path(m.__file__).resolve())} for name,m in list(sys.modules.items()) if name.split('.')[0] in ('capstone','unicorn','pefile') and getattr(m,'__file__','').endswith('.py')}
 executable=Path(sys.executable).resolve()
 return {'python':sys.version,'executable':str(executable),'executable_sha256':hashed(executable),'libraries':libraries,'loaded_python_modules':modules}

def main():
 require(len(sys.argv)==5 and sys.argv[1]=='root-reviewed-thermostat-levels-pilot-v1','Reviewed execution release required')
 case_path=Path(sys.argv[2]);out=Path(sys.argv[3]);exe=Path(sys.argv[4])
 raw=bounded_read(case_path,256*1024);cases=json.loads(raw)
 require(type(cases) is list and len(cases)==12,'Exact pilot12')
 for case in cases:validate(case)
 require(len({c['id'] for c in cases})==12,'Unique IDs')
 image=Image(exe);out.mkdir(exist_ok=False)
 report={'format':'thermostat-levels-original-pilot-v1','passed':False,'python':sys.version,'cases_sha256':digest(raw),'probe_sha256':digest(bounded_read(Path(__file__),1024*1024)),'exe_sha256':digest(image.raw),'spans':image.spans,'results':[],
  'scope':{'original_constructor_executed':False,'explicit_owned_constructor_provider':True,'original_methods_unchanged':True,'string_variant_collection_storage_providers_are_fixtures':True,'native_storage_performed':False,'original_exception_unwind_executed':False,'network':False,'registry':False,'ui':False,'pe_entrypoint':False}}
 primary=None;started=time.monotonic()
 try:
  report['runtime_before']=runtime_evidence()
  for case in cases:
   require(time.monotonic()-started<60,'Pilot wall bound');row={'id':case['id'],'started':True};report['results'].append(row);run_case(image,case,row)
  report['passed']=all(r['matched_expected'] for r in report['results'])
 except BaseException as error:primary=error;report['error']=error_dict(error);raise
 finally:
  report['source_after']={};report['source_postcheck_errors']=[]
  for name,path,limit in (('cases_sha256',case_path,256*1024),('probe_sha256',Path(__file__),1024*1024),('exe_sha256',exe,64*1024*1024)):
   try:
    report['source_after'][name]=digest(bounded_read(path,limit))
    require(report['source_after'][name]==report[name],'Child source changed: '+name)
   except BaseException as error:
    report['passed']=False;report['source_postcheck_errors'].append({'input':name,**error_dict(error)})
    if primary is None:primary=error
  try:
   report['runtime_after']=runtime_evidence()
   require(report.get('runtime_before')==report['runtime_after'],'Child actual runtime changed')
  except BaseException as error:
   report['passed']=False;report['runtime_postcheck_error']=error_dict(error)
   if primary is None:primary=error
  try:
   report['elapsed_seconds']=time.monotonic()-started
   stream=(out/'report.json').open('x');first=None
   try:
    raw=json.dumps(report,indent=2)+'\n';require(len(raw.encode('utf-8'))<=32*1024*1024,'Report byte bound');stream.write(raw)
   except BaseException as error:first=error;raise
   finally:
    try:stream.close()
    except BaseException:
     if first is None:raise
  except BaseException:
   if primary is None:raise
 if primary is not None:raise BaseException.with_traceback(primary,primary.__traceback__)
 print(json.dumps({'passed':report['passed'],'cases':len(report['results'])}))

if __name__=='__main__':main()
