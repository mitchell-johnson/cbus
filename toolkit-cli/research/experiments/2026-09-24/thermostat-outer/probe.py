"""Reviewed-source preparation for composed outer thermostat scheduling.

Only prepare mode is permitted before an exact external admission is supplied.
The accepted inner provider helper is reused, never production code as oracle.
"""
from pathlib import Path
import hashlib,importlib.util,json,os,stat,sys,time
BASE=Path(__file__).resolve().parent
PRIOR=Path('/Volumes/external/cbus-toolkit-research-20260915-thermostat-levels/pilot-313-v2/probe.py')
PRIOR_SHA='b963686614a715b8ca3d5b95da1ff1897318196c76d4228932b703530db52537'
EXE=Path('/Users/mitchell/source/cbus/toolkit-cli/research/vendor/toolkit/app/CBusToolkit.exe')
MAP=EXE.with_suffix('.map')
TOKEN='root-reviewed-thermostat-outer12-v1'
def sha(raw):return hashlib.sha256(raw).hexdigest()
def check(value,message):
 if not value:raise RuntimeError(message)
def read(path,limit=64*1024*1024):
 fd=os.open(path,os.O_RDONLY|os.O_NONBLOCK|os.O_NOFOLLOW);first=None
 try:
  info=os.fstat(fd);check(stat.S_ISREG(info.st_mode) and info.st_size<=limit,'Bounded regular input');parts=[];size=0
  while size<=limit:
   raw=os.read(fd,min(65536,limit+1-size))
   if not raw:break
   parts.append(raw);size+=len(raw)
  check(size<=limit,'Input grew beyond limit');return b''.join(parts)
 except BaseException as error:first=error;raise
 finally:
  try:os.close(fd)
  except BaseException:
   if first is None:raise
def load_prior():
 raw=read(PRIOR,1024*1024);check(sha(raw)==PRIOR_SHA,'Accepted helper source changed')
 spec=importlib.util.spec_from_file_location('outer_owned_inner',PRIOR);m=importlib.util.module_from_spec(spec);exec(compile(raw,str(PRIOR),'exec'),m.__dict__);return m
EXTRA=(('Button',0x112fad4,0x112fafb),('Required',0xfed2d4,0xfed3c3),('ZoneLevels',0xfda7a4,0xfda7ff),('IsUnused',0xf27e14,0xf27e35),
 ('Outer',0x1130704,0x113086b),('OnWrapper',0x113086c,0x1130895),('OffWrapper',0x11308b4,0x11308dd),('OverrideWrapper',0x11308fc,0x1130925),
 ('GetZoneManager',0xfea78c,0xfea7b0),('GetOn',0xfe0040,0xfe0064),('GetOff',0xfe001c,0xfe0040),('GetOverride',0xfdfff8,0xfe001c),
 ('GetEnable',0xfdffd4,0xfdfff8),('BooleanGetter',0x7f43d8,0x7f43f9),('ObjectGetter',0x7de538,0x7de5e9),
 ('ReferenceAttributeGetter',0x7dda60,0x7dda86),('CustomObjectGetter',0x7dd428,0x7dd445),('ReferenceGetter',0x7ed3a0,0x7ed3c1),('ResolveReference',0x7ed41c,0x7ed531))
ROLES={0xfe0040:'on',0xfe001c:'off',0xfdfff8:'override'}
WRAPPERS={0x113086c:('on','Enable'),0x11308b4:('off','Disable'),0x11308fc:('override','Overrd')}
RETURNS={0x1130892:'on',0x11308da:'off',0x1130922:'override'}
def image(m):
 # Only add separately decoded exact spans to this in-memory helper instance.
 m.RANGES=m.RANGES+EXTRA
 return m.Image(EXE)
