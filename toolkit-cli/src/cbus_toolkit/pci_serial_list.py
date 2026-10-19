"""Enumerate local serial ports and optionally probe each for an attached PCI.

Listing reads only the host's port metadata through pyserial's
``serial.tools.list_ports.comports()``; no port is opened. ``probe=True``
runs :func:`probe_serial_interface` once per listed port, sequentially and
without ``setup``, so the only bytes sent are that probe's reset, SMART/
CONNECT, local-address, IDENTIFY and RECALL frames. Each probe's exclusive open
is released before the next port is opened. Nothing is retried.

Per-port outcomes are a coarser view of the probe's own outcome, which is kept
in full under ``probe``:

* ``found``: the probe outcome was ``present``;
* ``no_response``: ``absent`` or ``timeout``;
* ``busy``: the exclusive open failed because the port is locked or in use;
* ``permission_denied``: the open failed with ``EACCES``/``EPERM``;
* ``error``: anything else (``malformed``, ``rejected``, ``not_found``,
  ``error``), with the probe outcome retained.

On Windows an in-use COM port also reports "Access is denied"; that text is
classified ``busy``, as the probe does, because the two cannot be told apart.
"""
from __future__ import annotations

import errno as errnos

from . import pci_serial_probe
from .pci_serial_probe import _open_errno, probe_serial_interface

FORMAT = "cbus-serial-port-list-v1"
OUTCOMES = ("found", "no_response", "busy", "permission_denied", "error")
_PERMISSION = {errnos.EACCES, errnos.EPERM}
_FROM_PROBE = {"present": "found", "absent": "no_response", "timeout": "no_response", "busy": "busy"}


def _default_comports():
    try:
        from serial.tools.list_ports import comports
    except ImportError as error:
        raise RuntimeError("Install cbus-toolkit-cli[serial] to list serial ports") from error
    return comports()


def _text(value):
    if value is None:
        return None
    value = str(value)
    return None if value in ("", "n/a") else value


def _usb_id(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 0xFFFF else None


def describe_port(info):
    """Metadata of one pyserial ``ListPortInfo`` (or any object with its attributes)."""
    vid, pid = _usb_id(getattr(info, "vid", None)), _usb_id(getattr(info, "pid", None))
    return {"device": str(info.device), "name": _text(getattr(info, "name", None)),
            "description": _text(getattr(info, "description", None)),
            "hwid": _text(getattr(info, "hwid", None)), "vid": vid, "pid": pid,
            "vid_pid": f"{vid:04X}:{pid:04X}" if vid is not None and pid is not None else None,
            "serial_number": _text(getattr(info, "serial_number", None)),
            "manufacturer": _text(getattr(info, "manufacturer", None)),
            "product": _text(getattr(info, "product", None)),
            "location": _text(getattr(info, "location", None))}


def _recording(factory):
    """Wrap a serial factory so the open exception, if any, can be inspected."""
    seen = []

    def open_port(**kwargs):
        try:
            return factory(**kwargs)
        except BaseException as error:
            seen.append(error)
            raise
    return open_port, seen


def classify(result, open_error=None):
    """Map one probe result (and its open exception) to a list outcome."""
    outcome = result["outcome"]
    if outcome == "busy" and open_error is not None:
        if _open_errno(open_error) in _PERMISSION:
            return "permission_denied"
    return _FROM_PROBE.get(outcome, "error")


def _probe_port(device, *, baud, timeout, serial_factory, probe):
    factory = serial_factory
    if factory is None:
        try:
            from serial import Serial
        except ImportError as error:
            raise RuntimeError("Install cbus-toolkit-cli[serial] for serial interface probes") from error
        factory = Serial
    factory, seen = _recording(factory)
    try:
        result = probe(device, baud=baud, timeout=timeout, setup=False, serial_factory=factory)
    except ValueError as error:  # an unusable device name from the host
        return "error", str(error), None
    outcome = classify(result, seen[0] if seen else None)
    return outcome, result.get("detail"), result


def list_serial_ports(*, probe=False, baud=9600, timeout=5.0, comports=None, serial_factory=None,
                      probe_function=None):
    """List host serial ports; with ``probe``, run the read-only PCI probe on each."""
    if probe:
        pci_serial_probe._validate("validation", baud, timeout)
    entries = sorted((describe_port(item) for item in (comports or _default_comports)()),
                     key=lambda entry: entry["device"])
    report = {"format": FORMAT, "probe_requested": bool(probe), "ports": entries,
              "port_count": len(entries), "configuration_writes": 0, "automatic_retries": 0}
    if not probe:
        return report
    report.update(baud=baud, timeout_seconds=timeout, probe_format=pci_serial_probe.FORMAT)
    counts = dict.fromkeys(OUTCOMES, 0)
    for entry in entries:
        outcome, detail, result = _probe_port(entry["device"], baud=baud, timeout=timeout,
                                              serial_factory=serial_factory,
                                              probe=probe_function or probe_serial_interface)
        entry.update(outcome=outcome, detail=detail, probe=result,
                     identity=(result or {}).get("identity") if outcome == "found" else None)
        counts[outcome] += 1
    report["outcome_counts"] = counts
    return report


def render_text(report):
    """Human-readable form; escaped to ASCII like the CLI's JSON output."""
    ports = report["ports"]
    if not ports:
        lines = ["No serial ports found."]
    else:
        lines = []
        for entry in ports:
            head = entry["device"]
            if report["probe_requested"]:
                head += "  " + entry["outcome"]
                identity = entry.get("identity") or {}
                if identity:
                    head += " (" + ", ".join(f"{key}={identity[key]}" for key in
                                             ("unit_type", "firmware_version", "local_unit")
                                             if identity.get(key) is not None) + ")"
                elif entry.get("detail"):
                    head += ": " + entry["detail"]
            lines.append(head)
            for key in ("description", "hwid", "vid_pid", "serial_number", "manufacturer", "product",
                        "location"):
                if entry.get(key) is not None:
                    lines.append(f"  {key}: {entry[key]}")
    if report["probe_requested"]:
        counts = report["outcome_counts"]
        lines.append(f"{report['port_count']} port(s) probed at {report['baud']} baud: "
                     + ", ".join(f"{name}={counts[name]}" for name in OUTCOMES))
    return "\n".join(lines).encode("ascii", "backslashreplace").decode("ascii")


__all__ = ["FORMAT", "OUTCOMES", "classify", "describe_port", "list_serial_ports", "render_text"]
