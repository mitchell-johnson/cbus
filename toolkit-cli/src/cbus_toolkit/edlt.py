"""Bounded KEYGL5 lighting-widget programming from Toolkit 1.18 .NET models.

5055EDL firmware5.5.00: Off/On and Dimmer, page placement, shared static or
dynamic label references, status display, restore level and dimmer ramp time.
Plans preserve unrelated PP values and only stage database programming sessions.
Toolkit configuration CRCs are not the legacy firmware EEPROM checksum.
"""
from __future__ import annotations

from binascii import crc_hqx
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping
import xml.etree.ElementTree as ET

from .memory import MemoryCodec, MemoryError
from .programming import xml_text


class EdltError(ValueError):
    pass


def _apply_error_text(error):
    """Keep reporting a failed edit even when its exception cannot be printed."""
    try:
        return str(error)
    except BaseException:
        try:
            return f"<unprintable {type(error).__name__}>"
        except BaseException:
            return "<unprintable exception>"


class EdltApplyError(RuntimeError):
    def __init__(self, cause, rollback_errors=(), attempted_parameters=()):
        self.cause, self.rollback_errors = cause, tuple(rollback_errors)
        self.attempted_parameters = tuple(attempted_parameters)
        self.saved = False
        self.details = self.as_dict()
        super().__init__("eDLT edit failed; " + ("rollback had errors" if rollback_errors else
                         "original PP values were restored") + ": " + _apply_error_text(cause))

    def as_dict(self):
        return {"error": _apply_error_text(self.cause), "attempted_parameters": list(self.attempted_parameters),
                "rollback_errors": list(self.rollback_errors), "saved": False,
                "rollback_verified": not self.rollback_errors}


RAMP_SECONDS = (0, 4, 8, 12, 20, 30, 40, 60, 90, 120, 180, 300, 420, 600, 900, 1020)
MODES = MappingProxyType({"off-on": (10, 9), "dimmer": (15, 16)})
LABEL_TYPES = MappingProxyType({"blank": 0, "dynamic-text": 1, "dynamic-icon": 2, "static": 3})
STATUS_TYPES = MappingProxyType({"blank": 0, "level": 1, "percent": 2, "bar": 3,
                               "static": 5, "dynamic-text": 6, "dynamic-icon": 7})
CRC_RANGES = MappingProxyType({"GlobalParameterCRC": (16, 239), "WidgetsCRC": (256, 3839),
                              "StaticTextCRC": (4096, 4095), "ScenesCheckSum": (8192, 1023),
                              "OverallCRC": (16, 9199)})


def _int(value, name, minimum=0, maximum=255):
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise EdltError(f"{name} must be an integer in {minimum}..{maximum}")
    return value


def _numbers(value):
    parts = value.split() if isinstance(value, str) else value if isinstance(value, (tuple, list)) else (value,)
    try:
        return tuple(int(p[1:], 16) if isinstance(p, str) and p.startswith("$") else
                     int(p, 16) if isinstance(p, str) and p.lower().startswith("0x") else
                     int(p, 10) if isinstance(p, str) else _int(p, "PP value", 0, 65535) for p in parts)
    except (ValueError, TypeError) as error:
        raise EdltError("Invalid numeric PP value") from error


def configuration_crc(data: bytes) -> int:
    """Toolkit Crc16Ccitt: seedFA50, polynomial1021, MSB first, no final XOR."""
    if not isinstance(data, bytes):
        raise EdltError("CRC input must be bytes")
    if type(data) is bytes:
        return crc_hqx(data, 0xFA50)
    # Preserve the existing iterator behavior of accepted bytes subclasses.
    value = 0xFA50
    for byte in data:
        value ^= byte << 8
        for _ in range(8):
            value = ((value << 1) ^ (0x1021 if value & 0x8000 else 0)) & 0xFFFF
    return value


def _field(widget, offset=0):
    return f"Widget{widget}WidgetType" if offset == 0 else f"Widget{widget}WidgetByteValue{offset}"


def _render(value):
    return value if isinstance(value, str) else " ".join(str(n) for n in value)


