"""CLI for the ST7 PIR and SENLL light-level sensor dialogs.

Offline: ``cbus-toolkit sensors pir-plan|light-level-plan FILE``. Native:
``cbus-toolkit cgate ... unit ... sensor-pir|sensor-light-level``. Both run
the dialog model and the complete Toolkit save; see docs/sensors.md.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

NATIVE_ACTIONS = ("sensor-pir", "sensor-light-level")
OFFLINE_ACTIONS = ("pir-plan", "light-level-plan")
KEY_FIELDS = ("block", "group", "timer_seconds", "expiry")
EXPIRY = ("idle", "off", "down", "ramp_off", "recall1", "recall2", "ramp_recall1")


def _number(text):
    return int(text, 0)


def _key(text):
    """KEY:FIELD=VALUE[,FIELD=VALUE...], for example 1:block=1,group=41,timer_seconds=300,expiry=ramp_off."""
    key, separator, rest = text.partition(":")
    if not separator or not rest:
        raise argparse.ArgumentTypeError("Use KEY:FIELD=VALUE[,FIELD=VALUE]")
    options = {}
    for item in rest.split(","):
        name, equals, value = item.partition("=")
        name = name.strip().replace("-", "_")
        if not equals or name not in KEY_FIELDS or name in options:
            raise argparse.ArgumentTypeError("Key fields are block, group, timer_seconds and expiry, each once")
        if name == "expiry":
            if value not in EXPIRY:
                raise argparse.ArgumentTypeError("expiry must be one of " + ", ".join(EXPIRY))
            options[name] = value
        else:
            try:
                options[name] = _number(value)
            except ValueError as error:
                raise argparse.ArgumentTypeError(f"{name} must be an integer") from error
    try:
        return _number(key), options
    except ValueError as error:
        raise argparse.ArgumentTypeError("KEY must be 1..4") from error


def _group(text):
    return 255 if text.lower() == "none" else _number(text)


def _on_off_control(text):
    field, equals, value = text.partition('=')
    if not equals or field not in ('application', 'group'):
        raise argparse.ArgumentTypeError('Use application=primary|secondary or group=0..254|none')
    if field == 'application':
        if value not in ('primary', 'secondary'):
            raise argparse.ArgumentTypeError('On/off control application must be primary or secondary')
        return {'application': value}
    try:
        value = _group(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError('On/off control group must be 0..254 or none/255') from error
    if not 0 <= value <= 255:
        raise argparse.ArgumentTypeError('On/off control group must be 0..254 or none/255')
    return {'group': value}


def _pir_options(parser):
    parser.add_argument("--key", dest="pir_keys", type=_key, action="append", default=[],
                        help="Fixed key 1..4 edit KEY:FIELD=VALUE[,...]; fields block (1..4), group "
                             "(0..254 or 255), timer_seconds (0..65535) and expiry")
    functions = parser.add_mutually_exclusive_group()
    functions.add_argument("--restore-functions", dest="restore_functions", action="store_true", default=None,
                           help="Answer the Toolkit prompt by restoring an edited key's fixed function")
    functions.add_argument("--keep-functions", dest="restore_functions", action="store_false",
                           help="Answer the Toolkit prompt by keeping an edited key's custom function")
    link = parser.add_mutually_exclusive_group()
    link.add_argument("--darkness-same-as-light", dest="darkness_same_as_light", action="store_true", default=None)
    link.add_argument("--separate-darkness", dest="darkness_same_as_light", action="store_false")
    parser.add_argument("--enable-group", dest="pir_enable_group", type=_group, help="Occupancy enable group; 255 or none removes it")
    parser.add_argument("--enabled-when", dest="pir_enabled_when", choices=("on", "off"))
    parser.add_argument("--power-up", choices=("disabled", "enabled", "resume"))
    parser.add_argument("--allow-shared-block", dest="pir_allow_shared_block", action="store_true")


def _light_level_options(parser):
    for name, help_text in (("level-group", "Light level group (block 2)"), ("on-off-group", "Light on/off group (block 3)"),
                            ("broadcast-group", "Broadcast group (block 5)"),
                            ("enable-group", "Maintenance enable group")):
        parser.add_argument("--" + name, dest="ll_" + name.replace("-", "_"), type=_group,
                            help=help_text + "; 0..254, or 255/none")
    parser.add_argument("--on-off-application", dest="ll_on_off_application", choices=("primary", "secondary"))
    parser.add_argument('--on-off-control', dest='ll_on_off_controls', type=_on_off_control, action='append',
                        help='Ordered fresh SENLL callback: application=primary|secondary or group=N|none; repeat for history')
    parser.add_argument("--indicator", dest="ll_indicator", choices=("light-level", "on-off", "enable"))
    parser.add_argument("--target-lux", dest="ll_target_lux", type=_number, help="0..2000 lux; stored as Ceil(lux/10)")
    parser.add_argument("--margin-percent", dest="ll_margin_percent", type=_number, help="0..100")
    parser.add_argument("--broadcast-interval-seconds", dest="ll_broadcast_interval_seconds", type=_number,
                        help="Block 5 broadcast interval, 10..65535 seconds; preserves other timers")
    parser.add_argument("--power-up", dest="ll_power_up", choices=("disabled", "enabled", "resume"),
                        help="Light-level maintenance state after power failure, with the Toolkit save order")
    parser.add_argument("--status-report-interval", dest="ll_status_report_interval", type=_number,
                        help="Global status-report interval, native integer 3..255 seconds")


def offline_options(sensor_ops):
    """Add the PIR and SENLL plan actions under ``cbus-toolkit sensors``."""
    p = sensor_ops.add_parser("pir-plan", help="Plan the ST7 PIR dialog and Toolkit save without C-Gate")
    p.add_argument("file", type=Path, help="SENPIROA/SENPIRIA/SENPIRIB PP export, or parameter mapping with --spec")
    p.add_argument("--spec", help="Specification for a bare mapping, for example SENPIRIA_ST7.xml")
    _pir_options(p)
    p = sensor_ops.add_parser("light-level-plan", help="Plan the ST7 SENLL dialog and Toolkit save without C-Gate")
    p.add_argument("file", type=Path, help="SENLL 2.0.01..2.4.99 PP export or parameter mapping")
    _light_level_options(p)


def native_options(unops):
    p = unops.add_parser("sensor-pir", help="Edit the ST7 PIR dialog (SENPIROA/SENPIRIA/SENPIRIB) with the Toolkit save")
    p.add_argument("--spec-dir", type=Path, default=os.environ.get("CBUS_UNITSPEC_DIR"))
    _pir_options(p)
    p = unops.add_parser("sensor-light-level", help="Edit the ST7 SENLL light-level dialog with the Toolkit save")
    p.add_argument("--spec-dir", type=Path, default=os.environ.get("CBUS_UNITSPEC_DIR"))
    _light_level_options(p)


def _store(spec_dir):
    from .unitspec import UnitSpecStore
    if spec_dir is None:
        raise ValueError("Use --spec-dir or CBUS_UNITSPEC_DIR for decoded vendor specifications")
    return UnitSpecStore(spec_dir)


def pir_settings(args):
    keys = {}
    for key, options in args.pir_keys:
        if key in keys:
            raise ValueError(f"Key {key} is given more than once")
        keys[key] = options
    settings = {"keys": keys or None, "restore_functions": args.restore_functions,
                "darkness_same_as_light": args.darkness_same_as_light, "enable_group": args.pir_enable_group,
                "enabled_when": args.pir_enabled_when, "power_up": args.power_up,
                "allow_shared_block": args.pir_allow_shared_block}
    return {k: v for k, v in settings.items() if v is not None}


def light_level_settings(args):
    controls = getattr(args, 'll_on_off_controls', None)
    if controls is not None and any(value is not None for value in
            (args.ll_on_off_group, args.ll_on_off_application, args.ll_level_group,
             args.ll_broadcast_group, args.ll_enable_group)):
        raise ValueError('Explicit --on-off-control cannot be mixed with flat application/group edits')
    settings = {"level_group": args.ll_level_group, "on_off_group": args.ll_on_off_group,
                "broadcast_group": args.ll_broadcast_group, "enable_group": args.ll_enable_group,
                "on_off_application": args.ll_on_off_application,
                "indicator": args.ll_indicator.replace("-", "_") if args.ll_indicator else None,
                "target_lux": args.ll_target_lux, "margin_percent": args.ll_margin_percent,
                "broadcast_interval_seconds": args.ll_broadcast_interval_seconds, "power_up": args.ll_power_up,
                "status_report_interval": args.ll_status_report_interval, 'on_off_controls': controls}
    return {k: v for k, v in settings.items() if v is not None}


def offline(args):
    """Return (plan dictionary, exit status) for ``sensors pir-plan|light-level-plan``."""
    from .cli import _parameter_snapshot
    identity = []
    if args.action == "pir-plan":
        from .pir_sensors import PIRSensor, check_profile
        values = _parameter_snapshot(args.file, check_profile, identity=identity)
        if identity:
            spec_name = check_profile(*identity)[1]
            if args.spec not in (None, spec_name):
                raise ValueError(f"{identity[0]} {identity[1]} uses {spec_name}, not {args.spec}")
        elif args.spec is None:
            raise ValueError("A bare parameter mapping requires --spec")
        else:
            spec_name = args.spec
        sensor = PIRSensor(_store(args.spec_dir).load(spec_name))
        return sensor.plan(values, identity=tuple(identity) or None, **pir_settings(args)).as_dict(), 0
    from .light_level_sensors import PROFILE, LightLevelSensor, check_profile
    values = _parameter_snapshot(args.file, check_profile, identity=identity)
    sensor = LightLevelSensor(_store(args.spec_dir).load(PROFILE["spec_filename"]))
    return sensor.plan(values, identity=tuple(identity) or None, **light_level_settings(args)).as_dict(), 0


def native(args, session):
    """Apply one dialog edit (or the unchanged-dialog save) to an open PP session."""
    if args.remote_action == "sensor-pir":
        from .pir_sensors import PIRSensor, check_profile
        spec_name = check_profile(session.unit_type, session.firmware, session.catalog_number,
                                  subject="Native session")[1]
        return PIRSensor(_store(args.spec_dir).load(spec_name)).configure(session, **pir_settings(args))
    from .light_level_sensors import PROFILE, LightLevelSensor, check_profile
    check_profile(session.unit_type, session.firmware, session.catalog_number, subject="Native session")
    sensor = LightLevelSensor(_store(args.spec_dir).load(PROFILE["spec_filename"]))
    return sensor.configure(session, **light_level_settings(args))
