"""Fault-injection matrix for the journaled eDLT update and its explicit resume.

Every case drives the independent memory DFU peer (directly, or through real
PyUSB with a fake claimed backend) and asserts three things: the device-side
memory, what the tool reports and journals, and that no request was retried.
Images are the synthetic fixture bytes; no hardware or vendor file is used.
"""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

import usb.core

from cbus_toolkit import firmware_update_plan as api
from cbus_toolkit import firmware_update_run as run
from cbus_toolkit.dfu_simulator import DFUDisconnect, DFUSimulator, FaultInjectingPeer, SimulatedProcessDeath
from cbus_toolkit.dfu_transport import parse_descriptors

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ROOT / 'research/fixtures/firmware-update-packages'
sys.path.insert(0, str(ROOT))
from research.build_firmware_update_fixtures import PACKAGES as FIXTURE_SPEC, image  # noqa: E402

PACKAGE = PACKAGES / 'eDLTFirmware_1.8.0.zip'   # unlisted version: font and main stages
DESCRIPTOR = parse_descriptors(api.SIMULATOR_DEVICE_DESCRIPTOR, api.SIMULATOR_CONFIGURATION_DESCRIPTOR)
FLASH, EXTERNAL = 262144, 131072
FONT, MAIN = 'edlt_fontdata_1.1.0.bin', 'edlt_main_hwv2_1_8_0.bin'
OLD = bytes(range(251)) * 600   # prior firmware/font bytes that must be erased
ERASE, PROGRAM, READ = 4, 1, 2


def images():
    return {name: image(name, size, address) for name, size, address in FIXTURE_SPEC[PACKAGE.name][1]}


def plan(variant='TivaPCI'):
    return api.update_plan(PACKAGE, variant=variant)


def device(application_start=0x4000):
    peer = DFUSimulator(flash_size=FLASH, application_start=application_start, external_size=EXTERNAL)
    peer.internal[application_start:application_start + 8192] = OLD[:8192]
    peer.external[:EXTERNAL] = OLD[:EXTERNAL]
    return peer


def sha(data):
    return hashlib.sha256(bytes(data)).hexdigest()


class Rig:
    """One simulated device plus the host-side pieces a run needs."""
    def __init__(self, directory, peer=None, *, serial='ABC123', **fault):
        self.peer = peer or device()
        self.faulty = FaultInjectingPeer(self.peer, **fault) if fault else None
        self.target = self.faulty or self.peer
        self.opener = run.MemoryDeviceOpener(self.target, DESCRIPTOR, serial=serial)
        self.journal = Path(directory, 'update.journal')
        self.clock = api._VirtualClock()

    def options(self):
        return dict(opener=self.opener, clock=self.clock, sleep=self.clock.sleep)

    def run(self, update_plan=None, update_images=None):
        return run.run_update(update_plan or plan(), update_images or images(), journal_path=self.journal,
                              flash_size=FLASH, external_size=EXTERNAL, **self.options())

    def resume(self, opener=None, update_plan=None):
        options = self.options()
        if opener is not None:
            options['opener'] = opener
        return run.resume_update(self.journal, update_plan or plan(), images(), **options)

    def commands(self):
        return dict(self.faulty.commands) if self.faulty else {}

    def journal_doc(self):
        return run.load_journal(self.journal)[0]


class FaultMatrixTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        self.directory = folder.name

    def assert_installed(self, peer):
        data = images()
        self.assertEqual(bytes(peer.internal[0x4000:0x4000 + len(data[MAIN])]), data[MAIN])
        self.assertEqual(bytes(peer.external[:len(data[FONT])]), data[FONT])
        self.assertEqual(bytes(peer.external[len(data[FONT]):]), b'\xff' * (EXTERNAL - len(data[FONT])))
        # The main erase is rounded to 1024-byte blocks; nothing past it is touched.
        end = 0x4000 + 2048
        self.assertEqual(bytes(peer.internal[0x4000 + len(data[MAIN]):end]), b'\xff' * (end - 0x4000 - len(data[MAIN])))
        self.assertEqual(bytes(peer.internal[end:0x4000 + 8192]), OLD[2048:8192])

    def assert_stopped(self, result, *, stage, phase, status='interrupted'):
        self.assertFalse(result['complete']); self.assertFalse(result['refused'])
        self.assertEqual((result['failed_stage'], result['failed_phase'], result['status']), (stage, phase, status))
        self.assertTrue(result['resume_required']); self.assertFalse(result['retried'])
        self.assertIn('update-resume', result['next_action'])

    def test_clean_run_journals_before_each_destructive_step_and_installs_both_stages(self):
        rig = Rig(self.directory, trigger='status', effect='hang', offset=10**9)
        result = rig.run()
        self.assertTrue(result['complete'], result['error'])
        self.assertTrue(result['journal_created'])
        self.assertEqual(result['stages'], {'font': 'verified', 'main': 'verified'})
        self.assert_installed(rig.peer)
        doc = rig.journal_doc()
        self.assertEqual(doc['status'], 'complete')
        self.assertTrue(doc['send_may_have_occurred']); self.assertFalse(doc['replay_authorized'])
        events = [(row['event'], row['stage']) for row in doc['history']]
        self.assertEqual(events, [('journal-created', None)] + [
            (event, stage) for stage in ('font', 'main') for event in
            ('erase-sent', 'erase-result', 'erased', 'write-sent', 'write-result', 'verified')]
            + [('run-complete', None)])
        self.assertEqual([name for name, _ in events if name.endswith('-sent')],
                         ['erase-sent', 'write-sent', 'erase-sent', 'write-sent'])
        # Two inspections, then one erase and one program per stage; each once.
        self.assertEqual([row['operation'] for row in result['operations']],
                         ['inspect', 'inspect', 'erase', 'program', 'erase', 'program'])
        self.assertEqual(rig.commands()[ERASE], 2); self.assertEqual(rig.commands()[PROGRAM], 2)
        self.assertEqual(rig.opener.opens, 6)
        self.assertEqual(run.resume_update(rig.journal, plan(), images(), **rig.options())['refusal_kind'],
                         'journal-complete')

    def test_wrong_variant_device_is_refused_before_journal_or_any_write(self):
        peer = device(application_start=0x2000); before = (sha(peer.internal), sha(peer.external))
        rig = Rig(self.directory, peer, trigger='status', effect='hang', offset=10**9)
        result = rig.run()
        self.assertTrue(result['refused']); self.assertEqual(result['refusal_kind'], 'variant-mismatch')
        self.assertIn('StellarisPCI', result['error']); self.assertIn('TivaPCI', result['error'])
        self.assertFalse(result['journal_created']); self.assertFalse(rig.journal.exists())
        self.assertFalse(result['resume_required'])
        self.assertEqual((sha(peer.internal), sha(peer.external)), before)
        self.assertNotIn(ERASE, rig.commands()); self.assertNotIn(PROGRAM, rig.commands())
        self.assertEqual(rig.opener.opens, 1)

    def test_wrong_variant_image_is_refused_before_any_device_access(self):
        rig = Rig(self.directory)
        swapped = images(); swapped[MAIN] = image(MAIN, len(swapped[MAIN]), 0x2000)
        result = rig.run(update_images=swapped)
        self.assertEqual(result['refusal_kind'], 'variant-mismatch')
        self.assertEqual(rig.opener.opens, 0); self.assertFalse(rig.journal.exists())
        truncated = images(); truncated[FONT] = truncated[FONT][:-1]
        self.assertEqual(rig.run(update_images=truncated)['refusal_kind'], 'image')
        self.assertEqual(rig.opener.opens, 0)

    def test_existing_journal_is_never_overwritten_and_blocks_the_first_erase(self):
        rig = Rig(self.directory, trigger='status', effect='hang', offset=10**9)
        rig.journal.write_text('prior evidence')
        result = rig.run()
        self.assertEqual(result['refusal_kind'], 'journal')
        self.assertEqual(rig.journal.read_text(), 'prior evidence')
        self.assertNotIn(ERASE, rig.commands())

    def test_interrupted_erase_leaves_partial_erase_and_resume_restarts_from_erase(self):
        rig = Rig(self.directory, trigger='erase', effect='disconnect', external=True, erase_fraction=0.5)
        result = rig.run()
        self.assert_stopped(result, stage='font', phase='erase-sent')
        self.assertEqual(result['stage_states']['font'], 'unknown: erase may be partial')
        self.assertEqual(bytes(rig.peer.external[:65536]), b'\xff' * 65536)
        self.assertEqual(bytes(rig.peer.external[65536:]), OLD[65536:EXTERNAL])
        # Two inspections, the erase operation's own INFO, one erase, nothing after.
        self.assertEqual(rig.commands(), {5: 3, ERASE: 1})
        self.assertEqual(rig.opener.opens, 3)
        refused = rig.resume()   # still off the bus: refused without a destructive request
        self.assertEqual(refused['refusal_kind'], 'device-unavailable')
        self.assertEqual(rig.commands(), {5: 3, ERASE: 1})
        rig.faulty.reenumerate()
        resumed = rig.resume()
        self.assertTrue(resumed['complete'], resumed['error'])
        self.assertEqual(resumed['restarted_stage'], 'font'); self.assertEqual(resumed['reverify'], [])
        self.assert_installed(rig.peer)
        self.assertEqual(rig.commands()[ERASE], 3)   # font once per run, main once
        events = [row['event'] for row in rig.journal_doc()['history']]
        self.assertEqual(events.count('resume-started'), 2); self.assertEqual(events.count('resume-refused'), 1)
        self.assertEqual(rig.journal_doc()['runs'], 3)

    def test_interrupted_write_at_several_offsets_keeps_partial_image_and_restarts_main(self):
        data = images()[MAIN]
        for offset in (0, 17, 1023, 1024, 1024 + 100, len(data) - 1):
            with self.subTest(offset=offset):
                folder = tempfile.mkdtemp(dir=self.directory)
                rig = Rig(folder, trigger='program-data', effect='power-loss', external=False, offset=offset)
                result = rig.run()
                self.assert_stopped(result, stage='main', phase='write-sent')
                self.assertEqual(result['stages']['font'], 'verified')
                written = bytes(rig.peer.internal[0x4000:0x4000 + len(data)])
                self.assertEqual(written[:offset], data[:offset])
                self.assertEqual(written[offset:], b'\xff' * (len(data) - offset))
                self.assertEqual(rig.commands()[PROGRAM], 2)
                self.assertEqual(rig.faulty.fault_record['address'], 0x4000 + offset)
                rig.faulty.reenumerate()
                resumed = rig.resume()
                self.assertTrue(resumed['complete'], resumed['error'])
                self.assertEqual(resumed['reverify'], [{'stage': 'font', 'complete': True, 'first_mismatch': None}])
                self.assertEqual(resumed['restarted_stage'], 'main')
                self.assert_installed(rig.peer)
                self.assertEqual(rig.commands()[ERASE], 3); self.assertEqual(rig.commands()[PROGRAM], 3)
                restart = [row for row in rig.journal_doc()['history'] if row['event'] == 'stage-restart']
                self.assertEqual([(row['stage'], row['detail']['from_phase']) for row in restart], [('main', 'write-sent')])

    def test_interrupted_readback_is_not_trusted_even_when_flash_holds_the_image(self):
        rig = Rig(self.directory, trigger='readback-data', effect='disconnect', external=False,
                  offset=1024, occurrence=2)   # the first internal read is the main erase's blank check
        result = rig.run()
        self.assert_stopped(result, stage='main', phase='write-sent')
        self.assertEqual(result['operations'][-1]['stage'], 'main')
        self.assertEqual(result['operations'][-1]['dfu_stage'], 'readback-data')
        data = images()[MAIN]
        self.assertEqual(bytes(rig.peer.internal[0x4000:0x4000 + len(data)]), data)
        self.assertEqual(rig.commands()[READ], 4)   # font blank/image, main blank, interrupted main image
        rig.faulty.reenumerate()
        resumed = rig.resume()
        self.assertTrue(resumed['complete'])
        self.assertEqual(rig.commands()[ERASE], 3)   # main still restarted from erase

    def test_bootloader_timeout_stops_without_retry_until_power_cycle(self):
        rig = Rig(self.directory, trigger='erase', effect='hang', external=False, erase_fraction=0)
        result = rig.run()
        self.assert_stopped(result, stage='main', phase='erase-sent')
        self.assertRegex(result['error'], 'polling limit|deadline')
        self.assertEqual(rig.commands()[ERASE], 2); self.assertEqual(rig.opener.opens, 5)
        self.assertEqual(bytes(rig.peer.internal[0x4000:0x4000 + 8192]), OLD[:8192])
        hung = rig.resume()   # the hung bootloader cannot be inspected: refused before any erase
        self.assertEqual(hung['refusal_kind'], 'inspection-failed')
        self.assertEqual(rig.commands()[ERASE], 2)
        rig.faulty.reenumerate()
        self.assertTrue(rig.resume()['complete'])
        self.assert_installed(rig.peer)

    def test_host_crash_leaves_a_durable_in_progress_journal_that_resume_accepts(self):
        rig = Rig(self.directory, trigger='program-data', effect='crash', external=False, offset=1100)
        with self.assertRaises(SimulatedProcessDeath):
            rig.run()
        doc = rig.journal_doc()
        self.assertEqual(doc['status'], 'in-progress')
        self.assertEqual(doc['stages'], {'font': 'verified', 'main': 'write-sent'})
        self.assertEqual(doc['history'][-1]['event'], 'write-sent')
        data = images()[MAIN]
        self.assertEqual(bytes(rig.peer.internal[0x4000:0x4000 + 1100]), data[:1100])
        # A new process: fresh opener and clock; the device is still attached.
        fresh = run.MemoryDeviceOpener(rig.target, DESCRIPTOR, serial='ABC123')
        resumed = rig.resume(opener=fresh)
        self.assertTrue(resumed['complete'], resumed['error'])
        self.assertEqual(resumed['restarted_stage'], 'main')
        self.assert_installed(rig.peer)

    def test_resume_refuses_changed_identity_or_variant_without_destructive_requests(self):
        rig = Rig(self.directory, trigger='program-data', effect='disconnect', external=False, offset=700)
        rig.run(); rig.faulty.reenumerate()
        destructive = lambda: (rig.commands()[ERASE], rig.commands()[PROGRAM])
        before = (sha(rig.peer.internal), sha(rig.peer.external), destructive())
        other = run.MemoryDeviceOpener(rig.target, DESCRIPTOR, serial='OTHER1')
        refused = rig.resume(opener=other)
        self.assertEqual(refused['refusal_kind'], 'identity-changed')
        self.assertEqual(refused['refusal_detail'], {'changed': ['usb_serial']})
        replacement = device(application_start=0x2000)
        refused_variant = rig.resume(opener=run.MemoryDeviceOpener(replacement, DESCRIPTOR, serial='ABC123'))
        self.assertEqual(refused_variant['refusal_kind'], 'variant-mismatch')
        self.assertEqual((sha(rig.peer.internal), sha(rig.peer.external), destructive()), before)
        self.assertEqual(replacement.programmed_bytes, 0)
        doc = rig.journal_doc()
        self.assertEqual([row['detail']['kind'] for row in doc['history'] if row['event'] == 'resume-refused'],
                         ['identity-changed', 'variant-mismatch'])
        self.assertEqual(doc['stages'], {'font': 'verified', 'main': 'write-sent'})
        self.assertTrue(rig.resume()['complete'])

    def test_resume_reverifies_verified_stages_and_restarts_a_changed_one(self):
        rig = Rig(self.directory, trigger='program-data', effect='disconnect', external=False, offset=10)
        rig.run(); rig.faulty.reenumerate()
        rig.peer.external[5] ^= 0xff
        resumed = rig.resume()
        self.assertTrue(resumed['complete'])
        self.assertEqual(resumed['reverify'], [{'stage': 'font', 'complete': False, 'first_mismatch': 5}])
        self.assertEqual(resumed['restarted_stage'], 'font')
        self.assert_installed(rig.peer)

    def test_resume_refuses_other_package_selection_and_tampered_journal(self):
        rig = Rig(self.directory, trigger='program-data', effect='disconnect', external=False, offset=10)
        rig.run(); rig.faulty.reenumerate(); opens = rig.opener.opens
        self.assertEqual(rig.resume(update_plan=plan('TivaNCC'))['refusal_kind'], 'journal-binding-mismatch')
        self.assertEqual(rig.opener.opens, opens)
        doc = json.loads(rig.journal.read_text()); doc['binding']['flash_size'] = 1024 * 1024
        rig.journal.write_text(json.dumps(doc))
        with self.assertRaisesRegex(run.UpdateJournalError, 'attempt_id'):
            rig.resume()
        self.assertEqual(rig.opener.opens, opens)

    def test_injector_rejects_unknown_faults_and_reenumeration_keeps_flash(self):
        with self.assertRaises(ValueError):
            FaultInjectingPeer(DFUSimulator(), trigger='nope', effect='disconnect')
        peer = DFUSimulator(); faulty = FaultInjectingPeer(peer, trigger='status', effect='disconnect', offset=1)
        with self.assertRaises(DFUDisconnect):
            faulty.control(0xA1, 3, 0, 0, length=6)
        with self.assertRaises(DFUDisconnect):
            faulty.new_host_session()
        peer.internal[8192] = 0
        faulty.reenumerate()
        self.assertEqual((peer.internal[8192], faulty.absent, faulty.enumerations), (0, False, 1))