@dataclass(frozen=True)
class StaticTextAllocation:
    index: int
    text: str
    reused: bool
    changes: Mapping
    used_indices: tuple[int, ...]

    def __post_init__(self):
        object.__setattr__(self, "changes", MappingProxyType(dict(self.changes)))

    def as_dict(self):
        return {"index": self.index, "text": self.text, "reused": self.reused,
                "used_indices": list(self.used_indices),
                "changes": {name: list(value) for name, value in self.changes.items()}}


@dataclass(frozen=True)
class LightingWidgetPlan:
    page: int
    position: int
    widget: int
    page_mode: str
    mode: str
    expected: Mapping
    changes: Mapping
    record: bytes
    static_allocation: StaticTextAllocation | None = None
    status_allocation: StaticTextAllocation | None = None
    options: Mapping | None = None

    def __post_init__(self):
        for name in ("expected", "changes"):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))
        if self.options is not None:
            object.__setattr__(self, "options", MappingProxyType(dict(self.options)))

    def as_dict(self):
        return {"format": "cbus-edlt-lighting-plan-v1", "unit_type": "KEYGL5",
                "catalog_number": "5055EDL", "firmware": "5.5.00", "page": self.page,
                "position": self.position, "widget": self.widget, "page_mode": self.page_mode,
                "mode": self.mode, "record_hex": self.record.hex(),
                "changes": {k: list(v) if isinstance(v, tuple) else v for k, v in self.changes.items()},
                "static_allocation": self.static_allocation.as_dict() if self.static_allocation else None,
                "status_allocation": self.status_allocation.as_dict() if self.status_allocation else None,
                "saved": False, "physical_device_verified": False}


