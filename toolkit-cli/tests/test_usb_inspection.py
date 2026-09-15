"""Real PyUSB core with an independent, explicit fake libusb-style backend.

No test enumerates or opens host USB devices. Root CLI tests reuse FakeBackend.
"""
import gc
import json
import os
from pathlib import Path
import struct
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import usb.core

from cbus_toolkit.usb_inspection import list_edlt_devices, inspect_edlt_device

DEVICE = bytes.fromhex('12010002000000406a160105341201020301')
CONFIG = bytes.fromhex('09021b0001010080320904000000fe010200092107e80300040001')
REPORT = os.getenv('CBUS_USB_INSPECTION_REPORT')
EVIDENCE = []


class USBFixture:
    """Independent descriptor bytes. Mapping keys are (string index, LANGID)."""
    def __init__(self, *, bus=1, address=7, descriptor=DEVICE, configurations=(CONFIG,),
                 active_configuration=1, strings=None, cached_descriptor=None):
        self.bus = bus; self.address = address; self.descriptor = descriptor
        self.configurations = configurations; self.active_configuration = active_configuration
        self.cached_descriptor = descriptor if cached_descriptor is None else cached_descriptor
        self.strings = ({(0, 0): bytes.fromhex('04030904'),
                         (1, 0x409): bytes.fromhex('0803430049005300'),
                         (2, 0x409): bytes.fromhex('0a03650044004c005400'),
                         (3, 0x409): bytes.fromhex('0e03410042004300310032003300')}
                        if strings is None else strings)


class FakeBackend:
    """Supply to inspect backend= or patch libusb1.get_backend to return it.

    fault(backend, fixture, request_dict, normal_bytes) may return replacement
    bytes or raise. requests/events retain the exact PyUSB-to-backend path.
    """
    def __init__(self, devices=None, *, fault=None, close_error=None, open_error=None,
                 enumeration_error=None):
        self.devices = [USBFixture()] if devices is None else devices
        self.fault = fault; self.close_error = close_error; self.open_error = open_error
        self.enumeration_error = enumeration_error; self.events = []; self.requests = []
        self.open_count = self.close_count = 0

    def enumerate_devices(self):
        self.events.append('enumerate')
        for device in self.devices: yield device
        if self.enumeration_error: raise self.enumeration_error

    def get_device_descriptor(self, device):
        self.events.append('cached_descriptor')
        fields = ('bLength', 'bDescriptorType', 'bcdUSB', 'bDeviceClass', 'bDeviceSubClass',
                  'bDeviceProtocol', 'bMaxPacketSize0', 'idVendor', 'idProduct', 'bcdDevice',
                  'iManufacturer', 'iProduct', 'iSerialNumber', 'bNumConfigurations')
        values = struct.unpack('<BBHBBBBHHHBBBB', device.cached_descriptor)
        return SimpleNamespace(**dict(zip(fields, values)), bus=device.bus, address=device.address,
            port_number=2, port_numbers=(2, 1), speed=2)

    def open_device(self, device):
        self.events.append('open'); self.open_count += 1
        if self.open_error: raise self.open_error
        return device

    def close_device(self, handle):
        self.events.append('close'); self.close_count += 1
        if self.close_error: raise self.close_error

    def ctrl_transfer(self, handle, bm, request, value, index, buffer, timeout):
        self.events.append('control')
        row = {'bmRequestType': bm, 'bRequest': request, 'wValue': value, 'wIndex': index,
               'wLength': len(buffer), 'timeout_ms': timeout, 'bus': handle.bus, 'address': handle.address}
        self.requests.append(row)
        if bm != 0x80: raise AssertionError('Independent peer forbids OUT/class/interface requests')
        if request == 6:
            kind, item = value >> 8, value & 255
            if kind == 1 and item == index == 0: data = handle.descriptor
            elif kind == 2 and index == 0: data = handle.configurations[item]
            elif kind == 3: data = handle.strings[(item, index)]
            else: raise AssertionError('Unexpected descriptor request')
        elif request == 8 and value == index == 0 and len(buffer) == 1:
            data = bytes([handle.active_configuration])
        else: raise AssertionError('Independent peer forbids this USB request')
        result = data[:len(buffer)]
        if self.fault: result = self.fault(self, handle, row, result)
        if not isinstance(result, bytes): raise AssertionError('Fake transfer response must be bytes')
        for offset, value in enumerate(result): buffer[offset] = value
        row['transferred'] = len(result); row['data'] = result.hex()
        return len(result)

    def _forbidden(self, *args, **kwargs):
        self.events.append('FORBIDDEN')
        raise AssertionError('Claim/release/configuration/alternate/reset/kernel-driver methods are forbidden')

    claim_interface = release_interface = set_configuration = get_configuration = _forbidden
    set_interface_altsetting = reset_device = detach_kernel_driver = attach_kernel_driver = _forbidden
    is_kernel_driver_active = get_configuration_descriptor = get_interface_descriptor = _forbidden


