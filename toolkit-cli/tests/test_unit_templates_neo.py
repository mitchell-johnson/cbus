"""NeoPro key-input Toolkit templates and Unicode Description metadata."""
import json
import os
from pathlib import Path
import unittest
from uuid import uuid4

from cbus_toolkit.unit_templates import (ATTRIBUTE_ORDER, NEO_ATTRIBUTE_ORDER, NEO_CATALOGS, NEO_FAMILY,
                                         NEO_PROFILES, UnitTemplate, UnitTemplateError, UnitTemplates,
                                         template_crc)
from cbus_toolkit.unitspec import UnitSpecStore


ROOT = Path(__file__).resolve().parents[1]
PRESETS = ROOT / 'research/fixtures/key-preset-family-equivalence.json'
EXCLUDED = ('Project', 'SerialNo', 'State', 'UnitAddress', 'LearnedFlag')
UNICODE = 'Küche — 客厅 🌟 "A&B" <tab>\there'
SPECS = os.environ.get('CBUS_UNITSPEC_DIR')
VENDOR = os.environ.get('CBUS_LOCAL_CGATE_VENDOR')


def synthetic(unit_type='KEYM4', **changes):
    attributes = {name: '0' for name in NEO_ATTRIBUTE_ORDER}
    attributes.update(UnitType=unit_type, FirmwareVersion='2.5.00', UnitName='NEWUNIT',
                      Application='56 255', GroupAddress='1 2 3 255 255 255 255 255 255')
    attributes.update(changes)
    return attributes


class NeoTemplateFormatTests(unittest.TestCase):
    def test_attribute_list_matches_recovered_neopro_agent(self):
        self.assertEqual(len(NEO_ATTRIBUTE_ORDER), 58)
        self.assertEqual(len(set(NEO_ATTRIBUTE_ORDER)), 58)
        self.assertIn('IRBank', NEO_ATTRIBUTE_ORDER)
        self.assertIn('PatchEnable', NEO_ATTRIBUTE_ORDER)
        self.assertNotIn('InfraRedBank', NEO_ATTRIBUTE_ORDER)
        self.assertNotIn('GAVBroadcastFlag', NEO_ATTRIBUTE_ORDER)
        self.assertFalse(set(EXCLUDED) & set(NEO_ATTRIBUTE_ORDER))
        # The shared key-input prefix keeps the classic order with the IRBank rename.
        classic = [('IRBank' if name == 'InfraRedBank' else name) for name in ATTRIBUTE_ORDER[:-1]]
        self.assertEqual(list(NEO_ATTRIBUTE_ORDER[:len(classic)]), classic)
        self.assertEqual(len(NEO_FAMILY.parameters), 56)
        self.assertEqual(NEO_FAMILY.virtual, frozenset())

    def test_profiles_are_the_admitted_neopro_types(self):
        rows = json.loads(PRESETS.read_text(encoding='utf-8'))['families']['neo']['types']
        admitted = {row['unit_type']: row for row in rows if row['decision'] == 'admitted'
                    and row['toolkit_agent_class'] == 'TCBusNeoProInputCGateAgent'}
        self.assertEqual(len(admitted), 30)
        self.assertEqual(set(NEO_PROFILES), set(admitted))
        for unit_type, row in admitted.items():
            self.assertEqual(NEO_PROFILES[unit_type], (unit_type, '2.5.00', row['catalog_selection']['catalog_numbers'][0],
                                                       row['spec_filename']))
            self.assertEqual(list(NEO_CATALOGS[unit_type]), row['catalog_selection']['catalog_numbers'])

    def test_literal_roundtrip_crc_and_identity(self):
        template = UnitTemplate(synthetic(PatchEnable='1 2', IRBank='2', UnitName='A<&"B'), 'Neo')
        text = template.to_xml()
        self.assertTrue(text.startswith('<?xml version="1.0" encoding="utf-8"?>\r\n<UnitTemplate>\r\n'))
        self.assertIn('<PatchEnable>1 2</PatchEnable>', text)
        self.assertIn('<IRBank>2</IRBank>', text)
        self.assertIn('<UnitName>A&lt;&amp;&quot;B</UnitName>', text)
        parsed = UnitTemplate.from_xml(text.encode('utf-8'))
        self.assertEqual(dict(parsed.attributes), dict(template.attributes))
        self.assertEqual(parsed.crc, template_crc(dict(template.attributes)))
        self.assertEqual(parsed.profile, NEO_PROFILES['KEYM4'])
        self.assertNotEqual(UnitTemplate(synthetic(IRBank='1')).crc, UnitTemplate(synthetic()).crc)
        with self.assertRaises(UnitTemplateError):
            UnitTemplate.from_xml(text.replace(f'<CRC>{template.crc}</CRC>', f'<CRC>{(template.crc + 1) % 65536}</CRC>'))

    def test_wrong_identity_mixed_fields_and_unsupported_types_rejected(self):
        for attributes in (synthetic(FirmwareVersion='1.2.67'), synthetic('KEY4'), synthetic('KEYE1'),
                           {**synthetic(), 'InfraRedBank': '0'}):
            with self.subTest(attributes=attributes.get('UnitType')), self.assertRaises(UnitTemplateError):
                UnitTemplate(attributes)
        text = UnitTemplate(synthetic()).to_xml()
        for changed in (text.replace('    <IRBank>0</IRBank>\r\n', ''),
                        text.replace('</UnitTemplate>', '<InfraRedBank>0</InfraRedBank></UnitTemplate>'),
                        text.replace('</UnitTemplate>', '<GAVBroadcastFlag>0</GAVBroadcastFlag></UnitTemplate>')):
            with self.assertRaises(UnitTemplateError):
                UnitTemplate.from_xml(changed)

    def test_unicode_description_is_file_metadata_only(self):
        for attributes in (synthetic(), synthetic('KEYC4')):
            plain = UnitTemplate(attributes)
            template = UnitTemplate(attributes, UNICODE)
            data = template.to_xml().encode('utf-8')
            parsed = UnitTemplate.from_xml(data)
            self.assertEqual(parsed.description, UNICODE)
            self.assertEqual(parsed.crc, plain.crc)
            self.assertEqual(dict(parsed.attributes), dict(plain.attributes))
            self.assertEqual(UnitTemplate.from_xml(b'\xef\xbb\xbf' + data).description, UNICODE)
            self.assertEqual(parsed.as_dict()['description'], UNICODE)
        for bad in ('multi\nline', '\x01', '\ud800', '￿'):
            with self.assertRaises(UnitTemplateError):
                UnitTemplate(synthetic(), bad)
        # Attribute text remains ASCII-only.
        with self.assertRaises(UnitTemplateError):
            UnitTemplate(synthetic(UnitName='É'))