class ReenumeratingBackend:
    """Factory for a fake claimed PyUSB backend whose device can vanish and return."""
    @staticmethod
    def create(faulty, *, serial='ABC123', address=7):
        from tests.test_usb_dfu import ClaimedBackend
        from tests.test_usb_inspection import USBFixture

        def fixture(address, serial):
            text = serial.encode('utf-16-le')
            usb_fixture = USBFixture(address=address, descriptor=api.SIMULATOR_DEVICE_DESCRIPTOR,
                                     configurations=(api.SIMULATOR_CONFIGURATION_DESCRIPTOR,))
            usb_fixture.strings[(3, 0x409)] = bytes((len(text) + 2, 3)) + text
            return usb_fixture

        class Backend(ClaimedBackend):
            def open_device(self, device):
                if device not in self.devices:
                    raise usb.core.USBError('No such device', errno=19, error_code=-4)
                handle = super().open_device(device)
                faulty.new_host_session()
                return handle

            def ctrl_transfer(self, handle, *args):
                try:
                    return super().ctrl_transfer(handle, *args)
                except DFUDisconnect as error:
                    self.devices = []
                    raise usb.core.USBError('No such device: ' + str(error), errno=19, error_code=-4) from error

            def release_interface(self, handle, interface):
                if handle not in self.devices:
                    self.lifecycle.append('release'); self.release_count += 1; self.claimed = False
                    raise usb.core.USBError('No such device', errno=19, error_code=-4)
                return super().release_interface(handle, interface)

            def replug(self, address, serial='ABC123'):
                faulty.reenumerate(); self.claimed = False
                self.devices = [fixture(address, serial)]

        return Backend([fixture(address, serial)], peer=faulty)


class USBFaultTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        self.journal = Path(folder.name, 'update.journal')

    def opener(self, backend, address, serial='ABC123'):
        return run.USBDeviceOpener(bus=1, address=address, expected_serial=serial, descriptor=DESCRIPTOR,
                                   release_policy='reset-first-alternate', backend=backend)

    def test_usb_disconnect_and_reenumeration_at_a_new_address(self):
        peer = device(); faulty = FaultInjectingPeer(peer, trigger='program-data', effect='disconnect',
                                                     external=False, offset=1100)
        backend = ReenumeratingBackend.create(faulty); clock = api._VirtualClock()
        result = run.run_update(plan(), images(), opener=self.opener(backend, 7), journal_path=self.journal,
                                flash_size=FLASH, external_size=EXTERNAL, clock=clock, sleep=clock.sleep)
        self.assertEqual((result['failed_stage'], result['failed_phase']), ('main', 'write-sent'))
        self.assertIn('No such device', result['error'])
        self.assertFalse(result['releases'][-1]['complete'])   # release on a vanished device is reported
        opens = backend.open_count
        self.assertEqual(faulty.commands[PROGRAM], 2)
        # Same address after the device left: nothing to enumerate, nothing sent.
        gone = run.resume_update(self.journal, plan(), images(), opener=self.opener(backend, 7),
                                 clock=clock, sleep=clock.sleep)
        self.assertEqual(gone['refusal_kind'], 'device-unavailable')
        self.assertEqual(backend.open_count, opens)
        backend.replug(9, serial='ZZZ999')
        swapped = run.resume_update(self.journal, plan(), images(), opener=self.opener(backend, 9, 'ZZZ999'),
                                    clock=clock, sleep=clock.sleep)
        self.assertEqual(swapped['refusal_kind'], 'identity-changed')
        self.assertEqual(faulty.commands.get(ERASE), 2)
        backend.replug(9)
        resumed = run.resume_update(self.journal, plan(), images(), opener=self.opener(backend, 9),
                                    clock=clock, sleep=clock.sleep)
        self.assertTrue(resumed['complete'], resumed['error'])
        self.assertEqual(resumed['restarted_stage'], 'main')
        self.assertTrue(all(release['complete'] for release in resumed['releases']))
        self.assertEqual(faulty.commands[ERASE], 3); self.assertEqual(faulty.commands[PROGRAM], 3)
        self.assertNotIn('FORBIDDEN', backend.events)
        FaultMatrixTests.assert_installed(self, peer)


