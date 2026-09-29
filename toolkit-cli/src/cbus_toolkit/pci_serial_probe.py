"""Bounded probe and explicit option setup for a PCI on a local serial port.

Every frame comes from an existing transport; nothing here is new protocol:

* reset: three ``~\\r`` then the ``|\\r`` SMART/CONNECT shortcut, each after
  the 100 ms ``INIT_SEND_DELAY`` of cmqttd's ``PciClient::pci_reset``
  (``rust/cbus-transport/src/pci.rs``, pinned by ``init_sequence_bytes``);
* local address: BASIC ``@1A2001`` from ``PCIClient._discover_local_unit``;
* identity: IDENTIFY attributes 1 (type) and 2 (firmware) to that address;
* options: RECALL parameters 0x30 and 0x42 (one byte each, 0x42 as in
  ``pci_local_options``) and the two application-address bytes at 0x21;
* ``setup`` only: the four basic-mode device-management frames that
  ``pci_reset`` sends without confirmation, then the same RECALL readback
  with command checksums because option 0x79 enables SRCHK.

Without ``setup`` no device-management (A3) frame is sent. Reset and SMART/
CONNECT change only the volatile session mode every cmqttd connection already
establishes. Nothing is retried. Bare replies are attributed only to the PCI
attached to the explicitly selected port.
"""
from __future__ import annotations

import errno as errnos
import math
import time

from .pci import PCIClient, PCIRejected, ProtocolError

FORMAT = "cbus-pci-serial-probe-v1"
PCI_BAUD_RATES = (9600, 4800, 2400, 1200, 600, 300)
INIT_SEND_DELAY = 0.1
RESET_SETTLE = 0.2
RESET_FRAMES = (b"~\r", b"~\r", b"~\r", b"|\r")
# (parameter, value) in pci_reset order; the wire form is A3 PP 00 VV.
SETUP_OPTIONS = ((0x21, 0xFF), (0x22, 0xFF), (0x42, 0x0E), (0x30, 0x79))
SETUP_FRAMES = tuple(b"A3%02X00%02X\r" % item for item in SETUP_OPTIONS)
OUTCOMES = ("present", "absent", "timeout", "busy", "malformed", "not_found", "rejected", "error")
_REPERTOIRE = frozenset(range(0x20, 0x7F)) | {0x0A, 0x0D, 0x11, 0x13}
_CAPTURE_LIMIT = 65536
_BUSY = {errnos.EBUSY, errnos.EACCES, errnos.EPERM, errnos.EAGAIN, errnos.EWOULDBLOCK}
_MISSING = {errnos.ENOENT, errnos.ENODEV, errnos.ENXIO, errnos.ENOTTY}


class _Deadline(Exception):
    """The probe's own wall-clock budget elapsed."""


def _open_errno(error):
    """pyserial wraps termios failures without ``errno``; use their context."""
    for item in (error, error.__cause__, error.__context__):
        number = getattr(item, "errno", None)
        if number is None and item is not None and item.args and isinstance(item.args[0], int):
            number = item.args[0]
        if isinstance(number, int):
            return number
    return None


def classify_open_error(error):
    number = _open_errno(error)
    text = str(error).lower()
    if number in _BUSY or "access is denied" in text or ("lock" in text and "exclusive" in text):
        return "busy"
    if number in _MISSING or "cannot find" in text or "filenotfounderror" in text:
        return "not_found"
    return "error"


class _Capture:
    def __init__(self):
        self.started = time.monotonic()
        self.sent, self.received, self.truncated = [], bytearray(), False

    def tx(self, phase, data):
        self.sent.append({"phase": phase, "offset_seconds": round(time.monotonic() - self.started, 3),
                          "hex": data.hex()})

    def rx(self, data):
        room = _CAPTURE_LIMIT - len(self.received)
        self.received.extend(data[:max(room, 0)])
        self.truncated |= len(data) > room

    def as_dict(self):
        return {"sent": self.sent, "received_hex": bytes(self.received).hex(),
                "received_bytes": len(self.received), "received_truncated": self.truncated}


class _SerialSocket:
    """The socket subset PCIClient uses, over an already-open pyserial port."""

    def __init__(self, port, capture, deadline, phase):
        self.port, self.capture, self.deadline, self.phase = port, capture, deadline, phase
        self._timeout = 0.0

    def settimeout(self, value):
        self._timeout = value

    def sendall(self, data):
        if time.monotonic() >= self.deadline:
            raise _Deadline()
        self.capture.tx(self.phase, data)
        if self.port.write(data) != len(data):
            raise OSError("Short serial write")
        self.port.flush()

    def recv(self, size):
        wait = min(self._timeout, self.deadline - time.monotonic())
        if wait <= 0:
            raise TimeoutError("timed out")
        self.port.timeout = wait
        data = self.port.read(1)
        if not data:
            raise TimeoutError("timed out")
        waiting = self.port.in_waiting
        if waiting:
            data += self.port.read(min(size - 1, waiting))
        self.capture.rx(data)
        if any(byte not in _REPERTOIRE for byte in data):
            raise ProtocolError("Received bytes outside the ASCII PCI repertoire")
        return data

    def close(self):
        pass


def _failure_kind(error):
    # pyserial's write timeout is an OSError subclass, not TimeoutError.
    if isinstance(error, (TimeoutError, _Deadline)) or type(error).__name__ == "SerialTimeoutException":
        return "timeout"
    if isinstance(error, PCIRejected):
        return "rejected"
    return "malformed" if isinstance(error, ProtocolError) else "error"


