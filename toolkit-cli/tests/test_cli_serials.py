"""CLI serial inventories, canonical comparison and native cache boundaries."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from uuid import uuid4


class SerialCLITests(unittest.TestCase):
    def cli(self, *args, status=0):
        result = subprocess.run([sys.executable, "-m", "cbus_toolkit", *map(str, args)],
                                capture_output=True, text=True, timeout=45)
        self.assertEqual(result.returncode, status, result.stdout + result.stderr)
        return json.loads(result.stdout or result.stderr)

    def test_native_inventory_comparison_retains_partial_evidence_and_original_serials(self):
        with tempfile.TemporaryDirectory() as folder:
            database, network = Path(folder) / "db.json", Path(folder) / "net.json"
            database.write_text(json.dumps([{"address": 4, "unit_type": "KEYE1", "serial": "00101136.1558"}]))
            snapshot = {"format": "cbus-native-serial-inventory-v1", "network": "//TEST/254",
                        "mode": "refresh", "complete": True, "observed_at": "2026-09-14T00:00:00+00:00",
                        "errors": [], "records": [{"address": 4, "status": "ok", "errors": []}],
                        "identities": [{"address": 4, "unit_type": "KEYE1", "serial": "101136.1558"}]}
            network.write_text(json.dumps(snapshot))
            report = self.cli("unit-addressing", "match", database, network)
            self.assertTrue(report["native_serials"])
            self.assertTrue(report["inventory_complete"])
            self.assertEqual(report["matches"][0]["status"], "aligned")
            self.assertEqual(report["matches"][0]["database"][0]["serial"], "00101136.1558")
            snapshot["complete"] = False
            snapshot["records"].append({"address": 5, "status": "absent", "errors": []})
            network.write_text(json.dumps(snapshot))
            before = database.read_bytes(), network.read_bytes()
            report = self.cli("unit-addressing", "match", database, network, status=1)
            self.assertFalse(report["inventory_complete"])
            self.assertFalse(report["applied"])
            self.assertEqual(report["inventory_sources"]["network"]["incomplete_records"][0]["status"], "absent")
            self.assertEqual(before, (database.read_bytes(), network.read_bytes()))
            del snapshot["complete"]
            network.write_text(json.dumps(snapshot))
            self.assertIn("requires complete", self.cli("unit-addressing", "match", database, network, status=1)["error"])

    def test_explicit_native_mode_excludes_placeholders_and_reports_invalid_serials(self):
        with tempfile.TemporaryDirectory() as folder:
            database, network = Path(folder) / "db.json", Path(folder) / "net.json"
            database.write_text(json.dumps([{"address": 4, "unit_type": "KEYE1", "serial": "0.0"},
                                             {"address": 5, "unit_type": "KEYGL5", "serial": "not-native"}]))
            network.write_text("[]")
            report = self.cli("unit-addressing", "match", database, network, "--native-serials")
            self.assertEqual(report["matches"], [])
            self.assertEqual([row["address"] for row in report["unidentified_database"]], [4, 5])
            self.assertEqual(report["invalid_database_serials"][0]["address"], 5)

    @unittest.skipUnless(os.environ.get("CBUS_CGATE_TEST_HOST"), "Set CBUS_CGATE_TEST_HOST for native CLI serial acceptance")
    def test_cli_native_cache_refresh_and_partial_exit(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase, NativeProjects
        from cbus_toolkit.networks import NativeNetworks
        from cbus_toolkit.programming import xml_text
        from cbus_toolkit.simulator import PCISimulator
        project = "SC" + uuid4().hex[:6].upper()
        network = "//" + project + "/254"
        host, port = os.environ["CBUS_CGATE_TEST_HOST"], int(os.environ.get("CBUS_CGATE_TEST_PORT", "20023"))
        args = ("cgate", "--host", host, "--port", port, "--timeout", "30", "serials")
        sim = PCISimulator(profile="synthetic", response_delay=0.01)
        with sim.running("0.0.0.0", 0) as (_, sim_port), CGateClient(host, port, timeout=30) as client:
            projects, database, lifecycle = NativeProjects(client), NativeDatabase(client), NativeNetworks(client)
            projects.operation("new", project)
            try:
                database.create_network(project, 254, "Serial_CLI", "Cni",
                    os.environ.get("CBUS_CGATE_SIMULATOR_HOST", "host.docker.internal") + ":" + str(sim_port))
                projects.operation("save", project)
                before = xml_text(database.get(network, xml=True))
                lifecycle.open(network)
                self.assertTrue(lifecycle.wait_ready(network, timeout=25)["ready"])
                cached = self.cli(*args, "cached", network, "--unit", "4", "--unit", "5")
                self.assertTrue(cached["complete"])
                self.assertEqual([row["serial"] for row in cached["identities"]], ["101136.1558", "101183.1666"])
                partial = self.cli(*args, "refresh", network, "--unit", "4", "--unit", "6", status=1)
                self.assertFalse(partial["complete"])
                self.assertTrue(partial["refresh_completed"])
                self.assertEqual(partial["refresh_scope"], "entire_network")
                self.assertEqual([row["status"] for row in partial["records"]], ["ok", "absent"])
                self.assertEqual(xml_text(database.get(network, xml=True)), before)
                self.assertFalse([row for row in sim.wire_log if row.get("reason")])
                lifecycle.close(network)
                start = len(sim.wire_log)
                closed = self.cli(*args, "cached", network, "--unit", "4", "--unit", "6", status=1)
                self.assertEqual(closed["records"][0]["serial"], "101136.1558")
                self.assertEqual(closed["records"][1]["status"], "not_cached")
                self.assertFalse(closed["complete"])
                self.assertEqual(len(sim.wire_log), start)
                self.assertIn("InterfaceState", self.cli(*args, "refresh", network, status=1)["error"])
            finally:
                lifecycle.close(network)
                projects.operation("close", project)
                projects.operation("delete", project)

    @unittest.skipUnless(os.environ.get("CBUS_CGATE_TEST_HOST"), "Set CBUS_CGATE_TEST_HOST for native serial population CLI")
    def test_cli_population_preview_backup_noop_and_persistence(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase, NativeProjects
        from cbus_toolkit.networks import NativeNetworks
        from cbus_toolkit.programming import xml_text
        project = "SU" + uuid4().hex[:6].upper()
        network = "//" + project + "/254"
        host, port = os.environ["CBUS_CGATE_TEST_HOST"], int(os.environ.get("CBUS_CGATE_TEST_PORT", "20023"))
        from cbus_toolkit.simulator import PCISimulator
        sim = PCISimulator(profile="synthetic", response_delay=0.01)
        args = ("cgate", "--host", host, "--port", port, "--timeout", "30", "serials", "populate", network)
        backup = None
        with sim.running("0.0.0.0", 0) as (_, sim_port), CGateClient(host, port, timeout=30) as client:
            projects, database, lifecycle = NativeProjects(client), NativeDatabase(client), NativeNetworks(client)
            projects.operation("new", project)
            try:
                database.create_network(project, 254, "Serial_Population_CLI", "Cni",
                    os.environ.get("CBUS_CGATE_SIMULATOR_HOST", "host.docker.internal") + ":" + str(sim_port))
                database.create_unit(network, 4, "Key", "KEYE1", "2.5.00", catalog_number="5031NMML")
                projects.operation("save", project)
                projects.operation("close", project)
                projects.operation("load", project)
                before = xml_text(database.get(network, xml=True))
                lifecycle.open(network)
                self.assertTrue(lifecycle.wait_ready(network, timeout=25)["ready"])
                preview = self.cli(*args, "--dry-run")
                self.assertFalse(preview["updated"])
                self.assertEqual(preview["changes"][0]["new_serial"], "101136.1558")
                self.assertEqual(xml_text(database.get(network, xml=True)), before)
                invalid = self.cli(*args, "--unit", "6", status=1)
                self.assertIn("Selected address", invalid["error"])
                self.assertEqual(xml_text(database.get(network, xml=True)), before)
                result = self.cli(*args)
                backup = result["backup_project"]
                self.assertTrue(result["updated"])
                self.assertTrue(result["project_saved"])
                self.assertEqual(result["changes"], preview["changes"])
                noop = self.cli(*args)
                self.assertFalse(noop["updated"])
                self.assertIsNone(noop["backup_project"])
                self.assertFalse(noop["project_saved"])
                after = xml_text(database.get(network, xml=True))
                projects.operation("close", project)
                projects.operation("load", project)
                self.assertEqual(xml_text(database.get(network, xml=True)), after)
                projects.operation("load", backup)
                from xml.etree import ElementTree
                backup_unit = ElementTree.fromstring(xml_text(database.get(f"//{backup}/254/p/4", xml=True)))
                self.assertEqual(backup_unit.findtext("SerialNumber", ""), preview["changes"][0]["old_serial"])
            finally:
                lifecycle.close(network)
                projects.operation("close", project)
                projects.operation("delete", project)
                if backup:
                    projects.operation("close", backup)
                    projects.operation("delete", backup)


if __name__ == "__main__":
    unittest.main()
