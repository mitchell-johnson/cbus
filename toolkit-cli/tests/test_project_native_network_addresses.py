"""Read and edit the original server's materialized Network identities."""
from pathlib import Path
import json
import tempfile
import unittest
from zipfile import ZipFile

from cbus_toolkit.project import IntegrityError, ProjectDocument, ProjectError


FIXTURE = Path(__file__).resolve().parents[2] / "rust/testdata/fixtures/native_cgate_net_save_db_materialization.json"


def captured_project():
    capture = json.loads(FIXTURE.read_text())
    row = next(row for row in capture["commands"] if row["label"] == "project-save1")
    return "\n".join(line.split("347-", 1)[1] for line in row["response"] if "347-" in line).encode()


def descendants(node, tag):
    return list(node.getElementsByTagName(tag))


def text(node, tag):
    child = next(child for child in node.childNodes if child.nodeType == child.ELEMENT_NODE and child.tagName == tag)
    return "".join(c.data for c in child.childNodes if c.nodeType in (c.TEXT_NODE, c.CDATA_SECTION_NODE))


class NativeNetworkAddressProjectTests(unittest.TestCase):
    def setUp(self):
        self.data = captured_project()
        self.project = ProjectDocument.from_bytes(self.data)
        self.nodes = {text(n, "Address"): n for n in descendants(self.project.project, "Network")}

    def test_original_materialized_project_inspects_and_lists_every_network(self):
        self.assertEqual(self.project.validate(), [])
        self.assertEqual(self.project.inspect()["counts"]["network"], len(self.nodes))
        records = self.project.list_entities(kind="network")
        self.assertEqual([r["fields"]["Address"] for r in records], list(self.nodes))
        self.assertEqual(len({r["fields"]["OID"] for r in records}), len(records))

    def test_captured_address_lexemes_and_case_are_independent_of_network_number(self):
        for address in ("42", "0254", "254", "256", "255", "0xff", "CustomA", "Customa", "Duplicates"):
            with self.subTest(address=address):
                fields = self.project.get("/network/" + address)["fields"]
                self.assertEqual(fields["Address"], address)
                self.assertEqual(fields["OID"], text(self.nodes[address], "OID"))
                self.assertEqual(fields["NetworkNumber"], "254" if address == "254" else "0xff")
                self.assertIs(self.project.resolve("oid:" + fields["OID"]), self.nodes[address])
        self.assertNotEqual(self.project.get("/0254"), self.project.get("/254"))
        with self.assertRaises(ProjectError):
            self.project.get("/network/CUSTOMA")

    def test_xml_and_cbz_roundtrips_preserve_complete_native_dom_and_original_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            xml = root / "snapshot.xml"
            cbz = root / "snapshot.cbz"
            self.project.save(xml)
            self.project.save(cbz, format="cbz")
            self.assertEqual(xml.read_bytes(), self.data)
            loaded = ProjectDocument.load(cbz)
            self.assertEqual(loaded.document.toxml(), self.project.document.toxml())
            self.assertEqual(loaded.validate(), [])
            with ZipFile(cbz) as archive:
                self.assertEqual(archive.read(loaded.xml_member), self.data)

    def test_named_network_edit_preserves_interfaces_properties_and_unrelated_rows(self):
        before = {a: n.toxml() for a, n in self.nodes.items()}
        interface = self.nodes["Duplicates"].getElementsByTagName("Interface")[0].toxml()
        self.project.set_field("/network/Duplicates", "TagName", "Edited & reviewed")
        self.assertEqual(self.project.get("/Duplicates")["fields"]["TagName"], "Edited & reviewed")
        self.assertEqual(self.project.resolve("/Duplicates").getElementsByTagName("Interface")[0].toxml(), interface)
        for address in self.nodes.keys() - {"Duplicates"}:
            self.assertEqual(self.project.resolve("/" + address).toxml(), before[address])

    def test_copy_named_subtree_retains_values_and_allocates_complete_fresh_identities(self):
        original = self.project.resolve("/Duplicates")
        original_properties = [(text(p, "Name"), text(p, "Value")) for p in descendants(original, "Property")]
        old_oids = {"".join(c.data for c in n.childNodes if c.nodeType == c.TEXT_NODE) for n in descendants(original, "OID")}
        result = self.project.copy("/Duplicates", "/", address="DuplicateCopy", name="Copy")
        copied = self.project.resolve(result["path"])
        self.assertEqual(result["fields"]["Address"], "DuplicateCopy")
        self.assertEqual(result["fields"]["NetworkNumber"], "0xff")
        self.assertEqual([(text(p, "Name"), text(p, "Value")) for p in descendants(copied, "Property")], original_properties)
        new_oids = {"".join(c.data for c in n.childNodes if c.nodeType == c.TEXT_NODE) for n in descendants(copied, "OID")}
        self.assertEqual(len(new_oids), len(old_oids))
        self.assertFalse(old_oids & new_oids)
        self.assertEqual(self.project.validate(), [])

    def test_move_named_address_preserves_network_number_and_all_subtree_identities(self):
        before = self.project.resolve("/CustomA").toxml()
        oid = self.project.get("/CustomA")["fields"]["OID"]
        result = self.project.move("/CustomA", "/", address="MovedA")
        self.assertEqual(result["fields"]["NetworkNumber"], "0xff")
        self.assertEqual(self.project.resolve("oid:" + oid).toxml(), before.replace("<Address>CustomA</Address>", "<Address>MovedA</Address>"))
        with self.assertRaises(ProjectError):
            self.project.get("/CustomA")

    def test_add_named_network_requires_explicit_native_number_representation(self):
        result = self.project.add("network", address="AddedA", name="Added", fields={"NetworkNumber": "0xff", "Interface/InterfaceType": "Cni", "Interface/InterfaceAddress": "127.0.0.1:1"})
        self.assertEqual(result["fields"]["Address"], "AddedA")
        self.assertEqual(result["fields"]["NetworkNumber"], "0xff")
        self.assertEqual(self.project.get_field(result["path"], "Interface/InterfaceType"), "Cni")
        self.assertEqual(self.project.validate(), [])

    def test_number_lexical_edits_do_not_rename_or_normalize_address(self):
        for number in ("255", "0xff"):
            with self.subTest(number=number):
                self.project.set_field("/network/0254", "NetworkNumber", number)
                self.assertEqual(self.project.get("/0254")["fields"]["NetworkNumber"], number)
                self.assertEqual(self.project.get("/0254")["fields"]["Address"], "0254")
                self.assertEqual(self.project.get("/254")["fields"]["NetworkNumber"], "254")

    def test_duplicate_or_invalid_edits_restore_the_complete_document(self):
        before = self.project.document.toxml()
        for field, value in (("Address", "Customa"), ("Address", "bad/path"), ("Address", ""), ("Address", "bad\nname"), ("NetworkNumber", "256")):
            with self.subTest(field=field, value=value), self.assertRaises((IntegrityError, ProjectError)):
                self.project.set_field("/CustomA", field, value)
            self.assertEqual(self.project.document.toxml(), before)

    def test_named_deletion_keeps_other_same_number_rows(self):
        count = len(self.nodes)
        self.project.delete("/CustomA")
        self.assertEqual(len(self.project.list_entities(kind="network")), count - 1)
        self.assertEqual(self.project.get("/Customa")["fields"]["NetworkNumber"], "0xff")
        self.assertEqual(self.project.get("/42")["fields"]["NetworkNumber"], "0xff")

    def test_legacy_numeric_aliases_and_other_entity_bounds_remain(self):
        legacy = ProjectDocument.from_bytes(b'<Installation><DBVersion>1</DBVersion><Project><Address>1</Address><Network><Address>254</Address><NetworkNumber>1</NetworkNumber><Application><Address>56</Address></Application></Network></Project></Installation>')
        self.assertEqual(legacy.get("/0xfe")["fields"]["Address"], "254")
        legacy.set_field("/254", "NetworkNumber", "255")
        self.assertEqual(legacy.get("/0xfe")["fields"]["Address"], "254")
        for address in ("Named", 256, True):
            with self.subTest(address=address), self.assertRaises(ProjectError):
                legacy.add("network", address=address)
        for address in ("Named", 256):
            with self.subTest(address=address), self.assertRaises(ProjectError):
                self.project.add("application", "/Duplicates", address=address)


if __name__ == "__main__":
    unittest.main()