def validate(cases):
 check(type(cases) is list and len(cases)==12,'Exactly twelve cases')
 check([c.get('id') for c in cases if type(c) is dict]==[f'O{i:02}' for i in range(1,13)],'Exact ordered IDs')
 for c in cases:
  check(set(c)=={'id','entry','enabled','groups','roles','initial_lock','initial_pending','release_lock','deny_level_save','deny_storage_save','expected'},'Exact case schema')
  check(c['entry'] in ('button','direct') and type(c['enabled']) is bool,'Entry/enable')
  check(type(c['groups']) is list and len(c['groups'])<=3,'Group count');ids=[]
  for g in c['groups']:
   check(type(g) is dict and set(g)=={'identity','address','levels'},'Group schema');check(g['identity'] in ('A','B','C','U') and g['identity'] not in ids,'Unique group identity');ids.append(g['identity'])
   check(type(g['address']) is int and 0<=g['address']<=255,'Group address');check(type(g['levels']) is list and len(g['levels'])<=64,'Level bound');addresses=[]
   for l in g['levels']:
    check(type(l) is dict and set(l)=={'address','value','tag'},'Level schema')
    check(all(type(l[k]) is int and 0<=l[k]<=255 for k in ('address','value')),'Level bytes')
    check(l['address'] not in addresses,'Unique addresses');addresses.append(l['address'])
    check(type(l['tag']) is str and len(l['tag'])<=128 and l['tag'].isascii() and '\0' not in l['tag'],'Tag domain')
  check(type(c['roles']) is dict and list(c['roles'])==['on','off','override'] and all(v is None or v in ids for v in c['roles'].values()),'Exact role references')
  check(type(c['initial_lock']) is int and c['initial_lock'] in (0,1),'Lock');check(type(c['initial_pending']) is bool and type(c['release_lock']) is bool,'Pending/release')
  check(not c['release_lock'] or c['initial_lock']==1,'Release existing outer lock')
  for k in ('deny_level_save','deny_storage_save'):check(c[k] is None or type(c[k]) is int and 1<=c[k]<=200,'Denial ordinal')
  check(not(c['deny_level_save'] and c['deny_storage_save']),'One denial');check(type(c['expected']) is dict,'Expected facts')
