"""Owned original C-Gate acceptance for public database XML file commands."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from xml.etree import ElementTree as ET

from cbus_toolkit.cgate import CGateClient
from cbus_toolkit.native import NativeDatabase
from cbus_toolkit.programming import xml_text
from research.local_cgate import JAR_SHA256, LocalCGate


@unittest.skipUnless(
    all(os.environ.get(name) for name in ("CBUS_CGATE_JAVA", "CBUS_LOCAL_CGATE_VENDOR")),
    "Select pinned Java11/vendor for owned original C-Gate CLI acceptance",
)
class NativeDatabaseXmlFileCliTests(unittest.TestCase):
    def test_group_label_export_guarded_replace_and_native_reload(self):
        java = Path(os.environ["CBUS_CGATE_JAVA"])
        vendor = Path(os.environ["CBUS_LOCAL_CGATE_VENDOR"])
        self.assertEqual(JAR_SHA256, "3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630")
        self.assertEqual(
            hashlib.sha256(java.read_bytes()).hexdigest(),
            "94e156397958bb83fda31ee16200580fd083b0fc0ed4a9ce795cfa44ff8e72f4",
        )
        service = LocalCGate(vendor, java=java)
        with service:
            with CGateClient("127.0.0.1", service.port, timeout=15) as owner:
                self.assertEqual(owner.command("PROJECT NEW XFILE").code, 200)
                self.assertEqual(owner.command("PROJECT USE XFILE").code, 200)
                self.assertEqual(owner.command("DBCREATENET 254 Local Cni 127.0.0.1:1").code, 301)
                database = NativeDatabase(owner)
                network = xml_text(database.get("//XFILE/254", xml=True))
                application = (
                    "<Application><OID>33333333-3333-4333-8333-333333333333</OID>"
                    "<TagName>Lighting</TagName><Address>56</Address>"
                    "<Group><OID>44444444-4444-4444-8444-444444444444</OID>"
                    "<TagName>Garage</TagName><Address>1</Address></Group></Application>"
                )
                self.assertEqual(database.set_xml(
                    "//XFILE/254", network.replace("</Network>", application + "</Network>")
                ).code, 301)
                for command in (
                    "PROJECT SAVE XFILE", "PROJECT CLOSE XFILE",
                    "PROJECT LOAD XFILE", "PROJECT USE XFILE",
                ):
                    self.assertEqual(owner.command(command).code, 200)

                def cli(*arguments):
                    process = subprocess.run(
                        [sys.executable, "-m", "cbus_toolkit", "cgate", "--host", "127.0.0.1",
                         "--port", str(service.port), "database", *map(str, arguments)],
                        text=True, capture_output=True, timeout=20,
                    )
                    return process.returncode, json.loads(process.stdout or process.stderr)

                group_path = "//XFILE/254/56/1"
                with tempfile.TemporaryDirectory() as directory:
                    exported = Path(directory) / "group.xml"
                    status, receipt = cli("get-xml", group_path, "--project", "XFILE",
                                          "--output", exported)
                    self.assertEqual(status, 0, receipt)
                    original = exported.read_bytes()
                    self.assertEqual(receipt["sha256"], hashlib.sha256(original).hexdigest())
                    label = (
                        "<TagsDLT><TagDLT><LanguageID>1</LanguageID><FlavourID>1</FlavourID>"
                        "<TagType>TEXT</TagType><TagValue>Owned CLI label</TagValue>"
                        "</TagDLT></TagsDLT>"
                    )
                    replacement = Path(directory) / "replacement.xml"
                    replacement.write_text(
                        original.decode("utf-8").replace("</Group>", label + "</Group>"),
                        encoding="utf-8",
                    )
                    status, applied = cli(
                        "set-xml", group_path, replacement, "--project", "XFILE",
                        "--expect-current-sha256", receipt["sha256"], "--readback",
                    )
                    self.assertEqual(status, 0, applied)
                    self.assertEqual(applied["response"]["status"], 301)
                    self.assertTrue(applied["readback"]["retrieved"])
                    self.assertFalse(applied["project_save_requested"])
                    direct = ET.fromstring(xml_text(database.get(group_path, xml=True)))
                    tag = direct.find("TagsDLT/TagDLT")
                    self.assertEqual(tag.findtext("TagValue"), "Owned CLI label")
                    issued_oid = tag.findtext("OID")
                    self.assertTrue(issued_oid)
                    status, stale = cli(
                        "set-xml", group_path, replacement, "--project", "XFILE",
                        "--expect-current-sha256", "0" * 64,
                    )
                    self.assertEqual(status, 1)
                    self.assertIn("SHA-256 differs", stale["error"])
                    self.assertEqual(
                        ET.fromstring(xml_text(database.get(group_path, xml=True)))
                        .findtext("TagsDLT/TagDLT/OID"),
                        issued_oid,
                    )

                self.assertEqual(owner.command("PROJECT SAVE XFILE").code, 200)
                self.assertEqual(owner.command("PROJECT CLOSE XFILE").code, 200)
                self.assertEqual(owner.command("PROJECT LOAD XFILE").code, 200)
                self.assertEqual(owner.command("PROJECT USE XFILE").code, 200)
                reloaded = ET.fromstring(xml_text(database.get("//XFILE/254", xml=True)))
                self.assertEqual(
                    reloaded.findtext(".//Group/TagsDLT/TagDLT/OID"), issued_oid
                )
        self.assertTrue(service.report["listener_ownership_verified"])
        self.assertTrue(service.report["process_exit_confirmed"])
        self.assertTrue(service.report["work_removed"])
        self.assertTrue(service.report["cleanup_complete"])
