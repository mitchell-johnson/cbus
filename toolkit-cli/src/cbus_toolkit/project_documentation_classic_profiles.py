"""Additional original ClassicKeyInput profiles using the shared PP projection.

All admitted classes use the classic key agent, four blocks, physical-only key
collections and no IBistable interface. AUX's template override changes the
Bell Press label to Aux On/Off without changing the loaded microfunctions.
This is source-pinned snapshot rendering, not original generated-page parity.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .project_documentation_devices import ClassicKeyData, classic_key_data, classic_key_macro
from .project_documentation_outputs import _registration

if TYPE_CHECKING:
    from .project_documentation import Network, Unit, _Writer

CLASSIC_PROFILE_COUNTS = {"KEYIR1": 4, "KEYIR4": 4, "KEYBC2": 2, "KEYBC4": 4,
                          "KEYAUX4": 4, "DINAUX4": 4, "BCNC4A": 4, "BCNC4B": 4}
AUX_TYPES = frozenset(("KEYAUX4", "DINAUX4"))
BCNC_TYPES = frozenset(("BCNC4A", "BCNC4B"))


def classic_profile(unit: Unit) -> tuple[int, bool]:
    """Return the source-registered physical count and AUX override flag."""
    typ = unit.unit_type.upper()
    registration = _registration(unit)
    agent = "TBCNC4CGateAgent" if typ in BCNC_TYPES else "TCBusKeyInputCGateAgent"
    if (typ not in CLASSIC_PROFILE_COUNTS or registration is None
            or registration[3:5] != ("T" + typ, agent)):
        raise ValueError("unrecovered classic key class/firmware")
    return CLASSIC_PROFILE_COUNTS[typ], typ in AUX_TYPES


def auxiliary_key_macro(commands: tuple[int, ...], application: int,
                        primary_stored1: int | None, primary_stored2: int | None) -> tuple[int, str]:
    """AUX reconciliation followed by its application-specific subset.

    The source AUX subset replaces KEY's type7 with type28. The global first match
    is type7 and all three Bell Press/Aux group registrations share the same four
    commands. Application255 filtering still yields Custom, as in the KEY subset.
    """
    kind, label = classic_key_macro(commands, application, primary_stored1, primary_stored2)
    return (28, "Aux On/Off") if kind == 7 else (kind, label)


def classic_profile_data(unit: Unit) -> tuple[ClassicKeyData, list[tuple[int, str]]]:
    count, auxiliary = classic_profile(unit)
    resolver = auxiliary_key_macro if auxiliary else classic_key_macro
    data = classic_key_data(unit, key_count=count, macro_resolver=resolver)
    macros = []
    for mask, commands in zip(data.masks, data.commands):
        primary = next((block for block in range(len(data.groups)) if mask & (1 << block)), None)
        macros.append(resolver(commands, data.application,
                               data.stored1[primary] if primary is not None else None,
                               data.stored2[primary] if primary is not None else None))
    return data, macros


def document_classic_profile(out: _Writer, network: Network, unit: Unit) -> str:
    from .project_documentation import document_base
    from .project_documentation_devices import classic_key_lines

    document_base(out, network, unit)
    try:
        data, macros = classic_profile_data(unit)
        lines = classic_key_lines(network, data, macros=macros)
    except ValueError as exc:
        out.mark(network, unit, f"Classic key controls: {exc}")
        return "partial"
    for line in lines:
        out.add(line)
    return "recovered"
