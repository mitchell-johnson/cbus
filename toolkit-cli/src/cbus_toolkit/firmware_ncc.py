"""Bounded, offline model of the original eDLT NCC post-update branch.

Only caller-supplied, command-delimited transcript bytes are consumed. No port,
transport, clock, subprocess, restart or firmware update is available here.
Native branch outcomes are kept separate from additional transcript checks;
neither establishes execution, device identity or physical acceptance.
"""
from __future__ import annotations

import hashlib

from .firmware_diagnostics import DiagnosticError, DiagnosticParser, compare_versions


SOURCE = {
    'assembly': 'Toolkit 1.18 FirmwareUpdater 1.16.3.0',
    'sha256': 'f54ea945167436b8a3e95decb1d146d01d60e4af1badcd34f4bad626df1e54d5',
    'il_sha256': 'a76d6fef297d74dc2429dbee68252c46b46820c53ad8a2d5add8fe60eeafddfd',
    'methods': ['FirmwareUpdater.UpgradeFirmware IL_04f1..IL_07e0',
                'EdltSerialInterface.SendIdentifyNccCommand',
                'EdltSerialInterface.SendUpdateNccCommand',
                'EdltSerialInterface.SendRestartCommand',
                'EdltSerialInterface.NuCommandDataReceived'],
    'evidence': 'static IL recovery; no original post-check execution',
}
PROGRESS_KEYS = ('Updating NCC Firmware..', 'Update Started', 'Update Complete')
MAX_EXCHANGES = 6
MAX_RESPONSE_BYTES = 65536
_STEPS = {
    'identify': ('id', 10000, 10000, False),
    'ncc-versions': ('nv', 500, 10000, False),
    'ncc-update': ('nu', 0, 60000, True),
    'ncc-versions-after-update': ('nv', 0, 10000, False),
    'restart': ('rs', 0, None, True),
    'identify-after-restart': ('id', 10000, 10000, False),
}


def _step(name):
    command, delay, timeout, effectful = _STEPS[name]
    return {'step': name, 'command': command, 'request_hex': (command + '\r').encode().hex(),
            'delay_before_ms': delay, 'native_timeout_ms': timeout,
            'would_mutate_device': effectful, 'execution_supported': False}


def _validate(expected_version, exchanges):
    if (not isinstance(expected_version, str) or not 1 <= len(expected_version) <= 128
            or any(not 32 <= ord(c) <= 126 for c in expected_version)):
        raise ValueError('Expected firmware version must be 1..128 printable ASCII characters')
    if not isinstance(exchanges, (list, tuple)) or len(exchanges) > MAX_EXCHANGES:
        raise ValueError('Supply a list or tuple of at most six NCC transcript exchanges')
    admitted = []
    for exchange in exchanges:
        if not isinstance(exchange, dict) or set(exchange) - {'command', 'response', 'outcome'}:
            raise ValueError('Transcript exchange accepts only command, response and outcome')
        command = exchange.get('command')
        if not isinstance(command, str) or command not in ('id', 'nv', 'nu', 'rs'):
            raise ValueError('Unrecognized transcript command')
        outcome = exchange.get('outcome', 'response')
        allowed = ('write-ok', 'timeout', 'io-error') if command == 'rs' else ('response', 'timeout', 'io-error')
        if not isinstance(outcome, str) or outcome not in allowed:
            raise ValueError('Unrecognized outcome for transcript command')
        response = exchange.get('response', b'')
        if not isinstance(response, bytes) or len(response) > MAX_RESPONSE_BYTES:
            raise ValueError('Transcript responses must be bytes of at most 65536 bytes')
        if command == 'rs' and response:
            raise ValueError('Restart has no response contract; supply only its write outcome')
        admitted.append((command, outcome, response))
    return admitted


class _Stop(Exception):
    def __init__(self, outcome, reason=None, next_step=None):
        self.outcome, self.reason, self.next_step = outcome, reason, next_step


class _Transcript:
    def __init__(self, exchanges):
        self.exchanges, self.index = exchanges, 0
        self.steps, self.gaps = [], []

    def read(self, name):
        step = _step(name)
        if self.index == len(self.exchanges):
            raise _Stop('pending', next_step=step)
        command, outcome, data = self.exchanges[self.index]
        if command != step['command']:
            raise ValueError('Transcript command does not match the next original NCC step')
        self.index += 1
        step.update({'supplied_outcome': outcome, 'response_bytes': len(data),
                     'response_sha256': hashlib.sha256(data).hexdigest()})
        self.steps.append(step)
        if outcome in ('timeout', 'io-error'):
            raise _Stop('failed', reason=name + ':' + outcome)
        if command == 'rs':
            step['acknowledged'] = False
            return None
        parser = DiagnosticParser('id' if command == 'id' else 'nv')
        try:
            parser.feed(data)
        except DiagnosticError:
            # DiagnosticError contains raw fields/messages: never propagate it
            # into a sanitized receipt or expose unsupported input as native.
            raise ValueError('Response is outside the bounded ASCII transcript profile') from None
        if data and not data.endswith(b'\r\n'):
            self.gaps.append(name + ':trailing-fragment')
        if command == 'nu':
            # NuCommandDataReceived trims the ENTIRE line and stores empty
            # values. It does not apply NV's colon splitter or test ordering.
            lines = {line.strip() for line in parser.messages}
            if len(lines) > 256:
                raise ValueError('Progress response exceeds 256 distinct lines')
            step['progress_keys_present'] = [key for key in PROGRESS_KEYS if key in lines]
            if not set(PROGRESS_KEYS) <= lines:
                raise _Stop('failed', reason=name + ':incomplete-response')
            return None
        if not parser.complete:
            raise _Stop('failed', reason=name + ':incomplete-response')
        result = parser.result()
        step['ambiguous'] = result.ambiguous
        if result.ambiguous:
            self.gaps.append(name + ':ambiguous-response')
        return result


