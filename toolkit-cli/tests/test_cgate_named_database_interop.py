"""Public selected database CLI sessions on two explicitly owned Rust backends."""
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
import time
import uuid
from xml.etree import ElementTree as ET

import pytest

from cbus_toolkit.cgate import CGateClient
from cbus_toolkit.file_transfer import prepare_upload, upload
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
def owned_backend(kind, binary, work):
    """One direct child; no adopted process, listener, PCI or MQTT endpoint."""
    record = {"backend": kind, "process_cleanup": False}
    pci = broker_endpoint = endpoint = simulator = None
    listeners = []
    with ExitStack() as resources:
        if kind == "cmqttd":
            # A socket held by this test is an inert MQTT peer: it never
            # publishes a command. The empty Lighting application prevents
            # startup fallback full-bus discovery while awaiting its handshake.
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
            argv = [str(binary), "--tcp", f"{pci[0]}:{pci[1]}", "--broker-address", "127.0.0.1",
                    "--broker-port", str(broker_endpoint[1]), "--broker-disable-tls",
                    "--timesync", "0", "--status-resync", "0", "--project-file", str(project),
                    "--cgate-bind", "127.0.0.1:0", "--cgate-state", str(work / "state.json")]
            pattern = r"C-Gate service listening on 127\.0\.0\.1:(\d+)"
        else:
            argv = [str(binary), "--bind", "127.0.0.1:0", "--native-project-archives"]
            pattern = r"cgate-mock listening on 127\.0\.0\.1:(\d+)"
        stdout_path, stderr_path = work / "stdout.log", work / "stderr.log"
        stdout = resources.enter_context(stdout_path.open("wb"))
        stderr = resources.enter_context(stderr_path.open("wb"))
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
            lsof = shutil.which("lsof")
            assert lsof is not None, "Owned listener verification requires lsof"
            listing = subprocess.run(
                [lsof, "-nP", "-a", "-p", str(process.pid), "-iTCP", "-sTCP:LISTEN", "-Fpn"],
                text=True, capture_output=True, timeout=5,
            )
            assert listing.returncode == 0 and not listing.stderr, listing
            assert [line[1:] for line in listing.stdout.splitlines() if line.startswith("p")] == [str(process.pid)]
            actual_listeners = [line[1:] for line in listing.stdout.splitlines() if line.startswith("n")]
            assert sorted(actual_listeners) == sorted(f"{host}:{port}" for host, port in listeners), listing.stdout
            record["listener_endpoints"] = listeners
            record["listener_owned"] = True
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
        # Inspect after child termination to include shutdown traffic.
        record["pci_wire"] = [] if simulator is None else list(simulator.wire_log)
        if simulator is not None:
            assert [(row["direction"], bytes.fromhex(row["hex"])) for row in simulator.wire_log] == [
                ("rx", frame) for frame in STARTUP
            ], simulator.wire_log
        resources.close()
        record.update(pci_closed=pci is None or port_closed(pci),
                      broker_closed=broker_endpoint is None or port_closed(broker_endpoint))
    assert all(record[key] for key in ("listener_owned", "process_cleanup", "listener_closed",
                                        "pci_closed", "broker_closed")), record


