"""CLI options and save/cleanup evidence for retained eDLT control editors."""
from __future__ import annotations
import json
from contextlib import contextmanager
from pathlib import Path

from .edlt_application_cache import ApplicationCache

MAX_CACHE_BYTES = 16 * 1024 * 1024


def options(parser, kind):
    parser.add_argument('--metadata', type=Path, required=True, help='Ordered application/group cache and lifecycle facts')
    if kind == 'applications':
        parser.add_argument('--select', action='append', default=[], metavar='FIELD=ADDRESS',
            help='Ordered primary/secondary selection; repeat to specify intermediate choices')
    elif kind == 'corridor':
        parser.add_argument('--edit', action='append', default=[], metavar='FIELD=VALUE',
            help='Ordered link_group, office_group, corridor_group or seconds control edit')
    else: raise ValueError('Unknown eDLT ordered control editor')


def editor(args, kind):
    from .unitspec import UnitSpecStore
    if args.spec_dir is None:
        raise ValueError('Use --spec-dir or CBUS_UNITSPEC_DIR for decoded vendor specifications')
    spec = UnitSpecStore(args.spec_dir).load('KEYGL5.xml')
    if kind == 'applications':
        from .edlt_applications import EdltApplications
        return EdltApplications(spec)
    if kind == 'corridor':
        from .edlt_corridor import EdltCorridor
        return EdltCorridor(spec)
    raise ValueError('Unknown eDLT ordered control editor')


def settings(args, kind):
    if kind == 'applications':
        from .edlt_applications import ApplicationEdit as Edit
        raw_edits = args.select
    elif kind == 'corridor':
        from .edlt_corridor import CorridorEdit as Edit
        raw_edits = args.edit
    else: raise ValueError('Unknown eDLT ordered control editor')
    if len(raw_edits) > 64: raise ValueError('Use at most 64 ordered control edits')
    edits = []
    for raw in raw_edits:
        name, separator, value = raw.partition('=')
        if not separator or not name or not value or len(raw) > 128:
            raise ValueError('Control edits must use FIELD=VALUE')
        try: number = int(value, 16 if value.lstrip("+-").lower().startswith("0x") else 10)
        except ValueError as error: raise ValueError('Control values must be decimal or 0x-prefixed integers') from error
        edits.append(Edit(name, number))
    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result: raise ValueError('Duplicate key in ordered control metadata: ' + key)
            result[key] = value
        return result
    with args.metadata.open('rb') as source: raw = source.read(MAX_CACHE_BYTES + 1)
    if len(raw) > MAX_CACHE_BYTES: raise ValueError('Ordered control metadata exceeds 16 MiB')
    return {'cache': ApplicationCache.from_dict(json.loads(raw, object_pairs_hook=unique_keys)), 'edits': tuple(edits)}


class OrderedControlCommandError(RuntimeError):
    """An edit staged successfully, but readback, save or cleanup then failed."""
    def __init__(self, cause, evidence):
        from .edlt import _apply_error_text
        self.cause = cause
        self.details = {'saved': evidence['saved'], 'save_attempted': evidence['save_attempted'],
                        'save_outcome_uncertain': evidence['save_outcome_uncertain'],
                        'rollback_performed': False}
        for name in ('programming_cleanup_errors', 'cgate_cleanup_errors'):
            try:
                value = getattr(cause, name, None)
                if value is not None: setattr(self, name, value)
            except BaseException: pass
        super().__init__(_apply_error_text(cause))


def program(context, editor, settings, *, kind, destination, explicit_destination, dry_run, state=None):
    """Keep completed staging evidence through final readback/save and cleanup.

    Never replay or roll back a save whose reply may have been lost. A confirmed
    save remains confirmed if the later programming-context cleanup fails.
    """
    result = None
    phase, save_attempted, save_confirmed = 'enter', False, False
    def remember(evidence):
        editor.last_evidence = evidence
        if state is not None: state.update(evidence=evidence, kind=kind)
    try:
        with context as session:
            phase = 'configure'
            editor.last_evidence = None
            result = editor.configure(session, **settings)
            phase = 'readback'
            values = session.values()
            saved = None
            if not dry_run:
                phase, save_attempted = 'save', True
                saved = session.save(destination) if explicit_destination else session.save_to_source()
                save_confirmed = saved is not None
            phase = 'cleanup'
        remember({**result, 'operation_completed': True, 'staging_verified': True,
                  'attempted_parameters': list(result['changes']), 'saved': save_confirmed,
                  'save_attempted': save_attempted, 'save_outcome_uncertain': False,
                  'destination': destination, 'rollback_performed': False, 'pp_state_uncertain': False})
        return {**result, 'parameters': values, 'saved': save_confirmed,
                'destination': destination if saved else None}
    except BaseException as error:
        # configure() owns its own partial-write evidence and rollback policy.
        if result is None:
            # Module-stage interruptions may reject exception attributes. Keep
            # only evidence created by this configure call, never an old edit.
            evidence = editor.last_evidence if phase == 'configure' else None
            if isinstance(evidence, dict):
                remember({**evidence, 'failure_phase': 'configure', 'operation_completed': False,
                          'staging_verified': bool(evidence.get('verified', False)),
                          'saved': False, 'save_attempted': False, 'save_outcome_uncertain': False,
                          'destination': destination})
            raise
        evidence = {**result, 'failure_phase': phase, 'operation_completed': False,
                    'staging_verified': True, 'attempted_parameters': list(result['changes']),
                    'saved': save_confirmed, 'save_attempted': save_attempted,
                    'save_outcome_uncertain': save_attempted and not save_confirmed,
                    'rollback_performed': False, 'pp_state_uncertain': True, 'destination': destination}
        remember(evidence)
        wrapped = OrderedControlCommandError(error, evidence) if isinstance(error, Exception) else error
        try: setattr(wrapped, 'edlt_' + kind + '_evidence', evidence)
        except BaseException: pass
        if wrapped is error: raise
        raise wrapped from error


@contextmanager
def connection_guard(args):
    """Retain a completed ordered command if the enclosing socket close fails."""
    if args.action != 'unit' or args.remote_action not in ('edlt-applications', 'edlt-corridor', 'edlt-blank', 'edlt-reset-controls', 'edlt-scene-manager', 'edlt-scene-capture'):
        yield
        return
    state = args._ordered_control_state = {}
    try:
        yield
    except BaseException as error:
        evidence = state.get('evidence')
        if evidence is None: raise
        completed = evidence.get('operation_completed')
        if completed:
            evidence = {**evidence, 'operation_completed': False, 'failure_phase': 'connection_cleanup'}
            state['evidence'] = evidence
        wrapped = (OrderedControlCommandError(error, evidence)
                   if completed and isinstance(error, Exception) else error)
        try: setattr(wrapped, 'edlt_' + state['kind'] + '_evidence', evidence)
        except BaseException: pass
        if wrapped is error: raise
        raise wrapped from error
