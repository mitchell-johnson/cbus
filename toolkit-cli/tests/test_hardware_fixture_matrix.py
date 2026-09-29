"""P1.04 hardware fixture matrix: sanitized, deterministic and complete."""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from hashlib import sha256
import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from research import build_hardware_fixture_matrix as matrix_builder


PREAMBLE = "(C) CLIPSAL INTEGRATED SYSTEMS 2003 all rights reserved\n"


def spec(unit_type: str, params: str = "", includes: tuple[str, ...] = ()) -> str:
    include_block = (
        "<Includes>"
        + "".join(f"<Include>{name}</Include>" for name in includes)
        + "</Includes>"
        if includes
        else ""
    )
    return (
        PREAMBLE
        + '<?xml version="1.0" encoding="UTF-8" ?>\n'
        + f"<UnitSpecification><Type>{unit_type}</Type><MinVersion>1.0</MinVersion>"
        + f"<MaxVersion>9</MaxVersion>{include_block}<Parameters>{params}</Parameters>"
        + "</UnitSpecification>\n"
    )


def param(name: str, address: str, method: str | None, protection: str) -> str:
    method_field = f"<ProgramMethod>{method}</ProgramMethod>" if method else ""
    return (
        f"<Param><Name>{name}</Name><Type>int</Type>{method_field}"
        f"<Address>{address}</Address><Protection>{protection}</Protection></Param>"
    )


def unit(title: str, number: str, alternatives: str, revisions: list[tuple[str, str, str, str, str]]) -> str:
    rows = "".join(
        f"<Revision><UnitType>{unit_type}</UnitType><MinVersion>{low}</MinVersion>"
        f"<MaxVersion>{high}</MaxVersion><UnitSpecName>{name}</UnitSpecName>"
        f"<ClassName>{class_name}</ClassName></Revision>"
        for unit_type, low, high, name, class_name in revisions
    )
    return (
        f"<Unit><UnitTitle>{title}</UnitTitle><Description>fixture</Description>"
        f"<CatalogNumber>{number}</CatalogNumber>"
        f"<AlternativeCatalogNumbers>{alternatives}</AlternativeCatalogNumbers>"
        f"<FirmwareRevisions>{rows}</FirmwareRevisions></Unit>"
    )


def write_inputs(root: Path) -> tuple[Path, Path]:
    specs = root / "specs"
    specs.mkdir()
    files = {
        "DIMX.xml": spec("DIMX", param("UnitAddress", "$20", None, "factory") + param("Level", "$21", "direct", "checksum")),
        "I_BASE.xml": spec("XXXXXXXX", param("Base", "$22", "paged", "lock")),
        "KEYX.xml": spec("KEYX", param("Key", "$30", "paged", "none"), ("I_BASE.xml",)),
        "KEYX_A.xml": spec("KEYY", param("Key", "$30", "paged", "none"), ("I_BASE.xml",)),
        "THERMO_TEMPLATE01.xml": spec("THERMO"),
        "ConvertTable.xml": '<?xml version="1.0"?><UnitConversions/>\n',
    }
    for name, content in files.items():
        (specs / name).write_text(content, encoding="utf-8")
    catalogue = root / "cbusunits.xml"
    catalogue.write_text(
        '<?xml version="1.0"?><CBusUnits><Units>'
        + unit(
            "Family=Wired;Category=Output Units - Dimmers", "5504D", "L5504D;E5504D",
            [("DIMX", "1.0", "1.9", "DIMX.xml", "CBusDimmerUnit"),
             ("DIMX", "2.0", "9", "DIMX.xml", "CBusDimmerUnit")],
        )
        + unit(
            "Family=Wired;Category=Input Units - Saturn", "5052", "",
            [("KEYX", "1.2.0", "1.4.99", "KEYX.xml", "CBusNeoInputUnit")],
        )
        + "</Units></CBusUnits>\n",
        encoding="utf-8",
    )
    return specs, catalogue


def run_main(*args: str) -> tuple[int, str]:
    stdout, stderr = io.StringIO(), io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        code = matrix_builder.main(list(args))
    return code, stdout.getvalue() + stderr.getvalue()


