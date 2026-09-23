"""Exclusive portable UTF-8 export from an explicit captured-report JSON file."""
from __future__ import annotations

import copy
import math
import os
from pathlib import Path
import stat

from .toolkit_database_csv import COLUMNS, MAX_CAPTURE_BYTES, document_database_csv, loads_capture, validate_columns


def options(commands):
    parser = commands.add_parser('toolkit-database-csv', help='Export captured Toolkit report values as portable UTF-8 CSV offline')
    parser.add_argument('file', type=Path, help='Captured report or bounded cached-projection JSON; generic project XML is not accepted')
    parser.add_argument('--output', required=True, type=Path, help='New UTF-8 file; existing destinations are never overwritten')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--cached-projection', action='store_true',
                      help='Replay the original-backed cached unit/group projection schema before export')
    mode.add_argument('--native-xml-unit', metavar='//PROJECT/NETWORK/p/UNIT',
                      help='Project one captured native DBGETXML Installation snapshot read-only')
    parser.add_argument('--columns', nargs='+', default=None, metavar='COLUMN',
                        help='all (default), or selected names: ' + ', '.join(COLUMNS) + '; output follows original order')
    _selection_options(parser)


def live_options(parser):
    parser.add_argument('unit', metavar='//PROJECT/NETWORK/p/UNIT',
                        help='Unit selected from one read-only DBGETXML project snapshot')
    parser.add_argument('--output', required=True, type=Path,
                        help='New UTF-8 CSV file; existing destinations are never overwritten')
    parser.add_argument('--columns', nargs='+', default=None, metavar='COLUMN',
                        help='all (default), or selected names: ' + ', '.join(COLUMNS) + '; output follows original order')
    _selection_options(parser)
    parser.add_argument('--apply-missing-area', action='store_true',
                        help='For the exact captured B03 shape, back up and persist missing Area13 before export')
    parser.add_argument('--backup-project',
                        help='New C-Gate backup project; required with --apply-missing-area')


def _selection_options(parser):
    parser.add_argument(
        '--toolkit-column-selection', action='store_true',
        help='Load the original Toolkit 32-bit HKCU CSVSelection value; cannot be combined with explicit --columns')
    parser.add_argument(
        '--save-toolkit-column-selection', action='store_true',
        help='Persist the effective columns to the original Toolkit 32-bit HKCU CSVSelection value before export')


def selection_registry_backend():
    from .windows_csv_selection import WindowsCSVSelectionRegistry
    return WindowsCSVSelectionRegistry()


def _resolve_columns(args):
    """Resolve explicit/default/registry columns before any source or network I/O."""
    from .toolkit_database_csv_selection import ToolkitDatabaseCSVSelectionStore

    requested = getattr(args, 'columns', None)
    use_registry = getattr(args, 'toolkit_column_selection', False)
    save_registry = getattr(args, 'save_toolkit_column_selection', False)
    if type(use_registry) is not bool or type(save_registry) is not bool:
        raise ValueError('Toolkit column-selection options must be Boolean')
    if use_registry and requested is not None:
        raise ValueError('--toolkit-column-selection cannot be combined with explicit --columns')
    evidence = {
        'format': 'cbus-toolkit-database-csv-column-resolution-v1',
        'source': 'toolkit_registry' if use_registry else 'command_line',
        'registry_accessed': use_registry or save_registry,
        'load': None, 'save': None, 'effective_columns': None,
    }
    store = None
    try:
        if use_registry:
            store = ToolkitDatabaseCSVSelectionStore(selection_registry_backend())
            args._toolkit_database_csv_selection_store = store
            selection = store.load()
            evidence['load'] = copy.deepcopy(store.last_evidence)
            if not selection.ok_enabled:
                raise ValueError('Toolkit CSV selection contains no recognized selected columns')
            selected = selection.columns
        else:
            selected = validate_columns(
                COLUMNS if requested is None or requested == ['all']
                else tuple(requested))
        if save_registry:
            if store is None:
                store = ToolkitDatabaseCSVSelectionStore(selection_registry_backend())
                args._toolkit_database_csv_selection_store = store
            store.save(selected)
            evidence['save'] = copy.deepcopy(store.last_evidence)
        evidence['effective_columns'] = list(selected)
        args._toolkit_database_csv_selection_evidence = copy.deepcopy(evidence)
        return selected, evidence
    except BaseException as error:
        if store is not None and type(store.last_evidence) is dict:
            key = 'load' if use_registry and evidence['load'] is None else 'save'
            evidence[key] = copy.deepcopy(store.last_evidence)
        evidence['error'] = _failure(error)
        args._toolkit_database_csv_selection_evidence = copy.deepcopy(evidence)
        try:
            error.toolkit_database_csv_column_resolution = evidence
        except BaseException:
            pass
        raise


