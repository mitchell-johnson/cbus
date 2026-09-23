"""Synthetic project-editor tests; no private project or device data is embedded."""
from io import BytesIO
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from xml.dom import minidom
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

from cbus_toolkit.project import ProjectDocument, ProjectError, IntegrityError, UnsupportedProjectFormat


FIXTURE = b'''<?xml version="1.0" encoding="UTF-8"?>
<?test before?>
<!--before root--><Installation xmlns="urn:legacy:test" xmlns:ext="urn:extension" custom="keep">
  <DBVersion>1</DBVersion>
  <Project oid="project-1"><TagName>TEST</TagName><Address>1</Address><Description>demo</Description>
    <Network oid="network-1"><TagName>Local</TagName><Address>254</Address><NetworkNumber>1</NetworkNumber>
      <Interface><InterfaceType>CNI</InterfaceType><InterfaceAddress>127.0.0.1:10001</InterfaceAddress></Interface>
      <Application oid="app-1"><TagName>Lighting</TagName><Address>56</Address>
        <Group oid="group-1"><TagName>First</TagName><Address>1</Address><Description><![CDATA[a < b]]><!--inner--></Description>
          <Level Value="255" oid="level-1"><TagName>Full</TagName><Address>255</Address></Level>
          <ext:Unknown ext:flag="true"><ext:Nested>keep</ext:Nested></ext:Unknown>
        </Group>
        <Group oid="group-2"><TagName>Second</TagName><Address>2</Address></Group>
      </Application>
      <Unit oid="unit-1"><TagName>Device</TagName><Address>12</Address><UnitType>RELAY</UnitType>
        <PP Name="GroupAddress" Value="0x1 0x2" custom="preserve"/>
        <ProgramBlock Type="EEPROM" Start="0" Bytes="2">0102</ProgramBlock>
      </Unit>
    </Network>
    <Network oid="network-2"><TagName>Remote</TagName><Address>253</Address></Network>
  </Project>
</Installation><!--after root-->
'''


def structural_xml(data):
    """Compare all DOM content while ignoring the declaration's encoding spelling."""
    return minidom.parseString(data).documentElement.toxml()


class ProjectTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.path = self.root / "source.xml"
        self.path.write_bytes(FIXTURE)
        self.project = ProjectDocument.load(self.path)

    def test_exact_unedited_xml_roundtrip(self):
        target = self.root / "saved.xml"
        self.project.save(target)
        self.assertEqual(target.read_bytes(), FIXTURE)

    def test_inspect_lists_and_compact_paths(self):
        report = self.project.inspect()
        self.assertEqual(report["format"], "legacy-xml")
        self.assertEqual(report["counts"], dict(network=2, application=1, group=2, level=1, unit=1))
        self.assertEqual(self.project.get("/254/56/1")["fields"]["TagName"], "First")
        self.assertEqual(self.project.get("oid:group-1")["path"], "/network/254/application/56/group/1")
        self.assertEqual(len(self.project.list_entities(recursive=True, kind="group")), 2)
        self.assertEqual(len(self.project.list_entities()), 2)
        self.assertEqual(self.project.validate(), [])

    def test_unknown_elements_comments_pi_cdata_and_namespaces_survive(self):
        self.project.set_field("/", "Description", "Edited & reviewed")
        self.project.save()
        updated = self.path.read_bytes()
        for part in (b"<!--before root-->", b"<!--after root-->", b"<?test before?>", b"<!--inner-->", b"<![CDATA[a < b]]>", b'<ext:Unknown ext:flag="true">', b'<ProgramBlock Type="EEPROM" Start="0" Bytes="2">0102</ProgramBlock>'):
            self.assertIn(part, updated)
        self.assertNotIn(b"ns0:", updated)
        self.assertEqual(ProjectDocument.load(self.path).metadata["Description"], "Edited & reviewed")

    def test_create_new_project_and_all_entity_kinds(self):
        project = ProjectDocument.new("NEW", description="new project", namespace="urn:new")
        project.add("network", address=254, name="Main", fields={"NetworkNumber": 1, "Interface/InterfaceType": "CNI"})
        project.add("application", "/254", address=56, name="Lighting")
        project.add("group", "/254/56", address=10, name="Kitchen")
        project.add("level", "/254/56/10", address=127, name="Half")
        project.add("unit", "/254", address=1, name="Relay", fields={"UnitType": "RELAY", "UnitName": "Output"})
        self.assertEqual(project.get_field("/254/56/10/127", "@Value"), "127")
        project.save(self.root / "new.cbz", format="cbz")
        loaded = ProjectDocument.load(self.root / "new.cbz")
        self.assertEqual(loaded.inspect()["counts"], dict(network=1, application=1, group=1, level=1, unit=1))
        self.assertEqual(loaded.document.documentElement.namespaceURI, "urn:new")

    def test_oid_child_style_retained_when_adding(self):
        project = ProjectDocument.from_bytes(b'<Installation><Project><OID>p</OID><TagName>TEST</TagName><Address>1</Address></Project></Installation>')
        project.add("network", address=254)
        node = project.resolve("/254")
        self.assertFalse(node.hasAttribute("oid"))
        self.assertTrue(project.get_field("/254", "OID"))

    def test_project_without_oids_does_not_invent_style(self):
        project = ProjectDocument.new("TEST")
        project.add("network", address=254)
        self.assertNotIn("oid", project.raw_xml().lower())

    def test_bad_entity_paths(self):
        for path in ("/unit/1", "/network", "/254/56/1/2/3", "/254/unit/12", "/network/-1", "/999", "oid:unknown"):
            with self.subTest(path=path), self.assertRaises(ProjectError):
                self.project.resolve(path)

    def test_address_validation(self):
        for address in (-1, 256, True, "1.5", None):
            with self.subTest(address=address), self.assertRaises(ProjectError):
                self.project.add("network", address=address)
        self.project.add("network", address="0x10")
        self.assertEqual(self.project.get_field("/16", "Address"), "16")

    def test_duplicate_address_and_failed_multi_field_update_roll_back(self):
        before = self.project.raw_xml()
        with self.assertRaises(ProjectError):
            self.project.add("group", "/254/56", address=1)
        self.assertEqual(self.project.raw_xml(), before)
        with self.assertRaises(ProjectError):
            self.project.update("/254/56/2", {"TagName": "changed", "Address": 1})
        self.assertEqual(self.project.raw_xml(), before)
        self.project.save()
        self.assertEqual(self.path.read_bytes(), FIXTURE)

    def test_generic_nested_fields_attributes_and_removal(self):
        self.project.set_field("/254", "Interface/InterfaceAddress", "localhost:10001")
        self.project.set_field("/254", "ext:Custom/@ext:flag", "yes")
        self.assertEqual(self.project.get_field("/254", "ext:Custom/@ext:flag"), "yes")
        self.project.remove_field("/254", "ext:Custom/@ext:flag")
        self.project.remove_field("/254", "ext:Custom")
        self.assertEqual(self.project.get_field("/254", "Interface/InterfaceAddress"), "localhost:10001")

    def test_scalar_edit_preserves_comment_and_handles_cdata_terminator(self):
        self.project.set_field("/254/56/1", "Description", "new ]]> value")
        self.assertIn("<!--inner-->", self.project.raw_xml())
        self.project.save()
        self.assertEqual(ProjectDocument.load(self.path).get_field("/254/56/1", "Description"), "new ]]> value")

    def test_reject_destructive_scalar_edit_and_invalid_xml_names(self):
        for field in ("Interface", "../Description", "Invalid Name", "@xmlns", "a:b:c", "unknown:Element"):
            before = self.project.raw_xml()
            with self.subTest(field=field), self.assertRaises(ProjectError):
                self.project.set_field("/254", field, "value")
            self.assertEqual(self.project.raw_xml(), before)
        with self.assertRaises(ProjectError):
            self.project.set_field("/", "Description", "invalid\x00")
        with self.assertRaises(ProjectError):
            self.project.remove_field("/254", "Interface")
        with self.assertRaises(ProjectError):
            self.project.remove_field("/254", "Address")

    def test_delete_leaf_and_cascade(self):
        self.project.delete("/254/56/2")
        self.assertEqual(len(self.project.list_entities("/254/56")), 1)
        with self.assertRaises(IntegrityError):
            self.project.delete("/254/56/1")
        self.project.delete("/254/56/1", cascade=True)
        self.assertEqual(self.project.list_entities("/254/56"), [])
        with self.assertRaises(ProjectError):
            self.project.delete("/", cascade=True)

    def test_copy_regenerates_oids_and_preserves_internal_references(self):
        self.project.set_field("/254/56/1", "ext:Reference", "level-1")
        result = self.project.copy("/254/56/1", "/254/56", address=3, name="Clone")
        self.assertEqual(result["path"], "/network/254/application/56/group/3")
        self.assertNotEqual(self.project.get_field("/254/56/3", "@oid"), "group-1")
        self.assertEqual(self.project.get_field("/254/56/3", "ext:Reference"), self.project.get_field("/254/56/3/255", "@oid"))
        self.assertIn("ext:Unknown", self.project.raw_xml("/254/56/3"))
        self.assertEqual(self.project.validate(), [])

    def test_move_preserves_oid(self):
        self.project.move("/254/56", "/253", address=48, name="Moved")
        self.assertEqual(self.project.get_field("/253/48", "@oid"), "app-1")
        self.assertEqual(self.project.list_entities("/254", kind="application"), [])
        with self.assertRaises(ProjectError):
            self.project.move("/253/48", "/253/48/1")

    def test_external_explicit_reference_protects_delete_and_oid_change(self):
        self.project.set_field("/network/254/unit/12", "ext:Reference", "group-2")
        for operation in (lambda: self.project.delete("/254/56/2"), lambda: self.project.set_field("/254/56/2", "@oid", "replacement")):
            with self.assertRaises(IntegrityError):
                operation()
        self.assertEqual(self.project.get_field("/254/56/2", "@oid"), "group-2")

    def test_parameter_crud_preserves_unknown_attributes_and_program_block(self):
        unit = "/network/254/unit/12"
        self.assertEqual(self.project.parameters(unit), {"GroupAddress": "0x1 0x2"})
        self.project.set_parameter(unit, "GroupAddress", "0x3 0x4")
        self.assertIn('custom="preserve"', self.project.raw_xml(unit))
        self.project.set_parameter(unit, "ClockGenEnable", "1")
        self.project.delete_parameter(unit, "ClockGenEnable")
        self.assertIn("ProgramBlock", self.project.raw_xml(unit))
        self.assertEqual(self.project.parameters(unit), {"GroupAddress": "0x3 0x4"})
        with self.assertRaises(ProjectError):
            self.project.parameters("/254")
        with self.assertRaises(ProjectError):
            self.project.delete_parameter(unit, "Missing")

    def test_opaque_parameters_are_never_silently_rewritten(self):
        self.project.update("/254/56/1", {"Address": 3})
        self.assertEqual(self.project.parameters("/network/254/unit/12")["GroupAddress"], "0x1 0x2")
        self.assertTrue(any("opaque" in text for text in self.project.inspect()["limitations"]))

    def test_invalid_unknown_sql_and_doctype_inputs(self):
        for content in (b"SQLite format 3\0rest", b"not XML", b"<Database/>", b"<Installation><Project/><Project/></Installation>", b'<!DOCTYPE Project [<!ENTITY x "expanded">]><Project>&x;</Project>', '<?xml version="1.0" encoding="utf-16"?><!DOCTYPE Project><Project/>'.encode("utf-16")):
            with self.subTest(content=content[:30]), self.assertRaises(ProjectError):
                ProjectDocument.from_bytes(content)

    def test_invalid_project_reports_and_cannot_save(self):
        document = ProjectDocument.from_bytes(b'<Project><Network><Address>300</Address></Network><Network><Address>254</Address></Network><Network><Address>254</Address></Network></Project>')
        self.assertEqual({i["code"] for i in document.validate()}, {"invalid-address", "duplicate-address"})
        with self.assertRaises(IntegrityError):
            document.save(self.root / "invalid.xml")
        self.assertFalse((self.root / "invalid.xml").exists())

    def test_atomic_failure_keeps_original_and_cleans_temporary(self):
        self.project.set_field("/", "Description", "change")
        with patch("cbus_toolkit.project.os.replace", side_effect=OSError("simulated replace failure")), self.assertRaises(OSError):
            self.project.save()
        self.assertEqual(self.path.read_bytes(), FIXTURE)
        self.assertEqual(list(self.root.iterdir()), [self.path])

    def test_write_preserves_permissions_and_refuses_symlinks(self):
        self.path.chmod(0o640)
        self.project.set_field("/", "Description", "change")
        self.project.save()
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o640)
        link = self.root / "link.xml"
        link.symlink_to(self.path)
        with self.assertRaises(ProjectError):
            self.project.save(link)

    def make_archive(self, *, multiple=False):
        path = self.root / "source.cbz"
        with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
            archive.comment = b"archive comment"
            info = ZipInfo("subdir/project.xml", date_time=(2020, 1, 2, 3, 4, 6))
            info.comment = b"XML comment"
            info.external_attr = 0o100640 << 16
            info.compress_type = ZIP_DEFLATED
            archive.writestr(info, FIXTURE)
            archive.writestr("opaque.bin", b"\x00\xffsecretless binary")
            archive.writestr("metadata.xml", b"<Metadata xmlns='urn:other'>keep</Metadata>")
            if multiple:
                archive.writestr("second.xml", FIXTURE)
        return path

    def test_exact_archive_roundtrip(self):
        path = self.make_archive()
        target = self.root / "saved.cbz"
        ProjectDocument.load(path).save(target)
        self.assertEqual(target.read_bytes(), path.read_bytes())

    def test_edited_archive_preserves_members_metadata_and_comment(self):
        path = self.make_archive()
        project = ProjectDocument.load(path)
        project.set_field("/", "Description", "archive edit")
        target = self.root / "edited.cbz"
        project.save(target)
        with ZipFile(path) as original, ZipFile(target) as edited:
            self.assertEqual(original.namelist(), edited.namelist())
            self.assertEqual(original.comment, edited.comment)
            for name in ("opaque.bin", "metadata.xml"):
                self.assertEqual(original.read(name), edited.read(name))
            for old, new in zip(original.infolist(), edited.infolist()):
                for attribute in ("comment", "external_attr", "compress_type", "date_time"):
                    self.assertEqual(getattr(old, attribute), getattr(new, attribute))
        self.assertEqual(ProjectDocument.load(target).metadata["Description"], "archive edit")

    def test_multi_project_archive_requires_selection_preserves_other_project(self):
        path = self.make_archive(multiple=True)
        with self.assertRaises(ProjectError):
            ProjectDocument.load(path)
        project = ProjectDocument.load(path, xml_member="second.xml")
        project.set_field("/", "Description", "second only")
        project.save()
        with ZipFile(path) as archive:
            self.assertEqual(archive.read("subdir/project.xml"), FIXTURE)
            self.assertIn(b"second only", archive.read("second.xml"))
        with self.assertRaises(UnsupportedProjectFormat):
            ProjectDocument.load(path, xml_member="missing.xml")

    def test_duplicate_archive_names_are_rejected(self):
        import warnings
        path = self.root / "duplicate.cbz"
        with warnings.catch_warnings(), ZipFile(path, "w") as archive:
            warnings.simplefilter("ignore", UserWarning)
            archive.writestr("project.xml", FIXTURE)
            archive.writestr("project.xml", FIXTURE)
        with self.assertRaises(ProjectError):
            ProjectDocument.load(path)

    def test_explicit_format_conversion_and_extension_does_not_silently_convert(self):
        archive = self.make_archive()
        document = ProjectDocument.load(archive)
        target = self.root / "export.xml"
        document.save(target, format="xml")
        self.assertEqual(target.read_bytes(), FIXTURE)
        document.save(self.root / "still-an-archive.xml")
        with ZipFile(self.root / "still-an-archive.xml") as zipped:
            self.assertIn("opaque.bin", zipped.namelist())
        with self.assertRaises(UnsupportedProjectFormat):
            document.save(target, format="sqlite")

    def test_unknown_scalar_and_foreign_entity_names_are_preserved(self):
        project = ProjectDocument.from_bytes(b'<Project xmlns:x="urn:foreign"><Address>1</Address><x:Address>foreign</x:Address><Config><Application>opaque</Application></Config><x:Network><x:Address>opaque</x:Address></x:Network></Project>')
        self.assertEqual(project.validate(), [])
        project.set_field("/", "Address", "2")
        self.assertEqual(project.get_field("/", "x:Address"), "foreign")
        self.assertEqual(project.inspect()["counts"]["network"], 0)
        self.assertIn("<Application>opaque</Application>", project.raw_xml())

    def test_namespace_scope_retained_when_moving_between_siblings(self):
        project = ProjectDocument.from_bytes(b'<Project><Network xmlns:x="urn:source"><Address>254</Address><Application><Address>56</Address><x:Extra>keep</x:Extra></Application></Network><Network><Address>253</Address></Network></Project>')
        project.move("/254/56", "/253")
        reparsed = minidom.parseString(project.to_xml_bytes())
        self.assertEqual(reparsed.getElementsByTagName("x:Extra")[0].namespaceURI, "urn:source")
        self.assertEqual(project.validate(), [])

    def test_internal_explicit_reference_protects_oid_edit_and_removal(self):
        self.project.set_field("/254/56/1", "ext:Reference", "group-1")
        with self.assertRaises(IntegrityError):
            self.project.set_field("/254/56/1", "@oid", "new")
        with self.assertRaises(IntegrityError):
            self.project.remove_field("/254/56/1", "@oid")

    def test_duplicate_field_validation_is_reported_without_crashing(self):
        project = ProjectDocument.from_bytes(b'<Project><Network><Address>254</Address><Address>253</Address></Network></Project>')
        self.assertIn("duplicate-field", {issue["code"] for issue in project.validate()})

    def test_exposed_dom_changes_are_not_silently_lost(self):
        self.project.project.setAttribute("custom", "edited directly")
        target = self.root / "direct.xml"
        self.project.save(target)
        self.assertIn(b'custom="edited directly"', target.read_bytes())

    def test_clone_rewrites_repeated_internal_reference_elements(self):
        project = ProjectDocument.from_bytes(b'<Project><Network oid="n"><Address>254</Address><Application oid="a"><Address>56</Address><Group oid="g"><Address>1</Address><Ref>g</Ref><Ref>g</Ref></Group></Application></Network></Project>')
        project.copy("/254/56/1", "/254/56", address=2)
        clone = project.resolve("/254/56/2")
        identifier = clone.getAttribute("oid")
        self.assertTrue(all(node.firstChild.data == identifier for node in clone.getElementsByTagName("Ref")))

    def test_archive_expansion_limit(self):
        path = self.make_archive()
        with patch("cbus_toolkit.project.MAX_DOCUMENT_BYTES", path.stat().st_size + 1), self.assertRaises(ProjectError):
            ProjectDocument.load(path)


if __name__ == "__main__":
    unittest.main()
