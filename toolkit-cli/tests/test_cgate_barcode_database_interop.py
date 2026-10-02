"""Public barcode database journeys on explicitly owned, closed Rust backends.

The catalogue and projects are synthetic. These checks exercise the public
subprocess CLI, keep literal request/reply bytes, and make no native or physical
acceptance claim.
"""
from __future__ import annotations

from contextlib import contextmanager, nullcontext
import hashlib
import json
import os
from pathlib import Path
import re
import select
import socket
import subprocess
import sys
import uuid
from xml.etree import ElementTree as ET

import pytest

from cbus_toolkit.cgate import CGateClient
from cbus_toolkit.file_transfer import prepare_upload, upload
from cbus_toolkit.native import NativeDatabase
from cbus_toolkit.programming import xml_text
from test_barcode_scanner import CATALOG_XML
from test_cgate_named_database_interop import (
    RecordedGate, associated_evidence, associated_work, no_contact_trap,
    owned_backend,
)


VECTOR_PATH = Path(__file__).resolve().parents[2] / "rust/testdata/vectors/cgate_barcode_database_cli_wire.json"
CONFIG = "5031NL          123456789012"
FIELDS = ("OID", "TagName", "Address", "UnitType", "UnitName", "SerialNumber",
          "FirmwareVersion", "CatalogNumber")
MUTATIONS = ("DBADD", "DBADDSAFE", "DBSET", "DBSETSAFE", "DBSETXML", "DBDELETE",
             "DBCOPY", "DBCOPYSAFE", "PP ", "PROJECT SAVE", "PROJECT CLOSE", "PROJECT LOAD")


def digest(value):
    return hashlib.sha256(value.encode("utf-8") if isinstance(value, str) else value).hexdigest()


def vector():
    value = json.loads(VECTOR_PATH.read_text(encoding="utf-8"))
    assert value["format"] == "cbus-cgate-barcode-database-cli-wire-v1"
    assert value["scope"]["original_execution"] is False
    assert value["scope"]["physical_acceptance"] is False
    return value


def expand(value, roles):
    for name, replacement in roles.items():
        value = value.replace("${" + name + "}", str(replacement))
    assert "${" not in value, value
    return value


def document(owner, path):
    return xml_text(NativeDatabase(owner).get(path, xml=True))


def graph(text):
    """Compare the full emitted tree, retaining attributes, order, comments/PI.

    Formatting whitespace between children has no model meaning; all scalar
    text and significant mixed text remain exact.
    """
    root = ET.fromstring(text, parser=ET.XMLParser(target=ET.TreeBuilder(
        insert_comments=True, insert_pis=True)))

    def node(element):
        tag = element.tag if isinstance(element.tag, str) else element.tag.__name__
        text = element.text or ""
        tail = element.tail or ""
        return (tag, tuple(sorted(element.attrib.items())),
                text if not list(element) or text.strip() else "",
                tail if tail.strip() else "", tuple(node(child) for child in element))

    return node(root)


def snapshot(owner, backend):
    return {project: document(owner, "//" + project)
            for project in ("LAB", "OTHER", "BRIDGE") if project != "BRIDGE" or backend == "cmqttd"}


def assert_unchanged(owner, backend, before):
    assert snapshot(owner, backend) == before


def fields(text):
    root = ET.fromstring(text)
    assert root.tag == "Unit", text
    result = {child.tag: child.text or "" for child in root if child.tag != "PP"}
    assert len(result) == len([child for child in root if child.tag != "PP"]), text
    return result


def assert_plain_unit(text, expected, *, order=FIELDS):
    root = ET.fromstring(text, parser=ET.XMLParser(target=ET.TreeBuilder(
        insert_comments=True, insert_pis=True)))
    assert root.tag == "Unit" and not root.attrib, text
    assert [child.tag for child in root] == list(order), text
    assert not (root.text or "").strip(), text
    assert all(not child.attrib and not len(child) and not (child.tail or "").strip()
               for child in root), text
    assert {child.tag: child.text or "" for child in root} == expected, text


def without_unit(text, oid):
    # The added Unit is a verified plain, unnamespaced document. Remove only
    # that literal fragment so the independent oracle also retains namespace
    # prefixes, comments, formatting and every preexisting byte outside it.
    matches = [match for match in re.finditer(r"<Unit>.*?</Unit>", text, re.DOTALL)
               if ET.fromstring(match[0]).findtext("OID") == oid]
    assert len(matches) == 1, (oid, text)
    match = matches[0]
    return text[:match.start()] + text[match.end():]


