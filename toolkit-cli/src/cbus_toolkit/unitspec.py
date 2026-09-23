"""Read user-supplied C-Gate unit specifications and catalogues.

Include precedence and firmware comparisons follow the C-Gate 3.4.0 loader.
Validation is intentionally strict: values are never silently masked, truncated
or reset to defaults. This module does not encode or program device memory.
Vendor files are read from an explicit directory and are not bundled here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any, Mapping
import xml.etree.ElementTree as ET
from xml.parsers import expat


_COPYRIGHT = b"(C) CLIPSAL INTEGRATED SYSTEMS 2003 all rights reserved"
MAX_SPEC_BYTES = 8 * 1024 * 1024


class UnitSpecError(ValueError):
    """A malformed or ambiguous specification, reference or value."""


def _tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _children(element: ET.Element, name: str) -> list[ET.Element]:
    return [child for child in element if _tag(child) == name]


def _value(element: ET.Element, name: str, default: str = "") -> str:
    children = _children(element, name)
    if len(children) > 1:
        raise UnitSpecError(f"Repeated scalar specification field {name!r}")
    return children[0].text or "" if children else default


def _integer(value: Any) -> int:
    if isinstance(value, bool):
        raise UnitSpecError("Boolean is not an integer parameter value")
    if isinstance(value, int):
        return value
    if not isinstance(value, str):
        raise UnitSpecError("Expected an integer value")
    text = value.strip()
    if not re.fullmatch(r"[+-]?(?:\$[0-9A-Fa-f]+|0[xX][0-9A-Fa-f]+|[0-9]+)", text):
        raise UnitSpecError(f"Invalid integer value {value!r}")
    sign = -1 if text.startswith("-") else 1
    text = text.lstrip("+-")
    return sign * int(text[1:] if text.startswith("$") else text, 16 if text.startswith("$") or text.lower().startswith("0x") else 10)


def _read_xml(path: Path) -> ET.Element:
    if path.stat().st_size > MAX_SPEC_BYTES:
        raise UnitSpecError("Specification exceeds the size limit")
    data = path.read_bytes()
    # Decrypted signed specs have one authenticated copyright line before XML.
    # Only that exact documented preamble is accepted, not arbitrary leading junk.
    if data.startswith(_COPYRIGHT + b"\n") or data.startswith(_COPYRIGHT + b"\r\n"):
        data = data.split(b"\n", 1)[1]
    def reject(*_args: Any) -> None:
        raise UnitSpecError("DTD/entity declarations are unsupported in specifications")
    checker = expat.ParserCreate()
    checker.StartDoctypeDeclHandler = reject
    try:
        checker.Parse(data, True)
        return ET.fromstring(data)
    except (expat.ExpatError, ET.ParseError) as exc:
        raise UnitSpecError(f"Invalid specification XML in {path.name}") from exc


def compare_versions(left: str, right: str) -> int:
    """C-Gate's numeric-component comparison (labels ignored, zero suffixes equal)."""
    def components(version: str) -> list[int]:
        cleaned = re.sub(r"[^0-9.]", "", version).rstrip(".")
        if not cleaned or any(not p for p in cleaned.split(".")):
            raise UnitSpecError(f"Invalid firmware version {version!r}")
        return [int(p) for p in cleaned.split(".")]
    first, second = components(left), components(right)
    count = max(len(first), len(second))
    first.extend([0] * (count - len(first)))
    second.extend([0] * (count - len(second)))
    return (first > second) - (first < second)


def version_matches(version: str, minimum: str = "", maximum: str = "") -> bool:
    if not version:
        raise UnitSpecError("Firmware version must not be blank")
    compare_versions(version, version)
    return (not minimum or compare_versions(version, minimum) >= 0) and (not maximum or compare_versions(version, maximum) <= 0)


def _pattern_matches(pattern: str, value: str) -> bool:
    # C-Gate matches everything after the first '*' by prefix, not shell globbing.
    return value.startswith(pattern.split("*", 1)[0]) if "*" in pattern else pattern == value


