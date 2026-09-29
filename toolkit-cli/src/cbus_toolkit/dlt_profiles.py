"""DLT/eDLT unit profile registry and workflow admission.

Every Python DLT/eDLT gate asks this registry whether one exact identity is
admitted by one named workflow. Profiles hold sanitized facts from the
Toolkit 1.18.0.2754 / C-Gate 3.4.0.2001 catalogue, decoded unit
specifications and help topics (see research/fixtures/dlt-profile-facts.json
and research/dlt_profile_facts.py). Capabilities describe the vendor
profile; admission describes what this CLI has retained evidence for. A
refused identity always has an explicit reason, and evidence for KEYGL5
5.5.00 is never extrapolated to another type, firmware or catalogue number.
See docs/dlt-profiles.md.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from types import MappingProxyType

from .unitspec import compare_versions


class DltProfileError(ValueError):
    pass


@dataclass(frozen=True)
class Revision:
    minimum: str
    maximum: str
    internal: bool = False
    default: bool = False

    def contains(self, firmware):
        return compare_versions(firmware, self.minimum) >= 0 and compare_versions(firmware, self.maximum) <= 0

    def as_dict(self):
        return {'min': self.minimum, 'max': self.maximum, 'internal': self.internal, 'default': self.default}


@dataclass(frozen=True)
class DltProfile:
    unit_type: str
    family: str
    style: str
    spec_filename: str
    spec_sha256: str
    label_spec: str | None
    catalog_numbers: tuple
    revisions: tuple
    help_topics: tuple
    help_catalog_names: tuple
    # Vendor capabilities, not CLI support.
    static_label_text: bool
    dynamic_labels: bool
    label_variant_selection: bool
    edlt_widgets: bool

    def revision(self, firmware):
        rows = [row for row in self.revisions if row.contains(firmware)]
        return rows[0] if len(rows) == 1 else None

    def as_dict(self):
        return {'unit_type': self.unit_type, 'family': self.family, 'style': self.style,
                'spec_filename': self.spec_filename, 'spec_sha256': self.spec_sha256,
                'label_spec': self.label_spec, 'catalog_numbers': list(self.catalog_numbers),
                'revisions': [row.as_dict() for row in self.revisions],
                'help_topics': list(self.help_topics), 'help_catalog_names': list(self.help_catalog_names),
                'capabilities': {'static_label_text': self.static_label_text,
                                 'dynamic_labels': self.dynamic_labels,
                                 'label_variant_selection': self.label_variant_selection,
                                 'edlt_widgets': self.edlt_widgets},
                'workflows': {name: workflow.summary(self.unit_type) for name, workflow in WORKFLOWS.items()
                              if self.unit_type in workflow.unit_types()}}


def _classic_revisions(first_public):
    rows = [Revision('1.1', '1.1', internal=True), Revision('1.4.00', '1.4.00'),
            Revision('1.4.01', '1.4.16', internal=True)] if first_public == '1.4.00' else []
    return tuple(rows) + (Revision('2.0.00', '2.0.00', internal=first_public != '1.4.00'),
                          Revision('2.0.01', '2.0.99', internal=True),
                          Revision('2.1.00', '2.1.00', default=True),
                          Revision('2.1.01', '2.9.99', internal=True),
                          Revision('3.0.00', '3.0.99'))


KEYL5_SHA256 = 'c3f29166c59b03a76c4545ca3dd79de89b277fe5f0a3188b5bd686a3795a8095'
KEYL4_SHA256 = '8d045edada38377378d01c76d5c48c7a84126aea7e3e1a1973dac312f26fd995'
KEYGL5_SHA256 = '812d2f92ccf3176d9f3d4c0f35fc196ac9ba45bc419639421e4e5ff082d2af21'
I_DLT_SHA256 = '48fcff154e8172e254323e766f795650bab7d0dd572beebbf68a08c4922e2133'
I_DLTF_SHA256 = 'db1eee1f7c92271085514e11e0061b617dbb39094c318f5bf29c7e598f7d3c28'
# I_DLT.xml carries LabelFlavourLSB/MSB and declares MinVersion 2.0.
I_DLT_MIN_VERSION = '2.0'

PROFILES = MappingProxyType({row.unit_type: row for row in (
    DltProfile('KEYBL5', 'classic-dlt', 'Saturn 5-key DLT', 'KEYL5.xml', KEYL5_SHA256, 'I_DLT.xml',
               ('5085DL',), _classic_revisions('1.4.00'),
               ('help:2111.htm', 'help:2500.htm', 'help:4898.htm'), ('5085DL',),
               static_label_text=False, dynamic_labels=True, label_variant_selection=True, edlt_widgets=False),
    DltProfile('KEYML5', 'classic-dlt', 'Neo 5-key DLT', 'KEYL5.xml', KEYL5_SHA256, 'I_DLT.xml',
               ('5055DL',), _classic_revisions('1.4.00'),
               ('help:2092.htm', 'help:2160.htm', 'help:2506.htm', 'help:4838.htm'), ('5055DL', 'SLC5055DL'),
               static_label_text=False, dynamic_labels=True, label_variant_selection=True, edlt_widgets=False),
    DltProfile('KEYDL4', 'classic-dlt', 'Decorator 4-key DLT', 'KEYL4.xml', KEYL4_SHA256, 'I_DLT.xml',
               ('E5054DL', 'E5084DL'), _classic_revisions('2.0.00'),
               ('help:2113.htm', 'help:2501.htm', 'help:4825.htm'), ('5084DL',),
               static_label_text=False, dynamic_labels=True, label_variant_selection=True, edlt_widgets=False),
    DltProfile('KEYGL5', 'edlt', 'eDLT 5-key', 'KEYGL5.xml', KEYGL5_SHA256, None,
               ('5055EDL', '5085EDL', '5085EDLB', 'R5045EDL', 'R5045EDLW'),
               (Revision('1.5.01', '1.5.99', internal=True), Revision('1.6.00', '1.6.99'),
                Revision('1.7.00', '1.7.99'), Revision('5.4.00', '5.4.99'),
                Revision('5.5.00', '5.5.99', default=True), Revision('5.6.00', '9', internal=True)),
               ('help:18867.htm', 'help:19689.htm', 'help:19690.htm'), ('5085ED', '5505ED', 'R5045ED'),
               static_label_text=True, dynamic_labels=True, label_variant_selection=False, edlt_widgets=True),
)})

# Catalogue-alias finding: every KEYGL5 help catalogue name is absent from
# cbusunits.xml, and help never names 5055EDL, the only admitted eDLT
# catalogue number. Help topic 20074 names KEYH5 for R5045EDL, but neither the
# catalogue nor the decoded specifications define KEYH5; the catalogue maps
# R5045EDL to KEYGL5. Help 5084DL/SLC5055DL are also not catalogue numbers.
HELP_ONLY_CATALOG_NAMES = MappingProxyType({
    '5505ED': 'KEYGL5', '5085ED': 'KEYGL5', 'R5045ED': 'KEYGL5', '5084DL': 'KEYDL4', 'SLC5055DL': 'KEYML5'})
UNDEFINED_HELP_TYPES = MappingProxyType({
    'KEYH5': 'Toolkit help topic 20074 names KEYH5 for R5045EDL, but neither the C-Gate catalogue nor any '
             'decoded unit specification defines KEYH5; the catalogue maps R5045EDL to KEYGL5'})
# Specification-only facts: KEYL5.xml's Type is KEYL5, which no catalogue
# revision reports; I_DLTF.xml is a fragment that no specification includes.
SPEC_ONLY_TYPES = MappingProxyType({
    'KEYL5': 'KEYL5 is the Type inside KEYL5.xml; the catalogue reports KEYBL5 (Saturn) or KEYML5 (Neo)'})
UNUSED_FRAGMENTS = MappingProxyType({
    'I_DLTF.xml': 'Internal fragment included by no unit specification; C-Gate cannot open it as a PP session'})

EDLT_EVIDENCE = ('KEYGL5', '5.5.00', '5055EDL')
_PHYSICAL_FIRMWARE = re.compile(r'([0-9]{1,2})\.([0-9]{1,2})\.([0-9]{1,2})')
_VERSION = re.compile(r'[0-9]{1,4}(\.[0-9]{1,4}){1,3}')


def physical_firmware(value):
    """Canonicalize a physical IDENTIFY firmware string such as ``05.05.00``.

    Each component may be one or two digits; the canonical form uses the
    database spelling ``M.m.pp``. Anything else is returned as ``None``.
    """
    match = _PHYSICAL_FIRMWARE.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        return None
    return f'{int(match[1])}.{int(match[2])}.{int(match[3]):02d}'


@dataclass(frozen=True)
class Workflow:
    name: str
    description: str
    identity: tuple          # 'unit_type', 'firmware', 'catalog_number' in the order checked
    admitted: tuple          # exact admitted identities (type, firmware, catalogue) or rules
    firmware_form: str = 'database'

    def unit_types(self):
        return {row[0] for row in self.admitted}

    def summary(self, unit_type):
        rows = [row for row in self.admitted if row[0] == unit_type]
        return {'identity': list(self.identity), 'firmware_form': self.firmware_form,
                'admitted': [{'firmware': row[1], 'catalog_number': row[2]} for row in rows]}


_EDLT_FULL = (EDLT_EVIDENCE,)
_EDLT_FIRMWARE = (('KEYGL5', '5.5.00', None),)
# Classic label variants: public (non-internal) catalogue revisions at or
# above I_DLT.xml's MinVersion. '*' admits any catalogue number of the type.
_CLASSIC = tuple((unit_type, firmware, '*') for unit_type in ('KEYBL5', 'KEYML5', 'KEYDL4')
                 for firmware in ('2.0.00', '2.1.00', '3.0.00..3.0.99')
                 if not (unit_type == 'KEYDL4' and firmware == '2.0.00'))
WORKFLOWS = MappingProxyType({row.name: row for row in (
    Workflow('edlt-database-widgets', 'Database PP eDLT widget, global and lifecycle editors',
             ('unit_type', 'firmware', 'catalog_number'), _EDLT_FULL),
    Workflow('edlt-parent-metadata', 'Native XML parent transaction and SceneManager metadata',
             ('unit_type', 'firmware', 'catalog_number'), _EDLT_FULL),
    Workflow('edlt-global-source', 'Global Programming / factory preparation source PP export',
             ('unit_type', 'firmware', 'catalog_number'), _EDLT_FULL),
    Workflow('edlt-label-clear', 'Physical eDLT dynamic-label clear request',
             ('unit_type', 'firmware'), _EDLT_FIRMWARE),
    Workflow('edlt-physical-labels', 'Physical eDLT static-label/widget memory read through cmqttd',
             ('unit_type', 'firmware'), _EDLT_FIRMWARE, firmware_form='physical'),
    Workflow('serial-population', 'Database serial metadata population (Toolkit equality branch)',
             ('unit_type',), (('KEYGL5', None, None),)),
    Workflow('classic-dlt-label-variants', 'Classic DLT per-key LabelFlavour (label variant) PP edits',
             ('unit_type', 'firmware', 'catalog_number'), _CLASSIC),
)})


def _firmware_matches(rule, firmware):
    if rule is None:
        return True
    if '..' in rule:
        low, high = rule.split('..')
        return compare_versions(firmware, low) >= 0 and compare_versions(firmware, high) <= 0
    return firmware == rule


def _canonical_firmware(workflow, firmware):
    if workflow.firmware_form == 'physical':
        return physical_firmware(firmware)
    return firmware if isinstance(firmware, str) and _VERSION.fullmatch(firmware) else None


def _unknown_type_reason(unit_type):
    if not isinstance(unit_type, str):
        return 'Unit type must be text'
    if unit_type in UNDEFINED_HELP_TYPES:
        return UNDEFINED_HELP_TYPES[unit_type]
    if unit_type in SPEC_ONLY_TYPES:
        return SPEC_ONLY_TYPES[unit_type]
    return f'{unit_type!r} is not a DLT or eDLT unit type in the retained catalogue'


def refusal(workflow, unit_type, firmware=None, catalog_number=None):
    """Return why an identity is outside ``workflow``, or ``None`` when admitted."""
    if workflow not in WORKFLOWS:
        raise DltProfileError('Unknown DLT workflow: ' + repr(workflow))
    rule = WORKFLOWS[workflow]
    if not isinstance(unit_type, str) or unit_type not in PROFILES:
        return _unknown_type_reason(unit_type)
    profile = PROFILES[unit_type]
    rows = [row for row in rule.admitted if row[0] == unit_type]
    if not rows:
        if profile.family == 'classic-dlt' and workflow.startswith('edlt-'):
            return (f'{unit_type} is a classic {profile.style} ({profile.spec_filename} / I_DLT.xml) without '
                    'eDLT widgets or unit-resident static label text')
        if profile.family == 'edlt' and workflow.startswith('classic-'):
            return ('KEYGL5 is an eDLT; per-key label variants (LabelFlavour) are classic I_DLT.xml fields '
                    'that KEYGL5.xml does not declare')
        return f'{unit_type} ({profile.style}) has no retained evidence for the {workflow} workflow'
    if 'firmware' not in rule.identity:
        return None
    canonical = _canonical_firmware(rule, firmware)
    if canonical is None:
        return f'{unit_type} firmware {firmware!r} is not a recognised version string'
    revision = profile.revision(canonical)
    if revision is None:
        return f'{unit_type} firmware {canonical} is outside every C-Gate catalogue revision'
    rows = [row for row in rows if _firmware_matches(row[1], canonical)]
    if not rows:
        if profile.family == 'edlt':
            return (f'KEYGL5 firmware {canonical} (catalogue revision {revision.minimum}..{revision.maximum}) '
                    'shares KEYGL5.xml, but only 5.5.00 evidence is retained and it is not extrapolated')
        if compare_versions(canonical, I_DLT_MIN_VERSION) < 0:
            return (f'{unit_type} firmware {canonical} is below I_DLT.xml MinVersion {I_DLT_MIN_VERSION}, '
                    'the specification that declares the label variant fields')
        if revision.internal:
            return (f'{unit_type} firmware {canonical} is in catalogue revision {revision.minimum}..'
                    f'{revision.maximum}, which C-Gate marks IsInternal')
        return f'{unit_type} firmware {canonical} has no retained evidence for {workflow}'
    if 'catalog_number' not in rule.identity:
        return None
    if catalog_number is None and all(row[2] == '*' for row in rows):
        return None
    if catalog_number is not None and not isinstance(catalog_number, str):
        return 'Catalogue number must be text'
    if catalog_number in HELP_ONLY_CATALOG_NAMES:
        return (f'{catalog_number!r} is a Toolkit help catalogue name that does not exist in the C-Gate '
                f'catalogue (catalogue numbers for {unit_type}: {", ".join(profile.catalog_numbers)})')
    if catalog_number not in profile.catalog_numbers:
        return f'Catalogue number {catalog_number!r} is not a C-Gate catalogue number for {unit_type}'
    if any(row[2] in ('*', catalog_number) for row in rows):
        return None
    return (f'Catalogue number {catalog_number} shares {profile.spec_filename} with 5055EDL, but only '
            '5055EDL evidence is retained')


def admits(workflow, unit_type, firmware=None, catalog_number=None):
    return refusal(workflow, unit_type, firmware, catalog_number) is None


def require(workflow, unit_type, firmware=None, catalog_number=None, *, error=DltProfileError, message=None):
    """Raise ``error`` with ``message`` and the registry reason unless admitted."""
    reason = refusal(workflow, unit_type, firmware, catalog_number)
    if reason is not None:
        raise error((message + ': ' if message else '') + reason)
    return unit_type, firmware, catalog_number


def admitted_types(workflow):
    return frozenset(WORKFLOWS[workflow].unit_types())


def profile_for(unit_type):
    if unit_type not in PROFILES:
        raise DltProfileError(_unknown_type_reason(unit_type))
    return PROFILES[unit_type]


def lookup(unit_type, firmware=None, catalog_number=None):
    """Report the profile facts and every workflow decision for one identity."""
    if unit_type not in PROFILES:
        return {'unit_type': unit_type, 'profile': None, 'reason': _unknown_type_reason(unit_type),
                'workflows': {}}
    profile = PROFILES[unit_type]
    revision = None
    canonical = physical_firmware(firmware) if firmware is not None and not _VERSION.fullmatch(firmware) \
        else firmware
    if canonical is not None and _VERSION.fullmatch(canonical):
        row = profile.revision(canonical)
        revision = None if row is None else row.as_dict()
    decisions = {}
    for name in WORKFLOWS:
        reason = refusal(name, unit_type, firmware, catalog_number)
        decisions[name] = {'admitted': reason is None, 'reason': reason}
    return {'unit_type': unit_type, 'firmware': firmware, 'catalog_number': catalog_number,
            'catalogue_revision': revision, 'profile': profile.as_dict(), 'workflows': decisions}


def registry():
    return {'format': 'cbus-dlt-profile-registry-v1',
            'profiles': [profile.as_dict() for profile in PROFILES.values()],
            'workflows': {name: {'description': row.description, 'identity': list(row.identity),
                                 'firmware_form': row.firmware_form} for name, row in WORKFLOWS.items()},
            'findings': {'help_only_catalog_names': dict(HELP_ONLY_CATALOG_NAMES),
                         'undefined_help_types': dict(UNDEFINED_HELP_TYPES),
                         'spec_only_types': dict(SPEC_ONLY_TYPES),
                         'unused_fragments': {**UNUSED_FRAGMENTS, 'I_DLTF.xml sha256': I_DLTF_SHA256}}}
