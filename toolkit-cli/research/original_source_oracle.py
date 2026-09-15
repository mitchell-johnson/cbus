"""Explicit research-only multi-source original .NET compilation.

Keeps each owned source byte-for-byte; no concatenation or compiler shell input.
"""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import re
import tempfile
import uuid

from research.original_oracle import (
    OriginalModelOracle, OriginalResult, OriginalOracleError,
    FRAMEWORK_REFERENCES, MONO_IMAGE, _filename,
)
from research.windows_bridge import WindowsBridge, WindowsModelProbe

STAGED_MANIFEST_SHA256 = '689931140e99a8366021073dd5980d2e43dbb61059eef0a488b69e8d856f69cc'


class _WindowsSourceSetProbe(WindowsModelProbe):
    """Use frozen per-probe file/run methods after a separate explicit compile."""
    def __init__(self, owner):
        self.bridge = WindowsBridge()
        self.prefix = 'probe-' + uuid.uuid4().hex[:16]
        self.source_sha256 = owner.source_sha256
        self.app = owner.app
        directory = self.bridge.path('vendor')
        if any(char in directory for char in '"%!?\r\n'):
            raise ValueError('Unsafe owned guest directory')
        manifest_bytes = self.bridge.pull('guest-vendor-manifest.json')
        if hashlib.sha256(manifest_bytes).hexdigest() != STAGED_MANIFEST_SHA256:
            raise RuntimeError('Original staged manifest fingerprint differs')
        manifest = json.loads(manifest_bytes)
        if not isinstance(manifest, list) or len(manifest) != 25:
            raise RuntimeError('Unexpected original staged manifest')
        for row in manifest:
            local = self.app / row['name']
            if not local.is_file() or local.stat().st_size != row['size'] or hashlib.sha256(local.read_bytes()).hexdigest() != row['sha256']:
                raise RuntimeError('Staged vendor file differs from local original: ' + row['name'])
        vendor_names = {row['name'] for row in manifest if row['name'].endswith('.dll')}
        if any(name not in vendor_names for name in owner.references):
            raise ValueError('Additional reference is absent from the pinned staged vendor manifest')
        toolkit = next(row for row in manifest if row['name'] == 'CBusToolkit.exe')
        if toolkit['file_version'] != '1.18.0.2754' or toolkit['product_version'] != '1.18.0':
            raise RuntimeError('Wrong original Toolkit version')
        self.vendor_manifest = manifest
        source_names = []
        for index, (path, data) in enumerate(zip(owner.sources, owner.source_snapshots)):
            name = self.prefix + '-source' + str(index) + '.cs'
            digest = self.bridge.push('vendor\\' + name, data)
            if digest != hashlib.sha256(data).hexdigest():
                raise RuntimeError('Owned source upload fingerprint differs')
            source_names.append(name)
        references = tuple(dict.fromkeys(('CBusLogicModel.dll', *owner.references)))
        args = (' /nologo /platform:x86 /main:' + owner.entry_point
                + ''.join(' /r:' + name for name in references)
                + ''.join(' /r:' + name + '.dll' for name in FRAMEWORK_REFERENCES)
                + ' /out:' + self.prefix + '.exe ' + ' '.join(source_names))
        self.compile_native = self.bridge.run('@echo off\ncd /d "' + directory + '"\n'
            + r'C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe' + args + '\n')
        self._check(self.compile_native)


class OriginalSourceSetOracle(OriginalModelOracle):
    """Two to eight ordered owned sources, one explicit entry point, lazy compile.

    The result source_sha256 is the ordered source-set fingerprint, and
    process_evidence includes individual source hashes. Backend, file/argument,
    exception and sequential instance contracts match OriginalModelOracle.
    """
    def __init__(self, sources, app, *, entry_point, backend=None, references=(),
                 gui=False, docker_image=MONO_IMAGE, timeout=60):
        if not isinstance(sources, (tuple, list)) or not 2 <= len(sources) <= 8:
            raise ValueError('Sources must be an ordered sequence of two to eight owned C# files')
        if not isinstance(entry_point, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*', entry_point) or len(entry_point) > 120:
            raise ValueError('Entry point must be one explicit simple qualified C# identifier')
        paths = tuple(Path(source).resolve() for source in sources)
        if any(path.suffix != '.cs' or not path.is_file() for path in paths):
            raise ValueError('Each owned source must be an existing C# file')
        for path in paths:
            _filename(path.name)
        if len({path.name.casefold() for path in paths}) != len(paths):
            raise ValueError('Source basenames must be distinct ignoring case')
        snapshots = tuple(path.read_bytes() for path in paths)
        super().__init__(paths[0], app, backend=backend, references=references, gui=gui,
                         docker_image=docker_image, timeout=timeout)
        self.sources, self.source_snapshots, self.entry_point = paths, snapshots, entry_point
        self._source_hashes = tuple((path.name, hashlib.sha256(data).hexdigest())
                                    for path, data in zip(paths, snapshots))
        self.source_sha256 = hashlib.sha256(json.dumps(self.source_hashes, separators=(',', ':')).encode()).hexdigest()

    @property
    def source_hashes(self):
        return tuple({'name': name, 'sha256': digest} for name, digest in self._source_hashes)

    def _compile(self):
        if self._compiled:
            return
        if any(path.read_bytes() != data for path, data in zip(self.sources, self.source_snapshots)):
            raise ValueError('Owned source set changed before compilation')
        if self.backend == 'windows':
            self._windows = _WindowsSourceSetProbe(self)
            native = self._windows.compile_native
            self.compile_result = OriginalResult('windows', native['exit_code'], native['stdout'].decode('utf-8-sig'),
                native['stderr'].decode('utf-8-sig'), self.source_sha256,
                {key: value for key, value in native.items() if key not in ('stdout', 'stderr')})
        else:
            self._temporary = tempfile.TemporaryDirectory(prefix='cbus-original-source-set-')
            for path, data in zip(self.sources, self.source_snapshots):
                Path(self._temporary.name, path.name).write_bytes(data)
            names = tuple(dict.fromkeys(('CBusLogicModel.dll', *self.references)))
            command = ['mcs', *('-r:/input/' + name for name in names),
                *('-r:' + name for name in FRAMEWORK_REFERENCES), '-main:' + self.entry_point,
                '-out:OriginalProbe.exe', *(path.name for path in self.sources)]
            result = self._docker(command)
            self.compile_result = result
            if result.returncode:
                self.close()
                raise OriginalOracleError('compile', result)
        self._compiled = True

    def run_result(self, arguments=(), *, files=None):
        result = super().run_result(arguments, files=files)
        return replace(result, process_evidence={**result.process_evidence,
            'source_hashes': list(self.source_hashes), 'entry_point': self.entry_point,
            'source_set_sha256': self.source_sha256})
