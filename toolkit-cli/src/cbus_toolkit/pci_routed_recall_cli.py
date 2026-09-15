"""CLI for one routed read with an explicit independent reply path."""
import argparse
import copy
import re

from .pci import RecallCAL
from .pci_routing import RoutedCALCommand
from .pci_routing_cli import _byte
from .pci_routed_recall import RoutedRecallClient, RoutedReplyPath


def _count(text):
    value = _byte(text)
    if not 1 <= value <= 30:
        raise argparse.ArgumentTypeError('RECALL count must be in 1..30')
    return value


def _limit(text):
    if type(text) is not str or not re.fullmatch('[0-9]{1,7}', text):
        raise argparse.ArgumentTypeError('Expected a positive decimal resource limit')
    value = int(text)
    if value <= 0:
        raise argparse.ArgumentTypeError('Expected a positive decimal resource limit')
    return value


def options(operations):
    parser = operations.add_parser('routed-recall', help='Read one parameter through an explicit route and require an exact reply path')
    parser.add_argument('unit', type=_byte)
    parser.add_argument('parameter', type=_byte)
    parser.add_argument('count', type=_count)
    parser.add_argument('--bridge', type=_byte, action='append', default=[], help='Outgoing bridge byte; repeat in nearest-first order')
    parser.add_argument('--expected-source', type=_byte, required=True, help='Explicit outer source byte of the expected reply')
    parser.add_argument('--expected-destination', type=_byte, required=True)
    parser.add_argument('--expected-route', type=_byte, action='append', default=[], help='Expected incoming route byte; repeat in received order')
    parser.add_argument('--max-events', type=_limit, default=256)
    parser.add_argument('--max-received-bytes', type=_limit, default=32768)


def run(args):
    args._pci_routed_recall_error = None
    args._pci_routed_recall_client = None
    args._pci_routed_recall_evidence = {'format': 'cbus-routed-recall-evidence-v1', 'complete': False,
        'stage': 'cli_preflight', 'connect_attempted': False, 'send_attempted': False, 'resubmitted': False}
    try:
        if args.area != 'pci' or args.action != 'routed-recall':
            raise ValueError('Unsupported routed RECALL CLI operation')
        if args.local_unit is not None:
            raise ValueError('--local-unit is not used by routed-recall; supply the complete expected reply path')
        command = RoutedCALCommand(args.unit, RecallCAL(args.parameter, args.count),
                                   bridges=tuple(args.bridge), addressing='direct')
        expected = RoutedReplyPath(args.expected_source, args.expected_destination, tuple(args.expected_route))
        client = RoutedRecallClient(args.host, args.port, timeout=5.0 if args.timeout is None else args.timeout,
            command_checksum=args.checksum, max_events=args.max_events, max_received_bytes=args.max_received_bytes)
        args._pci_routed_recall_client = client
        receipt = client.exchange(command, expected=expected)
        args._pci_routed_recall_evidence = client.last_evidence
        result = receipt.as_dict()
        result['requested'] = {'unit': command.unit, 'parameter': command.cal.parameter,
            'count': command.cal.count, 'bridges': list(command.bridges), 'addressing': 'direct'}
        result['endpoint'] = {'host': client.host, 'port': client.port}
        return result, 0
    except BaseException as error:
        args._pci_routed_recall_error = error
        client = args._pci_routed_recall_client
        if client is not None and client.last_error is error:
            args._pci_routed_recall_evidence = client.last_evidence
        elif client is not None and type(client.last_evidence) is dict and client.last_evidence.get('complete'):
            args._pci_routed_recall_evidence = {'complete': False, 'stage': 'result_export',
                'result_export_failed': True, 'completed_exchange': client.last_evidence}
        raise


def error_payload(error, args):
    if (getattr(args, 'area', None) != 'pci' or getattr(args, 'action', None) != 'routed-recall'
            or getattr(args, '_pci_routed_recall_error', None) is not error):
        return {}
    try:
        return {'pci_routed_recall_evidence': copy.deepcopy(args._pci_routed_recall_evidence)}
    except BaseException:
        return {'pci_routed_recall_evidence': {'complete': False, 'evidence_export_failed': True}}
