"""CLI boundary for independent offline SESU metadata-stage diagnostics."""
from pathlib import Path
import hashlib
import os
import stat

from .toolkit_update_metadata import (MAX_CERTIFICATE_BYTES, MAX_NODE_BYTES,
    ToolkitUpdateMetadataStages, select_node, validate_context, validate_node_id)


def options(commands):
    command = commands.add_parser('update-metadata-stages',
        help='Evaluate offline metadata stages for a supplied untrusted certificate; no publisher trust or update availability claim')
    command.add_argument('file', type=Path, help='Complete node JSON, or raw catalogue response with --node-id')
    command.add_argument('--certificate', type=Path, required=True, help='Exact DER bytes of the untrusted supplied certificate')
    command.add_argument('--at-utc', required=True, help='Explicit evaluation instant YYYY-MM-DDTHH:MM:SS[.fffffff]Z')
    command.add_argument('--node-id', help='Select one unique node from a complete raw catalogue response')
    command.add_argument('--culture', default='invariant', choices=('invariant',))
    command.add_argument('--timezone', default='UTC', choices=('UTC',))


def _read(path, limit):
    # Reject pipes/devices/symlinks before opening. The descriptor check and
    # nonblocking/no-follow flags also protect the ordinary Unix replacement race.
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= limit:
        raise ValueError(path.name + ' must be a nonempty regular file within its byte bound')
    flags = os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_CLOEXEC', 0)
    descriptor = os.open(path, flags)
    first = None
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError('Input descriptor is not a regular file')
        chunks = []
        retained = 0
        while retained <= limit:
            chunk = os.read(descriptor, min(65536, limit + 1 - retained))
            if not chunk:
                break
            chunks.append(chunk)
            retained += len(chunk)
        data = b''.join(chunks)
        if not data or len(data) > limit:
            raise ValueError(path.name + ' is empty or exceeds its supported byte bound')
        return data
    except BaseException as error:
        first = error
        raise
    finally:
        try:
            os.close(descriptor)
        except BaseException:
            if first is None:
                raise


def run(args):
    args._update_metadata_editor = None
    args._update_metadata_source = None
    if args.area != 'update-metadata-stages':
        raise ValueError('Unsupported metadata-stage command')
    validate_context(args.at_utc, culture=args.culture, timezone=args.timezone)
    if args.node_id is not None:
        validate_node_id(args.node_id)
    original = _read(args.file, MAX_NODE_BYTES)
    node = original if args.node_id is None else select_node(original, node_id=args.node_id)
    certificate = _read(args.certificate, MAX_CERTIFICATE_BYTES)
    source = {'file_sha256': hashlib.sha256(original).hexdigest(),
        'selection': 'complete-node-file' if args.node_id is None else 'unique-node-from-raw-catalogue-response',
        'selected_node_id': args.node_id,
        'selected_node_representation': 'original-input-bytes' if args.node_id is None else 'normalized UTF-8 JSON; not an original byte slice',
        'selected_node_sha256': hashlib.sha256(node).hexdigest()}
    args._update_metadata_source = source
    editor = ToolkitUpdateMetadataStages()
    args._update_metadata_editor = editor
    report = editor.evaluate(node, certificate_der=certificate, at_utc=args.at_utc,
                             culture=args.culture, timezone=args.timezone)
    value = report.as_dict()
    value['source'] = dict(source)
    statuses = {row['status'] for row in value['stages']}
    # These codes describe only the six supported diagnostics, never trust.
    return value, 1 if 'failed' in statuses else 0 if statuses == {'passed'} else 2


def error_payload(error, args):
    matched = False
    try:
        if getattr(args, 'area', None) != 'update-metadata-stages':
            return {}
        editor = getattr(args, '_update_metadata_editor', None)
        if editor is None or editor.last_report is None or editor.last_report.cause is not error:
            return {}
        matched = True
        try:
            value = editor.last_report.as_dict()
        except BaseException:
            value = {'scope': 'Partial offline metadata-stage evidence', 'evidence_export_failed': True,
                     'original_error_retained': True, 'publisher_trust_evaluated': False}
        source = getattr(args, '_update_metadata_source', None)
        if type(source) is dict:
            value['source'] = dict(source)
        return {'toolkit_update_metadata_evidence': value}
    except BaseException:
        # Error reporting must not replace the exception already handled by main.
        return {'toolkit_update_metadata_evidence': {'evidence_export_failed': True,
                'original_error_retained': True, 'publisher_trust_evaluated': False}} if matched else {}
