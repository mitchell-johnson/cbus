"""Separate public CLI sessions against one explicitly owned closed C-Gate model."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import socketserver
import subprocess
import sys
import threading
import unittest
from xml.etree import ElementTree as ET

from cbus_toolkit.cgate import CGateClient
from cbus_toolkit.native import NativeDatabase
from cbus_toolkit.programming import xml_text
from research.local_cgate import LocalCGate


@contextmanager
def no_contact_trap():
    connections = []

    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            connections.append(self.client_address)

    server = socketserver.TCPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": .01}, daemon=True,
    )
    thread.start()
    try:
        yield f"127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(3)
        assert not thread.is_alive()
        assert connections == [], "Closed database workflow contacted its CNI"


@unittest.skipUnless(
    os.environ.get("CBUS_NATIVE_SERVICE_BACKEND") == "local"
    and all(os.environ.get(name) for name in ("CBUS_CGATE_JAVA", "CBUS_LOCAL_CGATE_VENDOR")),
    "Select local backend and pinned Java11/vendor for owned original typed CLI validation",
)
class NativeDatabaseProjectCliTests(unittest.TestCase):
    def test_named_graph_separate_selected_cli_sessions_and_explicit_reload(self):
        java = Path(os.environ["CBUS_CGATE_JAVA"])
        self.assertEqual(hashlib.sha256(java.read_bytes()).hexdigest(),
                         "94e156397958bb83fda31ee16200580fd083b0fc0ed4a9ce795cfa44ff8e72f4")
        service = LocalCGate(os.environ["CBUS_LOCAL_CGATE_VENDOR"], java=java)
        with no_contact_trap() as endpoint, service:
            with CGateClient("127.0.0.1", service.port, timeout=15) as owner:
                db = NativeDatabase(owner)

                def command(body, status=200):
                    result = owner.command(body)
                    self.assertEqual(result.code, status, result.final)
                    return result

                def document(path):
                    return xml_text(db.get(path, xml=True))

                def cli(*arguments, expected=0):
                    process = subprocess.run(
                        [sys.executable, "-m", "cbus_toolkit", "cgate", "--host", "127.0.0.1",
                         "--port", str(service.port), "--timeout", "15", "database",
                         *map(str, arguments), "--project", "LAB"],
                        text=True, capture_output=True, timeout=30,
                    )
                    result = json.loads(process.stdout or process.stderr)
                    self.assertEqual(process.returncode, expected, result)
                    return result

                def field(oid, name, value):
                    result = cli("get", "!" + oid + "/" + name)
                    self.assertEqual(result["status"], 342, result)
                    self.assertEqual(result["final"].rsplit("=", 1)[-1], str(value))

                def issued(result):
                    self.assertEqual(result["status"], 301, result)
                    match = re.fullmatch(r"301 OID=([0-9a-fA-F-]{36})", result["final"])
                    self.assertIsNotNone(match, result)
                    oid = match[1]
                    field(oid, "OID", oid)
                    return oid

                def add(parent, kind, address, name):
                    return issued(cli("add", parent, kind, address, name))

                command("PROJECT NEW LAB")
                command("PROJECT USE LAB")
                command("NET CREATE Neighbor cni " + endpoint)
                command("NET CREATE CustomA cni " + endpoint)
                command("NET SAVE DB")
                command("PROJECT SAVE LAB")
                neighbor = document("//LAB/Neighbor")
                command("PROJECT NEW OTHER")
                command("PROJECT USE OTHER")
                command("NET CREATE Else cni " + endpoint)
                command("NET SAVE DB")
                command("PROJECT SAVE OTHER")
                other = document("//OTHER")
                # The owner stays on OTHER while each public process selects LAB.
                network = "//LAB/CustomA"
                self.assertEqual(cli("get", network + "/Address")["final"].rsplit("=", 1)[-1],
                                 "CustomA")
                app = add(network, "application", 56, "Lighting")
                group = add("!" + app, "group", 1, "Lamp")
                self.assertEqual(cli("set", "!" + group + "/TagName", "Edited lamp")["status"], 200)
                field(group, "TagName", "Edited lamp")
                level = add("!" + group, "level", 7, "Evening")
                field(level, "Value", 7)
                copied_level = issued(cli("copy", "!" + level, "!" + group, 8, "Reading"))
                self.assertNotEqual(copied_level, level)
                field(copied_level, "Address", 8)
                field(copied_level, "Value", 8)
                field(level, "Value", 7)
                netvar = add("!" + app, "netvar", 4, "Variable")
                netvar_level = add("!" + netvar, "level", 42, "Dinner")
                field(netvar_level, "Value", 42)

                command("PROJECT USE LAB")
                source = document("!" + group)
                copied_group = issued(cli("copy", "!" + group, "!" + app, 2, "Copied lamp"))
                self.assertEqual(document("!" + group), source)
                source_oids = {node.text for node in ET.fromstring(source).iter("OID")}
                copied_tree = ET.fromstring(document("!" + copied_group))
                copied_oids = {node.text for node in copied_tree.iter("OID")}
                self.assertEqual(len(copied_oids), len(source_oids))
                self.assertTrue(source_oids.isdisjoint(copied_oids))
                self.assertEqual({node.get("Value") for node in copied_tree.findall("Level")}, {"7", "8"})
                self.assertEqual(cli("delete", "!" + copied_group)["status"], 200)
                self.assertIn("401", cli("get", "!" + copied_group + "/OID", expected=1)["error"])
                validation = cli("validate", network)
                self.assertEqual(validation["status"], 233, validation)
                self.assertIn("Network: Valid", validation["final"])
                self.assertEqual(document("//LAB/Neighbor"), neighbor)
                self.assertEqual(document("//OTHER"), other)

                command("PROJECT USE LAB")
                for body in ("PROJECT SAVE LAB", "PROJECT CLOSE LAB", "PROJECT LOAD LAB"):
                    command(body)
                for oid, address, name in (
                    (app, 56, "Lighting"), (group, 1, "Edited lamp"),
                    (level, 7, "Evening"), (copied_level, 8, "Reading"),
                    (netvar, 4, "Variable"), (netvar_level, 42, "Dinner"),
                ):
                    field(oid, "OID", oid)
                    field(oid, "Address", address)
                    field(oid, "TagName", name)
                for oid, value in ((level, 7), (copied_level, 8), (netvar_level, 42)):
                    field(oid, "Value", value)
                self.assertIn("401", cli("get", "!" + copied_group + "/OID", expected=1)["error"])
                self.assertEqual(document("//LAB/Neighbor"), neighbor)
                self.assertEqual(document("//OTHER"), other)
        for fact in ("listener_ownership_verified", "process_exit_confirmed", "work_removed",
                     "cleanup_complete"):
            self.assertTrue(service.report[fact], service.report)
