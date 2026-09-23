"""Independent serial fixtures and unchanged FirmwareUpdater assembly probes."""
import base64
import importlib.util
import json
import os
from pathlib import Path
import select
import subprocess
import tempfile
import threading
import time
import unittest
import zipfile

from cbus_toolkit.firmware_diagnostics import (
    DiagnosticError, DiagnosticParser, Identification, SerialDiagnostics,
    classify_hardware, compare_package, compare_versions, inspect_package,
    package_version, parse_identification, parse_ncc_versions,
)


ID1=b'Manufacturer=Clipsal\r\nModel=eDLT\r\nSerial Number=123\r\nVersion=1.0\r\nAuthors=A\r\nCpu_Speed=80\r\nUnit Address=20\r\n'
ID2=b'Manufacturer=Clipsal\r\nProduct=eDLT\r\nSerial Number=123\r\nHW Version=2 (Tiva)\r\nFW Version=1.5.0\r\nAuthors=A\r\nCpu_Speed=120\r\nUnit Address=20\r\n'
ID3=b'Manufacturer=Clipsal\r\nProduct=eDLT\r\nSerial Number=123\r\nHW Version=3.0 (Tiva + NCC)\r\nFW Version=1.7.0\r\nCPU Speed=120\r\nUnit Address=20\r\n'
NCC=b'NCC current version: 1.0.0\r\nNCC embedded version: 1.1.0\r\n'
MONO='mono@sha256:34d816779b1248b5cfd095770b64ecbaf1798e2aca693a91c11a018dce9c7ad5'


