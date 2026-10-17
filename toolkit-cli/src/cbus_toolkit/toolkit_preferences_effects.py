"""Runtime effects of retained Toolkit preferences on implemented CLI features.

The denominator is research/experiments/2026-09-30/preference-runtime-consumers.json:
each of the forty registered preferences with its original consumers. Only two
have a consumer the CLI implements; the rest are GUI-only, unimplemented
workflows, or have no runtime consumer. Reads are explicit: a state file is
passed with ``--preferences``; no registry value is read implicitly.

Culture applicability for the honored effects: TemperatureUnit is a binary
low-byte test with no string surface; Default Site folds ASCII a-z only
(SysUtils.UpperCase), so Turkish dotted/dotless and fullwidth forms never match
LOCAL; the application switches are typed booleans with no string surface.
Broader locale behavior is unestablished. The site write-back and the
application candidate sets are pure previews: the CLI performs no write-back
and applies no allowlist to any command.
"""
from __future__ import annotations

from pathlib import Path

LOCAL_SITE = 'LOCAL'
LOCAL_HOST = '127.0.0.1'
# Pinned IsLocalHost literals from the runtime-consumer receipt. Comparison
# semantics beyond these two exact strings are unestablished.
LOCAL_HOSTS = ('localhost', '127.0.0.1')


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


def cgate_site_writeback(opened) -> str:
    """Preview the Default Site value OpenSite would store after opening ``opened``.

    Pure preview only; the CLI never stores it. The receipt pins that opening a
    localhost/127.0.0.1 site stores LOCAL and any other site stores its name.
    Only the two pinned literals select LOCAL: case, whitespace and
    internationalized variants are echoed unchanged because the original
    comparison semantics are unestablished.
    """
    if type(opened) is not str:
        raise ValueError('Opened site must be a string')
    return LOCAL_SITE if opened in LOCAL_HOSTS else opened


def cgate_site(values) -> dict:
    """Resolve the original startup site selection to a C-Gate host.

    Startup replaces an empty Default Site with LOCAL; OpenSite accepts
    UpperCase(site) = LOCAL as the local C-Gate. Any other name is looked up in
    the Toolkit C-Gate site list, which is not modelled, so it is rejected.
    ``writeback_preview`` is the value OpenSite would store back into Default
    Site for the opened loopback site; ``writeback_performed`` is always False
    because the CLI never writes it.
    """
    site = values['Default Site']
    if type(site) is not str:
        raise ValueError('Default Site must be a string')
    selected = site or LOCAL_SITE
    if _ascii_upper(selected) != LOCAL_SITE:
        raise ValueError(f'Default Site {site!r} names a Toolkit C-Gate site; the site list is not '
                         'modelled, so pass --host explicitly')
    return {'default_site': site, 'selected_site': selected, 'host': LOCAL_HOST,
            'writeback_preview': cgate_site_writeback(LOCAL_HOST), 'writeback_performed': False}


def application_creation_preferences(values) -> dict:
    """Extract the explicit eDLT Application Add switches from stored values.

    Both switches default to False in the original registry; the validated
    state file already types them as booleans. The dialog flag
    (TfrmApplication+0x3F1, copied from its owner) is not resolved, so this
    mapping alone decides no dialog outcome.
    """
    try:
        legacy = values['AllowLegacyApplicationCreation']
        user_defined = values['AllowUserDefinedApplicationCreation']
    except (KeyError, TypeError) as error:
        raise ValueError('Preference values must contain both application creation switches') from error
    if type(legacy) is not bool or type(user_defined) is not bool:
        raise ValueError('AllowLegacyApplicationCreation and AllowUserDefinedApplicationCreation must be booleans')
    return {'allow_legacy': legacy, 'allow_user_defined': user_defined}


def application_candidates(values, applications) -> tuple:
    """List free application addresses admitted under the stored switches.

    ``applications`` holds the occupied addresses. The pinned dialog policy
    admits 48-95/112-114/136 normally, or 48-127/136 when either switch is set.
    No CLI command calls this implicitly.
    """
    from .edlt_application_add_dialog import candidates
    return candidates(applications, application_creation_preferences(values))


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
