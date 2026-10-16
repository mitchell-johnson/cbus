"""Pure validation and JSON serialization for explicit offline input adapters."""
from __future__ import annotations

import json
import math
import re

MAX_INPUT_BYTES = 4 * 1024 * 1024
MAX_OUTPUT_BYTES = 16 * 1024 * 1024
MAX_JSON_DEPTH = 64
MAX_JSON_NODES = 100_000


class InputError(ValueError):
    def __init__(self, message, code="invalid_input"):
        super().__init__(message)
        self.code = code


def object_fields(value, required, optional=(), *, label="object"):
    if type(value) is not dict:
        raise InputError(f"{label} must be a JSON object")
    if any(type(key) is not str for key in value):
        raise InputError(f"{label} keys must be strings")
    required, optional = set(required), set(optional)
    if not required.issubset(value) or set(value) - required - optional:
        raise InputError(f"{label} has missing or unknown fields")
    return value


def as_array(value, label, *, max_items=4096):
    if type(value) is not list or len(value) > max_items:
        raise InputError(f"{label} must be a bounded JSON array")
    return value


def as_text(value, label, *, allow_empty=False):
    if type(value) is not str or (not allow_empty and not value):
        raise InputError(f"{label} must be a string" + ("" if allow_empty else " with content"))
    return value


def as_int(value, label, *, minimum=0, maximum=2**63 - 1):
    if type(value) is not int or not minimum <= value <= maximum:
        raise InputError(f"{label} must be an integer in {minimum}..{maximum}")
    return value


def as_bool(value, label):
    if type(value) is not bool:
        raise InputError(f"{label} must be a Boolean")
    return value


def hex_bytes(value, label, *, max_bytes=16 * 1024 * 1024):
    as_text(value, label, allow_empty=True)
    if len(value) % 2 or len(value) > max_bytes * 2 or re.fullmatch(r"[0-9a-fA-F]*", value) is None:
        raise InputError(f"{label} must be bounded hexadecimal bytes")
    return bytes.fromhex(value)


def _check_json_tree(value):
    pending = [(value, 0)]
    nodes = 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        if depth > MAX_JSON_DEPTH or nodes > MAX_JSON_NODES:
            raise InputError("JSON depth or node limit exceeded", "json_limit")
        if type(item) is dict:
            if any(type(key) is not str or any(0xD800 <= ord(char) <= 0xDFFF for char in key) for key in item):
                raise InputError("JSON object keys must contain Unicode scalar characters", "invalid_json")
            pending.extend((child, depth + 1) for child in item.values())
        elif type(item) is list:
            pending.extend((child, depth + 1) for child in item)
        elif type(item) is str:
            if any(0xD800 <= ord(char) <= 0xDFFF for char in item):
                raise InputError("JSON strings must contain Unicode scalar characters", "invalid_json")
        elif type(item) is float:
            if not math.isfinite(item):
                raise InputError("Nonfinite numbers are unsupported", "invalid_json")
        elif item is not None and type(item) not in (str, bool, int):
            raise InputError("Unsupported JSON value type")


def decode_json(data):
    """Decode one bounded UTF-8 object with no duplicate/nonfinite values."""
    if type(data) is not bytes or len(data) > MAX_INPUT_BYTES:
        raise InputError("Input exceeds the 4 MiB JSON limit", "input_too_large")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise InputError("Duplicate JSON object key", "duplicate_json_key")
            result[key] = value
        return result
    def constant(_value):
        raise InputError("Nonfinite numbers are unsupported", "invalid_json")
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    except InputError:
        raise
    except (ValueError, UnicodeError, RecursionError) as error:
        raise InputError("Input must contain one strict UTF-8 JSON document", "invalid_json") from error
    _check_json_tree(value)
    if type(value) is not dict:
        raise InputError("Top-level input must be a JSON object")
    return value


def json_bytes(value, *, compact=False, max_bytes=MAX_OUTPUT_BYTES):
    """Serialize deterministically with an enforced output byte cap."""
    encoder = json.JSONEncoder(sort_keys=True, ensure_ascii=True, allow_nan=False,
                               indent=None if compact else 2,
                               separators=(",", ":") if compact else None)
    chunks, size = [], 1
    try:
        for chunk in encoder.iterencode(value):
            encoded = chunk.encode("ascii")
            size += len(encoded)
            if size > max_bytes:
                raise InputError("Report exceeds the 16 MiB output limit", "output_too_large")
            chunks.append(encoded)
    except (TypeError, ValueError, RecursionError) as error:
        if isinstance(error, InputError):
            raise
        raise InputError("Report is not finite JSON", "invalid_report") from error
    return b"".join(chunks) + b"\n"
