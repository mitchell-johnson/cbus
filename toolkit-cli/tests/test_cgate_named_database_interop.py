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
import threading
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
def owned_backend(kind, binary, work, *, state_path=None, auth_file=None):
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
            project.chmod(0o600)
            argv = [str(binary), "--tcp", f"{pci[0]}:{pci[1]}", "--broker-address", "127.0.0.1",
                    "--broker-port", str(broker_endpoint[1]), "--broker-disable-tls",
                    "--timesync", "0", "--status-resync", "0", "--project-file", str(project),
                    "--cgate-bind", "127.0.0.1:0", "--cgate-state", str(state_path or work / "state.json")]
            if auth_file is not None:
                argv.extend(("--cgate-auth-file", str(auth_file)))
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
            # Inspect after child termination, including failed journeys and shutdown traffic.
            record["pci_wire"] = [] if simulator is None else list(simulator.wire_log)
            resources.close()
            record.update(pci_closed=pci is None or port_closed(pci),
                          broker_closed=broker_endpoint is None or port_closed(broker_endpoint))
            associated_evidence(work / "backend-process-evidence.json", record)
            if simulator is not None:
                assert [(row["direction"], bytes.fromhex(row["hex"])) for row in record["pci_wire"]] == [
                    ("rx", frame) for frame in STARTUP
                ], record["pci_wire"]
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


class RecordedGate:
    """Owned loopback byte relay; each CLI has one separately recorded socket."""

    def __init__(self, target):
        self.target = target
        self.rows = []
        self.workers = []
        self.errors = []
        self.stop = threading.Event()

    def __enter__(self):
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(8)
        self.listener.settimeout(.05)
        self.endpoint = self.listener.getsockname()
        self.acceptor = threading.Thread(target=self._accept, daemon=True)
        self.acceptor.start()
        return self

    def _accept(self):
        while not self.stop.is_set():
            try:
                peer, _ = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                if not self.stop.is_set():
                    self.errors.append("accept failed")
                return
            row = {"request_hex": "", "response_hex": "", "closed": False,
                   "done": threading.Event()}
            self.rows.append(row)
            worker = threading.Thread(target=self._relay, args=(peer, row), daemon=True)
            self.workers.append(worker)
            worker.start()

    def _relay(self, peer, row):
        try:
            with peer, socket.create_connection(self.target, timeout=5) as remote:
                peer.settimeout(5)
                remote.settimeout(5)
                while not self.stop.is_set():
                    readable, _, _ = select.select([peer, remote], [], [], .05)
                    for source in readable:
                        data = source.recv(65536)
                        if not data:
                            return
                        key, destination = ("request_hex", remote) if source is peer else ("response_hex", peer)
                        row[key] += data.hex()
                        destination.sendall(data)
        except (OSError, ValueError) as error:
            self.errors.append(type(error).__name__)
        finally:
            row["closed"] = True
            row["done"].set()

    def __exit__(self, *_):
        self.stop.set()
        self.listener.close()
        self.acceptor.join(5)
        for worker in self.workers:
            worker.join(5)
        assert not self.acceptor.is_alive() and all(not worker.is_alive() for worker in self.workers)
        assert all(row["closed"] for row in self.rows), self.rows
        assert not self.errors, self.errors
        assert port_closed(self.endpoint)

    def evidence(self):
        return [{key: value for key, value in row.items() if key != "done"} for row in self.rows]


