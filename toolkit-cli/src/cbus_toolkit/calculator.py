"""Offline reproduction of C-Gate 3.4 CALCULATOR TEST's database calculation.

Catalogue metadata is supplied by the user, never bundled. The calculation is
for database units and deliberately preserves native edges: exact catalogue and
UnitType casing, last duplicate/alias wins, prefix-star fallback, Burden's literal
"0" comparison, the KEYGL5/SENTEMP4 burden exclusions, and ignoring impedance
below 10 ohms. It does not model cable resistance or hardware measurements.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from pathlib import Path
from typing import Any, Iterable, Mapping
import xml.etree.ElementTree as ET

from .unitspec import _read_xml

MAX_UNITS = 10000


class CalculatorError(ValueError):
    """Invalid input or a network for which the native calculator cannot return results."""


@dataclass(frozen=True)
class CalculatorUnit:
    catalog_number: str | None
    unit_type: str
    burden: str | None = None
    switchable_supply_enabled: bool = False
    parameters: tuple[tuple[str, str], ...] = ()

    def __post_init__(self):
        if self.catalog_number is not None and not isinstance(self.catalog_number, str):
            raise CalculatorError("Catalogue number must be text or null")
        if not isinstance(self.unit_type, str) or not self.unit_type:
            raise CalculatorError("Unit type must be nonempty text")
        if self.burden is not None and not isinstance(self.burden, str):
            raise CalculatorError("Burden must be its native text value or null")
        if not isinstance(self.switchable_supply_enabled, bool):
            raise CalculatorError("Switchable supply enabled must be a boolean")
        try:
            parameters = tuple(self.parameters.items()) if isinstance(self.parameters, Mapping) else tuple(self.parameters)
        except TypeError as error:
            raise CalculatorError("Parameters must be ordered name/text-value pairs") from error
        if any(not isinstance(item, (tuple, list)) or len(item) != 2 or not all(isinstance(value, str) for value in item) for item in parameters):
            raise CalculatorError("Parameters must be ordered name/text-value pairs")
        if self.burden is not None and any(name in ("Burden", "HardwareBurdenMarker") for name, _value in parameters):
            raise CalculatorError("Supply burden once, either directly or in the ordered parameters")
        object.__setattr__(self, "parameters", tuple(tuple(item) for item in parameters))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> CalculatorUnit:
        unknown = set(value) - {"catalog_number", "unit_type", "burden", "switchable_supply_enabled", "parameters"}
        if unknown:
            raise CalculatorError("Unknown calculator unit fields: " + ", ".join(sorted(unknown)))
        try:
            return cls(**value)
        except TypeError as error:
            raise CalculatorError("Calculator units require catalogue number and unit type") from error

    def burden_enabled(self) -> bool:
        if self.unit_type.upper() in ("KEYGL5", "SENTEMP4"):
            return False
        if self.burden is not None:
            return self.burden != "0"
        for name, value in self.parameters:
            if name in ("Burden", "HardwareBurdenMarker"):
                return value != "0"
        return False


@dataclass(frozen=True)
class CalculatorLimits:
    min_impedance_ohms: int
    max_impedance_ohms: int
    max_supply_current_ma: int


@dataclass(frozen=True)
class CalculationResult:
    result: str
    current_supply_ma: int
    current_consumption_ma: int
    impedance_ohms: int
    exact_impedance_ohms: float
    units_calculated: int
    units_not_calculated: int
    limits: CalculatorLimits | None
    reasons: tuple[str, ...]
    catalog_sha256: str

    @property
    def passed(self) -> bool:
        return self.result == "OK"

    def native_values(self) -> dict[str, Any]:
        """The six fields returned by native CALCULATOR TEST, ready for comparison."""
        return {"result": self.result, "current_supply(mA)": self.current_supply_ma,
                "current_consumption(mA)": self.current_consumption_ma,
                "impedance(ohms)": float(self.impedance_ohms),
                "units_calculated": self.units_calculated,
                "units_not_calculated": self.units_not_calculated}


@dataclass(frozen=True)
class _ElectricalUnit:
    current_drawn: int
    current_supplied: int
    switchable_drawn: int
    switchable_supplied: int
    impedance: int
    switchable_declared: bool
    unit_types: tuple[str, ...]


def _number(element: ET.Element, field: str, default: int = 0) -> int:
    text = element.findtext(field)
    if text is None:
        return default
    try:
        value = int(text.strip(), 10)
    except (TypeError, ValueError) as error:
        raise CalculatorError(f"Invalid catalogue integer field {field}") from error
    if not -(1 << 31) <= value < (1 << 31):
        raise CalculatorError(f"Catalogue field {field} exceeds the native signed 32-bit range")
    return value


def _int32(value: int) -> int:
    return (value + (1 << 31)) % (1 << 32) - (1 << 31)


class CalculatorCatalog:
    """Native catalogue lookup and electrical totals, limited to 10,000 input units."""
    def __init__(self, entries: Mapping[str, _ElectricalUnit], limits: CalculatorLimits | None, sha256: str):
        self._entries = dict(entries)
        self.limits = limits
        self.sha256 = sha256
        # Native cW builds this set from the final alias/catalogue lookup map.
        self.switchable_unit_types = frozenset(unit_type for record in self._entries.values()
                                              if record.switchable_declared for unit_type in record.unit_types)

    @classmethod
    def load(cls, path: str | Path) -> CalculatorCatalog:
        path = Path(path)
        root = _read_xml(path)
        if root.tag != "CBusUnits":
            raise CalculatorError("Expected a CBusUnits catalogue")
        entries = {}
        def visit(unit: ET.Element):
            subunits = unit.find("SubUnits")
            if subunits is not None:
                for child in subunits.findall("Unit"):
                    visit(child)
                return
            record = _ElectricalUnit(
                _number(unit, "CurrentDrawn"), _number(unit, "CurrentSupplied"),
                _number(unit, "CurrentDrawnSwitchablePowerSupply"), _number(unit, "CurrentSuppliedSwitchablePowerSupply"),
                _number(unit, "Impedance"),
                unit.find("CurrentDrawnSwitchablePowerSupply") is not None and unit.find("CurrentSuppliedSwitchablePowerSupply") is not None,
                tuple(revision.findtext("UnitType", "") for revision in unit.findall("FirmwareRevisions/Revision")))
            catalog = unit.findtext("CatalogNumber", "")
            if catalog:
                entries[catalog] = record
            for alternative in unit.findtext("AlternativeCatalogNumbers", "").split(";"):
                if alternative:
                    entries[alternative] = record
        for unit in root.findall("Units/Unit"):
            visit(unit)
        calculator = root.find("Calculator")
        fields = ("MinImpedance", "MaxImpedance", "MaxSupplyCurrent")
        limits = CalculatorLimits(*(_number(calculator, name) for name in fields)) if calculator is not None and all(calculator.find(name) is not None for name in fields) else None
        return cls(entries, limits, hashlib.sha256(path.read_bytes()).hexdigest())

    def _lookup(self, catalog_number: str | None) -> _ElectricalUnit | None:
        if not catalog_number:
            return None
        record = self._entries.get(catalog_number)
        # Native only probes nonempty prefixes; a lone '*' is not a catch-all.
        while record is None and catalog_number:
            record = self._entries.get(catalog_number + "*")
            catalog_number = catalog_number[:-1]
        return record

    def calculate(self, units: Iterable[CalculatorUnit | Mapping[str, Any]]) -> CalculationResult:
        supply = consumption = known = unknown = 0
        conductance = 0.0
        for index, unit in enumerate(units):
            if index >= MAX_UNITS:
                raise CalculatorError(f"Calculator input exceeds the {MAX_UNITS}-unit limit")
            if isinstance(unit, Mapping):
                unit = CalculatorUnit.from_mapping(unit)
            if not isinstance(unit, CalculatorUnit):
                raise CalculatorError("Each calculator input must be a CalculatorUnit or mapping")
            record = self._lookup(unit.catalog_number)
            if record is None:
                unknown += 1
                continue
            if unit.unit_type in self.switchable_unit_types:
                if unit.switchable_supply_enabled:
                    supply = _int32(supply + record.switchable_supplied)
                else:
                    consumption = _int32(consumption + record.switchable_drawn)
            else:
                consumption = _int32(consumption + record.current_drawn)
                supply = _int32(supply + record.current_supplied)
            if record.impedance >= 10:
                conductance += 1.0 / record.impedance
            if unit.burden_enabled():
                conductance += 0.001
            known += 1
        if conductance == 0.0:
            error = CalculatorError("The field Impedance Accumulator cannot be zero.")
            error.units_calculated, error.units_not_calculated = known, unknown
            raise error
        impedance = 1.0 / conductance if conductance > 0 else 0.0
        reasons = []
        if self.limits is None:
            reasons.append("Catalogue calculator limits are missing or incomplete")
        else:
            if consumption > supply:
                reasons.append("Current consumption exceeds supply")
            if supply > self.limits.max_supply_current_ma:
                reasons.append("Supply current exceeds the catalogue maximum")
            if impedance < self.limits.min_impedance_ohms:
                reasons.append("Impedance is below the catalogue minimum")
            if impedance > self.limits.max_impedance_ohms:
                reasons.append("Impedance exceeds the catalogue maximum")
        if unknown:
            reasons.append("Some catalogue numbers were not found")
        return CalculationResult("FAILED" if reasons else "OK", supply, consumption,
                                 math.floor(impedance + 0.5), impedance, known, unknown,
                                 self.limits, tuple(reasons), self.sha256)


def calculate(catalog: str | Path, units: Iterable[CalculatorUnit | Mapping[str, Any]]) -> CalculationResult:
    return CalculatorCatalog.load(catalog).calculate(units)
