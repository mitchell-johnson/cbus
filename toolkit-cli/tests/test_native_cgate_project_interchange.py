"""Cross-server PROJECT ARCHIVE/RESTORE interchange: native C-Gate <-> cmqttd.

Both directions move the synthetic two-network project through each server's
FILE DOWNLOAD/UPLOAD and compare complete DBGETXML Network documents. The
native side is an owned loopback C-Gate 3.4.0.2001 child; cmqttd runs on an
ephemeral loopback port against a scripted PCI simulator. No physical C-Bus
endpoint or site project is used.
"""

from __future__ import annotations

import base64
import gzip
import io
import os
from pathlib import Path
import re
import shutil
import socket
from xml.etree import ElementTree as ET
import zipfile

import pytest

from research.cgate_dbsetxml_unit_differential import owned_server


ROOT = Path(__file__).resolve().parents[2]
NATIVE = bool(os.environ.get("CBUS_LOCAL_CGATE_VENDOR") and os.environ.get("CBUS_CGATE_JAVA"))
CMQTTD = Path(os.environ.get("CBUS_CMQTTD_BIN", ROOT / "rust/target/debug/cmqttd"))

pytestmark = [
    pytest.mark.skipif(not NATIVE, reason="owned native C-Gate is not configured"),
    pytest.mark.skipif(
        not CMQTTD.is_file() or not os.access(CMQTTD, os.X_OK), reason="cmqttd binary is not built"
    ),
    pytest.mark.skipif(shutil.which("sqlite3") is None, reason="cmqttd SQLite restore needs sqlite3"),
]


class Session:
    """One tagged raw C-Gate connection with here-document support."""

    def __init__(self, port: int):
        self.socket = socket.create_connection(("127.0.0.1", port), timeout=10)
        self.socket.settimeout(60)
        self.stream = self.socket.makefile("rwb", buffering=0)
        assert self.stream.readline().startswith(b"201 ")
        self.tag = 0

    def close(self) -> None:
        self.stream.close()
        self.socket.close()

    def call(self, command: str, document: str | None = None) -> list[str]:
        self.tag += 1
        request = f"[{self.tag}] {command}"
        if document is not None:
            request += f" << END{self.tag}\r\n{document}\r\nEND{self.tag}"
        self.stream.write((request + "\r\n").encode())
        final = re.compile(rf"^\[{self.tag}\] \d{{3}} ")
        lines = []
        while True:
            line = self.stream.readline().decode().rstrip("\r\n")
            assert line, f"connection closed during {command}"
            lines.append(line.removeprefix(f"[{self.tag}] "))
            if final.match(line):
                return lines

    def ok(self, command: str, document: str | None = None) -> list[str]:
        lines = self.call(command, document)
        assert lines[-1].startswith(("200 ", "301 ")), (command, lines)
        return lines

    def network(self, path: str) -> str:
        lines = self.call(f"DBGETXML {path}")
        assert lines[-1] == "344 End XML snippet", lines
        return "".join(line[4:] for line in lines if line.startswith("347-")).split("\n", 1)[-1]

    def download(self, path: str) -> bytes:
        lines = self.call(f"FILE DOWNLOAD {path}")
        assert lines[-1].startswith("346 "), lines[-1]
        return base64.b64decode("".join(line[4:] for line in lines if line.startswith("347-")))

    def upload(self, path: str, data: bytes) -> None:
        encoded = base64.b64encode(data).decode()
        rows = "\n".join(encoded[offset:offset + 76] for offset in range(0, len(encoded), 76))
        self.ok(f"FILE UPLOAD {path}", rows)


