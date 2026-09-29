"""Serial PCI probe classifications against pseudo-terminal peers.

The present/setup peer drives the independent PCISimulator codec through a
real pty; only serial line handling (reset, SMART/CONNECT, basic echo and the
device-management option writes) lives here. No physical port is opened.
"""
import errno
import importlib.util
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import threading
import unittest

from cbus_toolkit.pci_serial_probe import (RESET_FRAMES, SETUP_FRAMES, classify_open_error,
                                           exit_status, probe_serial_interface)
from cbus_toolkit.simulator import PCISimulator

POSIX_SERIAL = os.name == "posix" and importlib.util.find_spec("serial") is not None
RUST_PCI = Path(__file__).parents[2] / "rust" / "cbus-transport" / "src" / "pci.rs"


class PtyPCIPeer:
    """A pty master served by ``handler(line) -> bytes`` on its own thread.

    ``handler=None`` drains and discards input: an attached but silent port.
    Draining also keeps macOS tty close from waiting for unread output.
    """

    def __init__(self, handler=None):
        import pty
        self.master, self.slave = pty.openpty()
        self.path = os.ttyname(self.slave)
        self.handler, self.lines, self.errors = handler, [], []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *_):
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(2)
        os.close(self.master)
        os.close(self.slave)

    def _serve(self):
        buffer = bytearray()
        try:
            while not self._stop.is_set():
                if not select.select([self.master], [], [], 0.05)[0]:
                    continue
                buffer.extend(os.read(self.master, 1024))
                while b"\r" in buffer:
                    end = buffer.index(b"\r")
                    line = bytes(buffer[:end]).translate(None, b"\x11\x13")
                    del buffer[:end + 1]
                    self.lines.append(line)
                    reply = self.handler(line) if self.handler else b""
                    if reply:
                        os.write(self.master, reply)
        except BaseException as error:  # retained for the test thread
            self.errors.append(error)


class SerialSimulatorLine:
    """Serial-line state around PCISimulator's command decoder.

    Reset returns to basic mode (echo on, no SMART, no SRCHK) and restores the
    local PCI's power-up option bytes. ``A3 PP 00 VV`` updates those bytes;
    option 0x30 bit 0x10 selects SMART and bit 0x08 SRCHK.
    """

    def __init__(self, *, ignore_parameters=()):
        self.sim = PCISimulator(smart=False)
        self.local = self.sim.units[self.sim.local_unit]
        self.power_up = {key: self.local.parameters[key] for key in (0x21, 0x30, 0x42)}
        self.ignore = set(ignore_parameters)
        self.smart, self.context, self.dm = False, {"header": None}, []

    def __call__(self, line):
        echo = b"" if self.smart else line + b"\r"
        if line == b"~":
            self.smart, self.context = False, {"header": None}
            self.sim.command_checksum = False
            self.local.parameters.update(self.power_up)
            return echo
        if line in (b"|", b"||"):
            self.smart = True
            return echo
        if line.startswith(b"A3") and len(line) == 8 and line[4:6] == b"00":
            parameter, value = int(line[2:4], 16), int(line[6:8], 16)
            self.dm.append((parameter, value))
            if parameter in self.ignore:
                return echo
            if parameter == 0x30:
                self.smart, self.sim.command_checksum = bool(value & 0x10), bool(value & 0x08)
                self.local.parameters[0x30] = bytes([value])
            elif parameter == 0x42:
                self.local.parameters[0x42] = bytes([value])
            elif parameter in (0x21, 0x22):
                block = bytearray(self.local.parameters[0x21])
                block[parameter - 0x21] = value
                self.local.parameters[0x21] = bytes(block)
            return echo
        if not self.smart and not line.startswith(b"@"):
            return echo + b"#"
        response, _ = self.sim._command(line, self.context)
        return echo + response


def discovery_only():
    """Serial line that answers reset and BASIC discovery, then goes silent."""
    line_state = SerialSimulatorLine()
    return lambda line: line_state(line) if line in (b"~", b"|") or line.startswith(b"@") else b""


