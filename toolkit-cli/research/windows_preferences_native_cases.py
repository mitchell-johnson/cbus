"""Execute raw adapter/store tests only under an owned Windows HKCU namespace."""
import hashlib,json,os,struct,subprocess,sys,unittest,zipfile
from pathlib import Path
archive=Path(sys.argv[1]);namespace=sys.argv[2]
sys.path.insert(0,str(archive))
with zipfile.ZipFile(archive) as z: initial=json.loads(z.read('initial.json'))
import winreg
from cbus_toolkit.windows_preferences import WindowsPreferenceRegistry
from cbus_toolkit.toolkit_preferences_store import (
 HKCU,HKLM,TOOLKIT_KEY,CGATE_KEY,DISPLAY_KEY,DISPLAY_DEFINITIONS,PREFERENCE_DEFINITIONS,
 REG_SZ,REG_DWORD,RegistryValue,UnsupportedPreferenceEncoding,ToolkitPreferencesStore,
)
assert os.name=='nt'
with zipfile.ZipFile(archive) as z: runtime=json.loads(z.read('runtime.json'))
assert list(sys.version_info[:3])==runtime['version'] and struct.calcsize('P')*8==runtime['bits']
actual_files={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(sys.executable).parent.iterdir() if p.is_file()}
assert actual_files==runtime['files'], 'Extracted Windows Python runtime differs from the pinned release'
evidence=[];namespaces=[]

def encoded(value):
 return RegistryValue(REG_SZ,(('True' if value is True else 'False' if value is False else str(value))+'\0').encode('utf-16-le'))

def cleanup_key(path):
 try:
  with winreg.OpenKey(HKCU,path,0,winreg.KEY_READ|winreg.KEY_WOW64_32KEY) as h:
   children=[]
   while True:
    try:children.append(winreg.EnumKey(h,len(children)))
    except OSError as error:
     if error.winerror!=259:raise
     break
  for child in children:cleanup_key(path+'\\'+child)
  winreg.DeleteKeyEx(HKCU,path,winreg.KEY_WOW64_32KEY,0)
 except FileNotFoundError:pass

