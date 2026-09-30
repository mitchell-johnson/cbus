"""Owned synthetic peers and lossless subprocess evidence for commissioning.

This is acceptance infrastructure, not C-Bus firmware or a transport backend.
The routed peer independently constructs literal Reply Network vectors, accepts
one explicitly selected bridge, and delegates only direct read/address effects
to the existing read-only two-node fixture. It never enables generic writes.
"""
from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time

from cbus_toolkit.simulator import PCISimulator
from tests.test_pci_selected_serial_routed import (
    identify4, mmi, receipt, routed_co, routed_identify_request, routed_mmi_request,
)
from tests.test_simulator_duplicate_addressing import A, B, CO_A, fixture


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def artifact(path):
    path = Path(path)
    return {"path": str(path.resolve()), "sha256": digest(path), "bytes": path.stat().st_size}


class CLIRecorder:
    """Retain actual argv and exact output bytes, including failed commands."""

    def __init__(self, interpreter, directory, *, cwd, environment=None):
        self.interpreter = str(interpreter)
        self.directory = Path(directory)
        self.directory.mkdir(exist_ok=False)
        self.cwd = Path(cwd)
        self.environment = dict(os.environ if environment is None else environment)
        self.commands = []

    def invoke(self, arguments, *, expected=0, label=None, timeout=90):
        argv = [self.interpreter, "-m", "cbus_toolkit", *map(str, arguments)]
        sequence = len(self.commands)
        row = {"sequence": sequence, "label": label, "argv": argv,
               "cwd": str(self.cwd.resolve()), "execution": "public_cli_subprocess"}
        self.commands.append(row)
        try:
            result = subprocess.run(argv, cwd=self.cwd, env=self.environment,
                                    capture_output=True, timeout=timeout)
            stdout, stderr = result.stdout, result.stderr
            row["exit_status"] = result.returncode
        except subprocess.TimeoutExpired as error:
            stdout, stderr = error.stdout or b"", error.stderr or b""
            row["exit_status"] = None
            row["timeout_seconds"] = timeout
        for name, data in (("stdout", stdout), ("stderr", stderr)):
            path = self.directory / f"{sequence:03d}-{name}.bin"
            path.write_bytes(data)
            row[name] = artifact(path)
            row[name + "_hex"] = data.hex()
            row[name + "_utf8"] = data.decode("utf-8", errors="replace")
        row["expected_exit_status"] = expected
        (self.directory / f"{sequence:03d}-command.json").write_text(json.dumps(row, indent=2) + "\n")
        if row["exit_status"] != expected:
            raise AssertionError(f"CLI {sequence} ({label}) returned {row['exit_status']}, expected {expected}: "
                                 f"{row['stderr_utf8']} {row['stdout_utf8']}")
        try:
            return json.loads(stdout or stderr)
        except (ValueError, UnicodeError):
            return (stdout or stderr).decode("utf-8", errors="replace")


def commissioning_fixture(profile, work):
    """Two serials initially share255; routed target is one bridge252 from254."""
    sim = fixture(state_path=Path(work) / "pci-state.json", wire_log_path=Path(work) / "pci-wire.jsonl")
    original = sim._command
    route = [252] if profile == "routed" else []
    sim.acceptance_corrupt_receipt = False
    sim.acceptance_route = route

    def command(line, context):
        if route:
            if line + b"\r" == routed_mmi_request(route):
                states = {node.address: node.mmi_state for node in sim.nodes.values()}
                return b"g." + mmi(route, states), None
            for address in (6, 255):
                if line + b"\r" == routed_identify_request(route, address):
                    replies = b"".join(identify4(route, address, serial) for serial in (A, B)
                                       if sim.nodes[serial].address == address)
                    return b"g." + replies, None
            if line + b"\r" == routed_co(route, A, 6):
                # Only the exact independent literal route252/serialA/target6
                # is admitted. The existing fixture models its bus-only move.
                direct, reason = original(CO_A.rstrip(b"\r"), {"header": None})
                if reason or not direct.startswith(b"g."):
                    return direct, reason
                response = b"g." + receipt(route, 6, A)
                if sim.acceptance_corrupt_receipt:
                    response += b"XX\r\n"
                return response, None
            if line.startswith((b"\\03", b"\\46FC09")):
                return b"g#", "Outside explicit acceptance route scope"
        response, reason = original(line, context)
        if not route and line == CO_A.rstrip(b"\r") and sim.acceptance_corrupt_receipt:
            response += b"XX\r\n"
        return response, reason

    sim._command = command
    return sim


def port_closed(endpoint):
    try:
        with socket.create_connection(endpoint, timeout=.2):
            return False
    except OSError:
        return True


@contextmanager
def owned_cmqttd(binary, directory, record):
    """Start one retained, owned cmqttd state with separate PCI and fake broker."""
    work = Path(directory)
    work.mkdir(exist_ok=False)
    project = work / "bridge-project.xml"
    project.write_text("<Installation><Project><TagName>BRIDGE_TEST</TagName><Network>"
                       "<Address>254</Address><TagName>Loopback</TagName>"
                       "</Network></Project></Installation>")

    class InitializedPCI(PCISimulator):
        def _command(self, line, context):
            if line in (b"~", b"A32100FF", b"A32200FF", b"A342000E", b"A3300079"):
                return b"", None
            return super()._command(line, context)

    with socket.socket() as broker, InitializedPCI(profile="captured", command_checksum=True,
                  wire_log_path=work / "daemon-pci-wire.jsonl").running() as pci:
        broker.bind(("127.0.0.1", 0)); broker.listen(1)
        log_path = work / "cmqttd.stderr.log"
        output_path = work / "cmqttd.stdout.log"
        state = work / "durable-state.json"
        argv = [str(binary), "--tcp", f"{pci[0]}:{pci[1]}", "--broker-address", "127.0.0.1",
                "--broker-port", str(broker.getsockname()[1]), "--broker-disable-tls",
                "--timesync", "0", "--status-resync", "0", "--project-file", str(project),
                "--cgate-bind", "127.0.0.1:0", "--cgate-state", str(state)]
        record.update(argv=argv, binary=artifact(binary), pci_endpoint=list(pci),
                      broker_endpoint=list(broker.getsockname()), state_path=str(state),
                      process_cleanup_verified=False)
        with log_path.open("wb") as log, output_path.open("wb") as output:
            process = subprocess.Popen(argv, stdout=output, stderr=log)
            record["pid"] = process.pid
            endpoint = None
            try:
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    match = re.search(r"C-Gate service listening on 127\.0\.0\.1:([0-9]+)",
                                      log_path.read_text(errors="replace"))
                    if match:
                        endpoint = ("127.0.0.1", int(match[1]))
                        record["cgate_endpoint"] = list(endpoint)
                        yield endpoint[1]
                        break
                    if process.poll() is not None:
                        raise RuntimeError("Owned cmqttd exited before listener announcement")
                    time.sleep(.02)
                else:
                    raise TimeoutError("Owned cmqttd listener announcement timed out")
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait(timeout=5)
                record.update(exit_status=process.returncode, process_waited=True,
                              cgate_port_closed=endpoint is not None and port_closed(endpoint),
                              process_cleanup_verified=process.poll() is not None)
        for name, path in (("stderr", log_path), ("stdout", output_path), ("durable_state", state)):
            if path.is_file():
                record[name] = artifact(path)
    record["pci_port_closed"] = port_closed(pci)
    record["broker_socket_closed"] = broker.fileno() == -1
