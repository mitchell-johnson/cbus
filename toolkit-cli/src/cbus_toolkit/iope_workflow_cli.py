"""Standalone database-only IOPE editor workflows.

Run ``python -m cbus_toolkit.iope_workflow_cli --help``.  The small registration
patch in docs can expose the same parser through cbus-toolkit.  No physical PP
path, automatic group creation, uncertain-save retry or implicit network open.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

LIMIT = 1024 * 1024


class PersistenceError(RuntimeError):
    def __init__(self, cause, evidence):
        self.evidence = dict(evidence)
        self.details = self.evidence  # Shared cbus-toolkit JSON error adapter.
        super().__init__(str(cause))


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key: ' + key)
        result[key] = value
    return result


def read_json(path):
    with Path(path).open('rb') as stream:
        raw = stream.read(LIMIT + 1)
    if not raw or len(raw) > LIMIT:
        raise ValueError('JSON input must be nonempty and at most 1 MiB')
    return json.loads(raw.decode('utf-8'), object_pairs_hook=_pairs,
                      parse_constant=lambda token: (_ for _ in ()).throw(ValueError('Invalid JSON number: ' + token)))


def _module(family):
    if family == 'environment':
        from . import iope_environment as module
        return module, module.IopeEnvironment
    if family == 'output':
        from . import iope_output_settings as module
        return module, module.IopeOutputSettings
    if family == 'logic':
        from . import iope_logic as module
        return module, module.IopeLogic
    if family == 'join-recovery':
        from . import iope_join_recovery as module
        return module, module.IopeJoinRecovery
    if family == 'block-timer':
        from . import iope_block_timer as module
        return module, module.IopeBlockTimer
    if family == 'join-groups':
        from . import iope_join_groups as module
        return module, module.IopeJoinGroups
    if family == 'scene-selectors':
        from . import iope_scene_selectors as module
        return module, module.IopeSceneSelectors
    if family == 'scene-levels':
        from . import iope_scene_levels as module
        return module, module.IopeSceneLevels
    raise ValueError('Unsupported IOPE workflow')


def _identity(document):
    from .iope_settings import PROFILES, profile_refusal
    if type(document) is not dict:
        raise ValueError('Expected an IOPE identity document')
    identity = tuple(document.get(key) for key in ('unit_type', 'firmware', 'catalog_number'))
    reason = profile_refusal(*identity[:2])
    if reason:
        raise ValueError(reason)
    if identity[2] != PROFILES[identity[0]].catalog_number:
        raise ValueError('Catalogue number must match the exact IOPE unit type')
    return identity


def _editor(args, identity):
    from .unitspec import UnitSpecStore
    if args.spec_dir is None:
        raise ValueError('Use --spec-dir or CBUS_UNITSPEC_DIR for decoded specifications')
    module, cls = _module(args.family)
    return module, cls(UnitSpecStore(args.spec_dir).load(identity[0] + '.xml'), identity[0])


def _edits(document):
    if type(document) is not dict or not document:
        raise ValueError('Edits must be a nonempty JSON object')
    result = dict(document)
    for field in ('channels', 'logic_groups'):
        if field not in result:
            continue
        if type(result[field]) is not dict:
            raise ValueError(field + ' must be an object keyed by number')
        numbered = {}
        for key, value in result[field].items():
            if not re.fullmatch(r'[1-4]', key):
                raise ValueError(field + ' keys must be canonical integers 1..4')
            numbered[int(key)] = value
        result[field] = numbered
    return result


def _add_options(parser):
    parser.add_argument('--spec-dir', type=Path, default=os.environ.get('CBUS_UNITSPEC_DIR'))
    families = parser.add_subparsers(dest='family', required=True)
    for family in ('environment', 'output', 'logic', 'join-recovery', 'block-timer', 'join-groups', 'scene-selectors', 'scene-levels'):
        actions = families.add_parser(family).add_subparsers(dest='action', required=True)
        for action in ('show', 'plan'):
            command = actions.add_parser(action)
            command.add_argument('snapshot', type=Path, help='cbus-cli-parameters-v1 export with exact identity')
            if action == 'plan':
                command.add_argument('--edits', type=Path, required=True, help='Editor options as a JSON object')
        command = actions.add_parser('database', help='Closed database unit only; apply one saved plan or read')
        command.add_argument('--host', required=True)
        command.add_argument('--port', type=int, required=True)
        command.add_argument('--timeout', type=float, default=30)
        command.add_argument('--source', required=True, help='/db//PROJECT/network/p/unit')
        command.add_argument('--lock-address', required=True, help='Exact //PROJECT/network for source')
        choice = command.add_mutually_exclusive_group(required=True)
        choice.add_argument('--show', action='store_true')
        choice.add_argument('--export', action='store_true')
        choice.add_argument('--plan', type=Path)
        command.add_argument('--dry-run', action='store_true', help='Verify plan/readback, discard staged session')
        command.add_argument('--exclusive-project', action='store_true',
                             help='Assert exclusive ownership of project editing and reloading')


def options(commands):
    _add_options(commands.add_parser('iope-workflow', help='Bounded IOPE Environment, output, join, timer, scene selector and scene level workflows'))


def parser():
    result = argparse.ArgumentParser(prog='python -m cbus_toolkit.iope_workflow_cli')
    _add_options(result)
    return result


def _source(args):
    match = re.fullmatch(r'/db//([A-Za-z0-9_]{1,8})/(0|[1-9][0-9]{0,2})/p/(0|[1-9][0-9]{0,2})', args.source)
    if not match or any(int(match[i]) > 255 for i in (2, 3)):
        raise ValueError('Source must be a canonical /db//PROJECT/network/p/unit database address')
    project, network = match[1], '//' + match[1] + '/' + match[2]
    if args.lock_address != network:
        raise ValueError('Lock address must exactly match the source network ' + network)
    if args.plan and not args.exclusive_project:
        raise ValueError('Applying or staging a plan requires --exclusive-project')
    if args.dry_run and not args.plan:
        raise ValueError('--dry-run requires --plan')
    return project, network


def _project_document(client, project):
    from .native import NativeDatabase
    reply = NativeDatabase(client).get('//' + project, xml=True)
    if reply.code != 344:
        raise ValueError('Expected native project XML')
    from .programming import xml_text
    raw = xml_text(reply)
    if '<!DOCTYPE' in raw.upper() or '<!ENTITY' in raw.upper():
        raise ValueError('Project XML declarations are unsupported')
    root = ET.fromstring(raw)
    projects = root.findall('Project') if root.tag == 'Installation' else []
    if len(projects) != 1 or projects[0].findtext('Address') != project:
        raise ValueError('Expected exactly the selected native project')
    return projects[0]


def _closed(client, project, network):
    from .addressing import NetworkAddressing
    document = _project_document(client, project)
    paths = []
    for row in document.findall('Network'):
        address = row.findtext('Address') or ''
        if not re.fullmatch(r'0|[1-9][0-9]{0,2}', address) or int(address) > 255:
            raise ValueError('Invalid database network address')
        path = '//' + project + '/' + address
        if path in paths:
            raise ValueError('Duplicate database network address')
        paths.append(path)
        runtime = dict(NetworkAddressing(client)._runtime(path))
        if any(runtime.get(key) != value for key, value in (
                ('InterfaceState', 'closed'), ('TargetInterfaceState', 'closed'), ('SyncState', 'idle'))):
            raise ValueError('Every project network must be closed with synchronization idle')
    if network not in paths:
        raise ValueError('Source network missing from project')
    return next(row for row in document.findall('Network')
                if network.endswith('/' + row.findtext('Address')))


def _check_group_cache(network, cache):
    if type(cache) is not dict or type(cache.get('applications')) is not list:
        raise ValueError('Plan requires group_cache evidence')
    actual = {}
    for app in network.findall('Application'):
        address = int(app.findtext('Address'))
        if address in actual:
            raise ValueError('Duplicate native application address')
        groups = [int(group.findtext('Address')) for group in app.findall('Group')]
        if len(groups) != len(set(groups)):
            raise ValueError('Duplicate native group address')
        actual[address] = set(groups)
    for app in cache['applications']:
        if app['address'] not in actual or not set(app['groups']) <= actual[app['address']]:
            raise ValueError('group_cache is not supported by current native database groups')
    if 'action_selectors' in cache:
        for inventory in cache['action_selectors']:
            application, group = inventory['application'], inventory['group']
            matches = [row for app in network.findall('Application')
                       if int(app.findtext('Address')) == application
                       for row in app.findall('Group')
                       if int(row.findtext('Address')) == group]
            if len(matches) != 1:
                raise ValueError('Action selector group is missing from the native database')
            addresses = [int(level.findtext('Address')) for level in matches[0].findall('Level')]
            if len(addresses) != len(set(addresses)):
                raise ValueError('Duplicate native action selector address')
            if set(addresses) != set(inventory['addresses']):
                raise ValueError('Action selector inventory differs from the complete native group levels')


def _cache(plan):
    # Positive group evidence is retained in the editor's canonical intent.
    return plan.details.get('options', {}).get('group_cache')


def database(args, client, module=None, editor=None, plan=None):
    from .programming import Programmer
    from .native import NativeProjects
    project, network = _source(args)
    evidence = {'saved': False, 'pp_save_attempted': False, 'pp_save_completed': False,
                'project_save_attempted': False, 'project_save_completed': False,
                'fresh_reload_verified': False, 'physical_hardware_verified': False}
    try:
        network_xml = _closed(client, project, network)
        if plan is not None and _cache(plan) is not None:
            _check_group_cache(network_xml, _cache(plan))
        programmer = Programmer(client)
        with programmer.load(network, args.source) as session:
            identity = _identity({'unit_type': session.unit_type, 'firmware': session.firmware,
                                  'catalog_number': session.catalog_number})
            if editor is None:
                module, editor = _editor(args, identity)
            editor.verify_profile(session)
            if args.export:
                return session.export_parameters()
            if args.show:
                return editor.show(session.values())
            before = session.values()
            result = editor.apply(session, plan)
            after = session.values()
            if {k: v for k, v in before.items() if k not in plan.changes} != {
                    k: v for k, v in after.items() if k not in plan.changes}:
                raise ValueError('Parameters outside this plan changed; session discarded')
            if args.dry_run:
                return {**result, **evidence, 'dry_run': True}
            network_xml = _closed(client, project, network)
            if _cache(plan) is not None:
                _check_group_cache(network_xml, _cache(plan))
            if not plan.changes:
                return {**result, **evidence, 'no_changes': True}
            evidence['pp_save_attempted'] = True
            session.save_to_source()
            evidence['pp_save_completed'] = True
        evidence['project_save_attempted'] = True
        reply = NativeProjects(client).operation('save', project)
        if reply.code != 200:
            raise ValueError('Project save did not return completion')
        evidence['project_save_completed'] = True
        with programmer.load(network, args.source) as reloaded:
            editor.verify_profile(reloaded)
            if reloaded.values() != after:
                raise ValueError('Fresh database reload differs from verified staged parameters')
        evidence.update(saved=True, fresh_reload_verified=True)
        return {**result, **evidence, 'unrelated_parameters_preserved': len(before) - len(plan.changes)}
    except BaseException as error:
        if evidence['pp_save_attempted']:
            evidence['outcome_uncertain'] = not evidence['fresh_reload_verified']
            evidence['automatic_retry_performed'] = False
            raise PersistenceError(error, evidence) from error
        raise


def _run(args, client_factory=None):
    if args.action != 'database':
        raw = read_json(args.snapshot)
        if type(raw) is not dict or raw.get('format') != 'cbus-cli-parameters-v1' or type(raw.get('parameters')) is not dict:
            raise ValueError('Expected cbus-cli-parameters-v1 snapshot with identity')
        identity = _identity(raw)
        _module_value, editor = _editor(args, identity)
        if args.action == 'show':
            return editor.show(raw['parameters']), 0
        edits = _edits(read_json(args.edits))
        return editor.plan(raw['parameters'], identity=identity, **edits).as_dict(), 0
    _source(args)  # Reject physical paths and unrelated locks before connecting.
    module = editor = plan = None
    if args.plan:
        raw = read_json(args.plan)
        identity = _identity(raw)
        module, editor = _editor(args, identity)
        plan = module.plan_from_dict(raw)
        canonical = editor.plan(plan.expected, identity=identity, **_edits(raw.get('options')))
        if json.dumps(canonical.as_dict(), sort_keys=True) != json.dumps(plan.as_dict(), sort_keys=True):
            raise ValueError('Saved plan differs from canonical controls and dependent writes')
    elif args.spec_dir is None:
        raise ValueError('Use --spec-dir or CBUS_UNITSPEC_DIR for decoded specifications')
    if client_factory is None:
        from .cgate import CGateClient
        client_factory = CGateClient
    with client_factory(args.host, args.port, timeout=args.timeout) as client:
        return database(args, client, module, editor, plan), 0


def run(args, client_factory=None):
    # Preserve the shared CLI's ordinary JSON error contract for invalid input.
    try:
        return _run(args, client_factory)
    except (TypeError, KeyError, ET.ParseError) as error:
        raise ValueError(str(error)) from error


def main(argv=None):
    try:
        result, status = run(parser().parse_args(argv))
    except (ValueError, OSError, RuntimeError, TypeError, KeyError, ET.ParseError) as error:
        result = {'error': str(error), **getattr(error, 'evidence', {})}
        status = 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return status


if __name__ == '__main__':
    sys.exit(main())