class FirmwareDiagnosticsTest(unittest.TestCase):
    def test_exact_hardware_variants_and_asymmetric_case(self):
        rows=((None,'StellarisPCI'),('','StellarisPCI'),(' \t','StellarisPCI'),('\u001c','Unknown'),('\u00a0','StellarisPCI'),
              ('1 (Stellaris)','StellarisPCI'),('1.0 (Stellaris + PCI)','StellarisPCI'),
              ('1 (stellaris)','Unknown'),('2 (Tiva)','TivaPCI'),('2 (tIvA)','TivaPCI'),
              ('2.0 (Tiva + PCI)','TivaPCI'),('2.0 (tiva + pci)','Unknown'),
              ('3.0 (Tiva + NCC)','TivaNCC'),('3.0 (tiva + ncc)','Unknown'),(' 2 (Tiva) ','Unknown'))
        for value,expected in rows:self.assertEqual(classify_hardware(value),expected)
        with self.assertRaises(ValueError):classify_hardware(2)

    def test_three_complete_native_identification_schemas(self):
        for i,data,variant,version in ((1,ID1,'StellarisPCI','1.0'),(2,ID2,'TivaPCI','1.5.0'),(3,ID3,'TivaNCC','1.7.0')):
            result=parse_identification(data)
            self.assertEqual(result.schemas,(f'firmware{i}',));self.assertEqual(result.variant,variant)
            self.assertEqual(result.firmware_version,version);self.assertFalse(result.ambiguous)
            self.assertFalse(result.as_dict()['firmware_contents_verified'])
            for line in data.splitlines(keepends=True):
                with self.assertRaises(DiagnosticError):parse_identification(data.replace(line,b'',1))

    def test_incremental_original_framing_and_duplicate_last_wins(self):
        parser=DiagnosticParser('id')
        parser.feed(b' Manufacturer = Clipsal\r');self.assertEqual(parser.fields,{})
        parser.feed(b'\n'+ID1.split(b'\r\n',1)[1])
        for byte in b'Version=1.7.0\r\n Banner \r\nX=a=b\r\n':parser.feed(bytes((byte,)))
        result=parser.result();self.assertEqual(result.fields['Manufacturer'],'Clipsal')
        self.assertEqual(result.fields['Version'],'1.7.0');self.assertEqual(result.fields[' Banner '],'')
        self.assertEqual(result.fields['X'],'a=b');self.assertTrue(result.ambiguous)
        self.assertEqual(parser.conflicts,{'Version'})

    def test_conflicting_legacy_and_new_firmware_identification_is_explicit(self):
        result=parse_identification(ID3+b'Version=1.0\r\n')
        self.assertEqual(result.firmware_version,'1.0');self.assertTrue(result.ambiguous)
        same=parse_identification(ID3+b'Version=1.7.0\r\n')
        self.assertFalse(same.ambiguous)

    def test_native_field_presence_is_distinct_from_usable_identity(self):
        for field in (b'Manufacturer=Clipsal',b'Product=eDLT',b'Serial Number=123',b'FW Version=1.7.0',b'Unit Address=20'):
            key=field.split(b'=')[0]+b'='
            result=parse_identification(ID3.replace(field,key))
            self.assertTrue(result.as_dict()['complete']);self.assertFalse(result.usable_identity)
        self.assertTrue(parse_identification(ID1).usable_identity)

    def test_ncc_separator_untrimmed_keys_and_status(self):
        parser=DiagnosticParser('nv')
        for byte in NCC:parser.feed(bytes((byte,)))
        parser.feed(b' X : a:b \r\n')
        result=parser.result();self.assertTrue(result.supported);self.assertTrue(result.update_available)
        self.assertEqual(result.fields[' X '],'a:b')
        self.assertTrue(result.as_dict()['complete'])
        with self.assertRaises(DiagnosticError):parse_ncc_versions(NCC.replace(b'NCC current',b' NCC current'))
        unsupported=parse_ncc_versions(b'COMMAND NOT VALID\r\n')
        self.assertFalse(unsupported.supported);self.assertFalse(unsupported.as_dict()['complete'])
        self.assertIsNone(unsupported.update_available)
        conflict=parse_ncc_versions(NCC+b'COMMAND NOT VALID\r\n')
        self.assertTrue(conflict.ambiguous);self.assertFalse(conflict.as_dict()['complete'])

    def test_version_comparison_preserves_dotnet_missing_components(self):
        for value,expected in (('1.0',-1),('1.0.0',0),('1.0.0.0',1),('01.02',1),('1. 2',1),('+1.2',1),('-0.2',-1)):
            self.assertEqual(compare_versions(value,'1.0.0'),expected)
        for value in ('1.-1','1','1.2.3.4.5','2147483648.0','','\u00a01.2','1.\u20032'):
            with self.assertRaises(ValueError):compare_versions(value,'1.0.0')
        invalid=parse_ncc_versions(NCC.replace(b'1.0.0',b''))
        self.assertFalse(invalid.as_dict()['complete']);self.assertTrue(invalid.supported)
        self.assertIsNone(invalid.update_available);self.assertTrue(invalid.reason)

    def test_parser_limits_and_incomplete_data(self):
        for parser,data in ((DiagnosticParser('id',max_bytes=2),b'abc'),(DiagnosticParser('id',max_line=2),b'abc\r\n'),
                            (DiagnosticParser('id',max_fields=1),b'A=1\r\nB=2\r\n'),(DiagnosticParser('id'),b'\x00'),
                            (DiagnosticParser('id'),b'\xff')):
            with self.assertRaises(DiagnosticError):parser.feed(data)
        with self.assertRaises(DiagnosticError):parse_identification(ID1.rstrip(b'\r\n'))
        with self.assertRaises(ValueError):DiagnosticParser('nu')
        with self.assertRaises(ValueError):DiagnosticParser('id',max_bytes=False)

    def test_package_filename_version_and_windows_path(self):
        for value,expected in (('eDLTFirmware_1.7.0.zip','1.7.0'),('plain.zip','plain'),
                               ('many_parts_1.2.zip','parts_1.2'),('_1.0.zip','1.0'),
                               (r'C:\Firmware\eDLTFirmware_1.5.0.zip','1.5.0')):
            self.assertEqual(package_version(value),expected)

    def test_archive_metadata_comparison_selection_and_ambiguity(self):
        with tempfile.TemporaryDirectory()as folder:
            path=Path(folder,'eDLTFirmware_1.7.0.zip')
            with zipfile.ZipFile(path,'w')as archive:
                for name in ('edlt_font.bin','edlt_main_hwv1.bin','edlt_main_hwv2.bin','edlt_main_hwv3.bin','MAIN_hwv3.bin'):
                    archive.writestr(name,b'fixture bytes')
            metadata=inspect_package(path)
            self.assertEqual(metadata['unknown_entries'],['MAIN_hwv3.bin'])
            self.assertEqual(metadata['version'],'1.7.0');self.assertFalse(metadata['archive_extracted'])
            self.assertEqual(list(Path(folder).iterdir()),[path])
            comparison=compare_package(parse_identification(ID3),metadata)
            self.assertTrue(comparison['metadata_match']);self.assertEqual(comparison['version_relation'],'same')
            self.assertFalse(comparison['image_contents_verified']);self.assertFalse(comparison['update_implemented'])
            with zipfile.ZipFile(path,'a')as archive:archive.writestr('second_main_hwv3.bin',b'other')
            comparison=compare_package(parse_identification(ID3),inspect_package(path))
            self.assertEqual(comparison['native_selected_image'],'second_main_hwv3.bin')
            self.assertTrue(comparison['ambiguous']);self.assertFalse(comparison['metadata_match'])
            with zipfile.ZipFile(path,'a')as archive:archive.writestr('directory/',b'')
            self.assertEqual(inspect_package(path)['native_invalid_entries'],['directory/'])

    def test_corrupt_package_is_rejected_without_extraction(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder, 'eDLTFirmware_1.7.0.zip')
            for contents in (b'', b'not a ZIP archive', b'PK\x03\x04truncated header'):
                path.write_bytes(contents)
                with self.assertRaisesRegex(ValueError, 'not a valid ZIP archive'):
                    inspect_package(path)
                self.assertEqual(path.read_bytes(), contents)
                self.assertEqual(list(Path(folder).iterdir()), [path])

    def test_serial_timeout_partial_and_no_retry(self):
        class Peer:
            def __init__(self,**kwargs):self.options=kwargs;self.writes=[];self.closed=False;self.reads=0
            def write(self,data):self.writes.append(data);return len(data)
            def read(self,size):
                self.reads+=1
                if self.reads==1:return b'Manufacturer=Clipsal\r\n'
                time.sleep(.001);return b''
            def close(self):self.closed=True
        peers=[]
        def factory(**kwargs):peer=Peer(**kwargs);peers.append(peer);return peer
        with self.assertRaises(DiagnosticError)as error:SerialDiagnostics('fixture',timeout=.02,serial_factory=factory).identify()
        self.assertEqual(error.exception.details['fields'],{'Manufacturer':'Clipsal'})
        self.assertEqual(len(peers),1);self.assertEqual(peers[0].writes,[b'id\r']);self.assertTrue(peers[0].closed)
        self.assertEqual({k:peers[0].options[k]for k in ('baudrate','bytesize','parity','stopbits','xonxoff','rtscts','dsrdtr')},
                         {'baudrate':9600,'bytesize':8,'parity':'N','stopbits':1,'xonxoff':False,'rtscts':False,'dsrdtr':False})

    def test_serial_transport_failure_closes_without_second_command(self):
        class Peer:
            closed=False
            def write(self,data):self.request=data;return len(data)
            def read(self,size):raise OSError('fixture disconnected')
            def close(self):self.closed=True
        peer=Peer()
        with self.assertRaisesRegex(DiagnosticError,'fixture disconnected'):
            SerialDiagnostics('fixture',serial_factory=lambda **kwargs:peer).ncc_versions()
        self.assertTrue(peer.closed);self.assertEqual(peer.request,b'nv\r')
        for timeout in (0,False,float('nan'),61):
            with self.assertRaises(ValueError):SerialDiagnostics('fixture',timeout=timeout)

    def test_close_failure_preserves_primary_partial_evidence(self):
        class Peer:
            reads=0
            def write(self,data):return len(data)
            def read(self,size):
                self.reads+=1
                if self.reads==1:return b'Manufacturer=Clipsal\r\n'
                raise OSError('primary disconnect')
            def close(self):raise RuntimeError('secondary close failure')
        with self.assertRaisesRegex(DiagnosticError,'primary disconnect')as error:
            SerialDiagnostics('fixture',serial_factory=lambda **kwargs:Peer()).identify()
        self.assertEqual(error.exception.details['fields'],{'Manufacturer':'Clipsal'})
        self.assertEqual(error.exception.details['close_error'],'secondary close failure')


