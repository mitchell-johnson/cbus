"""SceneData properties and explicit mutating getters, without host binding.

SceneData's ``new`` index properties are distinct from the base virtual auto
properties. A base display setter resets the latter, never stored bytes11/12.
"""
from __future__ import annotations

from dataclasses import dataclass

from .edlt import EdltError

LABEL_CHOICES = (("Blank", 0), ("Dynamic Label", 1), ("Dynamic Icon", 2), ("Scene Label", 3))
STATUS_CHOICES = (("Blank", 0), ("Dynamic Label", 6), ("Dynamic Icon", 7), ("Static Text", 5))
VARIANT_CHOICES = (("1", 0), ("2", 1), ("3", 2), ("4", 3))
MACRO_CHOICES = (("Cycle Down / Cycle Up", "30|31"), ("Off / On", "26|27"),
                 ("Off & Ramp Down / On & Ramp Up", "28|29"),
                 ("Off & Nudge Down / On & Nudge Up", "32|33"))


def _integer(value, name, low=0, high=255):
    if type(value) is not int or not low <= value <= high:
        raise EdltError(f"Scene widget {name} must be an integer in {low}..{high}")
    return value


@dataclass(frozen=True)
class SceneWidgetProperties:
    record: bytes
    base_label_index: int = 0
    base_status_index: int = 0

    def __post_init__(self):
        if type(self.record) is not bytes or len(self.record) != 32 or self.record[0] != 6:
            raise EdltError("Scene widget controls require an exact 32-byte SceneData record")
        _integer(self.base_label_index, "hidden base label index", -2**31, 2**31-1)
        _integer(self.base_status_index, "hidden base status index", -2**31, 2**31-1)

    def display_type(self, target):
        if target == "label":
            return (self.record[1] >> 4) & 7
        if target == "status":
            return self.record[1] & 15
        raise EdltError("Scene display target must be label or status")

    def index(self, target):
        if target not in ("label", "status"):
            raise EdltError("Scene index target must be label or status")
        return self.record[11 if target == "label" else 12]

    def as_dict(self):
        cycle = self.record[7] in (30, 31) or self.record[8] in (30, 31)
        return {"record_hex": self.record.hex(), "label_type": self.display_type("label"),
                "status_type": self.display_type("status"), "label_variant": self.record[11],
                "status_variant": self.record[12], "scene_item": self.record[6],
                "cycle_variant": self.record[1] >> 7, "cycle_storage": list(self.record[13:22]),
                "cycle_selection_editable": cycle, "single_selection_editable": not cycle,
                "dlt_variants_enabled": self.display_type("label") in (1, 2),
                "status_variants_visible": self.display_type("status") in (6, 7),
                "static_status_visible": self.display_type("status") == 5,
                "select_label_variants_enabled": self.display_type("label") == 10,
                "scene_cycle_state_label": "Scene Cycle List" if cycle else "Scene",
                "ramp_rate_editable": self.record[7] in (28, 29) or self.record[8] in (28, 29),
                "offset_editable": self.record[7] in (32, 33) or self.record[8] in (32, 33),
                "cycle_getter_invoked": False}


@dataclass(frozen=True)
class ScenePropertyResult:
    state: SceneWidgetProperties
    property_name: str
    notifications: tuple[str, ...] = ()
    hidden_base_index_reset: str | None = None

    def as_dict(self):
        return {"property": self.property_name, "state": self.state.as_dict(),
                "property_changed": list(self.notifications),
                "hidden_base_index_reset": self.hidden_base_index_reset,
                "automatic_binding_refresh_inferred": False}


def _record(state, record, *, label=None, status=None):
    if type(state) is not SceneWidgetProperties:
        raise EdltError("Use an exact typed Scene widget property state")
    return SceneWidgetProperties(bytes(record), state.base_label_index if label is None else label,
                                 state.base_status_index if status is None else status)


def set_display_type(state, *, target, value):
    if type(state) is not SceneWidgetProperties:
        raise EdltError("Scene type setter requires its typed property state")
    choices = LABEL_CHOICES if target == "label" else STATUS_CHOICES if target == "status" else ()
    if type(value) is not int or value not in [row[1] for row in choices]:
        raise EdltError("Scene display type is outside its source Scene-specific choices")
    record = bytearray(state.record)
    proposed = (value << 4) + (record[1] & 0x8f) if target == "label" else value + (record[1] & 0xf0)
    changed = proposed != record[1]
    record[1] = proposed
    property_name = "LabelDisplayType" if target == "label" else "StatusDisplayType"
    reset = target if changed and state.display_type(target) != value else None
    final = _record(state, record, label=0 if reset == "label" else None,
                    status=0 if reset == "status" else None)
    # These call the inherited base auto-property, not SceneData's new fields.
    notifications = (property_name, "LabelValueText" if target == "label" else "StatusValueText") if reset else ()
    return ScenePropertyResult(final, property_name, notifications, reset)


