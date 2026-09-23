"""Original-vector tests for cached Toolkit database CSV projection."""
from dataclasses import replace
import json
import unittest

from cbus_toolkit.toolkit_database_csv import COLUMNS
from cbus_toolkit.toolkit_database_csv_projection import (
    CSVAreaObservation,
    CSVGroupSaveObservation,
    PROFILE,
    CachedCSVGroup,
    CachedCSVUnit,
    loads_cached_projection,
    parse_cached_projection,
    project_cached_csv_unit,
)


HEADER = ('Unit Address,Part Name,Tag Name,Unit Type,Catalog Number,Serial Number,'
          'Firmware Version,Primary Application,Secondary Application,Area,'
          + ''.join('Group ' + str(number) + ',' for number in range(1, 17)))


def row(unit_type, firmware, area, interactions):
    return ('4,Owned part,Owned unit,' + unit_type + ',OWNED,No serial #,' + firmware
            + ',Lighting,Secondary,' + area + ','
            + ''.join('G' + str(number) + ',' for number in range(1, interactions + 1))
            + '<N/A>,' * (16 - interactions))


def group(address):
    return CachedCSVGroup('group-' + str(address), address,
                          '<Unused>' if address == 255 else
                          ('Area' + str(address) if address in (12, 13) else 'G' + str(address)),
                          'OID-group-' + str(address))


def fixture(unit_type='RELAY4', firmware='4.4', *, unused=True):
    addresses = [1, 2, 3, 4, 5, 6, 7, 8, 12, 13] + ([255] if unused else [])
    groups = tuple(group(address) for address in addresses)
    unit = CachedCSVUnit('unit', 4, 'Owned part', 'Owned unit', unit_type, 'OWNED', '',
                         firmware, 'Lighting', 'Secondary',
                         tuple('group-' + str(address) for address in range(1, 9)))
    return unit, groups


def projection_input(unit_type='RELAY4', firmware='4.4', *, unused=True,
                     observations=('12', '12'), save=None):
    unit, groups = fixture(unit_type, firmware, unused=unused)
    return {'format': PROFILE, 'unit': unit.as_dict(),
            'group_cache': [group.as_dict() for group in groups],
            'area_observations': [{'raw': raw, 'completed': True}
                                  for raw in observations],
            'group_save': None if save is None else {'completed': save}}


