"""Read native cached identities or explicitly refresh an already open network."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import re

from .addressing import UnitIdentity, _network_path
from .cgate import CGateError
from .native import _address


class SerialTransportError(RuntimeError):
    """An incomplete command stopped the scan; no later command was attempted."""


@dataclass(frozen=True)
class NativeSerialNumber:
    first: int
    second: int

    def __post_init__(self):
        if type(self.first) is not int or not 0 <= self.first <= 1048575:
            raise ValueError("Native serial first component must be in 0..1048575")
        if type(self.second) is not int or not 0 <= self.second <= 4095:
            raise ValueError("Native serial second component must be in 0..4095")

    @property
    def known(self):
        return (self.first, self.second) not in ((0, 0), (1048575, 4095))

    @property
    def canonical(self):
        return f"{self.first}.{self.second}"


def parse_native_serial(value):
    """Exact native decimal-dot bounds, with explicit failure instead of masking."""
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,16}\.[0-9]{1,16}", value):
        raise ValueError("Expected a native decimal-dot serial number")
    first, second = value.split(".")
    return NativeSerialNumber(int(first), int(second))


def _selection(units):
    if units is None: return None
    values = tuple(units)
    if not values: raise ValueError("Unit selection must not be empty")
    for value in values: _address(value)
    if len(set(values)) != len(values): raise ValueError("Unit selection contains duplicate addresses")
    return tuple(sorted(values))


def _addresses(value):
    if value == "": return ()
    if not re.fullmatch(r"[0-9]{1,3}(?:\s*,\s*[0-9]{1,3})*", value):
        raise ValueError("Unexpected native unit address list")
    return _selection(int(n.strip()) for n in value.split(","))


@dataclass(frozen=True)
class SerialRecord:
    address: int
    unit_type: str | None
    firmware: str | None
    serial: str | None
    state: str | None
    presence: str
    status: str
    errors: tuple[str, ...] = ()

    @property
    def identity(self):
        if self.errors or self.state != "ok" or self.presence not in ("cached", "single") or not self.unit_type:
            return None
        try:
            parsed = parse_native_serial(self.serial)
            serial = parsed.canonical if parsed.known else ""
        except ValueError:
            serial = ""
        return UnitIdentity(self.address, self.unit_type, serial)

    def as_dict(self):
        identity = self.identity
        return {"address": self.address, "unit_type": self.unit_type, "firmware": self.firmware,
                "serial": self.serial, "state": self.state, "presence": self.presence,
                "status": self.status, "errors": list(self.errors),
                "identity": identity.as_dict() if identity else None}


@dataclass(frozen=True)
class SerialInventory:
    network: str
    mode: str
    requested: tuple[int, ...] | None
    records: tuple[SerialRecord, ...]
    errors: tuple[str, ...]
    refresh_completed: bool
    observed_at: str

    @property
    def identities(self):
        if self.mode == "refresh" and not self.refresh_completed: return ()
        return tuple(identity for record in self.records if (identity := record.identity) is not None)

    @property
    def complete(self):
        resolved = {"ok"}
        if self.mode == "refresh" and self.requested is None:
            # A wildcard CHECKUNIT row that conclusively reports no unit is a
            # resolved MMI candidate, not a missing identity. Explicitly
            # requested absent addresses remain incomplete for callers that
            # expected an identity at that address.
            resolved.add("absent")
        return not self.errors and all(record.status in resolved for record in self.records)

    def as_dict(self):
        return {"format": "cbus-native-serial-inventory-v1", "network": self.network, "mode": self.mode,
                "requested": list(self.requested) if self.requested is not None else None,
                "records": [record.as_dict() for record in self.records],
                "identities": [identity.as_dict() for identity in self.identities],
                "errors": list(self.errors), "complete": self.complete, "observed_at": self.observed_at,
                "refresh_completed": self.refresh_completed,
                "refresh_scope": "entire_network" if self.mode == "refresh" else "none",
                "mmi_coverage_verified": False,
                "database_updated": False, "physical_addresses_changed": False}


_CHECK_STATUS = {"Single unit detected": "single", "Duplicate units detected": "duplicate_address",
                 "No units detected": "absent", "Single unit with error detected": "single_error",
                 "One or more units detected": "uncertain", "One or more units with error detected": "multiple_error"}


class NativeSerials:
    def __init__(self, client):
        self.client = client

    def _command(self, command):
        try:
            return self.client.command(command)
        except CGateError:
            # A complete native error reply keeps the stream synchronized.
            raise
        except Exception as error:
            # CGateClient closes on incomplete/framing-invalid replies and does
            # not reconnect automatically. Stop here instead of attempting the
            # remaining getters against a connection known to be unusable.
            raise SerialTransportError("Serial scan stopped after an incomplete native command: " + str(error)) from error

    def _get(self, path, field):
        response = self._command("GET " + path + " " + field)
        if response.code != 300 or len(response.lines) != 1:
            raise RuntimeError("Expected one native cached property response for " + field)
        match = re.fullmatch(r"300[- ]([^:]+): ([^=]+)=(.*)", response.lines[0])
        if not match or match[1].upper() != path.upper() or match[2].lower() != field.lower():
            raise RuntimeError("Native cached property response does not match its requested path/field")
        return match[3]

    def _record(self, network, address, presence):
        if presence in ("absent", "duplicate_address", "uncertain", "multiple_error"):
            return SerialRecord(address, None, None, None, None, presence, presence)
        values, errors = {}, []
        for field in ("Address", "Type", "Version", "SerialNumber", "State"):
            try: values[field] = self._get(network + "/p/" + str(address), field)
            except SerialTransportError: raise
            except Exception as error: errors.append(field + ": " + str(error))
        if "Address" in values and (not values["Address"].isdecimal() or int(values["Address"]) != address):
            errors.append("Returned unit Address differs from its requested path")
        if values.get("Type"):
            try: UnitIdentity(address, values["Type"])
            except ValueError as error: errors.append("Type: " + str(error))
        elif "Type" in values: errors.append("Unit type is missing")
        if not values.get("Version") and "Version" in values: errors.append("Firmware version is missing")
        serial = values.get("SerialNumber")
        if errors: status = "read_error"
        elif presence == "single_error": status = "single_error"
        elif values.get("State") != "ok": status = "unit_not_ok"
        elif serial == "": status = "missing_serial"
        else:
            try:
                number = parse_native_serial(serial)
                status = "ok" if number.known else "missing_serial"
            except ValueError: status = "invalid_serial"
        return SerialRecord(address, values.get("Type"), values.get("Version"), serial, values.get("State"),
                            presence, status, tuple(errors))

    def _inventory(self, network, selection, mode, *, checks=None, errors=(), refresh_completed=False):
        errors = list(errors)
        list_known = True
        try: occupied = _addresses(self._get(network, "Units"))
        except SerialTransportError: raise
        except Exception as error:
            errors.append("Cached unit list: " + str(error))
            occupied = ()
            list_known = False
        selected = selection if selection is not None else tuple(sorted(set(occupied) | set(checks or {})))
        records = []
        for address in selected:
            presence = checks.get(address, "unchecked") if checks is not None else "cached"
            if mode == "cached" and list_known and address not in occupied:
                records.append(SerialRecord(address, None, None, None, None, "not_cached", "not_cached"))
            else:
                record = self._record(network, address, presence)
                if presence == "unchecked": record = replace(record, status="unchecked")
                records.append(record)
        serials = {}
        for record in records:
            if record.status != "ok": continue
            canonical = parse_native_serial(record.serial).canonical
            serials.setdefault(canonical, []).append(record.address)
        duplicate = {address for addresses in serials.values() if len(addresses) > 1 for address in addresses}
        records = tuple(replace(record, status="duplicate_serial") if record.address in duplicate else record for record in records)
        return SerialInventory(network, mode, selection, records, tuple(errors), refresh_completed,
                               datetime.now(timezone.utc).isoformat())

    def cached(self, network, units=None):
        """Read only existing model fields, even while the interface is closed."""
        network, _project = _network_path(network)
        return self._inventory(network, _selection(units), "cached")

    def refresh(self, network, units=None):
        """Refresh the whole network, then report/check the selected addresses.

        NET SYNC fast has network scope. Unit selection limits the returned
        inventory and the multiplicity check, not the identity-refresh scope.
        """
        network, _project = _network_path(network)
        selection = _selection(units)
        expected = {"InterfaceState": "running", "TargetInterfaceState": "running", "SyncState": "idle",
                    "AutoUnravel": "no", "AutoUpdate": "no"}
        for field, required in expected.items():
            actual = self._get(network, field)
            if actual != required:
                raise ValueError(f"Physical identity refresh requires {field}={required}; native value is {actual!r}")
        errors, checks = [], {}
        refreshed = False
        try:
            response = self._command("NET SYNC " + network + " fast")
            if response.code != 200 or any(re.match(r"[456][0-9]{2}[- ]", line) for line in response.lines):
                raise RuntimeError("Native identity refresh did not complete successfully")
            refreshed = True
        except SerialTransportError: raise
        except Exception as error:
            errors.append("Physical identity refresh: " + str(error))
        if refreshed:
            response = None
            try:
                query = "*" if selection is None else ",".join(map(str, selection))
                response = self._command("NET CHECKUNIT " + network + " " + query)
            except SerialTransportError: raise
            except CGateError as error:
                response = error.response  # Preserve successful rows before a later native failure.
                errors.append("Physical unit multiplicity check: " + str(error))
            except Exception as error:
                errors.append("Physical unit multiplicity check: " + str(error))
            if response is not None:
                for line in response.lines:
                    if line == "200 OK." or re.fullmatch(r"120[- ]Command still in progress, please wait\.", line): continue
                    match = re.fullmatch(r"120[- ](.+) at address: ([0-9]{1,3})", line)
                    if not match or match[1] not in _CHECK_STATUS:
                        errors.append("Unexpected native unit multiplicity response: " + line)
                        continue
                    address = int(match[2])
                    try: _address(address)
                    except ValueError:
                        errors.append("Native unit multiplicity address is outside 0..255")
                        continue
                    if address in checks or selection is not None and address not in selection:
                        errors.append("Duplicate or unrequested native unit multiplicity result")
                        # Duplicate replies cannot prove a single physical identity.
                        if address in checks: checks[address] = "uncertain"
                        continue
                    checks[address] = _CHECK_STATUS[match[1]]
                if selection is not None and set(checks) != set(selection):
                    errors.append("Native unit check omitted selected addresses")
        return self._inventory(network, selection, "refresh", checks=checks, errors=errors, refresh_completed=refreshed)
