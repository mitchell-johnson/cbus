"""Prewritten outer-workflow hypotheses. Pure fixture construction, no oracle calls."""
from pathlib import Path
import copy,json
ROLES=(('on','Enable'),('off','Disable'),('override','Overrd'))
def levels(addresses):return [{'address':a,'value':(a+173)%256,'tag':'Retained '+str(a)} for a in addresses]
def group(name,address,existing=()):return {'identity':name,'address':address,'levels':levels(existing)}
def case(i,entry,enabled,groups,roles,**extra):
 d={'id':f'O{i:02}','entry':entry,'enabled':enabled,'groups':groups,'roles':dict(zip(('on','off','override'),roles)),'initial_lock':0,'initial_pending':False,'release_lock':False,'deny_level_save':None,'deny_storage_save':None};d.update(extra);return d
def build():
 full=list(range(1,32));extras=[0,32,255]
 cases=[case(1,'button',False,[group('A',1),group('B',2),group('C',3)],('A','B','C')),
 case(2,'button',True,[group('U',255)],(None,'U',None)),
 case(3,'button',True,[group('A',1,full+extras),group('B',2,full),group('C',3,full)],('A','B','C')),
 case(4,'direct',False,[],(None,None,None)),
 case(5,'button',True,[group('A',1),group('B',2),group('C',3)],('A','B','C')),
 case(6,'button',True,[group('A',1)],('A','A','A')),
 case(7,'direct',False,[group('A',1,list(range(1,32,2))+extras),group('B',2)],('A','A','B')),
 case(8,'button',True,[group('A',1,full+extras),group('U',255),group('C',3,extras)],('A','U','C')),
 case(9,'button',True,[group('A',1,list(range(2,32))),group('B',2,full),group('C',3,list(range(1,31)))],('A','B','C')),
 case(10,'direct',True,[group('A',1),group('B',2),group('C',3)],('A','B','C'),initial_lock=1,release_lock=True),
 case(11,'direct',True,[group('A',1),group('B',2),group('C',3)],('A','B','C'),deny_storage_save=2),
 case(12,'direct',True,[group('A',1),group('B',2),group('C',3)],('A','B','C'),deny_level_save=65)]
 for c in cases:c['expected']=hypothesis(c)
 return cases
class Denied(Exception):pass
def hypothesis(c):
 groups=copy.deepcopy(c['groups']);index={g['identity']:g for g in groups};trace=[]
 counts={'level_attempts':0,'level_completed':0,'storage_attempts':0,'storage_completed':0,'project_requests':0};lock=c['initial_lock'];pending=c['initial_pending'];cursor=None;delay=False;completed=False
 def emit(event,**kw):trace.append({'event':event,**kw})
 def get(role):emit('get_service');emit('get_role',role=role,group=c['roles'][role]);return index.get(c['roles'][role])
 def selected(g):emit('is_unused',group=g['identity']);return g['address']!=255
 def request():
  nonlocal pending
  counts['project_requests']+=1
  if lock:pending=True;return
  counts['storage_attempts']+=1;emit('storage')
  if counts['storage_attempts']==c['deny_storage_save']:raise Denied()
  counts['storage_completed']+=1
 def unlock():
  nonlocal lock,pending
  lock-=1
  if lock==0 and pending:request();pending=False
 def save(g,level):
  counts['level_attempts']+=1;emit('level_save',group=g['identity'],**level)
  if counts['level_attempts']==c['deny_level_save']:raise Denied()
  counts['level_completed']+=1
 def inner(g,role,action):
  nonlocal lock
  emit('inner',role=role,group=g['identity'],action=action);lock+=1;changed=False
  for a in range(1,32):
   emit('find',group=g['identity'],address=a,create=False)
   if any(l['address']==a for l in g['levels']):continue
   emit('find',group=g['identity'],address=a,create=True)
   l={'address':a,'value':a,'tag':'Level '+str(a)};g['levels'].append(l);save(g,l);request()
   zones=[n for bit,n in enumerate(('unsw','1','2','3','4')) if a&(1<<bit)]
   l['tag']='Sched '+action+' '+('Zone:' if len(zones)==1 else 'Zones:')+','.join(zones)
   save(g,l);changed=True
  if changed:request()
  unlock();emit('inner_return',role=role,group=g['identity'])
 try:
  required=c['entry']=='direct'
  if c['entry']=='button':
   emit('button');emit('required');emit('get_service');emit('get_enable',value=c['enabled'])
   if c['enabled']:
    for role,_ in ROLES:
     g=get(role)
     if g is None:continue
     g=get(role)
     if not selected(g):continue
     g=get(role);emit('zone_levels',group=g['identity'])
     for a in range(1,32):
      emit('find',group=g['identity'],address=a,create=False)
      if not any(l['address']==a for l in g['levels']):required=True;break
     if required:break
  if required:
   emit('outer');cursor=-11;emit('cursor',value=-11);emit('resource',which='message');emit('resource',which='title');delay=True;emit('delay_begin')
   for role,action in ROLES:
    g=get(role)
    if g is None:continue
    g=get(role)
    if not selected(g):continue
    emit('wrapper',role=role);g=get(role);inner(g,role,action)
   delay=False;emit('delay_finish');cursor=0;emit('cursor',value=0)
  if c['release_lock']:emit('explicit_unlock');unlock()
  completed=True
 except Denied:pass
 return {'completed':completed,'trace':trace,'groups':groups,'lock':lock,'pending':pending,'cursor':cursor,'delay_active':delay,**counts}
if __name__=='__main__':
 p=Path(__file__).with_name('cases.json')
 with p.open('x') as f:json.dump(build(),f,separators=(',',':'));f.write('\n')
