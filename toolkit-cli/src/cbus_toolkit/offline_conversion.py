"""Evidenced classic-key programming alignment, without replacing database units.

Toolkit 1.18 aligns its named programming attributes before replacing a unit.
This module implements the shared KEY1/KEY2/KEY4 configuration stage. It does
not model the frontend's conditional LearnedFlag transition or other families.
All retained target fields and physical-key changes are reported in each plan.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping
import xml.etree.ElementTree as ET

from .memory import MemoryCodec, MemoryError
from .programming import xml_text
from .unitspec import UnitSpec


class ConversionError(ValueError):
    pass


class ConversionApplyError(RuntimeError):
    def __init__(self, cause, rollback_errors=()):
        self.cause = cause
        self.rollback_errors = tuple(rollback_errors)
        super().__init__("Conversion alignment failed; " +
                         ("rollback had errors" if rollback_errors else "original parameters were restored") + ": " + str(cause))


CLASSIC_UNITS = MappingProxyType({"KEY1": 1, "KEY2": 2, "KEY4": 4})
# These are shared PP attributes registered by TCBusUnitCGateAgent,
# TCBusInputUnitCGateAgent, TCBusLearnUnitCGateAgent, and TCoreKeyInputCGateAgent.
# OID/type/firmware are not programming payload; identity and conditional flags
# are explicitly retained below. Source-only unknown fields are never copied.
COPY_PARAMETERS = (
    "Application", "UnitName", "LearnAnyApp", "LearnMode", "AreaGroupAddress",
    "StatusReportInterval", "GroupAddress", "DebounceTime", "IndicatorBrightness",
    "LongPressTime", "RampRate", "JPCommand", "SRCommand", "LPCommand", "LRCommand",
    "BlockAllocation", "IndicatorBlockAssignment", "IndicatorFunction",
    "TimerHighByte", "TimerLowByte", "TimerExpiryCommand", "EEPROMLevelStore",
    "LightIndex", "LightLevel", "LightLevelStore1", "LightLevelStore2",
)
RETAIN_REASONS = MappingProxyType({
    "UnitAddress": "destination address; replacement/readdress is a separate database operation",
    "Project": "destination project identity",
    "NetworkAddress": "destination network identity",
    "EEPROMChecksumActive": "runtime checksum state is not a Toolkit alignment attribute",
    "EEPROMChecksum": "checksum maintenance belongs to the backend/device",
    "EEPROMChecksumAlarm": "checksum alarm is not a Toolkit alignment attribute",
    "EEPROMLevelRecall": "not a registered classic alignment attribute",
    "LearnedFlag": "frontend transition requires original/current UI learned state; not modeled",
    "PatchEnable": "factory/protected target data",
    "CUSTYPE": "factory/protected target data",
})
# Fixed classic layouts: type, address, count, bits, bit offset, array skip.
_LAYOUTS = {
    "Application": ("int", 33, 2, 8, 0, 0), "UnitName": ("sixbit", 42, 8, 8, 0, 0),
    "LearnAnyApp": ("bit", 62, 1, 1, 4, 0), "LearnMode": ("bit", 62, 1, 1, 3, 0),
    "AreaGroupAddress": ("int", 67, 1, 8, 0, 0), "StatusReportInterval": ("int", 66, 1, 8, 0, 0),
    "GroupAddress": ("int", 80, 8, 8, 0, 0), "DebounceTime": ("int", 48, 1, 6, 0, 0),
    "IndicatorBrightness": ("int", 63, 1, 8, 0, 0), "LongPressTime": ("int", 49, 1, 6, 0, 0),
    "RampRate": ("int", 64, 2, 8, 0, 0), "JPCommand": ("int", 50, 4, 4, 4, 1),
    "SRCommand": ("int", 50, 4, 4, 0, 1), "LPCommand": ("int", 51, 4, 4, 4, 1),
    "LRCommand": ("int", 51, 4, 4, 0, 1), "BlockAllocation": ("int", 58, 4, 8, 0, 0),
    "IndicatorBlockAssignment": ("int", 96, 4, 2, 0, 0), "IndicatorFunction": ("int", 96, 4, 2, 2, 0),
    "TimerHighByte": ("int", 68, 4, 8, 0, 0), "TimerLowByte": ("int", 72, 4, 8, 0, 0),
    "TimerExpiryCommand": ("int", 76, 4, 4, 0, 0), "EEPROMLevelStore": ("bit", 62, 1, 1, 1, 0),
    "LightIndex": ("int", 0, 1, 8, 0, 0), "LightLevel": ("int", 1, 16, 8, 0, 0),
    "LightLevelStore1": ("int", 17, 4, 8, 0, 0), "LightLevelStore2": ("int", 21, 4, 8, 0, 0),
}


def _freeze(values):
    return MappingProxyType({k: tuple(v) if isinstance(v, (list, tuple)) else v for k, v in values.items()})


def _json_values(values):
    return {k: list(v) if isinstance(v, tuple) else v for k, v in values.items()}


def _text(value):
    return " ".join(map(str, value)) if isinstance(value, tuple) else str(value)


@dataclass(frozen=True)
class ConversionPlan:
    source_type: str
    target_type: str
    source: Mapping[str, Any]
    expected: Mapping[str, Any]
    changes: Mapping[str, Any]
    retained_target: Mapping[str, str]
    ignored_source: tuple[str, ...]

    def __post_init__(self):
        for name in ("source", "expected", "changes", "retained_target"):
            object.__setattr__(self, name, _freeze(getattr(self, name)))
        object.__setattr__(self, "ignored_source", tuple(self.ignored_source))

    def as_dict(self):
        return {"format": "cbus-offline-conversion-plan-v1", "scope": "classic_programming_alignment",
                "source_type": self.source_type, "target_type": self.target_type,
                "source": _json_values(self.source), "expected": _json_values(self.expected),
                "changes": _json_values(self.changes), "retained_target": dict(self.retained_target),
                "ignored_source": list(self.ignored_source),
                "source_physical_keys": CLASSIC_UNITS[self.source_type],
                "target_physical_keys": CLASSIC_UNITS[self.target_type],
                "stored_key_slots": 4,
                "inactive_source_keys": list(range(CLASSIC_UNITS[self.target_type] + 1, CLASSIC_UNITS[self.source_type] + 1)),
                "new_physical_keys": list(range(CLASSIC_UNITS[self.source_type] + 1, CLASSIC_UNITS[self.target_type] + 1)),
                "saved": False, "database_replaced": False,
                "limitations": ["LearnedFlag UI-state transition is not modeled",
                                "Neo, DLT and sensor conversion families are not implemented",
                                "Database metadata, replacement, readdress and hardware transfer are separate"]}


class OfflineConversion:
    """Plan and apply the classic programming stage to an existing target session."""
    def __init__(self, source_spec: UnitSpec, target_spec: UnitSpec):
        self.source_spec, self.target_spec = source_spec, target_spec
        for spec in (source_spec, target_spec):
            if spec.unit_type not in CLASSIC_UNITS or spec.filename != spec.unit_type + ".xml":
                raise ConversionError("Offline alignment currently supports KEY1.xml, KEY2.xml and KEY4.xml only")
            codec = MemoryCodec(spec)
            for name, expected in _LAYOUTS.items():
                try:
                    p = codec.layout(name)
                    actual = (p.parameter.type, p.address, p.array_size, p.bit_size, p.bit_address, p.array_skip)
                except (MemoryError, ValueError) as exc:
                    raise ConversionError("Missing classic parameter layout: " + name) from exc
                if actual != expected:
                    raise ConversionError("Unsupported classic parameter layout: " + name)
        self.codec = MemoryCodec(target_spec)

    def _snapshot(self, spec, values, names):
        result = {}
        for name in names:
            if name not in values:
                raise ConversionError("Current PP values are missing " + name)
            p = spec.get(name)
            checked = p.validate_value(values[name])
            if not checked["valid"]:
                raise ConversionError("Invalid " + name + ": " + "; ".join(checked["errors"]))
            value = checked["parsed"]
            if p.type == "sixbit":
                # Compare the representable native value, including eight-char padding.
                value = str(value).upper().replace("?", " ").ljust(8)
            elif isinstance(value, list):
                value = tuple(value)
            result[name] = value
        return result

    def plan(self, source_values: Mapping[str, Any], target_values: Mapping[str, Any]) -> ConversionPlan:
        source = self._snapshot(self.source_spec, source_values, COPY_PARAMETERS)
        target = self._snapshot(self.target_spec, target_values, self.target_spec.parameters)
        # Exact mask1 devices have one lighting application. Cross-application
        # translation requires the frontend's separate dual-app/group logic.
        if source["Application"][1] != 255 or not 48 <= source["Application"][0] <= 95:
            raise ConversionError("Classic conversion currently requires one primary lighting application and disabled secondary application")
        changes = {n: value for n, value in source.items() if target[n] != value}
        try:
            self.codec.encode_many(changes)
        except MemoryError as exc:
            raise ConversionError(str(exc)) from exc
        retained = {n: RETAIN_REASONS.get(n, "no evidenced classic attribute mapping; target value retained")
                    for n in self.target_spec.parameters if n not in COPY_PARAMETERS}
        return ConversionPlan(self.source_spec.unit_type, self.target_spec.unit_type, source, target,
                              changes, retained, tuple(sorted(set(source_values) - set(COPY_PARAMETERS))))

    def _verify_session(self, session, spec):
        session_source = getattr(session, "source", None)
        if session_source and not session_source.startswith("/db//"):
            raise ConversionError("Conversion alignment only supports offline database or new sessions")
        actual_type = getattr(session, "unit_type", None)
        if not actual_type:
            source = getattr(session, "source", "") or ""
            if not source.startswith("/db//"):
                raise ConversionError("Conversion requires an identifiable new or offline database session")
            response = session.client.command("DBGET " + source[3:] + "/UnitType")
            values = [line.split("=", 1)[1].strip() for line in response.lines if "UnitType=" in line]
            actual_type = values[-1] if values else ""
        if actual_type != spec.unit_type:
            raise ConversionError("Native session unit type differs from the conversion specification")
        try:
            root = ET.fromstring(xml_text(session.info("*")))
            native = {}
            for element in root.iter():
                if element.tag.rsplit("}", 1)[-1] == "Param":
                    fields = {c.tag.rsplit("}", 1)[-1]: c.text or "" for c in element}
                    name = fields.get("Name")
                    if name in native:
                        raise ConversionError("Duplicate native parameter schema")
                    native[name] = fields
            if set(native) != set(spec.parameters):
                raise ConversionError("Native parameter inventory differs from the supplied specification")
            for name, p in spec.parameters.items():
                if name not in native or native[name].get("Type", "").lower() != p.type:
                    raise ConversionError("Native schema mismatch: " + name)
                for field, default in (("Address", None), ("ArraySize", "1"), ("BitSize", "8"), ("BitAddress", "0"), ("ArraySkip", "0")):
                    def number(v):
                        return int(v.replace("$", "0x"), 16 if v.lower().startswith(("$", "0x")) else 10)
                    if number(native[name].get(field, default)) != number(p.fields.get(field, default)):
                        raise ConversionError("Native layout mismatch: " + name + "/" + field)
        except (ET.ParseError, TypeError, AttributeError) as exc:
            raise ConversionError("Invalid native schema XML") from exc

    def apply(self, target_session, plan: ConversionPlan):
        if (plan.source_type, plan.target_type) != (self.source_spec.unit_type, self.target_spec.unit_type):
            raise ConversionError("Plan unit types differ from this converter")
        # Recompute the entire plan so a constructed/modified plan cannot inject
        # factory fields, omit destination snapshots or conceal retained fields.
        rebuilt = self.plan(plan.source, plan.expected)
        if dict(rebuilt.changes) != dict(plan.changes) or dict(rebuilt.retained_target) != dict(plan.retained_target):
            raise ConversionError("Plan differs from the supported classic alignment")
        self._verify_session(target_session, self.target_spec)
        if self._snapshot(self.target_spec, target_session.values(), self.target_spec.parameters) != dict(plan.expected):
            raise ConversionError("Destination parameters changed since the conversion was planned")
        attempted = []
        expected = dict(plan.expected)
        expected.update(plan.changes)
        try:
            for name, value in plan.changes.items():
                attempted.append(name)
                target_session.set(name, _text(value))
            actual = self._snapshot(self.target_spec, target_session.values(), self.target_spec.parameters)
            if actual != expected:
                raise ConversionError("Native conversion readback differs from the plan")
        except Exception as exc:
            rollback_errors = []
            for name in reversed(attempted):
                try:
                    target_session.set(name, _text(plan.expected[name]))
                except Exception as rollback:
                    rollback_errors.append(str(rollback))
            try:
                if self._snapshot(self.target_spec, target_session.values(), self.target_spec.parameters) != dict(plan.expected):
                    rollback_errors.append("Original destination values could not be verified")
            except Exception as rollback:
                rollback_errors.append(str(rollback))
            raise ConversionApplyError(exc, rollback_errors) from exc
        return {**plan.as_dict(), "verified": True}

    def configure(self, source_session, target_session):
        self._verify_session(source_session, self.source_spec)
        return self.apply(target_session, self.plan(source_session.values(), target_session.values()))