@unittest.skipUnless(SPECS, 'set CBUS_UNITSPEC_DIR for NeoPro specification checks')
class NeoTemplateSpecTests(unittest.TestCase):
    def test_every_profile_builds_default_template_and_rejects_foreign_catalogues(self):
        store = UnitSpecStore(SPECS)
        for unit_type, profile in NEO_PROFILES.items():
            with self.subTest(unit_type=unit_type):
                spec = store.load(profile[3])
                templates = UnitTemplates(spec)
                template = templates.from_values(spec.defaults(), description=UNICODE)
                self.assertEqual(template.profile, profile)
                self.assertEqual(UnitTemplate.from_xml(template.to_xml()).attributes, template.attributes)
                for catalog in NEO_CATALOGS[unit_type]:
                    self.assertEqual(UnitTemplates(spec, catalog_number=catalog).profile[2], catalog)
                with self.assertRaises(UnitTemplateError):
                    UnitTemplates(spec, catalog_number='5034N')
                with self.assertRaises(UnitTemplateError):
                    UnitTemplates(spec, firmware='1.2.67')

    def test_classic_database_transaction_refuses_neopro_templates(self):
        from cbus_toolkit.template_transaction import NativeTemplateTransaction
        spec = UnitSpecStore(SPECS).load('KEYM4.xml')
        with self.assertRaisesRegex(ValueError, 'classic'):
            NativeTemplateTransaction(object(), UnitTemplates(spec), '//TEST/254')


def _changed(spec, name, seed):
    """Deterministic valid value that differs from the specification default."""
    parameter = spec.parameters[name]
    default = spec.defaults()[name]
    low = int(parameter.fields.get('MinValue', '0').replace('$', '0x'), 0) if parameter.fields.get('MinValue', '').strip() else 0
    high = (int(parameter.fields['MaxValue'].replace('$', '0x'), 0) if parameter.fields.get('MaxValue', '').strip()
            else (1 << parameter.bit_size) - 1)
    if parameter.type == 'bit':
        low, high = max(low, 0), min(high, 1)
    span = high - low + 1
    values = [low + (seed * 7 + index * 3 + len(name)) % span for index in range(parameter.array_size)]
    text = ' '.join(map(str, values))
    if text.split() == [str(int(str(token).replace('$', '0x'), 0)) for token in str(default).split()]:
        values[0] = low + (values[0] - low + 1) % span
        text = ' '.join(map(str, values))
    return text


