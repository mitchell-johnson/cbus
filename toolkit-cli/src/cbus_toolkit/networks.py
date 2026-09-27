"""Native network lifecycle and commissioning operations, invoked explicitly."""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
import math
import re
import time

from .native import _address, _project, _token
from .programming import quote_value
from .serials import parse_native_serial


class LearnGrade(IntEnum):
    """The six learn-mode grades retained by C-Gate 3.4 build 2001."""

    INIT_RELAY = 1
    INIT_DIM = 2
    CANCEL = 128
    EXIT_RELAY = 129
    EXIT_DIM = 130
    EXIT_AREA = 131

    @property
    def label(self):
        return self.name.lower().replace("_", "-")

    @property
    def native_token(self):
        return str(self.value) if self.value < 128 else f"${self.value:02X}"


_LEARN_GRADES = {grade.label: grade for grade in LearnGrade}


def _native_byte_text(value, label):
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a byte or supported symbolic name")
    try:
        number = (int(value[1:], 16) if value.startswith("$")
                  else int(value, 16 if value.lower().startswith("0x") else 10))
    except ValueError as error:
        raise ValueError(f"{label} must be a byte or supported symbolic name") from error
    if not 0 <= number <= 255:
        raise ValueError(f"{label} must be in 0..255")
    return number


def parse_learn_grade(value):
    """Accept a typed name or exact native byte spelling for one known grade."""
    if isinstance(value, LearnGrade):
        return value
    if type(value) is int:
        number = value
    elif isinstance(value, str) and value.lower().replace("_", "-") in _LEARN_GRADES:
        return _LEARN_GRADES[value.lower().replace("_", "-")]
    else:
        number = _native_byte_text(value, "Learn grade")
    try:
        return LearnGrade(number)
    except ValueError as error:
        raise ValueError(
            "Learn grade must be init-relay, init-dim, cancel, exit-relay, "
            "exit-dim, exit-area, or its native value"
        ) from error


def parse_locate_mode(value):
    """Return OFF/ON or an explicit native byte as a numeric mode."""
    if type(value) is int:
        if 0 <= value <= 255:
            return value
        raise ValueError("Locate mode must be in 0..255")
    if isinstance(value, str):
        if value.upper() == "OFF":
            return 0
        if value.upper() == "ON":
            return 1
    return _native_byte_text(value, "Locate mode")


def _byte_value(value, label, *, maximum=255):
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError(f"{label} must be an integer in 0..{maximum}")
    return value


def direct_network_path(value):
    """Admit only the fully qualified direct-network shape retained by evidence."""
    value = _token(value, "network address")
    match = re.fullmatch(r"//([A-Za-z0-9_]{1,8})/([0-9]{1,3})", value)
    if match is None or int(match[2]) > 255:
        raise ValueError("Use a fully qualified network address such as //PROJECT/254")
    return f"//{match[1]}/{int(match[2])}"


def network_management_application_path(value):
    """Admit the evidenced Network Management application 208 path."""
    value = _token(value, "Network Management application")
    match = re.fullmatch(r"//([A-Za-z0-9_]{1,8})/([0-9]{1,3})/([0-9]{1,3})", value)
    if (match is None or int(match[2]) > 255 or int(match[3]) != 208):
        raise ValueError(
            "Use a fully qualified Network Management application such as //PROJECT/254/208"
        )
    return f"//{match[1]}/{int(match[2])}/208"


def _mode_name(mode):
    return "off" if mode == 0 else "on" if mode == 1 else "byte"


def _mode_token(mode):
    return "OFF" if mode == 0 else "ON" if mode == 1 else str(mode)


@dataclass(frozen=True)
class NetworkManagementReceipt:
    """C-Gate acceptance without an invented unit-action or persistence claim."""

    operation: str
    network: str
    carrier_application: int
    selector: str
    target: dict
    mode: int | None
    command: str
    response: object

    def as_dict(self):
        return {
            "format": "cbus-cgate-network-management-v1",
            "operation": self.operation,
            "network": self.network,
            "carrier_application": self.carrier_application,
            "selector": self.selector,
            "target": dict(self.target),
            "mode": (None if self.mode is None else {
                "value": self.mode,
                "name": _mode_name(self.mode),
            }),
            "native_command": self.command,
            "cgate_accepted": True,
            "interface_delivery_confirmed": True,
            "device_action_verified": False,
            "physical_state_readback": False,
            "persistence_verified": False,
            "automatic_replay": False,
            "response": self.response,
        }


def _units(addresses):
    if addresses is None:
        return "*"
    addresses = list(addresses)
    if not addresses:
        raise ValueError("Unit selection cannot be empty")
    return ",".join(_address(address) for address in addresses)


