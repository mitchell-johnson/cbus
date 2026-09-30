"""Pure, bounded classic per-flavour broadcast planning and outcome assessment.

This module has no transport. Prepared monochrome bitmap bytes are caller input;
it does not render FONT/DYNAMIC labels, reconstruct key selection, save PP data,
change a real broadcast cache, or establish display/persistence acceptance.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re


REQUEST_FORMAT = 'cbus-classic-dlt-broadcast-request-v1'
PLAN_FORMAT = 'cbus-classic-dlt-broadcast-plan-v1'
OUTCOMES_FORMAT = 'cbus-classic-dlt-broadcast-outcomes-v1'
ASSESSMENT_FORMAT = 'cbus-classic-dlt-broadcast-assessment-v1'
MAX_TAG_CHARACTERS = 1024  # Local bound, not an original GUI limit.
_REQUEST_KEYS = {'format', 'project', 'network', 'application', 'application_oid',
                 'group', 'level', 'language', 'variant', 'tag_type', 'tag_value',
                 'already_broadcast', 'bitmap'}
_UUID = re.compile(r'[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}')
_ERRORS = (
    (('400', 'Syntax Error'), 'syntax_error'),
    (('408', 'Operation failed', 'System Exception'), 'system_exception'),
    (('408', 'Operation failed', 'Send failed'), 'send_failed'),
    (('402', 'Operation not supported'), 'operation_not_supported'),
)


class DltBroadcastError(ValueError):
    pass


def _canonical(value):
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False,
                          separators=(',', ':'))
    except (TypeError, ValueError) as error:
        raise DltBroadcastError('Expected finite, canonical JSON data') from error


def _hash(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _integer(value, name, minimum=0, maximum=255):
    if type(value) is not int or not minimum <= value <= maximum:
        raise DltBroadcastError(f'{name} must be an integer in {minimum}..{maximum}')
    return value


def _image_id(value):
    if re.fullmatch(r'0|[1-9][0-9]{0,4}', value) is None or int(value) > 65535:
        raise DltBroadcastError('Image ID must be a canonical decimal integer in 0..65535')
    return value


def _request(request):
    if not isinstance(request, dict) or set(request) != _REQUEST_KEYS or request.get('format') != REQUEST_FORMAT:
        raise DltBroadcastError('Expected exact ' + REQUEST_FORMAT + ' fields')
    if not isinstance(request['project'], str) or re.fullmatch(r'[A-Za-z0-9_]{1,8}', request['project']) is None:
        raise DltBroadcastError('Project must contain 1..8 letters, digits or underscores')
    for name in ('network', 'application', 'language'):
        _integer(request[name], name)
    application = request['application']
    if not (48 <= application <= 95 or application in (202, 203)):
        raise DltBroadcastError('Application must be Lighting 48..95, Trigger 202 or Enable 203')
    for name in ('group', 'level'):
        if request[name] is not None:
            _integer(request[name], name)
    if request['level'] is not None and application != 202:
        raise DltBroadcastError('A level requires Trigger Control application 202')
    _integer(request['variant'], 'variant', 1, 4)
    if type(request['already_broadcast']) is not bool:
        raise DltBroadcastError('already_broadcast must be a boolean')
    if request['application_oid'] is not None and (
            not isinstance(request['application_oid'], str) or _UUID.fullmatch(request['application_oid']) is None):
        raise DltBroadcastError('Application OID must be a bare UUID or null; its binding is caller-supplied')
    if not isinstance(request['tag_type'], str) or request['tag_type'] not in ('TEXT', 'ICON', 'DYNAMIC', 'FONT'):
        raise DltBroadcastError('Tag type must be TEXT, ICON, DYNAMIC or FONT')
    value = request['tag_value']
    if not isinstance(value, str) or len(value) > MAX_TAG_CHARACTERS or any(0xD800 <= ord(c) <= 0xDFFF for c in value):
        raise DltBroadcastError('Tag value must be a valid Unicode string of at most 1024 characters')
    bitmap = request['bitmap']
    if bitmap is not None:
        if not isinstance(bitmap, dict) or set(bitmap) != {'width', 'data_hex'}:
            raise DltBroadcastError('Prepared bitmap requires exactly width and data_hex')
        width = _integer(bitmap['width'], 'Prepared bitmap width', 1, 240)
        if not isinstance(bitmap['data_hex'], str) or re.fullmatch(r'[0-9A-Fa-f]+', bitmap['data_hex']) is None:
            raise DltBroadcastError('Prepared bitmap data_hex must contain hexadecimal bytes without whitespace')
        if len(bitmap['data_hex']) != width * 4:
            raise DltBroadcastError('Prepared bitmap must have exactly width * 2 bytes for original height 16')
    if request['tag_type'] in ('TEXT', 'ICON') and bitmap is not None:
        raise DltBroadcastError('TEXT and ICON do not consume prepared bitmap data')
    # Branch-specific prerequisites need only hold when a command can be built.
    if not request['already_broadcast'] and request['group'] is not None:
        if request['tag_type'] in ('ICON', 'DYNAMIC'):
            _image_id(value)
        if request['tag_type'] == 'FONT':
            if value.count(',') != 9 or any(ord(c) < 32 or ord(c) == 127 for c in value):
                raise DltBroadcastError('Prepared FONT requires exactly nine commas and no control characters; malformed follow-up IDs are unsupported')
            _image_id(value.split(',', 1)[0])
        if request['tag_type'] in ('DYNAMIC', 'FONT') and bitmap is None:
            raise DltBroadcastError('DYNAMIC and FONT require explicitly prepared bitmap bytes')
    return json.loads(_canonical(request))


@dataclass(frozen=True)
class DltBroadcastPlan:
    _json: str

    def as_dict(self):
        return json.loads(self._json)

    @property
    def plan_sha256(self):
        return self.as_dict()['plan_sha256']


def compile_broadcast(request):
    """Compile admitted original command/cache events without performing I/O."""
    request = _request(request)
    commands, events = [], []
    target = (f"//{request['project']}/!{request['application_oid']}" if request['application_oid'] is not None
              else f"//{request['project']}/{request['network']}/{request['application']}")
    family = {202: 'TRIGGER', 203: 'ENABLE'}.get(request['application'], 'LIGHTING')
    level = '-' if request['level'] is None else str(request['level'])
    prefix = f"{family} LABEL {target} {request['language']} {request['group']} {level} F{request['variant'] - 1}"

    def command(kind, data):
        text = prefix + ' ' + kind + ' ' + data
        row = {'index': len(commands) + 1, 'text': text, 'sha256': _hash(text),
               'timeout_ms': 30000 if kind == 'DYNAMIC' else 20000, 'type': kind, 'data': data}
        commands.append(row)
        events.append({'event': 'command', 'index': row['index']})

    def mark():
        events.append({'event': 'mark_broadcast', 'value': True})

    value, kind = request['tag_value'], request['tag_type']
    if request['already_broadcast']:
        disposition = 'already_broadcast'
    elif request['group'] is None:
        disposition = 'group_absent'
    elif kind == 'TEXT' and value not in ('', '<Default>') and any(ord(c) > 255 for c in value):
        disposition = 'unicode_suppressed'
        mark()
    else:
        disposition = 'commands_prepared'
        if kind == 'TEXT':
            if value in ('', '<Default>'):
                command('0', '10')  # Original literal DLE byte, not NUL/empty.
            else:
                command('00', ''.join(f'{ord(c):02X}' for c in value[:14]))
            mark()
        elif kind == 'ICON':
            command('ICON', value)
            mark()
        else:
            image_id = value if kind == 'DYNAMIC' else value.split(',', 1)[0]
            bitmap = request['bitmap']
            command('DYNAMIC', f"{image_id} {bitmap['width']} 16 10 {bitmap['data_hex']}")
            mark()
            command('ICON', image_id)
    payload = {'format': PLAN_FORMAT, 'request': request, 'request_sha256': _hash(_canonical(request)),
               'application_target': target, 'application_oid_binding_verified': False,
               'commands': commands, 'events': events, 'disposition': disposition,
               'initial_cache_marked': request['already_broadcast'],
               'planned_final_cache_marked': request['already_broadcast'] or bool(events),
               'planned_mark_requires_original_completion': bool(commands),
               'cache_mark_scope': 'original-model prediction, not an observed or modified runtime cache',
               'prepared_bitmap_basis': 'Caller-supplied packed bitmap bytes; original height 16 and offset 10; width 1..240 is a native encoding bound',
               'io_performed': False, 'native_accepted': False, 'device_verified': False,
               'rendering_verified': False, 'persistence_verified': False,
               'automatic_retry': False, 'full_unit_save_workflow': False}
    payload['plan_sha256'] = _hash(_canonical(payload))
    return DltBroadcastPlan(_canonical(payload))


def validate_broadcast_plan(plan):
    """Recompile every derived field and retain exact JSON type distinctions."""
    if isinstance(plan, DltBroadcastPlan):
        plan = plan.as_dict()
    if not isinstance(plan, dict) or plan.get('format') != PLAN_FORMAT:
        raise DltBroadcastError('Expected a ' + PLAN_FORMAT + ' document')
    fresh = compile_broadcast(plan.get('request'))
    if _canonical(plan) != fresh._json:
        raise DltBroadcastError('Broadcast plan differs from its canonical request-derived commands')
    return fresh


def _responses(lines):
    """Original callback fold plus a narrower supplied-native-receipt test."""
    state, error, completion_basis = 'pending', None, None
    for line in lines:
        if line.startswith('200 OK') and state != 'error':
            state, completion_basis = 'completed', '200_OK_prefix'
        for tokens, mapped in _ERRORS:
            if all(token in line for token in tokens):
                state, error, completion_basis = 'error', mapped, None
        if 'bad object' in line.lower() and state != 'error':
            state, completion_basis = 'completed', 'bad_object_substring'
    # This confirms only the shape of supplied native receipt lines. The caller
    # must establish their origin, command correlation and actual observation.
    valid_framing = all(re.fullmatch(r'[1-6][0-9]{2}[- ].*', line) is not None for line in lines)
    native_accepted = (state == 'completed' and lines[-1] in ('200 OK', '200 OK.') and valid_framing
                       and all(int(line[:3]) < 400 and 'bad object' not in line.lower() for line in lines))
    return {'original_state': state, 'original_error': error,
            'original_completion_basis': completion_basis,
            'native_accepted': native_accepted}


def _outcomes(plan, outcomes):
    if not isinstance(outcomes, dict) or set(outcomes) != {'format', 'plan_sha256', 'attempts'} or outcomes.get('format') != OUTCOMES_FORMAT:
        raise DltBroadcastError('Expected exact ' + OUTCOMES_FORMAT + ' fields')
    if outcomes['plan_sha256'] != plan['plan_sha256']:
        raise DltBroadcastError('Outcomes are bound to a different broadcast plan')
    attempts = outcomes['attempts']
    if not isinstance(attempts, list) or len(attempts) > len(plan['commands']):
        raise DltBroadcastError('Supply at most one ordered outcome per planned command')
    # Validate the entire externally supplied structure before any reduction.
    for position, row in enumerate(attempts, 1):
        if not isinstance(row, dict) or type(row.get('index')) is not int or row['index'] != position:
            raise DltBroadcastError('Outcomes must be the contiguous command prefix in exact order')
        if row.get('command_sha256') != plan['commands'][position - 1]['sha256']:
            raise DltBroadcastError('Outcome command hash differs from the planned command')
        if row.get('outcome') == 'response':
            if set(row) != {'index', 'command_sha256', 'outcome', 'responses'}:
                raise DltBroadcastError('Response outcome requires only index, command_sha256, outcome and responses')
            lines = row['responses']
            if (not isinstance(lines, list) or not 1 <= len(lines) <= 32 or any(
                    not isinstance(line, str) or not 1 <= len(line) <= 4096 or
                    any(ord(c) < 32 or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF for c in line)
                    for line in lines) or sum(len(line) for line in lines) > 65536):
                raise DltBroadcastError('Responses must be 1..32 bounded single-line strings without control characters')
        elif row.get('outcome') == 'uncertain':
            if set(row) != {'index', 'command_sha256', 'outcome', 'reason'} or row['reason'] not in (
                    'timeout', 'connection_lost', 'send_error'):
                raise DltBroadcastError('Uncertain outcome requires reason timeout, connection_lost or send_error')
        else:
            raise DltBroadcastError('Outcome must be response or uncertain')
    return json.loads(_canonical(attempts))


def assess_broadcast(plan, outcomes):
    """Fold supplied outcomes; report manual recovery without sending/retrying."""
    plan = validate_broadcast_plan(plan).as_dict()
    attempts = _outcomes(plan, outcomes)
    cache = plan['initial_cache_marked']
    if plan['disposition'] == 'unicode_suppressed':
        cache = True
    assessed, stopped = [], False
    status = 'not_observed' if plan['commands'] else plan['disposition']
    for row in attempts:
        if stopped:
            raise DltBroadcastError('Later command outcome is incompatible with the original earlier failure or incomplete command')
        if row['outcome'] == 'uncertain':
            result = {'original_state': 'unknown', 'original_error': None,
                      'original_completion_basis': None, 'native_accepted': False}
            if row['index'] == 1:
                cache = None
            status, stopped = 'uncertain', True
        else:
            result = _responses(row['responses'])
            if result['original_state'] == 'completed':
                if row['index'] == 1:
                    cache = True
                status = 'original_completed' if row['index'] == len(plan['commands']) else 'partially_observed'
            else:
                status, stopped = result['original_state'], True
        assessed.append({**row, **result})
    native_accepted = bool(plan['commands']) and len(assessed) == len(plan['commands']) and all(
        row['native_accepted'] for row in assessed)
    if status == 'uncertain':
        recovery = 'reconcile_uncertain_attempt_before_any_new_plan'
    elif status == 'error':
        recovery = 'review_error_and_reconcile_partial_delivery_before_any_new_plan'
    elif status == 'pending':
        recovery = 'resolve_incomplete_response_before_any_new_plan'
    elif native_accepted:
        recovery = 'no_retry_indicated_by_supplied_receipts'
    elif status == 'unicode_suppressed':
        recovery = 'choose_a_supported_text_or_prepared_image_workflow'
    elif status == 'already_broadcast':
        recovery = 'cache_flag_is_not_delivery_evidence; verify_before_clearing_or_replanning'
    elif status == 'group_absent':
        recovery = 'supply_an_existing_group_before_planning_delivery'
    elif status == 'original_completed':
        recovery = 'original_completion_is_not_native_acceptance; reconcile_before_replanning'
    else:
        recovery = 'explicit_decision_required_for_commands_without_supplied_outcomes'
    return {'format': ASSESSMENT_FORMAT, 'plan_sha256': plan['plan_sha256'],
            'outcomes_sha256': _hash(_canonical(outcomes)), 'status': status,
            'attempts': assessed, 'original_cache_marked': cache,
            'initial_cache_marked': plan['initial_cache_marked'],
            'planned_final_cache_marked': plan['planned_final_cache_marked'],
            'cache_mark_scope': plan['cache_mark_scope'], 'native_accepted': native_accepted,
            'native_accepted_scope': 'supplied receipt lines qualify; not independent acceptance evidence',
            'outcome_provenance': 'caller-supplied; not independently observed or authenticated',
            'commands_without_outcomes': [row['index'] for row in plan['commands'][len(attempts):]],
            'recovery': {'action': recovery, 'automatic_retry': False, 'automatic_resume': False,
                         'cache_mark_must_not_suppress_reconciliation': cache is not False,
                         'physical_state_known': False},
            'io_performed': False, 'device_verified': False, 'rendering_verified': False,
            'persistence_verified': False, 'full_unit_save_workflow': False}
