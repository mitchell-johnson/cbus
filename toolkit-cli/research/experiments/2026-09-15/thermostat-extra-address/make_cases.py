from pathlib import Path
import json
BASE=Path(__file__).resolve().parent
EXTRA=[{'address':0,'value':200,'tag':'extra-zero'},{'address':32,'value':201,'tag':'extra-thirtytwo'},{'address':255,'value':202,'tag':'extra-255'}]
rows=[]
for ident,existing,action in [('missing-schedule-with-extras',EXTRA,'Enable'),('complete-schedule-with-extras',[EXTRA[2]]+[{'address':a,'value':255-a,'tag':'kept-'+str(a)} for a in range(31,0,-1)]+EXTRA[:2],'Overrd')]:
 case={'id':ident,'kind':'create','actions':[action],'existing':existing,'initial_lock':0,'initial_pending':False,'defer_save':True,'release_outer_locks':False,'deny_level_save':None,'deny_storage_save':None}
 have={x['address']:x for x in existing};missing=[n for n in range(1,32) if n not in have]
 final=list(existing)
 for address in missing:
  zones=('Zone:' if address in (1,2,4,8,16) else 'Zones:')+','.join(n for bit,n in ((1,'unsw'),(2,'1'),(4,'2'),(8,'3'),(16,'4')) if address&bit)
  final.append({'address':address,'value':address,'tag':'Sched '+action+' '+zones})
 case['expected']={'completed':True,'original_exception_unwind_executed':False,'final_levels':sorted(final,key=lambda v:v['address']),'final_level_order':[v['address'] for v in final],'created':len(missing),'level_saves':2*len(missing),'storage_saves':int(bool(missing)),'project_requests':len(missing)+2*int(bool(missing)),'final_lock':0,'final_pending':False}
 rows.append(case)
with (BASE/'cases.json').open('x') as f:json.dump(rows,f,indent=2);f.write('\n')
