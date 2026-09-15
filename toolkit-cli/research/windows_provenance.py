"""Explicit owned Windows provenance for portable native acceptance harnesses.

This is research infrastructure: one fixed read-only query, no Toolkit session,
network listener, compiler invocation, runner start or automatic replay.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
from types import MappingProxyType


ENVIRONMENT = 'CBUS_WINDOWS_PROVENANCE_ROOT'


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate Windows provenance field: ' + key)
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique)


def _read(path, limit):
    with path.open('rb') as source:
        raw = source.read(limit + 1)
    if not raw or len(raw) > limit:
        raise ValueError('Windows provenance file is empty or exceeds its bound: ' + path.name)
    return raw


@dataclass(frozen=True)
class WindowsProvenance:
    paths: object
    evidence: object

    def __post_init__(self):
        object.__setattr__(self, 'paths', MappingProxyType(dict(self.paths)))
        # Evidence is diagnostic only; serialization always returns an isolated copy.
        object.__setattr__(self, 'evidence', json.dumps(self.evidence, sort_keys=True))

    def as_dict(self):
        return json.loads(self.evidence)

    def verify(self, bridge):
        expected = self.as_dict()['file_sha256']
        raw = {name: _read(path, 16 * 1024 * 1024 if name.endswith('.exe') else 256 * 1024)
               for name, path in self.paths.items()}
        if any(_digest(value) != expected[name] for name, value in raw.items()):
            raise RuntimeError('Windows provenance changed after validation')
        _matching_generation(bridge, raw)


def _matching_generation(bridge, raw):
    if bridge.pull('bridge-ready.json') != raw['bridge-ready.json']:
        raise RuntimeError('Owned Windows bridge ready record differs from supplied provenance')
    if bridge.pull('bridge-stopped.json', missing_ok=True) is not None:
        raise RuntimeError('Owned Windows bridge is stopped')
    if bridge.pull('NativeWindowsBridgeV2.exe') != raw['NativeWindowsBridgeV2.exe']:
        raise RuntimeError('Owned Windows bridge executable differs from supplied provenance')


def resolve_windows_provenance(root, bridge):
    """Resolve explicit files and match them to the current owned v2 generation."""
    configured = os.environ.get(ENVIRONMENT)
    if configured is not None:
        if not configured or not Path(configured).is_absolute():
            raise ValueError(ENVIRONMENT + ' must name an absolute owned runtime directory')
        directory = Path(configured).resolve()
    else:
        directory = (Path(root) / 'research/runtime').resolve()
    paths = {
        'NativeWindowsBridgeV2.exe': directory / 'windows-bridge/v2/NativeWindowsBridgeV2.exe',
        'bridge-ready.json': directory / 'windows-bridge/v2/bridge-ready.json',
        'windows-runtime.json': directory / 'edlt-lifecycle/windows-runtime.json',
    }
    raw = {name: _read(path, 16 * 1024 * 1024 if name.endswith('.exe') else 256 * 1024)
           for name, path in paths.items()}
    ready = _json(raw['bridge-ready.json'])
    runtime = _json(raw['windows-runtime.json'])
    if (not isinstance(ready, dict) or ready.get('format') != 'cbus-windows-bridge-v2'
            or ready.get('job_directory') != bridge.guest_root
            or ready.get('network_listener') is not False
            or type(ready.get('pid')) is not int or ready['pid'] <= 0):
        raise ValueError('Unexpected owned Windows bridge provenance identity')
    required = {'mscorlib', 'compiler', 'os_version', 'process_architecture', 'framework'}
    if not isinstance(runtime, dict) or set(runtime) != required:
        raise ValueError('Unexpected Windows runtime provenance fields')
    for name in ('compiler', 'mscorlib'):
        record = runtime[name]
        if (not isinstance(record, dict) or set(record) != {'path', 'sha256', 'version'}
                or any(not isinstance(value, str) or not value for value in record.values())):
            raise ValueError('Invalid Windows ' + name + ' provenance')
    if (any(not isinstance(runtime[name], str) or not runtime[name]
            for name in ('os_version', 'process_architecture'))
            or type(runtime['framework']) is not int or runtime['framework'] <= 0):
        raise ValueError('Invalid Windows runtime provenance')

    _matching_generation(bridge, raw)
    # PID is strictly validated above; all other command text is fixed. No supplied
    # JSON path, hash, version, shell text or metadata becomes executable syntax.
    script = ('@echo off\n'
        'powershell -NoProfile -Command "$ErrorActionPreference=\'Stop\'; '
        "$c='C:\\Windows\\Microsoft.NET\\Framework\\v4.0.30319\\csc.exe'; "
        "$m='C:\\Windows\\Microsoft.NET\\Framework\\v4.0.30319\\mscorlib.dll'; "
        '$p=Get-Process -Id ' + str(ready['pid']) + '; '
        '@{runner_pid=$p.Id; runner_executable=$p.Path; runtime=@{'
        'os_version=[Environment]::OSVersion.VersionString; process_architecture=$env:PROCESSOR_ARCHITECTURE; '
        "framework=(Get-ItemProperty 'HKLM:\\SOFTWARE\\Microsoft\\NET Framework Setup\\NDP\\v4\\Full').Release; "
        'compiler=@{path=$c; sha256=(Get-FileHash -Algorithm SHA256 $c).Hash; version=(Get-Item $c).VersionInfo.FileVersion}; '
        'mscorlib=@{path=$m; sha256=(Get-FileHash -Algorithm SHA256 $m).Hash; version=(Get-Item $m).VersionInfo.FileVersion}'
        '}} | ConvertTo-Json -Depth 5"\n')
    result = bridge.run(script)
    if (result.get('complete') is not True or type(result.get('exit_code')) is not int
            or result['exit_code'] != 0 or result.get('stderr') != b''
            or not isinstance(result.get('stdout'), bytes) or len(result['stdout']) > 256 * 1024
            or not isinstance(result.get('job_id'), str)
            or not re.fullmatch(r'job-[a-z0-9-]{1,48}', result['job_id'])):
        raise RuntimeError('Owned Windows runtime provenance query failed: ' + repr(result))
    observed = _json(result['stdout'])
    if (not isinstance(observed, dict) or set(observed) != {'runner_pid', 'runner_executable', 'runtime'}
            or type(observed['runner_pid']) is not int or observed['runner_pid'] != ready['pid']
            or observed['runner_executable'] != bridge.path('NativeWindowsBridgeV2.exe')
            or observed['runtime'] != runtime):
        raise RuntimeError('Current Windows runtime or runner identity differs from supplied provenance')
    _matching_generation(bridge, raw)
    for name, path in paths.items():
        if _read(path, 16 * 1024 * 1024 if name.endswith('.exe') else 256 * 1024) != raw[name]:
            raise RuntimeError('Windows provenance changed during validation: ' + name)
    return WindowsProvenance(paths, {
        'format': 'cbus-owned-windows-provenance-v1', 'root': str(directory),
        'environment': ENVIRONMENT if configured is not None else None,
        'file_sha256': {name: _digest(value) for name, value in raw.items()},
        'ready': ready, 'runtime': runtime, 'current_generation_verified': True,
        'query': {'job_id': result.get('job_id'), 'complete': True, 'exit_code': 0,
                  'script': script, 'script_sha256': _digest(script.replace('\n', '\r\n').encode()),
                  'script_encoding': 'UTF-8 with CRLF, as submitted by WindowsBridge',
                  'stdout': result['stdout'].decode('utf-8-sig'), 'stdout_sha256': _digest(result['stdout']),
                  'stderr': '', 'stderr_sha256': _digest(b'')},
        'physical_device_verified': False,
    })
