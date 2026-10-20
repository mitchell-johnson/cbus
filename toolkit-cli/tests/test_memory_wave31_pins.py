"""Wave 31 offline pins for memory guards with zero prior refs.

Narrow slice of ``cbus_toolkit.memory`` guards. Every pinned behavior had
zero prior refs (verified via ``grep -rn`` across tests/ before writing:
no hits for ``logical_pp``, ``cbus-memory-patch-v1``, ``from_bytes`` with
``bytearray``/``memoryview``, tuple ``encode`` input, or whole-field text
``decode`` slices in test_memory.py). Pure offline: no hardware, vendor
specs, C-Gate server, or network.
"""
import pytest

from cbus_toolkit.memory import (
    MemoryCodec,
    MemoryImage,
    UnsupportedMemoryLayout,
)
from cbus_toolkit.unitspec import ParameterSpec, UnitSpec


def _parameter(name="Value", kind="int", **fields):
    values = {"Name": name, "Type": kind, "Address": "$10"}
    values.update({key: str(value) for key, value in fields.items()})
    return ParameterSpec(name, kind, "fixture.xml", values)


def _codec(*parameters, **kwargs):
    spec = UnitSpec("fixture.xml", {}, ("fixture.xml",), {p.name: p for p in parameters})
    return MemoryCodec(spec, **kwargs)


def test_from_bytes_accepts_bytearray_and_memoryview():
    expected = MemoryImage.from_bytes(b"\x01\x02\x03", start=16)
    from_array = MemoryImage.from_bytes(bytearray(b"\x01\x02\x03"), start=16)
    from_view = MemoryImage.from_bytes(memoryview(b"\x01\x02\x03"), start=16)
    assert from_array.read(16, 3) == b"\x01\x02\x03"
    assert from_view.read(16, 3) == b"\x01\x02\x03"
    assert dict(from_array.data) == dict(expected.data) == {16: 1, 17: 2, 18: 3}
    assert from_view.as_dict() == expected.as_dict()


def test_encode_accepts_tuple_like_list():
    c = _codec(_parameter(ArraySize=2, BitSize=8))
    from_tuple = c.encode("Value", (1, 2)).apply(MemoryImage({}))
    from_list = c.encode("Value", [1, 2]).apply(MemoryImage({}))
    assert dict(from_tuple.data) == dict(from_list.data) == {16: 1, 17: 2}
    assert c.decode("Value", from_tuple) == [1, 2]


def test_patch_and_layout_dict_envelopes_stay_pinned():
    c = _codec(_parameter(ArraySize=2, BitSize=8))
    patch = c.encode("Value", [1, 2])
    assert patch.as_dict() == {
        "format": "cbus-memory-patch-v1",
        "edits": [
            {"address": 16, "value": 1, "mask": 255},
            {"address": 17, "value": 2, "mask": 255},
        ],
    }
    layout = c.layout("Value").as_dict()
    assert layout["memory_space"] == "logical_pp"
    assert layout["name"] == "Value"
    assert layout["address"] == 16
    assert layout["end_address"] == 18


def test_text_decode_requires_whole_field():
    text = _codec(_parameter(kind="string", ArraySize=8))
    image = text.encode("Value", "hi").apply(MemoryImage({}))
    assert text.decode("Value", image) == "hi"
    with pytest.raises(UnsupportedMemoryLayout):
        text.decode("Value", image, index=1)
    with pytest.raises(UnsupportedMemoryLayout):
        text.decode("Value", image, index=0, count=7)
    sixbit = _codec(_parameter(kind="sixbit", ArraySize=8))
    packed = sixbit.encode("Value", "AB").apply(MemoryImage({}))
    assert sixbit.decode("Value", packed) == "AB      "
    with pytest.raises(UnsupportedMemoryLayout):
        sixbit.decode("Value", packed, index=1)
