"""Public conversion XML guards on explicitly selected owned Rust backends.

The expected opaque XML is literal, and the complete-tree oracle retains every
DOM character node. It does not import the production comparison function or
the legacy graph comparator. Read projection faults alter only returned XML;
they are not backend mutations, original-server captures, or physical tests.
"""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
import select
import socket
import uuid
from xml.dom import Node, minidom
from xml.sax.saxutils import quoteattr

import pytest

from cbus_toolkit.cgate import CGateClient
from cbus_toolkit.file_transfer import prepare_upload, upload
from test_cgate_barcode_database_interop import FaultGate, selected_binary
from test_cgate_named_database_interop import (
    RecordedGate, STARTUP, associated_evidence, associated_work, no_contact_trap, owned_backend,
)
from test_cgate_toolkit_tweaker_interop import (
    BACKENDS, apply_flags, cli as create_cli, document, state as create_state,
)
from test_cgate_toolkit_tweaker_lifecycle_interop import (
    cli as replace_cli, flags as replace_flags, state as replace_state,
)
from test_toolkit_tweaker_workflow import profile_files


FIXTURE = Path(__file__).resolve().parents[1] / "research/fixtures/conversion-xml-space-preservation.xml"
EVIDENCE_NAME = "conversion-xml-preservation-evidence.json"
NS = "urn:cbus:synthetic:xml-space"
XML_NS = "http://www.w3.org/XML/1998/namespace"
# DIMDN8 -> DIMDU4's retained direct assignments with the public synthetic
# schema: the source maximums 1..8 become the four target power-up delays;
# interlocking becomes four, and the target maximum defaults remain zero.
EXPECTED_PP = {
    "Application": "56 255", "UnitAddress": "20", "UnitName": "SOURCE  ",
    "Project": "WFTEST  ", "GroupAddress": "0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0",
    "MaxDimmingLevel": "0 0 0 0", "PowerUpDelay": "1 2 3 4", "InterLockingChannel": "4",
}
READ_ONLY = ("DBGETXML ", "PROJECT USE WFTEST", "PP LOCK ", "PP START ", "PP LOAD ",
             "DBGET ", "PP GET ", "PP END ", "PP UNLOCK ")
PREVIEW_ONLY = READ_ONLY + ("PP NEW ", "PROJECT DIR", "GET //")
XML_POLICY = {"formatting_only_container_indentation_compared": False,
              "xml_space_preserve_override_enforced": True,
              "mixed_content_text_whitespace_compared": True,
              "whitespace_only_leaf_values_compared": True}


def digest(data):
    return hashlib.sha256(data.encode() if isinstance(data, str) else data).hexdigest()


def parse(text):
    return minidom.parseString(text)


def exact(node):
    """Literal DOM equality, including all whitespace, comments and PIs.

    No inherited-space policy is inferred here. Positive formatting admission
    is an explicitly selected Reset-node transformation in the relay below.
    """
    if node.nodeType == Node.ELEMENT_NODE:
        return (node.nodeType, node.namespaceURI, node.tagName,
                tuple(sorted(node.attributes.items())), tuple(exact(c) for c in node.childNodes))
    if node.nodeType in (Node.TEXT_NODE, Node.CDATA_SECTION_NODE, Node.COMMENT_NODE):
        return (node.nodeType, node.data)
    return (node.nodeType, getattr(node, "target", None), getattr(node, "data", None))


def tree(text):
    return exact(parse(text).documentElement)


def elements(node, name):
    return [c for c in node.childNodes if c.nodeType == Node.ELEMENT_NODE and c.tagName == name]


def field(node, name):
    rows = elements(node, name)
    assert len(rows) == 1, (name, node.toxml())
    assert all(c.nodeType in (Node.TEXT_NODE, Node.CDATA_SECTION_NODE) for c in rows[0].childNodes)
    return "".join(c.data for c in rows[0].childNodes)


def set_field(node, name, value):
    rows = elements(node, name)
    assert len(rows) == 1, (name, node.toxml())
    for child in list(rows[0].childNodes):
        rows[0].removeChild(child)
    rows[0].appendChild(node.ownerDocument.createTextNode(value))


def unit(doc, oid):
    rows = [n for n in doc.getElementsByTagName("Unit") if field(n, "OID") == oid]
    assert len(rows) == 1, (oid, doc.toxml())
    return rows[0]


def without_unit(text, oid):
    doc = parse(text)
    node = unit(doc, oid)
    node.parentNode.removeChild(node)
    return exact(doc.documentElement)


