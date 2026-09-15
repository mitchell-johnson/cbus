"""Original Toolkit CSV row semantics for explicit captured report values.

This module does not load project files or construct Toolkit database objects.
UTF-8 output is an explicit portable export, separate from native Windows ACP.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from types import MappingProxyType


MAX_TEXT_UNITS = 256
MAX_UNITS = 4096
MAX_CAPTURE_BYTES = 8 * 1024 * 1024
MAX_OUTPUT_BYTES = 32 * 1024 * 1024
CAPTURE_FORMAT = 'cbus-toolkit-database-report-v1'
COLUMNS = ('address', 'part_name', 'tag_name', 'unit_type', 'catalog', 'serial',
           'firmware', 'primary', 'secondary', 'area',
           *(f'group_{index}' for index in range(1, 17)))
_LABELS = ('Unit Address', 'Part Name', 'Tag Name', 'Unit Type', 'Catalog Number',
           'Serial Number', 'Firmware Version', 'Primary Application',
           'Secondary Application', 'Area', *(f'Group {index}' for index in range(1, 17)))
COLUMN_LABELS = MappingProxyType(dict(zip(COLUMNS, _LABELS)))
_TEXT_FIELDS = COLUMNS[1:9]
_UNIT_FIELDS = frozenset(('address', *_TEXT_FIELDS, 'area', 'groups'))


def _text(value, name):
    if type(value) is not str:
        raise ValueError(name + ' must be a string')
    if len(value) > MAX_TEXT_UNITS:
        raise ValueError(name + ' exceeds 256 UTF-16 code units')
    if '\0' in value:
        raise ValueError(name + ' must not contain NUL')
    try:
        raw = value.encode('utf-16le')
    except UnicodeEncodeError as error:
        raise ValueError(name + ' must not contain unpaired surrogates') from error
    if len(raw) > MAX_TEXT_UNITS * 2:
        raise ValueError(name + ' exceeds 256 UTF-16 code units')
    return value


@dataclass(frozen=True)
class CSVGroupValue:
    tag: str
    interaction: bool

    def __post_init__(self):
        _text(self.tag, 'Group tag')
        if type(self.interaction) is not bool:
            raise ValueError('Group interaction must be a boolean')

    def as_dict(self):
        return {'tag': self.tag, 'interaction': self.interaction}


@dataclass(frozen=True)
class CSVUnitValues:
    address: int
    part_name: str
    tag_name: str
    unit_type: str
    catalog: str
    serial: str
    firmware: str
    primary: str
    secondary: str
    area: str | None
    groups: tuple[CSVGroupValue, ...]

    def __post_init__(self):
        _validate_unit(self)

    def as_dict(self):
        return {**{name: getattr(self, name) for name in COLUMNS[:10]},
                'groups': [group.as_dict() for group in self.groups]}


def _validate_unit(unit):
    if type(unit) is not CSVUnitValues:
        raise ValueError('Units must be exact CSVUnitValues objects')
    if type(unit.address) is not int or not 0 <= unit.address <= 255:
        raise ValueError('Unit address must be an integer from 0 through 255')
    for name in _TEXT_FIELDS:
        _text(getattr(unit, name), name)
    if unit.area is not None:
        _text(unit.area, 'area')
    if type(unit.groups) is not tuple or len(unit.groups) > 16:
        raise ValueError('Groups must be a tuple containing at most 16 entries')
    for group in unit.groups:
        if type(group) is not CSVGroupValue:
            raise ValueError('Groups must be exact CSVGroupValue objects')
        _text(group.tag, 'Group tag')
        if type(group.interaction) is not bool:
            raise ValueError('Group interaction must be a boolean')


def validate_columns(columns):
    """Validate an explicit selection and return original ordinal order."""
    if type(columns) is not tuple or not 1 <= len(columns) <= len(COLUMNS):
        raise ValueError('columns must be a nonempty tuple of at most 26 names')
    if any(type(name) is not str or name not in COLUMN_LABELS for name in columns):
        raise ValueError('Unknown CSV column; use the documented captured-report names')
    if len(set(columns)) != len(columns):
        raise ValueError('CSV column selection contains duplicates')
    return tuple(name for name in COLUMNS if name in columns)


def _serial(raw):
    # Original FormatSerialNumber(..., dotted=False), followed by the two
    # GetDisplayableSerialNumber sentinel substitutions. No identity claim.
    value = ''.join(char for char in raw if '0' <= char <= '9' or char == '.')
    if '.' in value:
        left, right = value.split('.', 1)
        value = left.rjust(8, '0') + right.rjust(4, '0')
    else:
        value = value.rjust(12, '0')
    return 'No serial #' if value in ('000000000000', '010485754095') else value


def _quote(value):
    # Intentionally preserves original comma-only quoting, even for a quote
    # or newline without a comma. Public strings exclude original NUL edges.
    return '"' + value.replace('"', '""') + '"' if ',' in value else value


@dataclass(frozen=True)
class DatabaseCSV:
    columns: tuple[str, ...]
    rows: tuple[str, ...]
    unit_count: int

    def __post_init__(self):
        if validate_columns(self.columns) != self.columns:
            raise ValueError('Report columns must have original ordinal order')
        if type(self.unit_count) is not int or not 0 <= self.unit_count <= MAX_UNITS:
            raise ValueError('Invalid report unit count')
        if type(self.rows) is not tuple or len(self.rows) != self.unit_count + 1:
            raise ValueError('Report must contain one header and one row per unit')
        if self.rows[0] != ''.join(COLUMN_LABELS[name] + ',' for name in self.columns):
            raise ValueError('Report header does not match its columns')
        size = 2  # Handler adds one further empty line.
        for row in self.rows:
            if type(row) is not str or '\0' in row:
                raise ValueError('Report rows must be strings without NUL')
            try:
                size += len(row.encode('utf-8')) + 2
            except UnicodeEncodeError as error:
                raise ValueError('Report contains an unpaired surrogate') from error
            if size > MAX_OUTPUT_BYTES:
                raise ValueError('CSV exceeds the 32 MiB output bound')

    @property
    def csv_text(self):
        """Original row text plus CRLF per row and the handler's blank line."""
        return '\r\n'.join(self.rows) + '\r\n\r\n'

    @property
    def utf8_bytes(self):
        """Portable UTF-8 without BOM; native Windows ACP bytes are unverified."""
        return self.csv_text.encode('utf-8')

    def as_dict(self):
        raw = self.utf8_bytes
        return {'format': 'cbus-toolkit-database-csv-v1', 'columns': list(self.columns),
                'headers': [COLUMN_LABELS[name] for name in self.columns],
                'unit_count': self.unit_count, 'row_count': len(self.rows),
                'encoding': 'utf-8', 'bom': False, 'line_ending': 'crlf',
                'extra_final_blank_line': True, 'bytes': len(raw),
                'sha256': hashlib.sha256(raw).hexdigest(),
                'source': 'explicit captured report values',
                'database_projection_verified': False, 'native_codepage_verified': False,
                'original_form_executed': False, 'physical_identity_verified': False}


