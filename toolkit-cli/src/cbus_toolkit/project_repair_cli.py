"""Bounded file boundary for portable project repair; existing files are never replaced."""
from __future__ import annotations

import copy
import os
from pathlib import Path
import stat

from .project_repair import DEFAULT_MAX_BYTES, ProjectRepairError, repair_project_xml


def options(commands):
    parser = commands.add_parser('repair', help='Repair project XML into a new file without C-Gate or hardware access')
    parser.add_argument('file', type=Path)
    parser.add_argument('--output', type=Path, help='New output path; an existing file is never overwritten')
    parser.add_argument('--dry-run', action='store_true', help='Compute repair evidence without creating an output file')
    parser.add_argument('--line-ending', choices=('lf', 'crlf'), default='lf')
    parser.add_argument('--max-bytes', type=int, default=DEFAULT_MAX_BYTES)


def _failure(error):
    try:
        message = str(error)
    except BaseException:
        message = '<exception message unavailable>'
    return {'type': type(error).__name__, 'message': message[:4096]}


class ProjectRepairFileError(ValueError):
    def __init__(self, cause, evidence):
        super().__init__(_failure(cause)['message'])
        self.original_error = cause
        self.details = evidence


class ProjectRepairFileOperation:
    def __init__(self):
        self.last_error = self.last_cause = self.last_evidence = None

    def run(self, source, *, output=None, dry_run=False, line_ending='lf', max_bytes=DEFAULT_MAX_BYTES):
        self.last_error = self.last_cause = self.last_evidence = None
        state = {'operation': 'project-repair', 'complete': False, 'stage': 'validate',
                 'source': None, 'output': None, 'dry_run': dry_run if type(dry_run) is bool else None,
                 'source_regular_verified': False, 'source_bytes': 0, 'source_closed': False,
                 'output_create_attempted': False, 'output_created': False,
                 'output_write_attempted': False, 'output_bytes_confirmed': 0,
                 'output_write_complete': False, 'output_fsync_succeeded': False,
                 'output_closed': False, 'output_may_exist': False, 'output_may_be_partial': False,
                 'source_modified': False, 'native_load_verified': False,
                 'physical_io_attempted': False, 'error': None, 'cleanup_errors': [], 'repair': None,
                 'repair_failure_stage': None}
        handles = {'source': None, 'output': None}
        primary = None

        def close(name):
            handle = handles[name]
            if handle is None:
                return
            handles[name] = None  # A failed close is uncertain; never retry it.
            os.close(handle)
            state[name + '_closed'] = True

        try:
            if type(dry_run) is not bool:
                raise ValueError('dry_run must be a boolean')
            if type(max_bytes) is not int or not 1 <= max_bytes <= 64 * 1024 * 1024:
                raise ValueError('max_bytes must be an integer from 1 to 67108864')
            if line_ending not in ('lf', 'crlf'):
                raise ValueError('line_ending must be lf or crlf')
            if output is None and not dry_run:
                raise ValueError('--output is required unless --dry-run is selected')
            source = Path(source)
            output = Path(output) if output is not None else None
            state.update(source=str(source), output=str(output) if output is not None else None)
            state['stage'] = 'source_stat'
            # Reject devices, FIFOs and symlinks before opening. The descriptor
            # check also handles path replacement; nonblocking open avoids FIFO waits.
            if not stat.S_ISREG(os.lstat(source).st_mode):
                raise ValueError('Source must be a regular file, not a symlink or special file')
            state['stage'] = 'source_open'
            flags = os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0)
            handles['source'] = os.open(source, flags)
            info = os.fstat(handles['source'])
            if not stat.S_ISREG(info.st_mode):
                raise ValueError('Opened source is not a regular file')
            state['source_regular_verified'] = True
            if info.st_size > max_bytes:
                raise ValueError('Source exceeds max_bytes')
            state['stage'] = 'source_read'
            chunks = []
            while True:
                chunk = os.read(handles['source'], min(65536, max_bytes - state['source_bytes'] + 1))
                if type(chunk) is not bytes:
                    raise TypeError('Source reader must return bytes')
                if not chunk:
                    break
                state['source_bytes'] += len(chunk)
                if state['source_bytes'] > max_bytes:
                    raise ValueError('Source grew beyond max_bytes while reading')
                chunks.append(chunk)
            state['stage'] = 'source_close'
            close('source')
            state['stage'] = 'repair'
            repaired = repair_project_xml(b''.join(chunks), line_ending=line_ending, max_bytes=max_bytes)
            state['repair'] = repaired.as_dict()
            if not dry_run:
                state.update(stage='output_create', output_create_attempted=True, output_may_exist=True)
                handles['output'] = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0), 0o666)
                state['output_created'] = True
                state['stage'] = 'output_write'
                payload = memoryview(repaired.repaired_xml)
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
            if isinstance(error, ProjectRepairError):
                try:
                    failure_stage = error.stage
                except BaseException:
                    failure_stage = None
                if type(failure_stage) is str:
                    state['repair_failure_stage'] = failure_stage
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
            state['complete'] = False
            state['error'] = _failure(primary)
            state['output_may_be_partial'] = state['output_create_attempted']
        try:
            self.last_evidence = copy.deepcopy(state)
        except BaseException as error:
            if primary is None:
                primary = error
            state.update(complete=False, error=_failure(primary), evidence_export_failed=True)
            self.last_evidence = {'operation': 'project-repair', 'complete': False,
                                  'stage': state['stage'], 'evidence_export_failed': True,
                                  'output_may_exist': state['output_may_exist']}
        self.last_cause = primary
        if primary is not None:
            if not isinstance(primary, Exception):
                self.last_error = primary
                try:
                    primary.project_repair_evidence = state
                except BaseException:
                    pass
                raise primary
            error = ProjectRepairFileError(primary, state)
            self.last_error = error
            raise error from primary
        return state


def run(args):
    operation = ProjectRepairFileOperation()
    args._project_repair_operation = operation
    result = operation.run(args.file, output=args.output, dry_run=args.dry_run,
                           line_ending=args.line_ending, max_bytes=args.max_bytes)
    return result, 0


def error_payload(error, args):
    if getattr(args, 'area', None) != 'project' or getattr(args, 'action', None) != 'repair':
        return {}
    operation = getattr(args, '_project_repair_operation', None)
    if operation is not None and operation.last_error is error and isinstance(operation.last_evidence, dict):
        try:
            return {'project_repair_evidence': copy.deepcopy(operation.last_evidence)}
        except BaseException:
            return {'project_repair_evidence': {'operation': 'project-repair', 'complete': False,
                                                'evidence_export_failed': True}}
    return {}