def seed(owner, work, trap, *, numeric=False):
    """Import retained Networks; the numeric fixture is assigned to Network11."""
    roles = {name: str(uuid.uuid4()) for name in (
        "project", "network", "interface", "property", "one", "three", "neighbor",
        "neighbor_interface", "far", "air", "air_interface", "wireless", "app",
        "group", "level", "other_project", "other_network", "other_interface",
    )}

    def unit(role, address, name, unit_type, serial, *, pp=False):
        parameters = ("<PP Name=\"UnitType\" Value=\"PP identity stays separate\"/>"
                      "<PP Name=\"OID\" Value=\"opaque PP OID\"/>"
                      "<PP Name=\"UnitName\" Value=\"PP name, not scalar name\"/>"
                      "<PP Name=\"CustomWords\" Value=\"001,002,255\"/>") if pp else ""
        return (f"<Unit><OID>{roles[role]}</OID><TagName>{name}</TagName><Address>{address}</Address>"
                f"<UnitName>{name} scalar</UnitName><UnitType>{unit_type}</UnitType>"
                f"<SerialNumber>{serial}</SerialNumber><CatalogNumber>retained catalogue</CatalogNumber>"
                "<FirmwareVersion>1.2.00</FirmwareVersion>" + parameters + "</Unit>")

    def network(role, name, children):
        interface = {"network": "interface", "other_network": "other_interface"}.get(
            role, role + "_interface")
        prop = (f"<Property><OID>{roles['property']}</OID><Name>RetainedProperty</Name>"
                "<Value>unchanged &amp; exact</Value></Property>") if role == "network" else ""
        return (f"<Network><OID>{roles[role]}</OID><TagName>{name} label</TagName>"
                f"<Address>{name}</Address><NetworkNumber>{11 if numeric and role == 'network' else '0xff'}</NetworkNumber>"
                "<!-- synthetic retained Network comment -->"
                "<s:Keep xmlns:s=\"urn:cbus:synthetic:barcode\" token=\"unchanged\"/>"
                f"<Interface><OID>{roles[interface]}</OID><InterfaceType>cni</InterfaceType>"
                f"<InterfaceAddress>{trap}</InterfaceAddress>{prop}</Interface>"
                + children + "</Network>")

    app = (f"<Application><OID>{roles['app']}</OID><TagName>Lighting</TagName><Address>56</Address>"
           f"<Group><OID>{roles['group']}</OID><TagName>Retained group</TagName><Address>1</Address>"
           f'<Level Value="77"><OID>{roles["level"]}</OID><TagName>Retained level</TagName><Address>7</Address>'
           "<TagsDLT/></Level></Group></Application>")
    networks = (
        network("network", "11" if numeric else "CustomA", unit("one", 1, "One", "KEYE1", "1234.5", pp=True)
                + unit("three", 3, "Three", "KEYE1", "") + app),
        network("neighbor", "Neighbor", unit("far", 9, "Far", "RELDN4", "990001.2")),
        network("air", "Air", unit("wireless", 2, "Wireless", "WKEY", "")),
    )
    for command in ("FILE MKDIR Projects", "FILE MKDIR Projects/archived"):
        assert owner.command(command).code == 200
    for name, content, project_oid in (
        ("LAB", "".join(networks), roles["project"]),
        ("OTHER", network("other_network", "Else", ""), roles["other_project"]),
    ):
        path = work / f"{name}-synthetic.xml"
        path.write_text("<Installation><DBVersion>2.3</DBVersion><Project>"
                        f"<OID>{project_oid}</OID><TagName>{name}</TagName><Address>{name}</Address>"
                        + content + "</Project></Installation>", encoding="utf-8")
        path.chmod(0o600)
        uploaded = upload(prepare_upload(f"Projects/archived/{path.name}", path), owner)
        assert uploaded["upload_completed"] and not uploaded["project_save_requested"]
        for command in (f"PROJECT RESTORE {name} {path.name}", f"PROJECT USE {name}",
                        f"PROJECT SAVE {name}"):
            assert owner.command(command).code == 200
    assert owner.command("PROJECT USE LAB").code == 200
    return roles


def preserve_difficult_siblings(owner, roles):
    """Existing independent data must not be re-admitted as a whole Network."""
    assert owner.command("DBSET //LAB/CustomA/56/1/7/Value oops").code == 200
    added = owner.command("DBADDSAFE //LAB/CustomA Unit 4 IncompleteSibling")
    assert added.code == 301
    match = re.fullmatch(r"301 OID=([0-9a-fA-F-]{36})", added.final)
    assert match is not None, added
    roles["incomplete"] = match[1]
    value = fields(document(owner, "//LAB/CustomA/p/4"))
    assert value == {"OID": match[1], "TagName": "IncompleteSibling", "Address": "4",
                     "UnitName": "IncompleteSibling"}, value
    network = document(owner, "//LAB/CustomA")
    levels = [level for level in ET.fromstring(network).iter("Level")
              if level.findtext("OID") == roles["level"]]
    assert len(levels) == 1 and levels[0].attrib == {"Value": "oops"}
    assert "synthetic retained Network comment" in network
    assert "urn:cbus:synthetic:barcode" in network
    return network


