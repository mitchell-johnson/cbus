"""Bounded original DontAskAgain reset with an explicit registry backend."""
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol

HKCU=0x80000001
DONT_ASK_AGAIN_KEY=r'Software\Clipsal Integrated Systems\C-Bus Installation Software\3.0\DontAskAgain'
ORIGINAL_ACCESS=0xf003f


def _uint(value,name):
    if type(value)is not int or not 0<=value<=0xffffffff:raise ValueError(f'{name} must be an unsigned32-bit integer')
    return value


@dataclass(frozen=True)
class OpenKeyResult:
    status:int
    handle:int|None=None
    def __post_init__(self):
        _uint(self.status,'status')
        if self.status==0:
            if type(self.handle)is not int or not 0<self.handle<2**64 or self.handle==HKCU:raise ValueError('successful open requires an owned handle')
        elif self.handle is not None:raise ValueError('failed open must not supply a handle')


@dataclass(frozen=True)
class KeyInfoResult:
    status:int
    subkeys:int=0
    max_name_length:int=0
    def __post_init__(self):
        for name in ('status','subkeys','max_name_length'):_uint(getattr(self,name),name)


@dataclass(frozen=True)
class EnumKeyResult:
    status:int
    name:str|None=None
    def __post_init__(self):
        _uint(self.status,'status')
        if self.status and self.name is not None:raise ValueError('failed enumeration must not supply a name')


class DontAskAgainRegistry(Protocol):
    def open_key(self,parent:int,key:str,access:int)->OpenKeyResult:...
    def query_info(self,handle:int)->KeyInfoResult:...
    def enum_key(self,handle:int,index:int,capacity:int)->EnumKeyResult:...
    def close_key(self,handle:int)->int:...
    def delete_key(self,parent:int,key:str)->int:...


class ResetLimitExceeded(ValueError):
    """Configured resource bound stopped the operation before its next mutation."""


def _error(error):
    try:message=str(error)
    except BaseException:message='exception message unavailable'
    return {'type':type(error).__name__,'message':message}


@dataclass(frozen=True)
class DontAskAgainResetOutcome:
    complete:bool
    algorithm_completed:bool
    original_boolean:bool|None
    original_notice_requested:bool
    target_delete_succeeded:bool
    already_absent:bool
    operations:tuple
    issues:tuple
    error:object
    cleanup_errors:tuple
    limits:object
    def as_dict(self):
        return {'operation':'reset-dont-ask-again','complete':self.complete,
                'algorithm_completed':self.algorithm_completed,'original_boolean':self.original_boolean,
                'original_notice_requested':self.original_notice_requested,'notice_message_id':0x2bfc,
                'notice_displayed':False,'target_delete_succeeded':self.target_delete_succeeded,
                'absence_verified':False,'already_absent':self.already_absent,
                'hive':HKCU,'key':DONT_ASK_AGAIN_KEY,'operations':[dict(row)for row in self.operations],
                'issues':list(self.issues),'error':dict(self.error)if self.error else None,
                'cleanup_errors':[dict(row)for row in self.cleanup_errors],'limits':dict(self.limits),
                'transactional':False,'actual_registry_backend_verified':False}


