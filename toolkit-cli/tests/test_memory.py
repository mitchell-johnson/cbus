"""Fixed-vector codec tests plus explicit opt-in native PP acceptance.

Native tests create unique disposable Mxxxxxxx projects with closed networks. Enable
with CBUS_CGATE_TEST_HOST and CBUS_UNITSPEC_DIR pointing to decrypted vendor specs.
No test opens a network or reads/writes physical C-Bus units.
"""
from pathlib import Path
import os
import unittest
from uuid import uuid4

from cbus_toolkit.memory import (BytePatch, MemoryCodec, MemoryError, MemoryImage,
                                 MemoryPatch, MissingMemoryError, UnsupportedMemoryLayout,
                                 decode_sixbit, encode_sixbit)
from cbus_toolkit.unitspec import ParameterSpec, UnitSpec, UnitSpecStore


def parameter(name="Value", kind="int", **fields):
    values = {"Name": name, "Type": kind, "Address": "$10"}
    values.update({key: str(value) for key, value in fields.items()})
    return ParameterSpec(name, kind, "fixture.xml", values)


def codec(*parameters, **kwargs):
    spec = UnitSpec("fixture.xml", {}, ("fixture.xml",), {p.name: p for p in parameters})
    return MemoryCodec(spec, **kwargs)


class MemoryImageTests(unittest.TestCase):
    def test_sparse_memory_never_substitutes_missing_bytes(self):
        image = MemoryImage({16: 0, 18: 255})
        self.assertEqual(image.read(16, 1), b"\x00")
        with self.assertRaises(MissingMemoryError) as error:
            image.read(16, 3)
        self.assertEqual(error.exception.address, 17)
        self.assertEqual(image.as_dict()["bytes"], {"16": 0, "18": 255})
        with self.assertRaises(TypeError):
            image.data[17] = 1

    def test_masks_preserve_original_bits_and_apply_atomically(self):
        image = MemoryImage({16: 0b10100101})
        patch = MemoryPatch((BytePatch(16, 0b00010000, 0b00110000), BytePatch(17, 255)))
        result = patch.apply(image)
        self.assertEqual(result.read(16, 2), bytes([0b10010101, 255]))
        self.assertEqual(image.data, {16: 0b10100101})
        with self.assertRaises(MissingMemoryError):
            MemoryPatch((BytePatch(16, 0), BytePatch(17, 1, 1))).apply(image)
        self.assertEqual(image.data, {16: 0b10100101})

    def test_patch_merge_accepts_disjoint_bits_and_rejects_conflicts(self):
        a = MemoryPatch((BytePatch(16, 0xA0, 0xF0),))
        b = MemoryPatch((BytePatch(16, 0x05, 0x0F),))
        self.assertEqual(a.merge(b).apply(MemoryImage({})).byte(16), 0xA5)
        self.assertEqual(a.merge(a).edits, a.edits)
        with self.assertRaisesRegex(MemoryError, "Conflicting"):
            a.merge(MemoryPatch((BytePatch(16, 0x50, 0xF0),)))

    def test_bad_addresses_bytes_masks_and_bounds(self):
        for data in ({-1: 0}, {True: 0}, {0: 256}, {0: True}, {0: 1, "0": 2}):
            with self.subTest(data=data), self.assertRaises(MemoryError):
                MemoryImage(data)
        for args in ((0, 1, 0), (0, 0x10, 0x0F), (0, 0, 256)):
            with self.assertRaises(MemoryError):
                BytePatch(*args)
        with self.assertRaises(MemoryError):
            MemoryImage({}).read(0, -1)
        with self.assertRaises(MemoryError):
            MemoryImage.from_bytes("not bytes")