def parse_wire(row, *, complete=True):
    request = bytes.fromhex(row["request_hex"]).decode("utf-8").splitlines()
    commands, tags, documents = [], [], []
    index = 0
    while index < len(request):
        match = re.fullmatch(r"\[([^]]+)\] (.+)", request[index])
        assert match is not None, request
        tag, command = match.groups()
        tags.append(tag)
        if " << " in command:
            command, delimiter = command.rsplit(" << ", 1)
            assert command.startswith("DBSETXML "), request
            start = index + 1
            while index + 1 < len(request) and request[index + 1] != delimiter:
                index += 1
            assert index + 1 < len(request), "Unterminated document"
            body = "\n".join(request[start:index + 1]) + "\n"
            documents.append({"command": command, "body": body, "sha256": digest(body),
                              "delimiter": delimiter, "tag": tag})
            index += 1
        commands.append(command)
        index += 1
    assert tags and len(set(tags)) == len(tags), request
    terminals = {}
    payloads = {tag: [] for tag in tags}
    for line in bytes.fromhex(row["response_hex"]).decode("utf-8").splitlines():
        tagged = re.fullmatch(r"\[([^]]+)\] (.*)", line)
        if tagged and tagged[1] in tags:
            payloads[tagged[1]].append(tagged[2])
        match = re.fullmatch(r"\[([^]]+)\] (\d{3}) (.*)", line)
        if match and match[1] in tags:
            assert match[1] not in terminals, row
            terminals[match[1]] = (int(match[2]), match[3])
    assert set(terminals) <= set(tags), row
    if complete:
        assert set(terminals) == set(tags), row
    return {"commands": commands, "tags": tags, "documents": documents,
            "statuses": [terminals[tag][0] if tag in terminals else None for tag in tags],
            "terminals": [terminals[tag][1] if tag in terminals else None for tag in tags],
            "reply_lines": [payloads[tag] for tag in tags]}


def cli(relay, calls, *arguments, expected=0, connections=1, complete=True):
    before = len(relay.rows)
    argv = [sys.executable, "-m", "cbus_toolkit", "cgate", "--host", relay.endpoint[0],
            "--port", str(relay.endpoint[1]), "--timeout", "3", *map(str, arguments)]
    result = subprocess.run(argv, text=True, capture_output=True, timeout=20)
    call = {"argv": argv, "exit": result.returncode, "stdout": result.stdout, "stderr": result.stderr}
    calls.append(call)
    try:
        value = json.loads(result.stdout or result.stderr)
    except json.JSONDecodeError:
        pytest.fail(f"Public CLI did not emit JSON: {call}")
    call["result"] = value
    assert result.returncode == expected, call
    assert len(relay.rows) == before + connections, call
    if connections:
        row = relay.rows[before]
        assert row["done"].wait(5), "CLI connection did not close"
        call.update(parse_wire(row, complete=complete))
        call["wire_index"] = before
    else:
        call.update(commands=[], statuses=[], terminals=[], documents=[], reply_lines=[])
    return value, call


def barcode(relay, calls, catalog, *arguments, project="LAB", scan=CONFIG,
            network=None, **expected):
    return cli(relay, calls, "database", "barcode-add", network or "//" + project + "/CustomA",
               "--project", project, "--barcode", scan, "--catalog", catalog,
               *arguments, **expected)


def no_mutation(call):
    assert not any(command.startswith(MUTATIONS) for command in call["commands"]), call


