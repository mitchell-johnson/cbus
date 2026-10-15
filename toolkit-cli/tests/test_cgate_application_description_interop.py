"""Owned-model Application/Group Description XML round-trip (issue #75).

Drives the vector contract in
``rust/testdata/vectors/cgate_application_description_xml_roundtrip.jsonl``
against freshly built cgate-mock and cmqttd: scalar acknowledgement,
DBGETXML export, DBSETXML re-import, omission retires, save/reload
durability and admission refusals. Native C-Gate placement/order/default
behavior remains unproven; this pins the owned-model contract only.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from cbus_toolkit.cgate import CGateClient, CGateError
from cbus_toolkit.programming import xml_text
from research.cgate_dbsetxml_unit_differential import owned_server


ROOT = Path(__file__).resolve().parents[2]
VECTOR = ROOT / "rust/testdata/vectors/cgate_application_description_xml_roundtrip.jsonl"


def load_vector() -> dict:
    return json.loads(VECTOR.read_text())


@pytest.mark.parametrize("product,variable,binary_name", (
    ("cgate-mock", "CBUS_CGATE_MOCK_BIN", "cgate-mock"),
    ("cmqttd", "CBUS_CMQTTD_BIN", "cmqttd"),
))
def test_application_description_xml_roundtrip(product, variable, binary_name):
    vector = load_vector()
    assert vector["schema"] == "cgate-application-description-xml-roundtrip-v1"
    binary = Path(os.environ.get(variable, ROOT / "rust/target/debug" / binary_name))
    if not binary.is_file() or not os.access(binary, os.X_OK):
        pytest.skip(f"{binary_name} binary is not built")
    with owned_server(product, binary) as port:
        with CGateClient("127.0.0.1", port, timeout=10) as client:
            for command in vector["seed_commands"]:
                reply = client.command(command)
                assert reply.code in (200, 301), (command, reply)
                if command.startswith("DBADDSAFE //DESC/254 Application 48 "):
                    app_oid = reply.final.split("OID=", 1)[1]
                elif command.startswith("DBADDSAFE //DESC/254/48 Group 42 "):
                    group_oid = reply.final.split("OID=", 1)[1]
            case = vector["cases"][0]
            assert client.command(
                f"DBSETSAFE !{app_oid}/Description {case['oid_setter_value']}"
            ).code == vector["set_status"]
            read = client.command(f"DBGET !{app_oid}/Description")
            assert read.code == vector["get_status"]
            assert read.final == f"342 !{app_oid}/Description={case['oid_setter_value']}"
            group_case = vector["cases"][1]
            assert client.command(
                f"DBSETSAFE !{group_oid}/Description {group_case['oid_setter_value']}"
            ).code == 200
            export = client.command("DBGETXML //DESC")
            assert export.code in (200, 344)
            document = xml_text(export)
            assert "<Description>" in document
            assert case["oid_setter_value"].replace("&", "&amp;") in document
            application = xml_text(client.command("DBGETXML //DESC/254/48"))
            assert "<Description>" in application
            root = ET.fromstring(application.split("\n", 1)[1])
            assert root.tag == "Application"
            assert root.findtext("Description") == case["oid_setter_value"]
            # Re-importing the exported document is accepted and stable.
            reimport = client.command_document("DBSETXML //DESC/254/48", application)
            assert reimport.code == vector["reimport_status"], reimport
            again = xml_text(client.command("DBGETXML //DESC"))
            assert again == document
            # Omitting Description retires it.
            retired_source = application.replace(
                f"<Description>{case['oid_setter_value'].replace('&', '&amp;')}</Description>",
                "",
            )
            assert retired_source != application
            assert client.command_document("DBSETXML //DESC/254/48", retired_source).code == 301
            with pytest.raises(CGateError) as retired:
                client.command(f"DBGET !{app_oid}/Description")
            assert retired.value.response.status == 401
            retired_doc = xml_text(client.command("DBGETXML //DESC/254/48"))
            # The retired Application Description is gone; the Group child's
            # own Description is untouched.
            assert case["oid_setter_value"].replace("&", "&amp;") not in retired_doc
            assert group_case["oid_setter_value"].replace("&", "&amp;") in retired_doc
            # Duplicate and overlong Descriptions are refused; state is kept.
            assert client.command("PROJECT USE DESC").code == 200
            assert client.command(
                f"DBSETSAFE !{app_oid}/Description {case['canonical_setter_value']}"
            ).code == 200
            duplicate = (
                f"<Application><OID>{app_oid}</OID><TagName>{case['tag_name']}</TagName>"
                f"<Address>{case['address']}</Address>"
                "<Description>a</Description><Description>b</Description></Application>"
            )
            with pytest.raises(CGateError) as dup_refused:
                client.command_document("DBSETXML //DESC/254/48", duplicate)
            assert dup_refused.value.response.status == 400
            overlong = (
                f"<Application><OID>{app_oid}</OID><TagName>{case['tag_name']}</TagName>"
                f"<Address>{case['address']}</Address><Description>{'x' * 1025}</Description>"
                "</Application>"
            )
            with pytest.raises(CGateError) as long_refused:
                client.command_document("DBSETXML //DESC/254/48", overlong)
            assert long_refused.value.response.status == 400
            kept = client.command(f"DBGET !{app_oid}/Description")
            assert kept.final == f"342 !{app_oid}/Description={case['canonical_setter_value']}"
            # Saved image survives close/load.
            assert client.command("PROJECT SAVE DESC").code == 200
            assert client.command("PROJECT CLOSE DESC").code == 200
            assert client.command("PROJECT LOAD DESC").code == 200
            assert client.command("PROJECT USE DESC").code == 200
            reloaded = client.command(f"DBGET !{app_oid}/Description")
            assert reloaded.final == f"342 !{app_oid}/Description={case['canonical_setter_value']}"
