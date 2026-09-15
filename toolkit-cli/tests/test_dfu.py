"""Literal wire fixtures and unchanged native DLL against an independent peer."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import struct
import unittest
import zlib

from cbus_toolkit.dfu import inspect_image, parse_command, parse_status, plan_binary
from cbus_toolkit.dfu_simulator import DFUSimulator, DFUStall

DLL=os.getenv('CBUS_DFU_DLL')
REPORT=os.getenv('CBUS_DFU_REPORT')


def image(body=bytes.fromhex('0100080004000000deadbeef'), *, vid=0x166a,
          pid=0x501, device_version=0x100, version=0x100, signature=b'UFD'):
    data=body+struct.pack('<HHHH3sB',device_version,pid,vid,version,signature,16)
    return data+struct.pack('<I',zlib.crc32(data)^0xffffffff)


def dn(peer, data):
    peer.control(0x21,1,peer.next_block,0,data=data,length=len(data))
    while True:
        value=peer.control(0xa1,3,0,0,length=6)
        if value[4] not in (3,4): return value


class DFURecordsTest(unittest.TestCase):
    def test_status_literal_and_error_mapping(self):
        result=parse_status(bytes.fromhex('080102030a07'))
        self.assertEqual((result.status,result.poll_timeout_ms,result.state,result.string_index),(8,197121,10,7))
        self.assertEqual(result.native_error,-7)
        self.assertEqual(result.as_dict()['status_name'],'errADDRESS')
        self.assertFalse(result.as_dict()['device_verified'])
        for code,expected in enumerate((0,-5,-5,-12,-12,-12,-12,-12,-7,-12,-4,-4,-4,-4,-4,-11)):
            self.assertEqual(parse_status(bytes((code,0,0,0,5,0))).native_error,expected)

    def test_status_truncation_unknown_codes_and_types(self):
        for data in (b'',b'\0'*5,b'\0'*7,b'\x10'+b'\0'*5,b'\0'*4+b'\x0b\0',bytearray(6),'000000'):
            with self.assertRaises(ValueError): parse_status(data)

    def test_literal_native_command_headers(self):
        cases=(('0100080000050000','program',False,8192,1280),
               ('0800800000050000','program',True,131072,1280),
               ('0200080000050000','read',False,8192,1280),
               ('0300080000080000','check',False,8192,2048),
               ('0400080002000000','erase',False,8192,2048),
               ('0b00020002000000','erase',True,131072,131072))
        for value,name,external,address,length in cases:
            result=parse_command(bytes.fromhex(value))
            self.assertEqual((result.operation,result.external,result.address,result.length),(name,external,address,length))
        self.assertTrue(parse_command(bytes.fromhex('0601000000000000000000')).binary)
        self.assertFalse(parse_command(bytes.fromhex('0d00000000000000000000')).binary)
        self.assertEqual(parse_command(bytes.fromhex('0500000000000000')).operation,'info')
        self.assertEqual(parse_command(bytes.fromhex('0c00000000000000')).operation,'info')

    def test_external_check_is_explicitly_ambiguous(self):
        for value in ('0a00020000080000','0a00800000000200'):
            result=parse_command(bytes.fromhex(value))
            self.assertFalse(result.supported);self.assertIsNone(result.address)
            self.assertIn('conflicting',result.limitation)
        self.assertTrue(parse_command(bytes.fromhex('0a00000000000200')).supported)

    def test_command_lengths_reserved_fields_and_binary_values(self):
        for value in ('','00','0e00000000000000','01000000','0101000000000000',
                      '0400000000000100','0500000100000000','0601000000000000',
                      '0602000000000000000000','0601000000000000000001'):
            with self.assertRaises(ValueError):parse_command(bytes.fromhex(value))

    def test_image_native_literal_crc_and_optional_identity(self):
        value=bytes.fromhex('0100080004000000deadbeef000101056a16000155464410187ff0d3')
        self.assertEqual(image(),value)
        result=inspect_image(value,vendor_id=0x166a,product_id=0x501)
        self.assertTrue(result.valid);self.assertTrue(result.supported)
        self.assertEqual((result.address,result.payload_length),(8192,4))
        self.assertFalse(result.as_dict()['device_verified'])
        self.assertFalse(inspect_image(value,vendor_id=1).valid)
        self.assertFalse(inspect_image(value,product_id=2).valid)

    def test_image_checksum_format_and_payload_are_distinct(self):
        for data in (b'',b'x'*15,image()[:-1]+b'\0',image(signature=b'FOO')):
            self.assertFalse(inspect_image(data).valid)
        for value in (image(b'\x02'+bytes.fromhex('00080004000000deadbeef')),
                      image(bytes.fromhex('0101080004000000deadbeef')),image(version=0x110),
                      image(bytes.fromhex('0100080000000000'))):
            result=inspect_image(value)
            self.assertTrue(result.valid);self.assertFalse(result.supported)
        with self.assertRaises(ValueError):inspect_image(image(),vendor_id=True)
        with self.assertRaises(ValueError):inspect_image(bytearray(image()))

    def test_plan_explicit_capacity_chunking_and_native_headers(self):
        value=plan_binary(1280,address=8192,flash_size=262144,application_start=8192)
        self.assertEqual(value['program_header_hex'],'0100080000050000')
        self.assertEqual(value['data_chunk_lengths'],[1024,256])
        self.assertEqual(value['read_header_hex'],'0200080000050000')
        self.assertEqual(value['binary_enable_hex'],'0601000000000000000000')
        self.assertEqual(value['binary_disable_hex'],'0600000000000000000000')
        self.assertEqual(value['terminal_dnload_length'],0)
        json.dumps(value)
        ext=plan_binary(1,address=0,flash_size=131072,application_start=0,external=True)
        self.assertEqual(ext['program_header_hex'],'0800000001000000')

    def test_plan_preflight_limits_and_unsupported_external_address(self):
        base={'address':8192,'flash_size':262144,'application_start':8192}
        for length,extra in ((0,{}),(True,{}),(262144,{}),(4,{'address':8193}),
                             (4,{'address':0}),(4,{'external':1}),(4,{'transfer_size':10}),
                             (4,{'external':True}),(32766*1024,{'address':0,'application_start':0,'flash_size':64*1024*1024}),(64*1024*1024,{'address':0,'application_start':0,'flash_size':64*1024*1024,'transfer_size':11})):
            with self.assertRaises(ValueError):plan_binary(length,**(base|extra))


class DFUSimulatorTest(unittest.TestCase):
    def test_literal_program_read_and_independent_memory(self):
        peer=DFUSimulator(); before=bytes(peer.internal[:8192])
        self.assertEqual(dn(peer,bytes.fromhex('0100080004000000'))[0],0)
        self.assertEqual(dn(peer,bytes.fromhex('deadbeef'))[0],0)
        self.assertEqual(peer.completed_programs,0)
        self.assertEqual(dn(peer,b'')[4],2)
        dn(peer,bytes.fromhex('0601000000000000000000'))
        dn(peer,bytes.fromhex('0200080004000000'))
        self.assertEqual(peer.control(0xa1,2,peer.next_block,0,length=4),bytes.fromhex('deadbeef'))
        self.assertEqual(bytes(peer.internal[:8192]),before)
        self.assertEqual(peer.completed_programs,1)

    def test_interruption_preserves_partial_flash_and_is_not_complete(self):
        peer=DFUSimulator();dn(peer,bytes.fromhex('0100080008000000'));dn(peer,b'ABCD')
        self.assertEqual(bytes(peer.internal[8192:8200]),b'ABCD'+b'\xff'*4)
        self.assertEqual(dn(peer,b'')[0],9)
        self.assertEqual(peer.completed_programs,0);self.assertTrue(peer.snapshot()['partial_program'])
        peer.control(0x21,4,0,0)
        self.assertEqual(peer.state,2)
        self.assertEqual(bytes(peer.internal[8192:8196]),b'ABCD')
        dn(peer,bytes.fromhex('0400080001000000'))
        self.assertEqual(bytes(peer.internal[8192:9216]),b'\xff'*1024)

    def test_protected_bootloader_and_out_of_range_do_not_modify_memory(self):
        for value in ('0100000004000000','0400000001000000','0100ff0000080000'):
            peer=DFUSimulator();before=peer.snapshot()['internal_sha256']
            self.assertEqual(dn(peer,bytes.fromhex(value))[0],8)
            self.assertEqual(peer.snapshot()['internal_sha256'],before)

    def test_requires_erase_before_zero_to_one_programming(self):
        peer=DFUSimulator();dn(peer,bytes.fromhex('0100080004000000'));dn(peer,b'\0'*4);dn(peer,b'')
        dn(peer,bytes.fromhex('0100080004000000'))
        self.assertEqual(dn(peer,b'\xff'*4)[0],6)
        self.assertEqual(bytes(peer.internal[8192:8196]),b'\0'*4)
        self.assertEqual(peer.completed_programs,1)

    def test_busy_state_and_shared_block_sequence(self):
        peer=DFUSimulator()
        peer.control(0x21,1,0,0,data=bytes.fromhex('0500000000000000'),length=8)
        with self.assertRaises(DFUStall):peer.control(0x21,1,0,0,data=b'',length=0)
        self.assertEqual(peer.control(0xa1,3,0,0,length=6),bytes.fromhex('000100000400'))
        self.assertEqual(peer.control(0xa1,3,0,0,length=6),bytes.fromhex('000000000500'))
        self.assertEqual(peer.control(0xa1,2,1,0,length=22),bytes.fromhex('00040000000400000000000000000000040000200000'))
        self.assertEqual(peer.next_block,2)
        peer.control(0x21,6,0,0);self.assertEqual(peer.next_block,2)

    def test_external_zero_only_and_nonzero_operations_are_rejected(self):
        peer=DFUSimulator();dn(peer,bytes.fromhex('0800000004000000'));dn(peer,b'ABCD');dn(peer,b'')
        self.assertEqual(bytes(peer.external[:4]),b'ABCD')
        self.assertEqual(dn(peer,bytes.fromhex('0a00000004000000'))[0],5)
        peer.control(0x21,4,0,0)
        dn(peer,bytes.fromhex('0b00000001000000'))
        self.assertEqual(bytes(peer.external[:65536]),b'\xff'*65536)
        for value in ('0800010004000000','0900010004000000','0a00010004000000','0b00010001000000'):
            other=DFUSimulator();self.assertEqual(dn(other,bytes.fromhex(value))[0],15)

    def test_bad_fields_requests_and_binary_formats(self):
        peer=DFUSimulator()
        for args,kwargs in (((0xa1,3,0,1),{'length':6}),((0x21,1,0,0),{'data':b'A','length':2}),
                            ((0xa1,3,0,0),{'length':6,'data':b'X'}),((0xa1,7,0,0),{}),
                            ((0x21,4,0,0),{})):
            with self.assertRaises(DFUStall):peer.control(*args,**kwargs)
        self.assertEqual(dn(peer,bytes.fromhex('0601000000000000'))[0],15)
        with self.assertRaises(ValueError):DFUSimulator(flash_size=True)


@unittest.skipUnless(DLL,'Set CBUS_DFU_DLL to execute the original x86 vendor DLL without USB')
class NativeDFUTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path=Path(__file__).resolve().parents[1]/'research/native_dfu_probe.py'
        spec=importlib.util.spec_from_file_location('native_dfu_probe',path)
        cls.probe=importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.probe)
        cls.rows=[]

    @classmethod
    def tearDownClass(cls):
        if REPORT:
            import pefile,unicorn
            data={'schema':1,'scope':'Original x86 DLL with isolated CPU/runtime and independent memory-only DFU peer; no USB hardware or vendor firmware image',
                  'dll_sha256':hashlib.sha256(Path(DLL).read_bytes()).hexdigest(),
                  'versions':{'pefile':pefile.__version__,'unicorn':unicorn.__version__},'cases':cls.rows}
            Path(REPORT).write_text(json.dumps(data,indent=2)+'\n')

    def test_original_transport_headers_statuses_and_failure_quirks(self):
        rows=self.probe.run(Path(DLL));self.assertEqual(len(rows),44)
        self.rows.append({'name':'native-scripted-control-cases','count':44,'passed':True})

    def test_original_image_writer_reader_and_stricter_supported_scope(self):
        values=(('valid',image(),0,True),('bad-prefix',image(b'\x02'+bytes.fromhex('00080004000000deadbeef')),0,False),
                ('reserved',image(bytes.fromhex('0101080004000000deadbeef')),0,False),
                ('vid',image(vid=1),-5,False),('pid',image(pid=2),-5,False),
                ('signature',image(signature=b'FOO'),-6,False),('crc',image()[:-4]+bytes(4),-6,False),
                ('version',image(version=0x110),0,False),
                ('vid-wildcard',image(vid=65535),-5,False),('pid-wildcard',image(pid=65535),-5,False),
                ('device-wildcard',image(device_version=65535),0,True),
                ('device-other',image(device_version=0x1234),0,True))
        for name,data,expected,supported in values:
            p=self.probe.Probe(Path(DLL));self.assertEqual(p.call(0x1000F2A0),0)
            p.u.mem_write(p.DATA,data)
            result=p.call(0x1000E940,p.HANDLE,p.DATA,len(data),p.OUT)
            self.assertEqual(result,expected)
            parsed=inspect_image(data,vendor_id=0x166a,product_id=0x501)
            self.assertEqual(parsed.supported,supported)
            self.rows.append({'name':'image-'+name,'native_return':result,'python':parsed.as_dict()})
        p=self.probe.Probe(Path(DLL));p.call(0x1000F2A0)
        p.u.mem_write(p.DATA,image()[:-16]+bytes(16))
        p.call(0x1000EF80,p.HANDLE,p.DATA,len(image())-16)
        self.assertEqual(bytes(p.u.mem_read(p.DATA,len(image()))),image())
        self.rows.append({'name':'native-suffix-writer','passed':True,'synthetic_hex':image().hex()})

    def test_original_program_verify_erase_against_independent_peer(self):
        for external in (False,True):
            peer=DFUSimulator();p=self.probe.Probe(Path(DLL),peer=peer)
            if external:p.u.mem_write(p.HANDLE+0x12,struct.pack('<HH',2,0))
            payload=bytes(range(256))*5;p.u.mem_write(p.DATA,payload)
            address=0 if external else 8192
            self.assertEqual(p.call(0x10010050,p.HANDLE,p.DATA,len(payload),address,1,0,int(external)),0)
            memory=peer.external if external else peer.internal
            self.assertEqual(bytes(memory[address:address+len(payload)]),payload)
            self.assertEqual(peer.completed_programs,1);self.assertFalse(peer.binary[external])
            self.assertEqual(bytes(peer.internal[:8192]),b'\xff'*8192)
            length=65536 if external else 2048
            self.assertEqual(p.call(0x1000F9C0,p.HANDLE,address,length,1,0,int(external)),0)
            self.assertEqual(bytes(memory[address:address+length]),b'\xff'*length)
            self.assertEqual(p.call(0x1000F8C0,p.HANDLE,address,0 if external else length,int(external)),0)
            self.rows.append({'name':'peer-external-zero' if external else 'peer-internal',
                'payload_sha256':hashlib.sha256(payload).hexdigest(),'snapshot':peer.snapshot(),'wire':p.wire})

    def test_original_dfuprog_skip_option_is_forwarded_as_verify(self):
        executable=Path(DLL).resolve().parents[2]/'dfuprog.exe'
        for skip in (False,True):
            for external in (False,True):
                args=self.probe.dfuprog_download_arguments(executable,skip_flag=skip,external=external)
                self.assertEqual(args['verify'],int(skip));self.assertEqual(args['external'],int(external))
                self.assertEqual((args['address'],args['length']),(8192,1280))
                self.rows.append({'name':'dfuprog-verify-forwarding','skip_option_global':skip,
                                  'external_option_global':external,'arguments':args})

    def test_original_verification_detects_independent_readback_corruption(self):
        class CorruptRead(DFUSimulator):
            def control(self,bm,request,value,index,**kwargs):
                data=super().control(bm,request,value,index,**kwargs)
                return bytes([data[0]^1])+data[1:] if bm==0xa1 and request==2 and data else data
        peer=CorruptRead();p=self.probe.Probe(Path(DLL),peer=peer)
        p.u.mem_write(p.DATA,b'ABCD')
        result=p.call(0x10010050,p.HANDLE,p.DATA,4,8192,1,0,0)
        self.assertEqual(result,-14)
        self.assertEqual(bytes(peer.internal[8192:8196]),b'ABCD')
        self.assertFalse(peer.binary[False])
        self.rows.append({'name':'corrupt-readback','native_return':result,'snapshot':peer.snapshot()})


if __name__=='__main__':unittest.main()
