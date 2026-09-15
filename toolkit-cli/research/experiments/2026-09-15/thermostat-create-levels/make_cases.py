from pathlib import Path
import json
BASE=Path(__file__).resolve().parent

def levels(addresses):return [{'address':a,'value':255-a,'tag':'kept-'+str(a)} for a in addresses]
def case(name,actions=('Enable',),existing=(),**changes):
 value={'id':name,'kind':'create','actions':list(actions),'existing':list(existing),'initial_lock':0,'initial_pending':False,'defer_save':True,'release_outer_locks':False,'deny_level_save':None,'deny_storage_save':None}
 value.update(changes);return value
cases=[{'id':'zone-labels-1-through31','kind':'zones','levels':list(range(1,32))},
 case('empty-enable'),case('empty-disable',('Disable',)),case('empty-override',('Overrd',)),
 case('existing31-preserved',existing=levels(range(1,32))),
 case('mixed-preserved-odds',('Overrd',),levels(range(1,32,2))),
 case('same-group-three-actions',('Enable','Disable','Overrd')),
 case('nested-save-lock2',initial_lock=2,release_outer_locks=True),
 case('already-pending-existing',existing=levels(range(1,32)),initial_pending=True),
 case('nested-lock-retained',initial_lock=1),
 case('storage-denied-at-final-flush',deny_storage_save=1),
 case('level-save-denied-third',deny_level_save=3)]
for c in cases:
 if c['kind']=='zones':
  c['expected']={'labels':{str(a):('Zone:' if a in (1,2,4,8,16) else 'Zones:')+','.join(n for bit,n in ((1,'unsw'),(2,'1'),(4,'2'),(8,'3'),(16,'4')) if a&bit) for a in c['levels']}}
 else:
  denied=c['deny_storage_save'] is not None or c['deny_level_save'] is not None
  c['expected']={'completed':not denied,'original_exception_unwind_executed':False}
  if not denied:
   initial={v['address']:v for v in c['existing']}
   final=[]
   for a in range(1,32):
    zones=('Zone:' if a in (1,2,4,8,16) else 'Zones:')+','.join(n for bit,n in ((1,'unsw'),(2,'1'),(4,'2'),(8,'3'),(16,'4')) if a&bit)
    final.append(initial.get(a,{'address':a,'value':a,'tag':'Sched '+c['actions'][0]+' '+zones}))
   missing=31-len(c['existing'])
   # The original issues a ProjectSave for each new default level and once per changed action.
   saves=missing+(1 if missing else 0)
   expected_storage=saves if not c['defer_save'] else int(bool(saves or c['initial_pending']) and (c['initial_lock']==0 or c['release_outer_locks']))
   c['expected'].update(final_levels=final,created=missing,level_saves=2*missing,project_requests=saves+expected_storage*int(c['defer_save']),storage_saves=expected_storage,final_lock=0 if c['release_outer_locks'] else c['initial_lock'],final_pending=bool((missing or c['initial_pending']) and c['initial_lock'] and not c['release_outer_locks']))
(BASE/'cases.json').write_text(json.dumps(cases,indent=2)+'\n')
