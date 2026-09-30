"""CLI adapters for owned, non-replaying DALI extraction and deployment."""
from pathlib import Path

from .dali_commissioning import (
    CONDITIONAL_EXTRACT_TYPES, DEPLOY_TYPES, EXTRACT_TYPES, LINES,
    READ_ONLY_EXTRACT_TYPES, DaliCommissioning, dali_target, load_edits,
    deployment_preflight,
)


def options(parser):
    actions = parser.add_subparsers(dest="remote_action", required=True)
    extract = actions.add_parser("extract", help="Extract a gateway model; conditional modes assign DALI addresses")
    extract.add_argument("target", type=dali_target)
    extract.add_argument("--line", choices=LINES, default="A")
    extract.add_argument("--extract-type", choices=EXTRACT_TYPES, default="DALI_ONLY")
    extract.add_argument("--ecg", type=int, action="append", help="Select one ECG address 0..63; repeat as needed")
    extract.add_argument("--seed-extract", choices=READ_ONLY_EXTRACT_TYPES,
                         help="Run this read-only extraction first in the same owned session")
    extract.add_argument("--allow-address-assignment", action="store_true",
                         help="Required for COND_QUICK, COND_EXTENDED or RESCAN_FAULT")
    extract.add_argument("--journal", type=Path, help="Exclusive durable attempt receipt; required for conditional modes")
    deploy = actions.add_parser("deploy", help="Extract, stage reviewed edits and optionally deploy once")
    deploy.add_argument("target", type=dali_target)
    deploy.add_argument("--line", choices=LINES, default="A")
    deploy.add_argument("--extract-type", choices=READ_ONLY_EXTRACT_TYPES, default="DALI_ONLY")
    deploy.add_argument("--deploy-type", choices=DEPLOY_TYPES, default="DALI_ONLY")
    deploy.add_argument("--ecg", type=int, action="append", help="Select one ECG address 0..63; repeat as needed")
    deploy.add_argument("--edits", type=Path, required=True, help="Ordered JSON path/value or address/bytes edit objects")
    deploy.add_argument("--dry-run", action="store_true", help="Perform physical reads and temporary staging without DEPLOY")
    deploy.add_argument("--journal", type=Path, help="Exclusive durable attempt receipt; required unless --dry-run")
    recover = actions.add_parser("recover", help="Read a saved attempt and compare fresh fields without writes or replay")
    recover.add_argument("--journal", type=Path, required=True)
    recover.add_argument("--extract-type", choices=READ_ONLY_EXTRACT_TYPES,
                         help="Override the read-only recovery extraction (default derives from edited fields)")


def preconnect(args):
    """Validate edit files and permission inputs before even opening TCP."""
    from .dali_commissioning import _selection
    if args.remote_action == "recover":
        return None
    _selection(args.target, args.line, args.extract_type, args.ecg)
    if args.journal is not None and args.journal.exists():
        raise ValueError("DALI attempt journal already exists; it cannot authorize replay")
    if args.remote_action == "extract":
        conditional = args.extract_type in CONDITIONAL_EXTRACT_TYPES
        if conditional and (not args.allow_address_assignment or args.journal is None):
            raise ValueError("Conditional extraction requires --allow-address-assignment and --journal")
        if not conditional and args.allow_address_assignment:
            raise ValueError("Address-assignment permission requires a conditional extraction mode")
        return None
    edits = load_edits(args.edits)
    if not args.dry_run and args.journal is None:
        raise ValueError("DALI deployment requires --journal unless --dry-run")
    deployment_preflight(edits, args.line, args.ecg, extract_type=args.extract_type,
                         deploy_type=args.deploy_type, dry_run=args.dry_run)
    return edits


def run(args, client, edits=None):
    workflow = DaliCommissioning(client)
    if args.remote_action == "recover":
        report = workflow.recover(args.journal, extract_type=args.extract_type)
        return report, 0 if report["conclusive"] else 1
    if args.remote_action == "extract":
        return workflow.extract(args.target, line=args.line, extract_type=args.extract_type,
                                addresses=args.ecg, seed_extract=args.seed_extract,
                                allow_address_assignment=args.allow_address_assignment,
                                journal=args.journal), 0
    return workflow.deploy(args.target, edits if edits is not None else load_edits(args.edits),
                           line=args.line, extract_type=args.extract_type, deploy_type=args.deploy_type,
                           addresses=args.ecg, dry_run=args.dry_run, journal=args.journal), 0
