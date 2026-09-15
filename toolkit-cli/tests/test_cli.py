import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path


class CLITests(unittest.TestCase):
    def cli(self, *args, status=0):
        p = subprocess.run([sys.executable, "-m", "cbus_toolkit", *map(str, args)], text=True, capture_output=True)
        self.assertEqual(p.returncode, status, p.stderr + p.stdout)
        return json.loads(p.stdout if p.stdout else p.stderr)

    def test_complete_offline_project_workflow(self):
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / "house.cbz"
            self.cli("project", "new", file, "--name", "TESTHOME")
            self.cli("project", "add", file, "--kind", "network", "--address", "254", "--name", "Local")
            self.cli("project", "add", file, "--kind", "application", "--parent", "/network/254", "--address", "0x38", "--name", "Lighting")
            self.cli("project", "add", file, "--kind", "group", "--parent", "/254/56", "--address", "1", "--name", "Lounge")
            self.cli("project", "add", file, "--kind", "unit", "--parent", "/network/254", "--address", "5", "--name", "Relay")
            self.cli("project", "parameter-set", file, "/network/254/unit/5", "GroupAddress", "1 2 3 4")
            params = self.cli("project", "parameters", file, "/network/254/unit/5")
            self.assertEqual(params["GroupAddress"], "1 2 3 4")
            self.cli("project", "field-set", file, "/254/56/1", "TagName", "Living room")
            self.assertEqual(self.cli("project", "field-get", file, "/254/56/1", "TagName")["value"], "Living room")
            copy = Path(folder) / "copy.xml"
            self.cli("project", "export", file, copy, "--format", "xml")
            self.assertTrue(self.cli("project", "validate", copy)["valid"])
            original_info = self.cli("project", "inspect", file)
            copy_info = self.cli("project", "inspect", copy)
            self.assertEqual(original_info["project"], copy_info["project"])
            self.assertEqual(self.cli("project", "list", file, "--recursive"),
                             self.cli("project", "list", copy, "--recursive"))
            self.cli("project", "copy", file, "/254/56/1", "--parent", "/254/56", "--address", "2", "--name", "Hall")
            self.assertEqual(len(self.cli("project", "list", file, "/254/56", "--kind", "group")), 2)
            self.cli("project", "delete", file, "/254/56/2")
            self.assertEqual(len(self.cli("project", "list", file, "/254/56", "--kind", "group")), 1)

    def test_invalid_mutation_does_not_modify_file(self):
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / "project.xml"
            self.cli("project", "new", file, "--name", "TEST")
            original = file.read_bytes()
            error = self.cli("project", "add", file, "--kind", "group", "--address", "1", status=1)
            self.assertIn("error", error)
            self.assertEqual(file.read_bytes(), original)
            self.cli("project", "new", file, "--name", "REPLACEMENT", status=1)
            self.assertEqual(file.read_bytes(), original)

    def test_coverage_cannot_claim_completion(self):
        result = self.cli("coverage", "--require-complete", status=1)
        self.assertFalse(result["complete"])
        self.assertTrue(any(f["status"] == "pending" for f in result["features"]))

    def test_address_parser_rejects_out_of_range(self):
        p = subprocess.run([sys.executable, "-m", "cbus_toolkit", "pci", "identify", "256", "1"], text=True, capture_output=True)
        self.assertEqual(p.returncode, 2)
        self.assertIn("0..255", p.stderr)
        self.assertNotIn("Traceback", p.stderr)

    def test_serial_matching_cli_reports_conflicts_without_editing_inventories(self):
        with tempfile.TemporaryDirectory() as folder:
            database, network = Path(folder) / "database.json", Path(folder) / "network.json"
            database.write_text(json.dumps({"format": "cbus-unit-inventory-v1", "units": [
                {"address": 20, "unit_type": "KEY4", "serial": "ABC"},
                {"address": 21, "unit_type": "KEY2", "serial": "DEF"}]}))
            network.write_text(json.dumps([
                {"address": 21, "unit_type": "KEY4", "serial": "ABC"},
                {"address": 22, "unit_type": "KEY1", "serial": "DEF"}]))
            original = (database.read_bytes(), network.read_bytes())
            result = self.cli("unit-addressing", "match", database, network)
            self.assertEqual([item["status"] for item in result["matches"]], ["different_address", "type_mismatch"])
            self.assertTrue(result["matches"][0]["database_to_network"]["destination_occupied"])
            self.assertFalse(result["applied"])
            self.assertEqual((database.read_bytes(), network.read_bytes()), original)
            network.write_text('[{"address": true, "unit_type": "KEY4"}]')
            self.assertIn("error", self.cli("unit-addressing", "match", database, network, status=1))

    def test_missing_vendor_directory_has_clear_error(self):
        self.assertIn("error", self.cli("inventory", "--cgate-dir", "/nonexistent-cgate", "manifest", status=1))

    def test_cgate_batch_failure_reports_completed_commands_and_stops(self):
        from test_cgate import peer
        with tempfile.TemporaryDirectory() as folder:
            commands = Path(folder) / "commands.txt"
            commands.write_text("NOOP\nBAD\nNOOP\n")
            with peer([[b"[1] 200 OK.\r\n"], [b"[2] 400 Bad command\r\n"]]) as ((host, port), sent):
                error = self.cli("cgate", "--host", host, "--port", port, "run", commands, status=1)
                self.assertEqual(error["completed_count"], 1)
                self.assertEqual(error["failed_command_index"], 2)
                self.assertEqual(error["completed_responses"][0]["status"], 200)
            self.assertEqual(sent, [b"[1] NOOP\r\n", b"[2] BAD\r\n"])

    def test_cgate_confirmation_required_is_not_reported_as_success(self):
        from test_cgate import peer
        with peer([[b"[1] 600 Please confirm\r\n"]]) as ((host, port), sent):
            error = self.cli("cgate", "--host", host, "--port", port, "exec", "RESTART", status=1)
            self.assertIn("did not complete", error["error"])
        self.assertEqual(sent, [b"[1] RESTART\r\n"])

    def test_trigger_cli_percentage_force_and_unconfirmed_result(self):
        from test_cgate import peer
        with peer([[b"[1] 200 OK.\r\n"]]) as ((host, port), sent):
            result = self.cli("cgate", "--host", host, "--port", port, "trigger", "event", "//HOME/254/202/1", "50%", "--force")
            self.assertTrue(result["queued"])
            self.assertFalse(result["device_verified"])
        self.assertEqual(sent, [b"[1] TRIGGER EVENT //HOME/254/202/1 127 FORCE\r\n"])
        with peer([[b"[1] 600 Please confirm\r\n"]]) as ((host, port), sent):
            result = self.cli("cgate", "--host", host, "--port", port, "trigger", "kill", "//HOME/254/202/1", status=1)
            self.assertIn("did not complete", result["error"])

    def test_scene_file_workflow_preserves_input_copy_and_other_trigger(self):
        with tempfile.TemporaryDirectory() as folder:
            source, copy = Path(folder) / "scene.txt", Path(folder) / "copy.txt"
            self.cli("scene", "new", source, "--play-trigger", "//HOME/254/56/1", "--record-trigger", "//HOME/254/56/2")
            self.cli("scene", "add", source, "//HOME/254/56/3", 128, "--seconds", 4)
            original = source.read_bytes()
            self.cli("scene", "set", source, 0, "//HOME/254/56/3", 255, "--output", copy)
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(self.cli("scene", "show", copy)["actions"][0]["level"], 255)
            changed = self.cli("scene", "triggers", copy, "--play-trigger", "//HOME/254/56/4")
            self.assertEqual(changed["record_trigger"], "//HOME/254/56/2")
            self.assertIsNone(self.cli("scene", "triggers", copy, "--clear-play-trigger")["play_trigger"])
            self.assertEqual(self.cli("scene", "delete", copy, 0)["actions"], [])
            before = source.read_bytes()
            self.cli("scene", "add", source, "//HOME/254/56/3", 128, "--seconds", -1, status=1)
            self.assertEqual(source.read_bytes(), before)
            self.cli("scene", "export", source, copy, status=1)

    def test_scene_cli_reports_only_native_queue_acceptance(self):
        from test_cgate import peer
        with peer([[b"[1] 200 OK.\r\n"]]) as ((host, port), sent):
            result = self.cli("cgate", "--host", host, "--port", port, "scene", "play", "Home", "Evening")
            self.assertTrue(result["queued"])
            self.assertFalse(result["device_verified"])
        self.assertEqual(sent, [b"[1] SCENE PLAY Home Evening\r\n"])
        with peer([[b"[1] 600 Please confirm\r\n"]]) as ((host, port), sent):
            self.assertIn("did not complete", self.cli("cgate", "--host", host, "--port", port, "scene", "record", "Home", "Evening", status=1)["error"])

    def test_scene_execution_and_recording_cli_never_overwrites_partial_reads(self):
        from test_cgate import peer
        with tempfile.TemporaryDirectory() as folder:
            scene, output = Path(folder) / "scene.txt", Path(folder) / "recorded.txt"
            scene.write_text("# Scene\nset //HOME/254/56/1 255\nset //HOME/254/56/2 127 4\n")
            original = scene.read_bytes()
            with peer([[b"[1] 200 OK.\r\n"], [b"[2] 200 OK.\r\n"]]) as ((host, port), sent):
                result = self.cli("cgate", "--host", host, "--port", port, "scene", "execute", scene)
                self.assertTrue(result["queued"])
                self.assertFalse(result["device_verified"])
            self.assertEqual(sent, [b"[1] LIGHTING ON //HOME/254/56/1\r\n", b"[2] LIGHTING RAMP //HOME/254/56/2 127 4\r\n"])
            for last_reply, status in ((b"[2] 408 Network closed\r\n", 1), (b"[2] 300 //HOME/254/56/2: level=64\r\n", 0)):
                with peer([[b"[1] 300 //HOME/254/56/1: level=128\r\n"], [last_reply]]) as ((host, port), sent):
                    result = self.cli("cgate", "--host", host, "--port", port, "scene", "record-file", scene, output, status=status)
                if status:
                    self.assertFalse(output.exists())
                else:
                    self.assertTrue(result["cached"])
                    self.assertFalse(result["device_verified"])
                    self.assertEqual([x["level"] for x in result["actions"]], [128, 64])
                    self.assertEqual([x["ramp_seconds"] for x in result["actions"]], [0, 0])
            self.assertEqual(scene.read_bytes(), original)

    def test_scene_unknown_encoding_and_tls_orphan_key_report_json_errors(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "scene.txt"
            source.write_text("set //HOME/254/56/1 255\n")
            before = source.read_bytes()
            error = self.cli("scene", "--encoding", "invalid-cbus-encoding", "show", source, status=1)
            self.assertEqual(error["type"], "SceneError")
            self.assertEqual(source.read_bytes(), before)
            error = self.cli("cgate", "--tls", "--key", Path(folder) / "client.key", "exec", "NOOP", status=1)
            self.assertEqual(error["error"], "--key requires --cert")

    def test_label_cli_queues_payload_without_claiming_device_delivery(self):
        from test_cgate import peer
        cases = [(("text", "//TEST/254/56", "1", " A  B ", "--variant", "2"), b"LIGHTING LABEL //TEST/254/56 0 1 - F2 0 204120204220"),
                 (("clear", "//TEST/254/56", "1", "--unicode"), b"LIGHTING UNICODELABEL //TEST/254/56 0 1 - F0 RAW"),
                 (("dynamic", "//TEST/254/56", "1", "80", "--icon", "258", "--width", "8", "--height", "1"), b"LIGHTING LABEL //TEST/254/56 0 1 - F0 DYNAMIC 258 8 1 0 80"),
                 (("language", "//TEST/254/56", "1", "--language", "3"), b"LIGHTING LABEL //TEST/254/56 3 1 - F0 SET_LANGUAGE")]
        for arguments, expected in cases:
            with self.subTest(arguments=arguments), peer([[b"[1] 200 OK.\r\n"]]) as ((host, port), sent):
                result = self.cli("cgate", "--host", host, "--port", port, "label", *arguments)
                self.assertTrue(result["queued"])
                self.assertFalse(result["device_verified"])
            self.assertEqual(sent, [b"[1] " + expected + b"\r\n"])

    def test_label_confirmation_and_vendor_failure_are_errors(self):
        from test_cgate import peer
        for response in (b"[1] 600 Please confirm\r\n", b"[1] 408 Network closed\r\n"):
            with self.subTest(response=response), peer([[response]]) as ((host, port), sent):
                result = self.cli("cgate", "--host", host, "--port", port, "label", "text", "//TEST/254/56", "1", "Hello", status=1)
                self.assertIn("error", result)
                self.assertNotIn("queued", result)

    def test_valid_schema_defaults_return_success_and_invalid_defaults_fail(self):
        with tempfile.TemporaryDirectory() as folder:
            spec = Path(folder) / "fixture.xml"
            text = '<UnitSpecification><Type>TEST</Type><Parameters><Param><Name>Value</Name><Type>int</Type><Address>1</Address><DefaultValue>3</DefaultValue><MinValue>0</MinValue><MaxValue>7</MaxValue></Param></Parameters></UnitSpecification>'
            spec.write_text(text)
            result = self.cli("unit-schema", "--spec-dir", folder, "validate-defaults", "fixture.xml")
            self.assertEqual(result, {"checked": 1, "valid": True, "issues": []})
            spec.write_text(text.replace("<DefaultValue>3", "<DefaultValue>8"))
            result = self.cli("unit-schema", "--spec-dir", folder, "validate-defaults", "fixture.xml", status=1)
            self.assertFalse(result["valid"])

    def test_memory_cli_mask_patch_preserves_neighboring_bits(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            spec = directory / "fixture.xml"
            spec.write_text('<UnitSpecification><Type>TEST</Type><Parameters><Param><Name>Nibble</Name><Type>int</Type><Address>10</Address><BitSize>4</BitSize><BitAddress>4</BitAddress></Param></Parameters></UnitSpecification>')
            image, patch, output = (directory / name for name in ("image.json", "patch.json", "output.json"))
            image.write_text(json.dumps({"format": "cbus-sparse-memory-v1", "bytes": {"10": 0xab}}))
            prefix = ("memory", "--spec-dir", directory)
            result = self.cli(*prefix, "encode", spec.name, "Nibble", "5")
            self.assertEqual(result["edits"], [{"address": 10, "value": 0x50, "mask": 0xf0}])
            patch.write_text(json.dumps(result))
            self.cli("memory", "apply", image, patch, output)
            self.assertEqual(json.loads(output.read_text())["bytes"], {"10": 0x5b})
            self.assertEqual(json.loads(image.read_text())["bytes"], {"10": 0xab})
            self.assertEqual(self.cli(*prefix, "decode", spec.name, "Nibble", output)["value"], 5)
            self.cli("memory", "apply", image, patch, output, status=1)

    def test_calculator_cli_electrical_result_controls_exit_status(self):
        with tempfile.TemporaryDirectory() as folder:
            catalog, units = Path(folder) / "catalog.xml", Path(folder) / "units.json"
            catalog.write_text('<CBusUnits><Calculator><MinImpedance>400</MinImpedance><MaxImpedance>1500</MaxImpedance><MaxSupplyCurrent>2000</MaxSupplyCurrent></Calculator><Units><Unit><CatalogNumber>FIXTURE</CatalogNumber><Impedance>1000</Impedance><CurrentDrawn>18</CurrentDrawn><CurrentSupplied>350</CurrentSupplied></Unit></Units></CBusUnits>')
            units.write_text(json.dumps([{"catalog_number": "FIXTURE", "unit_type": "TEST"}]))
            result = self.cli("calculator", "--catalog", catalog, units)
            self.assertTrue(result["passed"])
            self.assertEqual(result["impedance_ohms"], 1000)
            units.write_text(json.dumps([{"catalog_number": "FIXTURE", "unit_type": "TEST"}, {"catalog_number": "MISSING", "unit_type": "TEST"}]))
            result = self.cli("calculator", "--catalog", catalog, units, status=1)
            self.assertFalse(result["passed"])
            self.assertEqual(result["units_not_calculated"], 1)

    def test_simulator_and_pci_cli_persistent_write_workflow(self):
        from cbus_toolkit.simulator import PCISimulator
        with tempfile.TemporaryDirectory() as folder:
            state = Path(folder) / "state.json"
            with PCISimulator(state_path=state).running() as (host, port):
                prefix = ("pci", "--host", host, "--port", port, "--local-unit", 16)
                self.assertEqual(self.cli(*prefix, "identify", 16, 1)["result"], b"PC_CNIED".hex())
                self.cli(*prefix, "write", 5, 0, "41a000")
                self.assertEqual(self.cli(*prefix, "recall", 5, 0, 3)["result"], "41a000")
            with PCISimulator(state_path=state).running() as (host, port):
                self.assertEqual(self.cli("pci", "--host", host, "--port", port, "recall", 5, 0, 3)["result"], "41a000")

    def test_classic_preset_listing(self):
        presets = {item["name"]: item for item in self.cli("keys", "presets")}
        self.assertEqual(len(presets), 18)
        self.assertEqual(presets["bellpress"]["codes"],
                         {"JPCommand": 13, "SRCommand": 15, "LPCommand": 13, "LRCommand": 15})

    @unittest.skipUnless(os.environ.get("CBUS_UNITSPEC_DIR"), "set CBUS_UNITSPEC_DIR for vendor classic key schema")
    def test_offline_classic_key_plan_and_identity_guard(self):
        directory = os.environ["CBUS_UNITSPEC_DIR"]
        defaults = self.cli("unit-schema", "--spec-dir", directory, "defaults", "KEY4.xml")
        with tempfile.TemporaryDirectory() as folder:
            snapshot = Path(folder) / "values.json"
            snapshot.write_text(json.dumps(defaults))
            arguments = ("keys", "--spec-dir", directory, "plan", "KEY4.xml", snapshot,
                         "--key", 1, "--preset", "timer", "--group", 42, "--timer-seconds", 300)
            result = self.cli(*arguments)
            self.assertEqual(result["changes"]["GroupAddress"][0], 42)
            self.assertEqual(result["changes"]["TimerHighByte"][0], 1)
            self.assertEqual(result["changes"]["TimerLowByte"][0], 44)
            self.assertFalse(result["saved"])
            self.assertEqual(json.loads(snapshot.read_text()), defaults)
            snapshot.write_text(json.dumps({"format": "cbus-cli-parameters-v1", "unit_type": "KEYGL5", "parameters": defaults}))
            self.assertIn("differs", self.cli(*arguments, status=1)["error"])

    @unittest.skipUnless(os.environ.get("CBUS_UNITSPEC_DIR"), "set CBUS_UNITSPEC_DIR for offline conversion CLI")
    def test_offline_alignment_plan_retains_target_identity(self):
        directory = os.environ["CBUS_UNITSPEC_DIR"]
        source = self.cli("unit-schema", "--spec-dir", directory, "defaults", "KEY4.xml")
        target = self.cli("unit-schema", "--spec-dir", directory, "defaults", "KEY2.xml")
        source["GroupAddress"] = "1 2 3 4 5 6 7 8"
        with tempfile.TemporaryDirectory() as folder:
            first, second = Path(folder) / "source.json", Path(folder) / "target.json"
            first.write_text(json.dumps(source))
            second.write_text(json.dumps(target))
            result = self.cli("unit-conversion", "--spec-dir", directory, "plan", "KEY4.xml", "KEY2.xml", first, second)
            self.assertEqual(result["changes"]["GroupAddress"], list(range(1, 9)))
            self.assertIn("UnitAddress", result["retained_target"])
            self.assertFalse(result["saved"])
            self.assertEqual(json.loads(second.read_text()), target)


@unittest.skipUnless(os.environ.get("CBUS_CGATE_TEST_HOST"), "set CBUS_CGATE_TEST_HOST for disposable real-server CLI acceptance")
class CLINativeTests(unittest.TestCase):
    def cli(self, *args):
        p = subprocess.run([sys.executable, "-m", "cbus_toolkit", "cgate", "--host", os.environ["CBUS_CGATE_TEST_HOST"],
                            "--port", os.environ.get("CBUS_CGATE_TEST_PORT", "20023"), *map(str, args)], text=True, capture_output=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return json.loads(p.stdout)

    def test_unit_cli_edits_persist_and_dry_run_does_not(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase, NativeProjects
        from cbus_toolkit.programming import Programmer, parameter_values
        name = "C" + uuid.uuid4().hex[:7].upper()
        with CGateClient(os.environ["CBUS_CGATE_TEST_HOST"], int(os.environ.get("CBUS_CGATE_TEST_PORT", "20023"))) as client:
            projects, database = NativeProjects(client), NativeDatabase(client)
            projects.operation("new", name)
            saved = False
            try:
                database.create_network(name, 254, "Local", "Cni", "127.0.0.1:29999")
                created = self.cli("database", "unit-new", f"//{name}/254", 21, "eDLT fixture", "KEYGL5", "5.5.00", "--catalog-number", "5055EDL")
                self.assertGreaterEqual(created["parameter_count"], 800)
                edlt = self.cli("unit", "--lock-address", f"//{name}/254", "--source", f"/db//{name}/254/p/21", "get", "UnitAddress")
                self.assertEqual(edlt["UnitAddress"], "0x15")
                database.add(f"//{name}/254", "unit", 20, "Key input")
                database.set(f"//{name}/254/p/20/UnitType", "KEY4")
                database.set(f"//{name}/254/p/20/UnitName", "KEY4")
                database.set(f"//{name}/254/p/20/FirmwareVersion", "1.2.67")
                destination = f"/db//{name}/254/p/20"
                result = self.cli("unit", "--lock-address", f"//{name}/254", "--unit-type", "KEY4", "--firmware", "1.2.67",
                                  "--destination", destination, "set", "UnitName", "LOUNGE")
                self.assertTrue(result["saved"])
                self.assertEqual(parameter_values(Programmer(client).quickget(f"//{name}/254/p/20", "UnitName"))["UnitName"].strip(), "LOUNGE")
                result = self.cli("unit", "--lock-address", f"//{name}/254", "--source", destination, "--dry-run", "set", "UnitName", "HALL")
                self.assertFalse(result["saved"])
                self.assertEqual(result["parameters"]["UnitName"].strip(), "HALL")
                unchanged = self.cli("unit", "--lock-address", f"//{name}/254", "--source", destination, "get", "UnitName")
                self.assertEqual(unchanged["UnitName"].strip(), "LOUNGE")
                projects.operation("save", name)
                saved = True
            finally:
                projects.operation("close", name)
                if saved:
                    projects.operation("delete", name)

    def test_readdress_cli_keeps_database_and_programming_addresses_together(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase, NativeProjects
        name = "U" + uuid.uuid4().hex[:7].upper()
        backup = None
        with CGateClient(os.environ["CBUS_CGATE_TEST_HOST"], int(os.environ.get("CBUS_CGATE_TEST_PORT", "20023"))) as client:
            projects, db = NativeProjects(client), NativeDatabase(client)
            projects.operation("new", name)
            try:
                network = f"//{name}/254"
                db.create_network(name, 254, "Offline", "Cni", "127.0.0.1:29999")
                db.create_unit(network, 20, "Retained room", "KEY4", "1.2.67")
                original = self.cli("address", "inventory", network)
                self.assertEqual(original["units"][0]["address"], 20)
                preview = self.cli("address", "readdress", network + "/p/20", 31, "--dry-run")
                self.assertFalse(preview["readdressed"])
                self.assertEqual(self.cli("address", "inventory", network), original)
                result = self.cli("address", "readdress", network + "/p/20", 31)
                backup = result["backup_project"]
                self.assertTrue(result["readdressed"])
                self.assertTrue(result["metadata_verified"])
                self.assertFalse(result["hardware_programmed"])
                projects.operation("close", name)
                projects.operation("load", name)
                values = self.cli("unit", "--lock-address", network, "--source", "/db" + network + "/p/31", "get", "UnitAddress")
                self.assertEqual(values["UnitAddress"], "0x1f")
                self.assertEqual(self.cli("address", "inventory", network)["units"][0]["address"], 31)
                self.assertIn("Retained room", db.get(network + "/p/31/TagName").final)
            finally:
                projects.operation("close", name)
                if backup:
                    projects.operation("delete", name)
                    projects.operation("delete", backup)

    def test_network_readdress_cli_preserves_unit_programming_and_moves_both_layers(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase, NativeProjects
        name = "N" + uuid.uuid4().hex[:7].upper()
        backup = None
        with CGateClient(os.environ["CBUS_CGATE_TEST_HOST"], int(os.environ.get("CBUS_CGATE_TEST_PORT", "20023"))) as client:
            projects, db = NativeProjects(client), NativeDatabase(client)
            projects.operation("new", name)
            try:
                source, target = f"//{name}/254", f"//{name}/253"
                db.create_network(name, 254, "Offline", "Cni", "127.0.0.1:29999")
                db.create_unit(source, 20, "Switch", "KEY4", "1.2.67")
                original = self.cli("unit", "--lock-address", source, "--source", "/db" + source + "/p/20", "show")
                preview = self.cli("address", "network-readdress", source, 253, "--dry-run")
                self.assertFalse(preview["readdressed"])
                self.assertEqual(self.cli("address", "inventory", source)["units"][0]["address"], 20)
                result = self.cli("address", "network-readdress", source, 253)
                backup = result["backup_project"]
                self.assertTrue(result["readdressed"])
                self.assertTrue(result["database_runtime_consistent"])
                self.assertTrue(result["parameters_verified"])
                self.assertFalse(result["hardware_programmed"])
                projects.operation("close", name)
                projects.operation("load", name)
                self.assertEqual(self.cli("unit", "--lock-address", target, "--source", "/db" + target + "/p/20", "show"), original)
                self.assertIn("InterfaceState=closed", client.command("GET " + target + " InterfaceState").final)
            finally:
                projects.operation("close", name)
                if backup:
                    projects.operation("delete", name)
                    projects.operation("delete", backup)

    def test_cgl_cli_default_backup_and_export(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase, NativeProjects
        name = "X" + uuid.uuid4().hex[:7].upper()
        backup = None
        with CGateClient(os.environ["CBUS_CGATE_TEST_HOST"], int(os.environ.get("CBUS_CGATE_TEST_PORT", "20023"))) as client:
            projects, database = NativeProjects(client), NativeDatabase(client)
            projects.operation("new", name)
            saved = False
            try:
                database.create_network(name, 254, "Local", "Cni", "127.0.0.1:29999")
                with tempfile.TemporaryDirectory() as folder:
                    source, target = Path(folder) / "source.cgl", Path(folder) / "result.cgl"
                    source.write_text(json.dumps({"cglVersion": "1.1", "localNetwork": 254,
                        "networks": [{"address": 254, "name": "Local", "applications": [
                            {"address": 56, "type": 56, "name": "Lighting", "groups": [{"address": 1, "name": "Hall"}]}]}]}))
                    result = self.cli("cgl", "import", name, source)
                    backup = result["backup_project"]
                    saved = True
                    self.assertTrue(result["complete"])
                    self.assertTrue(backup.startswith("B"))
                    result = self.cli("cgl", "export", name, target, "--network", 254, "--application", 56)
                    self.assertEqual(result["groups"], 1)
                    self.assertEqual(json.loads(target.read_text())["networks"][0]["applications"][0]["groups"][0]["name"], "Hall")
            finally:
                projects.operation("close", name)
                if saved:
                    projects.operation("delete", name)
                if backup:
                    projects.operation("delete", backup)

    @unittest.skipUnless(os.environ.get("CBUS_UNITSPEC_DIR"), "set CBUS_UNITSPEC_DIR for native classic key acceptance")
    def test_classic_key_cli_dry_run_then_persist(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase, NativeProjects
        name = "K" + uuid.uuid4().hex[:7].upper()
        with CGateClient(os.environ["CBUS_CGATE_TEST_HOST"], int(os.environ.get("CBUS_CGATE_TEST_PORT", "20023"))) as client:
            projects, database = NativeProjects(client), NativeDatabase(client)
            projects.operation("new", name)
            try:
                network = f"//{name}/254"
                database.create_network(name, 254, "Local", "Cni", "127.0.0.1:29999")
                database.create_unit(network, 20, "Classic fixture", "KEY4", "1.2.67")
                prefix = ("unit", "--lock-address", network, "--source", f"/db{network}/p/20")
                macro = ("key-macro", "--spec", "KEY4.xml", "--key", 1, "--preset", "timer",
                         "--group", 42, "--timer-seconds", 300)
                original = self.cli(*prefix, "show")
                preview = self.cli(*prefix, "--dry-run", *macro)
                self.assertFalse(preview["saved"])
                self.assertTrue(preview["verified"])
                self.assertEqual(self.cli(*prefix, "show"), original)
                applied = self.cli(*prefix, *macro)
                self.assertTrue(applied["saved"])
                self.assertEqual(self.cli(*prefix, "show"), applied["parameters"])
                self.assertEqual(applied["parameters"]["TimerLowByte"].split()[0], "0x2c")
            finally:
                projects.operation("close", name)

    @unittest.skipUnless(os.environ.get("CBUS_UNITSPEC_DIR"), "set CBUS_UNITSPEC_DIR for Neo-core CLI acceptance")
    def test_neo_key_cli_switches_scene_key_to_preset_and_verifies_secondary_block(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase, NativeProjects
        name = "K" + uuid.uuid4().hex[:7].upper()
        with CGateClient(os.environ["CBUS_CGATE_TEST_HOST"], int(os.environ.get("CBUS_CGATE_TEST_PORT", "20023"))) as client:
            projects, db = NativeProjects(client), NativeDatabase(client)
            projects.operation("new", name)
            try:
                network = f"//{name}/254"
                db.create_network(name, 254, "Offline", "Cni", "127.0.0.1:29999")
                db.create_unit(network, 20, "Neo fixture", "KEYM4", "2.5.00", catalog_number="5054NL")
                prefix = ("unit", "--lock-address", network, "--source", "/db" + network + "/p/20")
                self.cli(*prefix, "set", "Application", "56 57")
                self.cli(*prefix, "set", "SceneKeySelector", "0 0 0 1 0 0 0 0")
                original = self.cli(*prefix, "show")
                options = ("neo-key-macro", "--spec", "KEYM4.xml", "--key", 4, "--preset", "timer",
                           "--group", 31, "--timer-seconds", 300, "--application", "secondary", "--indicator-block", 8)
                preview = self.cli(*prefix, "--dry-run", *options)
                self.assertFalse(preview["saved"])
                self.assertTrue(preview["verified"])
                self.assertEqual(self.cli(*prefix, "show"), original)
                applied = self.cli(*prefix, *options)
                self.assertTrue(applied["saved"])
                values = self.cli(*prefix, "show")
                self.assertEqual(values, applied["parameters"])
                self.assertEqual(values["SceneTable"], original["SceneTable"])
                self.assertEqual(int(values["SceneKeySelector"].split()[3], 0), 0)
                self.assertEqual(int(values["SecondApplicationBlocks"], 0), 8)
                self.assertEqual(int(values["TimerLowByte"].split()[3], 0), 44)
                self.assertEqual(int(values["IndicatorBlockAssignment"].split()[3], 0), 7)
            finally:
                projects.operation("close", name)

    def test_native_conversion_cli_check_and_default_backup(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase, NativeProjects
        project = "V" + uuid.uuid4().hex[:7].upper()
        backup = None
        with CGateClient(os.environ["CBUS_CGATE_TEST_HOST"], int(os.environ.get("CBUS_CGATE_TEST_PORT", "20023"))) as client:
            projects, db = NativeProjects(client), NativeDatabase(client)
            projects.operation("new", project)
            try:
                network = f"//{project}/254"
                source = network + "/p/20"
                db.create_network(project, 254, "Offline", "Cni", "127.0.0.1:29999")
                db.create_unit(network, 20, "Dimmer", "DIMDN4", "2.7.00", catalog_number="L5504D2A")
                self.assertTrue(self.cli("conversion", "check-catalog", source, "DIMDU4", "L5504D2U")["allowed"])
                result = self.cli("conversion", "catalog", source, "DIMDU4", "L5504D2U")
                backup = result["backup_project"]
                self.assertTrue(backup.startswith("B"))
                self.assertTrue(result["converted"])
                self.assertEqual(result["after"]["unit_type"], "DIMDU4")
                self.assertFalse(result["hardware_programmed"])
            finally:
                projects.operation("close", project)
                if backup:
                    projects.operation("delete", project)
                    projects.operation("delete", backup)

    @unittest.skipUnless(os.environ.get("CBUS_UNITSPEC_DIR"), "set CBUS_UNITSPEC_DIR for classic alignment CLI")
    def test_classic_alignment_cli_preview_backup_and_destination_identity(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase, NativeProjects
        name = "A" + uuid.uuid4().hex[:7].upper()
        backup = None
        with CGateClient(os.environ["CBUS_CGATE_TEST_HOST"], int(os.environ.get("CBUS_CGATE_TEST_PORT", "20023"))) as client:
            projects, db = NativeProjects(client), NativeDatabase(client)
            projects.operation("new", name)
            try:
                network = f"//{name}/254"
                source, target = network + "/p/20", network + "/p/21"
                db.create_network(name, 254, "Offline", "Cni", "127.0.0.1:29999")
                db.create_unit(network, 20, "Source", "KEY4", "1.2.67")
                db.create_unit(network, 21, "Target", "KEY2", "1.2.67")
                self.cli("unit", "--lock-address", network, "--source", "/db" + source, "set", "GroupAddress", "1 2 3 4 5 6 7 8")
                args = ("conversion", "align", source, target, "--source-spec", "KEY4.xml", "--target-spec", "KEY2.xml")
                preview = self.cli(*args, "--dry-run")
                self.assertFalse(preview["saved"])
                self.assertIsNone(preview["backup_project"])
                self.assertEqual(self.cli("unit", "--lock-address", network, "--source", "/db" + target, "get", "GroupAddress")["GroupAddress"], "0xff 0xff 0xff 0xff 0xff 0xff 0xff 0xff")
                applied = self.cli(*args)
                backup = applied["backup_project"]
                self.assertTrue(applied["saved"])
                values = self.cli("unit", "--lock-address", network, "--source", "/db" + target, "show")
                self.assertEqual(values["UnitAddress"], "0x15")
                self.assertEqual(values["GroupAddress"], "0x1 0x2 0x3 0x4 0x5 0x6 0x7 0x8")
                self.assertIn("Source", db.get(source + "/TagName").final)
                self.assertIn("Target", db.get(target + "/TagName").final)
            finally:
                projects.operation("close", name)
                if backup:
                    projects.operation("delete", name)
                    projects.operation("delete", backup)

    @unittest.skipUnless(os.environ.get("CBUS_UNITSPEC_DIR"), "set CBUS_UNITSPEC_DIR for classic replacement CLI")
    def test_classic_replacement_cli_preview_backup_and_reopen(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase, NativeProjects
        name = "R" + uuid.uuid4().hex[:7].upper()
        backup = None
        with CGateClient(os.environ["CBUS_CGATE_TEST_HOST"], int(os.environ.get("CBUS_CGATE_TEST_PORT", "20023"))) as client:
            projects, db = NativeProjects(client), NativeDatabase(client)
            projects.operation("new", name)
            try:
                network, source = f"//{name}/254", f"//{name}/254/p/20"
                db.create_network(name, 254, "Offline", "Cni", "127.0.0.1:29999")
                db.create_unit(network, 20, "Original room", "KEY4", "1.2.67", catalog_number="5034N")
                db.set(source + "/Description", "Retained installer note")
                pp = ("unit", "--lock-address", network, "--source", "/db" + source)
                self.cli(*pp, "set", "GroupAddress", "1 2 3 4 5 6 7 8")
                original = db.get(source, xml=True).lines
                args = ("conversion", "replace", source, "--source-spec", "KEY4.xml", "--target-spec", "KEY1.xml",
                        "--firmware", "1.2.67", "--catalog-number", "5031N", "--learned-policy", "preserve_source")
                preview = self.cli(*args, "--dry-run")
                self.assertFalse(preview["replaced"])
                self.assertEqual(db.get(source, xml=True).lines, original)
                applied = self.cli(*args)
                backup = applied["backup_project"]
                self.assertTrue(applied["replaced"])
                self.assertTrue(applied["project_saved"])
                self.assertTrue(applied["metadata_verified"])
                self.assertNotEqual(applied["old_oid"], applied["new_oid"])
                self.assertFalse(applied["hardware_programmed"])
                projects.operation("close", name)
                projects.operation("load", name)
                values = self.cli(*pp, "show")
                self.assertEqual(values["UnitAddress"], "0x14")
                self.assertEqual(values["GroupAddress"], "0x1 0x2 0x3 0x4 0x5 0x6 0x7 0x8")
                self.assertIn("KEY1", db.get(source + "/UnitType").final)
                self.assertIn("Original room", db.get(source + "/TagName").final)
                self.assertIn("Retained installer note", db.get(source + "/Description").final)
            finally:
                projects.operation("close", name)
                if backup:
                    projects.operation("delete", name)
                    projects.operation("delete", backup)


if __name__ == "__main__":
    unittest.main()
