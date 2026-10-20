"""Serial port listing with mocked enumeration, and per-port probe outcomes.

Enumeration is injected; probed ports are real pseudo-terminals served by the
probe tests' PCISimulator line peer, or factories that raise open errors.
"""
import errno
import importlib.util
import io
import json
import os
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest import mock

from cbus_toolkit import cli
from cbus_toolkit.pci_serial_list import FORMAT, classify, list_serial_ports, render_text
from cbus_toolkit.pci_serial_probe import RESET_FRAMES
from test_pci_serial_probe import POSIX_SERIAL, PtyPCIPeer, SerialSimulatorLine

PYSERIAL = importlib.util.find_spec("serial") is not None


def port(device, **fields):
    defaults = dict(name=os.path.basename(device), description="n/a", hwid="n/a", vid=None, pid=None,
                    serial_number=None, manufacturer=None, product=None, location=None)
    return SimpleNamespace(device=device, **{**defaults, **fields})


FTDI = port("/dev/ttyUSB0", description="FT232R USB UART", hwid="USB VID:PID=0403:6001 SER=A1B2C3 LOCATION=1-1",
            vid=0x0403, pid=0x6001, serial_number="A1B2C3", manufacturer="FTDI", product="FT232R USB UART",
            location="1-1")


def raising(error):
    def factory(**kwargs):
        raise error
    return factory


