"""Owned-model Application/Group Description XML round trip on both Rust services (#75).

The vector is an owned-model contract: native C-Gate placement, default
omission and empty-value handling are unproven, so these checks never claim
native XML acceptance. cmqttd additionally proves its JSON repository keeps
the shared scalar/XML value across a process restart.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from cbus_toolkit.cgate import CGateClient, CGateError
from cbus_toolkit.programming import xml_text
from research.cgate_dbsetxml_unit_differential import owned_server
from test_cgate_named_database_interop import associated_work, owned_backend

ROOT = Path(__file__).resolve().parents[2]
VECTOR = ROOT / "rust/testdata/vectors/cgate_application_description_xml_roundtrip.jsonl"
CONTRACT = ROOT / "rust/testdata/vectors/cgate_application_description_xml_contract.json"


def vector():
    rows = [json.loads(line) for line in VECTOR.read_text(encoding="utf-8").splitlines() if line.strip()]
    scope = rows[0]
    assert scope["kind"] == "scope" and scope["model"] == "owned-model"
    assert scope["native_placement_order"] == "unproven"
    assert scope["native_xml_acceptance"] is False and scope["original_execution"] is False
    assert all(row["format"] == "cgate-application-description-xml-roundtrip-v1" and row["issue"] == 75
               for row in rows)
    return scope, rows[1:]


def expand(text, roles):
    for role, oid in roles.items():
        text = text.replace("{" + role + "}", oid)
    return text


def call(client, request, document=None):
    try:
        if document is None:
            return client.command(request)
        return client.command_document(request, document)
    except CGateError as error:
        return error.response


def exported(response):
    assert response.code == 344, response
    header, document = xml_text(response).split("\n", 1)
    assert header == '<?xml version="1.0" encoding="utf-8"?>'
    return document


def snapshot(client, roles):
    rows = [exported(call(client, "DBGETXML //DESC"))]
    rows.extend(call(client, f"DBGET !{oid}/Description").final for oid in roles.values())
    return rows


def run_vector(client, scope, rows):
    issued = []
    for command in scope["seed_commands"]:
        response = client.command(command)
        if response.final.startswith("301 OID="):
            issued.append(response.final.removeprefix("301 OID="))
    roles = dict(zip(scope["oid_roles"], issued, strict=True))
    for row in rows:
        request = expand(row["request"], roles)
        before = snapshot(client, roles) if row.get("preserves_state") else None
        document = expand(row["document"], roles) if "document" in row else None
        response = call(client, request, document)
        if row.get("xml") is not None:
            assert exported(response) == expand(row["xml"], roles), row["id"]
            # The export parses as one object whose Description follows Address.
            root = ET.fromstring(exported(response))
            names = [child.tag for child in root]
            if "Description" in names:
                assert names.index("Description") == names.index("Address") + 1
        elif row["wire"] is not None:
            assert "[d] " + response.final + "\n" == expand(row["wire"], roles), row["id"]
        else:
            assert response.code == 200, (row["id"], response)
        if before is not None:
            assert snapshot(client, roles) == before, row["id"]
    return roles


@pytest.mark.parametrize("backend,variable", [
    ("cgate-mock", "CBUS_CGATE_MOCK_BIN"), ("cmqttd", "CBUS_CMQTTD_BIN"),
], ids=["mock", "daemon"])
def test_application_description_xml_roundtrip_vector(backend, variable, tmp_path):
    supplied = os.environ.get(variable)
    if not supplied:
        pytest.skip(f"Select {variable} for the owned Application Description XML round trip")
    binary = Path(supplied).resolve()
    assert binary.is_file() and os.access(binary, os.X_OK)
    scope, rows = vector()
    work = associated_work(tmp_path, "initial")
    with owned_backend(backend, binary, work) as (endpoint, _record):
        with CGateClient(*endpoint, timeout=15) as client:
            roles = run_vector(client, scope, rows)
            final = snapshot(client, roles)
            assert "<Description>Imported &amp; Ω</Description>" in final[0]
    if backend != "cmqttd":
        return
    restart = associated_work(tmp_path, "restart")
    with owned_backend(backend, binary, restart, state_path=work / "state.json") as (endpoint, _record):
        with CGateClient(*endpoint, timeout=15) as client:
            assert client.command("PROJECT USE DESC").code == 200
            assert snapshot(client, roles) == final
            for command in ("PROJECT CLOSE DESC", "PROJECT LOAD DESC", "PROJECT USE DESC"):
                assert client.command(command).code == 200
            assert snapshot(client, roles) == final


def load_contract() -> dict:
    return json.loads(CONTRACT.read_text())


@pytest.mark.parametrize("product,variable,binary_name", (
    ("cgate-mock", "CBUS_CGATE_MOCK_BIN", "cgate-mock"),
    ("cmqttd", "CBUS_CMQTTD_BIN", "cmqttd"),
))
def test_application_description_xml_contract(product, variable, binary_name):
    """Single-document Description contract driven against both owned services."""
    vector = load_contract()
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
