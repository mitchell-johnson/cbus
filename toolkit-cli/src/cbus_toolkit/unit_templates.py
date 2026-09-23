"""Toolkit UnitTemplate XML for verified KEY1/KEY2/KEY4 1.2.67 profiles.

Template inclusion/order and checksum behavior follow the original EXE. This
is distinct from the CLI's complete JSON PP snapshots. No automatic save or
cross-model conversion is performed. See docs/unit-templates.md.
"""
from dataclasses import dataclass
from types import MappingProxyType
import re
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

from .macros import _numbers
from .programming import xml_text


class UnitTemplateError(ValueError):
    pass


class UnitTemplateApplyError(RuntimeError):
    def __init__(self, cause, attempted):
        self.cause, self.attempted = cause, tuple(attempted)
        self.details = {'attempted_parameters': list(attempted), 'saved': False, 'device_verified': False}
        super().__init__('Template application stopped; PP changes may be partial and were not saved: ' + str(cause))


PROFILE = ('KEY4', '1.2.67', '5034N', 'KEY4.xml')
PROFILES = MappingProxyType({
    'KEY1': ('KEY1', '1.2.67', '5031N', 'KEY1.xml'),
    'KEY2': ('KEY2', '1.2.67', '5032N', 'KEY2.xml'),
    'KEY4': PROFILE,
})
# Exact constructor order for TCBusKeyInputCGateAgent and its ancestors,
# restricted to attributes with TFlashAttribute's template flag (+0x6C).
ATTRIBUTE_ORDER = (
    'Application', 'FirmwareVersion', 'UnitName', 'UnitType', 'LearnAnyApp', 'LearnMode',
    'AreaGroupAddress', 'StatusReportInterval', 'GroupAddress', 'DebounceTime',
    'IndicatorBrightness', 'LongPressTime', 'EEPROMLevelStore', 'LightIndex', 'LightLevel',
    'LightLevelStore1', 'LightLevelStore2', 'RampRate', 'InfraRedBank', 'JPCommand',
    'SRCommand', 'LPCommand', 'LRCommand', 'BlockAllocation', 'IndicatorBlockAssignment',
    'IndicatorFunction', 'TimerHighByte', 'TimerLowByte', 'TimerExpiryCommand', 'GAVBroadcastFlag',
)
_METADATA = frozenset(('UnitType', 'FirmwareVersion'))
# These integer agent properties have no native parameter in these specs.
# Only their default zero values are supported; they never become PP setters.
_VIRTUAL = frozenset(('InfraRedBank', 'GAVBroadcastFlag'))
_INTEGER_ATTRIBUTES = frozenset(('DebounceTime', 'IndicatorBrightness', 'LongPressTime', 'LightIndex',
                                 'InfraRedBank', 'GAVBroadcastFlag', 'StatusReportInterval'))
_BOOLEAN_ATTRIBUTES = frozenset(('LearnAnyApp', 'LearnMode', 'EEPROMLevelStore'))
PARAMETERS = tuple(name for name in ATTRIBUTE_ORDER if name not in _METADATA | _VIRTUAL)
_MAX_BYTES = 1024 * 1024
_XML_ESCAPES = {'"': '&quot;'}


def _text(value, name):
    if not isinstance(value, str) or any(ord(c) < 32 and c not in '\t\r\n' for c in value):
        raise UnitTemplateError('Invalid template text: ' + name)
    # Original Toolkit uses low bytes of UTF-16 characters in its checksum;
    # retain a bounded ASCII profile until non-ASCII file I/O is verified.
    if not value.isascii():
        raise UnitTemplateError('This verified template workflow accepts ASCII text only')
    return value


def _normalized(name, value):
    value = _text(value, name).strip()
    if name in ('UnitType', 'FirmwareVersion', 'UnitName'):
        if name == 'UnitName' and (value != value.upper() or '?' in value or len(value) > 8
                                   or any(ord(character) < 32 or ord(character) > 96 for character in value)):
            raise UnitTemplateError('UnitName must use canonical uppercase sixbit text without ?')
        return value
    try:
        numbers = _numbers(value)
    except ValueError as error:
        raise UnitTemplateError('Invalid numeric template parameter: ' + name) from error
    if not numbers:
        raise UnitTemplateError('Empty numeric template parameter: ' + name)
    return ' '.join(map(str, numbers))


