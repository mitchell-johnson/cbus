"""Two distinct source-pinned light-level reports from explicit saved PP.

Old SENLL uses the native exponential Lux1600 scale and reports the midpoint
and full width of its two converted thresholds. ST7 SENLL uses Lux2550 and the
loaded percentage margin instead. No configuration or live sensor read occurs.
"""
from __future__ import annotations

from decimal import Decimal, localcontext
from fractions import Fraction

from .macros import STAGES
from .project_documentation_devices import _group_link, _required_array
from .project_documentation_outputs import _registration
from .project_documentation_usage import Usage
from .sensors import _extended, margin_percent

OLD_TYPES = ("SENLL", "PE_CELL")
# Exact native extended constants in ByteToLux1600 and both report bodies.
_EXP_BASE = Fraction(0xADF3B645A1CAC083, 1 << 62)
_FOOT_CANDLE = Fraction(13715050917036238853, 1 << 67)


def light_level_profile(unit):
    row = _registration(unit)
    if row is not None:
        if unit.unit_type.upper() in OLD_TYPES and row[3:5] == ("TSENLL", "TSENLLCGateAgent"):
            return "old"
        if unit.unit_type.upper() == "SENLL" and row[3:5] == ("TST7SENLL", "TCBusST7LightLevelSensorCGateAgent"):
            return "st7"
    raise ValueError("unrecovered light-level class or firmware (surface SENLLA is excluded)")


def _byte(unit, name):
    return _required_array(unit, name, 1)[0]


def lux1600(value):
    """ROUND(25 * original_extended_base ** (integer / 52)).

    Decimal evaluates the statically recovered formula without vendor execution.
    The independent static receipt checks the bounded -255..510 domain stays
    away from rounding ties under 60- and 90-digit calculations.
    """
    if type(value) is not int or not -255 <= value <= 510:
        raise ValueError("Lux1600 exponent must be an integer in -255..510")
    with localcontext() as context:
        context.prec = 60
        base = Decimal(_EXP_BASE.numerator) / Decimal(_EXP_BASE.denominator)
        return round(25 * base ** (Decimal(value) / 52))


def _foot_candle(lux):
    return round(_extended(lux * _FOOT_CANDLE))


def _st7_timer(unit, selected):
    high = _required_array(unit, "TimerHighByte", 8)
    low = _required_array(unit, "TimerLowByte", 8)
    timer = high[selected] * 256 + low[selected]
    if timer:
        return timer
    # Assigning a Timer/SENPILL template can default a zero timer during native
    # loading. Explicit all-idle keys and empty occupancy masks establish the
    # zero case without inventing a retained template/association history.
    commands = tuple(_required_array(unit, name, 8, 15) for name in STAGES)
    occupancy = tuple(_byte(unit, name) for name in ("PIRLightMovement", "PIRDarkMovement", "PIRDark"))
    if any(any(values) for values in commands) or any(occupancy):
        raise ValueError("zero broadcast timer with active key/occupancy templates is unrecovered")
    return 0


def light_level_data(unit):
    kind = light_level_profile(unit)
    apps = _required_array(unit, "Application", 2 if kind == "st7" else 1)
    data = {"kind": kind, "application": apps[0]}
    if kind == "old":
        data["groups"] = tuple((apps[0], _byte(unit, name)) for name in
                               ("LevelGroupAddress", "OnOffGroupAddress", "EnableGroupAddress"))
        target, hysteresis = _byte(unit, "TargetLUX"), _byte(unit, "Hystersis")
        upper, lower = lux1600(target + hysteresis), lux1600(target - hysteresis)
        data["target"] = round(Fraction(upper + lower, 2))
        data["margin"] = upper - lower
        data["percentage"] = (min(100, round(_extended(_extended(Fraction(data["margin"], data["target"])) * 100)))
                              if data["margin"] and data["target"] else 0)
    else:
        groups = _required_array(unit, "GroupAddress", 8)
        secondary = _byte(unit, "SecondApplicationBlocks")
        maintenance = _byte(unit, "PECFunctionBlock")
        broadcast = _byte(unit, "BroadcastBlock")
        if maintenance >= 8 or broadcast >= 8:
            raise ValueError("light-level maintenance/broadcast block is outside the eight loaded blocks")
        def block(index):
            return apps[int(bool(secondary & (1 << index)))], groups[index]
        data["groups"] = (block(maintenance), block(2), (apps[0], _byte(unit, "PECEnablerGroup")), block(broadcast))
        data["timer"] = _st7_timer(unit, broadcast)
        target = _byte(unit, "PECTargetLux")
        data["target"] = target * 10
        data["percentage"] = margin_percent(target, _byte(unit, "PECMarginLux"))
    return data


