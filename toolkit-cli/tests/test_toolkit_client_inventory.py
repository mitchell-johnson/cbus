"""cgate-mock answers Toolkit 1.18.0's own C-Gate commands in shapes Toolkit parses.

`research/toolkit-client/inventory.json` lists the commands Toolkit sends and
the reply codes or fragments its parsers accept, recovered statically with
REA. The reply shapes below come from the decompiled C-Gate 3.4.0 handlers
for the same commands. This checks reply envelopes only; it is not Toolkit
workflow acceptance.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import socket

import pytest

from research.cgate_dbsetxml_unit_differential import owned_server

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "research/toolkit-client/inventory.json"


def inventory():
    return json.loads(INVENTORY.read_text(encoding="utf-8"))


def test_inventory_records_sources_and_unique_command_classes():
    document = inventory()
    assert document["vendor_release"] == {"toolkit": "1.18.0.2754", "cgate": "3.4.0.2001"}
    assert all(re.fullmatch(r"[0-9a-f]{64}", source["sha256"]) for source in document["sources"])
    classes = [row["class"] for row in document["managed_commands"] + document["native_commands"]]
    assert len(classes) == len(set(classes))
    assert all(row["codes"] for row in document["managed_commands"])
    assert document["unrecovered"], "recovery limits must stay recorded"


class Session:
    def __init__(self, port):
        self.socket = socket.create_connection(("127.0.0.1", port), timeout=10)
        self.file = self.socket.makefile("rwb")
        assert self.file.readline().startswith(b"201 ")
        self.tag = 0

    def __call__(self, command):
        self.tag += 1
        tag = f"[{self.tag}] "
        self.file.write(f"{tag}{command}\n".encode())
        self.file.flush()
        lines = []
        while True:
            line = self.file.readline().decode().rstrip("\r\n")
            assert line, f"connection closed during {command!r}"
            if not line.startswith(tag):
                continue
            line = line[len(tag):]
            lines.append(line)
            if re.match(r"\d{3} ", line):
                return lines


def codes(lines):
    return {int(line[:3]) for line in lines}


def test_mock_replies_fit_toolkit_parsers():
    supplied = os.environ.get("CBUS_CGATE_MOCK_BIN")
    if not supplied:
        pytest.skip("Select CBUS_CGATE_MOCK_BIN for the Toolkit client reply check")
    binary = Path(supplied).resolve()
    assert binary.is_file() and os.access(binary, os.X_OK)
    with owned_server("cgate-mock", binary) as port:
        send = Session(port)
        # Empty server: native empty-list codes, which Toolkit matches by text.
        assert send("project list") == ["124 no projects found"]
        assert send("project dir all") == ["124 no projects found"]
        assert send("net list_all") == ["132 no networks found"]
        assert send("pp units") == ["122 no open sessions"]
        assert send("pp list_lock") == ["122 no open locks"]

        # TcgcMark relies on an unregistered verb answering a syntax error.
        assert send("Mark") == ["400 Syntax Error."]
        assert send("login") == ["210 Access level: Program"]
        assert send("login user") == ["400 Syntax Error."]
        assert send("login user secret") == ["211 Access level set to: Program"]
        assert send("noop") == ["200 OK."]

        assert send("project new TOOLKIT") == ["200 OK."]
        assert send("project load TOOLKIT")[-1].startswith("200 ")
        assert send("project use") == ["123 project=TOOLKIT"]
        assert send("project list") == ["123 project=TOOLKIT state=stopped"]
        assert send("project start TOOLKIT")[-1].startswith("200 ")
        assert send("project list") == ["123 project=TOOLKIT state=started"]
        listed = send("project dir all")
        assert re.fullmatch(
            r"123 project=TOOLKIT repository=XML creationDate=\d\d/\d\d/\d{4} description=",
            listed[-1],
        ), listed

        # Toolkit quotes the network name; native C-Gate answers with its OID.
        created = send('dbcreatenet 254 "Toolkit Net" Cni 127.0.0.1:10001')
        assert len(created) == 1 and created[0].startswith("301 OID="), created
        assert send('dbcreatenet 253 "Unbalanced Cni 127.0.0.1:10001') == [
            "400 Syntax Error: Missing parameter : name"
        ]
        assert send("net list") == ["131 network=254 State=new InterfaceState=closed"]
        oid = created[0].removeprefix("301 OID=")
        assert send("net list_all") == [
            f"135 project=TOOLKIT address=//TOOLKIT/254 OID={oid} interfaceType=Cni "
            "interfaceAddress=127.0.0.1:10001 state=new interfaceState=closed"
        ]

        # TcgcID marks itself done after one row, so ID must answer one line.
        assert send("ID //TOOLKIT/254/p/20 type") == [
            "401 Bad object or device ID: //TOOLKIT/254/p/20 (Object not found )"
        ]
        assert send("DBADDSAFE //TOOLKIT/254 Unit 20 Keypad")[-1].startswith("301 OID=")
        assert send("DBSETSAFE //TOOLKIT/254/p/20/UnitType KEYE1")[-1].startswith("200 ")
        assert send("ID //TOOLKIT/254/p/20 type") == ["521 Unit unavailable: Identify failed."]
        assert send("net open 254")[-1].startswith("200 ")
        assert send("ID //TOOLKIT/254/p/20 type") == ["300 p/254/20 type=KEYE1"]
        version = send("ID //TOOLKIT/254/p/20 version")
        assert len(version) == 1 and version[0].startswith("300 p/254/20 version="), version
        assert send("ID //TOOLKIT/254/p/20 bogus") == ["521 Unit unavailable: Identify failed."]
        assert send("do //TOOLKIT/254/p/20 qsync") == ["202 Done: //TOOLKIT/254/p/20"]
        assert send("net close 254")[-1].startswith("200 ")

        assert send("pp lock TheLock //TOOLKIT/254")[-1].startswith("200 ")
        assert send("pp start TheSession TheLock")[-1].startswith("200 ")
        assert send("pp units") == ["121 name=TheSession address=//TOOLKIT/254"]
        assert send("pp list_lock") == ["121 name=TheLock address=//TOOLKIT/254"]
        assert codes(send("pp end TheSession")) == {200}
        assert codes(send("pp unlock TheLock")) == {200}

        assert send("session_id tag toolkit")[-1].startswith("200 ")
        assert codes(send("session_id all")) == {300}
        assert codes(send("stop 999")) == {207}

        assert send("START_BACKGROUND_JOB XmlToSqlTransformJob") == ["200 OK."]
        assert send("START_BACKGROUND_JOB Undefined") == [
            "400 Syntax Error: Invalid parameter : The background job is not defined."
        ]
        # The mock has no CAL responder: a closed network reports the native
        # send error before Toolkit's `Response=` line.
        assert send("send //TOOLKIT/254 0021") == [
            "524-//TOOLKIT/254: Command send error",
            "300 Response=",
        ]
        assert send("send //TOOLKIT/9 0021") == ["401 Bad object or device ID."]

        assert codes(send("project close TOOLKIT")) == {200}
        assert send("project list") == ["124 no projects found"]