def build_project(session: Session, project: str) -> None:
    session.ok(f"PROJECT NEW {project}")
    session.ok(f"PROJECT USE {project}")
    for address, name in ((254, "Local"), (253, "Second")):
        session.ok(f"DBCREATENET {address} {name} Cni 127.0.0.1:{address}")
        baseline = ET.fromstring(session.network(f"//{project}/{address}"))
        document = (
            f"<Network><OID>{baseline.findtext('OID')}</OID><TagName>{name}</TagName>"
            f"<Address>{address}</Address><NetworkNumber>{address}</NetworkNumber>"
            f"<Interface><OID>{baseline.findtext('Interface/OID')}</OID><InterfaceType>Cni</InterfaceType>"
            f"<InterfaceAddress>127.0.0.1:{address}</InterfaceAddress></Interface>"
            f"<Unit><OID>11111111-1111-4111-8111-111111111{address}</OID><TagName>Bedroom {address}</TagName>"
            "<Address>20</Address><UnitType>KEYE1</UnitType><CatalogNumber>5031N</CatalogNumber>"
            '<SerialNumber>123.4</SerialNumber><PP Name="UnitAddress" Value="20"/>'
            f'<PP Name="Project" Value="{project}"/><UnitName>Room</UnitName>'
            "<FirmwareVersion>1.2.67</FirmwareVersion></Unit>"
            f"<Application><OID>22222222-2222-4222-8222-222222222{address}</OID><TagName>Lighting</TagName>"
            f"<Address>56</Address><Group><OID>33333333-3333-4333-8333-333333333{address}</OID>"
            "<TagName>Kitchen</TagName><Address>1</Address><TagsDLT><TagDLT>"
            f"<OID>44444444-4444-4444-8444-444444444{address}</OID><LanguageID>1</LanguageID>"
            "<FlavourID>1</FlavourID><TagType>TEXT</TagType><TagValue>Synthetic label</TagValue>"
            "</TagDLT></TagsDLT></Group></Application></Network>"
        )
        session.ok(f"DBSETXML //{project}/{address}", document)


def canonical(xml: str, *, oids: bool = True):
    """Order-insensitive element tree, optionally without OID values."""

    def walk(node):
        children = sorted(walk(child) for child in node if oids or child.tag != "OID")
        return (node.tag, tuple(sorted(node.attrib.items())), (node.text or "").strip(), tuple(children))

    return walk(ET.fromstring(xml))


def networks(session: Session, project: str) -> dict[int, str]:
    return {address: session.network(f"//{project}/{address}") for address in (254, 253)}


@pytest.fixture()
def servers():
    from research.local_cgate import LocalCGate

    with LocalCGate(os.environ["CBUS_LOCAL_CGATE_VENDOR"], java=os.environ["CBUS_CGATE_JAVA"]) as native:
        with owned_server("cmqttd", CMQTTD) as port:
            native_session = Session(native.port)
            cmqttd_session = Session(port)
            try:
                yield native_session, cmqttd_session
            finally:
                native_session.close()
                cmqttd_session.close()


def test_native_sqlite_archives_restore_into_cmqttd_with_oids(servers):
    native, cmqttd = servers
    build_project(native, "XNAT")
    native.ok("PROJECT SAVE XNAT")
    for name in ("nat.zip", "nat.gz", "nat.db"):
        native.ok(f"PROJECT ARCHIVE XNAT {name}")
    native.ok("PROJECT RESTORE XNR nat.zip")
    native.ok("PROJECT LOAD XNR")
    native.ok("PROJECT USE XNR")
    expected = networks(native, "XNR")

    archive = native.download("Projects/archived/nat.zip")
    with zipfile.ZipFile(io.BytesIO(archive)) as container:
        assert [entry.filename for entry in container.infolist()] == ["tagdb.db"]
        assert container.read("tagdb.db").startswith(b"SQLite format 3\x00")
    cmqttd.ok("FILE MKDIR Projects/archived")
    for index, name in enumerate(("nat.zip", "nat.gz", "nat.db")):
        cmqttd.upload(f"Projects/archived/{name}", native.download(f"Projects/archived/{name}"))
        project = f"XC{index}"
        assert cmqttd.call(f"PROJECT RESTORE {project} {name}") == ["200 OK."]
        cmqttd.ok(f"PROJECT USE {project}")
        restored = networks(cmqttd, project)
        for address in (254, 253):
            # SQLite keeps every OID, so the documents match exactly.
            assert canonical(restored[address]) == canonical(expected[address]), (name, address)
    assert cmqttd.call("PROJECT RESTORE XC0 nat.zip")[-1] == (
        "408 Operation failed: Archive failed: Destination file exists"
    )


