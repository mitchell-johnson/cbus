"""`cbus-toolkit thermostat template list|preview|apply`."""
from __future__ import annotations

import argparse
import json

from .thermostat_settings import NativeThermostatSettings
from .thermostat_output_groups import normalize_output_operations, normalize_output_selections
from .unitspec import UnitSpecStore
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


class _OutputControl(argparse.Action):
    """Preserve order across selection shorthand and explicit dialog records."""

    def __call__(self, parser, namespace, values, option_string=None):
        history = list(getattr(namespace, self.dest, None) or ())
        history.append((option_string, values))
        setattr(namespace, self.dest, history)


def options(commands):
    parser = commands.add_parser('thermostat', help='Thermostat Load Template and settings workflows')
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
        action.add_argument('--overlay-only', action='store_true',
                            help='Skip the replay of the original post-load model adjustments')
        action.add_argument('--group-sort', choices=('address-ascending',),
                            help='Declare original group sort context; requires an initially empty '
                                 'output application and post-load replay')
        if name == 'apply':
            action.add_argument('--backup-project', help='New backup project name')
    settings = areas.add_parser('settings', help='Thermostat settings and remote references')
    edits = settings.add_subparsers(dest='action', required=True)
    for name, text in (('preview', 'Validate settings edits against the unit and the original form save'),
                       ('apply', 'Apply settings and references with backup and reload readback')):
        action = edits.add_parser(name, help=text)
        action.add_argument('unit', help='Existing database thermostat: //PROJECT/network/p/unit')
        action.add_argument('--set', dest='edits', action='append', default=[], metavar='NAME=VALUE',
                            help='Raw setting before one projected load/save; omit to normalize current settings')
        action.add_argument('--temperature-preference', choices=('celsius', 'fahrenheit'),
                            help='Original Toolkit process preference for temperature load/save '
                                 'normalization; separate from the thermostat TemperatureUnits setting')
        action.add_argument('--setback-levels', choices=('accept', 'decline'), default='decline',
                            help='Accept or decline adding missing remote setback levels (default decline)')
        action.add_argument('--schedule-levels', choices=('accept', 'decline'), default='decline',
                            help='Accept or decline adding missing remote schedule levels (default decline)')
        action.add_argument('--output-group', dest='output_history', action=_OutputControl,
                            metavar='PARAMETER=ADDRESS',
                            help='Select an existing output group after model loading; repeat in control order')
        action.add_argument('--output-operation', dest='output_history', action=_OutputControl, metavar='JSON',
                            help='Ordered select-output-group, accepted/cancelled add-output-group/edit-output-group, '
                                 'or caller-explicit damper callback JSON record; may be interleaved with --output-group')
        action.add_argument('--resolve-output-groups', action='store_true',
                            help='Resolve current output groups and automatic names during model loading')
        action.add_argument('--host', required=True)
        action.add_argument('--port', type=_port, default=20023)
        action.add_argument('--timeout', type=float, default=30.0)
        action.add_argument('--exclusive-project', action='store_true',
                            help='Declare exclusive editing/reloading of the closed project; required')
        if name == 'apply':
            action.add_argument('--backup-project', help='New backup project name')
    for action in (listing, *[actions.choices[n] for n in ('preview', 'apply')],
                   *[edits.choices[n] for n in ('preview', 'apply')]):
        action.add_argument('--spec-dir', default=default_spec_dir(),
                            help='Decoded unit specifications (default CBUS_UNITSPEC_DIR)')


def _edits(items):
    result = {}
    for item in items:
        name, separator, value = item.partition('=')
        if not separator or not name or name in result:
            raise ValueError('Use distinct --set NAME=VALUE edits')
        result[name] = value
    return result


