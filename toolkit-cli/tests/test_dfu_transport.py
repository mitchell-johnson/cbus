"""Strict host client vs literal descriptor/control faults and independent flash."""
import importlib.util
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from cbus_toolkit.dfu_transport import (ControlReply, DFUClient, DFUOperationError,
    MemoryEndpoint0, parse_descriptors)
from cbus_toolkit.dfu_simulator import DFUSimulator

DEVICE=bytes.fromhex('12010002000000406a160105341201020301')
CONFIG=bytes.fromhex('09021b0001010080320904000000fe010200092107e80300040001')
DLL=os.getenv('CBUS_DFU_DLL')
REPORT=os.getenv('CBUS_DFU_TRANSPORT_REPORT')
EVIDENCE=[]

def record(name,outcome,peer):
    EVIDENCE.append({'name':name,'outcome':outcome.as_dict(),'peer':peer.snapshot()})


class Clock:
    def __init__(self):self.now=0.;self.sleeps=[]
    def __call__(self):return self.now
    def sleep(self,value):self.sleeps.append(value);self.now+=value


class Service(MemoryEndpoint0):
    def __init__(self,peer=None,*,fault=None):
        super().__init__(peer or DFUSimulator(),parse_descriptors(DEVICE,CONFIG));self.requests=[];self.fault=fault
    def control(self,bm,request,value,index,**kwargs):
        self.requests.append((bm,request,value,index,kwargs))
        actual=super().control(bm,request,value,index,**kwargs)
        return self.fault(self,bm,request,value,kwargs,actual) if self.fault else actual


def client(service,clock=None,**kwargs):
    timer=clock or Clock()
    return DFUClient(service,parse_descriptors(DEVICE,CONFIG),flash_size=kwargs.pop('flash_size',262144),
        application_start=kwargs.pop('application_start',8192),clock=timer,sleep=timer.sleep,**kwargs)


class DescriptorTest(unittest.TestCase):
    def test_literal_descriptor_and_public_metadata(self):
        value=parse_descriptors(DEVICE,CONFIG)
        self.assertEqual((value.vendor_id,value.product_id,value.device_version),(0x166a,0x501,0x1234))
        self.assertEqual((value.interface,value.attributes,value.transfer_size,value.detach_timeout_ms),(0,7,1024,1000))
        self.assertEqual(value.serial_index,3);json.dumps(value.as_dict())

    def test_native_permissive_cases_are_rejected_without_any_service(self):
        variants=[(DEVICE,CONFIG[:25]+b'\0\0'+CONFIG[27:]),
                  (DEVICE,CONFIG[:16]+b'\x01'+CONFIG[17:]),
                  (DEVICE,CONFIG[:18]),(DEVICE,CONFIG[:18]+b'\x00'+CONFIG[19:]),
                  (DEVICE,CONFIG[:9]+b'\0'+CONFIG[10:])]
        for device,configuration in variants:
            with self.assertRaises(ValueError):parse_descriptors(device,configuration)

    def test_header_lengths_identity_reserved_bits_and_count(self):
        variants=[(DEVICE[:-1],CONFIG),(b'\x11'+DEVICE[1:],CONFIG),
                  (DEVICE[:8]+b'\xff\xff'+DEVICE[10:],CONFIG),
                  (DEVICE[:7]+b'\0'+DEVICE[8:],CONFIG),
                  (DEVICE[:-1]+b'\0',CONFIG),(DEVICE,CONFIG[:2]+b'\xff\xff'+CONFIG[4:]),
                  (DEVICE,CONFIG[:4]+b'\x02'+CONFIG[5:]),
                  (DEVICE,CONFIG[:5]+b'\0'+CONFIG[6:]),
                  (DEVICE,CONFIG[:7]+b'\x81'+CONFIG[8:]),
                  (DEVICE,CONFIG[:20]+b'\x01'+CONFIG[21:]),
                  (DEVICE,CONFIG[:20]+b'\x87'+CONFIG[21:])]
        for device,configuration in variants:
            with self.subTest(device=device.hex(),configuration=configuration.hex()):
                with self.assertRaises(ValueError):parse_descriptors(device,configuration)

    def test_duplicate_or_misassociated_functional_descriptors(self):
        for body,count in ((CONFIG[9:]+CONFIG[18:],1),(CONFIG[9:]+CONFIG[9:],1),
                           (CONFIG[18:]+CONFIG[9:18],1),
                           (CONFIG[9:]+bytes.fromhex('0904010000fe010200')+CONFIG[18:],2)):
            config=CONFIG[:2]+(9+len(body)).to_bytes(2,'little')+bytes([count])+CONFIG[5:9]+body
            with self.assertRaises(ValueError):parse_descriptors(DEVICE,config)


