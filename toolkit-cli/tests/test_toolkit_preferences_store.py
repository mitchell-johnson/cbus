from dataclasses import asdict
import json
from pathlib import Path
import struct
import unittest

from cbus_toolkit.toolkit_preferences_store import (
    CGATE_KEY, DISPLAY_DEFINITIONS, DISPLAY_KEY, HKCU, HKLM,
    PREFERENCE_DEFINITIONS, REG_DWORD, REG_SZ, TOOLKIT_KEY,
    RegistryValue, ToolkitPreferencesStore, UnsupportedPreferenceEncoding,
    validate_values,
)

FIXTURE = Path(__file__).resolve().parents[1] / 'research/fixtures/toolkit-preferences-store-vectors.json'


def fixture():
    return json.loads(FIXTURE.read_text())


def values():
    return fixture()['initial_values']


def display():
    return dict.fromkeys((name for name, _ in DISPLAY_DEFINITIONS), False)


def text(value):
    return RegistryValue(REG_SZ, (value + '\0').encode('utf-16-le'))


class Registry:
    """Independent byte store: no production serializer or parser is reused."""
    def __init__(self):
        self.data = {}
        self.calls = []
        self.fault = None
        self.default_code = 0

    def check(self, row):
        self.calls.append(row)
        if self.fault:
            self.fault(row)

    def read_value(self, hive, key, name):
        self.check(('read', hive, key, name))
        try:
            return self.data[hive, key, name]
        except KeyError:
            raise FileNotFoundError(name) from None

    def write_value(self, hive, key, name, value):
        self.check(('write', hive, key, name, value))
        self.data[hive, key, name] = value

    def write_default_string(self, hive, key, value):
        self.check(('default', hive, key, '', value))
        if not self.default_code:
            self.data[hive, key, ''] = text(value)
        return self.default_code


def seeded():
    result = Registry()
    for spec in PREFERENCE_DEFINITIONS:
        value = values()[spec.name]
        raw = 'True' if value is True else 'False' if value is False else str(value)
        result.data[HKLM if spec.machine_first else HKCU, spec.key, spec.name] = text(raw)
    for _, name in DISPLAY_DEFINITIONS:
        result.data[HKCU, DISPLAY_KEY, name] = RegistryValue(REG_DWORD, b'\0'*4)
    return result


