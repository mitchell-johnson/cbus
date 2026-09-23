"""Native network lifecycle and commissioning operations, invoked explicitly."""
from __future__ import annotations

import math
import re
import time

from .native import _address, _project, _token


def _units(addresses):
    if addresses is None:
        return "*"
    addresses = list(addresses)
    if not addresses:
        raise ValueError("Unit selection cannot be empty")
    return ",".join(_address(address) for address in addresses)


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
        return self.client.command(f"NET SET_PROJECT_IDENTIFY {_token(address)} {_project(project)}")

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
