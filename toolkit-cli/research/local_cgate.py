"""Explicitly owned temporary C-Gate process for local research acceptance.

No running process or existing project directory is adopted. Cleanup never
removes a child's working directory until its exit has been confirmed.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import tempfile
import time

JAR_SHA256 = '3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630'


def service_backend():
    backend = os.environ.get('CBUS_NATIVE_SERVICE_BACKEND', 'docker')
    if backend not in ('docker', 'local'):
        raise ValueError('CBUS_NATIVE_SERVICE_BACKEND must be docker or local')
    return backend


def _attach(first, cleanup, report=None):
    # Exception messages may contain generated key data; evidence records types.
    try:
        first.local_cgate_cleanup_errors = (*getattr(first, 'local_cgate_cleanup_errors', ()), cleanup)
        if report is not None:
            first.local_cgate_report = report
    except BaseException:
        pass


class LocalCGate:
    def __init__(self, vendor, *, java=None, settings=None):
        self.vendor = Path(vendor).resolve()
        supplied = java or os.environ.get('CBUS_CGATE_JAVA')
        if not supplied:
            raise ValueError('Set CBUS_CGATE_JAVA to the explicitly selected native Java11 executable')
        self.java = Path(supplied).resolve()
        self.keytool = self.java.parent / 'keytool'
        self.lsof = shutil.which('lsof')
        if any(not p.is_file() or not os.access(p, os.X_OK) for p in (self.java, self.keytool)):
            raise ValueError('The selected Java runtime must provide executable java and keytool')
        if self.lsof is None:
            raise ValueError('Local native acceptance requires lsof to verify child listener ownership')
        jar = self.vendor / 'cgate.jar'
        if not jar.is_file() or hashlib.sha256(jar.read_bytes()).hexdigest() != JAR_SHA256:
            raise ValueError('Local acceptance requires the pinned original C-Gate3.4.0 build2001 jar')
        version = subprocess.run([str(self.java), '-version'], capture_output=True, text=True, timeout=10)
        if version.returncode or 'version "11.' not in version.stderr:
            raise ValueError('Local acceptance requires an explicit Java11 runtime')
        settings = dict(settings or {})
        if set(settings) - {'use-scenes', 'scene-base'}:
            raise ValueError('Unsupported local fixture setting')
        if 'use-scenes' in settings and settings['use-scenes'] not in ('yes', 'no'):
            raise ValueError('use-scenes must be yes or no')
        if 'scene-base' in settings and settings['scene-base'] != 'scene':
            raise ValueError('Scene fixtures must use their owned relative scene directory')
        java_sha256 = hashlib.sha256(self.java.read_bytes()).hexdigest()
        self.process = None
        self.log = None
        self.closed = False
        self._starting = False
        self._reserved = []
        # No automatic finalizer: failed process termination must retain cwd.
        self.work = Path(tempfile.mkdtemp(prefix='cbus-owned-native-'))
        self.report = {'backend': 'local', 'vendor_jar_sha256': JAR_SHA256,
                       'java': str(self.java), 'java_version': version.stderr.strip(),
                       'java_sha256': java_sha256,
                       'work_directory': str(self.work), 'projects_adopted': False,
                       'listener_ownership_verified': False, 'cleanup_complete': False,
                       'cleanup_errors': [], 'process_exit_confirmed': False,
                       'work_removed': False, 'reserved_sockets_closed': False, 'log_closed': False}
        try:
            for name in ('config', 'tag', 'logs', 'key', 'tmp', 'scene'):
                (self.work / name).mkdir()
            for name in ('lib', 'unitspec', 'help', 'transform', 'dali_catalogue'):
                (self.work / name).symlink_to(self.vendor / name, target_is_directory=True)
            shutil.copyfile(self.vendor / 'key/cis.ks', self.work / 'key/cis.ks')
            for _ in range(64):
                group = []
                try:
                    first = self._bind(0)
                    self._reserved.append(first); group.append(first)
                    base = first.getsockname()[1]
                    if base > 65532:
                        raise OSError('Insufficient consecutive ports')
                    for port in range(base + 1, base + 4):
                        peer = self._bind(port)
                        self._reserved.append(peer); group.append(peer)
                except BaseException as error:
                    try:
                        self._release_reserved(group)
                    except BaseException as cleanup:
                        _attach(error, cleanup)
                        raise error
                    if isinstance(error, OSError):
                        continue
                    raise
                break
            else:
                raise RuntimeError('Could not reserve four owned local secure ports')
            # Register each socket immediately: a failed second bind cannot leak the first.
            for _ in range(2):
                self._reserved.append(self._bind(0))
            self.tls_port = base
            self.port, self.event_port = [peer.getsockname()[1] for peer in self._reserved[-2:]]
            self.ports = {self.port, self.event_port, *range(base, base + 4)}
            config = {'command-local-address': '127.0.0.1', 'command-port': self.port,
                      'event-mode': 'server', 'event-port': self.event_port,
                      'secure.bind-address': '127.0.0.1', 'secure.port-base': base,
                      'use-load-change-port': 'no', 'use-config-change-port': 'no',
                      'accept-connections-from': '127.0.0.1', 'console.enable-commands': 'no',
                      'project.start': '', 'project.default': '', 'auto-reopen': 'no',
                      'network.source': 'db', 'tag-autosave': 'no', 'clock.master': 'no',
                      'use-scenes': 'no', 'instance.lock-file': 'owned-native.lock',
                      'use-event-file': 'yes', 'event-filename': 'logs/event.log', **settings}
            (self.work / 'config/C-GateConfig.txt').write_text(''.join(f'{key}={value}\n' for key, value in config.items()))
            (self.work / 'config/access.txt').write_text('interface 127.0.0.1 Program\n')
            self.report['configured_ports'] = sorted(self.ports)
        except BaseException as error:
            self._cleanup_preserving(error)
            raise

    @staticmethod
    def _bind(port):
        peer = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            peer.bind(('127.0.0.1', port))
            return peer
        except BaseException as error:
            try:
                peer.close()
            except BaseException as cleanup:
                _attach(error, cleanup)
            raise

    def _release_reserved(self, peers=None):
        first = None
        for peer in list(self._reserved if peers is None else peers):
            try:
                peer.close()
            except BaseException as error:
                if first is None:
                    first = error
                else:
                    _attach(first, error)
            else:
                self._reserved = [value for value in self._reserved if value is not peer]
        if first is not None:
            raise first

    def _cleanup_preserving(self, error):
        try:
            self.close()
        except BaseException as cleanup:
            _attach(error, cleanup, self.report)
        try:
            error.local_cgate_report = self.report
        except BaseException:
            pass

    def start(self):
        if self.closed or self._starting or self.process is not None:
            raise RuntimeError('Owned native process cannot be started twice or resumed')
        self._starting = True
        try:
            self.log = (self.work / 'process.log').open('wb')
            command = [str(self.java), '-Djava.net.preferIPv4Stack=true', '-Djava.io.tmpdir=' + str(self.work / 'tmp'),
                       '-Xms64M', '-Xmx512M', '-jar', str(self.vendor / 'cgate.jar')]
            self._release_reserved()
            self.process = subprocess.Popen(command, cwd=self.work, stdin=subprocess.DEVNULL,
                                            stdout=self.log, stderr=subprocess.STDOUT)
            self.report.update(pid=self.process.pid, argv=command)
            deadline = time.monotonic() + 30
            while True:
                if self.process.poll() is not None:
                    raise RuntimeError('Owned native C-Gate exited during startup')
                listing = subprocess.run([self.lsof, '-nP', '-a', '-p', str(self.process.pid), '-iTCP', '-sTCP:LISTEN', '-Fpn'],
                                         capture_output=True, text=True, timeout=5)
                if listing.returncode not in (0, 1) or listing.stderr:
                    raise RuntimeError('Could not verify owned native listener process')
                pids = [line[1:] for line in listing.stdout.splitlines() if line.startswith('p')]
                endpoints = [line[1:] for line in listing.stdout.splitlines() if line.startswith('n')]
                if endpoints and (pids != [str(self.process.pid)] or listing.returncode != 0):
                    raise RuntimeError('Listener inventory does not identify only the direct child')
                if any(not endpoint.startswith('127.0.0.1:') for endpoint in endpoints):
                    raise RuntimeError('Owned native process opened a non-loopback listener')
                expected = {'127.0.0.1:' + str(port) for port in self.ports}
                if len(endpoints) == 6 and set(endpoints) == expected:
                    if self.process.poll() is not None:
                        raise RuntimeError('Owned native C-Gate exited during listener verification')
                    self.report.update(listener_ownership_verified=True, listeners=sorted(endpoints))
                    return self
                if time.monotonic() >= deadline:
                    raise RuntimeError('Owned native process did not acquire all six reserved loopback ports')
                time.sleep(.1)
        except BaseException as error:
            self._cleanup_preserving(error)
            raise

    def _capture_log(self):
        path = self.work / 'process.log'
        if not path.exists():
            return
        digest = hashlib.sha256(); size = path.stat().st_size; read = 0; tail = b''
        with path.open('rb') as source:
            while True:
                chunk = source.read(min(65536, 1048576-read))
                if not chunk:
                    break
                digest.update(chunk); read += len(chunk); tail = (tail + chunk)[-65536:]
        # Never copy arbitrary log text or generated PEM/key material into a report.
        allowed = re.compile(r'^(Schneider Electric C-Gate\(TM\) v[0-9.]+ \(build [0-9]+\)|C-Gate is running\.|[0-9-]+ [0-9]+ cgate - C-Gate started\.)$')
        lines = [line for line in tail.decode('utf-8', errors='replace').splitlines() if allowed.fullmatch(line)]
        self.report.update(server_log_sha256=digest.hexdigest(), server_log_bytes=size, server_log_hashed_bytes=read, server_log_tail=lines[-10:])

    def close(self):
        if self.closed:
            return self.report
        self.closed = True  # Invalidate before any potentially interruptible cleanup.
        first = None
        def failed(phase, error):
            nonlocal first
            self.report['cleanup_errors'].append({'phase': phase, 'type': type(error).__name__})
            if first is None:
                first = error
            else:
                _attach(first, error)
        exited = self.process is None
        if self.process is not None:
            try:
                exited = self.process.poll() is not None
            except BaseException as error:
                failed('poll', error)
            if not exited:
                try:
                    self.process.terminate()
                except BaseException as error:
                    failed('terminate', error)
                try:
                    self.process.wait(timeout=10)
                    exited = True
                except subprocess.TimeoutExpired:
                    pass
                except BaseException as error:
                    failed('wait', error)
                if not exited:
                    try:
                        self.process.kill()
                    except BaseException as error:
                        failed('kill', error)
                    try:
                        self.process.wait(timeout=5)
                        exited = True
                    except BaseException as error:
                        failed('kill_wait', error)
            if exited:
                self.report['exit_code'] = self.process.returncode
        self.report['process_exit_confirmed'] = exited
        try:
            self._release_reserved()
        except BaseException as error:
            failed('reserved_sockets', error)
        self.report['reserved_sockets_closed'] = not self._reserved
        try:
            if self.log is not None:
                self.log.close()
            self.report['log_closed'] = True
        except BaseException as error:
            failed('log_close', error)
        if exited:
            try:
                self._capture_log()
            except BaseException as error:
                failed('log_capture', error)
        else:
            self.report['server_log_capture'] = 'deferred_process_alive'
        if exited:
            try:
                shutil.rmtree(self.work)
                self.report['work_removed'] = True
            except BaseException as error:
                failed('work_cleanup', error)
        self.report['cleanup_complete'] = all(self.report[key] for key in
            ('process_exit_confirmed', 'reserved_sockets_closed', 'log_closed', 'work_removed'))
        if not self.report['cleanup_complete'] and first is None:
            first = RuntimeError('Owned native cleanup incomplete; working directory retained')
        if first is not None:
            try:
                first.local_cgate_report = self.report
            except BaseException:
                pass
            raise first
        return self.report

    def __enter__(self):
        return self.start()

    def __exit__(self, kind, error, traceback):
        if error is not None:
            self._cleanup_preserving(error)
        else:
            self.close()
