"""`cbus-toolkit thermostat template list|preview|apply`."""
from __future__ import annotations

import argparse

from .thermostat_templates import (FAMILIES, NativeThermostatTemplates, ThermostatTemplateCatalog,
                                   default_spec_dir, family_for_unit_type)


def _number(text):
    if text not in tuple(str(n) for n in range(1, 10)) + tuple('0' + str(n) for n in range(1, 10)):
        raise argparse.ArgumentTypeError('Template number must be 1..9')
    return int(text)


def _port(text):
    if not text.isdigit() or not 1 <= int(text) <= 65535:
        raise argparse.ArgumentTypeError('C-Gate port must be in 1..65535')
    return int(text)


def options(commands):
    parser = commands.add_parser('thermostat', help='Thermostat Load Template workflow')
    areas = parser.add_subparsers(dest='thermostat_area', required=True)
    template = areas.add_parser('template', help='Original thermostat installation templates')
    actions = template.add_subparsers(dest='action', required=True)
    listing = actions.add_parser('list', help='List the templates the original offers per thermostat class')
    listing.add_argument('--unit-type', help='Restrict to the family of PC_TSA, PC_TSA5, PC_TSB or PC_TSB5')
    for name, text in (('preview', 'Read one closed database unit and plan the template overlay'),
                       ('apply', 'Apply the overlay with backup, one PP save and reload verification')):
        action = actions.add_parser(name, help=text)
        action.add_argument('unit', help='Existing database thermostat: //PROJECT/network/p/unit')
        action.add_argument('--template', dest='template_number', type=_number, required=True)
        action.add_argument('--host', required=True)
        action.add_argument('--port', type=_port, default=20023)
        action.add_argument('--timeout', type=float, default=30.0)
        action.add_argument('--exclusive-project', action='store_true',
                            help='Declare exclusive editing/reloading of the closed project; required')
        if name == 'apply':
            action.add_argument('--backup-project', help='New backup project name')
    for action in (listing, *[actions.choices[n] for n in ('preview', 'apply')]):
        action.add_argument('--spec-dir', default=default_spec_dir(),
                            help='Decoded unit specifications (default CBUS_UNITSPEC_DIR)')


def run(args, client_factory):
    if args.area != 'thermostat' or args.thermostat_area != 'template':
        raise ValueError('Unsupported thermostat command')
    catalog = ThermostatTemplateCatalog(args.spec_dir)
    scope = ('Original Load Template PP overlay only; Toolkit object-model post-load adjustments '
             'are not replayed and no physical thermostat is programmed')
    if args.action == 'list':
        family = family_for_unit_type(args.unit_type) if args.unit_type else None
        return {'templates': catalog.listing(family), 'families': {
            name: list(record['unit_types']) for name, record in FAMILIES.items()}, 'scope': scope}, 0
    if args.exclusive_project is not True:
        raise ValueError('Thermostat template preview/apply requires --exclusive-project')
    with client_factory(args.host, args.port, timeout=args.timeout) as client:
        manager = NativeThermostatTemplates(client, catalog)
        plan = manager.plan(args.unit, args.template_number, exclusive_project=True)
        if args.action == 'preview':
            return {**plan.as_dict(), 'scope': scope}, 0
        result = manager.apply(plan, backup_project=args.backup_project)
        return {**result, 'plan': plan.as_dict(), 'scope': scope}, 0