def normalized_backup(text):
    doc = parse(text)
    project = elements(doc.documentElement, "Project")
    assert len(project) == 1
    assert field(project[0], "Address") == field(project[0], "TagName") == "BACKUP"
    set_field(project[0], "Address", "WFTEST")
    set_field(project[0], "TagName", "WFTEST")
    return exact(doc.documentElement)


def opaque(doc, local):
    rows = doc.getElementsByTagNameNS(NS, local)
    assert len(rows) == 1, (local, doc.toxml())
    return rows[0]


def change_projection(text, kind):
    """One named literal edit, independent of the production comparator."""
    doc = parse(text)
    if kind == "default-formatting":
        node = opaque(doc, "Reset")
        assert node.getAttributeNS(XML_NS, "space") == "default"
        following = exact(node.nextSibling)
        chosen = [c for c in node.childNodes if c.nodeType == Node.TEXT_NODE and c.data == "   "]
        assert len(chosen) == 3
        for child in chosen:
            node.removeChild(child)
        assert exact(node.nextSibling) == following == (Node.TEXT_NODE, "  ")
    elif kind == "preserved-separator":
        node = opaque(doc, "Inherited")
        chosen = [c for c in node.childNodes if c.nodeType == Node.TEXT_NODE and c.data == "  "]
        assert len(chosen) == 1
        node.removeChild(chosen[0])
    elif kind == "mixed-separator":
        node = opaque(doc, "Mixed")
        assert node.getAttributeNS(XML_NS, "space") == "default"
        chosen = [c for c in node.childNodes if c.nodeType == Node.TEXT_NODE and c.data == "  "]
        assert len(chosen) == 1 and node.firstChild.data == "before" and node.lastChild.data == "after"
        node.removeChild(chosen[0])
    elif kind == "preserve-parent-tail":
        child = opaque(doc, "Reset")
        assert child.getAttributeNS(XML_NS, "space") == "default"
        assert child.parentNode.getAttributeNS(XML_NS, "space") == "preserve"
        assert child.nextSibling.nodeType == Node.TEXT_NODE and child.nextSibling.data == "  "
        child.parentNode.removeChild(child.nextSibling)
    elif kind == "cdata":
        node = opaque(doc, "CDATA")
        assert node.firstChild.nodeType == Node.CDATA_SECTION_NODE and node.firstChild.data == "   "
        node.removeChild(node.firstChild)
    elif kind == "leaf":
        node = opaque(doc, "Leaf")
        assert len(node.childNodes) == 1 and node.firstChild.nodeType == Node.TEXT_NODE
        assert node.firstChild.data == "   "
        node.removeChild(node.firstChild)
    else:
        raise AssertionError("Unknown controlled XML projection")
    result = doc.documentElement.toxml()
    assert tree(text) != tree(result), "The controlled literal projection did not change XML data"
    return result


class XMLProjectionGate(RecordedGate):
    """Alter one returned XML snippet after an actual selected request.

    Every upstream request and reply is retained separately from bytes sent to
    the CLI. The trigger is the actual successful command terminal, not time,
    guessed packet boundaries or an implementation-produced expected tree.
    """
    def __init__(self, target, path, kind, *, after=None, occurrence=1, enabled=True):
        super().__init__(target)
        self.path, self.kind, self.after, self.occurrence = path, kind, after, occurrence
        self.armed = after is None
        self.matches = 0
        self.enabled = enabled
        self.saved_cursor = 0

    def _relay(self, peer, row):
        row.update(backend_response_hex="", forwarded_request_hex="", projection_changes=[])
        commands, buffers = {}, {}
        try:
            with peer, socket.create_connection(self.target, timeout=5) as remote:
                peer.settimeout(5)
                remote.settimeout(5)
                buffers = {peer: b"", remote: b""}
                while not self.stop.is_set():
                    for source in select.select([peer, remote], [], [], .05)[0]:
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
                                row["forwarded_request_hex"] += wire.hex()
                                match = re.fullmatch(r"\[([^]]+)\] (.+)", text)
                                assert match, text
                                assert match[1] not in commands, "Reused request tag"
                                commands[match[1]] = match[2]
                                remote.sendall(wire)
                                continue
                            row["backend_response_hex"] += wire.hex()
                            match = re.fullmatch(r"\[([^]]+)\] (\d{3})([- ])(.*)", text)
                            if match and match[1] in commands:
                                command = commands[match[1]]
                                if (self.after is not None and command.startswith(self.after)
                                        and match[3] == " " and int(match[2]) < 400):
                                    self.armed = True
                                if (self.enabled and self.armed and command == "DBGETXML " + self.path
                                        and match[2] == "347" and match[4].startswith("<")
                                        and not match[4].startswith("<?xml")):
                                    self.matches += 1
                                    if self.matches == self.occurrence:
                                        changed = change_projection(match[4], self.kind)
                                        suffix = b"\r\n" if wire.endswith(b"\r\n") else b"\n"
                                        wire = (f"[{match[1]}] 347{match[3]}" + changed).encode() + suffix
                                        row["projection_changes"].append({
                                            "command": command, "tag": match[1], "kind": self.kind,
                                            "occurrence": self.matches, "backend_xml": match[4],
                                            "client_xml": changed, "backend_sha256": digest(match[4]),
                                            "client_sha256": digest(changed), "backend_mutation": False,
                                        })
                            row["response_hex"] += wire.hex()
                            peer.sendall(wire)
        except Exception as error:
            self.errors.append(type(error).__name__ + ": " + str(error))
        finally:
            row["closed"] = True
            row["done"].set()


