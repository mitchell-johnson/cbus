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


def connection_options(parser):
    parser.add_argument('--application1', type=_integer, help='Application 1 (255 = All Applications)')
    parser.add_argument('--application2', type=_integer, help='Application 2 (255 = Unused)')
    parser.add_argument('--adjacent-network', choices=('on', 'off'))
    parser.add_argument('--synchronise-to-wired', choices=('on', 'off'))
    parser.add_argument('--destination-network', help='Remote network beyond the adjacent network, or none')
    parser.add_argument('--status-monitor-application', type=_integer)


def connection_settings(args):
    result = {name: getattr(args, name) for name in ('application1', 'application2', 'status_monitor_application')
              if getattr(args, name) is not None}
    for name in ('adjacent_network', 'synchronise_to_wired'):
        if getattr(args, name) is not None:
            result[name] = getattr(args, name) == 'on'
    if args.destination_network is not None:
        result['destination_network'] = (None if args.destination_network.lower() == 'none'
                                         else _integer(args.destination_network))
    return result


def _plan_file(value):
    # Connection documents carry topology and controls and can be fully checked
    # during argument parsing, before the CLI constructs a C-Gate client.
    from argparse import ArgumentTypeError
    from .edlt_global_cli import read_json
    from .wireless_connection import PLAN_FORMAT, WirelessConnectionPlan
    path = Path(value)
    try:
        from .wireless_scenes import PLAN_FORMAT as SCENES_FORMAT, WirelessScenesPlan
        from .wireless_project_remotes import PLAN_FORMAT as REMOTE_FORMAT, RemoteCreationPlan
        data = read_json(path, limit=32 * 1024 * 1024)
        if isinstance(data, dict) and data.get('format') == REMOTE_FORMAT:
            RemoteCreationPlan.from_dict(data)
        elif isinstance(data, dict) and data.get('format') == SCENES_FORMAT:
            WirelessScenesPlan.from_dict(data)
        elif isinstance(data, dict) and data.get('format') == PLAN_FORMAT:
            WirelessConnectionPlan.from_dict(data)
        else:
            from .wireless_gateway import WirelessGatewayPlan
            WirelessGatewayPlan.from_dict(data)
    except (OSError, ValueError) as error:
        raise ArgumentTypeError(str(error)) from error
    return path


def scenes_options(parser):
    parser.add_argument('--scenes', type=Path, required=True, help='Complete scene-definition JSON list (at most eight)')


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
    for name, add in (('gateway', gateway_options), ('globals', globals_options), ('connection', connection_options), ('scenes', scenes_options)):
        group = ops.add_parser(name, help=('WGATE5F 2.2.90..2.4.99 Mode and Remotes tab' if name == 'gateway'
                                           else 'Connection controls from frozen topology' if name == 'connection'
                                           else 'Stored scenes with existing project metadata' if name == 'scenes'
                                           else 'WRM 2.x learn flags, house code and key masks'))
        gops = group.add_subparsers(dest='wireless_action', required=True)
        for action in ('show', 'plan'):
            p = gops.add_parser(action)
            p.add_argument('file', type=Path, help='PP export (cbus-cli-parameters-v1) or bare parameter mapping')
            p.add_argument('--unit-type', help='Required for a bare parameter mapping')
            p.add_argument('--firmware', help='Required for a bare parameter mapping')
            p.add_argument('--catalog-number')
            if name in ('connection', 'scenes'):
                p.add_argument('--project-xml', type=Path, required=True, help='Frozen project XML / native DBGETXML snapshot')
                p.add_argument('--source-network', type=int, required=True)
                p.add_argument('--gateway-address', type=int, required=True)
            if action == 'plan':
                add(p)
    action_group = ops.add_parser('action', help='Typed cached reads and explicit wireless unit actions')
    action_ops = action_group.add_subparsers(dest='wireless_action', required=True)
    p = action_ops.add_parser('plan')
    p.add_argument('--project-xml', type=Path, required=True)
    p.add_argument('--catalogue-xml', type=Path, required=True)
    p.add_argument('--source-network', type=int, required=True)
    p.add_argument('--unit-address', type=int, required=True)
    p.add_argument('--operation', required=True, choices=('cached-status', 'cached-op-stats', 'mai-sync',
                                                       'recall-op-stats', 'reset-op-stats'))
    remote = ops.add_parser('project-remote', help='Create WTXU project metadata; no pairing or PP initialization')
    remote_ops = remote.add_subparsers(dest='wireless_action', required=True)
    p = remote_ops.add_parser('plan')
    p.add_argument('--project-xml', type=Path, required=True)
    p.add_argument('--catalogue-xml', type=Path, required=True, help='Original local CBusUnits XML catalogue')
    p.add_argument('--source-network', type=int, required=True)
    p.add_argument('--gateway-address', type=int, required=True)
    p.add_argument('--serial', required=True, help='Known canonical native decimal-dot serial')
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


