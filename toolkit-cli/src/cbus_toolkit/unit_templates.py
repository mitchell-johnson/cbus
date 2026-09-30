"""Toolkit UnitTemplate XML for verified classic and NeoPro key-input profiles.

Classic KEY1/KEY2/KEY4 1.2.67 and the 30 NeoPro key-input types at 2.5.00 use
their original agents' template attribute selection/order and checksum. This
is distinct from the CLI's complete JSON PP snapshots. No automatic save or
cross-model conversion is performed. See docs/unit-templates.md.
"""
from dataclasses import dataclass, field
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

# TCBusNeoProInputCGateAgent constructor order restricted to template-flagged
# attributes. TCoreNeoInputCGateAgent renames the key-input InfraRedBank
# attribute to IRBank; PatchEnable is template-flagged and therefore copied.
# The excluded attributes are the classic five (Project, SerialNo, State,
# UnitAddress, LearnedFlag). Every selected name is a native PP parameter.
NEO_ATTRIBUTE_ORDER = (
    'Application', 'FirmwareVersion', 'UnitName', 'UnitType', 'LearnAnyApp', 'LearnMode', 'AreaGroupAddress',
    'StatusReportInterval', 'GroupAddress', 'DebounceTime', 'IndicatorBrightness', 'LongPressTime',
    'EEPROMLevelStore', 'LightIndex', 'LightLevel', 'LightLevelStore1', 'LightLevelStore2', 'RampRate', 'IRBank',
    'JPCommand', 'SRCommand', 'LPCommand', 'LRCommand', 'BlockAllocation', 'IndicatorBlockAssignment',
    'IndicatorFunction', 'TimerHighByte', 'TimerLowByte', 'TimerExpiryCommand', 'ControlAppGroupAddress',
    'EnableNightlight', 'EnableNightlightControl', 'DisableTimerFlash', 'FirstKeyThrowAway',
    'IndicatorPressedLevel', 'TimerDuration', 'PatchEnable', 'SceneKeySelector', 'SceneTable',
    'SceneTablePointer', 'DisableIR', 'IDBacklightIllumination', 'EnableNightlightOnPCx', 'EnableNightlightOnPA6',
    'PrimaryColour', 'DisableIRNEC', 'KeyDisableGroup', 'KeyDisableGroupInvert', 'CorridorLinkEnable',
    'CorridorMasterGroup', 'CorridorGroupBlock', 'CorridorOfficeGroupBlock', 'JoinPrimaryApplication',
    'JoinSecondaryApplication', 'DualJoinPrimaryApplication', 'DualJoinSecondaryApplication',
    'SecondApplicationBlocks', 'NightlightColour',
)
# TIntegerCGateAttribute and TBooleanCGateAttribute members of the NeoPro list.
_NEO_INTEGER_ATTRIBUTES = frozenset((
    'StatusReportInterval', 'DebounceTime', 'IndicatorBrightness', 'LongPressTime', 'LightIndex', 'IRBank',
    'IndicatorPressedLevel', 'TimerDuration', 'KeyDisableGroup', 'CorridorMasterGroup', 'CorridorGroupBlock',
    'CorridorOfficeGroupBlock', 'JoinPrimaryApplication', 'JoinSecondaryApplication', 'DualJoinPrimaryApplication',
    'DualJoinSecondaryApplication', 'SecondApplicationBlocks'))
_NEO_BOOLEAN_ATTRIBUTES = frozenset((
    'LearnAnyApp', 'LearnMode', 'EEPROMLevelStore', 'EnableNightlight', 'EnableNightlightControl',
    'DisableTimerFlash', 'FirstKeyThrowAway', 'DisableIR', 'IDBacklightIllumination', 'EnableNightlightOnPCx',
    'EnableNightlightOnPA6', 'DisableIRNEC', 'KeyDisableGroupInvert', 'CorridorLinkEnable', 'NightlightColour'))


@dataclass(frozen=True)
class TemplateFamily:
    name: str
    order: tuple
    integers: frozenset
    booleans: frozenset
    virtual: frozenset
    firmware: str
    parameters: tuple = field(init=False)

    def __post_init__(self):
        object.__setattr__(self, 'parameters',
                           tuple(name for name in self.order if name not in _METADATA | self.virtual))


CLASSIC_FAMILY = TemplateFamily('classic', ATTRIBUTE_ORDER, _INTEGER_ATTRIBUTES, _BOOLEAN_ATTRIBUTES, _VIRTUAL, '1.2.67')
NEO_FAMILY = TemplateFamily('neopro', NEO_ATTRIBUTE_ORDER, _NEO_INTEGER_ATTRIBUTES, _NEO_BOOLEAN_ATTRIBUTES,
                            frozenset(), '2.5.00')