class MemoryCodecTests(unittest.TestCase):
    def test_nibble_array_stride_preserves_gaps_and_adjacent_field(self):
        c = codec(parameter(ArraySize=3, BitSize=4, BitAddress=4, ArraySkip=1))
        image = MemoryImage.from_bytes(bytes.fromhex("aaaaaaaaaa"), start=16)
        patch = c.encode("Value", [1, 2, 3])
        self.assertEqual([e.as_dict() for e in patch.edits], [
            {"address": 16, "value": 0x10, "mask": 0xF0},
            {"address": 18, "value": 0x20, "mask": 0xF0},
            {"address": 20, "value": 0x30, "mask": 0xF0}])
        result = patch.apply(image)
        self.assertEqual(result.read(16, 5).hex(), "1aaa2aaa3a")
        self.assertEqual(c.decode("Value", result), [1, 2, 3])

    def test_int16_is_little_endian_and_skip_is_scaled_by_width(self):
        c = codec(parameter(ArraySize=2, BitSize=16, ArraySkip=1, Endian="big"))
        result = c.encode("Value", "$1234 0xcdef").apply(MemoryImage({}))
        self.assertEqual(dict(result.data), {16: 0x34, 17: 0x12, 20: 0xEF, 21: 0xCD})
        self.assertEqual(c.decode("Value", result), [0x1234, 0xCDEF])
        self.assertEqual(c.layout("Value").stride, 4)
        self.assertEqual(c.layout("Value").endian, "little")
        self.assertNotIn(18, result.data)

    def test_two_byte_shifted_mask_preserves_unrelated_bits(self):
        c = codec(parameter(BitSize=10, BitAddress=5))
        image = MemoryImage.from_bytes(bytes.fromhex("1580"), start=16)
        result = c.encode("Value", 1023).apply(image)
        self.assertEqual(result.read(16, 2).hex(), "f5ff")
        self.assertEqual(c.decode("Value", result), 1023)
        self.assertEqual(c.encode("Value", 0).apply(result).read(16, 2).hex(), "1580")

    def test_bit_array_crosses_byte_boundary_and_ignores_native_skip(self):
        c = codec(parameter(kind="bit", ArraySize=5, BitAddress=6, ArraySkip=9))
        result = c.encode("Value", "1 0 1 1 0").apply(MemoryImage.from_bytes(bytes.fromhex("aaaa"), start=16))
        self.assertEqual(result.read(16, 2).hex(), "6aab")
        self.assertEqual(c.decode("Value", result), [1, 0, 1, 1, 0])
        self.assertEqual(c.decode("Value", result, index=2, count=2), [1, 1])

    def test_partial_array_requires_explicit_option_and_respects_index_stride(self):
        c = codec(parameter(ArraySize=3, BitSize=16))
        image = MemoryImage.from_bytes(b"\x11\x11\x22\x22\x33\x33", start=16)
        with self.assertRaises(MemoryError):
            c.encode("Value", [0xABCD], index=1)
        result = c.encode("Value", [0xABCD], index=1, allow_partial=True).apply(image)
        self.assertEqual(result.read(16, 6).hex(), "1111cdab3333")
        self.assertEqual(c.decode("Value", result, index=1), [0xABCD, 0x3333])
        for index, count in ((-1, 1), (3, 1), (1, 3), (0, 0), (True, 1)):
            with self.subTest(index=index, count=count), self.assertRaises(MemoryError):
                c.decode("Value", result, index=index, count=count)

    def test_long_little_endian_fixed_vectors_all_supported_widths(self):
        c = codec(parameter(kind="long", BitSize=16, ArraySize=2, ArraySkip=1))
        result = c.encode("Value", "0b1001000110100 65535").apply(MemoryImage({}))
        self.assertEqual(dict(result.data), {16: 0x34, 17: 0x12, 20: 255, 21: 255})
        self.assertEqual(c.decode("Value", result), [0x1234, 65535])
        c64 = codec(parameter(kind="long", BitSize=64))
        result = c64.encode("Value", 0xFEDCBA9876543210).apply(MemoryImage({}))
        self.assertEqual(result.read(16, 8).hex(), "1032547698badcfe")
        self.assertEqual(c64.decode("Value", result), 0xFEDCBA9876543210)
        for bits in range(8, 65, 8):
            c = codec(parameter(kind="long", BitSize=bits))
            encoded = c.encode("Value", (1 << bits) - 1).apply(MemoryImage({}))
            self.assertEqual(encoded.read(16, bits // 8), b"\xff" * (bits // 8))

    def test_big_endian_long_decode_supported_but_buggy_native_write_rejected(self):
        c = codec(parameter(kind="long", BitSize=16, Endian="big"))
        self.assertEqual(c.decode("Value", MemoryImage.from_bytes(b"\x12\x34", start=16)), 0x1234)
        with self.assertRaises(UnsupportedMemoryLayout):
            c.encode("Value", 1)

    def test_sixbit_independent_fixed_vectors_and_alias(self):
        self.assertEqual(encode_sixbit("ABCDEFGH").hex(), "8218a39259a7")
        self.assertEqual(encode_sixbit("").hex(), "79e79e79e79e")
        self.assertEqual(decode_sixbit(bytes.fromhex("8218a39259a7")), "ABCDEFGH")
        self.assertEqual(decode_sixbit(bytes.fromhex("79e79e79e79e")), "        ")
        self.assertEqual(encode_sixbit("a?"), encode_sixbit("A "))
        self.assertEqual(encode_sixbit("!!!!!!!!"), bytes(6))
        self.assertEqual(decode_sixbit(bytes(6)), "!!!!!!!!")
        for text in ("TOO LONG!", "\n", "é", "ß", "{"):
            with self.subTest(text=text), self.assertRaises(MemoryError):
                encode_sixbit(text)
        c = codec(parameter(kind="sixbit", ArraySize=8))
        image = c.encode("Value", "abc").apply(MemoryImage({}))
        self.assertEqual(c.decode("Value", image), "ABC     ")

    def test_strings_preserve_text_zero_pad_and_latin1_native_reads(self):
        c = codec(parameter(kind="string", ArraySize=8))
        result = c.encode("Value", " A  B ").apply(MemoryImage({}))
        self.assertEqual(result.read(16, 8), b" A  B \x00\x00")
        self.assertEqual(c.decode("Value", result), " A  B ")
        embedded = MemoryImage.from_bytes(b"A\x00B\x00\x00\x00\x00\x00", start=16)
        self.assertEqual(c.decode("Value", embedded), "A\x00B")
        with self.assertRaises(MemoryError):
            c.encode("Value", "é")
        utf8 = codec(parameter(kind="string", ArraySize=8), string_encoding="utf-8")
        result = utf8.encode("Value", "é").apply(MemoryImage({}))
        self.assertEqual(result.read(16, 8).hex(), "c3a9000000000000")
        self.assertEqual(utf8.decode("Value", result), "Ã©")
        latin1 = codec(parameter(kind="string", ArraySize=8), string_encoding="latin-1")
        self.assertEqual(latin1.encode("Value", "é").apply(MemoryImage({})).byte(16), 0xE9)
        with self.assertRaises(MemoryError):
            utf8.encode("Value", "漢漢漢")
        with self.assertRaises(UnsupportedMemoryLayout):
            c.encode("Value", "partial", index=1)

    def test_invalid_values_reject_without_truncation_or_default_reset(self):
        c = codec(parameter(BitSize=4, MinValue=2, MaxValue=10, DefaultValue=3))
        for value in (-1, 0, 11, 16, True, 1.2, "bad", [], [2, 3]):
            with self.subTest(value=value), self.assertRaises(MemoryError):
                c.encode("Value", value)
        # Decoding reports the actual bits, even if outside the semantic range.
        self.assertEqual(c.decode("Value", MemoryImage({16: 15})), 15)
        with self.assertRaises(MemoryError):
            codec(parameter(MinValue=5, MaxValue=4)).encode("Value", 4)

    def test_invalid_or_unknown_layouts_and_size_limits(self):
        for p in (parameter(kind="opaque"), parameter(BitSize=17), parameter(BitSize=16, BitAddress=1),
                  parameter(kind="long", BitSize=12), parameter(kind="long", BitAddress=1),
                  parameter(kind="long", Endian="middle"), parameter(kind="sixbit", ArraySize=7),
                  parameter(kind="string", ArraySkip=1), parameter(Address=-1), parameter(ArraySkip=-1)):
            with self.subTest(fields=p.fields), self.assertRaises(MemoryError):
                codec(p).layout("Value")
        with self.assertRaises(MemoryError):
            codec(parameter(), memory_size=16).layout("Value")
        with self.assertRaises(MemoryError):
            codec(parameter(), memory_size=0)
        with self.assertRaises(MemoryError):
            codec(parameter(), string_encoding="made-up-codec")
        with self.assertRaises(MemoryError):
            codec(parameter()).layout("Missing")

    def test_encode_many_preflights_conflicting_aliases(self):
        c = codec(parameter("Low", BitSize=4), parameter("High", BitSize=4, BitAddress=4), parameter("Alias"))
        result = c.encode_many({"Low": 5, "High": 10}).apply(MemoryImage({}))
        self.assertEqual(result.byte(16), 0xA5)
        with self.assertRaises(MemoryError):
            c.encode_many({"Low": 5, "Alias": 0xA4})

    def test_array_map_three_cycle_direction_and_mask_preservation(self):
        c = codec(parameter(ArraySize=3, BitSize=4, BitAddress=4, ArraySkip=1, ArrayMap="2 3 1"))
        physical = MemoryImage.from_bytes(bytes.fromhex("a177b288c3"), start=16)
        logical = c.remap(physical, direction="physical_to_logical")
        self.assertEqual(logical.read(16, 5).hex(), "c177a288b3")
        self.assertEqual(c.decode("Value", logical), [12, 10, 11])
        self.assertEqual(c.remap(logical, direction="logical_to_physical"), physical)
        self.assertEqual(physical.read(16, 5).hex(), "a177b288c3")
        # Codec values are logical; encode itself never applies ArrayMap.
        self.assertEqual(c.encode("Value", [1, 2, 3]).apply(logical).read(16, 5).hex(), "1177228833")

    def test_array_map_invalid_permutations_and_missing_memory(self):
        for mapping in ("1 1 3", "0 2 3", "1 2 4", "1 2"):
            c = codec(parameter(ArraySize=3, ArrayMap=mapping))
            with self.subTest(mapping=mapping), self.assertRaises(MemoryError):
                c.remap(MemoryImage({}), direction="physical_to_logical")
        c = codec(parameter(ArraySize=3, ArrayMap="2 3 1"))
        with self.assertRaises(MissingMemoryError):
            c.remap(MemoryImage({16: 1, 17: 2}), direction="physical_to_logical")
        with self.assertRaises(MemoryError):
            c.remap(MemoryImage({}), direction="guess")
        wide = codec(parameter(ArraySize=2, ArrayMap="2 1", BitSize=16))
        with self.assertRaises(UnsupportedMemoryLayout):
            wide.remap(MemoryImage({}), direction="physical_to_logical")


@unittest.skipUnless(os.environ.get("CBUS_UNITSPEC_DIR"), "Set CBUS_UNITSPEC_DIR to audit real vendor parameter layouts")
class VendorLayoutTests(unittest.TestCase):
    def test_every_resolved_vendor_parameter_has_supported_layout(self):
        store = UnitSpecStore(os.environ["CBUS_UNITSPEC_DIR"])
        count = 0
        for row in store.list_specs():
            c = MemoryCodec(store.load(row["filename"]))
            for name in c.spec.parameters:
                with self.subTest(spec=row["filename"], parameter=name):
                    self.assertGreater(c.layout(name).end_address, c.layout(name).address)
                    count += 1
        self.assertGreater(count, 0)


@unittest.skipUnless(os.environ.get("CBUS_CGATE_TEST_HOST") and os.environ.get("CBUS_UNITSPEC_DIR"),
                     "Set CBUS_CGATE_TEST_HOST and CBUS_UNITSPEC_DIR for disposable native memory acceptance")
class NativeMemoryTests(unittest.TestCase):
    def setUp(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.programming import Programmer
        self.client = CGateClient(os.environ["CBUS_CGATE_TEST_HOST"],
                                  port=int(os.environ.get("CBUS_CGATE_TEST_PORT", "20023")), timeout=20)
        self.client.__enter__()
        self.addCleanup(self.client.close)
        self.project = "M" + uuid4().hex[:7].upper()
        self.client.command(f"PROJECT NEW {self.project}")
        self.client.command(f"PROJECT USE {self.project}")
        self.client.command("DBCREATENET 254 Memory_Offline Cni 127.0.0.1:29999")
        self.client.command(f"NET LOAD DB {self.project}")
        self.client.command(f"PROJECT SAVE {self.project}")
        self.addCleanup(self.cleanup_project)
        self.programmer = Programmer(self.client)
        self.store = UnitSpecStore(os.environ["CBUS_UNITSPEC_DIR"])

    def session(self, unit_type, firmware, catalog):
        return self.programmer.new(f"//{self.project}/254", unit_type, firmware, catalog_number=catalog,
                                   name="MEM_" + uuid4().hex[:8])

    def cleanup_project(self):
        self.client.command(f"PROJECT CLOSE {self.project}")
        self.client.command(f"PROJECT DELETE {self.project}")

    def raw(self, session, start, count):
        result = session.get_raw_data(start, count)
        lines = [line for line in result.lines if "RawData=" in line]
        self.assertEqual(len(lines), 1)
        data = bytes.fromhex(lines[0].split("RawData=", 1)[1])
        self.assertEqual(len(data), count)
        return data

    def compare(self, session, c, name, value):
        layout = c.layout(name)
        start, count = layout.address, layout.end_address - layout.address
        before = MemoryImage.from_bytes(self.raw(session, start, count), start=start)
        expected = c.encode(name, value).apply(before)
        text = " ".join(str(v) for v in value) if isinstance(value, (list, tuple)) else str(value)
        session.set(name, text)
        self.assertEqual(self.raw(session, start, count), expected.read(start, count))
        decoded = c.decode(name, expected)
        native = session.values(name)[name]
        if layout.parameter.type in ("int", "bit", "long"):
            values = [int(token, 0) for token in native.split()]
            self.assertEqual(values[0] if layout.array_size == 1 else values, decoded)
        else:
            self.assertEqual(native, decoded)

    def test_native_int_nibble_bit_and_sixbit_bytes(self):
        c = MemoryCodec(self.store.load("KEY4.xml"))
        with self.session("KEY4", "1.2.67", "5034N") as session:
            self.compare(session, c, "Application", [56, 255])
            self.compare(session, c, "JPCommand", [1, 2, 3, 4])
            self.compare(session, c, "EEPROMLevelStore", 1)
            self.compare(session, c, "DebounceTime", 17)
            self.compare(session, c, "UnitName", "ABCDEFGH")
            # Native SET has a BigInteger short-byte-array bug for leading '!'.
            # The codec produces valid packed bytes and native GET decodes them.
            address = c.layout("UnitName").address
            session.set_raw_data(address, encode_sixbit("!!!!!!!!"))
            self.assertEqual(session.values("UnitName")["UnitName"], "!!!!!!!!")

    def test_native_int16_bytes(self):
        c = MemoryCodec(self.store.load("KEYGL5.xml"))
        # Native PP NEW allocates 2048 bytes, too small for this eDLT schema.
        # Loading a database unit lets its device class determine memory size.
        path = f"//{self.project}/254/p/220"
        self.client.command(f"DBADDSAFE //{self.project}/254 Unit 220 Memory_eDLT")
        for field, value in (("UnitType", "KEYGL5"), ("FirmwareVersion", "5.5.00"),
                             ("CatalogNumber", "5085EDL"), ("UnitName", "KEYGL5")):
            self.client.command(f"DBSET {path}/{field} {value}")
        with self.programmer.load(f"//{self.project}/254", "/db" + path,
                                  name="MEM_" + uuid4().hex[:8]) as session:
            session.reset_defaults()
            self.compare(session, c, "CorridorLinkingCorridorTime", 0x1234)
            self.compare(session, c, "LCDForeground", 5)

    def test_native_packed_bit_array(self):
        c = MemoryCodec(self.store.load("SCNCTL5.xml"))
        with self.session("SCNCTL5", "1.2.3", "5035NIRSL") as session:
            self.compare(session, c, "SecondaryMasterOffEnabled", [int(i % 3 == 0) for i in range(30)])

    def test_native_long_and_wide_stride_ncc_arrays(self):
        c = MemoryCodec(self.store.load("NCC_KEYB6A.xml"))
        with self.session("KEYB6A", "1.3.0", "5086680") as session:
            self.compare(session, c, "KeyToWidgetAssignmentBitmaskArrayProfile0", [0, 1, 255, 256, 0x1234, 32767, 32768, 65535])
            self.compare(session, c, "WidgetPropertiesIndicatorOffColour", list(range(16)))
            self.compare(session, c, "UserColourSextant", [1, 254])

    def test_native_string_write_charset_and_read_asymmetry(self):
        c = MemoryCodec(self.store.load("PC_RDTS.xml"), string_encoding="utf-8")
        with self.session("SENTEMP4", "1.0.00", "5104DTSI") as session:
            self.compare(session, c, "Channel1ChannelName", "ASCII  TEXT")
            self.compare(session, c, "Channel1ChannelName", "é")
            self.assertEqual(session.values("Channel1ChannelName")["Channel1ChannelName"], "Ã©")
            self.compare(session, c, "Channel1ChannelName", "漢")
            self.assertEqual(session.values("Channel1ChannelName")["Channel1ChannelName"], "æ¼¢")


if __name__ == "__main__":
    unittest.main()