@unittest.skipUnless(POSIX_SERIAL, "POSIX PTY and serial extra required")
class SerialProbePtyTests(unittest.TestCase):
    def probe(self, handler, **options):
        with PtyPCIPeer(handler) as peer:
            result = probe_serial_interface(peer.path, **{"timeout": 2, **options})
            self.assertEqual(peer.errors, [])
            return result, peer

    def test_present_reads_identity_and_options_without_configuration_writes(self):
        line = SerialSimulatorLine()
        result, peer = self.probe(line)
        self.assertEqual(result["outcome"], "present", result)
        self.assertEqual(result["identity"], {"unit_type": "PC_CNIED", "local_unit": 16,
                                              "firmware_version": "5.5.00"})
        self.assertEqual(result["options"], {"interface_options_1": 0x55, "interface_options_3": 0x07,
                                             "application_addresses_hex": "FFFF"})
        self.assertEqual(result["configuration_writes"], 0)
        self.assertEqual(line.dm, [])
        self.assertFalse(any(sent.startswith(b"A3") for sent in peer.lines))
        self.assertEqual(peer.lines[:5], [b"~", b"~", b"~", b"|", b"@1A2001"])
        self.assertEqual(exit_status(result), 0)

    def test_setup_applies_transport_options_and_verifies_checksummed_readback(self):
        line = SerialSimulatorLine()
        result, peer = self.probe(line, setup=True)
        self.assertEqual(result["outcome"], "present", result)
        self.assertEqual(line.dm, [(0x21, 0xFF), (0x22, 0xFF), (0x42, 0x0E), (0x30, 0x79)])
        setup = result["setup"]
        self.assertTrue(setup["applied"] and setup["verified"], setup)
        self.assertEqual(setup["readback"], {"interface_options_1": 0x79, "interface_options_3": 0x0E,
                                             "application_addresses_hex": "FFFF"})
        self.assertEqual(result["options"]["interface_options_3"], 0x07)
        self.assertEqual(result["configuration_writes"], 4)
        after = peer.lines[peer.lines.index(b"A3300079") + 1:]
        self.assertEqual(len(after), 3)
        for sent in after:
            payload = bytes.fromhex(sent[1:-1].decode())
            self.assertEqual(sum(payload) & 0xFF, 0, sent)
        self.assertEqual(exit_status(result), 0)

    def test_setup_mismatch_is_reported_and_fails(self):
        result, _ = self.probe(SerialSimulatorLine(ignore_parameters={0x42}), setup=True)
        self.assertEqual(result["outcome"], "present")
        self.assertFalse(result["setup"]["verified"])
        self.assertEqual(result["setup"]["mismatches"], ["interface_options_3"])
        self.assertEqual(exit_status(result), 1)

    def test_silent_port_is_absent_and_setup_is_not_attempted(self):
        result, _ = self.probe(None, timeout=1, setup=True)
        self.assertEqual(result["outcome"], "absent", result)
        self.assertEqual(result["wire"]["received_bytes"], 0)
        self.assertEqual(result["configuration_writes"], 0)
        self.assertFalse(result["setup"]["applied"])
        self.assertIn("not attempted", result["setup"]["error"])
        self.assertEqual(exit_status(result), 1)

    def test_basic_reset_echo_without_identification_is_timeout(self):
        result, _ = self.probe(lambda line: line + b"\r" if line in (b"~", b"|") else b"", timeout=1)
        self.assertEqual(result["outcome"], "timeout", result)
        self.assertIsNone(result["identity"])
        self.assertGreater(result["wire"]["received_bytes"], 0)

    def test_loopback_echo_of_identification_is_malformed(self):
        result, _ = self.probe(lambda line: line + b"\r", timeout=1)
        self.assertEqual(result["outcome"], "malformed", result)

    def test_partial_identity_is_timeout_with_the_discovered_address(self):
        result, _ = self.probe(discovery_only(), timeout=1)
        self.assertEqual(result["outcome"], "timeout", result)
        self.assertEqual(result["identity"], {"local_unit": 16})
        self.assertIsNone(result["options"])

    def test_binary_garbage_is_malformed(self):
        result, _ = self.probe(lambda line: b"\xff\xfe\x80\x00", timeout=1)
        self.assertEqual(result["outcome"], "malformed", result)

    def test_other_text_protocol_is_malformed(self):
        result, _ = self.probe(lambda line: b"ERROR\r\n", timeout=1)
        self.assertEqual(result["outcome"], "malformed", result)
        self.assertIn("hexadecimal", result["detail"])

    def test_pci_refusal_is_rejected(self):
        result, _ = self.probe(lambda line: b"!" if line.startswith(b"@") else b"", timeout=1)
        self.assertEqual(result["outcome"], "rejected", result)

    def test_exclusive_lock_contention_is_busy_and_sends_nothing(self):
        import serial
        with PtyPCIPeer(SerialSimulatorLine()) as peer:
            holder = serial.Serial(peer.path, 9600, timeout=0, exclusive=True)
            try:
                result = probe_serial_interface(peer.path, timeout=1)
            finally:
                holder.close()
            self.assertEqual(result["outcome"], "busy", result)
            self.assertEqual(result["wire"]["sent"], [])
            self.assertEqual(peer.lines, [])
            self.assertEqual(probe_serial_interface(peer.path, timeout=2)["outcome"], "present")

    @unittest.skipIf(os.geteuid() == 0, "TIOCEXCL does not exclude root")
    def test_tiocexcl_holder_is_busy(self):
        import fcntl
        import termios
        with PtyPCIPeer(None) as peer:
            holder = os.open(peer.path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
            try:
                fcntl.ioctl(holder, termios.TIOCEXCL)
                try:
                    os.close(os.open(peer.path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK))
                except OSError as error:
                    self.assertEqual(error.errno, errno.EBUSY)
                else:
                    self.skipTest("this platform's pty driver does not enforce TIOCEXCL")
                result = probe_serial_interface(peer.path, timeout=1)
            finally:
                fcntl.ioctl(holder, termios.TIOCNXCL)
                os.close(holder)
        self.assertEqual(result["outcome"], "busy", result)

    def test_missing_and_non_terminal_paths_are_not_found(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = os.path.join(directory, "ttyMISSING")
            self.assertEqual(probe_serial_interface(missing, timeout=1)["outcome"], "not_found")
            regular = os.path.join(directory, "regular")
            Path(regular).write_bytes(b"")
            result = probe_serial_interface(regular, timeout=1)
            self.assertEqual(result["outcome"], "not_found", result)
            self.assertEqual(Path(regular).read_bytes(), b"")

    def test_cli_reports_json_and_exit_status(self):
        with PtyPCIPeer(SerialSimulatorLine()) as peer:
            process = subprocess.run([sys.executable, "-m", "cbus_toolkit", "interface", "probe-serial",
                                      peer.path, "--timeout", "2"], text=True, capture_output=True)
        self.assertEqual(process.returncode, 0, process.stderr)
        report = json.loads(process.stdout)
        self.assertEqual((report["format"], report["outcome"]), ("cbus-pci-serial-probe-v1", "present"))
        with tempfile.TemporaryDirectory() as directory:
            process = subprocess.run([sys.executable, "-m", "cbus_toolkit", "interface", "probe-serial",
                                      os.path.join(directory, "none"), "--timeout", "1"],
                                     text=True, capture_output=True)
        self.assertEqual(process.returncode, 1)
        self.assertEqual(json.loads(process.stdout)["outcome"], "not_found")


class SerialProbeUnitTests(unittest.TestCase):
    def test_bounds_are_validated_before_open(self):
        opened = []
        factory = lambda **kwargs: opened.append(kwargs)
        for kwargs in ({"baud": 115200}, {"timeout": 0.5}, {"timeout": 61}, {"baud": True}):
            with self.assertRaises(ValueError):
                probe_serial_interface("/dev/null", serial_factory=factory, **kwargs)
        with self.assertRaises(ValueError):
            probe_serial_interface("", serial_factory=factory)
        self.assertEqual(opened, [])

    def test_open_error_classification(self):
        cases = ((OSError(errno.EBUSY, "busy"), "busy"), (OSError(errno.EAGAIN, "locked"), "busy"),
                 (OSError(errno.EACCES, "denied"), "busy"), (OSError(errno.ENOENT, "gone"), "not_found"),
                 (OSError("could not open port 'COM9': FileNotFoundError(2, 'The system cannot find the file specified.')"), "not_found"),
                 (OSError("could not open port 'COM3': PermissionError(13, 'Access is denied.')"), "busy"),
                 (OSError(errno.EIO, "io"), "error"))
        for error, expected in cases:
            self.assertEqual(classify_open_error(error), expected, error)

    def test_write_failure_after_open_is_error_and_port_is_closed(self):
        class Port:
            closed = False
            def reset_input_buffer(self): pass
            def write(self, data): raise OSError(errno.EIO, "Input/output error")
            def close(self): self.closed = True
        port = Port()
        result = probe_serial_interface("fixture", timeout=1, serial_factory=lambda **kwargs: port)
        self.assertEqual(result["outcome"], "error")
        self.assertTrue(port.closed)

    @unittest.skipUnless(RUST_PCI.exists(), "repository Rust transport source required")
    def test_frames_match_the_rust_transport_init_sequence(self):
        wire = b"".join(RESET_FRAMES + SETUP_FRAMES).decode("ascii")
        self.assertEqual(wire, "~\r~\r~\r|\rA32100FF\rA32200FF\rA342000E\rA3300079\r")
        self.assertIn('let init = "' + wire.replace("\r", "\\r") + '";', RUST_PCI.read_text())


if __name__ == "__main__":
    unittest.main()