def save_projection(evidence, relay):
    rows = relay.evidence()[relay.saved_cursor:]
    relay.saved_cursor = len(relay.rows)
    evidence.setdefault("controlled_read_projections", []).append(rows)
    changes = [change for row in rows for change in row["projection_changes"]]
    assert len(changes) == 1, rows
    change = changes[0]
    assert change["backend_mutation"] is False and change["backend_sha256"] != change["client_sha256"]
    for row in rows:
        assert row["request_hex"] == row["forwarded_request_hex"] and row["closed"]
    return change


def seed_space(owner, work, trap, profile, evidence):
    """Restore complete synthetic XML before materializing the raw Level.

    No raw owner is re-admitted as a complete Network. Only modeled source
    Unit metadata and OutputChannel scalar data are submitted; unknown Unit
    extensions are not assumed to survive the importer. Opaque Network child
    text and the Network xml:space attribute are checked after admission.
    """
    roles = {name: str(uuid.uuid4()) for name in ("project", "network", "interface", "source",
        "source_channel", "neighbor", "application", "group", "level", "other_project", "other_network", "other_interface")}
    evidence["roles"] = roles
    pp = "".join(f"<PP Name={quoteattr(name)} Value={quoteattr(value)}/>"
                 for name, value in profile["source_values"].items())
    source = (f"<Unit><OID>{roles['source']}</OID><TagName>Source &amp; exact</TagName><Address>20</Address>"
        "<UnitType>DIMDN8</UnitType><UnitName>SOURCE</UnitName><SerialNumber>123456.7</SerialNumber>"
        f"<FirmwareVersion>{profile['source_firmware']}</FirmwareVersion><CatalogNumber>SYNTHETIC</CatalogNumber>"
        f"<OutputChannel><OID>{roles['source_channel']}</OID><TagName>Source channel</TagName><Address>1</Address>"
        "<Description>   </Description><LocationCode>9</LocationCode><ChannelNameCode>7</ChannelNameCode>"
        "</OutputChannel>" + pp + "</Unit>")
    neighbor = (f"<Unit><OID>{roles['neighbor']}</OID><TagName>Unrelated</TagName><Address>22</Address>"
        "<UnitType>KEY1</UnitType><UnitName>NEIGHBOR</UnitName><FirmwareVersion>1.2.67</FirmwareVersion>"
        '<PP Name="OpaqueSetting" Value="multiword &amp; raw Ω"/></Unit>')
    application = (f"<Application><OID>{roles['application']}</OID><Address>56</Address><TagName>Lighting</TagName>"
        f"<Group><OID>{roles['group']}</OID><Address>1</Address><TagName>Raw group</TagName>"
        f'<Level Value="77"><OID>{roles["level"]}</OID><Address>7</Address><TagName>Raw retained</TagName>'
        "<TagsDLT/></Level></Group></Application>")

    def network(key, contents):
        address = "11" if key == "network" else "12"
        interface = "interface" if key == "network" else "other_interface"
        return (f'<Network xml:space="preserve"><OID>{roles[key]}</OID><Address>{address}</Address>'
            f"<NetworkNumber>{address}</NetworkNumber><TagName>Owned{address}</TagName>"
            f"<Interface><OID>{roles[interface]}</OID><InterfaceType>cni</InterfaceType>"
            f"<InterfaceAddress>{trap}</InterfaceAddress></Interface>"
            "<!-- keep network comment --><?owned keep?>" + FIXTURE.read_text().strip() + contents + "</Network>")

    setup = evidence["seed_receipts"] = []
    for body in ("FILE MKDIR Projects", "FILE MKDIR Projects/archived"):
        response = owner.command(body)
        setup.append({"command": body, "status": response.code, "final": response.final})
        assert response.code == 200
    for name, oid, contents in (("WFTEST", roles["project"], network("network", source + neighbor + application)),
            ("OTHER", roles["other_project"], network("other_network", ""))):
        path = work / (name + "-xml-space.xml")
        submitted = ("<Installation><DBVersion>2.3</DBVersion><Project>"
            f"<OID>{oid}</OID><Address>{name}</Address><TagName>{name}</TagName>" + contents + "</Project></Installation>")
        path.write_text(submitted, encoding="utf-8")
        path.chmod(0o600)
        receipt = upload(prepare_upload("Projects/archived/" + path.name, path), owner)
        assert receipt["upload_completed"] and not receipt["project_save_requested"]
        body = f"PROJECT RESTORE {name} {path.name}"
        response = owner.command(body)
        setup.append({"command": body, "status": response.code, "final": response.final,
            "literal_submitted_xml": submitted, "file_sha256": digest(path.read_bytes())})
        assert response.code == 200
    for body in ("PROJECT USE WFTEST", "DBSET //WFTEST/11/56/1/7/Value oops"):
        response = owner.command(body)
        setup.append({"command": body, "status": response.code, "final": response.final})
        assert response.code == 200
    before, other = document(owner), document(owner, "//OTHER")
    actual = parse(before)
    net = next(n for n in actual.getElementsByTagName("Network") if field(n, "Address") == "11")
    assert net.getAttributeNS(XML_NS, "space") == "preserve"
    assert exact(opaque(actual, "Opaque")) == exact(parse(FIXTURE.read_text()).documentElement)
    assert not unit(actual, evidence["roles"]["source"]).hasAttributeNS(XML_NS, "space")
    source_channels = elements(unit(actual, roles["source"]), "OutputChannel")
    assert len(source_channels) == 1
    assert {c.tagName: field(source_channels[0], c.tagName) for c in source_channels[0].childNodes} == {
        "OID": roles["source_channel"], "TagName": "Source channel", "Address": "1",
        "Description": "   ", "LocationCode": "9", "ChannelNameCode": "7"}
    assert actual.getElementsByTagName("Level")[0].getAttribute("Value") == "oops"
    evidence["before_project_xml"], evidence["other_project_xml"] = before, other
    evidence["source_xml"] = document(owner, "//WFTEST/11/p/20")
    evidence["source_parent_xml_space"] = "preserve"
    return before, other


