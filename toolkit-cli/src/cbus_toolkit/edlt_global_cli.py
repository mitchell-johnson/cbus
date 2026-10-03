"""CLI preparation and finalization for database Global Programming."""
from __future__ import annotations
import json
from pathlib import Path
from dataclasses import dataclass

CATEGORIES = ('key-settings', 'standby', 'colour', 'general')
EVIDENCE = 'edlt_global_programming_evidence'
PREPARATION_EVIDENCE = 'edlt_global_preparation_evidence'


def options(parser, *, native=False):
    parser.add_argument('file', type=Path, nargs='?',
                        help='Complete source PP snapshot; optional with automatic project metadata')
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--metadata', type=Path,
                        help='Source lifecycle cache; complete application cache when --factory-context is used')
    if native:
        source.add_argument('--auto-metadata', action='store_true',
                            help='Derive the source lifecycle and image facts from one current project snapshot')
    else:
        source.add_argument('--project-xml', type=Path,
                            help='Exact native project XML used to derive the source lifecycle and image facts')
        parser.add_argument('--unit', help='Selected //PROJECT/network/p/unit; required with --project-xml')
    parser.add_argument('--project-images-export', type=Path,
                        help='Complete ordered SHA-bound cbus-edlt-project-images-v1 export')
    parser.add_argument('--project-images-sha256', help='SHA-256 of the exact project image export bytes')
    parser.add_argument('--toolkit-dltp-dir', type=Path, help='Toolkit directory containing Images/DLTP')
    parser.add_argument('--toolkit-dltp-sha256', help='SHA-256 of Images/DLTP/Index.txt')
    parser.add_argument('--toolkit-dltp-decode', action='store_true',
                        help='Decode SHA-bound DLTP BMPs in the supported bounded profile')
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
        from .dlt_profiles import refusal
        reason = 'unsupported export format' if values.get('format') != 'cbus-cli-parameters-v1' else refusal(
            'edlt-global-source', *(values.get(k) for k in ('unit_type', 'firmware', 'catalog_number')))
        if reason is not None:
            raise ValueError('eDLT source profile differs from KEYGL5 / 5055EDL / 5.5.00: ' + reason)
        values = values.get('parameters')
        if not isinstance(values, dict): raise ValueError('Source export requires a parameter mapping')
    if factory and any(type(value) is not str for value in values.values()):
        raise ValueError('Factory source export must retain every original raw PP string')
    return values


@dataclass(frozen=True)
class _AutomaticInputs:
    project_xml: str | None
    unit: str
    supplied: dict | None
    order: list | None
    categories: tuple[str, ...]
    providers: dict


def _automatic_inputs(args):
    if getattr(args, 'factory_context', None) is not None:
        raise ValueError('Automatic image metadata does not admit --factory-context')
    native = bool(getattr(args, 'auto_metadata', False))
    unit = getattr(args, 'source_database', None) if native else getattr(args, 'unit', None)
    if unit is None:
        raise ValueError('--auto-metadata requires --source-database' if native
                         else '--project-xml requires --unit')
    from .native_global_programming import _path
    canonical, project, _network, _address = _path(unit)
    if native:
        destinations = tuple(_path(path) for path in args.destination)
        if (not 1 <= len(destinations) <= 64
                or len({path[0].upper() for path in destinations}) != len(destinations)
                or any(path[1].upper() != project.upper() for path in destinations)
                or canonical.upper() in {path[0].upper() for path in destinations}):
            raise ValueError('Automatic destinations must be distinct, separate from the source and in the same project')
    from .edlt_parent_transaction_cli import presentation
    providers = presentation(args)
    providers.pop('display_preferences', None)
    if providers.get('project_images') is not None:
        from .edlt_scene_label_images import check_project_images
        check_project_images(providers['project_images'], project=project)
    text = None
    if not native:
        with args.project_xml.open('rb') as stream:
            raw = stream.read(16 * 1024 * 1024 + 1)
        if len(raw) > 16 * 1024 * 1024:
            raise ValueError('Global Programming project XML exceeds 16 MiB')
        text = raw.decode('utf-8')
    supplied = None if args.file is None else read_parameters(args.file)
    order = read_json(args.parameter_order, limit=128*1024) if args.parameter_order else None
    if order is not None and (type(order) is not list or len(order) != 874
                             or any(type(name) is not str for name in order)
                             or len(set(order)) != 874):
        raise ValueError('Parameter order must contain all 874 unique names exactly once')
    categories = tuple(args.category)
    if len(categories) != len(set(categories)) or any(c not in CATEGORIES for c in categories):
        raise ValueError('Global Programming categories must be distinct known names')
    return _AutomaticInputs(text, unit, supplied, order, categories, providers)


def inputs(args):
    from .edlt_lifecycle import LifecycleCache
    automatic = (getattr(args, 'project_xml', None) is not None
                 or getattr(args, 'auto_metadata', False))
    if automatic:
        return _automatic_inputs(args)
    from .edlt_parent_transaction_cli import presentation
    presentation(args)
    if getattr(args, 'unit', None) is not None:
        raise ValueError('--unit requires --project-xml')
    if args.file is None:
        raise ValueError('Supply the source PP file with --metadata')
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
    if isinstance(data, _AutomaticInputs):
        if data.project_xml is None:
            raise ValueError('Live automatic source preparation requires its native coordinator')
        source = engine.prepare_project_source(data.project_xml, data.unit, **data.providers)
        return _select_automatic(engine, source, data)
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


def _select_automatic(engine, source, data):
    if data.supplied is not None and engine.snapshot(data.supplied) != dict(source.expected):
        raise ValueError('Supplied source PP differs from the exact automatic project snapshot')
    if data.order is not None and tuple(data.order) != source.parameter_order:
        raise ValueError('--parameter-order cannot reorder an automatic project source')
    return engine.select(source, categories=data.categories)


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
    if not isinstance(data, _AutomaticInputs):
        prepare(EdltGlobalProgramming(unit_spec), data, args=args)
    manager, result = None, None
    try:
        with client_factory(args.host, args.port or (20123 if args.tls else 20023),
                            timeout=args.timeout, ssl_context=ssl_context) as client:
            manager = NativeEdltGlobalProgramming(client, unit_spec)
            if isinstance(data, _AutomaticInputs):
                source = manager.prepare_project_source(data.unit, **data.providers)
                payload = _select_automatic(manager.engine, source, data)
            else:
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
