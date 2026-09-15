"""Strict incoming wire inspection and unchanged original cache/CRC evidence."""
import base64
import dataclasses
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
import uuid
from unittest.mock import patch

from cbus_toolkit.pci import (AcknowledgeCAL, IdentifyCAL, ProtocolError, RecallCAL,
                              ReplyCAL, WriteCAL)
from cbus_toolkit.pci_routing import inspect_received_cal_route

ROOT=Path(__file__).resolve().parents[1]
FIXTURE=ROOT/'research/fixtures/pci-incoming-original-vectors.json'


def wire(*, header=0x86, outer=20, destination=16, route=(4,), cal=b'\x81\x04'):
    # Independent literal envelope assembly; does not use the product encoder.
    data=bytes((header,outer,destination,len(route),*route))+cal
    return (data+bytes((-sum(data)&255,))).hex().upper().encode()+b'\r'


class IncomingRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture=json.loads(FIXTURE.read_text())
        cls.original={case['input']['id']:case for case in cls.fixture['cases']}

    def test_all_original_header_and_unsigned_route_branches(self):
        admitted=rejected=0
        for header in ('06','86','46','C6'):
            for count in range(256):
                case=self.original[f'header-{header}-count-{count:03}']
                raw=case['input']['raw'].encode()+b'\r'
                with self.subTest(header=header,count=count):
                    if header in ('06','86') and count<=6:
                        value=inspect_received_cal_route(raw)
                        decoded=bytes.fromhex(case['input']['raw'])
                        self.assertEqual(value.header,int(header,16))
                        self.assertEqual(value.outer_source_byte,decoded[1])
                        self.assertEqual(value.destination_byte,16)
                        self.assertEqual(value.route_count,count)
                        self.assertEqual(value.route_entries,tuple(decoded[4:4+count]))
                        self.assertEqual(value.cal,ReplyCAL(4,b''))
                        self.assertEqual(value.checksum_byte,decoded[-1])
                        self.assertEqual(value.raw,raw)
                        admitted+=1
                    else:
                        with self.assertRaises(ProtocolError):inspect_received_cal_route(raw)
                        rejected+=1
        self.assertEqual((admitted,rejected),(14,1010))

    def test_identical_raw_bytes_keep_every_cached_projection_outside_public_result(self):
        variants=[self.original['cache-count2-depth0-'+kind] for kind in ('missing','wrong','dl','null-bridge')]
        variants+=[self.original['cache-count2-depth1-'+kind] for kind in ('missing','wrong','dl','null-bridge')]
        raws={case['input']['raw'] for case in variants}
        self.assertEqual(len(raws),1)
        observed=inspect_received_cal_route(next(iter(raws)).encode()+b'\r')
        self.assertEqual(observed.address_path,(20,21,4))
        self.assertEqual(observed.cal,ReplyCAL(4,b''))
        # The original contextual results differ (including a constructor error).
        self.assertGreater(len({case['original'].get('fields',{}).get('cj.b') for case in variants}),2)
        self.assertTrue(any(not case['original']['constructor_complete'] for case in variants))
        result=observed.as_dict()
        for key in ('source','unit','network','resolved_network','programming','working_text','constructor_fields'):
            self.assertNotIn(key,result)
        for key in ('logical_network_resolved','programming_mode_inferred','device_origin_verified','io_performed'):
            self.assertFalse(result[key])

    def test_zero_repeated_and_extreme_route_bytes_remain_literal(self):
        for header in (6,134):
            for outer,destination,route in ((0,255,()),(255,0,(0,)),(0,0,(0,0,255,255,0,0)),(255,255,(255,)*6)):
                value=inspect_received_cal_route(wire(header=header,outer=outer,destination=destination,route=route))
                self.assertEqual(value.address_path,(outer,*route))
                self.assertEqual(value.destination_byte,destination)
                self.assertEqual(value.route_count,len(route))
                self.assertFalse(value.as_dict()['programming_mode_inferred'])

    def test_every_supported_cal_family_and_exact_bytes(self):
        pairs=[(b'\x21\x04',IdentifyCAL(4)),(b'\x1a\xff\xff',RecallCAL(255,255)),
               (b'\x32\x00\xff',AcknowledgeCAL(0,255)),(b'\xa1\x00',WriteCAL(0,b'')),
               (b'\x81\xff',ReplyCAL(255,b'')),(b'\xbf\xff'+bytes(range(30)),WriteCAL(255,bytes(range(30)))),
               (b'\x9f\x00'+bytes(range(30)),ReplyCAL(0,bytes(range(30))))]
        for literal,expected in pairs:
            value=inspect_received_cal_route(wire(cal=literal))
            self.assertEqual(value.cal,expected)
            self.assertEqual(value.as_dict()['cal_hex'],literal.hex().upper())

    def test_maximum_original_single_cal_profile_and_size_before_copy(self):
        case=self.original['max-one-cal-six-route']
        raw=case['input']['raw'].encode()+b'\r'
        self.assertEqual(len(raw),87)
        value=inspect_received_cal_route(raw)
        self.assertEqual(value.cal,WriteCAL(255,bytes(range(30))))
        self.assertEqual(value.route_entries,(21,22,23,24,25,4))
        for bad in (raw+b'\r',bytearray(100000),memoryview(bytes(256)).cast('I')):
            with self.assertRaisesRegex(ProtocolError,'15..87'):inspect_received_cal_route(bad)
        class Hostile(bytearray):
            def __bytes__(self):raise AssertionError('Subclass should not be copied')
        with self.assertRaises(TypeError):inspect_received_cal_route(Hostile(raw))

    def test_exact_framing_no_control_stripping_and_case_preservation(self):
        raw=wire().lower()
        self.assertEqual(inspect_received_cal_route(raw).raw,raw)
        for bad in (raw[:-1],raw[:-1]+b'\n',raw+b'\n',raw+b'\r',b'\\'+raw,
                    raw[:-1]+b'g\r',raw[:3]+b'\x11'+raw[3:],raw[:3]+b'\x13'+raw[3:],
                    raw[:3]+b' '+raw[3:],raw[:3]+b'\r'+raw[3:],raw[:-1]+b'Z\r',raw[:3]+b'\xff'+raw[4:]):
            with self.subTest(raw=bad),self.assertRaises(ProtocolError):inspect_received_cal_route(bad)

    def test_original_lenient_domains_are_explicitly_excluded(self):
        names=('signed-count-negative','signed-count-zero','signed-count-plus','signed-source','signed-destination',
               'fullwidth-hex','odd-tail-letter','odd-tail-space','odd-tail-CR','beyond-receiver-line-bound',
               'empty-payload-constructor-not-cal-decoder','opaque-payload-constructor-not-cal-decoder',
               'multi-cal-constructor-does-not-count')
        for name in names:
            case=self.original[name]
            self.assertTrue(case['original']['private_crc_complete'])
            with self.subTest(name=name),self.assertRaises(ProtocolError):
                inspect_received_cal_route(case['input']['raw'].encode()+b'\r')

    def test_checksum_valid_truncation_and_trailing_bytes_reject(self):
        for literal in (b'\x21',b'\x1a\x04',b'\x1a\x04\x00',b'\xa0\x04',b'\x80\x04',b'\xff\xff',
                        b'\x81\x04\x81\x05',b'\x21\x04\xff',b'\x21\x04\x00',b'\x32\x04'):
            with self.subTest(cal=literal),self.assertRaises(ProtocolError):inspect_received_cal_route(wire(cal=literal))
        # Incoming count6 with no entries still has a valid original checksum.
        data=bytes((0x86,20,16,6,0x81,4))
        raw=(data+bytes((-sum(data)&255,))).hex().encode()+b'\r'
        with self.assertRaisesRegex(ProtocolError,'Truncated'):inspect_received_cal_route(raw)

    def test_checksum_precedes_cal_decoding_and_original_bytes_are_not_repaired(self):
        raw=wire(cal=b'\xff\xff')
        corrupt=raw[:-3]+(b'00' if raw[-3:-1]!=b'00' else b'01')+b'\r'
        with patch('cbus_toolkit.pci_routing.decode_cal',side_effect=AssertionError('CAL must remain unexamined')):
            with self.assertRaisesRegex(ProtocolError,'checksum'):inspect_received_cal_route(corrupt)
        good=wire();decoded=bytearray.fromhex(good[:-1].decode())
        for index in (1,2,4,5,len(decoded)-1):
            mutated=decoded[:];mutated[index]^=1
            with self.assertRaisesRegex(ProtocolError,'checksum'):
                inspect_received_cal_route(mutated.hex().encode()+b'\r')

    def test_header86_bare_overlap_never_falls_back(self):
        # A bare reply CAL starts86 and is checksum-valid, but its byte3 is not
        # a supported addressed count. The explicit addressed API must reject it.
        data=bytes((0x86,4,1,255,2,3,4))
        raw=(data+bytes((-sum(data)&255,))).hex().encode()+b'\r'
        with self.assertRaisesRegex(ProtocolError,'route count'):inspect_received_cal_route(raw)
        for header in (0x46,0xc6,0x03,0x05):
            with self.assertRaisesRegex(ProtocolError,'headers06 and86'):
                inspect_received_cal_route(wire(header=header))

    def test_immutable_detached_result_and_no_transport_calls(self):
        raw=bytearray(wire())
        with patch('socket.socket',side_effect=AssertionError('No socket')), \
             patch('cbus_toolkit.pci.PCIClient',side_effect=AssertionError('No PCI client')):
            value=inspect_received_cal_route(memoryview(raw))
        original=value.raw;raw[0]=ord('0')
        exported=value.as_dict();exported['route_entries'][0]=99;exported['address_path'][0]=99
        self.assertEqual(value.raw,original)
        self.assertEqual(value.route_entries,(4,))
        self.assertEqual(value.address_path,(20,4))
        self.assertTrue(value.as_dict()['checksum_valid'])
        with self.assertRaises(dataclasses.FrozenInstanceError):value.outer_source_byte=1
        for bad in (None,'860410008104E1\r',[1,2],True):
            with self.assertRaises(TypeError):inspect_received_cal_route(bad)