def _project_identity(value):
    """Validate the native eight-character project-identify repertoire."""
    if value is None or isinstance(value, bool):
        raise ValueError("project identity is required")
    value = str(value)
    try:
        input_units = len(value.encode("utf-16-le")) // 2
    except UnicodeEncodeError as error:
        raise ValueError("Project identity must be valid Unicode text") from error
    upper = value.upper()
    upper_units = len(upper.encode("utf-16-le")) // 2
    if (not value or input_units > 8 or upper_units > 8
            or any(character != " " and not 33 <= ord(character) <= 96
                   for character in upper)):
        raise ValueError("Project identity must be 1..8 characters in the native six-bit range")
    if any(character in ' "\\' for character in value):
        return quote_value(value)
    return value


class NativeNetworks:
    def __init__(self, client):
        self.client = client

    def list(self, project=None):
        return self.client.command("NET LIST_ALL" if project is None else f"NET LIST {_project(project)}")

    def state(self, address):
        response = self.client.command(f"GET {_token(address)} state")
        states = [match[1] for line in response.lines if (match := re.search(r"\bstate\s*=\s*(\S+)", line))]
        if len(states) != 1:
            raise RuntimeError("Expected exactly one network state; use a single network address")
        return states[0]

    def wait_ready(self, address, *, timeout=30.0, interval=0.1):
        """Wait for native network state=ok; never retry/open/sync the network."""
        if any(isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n) or n <= 0
               for n in (timeout, interval)):
            raise ValueError("Wait timeout and interval must be positive and finite")
        deadline = time.monotonic() + timeout
        while True:
            state = self.state(address)
            if state == "ok":
                return {"ready": True, "state": state}
            if state == "error":
                raise RuntimeError(f"Network is not ready: state={state}")
            if state in ("closed", "new"):
                # NET OPEN may return before background startup changes the
                # aggregate state. Its requested interface state distinguishes
                # an opening network from one intentionally left closed.
                reply = self.client.command(f"GET {_token(address)} TargetInterfaceState")
                targets = [match[1] for line in reply.lines
                           if (match := re.fullmatch(r"300[- ]\S+: TargetInterfaceState=(\S+)", line))]
                if len(targets) != 1 or targets[0] not in ("running", "closed"):
                    raise RuntimeError("Expected one native TargetInterfaceState of running or closed")
                if targets[0] == "closed":
                    raise RuntimeError(f"Network is not ready: state={state}, target interface is closed")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError(f"Network readiness timed out: state={state}; no operation was retried")
            time.sleep(min(interval, remaining))

    def open(self, address):
        return self.client.command(f"NET OPEN {_token(address)}")

    def close(self, address):
        return self.client.command(f"NET CLOSE {_token(address)}")

    def synchronize(self, address, *, fast=False, retries=None):
        command = f"NET SYNC {_token(address)}" + (" fast" if fast else "")
        if retries is not None:
            command += " " + _address(retries)
        return self.client.command(command)

    def sync_new(self, address, unit=None):
        return self.client.command(f"NET SYNCNEW {_token(address)}" + (" " + _address(unit) if unit is not None else ""))

    def discover(self, address):
        return self.client.command(f"NET PINGU {_token(address)}")

    def _network_management(self, *, operation, network, carrier_application,
                            selector, target, mode, command):
        response = self.client.command(command)
        if response.code != 200:
            raise RuntimeError(f"{operation} did not complete: {response.final}")
        return NetworkManagementReceipt(
            operation=operation.lower().replace(" ", "-"),
            network=network,
            carrier_application=carrier_application,
            selector=selector,
            target=target,
            mode=mode,
            command=command,
            response=response,
        )

    def learn(self, network, application, grade, group):
        """Send one evidenced NET LEARN grade and report interface delivery."""
        network = direct_network_path(network)
        application = _byte_value(application, "Learn application")
        group = _byte_value(group, "Learn group")
        grade = parse_learn_grade(grade)
        command = (
            f"NET LEARN {network} {application} {grade.native_token} {group}"
        )
        return self._network_management(
            operation="NET LEARN",
            network=network,
            carrier_application=application,
            selector="learn-grade",
            target={
                "grade": grade.label,
                "grade_value": grade.value,
                "group": group,
            },
            mode=None,
            command=command,
        )

    def _locate(self, application_path, selector, arguments, target, mode):
        application_path = network_management_application_path(application_path)
        mode = parse_locate_mode(mode)
        network = application_path.rsplit("/", 1)[0]
        command = " ".join((
            "NETWORK", "LOCATE", application_path, selector,
            *(str(argument) for argument in arguments), _mode_token(mode),
        ))
        return self._network_management(
            operation="NETWORK LOCATE",
            network=network,
            carrier_application=208,
            selector=selector.lower(),
            target=target,
            mode=mode,
            command=command,
        )

    def locate_unit(self, application_path, unit, mode):
        unit = _byte_value(unit, "Locate unit")
        return self._locate(
            application_path, "UNIT", (unit,), {"unit": unit}, mode,
        )

    def locate_application(self, application_path, application, mode):
        application = _byte_value(
            application, "Locate target application", maximum=254,
        )
        return self._locate(
            application_path, "APP", (application,),
            {"application": application}, mode,
        )

    def locate_group(self, application_path, application, group, mode):
        application = _byte_value(
            application, "Locate target application", maximum=254,
        )
        group = _byte_value(group, "Locate target group", maximum=254)
        return self._locate(
            application_path, "GROUP", (application, group),
            {"application": application, "group": group}, mode,
        )

    def locate_serial(self, application_path, manufacturer, serial, mode):
        manufacturer = _byte_value(manufacturer, "Locate manufacturer")
        serial = parse_native_serial(serial).canonical
        return self._locate(
            application_path, "SERIAL", (manufacturer, serial),
            {"manufacturer": manufacturer, "serial": serial}, mode,
        )

    def check_units(self, address, units=None):
        return self.client.command(f"NET CHECKUNIT {_token(address)} {_units(units)}")

    def unravel(self, address, *, units=None, match_database=False):
        command = f"NET {'UNRAVEL' if units is None else 'UNRAVELUNIT'} {_token(address)}"
        if units is not None:
            command += " " + _units(units)
        return self.client.command(command + (" matchdb" if match_database else ""))

    def clocks(self, address, target=None, *, recover=False):
        if not isinstance(recover, bool):
            raise ValueError("Clock recovery must be a boolean")
        if recover and target is not None:
            raise ValueError("Select clock recovery or a target count")
        command = f"NET CLOCKS {_token(address)}"
        if recover:
            command += " R"
        elif target is not None:
            if isinstance(target, bool) or not isinstance(target, int) or not 1 <= target <= 10:
                raise ValueError("Native clock target must be in 1..10")
            command += " " + str(target)
        return self.client.command(command)

    def tree(self, address, *, xml=False, details=False, sync=None):
        flags = tuple(sync or ())
        if any(flag not in ("withsync", "withpsync", "withqsync") for flag in flags):
            raise ValueError("Tree sync flags must be withsync, withpsync or withqsync")
        if flags and not (xml or details):
            raise ValueError("Tree sync flags require XML output")
        command = "TREEXMLDETAIL" if details else "TREEXML" if xml else "TREE"
        return self.client.command(f"{command} {_token(address)}" + (" " + " ".join(flags) if flags else ""))

    def rename(self, address, new_address, *, fix_references=True):
        return self.client.command(f"NET RENAME {_token(address)} {_address(new_address)}" +
                                   ("" if fix_references else " nofixrefs"))

    def set_project_identity(self, address, project):
        return self.client.command(
            f"NET SET_PROJECT_IDENTIFY {_token(address)} {_project_identity(project)}"
        )

    def calculate(self, address):
        address = _token(address)
        match = re.fullmatch(r"//([A-Za-z0-9_]{1,8})/([0-9]{1,3})", address)
        if match is None or int(match[2]) > 255:
            raise ValueError("Calculator requires a fully qualified network, e.g. //TEST/254")
        self.client.command("PROJECT USE " + match[1])
        response = self.client.command("CALCULATOR TEST " + address)
        result = {"response": response}
        fields = {"current_supply(mA)": "current_supply_ma", "current_consumption(mA)": "current_consumption_ma",
                  "impedance(ohms)": "impedance_ohms", "units_calculated": "units_calculated",
                  "units_not_calculated": "units_not_calculated"}
        for line in response.lines:
            if line[:4] not in ("134-", "134 "):
                raise RuntimeError("Unexpected native calculator response")
            value = line[4:]
            if value in ("result: OK", "result: FAILED"):
                result["passed"] = value == "result: OK"
            else:
                key, equals, number = value.partition("=")
                if key not in fields or not equals:
                    raise RuntimeError("Unexpected native calculator result field")
                result[fields[key]] = float(number) if key == "impedance(ohms)" else int(number)
        if set(result) != {"response", "passed", *fields.values()}:
            raise RuntimeError("Native calculator returned incomplete results")
        return result