def assert_new_unit(owner, backend, before, call, address, name, *, network="CustomA",
                    serial="12345678.9012"):
    """Derive the issued identity from literal wire, then independently read it."""
    additions = [index for index, command in enumerate(call["commands"])
                 if command.startswith("DBADDSAFE ")]
    assert len(additions) == 1, call
    index = additions[0]
    assert call["commands"][index] == f"DBADDSAFE //LAB/{network} Unit {address} {name}"
    assert call["statuses"][index] == 301
    issued = re.fullmatch(r"OID=([0-9a-fA-F-]{36})", call["terminals"][index])
    assert issued is not None, call
    oid = issued[1]
    assert str(uuid.UUID(oid)) == oid.lower()
    path = f"//LAB/{network}/p/{address}"
    expected = {"OID": oid, "TagName": name, "Address": str(address), "UnitName": "NEWUNIT",
                "UnitType": "KEYBL5", "SerialNumber": serial, "CatalogNumber": "5031NL",
                "FirmwareVersion": "1.2.00"}
    assert len(call["documents"]) == 1, call
    submitted = call["documents"][0]
    assert submitted["command"] == "DBSETXML " + path, call
    assert fields(submitted["body"]) == expected
    submitted_root = ET.fromstring(submitted["body"])
    assert [child.tag for child in submitted_root] == list(FIELDS)
    assert not submitted_root.attrib and not any(child.attrib for child in submitted_root)
    actual = document(owner, path)
    assert_plain_unit(actual, expected)
    assert_plain_unit(document(owner, "!" + oid), expected)
    after = snapshot(owner, backend)
    assert without_unit(after["LAB"], oid) == before["LAB"]
    assert {key: value for key, value in after.items() if key != "LAB"} == {
        key: value for key, value in before.items() if key != "LAB"}
    before_oids = [node.text for node in ET.fromstring(before["LAB"]).iter("OID")]
    after_oids = [node.text for node in ET.fromstring(after["LAB"]).iter("OID")]
    assert len(set(after_oids)) == len(after_oids)
    assert set(after_oids) == set(before_oids) | {oid}
    writes = [command for command in call["commands"] if command.startswith(MUTATIONS)]
    assert writes == [f"DBADDSAFE //LAB/{network} Unit {address} {name}", "DBSETXML " + path]
    initialized = call["commands"].index("DBSETXML " + path)
    assert call["statuses"][initialized] == 301 and call["terminals"][initialized] == "OID=" + oid
    for index, command in enumerate(call["commands"]):
        if command.startswith("DBGET " + path + "/") or command == "DBGET !" + oid + "/OID":
            field = command.rsplit("/", 1)[1]
            selector = command.removeprefix("DBGET ")
            if network == "11":
                # This restored Network is assigned to numeric Network11;
                # qualified scalar reads use its retained tag route. This does
                # not exercise the legacy bare/runtime-only scalar route.
                case = vector()["retained_numeric_scalar_reply"]["oid" if field == "OID" else "other_fields"]
                assert call["statuses"][index] == case["status"]
                assert call["reply_lines"][index] == [expand(row, {
                    "issued": oid, "exact_selector": selector, "planned_value": expected[field],
                }) for row in case["rows"]]
            else:
                assert call["statuses"][index] == 342
                assert call["reply_lines"][index] == ["342 " + selector + "=" + expected[field]]
    return oid, after


def selected_binary(variable):
    supplied = os.environ.get(variable)
    if not supplied:
        pytest.skip(f"Select {variable} for the owned barcode database journey")
    binary = Path(supplied).resolve()
    assert binary.is_file() and os.access(binary, os.X_OK), f"Invalid configured {variable}: {binary}"
    return binary


class FaultGate(RecordedGate):
    """One owned relay fault at a selected command; backend bytes stay literal.

    A refusal suppresses the request and injects one explicit terminal. A lost
    receipt forwards the complete request, records the actual backend terminal,
    then closes the caller's connection without forwarding that terminal. No
    fault simulates a second execution or adopts an external endpoint.
    """
    def __init__(self, target, verb, mode, *, occurrence=1, callback=None):
        super().__init__(target)
        self.verb, self.mode, self.occurrence = verb, mode, occurrence
        self.callback = callback
        self.matches = 0

    def _relay(self, peer, row):
        row["backend_response_hex"] = ""
        row["forwarded_request_hex"] = ""
        buffers = {}
        target_tag = suppressed_delimiter = None

        def send_reply(data):
            row["response_hex"] += data.hex()
            peer.sendall(data)

        try:
            with peer, socket.create_connection(self.target, timeout=5) as remote:
                peer.settimeout(5)
                remote.settimeout(5)
                buffers = {peer: b"", remote: b""}
                while not self.stop.is_set():
                    readable, _, _ = select.select([peer, remote], [], [], .05)
                    for source in readable:
                        data = source.recv(65536)
                        if not data:
                            return
                        buffers[source] += data
                        while b"\n" in buffers[source]:
                            line, buffers[source] = buffers[source].split(b"\n", 1)
                            wire = line + b"\n"
                            text = line.rstrip(b"\r").decode("utf-8")
                            if source is peer:
                                row["request_hex"] += wire.hex()
                                if suppressed_delimiter is not None:
                                    if text == suppressed_delimiter:
                                        suppressed_delimiter = None
                                        send_reply(f"[{target_tag}] 408 Controlled barcode refusal\r\n".encode())
                                    continue
                                match = re.fullmatch(r"\[([^]]+)\] (.+)", text)
                                if match and match[2].startswith(self.verb + " "):
                                    self.matches += 1
                                    if self.matches == self.occurrence:
                                        target_tag = match[1]
                                        row["fault"] = {"command": match[2], "tag": target_tag,
                                                        "mode": self.mode, "occurrence": self.matches}
                                        if self.mode == "refuse":
                                            if " << " in match[2]:
                                                suppressed_delimiter = match[2].rsplit(" << ", 1)[1]
                                            else:
                                                send_reply(f"[{target_tag}] 408 Controlled barcode refusal\r\n".encode())
                                            continue
                                row["forwarded_request_hex"] += wire.hex()
                                remote.sendall(wire)
                            else:
                                row["backend_response_hex"] += wire.hex()
                                terminal = re.fullmatch(r"\[([^]]+)\] \d{3} .*", text)
                                if terminal and terminal[1] == target_tag:
                                    if self.mode == "drop":
                                        row["lost_backend_terminal_hex"] = wire.hex()
                                        return
                                    if self.mode == "change":
                                        assert self.callback is not None
                                        self.callback()
                                        row["controlled_change_completed"] = True
                                send_reply(wire)
        except (OSError, ValueError) as error:
            self.errors.append(type(error).__name__)
        finally:
            row["closed"] = True
            row["done"].set()


