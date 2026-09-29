"""Independent model of C-Gate 3.4 CONVERTUNIT database parameter mapping.

C-Gate converts a database unit by rebuilding it for the destination
specification. Admission uses a fixed source-to-target type table. Each target
parameter, in target specification order, then takes one of three values:

* the result of the rule list in the first matching ``ConvertUnitMappingTable``
  pair for that target name, when the source unit has stored PP values;
* otherwise the source unit's same-named stored PP value; or
* otherwise the target session value for a declared default.

Empty results are omitted from the rebuilt unit. Rules receive the source PP
strings exactly as stored and the unchanged target baseline, not the result of
an earlier rule. A same-type conversion copies the stored PP list verbatim.

The behavior is modeled from the supplied C-Gate classes ``dg``, ``pv`` and
``ConvertUnitRulesUtility`` plus the supplied mapping table and unit
specifications. It does not read C-Gate responses. The mapping table and unit
specifications are private vendor inputs and are never bundled.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from pathlib import Path
import re
from types import MappingProxyType
from typing import Iterable, Mapping, Sequence

from .unitspec import ParameterSpec, UnitCatalog, UnitSpec, UnitSpecError, _read_xml


class MappingError(ValueError):
    """The table or a rule cannot be evaluated the way C-Gate would complete it."""


# Static admission table from C-Gate 3.4.0.2001 class dg. Identity is also
# admitted by the same method. Comparison is case-insensitive.
COMPATIBLE_TARGETS = MappingProxyType({
    "DIMDU4": ("DIMDN8", "DIMDN8F", "DIMDN4", "DIMDN4F", "DIMDD4"),
    "DIMDN4F": ("DIMDU4",),
    "DIMDN4": ("DIMDU4", "DIMDN8", "DIMDD4"),
    "DIMDN8F": ("DIMDU4",),
    "DIMDN8": ("DIMDU4", "DIMDD8"),
    "RELDN4": ("RELDN4A",),
    "RELDN8": ("RELDN8A",),
    "RELDN12": ("RELDN16A",),
})
RULES = frozenset({
    "extractByte", "oneBitToThreeBitAndInverse", "mapToIndex", "mapThreeParamToOne",
    "channelProperties", "setDefaultValue", "resetToZero", "mapTo2Byte", "changePropertyName",
    "convertDimChannelProfileSelection", "convertDimChProfileData", "convertErrorReportInterval",
    "mapInterlockMask", "mapInterlockPriority", "mapRestrikeDelay", "mapTurnOnThreshold",
    "toggleGlobalParam",
})
# C-Gate regenerates numbered output channels only for these catalogue classes.
CHANNEL_CLASSES = frozenset({"CBus3DinDigDimmerUnit", "CBus3DinRelayUnit"})
CATALOG_SERIAL_NUMBER = "00000000.0000"


def admitted_pairs() -> tuple[tuple[str, str], ...]:
    """Every non-identity pair the native admission table accepts."""
    return tuple((source, target) for source, targets in COMPATIBLE_TARGETS.items() for target in targets)


def compatible(source_type: str, target_type: str) -> bool:
    if source_type.lower() == target_type.lower():
        return True
    targets = {key.lower(): value for key, value in COMPATIBLE_TARGETS.items()}.get(source_type.lower(), ())
    # dg performs a case-sensitive List.contains after the case-insensitive key lookup.
    return target_type in targets


@dataclass(frozen=True)
class Rule:
    name: str
    param1: str | None = None
    param2: str | None = None
    param3: str | None = None


@dataclass(frozen=True)
class Pair:
    new: str
    old: tuple[str, ...]
    rules: tuple[Rule, ...]


@dataclass(frozen=True)
class Conversion:
    index: int | None
    old_type: str
    new_type: str
    pairs: tuple[Pair, ...]


class MappingTable:
    def __init__(self, conversions: Sequence[Conversion], *, sha256: str | None = None) -> None:
        self.conversions = tuple(conversions)
        self.sha256 = sha256

    @classmethod
    def load(cls, path: str | Path) -> "MappingTable":
        path = Path(path)
        try:
            root = _read_xml(path)
        except UnitSpecError as error:
            raise MappingError(str(error)) from error
        return cls.parse_root(root, sha256=hashlib.sha256(path.read_bytes()).hexdigest())

    @classmethod
    def parse_root(cls, root, *, sha256=None) -> "MappingTable":
        if root.tag != "UnitConversions":
            raise MappingError("Expected a UnitConversions mapping table")
        conversions = []
        for element in root:
            if element.tag != "UnitConversion":
                continue
            index = element.get("index")
            old_type, new_type = element.findtext("Unit_type_Old"), element.findtext("Unit_type_New")
            if not old_type or not new_type:
                raise MappingError("Each UnitConversion requires old and new unit types")
            pairs = []
            for parameters in element.findall("Parameters"):
                for pair in parameters.findall("Pair"):
                    new, old = pair.get("new"), pair.get("old")
                    if not new or old is None:
                        raise MappingError("Each Pair requires new and old attributes")
                    rules = []
                    for container in pair.findall("rules"):
                        for rule in container.findall("rule"):
                            name = (rule.text or "").strip()
                            if name not in RULES:
                                raise MappingError(f"Unsupported conversion rule {name!r}")
                            rules.append(Rule(name, rule.get("param1"), rule.get("param2"), rule.get("param3")))
                    pairs.append(Pair(new, tuple(old.split(",")), tuple(rules)))
            conversions.append(Conversion(int(index) if index and index.isdigit() else None,
                                          old_type.strip(), new_type.strip(), tuple(pairs)))
        return cls(conversions, sha256=sha256)

    def find(self, source_type: str, target_type: str) -> Conversion | None:
        """Return the first matching entry; C-Gate ignores later duplicates."""
        for conversion in self.conversions:
            if conversion.old_type.lower() == source_type.lower() and conversion.new_type.lower() == target_type.lower():
                return conversion
        return None


# -- Java string helpers ---------------------------------------------------

def _split(value: str) -> list[str]:
    """Java String.split(" "): keep leading empties, drop trailing empties."""
    if value == "":
        return [""]
    parts = value.split(" ")
    while parts and parts[-1] == "":
        parts.pop()
    return parts


def _int(value: str | None, radix: int = 10) -> int:
    """Java Integer.parseInt: no prefixes, no surrounding whitespace."""
    if value is None or not re.fullmatch(r"[+-]?[0-9A-Za-z]+", value):
        raise MappingError(f"Rule parameter {value!r} is not a Java integer")
    try:
        return int(value, radix)
    except ValueError as error:
        raise MappingError(f"Rule parameter {value!r} is not a base-{radix} integer") from error


def _decode(value: str) -> int:
    """Java Integer.decode for decimal, 0x/0X/#, and leading-zero octal."""
    match = re.fullmatch(r"([+-]?)(0[xX]|#|0(?=[0-7]))?([0-9A-Fa-f]+)", value)
    if not match:
        raise ValueError(value)
    sign, prefix, digits = match.groups()
    radix = 16 if prefix in ("0x", "0X", "#") else 8 if prefix == "0" else 10
    return (-1 if sign == "-" else 1) * int(digits, radix)


