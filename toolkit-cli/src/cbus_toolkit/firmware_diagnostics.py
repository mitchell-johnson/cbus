"""Read-only eDLT USB diagnostics and firmware package directory metadata.

Wire/parser evidence is the original FirmwareUpdater 1.16.3 assembly. This
module never extracts firmware, enters update mode, restarts or writes flash.
"""
from dataclasses import dataclass
import hashlib
import math
import ntpath
from pathlib import Path
import re
import sys
import time
from types import MappingProxyType
import zipfile


class DiagnosticError(RuntimeError):
    def __init__(self, message, *, fields=None, messages=()):
        self.details = {'complete': False, 'fields': dict(fields or {}), 'messages': list(messages),
                        'read_only': True, 'firmware_contents_verified': False}
        super().__init__(message)


VARIANTS = ('Unknown', 'StellarisPCI', 'TivaPCI', 'TivaNCC')
_DOTNET_WHITESPACE = frozenset('\t\n\v\f\r \u0085\u00a0\u1680\u2028\u2029\u202f\u205f\u3000') | frozenset(chr(n) for n in range(0x2000, 0x200B))
ID_FIELDS = (
    ('Manufacturer', 'Model', 'Serial Number', 'Version', 'Authors', 'Cpu_Speed', 'Unit Address'),
    ('Manufacturer', 'Product', 'Serial Number', 'HW Version', 'FW Version', 'Authors', 'Cpu_Speed', 'Unit Address'),
    ('Manufacturer', 'Product', 'Serial Number', 'HW Version', 'FW Version', 'CPU Speed', 'Unit Address'),
)


def classify_hardware(version):
    """Exact original HardwareVersion setter, including asymmetric casing."""
    if version is None or isinstance(version, str) and all(c in _DOTNET_WHITESPACE for c in version):
        return 'StellarisPCI'
    if not isinstance(version, str):
        raise ValueError('Hardware version must be text or None')
    if version in ('1 (Stellaris)', '1.0 (Stellaris + PCI)'):
        return 'StellarisPCI'
    if version.lower() == '2 (tiva)' or version == '2.0 (Tiva + PCI)':
        return 'TivaPCI'
    if version == '3.0 (Tiva + NCC)':
        return 'TivaNCC'
    return 'Unknown'


def package_version(filename):
    """Windows basename without extension, then text after first underscore."""
    if not isinstance(filename, str) or '\0' in filename or len(filename) > 4096:
        raise ValueError('Expected a bounded package filename')
    stem = ntpath.splitext(ntpath.basename(filename))[0]
    return stem[stem.find('_') + 1:]


def _version(value):
    # System.Version has two mandatory and two optional nonnegative Int32
    # components. Missing build/revision compare as -1, not zero.
    if not isinstance(value, str) or not 2 <= len(value.split('.')) <= 4:
        raise ValueError('Expected a .NET version with two to four integer components')
    if any(not re.fullmatch(r'[ \t\n\v\f\r]*[+-]?[0-9]+[ \t\n\v\f\r]*', part) for part in value.split('.')):
        raise ValueError('Expected integer version components')
    parts = tuple(int(part) for part in value.split('.'))
    if any(not 0 <= part <= 2147483647 for part in parts):
        raise ValueError('Version component must be a nonnegative Int32')
    return parts + (-1,) * (4 - len(parts))


def compare_versions(first, second):
    a, b = _version(first), _version(second)
    return (a > b) - (a < b)


class DiagnosticParser:
    """Incremental original CRLF parsing with additional resource bounds."""
    def __init__(self, command, *, max_bytes=65536, max_line=4096, max_fields=256):
        if command not in ('id', 'nv'):
            raise ValueError('Only read-only id and nv diagnostic commands are supported')
        for value in (max_bytes, max_line, max_fields):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError('Parser bounds must be positive integers')
        self.command, self.max_bytes, self.max_line, self.max_fields = command, max_bytes, max_line, max_fields
        self.fields, self.messages, self.conflicts = {}, [], set()
        self._buffer, self._received = '', 0

    def feed(self, data):
        if not isinstance(data, bytes):
            raise ValueError('Diagnostic stream chunks must be bytes')
        self._received += len(data)
        if self._received > self.max_bytes:
            self._error('Diagnostic response exceeds byte limit')
        try:
            text = data.decode('ascii')
        except UnicodeDecodeError:
            self._error('Non-ASCII diagnostic response is outside the verified protocol')
        if any(ord(c) < 32 and c not in '\r\n\t' for c in text):
            self._error('Control character in diagnostic response')
        self._buffer += text
        while '\r\n' in self._buffer:
            line, self._buffer = self._buffer.split('\r\n', 1)
            if len(line) > self.max_line:
                self._error('Diagnostic line exceeds limit')
            self.messages.append(line)
            separator = '=' if self.command == 'id' else ':'
            if separator in line:
                key, value = line.split(separator, 1)
                value = value.strip()
                if self.command == 'id':
                    key = key.strip()
            else:
                key, value = line, ''
            if key in self.fields and self.fields[key] != value:
                self.conflicts.add(key)
            if key not in self.fields and len(self.fields) >= self.max_fields:
                self._error('Diagnostic response exceeds field limit')
            self.fields[key] = value
        if len(self._buffer) > self.max_line:
            self._error('Diagnostic line exceeds limit')

    def _error(self, message):
        raise DiagnosticError(message, fields=self.fields, messages=self.messages)

    @property
    def complete(self):
        if self.command == 'id':
            return any(set(required) <= self.fields.keys() for required in ID_FIELDS)
        return {'NCC current version', 'NCC embedded version'} <= self.fields.keys() or 'COMMAND NOT VALID' in self.fields

    def result(self):
        if not self.complete:
            self._error('Incomplete diagnostic response')
        if self.command == 'id':
            return Identification.from_fields(self.fields, conflicts=self.conflicts, messages=self.messages)
        return NCCVersions.from_fields(self.fields, conflicts=self.conflicts, messages=self.messages)


