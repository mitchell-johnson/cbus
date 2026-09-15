"""Offline CLI boundaries for explicit outgoing and received CAL routing bytes."""
import argparse
import re

from .pci import decode_cal
from .pci_routing import RoutedCALCommand, inspect_received_cal_route, inspect_routed_cal_command


def _byte(text):
    if type(text) is not str or not re.fullmatch(r'(?:[0-9]{1,3}|0[xX][0-9a-fA-F]{1,2})', text):
        raise argparse.ArgumentTypeError('Expected an address byte in decimal or 0x hexadecimal notation')
    value = int(text, 0) if text.lower().startswith('0x') else int(text, 10)
    if not 0 <= value <= 255:
        raise argparse.ArgumentTypeError('Expected an address byte in 0..255')
    return value


def _hex(text, maximum, name):
    if type(text) is not str or not 0 < len(text) <= maximum * 2 or len(text) % 2 or not re.fullmatch(r'[0-9a-fA-F]+', text):
        raise argparse.ArgumentTypeError(name + ' requires bounded pairs of hexadecimal digits without whitespace')
    return bytes.fromhex(text)


def _cal(text):
    raw = _hex(text, 32, 'CAL')
    try:
        value, used = decode_cal(raw)
        if used != len(raw):
            raise ValueError('Expected exactly one supported CAL')
        return value
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def _wire(text):
    return _hex(text, 87, 'Wire command')


def options(commands):
    parser = commands.add_parser('pci-route', help='Encode or inspect CAL routing bytes offline')
    operations = parser.add_subparsers(dest='action', required=True)
    encode = operations.add_parser('encode', help='Construct one command from explicit routing bytes without sending it')
    encode.add_argument('--unit', type=_byte, required=True)
    encode.add_argument('--cal', type=_cal, required=True, help='One supported CAL as hex bytes, such as 2104')
    encode.add_argument('--bridge', type=_byte, action='append', default=[], help='Route byte; repeat in nearest-bridge-first order')
    encode.add_argument('--addressing', choices=('direct', 'programming'), default='direct')
    encode.add_argument('--confirmation', choices=tuple('ghijklmnopqrstuvwxyz'))
    encode.add_argument('--checksum', action='store_true')
    inspect = operations.add_parser('inspect', help='Inspect a complete outgoing ASCII command supplied as hex bytes')
    inspect.add_argument('wire_hex', type=_wire, help='Hex bytes including backslash and terminating CR, such as 5C343630343030323130340D')
    inspect.add_argument('--checksum', action='store_true', help='Input contains a command checksum')
    receive = operations.add_parser('receive', help='Inspect one received addressed CAL frame offline')
    receive.add_argument('wire_hex', type=_wire,
                         help='Complete received ASCII frame as hex bytes, including checksum and terminating CR')


def run(args):
    if args.area != 'pci-route':
        raise ValueError('Unsupported routing command area')
    if args.action == 'encode':
        command = RoutedCALCommand(args.unit, args.cal, bridges=args.bridge, addressing=args.addressing)
        wire = command.encode(confirmation=None if args.confirmation is None else args.confirmation.encode('ascii'), checksum=args.checksum)
        result = inspect_routed_cal_command(wire, checksum=args.checksum).as_dict()
        result['requested'] = {'unit': command.unit, 'bridges': list(command.bridges), 'addressing': command.addressing}
    elif args.action == 'inspect':
        wire = args.wire_hex
        result = inspect_routed_cal_command(wire, checksum=args.checksum).as_dict()
    elif args.action == 'receive':
        wire = args.wire_hex
        result = inspect_received_cal_route(wire).as_dict()
    else:
        raise ValueError('Unsupported routing action')
    result['wire_text'] = wire.decode('ascii')
    result['io_performed'] = False
    return result, 0