def connection_editor(spec_dir):
    from .wireless_connection import WirelessConnectionEditor, SPEC_FILENAME
    return WirelessConnectionEditor(_store(spec_dir).load(SPEC_FILENAME))


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
    if args.action == 'action':
        from .wireless_project_remotes import FrozenRemoteProject, MAX_PROJECT_XML_BYTES
        from .wireless_actions import WirelessActionCatalogue, plan_wireless_action
        project = FrozenRemoteProject.from_xml(_bounded_xml(args.project_xml, MAX_PROJECT_XML_BYTES))
        catalogue = WirelessActionCatalogue.from_xml(_bounded_xml(args.catalogue_xml, MAX_PROJECT_XML_BYTES))
        return plan_wireless_action(project, catalogue=catalogue, source_network=args.source_network,
                                    unit_address=args.unit_address, operation=args.operation).as_dict(), 0
    if args.action == 'project-remote':
        from .wireless_project_remotes import (FrozenRemoteProject, RemoteCatalogue, plan_project_remote,
                                               MAX_PROJECT_XML_BYTES, MAX_CATALOGUE_XML_BYTES)
        project = FrozenRemoteProject.from_xml(_bounded_xml(args.project_xml, MAX_PROJECT_XML_BYTES))
        catalogue = RemoteCatalogue.from_xml(_bounded_xml(args.catalogue_xml, MAX_CATALOGUE_XML_BYTES))
        return plan_project_remote(project, source_network=args.source_network,
                                   gateway_address=args.gateway_address, serial=args.serial,
                                   catalogue=catalogue).as_dict(), 0
    identity, values = _source(args)
    if args.action == 'scenes':
        from .commissioning_route import read_project_snapshot
        from .edlt_global_cli import read_json
        from .wireless_gateway import check_profile
        from .wireless_scenes import FrozenSceneProject, WirelessScenesEditor
        identity = check_profile(*identity)
        editor = WirelessScenesEditor(_store(args.spec_dir).load('WGATE5X_2.xml'))
        project = FrozenSceneProject.from_xml(read_project_snapshot(args.project_xml))
        if args.wireless_action == 'show':
            project.topology.selected(args.source_network, args.gateway_address)
            return editor.show(values), 0
        return editor.plan(values, project=project, source_network=args.source_network,
                           unit_address=args.gateway_address, identity=identity,
                           scenes=read_json(args.scenes)).as_dict(), 0
    if args.action == 'connection':
        from .commissioning_route import read_project_snapshot
        from .wireless_connection import FrozenTopology
        editor = connection_editor(args.spec_dir)
        context = dict(topology=FrozenTopology.from_xml(read_project_snapshot(args.project_xml)),
                       source_network=args.source_network, unit_address=args.gateway_address, identity=identity)
        if args.wireless_action == 'show':
            return editor.show(values, **context), 0
        return editor.plan(values, **context, **connection_settings(args)).as_dict(), 0
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
    p.add_argument('--plan', dest='wireless_plan', type=_plan_file,
                   help='Apply a saved Remote mapping, Connection, Scenes or project-remote plan after a stale check')
    p.add_argument('--exclusive-project', action='store_true',
                   help='Required for Connection/Scenes/project-remote: exclusively own this closed project during apply')
    gateway_options(p)
    p = unops.add_parser('wireless-globals', help='Show or edit WRM 2.x learn flags, house code and key masks')
    p.add_argument('--spec-dir', type=Path, default=os.environ.get('CBUS_UNITSPEC_DIR'))
    p.add_argument('--show', action='store_true', help='Report the Toolkit view without editing')
    p.add_argument('--plan', dest='wireless_plan', type=Path,
                   help='Apply a saved cbus-wireless-unit-globals-plan-v1 after a stale check')
    globals_options(p)
    p = unops.add_parser('wireless-action', help='Cached wireless reads or explicitly authorized physical unit actions')
    p.add_argument('--plan', dest='wireless_action_plan', type=_action_plan_file, required=True)
    p.add_argument('--allow-physical-action', action='store_true',
                   help='Explicitly allow the planned physical DO action; never opens a network or retries')


