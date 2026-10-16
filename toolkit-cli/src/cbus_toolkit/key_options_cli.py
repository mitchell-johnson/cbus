"""CLI for custom key micro-functions, power-up broadcast and Neo indicators."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

OFFLINE_ACTIONS = ("micro-functions", "custom-plan", "neo-custom-plan", "power-up-plan",
                   "neo-indicator-plan", "neo-style-plan", "neo-indicator-editor-show",
                   "neo-indicator-editor-plan")
NATIVE_ACTIONS = ("key-micro-functions", "neo-key-micro-functions", "power-up", "neo-indicators",
                  "neo-indicator-styles", "neo-indicator-editor")

NEO_EDITOR_ACTIONS = ("neo-indicator-editor-show", "neo-indicator-editor-plan", "neo-indicator-editor")


def _number(text):
    return int(text, 0)


def _stage_options(parser):
    parser.add_argument("--key", dest="key_number", type=_number, required=True, help="Physical key number, starting at 1")
    for stage in ("jp", "sr", "lp", "lr"):
        parser.add_argument("--" + stage, help=f"{stage.upper()} micro-function name or code 0..15")


def _power_up_options(parser):
    parser.add_argument("--enable-block", dest="enable_blocks", type=_number, action="append", default=[],
                        help="Coupler block 1..8 to broadcast on power-up (bistable keys only)")
    parser.add_argument("--disable-block", dest="disable_blocks", type=_number, action="append", default=[])
    parser.add_argument("--broadcast", action=argparse.BooleanOptionalAction, default=None,
                        help="KEYBC2/KEYBC4/DINAUX4 unit-wide Broadcast Values on Power Up")


def _indicator_options(parser):
    parser.add_argument("--brightness", choices=("fixed", "group", "first_block"))
    parser.add_argument("--brightness-percent", type=_number, help="Fixed level 0..100")
    parser.add_argument("--brightness-group", type=_number, help="Level-of-group address 0..255 (255 = unused)")
    parser.add_argument("--key-press-level", type=_number, help="Key-press brightness 0..15")
    parser.add_argument("--key-press-seconds", type=_number, help="Key-press brightening 1..15 s, 0 disables")
    for name in ("nightlight", "ignore-first-key-press", "timer-flash", "id-backlight"):
        parser.add_argument("--" + name, action=argparse.BooleanOptionalAction, default=None)


def _style_options(parser):
    from .neo_indicators import COLOURS, STYLES
    parser.add_argument("--colour", choices=tuple(COLOURS), required=True)
    parser.add_argument("--style", choices=tuple(STYLES), help="Omit to leave each key's style unchanged")


def _neo_editor_options(parser):
    parser.add_argument("--controls", type=Path, required=True,
                        help="JSON array of ordered indicator controls; [] previews load/save normalization")


def _neo_editor_native_options(parser):
    options = parser.add_mutually_exclusive_group(required=True)
    options.add_argument("--controls", type=Path, help="JSON array of ordered indicator controls")
    options.add_argument("--plan", type=Path, help="Apply a previously reviewed indicator plan with fresh guards")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key: " + key)
        result[key] = value
    return result


def _controls(path):
    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    if not isinstance(value, list):
        raise ValueError("Indicator controls must be a JSON array in callback order")
    return value


def offline_options(keyops):
    keyops.add_parser("micro-functions", help="List the TfrmKeyMicroFunctions value domain")
    for action in NEO_EDITOR_ACTIONS[:2]:
        p = keyops.add_parser(action, help="Inspect or plan the per-unit Neo indicator panel")
        p.add_argument("spec")
        p.add_argument("file", type=Path, help="PP export snapshot or JSON parameter mapping")
        p.add_argument("--firmware", help="Firmware for a bare mapping (default: 2.5.00)")
        p.add_argument("--catalog-number", help="Catalogue colour labels for a bare mapping")
        if action.endswith("-plan"):
            _neo_editor_options(p)
    for action, helper, text in (("custom-plan", _stage_options, "Plan classic per-key custom micro-functions"),
                                 ("neo-custom-plan", _stage_options, "Plan Neo-core per-key custom micro-functions"),
                                 ("power-up-plan", _power_up_options, "Plan coupler or broadcast power-up settings"),
                                 ("neo-indicator-plan", _indicator_options, "Plan Neo-core indicator options"),
                                 ("neo-style-plan", _style_options, "Plan Neo-core indicator style and colour")):
        p = keyops.add_parser(action, help=text)
        p.add_argument("spec")
        p.add_argument("file", type=Path, help="PP export snapshot or JSON parameter mapping")
        helper(p)


def native_options(unops):
    for action, helper, text in (
            ("key-micro-functions", _stage_options, "Set classic key JP/SR/LP/LR micro-functions with verified readback"),
            ("neo-key-micro-functions", _stage_options, "Set Neo-core key JP/SR/LP/LR micro-functions with verified readback"),
            ("power-up", _power_up_options, "Set coupler GroupAssertOnPowerup or GAVBroadcastFlag"),
            ("neo-indicators", _indicator_options, "Set Neo-core indicator brightness, key-press and nightlight options"),
            ("neo-indicator-editor", _neo_editor_native_options, "Edit the per-unit Neo indicator panel in callback order"),
            ("neo-indicator-styles", _style_options, "Set Neo-core indicator style and on colour for every key")):
        p = unops.add_parser(action, help=text)
        p.add_argument("--spec-dir", type=Path, default=os.environ.get("CBUS_UNITSPEC_DIR"))
        p.add_argument("--spec", required=True, help="Exact vendor schema, such as KEY4.xml, BCN4B.xml or KEYM4.xml")
        helper(p)


def _editor(action, spec_dir, spec_name):
    from .unitspec import UnitSpecStore
    if spec_dir is None:
        raise ValueError("Use --spec-dir or CBUS_UNITSPEC_DIR for decoded vendor specifications")
    spec = UnitSpecStore(spec_dir).load(spec_name)
    if action in NEO_EDITOR_ACTIONS:
        from .neo_indicator_editor import NeoIndicatorEditor
        return NeoIndicatorEditor(spec)
    if action in ("custom-plan", "key-micro-functions"):
        from .macros import ClassicKeys
        return ClassicKeys(spec)
    if action in ("neo-custom-plan", "neo-key-micro-functions"):
        from .extended_macros import ExtendedKeys
        return ExtendedKeys(spec)
    if action in ("power-up-plan", "power-up"):
        from .input_power_up import power_up_editor
        return power_up_editor(spec)
    if action in ("neo-indicator-plan", "neo-indicators"):
        from .neo_indicators import NeoIndicatorOptions
        return NeoIndicatorOptions(spec)
    from .neo_indicators import NeoIndicatorStyles
    return NeoIndicatorStyles(spec)


def _settings(action, args, editor):
    if action in ("custom-plan", "neo-custom-plan", "key-micro-functions", "neo-key-micro-functions"):
        stages = {stage: getattr(args, stage) for stage in ("jp", "sr", "lp", "lr") if getattr(args, stage) is not None}
        stages = {stage: int(value, 0) if value[:1].isdigit() else value for stage, value in stages.items()}
        return "micro_functions", {"key": args.key_number, "stages": stages}
    if action in ("power-up-plan", "power-up"):
        from .input_power_up import CouplerPowerUp
        if isinstance(editor, CouplerPowerUp):
            if args.broadcast is not None:
                raise ValueError("Couplers use --enable-block/--disable-block, not --broadcast")
            return "plan", {"enable": args.enable_blocks, "disable": args.disable_blocks}
        if args.enable_blocks or args.disable_blocks or args.broadcast is None:
            raise ValueError("This unit takes --broadcast or --no-broadcast only")
        return "plan", {"broadcast": args.broadcast}
    if action in ("neo-indicator-plan", "neo-indicators"):
        names = ("brightness", "brightness_percent", "brightness_group", "key_press_level", "key_press_seconds",
                 "nightlight", "ignore_first_key_press", "timer_flash", "id_backlight")
        options = {name: getattr(args, name) for name in names if getattr(args, name) is not None}
        if not options:
            raise ValueError("Supply at least one indicator option")
        return "plan", options
    return "plan", {"colour": args.colour, "style": args.style}


def offline(args):
    if args.action == "micro-functions":
        from .macros import MICRO_FUNCTION_LABELS, MICRO_FUNCTIONS, STAGES
        names = {code: name for name, code in MICRO_FUNCTIONS.items()}
        return {"stages": list(STAGES), "micro_functions": [
            {"code": code, "name": names[code], "label": label} for code, label in MICRO_FUNCTION_LABELS.items()]}, 0
    editor = _editor(args.action, args.spec_dir, args.spec)
    values = json.loads(args.file.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    if not isinstance(values, dict):
        raise ValueError("Expected a PP parameter mapping or export snapshot")
    if args.action in NEO_EDITOR_ACTIONS:
        identity = None
        if "format" in values:
            if values.get("format") != "cbus-cli-parameters-v1":
                raise ValueError("Snapshot format differs from the selected editor")
            identity = {name: values.get(name) for name in ("unit_type", "firmware", "catalog_number")}
            if (args.firmware is not None and args.firmware != identity["firmware"]
                    or args.catalog_number is not None and args.catalog_number != identity["catalog_number"]):
                raise ValueError("Snapshot identity differs from the explicit firmware or catalogue")
            values = values.get("parameters")
            if not isinstance(values, dict):
                raise ValueError("Snapshot requires a parameter mapping")
        elif args.firmware is not None or args.catalog_number is not None:
            identity = {"unit_type": editor.unit_type, "firmware": args.firmware or "2.5.00",
                        "catalog_number": args.catalog_number}
        if args.action.endswith("-show"):
            return editor.show(values, identity=identity), 0
        return editor.plan(values, _controls(args.controls), identity=identity).as_dict(), 0
    if "format" in values:
        if values.get("format") != "cbus-cli-parameters-v1" or values.get("unit_type") != editor.unit_type:
            raise ValueError("Snapshot format or unit type differs from the selected schema")
        values = values.get("parameters")
        if not isinstance(values, dict):
            raise ValueError("Snapshot requires a parameter mapping")
    method, options = _settings(args.action, args, editor)
    planner = editor.plan_micro_functions if method == "micro_functions" else editor.plan
    return planner(values, **options).as_dict(), 0


def native(args, session):
    editor = _editor(args.remote_action, args.spec_dir, args.spec)
    if args.remote_action == "neo-indicator-editor":
        if args.plan is not None:
            from .neo_indicator_editor import NeoIndicatorPlan
            plan = NeoIndicatorPlan.from_dict(json.loads(args.plan.read_text(encoding="utf-8"),
                                                       object_pairs_hook=_unique_object))
            return editor.apply(session, plan)
        return editor.configure(session, operations=_controls(args.controls))
    method, options = _settings(args.remote_action, args, editor)
    if method == "micro_functions":
        return editor.configure_micro_functions(session, **options)
    return editor.configure(session, **options)