# NeoPro-agent key-input types admitted by research/fixtures/key-preset-family-equivalence.json,
# with every catalogue number that selects the specification at firmware 2.5.00.
NEO_CATALOGS = MappingProxyType({
    'KEYA1': ('R5061NL',), 'KEYA3': ('R5063NL',), 'KEYA6': ('R5066NL',), 'KEYA8': ('R5068NL',),
    'KEYAV2': ('R5062VNL',), 'KEYAV4': ('R5064VNL',), 'KEYB2': ('5082NL', 'E5082NL', 'SLC5082NL'),
    'KEYB4': ('5084NL', 'E5084NL', 'SLC5084NL'), 'KEYB6': ('5086NL', 'E5086NL'), 'KEYC1': ('5031NL', 'E5031NL'),
    'KEYC2': ('5032NL', 'E5032NL'), 'KEYC4': ('5034NL', 'E5034NL'), 'KEYCIR4': ('5034NIRL', 'E5034NIRL'),
    'KEYDV1': ('SLC5051NLM', 'SLC5081NLM'), 'KEYDV2': ('SLC5052NLM', 'SLC5082NLM'),
    'KEYDV3': ('SLC5053NLM', 'SLC5083NLM'), 'KEYDV4': ('SLC5054NLM', 'SLC5084NLM'),
    'KEYH1': ('ER5041NL', 'R5041NL'), 'KEYH2': ('ER5042NL', 'R5042NL'), 'KEYH3': ('ER5043NL', 'R5043NL'),
    'KEYH4': ('ER5044NL', 'R5044NL'), 'KEYM2': ('5052NL', 'E5052NL', 'SLC5052NL'),
    'KEYM4': ('5054NL', 'E5054NL', 'SLC5054NL'), 'KEYM8': ('5058NL', 'E5058NL', 'SLC5058NL'),
    'KEYP2': ('LHC882',), 'KEYP4': ('LHC884',), 'KEYP6': ('LHC886',), 'KEYV1': ('5091NL',), 'KEYV2': ('5092NL',),
    'KEYV3': ('5093NL',),
})
NEO_PROFILES = MappingProxyType({unit_type: (unit_type, '2.5.00', catalogs[0], unit_type + '.xml')
                                 for unit_type, catalogs in NEO_CATALOGS.items()})
_MAX_BYTES = 1024 * 1024
_XML_ESCAPES = {'"': '&quot;'}


ALL_PROFILES = MappingProxyType({**PROFILES, **NEO_PROFILES})
_FAMILIES = (CLASSIC_FAMILY, NEO_FAMILY)
_ALL_FIELDS = frozenset(ATTRIBUTE_ORDER) | frozenset(NEO_ATTRIBUTE_ORDER)


def family_for(unit_type):
    if unit_type in PROFILES:
        return CLASSIC_FAMILY
    if unit_type in NEO_PROFILES:
        return NEO_FAMILY
    raise UnitTemplateError('Unsupported template unit type: ' + str(unit_type))


def _family_of(names):
    names = set(names)
    for family in _FAMILIES:
        if names == set(family.order):
            return family
    raise UnitTemplateError('Template attributes differ from every supported key-input format')


def _text(value, name):
    if not isinstance(value, str) or any(ord(c) < 32 and c not in '\t\r\n' for c in value):
        raise UnitTemplateError('Invalid template text: ' + name)
    # Original Toolkit uses low bytes of UTF-16 characters in its checksum;
    # retain a bounded ASCII profile until non-ASCII file I/O is verified.
    if not value.isascii():
        raise UnitTemplateError('This verified template workflow accepts ASCII text only')
    return value


def _description(value):
    """Description is file metadata only: never checksummed or programmed."""
    if not isinstance(value, str):
        raise UnitTemplateError('Template description must be text')
    if ('\n' in value or '\r' in value or len(value) > 4096
            or any(ord(c) < 32 and c != '\t' or 0xD800 <= ord(c) <= 0xDFFF or ord(c) in (0xFFFE, 0xFFFF)
                   for c in value)):
        raise UnitTemplateError('Template description must be one line of at most 4096 XML characters')
    return value


