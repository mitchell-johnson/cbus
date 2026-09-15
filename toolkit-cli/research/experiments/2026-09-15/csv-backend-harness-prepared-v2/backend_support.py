"""Host-only bounded evidence utilities. Importing this module performs no I/O."""
from __future__ import annotations
import hashlib, io, json, os, stat, tarfile
from pathlib import Path

TOKEN='b0f8078731a54cc4aa069f00b043d210'
VOLUME='24F890EF-A1B9-4B52-8E18-823080A2F0BB'

def require(condition,message):
    if not condition: raise RuntimeError(message)

def digest(raw): return hashlib.sha256(raw).hexdigest()

def error_record(error):
    try: message=str(error)
    except BaseException: message='<unprintable>'
    return {'type':type(error).__name__,'message':message[:2048]}

def read(path,limit=64*1024*1024):
    require(type(limit) is int and 0<limit<=256*1024*1024,'Read bound')
    fd=os.open(path,os.O_RDONLY|os.O_NONBLOCK|os.O_NOFOLLOW);first=None
    try:
        info=os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_size<=limit,'Bounded regular input: '+str(path))
        chunks=[];size=0
        while size<=limit:
            block=os.read(fd,min(65536,limit+1-size))
            if not block: break
            chunks.append(block);size+=len(block)
        require(size<=limit,'Input grew past bound: '+str(path))
        return b''.join(chunks)
    except BaseException as error:first=error;raise
    finally:
        try:os.close(fd)
        except BaseException:
            if first is None:raise

def strict_json(raw):
    def pairs(items):
        result={}
        for key,value in items:
            require(key not in result,'Duplicate JSON key');result[key]=value
        return result
    def constant(value):raise ValueError('Nonfinite JSON value')
    return json.loads(raw,object_pairs_hook=pairs,parse_constant=constant)

def own(base):
    owner=strict_json(read(base.parent/'ownership.json',4096))
    require(owner.get('owner_token')==TOKEN and owner.get('root')==str(base.parent)
            and owner.get('task')=='/root/project_store' and owner.get('volume_uuid')==VOLUME,'Owned external root')
    require(base==base.resolve(strict=True) and not base.is_symlink(),'Resolved harness root')
    return owner

def new_output(base,out,*,nested=None):
    require(out.is_absolute() and out.name not in ('','.','..'),'Absolute new output')
    require(not out.exists() and not out.is_symlink() and not out.parent.is_symlink(),'New nonsymlink output')
    parent=out.parent.resolve(strict=True)
    require(parent==out.parent and (parent==base or nested is not None and out.name==nested and parent.parent==base),'Direct owned output')
    require(out.resolve(strict=False)==parent/out.name,'Prospective output containment')

def existing_output(base,path,name):
    require(path.is_absolute() and path.name==name and not path.is_symlink() and not path.parent.is_symlink(),'Owned prior report')
    require(path.parent.resolve(strict=True)==path.parent and path.parent.parent==base,'Owned prior report directory')
    return path

def archive(out,inputs):
    index=[];first=None;stream=tarfile.open(out/'inputs.tar.gz','x:gz')
    try:
        for number,(path,raw) in enumerate(inputs.items()):
            name=str(number)+'/'+path.name;entry=tarfile.TarInfo(name);entry.size=len(raw);entry.mtime=0
            stream.addfile(entry,io.BytesIO(raw));index.append({'path':str(path),'member':name,'bytes':len(raw),'sha256':digest(raw)})
    except BaseException as error:first=error;raise
    finally:
        try:stream.close()
        except BaseException:
            if first is None:raise
    first=None;stream=tarfile.open(out/'inputs.tar.gz','r:gz')
    try:
        require(stream.getnames()==[r['member'] for r in index],'Exact archive member order')
        for row,(path,raw) in zip(index,inputs.items()):
            item=stream.extractfile(row['member']);require(item is not None,'Archive entry');inner=None
            try:observed=item.read(len(raw)+1)
            except BaseException as error:inner=error;raise
            finally:
                try:item.close()
                except BaseException:
                    if inner is None:raise
            require(observed==raw,'Archive input equality')
    except BaseException as error:first=error;raise
    finally:
        try:stream.close()
        except BaseException:
            if first is None:raise
    return index

class Failures:
    def __init__(self,report):self.report=report;self.first=None;report['secondary_errors']=[]
    def retain(self,label,error):
        self.report['passed']=False
        row={'stage':label,**error_record(error)}
        if self.first is None:self.first=error;self.report['error']=row
        else:self.report['secondary_errors'].append(row)
    def attempt(self,label,operation):
        try:return operation()
        except BaseException as error:self.retain(label,error);return None
    def raise_first(self):
        if self.first is not None:raise self.first

def posthashes(inputs,report,failures):
    report['after']={}
    for path,raw in inputs.items():
        value=failures.attempt('posthash '+str(path),lambda path=path:digest(read(path,256*1024*1024)))
        report['after'][str(path)]=value
        if value is not None:failures.attempt('posthash equality '+str(path),lambda value=value,raw=raw:require(value==digest(raw),'Input changed'))

def finish(out,report,failures):
    """Host-only reporting; any earlier exception object remains primary."""
    def write():
        if failures.first is not None:report['passed']=False
        raw=(json.dumps(report,ensure_ascii=True,indent=2)+'\n').encode('ascii')
        require(len(raw)<=48*1024*1024,'Report bound')
        pending=out/'report.pending.json';stream=pending.open('xb');first=None
        try:
            count=stream.write(raw);require(count==len(raw),'Report write count');stream.flush();os.fsync(stream.fileno())
        except BaseException as error:first=error;raise
        finally:
            try:stream.close()
            except BaseException:
                if first is None:raise
        os.replace(pending,out/'report.json')
    failures.attempt('report write/close',write)
