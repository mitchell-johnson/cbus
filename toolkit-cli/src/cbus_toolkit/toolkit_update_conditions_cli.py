"""CLI for a pure, explicitly supplied-context condition calculation."""
from pathlib import Path
import hashlib
import json

from .toolkit_update_conditions import MAX_JSON_BYTES, ToolkitUpdateConditions, ConditionStageReport
from .toolkit_update_metadata_cli import _read


def options(commands):
    command = commands.add_parser('update-condition-stages',
        help='Evaluate bounded original update conditions using supplied file facts; no live applicability query')
    command.add_argument('file', type=Path, help='Original ClientConditionData JSON (maximum128KiB)')
    command.add_argument('--context', type=Path, required=True,
        help='cbus-toolkit-condition-context-v1 JSON with explicit unverified file facts')


def run(args):
    args._update_conditions_editor = None
    args._update_conditions_source = None
    args._update_conditions_error = None
    args._update_conditions_report = None
    if args.area != 'update-condition-stages':
        raise ValueError('Unsupported conditions-stage command')
    conditions = _read(args.file, MAX_JSON_BYTES)
    context = _read(args.context, MAX_JSON_BYTES)
    source = {'conditions_file_sha256': hashlib.sha256(conditions).hexdigest(),
              'context_file_sha256': hashlib.sha256(context).hexdigest(),
              'representation': 'Exact supplied file bytes; normalized model reported separately'}
    args._update_conditions_source = source
    editor = ToolkitUpdateConditions(); args._update_conditions_editor = editor
    try:
        report = editor.evaluate(conditions, context=context)
        args._update_conditions_report = report
        value = report.as_dict(); value['source'] = dict(source)
        return value, 0 if report.computed else 1
    except BaseException as error:
        args._update_conditions_error = error
        raise


def error_payload(error, args):
    matched = False
    try:
        if getattr(args, 'area', None) != 'update-condition-stages':
            return {}
        editor = getattr(args, '_update_conditions_editor', None)
        if editor is None or editor.last_report is None:
            return {}
        report = editor.last_report
        if report.cause is not error and getattr(args, '_update_conditions_error', None) is not error:
            return {}
        matched = True
        try:
            value = report.as_dict()
        except BaseException:
            # The report's immutable encoded document is a second, independent
            # export path. Its scalar result also survives a decoder failure.
            try:
                value = json.loads(report._document) if type(report) is ConditionStageReport else None
                if type(value) is not dict:
                    raise ValueError('Invalid retained report')
                value.update(evidence_export_failed=True, original_error_retained=True)
            except BaseException:
                result = report.result if type(report) is ConditionStageReport else None
                value = {'scope': 'Partial supplied-context condition evidence', 'evidence_export_failed': True,
                         'original_error_retained': True, 'condition_result_under_supplied_context': result,
                         'calculation_completed_before_export_failure': type(result) is bool,
                         'package_applicability_evaluated': False, 'updates_available': None}
        source = getattr(args, '_update_conditions_source', None)
        if type(source) is dict:
            value['source'] = dict(source)
        return {'toolkit_update_conditions_evidence': value}
    except BaseException:
        return {'toolkit_update_conditions_evidence': {'evidence_export_failed': True,
                'original_error_retained': True, 'package_applicability_evaluated': False,
                'updates_available': None}} if matched else {}
