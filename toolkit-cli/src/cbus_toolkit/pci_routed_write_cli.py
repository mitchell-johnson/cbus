"""CLI for one raw routed WRITE with an exact independent ACK expectation."""
import argparse
import copy
from pathlib import Path
import re

from .commissioning_route import (
    assert_fresh_project,
    plan_commissioning_route,
    project_sha256,
    read_project_snapshot,
    revalidate_route_plan,
    route_plan_generation_id,
)
from .pci import WriteCAL
from .pci_routing import RoutedCALCommand
from .pci_routing_cli import _byte
from .pci_routed_recall import RoutedReplyPath
from .pci_routed_write import (
    RoutedWriteClient,
    create_routed_write_journal,
    load_routed_write_recovery,
    routed_write_attempt_id,
    routed_write_generation,
    update_routed_write_journal,
)
from .project import ProjectDocument


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


def _sha256(text):
    if type(text) is not str or not re.fullmatch("[0-9A-Fa-f]{64}", text):
        raise argparse.ArgumentTypeError("Expected exactly 64 hexadecimal SHA-256 characters")
    return text.lower()


def options(operations):
    parser = operations.add_parser(
        "routed-write",
        help="Write once through a raw explicit or project-resolved route and require an exact ACK",
    )
    parser.add_argument("unit", type=_byte)
    parser.add_argument("parameter", type=_byte)
    parser.add_argument("hex_data", type=_data)
    parser.add_argument("--expected-ack-tag", type=_byte, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--project-file",
        type=Path,
        help="Legacy XML/CBZ project used to resolve and bind the typed topology",
    )
    mode.add_argument(
        "--expected-source",
        type=_byte,
        help="Raw mode: explicit outer source byte of the expected ACK",
    )
    parser.add_argument("--source-network", type=_byte,
                        help="Typed mode: network attached to this PCI/CNI")
    parser.add_argument("--target-network", type=_byte,
                        help="Typed mode: logical network containing UNIT")
    parser.add_argument("--project-name",
                        help="Typed mode: require this exact project TagName")
    parser.add_argument("--project-sha256", type=_sha256,
                        help="Typed mode: require this exact project-file snapshot")
    parser.add_argument("--bridge", type=_byte, action="append", default=[],
                        help="Raw mode: outgoing bridge byte; repeat in nearest-first order")
    parser.add_argument("--expected-destination", type=_byte,
                        help="Raw mode: explicit destination byte of the expected ACK")
    parser.add_argument("--expected-route", type=_byte, action="append", default=[],
                        help="Raw mode: expected incoming route byte; repeat in received order")
    parser.add_argument("--max-events", type=_limit, default=256)
    parser.add_argument("--max-received-bytes", type=_limit, default=32768)
    parser.add_argument("--journal", type=Path, default=None,
                        help="Exclusive journal path bound to this generation; created before any send")
    parser.add_argument("--recover", action="store_true",
                        help="Read-only recovery from --journal without opening an endpoint")