def _validate(port, baud, timeout):
    if not isinstance(port, str) or not port.strip() or any(ord(c) < 32 for c in port):
        raise ValueError("An explicit serial port is required")
    if isinstance(baud, bool) or baud not in PCI_BAUD_RATES:
        raise ValueError("baud must be one of " + ", ".join(map(str, PCI_BAUD_RATES)))
    if (isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout)
            or not 1 <= timeout <= 60):
        raise ValueError("timeout must be in 1..60 seconds")


def _reset(port, capture, deadline):
    """Transport reset frames, then collect the settle window's bytes."""
    port.reset_input_buffer()
    for frame in RESET_FRAMES:
        time.sleep(INIT_SEND_DELAY)
        if time.monotonic() >= deadline:
            raise _Deadline()
        capture.tx("reset", frame)
        port.write(frame)
        port.flush()
    received = bytearray()
    settle = time.monotonic() + RESET_SETTLE
    while (now := time.monotonic()) < min(settle, deadline):
        port.timeout = min(settle, deadline) - now
        chunk = port.read(max(1, port.in_waiting))
        received.extend(chunk)
    capture.rx(bytes(received))
    if any(byte not in _REPERTOIRE for byte in received):
        raise ProtocolError("Reset reply contains bytes outside the ASCII PCI repertoire")
    return bytes(received)


def _read_options(client):
    return {"interface_options_1": client.recall(None, 0x30, 1)[0],
            "interface_options_3": client.recall(None, 0x42, 1)[0],
            "application_addresses_hex": client.recall(None, 0x21, 2).hex().upper()}


def probe_serial_interface(port, *, baud=9600, timeout=5.0, setup=False, serial_factory=None):
    """Open ``port`` exclusively, classify it, and optionally apply options."""
    _validate(port, baud, timeout)
    result = {"format": FORMAT, "port": port, "baud": baud, "timeout_seconds": timeout,
              "exclusive_open": True, "outcome": None, "detail": None, "identity": None,
              "options": None, "setup": {"requested": bool(setup), "applied": False},
              "configuration_writes": 0, "automatic_retries": 0,
              "attribution": "attached_pci_on_explicit_port"}
    factory = serial_factory
    if factory is None:
        try:
            from serial import Serial
        except ImportError as error:
            raise RuntimeError("Install cbus-toolkit-cli[serial] for serial interface probes") from error
        factory = Serial
    capture = _Capture()
    try:
        stream = factory(port=port, baudrate=baud, bytesize=8, parity="N", stopbits=1,
                         xonxoff=False, rtscts=False, dsrdtr=False, timeout=0,
                         write_timeout=timeout, exclusive=True)
    except (OSError, ValueError) as error:
        result.update(outcome=classify_open_error(error), detail=str(error))
        result["wire"] = capture.as_dict()
        return result
    stage, identity, options, client = "reset", {}, {}, None
    try:
        deadline = time.monotonic() + timeout
        _reset(stream, capture, deadline)
        stage = "identify"
        client = PCIClient("serial", timeout=timeout)
        client.socket = _SerialSocket(stream, capture, deadline, "identify")
        client.timeout = max(deadline - time.monotonic(), 1e-3)
        identity["unit_type"] = client.identify(None, 1).decode("ascii", "replace").strip()
        identity["local_unit"] = client.local_unit
        identity["firmware_version"] = client.identify(None, 2).decode("ascii", "replace").strip()
        stage = "options"
        options.update(_read_options(client))
        result.update(outcome="present", detail="PCI identity and options read back")
        if setup:
            stage = "setup"
            deadline = time.monotonic() + timeout
            for frame in SETUP_FRAMES:
                time.sleep(INIT_SEND_DELAY)
                if time.monotonic() >= deadline:
                    raise _Deadline()
                capture.tx("setup", frame)
                stream.write(frame)
                stream.flush()
                result["configuration_writes"] += 1
            result["setup"]["applied"] = True
            time.sleep(RESET_SETTLE)
            client.socket = _SerialSocket(stream, capture, deadline, "setup_readback")
            client.command_checksum = True
            client.timeout = max(deadline - time.monotonic(), 1e-3)
            readback = _read_options(client)
            values = dict(SETUP_OPTIONS)
            expected = {"interface_options_1": values[0x30], "interface_options_3": values[0x42],
                        "application_addresses_hex": bytes((values[0x21], values[0x22])).hex().upper()}
            result["setup"].update(expected=expected, readback=readback,
                                   verified=readback == expected,
                                   mismatches=sorted(k for k in expected if readback[k] != expected[k]))
    except (OSError, ProtocolError, _Deadline) as error:
        kind = _failure_kind(error)
        if result["outcome"] == "present":
            result["setup"]["error"] = f"{kind}: {error}" if str(error) else kind
        elif kind == "timeout":
            received = len(capture.received)
            result.update(outcome="timeout" if received else "absent",
                          detail=(f"No complete reply during {stage}" if received
                                  else "Port opened but no bytes were received"))
        else:
            result.update(outcome=kind, detail=f"{stage}: {error}")
    finally:
        try:
            stream.close()
        except OSError as error:
            result["close_error"] = str(error)
    if client is not None and client.local_unit is not None:
        identity.setdefault("local_unit", client.local_unit)
    result["identity"] = identity or None
    result["options"] = options or None
    result["wire"] = capture.as_dict()
    if setup and result["outcome"] != "present":
        result["setup"]["error"] = "not attempted: probe outcome was not present"
    return result


def exit_status(result):
    if result["outcome"] != "present":
        return 1
    setup = result["setup"]
    return 0 if not setup["requested"] or setup.get("verified") else 1


__all__ = ["FORMAT", "OUTCOMES", "PCI_BAUD_RATES", "RESET_FRAMES", "SETUP_FRAMES",
           "classify_open_error", "exit_status", "probe_serial_interface"]
