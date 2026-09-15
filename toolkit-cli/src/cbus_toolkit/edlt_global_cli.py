"""CLI preparation and finalization for database Global Programming."""
from __future__ import annotations
import json
from pathlib import Path

CATEGORIES = ('key-settings', 'standby', 'colour', 'general')
EVIDENCE = 'edlt_global_programming_evidence'
PREPARATION_EVIDENCE = 'edlt_global_preparation_evidence'


def options(parser, *, native=False):
    parser.add_argument('file', type=Path, help='Complete KEYGL5 5.5.00 / 5055EDL source PP snapshot')
    parser.add_argument('--metadata', type=Path, required=True,
                        help='Source lifecycle cache; complete application cache when --factory-context is used')
    parser.add_argument('--factory-context', type=Path,
                        help='Explicit source/form_project/cached_network_project JSON for the bounded original factory preparation')
    parser.add_argument('--category', choices=CATEGORIES, action='append', default=[],
                        help='Category to copy; repeat for distinct categories; empty selection still writes two CRC fields')
    parser.add_argument('--parameter-order', type=Path, help='JSON array of all source parameter names in original order')
    if native:
        parser.add_argument('--destination', action='append', required=True, help='Existing database unit; repeat for distinct targets')
        parser.add_argument('--source-database', help='Optional original database source path to verify and exclude from destinations')
        parser.add_argument('--exclusive-project', action='store_true',
                            help='Declare that this command has exclusive use of the closed destination project')
        parser.add_argument('--dry-run', action='store_true', help='Read target preconditions and show the plan without applying it')
        parser.add_argument('--backup-project', help='New backup project name; generated automatically when omitted')


def read_json(path, *, limit=1024*1024):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result: raise ValueError('Duplicate JSON key: ' + key)
            result[key] = value
        return result
    def nonfinite(value): raise ValueError('Non-finite JSON number: ' + value)
    with path.open('rb') as stream: raw = stream.read(limit + 1)
    if len(raw) > limit: raise ValueError('Global Programming input exceeds its size limit')
    return json.loads(raw, object_pairs_hook=unique, parse_constant=nonfinite)


def read_parameters(path, *, factory=False):
    values = read_json(path)
    if not isinstance(values, dict): raise ValueError('Source must be a parameter mapping or PP export')
    if factory and set(values) != {'format', 'unit_type', 'firmware', 'catalog_number', 'parameters'}:
        raise ValueError('Factory preparation requires an exact raw source PP export envelope')
    if 'format' in values:
        if values.get('format') != 'cbus-cli-parameters-v1' or tuple(values.get(k) for k in
                ('unit_type', 'firmware', 'catalog_number')) != ('KEYGL5', '5.5.00', '5055EDL'):
            raise ValueError('eDLT source profile differs from KEYGL5 / 5055EDL / 5.5.00')
        values = values.get('parameters')
        if not isinstance(values, dict): raise ValueError('Source export requires a parameter mapping')
    if factory and any(type(value) is not str for value in values.values()):
        raise ValueError('Factory source export must retain every original raw PP string')
    return values


def inputs(args):
    from .edlt_lifecycle import LifecycleCache
    factory_path = getattr(args, 'factory_context', None)
    values = read_parameters(args.file, factory=factory_path is not None)
    context = None
    if factory_path is not None:
        from .edlt_application_cache import ApplicationCache
        from .edlt_global_preparation import GlobalPreparationContext
        document = read_json(factory_path, limit=16*1024)
        if not isinstance(document, dict) or set(document) != {'source', 'form_project', 'cached_network_project'}:
            raise ValueError('Factory context requires exactly source, form_project and cached_network_project')
        context = GlobalPreparationContext(**document)
        metadata = ApplicationCache.from_dict(read_json(args.metadata, limit=16*1024*1024))
        if hasattr(args, 'destination') and getattr(args, 'source_database', None) != context.source:
            raise ValueError('Factory programming requires --source-database to equal the exact factory context source')
    else:
        metadata = LifecycleCache.from_dict(read_json(args.metadata, limit=256*1024))
    order = read_json(args.parameter_order, limit=128*1024) if args.parameter_order else None
    if order is not None and (not isinstance(order, list) or len(order) != 874 or
            any(not isinstance(name, str) for name in order)):
        raise ValueError('Parameter order must be an array of all 874 parameter names')
    categories = tuple(args.category)
    if len(categories) != len(set(categories)) or any(c not in CATEGORIES for c in categories):
        raise ValueError('Global Programming categories must be distinct known names')
    if context is not None:
        if order is not None and tuple(order) != tuple(values):
            raise ValueError('--parameter-order cannot reorder a factory source export')
        return values, metadata, order, categories, context
    return values, metadata, order, categories


