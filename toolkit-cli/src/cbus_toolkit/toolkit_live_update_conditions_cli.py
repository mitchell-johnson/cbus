"""CLI boundary for checked Windows registry condition evaluations."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .toolkit_live_update_conditions import LiveConditionReport, ToolkitLiveUpdateConditions
from .toolkit_update_conditions import MAX_JSON_BYTES
from .toolkit_update_metadata_cli import _read
from .windows_condition_registry import (COMPILER, RegistryReadScope, WindowsConditionRegistry,
                                         validate_user_sid)


EVIDENCE = 'toolkit_live_update_conditions_evidence'


def options(commands):
    command = commands.add_parser('update-condition-live',
        help='Evaluate bounded update conditions with checked live Windows HKCU observations')
    command.add_argument('file', type=Path,
        help='Original ClientConditionData JSON (maximum 128 KiB)')
    command.add_argument('--file-context', type=Path, required=True,
        help='Explicit unverified context-v1 file facts (maximum 128 KiB)')
    command.add_argument('--registry-scope', type=Path, required=True,
        help='Exact registry read-scope-v1 JSON with one to eight unique HKCU queries')
    command.add_argument('--repeat-once', action='store_true',
        help='After a clean Boolean result, evaluate once more on the same wrapper with a fresh observer')
    command.add_argument('--expected-user-sid',
        help='Require this exact Windows user SID before any HKCU query; does not switch users')
    command.add_argument('--compiler', type=Path, default=Path(COMPILER),
        help='Captured x86 .NET Framework compiler path')
    command.add_argument('--workspace-parent', type=Path,
        help='Existing ordinary directory for retained worker artifacts')
    command.add_argument('--timeout', type=float, default=60.0,
        help='Per-observer compile/read/cleanup deadline in seconds, greater than 0 and at most 60')


def _source(conditions, context, scope):
    return {
        'conditions_file_sha256': hashlib.sha256(conditions).hexdigest(),
        'file_context_sha256': hashlib.sha256(context).hexdigest(),
        'registry_scope_sha256': hashlib.sha256(scope).hexdigest(),
        'representation': 'Exact supplied bytes; normalized model and observed requests reported separately',
    }


def run(args):
    args._live_condition_wrapper = None
    args._live_condition_observer = None
    args._live_condition_source = None
    args._live_condition_error = None
    args._live_condition_output_error = None
    args._live_condition_report = None
    args._live_condition_completed = False
    args._live_condition_first_pass = None
    args._live_condition_second_attempted = False
    args._live_condition_second_report = False
    if args.area != 'update-condition-live':
        raise ValueError('Unsupported live condition command')
    expected_user_sid = getattr(args, 'expected_user_sid', None)
    if expected_user_sid is not None:
        validate_user_sid(expected_user_sid)
    conditions = _read(args.file, MAX_JSON_BYTES)
    context = _read(args.file_context, MAX_JSON_BYTES)
    scope_bytes = _read(args.registry_scope, MAX_JSON_BYTES)
    source = _source(conditions, context, scope_bytes)
    args._live_condition_source = source
    scope = RegistryReadScope.from_json(scope_bytes)
    def fresh_observer():
        return WindowsConditionRegistry(compiler_path=args.compiler, scope=scope,
            workspace_parent=args.workspace_parent, timeout=args.timeout,
            expected_user_sid=expected_user_sid)

    observer = fresh_observer()
    args._live_condition_observer = observer
    wrapper = ToolkitLiveUpdateConditions(observer)
    args._live_condition_wrapper = wrapper
    try:
        report = wrapper.evaluate(conditions, file_context=context)
        args._live_condition_report = report
        value = report.as_dict()
        if args.repeat_once:
            # The incomplete-first path uses this same value as its top-level
            # result. Detach before adding repeat metadata so a later output
            # failure cannot nest a prior composite receipt inside itself.
            args._live_condition_first_pass = dict(value)
            if report.computed:
                # Each Windows observer owns exactly one worker and its cleanup.
                # The wrapper preserves its original first report and starts a
                # fresh condition-name cache for the second public evaluation.
                next_observer = fresh_observer()
                args._live_condition_observer = next_observer
                args._live_condition_second_attempted = True
                report = wrapper.evaluate_next(conditions, file_context=context,
                                               observer=next_observer)
                args._live_condition_report = report
                args._live_condition_second_report = True
                value = report.as_dict()
            value = _repeat_payload(value, args)
        value['source'] = dict(source)
        args._live_condition_completed = True
        return value, 0 if report.computed else 1
    except BaseException as error:
        args._live_condition_error = error
        if wrapper.last_report is not None and wrapper.last_report is not args._live_condition_report:
            args._live_condition_report = wrapper.last_report
            if args._live_condition_second_attempted:
                args._live_condition_second_report = True
        raise


def _repeat_payload(value, args):
    """Keep detached ordered pass receipts without a self-reference."""
    first = getattr(args, '_live_condition_first_pass', None)
    passes = [dict(first)] if type(first) is dict else []
    if not passes or getattr(args, '_live_condition_second_report', False):
        passes.append(dict(value))
    value['repeated_evaluation'] = True
    value['evaluation_passes'] = passes
    value['second_evaluation_attempted'] = bool(args._live_condition_second_attempted)
    return value


def record_output_error(args, error):
    """Associate an immediate JSON-output failure with this completed command."""
    try:
        if (args.area == 'update-condition-live' and args._live_condition_completed is True
                and args._live_condition_error is None and args._live_condition_output_error is None):
            args._live_condition_output_error = error
    except BaseException:
        pass


def _decode_report(report):
    try:
        value = report.as_dict()
        if type(value) is not dict:
            raise ValueError('Live condition report must be an object')
        return value
    except BaseException:
        try:
            value = json.loads(report._document) if type(report) is LiveConditionReport else None
            if type(value) is not dict:
                raise ValueError('Invalid retained live condition report')
            value.update(evidence_export_failed=True, original_error_retained=True)
            return value
        except BaseException:
            result = report.result if type(report) is LiveConditionReport else None
            return {'profile': 'toolkit-1.18-sesu-3.0.7-lazy-registry-observations-v1',
                    'evidence_export_failed': True, 'original_error_retained': True,
                    'condition_result': result, 'evaluation_completed': type(result) is bool,
                    'package_applicability_evaluated': False,
                    'publisher_trust_evaluated': False, 'updates_available': None}


def error_payload(error, args):
    matched = False
    try:
        if getattr(args, 'area', None) != 'update-condition-live':
            return {}
        report = getattr(args, '_live_condition_report', None)
        if report is None:
            return {}
        if (getattr(args, '_live_condition_error', None) is not error
                and getattr(args, '_live_condition_output_error', None) is not error
                and report.cause is not error):
            return {}
        matched = True
        value = _decode_report(report)
        if getattr(args, 'repeat_once', False):
            value = _repeat_payload(value, args)
        source = getattr(args, '_live_condition_source', None)
        if type(source) is dict:
            value['source'] = dict(source)
        observer = getattr(args, '_live_condition_observer', None)
        if observer is not None and observer.last_report is not None:
            try:
                value.setdefault('observer_evidence', observer.last_report.as_dict())
            except BaseException:
                value['observer_evidence_export_failed'] = True
        return {EVIDENCE: value}
    except BaseException:
        return {EVIDENCE: {'evidence_export_failed': True,
                'original_error_retained': True, 'package_applicability_evaluated': False,
                'publisher_trust_evaluated': False, 'updates_available': None}} if matched else {}
