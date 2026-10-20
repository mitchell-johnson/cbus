"""Original Toolkit InputUnit conversion for fresh classic input models.

All admitted source/target models are non-Neo and have HasApplication2=false.
The CoreKey conversion hook therefore leaves aligned parameter strings alone;
only the inherited learning flags and target brightness predicate are applied.
"""
from __future__ import annotations

from .toolkit_conversion_key_to_neo import CLASSIC_ATTRIBUTES, TWEAKER_IMMUTABLE
from .unitspec import UnitSpec


INPUT_TWEAKER = 'TTweakerInputUnit'
INPUT_TYPES = ('KEY1', 'KEY2', 'KEY4', 'KEYBC2', 'KEYBC4', 'BCNC4A', 'BCNC4B')
BRIGHTNESS_TYPES = ('KEY1', 'KEY2', 'KEY4')
FIRMWARE = '1.2.67'
INPUT_ATTRIBUTES = CLASSIC_ATTRIBUTES
INPUT_IMMUTABLE = TWEAKER_IMMUTABLE[:13]

# Single backed-up lifecycle path for P5.06. Only KEY1 -> KEY2 is admitted
# here; every other InputUnit pair keeps its existing plan-only behaviour and
# is explicitly refused by the helpers below. All helpers are pure (no I/O)
# so a lost save/reopen reply can be recovered read-only without replay.
BACKED_UP_SOURCE = 'KEY1'
BACKED_UP_TARGET = 'KEY2'
BACKED_UP_FORMAT = 'cbus-toolkit-input-unit-backed-up-conversion-v1'
# Database metadata that must survive the lifecycle byte-for-byte. These are
# the source PP strings the backed-up path promises to preserve exactly;
# firmware/serial/state/type are never copied and are checked absent.
BACKED_UP_EXACT_FIELDS = ('Application', 'Project', 'UnitAddress', 'UnitName',
                          'GroupAddress', 'IndicatorFunction')
BACKED_UP_JOURNAL_STAGES = ('backup_taken', 'target_created', 'writes_staged',
                            'saved_to_database', 'project_saved', 'reopen_verified')


def validate_backed_up_pair(source_type, target_type):
    """Admit only the single backed-up KEY1 -> KEY2 path; refuse the rest."""
    if source_type != BACKED_UP_SOURCE or target_type != BACKED_UP_TARGET:
        raise ValueError('Backed-up InputUnit lifecycle admits only KEY1 -> KEY2')


def validate_readdress(source_address, target_address):
    """Validate an explicit database readdress without touching any endpoint."""
    for label, value in (('source_address', source_address), ('target_address', target_address)):
        if type(value) is not int or not 0 <= value <= 255:
            raise ValueError(f'{label} must be an int address 0..255')
    if source_address == target_address:
        raise ValueError('Target address must differ from the source address')
    return (source_address, target_address)


def require_backup_snapshot(backup_values, source_values):
    """Require an exact backup snapshot of the source before any mutation."""
    if not isinstance(backup_values, dict) or not isinstance(source_values, dict):
        raise ValueError('Backup and source snapshots must be dicts')
    if not backup_values or not source_values:
        raise ValueError('Backup and source snapshots must not be empty')
    missing = sorted(name for name in BACKED_UP_EXACT_FIELDS if name not in backup_values)
    if missing:
        raise ValueError('Backup snapshot is missing exact metadata: ' + ', '.join(missing))
    mismatches = sorted(name for name in BACKED_UP_EXACT_FIELDS
                        if backup_values.get(name) != source_values.get(name))
    if mismatches:
        raise ValueError('Backup snapshot differs from source for: ' + ', '.join(mismatches))
    if dict(backup_values) != dict(source_values):
        raise ValueError('Backup snapshot must equal the full source snapshot exactly')
    return dict(backup_values)


def require_exact_metadata(source_values, backup_values):
    """Require byte-for-byte metadata preservation; never silently coerce."""
    if not isinstance(source_values, dict) or not isinstance(backup_values, dict):
        raise ValueError('Source and backup snapshots must be dicts')
    problems = []
    for name in BACKED_UP_EXACT_FIELDS:
        if name not in source_values:
            problems.append(name + ' is missing from source')
        elif name not in backup_values:
            problems.append(name + ' is missing from backup')
        elif backup_values[name] != source_values[name]:
            problems.append(name + ' differs between source and backup')
    if problems:
        raise ValueError('Exact metadata mismatch: ' + '; '.join(problems))
    return {name: source_values[name] for name in BACKED_UP_EXACT_FIELDS}