@contextmanager
def space_journey(backend, variable, tmp_path, request):
    binary = selected_binary(variable)
    work = associated_work(tmp_path, "backend")
    specs = tmp_path / "synthetic-specs"
    profile = profile_files(specs, "DIMDN8", "DIMDU4")
    flag = "--unitspec" if backend == "cgate-mock" else "--cgate-unitspec"
    evidence = {"format": "cbus-conversion-xml-preservation-owned-v1", "backend": backend,
        "original_execution": False, "physical_acceptance": False, "binary_sha256": digest(binary.read_bytes()),
        "direct_launch_profile": {"kind": "selected-owned-rust", "binary": {"resolved": str(binary),
            "sha256": digest(binary.read_bytes()), "bytes": binary.stat().st_size},
            "extra_args": [flag, str(specs)], "specifications": {p.name: digest(p.read_bytes()) for p in specs.iterdir()},
            "argv": None}, "specifications": {p.name: digest(p.read_bytes()) for p in specs.iterdir()},
        "calls": [], "processes": [], "wires": []}
    path = tmp_path / EVIDENCE_NAME
    request.node.user_properties.append(("conversion_xml_evidence", str(path)))
    relay = None
    try:
        with no_contact_trap() as trap:
            with owned_backend(backend, binary, work, extra_args=(flag, specs)) as (endpoint, process):
                evidence["direct_launch_profile"]["argv"] = list(process["argv"])
                evidence["processes"].append(process)
                with RecordedGate(endpoint) as relay, CGateClient(*relay.endpoint, timeout=15) as owner:
                    evidence.update(nodeid=request.node.nodeid,
                        proposed_test_module={"sha256": digest(Path(__file__).read_bytes()), "bytes": Path(__file__).stat().st_size},
                        literal_xml_fixture={"sha256": digest(FIXTURE.read_bytes()), "bytes": FIXTURE.stat().st_size},
                        oracle="Literal fixture + complete untrimmed DOM tree + retained direct DIMDN8/DIMDU4 assignments",
                        scope={"original_execution": False, "native_xml_persistence_acceptance": False,
                            "physical_acceptance": False, "controlled_projection_is_backend_mutation": False})
                    before, other = seed_space(owner, work, trap, profile, evidence)
                    yield owner, relay, evidence, specs, profile, endpoint, before, other
        evidence["closed_graph_trap_contacts"] = 0
        for process in evidence["processes"]:
            assert all(process[k] for k in ("listener_owned", "process_cleanup", "listener_closed", "pci_closed", "broker_closed"))
            expected = [("rx", frame) for frame in STARTUP] if backend == "cmqttd" else []
            assert [(r["direction"], bytes.fromhex(r["hex"])) for r in process["pci_wire"]] == expected
        evidence.update(every_owned_process_reaped=True, no_later_pci=True, explicit_closed_graph_trap_zero=True)
    finally:
        if relay is not None:
            evidence["wires"] = relay.evidence()
        associated_evidence(path, evidence)


