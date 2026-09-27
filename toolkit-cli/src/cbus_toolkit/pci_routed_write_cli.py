"""CLI for one raw routed WRITE with an exact independent ACK expectation."""
import argparse
import copy
import re

from .pci import WriteCAL
from .pci_routing import RoutedCALCommand
from .pci_routing_cli import _byte
from .pci_routed_recall import RoutedReplyPath
from .pci_routed_write import RoutedWriteClient


def _limit(text):
    if type(text) is not str or not re.fullmatch("[0-9]{1,7}", text):
        raise argparse.ArgumentTypeError("Expected a positive decimal resource limit")
    value = int(text)
    if value <= 0:
        raise argparse.ArgumentTypeError("Expected a positive decimal resource limit")
    return value


def _data(text):
    if type(text) is not str or len(text) > 60 or len(text) % 2 or not re.fullmatch("[0-9A-Fa-f]*", text):
        raise argparse.ArgumentTypeError("WRITE data must be 0..30 complete hexadecimal bytes")
    return bytes.fromhex(text)


def options(operations):
    parser = operations.add_parser(
        "routed-write",
        help="Write one raw parameter through an explicit route and require an exact ACK path/tag",
    )
    parser.add_argument("unit", type=_byte)
    parser.add_argument("parameter", type=_byte)
    parser.add_argument("hex_data", type=_data)
    parser.add_argument("--expected-ack-tag", type=_byte, required=True)
    parser.add_argument("--bridge", type=_byte, action="append", default=[],
                        help="Outgoing bridge byte; repeat in nearest-first order")
    parser.add_argument("--expected-source", type=_byte, required=True,
                        help="Explicit outer source byte of the expected ACK")
    parser.add_argument("--expected-destination", type=_byte, required=True)
    parser.add_argument("--expected-route", type=_byte, action="append", default=[],
                        help="Expected incoming route byte; repeat in received order")
    parser.add_argument("--max-events", type=_limit, default=256)
    parser.add_argument("--max-received-bytes", type=_limit, default=32768)


def run(args):
    args._pci_routed_write_error = None
    args._pci_routed_write_client = None
    args._pci_routed_write_evidence = {
        "format": "cbus-routed-write-evidence-v1",
        "complete": False,
        "stage": "cli_preflight",
        "connect_attempted": False,
        "send_attempted": False,
        "resubmitted": False,
    }
    try:
        if args.area != "pci" or args.action != "routed-write":
            raise ValueError("Unsupported routed WRITE CLI operation")
        if args.local_unit is not None:
            raise ValueError("--local-unit is not used by routed-write; supply the complete expected ACK path")
        command = RoutedCALCommand(
            args.unit,
            WriteCAL(args.parameter, args.hex_data),
            bridges=tuple(args.bridge),
            addressing="direct",
        )
        expected = RoutedReplyPath(args.expected_source, args.expected_destination, tuple(args.expected_route))
        client = RoutedWriteClient(
            args.host,
            args.port,
            timeout=5.0 if args.timeout is None else args.timeout,
            command_checksum=args.checksum,
            max_events=args.max_events,
            max_received_bytes=args.max_received_bytes,
        )
        args._pci_routed_write_client = client
        receipt = client.exchange(command, expected=expected, expected_ack_tag=args.expected_ack_tag)
        args._pci_routed_write_evidence = client.last_evidence
        result = receipt.as_dict()
        result["requested"] = {
            "unit": command.unit,
            "parameter": command.cal.parameter,
            "data_hex": command.cal.data.hex().upper(),
            "bridges": list(command.bridges),
            "addressing": "direct",
        }
        result["endpoint"] = {"host": client.host, "port": client.port}
        return result, 0
    except BaseException as error:
        args._pci_routed_write_error = error
        client = args._pci_routed_write_client
        if client is not None and client.last_error is error:
            args._pci_routed_write_evidence = client.last_evidence
        elif client is not None and type(client.last_evidence) is dict and client.last_evidence.get("complete"):
            args._pci_routed_write_evidence = {
                "complete": False,
                "stage": "result_export",
                "result_export_failed": True,
                "completed_exchange": client.last_evidence,
            }
        raise


def error_payload(error, args):
    if (getattr(args, "area", None) != "pci" or getattr(args, "action", None) != "routed-write"
            or getattr(args, "_pci_routed_write_error", None) is not error):
        return {}
    try:
        return {"pci_routed_write_evidence": copy.deepcopy(args._pci_routed_write_evidence)}
    except BaseException:
        return {"pci_routed_write_evidence": {"complete": False, "evidence_export_failed": True}}
