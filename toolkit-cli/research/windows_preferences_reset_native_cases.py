"""Actual Windows reset tests restricted to fresh, owned HKCU namespaces."""
import hashlib,json,os,struct,sys,unittest,zipfile
from pathlib import Path
archive=Path(sys.argv[1]);namespace=sys.argv[2];sys.path.insert(0,str(archive))
import winreg
from cbus_toolkit.toolkit_preferences_reset import HKCU,DONT_ASK_AGAIN_KEY,ORIGINAL_ACCESS,ToolkitDontAskAgainReset
from cbus_toolkit.windows_preferences_reset import WindowsDontAskAgainRegistry
with zipfile.ZipFile(archive)as source:runtime=json.loads(source.read('runtime.json'))
assert os.name=='nt'and list(sys.version_info[:3])==runtime['version']and struct.calcsize('P')*8==runtime['bits']
assert {p.name:hashlib.sha256(p.read_bytes()).hexdigest()for p in Path(sys.executable).parent.iterdir()if p.is_file()}==runtime['files']
namespaces=[];evidence=[]
ACCESS=winreg.KEY_ALL_ACCESS|winreg.KEY_WOW64_32KEY

def create(path,value='fixture'):
    with winreg.CreateKeyEx(HKCU,path,0,ACCESS)as handle:
        winreg.SetValueEx(handle,'value',0,winreg.REG_SZ,value)

def exists(path):
    try:
        with winreg.OpenKey(HKCU,path,0,winreg.KEY_READ|winreg.KEY_WOW64_32KEY):return True
    except FileNotFoundError:return False

def clean(path,owned):
    assert path==owned or path.startswith(owned+'\\')
    try:
        with winreg.OpenKey(HKCU,path,0,ACCESS)as handle:
            names=[]
            while True:
                try:names.append(winreg.EnumKey(handle,len(names)))
                except OSError as error:
                    if error.winerror!=259:raise
                    break
        for name in names:clean(path+'\\'+name,owned)
        winreg.DeleteKeyEx(HKCU,path,winreg.KEY_WOW64_32KEY,0)
    except FileNotFoundError:pass