@unittest.skipUnless(os.name=='posix'and importlib.util.find_spec('serial'),'POSIX PTY and serial extra required')
class FirmwareSerialPeerTest(unittest.TestCase):
    def exchange(self,request,response,action):
        import pty
        master,slave=pty.openpty();path=os.ttyname(slave);observed=[];errors=[]
        def peer():
            try:
                command=b''
                while not command.endswith(b'\r'):
                    if not select.select([master],[],[],2)[0]:raise AssertionError('Missing diagnostic request')
                    command+=os.read(master,128)
                observed.append(command)
                if command!=request:raise AssertionError('Unexpected request')
                for start in range(0,len(response),3):os.write(master,response[start:start+3])
            except BaseException as error:errors.append(error)
        thread=threading.Thread(target=peer);thread.start()
        try:
            result=getattr(SerialDiagnostics(path,timeout=2),action)()
            thread.join(2);self.assertFalse(thread.is_alive());self.assertEqual(errors,[]);self.assertEqual(observed,[request])
            return result
        finally:thread.join(3);os.close(master);os.close(slave)

    def test_pyserial_readonly_identity_and_ncc_against_independent_pty(self):
        for response,variant in ((ID1,'StellarisPCI'),(ID2,'TivaPCI'),(ID3,'TivaNCC')):
            self.assertEqual(self.exchange(b'id\r',response,'identify').variant,variant)
        result=self.exchange(b'nv\r',NCC,'ncc_versions');self.assertTrue(result.update_available)
        self.assertFalse(self.exchange(b'nv\r',b'COMMAND NOT VALID\r\n','ncc_versions').supported)