def _hex(number: int) -> str:
    """Java Integer.toHexString, including two's-complement negatives."""
    return format(number & 0xFFFFFFFF, "x")


def _convert_to_hex(text: str) -> str:
    if len(text) == 2:
        return "0x" + text + " 0x0"
    if len(text) >= 3:
        return "0x" + text[-2:] + " 0x" + text[:-2]
    return text


def _hex_to_int(text: str) -> int:
    if text.startswith(("0x", "0X")):
        return _int(text[2:], 16)
    return 0


def _at(values: Sequence[str], index: int) -> str:
    if not 0 <= index < len(values):
        raise MappingError("Rule index is outside the stored value")
    return values[index]


def _first_values(old: Sequence[str]) -> list[str]:
    return _split(old[0]) if old else []


def _source_value(name: str, source: Sequence[tuple[str, str]]) -> str | None:
    for key, value in source:
        if key.lower() == name.lower():
            return value
    return None


# -- ConvertUnitRulesUtility --------------------------------------------------

def _extract_byte(rule, old, baseline, source):
    values = _first_values(old)
    if rule.param1 is None:
        raise MappingError("extractByte requires param1")
    if rule.param1 == "":
        return ""
    index = _int(rule.param1)
    return values[index] if values and len(values) > index else baseline


def _one_bit_to_three_bit_and_inverse(rule, old, baseline, source):
    values = _first_values(old)
    target = _split(baseline)
    if rule.param1 is None or rule.param2 is None:
        raise MappingError("oneBitToThreeBitAndInverse requires param1 and param2")
    selected = ""
    if rule.param1 != "" and values:
        selected = _at(values, _int(rule.param1))
    bit = _int(selected[2:], 2) if selected != "" else 0
    position = _int(rule.param2) if rule.param2 != "" else 0
    if not 0 <= position < len(target):
        raise MappingError("Rule index is outside the target value")
    target[position] = "0" if bit == 1 else "1"
    return " ".join(target)