def assert_target(owner, evidence, oid, *, replacement):
    raw = document(owner, "//WFTEST/11/p/" + ("20" if replacement else "21"))
    root = parse(raw).documentElement
    assert root.tagName == "Unit" and not root.attributes.items()
    scalar = {c.tagName: field(root, c.tagName) for c in root.childNodes
              if c.nodeType == Node.ELEMENT_NODE and c.tagName != "PP"}
    expected = {"OID": oid, "TagName": "Source & exact" if replacement else "Replacement & Ω",
                "Address": "20" if replacement else "21", "UnitType": "DIMDU4",
                "UnitName": "SOURCE" if replacement else "DIMDU4", "FirmwareVersion": "2.7.00",
                "CatalogNumber": "TARGET" if replacement else "SYNTHETIC"}
    if replacement:
        expected.update(Description="", SerialNumber="123456.7")
    assert scalar == expected, (scalar, expected, raw)
    pp = elements(root, "PP")
    assert [n.getAttribute("Name") for n in pp] == list(EXPECTED_PP)
    assert {n.getAttribute("Name"): n.getAttribute("Value") for n in pp} == EXPECTED_PP
    assert all(sorted(n.attributes.keys()) == ["Name", "Value"] and not n.childNodes for n in pp)
    assert all(c.nodeType == Node.ELEMENT_NODE for c in root.childNodes), raw
    assert len(root.childNodes) == len(expected) + len(EXPECTED_PP)
    assert str(uuid.UUID(oid)) == oid.lower() and oid not in evidence["before_project_xml"]
    evidence.setdefault("complete_target_unit_readbacks", []).append(raw)


def assert_graph(owner, evidence, before, other, oid, *, replacement):
    after = document(owner)
    assert_target(owner, evidence, oid, replacement=replacement)
    if replacement:
        assert without_unit(after, oid) == without_unit(before, evidence["roles"]["source"])
        assert not parse(after).getElementsByTagName("OutputChannel")
    else:
        assert without_unit(after, oid) == tree(before)
        assert document(owner, "//WFTEST/11/p/20") == evidence["source_xml"]
    assert document(owner, "//OTHER") == other
    evidence.setdefault("complete_project_checkpoints", []).append(after)
    return after


def backup(owner, evidence, before):
    raw = document(owner, "//BACKUP")
    assert normalized_backup(raw) == tree(before)
    evidence.setdefault("complete_backup_checkpoints", []).append(raw)
    return raw


def assert_read_only(call):
    assert all(c.startswith(READ_ONLY) for c in call["commands"]), call


def assert_preview_only(call):
    assert all(c.startswith(PREVIEW_ONLY) for c in call["commands"]), call


def completed_replace(owner, relay, evidence, specs, profile, before, other, journal):
    preview, call = replace_cli(relay, evidence, specs, profile)
    assert preview["phase"] == "preview_complete" and not journal.exists()
    assert_preview_only(call)
    assert document(owner) == before
    final, call = replace_cli(relay, evidence, specs, profile, extra=replace_flags(preview, journal))
    assert final["phase"] == "complete" and final["accepted"] and not final["outcome_uncertain"]
    assert final["xml_comparison"] == final["creation"]["xml_comparison"] == XML_POLICY
    for key in ("backup_verified", "created", "source_deleted", "readdressed", "project_saved", "reopened",
                "fresh_project_verified", "fresh_pp_verified", "unrelated_project_preserved"):
        assert final[key] is True
    sequence = ["PROJECT COPY WFTEST BACKUP", "DBDELETE //WFTEST/11/p/20",
        "DBSET //WFTEST/11/p/1/Address 20", "PROJECT SAVE WFTEST", "PROJECT CLOSE WFTEST", "PROJECT LOAD WFTEST"]
    assert all(call["commands"].count(c) == 1 for c in sequence)
    assert [call["commands"].index(c) for c in sequence] == sorted(call["commands"].index(c) for c in sequence)
    assert [call["statuses"][call["commands"].index(c)] for c in sequence] == [200] * len(sequence)
    assert sum(c.startswith("DBADDSAFE ") for c in call["commands"]) == 1
    assert sum(c.startswith("PP SAVE_TO_SOURCE ") for c in call["commands"]) == 1
    after = assert_graph(owner, evidence, before, other, final["destination_oid"], replacement=True)
    backup(owner, evidence, before)
    saved = json.loads(journal.read_text())
    assert saved["phase"] == "complete" and all(r["confirmed"] for r in saved["mutation_journal"])
    assert saved["xml_preservation_profile"] == "conversion-semantic-xml-v1"
    assert saved["staged_unit_parent_xml_space"] == "preserve"
    assert journal.stat().st_mode & 0o777 == 0o600
    evidence["complete_lifecycle_journal"] = saved
    return final, after


