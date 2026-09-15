"""Private, supplied-fact registry leaves; never reads a machine registry."""
from __future__ import annotations

import re

from .toolkit_update_conditions import MAX_PATH, MAX_VERSION, _failure, _native_how, _unsupported

CONTEXT_FORMAT = 'cbus-toolkit-condition-context-v2'
PROFILE = 'toolkit-1.18-sesu-3.0.7-condition-facts-v2'
PROVIDER = 'framework-registry-getvalue-x86-process-default-v1'
SENTINEL = '23021957-xxx-yy-z-27331bfa-adf0-46be-8d44-18b1a831affe'
_ROOT = 'HKEY_CURRENT_USER\\'
_INTEGER = re.compile(r'[+-]?[0-9]+\Z', re.ASCII)
_INTEGER_SPACE = ' \t\r\n'


def _printable(text):
    return all(32 <= ord(char) < 127 for char in text)


def _path(text, *, expanded=False):
    if type(text) is not str or not 0 < len(text) <= MAX_PATH or not _printable(text):
        _unsupported('Registry paths require bounded printable ASCII text')
    if not expanded and text.startswith('HKCU\\'):
        text = _ROOT + text[5:]
    if (not text.startswith(_ROOT) or len(text) > MAX_PATH
            or any(not component for component in text[len(_ROOT):].split('\\'))):
        _unsupported('Registry facts admit exact HKCU/HKEY_CURRENT_USER paths with nonempty components only')
    return text


def _entry(text):
    if type(text) is not str or not 0 < len(text) <= MAX_VERSION or not _printable(text):
        _unsupported('Registry entry names require nonempty bounded printable ASCII text')
    return text


def _primitive(value):
    if type(value) is not dict or set(value) != {'kind', 'value'}:
        _unsupported('Registry primitives require exactly kind and value')
    kind, item = value['kind'], value['value']
    if type(kind) is not str:
        _unsupported('Registry primitive kind must be exact text')
    valid = ((kind == 'null' and item is None)
             or (kind == 'System.String' and type(item) is str and len(item) <= MAX_VERSION
                 and item.isascii() and '\0' not in item)
             or (kind == 'System.Int32' and type(item) is int and -(1 << 31) <= item < (1 << 31)))
    if not valid:
        _unsupported('Registry results admit only null, bounded ASCII System.String or exact System.Int32')
    return kind, item


def facts(data):
    if (type(data) is not dict
            or set(data) != {'format', 'culture', 'files', 'registry_provider', 'registry_reads'}
            or data['format'] != CONTEXT_FORMAT or data['culture'] != 'invariant-ascii'
            or data['registry_provider'] != PROVIDER):
        _unsupported('Registry context requires exact v2 keys, invariant-ascii and the x86 process-default provider profile')
    records = data['registry_reads']
    if type(records) is not list or len(records) > 8:
        _unsupported('Context admits at most eight registry fact records')
    found = {}
    for item in records:
        if type(item) is not dict or set(item) != {'path', 'entry', 'default', 'result'}:
            _unsupported('Each registry fact requires exactly path, entry, default and result')
        path, entry = _path(item['path'], expanded=True), _entry(item['entry'])
        default = _primitive(item['default'])
        if default not in (('System.Int32', 1), ('System.String', SENTINEL)):
            _unsupported('Registry query defaults are limited to the two original typed constants')
        result = _primitive(item['result'])
        key = (path, entry, default)
        if key in found:
            _unsupported('Registry query records must have unique exact path/entry/typed-default identities')
        found[key] = result
    return found


def _int32(text):
    if text is None:
        return None
    if type(text) is not str or len(text) > MAX_VERSION or not text.isascii() or '\0' in text:
        _unsupported('Integer comparison requires bounded ASCII text or null')
    if any((ord(char) < 32 and char not in _INTEGER_SPACE) or ord(char) == 127 for char in text):
        _unsupported('Integer text uses control characters outside the captured space/tab/CR/LF domain')
    value = text.strip(_INTEGER_SPACE)
    if not _INTEGER.fullmatch(value):
        return None
    negative = value.startswith('-')
    digits = value.lstrip('+-').lstrip('0') or '0'
    bound = '2147483648' if negative else '2147483647'
    if len(digits) > 10 or (len(digits) == 10 and digits > bound):
        return None
    number = int(digits)
    return -number if negative else number