def set_index(state, *, target, value):
    _integer(value, "variant/index")
    record = bytearray(state.record)
    if target not in ("label", "status"):
        raise EdltError("Scene index target must be label or status")
    record[11 if target == "label" else 12] = value
    return ScenePropertyResult(_record(state, record), "SelectedLabelVariant" if target == "label" else "SelectedStatusVariant")


def set_scene_item(state, value):
    _integer(value, "SceneItem")
    record = bytearray(state.record); record[6] = value
    return ScenePropertyResult(_record(state, record), "SceneItem")


def set_cycle_variant(state, *, radio, checked):
    if radio not in ("cycle", "select") or type(checked) is not bool:
        raise EdltError("Scene cycle variant needs its exact radio and checked value")
    value = int(checked) if radio == "select" else int(not checked)
    record = bytearray(state.record); record[1] = (value << 7) + (record[1] & 127)
    return ScenePropertyResult(_record(state, record), "SceneCycleVariantSelect" if radio == "select" else "NotSceneCycleVariantSelect")


def set_macro(state, value):
    if value not in [row[1] for row in MACRO_CHOICES]:
        raise EdltError("Scene macro selection must use an exact source pair")
    left, right = map(int, value.split("|"))
    record = bytearray(state.record); notifications = []
    if record[7] != left:
        notifications.extend(("LeftButtonMacrofunction", "RampRateEditable"))
    if record[8] != right:
        notifications.append("RightButtonMacrofunction")
    record[7:9] = (left, right)
    # Original subscriber spells RightButtonMacrofunctin; do not repair it.
    notifications.append("SceneSingleSelectionEditable")
    return ScenePropertyResult(_record(state, record), "DualButtonMacrofunction", tuple(notifications))


@dataclass(frozen=True)
class SceneCycleRead:
    state: SceneWidgetProperties
    slots: tuple[int, ...]
    first_invalid_slot: int | None
    normalized_slots: tuple[int, ...]

    def as_dict(self):
        return {"property": "SceneCycle", "rows": [
            {"identity": f"cycle-slot:{slot}", "slot": slot, "value": self.state.record[13 + slot]}
            for slot in self.slots], "first_invalid_slot": self.first_invalid_slot,
                "normalized_slots": list(self.normalized_slots), "record_hex": self.state.record.hex(),
                "accepted_raw_scene_range": [0, 8], "configured_scene_existence_tested": False,
                "raise_list_changed_events": [False, True]}


def read_scene_cycle(state):
    if type(state) is not SceneWidgetProperties:
        raise EdltError("SceneCycle needs its typed SceneData record")
    record = bytearray(state.record); slots = []
    invalid = next((i for i, value in enumerate(record[13:22]) if value > 8), None)
    for slot in range(9 if invalid is None else invalid):
        slots.append(slot)
    # The for-loop increments after the first failure, before its flag break.
    normalized = tuple(range(invalid + 1, 9)) if invalid is not None else ()
    for slot in normalized:
        record[13 + slot] = 255
    return SceneCycleRead(_record(state, record), tuple(slots), invalid, normalized)


def add_cycle_scene(state):
    record = bytearray(state.record); inserted = None
    for slot in range(8):
        if inserted is not None:
            record[13 + slot] = 255
        elif record[13 + slot] > 7:
            record[13 + slot] = 0; inserted = slot
    return _record(state, record), inserted


def delete_cycle_scene(state, *, current_slot):
    if current_slot is None:
        return state, None
    _integer(current_slot, "current cycle slot", 0, 8)
    read = read_scene_cycle(state)
    if current_slot not in read.slots:
        raise EdltError("Original SceneCycle.IndexOf current object is absent; its negative index is outside this profile")
    record = bytearray(read.state.record)
    for slot in range(current_slot, 9):
        record[13 + slot] = 255 if slot == 8 else record[14 + slot]
    return _record(state, record), read


def set_cycle_row(state, *, slot, value):
    _integer(slot, "cycle slot", 0, 8); _integer(value, "cycle scene")
    record = bytearray(state.record); record[13 + slot] = value
    return _record(state, record)


def move_cycle_scene(state, *, index, row_count, direction):
    if index is None:
        return state, None
    _integer(index, "current cell index", 0, 8); _integer(row_count, "observed row count", 0, 9)
    if direction not in ("up", "down") or index >= row_count:
        raise EdltError("Scene cycle move needs an observed current grid row")
    other = index - 1 if direction == "up" else index + 1
    if other < 0 or other >= row_count:
        return state, None
    record = bytearray(state.record)
    record[13 + other], record[13 + index] = record[13 + index], record[13 + other]
    return _record(state, record), other
