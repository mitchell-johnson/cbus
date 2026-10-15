"""P5.01 wave-14 narrow offline pin for #38 (key-input template admission/exchange).

Pins pure-offline admission/exchange guards in unit_templates.py via symbols
with zero prior test refs (family_for, ALL_PROFILES, CLASSIC_FAMILY,
UnitTemplate.family): family admission routing, profile-union identity shape,
classic parameter/virtual admission set, and cross-family exchange refusal
before any native I/O. No server, hardware, GUI, or native claims; #38 stays OPEN.
"""
from __future__ import annotations

import unittest

from cbus_toolkit.unit_templates import (
    ALL_PROFILES,
    ATTRIBUTE_ORDER,
    CLASSIC_FAMILY,
    NEO_ATTRIBUTE_ORDER,
    NEO_FAMILY,
    NEO_PROFILES,
    PROFILES,
    UnitTemplate,
    UnitTemplateError,
    family_for,
)


def classic_attributes(**overrides):
    values = {name: '0' for name in ATTRIBUTE_ORDER}
    values.update(UnitType='KEY4', FirmwareVersion='1.2.67', UnitName='NEWUNIT')
    values.update(overrides)
    return values


class FamilyAdmissionWave14Tests(unittest.TestCase):
    def test_family_for_routes_classic_neo_and_refuses_unknown(self):
        # Next: native session/profile handshake stays open; routing only here.
        for unit_type in ('KEY1', 'KEY2', 'KEY4'):
            self.assertIs(family_for(unit_type), CLASSIC_FAMILY)
        for unit_type in ('KEYM4', 'KEYC4', 'KEYA1'):
            self.assertIs(family_for(unit_type), NEO_FAMILY)
        with self.assertRaisesRegex(UnitTemplateError, 'Unsupported template unit type'):
            family_for('NOPE')
        with self.assertRaisesRegex(UnitTemplateError, 'Unsupported template unit type'):
            family_for('')


class ProfileUnionWave14Tests(unittest.TestCase):
    def test_all_profiles_unites_classic_and_neo_identities(self):
        # Next: catalogue/firmware live handshake stays open; union shape only.
        self.assertEqual(set(ALL_PROFILES), set(PROFILES) | set(NEO_PROFILES))
        self.assertEqual(ALL_PROFILES['KEY4'], ('KEY4', '1.2.67', '5034N', 'KEY4.xml'))
        self.assertEqual(ALL_PROFILES['KEYM4'][1], '2.5.00')
        self.assertEqual(ALL_PROFILES['KEYM4'][3], 'KEYM4.xml')
        for unit_type, profile in ALL_PROFILES.items():
            self.assertEqual(profile[0], unit_type)
            self.assertIs(family_for(unit_type).firmware, profile[1])


class ClassicAdmissionSetWave14Tests(unittest.TestCase):
    def test_classic_parameters_exclude_metadata_and_virtual(self):
        # Next: NeoPro parameter mapping + live PP validation stay open.
        self.assertEqual(CLASSIC_FAMILY.name, 'classic')
        self.assertEqual(CLASSIC_FAMILY.firmware, '1.2.67')
        self.assertEqual(CLASSIC_FAMILY.virtual, frozenset(('InfraRedBank', 'GAVBroadcastFlag')))
        self.assertEqual(tuple(CLASSIC_FAMILY.order), tuple(ATTRIBUTE_ORDER))
        self.assertNotIn('UnitType', CLASSIC_FAMILY.parameters)
        self.assertNotIn('FirmwareVersion', CLASSIC_FAMILY.parameters)
        self.assertNotIn('InfraRedBank', CLASSIC_FAMILY.parameters)
        self.assertNotIn('GAVBroadcastFlag', CLASSIC_FAMILY.parameters)
        self.assertEqual(len(CLASSIC_FAMILY.parameters),
                         len(ATTRIBUTE_ORDER) - len(CLASSIC_FAMILY.virtual) - 2)
        self.assertEqual(tuple(NEO_FAMILY.order), tuple(NEO_ATTRIBUTE_ORDER))


class ExchangeGuardWave14Tests(unittest.TestCase):
    def test_family_property_and_cross_family_identity_refused_before_io(self):
        # Next: UnitTemplates.apply/session verify + CRC/mismatch paths stay open.
        template = UnitTemplate(classic_attributes())
        self.assertIs(template.family, CLASSIC_FAMILY)
        self.assertEqual(template.profile, ALL_PROFILES['KEY4'])
        with self.assertRaisesRegex(UnitTemplateError, 'Supported template identities'):
            UnitTemplate(classic_attributes(UnitType='KEYM4', FirmwareVersion='2.5.00'))
        with self.assertRaisesRegex(UnitTemplateError, 'Supported template identities'):
            UnitTemplate(classic_attributes(FirmwareVersion='1.2.66'))
        with self.assertRaisesRegex(UnitTemplateError, 'Nondefault InfraRedBank'):
            UnitTemplate(classic_attributes(InfraRedBank='1'))


if __name__ == '__main__':
    unittest.main()
