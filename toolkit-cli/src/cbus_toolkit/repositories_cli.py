"""CLI adapter for the read-only native repository inventory."""
from __future__ import annotations

from .repositories import NativeRepositories


def register(subparsers):
    return subparsers.add_parser(
        "repositories", help="List native project repositories and the observed server-wide current flags")


def run(args, client_factory, ssl_context):
    with client_factory(args.host, args.port, timeout=args.timeout, ssl_context=ssl_context) as client:
        result = NativeRepositories(client).list().as_dict()
    return result, 0
