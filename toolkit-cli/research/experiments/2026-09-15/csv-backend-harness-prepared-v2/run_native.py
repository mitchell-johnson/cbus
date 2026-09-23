"""Held four-fixture C-Gate capture. No original Toolkit execution in this process.

The native input-capture stage is separate from subsequent original response
replay/CSV composition. Requires an independently reviewed successful Stage A.
"""
from __future__ import annotations
import hashlib,importlib.util,json,os,re,socket,stat,sys,tempfile,time
from pathlib import Path
from xml.etree import ElementTree as ET
BASE=Path(__file__).resolve().parent;ROOT=Path('/Users/mitchell/source/cbus/toolkit-cli')
TOKEN='b0f8078731a54cc4aa069f00b043d210'

def require(c,m):
 if not c:raise RuntimeError(m)
def digest(b):return hashlib.sha256(b).hexdigest()
def module(path,raw,name):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec)
 exec(compile(raw,str(path),'exec'),m.__dict__);return m

def error_record(e):
 try:message=str(e)
 except BaseException:message='<unprintable>'
 return {'type':type(e).__name__,'message':message[:2048]}

def read(path,limit=64*1024*1024):
 fd=os.open(path,os.O_RDONLY|os.O_NONBLOCK|os.O_NOFOLLOW);first=None
 try:
  info=os.fstat(fd);require(stat.S_ISREG(info.st_mode) and info.st_size<=limit,'Bounded regular input')
  chunks=[];size=0
  while size<=limit:
   chunk=os.read(fd,min(65536,limit+1-size))
   if not chunk:break
   chunks.append(chunk);size+=len(chunk)
  require(size<=limit,'Input grew past bound');return b''.join(chunks)
 except BaseException as e:first=e;raise
 finally:
  try:os.close(fd)
  except BaseException:
   if first is None:raise

def quote(value):
 require(type(value) is str and value.isascii() and all(32<=ord(c)<=126 for c in value),'Fixture PP value')
 return '"'+value.replace('\\','\\\\').replace('"','\\"').replace(' ','\\ ')+'"'


def validate(cases):
 require(type(cases) is list and len(cases)==4,'Four native fixtures')
 for i,c in enumerate(cases,1):
  require(type(c) is dict and set(c)=={'id','project','unit_type','firmware','area','groups','association_reads'},'Exact native schema')
  require(c['id']=='B%02d'%i and c['project']=='CSVBA%02d'%i and c['firmware']=='4.4','Fixed generated identities')
  require(c['unit_type']==('OWNED_UNKNOWN' if i==4 else 'RELAY4'),'Fixed class family')
  require(c['area']==[12,255,13,None][i-1] and (c['area'] is None or type(c['area']) is int),'Exact Area input')
  require(c['groups']==([1,2,3,4,5,6,7,8,12,255] if i==3 else [1,2,3,4,5,6,7,8,12,13,255]) and all(type(x) is int for x in c['groups']),'Exact ordered metadata')
  require(type(c['association_reads']) is bool and c['association_reads']==(i==1),'Fixed association scope')


def xml(reply):
 require(reply.code==344 and reply.lines[0]=='343-Begin XML snippet' and reply.lines[-1]=='344 End XML snippet','Native XML framing')
 require(all(v.startswith('347-') for v in reply.lines[1:-1]),'Native XML rows')
 text='\n'.join(v[4:] for v in reply.lines[1:-1]);require(len(text.encode('utf-8'))<=1024*1024,'XML bound')
 require('<!DOCTYPE' not in text.upper() and '<!ENTITY' not in text.upper(),'No XML external definitions')
 return text

def params(reply):
 require(type(reply.code) is int and reply.code==315 and type(reply.lines) in (list,tuple) and 0<len(reply.lines)<=4096,'Native PP status');result={}
 for index,line in enumerate(reply.lines):
  require(type(line) is str and len(line)<=65536 and line.startswith('315 ' if index==len(reply.lines)-1 else '315-'),'PP continuation status')
  name,sep,value=line[4:].partition('=');require(sep and name and name not in result,'Unique named PP')
  result[name]=value
 return result