@pytest.mark.parametrize("backend,variable", BACKENDS, ids=["mock", "daemon"])
def test_public_conversion_creation_preserve_and_default_reset(backend, variable, tmp_path, request):
    with space_journey(backend, variable, tmp_path, request) as (owner, relay, ev, specs, profile, endpoint, before, other):
        with XMLProjectionGate(endpoint, "//WFTEST", "default-formatting", after="PP SAVE_TO_SOURCE ") as projection:
            preview, call = create_cli(projection, ev, specs, profile)
            assert preview["phase"] == "preview_complete" and not preview["created"]
            assert_preview_only(call)
            assert document(owner) == before
            final, call = create_cli(projection, ev, specs, profile, extra=apply_flags(preview))
        change = save_projection(ev, projection)
        assert change["kind"] == "default-formatting"
        assert final["phase"] == "complete" and final["accepted"] and not final["outcome_uncertain"]
        assert final["xml_comparison"] == XML_POLICY
        assert final["verified_expected_parameters"] == {
            n: v if n in ("UnitName", "Project") else list(map(int, v.split())) for n, v in EXPECTED_PP.items()}
        assert not any(final[k] for k in ("project_saved", "source_deleted", "readdressed", "automatic_retries", "rollback_performed"))
        assert sum(c.startswith("DBADDSAFE ") for c in call["commands"]) == 1
        assert sum(c.startswith("PP SAVE_TO_SOURCE ") for c in call["commands"]) == 1
        assert_graph(owner, ev, before, other, final["oid"], replacement=False)


@pytest.mark.parametrize("backend,variable", BACKENDS, ids=["mock", "daemon"])
def test_public_conversion_replace_backup_reopen_and_recovery_preserve(backend, variable, tmp_path, request):
    with space_journey(backend, variable, tmp_path, request) as (owner, relay, ev, specs, profile, _, before, other):
        journal = tmp_path / "attempt.json"
        _, after = completed_replace(owner, relay, ev, specs, profile, before, other, journal)
        retained = journal.read_bytes()
        recovered, call = replace_cli(relay, ev, recovery=True, extra=("--journal", str(journal)))
        assert_read_only(call)
        assert recovered["disposition"] == "observed_replaced" and recovered["persistence_verified"]
        assert recovered["backup_verified_fresh"] and recovered["fresh_pp_verified"]
        assert recovered["journal_xml_preservation_verified"] is True
        assert recovered["read_only_recovery_only"] and not recovered["replay_authorized"]
        assert journal.read_bytes() == retained and document(owner) == after
        backup(owner, ev, before)


@pytest.mark.parametrize("backend,variable", BACKENDS, ids=["mock", "daemon"])
def test_public_conversion_creation_mixed_separator_loss_refuses(backend, variable, tmp_path, request):
    with space_journey(backend, variable, tmp_path, request) as (owner, relay, ev, specs, profile, endpoint, before, other):
        with XMLProjectionGate(endpoint, "//WFTEST", "mixed-separator", after="PP SAVE_TO_SOURCE ") as projection:
            preview, _ = create_cli(projection, ev, specs, profile)
            failed, call = create_cli(projection, ev, specs, profile, expected=1, extra=apply_flags(preview))
        save_projection(ev, projection)
        error = failed["error"]
        failed = create_state(failed)
        assert not failed["accepted"] and failed["created"] and failed["applied"]
        assert "Source or unrelated project data changed" in error
        assert not any(c.startswith(("DBDELETE ", "PROJECT SAVE ", "PROJECT CLOSE ", "PROJECT LOAD ")) for c in call["commands"])
        assert not failed["automatic_retries"] and not failed["rollback_performed"]
        assert_graph(owner, ev, before, other, failed["oid"], replacement=False)


