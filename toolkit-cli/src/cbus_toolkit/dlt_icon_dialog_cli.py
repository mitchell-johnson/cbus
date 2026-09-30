"""Offline classic DLT predefined ICON dialog workflow; no native I/O."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from .dlt_project_cli import MAX_PLAN_BYTES, MAX_XML_BYTES, _read


def options(ops):
    dialog = ops.add_parser('icon-dialog', help='Inspect or plan the classic DLT predefined ICON dialog workflow')
    actions = dialog.add_subparsers(dest='icon_dialog_action', required=True)
    for action in ('show', 'plan', 'apply'):
        parser = actions.add_parser(action)
        parser.add_argument('--project-xml', type=Path, required=True,
                            help='Native DBGETXML Installation or Project document')
        if action in ('show', 'plan'):
            parser.add_argument('--target', required=True, help='//PROJECT/network/application/group[/action]')
            parser.add_argument('--language', type=int, required=True,
                                help='Exact selected language ID; predefined ICON dialog requires 202')
        if action == 'plan':
            parser.add_argument('--variant', type=int, choices=range(1, 5), required=True)
            parser.add_argument('--icon', type=int, required=True, help='Built-in icon ID in 1..91; stores the ID, not a list index')
        elif action == 'apply':
            parser.add_argument('--plan', type=Path, required=True, help='Saved ICON dialog plan JSON')
            parser.add_argument('--output', type=Path, required=True, help='New XML file; existing files are refused')


def _read_plan(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON key: ' + key)
            result[key] = value
        return result

    def nonfinite(value):
        raise ValueError('Non-finite JSON number: ' + value)

    def finite_float(value):
        number = float(value)
        if not math.isfinite(number):
            nonfinite(value)
        return number

    return json.loads(_read(path, MAX_PLAN_BYTES), object_pairs_hook=unique,
                      parse_constant=nonfinite, parse_float=finite_float)


def offline(args):
    from .dlt_icon_dialog import apply_icon_dialog, plan_icon_dialog, show_icon_dialog

    source = _read(args.project_xml, MAX_XML_BYTES)
    if args.icon_dialog_action == 'show':
        return show_icon_dialog(source, args.target, args.language), 0
    if args.icon_dialog_action == 'plan':
        return plan_icon_dialog(source, args.target, args.language, args.variant, args.icon).as_dict(), 0
    candidate = apply_icon_dialog(source, _read_plan(args.plan))
    # Derive and validate the complete candidate before creating an output file.
    with args.output.open('x', encoding='utf-8', newline='') as handle:
        handle.write(candidate)
    return {'format': 'cbus-classic-dlt-icon-dialog-result-v1', 'output': str(args.output),
            'candidate_sha256': hashlib.sha256(candidate.encode('utf-8')).hexdigest(),
            'file_saved': True, 'database_saved': False,
            'labels_transferred': False, 'device_verified': False}, 0