def compare_int(left, right, how, steps=None):
    """Original CompareInt ordering, independently checked against 107 calls."""
    def step(name, **details):
        if steps is not None:
            steps.append({'step': name, **details})
    step('integer_rhs_parse', text=right)
    rhs = _int32(right)
    if rhs is None:
        _failure('value defined for integer comparison cannot be converted to int: ' + (right or ''))
    if left is None or left == '' or left == SENTINEL:
        step('integer_empty_or_sentinel_lhs', result=False)
        return False
    step('integer_lhs_parse', text=left)
    lhs = _int32(left)
    if lhs is None:
        _failure('value read from registry cannot be converted to int: ' + left)
    step('integer_comparator', how=how, left=lhs, right=rhs)
    if how == 10: return lhs == rhs
    if how == 11: return lhs != rhs
    if how == 12: return lhs > rhs
    if how == 13: return lhs >= rhs
    if how == 14: return lhs < rhs
    if how == 15: return lhs <= rhs
    _failure('unexpected howToCheck = ' + _native_how(how) + ' in CompareInt')


def leaf(name, condition, registry, event):
    what, how, path, right = (condition[key] for key in ('what', 'how', 'path', 'right'))
    suffix = 'registry key existence' if what == 3 else 'registry entry existence' if what == 4 else 'registry entry content'
    event['registry_steps'] = steps = []
    if path is None or path == '':
        _failure("registry key path not given for condition '" + name + "' that checks " + suffix)
    entry = 'Test' if what == 3 else condition['entry']
    if what != 3 and (entry is None or entry == ''):
        _failure("registry entry name not given for condition '" + name + "' that checks " + suffix)
    query_path = _path(path)
    entry = _entry(entry)
    default = ('System.Int32', 1) if what == 3 else ('System.String', SENTINEL)
    query = {'path': query_path, 'entry': entry, 'default': {'kind': default[0], 'value': default[1]}}
    observation = {'provider': PROVIDER, 'query': query, 'status': 'unknown'}
    event['observations'].append(observation)
    key = (query_path, entry, default)
    if key not in registry:
        _unsupported('Required supplied registry fact is unknown', required_registry_query=query)
    kind, value = registry[key]
    observation.update(status='supplied', result={'kind': kind, 'value': value})
    # No arbitrary object or stateful ToString is admitted by the typed context.
    text = None if kind == 'null' else str(value)
    if what == 3:
        exists = kind != 'null'
    else:
        steps.append({'step': 'null_or_exact_sentinel', 'text': text, 'absent': text is None or text == SENTINEL})
        exists = text is not None and text != SENTINEL
    if what in (3, 4):
        steps.append({'step': 'existence_comparator', 'how': how})
        if how == 1: return exists
        if how == 2: return not exists
        if what == 3:
            _failure("error when evaluating condition '" + name + "': registry keys can only be checked against existence or not-existence, but not against " + _native_how(how))
        _failure("error when evaluating condition '" + name + "': not allowed HowToCheck=" + _native_how(how) + ' for registry entry existence condition')
    if not exists:
        steps.append({'step': 'missing_content_shortcut', 'result': how == 11})
        return how == 11
    left = text.lower()
    steps.append({'step': 'lowercase_lhs', 'text': text, 'lowered': left})
    if right is None:
        _failure("ComparisonRightSideValue is null for condition '" + name + "' that checks registry entry content")
    lowered_right = right.lower()
    steps.append({'step': 'lowercase_rhs', 'text': right, 'lowered': lowered_right})
    if what == 6:
        return compare_int(left, lowered_right, how, steps)
    if how in (12, 13, 14, 15, 16):
        _unsupported('Culture-sensitive registry string ordering and prefix comparisons are outside this profile')
    if how in (10, 11, 17):
        if not _printable(left + lowered_right):
            _unsupported('Registry string comparison admits printable ASCII only')
        steps.append({'step': 'string_comparator', 'how': how})
        if how == 10: return left == lowered_right
        if how == 11: return left != lowered_right
        return lowered_right in left
    _failure('unexpected howToCheck = ' + _native_how(how) + " in condition '" + name + "' that checks registry entry content")
