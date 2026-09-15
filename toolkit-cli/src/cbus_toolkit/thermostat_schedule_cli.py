"""Explicit preview/apply CLI boundary for closed-project scheduling levels."""
from __future__ import annotations

import json
import math

from .native import _project
from .native_thermostat_schedule import NativeThermostatScheduleLevels, _path

EVIDENCE = 'thermostat_schedule_evidence'
ACTIONS = ('Enable', 'Disable', 'Overrd')


def options(parser):
    parser.add_argument('group', help='Existing Enable Control NetVar: //PROJECT/network/203/group')
    parser.add_argument('--action', dest='schedule_action', choices=ACTIONS, required=True)
    parser.add_argument('--exclusive-project', action='store_true',
                        help='Declare exclusive editing/reloading of the closed project; required even for preview')
    parser.add_argument('--apply', action='store_true',
                        help='Create missing levels with backup and save/reload; default only reads a preview')
    parser.add_argument('--backup-project', help='New backup project name; applies only with --apply')


def _brief(error):
    try:
        message = str(error)
    except BaseException:
        message = '<unprintable>'
    return {'type': type(error).__name__, 'message': message[:2048]}


def _dump(value):
    text = json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(',', ':'))
    if len(text) > 16 * 1024 * 1024:
        raise ValueError('Scheduling CLI evidence exceeds 16 MiB')
    return text


def _decode(text):
    return json.loads(text)


def _inputs(args):
    if args.area != 'cgate' or args.action != 'thermostat-schedule-levels':
        raise ValueError('Unsupported thermostat scheduling CLI operation')
    path, project, _network, _group = _path(args.group)
    if type(args.schedule_action) is not str or args.schedule_action not in ACTIONS:
        raise ValueError('Action must be Enable, Disable or Overrd')
    if args.exclusive_project is not True:
        raise ValueError('Thermostat scheduling requires --exclusive-project')
    if type(args.apply) is not bool:
        raise ValueError('Apply must be an explicit boolean')
    if args.backup_project is not None:
        if not args.apply:
            raise ValueError('--backup-project requires --apply')
        if type(args.backup_project) is not str:
            raise ValueError('Backup project must be a string')
        if _project(args.backup_project).upper() == project.upper():
            raise ValueError('Backup project must differ from the edited project')
    if type(args.host) is not str or not args.host:
        raise ValueError('C-Gate host is required')
    if type(args.tls) is not bool:
        raise ValueError('TLS must be an explicit boolean')
    port = (20123 if args.tls else 20023) if args.port is None else args.port
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('C-Gate port must be in 1..65535')
    if type(args.timeout) not in (int, float) or not math.isfinite(args.timeout) or args.timeout <= 0:
        raise ValueError('C-Gate timeout must be positive and finite')
    return path, port


def _capture(manager, evidence, *, preserving_error=False):
    """Read the immutable native receipt without invoking its export method."""
    if manager is None:
        return
    try:
        receipt = manager.last_result
        if receipt is not None:
            # Preserve the immutable receipt even if decoding is interrupted.
            evidence['native_result_document'] = receipt.document
            value = _decode(receipt.document)
            if type(value) is not dict:
                raise ValueError('Native scheduling evidence must be an object')
            evidence['native_result'] = value
    except BaseException as error:
        evidence['evidence_errors'].append(_brief(error))
        if not preserving_error:
            raise


def _remember(args, evidence, error):
    args._thermostat_schedule_error = error
    # Keep a small detached fallback before optional export/attachment work.
    native = evidence.get('native_result') or {}
    args._thermostat_schedule_summary = {
        'format': evidence['format'], 'complete': evidence['complete'],
        'phase': evidence['phase'], 'evidence_export_failed': True,
        'native_operation_completed': evidence['native_operation_completed'],
        **{name: native[name] for name in ('backup_created', 'backup_source_save_confirmed',
             'target_mutation_attempted', 'target_save_attempted', 'target_save_confirmed',
             'persistence_verified') if type(native.get(name)) is bool},
    }
    try:
        args._thermostat_schedule_document = _dump(evidence)
    except BaseException:
        args._thermostat_schedule_document = None
        if error is None:
            raise
    if error is not None:
        try:
            setattr(error, EVIDENCE, _decode(args._thermostat_schedule_document)
                    if args._thermostat_schedule_document is not None else dict(args._thermostat_schedule_summary))
        except BaseException:
            pass


def error_payload(error, args=None):
    """Export only this invocation's first error; ignore hostile exception getters."""
    try:
        if (args.area != 'cgate' or args.action != 'thermostat-schedule-levels'
                or args._thermostat_schedule_error is not error):
            return {}
        try:
            document = args._thermostat_schedule_document
            if document is not None:
                return {EVIDENCE: _decode(document)}
        except BaseException:
            pass
        return {EVIDENCE: dict(args._thermostat_schedule_summary)}
    except BaseException:
        return {}