def machine_type(m):
 class Machine(m.Machine):
  def __init__(self,img,c):
   super().__init__(img,{'existing':[],'initial_lock':c['initial_lock'],'initial_pending':c['initial_pending'],'defer_save':True,'deny_level_save':c['deny_level_save'],'deny_storage_save':c['deny_storage_save']})
   self.input=c;self.trace=[];self.groups={};self.group_names={};self.collections={};self.manager_group={};self.level_owner={};self.pending_created=set();self.refs={};self.object_attrs=set();self.cursor=None;self.delay=False;self.active_role=None;self.invocations=0
   for data in c['groups']:
    g=self.obj({});manager=self.obj({0x58:0x30001000,0x68:0x30001010});self.groups[data['identity']]=g;self.group_names[g]=data['identity'];self.manager_group[manager]=g;self.collections[manager]=[]
    self.put(g+0xd0,manager);self.put(manager+0x30,g);self.put(g+0x80,self.attr(data['address'],'address'))
    for l in data['levels']:
     obj=self.new_level(l['address'],l['value'],l['tag']);self.put(obj+0x94,manager);self.collections[manager].append(obj);self.levels.append(obj);self.level_owner[obj]=g
   self.initial_ids=list(self.levels);self.initial_levels={l:self.level(l) for l in self.levels}
   self.service=self.obj({});self.service_attribute=self.reference_attr(self.service,True);self.put(self.unit+0x1a4,self.service_attribute)
   self.role_attrs={}
   for role,offset in (('on',0xe8),('off',0xec),('override',0xf0)):
    attr=self.reference_attr(self.groups.get(c['roles'][role],0),False);self.role_attrs[role]=attr;self.put(self.service+offset,attr)
   self.enable_attr=self.obj({0x24:0x30001100,0x88:0x7f43d8});self.u.mem_write(self.enable_attr+0x70,bytes([c['enabled']]));self.put(self.service+0xf4,self.enable_attr)
   self.screen=self.obj({});self.app_manager=self.obj({});self.facade=self.obj({});self.delay_owner=self.obj({});self.put(self.facade+4,self.app_manager);self.put(self.form+0x2c,self.delay_owner)
   self.global_patches={self.image.word(0x13c4080):self.screen,self.image.word(0x13c1bc8):self.facade}
   for address,value in self.global_patches.items():self.put(address,value)
   self.resources={self.image.word(0x13c1ce0):('message','owned message fixture'),self.image.word(0x13c1b30):('title','owned title fixture')}
  def reference_attr(self,target,owned):
   attr=self.obj({0x24:0x30001100,0xa4:0x7de538 if owned else 0x7dda60});ref=self.obj({});self.put(ref+0x18,target);self.put(attr+0x78,ref);self.refs[ref]=target;self.object_attrs.add(attr);return attr
  def event(self,event,**kw):check(len(self.trace)<300000,'Workflow trace bound');self.trace.append({'event':event,**kw})
  def level(self,l):return {k:self.attrs[self.get(l+offset)]['value'] for k,offset in (('address',0x80),('value',0xb0),('tag',0x9c))}
  def state(self):
   return {'groups':[{'identity':name,'address':self.attrs[self.get(g+0x80)]['value'],'levels':[self.level(l) for l in self.collections[self.get(g+0xd0)]]} for name,g in self.groups.items()],
    'lock':self.get(self.project+0xc8),'pending':bool(self.u.mem_read(self.project+0xcd,1)[0]),'level_attempts':self.level_attempts,'level_completed':self.level_completed,'storage_attempts':self.storage_attempts,'storage_completed':self.storage_completed,'project_requests':self.project_requests,'cursor':self.cursor,'delay_active':self.delay}
  def hook(self,u,address,size,user):
   eax,edx,ecx,esp=(u.reg_read(r) for r in (m.EAX,m.EDX,m.ECX,m.ESP));caller=self.get(esp)
   modified={0xf26e28,0xf27efc,0x7ea9dc,0x7ea6ac,0x7e8f74,0x30001000,0x30001010,0x30001030,0x7f409c,0x30001100,0x60bca4,0x723264,0x60c470,0xf0ffa0,0xf0ff20}
   if address in modified:
    self.instructions+=1;check(self.instructions<=5000000,'Instruction limit');pop=0
    if address==0xf26e28:
     check(eax in self.level_owner and self.manager_group[self.get(eax+0x94)]==self.level_owner[eax],'Level owner');u.reg_write(m.EAX,self.level_owner[eax])
    elif address==0xf27efc:check(eax in self.group_names,'Group owner');u.reg_write(m.EAX,self.application)
    elif address==0x7ea9dc:check(eax in self.group_names,'Workspace owner');u.reg_write(m.EAX,self.workspace)
    elif address==0x7ea6ac:
     check(eax==self.image.word(0xf237a4) and edx&255==1 and ecx==self.workspace and self.get(esp+4)==0 and self.get(esp+8)==1,'Owned level constructor');check(not self.pending_created,'One pending created object');l=self.new_level();self.pending_created.add(l);u.reg_write(m.EAX,l);pop=8
    elif address in (0x7e8f74,0x30001000,0x30001010):
     check(eax in self.collections,'Manager identity');collection=self.collections[eax]
     if address==0x7e8f74:check(edx<len(collection),'Collection index');u.reg_write(m.EAX,collection[edx])
     elif address==0x30001000:u.reg_write(m.EAX,len(collection))
     else:
      check(edx in self.pending_created and edx not in self.level_owner and len(collection)<64,'Owned collection addition');self.pending_created.remove(edx);collection.append(edx);self.levels.append(edx);self.level_owner[edx]=self.manager_group[eax]
    elif address==0x30001030:
     check(eax in self.level_owner,'Save owner');self.level_attempts+=1;self.event('level_save',group=self.group_names[self.level_owner[eax]],**self.level(eax));self.record('level_save_requested',identity=hex(eax),state=self.state())
     if self.level_attempts==self.case['deny_level_save']:raise m.ProviderDenied('Owned level-save boundary')
     self.level_completed+=1
    elif address==0x7f409c:
     check(eax==self.project and self.read(self.get(edx))=='ProjectSave' and ecx==0,'Storage call');self.storage_attempts+=1;self.event('storage');self.record('storage_requested',state=self.state())
     if self.storage_attempts==self.case['deny_storage_save']:raise m.ProviderDenied('Owned storage boundary')
     self.storage_completed+=1
    elif address==0x30001100:
     check((eax in self.object_attrs and caller==0x7dd439) or (eax==self.enable_attr and caller==0x7f43e9),'Initialized-only attribute provider')
    elif address==0x60bca4:check(caller==0x7ed524 and 0x20000000<=eax<0x20040000 and self.get(eax)==0,'Nil-only interface cleanup')
    elif address==0x723264:
     value=edx&65535;value=value-65536 if value>=32768 else value
     check(eax==self.screen and (caller,value) in ((0x113072e,-11),(0x113083d,0)),'Exact cursor request');self.cursor=value;self.event('cursor',value=value)
    elif address==0x60c470:
     check(eax in self.resources and caller in (0x1130742,0x1130753) and 0x20000000<=edx<0x20040000,'Exact resource fixture');which,text=self.resources[eax];check((caller,which) in ((0x1130742,'message'),(0x1130753,'title')),'Resource call association');self.put(edx,self.text(text));self.event('resource',which=which)
    elif address==0xf0ffa0:
     check(caller==0x1130766 and eax==self.app_manager and self.read(edx)=='owned title fixture' and self.read(ecx)=='owned message fixture' and self.get(esp+4)==self.delay_owner and not self.delay,'Exact delay request');self.delay=True;self.event('delay_begin');pop=4
    elif address==0xf0ff20:check(caller==0x113082f and eax==self.app_manager and self.delay,'Exact delay finish');self.delay=False;self.event('delay_finish')
    self.ret(pop);return
   if address in m.RTL or address in m.PROVIDERS:return super().hook(u,address,size,user)
   self.instructions+=1;check(self.instructions<=5000000,'Instruction limit');item=self.image.instructions.get(address);check(item is not None,'Unapproved original '+hex(address));name,raw=item;check(bytes(u.mem_read(address,len(raw)))==raw,'Original bytes changed');check(not 0x1130aa0<=address<0x1130ad1,'Original exception handler excluded')
   if address==0x7de538:check(eax in self.object_attrs and self.u.mem_read(eax+0x80,1)==b'\0','Resolved object attribute only')
   if address==0x7ed41c:check(eax in self.refs and self.u.mem_read(eax+0x40,1)==b'\0' and self.get(eax+0x18)==self.refs[eax],'Resolved stable reference only')
   if address==0x112fad4:self.event('button')
   if address==0xfed2d4:self.event('required')
   if address==0xfea78c:check(eax==self.unit,'Original service receiver');self.event('get_service')
   if address==0xfdffd4:check(eax==self.service,'Original enable receiver');self.event('get_enable',value=self.input['enabled'])
   if address in ROLES:check(eax==self.service,'Original role receiver');role=ROLES[address];self.event('get_role',role=role,group=self.input['roles'][role])
   if address==0xf27e14:check(eax in self.group_names,'Unused receiver');self.event('is_unused',group=self.group_names[eax])
   if address==0xfda7a4:check(eax in self.group_names,'Zone receiver');self.event('zone_levels',group=self.group_names[eax])
   if address==0x1130704:self.event('outer')
   if address in WRAPPERS:self.active_role=WRAPPERS[address][0];self.event('wrapper',role=self.active_role)
   if address==0x1130944:
    check(eax==self.form and edx in self.group_names and self.input['roles'][self.active_role]==self.group_names[edx],'Actual wrapper group');action=dict((r,a) for r,a in WRAPPERS.values())[self.active_role];check(self.read(ecx)==action,'Actual wrapper literal');self.event('inner',role=self.active_role,group=self.group_names[edx],action=action)
   if address in RETURNS:
    role=RETURNS[address];self.event('inner_return',role=role,group=self.input['roles'][role])
   if address==0xf2742c:
    check(eax in self.collections and 1<=edx<=31 and ecx&255 in (0,1) and self.get(esp+4)==0,'Actual FindLevel arguments');self.event('find',group=self.group_names[self.manager_group[eax]],address=edx,create=bool(ecx&255))
   if address==0xf2dac8:check(eax==self.project,'Project identity');self.project_requests+=1;self.record('project_save_entry',state=self.state())
   if address in (0xf2d370,0xf2d384):self.record(name+'_entry',state=self.state())
   self.executed[name]=self.executed.get(name,0)+1
  def call(self,address,eax):
   self.put(0,0);self.put(0x20030000,0x30000000)
   for reg,value in ((m.ESP,0x20030000),(m.EAX,eax),(m.EDX,0),(m.ECX,0),(m.FLAGS,2)):self.u.reg_write(reg,value)
   self.invocations+=1;self.u.emu_start(address,0x30000000,timeout=15000000,count=5000000)
   check(self.u.reg_read(m.EIP)==0x30000000 and self.u.reg_read(m.ESP)==0x20030004 and self.get(0)==0,'Original normal return/stack/SEH')
  def evidence(self):
   return {'state':self.state(),'trace':self.trace,'events':self.events,'executed_original':self.executed,'instructions':self.instructions,'original_entries':sum(self.executed.values()),'invocations_attempted':self.invocations,'group_objects':{k:hex(v) for k,v in self.groups.items()},'level_objects':{hex(l):{'group':self.group_names[g],'manager':hex(self.get(l+0x94)),**self.level(l)} for l,g in self.level_owner.items()},'global_patches':{hex(k):hex(v) for k,v in self.global_patches.items()},'original_exception_unwind_executed':False}
 return Machine
