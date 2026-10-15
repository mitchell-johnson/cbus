"""Wave 12 narrow offline pins for P5.07 (issue #44).

Each test pins ONE pure-offline branch in wireless_connection.py or
wireless_unit_globals.py with plain values only: no hardware, vendor EXE,
C-Gate server, PP session, or decoded vendor spec. Complements
test_wireless_connection.py / test_wireless_unit_globals.py (fixtures,
topology XML, native acceptance) with the adjacent unpinned details:
exact route-byte vectors, N-vs-F field ownership, house-code extremes,
spec filenames, and full refusal strings. #44 stays OPEN; radio
learn/join/house-code transfer and physical forwarding remain untouched.
"""
from __future__ import annotations

import unittest

from cbus_toolkit.wireless_connection import (
    FIELDS as CONNECTION_FIELDS,
)
from cbus_toolkit.wireless_connection import (
    OWNED as CONNECTION_OWNED,
)
from cbus_toolkit.wireless_connection import (
    check_profile as connection_check_profile,
)
from cbus_toolkit.wireless_connection import (
    encode_route,
)
from cbus_toolkit.wireless_connection import (
    fields_for as connection_fields_for,
)
from cbus_toolkit.wireless_connection import (
    WirelessConnectionError,
)
from cbus_toolkit.wireless_unit_globals import (
    check_profile as globals_check_profile,
)
from cbus_toolkit.wireless_unit_globals import (
    house_code_bytes,
    house_code_text,
    profile_refusal,
    spec_filename,
)
from cbus_toolkit.wireless_unit_globals import (
    WirelessGlobalsError,
)


class ConnectionEncodeRouteWave12Tests(unittest.TestCase):
    """encode_route: header byte, sentinels, and the six-hop refusal."""

    def test_empty_single_and_five_hop_vectors_and_six_hop_refusal(self):
        # Next: FrozenTopology.routes(); no XML/session here.
        self.assertEqual(encode_route(()), (255,) * 7)
        self.assertEqual(encode_route((80,)), (18, 80, 255, 255, 255, 255, 255))
        self.assertEqual(
            encode_route((190, 180, 170, 160, 150)),
            (54, 190, 180, 170, 160, 150, 255),
        )
        with self.assertRaisesRegex(
            WirelessConnectionError, "at most five are admitted"
        ):
            encode_route((190, 180, 170, 160, 150, 140))


class ConnectionProfileWave12Tests(unittest.TestCase):
    """check_profile boundaries with the full message; N owns a subset of F."""

    def test_boundaries_admitted_and_n_owns_subset_of_f(self):
        # Next: topology.selected() identity binding; no PP/save here.
        self.assertEqual(
            connection_check_profile("WGATE5N", "2.2.90"), ("WGATE5N", "2.2.90", None)
        )
        self.assertEqual(
            connection_check_profile("WGATE5F", "2.4.99", "2642"),
            ("WGATE5F", "2.4.99", "2642"),
        )
        with self.assertRaisesRegex(
            WirelessConnectionError,
            r"Only WGATE5N/F Connection profiles at firmware 2\.2\.90\.\.2\.4\.99 are admitted",
        ):
            connection_check_profile("WGATE5F", "2.2.89")
        with self.assertRaisesRegex(
            WirelessConnectionError,
            r"Only WGATE5N/F Connection profiles at firmware 2\.2\.90\.\.2\.4\.99 are admitted",
        ):
            connection_check_profile("BRIDGE2N", "2.4.00")
        self.assertEqual(
            connection_fields_for("WGATE5F"), tuple(CONNECTION_FIELDS)
        )
        self.assertEqual(
            connection_fields_for("WGATE5N"), tuple(CONNECTION_OWNED)
        )
        self.assertTrue(set(connection_fields_for("WGATE5N")) < set(connection_fields_for("WGATE5F")))
        self.assertIn("MapWirelessRemotes", connection_fields_for("WGATE5F"))
        self.assertNotIn("MapWirelessRemotes", connection_fields_for("WGATE5N"))


class GlobalsHouseCodeWave12Tests(unittest.TestCase):
    """House-code extremes roundtrip; spec filename is <type>_2.xml."""

    def test_extreme_vectors_and_spec_filename(self):
        # Next: WirelessGlobalsEditor plan/show; no spec fixture here.
        self.assertEqual(house_code_text((0, 0, 0, 0)), "00000000")
        self.assertEqual(house_code_text((255, 255, 255, 255)), "ffffffff")
        self.assertEqual(house_code_bytes("00000000"), (0, 0, 0, 0))
        self.assertEqual(house_code_bytes("FFFFFFFF"), (255, 255, 255, 255))
        self.assertEqual(
            house_code_bytes(house_code_text((0x01, 0xEF, 0xCD, 0xAB))),
            (0x01, 0xEF, 0xCD, 0xAB),
        )
        self.assertEqual(spec_filename("WRM4D1"), "WRM4D1_2.xml")
        self.assertEqual(spec_filename("WRM8R2"), "WRM8R2_2.xml")


class GlobalsProfileWave12Tests(unittest.TestCase):
    """Full WRM refusal strings; identity triple preserves the catalogue."""

    def test_full_refusals_and_identity_passthrough(self):
        # Next: WRM editor plan/apply; no PP/save here.
        self.assertEqual(
            profile_refusal("WRM2D1EZ", "2.4.00"),
            "WRM2D1EZ is a TnmWRDX EZ unit with a different Toolkit class and specification",
        )
        self.assertEqual(
            profile_refusal("WRM2D1", "1.11.0"),
            "WRM2D1 firmware outside 2.0.0..2.4.99 uses another Toolkit class or specification",
        )
        self.assertEqual(
            profile_refusal("WRB2D1", "2.4.00"),
            "Only WRM2/4/8 D/R Neo retrofit wireless units use this workflow",
        )
        self.assertIsNone(profile_refusal("WRM4D1", "2.4.00"))
        self.assertEqual(
            globals_check_profile("WRM4D1", "2.4.00", "5854D2L1AA"),
            ("WRM4D1", "2.4.00", "5854D2L1AA"),
        )
        with self.assertRaisesRegex(
            WirelessGlobalsError,
            r"Unit identity must be an admitted WRM unit at firmware 2\.0\.0\.\.2\.4\.99: "
            r"Only WRM2/4/8 D/R Neo retrofit wireless units use this workflow",
        ):
            globals_check_profile("WRB2D1", "2.4.00")


if __name__ == "__main__":
    unittest.main()