class CLITests(unittest.TestCase):
    def test_update_run_and_resume_commands_through_fake_pyusb(self):
        from contextlib import redirect_stderr, redirect_stdout
        import io
        from unittest.mock import patch
        from cbus_toolkit.cli import main
        from tests.test_firmware_update_plan import PASSWORD
        peer = device(); faulty = FaultInjectingPeer(peer, trigger='erase', effect='disconnect', external=True)
        backend = ReenumeratingBackend.create(faulty)
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            (folder / 'password').write_bytes(PASSWORD)
            (folder / 'device.bin').write_bytes(api.SIMULATOR_DEVICE_DESCRIPTOR)
            (folder / 'config.bin').write_bytes(api.SIMULATOR_CONFIGURATION_DESCRIPTOR)
            common = [str(PACKAGE), '--journal', str(folder / 'update.journal'),
                      '--package-password-file', str(folder / 'password'), '--bus', '1',
                      '--device-descriptor', str(folder / 'device.bin'),
                      '--configuration-descriptor', str(folder / 'config.bin'),
                      '--release-policy', 'reset-first-alternate']

            def cli(*argv, status):
                out, err = io.StringIO(), io.StringIO()
                with patch('usb.backend.libusb1.get_backend', return_value=backend), \
                        redirect_stdout(out), redirect_stderr(err):
                    code = main(['firmware', *argv])
                self.assertEqual(code, status, out.getvalue() + err.getvalue())
                self.assertNotIn(PASSWORD.decode(), out.getvalue() + err.getvalue())
                return json.loads(out.getvalue() or err.getvalue())
            stopped = cli('update-run', *common, '--address', '7', '--expected-serial', 'ABC123',
                          '--variant', 'TivaPCI', '--flash-size', str(FLASH), '--external-size', str(EXTERNAL),
                          status=1)
            self.assertEqual((stopped['failed_stage'], stopped['failed_phase']), ('font', 'erase-sent'))
            backend.replug(11)
            resumed = cli('update-resume', *common, '--address', '11', status=0)
            self.assertTrue(resumed['complete'])
            self.assertEqual(resumed['restarted_stage'], 'font')
            self.assertFalse(resumed['physical_device_verified'])
        FaultMatrixTests.assert_installed(self, peer)