class CachedCSVProjectionTests(unittest.TestCase):
    def test_all_twelve_original_cases(self):
        cases = (
            ('unknown-generic', 'OWNED_UNKNOWN', '4.4', ('12', '12'), True, None,
             COLUMNS, 'TCBusUnitGeneric', '<Unused>', 8, True, 0, 0),
            ('relay-existing', 'RELAY4', '4.4', ('12', '12'), True, None,
             COLUMNS, 'TRELAY4', 'Area12', 6, True, 2, 0),
            ('relay-lowercase-lower-bound', 'relay4', '0', ('12', '12'), True, None,
             COLUMNS, 'TRELAY4', 'Area12', 6, True, 2, 0),
            ('relay-upper-bound', 'RELAY4', '9', ('12', '12'), True, None,
             COLUMNS, 'TRELAY4', 'Area12', 6, True, 2, 0),
            ('relay-outside-upper', 'RELAY4', '10', ('12', '12'), True, None,
             COLUMNS, 'TCBusUnitGeneric', '<Unused>', 8, True, 0, 0),
            ('relay-dotted-outside-upper', 'RELAY4', '9.1', ('12', '12'), True, None,
             COLUMNS, 'TCBusUnitGeneric', '<Unused>', 8, True, 0, 0),
            ('relay-storage-changes-between-getters', 'RELAY4', '4.4', ('12', '13'), True, None,
             COLUMNS, 'TRELAY4', 'Area13', 6, True, 2, 0),
            ('relay-invalid-area-falls-back', 'RELAY4', '4.4', ('invalid', 'invalid'), True, None,
             COLUMNS, 'TRELAY4', '<Unused>', 6, True, 2, 0),
            ('relay-create-unused', 'RELAY4', '4.4', ('255', '255'), False, True,
             COLUMNS, 'TRELAY4', '<Unused>', 6, True, 2, 1),
            ('relay-save-denied-after-create', 'RELAY4', '4.4', ('255', '255'), False, False,
             COLUMNS, 'TRELAY4', None, 0, False, 1, 1),
            ('relay-area-column-omitted', 'RELAY4', '4.4', ('12', '12'), True, None,
             ('address',), 'TRELAY4', None, 0, True, 2, 0),
            ('relay-load-denied', 'RELAY4', '4.4', ('12', '12'), True, None,
             COLUMNS, 'TRELAY4', None, 0, False, 1, 0),
        )
        for (name, unit_type, firmware, observations, unused, save, columns, selected,
             area, interactions, complete, loads, saves) in cases:
            with self.subTest(name=name):
                unit, groups = fixture(unit_type, firmware, unused=unused)
                values = tuple(CSVAreaObservation(raw, not(name == 'relay-load-denied' and index == 0))
                               for index, raw in enumerate(observations))
                outcome = project_cached_csv_unit(unit, group_cache=groups,
                    area_observations=values,
                    group_save=None if save is None else CSVGroupSaveObservation(save),
                    columns=columns)
                self.assertEqual(outcome.selected_class, selected)
                self.assertEqual(outcome.complete, complete)
                events = [event.as_dict() for event in outcome.events]
                self.assertEqual(sum(event['event'] == 'area_load' for event in events), loads)
                self.assertEqual(sum(event['event'] == 'group_save' for event in events), saves)
                if complete:
                    expected = ('4,' if columns == ('address',) else
                                row(unit_type, firmware, area, interactions))
                    self.assertEqual(outcome.rows,
                                     ('Unit Address,', expected) if columns == ('address',)
                                     else (HEADER, expected))
                else:
                    self.assertEqual(outcome.rows, (HEADER,))
        self.assertEqual(len(cases), 12)

    def test_keye_preserves_repeated_unused_slots_and_eight_interaction_groups(self):
        groups = tuple(group(address) for address in (1, 2, 255))
        unit = CachedCSVUnit('keye-unit', 15, 'Neo Pro', 'Ensuite', 'KEYE2',
            '5031NMML', '101136.1558', '2.5.00', 'Lighting', '',
            ('group-1', 'group-2', *('group-255' for _ in range(7))))
        outcome = project_cached_csv_unit(unit, group_cache=groups,
            area_observations=(CSVAreaObservation('255'), CSVAreaObservation('255')),
            columns=COLUMNS)
        self.assertTrue(outcome.complete)
        self.assertEqual(outcome.selected_class, 'TKEYEx')
        self.assertEqual(outcome.area_identity, 'group-255')
        self.assertEqual(outcome.unit.group_identities.count('group-255'), 7)
        self.assertEqual(outcome.groups[-1].references, ('keye-unit',))
        fields = outcome.report.rows[1].split(',')
        self.assertEqual(fields[9:18],
            ['<Unused>', 'G1', 'G2', *('<Unused>' for _ in range(6))])
        self.assertEqual(fields[18:26], ['<N/A>'] * 8)

    def test_din_profiles_keep_configured_noninteraction_slots_unavailable(self):
        groups = tuple(group(address) for address in (*range(20, 33), 255))
        identities = tuple('group-' + str(address)
                           for address in (*range(20, 33), 255, 255, 255))
        for unit_type, selected_class, interactions in (
                ('DIMDN8', 'TDIMDN8', 8), ('RELDN12', 'TRELDN12', 12)):
            with self.subTest(unit_type=unit_type):
                unit = CachedCSVUnit('din-' + unit_type, 3, 'DIN part', 'DIN unit',
                    unit_type, 'DIN-CATALOG', '', '2.7.00', 'Lighting', '', identities)
                outcome = project_cached_csv_unit(unit, group_cache=groups,
                    area_observations=(CSVAreaObservation('255'), CSVAreaObservation('255')),
                    columns=COLUMNS)
                self.assertEqual(outcome.selected_class, selected_class)
                fields = outcome.report.rows[1].split(',')
                self.assertEqual(fields[10:10 + interactions],
                                 ['G' + str(index) for index in range(20, 20 + interactions)])
                self.assertEqual(fields[10 + interactions:26],
                                 ['<N/A>'] * (16 - interactions))

    def test_senpiroa_profile_keeps_eight_ordered_interaction_slots(self):
        addresses = (1, 0, 4, 2, 255, 255, 255, 255)
        groups = tuple(group(address) for address in (0, 1, 2, 4, 255))
        identities = tuple('group-' + str(address) for address in addresses)
        unit = CachedCSVUnit('sensor-senpiroa', 35, 'Sensor part', 'Sensor unit',
            'SENPIROA', '5750WPL', '', '2.4.00', 'Lighting', '', identities)
        outcome = project_cached_csv_unit(unit, group_cache=groups,
            area_observations=(CSVAreaObservation('255'), CSVAreaObservation('255')),
            columns=COLUMNS)
        self.assertEqual(outcome.selected_class, 'TST7SENPIROA')
        fields = outcome.report.rows[1].split(',')
        self.assertEqual(fields[10:18],
                         ['G1', 'G0', 'G4', 'G2', '<Unused>', '<Unused>',
                          '<Unused>', '<Unused>'])
        self.assertEqual(fields[18:26], ['<N/A>'] * 8)

    def test_same_address_groups_from_two_applications_resolve_by_identity(self):
        groups = (
            CachedCSVGroup('primary-255', 255, '<Unused>', 'OID-primary-255'),
            CachedCSVGroup('secondary-255', 255, 'Secondary unused', 'OID-secondary-255'),
        )
        unit = CachedCSVUnit('keye-secondary', 15, 'Neo Pro', 'Secondary groups',
            'KEYE1', '5031NMML', '', '2.5.00', 'Lighting', 'HVAC',
            ('secondary-255',) * 8 + ('primary-255',))
        outcome = project_cached_csv_unit(unit, group_cache=groups,
            area_observations=(CSVAreaObservation('255'), CSVAreaObservation('255')),
            columns=COLUMNS)
        fields = outcome.report.rows[1].split(',')
        self.assertEqual(fields[8:18],
                         ['HVAC', '<Unused>'] + ['Secondary unused'] * 8)
        self.assertEqual(outcome.area_identity, 'primary-255')

    def test_reference_moves_between_groups_and_retains_identity(self):
        unit, groups = fixture()
        outcome = project_cached_csv_unit(unit, group_cache=groups,
            area_observations=(CSVAreaObservation('12'), CSVAreaObservation('13')),
            columns=COLUMNS)
        by_address = {group.address: group for group in outcome.groups}
        self.assertEqual(by_address[12].references, ())
        self.assertEqual(by_address[13].references, ('unit',))
        self.assertEqual(outcome.area_identity, 'group-13')
        self.assertEqual([event.as_dict()['previous'] for event in outcome.events
                          if event.event == 'area_reference'], [None, 'group-12'])

    def test_missing_unused_group_success_and_denied_save_partial(self):
        unit, groups = fixture(unused=False)
        complete = project_cached_csv_unit(unit, group_cache=groups,
            area_observations=(CSVAreaObservation('255'), CSVAreaObservation('255')),
            group_save=CSVGroupSaveObservation(True), columns=COLUMNS)
        created = complete.groups[-1]
        self.assertEqual((created.identity, created.address, created.tag, created.oid,
                          created.references),
                         ('created-255', 255, '<Unused>', 'OID-created-255', ('unit',)))
        partial = project_cached_csv_unit(unit, group_cache=groups,
            area_observations=(CSVAreaObservation('255'), CSVAreaObservation('255')),
            group_save=CSVGroupSaveObservation(False), columns=COLUMNS)
        self.assertFalse(partial.complete)
        self.assertEqual(partial.stop_reason, 'group_save_failed')
        self.assertEqual(partial.groups[-1].references, ())
        self.assertIsNone(partial.area_identity)

    def test_validation_is_strict_and_inputs_are_immutable(self):
        unit, groups = fixture()
        before = repr((unit, groups))
        changes = (
            {'unit': replace(unit, unit_type='KEY4')},
            {'unit': replace(unit, firmware='4.5')},
            {'group_cache': groups + (replace(groups[0], identity='duplicate', address=2),)},
            {'group_cache': groups[1:]},
            {'area_observations': (CSVAreaObservation('12'),)},
            {'group_save': CSVGroupSaveObservation(True)},
        )
        for change in changes:
            with self.subTest(change=change):
                arguments = {'unit': unit, 'group_cache': groups,
                             'area_observations': (CSVAreaObservation('12'), CSVAreaObservation('12')),
                             'group_save': None, 'columns': COLUMNS}
                arguments.update(change)
                with self.assertRaises(ValueError):
                    project_cached_csv_unit(**arguments)
        self.assertEqual(repr((unit, groups)), before)

    def test_strict_json_loader_projects_detached_cached_records(self):
        source = projection_input()
        outcome = loads_cached_projection(json.dumps(source).encode(), columns=('area', 'address'))
        self.assertTrue(outcome.complete)
        self.assertEqual(outcome.columns, ('address', 'area'))
        self.assertEqual(outcome.rows, ('Unit Address,Area,', '4,Area12,'))
        source['unit']['tag_name'] = 'changed after projection'
        self.assertEqual(outcome.unit.tag_name, 'Owned unit')

    def test_cached_json_schema_rejects_ambiguity_and_unconsumed_outcomes(self):
        source = projection_input()
        invalid = []
        for mutate in (
            lambda value: value.update(extra=True),
            lambda value: value['unit'].update(extra=True),
            lambda value: value['group_cache'][0].update(extra=True),
            lambda value: value.update(group_save={'completed': True}),
        ):
            candidate = json.loads(json.dumps(source)); mutate(candidate); invalid.append(candidate)
        for candidate in invalid:
            with self.subTest(candidate=candidate):
                with self.assertRaises(ValueError):
                    parse_cached_projection(candidate, columns=COLUMNS)
        with self.assertRaises(ValueError):
            loads_cached_projection(b'{"format":"x","format":"y"}', columns=COLUMNS)
        with self.assertRaises(ValueError):
            loads_cached_projection(b'{"format":1.5}', columns=COLUMNS)


if __name__ == '__main__':
    unittest.main()