class EdltLighting:
    def __init__(self, spec, *, catalog_number="5055EDL", firmware="5.5.00"):
        if (spec.unit_type, spec.filename, catalog_number, firmware) != ("KEYGL5", "KEYGL5.xml", "5055EDL", "5.5.00"):
            raise EdltError("Lighting widgets currently support KEYGL5.xml, 5055EDL firmware5.5.00 only")
        self.spec, self.codec = spec, MemoryCodec(spec)
        required = {"Application": (0x21, 2), "ConfigVersionMinor": (0x100, 1),
                    "ConfigVersionMajor": (0x101, 1), "OverallCRC": (0x102, 2),
                    "GlobalParameterCRC": (0x104, 2), "WidgetsCRC": (0x106, 2),
                    "StaticTextCRC": (0x108, 2), "ScenesCheckSum": (0x10a, 2),
                    "PrimaryApplication": (0x110, 1), "SecondaryApplication": (0x111, 1),
                    "NavWidgetType": (0x200, 1)}
        for widget in range(1, 22):
            for offset in range(32):
                required[_field(widget, offset)] = (0x220 + (widget - 1) * 32 + offset, 1)
            if widget >= 6:
                required[f"Widget{widget}RestoreLevel"] = (0x1a0 + widget - 6, 1)
        for index in range(64):
            required[f"StaticTextString{index}"] = (0x1100 + index * 64, 64)
        try:
            for name, shape in required.items():
                layout = self.codec.layout(name)
                if (layout.parameter.type != "int" or
                        (layout.address, layout.array_size) != shape or
                        (layout.bit_size, layout.bit_address, layout.array_skip) != (8, 0, 0)):
                    raise EdltError("Unsupported eDLT layout: " + name)
            for name in spec.parameters:
                layout = self.codec.layout(name)
                if layout.address >= 256 and (layout.end_address > 9472 or layout.parameter.type not in ("int", "bit")):
                    raise EdltError("Unsupported eDLT CRC layout: " + name)
        except (MemoryError, KeyError) as error:
            raise EdltError(str(error)) from error

    def snapshot(self, values):
        """Normalize a full PP snapshot; missing schema parameters are errors."""
        if set(values) != set(self.spec.parameters):
            raise EdltError("A complete PP snapshot matching the unit specification is required")
        result = {}
        for name, parameter in self.spec.parameters.items():
            value = values[name] if parameter.type in ("string", "sixbit") else _numbers(values[name])
            try:
                self.codec.encode(name, value)
            except MemoryError as error:
                raise EdltError("Invalid current " + name + ": " + str(error)) from error
            result[name] = value
        return result

    def crcs(self, values):
        current = self.snapshot(values)
        # This zero-initialized temporary image is exactly the Toolkit's CRC
        # construction. It is not an EEPROM image or an assertion about gaps.
        memory = bytearray(9216)
        for name, value in current.items():
            if self.codec.layout(name).address < 256:
                continue
            for edit in self.codec.encode(name, value).edits:
                index = edit.address - 256
                memory[index] = (memory[index] & ~edit.mask) | edit.value
        return {name: tuple(configuration_crc(bytes(memory[start:start + length])).to_bytes(2, "big"))
                for name, (start, length) in CRC_RANGES.items()}

    def static_references(self, values):
        """Every Toolkit static reference, including unused255 sentinels.

        SceneCount is deliberately not used: original LoadScenes inspects all
        eight pointers. Unknown widget types and malformed pointers are errors.
        This is reference enumeration, not programming those other widget types.
        """
        current = self.snapshot(values)
        shapes = {"NavWidgetVariant": (0x201, 1, 4), "SceneBucket": (0x2112, 232, 8)}
        shapes.update({f"PageNameIndex{i}": (0x204 + i, 1, 8) for i in range(1, 5)})
        shapes.update({f"Scene{i}StartAddress": (0x2100 + 2 * i, 1, 16) for i in range(1, 9)})
        try:
            for name, shape in shapes.items():
                layout = self.codec.layout(name)
                if ((layout.address, layout.array_size, layout.bit_size) != shape or
                        layout.parameter.type != "int" or layout.bit_address or layout.array_skip):
                    raise EdltError("Unsupported static-reference schema: " + name)
        except (MemoryError, KeyError) as error:
            raise EdltError(str(error)) from error
        references = {}
        def add(index, origin):
            if index not in range(64) and index != 255:
                raise EdltError("Invalid static reference at " + origin)
            references.setdefault(index, []).append(origin)
        if current["NavWidgetVariant"] == (6,):
            for index in range(1, 5):
                name = f"PageNameIndex{index}"
                add(current[name][0], name)
        bucket = current["SceneBucket"]
        for scene in range(1, 9):
            name = f"Scene{scene}StartAddress"
            pointer = current[name][0]
            if pointer in (255, 65535):
                add(255, f"Scene{scene}NameIndex")
                continue
            if pointer >= len(bucket):
                raise EdltError("Scene pointer exceeds its declared bucket: " + name)
            if bucket[pointer] == 255:
                add(255, f"Scene{scene}NameIndex")
                continue
            if pointer + 5 > len(bucket) or pointer + 5 + 3 * bucket[pointer + 1] > len(bucket):
                raise EdltError("Truncated scene record: " + name)
            add(bucket[pointer + 4], f"Scene{scene}NameIndex")
        # Conditional static label/status property offsets. MRA/measurement
        # and multilevel named-text references below are unconditional.
        pairs = {2: (13, 14), 3: (10, 11), 4: (9, 10), 5: (17, 18),
                 14: (11, 12), 15: (8, 9), 16: (9, 10)}
        always = {4: (11, 12, 13), 7: (11,), 8: (9, 10), 9: (7,),
                  12: (10, 11, 13), 13: (6,), 16: (11, 12, 13)}
        terminated = False
        for widget in range(1, 22):
            kind = current[_field(widget)][0]
            if kind not in (0, *range(2, 17), 255):
                raise EdltError(f"Unknown or invalid widget type {kind} at widget{widget}; allocation refused")
            if widget >= 6:
                if kind == 255:
                    terminated = True
                elif kind and terminated:
                    raise EdltError("An active widget follows a terminator; allocation refused")
            control = current[_field(widget, 1)][0]
            offsets = list(always.get(kind, ()))
            if kind in pairs:
                label, status = pairs[kind]
                if (control >> 4) & 7 == 3:
                    offsets.append(label)
                if control & 15 == 5:
                    offsets.append(status)
            if (kind == 6 and control & 15 == 5) or (kind == 7 and control & 7 == 5):
                offsets.append(12)
            for offset in offsets:
                name = _field(widget, offset)
                value = current[name][0]
                # The conditional app-group getters clamp invalid indexes to
                # zero. Refuse malformed input rather than guessing firmware
                # behaviour and overwriting possibly referenced storage.
                if kind in pairs and offset in pairs[kind] and value > 63:
                    raise EdltError("Invalid conditional static reference at " + name)
                if kind == 12 and offset == 13 and value == 64:
                    # MeasurementData defaults this label to64. Its getter
                    # returns empty, but GetUsedStaticText includes64 and the
                    # original allocator counts it alongside the255 sentinel.
                    references.setdefault(64, []).append(name)
                    continue
                add(value, name)
        return {index: tuple(origins) for index, origins in sorted(references.items())}

    def allocate_static_text(self, values, text):
        """Plan exact-match reuse or highest-unused-slot allocation, no writes."""
        if not isinstance(text, str) or not text.strip() or "\0" in text:
            raise EdltError("Static label text must be nonblank and contain no NUL; use a blank label mode to detach")
        try:
            encoded = text.encode("utf-8")
        except UnicodeEncodeError as error:
            raise EdltError("Static label text must be valid Unicode") from error
        if len(encoded) > 63:
            raise EdltError("Static label text exceeds63UTF-8 bytes; truncation is not permitted")
        current = self.snapshot(values)
        for index in range(64):
            raw = bytes(current[f"StaticTextString{index}"]).split(b"\0", 1)[0]
            try:
                existing = raw.decode("utf-8")
            except UnicodeDecodeError as error:
                raise EdltError(f"StaticTextString{index} contains invalid UTF-8") from error
            if existing == text:
                # Like Toolkit, exact reuse does not require spare capacity.
                return StaticTextAllocation(index, text, True, {}, ())
        used = tuple(self.static_references(current))
        if len(used) > 63:
            # The original method counts the unused255 scene sentinel too.
            raise EdltError("Static text table is full under Toolkit's used-reference capacity check")
        for index in range(63, -1, -1):
            if index not in used:
                return StaticTextAllocation(index, text, False,
                                            {f"StaticTextString{index}": tuple(encoded.ljust(64, b"\0"))}, used)
        raise EdltError("Static text table has no unreferenced slot")

    def plan(self, current, *, page, position, group, mode, application="primary", page_mode=None,
             label_type=None, label_index=None, label_text=None, status_type=None, status_index=None,
             status_text=None, ramp_seconds=None, restore_level=None):
        options = dict(page=page, position=position, group=group, mode=mode, application=application,
                       page_mode=page_mode, label_type=label_type, label_index=label_index, label_text=label_text,
                       status_type=status_type, status_index=status_index, status_text=status_text,
                       ramp_seconds=ramp_seconds, restore_level=restore_level)
        original = self.snapshot(current)
        updates = dict(original)
        nav = original["NavWidgetType"][0]
        if nav not in (0, 1, 255):
            raise EdltError("Unsupported navigation widget mode")
        if page_mode is None:
            page_mode = "multiple" if nav == 1 else "single"
        if page_mode not in ("single", "multiple"):
            raise EdltError("page_mode must be single or multiple")
        _int(page, "Page", 1, 1 if page_mode == "single" else 4)
        _int(position, "Position", 1, 5 if page_mode == "single" else 4)
        widget = 6 + (page - 1) * 4 + position - 1
        group = _int(group, "Group", 0, 254)
        if mode not in MODES:
            raise EdltError("Supported lighting modes are off-on and dimmer")
        if application not in ("primary", "secondary"):
            raise EdltError("application selects the existing primary or secondary application")
        app = original["PrimaryApplication" if application == "primary" else "SecondaryApplication"][0]
        if not 48 <= app <= 95:
            raise EdltError("Selected application must be an assigned Lighting Type application in48..95")
        terminated = False
        for index in range(6, 22):
            kind = original[_field(index)][0]
            if kind == 255:
                terminated = True
            elif kind != 0 and terminated:
                raise EdltError("An active widget follows a terminator; repair this existing layout first")
        record = [original[_field(widget, i)][0] for i in range(32)]
        if record[0] not in (0, 2, 255):
            raise EdltError("Selected widget is another type; replacing it is outside this workflow")
        fresh = record[0] != 2
        if fresh:
            # Original SetToDefault writes these fields, preserving opaque
            # bytes4,5 and15..31. The default is not a zero-filled record.
            if record[1] & 0x70:
                record[13] = 0
            if record[1] & 0x0f:
                record[14] = 0
            for i, value in {0: 2, 1: 0, 2: 2, 3: 1, 6: 255, 7: 15, 8: 16,
                             9: 1, 10: 255, 11: 255, 12: 25}.items():
                record[i] = value
        elif record[6] != group and restore_level is None:
            raise EdltError("Changing an existing widget group requires an explicit restore_level")
        record[1] = (record[1] & 127) | (128 if application == "secondary" else 0)
        record[6] = group
        old_macro = tuple(record[7:9])
        record[7:9] = MODES[mode]
        if mode == "dimmer" and old_macro != MODES["dimmer"]:
            if old_macro != MODES["off-on"]:
                raise EdltError("Changing this lighting macro requires unsupported input-default semantics")
            record[9] = 1
        if ramp_seconds is not None:
            _int(ramp_seconds, "Ramp seconds", 0, 1020)
            if mode != "dimmer" or ramp_seconds not in RAMP_SECONDS:
                raise EdltError("Dimmer ramp seconds must be one of " + str(RAMP_SECONDS))
            record[9] = RAMP_SECONDS.index(ramp_seconds)
        if mode == "dimmer" and record[9] >= len(RAMP_SECONDS):
            raise EdltError("Invalid existing dimmer ramp index; supply ramp_seconds")
        if record[12] == 0:
            record[12] = 1  # LightingData.SetForcedValues, selected widget only.
        allocations = [None, None]
        if label_text is not None:
            if label_type not in (None, "static") or label_index is not None or not isinstance(label_text, str):
                raise EdltError("label_text selects a static label and cannot be combined with label_index")
            label_type = "static"
        if status_text is not None:
            if status_type not in (None, "static") or status_index is not None or not isinstance(status_text, str):
                raise EdltError("status_text selects static status and cannot be combined with status_index")
            status_type = "static"
        for entry, (option, index, text, codes, shift, mask, slot, static_code, dynamic_codes) in enumerate((
                (label_type, label_index, label_text, LABEL_TYPES, 4, 0x70, 13, 3, (1, 2)),
                (status_type, status_index, status_text, STATUS_TYPES, 0, 0x0f, 14, 5, (6, 7)))):
            if option is not None:
                if option not in codes:
                    raise EdltError("Unsupported label or status display type")
                code = codes[option]
                previous_code = (record[1] & mask) >> shift
                if previous_code != code and not (previous_code in dynamic_codes and code in dynamic_codes):
                    record[slot] = 0
                record[1] = (record[1] & ~mask) | (code << shift)
            code = (record[1] & mask) >> shift
            if index is not None:
                if code != static_code and code not in dynamic_codes:
                    raise EdltError("This label/status display does not use an index")
                record[slot] = _int(index, "Label/status index", 0, 63 if code == static_code else 3)
            if text is not None:
                # Match sequential model property edits: mode first, then text
                # allocation and binding. The second allocation sees the first
                # new reference and any released old reference.
                view = self._place_record(updates, widget, record)
                allocation = self.allocate_static_text(view, text)
                allocations[entry] = allocation
                updates.update(allocation.changes)
                record[slot] = allocation.index
            if code not in codes.values() or (code == static_code and record[slot] > 63) or (code in dynamic_codes and record[slot] > 3):
                raise EdltError("Invalid existing label/status type or index")
        updates = self._place_record(updates, widget, record)
        if restore_level is not None or fresh:
            updates[f"Widget{widget}RestoreLevel"] = (_int(0 if restore_level is None else restore_level, "Restore level"),)
        updates["NavWidgetType"] = (1 if page_mode == "multiple" else 0,)
        for name, value in (("ConfigVersionMajor", 1), ("ConfigVersionMinor", 0)):
            if original[name] == (255,):
                updates[name] = (value,)
        updates["Application"] = (original["PrimaryApplication"][0], original["SecondaryApplication"][0])
        updates.update(self.crcs(updates))
        changes = {name: value for name, value in updates.items() if value != original[name]}
        return LightingWidgetPlan(page, position, widget, page_mode, mode, original, changes, bytes(record),
                                  allocations[0], allocations[1], options)

    @staticmethod
    def _place_record(current, widget, record, *, normalize_mra=True):
        updates = dict(current)
        for offset, value in enumerate(record):
            updates[_field(widget, offset)] = (value,)
        # BeforeSavePPData places one terminator after the last active
        # functional widget (widget6 when none are active), and blanks earlier
        # terminators. Its WidgetType setter invokes BlankData.SetToDefault
        # only when the type changes, resetting that widget's restore value.
        # Resolved selected-widget defaults belong to the caller.
        last = max((i for i in range(6, 22) if updates[_field(i)][0] not in (0, 255)), default=5)
        for index in range(6, last):
            if updates[_field(index)] == (255,):
                updates[_field(index)] = (0,)
                updates[f"Widget{index}RestoreLevel"] = (0,)
        if last < 21 and updates[_field(last + 1)] != (255,):
            updates[_field(last + 1)] = (255,)
            updates[f"Widget{last + 1}RestoreLevel"] = (0,)
        if type(normalize_mra) is not bool:
            raise EdltError("MRA normalization flag must be boolean")
        if normalize_mra:
            # Original initialization happens before any selected type change.
            # Preserve stored raw multiplexer3 on unrelated edits even though
            # it is not a selectable value in the MRA editor.
            from .edlt_mra import normalize_mra_globals
            propagation = normalize_mra_globals(updates, source=current,
                                                _preserve_stored_multiplexer=True,
                                                _preserve_stored_placement=True)
            updates.update(propagation.changes)
        return updates

    def _verify_identity(self, session):
        source = getattr(session, "source", None)
        if not source or not source.lower().startswith("/db/"):
            raise EdltError("This bounded widget workflow requires a database programming session")
        for field, expected in (("UnitType", "KEYGL5"), ("FirmwareVersion", "5.5.00"), ("CatalogNumber", "5055EDL")):
            reply = session.programmer.client.command("DBGET " + source[3:] + "/" + field)
            values = [line.split("=", 1)[1].strip() for line in reply.lines if line.startswith("342") and "=" in line]
            if values != [expected]:
                raise EdltError("Database device identity differs: " + field)

    def _verify_session(self, session):
        self._verify_identity(session)
        document = xml_text(session.info("*"))
        if "<!DOCTYPE" in document.upper() or "<!ENTITY" in document.upper():
            raise EdltError("Unsupported schema XML declarations")
        try:
            fields = {}
            for element in ET.fromstring(document).iter():
                if element.tag.rsplit("}", 1)[-1] == "Param":
                    row = {child.tag.rsplit("}", 1)[-1]: child.text or "" for child in element}
                    if row.get("Name") in fields:
                        raise EdltError("Duplicate native schema parameter")
                    fields[row.get("Name")] = row
            if set(fields) != set(self.spec.parameters):
                raise EdltError("Native schema parameter set differs")
            for name, parameter in self.spec.parameters.items():
                native = fields[name]
                if native.get("Type", "").lower() != parameter.type:
                    raise EdltError("Native schema type differs: " + name)
                for field, default in (("Address", None), ("ArraySize", "1"), ("BitSize", "8"), ("BitAddress", "0"), ("ArraySkip", "0")):
                    if _numbers(native.get(field, default)) != _numbers(parameter.fields.get(field, default)):
                        raise EdltError("Native schema layout differs: " + name)
        except ET.ParseError as error:
            raise EdltError("Invalid native schema XML") from error

    def apply(self, session, plan):
        if not isinstance(plan, LightingWidgetPlan):
            raise EdltError("Expected a lighting widget plan")
        if plan.page_mode not in ("single", "multiple") or plan.mode not in MODES:
            raise EdltError("Invalid lighting plan mode")
        _int(plan.page, "Plan page", 1, 1 if plan.page_mode == "single" else 4)
        _int(plan.position, "Plan position", 1, 5 if plan.page_mode == "single" else 4)
        _int(plan.widget, "Plan widget", 6, 21)
        if plan.widget != 6 + (plan.page - 1) * 4 + plan.position - 1:
            raise EdltError("Plan widget does not match its page and position")
        if not isinstance(plan.record, bytes) or len(plan.record) != 32:
            raise EdltError("Plan widget record must contain32bytes")
        if not isinstance(plan.options, Mapping):
            raise EdltError("Use a plan returned by EdltLighting.plan")
        try:
            canonical = self.plan(plan.expected, **plan.options)
        except TypeError as error:
            raise EdltError("Invalid lighting plan settings") from error
        if canonical != plan:
            raise EdltError("Plan parameters or allocations differ from validated settings")
        self._verify_session(session)
        if self.snapshot(session.values()) != dict(plan.expected):
            raise EdltError("PP values changed since the lighting plan was made")
        expected = dict(plan.expected)
        expected.update(plan.changes)
        self.snapshot(expected)
        allowed = {_field(plan.widget, i) for i in range(32)} | {f"Widget{plan.widget}RestoreLevel",
                  "NavWidgetType", "Application", "ConfigVersionMajor", "ConfigVersionMinor"} | set(CRC_RANGES)
        allowed.update(_field(i) for i in range(6, 22))
        allowed.update(_field(i, 1) for i in range(1, 22)
                       if expected[_field(i)][0] in (7, 8, 9))
        allowed.update(f"Widget{i}RestoreLevel" for i in range(6, 22)
                       if plan.expected[_field(i)] != expected[_field(i)])
        for allocation in (plan.static_allocation, plan.status_allocation):
            if allocation is not None:
                allowed.update(allocation.changes)
        if set(plan.changes) - allowed:
            raise EdltError("Plan changes unrelated parameters")
        for index in range(6, 22):
            name = _field(index)
            if index != plan.widget and name in plan.changes and (plan.expected[name], expected[name]) not in (
                    ((255,), (0,)), ((0,), (255,))):
                raise EdltError("Plan replaces an unrelated widget")
        if bytes(expected[_field(plan.widget, i)][0] for i in range(32)) != plan.record:
            raise EdltError("Plan record differs from its parameter changes")
        if any(expected[name] != value for name, value in self.crcs(expected).items()):
            raise EdltError("Plan configuration CRCs do not match")
        attempted = []
        try:
            for name, value in plan.changes.items():
                attempted.append(name)
                session.set(name, _render(value))
            if self.snapshot(session.values()) != expected:
                raise EdltError("Native PP readback differs from the lighting plan")
        except Exception as error:
            rollback_errors = []
            for name in reversed(attempted):
                if not getattr(session.programmer.client, "connected", True):
                    rollback_errors.append("Connection lost; rollback stopped without recovery I/O; PP state is uncertain")
                    break
                try:
                    session.set(name, _render(plan.expected[name]))
                except Exception as rollback:
                    rollback_errors.append(str(rollback))
            if getattr(session.programmer.client, "connected", True):
                try:
                    if self.snapshot(session.values()) != dict(plan.expected):
                        rollback_errors.append("Original PP values could not be verified")
                except Exception as rollback:
                    rollback_errors.append(str(rollback))
            raise EdltApplyError(error, rollback_errors, attempted) from error
        return {**plan.as_dict(), "verified": True}

    def configure(self, session, **options):
        self._verify_identity(session)
        return self.apply(session, self.plan(session.values(), **options))
