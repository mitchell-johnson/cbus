"""Public CLI for the same-source SESU composite update report."""
from __future__ import annotations

from pathlib import Path

from .toolkit_update_applicability import PLATFORMS
from .toolkit_update_bundle import MAX_REPORT_BYTES
from .toolkit_update_composite import compose_update_report
from .toolkit_update_conditions import MAX_JSON_BYTES
from .toolkit_update_metadata import MAX_CERTIFICATE_BYTES, MAX_NODE_BYTES
from .toolkit_update_metadata_cli import _read
from .toolkit_update_trust import anchor_pins_from_certificates

EXIT = {"eligible": 0, "failed": 1, "refused": 1, "unsupported": 2}


def options(commands):
    command = commands.add_parser(
        "update-composite-report",
        help="Chain catalogue, metadata, revocation, conditions, applicability, trust and download eligibility "
             "from one supplied input set; never downloads",
    )
    command.add_argument("--catalogue-report", type=Path, required=True, help="Complete update-catalogue report JSON")
    command.add_argument("--catalogue-response", type=Path, required=True,
                         help="Exact raw catalogue response body described by that report")
    command.add_argument("--node-id", required=True, help="Unique catalogue node ID")
    command.add_argument("--file-id", required=True, help="Unique file ID within that node")
    command.add_argument("--platform", choices=PLATFORMS, required=True, help="Explicit Windows file-selection target")
    command.add_argument("--at-utc", required=True, help="Explicit evaluation instant YYYY-MM-DDTHH:MM:SS[.fffffff]Z")
    command.add_argument("--leaf-certificate", type=Path, required=True, help="DER certificate named by the node token")
    command.add_argument("--issuer-certificate", type=Path, action="append", default=[], help="DER issuer; repeatable")
    command.add_argument("--revocation-list", type=Path, action="append", default=[],
                         help="Signed rv1 RevocationList JSON bound by its id; repeatable")
    command.add_argument("--revocation-signer", type=Path, action="append", default=[],
                         help="DER revocation-signing certificate; repeatable")
    anchors = command.add_mutually_exclusive_group()
    anchors.add_argument("--anchors", type=Path, help="Anchor pin file (default: original embedded pins)")
    anchors.add_argument("--anchor-root-certificate", type=Path, action="append", default=None,
                         help="Derive a root pin from this private DER file at runtime; repeatable")
    command.add_argument("--anchor-revocation-signer", type=Path, action="append", default=[],
                         help="With --anchor-root-certificate, derive a revocation-signer pin from this DER file")
    command.add_argument("--condition-context", type=Path,
                         help="Supplied condition facts (context v1/v2) for a node with nonempty conditions")
    command.add_argument("--stored-cohort", help="Caller-supplied stored cohort 0..99 for visibility below 100")


def run(args):
    if args.area != "update-composite-report":
        raise ValueError("Unsupported composite update command")
    if bool(args.anchor_root_certificate) != bool(args.anchor_revocation_signer):
        raise ValueError("--anchor-root-certificate and --anchor-revocation-signer must be supplied together")
    anchors = None
    if args.anchors is not None:
        anchors = _read(args.anchors, 64 * 1024)
    elif args.anchor_root_certificate:
        anchors = anchor_pins_from_certificates(
            roots=[_read(path, MAX_CERTIFICATE_BYTES) for path in args.anchor_root_certificate],
            revocation_signers=[_read(path, MAX_CERTIFICATE_BYTES) for path in args.anchor_revocation_signer])
    report = compose_update_report(
        catalogue_report=_read(args.catalogue_report, MAX_REPORT_BYTES),
        catalogue_response=_read(args.catalogue_response, MAX_NODE_BYTES),
        node_id=args.node_id, file_id=args.file_id, platform=args.platform, at_utc=args.at_utc,
        leaf_der=_read(args.leaf_certificate, MAX_CERTIFICATE_BYTES),
        issuer_ders=[_read(path, MAX_CERTIFICATE_BYTES) for path in args.issuer_certificate],
        revocation_lists=[_read(path, MAX_NODE_BYTES) for path in args.revocation_list],
        revocation_signer_ders=[_read(path, MAX_CERTIFICATE_BYTES) for path in args.revocation_signer],
        anchors=anchors,
        condition_context=None if args.condition_context is None else _read(args.condition_context, MAX_JSON_BYTES),
        stored_cohort=args.stored_cohort,
    ).as_dict()
    return report, EXIT[report["status"]]