def document_database_csv(units, *, columns):
    """Render captured values; no file, registry, database or network access."""
    selected = validate_columns(columns)
    if type(units) is not tuple or len(units) > MAX_UNITS:
        raise ValueError('units must be a tuple containing at most 4096 entries')
    for unit in units:
        _validate_unit(unit)
    rows = [''.join(COLUMN_LABELS[name] + ',' for name in selected)]
    size = len(rows[0].encode('utf-8')) + 4
    for unit in units:
        fields = []
        for name in selected:
            if name.startswith('group_'):
                continue
            if name == 'address': value = str(unit.address)
            elif name == 'serial': value = _serial(unit.serial)
            elif name == 'area': value = '<Unused>' if unit.area is None else unit.area
            else: value = getattr(unit, name)
            fields.append(_quote(value) + ',')
        unavailable = 0
        for index in range(16):
            if f'group_{index + 1}' not in selected:
                continue
            if index < len(unit.groups) and unit.groups[index].interaction:
                fields.append(_quote(unit.groups[index].tag) + ',')
            else:
                unavailable += 1
        fields.extend(['<N/A>,'] * unavailable)
        row = ''.join(fields)
        size += len(row.encode('utf-8')) + 2
        if size > MAX_OUTPUT_BYTES:
            raise ValueError('CSV exceeds the 32 MiB output bound')
        rows.append(row)
    return DatabaseCSV(selected, tuple(rows), len(units))


def parse_capture(value):
    """Validate the exact JSON object schema and detach all captured values."""
    if type(value) is not dict or set(value) != {'format', 'units'}:
        raise ValueError('Expected the cbus-toolkit-database-report-v1 capture object')
    if type(value['format']) is not str:
        raise ValueError('Capture format must be an exact string')
    if value['format'] != CAPTURE_FORMAT:
        raise ValueError('Expected the cbus-toolkit-database-report-v1 capture object')
    raw_units = value['units']
    if type(raw_units) is not list or len(raw_units) > MAX_UNITS:
        raise ValueError('Capture units must be a list of at most 4096 entries')
    units = []
    for raw in raw_units:
        if type(raw) is not dict or set(raw) != _UNIT_FIELDS:
            raise ValueError('Each captured unit must provide every documented field, without extras')
        groups = raw['groups']
        if type(groups) is not list or len(groups) > 16:
            raise ValueError('Captured groups must be a list of at most 16 entries')
        result = []
        for group in groups:
            if type(group) is not dict or set(group) != {'tag', 'interaction'}:
                raise ValueError('Each captured group requires tag and interaction')
            result.append(CSVGroupValue(group['tag'], group['interaction']))
        units.append(CSVUnitValues(**{name: raw[name] for name in _UNIT_FIELDS - {'groups'}},
                                   groups=tuple(result)))
    return tuple(units)


def loads_capture(raw):
    """Decode bounded strict UTF-8 JSON; duplicate keys and floats are rejected."""
    if type(raw) is not bytes or not 1 <= len(raw) <= MAX_CAPTURE_BYTES:
        raise ValueError('Capture must be nonempty bytes within the 8 MiB bound')
    text = raw.decode('utf-8')
    depth = 0; quoted = escaped = False
    for char in text:
        if quoted:
            if escaped: escaped = False
            elif char == '\\': escaped = True
            elif char == '"': quoted = False
        elif char == '"': quoted = True
        elif char in '[{':
            depth += 1
            if depth > 5:
                raise ValueError('Capture nesting exceeds its schema')
        elif char in ']}': depth -= 1

    def unique(pairs):
        if len(pairs) > len(_UNIT_FIELDS) or len({key for key, _ in pairs}) != len(pairs):
            raise ValueError('Capture contains duplicate or excessive object keys')
        return dict(pairs)

    def integer(value):
        if len(value.lstrip('-')) > 10:
            raise ValueError('Capture integer exceeds its bounded domain')
        return int(value)

    def no_float(_):
        raise ValueError('Capture numbers must be integers')

    return parse_capture(json.loads(text, object_pairs_hook=unique, parse_int=integer,
                                    parse_float=no_float, parse_constant=no_float))