def _normalized(name, value, family=CLASSIC_FAMILY):
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
    try:
        family = _family_of(attributes)
    except UnitTemplateError as error:
        raise UnitTemplateError('Template checksum requires an exact supported key-input attribute set') from error
    pieces = []
    for name in family.order:
        value = _text(attributes[name], name).strip()
        # Scalar attributes have already parsed integers/booleans when the
        # original loader reaches its checksum. String arrays preserve
        # interior decimal whitespace; only a leading literal 0x invokes
        # HexStrArrayToDecStrArray in CalcTemplateCRC.
        if name in family.integers | family.booleans or value.startswith('0x'):
            value = _normalized(name, value, family)
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
        family = _family_of(self.attributes)
        values = {name: _normalized(name, self.attributes[name], family) for name in family.order}
        try:
            expected_family = family_for(values['UnitType'])
        except UnitTemplateError:
            expected_family = None
        if expected_family is not family or values['FirmwareVersion'] != family.firmware:
            raise UnitTemplateError('Supported template identities are KEY1/KEY2/KEY4 firmware 1.2.67 '
                                    'and NeoPro key-input types firmware 2.5.00')
        if any(values[name] != '0' for name in family.virtual):
            raise UnitTemplateError('Nondefault InfraRedBank/GAVBroadcastFlag is outside this classic key-input workflow')
        object.__setattr__(self, 'attributes', MappingProxyType(values))
        _description(self.description)

    @property
    def family(self):
        return family_for(self.attributes['UnitType'])

    @property
    def profile(self):
        return ALL_PROFILES[self.attributes['UnitType']]

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
        rows.extend(f'    <{name}>{escape(self.attributes[name], _XML_ESCAPES)}</{name}>' for name in self.family.order)
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
        if not isinstance(document, str) or len(document.encode('utf-8', 'surrogatepass')) > _MAX_BYTES:
            raise UnitTemplateError('Template must be XML text of at most 1 MiB')
        remainder = re.sub(r'\A﻿?\s*<\?xml\s[^?]*\?>', '', document, count=1)
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
            if (element.tag not in _ALL_FIELDS | {'Description', 'CRC'} or element.attrib or len(element)
                    or (element.tail or '').strip()):
                raise UnitTemplateError('Unexpected template field or nested content')
            value = element.text or ''
            if element.tag in fields:
                if element.tag not in _METADATA or fields[element.tag] != value:
                    raise UnitTemplateError('Conflicting or unexpected duplicate template field')
                if sum(child.tag == element.tag for child in root) > 2:
                    raise UnitTemplateError('Excess duplicate template identity fields')
            fields[element.tag] = value
        if not {'Description', 'CRC'} <= set(fields) or not any(
                set(fields) == set(family.order) | {'Description', 'CRC'} for family in _FAMILIES):
            raise UnitTemplateError('Incomplete key-input template')
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
    def __init__(self, spec, *, firmware=None, catalog_number=None):
        profile = ALL_PROFILES.get(spec.unit_type)
        family = family_for(spec.unit_type) if profile else None
        catalogs = NEO_CATALOGS.get(spec.unit_type, (profile[2],)) if profile else ()
        if (profile is None or spec.filename != profile[3] or (firmware or profile[1]) != profile[1]
                or (catalog_number is not None and catalog_number not in catalogs)):
            raise UnitTemplateError('Use an exact KEY1/5031N, KEY2/5032N or KEY4/5034N profile at firmware 1.2.67, '
                                    'or an admitted NeoPro key-input type and catalogue at firmware 2.5.00')
        self.family = family
        self.profile = profile if catalog_number is None else profile[:2] + (catalog_number,) + profile[3:]
        self.parameters = family.parameters
        self.spec = spec
        for name in self.parameters:
            spec.get(name)

    def _validate_values(self, values):
        result = {}
        for name in self.parameters:
            if name not in values:
                raise UnitTemplateError('Missing template parameter: ' + name)
            value = values[name]
            if not isinstance(value, str):
                value = ' '.join(map(str, value)) if isinstance(value, (tuple, list)) else str(value)
            normalized = _normalized(name, value, self.family)
            parameter = self.spec.get(name)
            check_value = normalized if name == 'UnitName' else list(_numbers(normalized))
            if not parameter.validate_value(check_value)['valid']:
                raise UnitTemplateError('Parameter outside native schema: ' + name)
            result[name] = normalized
        return result

    def from_values(self, values, *, description=''):
        attributes = self._validate_values(values)
        attributes.update(UnitType=self.profile[0], FirmwareVersion=self.profile[1])
        attributes.update({name: '0' for name in self.family.virtual})
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
        for name in self.parameters:
            native, local = fields.get(name, {}), self.spec.get(name).fields
            if native.get('Type', '').lower() != local.get('Type', '').lower():
                raise UnitTemplateError('Native parameter type mismatch: ' + name)
            for field_name, default in (('Address', None), ('ArraySize', '1'), ('BitSize', '1' if local.get('Type') == 'bit' else '8'), ('BitAddress', '0'), ('ArraySkip', '0')):
                if _numbers(native.get(field_name, default)) != _numbers(local.get(field_name, default)):
                    raise UnitTemplateError(f'Native parameter layout mismatch: {name}/{field_name}')

    def export(self, session, *, description=''):
        self._verify_session(session)
        return self.from_values(session.values(), description=description)

    def apply(self, session, template):
        if not isinstance(template, UnitTemplate):
            raise UnitTemplateError('Parse a UnitTemplate before applying it')
        if template.profile[:2] != self.profile[:2]:
            raise UnitTemplateError('Template identity differs from the selected profile; cross-type conversion is unsupported')
        desired = self._validate_values(template.attributes)
        self._verify_session(session)
        current = self._validate_values(session.values())
        changes = {name: desired[name] for name in self.parameters if desired[name] != current[name]}
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
