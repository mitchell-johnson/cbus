"""Wave 30 offline pins for percentage guards with zero prior refs.

P6 narrow slice of ``edlt_percentage`` guard messages and canonical
boundaries. Every pinned message had zero prior refs (verified via
``grep -rn`` across tests/ before writing: existing percentage tests use
only generic assertRaises or other messages, never these strings).
Pure offline: no hardware, vendor EXE, C-Gate server, or decoded spec.
"""
import pytest

from cbus_toolkit.edlt_percentage import byte_to_percentage, percentage_to_byte


def test_raw_byte_guard_pins_message():
    for bad in (257, -2, 2.5, 255.5, "0", None, True):
        with pytest.raises(
            ValueError, match="Raw byte must be an integer from 0 through 255"
        ):
            byte_to_percentage(bad)


def test_grammar_guard_pins_message():
    for bad in (
        "0001",
        "1.2.3",
        " 0",
        "0 ",
        "+0",
        "1e0",
        ".0",
        "0.",
        "00.00000000000000000000000000000",
    ):
        with pytest.raises(ValueError, match="ASCII fixed-point text"):
            percentage_to_byte(bad)


def test_range_guard_pins_message():
    for bad in ("100.1", "100.01", "200", "101"):
        with pytest.raises(ValueError, match="from 0 through 100"):
            percentage_to_byte(bad)


def test_canonical_boundaries_stay_pinned():
    assert byte_to_percentage(1) == "0.3921568627450980392156862745"
    assert byte_to_percentage(127) == "49.803921568627450980392156863"
    assert byte_to_percentage(254) == "99.60784313725490196078431373"
    assert percentage_to_byte("0.5") == 1
    assert percentage_to_byte("99.99") == 254
    assert percentage_to_byte("50.5") == 128