class NativeResetTests(unittest.TestCase):
    def setUp(self):
        name=namespace+'-'+str(len(namespaces)+1);namespaces.append(name)
        self.name=name;self.prefix='Software\\CBusToolkitCli\\Tests\\'+name
        self.target=self.prefix+'\\HKCU\\'+DONT_ASK_AGAIN_KEY
        self.registry=WindowsDontAskAgainRegistry(test_namespace=name)
    def record(self,**values):evidence.append({'test':self._testMethodName,**values})
    def test_missing_key_is_not_created_or_reported_deleted(self):
        result=ToolkitDontAskAgainReset(self.registry).run()
        self.assertFalse(result.complete);self.assertFalse(result.original_boolean)
        self.assertTrue(result.original_notice_requested);self.assertTrue(result.already_absent)
        self.assertFalse(result.target_delete_succeeded);self.assertFalse(result.as_dict()['absence_verified'])
        self.assertFalse(exists(self.prefix))
        self.record(result=result.as_dict())
    def test_leaf_values_deleted_and_parent_siblings_preserved(self):
        create(self.target,'delete');create(self.target+'Sibling','keep')
        parent=self.target.rsplit('\\',1)[0];create(parent,'parent')
        with winreg.OpenKey(HKCU,self.target,0,ACCESS)as h:winreg.SetValueEx(h,'',0,winreg.REG_BINARY,b'\0\xff')
        result=ToolkitDontAskAgainReset(self.registry).run()
        self.assertTrue(result.complete,result.as_dict());self.assertFalse(exists(self.target))
        for path,value in ((parent,'parent'),(self.target+'Sibling','keep')):
            with winreg.OpenKey(HKCU,path,0,ACCESS)as h:self.assertEqual(winreg.QueryValueEx(h,'value')[0],value)
        self.assertEqual(self.registry._handles,{})
        self.record(result=result.as_dict(),parent_and_sibling_preserved=True)
    def test_unicode_tree_uses_descending_enumeration_and_postorder_deletion(self):
        for name in ('Māori','🙂','Māori\\Nested'):create(self.target+'\\'+name)
        with winreg.OpenKey(HKCU,self.target,0,ACCESS)as h:names=[winreg.EnumKey(h,i)for i in range(2)]
        result=ToolkitDontAskAgainReset(self.registry).run();self.assertTrue(result.complete,result.as_dict())
        selected=[row['name']for row in result.operations if row['operation']=='enumerate'and row['path']==DONT_ASK_AGAIN_KEY]
        self.assertEqual(selected,list(reversed(names)))
        deletes=[row['path']for row in result.operations if row['operation']=='delete']
        self.assertEqual(deletes[-1],DONT_ASK_AGAIN_KEY)
        self.assertLess(deletes.index(DONT_ASK_AGAIN_KEY+'\\Māori\\Nested'),deletes.index(DONT_ASK_AGAIN_KEY+'\\Māori'))
        self.assertFalse(exists(self.target));self.assertEqual(self.registry._handles,{})
        self.record(result=result.as_dict(),original_enumeration=names)
    def test_bound_stops_without_deletion_then_explicit_larger_bound_succeeds(self):
        create(self.target+'\\a');create(self.target+'\\b')
        first=ToolkitDontAskAgainReset(self.registry,max_keys=1).run()
        self.assertFalse(first.complete);self.assertEqual(first.error['type'],'ResetLimitExceeded')
        self.assertFalse(any(row['operation']=='delete'for row in first.operations))
        self.assertTrue(exists(self.target+'\\a')and exists(self.target+'\\b'));self.assertEqual(self.registry._handles,{})
        second=ToolkitDontAskAgainReset(self.registry,max_keys=3).run()
        self.assertTrue(second.complete,second.as_dict())
        self.record(first=first.as_dict(),separate_larger_bound_run=second.as_dict())
    def test_scope_guards_precede_any_key_creation_or_access(self):
        r=self.registry
        for parent,key in ((0x80000002,DONT_ASK_AGAIN_KEY),(HKCU,'Software\\unrelated'),(HKCU,DONT_ASK_AGAIN_KEY+'\\child'),(0,DONT_ASK_AGAIN_KEY)):
            with self.assertRaises(ValueError):r.open_key(parent,key,ORIGINAL_ACCESS)
            with self.assertRaises(ValueError):r.delete_key(parent,key)
        with self.assertRaises(ValueError):r.open_key(HKCU,DONT_ASK_AGAIN_KEY,0)
        for operation in (r.close_key,r.query_info):
            with self.assertRaises(ValueError):operation(HKCU)
        with self.assertRaises(ValueError):r.enum_key(1,0,256)
        self.assertFalse(exists(self.prefix));self.assertEqual(r._handles,{})
        self.record(no_registry_key_created=True)
    def test_all_open_delete_calls_select_original_32_bit_view(self):
        create(self.target);r=self.registry;opened,deleted=r._open,r._delete;flags=[]
        def opening(*args):flags.append(('open',args[3]));return opened(*args)
        def deleting(*args):flags.append(('delete',args[2]));return deleted(*args)
        r._open,r._delete=opening,deleting
        result=ToolkitDontAskAgainReset(r).run();self.assertTrue(result.complete)
        self.assertEqual(len(flags),2);self.assertTrue(all(value&winreg.KEY_WOW64_32KEY for _,value in flags))
        self.record(flags=flags,result=result.as_dict())
    def test_interrupted_actual_child_deletion_keeps_prefix_and_closes_parent(self):
        class First(KeyboardInterrupt):
            def __setattr__(self,key,value):raise SystemExit('rejected attachment')
        create(self.target+'\\child');r=self.registry;delete=r.delete_key;first=First()
        def interrupted(parent,key):
            code=delete(parent,key)
            if key=='child'and code==0:raise first
            return code
        r.delete_key=interrupted;reset=ToolkitDontAskAgainReset(r)
        with self.assertRaises(KeyboardInterrupt)as caught:reset.run()
        self.assertIs(caught.exception,first);self.assertIs(reset.last_error,first)
        self.assertFalse(exists(self.target+'\\child'));self.assertTrue(exists(self.target))
        self.assertEqual(r._handles,{})
        self.assertEqual(sum(row['operation']=='delete'for row in reset.last_outcome.operations),1)
        self.record(result=reset.last_evidence,actual_child_deleted=True,actual_parent_preserved=True)
    def test_handles_cannot_cross_adapter_ownership(self):
        create(self.target);one=self.registry;two=WindowsDontAskAgainRegistry(test_namespace=self.name)
        opened=one.open_key(HKCU,DONT_ASK_AGAIN_KEY,ORIGINAL_ACCESS);self.assertEqual(opened.status,0)
        try:
            with self.assertRaises(ValueError):two.query_info(opened.handle)
            with self.assertRaises(ValueError):two.close_key(opened.handle)
            with self.assertRaises(ValueError):two.delete_key(opened.handle,'child')
        finally:self.assertEqual(one.close_key(opened.handle),0)
        self.assertEqual(one._handles,{});self.assertEqual(two._handles,{})
        self.record(cross_adapter_handles_rejected=True)

result=unittest.TextTestRunner(stream=sys.stderr,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(NativeResetTests))
cleanup=[]
for name in namespaces:
    prefix='Software\\CBusToolkitCli\\Tests\\'+name
    try:clean(prefix,prefix);assert not exists(prefix);cleanup.append({'namespace':name,'removed':True})
    except BaseException as error:cleanup.append({'namespace':name,'removed':False,'error':repr(error)})
outcome={'passed':result.wasSuccessful()and all(row['removed']for row in cleanup),'python':sys.version,'bits':struct.calcsize('P')*8,'tests_run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),'evidence':evidence,'cleanup':cleanup,'real_toolkit_registry_touched':False,'scope':'Actual Windows registry API, exact32-bit view, fresh owned HKCU subtree only; no Toolkit GUI/notice or real user registry changes.'}
print(json.dumps(outcome));raise SystemExit(0 if outcome['passed']else 1)