def associated_cli(relay, calls, *arguments, project="LAB", expected=0):
    before = len(relay.rows)
    argv = [sys.executable, "-m", "cbus_toolkit", "cgate", "--host", relay.endpoint[0],
            "--port", str(relay.endpoint[1]), "--timeout", "15", "database",
            *map(str, arguments), "--project", project]
    result = subprocess.run(argv, text=True, capture_output=True, timeout=30)
    calls.append({"argv": argv, "exit": result.returncode, "stdout": result.stdout,
                  "stderr": result.stderr})
    value = json.loads(result.stdout or result.stderr)
    calls[-1]["result"] = value
    assert result.returncode == expected, value
    assert len(relay.rows) == before + 1, "CLI opened more than one connection"
    row = relay.rows[before]
    assert row["done"].wait(5), "CLI connection did not close"
    requests = bytes.fromhex(row["request_hex"]).decode("utf-8").splitlines()
    tagged = [re.fullmatch(r"\[([^]]+)\] (.+)", line) for line in requests]
    assert tagged and all(tagged), requests
    tags, commands = zip(*(match.groups() for match in tagged))
    assert len(set(tags)) == len(tags), "Request tag was reused"
    assert commands[0] == f"PROJECT USE {project}"
    assert sum(command.startswith("PROJECT USE ") for command in commands) == 1
    replies = bytes.fromhex(row["response_hex"]).decode("utf-8").splitlines()
    terminals = {}
    for line in replies:
        match = re.fullmatch(r"\[([^]]+)\] (\d{3}) (.*)", line)
        if match and match[1] in tags:
            assert match[1] not in terminals, replies
            terminals[match[1]] = (int(match[2]), match[3])
    assert set(terminals) == set(tags), replies
    assert terminals[tags[0]][0] == 200, "Selection was not accepted before dependents"
    calls[-1].update(commands=list(commands), statuses=[terminals[tag][0] for tag in tags],
                     terminals=[terminals[tag][1] for tag in tags])
    return value, calls[-1]


def associated_seed(owner, work, trap):
    """Complete synthetic numeric graph plus a legacy NetVar created before rename."""
    roles = {name: str(uuid.uuid4()) for name in
             ("project", "network", "interface", "neighbor", "neighbor_interface",
              "application", "group1", "group2", "source")}
    network = (
        f"<Network><OID>{roles['network']}</OID><TagName>Eleven</TagName><Address>11</Address>"
        f"<NetworkNumber>11</NetworkNumber><Interface><OID>{roles['interface']}</OID>"
        f"<InterfaceType>Cni</InterfaceType><InterfaceAddress>{trap}</InterfaceAddress></Interface>"
        f"<Application><OID>{roles['application']}</OID><TagName>Lighting</TagName><Address>56</Address>"
        f"<Group><OID>{roles['group1']}</OID><TagName>Source group</TagName><Address>1</Address>"
        f"<Level Value=\"77\"><OID>{roles['source']}</OID><TagName>Source</TagName><Address>7</Address>"
        "</Level></Group>"
        f"<Group><OID>{roles['group2']}</OID><TagName>Destination</TagName><Address>2</Address>"
        "</Group></Application></Network>"
        f"<Network><OID>{roles['neighbor']}</OID><TagName>Neighbor</TagName><Address>12</Address>"
        f"<NetworkNumber>12</NetworkNumber><Interface><OID>{roles['neighbor_interface']}</OID>"
        f"<InterfaceType>Cni</InterfaceType><InterfaceAddress>{trap}</InterfaceAddress></Interface></Network>"
    )
    fixture = work / "associated-fixture.xml"
    fixture.write_text(
        f"<Installation><DBVersion>2.3</DBVersion><Project><OID>{roles['project']}</OID>"
        "<TagName>LAB</TagName><Address>LAB</Address>" + network + "</Project></Installation>",
        encoding="utf-8",
    )
    fixture.chmod(0o600)
    for command in ("FILE MKDIR Projects", "FILE MKDIR Projects/archived"):
        assert owner.command(command).code == 200
    uploaded = upload(prepare_upload("Projects/archived/associated.xml", fixture), owner)
    assert uploaded["upload_completed"] and not uploaded["project_save_requested"]
    for command in ("PROJECT RESTORE LAB associated.xml", "PROJECT USE LAB"):
        assert owner.command(command).code == 200
    variable = owner.command("DBADDSAFE //LAB/11/56 NetVar 4 Variable")
    assert variable.code == 301, variable
    roles["netvar"] = variable.final.removeprefix("301 OID=")
    assert re.fullmatch(r"[0-9a-fA-F-]{36}", roles["netvar"])
    assert owner.command("DBRENAMENETSAFE 11 Renamed").code == 200
    assert owner.command(f"DBGET !{roles['netvar']}/OID").final.endswith("=" + roles["netvar"])
    for command in ("PROJECT NEW OTHER", "PROJECT USE LAB"):
        assert owner.command(command).code == 200
    return roles