@unittest.skipUnless(sys.platform=='darwin' and all(os.environ.get(n) for n in
    ('CBUS_CGATE_JAVA','CBUS_CGATE_JAVAC','CBUS_LOCAL_CGATE_VENDOR')),
    'Explicit owned macOS JDK/compiler and original C-Gate files required')
class OriginalIncomingRouteTests(unittest.TestCase):
    def test_fresh_original_constructor_cache_and_checksum_matrix(self):
        fixture=json.loads(FIXTURE.read_text())
        source=ROOT/'research/NativeIncomingRouteProbe.java'
        java=Path(os.environ['CBUS_CGATE_JAVA']).resolve()
        javac=Path(os.environ['CBUS_CGATE_JAVAC']).resolve()
        jar=Path(os.environ['CBUS_LOCAL_CGATE_VENDOR'])/'cgate.jar'
        sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
        self.assertEqual(sha(source),fixture['source_sha256'])
        self.assertEqual(sha(jar),fixture['jar_sha256'])
        inputs=[source,jar,java,javac,java.parent.parent/'lib/modules',FIXTURE]
        before={str(p):sha(p) for p in inputs}
        destination=Path(os.environ.get('CBUS_PCI_INCOMING_REPORT_DIR',
            str(ROOT/'research/runtime/pci-incoming-original'))).resolve()/uuid.uuid4().hex
        destination.mkdir(parents=True,exist_ok=False)
        shutil.copyfile(source,destination/source.name)
        for label in ('tmp','home'):(destination/label).mkdir()
        profile=destination/'network-denied.sb'
        profile.write_text('(version 1)\n(allow default)\n(deny network*)\n')
        lines=[]
        for case in fixture['cases']:
            row=case['input'];raw='-' if row['raw'] is None else base64.b64encode(row['raw'].encode()).decode()
            lines.append('\t'.join((row['id'],raw,row['cache'],row['root'],row['ctor'],row['crc'],row['public'])))
        data='\n'.join(lines)+'\n';(destination/'input.tsv').write_text(data)
        sandbox=['/usr/bin/sandbox-exec','-f',str(profile)]
        commands=[sandbox+[str(javac),'-encoding','UTF-8','-classpath',str(jar),'-d',str(destination),str(destination/source.name)],
                  sandbox+[str(java),'-XX:-UsePerfData','-Djava.io.tmpdir='+str(destination/'tmp'),
                           '-Duser.home='+str(destination/'home'),'-Djava.awt.headless=true','-cp',str(destination)+':'+str(jar),
                           'NativeIncomingRouteProbe',str(destination/'input.tsv'),str(destination)]]
        env={'PATH':'/usr/bin:/bin','HOME':str(destination/'home'),'TMPDIR':str(destination/'tmp'),'LANG':'en_US.UTF-8'}
        report={'format':'pci-incoming-fresh-original-v1','inputs_before':before,'processes':[],
                'network_denied':True,'shared_service_or_vm_used':False,'passed':False}
        compiled_inputs=[]
        try:
            for label,command in zip(('compile','original'),commands):
                if label=='original':
                    compiled_inputs=[destination/source.name,destination/'input.tsv',profile,*sorted(destination.glob('*.class'))]
                    report['original_process_inputs_before']={str(p.relative_to(destination)):sha(p) for p in compiled_inputs}
                    (destination/'original-before.json').write_text(json.dumps(report['original_process_inputs_before'],indent=2)+'\n')
                try:result=subprocess.run(command,cwd=destination,env=env,capture_output=True,timeout=30)
                except subprocess.TimeoutExpired as error:
                    (destination/(label+'.stdout')).write_bytes(error.stdout or b'')
                    (destination/(label+'.stderr')).write_bytes(error.stderr or b'')
                    report['processes'].append({'stage':label,'timeout':True,'command':command})
                    raise
                (destination/(label+'.stdout')).write_bytes(result.stdout)
                (destination/(label+'.stderr')).write_bytes(result.stderr)
                report['processes'].append({'stage':label,'exit_code':result.returncode,'command':command})
                self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
            self.assertEqual(result.stderr,b'')
            observed=[json.loads(line) for line in result.stdout.decode().splitlines()]
            self.assertEqual(observed[0],fixture['runtime'])
            self.assertEqual(observed[-1],{'kind':'complete','cases':1142})
            self.assertEqual(observed[1:-1],[case['original'] for case in fixture['cases']])
            report['original_cases']=1142;report['passed']=True
        finally:
            report['inputs_after']={str(p):sha(p) for p in inputs}
            report['inputs_unchanged']=report['inputs_after']==before
            if compiled_inputs:
                report['original_process_inputs_after']={str(p.relative_to(destination)):sha(p) for p in compiled_inputs}
                report['original_process_inputs_unchanged']=report['original_process_inputs_after']==report['original_process_inputs_before']
            report['passed']=report['passed'] and report['inputs_unchanged'] and report.get('original_process_inputs_unchanged',False)
            report['artifact_sha256']={str(p.relative_to(destination)):sha(p) for p in destination.rglob('*') if p.is_file()}
            (destination/'report.json').write_text(json.dumps(report,indent=2)+'\n')
        self.assertTrue(report['inputs_unchanged'])
        self.assertTrue(report['original_process_inputs_unchanged'])


if __name__=='__main__':unittest.main()
