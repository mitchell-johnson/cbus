"""Toolkit 1.18.0.2754 barcode-scanner rules against original-emulated vectors."""
import json
from pathlib import Path
import tempfile
import unittest

from cbus_toolkit import barcode_scanner as model
from cbus_toolkit.barcode_scanner import BarcodeCatalog, BarcodeError, add_unit
from cbus_toolkit.project import ProjectDocument

ROOT = Path(__file__).resolve().parents[1]
RECEIPT = json.loads((ROOT / "research/fixtures/barcode-scanner-original-vectors.json").read_text())
VECTORS = RECEIPT["vectors"]
CONFIG = "5031NL          123456789012"


def unit(catalog, unit_type, *, alternatives="", family="Wired", default="1.2.00", extra=""):
    alt = f"<AlternativeCatalogNumbers>{alternatives}</AlternativeCatalogNumbers>" if alternatives else ""
    return (f"<Unit><UnitTitle>Family={family};Category=Test</UnitTitle><CatalogNumber>{catalog}</CatalogNumber>{alt}"
            f"<FirmwareRevisions><Revision><MinVersion>1.0.00</MinVersion><UnitType>{unit_type}</UnitType>"
            f"<IsDefault>false</IsDefault></Revision><Revision><MinVersion>{default}</MinVersion>"
            f"<UnitType>{unit_type}</UnitType><IsDefault>true</IsDefault></Revision></FirmwareRevisions>{extra}</Unit>")


CATALOG_XML = "<CBusUnits><Units>" + "".join((
    unit("5031NL", "KEYBL5", alternatives="C5031NL;SC5031NL"),
    unit("L5504D1A,B", "DIMDN4"),
    unit("5500SHAC-*", "SHAC"),
    unit("E3031D*", "KEYE1"),
    unit("5031RDTSL", "WKEY", family="Wireless"),
    unit("PARENT", "PARENT", extra="<SubUnits>" + unit("CHILD", "CHILD") + "</SubUnits>"),
    unit("NOREV", ""),
    unit("0SENSOR", "SENS"),
)) + "</Units></CBusUnits>"
PROJECT_XML = """<?xml version="1.0"?>
<Installation><Project><TagName>HOME</TagName><Address>1</Address>
<Network><TagName>Local</TagName><Address>254</Address>
<Unit><TagName>One</TagName><Address>1</Address><UnitType>KEYE1</UnitType><SerialNumber>1234.5</SerialNumber></Unit>
<Unit><TagName>Three</TagName><Address>3</Address><UnitType>KEYE1</UnitType><SerialNumber></SerialNumber></Unit>
</Network>
<Network><TagName>Other</TagName><Address>253</Address>
<Unit><TagName>Far</TagName><Address>9</Address><UnitType>RELDN4</UnitType><SerialNumber>990001.2</SerialNumber></Unit>
</Network>
<Network><TagName>Air</TagName><Address>252</Address>
<Unit><TagName>W</TagName><Address>2</Address><UnitType>WKEY</UnitType><SerialNumber></SerialNumber></Unit>
</Network>
</Project></Installation>
"""


