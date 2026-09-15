from dataclasses import replace
import os
from pathlib import Path
import struct
import unittest
from uuid import uuid4

from cbus_toolkit.addressing import (
    AddressingError, DatabaseAddressing, NetworkAddressing, UnitIdentity, match_serials, _network_path,
    _network_canonical,
)
from cbus_toolkit.classic_replacement import _canonical, _document, _field, _set


class SerialTests(unittest.TestCase):
    def test_exact_matches_report_both_directions_and_occupied_destinations(self):
        database = [UnitIdentity(1, "KEY4", "00100700.3526"), UnitIdentity(2, "KEY4", "00100327.0683")]
        network = [UnitIdentity(2, "KEY4", "00100700.3526"), UnitIdentity(1, "KEY4", "00100327.0683")]
        report = match_serials(database, network)
        self.assertFalse(report["applied"])
        for row in report["matches"]:
            self.assertEqual(row["status"], "different_address")
            self.assertTrue(row["database_to_network"]["destination_occupied"])
            self.assertTrue(row["network_to_database"]["destination_occupied"])
        report = match_serials(database[:1], [UnitIdentity(1, "KEY4", "00100700.3526")])
        self.assertEqual(report["matches"][0]["status"], "aligned")

    def test_ambiguous_missing_unknown_and_type_mismatch(self):
        database = [UnitIdentity(1, "KEY4", "DUP"), UnitIdentity(2, "KEY4", "DUP"),
                    UnitIdentity(3, "KEY4", "TYPE"), UnitIdentity(4, "KEY4", "DB_ONLY"),
                    UnitIdentity(5, "KEY4", ""), UnitIdentity(6, "KEY4", "00000000.0000")]
        network = [UnitIdentity(1, "KEY4", "DUP"), UnitIdentity(3, "KEY1", "TYPE"), UnitIdentity(7, "KEY4", "NET_ONLY")]
        report = match_serials(database, network)
        self.assertEqual({r["serial"]: r["status"] for r in report["matches"]},
                         {"DUP": "ambiguous_serial", "TYPE": "type_mismatch", "DB_ONLY": "database_only", "NET_ONLY": "network_only"})
        self.assertEqual(len(report["unidentified_database"]), 2)
        self.assertNotIn("database_to_network", next(r for r in report["matches"] if r["serial"] == "TYPE"))

    def test_no_serial_normalization_or_compatibility_guess(self):
        report = match_serials([UnitIdentity(1, "KEY1", "a")], [UnitIdentity(1, "KEY2", "A")])
        self.assertEqual({r["status"] for r in report["matches"]}, {"database_only", "network_only"})

    def test_invalid_inventories_and_addresses(self):
        for value in (-1, 256, True, "1", 1.1):
            with self.assertRaises(ValueError): UnitIdentity(value, "KEY4")
        for kind, serial in (("", ""), (" KEY4", "x"), ("KEY4", "x\ny"), ("KEY4", " x")):
            with self.assertRaises(ValueError): UnitIdentity(1, kind, serial)
        with self.assertRaises(ValueError): match_serials([UnitIdentity(1, "KEY4"), UnitIdentity(1, "KEY4")], [])
        with self.assertRaises(ValueError): match_serials([{}], [])
        for path in ("254", "//TOO_LONGER/254", "//TEST/256", "//TEST/254/p/1"):
            with self.assertRaises(ValueError): _network_path(path)


