#!/usr/bin/env python3
"""Extract a sanitized Toolkit executable form/control/event inventory.

The vendor executable and map remain outside Git.  This tool reads their PE
resources and Delphi binary form streams, then writes only the names and
digests needed to audit the compatibility census.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path, PureWindowsPath
import re
import struct
from typing import Any


SCHEMA_VERSION = 1
TARGET_PRODUCT_VERSION = "1.18.0"
MAX_DEPTH = 128
MAX_VALUE_BYTES = 32 * 1024 * 1024


class DfmFormatError(ValueError):
    """Raised when a binary Delphi form is malformed or unsupported."""


@dataclass
class Cursor:
    data: bytes
    offset: int = 0

    @property
    def remaining(self) -> int:
        return len(self.data) - self.offset

    def read(self, count: int) -> bytes:
        if count < 0 or count > self.remaining:
            raise DfmFormatError(
                f"read of {count} bytes at offset {self.offset} exceeds stream"
            )
        start = self.offset
        self.offset += count
        return self.data[start : self.offset]

    def peek_u8(self) -> int:
        if not self.remaining:
            raise DfmFormatError("unexpected end of stream")
        return self.data[self.offset]

    def u8(self) -> int:
        return self.read(1)[0]

    def i8(self) -> int:
        return struct.unpack("<b", self.read(1))[0]

    def i16(self) -> int:
        return struct.unpack("<h", self.read(2))[0]

    def i32(self) -> int:
        return struct.unpack("<i", self.read(4))[0]

    def u32(self) -> int:
        return struct.unpack("<I", self.read(4))[0]

    def i64(self) -> int:
        return struct.unpack("<q", self.read(8))[0]

    def u64(self) -> int:
        return struct.unpack("<Q", self.read(8))[0]

    def short_bytes(self) -> bytes:
        return self.read(self.u8())


def _text(raw: bytes, *, encoding: str = "cp1252") -> str:
    return raw.decode(encoding, errors="replace")


def _bounded_count(value: int, *, unit: int = 1) -> int:
    if value < 0 or value > MAX_VALUE_BYTES // unit:
        raise DfmFormatError(f"unreasonable value length: {value}")
    return value


def _read_string_value(cursor: Cursor, value_type: int) -> str:
    if value_type in (6, 7):  # vaString, vaIdent
        return _text(cursor.short_bytes())
    if value_type in (12, 20):  # vaLString, vaUTF8String
        size = _bounded_count(cursor.u32())
        raw = cursor.read(size)
        return _text(raw, encoding="utf-8" if value_type == 20 else "cp1252")
    if value_type in (18, 22):  # vaWString, vaUString
        units = _bounded_count(cursor.u32(), unit=2)
        return cursor.read(units * 2).decode("utf-16le", errors="replace")
    raise DfmFormatError(f"value type {value_type} is not a string")


def _read_value(cursor: Cursor, *, depth: int = 0) -> Any:
    if depth > MAX_DEPTH:
        raise DfmFormatError("DFM value nesting exceeds limit")
    value_type = cursor.u8()
    if value_type in (0, 13):  # vaNull, vaNil
        return None
    if value_type == 1:  # vaList
        values = []
        while cursor.peek_u8() != 0:
            values.append(_read_value(cursor, depth=depth + 1))
        cursor.u8()
        return values
    if value_type == 2:
        return cursor.i8()
    if value_type == 3:
        return cursor.i16()
    if value_type == 4:
        return cursor.i32()
    if value_type == 5:  # 80-bit extended on Win32
        return {"extended_hex": cursor.read(10).hex()}
    if value_type in (6, 7, 12, 18, 20, 22):
        return _read_string_value(cursor, value_type)
    if value_type == 8:
        return False
    if value_type == 9:
        return True
    if value_type == 10:  # vaBinary
        size = _bounded_count(cursor.u32())
        raw = cursor.read(size)
        return {"binary_size": size, "binary_sha256": sha256(raw).hexdigest()}
    if value_type == 11:  # vaSet
        values = []
        while True:
            value = _text(cursor.short_bytes())
            if not value:
                return values
            values.append(value)
    if value_type == 14:  # vaCollection
        items = []
        while cursor.peek_u8() != 0:
            order = None
            if cursor.peek_u8() in (2, 3, 4):
                order = _read_value(cursor, depth=depth + 1)
            if cursor.u8() != 1:  # collection item is encoded as vaList
                raise DfmFormatError("collection item does not start with vaList")
            properties = {}
            while cursor.peek_u8() != 0:
                name = _text(cursor.short_bytes())
                if not name:
                    raise DfmFormatError("empty collection property name")
                properties[name] = _read_value(cursor, depth=depth + 1)
            cursor.u8()
            items.append({"order": order, "properties": properties})
        cursor.u8()
        return items
    if value_type == 15:
        return struct.unpack("<f", cursor.read(4))[0]
    if value_type in (16, 17):  # vaCurrency, vaDate
        return {"raw_u64": cursor.u64()}
    if value_type == 19:
        return cursor.i64()
    if value_type == 21:
        return struct.unpack("<d", cursor.read(8))[0]
    if value_type == 23:
        return cursor.u64()
    raise DfmFormatError(
        f"unsupported Delphi value type {value_type} at offset {cursor.offset - 1}"
    )


def _read_component_header(cursor: Cursor, *, version: int) -> tuple[str, str]:
    if cursor.peek_u8() & 0xF0 == 0xF0:
        flags = cursor.u8() & 0x0F
        if flags & 0x02:  # ffChildPos
            position_type = cursor.u8()
            if position_type == 2:
                cursor.i8()
            elif position_type == 3:
                cursor.i16()
            elif position_type == 4:
                cursor.i32()
            else:
                raise DfmFormatError("invalid ffChildPos value")
    if version == 1:
        class_name = _read_string_value(cursor, cursor.u8())
        class_name = class_name.rsplit(".", maxsplit=1)[-1]
    else:
        class_name = _text(cursor.short_bytes())
    component_name = _text(cursor.short_bytes())
    if not class_name:
        raise DfmFormatError("component has an empty class name")
    return class_name, component_name


def parse_binary_dfm(raw: bytes) -> dict[str, Any]:
    """Parse one TPF0/TPF1 stream into a sanitized component inventory."""
    if raw[:4] not in (b"TPF0", b"TPF1"):
        raise DfmFormatError("missing TPF0/TPF1 signature")
    version = raw[3] - ord("0")
    cursor = Cursor(raw, 4)
    components: list[dict[str, str]] = []
    events: list[dict[str, str]] = []
    path_counts: dict[str, int] = {}

    def component(parent_path: str, depth: int) -> tuple[str, str]:
        if depth > MAX_DEPTH:
            raise DfmFormatError("DFM component nesting exceeds limit")
        class_name, component_name = _read_component_header(cursor, version=version)
        path_segment = component_name or f"<{class_name}>"
        base_path = f"{parent_path}/{path_segment}" if parent_path else path_segment
        path_counts[base_path] = path_counts.get(base_path, 0) + 1
        component_path = (
            base_path
            if path_counts[base_path] == 1
            else f"{base_path}[{path_counts[base_path]}]"
        )
        components.append(
            {"path": component_path, "class": class_name, "name": component_name}
        )
        while cursor.peek_u8() != 0:
            property_name = _text(cursor.short_bytes())
            if not property_name:
                raise DfmFormatError("empty property name")
            value = _read_value(cursor, depth=depth + 1)
            if property_name.casefold().startswith("on") and isinstance(value, str) and value:
                events.append(
                    {
                        "component_path": component_path,
                        "property": property_name,
                        "handler": value,
                    }
                )
        cursor.u8()
        while cursor.peek_u8() != 0:
            component(component_path, depth + 1)
        cursor.u8()
        return class_name, component_name

    root_class, root_name = component("", 0)
    if cursor.remaining:
        raise DfmFormatError(f"{cursor.remaining} trailing bytes after root component")
    return {
        "root_class": root_class,
        "root_name": root_name,
        "components": components,
        "event_bindings": events,
    }


def _entry_name(entry: Any) -> str:
    return str(entry.name) if entry.name is not None else str(entry.struct.Id)


def _resource_leaves(entry: Any) -> list[Any]:
    directory = getattr(entry, "directory", None)
    if directory is None:
        return [entry] if hasattr(entry, "data") else []
    leaves: list[Any] = []
    for child in directory.entries:
        leaves.extend(_resource_leaves(child))
    return leaves


def _version_strings(pe: Any) -> dict[str, str]:
    values: dict[str, str] = {}
    for group in getattr(pe, "FileInfo", []):
        for item in group:
            if item.Key == b"StringFileInfo":
                for table in item.StringTable:
                    for key, value in table.entries.items():
                        values[_text(key)] = _text(value)
    return values


def _map_bound_forms(path: Path) -> list[str]:
    text = path.read_text(encoding="cp1252")
    marker = "Bound resource files"
    if marker not in text:
        raise ValueError("map file has no Bound resource files section")
    section = text.split(marker, maxsplit=1)[1].split("Program entry point", maxsplit=1)[0]
    forms = {
        PureWindowsPath(line.strip()).stem.upper()
        for line in section.splitlines()
        if line.strip().casefold().endswith(".dfm")
    }
    return sorted(forms)


def _canonical_form_name(name: str) -> str:
    return re.sub(r"^CIS_", "", name.upper())


def extract(executable: Path, map_path: Path) -> dict[str, Any]:
    try:
        import pefile
    except ImportError as exc:  # pragma: no cover - dependency diagnostic
        raise SystemExit("install the research extra to provide pefile") from exc

    executable_raw = executable.read_bytes()
    map_raw = map_path.read_bytes()
    pe = pefile.PE(data=executable_raw, fast_load=False)
    version_strings = _version_strings(pe)
    product_version = version_strings.get("ProductVersion")
    if product_version != TARGET_PRODUCT_VERSION:
        raise ValueError(
            f"expected Toolkit {TARGET_PRODUCT_VERSION}, found {product_version!r}"
        )

    bound_forms = _map_bound_forms(map_path)
    bound_canonical = {_canonical_form_name(name) for name in bound_forms}
    rcdata_entry = next(
        (
            entry
            for entry in pe.DIRECTORY_ENTRY_RESOURCE.entries
            if _entry_name(entry) == "10"
        ),
        None,
    )
    if rcdata_entry is None:
        raise ValueError("executable has no RT_RCDATA resources")

    resources = []
    opaque_count = 0
    parse_errors = []
    for entry in sorted(rcdata_entry.directory.entries, key=_entry_name):
        resource_name = _entry_name(entry)
        for language_index, leaf in enumerate(_resource_leaves(entry)):
            data = leaf.data.struct
            raw = pe.get_data(data.OffsetToData, data.Size)
            record_name = (
                resource_name
                if language_index == 0
                else f"{resource_name}@{language_index}"
            )
            if raw[:4] not in (b"TPF0", b"TPF1"):
                opaque_count += 1
                continue
            try:
                parsed = parse_binary_dfm(raw)
            except DfmFormatError as exc:
                parse_errors.append({"resource_name": record_name, "error": str(exc)})
                continue
            parsed.update(
                {
                    "resource_name": record_name,
                    "resource_sha256": sha256(raw).hexdigest(),
                    "size": len(raw),
                    "map_bound": _canonical_form_name(resource_name)
                    in bound_canonical,
                }
            )
            resources.append(parsed)

    if parse_errors:
        names = ", ".join(row["resource_name"] for row in parse_errors[:8])
        raise DfmFormatError(
            f"failed to parse {len(parse_errors)} form resources: {names}"
        )
    components = sum(len(row["components"]) for row in resources)
    events = sum(len(row["event_bindings"]) for row in resources)
    return {
        "schema_version": SCHEMA_VERSION,
        "target": "Schneider Electric C-Bus Toolkit 1.18.0",
        "purpose": "Sanitized executable dialog, control, and event census; vendor binaries are not redistributed.",
        "sources": {
            "executable": {
                "sha256": sha256(executable_raw).hexdigest(),
                "size": len(executable_raw),
                "file_version": version_strings.get("FileVersion"),
                "product_version": product_version,
            },
            "map": {"sha256": sha256(map_raw).hexdigest(), "size": len(map_raw)},
        },
        "counts": {
            "map_bound_forms": len(bound_forms),
            "parsed_form_resources": len(resources),
            "opaque_rcdata_resources": opaque_count,
            "components": components,
            "event_bindings": events,
            "parse_errors": 0,
        },
        "map_bound_form_names": bound_forms,
        "resources": sorted(resources, key=lambda row: row["resource_name"]),
    }


def render(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--map", dest="map_path", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1]
        / "docs"
        / "toolkit-executable-surface.json",
    )
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    content = render(extract(args.executable, args.map_path))
    if args.check:
        if not args.output.is_file() or args.output.read_text(encoding="utf-8") != content:
            raise SystemExit(f"stale executable surface: {args.output}")
        print(f"current: {args.output}")
    else:
        args.output.write_text(content, encoding="utf-8")
        print(f"generated: {args.output}")


if __name__ == "__main__":
    main()
