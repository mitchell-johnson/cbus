"""CLI registration for an explicit-file, offline Toolkit About report."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import re
import stat

from .toolkit_about import MAX_EXE_BYTES, inspect_executable, validate_context, validate_year


def _year(text):
    if type(text) is not str or not re.fullmatch('[0-9]{1,4}', text) or not 1 <= int(text) <= 9999:
        raise argparse.ArgumentTypeError('Year must be an integer from1 through9999')
    return int(text)


def options(commands):
    parser = commands.add_parser('toolkit-about', help='Read an explicit EXE and format Toolkit About information offline')
    parser.add_argument('file', type=Path, help='Explicit PE executable; it is read, never executed')
    parser.add_argument('--year', type=_year, help='Copyright-year override; defaults to the current local calendar year')
    parser.add_argument('--context', type=Path, help='Optional captured C-Gate context JSON; never verified or fetched live')


def _read(path, limit):
    state = path.lstat()
    if not stat.S_ISREG(state.st_mode) or not 0 < state.st_size <= limit:
        raise ValueError(path.name + ' must be a nonempty regular file within its byte bound')
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_CLOEXEC', 0)
    descriptor = os.open(path, flags)
    first = None
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError('Input descriptor is not a regular file')
        chunks = []; size = 0
        while size <= limit:
            chunk = os.read(descriptor, min(65536, limit + 1 - size))
            if not chunk:
                break
            chunks.append(chunk); size += len(chunk)
        if not size or size > limit:
            raise ValueError('Input is empty or exceeds its byte bound')
        return b''.join(chunks)
    except BaseException as error:
        first = error
        raise
    finally:
        try:
            os.close(descriptor)
        except BaseException:
            if first is None:
                raise


def _context(raw):
    text = raw.decode('utf-8')
    depth = 0; quoted = escaped = False
    for char in text:
        if quoted:
            if escaped: escaped = False
            elif char == '\\': escaped = True
            elif char == '"': quoted = False
        elif char == '"': quoted = True
        elif char in '[{':
            depth += 1
            if depth > 2: raise ValueError('Captured context nesting exceeds its flat schema')
        elif char in ']}': depth -= 1
    def integer(text):
        if len(text.lstrip('-')) > 19:
            raise ValueError('Captured context integer exceeds Int64 digits')
        return int(text)
    def no_float(_):raise ValueError('Captured context numbers must be integers')
    def unique(pairs):
        if len(pairs) > 5 or len({name for name,_ in pairs}) != len(pairs):
            raise ValueError('Captured context has duplicate or excessive keys')
        return dict(pairs)
    result = json.loads(text, parse_int=integer, parse_float=no_float, parse_constant=no_float, object_pairs_hook=unique)
    if type(result) is not dict:
        raise ValueError('Captured context file must contain one object')
    return validate_context(result)


def run(args):
    if args.area != 'toolkit-about':
        raise ValueError('Unsupported About command')
    year = args.year if args.year is not None else datetime.now().year
    validate_year(year)
    context = _context(_read(args.context, 16384)) if args.context is not None else None
    raw = _read(args.file, MAX_EXE_BYTES)
    result = inspect_executable(raw, year=year, context=context).as_dict()
    result['clock_read'] = args.year is None
    result['provenance']['year'] = 'current local calendar year' if args.year is None else 'explicit CLI override'
    result['source_file'] = str(args.file)
    if args.context is not None:
        result['context_file'] = str(args.context)
    return result, 0
