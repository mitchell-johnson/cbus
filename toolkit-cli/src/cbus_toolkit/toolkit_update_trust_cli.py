"""Public CLI for the offline SESU metadata-signature trust stage."""
from __future__ import annotations

from pathlib import Path

from .toolkit_update_metadata import MAX_CERTIFICATE_BYTES, MAX_NODE_BYTES, _json
from .toolkit_update_metadata_cli import _read
from .toolkit_update_trust import anchor_pins_from_certificates, evaluate_update_trust

EXIT = {"passed": 0, "failed": 1, "unsupported": 2}


def options(commands):
    command = commands.add_parser(
        "update-trust",
        help="Evaluate a supplied SESU signing chain and signed revocation lists under explicit anchors; no fetch",
    )
    command.add_argument("--leaf-certificate", type=Path, required=True, help="DER certificate named by the node token x5t")
    command.add_argument("--issuer-certificate", type=Path, action="append", default=[],
                         help="DER issuer certificate; repeat for each chain certificate above the leaf")
    command.add_argument("--revocation-list", type=Path, action="append", default=[],
                         help="Signed rv1 RevocationList JSON (data object or success response); its id binds it")
    command.add_argument("--revocation-signer", type=Path, action="append", default=[],
                         help="DER revocation-signing certificate named by an rv1 token x5t")
    command.add_argument("--at-utc", required=True, help="Explicit evaluation instant YYYY-MM-DDTHH:MM:SS[.fffffff]Z")
    anchors = command.add_mutually_exclusive_group()
    anchors.add_argument("--anchors", type=Path,
                         help="cbus-toolkit-update-trust-anchors-v1 pin file (default: original embedded pins)")
    anchors.add_argument("--anchor-root-certificate", type=Path, action="append", default=None,
                         help="Derive a root pin from this private DER file at runtime; repeatable")
    command.add_argument("--anchor-revocation-signer", type=Path, action="append", default=[],
                         help="With --anchor-root-certificate, derive a revocation-signer pin from this DER file")
    command.add_argument("--node", type=Path,
                         help="Complete node JSON whose signatures.v1 token is checked against revoked signatures")


def run(args):
    if args.area != "update-trust":
        raise ValueError("Unsupported update trust command")
    if args.anchor_revocation_signer and not args.anchor_root_certificate:
        raise ValueError("--anchor-revocation-signer requires --anchor-root-certificate")
    if args.anchor_root_certificate and not args.anchor_revocation_signer:
        raise ValueError("--anchor-root-certificate requires at least one --anchor-revocation-signer")
    anchors = None
    if args.anchors is not None:
        anchors = _read(args.anchors, 64 * 1024)
    elif args.anchor_root_certificate:
        anchors = anchor_pins_from_certificates(
            roots=[_read(path, MAX_CERTIFICATE_BYTES) for path in args.anchor_root_certificate],
            revocation_signers=[_read(path, MAX_CERTIFICATE_BYTES) for path in args.anchor_revocation_signer])
    node_token = None
    if args.node is not None:
        node = _json(_read(args.node, MAX_NODE_BYTES))
        signatures = node.get("signatures") if type(node) is dict else None
        if type(signatures) is not dict or type(signatures.get("v1")) is not str:
            raise ValueError("--node must be a node JSON object with a signatures.v1 string")
        node_token = signatures["v1"]
    report = evaluate_update_trust(
        leaf_der=_read(args.leaf_certificate, MAX_CERTIFICATE_BYTES),
        issuer_ders=[_read(path, MAX_CERTIFICATE_BYTES) for path in args.issuer_certificate],
        revocation_lists=[_read(path, MAX_NODE_BYTES) for path in args.revocation_list],
        revocation_signer_ders=[_read(path, MAX_CERTIFICATE_BYTES) for path in args.revocation_signer],
        at_utc=args.at_utc, anchors=anchors, node_token=node_token,
    ).as_dict()
    return report, EXIT[report["status"]]