class Tap:
 def __init__(self,socket,trace):self.socket=socket;self.trace=trace;self.size=0
 def __getattr__(self,name):return getattr(self.socket,name)
 def record(self,direction,raw):
  require(len(self.trace)<20000,'Wire chunk count bound')
  remaining=max(0,16*1024*1024-self.size)
  row={'direction':direction,'hex':raw[:remaining].hex(),'bytes':len(raw),'truncated':len(raw)>remaining}
  self.trace.append(row);self.size+=len(raw)
  require(not row['truncated'],'Wire byte capture bound');return row
 def recv(self,*a,**k):
  raw=self.socket.recv(*a,**k);self.record('receive',raw);return raw
 def sendall(self,raw,*a,**k):
  row=self.record('send',raw);row['returned']=False
  result=self.socket.sendall(raw,*a,**k);row['returned']=True;return result

class Guard:
 def __init__(self,client,project,sentinel_port,report,deadline):
  self.client=client;self.project=project;self.network='//'+project+'/254';self.unit=self.network+'/p/4'
  self.port=sentinel_port;self.phase='setup';self.rows=report;self.deadline=deadline;self.first=None;self.allowed_oids=set();self.session='CSVSESSION';self.lock='CSVLOCK'
  self.read_parameters={'*','AreaGroupAddress','Application','GroupAddress',*(f'LogicGA{i}Associations' for i in range(6))}
 @property
 def connected(self):return self.client.connected
 def admit(self,command):
  require(type(command) is str and 0<len(command)<=4096 and all(32<=ord(c)<=126 for c in command),'Bounded single ASCII command')
  reads={'PP UNITS','PP LIST_LOCK',f'DBGETXML //{self.project}',f'DBGET {self.unit}',f'GET {self.network} *','PP GET_UNIT_SPEC RELAY4.xml'}
  if command in reads:return
  for target in {self.unit,*(f'//{self.project}/!{oid}' for oid in self.allowed_oids)}:
   if command in {f'pp quickget {target} {p}' for p in self.read_parameters}:return
  require(self.phase=='setup','Mutation excluded from read boundary')
  fixed={f'PROJECT {op} {self.project}' for op in ('NEW','USE','LOAD','SAVE','CLOSE')}
  fixed|={f'DBCREATENET 254 OwnedNet Cni 127.0.0.1:{self.port}','NET LOAD DB',f'DBADDSAFE {self.network} Unit 4 OwnedUnit',f'DBADDSAFE {self.network} Application 56 Lighting',
   f'PP LOCK {self.lock} {self.network}',f'PP START {self.session} {self.lock}',f'PP LOAD {self.session} /db{self.unit}',f'PP RESET_TO_DEFAULTS {self.session}',
   f'PP GET {self.session} *',f'PP SAVE_TO_SOURCE {self.session}',f'PP END {self.session}',f'PP UNLOCK {self.lock}'}
  fixed|={f'DBADDSAFE {self.network}/56 Group {n} '+('<Unused>' if n==255 else f'Group{n}') for n in (1,2,3,4,5,6,7,8,12,13,255)}
  fixed|={f'DBSETSAFE {self.unit}/{name} {value}' for name,values in {'UnitType':['RELAY4','OWNED_UNKNOWN'],'UnitName':['NativeUnit'],'FirmwareVersion':['4.4'],'CatalogNumber':['OWNED'],'SerialNumber':['1.2.3']}.items() for value in values}
  fixed|={f'PP SET {self.session} {name} {quote(value)}' for name,values in {'UnitAddress':['4'],'Application':['56 255'],'AreaGroupAddress':['12','13','255'],'UnitName':['NATUNIT'],'Project':[self.project],'GroupAddress':['1 2 3 4 5 6 7 8 255 255 255 255 255 255 255 255']}.items() for value in values}
  require(command in fixed,'Command outside exact owned grammar: '+command)
 def command(self,command):
  if self.first is not None:raise self.first
  self.admit(command);require(len(self.rows)<512 and time.monotonic()<self.deadline,'Command count/deadline bound')
  row={'phase':self.phase,'command':command,'returned':False};self.rows.append(row)
  try:
   reply=self.client.command(command);row.update(returned=True,code=reply.code,lines=list(reply.lines));return reply
  except BaseException as e:
   self.first=e;row['error']=error_record(e)
   # Diagnostic attributes may themselves raise; never replace the transport error.
   try:
    response=getattr(e,'response',None)
    if response is not None:row.update(code=response.code,lines=list(response.lines))
   except BaseException as secondary:row['diagnostic_error']=error_record(secondary)
   raise
 def success(self,command):
  reply=self.command(command);require(type(reply.code) is int and reply.code==200,'Exact native success required');return reply