@pytest.mark.parametrize("backend,variable", [
    ("cgate-mock", "CBUS_CGATE_MOCK_BIN"), ("cmqttd", "CBUS_CMQTTD_BIN"),
], ids=["mock", "daemon"])
def test_public_named_safe_graph_separate_project_selected_sessions(backend, variable, tmp_path):
    supplied = os.environ.get(variable)
    if not supplied:
        pytest.skip(f"Select {variable} for the owned named database journey")
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

            def cli(*arguments, project="LAB", expected=0):
                result = subprocess.run(
                    [sys.executable, "-m", "cbus_toolkit", "cgate", "--host", endpoint[0],
                     "--port", str(endpoint[1]), "--timeout", "15", "database",
                     *map(str, arguments), "--project", project],
                    text=True, capture_output=True, timeout=30,
                )
                value = json.loads(result.stdout or result.stderr)
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

            def add(parent, kind, address, name):
                return issued(cli("add", parent, kind, address, name))

            def seed_mock_project(project, names):
                # The mock has no runtime-definition materialization contract.
                # Public FILE/RESTORE imports complete independent tag records;
                # the daemon below exercises real NET CREATE/SAVE DB instead.
                networks = "".join(
                    f"<Network><OID>{uuid.uuid4()}</OID><TagName>n{name}</TagName>"
                    f"<Address>{name}</Address><NetworkNumber>0xff</NetworkNumber>"
                    f"<Interface><OID>{uuid.uuid4()}</OID><InterfaceType>cni</InterfaceType>"
                    f"<InterfaceAddress>{trap}</InterfaceAddress></Interface></Network>"
                    for name in names
                )
                fixture = tmp_path / f"{project}-fixture.xml"
                fixture.write_text(
                    f"<Installation><DBVersion>2.3</DBVersion><Project><OID>{uuid.uuid4()}</OID>"
                    f"<TagName>{project}</TagName><Address>{project}</Address>"
                    + networks + "</Project></Installation>", encoding="utf-8",
                )
                receipt = upload(prepare_upload(f"Projects/archived/{fixture.name}", fixture), owner)
                assert receipt["upload_completed"] and not receipt["project_save_requested"]
                command(f"PROJECT RESTORE {project} {fixture.name}")
                command(f"PROJECT USE {project}")
                command(f"PROJECT SAVE {project}")

            if backend == "cgate-mock":
                command("FILE MKDIR Projects")
                command("FILE MKDIR Projects/archived")
                seed_mock_project("LAB", ("Neighbor", "CustomA"))
                record["named_seeding"] = "Public controlled FILE upload and complete XML PROJECT RESTORE"
            else:
                for body in ("PROJECT NEW LAB", "PROJECT USE LAB", f"NET CREATE Neighbor cni {trap}",
                             f"NET CREATE CustomA cni {trap}", "NET SAVE DB", "PROJECT SAVE LAB"):
                    command(body)
                record["named_seeding"] = "NET CREATE then NET SAVE DB"
            neighbor = document("//LAB/Neighbor")
            if backend == "cgate-mock":
                seed_mock_project("OTHER", ("Else",))
            else:
                for body in ("PROJECT NEW OTHER", "PROJECT USE OTHER", f"NET CREATE Else cni {trap}",
                             "NET SAVE DB", "PROJECT SAVE OTHER"):
                    command(body)
            other = document("//OTHER")
            # Owner selection cannot select any subsequent CLI subprocess.
            network = "//LAB/CustomA"
            assert cli("get", network + "/Address")["final"].endswith("=CustomA")
            app = add(network, "application", 56, "Lighting")
            group = add("!" + app, "group", 1, "Lamp")
            assert cli("set", f"!{group}/TagName", "Edited lamp")["status"] == 200
            field(group, "TagName", "Edited lamp")
            level = add("!" + group, "level", 7, "Evening")
            field(level, "Value", 7)
            copied_level = issued(cli("copy", "!" + level, "!" + group, 8, "Reading"))
            assert copied_level != level
            field(copied_level, "Address", 8)
            field(copied_level, "Value", 8)
            field(level, "Value", 7)
            variable = add("!" + app, "netvar", 4, "Variable")
            variable_level = add("!" + variable, "level", 42, "Dinner")
            field(variable_level, "Value", 42)
            command("PROJECT USE LAB")
            source = document("!" + group)
            copied_group = issued(cli("copy", "!" + group, "!" + app, 2, "Copied lamp"))
            assert document("!" + group) == source
            source_oids = {node.text for node in ET.fromstring(source).iter("OID")}
            copied_oids = {node.text for node in ET.fromstring(document("!" + copied_group)).iter("OID")}
            assert len(copied_oids) == len(source_oids) and copied_oids.isdisjoint(source_oids)
            before = document(network)
            for action, arguments in (("get", (f"!{group}/OID",)),
                                      ("set", (f"!{group}/TagName", "Foreign edit"))):
                assert "401" in cli(action, *arguments, project="OTHER", expected=1)["error"]
                assert document(network) == before
            assert cli("delete", "!" + copied_group)["status"] == 200
            assert "401" in cli("get", f"!{copied_group}/OID", expected=1)["error"]
            validation = cli("validate", network)
            assert validation["status"] == 233 and "Network: Valid" in validation["final"]
            for body in ("PROJECT SAVE LAB", "PROJECT CLOSE LAB", "PROJECT LOAD LAB"):
                command(body)
            for oid in (app, group, level, copied_level, variable, variable_level):
                field(oid, "OID", oid)
            for oid, value in ((level, 7), (copied_level, 8), (variable_level, 42)):
                field(oid, "Value", value)
            field(group, "TagName", "Edited lamp")
            field(copied_level, "Address", 8)
            assert document("//LAB/Neighbor") == neighbor
            assert document("//OTHER") == other
    assert record["process_cleanup"] and record["listener_closed"]
