"""Read-only numeric IOPE delay inspection; separate from native PP editors.

Source arithmetic: iope-output-source-review.json, FormatTimeShort 0x1194d84.
No localized strings, native execution or physical behavior are established.
"""
import argparse

from .pp_editor import PPEditError, integer


def restrike_delay_time(ordinal):
    """Decode numeric time parts for every stored byte, including 0 and 255."""
    ordinal = integer(ordinal, "Restrike delay ordinal")
    if not 0 <= ordinal <= 255:
        raise PPEditError("Restrike delay ordinal must be 0..255")
    return {"minutes": ordinal // 6, "seconds": (ordinal % 6) * 10}


def restrike_delay_choices():
    """List the raw-value selector's complete 1..254 admitted inventory."""
    return [{"ordinal": value, **restrike_delay_time(value)} for value in range(1, 255)]


def _subcommands(parser):
    return next(action for action in parser._actions if isinstance(action, argparse._SubParsersAction))


def options(commands):
    """Extend only the public parser; the native workflow parser is unchanged."""
    workflow = commands.choices["iope-workflow"]
    output = _subcommands(workflow).choices["output"]
    actions = _subcommands(output)
    time = actions.add_parser("restrike-delay-time", help="Inspect numeric time parts for a stored delay byte")
    time.add_argument("ordinal", type=int)
    actions.add_parser("restrike-delay-choices", help="List the 254 selectable delay ordinals")


def run(args):
    if args.action == "restrike-delay-time":
        return {"format": "cbus-iope-restrike-delay-time-v1", "ordinal": args.ordinal,
                **restrike_delay_time(args.ordinal), "listed": 1 <= args.ordinal <= 254,
                "localized_display_verified": False}, 0
    if args.action == "restrike-delay-choices":
        return {"format": "cbus-iope-restrike-delay-choices-v1",
                "choices": restrike_delay_choices(), "localized_display_verified": False}, 0
    raise ValueError("Unsupported delay inspection action")