def closed(client):
 reply=client.command(f'GET {client.network} *');require(reply.code==300,'Runtime state response');values={}
 for line in reply.lines:
  m=re.fullmatch(r'300[- ]([^:]+): ([^=]+)=(.*)',line);require(m and m[1]==client.network and m[2] not in values,'Runtime property association')
  values[m[2]]=m[3]
 require(values.get('InterfaceState')=='closed' and values.get('TargetInterfaceState')=='closed' and values.get('SyncState')=='idle','Closed idle interface required')
 return values

def specification(reply,prior_bytes):
 native=ET.fromstring(xml(reply));prior=ET.fromstring(prior_bytes[prior_bytes.index(b'<?xml'):])
 names={'Application','AreaGroupAddress','GroupAddress',*(f'LogicGA{i}Associations' for i in range(6))}
 def fields(root):
  found={}
  for node in root.findall('.//Param'):
   name=node.findtext('Name')
   if name in names:
    require(name not in found,'Unique spec field');found[name]={child.tag:child.text for child in node}
  require(set(found)==names,'Complete selected spec');return found
 observed=fields(native);expected=fields(prior);require(observed==expected,'Selected backend spec differs from literal source')
 return {'fields':observed,'native_xml':xml(reply),'prior_sha256':digest(prior_bytes)}


NATIVE_SOURCES=('run_native.py','backend_support.py','NativeCSVBackendProbe.py','run_original.py','replay_native.py','run_replay.py','native-cases.json','cases.json','PLAN.md')

