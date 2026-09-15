"""Exact-identity serial metadata population and native rollback acceptance."""
from dataclasses import replace
import json
import os
from pathlib import Path
import struct
import unittest
from uuid import uuid4
from xml.dom import Node, minidom

from cbus_toolkit.addressing import _network_canonical
from cbus_toolkit.cgate import CGateClient, CGateError
from cbus_toolkit.classic_replacement import _canonical, _document, _field, _set
from cbus_toolkit.native import NativeDatabase, NativeProjects
from cbus_toolkit.networks import NativeNetworks
from cbus_toolkit.programming import Programmer, xml_text
from cbus_toolkit.serial_population import DatabaseSerials, SerialPopulationError
from cbus_toolkit.serials import NativeSerials
from cbus_toolkit.simulator import PCISimulator
from tests.test_serials import FakeClient, NET, reply


class PopulationClient(FakeClient):
    def __init__(self):
        super().__init__()
        self.document = minidom.parseString('''<Network><Address>254</Address><TagName>Fixture</TagName>
          <Unit><OID>11111111-1111-1111-1111-111111111111</OID><Address>4</Address><UnitType>KEYE1</UnitType>
          <FirmwareVersion>2.5.00</FirmwareVersion><SerialNumber>00000000.0000</SerialNumber><TagName>Four</TagName>
          <PP Name="UnitAddress" Value="0x04"/><Opaque kind="test"><Nested>keep</Nested></Opaque></Unit>
          <Unit><OID>55555555-5555-5555-5555-555555555555</OID><Address>5</Address><UnitType>KEYGL5</UnitType>
          <FirmwareVersion>5.5.00</FirmwareVersion><SerialNumber></SerialNumber><TagName>Five</TagName>
          <PP Name="UnitAddress" Value="0x05"/></Unit></Network>''')
        self.backups = {}
        self.connected = True
        self.mode = None
        self.failed = False
        self.saves = 0

    def unit(self, address):
        return next(n for n in self.document.documentElement.childNodes if n.nodeType == Node.ELEMENT_NODE
                    and n.tagName == "Unit" and _field(_document(n.toxml()), "Address") == str(address))

    def command(self, command):
        if command.startswith("GET ") or command.startswith("NET "): return super().command(command)
        self.commands.append(command)
        if command.startswith("PROJECT COPY "):
            backup = command.rsplit(" ", 1)[1]
            if backup in self.backups: raise CGateError(reply("400 Destination project already exists."))
            self.backups[backup] = self.document.toxml()
            if self.mode == "runtime_after_backup": self.units[5]["SerialNumber"] = "123.456"
            return reply("200 OK.")
        if command.startswith("PROJECT SAVE "):
            self.saves += 1
            if self.mode == "save" and self.saves == 2 and not self.failed:
                self.failed = True
                raise OSError("Lost save reply")
            return reply("200 OK.")
        if command.startswith("PROJECT USE "): return reply("200 OK.")
        if command.startswith("DBGETXML "):
            path = command.split(" ", 1)[1]
            text = self.document.toxml() if path == NET else self.unit(int(path.rsplit("/", 1)[1])).toxml()
            return reply("343-Begin XML snippet", *("347-" + line for line in text.splitlines()), "344 End XML snippet")
        if command.startswith("DBSETSAFE "):
            _, path, value = command.split(" ", 2)
            address = int(path.split("/")[-2]); field = path.rsplit("/", 1)[1]
            old = self.unit(address); unit = _document(old.toxml()); _set(unit, field, value)
            if self.mode == "metadata" and not self.failed: _set(unit, "TagName", "unexpected")
            if self.mode == "oid" and not self.failed: _set(unit, "OID", "99999999-9999-9999-9999-999999999999")
            self.document.documentElement.replaceChild(self.document.importNode(unit.documentElement, True), old)
            if self.mode in ("write", "metadata", "oid", "disconnect") and not self.failed:
                self.failed = True
                if self.mode == "disconnect": self.connected = False
                if self.mode != "metadata": raise OSError("Lost update reply")
            return reply("200 OK.")
        raise AssertionError(command)

    def command_document(self, command, document):
        self.commands.append(command)
        if self.mode == "rollback_error": raise OSError("Rollback failed")
        address = int(command.rsplit("/", 1)[1]); unit = _document(document)
        self.document.documentElement.replaceChild(self.document.importNode(unit.documentElement, True), self.unit(address))
        return reply("301 OID=" + _field(unit, "OID"))


