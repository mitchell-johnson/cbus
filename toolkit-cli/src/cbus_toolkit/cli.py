"""Command-line entry point. Results are JSON; diagnostics go to stderr."""
from __future__ import annotations

import argparse
import dataclasses
import enum
import json
import os
import sys
from importlib.resources import files
from pathlib import Path

from . import __version__


class BatchCommandError(RuntimeError):
    def __init__(self, error, completed):
        super().__init__(str(error))
        self.details = {"completed_count": len(completed), "completed_responses": completed,
                        "failed_command_index": len(completed) + 1}


def _json_default(value):
    if dataclasses.is_dataclass(value):
        return dataclasses.asdict(value)
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, enum.Enum):
        return value.value
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def _number(value):
    try:
        return int(value[1:], 16) if value.startswith("$") else int(value, 16 if value.lower().startswith("0x") else 10)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Use a decimal, 0x-prefixed or $-prefixed integer") from exc


def _byte(value):
    result = _number(value)
    if not 0 <= result <= 255:
        raise argparse.ArgumentTypeError("Address/value must be in 0..255")
    return result


def _label_application(value):
    from .labels import validate_label_application
    try:
        return validate_label_application(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def _unit(value):
    return None if value.lower() == "local" else _byte(value)


def _positive(value):
    result = float(value)
    if not 0 < result < float("inf"):
        raise argparse.ArgumentTypeError("Value must be positive and finite")
    return result


def _fields(values):
    result = {}
    for value in values or []:
        key, sep, data = value.partition("=")
        if not sep or not key:
            raise ValueError("Fields must have the form FIELD=VALUE")
        if key in result:
            raise ValueError(f"Duplicate field: {key}")
        result[key] = data
    return result


def _key_options(parser, *, extended=False):
    from .macros import PRESETS
    parser.add_argument("--key", dest="key_number", type=_number, required=True, help="Physical key number, starting at 1")
    parser.add_argument("--preset", choices=tuple(PRESETS), required=True)
    parser.add_argument("--group", type=_byte)
    parser.add_argument("--block", type=_number, help="Block number in 1..8" if extended else "Classic block number in 1..4")
    parser.add_argument("--timer-seconds", type=_number)
    parser.add_argument("--expiry", choices=("idle", "off", "down", "ramp_off", "recall1", "recall2", "ramp_recall1"), default="off")
    parser.add_argument("--recall1", type=_byte)
    parser.add_argument("--recall2", type=_byte)
    parser.add_argument("--allow-shared-block", action="store_true", help="Allow changing settings on a block assigned to other keys")
    if extended:
        parser.add_argument("--application", choices=("primary", "secondary"))
        parser.add_argument("--indicator-block", type=_number, help="Independent indicator block assignment in 1..8")


def _key_settings(args):
    result = {"key": args.key_number, **{name: getattr(args, name) for name in ("preset", "group", "block", "timer_seconds", "expiry", "recall1", "recall2", "allow_shared_block")}}
    for name in ("application", "indicator_block"):
        if hasattr(args, name):
            result[name] = getattr(args, name)
    return result


def _classic_keys(args, *, extended=False):
    from .macros import ClassicKeys
    from .unitspec import UnitSpecStore
    if args.spec_dir is None:
        raise ValueError("Use --spec-dir or CBUS_UNITSPEC_DIR for decoded vendor specifications")
    if extended:
        from .extended_macros import ExtendedKeys
        return ExtendedKeys(UnitSpecStore(args.spec_dir).load(args.spec))
    return ClassicKeys(UnitSpecStore(args.spec_dir).load(args.spec))


def _sensor_options(parser):
    parser.add_argument("--key", dest="key_number", type=_number, help="Virtual key in 1..8; requires --event")
    parser.add_argument("--event", choices=("day", "night", "any", "sunset", "disabled"))
    parser.add_argument("--block", type=_number)
    parser.add_argument("--group", type=_byte)
    parser.add_argument("--timer-seconds", type=_number)
    parser.add_argument("--expiry", choices=("idle", "off", "down", "ramp_off", "recall1", "recall2", "ramp_recall1"), default="off")
    parser.add_argument("--target-lux", type=_number, help="0..2550 in steps of 10; requires --margin-percent")
    parser.add_argument("--margin-percent", type=_number)
    parser.add_argument("--enable-group", type=_byte, help="Occupancy enable group; 255 removes its assignment")
    parser.add_argument("--enabled-when", choices=("on", "off"))
    parser.add_argument("--allow-shared-block", action="store_true")
    parser.add_argument("--disable-potentiometer-override", action="store_true",
                       help="Set only conflicting timer/threshold potentiometer functions to unused")


def _sensor_settings(args):
    return {"key": args.key_number, **{name: getattr(args, name) for name in (
        "event", "block", "group", "timer_seconds", "expiry", "target_lux", "margin_percent",
        "enable_group", "enabled_when", "allow_shared_block", "disable_potentiometer_override")}}


def _sensor(args):
    from .sensors import Multisensor
    from .unitspec import UnitSpecStore
    if args.spec_dir is None:
        raise ValueError("Use --spec-dir or CBUS_UNITSPEC_DIR for decoded vendor specifications")
    return Multisensor(UnitSpecStore(args.spec_dir).load("SENPILL_ST7.xml"))


def _parameter_snapshot(path, profile):
    with path.open("rb") as handle:
        data = handle.read(1024 * 1024 + 1)
    if len(data) > 1024 * 1024:
        raise ValueError("Parameter snapshot exceeds 1 MiB")
    values = json.loads(data)
    if not isinstance(values, dict):
        raise ValueError("Expected a PP parameter mapping or export snapshot")
    if "format" in values:
        if values.get("format") != "cbus-cli-parameters-v1" or tuple(values.get(key) for key in (
                "unit_type", "firmware", "catalog_number")) != tuple(profile):
            raise ValueError("Snapshot format or unit identity differs from the selected profile")
        values = values.get("parameters")
        if not isinstance(values, dict):
            raise ValueError("Snapshot requires a parameter mapping")
    return values


def _edlt_options(parser):
    parser.add_argument("--page", type=_number, required=True)
    parser.add_argument("--position", type=_number, required=True)
    parser.add_argument("--group", type=_byte, required=True)
    parser.add_argument("--mode", choices=("off-on", "dimmer"), required=True)
    parser.add_argument("--application", choices=("primary", "secondary"), default="primary")
    parser.add_argument("--page-mode", choices=("single", "multiple"))
    parser.add_argument("--label-type", choices=("blank", "dynamic-text", "dynamic-icon", "static"))
    parser.add_argument("--label-index", type=_number)
    parser.add_argument("--label-text", help="Reuse matching static text or allocate the highest unused shared text slot")
    parser.add_argument("--status-type", choices=("blank", "level", "percent", "bar", "static", "dynamic-text", "dynamic-icon"))
    parser.add_argument("--status-index", type=_number)
    parser.add_argument("--status-text", help="Reuse or allocate static status text with whole-unit reference checks")
    parser.add_argument("--ramp-seconds", type=_number)
    parser.add_argument("--restore-level", type=_byte)


def _edlt_settings(args):
    return {name: getattr(args, name) for name in (
        "page", "position", "group", "mode", "application", "page_mode", "label_type", "label_index",
        "label_text", "status_type", "status_index", "status_text", "ramp_seconds", "restore_level")}


def _edlt(args):
    from .edlt import EdltLighting
    from .unitspec import UnitSpecStore
    if args.spec_dir is None:
        raise ValueError("Use --spec-dir or CBUS_UNITSPEC_DIR for decoded vendor specifications")
    return EdltLighting(UnitSpecStore(args.spec_dir).load("KEYGL5.xml"))


def _edlt_scene_options(parser):
    parser.add_argument("--page", type=_number, required=True)
    parser.add_argument("--position", type=_number, required=True)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--scene", type=_number, help="Existing configured scene in 1..8")
    selection.add_argument("--cycle-scene", dest="cycle_scenes", type=_number, action="append", help="Repeat for an ordered cycle of 1..8 configured scenes")
    parser.add_argument("--mode", choices=("off-on", "ramp", "nudge", "cycle"), default="off-on")
    parser.add_argument("--ramp-seconds", type=_number, help="Scene ramp time; used by ramp mode")
    parser.add_argument("--offset", type=_byte, help="Nudge offset in 0..255")
    parser.add_argument("--cycle-variant", choices=("cycle", "select"))
    parser.add_argument("--page-mode", choices=("single", "multiple"))
    parser.add_argument("--label-type", choices=("blank", "dynamic-text", "dynamic-icon", "scene"))
    parser.add_argument("--label-index", type=_number, help="Dynamic label variant in 0..3")
    parser.add_argument("--status-type", choices=("blank", "static", "dynamic-text", "dynamic-icon"))
    parser.add_argument("--status-index", type=_number)
    parser.add_argument("--status-text", help="Reuse or allocate shared static status text")


def _edlt_enable_options(parser):
    parser.add_argument("--page", type=_number, required=True)
    parser.add_argument("--position", type=_number, required=True)
    parser.add_argument("--variable", type=_byte, required=True, help="Enable network variable in 0..254")
    parser.add_argument("--level", type=_byte, required=True, help="Preset level in 0..255")
    parser.add_argument("--page-mode", choices=("single", "multiple"))
    parser.add_argument("--label-type", choices=("blank", "dynamic-text", "dynamic-icon", "static"))
    parser.add_argument("--label-index", type=_number)
    parser.add_argument("--label-text", help="Reuse or allocate shared static label text")
    parser.add_argument("--status-type", choices=("blank", "level", "percent", "bar", "static", "dynamic-text", "dynamic-icon"))
    parser.add_argument("--status-index", type=_number)
    parser.add_argument("--status-text", help="Reuse or allocate shared static status text")


def _edlt_enable_settings(args):
    return {name: getattr(args, name) for name in (
        "page", "position", "variable", "level", "page_mode", "label_type", "label_index",
        "label_text", "status_type", "status_index", "status_text")}


def _edlt_enable(args):
    from .edlt_enable import EdltEnableWidget
    from .unitspec import UnitSpecStore
    if args.spec_dir is None:
        raise ValueError("Use --spec-dir or CBUS_UNITSPEC_DIR for decoded vendor specifications")
    return EdltEnableWidget(UnitSpecStore(args.spec_dir).load("KEYGL5.xml"))


def _edlt_shutter_options(parser):
    parser.add_argument("--page", type=_number, required=True)
    parser.add_argument("--position", type=_number, required=True)
    parser.add_argument("--group", type=_byte, required=True)
    parser.add_argument("--application", choices=("primary", "secondary"), default="primary")
    parser.add_argument("--mode", choices=("two-key", "two-key-presets"), default="two-key")
    parser.add_argument("--preset-left", type=_number, help="Left preset in 6..248, for two-key-presets mode")
    parser.add_argument("--preset-right", type=_number, help="Right preset in 6..248, for two-key-presets mode")
    parser.add_argument("--page-mode", choices=("single", "multiple"))
    parser.add_argument("--label-type", choices=("blank", "dynamic-text", "dynamic-icon", "static"))
    parser.add_argument("--label-index", type=_number)
    parser.add_argument("--label-text", help="Reuse or allocate shared static label text")
    parser.add_argument("--status-type", choices=("blank", "level", "percent", "bar", "static", "dynamic-text", "dynamic-icon"))
    parser.add_argument("--status-index", type=_number)
    parser.add_argument("--status-text", help="Reuse or allocate shared static status text")


def _edlt_shutter_settings(args):
    return {name: getattr(args, name) for name in (
        "page", "position", "group", "application", "mode", "preset_left", "preset_right", "page_mode",
        "label_type", "label_index", "label_text", "status_type", "status_index", "status_text")}


def _edlt_shutter(args):
    from .edlt_shutter import EdltShutterWidget
    from .unitspec import UnitSpecStore
    if args.spec_dir is None:
        raise ValueError("Use --spec-dir or CBUS_UNITSPEC_DIR for decoded vendor specifications")
    return EdltShutterWidget(UnitSpecStore(args.spec_dir).load("KEYGL5.xml"))


def _edlt_timer_options(parser):
    parser.add_argument("--page", type=_number, required=True)
    parser.add_argument("--position", type=_number, required=True)
    parser.add_argument("--group", type=_byte, required=True)
    parser.add_argument("--application", choices=("primary", "secondary"), default="primary")
    parser.add_argument("--duration-seconds", type=_number, help="Timer duration in 0..64800 seconds")
    parser.add_argument("--target-level", type=_number, help="Timer target in 1..255")
    parser.add_argument("--expiry-level", type=_byte, help="Level at timer expiry in 0..255")
    parser.add_argument("--ramp-seconds", type=_number, help="One of the supported timer ramp durations")
    parser.add_argument("--page-mode", choices=("single", "multiple"))
    parser.add_argument("--label-type", choices=("blank", "dynamic-text", "dynamic-icon", "static"))
    parser.add_argument("--label-index", type=_number)
    parser.add_argument("--label-text", help="Reuse or allocate shared static label text")
    parser.add_argument("--status-type", choices=("blank", "timer", "static", "dynamic-text", "dynamic-icon"))
    parser.add_argument("--status-index", type=_number)
    parser.add_argument("--status-text", help="Reuse or allocate shared static status text")


def _edlt_timer_settings(args):
    return {name: getattr(args, name) for name in (
        "page", "position", "group", "application", "duration_seconds", "target_level", "expiry_level",
        "ramp_seconds", "page_mode", "label_type", "label_index", "label_text", "status_type", "status_index", "status_text")}


def _edlt_timer(args):
    from .edlt_timer import EdltTimerWidget
    from .unitspec import UnitSpecStore
    if args.spec_dir is None:
        raise ValueError("Use --spec-dir or CBUS_UNITSPEC_DIR for decoded vendor specifications")
    return EdltTimerWidget(UnitSpecStore(args.spec_dir).load("KEYGL5.xml"))


def _edlt_threshold_options(parser, selector):
    parser.add_argument("--page", type=_number, required=True)
    parser.add_argument("--position", type=_number, required=True)
    parser.add_argument("--group", type=_byte, required=True)
    parser.add_argument("--application", choices=("primary", "secondary"), default="primary")
    parser.add_argument("--" + selector, type=_number, choices=(1, 2, 3))
    parser.add_argument("--low-threshold", type=_number, help="Lower threshold in 1..254")
    parser.add_argument("--high-threshold", type=_number, help="Upper threshold in 1..254, when three settings are selected")
    parser.add_argument("--page-mode", choices=("single", "multiple"))
    parser.add_argument("--label-type", choices=("blank", "dynamic-text", "dynamic-icon", "static"))
    parser.add_argument("--label-index", type=_number)
    parser.add_argument("--label-text", help="Reuse or allocate shared static label text")
    for state in ("off", "low", "medium", "high"):
        selection = parser.add_mutually_exclusive_group()
        selection.add_argument("--" + state + "-text", help="Reuse or allocate shared static " + state + " status text")
        selection.add_argument("--" + state + "-index", type=_number, help="Exact shared static text index in 0..63")


def _edlt_fan_options(parser):
    _edlt_threshold_options(parser, "speeds")


def _edlt_multilevel_options(parser):
    _edlt_threshold_options(parser, "levels")


def _edlt_threshold_settings(args, selector):
    return {name: getattr(args, name) for name in (selector,
        "page", "position", "group", "application", "low_threshold", "high_threshold",
        "page_mode", "label_type", "label_index", "label_text", "off_text", "low_text", "medium_text",
        "high_text", "off_index", "low_index", "medium_index", "high_index")}


def _edlt_fan_settings(args):
    return _edlt_threshold_settings(args, "speeds")


def _edlt_multilevel_settings(args):
    return _edlt_threshold_settings(args, "levels")


def _edlt_multilevel(args):
    from .edlt_multilevel import EdltMultiLevelWidget
    from .unitspec import UnitSpecStore
    if args.spec_dir is None:
        raise ValueError("Use --spec-dir or CBUS_UNITSPEC_DIR for decoded vendor specifications")
    return EdltMultiLevelWidget(UnitSpecStore(args.spec_dir).load("KEYGL5.xml"))


def _edlt_room_courtesy_options(parser):
    from .edlt_room_courtesy import ROOM_COURTESY_MODES, ROOM_COURTESY_COLOURS, ROOM_COURTESY_STATUS_TYPES
    parser.add_argument("--page", type=_number, required=True)
    parser.add_argument("--position", type=_number, required=True)
    parser.add_argument("--group", type=_byte, required=True)
    parser.add_argument("--application", choices=("primary", "secondary"), default="primary")
    parser.add_argument("--mode", choices=tuple(ROOM_COURTESY_MODES))
    parser.add_argument("--off-colour", choices=tuple(ROOM_COURTESY_COLOURS))
    parser.add_argument("--on-colour", choices=tuple(ROOM_COURTESY_COLOURS))
    parser.add_argument("--page-mode", choices=("single", "multiple"))
    parser.add_argument("--label-type", choices=("blank", "dynamic-text", "dynamic-icon", "static"))
    parser.add_argument("--label-index", type=_number)
    parser.add_argument("--label-text", help="Reuse or allocate shared static label text")
    parser.add_argument("--status-type", choices=tuple(ROOM_COURTESY_STATUS_TYPES))
    parser.add_argument("--status-index", type=_number)
    parser.add_argument("--status-text", help="Reuse or allocate shared static status text")


def _edlt_room_courtesy_settings(args):
    return {name: getattr(args, name) for name in (
        "page", "position", "group", "application", "mode", "off_colour", "on_colour", "page_mode",
        "label_type", "label_index", "label_text", "status_type", "status_index", "status_text")}


def _edlt_room_courtesy(args):
    from .edlt_room_courtesy import EdltRoomCourtesyWidget
    from .unitspec import UnitSpecStore
    if args.spec_dir is None:
        raise ValueError("Use --spec-dir or CBUS_UNITSPEC_DIR for decoded vendor specifications")
    return EdltRoomCourtesyWidget(UnitSpecStore(args.spec_dir).load("KEYGL5.xml"))


def _edlt_fan(args):
    from .edlt_fan import EdltFanWidget
    from .unitspec import UnitSpecStore
    if args.spec_dir is None:
        raise ValueError("Use --spec-dir or CBUS_UNITSPEC_DIR for decoded vendor specifications")
    return EdltFanWidget(UnitSpecStore(args.spec_dir).load("KEYGL5.xml"))


def _edlt_measurement_options(parser):
    parser.add_argument("--page", type=_number, required=True)
    parser.add_argument("--position", type=_number, required=True)
    parser.add_argument("--device-id", type=_byte, required=True, help="Measurement device ID in 0..254")
    parser.add_argument("--channel", type=_byte, required=True, help="Measurement channel in 0..254")
    parser.add_argument("--icon-index", type=_number, help="Built-in icon; editable on functional pages when icon display is enabled")
    parser.add_argument("--decimal-places", type=_number, help="Display precision in 0..5")
    for prefix in ("gain", "offset"):
        parser.add_argument("--" + prefix + "-mantissa", type=_number, help="Signed 16-bit scaling mantissa")
        parser.add_argument("--" + prefix + "-exponent", type=_number, help="Signed 8-bit power of ten")
        parser.add_argument("--" + prefix + "-value",
                            help="Decimal value using Toolkit's lossy Measurement editor conversion")
    parser.add_argument("--page-mode", choices=("single", "multiple"))
    for prefix in ("prefix", "suffix", "label"):
        parser.add_argument("--" + prefix + "-text", help="Shared static text; empty text detaches the reference")
        parser.add_argument("--" + prefix + "-index", type=_number,
                            help="Static slot 0..63 or empty 255; label also supports empty sentinel 64")


def _edlt_measurement_settings(args):
    return {name: getattr(args, name) for name in (
        "page", "position", "device_id", "channel", "icon_index", "decimal_places", "gain_mantissa", "gain_exponent",
        "offset_mantissa", "offset_exponent", "gain_value", "offset_value", "page_mode", "prefix_text", "prefix_index", "suffix_text",
        "suffix_index", "label_text", "label_index")}


def _edlt_measurement(args):
    from .edlt_measurement import EdltMeasurementWidget
    from .unitspec import UnitSpecStore
    if args.spec_dir is None:
        raise ValueError("Use --spec-dir or CBUS_UNITSPEC_DIR for decoded vendor specifications")
    return EdltMeasurementWidget(UnitSpecStore(args.spec_dir).load("KEYGL5.xml"))


def _edlt_time_date_options(parser):
    from .edlt_time_date import DISPLAY_TYPES, DATE_FORMATS, TIME_FORMATS
    parser.add_argument("--page", type=_number, required=True, help="0 selects standby; 1..4 select functional pages")
    parser.add_argument("--position", type=_number, required=True, help="Physical display slot within the selected page")
    parser.add_argument("--slices", type=_number, choices=(1, 2),
                        help="Two slices are available at standby positions 1..4; conversion clears the next widget type")
    parser.add_argument("--display", choices=tuple(DISPLAY_TYPES))
    parser.add_argument("--page-mode", choices=("single", "multiple"))
    parser.add_argument("--date-format", type=_number, choices=tuple(DATE_FORMATS),
                        help="Unit-wide date format: " + "; ".join(f"{code}={label}" for code, label in DATE_FORMATS.items()))
    parser.add_argument("--time-format", choices=tuple(TIME_FORMATS), help="Time format for the whole unit")
    parser.add_argument("--leading-zero", action=argparse.BooleanOptionalAction, default=None,
                        help="Enable or disable leading zeroes for all time/date displays")


def _edlt_time_date_settings(args):
    return {name: getattr(args, name) for name in (
        "page", "position", "slices", "display", "page_mode", "date_format", "time_format", "leading_zero")}


def _edlt_time_date(args):
    from .edlt_time_date import EdltTimeDateWidget
    from .unitspec import UnitSpecStore
    if args.spec_dir is None:
        raise ValueError("Use --spec-dir or CBUS_UNITSPEC_DIR for decoded vendor specifications")
    return EdltTimeDateWidget(UnitSpecStore(args.spec_dir).load("KEYGL5.xml"))


def _edlt_hvac_options(parser):
    from .edlt_hvac import TEMPERATURE_UNITS
    parser.add_argument("--page", type=_number, required=True, help="0 selects standby; 1..4 select functional pages")
    parser.add_argument("--position", type=_number, required=True)
    parser.add_argument("--group", type=_byte, required=True, help="HVAC application 172 communication group; 255 is unset")
    parser.add_argument("--zone", type=_number, help="HVAC zone in 0..4")
    parser.add_argument("--decimal-places", type=_number, help="Temperature precision in 0..2")
    parser.add_argument("--units", choices=tuple(TEMPERATURE_UNITS))
    parser.add_argument("--icon-index", type=_number, help="Built-in icon; editable on functional pages when icon display is enabled")
    parser.add_argument("--page-mode", choices=("single", "multiple"))
    parser.add_argument("--label-text", help="Shared static label; empty text detaches the reference")
    parser.add_argument("--label-index", type=_number, help="Static slot 0..63 or empty 255")


def _edlt_hvac_settings(args):
    return {name: getattr(args, name) for name in (
        "page", "position", "group", "zone", "decimal_places", "units", "icon_index", "page_mode", "label_text", "label_index")}


def _edlt_hvac(args):
    from .edlt_hvac import EdltHVACTemperatureWidget
    from .unitspec import UnitSpecStore
    if args.spec_dir is None:
        raise ValueError("Use --spec-dir or CBUS_UNITSPEC_DIR for decoded vendor specifications")
    return EdltHVACTemperatureWidget(UnitSpecStore(args.spec_dir).load("KEYGL5.xml"))


def _edlt_display_options(parser):
    parser.add_argument("--large-text", choices=("label", "status"), help="Choose which text line is larger across the unit")
    for flag, text in (("big-icons", "icon display"), ("timer-flash", "Timer widget flashing"),
                       ("fan-level-wrap", "Fan and Multi Level wrapping")):
        parser.add_argument("--" + flag, action=argparse.BooleanOptionalAction, default=None,
                            help="Enable or disable " + text + " for the whole unit")


def _edlt_display_settings(args):
    return {name: getattr(args, name) for name in ("large_text", "big_icons", "timer_flash", "fan_level_wrap")}


def _edlt_display(args):
    from .edlt_display import EdltDisplaySettings
    from .unitspec import UnitSpecStore
    if args.spec_dir is None:
        raise ValueError("Use --spec-dir or CBUS_UNITSPEC_DIR for decoded vendor specifications")
    return EdltDisplaySettings(UnitSpecStore(args.spec_dir).load("KEYGL5.xml"))


def _edlt_mra_globals_options(parser):
    parser.add_argument("--multiplexer", type=_number, help="MRA multiplexer 1..3, shared by all MRA widgets")
    parser.add_argument("--zone", type=_number, help="MRA zone 1..8, shared by all MRA widgets")


def _edlt_general_options(parser):
    parser.add_argument("--long-press-ms", type=_number, help="25..6375 milliseconds in steps of25")
    parser.add_argument("--debounce-ms", type=_number, help="0..6375 milliseconds in steps of25")
    parser.add_argument("--status-report-seconds", type=_number, help="Unit-wide status report interval in3..255 seconds")
    parser.add_argument("--tools-page-locked", action=argparse.BooleanOptionalAction, default=None,
                        help="Disable or enable access to the unit's tools page")
    parser.add_argument("--power-restore", choices=("previous", "preset"),
                        help="Select previous levels or configured preset levels after power restoration")


def _edlt_general_settings(args):
    return {name: getattr(args, name) for name in (
        "long_press_ms", "debounce_ms", "status_report_seconds", "tools_page_locked", "power_restore")}


def _edlt_general(args):
    from .edlt_general import EdltGeneralSettings
    from .unitspec import UnitSpecStore
    if args.spec_dir is None:
        raise ValueError("Use --spec-dir or CBUS_UNITSPEC_DIR for decoded vendor specifications")
    return EdltGeneralSettings(UnitSpecStore(args.spec_dir).load("KEYGL5.xml"))


def _edlt_mra_options(parser):
    from .edlt_mra import MRA_WIDGET_TYPES, MRA_VARIANTS, MRA_KEY_MODES, MRA_STATUS_TYPES, RAMP_SECONDS
    parser.add_argument("--page", type=_number, required=True)
    parser.add_argument("--position", type=_number, required=True)
    parser.add_argument("--kind", choices=tuple(MRA_WIDGET_TYPES), required=True)
    parser.add_argument("--variant", choices=tuple(name for variants in MRA_VARIANTS.values() for name in variants))
    _edlt_mra_globals_options(parser)
    parser.add_argument("--page-mode", choices=("single", "multiple"))
    parser.add_argument("--key-mode", choices=tuple(MRA_KEY_MODES), help="Zone Control button function")
    parser.add_argument("--ramp-seconds", type=_number, choices=RAMP_SECONDS, help="Zone Control decrease/increase ramp")
    for name in ("source1", "source2"):
        parser.add_argument("--" + name, type=_number, help="Absolute source 1..7 for Source Select")
    parser.add_argument("--label-text")
    parser.add_argument("--label-index", type=_number)
    parser.add_argument("--status-type", choices=tuple(MRA_STATUS_TYPES), help="Zone Control status display")
    parser.add_argument("--status-text")
    parser.add_argument("--status-index", type=_number)
    parser.add_argument("--on-icon", type=_number, help="Built-in icon; Source Select/Control set both icon bytes")
    parser.add_argument("--off-icon", type=_number, help="Zone Control off icon")


def _edlt_standby_options(parser):
    from .edlt_standby import DESTINATIONS, NIGHTLIGHT_COLOURS
    parser.add_argument("--enabled", action=argparse.BooleanOptionalAction, default=None,
                        help="Enable or disable standby; enabling applies the original timeout default before --after-seconds")
    parser.add_argument("--after-seconds", type=_number, help="Standby timeout in 1..255 seconds")
    parser.add_argument("--timeout-page", choices=tuple(DESTINATIONS), help="Page to show after the standby timeout")
    parser.add_argument("--nightlight-user-keys", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--nightlight-page-key", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--nightlight-colour", choices=tuple(NIGHTLIGHT_COLOURS), help="Colour source for enabled nightlight keys")


def _edlt_standby_settings(args):
    return {"enabled": args.enabled, "after_seconds": args.after_seconds, "destination": args.timeout_page,
            "nightlight_user_keys": args.nightlight_user_keys, "nightlight_page_key": args.nightlight_page_key,
            "nightlight_colour": args.nightlight_colour}


def _edlt_standby(args):
    from .edlt_standby import EdltStandby
    from .unitspec import UnitSpecStore
    if args.spec_dir is None:
        raise ValueError("Use --spec-dir or CBUS_UNITSPEC_DIR for decoded vendor specifications")
    return EdltStandby(UnitSpecStore(args.spec_dir).load("KEYGL5.xml"))


def _edlt_colours_options(parser):
    from .edlt_colours import COLOUR_OPTIONS, BRIGHTNESS_OPTIONS, GROUP_OPTIONS
    for name, (_, palette) in COLOUR_OPTIONS.items():
        parser.add_argument("--" + name.replace("_", "-"), choices=palette)
    for name in BRIGHTNESS_OPTIONS:
        parser.add_argument("--" + name.replace("_", "-"), type=_byte,
                            help="Fixed brightness in 0..255; its control group must be 255")
    for name in GROUP_OPTIONS:
        parser.add_argument("--" + name.replace("_", "-"), type=_byte,
                            help="Primary application control group in 0..254, or 255 for fixed mode")


def _edlt_colours_settings(args):
    from .edlt_colours import FIELDS
    return {name: getattr(args, name) for name in FIELDS}


def _edlt_colours(args):
    from .edlt_colours import EdltColours
    from .unitspec import UnitSpecStore
    if args.spec_dir is None:
        raise ValueError("Use --spec-dir or CBUS_UNITSPEC_DIR for decoded vendor specifications")
    return EdltColours(UnitSpecStore(args.spec_dir).load("KEYGL5.xml"))


def _edlt_quick_status_options(parser):
    from .edlt_quick_status import MODES
    from .edlt_colours import KEY_COLOURS, SCREEN_COLOURS
    parser.add_argument("--mode", choices=MODES)
    parser.add_argument("--group", type=_byte, help="Primary application Quick Status group in 0..254")
    for name in ("low-threshold", "high-threshold"):
        parser.add_argument("--" + name, type=_byte,
                            help="Original linked-control byte request; low is applied before high when both are supplied")
    for name in ("low-colour", "middle-colour", "high-colour"):
        parser.add_argument("--" + name, choices=tuple(dict.fromkeys((*KEY_COLOURS, *SCREEN_COLOURS))),
                            help="Key palette for off/page-key mode; screen palette for background/text mode")


def _edlt_quick_status_settings(args):
    from .edlt_quick_status import FIELDS
    return {name: getattr(args, name) for name in FIELDS}


def _edlt_quick_status(args):
    from .edlt_quick_status import EdltQuickStatus
    from .unitspec import UnitSpecStore
    if args.spec_dir is None:
        raise ValueError("Use --spec-dir or CBUS_UNITSPEC_DIR for decoded vendor specifications")
    return EdltQuickStatus(UnitSpecStore(args.spec_dir).load("KEYGL5.xml"))


def _edlt_percentage_value(value):
    from .edlt_percentage import percentage_to_byte
    try:
        return percentage_to_byte(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def _edlt_activation_options(parser):
    from .edlt_activation import WAKE_MODES, ACTIVATION_PAGES
    parser.add_argument("--wake-mode", choices=tuple(WAKE_MODES))
    parser.add_argument("--group", type=_byte, help="Numeric event group; 255 is unused")
    level = parser.add_mutually_exclusive_group()
    level.add_argument("--level", type=_byte, help="Primary-event level byte in 0..255")
    level.add_argument("--level-percent", dest="level", type=_edlt_percentage_value,
                       help="Primary-event percentage in 0..100, using Toolkit decimal conversion")
    parser.add_argument("--action-selector", type=_byte, help="Trigger-event action byte in 0..255; requires a group")
    parser.add_argument("--activation-page", choices=tuple(ACTIVATION_PAGES),
                        help="Page shown when leaving standby; requires the standby timeout page")
    parser.add_argument("--ignore-first-key-press", action=argparse.BooleanOptionalAction, default=None,
                        help="Ignore the waking key press; requires key-press mode and current/page-1 timeout destination")


def _edlt_activation_settings(args):
    return {"wake_mode": args.wake_mode, "group": args.group, "level": args.level,
            "action": args.action_selector, "activation_page": args.activation_page,
            "ignore_first_key_press": args.ignore_first_key_press}


def _edlt_activation(args):
    from .edlt_activation import EdltActivation
    from .unitspec import UnitSpecStore
    if args.spec_dir is None:
        raise ValueError("Use --spec-dir or CBUS_UNITSPEC_DIR for decoded vendor specifications")
    return EdltActivation(UnitSpecStore(args.spec_dir).load("KEYGL5.xml"))


def _edlt_page_control_options(parser):
    parser.add_argument("--group", type=_byte, help="Enable application 203 group in 0..254; 255 disables Page Control")


def _edlt_page_control(args):
    from .edlt_page_control import EdltPageControl
    from .unitspec import UnitSpecStore
    if args.spec_dir is None:
        raise ValueError("Use --spec-dir or CBUS_UNITSPEC_DIR for decoded vendor specifications")
    return EdltPageControl(UnitSpecStore(args.spec_dir).load("KEYGL5.xml"))


def _edlt_lifecycle(args):
    from .edlt_lifecycle import EdltLifecycle
    from .unitspec import UnitSpecStore
    if args.spec_dir is None:
        raise ValueError("Use --spec-dir or CBUS_UNITSPEC_DIR for decoded vendor specifications")
    return EdltLifecycle(UnitSpecStore(args.spec_dir).load("KEYGL5.xml"))


def _edlt_lifecycle_metadata(path):
    from .edlt_lifecycle import LifecycleCache
    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate key in lifecycle metadata: " + key)
            result[key] = value
        return result
    with path.open("rb") as source:
        raw = source.read(256 * 1024 + 1)
    if len(raw) > 256 * 1024:
        raise ValueError("Lifecycle metadata exceeds 256 KiB")
    return LifecycleCache.from_dict(json.loads(raw, object_pairs_hook=unique_keys))


def _edlt_restore_levels_options(parser):
    parser.add_argument("--metadata", type=Path, required=True, help="Lifecycle facts and exact cached display names")
    parser.add_argument("--widget", type=_byte, help="Visible preset control: functional widget 6..21")
    parser.add_argument("--level", type=_byte, help="Preset byte level 0..255")
    parser.add_argument("--synchronise", action="store_true", help="A changed value updates all 16 preset controls")
    parser.add_argument("--restore-mode", choices=("preset", "previous"))
    parser.add_argument("--page-mode", choices=("single", "multiple"))


def _edlt_restore_levels(args):
    from .edlt_restore_levels import EdltRestoreLevels
    from .unitspec import UnitSpecStore
    if args.spec_dir is None:
        raise ValueError("Use --spec-dir or CBUS_UNITSPEC_DIR for decoded vendor specifications")
    return EdltRestoreLevels(UnitSpecStore(args.spec_dir).load("KEYGL5.xml"))


def _edlt_restore_levels_settings(args):
    from .edlt_restore_levels import RestoreLevelCache
    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate key in restore metadata: " + key)
            result[key] = value
        return result
    with args.metadata.open("rb") as source:
        raw = source.read(2 * 1024 * 1024 + 1)
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError("Restore metadata exceeds 2 MiB")
    metadata = RestoreLevelCache.from_dict(json.loads(raw, object_pairs_hook=unique_keys))
    if (args.widget is None) != (args.level is None) or args.synchronise and args.widget is None:
        raise ValueError("A preset edit requires both --widget and --level")
    if args.widget is not None and not 6 <= args.widget <= 21:
        raise ValueError("Preset widget must be in 6..21")
    return {"metadata": metadata, **{name: getattr(args, name) for name in
            ("widget", "level", "synchronise", "restore_mode", "page_mode")}}


def _edlt_blank(args):
    from .edlt_blank import EdltBlankWidget
    from .unitspec import UnitSpecStore
    if args.spec_dir is None:
        raise ValueError("Use --spec-dir or CBUS_UNITSPEC_DIR for decoded vendor specifications")
    return EdltBlankWidget(UnitSpecStore(args.spec_dir).load("KEYGL5.xml"))


def _edlt_blank_options(parser):
    parser.add_argument("--metadata", type=Path, required=True, help="Caller-supplied lifecycle cache JSON")
    parser.add_argument("--page", type=_number, required=True, help="Page 0 is standby; functional pages are 1..4")
    parser.add_argument("--position", type=_number, required=True, help="Visible widget position on the selected page")


def _edlt_blank_settings(args):
    return {"metadata": _edlt_lifecycle_metadata(args.metadata), "page": args.page, "position": args.position}


def _edlt_scene_manager(args):
    from .edlt_scene_manager_cli import editor
    return editor(args)


def _edlt_scene_manager_options(parser, *, state_only=False):
    from .edlt_scene_manager_cli import options
    options(parser, state_only=state_only)


def _edlt_scene_manager_settings(args):
    from .edlt_scene_manager_cli import settings
    return settings(args)


def _edlt_scene_capture(args, client):
    from .edlt_scene_live_cli import editor
    return editor(args, client)


def _edlt_scene_capture_settings(args):
    from .edlt_scene_live_cli import settings
    return settings(args)


def _edlt_reset(args):
    from .edlt_reset_cli import editor
    return editor(args)


def _edlt_reset_settings(args):
    from .edlt_reset_cli import settings
    return settings(args)


def _edlt_applications(args):
    from .edlt_control_cli import editor
    return editor(args, "applications")


def _edlt_corridor(args):
    from .edlt_control_cli import editor
    return editor(args, "corridor")


def _edlt_ordered_options(parser, kind):
    from .edlt_control_cli import options
    options(parser, kind)


def _edlt_ordered_settings(args, kind):
    from .edlt_control_cli import settings
    return settings(args, kind)


def _edlt_ordered_payload(error, args=None):
    result = {}
    for name in ("edlt_applications_evidence", "edlt_corridor_evidence", "edlt_blank_evidence", "edlt_reset_evidence", "edlt_scene_manager_evidence", "edlt_scene_live_evidence"):
        evidence = getattr(error, name, None)
        if isinstance(evidence, dict): result[name] = evidence
    state = getattr(args, "_ordered_control_state", None)
    if isinstance(state, dict) and isinstance(state.get("evidence"), dict):
        result.setdefault("edlt_" + state["kind"] + "_evidence", state["evidence"])
    return result


def _edlt_navigation_options(parser):
    from .edlt_navigation import PAGE_MODES, NAVIGATION_VARIANTS, TEMPERATURE_SOURCES
    parser.add_argument("--page-mode", choices=tuple(PAGE_MODES))
    parser.add_argument("--variant", choices=tuple(NAVIGATION_VARIANTS))
    parser.add_argument("--temperature-source", choices=tuple(TEMPERATURE_SOURCES))
    parser.add_argument("--device-or-group", type=_byte, help="Measurement device or HVAC application 172 group")
    parser.add_argument("--channel-or-zone", type=_byte, help="Measurement channel 0..255 or HVAC zone 0..4")
    parser.add_argument("--dynamic-group", type=_byte, help="Primary application group for logo or dynamic labels; 255 is unused")
    parser.add_argument("--page-name", nargs=2, action="append", metavar=("PAGE", "TEXT"),
                        help="Static name for page 1..4; repeat for distinct pages; empty text detaches")
    parser.add_argument("--page-name-index", nargs=2, action="append", metavar=("PAGE", "INDEX"),
                        help="Static slot 0..63/255, or a dynamic variant present in --metadata")
    parser.add_argument("--metadata", type=Path, help="Caller-supplied navigation group metadata JSON")


def _edlt_navigation_settings(args):
    from .edlt_navigation import NavigationMetadata
    settings = {name: getattr(args, name) for name in (
        "page_mode", "variant", "temperature_source", "device_or_group", "channel_or_zone", "dynamic_group")}
    for argument, name, parse in ((args.page_name, "page_names", str),
                                  (args.page_name_index, "page_name_indices", _number)):
        values = {}
        for page, value in argument or ():
            try:
                page, value = _number(page), parse(value)
            except argparse.ArgumentTypeError as error:
                raise ValueError(str(error)) from error
            if page not in range(1, 5) or page in values:
                raise ValueError("Page names require distinct pages in 1..4")
            values[page] = value
        settings[name] = values
    if args.metadata is not None:
        def unique_keys(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("Duplicate key in navigation metadata: " + key)
                result[key] = value
            return result
        with args.metadata.open("rb") as source:
            raw = source.read(256 * 1024 + 1)
        if len(raw) > 256 * 1024:
            raise ValueError("Navigation metadata exceeds 256 KiB")
        settings["metadata"] = NavigationMetadata.from_dict(json.loads(raw, object_pairs_hook=unique_keys))
    return settings


def _edlt_navigation(args):
    from .edlt_navigation import EdltNavigation
    from .unitspec import UnitSpecStore
    if args.spec_dir is None:
        raise ValueError("Use --spec-dir or CBUS_UNITSPEC_DIR for decoded vendor specifications")
    return EdltNavigation(UnitSpecStore(args.spec_dir).load("KEYGL5.xml"))


def _edlt_mra_settings(args):
    return {name: getattr(args, name) for name in (
        "page", "position", "kind", "variant", "multiplexer", "zone", "page_mode", "key_mode", "ramp_seconds",
        "source1", "source2", "label_text", "label_index", "status_type", "status_text", "status_index", "on_icon", "off_icon")}


def _edlt_mra(args):
    from .edlt_mra import EdltMRAWidget
    from .unitspec import UnitSpecStore
    if args.spec_dir is None:
        raise ValueError("Use --spec-dir or CBUS_UNITSPEC_DIR for decoded vendor specifications")
    return EdltMRAWidget(UnitSpecStore(args.spec_dir).load("KEYGL5.xml"))


def _edlt_scene_settings(args):
    return {"scenes": args.cycle_scenes, **{name: getattr(args, name) for name in (
        "page", "position", "scene", "page_mode", "label_type", "label_index",
        "status_type", "status_index", "status_text", "mode", "ramp_seconds", "offset", "cycle_variant")}}


def _edlt_scene(args):
    from .edlt_scene import EdltSceneWidget
    from .unitspec import UnitSpecStore
    if args.spec_dir is None:
        raise ValueError("Use --spec-dir or CBUS_UNITSPEC_DIR for decoded vendor specifications")
    return EdltSceneWidget(UnitSpecStore(args.spec_dir).load("KEYGL5.xml"))


def _edlt_scene_table(args):
    from .edlt_scenes import EdltSceneTable
    from .unitspec import UnitSpecStore
    if args.spec_dir is None:
        raise ValueError("Use --spec-dir or CBUS_UNITSPEC_DIR for decoded vendor specifications")
    return EdltSceneTable(UnitSpecStore(args.spec_dir).load("KEYGL5.xml"))


def _edlt_scene_definitions(path):
    from .edlt_scenes import SceneDefinition
    with path.open("rb") as source:
        data = source.read(1024 * 1024 + 1)
    if len(data) > 1024 * 1024:
        raise ValueError("Scene table input exceeds 1 MiB")
    value = json.loads(data)
    if not isinstance(value, list) or len(value) > 8:
        raise ValueError("Scene table input must be an ordered array of up to eight scene definitions")
    return tuple(SceneDefinition.from_dict(row) for row in value)


def _device_scene_options(parser):
    from .device_scenes import RAMP_SECONDS
    parser.add_argument("--scene", type=_number, required=True, help="Stored scene number in 1..8")
    entries = parser.add_mutually_exclusive_group()
    entries.add_argument("--entry", action="append", help="GROUP=LEVEL in byte values; repeat up to ten times")
    entries.add_argument("--entries", type=Path, help="JSON array of {group, level} entries")
    entries.add_argument("--clear", action="store_true", help="Clear the last populated scene; renumbering is unsupported")
    parser.add_argument("--key", dest="key_number", type=_number, help="Bind the physical KEYE1 key (1)")
    rates = parser.add_mutually_exclusive_group()
    rates.add_argument("--ramp-rate", type=_number, help="Native scene ramp selector in 0..15")
    rates.add_argument("--ramp-seconds", type=_number, choices=RAMP_SECONDS)
    parser.add_argument("--action-selector", type=_byte)
    parser.add_argument("--trigger-group", type=_byte, help="Shared Trigger Control group; 255 is unassigned")
    parser.add_argument("--allow-shared-trigger-group", action="store_true")


def _device_scene_settings(args):
    from .device_scenes import SceneEntry, RAMP_SECONDS
    entries = None
    if args.clear:
        entries = []
    elif args.entry is not None:
        entries = []
        for value in args.entry:
            group, separator, level = value.partition("=")
            if not separator:
                raise ValueError("Scene entries must have the form GROUP=LEVEL")
            try:
                entries.append(SceneEntry(_byte(group), _byte(level)))
            except argparse.ArgumentTypeError as error:
                raise ValueError(str(error)) from error
    elif args.entries is not None:
        with args.entries.open("rb") as handle:
            data = handle.read(1024 * 1024 + 1)
        if len(data) > 1024 * 1024:
            raise ValueError("Scene entry file exceeds 1 MiB")
        rows = json.loads(data)
        if not isinstance(rows, list) or len(rows) > 10 or any(
                not isinstance(row, dict) or set(row) != {"group", "level"} for row in rows):
            raise ValueError("Scene entry file must contain up to ten {group, level} objects")
        entries = [SceneEntry(**row) for row in rows]
    return {"entries": entries, "key": args.key_number,
            "ramp_rate": args.ramp_rate if args.ramp_seconds is None else RAMP_SECONDS.index(args.ramp_seconds),
            **{name: getattr(args, name) for name in (
                "scene", "action_selector", "trigger_group", "allow_shared_trigger_group")}}


def _device_scenes(args):
    from .device_scenes import DeviceScenes
    from .unitspec import UnitSpecStore
    if args.spec_dir is None:
        raise ValueError("Use --spec-dir or CBUS_UNITSPEC_DIR for decoded vendor specifications")
    return DeviceScenes(UnitSpecStore(args.spec_dir).load("KEYE.xml"))


def _unit_templates(args):
    from .unit_templates import PROFILES, UnitTemplates
    from .unitspec import UnitSpecStore
    if args.spec_dir is None:
        raise ValueError("Use --spec-dir or CBUS_UNITSPEC_DIR for decoded vendor specifications")
    profile = PROFILES[args.profile]
    return UnitTemplates(UnitSpecStore(args.spec_dir).load(profile[3]), firmware=profile[1], catalog_number=profile[2])


def _read_unit_template(path):
    from .unit_templates import UnitTemplate
    with path.open("rb") as source:
        return UnitTemplate.from_xml(source.read(1024 * 1024 + 1))


def _write_unit_template(path, template):
    with path.open("x", encoding="utf-8", newline="") as target:
        target.write(template.to_xml())
    return {"file": str(path), **template.as_dict()}


def _firmware(args):
    if args.action.startswith("usb-dfu-"):
        from .dfu import MAX_IMAGE_SIZE
        from .dfu_transport import parse_descriptors
        from .firmware_usb import run_usb_dfu
        with args.device_descriptor.open("rb") as source:
            device = source.read(19)
        with args.configuration_descriptor.open("rb") as source:
            configuration = source.read(65536)
        descriptor = parse_descriptors(device, configuration)
        data = None
        if args.action == "usb-dfu-program":
            with args.file.open("rb") as source:
                data = source.read(MAX_IMAGE_SIZE + 1)
        result = run_usb_dfu(args.action.removeprefix("usb-dfu-"),
            descriptor=descriptor, data=data, address_offset=getattr(args, "offset", None),
            length=getattr(args, "length", None), **{name: getattr(args, name) for name in (
                "bus", "address", "expected_serial", "release_policy", "flash_size", "application_start",
                "external", "timeout", "inspection_timeout", "poll_limit")})
        return result, int(not result["complete"])
    if args.action in ("usb-list", "usb-inspect"):
        from .usb_inspection import inspect_edlt_device, list_edlt_devices
        result = (list_edlt_devices(max_devices=args.max_devices) if args.action == "usb-list" else
                  inspect_edlt_device(bus=args.bus, address=args.address,
                                      expected_serial=args.expected_serial, timeout=args.timeout))
        return result.as_dict(), int(not result.complete)
    if args.action.startswith("dfu-"):
        from .dfu import MAX_IMAGE_SIZE, inspect_image, parse_command, parse_status, plan_binary
        if args.action in ("dfu-status", "dfu-command"):
            if len(args.hex) > 256:
                raise ValueError("DFU record hex text exceeds 256 characters")
            try:
                data = bytes.fromhex(args.hex)
            except ValueError as error:
                raise ValueError("DFU record must contain hexadecimal byte pairs") from error
            if args.action == "dfu-status":
                parsed = parse_status(data)
                result, status = parsed.as_dict(), int(parsed.status != 0 or parsed.state == 10)
            else:
                result = parse_command(data).as_dict()
                status = int(not result["supported"])
        elif args.action == "dfu-descriptors":
            from .dfu_transport import parse_descriptors
            with args.device_file.open("rb") as source:
                device = source.read(19)
            with args.configuration_file.open("rb") as source:
                configuration = source.read(65536)
            result = {**parse_descriptors(device, configuration).as_dict(),
                      "physical_device_verified": False, "scope": "Offline validation of supplied descriptor bytes"}
            status = 0
        elif args.action == "dfu-inspect":
            with args.file.open("rb") as source:
                data = source.read(MAX_IMAGE_SIZE + 1)
            result = inspect_image(data, vendor_id=args.vendor_id, product_id=args.product_id).as_dict()
            status = int(not result["supported"])
        else:
            result = plan_binary(args.length, **{name: getattr(args, name) for name in
                                 ("address", "flash_size", "application_start", "external", "transfer_size")})
            status = 0
        return {"format": "cbus-" + args.action + "-v1", **result, "read_only": True,
                "firmware_written": False}, status
    from .firmware_diagnostics import (SerialDiagnostics, classify_hardware, compare_package,
                                       inspect_package, parse_identification, parse_ncc_versions)
    if args.action == "inspect-package":
        result = inspect_package(args.file)
        return result, int(bool(result["native_invalid_entries"]))
    if args.action == "classify-hardware":
        result = {"hardware_version": args.version, "variant": classify_hardware(args.version)}
        return result, int(result["variant"] == "Unknown")
    if args.action in ("parse-id", "parse-ncc"):
        with args.file.open("rb") as source:
            data = source.read(65537)
        parsed = (parse_identification if args.action == "parse-id" else parse_ncc_versions)(data)
    else:
        diagnostic = SerialDiagnostics(args.port, timeout=args.timeout)
        parsed = diagnostic.identify() if args.action == "identify" else diagnostic.ncc_versions()
    result = parsed.as_dict()
    status = int(not result["complete"] or result["ambiguous"] or result.get("usable_identity") is False)
    if getattr(args, "package", None):
        result["package"] = compare_package(parsed, inspect_package(args.package))
        status = int(bool(status) or not result["package"]["metadata_match"])
    return result, status


def build_parser():
    parser = argparse.ArgumentParser(prog="cbus-toolkit", description="C-Bus commissioning CLI. Use coverage to inspect verified scope.")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--compact", action="store_true", help="Emit single-line JSON")
    commands = parser.add_subparsers(dest="area", required=True)
    from .toolkit_preferences_cli import options as preference_options
    preference_options(commands)
    from .toolkit_updates_cli import options as update_options
    update_options(commands)
    from .toolkit_update_metadata_cli import options as metadata_options
    metadata_options(commands)
    from .toolkit_update_revocation_cli import options as revocation_options
    revocation_options(commands)
    from .toolkit_update_conditions_cli import options as condition_options
    condition_options(commands)
    from .toolkit_live_update_conditions_cli import options as live_condition_options
    live_condition_options(commands)
    from .pci_routing_cli import options as routing_options
    routing_options(commands)
    from .toolkit_about_cli import options as about_options
    about_options(commands)
    from .toolkit_database_csv_cli import options as database_csv_options
    database_csv_options(commands)
    from .thermostat_temperature_cli import options as thermostat_temperature_options
    thermostat_temperature_options(commands)
    from .thermostat_scheduling_cli import options as thermostat_scheduling_options
    thermostat_scheduling_options(commands)

    project = commands.add_parser("project", help="Edit legacy Toolkit XML/CBZ projects without discarding unknown data")
    ops = project.add_subparsers(dest="action", required=True)
    from .project_repair_cli import options as project_repair_options
    project_repair_options(ops)
    create = ops.add_parser("new")
    create.add_argument("file", type=Path)
    create.add_argument("--name", required=True)
    create.add_argument("--description", default="")
    create.add_argument("--format", choices=("xml", "cbz"))
    for action in ("inspect", "validate", "list", "get", "export", "add", "set", "delete", "copy", "move", "field-get", "field-set", "field-delete", "parameters", "parameter-set", "parameter-delete"):
        p = ops.add_parser(action)
        p.add_argument("file", type=Path)
        if action not in ("inspect", "validate", "export", "add"):
            p.add_argument("path", nargs="?" if action in ("list", "get") else None, default="/")
        if action in ("list", "add"):
            p.add_argument("--kind", choices=("network", "application", "group", "level", "unit"), required=action == "add")
        if action == "list":
            p.add_argument("--recursive", action="store_true")
        if action in ("add", "copy", "move"):
            p.add_argument("--parent", default="/" if action == "add" else None, required=action != "add")
            p.add_argument("--address", type=_byte, required=action == "add")
            p.add_argument("--name", default="" if action == "add" else None)
        if action in ("add", "set"):
            p.add_argument("--field", action="append", default=[])
        if action == "delete":
            p.add_argument("--cascade", action="store_true", help="Also remove descendant entities; external OID references still prevent deletion")
        if action.startswith("field-"):
            p.add_argument("field")
        if action.startswith("parameter-"):
            p.add_argument("name")
        if action in ("field-set", "parameter-set"):
            p.add_argument("value")
        if action == "export":
            p.add_argument("output", type=Path)
            p.add_argument("--format", choices=("xml", "cbz"), required=True)
        if action in ("add", "set", "delete", "copy", "move", "field-set", "field-delete", "parameter-set", "parameter-delete"):
            p.add_argument("--output", type=Path, help="Write to a copy instead of updating the input file")

    cgate = commands.add_parser("cgate", help="Issue C-Gate commands using a persistent, correlated connection")
    cgate.add_argument("--host", default="127.0.0.1")
    cgate.add_argument("--port", type=int)
    cgate.add_argument("--timeout", type=_positive, default=10.0)
    cgate.add_argument("--tls", action="store_true")
    cgate.add_argument("--ca", type=Path)
    cgate.add_argument("--cert", type=Path)
    cgate.add_argument("--key", type=Path)
    cgops = cgate.add_subparsers(dest="action", required=True)
    p = cgops.add_parser("edlt-labels", help="Read live KEYGL5 labels through cmqttd, without Windows or a second CNI connection")
    label_scope = p.add_mutually_exclusive_group(required=True)
    label_scope.add_argument("address", nargs="?", help="Fully qualified physical unit, e.g. //PROJECT/254/p/5")
    label_scope.add_argument("--network", help="Freshly discover and read every supported eDLT on //PROJECT/NETWORK")
    from .repositories_cli import register as repository_options
    repository_options(cgops)
    from .thermostat_schedule_cli import compose_options, options as schedule_options
    schedule_parser = cgops.add_parser("thermostat-schedule-levels", help="Preview or create thermostat scheduling levels in a closed project")
    schedule_options(schedule_parser)
    compose_parser = cgops.add_parser("thermostat-schedule-compose", help="Preview or compose thermostat scheduling from a closed database unit")
    compose_options(compose_parser)
    from .toolkit_database_csv_cli import live_options as database_csv_live_options
    database_csv_live_parser = cgops.add_parser(
        "database-csv", help="Export admitted units from a read-only live C-Gate database snapshot")
    database_csv_live_options(database_csv_live_parser)
    from .edlt_global_cli import options as global_options
    global_parser = cgops.add_parser("edlt-global", help="Copy selected eDLT categories to existing closed database units")
    global_parser.add_argument("--spec-dir", type=Path, default=os.environ.get("CBUS_UNITSPEC_DIR"))
    global_options(global_parser, native=True)
    from .edlt_scene_live_cli import options as scene_live_options
    live_parser = cgops.add_parser("edlt-scene-broadcast", help="Broadcast retained scene levels using immediate forced ramps")
    live_parser.add_argument("--spec-dir", type=Path, default=os.environ.get("CBUS_UNITSPEC_DIR"))
    scene_live_options(live_parser, broadcast=True)
    ex = cgops.add_parser("exec", help="One exact C-Gate command; preserves spaces and quotes")
    ex.add_argument("command")
    batch = cgops.add_parser("run", help="Run a UTF-8 file of commands in one session; stop on first error")
    batch.add_argument("file", type=Path)
    events = cgops.add_parser("events", help="Stream JSON event records and report any lost events")
    events.add_argument("--mode", default="e8s1c1", help="Native event mode, such as e8s1c1")
    event_limit = events.add_mutually_exclusive_group()
    event_limit.add_argument("--count", type=_number, default=1, help="Stop after this many events")
    event_limit.add_argument("--follow", action="store_true", help="Continue until interrupted; --timeout is the maximum idle wait")
    events.add_argument("--state", help="Request the current state of this already loaded network or C-Group")
    trigger = cgops.add_parser("trigger", help="Trigger events, indicator kill and cached application state")
    trigops = trigger.add_subparsers(dest="remote_action", required=True)
    for action in ("event", "kill", "get", "state", "groups"):
        p = trigops.add_parser(action)
        p.add_argument("address", help="Trigger group address, or application for groups")
        if action == "event":
            p.add_argument("selector", help="Byte, percent or a named level tag")
            p.add_argument("--force", action="store_true")
        if action == "get":
            p.add_argument("attribute", default="*", nargs="?")
    enable = cgops.add_parser("enable", help="Set Enable variables, request saved-value removal and query cached state")
    enops = enable.add_subparsers(dest="remote_action", required=True)
    for action in ("set", "remove", "get", "level", "state", "groups"):
        p = enops.add_parser(action)
        p.add_argument("address")
        if action == "set":
            p.add_argument("value", help="Byte, percent or a named level tag")
            p.add_argument("--force", action="store_true")
        if action == "get":
            p.add_argument("attribute", default="*", nargs="?")
    for action in ("on", "off", "get", "ramp", "stop"):
        p = cgops.add_parser(action)
        p.add_argument("address")
        if action == "get":
            p.add_argument("attribute", default="level", nargs="?")
        if action == "ramp":
            p.add_argument("level", type=_byte)
            p.add_argument("--seconds", type=_number, default=0)

    label = cgops.add_parser("label", help="Queue native dynamic-label messages; device receipt is not implied")
    label.add_argument("--family", choices=("lighting", "trigger", "enable"), default="lighting")
    labelops = label.add_subparsers(dest="remote_action", required=True)
    for action in ("text", "unicode", "raw", "unicode-raw", "icon", "dynamic", "language", "clear"):
        p = labelops.add_parser(action)
        p.add_argument("application")
        p.add_argument("group", type=_byte)
        p.add_argument("--language", type=_byte, default=0, required=action == "language")
        p.add_argument("--action-selector", type=_byte)
        if action != "language":
            p.add_argument("--variant", type=_number, choices=range(4), default=0)
        if action in ("text", "unicode"):
            p.add_argument("text")
        if action in ("raw", "unicode-raw", "dynamic"):
            p.add_argument("data", help="Contiguous hexadecimal bytes")
        if action == "raw":
            p.add_argument("--options", type=_byte, required=True)
        if action in ("icon", "dynamic"):
            p.add_argument("--icon", type=_number, required=True)
        if action == "dynamic":
            p.add_argument("--width", type=_number, required=True)
            p.add_argument("--height", type=_number, required=True)
            p.add_argument("--vertical-offset", type=_byte, default=0)
        if action == "clear":
            p.add_argument("--unicode", dest="unicode_label", action="store_true")
    p = labelops.add_parser(
        "cache-clear",
        help="Request native LABEL CLEAR for every cached key or one key; erasure is not verified",
    )
    p.add_argument("application", type=_label_application)
    p.add_argument("unit", type=_byte)
    p.add_argument("--key", dest="key_number", type=_number, choices=range(1, 9))

    clear_labels = cgops.add_parser("edlt-label-clear", help="Plan or request one eDLT dynamic-label clear; no physical erasure verification")
    clear_ops = clear_labels.add_subparsers(dest="remote_action", required=True)
    for action in ("plan", "request"):
        p = clear_ops.add_parser(action, help="Refresh an already open idle network" if action == "plan" else "Repeat identity guards and send one clear request")
        p.add_argument("source", help="One physical //PROJECT/NETWORK/p/UNIT path")
        p.add_argument("--serial", required=True, help="Expected native unit serial")
        p.add_argument("--plan-output", type=Path, help="Exclusively create and flush pre-request evidence before any clear request")

    factory_default = cgops.add_parser(
        "edlt-factory-default",
        help="Plan or request one destructive physical KEYGL5 FactoryDefault control",
    )
    factory_ops = factory_default.add_subparsers(dest="remote_action", required=True)
    for action in ("plan", "request"):
        p = factory_ops.add_parser(
            action,
            help="Refresh an already open idle network"
            if action == "plan"
            else "Repeat identity guards and send one non-replayed FactoryDefault request",
        )
        p.add_argument("source", help="One physical //PROJECT/NETWORK/p/UNIT path")
        p.add_argument("--serial", required=True, help="Expected native unit serial")
        p.add_argument(
            "--plan-output",
            type=Path,
            help="Exclusively create and flush pre-request evidence before the reset request",
        )

    network = cgops.add_parser("network", help="Explicit native network lifecycle, discovery and commissioning")
    netops = network.add_subparsers(dest="remote_action", required=True)
    p = netops.add_parser("list")
    p.add_argument("--project")
    for action in ("state", "open", "close", "sync", "sync-new", "discover", "check-units", "unravel", "clocks", "tree", "rename", "set-project", "wait-ready", "calculate"):
        p = netops.add_parser(action)
        p.add_argument("address")
        if action == "sync":
            p.add_argument("--fast", action="store_true")
            p.add_argument("--retries", type=_byte)
        if action in ("check-units", "unravel", "sync-new"):
            p.add_argument("--unit", type=_byte, action="append" if action != "sync-new" else "store")
        if action == "unravel":
            p.add_argument("--match-database", action="store_true")
        if action == "clocks":
            choice = p.add_mutually_exclusive_group()
            choice.add_argument("--target", type=_byte)
            choice.add_argument("--recover", action="store_true")
        if action == "tree":
            p.add_argument("--xml", action="store_true")
            p.add_argument("--details", action="store_true")
            p.add_argument("--sync", choices=("withsync", "withpsync", "withqsync"), action="append")
        if action == "rename":
            p.add_argument("new_address", type=_byte)
            p.add_argument("--no-fix-references", action="store_true")
        if action == "set-project":
            p.add_argument("project")
        if action == "wait-ready":
            p.add_argument("--wait-seconds", type=_positive, default=30.0)

    projects = cgops.add_parser("project", help="Manage native C-Gate 3 projects through the vendor server")
    prop = projects.add_subparsers(dest="remote_action", required=True)
    for action in ("list", "directory", "new", "use", "load", "save", "close", "delete", "repair", "copy", "rename", "archive", "restore"):
        p = prop.add_parser(action)
        if action not in ("list", "directory"):
            p.add_argument("name")
        if action in ("copy", "rename", "archive", "restore"):
            p.add_argument("other", help="New project name, or server-side archive path")
    database = cgops.add_parser("database", help="Edit the native project tree using C-Gate business rules")
    dbop = database.add_subparsers(dest="remote_action", required=True)
    p = dbop.add_parser("network-new", help="Create a network definition and load its closed model")
    p.add_argument("project")
    p.add_argument("address", type=_byte)
    p.add_argument("name")
    p.add_argument("interface_type", choices=("Serial", "Cni", "Bridge"))
    p.add_argument("interface_address")
    p = dbop.add_parser("unit-new", help="Create a database unit with vendor defaults, including large-memory units")
    p.add_argument("network", help="Fully qualified network, e.g. //TEST/254")
    p.add_argument("address", type=_byte)
    p.add_argument("name")
    p.add_argument("unit_type")
    p.add_argument("firmware")
    p.add_argument("--catalog-number")
    for action in ("get", "get-xml", "set", "add", "copy", "delete", "validate", "rename-network"):
        p = dbop.add_parser(action)
        p.add_argument("path")
        if action == "set":
            p.add_argument("value")
        if action == "add":
            p.add_argument("kind", choices=("network", "application", "group", "unit", "level", "netvar"))
        if action == "copy":
            p.add_argument("parent")
        if action in ("add", "copy", "rename-network"):
            p.add_argument("address", type=_byte)
        if action in ("add", "copy"):
            p.add_argument("name")

    unit = cgops.add_parser("unit", help="Edit a unit through a native C-Gate programming session")
    unit.add_argument("--lock-address", required=True, help="Network/unit to lock, e.g. //TEST/254")
    source = unit.add_mutually_exclusive_group(required=True)
    source.add_argument("--source", help="Explicit PP source; use /db//TEST/254/p/20 for database-only work")
    source.add_argument("--unit-type", help="Initialize a new temporary unit from vendor defaults")
    unit.add_argument("--firmware", help="Required with --unit-type")
    unit.add_argument("--catalog-number")
    unit.add_argument("--destination", help="Explicit PP destination; defaults to --source for edits")
    unit.add_argument("--dry-run", action="store_true", help="Stage and report edits without saving them")
    unops = unit.add_subparsers(dest="remote_action", required=True)
    unops.add_parser("show")
    for action in ("get", "info"):
        p = unops.add_parser(action)
        p.add_argument("parameter", default="*", nargs="?")
    p = unops.add_parser("set")
    p.add_argument("parameter")
    p.add_argument("value")
    unops.add_parser("reset-defaults")
    p = unops.add_parser("export")
    p.add_argument("file", type=Path)
    p = unops.add_parser("import")
    p.add_argument("file", type=Path)
    p = unops.add_parser("key-macro", help="Configure a classic KEY1/KEY2/KEY4 key preset with verified readback")
    p.add_argument("--spec-dir", type=Path, default=os.environ.get("CBUS_UNITSPEC_DIR"))
    p.add_argument("--spec", required=True, help="Exact classic vendor schema, such as KEY4.xml")
    _key_options(p)
    p = unops.add_parser("neo-key-macro", help="Configure tested Neo-core key presets with scene-selector and block handling")
    p.add_argument("--spec-dir", type=Path, default=os.environ.get("CBUS_UNITSPEC_DIR"))
    p.add_argument("--spec", required=True, help="KEYE.xml, KEYM4.xml, KEYA3.xml or KEYB4.xml")
    _key_options(p, extended=True)

    p = unops.add_parser("sensor-occupancy", help="Configure the tested SENPILL 2.3.00 / 5753PEIRL occupancy profile")
    p.add_argument("--spec-dir", type=Path, default=os.environ.get("CBUS_UNITSPEC_DIR"))
    _sensor_options(p)
    p = unops.add_parser("edlt-lighting", help="Configure tested KEYGL5 5.5.00 / 5055EDL lighting widgets in the database")
    p.add_argument("--spec-dir", type=Path, default=os.environ.get("CBUS_UNITSPEC_DIR"))
    _edlt_options(p)
    p = unops.add_parser("edlt-enable", help="Configure KEYGL5 5.5.00 Enable Off/Preset widgets in the database")
    p.add_argument("--spec-dir", type=Path, default=os.environ.get("CBUS_UNITSPEC_DIR"))
    _edlt_enable_options(p)
    p = unops.add_parser("edlt-shutter", help="Configure KEYGL5 5.5.00 two-key Shutter widgets in the database")
    p.add_argument("--spec-dir", type=Path, default=os.environ.get("CBUS_UNITSPEC_DIR"))
    _edlt_shutter_options(p)
    p = unops.add_parser("edlt-timer", help="Configure KEYGL5 5.5.00 Toggle/Retrigger Timer widgets in the database")
    p.add_argument("--spec-dir", type=Path, default=os.environ.get("CBUS_UNITSPEC_DIR"))
    _edlt_timer_options(p)
    p = unops.add_parser("edlt-fan", help="Configure KEYGL5 5.5.00 Fan widgets and speed status text in the database")
    p.add_argument("--spec-dir", type=Path, default=os.environ.get("CBUS_UNITSPEC_DIR"))
    _edlt_fan_options(p)
    p = unops.add_parser("edlt-multilevel", help="Configure KEYGL5 5.5.00 Multi Level widgets in the database")
    p.add_argument("--spec-dir", type=Path, default=os.environ.get("CBUS_UNITSPEC_DIR"))
    _edlt_multilevel_options(p)
    p = unops.add_parser("edlt-room-courtesy", help="Configure KEYGL5 5.5.00 Room Courtesy widgets in the database")
    p.add_argument("--spec-dir", type=Path, default=os.environ.get("CBUS_UNITSPEC_DIR"))
    _edlt_room_courtesy_options(p)
    p = unops.add_parser("edlt-measurement", help="Configure KEYGL5 5.5.00 Measurement widgets with exact scaling pairs")
    p.add_argument("--spec-dir", type=Path, default=os.environ.get("CBUS_UNITSPEC_DIR"))
    _edlt_measurement_options(p)
    p = unops.add_parser("edlt-time-date", help="Configure KEYGL5 5.5.00 Time/Date widgets and unit-wide display formats")
    p.add_argument("--spec-dir", type=Path, default=os.environ.get("CBUS_UNITSPEC_DIR"))
    _edlt_time_date_options(p)
    p = unops.add_parser("edlt-hvac", help="Configure KEYGL5 5.5.00 HVAC Temperature Display widgets in the database")
    p.add_argument("--spec-dir", type=Path, default=os.environ.get("CBUS_UNITSPEC_DIR"))
    _edlt_hvac_options(p)
    p = unops.add_parser("edlt-display", help="Configure KEYGL5 5.5.00 unit-wide font, icon, timer and wrap settings")
    p.add_argument("--spec-dir", type=Path, default=os.environ.get("CBUS_UNITSPEC_DIR"))
    _edlt_display_options(p)
    p = unops.add_parser("edlt-general", help="Configure KEYGL5 5.5.00 key timing, status reporting, tools-page and restore mode")
    p.add_argument("--spec-dir", type=Path, default=os.environ.get("CBUS_UNITSPEC_DIR"))
    _edlt_general_options(p)
    p = unops.add_parser("edlt-standby", help="Configure KEYGL5 5.5.00 standby timeout, destination page and nightlight keys")
    p.add_argument("--spec-dir", type=Path, default=os.environ.get("CBUS_UNITSPEC_DIR"))
    _edlt_standby_options(p)
    p = unops.add_parser("edlt-colours", help="Configure KEYGL5 5.5.00 colours, brightness and control group references")
    p.add_argument("--spec-dir", type=Path, default=os.environ.get("CBUS_UNITSPEC_DIR"))
    _edlt_colours_options(p)
    p = unops.add_parser("edlt-quick-status", help="Configure KEYGL5 5.5.00 Quick Status modes, group, colours and linked thresholds")
    p.add_argument("--spec-dir", type=Path, default=os.environ.get("CBUS_UNITSPEC_DIR"))
    _edlt_quick_status_options(p)
    p = unops.add_parser("edlt-activation", help="Configure KEYGL5 5.5.00 wake settings and proximity event references")
    p.add_argument("--spec-dir", type=Path, default=os.environ.get("CBUS_UNITSPEC_DIR"))
    _edlt_activation_options(p)
    p = unops.add_parser("edlt-page-control", help="Configure KEYGL5 5.5.00 Enable application page-control group")
    p.add_argument("--spec-dir", type=Path, default=os.environ.get("CBUS_UNITSPEC_DIR"))
    _edlt_page_control_options(p)
    p = unops.add_parser("edlt-lifecycle", help="Apply the KEYGL5 5.5.00 model load/before-save cycle using explicit cache facts")
    p.add_argument("--spec-dir", type=Path, default=os.environ.get("CBUS_UNITSPEC_DIR"))
    p.add_argument("--metadata", type=Path, required=True, help="Caller-supplied lifecycle cache JSON")
    p = unops.add_parser("edlt-restore-levels", help="Edit KEYGL5 5.5.00 preset controls with explicit cached names")
    p.add_argument("--spec-dir", type=Path, default=os.environ.get("CBUS_UNITSPEC_DIR"))
    _edlt_restore_levels_options(p)
    p = unops.add_parser("edlt-blank", help="Select Blank for one visible eDLT widget and retain other loaded models")
    p.add_argument("--spec-dir", type=Path, default=os.environ.get("CBUS_UNITSPEC_DIR"))
    _edlt_blank_options(p)
    p = unops.add_parser("edlt-reset-controls", help="Apply the bounded original eDLT Reset Unit control sequence")
    p.add_argument("--spec-dir", type=Path, default=os.environ.get("CBUS_UNITSPEC_DIR"))
    from .edlt_reset_cli import options as reset_options
    reset_options(p)
    p = unops.add_parser("edlt-scene-capture", help="Read live scene levels, stage them, and save to a database unit unless --dry-run")
    p.add_argument("--spec-dir", type=Path, default=os.environ.get("CBUS_UNITSPEC_DIR"))
    scene_live_options(p)
    p = unops.add_parser("edlt-scene-manager", help="Apply an ordered retained eDLT Scene Manager sequence")
    p.add_argument("--spec-dir", type=Path, default=os.environ.get("CBUS_UNITSPEC_DIR"))
    _edlt_scene_manager_options(p)
    for action, kind in (("edlt-applications", "applications"), ("edlt-corridor", "corridor")):
        p = unops.add_parser(action, help="Apply ordered KEYGL5 5.5.00 " + kind + " controls with explicit cache facts")
        p.add_argument("--spec-dir", type=Path, default=os.environ.get("CBUS_UNITSPEC_DIR"))
        _edlt_ordered_options(p, kind)
    p = unops.add_parser("edlt-navigation", help="Configure KEYGL5 5.5.00 navigation formats, temperature references and page labels")
    p.add_argument("--spec-dir", type=Path, default=os.environ.get("CBUS_UNITSPEC_DIR"))
    _edlt_navigation_options(p)
    p = unops.add_parser("edlt-mra", help="Configure KEYGL5 5.5.00 MRA Zone/Source widgets in the database")
    p.add_argument("--spec-dir", type=Path, default=os.environ.get("CBUS_UNITSPEC_DIR"))
    _edlt_mra_options(p)
    p = unops.add_parser("edlt-mra-globals", help="Set the shared multiplexer and zone across existing MRA widgets")
    p.add_argument("--spec-dir", type=Path, default=os.environ.get("CBUS_UNITSPEC_DIR"))
    _edlt_mra_globals_options(p)
    p = unops.add_parser("edlt-scene", help="Configure KEYGL5 5.5.00 Scene widgets referencing stored scenes")
    p.add_argument("--spec-dir", type=Path, default=os.environ.get("CBUS_UNITSPEC_DIR"))
    _edlt_scene_options(p)
    p = unops.add_parser("edlt-scenes", help="Replace a KEYGL5 5.5.00 scene table while retaining referenced scene identities")
    p.add_argument("--spec-dir", type=Path, default=os.environ.get("CBUS_UNITSPEC_DIR"))
    p.add_argument("--scenes", type=Path, required=True, help="Ordered JSON array of up to eight complete scene definitions")
    p = unops.add_parser("device-scene", help="Edit stored KEYE1 2.5.00 / 5031NMML scenes and scene-key binding")
    p.add_argument("--spec-dir", type=Path, default=os.environ.get("CBUS_UNITSPEC_DIR"))
    _device_scene_options(p)
    for action in ("template-export", "template-import"):
        p = unops.add_parser(action, help="Toolkit UnitTemplate XML for classic KEY1/KEY2/KEY4 1.2.67")
        p.add_argument("file", type=Path)
        p.add_argument("--spec-dir", type=Path, default=os.environ.get("CBUS_UNITSPEC_DIR"))
        p.add_argument("--profile", choices=("KEY1", "KEY2", "KEY4"), default="KEY4")
        if action == "template-export":
            p.add_argument("--description", default="")

    convert = cgops.add_parser("conversion", help="Native database conversion; moves replace the destination and remove the source")
    convops = convert.add_subparsers(dest="remote_action", required=True)
    p = convops.add_parser("align", help="Copy evidenced classic settings while retaining destination identity")
    p.add_argument("source")
    p.add_argument("destination")
    p.add_argument("--spec-dir", type=Path, default=os.environ.get("CBUS_UNITSPEC_DIR"))
    p.add_argument("--source-spec", required=True)
    p.add_argument("--target-spec", required=True)
    p.add_argument("--dry-run", action="store_true")
    backup = p.add_mutually_exclusive_group()
    backup.add_argument("--backup-project")
    backup.add_argument("--no-backup", action="store_true")
    p = convops.add_parser("replace", help="Replace a classic database unit at its original address with a verified backup")
    p.add_argument("source")
    p.add_argument("--spec-dir", type=Path, default=os.environ.get("CBUS_UNITSPEC_DIR"))
    p.add_argument("--source-spec", required=True)
    p.add_argument("--target-spec", required=True)
    p.add_argument("--firmware", required=True)
    p.add_argument("--catalog-number", required=True)
    p.add_argument("--target-serial", default="", help="Serial of the replacement hardware; blank means unassigned")
    p.add_argument("--learned-policy", choices=("frontend", "preserve_source", "target_default"), required=True)
    p.add_argument("--learned-current", choices=("true", "false"))
    p.add_argument("--learned-original", choices=("true", "false"))
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--backup-project", help="Defaults to a new B-prefixed backup")
    for action in ("check-catalog", "catalog", "check-move", "move"):
        p = convops.add_parser(action)
        p.add_argument("source", help="Fully qualified database path, e.g. //TEST/254/p/20")
        if action.endswith("catalog"):
            p.add_argument("unit_type")
            p.add_argument("catalog_number")
        else:
            p.add_argument("destination", help="Existing replacement unit; move deletes the source")
        if not action.startswith("check-"):
            backup = p.add_mutually_exclusive_group()
            backup.add_argument("--backup-project", help="Backup name; defaults to a new B-prefixed project")
            backup.add_argument("--no-backup", action="store_true")

    cgl = cgops.add_parser("cgl", help="Import/export CGL 1.1 using native network routing rules")
    cglo = cgl.add_subparsers(dest="remote_action", required=True)
    for action in ("export", "import"):
        p = cglo.add_parser(action)
        p.add_argument("project")
        p.add_argument("file", type=Path)
        if action == "export":
            p.add_argument("--network", type=_byte, action="append")
            p.add_argument("--application", type=_byte, action="append")
        else:
            backup = p.add_mutually_exclusive_group()
            backup.add_argument("--backup-project", help="Backup name; defaults to a new B-prefixed project")
            backup.add_argument("--no-backup", action="store_true")

    scene = cgops.add_parser("scene", help="Execute local scene files or invoke native named scenes")
    sceneops = scene.add_subparsers(dest="remote_action", required=True)
    for action in ("play", "record"):
        p = sceneops.add_parser(action)
        p.add_argument("scene_set")
        p.add_argument("scene")
    for action in ("execute", "record-file"):
        p = sceneops.add_parser(action)
        p.add_argument("file", type=Path)
        p.add_argument("--encoding", default="utf-8")
        if action == "record-file":
            p.add_argument("output", type=Path, help="New file for sampled cached levels; existing files are preserved")

    addressing = cgops.add_parser("address", help="Database addressing, verified physical moves and serial commissioning")
    aops = addressing.add_subparsers(dest="remote_action", required=True)
    p = aops.add_parser("inventory")
    p.add_argument("network")
    for action in ("readdress", "network-readdress"):
        p = aops.add_parser(action)
        p.add_argument("source")
        p.add_argument("new_address", type=_byte)
        p.add_argument("--dry-run", action="store_true")
        p.add_argument("--backup-project", help="Backup name; defaults to a new B-prefixed project")
    for action, help_text in (
            ("physical-readdress", "Move one verified physical KEYE1 to an empty address with native retries disabled"),
            ("serial-commission", "Commission one KEYE1 at address 255 to its matching database serial destination")):
        p = aops.add_parser(action, help=help_text)
        p.add_argument("source")
        p.add_argument("new_address", type=_byte)
        p.add_argument("--serial", required=True, help="Expected native decimal-dot unit serial")
        p.add_argument("--dry-run", action="store_true", help="Refresh and check identities without issuing an address write")
        p.add_argument("--plan-output", type=Path, help="Create a recovery plan file before an address write; existing files are preserved")
    for action in ("physical-verify", "serial-verify"):
        p = aops.add_parser(action, help="Observe a saved move plan without replaying its address write")
        p.add_argument("file", type=Path, help="Saved plan, move result or uncertain-error JSON containing the full plan")

    serials = cgops.add_parser("serials", help="Read cached physical identities or explicitly refresh an open network")
    serialops = serials.add_subparsers(dest="remote_action", required=True)
    for action in ("cached", "refresh"):
        p = serialops.add_parser(action)
        p.add_argument("network")
        p.add_argument("--unit", dest="units", type=_byte, action="append",
                       help="Select a unit; repeat for several. Refresh still scans the whole network.")
    p = serialops.add_parser("populate", help="Populate supported database serial metadata with a verified backup")
    p.add_argument("network")
    p.add_argument("--unit", dest="units", type=_byte, action="append", help="Select database targets; the identity inventory always covers the whole network")
    p.add_argument("--refresh", action="store_true", help="Explicitly refresh physical identities before planning; otherwise use the existing cache")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--backup-project", help="Backup name; defaults to a new B-prefixed project")

    serial_address = commands.add_parser("serial-address", help="Inspect selected-serial bytes or plan, apply and verify a guarded address move")
    serial_ops = serial_address.add_subparsers(dest="action", required=True)
    p = serial_ops.add_parser("encode", help="Return command bytes as JSON without transmitting them")
    p.add_argument("serial", help="Known decimal-dot unit serial")
    p.add_argument("destination", type=_byte, help="Destination unit address in 2..254")
    p.add_argument("--checksum", action="store_true", help="Include the separate SRCHK command checksum")
    p.add_argument("--confirmation", choices=tuple("ghijklmnopqrstuvwxyz"), default="g")
    p = serial_ops.add_parser("receipt", help="Classify an entire captured exchange; a match does not verify address movement")
    p.add_argument("file", type=Path, help="Raw captured PCI bytes, at most 4096 bytes")
    p.add_argument("--serial", required=True)
    p.add_argument("--destination", type=_byte, required=True)
    p.add_argument("--local-unit", type=_byte, required=True)
    p.add_argument("--confirmation", choices=tuple("ghijklmnopqrstuvwxyz"), default="g")

    p = serial_ops.add_parser("plan", help="Observe two distinct serials at address255 and save a plan for one explicit empty destination")
    p.add_argument("serial", help="Known decimal-dot serial to move")
    p.add_argument("destination", type=_byte, help="Explicit nonlocal empty address in2..254")
    p.add_argument("--source", type=_byte, default=255, help="Only duplicate source address255 is supported")
    p.add_argument("--host", required=True, help="Numeric IP address of the caller-owned PCI/CNI")
    p.add_argument("--port", type=int, default=10001)
    p.add_argument("--local-unit", type=_byte, required=True)
    p.add_argument("--expected-local-serial", required=True)
    p.add_argument("--output", type=Path, required=True, help="Create a new validated plan file; existing files are preserved")
    for name, default, description in (
        ("timeout", 600, "Transaction budget after admission; includes all network and journal phases"),
        ("observation-timeout", 10, "Overall budget per observation"),
        ("confirmation-timeout", 2, "Confirmation timeout for serial and MMI reads"),
        ("mmi-response-timeout", 5.5, "MMI response timeout"),
        ("quiet-period", 2, "Serial quiet interval; shorter values differ from the original two-second window"),
        ("options-response-timeout", 2, "Whole local option-byte response window"),
        ("address-response-timeout", 2, "Whole address-command response window")):
        p.add_argument("--" + name, type=_positive, default=default, help=description)
    for name, default in (("max-mmi-frames", 7), ("max-serial-frames", 7), ("max-unrelated", 64), ("max-bytes", 65536)):
        p.add_argument("--" + name, type=_number, default=default)
    p.add_argument("--checksum", action="store_true", help="Use the configured SRCHK command checksum mode")
    p = serial_ops.add_parser("apply", help="Repeat live guards and send exactly one command with a durable recovery journal")
    p.add_argument("plan", type=Path, help="Validated plan; endpoint and timing settings come from this file")
    p.add_argument("--recovery", type=Path, required=True, help="New recovery journal; caller must exclusively own commissioning access")
    p = serial_ops.add_parser("verify", help="Collect a fresh full inventory without replaying an address command")
    selection = p.add_mutually_exclusive_group(required=True)
    selection.add_argument("--plan", type=Path, help="Read the expected change from a saved plan")
    selection.add_argument("--recovery", type=Path, help="Read the plan from a recovery journal")

    pci = commands.add_parser("pci", help="Direct CNI/PCI operations with source and parameter correlation")
    pci.add_argument("--host", default="127.0.0.1")
    pci.add_argument("--port", type=int, default=10001)
    pci.add_argument("--timeout", type=_positive, help="Overall timeout: 600 seconds for inventory, 10 for MMI, 5 for other PCI operations")
    pci.add_argument("--local-unit", type=_byte, help="Known attached interface unit address, for source-less replies")
    pci.add_argument("--checksum", action="store_true", help="Append checksums; must match the configured interface mode")
    piops = pci.add_subparsers(dest="action", required=True)
    from .pci_routed_recall_cli import options as routed_recall_options
    routed_recall_options(piops)
    from .pci_routed_identify_cli import options as routed_identify_options
    routed_identify_options(piops)
    p = piops.add_parser("inventory", help="Read complete MMI coverage and per-address serials, then check MMI membership again")
    p.add_argument("--observation-timeout", type=_positive, default=10)
    p.add_argument("--confirmation-timeout", type=_positive, default=2)
    p.add_argument("--response-timeout", type=_positive, default=5.5)
    p.add_argument("--quiet-period", type=_positive, default=2,
                   help="Serial quiet interval; shorter values differ from the native two-second window")
    p.add_argument("--max-mmi-frames", type=_number, default=7)
    p.add_argument("--max-serial-frames", type=_number, default=7)
    p.add_argument("--max-unrelated", type=_number, default=64)
    p.add_argument("--max-bytes", type=_number, default=65536, help="Incoming byte limit per observation")
    p = piops.add_parser("mmi", help="Observe every address range with one read-only MMI request on a fresh connection")
    p.add_argument("--confirmation-timeout", type=_positive, default=2.0)
    p.add_argument("--response-timeout", type=_positive, default=5.5)
    p.add_argument("--max-frames", type=_number, default=7)
    p = piops.add_parser("serials", help="Collect serial replies for one address on a freshly owned PCI connection")
    p.add_argument("address", type=_byte)
    p.add_argument("--quiet-period", type=_positive, default=2.0,
                   help="Quiet interval after serial replies; shorter intervals differ from the native two-second window")
    p.add_argument("--confirmation-timeout", type=_positive, default=2.0)
    p.add_argument("--max-frames", type=_number, default=7, help="Reaching this response bound produces an incomplete observation")
    for action in ("identify", "recall", "write"):
        p = piops.add_parser(action)
        p.add_argument("unit", type=_unit, help="Unit address, or local for the attached PCI")
        p.add_argument("parameter", type=_byte)
        if action == "recall":
            p.add_argument("count", type=_byte)
            p.add_argument("--addressing", choices=("direct", "programming"), default="direct")
        if action == "write":
            p.add_argument("hex_data", help="Raw parameter bytes, no inferred memory or label semantics")
            p.add_argument("--addressing", choices=("direct", "programming"), default="programming")

    simulator = commands.add_parser("simulator", help="Persistent PCI fixture server with strict supported-command handling")
    simops = simulator.add_subparsers(dest="action", required=True)
    serve = simops.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=10001, help="TCP port; 0 selects a free port")
    serve.add_argument("--state", type=Path, help="Persist explicitly modeled raw parameter blocks as JSON")
    serve.add_argument("--profile", choices=("raw", "captured", "synthetic"), default="raw",
                       help="Raw parameter fixtures or captured native commissioning exchanges")
    serve.add_argument("--wire-log", type=Path)
    serve.add_argument("--local-unit", type=_byte, default=16)
    serve.add_argument("--checksum", action="store_true")
    serve.add_argument("--require-initialization", action="store_true")
    serve.add_argument("--fragment-size", type=int, action="append", default=[])
    serve.add_argument("--response-delay", type=float, default=0,
                       help="Simulated reply latency in seconds, 0..60; use 0.01 for the native clock fixture")

    inventory = commands.add_parser("inventory", help="Inspect the exact vendor's commands, unit catalog and help")
    inventory.add_argument("--cgate-dir", type=Path, default=os.environ.get("CBUS_CGATE_DIR"))
    inventory.add_argument("--help-dir", type=Path, default=os.environ.get("CBUS_TOOLKIT_HELP_DIR"))
    invops = inventory.add_subparsers(dest="action", required=True)
    for action in ("manifest", "commands", "units", "topics"):
        p = invops.add_parser(action)
        p.add_argument("--filter", default="")

    schema = commands.add_parser("unit-schema", help="Inspect and validate vendor unit parameters; does not program hardware")
    schema.add_argument("--spec-dir", type=Path, default=os.environ.get("CBUS_UNITSPEC_DIR"))
    shops = schema.add_subparsers(dest="action", required=True)
    shops.add_parser("list")
    for action in ("show", "defaults", "validate-defaults", "validate"):
        p = shops.add_parser(action)
        p.add_argument("spec", help="Unit spec filename, e.g. RELDN12.xml")
        if action == "validate":
            p.add_argument("parameter")
            p.add_argument("value", help="C-Gate-style parameter value")

    coverage = commands.add_parser("coverage", help="Show implementation and verification gaps")
    coverage.add_argument("--require-complete", action="store_true", help="Fail until all Toolkit functionality has independent acceptance evidence")

    memory = commands.add_parser("memory", help="Encode/decode logical unit memory and masked patches; no hardware I/O")
    memory.add_argument("--spec-dir", type=Path, default=os.environ.get("CBUS_UNITSPEC_DIR"))
    memory.add_argument("--string-encoding", default="ascii", help="Explicit native JVM write encoding for non-ASCII string fields")
    memops = memory.add_subparsers(dest="action", required=True)
    for action in ("layout", "encode", "decode", "remap", "apply"):
        p = memops.add_parser(action)
        if action != "apply":
            p.add_argument("spec")
        if action in ("layout", "encode", "decode"):
            p.add_argument("parameter")
        if action == "encode":
            p.add_argument("value")
            p.add_argument("--index", type=_number, default=0)
            p.add_argument("--partial", action="store_true")
        if action in ("decode", "remap", "apply"):
            p.add_argument("image", type=Path, help="JSON image in cbus-sparse-memory-v1 format")
        if action == "apply":
            p.add_argument("patch", type=Path, help="JSON patch in cbus-memory-patch-v1 format")
        if action in ("apply", "remap"):
            p.add_argument("output", type=Path, help="Create a new sparse-memory JSON image")
        if action == "remap":
            p.add_argument("--direction", choices=("physical_to_logical", "logical_to_physical"), required=True)

    calculator = commands.add_parser("calculator", help="Offline native-compatible network current and impedance calculation")
    calculator.add_argument("--catalog", type=Path, default=os.environ.get("CBUS_UNIT_CATALOG"))
    calculator.add_argument("file", type=Path, help="JSON array of catalogue/type/burden/switchable-supply records")

    keys = commands.add_parser("keys", help="Inspect and plan classic key presets without hardware I/O")
    keys.add_argument("--spec-dir", type=Path, default=os.environ.get("CBUS_UNITSPEC_DIR"))
    keyops = keys.add_subparsers(dest="action", required=True)
    keyops.add_parser("presets")
    p = keyops.add_parser("plan")
    p.add_argument("spec")
    p.add_argument("file", type=Path, help="PP export snapshot or JSON parameter mapping")
    _key_options(p)
    p = keyops.add_parser("neo-plan")
    p.add_argument("spec")
    p.add_argument("file", type=Path, help="PP export snapshot or JSON parameter mapping")
    _key_options(p, extended=True)
    sensors = commands.add_parser("sensors", help="Plan the tested ST7 occupancy settings without C-Gate")
    sensors.add_argument("--spec-dir", type=Path, default=os.environ.get("CBUS_UNITSPEC_DIR"))
    sops = sensors.add_subparsers(dest="action", required=True)
    p = sops.add_parser("plan")
    p.add_argument("file", type=Path, help="SENPILL 2.3.00 / 5753PEIRL PP export or parameter mapping")
    _sensor_options(p)
    edlt = commands.add_parser("edlt", help="Plan tested eDLT widgets with configuration CRCs offline")
    edlt.add_argument("--spec-dir", type=Path, default=os.environ.get("CBUS_UNITSPEC_DIR"))
    eops = edlt.add_subparsers(dest="action", required=True)
    p = eops.add_parser("lighting-plan")
    p.add_argument("file", type=Path, help="KEYGL5 5.5.00 / 5055EDL PP export or complete parameter mapping")
    _edlt_options(p)
    p = eops.add_parser("enable-plan")
    p.add_argument("file", type=Path, help="KEYGL5 5.5.00 / 5055EDL PP export or complete parameter mapping")
    _edlt_enable_options(p)
    p = eops.add_parser("shutter-plan")
    p.add_argument("file", type=Path, help="KEYGL5 5.5.00 / 5055EDL PP export or complete parameter mapping")
    _edlt_shutter_options(p)
    p = eops.add_parser("timer-plan")
    p.add_argument("file", type=Path, help="KEYGL5 5.5.00 / 5055EDL PP export or complete parameter mapping")
    _edlt_timer_options(p)
    p = eops.add_parser("fan-plan")
    p.add_argument("file", type=Path, help="KEYGL5 5.5.00 / 5055EDL PP export or complete parameter mapping")
    _edlt_fan_options(p)
    p = eops.add_parser("multilevel-plan")
    p.add_argument("file", type=Path, help="KEYGL5 5.5.00 / 5055EDL PP export or complete parameter mapping")
    _edlt_multilevel_options(p)
    p = eops.add_parser("room-courtesy-plan")
    p.add_argument("file", type=Path, help="KEYGL5 5.5.00 / 5055EDL PP export or complete parameter mapping")
    _edlt_room_courtesy_options(p)
    p = eops.add_parser("measurement-plan")
    p.add_argument("file", type=Path, help="KEYGL5 5.5.00 / 5055EDL PP export or complete parameter mapping")
    _edlt_measurement_options(p)
    p = eops.add_parser("time-date-plan")
    p.add_argument("file", type=Path, help="KEYGL5 5.5.00 / 5055EDL PP export or complete parameter mapping")
    _edlt_time_date_options(p)
    p = eops.add_parser("hvac-plan")
    p.add_argument("file", type=Path, help="KEYGL5 5.5.00 / 5055EDL PP export or complete parameter mapping")
    _edlt_hvac_options(p)
    p = eops.add_parser("display-plan")
    p.add_argument("file", type=Path, help="KEYGL5 5.5.00 / 5055EDL PP export or complete parameter mapping")
    _edlt_display_options(p)
    p = eops.add_parser("general-plan")
    p.add_argument("file", type=Path, help="KEYGL5 5.5.00 / 5055EDL PP export or complete parameter mapping")
    _edlt_general_options(p)
    p = eops.add_parser("standby-plan")
    p.add_argument("file", type=Path, help="KEYGL5 5.5.00 / 5055EDL PP export or complete parameter mapping")
    _edlt_standby_options(p)
    p = eops.add_parser("colours-plan")
    p.add_argument("file", type=Path, help="KEYGL5 5.5.00 / 5055EDL PP export or complete parameter mapping")
    _edlt_colours_options(p)
    p = eops.add_parser("quick-status-plan")
    p.add_argument("file", type=Path, help="KEYGL5 5.5.00 / 5055EDL PP export or complete parameter mapping")
    _edlt_quick_status_options(p)
    p = eops.add_parser("activation-plan")
    p.add_argument("file", type=Path, help="KEYGL5 5.5.00 / 5055EDL PP export or complete parameter mapping")
    _edlt_activation_options(p)
    p = eops.add_parser("page-control-plan")
    p.add_argument("file", type=Path, help="KEYGL5 5.5.00 / 5055EDL PP export or complete parameter mapping")
    _edlt_page_control_options(p)
    p = eops.add_parser("restore-levels-plan")
    p.add_argument("file", type=Path, help="KEYGL5 5.5.00 / 5055EDL PP export or complete parameter mapping")
    _edlt_restore_levels_options(p)
    p = eops.add_parser("blank-plan", help="Plan a visible eDLT widget Blank selection")
    p.add_argument("file", type=Path, help="Complete KEYGL5 5.5.00 / 5055EDL PP snapshot")
    _edlt_blank_options(p)
    p = eops.add_parser("reset-plan", help="Plan eDLT Reset Unit controls from a complete raw PP export")
    p.add_argument("file", type=Path)
    reset_options(p)
    for action in ("scene-manager-plan", "scene-manager-state"):
        p = eops.add_parser(action, help="Inspect or prepare an ordered retained Scene Manager sequence")
        p.add_argument("file", type=Path, help="Complete KEYGL5 5.5.00 / 5055EDL PP snapshot")
        _edlt_scene_manager_options(p, state_only=action == "scene-manager-state")
    for action, kind in (("applications-plan", "applications"), ("corridor-plan", "corridor")):
        p = eops.add_parser(action)
        p.add_argument("file", type=Path, help="KEYGL5 5.5.00 / 5055EDL PP export or complete parameter mapping")
        _edlt_ordered_options(p, kind)
    p = eops.add_parser("global-plan", help="Prepare an ordered eDLT Global Programming category payload")
    global_options(p)
    for action in ("lifecycle-requirements", "lifecycle-plan"):
        p = eops.add_parser(action)
        p.add_argument("file", type=Path, help="KEYGL5 5.5.00 / 5055EDL PP export or complete parameter mapping")
        if action == "lifecycle-plan":
            p.add_argument("--metadata", type=Path, required=True, help="Caller-supplied lifecycle cache JSON")
    p = eops.add_parser("navigation-plan")
    p.add_argument("file", type=Path, help="KEYGL5 5.5.00 / 5055EDL PP export or complete parameter mapping")
    _edlt_navigation_options(p)
    p = eops.add_parser("mra-plan")
    p.add_argument("file", type=Path, help="KEYGL5 5.5.00 / 5055EDL PP export or complete parameter mapping")
    _edlt_mra_options(p)
    p = eops.add_parser("mra-globals-plan")
    p.add_argument("file", type=Path, help="KEYGL5 5.5.00 / 5055EDL PP export or complete parameter mapping")
    _edlt_mra_globals_options(p)
    p = eops.add_parser("scene-plan")
    p.add_argument("file", type=Path, help="KEYGL5 5.5.00 / 5055EDL PP export or complete parameter mapping")
    _edlt_scene_options(p)
    for action in ("scenes-inspect", "scenes-plan"):
        p = eops.add_parser(action)
        p.add_argument("file", type=Path, help="KEYGL5 5.5.00 / 5055EDL PP export or complete parameter mapping")
        if action == "scenes-plan":
            p.add_argument("--scenes", type=Path, required=True, help="Ordered JSON array of complete scene definitions")
    templates = commands.add_parser("unit-templates", help="Inspect Toolkit UnitTemplate XML or export a supported PP snapshot")
    templates.add_argument("--spec-dir", type=Path, default=os.environ.get("CBUS_UNITSPEC_DIR"))
    tops = templates.add_subparsers(dest="action", required=True)
    p = tops.add_parser("inspect")
    p.add_argument("file", type=Path)
    p = tops.add_parser("export")
    p.add_argument("file", type=Path, help="Classic 1.2.67 PP export or parameter mapping")
    p.add_argument("output", type=Path)
    p.add_argument("--description", default="")
    p.add_argument("--profile", choices=("KEY1", "KEY2", "KEY4"), default="KEY4")
    firmware = commands.add_parser("firmware", help="eDLT diagnostics, offline firmware inspection and explicitly selected USB DFU operations")
    fwops = firmware.add_subparsers(dest="action", required=True)
    p = fwops.add_parser("usb-list", help="List cached metadata for eDLT USB candidates without reading strings or claiming interfaces")
    p.add_argument("--max-devices", type=_number, default=64, help="Maximum enumeration size before reporting an incomplete result")
    p = fwops.add_parser("usb-inspect", help="Read only standard USB descriptors/configuration for an explicitly selected eDLT")
    p.add_argument("--bus", type=_number, required=True)
    p.add_argument("--address", type=_number, required=True)
    p.add_argument("--expected-serial", help="Require this exact USB serial string")
    p.add_argument("--timeout", type=_positive, default=5, help="Timeout per control transfer in seconds; enumeration/open/close have no timeout")
    for action in ("inspect", "program", "erase"):
        p = fwops.add_parser("usb-dfu-" + action, help={
            "inspect": "Claim an explicitly selected eDLT already in DFU mode and read its memory geometry",
            "program": "Program raw bytes into an explicit flash range and verify the complete readback",
            "erase": "Erase an explicit flash range and verify every byte"}[action])
        p.add_argument("--bus", type=_number, required=True)
        p.add_argument("--address", type=_number, required=True, help="USB device address")
        p.add_argument("--expected-serial", required=True, help="Exact USB serial string from descriptor inspection")
        p.add_argument("--device-descriptor", type=Path, required=True, help="Expected eighteen-byte device descriptor")
        p.add_argument("--configuration-descriptor", type=Path, required=True, help="Expected complete configuration descriptor")
        p.add_argument("--release-policy", choices=("reset-first-alternate",), required=True,
                       help="Explicitly allow USB release to reset the interface to its first alternate")
        p.add_argument("--flash-size", type=_number, required=True)
        p.add_argument("--application-start", type=_number, required=True)
        p.add_argument("--external", action="store_true", help="External flash; only offset zero is currently supported")
        p.add_argument("--timeout", type=_positive, default=30, help="DFU operation deadline; USB acquisition and release are separate")
        p.add_argument("--inspection-timeout", type=_positive, default=5, help="Per-transfer timeout during USB acquisition")
        p.add_argument("--poll-limit", type=_number, default=256)
        if action == "program":
            p.add_argument("file", type=Path, help="Raw binary payload; no container extraction or automatic erase")
        if action != "inspect":
            p.add_argument("--offset", type=_number, required=True, help="Flash byte address")
        if action == "erase":
            p.add_argument("--length", type=_number, required=True, help="Erase byte count aligned to the flash erase block")
    for action in ("identify", "ncc-versions"):
        p = fwops.add_parser(action)
        p.add_argument("--port", required=True, help="Explicit eDLT diagnostic serial port")
        p.add_argument("--timeout", type=_positive, default=10, help="Read timeout in seconds, at most 60")
        if action == "identify":
            p.add_argument("--package", type=Path, help="Compare package directory metadata with the identified variant")
    for action in ("parse-id", "parse-ncc", "inspect-package"):
        p = fwops.add_parser(action)
        p.add_argument("file", type=Path)
        if action == "parse-id":
            p.add_argument("--package", type=Path)
    p = fwops.add_parser("classify-hardware")
    p.add_argument("version")
    for action in ("dfu-status", "dfu-command"):
        p = fwops.add_parser(action, help="Decode a captured DFU record without hardware access")
        p.add_argument("hex", help="Hexadecimal byte pairs, optionally separated by spaces")
    p = fwops.add_parser("dfu-inspect", help="Inspect a supplied DFU container; opaque firmware compatibility remains unverified")
    p.add_argument("file", type=Path)
    p.add_argument("--vendor-id", type=_number)
    p.add_argument("--product-id", type=_number)
    p = fwops.add_parser("dfu-descriptors", help="Validate supplied eDLT DFU-mode USB descriptors offline")
    p.add_argument("device_file", type=Path, help="Captured eighteen-byte USB device descriptor")
    p.add_argument("configuration_file", type=Path, help="Captured complete USB configuration descriptor")
    p = fwops.add_parser("dfu-plan", help="Plan binary transfer records offline using explicit memory bounds")
    for name in ("length", "address", "flash-size", "application-start"):
        p.add_argument("--" + name, type=_number, required=True)
    p.add_argument("--external", action="store_true", help="External flash; only address zero is currently supported")
    p.add_argument("--transfer-size", type=_number, default=1024)
    stored_scenes = commands.add_parser("unit-scenes", help="Inspect or plan the tested KEYE1 stored scene table offline")
    stored_scenes.add_argument("--spec-dir", type=Path, default=os.environ.get("CBUS_UNITSPEC_DIR"))
    ssops = stored_scenes.add_subparsers(dest="action", required=True)
    for action in ("inspect", "plan"):
        p = ssops.add_parser(action)
        p.add_argument("file", type=Path, help="KEYE1 2.5.00 / 5031NMML PP export or parameter mapping")
        if action == "plan":
            _device_scene_options(p)
    conversion = commands.add_parser("unit-conversion", help="Plan classic programming alignment without C-Gate or hardware I/O")
    conversion.add_argument("--spec-dir", type=Path, default=os.environ.get("CBUS_UNITSPEC_DIR"))
    cop = conversion.add_subparsers(dest="action", required=True)
    p = cop.add_parser("plan")
    p.add_argument("source_spec")
    p.add_argument("target_spec")
    p.add_argument("source_file", type=Path)
    p.add_argument("target_file", type=Path)

    scene = commands.add_parser("scene", help="Edit native C-Gate scene files")
    scene.add_argument("--encoding", default="utf-8")
    sceneops = scene.add_subparsers(dest="action", required=True)
    for action in ("new", "show", "add", "set", "delete", "triggers", "export"):
        p = sceneops.add_parser(action)
        p.add_argument("file", type=Path)
        if action in ("new", "triggers"):
            play = p.add_mutually_exclusive_group()
            record = p.add_mutually_exclusive_group()
            play.add_argument("--play-trigger")
            record.add_argument("--record-trigger")
            if action == "triggers":
                play.add_argument("--clear-play-trigger", action="store_true")
                record.add_argument("--clear-record-trigger", action="store_true")
        if action in ("set", "delete"):
            p.add_argument("index", type=_number, help="Action index, starting at zero")
        if action in ("add", "set"):
            p.add_argument("address")
            p.add_argument("level", type=_byte)
            p.add_argument("--seconds", type=_number, default=0)
        if action == "export":
            p.add_argument("output", type=Path)
        elif action not in ("new", "show"):
            p.add_argument("--output", type=Path, help="Create an edited copy instead of changing the input")
    matching = commands.add_parser("unit-addressing", help="Compare database and scanned unit serial inventories without making changes")
    mops = matching.add_subparsers(dest="action", required=True)
    p = mops.add_parser("match")
    p.add_argument("database_file", type=Path)
    p.add_argument("network_file", type=Path)
    p.add_argument("--native-serials", action="store_true",
                   help="Compare native decimal-dot serial components; enabled automatically for native serial inventories")
    return parser


def _project(args):
    if args.action == "repair":
        from .project_repair_cli import run as project_repair_run
        return project_repair_run(args)
    from .project import ProjectDocument
    if args.action == "new":
        if args.file.exists():
            raise ValueError(f"Output already exists: {args.file}")
        p = ProjectDocument.new(args.name, description=args.description)
        fmt = args.format or ("cbz" if args.file.suffix.lower() == ".cbz" else "xml")
        return {"file": p.save(args.file, format=fmt), "project": p.metadata}, 0
    p = ProjectDocument.load(args.file)
    if args.action == "inspect":
        return p.inspect(), 0
    if args.action == "validate":
        issues = p.validate()
        return {"valid": not issues, "issues": issues}, int(bool(issues))
    if args.action == "list":
        return p.list_entities(args.path, kind=args.kind, recursive=args.recursive), 0
    if args.action == "get":
        return p.get(args.path), 0
    if args.action == "export":
        return {"file": p.save(args.output, format=args.format)}, 0
    if args.action == "field-get":
        return {"value": p.get_field(args.path, args.field)}, 0
    if args.action == "parameters":
        return p.parameters(args.path), 0
    if args.action == "add":
        result = p.add(args.kind, args.parent, address=args.address, name=args.name, fields=_fields(args.field))
    elif args.action == "set":
        fields = _fields(args.field)
        if not fields:
            raise ValueError("Supply at least one --field FIELD=VALUE")
        result = p.update(args.path, fields)
    elif args.action == "delete":
        result = p.delete(args.path, cascade=args.cascade)
    elif args.action in ("copy", "move"):
        result = getattr(p, args.action)(args.path, args.parent, address=args.address, name=args.name)
    elif args.action == "field-set":
        result = p.set_field(args.path, args.field, args.value)
    elif args.action == "field-delete":
        result = p.remove_field(args.path, args.field)
    elif args.action == "parameter-set":
        result = p.set_parameter(args.path, args.name, args.value)
    elif args.action == "parameter-delete":
        result = p.delete_parameter(args.path, args.name)
    else:
        raise ValueError(f"Unknown operation: {args.action}")
    return {"file": p.save(args.output or args.file), "result": result}, 0


def _cgate(args):
    import ssl
    from .cgate import CGateClient
    context = None
    if args.tls:
        if args.key and not args.cert:
            raise ValueError("--key requires --cert")
        context = ssl.create_default_context(cafile=str(args.ca) if args.ca else None)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        if args.cert:
            context.load_cert_chain(str(args.cert), str(args.key) if args.key else None)
    elif args.ca or args.cert or args.key:
        raise ValueError("Certificate options require --tls")
    if args.action == "repositories":
        from .repositories_cli import run as repository_run
        return repository_run(args, CGateClient, context)
    if args.action in ("thermostat-schedule-levels", "thermostat-schedule-compose"):
        from .thermostat_schedule_cli import native as schedule_native
        return schedule_native(args, CGateClient, context)
    if args.action == "database-csv":
        from .toolkit_database_csv_cli import live as database_csv_live
        return database_csv_live(args, CGateClient, context)
    if args.action == "edlt-scene-broadcast":
        from .edlt_scene_live_cli import broadcast
        return broadcast(args, CGateClient, context)
    if args.action == "edlt-global":
        from .edlt_global_cli import native
        return native(args, CGateClient, context)
    if args.action == "edlt-label-clear":
        return _edlt_label_clear(args, CGateClient, context)
    if args.action == "edlt-factory-default":
        return _edlt_factory_default(args, CGateClient, context)
    if args.action == "exec":
        commands = [args.command]
    elif args.action == "run":
        commands = [line for line in args.file.read_text(encoding="utf-8").splitlines()
                    if line.strip() and not line.lstrip().startswith(("#", "//"))]
        if not commands:
            raise ValueError("Command file is empty")
    elif args.action not in ("project", "database", "unit", "cgl", "network", "label", "conversion", "events", "trigger", "enable", "scene", "address", "serials", "edlt-labels"):
        tokens = ["TERMINATERAMP" if args.action == "stop" else args.action.upper(), args.address]
        if args.action == "get":
            tokens.append(args.attribute)
        if args.action == "ramp":
            if args.seconds < 0:
                raise ValueError("Ramp duration must be nonnegative")
            tokens.extend([str(args.level), str(args.seconds)])
        if any(any(c.isspace() for c in token) for token in tokens):
            raise ValueError("Addresses and attributes must be single C-Gate tokens")
        commands = [" ".join(tokens)]
    else:
        commands = []
    from .edlt_control_cli import connection_guard
    with connection_guard(args), CGateClient(args.host, args.port or (20123 if args.tls else 20023),
                     timeout=args.timeout, ssl_context=context) as client:
        if args.action == "edlt-labels":
            from .cmqtt import edlt_label_inventory, edlt_labels
            if args.network is not None:
                result = edlt_label_inventory(client, args.network)
                return result, int(not result["complete"])
            return edlt_labels(client, args.address), 0
        if args.action == "label":
            if args.remote_action == "cache-clear":
                from .labels import NativeLabelCache
                return NativeLabelCache(client).clear(
                    args.application, args.unit, key=args.key_number
                ), 0
            from .labels import NativeLabels
            labels = NativeLabels(client, args.family)
            options = {"language": args.language, "action_selector": args.action_selector}
            if args.remote_action != "language":
                options["variant"] = args.variant
            action = args.remote_action.replace("-", "_")
            if action in ("raw", "unicode_raw", "dynamic"):
                if len(args.data) % 2 or any(character not in "0123456789abcdefABCDEF" for character in args.data):
                    raise ValueError("Label data must be contiguous hexadecimal byte pairs")
                data = bytes.fromhex(args.data)
            if action == "clear":
                response = getattr(labels, "unicode" if args.unicode_label else "text")(args.application, args.group, "", **options)
            elif action in ("text", "unicode"):
                response = getattr(labels, action)(args.application, args.group, args.text, **options)
            elif action == "raw":
                response = labels.raw(args.application, args.group, args.options, data, **options)
            elif action == "unicode_raw":
                response = labels.unicode_raw(args.application, args.group, data, **options)
            elif action == "icon":
                response = labels.icon(args.application, args.group, args.icon, **options)
            elif action == "dynamic":
                response = labels.dynamic(args.application, args.group, args.icon, args.width, args.height, data,
                                          vertical_offset=args.vertical_offset, **options)
            else:
                response = labels.set_language(args.application, args.group, **options)
            if response.status != 200:
                raise RuntimeError("C-Gate did not accept the label command: " + response.final)
            return {"queued": True, "device_verified": False, "response": response}, 0
        if args.action == "project":
            from .native import NativeProjects
            manager = NativeProjects(client)
            if args.remote_action in ("list", "directory"):
                return getattr(manager, args.remote_action)(), 0
            return manager.operation(args.remote_action, args.name, getattr(args, "other", None)), 0
        if args.action == "database":
            from .native import NativeDatabase
            db = NativeDatabase(client)
            if args.remote_action == "network-new":
                result = db.create_network(args.project, args.address, args.name, args.interface_type, args.interface_address)
            elif args.remote_action == "unit-new":
                result = db.create_unit(args.network, args.address, args.name, args.unit_type, args.firmware,
                                        catalog_number=args.catalog_number)
            elif args.remote_action in ("get", "get-xml"):
                result = db.get(args.path, xml=args.remote_action == "get-xml")
            elif args.remote_action == "set":
                result = db.set(args.path, args.value)
            elif args.remote_action == "add":
                result = db.add(args.path, args.kind, args.address, args.name)
            elif args.remote_action == "copy":
                result = db.copy(args.path, args.parent, args.address, args.name)
            elif args.remote_action == "rename-network":
                result = db.rename_network(args.path, args.address)
            else:
                result = getattr(db, args.remote_action)(args.path)
            return result, 0
        if args.action == "unit":
            return _programming(args, client), 0
        if args.action == "address":
            if args.remote_action in ("physical-readdress", "serial-commission"):
                from .physical_addressing import PhysicalAddressing
                from .serial_commissioning import SerialCommissioning
                if args.plan_output and args.plan_output.exists():
                    raise ValueError("Recovery plan output already exists")
                manager = (SerialCommissioning if args.remote_action == "serial-commission" else PhysicalAddressing)(client)
                plan = manager.plan(args.source, args.new_address, expected_serial=args.serial)
                if args.plan_output:
                    with args.plan_output.open("x", encoding="utf-8") as output:
                        json.dump(plan.as_dict(), output, indent=2, ensure_ascii=False)
                        output.write("\n")
                return plan.as_dict() if args.dry_run else manager.apply(plan), 0
            if args.remote_action in ("physical-verify", "serial-verify"):
                from .physical_addressing import PhysicalAddressing, PhysicalAddressPlan
                from .serial_commissioning import SerialCommissioning, SerialCommissionPlan
                with args.file.open("rb") as handle:
                    data = handle.read(32 * 1024 * 1024 + 1)
                if len(data) > 32 * 1024 * 1024:
                    raise ValueError("Recovery plan exceeds 32 MiB")
                value = json.loads(data)
                if isinstance(value, dict) and "plan" in value:
                    value = value["plan"]
                if args.remote_action == "serial-verify":
                    result = SerialCommissioning(client).verify(SerialCommissionPlan.from_dict(value))
                else:
                    result = PhysicalAddressing(client).verify(PhysicalAddressPlan.from_dict(value))
                return result, int(result["outcome"] == "uncertain")
            from .addressing import DatabaseAddressing, NetworkAddressing
            manager = NetworkAddressing(client) if args.remote_action == "network-readdress" else DatabaseAddressing(client)
            if args.remote_action == "inventory":
                return {"format": "cbus-unit-inventory-v1", "source": "database", "network": args.network,
                        "units": manager.inventory(args.network)}, 0
            plan = manager.plan(args.source, args.new_address)
            return plan.as_dict() if args.dry_run else manager.apply(plan, backup_project=args.backup_project), 0
        if args.action == "serials":
            from .serials import NativeSerials
            scanner = NativeSerials(client)
            if args.remote_action == "populate":
                from .serial_population import DatabaseSerials
                inventory = (scanner.refresh if args.refresh else scanner.cached)(args.network)
                if not inventory.complete:
                    return {"error": "Serial population requires a complete identity inventory", "updated": False,
                            "inventory": inventory.as_dict()}, 1
                manager = DatabaseSerials(client)
                plan = manager.plan(inventory, units=args.units)
                return plan.as_dict() if args.dry_run else manager.apply(plan, backup_project=args.backup_project), 0
            inventory = getattr(scanner, args.remote_action)(args.network, args.units)
            return inventory.as_dict(), int(not inventory.complete)
        if args.action == "enable":
            from .enable import NativeEnable
            enable = NativeEnable(client)
            if args.remote_action == "set":
                response = enable.set(args.address, args.value, force=args.force)
            elif args.remote_action == "remove":
                response = enable.remove(args.address)
            else:
                if args.remote_action == "get":
                    return enable.get(args.address, args.attribute), 0
                return getattr(enable, args.remote_action)(args.address), 0
            if response.code != 200:
                raise RuntimeError("Enable command did not complete: " + response.final)
            if args.remote_action == "remove":
                return {"accepted": True, "effect_verified": False, "response": response}, 0
            return {"queued": True, "device_verified": False, "response": response}, 0
        if args.action == "trigger":
            from .applications import NativeTrigger
            trigger = NativeTrigger(client)
            if args.remote_action == "event":
                response = trigger.event(args.address, args.selector, force=args.force)
            elif args.remote_action == "kill":
                response = trigger.indicator_kill(args.address)
            else:
                if args.remote_action == "get":
                    return trigger.get(args.address, args.attribute), 0
                return getattr(trigger, args.remote_action)(args.address), 0
            if response.code != 200:
                raise RuntimeError("Trigger command did not complete: " + response.final)
            return {"queued": True, "device_verified": False, "response": response}, 0
        if args.action == "events":
            from .events import NativeEvents
            if args.count < 1:
                raise ValueError("Event count must be positive")
            monitor = NativeEvents(client)
            monitor.subscribe(args.mode)
            if args.state:
                response = monitor.request_state(args.state)
                if not response.successful:
                    raise RuntimeError("State request did not complete: " + response.final)
            received = 0
            while args.follow or received < args.count:
                event = monitor.read()
                print(json.dumps({"type": "event", **dataclasses.asdict(event)}, ensure_ascii=True), flush=True)
                received += 1
                if event.category == "overflow":
                    return {"type": "event-summary", "received": received, "events_lost": True}, 1
            return {"type": "event-summary", "received": received, "events_lost": client.events_lost}, int(client.events_lost)
        if args.action == "conversion":
            from .conversion import NativeConversions
            converter = NativeConversions(client)
            if args.remote_action == "replace":
                from .classic_replacement import ClassicReplacement, LearnedHistory
                from .unitspec import UnitSpecStore
                if args.spec_dir is None:
                    raise ValueError("Use --spec-dir or CBUS_UNITSPEC_DIR for decoded vendor specifications")
                history = None
                if args.learned_current is not None or args.learned_original is not None:
                    if args.learned_current is None or args.learned_original is None:
                        raise ValueError("Both learned history values are required")
                    history = LearnedHistory(args.learned_current == "true", args.learned_original == "true")
                store = UnitSpecStore(args.spec_dir)
                replacement = ClassicReplacement(client, store.load(args.source_spec), store.load(args.target_spec))
                plan = replacement.plan(args.source, target_firmware=args.firmware, target_catalog=args.catalog_number,
                                        target_serial=args.target_serial, learned_policy=args.learned_policy, learned_history=history)
                return plan.as_dict() if args.dry_run else replacement.apply(plan, backup_project=args.backup_project), 0
            if args.remote_action == "align":
                import uuid
                from .unitspec import UnitSpecStore
                if args.spec_dir is None:
                    raise ValueError("Use --spec-dir or CBUS_UNITSPEC_DIR for decoded vendor specifications")
                store = UnitSpecStore(args.spec_dir)
                backup = None if args.no_backup else args.backup_project or "B" + uuid.uuid4().hex[:7].upper()
                return converter.align(args.source, args.destination, store.load(args.source_spec), store.load(args.target_spec),
                                       backup_project=backup, dry_run=args.dry_run), 0
            if args.remote_action == "check-catalog":
                result = converter.check_catalog(args.source, args.unit_type, args.catalog_number)
            elif args.remote_action == "check-move":
                result = converter.check_move(args.source, args.destination)
            else:
                import uuid
                backup = None if args.no_backup else args.backup_project or "B" + uuid.uuid4().hex[:7].upper()
                if args.remote_action == "catalog":
                    result = converter.convert_catalog(args.source, args.unit_type, args.catalog_number, backup_project=backup)
                else:
                    result = converter.move(args.source, args.destination, backup_project=backup)
            return result, int(result.get("allowed") is False)
        if args.action == "network":
            result = _network(args, client)
            if hasattr(result, "successful") and not result.successful:
                raise RuntimeError("Network command did not complete: " + result.final)
            return result, int((args.remote_action == "calculate" and not result["passed"])
                               or (args.remote_action == "clocks" and not result["complete"]))
        if args.action == "scene":
            from .scenes import NativeScenes, SceneExecutor, SceneFile
            if args.remote_action in ("execute", "record-file"):
                scene = SceneFile.load(args.file, encoding=args.encoding)
                executor = SceneExecutor(client)
                if args.remote_action == "execute":
                    return executor.play(scene), 0
                if args.output.exists():
                    raise ValueError(f"Output already exists: {args.output}")
                recorded = executor.record(scene)
                recorded.save(args.output, encoding=args.encoding)
                return {"file": str(args.output), "cached": True, "device_verified": False,
                        **recorded.as_dict()}, 0
            response = getattr(NativeScenes(client), args.remote_action)(args.scene_set, args.scene)
            if response.code != 200:
                raise RuntimeError("Scene command did not complete: " + response.final)
            return {"queued": True, "device_verified": False, "response": response}, 0
        if args.action == "cgl":
            from .cgl import NativeCGL, summary
            manager = NativeCGL(client)
            if args.remote_action == "export":
                if args.file.exists():
                    raise ValueError(f"Output already exists: {args.file}")
                document = manager.export(args.project, networks=args.network, applications=args.application)
                with args.file.open("x", encoding="utf-8") as target:
                    json.dump(document, target, ensure_ascii=False, indent=2)
                    target.write("\n")
                return {"file": str(args.file), **summary(document)}, 0
            import uuid
            backup = None if args.no_backup else args.backup_project or "B" + uuid.uuid4().hex[:7].upper()
            result = manager.import_document(args.project, args.file.read_text(encoding="utf-8"), backup_project=backup)
            return result, int(not result["complete"])
        results = []
        for command in commands:
            try:
                reply = client.command(command)
                if not reply.successful:
                    raise RuntimeError("C-Gate command did not complete: " + reply.final)
            except (RuntimeError, OSError) as error:
                if args.action == "run":
                    raise BatchCommandError(error, results) from error
                raise
            results.append(reply)
    return results if args.action == "run" else results[0], 0


def _pci(args):
    timeout = args.timeout if args.timeout is not None else {"mmi": 10.0, "inventory": 600.0}.get(args.action, 5.0)
    if args.action == "inventory":
        from .pci_full_inventory import PCIInventoryCollector
        if args.local_unit is None:
            raise ValueError("PCI inventory requires --local-unit with the known attached interface address")
        observation = PCIInventoryCollector(args.host, args.port, local_unit=args.local_unit,
            overall_timeout=timeout, command_checksum=args.checksum,
            **{name: getattr(args, name) for name in (
                "observation_timeout", "confirmation_timeout", "response_timeout", "quiet_period",
                "max_mmi_frames", "max_serial_frames", "max_unrelated", "max_bytes")}).collect_inventory()
        return observation.as_dict(), int(observation.status != "complete")
    if args.action == "mmi":
        from .pci_inventory import PCIMMICollector
        if args.local_unit is None:
            raise ValueError("PCI MMI collection requires --local-unit with the known attached interface address")
        observation = PCIMMICollector(args.host, args.port, local_unit=args.local_unit,
            overall_timeout=timeout, confirmation_timeout=args.confirmation_timeout,
            response_timeout=args.response_timeout, max_frames=args.max_frames,
            command_checksum=args.checksum).collect_mmi()
        return observation.as_dict(), int(observation.status != "complete")
    if args.action == "serials":
        from .pci_serials import PCISerialCollector
        if args.local_unit is None:
            raise ValueError("PCI serial collection requires --local-unit with the known attached interface address")
        observation = PCISerialCollector(args.host, args.port, local_unit=args.local_unit,
            quiet_period=args.quiet_period, overall_timeout=timeout,
            confirmation_timeout=args.confirmation_timeout, max_frames=args.max_frames,
            command_checksum=args.checksum).collect_serials(args.address)
        return observation.as_dict(), int(observation.status != "single")
    from .pci import PCIClient
    with PCIClient(args.host, args.port, timeout=timeout, local_unit=args.local_unit,
                   command_checksum=args.checksum) as client:
        if args.action == "identify":
            result = client.identify(args.unit, args.parameter)
        elif args.action == "recall":
            if args.count == 0:
                raise ValueError("Recall count must be positive")
            result = client.recall(args.unit, args.parameter, args.count, addressing=args.addressing)
        else:
            result = client.write(args.unit, args.parameter, bytes.fromhex(args.hex_data), addressing=args.addressing)
    return {"unit": args.unit, "parameter": args.parameter, "result": result}, 0


def _serial_address(args):
    if args.action in ("plan", "apply", "verify"):
        return _selected_serial_cli(args)
    from .pci_serial_address import encode_serial_address, decode_serial_address_receipt
    confirmation = args.confirmation.encode("ascii")
    if args.action == "encode":
        from .serials import parse_native_serial
        wire = encode_serial_address(args.serial, args.destination,
            command_checksum=args.checksum, confirmation=confirmation)
        return {"format": "cbus-pci-serial-address-command-v1",
                "serial": parse_native_serial(args.serial).canonical, "destination": args.destination,
                "command_checksum": args.checksum, "confirmation": args.confirmation,
                "wire_text": wire.decode("ascii"), "wire_hex": wire.hex(),
                "io_performed": False, "movement_verified": False, "persistence_verified": False}, 0
    with args.file.open("rb") as handle:
        data = handle.read(4097)
    receipt = decode_serial_address_receipt(data, serial=args.serial,
        destination=args.destination, local_unit=args.local_unit, confirmation=confirmation)
    return receipt.as_dict(), int(not receipt.matched)


def _selected_serial_cli(args):
    from .pci_selected_serial import SelectedSerialCoordinator, SelectedSerialPlan

    def new_path(path):
        if path.exists() or path.is_symlink():
            raise ValueError(f"Output already exists: {path}")
        if not path.parent.is_dir():
            raise ValueError(f"Output directory does not exist: {path.parent}")

    if args.action == "plan":
        new_path(args.output)
        names = ("observation_timeout", "confirmation_timeout", "mmi_response_timeout", "quiet_period",
                 "options_response_timeout", "address_response_timeout", "max_mmi_frames", "max_serial_frames",
                 "max_unrelated", "max_bytes")
        coordinator = SelectedSerialCoordinator(args.host, args.port, local_unit=args.local_unit,
            expected_local_serial=args.expected_local_serial, overall_timeout=args.timeout,
            command_checksum=args.checksum, **{name: getattr(args, name) for name in names})
        plan = coordinator.plan(args.serial, args.destination, source=args.source)
        document = plan.as_dict()
        with args.output.open("x", encoding="utf-8") as output:
            json.dump(document, output, ensure_ascii=False, allow_nan=False, indent=2)
            output.write("\n"); output.flush(); os.fsync(output.fileno())
        return {"format": "cbus-selected-serial-plan-export-v1", "plan_file": str(args.output),
                "plan": document, "address_command_sent": False, "database_updated": False}, 0
    if args.action == "apply":
        new_path(args.recovery)
    plan = (SelectedSerialPlan.load(args.plan) if args.plan is not None
            else SelectedSerialCoordinator.load_recovery(args.recovery))
    document = plan.as_dict()
    coordinator = SelectedSerialCoordinator(**document["endpoint"], local_unit=document["local_unit"],
        expected_local_serial=document["expected_local_serial"], **document["settings"])
    result = (coordinator.apply(plan, recovery_path=args.recovery) if args.action == "apply"
              else coordinator.verify(plan))
    return result.as_dict(), int(not result.observed_expected_change)


def _selected_serial_error_payload(error):
    evidence = getattr(error, "selected_serial_evidence", None)
    if not isinstance(evidence, dict):
        return {}
    try:
        # Large or interrupted evidence copies retain their original in-memory
        # object. Console export must not replace that first failure either.
        encoded = json.dumps(evidence, default=_json_default, ensure_ascii=False, allow_nan=False)
        if len(encoded.encode("utf-8")) > 16 * 1024 * 1024:
            raise ValueError("Recovery evidence exceeds the console export bound")
        return {"selected_serial_evidence": json.loads(encoded)}
    except BaseException as export_error:
        summary = {"evidence_export_complete": False,
                   "evidence_export_error": {"type": type(export_error).__name__, "message": str(export_error)[:1024]}}
        for name in ("operation", "state", "outcome", "attempt_recorded", "attempt_durability_verified", "send_attempted"):
            value = evidence.get(name)
            if (value is None or type(value) is bool or
                    (type(value) is int and -(2 ** 63) <= value < 2 ** 63) or
                    (type(value) is str and len(value) <= 4096)):
                summary[name] = value
        journal = evidence.get("journal")
        if isinstance(journal, dict) and isinstance(journal.get("path"), str) and len(journal["path"]) <= 4096:
            summary["journal"] = {"path": journal["path"]}
        return {"selected_serial_evidence": summary}


def _edlt_label_clear(args, client_factory, ssl_context):
    from .edlt_label_clear import EdltDynamicLabelClear, _path
    from .serials import parse_native_serial
    _path(args.source)
    if not parse_native_serial(args.serial).known:
        raise ValueError("Clear requires a known expected native serial")
    if args.plan_output is not None:
        if args.plan_output.exists() or args.plan_output.is_symlink():
            raise ValueError("Clear plan output already exists")
        if not args.plan_output.parent.is_dir():
            raise ValueError("Clear plan output parent must be an existing directory")
    manager = None
    try:
        with client_factory(args.host, args.port or (20123 if args.tls else 20023),
                            timeout=args.timeout, ssl_context=ssl_context) as client:
            manager = EdltDynamicLabelClear(client)
            plan = manager.plan(args.source, expected_serial=args.serial)
            if args.plan_output is not None:
                with args.plan_output.open("x", encoding="utf-8") as output:
                    json.dump(plan.as_dict(), output, indent=2, ensure_ascii=False)
                    output.write("\n"); output.flush(); os.fsync(output.fileno())
            if args.remote_action == "plan":
                return plan.as_dict(), 0
            result = manager.request(plan)
            return result, int(result["outcome"] != "native_accepted")
    except BaseException as error:
        if manager is not None and isinstance(manager.last_evidence, dict):
            error.edlt_label_clear_evidence = manager.last_evidence
        raise


def _edlt_label_clear_payload(error):
    evidence = getattr(error, "edlt_label_clear_evidence", None)
    return {"edlt_label_clear_evidence": evidence} if isinstance(evidence, dict) else {}


def _edlt_factory_default(args, client_factory, ssl_context):
    from .edlt_factory_default import EdltFactoryDefault
    from .edlt_label_clear import _path
    from .serials import parse_native_serial
    try:
        _path(args.source)
    except ValueError as error:
        message = str(error).replace("Clear", "Factory default").replace(
            "clear", "factory default"
        )
        raise ValueError(message) from error
    if not parse_native_serial(args.serial).known:
        raise ValueError("Factory default requires a known expected native serial")
    if args.plan_output is not None:
        if args.plan_output.exists() or args.plan_output.is_symlink():
            raise ValueError("Factory-default plan output already exists")
        if not args.plan_output.parent.is_dir():
            raise ValueError("Factory-default plan output parent must be an existing directory")
    manager = None
    try:
        with client_factory(
            args.host,
            args.port or (20123 if args.tls else 20023),
            timeout=args.timeout,
            ssl_context=ssl_context,
        ) as client:
            manager = EdltFactoryDefault(client)
            plan = manager.plan(args.source, expected_serial=args.serial)
            if args.plan_output is not None:
                with args.plan_output.open("x", encoding="utf-8") as output:
                    json.dump(plan.as_dict(), output, indent=2, ensure_ascii=False)
                    output.write("\n")
                    output.flush()
                    os.fsync(output.fileno())
            if args.remote_action == "plan":
                return plan.as_dict(), 0
            result = manager.request(plan)
            return result, int(result["outcome"] != "native_accepted")
    except BaseException as error:
        if manager is not None and isinstance(manager.last_evidence, dict):
            error.edlt_factory_default_evidence = manager.last_evidence
        raise


def _edlt_factory_default_payload(error):
    evidence = getattr(error, "edlt_factory_default_evidence", None)
    return (
        {"edlt_factory_default_evidence": evidence}
        if isinstance(evidence, dict)
        else {}
    )


def _programming_cleanup_payload(error):
    errors = getattr(error, "programming_cleanup_errors", None)
    if not isinstance(errors, (list, tuple)) or not errors:
        return {}
    return {"programming_cleanup_errors": [{"type": type(item).__name__, "error": str(item)[:1024]}
                                            for item in errors[:16]],
            "programming_cleanup_errors_truncated": len(errors) > 16}


def _cgate_cleanup_payload(error):
    errors = getattr(error, "cgate_cleanup_errors", None)
    if not isinstance(errors, (list, tuple)) or not errors:
        return {}
    return {"cgate_cleanup_errors": [{"type": type(item).__name__, "error": str(item)[:1024]}
                                      for item in errors[:16]],
            "cgate_cleanup_errors_truncated": len(errors) > 16}


def _network(args, client):
    from .networks import NativeNetworks
    network = NativeNetworks(client)
    action = args.remote_action
    if action == "list":
        return network.list(args.project)
    if action == "state":
        return {"state": network.state(args.address)}
    if action == "sync":
        return network.synchronize(args.address, fast=args.fast, retries=args.retries)
    if action == "sync-new":
        return network.sync_new(args.address, args.unit)
    if action == "check-units":
        return network.check_units(args.address, args.unit)
    if action == "unravel":
        return network.unravel(args.address, units=args.unit, match_database=args.match_database)
    if action == "clocks":
        from .clocks import NativeClocks
        clocks = NativeClocks(client)
        if args.recover:
            return clocks.recover(args.address).as_dict()
        if args.target is not None:
            return clocks.configure(args.address, args.target).as_dict()
        return clocks.inspect(args.address).as_dict()
    if action == "tree":
        return network.tree(args.address, xml=args.xml, details=args.details, sync=args.sync)
    if action == "rename":
        return network.rename(args.address, args.new_address, fix_references=not args.no_fix_references)
    if action == "set-project":
        return network.set_project_identity(args.address, args.project)
    if action == "wait-ready":
        return network.wait_ready(args.address, timeout=args.wait_seconds)
    return getattr(network, action)(args.address)


def _programming(args, client):
    from .programming import Programmer
    programmer = Programmer(client)
    mutable = args.remote_action in ("set", "reset-defaults", "import", "key-macro", "neo-key-macro", "sensor-occupancy", "edlt-lighting", "edlt-enable", "edlt-shutter", "edlt-timer", "edlt-fan", "edlt-multilevel", "edlt-room-courtesy", "edlt-measurement", "edlt-time-date", "edlt-hvac", "edlt-display", "edlt-mra", "edlt-mra-globals", "edlt-general", "edlt-standby", "edlt-colours", "edlt-navigation", "edlt-quick-status", "edlt-activation", "edlt-page-control", "edlt-lifecycle", "edlt-restore-levels", "edlt-applications", "edlt-corridor", "edlt-blank", "edlt-reset-controls", "edlt-scene-manager", "edlt-scene-capture", "edlt-scene", "edlt-scenes", "device-scene", "template-import")
    destination = args.destination or args.source
    if mutable and not args.dry_run and not destination:
        raise ValueError("Edits need --source or --destination, or --dry-run")
    if args.remote_action in ("edlt-lighting", "edlt-enable", "edlt-shutter", "edlt-timer", "edlt-fan", "edlt-multilevel", "edlt-room-courtesy", "edlt-measurement", "edlt-time-date", "edlt-hvac", "edlt-display", "edlt-mra", "edlt-mra-globals", "edlt-general", "edlt-standby", "edlt-colours", "edlt-navigation", "edlt-quick-status", "edlt-activation", "edlt-page-control", "edlt-lifecycle", "edlt-restore-levels", "edlt-applications", "edlt-corridor", "edlt-blank", "edlt-reset-controls", "edlt-scene-manager", "edlt-scene-capture", "edlt-scene", "edlt-scenes") and destination and not destination.lower().startswith("/db//"):
        raise ValueError("The eDLT widget workflows support database destinations only")
    if args.remote_action == "template-import" and destination and not destination.lower().startswith("/db//"):
        raise ValueError("The tested unit template workflow supports database destinations only")
    if args.unit_type:
        if not args.firmware:
            raise ValueError("--unit-type requires --firmware")
        context = programmer.new(args.lock_address, args.unit_type, args.firmware, catalog_number=args.catalog_number)
    else:
        context = programmer.load(args.lock_address, args.source)
    snapshot = None
    if args.remote_action == "import":
        snapshot = json.loads(args.file.read_text(encoding="utf-8"))
    if args.remote_action in ("export", "template-export") and args.file.exists():
        raise ValueError(f"Output already exists: {args.file}")
    template = _read_unit_template(args.file) if args.remote_action == "template-import" else None
    templates = _unit_templates(args) if args.remote_action in ("template-import", "template-export") else None
    keys = _classic_keys(args, extended=args.remote_action == "neo-key-macro") if args.remote_action in ("key-macro", "neo-key-macro") else None
    sensor = _sensor(args) if args.remote_action == "sensor-occupancy" else None
    edlt = _edlt(args) if args.remote_action == "edlt-lighting" else None
    edlt_enable = _edlt_enable(args) if args.remote_action == "edlt-enable" else None
    edlt_shutter = _edlt_shutter(args) if args.remote_action == "edlt-shutter" else None
    edlt_timer = _edlt_timer(args) if args.remote_action == "edlt-timer" else None
    edlt_fan = _edlt_fan(args) if args.remote_action == "edlt-fan" else None
    edlt_multilevel = _edlt_multilevel(args) if args.remote_action == "edlt-multilevel" else None
    edlt_room_courtesy = _edlt_room_courtesy(args) if args.remote_action == "edlt-room-courtesy" else None
    edlt_measurement = _edlt_measurement(args) if args.remote_action == "edlt-measurement" else None
    edlt_time_date = _edlt_time_date(args) if args.remote_action == "edlt-time-date" else None
    edlt_hvac = _edlt_hvac(args) if args.remote_action == "edlt-hvac" else None
    edlt_display = _edlt_display(args) if args.remote_action == "edlt-display" else None
    edlt_mra = _edlt_mra(args) if args.remote_action in ("edlt-mra", "edlt-mra-globals") else None
    edlt_general = _edlt_general(args) if args.remote_action == "edlt-general" else None
    edlt_standby = _edlt_standby(args) if args.remote_action == "edlt-standby" else None
    edlt_colours = _edlt_colours(args) if args.remote_action == "edlt-colours" else None
    edlt_quick_status = _edlt_quick_status(args) if args.remote_action == "edlt-quick-status" else None
    edlt_activation = _edlt_activation(args) if args.remote_action == "edlt-activation" else None
    edlt_page_control = _edlt_page_control(args) if args.remote_action == "edlt-page-control" else None
    edlt_lifecycle = _edlt_lifecycle(args) if args.remote_action == "edlt-lifecycle" else None
    lifecycle_metadata = _edlt_lifecycle_metadata(args.metadata) if edlt_lifecycle is not None else None
    edlt_restore_levels = _edlt_restore_levels(args) if args.remote_action == "edlt-restore-levels" else None
    restore_levels_settings = _edlt_restore_levels_settings(args) if edlt_restore_levels is not None else None
    edlt_applications = _edlt_applications(args) if args.remote_action == "edlt-applications" else None
    applications_settings = _edlt_ordered_settings(args, "applications") if edlt_applications is not None else None
    edlt_corridor = _edlt_corridor(args) if args.remote_action == "edlt-corridor" else None
    corridor_settings = _edlt_ordered_settings(args, "corridor") if edlt_corridor is not None else None
    edlt_blank = _edlt_blank(args) if args.remote_action == "edlt-blank" else None
    blank_settings = _edlt_blank_settings(args) if edlt_blank is not None else None
    edlt_reset = _edlt_reset(args) if args.remote_action == "edlt-reset-controls" else None
    reset_settings = _edlt_reset_settings(args) if edlt_reset is not None else None
    edlt_scene_capture = _edlt_scene_capture(args, client) if args.remote_action == "edlt-scene-capture" else None
    scene_capture_settings = _edlt_scene_capture_settings(args) if edlt_scene_capture is not None else None
    edlt_scene_manager = _edlt_scene_manager(args) if args.remote_action == "edlt-scene-manager" else None
    scene_manager_settings = _edlt_scene_manager_settings(args) if edlt_scene_manager is not None else None
    edlt_navigation = _edlt_navigation(args) if args.remote_action == "edlt-navigation" else None
    navigation_settings = _edlt_navigation_settings(args) if edlt_navigation is not None else None
    edlt_scene = _edlt_scene(args) if args.remote_action == "edlt-scene" else None
    edlt_scene_table = _edlt_scene_table(args) if args.remote_action == "edlt-scenes" else None
    scene_definitions = _edlt_scene_definitions(args.scenes) if args.remote_action == "edlt-scenes" else None
    device_scenes = _device_scenes(args) if args.remote_action == "device-scene" else None
    ordered = (("applications", edlt_applications, applications_settings),
               ("corridor", edlt_corridor, corridor_settings), ("blank", edlt_blank, blank_settings),
               ("reset", edlt_reset, reset_settings),
               ("scene_live", edlt_scene_capture, scene_capture_settings),
               ("scene_manager", edlt_scene_manager, scene_manager_settings))
    for kind, editor, settings in ordered:
        if editor is not None:
            from .edlt_control_cli import program
            return program(context, editor, settings, kind=kind, destination=destination,
                           explicit_destination=bool(args.destination), dry_run=args.dry_run,
                           state=getattr(args, "_ordered_control_state", None))
    result = {}
    with context as session:
        if args.remote_action == "show":
            return session.values()
        if args.remote_action == "get":
            return session.values(args.parameter)
        if args.remote_action == "info":
            return session.info(args.parameter)
        if args.remote_action == "export":
            snapshot = session.export_parameters()
            with args.file.open("x", encoding="utf-8") as target:
                json.dump(snapshot, target, indent=2, ensure_ascii=False)
                target.write("\n")
            return {"file": str(args.file)}
        if args.remote_action == "template-export":
            return _write_unit_template(args.file, templates.export(session, description=args.description))
        if args.remote_action == "set":
            session.set(args.parameter, args.value)
            values = session.values(args.parameter)
        elif args.remote_action == "reset-defaults":
            session.reset_defaults()
            values = session.values()
        elif args.remote_action in ("key-macro", "neo-key-macro"):
            result = keys.configure(session, **_key_settings(args))
            values = session.values()
        elif args.remote_action == "sensor-occupancy":
            result = sensor.configure(session, **_sensor_settings(args))
            values = session.values()
        elif args.remote_action == "edlt-lighting":
            result = edlt.configure(session, **_edlt_settings(args))
            values = session.values()
        elif args.remote_action == "edlt-enable":
            result = edlt_enable.configure(session, **_edlt_enable_settings(args))
            values = session.values()
        elif args.remote_action == "edlt-shutter":
            result = edlt_shutter.configure(session, **_edlt_shutter_settings(args))
            values = session.values()
        elif args.remote_action == "edlt-timer":
            result = edlt_timer.configure(session, **_edlt_timer_settings(args))
            values = session.values()
        elif args.remote_action == "edlt-fan":
            result = edlt_fan.configure(session, **_edlt_fan_settings(args))
            values = session.values()
        elif args.remote_action == "edlt-multilevel":
            result = edlt_multilevel.configure(session, **_edlt_multilevel_settings(args))
            values = session.values()
        elif args.remote_action == "edlt-room-courtesy":
            result = edlt_room_courtesy.configure(session, **_edlt_room_courtesy_settings(args))
            values = session.values()
        elif args.remote_action == "edlt-measurement":
            result = edlt_measurement.configure(session, **_edlt_measurement_settings(args))
            values = session.values()
        elif args.remote_action == "edlt-time-date":
            result = edlt_time_date.configure(session, **_edlt_time_date_settings(args))
            values = session.values()
        elif args.remote_action == "edlt-hvac":
            result = edlt_hvac.configure(session, **_edlt_hvac_settings(args))
            values = session.values()
        elif args.remote_action == "edlt-display":
            result = edlt_display.configure(session, **_edlt_display_settings(args))
            values = session.values()
        elif args.remote_action == "edlt-mra":
            result = edlt_mra.configure(session, **_edlt_mra_settings(args))
            values = session.values()
        elif args.remote_action == "edlt-mra-globals":
            result = edlt_mra.configure_globals(session, multiplexer=args.multiplexer, zone=args.zone)
            values = session.values()
        elif args.remote_action == "edlt-general":
            result = edlt_general.configure(session, **_edlt_general_settings(args))
            values = session.values()
        elif args.remote_action == "edlt-standby":
            result = edlt_standby.configure(session, **_edlt_standby_settings(args))
            values = session.values()
        elif args.remote_action == "edlt-colours":
            result = edlt_colours.configure(session, **_edlt_colours_settings(args))
            values = session.values()
        elif args.remote_action == "edlt-quick-status":
            result = edlt_quick_status.configure(session, **_edlt_quick_status_settings(args))
            values = session.values()
        elif args.remote_action == "edlt-activation":
            result = edlt_activation.configure(session, **_edlt_activation_settings(args))
            values = session.values()
        elif args.remote_action == "edlt-page-control":
            result = edlt_page_control.configure(session, group=args.group)
            values = session.values()
        elif args.remote_action == "edlt-lifecycle":
            result = edlt_lifecycle.configure(session, metadata=lifecycle_metadata)
            values = session.values()
        elif args.remote_action == "edlt-restore-levels":
            result = edlt_restore_levels.configure(session, **restore_levels_settings)
            values = session.values()
        elif args.remote_action == "edlt-navigation":
            result = edlt_navigation.configure(session, **navigation_settings)
            values = session.values()
        elif args.remote_action == "edlt-scene":
            result = edlt_scene.configure(session, **_edlt_scene_settings(args))
            values = session.values()
        elif args.remote_action == "edlt-scenes":
            result = edlt_scene_table.configure(session, scenes=scene_definitions)
            values = session.values()
        elif args.remote_action == "device-scene":
            result = device_scenes.configure(session, **_device_scene_settings(args))
            values = session.values()
        elif args.remote_action == "template-import":
            result = templates.apply(session, template)
            values = session.values()
        else:
            session.import_parameters(snapshot)
            values = session.values()
        saved = None
        if not args.dry_run:
            saved = session.save(destination) if args.destination else session.save_to_source()
        return {**result, "parameters": values,
                "saved": saved is not None, "destination": destination if saved else None}


def _memory(args):
    from .memory import BytePatch, MemoryCodec, MemoryImage, MemoryPatch
    from .unitspec import UnitSpecStore
    if args.action in ("apply", "remap") and args.output.exists():
        raise ValueError(f"Output already exists: {args.output}")
    image = None
    if hasattr(args, "image"):
        source = json.loads(args.image.read_text(encoding="utf-8"))
        if not isinstance(source, dict) or source.get("format") != "cbus-sparse-memory-v1" or not isinstance(source.get("bytes"), dict):
            raise ValueError("Expected a cbus-sparse-memory-v1 JSON image")
        image = MemoryImage(source["bytes"])
    if args.action == "apply":
        patch = json.loads(args.patch.read_text(encoding="utf-8"))
        if not isinstance(patch, dict) or patch.get("format") != "cbus-memory-patch-v1" or not isinstance(patch.get("edits"), list):
            raise ValueError("Expected a cbus-memory-patch-v1 JSON patch")
        edits = []
        for item in patch["edits"]:
            if not isinstance(item, dict) or set(item) != {"address", "value", "mask"}:
                raise ValueError("Patch edits require address, value and mask")
            edits.append(BytePatch(item["address"], item["value"], item["mask"]))
        result = MemoryPatch(tuple(edits)).apply(image).as_dict()
    else:
        if args.spec_dir is None:
            raise ValueError("Use --spec-dir or CBUS_UNITSPEC_DIR for decoded vendor specifications")
        codec = MemoryCodec(UnitSpecStore(args.spec_dir).load(args.spec), string_encoding=args.string_encoding)
        if args.action == "layout":
            return codec.layout(args.parameter).as_dict(), 0
        if args.action == "encode":
            return codec.encode(args.parameter, args.value, index=args.index, allow_partial=args.partial).as_dict(), 0
        if args.action == "decode":
            return {"parameter": args.parameter, "value": codec.decode(args.parameter, image)}, 0
        result = codec.remap(image, direction=args.direction).as_dict()
    with args.output.open("x", encoding="utf-8") as target:
        json.dump(result, target, indent=2)
        target.write("\n")
    return {"file": str(args.output), "byte_count": len(result["bytes"])}, 0


def run(args):
    if args.area == "thermostat-temperature":
        from .thermostat_temperature_cli import run as run_thermostat_temperature
        return run_thermostat_temperature(args)
    if args.area == "thermostat-scheduling":
        from .thermostat_scheduling_cli import run as run_thermostat_scheduling
        return run_thermostat_scheduling(args)
    if args.area == "pci" and args.action == "routed-recall":
        from .pci_routed_recall_cli import run as routed_recall_run
        return routed_recall_run(args)
    if args.area == "pci" and args.action == "routed-identify":
        from .pci_routed_identify_cli import run as routed_identify_run
        return routed_identify_run(args)
    if args.area == "preferences":
        from .toolkit_preferences_cli import run as preferences_run
        return preferences_run(args)
    if args.area in ("update-link", "update-catalogue"):
        from .toolkit_updates_cli import run as update_run
        return update_run(args)
    if args.area == "update-metadata-stages":
        from .toolkit_update_metadata_cli import run as metadata_run
        return metadata_run(args)
    if args.area == "update-revocation-stages":
        from .toolkit_update_revocation_cli import run as revocation_run
        return revocation_run(args)
    if args.area == "update-condition-stages":
        from .toolkit_update_conditions_cli import run as condition_run
        return condition_run(args)
    if args.area == "update-condition-live":
        from .toolkit_live_update_conditions_cli import run as live_condition_run
        return live_condition_run(args)
    if args.area == "pci-route":
        from .pci_routing_cli import run as routing_run
        return routing_run(args)
    if args.area == "toolkit-about":
        from .toolkit_about_cli import run as about_run
        return about_run(args)
    if args.area == "toolkit-database-csv":
        from .toolkit_database_csv_cli import run as database_csv_run
        return database_csv_run(args)
    if args.area == "unit-addressing":
        from .addressing import UnitIdentity, match_serials
        sources = {}
        def inventory(path, side):
            with path.open("rb") as handle:
                data = handle.read(1024 * 1024 + 1)
            if len(data) > 1024 * 1024:
                raise ValueError("Unit inventory exceeds 1 MiB")
            rows = json.loads(data)
            if isinstance(rows, dict):
                if rows.get("format") == "cbus-native-serial-inventory-v1":
                    if type(rows.get("complete")) is not bool or not isinstance(rows.get("records"), list):
                        raise ValueError("Native serial inventory requires complete and records fields")
                    if any(not isinstance(record, dict) for record in rows["records"]):
                        raise ValueError("Native serial inventory records must be objects")
                    sources[side] = {name: rows.get(name) for name in ("network", "mode", "complete", "observed_at", "errors")}
                    sources[side]["incomplete_records"] = [
                        {name: record.get(name) for name in ("address", "status", "errors")}
                        for record in rows["records"] if record.get("status") != "ok"]
                    rows = rows.get("identities")
                elif rows.get("format") == "cbus-unit-inventory-v1":
                    rows = rows.get("units")
                else:
                    raise ValueError("Unknown unit inventory format")
            if not isinstance(rows, list) or len(rows) > 256:
                raise ValueError("Unit inventory must contain at most 256 records")
            if any(not isinstance(row, dict) or not {"address", "unit_type"} <= set(row) <= {"address", "unit_type", "serial"} for row in rows):
                raise ValueError("Unit inventory records require address, unit_type and optional serial")
            return tuple(UnitIdentity(**row) for row in rows)
        database = inventory(args.database_file, "database")
        network = inventory(args.network_file, "network")
        report = match_serials(database, network, native_serials=args.native_serials or bool(sources))
        incomplete = any(not source["complete"] or source["incomplete_records"] or source["errors"] for source in sources.values())
        if sources:
            report.update(inventory_sources=sources, inventory_complete=not incomplete)
        return report, int(incomplete)
    if args.area == "project":
        return _project(args)
    if args.area == "scene":
        from .scenes import SceneAction, SceneFile
        if args.action == "new":
            scene = SceneFile(play_trigger=args.play_trigger, record_trigger=args.record_trigger)
            scene.save(args.file, encoding=args.encoding)
            return {"file": str(args.file), **scene.as_dict()}, 0
        scene = SceneFile.load(args.file, encoding=args.encoding)
        if args.action == "show":
            return scene.as_dict(), 0
        if args.action in ("add", "set"):
            scene = scene.with_action(len(scene.actions) if args.action == "add" else args.index,
                                      SceneAction(args.address, args.level, args.seconds))
        elif args.action == "delete":
            scene = scene.without_action(args.index)
        elif args.action == "triggers":
            if not any((args.play_trigger, args.record_trigger, args.clear_play_trigger, args.clear_record_trigger)):
                raise ValueError("Specify a trigger to set or clear")
            scene = dataclasses.replace(scene,
                play_trigger=None if args.clear_play_trigger else args.play_trigger if args.play_trigger is not None else scene.play_trigger,
                record_trigger=None if args.clear_record_trigger else args.record_trigger if args.record_trigger is not None else scene.record_trigger)
        destination = args.output or args.file
        scene.save(destination, overwrite=args.output is None, encoding=args.encoding)
        return {"file": str(destination), **scene.as_dict()}, 0
    if args.area == "cgate":
        return _cgate(args)
    if args.area == "pci":
        return _pci(args)
    if args.area == "serial-address":
        return _serial_address(args)
    if args.area == "memory":
        return _memory(args)
    if args.area == "unit-conversion":
        from .offline_conversion import OfflineConversion
        from .unitspec import UnitSpecStore
        if args.spec_dir is None:
            raise ValueError("Use --spec-dir or CBUS_UNITSPEC_DIR for decoded vendor specifications")
        store = UnitSpecStore(args.spec_dir)
        source_spec, target_spec = store.load(args.source_spec), store.load(args.target_spec)
        def parameters(path, spec):
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError("Expected a PP parameter mapping or export snapshot")
            if "format" in value:
                if value.get("format") != "cbus-cli-parameters-v1" or value.get("unit_type") != spec.unit_type:
                    raise ValueError("Snapshot format or unit type differs from the selected schema")
                value = value.get("parameters")
                if not isinstance(value, dict):
                    raise ValueError("Snapshot requires a parameter mapping")
            return value
        plan = OfflineConversion(source_spec, target_spec).plan(parameters(args.source_file, source_spec), parameters(args.target_file, target_spec))
        return plan.as_dict(), 0
    if args.area == "keys":
        from .macros import PRESETS
        if args.action == "presets":
            return [preset.as_dict() for preset in PRESETS.values()], 0
        keys = _classic_keys(args, extended=args.action == "neo-plan")
        values = json.loads(args.file.read_text(encoding="utf-8"))
        if not isinstance(values, dict):
            raise ValueError("Expected a PP parameter mapping or export snapshot")
        if "format" in values:
            if values.get("format") != "cbus-cli-parameters-v1" or values.get("unit_type") != keys.unit_type:
                raise ValueError("Snapshot format or unit type differs from the selected schema")
            values = values.get("parameters")
            if not isinstance(values, dict):
                raise ValueError("Snapshot requires a parameter mapping")
        return keys.plan(values, **_key_settings(args)).as_dict(), 0
    if args.area == "sensors":
        from .sensors import PROFILE
        values = _parameter_snapshot(args.file, PROFILE[:3])
        return _sensor(args).plan(values, **_sensor_settings(args)).as_dict(), 0
    if args.area == "edlt":
        if args.action == "reset-plan":
            from .edlt_reset_cli import offline
            return offline(args)
        if args.action in ("scene-manager-plan", "scene-manager-state"):
            from .edlt_scene_manager_cli import offline
            return offline(args, state_only=args.action == "scene-manager-state")
        if args.action == "blank-plan":
            from .edlt_global_cli import read_parameters
            return _edlt_blank(args).plan(read_parameters(args.file), **_edlt_blank_settings(args)).as_dict(), 0
        if args.action == "global-plan":
            from .edlt_global_cli import offline
            return offline(args)
        values = _parameter_snapshot(args.file, ("KEYGL5", "5.5.00", "5055EDL"))
        if args.action == "enable-plan":
            return _edlt_enable(args).plan(values, **_edlt_enable_settings(args)).as_dict(), 0
        if args.action == "shutter-plan":
            return _edlt_shutter(args).plan(values, **_edlt_shutter_settings(args)).as_dict(), 0
        if args.action == "timer-plan":
            return _edlt_timer(args).plan(values, **_edlt_timer_settings(args)).as_dict(), 0
        if args.action == "fan-plan":
            return _edlt_fan(args).plan(values, **_edlt_fan_settings(args)).as_dict(), 0
        if args.action == "multilevel-plan":
            return _edlt_multilevel(args).plan(values, **_edlt_multilevel_settings(args)).as_dict(), 0
        if args.action == "room-courtesy-plan":
            return _edlt_room_courtesy(args).plan(values, **_edlt_room_courtesy_settings(args)).as_dict(), 0
        if args.action == "measurement-plan":
            return _edlt_measurement(args).plan(values, **_edlt_measurement_settings(args)).as_dict(), 0
        if args.action == "time-date-plan":
            return _edlt_time_date(args).plan(values, **_edlt_time_date_settings(args)).as_dict(), 0
        if args.action == "hvac-plan":
            return _edlt_hvac(args).plan(values, **_edlt_hvac_settings(args)).as_dict(), 0
        if args.action == "display-plan":
            return _edlt_display(args).plan(values, **_edlt_display_settings(args)).as_dict(), 0
        if args.action == "mra-plan":
            return _edlt_mra(args).plan(values, **_edlt_mra_settings(args)).as_dict(), 0
        if args.action == "mra-globals-plan":
            return _edlt_mra(args).plan_globals(values, multiplexer=args.multiplexer, zone=args.zone).as_dict(), 0
        if args.action == "general-plan":
            return _edlt_general(args).plan(values, **_edlt_general_settings(args)).as_dict(), 0
        if args.action == "standby-plan":
            return _edlt_standby(args).plan(values, **_edlt_standby_settings(args)).as_dict(), 0
        if args.action == "colours-plan":
            return _edlt_colours(args).plan(values, **_edlt_colours_settings(args)).as_dict(), 0
        if args.action == "quick-status-plan":
            return _edlt_quick_status(args).plan(values, **_edlt_quick_status_settings(args)).as_dict(), 0
        if args.action == "activation-plan":
            return _edlt_activation(args).plan(values, **_edlt_activation_settings(args)).as_dict(), 0
        if args.action == "page-control-plan":
            return _edlt_page_control(args).plan(values, group=args.group).as_dict(), 0
        if args.action == "lifecycle-requirements":
            return _edlt_lifecycle(args).requirements(values).as_dict(), 0
        if args.action == "lifecycle-plan":
            return _edlt_lifecycle(args).plan(values, metadata=_edlt_lifecycle_metadata(args.metadata)).as_dict(), 0
        if args.action == "restore-levels-plan":
            return _edlt_restore_levels(args).plan(values, **_edlt_restore_levels_settings(args)).as_dict(), 0
        if args.action == "applications-plan":
            return _edlt_applications(args).plan(values, **_edlt_ordered_settings(args, "applications")).as_dict(), 0
        if args.action == "corridor-plan":
            return _edlt_corridor(args).plan(values, **_edlt_ordered_settings(args, "corridor")).as_dict(), 0
        if args.action == "navigation-plan":
            return _edlt_navigation(args).plan(values, **_edlt_navigation_settings(args)).as_dict(), 0
        if args.action == "scene-plan":
            return _edlt_scene(args).plan(values, **_edlt_scene_settings(args)).as_dict(), 0
        if args.action == "scenes-inspect":
            return [scene.as_dict() for scene in _edlt_scene_table(args).read(values)], 0
        if args.action == "scenes-plan":
            return _edlt_scene_table(args).plan(values, scenes=_edlt_scene_definitions(args.scenes)).as_dict(), 0
        return _edlt(args).plan(values, **_edlt_settings(args)).as_dict(), 0
    if args.area == "unit-templates":
        if args.action == "inspect":
            return _read_unit_template(args.file).as_dict(), 0
        if args.output.exists():
            raise ValueError(f"Output already exists: {args.output}")
        from .unit_templates import PROFILES
        values = _parameter_snapshot(args.file, PROFILES[args.profile][:3])
        template = _unit_templates(args).from_values(values, description=args.description)
        return _write_unit_template(args.output, template), 0
    if args.area == "firmware":
        return _firmware(args)
    if args.area == "unit-scenes":
        from .device_scenes import PROFILE
        values = _parameter_snapshot(args.file, PROFILE[:3])
        scenes = _device_scenes(args)
        if args.action == "inspect":
            return scenes.inspect(values), 0
        return scenes.plan(values, **_device_scene_settings(args)).as_dict(), 0
    if args.area == "calculator":
        from .calculator import CalculatorCatalog
        if args.catalog is None:
            raise ValueError("Use --catalog or CBUS_UNIT_CATALOG to locate cbusunits.xml")
        units = json.loads(args.file.read_text(encoding="utf-8"))
        if not isinstance(units, list):
            raise ValueError("Calculator input must be a JSON array of unit records")
        result = CalculatorCatalog.load(args.catalog).calculate(units)
        return {"passed": result.passed, **dataclasses.asdict(result)}, int(not result.passed)
    if args.area == "simulator":
        import threading
        from .simulator import PCISimulator
        if not 0 <= args.port <= 65535:
            raise ValueError("Simulator port must be in 0..65535")
        simulator = PCISimulator(state_path=args.state, wire_log_path=args.wire_log,
                                 local_unit=args.local_unit, command_checksum=args.checksum,
                                 smart=not args.require_initialization, fragment_sizes=args.fragment_size,
                                 profile=args.profile, response_delay=args.response_delay)
        with simulator.running(args.host, args.port) as (host, port):
            print(json.dumps({"listening": {"host": host, "port": port}, "state": str(args.state) if args.state else None,
                              "response_delay": simulator.response_delay,
                              "scope": "Configured PCI parameter blocks; incomplete C-Bus network emulation"}), flush=True)
            threading.Event().wait()
    if args.area == "inventory":
        from .inventory import VendorInventory
        if args.cgate_dir is None:
            raise ValueError("Use --cgate-dir or CBUS_CGATE_DIR to locate the vendor installation")
        v = VendorInventory(args.cgate_dir, args.help_dir)
        result = getattr(v, {"topics": "help_topics"}.get(args.action, args.action))()
        if args.filter:
            if not isinstance(result, list):
                raise ValueError("--filter applies to commands, units and topics")
            needle = args.filter.casefold()
            result = [x for x in result if needle in json.dumps(x, ensure_ascii=False).casefold()]
        return result, 0
    if args.area == "unit-schema":
        from .unitspec import UnitSpecStore
        if args.spec_dir is None:
            raise ValueError("Use --spec-dir or CBUS_UNITSPEC_DIR for decoded vendor specifications")
        store = UnitSpecStore(args.spec_dir)
        if args.action == "list":
            return store.list_specs(), 0
        spec = store.load(args.spec)
        if args.action == "show":
            return spec.as_dict(), 0
        if args.action == "defaults":
            return spec.defaults(), 0
        if args.action == "validate-defaults":
            validations = spec.validate_defaults()
            issues = [result for result in validations if not result["valid"]]
            return {"checked": len(validations), "valid": not issues, "issues": issues}, int(bool(issues))
        result = spec.validate_value(args.parameter, args.value)
        return {"parameter": args.parameter, "value": result}, int(not result["valid"])
    if args.area == "coverage":
        ledger = json.loads(files("cbus_toolkit").joinpath("capabilities.json").read_text())
        # The ledger issues implemented/in_progress/pending (never "verified");
        # parity burden lives in the ledger IDs themselves, including
        # toolkit-differential-acceptance and unit-hardware-acceptance.
        complete = ledger["census_complete"] and all(x["status"] == "implemented" for x in ledger["features"])
        return {"complete": complete, **ledger}, int(args.require_complete and not complete)
    raise ValueError("Unknown command area")


def main(argv=None):
    args = build_parser().parse_args(argv)
    from .edlt_global_cli import error_payload as global_error_payload
    from .edlt_scene_live_cli import error_payload as live_error_payload
    from .toolkit_preferences_cli import error_payload as preference_error_payload
    from .toolkit_updates_cli import error_payload as update_error_payload
    from .toolkit_update_metadata_cli import error_payload as metadata_error_payload
    from .toolkit_update_revocation_cli import error_payload as revocation_error_payload
    from .toolkit_update_conditions_cli import error_payload as condition_error_payload
    from .toolkit_live_update_conditions_cli import error_payload as live_condition_error_payload
    from .toolkit_database_csv_cli import error_payload as database_csv_error_payload
    from .pci_routed_recall_cli import error_payload as routed_recall_error_payload
    from .pci_routed_identify_cli import error_payload as routed_identify_error_payload
    from .project_repair_cli import error_payload as project_repair_error_payload
    from .thermostat_schedule_cli import error_payload as schedule_error_payload
    try:
        result, status = run(args)
        stream = args.area == "cgate" and args.action == "events"
        # JSON escapes preserve Unicode even when redirected Windows stdout uses
        # a legacy code page. An output encoding error must not mask a completed write.
        try:
            print(json.dumps(result, default=_json_default, ensure_ascii=True, indent=None if args.compact or stream else 2))
        except BaseException as output_error:
            if args.area == "cgate" and args.action in ("thermostat-schedule-levels", "thermostat-schedule-compose"):
                from .thermostat_schedule_cli import record_output_error
                record_output_error(args, output_error)
            if args.area == "update-condition-live":
                from .toolkit_live_update_conditions_cli import record_output_error
                record_output_error(args, output_error)
            raise
        return status
    except (ValueError, OSError, RuntimeError) as exc:
        scheduling = schedule_error_payload(exc, args)
        if scheduling:
            try:
                message = str(exc)
            except BaseException:
                message = "<unprintable>"
            print(json.dumps({"error": message, "type": type(exc).__name__, **scheduling},
                             default=_json_default), file=sys.stderr)
            return 1
        print(json.dumps({"error": str(exc), "type": type(exc).__name__, **getattr(exc, "details", {}),
                          **_selected_serial_error_payload(exc), **_programming_cleanup_payload(exc),
                          **_cgate_cleanup_payload(exc), **_edlt_label_clear_payload(exc), **_edlt_factory_default_payload(exc), **_edlt_ordered_payload(exc, args), **global_error_payload(exc, args), **live_error_payload(exc, args), **preference_error_payload(exc, args), **update_error_payload(exc, args), **metadata_error_payload(exc, args), **revocation_error_payload(exc, args), **condition_error_payload(exc, args), **live_condition_error_payload(exc, args), **database_csv_error_payload(exc, args), **routed_recall_error_payload(exc, args), **routed_identify_error_payload(exc, args), **project_repair_error_payload(exc, args)},
                         default=_json_default), file=sys.stderr)
        return 1
    except KeyboardInterrupt as exc:
        scheduling = schedule_error_payload(exc, args)
        if scheduling:
            print(json.dumps({"error": "Interrupted", **scheduling}, default=_json_default), file=sys.stderr)
            return 130
        evidence = getattr(exc, "physical_address_evidence", None)
        result = {"error": "Interrupted", **(evidence if isinstance(evidence, dict) else {})}
        result.update(_selected_serial_error_payload(exc))
        result.update(_programming_cleanup_payload(exc))
        result.update(_cgate_cleanup_payload(exc))
        result.update(_edlt_label_clear_payload(exc))
        result.update(_edlt_factory_default_payload(exc))
        result.update(_edlt_ordered_payload(exc, args))
        result.update(global_error_payload(exc, args))
        result.update(live_error_payload(exc, args))
        result.update(preference_error_payload(exc, args))
        result.update(update_error_payload(exc, args))
        result.update(metadata_error_payload(exc, args))
        result.update(revocation_error_payload(exc, args))
        result.update(condition_error_payload(exc, args))
        result.update(live_condition_error_payload(exc, args))
        result.update(database_csv_error_payload(exc, args))
        result.update(routed_recall_error_payload(exc, args))
        result.update(routed_identify_error_payload(exc, args))
        result.update(project_repair_error_payload(exc, args))
        for name in ("pci_mmi_observation", "pci_serial_observation", "pci_inventory_observation", "usb_dfu_evidence", "edlt_display_evidence", "edlt_mra_evidence", "edlt_general_evidence", "edlt_standby_evidence", "edlt_colours_evidence", "edlt_navigation_evidence", "edlt_quick_status_evidence", "edlt_activation_evidence", "edlt_page_control_evidence", "edlt_lifecycle_evidence", "edlt_restore_levels_evidence", "edlt_applications_evidence", "edlt_corridor_evidence", "edlt_blank_evidence", "edlt_reset_evidence", "edlt_scene_manager_evidence", "edlt_scene_live_evidence"):
            evidence = getattr(exc, name, None)
            if isinstance(evidence, dict):
                result[name] = evidence
        print(json.dumps(result, default=_json_default), file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
