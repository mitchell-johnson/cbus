"""Runtime effects of retained Toolkit preferences on implemented CLI features.

The denominator is research/experiments/2026-09-30/preference-runtime-consumers.json:
each of the forty registered preferences with its original consumers. Only two
have a consumer the CLI implements; the rest are GUI-only, unimplemented
workflows, or have no runtime consumer. Reads are explicit: a state file is
passed with ``--preferences``; no registry value is read implicitly.
"""
from __future__ import annotations

from pathlib import Path

LOCAL_SITE = 'LOCAL'
LOCAL_HOST = '127.0.0.1'


def read_values(path: Path) -> dict:
    """Read the forty typed values from a complete preference state file."""
    from .toolkit_preferences_cli import read_state
    values, _display = read_state(Path(path))
    return values


def temperature_units(values) -> str:
    """Original thermostat selector: the low byte of TemperatureUnit.

    Every thermostat conversion compares ``byte ptr [pref + 0x20]`` with zero,
    so 1 and 2 select Fahrenheit while 0 and 256 select Celsius.
    """
    value = values['TemperatureUnit']
    if type(value) is not int:
        raise ValueError('TemperatureUnit must be an integer')
    return 'fahrenheit' if value & 0xFF else 'celsius'


def _ascii_upper(text: str) -> str:
    # SysUtils.UpperCase only folds ASCII a-z.
    return ''.join(chr(ord(ch) - 32) if 'a' <= ch <= 'z' else ch for ch in text)


def cgate_site(values) -> dict:
    """Resolve the original startup site selection to a C-Gate host.

    Startup replaces an empty Default Site with LOCAL; OpenSite accepts
    UpperCase(site) = LOCAL as the local C-Gate. Any other name is looked up in
    the Toolkit C-Gate site list, which is not modelled, so it is rejected.
    """
    site = values['Default Site']
    if type(site) is not str:
        raise ValueError('Default Site must be a string')
    selected = site or LOCAL_SITE
    if _ascii_upper(selected) != LOCAL_SITE:
        raise ValueError(f'Default Site {site!r} names a Toolkit C-Gate site; the site list is not '
                         'modelled, so pass --host explicitly')
    return {'default_site': site, 'selected_site': selected, 'host': LOCAL_HOST}


def apply_cgate_preferences(args) -> dict | None:
    """Fill ``args.host`` from Default Site when --host was omitted."""
    path = getattr(args, 'preferences', None)
    values = None if path is None else read_values(path)  # validate even when --host wins
    if args.host is not None:
        return None if values is None else {'default_site_ignored': True, 'reason': 'explicit --host'}
    if values is None:
        args.host = LOCAL_HOST
        return None
    resolved = cgate_site(values)
    args.host = resolved['host']
    return resolved