def main():
 require(sys.version_info[:2] in ((3,10),(3,13)) and sys.platform=='darwin','Supported local runtime')
 require(len(sys.argv)==2,'Fresh output path required');out=Path(sys.argv[1])
 # No helper/package import or native constructor until the reviewed source map matches.
 source_inputs={BASE/name:read(BASE/name) for name in NATIVE_SOURCES}
 admission_raw=read(BASE/'native-admission.json',8192);admission=json.loads(admission_raw)
 expected={'format':'csv-backend-native4-admission-v1','inputs_sha256':{p.name:digest(raw) for p,raw in source_inputs.items()},
  'authorization':'root-reviewed-csv-backend-native4-v1','original_stage_a_report':admission.get('original_stage_a_report'),'original_stage_a_sha256':admission.get('original_stage_a_sha256')}
 require(admission==expected,'Held until exact native admission')
 support=module(BASE/'backend_support.py',source_inputs[BASE/'backend_support.py'],'csv_backend_host_support')
 support.own(BASE);support.new_output(BASE,out)
 cases=support.strict_json(source_inputs[BASE/'native-cases.json']);validate(cases)
 a_path=support.existing_output(BASE,Path(admission['original_stage_a_report']),'report.json')
 a_raw=read(a_path,8*1024*1024);a=support.strict_json(a_raw)
 require(digest(a_raw)==admission['original_stage_a_sha256'] and a.get('passed') is True and a.get('original_completed_cases')==8,'Reviewed completed original Stage A')
 for name in ('NativeCSVBackendProbe.py','cases.json','run_original.py'):
  path=BASE/name;require(a['before'][str(path)]==digest(source_inputs[path])==a['after'][str(path)],'Stage A input association')
 require(not any(k in os.environ for k in ('JAVA_TOOL_OPTIONS','JDK_JAVA_OPTIONS','_JAVA_OPTIONS','CLASSPATH','DYLD_INSERT_LIBRARIES','DYLD_LIBRARY_PATH')),'No inherited Java/library injection')
 java=Path(os.environ['CBUS_CGATE_JAVA']).resolve(strict=True);vendor=(ROOT/'research/vendor/cgate/app').resolve(strict=True)
 paths=[BASE/'native-admission.json',a_path,BASE.parent/'ownership.json',ROOT/'research/local_cgate.py',ROOT/'research/vendor/unitspec-plain/RELAY4.xml',vendor/'cgate.jar',java,java.parent/'keytool',Path(sys.executable).resolve()]
 paths+=sorted((ROOT/'src/cbus_toolkit').glob('*.py'))+sorted((vendor/'lib').rglob('*.jar'))
 # Actual runtime libraries and unit-description files, not just the Java launcher.
 runtime_root=java.parent.parent
 paths += [p for p in (runtime_root/'lib/server/libjvm.dylib',runtime_root/'lib/modules',runtime_root/'release') if p.is_file()]
 paths += sorted(p for p in (vendor/'unitspec').rglob('*') if p.is_file())
 inputs=dict(source_inputs)
 for path in paths:
  path=path.resolve(strict=True);inputs[path]=read(path,256*1024*1024)
 require(digest(inputs[vendor/'cgate.jar'])=='3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630','Pinned vendor C-Gate')
 require(any(p.name=='libjvm.dylib' for p in inputs) and any(p.name=='modules' for p in inputs),'Actual Java11 code inventory')
 sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
 from cbus_toolkit.cgate import CGateClient
 from cbus_toolkit.native import NativeDatabase,NativeProjects
 local=module(ROOT/'research/local_cgate.py',inputs[ROOT/'research/local_cgate.py'],'csv_backend_local_cgate')
 support.new_output(BASE,out);out.mkdir()
 report={'format':'csv-backend-native4-v1','passed':False,'native_capture_complete':False,'original_replay_performed':False,'full_csv_workflow_verified':False,
  'before':{str(p):digest(raw) for p,raw in inputs.items()},'fixtures':[],'wire':[],'scope':{'greeting_captured_separately':True,'generated_database_setup_writes':True,'physical_io':False,'read_boundary_project_save':False}}
 failures=support.Failures(report);service=None;client=None;sentinel=None;g=None;oldtemp=tempfile.tempdir
 try:
  report['archive_index']=support.archive(out,inputs);report['archive_sha256']=digest(read(out/'inputs.tar.gz',256*1024*1024))
  # Archive and exact loaded-module source association must precede the first owned socket.
  for name,m in tuple(sys.modules.items()):
   path=getattr(m,'__file__',None)
   if name.startswith('cbus_toolkit') and path:
    path=Path(path).resolve();require(path in inputs and read(path)==inputs[path],'Loaded package source association')
  for path,raw in inputs.items():require(read(path,256*1024*1024)==raw,'Pre-native input changed')
  sentinel=socket.socket();sentinel.bind(('127.0.0.1',0));sentinel.listen(4);sentinel.setblocking(False);sentinel_port=sentinel.getsockname()[1]
  tempfile.tempdir=str(out)
  service=local.LocalCGate(vendor,java=java);require(service.work.parent==out,'External service work')
  (service.work/'config/access.txt').write_text('interface 127.0.0.1 Clipsal\n');service.start();report['service']=service.report
  require(service.report['java_sha256']==digest(inputs[java]),'Actual child Java association')
  client=CGateClient('127.0.0.1',port=service.port,timeout=10,max_response_bytes=2*1024*1024,max_response_lines=10000)
  client.connect();report['greeting']=client.greeting;client._socket=Tap(client._socket,report['wire'])
  deadline=time.monotonic()+180
  for case in cases:
   row={'case':case,'capture_complete':False,'commands':[],'setup_session':{'started':False,'locked':False}};report['fixtures'].append(row)
   g=Guard(client,case['project'],sentinel_port,row['commands'],deadline);projects=NativeProjects(g);db=NativeDatabase(g)
   projects.operation('new',case['project']);db.create_network(case['project'],254,'OwnedNet','Cni',f'127.0.0.1:{sentinel_port}')
   db.add(g.network,'application',56,'Lighting')
   for address in case['groups']:db.add(g.network+'/56','group',address,'<Unused>' if address==255 else f'Group{address}')
   db.add(g.network,'unit',4,'OwnedUnit')
   for name,value in (('UnitType',case['unit_type']),('UnitName','NativeUnit'),('FirmwareVersion','4.4'),('CatalogNumber','OWNED'),('SerialNumber','1.2.3')):db.set(g.unit+'/'+name,value)
   if case['unit_type']=='RELAY4':
    # Manual finite session grammar avoids any library-generated recovery I/O.
    g.success(f'PP LOCK {g.lock} {g.network}');row['setup_session']['locked']=True
    g.success(f'PP START {g.session} {g.lock}');row['setup_session']['started']=True
    g.success(f'PP LOAD {g.session} /db{g.unit}');g.success(f'PP RESET_TO_DEFAULTS {g.session}')
    for name,value in (('UnitAddress','4'),('Application','56 255'),('Project',case['project']),('UnitName','NATUNIT'),('AreaGroupAddress',str(case['area'])),('GroupAddress','1 2 3 4 5 6 7 8 255 255 255 255 255 255 255 255')):
     g.success(f'PP SET {g.session} {name} {quote(value)}')
    g.success(f'PP SAVE_TO_SOURCE {g.session}');row['setup_parameters']=params(g.command(f'PP GET {g.session} *'))
    g.success(f'PP END {g.session}');row['setup_session']['started']=False
    g.success(f'PP UNLOCK {g.lock}');row['setup_session']['locked']=False
   projects.operation('save',case['project']);projects.operation('close',case['project']);projects.operation('load',case['project']);g.phase='read'
   row['runtime_before']=closed(g);before=xml(db.get('//'+case['project'],xml=True));row['xml_before']=before
   document=ET.fromstring(before);units=document.findall('.//Unit');require(len(units)==1,'One generated unit')
   unit=units[0];oid=unit.findtext('OID');require(re.fullmatch(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}',oid or ''),'Native unit OID')
   require(unit.findtext('UnitType')==case['unit_type'] and unit.findtext('FirmwareVersion')=='4.4','Native unit identity');g.allowed_oids.add(oid)
   row['oid']=oid;row['database_unit']=list(db.get(g.unit).lines)
   row['sessions_before']={'units':list(g.command('PP UNITS').lines),'locks':list(g.command('PP LIST_LOCK').lines)}
   require(all('CSVSESSION' not in line for line in row['sessions_before']['units']) and all('CSVLOCK' not in line for line in row['sessions_before']['locks']),'No setup sessions/locks retained')
   if case['unit_type']=='RELAY4':
    if case['id']=='B01':report['specification']=specification(g.command('PP GET_UNIT_SPEC RELAY4.xml'),inputs[ROOT/'research/vendor/unitspec-plain/RELAY4.xml'])
    row['parameters_before']=params(g.command(f'pp quickget {g.unit} *'))
    require(row['parameters_before']==row['setup_parameters'],'Materialized reload PP unchanged before reads')
    require(xml(db.get('//'+case['project'],xml=True))==before,'Baseline PP read materialized database unexpectedly')
    row['reads']=[]
    names=['AreaGroupAddress','Application','GroupAddress']+([f'LogicGA{i}Associations' for i in range(6)] if case['association_reads'] else [])
    for name in names:
     values=[]
     for target in (g.unit,f'//{case["project"]}/!{oid}'):
      reply=g.command(f'pp quickget {target} {name}');observed=params(reply);require(set(observed)=={name},'Exact requested parameter correlation');values.append(observed[name])
      row['reads'].append({'target':target,'parameter':name,'lines':list(reply.lines),'value':observed[name]})
     require(values[0]==values[1]==row['parameters_before'][name],'Path/OID/value equality')
    row['parameters_after']=params(g.command(f'pp quickget {g.unit} *'));require(row['parameters_after']==row['parameters_before'],'Full PP readback changed')
   row['xml_after']=xml(db.get('//'+case['project'],xml=True));require(row['xml_after']==before,'Database changed during read boundary')
   row['runtime_after']=closed(g);row['sessions_after']={'units':list(g.command('PP UNITS').lines),'locks':list(g.command('PP LIST_LOCK').lines)};require(row['sessions_after']==row['sessions_before'],'Session inventory changed')
   observed_groups=[int(v.findtext('Address')) for v in document.findall('.//Application/Group')];require(set(observed_groups)==set(case['groups']) and len(observed_groups)==len(case['groups']),'Exact existing metadata set')
   row['group_order']=observed_groups;row['capture_complete']=True
   g.phase='setup';projects.operation('close',case['project'])
  report['native_capture_complete']=True
 except BaseException as error:failures.retain('native operation',error)
 finally:
  # No protocol commands after a failed operation. Only owned resource release,
  # local sentinel observation and host evidence follow, including interruptions.
  if g is not None and failures.first is not None:g.first=failures.first
  if client is not None:failures.attempt('client close',client.close)
  if service is not None:
   failures.attempt('service close',service.close);report['service']=service.report
  tempfile.tempdir=oldtemp
  if sentinel is not None:
   def sentinel_check():
    try:connection,address=sentinel.accept()
    except BlockingIOError:report['sentinel_connections']=0;return
    report['sentinel_connections']=1;report['sentinel_peer']=address
    try:raise RuntimeError('Unexpected CNI connection attempt')
    finally:
     try:connection.close()
     except BaseException as error:report['sentinel_close_error']=error_record(error)
   failures.attempt('sentinel observation',sentinel_check);failures.attempt('sentinel close',sentinel.close)
  support.posthashes(inputs,report,failures)
  report['passed']=failures.first is None and report['native_capture_complete'] and service is not None and service.report.get('cleanup_complete') is True and report.get('sentinel_connections')==0
  if not report['passed'] and failures.first is None:failures.retain('incomplete native capture/cleanup',RuntimeError('Native capture or cleanup not verified'))
  support.finish(out,report,failures)
 failures.raise_first()
 print(json.dumps({'passed':report['passed'],'native_fixtures':4,'original_replay_performed':False,'report':str(out/'report.json')}))

if __name__=='__main__':main()
