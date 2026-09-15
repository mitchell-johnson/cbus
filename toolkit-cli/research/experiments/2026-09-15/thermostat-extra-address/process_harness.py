"""Local process evidence only; never retries an original process."""
import base64
import hashlib
import json
import subprocess
import time


def description(error):
    result={'class':type(error).__name__}
    try:result['message']=str(error)
    except BaseException:result['message']='<unavailable>'
    return result


class Failures:
    def __init__(self):
        self.first=None
        self.traceback=None
        self.records=[]
    def remember(self, stage, error):
        if self.first is None:self.first,self.traceback=error,error.__traceback__
        try:self.records.append({'stage':stage,**description(error)})
        except BaseException:pass
    def attempt(self, stage, operation):
        try:return operation()
        except BaseException as error:self.remember(stage,error)
    def raise_first(self):
        if self.first is not None:raise BaseException.with_traceback(self.first, self.traceback)


def plan_tsv(plans):
    lines=[]
    for c in plans:
        values=[c['id'],str(c['unit']),str(c['parameter']),','.join(map(str,c['bridges'])) or '-',
                str(c['root']),str(c['context']),c['cache'],str(int(c['n'])),str(int(c['t'])),str(int(c['active'])),
                c['tag'],','.join(base64.b64encode(raw.encode('ascii')).decode('ascii') for raw in c['raws']),
                ';'.join(c['operations']) or '-']
        lines.append('\t'.join(values))
    return ('\n'.join(lines)+'\n').encode('ascii')


def run_process(stage, command, *, destination, environment, failures, timeout=30, popen=subprocess.Popen):
    """Always file-backed output; record start/reap separately from exit success."""
    record={'stage':stage,'command':command,'launch_attempted':False,'started':False,
            'completed':False,'exit_code':None,'timeout':False,'resubmitted':False}
    streams=[];process=None;clock=time.monotonic()
    try:
        for suffix in ('stdout','stderr'):
            streams.append((destination/(stage+'.'+suffix)).open('xb',buffering=0))
        record['launch_attempted']=True
        process=popen(command,cwd=destination,env=environment,stdout=streams[0],stderr=streams[1],start_new_session=True)
        record['started']=True;record['pid']=process.pid
        record['exit_code']=process.wait(timeout=timeout)
        record['completed']=True
    except BaseException as error:
        record['timeout']=isinstance(error,subprocess.TimeoutExpired)
        failures.remember(stage,error)
        if process is not None:
            # Exact locally returned Popen only; no group/shared-process operation.
            failures.attempt(stage+'.kill_owned_process',process.kill)
            def reap():
                record['exit_code']=process.wait(timeout=5)
                record['completed']=True
            failures.attempt(stage+'.reap_owned_process',reap)
    finally:
        for index,stream in enumerate(streams):
            failures.attempt(stage+'.close_'+str(index),stream.close)
        def finish_clock():record['duration_seconds']=time.monotonic()-clock
        failures.attempt(stage+'.finish_clock',finish_clock)
    for suffix in ('stdout','stderr'):
        def output_stat(suffix=suffix):
            path=destination/(stage+'.'+suffix)
            record[suffix+'_bytes']=path.stat().st_size
            record[suffix+'_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
        failures.attempt(stage+'.inspect_'+suffix,output_stat)
    return record