def run(args):
    topology_fresh_at_handoff = False
    reply_network_revalidated = False
    journal_raw = None
    journal_path = getattr(args, "journal", None)
    recover_only = bool(getattr(args, "recover", False))
    args._pci_routed_write_error = None
    args._pci_routed_write_client = None
    args._pci_routed_write_evidence = {
        "format": "cbus-routed-write-evidence-v1",
        "complete": False,
        "stage": "cli_preflight",
        "connect_attempted": False,
        "send_attempted": False,
        "resubmitted": False,
        "logical_network_resolved": False,
    }
    try:
        if args.area != "pci" or args.action != "routed-write":
            raise ValueError("Unsupported routed WRITE CLI operation")
        if recover_only and journal_path is None:
            raise ValueError("--recover requires --journal")
        if journal_path is not None and not isinstance(journal_path, Path):
            raise ValueError("--journal must be a filesystem path")
        if recover_only:
            return _recover(args, journal_path)
        route_plan = None
        if args.project_file is not None:
            if args.local_unit is None:
                raise ValueError("Typed routed-write requires --local-unit")
            if args.source_network is None or args.target_network is None:
                raise ValueError("Typed routed-write requires --source-network and --target-network")
            if args.bridge or args.expected_destination is not None or args.expected_route:
                raise ValueError("Typed routed-write does not accept raw route expectation options")
            snapshot = read_project_snapshot(args.project_file)
            digest = project_sha256(snapshot)
            if args.project_sha256 is not None and args.project_sha256 != digest:
                raise ValueError(
                    f"Project snapshot SHA-256 mismatch: expected {args.project_sha256}, got {digest}"
                )
            project = ProjectDocument.from_snapshot(snapshot, source=args.project_file)
            route_plan = plan_commissioning_route(
                project,
                project_digest=digest,
                source_network=args.source_network,
                target_network=args.target_network,
                target_unit=args.unit,
                local_unit=args.local_unit,
                expected_ack_tag=args.expected_ack_tag,
                expected_project_name=args.project_name,
            )
            # Detect a replacement during parsing/planning and repeat this
            # exact check immediately before the one-shot transport handoff.
            assert_fresh_project(args.project_file, digest)
            bridges = route_plan.bridges
            expected = route_plan.expected
            args._pci_routed_write_evidence.update(
                logical_network_resolved=True,
                route_plan=route_plan.as_dict(),
                route_generation_id=route_plan_generation_id(route_plan),
            )
        else:
            if args.local_unit is not None:
                raise ValueError(
                    "--local-unit is reserved for typed routed-write; raw mode supplies the complete ACK path"
                )
            if args.source_network is not None or args.target_network is not None:
                raise ValueError("Raw routed-write does not accept typed network selectors")
            if args.project_name is not None or args.project_sha256 is not None:
                raise ValueError("Raw routed-write does not accept project identity options")
            if args.expected_destination is None:
                raise ValueError("Raw routed-write requires --expected-destination")
            bridges = tuple(args.bridge)
            expected = RoutedReplyPath(
                args.expected_source,
                args.expected_destination,
                tuple(args.expected_route),
            )
        command = RoutedCALCommand(
            args.unit,
            WriteCAL(args.parameter, args.hex_data),
            bridges=bridges,
            addressing="direct",
        )
        # Generation binding for an optional exclusive journal. The digest,
        # bridges and independent expected path are all part of the handle,
        # so a substituted project or mismatched expectation refuses here.
        generation = None
        attempt_id = None
        if route_plan is not None:
            generation = routed_write_generation(
                command, expected, args.expected_ack_tag,
                project_sha256=route_plan.project_sha256,
                route_plan=route_plan.as_dict(),
            )
        elif journal_path is not None:
            generation = routed_write_generation(command, expected, args.expected_ack_tag)
        if generation is not None:
            attempt_id = routed_write_attempt_id(generation)
            args._pci_routed_write_evidence.update(
                generation=generation,
                attempt_id=attempt_id,
            )
        if route_plan is not None:
            # Exact Reply Network revalidation from fresh bytes before any
            # journal creation or send.
            revalidate_route_plan(route_plan, args.project_file)
            reply_network_revalidated = True
            args._pci_routed_write_evidence["reply_network_revalidated"] = True
        if journal_path is not None:
            if generation is None:
                raise ValueError("Journaling requires a bound generation")
            journal_raw = create_routed_write_journal(journal_path, generation)
            args._pci_routed_write_evidence.update(
                journal=str(journal_path),
                journal_stage="planned",
                attempt_id=attempt_id,
            )
        client = RoutedWriteClient(
            args.host,
            args.port,
            timeout=5.0 if args.timeout is None else args.timeout,
            command_checksum=args.checksum,
            max_events=args.max_events,
            max_received_bytes=args.max_received_bytes,
        )
        args._pci_routed_write_client = client
        if route_plan is not None:
            assert_fresh_project(args.project_file, route_plan.project_sha256)
            topology_fresh_at_handoff = True
            args._pci_routed_write_evidence["topology_fresh_at_handoff"] = True
        receipt = client.exchange(command, expected=expected, expected_ack_tag=args.expected_ack_tag)
        args._pci_routed_write_evidence = client.last_evidence
        if journal_path is not None:
            completed = {
                "format": "cbus-routed-write-journal-v1",
                "operation": "routed-write",
                "attempt_id": attempt_id,
                "generation": generation,
                "route_plan": generation.get("route_plan"),
                "send_may_have_occurred": True,
                "read_only_recovery_only": True,
                "complete": True,
                "stage": "complete",
                "resubmitted": False,
                "evidence": client.last_evidence,
            }
            journal_raw = update_routed_write_journal(journal_path, journal_raw, completed)
            args._pci_routed_write_evidence.update(
                journal=str(journal_path),
                journal_stage="complete",
            )
        result = receipt.as_dict()
        result["requested"] = {
            "unit": command.unit,
            "parameter": command.cal.parameter,
            "data_hex": command.cal.data.hex().upper(),
            "bridges": list(command.bridges),
            "addressing": "direct",
        }
        result["endpoint"] = {"host": client.host, "port": client.port}
        if route_plan is not None:
            plan = route_plan.as_dict()
            result.update(
                logical_network_resolved=True,
                topology_fresh_at_handoff=True,
                reply_network_revalidated=True,
                route_plan=plan,
                route_generation_id=route_plan_generation_id(route_plan),
            )
            if generation is not None:
                result.update(generation=generation, attempt_id=attempt_id)
            if journal_path is not None:
                result.update(journal=str(journal_path), journal_stage="complete")
            args._pci_routed_write_evidence.update(
                logical_network_resolved=True,
                topology_fresh_at_handoff=True,
                reply_network_revalidated=True,
                route_plan=plan,
                route_generation_id=route_plan_generation_id(route_plan),
            )
        elif journal_path is not None:
            result.update(journal=str(journal_path), attempt_id=attempt_id,
                          generation=generation)
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
        if 'route_plan' in locals() and route_plan is not None:
            args._pci_routed_write_evidence.update(
                logical_network_resolved=True,
                topology_fresh_at_handoff=topology_fresh_at_handoff,
                reply_network_revalidated=reply_network_revalidated,
                route_plan=route_plan.as_dict(),
                route_generation_id=route_plan_generation_id(route_plan),
            )
        if journal_raw is not None and journal_path is not None:
            try:
                failed_generation = locals().get("generation")
                failed_attempt = locals().get("attempt_id")
                if failed_generation is not None and failed_attempt is not None:
                    evidence_snapshot = args._pci_routed_write_evidence
                    try:
                        evidence_copy = copy.deepcopy(evidence_snapshot)
                    except BaseException:
                        evidence_copy = {"complete": False, "evidence_export_failed": True}
                    failed_doc = {
                        "format": "cbus-routed-write-journal-v1",
                        "operation": "routed-write",
                        "attempt_id": failed_attempt,
                        "generation": failed_generation,
                        "route_plan": failed_generation.get("route_plan"),
                        "send_may_have_occurred": True,
                        "read_only_recovery_only": True,
                        "complete": False,
                        "stage": "uncertain",
                        "resubmitted": False,
                        "evidence": evidence_copy if type(evidence_copy) is dict else {},
                    }
                    try:
                        update_routed_write_journal(journal_path, journal_raw, failed_doc)
                        args._pci_routed_write_evidence.update(
                            journal=str(journal_path), journal_stage="uncertain")
                    except BaseException as journal_error:
                        args._pci_routed_write_evidence.setdefault(
                            "cleanup_errors", []).append(
                            {"type": type(journal_error).__name__, "message": str(journal_error)[:512]})
            except BaseException:
                pass
        raise