@dataclass(frozen=True)
class ParameterSpec:
    name: str
    type: str
    source: str
    fields: Mapping[str, str] = field(repr=False)
    tags: tuple[str, ...] = ()

    @property
    def description(self) -> str:
        return self.fields.get("Description", "")

    @property
    def default(self) -> str | None:
        return self.fields.get("DefaultValue")

    @property
    def array_size(self) -> int:
        return _integer(self.fields.get("ArraySize") or "1")

    @property
    def bit_size(self) -> int:
        return _integer(self.fields.get("BitSize") or "8")

    @property
    def address(self) -> int:
        return _integer(self.fields["Address"])

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "type": self.type, "source": self.source, "description": self.description, "address": self.address, "array_size": self.array_size, "bit_size": self.bit_size, "bit_address": _integer(self.fields.get("BitAddress") or "0"), "array_skip": _integer(self.fields.get("ArraySkip") or "0"), "protection": self.fields.get("Protection", ""), "program_method": self.fields.get("ProgramMethod"), "default": self.default, "tags": list(self.tags), "fields": dict(self.fields)}

    def validate_value(self, value: Any, *, allow_partial: bool = False) -> dict[str, Any]:
        """Check type, explicit ranges, width and length without changing a device.

        Full numeric arrays are required unless allow_partial=True. Short declared
        defaults are preserved separately and are not expanded by guessing.
        """
        errors: list[str] = []
        warnings: list[str] = []
        parsed: Any = None
        try:
            count, bits = self.array_size, self.bit_size
            if count < 1 or bits < 1 or bits > 64:
                raise UnitSpecError("Invalid ArraySize or BitSize in specification")
            if self.type in ("int", "long", "bit"):
                tokens = value.split() if isinstance(value, str) else value if isinstance(value, (list, tuple)) else [value]
                parsed = [_integer(token) for token in tokens]
                if not parsed or len(parsed) > count or (not allow_partial and len(parsed) != count):
                    raise UnitSpecError(f"Expected {'1 to ' if allow_partial else ''}{count} numeric value(s), got {len(parsed)}")
                minimum = _integer(self.fields["MinValue"]) if self.fields.get("MinValue", "").strip() else 0
                maximum = _integer(self.fields["MaxValue"]) if self.fields.get("MaxValue", "").strip() else ((1 << bits) - 1)
                if self.type == "bit":
                    minimum, maximum = max(0, minimum), min(1, maximum)
                if minimum > maximum:
                    raise UnitSpecError("Specification MinValue exceeds MaxValue")
                for index, number in enumerate(parsed):
                    if not minimum <= number <= maximum:
                        errors.append(f"Value {index} must be between {minimum} and {maximum}")
                    if number >= (1 << bits) or number < -(1 << (bits - 1)):
                        errors.append(f"Value {index} does not fit the declared {bits}-bit width")
                if len(parsed) < count:
                    warnings.append("Partial array: unspecified elements are not populated or inferred")
                if count == 1:
                    parsed = parsed[0]
            elif self.type in ("string", "sixbit"):
                if not isinstance(value, str):
                    raise UnitSpecError("Expected a text string")
                parsed = value
                if self.type == "sixbit":
                    candidate = value.upper()
                    if len(candidate) > 8:
                        errors.append("Sixbit text exceeds eight characters after uppercase conversion")
                    if any(ord(character) < 32 or ord(character) > 96 for character in candidate):
                        errors.append("Sixbit text contains a character outside the C-Gate character range")
                    if count != 8:
                        errors.append("Sixbit specification must have ArraySize 8")
                    if "?" in candidate:
                        warnings.append("C-Gate sixbit maps '?' and space to the same code")
                else:
                    if len(value) > count:
                        errors.append(f"String exceeds ArraySize {count}")
                    if any(ord(character) > 127 for character in value):
                        warnings.append("Non-ASCII string encoding is C-Gate platform-dependent; no byte encoding was performed")
                    if "\x00" in value:
                        errors.append("String contains an embedded null character")
            else:
                raise UnitSpecError(f"Unsupported parameter type {self.type!r}; no encoding is inferred")
        except (UnitSpecError, KeyError) as exc:
            errors.append(str(exc))
        return {"name": self.name, "valid": not errors, "errors": errors, "warnings": warnings, "parsed": parsed}