class SerialPopulationTests(unittest.TestCase):
    def setUp(self):
        self.client = PopulationClient()
        self.manager = DatabaseSerials(self.client)
        self.inventory = NativeSerials(self.client).cached(NET)

    def test_plan_and_apply_preserve_all_metadata_and_programming(self):
        before = self.client.document.toxml()
        plan = self.manager.plan(self.inventory)
        self.assertEqual([c.address for c in plan.changes], [4, 5])
        for change in plan.changes:
            self.assertEqual(_canonical(change.source_xml, exclude=("SerialNumber",)),
                             _canonical(change.candidate_xml, exclude=("SerialNumber",)))
        result = self.manager.apply(plan, backup_project="BACKUP")
        self.assertTrue(result["updated"])
        self.assertTrue(result["project_saved"])
        self.assertEqual(_network_canonical(self.client.backups["BACKUP"]), _network_canonical(before))
        self.assertEqual([c for c in self.client.commands if c.startswith("DBSETSAFE ")],
            [f"DBSETSAFE {NET}/p/4/SerialNumber 101136.1558", f"DBSETSAFE {NET}/p/5/SerialNumber 101183.1666"])
        self.assertFalse(any(c.startswith(("NET ", "PP ")) for c in self.client.commands))
        json.dumps(result)

    def test_subset_plan_noop_and_unselected_serial_collision(self):
        plan = self.manager.plan(self.inventory, units=[4])
        self.assertEqual(len(plan.changes), 1)
        self.manager.apply(plan)
        no_op = self.manager.plan(self.inventory, units=[4])
        before = len(self.client.commands)
        result = self.manager.apply(no_op)
        self.assertFalse(result["updated"])
        self.assertIsNone(result["backup_project"])
        self.assertFalse(any(c.startswith(("PROJECT SAVE ", "PROJECT COPY ", "DBSET")) for c in self.client.commands[before:]))
        other = _document(self.client.unit(5).toxml()); _set(other, "SerialNumber", "101136.1558")
        self.client.document.documentElement.replaceChild(self.client.document.importNode(other.documentElement, True), self.client.unit(5))
        with self.assertRaisesRegex(ValueError, "duplicate database"): self.manager.plan(self.inventory, units=[4])

    def test_partial_ambiguous_malformed_or_stale_inventory_is_rejected(self):
        variants = [replace(self.inventory, requested=(4, 5, 16)), replace(self.inventory, errors=("partial",)),
                    replace(self.inventory, records=()), replace(self.inventory, mode="refresh", refresh_completed=False)]
        variants += [replace(self.inventory, records=(replace(self.inventory.records[0], **fields), *self.inventory.records[1:]))
                     for fields in ({"status": "duplicate_serial"}, {"serial": "0.0"}, {"serial": "bad"},
                                    {"serial": "100966.1187"}, {"state": "sync"}, {"presence": "unchecked"})]
        for inventory in variants:
            with self.subTest(inventory=inventory), self.assertRaises(ValueError): self.manager.plan(inventory)
        self.client.units[5]["SerialNumber"] = "123.456"
        with self.assertRaisesRegex(ValueError, "stale"): self.manager.plan(self.inventory)

    def test_type_firmware_oid_selection_and_forged_plan_guards(self):
        for field, value in (("UnitType", "KEY4"), ("FirmwareVersion", "2.6.00"), ("OID", "invalid")):
            with self.subTest(field=field):
                client = PopulationClient(); unit = _document(client.unit(4).toxml()); _set(unit, field, value)
                client.document.documentElement.replaceChild(client.document.importNode(unit.documentElement, True), client.unit(4))
                with self.assertRaises(ValueError): DatabaseSerials(client).plan(self.inventory)
        for units in ([], [4, 4], [6], [256], [True]):
            with self.subTest(units=units), self.assertRaises(ValueError): self.manager.plan(self.inventory, units=units)
        plan = self.manager.plan(self.inventory)
        for forged in (replace(plan, source_hash="wrong"), replace(plan, candidate_xml="<Network/>"), replace(plan, changes=())):
            with self.assertRaises(ValueError): self.manager.apply(forged)

    def test_backup_collision_and_runtime_change_after_backup_never_write(self):
        self.client.backups["EXISTS"] = "protected"
        plan = self.manager.plan(self.inventory)
        with self.assertRaises(SerialPopulationError): self.manager.apply(plan, backup_project="EXISTS")
        self.assertEqual(self.client.backups["EXISTS"], "protected")
        self.client.mode = "runtime_after_backup"
        with self.assertRaises(SerialPopulationError) as error: self.manager.apply(plan)
        self.assertEqual(error.exception.details["rollback_errors"], [])
        self.assertFalse(any(c.startswith("DBSET") for c in self.client.commands))

    def test_update_metadata_and_save_failures_restore_all_original_xml(self):
        for mode in ("write", "metadata", "save"):
            with self.subTest(mode=mode):
                client = PopulationClient(); client.mode = mode
                original = client.document.toxml(); manager = DatabaseSerials(client)
                with self.assertRaises(SerialPopulationError) as error: manager.apply(manager.plan(self.inventory))
                self.assertEqual(error.exception.details["rollback_errors"], [])
                self.assertEqual(_network_canonical(client.document.toxml()), _network_canonical(original))
                self.assertTrue(error.exception.details["backup_project"] in client.backups)

    def test_changed_oid_and_lost_connection_never_claim_restoration(self):
        for mode in ("oid", "disconnect"):
            with self.subTest(mode=mode):
                client = PopulationClient(); client.mode = mode; manager = DatabaseSerials(client)
                with self.assertRaises(SerialPopulationError) as error: manager.apply(manager.plan(self.inventory))
                self.assertTrue(error.exception.details["rollback_errors"])
                if mode == "disconnect":
                    self.assertTrue(client.commands[-1].startswith("DBSETSAFE "))
                    self.assertIn("not attempted", error.exception.details["rollback_errors"][0])
                else: self.assertFalse(any(c.startswith("DBSETXML ") for c in client.commands))


