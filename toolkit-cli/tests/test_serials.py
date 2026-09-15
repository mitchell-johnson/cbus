"""Serial inventory grammar, partial failures, and isolated native acceptance."""
import json
import os
from pathlib import Path
import struct
import unittest
from unittest import mock
from uuid import uuid4

from cbus_toolkit.addressing import UnitIdentity, match_serials
from cbus_toolkit.cgate import CGateClient, CGateError, CGateResponse
from cbus_toolkit.native import NativeDatabase, NativeProjects
from cbus_toolkit.networks import NativeNetworks
from cbus_toolkit.programming import xml_text
from cbus_toolkit.serials import NativeSerialNumber, NativeSerials, SerialTransportError, parse_native_serial
from cbus_toolkit.simulator import PCISimulator

NET = "//SERTEST/254"


def reply(*lines):
    return CGateResponse(tuple(lines), lines[-1], int(lines[-1][:3]))


class FakeClient:
    def __init__(self):
        self.commands = []
        self.overrides = {}
        self.network = {"Units": "4,5,16", "InterfaceState": "running", "TargetInterfaceState": "running",
                        "SyncState": "idle", "AutoUnravel": "no", "AutoUpdate": "no"}
        self.units = {4: {"Address": "4", "Type": "KEYE1", "Version": "2.5.00", "SerialNumber": "101136.1558", "State": "ok"},
                      5: {"Address": "5", "Type": "KEYGL5", "Version": "5.5.00", "SerialNumber": "101183.1666", "State": "ok"},
                      16: {"Address": "16", "Type": "PC_CNIED", "Version": "5.5.00", "SerialNumber": "100966.1187", "State": "ok"}}

    def command(self, command):
        self.commands.append(command)
        if command in self.overrides:
            result = self.overrides[command]
            if isinstance(result, Exception): raise result
            return result
        if command.startswith("GET "):
            _, path, field = command.split(" ", 2)
            try:
                value = self.network[field] if path == NET else self.units[int(path.rsplit("/", 1)[1])][field]
            except (KeyError, ValueError):
                raise CGateError(reply("401 Bad object or device ID."))
            return reply(f"300 {path}: {field}={value}")
        if command == "NET SYNC " + NET + " fast": return reply("120-Network sync started", "200 OK.")
        if command.startswith("NET CHECKUNIT " + NET + " "):
            selected = command.rsplit(" ", 1)[1]
            addresses = self.units if selected == "*" else [int(a) for a in selected.split(",")]
            rows = [f"120-{'Single unit' if a in self.units else 'No units'} detected at address: {a}" for a in addresses]
            rows[-1] = rows[-1].replace("120-", "120 ", 1)
            return reply(*rows)
        raise AssertionError("Unexpected command: " + command)


class SerialNumberTests(unittest.TestCase):
    def test_native_decimal_components_and_placeholders(self):
        for text, canonical, known in (("00101136.1558", "101136.1558", True), ("00000000.0000", "0.0", False),
                                       ("1048575.4095", "1048575.4095", False), ("0.1", "0.1", True),
                                       ("1048575.4094", "1048575.4094", True)):
            with self.subTest(text=text):
                parsed = parse_native_serial(text)
                self.assertEqual((parsed.canonical, parsed.known), (canonical, known))
        for value in (None, "", "1", "1.2.3", "-1.2", "1.4096", "1048576.0", " 1.2", "1.2 ", "A123.456", "0" * 17 + ".1"):
            with self.subTest(value=value), self.assertRaises(ValueError): parse_native_serial(value)
        for args in ((True, 1), (1, False), (1.0, 2), (0, -1)):
            with self.subTest(args=args), self.assertRaises(ValueError): NativeSerialNumber(*args)

    def test_native_match_is_explicit_and_preserves_original_serials(self):
        database = [UnitIdentity(4, "KEYE1", "00101136.1558")]
        network = [UnitIdentity(5, "KEYE1", "101136.1558")]
        opaque = match_serials(database, network)
        self.assertEqual([r["status"] for r in opaque["matches"]], ["database_only", "network_only"])
        report = match_serials(database, network, native_serials=True)
        self.assertEqual(report["matches"][0]["status"], "different_address")
        self.assertEqual(report["matches"][0]["serial"], "101136.1558")
        self.assertEqual(report["matches"][0]["database"][0]["serial"], "00101136.1558")
        self.assertFalse(report["applied"])
        with self.assertRaises(ValueError): match_serials([], [], native_serials=1)

    def test_native_match_excludes_invalid_unset_and_duplicate_serials(self):
        db = [UnitIdentity(1, "KEY1", "00000000.0000"), UnitIdentity(2, "KEY1", "1048575.4095"),
              UnitIdentity(3, "KEY1", "bad"), UnitIdentity(4, "KEY1", "0001.02"), UnitIdentity(5, "KEY1", "1.2")]
        report = match_serials(db, [UnitIdentity(6, "KEY1", "1.2")], native_serials=True)
        self.assertEqual(report["matches"][0]["status"], "ambiguous_serial")
        self.assertEqual(len(report["unidentified_database"]), 3)
        self.assertEqual([u["address"] for u in report["invalid_database_serials"]], [3])
        self.assertEqual(report["invalid_network_serials"], [])


class SerialInventoryTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeClient()
        self.serials = NativeSerials(self.client)

    def test_cached_only_explicit_properties_and_closed_is_allowed(self):
        self.client.network["InterfaceState"] = "closed"
        inventory = self.serials.cached(NET)
        self.assertTrue(inventory.complete)
        self.assertEqual([u.address for u in inventory.identities], [4, 5, 16])
        self.assertEqual(inventory.records[0].as_dict()["unit_type"], "KEYE1")
        self.assertEqual(len(self.client.commands), 16)
        self.assertTrue(all(c.startswith("GET ") and not c.endswith(" *") for c in self.client.commands))
        self.assertFalse(inventory.refresh_completed)
        self.assertFalse(inventory.as_dict()["database_updated"])
        self.assertFalse(inventory.as_dict()["mmi_coverage_verified"])
        json.dumps(inventory.as_dict())

    def test_cached_subset_missing_address_is_not_invented(self):
        inventory = self.serials.cached(NET, [6, 4])
        self.assertEqual(inventory.requested, (4, 6))
        self.assertEqual([r.status for r in inventory.records], ["ok", "not_cached"])
        self.assertEqual([u.address for u in inventory.identities], [4])
        self.assertFalse(any("/p/6" in c for c in self.client.commands))
        self.assertFalse(inventory.complete)

    def test_cached_partial_field_error_preserves_other_unit_results(self):
        self.client.overrides[f"GET {NET}/p/4 SerialNumber"] = CGateError(reply("408 Unit failed to respond."))
        inventory = self.serials.cached(NET)
        self.assertEqual(inventory.records[0].status, "read_error")
        self.assertIn("SerialNumber:", inventory.records[0].errors[0])
        self.assertEqual([u.address for u in inventory.identities], [5, 16])

    def test_unset_malformed_and_duplicate_serials(self):
        for serial, status in (("", "missing_serial"), ("0.0", "missing_serial"),
                               ("1048575.4095", "missing_serial"), ("not-native", "invalid_serial")):
            with self.subTest(serial=serial):
                self.client.units[4]["SerialNumber"] = serial
                inventory = self.serials.cached(NET, [4])
                self.assertEqual(inventory.records[0].status, status)
                self.assertEqual(inventory.identities[0].serial, "")
        self.client.units[4]["SerialNumber"] = "00100966.1187"
        inventory = self.serials.cached(NET)
        self.assertEqual([r.status for r in inventory.records], ["duplicate_serial", "ok", "duplicate_serial"])
        self.assertEqual(inventory.identities[0].serial, "100966.1187")
        self.assertFalse(inventory.complete)

    def test_path_address_state_and_reply_validation(self):
        for path in ("254", "//TOOLONGXX/1", "//OK/256", "//OK/254/p/4", "//OK/1\rGET *"):
            with self.subTest(path=path), self.assertRaises(ValueError): self.serials.cached(path)
        for selection in ([], [4, 4], [-1], [256], [True], ["4"]):
            with self.subTest(selection=selection), self.assertRaises(ValueError): self.serials.cached(NET, selection)
        for bad in (reply("300 //OTHER/254/p/4: Address=4"), reply(f"300 {NET}/p/4: Type=KEYE1"),
                    reply("600 Not implemented."), reply(f"300-{NET}/p/4: Address=4", "408 no response")):
            with self.subTest(bad=bad):
                self.client.overrides[f"GET {NET}/p/4 Address"] = bad
                self.assertEqual(self.serials.cached(NET, [4]).records[0].status, "read_error")
        self.client.overrides.clear()
        self.client.units[4]["Address"] = "5"
        self.assertIn("differs", self.serials.cached(NET, [4]).records[0].errors[0])
        self.client.units[4]["Address"] = "4"
        self.client.units[4]["State"] = "new"
        self.assertEqual(self.serials.cached(NET, [4]).records[0].status, "unit_not_ok")
        self.assertEqual(self.serials.cached(NET, [4]).identities, ())

    def test_cached_list_failure_is_explicit_with_partial_selected_results(self):
        for value in ("4,4", "4,256", "garbage"):
            with self.subTest(value=value):
                self.client.network["Units"] = value
                inventory = self.serials.cached(NET, [4])
                self.assertTrue(inventory.errors)
                self.assertFalse(inventory.complete)
                self.assertEqual(len(inventory.identities), 1)
        self.assertEqual(self.serials.cached(NET).identities, ())

    def test_refresh_scope_and_explicit_absence(self):
        inventory = self.serials.refresh(NET, [4, 5, 6])
        self.assertTrue(inventory.refresh_completed)
        self.assertEqual([r.presence for r in inventory.records], ["single", "single", "absent"])
        self.assertEqual([u.address for u in inventory.identities], [4, 5])
        self.assertIn("NET SYNC " + NET + " fast", self.client.commands)
        self.assertIn("NET CHECKUNIT " + NET + " 4,5,6", self.client.commands)
        self.assertEqual(inventory.as_dict()["refresh_scope"], "entire_network")
        self.assertFalse(inventory.complete)

    def test_refresh_guards_do_not_modify_network_configuration(self):
        for field, value in (("InterfaceState", "closed"), ("TargetInterfaceState", "closed"),
                             ("SyncState", "running"), ("AutoUnravel", "yes"), ("AutoUpdate", "yes")):
            with self.subTest(field=field):
                client = FakeClient(); client.network[field] = value
                with self.assertRaisesRegex(ValueError, field): NativeSerials(client).refresh(NET)
                self.assertTrue(all(c.startswith("GET ") for c in client.commands))

    def test_failed_refresh_never_exports_stale_identity_as_refreshed(self):
        for failed in (CGateError(reply("408 Native sync failed.")), reply("600 Unsupported."),
                       reply("408-Native sync failed.", "200 OK.")):
            with self.subTest(failed=failed):
                self.client.commands.clear()
                self.client.overrides["NET SYNC " + NET + " fast"] = failed
                inventory = self.serials.refresh(NET)
                self.assertFalse(inventory.refresh_completed)
                self.assertEqual(inventory.identities, ())
                self.assertTrue(inventory.errors)
                self.assertFalse(any(c.startswith("NET CHECKUNIT") for c in self.client.commands))

    def test_transport_failures_stop_without_later_commands_or_reconnect(self):
        for method, command in (("cached", "GET " + NET + " Units"),
                                ("cached", f"GET {NET}/p/4 Type"),
                                ("refresh", "GET " + NET + " InterfaceState"),
                                ("refresh", "NET SYNC " + NET + " fast"),
                                ("refresh", "NET CHECKUNIT " + NET + " *")):
            with self.subTest(command=command):
                client = FakeClient()
                client.overrides[command] = TimeoutError("stream timed out")
                with self.assertRaisesRegex(SerialTransportError, "incomplete"):
                    getattr(NativeSerials(client), method)(NET)
                self.assertEqual(client.commands[-1], command)

    def test_real_transport_invalid_frame_stops_getter_loop(self):
        from tests.test_cgate import peer
        for broken in (b"[99] 300 wrong tag\r\n", b"[2] 300 invalid\xff\r\n", b"[2] 300 incomplete"):
            with self.subTest(broken=broken):
                responses = [[f"[1] 300 {NET}: Units=4\r\n".encode()], [broken]]
                with peer(responses) as (address, sent), CGateClient(*address, timeout=1) as client:
                    with mock.patch.object(client, "command", wraps=client.command) as command:
                        with self.assertRaises(SerialTransportError): NativeSerials(client).cached(NET)
                        self.assertFalse(client.connected)
                        self.assertEqual(command.call_count, 2)
                self.assertEqual(len(sent), 2)

    def test_multiplicity_errors_and_missing_check_results(self):
        command = "NET CHECKUNIT " + NET + " 4,5,16"
        self.client.overrides[command] = reply("120-Duplicate units detected at address: 4",
            "120-Single unit with error detected at address: 5", "120 One or more units detected at address: 16")
        inventory = self.serials.refresh(NET, [4, 5, 16])
        self.assertEqual([r.status for r in inventory.records], ["duplicate_address", "single_error", "uncertain"])
        self.assertEqual(inventory.identities, ())
        self.client.overrides[command] = reply("120 Single unit detected at address: 4")
        inventory = self.serials.refresh(NET, [4, 5, 16])
        self.assertEqual([r.status for r in inventory.records], ["ok", "unchecked", "unchecked"])
        self.assertEqual([u.address for u in inventory.identities], [4])
        self.assertIn("omitted", inventory.errors[-1])

    def test_partial_native_check_error_retains_proven_rows(self):
        self.client.overrides["NET CHECKUNIT " + NET + " 4,5"] = CGateError(reply(
            "120-Single unit detected at address: 4", "408 unravel check failed (timeout)"))
        inventory = self.serials.refresh(NET, [4, 5])
        self.assertEqual([u.address for u in inventory.identities], [4])
        self.assertTrue(inventory.errors)
        self.assertFalse(inventory.complete)

    def test_malformed_duplicate_and_out_of_range_checks_are_partial_errors(self):
        self.client.overrides["NET CHECKUNIT " + NET + " 4,5"] = reply(
            "120-Single unit detected at address: 4", "120-Single unit detected at address: 4",
            "120-Single unit detected at address: 999", "120-Single unit detected at address: 6",
            "120-Malformed vendor response", "120 Single unit detected at address: 5")
        inventory = self.serials.refresh(NET, [4, 5])
        self.assertEqual([r.status for r in inventory.records], ["uncertain", "ok"])
        self.assertEqual([u.address for u in inventory.identities], [5])
        self.assertEqual(len(inventory.errors), 4)


