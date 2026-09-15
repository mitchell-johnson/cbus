import json
from pathlib import Path
import unittest

from cbus_toolkit.toolkit_numeric import ToolkitNumericConversionError
from cbus_toolkit.toolkit_preferences_store import (
    CGATE_KEY, HKCU, HKLM, TOOLKIT_KEY, RegistryValue,
    ToolkitPreferencesStore, UnsupportedPreferenceEncoding, validate_numeric_locale,
)
from tests.test_toolkit_preferences_store import display, seeded, text, values

ROOT=Path(__file__).resolve().parents[1]


class NumericPreferenceStoreTests(unittest.TestCase):
    def test_explicit_locale_validation_precedes_backend_and_preserves_default(self):
        registry=seeded()
        for invalid in (True,0,{},['.',','],('.',),('.',',',''),('.', '.'),('x',','),(1,',')):
            with self.assertRaises(ValueError):ToolkitPreferencesStore(registry,numeric_locale=invalid)
            self.assertEqual(registry.calls,[])
        self.assertIsNone(validate_numeric_locale(None))
        self.assertIsNone(ToolkitPreferencesStore(registry).numeric_locale)
        for locale in (('.',','),(',','.')):
            store=ToolkitPreferencesStore(registry,numeric_locale=locale)
            self.assertEqual(store.numeric_locale,locale)
            with self.assertRaises(AttributeError):store.numeric_locale=None

    def test_all_original_manager_vectors_and_exact_copy_prefix(self):
        vectors=json.loads((ROOT/'research/fixtures/toolkit-preferences-numeric-vectors.json').read_text())
        self.assertEqual(len(vectors['cases']),40)
        for original in vectors['cases']:
            name=original['name'];key=CGATE_KEY if name=='JavaHeapMin' else TOOLKIT_KEY
            locale=(original['decimal_separator'],original['thousands_separator'])
            with self.subTest(name=name,input=original['input'],seed=original['seed'],locale=locale):
                registry=seeded();initial=values();initial[name]=17;initial['Default Language 8']=29
                for hive in (HKCU,HKLM):registry.data.pop((hive,key,name),None)
                for row in original['seed']:registry.data[int(row['hive'],16),key,name]=text(row['value'])
                registry.data[HKCU,TOOLKIT_KEY,'Default Language 8']=text('123')
                store=ToolkitPreferencesStore(registry,numeric_locale=locale);result=store.load(initial)
                self.assertEqual(result.values[name],original['after'][0]['value'])
                self.assertEqual(result.values['Default Language 8'],original['after'][1]['value'])
                actual=[row for row in result.operations if row['name']==name]
                expected=[row for row in original['trace']if row.get('name')==name and row['call']in('read','write')]
                self.assertEqual([(row['action'].split('-')[0],row['hive'])for row in actual],[(row['call'],int(row['hive'],16))for row in expected])
                self.assertEqual([row['data_hex']for row in actual if row['action'].startswith('write')],[row['utf16le_hex']for row in expected if row['call']=='write'])
                if original['error']:
                    self.assertFalse(result.complete)
                    self.assertFalse(result.algorithm_completed)
                    self.assertIsInstance(store.last_error,ToolkitNumericConversionError)
                    self.assertFalse(any(row['name']=='Default Language 8'for row in result.operations))
                    self.assertTrue(all(row['destination']=='0x606c24'for row in original['conversion_error_frames']))
                else:self.assertTrue(result.complete)
                for row in original['registry']:
                    if row['name']==name:
                        self.assertEqual(registry.data[int(row['hive'],16),key,name],text(row['value']))

    def test_canonical_default_still_rejects_extended_text_before_copy(self):
        for raw in ('6A4','64.5','NaN','2147483648','.2.3',''):
            registry=seeded();registry.data[HKCU,TOOLKIT_KEY,'TemperatureUnit']=text(raw)
            store=ToolkitPreferencesStore(registry);result=store.load(values())
            self.assertFalse(result.complete)
            self.assertIsInstance(store.last_error,UnsupportedPreferenceEncoding)
            self.assertNotIn('numeric_locale',result.as_dict())
            self.assertFalse(any(row['action'].startswith('write-preference')for row in result.operations))

    def test_unsupported_numeric_domains_never_copy_or_try_another_hive(self):
        for raw in ('9223372036854775808','-9223372036854775809','9'*65,'６４','64\0x'):
            for source in (HKCU,HKLM):
                with self.subTest(raw=raw,source=source):
                    registry=seeded();registry.data.pop((HKCU,TOOLKIT_KEY,'TemperatureUnit'))
                    registry.data[source,TOOLKIT_KEY,'TemperatureUnit']=text(raw)
                    store=ToolkitPreferencesStore(registry,numeric_locale=('.',','));result=store.load(values())
                    self.assertFalse(result.complete)
                    self.assertIsInstance(store.last_error,UnsupportedPreferenceEncoding)
                    relevant=[row for row in result.operations if row['name']=='TemperatureUnit']
                    self.assertEqual([row['action']for row in relevant],['read'] if source==HKCU else ['read','read'])
                    self.assertFalse(any(row['name']=='DoNotPauseEventsWhileLoadingProject'for row in result.operations))
                    if source==HKLM:self.assertNotIn((HKCU,TOOLKIT_KEY,'TemperatureUnit'),registry.data)

    def test_successful_fallback_copy_retains_raw_bytes_not_normalized_result(self):
        registry=seeded();registry.data.pop((HKCU,TOOLKIT_KEY,'TemperatureUnit'))
        original=RegistryValue(1,'  --0x40  \0'.encode('utf-16le'))
        registry.data[HKLM,TOOLKIT_KEY,'TemperatureUnit']=original
        store=ToolkitPreferencesStore(registry,numeric_locale=('.',','));result=store.load(values())
        self.assertTrue(result.complete)
        self.assertEqual(result.values['TemperatureUnit'],40)
        self.assertEqual(registry.data[HKCU,TOOLKIT_KEY,'TemperatureUnit'],original)
        self.assertEqual(result.as_dict()['numeric_locale'],['.',','])
        exported=result.as_dict();exported['numeric_locale'][0]='x'
        self.assertEqual(result.numeric_locale,('.',','))

    def test_failed_copy_precedes_known_parser_error_and_preserves_exact_interruption(self):
        class RejectedAttachment(KeyboardInterrupt):
            def __setattr__(self,name,value):raise SystemExit('secondary')
        for first in (OSError('copy failed'),RejectedAttachment()):
            with self.subTest(error=type(first).__name__):
                registry=seeded();registry.data.pop((HKCU,TOOLKIT_KEY,'TemperatureUnit'))
                registry.data[HKLM,TOOLKIT_KEY,'TemperatureUnit']=text('.2.3')
                def fail(row):
                    if row[:4]==('write',HKCU,TOOLKIT_KEY,'TemperatureUnit'):raise first
                registry.fault=fail
                store=ToolkitPreferencesStore(registry,numeric_locale=('.',','))
                if isinstance(first,KeyboardInterrupt):
                    with self.assertRaises(KeyboardInterrupt)as caught:store.load(values())
                    self.assertIs(caught.exception,first)
                else:self.assertFalse(store.load(values()).complete)
                self.assertIs(store.last_error,first)
                self.assertIsNotNone(store.last_evidence)
                self.assertEqual(store.last_outcome.values['TemperatureUnit'],values()['TemperatureUnit'])
                self.assertEqual(sum(row[0]=='write'and row[3]=='TemperatureUnit'for row in registry.calls),1)

    def test_save_is_identical_and_reuse_clears_previous_failure(self):
        first,second=seeded(),seeded()
        canonical=ToolkitPreferencesStore(first)
        broad=ToolkitPreferencesStore(second,numeric_locale=(',', '.'))
        second.data[HKCU,TOOLKIT_KEY,'TemperatureUnit']=text(',2,3')
        self.assertFalse(broad.load(values()).complete)
        first.calls=[];second.calls=[]
        one=canonical.save(values(),display());two=broad.save(values(),display())
        self.assertTrue(one.complete and two.complete)
        self.assertEqual(first.calls,second.calls)
        self.assertIsNone(broad.last_error)
        self.assertIs(broad.last_outcome,two)

