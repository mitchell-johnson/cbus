"""Wave-18 offline pins for DALI extended-proxy guards (P7.01 #51).

Narrow scope: guard semantics in cbus_toolkit.dali_extended_proxy only,
with in-memory models (no sockets, hardware, or C-Gate I/O). Each pinned
guard phrase has zero prior references in tests/.
"""

import pytest

from cbus_toolkit import dali_extended_proxy as proxy


def _model(targets=None, values=None):
    return {"extParams": {"targetValues": dict(targets or {}),
                          "values": dict(values or {})}}


def test_wave18_options_bit_gate_excludes_554_555():
    assert proxy.byte_excluded(_model(values={"521": 0}), 554) is False
    assert proxy.byte_excluded(_model(values={"521": 0}), 555) is False
    assert proxy.byte_excluded(_model(values={"521": 1}), 554) is True
    assert proxy.byte_excluded(_model(values={"521": 1}), 555) is False
    assert proxy.byte_excluded(_model(values={"521": 2}), 554) is False
    assert proxy.byte_excluded(_model(values={"521": 2}), 555) is True
    staged = _model(targets={"521": 3}, values={"521": 0})
    assert proxy.byte_excluded(staged, 554) is True
    assert proxy.byte_excluded(staged, 555) is True


def test_wave18_error_reporting_mode_byte_gate_needs_group_and_store_bit():
    assert proxy.byte_excluded(
        _model(values={"632": 0, "521": 4}), 636) is True
    assert proxy.byte_excluded(
        _model(values={"632": 255, "521": 4}), 636) is False
    assert proxy.byte_excluded(
        _model(values={"632": 0, "521": 0}), 636) is False
    assert proxy.byte_excluded(
        _model(values={"632": 0, "521": 3}), 636) is False


def test_wave18_restore_level_bytes_follow_indexed_logic_group_bit():
    assert proxy.byte_excluded(_model(values={"523": 4}), 616) is True
    assert proxy.byte_excluded(_model(values={"523": 0}), 616) is False
    assert proxy.byte_excluded(_model(values={"523": 3}), 616) is False
    model = _model(values={"523": 0, "553": 4})
    assert proxy.byte_excluded(model, 616) is False
    assert proxy.byte_excluded(model, 631) is True
    assert proxy.byte_excluded(_model(values={"553": 0}), 631) is False


def test_wave18_staged_scene_bytes_and_far_reserved_ranges():
    assert proxy.byte_excluded(_model(targets={"7424": 0}), 7424) is False
    assert proxy.byte_excluded(_model(targets={"7424": 5}), 7424) is True
    assert proxy.byte_excluded(_model(), 7424) is True
    assert proxy.byte_excluded(_model(), 7936) is False
    for address in (600, 612, 647, 7000, 8700, 9000):
        assert proxy.static_excluded(address) is True, address
        assert proxy.byte_excluded(_model(), address) is True, address
    for address in (591, 608, 611, 614, 648, 7040, 8800):
        assert proxy.static_excluded(address) is False, address
