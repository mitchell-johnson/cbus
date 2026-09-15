"""Real PyUSB through an independent fake claimed backend and flash peer.

The injected backend is mandatory in every test; no host USB is enumerated.
"""
import gc
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import usb.core

from cbus_toolkit.dfu_transport import DFUClient, DFUOperationError, parse_descriptors
from cbus_toolkit.dfu_simulator import DFUSimulator
from cbus_toolkit.usb_dfu import ClaimedUSBSession, USBAcquisitionError, USBEndpoint0Lease
from tests.test_usb_inspection import DEVICE, CONFIG, USBFixture, FakeBackend

REPORT = os.getenv('CBUS_USB_DFU_REPORT')
EVIDENCE = []


class ClaimedBackend(FakeBackend):
    """Independent standard requests plus actual DFUSimulator byte decoding.

    fault(backend, fixture, request, normal) sees IN bytes or OUT integer count.
    Every request and lifecycle call is retained; release side effect is modeled.
    """
    def __init__(self, devices=None, *, peer=None, alternate=0, claim_error=None,
                 release_error=None, **kwargs):
        super().__init__(devices, **kwargs)
        self.peer = peer or DFUSimulator(); self.alternate = alternate
        self.claim_error = claim_error; self.release_error = release_error
        self.claimed = False; self.claim_count = self.release_count = 0; self.lifecycle = []

    def open_device(self, device):
        self.lifecycle.append('open')
        return super().open_device(device)

    def close_device(self, handle):
        self.lifecycle.append('close')
        return super().close_device(handle)

    def claim_interface(self, handle, interface):
        self.lifecycle.append('claim'); self.claim_count += 1
        if interface != 0: raise AssertionError('Independent fixture exposes only interface0')
        if self.claim_error: raise self.claim_error
        if self.claimed: raise AssertionError('Unexpected repeated backend claim')
        self.claimed = True

    def release_interface(self, handle, interface):
        self.lifecycle.append('release'); self.release_count += 1
        if interface != 0 or not self.claimed: raise AssertionError('Releasing an unclaimed interface')
        if self.release_error: raise self.release_error
        self.claimed = False; self.alternate = 0

    def ctrl_transfer(self, handle, bm, request, value, index, buffer, timeout):
        self.lifecycle.append(f'control:{bm:02X}:{request:02X}')
        if bm == 0x80:
            return super().ctrl_transfer(handle, bm, request, value, index, buffer, timeout)
        if not self.claimed: raise AssertionError('Unclaimed class/interface request')
        row = {'bmRequestType': bm, 'bRequest': request, 'wValue': value, 'wIndex': index,
               'wLength': len(buffer), 'timeout_ms': timeout, 'bus': handle.bus, 'address': handle.address}
        self.requests.append(row); self.events.append('control')
        incoming = bool(bm & 0x80)
        if (bm, request, value, index, len(buffer)) == (0x81, 10, 0, 0, 1):
            result = bytes([self.alternate])
        else:
            payload = b'' if incoming else buffer.tobytes()
            if payload: row['out_data'] = payload.hex()
            response = self.peer.control(bm, request, value, index, data=payload, length=len(buffer))
            result = response if incoming else len(payload)
        if self.fault: result = self.fault(self, handle, row, result)
        if incoming:
            if not isinstance(result, bytes): raise AssertionError('IN fixture must return bytes')
            for offset, byte in enumerate(result): buffer[offset] = byte
            row['data'] = result.hex(); count = len(result)
        else:
            if type(result) is not int: raise AssertionError('OUT fixture must return integer count')
            count = result
        row['transferred'] = count
        return count


def acquire(backend, **kwargs):
    args = dict(bus=1, address=7, expected_serial='ABC123', descriptor=parse_descriptors(DEVICE, CONFIG),
                release_policy='reset-first-alternate', backend=backend)
    return ClaimedUSBSession.acquire(**{**args, **kwargs})


