"""Local file commands for eDLT templates; parent-form application is refused.

Run ``python -m cbus_toolkit.edlt_templates_cli --help`` directly, or register
``options`` and ``run`` with the central CLI. No command opens a C-Gate session.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import sys

from .edlt_templates import (
    EdltTemplate, EdltTemplateApplyRefused, EdltTemplateError,
    export_edlt_template, preview_edlt_template,
)


MAX_INPUT_BYTES = 8 * 1024 * 1024
EXPORT_FIELDS = frozenset((
    'description', 'firmware', 'unit_name', 'primary_application',
    'secondary_application', 'pp_attributes',
))


def _actions(parser):
    actions = parser.add_subparsers(dest='action', required=True)
    inspect = actions.add_parser('inspect', help='Validate template XML and its ordered CRC')
    inspect.add_argument('file', type=Path, help='Local eDLT template XML')
    export = actions.add_parser('export', help='Export explicit local JSON to a new XML file')
    export.add_argument('file', type=Path, help='JSON with the six exact export arguments and ordered PP pairs')
    export.add_argument('--output', type=Path, required=True,
                        help='New XML file; an existing file is never overwritten')
    preview = actions.add_parser('preview', help='Stage and validate a local template without applying it')
    preview.add_argument('file', type=Path, help='Local eDLT template XML')
    preview.add_argument('--pp-attribute-names', type=Path, required=True,
                         help='JSON array of target PP attribute names in their original order')
    preview.add_argument('--spec-dir', type=Path,
                         help='Optional explicit directory containing decoded KEYGL5.xml')
    preview.add_argument('--firmware', help='Optional explicit target firmware for validation')
    apply = actions.add_parser('apply', help='Refuse unproved parent-form application before any I/O')
    apply.add_argument('file', nargs='?', type=Path,
                       help='Optional template path; this command refuses before reading it')


def options(subparsers):
    """Register the root ``edlt-templates`` command with the central CLI."""
    parser = subparsers.add_parser(
        'edlt-templates', help='Inspect, export and preview local eDLT templates; apply unavailable')
    _actions(parser)
    return parser


def build_parser():
    parser = argparse.ArgumentParser(
        prog='python -m cbus_toolkit.edlt_templates_cli',
        description='Local eDLT template format and staged validation; parent-form apply unavailable.')
    parser.add_argument('--compact', action='store_true', help='Emit single-line JSON')
    parser.set_defaults(area='edlt-templates')
    _actions(parser)
    return parser


def _read_bytes(path):
    info = path.stat()
    if not stat.S_ISREG(info.st_mode):
        raise EdltTemplateError('Template inputs must be regular local files')
    if info.st_size > MAX_INPUT_BYTES:
        raise EdltTemplateError('Template input exceeds the 8 MiB size limit')
    # Check before open to avoid special files, then check the descriptor too.
    # Nonblocking open prevents a replacement FIFO from waiting for a writer.
    flags = os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_BINARY', 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise EdltTemplateError('Template inputs must be regular local files')
        if info.st_size > MAX_INPUT_BYTES:
            raise EdltTemplateError('Template input exceeds the 8 MiB size limit')
        raw = stream.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        raise EdltTemplateError('Template input exceeds the 8 MiB size limit')
    return raw


def _read_json(path):
    def unique(pairs):
        result = {}
        for name, value in pairs:
            if name in result:
                raise EdltTemplateError('Duplicate JSON key: ' + name)
            result[name] = value
        return result

    def nonfinite(value):
        raise EdltTemplateError('Non-finite JSON number: ' + value)

    try:
        return json.loads(_read_bytes(path), object_pairs_hook=unique,
                          parse_constant=nonfinite)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise EdltTemplateError('Invalid template input JSON: ' + str(exc)) from exc


def _export_arguments(path):
    arguments = _read_json(path)
    if not isinstance(arguments, dict) or set(arguments) != EXPORT_FIELDS:
        raise EdltTemplateError(
            'Export JSON must contain exactly: ' + ', '.join(sorted(EXPORT_FIELDS)))
    for name in ('description', 'firmware', 'unit_name'):
        if not isinstance(arguments[name], str):
            raise EdltTemplateError(name + ' must be a string')
    for name in ('primary_application', 'secondary_application'):
        if type(arguments[name]) is not int:
            raise EdltTemplateError(name + ' must be an integer, not a string or boolean')
    attributes = arguments['pp_attributes']
    if not isinstance(attributes, list) or any(
            not isinstance(pair, list) or len(pair) != 2
            or any(not isinstance(value, str) for value in pair)
            for pair in attributes):
        raise EdltTemplateError('pp_attributes must be an ordered array of [name, raw_string] pairs')
    return arguments


class EdltTemplateFileError(EdltTemplateError):
    """Preserve evidence if a new local export file could be incomplete."""

    def __init__(self, error, details):
        super().__init__(str(error))
        self.details = details


def _export(args):
    template = export_edlt_template(**_export_arguments(args.file))
    xml = template.to_xml()
    raw = xml.encode('utf-8') if isinstance(xml, str) else xml
    evidence = {
        'file': str(args.output), 'output_created': False,
        'output_complete': False, 'output_may_be_partial': False,
        'network_io_attempted': False, 'unit_modified': False,
    }
    try:
        with args.output.open('xb') as stream:
            evidence.update(output_created=True, output_may_be_partial=True)
            written = stream.write(raw)
            if written != len(raw):
                raise OSError('Template export did not write the complete XML')
        evidence.update(output_complete=True, output_may_be_partial=False)
    except OSError as exc:
        raise EdltTemplateFileError(exc, evidence) from exc
    return {**evidence, 'byte_count': len(raw), 'template': template.as_dict()}, 0


def run(args):
    """Return ``(JSON result, status)`` for the central or standalone CLI."""
    if args.area != 'edlt-templates':
        raise EdltTemplateError('Unsupported eDLT template command area')
    # Keep this before any source read, specification load or target access.
    if args.action == 'apply':
        raise EdltTemplateApplyRefused()
    if args.action == 'export':
        return _export(args)
    if args.action not in ('inspect', 'preview'):
        raise EdltTemplateError('Unsupported eDLT template action')
    template = EdltTemplate.from_xml(_read_bytes(args.file))
    if args.action == 'inspect':
        return template.as_dict(), 0
    names = _read_json(args.pp_attribute_names)
    if not isinstance(names, list) or any(not isinstance(name, str) for name in names):
        raise EdltTemplateError('--pp-attribute-names must contain a JSON array of strings')
    spec = None
    if args.spec_dir is not None:
        from .unitspec import UnitSpecStore
        spec = UnitSpecStore(args.spec_dir).load('KEYGL5.xml')
    result = preview_edlt_template(
        template, pp_attribute_names=names, spec=spec,
        target_firmware=args.firmware).as_dict()
    return result, int(not result['input_validated'])


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        result, status = run(args)
        print(json.dumps(result, ensure_ascii=True, indent=None if args.compact else 2))
        return status
    except (ValueError, OSError, RuntimeError) as exc:
        print(json.dumps({'error': str(exc), 'type': type(exc).__name__,
                          **getattr(exc, 'details', {})}, ensure_ascii=True), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
