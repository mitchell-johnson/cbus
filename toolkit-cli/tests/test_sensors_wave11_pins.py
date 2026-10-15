"""P5 wave-11 narrow offline pin for #41 (sensor dialogs).

One narrow slice: full-message pins for the pure-offline profile gates in
``pir_sensors.profile`` / ``check_profile`` and
``light_level_sensors.profile_refusal`` / ``check_profile`` / 
``validate_on_off_controls``. Every asserted full string was verified to
have zero prior refs via ``grep -rl`` across tests/*.py (only shorter
substrings such as "Only SENPIROA", "Only SENLL", "catalogue", "TSENLLA",
"boolean" or generic assertRaises appear elsewhere).

Pure-offline only: plain values, no spec fixture, PP session, hardware,
vendor EXE, C-Gate server, or decoded vendor spec. #41 stays OPEN;
SENLLA/SENPILLA/SENPIRIC and older classes (explicitly refused here),
calibration/IR/corridor/join/maintenance/macro/output interactions, the
original GUI run and physical acceptance remain future work. Next: original
class evidence, then new modules mirroring pir_sensors.py.
"""
from __future__ import annotations

import unittest

from cbus_toolkit.light_level_sensors import (
    check_profile as ll_check_profile,
)
from cbus_toolkit.light_level_sensors import (
    profile_refusal as ll_refusal,
)
from cbus_toolkit.light_level_sensors import (
    validate_on_off_controls,
)
from cbus_toolkit.pir_sensors import check_profile as pir_check_profile
from cbus_toolkit.pir_sensors import profile as pir_profile
from cbus_toolkit.sensors import SensorError


class PirProfileFullMessageWave11Tests(unittest.TestCase):
    """pir_sensors.profile/check_profile: full refusal strings and band edges."""

    def test_redirect_unknown_firmware_gap_and_catalogue_pins(self):
        # Next: SENLLA/SENPILLA/SENPIRIC classes; no PP/save here.
        self.assertEqual(
            pir_profile("SENPILL", "2.3.00", "5753PEIRL"),
            ("SENPILL uses the Toolkit multisensor class; use cbus_toolkit.sensors", None),
        )
        self.assertEqual(
            pir_profile("NOPE", "2.3.00", "x"),
            ("Only SENPIROA, SENPIRIA and SENPIRIB ST7 PIR sensors use this workflow", None),
        )
        self.assertEqual(
            pir_profile("SENPIRIB", "2.3.10", "5753L"),
            ("SENPIRIB firmware 2.3.10 has no admitted Toolkit ST7 PIR class and catalogue "
             "specification (SENPIRIB 2.3.10..2.3.99 is unregistered; "
             "SENPIRIB 2.4 uses SENPIRIC)", None),
        )
        self.assertEqual(
            pir_profile("SENPIRIA", "2.3.00", "BAD"),
            ("SENPIRIA catalogue number must be one of 5751L, SLC5751L,WE",
             "SENPIRIA_ST7.xml"),
        )
        with self.assertRaisesRegex(
            SensorError,
            r"Unit identity must be an admitted ST7 PIR sensor: Only SENPIROA",
        ):
            pir_check_profile("NOPE", "2.3.00", "x")
        self.assertEqual(
            pir_check_profile("SENPIROA", "2.4.00", "5750WPL"),
            (("SENPIROA", "2.4.00", "5750WPL"), "SENPIROA_ST7_2.xml"),
        )

    def test_band_edges_admit_239_and_24_but_refuse_gap(self):
        # Next: same class-evidence boundary; SENPIRIB 2.4 uses SENPIRIC.
        self.assertEqual(pir_profile("SENPIRIB", "2.3.9", "5753L"), (None, "SENPIRIB_ST7.xml"))
        self.assertEqual(pir_profile("SENPIROA", "2.0.01", "5750WPL"), (None, "SENPIROA_ST7.xml"))
        self.assertEqual(pir_profile("SENPIROA", "2.4.00", "5750WPL"), (None, "SENPIROA_ST7_2.xml"))
        reason, _spec = pir_profile("SENPIRIB", "2.4.00", "5753L")
        self.assertIn("SENPIRIB 2.4 uses SENPIRIC", reason)


