"""Schema-driven codecs for logical C-Gate PP memory, without hardware I/O.

Offsets, masks and strides follow C-Gate 3.4.0 lP; long values follow lz.
The caller supplies known memory bytes. Missing bytes are never guessed, and
patches describe changed bits rather than overwriting neighbouring fields.

This is a memory format API, not the PP command parser: it does not trim strings,
reset invalid values to defaults, truncate arrays, or emulate buggy indexed PP
SET commands. Strings default to strict ASCII. An explicit string_encoding is
required for non-ASCII writes because native SET uses the JVM default charset;
native GET always decodes Latin-1 and strips trailing NULs. Hardware transfer
methods, checksums, protection flags and physical memory protocols are separate.
"""
from __future__ import annotations

from dataclasses import dataclass
import codecs
import re
from types import MappingProxyType
from typing import Any, Mapping

from .unitspec import ParameterSpec, UnitSpec, UnitSpecError


MAX_MEMORY_BYTES = 16 * 1024 * 1024  # Resource limit, not a device capacity claim.


class MemoryError(ValueError):
    """Invalid memory, parameter layout, patch or value."""


class MissingMemoryError(MemoryError):
    """A required byte has not been captured or explicitly supplied."""

    def __init__(self, address: int):
        self.address = address
        super().__init__(f"No known memory byte at 0x{address:x}")


class UnsupportedMemoryLayout(MemoryError):
    """A schema layout has no supported, verified encoding."""