class HardwareGateTemplateTests(unittest.TestCase):
    def test_template_passes_the_release_gate_schema_and_names_the_fixture(self):
        from research import release_gate
        template = ROOT / 'research/release-gates/hardware-usb-dfu.template.json'
        manifest = release_gate.load_manifest(template, 'hardware')
        self.assertEqual(manifest['tests'], ['tests/test_usb_dfu_physical.py'])
        self.assertEqual(manifest['required_environment']['CBUS_HARDWARE_ACCEPTANCE'], {'kind': 'flag'})
        # The committed template carries provision kinds only, never values or paths.
        self.assertTrue(all(set(rule) == {'kind'} for rule in manifest['required_environment'].values()))
        matrix = json.loads((ROOT / 'research/hardware-fixture-matrix.json').read_text())
        rows = {row['id']: row for row in matrix['fixtures']}
        for fixture in manifest['fixture_ids']:
            self.assertEqual({item['id'] for item in rows[fixture]['work_items']} & {'P10.02', 'P10.03'},
                             set(manifest['work_items']))
        with self.assertRaises(release_gate.GateError):
            release_gate.verify_provision(manifest, {})
        physical = (ROOT / 'tests/test_usb_dfu_physical.py').read_text()
        from tests.test_usb_dfu_physical import PROVISIONS
        self.assertEqual(set(PROVISIONS) | {'CBUS_HARDWARE_ACCEPTANCE'}, set(manifest['required_environment']))
        self.assertIn("os.environ.get('CBUS_HARDWARE_ACCEPTANCE') == '1'", physical)
        self.assertTrue((ROOT / 'docs/usb-dfu-hardware-runbook.md').is_file())


if __name__ == '__main__':
    unittest.main()
