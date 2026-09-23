"""Explicit research-only original .NET oracle selection; never a silent fallback."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Mapping

MONO_IMAGE = 'mono@sha256:34d816779b1248b5cfd095770b64ecbaf1798e2aca693a91c11a018dce9c7ad5'
FRAMEWORK_REFERENCES = ('System.Xml.Linq', 'System.Windows.Forms', 'System.Drawing')


def selected_backend(value=None):
    value = os.environ.get('CBUS_ORIGINAL_MODEL_BACKEND', 'docker') if value is None else value
    if value not in ('docker', 'windows'):
        raise ValueError('Original model backend must be exactly docker or windows')
    return value


def _argument(value):
    if not isinstance(value, str):
        return False
    if re.fullmatch(r'@[0-9]{1,2}', value):
        digits = value[1:]
        return str(int(digits)) == digits and 0 <= int(digits) <= 64
    return bool(re.fullmatch(r'[A-Za-z0-9_.-]{1,120}', value)) and value not in ('.', '..')


def _filename(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,78}', value) or value.endswith('.'):
        raise ValueError('Input filenames must be simple owned basenames')
    if value.split('.', 1)[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}:
        raise ValueError('Reserved Windows device filename')
    return value


@dataclass(frozen=True)
class OriginalResult:
    backend: str
    returncode: int
    stdout: str
    stderr: str
    source_sha256: str
    process_evidence: dict


class OriginalOracleError(RuntimeError):
    def __init__(self, stage, result):
        super().__init__(f'Original {result.backend} {stage} exited {result.returncode}: {result.stdout}{result.stderr}')
        self.stage = stage
        self.result = result


class OriginalModelOracle:
    """Single-source model probe, lazy compilation, sequential calls per instance.

    Validate all file/argument/configuration input before the first compile or job.
    Windows delegates to WindowsModelProbe; Docker uses argv-only compile/runtime
    commands with the same pinned original assemblies. No shell command parsing.
    GUI probes explicitly request Xvfb on Docker and use native WinForms on Windows.
    Each backend preserves nonzero native exits and stderr through run_result().
    """
    def __init__(self, source, app, *, backend=None, references=(), gui=False,
                 docker_image=MONO_IMAGE, timeout=60):
        self.backend = selected_backend(backend)
        if not isinstance(references, (tuple, list)) or any(not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_.-]+\.dll', name) for name in references):
            raise ValueError('References must be simple vendor DLL filenames')
        if type(gui) is not bool:
            raise ValueError('gui must be boolean')
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= 300:
            raise ValueError('Timeout must be positive and at most300seconds')
        if not isinstance(docker_image, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/@:-]*', docker_image):
            raise ValueError('Invalid explicit Docker image')
        self.source = Path(source).resolve()
        self.app = Path(app).resolve()
        if self.source.suffix != '.cs' or not self.source.is_file():
            raise ValueError('An existing owned C# probe source is required')
        _filename(self.source.name)
        if not self.app.is_dir() or not (self.app / 'CBusLogicModel.dll').is_file():
            raise ValueError('Original application directory lacks CBusLogicModel.dll')
        if any(not (self.app / name).is_file() for name in references):
            raise ValueError('Additional vendor reference is absent from the original app directory')
        self.source_bytes = self.source.read_bytes()
        self.source_sha256 = hashlib.sha256(self.source_bytes).hexdigest()
        self.references = tuple(dict.fromkeys(references))
        self.gui, self.docker_image, self.timeout = gui, docker_image, timeout
        self._windows = None
        self._temporary = None
        self._compiled = False
        self.compile_result = None

    @staticmethod
    def _inputs(arguments, files):
        if not isinstance(arguments, (tuple, list)) or any(not _argument(arg) for arg in arguments):
            raise ValueError('Probe arguments must be a sequence of simple literal tokens')
        if files is None:
            files = {}
        if not isinstance(files, Mapping):
            raise ValueError('Input files must map owned basenames to bytes')
        result = {}
        names = set()
        for name, data in files.items():
            _filename(name)
            if name.lower() in names or Path(name).suffix.lower() in {'.exe', '.dll', '.cs', '.cmd', '.bat', '.com', '.ps1'}:
                raise ValueError('Input files cannot collide by case or replace code/executables')
            names.add(name.lower())
            if not isinstance(data, bytes):
                raise ValueError('Input file contents must be bytes')
            result[name] = data
        return tuple(arguments), result

    def _docker(self, command):
        base = ['docker', 'run', '--rm', '--network', 'none', '-v', str(self.app) + ':/input:ro',
                '-v', self._temporary.name + ':/work', '-w', '/work', '-e', 'MONO_PATH=/input', self.docker_image]
        completed = subprocess.run(base + command, capture_output=True, text=True, timeout=self.timeout)
        return OriginalResult('docker', completed.returncode, completed.stdout, completed.stderr,
                              self.source_sha256, {'image': self.docker_image, 'command': command})

    def _compile(self):
        if self._compiled:
            return
        # Catch source replacement between planning and its eventual first job.
        if self.source.read_bytes() != self.source_bytes:
            raise ValueError('Owned probe source changed before compilation')
        if self.backend == 'windows':
            from research.windows_bridge import WindowsModelProbe
            self._windows = WindowsModelProbe(self.source, self.app, references=self.references)
        else:
            self._temporary = tempfile.TemporaryDirectory(prefix='cbus-original-model-')
            Path(self._temporary.name, self.source.name).write_bytes(self.source_bytes)
            names = tuple(dict.fromkeys(('CBusLogicModel.dll', *self.references)))
            command = ['mcs', *('-r:/input/' + name for name in names),
                       *('-r:' + name for name in FRAMEWORK_REFERENCES), '-out:OriginalProbe.exe', self.source.name]
            result = self._docker(command)
            self.compile_result = result
            if result.returncode:
                self.close()
                raise OriginalOracleError('compile', result)
        self._compiled = True

    def run_result(self, arguments=(), *, files=None):
        arguments, files = self._inputs(arguments, files)
        self._compile()
        if self.backend == 'windows':
            if any(arg.startswith('@') for arg in arguments):
                # Frozen WindowsModelProbe's literal-token grammar predates the
                # original static-label @0..64 syntax. Keep this narrow extension
                # here, using its same compiled/source-pinned instance and v2 jobs.
                probe = self._windows
                if probe.source_sha256 != self.source_sha256 or not re.fullmatch(r'probe-[a-f0-9]{16}', probe.prefix):
                    raise RuntimeError('Unexpected compiled Windows probe identity')
                directory = probe.bridge.path('vendor')
                if any(char in directory for char in '"%!?\r\n'):
                    raise ValueError('Unsafe explicit guest directory')
                renames = {}
                for name, data in files.items():
                    renamed = probe.prefix + '-' + name
                    probe.bridge.push('vendor\\' + renamed, data)
                    renames[name] = renamed
                actual = [renames.get(arg, arg) for arg in arguments]
                native = probe.bridge.run('@echo off\ncd /d "' + directory + '"\n' + probe.prefix + '.exe ' + ' '.join(actual) + '\n')
                if type(native.get('exit_code')) is not int or native.get('stdout') is None or native.get('stderr') is None:
                    raise RuntimeError('Windows admission did not produce a process result: ' + repr(native))
            else:
                native = self._windows.run_result(arguments, files=files)
            return OriginalResult('windows', native['exit_code'], native['stdout'].decode('utf-8-sig'),
                                  native['stderr'].decode('utf-8-sig'), self.source_sha256,
                                  {k: value for k, value in native.items() if k not in ('stdout', 'stderr')})
        for name, data in files.items():
            Path(self._temporary.name, name).write_bytes(data)
        command = (['xvfb-run', '-a'] if self.gui else []) + ['mono', 'OriginalProbe.exe', *arguments]
        return self._docker(command)

    def run(self, arguments=(), *, files=None):
        result = self.run_result(arguments, files=files)
        if result.returncode:
            raise OriginalOracleError('run', result)
        return result.stdout

    def close(self):
        if self._temporary is not None:
            self._temporary.cleanup()
            self._temporary = None
        self._compiled = False
        self._windows = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
