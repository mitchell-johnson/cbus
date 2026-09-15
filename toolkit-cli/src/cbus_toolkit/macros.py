"""Classic KEY1/KEY2/KEY4 macro presets, grounded in Toolkit 1.18.

Four stages are JP (short press), SR, LP and LR. These are classic nibble
micro-functions, not the newer command encodings or eDLT/NCC widget formats.
Plans edit logical PP parameters and never save or transfer to a device.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping
import xml.etree.ElementTree as ET

from .memory import MemoryCodec, MemoryError
from .programming import xml_text
from .unitspec import UnitSpec


class MacroError(ValueError):
    pass


class MacroApplyError(RuntimeError):
    def __init__(self, cause, rollback_errors=()):
        self.cause = cause
        self.rollback_errors = tuple(rollback_errors)
        super().__init__("Macro application failed; " + ("rollback had errors" if rollback_errors else "changed parameters were restored") + ": " + str(cause))


STAGES = ("JPCommand", "SRCommand", "LPCommand", "LRCommand")
MICRO_FUNCTIONS = MappingProxyType({
    "idle": 0, "store1": 1, "downcycle": 2, "memory_toggle2": 3,
    "down": 4, "up": 5, "recall2": 6, "retrigger_timer": 7,
    "start_timer": 8, "ramp_off": 9, "ramp_recall1": 10,
    "toggle": 11, "recall1": 12, "on": 13, "end_ramp": 14, "off": 15,
})


@dataclass(frozen=True)
class Preset:
    name: str
    events: tuple[str, str, str, str]
    help_topic: str

    @property
    def codes(self):
        return tuple(MICRO_FUNCTIONS[event] for event in self.events)

    def as_dict(self):
        return {"name": self.name, "events": dict(zip(STAGES, self.events)),
                "codes": dict(zip(STAGES, self.codes)), "help_topic": self.help_topic}


PRESETS = MappingProxyType({p.name: p for p in (
    Preset("on", ("on", "idle", "idle", "idle"), "958.htm"),
    Preset("off", ("off", "idle", "idle", "idle"), "959.htm"),
    Preset("toggle", ("toggle", "idle", "idle", "idle"), "960.htm"),
    Preset("dimmer", ("idle", "toggle", "downcycle", "end_ramp"), "961.htm"),
    Preset("dimmer_memory", ("idle", "memory_toggle2", "downcycle", "end_ramp"), "961.htm"),
    Preset("dimmer_up", ("idle", "on", "up", "end_ramp"), "966.htm"),
    Preset("dimmer_down", ("idle", "off", "down", "end_ramp"), "967.htm"),
    Preset("on_up", ("idle", "memory_toggle2", "up", "end_ramp"), "962.htm"),
    Preset("off_down", ("idle", "memory_toggle2", "down", "end_ramp"), "963.htm"),
    Preset("timer", ("toggle", "retrigger_timer", "idle", "retrigger_timer"), "964.htm"),
    Preset("bellpress", ("on", "off", "on", "off"), "965.htm"),
    Preset("soft_up", ("end_ramp", "ramp_recall1", "up", "end_ramp"), "968.htm"),
    Preset("soft_down", ("end_ramp", "ramp_off", "down", "end_ramp"), "969.htm"),
    Preset("preset1", ("idle", "recall1", "ramp_off", "idle"), "970.htm"),
    Preset("preset2", ("idle", "recall2", "ramp_off", "idle"), "971.htm"),
    Preset("trigger1", ("recall1", "idle", "idle", "idle"), "972.htm"),
    Preset("trigger2", ("recall2", "idle", "idle", "idle"), "973.htm"),
    Preset("unused", ("idle", "idle", "idle", "idle"), "976.htm"),
)})

SUPPORTED_UNITS = MappingProxyType({"KEY1": 1, "KEY2": 2, "KEY4": 4})
_READ_FIELDS = STAGES + ("BlockAllocation", "GroupAddress", "Application", "TimerHighByte",
                       "TimerLowByte", "TimerExpiryCommand", "LightLevelStore1", "LightLevelStore2")
_EXPIRY = frozenset(("idle", "off", "down", "ramp_off", "recall1", "recall2", "ramp_recall1"))


def _int(value, label):
    if isinstance(value, bool) or not isinstance(value, int):
        raise MacroError(label + " must be an integer")
    return value


def _numbers(value):
    tokens = value.split() if isinstance(value, str) else value if isinstance(value, (list, tuple)) else [value]
    try:
        return tuple(int(str(t).replace("$", "0x"), 0) if isinstance(t, str) and str(t).lower().startswith(("$", "0x", "0b")) else _int(t, "Value") if not isinstance(t, str) else int(t, 10) for t in tokens)
    except (ValueError, TypeError) as exc:
        raise MacroError("Expected numeric PP parameter values") from exc


@dataclass(frozen=True)
class KeyPlan:
    unit_type: str
    key: int
    preset: str
    block: int | None
    expected: Mapping[str, tuple[int, ...]]
    changes: Mapping[str, tuple[int, ...]]
    shared_keys: tuple[int, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "expected", MappingProxyType({k: tuple(v) for k, v in self.expected.items()}))
        object.__setattr__(self, "changes", MappingProxyType({k: tuple(v) for k, v in self.changes.items()}))

    def as_dict(self):
        return {"format": "cbus-classic-key-plan-v1", "unit_type": self.unit_type,
                "key": self.key, "preset": PRESETS[self.preset].as_dict(), "block": self.block,
                "expected": {k: list(v) for k, v in self.expected.items()},
                "changes": {k: list(v) for k, v in self.changes.items()},
                "shared_keys": list(self.shared_keys), "saved": False}


class ClassicKeys:
    def __init__(self, spec: UnitSpec):
        self.spec = spec
        self.unit_type = spec.unit_type
        if self.unit_type not in SUPPORTED_UNITS or spec.filename != self.unit_type + ".xml":
            raise MacroError("Classic presets currently support KEY1.xml, KEY2.xml and KEY4.xml only")
        self.key_count = SUPPORTED_UNITS[self.unit_type]
        self.codec = MemoryCodec(spec)
        expected = {"JPCommand": (0x32, 4, 4, 4, 1), "SRCommand": (0x32, 4, 4, 0, 1),
                    "LPCommand": (0x33, 4, 4, 4, 1), "LRCommand": (0x33, 4, 4, 0, 1),
                    "BlockAllocation": (0x3A, 4, 8, 0, 0), "GroupAddress": (0x50, 8, 8, 0, 0),
                    "TimerHighByte": (0x44, 4, 8, 0, 0), "TimerLowByte": (0x48, 4, 8, 0, 0),
                    "TimerExpiryCommand": (0x4C, 4, 4, 0, 0)}
        try:
            for name in _READ_FIELDS:
                layout = self.codec.layout(name)
                if layout.parameter.type != "int":
                    raise MacroError("Classic numeric parameter layout required")
                shape = (layout.address, layout.array_size, layout.bit_size, layout.bit_address, layout.array_skip)
                if name in expected and shape != expected[name]:
                    raise MacroError(f"Unsupported classic parameter layout for {name}")
        except MemoryError as exc:
            raise MacroError(str(exc)) from exc

    def _snapshot(self, values):
        result = {}
        for name in _READ_FIELDS:
            if name not in values:
                raise MacroError(f"Current PP values are missing {name}")
            parsed = _numbers(values[name])
            validation = self.spec.get(name).validate_value(list(parsed))
            if not validation["valid"]:
                raise MacroError(f"Invalid current {name}: " + "; ".join(validation["errors"]))
            result[name] = parsed
        return result

    def plan(self, current: Mapping[str, Any], *, key: int, preset: str, group: int | None = None,
             block: int | None = None, timer_seconds: int | None = None, expiry: str = "off",
             recall1: int | None = None, recall2: int | None = None, allow_shared_block: bool = False) -> KeyPlan:
        key = _int(key, "Key")
        if not 1 <= key <= self.key_count:
            raise MacroError(f"{self.unit_type} has {self.key_count} physical key(s)")
        if preset not in PRESETS:
            raise MacroError("Unknown classic macro preset")
        original = self._snapshot(current)
        updates = {name: list(values) for name, values in original.items()}
        for name, code in zip(STAGES, PRESETS[preset].codes):
            updates[name][key - 1] = code
        needs_block = preset == "timer" or any(value is not None for value in (group, block, timer_seconds, recall1, recall2))
        selected = None
        shared = ()
        if needs_block:
            if block is None:
                mask = original["BlockAllocation"][key - 1]
                if not mask or mask & (mask - 1) or mask > 8:
                    raise MacroError("Specify a block in 1..4 for a key without one supported block assignment")
                block = mask.bit_length()
            block = _int(block, "Block")
            if not 1 <= block <= 4:
                raise MacroError("Classic block must be in 1..4")
            selected = block
            shared = tuple(i + 1 for i, mask in enumerate(original["BlockAllocation"]) if i != key - 1 and mask & (1 << (block - 1)))
            modifies_block = any(value is not None for value in (group, timer_seconds, recall1, recall2))
            if modifies_block and shared and not allow_shared_block:
                raise MacroError(f"Block {block} is also assigned to keys {shared}; choose an unused block or explicitly allow the shared edit")
            updates["BlockAllocation"][key - 1] = 1 << (block - 1)
            if group is not None:
                group = _int(group, "Group")
                if not 0 <= group <= 254:
                    raise MacroError("Group must be in 0..254; 255 is the unassigned sentinel")
                # These classic units use the primary application for the four
                # supported blocks. No secondary-application mapping is inferred.
                if not 48 <= original["Application"][0] <= 95:
                    raise MacroError("Group assignment requires a Lighting Type primary application in 48..95")
                updates["GroupAddress"][block - 1] = group
            if timer_seconds is not None:
                timer_seconds = _int(timer_seconds, "Timer seconds")
                if not 0 <= timer_seconds <= 65535:
                    raise MacroError("Timer seconds must be in 0..65535")
                if expiry not in _EXPIRY:
                    raise MacroError("Unsupported classic timer-expiry function")
                updates["TimerHighByte"][block - 1] = timer_seconds >> 8
                updates["TimerLowByte"][block - 1] = timer_seconds & 255
                updates["TimerExpiryCommand"][block - 1] = MICRO_FUNCTIONS[expiry]
            elif preset == "timer" and original["TimerHighByte"][block - 1] == 0 and original["TimerLowByte"][block - 1] == 0:
                raise MacroError("The selected block's timer is disabled; supply timer_seconds")
            for name, value in (("LightLevelStore1", recall1), ("LightLevelStore2", recall2)):
                if value is not None:
                    value = _int(value, "Recall level")
                    if not 0 <= value <= 255:
                        raise MacroError("Recall level must be in 0..255")
                    updates[name][block - 1] = value
        changes = {name: tuple(values) for name, values in updates.items() if tuple(values) != original[name]}
        try:
            self.codec.encode_many(changes)
        except MemoryError as exc:
            raise MacroError(str(exc)) from exc
        return KeyPlan(self.unit_type, key, preset, selected, original, changes, shared)

    def _verify_session(self, session):
        # PP INFO exposes the actual native schema, avoiding accidental writes
        # into newer devices with similarly named but differently laid-out fields.
        unit_type = getattr(session, "unit_type", None)
        if unit_type is None:
            source = getattr(session, "source", None)
            if not source or not source.lower().startswith("/db/"):
                raise MacroError("A known unit type or a database programming session is required")
            reply = session.programmer.client.command("DBGET " + source[3:] + "/UnitType")
            values = [line.split("=", 1)[1].strip() for line in reply.lines if line.startswith("342") and "=" in line]
            if len(values) != 1:
                raise MacroError("Native database unit type could not be determined")
            unit_type = values[0]
        if unit_type != self.unit_type:
            raise MacroError("Programming session unit type differs from the plan")
        document = xml_text(session.info("*"))
        if "<!DOCTYPE" in document.upper() or "<!ENTITY" in document.upper():
            raise MacroError("Unsupported native schema XML declarations")
        try:
            root = ET.fromstring(document)
            parameters = {}
            for element in root.iter():
                if element.tag.rsplit("}", 1)[-1] != "Param":
                    continue
                fields = {child.tag.rsplit("}", 1)[-1]: child.text or "" for child in element}
                if fields.get("Name") in parameters:
                    raise MacroError("Duplicate native parameter schema")
                parameters[fields.get("Name")] = fields
            for name in _READ_FIELDS:
                if name not in parameters:
                    raise MacroError("Native session is missing classic schema parameter " + name)
                native, spec = parameters[name], self.spec.get(name)
                if native.get("Type", "").lower() != spec.type:
                    raise MacroError("Native parameter type mismatch: " + name)
                for field, default in (("Address", None), ("ArraySize", "1"), ("BitSize", "8"), ("BitAddress", "0"), ("ArraySkip", "0")):
                    if _numbers(native.get(field, default)) != _numbers(spec.fields.get(field, default)):
                        raise MacroError("Native parameter layout mismatch: " + name + "/" + field)
        except ET.ParseError as exc:
            raise MacroError("Invalid native schema XML") from exc

    def apply(self, session, plan: KeyPlan):
        if plan.unit_type != self.unit_type:
            raise MacroError("Plan unit type differs from the programmer")
        if any(name not in _READ_FIELDS for name in plan.changes):
            raise MacroError("Plan contains fields outside the classic key workflow")
        try:
            self.codec.encode_many(plan.changes)
        except MemoryError as exc:
            raise MacroError(str(exc)) from exc
        self._verify_session(session)
        if self._snapshot(session.values()) != dict(plan.expected):
            raise MacroError("PP parameters changed since this plan was created")
        attempted = []
        try:
            for name, values in plan.changes.items():
                attempted.append(name)
                session.set(name, " ".join(str(value) for value in values))
            after = self._snapshot(session.values())
            expected = dict(plan.expected)
            expected.update(plan.changes)
            if after != expected:
                raise MacroError("Native macro readback differed from the plan")
        except Exception as exc:
            rollback_errors = []
            for name in reversed(attempted):
                try:
                    session.set(name, " ".join(str(value) for value in plan.expected[name]))
                except Exception as rollback:
                    rollback_errors.append(str(rollback))
            try:
                if self._snapshot(session.values()) != dict(plan.expected):
                    rollback_errors.append("Original PP values could not be verified after rollback")
            except Exception as rollback:
                rollback_errors.append(str(rollback))
            raise MacroApplyError(exc, rollback_errors) from exc
        return {**plan.as_dict(), "verified": True}

    def configure(self, session, **options):
        return self.apply(session, self.plan(session.values(), **options))
