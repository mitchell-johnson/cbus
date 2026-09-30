"""Port of the SESU 3.0.7 file-version comparator.

``ClientConditionChecker.EvaluateFileVersion`` (SE.DAD.SESU.Common RVA 0x26A8)
parses both sides with ``System.Version.TryParse`` and applies
``Version.CompareTo`` through a six-way HowToCheck switch. BeginsWith and
Contains use the raw strings instead. This module reproduces the parse and
comparison rules pinned by ``research/fixtures/toolkit-update-version-vectors.json``;
it never reads a file or its version resource.
"""
from __future__ import annotations

import re

INT32_MAX = 2147483647
# Int32.TryParse(NumberStyles.Integer, invariant): leading/trailing white space
# U+0009..U+000D and U+0020, one leading sign, ASCII digits, then only NULs.
_COMPONENT = re.compile(r'[\t\n\v\f\r ]*([+-]?)([0-9]+)[\t\n\v\f\r ]*\x00*\Z', re.ASCII)

HOW_NAMES = {10: 'isEqual', 11: 'isNotEqual', 12: 'isGreater', 13: 'isGreaterOrEqual',
             14: 'isLess', 15: 'isLessOrEqual', 16: 'beginsWith', 17: 'contains'}
_ORDER = {10: lambda c: c == 0, 11: lambda c: c != 0, 12: lambda c: c > 0,
          13: lambda c: c >= 0, 14: lambda c: c < 0, 15: lambda c: c <= 0}


def parse_version(text):
    """Return ``(major, minor, build, revision)`` with omitted parts as -1, or None.

    Mirrors ``System.Version.TryParse``: two to four '.'-separated components,
    each a non-negative Int32 under the invariant integer grammar above.
    """
    if type(text) is not str:
        return None
    parts = text.split('.')
    if not 2 <= len(parts) <= 4:
        return None
    values = []
    for part in parts:
        match = _COMPONENT.match(part)
        if match is None:
            return None
        sign, digits = match.groups()
        digits = digits.lstrip('0') or '0'
        if len(digits) > 10 or int(digits) > INT32_MAX:
            return None
        value = -int(digits) if sign == '-' else int(digits)
        if value < 0:
            return None
        values.append(value)
    return tuple(values + [-1] * (4 - len(values)))


def compare_versions(left, right):
    """``Version.CompareTo`` sign for two parsed versions (-1, 0 or 1)."""
    return (left > right) - (left < right)


class VersionComparisonError(ValueError):
    """The original's ClientConditionException for an invalid comparison request."""


def evaluate_file_version(how, observed, right, *, name='condition'):
    """Evaluate one fileVersion comparison under an explicit observed version.

    ``observed`` is the version-resource text, or None for a missing file or
    absent/empty FileVersion (the original returns false). Invalid requests
    raise ``VersionComparisonError`` with the original message. BeginsWith is
    culture-sensitive in the original; this port admits printable ASCII only.
    """
    if right is None or right == '':
        raise VersionComparisonError("version to compare not given for condition '" + name + "' that checks file version")
    if how in (1, 2):
        raise VersionComparisonError("unexpected howToCheck for condition '" + name + "' that checks file version")
    requested = None
    if how not in (16, 17):
        requested = parse_version(right)
        if requested is None:
            raise VersionComparisonError("invalid version given in condition '" + name + "' that checks file version")
    if observed is None or observed == '':
        return False
    if how == 16:
        if any(not 32 <= ord(char) < 127 for char in observed + right):
            raise ValueError('Culture-sensitive beginsWith is admitted for printable ASCII only')
        return observed.startswith(right)
    if how == 17:
        return right in observed
    parsed = parse_version(observed)
    if parsed is None:
        return False
    if how in _ORDER:
        return _ORDER[how](compare_versions(parsed, requested))
    raise VersionComparisonError('unexpected howToCheck = ' + str(how) + " in condition '" + name + "' that checks file version")
