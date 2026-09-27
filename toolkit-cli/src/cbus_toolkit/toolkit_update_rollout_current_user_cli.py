"""Explicitly source-bound, read-only current-user SESU cohort observation."""
from __future__ import annotations

from pathlib import Path

from .windows_sesu_current_user_cohort import observe_current_user_cohort


def options(commands):
    command = commands.add_parser(
        "update-rollout-current-user",
        help="Read the pinned original SESU cohort in this Windows process user's HKCU Registry32 view",
    )
    command.add_argument("--source-assembly", type=Path, required=True,
                         help="Installed SesuBrick.DAD.dll; exact original bytes are required")
    command.add_argument("--expected-source-sha256", required=True,
                         help="Explicit exact SHA-256 of the pinned SESU 3.0.7 assembly")
    command.add_argument("--expected-user-sid", required=True,
                         help="Explicit Windows SID of the intended current process user")


def run(args):
    if args.area != "update-rollout-current-user":
        raise ValueError("Unsupported current-user rollout command")
    result = observe_current_user_cohort(
        args.source_assembly,
        expected_source_sha256=args.expected_source_sha256,
        expected_user_sid=args.expected_user_sid,
    )
    return result.as_dict(), 0 if result.status == "observed" else 2