class DFUClientTest(unittest.TestCase):
    def test_public_preflight_reuses_execution_validation_without_any_transport(self):
        descriptor=parse_descriptors(DEVICE,CONFIG)
        with patch.object(DFUClient,'_run',side_effect=AssertionError('Preflight must not execute')):
            inspection=DFUClient.preflight(descriptor,operation='inspect',flash_size=262144,application_start=8192)
            program=DFUClient.preflight(descriptor,operation='program',flash_size=262144,application_start=8192,
                                        data=b'ABCD',address=8192)
            erase=DFUClient.preflight(descriptor,operation='erase',flash_size=262144,application_start=8192,
                                      address=8192,length=2048)
        self.assertFalse(inspection['transport_acquired']);self.assertEqual(program['length'],4)
        self.assertEqual(erase['data_chunks'],2);self.assertIsNotNone(program['payload_sha256'])
        invalid=[{'operation':'other'},{'external':1},{'timeout':0},{'poll_limit':0},
                 {'flash_size':262145},{'application_start':1},
                 {'operation':'inspect','address':8192},{'operation':'inspect','data':b'X'},
                 {'operation':'program','data':b'','address':8192},
                 {'operation':'program','data':b'X','address':0},
                 {'operation':'program','data':b'X','address':8192,'length':1},
                 {'operation':'erase','address':8192,'length':1},
                 {'operation':'erase','address':8192,'length':1024,'data':b'X'}]
        for options in invalid:
            with self.assertRaises(ValueError):DFUClient.preflight(descriptor,**{
                'operation':'inspect','flash_size':262144,'application_start':8192,**options})

    def test_preflight_program_sequence_boundary_matches_execution_before_io(self):
        descriptor=parse_descriptors(DEVICE,CONFIG)
        # At1024 bytes/transfer, this crosses the inspection+program+readback sequence bound.
        data=b'X'*(32765*1024)
        with self.assertRaises(ValueError):DFUClient.preflight(descriptor,operation='program',
            flash_size=64*1024*1024,application_start=8192,data=data,address=8192)
        service=Service();api=client(service,flash_size=64*1024*1024)
        with self.assertRaises(ValueError):api.program(data,address=8192)
        self.assertEqual(service.requests,[])

    def test_inspect_geometry_and_closes_one_operation_session(self):
        service=Service();api=client(service);result=api.inspect()
        self.assertTrue(result.complete);self.assertEqual(result.info['flash_size'],262144)
        self.assertFalse(result.as_dict()['peer_verified']);self.assertTrue(service.closed)
        with self.assertRaises(RuntimeError):api.inspect()
        self.assertFalse(service.peer.snapshot()['partial_program'])
        record('inspect',result,service.peer)

    def test_program_full_readback_and_protected_bytes(self):
        service=Service();data=bytes(range(256))*5
        result=client(service).program(data,address=8192)
        self.assertTrue(result.complete);self.assertEqual(result.payload_transferred,1280)
        self.assertEqual(result.readback_bytes,1280)
        self.assertEqual(result.expected_sha256,result.readback_sha256)
        self.assertTrue(result.as_dict()['peer_verified']);self.assertFalse(result.as_dict()['physical_device_verified'])
        self.assertEqual(bytes(service.peer.internal[8192:9472]),data)
        self.assertEqual(bytes(service.peer.internal[:8192]),b'\xff'*8192)
        self.assertFalse(service.peer.binary[False]);self.assertEqual(service.peer.state,2)
        self.assertEqual(service.peer.completed_programs,1)
        values=[request[2] for request in service.requests if request[:2] in ((0x21,1),(0xa1,2))]
        self.assertEqual(values,list(range(len(values))))
        json.dumps(result.as_dict())
        record('program-internal',result,service.peer)

    def test_erase_reads_every_requested_byte(self):
        peer=DFUSimulator();peer.internal[8192:11264]=b'\0'*3072
        result=client(Service(peer)).erase(address=8192,length=2048)
        self.assertTrue(result.complete);self.assertEqual(result.readback_bytes,2048)
        self.assertEqual(bytes(peer.internal[8192:10240]),b'\xff'*2048)
        self.assertEqual(bytes(peer.internal[10240:11264]),b'\0'*1024)
        self.assertEqual(result.payload_transferred,0)
        record('erase-internal',result,peer)

    def test_large_erase_uses_exact_block_count_instead_of_native_arithmetic_bug(self):
        peer=DFUSimulator(flash_size=4*1024*1024)
        length=2*1024*1024;peer.internal[8192:8192+length+2048]=b'\0'*(length+2048)
        service=Service(peer);result=client(service,flash_size=4*1024*1024).erase(address=8192,length=length)
        self.assertTrue(result.complete);self.assertEqual(result.readback_bytes,length)
        self.assertEqual(bytes(peer.internal[8192:8192+length]),b'\xff'*length)
        self.assertEqual(bytes(peer.internal[8192+length:8192+length+2048]),b'\0'*2048)
        headers=[row[4]['data'].hex() for row in service.requests if row[4]['data'][:1]==b'\x04']
        self.assertEqual(headers,['0400080000080000'])
        record('large-erase-exact-range',result,peer)

    def test_external_zero_program_and_erase(self):
        peer=DFUSimulator();data=b'FONTS!'
        result=client(Service(peer),flash_size=131072,application_start=0,external=True).program(data,address=0)
        self.assertTrue(result.complete);self.assertEqual(bytes(peer.external[:6]),data)
        other=DFUSimulator();other.external[:65536]=b'\0'*65536
        erased=client(Service(other),flash_size=131072,application_start=0,external=True).erase(address=0,length=65536)
        self.assertTrue(erased.complete);self.assertEqual(erased.readback_bytes,65536)
        self.assertEqual(bytes(other.external[:65536]),b'\xff'*65536)
        record('program-external-zero',result,peer);record('erase-external-zero',erased,other)

    def test_all_bounds_fail_before_any_service_request(self):
        for method,kwargs in (('program',{'data':b'','address':8192}),('program',{'data':b'x','address':8193}),
                              ('program',{'data':b'x','address':0}),('erase',{'address':8192,'length':1023}),
                              ('erase',{'address':8192,'length':262144})):
            service=Service();api=client(service)
            with self.assertRaises(ValueError):getattr(api,method)(**kwargs)
            self.assertFalse(service.requests);self.assertFalse(service.closed)
        for options in ({'timeout':False},{'timeout':float('inf')},{'poll_limit':0},
                        {'flash_size':262143},{'application_start':1},{'external':1}):
            with self.assertRaises(ValueError):client(Service(),**options)

    def test_geometry_mismatch_and_no_extension_never_send_program(self):
        def no_extensions(s,bm,request,value,kwargs,reply):
            return ControlReply(True,4,b'NOPE') if request==0x42 else reply
        for service,options in ((Service(),{'flash_size':524288}),(Service(fault=no_extensions),{})):
            with self.assertRaises(DFUOperationError) as failure:client(service,**options).program(b'ABCD',address=8192)
            self.assertFalse(failure.exception.outcome.complete);self.assertTrue(service.closed)
            self.assertEqual(service.peer.completed_programs,0)
            self.assertFalse(any(r[4]['data'][:1]==b'\x01' for r in service.requests))

    def test_initial_non_idle_and_native_unknown_state_are_not_recovered(self):
        for state in (0,1,3,4,5,6,7,8,9,10,11):
            def status(s,bm,request,value,kwargs,reply):
                return ControlReply(True,6,bytes([0,0,0,0,state,0])) if request==3 else reply
            service=Service(fault=status)
            with self.assertRaises(DFUOperationError):client(service).inspect()
            self.assertEqual(len(service.requests),4);self.assertTrue(service.closed)

    def test_short_failed_and_malformed_replies_invalidate_without_further_io(self):
        values=(ControlReply(True,5,b'\0'*5),ControlReply(False,6,b'\0'*6),
                ControlReply(True,6,b'\0'*5),ControlReply(True,True,b'\0'*6),None)
        for value in values:
            service=Service(fault=lambda *args:value)
            with self.assertRaises(DFUOperationError) as failure:client(service).inspect()
            self.assertFalse(failure.exception.outcome.outcome_known)
            self.assertEqual(len(service.requests),1);self.assertTrue(service.closed)

    def test_fetched_descriptors_cannot_be_replaced_by_expected_metadata(self):
        def wrong_device(s,bm,request,value,kwargs,reply):
            if bm==0x80 and value==0x100:
                return ControlReply(True,18,reply.data[:10]+b'\x02\x05'+reply.data[12:])
            return reply
        def short_configuration(s,bm,request,value,kwargs,reply):
            if bm==0x80 and value==0x200:
                return ControlReply(True,reply.transferred-1,reply.data[:-1])
            return reply
        for fault in (wrong_device,short_configuration):
            service=Service(fault=fault)
            with self.assertRaises(DFUOperationError):client(service).program(b'ABCD',address=8192)
            self.assertFalse(any(request[0]==0x21 for request in service.requests))
            self.assertEqual(service.peer.programmed_bytes,0);self.assertTrue(service.closed)

    def test_short_or_failed_status_is_rejected_after_valid_descriptors(self):
        for value in (ControlReply(True,5,b'\0'*5),ControlReply(False,6,b'\0'*6)):
            def fault(s,bm,request,sequence,kwargs,reply):return value if bm==0xa1 and request==3 else reply
            service=Service(fault=fault)
            with self.assertRaises(DFUOperationError):client(service).inspect()
            self.assertEqual(len(service.requests),4);self.assertTrue(service.closed)

    def test_short_program_ack_and_native_program_failure_stop_without_cleanup(self):
        def short_ack(s,bm,request,value,kwargs,reply):
            return ControlReply(True,3) if kwargs['data']==b'ABCD' else reply
        service=Service(fault=short_ack)
        with self.assertRaises(DFUOperationError) as short:client(service).program(b'ABCD',address=8192)
        self.assertFalse(short.exception.outcome.outcome_known)
        self.assertEqual(bytes(service.peer.internal[8192:8196]),b'ABCD')
        self.assertEqual(service.requests[-1][4]['data'],b'ABCD');self.assertTrue(service.closed)
        record('short-program-ack',short.exception.outcome,service.peer)
        other=Service();other.peer.internal[8192:8196]=b'\0'*4
        with self.assertRaises(DFUOperationError) as native:client(other).program(b'\xff'*4,address=8192)
        self.assertTrue(native.exception.outcome.outcome_known)
        self.assertEqual(native.exception.outcome.payload_transferred,4)
        self.assertEqual(other.peer.state,10);self.assertEqual(other.peer.completed_programs,0)
        self.assertEqual(other.requests[-1][:2],(0xa1,3));self.assertTrue(other.closed)
        record('native-program-error',native.exception.outcome,other.peer)

    def test_program_transfer_timeout_preserves_actual_partial_flash_and_never_replays(self):
        def uncertain(s,bm,request,value,kwargs,reply):
            if kwargs['data']==b'ABCD':raise TimeoutError('ACK lost after peer write')
            return reply
        service=Service(fault=uncertain);api=client(service)
        with self.assertRaises(DFUOperationError) as failure:api.program(b'ABCD',address=8192)
        outcome=failure.exception.outcome
        self.assertFalse(outcome.outcome_known);self.assertEqual(outcome.stage,'program-data')
        self.assertEqual(bytes(service.peer.internal[8192:8196]),b'ABCD')
        self.assertEqual(service.peer.completed_programs,0)
        self.assertEqual(sum(r[4]['data']==b'ABCD' for r in service.requests),1)
        count=len(service.requests)
        with self.assertRaises(RuntimeError):api.program(b'ABCD',address=8192)
        self.assertEqual(len(service.requests),count);self.assertTrue(service.closed)
        record('lost-program-ack',outcome,service.peer)

    def test_readback_corruption_is_known_failure_with_cleanup(self):
        def corrupt(s,bm,request,value,kwargs,reply):
            if bm==0xa1 and request==2 and kwargs['length']!=22:
                return ControlReply(True,reply.transferred,bytes([reply.data[0]^1])+reply.data[1:])
            return reply
        service=Service(fault=corrupt)
        with self.assertRaises(DFUOperationError) as failure:client(service).program(b'ABCD',address=8192)
        outcome=failure.exception.outcome
        self.assertTrue(outcome.outcome_known);self.assertEqual(outcome.first_mismatch,8192)
        self.assertEqual(outcome.readback_bytes,4);self.assertFalse(service.peer.binary[False])
        self.assertEqual(service.peer.state,2);self.assertTrue(service.closed)
        record('readback-corruption',outcome,service.peer)

    def test_busy_deadline_and_poll_limit_are_bounded(self):
        for timeout,limit in ((0.01,256),(100,3)):
            calls=0
            def busy(s,bm,request,value,kwargs,reply):
                nonlocal calls
                if request==3:
                    calls+=1
                    if calls>1:return ControlReply(True,6,bytes.fromhex('006400000400'))
                return reply
            timer=Clock();service=Service(fault=busy)
            with self.assertRaises(DFUOperationError) as failure:client(service,timer,timeout=timeout,poll_limit=limit).inspect()
            self.assertFalse(failure.exception.outcome.outcome_known)
            self.assertLessEqual(timer.now,timeout);self.assertLessEqual(calls,limit+1)
            self.assertTrue(service.closed)

    def test_transport_return_after_deadline_is_rejected(self):
        timer=Clock()
        def late(s,bm,request,value,kwargs,reply):timer.now+=2;return reply
        service=Service(fault=late)
        with self.assertRaises(DFUOperationError) as failure:client(service,timer,timeout=1).inspect()
        self.assertIn('deadline',str(failure.exception));self.assertEqual(len(service.requests),1)

    def test_close_failure_does_not_erase_completed_readback_evidence(self):
        class BadClose(Service):
            def close(self):raise RuntimeError('close fault')
        peer=BadClose()
        with self.assertRaises(DFUOperationError) as failure:client(peer).program(b'ABCD',address=8192)
        result=failure.exception.outcome
        self.assertFalse(result.complete);self.assertEqual(result.stage,'close')
        self.assertTrue(result.outcome_known);self.assertTrue(result.as_dict()['peer_verified'])
        self.assertEqual(result.readback_bytes,4);self.assertEqual(result.expected_sha256,result.readback_sha256)
        record('close-after-readback',result,peer.peer)

    def test_close_failure_preserves_primary_error_and_partial_evidence(self):
        class BadClose(Service):
            def close(self):raise RuntimeError('close fault')
        service=BadClose(fault=lambda *args:ControlReply(False,0))
        with self.assertRaises(DFUOperationError) as failure:client(service).inspect()
        self.assertIn('incomplete',str(failure.exception));self.assertEqual(failure.exception.outcome.close_error,'close fault')
        self.assertEqual(len(failure.exception.outcome.trace),1)

    def test_control_interruption_closes_once_preserves_partial_flash_and_original_exception(self):
        for interruption in (KeyboardInterrupt('stop'),SystemExit(17)):
            def interrupt(s,bm,request,value,kwargs,reply):
                if kwargs['data']==b'ABCD':raise interruption
                return reply
            class Counted(Service):
                def close(self):self.close_calls=getattr(self,'close_calls',0)+1;super().close()
            service=Counted(fault=interrupt);api=client(service)
            with self.assertRaises(type(interruption)) as failure:api.program(b'ABCD',address=8192)
            self.assertIs(failure.exception,interruption)
            outcome=api.last_outcome
            self.assertFalse(outcome.complete);self.assertFalse(outcome.outcome_known)
            self.assertEqual(outcome.stage,'program-data');self.assertEqual(outcome.payload_transferred,0)
            self.assertEqual(bytes(service.peer.internal[8192:8196]),b'ABCD')
            self.assertEqual(service.peer.completed_programs,0)
            self.assertEqual(service.requests[-1][4]['data'],b'ABCD')
            self.assertEqual(service.close_calls,1);self.assertTrue(api.closed);self.assertTrue(service.closed)
            count=len(service.requests)
            with self.assertRaises(RuntimeError):api.inspect()
            self.assertEqual(len(service.requests),count);self.assertEqual(service.close_calls,1)
            record('control-'+type(interruption).__name__,outcome,service.peer)

    def test_poll_sleep_interruption_retains_acknowledged_bytes_and_close_error(self):
        programmed=False;interruption=KeyboardInterrupt('poll stopped')
        def busy(s,bm,request,value,kwargs,reply):
            nonlocal programmed
            if kwargs['data']==b'ABCD':programmed=True
            if programmed and bm==0xa1 and request==3:
                return ControlReply(True,6,bytes.fromhex('006400000400'))
            return reply
        class PollClock(Clock):
            def sleep(self,value):
                if programmed:raise interruption
                super().sleep(value)
        class BadClose(Service):
            def close(self):self.close_calls=getattr(self,'close_calls',0)+1;raise RuntimeError('close fault')
        service=BadClose(fault=busy);api=client(service,PollClock())
        with self.assertRaises(KeyboardInterrupt) as failure:api.program(b'ABCD',address=8192)
        self.assertIs(failure.exception,interruption);self.assertTrue(api.closed);self.assertEqual(service.close_calls,1)
        result=api.last_outcome
        self.assertFalse(result.complete);self.assertFalse(result.outcome_known)
        self.assertEqual(result.payload_transferred,4);self.assertEqual(result.close_error,'close fault')
        self.assertIn('interrupted',result.error);self.assertEqual(service.requests[-1][:2],(0xa1,3))
        self.assertEqual(bytes(service.peer.internal[8192:8196]),b'ABCD')
        self.assertEqual(service.peer.completed_programs,0)
        record('poll-sleep-interruption-with-close-failure',result,service.peer)

    def test_close_interruption_preserves_completed_readback_and_invalidates_client(self):
        interruption=SystemExit(23)
        class InterruptedClose(Service):
            def close(self):self.close_calls=getattr(self,'close_calls',0)+1;raise interruption
        service=InterruptedClose();api=client(service)
        with self.assertRaises(SystemExit) as failure:api.program(b'ABCD',address=8192)
        self.assertIs(failure.exception,interruption);self.assertTrue(api.closed);self.assertEqual(service.close_calls,1)
        result=api.last_outcome
        self.assertFalse(result.complete);self.assertTrue(result.as_dict()['peer_verified'])
        self.assertEqual(result.close_error,'23');self.assertEqual(result.stage,'close')
        record('close-interruption-after-readback',result,service.peer)

    def test_start_clock_interruption_closes_before_any_control_io(self):
        interruption=KeyboardInterrupt()
        def clock():raise interruption
        service=Service();api=client(service);api.clock=clock
        with self.assertRaises(KeyboardInterrupt) as failure:api.inspect()
        self.assertIs(failure.exception,interruption);self.assertTrue(api.closed);self.assertTrue(service.closed)
        self.assertEqual(service.requests,[]);self.assertEqual(api.last_outcome.stage,'start')
        self.assertFalse(api.last_outcome.complete)