def associated_document(owner, path):
    return xml_text(NativeDatabase(owner).get(path, xml=True))


def associated_snapshot(owner, backend):
    control = "//BRIDGE/254" if backend == "cmqttd" else "//CONTROL/254"
    result = {}
    try:
        for path in ("//LAB/Renamed", "//LAB/12", "//OTHER", control):
            project = path.split("/")[2]
            assert owner.command("PROJECT USE " + project).code == 200
            result[path] = associated_document(owner, path)
    finally:
        assert owner.command("PROJECT USE LAB").code == 200
    return result


def associated_work(parent, name):
    work = parent / name
    work.mkdir(mode=0o700)
    return work


def associated_evidence(path, data):
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)


@pytest.mark.parametrize("backend,variable", [
    ("cgate-mock", "CBUS_CGATE_MOCK_BIN"), ("cmqttd", "CBUS_CMQTTD_BIN"),
], ids=["mock", "daemon"])
def test_public_renamed_associated_level_cli_owner_and_wire(backend, variable, tmp_path):
    supplied = os.environ.get(variable)
    if not supplied:
        pytest.skip(f"Select {variable} for the owned associated Level journey")
    binary = Path(supplied).resolve()
    assert binary.is_file() and os.access(binary, os.X_OK)
    vector_path = Path(__file__).resolve().parents[2] / "rust/testdata/vectors/cgate_associated_level_cli_wire.json"
    vector = json.loads(vector_path.read_text(encoding="utf-8"))
    assert vector["format"] == "cbus-associated-level-cli-wire-v1"
    assert not vector["scope"]["original_execution"]
    calls, processes, wires = [], [], []
    work = associated_work(tmp_path, "initial")
    evidence = {"format": "cbus-associated-level-cli-local-v1", "backend": backend,
                "original_execution": False, "calls": calls, "processes": processes,
                "scope": vector["scope"], "vector": str(vector_path), "wires": wires}
    relay = None
    try:
        with no_contact_trap() as trap:
            with owned_backend(backend, binary, work) as (endpoint, record):
                processes.append(record)
                with CGateClient(*endpoint, timeout=15) as owner, RecordedGate(endpoint) as relay:
                    roles = associated_seed(owner, work, trap)
                    evidence["oid_roles"] = roles
                    if backend == "cgate-mock":
                        for command in ("PROJECT NEW CONTROL", f"DBCREATENET 254 Control Cni {trap}", "PROJECT USE LAB"):
                            assert owner.command(command).code == 200
                    before = associated_snapshot(owner, backend)
                    source = associated_document(owner, "!" + roles["source"])
                    evidence.update(before=before, source_xml=source)
                    issued_oids = set(roles.values())
                    # Canonicalize first so subsequent copies consume the synchronized owner.
                    for literal in ("077", "+77"):
                        value, wire = associated_cli(relay, calls, "set", "!" + roles["source"] + "/Value", literal)
                        assert value["status"] == 200 and wire["statuses"] == [200, 200]
                        got, _ = associated_cli(relay, calls, "get", "!" + roles["source"] + "/Value")
                        assert got["final"].endswith("=77")
                        assert associated_document(owner, "!" + roles["source"]) == source

                    def expand(value):
                        for role, oid in roles.items():
                            value = value.replace("${" + role + "}", oid)
                        return value

                    for case in vector["cases"]:
                        value, wire = associated_cli(relay, calls, *(expand(arg) for arg in case["argv"]))
                        assert value["status"] == 301, value
                        oid = value["final"].removeprefix("301 OID=")
                        assert re.fullmatch(r"[0-9a-fA-F-]{36}", oid)
                        assert oid not in issued_oids
                        issued_oids.add(oid)
                        roles["issued"] = oid
                        roles[case["id"]] = oid
                        assert wire["commands"] == [expand(request) for request in case["requests"]]
                        assert wire["statuses"] == case["statuses"]
                        assert wire["terminals"][-2] == f"!{oid}/OID={oid}"
                        got, _ = associated_cli(relay, calls, "get", f"!{oid}/Value")
                        assert got["status"] == 342 and got["final"].endswith("=" + str(case["value"]))
                        assert associated_document(owner, "!" + roles["source"]) == source
                    immutable = associated_snapshot(owner, backend)
                    evidence["before_refusals"] = immutable
                    failures = [
                        (("add", "//LAB/Renamed/56/1", "level", "20", "Foreign"), "OTHER", [200, 401]),
                        (("copy", "!" + roles["source"], "!" + roles["group2"], "20", "Foreign"), "OTHER", [200, 401]),
                        (("add", "!" + roles["group1"] + "/Address", "level", "20", "Scalar"), "LAB", [200, 401]),
                        (("add", "!" + roles["group1"], "level", "7", "Collision"), "LAB", [200, 401]),
                    ]
                    for arguments, project, statuses in failures:
                        value, wire = associated_cli(relay, calls, *arguments, project=project, expected=1)
                        assert "401" in value["error"] and wire["statuses"] == statuses
                        request = ("DBGETXML " + arguments[1] if arguments[0] == "copy" else
                                   f"DBADDSAFE {arguments[1]} Level {arguments[3]} {arguments[4]}")
                        assert wire["commands"] == [f"PROJECT USE {project}", request]
                        assert associated_snapshot(owner, backend) == immutable
                    # A direct SAFE add has no public CLI Value initializer. Preserve the
                    # associated owner's local NULL getter/save contract independently.
                    null_level = owner.command(f"DBADDSAFE !{roles['group2']} Level 30 Null")
                    assert null_level.code == 301, null_level
                    roles["null"] = null_level.final.removeprefix("301 OID=")
                    assert roles["null"] not in issued_oids
                    null, wire = associated_cli(relay, calls, "get", f"!{roles['null']}/Value")
                    assert wire["commands"] == [expand(request) for request in vector["null_case"]["requests"]]
                    assert wire["statuses"] == vector["null_case"]["statuses"]
                    assert null["final"].endswith("=null")
                    for command in ("PROJECT SAVE LAB", "PROJECT CLOSE LAB", "PROJECT LOAD LAB", "PROJECT USE LAB"):
                        assert owner.command(command).code == 200
                    saved = associated_snapshot(owner, backend)
                    evidence["saved_reload"] = saved
                    for path in ("//LAB/12", "//OTHER", "//BRIDGE/254" if backend == "cmqttd" else "//CONTROL/254"):
                        assert saved[path] == before[path]
                    assert owner.command(f"DBGET !{roles['netvar']}/OID").final.endswith("=" + roles["netvar"])
                    for case in vector["cases"]:
                        value = owner.command(f"DBGET !{roles[case['id']]}/Value")
                        assert value.code == 342 and value.final.endswith("=" + str(case["value"]))
                    assert owner.command(f"DBGET !{roles['null']}/Value").final.endswith("=null")
            # Only cmqttd owns durable JSON; mock has process-local save/load above.
            if backend == "cmqttd":
                restart = associated_work(tmp_path, "restart")
                with owned_backend(backend, binary, restart, state_path=work / "state.json") as (endpoint, record):
                    processes.append(record)
                    with CGateClient(*endpoint, timeout=15) as owner:
                        assert owner.command("PROJECT USE LAB").code == 200
                        restarted = associated_snapshot(owner, backend)
                        evidence["restart"] = restarted
                        assert restarted == saved
                        assert owner.command(f"DBGET !{roles['netvar']}/OID").final.endswith("=" + roles["netvar"])
                evidence["json_restart_verified"] = True
            else:
                evidence["json_restart_verified"] = False
            evidence["closed_graph_trap_contacts"] = 0
    finally:
        if relay is not None:
            wires[:] = relay.evidence()
        associated_evidence(tmp_path / "associated-level-evidence.json", evidence)