class PreferenceStoreTests(unittest.TestCase):
    def test_original_schema_and_table_order_are_exact(self):
        expected = fixture()['schema']['rows']
        self.assertEqual(len(PREFERENCE_DEFINITIONS), 40)
        self.assertEqual([asdict(spec) for spec in PREFERENCE_DEFINITIONS],
                         [{key: row[key] for key in ('name', 'kind', 'machine_first', 'skip_save', 'alternate_key', 'boolean_default')} for row in expected])
        self.assertEqual([spec.name for spec in PREFERENCE_DEFINITIONS[:4]], ['LoadChangePortDisable', 'ApplicationLogDisable', 'TemperatureUnit', 'DoNotPauseEventsWhileLoadingProject'])
        self.assertEqual([spec.name for spec in PREFERENCE_DEFINITIONS[-8:]], [f'Default Language {index}' for index in range(1, 9)])
        self.assertEqual([row['ordinal'] for row in fixture()['original_registration_order']], [388, 614, 682])

    def test_input_validation_detaches_and_precedes_every_backend_call(self):
        original = values()
        detached = validate_values(original)
        detached['TemperatureUnit'] = 7
        self.assertEqual(original['TemperatureUnit'], 0)
        invalid = []
        missing = dict(original); del missing['FeedbackLog']; invalid.append(missing)
        extra = dict(original, Unknown=True); invalid.append(extra)
        for name, value in [('FeedbackLog', 1), ('TemperatureUnit', True), ('TemperatureUnit', 2**31), ('Default Site', 'a\0b'), ('Default Site', '\ud800'), ('Default Site', 'a'*4097)]:
            item = dict(original); item[name] = value; invalid.append(item)
        for item in invalid:
            registry = Registry(); store = ToolkitPreferencesStore(registry)
            with self.assertRaises((ValueError, TypeError)):
                store.save(item, display())
            self.assertEqual(registry.calls, [])
        registry = Registry()
        with self.assertRaises(ValueError):
            ToolkitPreferencesStore(registry).save(original, dict(display(), tag_hex=256))
        self.assertEqual(registry.calls, [])

    def test_save_matches_original_35_literal_bytes_and_order_after_display(self):
        registry = Registry(); original = fixture(); source = original['second_load_values']
        registry.data[HKCU, TOOLKIT_KEY, 'unrelated'] = RegistryValue(3, b'unchanged')
        outcome = ToolkitPreferencesStore(registry).save(source, display())
        self.assertTrue(outcome.complete)
        named = [row for row in registry.calls if row[0] == 'write' and row[2] != DISPLAY_KEY]
        self.assertEqual([(row[1], row[2], row[3], row[4].win32_type, row[4].data.hex()) for row in named],
                         [(int(row['hive'], 16), row['key'].strip('\\'), row['name'], 1, row['utf16le_hex']) for row in original['original_named_save']])
        self.assertEqual(len(named), 35)
        self.assertEqual([row[3] for row in registry.calls[:5]], [name for _, name in DISPLAY_DEFINITIONS])
        self.assertEqual(registry.calls[5:7], [('default', HKCU, TOOLKIT_KEY, '', ''), ('default', HKCU, CGATE_KEY, '', '')])
        self.assertEqual(registry.data[HKCU, TOOLKIT_KEY, 'unrelated'], RegistryValue(3, b'unchanged'))
        self.assertEqual(len(registry.calls), 43)
        self.assertFalse(outcome.as_dict()['transactional'])

    def test_original_empty_store_two_loads_preserve_first_default_asymmetry(self):
        registry = Registry(); store = ToolkitPreferencesStore(registry)
        first = store.load(values())
        self.assertTrue(first.complete)
        self.assertFalse(first.fully_observed)
        self.assertEqual(dict(first.values), fixture()['first_load_values'])
        self.assertFalse(first.values['ShowProjectManager'])
        self.assertEqual(registry.data[HKCU, TOOLKIT_KEY, 'ShowProjectManager'], text('True'))
        self.assertIn((HKCU, TOOLKIT_KEY, 'ShowDatabaseLabelsOption'), registry.data)
        self.assertNotIn((HKCU, TOOLKIT_KEY, 'FeedbackLogSize'), registry.data)
        self.assertTrue(first.as_dict()['default_writes'])
        second = store.load(first.values)
        self.assertEqual(dict(second.values), fixture()['second_load_values'])
        self.assertTrue(second.values['ShowProjectManager'])

    def test_all_present_values_and_raw_display_dwords(self):
        registry = seeded()
        registry.data[HKCU, TOOLKIT_KEY, 'Default Site'] = text('  Māori  ')
        registry.data[HKCU, TOOLKIT_KEY, 'LoadChangePortDisable'] = text('tRuE')
        registry.data[HKCU, TOOLKIT_KEY, 'ApplicationLogDisable'] = text('1')
        for index, (_, name) in enumerate(DISPLAY_DEFINITIONS):
            registry.data[HKCU, DISPLAY_KEY, name] = RegistryValue(REG_DWORD, struct.pack('<I', [0, 1, 2, 0x80000000, 0xffffffff][index]))
        outcome = ToolkitPreferencesStore(registry).load(values())
        self.assertTrue(outcome.complete)
        self.assertTrue(outcome.fully_observed)
        self.assertEqual(outcome.values['Default Site'], '  Māori  ')
        self.assertTrue(outcome.values['LoadChangePortDisable'])
        self.assertFalse(outcome.values['ApplicationLogDisable'])
        self.assertEqual(list(outcome.display_values.values()), [False, True, True, True, True])
        self.assertEqual([row[0] for row in registry.calls[:2]], ['default', 'default'])
        self.assertFalse(any(row[0] == 'write' for row in registry.calls))

    def test_read_hive_precedence_copy_and_write_fallback_are_single_attempts(self):
        registry = seeded(); name = 'FeedbackLogSize'
        del registry.data[HKLM, TOOLKIT_KEY, name]
        registry.data[HKCU, TOOLKIT_KEY, name] = text('99')
        del registry.data[HKCU, CGATE_KEY, 'JavaHeapMin']
        registry.data[HKLM, CGATE_KEY, 'JavaHeapMin'] = text('32')
        store = ToolkitPreferencesStore(registry); loaded = store.load(values())
        self.assertTrue(loaded.complete)
        self.assertEqual(loaded.values[name], 99)
        self.assertEqual(registry.data[HKCU, CGATE_KEY, 'JavaHeapMin'], text('32'))
        registry.calls.clear()
        def deny(row):
            if row[:4] == ('write', HKLM, TOOLKIT_KEY, name):
                raise PermissionError('fixture machine write denied')
        registry.fault = deny
        saved = store.save(loaded.values, display())
        self.assertTrue(saved.complete)
        attempts = [row for row in registry.calls if row[0] == 'write' and row[3] == name]
        self.assertEqual([row[1] for row in attempts], [HKLM, HKCU])
        self.assertEqual(registry.data[HKCU, TOOLKIT_KEY, name], text('99'))
        self.assertFalse(saved.fully_observed)

    def test_unsupported_numeric_or_raw_encoding_stops_without_copying(self):
        bad = [text('6A4'), text('64.5'), text('+64'), text('00'), text('-0'), text('2147483648'), RegistryValue(REG_DWORD, b'\0'*4), RegistryValue(REG_SZ, b'1\0'), RegistryValue(REG_SZ, b'1'), text('1\0junk'), RegistryValue(REG_SZ, b'\x00\xd8\0\0')]
        for raw in bad:
            registry = seeded(); name = 'TemperatureUnit'
            del registry.data[HKCU, TOOLKIT_KEY, name]
            registry.data[HKLM, TOOLKIT_KEY, name] = raw
            store = ToolkitPreferencesStore(registry); outcome = store.load(values())
            self.assertFalse(outcome.complete)
            self.assertIsInstance(store.last_error, UnsupportedPreferenceEncoding)
            self.assertNotIn((HKCU, TOOLKIT_KEY, name), registry.data)
            self.assertFalse(any(row[0] == 'write' for row in registry.calls))
            self.assertEqual(outcome.values[name], values()[name])

    def test_display_write_uses_original_seven_bit_mask_and_signed_integer_bytes(self):
        registry = Registry(); raw = dict(zip((key for key, _ in DISPLAY_DEFINITIONS), [0, 1, 127, 128, 255]))
        source = values(); source['TemperatureUnit'] = -(2**31)
        outcome = ToolkitPreferencesStore(registry).save(source, raw)
        self.assertTrue(outcome.complete)
        self.assertEqual([registry.data[HKCU, DISPLAY_KEY, name].data for _, name in DISPLAY_DEFINITIONS], [struct.pack('<I', value) for value in [0, 1, 127, 0, 127]])
        self.assertEqual(registry.data[HKCU, TOOLKIT_KEY, 'TemperatureUnit'].data, b'-\x002\x001\x004\x007\x004\x008\x003\x006\x004\x008\x00\x00\x00')

    def test_default_failure_is_ignored_by_original_algorithm_but_not_hidden(self):
        registry = Registry(); registry.default_code = 5
        outcome = ToolkitPreferencesStore(registry).save(values(), display())
        self.assertTrue(outcome.algorithm_completed)
        self.assertFalse(outcome.complete)
        self.assertEqual(len(outcome.issues), 3)
        self.assertEqual(len([row for row in registry.calls if row[0] == 'write']), 40)
        self.assertEqual([row['return_code'] for row in outcome.as_dict()['default_writes']], [5, 5, 5])

    def test_definite_write_failure_preserves_prefix_without_retry_or_rollback(self):
        registry = Registry(); original_error = OSError('failed named write')
        def fail(row):
            if row[0] == 'write' and row[3] == 'TemperatureUnit':
                raise original_error
        registry.fault = fail; store = ToolkitPreferencesStore(registry)
        outcome = store.save(values(), display())
        self.assertFalse(outcome.complete)
        self.assertFalse(outcome.algorithm_completed)
        self.assertIs(store.last_error, original_error)
        self.assertEqual(registry.calls[-1][3], 'TemperatureUnit')
        self.assertIn((HKCU, TOOLKIT_KEY, 'ApplicationLogDisable'), registry.data)
        self.assertNotIn((HKCU, TOOLKIT_KEY, 'TemperatureUnit'), registry.data)
        self.assertFalse(outcome.operations[-1]['completed'])
        self.assertEqual(original_error.toolkit_preferences_evidence, store.last_evidence)

    def test_interruption_identity_evidence_and_reuse_preflight_reset(self):
        class Interrupted(KeyboardInterrupt):
            def __setattr__(self, name, value):
                raise SystemExit('attachment rejected')
            def __str__(self):
                raise SystemExit('rendering rejected')
        registry = Registry(); error = Interrupted()
        def stop(row):
            if row[0] == 'write' and row[3] == 'TemperatureUnit':
                raise error
        registry.fault = stop; store = ToolkitPreferencesStore(registry)
        with self.assertRaises(Interrupted) as caught:
            store.save(values(), display())
        self.assertIs(caught.exception, error)
        self.assertIs(store.last_error, error)
        self.assertFalse(store.last_evidence['complete'])
        self.assertEqual(store.last_evidence['error']['message'], 'exception message unavailable')
        before = list(registry.calls)
        with self.assertRaises(ValueError):
            store.load({})
        self.assertIsNone(store.last_evidence)
        self.assertIsNone(store.last_error)
        self.assertEqual(registry.calls, before)

    def test_outcome_exports_do_not_alias_immutable_state(self):
        outcome = ToolkitPreferencesStore(Registry()).save(values(), display())
        exported = outcome.as_dict(); exported['values']['TemperatureUnit'] = 999
        exported['operations'][0]['name'] = 'changed'
        self.assertEqual(outcome.values['TemperatureUnit'], 0)
        self.assertEqual(outcome.operations[0]['name'], 'DisplayHexAddress')
        with self.assertRaises(TypeError):
            outcome.values['TemperatureUnit'] = 1

