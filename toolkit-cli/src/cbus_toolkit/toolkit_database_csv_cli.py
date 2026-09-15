"""Exclusive portable UTF-8 export from an explicit captured-report JSON file."""
from __future__ import annotations

import copy
import os
from pathlib import Path
import stat

from .toolkit_database_csv import COLUMNS, MAX_CAPTURE_BYTES, document_database_csv, loads_capture, validate_columns


def options(commands):
    parser = commands.add_parser('toolkit-database-csv', help='Export captured Toolkit report values as portable UTF-8 CSV offline')
    parser.add_argument('file', type=Path, help='Captured report JSON; generic project XML is not accepted')
    parser.add_argument('--output', required=True, type=Path, help='New UTF-8 file; existing destinations are never overwritten')
    parser.add_argument('--columns', nargs='+', default=['all'], metavar='COLUMN',
                        help='all (default), or selected names: ' + ', '.join(COLUMNS) + '; output follows original order')


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


class DatabaseCSVFileOperation:
    def __init__(self):
        self.last_error = self.last_cause = self.last_evidence = None

    def run(self, source, *, output, columns):
        self.last_error = self.last_cause = self.last_evidence = None
        state = {'operation': 'toolkit-database-csv', 'complete': False, 'stage': 'validate',
                 'source': None, 'output': None, 'source_regular_verified': False,
                 'source_identity_verified': False,
                 'source_bytes': 0, 'source_closed': False,
                 'output_create_attempted': False, 'output_created': False,
                 'output_write_attempted': False, 'output_bytes_confirmed': 0,
                 'output_write_complete': False, 'output_fsync_succeeded': False,
                 'output_closed': False, 'output_may_exist': False, 'output_may_be_partial': False,
                 'source_modified': False, 'network_io_attempted': False, 'registry_io_attempted': False,
                 'error': None, 'cleanup_errors': [], 'report': None}
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
            state['stage'] = 'parse_capture'
            units = loads_capture(b''.join(chunks))
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
    columns = COLUMNS if args.columns == ['all'] else tuple(args.columns)
    operation = DatabaseCSVFileOperation()
    args._toolkit_database_csv_operation = operation
    result = operation.run(args.file, output=args.output, columns=columns)
    return result, 0


def error_payload(error, args):
    if getattr(args, 'area', None) != 'toolkit-database-csv':
        return {}
    operation = getattr(args, '_toolkit_database_csv_operation', None)
    if operation is not None and operation.last_error is error and type(operation.last_evidence) is dict:
        try:
            return {'toolkit_database_csv_evidence': copy.deepcopy(operation.last_evidence)}
        except BaseException:
            return {'toolkit_database_csv_evidence': {'operation': 'toolkit-database-csv',
                    'complete': False, 'evidence_export_failed': True}}
    return {}