class ListingTests(unittest.TestCase):
    def test_empty_list(self):
        report = list_serial_ports(comports=lambda: [])
        self.assertEqual((report["format"], report["ports"], report["port_count"]), (FORMAT, [], 0))
        self.assertNotIn("outcome_counts", report)
        self.assertEqual(render_text(report), "No serial ports found.")

    def test_empty_list_with_probe_opens_nothing(self):
        opened = []
        report = list_serial_ports(probe=True, comports=lambda: [], serial_factory=opened.append)
        self.assertEqual(report["outcome_counts"], dict.fromkeys(
            ("found", "no_response", "busy", "permission_denied", "error"), 0))
        self.assertEqual(opened, [])
        self.assertIn("0 port(s) probed at 9600 baud", render_text(report))

    def test_metadata_is_reported_sorted_and_without_opening(self):
        opened = []
        report = list_serial_ports(comports=lambda: [port("/dev/ttyS0"), FTDI], serial_factory=opened.append)
        self.assertEqual(opened, [])
        self.assertEqual([entry["device"] for entry in report["ports"]], ["/dev/ttyS0", "/dev/ttyUSB0"])
        plain, usb = report["ports"]
        self.assertEqual((plain["description"], plain["hwid"], plain["vid_pid"]), (None, None, None))
        self.assertEqual(usb, {"device": "/dev/ttyUSB0", "name": "ttyUSB0", "description": "FT232R USB UART",
                               "hwid": "USB VID:PID=0403:6001 SER=A1B2C3 LOCATION=1-1", "vid": 0x0403,
                               "pid": 0x6001, "vid_pid": "0403:6001", "serial_number": "A1B2C3",
                               "manufacturer": "FTDI", "product": "FT232R USB UART", "location": "1-1"})
        self.assertNotIn("outcome", usb)
        text = render_text(report)
        self.assertIn("/dev/ttyUSB0\n  description: FT232R USB UART\n", text)
        self.assertIn("  vid_pid: 0403:6001\n  serial_number: A1B2C3", text)

    def test_text_is_ascii_escaped(self):
        report = list_serial_ports(comports=lambda: [port("COM3", description="Café \U0001F50C")])
        text = render_text(report)
        text.encode("ascii")
        self.assertIn("Caf\\xe9 \\U0001f50c", text)

    @unittest.skipUnless(PYSERIAL, "serial extra required")
    def test_default_enumeration_uses_pyserial_list_ports(self):
        with mock.patch("serial.tools.list_ports.comports", return_value=[FTDI]) as comports:
            report = list_serial_ports()
        comports.assert_called_once_with()
        self.assertEqual(report["ports"][0]["serial_number"], "A1B2C3")

    def test_probe_bounds_are_validated_before_enumeration(self):
        listed = []
        for kwargs in ({"baud": 19200}, {"timeout": 0}, {"timeout": 61}):
            with self.assertRaises(ValueError):
                list_serial_ports(probe=True, comports=lambda: listed.append(1) or [], **kwargs)
        self.assertEqual(listed, [])

    def test_open_failures_are_distinct_outcomes(self):
        cases = {
            "busy-ebusy": (OSError(errno.EBUSY, "Device or resource busy"), "busy"),
            "busy-flock": (OSError("Could not exclusively lock port /dev/x: [Errno 11] Resource temporarily unavailable"),
                           "busy"),
            "busy-eagain": (OSError(errno.EAGAIN, "Resource temporarily unavailable"), "busy"),
            "denied-eacces": (PermissionError(errno.EACCES, "Permission denied"), "permission_denied"),
            "denied-eperm": (OSError(errno.EPERM, "Operation not permitted"), "permission_denied"),
            "windows-in-use": (OSError("could not open port 'COM3': PermissionError(13, 'Access is denied.')"), "busy"),
            "gone": (OSError(errno.ENOENT, "No such file or directory"), "error"),
            "io": (OSError(errno.EIO, "Input/output error"), "error"),
        }
        for name, (error, expected) in cases.items():
            with self.subTest(name):
                report = list_serial_ports(probe=True, timeout=1, comports=lambda: [FTDI],
                                           serial_factory=raising(error))
                entry = report["ports"][0]
                self.assertEqual(entry["outcome"], expected, entry)
                self.assertEqual(entry["probe"]["wire"]["sent"], [])
                self.assertIsNone(entry["identity"])
                self.assertEqual(report["outcome_counts"][expected], 1)

    def test_pyserial_wrapped_lock_failure_is_busy(self):
        try:
            raise OSError(errno.EAGAIN, "Resource temporarily unavailable")
        except OSError as cause:
            wrapped = OSError(f"Could not exclusively lock port /dev/ttyUSB0: {cause}")
            wrapped.__cause__ = cause
        report = list_serial_ports(probe=True, timeout=1, comports=lambda: [FTDI],
                                   serial_factory=raising(wrapped))
        self.assertEqual(report["ports"][0]["outcome"], "busy")

    def test_classify_maps_every_probe_outcome(self):
        expected = {"present": "found", "absent": "no_response", "timeout": "no_response", "busy": "busy",
                    "malformed": "error", "not_found": "error", "rejected": "error", "error": "error"}
        for outcome, mapped in expected.items():
            self.assertEqual(classify({"outcome": outcome}), mapped, outcome)
        self.assertEqual(classify({"outcome": "busy"}, OSError(errno.EACCES, "denied")), "permission_denied")

    def test_probe_function_failure_shape_and_unusable_device_name(self):
        calls = []

        def probe(device, **kwargs):
            calls.append((device, kwargs["setup"]))
            return {"outcome": "rejected", "detail": "identify: refused", "identity": None}
        opened = []
        report = list_serial_ports(probe=True, comports=lambda: [port("bad\x01name")],
                                   serial_factory=opened.append)
        self.assertEqual(report["ports"][0]["outcome"], "error")
        self.assertIn("explicit serial port", report["ports"][0]["detail"])
        self.assertIsNone(report["ports"][0]["probe"])
        self.assertEqual(opened, [])
        report = list_serial_ports(probe=True, comports=lambda: [FTDI], probe_function=probe)
        self.assertEqual(calls, [("/dev/ttyUSB0", False)])
        self.assertEqual((report["ports"][0]["outcome"], report["ports"][0]["detail"]),
                         ("error", "identify: refused"))

    @unittest.skipUnless(PYSERIAL, "serial extra required")
    def test_cli_json_and_text(self):
        with mock.patch("serial.tools.list_ports.comports", return_value=[FTDI]):
            for argv, check in ((["interface", "list-serial"], lambda out: json.loads(out)["ports"][0]["vid_pid"]),
                                (["interface", "list-serial", "--format", "text"], lambda out: out.splitlines()[0])):
                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    self.assertEqual(cli.main(argv), 0)
                self.assertIn(check(stdout.getvalue()), ("0403:6001", "/dev/ttyUSB0"))
        with mock.patch("serial.tools.list_ports.comports", return_value=[]):
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                self.assertEqual(cli.main(["interface", "list-serial", "--probe", "--format", "text"]), 0)
            self.assertIn("No serial ports found.", stdout.getvalue())