def api(session, **kwargs):
    return DFUClient(session.endpoint(), session.descriptor, flash_size=kwargs.pop('flash_size', 262144),
                     application_start=kwargs.pop('application_start', 8192), **kwargs)


def record(name, session, backend, outcome=None):
    EVIDENCE.append({'name': name, 'acquisition': session.acquisition.as_dict(),
        'dfu': outcome.as_dict() if outcome else None,
        'release': session.last_release.as_dict() if session.last_release else None,
        'lifecycle': backend.lifecycle, 'requests': backend.requests, 'peer': backend.peer.snapshot()})


class ClaimedUSBTest(unittest.TestCase):
    def test_exact_acquisition_manual_claim_and_one_logical_lease(self):
        backend = ClaimedBackend(); session = acquire(backend)
        self.assertTrue(session.acquisition.complete)
        self.assertEqual((session.acquisition.active_configuration, session.acquisition.active_alternate), (1, 0))
        self.assertEqual(session.acquisition.serial, 'ABC123')
        self.assertEqual(backend.claim_count, 1); self.assertEqual(backend.release_count, 0)
        self.assertEqual(backend.lifecycle[-3:], ['claim', 'control:81:0A', 'control:80:08'])
        lease = session.endpoint(); lease.close(); lease.close()
        self.assertTrue(lease.closed); self.assertTrue(backend.claimed)
        self.assertEqual(backend.close_count, 0); self.assertEqual(backend.release_count, 0)
        with self.assertRaises(RuntimeError): session.endpoint()
        with self.assertRaises(TypeError): USBEndpoint0Lease(session)
        release = session.release(); self.assertTrue(release.complete)
        self.assertTrue(release.as_dict()['implicit_set_interface_possible'])
        self.assertEqual((backend.claim_count, backend.release_count, backend.close_count), (1, 1, 1))
        before = list(backend.lifecycle)
        self.assertIs(session.release(), release); gc.collect()
        self.assertEqual(backend.lifecycle, before)
        with self.assertRaises(RuntimeError): session.endpoint()
        record('acquisition-logical-close-explicit-release', session, backend)

    def test_preflight_requires_exact_policy_serial_and_single_configuration_before_io(self):
        variants = [{'release_policy': None}, {'release_policy': 'silent'}, {'expected_serial': ''},
            {'expected_serial': '\ud800'}, {'expected_serial': 'a'*127}, {'bus': True}, {'address': 0},
            {'inspection_timeout': 0}, {'inspection_timeout': float('nan')}, {'inspection_timeout': True},
            {'descriptor': parse_descriptors(DEVICE[:-1]+b'\x02', CONFIG)},
            {'descriptor': parse_descriptors(DEVICE[:16]+b'\0'+DEVICE[17:], CONFIG)}]
        for kwargs in variants:
            backend = ClaimedBackend()
            with self.assertRaises(ValueError): acquire(backend, **kwargs)
            self.assertEqual(backend.events, [])
        with self.assertRaises(TypeError):
            ClaimedUSBSession.acquire(bus=1,address=7,expected_serial='ABC123',descriptor=parse_descriptors(DEVICE,CONFIG))

    def test_absent_ambiguous_or_failed_enumeration_does_not_claim_or_open(self):
        for backend in (ClaimedBackend([]), ClaimedBackend([USBFixture(), USBFixture()]),
                        ClaimedBackend(enumeration_error=OSError('enumeration failed'))):
            with self.assertRaises(USBAcquisitionError) as failure: acquire(backend)
            self.assertFalse(failure.exception.acquisition.complete)
            self.assertTrue(failure.exception.release.complete)
            self.assertEqual((backend.open_count, backend.claim_count), (0, 0))
            self.assertFalse(failure.exception.release.close_attempted)

    def test_serial_config_or_descriptor_mismatch_closes_without_claim(self):
        fixtures = [USBFixture(active_configuration=0),
                    USBFixture(cached_descriptor=DEVICE, descriptor=DEVICE[:12]+b'\x78\x56'+DEVICE[14:]),
                    USBFixture(configurations=(CONFIG[:20]+b'\x03'+CONFIG[21:],))]
        for fixture in fixtures:
            backend = ClaimedBackend([fixture])
            with self.assertRaises(USBAcquisitionError) as failure: acquire(backend)
            self.assertEqual(backend.claim_count, 0); self.assertEqual(backend.close_count, 1)
            self.assertTrue(failure.exception.release.complete)
        backend = ClaimedBackend()
        with self.assertRaises(USBAcquisitionError) as failure: acquire(backend, expected_serial='OTHER')
        self.assertEqual(failure.exception.acquisition.serial, 'ABC123')
        self.assertEqual(backend.claim_count, 0); self.assertEqual(backend.close_count, 1)

    def test_invalid_language_unicode_and_partial_acquisition_stop_before_claim(self):
        for key, value in (((0,0), b'\x02\x03'), ((0,0), bytes.fromhex('060309040904')),
                           ((3,0x409), bytes.fromhex('040300d8')), ((3,0x409), bytes.fromhex('040341'))):
            fixture = USBFixture(); fixture.strings[key] = value; backend = ClaimedBackend([fixture])
            with self.assertRaises(USBAcquisitionError): acquire(backend)
            self.assertEqual((backend.claim_count,backend.close_count),(0,1))
        backend = ClaimedBackend(fault=lambda backend, fixture, row, response: response[:-1])
        with self.assertRaises(USBAcquisitionError) as failure: acquire(backend)
        self.assertEqual(failure.exception.acquisition.trace[0]['transferred'],17)
        self.assertEqual(len(backend.requests),1); self.assertEqual(backend.close_count,1)

    def test_claim_busy_never_detaches_or_retries_and_closes(self):
        backend = ClaimedBackend(claim_error=usb.core.USBError('BUSY', error_code=-6))
        with self.assertRaises(USBAcquisitionError) as failure: acquire(backend)
        self.assertTrue(failure.exception.acquisition.claim_attempted)
        self.assertFalse(failure.exception.acquisition.claim_succeeded)
        self.assertEqual((backend.claim_count,backend.release_count,backend.close_count),(1,0,1))
        self.assertNotIn('FORBIDDEN',backend.events)
        record('claim-busy',failure.exception.session,backend)

    def test_alternate_mismatch_and_changed_configuration_still_release_once(self):
        backend = ClaimedBackend(alternate=1)
        with self.assertRaises(USBAcquisitionError) as failure: acquire(backend)
        self.assertEqual(failure.exception.acquisition.active_alternate,1)
        self.assertEqual(backend.alternate,0)  # Modeled documented release side effect.
        self.assertEqual((backend.release_count,backend.close_count),(1,1))
        record('alternate-mismatch-with-release-side-effect',failure.exception.session,backend)
        def changed(backend,fixture,row,response):
            return b'\0' if row['bRequest']==8 and backend.claimed else response
        backend = ClaimedBackend(fault=changed)
        with self.assertRaises(USBAcquisitionError) as failure: acquire(backend)
        self.assertEqual(failure.exception.acquisition.stage,'configuration_recheck')
        self.assertEqual((backend.release_count,backend.close_count),(1,1))

    def test_short_or_failed_get_interface_does_not_send_dfu_requests(self):
        for mode in ('short','timeout'):
            def fault(backend,fixture,row,response):
                if row['bmRequestType']==0x81:
                    if mode=='timeout': raise usb.core.USBTimeoutError('GET_INTERFACE timeout', error_code=-7)
                    return b''
                return response
            backend = ClaimedBackend(fault=fault)
            with self.assertRaises(USBAcquisitionError): acquire(backend)
            self.assertEqual(backend.peer.transfers,0)
            self.assertEqual((backend.release_count,backend.close_count),(1,1))

    def test_acquisition_and_release_failures_preserve_both_without_hidden_retry(self):
        backend = ClaimedBackend(alternate=1,release_error=usb.core.USBError('release failed'),close_error=OSError('close failed'))
        with self.assertRaises(USBAcquisitionError) as failure: acquire(backend)
        value = failure.exception; self.assertIn('alternate',str(value))
        self.assertFalse(value.release.complete); self.assertIn('release failed',value.release.release_error)
        self.assertEqual(value.release.close_error,'close failed')
        before=list(backend.lifecycle); value.session.release(); gc.collect()
        self.assertEqual(backend.lifecycle,before)
        self.assertEqual((backend.release_count,backend.close_count),(1,1))
        json.dumps(value.details); record('acquisition-and-cleanup-errors',value.session,backend)

    def test_acquisition_interruption_retains_original_and_release_evidence(self):
        interruption=KeyboardInterrupt('stop acquisition')
        def fault(backend,fixture,row,response):
            if row['bmRequestType']==0x81: raise interruption
            return response
        backend = ClaimedBackend(fault=fault,release_error=OSError('release error'))
        with self.assertRaises(KeyboardInterrupt) as failure: acquire(backend)
        self.assertIs(failure.exception,interruption)
        self.assertFalse(interruption.usb_acquisition.complete)
        self.assertFalse(interruption.usb_release.complete)
        self.assertEqual((backend.release_count,backend.close_count),(1,1))

    def test_release_interruption_is_recorded_and_never_repeated(self):
        interruption=SystemExit(13)
        backend = ClaimedBackend(release_error=interruption); session=acquire(backend)
        with self.assertRaises(SystemExit) as failure: session.release()
        self.assertIs(failure.exception,interruption); self.assertFalse(session.last_release.complete)
        self.assertEqual((backend.release_count,backend.close_count),(1,1))
        self.assertIs(session.release(),session.last_release)
        self.assertEqual((backend.release_count,backend.close_count),(1,1))

    def test_release_clock_interruptions_cannot_skip_cleanup_or_lose_outcome(self):
        for when in ('start','finish'):
            interruption=KeyboardInterrupt('timer interrupted')
            backend=ClaimedBackend();session=acquire(backend);lease=session.endpoint()
            values=[interruption] if when=='start' else [10.0,interruption]
            with patch('cbus_toolkit.usb_dfu.time.monotonic',side_effect=values):
                with self.assertRaises(KeyboardInterrupt) as failure:session.release()
            self.assertIs(failure.exception,interruption);self.assertTrue(lease.closed)
            self.assertEqual((backend.release_count,backend.close_count),(1,1))
            result=session.last_release
            self.assertIsNotNone(result);self.assertFalse(result.complete)
            self.assertTrue(result.release_succeeded);self.assertTrue(result.close_succeeded)
            self.assertIsNone(result.release_error);self.assertIsNone(result.close_error)
            self.assertIn('clock failed',result.timing_error)
            before=list(backend.lifecycle)
            with patch('cbus_toolkit.usb_dfu.time.monotonic',side_effect=AssertionError('Clock retried')):
                self.assertIs(session.release(),result)
            self.assertEqual(backend.lifecycle,before)
            record('release-clock-interruption-'+when,session,backend)

    def test_release_clock_failure_does_not_mask_primary_acquisition_or_cleanup_errors(self):
        backend=ClaimedBackend(alternate=1,release_error=OSError('release failed'),close_error=OSError('close failed'))
        with patch('cbus_toolkit.usb_dfu.time.monotonic',side_effect=RuntimeError('clock failed')):
            with self.assertRaises(USBAcquisitionError) as failure:acquire(backend)
        self.assertIn('alternate',str(failure.exception))
        result=failure.exception.release
        self.assertIn('release failed',result.release_error);self.assertIn('close failed',result.close_error)
        self.assertIn('clock failed',result.timing_error)
        self.assertEqual((backend.release_count,backend.close_count),(1,1))

    def test_first_clock_interruption_survives_a_distinct_release_interruption(self):
        first=KeyboardInterrupt('clock stopped');second=SystemExit('release stopped')
        backend=ClaimedBackend(release_error=second);session=acquire(backend)
        with patch('cbus_toolkit.usb_dfu.time.monotonic',side_effect=first):
            with self.assertRaises(KeyboardInterrupt) as failure:session.release()
        self.assertIs(failure.exception,first);self.assertIsNot(failure.exception,second)
        result=session.last_release
        self.assertIn('clock stopped',result.timing_error)
        self.assertEqual(result.release_error,'release stopped');self.assertTrue(result.close_succeeded)
        self.assertEqual((backend.release_count,backend.close_count),(1,1))
        self.assertIs(session.release(),result)

    def test_lease_rejects_other_requests_direction_lengths_and_submillisecond_timeouts(self):
        backend=ClaimedBackend();session=acquire(backend);lease=session.endpoint();before=len(backend.requests)
        bad=[(0x21,0,0,0,b'',0,1),(0x21,4,0,0,b'',0,1),(0x00,9,1,0,b'',0,1),
             (0x01,11,0,0,b'',0,1),(0xa1,5,0,0,b'',1,1),(0xa1,3,0,1,b'',6,1),
             (0x80,6,0x201,0,b'',9,1),(0xa1,3,0,0,b'',5,1),(0xa1,3,0,0,b'X',6,1),
             (0x21,1,0,0,b'X',2,1),(0x21,1,0,0,b'X'*1025,1025,1),
             (0xa1,3,0,0,b'',6,True),(0xa1,3,0,0,b'',6,0.0009)]
        for bm,request,value,index,data,length,timeout in bad:
            with self.assertRaises((ValueError,TimeoutError)):
                lease.control(bm,request,value,index,data=data,length=length,timeout=timeout)
        self.assertEqual(len(backend.requests),before)
        reply=lease.control(0xa1,3,0,0,length=6,timeout=0.0019)
        self.assertEqual(reply.transferred,6);self.assertEqual(backend.requests[-1]['timeout_ms'],1)
        session.release();self.assertNotIn('FORBIDDEN',backend.events)

    def test_short_and_failed_controls_invalidate_the_lease_without_automatic_release(self):
        for mode in ('short','timeout'):
            backend=ClaimedBackend();session=acquire(backend);lease=session.endpoint()
            def fault(backend,fixture,row,response):
                if mode=='timeout':raise usb.core.USBTimeoutError('lost ACK',error_code=-7)
                return response[:-1]
            backend.fault=fault
            if mode=='timeout':
                with self.assertRaises(usb.core.USBTimeoutError):lease.control(0xa1,3,0,0,length=6,timeout=1)
                self.assertEqual(lease.trace[-1]['backend_error_code'],-7)
            else:self.assertEqual(lease.control(0xa1,3,0,0,length=6,timeout=1).transferred,5)
            self.assertTrue(lease.closed);self.assertTrue(backend.claimed);self.assertEqual(backend.release_count,0)
            before=len(backend.requests)
            with self.assertRaises(RuntimeError):lease.control(0xa1,3,0,0,length=6,timeout=1)
            self.assertEqual(len(backend.requests),before);session.release()

    def test_dnload_rejects_vendor_reset_and_replay_but_preserves_program_payload_bytes(self):
        backend=ClaimedBackend();session=acquire(backend);lease=session.endpoint();before=len(backend.requests)
        for header in (bytes.fromhex('0700000000000000'),bytes.fromhex('0300080004000000'),
                       bytes.fromhex('0100080000000000'),bytes.fromhex('0800010004000000')):
            with self.assertRaises(ValueError):lease.control(0x21,1,0,0,data=header,length=len(header),timeout=1)
        self.assertEqual(len(backend.requests),before)
        header=bytes.fromhex('0100080008000000')
        lease.control(0x21,1,0,0,data=header,length=8,timeout=1)
        with self.assertRaises(ValueError):lease.control(0x21,1,0,0,data=header,length=8,timeout=1)
        with self.assertRaises(ValueError):lease.control(0x21,1,1,0,data=b'',length=0,timeout=1)
        with self.assertRaises(ValueError):lease.control(0x21,6,0,0,data=b'',length=0,timeout=1)
        # Read the busy status twice; the independent peer then accepts data.
        lease.control(0xa1,3,0,0,length=6,timeout=1)
        lease.control(0xa1,3,0,0,length=6,timeout=1)
        payload=bytes.fromhex('0700000000000000')
        lease.control(0x21,1,1,0,data=payload,length=8,timeout=1)
        self.assertEqual(bytes(backend.peer.internal[8192:8200]),payload)
        self.assertEqual(backend.peer.completed_programs,0)
        session.release();self.assertFalse(backend.peer.detached)

    def test_concurrent_call_and_release_rejected_without_wait_or_partial_cleanup(self):
        backend=ClaimedBackend();session=acquire(backend);lease=session.endpoint()
        with session._lock:
            with self.assertRaises(RuntimeError):lease.control(0xa1,3,0,0,length=6,timeout=1)
            with self.assertRaises(RuntimeError):session.release()
        self.assertEqual(backend.release_count,0);self.assertFalse(lease.closed)
        self.assertTrue(session.release().complete)

    def test_missing_backend_is_structured_without_device_access(self):
        with patch('usb.backend.libusb1.get_backend',return_value=None):
            with self.assertRaises(USBAcquisitionError) as failure: acquire(None)
        self.assertIn('unavailable',str(failure.exception));self.assertTrue(failure.exception.release.complete)


