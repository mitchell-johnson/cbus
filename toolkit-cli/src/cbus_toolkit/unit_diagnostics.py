"""Per-unit network diagnostics recovered from the Toolkit Diagnostics dialog.

Toolkit 1.18.0.2754 ``TfrmPingUnits`` (help topics 20132/20136) first marks
every database unit ``Not Found``, issues ``NET PINGU`` and marks each listed
address ``Unit Present``. Listed addresses without a database unit are
``Rescan Network`` rows. It then optionally reads, in three separate passes
over the database units: ``GET <unit> NetVoltage``; ``DO <unit> Psync`` then
``GET <unit> BurdenActive``; and a PP session reading ``ClockGenEnable``.
KEYGL5 and SENTEMP4 are never asked for burden or clock status. Values of
units that PINGU did not report are displayed as ``Unknown``.

This module preserves that order and those display rules. It deliberately
sends no per-unit request to a unit that PINGU did not report: the original
still issues them, but its displayed result for such a unit is ``Unknown``
regardless of the reply. A per-unit command failure is also ``unknown``;
it is never a zero voltage or a disabled burden/clock. No command is retried.
Transport and framing failures stop further I/O.

Voltage is C-Gate's cached ``NetVoltage``: the unit-reported IDENTIFY4 byte
at the last synchronisation, formatted by C-Gate. It is not an independent
electrical measurement and the Toolkit reads it before the burden pass's
Psync, so it can predate that refresh.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
import re

from .cgate import CGateError
from .networks import direct_network_path
from .programming import Programmer, ProgrammingCommandError


MAX_DATABASE_UNITS = 256
# Toolkit TCBusUnitCGateAgent.LoadBurden/LoadClockGenEnabled compare the
# unit type with these exact, case-sensitive strings and skip the request.
TYPE_RULE_UNITS = ("KEYGL5", "SENTEMP4")
FIELDS = ("voltage", "burden", "clock")
_PINGU = re.compile(r"302-Units=([0-9]{1,3}(?:, [0-9]{1,3})*)?")
_NUMBER = re.compile(r"-?[0-9]{1,6}(?:\.[0-9]{1,6})?")


class DiagnosticsError(RuntimeError):
    """The dialog-equivalent run could not start or was stopped by I/O."""

    def __init__(self, message, commands=()):
        self.commands = tuple(commands)
        super().__init__(message)


@dataclass
class UnitDiagnostic:
    address: int
    unit_type: str | None
    found: str
    voltage: float | str | None = None
    voltage_text: str | None = None
    burden: str | None = None
    burden_basis: str | None = None
    clock: str | None = None
    clock_basis: str | None = None
    errors: list = field(default_factory=list)

    def known(self, name):
        value = getattr(self, name)
        return value is None or value != "unknown"

    def as_dict(self):
        return {
            "address": self.address,
            "unit_type": self.unit_type,
            "found": self.found,
            "voltage": self.voltage,
            "voltage_text": self.voltage_text,
            "burden": self.burden,
            "burden_basis": self.burden_basis,
            "clock": self.clock,
            "clock_basis": self.clock_basis,
            "errors": list(self.errors),
        }


class _Recorder:
    """Record each command and its complete reply for the evidence trail."""

    def __init__(self, client):
        self._client = client
        self.commands = []

    def command(self, text):
        try:
            response = self._client.command(text)
        except CGateError as error:
            self.commands.append({"command": text, "lines": list(error.response.lines)})
            raise
        except Exception as error:
            self.commands.append({"command": text, "lines": None, "transport_error": type(error).__name__})
            raise
        self.commands.append({"command": text, "lines": list(response.lines)})
        return response

    def __getattr__(self, name):
        return getattr(self._client, name)


def _database_units(response, network):
    from .addressing import _container
    from .toolkit_database_csv_native import _children, native_xml_reply_text

    root = _container(native_xml_reply_text(response, completion_codes=(200, 344)),
                      "Network").documentElement
    number = int(network.rsplit("/", 1)[1])

    def text(node, name):
        rows = _children(node, name)
        if len(rows) > 1:
            raise DiagnosticsError(f"Database unit has duplicate {name} fields")
        if not rows:
            return None
        value = "".join(child.data for child in rows[0].childNodes
                        if child.nodeType in (child.TEXT_NODE, child.CDATA_SECTION_NODE))
        return value if value else None

    if text(root, "Address") != str(number):
        raise DiagnosticsError("C-Gate network XML does not match the requested network")
    units = {}
    for unit in _children(root, "Unit"):
        address = text(unit, "Address")
        if address is None or re.fullmatch(r"0|[1-9][0-9]{0,2}", address) is None or int(address) > 255:
            raise DiagnosticsError("Database unit address must be a canonical decimal byte")
        if int(address) in units:
            raise DiagnosticsError("Database contains duplicate unit addresses")
        units[int(address)] = text(unit, "UnitType")
        if len(units) > MAX_DATABASE_UNITS:
            raise DiagnosticsError("Database unit count exceeds the network address space")
    return units


def _pingu(response):
    lines = list(response.lines)
    if response.code != 200 or len(lines) != 2 or lines[1] != "200 OK.":
        raise DiagnosticsError("Expected an exact successful NET PINGU reply")
    match = _PINGU.fullmatch(lines[0])
    if match is None:
        raise DiagnosticsError("NET PINGU did not return an exact unit address list")
    tokens = match[1].split(", ") if match[1] else []
    addresses = [int(token) for token in tokens]
    if (any(value > 255 or token != str(value) for token, value in zip(tokens, addresses))
            or addresses != sorted(set(addresses))):
        raise DiagnosticsError("NET PINGU addresses must be unique, ordered decimal values in 0..255")
    return addresses


def _property(response, path, name):
    lines = list(response.lines)
    prefix = f"300 {path}: {name}="
    if response.code != 300 or len(lines) != 1 or not lines[0].startswith(prefix):
        return None
    return lines[0][len(prefix):]


def _failure(step, error):
    if isinstance(error, CGateError):
        return {"step": step, "status": error.response.code, "reply": list(error.response.lines)}
    if isinstance(error, ProgrammingCommandError):
        reply = getattr(error, "reply", None)
        return {"step": step, "status": getattr(reply, "code", None),
                "reply": list(getattr(reply, "lines", ()) or ())}
    return {"step": step, "status": None, "reply": [str(error)]}


class NetworkDiagnostics:
    """Run the recovered Diagnostics dialog sequence against one network."""

    def __init__(self, client):
        self.client = client

    def diagnose(self, network, *, units=None, voltage=True, burden=True, clock=True):
        network = direct_network_path(network)
        if any(not isinstance(flag, bool) for flag in (voltage, burden, clock)):
            raise ValueError("Diagnostic field selections must be booleans")
        selected = None
        if units is not None:
            selected = list(units)
            if not selected:
                raise ValueError("Unit selection cannot be empty")
            if any(isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 255
                   for value in selected):
                raise ValueError("Unit addresses must be integers in 0..255")
            if len(set(selected)) != len(selected):
                raise ValueError("Unit selection contains duplicate addresses")
        recorder = _Recorder(self.client)
        try:
            return self._diagnose(recorder, network, selected, {"voltage": voltage, "burden": burden, "clock": clock})
        except DiagnosticsError as error:
            raise DiagnosticsError(str(error), recorder.commands) from error
        except CGateError as error:
            raise DiagnosticsError(f"C-Gate stopped the diagnostics run: {error.response.final}",
                                   recorder.commands) from error

    def _diagnose(self, client, network, selected, requested):
        database = _database_units(client.command("DBGETXML " + network), network)
        if selected is not None:
            missing = sorted(set(selected) - set(database))
            if missing:
                raise DiagnosticsError("Selected units are not in the network database: "
                                       + ", ".join(map(str, missing)))
        addresses = sorted(database if selected is None else selected)
        present = set(_pingu(client.command("NET PINGU " + network)))
        rows = [UnitDiagnostic(address, database[address],
                               "present" if address in present else "not-found")
                for address in addresses]
        for row in rows:
            if row.found != "present":
                for name in FIELDS:
                    if requested[name]:
                        setattr(row, name, "unknown")
        live = [row for row in rows if row.found == "present"]
        if requested["voltage"]:
            for row in live:
                self._voltage(client, network, row)
        if requested["burden"]:
            for row in live:
                self._burden(client, network, row)
        if requested["clock"]:
            for row in live:
                self._clock(client, network, row)
        rescan = [UnitDiagnostic(address, None, "rescan-network",
                                 **{name: "unknown" for name in FIELDS if requested[name]})
                  for address in sorted(present - set(database))]
        return DiagnosticReport(network, len(database), requested, sorted(present), rows, rescan,
                                client.commands)

    @staticmethod
    def _path(network, address):
        return f"{network}/p/{address}"

    def _voltage(self, client, network, row):
        path = self._path(network, row.address)
        try:
            response = client.command(f"GET {path} NetVoltage")
        except CGateError as error:
            row.voltage = "unknown"
            row.errors.append(_failure("voltage", error))
            return
        text = _property(response, path, "NetVoltage")
        value = float(text) if text is not None and _NUMBER.fullmatch(text) else None
        row.voltage_text = text
        if value is None or not math.isfinite(value) or value <= 0:
            # Toolkit clamps a negative value to 0 and displays 0 as unknown.
            row.voltage = "unknown"
            row.errors.append({"step": "voltage", "status": response.code, "reply": list(response.lines)})
        else:
            row.voltage = value

    def _burden(self, client, network, row):
        if row.unit_type in TYPE_RULE_UNITS:
            row.burden, row.burden_basis = "not-enabled", "toolkit-unit-type-rule"
            return
        path = self._path(network, row.address)
        try:
            client.command(f"DO {path} Psync")
            response = client.command(f"GET {path} BurdenActive")
        except CGateError as error:
            # The original skips its BurdenActive read after a Psync failure.
            row.burden = "unknown"
            row.errors.append(_failure("burden", error))
            return
        value = _property(response, path, "BurdenActive")
        if value in ("yes", "no"):
            row.burden = "enabled" if value == "yes" else "not-enabled"
            row.burden_basis = "native-burdenactive"
        else:
            row.burden = "unknown"
            row.errors.append({"step": "burden", "status": response.code, "reply": list(response.lines)})

    def _clock(self, client, network, row):
        if row.unit_type in TYPE_RULE_UNITS:
            row.clock, row.clock_basis = "not-enabled", "toolkit-unit-type-rule"
            return
        path = self._path(network, row.address)
        stage = "load"
        try:
            with Programmer(client).session(network) as session:
                session.load(path)
                stage = "get"
                response = session.get("ClockGenEnable")
        except (CGateError, ProgrammingCommandError) as error:
            reply = error.response if isinstance(error, CGateError) else getattr(error, "reply", None)
            if (stage == "get" and getattr(reply, "code", None) == 460
                    and list(getattr(reply, "lines", ()))[-1:] == ["460 No such parameter: ClockGenEnable"]):
                row.clock, row.clock_basis = "not-enabled", "no-clockgenenable-parameter"
                return
            row.clock = "unknown"
            row.errors.append(_failure("clock-" + stage, error))
            return
        lines = [line for line in response.lines if not line.startswith("120-")]
        if lines in (["315 ClockGenEnable=1"], ["315 ClockGenEnable=0"]):
            row.clock = "enabled" if lines[0].endswith("1") else "not-enabled"
            row.clock_basis = "native-pp-clockgenenable"
        else:
            row.clock = "unknown"
            row.errors.append({"step": "clock-get", "status": response.code, "reply": list(response.lines)})


@dataclass
class DiagnosticReport:
    network: str
    database_unit_count: int
    requested: dict
    pingu_addresses: list
    units: list
    rescan: list
    commands: list

    @property
    def all_units_not_found(self):
        """The original's AllUnitsFailed error condition over reported rows."""
        return not self.rescan and all(row.found == "not-found" for row in self.units)

    @property
    def complete(self):
        return (not self.rescan and bool(self.units)
                and all(row.found == "present" and all(row.known(name) for name in FIELDS)
                        for row in self.units))

    def as_dict(self):
        return {
            "format": "cbus-network-unit-diagnostics-v1",
            "network": self.network,
            "requested": dict(self.requested),
            "database_unit_count": self.database_unit_count,
            "pingu_addresses": list(self.pingu_addresses),
            "units": [row.as_dict() for row in self.units],
            "rescan_network": [row.as_dict() for row in self.rescan],
            "all_units_not_found": self.all_units_not_found,
            "complete": self.complete,
            "absent_units_queried": False,
            "voltage_source": "cgate-cached-netvoltage",
            "electrical_measurement_verified": False,
            "device_verified": False,
            "commands": list(self.commands),
        }