@contextmanager
def journey(backend, variable, tmp_path, *, auth_file=None, trap_endpoint=None):
    binary = selected_binary(variable)
    work = associated_work(tmp_path, "initial")
    catalog = tmp_path / "synthetic-catalogue.xml"
    catalog.write_text(CATALOG_XML, encoding="utf-8")
    catalog.chmod(0o600)
    evidence = {"format": "cbus-cgate-barcode-database-owned-v1", "backend": backend,
                "original_execution": False, "physical_acceptance": False,
                "binary_sha256": digest(binary.read_bytes()), "calls": [], "processes": [],
                "wires": [], "catalog_sha256": digest(catalog.read_bytes()),
                "vector_sha256": digest(VECTOR_PATH.read_bytes())}
    relay = None
    try:
        with (no_contact_trap() if trap_endpoint is None else nullcontext(trap_endpoint)) as trap:
            with owned_backend(backend, binary, work, auth_file=auth_file) as (endpoint, record):
                evidence["processes"].append(record)
                with CGateClient(*endpoint, timeout=15) as owner, RecordedGate(endpoint) as relay:
                    yield owner, relay, catalog, evidence, work, trap, binary
            if trap_endpoint is None:
                evidence["closed_graph_trap_contacts"] = 0
    finally:
        if relay is not None:
            evidence["wires"] = relay.evidence()
        associated_evidence(tmp_path / "barcode-database-evidence.json", evidence)


def assert_result(value, phase, *, applied=False, created=False, accepted=False):
    assert value["format"] == "cbus-cgate-barcode-add-v1", value
    assert value["phase"] == phase, value
    assert value["applied"] is applied and value["created"] is created, value
    assert value["accepted"] is accepted, value
    assert value["project_saved"] is False and value["hardware_programmed"] is False, value


def assert_case(call, case, roles):
    assert call["commands"] == [expand(command, roles) for command in case["requests"]], call
    assert call["statuses"] == case["statuses"], call


