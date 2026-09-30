"""Ordered eDLT UnitTemplate interchange and immutable assignment previews.

This is deliberately separate from classic/Neo templates and PP overlays.
Template load requires an unimplemented parent reset/rebind transaction. No
function here reads a session, mutates an editor or persists a unit.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
import unicodedata
import xml.etree.ElementTree as ET


MAX_XML_BYTES = 1024 * 1024
MAX_FIELDS = 4096
EXCLUDED_EXPORT_ATTRIBUTES = frozenset((
    'UnitAddress', 'Application', 'Project', 'NetworkAddress', 'UnitName', 'SerialNumber'))
APPLY_BLOCKERS = (
    'The complete FrmBaseUnit.ResetUnit(true) result and reset graph are not established for template load.',
    'The second PopulateWidgetPanels / BeforeChangePpAttributes / ordered assignment / '
    'AfterChangePpAttributes graph rebuild is not implemented or compared with an original complete load.',
    'Reset, assignment and rebind failure rollback, cancellation, and the later single Apply/OK '
    'save have no accepted template transaction contract.',
)
ORIGINAL_LOAD_PHASES = (
    'validate_headers_and_ordered_crc', 'ResetUnit(true)', 'PopulateWidgetPanels',
    'BeforeChangePpAttributes', 'assign_matching_PPAttributes_in_XML_child_order',
    'AfterChangePpAttributes', 'await_Apply_or_OK',
)
# Char.IsWhiteSpace / String.Trim on the retained CLR generation. Python's
# str.strip additionally strips U+001C..U+001F, which the original does not.
_CLR_WHITESPACE = '\u0009\u000a\u000b\u000c\u000d\u0020\u0085\u00a0\u1680' + ''.join(
    chr(n) for n in range(0x2000, 0x200b)) + '\u2028\u2029\u202f\u205f\u3000'
_NAME = re.compile(r'[A-Za-z_][A-Za-z0-9_.-]*\Z')


class EdltTemplateError(ValueError):
    """Invalid input or a format outside the explicitly bounded profile."""


class EdltTemplateApplyRefused(EdltTemplateError):
    def __init__(self):
        self.details = {
            'status': 'refused', 'apply_allowed': False, 'blockers': list(APPLY_BLOCKERS),
            'mutation_attempted': False, 'saved': False, 'physical_device_verified': False,
        }
        super().__init__('eDLT template apply is unavailable: ' + ' '.join(APPLY_BLOCKERS))


def _int32(text, base):
    """Bounded Convert.ToInt32(string, base) grammar used by both helpers."""
    pattern = r'\+?(?:0[xX])?[0-9A-Fa-f]+' if base == 16 else r'[+-]?[0-9]+'
    if not re.fullmatch(pattern, text):
        raise EdltTemplateError('Invalid base-' + str(base) + ' Int32 token: ' + repr(text))
    unsigned = text.lstrip('+-')
    if base == 16 and unsigned.lower().startswith('0x'):
        unsigned = unsigned[2:]
    significant = unsigned.lstrip('0') or '0'
    if len(significant) > (8 if base == 16 else 10):
        raise EdltTemplateError('Template token exceeds Int32')
    number = int(significant, base) * (-1 if text.startswith('-') else 1)
    if base == 16:
        if number > 0xffffffff:
            raise EdltTemplateError('Hexadecimal template token exceeds 32 bits')
        return number - 0x100000000 if number >= 0x80000000 else number
    if not -0x80000000 <= number <= 0x7fffffff:
        raise EdltTemplateError('Decimal template token exceeds Int32')
    return number


def edlt_template_crc(values):
    """PPHelper.CalcTemplateCrc over ordered raw strings, never a mapping.

    Includes the original untrimmed lowercase-prefix test, literal-space hex
    conversion, UTF-16 low bytes, 65536-byte buffer and final-byte omission.
    """
    if isinstance(values, (str, bytes, dict)):
        raise EdltTemplateError('CRC requires an ordered sequence of raw value strings')
    data = bytearray()
    for original in values:
        if not isinstance(original, str):
            raise EdltTemplateError('CRC values must be strings')
        # Original StartsWith(string) is culture-sensitive: the owned CLR
        # ignores ZWJ/NUL in some prefixes although Python startswith does not.
        # Do not guess the host culture or silently hash these as ordinary text.
        if not original.startswith('0x'):
            visible = ''.join(c for c in original
                              if unicodedata.category(c) not in ('Cc', 'Cf', 'Mn', 'Mc', 'Me'))
            if visible.startswith('0x'):
                raise EdltTemplateError('Culture-sensitive hexadecimal prefix is outside the admitted CRC profile')
        value = original.strip(_CLR_WHITESPACE)
        if original.startswith('0x'):
            value = ' '.join(str(_int32(token, 16)) for token in original.split(' '))
        low_bytes = value.encode('utf-16-le', errors='surrogatepass')[::2]
        if len(data) + len(low_bytes) > 65536:
            raise EdltTemplateError('Template CRC input exceeds the original 65536-byte buffer')
        data.extend(low_bytes)
    crc = 0xfeed
    for byte in data[:-1]:
        for _ in range(8):
            feedback = bool(crc & 0x8000) != bool(byte & 1)
            crc = (crc << 1) & 0xffff
            if feedback:
                crc ^= 0x1021
            byte >>= 1
    return crc


def _plain_text(value):
    if not isinstance(value, str):
        raise EdltTemplateError('Template field values must be raw strings')
    if any(not (c in '\t\n\r' or 0x20 <= ord(c) <= 0xd7ff
                or 0xe000 <= ord(c) <= 0xfffd or 0x10000 <= ord(c) <= 0x10ffff) for c in value):
        raise EdltTemplateError('Template contains an invalid XML character')
    # The original exporter interpolates unescaped values, while the importer
    # consumes InnerXml, not InnerText. Do not silently reinterpret either.
    if any(c in value for c in '&<>\r\n'):
        raise EdltTemplateError('Markup, entities and multiline values require an original XML roundtrip; unsupported')
    if value and not value.strip(_CLR_WHITESPACE):
        raise EdltTemplateError('Whitespace-only fields have unsupported XmlDocument whitespace semantics')
    return value


def _fields(rows):
    if isinstance(rows, (dict, str, bytes)):
        raise EdltTemplateError('Fields must be ordered (name, raw value) pairs, not a mapping')
    result = []
    for row in rows:
        if not isinstance(row, (tuple, list)) or len(row) != 2:
            raise EdltTemplateError('Fields must be ordered (name, raw value) pairs')
        name, value = row
        if not isinstance(name, str) or not _NAME.fullmatch(name):
            raise EdltTemplateError('Unsupported plain XML field name')
        result.append((name, _plain_text(value)))
        if len(result) > MAX_FIELDS:
            raise EdltTemplateError('Template has too many fields')
    return tuple(result)


@dataclass(frozen=True)
class EdltTemplate:
    """Validated file representation; duplicates and raw value order survive."""

    fields: tuple[tuple[str, str], ...]

    def __post_init__(self):
        fields = _fields(self.fields)
        object.__setattr__(self, 'fields', fields)
        if sum(name == 'CRC' for name, _ in fields) != 1:
            raise EdltTemplateError('Exactly one CRC field is required in this profile')
        header = fields[:self.crc_index]
        for name in ('UnitType', 'FirmwareVersion'):
            values = [value for key, value in header if key == name]
            if len(values) != 1:
                raise EdltTemplateError('Exactly one pre-CRC ' + name + ' is required')
            if not values[0] or name == 'UnitType' and values[0] != 'KEYGL5':
                raise EdltTemplateError('Template requires KEYGL5 and nonempty firmware headers')
            if any(value != values[0] for key, value in fields if key == name):
                raise EdltTemplateError('Conflicting template identity fields are unsupported: ' + name)
        crc = fields[self.crc_index][1]
        if not re.fullmatch(r'[0-9]{1,5}', crc) or int(crc) > 65535:
            raise EdltTemplateError('CRC must be a decimal UInt16')
        if edlt_template_crc(value for _, value in self.payload) != int(crc):
            raise EdltTemplateError('Template CRC mismatch')
        if len(self.to_xml().encode('utf-8')) > MAX_XML_BYTES:
            raise EdltTemplateError('Template exceeds 1 MiB')

    @property
    def crc_index(self):
        return next(i for i, (name, _) in enumerate(self.fields) if name == 'CRC')

    @property
    def payload(self):
        return self.fields[self.crc_index + 1:]

    @property
    def firmware(self):
        return next(value for name, value in self.fields if name == 'FirmwareVersion')

    @property
    def crc(self):
        return int(self.fields[self.crc_index][1])

    def to_xml(self):
        rows = ['<?xml version="1.0" encoding="utf-8"?>', '<UnitTemplate>']
        rows.extend(f'<{name}>{value}</{name}>' for name, value in self.fields)
        return '\r\n'.join(rows + ['</UnitTemplate>', ''])

    @classmethod
    def from_xml(cls, document):
        if isinstance(document, bytes):
            if len(document) > MAX_XML_BYTES:
                raise EdltTemplateError('Template exceeds 1 MiB')
            try:
                document = document.decode('utf-8-sig')
            except UnicodeDecodeError as error:
                raise EdltTemplateError('Template must use UTF-8') from error
        if not isinstance(document, str) or len(document.encode('utf-8', 'surrogatepass')) > MAX_XML_BYTES:
            raise EdltTemplateError('Template must be XML text of at most 1 MiB')
        document = document.removeprefix('\ufeff')
        declaration = re.match(r'\A<\?xml\s+[^?]*\?>', document)
        if declaration:
            versions = re.findall(r'\bversion\s*=\s*[\'"]([^\'"]+)[\'"]', declaration[0])
            if versions != ['1.0']:
                raise EdltTemplateError('Template declaration must use XML 1.0')
            encoding = re.search(r'encoding\s*=\s*[\'"]([^\'"]+)[\'"]', declaration[0])
            if encoding and encoding[1].lower() != 'utf-8':
                raise EdltTemplateError('Template declaration must use UTF-8')
        remainder = document[declaration.end():] if declaration else document
        if '<!' in document or '<?' in remainder or '&' in document:
            raise EdltTemplateError('DTD, entities, comments, CDATA and processing instructions are unsupported')
        try:
            root = ET.fromstring(document)
        except (ET.ParseError, UnicodeEncodeError) as error:
            raise EdltTemplateError('Malformed UnitTemplate XML') from error
        if root.tag != 'UnitTemplate' or root.attrib or (root.text or '').strip(' \t\r\n'):
            raise EdltTemplateError('Expected a plain UnitTemplate root')
        rows = []
        for element in root:
            if element.attrib or len(element) or (element.tail or '').strip(' \t\r\n'):
                raise EdltTemplateError('Template requires flat fields without attributes or mixed content')
            rows.append((element.tag, element.text or ''))
        return cls(tuple(rows))

    def as_dict(self):
        return {
            'format': 'cbus-edlt-template-v1', 'unit_type': 'KEYGL5', 'firmware': self.firmware,
            'crc': self.crc, 'crc_valid': True, 'crc_child_index': self.crc_index,
            'fields': [{'child_index': i, 'name': name, 'value': value, 'checksummed': i > self.crc_index}
                       for i, (name, value) in enumerate(self.fields)],
            'canonical_xml_sha256': hashlib.sha256(self.to_xml().encode('utf-8')).hexdigest(),
            'format_profile': 'flat-UTF8-text-no-entities-matching-identities',
            'native_template_workflow_verified': False, 'apply_allowed': False,
        }


def export_edlt_template(*, description, firmware, unit_name, primary_application,
                         secondary_application, pp_attributes):
    """Export the supplied original ordered PP collection; no schema inference.

    Identity properties and application integers are explicit since the
    original obtains them separately from PPAttributes enumeration.
    """
    for value in (primary_application, secondary_application):
        if type(value) is not int or not 0 <= value <= 255:
            raise EdltTemplateError('Export requires byte-valued primary/secondary applications')
    attrs = _fields(pp_attributes)
    if len({name for name, _ in attrs}) != len(attrs):
        raise EdltTemplateError('Export requires a unique ordered PPAttribute collection')
    if any(name in ('CRC', 'Description') for name, _ in attrs):
        raise EdltTemplateError('PPAttribute collection collides with template metadata')
    payload = (('Application', f'{primary_application} {secondary_application}'),
               ('FirmwareVersion', firmware), ('UnitName', unit_name), ('UnitType', 'KEYGL5'))
    payload += tuple((name, value) for name, value in attrs if name not in EXCLUDED_EXPORT_ATTRIBUTES)
    payload = _fields(payload)
    crc = edlt_template_crc(value for _, value in payload)
    return EdltTemplate((('Description', description), ('UnitType', 'KEYGL5'),
                         ('FirmwareVersion', firmware), ('CRC', str(crc))) + payload)


def _assignment_value(name, value):
    if name != 'Application' or value == '':
        return value
    return ' '.join(f'0x{_int32(token, 10) & 0xffffffff:x}' for token in value.split(' '))


@dataclass(frozen=True)
class EdltTemplatePreview:
    template: EdltTemplate
    assignments: tuple[tuple[int, str, str], ...]
    ignored: tuple[int, ...]
    validation_errors: tuple[str, ...]
    warnings: tuple[str, ...]
    schema_checked: bool

    def as_dict(self):
        return {
            'format': 'cbus-edlt-template-preview-v1', 'status': 'preview_only',
            'template': self.template.as_dict(),
            'assignment_candidates': [
                {'child_index': i, 'name': name, 'value': value,
                 'condition': 'assign only if the post-reset PPAttribute raw value differs'}
                for i, name, value in self.assignments],
            'ignored_child_indices': list(self.ignored),
            'attribute_membership_source': 'caller_supplied_PPAttribute_names',
            'schema_checked': self.schema_checked, 'validation_errors': list(self.validation_errors),
            'warnings': list(self.warnings), 'input_validated': not self.validation_errors,
            'validation_scope': 'individual-local-schema-only' if self.schema_checked else 'format-and-conversion-only',
            'raw_setter_validated': False,
            'original_load_phases': list(ORIGINAL_LOAD_PHASES), 'apply_blockers': list(APPLY_BLOCKERS),
            'apply_allowed': False, 'post_reset_values_known': False,
            'parent_lifecycle_executed': False, 'mutation_attempted': False, 'saved': False,
            'native_template_workflow_verified': False, 'physical_device_verified': False,
        }

    def apply(self, target=None):
        # No callback, property read, session method, reset, assignment or save
        # may occur before refusal. A Boolean override cannot unlock this.
        raise EdltTemplateApplyRefused()


def preview_edlt_template(template, *, pp_attribute_names, spec=None, target_firmware=None):
    """Validate candidate assignments without constructing a pretend final unit."""
    if not isinstance(template, EdltTemplate):
        raise EdltTemplateError('Parse an EdltTemplate before previewing it')
    if isinstance(pp_attribute_names, (str, bytes, dict)):
        raise EdltTemplateError('Supply the complete ordered original PPAttribute name collection')
    names = tuple(pp_attribute_names)
    if any(not isinstance(name, str) or not _NAME.fullmatch(name) for name in names) or len(set(names)) != len(names):
        raise EdltTemplateError('PPAttribute names must be valid and unique')
    if spec is not None and spec.unit_type != 'KEYGL5':
        raise EdltTemplateError('Local validation requires a KEYGL5 specification')
    errors, warnings, assignments, ignored = [], [], [], []
    if target_firmware is not None and target_firmware != template.firmware:
        warnings.append('Template and target firmware differ; the original does not compare them. '
                        'Cross-firmware lifecycle compatibility is unproved.')
    if spec is not None and target_firmware is not None and not spec.supports_version(target_firmware):
        errors.append('Target firmware is outside the supplied local specification')
    seen = set()
    for i, (name, raw) in enumerate(template.fields):
        try:
            value = _assignment_value(name, raw)
        except EdltTemplateError as error:
            errors.append(f'Child {i} {name}: {error}')
            continue
        if name not in names:
            ignored.append(i)
            continue
        assignments.append((i, name, value))
        if name in seen:
            warnings.append(f'Child {i} repeats PP assignment {name}; order is retained, not collapsed')
        seen.add(name)
        if spec is not None:
            if name not in spec.parameters:
                errors.append(f'Child {i} {name}: no local parameter schema; native admissibility is unknown')
            else:
                try:
                    result = spec.get(name).validate_value(value)
                except (ValueError, OverflowError) as error:
                    errors.append(f'Child {i} {name}: local schema validation failed: {error}')
                    continue
                errors.extend(f'Child {i} {name}: {message}' for message in result['errors'])
                warnings.extend(f'Child {i} {name}: {message}' for message in result['warnings'])
    if spec is None:
        warnings.append('No local schema supplied; PP value admissibility has not been checked')
    return EdltTemplatePreview(template, tuple(assignments), tuple(ignored), tuple(errors),
                               tuple(warnings), spec is not None)