def template_crc(attributes):
    """Native 0xFEED/0x1021 LSB-data CRC, including its final-byte omission."""
    if set(attributes) != set(ATTRIBUTE_ORDER):
        raise UnitTemplateError('Template checksum requires the exact classic key-input attribute set')
    pieces = []
    for name in ATTRIBUTE_ORDER:
        value = _text(attributes[name], name).strip()
        # Scalar attributes have already parsed integers/booleans when the
        # original loader reaches its checksum. String arrays preserve
        # interior decimal whitespace; only a leading literal 0x invokes
        # HexStrArrayToDecStrArray in CalcTemplateCRC.
        if name in _INTEGER_ATTRIBUTES | _BOOLEAN_ATTRIBUTES or value.startswith('0x'):
            value = _normalized(name, value)
        pieces.append(value)
    data = ''.join(pieces).encode('ascii')
    if len(data) > 65536:
        raise UnitTemplateError('Toolkit template checksum input exceeds 65536 bytes')
    crc = 0xFEED
    # CalcTemplateCRC passes DynArrayHigh to CalculateCRC; that routine treats
    # the argument as its iteration count, so the final byte is omitted.
    for byte in data[:-1]:
        for _ in range(8):
            feedback = bool(crc & 0x8000) != bool(byte & 1)
            crc = (crc << 1) & 65535
            if feedback:
                crc ^= 0x1021
            byte >>= 1
    return crc


@dataclass(frozen=True)
class UnitTemplate:
    attributes: dict
    description: str = ''

    def __post_init__(self):
        if set(self.attributes) != set(ATTRIBUTE_ORDER):
            raise UnitTemplateError('Template attributes differ from the supported classic key-input format')
        values = {name: _normalized(name, self.attributes[name]) for name in ATTRIBUTE_ORDER}
        if values['UnitType'] not in PROFILES or values['FirmwareVersion'] != '1.2.67':
            raise UnitTemplateError('Supported template identities are KEY1/KEY2/KEY4 firmware 1.2.67')
        if any(values[name] != '0' for name in _VIRTUAL):
            raise UnitTemplateError('Nondefault InfraRedBank/GAVBroadcastFlag is outside this classic key-input workflow')
        object.__setattr__(self, 'attributes', MappingProxyType(values))
        _text(self.description, 'Description')
        if '\n' in self.description or '\r' in self.description or len(self.description) > 4096:
            raise UnitTemplateError('Template description must be one line of at most 4096 characters')

    @property
    def profile(self):
        return PROFILES[self.attributes['UnitType']]

    @property
    def crc(self):
        return template_crc(self.attributes)

    def to_xml(self):
        # Toolkit explicitly writes identity before its CRC, then iterates all
        # template attributes. Its constructor includes the two identities in
        # that collection too; preserve the matching duplicate header values.
        rows = ['<?xml version="1.0" encoding="utf-8"?>', '<UnitTemplate>',
                '    <Description>' + escape(self.description) + '</Description>']
        for name in ('UnitType', 'FirmwareVersion'):
            rows.append(f'    <{name}>{escape(self.attributes[name])}</{name}>')
        rows.append(f'    <CRC>{self.crc}</CRC>')
        rows.extend(f'    <{name}>{escape(self.attributes[name], _XML_ESCAPES)}</{name}>' for name in ATTRIBUTE_ORDER)
        rows.append('</UnitTemplate>')
        return '\r\n'.join(rows) + '\r\n'

    @classmethod
    def from_xml(cls, document):
        if isinstance(document, bytes):
            if len(document) > _MAX_BYTES:
                raise UnitTemplateError('Template exceeds 1 MiB')
            try:
                document = document.decode('utf-8-sig')
            except UnicodeDecodeError as error:
                raise UnitTemplateError('Template must be UTF-8') from error
        if not isinstance(document, str) or len(document.encode('utf-8')) > _MAX_BYTES:
            raise UnitTemplateError('Template must be XML text of at most 1 MiB')
        remainder = re.sub(r'\A\ufeff?\s*<\?xml\s[^?]*\?>', '', document, count=1)
        if '<!' in document or '&#' in document or '<?' in remainder:
            raise UnitTemplateError('Template declarations, processing instructions and numeric character references are unsupported')
        try:
            root = ET.fromstring(document)
        except ET.ParseError as error:
            raise UnitTemplateError('Malformed UnitTemplate XML') from error
        if root.tag != 'UnitTemplate' or root.attrib or (root.text or '').strip():
            raise UnitTemplateError('Expected a plain UnitTemplate root')
        fields = {}
        for element in root:
            if (element.tag not in set(ATTRIBUTE_ORDER) | {'Description', 'CRC'} or element.attrib or len(element)
                    or (element.tail or '').strip()):
                raise UnitTemplateError('Unexpected template field or nested content')
            value = element.text or ''
            if element.tag in fields:
                if element.tag not in _METADATA or fields[element.tag] != value:
                    raise UnitTemplateError('Conflicting or unexpected duplicate template field')
                if sum(child.tag == element.tag for child in root) > 2:
                    raise UnitTemplateError('Excess duplicate template identity fields')
            fields[element.tag] = value
        if set(fields) != set(ATTRIBUTE_ORDER) | {'Description', 'CRC'}:
            raise UnitTemplateError('Incomplete classic key-input template')
        crc_text = fields.pop('CRC')
        if not re.fullmatch(r'[0-9]{1,5}', crc_text) or int(crc_text) > 65535:
            raise UnitTemplateError('Invalid template CRC')
        description = fields.pop('Description')
        original_crc = template_crc(fields)
        result = cls(fields, description)
        if original_crc != int(crc_text):
            raise UnitTemplateError('Template CRC mismatch')
        return result

    def as_dict(self):
        return {'format': 'toolkit-unit-template-xml', 'unit_type': self.profile[0], 'firmware': self.profile[1],
                'tested_catalog_number': self.profile[2], 'description': self.description, 'crc': self.crc,
                'attributes': dict(self.attributes), 'physical_hardware_verified': False}


