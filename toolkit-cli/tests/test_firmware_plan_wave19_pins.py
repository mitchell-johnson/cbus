"""Wave19 offline pins for firmware update plan guards (P10).

Narrow scope: only ``cbus_toolkit.firmware_update_plan``. No hardware,
network, broker, vendor archives, or passwords. Synthetic ZIP metadata only.
Pins plan guards with zero prior test refs (verified 2026-10-16 via
``grep -rn`` over ``tests/``):

* ``FONT_DATA1_VERSIONS`` exact tuple and ``VARIANT_HARDWARE`` mapping
* ``MAIN_ADDRESS_TEXT`` mapping and ``plan['main_address']`` field
* ``MODE_SWITCH_FAILURE`` template and ``plan['dfuprog_program']`` literal
* ``plan['selected_font_entry']`` and ``_check_inspection_binding`` refusals
"""

from __future__ import annotations

import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

from cbus_toolkit import firmware_update_plan as api


def write_package(directory, filename, entries):
    path = Path(directory) / filename
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as archive:
        for name, data in entries:
            archive.writestr(name, data)
    return path


class FirmwarePlanWave19PinsTests(unittest.TestCase):
    def test_wave19_font_versions_and_variant_hardware_tables(self):
        self.assertEqual(
            api.FONT_DATA1_VERSIONS,
            ("1.0.0", "1.1.0", "1.2.0", "1.3.0", "1.4.0", "1.5.0", "1.6.0", "1.7.0"),
        )
        self.assertEqual(
            api.VARIANT_HARDWARE,
            {
                "StellarisPCI": "1.0 (Stellaris + PCI)",
                "TivaPCI": "2.0 (Tiva + PCI)",
                "TivaNCC": "3.0 (Tiva + NCC)",
            },
        )
        with TemporaryDirectory() as directory:
            listed = write_package(
                directory,
                "eDLTFirmware_1.7.0.zip",
                [("edlt_main_hwv1_x.bin", b"\0" * 64), ("edlt_fontdata_x.bin", b"\1" * 64)],
            )
            plan = api.update_plan(listed, variant="StellarisPCI")
            self.assertTrue(plan["supported"], plan["issues"])
            self.assertTrue(plan["font_install"]["package_version_in_font_data1_versions"])
            self.assertEqual(
                plan["font_install"]["font_data1_versions"], list(api.FONT_DATA1_VERSIONS)
            )
            unlisted_dir = Path(directory) / "unlisted"
            unlisted_dir.mkdir()
            # Same entry shapes under an unlisted filename version install the font.
            unlisted = write_package(
                unlisted_dir,
                "eDLTFirmware_1.8.0.zip",
                [("edlt_main_hwv1_x.bin", b"\0" * 64), ("edlt_fontdata_x.bin", b"\1" * 64)],
            )
            plan2 = api.update_plan(unlisted, variant="StellarisPCI")
            self.assertTrue(plan2["supported"], plan2["issues"])
            self.assertFalse(plan2["font_install"]["package_version_in_font_data1_versions"])

    def test_wave19_main_address_text_and_plan_main_address(self):
        self.assertEqual(
            api.MAIN_ADDRESS_TEXT,
            {"StellarisPCI": "0x2000", "TivaPCI": "0x4000", "TivaNCC": "0x4000"},
        )
        mains = {
            "StellarisPCI": "edlt_main_hwv1_x.bin",
            "TivaPCI": "edlt_main_hwv2_x.bin",
            "TivaNCC": "edlt_main_hwv3_x.bin",
        }
        with TemporaryDirectory() as directory:
            for variant, main in mains.items():
                folder = Path(directory) / variant
                folder.mkdir()
                package = write_package(
                    folder,
                    "eDLTFirmware_1.8.0.zip",
                    [(main, b"\0" * 64), ("edlt_fontdata_x.bin", b"\1" * 64)],
                )
                plan = api.update_plan(package, variant=variant)
                self.assertTrue(plan["supported"], (variant, plan["issues"]))
                self.assertEqual(plan["main_address"], api.MAIN_ADDRESS_TEXT[variant])
                self.assertEqual(plan["dfuprog_steps"][-1]["argv"][2], plan["main_address"])
                self.assertEqual(plan["selected_main_entry"], main)

    def test_wave19_mode_switch_failure_and_dfuprog_program(self):
        self.assertEqual(
            api.MODE_SWITCH_FAILURE,
            "Unable to prepare unit for firmware upgrade (exit code {exit_code}).",
        )
        with TemporaryDirectory() as directory:
            package = write_package(
                directory,
                "eDLTFirmware_1.8.0.zip",
                [("edlt_main_hwv1_x.bin", b"\0" * 64), ("edlt_fontdata_x.bin", b"\1" * 64)],
            )
            plan = api.update_plan(package, variant="StellarisPCI")
            self.assertTrue(plan["supported"], plan["issues"])
            self.assertEqual(
                plan["dfuprog_program"],
                "Firmware\\eDLTFirmware\\dfuprog.exe under the updater directory",
            )
            switches = [s for s in plan["dfuprog_steps"] if s["step"] == "mode-switch"]
            self.assertTrue(switches)
            for step in switches:
                self.assertEqual(step["argv"], ["-m"])
                self.assertEqual(step["native_arguments"], "-m")
                self.assertEqual(step["failure_message"], api.MODE_SWITCH_FAILURE)
                self.assertEqual(
                    step["failure_message"].format(exit_code=3),
                    "Unable to prepare unit for firmware upgrade (exit code 3).",
                )

    def test_wave19_selected_font_entry_and_inspection_binding(self):
        with TemporaryDirectory() as directory:
            package = write_package(
                directory,
                "eDLTFirmware_1.8.0.zip",
                [("edlt_main_hwv1_x.bin", b"\0" * 64), ("edlt_fontdata_x.bin", b"\1" * 64)],
            )
            plan = api.update_plan(package, variant="StellarisPCI")
            self.assertTrue(plan["supported"], plan["issues"])
            self.assertEqual(plan["selected_font_entry"], "edlt_fontdata_x.bin")

            def inspection_for(target_plan):
                return {
                    "format": "cbus-edlt-firmware-package-images-v1",
                    "name": target_plan["package"]["name"],
                    "sha256": target_plan["package"]["sha256"],
                    "version": target_plan["package"]["version"],
                    "images": [
                        {"name": e["name"], "bytes": e["bytes"], "sha256": "0" * 64}
                        for e in target_plan["package"]["entries"]
                    ],
                }

            wrong_digest = inspection_for(plan)
            wrong_digest["sha256"] = "f" * 64
            with self.assertRaisesRegex(api.FirmwarePackageError, "does not bind"):
                api.attach_image_inspection(dict(plan), wrong_digest)
            missing_entry = inspection_for(plan)
            missing_entry["images"] = missing_entry["images"][:-1]
            with self.assertRaisesRegex(api.FirmwarePackageError, "does not cover"):
                api.attach_image_inspection(dict(plan), missing_entry)


if __name__ == "__main__":
    unittest.main()
