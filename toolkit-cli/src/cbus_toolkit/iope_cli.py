"""CLI for the IOPE occupancy-controller settings editor."""
from __future__ import annotations

import argparse
import os
from pathlib import Path

NATIVE_ACTION = "iope-settings"


def _number(text):
    return int(text, 0)


def _pair(text):
    key, separator, value = text.partition("=")
    if not separator:
        raise argparse.ArgumentTypeError("Expected KEY=VALUE")
    return key.strip(), value.strip()


def _edit_options(parser):
    onoff = ("on", "off")
    parser.add_argument("--long-press", type=_number, help="Long press time ordinal 6..63 (x16 ms)")
    parser.add_argument("--ramp-rate", type=_pair, action="append", default=[],
                        help="global1|global2|global3|scene=0..15 or a label such as '8 secs'")
    parser.add_argument("--status-report", type=_number, help="Status report interval 3..255")
    parser.add_argument("--debounce", type=_number, help="Sensor debounce ordinal 0..6")
    parser.add_argument("--recall-percent", type=_pair, action="append", default=[], help="G=0..100 for global 1..4")
    parser.add_argument("--recall-level", type=_pair, action="append", default=[], help="G=0..255 raw for global 1..4")
    parser.add_argument("--clock-gen", choices=onoff)
    parser.add_argument("--burden", choices=onoff)
    parser.add_argument("--sensor", type=_number, help="Sensor 1..2 for the sensor options")
    parser.add_argument("--disabled-when", choices=onoff, help="Sensor disabled while its enable group is on/off")
    parser.add_argument("--enable-group", help="Sensor enable group 0..254, or 'none'")
    parser.add_argument("--enable-application", choices=("primary", "enable-control"))
    parser.add_argument("--state-recovery", choices=("enabled", "disabled", "restore"))
    parser.add_argument("--enable-broadcast-block", type=_number, action="append", default=[],
                        help="Input block 1..8 to broadcast on power-up (bistable auxiliary, assigned group)")
    parser.add_argument("--disable-broadcast-block", type=_number, action="append", default=[])
    parser.add_argument("--output", type=_number, help="Output channel for the recovery options")
    parser.add_argument("--level-store", choices=onoff)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--recovery-percent", type=_number)
    group.add_argument("--recovery-level", type=_number)
    parser.add_argument("--block-timer", type=_pair, action="append", default=[],
                        help="B=SECONDS or B=H:MM:SS for input block 1..8")


def offline_options(commands):
    iope = commands.add_parser("iope-settings", help="Show or plan IOPE occupancy-controller settings without C-Gate")
    iope.add_argument("--spec-dir", type=Path, default=os.environ.get("CBUS_UNITSPEC_DIR"))
    ops = iope.add_subparsers(dest="action", required=True)
    for action in ("show", "plan"):
        p = ops.add_parser(action)
        p.add_argument("file", type=Path, help="IOPE PP export, or parameter mapping with --unit-type")
        p.add_argument("--unit-type", choices=("IOPE1R1", "IOPE2R2", "IOPE2C4"))
        if action == "plan":
            _edit_options(p)


def native_options(unops):
    p = unops.add_parser(NATIVE_ACTION, help="Show or edit IOPE Global, sensor enable, power failure and block timer settings")
    p.add_argument("--spec-dir", type=Path, default=os.environ.get("CBUS_UNITSPEC_DIR"))
    p.add_argument("--show", action="store_true", help="Report the Toolkit view without editing")
    p.add_argument("--plan", dest="iope_plan", type=Path, help="Apply a saved cbus-iope-settings-plan-v1 after a stale check")
    _edit_options(p)


def _editor(spec_dir, unit_type):
    from .iope_settings import IopeSettings, PROFILES, profile_refusal
    from .unitspec import UnitSpecStore
    if spec_dir is None:
        raise ValueError("Use --spec-dir or CBUS_UNITSPEC_DIR for decoded vendor specifications")
    if unit_type not in PROFILES:
        raise ValueError(profile_refusal(unit_type, None))
    return IopeSettings(UnitSpecStore(spec_dir).load(unit_type + ".xml"), unit_type)


def settings(args):
    flag = lambda value: None if value is None else value == "on"
    numbered = lambda pairs: {int(k, 0): int(v, 0) for k, v in pairs}
    options = {"long_press": args.long_press, "status_report": args.status_report, "debounce": args.debounce,
               "clock_gen": flag(args.clock_gen), "burden": flag(args.burden)}
    if args.ramp_rate:
        options["ramp_rates"] = {k: int(v, 0) if v.isdigit() else v for k, v in args.ramp_rate}
    if args.recall_percent:
        options["recall_percents"] = numbered(args.recall_percent)
    if args.recall_level:
        options["recall_levels"] = numbered(args.recall_level)
    sensor = {k: v for k, v in (("disabled_when", args.disabled_when), ("enable_application", args.enable_application),
                                ("state_recovery", args.state_recovery)) if v is not None}
    if args.enable_group is not None:
        sensor["enable_group"] = None if args.enable_group.lower() == "none" else int(args.enable_group, 0)
    if sensor and args.sensor is None:
        raise ValueError("Sensor options require --sensor")
    if args.sensor is not None:
        options["sensors"] = {args.sensor: sensor}
    output = {k: v for k, v in (("level_store", flag(args.level_store)), ("recovery_level", args.recovery_level),
                                ("recovery_percent", args.recovery_percent)) if v is not None}
    if output and args.output is None:
        raise ValueError("Output recovery options require --output")
    if args.output is not None:
        options["outputs"] = {args.output: output}
    if args.enable_broadcast_block or args.disable_broadcast_block:
        options.update(enable_broadcast=args.enable_broadcast_block, disable_broadcast=args.disable_broadcast_block)
    if args.block_timer:
        options["block_timers"] = {int(k, 0): int(v, 0) if ":" not in v else v for k, v in args.block_timer}
    return {k: v for k, v in options.items() if v is not None}


def offline(args):
    from .cli import _parameter_snapshot
    from .iope_settings import profile_refusal

    def check(unit_type, firmware, _catalog):
        reason = profile_refusal(unit_type, firmware)
        if reason:
            raise ValueError(reason)
    identity = []
    values = _parameter_snapshot(args.file, check, identity=identity)
    unit_type = identity[0] if identity else args.unit_type
    if unit_type is None or (identity and args.unit_type not in (None, unit_type)):
        raise ValueError("A bare parameter mapping requires a matching --unit-type")
    editor = _editor(args.spec_dir, unit_type)
    if args.action == "show":
        return editor.show(values), 0
    return editor.plan(values, identity=tuple(identity) or None, **settings(args)).as_dict(), 0


def native(args, session):
    """Return (result, edited)."""
    editor = _editor(args.spec_dir, session.unit_type)
    editor.verify_profile(session)
    edits = settings(args)
    if args.show:
        if edits or args.iope_plan is not None:
            raise ValueError("--show cannot be combined with edits or --plan")
        return editor.show(session.values()), False
    if args.iope_plan is not None:
        from .edlt_global_cli import read_json
        from .iope_settings import plan_from_dict
        if edits:
            raise ValueError("--plan cannot be combined with edit options")
        return editor.apply(session, plan_from_dict(read_json(args.iope_plan, limit=1024 * 1024))), True
    if not edits:
        raise ValueError("Supply IOPE edit options, --plan or --show")
    return editor.configure(session, **edits), True
