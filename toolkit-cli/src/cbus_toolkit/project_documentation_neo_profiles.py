"""Exact factory profiles for the Neo and NeoPro Document Project families.

Counts, IR rules and dependency slots are pinned by the companion static annex.
These profiles describe freshly loaded reports, not an editor or physical unit.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

# Original factory registration order. Counts are VMT results, not type-name
# parsing; KEYEx exposes four positions even on its one-button variant.
PAIRED_COUNTS = {
    "KEYA1": 1, "KEYAV2": 2, "KEYA3": 3, "KEYAV4": 4, "KEYA6": 6, "KEYA8": 8,
    "KEYB2": 2, "KEYB4": 4, "KEYB6": 6, "KEYH1": 1, "KEYH2": 2, "KEYH3": 3,
    "KEYH4": 4, "KEYM2": 2, "KEYM4": 4, "KEYM8": 8,
}
SINGLE_COUNTS = {
    "BCI4A": 4, "KEYE1": 4, "KEYE2": 4, "KEYE3": 4, "KEYE4": 4,
    "KEYEIR1": 4, "KEYEIR2": 4, "KEYEIR3": 4, "KEYEIR4": 4,
    "KEYBIR2": 2, "KEYBIR4": 4, "KEYBIR6": 6,
    "KEYDV1": 1, "KEYDV2": 2, "KEYDV3": 3, "KEYDV4": 4,
    "KEYP2": 2, "KEYP4": 4, "KEYP6": 6, "KEYV1": 1, "KEYV2": 2, "KEYV3": 3,
    "KEYV1SP": 1, "KEYV2SP": 2, "KEYV3SP": 3, "BCN2B": 2, "BCN4B": 4,
}
COUPLER_TYPES = frozenset(("BCI4A", "KEYV1SP", "KEYV2SP", "KEYV3SP", "BCN2B", "BCN4B"))
KEYE_TYPES = frozenset(("KEYE1", "KEYE2", "KEYE3", "KEYE4", "KEYEIR1", "KEYEIR2", "KEYEIR3", "KEYEIR4"))
IR_TYPES = frozenset(("KEYM2", "KEYM4", "KEYM8", "KEYBIR2", "KEYBIR4", "KEYBIR6",
                      "KEYDV1", "KEYDV2", "KEYDV3", "KEYDV4", "KEYEIR1", "KEYEIR2", "KEYEIR3", "KEYEIR4"))


@dataclass(frozen=True)
class NeoClassProfile:
    unit_type: str
    class_name: str
    firmware_min: str
    firmware_max: str
    physical_key_count: int
    is_pro: bool
    infrared_virtual_keys: bool
    key_mask_default: int | None = None
    bistable: bool = False
    other_dependency_pro: bool = True

    def join_supported(self, firmware: str) -> bool:
        # CoreNeoPro requires firmware>=1.6.0 and <=4physical keys. KEYEx
        # and CoreBusCoupler override the method with constant false.
        return (self.is_pro and self.unit_type not in KEYE_TYPES | COUPLER_TYPES
                and self.physical_key_count <= 4 and _version(firmware) >= (1, 6, 0))


def _version(value: str) -> tuple[int, int, int]:
    parts = tuple(map(int, value.split(".")))
    return (parts + (0, 0, 0))[:3]


def _single(kind: str, count: int) -> NeoClassProfile:
    low, high = ("1.8.00", "2.9.99") if kind.startswith("KEYDV") else (
        ("1.7.00", "2.9.99") if kind in {"KEYV1", "KEYV2", "KEYV3"} else ("0", "9"))
    return NeoClassProfile(kind, "TKEYEx" if kind in KEYE_TYPES else "T" + kind,
                           low, high, count, True, kind in IR_TYPES,
                           (1 << int(kind[-1])) - 1 if kind in KEYE_TYPES else None,
                           kind in COUPLER_TYPES, kind not in COUPLER_TYPES)


NEO_CLASS_PROFILES = tuple(
    NeoClassProfile(kind, "T" + kind + suffix, low, high, count, pro, kind in IR_TYPES,
                    other_dependency_pro=pro)
    for kind, count in PAIRED_COUNTS.items()
    for suffix, low, high, pro in (("_A", "1.3.01", "1.5.02", False),
                                   ("", "1.5.03", "2.9.99", True))
) + tuple(_single(kind, count) for kind, count in SINGLE_COUNTS.items())
NEO_TYPES = frozenset(PAIRED_COUNTS) | frozenset(SINGLE_COUNTS)


def profile_facts(unit) -> NeoClassProfile:
    """Select one exact factory partition within the existing PP identity profile.

    Retain the established major.minor.two-digit-release grammar; missing,
    decorated and unsupported firmware identities never select a class.
    """
    firmware = getattr(unit, "firmware", "")
    typ = getattr(unit, "unit_type", "")
    if type(typ) is not str or type(firmware) is not str or re.fullmatch(
            r"[0-9]{1,2}\.[0-9]{1,2}\.[0-9]{2}", firmware) is None:
        raise ValueError("unrecovered Neo class/firmware")
    candidates = [row for row in NEO_CLASS_PROFILES if row.unit_type == typ.upper()
                  and _version(row.firmware_min) <= _version(firmware) <= _version(row.firmware_max)]
    if len(candidates) != 1:
        raise ValueError("unrecovered Neo class/firmware")
    return candidates[0]