class SyntheticMatrixTests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.specs, self.catalogue = write_inputs(self.root)

    def test_regeneration_is_deterministic_and_sanitized(self):
        first = matrix_builder.render(matrix_builder.build(self.specs, self.catalogue))
        second = matrix_builder.render(matrix_builder.build(self.specs, self.catalogue))
        self.assertEqual(first, second)
        matrix = json.loads(first)
        rows = matrix_builder.validate_matrix(matrix)
        roles = {row["filename"]: row["role"] for row in matrix["inputs"]["unit_specs"]}
        self.assertEqual(
            roles,
            {
                "ConvertTable.xml": "non_unit_specification",
                "DIMX.xml": "catalogued_device",
                "I_BASE.xml": "include_only",
                "KEYX.xml": "catalogued_device",
                "KEYX_A.xml": "uncatalogued_device_variant",
                "THERMO_TEMPLATE01.xml": "template",
            },
        )
        dimmer = rows["fixture:unit:DIMX"]
        self.assertEqual(dimmer["family"], "dimmer")
        self.assertEqual(dimmer["catalogue"]["numbers"], ["5504D", "E5504D", "L5504D"])
        self.assertEqual(dimmer["firmware"]["major_versions"], ["1", "2"])
        self.assertEqual(dimmer["programming"]["methods"], ["direct"])
        self.assertEqual(dimmer["programming"]["protection_classes"], ["checksum", "factory"])
        self.assertEqual(
            dimmer["input_digest"]["spec_sha256"],
            sha256((self.specs / "DIMX.xml").read_bytes()).hexdigest(),
        )
        self.assertIn("output_effect", dimmer["required_observables"])
        variant = rows["fixture:unit:KEYX_A"]
        self.assertEqual(variant["family"], "key_input")
        self.assertEqual(variant["catalogue"]["status"], "not_selected_by_catalogue")
        self.assertEqual(
            set(variant["input_digest"]["include_sha256"]), {"I_BASE.xml"}
        )
        self.assertEqual(
            rows["fixture:programming:paged"]["candidate_fixture_ids"],
            ["fixture:unit:KEYX", "fixture:unit:KEYX_A"],
        )
        self.assertTrue(all(row["status"] == "unavailable" for row in rows.values()))
        self.assertTrue(all(row["private_manifest_ref"] is None for row in rows.values()))
        for leaked in ("UnitAddress", "<Param", "Protection>", "fixture</Description>"):
            self.assertNotIn(leaked, first)

    def test_check_mode_detects_tampering_and_absent_inputs(self):
        output = self.root / "matrix.json"
        common = ("--unitspec-dir", str(self.specs), "--catalogue", str(self.catalogue), "--output", str(output))
        self.assertEqual(run_main(*common)[0], 0)
        self.assertEqual(run_main("--check", *common)[0], 0)
        self.assertEqual(run_main("--verify", "--output", str(output))[0], 0)

        tampered = json.loads(output.read_text(encoding="utf-8"))
        tampered["fixtures"][0]["status"] = "provisioned"
        output.write_text(matrix_builder.render(tampered), encoding="utf-8")
        code, message = run_main("--check", *common)
        self.assertEqual(code, 1)
        self.assertIn("stale hardware fixture matrix", message)
        with self.assertRaisesRegex(ValueError, "digest changed"):
            run_main("--verify", "--output", str(output))

        (self.specs / "DIMX.xml").write_text(
            spec("DIMX", param("Level", "$21", "direct", "lock")), encoding="utf-8"
        )
        self.assertEqual(run_main(*common)[0], 0)
        (self.specs / "DIMX.xml").write_text(
            spec("DIMX", param("Level", "$21", "direct", "checksum")), encoding="utf-8"
        )
        self.assertEqual(run_main("--check", *common)[0], 1)

        code, message = run_main(
            "--check", "--unitspec-dir", str(self.root / "absent"),
            "--catalogue", str(self.catalogue), "--output", str(output),
        )
        self.assertEqual(code, 2)
        self.assertIn("inputs are unavailable", message)

    def test_validator_rejects_invalid_rows_even_when_resigned(self):
        base = matrix_builder.build(self.specs, self.catalogue)

        def resigned(mutate):
            changed = json.loads(json.dumps(base))
            mutate(changed)
            changed.pop("matrix_sha256")
            changed["counts"] = matrix_builder._counts(
                changed["fixtures"], changed["inputs"]["unit_specs"]
            )
            changed["matrix_sha256"] = matrix_builder.canonical_digest(changed)
            return changed

        first = lambda matrix: matrix["fixtures"][0]
        cases = [
            (lambda m: m["fixtures"].append(dict(first(m))), "Duplicate fixture id"),
            (lambda m: first(m).update(status="provisioned"), "without a private manifest"),
            (lambda m: first(m).update(private_manifest_ref="private-manifest:sha256:" + "0" * 64), "unavailable but names"),
            (lambda m: first(m).update(required_observables=["telepathy"]), "known observables"),
            (lambda m: first(m).update(work_items=[{"id": "P3.01", "issue": 28}]), "including P1.04"),
            (lambda m: m.update(fixtures=[row for row in m["fixtures"] if row["family"] != "usb_bootloader"]), "required families"),
            (lambda m: m.update(fixtures=[row for row in m["fixtures"] if row["id"] != "fixture:topology:bridges-6"]), "one to six bridge"),
            (lambda m: m.update(fixtures=[row for row in m["fixtures"] if row["id"] != "fixture:unit:DIMX"]), "unknown candidate|differ from device spec"),
            (lambda m: next(row for row in m["fixtures"] if row["id"] == "fixture:unit:DIMX")["input_digest"].update(spec_sha256="0" * 64), "unit spec digest"),
        ]
        for mutate, expected in cases:
            with self.subTest(expected=expected):
                with self.assertRaisesRegex(ValueError, expected):
                    matrix_builder.validate_matrix(resigned(mutate))
        provisioned = resigned(
            lambda m: first(m).update(
                status="provisioned",
                private_manifest_ref="private-manifest:sha256:" + "a" * 64,
            )
        )
        self.assertIn(first(provisioned)["id"], matrix_builder.validate_matrix(provisioned))


