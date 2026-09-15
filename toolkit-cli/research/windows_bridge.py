"""Owned Windows original-model research jobs through UTM's existing file API.

No network listener, credentials, guest policy changes, or Toolkit installation.
The separately launched NativeBridge.cs polls hash-verified owned .cmd jobs once.
This module is research tooling, not a supported CLI or physical acceptance.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path, PureWindowsPath
import re
import subprocess
import time
import uuid

UTMCTL = '/Applications/UTM.app/Contents/MacOS/utmctl'
VM_UUID = '1107696A-3DD0-4531-9C3A-DCF798C5ACAD'
GUEST_ROOT = r'C:\CBusCliOracle118-88d8'


class WindowsFileBusyError(RuntimeError):
    """The exact UTM/Windows sharing violation for one read-only file pull."""
    def __init__(self, operation, relative, guest_path, returncode, stderr):
        super().__init__(stderr)
        self.operation, self.relative, self.guest_path = operation, relative, guest_path
        self.returncode, self.stderr = returncode, stderr

    def as_dict(self):
        return dict(operation=self.operation, relative=self.relative, guest_path=self.guest_path,
                    returncode=self.returncode, stderr=self.stderr)


def _wait_options(timeout, max_busy_retries):
    try:
        finite = type(timeout) in (int, float) and math.isfinite(timeout)
    except OverflowError:
        finite = False
    if not finite or timeout <= 0:
        raise ValueError('Windows result timeout must be positive and finite')
    if type(max_busy_retries) is not int or not 0 <= max_busy_retries <= 256:
        raise ValueError('Windows busy retry limit must be an integer from0 through256')


class WindowsBridge:
    def __init__(self, *, vm_uuid=VM_UUID, guest_root=GUEST_ROOT, utmctl=UTMCTL):
        self.vm_uuid = vm_uuid
        self.guest_root = guest_root
        self.utmctl = utmctl
        self.last_wait_evidence = None
        self.last_wait_error = None

    def path(self, relative):
        path = PureWindowsPath(relative)
        if not relative or path.is_absolute() or path.drive or any(x in ('..', '') for x in path.parts):
            raise ValueError('Guest path must be relative to the owned bridge directory')
        return str(PureWindowsPath(self.guest_root) / path)

    def _file(self, operation, relative, *, data=None, missing_ok=False, _deadline=None):
        guest_path = self.path(relative)
        timeout = 120
        if _deadline is not None:
            timeout = min(timeout, _deadline - time.monotonic())
            if timeout <= 0:
                raise TimeoutError('Windows result retrieval deadline expired before file pull')
        result = subprocess.run([self.utmctl, 'file', operation, self.vm_uuid, guest_path],
                                input=data, capture_output=True, timeout=timeout)
        # UTM 4.7 reports guest errors on stderr while returning status zero.
        if result.returncode or result.stderr:
            message = result.stderr.decode(errors='replace')
            expected = ("Error from event: The operation couldn’t be completed. (OSStatus error -2700.)\n"
                        "failed to open file '" + guest_path + "': The process cannot access the file because it is being used by another process.")
            if operation == 'pull' and result.returncode == 0 and message.replace('\r\n', '\n').rstrip('\n') == expected:
                raise WindowsFileBusyError(operation, relative, guest_path, result.returncode, message)
            if missing_ok and not result.returncode and b'The system cannot find the file specified' in result.stderr:
                return None
            raise RuntimeError(message or f'utmctl status {result.returncode}')
        return result.stdout

    def push(self, relative, data):
        if not isinstance(data, bytes):
            raise TypeError('File data must be bytes')
        self._file('push', relative, data=data)
        if self.pull(relative) != data:
            raise RuntimeError('Guest file verification differs after push')
        return hashlib.sha256(data).hexdigest()

    def pull(self, relative, *, missing_ok=False, _deadline=None):
        return self._file('pull', relative, missing_ok=missing_ok, _deadline=_deadline)

    def submit(self, script, *, job_id=None):
        """Submit an owned .cmd exactly once; returns the job id, without waiting."""
        if isinstance(script, str):
            script = script.replace('\r\n', '\n').replace('\n', '\r\n').encode('utf-8')
        if not isinstance(script, bytes) or not script:
            raise ValueError('A nonempty owned command script is required')
        job_id = job_id or 'job-probe-' + uuid.uuid4().hex[:16]
        if not re.fullmatch(r'job-[a-z0-9-]{1,48}', job_id):
            raise ValueError('Invalid owned job id')
        if any(self.pull(job_id + suffix, missing_ok=True) is not None for suffix in ('.ready.json', '.result.json', '.admitted.cmd', '.admitted.json')):
            raise ValueError('Job id already submitted or admitted; inspect its evidence, never resubmit')
        ready = self.pull('bridge-ready.json')
        if not ready or self.pull('bridge-stopped.json', missing_ok=True) is not None:
            raise RuntimeError('Owned runner is not active')
        spec = json.loads(ready)
        if spec.get('format') != 'cbus-windows-bridge-v2':
            raise RuntimeError('The verified v2 admission protocol is required')
        if spec['job_directory'] != self.guest_root or spec['network_listener'] is not False:
            raise RuntimeError('Unexpected guest bridge identity')
        digest = self.push(job_id + '.cmd', script)
        self.push(job_id + '.ready.json', json.dumps({'sha256': digest}).encode())
        return job_id

    def result(self, job_id, *, missing_ok=False, _deadline=None):
        if not re.fullmatch(r'job-[a-z0-9-]{1,48}', job_id):
            raise ValueError('Invalid owned job id')
        budget = {} if _deadline is None else {'_deadline': _deadline}
        data = self.pull(job_id + '.result.json', missing_ok=missing_ok, **budget)
        if data is None:
            return None
        result = json.loads(data)
        result['job_id'] = job_id
        result['stdout'] = self.pull(job_id + '.stdout.txt', missing_ok=True, **budget)
        result['stderr'] = self.pull(job_id + '.stderr.txt', missing_ok=True, **budget)
        return result

    def wait(self, job_id, *, timeout=330, max_busy_retries=8):
        """Read the same job's artifacts under one deadline; never resubmit it.

        Only exact sharing violations are retried. The deadline starts here,
        after submission, and bounds each subprocess read as well as polling.
        """
        self.last_wait_evidence = self.last_wait_error = None
        _wait_options(timeout, max_busy_retries)
        if not isinstance(job_id, str) or not re.fullmatch(r'job-[a-z0-9-]{1,48}', job_id):
            raise ValueError('Invalid owned job id')
        artifacts = {job_id + suffix for suffix in ('.result.json', '.stdout.txt', '.stderr.txt')}
        attempts = []
        def remember(state):
            evidence = dict(job_id=job_id, state=state, timeout=timeout, max_busy_retries=max_busy_retries,
                            file_busy_attempts=[dict(row) for row in attempts], job_resubmitted=False)
            self.last_wait_evidence = evidence
            return dict(evidence, file_busy_attempts=[dict(row) for row in attempts])
        try:
            deadline = time.monotonic() + timeout
            remember('waiting')
            while True:
                if time.monotonic() >= deadline:
                    raise TimeoutError('Windows result retrieval deadline expired; inspect the same durable job, never resubmit automatically')
                try:
                    result = self.result(job_id, missing_ok=True, _deadline=deadline)
                except WindowsFileBusyError as error:
                    if error.operation != 'pull' or error.relative not in artifacts or error.guest_path != self.path(error.relative):
                        raise
                    attempts.append(dict(error.as_dict(), attempt=len(attempts) + 1))
                    remember('waiting')
                    if len(attempts) > max_busy_retries:
                        raise
                else:
                    if time.monotonic() >= deadline:
                        raise TimeoutError('Windows result retrieval completed after its deadline; inspect the same durable job, never resubmit automatically')
                    if result is not None:
                        evidence = remember('retrieved')
                        result['wait_evidence'] = evidence
                        return result
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('Windows result retrieval deadline expired; inspect the same durable job, never resubmit automatically')
                time.sleep(min(.5, remaining))
        except BaseException as error:
            self.last_wait_error = error
            try:
                evidence = remember('error')
                error.windows_bridge_wait_evidence = evidence
            except BaseException:
                pass
            raise

    def run(self, script, *, job_id=None, timeout=330, max_busy_retries=8):
        self.last_wait_evidence = self.last_wait_error = None
        _wait_options(timeout, max_busy_retries)  # Invalid options must not publish a job.
        return self.wait(self.submit(script, job_id=job_id), timeout=timeout, max_busy_retries=max_busy_retries)


class WindowsModelProbe:
    """Compile an owned x86 probe against the pinned, staged original assemblies."""
    def __init__(self, source, app, *, bridge=None, references=()):
        if isinstance(references, (str, bytes)) or not isinstance(references, (tuple, list)):
            raise ValueError('References must be a sequence of staged vendor DLL names')
        if any(not isinstance(name, str) or not re.fullmatch(r'[a-zA-Z0-9_.-]+\.dll', name) for name in references):
            raise ValueError('References must be simple vendor DLL filenames')
        self.bridge = bridge or WindowsBridge()
        self.prefix = 'probe-' + uuid.uuid4().hex[:16]
        self.app = Path(app)
        manifest = json.loads(self.bridge.pull('guest-vendor-manifest.json'))
        if len(manifest) != 25:
            raise RuntimeError('Unexpected staged vendor manifest')
        for row in manifest:
            local = self.app / row['name']
            if not local.is_file() or local.stat().st_size != row['size'] or hashlib.sha256(local.read_bytes()).hexdigest() != row['sha256']:
                raise RuntimeError('Staged vendor file differs from local original: ' + row['name'])
        vendor_names = {row['name'] for row in manifest if row['name'].endswith('.dll')}
        if any(name not in vendor_names for name in references):
            raise ValueError('Additional reference is absent from the pinned staged vendor manifest')
        reference_args = ''.join(' /r:' + name for name in dict.fromkeys(references) if name != 'CBusLogicModel.dll')
        toolkit = next(row for row in manifest if row['name'] == 'CBusToolkit.exe')
        if toolkit['file_version'] != '1.18.0.2754' or toolkit['product_version'] != '1.18.0':
            raise RuntimeError('Wrong original Toolkit version')
        self.vendor_manifest = manifest
        self.source_sha256 = self.bridge.push('vendor\\' + self.prefix + '.cs', Path(source).read_bytes())
        result = self.bridge.run('@echo off\ncd /d ' + self.bridge.path('vendor') + '\n'
            + r'C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe'
            + ' /nologo /platform:x86 /r:CBusLogicModel.dll /r:System.Xml.Linq.dll /r:System.Windows.Forms.dll /r:System.Drawing.dll'
            + reference_args + ' /out:' + self.prefix + '.exe ' + self.prefix + '.cs\n')
        self._check(result)

    @staticmethod
    def _check(result):
        if result.get('complete') is not True or result.get('exit_code') != 0:
            raise RuntimeError('Windows original-model job failed: ' + repr(result))
        if result['stderr']:
            raise RuntimeError('Windows original-model stderr: ' + result['stderr'].decode(errors='replace'))

    def run_result(self, arguments=(), *, files=None):
        """Return original exit/stdout/stderr; run sequentially per probe instance.

        Independent instances use separate filenames and can run concurrently.
        """
        renames = {}
        for name, data in (files or {}).items():
            if not re.fullmatch(r'[a-zA-Z0-9_.-]{1,80}', name):
                raise ValueError('Only simple owned input filenames are accepted')
            renamed = self.prefix + '-' + name
            self.bridge.push('vendor\\' + renamed, data)
            renames[name] = renamed
        args = [renames.get(arg, arg) for arg in arguments]
        if any(not isinstance(arg, str) or not re.fullmatch(r'[a-zA-Z0-9_.-]{1,120}', arg) for arg in args):
            raise ValueError('Only simple probe arguments are accepted')
        result = self.bridge.run('@echo off\ncd /d ' + self.bridge.path('vendor') + '\n' + self.prefix + '.exe ' + ' '.join(args) + '\n')
        if type(result.get('exit_code')) is not int or result.get('stdout') is None or result.get('stderr') is None:
            raise RuntimeError('Windows job did not produce a process result: ' + repr(result))
        return result

    def run(self, arguments=(), *, files=None):
        result = self.run_result(arguments, files=files)
        self._check(result)
        return result['stdout'].decode('utf-8-sig')