@unittest.skipUnless(DLL,'Set CBUS_DFU_DLL for original DeviceOpen descriptor execution without USB')
class NativeDescriptorTest(unittest.TestCase):
    def test_original_device_open_and_strict_negative_cases(self):
        path=Path(__file__).resolve().parents[1]/'research/native_dfu_descriptors.py'
        spec=importlib.util.spec_from_file_location('native_dfu_descriptors',path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        rows=[]
        for case,expected,accepted in (('dfu',0,True),('runtime',0,False),('not-found',-3,True),
            ('short-device',-4,True),('wrong-device-length',-4,True),('short-config',-4,True),
            ('wrong-interface-class',-4,False),('missing-functional',0,False),('zero-transfer',0,False),
            ('status-failure',0,True),('no-extension',0,True),('zero-length-interface',None,False)):
            p=module.OpenProbe(Path(DLL),case=case,index=2);row=p.result();rows.append(row)
            self.assertEqual(row['native_return'],expected)
            if accepted:self.assertIsNotNone(parse_descriptors(p.device,p.config))
            else:
                with self.assertRaises(ValueError):parse_descriptors(p.device,p.config)
            # Accepted descriptor bytes do not override actual short/failed
            # transfers: those are separately rejected by DFUClient tests.
        if REPORT:Path(REPORT).write_text(json.dumps({'scope':'Original DeviceOpen with synthetic descriptors and fake USB services; no hardware','cases':rows,'client_outcomes':EVIDENCE},indent=2)+'\n')


if __name__=='__main__':unittest.main()