class CommittedMatrixTests(unittest.TestCase):
    def setUp(self):
        self.matrix, self.raw = matrix_builder.load_committed()

    def test_committed_matrix_is_valid_complete_and_unavailable(self):
        rows = matrix_builder.validate_matrix(self.matrix)
        self.assertEqual(len(rows), len(self.matrix["fixtures"]))
        self.assertEqual(self.matrix["inputs"]["unit_spec_count"], 280)
        self.assertEqual(sum(self.matrix["counts"]["unit_specs_by_role"].values()), 280)
        families = {row["family"] for row in rows.values()}
        for family in matrix_builder.REQUIRED_ASSEMBLY_FAMILIES:
            with self.subTest(family=family):
                self.assertIn(family, families)
        for family in ("relay", "dimmer", "key_input", "sensor", "thermostat",
                       "dali_gateway", "wireless_device", "bridge", "pc_interface",
                       "edlt_display", "dlt_display", "programming_method"):
            with self.subTest(family=family):
                self.assertIn(family, families)
        self.assertEqual(
            {row["bridge_count"] for row in rows.values() if row["family"] == "bridge_topology"},
            set(range(1, 7)),
        )
        self.assertEqual(self.matrix["counts"]["by_status"], {"unavailable": len(rows)})
        self.assertTrue(all(row["private_manifest_ref"] is None for row in rows.values()))
        text = self.raw.decode("utf-8")
        for leaked in ("<Param", "DefaultValue", "SpecAuthor", "<Description>"):
            self.assertNotIn(leaked, text)

    def test_committed_matrix_regenerates_from_private_inputs(self):
        spec_dir, catalogue = matrix_builder.default_inputs()
        if spec_dir is None or catalogue is None or not spec_dir.is_dir() or not catalogue.is_file():
            self.skipTest(
                "requires CBUS_UNITSPEC_DIR and CBUS_LOCAL_CGATE_VENDOR private inputs"
            )
        self.assertEqual(
            matrix_builder.render(matrix_builder.build(spec_dir, catalogue)),
            self.raw.decode("utf-8"),
        )


if __name__ == "__main__":
    unittest.main()