def _recover(args, journal_path: Path):
    """Read-only recovery from one journal; never opens an endpoint."""
    journal = load_routed_write_recovery(journal_path)
    generation = journal["generation"]
    # The supplied WRITE identity must match the recorded generation;
    # otherwise this recovery is for a different attempt.
    if args.project_file is not None:
        if generation.get("project_sha256") is None:
            raise ValueError("Raw journal recovery does not accept --project-file")
        assert_fresh_project(args.project_file, generation["project_sha256"])
        if args.source_network is None or args.target_network is None or args.local_unit is None:
            raise ValueError("Typed recovery requires --source-network, --target-network and --local-unit")
    elif generation.get("project_sha256") is not None:
        raise ValueError("Typed journal recovery requires --project-file")
    if args.project_file is not None:
        if args.bridge or args.expected_destination is not None or args.expected_route:
            raise ValueError("Typed recovery does not accept raw route expectation options")
        expected = RoutedReplyPath(
            generation["expected"]["outer_source_byte"],
            generation["expected"]["destination_byte"],
            tuple(generation["expected"]["route_entries"]),
        )
        bridges = tuple(generation["bridges"])
    else:
        if args.local_unit is not None:
            raise ValueError("--local-unit is reserved for typed recovery")
        if args.source_network is not None or args.target_network is not None:
            raise ValueError("Raw recovery does not accept typed network selectors")
        if args.expected_destination is None:
            raise ValueError("Raw recovery requires --expected-destination")
        bridges = tuple(args.bridge)
        expected = RoutedReplyPath(
            args.expected_source, args.expected_destination, tuple(args.expected_route))
    if (args.unit != generation["unit"] or args.parameter != generation["parameter"]
            or bytes(args.hex_data).hex().upper() != generation["data_hex"]
            or list(bridges) != list(generation["bridges"])
            or expected.as_dict() != generation["expected"]
            or args.expected_ack_tag != generation["expected_ack_tag"]):
        raise ValueError("Supplied WRITE identity does not match the journal generation; refused")
    args._pci_routed_write_evidence = {
        "format": "cbus-routed-write-evidence-v1",
        "complete": False,
        "stage": "recovery",
        "connect_attempted": False,
        "send_attempted": False,
        "send_completed": False,
        "resubmitted": False,
        "recovery_only": True,
        "logical_network_resolved": args.project_file is not None,
        "journal": str(journal_path),
        "attempt_id": journal["attempt_id"],
        "generation": generation,
        "journal_complete": journal["complete"],
        "journal_stage": journal["stage"],
    }
    result = {
        "format": "cbus-routed-write-recovery-v1",
        "recovery_only": True,
        "complete": journal["complete"],
        "stage": journal["stage"],
        "attempt_id": journal["attempt_id"],
        "generation": generation,
        "route_plan": journal["route_plan"],
        "journal": str(journal_path),
        "io_performed": False,
        "request_sent": False,
        "resubmitted": False,
        "logical_network_resolved": args.project_file is not None,
    }
    return result, 0


def error_payload(error, args):
    if (getattr(args, "area", None) != "pci" or getattr(args, "action", None) != "routed-write"
            or getattr(args, "_pci_routed_write_error", None) is not error):
        return {}
    try:
        return {"pci_routed_write_evidence": copy.deepcopy(args._pci_routed_write_evidence)}
    except BaseException:
        return {"pci_routed_write_evidence": {"complete": False, "evidence_export_failed": True}}
