"""CLI boundary for independent offline SESU revocation-stage diagnostics."""
from pathlib import Path
import hashlib

from .toolkit_update_revocation import (MAX_CERTIFICATE_BYTES, MAX_NODE_BYTES,
    ToolkitUpdateRevocationStages, select_revocation_data, validate_context)


def options(commands):
    command = commands.add_parser('update-revocation-stages',
        help='Evaluate offline revocation stages for a supplied untrusted certificate; no publisher trust or update availability claim')
    command.add_argument('file', type=Path, help='Complete revocation data JSON, or raw API response with --response')
    command.add_argument('--signer-certificate', type=Path, required=True, help='Exact DER bytes of the untrusted supplied certificate')
    command.add_argument('--at-utc', required=True, help='Explicit evaluation instant YYYY-MM-DDTHH:MM:SS[.fffffff]Z')
    command.add_argument('--response', action='store_true', help='Select normalized data from a successful raw API response')
    command.add_argument('--culture', default='invariant', choices=('invariant',))
    command.add_argument('--timezone', default='UTC', choices=('UTC',))


# Share the accepted bounded regular-file reader and first-error cleanup rule.
from .toolkit_update_metadata_cli import _read

def run(args):
    args._update_revocation_editor = None
    args._update_revocation_source = None
    if args.area != 'update-revocation-stages':
        raise ValueError('Unsupported revocation-stage command')
    validate_context(args.at_utc, culture=args.culture, timezone=args.timezone)
    original = _read(args.file, MAX_NODE_BYTES)
    node = select_revocation_data(original) if args.response else original
    certificate = _read(args.signer_certificate, MAX_CERTIFICATE_BYTES)
    source = {'file_sha256': hashlib.sha256(original).hexdigest(),
        'selection': 'normalized-data-from-raw-response' if args.response else 'complete-data-file',
        'selected_data_representation': 'normalized UTF-8 JSON; not an original byte slice' if args.response else 'original-input-bytes',
        'selected_data_sha256': hashlib.sha256(node).hexdigest()}
    args._update_revocation_source = source
    editor = ToolkitUpdateRevocationStages()
    args._update_revocation_editor = editor
    report = editor.evaluate(node, signer_certificate_der=certificate, at_utc=args.at_utc,
                             culture=args.culture, timezone=args.timezone)
    value = report.as_dict()
    value['source'] = dict(source)
    statuses = {row['status'] for row in value['stages']}
    # These codes describe only the seven supported diagnostics, never trust.
    return value, 1 if 'failed' in statuses else 0 if statuses == {'passed'} else 2


def error_payload(error, args):
    matched = False
    try:
        if getattr(args, 'area', None) != 'update-revocation-stages':
            return {}
        editor = getattr(args, '_update_revocation_editor', None)
        if editor is None or editor.last_report is None or editor.last_report.cause is not error:
            return {}
        matched = True
        try:
            value = editor.last_report.as_dict()
        except BaseException:
            value = {'scope': 'Partial offline revocation-stage evidence', 'evidence_export_failed': True,
                     'original_error_retained': True, 'publisher_trust_evaluated': False}
        source = getattr(args, '_update_revocation_source', None)
        if type(source) is dict:
            value['source'] = dict(source)
        return {'toolkit_update_revocation_evidence': value}
    except BaseException:
        # Error reporting must not replace the exception already handled by main.
        return {'toolkit_update_revocation_evidence': {'evidence_export_failed': True,
                'original_error_retained': True, 'publisher_trust_evaluated': False}} if matched else {}