def test_public_renamed_associated_level_cli_auth_and_restart(tmp_path):
    supplied = os.environ.get("CBUS_CMQTTD_BIN")
    if not supplied:
        pytest.skip("Select CBUS_CMQTTD_BIN for the owned associated Level LOGIN journey")
    binary = Path(supplied).resolve()
    assert binary.is_file() and os.access(binary, os.X_OK)
    auth_file = tmp_path / "owned-auth.token"
    token = uuid.uuid4().hex + uuid.uuid4().hex
    auth_file.write_text(token + "\n", encoding="utf-8")
    auth_file.chmod(0o600)
    calls, processes, wires = [], [], []
    evidence = {"format": "cbus-associated-level-cli-auth-local-v1", "original_execution": False,
                "calls": calls, "processes": processes, "wires": wires}
    work = associated_work(tmp_path, "initial")
    relay = None
    try:
        with no_contact_trap() as trap:
            with owned_backend("cmqttd", binary, work, auth_file=auth_file) as (endpoint, record):
                processes.append(record)
                with CGateClient(*endpoint, timeout=15) as owner, RecordedGate(endpoint) as relay:
                    assert owner.command("LOGIN " + token).code == 200
                    roles = associated_seed(owner, work, trap)
                    evidence["oid_roles"] = roles
                    before = associated_snapshot(owner, "cmqttd")
                    evidence["before_refusals"] = before
                    state = (work / "state.json").read_bytes()
                    for arguments, statuses in (
                        (("add", "!" + roles["group1"], "level", "8", "Denied"), [200, 420]),
                        (("copy", "!" + roles["source"], "!" + roles["group2"], "8", "Denied"), [200, 344, 420]),
                        (("set", "!" + roles["source"] + "/Value", "8"), [200, 420]),
                    ):
                        value, wire = associated_cli(relay, calls, *arguments, expected=1)
                        assert "420" in value["error"] and wire["statuses"] == statuses
                        expected_commands = ["PROJECT USE LAB"]
                        if arguments[0] == "copy":
                            expected_commands.extend((f"DBGETXML {arguments[1]}",
                                                      f"DBCOPYSAFE {arguments[1]} {arguments[2]} 8 Denied"))
                        elif arguments[0] == "add":
                            expected_commands.append(f"DBADDSAFE {arguments[1]} Level 8 Denied")
                        else:
                            expected_commands.append(f"DBSETSAFE {arguments[1]} 8")
                        assert wire["commands"] == expected_commands
                        assert associated_snapshot(owner, "cmqttd") == before
                        assert (work / "state.json").read_bytes() == state
                    for command in ("PROJECT SAVE LAB", "PROJECT CLOSE LAB", "PROJECT LOAD LAB", "PROJECT USE LAB"):
                        assert owner.command(command).code == 200
                    saved = associated_snapshot(owner, "cmqttd")
                    evidence["saved_reload"] = saved
            restart = associated_work(tmp_path, "restart")
            with owned_backend("cmqttd", binary, restart, state_path=work / "state.json", auth_file=auth_file) as (endpoint, record):
                processes.append(record)
                with CGateClient(*endpoint, timeout=15) as owner:
                    assert owner.command("LOGIN " + token).code == 200
                    assert owner.command("PROJECT USE LAB").code == 200
                    restarted = associated_snapshot(owner, "cmqttd")
                    evidence["restart"] = restarted
                    assert restarted == saved
            evidence["json_restart_verified"] = True
            evidence["closed_graph_trap_contacts"] = 0
    finally:
        if relay is not None:
            wires[:] = relay.evidence()
        associated_evidence(tmp_path / "associated-level-auth-evidence.json", evidence)
