"""Exact-profile Windows Framework registry reads in an owned x86 process.

Construction is inert. Only explicit, scoped queries reach Registry.GetValue.
The checked worker provenance is operational evidence, not host attestation.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import time
import uuid

from . import _toolkit_update_registry_conditions as leaves
from .toolkit_update_conditions import MAX_JSON_BYTES, _Outcome, _ascii, _unsupported
from .toolkit_update_metadata import _json, _error
from ._windows_condition_registry_worker import SOURCE

SCOPE_FORMAT = 'cbus-toolkit-registry-read-scope-v1'
QUERY_FORMAT = 'cbus-toolkit-registry-queries-v1'
COMPILER = r'C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe'
COMPILER_SHA256 = '012e8cd8adff0c439a90ffd22c0e33efeb6fbc8cf660d52b4858d310649382fa'
RUNTIME = r'C:\Windows\Microsoft.NET\Framework\v4.0.30319\mscorlib.dll'
RUNTIME_SHA256 = '93d46bdac1664dba87641925572c789d71a21bb01dc7c7e5aa99c0eca8335e5e'
RUNTIME_MVID = '5f1a0e73-9147-408f-b533-0f636e32558c'
PROVIDER_IL_SHA256 = 'c0363d229d83fb9ca8d8c88ef77816bbd3971cec725fafb68ef96d1486024b72'
MAX_FRAME = 16384


def _query(value):
    if type(value) is not dict or set(value) != {'path', 'entry', 'default'}:
        _unsupported('A registry query requires exactly path, entry and default')
    path = leaves._path(value['path'], expanded=True)
    entry = leaves._entry(value['entry'])
    default = leaves._primitive(value['default'])
    if default not in (('System.Int32', 1), ('System.String', leaves.SENTINEL)):
        _unsupported('Registry query default must be one of the two original typed constants')
    return path, entry, default


def _query_dict(key):
    return {'path': key[0], 'entry': key[1], 'default': {'kind': key[2][0], 'value': key[2][1]}}


def _queries(raw, format_name):
    data = _json(raw, limit=MAX_JSON_BYTES, depth_limit=12); _ascii(data)
    if (type(data) is not dict or set(data) != {'format', 'queries'} or data['format'] != format_name
            or type(data['queries']) is not list or not 1 <= len(data['queries']) <= 8):
        _unsupported('Registry scope/query input requires its exact format and one to eight queries')
    return tuple(_query(item) for item in data['queries'])


@dataclass(frozen=True)
class RegistryReadScope:
    """An explicit finite allowlist, never a claim that values were observed."""
    _json_bytes: bytes = field(repr=False)

    @classmethod
    def from_json(cls, raw: bytes):
        keys = _queries(raw, SCOPE_FORMAT)
        if len(set(keys)) != len(keys):
            _unsupported('Read scope query identities must be unique')
        return cls(bytes(raw))

    def _keys(self):
        # Revalidate constructible/frozen-bypassed objects before using them.
        if type(self) is not RegistryReadScope or type(self._json_bytes) is not bytes:
            raise ValueError('Invalid registry scope object')
        keys = _queries(self._json_bytes, SCOPE_FORMAT)
        if len(set(keys)) != len(keys):
            raise ValueError('Duplicate registry scope query')
        return keys

    def as_dict(self):
        return {'format': SCOPE_FORMAT, 'queries': [_query_dict(key) for key in self._keys()]}


def _b64(value):
    return base64.b64encode(value.encode('utf-8')).decode('ascii')


def _unb64(value, maximum=512):
    if type(value) is not str or len(value) > maximum * 8:
        raise ValueError('Base64 field exceeds bound')
    raw = base64.b64decode(value, validate=True)
    if base64.b64encode(raw).decode('ascii') != value:
        raise ValueError('Noncanonical base64 field')
    result = raw.decode('utf-8', errors='strict')
    if len(result) > maximum or any(0xD800 <= ord(char) <= 0xDFFF for char in result):
        raise ValueError('Decoded field exceeds domain')
    return result


def _wire(key):
    return '\t'.join((_b64(key[0]), _b64(key[1]), 'I' if key[2][0] == 'System.Int32' else 'S', _b64(str(key[2][1]))))


def _ordinary(path, *, directory=False):
    info = os.lstat(path)
    if (stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400
            or not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))):
        raise ValueError('Registry worker path is not an ordinary ' + ('directory' if directory else 'file'))


def _read(path, limit=MAX_FRAME, *, digest=False):
    """Nonblocking bounded descriptor read, preserving a first read/close failure."""
    _ordinary(path)
    descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NONBLOCK', 0)
                         | getattr(os, 'O_NOFOLLOW', 0))
    failure = None
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError('Registry worker input exceeds regular-file bound')
        value = hashlib.sha256() if digest else bytearray()
        total = 0
        while True:
            part = os.read(descriptor, min(65536, limit - total + 1))
            if not part:
                break
            total += len(part)
            if total > limit:
                raise ValueError('Registry worker input grew beyond bound')
            value.update(part) if digest else value.extend(part)
        return value.hexdigest() if digest else bytes(value)
    except BaseException as error:
        failure = error; raise
    finally:
        try:
            os.close(descriptor)
        except BaseException:
            if failure is None:
                raise


def _publish(path, data):
    if type(data) is not bytes or len(data) > MAX_FRAME:
        raise ValueError('Registry worker publication exceeds bound')
    temporary = path.with_name(path.name + '.host-partial')
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0), 0o600)
    failure = None
    try:
        offset = 0
        while offset < len(data):
            count = os.write(descriptor, data[offset:])
            if count <= 0:
                raise OSError('Incomplete registry worker request write')
            offset += count
        os.fsync(descriptor)
    except BaseException as error:
        failure = error; raise
    finally:
        try:
            os.close(descriptor)
        except BaseException:
            if failure is None:
                raise
    if path.exists():
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise ValueError('Registry worker publication target already exists')
    # Claim the final name atomically: linking fails when another publisher
    # won the race, so a concurrently created target is never overwritten.
    # No rename fallback is attempted: POSIX rename would silently replace a
    # concurrent winner and Windows rename would fail while leaking the
    # temporary file, both breaking the atomic-claim invariant.
    try:
        os.link(temporary, path)
    except FileExistsError:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise ValueError('Registry worker publication target already exists')
    except OSError as error:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise OSError('Registry worker publication requires a hard-link capable directory') from error
    try:
        os.unlink(temporary)
    except OSError:
        pass


@dataclass(frozen=True, eq=False)
class RegistryObservation:
    _document: str = field(repr=False)

    def as_dict(self):
        return json.loads(self._document)


@dataclass(frozen=True)
class RegistryCaptureReport:
    _document: str = field(repr=False)
    cause: BaseException | None = field(default=None, repr=False, compare=False)

    def as_dict(self):
        return json.loads(self._document)

    def context_v2(self, *, files=()):
        document = self.as_dict()
        if not document.get('capture_completed') or document.get('cause'):
            raise ValueError('Only completed captures can export supplied facts')
        seen = set(); records = []
        for observation in document['observations']:
            key = _query(observation['query'])
            if key in seen:
                raise ValueError('Repeated query observations cannot be represented by a v2 fact snapshot')
            seen.add(key)
            records.append({**observation['query'], 'result': observation['result']})
        result = {'format': leaves.CONTEXT_FORMAT, 'culture': 'invariant-ascii', 'files': list(files),
                  'registry_provider': leaves.PROVIDER, 'registry_reads': records}
        from .toolkit_update_conditions import _facts, CONTEXT_FORMAT
        _ascii(result); leaves.facts(result)
        _facts({'format': CONTEXT_FORMAT, 'culture': 'invariant-ascii', 'files': result['files']})
        return result


class WindowsConditionRegistry:
    """Single-use session with an exact finite scope and no query retries.

    Artifacts are retained in a new directory beneath workspace_parent (or the
    ordinary temporary directory). Closing terminates/reaps only owned children;
    it never changes registry keys. The initial profile requires the captured
    Framework compiler/runtime bytes, not merely a compatible version number.
    """
    def __init__(self, *, compiler_path, scope: RegistryReadScope, workspace_parent=None, timeout=60.0):
        if type(scope) is not RegistryReadScope:
            raise ValueError('An exact RegistryReadScope is required')
        if type(timeout) not in (int, float) or not 0 < timeout <= 60:
            raise ValueError('Registry session timeout must be in (0, 60] seconds')
        self._scope = scope._keys()
        self._compiler = os.fspath(compiler_path)
        self._parent = None if workspace_parent is None else os.fspath(workspace_parent)
        self._timeout = float(timeout)
        self._directory = None; self._process = None; self._compiler_process = None
        self._handles = []; self._deadline = None; self._nonce = None; self._helper_hash = None
        self._closed = False; self._terminal = False; self._failure = None; self._issued = {}
        self._proof = None; self._records = []; self._cleanup = []
        self.last_report = None

    def _remember(self, cause=None, *, completed=False):
        document = {'profile': leaves.PROVIDER, 'scope': [_query_dict(key) for key in self._scope],
            'capture_completed': completed, 'atomic_machine_snapshot': False,
            'registry_provider_identity_verified': self._proof is not None,
            'provider_proof': self._proof, 'observations': self._records,
            'cleanup': self._cleanup, 'closed': self._closed,
            'artifact_directory': None if self._directory is None else str(self._directory),
            'registry_writes_performed': False, 'network_accessed': False,
            'runtime_internal_syscalls_instrumented': False,
            'provenance_is_host_attestation': False, 'cause': None if cause is None else _error(cause)}
        try:
            self.last_report = RegistryCaptureReport(json.dumps(document, ensure_ascii=True, allow_nan=False), cause)
        except BaseException as error:
            self.last_report = RegistryCaptureReport('{"capture_completed":false,"evidence_export_failed":true}', cause or error)
            if cause is None:
                raise
        return self.last_report

    def _remaining(self):
        remaining = self._deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Registry observation session deadline expired')
        return remaining

    def _wait_file(self, name):
        path = self._directory / name
        while True:
            self._remaining()
            try:
                raw = _read(path)
            except FileNotFoundError:
                if self._process.poll() is not None:
                    # One final read resolves a publication immediately before exit.
                    try:
                        raw = _read(path)
                    except FileNotFoundError:
                        raise RuntimeError('Registry worker exited before publishing ' + name) from None
                    break
                time.sleep(min(0.01, self._remaining()))
            else:
                break
        self._remaining()
        return raw.decode('ascii', errors='strict')

    def _log(self, name):
        handle = open(self._directory / name, 'xb')
        self._handles.append(handle)
        return handle

    def _start(self):
        if os.name != 'nt':
            raise OSError('Exact Framework registry observation requires Windows')
        if os.path.normcase(os.path.abspath(self._compiler)) != os.path.normcase(COMPILER):
            raise ValueError('Compiler path is outside the captured Framework profile')
        self._deadline = time.monotonic() + self._timeout
        for path, expected in ((self._compiler, COMPILER_SHA256), (RUNTIME, RUNTIME_SHA256)):
            if _read(path, 64 * 1024 * 1024, digest=True) != expected:
                raise ValueError('Framework compiler/runtime hash is outside the captured profile')
        parent = Path(self._parent if self._parent is not None else tempfile.gettempdir()).absolute()
        for part in (parent, *parent.parents):
            _ordinary(part, directory=True)
        self._directory = Path(tempfile.mkdtemp(prefix='cbus-registry-observation-', dir=parent))
        self._nonce = uuid.uuid4().hex
        source = self._directory / 'RegistryWorker.cs'; executable = self._directory / 'RegistryWorker.exe'
        _publish(source, SOURCE.encode('ascii'))
        _publish(self._directory / 'scope', '\n'.join(_wire(key) for key in self._scope).encode('ascii'))
        out, err = self._log('compile.stdout'), self._log('compile.stderr')
        command = [self._compiler, '/noconfig', '/nologo', '/nostdlib+', '/target:exe', '/platform:x86',
                   '/optimize+', '/r:' + RUNTIME, '/out:' + str(executable), str(source)]
        self._compiler_process = subprocess.Popen(command, cwd=self._directory, stdin=subprocess.DEVNULL,
            stdout=out, stderr=err, close_fds=True, shell=False)
        code = self._compiler_process.wait(timeout=self._remaining())
        if code != 0:
            raise RuntimeError('Framework registry worker compilation failed with exit ' + str(code))
        for path, expected in ((self._compiler, COMPILER_SHA256), (RUNTIME, RUNTIME_SHA256)):
            if _read(path, 64 * 1024 * 1024, digest=True) != expected:
                raise ValueError('Framework input changed during compilation')
        self._helper_hash = _read(executable, 1024 * 1024, digest=True)
        out, err = self._log('worker.stdout'), self._log('worker.stderr')
        self._process = subprocess.Popen([str(executable), str(self._directory), self._nonce],
            cwd=self._directory, stdin=subprocess.DEVNULL, stdout=out, stderr=err, close_fds=True, shell=False)
        self._proof = self._ready(self._wait_file('ready'), executable)

    def _ready(self, text, executable):
        fields = text.split('\t')
        if len(fields) != 12:
            raise ValueError('Registry ready record shape mismatch')
        if (fields[:4] != ['READY1', self._nonce, str(self._process.pid), '4']
                or fields[5:9] != [RUNTIME_SHA256, RUNTIME_MVID, '060000f3', PROVIDER_IL_SHA256]
                or _unb64(fields[4], 1024).lower() != RUNTIME.lower()
                or _unb64(fields[9], 1024).lower() != str(executable).lower()
                or fields[10] != self._helper_hash):
            raise ValueError('Registry worker/runtime identity correlation failed')
        sid = _unb64(fields[11], 256)
        if re.fullmatch(r'S-1-[0-9]+(?:-[0-9]+){1,15}', sid, re.ASCII) is None:
            raise ValueError('Registry worker SID is malformed')
        return {'worker_pid': self._process.pid, 'nonce': self._nonce, 'pointer_size': 4,
            'runtime_path': RUNTIME, 'runtime_sha256': RUNTIME_SHA256, 'runtime_mvid': RUNTIME_MVID,
            'method_token': '060000f3', 'method_il_sha256': PROVIDER_IL_SHA256,
            'provider': 'Microsoft.Win32.Registry.GetValue(System.String,System.String,System.Object)',
            'registry_view': 'x86-process-default', 'culture': 'invariant', 'user_sid': sid,
            'helper_path': str(executable), 'helper_sha256': self._helper_hash,
            'authored_source_sha256': hashlib.sha256(SOURCE.encode('ascii')).hexdigest()}

    def _response(self, text, request, record):
        fields = text.split('\t')
        if (len(fields) != 7 or fields[:4] != ['RESPONSE1', self._nonce, str(record['sequence']),
                hashlib.sha256(request).hexdigest()]):
            raise ValueError('Registry response correlation or framing failed')
        if fields[4] == 'VALUE':
            if fields[5] == 'N' and fields[6] == '':
                result = ('null', None)
            elif fields[5] == 'I':
                text = _unb64(fields[6], 11)
                if re.fullmatch(r'0|-?[1-9][0-9]{0,9}', text, re.ASCII) is None:
                    raise ValueError('Noncanonical CLR Int32 result')
                result = ('System.Int32', int(text))
            elif fields[5] == 'S':
                result = ('System.String', _unb64(fields[6], 256))
            else:
                raise ValueError('Unknown CLR value frame')
            leaves._primitive({'kind': result[0], 'value': result[1]})
            record.update(status='observed', result={'kind': result[0], 'value': result[1]})
            return result
        if fields[4] in ('ERROR', 'UNSUPPORTED'):
            kind, message = _unb64(fields[5]), _unb64(fields[6])
            record.update(status='provider_error' if fields[4] == 'ERROR' else 'unsupported',
                          provider_error_type=kind, provider_error_message=message)
            self._terminal = True
            raise _Outcome('failed' if fields[4] == 'ERROR' else 'unsupported', message,
                           provider_error_type=kind, provider_error_message=message)
        raise ValueError('Unknown registry response outcome')

    def read(self, query):
        """Return an issued observation; this method never caches a query."""
        if self._closed or self._failure is not None or self._terminal:
            raise ValueError('Registry observation session is closed or failed')
        key = _query(query)
        if key not in self._scope:
            _unsupported('Registry query is outside the explicit read scope', required_registry_query=_query_dict(key))
        if len(self._records) >= 8:
            _unsupported('At most eight registry observations are supported')
        record = {'sequence': len(self._records), 'query': _query_dict(key), 'status': 'admitted',
                  'request_published': False, 'response_received': False}
        self._records.append(record)
        try:
            if self._process is None:
                self._start()
            request = (self._nonce + '\t' + str(record['sequence']) + '\t' + _wire(key)).encode('ascii')
            name = 'q' + str(record['sequence']).zfill(3)
            self._remaining()
            record['status'] = 'publishing_request'
            _publish(self._directory / (name + '.request'), request)
            record.update(request_published=True, status='awaiting_response')
            text = self._wait_file(name + '.response')
            record['response_received'] = True
            self._response(text, request, record)
            receipt = RegistryObservation(json.dumps(record, ensure_ascii=True, allow_nan=False))
            self._issued[id(receipt)] = (receipt, receipt._document)
            self._remember()
            return receipt
        except BaseException as error:
            self._failure = error
            try:
                record['failure'] = _error(error); self._remember(error)
            except BaseException:
                pass
            raise

    def _validate_observation(self, receipt):
        issued = self._issued.get(id(receipt))
        if (type(receipt) is not RegistryObservation or issued is None or issued[0] is not receipt
                or type(receipt._document) is not str or receipt._document != issued[1] or self._proof is None):
            raise ValueError('Registry observation is not an unchanged receipt from this observer')
        return json.loads(issued[1])

    def close(self):
        if self._closed:
            return
        first = self._failure
        def attempt(stage, action):
            nonlocal first
            row = {'stage': stage, 'status': 'started'}; self._cleanup.append(row)
            try:
                action(); row['status'] = 'passed'
            except BaseException as error:
                if first is None: first = error
                row['status'] = 'failed'
                try: row['error'] = _error(error)
                except BaseException: row['error_export_failed'] = True
        if self._process is not None and first is None and not self._terminal:
            def finish():
                _publish(self._directory / 'finish', (self._nonce + '\t' + str(len(self._records))).encode('ascii'))
                if self._wait_file('done') != 'DONE1\t' + self._nonce + '\t' + str(len(self._records)):
                    raise ValueError('Registry done correlation failed')
                if self._process.wait(timeout=self._remaining()) != 0:
                    raise RuntimeError('Registry worker did not exit successfully')
            attempt('finish', finish)
        for label, process in (('worker', self._process), ('compiler', self._compiler_process)):
            if process is not None:
                def reap(process=process):
                    failure = None
                    try:
                        if process.poll() is None:
                            process.kill()
                    except BaseException as error:
                        failure = error
                    # A termination error does not establish whether the child
                    # exited. Always attempt to reap this exact owned process,
                    # while retaining the first termination/observation error.
                    try:
                        process.wait(timeout=5.0)
                    except BaseException:
                        if failure is None:
                            raise
                    if failure is not None:
                        raise failure
                attempt(label + '_reaped', reap)
        for handle in reversed(self._handles):
            attempt('file_close', handle.close)
        if self._helper_hash is not None:
            def verify():
                if _read(self._directory / 'RegistryWorker.exe', 1024 * 1024, digest=True) != self._helper_hash:
                    raise ValueError('Registry worker bytes changed during observation')
                for path, expected in ((self._compiler, COMPILER_SHA256), (RUNTIME, RUNTIME_SHA256)):
                    if _read(path, 64 * 1024 * 1024, digest=True) != expected:
                        raise ValueError('Registry runtime input changed during observation')
            attempt('input_hashes_after', verify)
        self._closed = True
        self._failure = first
        attempt('evidence_export', lambda: self._remember(first, completed=first is None))
        if first is not None:
            self._failure = first
            raise first

    def capture(self, query_json: bytes):
        keys = _queries(query_json, QUERY_FORMAT)
        # Complete read-scope preflight before the first provider request.
        if any(key not in self._scope for key in keys):
            _unsupported('Capture contains a registry query outside its explicit read scope')
        first = None
        try:
            for key in keys:
                self.read(_query_dict(key))
        except BaseException as error:
            first = error
        try:
            self.close()
        except BaseException as error:
            if first is None: first = error
        if first is not None:
            try: self._remember(first)
            except BaseException: pass
            raise first
        return self.last_report