def _output_controls(history, resolve):
    def object_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate --output-operation JSON key: ' + key)
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError('Invalid --output-operation JSON constant: ' + value)

    history = history or ()
    explicit = any(option == '--output-operation' for option, _value in history)
    records = []
    for option, value in history:
        if option == '--output-group':
            parameter, separator, address = value.partition('=')
            if not separator or not parameter or not address:
                raise ValueError('Use --output-group PARAMETER=ADDRESS selections')
            record = {'parameter': parameter, 'address': address}
            if explicit:
                record['op'] = 'select-output-group'
        else:
            try:
                record = json.loads(value, object_pairs_hook=object_pairs, parse_constant=invalid_constant)
            except json.JSONDecodeError as error:
                raise ValueError('--output-operation requires a JSON object: ' + str(error)) from error
            if type(record) is not dict:
                raise ValueError('--output-operation requires a JSON object')
        records.append(record)
    if explicit:
        return None, records
    return (records if history or resolve else None), None


def _settings(args, client_factory):
    if args.exclusive_project is not True:
        raise ValueError('Thermostat settings preview/apply requires --exclusive-project')
    if args.spec_dir is None:
        raise ValueError('Use --spec-dir or CBUS_UNITSPEC_DIR for decoded vendor specifications')
    edits = _edits(args.edits)
    output_selections, output_operations = _output_controls(args.output_history, args.resolve_output_groups)
    # Validate only record schema here; current model/reference choices are
    # resolved by the same native settings owner after its readonly inventory.
    # Normalization is not permission to invent a host binding callback.
    normalize_output_selections(output_selections)
    normalize_output_operations(output_operations)
    scope = ('Thermostat settings, remote references and optional ordered output controls checked against the unit specification, '
             'complete project graph and recovered form-save fields in one transaction; '
             'complete dialog lifecycle remains unreproduced and no physical thermostat is programmed')
    with client_factory(args.host, args.port, timeout=args.timeout) as client:
        manager = NativeThermostatSettings(client, UnitSpecStore(args.spec_dir))
        plan = manager.plan(args.unit, edits, exclusive_project=True,
                            temperature_preference=args.temperature_preference,
                            level_prompts={'setback': args.setback_levels, 'schedule': args.schedule_levels},
                            output_selections=output_selections, output_operations=output_operations)
        if args.action == 'preview':
            return {**plan.as_dict(), 'scope': scope}, 0
        result = manager.apply(plan, backup_project=args.backup_project)
        return {**result, 'plan': plan.as_dict(), 'scope': scope}, 0


def run(args, client_factory):
    if args.area == 'thermostat' and args.thermostat_area == 'settings':
        return _settings(args, client_factory)
    if args.area != 'thermostat' or args.thermostat_area != 'template':
        raise ValueError('Unsupported thermostat command')
    catalog = ThermostatTemplateCatalog(args.spec_dir)
    scope = ('Original Load Template PP overlay plus the replayed post-load model adjustments and form '
             'save for the fields they touch (unless --overlay-only); no physical thermostat is programmed')
    if args.action == 'list':
        family = family_for_unit_type(args.unit_type) if args.unit_type else None
        return {'templates': catalog.listing(family), 'families': {
            name: list(record['unit_types']) for name, record in FAMILIES.items()}, 'scope': scope}, 0
    if args.exclusive_project is not True:
        raise ValueError('Thermostat template preview/apply requires --exclusive-project')
    if args.overlay_only and args.group_sort is not None:
        raise ValueError('--group-sort requires post-load replay; omit --overlay-only')
    with client_factory(args.host, args.port, timeout=args.timeout) as client:
        manager = NativeThermostatTemplates(client, catalog)
        plan = manager.plan(args.unit, args.template_number, exclusive_project=True,
                            post_load=not args.overlay_only, group_sort=args.group_sort)
        if args.action == 'preview':
            return {**plan.as_dict(), 'scope': scope}, 0
        result = manager.apply(plan, backup_project=args.backup_project)
        return {**result, 'plan': plan.as_dict(), 'scope': scope}, 0