class FaultClient:
    def __init__(self, client, source, mode):
        self.client, self.source, self.mode = client, source, mode
        self.failed = False
        self.saves = 0

    def command(self, command):
        if command.startswith("PROJECT SAVE "):
            self.saves += 1
            if self.mode == "save" and self.saves == 2 and not self.failed:
                result = self.client.command(command)
                self.failed = True
                raise OSError("Simulated lost reply after project save")
        return self.client.command(command)

    def command_document(self, command, document):
        if self.mode == "unrecoverable" and self.failed:
            raise OSError("Simulated disconnected rollback")
        if command == "DBSETXML " + self.source and not self.failed:
            if self.mode == "metadata":
                doc = _document(document)
                _set(doc, "Description", "Unexpected metadata mutation")
                document = doc.toxml()
                self.failed = True
            result = self.client.command_document(command, document)
            if self.mode in ("write", "unrecoverable"):
                self.failed = True
                raise OSError("Simulated lost reply after readdress")
            return result
        return self.client.command_document(command, document)


@unittest.skipUnless(os.environ.get("CBUS_CGATE_TEST_HOST"), "Set CBUS_CGATE_TEST_HOST for native database address acceptance")
class NativeAddressingTests(unittest.TestCase):
    def setUp(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase
        from cbus_toolkit.programming import Programmer
        self.host = os.environ["CBUS_CGATE_TEST_HOST"]
        self.port = int(os.environ.get("CBUS_CGATE_TEST_PORT", "20023"))
        self.client = CGateClient(self.host, self.port, timeout=25)
        self.client.connect()
        self.database = NativeDatabase(self.client)
        self.programmer = Programmer(self.client)
        self.addressing = DatabaseAddressing(self.client)
        self.project = "A" + uuid4().hex[:7].upper()
        self.backups = []
        self.client.command("PROJECT NEW " + self.project)
        self.database.create_network(self.project, 254, "Address_Offline", "Cni", "127.0.0.1:29999")
        self.network = "//" + self.project + "/254"
        self.client.command("PROJECT SAVE " + self.project)

    def tearDown(self):
        errors = []
        for project in [self.project, *self.backups]:
            try: self.client.command("PROJECT CLOSE " + project)
            except Exception: pass
            try: self.client.command("PROJECT DELETE " + project)
            except Exception as error: errors.append(str(error))
        self.client.close()
        if errors: self.fail("Disposable project cleanup failed: " + "; ".join(errors))

    def backup(self):
        result = "B" + uuid4().hex[:7].upper()
        self.backups.append(result)
        return result

    def create(self, address=210, unit_type="KEY4", firmware="1.2.67", catalog="5034N"):
        self.database.create_unit(self.network, address, "Unit_" + str(address), unit_type, firmware, catalog_number=catalog)
        path = self.network + "/p/" + str(address)
        self.database.set(path + "/Description", 'Keep A & B <opaque attr="v">metadata</opaque>')
        self.database.set(path + "/SerialNumber", "00100700.3526")
        self.client.command("PROJECT SAVE " + self.project)
        self.client.command("PROJECT CLOSE " + self.project)
        self.client.command("PROJECT LOAD " + self.project)
        return path

    def test_native_primitive_leaves_pp_address_stale(self):
        old = self.create()
        self.database.set(old + "/Address", "211")
        with self.programmer.load(self.network, "/db" + self.network + "/p/211") as session:
            self.assertEqual(int(session.values()["UnitAddress"], 0), 210)
        with self.assertRaisesRegex(ValueError, "does not match"):
            self.addressing.plan(self.network + "/p/211", 212)

    def test_six_families_metadata_full_pp_raw_bytes_backup_and_fresh_reload(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase
        from cbus_toolkit.programming import Programmer, xml_text
        families = [("KEY1", "1.2.67", "5031N"), ("KEY2", "1.2.67", "5032N"),
                    ("KEY4", "1.2.67", "5034N"), ("KEYE1", "2.5.00", "5031NMML"),
                    ("KEYGL5", "5.5.00", "5085EDL"), ("DIMDN4", "1.2.67", "SLC5504TD2A")]
        for index, (kind, firmware, catalog) in enumerate(families):
            with self.subTest(kind=kind):
                source = self.create(200 + index, kind, firmware, catalog)
                original = self.addressing._xml(source)
                destination_address = 220 + index
                plan = self.addressing.plan(source, destination_address)
                # Planning uses a disposable PP edit and must leave the database unchanged.
                self.assertEqual(_canonical(original), _canonical(self.addressing._xml(source)))
                backup = self.backup()
                result = self.addressing.apply(plan, backup_project=backup)
                self.assertTrue(result["readdressed"])
                self.assertFalse(result["hardware_programmed"])
                self.assertEqual(_field(_document(self.addressing._xml(plan.destination)), "OID"), plan.oid)
                self.client.command("PROJECT LOAD " + backup)
                backed_up = xml_text(self.database.get(f"//{backup}/254/p/{200 + index}", xml=True))
                for field in ("Description", "SerialNumber", "Address", "UnitType", "UnitName"):
                    self.assertEqual(_field(_document(backed_up), field), _field(_document(original), field))
                self.client.command("PROJECT CLOSE " + backup)
                self.client.command("PROJECT CLOSE " + self.project)
                self.client.command("PROJECT LOAD " + self.project)
                with CGateClient(self.host, self.port, timeout=25) as fresh:
                    copied_xml = xml_text(NativeDatabase(fresh).get(plan.destination, xml=True))
                    self.assertEqual(_canonical(copied_xml), _canonical(plan.candidate_xml))
                    with Programmer(fresh).load(self.network, "/db" + plan.destination) as session:
                        self.assertEqual(tuple(sorted(session.values().items())), plan.parameters)
                        # Independently fixed native parameter location: all six
                        # exact fixture specs put UnitAddress at byte 0x20.
                        self.assertEqual(session.get_raw_data(0x20, 1).lines[-1].split("RawData=", 1)[1], f"{destination_address:02x}")

    def test_boundary_zero_and_255_and_automatic_backup(self):
        source = self.create()
        for address in (0, 255):
            result = self.addressing.readdress(source, address)
            self.backups.append(result["backup_project"])
            self.assertTrue(result["parameters_verified"])
            source = result["destination"]

    def test_occupied_stale_forged_and_invalid_inputs(self):
        source = self.create()
        self.create(211)
        for value in (210, 211, -1, 256, True, "212"):
            with self.assertRaises(ValueError): self.addressing.plan(source, value)
        plan = self.addressing.plan(source, 212)
        with self.assertRaisesRegex(ValueError, "modified"):
            self.addressing.apply(replace(plan, candidate_xml=plan.candidate_xml.replace("<Description>", "<Description>forged")))
        self.database.set(source + "/Description", "Changed since plan")
        with self.assertRaisesRegex(ValueError, "stale"):
            self.addressing.apply(plan)
        self.assertEqual({u.address for u in self.addressing.inventory(self.network)}, {210, 211})

    def test_opaque_pp_parameter_preserved_and_path_reference_rejected(self):
        source = self.create()
        document = _document(self.addressing._xml(source))
        pp = document.createElement("PP")
        pp.setAttribute("Name", "FutureOpaqueParameter")
        pp.setAttribute("Value", "vendor-value")
        document.documentElement.appendChild(pp)
        self.client.command_document("DBSETXML " + source, document.toxml())
        plan = self.addressing.plan(source, 211)
        self.addressing.apply(plan, backup_project=self.backup())
        self.assertIn('Name="FutureOpaqueParameter" Value="vendor-value"', self.addressing._xml(plan.destination))
        self.database.set(plan.destination + "/Description", "Opaque reference to " + plan.destination)
        with self.assertRaisesRegex(ValueError, "textual unit-path"):
            self.addressing.plan(plan.destination, 212)

    def test_bridge_and_wireless_gateway_types_rejected(self):
        source = self.create()
        for kind in ("BRIDGE", "WGATE5X"):
            self.database.set(source + "/UnitType", kind)
            with self.assertRaisesRegex(ValueError, "coupled topology"):
                self.addressing.plan(source, 211)

    def test_ambiguous_write_and_metadata_loss_and_post_save_failure_roll_back(self):
        for mode in ("write", "metadata", "save"):
            with self.subTest(mode=mode):
                source = self.create(210)
                before = self.addressing._xml(source)
                values = self.addressing._snapshot(source)
                plan = self.addressing.plan(source, 211)
                faulty = DatabaseAddressing(FaultClient(self.client, source, mode))
                with self.assertRaises(AddressingError) as error:
                    faulty.apply(plan, backup_project=self.backup())
                self.assertEqual(error.exception.details["rollback_errors"], [])
                self.client.command("PROJECT CLOSE " + self.project)
                self.client.command("PROJECT LOAD " + self.project)
                self.assertEqual(_canonical(self.addressing._xml(source)), _canonical(before))
                self.assertEqual(self.addressing._snapshot(source), values)
                self.assertEqual([u.address for u in self.addressing.inventory(self.network)], [210])
                self.database.delete(source)

    def test_failed_rollback_reports_backup_without_claiming_restoration(self):
        source = self.create()
        plan = self.addressing.plan(source, 211)
        backup = self.backup()
        with self.assertRaises(AddressingError) as error:
            DatabaseAddressing(FaultClient(self.client, source, "unrecoverable")).apply(plan, backup_project=backup)
        self.assertEqual(error.exception.details["backup_project"], backup)
        self.assertIn("Simulated disconnected rollback", error.exception.details["rollback_errors"][0])
        self.assertEqual([u.address for u in self.addressing.inventory(self.network)], [211])
        self.client.command_document("DBSETXML " + plan.destination, plan.source_xml)
        self.assertEqual(self.addressing._snapshot(source), plan.source_parameters)

    def test_existing_backup_is_not_overwritten(self):
        source = self.create()
        plan = self.addressing.plan(source, 211)
        backup = self.backup()
        self.client.command("PROJECT COPY " + self.project + " " + backup)
        with self.assertRaisesRegex(AddressingError, "backup failed"):
            self.addressing.apply(plan, backup_project=backup)
        self.assertEqual(_canonical(self.addressing._xml(source)), _canonical(plan.source_xml))


class NetworkFaultClient:
    def __init__(self, client, source, destination, mode):
        self.client, self.source, self.destination, self.mode = client, source, destination, mode
        self.failed = False
        self.saves = 0

    def command(self, command):
        if self.mode == "unrecoverable" and self.failed and command.startswith(("NET RENAME ", "DBRENAMENETSAFE ")):
            raise OSError("Simulated rollback connection failure")
        if command.startswith("PROJECT SAVE "):
            self.saves += 1
            if self.mode == "save" and self.saves == 2 and not self.failed:
                self.client.command(command)
                self.failed = True
                raise OSError("Simulated lost project save reply")
        if command.startswith("DBRENAMENETSAFE ") and not self.failed:
            result = self.client.command(command)
            if self.mode == "db_write":
                self.failed = True
                raise OSError("Simulated lost database rename reply")
            if self.mode == "metadata":
                self.client.command("DBSETSAFE " + self.destination + "/p/210/Description Unexpected metadata mutation")
                self.failed = True
            return result
        if command.startswith("NET RENAME " + self.source + " ") and not self.failed:
            if self.mode == "runtime_before":
                self.failed = True
                raise OSError("Simulated runtime rename failure")
            result = self.client.command(command)
            if self.mode in ("runtime_after", "unrecoverable"):
                self.failed = True
                raise OSError("Simulated lost runtime rename reply")
            return result
        result = self.client.command(command)
        if self.mode == "open" and command == "GET " + self.source + " *":
            return replace(result, lines=tuple(line.replace("InterfaceState=closed", "InterfaceState=open") for line in result.lines))
        return result

    def command_document(self, command, document):
        return self.client.command_document(command, document)


@unittest.skipUnless(os.environ.get("CBUS_CGATE_TEST_HOST"), "Set CBUS_CGATE_TEST_HOST for native closed-network address acceptance")
class NativeNetworkAddressingTests(unittest.TestCase):
    setUp = NativeAddressingTests.setUp
    tearDown = NativeAddressingTests.tearDown
    create = NativeAddressingTests.create
    backup = NativeAddressingTests.backup

    def test_cni_whole_network_metadata_pp_and_runtime_persist(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.programming import Programmer
        source_unit = self.create()
        self.create(211, "KEYGL5", "5.5.00", "5085EDL")
        self.database.add(self.network, "application", 56, "Lighting")
        self.database.add(self.network + "/56", "group", 123, "Desk_Lamp")
        with self.programmer.load(self.network, "/db" + source_unit) as session:
            session.set("NetworkAddress", "254")
            session.set("UnitName", "KEEP_NET")
            session.save_to_source()
        self.client.command("PROJECT SAVE " + self.project)
        self.client.command("PROJECT CLOSE " + self.project)
        self.client.command("PROJECT LOAD " + self.project)
        manager = NetworkAddressing(self.client)
        plan = manager.plan(self.network, 253)
        self.assertEqual(len(plan.unit_parameters), 2)
        result = manager.apply(plan, backup_project=self.backup())
        self.assertTrue(result["database_runtime_consistent"])
        self.assertTrue(result["runtime_configuration_verified"])
        self.assertEqual(manager._optional_runtime(self.network), None)
        self.client.command("PROJECT CLOSE " + self.project)
        self.client.command("PROJECT LOAD " + self.project)
        with CGateClient(self.host, self.port, timeout=25) as fresh:
            renamed = NetworkAddressing(fresh)
            self.assertEqual(_network_canonical(renamed._xml(plan.destination)), _network_canonical(plan.candidate_xml))
            for address, expected in plan.unit_parameters:
                with Programmer(fresh).load(plan.destination, "/db" + plan.destination + "/p/" + str(address)) as session:
                    self.assertEqual(tuple(sorted(session.values().items())), expected)
                    if address == 210:
                        self.assertEqual(int(session.values()["NetworkAddress"], 0), 254)
                        self.assertEqual(session.values()["UnitName"], "KEEP_NET")
            self.assertEqual(dict(renamed._runtime(plan.destination))["Name"], "253")

    def test_serial_network_boundary_addresses_and_automatic_backup(self):
        self.database.create_network(self.project, 253, "Serial_Offline", "Serial", "COM99")
        manager = NetworkAddressing(self.client)
        source = "//" + self.project + "/253"
        for target in (0, 255):
            result = manager.readdress(source, target)
            self.backups.append(result["backup_project"])
            self.assertEqual(dict(manager._runtime(result["destination"]))["Type"], "Serial")
            self.assertTrue(result["database_runtime_consistent"])
            source = result["destination"]

    def test_database_and_runtime_destinations_stale_open_and_forged_rejected(self):
        source = self.create()
        manager = NetworkAddressing(self.client)
        self.database.create_network(self.project, 253, "Occupied", "Cni", "127.0.0.1:29998")
        with self.assertRaisesRegex(ValueError, "occupied"):
            manager.plan(self.network, 253)
        # Remove only its database record: runtime occupancy independently blocks.
        self.database.delete("//" + self.project + "/253")
        with self.assertRaisesRegex(ValueError, "occupied"):
            manager.plan(self.network, 253)
        plan = manager.plan(self.network, 252)
        with self.assertRaisesRegex(ValueError, "modified"):
            manager.apply(replace(plan, candidate_xml=plan.source_xml))
        self.database.set(source + "/Description", "Changed since plan")
        with self.assertRaisesRegex(ValueError, "stale"):
            manager.apply(plan)
        fake_open = NetworkAddressing(NetworkFaultClient(self.client, self.network, plan.destination, "open"))
        with self.assertRaisesRegex(ValueError, "closed interface"):
            fake_open.plan(self.network, 252)

    def test_bridge_topology_textual_references_and_identity_mismatch_rejected(self):
        source = self.create()
        manager = NetworkAddressing(self.client)
        self.database.set(source + "/UnitType", "WGATE5X")
        with self.assertRaisesRegex(ValueError, "coupled topology"):
            manager.plan(self.network, 253)
        self.database.set(source + "/UnitType", "KEY4")
        self.database.set(source + "/Description", "Explicit path reference " + self.network + "/56/123")
        with self.assertRaisesRegex(ValueError, "textual network-path"):
            manager.plan(self.network, 253)
        self.database.set(source + "/Description", "Plain metadata")
        self.database.set(self.network + "/NetworkNumber", "252")
        with self.assertRaisesRegex(ValueError, "NetworkNumber"):
            manager.plan(self.network, 253)

    def test_both_rename_boundaries_metadata_and_saved_failure_restore(self):
        self.create()
        for mode in ("db_write", "runtime_before", "runtime_after", "metadata", "save"):
            with self.subTest(mode=mode):
                manager = NetworkAddressing(self.client)
                plan = manager.plan(self.network, 253)
                faulty = NetworkAddressing(NetworkFaultClient(self.client, self.network, plan.destination, mode))
                with self.assertRaises(AddressingError) as error:
                    faulty.apply(plan, backup_project=self.backup())
                self.assertEqual(error.exception.details["rollback_errors"], [])
                self.assertEqual(manager._runtime(self.network), plan.runtime)
                self.assertEqual(manager._optional_runtime(plan.destination), None)
                self.assertEqual(_network_canonical(manager._xml(self.network)), _network_canonical(plan.source_xml))
                self.assertEqual(manager._snapshots(self.network, plan.source_xml), plan.unit_parameters)

    def test_network_rollback_failure_reports_both_layers_and_backup(self):
        self.create()
        manager = NetworkAddressing(self.client)
        plan = manager.plan(self.network, 253)
        backup = self.backup()
        faulty = NetworkAddressing(NetworkFaultClient(self.client, self.network, plan.destination, "unrecoverable"))
        with self.assertRaises(AddressingError) as error:
            faulty.apply(plan, backup_project=backup)
        self.assertEqual(error.exception.details["backup_project"], backup)
        self.assertTrue(any(e.startswith("Runtime rollback:") for e in error.exception.details["rollback_errors"]))
        self.assertTrue(any(e.startswith("Database rollback:") for e in error.exception.details["rollback_errors"]))
        self.client.command("NET RENAME " + plan.destination + " 254")
        self.database.rename_network(plan.destination, 254)
        self.assertEqual(manager._runtime(self.network), plan.runtime)
        self.assertEqual(manager._snapshots(self.network, plan.source_xml), plan.unit_parameters)


@unittest.skipUnless(os.environ.get("CBUS_TOOLKIT_EXE"), "Set CBUS_TOOLKIT_EXE for exact Toolkit addressing source checks")
class AddressingSourceTests(unittest.TestCase):
    def test_network_workflow_command_types_and_metadata_fields(self):
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
        # Exact MAP identifies these two class globals as TcgcDBRenameNet
        # followed by TcgcNetRename in TCBusNetworkCGateAgent.ReaddressNetwork.
        self.assertEqual(at(0xD87860, 5), bytes.fromhex("a1b417d800"))
        self.assertEqual(at(0xD8793A, 5), bytes.fromhex("a1281bd800"))
        self.assertEqual(at(0xD87B3C, 26).decode("utf-16le"), "NetworkNumber")
        self.assertEqual(at(0xD87B64, 22).decode("utf-16le"), "ProjectSave")
        self.assertEqual(at(0xD87AEF, 5), bytes.fromhex("e8d8eeffff"))  # NetLoadDB refresh


if __name__ == "__main__": unittest.main()
