"""Public, offline SESU rollout comparison under a supplied cohort."""
from __future__ import annotations

from pathlib import Path

from .toolkit_update_metadata import MAX_NODE_BYTES, validate_node_id
from .toolkit_update_metadata_cli import _read
from .toolkit_update_rollout import inspect_rollout_cohort


def options(commands):
    command = commands.add_parser(
        "update-rollout-cohort",
        help="Compare one untrusted catalogue visibility with a supplied stored cohort; no registry or update trust",
    )
    command.add_argument("--catalogue-response", type=Path, required=True,
                         help="Exact raw catalogue response body")
    command.add_argument("--node-id", required=True, help="Unique catalogue node ID")
    command.add_argument("--stored-cohort", required=True,
                         help="Caller-supplied stored cohort, ASCII decimal 0..99; no host registry read")


def run(args):
    if args.area != "update-rollout-cohort":
        raise ValueError("Unsupported rollout-cohort command")
    validate_node_id(args.node_id)
    source = _read(args.catalogue_response, MAX_NODE_BYTES)
    result = inspect_rollout_cohort(
        source, node_id=args.node_id, stored_cohort=args.stored_cohort,
    )
    return result.as_dict(), {"passed": 0, "failed": 1, "unsupported": 2}[result.status]