def preflight(args):
    """Freeze wireless inputs and refuse unsafe targeting before any client I/O."""
    if getattr(args, 'action', None) == 'unit' and getattr(args, 'remote_action', None) == 'wireless-action':
        return action_preflight(args)
    from .edlt_global_cli import read_json
    from .wireless_connection import MAX_PROJECT_XML_BYTES, PLAN_FORMAT, WirelessConnectionPlan
    if (getattr(args, 'action', None) != 'unit'
            or getattr(args, 'remote_action', None) != 'wireless-gateway'
            or args.wireless_plan is None):
        return {}
    from .wireless_scenes import PLAN_FORMAT as SCENES_FORMAT, WirelessScenesPlan, WirelessScenesEditor
    data = read_json(args.wireless_plan, limit=32 * 1024 * 1024)
    # Cache the classification too: replacing a legacy plan file after preflight
    # must not select the Connection workflow after the client has connected.
    args._wireless_gateway_plan_data = data
    from .wireless_project_remotes import PLAN_FORMAT as REMOTE_FORMAT
    if isinstance(data, dict) and data.get('format') == REMOTE_FORMAT:
        return _project_remote_preflight(args, data)
    if not isinstance(data, dict) or data.get('format') not in (PLAN_FORMAT, SCENES_FORMAT):
        from .wireless_gateway import WirelessGatewayPlan
        WirelessGatewayPlan.from_dict(data)
        return {}
    scenes = data['format'] == SCENES_FORMAT
    plan = WirelessScenesPlan.from_dict(data) if scenes else WirelessConnectionPlan.from_dict(data)
    label = 'Scenes' if scenes else 'Connection'
    project = (plan.project.topology if scenes else plan.topology).facts['project']
    network = f'//{project}/{plan.source_network}'
    if args.source != f'/db{network}/p/{plan.unit_address}' or args.lock_address != network:
        raise ValueError(label + ' source and lock must exactly match the planned database gateway')
    if args.destination is not None or args.unit_type is not None:
        raise ValueError(label + ' plans require their loaded database source; omit --destination and --unit-type')
    if not args.exclusive_project:
        raise ValueError(label + ' apply requires exclusive project ownership')
    if args.show or gateway_settings(args):
        raise ValueError(label + ' --plan cannot be combined with --show or Remote mapping edits')
    if scenes:
        args._wireless_scenes_plan = plan
        args._wireless_scenes_editor = WirelessScenesEditor(_store(args.spec_dir).load('WGATE5X_2.xml'))
    else:
        args._wireless_connection_plan = plan
        args._wireless_connection_editor = connection_editor(args.spec_dir)
    # Native DBGETXML puts almost the entire document in one 347 row. These
    # bounds apply only to this command; XML parsing separately enforces 16 MiB.
    return {'max_line_bytes': MAX_PROJECT_XML_BYTES + 4096,
            'max_response_bytes': MAX_PROJECT_XML_BYTES + 65536}


def native(args, session):
    """Return (result, edited) for ``cgate unit ... wireless-gateway`` and ``wireless-globals``."""
    from .edlt_global_cli import read_json
    if args.remote_action == 'wireless-gateway':
        from .wireless_gateway import WirelessGatewayPlan as Plan
        editor = None
        edits = gateway_settings(args)
    else:
        from .wireless_unit_globals import WirelessGlobalsPlan as Plan
        editor = globals_editor(args.spec_dir, session.unit_type)
        edits = globals_settings(args)
    if args.remote_action == 'wireless-gateway' and args.wireless_plan is not None:
        from .wireless_connection import PLAN_FORMAT, native_topology
        if not hasattr(args, '_wireless_gateway_plan_data'):
            preflight(args)
        data = args._wireless_gateway_plan_data
        from .wireless_scenes import PLAN_FORMAT as SCENES_FORMAT, native_project
        if isinstance(data, dict) and data.get('format') == SCENES_FORMAT:
            plan = args._wireless_scenes_plan
            project = native_project(session, plan, exclusive_project=args.exclusive_project)
            return args._wireless_scenes_editor.apply(session, plan, project=project,
                                                    exclusive_project=args.exclusive_project), True
        if isinstance(data, dict) and data.get('format') == PLAN_FORMAT:
            if edits or args.show:
                raise ValueError('Connection --plan cannot be combined with --show or Remote mapping edits')
            if args.destination is not None:
                raise ValueError('Connection plans save only to their exact loaded source; omit --destination')
            plan = args._wireless_connection_plan
            topology = native_topology(session, plan, exclusive_project=args.exclusive_project)
            return args._wireless_connection_editor.apply(session, plan, topology=topology,
                                                        exclusive_project=args.exclusive_project), True
    if editor is None:
        editor = gateway_editor(args.spec_dir)
    editor._verify_profile(session)
    editor._verify_session(session)
    if args.show:
        if edits or args.wireless_plan is not None:
            raise ValueError('--show cannot be combined with edits or --plan')
        return editor.show(session.values()), False
    if args.wireless_plan is not None:
        if edits:
            raise ValueError('--plan cannot be combined with edit options')
        data = (args._wireless_gateway_plan_data if hasattr(args, '_wireless_gateway_plan_data')
                else read_json(args.wireless_plan, limit=1024 * 1024))
        return editor.apply(session, Plan.from_dict(data)), True
    if not edits:
        raise ValueError('Supply edit options, --plan or --show')
    return editor.configure(session, **edits), True