class PreferenceStoreFailureTests(unittest.TestCase):
    def test_write_then_error_is_uncertain_and_is_not_replayed(self):
        error = OSError('reply lost after committed write')
        class UncertainRegistry(Registry):
            def write_value(self, hive, key, name, value):
                super().write_value(hive, key, name, value)
                if name == 'TemperatureUnit':
                    raise error
        registry = UncertainRegistry(); store = ToolkitPreferencesStore(registry)
        outcome = store.save(values(), display())
        self.assertIs(store.last_error, error)
        self.assertFalse(outcome.complete)
        self.assertEqual(registry.data[HKCU, TOOLKIT_KEY, 'TemperatureUnit'], text('0'))
        self.assertEqual(sum(row[0] == 'write' and row[3] == 'TemperatureUnit' for row in registry.calls), 1)
        self.assertEqual(registry.calls[-1][3], 'TemperatureUnit')
        self.assertFalse(outcome.operations[-1]['completed'])

    def test_load_interruption_keeps_the_actual_default_write_prefix(self):
        error = SystemExit(7)
        registry = seeded()
        def interrupt(row):
            if row[0] == 'read':
                raise error
        registry.fault = interrupt; store = ToolkitPreferencesStore(registry)
        with self.assertRaises(SystemExit) as caught:
            store.load(values())
        self.assertIs(caught.exception, error)
        self.assertIs(store.last_error, error)
        self.assertEqual([row[0] for row in registry.calls], ['default', 'default', 'read'])
        self.assertEqual(len(store.last_evidence['default_writes']), 2)
        self.assertTrue(all(row['write_succeeded'] for row in store.last_evidence['default_writes']))


if __name__ == '__main__':
    unittest.main()