@dataclass(frozen=True)
class UnitSpec:
    filename: str
    metadata: Mapping[str, str]
    sources: tuple[str, ...]
    parameters: Mapping[str, ParameterSpec]
    overrides: tuple[dict[str, str], ...] = ()

    @property
    def unit_type(self) -> str:
        return self.metadata.get("Type", "").strip().strip('"')

    def get(self, name: str) -> ParameterSpec:
        try:
            return self.parameters[name]
        except KeyError as exc:
            raise UnitSpecError(f"Unknown parameter {name!r}") from exc

    def list_parameters(self, *, tags: list[str] | None = None) -> list[dict[str, Any]]:
        selected = {tag.lower() for tag in tags or []}
        return [parameter.as_dict() for parameter in self.parameters.values() if not selected or selected.intersection(tag.lower() for tag in parameter.tags)]

    def defaults(self) -> dict[str, str]:
        return {name: parameter.default for name, parameter in self.parameters.items() if parameter.default is not None}

    def validate_value(self, name: str, value: Any, *, allow_partial: bool = False) -> dict[str, Any]:
        return self.get(name).validate_value(value, allow_partial=allow_partial)

    def validate_defaults(self) -> list[dict[str, Any]]:
        return [parameter.validate_value(parameter.default, allow_partial=True) for parameter in self.parameters.values() if parameter.default is not None]

    def supports_version(self, version: str) -> bool:
        return version_matches(version, self.metadata.get("MinVersion", ""), self.metadata.get("MaxVersion", ""))

    def as_dict(self, *, include_parameters: bool = True) -> dict[str, Any]:
        output = {"filename": self.filename, "unit_type": self.unit_type, "metadata": dict(self.metadata), "sources": list(self.sources), "parameter_count": len(self.parameters), "overrides": list(self.overrides)}
        if include_parameters:
            output["parameters"] = self.list_parameters()
        return output


class UnitSpecStore:
    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory).resolve()
        if not self.directory.is_dir():
            raise UnitSpecError("Unit specification directory does not exist")

    def _path(self, filename: str) -> Path:
        if not filename or "\\" in filename or Path(filename).is_absolute():
            raise UnitSpecError("Specification filename must be relative to the specification directory")
        path = (self.directory / filename).resolve()
        if not path.is_relative_to(self.directory) or ".." in Path(filename).parts:
            raise UnitSpecError("Specification include escapes its directory")
        if not path.is_file():
            raise UnitSpecError(f"Specification file {filename!r} does not exist")
        return path

    def load(self, filename: str) -> UnitSpec:
        visited: set[Path] = set()
        sources: list[str] = []
        parameters: dict[str, ParameterSpec] = {}
        overrides: list[dict[str, str]] = []
        def visit(name: str) -> dict[str, str]:
            path = self._path(name)
            if path in visited:
                raise UnitSpecError(f"Specification {name!r} was included more than once (cycle or repeated include)")
            if len(visited) >= 128:
                raise UnitSpecError("Specification include limit exceeded")
            visited.add(path)
            root = _read_xml(path)
            if _tag(root) not in ("UnitSpecification", "UnitSpec"):
                raise UnitSpecError(f"{name!r} is not a unit specification")
            metadata = {_tag(child): child.text or "" for child in root if len(child) == 0 and _tag(child) not in ("Parameters", "Includes")}
            for includes in _children(root, "Includes"):
                for include in _children(includes, "Include"):
                    visit((include.text or "").strip())
            sources.append(name)
            for container in _children(root, "Parameters"):
                for element in _children(container, "Param"):
                    fields = {_tag(child): child.text or "" for child in element if _tag(child) != "Tag"}
                    name_value = _value(element, "Name").strip()
                    kind = _value(element, "Type").strip().lower()
                    if not name_value or not kind or not fields.get("Address"):
                        raise UnitSpecError(f"Parameter in {name!r} requires Name, Type and Address")
                    parameter = ParameterSpec(name_value, kind, name, fields, tuple((tag.text or "") for tag in _children(element, "Tag")))
                    # Parse structural numeric metadata now, leaving unexpected
                    # default/range contents visible for explicit validation.
                    if parameter.address < 0 or parameter.array_size < 1 or not 1 <= parameter.bit_size <= 64:
                        raise UnitSpecError(f"Invalid numeric parameter metadata for {name_value!r}")
                    for key in ("ArraySkip", "BitAddress"):
                        if _integer(fields.get(key) or "0") < 0:
                            raise UnitSpecError(f"Negative {key} for {name_value!r}")
                    if name_value in parameters:
                        overrides.append({"name": name_value, "previous_source": parameters[name_value].source, "source": name})
                    parameters[name_value] = parameter
            return metadata
        metadata = visit(filename)
        return UnitSpec(filename, metadata, tuple(sources), parameters, tuple(overrides))

    def list_specs(self) -> list[dict[str, Any]]:
        result = []
        for path in sorted(self.directory.glob("*.xml")):
            root = _read_xml(path)
            if _tag(root) not in ("UnitSpecification", "UnitSpec"):
                continue
            result.append({"filename": path.name, "unit_type": _value(root, "Type").strip().strip('"'), "description": _value(root, "Description"), "minimum_version": _value(root, "MinVersion"), "maximum_version": _value(root, "MaxVersion")})
        return result


