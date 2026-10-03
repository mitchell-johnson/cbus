"""Bounded file adapter for the offline NCC post-check transcript model."""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat

from .firmware_ncc import MAX_EXCHANGES, MAX_RESPONSE_BYTES, evaluate_ncc_post_check

INPUT_FORMAT = 'cbus-edlt-ncc-transcript-input-v1'
MAX_INPUT_BYTES = 1024 * 1024


def options(parsers):
    parser = parsers.add_parser(
        'ncc-transcript', help='Check supplied NCC transcript bytes offline; no device commands execute')
    parser.add_argument('file', type=Path, nargs='?',
                        help='Bounded NCC transcript JSON; omit to report the first planned step')
    parser.add_argument('--expected-version', required=True,
                        help='Expected firmware version, compared as an exact printable ASCII string')


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate NCC transcript JSON key')
        result[key] = value
    return result


def _nonfinite(_value):
    raise ValueError('Non-finite NCC transcript JSON number')


def read_exchanges(path):
    """Read one regular file and translate strict hexadecimal responses to bytes.

    Check the path before opening so a selected device is refused without an
    open. Recheck the descriptor and use a nonblocking open for replacements.
    Symlinks to regular files are admitted. File contents,
    arbitrary keys and filesystem paths are never included in error messages.
    """
    flags = os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_BINARY', 0)
    try:
        if not stat.S_ISREG(os.stat(path).st_mode):
            raise ValueError('NCC transcript input must be a regular file')
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, 'rb') as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise ValueError('NCC transcript input must be a regular file')
            if info.st_size > MAX_INPUT_BYTES:
                raise ValueError('NCC transcript input exceeds 1 MiB')
            raw = source.read(MAX_INPUT_BYTES + 1)
    except OSError:
        raise ValueError('Cannot read NCC transcript input') from None
    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError('NCC transcript input exceeds 1 MiB')
    try:
        document = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique_pairs,
                              parse_constant=_nonfinite)
    except (ValueError, RecursionError):
        raise ValueError('NCC transcript input requires bounded UTF-8 JSON with unique keys and finite numbers') from None
    if (not isinstance(document, dict) or set(document) != {'format', 'exchanges'}
            or document.get('format') != INPUT_FORMAT):
        raise ValueError('NCC transcript input requires the exact versioned envelope')
    exchanges = document['exchanges']
    if not isinstance(exchanges, list) or len(exchanges) > MAX_EXCHANGES:
        raise ValueError('NCC transcript input requires an array of at most six exchanges')
    result = []
    for exchange in exchanges:
        if (not isinstance(exchange, dict) or 'command' not in exchange
                or set(exchange) - {'command', 'response_hex', 'outcome'}):
            raise ValueError('NCC transcript exchange accepts only command, response_hex and outcome')
        hexadecimal = exchange.get('response_hex', '')
        if (not isinstance(hexadecimal, str) or len(hexadecimal) > MAX_RESPONSE_BYTES * 2
                or len(hexadecimal) % 2
                or any(character not in '0123456789abcdefABCDEF' for character in hexadecimal)):
            raise ValueError('NCC transcript response_hex requires at most 65536 bytes of hexadecimal pairs without whitespace')
        row = {key: value for key, value in exchange.items() if key != 'response_hex'}
        row['response'] = bytes.fromhex(hexadecimal)
        result.append(row)
    return result


def run(args):
    exchanges = () if args.file is None else read_exchanges(args.file)
    result = evaluate_ncc_post_check(args.expected_version, exchanges)
    return result, int(not result['transcript_checks_passed'])
