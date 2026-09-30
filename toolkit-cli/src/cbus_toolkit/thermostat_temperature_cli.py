"""Offline thermostat integer conversions with an explicit unit preference."""
import argparse
from pathlib import Path
import re

from .thermostat_temperature import METHODS, convert_temperature


def _integer(text):
    if type(text) is not str or len(text) > 11 or not re.fullmatch(r'-?[0-9]{1,10}', text):
        raise argparse.ArgumentTypeError('Expected a signed 32-bit decimal integer')
    value = int(text)
    if not -(1 << 31) <= value < (1 << 31):
        raise argparse.ArgumentTypeError('Expected a signed 32-bit decimal integer')
    return value


def options(commands):
    parser = commands.add_parser('thermostat-temperature', help='Original thermostat scalar temperature conversions')
    actions = parser.add_subparsers(dest='action', required=True)
    actions.add_parser('methods', help='List the fourteen original conversion names')
    convert = actions.add_parser('convert', help='Convert one integer with an explicit unit preference')
    convert.add_argument('method', choices=METHODS)
    convert.add_argument('value', type=_integer)
    units = convert.add_mutually_exclusive_group(required=True)
    units.add_argument('--units', choices=('celsius', 'fahrenheit'))
    units.add_argument('--preferences', type=Path, metavar='STATE.json',
                       help='Select units from a retained Toolkit preference state (TemperatureUnit low byte)')


def run(args):
    if args.area != 'thermostat-temperature':
        raise ValueError('Unsupported thermostat temperature command')
    scope = 'Original scalar arithmetic only; no thermostat form, scheduling or device operation'
    if args.action == 'methods':
        return {'methods': list(METHODS), 'input_domain': 'signed 32-bit integer',
                'units': ['celsius', 'fahrenheit'], 'scope': scope}, 0
    if args.action != 'convert':
        raise ValueError('Unsupported thermostat temperature action')
    units, source = args.units, 'argument'
    if units is None:
        from .toolkit_preferences_effects import read_values, temperature_units
        values = read_values(args.preferences)
        units, source = temperature_units(values), {'preference': 'TemperatureUnit',
                                                     'value': values['TemperatureUnit'], 'rule': 'low byte non-zero selects fahrenheit'}
    value = convert_temperature(args.method, args.value, units=units)
    return {'method': args.method, 'input': args.value, 'units': units, 'units_source': source,
            'result': value, 'scope': scope}, 0