class OriginalVectorTests(unittest.TestCase):
    def test_receipt_pins_executable_and_contains_no_code_bytes(self):
        self.assertEqual(RECEIPT["format"], "cbus-toolkit-barcode-scanner-original-v1")
        self.assertEqual(RECEIPT["executable_sha256"], "9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab")
        self.assertEqual(set(RECEIPT["methods"]["CIS_TfrmSoftwareLabel.IsSerialNumber"]), {"start", "end", "sha256"})
        self.assertEqual(RECEIPT["piced_negative_search"]["map_symbol_matches"], 0)
        for identifier, text in model.MESSAGES.items():
            registered = RECEIPT["registered_messages"][str(identifier)]
            self.assertEqual(registered, "%1" if identifier == 2066 else
                             text.replace('"{network}"', '"%1"').replace("a new Unit.", "a new %1."))

    def test_keystroke_buffer_and_idle_timer(self):
        for vector in VECTORS["keystrokes"]:
            with self.subTest(vector["events"]):
                got = model.acquire([tuple(event) for event in vector["events"]])
                self.assertEqual(got["modal_result"], vector["modal_result"])
                if vector["modal_result"] == 1:
                    self.assertEqual(got["barcode"], vector["buffer"])

    def test_unit_dialog_serial_scan(self):
        for vector in VECTORS["is_serial_number"]:
            with self.subTest(vector["input"]):
                got = model.unit_dialog_serial(vector["input"])
                self.assertEqual(got["accepted"], vector["accepted"])
                if vector["accepted"]:
                    self.assertEqual(got["serial"], vector["serial"])
                    self.assertEqual([got["message_id"]], vector["message_ids"])
                else:
                    self.assertEqual([got["message"]], vector["wrong_barcode_form"])

    def test_units_view_dispatch(self):
        for vector in VECTORS["process_barcode"]:
            with self.subTest(vector["input"]):
                got = model.units_view_actions(vector["input"])
                expected = [("add_by_catalog_code", call["text"]) if call["call"] == "AddUnitByCatalogCode"
                            else ("find_by_serial", call["serial"]) for call in vector["calls"]]
                self.assertEqual([(a["action"], a["barcode"] if "barcode" in a else a["serial"]) for a in got], expected)

    def test_software_config_split(self):
        for vector in VECTORS["add_by_catalog_code"]:
            calls = {call["call"]: call for call in vector["calls"]}
            if "HandleScannedSerialNumber" not in calls:
                continue
            with self.subTest(vector["input"]):
                config = model._split_fields(vector["input"])
                self.assertEqual(config.serial, calls["HandleScannedSerialNumber"]["serial"])
                if "FindUnitByCatalogCode" in calls:
                    self.assertEqual(config.catalog_lookup, calls["FindUnitByCatalogCode"]["catalog"])
                if "AddUnit" in calls:
                    self.assertEqual(config.catalog_field, calls["AddUnit"]["catalog_number"])

    def test_catalog_add_branch_order(self):
        for vector in VECTORS["add_by_catalog_code"]:
            with self.subTest(vector["fixtures"]):
                got = model.catalog_add_outcome(**vector["fixtures"])
                calls = [call["call"] for call in vector["calls"]]
                expected = ("add" if "AddUnit" in calls else "error" if vector["message_ids"] else
                            "selected_existing" if vector["fixtures"]["serial_found"] and calls else "ignored")
                self.assertEqual(got["outcome"], expected)
                self.assertEqual([got["message_id"]] if "message_id" in got else [], vector["message_ids"])

    def test_serial_normalization_and_matching(self):
        for vector in VECTORS["displayable_serial"]:
            self.assertEqual(model.displayable_serial(vector["input"]), vector["displayable"], vector)
        for vector in VECTORS["set_serial_number"]:
            self.assertEqual([model.stored_serial(vector["input"])], vector["stored"], vector)
        for vector in VECTORS["unit_by_serial_number"]:
            got = next((index for index, value in enumerate(vector["existing"])
                        if model.serials_match(vector["input"], value)), None)
            self.assertEqual(got, vector["match_index"], vector)


class ModelTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.dir = Path(directory.name)
        (self.dir / "cbusunits.xml").write_text(CATALOG_XML)
        self.catalog = BarcodeCatalog.load(self.dir / "cbusunits.xml")
        (self.dir / "p.xml").write_text(PROJECT_XML)
        self.project = ProjectDocument.load(self.dir / "p.xml")

    def test_wedge_lines_and_invalid_input(self):
        self.assertEqual(model.wedge_lines("A\r\nB\n\r\n\rC\r"), ["A", "B", "C"])
        with self.assertRaises(TypeError):
            model.parse(b"123456789012")
        with self.assertRaises(BarcodeError) as caught:
            model.parse("12345678901\U0001F600")
        self.assertEqual(caught.exception.details["code"], "non_bmp_input")
        self.assertEqual(model.acquire([("key", "A", 0), ("escape", None, 5)])["barcode"], "")

    def test_parse_reports_both_consumers(self):
        result = model.parse("93" + "1" * 11)
        self.assertTrue(result["units_view"]["ignored"])
        self.assertEqual(result["unit_dialog"]["reason"], "wrong_barcode")
        dialog = model.parse(CONFIG)["unit_dialog"]
        self.assertEqual((dialog["serial"], dialog["stored_serial"], dialog["catalog_number"]),
                         ("123456789012", "12345678.9012", "5031NL"))

    def test_catalogue_rules(self):
        find = lambda code: getattr(self.catalog.find(code), "unit_code", None)  # noqa: E731
        self.assertEqual(find("5031nl"), "KEYBL5")          # ASCII case fold
        self.assertEqual(find("SC5031NL"), "KEYBL5")        # last alternative only via its clone
        self.assertEqual(find("L5504D1A"), "DIMDN4")        # catalogue truncated at ','
        self.assertEqual(find("5500SHAC"), "SHAC")          # '-' wins before '*'
        self.assertEqual(find("E3031DZZ"), "KEYE1")         # '*' prefix
        self.assertEqual(find("CHILD"), "CHILD")            # SubUnits are searched
        self.assertIsNone(find("UNKNOWN"))
        self.assertIsNone(find("5031NLé"))
        self.assertFalse(model._alternates_match("C5031NL;SC5031NL", "SC5031NL"))  # original drops final char
        self.assertTrue(model._alternates_match("C5031NL;SC5031NL", "C5031NL"))
        self.assertEqual(self.catalog.default_firmware("keybl5"), "1.2.00")
        self.assertEqual(self.catalog.default_firmware("MISSING"), model.DEFAULT_FIRMWARE)

    def test_add_unit_next_free_address_and_metadata(self):
        result = add_unit(self.project, "/network/254", CONFIG, self.catalog)
        self.assertEqual((result["action"], result["address"], result["unit"]), ("added", 2, "/network/254/unit/2"))
        fields = self.project.get("/network/254/unit/2")["fields"]
        self.assertEqual({k: fields[k] for k in ("TagName", "UnitType", "SerialNumber", "CatalogNumber",
                                                 "FirmwareVersion", "UnitName", "State")},
                         {"TagName": "NEWUNIT", "UnitType": "KEYBL5", "SerialNumber": "12345678.9012",
                          "CatalogNumber": "5031NL", "FirmwareVersion": "1.2.00", "UnitName": "NEWUNIT", "State": "New"})

    def test_add_unit_explicit_address_and_tag(self):
        result = add_unit(self.project, "/network/254", "5031NL          000000000042", self.catalog,
                          address=0, tag_name="Hall")
        self.assertEqual((result["address"], result["tag_name"], result["automatic_address"]), (0, "Hall", 2))
        with self.assertRaises(BarcodeError) as caught:
            add_unit(self.project, "/network/254", "5031NL          000000000043", self.catalog, address=3)
        self.assertEqual(caught.exception.details["code"], "address_unavailable")

    def test_duplicate_serial_selects_existing_unit_in_any_network(self):
        before = self.project.to_xml_bytes()
        result = add_unit(self.project, "/network/254", "E3031D          009900010002", self.catalog)
        self.assertEqual((result["action"], result["unit"], result["changed"]), ("selected_existing", "/network/253/unit/9", False))
        result = add_unit(self.project, "/network/254", "E3031D          000012340005", self.catalog)
        self.assertEqual(result["unit"], "/network/254/unit/1")
        self.assertEqual(self.project.to_xml_bytes(), before)

    def test_unidentified_serial_never_selects(self):
        result = add_unit(self.project, "/network/254", "E3031D          000000000000", self.catalog)
        self.assertEqual((result["action"], self.project.get(result["unit"])["fields"]["SerialNumber"]),
                         ("added", "00000000.0000"))

    def test_zero_prefixed_configuration_also_runs_serial_lookup(self):
        result = add_unit(self.project, "/network/254", "0SENSOR         000000000077", self.catalog)
        self.assertEqual((result["action"], result["serial_lookup"]["found"]), ("added", None))
        self.assertEqual([w["toolkit_message_id"] for w in result["warnings"]], [2096])

    def test_errors(self):
        cases = {
            "wrong_barcode": ("/network/254", "123456789012"),
            "unknown_unit_type": ("/network/254", "ZZZ             123456789012"),
            "catalog_entry_without_type": ("/network/254", "NOREV           123456789012"),
            "network_not_selected": ("/network/7", CONFIG),
            "not_units_node": ("/network/254/unit/1", CONFIG),
            "wired_unit_on_wireless_network": ("/network/252", CONFIG),
            "wireless_unit_on_wired_network": ("/network/254", "5031RDTSL       123456789012"),
        }
        for code, (network, barcode) in cases.items():
            with self.subTest(code):
                with self.assertRaises(BarcodeError) as caught:
                    add_unit(self.project, network, barcode, self.catalog)
                self.assertEqual(caught.exception.details["code"], code)

    def test_address_exhaustion_and_recommended_maximum(self):
        project = ProjectDocument.new("FULL")
        project.add("network", "/", address=254, name="Net")
        for address in range(1, 101):
            project.add("unit", "/network/254", address=address, fields={"UnitType": "KEYE1"})
        result = add_unit(project, "/network/254", CONFIG, self.catalog)
        self.assertEqual(result["address"], 101)
        self.assertEqual([w["toolkit_message_id"] for w in result["warnings"]], [45141])
        for address in range(102, 256):
            project.add("unit", "/network/254", address=address, fields={"UnitType": "KEYE1"})
        with self.assertRaises(BarcodeError) as caught:
            add_unit(project, "/network/254", "5031NL          000000000099", self.catalog)
        self.assertEqual(caught.exception.details["code"], "database_full")


if __name__ == "__main__":
    unittest.main()