class UnitCatalog:
    """Catalogue revision lookup retaining alternatives and nested subunit records."""
    def __init__(self, records: list[dict[str, Any]]) -> None:
        self.records = records

    @classmethod
    def load(cls, path: str | Path) -> UnitCatalog:
        root = _read_xml(Path(path))
        if _tag(root) != "CBusUnits":
            raise UnitSpecError("Expected a CBusUnits catalogue")
        records = []
        def visit(unit: ET.Element) -> None:
            subunits = _children(unit, "SubUnits")
            if subunits:
                for container in subunits:
                    for child in _children(container, "Unit"):
                        visit(child)
                return
            alternatives = [value for value in _value(unit, "AlternativeCatalogNumbers").split(";") if value]
            for revisions in _children(unit, "FirmwareRevisions"):
                for revision in _children(revisions, "Revision"):
                    metadata = {_tag(child): child.text or "" for child in revision}
                    records.append({"catalog_number": _value(unit, "CatalogNumber"), "alternatives": alternatives, "description": _value(unit, "Description"), "unit_type": metadata.get("UnitType", ""), "minimum_version": metadata.get("MinVersion", ""), "maximum_version": metadata.get("MaxVersion", ""), "spec_filename": metadata.get("UnitSpecName", ""), "default": metadata.get("IsDefault", "").lower() == "true", "revision": metadata})
        for units in _children(root, "Units"):
            for unit in _children(units, "Unit"):
                visit(unit)
        return cls(records)

    def match(self, *, unit_type: str | None = None, firmware: str | None = None, catalog_number: str | None = None) -> list[dict[str, Any]]:
        """Return all exact matching records, never fall back to another catalogue."""
        return [dict(record) for record in self.records if (unit_type is None or _pattern_matches(record["unit_type"], unit_type)) and (firmware is None or version_matches(firmware, record["minimum_version"], record["maximum_version"])) and (catalog_number is None or any(_pattern_matches(pattern, catalog_number) for pattern in [record["catalog_number"], *record["alternatives"]]))]

    def select_spec(self, *, unit_type: str, firmware: str, catalog_number: str | None = None) -> str:
        matches = self.match(unit_type=unit_type, firmware=firmware, catalog_number=catalog_number)
        filenames = {record["spec_filename"] for record in matches if record["spec_filename"]}
        if len(filenames) != 1:
            raise UnitSpecError("Catalogue selection does not identify exactly one unit specification")
        return filenames.pop()
