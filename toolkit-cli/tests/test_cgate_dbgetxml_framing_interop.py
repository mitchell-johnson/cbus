"""Production Python client and pipelined TCP reads against both Rust services."""

from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import xml.etree.ElementTree as ET

import pytest

from cbus_toolkit.cgate import CGateClient
from cbus_toolkit.programming import xml_text
from research.cgate_dbsetxml_unit_differential import owned_server


ROOT = Path(__file__).resolve().parents[2]
NATIVE_WIRE_VECTOR = ROOT / "rust/testdata/vectors/cgate_dbgetxml_wire.json"


@pytest.mark.parametrize("product,variable,binary_name", (
    ("cgate-mock", "CBUS_CGATE_MOCK_BIN", "cgate-mock"),
    ("cmqttd", "CBUS_CMQTTD_BIN", "cmqttd"),
))
def test_python_client_and_pipelined_xml_roundtrip(product, variable, binary_name):
    binary = Path(os.environ.get(variable, ROOT / "rust/target/debug" / binary_name))
    if not binary.is_file() or not os.access(binary, os.X_OK):
        pytest.skip(f"{binary_name} binary is not built")
    native_noop, = [case for case in json.loads(NATIVE_WIRE_VECTOR.read_bytes())["cases"]
                    if case["command"] == "NOOP"]
    native_noop_row, = native_noop["response_lines"]
    native_noop_reply = native_noop_row.removeprefix(f"[{native_noop['tag']}] ").removesuffix("\r\n")
    with owned_server(product, binary) as port:
        with CGateClient("127.0.0.1", port, timeout=5) as client:
            assert client.command("PROJECT NEW XWIRE").code == 200
            assert client.command("DBCREATENET 254 Local Cni 127.0.0.1:1").code == 200
            before = client.command("DBGETXML //XWIRE/254")
            assert before.code == 344
            assert before.lines[0] == "343-Begin XML snippet"
            assert before.lines[-1] == "344 End XML snippet"
            network = xml_text(before).split("\n", 1)[1]
            assert ET.fromstring(network).tag == "Network"
            unit = (
                "<Unit><OID>11111111-1111-4111-8111-111111111111</OID>"
                "<TagName>Bedroom</TagName><Address>20</Address><UnitType>KEYE1</UnitType>"
                "<UnitName>Room</UnitName><FirmwareVersion>1.2.67</FirmwareVersion></Unit>"
            )
            replacement = network.replace("</Network>", unit + "</Network>")
            set_reply = client.command_document("DBSETXML //XWIRE/254", replacement)
            assert set_reply.code == 301
            assert set_reply.final.startswith("301 OID=")
            readback = client.command("DBGETXML //XWIRE/254/p/20")
            assert readback.code == 344
            assert len(readback.lines) == 4
            assert ET.fromstring(xml_text(readback)).findtext("UnitName") == "Room"
            noop = client.command("NOOP")
            assert noop.code == 200
            assert noop.lines == (native_noop_reply,)

        with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
            sock.settimeout(5)
            stream = sock.makefile("rb")
            try:
                assert stream.readline().startswith(b"201 ")
                sock.sendall(b"[899] PROJECT USE XWIRE\r\n")
                assert stream.readline() == b"[899] 200 OK.\r\n"
                sock.sendall(
                    b"[900] DBGETXML //XWIRE/254/p/20\r\n[901] NOOP\r\n"
                )
                assert stream.readline() == b"[900] 343-Begin XML snippet\r\n"
                assert stream.readline() == (
                    b'[900] 347-<?xml version="1.0" encoding="utf-8"?>\n'
                )
                document_row = stream.readline()
                assert document_row.startswith(b"[900] 347-<Unit>")
                assert document_row.endswith(b"</Unit>\r\n")
                assert stream.readline() == b"[900] 344 End XML snippet\r\n"
                assert stream.readline() == native_noop_row.replace(
                    f"[{native_noop['tag']}] ", "[901] ", 1
                ).encode()
            finally:
                stream.close()