@pytest.mark.parametrize("backend,variable", BACKENDS, ids=["mock", "daemon"])
def test_public_conversion_backup_preserved_separator_loss_stops_before_add(backend, variable, tmp_path, request):
    with space_journey(backend, variable, tmp_path, request) as (owner, relay, ev, specs, profile, endpoint, before, other):
        journal = tmp_path / "attempt.json"
        with XMLProjectionGate(endpoint, "//BACKUP", "preserved-separator") as projection:
            preview, _ = replace_cli(projection, ev, specs, profile)
            failed, call = replace_cli(projection, ev, specs, profile, expected=1, extra=replace_flags(preview, journal))
        save_projection(ev, projection)
        failed = replace_state(failed)
        assert failed["failure_phase"] == "backup" and not failed["backup_verified"] and not failed["created"]
        assert call["commands"].count("PROJECT COPY WFTEST BACKUP") == 1
        assert not any(c.startswith(("DBADD", "DBSET", "DBDELETE", "PP SAVE", "PROJECT SAVE")) for c in call["commands"])
        assert document(owner) == before and document(owner, "//OTHER") == other
        backup(owner, ev, before)
        assert json.loads(journal.read_text())["phase"] == "backup"


@pytest.mark.parametrize("backend,variable", BACKENDS, ids=["mock", "daemon"])
def test_public_conversion_predelete_preserve_parent_tail_loss_keeps_source(backend, variable, tmp_path, request):
    with space_journey(backend, variable, tmp_path, request) as (owner, relay, ev, specs, profile, endpoint, before, other):
        journal = tmp_path / "attempt.json"
        with XMLProjectionGate(endpoint, "//WFTEST", "preserve-parent-tail", after="PP SAVE_TO_SOURCE ", occurrence=2) as projection:
            preview, _ = replace_cli(projection, ev, specs, profile)
            failed, call = replace_cli(projection, ev, specs, profile, expected=1, extra=replace_flags(preview, journal))
        save_projection(ev, projection)
        failed = replace_state(failed)
        assert failed["failure_phase"] == "source_verify" and failed["created"] and not failed["source_deleted"]
        assert not any(c.startswith(("DBDELETE ", "PROJECT SAVE ", "PROJECT CLOSE ", "PROJECT LOAD ")) for c in call["commands"])
        oid = failed["creation"]["oid"]
        after = document(owner)
        assert without_unit(after, oid) == tree(before)
        assert document(owner, "//WFTEST/11/p/20") == ev["source_xml"] and document(owner, "//OTHER") == other
        backup(owner, ev, before)
        ev["retained_scaffold_project_xml"] = after


@pytest.mark.parametrize("backend,variable", BACKENDS, ids=["mock", "daemon"])
def test_public_conversion_reopen_cdata_loss_refuses_completed_receipt(backend, variable, tmp_path, request):
    with space_journey(backend, variable, tmp_path, request) as (owner, relay, ev, specs, profile, endpoint, before, other):
        journal = tmp_path / "attempt.json"
        with XMLProjectionGate(endpoint, "//WFTEST", "cdata", after="PROJECT LOAD WFTEST") as projection:
            preview, _ = replace_cli(projection, ev, specs, profile)
            failed, call = replace_cli(projection, ev, specs, profile, expected=1, extra=replace_flags(preview, journal))
        save_projection(ev, projection)
        failed = replace_state(failed)
        assert failed["failure_phase"] == "readback" and not failed["accepted"] and failed["outcome_uncertain"]
        assert all(failed[k] is True for k in ("created", "source_deleted", "readdressed", "project_saved", "reopened"))
        assert call["commands"].count("PROJECT SAVE WFTEST") == call["commands"].count("PROJECT LOAD WFTEST") == 1
        assert_graph(owner, ev, before, other, failed["creation"]["oid"], replacement=True)
        backup(owner, ev, before)
        assert not failed["rollback_performed"] and not failed["automatic_retries"]