@unittest.skipUnless(os.environ.get("CBUS_CGATE_TEST_HOST"), "Set CBUS_CGATE_TEST_HOST for isolated native serial acceptance")
class NativeSerialTests(unittest.TestCase):
    def test_cached_and_physical_refresh_use_real_captured_serials(self):
        project = "SR" + uuid4().hex[:6].upper()
        network = f"//{project}/254"
        sim = PCISimulator(profile="synthetic")
        report = {"scope": "Isolated C-Gate and explicit synthetic fixture; no hardware parity claim", "passed": False}
        try:
            with sim.running("0.0.0.0", 0) as (_, port), CGateClient(os.environ["CBUS_CGATE_TEST_HOST"],
                    int(os.environ.get("CBUS_CGATE_TEST_PORT", "20023")), timeout=30) as client:
                projects, database, lifecycle = NativeProjects(client), NativeDatabase(client), NativeNetworks(client)
                created = False
                try:
                    projects.operation("new", project); created = True
                    database.create_network(project, 254, "Serial_Oracle", "Cni",
                        os.environ.get("CBUS_CGATE_SIMULATOR_HOST", "host.docker.internal") + ":" + str(port))
                    projects.operation("save", project)
                    before = xml_text(database.get(network, xml=True))
                    lifecycle.open(network)
                    self.assertTrue(lifecycle.wait_ready(network, timeout=25)["ready"])
                    scanner = NativeSerials(client)
                    self.assertEqual(scanner._get(network, "TargetInterfaceState"), "running")
                    start = len(sim.wire_log)
                    cached = scanner.cached(network)
                    self.assertTrue(cached.complete, cached.as_dict())
                    self.assertEqual([(u.address, u.unit_type, u.serial) for u in cached.identities],
                        [(4, "KEYE1", "101136.1558"), (5, "KEYGL5", "101183.1666"), (16, "PC_CNIED", "100966.1187")])
                    self.assertEqual(len(sim.wire_log), start, "Cached getters emitted physical network traffic")
                    partial = scanner.cached(network, [4, 6])
                    self.assertEqual([r.status for r in partial.records], ["ok", "not_cached"])
                    refreshed = scanner.refresh(network, [4, 5, 6])
                    self.assertEqual([r.status for r in refreshed.records], ["ok", "ok", "absent"], refreshed.as_dict())
                    self.assertEqual([u.serial for u in refreshed.identities], ["101136.1558", "101183.1666"])
                    self.assertGreater(len(sim.wire_log), start)
                    self.assertEqual(xml_text(database.get(network, xml=True)), before)
                    self.assertFalse([r for r in sim.wire_log if r.get("reason")])
                    # An explicit fixture mutation gives a new independent raw
                    # IDENTIFY4 serial, while the previous cache remains intact.
                    original = sim.units[4].attributes[4]
                    replacement = bytearray(original)
                    replacement[5:9] = sim.units[16].attributes[4][5:9]
                    sim.units[4].attributes[4] = bytes(replacement)
                    self.assertEqual(scanner.cached(network, [4]).identities[0].serial, "101136.1558")
                    changed = scanner.refresh(network)
                    self.assertEqual([u.serial for u in changed.identities if u.address == 4], ["100966.1187"], changed.as_dict())
                    self.assertEqual({r.address for r in changed.records if r.status == "duplicate_serial"}, {4, 16})
                    self.assertEqual(xml_text(database.get(network, xml=True)), before)
                    lifecycle.close(network)
                    start = len(sim.wire_log)
                    closed = scanner.cached(network, [4])
                    self.assertEqual(closed.records[0].serial, "100966.1187")
                    self.assertEqual(len(sim.wire_log), start)
                    with self.assertRaisesRegex(ValueError, "InterfaceState"): scanner.refresh(network)
                    report.update(passed=True, cached=cached.as_dict(), refreshed=refreshed.as_dict(), changed=changed.as_dict())
                finally:
                    if created:
                        errors = []
                        for command in ("NET CLOSE " + network, "PROJECT CLOSE " + project, "PROJECT DELETE " + project):
                            try:
                                if not client.connected: client.connect()
                                client.command(command)
                            except Exception as error: errors.append(str(error))
                        report["cleanup_errors"] = errors
                        if report["passed"]: self.assertEqual(errors, [])
        finally:
            report["wire"] = list(sim.wire_log)
            if os.environ.get("CBUS_SERIALS_REPORT"):
                Path(os.environ["CBUS_SERIALS_REPORT"]).write_text(json.dumps(report, indent=2) + "\n")


@unittest.skipUnless(os.environ.get("CBUS_TOOLKIT_EXE"), "Set CBUS_TOOLKIT_EXE for exact Toolkit serial source checks")
class SerialSourceTests(unittest.TestCase):
    def test_get_serials_updates_database_serial_metadata_then_saves_project(self):
        data = Path(os.environ["CBUS_TOOLKIT_EXE"]).read_bytes()
        u16 = lambda n: struct.unpack_from("<H", data, n)[0]
        u32 = lambda n: struct.unpack_from("<I", data, n)[0]
        pe = u32(60); optional = pe + 24; sections = optional + u16(pe + 20); base = u32(optional + 28)
        def at(address, length):
            rva = address - base
            for i in range(u16(pe + 6)):
                offset = sections + i * 40; start = u32(offset + 12)
                if start <= rva < start + max(u32(offset + 8), u32(offset + 16)):
                    raw = u32(offset + 20) + rva - start
                    return data[raw:raw + length]
            self.fail("Address outside PE sections")
        self.assertEqual(at(0xEB5D48, 24).decode("utf-16le"), "UpdateSerial")
        self.assertEqual(at(0xEB5D88, 22).decode("utf-16le"), "ProjectSave")


if __name__ == "__main__": unittest.main()