def _failure(error):
    try:
        message = str(error)
    except BaseException:
        message = '<exception message unavailable>'
    return {'type': type(error).__name__, 'message': message[:4096]}


class DatabaseCSVFileError(ValueError):
    def __init__(self, cause, evidence):
        super().__init__(_failure(cause)['message'])
        self.original_error = cause
        self.details = evidence


class DatabaseCSVLiveError(RuntimeError):
    def __init__(self, cause, *, mutation, output, confirmed):
        self.original_error = cause
        self.details = {
            'native_database_mutated': True,
            'area_group_mutation': copy.deepcopy(mutation),
            'backup_project': mutation['backup_project'],
            'output': str(output),
            'output_bytes_confirmed': confirmed,
            'output_may_be_partial': confirmed > 0,
        }
        super().__init__('CSV output failed after the Area group was saved: ' +
                         _failure(cause)['message'])


class DatabaseCSVFileOperation:
    def __init__(self):
        self.last_error = self.last_cause = self.last_evidence = None

    def run(self, source, *, output, columns, cached_projection=False, native_xml_unit=None,
            selection_evidence=None):
        self.last_error = self.last_cause = self.last_evidence = None
        if type(cached_projection) is not bool:
            raise ValueError('cached_projection must be Boolean')
        if native_xml_unit is not None and type(native_xml_unit) is not str:
            raise ValueError('native_xml_unit must be text or absent')
        if cached_projection and native_xml_unit is not None:
            raise ValueError('Select at most one database CSV input mode')
        input_mode = ('native_xml' if native_xml_unit is not None else
                      'cached_projection' if cached_projection else 'captured_report')
        state = {'operation': 'toolkit-database-csv', 'complete': False, 'stage': 'validate',
                 'input_mode': input_mode,
                 'source': None, 'output': None, 'source_regular_verified': False,
                 'source_identity_verified': False,
                 'source_bytes': 0, 'source_closed': False,
                 'output_create_attempted': False, 'output_created': False,
                 'output_write_attempted': False, 'output_bytes_confirmed': 0,
                 'output_write_complete': False, 'output_fsync_succeeded': False,
                 'output_closed': False, 'output_may_exist': False, 'output_may_be_partial': False,
                 'source_modified': False, 'network_io_attempted': False, 'registry_io_attempted': False,
                 'error': None, 'cleanup_errors': [], 'projection': None, 'report': None,
                 'column_selection': (copy.deepcopy(selection_evidence)
                                      if isinstance(selection_evidence, dict) else None)}
        if isinstance(selection_evidence, dict):
            state['registry_io_attempted'] = bool(selection_evidence.get('registry_accessed'))
        handles = {'source': None, 'output': None}
        primary = None

        def close(name):
            descriptor = handles[name]
            if descriptor is None:
                return
            handles[name] = None  # Do not retry an uncertain failed close.
            os.close(descriptor)
            state[name + '_closed'] = True

        try:
            selected = validate_columns(columns)
            source, output = Path(source), Path(output)
            state.update(source=str(source), output=str(output), stage='source_stat')
            initial = os.lstat(source)
            if not stat.S_ISREG(initial.st_mode):
                raise ValueError('Capture must be a regular file, not a symlink or special file')
            state['stage'] = 'source_open'
            flags = os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0)
            handles['source'] = os.open(source, flags)
            info = os.fstat(handles['source'])
            if not stat.S_ISREG(info.st_mode):
                raise ValueError('Opened capture is not a regular file')
            state['source_regular_verified'] = True
            after_open = os.lstat(source)
            identities = {(item.st_dev, item.st_ino) for item in (initial, info, after_open)}
            if (not stat.S_ISREG(after_open.st_mode) or len(identities) != 1
                    or info.st_ino == 0):
                raise ValueError('Capture path changed while opening, or file identity cannot be verified')
            state['source_identity_verified'] = True
            if not 0 < info.st_size <= MAX_CAPTURE_BYTES:
                raise ValueError('Capture must be nonempty and at most 8 MiB')
            state['stage'] = 'source_read'
            chunks = []
            while True:
                chunk = os.read(handles['source'], min(65536, MAX_CAPTURE_BYTES - state['source_bytes'] + 1))
                if type(chunk) is not bytes:
                    raise TypeError('Capture reader must return bytes')
                if not chunk:
                    break
                state['source_bytes'] += len(chunk)
                if state['source_bytes'] > MAX_CAPTURE_BYTES:
                    raise ValueError('Capture grew beyond 8 MiB while reading')
                chunks.append(chunk)
            state['stage'] = 'source_close'
            close('source')
            raw = b''.join(chunks)
            if native_xml_unit is not None:
                from .toolkit_database_csv_native import loads_native_xml_projection
                state['stage'] = 'project_native_xml_unit'
                projection = loads_native_xml_projection(raw, native_xml_unit, columns=selected)
                state['projection'] = projection.as_dict()
                if not projection.complete or projection.report is None:
                    raise ValueError('Native XML projection stopped: ' + str(projection.stop_reason))
                report = projection.report
            elif cached_projection:
                from .toolkit_database_csv_projection import loads_cached_projection
                state['stage'] = 'project_cached_unit'
                projection = loads_cached_projection(raw, columns=selected)
                state['projection'] = projection.as_dict()
                if not projection.complete or projection.report is None:
                    raise ValueError('Cached projection stopped: ' + str(projection.stop_reason))
                report = projection.report
            else:
                state['stage'] = 'parse_capture'
                units = loads_capture(raw)
                state['stage'] = 'render'
                report = document_database_csv(units, columns=selected)
            state['report'] = report.as_dict()
            payload = memoryview(report.utf8_bytes)
            state.update(stage='output_create', output_create_attempted=True, output_may_exist=True)
            handles['output'] = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0), 0o666)
            state['output_created'] = True
            state['stage'] = 'output_write'
            while state['output_bytes_confirmed'] < len(payload):
                state['output_write_attempted'] = True
                remaining = payload[state['output_bytes_confirmed']:]
                written = os.write(handles['output'], remaining)
                if type(written) is not int or not 0 < written <= len(remaining):
                    raise OSError('Output writer returned an invalid or zero byte count')
                state['output_bytes_confirmed'] += written
            state['output_write_complete'] = True
            state['stage'] = 'output_fsync'
            os.fsync(handles['output'])
            state['output_fsync_succeeded'] = True
            state['stage'] = 'output_close'
            close('output')
            state.update(stage='complete', complete=True)
        except BaseException as error:
            primary = error
        finally:
            for name in ('output', 'source'):
                if handles[name] is None:
                    continue
                try:
                    close(name)
                except BaseException as error:
                    state['cleanup_errors'].append({'resource': name, **_failure(error)})
                    if primary is None:
                        primary = error
        if primary is not None:
            state.update(complete=False, error=_failure(primary),
                         output_may_be_partial=(state['output_created'] or
                             state['output_create_attempted'] and not isinstance(primary, FileExistsError)))
        try:
            self.last_evidence = copy.deepcopy(state)
        except BaseException as error:
            if primary is None:
                primary = error
            state.update(complete=False, error=_failure(primary), evidence_export_failed=True)
            self.last_evidence = {'operation': 'toolkit-database-csv', 'complete': False,
                                  'stage': state['stage'], 'output': state['output'],
                                  'output_may_exist': state['output_may_exist'],
                                  'evidence_export_failed': True}
        self.last_cause = primary
        if primary is not None:
            if not isinstance(primary, Exception):
                self.last_error = primary
                try:
                    primary.toolkit_database_csv_evidence = state
                except BaseException:
                    pass
                raise primary
            error = DatabaseCSVFileError(primary, state)
            self.last_error = error
            raise error from primary
        return state


