"""Offline classic DLT network-save sequencing for explicitly resolved models.

No transport or whole-unit PP serializer lives here. The caller supplies key
roles, selected owners/flavours, a resolved network language and prepared image
cache. Operation outcomes describe original call returns/exceptions; they are
neither authenticated receipts nor evidence of device acceptance.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re

from .dlt_broadcast import DltBroadcastError, compile_broadcast


REQUEST_FORMAT = 'cbus-classic-dlt-unit-delivery-request-v1'
PLAN_FORMAT = 'cbus-classic-dlt-unit-delivery-plan-v1'
OUTCOMES_FORMAT = 'cbus-classic-dlt-unit-delivery-outcomes-v1'
ASSESSMENT_FORMAT = 'cbus-classic-dlt-unit-delivery-assessment-v1'
_REQUEST_KEYS = {'format', 'project', 'network', 'unit_application', 'unit_address',
                 'default_language', 'save_labels', 'transfer', 'block_dynamic_updates',
                 'kfi_enabled', 'reblock_session_open', 'keys'}
_KEY_KEYS = {'key', 'kfi', 'role', 'target_state', 'flavour'}
_PROVENANCE = 'caller-supplied; not independently observed or authenticated'


class DltUnitDeliveryError(ValueError):
    pass


def _canonical(value):
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False,
                          separators=(',', ':'))
    except (TypeError, ValueError) as error:
        raise DltUnitDeliveryError('Expected finite canonical JSON data') from error


def _hash(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _integer(value, name, minimum=0, maximum=255):
    if type(value) is not int or not minimum <= value <= maximum:
        raise DltUnitDeliveryError(f'{name} must be an integer in {minimum}..{maximum}')


def _request(request):
    if (not isinstance(request, dict) or set(request) != _REQUEST_KEYS
            or request.get('format') != REQUEST_FORMAT):
        raise DltUnitDeliveryError('Expected exact ' + REQUEST_FORMAT + ' fields')
    if not isinstance(request['project'], str) or re.fullmatch(r'[A-Za-z0-9_]{1,8}', request['project']) is None:
        raise DltUnitDeliveryError('Project must contain 1..8 letters, digits or underscores')
    for field in ('network', 'unit_application', 'unit_address'):
        _integer(request[field], field)
    _integer(request['default_language'], 'Resolved default language', 1, 255)
    for field in ('save_labels', 'transfer', 'block_dynamic_updates', 'kfi_enabled', 'reblock_session_open'):
        if type(request[field]) is not bool:
            raise DltUnitDeliveryError(field + ' must be a boolean')
    keys = request['keys']
    if not isinstance(keys, list) or len(keys) > 8:
        raise DltUnitDeliveryError('keys must contain 0..8 ordered logical keys')
    for number, key in enumerate(keys, 1):
        if not isinstance(key, dict) or set(key) != _KEY_KEYS:
            raise DltUnitDeliveryError('Each key requires exactly key, kfi, role, target_state and flavour')
        if type(key['key']) is not int or key['key'] != number:
            raise DltUnitDeliveryError('Logical keys must be contiguous and ordered from 1')
        _integer(key['kfi'], 'Key function indicator', 0, 15)
        if not isinstance(key['role'], str) or key['role'] not in ('ordinary', 'scene', 'scene_modify'):
            raise DltUnitDeliveryError('Key role must be ordinary, scene or scene_modify')
        if not isinstance(key['target_state'], str) or key['target_state'] not in ('present', 'missing', 'unused'):
            raise DltUnitDeliveryError('Target state must be present, missing or unused')
        if key['role'] == 'scene' and key['target_state'] == 'unused':
            raise DltUnitDeliveryError('Scene target state describes a present or missing trigger level')
        flavour = key['flavour']
        if key['target_state'] != 'present' and flavour is not None:
            raise DltUnitDeliveryError('An absent or unused target cannot have a selected flavour')
        if flavour is None:
            continue
        # The outer clear decision precedes inner payload validation. Validate
        # the common request with its early-return gate, then compile the active
        # payload only if this unit workflow will actually broadcast it.
        if not isinstance(flavour, dict) or type(flavour.get('already_broadcast')) is not bool:
            raise DltUnitDeliveryError('Selected flavour requires a complete broadcast request')
        try:
            compile_broadcast({**flavour, 'already_broadcast': True})
        except DltBroadcastError as error:
            raise DltUnitDeliveryError('Invalid selected flavour: ' + str(error)) from error
        if (flavour['project'] != request['project'] or flavour['network'] != request['network']
                or flavour['language'] != request['default_language']):
            raise DltUnitDeliveryError('Selected flavour must match project, network and resolved default language')
        if flavour['group'] is None:
            raise DltUnitDeliveryError('A retained flavour must have a resolved group')
        if key['role'] != 'scene' and flavour['group'] == 255:
            raise DltUnitDeliveryError('Group 255 is unused for ordinary and scene-modify keys; it cannot be declared present')
        if key['role'] == 'scene':
            if flavour['application'] != 202 or flavour['level'] is None:
                raise DltUnitDeliveryError('A scene key requires a resolved Trigger Control level')
        elif flavour['level'] is not None:
            raise DltUnitDeliveryError('Ordinary and scene-modify keys require a group rather than a level')
        if ((request['save_labels'] or request['transfer']) and key['role'] == 'ordinary'
                and flavour['tag_type'] in ('DYNAMIC', 'FONT')
                and flavour['bitmap'] is None):
            raise DltUnitDeliveryError('Ordinary DYNAMIC/FONT requires a prepared nonempty bitmap cache; original LoadDLTBitmap is an unresolved prerequisite')
    return json.loads(_canonical(request))


@dataclass(frozen=True)
class DltUnitDeliveryPlan:
    _json: str

    def as_dict(self):
        return json.loads(self._json)

    @property
    def plan_sha256(self):
        return self.as_dict()['plan_sha256']


def compile_unit_delivery(request):
    """Compile a bounded resolved network-save trace, without executing it."""
    request = _request(request)
    operations, events, decisions = [], [], []
    relative_target = f"{request['network']}/{request['unit_application']} {request['unit_address']}"

    def event(kind, **fields):
        events.append({'event': kind, **fields})

    def operation(identifier, kind, *, key=None, error_policy='abort', **fields):
        value = {'id': identifier, 'kind': kind, 'key': key, 'error_policy': error_policy, **fields}
        value['operation_sha256'] = _hash(_canonical(value))
        operations.append(value)
        event('operation', id=identifier, key=key)

    operation('initial_save', 'initial_save', enable_dynamic_labels=1,
              boundary='inherited network save, including PP SAVE, ProjectSave and LoadStatus, through entry to AfterSaveProgrammingInformation',
              whole_pp_serialized=False)
    if request['kfi_enabled']:
        values = [key['kfi'] for key in request['keys']] + [0] * (8 - len(request['keys']))
        operation('kfi', 'kfi', command='label kfiset ' + relative_target + ' ' + ' '.join(map(str, values)),
                  values=values, relative_project_context=request['project'])
    event('reset_label_errors')
    event('resolved_language_prerequisite', language=request['default_language'])
    enabled = bool(request['keys']) and (request['save_labels'] or request['transfer'])
    for key in request['keys']:
        number, flavour = key['key'], key['flavour']
        decision = {'key': number, 'role': key['role'], 'target_state': key['target_state']}
        if not enabled:
            decision['action'] = 'gate_skipped'
        elif key['target_state'] != 'present' and key['role'] != 'ordinary':
            decision['action'] = 'target_skipped'
        elif key['target_state'] != 'present' or flavour is None:
            decision['action'] = 'clear_without_flavour'
            operation(f'key.{number}.clear', 'clear', key=number,
                      command=f'label clear {relative_target} {number}',
                      relative_project_context=request['project'])
        else:
            event('reset_broadcast', key=number, value=False,
                  supplied_initial_value=flavour['already_broadcast'])
            clear = (flavour['tag_value'] in ('', '<Default>') or
                     (flavour['tag_type'] in ('DYNAMIC', 'FONT') and flavour['bitmap'] is None))
            if clear:
                decision['action'] = 'clear_retained_flavour'
                operation(f'key.{number}.clear', 'clear', key=number, error_policy='collect_cgate_command',
                          command=f'label clear {relative_target} {number}',
                          relative_project_context=request['project'])
                event('mark_broadcast', key=number, value=True)
            else:
                try:
                    broadcast = compile_broadcast({**flavour, 'already_broadcast': False}).as_dict()
                except DltBroadcastError as error:
                    raise DltUnitDeliveryError('Uncompilable selected flavour: ' + str(error)) from error
                decision['action'] = 'broadcast'
                decision['broadcast_plan'] = broadcast
                for step in broadcast['events']:
                    if step['event'] == 'mark_broadcast':
                        event('mark_broadcast', key=number, value=True)
                    else:
                        command = broadcast['commands'][step['index'] - 1]
                        operation(f"key.{number}.broadcast.{step['index']}", 'broadcast', key=number,
                                  error_policy='collect_cgate_command', command=command['text'],
                                  command_sha256=command['sha256'], timeout_ms=command['timeout_ms'],
                                  broadcast_plan_sha256=broadcast['plan_sha256'], command_index=step['index'])
        decisions.append(decision)
    if request['block_dynamic_updates']:
        own = not request['reblock_session_open']
        operation('reblock', 'reblock', enable_dynamic_labels=0, timeout_ms=30000,
                  opens_session=own, saves_existing_session=True,
                  sequence=(['LOCK', 'START', 'LOAD'] if own else []) + ['SET EnableDynamicLabels=0', 'SAVE'],
                  owned_cleanup=['END', 'UNLOCK'] if own else [],
                  cleanup_scope='Original owned-session finally path; END failure can prevent UNLOCK; operation receipt does not resolve individual cleanup steps')
    result = {'format': PLAN_FORMAT, 'request': request, 'request_sha256': _hash(_canonical(request)),
              'operations': operations, 'events': events, 'keys': decisions,
              'delivery_gate': enabled, 'mode': 'resolved_network_save',
              'relative_commands_require_active_project': request['project'],
              'active_project_binding_verified': False,
              'input_provenance': _PROVENANCE,
              'cache_scope': 'per-key selected-model predictions; every retained key resets its mark; no alias reconstruction or deduplication',
              'prerequisites': ['Resolved nonnull network default language and initialized language cache',
                                'Caller-resolved logical key roles, owners and selected flavours',
                                'Prepared nonempty bitmap cache for ordinary DYNAMIC/FONT keys',
                                'Correct active project for relative KFI and clear commands'],
              'excluded': ['database save', 'align and readdress saves', 'physical key/page mapping',
                           'key-role derivation from PP', 'network language initialization',
                           'bitmap/font loading or rendering', 'whole-unit PP serialization',
                           'transport execution and automatic recovery'],
              'key_function_indicator_portable_range': [0, 15],
              'key_function_indicator_range_basis': 'Portable bound; original model field is a byte',
              'io_performed': False, 'native_accepted': False, 'device_verified': False,
              'rendering_verified': False, 'persistence_verified': False,
              'automatic_retry': False, 'full_unit_save_executor': False}
    result['plan_sha256'] = _hash(_canonical(result))
    return DltUnitDeliveryPlan(_canonical(result))


def validate_unit_delivery_plan(plan):
    if isinstance(plan, DltUnitDeliveryPlan):
        plan = plan.as_dict()
    if not isinstance(plan, dict) or plan.get('format') != PLAN_FORMAT:
        raise DltUnitDeliveryError('Expected a ' + PLAN_FORMAT + ' document')
    fresh = compile_unit_delivery(plan.get('request'))
    if _canonical(plan) != fresh._json:
        raise DltUnitDeliveryError('Unit delivery plan differs from its canonical request-derived trace')
    return fresh


def _outcomes(plan, outcomes):
    if (not isinstance(outcomes, dict) or set(outcomes) != {'format', 'plan_sha256', 'operations'}
            or outcomes.get('format') != OUTCOMES_FORMAT):
        raise DltUnitDeliveryError('Expected exact ' + OUTCOMES_FORMAT + ' fields')
    if outcomes['plan_sha256'] != plan['plan_sha256']:
        raise DltUnitDeliveryError('Outcomes belong to a different unit delivery plan')
    rows = outcomes['operations']
    if not isinstance(rows, list) or len(rows) > len(plan['operations']):
        raise DltUnitDeliveryError('Supply at most one outcome per reachable operation')
    known = {row['id']: row for row in plan['operations']}
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('id'), str) or row['id'] not in known or row['id'] in seen:
            raise DltUnitDeliveryError('Outcome operation IDs must be known and unique')
        seen.add(row['id'])
        if row.get('operation_sha256') != known[row['id']]['operation_sha256']:
            raise DltUnitDeliveryError('Outcome operation hash does not match the plan')
        base = {'id', 'operation_sha256', 'outcome'}
        if row.get('outcome') == 'returned':
            valid = set(row) == base
        elif row.get('outcome') == 'raised':
            message = row.get('message')
            valid = (set(row) == base | {'error_class', 'message'} and
                     isinstance(row.get('error_class'), str) and row['error_class'] in ('cgate_command', 'other') and
                     isinstance(message, str) and 1 <= len(message) <= 4096 and
                     not any(ord(c) < 32 or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF for c in message))
        elif row.get('outcome') == 'uncertain':
            valid = (set(row) == base | {'reason'} and isinstance(row.get('reason'), str)
                     and row['reason'] in ('timeout', 'connection_lost', 'unknown'))
        else:
            valid = False
        if not valid:
            raise DltUnitDeliveryError('Outcome requires exact returned, typed raised, or uncertain fields')
    return json.loads(_canonical(rows))


def assess_unit_delivery(plan, outcomes):
    """Reduce supplied original call outcomes; do not infer native acceptance."""
    plan = validate_unit_delivery_plan(plan).as_dict()
    rows = _outcomes(plan, outcomes)
    operations = {row['id']: row for row in plan['operations']}
    cache = {str(key['key']): None for key in plan['request']['keys']}
    reached, skipped, errors, trace = [], [], [], []
    cursor, skip_key = 0, None
    status, next_operation, enabled = 'completed', None, None
    initial_returned, reblock_returned = False, False
    stopped = None
    for event in plan['events']:
        key = event.get('key')
        if skip_key is not None and key == skip_key:
            if event['event'] == 'operation':
                skipped.append(event['id'])
            continue
        if key != skip_key:
            skip_key = None
        if event['event'] != 'operation':
            trace.append(event)
            if event['event'] in ('reset_broadcast', 'mark_broadcast'):
                cache[str(key)] = event['value']
            continue
        operation = operations[event['id']]
        if cursor == len(rows):
            status, next_operation = 'awaiting_outcomes', operation['id']
            break
        row = rows[cursor]
        if row['id'] != operation['id']:
            raise DltUnitDeliveryError('Outcomes must follow the reachable operation order; expected ' + operation['id'])
        cursor += 1
        reached.append(operation['id'])
        trace.append({'event': 'operation_outcome', **row})
        if row['outcome'] == 'returned':
            if operation['kind'] == 'initial_save':
                initial_returned, enabled = True, 1
            elif operation['kind'] == 'reblock':
                reblock_returned, enabled = True, 0
            continue
        if operation['kind'] in ('initial_save', 'reblock'):
            enabled = None
        if row['outcome'] == 'uncertain':
            # A call may have returned and reached its following mark, or raised
            # before that point. Retain true when DYNAMIC already reached it.
            if key is not None and cache[str(key)] is False:
                cache[str(key)] = None
            status, stopped = 'uncertain', operation['id']
            break
        if operation['error_policy'] == 'collect_cgate_command' and row['error_class'] == 'cgate_command':
            errors.append({'key': key, 'operation': operation['id'], 'message': row['message'],
                           'error_class': row['error_class']})
            skip_key = key
            continue
        status, stopped = 'aborted', operation['id']
        break
    if cursor != len(rows):
        raise DltUnitDeliveryError('Outcomes include an operation unreachable after the supplied failure or uncertainty')
    if status == 'completed' and errors:
        status = 'completed_with_label_errors'
    pending = [row['id'] for row in plan['operations'] if row['id'] not in reached and row['id'] not in skipped]
    return {'format': ASSESSMENT_FORMAT, 'plan_sha256': plan['plan_sha256'], 'status': status,
            'outcome_provenance': _PROVENANCE,
            'operation_return_semantics': 'Caller declares the original call returned without raising; no receipt parsing, authentication or acceptance implied',
            'reached_operations': reached, 'skipped_operations': skipped,
            'operations_without_outcomes': pending, 'next_operation': next_operation,
            'stopped_at': stopped, 'trace': trace, 'collected_label_errors': errors,
            'displayed_label_errors': errors[:10], 'per_key_cache_marked': cache,
            'cache_scope': plan['cache_scope'],
            'initial_save_returned': initial_returned, 'reblock_returned': reblock_returned,
            'predicted_enable_dynamic_labels': enabled,
            'dynamic_label_prediction_scope': 'Original model progression from supplied call outcomes; no physical PP readback',
            'reblock_cleanup_verified': False,
            'io_performed': False, 'native_accepted': False, 'device_verified': False,
            'rendering_verified': False, 'persistence_verified': False,
            'recovery': {'automatic_retry': False, 'automatic_resume': False, 'physical_state_known': False,
                         'required': 'Independently inspect programming, labels, session ownership and cache state before creating a fresh plan; do not replay this trace automatically'}}
