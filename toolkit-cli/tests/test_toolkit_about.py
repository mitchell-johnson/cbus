"""Independent original About labels, explicit resource bytes and bounded inputs."""
import copy
import hashlib
import json
import os
from pathlib import Path
import struct
import unittest
from unittest.mock import patch

from cbus_toolkit import toolkit_about as about

ROOT = Path(__file__).resolve().parents[1]
VECTORS = ROOT/'research/fixtures/toolkit-about-vectors.json'


def executable():
    path = Path(os.environ.get('CBUS_TOOLKIT_EXE', ROOT/'research/vendor/toolkit/app/CBusToolkit.exe'))
    if not path.is_file():raise unittest.SkipTest('Pinned original Toolkit EXE is unavailable')
    return path


def fixed_locations(raw):
    import pefile
    pe=pefile.PE(data=raw)
    entry=next(x for x in pe.DIRECTORY_ENTRY_RESOURCE.entries if x.id==16).directory.entries[0].directory.entries[0].data.struct
    return pe,pe.VS_FIXEDFILEINFO[0].get_file_offset(),pe.get_offset_from_rva(entry.OffsetToData),entry


class AboutTests(unittest.TestCase):
    def test_all_51_original_formula_vectors_exact(self):
        vectors=json.loads(VECTORS.read_text());self.assertEqual(len(vectors['cases']),51)
        for row in vectors['cases']:
            case=row['input']
            with self.subTest(case=case['id']):
                value=about.format_about(None if 'failure'in case else case['version'],flags=case['flags'],
                    year=case.get('year',2026),product_name=case.get('product_name','C-Bus Toolkit'),context=case.get('context')).as_dict()
                self.assertEqual(value['captions'],row['captions'])
                self.assertEqual(value['window_caption'],row['window_caption'])
                self.assertFalse(value['context_verified_live']);self.assertFalse(value['clock_read'])
        self.assertEqual(about.format_about((1,18,0,2754),flags=42,year=2026).as_dict()['captions']['version'],
            'Version 1.18.0 Beta (build 2754)  Special Build')

    def test_context_and_word_bounds_types_and_aliases(self):
        context={'version':'3.3.2','build':'2039','max_memory_mb':512,'used_memory_mb':42,'java_version':'11'}
        report=about.format_about((1,18,0,2754),year=2026,context=context)
        context['version']='mutated';view=report.as_dict();view['captions']['product']='mutated'
        self.assertEqual(report.as_dict()['captured_context']['version'],'3.3.2')
        self.assertEqual(report.as_dict()['captions']['product'],'C-Bus Toolkit')
        for version in ((1,2,3),(1,2,3,True),(1,2,3,-1),(1,2,3,65536),'1.2.3.4'):
            with self.assertRaises(ValueError):about.format_about(version,year=2026)
        for year in (True,0,10000,'2026',2026.0):
            with self.assertRaises(ValueError):about.format_about((1,2,3,4),year=year)
        for flag in (True,-1,1<<32,'0'):
            with self.assertRaises(ValueError):about.format_about((1,2,3,4),flags=flag,year=2026)
        for key,value in (('version',True),('build','bad\0name'),('java_version','\ud800'),
                ('max_memory_mb',True),('used_memory_mb',1<<63),('max_memory_mb',-(1<<63)-1),('unknown',1)):
            with self.subTest(key=key),self.assertRaises(ValueError):
                about.format_about((1,2,3,4),year=2026,context={**context,key:value})

    def test_pinned_exe_resource_and_provenance_are_independent(self):
        raw=executable().read_bytes();before=hashlib.sha256(raw).hexdigest()
        with patch('builtins.open',side_effect=AssertionError('Unexpected file open')), \
             patch('socket.create_connection',side_effect=AssertionError('Unexpected network')):
            report=about.inspect_executable(raw,year=2026).as_dict()
        self.assertEqual(report['version'],[1,18,0,2754]);self.assertEqual(report['flags'],0)
        self.assertEqual(report['resource_product_name'],'C-Bus Toolkit')
        self.assertEqual(report['executable_sha256'],before);self.assertTrue(report['matches_pinned_toolkit_1_18'])
        self.assertEqual(report['executable_resource']['strings']['ProductVersion'],'1.18.0')
        self.assertFalse(report['original_live_application_name_provider_observed'])
        self.assertIn('substituted',report['provenance']['display_name'])
        self.assertFalse(report['executable_authenticity_verified']);self.assertFalse(report['executable_executed'])

    def test_mask_product_version_and_high_flag_bits_do_not_change_formula(self):
        raw=executable().read_bytes();_,fixed,_,_=fixed_locations(raw)
        for flags in (0,2,8,10,32,34,40,42,0xffffffff,0x1234002a):
            edited=bytearray(raw);struct.pack_into('<IIII',edited,fixed+16,0x99887766,0x55443322,0,flags)
            report=about.inspect_executable(bytes(edited),year=2026).as_dict()
            self.assertEqual(report['version'],[1,18,0,2754])
            self.assertEqual(report['captions'],about.format_about((1,18,0,2754),flags=flags,year=2026).as_dict()['captions'])
            self.assertFalse(report['executable_resource']['file_flags_mask_applied'])
            self.assertFalse(report['matches_pinned_toolkit_1_18'])

    def test_resource_display_name_is_substituted_and_absence_has_explicit_fallback(self):
        raw=executable().read_bytes();pe,_,offset,entry=fixed_locations(raw)
        blob=raw[offset:offset+entry.Size];key='ProductName'.encode('utf-16le')+b'\0\0'
        key_pos=blob.index(key);value_pos=(key_pos+len(key)+3)&~3
        altered=bytearray(raw);name='Owned Toolkit'.encode('utf-16le')
        altered[offset+value_pos:offset+value_pos+len(name)]=name
        report=about.inspect_executable(bytes(altered),year=2026).as_dict()
        self.assertEqual(report['resource_product_name'],'Owned Toolkit');self.assertEqual(report['window_caption'],'About Owned Toolkit')
        self.assertEqual(report['executable_resource']['strings']['FileDescription'],'C-Bus Toolkit')
        altered=bytearray(raw);replacement='OtherPropXX'.encode('utf-16le');self.assertEqual(len(replacement),len(key)-2)
        altered[offset+key_pos:offset+key_pos+len(replacement)]=replacement
        report=about.inspect_executable(bytes(altered),year=2026).as_dict()
        self.assertIsNone(report['resource_product_name']);self.assertEqual(report['window_caption'],'About C-Bus Toolkit')
        self.assertIn('fallback',report['provenance']['display_name'])

    def test_missing_resource_renders_original_unknown_but_malformed_rejects(self):
        raw=executable().read_bytes();pe,fixed,offset,entry=fixed_locations(raw)
        edited=bytearray(raw);directory=pe.OPTIONAL_HEADER.DATA_DIRECTORY[2].get_file_offset()
        struct.pack_into('<II',edited,directory,0,0)
        report=about.inspect_executable(bytes(edited),year=2026).as_dict()
        self.assertEqual(report['executable_resource']['status'],'missing')
        self.assertEqual(report['captions']['version'],'Version (unknown) (build unknown) ')
        for where,fmt,value in ((fixed,'<I',0),(offset,'<H',65535),(offset+2,'<H',0),
                (entry.get_file_offset()+4,'<I',0xffffffff),(entry.get_file_offset(),'<I',0xffffffff)):
            edited=bytearray(raw);struct.pack_into(fmt,edited,where,value)
            with self.subTest(where=where,fmt=fmt),self.assertRaises(ValueError):about.inspect_executable(bytes(edited),year=2026)
        for value in (b'',b'not a PE',b'X'*64,bytearray(raw)):
            with self.assertRaises(ValueError):about.inspect_executable(value,year=2026)

    def test_nested_version_blocks_duplicate_and_language_ambiguity_reject(self):
        raw=executable().read_bytes();pe,_,offset,entry=fixed_locations(raw)
        blob=raw[offset:offset+entry.Size];edited=bytearray(raw)
        for name in ('StringFileInfo','0C0904E4'):
            type_offset=offset+blob.index(name.encode('utf-16le')+b'\0\0')-2
            self.assertEqual(struct.unpack_from('<H',raw,type_offset)[0],0)
            struct.pack_into('<H',edited,type_offset,1)
        self.assertEqual(about.inspect_executable(bytes(edited),year=2026).as_dict()['captions'],
                         about.inspect_executable(raw,year=2026).as_dict()['captions'])
        resource=next(x for x in pe.DIRECTORY_ENTRY_RESOURCE.entries if x.id==16)
        for directory in (resource.directory,resource.directory.entries[0].directory):
            edited=bytearray(raw);struct.pack_into('<H',edited,directory.struct.get_file_offset()+14,2)
            with self.assertRaises(ValueError):about.inspect_executable(bytes(edited),year=2026)
        blob=bytearray(raw[offset:offset+entry.Size]);old='LegalTrademarks'.encode('utf-16le');new='FileDescription'.encode('utf-16le')
        self.assertEqual(len(old),len(new))
        start=blob.index(old);edited=bytearray(raw);edited[offset+start:offset+start+len(new)]=new
        with self.assertRaisesRegex(ValueError,'Duplicate'):about.inspect_executable(bytes(edited),year=2026)
        # Distinct block validation is independent of the later selected ProductName.
        with self.assertRaises(ValueError):about._version_tree(b'\x08\x00\xff\xff\x01\x00\x00\x00')
        name=resource.directory.entries[0];edited=bytearray(raw)
        struct.pack_into('<I',edited,name.struct.get_file_offset(),2)
        with self.assertRaises(ValueError):about.inspect_executable(bytes(edited),year=2026)

    def test_dependency_missing_and_invalid_context_precedes_pe_reader(self):
        raw=executable().read_bytes()
        with patch.dict('sys.modules',{'pefile':None}):
            with self.assertRaisesRegex(RuntimeError,'research'):about.inspect_executable(raw,year=2026)
            with self.assertRaises(ValueError):about.inspect_executable(raw,year=True)
            with self.assertRaises(ValueError):about.inspect_executable(raw,year=2026,context={})

    def test_fresh_original_menu_and_resource_instruction_probe(self):
        from research.toolkit_about_original import probe
        captured=json.loads(VECTORS.read_text());fresh=probe(executable())
        self.assertTrue(fresh['passed']);self.assertEqual(json.loads(json.dumps(fresh['cases'])),captured['cases'])
        self.assertEqual(fresh['original_executed_instructions'],captured['original_executed_instructions'])
        self.assertEqual(fresh['probe_sha256'],captured['probe_sha256'])
        self.assertFalse(fresh['ui_created']);self.assertEqual(fresh['network_calls'],0)