def run(args):
    if args.area != 'toolkit-database-csv':
        raise ValueError('Unsupported database CSV command')
    operation = DatabaseCSVFileOperation()
    args._toolkit_database_csv_operation = operation
    try:
        columns, selection = _resolve_columns(args)
    except BaseException as error:
        operation.last_error = operation.last_cause = error
        operation.last_evidence = {
            'operation': 'toolkit-database-csv', 'complete': False,
            'stage': 'validate', 'input_mode': None,
            'registry_io_attempted': bool(
                getattr(args, '_toolkit_database_csv_selection_evidence', {}).get(
                    'registry_accessed', False)),
            'column_selection': copy.deepcopy(getattr(
                args, '_toolkit_database_csv_selection_evidence', None)),
            'error': _failure(error),
        }
        raise
    result = operation.run(args.file, output=args.output, columns=columns,
                           cached_projection=args.cached_projection,
                           native_xml_unit=args.native_xml_unit,
                           selection_evidence=selection)
    return result, 0


def live(args, client_factory, ssl_context):
    """Acquire one project snapshot through C-Gate and project it read-only."""
    from .native import NativeDatabase
    from .toolkit_database_csv_native import (_path, native_xml_reply_text,
                                               project_native_xml_unit)

    if args.area != 'cgate' or args.action != 'database-csv':
        raise ValueError('Unsupported live database CSV command')
    selected, selection = _resolve_columns(args)
    project, _network, _unit = _path(args.unit)
    if type(args.apply_missing_area) is not bool:
        raise ValueError('apply_missing_area must be Boolean')
    if args.apply_missing_area:
        if type(args.backup_project) is not str:
            raise ValueError('--apply-missing-area requires --backup-project')
        from .native import _project
        if _project(args.backup_project).upper() == project.upper():
            raise ValueError('Backup project must differ from the edited project')
    elif args.backup_project is not None:
        raise ValueError('--backup-project requires --apply-missing-area')
    if type(args.host) is not str or not args.host:
        raise ValueError('C-Gate host is required')
    if type(args.tls) is not bool:
        raise ValueError('TLS must be an explicit boolean')
    port = (20123 if args.tls else 20023) if args.port is None else args.port
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('C-Gate port must be in 1..65535')
    if type(args.timeout) not in (int, float) or not math.isfinite(args.timeout) or args.timeout <= 0:
        raise ValueError('C-Gate timeout must be positive and finite')
    output = Path(args.output)
    if output.exists():
        raise FileExistsError('Output already exists: ' + str(output))

    with client_factory(args.host, port, timeout=args.timeout, ssl_context=ssl_context) as client:
        mutation = None
        if args.apply_missing_area:
            from .toolkit_database_csv_area import NativeCSVAreaGroups
            manager = NativeCSVAreaGroups(client)
            mutation_result = manager.apply(manager.plan(args.unit),
                                            backup_project=args.backup_project)
            mutation = mutation_result.as_dict()
            xml = mutation_result.final_xml
        else:
            reply = NativeDatabase(client).get('//' + project, xml=True)
            xml = native_xml_reply_text(reply)
        projection = project_native_xml_unit(xml, args.unit, columns=selected)
    if not projection.complete or projection.report is None:
        raise ValueError('Native XML projection stopped: ' + str(projection.stop_reason))

    descriptor = None
    confirmed = 0
    primary = None
    payload = memoryview(projection.report.utf8_bytes)
    try:
        descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                             getattr(os, 'O_BINARY', 0), 0o666)
        while confirmed < len(payload):
            remaining = payload[confirmed:]
            written = os.write(descriptor, remaining)
            if type(written) is not int or not 0 < written <= len(remaining):
                raise OSError('Output writer returned an invalid or zero byte count')
            confirmed += written
        os.fsync(descriptor)
        closing, descriptor = descriptor, None
        os.close(closing)
    except BaseException as error:
        primary = error
    finally:
        if descriptor is not None:
            closing, descriptor = descriptor, None
            try:
                os.close(closing)
            except BaseException as cleanup:
                if primary is None:
                    primary = cleanup
                else:
                    try:
                        primary.database_csv_cleanup_errors = tuple(
                            getattr(primary, 'database_csv_cleanup_errors', ())) + (cleanup,)
                    except BaseException:
                        pass
    if primary is not None:
        if mutation is not None and isinstance(primary, Exception):
            raise DatabaseCSVLiveError(primary, mutation=mutation,
                                       output=output, confirmed=confirmed) from primary
        raise primary
    return {
        'format': 'cbus-toolkit-database-live-csv-v1', 'complete': True,
        'input_mode': 'live_native_xml', 'database_command': 'DBGETXML //' + project,
        'network_io_performed': True, 'physical_device_accessed': False,
        'output': str(output),
        'output_bytes_confirmed': confirmed, 'projection': projection.as_dict(),
        'area_group_mutation': mutation,
        'native_database_mutated': mutation is not None,
        'column_selection': selection,
        'report': projection.report.as_dict(),
    }, 0


def error_payload(error, args):
    is_offline = getattr(args, 'area', None) == 'toolkit-database-csv'
    is_live = (getattr(args, 'area', None) == 'cgate' and
               getattr(args, 'action', None) == 'database-csv')
    if not (is_offline or is_live):
        return {}
    result = {}
    selection = getattr(args, '_toolkit_database_csv_selection_evidence', None)
    if isinstance(selection, dict):
        try:
            result['toolkit_database_csv_column_selection'] = copy.deepcopy(selection)
        except BaseException:
            result['toolkit_database_csv_column_selection'] = {
                'format': 'cbus-toolkit-database-csv-column-resolution-v1',
                'error_export_failed': True,
            }
    operation = getattr(args, '_toolkit_database_csv_operation', None)
    if operation is not None and operation.last_error is error and type(operation.last_evidence) is dict:
        try:
            result['toolkit_database_csv_evidence'] = copy.deepcopy(operation.last_evidence)
        except BaseException:
            result['toolkit_database_csv_evidence'] = {'operation': 'toolkit-database-csv',
                    'complete': False, 'evidence_export_failed': True}
    return result
