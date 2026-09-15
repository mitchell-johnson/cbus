"""Pinned, task-local macOS Mono oracle for the unchanged diagnostic PTY probe.

Research tooling only; no installer, physical serial device, or firmware action.
"""
from __future__ import annotations
import hashlib
import os
from pathlib import Path
import platform
import subprocess
import tempfile

PACKAGE_SHA256 = '80b0dbfa59ba9ed76dbf1393998e6a2ed2d1ccc8f5850c7a46fbe31a2aea88d8'
PROBE_SHA256 = '409a12773d1ff67d33337efe7fdd8ae451921043a2f7d04b144e6454af96db75'
RUNTIME_HASHES = {'bin/mono-sgen64': '91b99fc4b1158785b43506f2d76f9998c31f0492128e5789fbaaab0e300afd49',
 'etc/mono/config': '5f8a2ac3f2ba0ab21c53f75d06414ce049232c7d6dc45a921bdff66a7dab11a2',
 'lib/libMonoPosixHelper.dylib': '243763bbaa900ae5f69ce3c5325ed1f321b6b3f77aaf7c1318db84e5ae32343a',
 'lib/libmono-native-compat.0.dylib': 'c89a2392978245b560e619f45b7f2fb8c855a3dd0872a8604dc4ef7e5adab17d',
 'lib/mono/4.5/Microsoft.CSharp.dll': '6a32705163da884cee8bd7ef381694a119865f4a6f9b6fa39e0bbe60cdc4b248',
 'lib/mono/4.5/System.Core.dll': '18507d65f274356ca237e7ff69eae1bd5f4e3ef3ad4c611b83cb65eebdbcf65f',
 'lib/mono/4.5/System.Xml.dll': '95b7a14296050b5e5b73753b84cddc54ef90b94aaad0af980df4746dba8f9fd4',
 'lib/mono/4.5/System.dll': '5d5c56e3a70e873e8f8c514cc5db15c8647c8b0933b7eeae11a5e9705f5c8386',
 'lib/mono/4.5/mcs.exe': '857bb3129c3e2a5e7f8410db8fa5eb78139e934bb6279a72428597962311d771',
 'lib/mono/4.5/mscorlib.dll': '86364b7803c92d8c88b590031f015f80b10b00641e9d067e07a529a131d815e4',
 'lib/mono/gac/I18N.West/4.0.0.0__0738eb9f132ed756/I18N.West.dll': 'd9b1af4624fc2ad388019d534bba0e7667646d45e55795d2d1a738d4bcaa1eb6',
 'lib/mono/gac/I18N/4.0.0.0__0738eb9f132ed756/I18N.dll': '1304efeb2c590721b5cd78f89b2bac423784f05c532a51970551a0170c44812d',
 'lib/mono/gac/Mono.Security/4.0.0.0__0738eb9f132ed756/Mono.Security.dll': 'f3aee98ee4953edc81d092f39696dccb3c3aedaed8dd60f01c60f4d649be6172',
 'lib/mono/gac/System.Core/4.0.0.0__b77a5c561934e089/System.Core.dll': '18507d65f274356ca237e7ff69eae1bd5f4e3ef3ad4c611b83cb65eebdbcf65f',
 'lib/mono/gac/System.Management/4.0.0.0__b03f5f7f11d50a3a/System.Management.dll': '1d2f8c36846a0a1a1b9e2e9defcf03aa15052b989436bc411ff79a5104f6d5c6',
 'lib/mono/gac/System.Xml/4.0.0.0__b77a5c561934e089/System.Xml.dll': '95b7a14296050b5e5b73753b84cddc54ef90b94aaad0af980df4746dba8f9fd4',
 'lib/mono/gac/System/4.0.0.0__b77a5c561934e089/System.dll': '5d5c56e3a70e873e8f8c514cc5db15c8647c8b0933b7eeae11a5e9705f5c8386'}
VENDOR_HASHES = {'Firmware/eDLTFirmware/eDLTFirmware_1.3.0.zip': '47c58e7dfefae4786c2536b6949e5fafa8c8877a0e3785791a35884809b4ac3d',
 'Firmware/eDLTFirmware/eDLTFirmware_1.4.0.zip': 'b069b3aa6aa414839d880fd8163f15db8afa6de67475925a5f27bf75267daa61',
 'Firmware/eDLTFirmware/eDLTFirmware_1.5.0.zip': '93e258c9bf2482a20579a4abf1d125956fe074a11ed8ef823e871773870a946b',
 'Firmware/eDLTFirmware/eDLTFirmware_1.7.0.zip': 'f937ccf1ec0d13939e0ba677ee54fe44b2d4a250fe0b578a0dd82effbbc05a34',
 'FirmwareUpdater.exe': 'f54ea945167436b8a3e95decb1d146d01d60e4af1badcd34f4bad626df1e54d5'}

DLLMAP = b'<configuration>\n  <dllmap dll="libutil.so.1" target="/usr/lib/libSystem.B.dylib" os="osx" />\n  <dllmap dll="libc.so.6" target="/usr/lib/libSystem.B.dylib" os="osx" />\n</configuration>\n'


def selected_firmware_backend():
    value = os.environ.get('CBUS_FIRMWARE_ORACLE_BACKEND', 'docker')
    if value not in ('docker', 'macos-mono'):
        raise ValueError('Firmware oracle backend must be exactly docker or macos-mono')
    return value