@pytest.mark.parametrize("backend,variable", [
    ("cgate-mock", "CBUS_CGATE_MOCK_BIN"), ("cmqttd", "CBUS_CMQTTD_BIN"),
], ids=["mock", "daemon"])
def test_public_barcode_named_unit_preservation_and_lifecycle(backend, variable, tmp_path):
    expectations = vector()
    evidence = None
    try:
        with no_contact_trap() as restart_trap:
            with journey(backend, variable, tmp_path, trap_endpoint=restart_trap) as (owner, relay, catalog, evidence, work, trap, binary):
                roles = seed(owner, work, trap)
                preserve_difficult_siblings(owner, roles)
                evidence["oid_roles"] = roles
                before = snapshot(owner, backend)
                evidence["before"] = before
                state_before = (work / "state.json").read_bytes() if backend == "cmqttd" else None
                value, call = barcode(relay, evidence["calls"], catalog)
                assert_result(value, "planned")
                assert value["mode"] == "preview"
                assert value["plan"]["action"] == "add" and value["plan"]["would_change"] is True
                assert value["plan"]["snapshot_sha256"] == digest(before["LAB"])
                assert value["plan"]["catalog_sha256"] == digest(catalog.read_bytes())
                assert value["plan"]["unit"] == "//LAB/CustomA/p/2"
                assert value["plan"]["fields"] == expectations["new_fields"]
                assert_case(call, expectations["preview"], roles)
                no_mutation(call)
                assert_unchanged(owner, backend, before)
                if state_before is not None:
                    assert (work / "state.json").read_bytes() == state_before

                for case in expectations["selections"]:
                    value, call = barcode(relay, evidence["calls"], catalog,
                                          *case.get("options", []), scan=case["barcode"])
                    assert_result(value, case["phase"], accepted=case["action"] == "selected_existing")
                    assert value["plan"]["action"] == case["action"]
                    assert value["plan"]["would_change"] is False
                    if case["action"] == "selected_existing":
                        assert value["plan"]["unit"] == "//LAB/Neighbor/p/9"
                        assert value["plan"]["oid"] == roles["far"]
                    else:
                        assert [warning["toolkit_message_id"] for warning in value["plan"]["warnings"]] == [2096]
                    assert_case(call, expectations["preview"], roles)
                    no_mutation(call)
                    assert_unchanged(owner, backend, before)
                    if state_before is not None:
                        assert (work / "state.json").read_bytes() == state_before

                value, call = barcode(relay, evidence["calls"], catalog, "--apply", "--exclusive-project")
                assert_result(value, "complete", applied=True, created=True, accepted=True)
                oid, added = assert_new_unit(owner, backend, before, call, 2, "NEWUNIT")
                roles["issued"] = oid
                assert value["database_write"]["oid"] == oid
                assert value["database_write"]["path"] == "//LAB/CustomA/p/2"
                assert all(value["readback"][key] is True for key in (
                    "unit_verified", "scalars_verified", "unrelated_project_preserved"))
                assert_case(call, expectations["apply"], roles)
                evidence["after_add"] = added
                assert document(owner, "!" + roles["one"]) == document(owner, "//LAB/CustomA/p/1")

                # An accepted database edit has not crossed a project-save boundary.
                # The caller performs these separate public lifecycle commands.
                for case in expectations["lifecycle"]:
                    value, call = cli(relay, evidence["calls"], "project", *case["argv"])
                    assert_case(call, case, roles)
                    assert value["status"] == 200
                assert owner.command("PROJECT USE LAB").code == 200
                saved = snapshot(owner, backend)
                assert saved == added
                evidence["saved_reload"] = saved
                value, call = barcode(relay, evidence["calls"], catalog, "--apply", "--exclusive-project")
                assert_result(value, "selected_existing", accepted=True)
                assert value["plan"]["oid"] == oid and value["plan"]["unit"] == "//LAB/CustomA/p/2"
                no_mutation(call)
                assert_case(call, expectations["preview"], roles)
                assert_unchanged(owner, backend, saved)

            if backend == "cmqttd":
                restart = associated_work(tmp_path, "restart")
                with owned_backend(backend, binary, restart, state_path=work / "state.json") as (endpoint, record):
                    evidence["processes"].append(record)
                    with CGateClient(*endpoint, timeout=15) as owner, RecordedGate(endpoint) as restarted_relay:
                        assert owner.command("PROJECT USE LAB").code == 200
                        assert snapshot(owner, backend) == saved
                        value, call = barcode(restarted_relay, evidence["calls"], catalog,
                                              "--apply", "--exclusive-project")
                        assert_result(value, "selected_existing", accepted=True)
                        assert value["plan"]["oid"] == oid
                        no_mutation(call)
                        assert_case(call, expectations["preview"], roles)
                    evidence["wires"].extend(restarted_relay.evidence())
                evidence["json_restart_verified"] = True
        evidence["closed_graph_trap_contacts"] = 0
    finally:
        if evidence is not None:
            associated_evidence(tmp_path / "barcode-database-evidence.json", evidence)


@pytest.mark.parametrize("backend,variable", [
    ("cgate-mock", "CBUS_CGATE_MOCK_BIN"), ("cmqttd", "CBUS_CMQTTD_BIN"),
], ids=["mock", "daemon"])
def test_public_barcode_numeric_unit_issued_identity(backend, variable, tmp_path):
    expectations = vector()
    with journey(backend, variable, tmp_path) as (owner, relay, catalog, evidence, work, trap, _):
        roles = seed(owner, work, trap, numeric=True)
        evidence["oid_roles"] = roles
        before = snapshot(owner, backend)
        evidence["before"] = before
        value, call = barcode(relay, evidence["calls"], catalog, "--apply", "--exclusive-project",
                              "--address", "0", "--tag-name", "Hall & Café", network="//LAB/11")
        assert_result(value, "complete", applied=True, created=True, accepted=True)
        oid, after = assert_new_unit(owner, backend, before, call, 0, "Hall & Café", network="11")
        roles["issued"] = oid
        assert_case(call, expectations["numeric_apply"], roles)
        assert value["plan"]["automatic_address"] == 2 and value["plan"]["address"] == 0
        assert value["database_write"]["oid"] == oid
        assert call["commands"].count("DBGETXML //LAB/11/p/0") == 2
        assert call["commands"].count("DBGET !" + oid + "/OID") == 1
        evidence["after_add"] = after