def _bounded_xml(path, cap):
    with path.open('rb') as stream:
        payload = stream.read(cap + 1)
    if len(payload) > cap:
        raise ValueError('Wireless XML input exceeds the command size cap')
    return payload


def _project_remote_preflight(args, data):
    from .wireless_project_remotes import RemoteCreationPlan, MAX_PROJECT_XML_BYTES
    plan = RemoteCreationPlan.from_dict(data)
    if args.source != plan.gateway_source or args.lock_address != plan.network_path:
        raise ValueError('Project remote source and lock must exactly match the planned database gateway')
    if args.destination is not None or args.unit_type is not None:
        raise ValueError('Project remote creation requires its existing database gateway; omit destination and unit-type')
    if not args.exclusive_project:
        raise ValueError('Project remote creation requires exclusive project ownership')
    if args.show or gateway_settings(args):
        raise ValueError('Project remote --plan cannot be combined with --show or Remote mapping edits')
    args._wireless_project_remote_plan = plan
    return {'max_line_bytes': MAX_PROJECT_XML_BYTES + 4096,
            'max_response_bytes': MAX_PROJECT_XML_BYTES + 65536}


def project_remote_native(args, client):
    """Metadata-only dispatch: never constructs Programmer or opens a PP session."""
    from .wireless_project_remotes import (apply_project_remote, preview_project_remote,
                                          RemoteCreationApplyError)
    plan = args._wireless_project_remote_plan
    operation = preview_project_remote if args.dry_run else apply_project_remote
    try:
        return operation(client, plan, exclusive_project=args.exclusive_project), 0
    except RemoteCreationApplyError as error:
        return {'error': str(error), 'remote_creation_evidence': error.details}, 1


def _action_plan_file(value):
    from argparse import ArgumentTypeError
    from .edlt_global_cli import read_json
    from .wireless_actions import WirelessActionPlan
    path = Path(value)
    try:
        WirelessActionPlan.from_dict(read_json(path, limit=32 * 1024 * 1024))
    except (OSError, ValueError) as error:
        raise ArgumentTypeError(str(error)) from error
    return path


def action_preflight(args):
    from .edlt_global_cli import read_json
    from .wireless_actions import WirelessActionPlan, validate_action_execution
    from .wireless_project_remotes import MAX_PROJECT_XML_BYTES
    plan = WirelessActionPlan.from_dict(read_json(args.wireless_action_plan, limit=32 * 1024 * 1024))
    if args.source != plan.source or args.lock_address != plan.network_path:
        raise ValueError('Wireless action source and lock must exactly match the planned physical unit')
    if args.destination is not None or args.unit_type is not None:
        raise ValueError('Wireless actions require their existing unit; omit destination and unit-type')
    validate_action_execution(plan, allow_physical_action=args.allow_physical_action,
                              timeout=args.timeout, preview=args.dry_run)
    args._wireless_action_plan = plan
    return {'max_line_bytes': MAX_PROJECT_XML_BYTES + 4096,
            'max_response_bytes': MAX_PROJECT_XML_BYTES + 65536}


def action_native(args, client):
    from .wireless_actions import (apply_wireless_action, preview_wireless_action,
                                   WirelessActionApplyError)
    plan = args._wireless_action_plan
    try:
        if args.dry_run:
            return preview_wireless_action(client, plan), 0
        return apply_wireless_action(client, plan, allow_physical_action=args.allow_physical_action), 0
    except WirelessActionApplyError as error:
        return {'error': str(error), 'wireless_action_evidence': error.details}, 1