def evaluate_ncc_post_check(expected_version, exchanges=()):
    """Evaluate a prefix of the original NCC transcript without any I/O.

    Each exchange is ``{'command': 'id'|'nv'|'nu'|'rs', 'response': bytes,
    'outcome': 'response'|'timeout'|'io-error'|'write-ok'}``. The default outcome
    is ``response``; ``rs`` requires ``write-ok`` and an empty response. Outcomes
    are supplied facts, not measured timing or I/O. At most six exchanges and
    64 KiB per response are admitted. Missing exchanges yield the next original
    step. Out-of-order/extra exchanges and unsupported byte profiles raise
    ValueError; no automatic retry or destructive execution path exists.

    Receipts contain hashes and predicates, never raw responses, serial numbers,
    arbitrary response fields or supplied error messages. ``native_success``
    models the original branch, including its unverified success paths.
    """
    state = _Transcript(_validate(expected_version, exchanges))
    checks = {'initial_identity_usable_tiva_ncc': None, 'firmware_version_exact': None,
              'initial_ncc_versions_valid': None, 'ncc_update_required': None,
              'post_update_current_matches_target': None, 'embedded_target_unchanged': None,
              'restart_required': None, 'restart_identity_matches': None,
              'restart_firmware_version_exact': None}
    outcome, reason, next_step = 'reported-success', None, None
    try:
        identity = state.read('identify')
        checks['initial_identity_usable_tiva_ncc'] = identity.usable_identity and identity.variant == 'TivaNCC'
        if not checks['initial_identity_usable_tiva_ncc']:
            state.gaps.append('identify:unusable-or-non-ncc-identity')
        checks['firmware_version_exact'] = identity.firmware_version == expected_version
        if not checks['firmware_version_exact']:
            raise _Stop('failed', reason='identify:firmware-version-mismatch')
        versions = state.read('ncc-versions')
        # The original constructor calls precede its IsNullOrWhiteSpace test.
        # COMMAND NOT VALID therefore fails here through two empty versions.
        try:
            comparison = compare_versions(versions.embedded_version, versions.current_version)
        except ValueError:
            checks['initial_ncc_versions_valid'] = False
            raise _Stop('failed', reason='ncc-versions:invalid-version') from None
        checks['initial_ncc_versions_valid'] = True
        checks['ncc_update_required'] = comparison > 0
        if comparison > 0:
            state.read('ncc-update')
            after = state.read('ncc-versions-after-update')
            # COMMAND NOT VALID before a complete pair returns true with BOTH
            # out arguments still empty, even if one version key was received.
            current, embedded = ((after.current_version, after.embedded_version)
                                 if after.supported else ('', ''))
            # Original logs these strings without comparing or validating them.
            # Keep a stronger independent check visibly separate.
            try:
                matches = compare_versions(current, versions.embedded_version) == 0
                unchanged = compare_versions(embedded, versions.embedded_version) == 0
            except ValueError:
                matches, unchanged = False, False
            checks['post_update_current_matches_target'] = matches
            checks['embedded_target_unchanged'] = unchanged
            if not matches:
                state.gaps.append('ncc-versions-after-update:target-not-confirmed')
            if not unchanged:
                state.gaps.append('ncc-versions-after-update:embedded-target-changed-or-invalid')
            checks['restart_required'] = current == '0.0.0'
            if checks['restart_required']:
                state.read('restart')
                state.gaps.append('restart:no-final-ncc-version-read-in-original')
                try:
                    restarted = state.read('identify-after-restart')
                except _Stop as stop:
                    if stop.outcome != 'failed':
                        raise
                    state.gaps.append('identify-after-restart:failed')
                    raise _Stop('reported-success-manual-restart', reason=stop.reason) from None
                matches = (restarted.usable_identity and restarted.variant == 'TivaNCC'
                           and restarted.fields.get('Serial Number') == identity.fields.get('Serial Number')
                           and restarted.hardware_version == identity.hardware_version)
                checks['restart_identity_matches'] = matches
                checks['restart_firmware_version_exact'] = restarted.firmware_version == expected_version
                if not matches:
                    state.gaps.append('identify-after-restart:identity-not-matched')
                if not checks['restart_firmware_version_exact']:
                    state.gaps.append('identify-after-restart:firmware-version-mismatch')
    except _Stop as stop:
        outcome, reason, next_step = stop.outcome, stop.reason, stop.next_step
    if state.index != len(state.exchanges):
        raise ValueError('Transcript has exchanges after the original NCC branch stopped')
    native_success = None if outcome == 'pending' else outcome.startswith('reported-success')
    passed = native_success is True and not state.gaps
    status = ('awaiting-transcript' if outcome == 'pending' else
              'native-failure' if not native_success else
              'transcript-checks-passed' if passed else 'native-success-with-verification-gaps')
    return {'format': 'cbus-edlt-ncc-transcript-v1', 'status': status,
            'native_outcome': outcome, 'native_success': native_success, 'reason': reason,
            'transcript_checks_passed': passed, 'checks': checks,
            'verification_gaps': state.gaps, 'steps': state.steps, 'next_step': next_step,
            'expected_firmware_version_sha256': hashlib.sha256(expected_version.encode('ascii')).hexdigest(),
            'source': {**SOURCE, 'methods': list(SOURCE['methods'])},
            'read_only': True, 'commands_sent': 0, 'hardware_accessed': False,
            'native_execution': False, 'physical_acceptance': False,
            'firmware_contents_verified': False, 'destructive_execution_supported': False,
            'timing_modelled': False, 'raw_responses_reported': False}