class UnitTemplates:
    def __init__(self, spec, *, firmware='1.2.67', catalog_number=None):
        profile = PROFILES.get(spec.unit_type)
        if (profile is None or spec.filename != profile[3] or firmware != profile[1]
                or (catalog_number is not None and catalog_number != profile[2])):
            raise UnitTemplateError('Use an exact KEY1/5031N, KEY2/5032N or KEY4/5034N profile, firmware 1.2.67')
        self.profile = profile
        self.spec = spec
        for name in PARAMETERS:
            spec.get(name)

    def _validate_values(self, values):
        result = {}
        for name in PARAMETERS:
            if name not in values:
                raise UnitTemplateError('Missing template parameter: ' + name)
            value = values[name]
            if not isinstance(value, str):
                value = ' '.join(map(str, value)) if isinstance(value, (tuple, list)) else str(value)
            normalized = _normalized(name, value)
            parameter = self.spec.get(name)
            check_value = normalized if name == 'UnitName' else list(_numbers(normalized))
            if not parameter.validate_value(check_value)['valid']:
                raise UnitTemplateError('Parameter outside native schema: ' + name)
            result[name] = normalized
        return result

    def from_values(self, values, *, description=''):
        attributes = self._validate_values(values)
        attributes.update(UnitType=self.profile[0], FirmwareVersion=self.profile[1], InfraRedBank='0', GAVBroadcastFlag='0')
        return UnitTemplate(attributes, description)

    def _verify_profile(self, session):
        if (session.unit_type, session.firmware, session.catalog_number) != self.profile[:3]:
            raise UnitTemplateError('Native session must match the selected template profile: ' + ' / '.join(self.profile[:3]))

    def _verify_session(self, session):
        self._verify_profile(session)
        text = xml_text(session.info('*'))
        if '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper():
            raise UnitTemplateError('Unsupported native parameter schema')
        try:
            root = ET.fromstring(text)
        except ET.ParseError as error:
            raise UnitTemplateError('Invalid native parameter schema') from error
        fields = {}
        for param in root.iter('Param'):
            row = {child.tag: child.text or '' for child in param}
            if row.get('Name') in fields:
                raise UnitTemplateError('Duplicate native parameter schema')
            fields[row.get('Name')] = row
        for name in PARAMETERS:
            native, local = fields.get(name, {}), self.spec.get(name).fields
            if native.get('Type', '').lower() != local.get('Type', '').lower():
                raise UnitTemplateError('Native parameter type mismatch: ' + name)
            for field, default in (('Address', None), ('ArraySize', '1'), ('BitSize', '1' if local.get('Type') == 'bit' else '8'), ('BitAddress', '0'), ('ArraySkip', '0')):
                if _numbers(native.get(field, default)) != _numbers(local.get(field, default)):
                    raise UnitTemplateError(f'Native parameter layout mismatch: {name}/{field}')

    def export(self, session, *, description=''):
        self._verify_session(session)
        return self.from_values(session.values(), description=description)

    def apply(self, session, template):
        if not isinstance(template, UnitTemplate):
            raise UnitTemplateError('Parse a UnitTemplate before applying it')
        if template.profile != self.profile:
            raise UnitTemplateError('Template identity differs from the selected profile; cross-type conversion is unsupported')
        desired = self._validate_values(template.attributes)
        self._verify_session(session)
        current = self._validate_values(session.values())
        changes = {name: desired[name] for name in PARAMETERS if desired[name] != current[name]}
        attempted = []
        try:
            for name, value in changes.items():
                attempted.append(name)
                session.set(name, value)
            if self._validate_values(session.values()) != desired:
                raise UnitTemplateError('Native template readback differs from requested values')
        except (RuntimeError, OSError, ValueError) as error:
            raise UnitTemplateApplyError(error, attempted) from error
        return {'format': 'cbus-toolkit-template-apply-v1', 'crc': template.crc,
                'changed_parameters': list(changes), 'verified': True, 'saved': False, 'device_verified': False}