def _map_to_index(rule, old, baseline, source):
    values = _split(old[0]) if old else []
    target = _split(baseline)
    source_index, target_index = _int(rule.param1), _int(rule.param2)
    if values and len(values) > source_index and len(target) > target_index:
        target[target_index] = values[source_index]
    return " ".join(target)


def _map_three_param_to_one(rule, old, baseline, source):
    index = _int(rule.param1)
    target = _split(baseline)
    for position, value in enumerate(old):
        selected = _at(_split(value), index)
        if len(selected) < 3 or position >= len(target):
            raise MappingError("mapThreeParamToOne input is shorter than C-Gate requires")
        target[position] = selected[2]
    return " ".join(target)


def _channel_properties(rule, old, baseline, source):
    values = _first_values(old)
    target = _split(baseline)
    if len(values) > len(target):
        return " ".join(values[:len(target)])
    if len(values) < len(target):
        return " ".join(values + target[len(values):])
    return ""  # Native equal-length result is empty, so the PP is omitted.


def _set_default_value(rule, old, baseline, source):
    return baseline


def _reset_to_zero(rule, old, baseline, source):
    values = _first_values(old)
    target = _split(baseline)
    if len(values) > len(target):
        return " ".join(["0x0"] * len(target))
    if len(values) < len(target):
        return " ".join(["0x0"] * len(values) + target[len(values):])
    return ""


def _map_to_2_byte(rule, old, baseline, source):
    values = _first_values(old)
    if rule.param1 is None:
        raise MappingError("mapTo2Byte requires param1")
    if rule.param1 == "":
        return ""
    index = _int(rule.param1)
    if not values or len(values) <= index:
        return baseline
    selected = values[index]
    digits = selected[2:] if selected.startswith(("0x", "0X")) else selected
    number = _int(digits, 16)
    if number >= 60:
        return _convert_to_hex(_hex((number - 60) * 10 + 60))
    return selected + " 0x0"


def _change_property_name(rule, old, baseline, source):
    values = _first_values(old)
    return values[0] if values else baseline


def _convert_dim_channel_profile_selection(rule, old, baseline, source):
    if not old:
        return "0 0 0"
    values = _split(old[0])
    index = _int(rule.param1)
    try:
        selected = _decode(_at(values, index))
    except ValueError:
        selected = 0
    if selected != 1:
        return baseline
    return {0: "0 0 1", 1: "1 0 1", 2: "0 1 1", 3: "1 1 1"}.get(index, "")


def _convert_dim_ch_profile_data(rule, old, baseline, source):
    index = _int(rule.param1)
    selector = _source_value(rule.param2 or "", source)
    if selector is None or _at(_split(selector), index).lower() != "0x1":
        return baseline
    if (rule.param3 or "").lower() != "oldunitvalue":
        if rule.param3 is None:
            # A null method result is rejected by C-Gate's rule dispatcher.
            raise MappingError("convertDimChProfileData requires param3")
        return rule.param3
    if not old:
        return baseline
    text = old[0][2:] if old[0].startswith(("0x", "0X")) else old[0]
    # Java Math.round(double): floor(x + 0.5).
    scaled = math.floor(_int(text, 16) / 62.195 * 100.0 + 0.5)
    return _convert_to_hex(_hex(scaled))


def _convert_error_report_interval(rule, old, baseline, source):
    values = _first_values(old)
    if not values:
        return baseline
    return {"0x1": "0x1", "0x2": "0x1", "0x3": "0x1", "0x4": "0x1", "0x5": "0x1",
            "0x6": "0x2", "0x7": "0x4"}.get(values[0], "")


_INTERLOCK_MASKS = {"0x0": "0x0 0x0", "0x1": "0x3 0x0", "0x2": "0x7 0x0", "0x3": "0xf 0x0",
                    "0x4": "0x1f 0x0", "0x5": "0x3f 0x0", "0x6": "0x7f 0x0", "0x7": "0xff 0x0"}


def _map_interlock_mask(rule, old, baseline, source):
    values = _first_values(old)
    channel = _int(rule.param2)
    if not values:
        return baseline
    count = _int(values[0][2:], 16)
    if channel > count:
        return baseline
    return _INTERLOCK_MASKS.get(values[0], "")


