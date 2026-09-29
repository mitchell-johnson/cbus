"""SHA-256-bound Toolkit DLTP icon index for eDLT ``ICON`` dynamic labels.

``CBusNetwork.LoadChineseCharacterImages`` reads
``<application base>\\Images\\DLTP\\Index.txt``.  Each line is
``N,Name,file.bmp``; the loader keeps ``(int.Parse(N), Image.FromFile(file))``
and stops silently at the first error.  ``TagDLT.PopulateImage`` gives an
``ICON`` variant an image when ``key.ToString() == TagValue`` exactly.

This loader is stricter than that partial-prefix behavior.  It binds the index
bytes to a caller-supplied SHA-256, resolves each path component
case-insensitively (the original runs on a case-insensitive file system), and
rejects malformed, duplicate or unresolved rows instead of keeping a prefix.
It never decodes, renders or copies the referenced images.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import stat

MAX_INDEX_BYTES = 1024 * 1024
MAX_IMAGE_BYTES = 4 * 1024 * 1024
MAX_ROWS = 4096
_SHA256 = re.compile('[0-9a-f]{64}')
_KEY = re.compile('0|[1-9][0-9]{0,9}')


class DltpIndexError(ValueError):
    """The supplied Toolkit DLTP index is not the admitted strict profile."""


@dataclass(frozen=True)
class DltpIndexEntry:
    key: int
    name: str
    file_name: str
    file_sha256: str

    def as_dict(self):
        return {'key': self.key, 'name': self.name, 'file_name': self.file_name,
                'file_sha256': self.file_sha256}


@dataclass(frozen=True)
class DltpIndex:
    index_sha256: str
    entries: tuple[DltpIndexEntry, ...]

    def image_present(self, tag_value):
        """``TagDLT.PopulateImage`` ICON match: exact ``key.ToString()`` text."""
        if not isinstance(tag_value, str):
            raise DltpIndexError('ICON TagValue must be text')
        return any(str(entry.key) == tag_value for entry in self.entries)

    def as_dict(self):
        return {'format': 'cbus-toolkit-dltp-index-v1',
                'index_sha256': self.index_sha256, 'rows': len(self.entries),
                'entries': [entry.as_dict() for entry in self.entries],
                'images_decoded': False}

    def evidence(self):
        return {'index_sha256': self.index_sha256, 'rows': len(self.entries),
                'keys': [entry.key for entry in self.entries],
                'image_files_sha256': hashlib.sha256(''.join(
                    entry.file_sha256 for entry in self.entries).encode()).hexdigest()}


def parse_dltp_index(raw):
    """Parse index bytes into ``(key, name, file name)`` rows."""
    if type(raw) is not bytes or not raw or len(raw) > MAX_INDEX_BYTES:
        raise DltpIndexError('DLTP index must be 1 byte to 1 MiB')
    if raw.startswith(b'\xef\xbb\xbf') or b'\0' in raw:
        raise DltpIndexError('DLTP index must be plain UTF-8 without BOM or NUL')
    try:
        text = raw.decode('utf-8', 'strict')
    except UnicodeDecodeError as error:
        raise DltpIndexError('DLTP index is not valid UTF-8') from error
    # StreamReader.ReadLine treats CRLF, LF and CR as terminators and returns
    # a final unterminated line.  An empty line would stop the original load.
    lines = re.split('\r\n|\n|\r', text)
    if lines[-1] == '':
        lines.pop()
    if not lines or len(lines) > MAX_ROWS:
        raise DltpIndexError(f'DLTP index must contain 1..{MAX_ROWS} rows')
    rows, keys, files = [], set(), set()
    for number, line in enumerate(lines, 1):
        fields = line.split(',')
        if len(fields) != 3:
            raise DltpIndexError(f'DLTP index row {number} must have exactly three fields')
        key, name, file_name = fields
        if _KEY.fullmatch(key) is None or int(key) >= 2**31:
            raise DltpIndexError(f'DLTP index row {number} key must be a canonical Int32')
        if not name or any(ord(char) < 32 or ord(char) == 127 for char in name + file_name):
            raise DltpIndexError(f'DLTP index row {number} has an empty name or control text')
        if (not file_name or file_name != file_name.strip()
                or any(char in file_name for char in '\\/:')
                or file_name in ('.', '..')
                or not file_name.lower().endswith('.bmp')):
            raise DltpIndexError(f'DLTP index row {number} must name one bare .bmp file')
        if int(key) in keys:
            raise DltpIndexError(f'DLTP index row {number} duplicates key {key}')
        if file_name.casefold() in files:
            raise DltpIndexError(f'DLTP index row {number} duplicates an image file')
        keys.add(int(key)); files.add(file_name.casefold())
        rows.append((int(key), name, file_name))
    return tuple(rows)


def _entries(directory):
    try:
        return {entry.name: entry for entry in os.scandir(directory)}
    except OSError as error:
        raise DltpIndexError('Cannot list DLTP directory component') from error


def _component(directory, name, *, directory_expected):
    """Resolve one path component with Windows-style case-insensitive lookup."""
    matches = [entry for key, entry in _entries(directory).items()
               if key.casefold() == name.casefold()]
    if len(matches) != 1:
        raise DltpIndexError(
            f'Expected exactly one case-insensitive {name!r} in the Toolkit install')
    entry = matches[0]
    mode = entry.stat(follow_symlinks=False).st_mode
    expected = stat.S_ISDIR(mode) if directory_expected else stat.S_ISREG(mode)
    if stat.S_ISLNK(mode) or not expected:
        raise DltpIndexError(f'Toolkit install component {entry.name!r} has the wrong type')
    return Path(entry.path)


def _read(path, limit):
    with open(path, 'rb') as source:
        raw = source.read(limit + 1)
    if len(raw) > limit:
        raise DltpIndexError(f'{path.name} exceeds {limit} bytes')
    return raw


def load_dltp_index(application_directory, *, expected_sha256):
    """Load ``Images/DLTP/Index.txt`` below a Toolkit application directory."""
    if not isinstance(expected_sha256, str) or _SHA256.fullmatch(expected_sha256) is None:
        raise DltpIndexError('Expected DLTP index SHA-256 must be 64 lowercase hex digits')
    base = Path(application_directory)
    if not base.is_dir() or base.is_symlink():
        raise DltpIndexError('Toolkit application directory must be a real directory')
    images = _component(base, 'Images', directory_expected=True)
    dltp = _component(images, 'DLTP', directory_expected=True)
    raw = _read(_component(dltp, 'Index.txt', directory_expected=False), MAX_INDEX_BYTES)
    digest = hashlib.sha256(raw).hexdigest()
    if digest != expected_sha256:
        raise DltpIndexError('DLTP index SHA-256 differs from the supplied binding')
    entries = []
    for key, name, file_name in parse_dltp_index(raw):
        image = _read(_component(dltp, file_name, directory_expected=False), MAX_IMAGE_BYTES)
        if not image.startswith(b'BM'):
            raise DltpIndexError(f'DLTP image {file_name!r} is not a BMP file')
        entries.append(DltpIndexEntry(key, name, file_name, hashlib.sha256(image).hexdigest()))
    return DltpIndex(digest, tuple(entries))
