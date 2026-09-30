"""Bounded CLI diagnostics for an interrupted journaled firmware lifecycle.

Receipts contain scalar transfer/release facts, never raw payloads, USB traces,
identity, package secrets or journal bindings/history. A journal snapshot is a
read-only observation after failure and cannot authorize replay or resume.
"""
from __future__ import annotations

import math

# Backend exception text can contain passwords, identity or private paths.
# Retain error presence and category without copying that text into diagnostics.
_ERROR_LABELS = {'error': 'Operation failed', 'release_error': 'USB release failed',
                 'close_error': 'USB close failed', 'timing_error': 'USB release timing failed'}
_OPERATIONS = ('inspect', 'erase', 'program', 'verify')
_STAGES = ('start', 'inspect-device', 'inspect-configuration', 'inspect-status',
           'inspect-extensions', 'inspect-memory', 'readback-enable', 'readback-select',
           'readback-data', 'readback-disable', 'readback-compare', 'program-select',
           'program-data', 'program-terminate', 'erase', 'complete', 'close')
_RELEASE_BOOLS = ('complete', 'claim_attempted', 'claimed_before_release', 'release_attempted',
                  'release_succeeded', 'close_attempted', 'close_succeeded',
                  'implicit_set_interface_possible', 'state_after_release_unknown', 'deadline_bounded')
_RELEASE_ERRORS = ('error', 'release_error', 'close_error', 'timing_error')


def _scalars(source, *, booleans=(), counts=(), errors=(), enums=None):
    if type(source) is not dict:
        return None
    result = {}
    for name in booleans:
        if type(source.get(name)) is bool:
            result[name] = source[name]
    for name in counts:
        value = source.get(name)
        if type(value) is int and 0 <= value < 2**64:
            result[name] = value
        elif name in source and value is None:
            result[name] = None
    for name in errors:
        value = source.get(name)
        if type(value) is str:
            result[name] = _ERROR_LABELS[name]
        elif name in source and value is None:
            result[name] = None
    for name, choices in (enums or {}).items():
        value = source.get(name)
        if type(value) is str and value in choices:
            result[name] = value
    return result


def _transfer(source):
    result = _scalars(source, booleans=('complete', 'external', 'peer_verified', 'outcome_known'),
        counts=('address', 'length', 'payload_transferred', 'readback_bytes', 'first_mismatch', 'trace_rows'),
        errors=('error',), enums={'operation': _OPERATIONS, 'stage': _STAGES})
    if result is not None:
        for name in ('expected_sha256', 'readback_sha256'):
            value = source.get(name)
            if type(value) is str and len(value) == 64 and all(c in '0123456789abcdefABCDEF' for c in value):
                result[name] = value
            elif name in source and value is None:
                result[name] = None
    return result


def _release(source):
    result = _scalars(source, booleans=_RELEASE_BOOLS, errors=_RELEASE_ERRORS,
        enums={'release_policy': ('reset-first-alternate',)})
    if result is not None:
        elapsed = source.get('elapsed_seconds')
        if type(elapsed) in (int, float) and 0 <= elapsed <= 2**32 and math.isfinite(elapsed):
            result['elapsed_seconds'] = elapsed
    return result


def _release_source(source):
    if type(source) is dict or source is None:
        return source
    from .usb_dfu import USBReleaseOutcome
    if type(source) is USBReleaseOutcome:
        # Acquisition interruptions attach the exact dataclass. Project its
        # known fields directly instead of invoking arbitrary as_dict methods.
        result = {name: getattr(source, name) for name in (
            'complete', 'claim_attempted', 'claimed_before_release', 'release_attempted',
            'release_succeeded', 'close_attempted', 'close_succeeded', 'release_error',
            'close_error', 'timing_error', 'release_policy', 'elapsed_seconds')}
        result.update(implicit_set_interface_possible=source.release_attempted,
                      state_after_release_unknown=source.claim_attempted, deadline_bounded=False)
        return result
    return None


def _journal_snapshot(args):
    # The existing reader rejects symlinks/special files, opens nonblocking and
    # bounds bytes before validating the journal. No hardware requests are made.
    try:
        from .firmware_update_run import load_journal
        doc, _ = load_journal(args.journal)
        stages = doc['stages']
        if not stages or len(stages) > 2 or not set(stages) <= {'font', 'main'}:
            raise ValueError('Unsupported stage inventory')
        return {'snapshot_available': True, 'snapshot_only': True, 'status': doc['status'],
                'stages': dict(stages), 'replay_authorized': False}
    except BaseException:
        # Diagnostic failure must not mask the original error or disclose a path.
        return {'snapshot_available': False, 'snapshot_only': True,
                'error': 'Journal snapshot unavailable', 'replay_authorized': False}


def error_payload(error, args):
    """Export only recognized lifecycle receipts for the two update commands."""
    if getattr(args, 'area', None) != 'firmware' or getattr(args, 'action', None) not in ('update-run', 'update-resume'):
        return {}
    matched = False
    try:
        evidence = getattr(error, 'firmware_update_evidence', None)
        release = _release_source(getattr(error, 'usb_release', None))
        matched = (type(evidence) is dict and bool(evidence)) or (type(release) is dict and bool(release))
        if not matched:
            return {}
        row = _scalars(evidence, enums={'operation': _OPERATIONS, 'stage': ('font', 'main')}) or {}
        if type(evidence) is dict:
            row['transfer'] = _transfer(evidence.get('transfer'))
            row['release'] = _release(evidence.get('release'))
            if 'journal_error' in evidence:
                # Persistence errors can contain private paths; retain the fact,
                # while the original attached exception remains unchanged.
                row['journal_error'] = 'Journal persistence failed'
        row.update(complete=False, physical_device_verified=False, replay_authorized=False,
                   journal=_journal_snapshot(args))
        result = {'firmware_update_evidence': row}
        if type(release) is dict:
            result['usb_release'] = _release(release)
        return result
    except BaseException:
        return {'firmware_update_evidence': {'complete': False, 'evidence_export_failed': True,
                'physical_device_verified': False, 'replay_authorized': False}} if matched else {}