def _map_interlock_priority(rule, old, baseline, source):
    values = _first_values(old)
    if not values:
        return baseline
    count = _int(values[0][2:], 16)
    highest, channel = _int(rule.param1), _int(rule.param2)
    if channel > count:
        return baseline
    number = highest - count + channel
    bits = format(number & 0xFFFFFFFF, "b") if number < 0 else format(number, "b")
    return " ".join(bits.rjust(4, "0")[::-1])


def _map_restrike_delay(rule, old, baseline, source):
    delay = _source_value(rule.param2 or "", source)
    values = _first_values(old)
    if rule.param1 is None:
        raise MappingError("mapRestrikeDelay requires param1")
    if rule.param1 != "":
        index = _int(rule.param1)
        if values and len(values) > index and _hex_to_int(values[index]) == 1 and delay is not None:
            return _convert_to_hex(_hex(_hex_to_int(delay) * 10))
    return baseline


def _map_turn_on_threshold(rule, old, baseline, source):
    values = _first_values(old)
    return _at(values, _int(rule.param1)) if values else baseline


def _toggle_global_param(rule, old, baseline, source):
    values = _first_values(old)
    if not values:
        return baseline
    return "0" if values[0].lower() == "1" else "1"


_RULES = MappingProxyType({
    "extractByte": _extract_byte,
    "oneBitToThreeBitAndInverse": _one_bit_to_three_bit_and_inverse,
    "mapToIndex": _map_to_index,
    "mapThreeParamToOne": _map_three_param_to_one,
    "channelProperties": _channel_properties,
    "setDefaultValue": _set_default_value,
    "resetToZero": _reset_to_zero,
    "mapTo2Byte": _map_to_2_byte,
    "changePropertyName": _change_property_name,
    "convertDimChannelProfileSelection": _convert_dim_channel_profile_selection,
    "convertDimChProfileData": _convert_dim_ch_profile_data,
    "convertErrorReportInterval": _convert_error_report_interval,
    "mapInterlockMask": _map_interlock_mask,
    "mapInterlockPriority": _map_interlock_priority,
    "mapRestrikeDelay": _map_restrike_delay,
    "mapTurnOnThreshold": _map_turn_on_threshold,
    "toggleGlobalParam": _toggle_global_param,
})
assert set(_RULES) == RULES


def apply_rules(rules: Iterable[Rule], old: Sequence[str], baseline: str,
                source: Sequence[tuple[str, str]]) -> str | None:
    """Run each rule against the same inputs; the last rule's result wins."""
    result = None
    for rule in rules:
        try:
            result = _RULES[rule.name](rule, list(old), baseline, source)
        except (IndexError, ValueError) as error:
            if isinstance(error, MappingError):
                raise
            raise MappingError(f"{rule.name} cannot be evaluated: {error}") from error
    return result


# -- Target baseline ----------------------------------------------------------

def render_value(parameter: ParameterSpec, value: str) -> str:
    """C-Gate's PP GET rendering of one value: 0x-hex integers and bit digits.

    Native database PP strings are already rendered this way. A value that
    does not parse under the specification grammar is returned unchanged.
    """
    if parameter.type in ("int", "long", "bit"):
        checked = parameter.validate_value(value, allow_partial=True)
        if checked["parsed"] is None or any("numeric value" in error or "Invalid integer" in error
                                            for error in checked["errors"]):
            return value
        numbers = checked["parsed"] if isinstance(checked["parsed"], list) else [checked["parsed"]]
        return " ".join(str(number) if parameter.type == "bit" else "0x" + _hex(number) for number in numbers)
    if parameter.type == "sixbit":
        return value.upper().ljust(parameter.array_size)
    return value


def session_default(parameter: ParameterSpec) -> str:
    """C-Gate's PP GET rendering of a declared default, or "" when undeclared."""
    default = parameter.default
    if default is None or default == "":
        return ""
    if parameter.type in ("int", "long", "bit") and not parameter.validate_value(default)["valid"]:
        raise MappingError(f"Invalid declared default for {parameter.name}")
    return render_value(parameter, default)


def render_parameters(spec: UnitSpec, values: Sequence[tuple[str, str]]) -> list[tuple[str, str]]:
    """Render stored PP strings the way native C-Gate stores them."""
    return [(name, render_value(spec.parameters[name], value) if name in spec.parameters else value)
            for name, value in values]


