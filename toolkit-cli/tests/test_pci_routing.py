"""Literal original route transformations and independent framing guards."""
import dataclasses
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import unittest
import uuid

from cbus_toolkit.pci import (AcknowledgeCAL, IdentifyCAL, ProtocolError, RecallCAL,
                              ReplyCAL, WriteCAL)
from cbus_toolkit.pci_routing import RoutedCALCommand, inspect_routed_cal_command


def literal_cal(data):
    """Test input construction from the fixed known CAL literals, not the codec."""
    if data[0] == 0x21:
        return IdentifyCAL(data[1])
    if data[0] == 0x1A:
        return RecallCAL(data[1], data[2])
    if data[0] == 0x32:
        return AcknowledgeCAL(data[1], data[2])
    if data[0] & 0xE0 == 0x80:
        return ReplyCAL(data[1], data[2:])
    if data[0] & 0xE0 == 0xA0:
        return WriteCAL(data[1], data[2:])
    raise AssertionError('Unexpected literal fixture CAL')


class RoutedCALTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads((Path(__file__).resolve().parents[1] /
                                  'research/fixtures/pci-routing-original-vectors.json').read_text())

    def test_original_typed_vectors_and_refused_overflow(self):
        covered = steps = refused = 0
        for case in self.fixture['cases']:
            if not (case['id'].startswith(('byte-', 'direct-depth-', 'programming-depth-', 'cal-',
                                           'source-illustration-')) or case['id'] == 'repeated-address'):
                continue
            seed = bytes.fromhex(case['seed'][1:])
            mode = 'programming' if seed[2] == 9 else 'direct'
            cal = literal_cal(seed[4:] if mode == 'programming' else seed[3:])
            bridges = ()
            initial = RoutedCALCommand(seed[1], cal, addressing=mode)
            self.assertEqual(initial.encode(), case['seed'].encode()+b'\r')
            covered += 1
            for address, row in zip(case['prepend'], case['steps']):
                with self.subTest(case=case['id'], step=row['step']):
                    proposed = (address,) + bridges
                    if row['result'] == 'false':
                        with self.assertRaisesRegex(ValueError, 'six route entries'):
                            RoutedCALCommand(seed[1], cal, bridges=proposed, addressing=mode)
                        self.assertEqual(row['before'], row['after'])
                        refused += 1
                        continue
                    self.assertEqual(row['result'], 'true')
                    command = RoutedCALCommand(seed[1], cal, bridges=proposed, addressing=mode)
                    self.assertEqual(command.encode(), row['after'].encode()+b'\r')
                    self.assertEqual(command.encode(confirmation=b'g', checksum=True),
                                     (row['after']+row['checksum']+'g\r').encode())
                    observed = inspect_routed_cal_command(command.encode(checksum=True), checksum=True)
                    self.assertEqual(observed.address_path, command.address_path)
                    self.assertEqual(observed.cal, cal)
                    bridges = proposed
                    steps += 1
        self.assertEqual(covered, 341)
        self.assertGreater(steps, 400)
        self.assertEqual(refused, 5)

    def test_original_out_of_domain_and_malformed_inputs_remain_distinct(self):
        by_id = {row['id']: row for row in self.fixture['cases']}
        for value, label in ((-1, 'negative1'), (256, '256'), (65535, '65535')):
            row = by_id['outside-byte-'+label]['steps'][0]
            self.assertEqual(row['result'], 'true')
            self.assertEqual(row['after'], '\\46FF09042104')
            with self.assertRaises(ValueError):
                RoutedCALCommand(4, IdentifyCAL(4), bridges=(value,))
        for case in self.fixture['cases']:
            if case['id'].startswith('refused-field-'):
                for row in case['steps']:
                    self.assertEqual(row['result'], 'false')
                    self.assertEqual(row['after'], case['seed'])
        self.assertEqual(by_id['malformed-routing']['steps'][0]['result'], 'java.lang.NumberFormatException')

    def test_fixed_literals_zero_six_and_programming(self):
        command = RoutedCALCommand(4, IdentifyCAL(4), bridges=(30, 20))
        self.assertEqual(command.encode(), b'\\461E1214042104\r')
        self.assertEqual(command.encode(checksum=True, confirmation=b'g'), b'\\461E12140421044Dg\r')
        self.assertEqual(RoutedCALCommand(4, IdentifyCAL(4), bridges=(6,5,4,3,2,1)).encode(),
                         b'\\4606360504030201042104\r')
        self.assertEqual(RoutedCALCommand(4, IdentifyCAL(4), bridges=(20,), addressing='programming').encode(),
                         b'\\46141204002104\r')

    def test_unit_zero_programming_ambiguity_is_retained(self):
        direct = RoutedCALCommand(0, IdentifyCAL(4), bridges=(4,)).encode()
        programming = RoutedCALCommand(4, IdentifyCAL(4), addressing='programming').encode()
        self.assertEqual(direct, programming)
        result = inspect_routed_cal_command(direct)
        self.assertEqual(result.address_path, (4, 0))
        self.assertFalse(result.as_dict()['programming_mode_inferred'])
        self.assertFalse(result.as_dict()['logical_network_resolved'])
        self.assertFalse(result.as_dict()['command_sent'])
        self.assertNotIn('unit', result.as_dict())
        self.assertNotIn('source', result.as_dict())

    def test_maximum_cal_route_checksum_and_confirmation_length(self):
        command = RoutedCALCommand(255, WriteCAL(255, bytes(range(30))), bridges=(0,1,2,3,4,5))
        raw = command.encode(confirmation=b'z', checksum=True)
        self.assertEqual(len(raw), 87)
        result = inspect_routed_cal_command(raw, checksum=True)
        self.assertEqual(result.cal, command.cal)
        self.assertEqual(result.address_path, (0,1,2,3,4,5,255))
        self.assertEqual(result.confirmation, b'z')
        self.assertEqual(sum(bytes.fromhex(raw[1:-2].decode())) & 255, 0)
        oversized_view = memoryview(bytes(range(256))).cast('I')
        self.assertLess(len(oversized_view), 87)
        self.assertGreater(oversized_view.nbytes, 87)
        with self.assertRaisesRegex(ProtocolError, 'bounded outgoing'):
            inspect_routed_cal_command(oversized_view)

    def test_constructor_bytes_bounds_and_mutable_input_detachment(self):
        for name, options in [('unit', {'unit':True}), ('unit', {'unit':256}),
                              ('bridge', {'bridges':[False]}), ('bridge', {'bridges':[1.0]}),
                              ('bridge', {'bridges':[-1]})]:
            with self.subTest(options=options), self.assertRaisesRegex(ValueError, name):
                RoutedCALCommand(**{'unit':4, 'cal':IdentifyCAL(4), **options})
        for options in ({'bridges':range(3)}, {'cal':b'2104'}, {'addressing':'automatic'},
                        {'addressing':False}):
            with self.subTest(options=options), self.assertRaises((TypeError, ValueError)):
                RoutedCALCommand(**{'unit':4, 'cal':IdentifyCAL(4), **options})
        original = [20]
        command = RoutedCALCommand(4, IdentifyCAL(4), bridges=original)
        original[0] = 99
        self.assertEqual(command.bridges, (20,))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            command.unit = 5
        with self.assertRaises(ValueError):
            RoutedCALCommand(4, IdentifyCAL(4), bridges=(1,)*6, addressing='programming')
        with self.assertRaisesRegex(ValueError, 'six route entries'):
            RoutedCALCommand(4, IdentifyCAL(4), bridges=[object()]*7)

    def test_all_confirmation_bytes_and_explicit_checksum_mode(self):
        command = RoutedCALCommand(4, IdentifyCAL(4), bridges=(20,))
        for tag in range(ord('g'),ord('z')+1):
            raw = command.encode(confirmation=bytes([tag]), checksum=True)
            self.assertEqual(inspect_routed_cal_command(raw, checksum=True).confirmation, bytes([tag]))
            with self.assertRaises(ProtocolError):
                inspect_routed_cal_command(raw)
        for tag in (b'f',b'{',b'',b'gg','g',1,bytearray(b'g')):
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                command.encode(confirmation=tag)
        for value in (0,1,None,'yes'):
            with self.subTest(value=value), self.assertRaises(TypeError):command.encode(checksum=value)
            with self.subTest(value=value), self.assertRaises(TypeError):inspect_routed_cal_command(b'\\4604002104\r',checksum=value)

    def test_reserved_routing_values_and_short_routes_reject(self):
        for value in range(256):
            if value in (0,9,18,27,36,45,54):continue
            raw = b'\\'+bytes([0x46,4,value,0x21,4]).hex().encode()+b'\r'
            with self.subTest(value=value), self.assertRaisesRegex(ProtocolError, 'routing byte'):
                inspect_routed_cal_command(raw)
        for raw in (b'\\460409\r', b'\\4604120121\r',b'\\460436010203040506\r'):
            with self.subTest(raw=raw), self.assertRaises(ProtocolError):inspect_routed_cal_command(raw)

    def test_received_broadcast_bare_and_malformed_frames_reject(self):
        for raw in (b'\\05FF00FAFF00\r', b'\\031409FFFAFF00\r', b'86041000810400\r',
                    b'\\860410008104\r', b'2104\r', b'\\4604002104\r\n', b'\\4604002104\r\\4604002104\r',
                    b'\\460400210',b'\\4604002X04\r',b'\\4604002104g.\r',b'\\4604002104\x11\r',
                    b'\\'+b'00'*44+b'\r'):
            with self.subTest(raw=raw), self.assertRaises(ProtocolError):inspect_routed_cal_command(raw)
        with self.assertRaises(TypeError):inspect_routed_cal_command('\\4604002104\r')

    def test_checksum_trailing_cal_and_payload_errors_reject(self):
        for raw, checksum in ((b'\\46140904210475g\r',True), (b'\\461409042104\r',True),
                              (b'\\46040021042104\r',False), (b'\\4604001A0400\r',False),
                              (b'\\46040080\r',False),(b'\\460400BF00\r',False)):
            with self.subTest(raw=raw), self.assertRaises(ProtocolError):
                inspect_routed_cal_command(raw,checksum=checksum)

    def test_observation_detaches_raw_and_exported_paths(self):
        raw=bytearray(b'\\461409042104g\r')
        value=inspect_routed_cal_command(raw)
        raw[1]=ord('0')
        exported=value.as_dict();exported['address_path'][0]=99
        self.assertEqual(value.address_path,(20,4))
        self.assertEqual(value.raw,b'\\461409042104g\r')
        self.assertEqual(value.as_dict()['address_path'],[20,4])


