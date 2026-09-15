"""Public coordinator through real PyUSB core and independent fake backend.

Every call injects a backend. These tests never enumerate the host's USB bus.
"""
import gc
import hashlib
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import usb.core

from cbus_toolkit.dfu_transport import DFUClient, parse_descriptors
from cbus_toolkit.firmware_usb import run_usb_dfu
from tests.test_usb_dfu import ClaimedBackend, DEVICE, CONFIG

EVIDENCE=[]


def run(backend, operation='inspect', **options):
    defaults=dict(bus=1,address=7,expected_serial='ABC123',descriptor=parse_descriptors(DEVICE,CONFIG),
                  release_policy='reset-first-alternate',flash_size=262144,application_start=8192,backend=backend)
    defaults.update(options)
    return run_usb_dfu(operation,**defaults)


def record(name, result, backend):
    json.dumps(result)
    EVIDENCE.append({'name':name,'result':result,'lifecycle':list(backend.lifecycle),
                     'requests':list(backend.requests),'peer':backend.peer.snapshot()})


class USBDFUCoordinatorTests(unittest.TestCase):
    def test_inspect_program_erase_complete_only_after_single_release(self):
        payload=bytes.fromhex('0700000000000000')+bytes(range(256))*5
        for operation in ('inspect','program','erase'):
            with self.subTest(operation=operation):
                backend=ClaimedBackend();options={}
                if operation=='program':options=dict(data=payload,address_offset=8192)
                elif operation=='erase':
                    backend.peer.internal[8192:11264]=b'\0'*3072;options=dict(address_offset=8192,length=2048)
                result=run(backend,operation,**options)
                self.assertTrue(result['complete']);self.assertFalse(result['physical_device_verified'])
                self.assertTrue(result['acquisition']['complete']);self.assertTrue(result['transfer']['complete']);self.assertTrue(result['release']['complete'])
                self.assertTrue(result['operation_invoked']);self.assertTrue(result['release']['state_after_release_unknown'])
                self.assertEqual(result['errors'],[]);self.assertEqual((backend.claim_count,backend.release_count,backend.close_count),(1,1,1))
                self.assertEqual(backend.lifecycle[-2:],['release','close']);self.assertFalse(backend.peer.detached)
                if operation=='program':
                    self.assertEqual(bytes(backend.peer.internal[8192:8192+len(payload)]),payload)
                    self.assertEqual(result['transfer']['readback_bytes'],len(payload));self.assertEqual(result['transfer']['expected_sha256'],hashlib.sha256(payload).hexdigest())
                    self.assertTrue(result['transfer']['peer_verified']);self.assertEqual(backend.peer.completed_programs,1)
                elif operation=='erase':
                    self.assertEqual(bytes(backend.peer.internal[8192:10240]),b'\xff'*2048)
                    self.assertEqual(bytes(backend.peer.internal[10240:11264]),b'\0'*1024)
                    self.assertTrue(result['transfer']['peer_verified'])
                before=list(backend.lifecycle);gc.collect();self.assertEqual(backend.lifecycle,before)
                record(operation,result,backend)

    def test_external_program_raw_bytes_at_zero(self):
        backend=ClaimedBackend();result=run(backend,'program',data=b'FONTS',address_offset=0,flash_size=131072,application_start=0,external=True)
        self.assertTrue(result['complete']);self.assertEqual(bytes(backend.peer.external[:5]),b'FONTS')
        self.assertEqual(result['preflight']['payload_sha256'],hashlib.sha256(b'FONTS').hexdigest())
        record('external-program',result,backend)

    def test_operation_preflight_rejects_invalid_inputs_before_acquisition(self):
        cases=[('unknown',{}),('inspect',{'data':b'x'}),('inspect',{'address_offset':0}),('inspect',{'length':1}),
            ('program',{'data':'text','address_offset':8192}),('program',{'data':b'','address_offset':8192}),
            ('program',{'data':b'x','address_offset':8191}),('program',{'data':b'x','address_offset':8192,'length':1}),
            ('program',{'data':b'x','address_offset':262144}),('program',{'data':b'x','address_offset':True}),
            ('erase',{'address_offset':8192,'length':1}),('erase',{'address_offset':8192,'length':0}),
            ('erase',{'address_offset':8192,'length':1024,'data':b'x'}),('inspect',{'flash_size':True}),
            ('inspect',{'application_start':1}),('inspect',{'external':1}),('inspect',{'timeout':float('nan')}),
            ('inspect',{'poll_limit':True}),('inspect',{'descriptor':None}),
            ('program',{'external':True,'application_start':0,'flash_size':131072,'address_offset':65536,'data':b'x'})]
        for operation,options in cases:
            with self.subTest(operation=operation,options=options):
                backend=ClaimedBackend()
                with patch('cbus_toolkit.firmware_usb.ClaimedUSBSession.acquire') as acquire:
                    with self.assertRaises(ValueError):run(backend,operation,**options)
                    acquire.assert_not_called()
                self.assertEqual(backend.events,[])

    def test_usb_policy_identity_and_inspection_validation_send_no_requests(self):
        for options in ({'bus':True},{'address':0},{'release_policy':None},{'expected_serial':''},
                        {'expected_serial':'\ud800'},{'inspection_timeout':0},{'inspection_timeout':True}):
            with self.subTest(options=options):
                backend=ClaimedBackend();result=run(backend,**options)
                self.assertFalse(result['complete']);self.assertIsNone(result['acquisition']);self.assertIsNone(result['release'])
                self.assertEqual(backend.events,[]);self.assertFalse(result['operation_invoked'])

    def test_acquisition_failure_and_cleanup_are_both_retained(self):
        for backend in (ClaimedBackend([]),ClaimedBackend(claim_error=OSError('claim blocked')),
                        ClaimedBackend(alternate=1,release_error=OSError('release failed'),close_error=OSError('close failed'))):
            result=run(backend);self.assertFalse(result['complete']);self.assertFalse(result['acquisition']['complete'])
            self.assertIsNone(result['transfer']);self.assertFalse(result['operation_invoked']);self.assertEqual(backend.peer.transfers,0)
            self.assertLessEqual(backend.release_count,1);self.assertLessEqual(backend.close_count,1)
            before=list(backend.lifecycle);gc.collect();self.assertEqual(backend.lifecycle,before)
            if backend.alternate==1:
                self.assertIn('alternate',result['error']);self.assertEqual(result['release']['close_error'],'close failed')
                self.assertIn('release failed',[row['error'] for row in result['errors']])
            record('acquisition-failure',result,backend)

    def test_endpoint_and_client_construction_failure_always_release(self):
        for stage in ('endpoint','client'):
            backend=ClaimedBackend()
            if stage=='endpoint':
                context=patch('cbus_toolkit.firmware_usb.ClaimedUSBSession.endpoint',side_effect=OSError('endpoint failed'))
            else:context=patch('cbus_toolkit.firmware_usb.DFUClient',side_effect=OSError('client failed'))
            with context as mocked:
                if stage=='client':mocked.preflight.side_effect=DFUClient.preflight
                result=run(backend)
            self.assertFalse(result['complete']);self.assertEqual(result['errors'][0]['stage'],stage)
            self.assertTrue(result['acquisition']['complete']);self.assertIsNone(result['transfer']);self.assertFalse(result['operation_invoked'])
            self.assertTrue(result['release']['complete']);self.assertEqual((backend.release_count,backend.close_count),(1,1))
            self.assertEqual(backend.peer.transfers,0);record(stage+'-failure',result,backend)

    def test_lost_ack_preserves_partial_transfer_without_replay_or_recovery(self):
        for mode in ('short','timeout'):
            def fault(backend,fixture,row,normal):
                if row.get('out_data')=='41424344':
                    if mode=='timeout':raise usb.core.USBTimeoutError('lost after write',error_code=-7)
                    return 3
                return normal
            backend=ClaimedBackend(fault=fault,release_error=OSError('release also failed'))
            result=run(backend,'program',data=b'ABCD',address_offset=8192)
            self.assertFalse(result['complete']);self.assertFalse(result['transfer']['complete']);self.assertFalse(result['transfer']['outcome_known'])
            self.assertEqual(bytes(backend.peer.internal[8192:8196]),b'ABCD');self.assertEqual(backend.peer.completed_programs,0)
            self.assertEqual(backend.requests[-1].get('out_data'),'41424344');self.assertEqual(backend.lifecycle[-2:],['release','close'])
            self.assertEqual((backend.release_count,backend.close_count),(1,1));self.assertNotEqual(result['error'],'release also failed')
            self.assertIn('release also failed',[row['error'] for row in result['errors']]);record(mode+'-partial',result,backend)

    def test_verified_transfer_remains_separate_from_failed_release_and_close(self):
        backend=ClaimedBackend(release_error=OSError('release failed'),close_error=OSError('close failed'))
        result=run(backend,'program',data=b'ABCD',address_offset=8192)
        self.assertFalse(result['complete']);self.assertTrue(result['transfer']['complete']);self.assertTrue(result['transfer']['peer_verified'])
        self.assertFalse(result['release']['complete']);self.assertEqual(result['error'],'release failed')
        self.assertEqual([e['error'] for e in result['errors']],['release failed','close failed'])
        record('verified-transfer-release-failure',result,backend)

    def test_corrupt_readback_is_incomplete_even_with_successful_cleanup(self):
        def fault(backend,fixture,row,normal):
            if row['bmRequestType']==0xa1 and row['bRequest']==2 and row['wLength']==4:return bytes([normal[0]^1])+normal[1:]
            return normal
        backend=ClaimedBackend(fault=fault);result=run(backend,'program',data=b'ABCD',address_offset=8192)
        self.assertFalse(result['complete']);self.assertTrue(result['release']['complete']);self.assertEqual(result['transfer']['first_mismatch'],8192)
        self.assertFalse(result['transfer']['peer_verified']);record('mismatching-readback',result,backend)

    def test_acquisition_and_program_interruptions_preserve_same_exception_with_evidence(self):
        for stage,interruption in (('acquisition',KeyboardInterrupt('stop claim')),('transfer',SystemExit(17))):
            def fault(backend,fixture,row,normal):
                if (stage=='acquisition' and row['bmRequestType']==0x81) or (stage=='transfer' and row.get('out_data')=='41424344'):
                    raise interruption
                return normal
            backend=ClaimedBackend(fault=fault,release_error=OSError('release failed'))
            with self.assertRaises(type(interruption)) as caught:run(backend,'program',data=b'ABCD',address_offset=8192)
            self.assertIs(caught.exception,interruption);result=interruption.usb_dfu_evidence
            self.assertFalse(result['complete']);self.assertFalse(result['release']['complete']);self.assertEqual((backend.release_count,backend.close_count),(1,1))
            if stage=='transfer':
                self.assertFalse(result['transfer']['complete']);self.assertEqual(result['transfer']['stage'],'program-data')
                self.assertEqual(bytes(backend.peer.internal[8192:8196]),b'ABCD')
            else:self.assertIsNone(result['transfer'])
            record(stage+'-interruption',result,backend)

    def test_construction_interruptions_and_cleanup_interruptions_retain_original(self):
        for stage in ('endpoint','client'):
            interruption=KeyboardInterrupt(stage);cleanup=SystemExit(23);backend=ClaimedBackend(release_error=cleanup)
            context=patch('cbus_toolkit.firmware_usb.ClaimedUSBSession.endpoint',side_effect=interruption) if stage=='endpoint' else patch('cbus_toolkit.firmware_usb.DFUClient',side_effect=interruption)
            with context as mocked:
                if stage=='client':mocked.preflight.side_effect=DFUClient.preflight
                with self.assertRaises(KeyboardInterrupt) as caught:run(backend)
            self.assertIs(caught.exception,interruption);result=interruption.usb_dfu_evidence
            self.assertEqual(result['error'],stage);self.assertEqual(result['release']['release_error'],'23')
            self.assertEqual((backend.release_count,backend.close_count),(1,1));record(stage+'-double-interruption',result,backend)
        cleanup=SystemExit(31);backend=ClaimedBackend(release_error=cleanup)
        with self.assertRaises(SystemExit) as caught:run(backend)
        self.assertIs(caught.exception,cleanup);result=cleanup.usb_dfu_evidence
        self.assertTrue(result['transfer']['complete']);self.assertFalse(result['complete']);record('cleanup-interruption',result,backend)

    def test_cleanup_interruption_does_not_erase_earlier_operation_error(self):
        cleanup=KeyboardInterrupt('cleanup interrupted')
        def fault(backend,fixture,row,normal):
            if row.get('out_data')=='41424344':raise OSError('original failed transfer')
            return normal
        backend=ClaimedBackend(fault=fault,close_error=cleanup)
        with self.assertRaises(KeyboardInterrupt) as caught:run(backend,'program',data=b'ABCD',address_offset=8192)
        self.assertIs(caught.exception,cleanup);result=cleanup.usb_dfu_evidence
        self.assertIn('original failed transfer',result['error']);self.assertEqual(result['release']['close_error'],'cleanup interrupted')
        self.assertFalse(result['transfer']['complete']);self.assertEqual((backend.release_count,backend.close_count),(1,1))
        record('primary-error-cleanup-interruption',result,backend)

    def test_release_clock_failures_are_visible_and_do_not_skip_cleanup(self):
        for stage in ('start','finish'):
            backend=ClaimedBackend()
            failures=[OSError('clock failed')] if stage=='start' else [12.,OSError('clock failed')]
            with patch('cbus_toolkit.usb_dfu.time.monotonic',side_effect=failures):result=run(backend)
            self.assertFalse(result['complete']);self.assertTrue(result['transfer']['complete'])
            self.assertIn('clock failed',result['error']);self.assertIn('clock failed',result['release']['timing_error'])
            self.assertTrue(result['release']['release_succeeded']);self.assertTrue(result['release']['close_succeeded'])
            self.assertEqual((backend.release_count,backend.close_count),(1,1));record(stage+'-release-clock-error',result,backend)
        first=KeyboardInterrupt('first clock');second=SystemExit(41);backend=ClaimedBackend(release_error=second)
        with patch('cbus_toolkit.usb_dfu.time.monotonic',side_effect=first):
            with self.assertRaises(KeyboardInterrupt) as caught:run(backend)
        self.assertIs(caught.exception,first);result=first.usb_dfu_evidence
        self.assertIn('first clock',result['release']['timing_error']);self.assertEqual(result['release']['release_error'],'41')
        self.assertEqual((backend.release_count,backend.close_count),(1,1));record('first-release-interruption',result,backend)

    def test_acquisition_failure_is_not_erased_by_cleanup_interruption(self):
        cleanup=KeyboardInterrupt('release interrupted')
        def fault(backend,fixture,row,normal):
            if row['bmRequestType']==0x81:raise OSError('original alternate read failed')
            return normal
        backend=ClaimedBackend(fault=fault,release_error=cleanup)
        with self.assertRaises(KeyboardInterrupt) as caught:run(backend)
        self.assertIs(caught.exception,cleanup);result=cleanup.usb_dfu_evidence
        self.assertEqual(result['error'],'original alternate read failed');self.assertIsNone(result['transfer'])
        self.assertEqual(result['release']['release_error'],'release interrupted')
        self.assertEqual((backend.release_count,backend.close_count),(1,1));record('acquisition-primary-error-cleanup-interruption',result,backend)

    @classmethod
    def tearDownClass(cls):
        if os.environ.get('CBUS_FIRMWARE_USB_REPORT'):
            Path(os.environ['CBUS_FIRMWARE_USB_REPORT']).write_text(json.dumps({'scope':'Real PyUSB1.3.1 through explicit fake backend and independent DFUSimulator; no host USB','evidence':EVIDENCE},indent=2)+'\n')


if __name__=='__main__':unittest.main()
