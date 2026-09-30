"""Input-unit power-up broadcast settings from Toolkit 1.18.

Two Toolkit editors are covered:

* Bus couplers (BCN2B, BCN4B, KEYV1SP): "Broadcast Values on Power Up" on the
  coupler restore tab (TfrmBCProLightLevelRestore). GroupAssertOnPowerup holds
  one bit per block (bit 0 = block 1). TcdBCProLightLevelRestore enables a
  block's checkbox only when a bistable key references it
  (TCoreBusCouplerInputUnit.IsKeyBlockBistable) and unticks every other block;
  TCoreBusCouplerInputCGateAgent.SaveGroupAssertOnPowerupAttribute rebuilds the
  whole byte from the per-block flags.
* KEYBC2, KEYBC4 and DINAUX4: the unit-wide "Broadcast Values on Power Up"
  checkbox, saved by TCBusKeyInputCGateAgent as GAVBroadcastFlag 0 (ticked) or
  $FF (unticked).

IOPE occupancy controllers use a different enable rule (bistable auxiliary
inputs and assigned block groups); iope_settings.py edits them.
"""
from __future__ import annotations

from types import MappingProxyType

from .pp_editor import PPEditError, PPEditor, boolean, integer

# Toolkit MaximumKeyCount for each coupler class (TBCN2B, TBCN4B, TKEYV1SP).
COUPLER_UNITS = MappingProxyType({"BCN2B": 2, "BCN4B": 4, "KEYV1SP": 1})
COUPLER_LAYOUTS = MappingProxyType({
    "GroupAssertOnPowerup": ("int", 0x1D, 1, 8, 0, 0),
    "BistableSwitchBlock": ("int", 0x46, 1, 8, 0, 0),
    "BlockAllocation": ("int", 0x36, 8, 8, 0, 0),
})
BROADCAST_UNITS = frozenset({"KEYBC2", "KEYBC4", "DINAUX4"})
BROADCAST_LAYOUTS = MappingProxyType({"GAVBroadcastFlag": ("int", 0x6F, 1, 8, 0, 0)})
BLOCKS = 8


def _blocks(values, label):
    if isinstance(values, (str, bytes)) or not hasattr(values, "__iter__"):
        raise PPEditError(label + " must be a list of block numbers")
    result = set()
    for value in values:
        value = integer(value, "Block")
        if not 1 <= value <= BLOCKS:
            raise PPEditError("Blocks are numbered 1..8")
        result.add(value)
    return result


class CouplerPowerUp(PPEditor):
    FORMAT = "cbus-coupler-power-up-plan-v1"

    def __init__(self, spec):
        if spec.unit_type not in COUPLER_UNITS or spec.filename != spec.unit_type + ".xml":
            raise PPEditError("Coupler power-up supports " + ", ".join(name + ".xml" for name in COUPLER_UNITS) + " only")
        super().__init__(spec, spec.unit_type, COUPLER_LAYOUTS)
        self.key_count = COUPLER_UNITS[spec.unit_type]

    def bistable_blocks(self, snapshot) -> set[int]:
        """Blocks referenced by a key whose BistableSwitchBlock bit is set."""
        mask, allocation = snapshot["BistableSwitchBlock"][0], snapshot["BlockAllocation"]
        return {block for key in range(self.key_count) if mask >> key & 1
                for block in range(1, BLOCKS + 1) if allocation[key] >> (block - 1) & 1}

    def plan(self, current, *, enable=(), disable=()):
        enable, disable = _blocks(enable, "enable"), _blocks(disable, "disable")
        if enable & disable:
            raise PPEditError("A block cannot be both enabled and disabled")
        original = self.snapshot(current)
        eligible = self.bistable_blocks(original)
        refused = sorted(enable - eligible)
        if refused:
            raise PPEditError(f"Blocks {refused} are not used by a bistable key; Toolkit disables their power-up broadcast")
        before = {block for block in range(1, BLOCKS + 1) if original["GroupAssertOnPowerup"][0] >> (block - 1) & 1}
        selected = ((before & eligible) | enable) - disable
        # The dialog unticks non-bistable blocks, so a Toolkit save clears them.
        cleared = sorted(before - eligible)
        value = sum(1 << (block - 1) for block in selected)
        updates = dict(original, GroupAssertOnPowerup=(value,))
        return self.make_plan(original, updates, {
            "blocks": sorted(selected), "bistable_blocks": sorted(eligible), "cleared_non_bistable": cleared})

    def configure(self, session, **options):
        return self.apply(session, self.plan(session.values(), **options))


class KeyPowerUpBroadcast(PPEditor):
    FORMAT = "cbus-key-power-up-broadcast-plan-v1"

    def __init__(self, spec):
        if spec.unit_type not in BROADCAST_UNITS or spec.filename != spec.unit_type + ".xml":
            raise PPEditError("Broadcast Values on Power Up supports KEYBC2.xml, KEYBC4.xml and DINAUX4.xml only")
        super().__init__(spec, spec.unit_type, BROADCAST_LAYOUTS)

    def plan(self, current, *, broadcast):
        broadcast = boolean(broadcast, "broadcast")
        original = self.snapshot(current)
        updates = {"GAVBroadcastFlag": (0 if broadcast else 0xFF,)}
        return self.make_plan(original, updates, {"broadcast": broadcast})

    def configure(self, session, **options):
        return self.apply(session, self.plan(session.values(), **options))


def power_up_editor(spec):
    if spec.unit_type in COUPLER_UNITS:
        return CouplerPowerUp(spec)
    if spec.unit_type in BROADCAST_UNITS:
        return KeyPowerUpBroadcast(spec)
    raise PPEditError(f"{spec.unit_type} has no admitted power-up broadcast editor")
