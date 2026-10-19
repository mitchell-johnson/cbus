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
from test_cgate_named_database_interop import associated_work, owned_backend

ROOT = Path(__file__).resolve().parents[2]
VECTOR = ROOT / "rust/testdata/vectors/cgate_application_description_xml_roundtrip.jsonl"


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