def compare(row,c):
 expected=c['expected'];check(row['completed']==expected['completed'],'Completion hypothesis')
 check(row['trace']==expected['trace'],'Ordered complete workflow hypothesis')
 check(row['state']=={k:v for k,v in expected.items() if k not in ('completed','trace')},'Retained state/counter hypothesis')
def run_case(m,Machine,img,c,row):
 row.update(id=c['id'],case=c,completed=False);machine=Machine(img,c);first=None
 try:
  machine.call(0x112fad4 if c['entry']=='button' else 0x1130704,machine.form)
  if c['release_lock']:machine.event('explicit_unlock');machine.call(0xf2d384,machine.project)
  row['completed']=True
 except m.ProviderDenied as error:
  first=error;row['provider_denial']=m.error_dict(error)
  check(c['deny_level_save'] is not None or c['deny_storage_save'] is not None,'Unplanned denial')
 except BaseException as error:first=error;raise
 finally:
  row['original_entries']=sum(machine.executed.values());row['invocations_attempted']=machine.invocations
  try:row.update(machine.evidence())
  except BaseException:
   if first is not None:raise first
   raise
 check(all(machine.level(l)==before and l in machine.level_owner for l,before in machine.initial_levels.items()),'Existing level object/value/tag retention')
 compare(row,c);row['matched_expected']=True

