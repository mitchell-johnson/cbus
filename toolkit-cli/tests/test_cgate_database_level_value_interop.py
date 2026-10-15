"""Public numeric Level Value SAFE writes on two owned Rust backends (issue #131)."""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import select
import socket
import subprocess
import sys
import time
from xml.etree import ElementTree as ET

import pytest

from cbus_toolkit.cgate import CGateClient
from cbus_toolkit.native import NativeDatabase
from cbus_toolkit.programming import xml_text
from cbus_toolkit.simulator import PCISimulator
from test_cgate_named_database_interop import owned_backend


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


@pytest.mark.parametrize("backend,variable", [
    ("cgate-mock", "CBUS_CGATE_MOCK_BIN"), ("cmqttd", "CBUS_CMQTTD_BIN"),
], ids=["mock", "daemon"])
def test_public_numeric_level_value_end_to_end(backend, variable, tmp_path):
    supplied = os.environ.get(variable)
    if not supplied:
        pytest.skip(f"Select {variable} for the owned numeric Level Value journey")
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

            def cli(*arguments, project="LAB", expected=0, select_project=True):
                argv = [sys.executable, "-m", "cbus_toolkit", "cgate", "--host", endpoint[0],
                        "--port", str(endpoint[1]), "--timeout", "15", "database",
                        *map(str, arguments)]
                if select_project:
                    argv += ["--project", project]
                result = subprocess.run(argv, text=True, capture_output=True, timeout=30)
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

            def level_value(oid, expected):
                raw = document("!" + oid)
                root = ET.fromstring(raw)
                assert root.tag.rsplit("}", 1)[-1] == "Level", raw
                assert root.attrib.get("Value") == str(expected), raw
                assert f'Value="{expected}"' in raw, raw

            command("PROJECT NEW LAB")
            command("PROJECT USE LAB")
            created = cli("network-new", "LAB", "254", "Loopback", "Cni", "127.0.0.1:1",
                          project="LAB", select_project=False)
            assert created["status"] in (200, 301), created
            network = "//LAB/254"
            app = issued(cli("add", network, "application", 80, "App80"))
            group = issued(cli("add", network + "/80", "group", 8, "Grp8"))
            level = issued(cli("add", network + "/80/8", "level", 4, "Lvl4"))
            field(level, "Value", 4)
            level_value(level, 4)
            # Numeric SAFE write owns the typed record.
            updated = cli("set", network + "/80/8/4/Value", "77")
            assert updated["status"] == 200, updated
            field(level, "Value", 77)
            numeric = cli("get", network + "/80/8/4/Value")
            assert numeric["status"] == 342, numeric
            assert numeric["final"].rsplit("=", 1)[-1] == "77", numeric
            level_value(level, 77)
            # Issued-OID SAFE write addresses the same owner (core #131 acceptance).
            oid_updated = cli("set", f"!{level}/Value", "99")
            assert oid_updated["status"] == 200, oid_updated
            field(level, "Value", 99)
            numeric = cli("get", network + "/80/8/4/Value")
            assert numeric["status"] == 342, numeric
            assert numeric["final"].rsplit("=", 1)[-1] == "99", numeric
            level_value(level, 99)
            # Invalid values refuse without mutation.
            before = document(network)
            for tail in ("oops", "256", "-1"):
                refused = cli("set", network + "/80/8/4/Value", tail, expected=1)
                assert "error" in refused, refused
            refused = cli("set", f"!{level}/Value", "oops", expected=1)
            assert "error" in refused, refused
            assert document(network) == before
            field(level, "Value", 99)
            level_value(level, 99)
            for body in ("PROJECT SAVE LAB", "PROJECT CLOSE LAB", "PROJECT LOAD LAB"):
                command(body)
            for oid in (app, group, level):
                field(oid, "OID", oid)
            field(level, "Value", 99)
            level_value(level, 99)
    assert record["process_cleanup"] and record["listener_closed"]