class MacOSFirmwareOracle:
    """Validate exact artifacts before each bounded compile/run; never retry.

    compile() and run() return actual subprocess.CompletedProcess values. A
    nonzero compile cannot be run. Instances own one disposable directory and
    one execution; the original probe itself creates and closes the PTY pair.
    """
    def __init__(self, app, *, mono_root=None, timeout=30):
        if platform.system() != 'Darwin':
            raise ValueError('macos-mono requires macOS')
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= 60:
            raise ValueError('Timeout must be positive and at most 60 seconds')
        selected_root = os.environ.get('CBUS_MONO_MACOS_ROOT') if mono_root is None else mono_root
        if not selected_root:
            raise ValueError('Explicit CBUS_MONO_MACOS_ROOT is required')
        self.runtime = Path(selected_root).resolve()
        self.app = Path(app).resolve()
        self.source = Path(__file__).resolve().with_name('NativeFirmwareProbe.cs')
        self.timeout = timeout
        self._temporary = None
        self._compiled = None
        self._compiled_exe_hash = None
        self._compile_attempted = False
        self._run_attempted = False
        self._closed = False
        self._verify()
        self.source_bytes = self.source.read_bytes()
        self.env = {key: value for key, value in os.environ.items()
                    if not key.startswith(('MONO_', 'DYLD_'))}
        self.env.update(MONO_CFG_DIR=str(self.runtime / 'etc'),
            MONO_PATH=str(self.app) + ':' + str(self.runtime / 'lib/mono/4.5'),
            DYLD_FALLBACK_LIBRARY_PATH=str(self.runtime / 'lib'))

    @staticmethod
    def _check_files(directory, hashes):
        for name, expected in hashes.items():
            path = directory / name
            if not path.is_file() or not path.resolve().is_relative_to(directory) or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError('Pinned original artifact differs: ' + name)

    def _verify(self):
        self._check_files(self.runtime, RUNTIME_HASHES)
        self._check_files(self.app, VENDOR_HASHES)
        if not self.source.is_file() or hashlib.sha256(self.source.read_bytes()).hexdigest() != PROBE_SHA256:
            raise ValueError('Pinned unchanged firmware probe differs')
        packages = sorted(path.name for path in (self.app / 'Firmware/eDLTFirmware').glob('*.zip'))
        if packages != sorted(Path(name).name for name in VENDOR_HASHES if name.endswith('.zip')):
            raise ValueError('Original firmware package inventory differs')

    @property
    def evidence(self):
        return {'backend': 'macos-mono', 'package_sha256': PACKAGE_SHA256,
            'runtime_version': '6.12.0.206', 'architecture': 'amd64',
            'runtime_hashes': dict(RUNTIME_HASHES), 'vendor_hashes': dict(VENDOR_HASHES),
            'probe_sha256': PROBE_SHA256, 'probe_source_unchanged': True,
            'dllmap_sha256': hashlib.sha256(DLLMAP).hexdigest(),
            'transport': 'owned POSIX pseudo-terminal and original System.IO.Ports.SerialPort',
            'darwin_libraries': {'libutil.so.1': '/usr/lib/libSystem.B.dylib', 'libc.so.6': '/usr/lib/libSystem.B.dylib'},
            'physical_hardware_accessed': False, 'global_installation': False,
            'compile_attempted': self._compile_attempted, 'run_attempted': self._run_attempted,
            'compiled_exe_sha256': self._compiled_exe_hash}

    def compile(self):
        if self._closed or self._compile_attempted:
            raise RuntimeError('An oracle instance permits one compile attempt')
        self._verify()
        self._temporary = tempfile.TemporaryDirectory(prefix='cbus-firmware-macos-')
        self.work = Path(self._temporary.name)
        (self.work / 'NativeFirmwareProbe.cs').write_bytes(self.source_bytes)
        (self.work / 'NativeFirmwareProbe.exe.config').write_bytes(DLLMAP)
        self._compile_attempted = True
        self._compiled = subprocess.run([str(self.runtime / 'bin/mono-sgen64'),
            str(self.runtime / 'lib/mono/4.5/mcs.exe'), '-r:' + str(self.app / 'FirmwareUpdater.exe'),
            'NativeFirmwareProbe.cs'], cwd=self.work, env=self.env,
            capture_output=True, text=True, timeout=self.timeout)
        self._verify()
        if self._compiled.returncode == 0:
            self._compiled_exe_hash = hashlib.sha256((self.work / 'NativeFirmwareProbe.exe').read_bytes()).hexdigest()
        return self._compiled

    def run(self):
        if self._closed or self._compiled is None or self._compiled.returncode != 0 or self._run_attempted:
            raise RuntimeError('Run requires one successful compile and permits one attempt')
        self._verify()
        if (self.work / 'NativeFirmwareProbe.cs').read_bytes() != self.source_bytes or (self.work / 'NativeFirmwareProbe.exe.config').read_bytes() != DLLMAP:
            raise ValueError('Owned probe input changed after compilation')
        if hashlib.sha256((self.work / 'NativeFirmwareProbe.exe').read_bytes()).hexdigest() != self._compiled_exe_hash:
            raise ValueError('Compiled probe changed before execution')
        self._run_attempted = True
        result = subprocess.run([str(self.runtime / 'bin/mono-sgen64'), str(self.work / 'NativeFirmwareProbe.exe'),
            *(str(self.app / name) for name in sorted(VENDOR_HASHES) if name.endswith('.zip'))],
            cwd=self.work, env=self.env, capture_output=True, text=True, timeout=self.timeout)
        self._verify()
        return result

    def close(self):
        self._closed = True
        if self._temporary is not None:
            self._temporary.cleanup()
            self._temporary = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
