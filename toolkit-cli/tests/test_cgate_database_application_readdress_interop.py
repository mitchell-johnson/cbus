"""Public Application Address DBSETSAFE readdress journey on two owned Rust backends."""
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
def test_public_application_readdress_end_to_end(backend, variable, tmp_path):
    supplied = os.environ.get(variable)
    if not supplied:
        pytest.skip(f"Select {variable} for the owned application readdress journey")
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

            def gone(path):
                try:
                    document(path)
                except RuntimeError as error:
                    message = str(error)
                    assert "401" in message or "404" in message, message
                    return
                raise AssertionError(f"Retired path still readable: {path}")

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

            def oids_of(document_text):
                return {node.text for node in ET.fromstring(document_text).iter("OID")}

            command("PROJECT NEW LAB")
            command("PROJECT USE LAB")
            created = cli("network-new", "LAB", "254", "Loopback", "Cni", "127.0.0.1:1",
                          project="LAB", select_project=False)
            assert created["status"] in (200, 301), created
            network = "//LAB/254"
            app = issued(cli("add", network, "application", 70, "Lighting"))
            group = issued(cli("add", network + "/70", "group", 5, "Lamp"))
            level = issued(cli("add", network + "/70/5", "level", 9, "Evening"))
            field(level, "Value", 9)
            source = document(network + "/70")
            source_oids = oids_of(source)
            assert {app, group, level} <= source_oids, (source_oids, source)
            assert "<Address>70</Address>" in source
            # Numeric readdress 70 -> 71 moves the canonical path.
            moved = cli("set", network + "/70/Address", "71")
            assert moved["status"] == 200, moved
            moved_document = document(network + "/71")
            assert "<Address>71</Address>" in moved_document, moved_document
            assert oids_of(moved_document) == source_oids, moved_document
            gone(network + "/70")
            # Descendants travel with the application.
            group_document = document(network + "/71/5")
            assert group in oids_of(group_document), group_document
            level_value = cli("get", network + "/71/5/9/Value")
            assert level_value["status"] == 342, level_value
            assert level_value["final"].rsplit("=", 1)[-1] == "9", level_value
            field(level, "Value", 9)
            field(app, "Address", 71)
            # Issued-OID readdress moves the same identity again.
            moved_oid = cli("set", f"!{app}/Address", "72")
            assert moved_oid["status"] == 200, moved_oid
            oid_document = document(network + "/72")
            assert "<Address>72</Address>" in oid_document, oid_document
            assert oids_of(oid_document) == source_oids, oid_document
            gone(network + "/71")
            oid_group_document = document(network + "/72/5")
            assert group in oids_of(oid_group_document), oid_group_document
            oid_level_value = cli("get", network + "/72/5/9/Value")
            assert oid_level_value["status"] == 342, oid_level_value
            assert oid_level_value["final"].rsplit("=", 1)[-1] == "9", oid_level_value
            field(app, "Address", 72)
            field(level, "Value", 9)
            # Duplicate destination refuses without mutation.
            blocker = issued(cli("add", network, "application", 80, "Blocker"))
            before = document(network)
            conflict = cli("set", network + "/72/Address", "80", expected=1)
            assert "error" in conflict, conflict
            assert "408" in conflict["error"] or "409" in conflict["error"] or "already in use" in conflict["error"], conflict
            assert document(network) == before
            oid_conflict = cli("set", f"!{app}/Address", "80", expected=1)
            assert "error" in oid_conflict, oid_conflict
            assert "408" in oid_conflict["error"] or "409" in oid_conflict["error"] or "already in use" in oid_conflict["error"], oid_conflict
            assert document(network) == before
            for body in ("PROJECT SAVE LAB", "PROJECT CLOSE LAB", "PROJECT LOAD LAB"):
                command(body)
            command("PROJECT USE LAB")
            for oid in (app, group, level, blocker):
                field(oid, "OID", oid)
            reloaded = document(network + "/72")
            assert "<Address>72</Address>" in reloaded, reloaded
            assert oids_of(reloaded) == source_oids, reloaded
            assert "<Address>80</Address>" in document(network + "/80"), document(network + "/80")
            assert group in oids_of(document(network + "/72/5")), document(network + "/72/5")
            field(app, "Address", 72)
            field(level, "Value", 9)
    assert record["process_cleanup"] and record["listener_closed"]
