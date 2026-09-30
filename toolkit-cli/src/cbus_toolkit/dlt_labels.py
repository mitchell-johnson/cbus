"""Classic Saturn/Neo/Decorator DLT per-key label variant (LabelFlavour) model.

Classic DLT units (KEYBL5, KEYML5 via KEYL5.xml; KEYDL4 via KEYL4.xml) keep
no label text in unit memory. Label text lives in the project as up to four
variants per group or action selector and reaches the unit as dynamic
labels. The unit-resident label configuration is one variant selection per
key slot, stored as the I_DLT.xml ``LabelFlavourLSB`` (bit 3) and
``LabelFlavourMSB`` (bit 6) arrays in bytes 0x60..0x67. The other bits of
those bytes belong to I_NEOCORE.xml indicator and scene-key fields and are
preserved.

Toolkit 1.18.0.2754 ``TCBusDynamicLabelInputCGateAgent.LoadLabelFlavours``
exposes each key's variant as ``2*MSB + LSB + 1`` (1..4), and
``SaveLabelFlavours`` stores ``LSB = (variant-1) mod 2`` and
``MSB = (variant-1) div 2``; the pinned instruction ranges are recorded in
research/fixtures/dlt-profile-facts.json. This module stages database PP
sessions only: it does not save, transfer labels, render a display or send
dynamic-label messages. See docs/dlt-profiles.md.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from types import MappingProxyType
import xml.etree.ElementTree as ET

from .dlt_profiles import PROFILES, require, refusal
from .macros import MacroError, _numbers
from .memory import MemoryCodec, MemoryImage
from .programming import xml_text


class DltLabelError(ValueError):
    pass


class DltLabelApplyError(RuntimeError):
    def __init__(self, cause, attempted):
        self.cause, self.attempted = cause, tuple(attempted)
        self.details = {'attempted_parameters': list(self.attempted), 'saved': False, 'device_verified': False}
        super().__init__('DLT label variant edit stopped; PP changes may be partial and were not saved: '
                         + str(cause))


WORKFLOW = 'classic-dlt-label-variants'
PLAN_FORMAT = 'cbus-dlt-label-variant-plan-v1'
VIEW_FORMAT = 'cbus-dlt-label-variants-v1'
SLOTS = 8
VARIANTS = (1, 2, 3, 4)
BYTE_ADDRESS = 0x60
FLAVOUR_MASK = 0x48
# Name: (address, array size, bit size, bit address, array skip, type). The
# five fields exactly cover bytes 0x60..0x67 in both KEYL5.xml and KEYL4.xml.
LAYOUT = MappingProxyType({
    'IndicatorBlockAssignment': (0x60, 8, 3, 0, 0, 'int'),
    'LabelFlavourLSB': (0x60, 8, 1, 3, 0, 'int'),
    'IndicatorFunction': (0x60, 8, 2, 4, 0, 'int'),
    'LabelFlavourMSB': (0x60, 8, 1, 6, 0, 'int'),
    'SceneKeySelector': (0x60, 8, 1, 7, 0, 'int'),
})
FIELDS = tuple(LAYOUT)
CHANGED = ('LabelFlavourLSB', 'LabelFlavourMSB')
# I_DLT.xml "Allow Dynamic Labelling". The optional dlt_controls editor owns
# the original inverse "Block Dynamic Updates" control.
DYNAMIC_FLAG = ('EnableDynamicLabels', (0x3E, 1, 1, 6, 0, 'bit'))


def variant(lsb, msb):
    """Toolkit LoadLabelFlavours: 2*min(MSB, 1) + min(LSB, 1) + 1."""
    return 2 * min(msb, 1) + min(lsb, 1) + 1


def flavour_bits(value):
    """Toolkit SaveLabelFlavours: (LSB, MSB) for a 1..4 variant."""
    if isinstance(value, bool) or not isinstance(value, int) or value not in VARIANTS:
        raise DltLabelError('Label variant must be an integer in 1..4')
    return (value - 1) % 2, (value - 1) // 2


def _values(value, name):
    try:
        values = _numbers(value)
    except MacroError as error:
        raise DltLabelError('Invalid current ' + name) from error
    return values


@dataclass(frozen=True)
class DltLabelPlan:
    unit_type: str
    identity: tuple | None
    expected: dict
    changes: dict
    requested: tuple
    raw_preview: tuple

    def __post_init__(self):
        for name in ('expected', 'changes'):
            object.__setattr__(self, name, MappingProxyType({k: tuple(v) for k, v in getattr(self, name).items()}))

    def variants(self, *, after=True):
        source = dict(self.expected)
        if after:
            source.update(self.changes)
        return tuple(variant(lsb, msb) for lsb, msb in zip(source['LabelFlavourLSB'], source['LabelFlavourMSB']))

    def as_dict(self):
        profile = PROFILES[self.unit_type]
        firmware, catalog_number = self.identity[1:] if self.identity else (None, None)
        return {'format': PLAN_FORMAT, 'unit_type': self.unit_type, 'firmware': firmware,
                'catalog_number': catalog_number, 'spec_filename': profile.spec_filename,
                'label_spec': profile.label_spec, 'requested': [list(row) for row in self.requested],
                'variants_before': list(self.variants(after=False)), 'variants_after': list(self.variants()),
                'expected': {k: list(v) for k, v in self.expected.items()},
                'changes': {k: list(v) for k, v in self.changes.items()},
                'raw_preview': [dict(row) for row in self.raw_preview],
                'saved': False, 'device_verified': False, 'labels_transferred': False}

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict) or data.get('format') != PLAN_FORMAT:
            raise DltLabelError('Expected a ' + PLAN_FORMAT + ' document')
        unit_type = data.get('unit_type')
        if unit_type not in PROFILES or PROFILES[unit_type].family != 'classic-dlt':
            raise DltLabelError('Plan unit type is not a classic DLT profile')
        try:
            expected = {str(k): tuple(v) for k, v in data['expected'].items()}
            changes = {str(k): tuple(v) for k, v in data['changes'].items()}
            requested = tuple((int(slot), int(value)) for slot, value in data['requested'])
            preview = tuple(MappingProxyType(dict(row)) for row in data.get('raw_preview') or ())
        except (KeyError, AttributeError, TypeError, ValueError) as error:
            raise DltLabelError('Plan requires expected, changes and requested fields') from error
        firmware = data.get('firmware')
        identity = None
        if firmware is not None:
            identity = require(WORKFLOW, unit_type, firmware, data.get('catalog_number'), error=DltLabelError,
                               message='Plan identity is not an admitted classic DLT profile')
        return cls(unit_type, identity, expected, changes, requested, preview)


class ClassicDltLabels:
    def __init__(self, spec, unit_type):
        if unit_type not in PROFILES or PROFILES[unit_type].family != 'classic-dlt':
            raise DltLabelError(refusal(WORKFLOW, unit_type) or 'Only classic DLT profiles use this workflow')
        self.profile = PROFILES[unit_type]
        if spec.filename != self.profile.spec_filename:
            raise DltLabelError(f'Use {self.profile.spec_filename} for {unit_type}')
        self.spec, self.codec = spec, MemoryCodec(spec)
        for name, expected in (*LAYOUT.items(), DYNAMIC_FLAG):
            try:
                layout = self.codec.layout(name)
            except Exception as error:
                raise DltLabelError('Unit specification lacks classic DLT label field ' + name) from error
            actual = (layout.address, layout.array_size, layout.bit_size, layout.bit_address,
                      layout.array_skip, layout.parameter.type)
            if actual != expected:
                raise DltLabelError('Unsupported classic DLT label layout: ' + name)

    @property
    def unit_type(self):
        return self.profile.unit_type

    def check_identity(self, unit_type, firmware, catalog_number=None, *, subject='Unit identity'):
        identity = require(WORKFLOW, unit_type, firmware, catalog_number, error=DltLabelError,
                           message=subject + ' is not an admitted classic DLT label-variant profile')
        if unit_type != self.unit_type:
            raise DltLabelError(subject + ' unit type differs from the selected profile')
        return identity

    def snapshot(self, current):
        result = {}
        for name in FIELDS:
            if name not in current:
                raise DltLabelError('Missing current DLT label parameter: ' + name)
            values = _values(current[name], name)
            if not self.spec.get(name).validate_value(list(values))['valid']:
                raise DltLabelError('Invalid current DLT label parameter: ' + name)
            result[name] = values
        return result

    def _raw(self, values):
        image = self.codec.encode_many(values).apply(MemoryImage.from_bytes(bytes(SLOTS), start=BYTE_ADDRESS))
        return image.read(BYTE_ADDRESS, SLOTS)

    def show(self, current, identity=None):
        values = self.snapshot(current)
        raw = self._raw(values)
        flag = current.get(DYNAMIC_FLAG[0])
        return {'format': VIEW_FORMAT, 'unit_type': self.unit_type,
                'firmware': identity[1] if identity else None,
                'catalog_number': identity[2] if identity else None,
                'spec_filename': self.profile.spec_filename, 'label_spec': self.profile.label_spec,
                'slots': [{'slot': index + 1, 'variant': variant(lsb, msb), 'lsb': lsb, 'msb': msb,
                           'address': BYTE_ADDRESS + index, 'raw_byte': raw[index]}
                          for index, (lsb, msb) in enumerate(zip(values['LabelFlavourLSB'],
                                                                 values['LabelFlavourMSB']))],
                'enable_dynamic_labels_raw': None if flag is None else _values(flag, DYNAMIC_FLAG[0])[0],
                'label_text_in_unit': False, 'slot_to_physical_key_verified': False}

    def plan(self, current, *, variants, identity=None):
        if identity is not None:
            identity = self.check_identity(*identity)
        if not isinstance(variants, dict) or not variants:
            raise DltLabelError('Supply at least one slot=variant selection')
        requested = []
        for slot, value in variants.items():
            if isinstance(slot, bool) or not isinstance(slot, int) or not 1 <= slot <= SLOTS:
                raise DltLabelError(f'Label variant slot must be an integer in 1..{SLOTS}')
            flavour_bits(value)
            requested.append((slot, value))
        requested.sort()
        expected = self.snapshot(current)
        lsb, msb = list(expected['LabelFlavourLSB']), list(expected['LabelFlavourMSB'])
        for slot, value in requested:
            lsb[slot - 1], msb[slot - 1] = flavour_bits(value)
        changes = {name: tuple(values) for name, values in (('LabelFlavourLSB', lsb), ('LabelFlavourMSB', msb))
                   if tuple(values) != expected[name]}
        after = dict(expected)
        after.update(changes)
        before_raw, after_raw = self._raw(expected), self._raw(after)
        preview = tuple(MappingProxyType({'address': BYTE_ADDRESS + index, 'before': before_raw[index],
                                          'after': after_raw[index],
                                          'changed_mask': before_raw[index] ^ after_raw[index]})
                        for index in range(SLOTS))
        if any(row['changed_mask'] & ~FLAVOUR_MASK for row in preview):
            raise DltLabelError('Label variant edit would change bits outside LabelFlavourLSB/MSB')
        return DltLabelPlan(self.unit_type, identity, expected, changes, tuple(requested), preview)

    def _verify_profile(self, session):
        return self.check_identity(session.unit_type, session.firmware, session.catalog_number,
                                   subject='Native session')

    def _verify_session(self, session, *, fields=FIELDS):
        document = xml_text(session.info('*'))
        if '<!DOCTYPE' in document.upper() or '<!ENTITY' in document.upper():
            raise DltLabelError('Unsupported native schema declarations')
        try:
            root = ET.fromstring(document)
        except ET.ParseError as error:
            raise DltLabelError('Invalid native parameter schema') from error
        native_fields = {}
        for param in root.iter():
            if param.tag.rsplit('}', 1)[-1] == 'Param':
                row = {child.tag.rsplit('}', 1)[-1]: child.text or '' for child in param}
                if row.get('Name') in native_fields:
                    raise DltLabelError('Duplicate native parameter schema')
                native_fields[row.get('Name')] = row
        for name in fields:
            native, local = native_fields.get(name, {}), self.spec.get(name).fields
            if native.get('Type', '').lower() != local.get('Type', '').lower():
                raise DltLabelError('Native parameter type mismatch: ' + name)
            for field, default in (('Address', None), ('ArraySize', '1'), ('BitAddress', '0'),
                                   ('BitSize', '8'), ('ArraySkip', '0')):
                if _values(native.get(field, default), name) != _values(local.get(field, default), name):
                    raise DltLabelError(f'Native parameter layout mismatch: {name}/{field}')

    def _raw_readback(self, session):
        if not hasattr(session, 'get_raw_data'):
            return None
        line = session.get_raw_data(BYTE_ADDRESS, SLOTS).lines[-1]
        if 'RawData=' not in line:
            raise DltLabelError('Native raw readback did not return RawData')
        return bytes.fromhex(line.split('RawData=', 1)[1].strip())

    def apply(self, session, plan):
        if (not isinstance(plan, DltLabelPlan) or plan.unit_type != self.unit_type
                or set(plan.expected) != set(FIELDS) or any(name not in CHANGED for name in plan.changes)):
            raise DltLabelError('Plan contains fields or a unit type outside this DLT label workflow')
        self.codec.encode_many(plan.changes)
        identity = self._verify_profile(session)
        if plan.identity is not None and plan.identity[:2] != identity[:2]:
            raise DltLabelError('Plan was created for another unit type or firmware')
        self._verify_session(session)
        if self.snapshot(session.values()) != dict(plan.expected):
            raise DltLabelError('PP parameters changed since the DLT label plan was created')
        expected = dict(plan.expected)
        expected.update(plan.changes)
        attempted = []
        try:
            for name, values in plan.changes.items():
                attempted.append(name)
                session.set(name, ' '.join(map(str, values)))
            if self.snapshot(session.values()) != expected:
                raise DltLabelError('Native DLT label readback differs from the plan')
            raw = self._raw_readback(session)
            if raw is not None and raw != self._raw(expected):
                raise DltLabelError('Native raw bytes 0x60..0x67 differ from the planned image')
        except (RuntimeError, OSError, ValueError) as error:
            # No recovery I/O after a partial or uncertain PP edit; the unsaved
            # session can be inspected or discarded by its owner.
            raise DltLabelApplyError(error, attempted) from error
        return {**replace(plan, identity=identity).as_dict(), 'verified': True,
                'raw_bytes_verified': raw is not None,
                'raw_after_hex': None if raw is None else raw.hex()}

    def configure(self, session, *, variants):
        identity = self._verify_profile(session)
        return self.apply(session, self.plan(session.values(), variants=variants, identity=identity))


def project_unit(text, unit_path):
    """Read one unit's identity and PP values from native Installation XML.

    Accepts C-Gate DBGETXML project output. Only UnitType, FirmwareVersion,
    optional CatalogNumber and the ``<PP Name Value>`` rows are consumed.
    """
    from .addressing import _container
    from .toolkit_database_csv_native import _byte, _children, _field, _path
    project_name, network_address, unit_address = _path(unit_path)
    root = _container(text, 'Installation').documentElement
    projects = [node for node in _children(root, 'Project') if _field(node, 'Address') == project_name]
    if len(projects) != 1:
        raise DltLabelError('Native XML must contain exactly the selected project')

    def one(parent, kind, address):
        rows = [node for node in _children(parent, kind)
                if _byte(_field(node, 'Address'), kind + ' address') == address]
        if len(rows) != 1:
            raise DltLabelError(f'Expected exactly one native {kind} at address {address}')
        return rows[0]

    unit = one(one(projects[0], 'Network', network_address), 'Unit', unit_address)
    catalog = _children(unit, 'CatalogNumber')
    identity = (_field(unit, 'UnitType'), _field(unit, 'FirmwareVersion'),
                _field(unit, 'CatalogNumber') if catalog else None)
    values = {}
    for row in _children(unit, 'PP'):
        name = row.getAttribute('Name')
        if not name or name in values or not row.hasAttribute('Value') or row.childNodes:
            raise DltLabelError('Native PP rows require unique Name and Value attributes')
        values[name] = row.getAttribute('Value')
    return identity, values
