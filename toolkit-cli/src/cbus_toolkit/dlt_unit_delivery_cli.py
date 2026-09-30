"""Offline classic unit-label lifecycle planning and supplied-outcome assessment."""
from __future__ import annotations

from pathlib import Path

from .dlt_broadcast_cli import _read_json


def options(ops):
    delivery = ops.add_parser(
        'unit-delivery', help='Plan classic unit-label sequencing or assess supplied outcomes offline',
        description='Model the original save and label lifecycle from explicit resolved state; no commands are executed.')
    actions = delivery.add_subparsers(dest='unit_delivery_action', required=True)
    plan = actions.add_parser('plan', help='Compile an explicit unit-label request into a lifecycle plan')
    plan.add_argument('--input', type=Path, required=True, help='Resolved unit-label request JSON')
    assess = actions.add_parser('assess', help='Assess supplied operation outcomes against the unchanged plan')
    assess.add_argument('--plan', type=Path, required=True, help='Saved unit-label lifecycle plan JSON')
    assess.add_argument('--outcomes', type=Path, required=True,
                        help='Caller-supplied returned, raised or uncertain outcomes; no C-Gate connection')


def offline(args):
    from .dlt_unit_delivery import assess_unit_delivery, compile_unit_delivery

    if args.unit_delivery_action == 'plan':
        return compile_unit_delivery(_read_json(args.input)).as_dict(), 0
    return assess_unit_delivery(_read_json(args.plan), _read_json(args.outcomes)), 0