class ClaimedDFUClientTest(unittest.TestCase):
    def test_inspect_program_and_erase_real_pyusb_independent_memory(self):
        for operation in ('inspect','program','erase'):
            backend=ClaimedBackend()
            if operation=='erase':backend.peer.internal[8192:11264]=b'\0'*3072
            session=acquire(backend);client=api(session)
            try:
                if operation=='inspect':result=client.inspect()
                elif operation=='program':result=client.program(bytes(range(256))*5,address=8192)
                else:result=client.erase(address=8192,length=2048)
                self.assertTrue(result.complete);self.assertTrue(client.closed)
                self.assertTrue(backend.claimed);self.assertEqual(backend.release_count,0)
                if operation=='program':
                    self.assertEqual(bytes(backend.peer.internal[8192:9472]),bytes(range(256))*5)
                    self.assertEqual(backend.peer.completed_programs,1)
                    self.assertTrue(any(row['bmRequestType']==0x21 and row['bRequest']==1 and row['wLength']==0 and row['transferred']==0 for row in backend.requests))
                elif operation=='erase':
                    self.assertEqual(bytes(backend.peer.internal[8192:10240]),b'\xff'*2048)
                    self.assertEqual(bytes(backend.peer.internal[10240:11264]),b'\0'*1024)
                self.assertEqual(backend.claim_count,1)
            finally:release=session.release()
            self.assertTrue(release.complete);self.assertEqual((backend.release_count,backend.close_count),(1,1))
            self.assertNotIn('FORBIDDEN',backend.events)
            record('real-pyusb-memory-'+operation,session,backend,result)

    def test_external_zero_program_independent_readback(self):
        backend=ClaimedBackend();session=acquire(backend);client=api(session,flash_size=131072,application_start=0,external=True)
        try:result=client.program(b'FONTS',address=0)
        finally:session.release()
        self.assertTrue(result.complete);self.assertEqual(bytes(backend.peer.external[:5]),b'FONTS')
        self.assertTrue(result.as_dict()['peer_verified']);record('external-zero-program',session,backend,result)

    def test_lost_or_short_program_ack_keeps_actual_partial_memory_without_recovery(self):
        for mode in ('short','timeout'):
            backend=ClaimedBackend();session=acquire(backend);client=api(session)
            def fault(backend,fixture,row,response):
                if row.get('out_data')=='41424344':
                    if mode=='timeout':raise usb.core.USBTimeoutError('lost after programming',error_code=-7)
                    return 3
                return response
            backend.fault=fault
            try:
                with self.assertRaises(DFUOperationError) as failure:client.program(b'ABCD',address=8192)
                self.assertFalse(failure.exception.outcome.outcome_known)
                self.assertEqual(bytes(backend.peer.internal[8192:8196]),b'ABCD')
                self.assertEqual(backend.peer.completed_programs,0)
                self.assertEqual(backend.requests[-1].get('out_data'),'41424344')
                self.assertEqual(backend.release_count,0)
            finally:session.release()
            record('program-'+mode+'-ack',session,backend,failure.exception.outcome)

    def test_native_error_and_corrupt_readback_do_not_become_success(self):
        for mode in ('native-error','corrupt-readback'):
            backend=ClaimedBackend()
            if mode=='native-error':backend.peer.internal[8192:8196]=b'\0'*4
            session=acquire(backend);client=api(session)
            def fault(backend,fixture,row,response):
                if row['bmRequestType']==0xa1 and row['bRequest']==2 and row['wLength']==4:
                    return bytes([response[0]^1])+response[1:]
                return response
            if mode=='corrupt-readback':backend.fault=fault
            try:
                with self.assertRaises(DFUOperationError) as failure:client.program(b'ABCD',address=8192)
                result=failure.exception.outcome;self.assertFalse(result.complete)
                self.assertTrue(result.outcome_known)
                if mode=='corrupt-readback':self.assertEqual(result.first_mismatch,8192)
            finally:session.release()
            record(mode,session,backend,result)

    def test_program_interruption_preserves_original_and_requires_outer_release(self):
        backend=ClaimedBackend();session=acquire(backend);client=api(session);interruption=KeyboardInterrupt()
        def fault(backend,fixture,row,response):
            if row.get('out_data')=='41424344':raise interruption
            return response
        backend.fault=fault
        try:
            with self.assertRaises(KeyboardInterrupt) as failure:client.program(b'ABCD',address=8192)
            self.assertIs(failure.exception,interruption);self.assertTrue(client.closed)
            self.assertTrue(backend.claimed);self.assertEqual(backend.release_count,0)
            self.assertEqual(bytes(backend.peer.internal[8192:8196]),b'ABCD')
            self.assertFalse(client.last_outcome.complete);self.assertEqual(backend.requests[-1].get('out_data'),'41424344')
        finally:session.release()
        record('interrupted-program-outer-release',session,backend,client.last_outcome)

    def test_verified_dfu_result_is_separate_from_failed_release(self):
        backend=ClaimedBackend(release_error=usb.core.USBError('release failed'),close_error=OSError('close failed'))
        session=acquire(backend);client=api(session)
        try:result=client.program(b'ABCD',address=8192)
        finally:release=session.release()
        self.assertTrue(result.complete);self.assertTrue(result.as_dict()['peer_verified'])
        self.assertFalse(release.complete);self.assertIn('release failed',release.release_error)
        self.assertEqual(release.close_error,'close failed');self.assertEqual((backend.release_count,backend.close_count),(1,1))
        record('verified-memory-failed-release',session,backend,result)


def tearDownModule():
    if REPORT:
        path=Path(REPORT);path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps({'scope':'Real PyUSB1.3.1, explicit fake claimed USB backend and independent DFUSimulator only',
            'physical_usb_access':False,'release_effect':'Modeled SET_INTERFACE to alternate0, not a physical capture',
            'cases':EVIDENCE},indent=2)+'\n')


if __name__=='__main__':unittest.main()