def test_cmqttd_archives_restore_into_the_native_file_repository(servers):
    native, cmqttd = servers
    build_project(cmqttd, "XCM")
    source = networks(cmqttd, "XCM")
    for name in ("cm.zip", "cm.gz"):
        assert cmqttd.call(f"PROJECT ARCHIVE XCM {name}") == ["200 OK."]
    assert cmqttd.call("PROJECT ARCHIVE XCM cm.db")[-1].startswith("408 Operation failed: Archive failed: cmqttd cannot write")
    archive = cmqttd.download("Projects/archived/cm.zip")
    with zipfile.ZipFile(io.BytesIO(archive)) as container:
        assert [entry.filename for entry in container.infolist()] == ["tagdb.xml"]
        payload = container.read("tagdb.xml")
    modified = re.compile(rb"<Modified>[^<]*</Modified>")
    assert modified.sub(b"", gzip.decompress(cmqttd.download("Projects/archived/cm.gz"))) == modified.sub(b"", payload)
    assert ET.fromstring(payload).tag == "Installation"

    native.ok("FILE MKDIR Projects/archived")
    native.upload("Projects/archived/cm.zip", archive)
    native.upload("Projects/archived/cm.gz", cmqttd.download("Projects/archived/cm.gz"))
    # The default sqlite-file repository requires a tagdb.db entry.
    assert native.call("PROJECT RESTORE XSQ cm.zip")[-1] == (
        "408 Operation failed: Archive failed: Zip entry tagdb.db not found"
    )
    native.ok("REPOSITORY USE 2")
    try:
        for project, name in (("XBZ", "cm.zip"), ("XBG", "cm.gz")):
            native.ok(f"PROJECT RESTORE {project} {name}")
            native.ok(f"PROJECT LOAD {project}")
            native.ok(f"PROJECT USE {project}")
            restored = networks(native, project)
            for address in (254, 253):
                assert canonical(restored[address]) == canonical(source[address]), (name, address)
            native.ok(f"PROJECT CLOSE {project}")
    finally:
        native.call("REPOSITORY USE 1")


def test_native_project_survives_a_cmqttd_round_trip(servers):
    native, cmqttd = servers
    build_project(native, "XRT")
    native.ok("PROJECT SAVE XRT")
    native.ok("PROJECT ARCHIVE XRT rt.zip")
    native.ok("PROJECT RESTORE XRN rt.zip")
    native.ok("PROJECT LOAD XRN")
    native.ok("PROJECT USE XRN")
    original = networks(native, "XRN")
    native.ok("PROJECT CLOSE XRN")

    cmqttd.ok("FILE MKDIR Projects/archived")
    cmqttd.upload("Projects/archived/rt.zip", native.download("Projects/archived/rt.zip"))
    cmqttd.ok("PROJECT RESTORE XRT rt.zip")
    cmqttd.ok("PROJECT ARCHIVE XRT back.zip")
    payload = zipfile.ZipFile(io.BytesIO(cmqttd.download("Projects/archived/back.zip"))).read("tagdb.xml")
    # Unmodeled native project content travels back unchanged.
    root = ET.fromstring(payload)
    assert root.find("Project/Config/Application").text == "cgate"
    assert root.find("InstallationDetail/SystemLocation") is not None

    native.ok("PROJECT CLOSE XRT")
    native.upload("Projects/archived/back.zip", cmqttd.download("Projects/archived/back.zip"))
    native.ok("REPOSITORY USE 2")
    try:
        native.ok("PROJECT RESTORE XBACK back.zip")
        native.ok("PROJECT LOAD XBACK")
        native.ok("PROJECT USE XBACK")
        returned = networks(native, "XBACK")
        for address in (254, 253):
            assert canonical(returned[address]) == canonical(original[address]), address
        native.ok("PROJECT CLOSE XBACK")
    finally:
        native.call("REPOSITORY USE 1")