def main():
 check(sys.version_info[:2] in ((3,10),(3,13)),'Supported runtime');check(len(sys.argv)==4 and sys.argv[1] in ('prepare','execute'),'Mode/output/source-directory')
 mode,out,source=sys.argv[1],Path(sys.argv[2]),Path(sys.argv[3]).resolve();check(source==BASE,'Own exact source directory');check(out.parent.resolve()==BASE and not out.exists() and not out.is_symlink(),'Fresh direct output')
 raw=read(BASE/'cases.json',256*1024);cases=json.loads(raw);validate(cases);before={str(p):sha(read(p)) for p in (Path(__file__),BASE/'cases.json',PRIOR,EXE,MAP)}
 if mode=='execute':
  admission=json.loads(read(BASE/'admission.json',4096));check(admission=={'release':TOKEN,'probe_sha256':before[str(Path(__file__))],'cases_sha256':sha(raw)},'Reviewed exact execution admission')
 m=load_prior();img=image(m);out.mkdir();report={'format':'thermostat-outer-original12-v1','passed':False,'preparation_complete':False,'original_requested':mode=='execute','original_executed':False,'inputs_before':before,'results':[],'spans':img.spans,'runtime_before':m.runtime_evidence()};first=None
 try:
  if mode=='prepare':report['preparation_complete']=True
  else:
   Machine=machine_type(m);started=time.monotonic()
   for c in cases:
    check(time.monotonic()-started<180,'Batch deadline');row={'id':c['id']};report['results'].append(row);run_case(m,Machine,img,c,row);check(time.monotonic()-started<180,'Post-case batch deadline')
   report['passed']=True
 except BaseException as error:first=error;report['error']=m.error_dict(error)
 finally:
  report['original_executed']=any(r.get('original_entries',0)>0 for r in report['results']);report['secondary_errors']=[]
  def attempt(label,operation):
   nonlocal first
   try:return operation()
   except BaseException as error:
    report['secondary_errors'].append({'phase':label,**m.error_dict(error)});report['passed']=False;report['preparation_complete']=False
    if first is None:first=error
  report['inputs_after']={p:attempt('hash '+p,lambda p=p:sha(read(Path(p)))) for p in before};attempt('source equality',lambda:check(before==report['inputs_after'],'Source changed'))
  report['runtime_after']=attempt('runtime',m.runtime_evidence);attempt('runtime equality',lambda:check(report['runtime_after']==report['runtime_before'],'Runtime changed'))
  body=attempt('report encoding',lambda:(json.dumps(report,indent=2)+'\n').encode());stream=None
  if body is not None:
   attempt('report bound',lambda:check(len(body)<=64*1024*1024,'Report size'))
   try:stream=(out/'report.json').open('xb');stream.write(body);stream.flush();os.fsync(stream.fileno())
   except BaseException as error:
    if first is None:first=error
   finally:
    if stream is not None:attempt('report close',stream.close)
 if first is not None:raise first
 print(json.dumps({'passed':report['passed'],'preparation_complete':report['preparation_complete'],'original_executed':report['original_executed']}))
if __name__=='__main__':main()
