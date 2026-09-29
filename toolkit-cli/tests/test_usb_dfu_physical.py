"""Physical eDLT USB DFU acceptance for issues #65 and #66. Hardware gate only.

A private manifest derived from
research/release-gates/hardware-usb-dfu.template.json selects this module; the
operator follows docs/usb-dfu-hardware-runbook.md. Once
CBUS_HARDWARE_ACCEPTANCE=1, a missing provision fails instead of skipping.
These tests write firmware to the selected, disposable unit only.
"""
import os
from pathlib import Path
import tempfile
import unittest

from cbus_toolkit import firmware_update_plan as updater
from cbus_toolkit import firmware_update_run as run
from cbus_toolkit.dfu_simulator import SimulatedProcessDeath
from cbus_toolkit.dfu_transport import parse_descriptors
from cbus_toolkit.usb_inspection import inspect_edlt_device

PROVISIONS = ('CBUS_USB_DFU_BUS', 'CBUS_USB_DFU_ADDRESS', 'CBUS_USB_DFU_SERIAL',
              'CBUS_USB_DFU_DEVICE_DESCRIPTOR', 'CBUS_USB_DFU_CONFIGURATION_DESCRIPTOR',
              'CBUS_USB_DFU_VARIANT', 'CBUS_USB_DFU_FLASH_SIZE', 'CBUS_USB_DFU_EXTERNAL_SIZE',
              'CBUS_EDLT_FIRMWARE_PACKAGE', 'CBUS_EDLT_PACKAGE_PASSWORD_FILE')


class AbortBeforeProgramBlock:
    """Host-side process death before the Nth internal program data block is sent."""
    def __init__(self, opener, block):
        self.opener = opener; self.block = block; self.sent = None

    def open(self):
        session = self.opener.open(); outer = self; endpoint = session.endpoint

        class Endpoint:
            def control(self, bm, request, value, index, *, data=b'', length=0, timeout):
                if bm == 0x21 and request == 1 and data:
                    if outer.sent is None and data[0] == 1 and len(data) == 8:
                        outer.sent = 0
                    elif outer.sent is not None:
                        if outer.sent + 1 == outer.block:
                            raise SimulatedProcessDeath('Deliberate host abort during the main write')
                        outer.sent += 1
                return endpoint.control(bm, request, value, index, data=data, length=length, timeout=timeout)

            def close(self):
                endpoint.close()
        return run.DeviceSession(Endpoint(), session.descriptor, session.identity, session._release)


@unittest.skipUnless(os.environ.get('CBUS_HARDWARE_ACCEPTANCE') == '1',
                     'physical eDLT USB DFU acceptance is not provisioned')
class PhysicalUSBDFUTests(unittest.TestCase):
    def setUp(self):
        missing = [name for name in PROVISIONS if not os.environ.get(name)]
        self.assertEqual(missing, [], 'hardware gate provisions are missing')
        env = os.environ
        self.bus, self.address = int(env['CBUS_USB_DFU_BUS'], 0), int(env['CBUS_USB_DFU_ADDRESS'], 0)
        self.serial = env['CBUS_USB_DFU_SERIAL']
        self.descriptor = parse_descriptors(Path(env['CBUS_USB_DFU_DEVICE_DESCRIPTOR']).read_bytes(),
                                            Path(env['CBUS_USB_DFU_CONFIGURATION_DESCRIPTOR']).read_bytes())
        self.flash_size = int(env['CBUS_USB_DFU_FLASH_SIZE'], 0)
        self.external_size = int(env['CBUS_USB_DFU_EXTERNAL_SIZE'], 0)
        package = Path(env['CBUS_EDLT_FIRMWARE_PACKAGE'])
        password, _ = updater.read_password_file(env['CBUS_EDLT_PACKAGE_PASSWORD_FILE'])
        self.plan = updater.update_plan(package, variant=env['CBUS_USB_DFU_VARIANT'], force_font=True)
        self.assertTrue(self.plan['supported'], self.plan['issues'])
        self.images = updater.load_selected_images(package, self.plan, password)
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        self.journal = Path(folder.name, 'update.journal')

    def opener(self):
        return run.USBDeviceOpener(bus=self.bus, address=self.address, expected_serial=self.serial,
                                   descriptor=self.descriptor, release_policy='reset-first-alternate')

    def verify(self):
        result = run.verify_device(self.plan, self.images, opener=self.opener(), flash_size=self.flash_size,
                                   external_size=self.external_size)
        self.assertTrue(result['complete'], result)
        return result

    def test_01_read_only_identity_matches_the_provisioned_unit(self):
        result = inspect_edlt_device(bus=self.bus, address=self.address, expected_serial=self.serial, timeout=5)
        self.assertTrue(result.complete, result.error)
        self.assertTrue(result.expected_serial_matches)

    def test_02_journaled_update_then_fresh_session_readback(self):
        result = run.run_update(self.plan, self.images, opener=self.opener(), journal_path=self.journal,
                                flash_size=self.flash_size, external_size=self.external_size)
        self.assertTrue(result['complete'], result)
        self.assertEqual(set(result['stages'].values()), {'verified'})
        self.assertTrue(all(release['complete'] for release in result['releases']))
        self.verify()

    def test_03_host_abort_mid_write_then_explicit_resume(self):
        with self.assertRaises(SimulatedProcessDeath):
            run.run_update(self.plan, self.images, opener=AbortBeforeProgramBlock(self.opener(), 2),
                           journal_path=self.journal, flash_size=self.flash_size, external_size=self.external_size)
        doc, _ = run.load_journal(self.journal)
        self.assertEqual((doc['status'], doc['stages']['main']), ('in-progress', 'write-sent'))
        resumed = run.resume_update(self.journal, self.plan, self.images, opener=self.opener())
        self.assertTrue(resumed['complete'], resumed)
        self.assertEqual(resumed['restarted_stage'], 'main')
        self.verify()


if __name__ == '__main__':
    unittest.main()
