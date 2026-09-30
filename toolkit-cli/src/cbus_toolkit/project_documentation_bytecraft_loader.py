"""Bounded old DIMPR12 packed scene projection; no original PP execution."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .project_documentation_devices import _required_array
from .project_documentation_outputs import _registration

if TYPE_CHECKING:
    from .project_documentation import Unit

CHANNEL_COUNT = 12
SCENE_COUNT = 33
RECORD_SIZE = 32


@dataclass(frozen=True)
class BytecraftScene:
    """One freshly loaded record; selector identity is its Address, never Value."""

    index: int
    advanced: bool
    recall_group: int
    selector_address: int
    link_group: int
    on: tuple[bool, ...]
    on_levels: tuple[int, ...]
    off: tuple[bool, ...]
    off_levels: tuple[int, ...]
    ramp_on: int
    ramp_off: int

    @property
    def on_unused(self) -> bool:
        return not any(self.on)

    @property
    def off_unused(self) -> bool:
        return not any(self.off)

    @property
    def unused(self) -> bool:
        return self.on_unused and self.off_unused


def decode_bytecraft_scenes(unit: Unit) -> tuple[BytecraftScene, ...]:
    """Decode explicit PresetRec00..32 under the exact old class registration.

    Native array defaults are zero, but this saved-project adapter requires all
    consumed values explicitly. It models the fresh records only, without any
    previous GUI scene/group state, auto-created metadata or loader execution.
    Loader SETG/SETE instructions normalize the Boolean byte before the setter
    constructs a Variant Boolean. In particular channels 8..11 are not dropped
    by a low-byte truncation of the raw inclusion mask.
    """
    row = _registration(unit)
    if (unit.unit_type != "DIMPR12" or row is None
            or row[3:5] != ("TDIMPR12", "TDIMPR12CGateAgent")):
        raise ValueError("old DIMPR12 class/agent firmware profile")
    scenes = []
    for index in range(SCENE_COUNT):
        name = f"PresetRec{index:02d}"
        try:
            record = _required_array(unit, name, RECORD_SIZE)
        except ValueError as error:
            raise ValueError(f"{name} (requires {RECORD_SIZE} explicit byte values)") from error
        on_mask = (record[4] << 8) + record[5]
        off_mask = (record[18] << 8) + record[19]
        scenes.append(BytecraftScene(
            index=index, advanced=record[0] == 1,
            recall_group=record[1], selector_address=record[2], link_group=record[3],
            on=tuple((on_mask & (1 << channel)) > 0 for channel in range(CHANNEL_COUNT)),
            on_levels=tuple(record[6:18]),
            off=tuple((off_mask & (1 << channel)) > 0 for channel in range(CHANNEL_COUNT)),
            off_levels=tuple(record[20:32]),
            ramp_on=(record[4] & 0xF0) >> 4,
            ramp_off=(record[18] & 0xF0) >> 4,
        ))
    return tuple(scenes)