@dataclass(frozen=True)
class Identification:
    fields: object
    schemas: tuple
    hardware_version: str
    firmware_version: str
    variant: str
    ambiguous: bool
    messages: tuple = ()

    @classmethod
    def from_fields(cls, fields, *, conflicts=(), messages=()):
        if not isinstance(fields, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in fields.items()):
            raise ValueError('Identification fields must map text to text')
        schemas = tuple(f'firmware{i + 1}' for i, required in enumerate(ID_FIELDS) if set(required) <= fields.keys())
        if not schemas:
            raise DiagnosticError('Identification does not contain a complete native field set', fields=fields)
        hardware = fields.get('HW Version', '')
        firmware = fields.get('Version', fields.get('FW Version', ''))
        ambiguous = bool(conflicts) or any(a in fields and b in fields and fields[a] != fields[b]
                                          for a, b in (('Version', 'FW Version'), ('Model', 'Product')))
        return cls(MappingProxyType(dict(fields)), schemas, hardware, firmware,
                   classify_hardware(hardware), ambiguous, tuple(messages))

    def as_dict(self):
        return {'complete': True, 'usable_identity': self.usable_identity, 'ambiguous': self.ambiguous, 'schemas': list(self.schemas),
                'hardware_version': self.hardware_version, 'firmware_version': self.firmware_version,
                'variant': self.variant, 'fields': dict(self.fields), 'messages': list(self.messages),
                'read_only': True, 'firmware_contents_verified': False}

    @property
    def usable_identity(self):
        # Native "complete" tests only field presence. Keep that fact while
        # distinguishing blank/conflicting identification from usable data.
        product = self.fields.get('Model', self.fields.get('Product', ''))
        return (not self.ambiguous and self.variant != 'Unknown' and
                all(value.strip() for value in (self.fields.get('Manufacturer', ''), product,
                    self.fields.get('Serial Number', ''), self.fields.get('Unit Address', ''), self.firmware_version)))


@dataclass(frozen=True)
class NCCVersions:
    fields: object
    supported: bool
    current_version: str
    embedded_version: str
    update_available: object
    ambiguous: bool
    reason: str
    messages: tuple = ()

    @classmethod
    def from_fields(cls, fields, *, conflicts=(), messages=()):
        have_versions = {'NCC current version', 'NCC embedded version'} <= fields.keys()
        unsupported = 'COMMAND NOT VALID' in fields
        if not have_versions and not unsupported:
            raise DiagnosticError('Incomplete NCC version response', fields=fields)
        current, embedded = fields.get('NCC current version', ''), fields.get('NCC embedded version', '')
        reason = 'COMMAND NOT VALID' if unsupported and not have_versions else ''
        update = None
        if have_versions:
            try:
                update = compare_versions(embedded, current) > 0
            except ValueError as error:
                reason = str(error)
        return cls(MappingProxyType(dict(fields)), have_versions, current, embedded, update,
                   bool(conflicts) or have_versions and unsupported, reason, tuple(messages))

    def as_dict(self):
        return {'complete': self.supported and not self.ambiguous and not self.reason,
                'supported': self.supported, 'current_version': self.current_version,
                'embedded_version': self.embedded_version, 'update_available': self.update_available,
                'ambiguous': self.ambiguous, 'reason': self.reason, 'fields': dict(self.fields),
                'messages': list(self.messages), 'read_only': True, 'firmware_contents_verified': False}


def parse_identification(data):
    parser = DiagnosticParser('id')
    parser.feed(data)
    return parser.result()


def parse_ncc_versions(data):
    parser = DiagnosticParser('nv')
    parser.feed(data)
    return parser.result()