class NativePreferenceTests(unittest.TestCase):
 def setUp(self):
  name=namespace+'-'+str(len(namespaces)+1)
  namespaces.append(name);self.name=name
  self.registry=WindowsPreferenceRegistry(test_namespace=name)
  self.prefix='Software\\CBusToolkitCli\\Tests\\'+name
 def record(self,**values):evidence.append({'test':self._testMethodName,**values})
 def test_raw_registry_bytes_types_and_hive_separation(self):
  cases=[RegistryValue(1,'Māori \U0001f4a1\0'.encode('utf-16-le')),RegistryValue(1,b'a\0\0\0'),
         RegistryValue(1,b'\0\0'),RegistryValue(3,b''),RegistryValue(3,b'\0\xff\x80'),RegistryValue(4,b'\xff\0\0\x80')]
  for hive in (HKCU,HKLM):
   for key in (TOOLKIT_KEY,CGATE_KEY,DISPLAY_KEY):
    for i,value in enumerate(cases):
     self.registry.write_value(hive,key,'raw-'+str(i),value)
     self.assertEqual(self.registry.read_value(hive,key,'raw-'+str(i)),value)
  self.registry.write_value(HKCU,TOOLKIT_KEY,'hive-separation',encoded('user'))
  self.registry.write_value(HKLM,TOOLKIT_KEY,'hive-separation',encoded('machine'))
  self.assertEqual(self.registry.read_value(HKCU,TOOLKIT_KEY,'hive-separation'),encoded('user'))
  self.assertEqual(self.registry.read_value(HKLM,TOOLKIT_KEY,'hive-separation'),encoded('machine'))
  self.record(raw_roundtrips=36,separate_logical_hives=True)
 def test_malformed_string_writes_reject_before_key_creation(self):
  cases=[RegistryValue(1,b'a\0'),RegistryValue(1,b'\0'),RegistryValue(1,b'\0\xd8\0\0'),
         RegistryValue(2,b'a\0'),RegistryValue(7,b'a\0\0\0')]
  for value in cases:
   with self.assertRaises(ValueError):self.registry.write_value(HKCU,TOOLKIT_KEY,'bad-string',value)
  with self.assertRaises(FileNotFoundError):winreg.OpenKey(HKCU,self.prefix,0,winreg.KEY_READ|winreg.KEY_WOW64_32KEY)
  self.record(malformed_inputs_rejected=len(cases),no_key_created=True,
              native_string_contract='terminated valid UTF-16; MULTI_SZ double terminator')
 def test_default_write_creates_empty_unnamed_value_and_retains_named(self):
  r=self.registry
  for hive in (HKCU,HKLM):
   for key in (TOOLKIT_KEY,CGATE_KEY):
    r.write_value(hive,key,'sentinel',encoded('keep'))
    self.assertEqual(r.write_default_string(hive,key,''),0)
    actual,path=r._location(hive,key)
    with winreg.OpenKey(actual,path,0,winreg.KEY_QUERY_VALUE|winreg.KEY_WOW64_32KEY) as h:
     self.assertEqual(winreg.QueryValueEx(h,''),('',REG_SZ))
    self.assertEqual(r.read_value(hive,key,'sentinel'),encoded('keep'))
  self.record(empty_unnamed_values_verified=4,named_values_preserved=4)
 def test_missing_read_does_not_create_a_key(self):
  with self.assertRaises(FileNotFoundError):self.registry.read_value(HKCU,TOOLKIT_KEY,'missing')
  with self.assertRaises(FileNotFoundError):winreg.OpenKey(HKCU,self.prefix,0,winreg.KEY_READ|winreg.KEY_WOW64_32KEY)
  self.record(no_key_created=True)
 def test_invalid_inputs_reject_before_key_creation(self):
  r=self.registry
  for hive,key,name in [(0,TOOLKIT_KEY,'x'),(HKCU,'Software\\unrelated','x'),(HKCU,TOOLKIT_KEY,''),(HKCU,TOOLKIT_KEY,'x\0y')]:
   with self.assertRaises(ValueError):r.write_value(hive,key,name,encoded('x'))
  with self.assertRaises(ValueError):r.write_value(HKCU,TOOLKIT_KEY,'x',object())
  with self.assertRaises(ValueError):r.write_default_string(HKCU,TOOLKIT_KEY,'nonempty')
  with self.assertRaises(FileNotFoundError):winreg.OpenKey(HKCU,self.prefix,0,winreg.KEY_READ|winreg.KEY_WOW64_32KEY)
  self.record(no_key_created=True)
 def test_oversized_query_has_explicit_nonfallback_error(self):
  root,path=self.registry._location(HKCU,TOOLKIT_KEY)
  with winreg.CreateKeyEx(root,path,0,winreg.KEY_SET_VALUE|winreg.KEY_WOW64_32KEY) as h:
   winreg.SetValueEx(h,'oversized',0,winreg.REG_BINARY,b'x'*65537)
  with self.assertRaises(UnsupportedPreferenceEncoding):self.registry.read_value(HKCU,TOOLKIT_KEY,'oversized')
  self.record(oversized_bytes=65537,explicit_rejection=True)
 def test_full_save_load_retains_skipped_values_and_unknown_named_values(self):
  r=self.registry;values=dict(initial)
  values['Default Site']='Māori \U0001f4a1';values['FeedbackLogSize']=2700
  for spec in PREFERENCE_DEFINITIONS:
   if spec.skip_save:r.write_value(HKLM if spec.machine_first else HKCU,spec.key,spec.name,encoded(values[spec.name]))
  r.write_value(HKCU,TOOLKIT_KEY,'unrelated-sentinel',RegistryValue(3,b'preserve'))
  d=dict(zip((x[0] for x in DISPLAY_DEFINITIONS),(False,True,128,255,2)))
  saved=ToolkitPreferencesStore(r).save(values,d)
  self.assertTrue(saved.complete,saved.as_dict())
  expected_display={key:bool(int(value)&0x7f) for key,value in d.items()}
  loaded=ToolkitPreferencesStore(r).load(initial)
  self.assertTrue(loaded.complete,loaded.as_dict())
  self.assertEqual(dict(loaded.values),values)
  self.assertEqual(dict(loaded.display_values),expected_display)
  self.assertEqual(r.read_value(HKCU,TOOLKIT_KEY,'unrelated-sentinel'),RegistryValue(3,b'preserve'))
  for spec in PREFERENCE_DEFINITIONS:
   self.assertEqual(r.read_value(HKLM if spec.machine_first else HKCU,spec.key,spec.name),encoded(values[spec.name]))
  code = ("import json,sys,zipfile;sys.path.insert(0,sys.argv[1]);"
          "from cbus_toolkit.windows_preferences import WindowsPreferenceRegistry;"
          "from cbus_toolkit.toolkit_preferences_store import ToolkitPreferencesStore;"
          "v=json.loads(zipfile.ZipFile(sys.argv[1]).read('initial.json'));"
          "r=ToolkitPreferencesStore(WindowsPreferenceRegistry(test_namespace=sys.argv[2])).load(v);"
          "print(json.dumps(r.as_dict()));sys.exit(0 if r.complete else 1)")
  child=subprocess.run([sys.executable,'-I','-S','-c',code,str(archive),self.name],capture_output=True,text=True,timeout=30)
  self.assertEqual(child.returncode,0,child.stdout+child.stderr)
  self.assertFalse(child.stderr)
  independent=json.loads(child.stdout)
  self.assertEqual(independent['values'],values)
  self.assertEqual(independent['display_values'],expected_display)
  self.record(values_compared=40,display_compared=5,skipped_values_preserved=5,
              independent_process_reload_verified=True,
              named_save_operations=sum(o['action']=='write' for o in saved.operations),
              default_save_operations=len(saved.as_dict()['default_writes']),save=saved.as_dict(),load=loaded.as_dict())
 def test_missing_load_original_first_and_second_boolean_default(self):
  source=dict(initial);source['ShowProjectManager']=False
  first=ToolkitPreferencesStore(self.registry).load(source)
  self.assertTrue(first.algorithm_completed,first.as_dict())
  self.assertFalse(first.values['ShowProjectManager'])
  self.assertEqual(self.registry.read_value(HKCU,TOOLKIT_KEY,'ShowProjectManager'),encoded(True))
  second=ToolkitPreferencesStore(self.registry).load(first.values)
  self.assertTrue(second.algorithm_completed,second.as_dict())
  self.assertTrue(second.values['ShowProjectManager'])
  self.record(first_retained=False,second_loaded=True,first=first.as_dict(),second=second.as_dict())
 def test_unsupported_integer_is_not_copied_or_replaced(self):
  r=self.registry;bad=encoded('6A4')
  r.write_value(HKCU,TOOLKIT_KEY,'TemperatureUnit',bad)
  r.write_value(HKLM,TOOLKIT_KEY,'TemperatureUnit',encoded(1))
  result=ToolkitPreferencesStore(r).load(initial)
  self.assertFalse(result.complete)
  self.assertEqual(result.error['type'],'UnsupportedPreferenceEncoding')
  self.assertEqual(r.read_value(HKCU,TOOLKIT_KEY,'TemperatureUnit'),bad)
  calls=[o for o in result.operations if o['name']=='TemperatureUnit']
  self.assertEqual(len(calls),1)
  self.assertEqual(calls[0]['hive'],HKCU)
  self.record(unsupported_preserved=True,no_fallback=True)
 def test_all_handle_opens_request_original_32bit_view(self):
  old_open,old_create=winreg.OpenKey,winreg.CreateKeyEx;flags=[]
  def opened(root,path,reserved=0,access=winreg.KEY_READ):
   flags.append(access);return old_open(root,path,reserved,access)
  def created(root,path,reserved=0,access=winreg.KEY_WRITE):
   flags.append(access);return old_create(root,path,reserved,access)
  try:
   winreg.OpenKey,winreg.CreateKeyEx=opened,created
   self.registry.write_value(HKCU,TOOLKIT_KEY,'x',encoded('test'))
   self.registry.read_value(HKCU,TOOLKIT_KEY,'x')
   self.assertEqual(self.registry.write_default_string(HKLM,CGATE_KEY,''),0)
  finally:winreg.OpenKey,winreg.CreateKeyEx=old_open,old_create
  self.assertEqual(len(flags),3)
  self.assertTrue(all(flag&winreg.KEY_WOW64_32KEY for flag in flags))
  self.record(handle_access_flags=flags,explicit_32bit_view=True)

 def seed_all_preferences(self):
  saved=ToolkitPreferencesStore(self.registry).save(initial,{key:False for key,_ in DISPLAY_DEFINITIONS})
  self.assertTrue(saved.complete,saved.as_dict())
  for spec in PREFERENCE_DEFINITIONS:
   if spec.skip_save:self.registry.write_value(HKLM if spec.machine_first else HKCU,spec.key,spec.name,encoded(initial[spec.name]))
 def remove_user_value(self,name):
  root,path=self.registry._location(HKCU,TOOLKIT_KEY)
  with winreg.OpenKey(root,path,0,winreg.KEY_SET_VALUE|winreg.KEY_WOW64_32KEY) as h:
   winreg.DeleteValue(h,name)
 def test_numeric_locale_fallback_preserves_original_bytes_and_reload(self):
  self.seed_all_preferences();r=self.registry
  original=encoded('64.5');r.write_value(HKLM,TOOLKIT_KEY,'TemperatureUnit',original)
  for locale,expected in [(('.',','),64),((',','.'),645)]:
   self.remove_user_value('TemperatureUnit')
   result=ToolkitPreferencesStore(r,numeric_locale=locale).load(initial)
   self.assertTrue(result.complete,result.as_dict())
   self.assertEqual(result.values['TemperatureUnit'],expected)
   self.assertEqual(r.read_value(HKCU,TOOLKIT_KEY,'TemperatureUnit'),original)
   code=("import json,sys,zipfile;sys.path.insert(0,sys.argv[1]);"
         "from cbus_toolkit.windows_preferences import WindowsPreferenceRegistry;"
         "from cbus_toolkit.toolkit_preferences_store import ToolkitPreferencesStore;"
         "v=json.loads(zipfile.ZipFile(sys.argv[1]).read('initial.json'));"
         "s=ToolkitPreferencesStore(WindowsPreferenceRegistry(test_namespace=sys.argv[2]),numeric_locale=tuple(sys.argv[3]));"
         "r=s.load(v);print(json.dumps(r.as_dict()));sys.exit(0 if r.complete else 1)")
   child=subprocess.run([sys.executable,'-I','-S','-c',code,str(archive),self.name,''.join(locale)],capture_output=True,text=True,timeout=30)
   self.assertEqual(child.returncode,0,child.stdout+child.stderr)
   independent=json.loads(child.stdout)
   self.assertEqual(independent['values']['TemperatureUnit'],expected)
   self.assertEqual(independent['numeric_locale'],list(locale))
  self.record(locales_verified=2,raw_copy_preserved=True,independent_process_reloads=2)
 def test_numeric_known_conversion_error_copies_then_stops(self):
  self.seed_all_preferences();r=self.registry
  for locale,raw in [(('.',','),'.2.3'),((',','.'),',2,3')]:
   self.remove_user_value('TemperatureUnit')
   original=encoded(raw);r.write_value(HKLM,TOOLKIT_KEY,'TemperatureUnit',original)
   result=ToolkitPreferencesStore(r,numeric_locale=locale).load(initial)
   self.assertFalse(result.complete)
   self.assertFalse(result.algorithm_completed)
   self.assertEqual(result.error['type'],'ToolkitNumericConversionError')
   self.assertEqual(result.values['TemperatureUnit'],initial['TemperatureUnit'])
   self.assertEqual(r.read_value(HKCU,TOOLKIT_KEY,'TemperatureUnit'),original)
   calls=[row for row in result.operations if row['name']=='TemperatureUnit']
   self.assertEqual([row['action'].split('-')[0] for row in calls],['read','read','write'])
   self.assertFalse(any(row['name']=='DoNotPauseEventsWhileLoadingProject' for row in result.operations))
  self.record(locales_verified=2,known_error_raw_copy_verified=True,later_preference_not_visited=True)
 def test_numeric_unsupported_overflow_rejects_before_fallback_copy(self):
  self.seed_all_preferences();r=self.registry
  self.remove_user_value('TemperatureUnit')
  original=encoded('9223372036854775808')
  r.write_value(HKLM,TOOLKIT_KEY,'TemperatureUnit',original)
  result=ToolkitPreferencesStore(r,numeric_locale=('.',',')).load(initial)
  self.assertFalse(result.complete)
  self.assertEqual(result.error['type'],'UnsupportedPreferenceEncoding')
  with self.assertRaises(FileNotFoundError):r.read_value(HKCU,TOOLKIT_KEY,'TemperatureUnit')
  self.assertEqual(r.read_value(HKLM,TOOLKIT_KEY,'TemperatureUnit'),original)
  self.assertFalse(any(row['name']=='DoNotPauseEventsWhileLoadingProject' for row in result.operations))
  self.record(unsupported_raw_source_preserved=True,no_fallback_copy=True)