def convert_parameters(table: MappingTable, source_type: str, source: Sequence[tuple[str, str]],
                       target_spec: UnitSpec, target_type: str | None = None) -> list[tuple[str, str]]:
    """Predict the ordered PP list C-Gate stores on the converted unit."""
    target_type = target_type or target_spec.unit_type
    source = [(str(name), str(value)) for name, value in source]
    if source_type.lower() == target_type.lower():
        return list(source)
    conversion = table.find(source_type, target_type)
    pairs = conversion.pairs if conversion else ()
    result = []
    for name, parameter in target_spec.parameters.items():
        baseline = session_default(parameter)
        pair = next((item for item in pairs if item.new.lower() == name.lower()), None)
        if pair is not None and source:
            old = [value for value in (_source_value(key, source) for key in pair.old) if value is not None]
            value = apply_rules(pair.rules, old, baseline, source)
        else:
            value = _source_value(name, source)
            if value is None or value == "":
                value = baseline
        if value:
            result.append((name, value))
    return result


# -- Database identity ----------------------------------------------------------

def catalog_default(catalog: UnitCatalog, target_type: str, catalog_number: str) -> dict:
    """Default catalogue revision for a catalogue-mode (mode 1) destination."""
    records = [record for record in catalog.records if record["default"]
               and record["catalog_number"].lower() == catalog_number.lower()]
    typed = [record for record in records if record["unit_type"].lower() == target_type.lower()]
    selected = typed or records
    if not selected:
        raise MappingError("Catalogue number has no default firmware revision")
    record = selected[0]
    return {"firmware": record["minimum_version"], "spec_filename": record["spec_filename"],
            "class_name": record["revision"].get("ClassName", "")}


def output_channels(catalog: UnitCatalog, catalog_number: str, class_name: str) -> list[dict[str, str]]:
    """Numbered channels regenerated for C-Bus 3 DIN destinations."""
    if class_name not in CHANNEL_CLASSES:
        return []
    count = _catalog_output_count(catalog, catalog_number)
    return [{"Address": str(number), "TagName": f"Channel{number}"} for number in range(1, count + 1)]


def _catalog_output_count(catalog: UnitCatalog, catalog_number: str) -> int:
    counts = getattr(catalog, "output_counts", None)
    if counts is None:
        raise MappingError("Catalogue output counts are unavailable")
    return counts.get(catalog_number.upper(), 0)


def load_catalog(path: str | Path) -> UnitCatalog:
    """Load cbusunits.xml, retaining each catalogue number's OutputCount."""
    catalog = UnitCatalog.load(path)
    root = _read_xml(Path(path))
    counts = {}
    for unit in root.iter("Unit"):
        number = unit.findtext("CatalogNumber")
        output = unit.findtext("OutputCount")
        if number and output and output.strip().isdigit():
            counts.setdefault(number.upper(), int(output))
    catalog.output_counts = counts
    return catalog


def expected_identity(*, mode: int, source: Mapping[str, str], destination: Mapping[str, str] | None,
                      target_type: str, catalog_number: str | None, catalog: UnitCatalog) -> dict:
    """Unit scalar fields and channels C-Gate writes on the rebuilt unit."""
    if mode == 1:
        revision = catalog_default(catalog, target_type, catalog_number)
        identity = {key: source.get(key) for key in ("TagName", "UnitName", "Description", "Address")}
        identity.update(SerialNumber=CATALOG_SERIAL_NUMBER, FirmwareVersion=revision["firmware"],
                        CatalogNumber=catalog_number, UnitType=target_type)
    elif mode == 2 and destination is not None:
        catalog_number = destination.get("CatalogNumber")
        identity = {key: destination.get(key) for key in ("TagName", "UnitName", "Description", "Address", "SerialNumber")}
        identity.update(FirmwareVersion=destination.get("FirmwareVersion"), CatalogNumber=catalog_number,
                        UnitType=destination.get("UnitType"))
        # Channel regeneration uses the class of the catalogue's default revision.
        revision = catalog_default(catalog, identity["UnitType"] or "", catalog_number or "")
    else:
        raise MappingError("Unsupported conversion mode")
    identity["DeviceName"] = source.get("DeviceName")
    identity = {key: value for key, value in identity.items() if value is not None}
    identity["OutputChannels"] = output_channels(catalog, catalog_number or "", revision["class_name"])
    return identity
