"""CLI adapters for the wireless gateway remote mapping, WRM unit globals and C-Gate boundary."""
from __future__ import annotations

import os
from pathlib import Path


def _pair(text, label):
    key, separator, value = text.partition('=')
    if not separator or not key.strip().isdecimal() or not value.strip():
        raise ValueError(f'{label} uses N=VALUE')
    return int(key), value.strip()


def _integer(text):
    try:
        return int(text, 0)
    except ValueError as error:
        raise ValueError(f'Expected an integer, got {text!r}') from error


def gateway_options(parser):
    parser.add_argument('--mode', choices=('network-gateway', 'remote-switch'), help='Mode radio group')
    parser.add_argument('--remote', type=int, help='Remote Control page 1..8')
    parser.add_argument('--serial', help="Remote identity as a 32-bit integer (decimal or 0x hex), or 'none'")
    parser.add_argument('--remote-key', dest='remote_keys', action='append', default=[], metavar='K=ASSIGNMENT',
                        help='Dialog key 1..10: group:G[:primary|secondary], group:none, scene-set:N or scene-toggle:N')
    parser.add_argument('--remote-slot', dest='remote_slots', action='append', default=[], metavar='S=ASSIGNMENT',
                        help='Raw PP key slot 1..16 with the same assignment grammar (bypasses the key map)')


def gateway_settings(args):
    settings = {'mode': args.mode, 'remote': args.remote}
    if args.serial is not None:
        settings['serial'] = None if args.serial.strip().lower() == 'none' else _integer(args.serial)
    for option, target in (('key', 'keys'), ('slot', 'slots')):
        pairs = {}
        for text in getattr(args, 'remote_' + target):
            index, value = _pair(text, '--remote-' + option)
            if index in pairs:
                raise ValueError(f'--remote-{option} {index} was selected more than once')
            pairs[index] = value
        if pairs:
            settings[target] = pairs
    return {k: v for k, v in settings.items() if v is not None or k == 'serial'}


def globals_options(parser):
    parser.add_argument('--learn-mode', choices=('off', 'current', 'any'),
                        help='Allow Learn Mode with Current or Any Application Learn')
    parser.add_argument('--network-learn', choices=('on', 'off'), help='Allow Network Learn')
    parser.add_argument('--reset-learned', action='store_true', help='Reset the learn history (LearnedFlag)')
    parser.add_argument('--house-code', help='Eight hex digits in Toolkit display order (not a Toolkit control)')
    parser.add_argument('--key-enable-mask', action='append', default=[], metavar='N=VALUE',
                        help='KeyEnableMaskN 1..4, 0..0xFFFF (not a Toolkit control)')
    parser.add_argument('--key-mask-allowed', type=_integer, help='KeyMaskAllowed 0..255 (not a Toolkit control)')
    parser.add_argument('--key-mask-save', type=_integer, help='KeyMaskSave 0..255 (not a Toolkit control)')


def globals_settings(args):
    masks = {}
    for text in args.key_enable_mask:
        index, value = _pair(text, '--key-enable-mask')
        if index in masks:
            raise ValueError(f'--key-enable-mask {index} was selected more than once')
        masks[index] = _integer(value)
    settings = {'learn_mode': args.learn_mode, 'house_code': args.house_code,
                'network_learn': None if args.network_learn is None else args.network_learn == 'on',
                'key_enable_masks': masks or None, 'key_mask_allowed': args.key_mask_allowed,
                'key_mask_save': args.key_mask_save}
    settings = {k: v for k, v in settings.items() if v is not None}
    if args.reset_learned:
        settings['reset_learned'] = True
    return settings


def options(commands):
    """Register the offline ``wireless`` command group."""
    wireless = commands.add_parser('wireless', help='Show or plan wireless gateway remotes and WRM globals offline')
    wireless.add_argument('--spec-dir', type=Path, default=os.environ.get('CBUS_UNITSPEC_DIR'))
    ops = wireless.add_subparsers(dest='action', required=True)
    for name, add in (('gateway', gateway_options), ('globals', globals_options)):
        group = ops.add_parser(name, help=('WGATE5F 2.2.90..2.4.99 Mode and Remotes tab' if name == 'gateway'
                                           else 'WRM 2.x learn flags, house code and key masks'))
        gops = group.add_subparsers(dest='wireless_action', required=True)
        for action in ('show', 'plan'):
            p = gops.add_parser(action)
            p.add_argument('file', type=Path, help='PP export (cbus-cli-parameters-v1) or bare parameter mapping')
            p.add_argument('--unit-type', help='Required for a bare parameter mapping')
            p.add_argument('--firmware', help='Required for a bare parameter mapping')
            p.add_argument('--catalog-number')
            if action == 'plan':
                add(p)
    p = ops.add_parser('boundary', help='Show the C-Gate wireless learn and unit-action commands (no I/O)')
    p.add_argument('--unit', type=int, default=None, help='Unit address for the unit-action commands')
    p.add_argument('--learn', nargs=3, type=int, metavar=('APP', 'GRADE', 'GROUP'),
                   help='Compose the NET LEARN command body')