@unittest.skipUnless(os.environ.get('CBUS_CGATE_JAVA') and SPECS and VENDOR,
                     'set CBUS_CGATE_JAVA, CBUS_LOCAL_CGATE_VENDOR and CBUS_UNITSPEC_DIR for native Neo templates')
class NeoTemplateNativeTests(unittest.TestCase):
    def test_every_profile_roundtrips_through_native_database_units(self):
        from cbus_toolkit.cgate import CGateError
        from cbus_toolkit.native import NativeDatabase, NativeProjects
        from cbus_toolkit.programming import Programmer
        from research.convertunit_pairs import owned_backend
        specs, catalog = Path(SPECS), Path(VENDOR) / 'unitspec/cbusunits.xml'
        store = UnitSpecStore(SPECS)
        report = {'format': 'cbus-neo-unit-template-native-v1', 'profiles': []}
        with owned_backend('native', spec_dir=specs, catalog_path=catalog, table_path=None, vendor=VENDOR,
                           java=os.environ['CBUS_CGATE_JAVA']) as (client, backend):
            report['backend'] = backend
            project = 'NT' + uuid4().hex[:6].upper()
            network = f'//{project}/254'
            projects, database, programmer = NativeProjects(client), NativeDatabase(client), Programmer(client)
            projects.operation('new', project)
            projects.operation('use', project)
            client.command('DBCREATENET 254 NeoTemplates Cni 127.0.0.1:29999')
            client.command('NET LOAD DB')
            try:
                identity_names = ('UnitAddress', 'Project', 'SerialNo', 'LearnedFlag', 'CUSTYPE', 'HardwareConfiguration')
                finals = {}
                for index, (unit_type, profile) in enumerate(sorted(NEO_PROFILES.items())):
                    with self.subTest(unit_type=unit_type):
                        spec = store.load(profile[3])
                        templates = UnitTemplates(spec)
                        source, target = 2 * index + 10, 2 * index + 11
                        for address in (source, target):
                            database.create_unit(network, address, f'{unit_type}_{address}', unit_type, profile[1],
                                                 catalog_number=profile[2])
                        chosen = {name: _changed(spec, name, index + 1) for name in templates.parameters
                                  if name != 'UnitName'}
                        chosen['UnitName'] = 'N<&"' + str(index)
                        with programmer.load(network, f'/db{network}/p/{source}') as session:
                            for name, value in chosen.items():
                                session.set(name, value)
                            template = templates.export(session, description=UNICODE)
                            session.save_to_source()
                        parsed = UnitTemplate.from_xml(template.to_xml().encode('utf-8'))
                        self.assertEqual(parsed.description, UNICODE)
                        changed_from_default = sorted(name for name in templates.parameters
                                                      if parsed.attributes[name] != templates.from_values(spec.defaults()).attributes[name])
                        with programmer.load(network, f'/db{network}/p/{target}') as session:
                            before = session.values()
                            result = templates.apply(session, parsed)
                            self.assertTrue(result['verified'])
                            session.save_to_source()
                        with programmer.load(network, f'/db{network}/p/{target}') as session:
                            after = session.values()
                            self.assertEqual(templates.export(session).attributes, parsed.attributes)
                        for name in identity_names:
                            if name in before:
                                self.assertEqual(after[name], before[name], name)
                        finals[target] = (templates, parsed.attributes)
                        report['profiles'].append({'unit_type': unit_type, 'catalog_number': profile[2],
                                                   'firmware': profile[1], 'parameters': len(templates.parameters),
                                                   'changed_from_default': len(changed_from_default),
                                                   'crc': parsed.crc, 'passed': True})
                projects.operation('save', project)
                projects.operation('close', project)
                projects.operation('load', project)
                projects.operation('use', project)
                client.command('NET LOAD DB')
                for target, (templates, attributes) in finals.items():
                    with programmer.load(network, f'/db{network}/p/{target}') as session:
                        self.assertEqual(templates.export(session).attributes, attributes)
                report['project_reload_cases'] = len(finals)
            finally:
                for action in ('close', 'delete'):
                    try:
                        projects.operation(action, project)
                    except (CGateError, RuntimeError, OSError):
                        pass
        report['passed'] = len(report['profiles']) == len(NEO_PROFILES)
        if os.environ.get('CBUS_NEO_TEMPLATE_REPORT'):
            Path(os.environ['CBUS_NEO_TEMPLATE_REPORT']).write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
        self.assertTrue(report['passed'])


if __name__ == '__main__':
    unittest.main()