def _integer(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise MemoryError(f"{label} must be an integer, not a boolean")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip()
        if re.fullmatch(r"[+-]?(?:\$[0-9a-fA-F]+|0[xX][0-9a-fA-F]+|0[bB][01]+|[0-9]+)", text):
            sign = -1 if text.startswith("-") else 1
            text = text.lstrip("+-")
            if text.startswith("$"):
                return sign * int(text[1:], 16)
            return sign * int(text, 0 if text.lower().startswith(("0x", "0b")) else 10)
    raise MemoryError(f"{label} must be an integer")


def _address(value: Any) -> int:
    value = _integer(value, "Memory address")
    if not 0 <= value < MAX_MEMORY_BYTES:
        raise MemoryError("Memory address is outside the supported resource bounds")
    return value


def _byte(value: Any, label: str = "Memory byte") -> int:
    value = _integer(value, label)
    if not 0 <= value <= 255:
        raise MemoryError(f"{label} must be in 0..255")
    return value


@dataclass(frozen=True)
class MemoryImage:
    """Immutable sparse bytes; omission means unknown, including sparse gaps."""

    data: Mapping[int, int]

    def __post_init__(self):
        cells = {}
        for address, value in self.data.items():
            address = _address(address)
            if address in cells:
                raise MemoryError("Duplicate memory address after integer conversion")
            cells[address] = _byte(value)
        object.__setattr__(self, "data", MappingProxyType(cells))

    @classmethod
    def from_bytes(cls, data: bytes, *, start: int = 0) -> MemoryImage:
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise MemoryError("Memory data must be bytes")
        start = _address(start)
        if start + len(data) > MAX_MEMORY_BYTES:
            raise MemoryError("Memory data exceeds supported resource bounds")
        return cls({start + i: byte for i, byte in enumerate(bytes(data))})

    def byte(self, address: int) -> int:
        address = _address(address)
        try:
            return self.data[address]
        except KeyError as exc:
            raise MissingMemoryError(address) from exc

    def read(self, start: int, count: int) -> bytes:
        start, count = _address(start), _integer(count, "Byte count")
        if count < 0 or start + count > MAX_MEMORY_BYTES:
            raise MemoryError("Invalid memory read bounds")
        return bytes(self.byte(start + i) for i in range(count))

    def as_dict(self) -> dict[str, Any]:
        return {"format": "cbus-sparse-memory-v1", "bytes": {str(a): self.data[a] for a in sorted(self.data)}}


@dataclass(frozen=True)
class BytePatch:
    address: int
    value: int
    mask: int = 255

    def __post_init__(self):
        object.__setattr__(self, "address", _address(self.address))
        object.__setattr__(self, "value", _byte(self.value, "Patch value"))
        object.__setattr__(self, "mask", _byte(self.mask, "Patch mask"))
        if not self.mask or self.value & ~self.mask:
            raise MemoryError("Patch needs a nonzero mask and no value bits outside its mask")

    def as_dict(self):
        return {"address": self.address, "value": self.value, "mask": self.mask}


@dataclass(frozen=True)
class MemoryPatch:
    """A set of masked byte edits, applied atomically to a new image."""

    edits: tuple[BytePatch, ...] = ()

    def __post_init__(self):
        cells = {}
        for edit in self.edits:
            if not isinstance(edit, BytePatch):
                raise MemoryError("Patch entries must be BytePatch objects")
            previous = cells.get(edit.address)
            if previous:
                if (previous.value ^ edit.value) & previous.mask & edit.mask:
                    raise MemoryError(f"Conflicting patches at 0x{edit.address:x}")
                edit = BytePatch(edit.address, previous.value | edit.value, previous.mask | edit.mask)
            cells[edit.address] = edit
        object.__setattr__(self, "edits", tuple(cells[a] for a in sorted(cells)))

    def merge(self, *patches: MemoryPatch) -> MemoryPatch:
        return MemoryPatch(self.edits + tuple(edit for patch in patches for edit in patch.edits))

    def apply(self, image: MemoryImage) -> MemoryImage:
        cells = dict(image.data)
        for edit in self.edits:
            # A whole-byte assignment can establish a previously unknown byte;
            # preserving unrelated bits requires a known original byte.
            before = 0 if edit.mask == 255 else image.byte(edit.address)
            cells[edit.address] = (before & ~edit.mask) | edit.value
        return MemoryImage(cells)

    def as_dict(self) -> dict[str, Any]:
        return {"format": "cbus-memory-patch-v1", "edits": [edit.as_dict() for edit in self.edits]}


def encode_sixbit(value: str) -> bytes:
    """Eight uppercased characters packed MSB first into exactly six bytes.

    Space and '?' share code 30; decoding chooses space. Unlike the native
    BigInteger encoder's short-array bug, leading zero codes are zero-padded.
    Non-ASCII input is rejected to avoid locale-dependent uppercase changes.
    """
    if not isinstance(value, str) or any(ord(c) > 127 for c in value):
        raise MemoryError("Sixbit requires ASCII text")
    value = value.upper()
    if len(value) > 8 or any(not 32 <= ord(c) <= 96 for c in value):
        raise MemoryError("Sixbit needs at most eight characters in ASCII 32..96 after uppercase")
    bits = 0
    for char in value.ljust(8):
        bits = (bits << 6) | (30 if char == " " else ord(char) - 33)
    return bits.to_bytes(6, "big")


def decode_sixbit(data: bytes) -> str:
    if not isinstance(data, bytes) or len(data) != 6:
        raise MemoryError("Sixbit requires exactly six bytes")
    bits = int.from_bytes(data, "big")
    codes = [(bits >> (6 * (7 - index))) & 63 for index in range(8)]
    return "".join(" " if code == 30 else chr(code + 33) for code in codes)


@dataclass(frozen=True)
class ParameterLayout:
    parameter: ParameterSpec
    address: int
    array_size: int
    bit_size: int
    bit_address: int
    array_skip: int
    byte_width: int
    stride: int
    endian: str
    end_address: int  # Exclusive span end; gaps within the span can be unknown.

    def as_dict(self):
        return {"name": self.parameter.name, "type": self.parameter.type,
                "address": self.address, "array_size": self.array_size,
                "bit_size": self.bit_size, "bit_address": self.bit_address,
                "array_skip": self.array_skip, "byte_width": self.byte_width,
                "stride": self.stride, "endian": self.endian, "end_address": self.end_address,
                "memory_space": "logical_pp"}


class MemoryCodec:
    def __init__(self, spec: UnitSpec, *, string_encoding: str = "ascii", memory_size: int | None = None):
        self.spec = spec
        try:
            self.string_encoding = codecs.lookup(string_encoding).name
        except (LookupError, TypeError) as exc:
            raise MemoryError("Unknown explicit string encoding") from exc
        self.memory_size = MAX_MEMORY_BYTES if memory_size is None else _integer(memory_size, "Memory size")
        if not 0 < self.memory_size <= MAX_MEMORY_BYTES:
            raise MemoryError("Memory size is outside the supported resource bounds")

    def layout(self, name: str) -> ParameterLayout:
        try:
            p = self.spec.get(name)
            address, count, bits = p.address, p.array_size, p.bit_size
        except (UnitSpecError, KeyError) as exc:
            raise MemoryError(str(exc)) from exc
        offset = _integer(p.fields.get("BitAddress") or "0", "BitAddress")
        skip = _integer(p.fields.get("ArraySkip") or "0", "ArraySkip")
        endian = (p.fields.get("Endian") or "little").lower()
        if not 0 <= address < self.memory_size or count < 1 or skip < 0 or offset < 0:
            raise MemoryError(f"Invalid memory layout for {name!r}")
        if count > MAX_MEMORY_BYTES or skip >= MAX_MEMORY_BYTES:
            raise MemoryError("Array exceeds supported resource bounds")
        if p.type == "int":
            if not 1 <= bits <= 16 or offset + bits > 16:
                raise UnsupportedMemoryLayout("C-Gate int encoding supports at most two bytes including BitAddress")
            width = (offset + bits + 7) // 8
            stride = width * (skip + 1)
            end = address + (count - 1) * stride + width
            endian = "little"  # Native int ignores Endian; only long uses it.
        elif p.type == "long":
            if bits not in range(8, 65, 8) or offset:
                raise UnsupportedMemoryLayout("Long requires a byte-aligned width in 8..64 and BitAddress 0")
            if endian not in ("little", "big"):
                raise UnsupportedMemoryLayout("Unknown long byte order")
            width = bits // 8
            stride = width * (skip + 1)
            end = address + (count - 1) * stride + width
        elif p.type == "bit":
            # BitSize and ArraySkip are ignored by native bit packing.
            bits, width, stride, endian = 1, 1, 0, "little"
            end = address + (offset + count + 7) // 8
        elif p.type in ("string", "sixbit"):
            if offset or skip:
                raise UnsupportedMemoryLayout("Text layout with BitAddress or ArraySkip needs separate verification")
            if p.type == "sixbit" and count != 8:
                raise UnsupportedMemoryLayout("Sixbit specification must have ArraySize 8")
            width = count if p.type == "string" else 6
            stride, endian = 0, "big" if p.type == "sixbit" else self.string_encoding
            end = address + width
        else:
            raise UnsupportedMemoryLayout(f"Unsupported parameter type {p.type!r}")
        if end > self.memory_size:
            raise MemoryError(f"Parameter {name!r} exceeds supplied memory bounds")
        return ParameterLayout(p, address, count, bits, offset, skip, width, stride, endian, end)

    @staticmethod
    def _selection(layout: ParameterLayout, index: int, count: int | None = None):
        index = _integer(index, "Array index")
        count = layout.array_size - index if count is None else _integer(count, "Array count")
        if index < 0 or index >= layout.array_size or count < 1 or index + count > layout.array_size:
            raise MemoryError("Array selection is outside the declared bounds")
        if layout.parameter.type in ("string", "sixbit") and (index or count != layout.array_size):
            raise UnsupportedMemoryLayout("Text fields require whole-field reads and writes")
        return index, count

    def decode(self, name: str, image: MemoryImage, *, index: int = 0, count: int | None = None):
        layout = self.layout(name)
        index, count = self._selection(layout, index, count)
        kind = layout.parameter.type
        if kind == "string":
            return image.read(layout.address, layout.byte_width).decode("latin-1").rstrip("\x00")
        if kind == "sixbit":
            return decode_sixbit(image.read(layout.address, 6))
        values = []
        for element in range(index, index + count):
            if kind == "bit":
                bit = layout.bit_address + element
                values.append((image.byte(layout.address + bit // 8) >> (bit % 8)) & 1)
            else:
                address = layout.address + element * layout.stride
                value = int.from_bytes(image.read(address, layout.byte_width), layout.endian)
                values.append((value >> layout.bit_address) & ((1 << layout.bit_size) - 1))
        return values[0] if layout.array_size == 1 else values

    def encode(self, name: str, value: Any, *, index: int = 0, allow_partial: bool = False) -> MemoryPatch:
        layout = self.layout(name)
        index, available = self._selection(layout, index)
        p, kind = layout.parameter, layout.parameter.type
        if kind in ("string", "sixbit"):
            if not isinstance(value, str):
                raise MemoryError("Text parameter requires a string")
            if kind == "sixbit":
                data = encode_sixbit(value)
            else:
                try:
                    data = value.encode(self.string_encoding, errors="strict")
                except (UnicodeError, LookupError) as exc:
                    raise MemoryError(f"String cannot be encoded using explicit {self.string_encoding}") from exc
                if len(data) > layout.array_size:
                    raise MemoryError("Encoded string bytes exceed ArraySize")
                data = data.ljust(layout.array_size, b"\x00")
            return MemoryPatch(tuple(BytePatch(layout.address + i, b) for i, b in enumerate(data)))
        tokens = value.split() if isinstance(value, str) else value if isinstance(value, (tuple, list)) else [value]
        values = [_integer(token, "Parameter value") for token in tokens]
        if not values or len(values) > available or (not allow_partial and len(values) != available):
            raise MemoryError(f"Expected {'1..' if allow_partial else ''}{available} numeric values")
        minimum = _integer(p.fields["MinValue"], "MinValue") if p.fields.get("MinValue", "").strip() else 0
        maximum = _integer(p.fields["MaxValue"], "MaxValue") if p.fields.get("MaxValue", "").strip() else (1 << layout.bit_size) - 1
        if minimum > maximum:
            raise MemoryError("Parameter minimum exceeds maximum")
        edits = []
        for element, number in enumerate(values, index):
            if not minimum <= number <= maximum:
                raise MemoryError(f"Parameter value must be in {minimum}..{maximum}")
            if not 0 <= number < (1 << layout.bit_size):
                raise MemoryError("Parameter value does not fit its unsigned bit width")
            if kind == "bit":
                bit = layout.bit_address + element
                edits.append(BytePatch(layout.address + bit // 8, number << (bit % 8), 1 << (bit % 8)))
                continue
            if kind == "long" and layout.endian == "big":
                # Native lz copies BigInteger's variable-width signed byte array
                # from its start, then pads at the end. That is not a stable
                # fixed-width unsigned encoding (e.g. 1 -> 0100 at width16).
                raise UnsupportedMemoryLayout("Native big-endian long encoder is inconsistent; only little-endian long writes are supported")
            address = layout.address + element * layout.stride
            mask = ((1 << layout.bit_size) - 1) << layout.bit_address
            encoded = number << layout.bit_address
            for byte in range(layout.byte_width):
                byte_mask = (mask >> (byte * 8)) & 255
                if byte_mask:
                    edits.append(BytePatch(address + byte, (encoded >> (byte * 8)) & byte_mask, byte_mask))
        return MemoryPatch(tuple(edits))

    def encode_many(self, values: Mapping[str, Any]) -> MemoryPatch:
        """Preflight all complete field assignments and reject conflicting aliases."""
        return MemoryPatch(tuple(edit for name, value in values.items() for edit in self.encode(name, value).edits))

    def remap(self, image: MemoryImage, *, direction: str) -> MemoryImage:
        """Apply native ArrayMap permutations explicitly, preserving other bits.

        ArrayMap lists one-based logical destinations in physical element order.
        Native PP values are already logical; never apply this to PP GET_RAW_DATA
        unless intentionally converting it to a physical-layout snapshot.
        Only the vendor's single-byte masked remap shape is supported.
        """
        if direction not in ("physical_to_logical", "logical_to_physical"):
            raise MemoryError("Specify physical_to_logical or logical_to_physical")
        edits = []
        for name, p in self.spec.parameters.items():
            if not p.fields.get("ArrayMap", "").strip():
                continue
            layout = self.layout(name)
            if p.type != "int" or layout.bit_address + layout.bit_size > 8:
                raise UnsupportedMemoryLayout("ArrayMap supports only int fields contained in one byte")
            mapping = [_integer(x, "ArrayMap index") - 1 for x in p.fields["ArrayMap"].split()]
            if sorted(mapping) != list(range(layout.array_size)):
                raise MemoryError("ArrayMap must be a complete one-based permutation")
            if direction == "logical_to_physical":
                inverse = [0] * len(mapping)
                for source, destination in enumerate(mapping):
                    inverse[destination] = source
                mapping = inverse
            mask = ((1 << layout.bit_size) - 1) << layout.bit_address
            for source, destination in enumerate(mapping):
                value = image.byte(layout.address + source * (layout.array_skip + 1)) & mask
                edits.append(BytePatch(layout.address + destination * (layout.array_skip + 1), value, mask))
        return MemoryPatch(tuple(edits)).apply(image)