suite=unittest.defaultTestLoader.loadTestsFromTestCase(NativePreferenceTests)
result=unittest.TextTestRunner(stream=sys.stderr,verbosity=2).run(suite)
cleanup=[]
for name in namespaces:
 prefix='Software\\CBusToolkitCli\\Tests\\'+name
 try:
  cleanup_key(prefix)
  try:winreg.OpenKey(HKCU,prefix,0,winreg.KEY_READ|winreg.KEY_WOW64_32KEY)
  except FileNotFoundError:pass
  else:raise AssertionError('Owned registry cleanup did not remove namespace')
  cleanup.append({'namespace':name,'removed':True})
 except BaseException as error:cleanup.append({'namespace':name,'removed':False,'error':repr(error)})
output={'passed':result.wasSuccessful() and all(r['removed'] for r in cleanup),
 'python':sys.version,'bits':struct.calcsize('P')*8,'tests_run':result.testsRun,
 'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),
 'evidence':evidence,'cleanup':cleanup,'real_toolkit_registry_touched':False,
 'scope':'Actual Win32 registry API through x86 Python; both logical hives redirected to distinct owned HKCU subtrees; no native HKLM permission/elevation or Toolkit GUI acceptance'}
print(json.dumps(output));sys.exit(0 if output['passed'] else 1)