def record_output_error(args, error):
    """Retain a failure while emitting this completed invocation's output.

    The CLI calls this only around its immediate final output. Existing first
    errors win; a failed/new invocation or a different command is not admitted.
    """
    try:
        if args.area != 'cgate' or args.action != 'thermostat-schedule-levels':
            return {}
        first = args._thermostat_schedule_error
        if first is not None:
            return error_payload(first, args)
        summary = args._thermostat_schedule_summary
        if type(summary) is not dict or summary.get('complete') is not True or summary.get('phase') != 'complete':
            return {}
        try:
            evidence = _decode(args._thermostat_schedule_document)
        except BaseException:
            evidence = {'format': summary['format'], 'native_operation_completed': summary['native_operation_completed'],
                        'native_result': {name: value for name, value in summary.items() if name in (
                            'backup_created', 'backup_source_save_confirmed', 'target_mutation_attempted',
                            'target_save_attempted', 'target_save_confirmed', 'persistence_verified')},
                        'evidence_export_failed': True}
        evidence.update(complete=False, phase='output', error=_brief(error))
        _remember(args, evidence, error)
        return error_payload(error, args)
    except BaseException:
        # Never replace the caller's output error with evidence bookkeeping.
        return {}


def native(args, client_factory, ssl_context):
    """Plan once, optionally apply once, and close the entered context once.

    CLI completion and native completion are separate. A failed connection exit
    cannot undo a confirmed save or replace an earlier operational exception.
    """
    args._thermostat_schedule_error = None
    args._thermostat_schedule_document = None
    args._thermostat_schedule_summary = None
    args._thermostat_schedule_cleanup_errors = ()
    evidence = {'format': 'cbus-thermostat-schedule-cli-evidence-v1', 'complete': False,
                'phase': 'cli_preflight', 'apply_requested': False,
                'connection_attempted': False, 'connection_entered': False,
                'connection_exit_attempted': False, 'connection_exit_completed': False,
                'native_operation_completed': False, 'native_result': None,
                'automatic_retries': 0, 'rollback_performed': False,
                'physical_device_programmed': False, 'cleanup_errors': [], 'evidence_errors': []}
    context = manager = result = first = None
    failure_phase = None
    entered = False
    try:
        path, port = _inputs(args)
        evidence['apply_requested'] = args.apply
        evidence['phase'] = 'connection_construct'
        context = client_factory(args.host, port, timeout=args.timeout, ssl_context=ssl_context)
        evidence.update(phase='connection_enter', connection_attempted=True)
        client = context.__enter__()
        entered = True
        evidence.update(connection_entered=True, phase='plan')
        manager = NativeThermostatScheduleLevels(client)
        plan = manager.plan(path, args.schedule_action, exclusive_project=True)
        if args.apply:
            evidence['phase'] = 'apply'
            receipt = manager.apply(plan, backup_project=args.backup_project)
        else:
            receipt = plan
        evidence['native_operation_completed'] = True
        evidence['phase'] = 'native_evidence'
        _capture(manager, evidence)
        evidence['phase'] = 'result_export'
        result = receipt.as_dict()
        if type(result) is not dict:
            raise ValueError('Native scheduling output must be a JSON object')
        result = _decode(_dump(result))
    except BaseException as error:
        first, failure_phase = error, evidence['phase']
        _capture(manager, evidence, preserving_error=True)
    finally:
        if entered:
            evidence['connection_exit_attempted'] = True
            try:
                # Ignore suppression: a stopped native operation must stay a
                # failure even if an injected context asks to suppress it.
                context.__exit__(type(first) if first is not None else None, first,
                                 BaseException.__traceback__.__get__(first) if first is not None else None)
                evidence['connection_exit_completed'] = True
                if first is not None:
                    try:
                        retained = getattr(first, 'cgate_cleanup_errors', ())
                        if type(retained) is tuple:
                            for cleanup in retained:
                                if isinstance(cleanup, BaseException):
                                    args._thermostat_schedule_cleanup_errors += (cleanup,)
                                    evidence['cleanup_errors'].append(_brief(cleanup))
                                    evidence['connection_exit_completed'] = False
                    except BaseException as export_error:
                        evidence['evidence_errors'].append(_brief(export_error))
            except BaseException as cleanup:
                args._thermostat_schedule_cleanup_errors += (cleanup,)
                evidence['cleanup_errors'].append(_brief(cleanup))
                if first is None:
                    first, failure_phase = cleanup, 'connection_cleanup'
    if first is not None:
        evidence.update(phase=failure_phase, error=_brief(first))
        _remember(args, evidence, first)
        raise first
    evidence.update(phase='complete', complete=True)
    try:
        _remember(args, evidence, None)
    except BaseException as error:
        evidence.update(phase='evidence_export', complete=False, error=_brief(error))
        _remember(args, evidence, error)
        raise
    result['cli'] = {name: evidence[name] for name in (
        'complete', 'apply_requested', 'connection_exit_completed', 'native_operation_completed',
        'automatic_retries', 'rollback_performed', 'physical_device_programmed')}
    return result, 0