def light_level_lines(network, data):
    labels = ("Light Level Group", "On/Off Group", "Enable Group", "Broadcast Group")
    lines = [f"{label}: {_group_link(network, app, group)}<br />"
             for label, (app, group) in zip(labels, data["groups"])]
    if data["kind"] == "st7":
        hours, remainder = divmod(data["timer"], 3600)
        minutes, seconds = divmod(remainder, 60)
        lines.append(f"Broadcast Time: {hours}h{minutes}m{seconds}s<br />")
    lines.append(f'Target: {data["target"]} Lux, {_foot_candle(data["target"])} ft-candle<br />')
    if data["kind"] == "old":
        lines.append(f'Margin: {data["margin"]} Lux, {_foot_candle(data["margin"])} ft-candle ({data["percentage"]}%)<br />')
    else:
        lines.append(f'Margin: {data["percentage"]}%<br />')
    return lines


def document_light_level(out, network, unit):
    from .project_documentation import document_base
    document_base(out, network, unit)
    try:
        lines = light_level_lines(network, light_level_data(unit))
    except ValueError as error:
        out.mark(network, unit, f"Light-level report: {error}")
        return "partial"
    for line in lines:
        out.add(line)
    return "recovered"


def light_level_group_usage(unit, application, group, kind):
    if kind not in {"input", "output", "other"}:
        raise ValueError("Group usage kind must be input, output or other")
    try:
        profile = light_level_profile(unit)
        if kind == "output":
            return Usage()
        if profile == "old":
            if application != _byte(unit, "Application"):
                return Usage()
            fields = (("LevelGroupAddress", "Level Group"),) if kind == "input" else (
                ("AreaGroupAddress", "Area Group"), ("OnOffGroupAddress", "On/Off Group"),
                ("EnableGroupAddress", "Enable Group"))
            return Usage("<br/>".join(label for name, label in fields if _byte(unit, name) == group))
        if kind == "other":
            return _st7_other_usage(unit, application, group)
        apps = _required_array(unit, "Application", 2)
        groups = _required_array(unit, "GroupAddress", 8)
        secondary = _byte(unit, "SecondApplicationBlocks")
        active = _required_array(unit, "PECFunctionActive", 1, 1)[0]
        maintenance = _byte(unit, "PECFunctionBlock")
        if maintenance >= 8:
            raise ValueError("PECFunctionBlock (requires an existing loaded block)")
        # TST7SENLL has zero physical keys and both joins unsupported. None of
        # its virtual keys satisfies the report's visible-key predicate.
        descriptions = []
        for index, address in enumerate(groups):
            if (apps[int(bool(secondary & (1 << index)))], address) == (application, group):
                descriptions.append("Light Level Maintenance" if active and maintenance == index else "Block (Unused)")
        scenes = unit.array("SceneTable")
        if scenes is None or any(not 0 <= value <= 255 for value in scenes):
            return Usage("<br/>".join(descriptions), "partial", ("SceneTable (explicit empty scene graph required)",))
        if scenes and scenes[0] != 255:
            return Usage("<br/>".join(descriptions), "partial", ("light-level scene group dependencies",))
        return Usage("<br/>".join(descriptions))
    except ValueError as error:
        return Usage(status="unrecovered", missing=(str(error),))


def _st7_other_usage(unit, application, group):
    apps = _required_array(unit, "Application", 2)
    descriptions = []
    if application == apps[0]:
        if _byte(unit, "AreaGroupAddress") == group:
            descriptions.append("Area Group")
    if application == 203 and group == 255:
        descriptions.append("Key Disable Group")
    if application == apps[0] and _byte(unit, "CorridorLinkEnablerGroup") == group:
        descriptions.append("Corridor Link Group")
    if application == 202 and _byte(unit, "ControlAppGroupAddress") == group:
        descriptions.append("Control App Group")
    if application == apps[0]:
        for name, label in (("PECEnablerGroup", "Light Level Maintenance Enable"),
                            ("PIREnablerGroup", "Occupancy Enable"),
                            ("CorridorLinkEnablerGroup", "Corridor Link")):
            if _byte(unit, name) == group:
                descriptions.append(label)
    selected = _byte(unit, "BroadcastBlock")
    if selected >= 8:
        raise ValueError("BroadcastBlock (requires an existing loaded block)")
    groups = _required_array(unit, "GroupAddress", 8)
    secondary = _byte(unit, "SecondApplicationBlocks")
    if (apps[int(bool(secondary & (1 << selected)))], groups[selected]) == (application, group):
        descriptions.append("Light Level Broadcast Group")
    return Usage("<br/>".join(descriptions))