def lifecycle_plan(source_values, *, source_address, target_address, backup_values,
                   target_parameters, project_saved=False):
    """Build the reviewed backed-up plan for KEY1 -> KEY2 without any I/O.

    Validates pair, firmware profile, backup exactness, readdress distinctness
    and the native target-parameter gate up front. The returned plan records
    that project save, reopen verification and read-only recovery are still
    required; it never marks them complete.
    """
    validate_backed_up_pair(BACKED_UP_SOURCE, BACKED_UP_TARGET)
    require_target_firmware(FIRMWARE)
    validate_readdress(source_address, target_address)
    require_backup_snapshot(backup_values, source_values)
    require_exact_metadata(source_values, backup_values)
    if not isinstance(target_parameters, (set, frozenset, list, tuple)):
        raise ValueError('target_parameters must be a collection of native PP names')
    native = set(target_parameters)
    if not native:
        raise ValueError('target_parameters must not be empty')
    missing_native = sorted(name for name in BACKED_UP_EXACT_FIELDS if name not in native)
    if missing_native:
        raise ValueError('Native target is missing parameters: ' + ', '.join(missing_native))
    for name in BACKED_UP_EXACT_FIELDS:
        value = source_values.get(name)
        if not isinstance(value, str) or value == '':
            raise ValueError(f'{name} requires an exact non-empty source string')
    import hashlib as _hashlib
    import json as _json
    digest = _hashlib.sha256(
        _json.dumps({k: backup_values[k] for k in sorted(backup_values)},
                    sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()
    return {
        'format': BACKED_UP_FORMAT,
        'source_type': BACKED_UP_SOURCE, 'target_type': BACKED_UP_TARGET,
        'tweaker': INPUT_TWEAKER, 'firmware': FIRMWARE,
        'source_address': source_address, 'target_address': target_address,
        'backup_sha256': digest,
        'exact_fields': list(BACKED_UP_EXACT_FIELDS),
        'project_saved': bool(project_saved),
        'reopen_verified': False, 'recovery_replay': False,
        'requires': ['project_save', 'reopen_verification', 'read_only_recovery'],
    }


def verify_save_reopen(*, project_saved, reopen_values, expected_values):
    """Verify project save and reopen readback; fail closed on any gap."""
    if project_saved is not True:
        raise ValueError('Project save must be recorded before reopen verification')
    if not isinstance(reopen_values, dict) or not isinstance(expected_values, dict):
        raise ValueError('Reopen and expected values must be dicts')
    if not expected_values:
        raise ValueError('Expected values must not be empty')
    problems = []
    for name in sorted(expected_values):
        if name not in reopen_values:
            problems.append(name + ' is missing from reopen readback')
        elif reopen_values[name] != expected_values[name]:
            problems.append(name + ' differs in reopen readback')
    if problems:
        raise ValueError('Reopen verification failed: ' + '; '.join(problems))
    return True


def recover_from_journal(journal):
    """Read-only recovery summary for a backed-up conversion journal.

    Never replays transport or marks completion silently: every stage must be
    an explicit boolean, unknown stages are refused, and completion requires
    all six stages true.
    """
    if not isinstance(journal, dict):
        raise ValueError('Recovery journal must be a dict')
    unknown = sorted(name for name in journal if name not in BACKED_UP_JOURNAL_STAGES)
    if unknown:
        raise ValueError('Recovery journal has unknown stages: ' + ', '.join(unknown))
    missing = [name for name in BACKED_UP_JOURNAL_STAGES if name not in journal]
    if missing:
        raise ValueError('Recovery journal is missing stages: ' + ', '.join(missing))
    non_bool = sorted(name for name in BACKED_UP_JOURNAL_STAGES
                      if type(journal[name]) is not bool)
    if non_bool:
        raise ValueError('Recovery journal stages must be booleans: ' + ', '.join(non_bool))
    uncertain = [name for name in BACKED_UP_JOURNAL_STAGES if journal[name] is not True]
    complete = not uncertain
    if complete:
        next_action = 'none; conversion is fully verified'
    elif journal['backup_taken'] is not True:
        next_action = 'restore is not allowed; retake an exact backup before any retry'
    elif journal['project_saved'] is not True or journal['reopen_verified'] is not True:
        next_action = 're-read the project and target PP read-only; do not replay writes'
    else:
        next_action = 're-read the target PP read-only; do not replay writes'
    return {'format': BACKED_UP_FORMAT + '+recovery-v1', 'complete': complete,
            'uncertain': list(uncertain), 'replay': False,
            'next_action': next_action}


def require_target_firmware(firmware):
    if firmware != FIRMWARE:
        raise ValueError('InputUnit conversion requires the fresh-target firmware 1.2.67 profile')


def apply_input_hooks(target_type, values, mutable, origin, not_written):
    """Apply original flags without parsing or rewriting aligned value strings."""
    for name in INPUT_IMMUTABLE:
        if name in mutable:
            mutable[name] = False
            not_written[name] = 'InputUnit tweaker makes the attribute immutable'
    # At the exact admitted firmware, CoreKey's lexical >=1.2.63 test is true.
    for name in ('LearnMode', 'LearnAnyApp'):
        mutable[name] = True
        not_written.pop(name, None)
    mutable['LearnedFlag'] = False
    not_written['LearnedFlag'] = 'fresh target model has no original learned-state transition'
    mutable['IndicatorBrightness'] = target_type in BRIGHTNESS_TYPES
    if mutable['IndicatorBrightness']:
        not_written.pop('IndicatorBrightness', None)
    else:
        not_written['IndicatorBrightness'] = 'target brightness property makes the attribute immutable'


def validate_input_spec(unit_type, spec):
    # BCNC4B has this exact catalogue alias in both source and target roles.
    expected_type = 'BCNC4A' if unit_type == 'BCNC4B' else unit_type
    if (unit_type not in INPUT_TYPES or not isinstance(spec, UnitSpec) or spec.unit_type != expected_type
            or spec.filename != expected_type + '.xml' or not spec.supports_version(FIRMWARE)):
        raise ValueError('InputUnit conversion requires matching 1.2.67 source and target specifications')
    shapes = {
        'Application': ('int', 2, 8), 'GroupAddress': ('int', 8, 8),
        'IndicatorFunction': ('int', 4, 2),
        'LearnAnyApp': ('bit', 1, 8), 'LearnMode': ('bit', 1, 8), 'LearnedFlag': ('bit', 1, 8),
    }
    if unit_type in BRIGHTNESS_TYPES:
        shapes['IndicatorBrightness'] = ('int', 1, 8)
    for name, expected in shapes.items():
        parameter = spec.parameters.get(name)
        if parameter is None or (parameter.type, parameter.array_size, parameter.bit_size) != expected:
            raise ValueError(f'Unsupported InputUnit PP shape for {name}')
