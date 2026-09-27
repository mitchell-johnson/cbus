"""Public, offline SESU preflight through a supplied stored-cohort gate."""
from __future__ import annotations

from pathlib import Path

from .toolkit_update_applicability import PLATFORMS, inspect_update_applicability
from .toolkit_update_metadata import MAX_NODE_BYTES, validate_context, validate_node_id
from .toolkit_update_metadata_cli import _read
from .toolkit_update_rollout import parse_supplied_stored_cohort


def options(commands):
    command = commands.add_parser(
        "update-applicability-cohort-preflight",
        help="Inspect the empty-condition applicability path through a caller-supplied rollout cohort; no host or trust attestation",
    )
    command.add_argument("--catalogue-response", type=Path, required=True,
                         help="Exact raw, untrusted catalogue response body")
    command.add_argument("--node-id", required=True, help="Unique catalogue node ID")
    command.add_argument("--platform", choices=PLATFORMS, required=True,
                         help="Explicit original Windows file-selection target")
    command.add_argument("--at-utc", required=True,
                         help="Explicit evaluation instant YYYY-MM-DDTHH:MM:SS[.fffffff]Z")
    command.add_argument("--stored-cohort", required=True,
                         help="Caller-supplied already-stored ASCII decimal cohort 0..99; no host registry read")


def run(args):
    if args.area != "update-applicability-cohort-preflight":
        raise ValueError("Unsupported applicability-cohort-preflight command")
    validate_node_id(args.node_id)
    validate_context(args.at_utc)
    parse_supplied_stored_cohort(args.stored_cohort)
    source = _read(args.catalogue_response, MAX_NODE_BYTES)
    result = inspect_update_applicability(
        source, node_id=args.node_id, platform=args.platform, at_utc=args.at_utc,
        stored_cohort=args.stored_cohort,
    )
    return result.as_dict(), {"passed": 0, "failed": 1, "unsupported": 2}[result.status]