def inspect(backend, **kwargs):
    return inspect_edlt_device(bus=1, address=7, backend=backend, **kwargs)


def record(name, result, backend):
    EVIDENCE.append({'name': name, 'result': result.as_dict(),
                     'backend_events': list(backend.events), 'backend_requests': list(backend.requests),
                     'opened': backend.open_count, 'closed': backend.close_count})


class USBInspectionTest(unittest.TestCase):
    def assert_read_only(self, backend):
        self.assertNotIn('FORBIDDEN', backend.events)
        self.assertTrue(all(row['bmRequestType'] == 0x80 and row['bRequest'] in (6, 8)
                            for row in backend.requests))

    def test_enumeration_uses_cached_metadata_without_open_or_string_requests(self):
        other = USBFixture(address=8, descriptor=DEVICE[:8] + b'\x34\x12' + DEVICE[10:])
        backend = FakeBackend([USBFixture(), other, USBFixture(address=9)])
        result = list_edlt_devices(backend=backend)
        self.assertTrue(result.complete); self.assertEqual([row['address'] for row in result.devices], [7, 9])
        self.assertEqual(backend.events, ['enumerate', 'cached_descriptor', 'cached_descriptor', 'cached_descriptor'])
        self.assertEqual(backend.open_count, 0); self.assertEqual(backend.requests, [])
        record('cached-enumeration', result, backend)

    def test_full_real_pyusb_inspection_identity_no_claim_and_exact_requests(self):
        backend = FakeBackend(); result = inspect(backend, expected_serial='ABC123')
        self.assertTrue(result.complete, result.error); self.assertTrue(result.expected_serial_matches)
        self.assertEqual(result.strings, {'manufacturer': 'CIS', 'product': 'eDLT', 'serial': 'ABC123'})
        self.assertEqual(result.language_ids, (0x409,)); self.assertEqual(result.active_configuration, 1)
        self.assertEqual(result.dfu_interface['transfer_size'], 1024)
        self.assertFalse(result.as_dict()['exclusive_ownership']); self.assert_read_only(backend)
        self.assertEqual((backend.open_count, backend.close_count), (1, 1))
        vectors = [(row['bRequest'], row['wValue'], row['wIndex'], row['wLength']) for row in backend.requests]
        self.assertEqual(vectors, [(6, 0x100, 0, 18), (8, 0, 0, 1), (6, 0x200, 0, 9),
            (6, 0x200, 0, 27), (6, 0x300, 0, 2), (6, 0x300, 0, 4),
            (6, 0x301, 0x409, 2), (6, 0x301, 0x409, 8), (6, 0x302, 0x409, 2),
            (6, 0x302, 0x409, 10), (6, 0x303, 0x409, 2), (6, 0x303, 0x409, 14), (8, 0, 0, 1)])
        json.dumps(result.as_dict()); record('complete-selected-inspection', result, backend)

    def test_only_selected_device_is_opened_or_queried(self):
        backend = FakeBackend([USBFixture(address=6), USBFixture(), USBFixture(address=8)])
        result = inspect(backend)
        self.assertTrue(result.complete); self.assertTrue(all(row['address'] == 7 for row in backend.requests))
        self.assertEqual((backend.open_count, backend.close_count), (1, 1))

    def test_missing_and_ambiguous_selectors_never_open_any_device(self):
        for devices in ([], [USBFixture(address=8)], [USBFixture(), USBFixture()]):
            backend = FakeBackend(devices); result = inspect(backend)
            self.assertFalse(result.complete); self.assertIn('exactly one', result.error)
            self.assertEqual((backend.open_count, backend.close_count), (0, 0)); self.assertEqual(backend.requests, [])
            record('selector-rejected', result, backend)

    def test_unavailable_location_is_reported_and_cannot_match(self):
        backend = FakeBackend([USBFixture(bus=None, address=None)])
        listed = list_edlt_devices(backend=backend)
        self.assertFalse(listed.devices[0]['selectable'])
        self.assertFalse(inspect(backend).complete); self.assertEqual(backend.open_count, 0)

    def test_enumeration_limits_and_partial_error_do_not_open_devices(self):
        backend = FakeBackend([USBFixture(), USBFixture(address=8)])
        result = list_edlt_devices(backend=backend, max_devices=1)
        self.assertFalse(result.complete); self.assertEqual(len(result.devices), 1)
        self.assertEqual(backend.open_count, 0)
        backend = FakeBackend(enumeration_error=OSError('enumeration stopped'))
        result = list_edlt_devices(backend=backend)
        self.assertFalse(result.complete); self.assertEqual(len(result.devices), 1)
        result = inspect(backend); self.assertFalse(result.complete); self.assertEqual(backend.open_count, 0)

    def test_active_configuration_value_binds_to_second_descriptor_not_index_zero(self):
        first = CONFIG[:5] + b'\x03' + CONFIG[6:16] + b'\x01' + CONFIG[17:]
        second = CONFIG[:5] + b'\x07' + CONFIG[6:]
        fixture = USBFixture(descriptor=DEVICE[:-1] + b'\x02', configurations=(first, second), active_configuration=7)
        backend = FakeBackend([fixture]); result = inspect(backend)
        self.assertTrue(result.complete, result.error); self.assertEqual(result.active_configuration, 7)
        self.assertEqual([row['value'] for row in result.configurations], [3, 7])
        self.assertIsNotNone(result.dfu_interface); self.assert_read_only(backend)
        record('active-configuration-binding', result, backend)

    def test_unconfigured_and_runtime_are_complete_inspection_but_not_dfu_profile(self):
        for fixture in (USBFixture(active_configuration=0),
                        USBFixture(configurations=(CONFIG[:16] + b'\x01' + CONFIG[17:],))):
            backend = FakeBackend([fixture]); result = inspect(backend)
            self.assertTrue(result.complete, result.error); self.assertIsNone(result.dfu_interface)
            self.assertIsNotNone(result.unsupported_reason); self.assert_read_only(backend)
            record('inspect-without-dfu-profile', result, backend)

    def test_configuration_unknown_duplicate_or_changes_are_failures(self):
        fixtures = [USBFixture(active_configuration=2),
            USBFixture(descriptor=DEVICE[:-1] + b'\x02', configurations=(CONFIG, CONFIG))]
        for fixture in fixtures:
            result = inspect(FakeBackend([fixture])); self.assertFalse(result.complete)
        def changed(backend, fixture, row, response):
            return b'\0' if row['bRequest'] == 8 and len(backend.requests) > 2 else response
        backend = FakeBackend(fault=changed); result = inspect(backend)
        self.assertFalse(result.complete); self.assertEqual(result.stage, 'configuration_recheck')
        record('configuration-changed', result, backend)

    def test_strict_configuration_lengths_interfaces_endpoints_and_counts(self):
        variants = [CONFIG[:2] + b'\x01\0' + CONFIG[4:], CONFIG[:5] + b'\0' + CONFIG[6:],
            CONFIG[:7] + b'\x81' + CONFIG[8:], CONFIG[:4] + b'\x02' + CONFIG[5:],
            CONFIG[:9] + b'\0' + CONFIG[10:], CONFIG[:13] + b'\x01' + CONFIG[14:]]
        for data in variants:
            backend = FakeBackend([USBFixture(configurations=(data,))]); result = inspect(backend)
            self.assertFalse(result.complete); self.assert_read_only(backend)
            self.assertEqual(backend.close_count, 1)

    def test_device_descriptor_mismatch_and_profile_bounds_stop_before_more_reads(self):
        for fixture in (USBFixture(descriptor=DEVICE[:12] + b'\x78\x56' + DEVICE[14:], cached_descriptor=DEVICE),
                        USBFixture(descriptor=DEVICE[:7] + b'\0' + DEVICE[8:]),
                        USBFixture(descriptor=DEVICE[:-1] + b'\x09')):
            backend = FakeBackend([fixture]); result = inspect(backend)
            self.assertFalse(result.complete); self.assertEqual(len(backend.requests), 1)
            self.assertEqual(backend.close_count, 1)

    def test_languages_and_non_ascii_strings_decode_using_advertised_language(self):
        fixture = USBFixture(); fixture.strings = {(0, 0): bytes.fromhex('060311040904'),
            (1, 0x411): bytes.fromhex('0803430049005300'),
            (2, 0x411): bytes.fromhex('06039e8a2d4e'), (3, 0x411): bytes.fromhex('06033dd800de')}
        backend = FakeBackend([fixture]); result = inspect(backend, expected_serial='😀')
        self.assertTrue(result.complete, result.error); self.assertEqual(result.selected_language_id, 0x411)
        self.assertEqual(result.strings['product'], '語中'); self.assertEqual(result.strings['serial'], '😀')
        record('strict-multilingual-strings', result, backend)

    def test_invalid_language_and_string_descriptors_stop_without_retry(self):
        bad_languages = ['0203', '0503090400', '04020000', '04030000', '060309040904']
        for literal in bad_languages:
            fixture = USBFixture(); fixture.strings[(0, 0)] = bytes.fromhex(literal)
            backend = FakeBackend([fixture]); result = inspect(backend)
            self.assertFalse(result.complete); self.assertEqual(result.stage, 'string_descriptors')
            self.assertEqual(backend.close_count, 1); self.assert_read_only(backend)
        for literal in ('030341', '040341', '04010000', '040300d8'):
            fixture = USBFixture(); fixture.strings[(3, 0x409)] = bytes.fromhex(literal)
            backend = FakeBackend([fixture]); result = inspect(backend)
            self.assertFalse(result.complete); self.assertEqual(backend.close_count, 1)
            self.assertEqual(backend.requests[-1]['wValue'], 0x303)

    def test_missing_strings_need_no_language_request_and_serial_mismatch_is_partial(self):
        backend = FakeBackend([USBFixture(descriptor=DEVICE[:14] + b'\0\0\0' + DEVICE[17:])])
        result = inspect(backend); self.assertTrue(result.complete); self.assertEqual(result.strings['serial'], None)
        self.assertFalse(any(row['wValue'] >> 8 == 3 for row in backend.requests))
        result = inspect(FakeBackend(), expected_serial='DIFFERENT')
        self.assertFalse(result.complete); self.assertFalse(result.expected_serial_matches)
        self.assertEqual(result.strings['serial'], 'ABC123'); self.assertIn('does not match', result.error)
        self.assertEqual(result.stage, 'string_descriptors')

    def test_empty_serial_is_not_usable_identity(self):
        fixture = USBFixture(); fixture.strings[(3, 0x409)] = b'\x02\x03'
        result = inspect(FakeBackend([fixture])); self.assertTrue(result.complete)
        self.assertFalse(result.as_dict()['usable_usb_serial'])
        result = inspect(FakeBackend([fixture]), expected_serial='ABC123')
        self.assertFalse(result.complete); self.assertFalse(result.expected_serial_matches)

    def test_shared_string_index_is_read_once_and_header_change_is_rejected(self):
        fixture = USBFixture(descriptor=DEVICE[:14] + b'\x03\x03\x03' + DEVICE[17:])
        backend = FakeBackend([fixture]); result = inspect(backend)
        self.assertTrue(result.complete); self.assertEqual(len(backend.requests), 9)
        def changed(backend, fixture, row, response):
            return bytes([response[0] - 2]) + response[1:] if row['wValue'] == 0x303 and row['wLength'] > 2 else response
        result = inspect(FakeBackend(fault=changed)); self.assertFalse(result.complete)
        self.assertIn('changed', result.error)

    def test_short_control_reply_and_native_error_preserve_evidence_no_replay(self):
        backend = FakeBackend(fault=lambda backend, fixture, row, response: response[:-1])
        result = inspect(backend); self.assertFalse(result.complete)
        self.assertEqual(result.trace[0]['transferred'], 17); self.assertEqual(len(backend.requests), 1)
        self.assertEqual(backend.close_count, 1); record('short-control-result', result, backend)
        def timeout(backend, fixture, row, response):
            if row['wValue'] == 0x303: raise usb.core.USBTimeoutError('scripted timeout', error_code=-7)
            return response
        backend = FakeBackend(fault=timeout); result = inspect(backend)
        self.assertFalse(result.complete); self.assertEqual(result.trace[-1]['backend_error_code'], -7)
        self.assertEqual(result.strings, {'manufacturer': 'CIS', 'product': 'eDLT'})
        self.assertEqual(backend.close_count, 1); record('control-timeout-partial', result, backend)

    def test_open_and_close_failures_preserve_primary_and_finalize_only_once(self):
        backend = FakeBackend(open_error=OSError('permission denied')); result = inspect(backend)
        self.assertFalse(result.complete); self.assertIn('permission denied', result.error)
        self.assertEqual(backend.requests, []); self.assertEqual(backend.close_count, 0)
        for fault in (None, lambda backend, fixture, row, response: response[:-1]):
            backend = FakeBackend(fault=fault, close_error=OSError('close failed'))
            result = inspect(backend); gc.collect()
            self.assertFalse(result.complete); self.assertEqual(result.close_error, 'close failed')
            self.assertFalse(result.resources_closed); self.assertEqual(backend.close_count, 1)
            if fault: self.assertIn('Incomplete', result.error)
            else: self.assertEqual(result.strings['serial'], 'ABC123')
            self.assert_read_only(backend); record('closure-failure', result, backend)

    def test_timeout_rounds_up_to_one_millisecond_and_invalid_arguments_do_no_io(self):
        backend = FakeBackend(); result = inspect(backend, timeout=0.000001)
        self.assertTrue(result.complete); self.assertTrue(all(row['timeout_ms'] == 1 for row in backend.requests))
        for kwargs in ({'bus': True}, {'bus': -1}, {'address': 0}, {'address': 128},
                       {'timeout': 0}, {'timeout': float('nan')}, {'timeout': True},
                       {'expected_serial': ''}, {'expected_serial': '\ud800'}, {'expected_serial': 'a'*127}):
            backend = FakeBackend(); args = {'bus': 1, 'address': 7, 'backend': backend, **kwargs}
            with self.assertRaises(ValueError): inspect_edlt_device(**args)
            self.assertEqual(backend.events, [])

    def test_interruption_still_closes_and_empty_error_is_not_success(self):
        def interrupted(backend, fixture, row, response): raise KeyboardInterrupt()
        backend = FakeBackend(fault=interrupted)
        with self.assertRaises(KeyboardInterrupt): inspect(backend)
        self.assertEqual(backend.close_count, 1); self.assert_read_only(backend)
        backend = FakeBackend(enumeration_error=RuntimeError())
        result = list_edlt_devices(backend=backend)
        self.assertFalse(result.complete); self.assertEqual(result.error, 'RuntimeError')
        backend = FakeBackend(close_error=RuntimeError()); result = inspect(backend)
        self.assertFalse(result.complete); self.assertEqual(result.close_error, 'RuntimeError')

    def test_explicit_libusb1_backend_is_used_and_missing_backend_is_clear(self):
        backend = FakeBackend()
        with patch('usb.backend.libusb1.get_backend', return_value=backend):
            self.assertTrue(inspect_edlt_device(bus=1, address=7).complete)
        with patch('usb.backend.libusb1.get_backend', return_value=None):
            with self.assertRaisesRegex(RuntimeError, 'unavailable'): list_edlt_devices()
        with patch('usb.__version__', '1.3.0'):
            with self.assertRaisesRegex(RuntimeError, '1.3.1'): list_edlt_devices(backend=backend)


def tearDownModule():
    if REPORT:
        Path(REPORT).parent.mkdir(parents=True, exist_ok=True)
        Path(REPORT).write_text(json.dumps({'scope': 'Real PyUSB1.3.1 core, independent fake USB backend only',
            'physical_usb_access': False, 'cases': EVIDENCE}, indent=2) + '\n')


if __name__ == '__main__': unittest.main()
