import json
import importlib.util
import os
from pathlib import Path
import unittest
from cbus_toolkit.toolkit_preferences_reset import (
    HKCU,DONT_ASK_AGAIN_KEY,ORIGINAL_ACCESS,OpenKeyResult,KeyInfoResult,EnumKeyResult,
    ToolkitDontAskAgainReset,ResetLimitExceeded,
)


class MemoryRegistry:
    def __init__(self,children=(),faults=()):
        self.nodes={DONT_ASK_AGAIN_KEY:True};self.handles={};self.next=1000;self.calls=[];self.fault=None
        if children is None:self.nodes={}
        else:
            for child in children:
                parts=child.split('\\')
                for count in range(1,len(parts)+1):self.nodes[DONT_ASK_AGAIN_KEY+'\\'+'\\'.join(parts[:count])]=True
        self.rules={(op,path,index):status for op,path,index,status in faults}
    def path(self,parent,key):return key if parent==HKCU else self.handles[parent]+'\\'+key
    def children(self,path):return [key[len(path)+1:]for key in self.nodes if key.startswith(path+'\\')and'\\'not in key[len(path)+1:]]
    def check(self,row):
        self.calls.append(row)
        if self.fault:self.fault(row)
    def open_key(self,parent,key,access):
        path=self.path(parent,key);self.check(('open',path,access))
        status=self.rules.get(('open',path,None),0 if path in self.nodes else 2)
        if status:return OpenKeyResult(status)
        handle=self.next;self.next+=1;self.handles[handle]=path;return OpenKeyResult(0,handle)
    def query_info(self,handle):
        path=self.handles[handle];self.check(('query',path))
        status=self.rules.get(('query',path,None),0);names=self.children(path)
        return KeyInfoResult(status,len(names),max((len(name.encode('utf-16le'))//2 for name in names),default=0))
    def enum_key(self,handle,index,capacity):
        path=self.handles[handle];self.check(('enumerate',path,index,capacity));names=self.children(path)
        status=self.rules.get(('enumerate',path,index),0 if index<len(names)else 259)
        return EnumKeyResult(status,None if status else names[index])
    def close_key(self,handle):
        path=self.handles.pop(handle);self.check(('close',path));return self.rules.get(('close',path,None),0)
    def delete_key(self,parent,key):
        path=self.path(parent,key);self.check(('delete',path))
        status=self.rules.get(('delete',path,None),2 if path not in self.nodes else 5 if self.children(path)else 0)
        if not status:del self.nodes[path]
        return status


class ResetTests(unittest.TestCase):
    def test_original_complete_and_partial_vectors(self):
        data=json.loads((Path(__file__).resolve().parents[1]/'research/fixtures/toolkit-preferences-reset-vectors.json').read_text())
        for expected in data['cases']:
            with self.subTest(children=expected['children'],faults=expected['faults']):
                backend=MemoryRegistry(expected['children'],expected['faults']);reset=ToolkitDontAskAgainReset(backend)
                result=reset.run()
                self.assertEqual(result.original_boolean,expected['original_delete_return'][0])
                self.assertEqual(result.original_notice_requested,bool(expected['notice_requests']))
                self.assertEqual(list(backend.nodes),expected['remaining_nodes'])
                actual=[{key:value for key,value in row.items()if key not in ('sequence','completed')}for row in result.operations]
                self.assertEqual(actual,expected['trace'])
                self.assertEqual(result.complete,all(row['status']==0 for row in expected['trace']))
                self.assertEqual(result.target_delete_succeeded,expected['original_delete_return'][0])
                self.assertFalse(result.as_dict()['absence_verified'])
                self.assertEqual(backend.handles,{})

    def test_bound_checks_stop_before_dependent_deletion_and_release_handles(self):
        for limits in ({'max_keys':1},{'max_depth':1},{'max_name_units':1}):
            backend=MemoryRegistry(['aa','bb']);initial=list(backend.nodes)
            reset=ToolkitDontAskAgainReset(backend,**limits);result=reset.run()
            self.assertFalse(result.complete);self.assertFalse(result.original_notice_requested)
            self.assertIsInstance(reset.last_error,ResetLimitExceeded)
            self.assertFalse(any(row[0]=='delete'for row in backend.calls))
            self.assertEqual(list(backend.nodes),initial);self.assertEqual(backend.handles,{})
        backend=MemoryRegistry(['a\\x','b']);reset=ToolkitDontAskAgainReset(backend,max_keys=3)
        result=reset.run();self.assertFalse(result.complete)
        self.assertNotIn(DONT_ASK_AGAIN_KEY+'\\b',backend.nodes)
        self.assertIn(DONT_ASK_AGAIN_KEY+'\\a\\x',backend.nodes)
        self.assertEqual(backend.handles,{})

    def test_raised_bounds_allow_large_tree_without_product_limit_claim(self):
        backend=MemoryRegistry(['key'+str(i)for i in range(300)])
        result=ToolkitDontAskAgainReset(backend,max_keys=301).run()
        self.assertTrue(result.complete);self.assertEqual(backend.nodes,{})
        self.assertEqual(sum(row[0]=='delete'for row in backend.calls),301)

    def test_constructor_rejects_invalid_bounds_before_backend_calls(self):
        backend=MemoryRegistry()
        for name in ('max_keys','max_depth','max_name_units'):
            for value in (True,0,-1,1000001,'32'):
                with self.assertRaises(ValueError):ToolkitDontAskAgainReset(backend,**{name:value})
        self.assertEqual(backend.calls,[])

    def test_uncertain_delete_and_cleanup_keep_original_interrupt_identity(self):
        class First(KeyboardInterrupt):
            def __str__(self):raise SystemExit('message rejected')
            def __setattr__(self,key,value):raise SystemExit('attachment rejected')
        backend=MemoryRegistry(['child']);original=First()
        def fault(row):
            if row==('delete',DONT_ASK_AGAIN_KEY+'\\child'):
                del backend.nodes[row[1]];raise original
            if row==('close',DONT_ASK_AGAIN_KEY):raise SystemExit('second cleanup interruption')
        backend.fault=fault;reset=ToolkitDontAskAgainReset(backend)
        with self.assertRaises(KeyboardInterrupt)as raised:reset.run()
        self.assertIs(raised.exception,original);self.assertIs(reset.last_error,original)
        self.assertFalse(reset.last_outcome.complete);self.assertIsNotNone(reset.last_evidence)
        self.assertEqual(len(reset.last_outcome.cleanup_errors),1)
        self.assertEqual(sum(row[0]=='delete'for row in backend.calls),1)
        self.assertEqual(backend.handles,{})

    def test_ordinary_first_error_survives_cleanup_interruption(self):
        backend=MemoryRegistry(['child']);first=OSError('read failed')
        def fault(row):
            if row[0]=='query':raise first
            if row[0]=='close':raise KeyboardInterrupt('cleanup')
        backend.fault=fault;reset=ToolkitDontAskAgainReset(backend);result=reset.run()
        self.assertIs(reset.last_error,first);self.assertFalse(result.complete)
        self.assertFalse(any(row[0]=='delete'for row in backend.calls))
        self.assertEqual(backend.handles,{})

    def test_invalid_backend_child_stops_before_open_and_stale_evidence_clears(self):
        backend=MemoryRegistry(['child'])
        backend.enum_key=lambda *args:EnumKeyResult(0,'child\\escape')
        reset=ToolkitDontAskAgainReset(backend);result=reset.run()
        self.assertFalse(result.complete);self.assertIsInstance(reset.last_error,ValueError)
        self.assertEqual(sum(row[0]=='open'for row in backend.calls),1)
        self.assertEqual(backend.handles,{})
        backend.enum_key=MemoryRegistry.enum_key.__get__(backend)
        self.assertTrue(reset.run().complete);self.assertIsNone(reset.last_error)

    def test_result_exports_do_not_alias_nested_error_or_limits(self):
        backend=MemoryRegistry();backend.fault=lambda row:(_ for _ in ()).throw(OSError('failure'))
        reset=ToolkitDontAskAgainReset(backend);result=reset.run();data=result.as_dict()
        data['operations'][0]['error_message']='changed';data['limits']['max_keys']=1
        self.assertEqual(result.operations[0]['error_message'],'failure')
        self.assertEqual(result.limits['max_keys'],256)


@unittest.skipUnless(os.environ.get('CBUS_TOOLKIT_EXE'),'requires exact original Toolkit executable')
class OriginalResetTests(unittest.TestCase):
    def test_original_handler_wrapper_recursion_and_notice(self):
        root=Path(__file__).resolve().parents[1]
        path=root/'research/toolkit_reset_original.py'
        spec=importlib.util.spec_from_file_location('toolkit_reset_original',path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        probe=module.OriginalResetProbe(os.environ['CBUS_TOOLKIT_EXE'])
        expected=json.loads((Path(__file__).resolve().parents[1]/'research/fixtures/toolkit-preferences-reset-vectors.json').read_text())
        self.assertEqual(len(expected['cases']),13)
        for row in expected['cases']:
            with self.subTest(children=row['children'],faults=row['faults']):
                self.assertEqual(probe.run(row['children'],faults=row['faults']),row)


if __name__=='__main__':unittest.main()