class SerialDiagnostics:
    def __init__(self, port, *, timeout=10, serial_factory=None):
        if not isinstance(port, str) or not port.strip() or any(ord(c) < 32 for c in port):
            raise ValueError('An explicit serial port is required')
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 < timeout <= 60:
            raise ValueError('Diagnostic timeout must be positive and at most 60 seconds')
        self.port, self.timeout, self.serial_factory = port, timeout, serial_factory

    def _query(self, command):
        factory = self.serial_factory
        if factory is None:
            try:
                from serial import Serial
            except ImportError as error:
                raise DiagnosticError('Install cbus-toolkit-cli[serial] for serial diagnostics') from error
            factory = Serial
        parser, stream = DiagnosticParser(command), None
        try:
            stream = factory(port=self.port, baudrate=9600, bytesize=8, parity='N', stopbits=1,
                             xonxoff=False, rtscts=False, dsrdtr=False,
                             timeout=min(self.timeout, 0.05), write_timeout=self.timeout)
            request = command.encode('ascii') + b'\r'
            if stream.write(request) != len(request):
                raise DiagnosticError('Short diagnostic command write')
            deadline = time.monotonic() + self.timeout
            while time.monotonic() < deadline:
                parser.feed(stream.read(1024))
                if parser.complete:
                    return parser.result()
            parser._error('Timed out while waiting for response from unit')
        except DiagnosticError:
            raise
        except Exception as error:
            raise DiagnosticError(str(error), fields=parser.fields, messages=parser.messages) from error
        finally:
            if stream is not None:
                primary = sys.exc_info()[1]
                try:
                    stream.close()
                except Exception as error:
                    if primary is None:
                        raise DiagnosticError('Diagnostic port close failed: ' + str(error),
                                              fields=parser.fields, messages=parser.messages) from error
                    if isinstance(primary, DiagnosticError):
                        primary.details['close_error'] = str(error)

    def identify(self):
        return self._query('id')

    def ncc_versions(self):
        return self._query('nv')


def inspect_package(path):
    """Read only ZIP directory metadata and hash; never extract/decrypt data."""
    path = Path(path)
    if path.stat().st_size > 512 * 1024 * 1024:
        raise ValueError('Firmware package exceeds 512 MiB metadata inspection limit')
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    selections = {variant: [] for variant in VARIANTS[1:]}
    fonts, entries, unknown, invalid = [], [], [], []
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile as error:
        raise ValueError('Firmware package is not a valid ZIP archive') from error
    with archive:
        info = archive.infolist()
        if len(info) > 1024:
            raise ValueError('Firmware package exceeds 1024 directory entries')
        for item in info:
            name = item.filename
            if len(name) > 4096:
                raise ValueError('Firmware package entry name exceeds limit')
            entries.append({'name': name, 'bytes': item.file_size, 'encrypted': bool(item.flag_bits & 1),
                            'crc32': f'{item.CRC:08x}'})
            if name.endswith(('/', '\\')) or item.create_system in (0, 10) and item.external_attr & 0x18:
                invalid.append(name)
                continue
            # Original selection is case-sensitive and first matching branch
            # wins for each entry. Later matching entries replace earlier ones.
            if 'main' in name and 'hwv1' in name:
                selections['StellarisPCI'].append(name)
            elif 'main' in name and 'hwv2' in name:
                selections['TivaPCI'].append(name)
            elif 'main' in name and 'hwv3' in name:
                selections['TivaNCC'].append(name)
            elif 'font' in name:
                fonts.append(name)
            else:
                unknown.append(name)
    return {'format': 'cbus-edlt-package-metadata-v1', 'name': path.name, 'version': package_version(path.name),
            'sha256': digest.hexdigest(), 'entries': entries, 'image_candidates': selections,
            'font_candidates': fonts, 'unknown_entries': unknown, 'native_invalid_entries': invalid, 'read_only': True,
            'image_contents_verified': False, 'archive_extracted': False}


def compare_package(identification, package):
    if not isinstance(identification, Identification):
        raise ValueError('A parsed Identification is required')
    if not isinstance(package, dict) or package.get('format') != 'cbus-edlt-package-metadata-v1':
        raise ValueError('Inspect a firmware package before comparing it')
    images = package['image_candidates'].get(identification.variant, [])
    fonts = package['font_candidates']
    ambiguous = identification.ambiguous or len(images) > 1 or len(fonts) > 1
    try:
        comparison = compare_versions(package['version'], identification.firmware_version)
        relation = {-1: 'older', 0: 'same', 1: 'newer'}[comparison]
    except ValueError:
        relation = 'unparseable'
    return {'variant': identification.variant, 'current_version': identification.firmware_version,
            'package_version': package['version'], 'version_relation': relation,
            'variant_images_present': bool(images and fonts), 'ambiguous': ambiguous,
            'native_selected_image': images[-1] if images else None,
            'native_selected_font': fonts[-1] if fonts else None,
            'native_invalid_entries': package.get('native_invalid_entries', []),
            'usable_identity': identification.usable_identity,
            'metadata_match': bool(images and fonts) and not ambiguous and identification.usable_identity
                              and not package.get('native_invalid_entries'),
            'read_only': True, 'image_contents_verified': False, 'update_implemented': False}