class SenllProfileFullMessageWave11Tests(unittest.TestCase):
    """light_level_sensors.profile_refusal/check_profile: full strings."""

    def test_surface_redirect_unknown_firmware_and_catalogue_pins(self):
        # Next: SENLLA/SENPILLA/SENPIRIC class evidence; no PP/save here.
        self.assertEqual(
            ll_refusal("SENLLA", "2.4.00", "5754PE"),
            "SENLLA uses the Toolkit surface-mount class TSENLLA and the SENLLA layout",
        )
        self.assertEqual(
            ll_refusal("SENPILL", "2.3.00", "5753PEIRL"),
            "Only SENLL ST7 light-level sensors use this workflow",
        )
        self.assertEqual(
            ll_refusal("SENLL", "2.5.00", "5031PE"),
            "SENLL firmware 2.5.00 has no Toolkit TST7SENLL class and SENLL_ST7 catalogue "
            "band (SENLL 1.x uses TSENLL and SENLL.xml)",
        )
        self.assertEqual(
            ll_refusal("SENLL", "2.3.00", "BAD"),
            "SENLL catalogue number must be one of 5031PE, 5031PEWP, SLC5031PE, SLC5031PEWP,GY",
        )
        self.assertIsNone(ll_refusal("SENLL", "2.4.99", "5031PE"))
        self.assertEqual(
            ll_check_profile("SENLL", "2.3.00", "5031PE"), ("SENLL", "2.3.00", "5031PE")
        )
        with self.assertRaisesRegex(
            SensorError,
            "must be an admitted ST7 SENLL light-level sensor: SENLL firmware 2.5.00",
        ):
            ll_check_profile("SENLL", "2.5.00", "5031PE")


class SenllOnOffControlShapeWave11Tests(unittest.TestCase):
    """light_level_sensors.validate_on_off_controls: shape/field/app guards."""

    def test_shape_field_and_application_full_messages(self):
        # Next: creation/decline decisions for unestablished destinations.
        for bad in (None, 0, "primary", [], (), [{"application": "primary"}] * 65):
            with self.subTest(bad=bad), self.assertRaisesRegex(
                SensorError,
                r"on_off_controls must contain 1\.\.64 application/group operations",
            ):
                validate_on_off_controls(bad)
        for bad in (
            [{"application": "primary", "group": 20}],
            [{"cache": {}}],
            ["x"],
            [{}],
        ):
            with self.subTest(bad=bad), self.assertRaisesRegex(
                SensorError,
                "Each on/off control accepts exactly one application or group field",
            ):
                validate_on_off_controls(bad)
        for bad in ([{"application": "bogus"}], [{"application": True}], [{"application": 5}]):
            with self.subTest(bad=bad), self.assertRaisesRegex(
                SensorError,
                "On/off control application must be primary or secondary",
            ):
                validate_on_off_controls(bad)
        with self.assertRaisesRegex(
            SensorError, "On/off control group must be an integer in 0..255"
        ):
            validate_on_off_controls([{"group": 256}])
        with self.assertRaisesRegex(
            SensorError, "On/off control group must be an integer in 0..255"
        ):
            validate_on_off_controls([{"group": None}])

    def test_happy_path_normalizes_order_and_group_bounds(self):
        # Next: same destination-decision boundary; forced save stays open.
        self.assertEqual(
            validate_on_off_controls([{"application": "primary"}, {"group": 20}]),
            [{"application": "primary"}, {"group": 20}],
        )
        self.assertEqual(
            validate_on_off_controls(({"group": 255},)), [{"group": 255}]
        )
        self.assertEqual(
            validate_on_off_controls([{"application": "secondary"}]),
            [{"application": "secondary"}],
        )


if __name__ == "__main__":
    unittest.main()