@unittest.skipUnless(os.environ.get('CBUS_FIRMWARE_UPDATER'),'Set original FirmwareUpdater.exe for unchanged assembly acceptance')
class FirmwareOriginalAssemblyTest(unittest.TestCase):
    def test_original_metadata_and_serial_handlers_through_linux_pty(self):
        root=Path(__file__).resolve().parents[1];app=Path(os.environ['CBUS_FIRMWARE_UPDATER']).resolve().parent
        from research.firmware_oracle import MacOSFirmwareOracle, selected_firmware_backend
        backend = selected_firmware_backend()
        oracle = MacOSFirmwareOracle(app) if backend == 'macos-mono' else None
        if oracle is not None: self.addCleanup(oracle.close)
        packages=sorted((app/'Firmware/eDLTFirmware').glob('*.zip'))
        self.assertEqual([p.name for p in packages],[f'eDLTFirmware_{version}.zip'for version in ('1.3.0','1.4.0','1.5.0','1.7.0')])
        with tempfile.TemporaryDirectory()as folder:
            Path(folder,'NativeFirmwareProbe.cs').write_bytes((root/'research/NativeFirmwareProbe.cs').read_bytes())
            if oracle is not None:
                compiled = oracle.compile()
            else:
                compiled=subprocess.run(['docker','run','--rm','-v',str(app)+':/input:ro','-v',folder+':/work','-w','/work',MONO,
                                         'mcs','-r:/input/FirmwareUpdater.exe','NativeFirmwareProbe.cs'],capture_output=True,text=True,timeout=30)
            self.assertEqual(compiled.returncode,0,compiled.stdout+compiled.stderr)
            if oracle is not None:
                native = oracle.run()
            else:
                command=['docker','run','--rm','-e','MONO_PATH=/input','-v',str(app)+':/input:ro','-v',folder+':/work','-w','/work',MONO,
                         'mono','NativeFirmwareProbe.exe']+['/input/'+str(p.relative_to(app))for p in packages]
                native=subprocess.run(command,capture_output=True,text=True,timeout=30)
            self.assertEqual(native.returncode,0,native.stdout+native.stderr)
        rows={}
        for line in native.stdout.splitlines():
            kind,key,value=line.split('\t');rows.setdefault(kind,{})[base64.b64decode(key).decode()]=base64.b64decode(value).decode()
        self.assertEqual(rows['assembly'],{'version':'1.16.3.0'})
        for value,expected in rows['variant'].items():self.assertEqual(classify_hardware(value),expected)
        for value,expected in rows['package'].items():self.assertEqual(package_version(value),expected)
        for value,expected in rows['version'].items():self.assertEqual(compare_versions(value,'1.0.0'),int(expected))
        for value in rows['version-error']:
            with self.assertRaises(ValueError):compare_versions(value,'1.0.0')
        self.assertEqual(rows['id-stage'],{'fragment-count':'0'})
        self.assertEqual(rows['id'],dict(parse_identification(ID1).fields))
        parser=DiagnosticParser('id');parser.feed(ID1);parser.feed(b'Version=1.7.0\r\n Banner \r\nX=a=b\r\n')
        self.assertEqual(rows['id-last'],{key:parser.fields[key]for key in ('Version',' Banner ','X')})
        parser=DiagnosticParser('nv');parser.feed(NCC+b' X : a:b \r\nCOMMAND NOT VALID\r\n')
        self.assertEqual(rows['ncc'],parser.fields)
        for category,data in (('complete',ID1),('schema-8',ID2),('schema-7',ID3)):
            expected=parse_identification(data).schemas
            for i in range(1,4):self.assertEqual(rows[category][f'HaveFullFirmware{i}IdResponse'],str(f'firmware{i}'in expected))
        for path in packages:
            for entry in inspect_package(path)['entries']:
                expected=f"{entry['bytes']}|{entry['encrypted']}|True|{entry['crc32']}"
                self.assertEqual(rows['archive-entry'][path.name+'/'+entry['name']],expected)
        report={'format':'cbus-firmware-diagnostic-acceptance-v1','passed':True,'original_assembly':'FirmwareUpdater '+rows['assembly']['version'],
                'hardware_variant_vectors':len(rows['variant']),'package_version_vectors':len(rows['package']),
                'dotnet_version_vectors':len(rows['version'])+len(rows['version-error']),
                'original_serial_handlers':2,'identification_schemas':3,'package_archives':len(packages),
                'package_directory_entries':len(rows.get('archive-entry',{})),
                'usb_hardware_accessed':False,'firmware_extracted':False,'firmware_written':False}
        report.update(original_backend=backend, original_stdout=native.stdout)
        if oracle is not None: report['macos_mono_evidence'] = oracle.evidence
        if os.environ.get('CBUS_FIRMWARE_DIAGNOSTIC_REPORT'):
            Path(os.environ['CBUS_FIRMWARE_DIAGNOSTIC_REPORT']).write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':unittest.main()
