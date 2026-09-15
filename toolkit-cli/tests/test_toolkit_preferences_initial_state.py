import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from cbus_toolkit.toolkit_preferences_initial_state import constructor_state
from cbus_toolkit.toolkit_preferences_store import (
    PREFERENCE_DEFINITIONS, DISPLAY_DEFINITIONS, HKCU, TOOLKIT_KEY,
    RegistryValue, REG_SZ, ToolkitPreferencesStore,
)
from cbus_toolkit.toolkit_preferences_controls import ToolkitPreferenceControls
from cbus_toolkit.toolkit_preferences_cli import read_state
from tests import test_toolkit_preferences_store as store_support

ROOT=Path(__file__).resolve().parents[1]
FIXTURE=ROOT/'research/fixtures/toolkit-preferences-initial-state-vectors.json'
PROBE=ROOT/'research/toolkit_preferences_initial_state_probe.py'


def fixture():return json.loads(FIXTURE.read_text())

def original_probe():
    spec=importlib.util.spec_from_file_location('initial_state_original_probe',PROBE)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


class PreferenceInitialStateTests(unittest.TestCase):
    def test_exact_original_forty_values_order_types_and_five_fallbacks(self):
        actual=constructor_state();expected=fixture()['state']
        self.assertEqual(actual,expected)
        self.assertEqual(list(actual),['format','values','display_values'])
        self.assertEqual(list(actual['values']),[row['name'] for row in fixture()['preferences']])
        self.assertEqual(list(actual['values']),[definition.name for definition in PREFERENCE_DEFINITIONS])
        self.assertEqual(list(actual['display_values']),[name for name,_ in DISPLAY_DEFINITIONS])
        for name,value in actual['values'].items():self.assertIs(type(value),type(expected['values'][name]))
        for value in actual['display_values'].values():self.assertIs(value,False)
        self.assertEqual(len(actual['values']),40)

    def test_current_and_registry_default_are_separate_and_calls_detach(self):
        state=constructor_state()
        self.assertIs(state['values']['ShowProjectManager'],False)
        self.assertIs(next(item.boolean_default for item in PREFERENCE_DEFINITIONS if item.name=='ShowProjectManager'),True)
        state['values']['ShowProjectManager']=True;state['values']['Default Site']='changed'
        state['display_values']['tag_hex']=True;state['extra']='not retained'
        state['format']='changed'
        self.assertEqual(constructor_state(),fixture()['state'])

    def test_existing_reader_and_controls_consume_the_exact_document(self):
        state=constructor_state()
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'state.json';path.write_text(json.dumps(state))
            values,display=read_state(path)
        self.assertEqual(values,state['values']);self.assertEqual(display,state['display_values'])
        editor=ToolkitPreferenceControls(values,display)
        self.assertFalse(editor.as_dict()['storage_applied'])
        self.assertEqual(editor.as_dict()['display_values'],state['display_values'])
        self.assertEqual(state,fixture()['state'])

    def test_empty_store_loads_keep_original_first_second_asymmetry(self):
        state=constructor_state();backend=store_support.Registry();store=ToolkitPreferencesStore(backend)
        first=store.load(state['values'])
        self.assertTrue(first.complete)
        self.assertEqual(dict(first.values),store_support.fixture()['first_load_values'])
        self.assertIs(first.values['ShowProjectManager'],False)
        self.assertEqual(backend.data[HKCU,TOOLKIT_KEY,'ShowProjectManager'],RegistryValue(REG_SZ,b'T\x00r\x00u\x00e\x00\x00\x00'))
        second=store.load(first.values)
        self.assertTrue(second.complete)
        self.assertEqual(dict(second.values),store_support.fixture()['second_load_values'])
        self.assertIs(second.values['ShowProjectManager'],True)
        self.assertEqual(state,fixture()['state'])

    def test_helper_performs_no_file_environment_socket_or_backend_access(self):
        def forbidden(*args,**kwargs):raise AssertionError('unexpected I/O')
        with patch('builtins.open',side_effect=forbidden),patch.object(Path,'open',side_effect=forbidden),\
             patch('socket.create_connection',side_effect=forbidden),patch('os.getenv',side_effect=forbidden),\
             patch('cbus_toolkit.toolkit_preferences_store.ToolkitPreferencesStore',side_effect=forbidden):
            first=constructor_state();second=constructor_state()
        self.assertEqual(first,second);self.assertIsNot(first['values'],second['values'])

    def test_original_probe_rejects_wrong_executable_before_emulator(self):
        module=original_probe()
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'wrong.exe';path.write_bytes(b'not original code')
            with self.assertRaisesRegex(ValueError,'exact Toolkit'):
                module.probe_constructor_state(path)

    def test_package_state_works_with_only_standard_library_and_literal_modules(self):
        import cbus_toolkit.toolkit_preferences_initial_state as initial_module
        package=Path(initial_module.__file__).resolve().parent
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'cbus_toolkit';target.mkdir()
            for name in ('__init__.py','toolkit_preferences_initial_state.py','toolkit_preferences_store.py','toolkit_numeric.py'):
                (target/name).write_bytes((package/name).read_bytes())
            script=("import sys,json;sys.path.insert(0,sys.argv[1]);"
                    "from cbus_toolkit.toolkit_preferences_initial_state import constructor_state;"
                    "print(json.dumps(constructor_state()));"
                    "assert 'unicorn' not in sys.modules and 'pefile' not in sys.modules")
            result=subprocess.run([sys.executable,'-I','-S','-c',script,directory],
                                  text=True,capture_output=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout),fixture()['state'])


@unittest.skipUnless(os.environ.get('CBUS_TOOLKIT_EXE'),'requires exact original Toolkit executable')
class OriginalPreferenceInitialStateTests(unittest.TestCase):
    def test_fresh_original_registers_all_forty_and_proves_layout_and_display_prefix(self):
        result=original_probe().probe_constructor_state(os.environ['CBUS_TOOLKIT_EXE'])
        expected=fixture()
        self.assertTrue(result['passed']);self.assertEqual(result['state'],constructor_state())
        for key in ('preferences','constructor_returns','type_initializer_calls','registration_order','zero_layout_proofs','display_initial_bss'):
            self.assertEqual(result[key],expected[key],key)
        self.assertEqual(len(result['constructor_returns']),40)
        self.assertEqual(len(result['zero_layout_proofs']),3)
        self.assertTrue(result['display_reset_prefix_executed'])
        self.assertEqual(result['registry_calls'],0);self.assertEqual(result['network_calls'],0)
        for key,value in expected['scope'].items():self.assertEqual(result[key],value)
        self.assertEqual(result['original_executable_sha256'],expected['original_executable_sha256'])


if __name__=='__main__':unittest.main()