@pytest.mark.parametrize("backend,variable", [
    ("cgate-mock", "CBUS_CGATE_MOCK_BIN"), ("cmqttd", "CBUS_CMQTTD_BIN"),
], ids=["mock", "daemon"])
def test_public_barcode_guards_are_read_only(backend, variable, tmp_path):
    expectations = vector()
    with journey(backend, variable, tmp_path) as (owner, relay, catalog, evidence, work, trap, _):
        roles = seed(owner, work, trap)
        evidence["oid_roles"] = roles
        before = snapshot(owner, backend)
        evidence["before"] = before
        state = (work / "state.json").read_bytes() if backend == "cmqttd" else None
        for case in expectations["refusals"]:
            value, call = barcode(relay, evidence["calls"], catalog,
                                  *case.get("options", []), scan=case.get("barcode", CONFIG),
                                  network=case.get("network"), expected=1,
                                  connections=case["connections"])
            assert case["error_contains"] in value["error"], value
            assert_case(call, case, roles)
            no_mutation(call)
            assert_unchanged(owner, backend, before)
            if state is not None:
                assert (work / "state.json").read_bytes() == state

        def controlled_change():
            assert owner.command("DBSETSAFE //LAB/Neighbor/TagName External controlled change").code == 200

        with FaultGate(relay.target, "DBGETXML", "change", callback=controlled_change) as stale:
            value, call = barcode(stale, evidence["calls"], catalog, "--apply", "--exclusive-project",
                                  expected=1)
            failure = value["barcode_database_evidence"]
            assert failure["phase"] == expectations["stale_between_reads"]["phase"]
            assert_case(call, expectations["stale_between_reads"], roles)
            assert failure["database_write"]["add_attempted"] is False
            assert failure["database_write"]["document_attempted"] is False
            assert failure["database_write"]["outcome_uncertain"] is False
            no_mutation(call)
            assert stale.rows[0]["controlled_change_completed"] is True
        evidence["stale_wires"] = stale.evidence()
        changed = snapshot(owner, backend)
        assert graph(changed["LAB"]) == graph(before["LAB"].replace(
            "<TagName>Neighbor label</TagName>", "<TagName>External controlled change</TagName>"))
        assert {key: value for key, value in changed.items() if key != "LAB"} == {
            key: value for key, value in before.items() if key != "LAB"}
        evidence["after_controlled_stale"] = changed


def test_public_barcode_owned_login_denial_and_positive_apply(tmp_path):
    expectations = vector()
    token = uuid.uuid4().hex + uuid.uuid4().hex
    auth_file = tmp_path / "owned-auth.token"
    auth_file.write_text(token + "\n", encoding="utf-8")
    auth_file.chmod(0o600)
    with journey("cmqttd", "CBUS_CMQTTD_BIN", tmp_path, auth_file=auth_file) as (
            owner, relay, catalog, evidence, work, trap, _):
        assert owner.command("LOGIN " + token).code == 200
        roles = seed(owner, work, trap)
        evidence["oid_roles"] = roles
        before = snapshot(owner, "cmqttd")
        evidence["before"] = before
        state = (work / "state.json").read_bytes()
        value, call = barcode(relay, evidence["calls"], catalog, "--apply", "--exclusive-project",
                              expected=1)
        failure = value["barcode_database_evidence"]
        assert failure["phase"] == "add"
        assert "420" in value["error"] and failure["database_write"]["add_attempted"] is True
        assert failure["database_write"]["add_confirmed"] is False
        assert failure["database_write"]["document_attempted"] is False
        assert failure["database_write"]["outcome_uncertain"] is False
        assert_case(call, expectations["auth_denied"], roles)
        assert_unchanged(owner, "cmqttd", before)
        assert (work / "state.json").read_bytes() == state

        wrong_file = tmp_path / "wrong-owned-auth.token"
        wrong_file.write_text("wrong-owned-token\n", encoding="utf-8")
        wrong_file.chmod(0o600)
        value, call = barcode(relay, evidence["calls"], catalog, "--apply", "--exclusive-project",
                              "--auth-token-file", wrong_file, expected=1)
        assert call["commands"] == ["LOGIN wrong-owned-token"] and call["statuses"] == [420]
        assert value["barcode_database_evidence"]["database_write"]["add_attempted"] is False
        assert "wrong-owned-token" not in json.dumps(value) + call["stdout"] + call["stderr"]
        assert value["barcode_database_evidence"]["commands"] == ["LOGIN <redacted>"]
        assert_unchanged(owner, "cmqttd", before)
        assert (work / "state.json").read_bytes() == state

        value, call = barcode(relay, evidence["calls"], catalog, "--apply", "--exclusive-project",
                              "--auth-token-file", auth_file)
        assert_result(value, "complete", applied=True, created=True, accepted=True)
        oid, after = assert_new_unit(owner, "cmqttd", before, call, 2, "NEWUNIT")
        roles.update(issued=oid, owned_token=token)
        assert_case(call, expectations["auth_apply"], roles)
        assert token not in json.dumps(value) and token not in call["stdout"] + call["stderr"]
        assert value["commands"][0] == "LOGIN <redacted>"
        evidence["after_add"] = after


