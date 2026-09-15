"""Programming workflow tests; native acceptance is explicitly opt-in.

Set CBUS_CGATE_TEST_HOST and optionally CBUS_CGATE_TEST_PORT for a disposable
C-Gate server. Native tests reserve project CLI_TEST, never open a network, and
only load/save database addresses. Unit fixture slots 220/221 must be unused.
"""
from dataclasses import dataclass
import os
import re
import unittest
from uuid import uuid4

from cbus_toolkit.programming import Programmer, ProgrammingError, ProgrammingCommandError, ProgrammingCleanupError, NativeCommandLimitation, database_address, parameter_values, quote_value, xml_text


@dataclass
class Reply:
    lines: tuple = ("200 OK.",)
    code: int = 200


class Client:
    def __init__(self):
        self.commands = []
        self.responses = {}
        self.failures = {}

    def command(self, command):
        self.commands.append(command)
        if command in self.failures:
            raise self.failures[command]
        if command in self.responses:
            return self.responses[command]
        if command.startswith("DBGET ") and command.rsplit("/", 1)[-1].isdigit():
            return Reply(("342-/UnitType=KEY4", "342-/FirmwareVersion=1.2.67", "342 /CatalogNumber=5034N"), 342)
        return Reply()


class ProgrammingTest(unittest.TestCase):
    def setUp(self):
        self.client = Client()
        self.programmer = Programmer(self.client)

    def session(self):
        return self.programmer.session("//CLI_TEST/254", name="CLI_TEST_SESSION", lock_name="CLI_TEST_LOCK")

    def test_new_context_native_command_order_and_cleanup(self):
        with self.programmer.new("//CLI_TEST/254", "KEY4", "1.2.67", catalog_number="5034N", name="CLI_TEST_SESSION", lock_name="CLI_TEST_LOCK") as session:
            self.assertEqual(session.unit_type, "KEY4")
            session.set("Application", "$38 $ff")
        self.assertEqual(self.client.commands, ["PROJECT USE CLI_TEST", "PP LOCK CLI_TEST_LOCK //CLI_TEST/254", "PP START CLI_TEST_SESSION CLI_TEST_LOCK", "PP NEW CLI_TEST_SESSION KEY4 1.2.67 5034N", 'PP SET CLI_TEST_SESSION Application "$38\\ $ff"', "PP END CLI_TEST_SESSION", "PP UNLOCK CLI_TEST_LOCK"])
        self.assertFalse(any("SAVE" in command for command in self.client.commands))

    def test_load_context_database_addresses_and_tags(self):
        with self.programmer.load("//CLI_TEST/254", database_address("//CLI_TEST/254/p/20"), tags=["all", "Scenes"], name="CLI_TEST_SESSION", lock_name="CLI_TEST_LOCK") as session:
            session.save_to_source(tags=["Scenes"])
            session.save(database_address("//CLI_TEST/254/p/21"))
        self.assertIn('PP LOAD CLI_TEST_SESSION /db//CLI_TEST/254/p/20 "all" "Scenes"', self.client.commands)
        self.assertIn('PP SAVE_TO_SOURCE CLI_TEST_SESSION "Scenes"', self.client.commands)
        self.assertIn("PP SAVE CLI_TEST_SESSION /db//CLI_TEST/254/p/21", self.client.commands)

    def test_failed_lock_does_not_unlock_another_owners_lock(self):
        failure = RuntimeError("locked by another owner")
        self.client.failures["PP LOCK CLI_TEST_LOCK //CLI_TEST/254"] = failure
        with self.assertRaises(RuntimeError):
            self.session().open()
        self.assertEqual(self.client.commands, ["PROJECT USE CLI_TEST", "PP LOCK CLI_TEST_LOCK //CLI_TEST/254"])

    def test_failed_start_unlocks_successfully_acquired_lock(self):
        self.client.failures["PP START CLI_TEST_SESSION CLI_TEST_LOCK"] = RuntimeError("start failed")
        with self.assertRaises(RuntimeError):
            self.session().open()
        self.assertEqual(self.client.commands[-1], "PP UNLOCK CLI_TEST_LOCK")
        self.assertNotIn("PP END CLI_TEST_SESSION", self.client.commands)

    def test_failed_initializer_cleans_session_and_lock(self):
        self.client.failures["PP NEW CLI_TEST_SESSION BAD 1"] = RuntimeError("unknown unit")
        with self.assertRaises(RuntimeError):
            with self.programmer.new("//CLI_TEST/254", "BAD", "1", name="CLI_TEST_SESSION", lock_name="CLI_TEST_LOCK"):
                self.fail("initializer should fail")
        self.assertEqual(self.client.commands[-2:], ["PP END CLI_TEST_SESSION", "PP UNLOCK CLI_TEST_LOCK"])

    def test_body_failure_keeps_primary_exception_and_records_cleanup_errors(self):
        self.client.failures["PP END CLI_TEST_SESSION"] = RuntimeError("end failed")
        primary = ValueError("body failed")
        with self.assertRaises(ValueError) as captured:
            with self.session():
                raise primary
        self.assertIs(captured.exception, primary)
        self.assertEqual(str(primary.programming_cleanup_errors[0]), "end failed")
        self.assertEqual(self.client.commands[-1], "PP UNLOCK CLI_TEST_LOCK")

    def test_cleanup_failure_is_raised_without_body_exception(self):
        self.client.failures["PP UNLOCK CLI_TEST_LOCK"] = RuntimeError("unlock failed")
        with self.assertRaises(ProgrammingCleanupError):
            with self.session():
                pass

    def test_close_is_idempotent_and_closed_sessions_reject_commands(self):
        session = self.session()
        with self.assertRaises(ProgrammingError):
            session.get()
        session.open()
        with self.assertRaises(ProgrammingError):
            session.open()
        session.close()
        count = len(self.client.commands)
        session.close()
        self.assertEqual(len(self.client.commands), count)
        with self.assertRaises(ProgrammingError):
            session.set("Name", "new")

    def test_explicit_lock_project_is_selected_on_fresh_connection(self):
        with self.session():
            pass
        self.assertEqual(self.client.commands[:2], ["PROJECT USE CLI_TEST", "PP LOCK CLI_TEST_LOCK //CLI_TEST/254"])
        self.client.commands.clear()
        with self.programmer.session("254", name="CLI_TEST_RELATIVE", lock_name="CLI_TEST_LOCK"):
            pass
        self.assertEqual(self.client.commands[0], "PP LOCK CLI_TEST_LOCK 254")

    def test_new_database_save_preserves_values_and_binds_existing_target(self):
        self.client.responses["DBGET //CLI_TEST/254/p/20/UnitType"] = Reply(("342 UnitType=KEY4",), 342)
        self.client.responses["DBGET //CLI_TEST/254/p/20/FirmwareVersion"] = Reply(("342 FirmwareVersion=1.2.67",), 342)
        self.client.responses["PP GET CLI_TEST_SESSION *"] = Reply(("315 UnitName=NEW SAVE",), 315)
        with self.session() as session:
            session.new("KEY4", "1.2.67")
            session.save("/db//CLI_TEST/254/p/20")
            self.assertEqual(session.source, "/db//CLI_TEST/254/p/20")
            self.assertEqual(session.unit_type, "KEY4")
        commands = self.client.commands
        snapshot_index = commands.index("PP GET CLI_TEST_SESSION *")
        bind_index = commands.index("PP LOAD CLI_TEST_SESSION /db//CLI_TEST/254/p/20")
        restore_index = commands.index('PP SET CLI_TEST_SESSION UnitName "NEW\\ SAVE"')
        save_index = commands.index("PP SAVE CLI_TEST_SESSION /db//CLI_TEST/254/p/20")
        self.assertLess(snapshot_index, bind_index)
        self.assertLess(bind_index, restore_index)
        self.assertLess(restore_index, save_index)

    def test_new_save_rejects_incompatible_destination_before_binding(self):
        self.client.responses["DBGET //CLI_TEST/254/p/20/UnitType"] = Reply(("342 UnitType=OTHER",), 342)
        with self.session() as session:
            session.new("KEY4", "1.2.67")
            with self.assertRaises(ProgrammingError):
                session.save("/db//CLI_TEST/254/p/20")
            with self.assertRaises(ProgrammingError):
                session.save_to_source()
            with self.assertRaises(ProgrammingError):
                session.save("//CLI_TEST/254/p/20")
        self.assertFalse(any(command.startswith("PP LOAD") or command.startswith("PP SAVE") for command in self.client.commands))

    def test_new_save_rejects_known_catalog_mismatch_without_replacing_staged_unit(self):
        for field, value in (("UnitType", "KEY4"), ("FirmwareVersion", "1.2.67"), ("CatalogNumber", "OTHER")):
            self.client.responses[f"DBGET //CLI_TEST/254/p/20/{field}"] = Reply((f"342 {field}={value}",), 342)
        with self.session() as session:
            session.new("KEY4", "1.2.67", catalog_number="5034N")
            with self.assertRaisesRegex(ProgrammingError, "CatalogNumber"):
                session.save("/db//CLI_TEST/254/p/20")
            self.assertIsNone(session.source)
            self.assertEqual(session.catalog_number, "5034N")
        self.assertFalse(any(command.startswith("PP LOAD") for command in self.client.commands))

    def test_native_null_catalog_is_unknown_not_a_literal_catalog_name(self):
        self.client.responses["DBGET //CLI_TEST/254/p/20"] = Reply(("342-/UnitType=KEY4", "342-/FirmwareVersion=1.2.67", "342 /CatalogNumber=null"), 342)
        with self.session() as session:
            session.load("/db//CLI_TEST/254/p/20")
            self.assertIsNone(session.catalog_number)

    def test_parameter_text_is_escaped_without_changing_vector_grammar(self):
        self.assertEqual(quote_value("A  B"), '"A\\ \\ B"')
        self.assertEqual(quote_value('A"B'), '"A\\"B"')
        self.assertEqual(quote_value("A\\B"), '"A\\\\B"')
        self.assertEqual(quote_value(""), '""')
        for value in ("x\rPP END victim", "x\n", "\x00", "\t", 7):
            with self.subTest(value=value), self.assertRaises(ProgrammingError):
                quote_value(value)
        with self.session() as session:
            for parameter in ("X\nPP END victim", "Space Name", "X\"quoted"):
                with self.assertRaises(ProgrammingError):
                    session.set(parameter, "v")

    def test_parse_values_preserves_equals_and_trailing_padding(self):
        reply = Reply(("315-Name=A=B   ", "315 GroupAddress=0x1 0xff"), 315)
        self.assertEqual(parameter_values(reply), {"Name": "A=B   ", "GroupAddress": "0x1 0xff"})
        with self.assertRaises(ProgrammingError):
            parameter_values(Reply(("315-Name=a", "315 Name=b"), 315))
        with self.assertRaises(ProgrammingError):
            parameter_values(Reply(("315 missingequals",), 315))

    def test_native_errors_in_continuations_are_not_hidden_by_final_success(self):
        self.client.responses["PP UNITS"] = Reply(("460-Missing parameter", "200 OK."))
        with self.assertRaises(ProgrammingCommandError) as failure:
            self.programmer.units()
        self.assertEqual(failure.exception.errors[0][0], 460)

    def test_xml_extraction(self):
        reply = Reply(("343-Begin XML", '347-<?xml version="1.0"?>', "347-<Parameters/>", "344 End XML"), 344)
        self.assertEqual(xml_text(reply), '<?xml version="1.0"?>\n<Parameters/>')
        with self.assertRaises(ProgrammingError):
            xml_text(Reply())

    def test_session_command_builders(self):
        with self.session() as session:
            session.load_from_file("KEY4.xml")
            session.info("GroupAddress")
            session.get("*")
            session.reset_defaults()
            session.get_raw_data(32, 2)
            session.set_raw_data(32, bytes([1, 255]))
            session.debug_memory(32)
            session.copy("/db//CLI_TEST/254/p/20", "/db//CLI_TEST/254/p/21", tags=["all"])
        for command in ["PP LOAD_FROM_FILE CLI_TEST_SESSION KEY4.xml", "PP INFO CLI_TEST_SESSION GroupAddress", "PP GET CLI_TEST_SESSION *", "PP RESET_TO_DEFAULTS CLI_TEST_SESSION", "PP GET_RAW_DATA CLI_TEST_SESSION 32 2", "PP SET_RAW_DATA CLI_TEST_SESSION 32 01ff", "PP DEBUG mem CLI_TEST_SESSION 20", 'PP COPY CLI_TEST_LOCK /db//CLI_TEST/254/p/20 /db//CLI_TEST/254/p/21 "all"']:
            self.assertIn(command, self.client.commands)

    def test_programmer_command_builders(self):
        self.programmer.list_locks(); self.programmer.units(); self.programmer.get_unit_spec("KEY4.xml"); self.programmer.get_unit_catalog(); self.programmer.reload_catalog(); self.programmer.catalog_info(); self.programmer.list_catalog_numbers("KEY4", "1.2.67"); self.programmer.patch_version(debug=True); self.programmer.write_patch("/db//CLI_TEST/254/p/20", 16, simulate=True); self.programmer.quickget("//CLI_TEST/254/p/20"); self.programmer.cancel_lock("//CLI_TEST/254")
        self.assertEqual(self.client.commands, ["PP LIST_LOCK", "PP UNITS", "PP GET_UNIT_SPEC KEY4.xml", "PP GET_UNIT_CATALOG", "PP RELOAD_CATALOG", "PP CATALOG_INFO", "PP LIST_CATALOG_NUMBERS KEY4 1.2.67", "PP PATCH_VERSION debug", "PP WRITE_PATCH /db//CLI_TEST/254/p/20 10 simulate", "PP QUICKGET //CLI_TEST/254/p/20 *", "PP CANCEL_LOCK //CLI_TEST/254"])

    def test_raw_data_and_tag_validation(self):
        with self.session() as session:
            for data in ("", "0", "GG", "0a 0b", "00\nPP END victim"):
                with self.subTest(data=data), self.assertRaises(ProgrammingError):
                    session.set_raw_data(0, data)
            for start, count in ((-1, 1), (0, 0), (True, 1), (0, 1.5)):
                with self.assertRaises(ProgrammingError):
                    session.get_raw_data(start, count)
            with self.assertRaises(ProgrammingError):
                session.load("/db//CLI_TEST/254/p/20", tags="all")
        with self.assertRaises(ProgrammingError):
            self.programmer.write_patch("target", 256)

    def test_parameter_export_import_preflights_all_fields(self):
        self.client.responses["PP GET CLI_TEST_SESSION *"] = Reply(("315-Name=TEST    ", "315 Groups=0x1 0x2"), 315)
        with self.session() as session:
            snapshot = session.export_parameters()
            self.assertEqual(snapshot["format"], "cbus-cli-parameters-v1")
            session.import_parameters(snapshot)
            before = len(self.client.commands)
            with self.assertRaises(ProgrammingError):
                session.import_parameters({"format": "cbus-cli-parameters-v1", "parameters": {"Good": "value", "Bad": "\n"}})
            self.assertEqual(len(self.client.commands), before)
            with self.assertRaises(ProgrammingError):
                session.import_parameters({"format": "unknown", "parameters": {}})
            session.unit_type = "KEY4"
            with self.assertRaises(ProgrammingError):
                session.import_parameters(dict(snapshot, unit_type="RELAY"))

    def checksum_schema(self, *, fields=""):
        return Reply((
            "343-Begin XML snippet", '347-<Parameters><Param><Name>EEPROM Checksum</Name>'
            '<Type>int</Type><Address>$1F</Address><Protection>checksum</Protection>' + fields +
            '</Param></Parameters>', "344 End XML snippet"), 344)

    def test_spaced_parameter_uses_native_schema_byte_write_and_readback(self):
        self.client.responses["PP INFO CLI_TEST_SESSION *"] = self.checksum_schema()
        self.client.responses["PP GET CLI_TEST_SESSION *"] = Reply(("315-EEPROM Checksum=0x7b", "315 Other=0xff"), 315)
        with self.session() as session:
            session.set("EEPROM Checksum", "0x7b")
            self.assertEqual(session.values("EEPROM Checksum"), {"EEPROM Checksum": "0x7b"})
            self.assertIn("<Name>EEPROM Checksum</Name>", xml_text(session.info("EEPROM Checksum")))
        self.assertIn("PP SET_RAW_DATA CLI_TEST_SESSION 31 7b", self.client.commands)
        self.assertFalse(any(command.startswith("PP SET CLI_TEST_SESSION EEPROM") for command in self.client.commands))

    def test_spaced_parameter_limits_and_schema_preflight_before_any_write(self):
        for fields, value in (("", "256"), ("", "-1"), ("<BitSize>7</BitSize>", "1"),
                              ("<ArraySize>2</ArraySize>", "1"), ("<BitAddress>1</BitAddress>", "1"),
                              ("<MinValue>5</MinValue>", "4")):
            with self.subTest(fields=fields, value=value):
                self.client.responses["PP INFO CLI_TEST_SESSION *"] = self.checksum_schema(fields=fields)
                with self.session() as session:
                    start = len(self.client.commands)
                    with self.assertRaises(ProgrammingError):
                        session.import_parameters({"format": "cbus-cli-parameters-v1", "parameters": {
                            "Good": "1", "EEPROM Checksum": value}})
                    self.assertFalse(any(command.startswith(("PP SET ", "PP SET_RAW_DATA "))
                                         for command in self.client.commands[start:]))

    def test_spaced_parameter_failed_readback_is_not_success(self):
        self.client.responses["PP INFO CLI_TEST_SESSION *"] = self.checksum_schema()
        self.client.responses["PP GET CLI_TEST_SESSION *"] = Reply(("315 EEPROM Checksum=0x0",), 315)
        with self.session() as session:
            with self.assertRaisesRegex(ProgrammingError, "readback differed"):
                session.set("EEPROM Checksum", "1")

    def test_spaced_unit_type_reports_native_grammar_limitation(self):
        with self.session() as session:
            before = len(self.client.commands)
            with self.assertRaisesRegex(NativeCommandLimitation, "cannot represent"):
                session.new("WTXU 2FL", "0", catalog_number="5882TXWMBA")
            self.assertEqual(len(self.client.commands), before)

    def test_database_load_records_identity_and_rejects_mismatched_import_before_set(self):
        with self.session() as session:
            session.load("/db//CLI_TEST/254/p/20")
            self.assertEqual((session.unit_type, session.firmware, session.catalog_number), ("KEY4", "1.2.67", "5034N"))
            for field, wrong in (("unit_type", "RELAY"), ("firmware", "9.0"), ("catalog_number", "OTHER")):
                snapshot = {"format": "cbus-cli-parameters-v1", "unit_type": "KEY4", "firmware": "1.2.67",
                            "catalog_number": "5034N", "parameters": {"Application": "0x38"}}
                snapshot[field] = wrong
                before = len(self.client.commands)
                with self.assertRaisesRegex(ProgrammingError, "differs"):
                    session.import_parameters(snapshot)
                self.assertEqual(len(self.client.commands), before)

    def test_database_load_requires_unambiguous_unit_identity(self):
        for lines in (("342 /TagName=Test",), ("342-/UnitType=KEY4", "342-/UnitType=OTHER", "342 /FirmwareVersion=1")):
            self.client.responses["DBGET //CLI_TEST/254/p/20"] = Reply(lines, 342)
            with self.session() as session:
                with self.assertRaises(ProgrammingError):
                    session.load("/db//CLI_TEST/254/p/20")

    def test_database_address_conversion(self):
        self.assertEqual(database_address("//CLI_TEST/254/p/20"), "/db//CLI_TEST/254/p/20")
        self.assertEqual(database_address("/db//CLI_TEST/254/p/20"), "/db//CLI_TEST/254/p/20")
        self.assertEqual(database_address("254/p/20"), "/db/254/p/20")


