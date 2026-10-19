"""Public numeric Application DBCOPYSAFE journeys on two owned Rust backends."""
from __future__ import annotations

from contextlib import contextmanager, ExitStack
import json
import os
from pathlib import Path
import re
import select
import shutil
import socket
import subprocess
import sys
import threading
import time
import uuid
from xml.etree import ElementTree as ET

import pytest

from cbus_toolkit.cgate import CGateClient
from cbus_toolkit.native import NativeDatabase
from cbus_toolkit.programming import xml_text
from cbus_toolkit.simulator import PCISimulator


STARTUP = [b"~\r"] * 3 + [b"|\r", b"A32100FF\r", b"A32200FF\r",
                           b"A342000E\r", b"A3300079\r"]


class InitializedPCI(PCISimulator):
    def _command(self, line, context):
        if line in (b"~", b"A32100FF", b"A32200FF", b"A342000E", b"A3300079"):
            return b"", None
        return super()._command(line, context)


def port_closed(endpoint):
    with socket.socket() as peer:
        peer.settimeout(.2)
        return peer.connect_ex(endpoint) != 0


@contextmanager
def no_contact_trap():
    with socket.socket() as trap:
        trap.bind(("127.0.0.1", 0))
        trap.listen(1)
        endpoint = trap.getsockname()
        try:
            yield f"{endpoint[0]}:{endpoint[1]}"
        finally:
            assert not select.select([trap], [], [], .02)[0], "Closed graph contacted CNI"
    assert port_closed(endpoint)


@contextmanager
def owned_backend(kind, binary, work, *, state_path=None):
    """One direct child; no adopted process, listener, PCI or MQTT endpoint."""
    record = {"backend": kind, "process_cleanup": False}
    pci = broker_endpoint = endpoint = simulator = None
    listeners = []
    with ExitStack() as resources:
        if kind == "cmqttd":
            broker = resources.enter_context(socket.socket())
            broker.bind(("127.0.0.1", 0))
            broker.listen(1)
            broker_endpoint = broker.getsockname()
            simulator = InitializedPCI(profile="captured", command_checksum=True)
            pci = resources.enter_context(simulator.running())
            project = work / "bridge.xml"
            project.write_text(
                "<Installation><Project><TagName>BRIDGE</TagName><Network><Address>254</Address>"
                "<TagName>Loopback</TagName><Application><Address>48</Address>"
                "<TagName>Empty owned Lighting</TagName></Application></Network></Project></Installation>",
                encoding="utf-8",
            )
            project.chmod(0o600)
            argv = [str(binary), "--tcp", f"{pci[0]}:{pci[1]}", "--broker-address", "127.0.0.1",
                    "--broker-port", str(broker_endpoint[1]), "--broker-disable-tls",
                    "--timesync", "0", "--status-resync", "0", "--project-file", str(project),
                    "--cgate-bind", "127.0.0.1:0", "--cgate-state", str(state_path or work / "state.json")]
            pattern = r"C-Gate service listening on 127\.0\.0\.1:(\d+)"
        else:
            argv = [str(binary), "--bind", "127.0.0.1:0", "--native-project-archives"]
            pattern = r"cgate-mock listening on 127\.0\.0\.1:(\d+)"
        stdout_path, stderr_path = work / "stdout.log", work / "stderr.log"
        stdout = resources.enter_context(stdout_path.open("wb"))
        stderr = resources.enter_context(stderr_path.open("wb"))
        stdout_path.chmod(0o600)
        stderr_path.chmod(0o600)
        process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr)
        record.update(argv=argv, pid=process.pid)
        try:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                logs = stdout_path.read_text(errors="replace") + stderr_path.read_text(errors="replace")
                match = re.search(pattern, logs)
                if match:
                    endpoint = ("127.0.0.1", int(match[1]))
                    if kind == "cmqttd":
                        event = re.search(r"C-Gate event service listening on 127\.0\.0\.1:(\d+)", logs)
                        if event is None:
                            time.sleep(.02)
                            continue
                        listeners = [endpoint, ("127.0.0.1", int(event[1]))]
                    else:
                        listeners = [endpoint]
                    break
                assert process.poll() is None, logs
                time.sleep(.02)
            assert endpoint is not None, logs
            if simulator is not None:
                deadline = time.monotonic() + 15
                while len(simulator.wire_log) < len(STARTUP) and time.monotonic() < deadline:
                    assert process.poll() is None, "Owned daemon exited during PCI initialization"
                    time.sleep(.02)
                assert [(row["direction"], bytes.fromhex(row["hex"])) for row in simulator.wire_log] == [
                    ("rx", frame) for frame in STARTUP
                ], simulator.wire_log
            yield endpoint, record
        finally:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            record.update(process_exit=process.returncode, process_cleanup=process.poll() is not None,
                          listener_closed=bool(listeners) and all(port_closed(address) for address in listeners))
            record["pci_wire"] = [] if simulator is None else list(simulator.wire_log)
            resources.close()
            record.update(pci_closed=pci is None or port_closed(pci),
                          broker_closed=broker_endpoint is None or port_closed(broker_endpoint))
            if simulator is not None:
                assert [(row["direction"], bytes.fromhex(row["hex"])) for row in record["pci_wire"]] == [
                    ("rx", frame) for frame in STARTUP
                ], record["pci_wire"]
    assert all(record[key] for key in ("listener_owned", "process_cleanup", "listener_closed",
                                        "pci_closed", "broker_closed")) if "listener_owned" in record else True


