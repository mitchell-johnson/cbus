"""Windows-only SESU rollout branch under an explicit owned scratch key."""
from __future__ import annotations

from pathlib import Path

from .toolkit_update_metadata import MAX_NODE_BYTES, validate_node_id
from .toolkit_update_metadata_cli import _read
from .toolkit_update_rollout_registry import inspect_rollout_owned_registry


def options(commands):
    command = commands.add_parser(
        "update-rollout-owned-registry",
        help="Inspect an untrusted node through an explicitly owned HKCU Registry32 cohort scratch key on Windows",
    )
    command.add_argument("--catalogue-response", type=Path, required=True,
                         help="Exact raw, untrusted catalogue response body")
    command.add_argument("--node-id", required=True, help="Unique catalogue node ID")
    command.add_argument("--owned-namespace", required=True,
                         help="Lowercase name below Software\\CBusToolkitCli\\Tests; never the vendor updater key")
    command.add_argument("--ensure-owned-key", action="store_true",
                         help="Explicitly create the owned scratch key before reading it; preserve any existing entry")


def registry_backend(namespace, *, ensure_owned_key):
    from .windows_sesu_cohort_registry import WindowsSesuCohortRegistry
    return WindowsSesuCohortRegistry(namespace, ensure_owned_key=ensure_owned_key)


def run(args):
    if args.area != "update-rollout-owned-registry":
        raise ValueError("Unsupported owned-registry rollout command")
    validate_node_id(args.node_id)
    source = _read(args.catalogue_response, MAX_NODE_BYTES)
    registry = registry_backend(args.owned_namespace,
                                ensure_owned_key=args.ensure_owned_key)
    decision = inspect_rollout_owned_registry(
        source, node_id=args.node_id, registry=registry)
    result = decision.as_dict()
    result["owned_registry_location"] = {
        "hive": "HKCU", "view": "Registry32", "key": registry.path,
        "entry": registry.entry, "ensure_requested": args.ensure_owned_key,
    }
    return result, {"passed": 0, "failed": 1, "unsupported": 2}[decision.status]
