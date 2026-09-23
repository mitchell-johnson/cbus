"""CLI through actual PyUSB, an explicit fake backend and independent flash."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import usb.core

from cbus_toolkit.cli import main
from tests.test_usb_dfu import ClaimedBackend
from tests.test_usb_inspection import DEVICE, CONFIG


class USBDfuCLITests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        directory = Path(self.folder.name)
        self.device = directory / 'device.bin'; self.device.write_bytes(DEVICE)
        self.configuration = directory / 'configuration.bin'; self.configuration.write_bytes(CONFIG)
        self.payload = bytes(range(256))*5
        self.binary = directory / 'raw.bin'; self.binary.write_bytes(self.payload)
        self.options = ['--bus','1','--address','7','--expected-serial','ABC123',
            '--device-descriptor',str(self.device),'--configuration-descriptor',str(self.configuration),
            '--release-policy','reset-first-alternate','--flash-size','262144','--application-start','8192']

    def cli(self, backend, action, *args, status=0, options=None):
        out, err = io.StringIO(), io.StringIO()
        argv = ['firmware', action, *(self.options if options is None else options), *map(str,args)]
        with patch('usb.backend.libusb1.get_backend', return_value=backend), redirect_stdout(out), redirect_stderr(err):
            code = main(argv)
        self.assertEqual(code, status, out.getvalue() + err.getvalue())
        self.assertNotIn('FORBIDDEN', backend.events)
        return json.loads(out.getvalue() or err.getvalue())

    def test_inspection_has_separate_acquisition_transfer_and_release_evidence(self):
        backend = ClaimedBackend()
        result = self.cli(backend, 'usb-dfu-inspect')
        self.assertTrue(result['complete'])
        self.assertTrue(result['acquisition']['complete'])
        self.assertTrue(result['transfer']['complete'])
        self.assertTrue(result['release']['complete'])
        self.assertTrue(result['release']['implicit_set_interface_possible'])
        self.assertFalse(result['physical_device_verified'])
        self.assertEqual(result['acquisition']['serial'], 'ABC123')
        self.assertEqual((backend.open_count,backend.claim_count,backend.release_count,backend.close_count), (1,1,1,1))
        self.assertEqual(backend.peer.programmed_bytes,0)
        self.assertFalse(backend.peer.detached)

    def test_program_and_erase_verify_whole_range_and_preserve_adjacent_bytes(self):
        backend = ClaimedBackend()
        before = bytes(backend.peer.internal)
        result = self.cli(backend, 'usb-dfu-program', self.binary, '--offset', '0x2000')
        self.assertTrue(result['complete'])
        self.assertEqual(result['transfer']['readback_bytes'],len(self.payload))
        self.assertTrue(result['transfer']['peer_verified'])
        self.assertEqual(bytes(backend.peer.internal), before[:8192]+self.payload+before[9472:])
        self.assertEqual(backend.peer.completed_programs,1)
        self.assertEqual(backend.lifecycle[-2:], ['release','close'])
        erase = ClaimedBackend()
        erase.peer.internal[8192:11264] = b'\0'*3072
        result = self.cli(erase, 'usb-dfu-erase', '--offset',8192,'--length',2048)
        self.assertTrue(result['complete'])
        self.assertEqual(result['transfer']['readback_bytes'],2048)
        self.assertEqual(bytes(erase.peer.internal[8192:11264]),b'\xff'*2048+b'\0'*1024)
        self.assertEqual((erase.claim_count,erase.release_count,erase.close_count),(1,1,1))
        self.assertFalse(erase.peer.detached)

    def test_invalid_file_descriptor_or_range_fails_before_usb_access(self):
        for action,args in (('usb-dfu-program',(self.binary,'--offset',0)),
                            ('usb-dfu-erase',('--offset',8192,'--length',1025)),
                            ('usb-dfu-inspect',('--flash-size',1)),
                            ('usb-dfu-program',(Path(self.folder.name)/'missing.bin','--offset',8192))):
            backend = ClaimedBackend()
            result = self.cli(backend,action,*args,status=1)
            self.assertIn('error',result)
            self.assertEqual(backend.events,[])
        self.device.write_bytes(DEVICE+b'\0')
        backend = ClaimedBackend()
        self.assertIn('eighteen',self.cli(backend,'usb-dfu-inspect',status=1)['error'])
        self.assertEqual(backend.events,[])

    def test_serial_mismatch_stops_before_claim_and_release_failure_changes_exit(self):
        backend = ClaimedBackend()
        result = self.cli(backend,'usb-dfu-inspect','--expected-serial','MISMATCH',status=1)
        self.assertFalse(result['acquisition']['complete'])
        self.assertIsNone(result['transfer'])
        self.assertFalse(result['operation_invoked'])
        self.assertTrue(result['release']['complete'])
        self.assertEqual((backend.claim_count,backend.release_count,backend.close_count),(0,0,1))
        backend = ClaimedBackend(release_error=usb.core.USBError('release failed'))
        result = self.cli(backend,'usb-dfu-inspect',status=1)
        self.assertTrue(result['transfer']['complete'])
        self.assertFalse(result['release']['complete'])
        self.assertIn('release failed',result['release']['release_error'])
        self.assertTrue(result['release']['close_succeeded'])
        self.assertEqual((backend.release_count,backend.close_count),(1,1))

    def test_interrupted_program_returns_partial_evidence_and_never_replays(self):
        def interrupt(backend,fixture,row,normal):
            if row.get('out_data') == self.payload[:1024].hex():
                raise KeyboardInterrupt()
            return normal
        backend = ClaimedBackend(fault=interrupt)
        result = self.cli(backend,'usb-dfu-program',self.binary,'--offset',8192,status=130)
        self.assertEqual(result['error'],'Interrupted')
        evidence = result['usb_dfu_evidence']
        self.assertFalse(evidence['complete'])
        self.assertFalse(evidence['transfer']['outcome_known'])
        self.assertEqual(evidence['transfer']['stage'],'program-data')
        self.assertTrue(evidence['release']['complete'])
        self.assertEqual(backend.peer.programmed_bytes,1024)
        self.assertEqual(bytes(backend.peer.internal[8192:9216]),self.payload[:1024])
        self.assertEqual(bytes(backend.peer.internal[9216:9472]),b'\xff'*256)
        self.assertEqual(backend.lifecycle[-3:],['control:21:01','release','close'])
        self.assertEqual(backend.peer.completed_programs,0)
        self.assertEqual((backend.release_count,backend.close_count),(1,1))

    def test_release_policy_is_required_by_cli_before_any_usb_access(self):
        options = list(self.options)
        index = options.index('--release-policy'); del options[index:index+2]
        backend = ClaimedBackend(); out,err = io.StringIO(),io.StringIO()
        with patch('usb.backend.libusb1.get_backend',return_value=backend), redirect_stdout(out), redirect_stderr(err):
            with self.assertRaises(SystemExit) as failure:
                main(['firmware','usb-dfu-inspect',*options])
        self.assertEqual(failure.exception.code,2)
        self.assertIn('--release-policy',err.getvalue())
        self.assertEqual(backend.events,[])


if __name__ == '__main__':
    unittest.main()