@pytest.mark.parametrize("backend,variable", [
    ("cgate-mock", "CBUS_CGATE_MOCK_BIN"), ("cmqttd", "CBUS_CMQTTD_BIN"),
], ids=["mock", "daemon"])
def test_public_barcode_failure_is_exact_once_without_rollback(backend, variable, tmp_path):
    expectations = vector()
    for case in expectations["failures"]:
        case_path = associated_work(tmp_path, case["id"])
        with journey(backend, variable, case_path) as (owner, relay, catalog, evidence, work, trap, _):
            roles = seed(owner, work, trap)
            evidence["oid_roles"] = roles
            before = snapshot(owner, backend)
            evidence["before"] = before
            state_before = (work / "state.json").read_bytes() if backend == "cmqttd" else None
            with FaultGate(relay.target, case["verb"], case["mode"],
                           occurrence=case.get("occurrence", 1)) as fault:
                value, call = barcode(fault, evidence["calls"], catalog,
                                      "--apply", "--exclusive-project", expected=1,
                                      complete=case["mode"] != "drop")
                failure = value["barcode_database_evidence"]
                assert failure["format"] == "cbus-cgate-barcode-add-v1"
                assert failure["phase"] == case["phase"]
                assert failure["project_saved"] is False and failure["hardware_programmed"] is False
                for name, expected in case["database_write"].items():
                    assert failure["database_write"][name] is expected, (name, failure)
                mutations = [command for command in call["commands"] if command.startswith(MUTATIONS)]
                assert sum(command.startswith("DBADDSAFE ") for command in mutations) == 1
                assert sum(command.startswith("DBSETXML ") for command in mutations) == case["document_count"]
                assert all(command.startswith(("DBADDSAFE ", "DBSETXML ")) for command in mutations)
                assert call["commands"].count("PROJECT USE LAB") == 1
                assert len(fault.rows) == 1 and fault.rows[0]["fault"]["mode"] == case["mode"]
            evidence["fault_wires"] = fault.evidence()
            after = snapshot(owner, backend)
            evidence["after_fault"] = after
            if case["created_in_backend"]:
                root = ET.fromstring(after["LAB"])
                added = [unit for net in root.iter("Network") if net.findtext("Address") == "CustomA"
                         for unit in net.findall("Unit") if unit.findtext("Address") == "2"]
                assert len(added) == 1
                oid = added[0].findtext("OID")
                assert without_unit(after["LAB"], oid) == before["LAB"]
                assert {key: value for key, value in after.items() if key != "LAB"} == {
                    key: value for key, value in before.items() if key != "LAB"}
                actual = document(owner, "!" + oid)
                if case["initialized_in_backend"]:
                    expected = {"OID": oid, "TagName": "NEWUNIT", "Address": "2", **expectations["new_fields"]}
                    assert_plain_unit(actual, expected)
                else:
                    assert_plain_unit(actual, {"OID": oid, "TagName": "NEWUNIT", "Address": "2", "UnitName": "NEWUNIT"},
                                      order=("OID", "TagName", "Address", "UnitName"))
            else:
                assert after == before
                if state_before is not None:
                    assert (work / "state.json").read_bytes() == state_before
            # Persist the post-fault independent observation before teardown;
            # no test cleanup deletes or repairs a partially created Unit.
            associated_evidence(case_path / "barcode-database-evidence.json", evidence)