@pytest.mark.parametrize("backend,variable", BACKENDS, ids=["mock", "daemon"])
def test_public_conversion_recovery_current_or_backup_space_loss_read_only(backend, variable, tmp_path, request):
    with space_journey(backend, variable, tmp_path, request) as (owner, relay, ev, specs, profile, endpoint, before, other):
        journal = tmp_path / "attempt.json"
        with XMLProjectionGate(endpoint, "//WFTEST", "preserved-separator", enabled=False) as projection:
            _, after = completed_replace(owner, projection, ev, specs, profile, before, other, journal)
            retained = journal.read_bytes()
            for path, kind in (("//WFTEST", "preserved-separator"), ("//BACKUP", "leaf")):
                projection.path, projection.kind, projection.enabled, projection.matches = path, kind, True, 0
                value, call = replace_cli(projection, ev, recovery=True, extra=("--journal", str(journal)))
                save_projection(ev, projection)
                assert_read_only(call)
                assert value["read_only_recovery_only"] and not value["replay_authorized"] and not value["persistence_verified"]
                assert value["project_saved"] is None
                if path == "//WFTEST":
                    assert value["disposition"] == "conflict" and not value["fresh_pp_verified"]
                else:
                    assert value["disposition"] == "observed_replaced" and value["fresh_pp_verified"]
                    assert not value["backup_verified_fresh"] and "backup_error" in value
                assert journal.read_bytes() == retained and document(owner) == after
                backup(owner, ev, before)


def failed_save(backend, variable, tmp_path, request, mode):
    with space_journey(backend, variable, tmp_path, request) as (owner, relay, ev, specs, profile, endpoint, before, other):
        journal = tmp_path / "attempt.json"
        fault = FaultGate(endpoint, "PROJECT SAVE", mode)
        try:
            with fault:
                # The plan and journal bind the owned endpoint. Keep that
                # endpoint stable; recovery uses a new connection after the
                # selected one-shot fault has been consumed, with no write.
                preview, _ = replace_cli(fault, ev, specs, profile)
                failed, call = replace_cli(fault, ev, specs, profile, expected=1, extra=replace_flags(preview, journal))
                rows = [r for r in fault.evidence() if r.get("fault")]
                assert len(rows) == 1 and fault.matches == 1
                row, selected = rows[0], rows[0]["fault"]
                assert selected["command"] == "PROJECT SAVE WFTEST" and selected["mode"] == mode
                failed = replace_state(failed)
                assert failed["failure_phase"] == "save" and failed["project_saved"] is None
                assert failed["outcome_uncertain"] and not failed["accepted"]
                assert failed["created"] and failed["source_deleted"] and failed["readdressed"]
                assert not failed["reopened"] and not failed["automatic_retries"] and not failed["rollback_performed"]
                assert call["commands"].count("PROJECT SAVE WFTEST") == 1
                assert not any(c.startswith(("PROJECT CLOSE ", "PROJECT LOAD ")) for c in call["commands"])
                target_request = "[" + selected["tag"] + "] " + selected["command"]
                assert bytes.fromhex(row["request_hex"]).decode().splitlines().count(target_request) == 1
                forwarded = bytes.fromhex(row["forwarded_request_hex"]).decode().splitlines()
                if mode == "drop":
                    assert forwarded.count(target_request) == 1
                    terminal = bytes.fromhex(row["lost_backend_terminal_hex"]).decode()
                    assert re.fullmatch(r"\[" + re.escape(selected["tag"]) + r"\] 200 OK\.?\r\n", terminal)
                    assert terminal.encode().hex() in row["backend_response_hex"]
                    assert terminal.encode().hex() not in row["response_hex"]
                    assert call["statuses"][-1] is None
                else:
                    assert target_request not in forwarded and "lost_backend_terminal_hex" not in row
                    assert call["statuses"][-1] == 408
                after = assert_graph(owner, ev, before, other, failed["creation"]["oid"], replacement=True)
                backup(owner, ev, before)
                retained = journal.read_bytes()
                saved = json.loads(retained)
                assert saved["phase"] == "save" and not saved["mutation_journal"][-1]["confirmed"]
                recovered, read = replace_cli(fault, ev, recovery=True, extra=("--journal", str(journal)))
                assert_read_only(read)
                assert recovered["disposition"] == "observed_replaced" and recovered["fresh_pp_verified"]
                assert recovered["backup_verified_fresh"] and recovered["project_saved"] is None
                assert not recovered["persistence_verified"] and not recovered["replay_authorized"]
                assert journal.read_bytes() == retained and document(owner) == after
                ev["after_loss_read_only_recovery"] = recovered
        finally:
            ev["fault_wires"] = fault.evidence()


@pytest.mark.parametrize("backend,variable", BACKENDS, ids=["mock", "daemon"])
def test_public_conversion_save_refusal_retains_preserved_graph(backend, variable, tmp_path, request):
    failed_save(backend, variable, tmp_path, request, "refuse")


@pytest.mark.parametrize("backend,variable", BACKENDS, ids=["mock", "daemon"])
def test_public_conversion_lost_save_200_retains_graph_without_replay(backend, variable, tmp_path, request):
    failed_save(backend, variable, tmp_path, request, "drop")
