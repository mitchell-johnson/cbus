"""Byte-backed ordered project image export for native eDLT label metadata.

The export is an explicit complete FILE directory/download input, not a server
fetch. Toolkit selects project-prefixed .bmp files in directory order, decodes
their downloaded bytes, and uses the last four characters before the first dot
as their keys. This module decodes a bounded Windows BI_RGB BMP profile; it does
not emulate GDI+, culture-sensitive filename matching, rendering or opacity.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import struct
from weakref import WeakKeyDictionary

MAX_EXPORT_BYTES = 24 * 1024 * 1024
MAX_IMAGE_BYTES = 4 * 1024 * 1024
MAX_TOTAL_IMAGE_BYTES = 16 * 1024 * 1024
MAX_PIXELS = 1024 * 1024
MAX_FILES = 4096
_SHA = re.compile(r'[0-9a-f]{64}')
_PROJECT = re.compile(r'[A-Za-z0-9_-]{1,64}')


class LabelImageError(ValueError):
    pass


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def decode_bmp(raw):
    """Decode indexed 1/4/8 and RGB 16/24/32-bit BITMAPINFOHEADER pixels.

    RGB32's fourth storage byte is not treated as alpha. The receipt hashes RGB
    sample values and original bytes separately, making no opacity claim.
    """
    if type(raw) is not bytes or not 54 <= len(raw) <= MAX_IMAGE_BYTES:
        raise LabelImageError('BMP must contain 54 bytes to 4 MiB')
    if raw[:2] != b'BM':
        raise LabelImageError('Project image must be a BMP')
    size, reserved, offset = struct.unpack_from('<III', raw, 2)
    header, width, height, planes, bits, compression, image_size = struct.unpack_from('<IiiHHII', raw, 14)
    used = struct.unpack_from('<I', raw, 46)[0]
    if (size != len(raw) or reserved != 0 or header != 40 or planes != 1
            or compression != 0 or bits not in (1, 4, 8, 16, 24, 32)
            or not 1 <= width <= 4096 or not 1 <= abs(height) <= 4096
            or width * abs(height) > MAX_PIXELS):
        raise LabelImageError('BMP is outside the admitted bounded BI_RGB profile')
    stride = ((width * bits + 31) // 32) * 4
    expected = stride * abs(height)
    colors = (used or (1 << bits)) if bits <= 8 else used
    if (bits <= 8 and colors > 1 << bits or bits > 8 and colors != 0
            or offset < 54 + colors * 4 or offset + expected != len(raw)
            or image_size not in (0, expected)):
        raise LabelImageError('BMP pixel/palette spans are inconsistent')
    palette = tuple(tuple(raw[54 + n * 4:57 + n * 4][::-1]) for n in range(colors))
    rgb = bytearray()
    for y in range(abs(height)):
        stored_y = y if height < 0 else abs(height) - 1 - y
        row = raw[offset + stored_y * stride:offset + (stored_y + 1) * stride]
        for x in range(width):
            if bits <= 8:
                index = (row[x] if bits == 8 else
                         (row[x // 2] >> (4 if x % 2 == 0 else 0)) & 15 if bits == 4 else
                         (row[x // 8] >> (7 - x % 8)) & 1)
                if index >= colors:
                    raise LabelImageError('BMP pixel references an absent palette entry')
                rgb.extend(palette[index])
            elif bits == 16:
                value = int.from_bytes(row[x * 2:x * 2 + 2], 'little')
                rgb.extend(((value >> shift & 31) * 255 // 31 for shift in (10, 5, 0)))
            else:
                start = x * (bits // 8)
                rgb.extend(row[start:start + 3][::-1])
    return {'format': 'windows-bmp-info40-bi-rgb', 'width': width,
            'height': abs(height), 'bits_per_pixel': bits,
            'rgb_sha256': _sha(bytes(rgb)), 'file_sha256': _sha(raw),
            'opacity_modeled': False}


@dataclass(frozen=True)
class ProjectImage:
    key: str
    file_name: str
    file_sha256: str
    width: int
    height: int
    bits_per_pixel: int
    rgb_sha256: str

    def as_dict(self):
        return dict(key=self.key, file_name=self.file_name,
                    file_sha256=self.file_sha256, width=self.width,
                    height=self.height, bits_per_pixel=self.bits_per_pixel,
                    rgb_sha256=self.rgb_sha256)


class _Seal:
    __slots__ = ('__weakref__',)


_ISSUED = WeakKeyDictionary()


def _issue(value):
    _ISSUED[value._seal] = value.fingerprint
    return value


@dataclass(frozen=True)
class ProjectImages:
    project: str
    export_sha256: str
    entries: tuple[ProjectImage, ...]
    directory_files: int
    _seal: _Seal

    @property
    def fingerprint(self):
        value = [self.project, self.export_sha256, self.directory_files,
                 [row.as_dict() for row in self.entries]]
        return _sha(json.dumps(value, separators=(',', ':'), ensure_ascii=True).encode('ascii'))

    def match(self, key):
        check_project_images(self)
        if type(key) is not str:
            raise LabelImageError('Project image key must be exact text')
        return next((row for row in self.entries if row.key == key), None)

    def image_present(self, key):
        return self.match(key) is not None

    def evidence(self):
        check_project_images(self)
        return {'format': 'cbus-edlt-project-images-v1', 'project': self.project,
                'export_sha256': self.export_sha256, 'sha256': self.fingerprint,
                'directory_files': self.directory_files, 'rows': len(self.entries),
                'entries': [row.as_dict() for row in self.entries],
                'images_decoded': True, 'decoder_profile': 'windows-bmp-info40-bi-rgb',
                'complete_directory_declared': True, 'server_directory_observed': False,
                'gdi_decoder_equivalence': False, 'opacity_modeled': False}


def check_project_images(value, *, project=None):
    if (type(value) is not ProjectImages or type(value._seal) is not _Seal
            or _ISSUED.get(value._seal) != value.fingerprint):
        raise LabelImageError('Project images are foreign, serialized or modified')
    if project is not None and value.project != project:
        raise LabelImageError('Project images belong to another project')
    return value


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise LabelImageError('Project image export contains duplicate JSON keys')
        result[key] = value
    return result


def parse_project_images(raw, *, expected_sha256):
    if type(expected_sha256) is not str or _SHA.fullmatch(expected_sha256) is None:
        raise LabelImageError('Expected image export SHA-256 must be lowercase hex')
    if type(raw) is not bytes or not 1 <= len(raw) <= MAX_EXPORT_BYTES or _sha(raw) != expected_sha256:
        raise LabelImageError('Image export bytes differ from their SHA-256/size binding')
    try:
        payload = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique_pairs)
    except (ValueError, UnicodeError) as error:
        raise LabelImageError('Image export must be valid unique-key UTF-8 JSON') from error
    if (type(payload) is not dict or set(payload) != {'format', 'project', 'complete', 'directory_names', 'files'}
            or payload['format'] != 'cbus-edlt-project-images-v1' or payload['complete'] is not True
            or type(payload['project']) is not str or _PROJECT.fullmatch(payload['project']) is None
            or type(payload['files']) is not list or len(payload['files']) > MAX_FILES
            or type(payload['directory_names']) is not list or len(payload['directory_names']) > MAX_FILES):
        raise LabelImageError('Invalid complete project image export schema')
    names = payload['directory_names']
    if (any(type(name) is not str or not 1 <= len(name) <= 255
            or any(not 32 <= ord(c) < 127 or c in '\\:' for c in name)
            or '/' in name.rstrip('/') or name in ('.', '..', '/') for name in names)
            or len(set(names)) != len(names)):
        raise LabelImageError('Directory names must be bounded unique ASCII names in received order')
    selected = [name for name in names
                if name.startswith(payload['project'] + '-DLTD-Pic') and name.endswith('.bmp')]
    if ([row.get('name') if type(row) is dict else None for row in payload['files']] != selected
            or any(any(c.isspace() for c in name) for name in selected)):
        raise LabelImageError('Files must exactly match the source ASCII selection in directory order')
    entries, total = [], 0
    for row in payload['files']:
        if (type(row) is not dict or set(row) != {'name', 'sha256', 'data_base64'}
                or type(row['name']) is not str or not 1 <= len(row['name']) <= 255
                or any(not 32 <= ord(c) < 127 or c in '/\\:' for c in row['name'])
                or row['name'] in ('.', '..') or type(row['sha256']) is not str
                or _SHA.fullmatch(row['sha256']) is None or type(row['data_base64']) is not str
                or len(row['data_base64']) > (MAX_IMAGE_BYTES + 2) // 3 * 4):
            raise LabelImageError('Invalid bounded image export file row')
        try:
            data = base64.b64decode(row['data_base64'], validate=True)
        except ValueError as error:
            raise LabelImageError('Project image Base64 is invalid') from error
        if _sha(data) != row['sha256']:
            raise LabelImageError('Project image file SHA-256 differs')
        total += len(data)
        if total > MAX_TOTAL_IMAGE_BYTES:
            raise LabelImageError('Project image export exceeds 16 MiB of decoded file bytes')
        decoded = decode_bmp(data)
        first = row['name'].split('.', 1)[0]
        if len(first) < 4:
            raise LabelImageError('Source image filename cannot supply its four-character key')
        entries.append(ProjectImage(first[-4:], row['name'], row['sha256'],
            decoded['width'], decoded['height'], decoded['bits_per_pixel'], decoded['rgb_sha256']))
    value = ProjectImages(payload['project'], expected_sha256, tuple(entries), len(names), _Seal())
    return _issue(value)


def load_project_images(path, *, expected_sha256):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise LabelImageError('Image export must be a regular file, not a symlink')
    with path.open('rb') as source:
        raw = source.read(MAX_EXPORT_BYTES + 1)
    return parse_project_images(raw, expected_sha256=expected_sha256)


@dataclass(frozen=True)
class DecodedDltpImages:
    """Optional decoded successor; the legacy index loader remains unchanged."""
    index: object
    decoded_entries: tuple[ProjectImage, ...]
    _seal: _Seal

    @property
    def fingerprint(self):
        return _sha(json.dumps([self.index.evidence(), [row.as_dict() for row in self.decoded_entries]],
                              separators=(',', ':'), ensure_ascii=True).encode('ascii'))

    @property
    def entries(self):
        check_dltp_images(self)
        return self.index.entries

    def image_present(self, key):
        check_dltp_images(self)
        return self.index.image_present(key)

    def evidence(self):
        check_dltp_images(self)
        return {**self.index.evidence(), 'images_decoded': True,
                'decoder_profile': 'windows-bmp-info40-bi-rgb',
                'decoded_entries': [row.as_dict() for row in self.decoded_entries],
                'gdi_decoder_equivalence': False, 'opacity_modeled': False}


def check_dltp_images(value):
    from .edlt_dltp_index import DltpIndex
    if type(value) is DltpIndex:
        return value
    if (type(value) is not DecodedDltpImages or type(value._seal) is not _Seal
            or type(value.index) is not DltpIndex or _ISSUED.get(value._seal) != value.fingerprint):
        raise LabelImageError('DLTP images must come from load_dltp_index or its sealed decoded successor')
    return value


def load_decoded_dltp_index(application_directory, *, expected_sha256):
    from .edlt_dltp_index import load_dltp_index, _component, _read, MAX_IMAGE_BYTES
    index = load_dltp_index(application_directory, expected_sha256=expected_sha256)
    directory = _component(_component(Path(application_directory), 'Images', directory_expected=True),
                           'DLTP', directory_expected=True)
    decoded = []
    for entry in index.entries:
        raw = _read(_component(directory, entry.file_name, directory_expected=False), MAX_IMAGE_BYTES)
        if _sha(raw) != entry.file_sha256:
            raise LabelImageError('DLTP image changed between index binding and decoding')
        facts = decode_bmp(raw)
        decoded.append(ProjectImage(str(entry.key), entry.file_name, entry.file_sha256,
                       facts['width'], facts['height'], facts['bits_per_pixel'], facts['rgb_sha256']))
    value = DecodedDltpImages(index, tuple(decoded), _Seal())
    return _issue(value)


@dataclass(frozen=True)
class ProjectImagesExport:
    raw: bytes
    images: ProjectImages
    commands: tuple[dict, ...]

    def as_dict(self):
        return {'format': 'cbus-edlt-project-image-export-receipt-v1',
                'export_sha256': _sha(self.raw), 'export_bytes': len(self.raw),
                'image_input': self.images.evidence(), 'commands': list(self.commands),
                'persistent_mutations': 0, 'automatic_retries': 0,
                'native_directory_authenticity_verified': False,
                'original_execution': False}


def export_project_images(client, project):
    """Export one explicit source-shaped FILE DIR/DOWNLOAD read sequence.

    Only the bounded ASCII ordinal filename profile is admitted. Command and
    response evidence is retained, without host culture or server-authenticity
    inference. Any malformed/failed read stops immediately without a retry.
    """
    if type(project) is not str or _PROJECT.fullmatch(project) is None:
        raise LabelImageError('Image export project must be bounded ASCII text')
    commands = []

    def read(command):
        response = client.command(command)
        lines = getattr(response, 'lines', None)
        final, status = getattr(response, 'final', None), getattr(response, 'status', None)
        if (type(lines) is not tuple or not lines or any(type(row) is not str for row in lines)
                or lines[-1] != final or type(status) is not int
                or sum(len(row) for row in lines) > MAX_EXPORT_BYTES):
            raise LabelImageError('FILE response is not a complete bounded terminal receipt')
        commands.append({'command': command, 'status': status,
                         'response_lines': len(lines),
                         'response_sha256': _sha(json.dumps(list(lines), ensure_ascii=True,
                            separators=(',', ':')).encode('ascii'))})
        return lines, final, status

    path = '%PROJ%/' + project
    lines, final, status = read('FILE DIR ' + path)
    header = re.fullmatch(r'304[- ]directory="([^"\r\n]{1,1024})" files=(0|[1-9][0-9]{0,4})', lines[0])
    if header is None or int(header[2]) > MAX_FILES:
        raise LabelImageError('FILE DIR has an invalid directory header/count')
    count = int(header[2])
    if (len(lines) != count + 1 or status != (305 if count else 304)
            or not final.startswith(str(status) + ' ')
            or (count and not lines[0].startswith('304-'))):
        raise LabelImageError('FILE DIR roster does not match its terminal/count')
    names, sizes = [], {}
    for index, line in enumerate(lines[1:], 1):
        pattern = r'305' + (' ' if index == count else '-') + r'name="([^"\r\n]{1,255})" size=(0|[1-9][0-9]{0,10}) modified=([^\r\n]{1,64})'
        row = re.fullmatch(pattern, line)
        if row is None or row[1] in sizes:
            raise LabelImageError('FILE DIR file row is invalid or repeated')
        names.append(row[1]); sizes[row[1]] = int(row[2])
    selected = [name for name in names if name.startswith(project + '-DLTD-Pic') and name.endswith('.bmp')]
    if sum(sizes[name] for name in selected) > MAX_TOTAL_IMAGE_BYTES:
        raise LabelImageError('Selected FILE images exceed 16 MiB')
    files = []
    for name in selected:
        if (any(not 32 <= ord(c) < 127 or c.isspace() or c in '/\\:' for c in name)
                or not 54 <= sizes[name] <= MAX_IMAGE_BYTES):
            raise LabelImageError('Selected FILE image has unsupported name/size')
        requested = path + '/' + name
        rows, terminal, code = read('FILE DOWNLOAD ' + requested)
        if (code != 346 or terminal != '346 End file download' or len(rows) < 3
                or rows[0] != '345-Start file download for file: ' + requested):
            raise LabelImageError('FILE DOWNLOAD envelope differs from the requested file')
        chunks = []
        for row in rows[1:-1]:
            match = re.fullmatch(r'347-([A-Za-z0-9+/=]{1,76})', row)
            if match is None:
                raise LabelImageError('FILE DOWNLOAD contains an invalid Base64 chunk')
            chunks.append(match[1])
        try:
            data = base64.b64decode(''.join(chunks), validate=True)
        except ValueError as error:
            raise LabelImageError('FILE DOWNLOAD Base64 data is invalid') from error
        if len(data) != sizes[name]:
            raise LabelImageError('FILE DOWNLOAD size differs from its directory observation')
        decode_bmp(data)
        files.append({'name': name, 'sha256': _sha(data), 'data_base64': base64.b64encode(data).decode('ascii')})
    payload = {'format': 'cbus-edlt-project-images-v1', 'project': project,
               'complete': True, 'directory_names': names, 'files': files}
    raw = (json.dumps(payload, indent=2, ensure_ascii=True) + '\n').encode('ascii')
    images = parse_project_images(raw, expected_sha256=_sha(raw))
    return ProjectImagesExport(raw, images, tuple(commands))