@pytest.mark.parametrize("backend,variable", [
    ("cgate-mock", "CBUS_CGATE_MOCK_BIN"), ("cmqttd", "CBUS_CMQTTD_BIN"),
], ids=["mock", "daemon"])
def test_public_numeric_application_copy_end_to_end(backend, variable, tmp_path):
    supplied = os.environ.get(variable)
    if not supplied:
        pytest.skip(f"Select {variable} for the owned numeric copy journey")
    binary = Path(supplied).resolve()
    assert binary.is_file() and os.access(binary, os.X_OK), f"Invalid configured {variable}: {binary}"
    with no_contact_trap() as trap, owned_backend(backend, binary, tmp_path) as (endpoint, record):
        with CGateClient(*endpoint, timeout=15) as owner:
            db = NativeDatabase(owner)

            def command(body):
                result = owner.command(body)
                assert result.code == 200, result

            def document(path):
                return xml_text(db.get(path, xml=True))

            def cli(*arguments, project="LAB", expected=0, select_project=True):
                argv = [sys.executable, "-m", "cbus_toolkit", "cgate", "--host", endpoint[0],
                        "--port", str(endpoint[1]), "--timeout", "15", "database",
                        *map(str, arguments)]
                if select_project:
                    argv += ["--project", project]
                result = subprocess.run(argv, text=True, capture_output=True, timeout=30)
                value = json.loads(result.stdout or result.stderr)
                record.setdefault("cli_calls", []).append({"argv": result.args, "exit": result.returncode,
                                                           "stdout": result.stdout, "stderr": result.stderr,
                                                           "result": value})
                assert result.returncode == expected, value
                return value

            def field(oid, name, expected):
                value = cli("get", f"!{oid}/{name}")
                assert value["status"] == 342, value
                assert value["final"].rsplit("=", 1)[-1] == str(expected)

            def issued(value):
                assert value["status"] == 301, value
                match = re.fullmatch(r"301 OID=([0-9a-fA-F-]{36})", value["final"])
                assert match is not None, value
                oid = match[1]
                field(oid, "OID", oid)
                return oid

            command("PROJECT NEW LAB")
            command("PROJECT USE LAB")
            created = cli("network-new", "LAB", "254", "Loopback", "Cni", "127.0.0.1:1",
                          project="LAB", select_project=False)
            assert created["status"] in (200, 301), created
            network = "//LAB/254"
            app = issued(cli("add", network, "application", 56, "Lighting"))
            group = issued(cli("add", network + "/56", "group", 1, "Lamp"))
            level = issued(cli("add", network + "/56/1", "level", 7, "Evening"))
            field(level, "Value", 7)
            variable_oid = issued(cli("add", network + "/56", "netvar", 4, "Variable"))
            variable_level = issued(cli("add", network + "/56/4", "level", 42, "Dinner"))
            field(variable_level, "Value", 42)
            # Ordinary numeric Application copy with descendant preservation.
            source = document(network + "/56")
            source_oids = {node.text for node in ET.fromstring(source).iter("OID")}
            assert source_oids == {app, group, level, variable_oid, variable_level}
            copied = issued(cli("copy", network + "/56", network, 57, "Copy"))
            assert copied != app
            copied_document = document("!" + copied)
            copied_oids = {node.text for node in ET.fromstring(copied_document).iter("OID")}
            assert len(copied_oids) == len(source_oids) and copied_oids.isdisjoint(source_oids)
            assert document(network + "/56") == source
            assert "<TagName>Copy</TagName>" in copied_document
            assert "<Address>57</Address>" in copied_document
            # Admitted OID Group selector with a numeric parent.
            group_source = document("!" + group)
            copied_group = issued(cli("copy", "!" + group, network + "/56", 2, "Copied lamp"))
            assert document("!" + group) == group_source
            # Numeric Level copy flows through the caller value initializer.
            # Numeric bare-Level sources project as `<Object/>`, so the CLI
            # retains the source value there; the admitted OID selector
            # renders `<Level>` and takes the initializer.
            copied_level = issued(cli("copy", network + "/56/1/7", network + "/56/1", 8, "Reading"))
            field(copied_level, "Address", 8)
            field(copied_level, "Value", 7)
            field(level, "Value", 7)
            oid_copied_level = issued(cli("copy", "!" + level, network + "/56/1", 9, "OID reading"))
            field(oid_copied_level, "Address", 9)
            field(oid_copied_level, "Value", 9)
            # Destination conflicts refuse without mutation.
            before = document(network)
            assert "409" in cli("copy", network + "/56", network, 57, "Clash", expected=1)["error"]
            assert "409" in cli("copy", network + "/56", network, 56, "Self", expected=1)["error"]
            ghost = cli("copy", network + "/99", network, 60, "Ghost", expected=1)["error"]
            assert "401" in ghost or "404" in ghost, ghost
            assert document(network) == before
            for body in ("PROJECT SAVE LAB", "PROJECT CLOSE LAB", "PROJECT LOAD LAB"):
                command(body)
            for oid in (app, group, level, variable_oid, variable_level, copied, copied_group, copied_level,
                        oid_copied_level):
                field(oid, "OID", oid)
    assert record["process_cleanup"] and record["listener_closed"]