def spec(args):
    from .unitspec import UnitSpecStore
    if args.spec_dir is None: raise ValueError('Use --spec-dir or CBUS_UNITSPEC_DIR for decoded vendor specifications')
    return UnitSpecStore(args.spec_dir).load('KEYGL5.xml')


def prepare(engine, data, *, args=None):
    values, metadata, order, categories = data[:4]
    if len(data) == 5:
        from .edlt_global_preparation import EdltGlobalPreparation
        preparer = EdltGlobalPreparation(engine.spec)
        stage = 'factory_preparation'
        try:
            prepared = preparer.prepare_factory(values, metadata=metadata,
                context=data[4], global_engine=engine)
            stage = 'factory_source_bridge'
            source = engine.prepare_factory_source(prepared)
            stage = 'category_selection'
            return engine.select(source, categories=categories)
        except BaseException as error:
            try: evidence = getattr(error, PREPARATION_EVIDENCE, None)
            except BaseException: evidence = None
            if not isinstance(evidence, dict): evidence = preparer.last_evidence
            if isinstance(evidence, dict):
                evidence = {**evidence, 'complete': False, 'cli_failure_stage': stage}
                if args is not None: args._global_programming_evidence = evidence
                wrapped = GlobalCommandError(error, evidence) if isinstance(error, Exception) else error
                try: setattr(wrapped, EVIDENCE, evidence)
                except BaseException: pass
                if wrapped is not error: raise wrapped from error
            raise
    source = engine.prepare_source(values, metadata=metadata, parameter_order=order)
    return engine.select(source, categories=categories)


def offline(args):
    from .edlt_global_programming import EdltGlobalProgramming
    args._global_programming_evidence = None
    return prepare(EdltGlobalProgramming(spec(args)), inputs(args), args=args).as_dict(), 0


class GlobalCommandError(RuntimeError):
    def __init__(self, cause, evidence):
        from .edlt import _apply_error_text
        self.cause = cause
        self.details = {EVIDENCE: evidence}
        for name in ('programming_cleanup_errors', 'cgate_cleanup_errors'):
            try:
                value = getattr(cause, name, None)
                if value is not None: setattr(self, name, value)
            except BaseException: pass
        super().__init__(_apply_error_text(cause))


def error_payload(error, args=None):
    result = {}
    try: evidence = getattr(error, EVIDENCE, None)
    except BaseException: evidence = None
    if not isinstance(evidence, dict):
        try: evidence = getattr(error, PREPARATION_EVIDENCE, None)
        except BaseException: evidence = None
    if not isinstance(evidence, dict): evidence = getattr(args, '_global_programming_evidence', None)
    if isinstance(evidence, dict): result[EVIDENCE] = evidence
    return result


def native(args, client_factory, ssl_context):
    from .native_global_programming import NativeEdltGlobalProgramming
    args._global_programming_evidence = None
    data, unit_spec = inputs(args), spec(args)
    if not args.exclusive_project: raise ValueError('Global Programming requires --exclusive-project for the closed destination project')
    if args.dry_run and args.backup_project: raise ValueError('--backup-project applies only when saving; omit it for --dry-run')
    # Source validation is local and precedes opening a transport. Reprepare on
    # the coordinator's own engine after connecting to preserve issued identity.
    from .edlt_global_programming import EdltGlobalProgramming
    prepare(EdltGlobalProgramming(unit_spec), data, args=args)
    manager, result = None, None
    try:
        with client_factory(args.host, args.port or (20123 if args.tls else 20023),
                            timeout=args.timeout, ssl_context=ssl_context) as client:
            manager = NativeEdltGlobalProgramming(client, unit_spec)
            payload = prepare(manager.engine, data, args=args)
            plan = manager.plan(payload, tuple(args.destination), source_database=args.source_database,
                                exclusive_project=args.exclusive_project)
            result = plan.as_dict() if args.dry_run else manager.apply(plan, backup_project=args.backup_project).as_dict()
            args._global_programming_evidence = result
        return result, 0
    except BaseException as error:
        if result is not None:
            evidence = {**result, 'operation_completed': False, 'failure_phase': 'connection_cleanup',
                        'automatic_retries': 0, 'rollback_performed': False}
        else:
            try: evidence = getattr(error, EVIDENCE, None)
            except BaseException: evidence = None
            if not isinstance(evidence, dict) and manager is not None:
                evidence = getattr(manager, 'last_evidence', None)
        if isinstance(evidence, dict):
            args._global_programming_evidence = evidence
            wrapped = GlobalCommandError(error, evidence) if result is not None and isinstance(error, Exception) else error
            try: setattr(wrapped, EVIDENCE, evidence)
            except BaseException: pass
            if wrapped is not error: raise wrapped from error
        raise