@unittest.skipUnless(POSIX_SERIAL, "POSIX PTY and serial extra required")
class ListingPtyProbeTests(unittest.TestCase):
    def test_found_no_response_and_busy_across_ports(self):
        import serial
        with PtyPCIPeer(SerialSimulatorLine()) as pci, PtyPCIPeer(None) as silent, \
                PtyPCIPeer(SerialSimulatorLine()) as held:
            holder = serial.Serial(held.path, 9600, timeout=0, exclusive=True)
            try:
                ports = [port(pci.path, description="PCI"), port(silent.path), port(held.path)]
                report = list_serial_ports(probe=True, timeout=1, comports=lambda: ports)
            finally:
                holder.close()
            for peer in (pci, silent, held):
                self.assertEqual(peer.errors, [])
            outcomes = {entry["device"]: entry for entry in report["ports"]}
            found = outcomes[pci.path]
            self.assertEqual(found["outcome"], "found", found)
            self.assertEqual(found["identity"], {"unit_type": "PC_CNIED", "local_unit": 16,
                                                 "firmware_version": "5.5.00"})
            self.assertEqual(outcomes[silent.path]["outcome"], "no_response")
            self.assertEqual(outcomes[held.path]["outcome"], "busy")
            self.assertEqual(held.lines, [])
            self.assertEqual(report["outcome_counts"], {"found": 1, "no_response": 1, "busy": 1,
                                                        "permission_denied": 0, "error": 0})
            self.assertEqual(report["configuration_writes"], 0)
            # Only the probe's own frames: no device-management (A3) frame anywhere.
            for peer in (pci, silent):
                self.assertEqual(peer.lines[:4], [frame[:-1] for frame in RESET_FRAMES])
                self.assertFalse(any(line.startswith(b"A3") for line in peer.lines))
            self.assertTrue(all(entry["probe"]["setup"] == {"requested": False, "applied": False}
                                for entry in report["ports"] if entry["outcome"] != "busy"))
            text = render_text(report)
            self.assertIn("found (unit_type=PC_CNIED, firmware_version=5.5.00, local_unit=16)", text)
            self.assertIn("found=1, no_response=1, busy=1, permission_denied=0, error=0", text)

    def test_every_pci_baud_rate_is_passed_to_each_probe(self):
        from cbus_toolkit.pci_serial_probe import PCI_BAUD_RATES
        for baud in PCI_BAUD_RATES:
            with self.subTest(baud=baud), PtyPCIPeer(SerialSimulatorLine()) as pci:
                report = list_serial_ports(probe=True, baud=baud, timeout=2, comports=lambda: [port(pci.path)])
                entry = report["ports"][0]
                self.assertEqual((report["baud"], entry["probe"]["baud"], entry["outcome"]), (baud, baud, "found"))

    @unittest.skipIf(os.geteuid() == 0, "root bypasses file permissions")
    def test_unreadable_port_is_permission_denied(self):
        with PtyPCIPeer(None) as peer:
            mode = os.stat(peer.path).st_mode
            os.chmod(peer.path, 0)
            try:
                report = list_serial_ports(probe=True, timeout=1, comports=lambda: [port(peer.path)])
            finally:
                os.chmod(peer.path, mode)
            self.assertEqual(report["ports"][0]["outcome"], "permission_denied", report)
            self.assertEqual(peer.lines, [])


if __name__ == "__main__":
    unittest.main()
