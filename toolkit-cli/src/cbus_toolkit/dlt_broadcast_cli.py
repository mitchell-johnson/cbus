"""Pure classic DLT broadcast planning and outcome assessment; no execution."""
from __future__ import annotations

import json
import math
from pathlib import Path

from .dlt_project_cli import _read

MAX_JSON_BYTES = 1024 * 1024  # Local request/report input bound.


def options(ops):
    broadcast = ops.add_parser('broadcast', help='Plan classic DLT label commands or assess supplied outcomes offline',
                               description='Compile command text or assess supplied outcomes; no commands are executed.')
    actions = broadcast.add_subparsers(dest='broadcast_action', required=True)
    plan = actions.add_parser('plan', help='Compile one label request into an offline report')
    plan.add_argument('--input', type=Path, required=True, help='Label request JSON')
    assess = actions.add_parser('assess', help='Assess supplied outcomes against an unchanged saved plan')
    assess.add_argument('--plan', type=Path, required=True, help='Saved broadcast plan JSON')
    assess.add_argument('--outcomes', type=Path, required=True, help='Caller-supplied outcome JSON; does not contact C-Gate')


def _read_json(path):
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

    return json.loads(_read(path, MAX_JSON_BYTES), object_pairs_hook=unique,
                      parse_constant=nonfinite, parse_float=finite_float)


def offline(args):
    from .dlt_broadcast import assess_broadcast, compile_broadcast

    if args.broadcast_action == 'plan':
        return compile_broadcast(_read_json(args.input)).as_dict(), 0
    return assess_broadcast(_read_json(args.plan), _read_json(args.outcomes)), 0