@unittest.skipUnless(os.environ.get("CBUS_CGATE_TEST_HOST"), "Set CBUS_CGATE_TEST_HOST for disposable native C-Gate acceptance")
class NativeProgrammingTest(unittest.TestCase):
    def setUp(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase, NativeProjects
        self.project = "P" + uuid4().hex[:7].upper()
        self.fixture = CGateClient(os.environ["CBUS_CGATE_TEST_HOST"],
                                   port=int(os.environ.get("CBUS_CGATE_TEST_PORT", "20023")), timeout=20)
        self.fixture.__enter__()
        self.addCleanup(self.fixture.close)
        projects = NativeProjects(self.fixture)
        projects.operation("new", self.project)
        # Unsaved projects exist only in memory; closing discards this owned fixture.
        self.addCleanup(projects.operation, "close", self.project)
        NativeDatabase(self.fixture).create_network(self.project, 254, "Offline", "Cni", "127.0.0.1:29999")

    def test_offline_defaults_edit_copy_export_import_and_cleanup(self):
        from cbus_toolkit.cgate import CGateClient, CGateError
        host = os.environ["CBUS_CGATE_TEST_HOST"]
        port = int(os.environ.get("CBUS_CGATE_TEST_PORT", "20023"))
        with CGateClient(host, port=port, timeout=20) as client:
            programmer = Programmer(client)
            created = []
            try:
                for address in (220, 221):
                    client.command(f"DBADDSAFE //{self.project}/254 Unit {address} CLI_TEST_U{address}")
                    created.append(address)
                    for field, value in (("UnitType", "KEY4"), ("FirmwareVersion", "1.2.67"), ("UnitName", "KEY4")):
                        client.command(f"DBSET //{self.project}/254/p/{address}/{field} {value}")
                session_name = "CLI_TEST_NATIVE_" + uuid4().hex[:8]
                with programmer.new(f"//{self.project}/254", "KEY4", "1.2.67", name=session_name) as session:
                    self.assertEqual(session.values("UnitName")["UnitName"].rstrip(), "NEWUNIT")
                    for text in ("A  B", 'A"B', "A\\B"):
                        session.set("UnitName", text)
                        self.assertEqual(session.values("UnitName")["UnitName"].rstrip(), text)
                    self.assertIn("<Param", xml_text(session.info("UnitName")))
                    snapshot = session.export_parameters()
                    session.reset_defaults()
                    session.import_parameters(snapshot)
                    self.assertEqual(session.values(), snapshot["parameters"])
                    self.assertIn("RawData=ff38", "\n".join(session.get_raw_data(32, 2).lines))
                    session.set_raw_data(33, "30")
                    self.assertEqual(session.values("Application")["Application"], "0x30 0xff")
                self.assertNotIn(session_name, "\n".join(programmer.units().lines))
                # Regression: the CLI creates a fresh connection after another
                # connection creates the project, then NEW -> SAVE previously
                # triggered C-Gate's null-source internal error.
                with CGateClient(host, port=port, timeout=20) as fresh:
                    with Programmer(fresh).new(f"//{self.project}/254", "KEY4", "1.2.67", name="CLI_TEST_FRESH_" + uuid4().hex[:8]) as session:
                        session.set("UnitName", "FRESH")
                        session.set_raw_data(33, "30")
                        before_save = session.values()
                        session.save(f"/db//{self.project}/254/p/220")
                        self.assertEqual(session.values(), before_save)
                fresh_values = parameter_values(programmer.quickget(f"//{self.project}/254/p/220"))
                self.assertEqual(fresh_values["UnitName"].rstrip(), "FRESH")
                self.assertEqual(fresh_values["Application"], "0x30 0xff")
                source = f"/db//{self.project}/254/p/220"
                destination = f"/db//{self.project}/254/p/221"
                with programmer.load(f"//{self.project}/254", source, name="CLI_TEST_NATIVE_DB_" + uuid4().hex[:8]) as session:
                    self.assertEqual(session.unit_type, "KEY4")
                    self.assertEqual(session.firmware, "1.2.67")
                    identity_snapshot = session.export_parameters()
                    with self.assertRaisesRegex(ProgrammingError, "differs"):
                        session.import_parameters(dict(identity_snapshot, unit_type="KEYC1"))
                    self.assertEqual(session.values(), identity_snapshot["parameters"])
                    session.set("UnitName", "DB UNIT")
                    session.save_to_source()
                    self.assertEqual(parameter_values(programmer.quickget(f"//{self.project}/254/p/220", "UnitName"))["UnitName"].rstrip(), "DB UNIT")
                    session.copy(source, destination)
                    self.assertEqual(parameter_values(programmer.quickget(f"//{self.project}/254/p/221", "UnitName"))["UnitName"].rstrip(), "DB UNIT")
                    session.set("UnitName", "SAVE AS")
                    session.save(destination)
                    self.assertEqual(parameter_values(programmer.quickget(f"//{self.project}/254/p/221", "UnitName"))["UnitName"].rstrip(), "SAVE AS")
                self.assertIn("<Parameters", xml_text(programmer.get_unit_spec("KEY4.xml")))
            finally:
                for address in reversed(created):
                    client.command(f"DBDELETE //{self.project}/254/p/{address}")

    def test_spaced_checksum_actual_byte_change_reset_and_import(self):
        from cbus_toolkit.cgate import CGateClient, CGateError
        with CGateClient(os.environ["CBUS_CGATE_TEST_HOST"],
                         port=int(os.environ.get("CBUS_CGATE_TEST_PORT", "20023")), timeout=20) as client:
            with Programmer(client).new(f"//{self.project}/254", "KEYC1", "2.5.00", catalog_number="5031NL",
                                        name="CLI_TEST_CHECKSUM_" + uuid4().hex[:8]) as session:
                before = session.get_raw_data(30, 3).lines[-1].split("=", 1)[1]
                session.set("EEPROM Checksum", "0x72")
                after = session.get_raw_data(30, 3).lines[-1].split("=", 1)[1]
                self.assertEqual(after, before[:2] + "72" + before[4:])
                self.assertEqual(session.values("EEPROM Checksum"), {"EEPROM Checksum": "0x72"})
                self.assertIn("<Name>EEPROM Checksum</Name>", xml_text(session.info("EEPROM Checksum")))
                snapshot = session.export_parameters()
                session.reset_defaults()
                self.assertEqual(session.values("EEPROM Checksum"), {"EEPROM Checksum": "0x0"})
                session.import_parameters(snapshot)
                self.assertEqual(session.values(), snapshot["parameters"])


if __name__ == "__main__":
    unittest.main()
