"""Ordered original choice lists and strict cache-presence contracts."""
from dataclasses import replace
import json
from pathlib import Path
import unittest

from cbus_toolkit.edlt import EdltError
from cbus_toolkit.edlt_lifecycle import LifecycleCache, LifecycleGroup, LifecycleMetadataError
from cbus_toolkit.edlt_application_cache import ApplicationCache, CachedDisplay, CachedGroupList


def display(address, name='Same name'):
    return CachedDisplay(address, name, f'{address:03d} - {name}')


class ApplicationCacheTests(unittest.TestCase):
    def fixture(self):
        facts = LifecycleCache((136, 56, 57, 202, 203), (LifecycleGroup(56, 42, True), LifecycleGroup(56, 99, False)))
        return ApplicationCache(facts, True, tuple(display(a) for a in facts.applications),
            (CachedGroupList(56, True, tuple(display(g) for g in (42, 255, 12, 0))),))

    def test_original_windows_lists_keep_order_names_and_exclusions(self):
        root = Path(__file__).resolve().parents[1]
        document = json.loads((root / 'research/fixtures/edlt-application-list-windows-vectors.json').read_text())
        self.assertEqual(len(document['cases']), 12)
        count = 0
        for case in document['cases']:
            apps = tuple(CachedDisplay.from_dict(row) for row in case['applications'])
            cache = ApplicationCache(LifecycleCache(tuple(a.address for a in apps), ()), True, apps, ())
            for stage, observation in case['stages'].items():
                with self.subTest(case=case['case'], stage=stage):
                    choices = cache.application_choices(primary=observation['PrimaryApplication'], secondary=observation['SecondaryApplication'])
                    for role in ('primary', 'secondary'):
                        self.assertEqual([{'address': a.address, 'formatted_display': a.formatted_display} for a in choices[role]],
                                         observation['list-' + role])
                    count += 1
        self.assertEqual(count, 48)

    def test_all_address_boundaries_duplicate_names_and_unused_placeholder(self):
        addresses = tuple(reversed(range(256)))
        cache = ApplicationCache(LifecycleCache(addresses, ()), True, tuple(display(a) for a in addresses), ())
        wanted = [136, *range(127, 47, -1)]
        for primary, secondary in ((56, 57), (255, 255), (136, 127), (56, 56)):
            choices = cache.application_choices(primary=primary, secondary=secondary)
            self.assertEqual([a.address for a in choices['primary']], [a for a in wanted if a != secondary])
            self.assertEqual([a.address for a in choices['secondary']], [255] + [a for a in wanted if a != primary])
            self.assertEqual(choices['secondary'][0].formatted_display, '<Unused>')

    def test_group_list_exclusion_does_not_change_presence_or_stored_identity(self):
        cache = self.fixture()
        choices = cache.group_choices(56, exclude=(42, 255), placeholder='<Disabled>')
        self.assertEqual([g.address for g in choices], [255, 12, 0])
        self.assertEqual(choices[0].name, '<Disabled>')
        self.assertTrue(cache.group_presence(56, 42)); self.assertFalse(cache.group_presence(56, 99))
        self.assertIsNone(cache.group_presence(57, 42))
        self.assertEqual([g.address for g in cache.find_group_list(56).groups], [42, 255, 12, 0])

    def test_incomplete_lists_are_not_complete_empty_lists(self):
        cache = replace(self.fixture(), applications_complete=False)
        with self.assertRaises(LifecycleMetadataError): cache.application_choices(primary=56, secondary=57)
        row = replace(cache.group_lists[0], complete=False)
        cache = replace(cache, group_lists=(row,))
        self.assertTrue(cache.group_presence(56, 42)); self.assertFalse(cache.group_presence(56, 99))
        self.assertIsNone(cache.group_presence(56, 98))
        with self.assertRaises(LifecycleMetadataError): cache.group_choices(56)
        with self.assertRaises(LifecycleMetadataError): cache.group_choices(57)

    def test_roundtrip_is_immutable_and_rejects_conflicting_identity_facts(self):
        cache = self.fixture(); document = cache.as_dict()
        self.assertEqual(ApplicationCache.from_dict(document), cache)
        document['applications'][0]['name'] = 'Changed external dict'
        self.assertEqual(cache.applications[0].name, 'Same name')
        bads = [dict(applications=cache.applications * 2), dict(applications_complete=1),
                dict(applications=cache.applications[:-1]), dict(group_lists=cache.group_lists * 2),
                dict(group_lists=(CachedGroupList(56, True, (display(99), display(42))),)),
                dict(group_lists=(CachedGroupList(56, True, (display(12),)),))]
        for changes in bads:
            with self.assertRaises(EdltError): replace(cache, **changes)
        for bad in ({**cache.as_dict(), 'unknown': True},
                    {**cache.as_dict(), 'applications': [{'address': True, 'name': 'x', 'formatted_display': 'x'}]},
                    {**cache.as_dict(), 'group_lists': [{'application': 56, 'complete': True, 'groups': 'bad'}]}):
            with self.assertRaises(EdltError): ApplicationCache.from_dict(bad)
        for options in ({'primary': True, 'secondary': 57}, {'primary': 56, 'secondary': 256}):
            with self.assertRaises(EdltError): cache.application_choices(**options)


if __name__ == '__main__': unittest.main()