class NativeFaultClient:
    def __init__(self, client, mode): self.client, self.mode, self.failed, self.saves = client, mode, False, 0
    @property
    def connected(self): return self.client.connected
    def command(self, command):
        result = self.client.command(command)
        if command.startswith("PROJECT SAVE "):
            self.saves += 1
            if self.mode == "save" and self.saves == 2 and not self.failed:
                self.failed = True; raise OSError("Lost native save response")
        if self.mode in ("write", "metadata") and command.startswith("DBSETSAFE ") and command.endswith("101136.1558") and not self.failed:
            self.failed = True
            if self.mode == "metadata":
                self.client.command(command.rsplit("/SerialNumber", 1)[0] + "/TagName Unexpected")
            else: raise OSError("Lost native scalar-write response")
        return result
    def command_document(self, command, document): return self.client.command_document(command, document)


@unittest.skipUnless(os.environ.get("CBUS_CGATE_TEST_HOST"), "Set CBUS_CGATE_TEST_HOST for isolated native serial population")
class NativeSerialPopulationTests(unittest.TestCase):
    def test_three_supported_types_metadata_persistence_backup_and_rollback(self):
        project = "SP" + uuid4().hex[:6].upper(); network = f"//{project}/254"
        sim = PCISimulator(profile="synthetic")
        backups = []
        report = {"scope": "Native database-only serial metadata update from isolated synthetic inventory", "passed": False,
                  "rollback_cases": []}
        try:
            with sim.running("0.0.0.0", 0) as (_, port), CGateClient(os.environ["CBUS_CGATE_TEST_HOST"],
                    int(os.environ.get("CBUS_CGATE_TEST_PORT", "20023")), timeout=30) as client:
                projects, database, networks = NativeProjects(client), NativeDatabase(client), NativeNetworks(client)
                created = False
                try:
                    projects.operation("new", project); created = True
                    database.create_network(project, 254, "Get_Serials", "Cni",
                        os.environ.get("CBUS_CGATE_SIMULATOR_HOST", "host.docker.internal") + ":" + str(port))
                    for address, kind, firmware, catalog in ((4, "KEYE1", "2.5.00", "5031NMML"),
                            (5, "KEYGL5", "5.5.00", "5085EDL"), (16, "PC_CNIED", "5.5.00", "5500CN2")):
                        path = network + "/p/" + str(address)
                        database.create_unit(network, address, "Serial_" + str(address), kind, firmware, catalog_number=catalog)
                        database.set(path + "/Description", "Keep descriptive metadata " + str(address))
                        unit = _document(xml_text(database.get(path, xml=True)))
                        extra = unit.createElement("SerialTestOpaque"); extra.setAttribute("key", str(address))
                        extra.appendChild(unit.createTextNode("Preserve unknown metadata")); unit.documentElement.appendChild(extra)
                        client.command_document("DBSETXML " + path, unit.toxml())
                    projects.operation("save", project)
                    # Native LOAD materializes scalar DeviceName metadata from
                    # newly initialized PP. Establish that persisted baseline
                    # before measuring this workflow's serial-only changes.
                    projects.operation("close", project)
                    projects.operation("load", project)
                    client.command("NET LOAD DB " + project)
                    networks.open(network); networks.wait_ready(network, timeout=25)
                    inventory = NativeSerials(client).cached(network)
                    self.assertTrue(inventory.complete, inventory.as_dict())
                    before = xml_text(database.get(network, xml=True))
                    programmer = Programmer(client)
                    parameter_before = {}
                    for address in (4, 5, 16):
                        with programmer.load(network, "/db" + network + "/p/" + str(address)) as session:
                            parameter_before[address] = session.values()
                    for mode in ("write", "metadata", "save"):
                        with self.subTest(mode=mode):
                            backup = "B" + uuid4().hex[:7].upper(); backups.append(backup)
                            faulty = DatabaseSerials(NativeFaultClient(client, mode))
                            with self.assertRaises(SerialPopulationError) as error:
                                faulty.apply(faulty.plan(inventory), backup_project=backup)
                            self.assertEqual(error.exception.details["rollback_errors"], [])
                            self.assertEqual(_network_canonical(xml_text(database.get(network, xml=True))), _network_canonical(before))
                            report["rollback_cases"].append(mode)
                    self.assertEqual(report["rollback_cases"], ["write", "metadata", "save"])
                    manager = DatabaseSerials(client); plan = manager.plan(inventory)
                    backup = "B" + uuid4().hex[:7].upper(); backups.append(backup)
                    start = len(sim.wire_log)
                    result = manager.apply(plan, backup_project=backup)
                    self.assertTrue(result["updated"])
                    self.assertEqual(len(sim.wire_log), start, "Database serial population emitted network traffic")
                    after = xml_text(database.get(network, xml=True))
                    for change in plan.changes:
                        actual = _document(xml_text(database.get(network + "/p/" + str(change.address), xml=True)))
                        self.assertEqual(_field(actual, "SerialNumber"), change.new_serial)
                        self.assertEqual(_canonical(actual.toxml(), exclude=("SerialNumber",)),
                                         _canonical(change.source_xml, exclude=("SerialNumber",)))
                        with programmer.load(network, "/db" + network + "/p/" + str(change.address)) as session:
                            self.assertEqual(session.values(), parameter_before[change.address])
                    projects.operation("load", backup)
                    backup_xml = xml_text(database.get("//" + backup + "/254", xml=True))
                    # Project copy may change project paths in PP; unit scalar
                    # serials must independently remain their original values.
                    for node in minidom.parseString(backup_xml).getElementsByTagName("Unit"):
                        unit = _document(node.toxml())
                        original = next(c.old_serial for c in plan.changes if c.address == int(_field(unit, "Address")))
                        self.assertEqual(_field(unit, "SerialNumber"), original)
                    projects.operation("close", backup)
                    projects.operation("use", project)
                    networks.close(network); projects.operation("close", project); projects.operation("load", project)
                    self.assertEqual(_network_canonical(xml_text(database.get(network, xml=True))), _network_canonical(after))
                    report.update(passed=True, result=result, source_xml=before, saved_xml=after,
                                  programming_unchanged=True, backup_serials_verified=True, scalar_only=True)
                finally:
                    if created:
                        errors = []
                        for command in ("NET CLOSE " + network, "PROJECT CLOSE " + project, "PROJECT DELETE " + project,
                                        *("PROJECT DELETE " + backup for backup in backups)):
                            try:
                                if not client.connected: client.connect()
                                client.command(command)
                            except Exception as error: errors.append(str(error))
                        report["cleanup_errors"] = errors
                        if report["passed"]: self.assertEqual(errors, [])
        finally:
            if os.environ.get("CBUS_SERIAL_POPULATION_REPORT"):
                Path(os.environ["CBUS_SERIAL_POPULATION_REPORT"]).write_text(json.dumps(report, indent=2) + "\n")


@unittest.skipUnless(os.environ.get("CBUS_TOOLKIT_EXE"), "Set CBUS_TOOLKIT_EXE for exact serial compatibility source checks")
class SerialPopulationSourceTests(unittest.TestCase):
    def test_three_types_use_exact_type_and_firmware_compatibility_branch(self):
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
        for symbol in (0x129ACCC, 0xEA8CFC, 0xD1897C, 0xF2112C):
            vmt = struct.unpack("<I", at(symbol, 4))[0]
            self.assertEqual(struct.unpack("<I", at(vmt + 0x134, 4))[0], 0xF33EC4)
        self.assertEqual(at(0x138B880, 10).decode("utf-16le"), "KEYE1")
        self.assertEqual(at(0x1386738, 16).decode("utf-16le"), "PC_CNIED")
        self.assertEqual(at(0xF34017, 5), bytes.fromhex("e890acffff"))  # GetFirmwareVersion
        self.assertEqual(at(0xF34034, 2), bytes.fromhex("745d"))  # Both exact equal -> success


if __name__ == "__main__": unittest.main()
