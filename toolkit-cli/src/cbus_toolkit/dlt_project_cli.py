"""Offline ``dlt text`` command adapter; no C-Gate or device operations."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat

from .dlt_project_labels import (MAX_XML_BYTES, apply_project_labels,
                                 plan_project_labels, show_project_labels)

# before/after inventories and target XML repeat source text; JSON escaping can
# expand each character. Keep a separate bounded size for saved plans.
MAX_PLAN_BYTES = 16 * MAX_XML_BYTES


def _edit(text):
    match = re.fullmatch(r'(0|[1-9][0-9]{0,2}):([1-4])=(.*)', text, flags=re.DOTALL)
    if match is None:
        raise ValueError('--edit uses LANGUAGE:VARIANT=TEXT, for example 1:2=Kitchen')
    return {'language_id': int(match[1]), 'variant': int(match[2]), 'text': match[3]}


def options(ops):
    text = ops.add_parser('text', help='Inspect and edit saved project classic DLT TEXT variants offline')
    sub = text.add_subparsers(dest='text_action', required=True)
    for action in ('show', 'plan', 'apply'):
        parser = sub.add_parser(action)
        parser.add_argument('--project-xml', type=Path, required=True,
                            help='Native DBGETXML Installation or Project document')
        if action != 'apply':
            parser.add_argument('--target', required=True,
                                help='//PROJECT/network/application/group[/action]')
        if action == 'plan':
            parser.add_argument('--edit', action='append', type=_edit, required=True,
                                metavar='LANGUAGE:VARIANT=TEXT', help='Repeat for each text variant; empty text keeps a blank TEXT record')
        if action == 'apply':
            parser.add_argument('--plan', type=Path, required=True, help='Saved text plan JSON')
            parser.add_argument('--output', type=Path, required=True, help='New XML file; existing files are refused')


def _read(path, limit):
    if not stat.S_ISREG(os.lstat(path).st_mode):
        raise ValueError('DLT text input must be a regular file, not a symlink or special file')
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_BINARY', 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, 'rb') as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise ValueError('DLT text input must be a regular file')
        value = handle.read(limit + 1)
    if len(value) > limit:
        raise ValueError('DLT text input exceeds the workflow size limit')
    return value.decode('utf-8')


def offline(args):
    text = _read(args.project_xml, MAX_XML_BYTES)
    if args.text_action == 'show':
        return show_project_labels(text, args.target), 0
    if args.text_action == 'plan':
        return plan_project_labels(text, args.target, args.edit).as_dict(), 0
    plan = json.loads(_read(args.plan, MAX_PLAN_BYTES))
    candidate = apply_project_labels(text, plan)
    # Exclusive creation prevents an input/backup from being overwritten.
    with args.output.open('x', encoding='utf-8', newline='') as handle:
        handle.write(candidate)
    return {'format': 'cbus-classic-dlt-project-text-result-v1', 'output': str(args.output),
            'candidate_sha256': plan['candidate_sha256'], 'changed': plan['changed'],
            'file_saved': True, 'database_saved': False,
            'labels_transferred': False, 'device_verified': False}, 0