class ToolkitDontAskAgainReset:
    """One bounded traversal of the exact original HKCU subtree; no retry."""
    def __init__(self,registry:DontAskAgainRegistry,*,max_keys=256,max_depth=32,max_name_units=1024):
        for name,value in (('max_keys',max_keys),('max_depth',max_depth),('max_name_units',max_name_units)):
            if type(value)is not int or not 1<=value<=1000000:raise ValueError(f'{name} must be an integer from1 to1000000')
        self.registry=registry;self._limits={'max_keys':max_keys,'max_depth':max_depth,'max_name_units':max_name_units}
        self.last_error=None;self.last_outcome=None;self.last_evidence=None

    def _call(self,operation,path,function,*args,**fields):
        row={'sequence':len(self._operations)+1,'operation':operation,'path':path,'completed':False,**fields}
        self._operations.append(row)
        try:value=function(*args)
        except BaseException as error:
            detail=_error(error);row.update(error_type=detail['type'],error_message=detail['message']);raise
        if operation=='open':
            if type(value)is not OpenKeyResult:raise TypeError('invalid open result')
            status=value.status
        elif operation=='query':
            if type(value)is not KeyInfoResult:raise TypeError('invalid query result')
            status=value.status;row.update(count=value.subkeys if not status else None,max_name_length=value.max_name_length if not status else None)
        elif operation=='enumerate':
            if type(value)is not EnumKeyResult:raise TypeError('invalid enumeration result')
            status=value.status;row['name']=value.name
        else:status=_uint(value,'registry status')
        row.update(completed=True,status=status)
        if status:self._issues.append(f'{operation} returned {status}: {path}')
        return value

    def _finish(self,finished,status,error,cleanup):
        result=DontAskAgainResetOutcome(finished and status==0 and error is None and not self._issues,
            finished,status==0 if finished else None,finished,status==0 if finished else False,
            status in (2,3)if finished else False,tuple(MappingProxyType(dict(row))for row in self._operations),
            tuple(self._issues),MappingProxyType(_error(error))if error is not None else None,
            tuple(MappingProxyType(dict(row))for row in cleanup),MappingProxyType(dict(self._limits)))
        self.last_error=error;self.last_outcome=result
        try:self.last_evidence=result.as_dict()
        except BaseException:self.last_evidence={'operation':'reset-dont-ask-again','complete':False,'evidence_export_failed':True,'attempted_operations':len(self._operations)}
        if error is not None:
            try:error.toolkit_preferences_reset_evidence=self.last_evidence
            except BaseException:pass
        return result

    def run(self):
        self.last_error=self.last_outcome=self.last_evidence=None
        self._operations=[];self._issues=[]
        stack=[{'parent':HKCU,'key':DONT_ASK_AGAIN_KEY,'path':DONT_ASK_AGAIN_KEY,'depth':1,'stage':'open'}]
        owned={};visited=0;error=None;cleanup=[];finished=False;final_status=None
        try:
            while stack:
                frame=stack[-1];path=frame['path'];stage=frame['stage']
                if stage=='open':
                    if visited>=self._limits['max_keys'] or frame['depth']>self._limits['max_depth']:
                        raise ResetLimitExceeded('configured key or depth bound reached')
                    visited+=1
                    opened=self._call('open',path,self.registry.open_key,frame['parent'],frame['key'],ORIGINAL_ACCESS,access=ORIGINAL_ACCESS)
                    if opened.status:
                        frame['stage']='delete'
                    else:
                        if opened.handle in owned:raise ValueError('backend reused an active handle')
                        owned[opened.handle]=path;frame['handle']=opened.handle;frame['stage']='query'
                elif stage=='query':
                    info=self._call('query',path,self.registry.query_info,frame['handle'])
                    if not info.status:
                        if info.subkeys>self._limits['max_keys']-visited:raise ResetLimitExceeded('reported child count exceeds remaining key bound')
                        if info.max_name_length>self._limits['max_name_units']:raise ResetLimitExceeded('reported name length exceeds configured bound')
                        frame.update(index=info.subkeys-1,capacity=info.max_name_length+1,stage='enumerate')
                    else:frame['stage']='close'
                elif stage=='enumerate':
                    if frame['index']<0:frame['stage']='close';continue
                    index=frame['index'];frame['index']-=1
                    item=self._call('enumerate',path,self.registry.enum_key,frame['handle'],index,frame['capacity'],index=index,capacity=frame['capacity'])
                    if item.status:continue
                    name=item.name
                    if type(name)is not str or not name or '\0'in name or '\\'in name:raise ValueError('backend returned an invalid child component')
                    units=len(name.encode('utf-16le'))//2
                    if units>=frame['capacity'] or units>self._limits['max_name_units']:raise ValueError('backend child exceeds enumeration capacity')
                    stack.append({'parent':frame['handle'],'key':name,'path':path+'\\'+name,'depth':frame['depth']+1,'stage':'open'})
                elif stage=='close':
                    handle=frame['handle'];owned.pop(handle)
                    self._call('close',path,self.registry.close_key,handle)
                    frame['stage']='delete'
                else:
                    status=self._call('delete',path,self.registry.delete_key,frame['parent'],frame['key'])
                    stack.pop()
                    if not stack:final_status=status;finished=True
        except BaseException as caught:error=caught
        finally:
            for handle,path in reversed(list(owned.items())):
                owned.pop(handle)
                try:self._call('close',path,self.registry.close_key,handle,cleanup=True)
                except BaseException as caught:
                    cleanup.append(_error(caught))
                    if error is None:error=caught
        result=self._finish(finished,final_status,error,cleanup)
        if isinstance(error,(KeyboardInterrupt,SystemExit)):raise error
        return result