@unittest.skipUnless(sys.platform == 'darwin' and all(os.environ.get(n) for n in
    ('CBUS_CGATE_JAVA','CBUS_CGATE_JAVAC','CBUS_LOCAL_CGATE_VENDOR')),
    'Explicit owned macOS JDK/compiler and original C-Gate files required')
class OriginalRoutedCALTests(unittest.TestCase):
    def test_original_method_against_frozen_matrix(self):
        root=Path(__file__).resolve().parents[1]
        fixture_path=root/'research/fixtures/pci-routing-original-vectors.json'
        fixture=json.loads(fixture_path.read_text())
        java=Path(os.environ['CBUS_CGATE_JAVA']).resolve()
        javac=Path(os.environ['CBUS_CGATE_JAVAC']).resolve()
        jar=Path(os.environ['CBUS_LOCAL_CGATE_VENDOR'])/'cgate.jar'
        source=root/'research/NativePCIRouteProbe.java'
        sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
        self.assertEqual(sha(jar),fixture['jar_sha256'])
        self.assertEqual(sha(source),fixture['source_sha256'])
        inputs=[source,jar,java,javac,java.parent.parent/'lib/modules',fixture_path]
        before={str(p):sha(p) for p in inputs}
        destination=Path(os.environ.get('CBUS_PCI_ROUTING_REPORT_DIR',
                                       str(root/'research/runtime/pci-routing-original')))/uuid.uuid4().hex
        destination.mkdir(parents=True,exist_ok=False)
        shutil.copy2(source,destination/source.name)
        profile=destination/'network-denied.sb'
        profile.write_text('(version 1)\n(allow default)\n(deny network*)\n')
        data=''.join(c['id']+'\t'+base64.b64encode(c['seed'].encode()).decode()+'\t'+
                     ','.join(map(str,c['prepend']))+'\n' for c in fixture['cases']).encode()
        (destination/'input.tsv').write_bytes(data)
        env={k:v for k,v in os.environ.items() if not k.startswith(('CBUS_','JAVA_','JDK_','_JAVA'))}
        env['TMPDIR']=str(destination)+'/'
        commands=[['/usr/bin/sandbox-exec','-f',str(profile),str(javac),
                   '-J-Djava.io.tmpdir='+str(destination),'-classpath',str(jar),'-d',str(destination),
                   str(destination/source.name)]]
        report={'format':'pci-route-fresh-original-v1','input_sha256_before':before,'processes':[],
                'shared_service_or_vm_used':False,'unexpected_loopback_connection':False}
        output=None
        try:
            compiled=subprocess.run(commands[0],env=env,capture_output=True,timeout=30)
            report['processes'].append({'stage':'compile','args':commands[0],'exit_code':compiled.returncode})
            (destination/'compile.stdout').write_bytes(compiled.stdout)
            (destination/'compile.stderr').write_bytes(compiled.stderr)
            self.assertEqual(compiled.returncode,0,compiled.stderr.decode(errors='replace'))
            with socket.socket() as listener:
                listener.bind(('127.0.0.1',0));listener.listen(1);listener.settimeout(.1)
                command=['/usr/bin/sandbox-exec','-f',str(profile),str(java),
                         '-Djava.io.tmpdir='+str(destination),'-cp',str(destination)+':'+str(jar),
                         'NativePCIRouteProbe',str(listener.getsockname()[1])]
                executed=subprocess.run(command,input=data,env=env,capture_output=True,timeout=30)
                report['processes'].append({'stage':'original','args':command,'exit_code':executed.returncode})
                (destination/'run.stdout').write_bytes(executed.stdout)
                (destination/'run.stderr').write_bytes(executed.stderr)
                try:
                    accepted,_=listener.accept();accepted.close()
                    report['unexpected_loopback_connection']=True
                except socket.timeout:
                    pass
                self.assertFalse(report['unexpected_loopback_connection'])
                self.assertEqual(executed.returncode,0,executed.stderr.decode(errors='replace'))
                self.assertEqual(executed.stderr,b'')
                output=executed.stdout.decode().splitlines()
            self.assertEqual(output[0],fixture['network_witness'])
            expected=[]
            for c in fixture['cases']:
                expected.append('SEED\t'+c['id']+'\t'+base64.b64encode(c['seed'].encode()).decode())
                for row in c['steps']:
                    expected.append('\t'.join(('STEP',c['id'],str(row['step']),row['result'],
                        base64.b64encode(row['before'].encode()).decode(),
                        base64.b64encode(row['after'].encode()).decode(),row['checksum'])))
            expected.append('COMPLETE\t358\t493\toriginal_send_methods_invoked=false')
            self.assertEqual(output[1:],expected)
            report['original_cases']=358;report['original_steps']=493
            report['matches_captured_vectors']=True
        finally:
            report['input_sha256_after']={str(p):sha(p) for p in inputs}
            report['inputs_stable']=report['input_sha256_after']==before
            report['artifact_sha256']={p.name:sha(p) for p in destination.iterdir() if p.is_file()}
            (destination/'report.json').write_text(json.dumps(report,indent=2)+'\n')
        self.assertTrue(report['inputs_stable'])


if __name__ == '__main__':
    unittest.main()