def _source(args):
    from .edlt_global_cli import read_json
    values = read_json(args.file, limit=1024 * 1024)
    if not isinstance(values, dict):
        raise ValueError('Expected a PP parameter mapping or export snapshot')
    if 'format' in values:
        if values.get('format') != 'cbus-cli-parameters-v1':
            raise ValueError('Snapshot format differs from cbus-cli-parameters-v1')
        identity = tuple(values.get(key) for key in ('unit_type', 'firmware', 'catalog_number'))
        if any(value is not None and getattr(args, key) not in (None, value) for key, value in
               zip(('unit_type', 'firmware', 'catalog_number'), identity)):
            raise ValueError('Command-line identity differs from the snapshot identity')
        values = values.get('parameters')
        if not isinstance(values, dict):
            raise ValueError('Snapshot requires a parameter mapping')
        return identity, values
    if args.unit_type is None or args.firmware is None:
        raise ValueError('A bare parameter mapping requires --unit-type and --firmware')
    return (args.unit_type, args.firmware, args.catalog_number), values


def _store(spec_dir):
    from .unitspec import UnitSpecStore
    if spec_dir is None:
        raise ValueError('Use --spec-dir or CBUS_UNITSPEC_DIR for decoded vendor specifications')
    return UnitSpecStore(spec_dir)


def gateway_editor(spec_dir):
    from .wireless_gateway import SPEC_FILENAME, WirelessGatewayEditor
    return WirelessGatewayEditor(_store(spec_dir).load(SPEC_FILENAME))


def globals_editor(spec_dir, unit_type):
    from .wireless_unit_globals import WirelessGlobalsEditor, check_profile, spec_filename
    check_profile(unit_type, '2.0.0')
    return WirelessGlobalsEditor(_store(spec_dir).load(spec_filename(unit_type)), unit_type)


def offline(args):
    if args.action == 'boundary':
        from .wireless_commissioning import LIVE_NETWORK_REASON, net_learn_command, unit_action_commands
        result = {'format': 'cbus-wireless-cgate-boundary-v1', 'requires_live_network': LIVE_NETWORK_REASON,
                  'io_performed': False}
        if args.unit is not None:
            result['unit_actions'] = unit_action_commands(args.unit)
        if args.learn is not None:
            result['net_learn'] = net_learn_command(*args.learn)
        return result, 0
    identity, values = _source(args)
    if args.action == 'gateway':
        from .wireless_gateway import check_profile
        identity = check_profile(*identity)
        editor = gateway_editor(args.spec_dir)
        if args.wireless_action == 'show':
            return editor.show(values), 0
        return editor.plan(values, identity=identity, **gateway_settings(args)).as_dict(), 0
    from .wireless_unit_globals import check_profile
    identity = check_profile(*identity)
    editor = globals_editor(args.spec_dir, identity[0])
    if args.wireless_action == 'show':
        return editor.show(values), 0
    return editor.plan(values, identity=identity, **globals_settings(args)).as_dict(), 0


def native_options(unops):
    p = unops.add_parser('wireless-gateway', help='Show or edit the WGATE5F 2.2.90..2.4.99 Mode and Remotes tab')
    p.add_argument('--spec-dir', type=Path, default=os.environ.get('CBUS_UNITSPEC_DIR'))
    p.add_argument('--show', action='store_true', help='Report the Toolkit view without editing')
    p.add_argument('--plan', dest='wireless_plan', type=Path,
                   help='Apply a saved cbus-wireless-gateway-remotes-plan-v1 after a stale check')
    gateway_options(p)
    p = unops.add_parser('wireless-globals', help='Show or edit WRM 2.x learn flags, house code and key masks')
    p.add_argument('--spec-dir', type=Path, default=os.environ.get('CBUS_UNITSPEC_DIR'))
    p.add_argument('--show', action='store_true', help='Report the Toolkit view without editing')
    p.add_argument('--plan', dest='wireless_plan', type=Path,
                   help='Apply a saved cbus-wireless-unit-globals-plan-v1 after a stale check')
    globals_options(p)


def native(args, session):
    """Return (result, edited) for ``cgate unit ... wireless-gateway`` and ``wireless-globals``."""
    from .edlt_global_cli import read_json
    if args.remote_action == 'wireless-gateway':
        from .wireless_gateway import WirelessGatewayPlan as Plan
        editor = gateway_editor(args.spec_dir)
        edits = gateway_settings(args)
    else:
        from .wireless_unit_globals import WirelessGlobalsPlan as Plan
        editor = globals_editor(args.spec_dir, session.unit_type)
        edits = globals_settings(args)
    editor._verify_profile(session)
    editor._verify_session(session)
    if args.show:
        if edits or args.wireless_plan is not None:
            raise ValueError('--show cannot be combined with edits or --plan')
        return editor.show(session.values()), False
    if args.wireless_plan is not None:
        if edits:
            raise ValueError('--plan cannot be combined with edit options')
        return editor.apply(session, Plan.from_dict(read_json(args.wireless_plan, limit=1024 * 1024))), True
    if not edits:
        raise ValueError('Supply edit options, --plan or --show')
    return editor.configure(session, **edits), True
